"""Read Claude Code transcripts and count usage once per API message.

A response is logged once per content block, each line carrying the same
usage, so usage is keyed by message id.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import prices


def parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def encode_project_dir(path: str) -> str:
    """Claude Code names a project's transcript folder after its path: every
    character that is not a letter or digit becomes a dash."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def read_jsonl(lines):
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            yield rec


def collect(records, scope: str = ""):
    """The API messages in `records`, each once, keyed by message id.

    A message with no id is keyed by its line number, prefixed with `scope`
    (the file name) so two files' line 7s do not collide. Returns
    (requests, order, times, usage_lines): requests maps key to
    (model, usage, timestamp), order is the keys in first-seen order, times the
    timestamps of every record, usage_lines how many lines carried usage.
    """
    requests, order, times, usage_lines = {}, [], [], 0
    for i, rec in enumerate(records):
        ts = parse_ts(rec.get("timestamp"))
        if ts:
            times.append(ts)
        msg = rec.get("message")
        if isinstance(msg, dict) and isinstance(msg.get("usage"), dict):
            usage_lines += 1
            key = msg.get("id") or f"{scope}line-{i}"
            if key not in requests:
                order.append(key)
            requests[key] = (msg.get("model") or "", msg["usage"], ts)
    return requests, order, times, usage_lines


def _summarise_requests(requests, order, times, start=None, end=None, sessions=1) -> dict:
    by_model = {}
    unpriced = set()
    contexts = []
    total = 0.0
    # Contexts run in time order: a resumed session's transcript can sort after a later one in the list.
    for key in sorted(order, key=lambda k: requests[k][2].timestamp() if requests[k][2] else float("-inf")):
        model, usage, ts = requests[key]
        if model == "<synthetic>":
            continue
        if (start is not None and (ts is None or ts < start)) or (end is not None and ts is not None and ts >= end):
            continue
        cost = prices.message_cost(model, usage)
        tokens = prices.usage_tokens(usage)
        slot = by_model.setdefault(model, {"cost": 0.0, "messages": 0, **{k: 0 for k in prices.TOKEN_KEYS.values()}})
        slot["messages"] += 1
        for k, v in tokens.items():
            slot[k] += v
        if cost is None:
            unpriced.add(model)
        else:
            slot["cost"] += cost
            total += cost
        contexts.append(
            {
                "at": ts.isoformat() if ts else None,
                "prompt": tokens["input"] + tokens["cache_read"] + tokens["cache_write"],
            }
        )
    times = sorted(times)
    return {
        "cost": total,
        "by_model": by_model,
        "unpriced_models": sorted(unpriced),
        "messages": len(contexts),
        "contexts": contexts,
        "sessions": sessions,
        "first_at": times[0].isoformat() if times else None,
        "last_at": times[-1].isoformat() if times else None,
    }


def summarise(records, start=None, end=None) -> dict:
    """Usage and cost of one transcript, given its parsed records.

    With `start` or `end`, only the API messages stamped in [start, end) count,
    so one session shared by several dispatches can be split between them. A
    message with no timestamp counts only when there is no `start`.
    """
    requests, order, times, _ = collect(records)
    return _summarise_requests(requests, order, times, start, end)


def summarise_file(path, start=None, end=None) -> dict:
    with open(path, encoding="utf-8", errors="replace") as fh:
        out = summarise(read_jsonl(fh), start, end)
    out["path"] = str(path)
    return out


def summarise_files(paths) -> tuple:
    """Usage across several transcripts of one run, a message counted once. Returns (summary, missing).

    A run spans several coordinator sessions, each its own transcript, and a
    resumed session repeats the messages before it, so a message seen in more
    than one file is counted the first time only. `missing` names the paths that
    do not exist or hold no usage; they are left out of the sum, and the summary
    is None when no path was left.
    """
    requests, order, times = {}, [], []
    counted, missing = [], []
    for path in paths:
        p = Path(path)
        if not p.is_file():
            missing.append(str(path))
            continue
        with open(p, encoding="utf-8", errors="replace") as fh:
            got, got_order, got_times, usage_lines = collect(read_jsonl(fh), scope=f"{p}:")
        if not usage_lines:
            missing.append(str(path))
            continue
        counted.append(str(path))
        times.extend(got_times)
        for key in got_order:
            if key not in requests:
                requests[key] = got[key]
                order.append(key)
    if not counted:
        return None, missing
    out = _summarise_requests(requests, order, times, sessions=len(counted))
    out["paths"] = counted
    return out, missing


def files_for_worktree(worktree: str, projects_root: Path) -> list:
    """Every transcript Claude Code wrote while running in `worktree`,
    including subagent transcripts in <session>/subagents/."""
    folder = projects_root / encode_project_dir(worktree)
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.jsonl")) + sorted(folder.glob("*/subagents/*.jsonl"))


def in_window(summary: dict, start, end) -> bool:
    """True when a transcript overlaps [start, end]. Missing bounds are open."""
    first, last = parse_ts(summary.get("first_at")), parse_ts(summary.get("last_at"))
    if first is None or last is None:
        return False
    if start is not None and last < start:
        return False
    if end is not None and first > end:
        return False
    return True


def session_of(path) -> str:
    """The session a transcript belongs to: its own name, or its parent session for a subagent's."""
    p = Path(path)
    return p.parent.parent.name if p.parent.name == "subagents" else p.stem


def assign(workers: list, sessions: list) -> dict:
    """Give every session to one worker chain, and every message to one worker. Pure.

    workers:  [{dispatch_id, worktree, started_at, follow_up_of}]
    sessions: [{session, worktree, first_at}], one per session id
    Returns {dispatch_id: [(session, start, end)]}: the sessions a worker owns
    and the slice of each that is its own ([start, end), None is open).

    A worktree is reused by a ticket's implementer, checker and merger, and
    `orchestration send` continues a worker in its old session under a new
    dispatch. So a session goes to the chain (a first dispatch and its
    follow-ups) that most recently started before the session's first message,
    and inside a chain a message goes to the dispatch most recently started
    before it. Nothing is counted twice and nothing is dropped.
    """
    by_id = {w["dispatch_id"]: w for w in workers}

    def root(w):
        seen = set()
        while w.get("follow_up_of") in by_id and w["dispatch_id"] not in seen:
            seen.add(w["dispatch_id"])
            w = by_id[w["follow_up_of"]]
        return w["dispatch_id"]

    chains = {}
    for w in workers:
        chains.setdefault(root(w), []).append(w)
    far = datetime.min.replace(tzinfo=timezone.utc)
    out = {w["dispatch_id"]: [] for w in workers}
    for s in sessions:
        first = parse_ts(s.get("first_at"))
        roots = sorted((parse_ts(by_id[r].get("started_at")) or far, r) for r in chains
                       if by_id[r].get("worktree") == s.get("worktree"))
        if not roots:
            continue
        owner = roots[0][1]
        for started, r in roots:
            if first is not None and started <= first:
                owner = r
        chain = sorted(chains[owner], key=lambda w: parse_ts(w.get("started_at")) or far)
        for i, w in enumerate(chain):
            start = None if i == 0 else parse_ts(w.get("started_at"))
            end = parse_ts(chain[i + 1].get("started_at")) if i + 1 < len(chain) else None
            out[w["dispatch_id"]].append((s["session"], start, end))
    return out
