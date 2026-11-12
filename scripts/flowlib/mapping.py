"""Pure mapping from GitHub issues to a Linear migration plan.

No I/O here. migrate.py fetches, calls build_plan(), then carries the plan out.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from collections import Counter

ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/linear-orca-flow")

PROJECT_DESCRIPTION_LIMIT = 255
SIZE_LETTERS = ("XS", "S", "M", "L", "XL")


def stable_id(*parts: str) -> str:
    """Same input, same id: reruns find what the last run created."""
    return str(uuid.uuid5(ID_NAMESPACE, "|".join(str(p) for p in parts)))


# ---- classification -------------------------------------------------------


def classify(issue: dict, cfg: dict):
    """Return "map", "spec" or None for a GitHub issue."""
    projects = cfg["projects"]
    for extra in projects.get("extra", []):
        if extra.get("number") == issue["number"]:
            return "map" if extra.get("kind") in ("map", "wayfinder") else "spec"
    labels = {l.lower() for l in issue["labels"]}
    if labels & {l.lower() for l in projects.get("map_labels", [])}:
        return "map"
    title = issue["title"].strip()
    if any(title.startswith(p) for p in projects.get("map_title_prefixes", [])):
        return "map"
    if any(title.startswith(p) for p in projects.get("spec_title_prefixes", [])):
        return "spec"
    return None


def project_label(kind: str, cfg: dict) -> str:
    return cfg["project_labels"]["wayfinder" if kind == "map" else "build"]


def project_name(title: str, cfg: dict) -> str:
    projects = cfg["projects"]
    for prefix in projects.get("map_title_prefixes", []) + projects.get("spec_title_prefixes", []):
        if title.startswith(prefix):
            return title[len(prefix) :].strip()
    return title.strip()


def split_sections(body: str) -> list:
    """Split markdown into [(heading or "", text)] at level-2 headings."""
    sections = []
    heading = ""
    lines = []
    fence = False
    for line in body.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
        m = None if fence else re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            sections.append((heading, "\n".join(lines).strip()))
            heading, lines = m.group(1), []
        else:
            lines.append(line)
    sections.append((heading, "\n".join(lines).strip()))
    return [(h, t) for h, t in sections if h or t]


def _first_paragraph(text: str) -> str:
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if para and not para.startswith("#"):
            return para
    return ""


def _summary(text: str, limit: int = PROJECT_DESCRIPTION_LIMIT) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # links read badly in a summary
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return cut + "…"


def project_fields(issue: dict, cfg: dict) -> dict:
    """Destination goes in the summary; the other sections go in the content."""
    sections = split_sections(issue["body"])
    destination = next((t for h, t in sections if h.lower() == "destination"), None)
    rest = [(h, t) for h, t in sections if h.lower() != "destination"]
    if destination is not None:
        summary = _summary(_first_paragraph(destination) or destination)
        content_parts = []
        if _summary(destination, 10**6) != summary:
            content_parts.append("## Destination\n\n" + destination)
        content_parts += [(f"## {h}\n\n{t}" if h else t) for h, t in rest]
    else:
        # A spec has no Destination: summarise its problem statement, else its opening.
        wanted = [s.lower() for s in cfg["projects"].get("summary_sections", ["Problem Statement"])]
        source = next((t for h, t in rest if h.lower() in wanted), None)
        if source is None:
            source = rest[0][1] if rest else issue["title"]
        summary = _summary(_first_paragraph(source) or issue["title"])
        content_parts = [(f"## {h}\n\n{t}" if h else t) for h, t in rest]
    content = "\n\n".join(p for p in content_parts if p.strip())
    content += "\n\n" + footer(issue)
    return {"name": project_name(issue["title"], cfg), "description": summary, "content": content}


# ---- labels, state, estimate ---------------------------------------------


def size_to_estimate(size: str, cfg: dict):
    sizes = cfg["estimate_scale"]["sizes"]
    size = size.upper()
    if size in sizes:
        return sizes[size]
    if size == "XS":
        return sizes["S"]
    if size == "XL":
        return sizes["L"]
    return None


def estimate_to_size(estimate, cfg: dict):
    """Band an estimate into S, M or L. None stays None."""
    if estimate is None:
        return None
    sizes = cfg["estimate_scale"]["sizes"]
    if estimate <= sizes["S"]:
        return "S"
    if estimate <= sizes["M"]:
        return "M"
    return "L"


def map_labels(labels: list, cfg: dict) -> dict:
    """Map GitHub label names to Linear label names.

    Returns {"labels": [...], "estimate": n|None, "dropped": [...], "unmapped": [...]}.
    """
    lab = cfg["labels"]
    retired = {l.lower() for l in lab.get("retired", [])}
    rename = {k.lower(): v for k, v in lab.get("rename", {}).items()}
    known = {
        lab["needs_info"].lower(),
        lab["ready_for_agent"].lower(),
        lab["ready_for_human"].lower(),
        lab["risk"].lower(),
    } | {l.lower() for l in lab.get("workspace", [])}
    prefix = lab.get("wayfinder_prefix", "wayfinder:").lower()
    size_prefix = lab.get("size_prefix", "size:").lower()
    out, dropped, unmapped = [], [], []
    estimate = None
    for name in labels:
        low = name.lower()
        if low in retired:
            dropped.append(name)
        elif low in rename:
            out.append(rename[low])
        elif low.startswith(size_prefix):
            est = size_to_estimate(name[len(size_prefix) :], cfg)
            if est is None:
                unmapped.append(name)
            else:
                estimate = est
                dropped.append(name)
        elif low in known or low.startswith(prefix):
            out.append(name)
        elif lab.get("unmapped") == "keep":
            out.append(name)
            unmapped.append(name)
        else:
            dropped.append(name)
            unmapped.append(name)
    seen = set()
    deduped = [l for l in out if not (l.lower() in seen or seen.add(l.lower()))]
    return {"labels": deduped, "estimate": estimate, "dropped": dropped, "unmapped": unmapped}


def issue_state(issue: dict, cfg: dict, in_project: bool) -> str:
    """Return a state key from cfg["states"] for one issue."""
    if issue["state"] == "CLOSED":
        reason = (issue.get("state_reason") or "").upper()
        if reason == "NOT_PLANNED":
            return "canceled"
        if reason == "DUPLICATE":
            return "duplicate"
        return "done"
    lab = cfg["labels"]
    labels = {l.lower() for l in issue["labels"]}
    if lab["needs_info"].lower() in labels:
        return "triage"
    if labels & {lab["ready_for_agent"].lower(), lab["ready_for_human"].lower()}:
        return "todo"
    prefix = lab.get("wayfinder_prefix", "wayfinder:").lower()
    retired = {l.lower() for l in lab.get("retired", [])}
    if any(l.startswith(prefix) and l not in retired for l in labels):
        return "todo"
    if in_project:
        return "todo"
    return "triage"


# ---- bodies ---------------------------------------------------------------


def footer(issue: dict) -> str:
    return f"_Moved from GitHub {issue['url']}, opened by @{issue['author']} on {issue['created_at'][:10]}._"


def issue_description(issue: dict) -> str:
    body = issue["body"].rstrip()
    return (body + "\n\n" if body else "") + footer(issue)


def comment_body(comment: dict) -> str:
    head = f"**@{comment['author']}** on GitHub, {comment['created_at'][:10]} ([original]({comment['url']})):"
    return head + "\n\n" + comment["body"]


# ---- the plan -------------------------------------------------------------


def build_plan(issues: list, cfg: dict) -> dict:
    """Turn fetched GitHub issues into the full list of Linear writes."""
    by_number = {i["number"]: i for i in issues}
    kinds = {i["number"]: classify(i, cfg) for i in issues}
    project_numbers = {n for n, k in kinds.items() if k}

    def parent_of(n):
        p = by_number[n].get("parent")
        return p if p in by_number else None

    def project_for(n):
        seen = set()
        p = parent_of(n)
        while p is not None and p not in seen:
            if p in project_numbers:
                return p
            seen.add(p)
            p = parent_of(p)
        return None

    projects, planned_issues, relations, skipped = [], [], [], []
    unmapped, dropped = Counter(), Counter()
    states = cfg["states"]

    for issue in sorted(issues, key=lambda i: i["number"]):
        n = issue["number"]
        if n in project_numbers:
            kind = kinds[n]
            fields = project_fields(issue, cfg)
            projects.append(
                {
                    "number": n,
                    "kind": kind,
                    "id": stable_id(issue["url"], "project"),
                    "url": issue["url"],
                    "label": project_label(kind, cfg),
                    "status_type": "completed" if issue["state"] == "CLOSED" else "started",
                    "children": [c for c in issue["sub_issues"] if c in by_number],
                    "comments": _plan_comments(issue),
                    **fields,
                }
            )
            continue
        project = project_for(n)
        direct = parent_of(n)
        mapped = map_labels(issue["labels"], cfg)
        unmapped.update(mapped["unmapped"])
        dropped.update(mapped["dropped"])
        state_key = issue_state(issue, cfg, in_project=project is not None)
        planned_issues.append(
            {
                "number": n,
                "id": stable_id(issue["url"]),
                "url": issue["url"],
                "title": issue["title"],
                "description": issue_description(issue),
                "state_key": state_key,
                "state": states[state_key],
                "labels": mapped["labels"],
                "estimate": mapped["estimate"],
                "project_number": project,
                "parent_number": direct if direct is not None and direct not in project_numbers else None,
                "created_at": issue["created_at"],
                "completed_at": issue.get("closed_at") if state_key == "done" else None,
                "comments": _plan_comments(issue),
            }
        )

    _unique_project_names(projects, cfg)

    issue_numbers = {i["number"] for i in planned_issues}
    seen_pairs = set()
    for issue in issues:
        for blocker in issue.get("blocked_by", []):
            pair = (blocker, issue["number"])
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            if blocker in issue_numbers and issue["number"] in issue_numbers:
                relations.append({"id": stable_id("blocks", blocker, issue["number"]), "blocker": blocker, "blocked": issue["number"]})
            else:
                skipped.append({"blocker": blocker, "blocked": issue["number"], "why": "one side is a project or outside the repo"})
    relations.sort(key=lambda r: (r["blocked"], r["blocker"]))

    return {
        "projects": projects,
        "issues": planned_issues,
        "relations": relations,
        "skipped_relations": skipped,
        "unmapped_labels": dict(unmapped),
        "dropped_labels": dict(dropped),
    }


def _unique_project_names(projects: list, cfg: dict) -> None:
    """Config names win; otherwise a clash gets "(map)" or "(spec)" added."""
    names = {str(k): v for k, v in cfg["projects"].get("names", {}).items()}
    for p in projects:
        if str(p["number"]) in names:
            p["name"] = names[str(p["number"])]
    counts = Counter(p["name"].lower() for p in projects)
    for p in projects:
        if counts[p["name"].lower()] > 1 and str(p["number"]) not in names:
            p["name"] = f"{p['name']} ({p['kind']})"


def _plan_comments(issue: dict) -> list:
    return [
        {
            "id": stable_id(c["url"] or c["id"]),
            "github_id": c["id"],
            "body": comment_body(c),
            "created_at": c["created_at"],
        }
        for c in sorted(issue["comments"], key=lambda c: c["created_at"])
    ]


def needed_labels(plan: dict) -> set:
    names = set()
    for i in plan["issues"]:
        names.update(i["labels"])
    return names


def summarise(plan: dict, issues: list) -> dict:
    """Counts for the dry run."""
    states = Counter(i["state"] for i in plan["issues"])
    open_count = sum(1 for i in issues if i["state"] == "OPEN")
    issue_comments = sum(len(i["comments"]) for i in plan["issues"])
    project_comments = sum(len(p["comments"]) for p in plan["projects"])
    return {
        "github_issues": len(issues),
        "github_open": open_count,
        "github_comments": sum(len(i["comments"]) for i in issues),
        "linear_issues": len(plan["issues"]),
        "linear_projects": len(plan["projects"]),
        "issue_comments": issue_comments,
        "project_comments": project_comments,
        "states": dict(states),
        "with_estimate": sum(1 for i in plan["issues"] if i["estimate"] is not None),
        "in_a_project": sum(1 for i in plan["issues"] if i["project_number"] is not None),
        "with_parent": sum(1 for i in plan["issues"] if i["parent_number"] is not None),
        "relations": len(plan["relations"]),
        "skipped_relations": len(plan["skipped_relations"]),
        "labels_used": sorted(needed_labels(plan)),
        "unmapped_labels": plan["unmapped_labels"],
        "dropped_labels": plan["dropped_labels"],
        "projects": [
            {
                "number": p["number"],
                "kind": p["kind"],
                "name": p["name"],
                "status": p["status_type"],
                "label": p["label"],
                "children": sum(1 for i in plan["issues"] if i["project_number"] == p["number"]),
                "comments": len(p["comments"]),
            }
            for p in plan["projects"]
        ],
    }


# ---- the mapping file -----------------------------------------------------


class MappingFile:
    """GitHub number -> Linear record. Saved after every write, so reruns resume."""

    VERSION = 1

    def __init__(self, path: str, repo: str = "", team_key: str = ""):
        self.path = path
        self.data = {
            "version": self.VERSION,
            "github_repo": repo,
            "team_key": team_key,
            "issues": {},
            "projects": {},
            "comments": {},
            "relations": {},
        }

    @classmethod
    def load(cls, path: str, repo: str = "", team_key: str = "") -> "MappingFile":
        m = cls(path, repo, team_key)
        if os.path.exists(path):
            with open(path) as fh:
                loaded = json.load(fh)
            if loaded.get("version") != cls.VERSION:
                raise ValueError(f"{path}: mapping file version {loaded.get('version')} is not {cls.VERSION}")
            if repo and loaded.get("github_repo") and loaded["github_repo"] != repo:
                raise ValueError(f"{path} belongs to {loaded['github_repo']}, not {repo}")
            for key in m.data:
                if key in loaded:
                    m.data[key] = loaded[key]
        return m

    def save(self) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        with os.fdopen(fd, "w") as fh:
            json.dump(self.data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, self.path)

    def record_issue(self, number: int, linear_id: str, identifier: str, url: str) -> None:
        self.data["issues"][str(number)] = {"id": linear_id, "identifier": identifier, "url": url}

    def record_project(self, number: int, linear_id: str, name: str, url: str) -> None:
        self.data["projects"][str(number)] = {"id": linear_id, "name": name, "url": url}

    def record_comment(self, github_id: str, linear_id: str) -> None:
        self.data["comments"][github_id] = linear_id

    def record_relation(self, rel_id: str, blocker: int, blocked: int) -> None:
        self.data["relations"][rel_id] = [blocker, blocked]

    def issue(self, number: int):
        return self.data["issues"].get(str(number))

    def project(self, number: int):
        return self.data["projects"].get(str(number))

    def ref_table(self) -> dict:
        """{number: {"kind", "label", "url"}} for rewrite_refs."""
        table = {}
        for n, rec in self.data["issues"].items():
            table[int(n)] = {"kind": "issue", "label": rec["identifier"], "url": rec["url"]}
        for n, rec in self.data["projects"].items():
            table[int(n)] = {"kind": "project", "label": rec["name"], "url": rec["url"]}
        return table
