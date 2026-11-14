"""Pick a model and effort for an Orca worker from the routing table.

The table lives in the repo's docs/agents/orchestration.md under
"## Model routing". The coordinator runs route.py on every dispatch, so the
doc is the single source and nobody routes from memory.
"""

from __future__ import annotations

import re

from . import agents, config, estimating, repofacts

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
        if not model:
            raise RoutingError(f"row {key!r} names no model")
        table[key] = {
            "model": model,
            "effort": cell["effort"].strip("` ").lower() or None,
            "role": cell.get("role", ""),
            "notes": cell.get("notes", ""),
        }
    return table


def ticket_facts(cfg: dict, labels, body: str = "", paths=(), tree=None) -> dict:
    """Size and risk for one ticket: the `size:` label, and the `risk` label or any configured risk path.

    Paths come from --paths and from the ticket body; a path named in the body
    raises the model even if the ticket only mentions it, which errs safe.
    With `tree` (a repofacts.GitTree) a short path or a code name is looked up
    in the repo, so `identity/standing.go` counts for `backend/internal/identity/**`.
    """
    reasons = []
    if config.has_risk_label(cfg, labels):
        reasons.append(f"label {cfg['labels']['risk']}")
    text = "\n".join([body or ""] + [f"`{p}`" for p in paths])
    reasons += repofacts.risk_paths(text, tree or repofacts.EMPTY, cfg)
    return {"size": config.size_from_labels(cfg, labels), "risk": bool(reasons), "risk_reasons": reasons}


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
    """The --agent/--model/--effort flags for `orca orchestration worker-start`.

    --model is always passed: the user's own settings default to Opus.
    """
    try:
        prof = agents.profile(choice["model"], models)
    except agents.AgentError as exc:
        raise RoutingError(f"row {choice.get('key', '?')!r}: {exc}") from exc
    flags = ["--agent", prof["agent"], "--model", prof["model"]]
    if choice.get("effort"):
        flags += ["--effort", choice["effort"]]
    return flags


def ticket_id(ref) -> str:
    """123, "123" or "#123" -> "#123". Anything else (a Linear id such as ABC-1) is left as it is."""
    text = str(ref).strip()
    return f"#{text}" if text.isdigit() else text


def task_title(ticket, role: str, choice: dict) -> str:
    """`#123 · build · haiku`. The profiler parses this shape."""
    return f"{ticket_id(ticket)} · {role} · {choice['model']}"


# `#123` is the shape this plugin writes. The wider alternative keeps the Linear
# adapter's `ABC-123` titles and a bare milestone name readable.
TITLE_RE = re.compile(r"^(?P<ticket>#\d+|[A-Z][A-Z0-9]*-\d+|[\w-]+)\s*·\s*(?P<role>[\w-]+)\s*·\s*(?P<model>[\w.-]+)")


def parse_task_title(title: str):
    """Inverse of task_title(); None when the title does not follow the shape."""
    m = TITLE_RE.match(title or "")
    return m.groupdict() if m else None
