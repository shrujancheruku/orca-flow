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


def locate(worker: dict, root: Path, show) -> list:
    paths = list(worker["transcript_paths"])
    if not paths and worker.get("dispatch_id") and show is not None:
        try:
            detail = show(worker["dispatch_id"])
            paths = orca.find_paths(detail, "transcript", ".jsonl")
            if not worker.get("worktree"):
                worker["worktree"] = orca.first(detail, "worktreePath", "worktree_path", "cwd")
        except orca.OrcaError:
            paths = []
    summaries = [transcripts.summarise_file(p) for p in paths if os.path.exists(p)]
    if not summaries and worker.get("worktree"):
        start, end = parse_ts(worker.get("started_at")), parse_ts(worker.get("ended_at"))
        for p in transcripts.files_for_worktree(worker["worktree"], root):
            s = transcripts.summarise_file(p)
            if transcripts.in_window(s, start, end):
                summaries.append(s)
    return summaries


def main() -> None:
    p = cli.parser(__doc__)
    p.add_argument("--run", required=True, help="Orca Run id")
    p.add_argument("--workers-json", help="read the worker list from this file instead of Orca")
    p.add_argument("--coordinator", help="the coordinator's transcript (.jsonl path)")
    p.add_argument("--merged", default="", help="comma-separated ticket ids (#12,#13) that merged, added to what workers report")
    p.add_argument("--slots", type=int, default=int(os.environ.get("FLOW_SLOTS", "4")), help="worker slots (default 4)")
    p.add_argument("--out", help="JSON output (default profile-<run>.json)")
    p.add_argument("--allow-missing", action="store_true", help="report even when some workers have no transcript")
    p.add_argument("--pr", help="integration PR number to comment the summary on (with --apply)")
    args = p.parse_args()

    if args.workers_json:
        with open(args.workers_json) as fh:
            raw = json.load(fh)
        raw = raw.get("result", raw).get("workers", raw) if isinstance(raw, dict) else raw
        show = None
    else:
        try:
            raw = orca.list_workers(args.run)
        except orca.OrcaError as exc:
            cli.die(str(exc))
        show = orca.show_worker
    if not raw:
        cli.die(f"run {args.run} has no workers (orca orchestration worker-list --run {args.run} --json)")

    # Transcripts are read as Claude's; a worker on another agent shows up as
    # missing until flowlib/agents.py and flowlib/transcripts.py learn it.
    root = agents.transcript_root(agents.DEFAULT_AGENT)
    workers, missing = [], []
    for item in raw:
        w = orca.normalise_worker(item)
        w["transcripts"] = locate(w, root, show)
        if not w["transcripts"]:
            missing.append(w)
        w.pop("raw", None)
        workers.append(w)
    if missing and not args.allow_missing:
        print("No transcript found for these workers:", file=sys.stderr)
        for w in missing:
            print(f"  {w['dispatch_id']} {w['task_title']!r} worktree={w['worktree']!r}", file=sys.stderr)
        print(f"Looked in worker records and {root}/<encoded worktree>/. The transcript location for Orca "
              "chat-surface workers is unverified; find one by hand and fix flowlib/orca.py. "
              "--allow-missing reports anyway.", file=sys.stderr)
        sys.exit(2)

    coordinator = transcripts.summarise_file(args.coordinator) if args.coordinator else None
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
