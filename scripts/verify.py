#!/usr/bin/env python3
"""Check that Linear matches what migrate.py meant to write. Reads only.

For every GitHub issue it checks the mapping file, then the Linear record:
state, labels, project, parent, comment count and blocking relations. For every
map and spec it checks the project, its label, its status type and its
initiative. Exits 1 when anything differs.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flowlib.config import initiative_name  # noqa: E402
from flowlib import cli, github, mapping  # noqa: E402
from flowlib import linear as L  # noqa: E402

ISSUES_DETAIL = """query($ids: [ID!], $after: String) {
  issues(first: 50, after: $after, filter: { id: { in: $ids } }) {
    nodes {
      id identifier state { name } labels { nodes { name } } project { id } parent { id }
      comments(first: 250) { nodes { id } }
      relations(first: 100) { nodes { type relatedIssue { id } } }
    }
    pageInfo { hasNextPage endCursor } } }"""

PROJECTS_DETAIL = """query($ids: [ID!], $after: String) {
  projects(first: 50, after: $after, filter: { id: { in: $ids } }) {
    nodes {
      id name status { type } labels { nodes { name } } initiatives { nodes { name } }
      comments(first: 250) { nodes { id } }
    }
    pageInfo { hasNextPage endCursor } } }"""


def main() -> None:
    p = cli.parser(__doc__, mutates=False)
    p.add_argument("--github-cache", help="read GitHub issues from this JSON file")
    p.add_argument("--mapping", help="mapping file (default: mapping_file in the config)")
    args = p.parse_args()
    cfg = cli.load(args)
    client = cli.client(cfg, apply=False)
    if args.github_cache and os.path.exists(args.github_cache):
        with open(args.github_cache) as fh:
            issues = json.load(fh)
    else:
        issues = github.fetch_issues(cfg["github_repo"])
    plan = mapping.build_plan(issues, cfg)
    mpath = args.mapping or cfg["mapping_file"]
    if not os.path.exists(mpath):
        cli.die(f"no mapping file at {mpath}")
    m = mapping.MappingFile.load(mpath, cfg["github_repo"])
    problems = []

    unmapped = [i["number"] for i in plan["issues"] if not m.issue(i["number"])]
    unmapped += [x["number"] for x in plan["projects"] if not m.project(x["number"])]
    if unmapped:
        problems.append(f"{len(unmapped)} GitHub issues missing from the mapping file: {sorted(unmapped)[:20]}")

    ids = [m.issue(i["number"])["id"] for i in plan["issues"] if m.issue(i["number"])]
    found = L.existing_ids(client, ISSUES_DETAIL, "issues", ids)
    pids = [m.project(x["number"])["id"] for x in plan["projects"] if m.project(x["number"])]
    pfound = L.existing_ids(client, PROJECTS_DETAIL, "projects", pids)
    id_of = {i["number"]: (m.issue(i["number"]) or {}).get("id") for i in plan["issues"]}
    pid_of = {x["number"]: (m.project(x["number"]) or {}).get("id") for x in plan["projects"]}

    blocks_expected = {}
    for r in plan["relations"]:
        blocks_expected.setdefault(r["blocker"], set()).add(id_of.get(r["blocked"]))

    for i in plan["issues"]:
        lid = id_of.get(i["number"])
        node = found.get(lid)
        if node is None:
            if lid:
                problems.append(f"#{i['number']}: not found in Linear")
            continue
        tag = f"#{i['number']} ({node['identifier']})"
        if node["state"]["name"] != i["state"]:
            problems.append(f"{tag}: state {node['state']['name']!r}, expected {i['state']!r}")
        have = {l["name"].lower() for l in node["labels"]["nodes"]}
        want = {l.lower() for l in i["labels"]}
        if not want <= have:
            problems.append(f"{tag}: labels missing {sorted(want - have)}")
        want_project = pid_of.get(i["project_number"]) if i["project_number"] else None
        if (node.get("project") or {}).get("id") != want_project:
            problems.append(f"{tag}: project differs")
        want_parent = id_of.get(i["parent_number"]) if i["parent_number"] else None
        if (node.get("parent") or {}).get("id") != want_parent:
            problems.append(f"{tag}: parent differs")
        if len(node["comments"]["nodes"]) < len(i["comments"]):
            problems.append(f"{tag}: {len(node['comments']['nodes'])} comments, expected {len(i['comments'])}")
        have_blocks = {r["relatedIssue"]["id"] for r in node["relations"]["nodes"] if r["type"] == "blocks"}
        missing = blocks_expected.get(i["number"], set()) - have_blocks
        if missing:
            problems.append(f"{tag}: {len(missing)} blocking relation(s) missing")

    for x in plan["projects"]:
        node = pfound.get(pid_of.get(x["number"]))
        if node is None:
            problems.append(f"project #{x['number']}: not found in Linear")
            continue
        if node["status"]["type"] != x["status_type"]:
            problems.append(f"project #{x['number']}: status {node['status']['type']}, expected {x['status_type']}")
        if x["label"].lower() not in {l["name"].lower() for l in node["labels"]["nodes"]}:
            problems.append(f"project #{x['number']}: label {x['label']!r} missing")
        if initiative_name(cfg) and initiative_name(cfg).lower() not in {n["name"].lower() for n in node["initiatives"]["nodes"]}:
            problems.append(f"project #{x['number']}: not in the initiative")
        if len(node["comments"]["nodes"]) < len(x["comments"]):
            problems.append(f"project #{x['number']}: comments missing")

    print(f"Checked {len(plan['issues'])} issues and {len(plan['projects'])} projects.")
    if problems:
        print(f"{len(problems)} problem(s):")
        for line in problems:
            print(f"  - {line}")
        sys.exit(1)
    print("Linear matches the plan.")


if __name__ == "__main__":
    main()
