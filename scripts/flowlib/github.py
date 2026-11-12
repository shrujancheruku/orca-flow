"""Read GitHub through the `gh` CLI. Writes happen only in cutover, under --apply."""

from __future__ import annotations

import json
import subprocess

ISSUES_QUERY = """
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    issues(first: 20, after: $after, orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title body url state stateReason createdAt closedAt
        author { login }
        labels(first: 50) { nodes { name } }
        parent { number }
        subIssues(first: 100) { totalCount nodes { number } }
        blockedBy(first: 50) { nodes { number repository { nameWithOwner } } }
        comments(first: 100) {
          totalCount
          pageInfo { hasNextPage endCursor }
          nodes { id databaseId url createdAt body author { login } }
        }
      }
    }
  }
}
"""

MORE_COMMENTS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      comments(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes { id databaseId url createdAt body author { login } }
      }
    }
  }
}
"""


class GitHubError(Exception):
    pass


def gh(args: list, stdin: str | None = None) -> str:
    try:
        out = subprocess.run(["gh"] + args, input=stdin, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise GitHubError("the gh CLI is missing") from exc
    if out.returncode != 0:
        raise GitHubError(f"gh {' '.join(args[:2])} failed: {out.stderr.strip()[:300]}")
    return out.stdout


def graphql(query: str, **variables) -> dict:
    args = ["api", "graphql", "-f", f"query={query}"]
    for k, v in variables.items():
        if v is None:
            continue
        flag = "-F" if isinstance(v, int) else "-f"
        args += [flag, f"{k}={v}"]
    data = json.loads(gh(args))
    if data.get("errors"):
        raise GitHubError("; ".join(e.get("message", "?") for e in data["errors"]))
    return data["data"]


def _normalise(node: dict) -> dict:
    return {
        "number": node["number"],
        "title": node["title"],
        "body": node.get("body") or "",
        "url": node["url"],
        "state": node["state"],
        "state_reason": node.get("stateReason") or "",
        "created_at": node["createdAt"],
        "closed_at": node.get("closedAt"),
        "author": (node.get("author") or {}).get("login") or "ghost",
        "labels": [l["name"] for l in node["labels"]["nodes"]],
        "parent": (node.get("parent") or {}).get("number"),
        "sub_issues": [s["number"] for s in node["subIssues"]["nodes"]],
        "sub_issue_total": node["subIssues"]["totalCount"],
        "blocked_by": [b["number"] for b in node["blockedBy"]["nodes"]],
        "blocked_by_repos": [(b.get("repository") or {}).get("nameWithOwner", "") for b in node["blockedBy"]["nodes"]],
        "comments": [
            {
                "id": c["id"],
                "database_id": c.get("databaseId"),
                "url": c["url"],
                "created_at": c["createdAt"],
                "body": c.get("body") or "",
                "author": (c.get("author") or {}).get("login") or "ghost",
            }
            for c in node["comments"]["nodes"]
        ],
        "comment_total": node["comments"]["totalCount"],
        "_comments_page": node["comments"]["pageInfo"],
    }


def fetch_issues(repo: str) -> list:
    """Every issue (not PRs) with labels, hierarchy, blocking and all comments."""
    owner, name = repo.split("/")
    issues = []
    after = None
    while True:
        data = graphql(ISSUES_QUERY, owner=owner, name=name, after=after)
        conn = data["repository"]["issues"]
        issues.extend(_normalise(n) for n in conn["nodes"])
        if not conn["pageInfo"]["hasNextPage"]:
            break
        after = conn["pageInfo"]["endCursor"]
    for issue in issues:
        page = issue.pop("_comments_page")
        while page["hasNextPage"]:
            more = graphql(MORE_COMMENTS_QUERY, owner=owner, name=name, number=issue["number"], after=page["endCursor"])
            conn = more["repository"]["issue"]["comments"]
            issue["comments"].extend(
                {
                    "id": c["id"],
                    "database_id": c.get("databaseId"),
                    "url": c["url"],
                    "created_at": c["createdAt"],
                    "body": c.get("body") or "",
                    "author": (c.get("author") or {}).get("login") or "ghost",
                }
                for c in conn["nodes"]
            )
            page = conn["pageInfo"]
        if issue["sub_issue_total"] > len(issue["sub_issues"]):
            raise GitHubError(f"#{issue['number']} has over 100 sub-issues; paging them is not built yet")
        # Keep only blockers from this repo.
        issue["blocked_by"] = [
            n for n, r in zip(issue["blocked_by"], issue.pop("blocked_by_repos")) if not r or r.lower() == repo.lower()
        ]
    return issues


def fetch_pr_numbers(repo: str) -> set:
    out = gh(["pr", "list", "--repo", repo, "--state", "all", "--limit", "5000", "--json", "number"])
    return {p["number"] for p in json.loads(out)}
