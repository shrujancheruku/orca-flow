"""Read Orca orchestration state through the `orca` CLI.

UNVERIFIED: the JSON field names of worker-list and worker-show were not
seen with a real worker (no run had workers when this was written). The
readers below search the JSON for likely keys and fail loudly when they
find nothing. Confirm on the first real run and pin the names here.
"""

from __future__ import annotations

import json
import subprocess


class OrcaError(Exception):
    pass


def orca(args: list) -> dict:
    try:
        out = subprocess.run(["orca"] + args, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise OrcaError("the orca CLI is missing") from exc
    if out.returncode != 0:
        raise OrcaError(f"orca {' '.join(args[:2])} failed: {out.stderr.strip()[:300]}")
    try:
        data = json.loads(out.stdout)
    except ValueError as exc:
        raise OrcaError(f"orca {' '.join(args[:2])} did not return JSON") from exc
    if isinstance(data, dict) and data.get("ok") is False:
        raise OrcaError(f"orca {' '.join(args[:2])}: {data.get('error')}")
    return data.get("result", data) if isinstance(data, dict) else data


def walk(node, path=()):
    """Yield (key path, value) for every leaf in a JSON tree."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, path + (str(k),))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, path + (str(i),))
    else:
        yield path, node


def first(node: dict, *names):
    """The first leaf whose key matches one of `names` (case-insensitive)."""
    wanted = [n.lower() for n in names]
    for want in wanted:
        for path, value in walk(node):
            if path and path[-1].lower() == want and value not in (None, ""):
                return value
    return None


def find_paths(node: dict, key_hint: str, suffix: str = "") -> list:
    out = []
    for path, value in walk(node):
        if isinstance(value, str) and path and key_hint in path[-1].lower() and value.startswith("/"):
            if not suffix or value.endswith(suffix):
                out.append(value)
    return sorted(set(out))


def normalise_worker(raw: dict) -> dict:
    return {
        "dispatch_id": first(raw, "dispatchId", "dispatch_id", "id"),
        "task_title": first(raw, "taskTitle", "task_title", "title", "displayName") or "",
        "worktree": first(raw, "worktreePath", "worktree_path", "cwd", "path"),
        "started_at": first(raw, "startedAt", "started_at", "createdAt"),
        "ended_at": first(raw, "endedAt", "ended_at", "completedAt", "finishedAt", "updatedAt"),
        "outcome": first(raw, "outcome", "result", "status") or "",
        "transcript_paths": find_paths(raw, "transcript", ".jsonl"),
        "raw": raw,
    }


def list_workers(run_id: str) -> list:
    workers = []
    cursor = None
    while True:
        args = ["orchestration", "worker-list", "--run", run_id, "--json", "--limit", "100"]
        if cursor:
            args += ["--cursor", cursor]
        data = orca(args)
        page = data.get("workers", []) if isinstance(data, dict) else data
        workers.extend(page)
        cursor = data.get("nextCursor") or data.get("cursor") if isinstance(data, dict) else None
        if not cursor or not page:
            return workers


def show_worker(dispatch_id: str) -> dict:
    return orca(["orchestration", "worker-show", "--dispatch", dispatch_id, "--json", "--full"])
