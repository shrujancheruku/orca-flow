#!/usr/bin/env python3
"""Read and edit a Linear project's summary and content: the map or spec body.

`orca linear` cannot create projects or edit their content, so wayfinder and
to-spec use this for those steps.

  project_doc.py show <project id or exact name>
  project_doc.py create --name N --summary S --content-file F --kind map|spec [--apply]
  project_doc.py append <project> --section "Decisions so far" --line "- ..." [--apply]
  project_doc.py set-content <project> --content-file F [--apply]
  project_doc.py complete <project> [--apply]

Dry run by default for every write.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flowlib.config import initiative_name  # noqa: E402
from flowlib import cli, mapping  # noqa: E402
from flowlib import linear as L  # noqa: E402
from flowlib.workspace import Workspace  # noqa: E402

FIND = """query($q: String!) {
  projects(first: 5, filter: { or: [ { id: { eq: $q } }, { name: { eqIgnoreCase: $q } }, { slugId: { eq: $q } } ] }) {
    nodes { id name url description content status { name type } labels { nodes { name } } } } }"""
CREATE = """mutation($input: ProjectCreateInput!) {
  projectCreate(input: $input) { success project { id name url } } }"""
UPDATE = """mutation($id: String!, $input: ProjectUpdateInput!) {
  projectUpdate(id: $id, input: $input) { success } }"""
LINK = """mutation($input: InitiativeToProjectCreateInput!) {
  initiativeToProjectCreate(input: $input) { success } }"""


def find(client, ref: str) -> dict:
    nodes = client.query(FIND, {"q": ref})["projects"]["nodes"]
    if len(nodes) != 1:
        cli.die(f"{len(nodes)} projects match {ref!r}; use the project id")
    return nodes[0]


def append_to_section(content: str, section: str, line: str) -> str:
    """Add a line at the end of a level-2 section, creating the section if missing."""
    lines = content.split("\n")
    start = next((i for i, l in enumerate(lines) if l.strip().lower() == f"## {section}".lower()), None)
    if start is None:
        return content.rstrip() + f"\n\n## {section}\n\n{line}\n"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    insert = end
    while insert > start + 1 and not lines[insert - 1].strip():
        insert -= 1
    lines.insert(insert, line)
    return "\n".join(lines)


def main() -> None:
    p = cli.parser(__doc__)
    p.add_argument("command", choices=["show", "create", "append", "set-content", "complete"])
    p.add_argument("project", nargs="?", help="project id, slug or exact name")
    p.add_argument("--name")
    p.add_argument("--summary", help="the one-line summary (a map's Destination)")
    p.add_argument("--content-file", help="markdown file for the content; - for stdin")
    p.add_argument("--kind", choices=["map", "spec"])
    p.add_argument("--section")
    p.add_argument("--line")
    args = p.parse_args()
    cfg = cli.load(args)
    client = cli.client(cfg, args.apply)

    def read_content():
        if not args.content_file:
            cli.die("--content-file is required")
        return sys.stdin.read() if args.content_file == "-" else open(args.content_file).read()

    try:
        if args.command == "show":
            node = find(client, args.project)
            print(f"# {node['name']}  ({node['status']['name']})\n{node['url']}\n\nSummary: {node['description']}\n")
            print(node["content"] or "")
            return
        print(cli.mode_line(args.apply))
        if args.command == "create":
            if not (args.name and args.summary and args.kind):
                cli.die("create needs --name, --summary and --kind")
            ws = Workspace(client, cfg)
            label = mapping.project_label(args.kind, cfg)
            res = client.mutate("projectCreate", CREATE, {"input": {
                "name": args.name, "description": mapping._summary(args.summary), "content": read_content(),
                "teamIds": [cfg["team"]["id"]], "statusId": ws.project_status_id("started"),
                "labelIds": [ws.project_label_id(label)],
            }}, f"create {args.kind} project {args.name!r} labelled {label}")
            if res and initiative_name(cfg):
                client.mutate("initiativeToProjectCreate", LINK, {"input": {
                    "projectId": res["project"]["id"], "initiativeId": ws.initiative_id(initiative_name(cfg))}},
                    "link it to the initiative")
            if res:
                print(res["project"]["url"])
        else:
            node = find(client, args.project)
            if args.command == "append":
                if not (args.section and args.line):
                    cli.die("append needs --section and --line")
                body = {"content": append_to_section(node["content"] or "", args.section, args.line)}
                what = f"append to {args.section!r} in {node['name']!r}"
            elif args.command == "set-content":
                body = {"content": read_content()}
                what = f"replace the content of {node['name']!r}"
            else:
                ws = Workspace(client, cfg)
                body = {"statusId": ws.project_status_id("completed")}
                what = f"mark {node['name']!r} completed"
            client.mutate("projectUpdate", UPDATE, {"id": node["id"], "input": body}, what)
        if not args.apply:
            cli.show_planned(client)
    except L.LinearError as exc:
        cli.die(str(exc))


if __name__ == "__main__":
    main()
