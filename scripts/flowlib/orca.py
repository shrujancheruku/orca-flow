"""Read Orca orchestration state through the `orca` CLI.

Field names were pinned on the first real run (Orca, 2026-11):

  worker-list   dispatchId, taskId, state, workspace ("<repo id>::<worktree path>")
  task-list     id, title: the task title lives here, not on the worker
  worker-show   dispatch.dispatchedAt ("YYYY-MM-DD HH:MM:SS", UTC), dispatch.completedAt,
                dispatch.followUpOf (set when `orchestration send` continued a worker),
                projection.outcome

No record carries a transcript path, so transcripts are found by worktree
(flowlib/transcripts.py). The key-guessing readers below stay as a fallback
for a worker list read from a file.
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


def list_tasks(run_id: str) -> dict:
    """{task id: title} for a run."""
    data = orca(["orchestration", "task-list", "--run", run_id, "--json"])
    tasks = data.get("tasks", []) if isinstance(data, dict) else data
    return {t["id"]: t.get("title") or "" for t in tasks if isinstance(t, dict) and t.get("id")}


def utc(value):
    """Orca's "2026-11-22 05:10:40" (UTC, no zone) as ISO; an ISO value is returned as it is."""
    if isinstance(value, str) and len(value) == 19 and value[10] == " ":
        return value.replace(" ", "T") + "+00:00"
    return value


def worker_record(raw: dict, detail: dict | None = None, titles: dict | None = None) -> dict:
    """One worker with the pinned field names, falling back to the guesses in normalise_worker."""
    w = normalise_worker(raw)
    detail = detail or {}
    dispatch = detail.get("dispatch") or {}
    title = (titles or {}).get(raw.get("taskId"))
    if title:
        w["task_title"] = title
    workspace = raw.get("workspace") or (detail.get("worker") or {}).get("worktreeId") or ""
    if "::" in workspace:
        w["worktree"] = workspace.split("::", 1)[1]
    w["started_at"] = utc(dispatch.get("dispatchedAt")) or w["started_at"]
    w["ended_at"] = utc(dispatch.get("completedAt")) or w["ended_at"]
    w["follow_up_of"] = dispatch.get("followUpOf")
    w["outcome"] = (detail.get("projection") or {}).get("outcome") or raw.get("state") or w["outcome"]
    return w
