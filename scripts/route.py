#!/usr/bin/env python3
"""Pick the model and effort for one Orca worker, from the routing table.

The coordinator runs this before every worker-start and passes the flags it
prints. The table is the "## Model routing" section of the repo's
docs/agents/orchestration.md, read fresh each time.

  route.py --role build --ticket 123 --lookup
      reads #123's `size:` and `risk` labels from GitHub (read only); a risk
      path named in its body raises the model too
  route.py --role build --ticket 123 --size S
  route.py --role build --ticket 123 --size S --paths packages/records/src/a.ts
  route.py --role merge --ticket 123 --variant conflict
  route.py --role review --ticket 45 --risk      (45 is the integration PR)

Prints JSON: model, effort, the worker-start flags and the task title
(`#123 · build · haiku`).
"""

from __future__ import annotations

import json
import os
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flowlib import cli, routing  # noqa: E402
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
    p.add_argument("--doc", help="orchestration doc (default: orchestration_doc in the config)")
    p.add_argument("--shell", action="store_true", help="print only the worker-start flags, shell-quoted")
    args = p.parse_args()
    cfg = cli.load(args)

    size, risk, reasons, warnings = args.size, args.risk, [], []
    labels, body = [], ""
    if args.lookup:
        try:
            issue = gh_mod.Gh(cfg["github_repo"]).issue(gh_mod.ticket_number(args.ticket))
        except gh_mod.GitHubError as exc:
            cli.die(str(exc))
        labels, body = issue["labels"], issue["body"] or ""
    facts = routing.ticket_facts(cfg, labels, body, args.paths)
    size = size or facts["size"]
    risk = risk or facts["risk"]
    reasons = facts["risk_reasons"]
    if args.role == "build" and size is None:
        size = "M"
        warnings.append("no size: label: routed as M; run estimate.py so the next dispatch is sized")

    try:
        table = routing.parse_table(open(args.doc or cfg["orchestration_doc"]).read())
        choice = routing.select(table, args.role, size=size, risk=risk, variant=args.variant)
        flags = routing.worker_flags(choice, cfg["models"])
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
