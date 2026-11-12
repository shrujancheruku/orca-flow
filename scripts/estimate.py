#!/usr/bin/env python3
"""Propose `size:` labels (and the `risk` label) for the founder to approve.

  estimate.py propose  reads the open issues, copies any existing `size:` label
                       as the proposal, and asks the `--model` profile (Haiku by default, headless
                       on your Claude subscription) to double-check it or, where there is no
                       label, to size the issue. It writes a proposals file and
                       changes nothing on GitHub.
  estimate.py apply    reads the proposals file and, with --apply, edits only the
                       issues marked "approved": true, through
                       `gh issue edit --add-label` (and --remove-label for an
                       old size label that the new one replaces).

Risk paths and label names come from docs/agents/flow.json.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flowlib import agents, cli, config, estimating, proposals  # noqa: E402
from flowlib import github as gh_mod  # noqa: E402


def save(path: str, cfg: dict, items: list) -> None:
    with open(path, "w") as fh:
        json.dump({"repo": cfg["github_repo"], "proposals": items}, fh, indent=2)
        fh.write("\n")


def propose(args, cfg) -> None:
    gh = gh_mod.Gh(cfg["github_repo"])
    issues = gh.issues(state="open", milestone=args.milestone)
    if args.only:
        wanted = {gh_mod.ticket_number(n) for n in args.only}
        issues = [i for i in issues if i["number"] in wanted]
    elif args.unsized_only:
        issues = [i for i in issues if config.size_from_labels(cfg, i["labels"]) is None]
    issues = issues[: args.limit] if args.limit else issues
    print(f"{len(issues)} issue(s). Asking {args.model} about each; GitHub is not changed.")
    items = []
    if os.path.exists(args.out):
        with open(args.out) as fh:
            items = json.load(fh).get("proposals", [])
    done = {p["number"] for p in items}
    try:
        prof = agents.profile(args.model, cfg["models"])
    except agents.AgentError as exc:
        cli.die(str(exc))
    for issue in issues:
        if issue["number"] in done:
            continue
        ident = f"#{issue['number']}"
        prompt = estimating.build_prompt({"identifier": ident, "title": issue["title"], "description": issue["body"]}, cfg)
        answer = None
        try:
            answer = estimating.parse_answer(agents.ask(prof, prompt, args.timeout))
        except (agents.AgentError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            print(f"  {ident}: no answer ({exc})")
        hints = estimating.risk_hints(f"{issue['title']}\n{issue['body'] or ''}", cfg)
        try:
            item = proposals.make_proposal(issue, cfg, answer, hints)
        except ValueError:
            continue
        items.append(item)
        flag = "" if item["agrees"] is None else ("  agrees" if item["agrees"] else "  DISAGREES")
        print(f"  {ident}: {item['size']} ({item['source']}){' risk' if item['risk'] else ''}{flag}  {item['reason']}")
        save(args.out, cfg, items)
    print(f"\nWrote {args.out}. Set \"approved\": true on the entries you accept (change \"size\" first to override), "
          "then run `estimate.py apply --apply`.")


def apply(args, cfg) -> None:
    gh = gh_mod.Gh(cfg["github_repo"], apply=args.apply)
    print(cli.mode_line(args.apply))
    with open(args.out) as fh:
        items = json.load(fh)["proposals"]
    approved = [p for p in items if p.get("approved") is True]
    print(f"{len(approved)} of {len(items)} proposal(s) approved.")
    existing = {l["name"].lower() for l in gh.labels()}
    needed = list(cfg["labels"]["size"].values()) + [cfg["labels"]["risk"]]
    missing = [n for n in needed if n.lower() not in existing]
    if approved and missing:
        cli.die(f"labels missing on {cfg['github_repo']}: {', '.join(missing)}. Run setup_labels.py --apply first.")
    for p in approved:
        current = gh.issue(p["number"])["labels"]
        edits = proposals.label_edits(p, cfg, current)
        if not edits["add"] and not edits["remove"]:
            print(f"  #{p['number']}: already {p['size']}")
            continue
        gh.write(proposals.edit_args(gh.repo, p["number"], edits),
                 f"#{p['number']}: +{','.join(edits['add']) or '-'} -{','.join(edits['remove']) or '-'}")
    if not args.apply:
        gh.show_planned(limit=200)
    else:
        print(f"Edited {len(gh.done)} issue(s).")


def main() -> None:
    p = cli.parser(__doc__)
    p.add_argument("command", choices=["propose", "apply"])
    p.add_argument("--out", default="estimate-proposals.json", help="proposals file (default: ./estimate-proposals.json)")
    p.add_argument("--model", default="haiku", help="model alias for propose (default haiku)")
    p.add_argument("--milestone", help="only issues in this GitHub Milestone (title)")
    p.add_argument("--unsized-only", action="store_true", help="skip issues that already have a size: label (no double-check)")
    p.add_argument("--limit", type=int, help="ask about at most this many issues")
    p.add_argument("--only", nargs="*", help="only these issues, e.g. 12 13")
    p.add_argument("--timeout", type=int, default=180, help="seconds per model call")
    args = p.parse_args()
    cfg = cli.load(args)
    try:
        (propose if args.command == "propose" else apply)(args, cfg)
    except gh_mod.GitHubError as exc:
        cli.die(str(exc))


if __name__ == "__main__":
    main()
