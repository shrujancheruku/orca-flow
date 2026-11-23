"""Pick a model and effort for an Orca worker from the routing table.

The table's defaults live here, in the plugin, so a new release changes every
row a repo has not set itself. A repo sets a row in `routing` in its
docs/agents/flow.json. The table in docs/agents/orchestration.md is a copy the
plugin writes between its own markers for people and agents to read; route.py
never routes from it, and warns when it is out of date.
"""

from __future__ import annotations

import re

from . import agents, config, estimating, repofacts, seeding

HEADING = "model routing"
ROLES = ("coordinator", "scout", "build", "merge", "check", "review", "fix")


class RoutingError(Exception):
    pass


BLOCK = "routing"

# (key, role, model, effort, notes). {size} reads "size" on GitHub and "Estimate" on Linear.
DEFAULT_ROWS = (
    ("coordinator", "Coordinator", "opus", "medium", "The session running `/flow:build`."),
    ("scout", "Exploration or scout", "haiku", None, "A subagent inside a worker."),
    ("build.S", "Implementer, {size} S, no `risk`", "haiku", None, "Escalates once; see Escalation."),
    ("build.S.risk", "Implementer, {size} S, `risk`", "sonnet", "medium", ""),
    ("build.M", "Implementer, {size} M", "sonnet", "medium", ""),
    ("build.M.risk", "Implementer, {size} M, `risk`", "sonnet", "high", ""),
    ("build.L", "Implementer, {size} L", "sonnet", "high", ""),
    ("build.L.risk", "Implementer, {size} L, `risk`", "opus", None, ""),
    ("build.escalated", "Implementer after an escalation", "sonnet", "medium", "A fresh worker on the same branch."),
    ("merge", "Merger", "haiku", None, ""),
    ("merge.conflict", "Merger on a real conflict", "sonnet", "medium", ""),
    ("check", "Spec check before a ticket merges into the integration branch", "haiku", None, "One per ticket."),
    ("review", "Integration `code-review`, once per milestone", "opus", None, ""),
    ("review.risk", "Integration `code-review`, milestone has `risk` tickets", "opus", None,
     "Same as `review`; kept so `--risk` resolves."),
    ("fix", "Fixer for the integration review's findings", "opus", None, ""),
)

# What earlier releases shipped for a row. A table written before the defaults
# moved here may still hold these; such a row was never the repo's own choice,
# so it follows the current default. Add the old value here when a default changes.
PAST_DEFAULTS = {
    "review": [("sonnet", "high")],
    "fix": [("sonnet", "medium")],
    # Haiku takes no effort: Orca refuses `--model haiku --effort low` and the worker never starts.
    "scout": [("haiku", "low")],
    "merge": [("haiku", "low")],
    "check": [("haiku", "low")],
}

# Model ids that take no effort setting. Orca rejects worker-start outright when
# one is passed, so the flag is left off even when a repo's own row names one.
NO_EFFORT = ("haiku",)

SET_NOTE = "Set in `flow.json`."
FOOTER = ("The flow plugin writes this table from its defaults and from `routing` in `docs/agents/flow.json`. "
          "To change a row, set it there (`\"routing\": {\"fix\": {\"model\": \"sonnet\", \"effort\": \"medium\"}}`), "
          "not here: a row you have not set follows the plugin's default and changes with its releases.")


def default_table(size_word: str = "size") -> dict:
    """{lower key: row} for the plugin's defaults, in table order."""
    return {
        key.lower(): {"key": key, "role": role.format(size=size_word), "model": model, "effort": effort,
                      "notes": notes, "set": False}
        for key, role, model, effort, notes in DEFAULT_ROWS
    }


def check_overrides(raw) -> list:
    """Problems with a config's `routing` value. Empty means usable."""
    if raw is None:
        return []
    if not isinstance(raw, dict):
        return ["routing must be an object of row key -> {model, effort}"]
    problems = []
    for key, row in raw.items():
        if not isinstance(row, dict) or not isinstance(row.get("model"), str) or not row["model"].strip():
            problems.append(f"routing.{key} needs a model")
        elif row.get("effort") not in (None, "") and not isinstance(row["effort"], str):
            problems.append(f"routing.{key}.effort must be a string or null")
        elif key.split(".")[0].lower() not in ROLES:
            problems.append(f"routing.{key} must start with one of {', '.join(ROLES)}")
    return problems


def effective(overrides=None, size_word: str = "size") -> dict:
    """The plugin's defaults with the repo's own rows laid over them."""
    table = default_table(size_word)
    for key, row in (overrides or {}).items():
        base = table.get(key.lower(), {"key": key, "role": "", "notes": ""})
        table[key.lower()] = dict(
            base, model=row["model"].strip().lower(), effort=(row.get("effort") or "").strip().lower() or None,
            role=row.get("role") or base["role"], notes=row.get("notes") or base["notes"], set=True)
    return table


def render(table: dict) -> str:
    """The marked block's text: the table, then how to change it."""
    lines = ["| Key | Role | Model | Effort | Notes |", "|---|---|---|---|---|"]
    for row in table.values():
        notes = " ".join(n for n in (row["notes"], SET_NOTE if row.get("set") else "") if n)
        lines.append(f"| {row['key']} | {row['role']} | {row['model']} | {row['effort'] or ''} | {notes} |")
    return "\n".join(lines) + "\n\n" + FOOTER


def legacy_overrides(doc_table: dict) -> dict:
    """Rows of a hand-kept table that are the repo's own choice.

    A row counts as the repo's own when it is neither the current default nor
    anything an earlier release shipped for that key, or when the key is new.
    """
    defaults = default_table()
    out = {}
    for key, row in doc_table.items():
        got = (row["model"], row["effort"])
        base = defaults.get(key)
        if base is None:
            out[key] = {"model": row["model"], "effort": row["effort"]}
            for extra in ("role", "notes"):
                if row.get(extra):
                    out[key][extra] = row[extra]
        elif got != (base["model"], base["effort"]) and got not in PAST_DEFAULTS.get(base["key"], []):
            out[base["key"]] = {"model": row["model"], "effort": row["effort"]}
    return out


def block_text(doc: str):
    """What sits between the routing markers in the doc, or None when it has no block."""
    span = seeding._span(doc, BLOCK)
    if span is None:
        return None
    return doc[span[0] + len(seeding.begin(BLOCK)): span[1] - len(seeding.end(BLOCK))].strip()


def _legacy_table_span(doc: str):
    """(start, end) of the hand-kept table under "## Model routing", or None."""
    sec = None
    for m in re.finditer(r"^#{2,3}\s+(.*)$", doc, re.MULTILINE):
        if m.group(1).strip().lower() == HEADING:
            sec = m.end()
            break
    if sec is None:
        return None
    nxt = re.compile(r"^#{1,3}\s", re.MULTILINE).search(doc, sec)
    stop = nxt.start() if nxt else len(doc)
    start = end = None
    pos = sec
    for line in doc[sec:stop].splitlines(keepends=True):
        if line.strip().startswith("|"):
            start = pos if start is None else start
            end = pos + len(line.rstrip("\n"))
        elif start is not None:
            break
        pos += len(line)
    return (start, end) if start is not None else None


def place_block(doc: str, table: dict) -> str:
    """Put the routing block in the doc: over its own block, over a hand-kept table, or under a new heading."""
    body = render(table)
    if seeding._span(doc, BLOCK):
        return seeding.upsert(doc, BLOCK, body)
    span = _legacy_table_span(doc)
    if span:
        return doc[: span[0]] + seeding.wrap(BLOCK, body) + doc[span[1]:]
    return (doc.rstrip() + "\n\n" if doc.strip() else "") + "## Model routing\n\n" + seeding.wrap(BLOCK, body) + "\n"


def resolve(overrides, doc, size_word: str = "size", seed: str = "seed_docs.py") -> tuple:
    """(table, warnings) for one dispatch.

    The table is the defaults plus the repo's `routing`. The doc is read only to
    keep a not-yet-migrated repo's own rows and to say when its copy is stale.
    """
    overrides = dict(overrides or {})
    warnings = []
    if doc is not None and block_text(doc) is None:
        try:
            legacy = legacy_overrides(parse_table(doc))
        except RoutingError:
            legacy = {}
        set_keys = {k.lower() for k in overrides}
        kept = {k: v for k, v in legacy.items() if k.lower() not in set_keys}
        overrides.update(kept)
        warnings.append(
            f"the orchestration doc's routing table is hand-kept: run {seed} --apply to hand it to the plugin"
            + (f" (your rows {', '.join(sorted(kept))} are kept and move to the config)" if kept else ""))
    table = effective(overrides, size_word)
    if doc is not None and block_text(doc) is not None and block_text(doc) != render(table).strip():
        warnings.append(f"the orchestration doc's routing table is out of date: run {seed} --apply")
    return table, warnings


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
    if choice.get("effort") and not takes_no_effort(choice, models):
        flags += ["--effort", choice["effort"]]
    return flags


def takes_no_effort(choice: dict, models: dict) -> bool:
    """True when the row's model (by its profile name or its model id) takes no effort setting."""
    try:
        model = agents.profile(choice["model"], models)["model"]
    except agents.AgentError:
        model = ""
    return any(word in f"{choice['model']} {model}".lower() for word in NO_EFFORT)


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
