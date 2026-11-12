"""A small Linear GraphQL client with a dry-run guard.

The API key comes from the macOS Keychain, read inside a subprocess. It is
never printed, logged or put in an error message.

`query()` runs reads. `mutate()` runs writes only when the client was built
with apply=True; otherwise it records the planned write and returns None.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request

API_URL = "https://api.linear.app/graphql"


class LinearError(Exception):
    pass


def read_key(service: str) -> str:
    """Read the key from the Keychain. The value never leaves this process."""
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-a", os.environ.get("USER", ""), "-s", service, "-w"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise LinearError("the `security` tool is missing; this needs macOS Keychain") from exc
    if out.returncode != 0 or not out.stdout.strip():
        raise LinearError(f"no Linear key in the Keychain under service {service!r}. Run wizard/wizard.sh.")
    return out.stdout.strip()


class Planned:
    """One write the dry run would have made."""

    def __init__(self, name: str, variables: dict, describe: str):
        self.name = name
        self.variables = variables
        self.describe = describe

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Planned({self.name}: {self.describe})"


class LinearClient:
    def __init__(self, service: str, apply: bool = False, transport=None, sleep=time.sleep):
        self._service = service
        self._key = None
        self.apply = apply
        self.planned = []
        self.done = []
        self._transport = transport or self._http
        self._sleep = sleep

    def _auth(self) -> str:
        if self._key is None:
            self._key = read_key(self._service)
        return self._key

    def _http(self, payload: bytes) -> dict:
        req = urllib.request.Request(
            API_URL,
            data=payload,
            headers={"Authorization": self._auth(), "Content-Type": "application/json"},
            method="POST",
        )
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as exc:
                body = exc.read().decode(errors="replace")
                if exc.code in (429, 503) and attempt < 4:
                    wait = int(exc.headers.get("Retry-After") or 2 ** (attempt + 1))
                    self._sleep(min(wait, 60))
                    continue
                try:
                    return json.loads(body)
                except ValueError:
                    raise LinearError(f"Linear HTTP {exc.code}") from None
            except urllib.error.URLError as exc:
                if attempt < 4:
                    self._sleep(2 ** (attempt + 1))
                    continue
                raise LinearError(f"cannot reach Linear: {exc.reason}") from None
        raise LinearError("Linear kept refusing the request")

    def _run(self, query: str, variables: dict | None) -> dict:
        payload = json.dumps({"query": query, "variables": variables or {}}).encode()
        data = self._transport(payload)
        errors = data.get("errors")
        if errors:
            def detail(e):
                ext = e.get("extensions") or {}
                extra = ext.get("userPresentableMessage") or ext.get("validationErrors") or ""
                return e.get("message", "?") + (f" ({extra})" if extra else "")
            messages = "; ".join(detail(e) for e in errors)
            raise LinearError(f"Linear error: {messages}")
        return data.get("data") or {}

    def query(self, query: str, variables: dict | None = None) -> dict:
        if query.lstrip().startswith("mutation"):
            raise LinearError("query() is for reads; use mutate() for writes")
        return self._run(query, variables)

    def mutate(self, name: str, query: str, variables: dict, describe: str):
        """Run a write when applying; otherwise record it and return None."""
        if not query.lstrip().startswith("mutation"):
            raise LinearError("mutate() needs a mutation document")
        if not self.apply:
            self.planned.append(Planned(name, variables, describe))
            return None
        data = self._run(query, variables)
        result = data.get(name) or {}
        if result.get("success") is False:
            raise LinearError(f"{name} did not succeed: {describe}")
        self.done.append(Planned(name, variables, describe))
        print(f"  wrote {name}: {describe}", flush=True)
        return result

    def paginate(self, query: str, variables: dict, path: list) -> list:
        """Walk a connection. `path` leads to the node holding nodes/pageInfo."""
        out = []
        after = None
        while True:
            data = self.query(query, dict(variables, after=after))
            node = data
            for key in path:
                node = node[key]
            out.extend(node["nodes"])
            info = node["pageInfo"]
            if not info["hasNextPage"]:
                return out
            after = info["endCursor"]


# Read queries shared by the scripts.

TEAM_QUERY = """
query($id: String!) {
  team(id: $id) {
    id key name triageEnabled issueEstimationType
    states { nodes { id name type position color } }
  }
}
"""

LABELS_QUERY = """
query($after: String) {
  issueLabels(first: 250, after: $after) {
    nodes { id name isGroup team { id } parent { id name } }
    pageInfo { hasNextPage endCursor }
  }
}
"""

PROJECT_LABELS_QUERY = """
query($after: String) {
  projectLabels(first: 250, after: $after) {
    nodes { id name isGroup }
    pageInfo { hasNextPage endCursor }
  }
}
"""

INITIATIVES_QUERY = """
query($after: String) {
  initiatives(first: 100, after: $after) {
    nodes { id name status }
    pageInfo { hasNextPage endCursor }
  }
}
"""

PROJECT_STATUSES_QUERY = """
query($after: String) {
  projectStatuses(first: 50, after: $after) {
    nodes { id name type }
    pageInfo { hasNextPage endCursor }
  }
}
"""

ISSUES_BY_ID_QUERY = """
query($ids: [ID!], $after: String) {
  issues(first: 100, after: $after, filter: { id: { in: $ids } }) {
    nodes { id identifier url }
    pageInfo { hasNextPage endCursor }
  }
}
"""

PROJECTS_BY_ID_QUERY = """
query($ids: [ID!], $after: String) {
  projects(first: 100, after: $after, filter: { id: { in: $ids } }) {
    nodes { id name url slugId }
    pageInfo { hasNextPage endCursor }
  }
}
"""

COMMENTS_BY_ID_QUERY = """
query($ids: [ID!], $after: String) {
  comments(first: 100, after: $after, filter: { id: { in: $ids } }) {
    nodes { id }
    pageInfo { hasNextPage endCursor }
  }
}
"""


def existing_ids(client: LinearClient, query: str, kind: str, ids: list) -> dict:
    """Return {id: node} for the ids that already exist in Linear."""
    found = {}
    for i in range(0, len(ids), 100):
        chunk = ids[i : i + 100]
        for node in client.paginate(query, {"ids": chunk}, [kind]):
            found[node["id"]] = node
    return found
