"""GitHub through the `gh` CLI, with a dry-run guard.

`Gh.read()` runs only read commands and refuses anything else. `Gh.write()`
runs a write only when the client was built with apply=True; otherwise it
records the planned write and returns None. Orca has no GitHub issue commands,
so every issue, label and PR call in this plugin goes through here or through
the agent's own `gh`.
"""

from __future__ import annotations

import json
import subprocess

READ_COMMANDS = {
    ("label", "list"),
    ("issue", "list"),
    ("issue", "view"),
    ("pr", "list"),
    ("pr", "view"),
    ("repo", "view"),
    ("auth", "status"),
}
API_WRITE_FLAGS = {"-X", "--method", "-f", "-F", "--field", "--raw-field", "--input"}


# Pages of 50: each issue carries up to 5 PRs with up to 100 files, and GitHub
# caps the nodes one query may ask for.
CLOSED_WITH_PRS = """query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    issues(states: CLOSED, first: 50, after: $cursor, orderBy: {field: CREATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title body stateReason
        labels(first: 30) { nodes { name } }
        closedByPullRequestsReferences(first: 5, includeClosedPrs: false) {
          nodes {
            number merged additions deletions changedFiles
            closingIssuesReferences(first: 10) { totalCount }
            files(first: 100) { nodes { path additions deletions } }
          }
        }
      }
    }
  }
}"""


class GitHubError(Exception):
    pass


def run_gh(args: list, stdin: str | None = None) -> str:
    try:
        out = subprocess.run(["gh"] + args, input=stdin, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise GitHubError("the gh CLI is missing") from exc
    if out.returncode != 0:
        raise GitHubError(f"gh {' '.join(args[:2])} failed: {out.stderr.strip()[:300]}")
    return out.stdout


def is_read(args: list) -> bool:
    if args[:2] == ["api", "graphql"]:
        # GraphQL sends its query and variables as -f/-F fields, so the field
        # flags don't mean a write here; a mutation, or a method override, does.
        if {"-X", "--method", "--input"} & set(args[2:]):
            return False
        return not any(a.startswith("query=") and a[6:].lstrip().startswith("mutation") for a in args[2:])
    if len(args) >= 1 and args[0] == "api":
        return not (API_WRITE_FLAGS & set(args[1:]))
    return len(args) >= 2 and (args[0], args[1]) in READ_COMMANDS


class Planned:
    def __init__(self, args: list, describe: str):
        self.args = args
        self.describe = describe

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Planned({self.describe})"


class Gh:
    def __init__(self, repo: str, apply: bool = False, runner=run_gh):
        self.repo = repo
        self.apply = apply
        self._run = runner
        self.planned = []
        self.done = []

    def read(self, args: list) -> str:
        if not is_read(args):
            raise GitHubError(f"refusing to run `gh {' '.join(args[:2])}` as a read")
        return self._run(args)

    def read_json(self, args: list):
        return json.loads(self.read(args) or "null")

    def write(self, args: list, describe: str, stdin: str | None = None):
        if not self.apply:
            self.planned.append(Planned(args, describe))
            return None
        out = self._run(args, stdin) if stdin is not None else self._run(args)
        self.done.append(describe)
        return out

    # reads

    def labels(self) -> list:
        return self.read_json(["label", "list", "--repo", self.repo, "--limit", "1000",
                               "--json", "name,color,description"])

    def issues(self, state: str = "open", milestone: str | None = None, limit: int = 1000) -> list:
        args = ["issue", "list", "--repo", self.repo, "--state", state, "--limit", str(limit),
                "--json", "number,title,body,labels,state,assignees,milestone"]
        if milestone:
            args += ["--milestone", milestone]
        issues = self.read_json(args)
        for i in issues:
            i["labels"] = [l["name"] for l in i["labels"]]
        return issues

    def issue(self, number: int) -> dict:
        i = self.read_json(["issue", "view", str(number), "--repo", self.repo,
                            "--json", "number,title,body,labels,state,assignees,milestone"])
        i["labels"] = [l["name"] for l in i["labels"]]
        return i

    def closed_with_prs(self, limit: int = 1000) -> list:
        """Closed issues with the PRs that closed them and each PR's per-file line counts.

        Raw GraphQL nodes; flowlib/backtest.py picks the usable ones.
        """
        owner, name = self.repo.split("/")
        nodes, cursor = [], None
        while len(nodes) < limit:
            args = ["api", "graphql", "-f", f"query={CLOSED_WITH_PRS}", "-f", f"owner={owner}", "-f", f"name={name}"]
            if cursor:
                args += ["-f", f"cursor={cursor}"]
            page = self.read_json(args)["data"]["repository"]["issues"]
            nodes += page["nodes"]
            if not page["pageInfo"]["hasNextPage"]:
                break
            cursor = page["pageInfo"]["endCursor"]
        return nodes[:limit]

    # the command lines for writes, kept pure so tests can pin them

    def show_planned(self, limit: int = 50) -> None:
        if not self.planned:
            print("No GitHub writes needed.")
            return
        print(f"{len(self.planned)} GitHub write(s) planned:")
        for p in self.planned[:limit]:
            print(f"  - {p.describe}")
        if len(self.planned) > limit:
            print(f"  ... and {len(self.planned) - limit} more")


def ticket_number(ref) -> int:
    """123, "123" or "#123" -> 123."""
    text = str(ref).strip().lstrip("#")
    if not text.isdigit():
        raise GitHubError(f"{ref!r} is not an issue number like 123 or #123")
    return int(text)
