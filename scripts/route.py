#!/usr/bin/env python3
"""Pick the model and effort for one Orca worker, from the routing table.

The coordinator runs this before every worker-start and passes the flags it
prints. The table is the plugin's defaults with the rows the repo sets in
`routing` in its config laid over them, so a new release changes every row the
repo has not set. docs/agents/orchestration.md holds a copy; this warns when
that copy is out of date.

  route.py --role build --ticket 123 --lookup
      reads #123's `size:` and `risk` labels from GitHub (read only); a risk
      path named in its body raises the model too
  route.py --role build --ticket 123 --size S
  route.py --role build --ticket 123 --size S --paths packages/records/src/a.ts
  route.py --role merge --ticket 123 --variant conflict
  route.py --role review --ticket 45 --risk      (45 is the integration PR)
  route.py --role build --ticket 123 --lookup --wait
      blocks while GitHub cannot be read (a rate limit), then routes

`--lookup` reads GraphQL through the cache the console and status.py share, then REST when GraphQL
fails (REST has its own rate limit), then the last answer it kept. When none answers it exits 75
(EX_TEMPFAIL), not 1, so a caller can tell "try again later" from a bad argument. With `--wait` it
asks again until it can route, for up to --wait-max minutes (default 90: one rate-limit window and
then some), saying each wait on stderr.

Prints JSON: model, effort, the worker-start flags and the task title
(`#123 · build · haiku`).
"""

from __future__ import annotations

import json
import os
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flowlib import cli, ghcache, repofacts, routing  # noqa: E402
from flowlib import github as gh_mod  # noqa: E402


def main() -> None:
    p = cli.parser(__doc__, mutates=False)
    p.add_argument("--role", required=True, choices=routing.ROLES)
    p.add_argument("--ticket", required=True, help="issue number (123 or #123); for review, the integration PR number")
    p.add_argument("--size", choices=["S", "M", "L"])
    p.add_argument("--risk", action="store_true", help="the ticket (or, for review, the milestone) has risk")
    p.add_argument("--paths", nargs="*", default=[], help="paths the ticket touches; a configured risk path raises the model")
    p.add_argument("--variant", help="a named variant row, e.g. conflict or escalated")
    p.add_argument("--lookup", action="store_true", help="read the size and risk labels from GitHub")
    p.add_argument("--wait", action="store_true", help="with --lookup: block until GitHub can be read, then route")
    p.add_argument("--wait-max", type=float, default=90, help="minutes --wait blocks for at most (default 90)")
    p.add_argument("--doc", help="orchestration doc to check for a stale copy (default: orchestration_doc in the config)")
    p.add_argument("--shell", action="store_true", help="print only the worker-start flags, shell-quoted")
    args = p.parse_args()
    cfg = cli.load(args)

    size, risk, reasons, warnings = args.size, args.risk, [], []
    labels, body = [], ""
    if args.lookup:
        try:
            number = gh_mod.ticket_number(args.ticket)
        except gh_mod.GitHubError as exc:
            cli.die(str(exc))
        cached = ghcache.CachedGitHub(gh_mod.Gh(cfg["github_repo"]), ghcache.cache_path("."))
        try:
            if args.wait:
                say = lambda m: print(m, file=sys.stderr, flush=True)  # noqa: E731
                issue, source = ghcache.wait_for_issue(cached, cfg["github_repo"], number, args.wait_max * 60, say)
            else:
                issue, source = ghcache.issue_facts(cached, cfg["github_repo"], number)
        except ghcache.NoGitHub as exc:
            cli.die(f"{exc}; rerun with --wait to block until it can", code=ghcache.EXIT_NO_GITHUB)
        labels, body = issue["labels"], issue["body"]
        if source != "github":
            warnings.append(f"labels read from {source}: GitHub GraphQL was unavailable")
    # run from the repo: short paths and code names in the ticket resolve against HEAD
    facts = routing.ticket_facts(cfg, labels, body, args.paths, tree=repofacts.GitTree(cfg))
    size = size or facts["size"]
    risk = risk or facts["risk"]
    reasons = facts["risk_reasons"]
    if args.role == "build" and size is None:
        size = "M"
        warnings.append("no size: label: routed as M; run estimate.py so the next dispatch is sized")

    try:
        doc_path = args.doc or cfg["orchestration_doc"]
        doc = open(doc_path).read() if os.path.exists(doc_path) else None
        table, stale = routing.resolve(cfg.get("routing"), doc, size_word="size", seed="seed_docs.py")
        warnings += stale
        choice = routing.select(table, args.role, size=size, risk=risk, variant=args.variant)
        flags = routing.worker_flags(choice, cfg["models"])
        if choice.get("effort") and routing.takes_no_effort(choice, cfg["models"]):
            warnings.append(f"row {choice['key']}: {choice['model']} takes no effort, so --effort {choice['effort']} "
                            "is left off (Orca refuses it); clear the row's effort")
    except (OSError, routing.RoutingError) as exc:
        cli.die(str(exc))
    if args.shell:
        print(" ".join(shlex.quote(f) for f in flags))
    else:
        print(json.dumps({
            "row": choice["key"], "model": choice["model"], "effort": choice["effort"],
            "size": size, "risk": risk, "risk_reasons": reasons, "flags": flags,
            "task_title": routing.task_title(args.ticket, args.role, choice),
            "notes": choice["notes"], "warnings": warnings,
        }, indent=2))
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
