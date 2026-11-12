#!/usr/bin/env python3
"""Pick the model and effort for one Orca worker, from the routing table.

The coordinator runs this before every worker-start and passes the flags it
prints. The table is the "## Model routing" section of the repo's
docs/agents/orchestration.md, read fresh each time.

  route_linear.py --role build --ticket ABC-123 --lookup
      reads ABC-123's estimate and labels from Linear (read only)
  route_linear.py --role build --ticket ABC-123 --size S
  route_linear.py --role merge --ticket ABC-123 --variant conflict
  route_linear.py --role review --ticket MVP --risk

Prints JSON: model, effort, the worker-start flags and the task title.
"""

from __future__ import annotations

import json
import os
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "scripts"))

from flowlib import routing  # noqa: E402
from linearlib import cli, mapping  # noqa: E402
from linearlib import linear as L  # noqa: E402

ISSUE = """query($id: String!) { issue(id: $id) { identifier estimate labels { nodes { name } } } }"""


def main() -> None:
    p = cli.parser(__doc__, mutates=False)
    p.add_argument("--role", required=True, choices=routing.ROLES)
    p.add_argument("--ticket", required=True, help="Linear identifier, or a milestone name for review")
    p.add_argument("--size", choices=["S", "M", "L"])
    p.add_argument("--estimate", type=float, help="the ticket's Linear estimate; banded into S, M or L")
    p.add_argument("--risk", action="store_true", help="the ticket (or, for review, the milestone) has risk")
    p.add_argument("--variant", help="a named variant row, e.g. conflict or escalated")
    p.add_argument("--lookup", action="store_true", help="read estimate and risk label from Linear")
    p.add_argument("--doc", help="orchestration doc (default: orchestration_doc in the config)")
    p.add_argument("--shell", action="store_true", help="print only the worker-start flags, shell-quoted")
    args = p.parse_args()
    cfg = cli.load(args)

    size, risk, warnings = args.size, args.risk, []
    if args.estimate is not None:
        size = mapping.estimate_to_size(args.estimate, cfg)
    if args.lookup:
        node = cli.client(cfg, apply=False).query(ISSUE, {"id": args.ticket}).get("issue")
        if not node:
            cli.die(f"{args.ticket} not found in Linear")
        if node["estimate"] is not None:
            size = mapping.estimate_to_size(node["estimate"], cfg)
        names = {l["name"].lower() for l in node["labels"]["nodes"]}
        risk = risk or cfg["labels"]["risk"].lower() in names
    if args.role == "build" and size is None:
        size = "M"
        warnings.append("no estimate: routed as M; run estimate_linear.py so the next dispatch is sized")

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
            "size": size, "risk": risk, "flags": flags,
            "task_title": routing.task_title(args.ticket, args.role, choice),
            "notes": choice["notes"], "warnings": warnings,
        }, indent=2))
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except L.LinearError as exc:
        cli.die(str(exc))
