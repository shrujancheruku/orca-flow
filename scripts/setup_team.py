#!/usr/bin/env python3
"""Prepare the Linear team: the In Review state, estimates, labels and the initiative.

Dry run by default. Pass --apply to write. Safe to rerun: it only creates what
is missing.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flowlib import cli, github, mapping  # noqa: E402
from flowlib.linear import LinearError  # noqa: E402
from flowlib.workspace import Workspace  # noqa: E402

LABEL_COLORS = {
    "needs-info": "#f2994a",
    "ready-for-agent": "#5e6ad2",
    "ready-for-human": "#26b5ce",
    "risk": "#eb5757",
}
DEFAULT_COLOR = "#95a2b3"
IN_REVIEW_COLOR = "#f2c94c"

STATE_CREATE = """mutation($input: WorkflowStateCreateInput!) {
  workflowStateCreate(input: $input) { success workflowState { id name } } }"""
TEAM_UPDATE = """mutation($id: String!, $input: TeamUpdateInput!) {
  teamUpdate(id: $id, input: $input) { success } }"""
LABEL_CREATE = """mutation($input: IssueLabelCreateInput!) {
  issueLabelCreate(input: $input) { success issueLabel { id name } } }"""
PROJECT_LABEL_CREATE = """mutation($input: ProjectLabelCreateInput!) {
  projectLabelCreate(input: $input) { success projectLabel { id name } } }"""
INITIATIVE_CREATE = """mutation($input: InitiativeCreateInput!) {
  initiativeCreate(input: $input) { success initiative { id name } } }"""


def wanted_labels(cfg: dict, github_labels: list) -> list:
    lab = cfg["labels"]
    names = [lab["needs_info"], lab["ready_for_agent"], lab["ready_for_human"], lab["risk"]]
    names += list(lab.get("workspace", []))
    names += list(lab.get("rename", {}).values())
    names += mapping.map_labels(github_labels, cfg)["labels"]
    seen, out = set(), []
    for n in names:
        if n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


def main() -> None:
    p = cli.parser(__doc__)
    p.add_argument("--skip-github-labels", action="store_true", help="do not read the labels the repo's issues use")
    p.add_argument("--github-cache", help="read GitHub issues from this JSON file (as written by migrate.py)")
    args = p.parse_args()
    cfg = cli.load(args)
    client = cli.client(cfg, args.apply)
    print(cli.mode_line(args.apply))
    try:
        ws = Workspace(client, cfg)
    except LinearError as exc:
        cli.die(str(exc))
    team = ws.team
    states = cfg["states"]

    cli.heading(f"Team {team['key']} ({team['name']})")
    print(f"Triage enabled: {team['triageEnabled']}")
    if not team["triageEnabled"]:
        print("  Triage is off. Turn it on in Team settings > Triage (the wizard covers this).")

    for key in ("triage", "todo", "in_progress", "done", "canceled", "duplicate"):
        if not ws.state_id(states[key]):
            print(f"  missing state {states[key]!r} ({key}); rename an existing state or fix states.{key} in the config")

    in_review = states["in_review"]
    if ws.state_id(in_review):
        print(f"State {in_review!r}: present")
    else:
        progress = ws.states.get(states["in_progress"].lower())
        position = (progress["position"] + 1) if progress else None
        state_input = {"teamId": team["id"], "name": in_review, "type": "started", "color": IN_REVIEW_COLOR}
        if position is not None:
            state_input["position"] = position
        client.mutate("workflowStateCreate", STATE_CREATE, {"input": state_input},
                      f"add state {in_review!r} (started) after {states['in_progress']!r}")

    est_type = cfg["estimate_scale"]["linear_type"]
    if team["issueEstimationType"] != est_type:
        client.mutate("teamUpdate", TEAM_UPDATE, {"id": team["id"], "input": {"issueEstimationType": est_type}},
                      f"set estimate type {team['issueEstimationType']!r} -> {est_type!r}")
    else:
        print(f"Estimate type {est_type!r}: present")

    github_labels = []
    if not args.skip_github_labels:
        # Only labels some issue carries: a repo's unused defaults never reach the workspace.
        if args.github_cache:
            with open(args.github_cache) as f:
                issues = json.load(f)
        else:
            issues = github.fetch_issues(cfg["github_repo"])
        github_labels = sorted({name for issue in issues for name in issue["labels"]})
    cli.heading("Workspace labels")
    for name in wanted_labels(cfg, github_labels):
        if ws.label_id(name):
            print(f"  {name}: present")
            continue
        client.mutate("issueLabelCreate", LABEL_CREATE,
                      {"input": {"name": name, "color": LABEL_COLORS.get(name, DEFAULT_COLOR)}},
                      f"create workspace label {name!r}")

    cli.heading("Project labels")
    for name in cfg["project_labels"].values():
        if ws.project_label_id(name):
            print(f"  {name}: present")
            continue
        client.mutate("projectLabelCreate", PROJECT_LABEL_CREATE, {"input": {"name": name}},
                      f"create project label {name!r}")

    cli.heading("Initiative")
    ini = cfg["initiative"]
    if ini is None:
        print("  none in the config: projects are not grouped under an initiative")
    elif ws.initiative_id(ini["name"]):
        print(f"  {ini['name']}: present")
    else:
        body = {"name": ini["name"], "status": ini.get("status", "Active")}
        if ini.get("description"):
            body["description"] = ini["description"]
        try:
            client.mutate("initiativeCreate", INITIATIVE_CREATE, {"input": body}, f"create initiative {ini['name']!r}")
        except LinearError as exc:
            if "disabled" not in str(exc).lower():
                raise
            cli.die("Initiatives are off in this workspace. Turn them on in Linear's settings "
                    "(they may need a paid plan), or set \"initiative\": null in the config.")

    cli.heading("Summary")
    if args.apply:
        print("Done. Rerun without --apply to confirm nothing is left.")
    else:
        cli.show_planned(client, limit=100)


if __name__ == "__main__":
    main()
