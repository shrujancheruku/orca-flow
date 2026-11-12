"""Read Claude Code transcripts and count usage once per API message.

A response is logged once per content block, each line carrying the same
usage, so usage is keyed by message id.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
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


def summarise(records) -> dict:
    """Usage and cost of one transcript, given its parsed records."""
    requests = {}
    order = []
    times = []
    for i, rec in enumerate(records):
        ts = parse_ts(rec.get("timestamp"))
        if ts:
            times.append(ts)
        msg = rec.get("message")
        if isinstance(msg, dict) and isinstance(msg.get("usage"), dict):
            key = msg.get("id") or f"line-{i}"
            if key not in requests:
                order.append(key)
            requests[key] = (msg.get("model") or "", msg["usage"], ts)
    by_model = {}
    unpriced = set()
    contexts = []
    total = 0.0
    for key in order:
        model, usage, ts = requests[key]
        if model == "<synthetic>":
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
    times.sort()
    return {
        "cost": total,
        "by_model": by_model,
        "unpriced_models": sorted(unpriced),
        "messages": len(contexts),
        "contexts": contexts,
        "first_at": times[0].isoformat() if times else None,
        "last_at": times[-1].isoformat() if times else None,
    }


def summarise_file(path) -> dict:
    with open(path, encoding="utf-8", errors="replace") as fh:
        out = summarise(read_jsonl(fh))
    out["path"] = str(path)
    return out


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
