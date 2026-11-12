"""Pick a model and effort for an Orca worker from the routing table.

The table lives in the repo's docs/agents/orchestration.md under
"## Model routing". The coordinator runs route.py on every dispatch, so the
doc is the single source and nobody routes from memory.
"""

from __future__ import annotations

import re

HEADING = "model routing"
ROLES = ("coordinator", "scout", "build", "merge", "check", "review", "fix")


class RoutingError(Exception):
    pass


def parse_table(markdown: str) -> dict:
    """Return {key: {"model", "effort", "role", "notes"}} from the routing table."""
    lines = markdown.splitlines()
    start = None
    for i, line in enumerate(lines):
        m = re.match(r"^#{2,3}\s+(.*)$", line)
        if m and m.group(1).strip().lower() == HEADING:
            start = i + 1
            break
    if start is None:
        raise RoutingError('no "## Model routing" heading in the orchestration doc')
    rows = []
    for line in lines[start:]:
        if re.match(r"^#{1,3}\s", line):
            break
        if line.strip().startswith("|"):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    if len(rows) < 3:
        raise RoutingError("the routing table has no rows")
    header = [h.lower() for h in rows[0]]
    for need in ("key", "model", "effort"):
        if need not in header:
            raise RoutingError(f"the routing table needs a {need!r} column")
    table = {}
    for row in rows[2:]:
        row = row + [""] * (len(header) - len(row))
        cell = dict(zip(header, row))
        key = cell["key"].strip("` ").lower()
        if not key:
            continue
        model = cell["model"].strip("` ").lower()
        if model not in ("haiku", "sonnet", "opus", "fable"):
            raise RoutingError(f"row {key!r}: unknown model {cell['model']!r}")
        table[key] = {
            "model": model,
            "effort": cell["effort"].strip("` ").lower() or None,
            "role": cell.get("role", ""),
            "notes": cell.get("notes", ""),
        }
    return table


def candidates(role: str, size=None, risk: bool = False, variant=None) -> list:
    """Most specific key first."""
    keys = []
    if variant:
        keys.append(f"{role}.{variant}")
    if size and risk:
        keys.append(f"{role}.{size}.risk")
    if size:
        keys.append(f"{role}.{size}")
    if risk:
        keys.append(f"{role}.risk")
    keys.append(role)
    return keys


def select(table: dict, role: str, size=None, risk: bool = False, variant=None) -> dict:
    role = role.lower()
    if role not in ROLES:
        raise RoutingError(f"unknown role {role!r}; use one of {', '.join(ROLES)}")
    if size is not None and size not in ("S", "M", "L"):
        raise RoutingError(f"size must be S, M or L, not {size!r}")
    for key in candidates(role, size, risk, variant):
        if key.lower() in table:
            return dict(table[key.lower()], key=key)
    raise RoutingError(f"no routing row for {role} (tried {', '.join(candidates(role, size, risk, variant))})")


def worker_flags(choice: dict, models: dict) -> list:
    """The --model/--effort flags for `orca orchestration worker-start`.

    --model is always passed: the user's own settings default to Opus.
    """
    model_id = models.get(choice["model"], choice["model"])
    flags = ["--model", model_id]
    if choice.get("effort"):
        flags += ["--effort", choice["effort"]]
    return flags


def task_title(ticket: str, role: str, choice: dict) -> str:
    return f"{ticket} · {role} · {choice['model']}"


TITLE_RE = re.compile(r"^(?P<ticket>[A-Z][A-Z0-9]*-\d+|[\w-]+)\s*·\s*(?P<role>[\w-]+)\s*·\s*(?P<model>[\w.-]+)")


def parse_task_title(title: str):
    """Inverse of task_title(); None when the title does not follow the shape."""
    m = TITLE_RE.match(title or "")
    return m.groupdict() if m else None
