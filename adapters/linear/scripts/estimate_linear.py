#!/usr/bin/env python3
"""Propose a size (S, M or L) and a risk flag for unestimated tickets.

  estimate_linear.py propose  asks Haiku, headless on your Claude subscription, about
                       each unestimated open ticket and writes the answers to a
                       proposals file. It never touches Linear.
  estimate_linear.py apply    reads the proposals file and, with --apply, sets the
                       estimate (and the risk label) only on entries the
                       founder marked "approved": true.

The estimate scale and the risk paths come from the config.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "scripts"))

from flowlib import agents, estimating  # noqa: E402
from linearlib import cli, mapping  # noqa: E402
from linearlib import linear as L  # noqa: E402
from linearlib.workspace import Workspace  # noqa: E402

UNESTIMATED = """query($team: ID!, $after: String) {
  issues(first: 50, after: $after, filter: {
    team: { id: { eq: $team } }, estimate: { null: true },
    state: { type: { in: ["triage", "backlog", "unstarted"] } } }) {
    nodes { id identifier title description labels { nodes { name } } }
    pageInfo { hasNextPage endCursor } } }"""
ISSUE_UPDATE = """mutation($id: String!, $input: IssueUpdateInput!) {
  issueUpdate(id: $id, input: $input) { success } }"""


def propose(args, cfg) -> None:
    client = cli.client(cfg, apply=False)
    issues = client.paginate(UNESTIMATED, {"team": cfg["team"]["id"]}, ["issues"])
    if args.only:
        wanted = set(args.only)
        issues = [i for i in issues if i["identifier"] in wanted]
    issues = issues[: args.limit] if args.limit else issues
    print(f"{len(issues)} unestimated ticket(s). Asking {args.model} about each; Linear is not changed.")
    proposals = []
    if os.path.exists(args.out):
        with open(args.out) as fh:
            proposals = json.load(fh).get("proposals", [])
    done = {p["identifier"] for p in proposals}
    for issue in issues:
        if issue["identifier"] in done:
            continue
        prompt = estimating.build_prompt(issue, cfg)
        try:
            answer = estimating.parse_answer(agents.ask(agents.profile(args.model, cfg["models"]), prompt, args.timeout), cfg)
        except (agents.AgentError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            print(f"  {issue['identifier']}: no answer ({exc})")
            continue
        hints = estimating.risk_hints(f"{issue['title']}\n{issue.get('description') or ''}", cfg)
        proposals.append({
            "identifier": issue["identifier"],
            "id": issue["id"],
            "title": issue["title"],
            "size": answer["size"],
            "estimate": mapping.size_to_estimate(answer["size"], cfg),
            "risk": answer["risk"],
            "risk_hints": hints,
            "reason": answer["reason"],
            "approved": False,
        })
        print(f"  {issue['identifier']}: {answer['size']}{' risk' if answer['risk'] else ''}  {answer['reason']}")
        with open(args.out, "w") as fh:
            json.dump({"scale": cfg["estimate_scale"], "proposals": proposals}, fh, indent=2)
            fh.write("\n")
    print(f"\nWrote {args.out}. Set \"approved\": true on the entries you accept, then run `estimate_linear.py apply --apply`.")


def apply(args, cfg) -> None:
    client = cli.client(cfg, args.apply)
    print(cli.mode_line(args.apply))
    with open(args.out) as fh:
        proposals = json.load(fh)["proposals"]
    approved = [p for p in proposals if p.get("approved") is True]
    print(f"{len(approved)} of {len(proposals)} proposal(s) approved.")
    risk_id = None
    if any(p["risk"] for p in approved):
        risk_id = Workspace(client, cfg).label_id(cfg["labels"]["risk"])
        if risk_id is None:
            cli.die(f"no {cfg['labels']['risk']!r} label in Linear; run setup_team.py --apply")
    for p in approved:
        body = {"estimate": p["estimate"]}
        if p["risk"]:
            body["addedLabelIds"] = [risk_id]
        client.mutate("issueUpdate", ISSUE_UPDATE, {"id": p["id"], "input": body},
                      f"{p['identifier']} -> {p['size']} ({p['estimate']}){' + risk' if p['risk'] else ''}")
    if not args.apply:
        cli.show_planned(client, limit=200)


def main() -> None:
    p = cli.parser(__doc__)
    p.add_argument("command", choices=["propose", "apply"])
    p.add_argument("--out", default="estimate-proposals.json", help="proposals file (default: ./estimate-proposals.json)")
    p.add_argument("--model", default="haiku", help="model alias for propose (default haiku)")
    p.add_argument("--limit", type=int, help="ask about at most this many tickets")
    p.add_argument("--only", nargs="*", help="only these identifiers, e.g. ABC-12 ABC-13")
    p.add_argument("--timeout", type=int, default=180, help="seconds per claude call")
    args = p.parse_args()
    cfg = cli.load(args)
    try:
        (propose if args.command == "propose" else apply)(args, cfg)
    except L.LinearError as exc:
        cli.die(str(exc))


if __name__ == "__main__":
    main()
