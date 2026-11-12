"""Pure parts of the estimator: the prompt, the answer parser and risk hints."""

from __future__ import annotations

import fnmatch
import json
import re

from . import config

RUBRIC = """Sizes are how much work one coding agent does, not how long the ticket is:
- S: one sitting. One module, about 300 changed lines or fewer with tests, and it
  follows a pattern that already exists or that the ticket spells out.
- M: one module or a few files, new tests, and some choices the ticket mostly settles.
  About 300 to 1000 changed lines.
- L: several sittings. New seams across packages, or design questions the ticket
  leaves open. An L usually ought to be split.
Detailed acceptance criteria are not size: a long ticket whose decisions are already
made can still be S or M."""

PROMPT = """You size one ticket for a coding agent. Answer with JSON only.

{rubric}

Risk is narrow. It is one of these kinds, or none: {risk_kinds}.
Touching an API, or having many acceptance criteria, is not risk by itself.
If none of the kinds applies, risk_kind is null.

Ticket {identifier}: {title}

{description}

Answer exactly: {{"size": "S|M|L", "risk_kind": "<one of the kinds>"|null, "reason": "one sentence"}}
"""

CALIBRATE = """These tickets come from one spec. Each was sized alone. Make the sizes consistent
across the set, using the same scale. Answer with JSON only.

{rubric}

Compare tickets with each other. A ticket that is clearly smaller than another one sized
L is not L too. Change a size only when the comparison calls for it.

{lines}

Answer exactly: {{"sizes": {{"<number>": {{"size": "S|M|L", "reason": "one sentence"}}}}}}
with one entry per ticket above.
"""


def build_prompt(issue: dict, cfg: dict, limit: int = 12000) -> str:
    description = (issue.get("description") or "").strip()
    if len(description) > limit:
        description = description[:limit] + "\n[truncated]"
    return PROMPT.format(
        rubric=RUBRIC,
        risk_kinds="; ".join(_kinds(cfg)),
        identifier=issue["identifier"],
        title=issue["title"],
        description=description or "(no description)",
    )


def _kinds(cfg: dict) -> list:
    return cfg.get("risk_kinds") or config.DEFAULTS["risk_kinds"]


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        raise ValueError("no JSON in the answer")
    return json.loads(m.group(0))


def _size(value) -> str:
    size = str(value or "").upper()
    if size not in ("S", "M", "L"):
        raise ValueError(f"bad size {value!r}")
    return size


def parse_answer(text: str, cfg: dict) -> dict:
    """Pull the JSON answer out of the model's reply. Risk holds only for a configured kind."""
    data = _json(text)
    kinds = {k.lower(): k for k in _kinds(cfg)}
    kind = kinds.get(str(data.get("risk_kind") or "").strip().lower())
    return {"size": _size(data.get("size")), "risk": kind is not None, "risk_kind": kind,
            "reason": str(data.get("reason", ""))[:300]}


def build_calibration_prompt(items: list) -> str:
    """items: [{"number", "title", "size", "reason"}], each sized alone."""
    lines = "\n".join(f"#{i['number']} [{i['size']}] {i['title']}: {i['reason']}" for i in items)
    return CALIBRATE.format(rubric=RUBRIC, lines=lines)


def parse_calibration(text: str, numbers) -> dict:
    """{number: {"size", "reason"}} for the asked-about numbers; anything else is dropped."""
    sizes = _json(text).get("sizes") or {}
    out = {}
    for key, val in sizes.items():
        try:
            n = int(str(key).lstrip("#"))
        except ValueError:
            continue
        if n in numbers and isinstance(val, dict):
            try:
                out[n] = {"size": _size(val.get("size")), "reason": str(val.get("reason", ""))[:300]}
            except ValueError:
                continue
    return out


def path_hints(text: str, cfg: dict) -> list:
    """Configured risk paths that the text names (a literal prefix, or a path that matches the glob)."""
    hints = []
    low = (text or "").lower()
    tokens = re.findall(r"[\w./-]+/[\w./-]+", text or "")
    for pattern in cfg.get("risk_paths", []):
        bare = pattern.rstrip("*").rstrip("/")
        if (bare and bare.lower() in low) or any(fnmatch.fnmatch(t, pattern) for t in tokens):
            hints.append(f"path {pattern}")
    return hints


def word_hints(text: str, cfg: dict) -> list:
    low = (text or "").lower()
    return [f"word {w}" for w in cfg.get("risk_keywords", []) if re.search(rf"\b{re.escape(w.lower())}", low)]


def risk_hints(text: str, cfg: dict) -> list:
    """Mechanical hints: named risk paths or keywords that appear in the ticket."""
    return path_hints(text, cfg) + word_hints(text, cfg)
