#!/usr/bin/env python3
"""Move GitHub issues into Linear.

Maps and specs become projects. Every other issue becomes a Linear issue with
its comments, labels, state, estimate, parent and blocking relations. The
mapping file records each GitHub number's Linear record.

Dry run by default: it reads GitHub and Linear, prints counts and a sample,
and writes nothing. --apply writes, phase by phase, and is safe to rerun:
every record gets a fixed id from its GitHub URL, so a rerun skips what exists.

Run setup_team.py --apply first.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flowlib import cli, github, mapping, refs  # noqa: E402
from flowlib import linear as L  # noqa: E402
from flowlib.workspace import Workspace  # noqa: E402

PHASES = ("projects", "issues", "comments", "relations", "attachments", "relink")

PROJECT_CREATE = """mutation($input: ProjectCreateInput!) {
  projectCreate(input: $input) { success project { id name url } } }"""
LINK_INITIATIVE = """mutation($input: InitiativeToProjectCreateInput!) {
  initiativeToProjectCreate(input: $input) { success } }"""
PROJECT_INITIATIVES = """query($id: String!) { project(id: $id) { initiatives { nodes { id } } } }"""
ISSUE_CREATE = """mutation($input: IssueCreateInput!) {
  issueCreate(input: $input) { success issue { id identifier url } } }"""
COMMENT_CREATE = """mutation($input: CommentCreateInput!) {
  commentCreate(input: $input) { success comment { id } } }"""
RELATION_CREATE = """mutation($input: IssueRelationCreateInput!) {
  issueRelationCreate(input: $input) { success issueRelation { id } } }"""
RELATIONS_BY_ID = """query($ids: [ID!], $after: String) {
  issueRelations(first: 100, after: $after, filter: { id: { in: $ids } }) {
    nodes { id } pageInfo { hasNextPage endCursor } } }"""
ATTACH = """mutation($input: AttachmentCreateInput!) {
  attachmentCreate(input: $input) { success } }"""
ISSUE_UPDATE = """mutation($id: String!, $input: IssueUpdateInput!) {
  issueUpdate(id: $id, input: $input) { success } }"""
COMMENT_UPDATE = """mutation($id: String!, $input: CommentUpdateInput!) {
  commentUpdate(id: $id, input: $input) { success } }"""
PROJECT_UPDATE = """mutation($id: String!, $input: ProjectUpdateInput!) {
  projectUpdate(id: $id, input: $input) { success } }"""


def fetch(cfg: dict, cache: str | None) -> list:
    if cache and os.path.exists(cache):
        with open(cache) as fh:
            return json.load(fh)
    issues = github.fetch_issues(cfg["github_repo"])
    if cache:
        with open(cache, "w") as fh:
            json.dump(issues, fh)
    return issues


def resolve(plan: dict, ws: Workspace, cfg: dict) -> dict:
    """Look up every Linear id the plan needs. Missing ones are listed, not guessed."""
    missing = {"states": set(), "labels": set(), "project_labels": set(), "other": []}
    for issue in plan["issues"]:
        if not ws.state_id(issue["state"]):
            missing["states"].add(issue["state"])
        for name in issue["labels"]:
            if not ws.label_id(name):
                missing["labels"].add(name)
    for project in plan["projects"]:
        if not ws.project_label_id(project["label"]):
            missing["project_labels"].add(project["label"])
        if not ws.project_status_id(project["status_type"]):
            missing["other"].append(f"project status of type {project['status_type']}")
    if not ws.initiative_id(cfg["initiative"]["name"]):
        missing["other"].append(f"initiative {cfg['initiative']['name']!r}")
    return missing


def print_dry_run(summary: dict, plan: dict, existing: dict, missing: dict, sample: int) -> None:
    cli.heading("Counts")
    rows = [
        ("GitHub issues", summary["github_issues"]),
        ("  open", summary["github_open"]),
        ("  comments", summary["github_comments"]),
        ("Linear projects (maps and specs)", summary["linear_projects"]),
        ("Linear issues", summary["linear_issues"]),
        ("  in a project", summary["in_a_project"]),
        ("  with a parent issue", summary["with_parent"]),
        ("  with an estimate", summary["with_estimate"]),
        ("Issue comments", summary["issue_comments"]),
        ("Project comments", summary["project_comments"]),
        ("Blocking relations", summary["relations"]),
        ("Blocking links skipped", summary["skipped_relations"]),
    ]
    for label, value in rows:
        print(f"  {label:<36} {value}")
    print("  States: " + ", ".join(f"{k} {v}" for k, v in sorted(summary["states"].items())))
    print("  Labels used: " + ", ".join(summary["labels_used"]))
    if summary["dropped_labels"]:
        print("  Labels dropped: " + ", ".join(f"{k} ({v})" for k, v in sorted(summary["dropped_labels"].items())))
    if summary["unmapped_labels"]:
        print("  Labels with no rule (kept or dropped per labels.unmapped): "
              + ", ".join(f"{k} ({v})" for k, v in sorted(summary["unmapped_labels"].items())))

    cli.heading("Projects")
    for p in summary["projects"]:
        print(f"  #{p['number']} {p['name']!r}: {p['kind']}, label {p['label']}, {p['status']}, "
              f"{p['children']} issues, {p['comments']} comments")

    cli.heading("Already in Linear (from an earlier run)")
    print(f"  projects {existing['projects']}, issues {existing['issues']}, comments {existing['comments']}")

    cli.heading("Missing in Linear (setup_team.py --apply creates these)")
    any_missing = False
    for key in ("states", "labels", "project_labels"):
        if missing[key]:
            any_missing = True
            print(f"  {key}: " + ", ".join(sorted(missing[key])))
    for item in missing["other"]:
        any_missing = True
        print(f"  {item}")
    if not any_missing:
        print("  nothing")

    cli.heading(f"Sample (first {sample} of each)")
    for p in plan["projects"][:sample]:
        print(f"  project #{p['number']} -> {p['name']!r}")
        print(f"    summary: {p['description'][:160]}")
        print(f"    content: {len(p['content'])} chars, {len(p['children'])} sub-issues on GitHub")
    for i in plan["issues"][:sample]:
        where = f"project #{i['project_number']}" if i["project_number"] else "no project"
        print(f"  issue #{i['number']} {i['title'][:60]!r}")
        print(f"    {i['state']}, labels {i['labels']}, estimate {i['estimate']}, {where}, "
              f"parent {i['parent_number']}, {len(i['comments'])} comments")
    for i in plan["issues"]:
        if i["comments"]:
            print("  first comment head: " + i["comments"][0]["body"].splitlines()[0][:140])
            break
    for r in plan["relations"][:sample]:
        print(f"  relation #{r['blocker']} blocks #{r['blocked']}")
    for s in plan["skipped_relations"][:sample]:
        print(f"  skipped #{s['blocker']} blocks #{s['blocked']}: {s['why']}")


def issue_order(plan: dict) -> list:
    """Parents before children, then by number, so parentId always exists."""
    by_number = {i["number"]: i for i in plan["issues"]}

    def depth(i, seen=()):
        p = i["parent_number"]
        if p is None or p not in by_number or p in seen:
            return 0
        return 1 + depth(by_number[p], seen + (i["number"],))

    return sorted(plan["issues"], key=lambda i: (depth(i), i["number"]))


def main() -> None:
    p = cli.parser(__doc__)
    p.add_argument("--phase", choices=PHASES, action="append", help="run only these phases (repeatable)")
    p.add_argument("--sample", type=int, default=3, help="how many items to show per kind in the dry run")
    p.add_argument("--github-cache", help="read GitHub issues from this JSON file, or write it after fetching")
    p.add_argument("--mapping", help="mapping file path (default: mapping_file in the config)")
    p.add_argument("--no-created-at", action="store_true", help="let Linear stamp creation times")
    p.add_argument("--json", action="store_true", help="print the dry-run summary as JSON too")
    args = p.parse_args()
    cfg = cli.load(args)
    phases = args.phase or list(PHASES)
    client = cli.client(cfg, args.apply)
    print(cli.mode_line(args.apply))

    issues = fetch(cfg, args.github_cache)
    plan = mapping.build_plan(issues, cfg)
    summary = mapping.summarise(plan, issues)

    try:
        ws = Workspace(client, cfg)
    except L.LinearError as exc:
        cli.die(str(exc))
    missing = resolve(plan, ws, cfg)

    existing_projects = L.existing_ids(client, L.PROJECTS_BY_ID_QUERY, "projects", [x["id"] for x in plan["projects"]])
    existing_issues = L.existing_ids(client, L.ISSUES_BY_ID_QUERY, "issues", [x["id"] for x in plan["issues"]])
    all_comments = [c["id"] for x in plan["issues"] + plan["projects"] for c in x["comments"]]
    existing_comments = L.existing_ids(client, L.COMMENTS_BY_ID_QUERY, "comments", all_comments)

    if not args.apply:
        print_dry_run(summary, plan, {"projects": len(existing_projects), "issues": len(existing_issues),
                                      "comments": len(existing_comments)}, missing, args.sample)
        if args.json:
            print(cli.dump(summary))
        return

    if any(missing[k] for k in ("states", "labels", "project_labels")) or missing["other"]:
        cli.die("Linear is missing states, labels or the initiative. Run setup_team.py --apply first.")

    m = mapping.MappingFile.load(args.mapping or cfg["mapping_file"], cfg["github_repo"], cfg["team"]["key"])
    team_id = cfg["team"]["id"]
    initiative_id = ws.initiative_id(cfg["initiative"]["name"])

    if "projects" in phases:
        cli.heading("Projects")
        for proj in plan["projects"]:
            node = existing_projects.get(proj["id"])
            if node is None:
                res = client.mutate("projectCreate", PROJECT_CREATE, {"input": {
                    "id": proj["id"], "name": proj["name"], "description": proj["description"],
                    "content": proj["content"], "teamIds": [team_id],
                    "statusId": ws.project_status_id(proj["status_type"]),
                    "labelIds": [ws.project_label_id(proj["label"])],
                }}, f"project #{proj['number']} {proj['name']!r}")
                node = res["project"]
            m.record_project(proj["number"], node["id"], node["name"], node["url"])
            m.save()
            linked = client.query(PROJECT_INITIATIVES, {"id": node["id"]})["project"]["initiatives"]["nodes"]
            if initiative_id not in {n["id"] for n in linked}:
                client.mutate("initiativeToProjectCreate", LINK_INITIATIVE,
                              {"input": {"projectId": node["id"], "initiativeId": initiative_id}},
                              f"link {proj['name']!r} to the initiative")

    if "issues" in phases:
        cli.heading("Issues")
        for issue in issue_order(plan):
            node = existing_issues.get(issue["id"])
            if node is None:
                body = {
                    "id": issue["id"], "teamId": team_id, "title": issue["title"],
                    "description": issue["description"], "stateId": ws.state_id(issue["state"]),
                    "labelIds": [ws.label_id(n) for n in issue["labels"]],
                }
                if issue["estimate"] is not None:
                    body["estimate"] = issue["estimate"]
                if issue["project_number"] is not None:
                    body["projectId"] = m.project(issue["project_number"])["id"]
                if issue["parent_number"] is not None:
                    body["parentId"] = m.issue(issue["parent_number"])["id"]
                if not args.no_created_at:
                    body["createdAt"] = issue["created_at"]
                    if issue["completed_at"]:
                        body["completedAt"] = issue["completed_at"]
                res = client.mutate("issueCreate", ISSUE_CREATE, {"input": body}, f"issue #{issue['number']}")
                node = res["issue"]
            m.record_issue(issue["number"], node["id"], node["identifier"], node["url"])
            m.save()

    if "comments" in phases:
        cli.heading("Comments")
        targets = [("issueId", m.issue(i["number"]), i) for i in plan["issues"]]
        targets += [("projectId", m.project(x["number"]), x) for x in plan["projects"]]
        for field, rec, owner in targets:
            if rec is None:
                cli.die(f"#{owner['number']} is not in the mapping file; run the issues and projects phases first")
            for c in owner["comments"]:
                if c["id"] not in existing_comments and c["github_id"] not in m.data["comments"]:
                    body = {"id": c["id"], field: rec["id"], "body": c["body"]}
                    if field == "issueId":
                        body["doNotSubscribeToIssue"] = True
                    if not args.no_created_at:
                        body["createdAt"] = c["created_at"]
                    client.mutate("commentCreate", COMMENT_CREATE, {"input": body},
                                  f"comment on #{owner['number']} from {c['created_at'][:10]}")
                m.record_comment(c["github_id"], c["id"])
            m.save()

    if "relations" in phases:
        cli.heading("Blocking relations")
        done = L.existing_ids(client, RELATIONS_BY_ID, "issueRelations", [r["id"] for r in plan["relations"]])
        for r in plan["relations"]:
            if r["id"] not in done:
                client.mutate("issueRelationCreate", RELATION_CREATE, {"input": {
                    "id": r["id"], "type": "blocks",
                    "issueId": m.issue(r["blocker"])["id"], "relatedIssueId": m.issue(r["blocked"])["id"],
                }}, f"#{r['blocker']} blocks #{r['blocked']}")
            m.record_relation(r["id"], r["blocker"], r["blocked"])
        m.save()

    if "attachments" in phases:
        cli.heading("GitHub links")
        # Linear treats a repeat attachment URL on the same issue as an update, so reruns are safe.
        for issue in plan["issues"]:
            client.mutate("attachmentCreate", ATTACH, {"input": {
                "issueId": m.issue(issue["number"])["id"], "url": issue["url"],
                "title": f"GitHub #{issue['number']}",
            }}, f"link #{issue['number']} to GitHub")

    if "relink" in phases:
        cli.heading("Rewrite #N references in Linear bodies")
        table = m.ref_table()
        prs = github.fetch_pr_numbers(cfg["github_repo"])
        repo = cfg["github_repo"]
        for issue in plan["issues"]:
            new = refs.rewrite_text(issue["description"], repo, table, prs)
            if new.changed:
                client.mutate("issueUpdate", ISSUE_UPDATE, {"id": m.issue(issue["number"])["id"],
                              "input": {"description": new.text}}, f"refs in #{issue['number']}")
            for c in issue["comments"]:
                new_c = refs.rewrite_text(c["body"], repo, table, prs)
                if new_c.changed:
                    client.mutate("commentUpdate", COMMENT_UPDATE, {"id": c["id"], "input": {"body": new_c.text}},
                                  f"refs in a comment on #{issue['number']}")
        for proj in plan["projects"]:
            new = refs.rewrite_text(proj["content"], repo, table, prs)
            if new.changed:
                client.mutate("projectUpdate", PROJECT_UPDATE, {"id": m.project(proj["number"])["id"],
                              "input": {"content": new.text}}, f"refs in project #{proj['number']}")
            for c in proj["comments"]:
                new_c = refs.rewrite_text(c["body"], repo, table, prs)
                if new_c.changed:
                    client.mutate("commentUpdate", COMMENT_UPDATE, {"id": c["id"], "input": {"body": new_c.text}},
                                  f"refs in a comment on project #{proj['number']}")

    cli.heading("Done")
    print(f"{len(client.done)} write(s). Mapping file: {m.path}. Next: verify.py.")


if __name__ == "__main__":
    main()
