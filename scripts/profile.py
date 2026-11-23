#!/usr/bin/env python3
"""Cost profile of one Orca run.

  profile.py --run <run id>

Lists the run's workers (orca orchestration worker-list --run --json), finds
each worker's Claude transcripts, counts usage once per API message and prices
it at API list prices as a proxy. Writes JSON and a self-contained HTML viewer:
cost per merged ticket by model and role, escalations, review rounds and
round-one approval, slot use and the coordinator's context growth.

UNVERIFIED: where Orca's chat-surface workers write transcripts. The locator
tries, in order: transcript paths in the worker record (worker-show --full),
then ~/.claude/projects/<encoded worktree path>/. When a worker yields nothing
it stops with the list, rather than report a cost that is too low.

Tickets are `#N` issue numbers, read from the Orca task titles (`#123 · build · haiku`).

--pr <number> --apply posts the short summary as a comment on that pull request
(`gh pr comment`); the coordinator runs it on the milestone's integration PR.
Without --apply it prints the summary only.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flowlib import agents, cli, orca, prices, profiler, routing, transcripts  # noqa: E402
from flowlib import github as gh_mod  # noqa: E402
from flowlib.transcripts import parse_ts  # noqa: E402

VIEWER = Path(__file__).resolve().parent.parent / "viewer" / "profile.html"
MERGED_WORDS = ("merged", "success", "succeeded", "done", "completed", "landed")


def locate(workers: list, root: Path) -> None:
    """Fill each worker's `transcripts` from the sessions in its worktree, each message counted once."""
    files = {}
    for worktree in {w.get("worktree") for w in workers if w.get("worktree")}:
        for path in transcripts.files_for_worktree(worktree, root):
            files.setdefault((worktree, transcripts.session_of(path)), []).append(path)
    sessions = []
    for (worktree, session), paths in files.items():
        firsts = [f for f in (transcripts.summarise_file(p).get("first_at") for p in paths) if f]
        sessions.append({"session": session, "worktree": worktree, "first_at": min(firsts) if firsts else None})
    owned = transcripts.assign(workers, sessions)
    for w in workers:
        w["transcripts"] = []
        for session, start, end in owned.get(w["dispatch_id"], []):
            for path in files[(w["worktree"], session)]:
                summary = transcripts.summarise_file(path, start, end)
                if summary["messages"]:
                    w["transcripts"].append(summary)


def inherit_titles(workers: list) -> None:
    """A follow-up sent to a worker has a free-text title; it takes the title of the worker it continues."""
    by_id = {w["dispatch_id"]: w for w in workers}
    for w in workers:
        cur, seen = w, set()
        while routing.parse_task_title(cur.get("task_title", "")) is None and cur.get("follow_up_of") in by_id \
                and cur["dispatch_id"] not in seen:
            seen.add(cur["dispatch_id"])
            cur = by_id[cur["follow_up_of"]]
        if cur is not w and routing.parse_task_title(cur.get("task_title", "")):
            w["subject"], w["task_title"] = w.get("task_title", ""), cur["task_title"]


def main() -> None:
    p = cli.parser(__doc__)
    p.add_argument("--run", required=True, help="Orca Run id")
    p.add_argument("--workers-json", help="read the worker list from this file instead of Orca")
    p.add_argument("--coordinator", action="extend", nargs="+", metavar="PATH",
                   help="the coordinator's transcript(s) (.jsonl paths); repeat the flag or list several for a run "
                        "that spanned several coordinator sessions")
    p.add_argument("--merged", default="", help="comma-separated ticket ids (#12,#13) that merged, added to what workers report")
    p.add_argument("--slots", type=int, default=int(os.environ.get("FLOW_SLOTS", "4")), help="worker slots (default 4)")
    p.add_argument("--out", help="JSON output (default profile-<run>.json)")
    p.add_argument("--allow-missing", action="store_true", help="report even when some workers have no transcript")
    p.add_argument("--pr", help="integration PR number to comment the summary on (with --apply)")
    args = p.parse_args()

    # Checked before any Orca read: a path with no usage would otherwise drop the coordinator from the total silently.
    coordinator = None
    if args.coordinator:
        coordinator, missing_coordinator = transcripts.summarise_files(args.coordinator)
        if missing_coordinator and not args.allow_missing:
            cli.die("no coordinator usage in: " + ", ".join(missing_coordinator)
                    + " (check the path; --allow-missing counts the rest)")

    titles, show = {}, None
    if args.workers_json:
        with open(args.workers_json) as fh:
            raw = json.load(fh)
        raw = raw.get("result", raw).get("workers", raw) if isinstance(raw, dict) else raw
    else:
        try:
            raw = orca.list_workers(args.run)
            titles = orca.list_tasks(args.run)
        except orca.OrcaError as exc:
            cli.die(str(exc))
        show = orca.show_worker
    if not raw:
        cli.die(f"run {args.run} has no workers (orca orchestration worker-list --run {args.run} --json)")

    # Transcripts are read as Claude's; a worker on another agent shows up as
    # missing until flowlib/agents.py and flowlib/transcripts.py learn it.
    root = agents.transcript_root(agents.DEFAULT_AGENT)
    workers = []
    for item in raw:
        detail = None
        if show is not None and item.get("dispatchId"):
            try:
                detail = show(item["dispatchId"])
            except orca.OrcaError:
                detail = None
        w = orca.worker_record(item, detail, titles)
        w.pop("raw", None)
        workers.append(w)
    inherit_titles(workers)
    locate(workers, root)
    # A follow-up that only relayed a message may have no API message of its own.
    missing = [w for w in workers if not w["transcripts"] and not w.get("follow_up_of")]
    if missing and not args.allow_missing:
        print("No transcript found for these workers:", file=sys.stderr)
        for w in missing:
            print(f"  {w['dispatch_id']} {w['task_title']!r} worktree={w['worktree']!r}", file=sys.stderr)
        print(f"Looked in worker records and {root}/<encoded worktree>/. The transcript location for Orca "
              "chat-surface workers is unverified; find one by hand and fix flowlib/orca.py. "
              "--allow-missing reports anyway.", file=sys.stderr)
        sys.exit(2)

    merged = {routing.ticket_id(t) for t in args.merged.split(",") if t.strip()}
    for w in workers:
        title = w["task_title"] or ""
        if "· merge ·" in title and any(word in (w["outcome"] or "").lower() for word in MERGED_WORDS):
            merged.add(title.split("·")[0].strip())
    profile = profiler.build_profile(args.run, workers, coordinator, sorted(merged), args.slots)
    profile["prices_as_of"] = prices.PRICES_AS_OF
    profile["prices_source"] = prices.PRICES_SOURCE
    profile["missing_transcripts"] = [w["dispatch_id"] for w in missing]

    out = Path(args.out or f"profile-{args.run}.json")
    out.write_text(json.dumps(profile, indent=2, default=str) + "\n")
    html = out.with_suffix(".html")
    html.write_text(VIEWER.read_text().replace("/*PROFILE_DATA*/null", json.dumps(profile, default=str)))
    print(f"Wrote {out} and {html}.")
    body = profiler.summary_body(profile, prices.PRICES_AS_OF)
    print("\n" + body)

    if args.pr:
        cfg = cli.load(args)
        gh = gh_mod.Gh(cfg["github_repo"], apply=args.apply)
        try:
            gh.write(["pr", "comment", str(gh_mod.ticket_number(args.pr)), "--repo", gh.repo, "--body-file", "-"],
                     f"comment the run summary on PR #{gh_mod.ticket_number(args.pr)}", stdin=body)
        except gh_mod.GitHubError as exc:
            cli.die(str(exc))
        if args.apply:
            print(f"Commented on PR #{args.pr}.")
        else:
            gh.show_planned()

if __name__ == "__main__":
    main()
