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

# The "lines" style asks for a count instead of a size; the script turns it into
# S/M/L with the repo's size_lines. A backtest on Issho (2026-11) showed the
# rubric style sizing by breadth: tickets that touch many layers, or leave
# decisions open, came back L though their PRs were a few hundred lines.
LINES_PROMPT = """You estimate how big the pull request for one ticket will be. Answer with JSON only.

Count the lines a coding agent will add plus delete: code, tests and docs, but not
generated code or lockfiles. Estimate the diff, not the effort:
- Breadth is not size. Touching the API, the backend, an app and the docs can still
  be a small diff when each touch is a few lines.
- Open questions and decisions are not size. A ticket that is mostly deciding and
  writing down a choice is usually a small diff.
- A long ticket with many acceptance criteria is not size by itself.
- Most tickets are smaller than they read. A one-line fix with a test is about 20
  lines, a new endpoint with tests is a few hundred, a new feature across packages is
  often 1000 or more.

Risk is narrow. It is one of these kinds, or none: {risk_kinds}.
Touching an API, or having many acceptance criteria, is not risk by itself.
If none of the kinds applies, risk_kind is null.

{context}Ticket {identifier}: {title}

{description}

Answer exactly: {{"lines": <number>, "files": <number>, "mostly": "code"|"decisions", "risk_kind": "<one of the kinds>"|null, "reason": "one sentence"}}
"""

# The "examples" style is the lines prompt plus similar closed tickets and the
# lines their PRs really changed, so the model has this repo's scale.
EXAMPLES = """Closed tickets from this repo that read most like this one, and the lines their
PRs really changed (generated and deleted files left out). Use them as the scale
for this repo: a ticket like one of these is likely to be about as big.
{lines}

"""

# The "facts" style is the lines prompt plus counts from the repo of what the
# ticket names (flowlib/repofacts.py): a change to every use of a name used in
# 40 files is bigger than one used in 3, and the ticket text can't show which.
FACTS = """Counted from the repo when the ticket was filed (generated files left out), for
each path and name the ticket mentions. Use them to judge how many places the change
touches and how big the files it edits are; "not in the repo yet" means new code.
{lines}

"""

STYLES = ("rubric", "lines", "examples", "facts")


def format_examples(cases: list) -> str:
    if not cases:
        return ""
    lines = "\n".join(f"- #{c['number']} {c['title']}: {c['lines']} lines, {c['files']} files" for c in cases)
    return EXAMPLES.format(lines=lines)


def format_facts(facts: list) -> str:
    return FACTS.format(lines="\n".join(f"- {f}" for f in facts)) if facts else ""

CALIBRATE = """These tickets come from one spec. Each was sized alone. Make the sizes consistent
across the set, using the same scale. Answer with JSON only.

{rubric}

Compare tickets with each other. A ticket that is clearly smaller than another one sized
L is not L too. Change a size only when the comparison calls for it.

{lines}

Answer exactly: {{"sizes": {{"<number>": {{"size": "S|M|L", "reason": "one sentence"}}}}}}
with one entry per ticket above.
"""


def build_prompt(issue: dict, cfg: dict, limit: int = 12000, style: str = "rubric",
                 examples: list | None = None, facts: list | None = None) -> str:
    """`examples` (backtest.cases rows) are shown only in the examples style,
    `facts` (repofacts.facts lines) only in the facts style."""
    description = (issue.get("description") or "").strip()
    if len(description) > limit:
        description = description[:limit] + "\n[truncated]"
    return (PROMPT if style == "rubric" else LINES_PROMPT).format(
        context=(format_examples(examples or []) if style == "examples" else
                 format_facts(facts or []) if style == "facts" else ""),
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


def size_for_lines(lines: int, cfg: dict) -> str:
    bounds = cfg["size_lines"]
    return "S" if lines <= bounds["S"] else "M" if lines <= bounds["M"] else "L"


def parse_answer(text: str, cfg: dict, style: str = "rubric") -> dict:
    """Pull the JSON answer out of the model's reply. Risk holds only for a configured kind.

    In the lines style the size comes from the estimated lines, cut at size_lines.
    """
    data = _json(text)
    kinds = {k.lower(): k for k in _kinds(cfg)}
    kind = kinds.get(str(data.get("risk_kind") or "").strip().lower())
    out = {"risk": kind is not None, "risk_kind": kind, "reason": str(data.get("reason", ""))[:300]}
    if style != "rubric":
        try:
            lines = int(float(data.get("lines")))
        except (TypeError, ValueError):
            raise ValueError(f"bad lines {data.get('lines')!r}") from None
        if lines < 0:
            raise ValueError(f"bad lines {lines}")
        out.update(size=size_for_lines(lines, cfg), lines=lines, files=data.get("files"),
                   mostly=data.get("mostly"))
    else:
        out["size"] = _size(data.get("size"))
    return out


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


def combine(answers: list, cfg: dict) -> dict:
    """One estimate from several answers to the same prompt.

    Lines style: the median line estimate, so one wild answer can't move the
    size. Rubric style: the first answer. The reason and risk kind come from the
    answer nearest the median.
    """
    with_lines = [a for a in answers if a.get("lines") is not None]
    if not with_lines:
        a = answers[0]
        return {"estimate": a["size"], "estimate_reason": a["reason"], "risk_kind": a.get("risk_kind")}
    ordered = sorted(with_lines, key=lambda a: a["lines"])
    mid = ordered[(len(ordered) - 1) // 2]
    lines = mid["lines"] if len(ordered) % 2 else (mid["lines"] + ordered[len(ordered) // 2]["lines"]) // 2
    return {"estimate": size_for_lines(lines, cfg), "estimate_lines": lines, "estimate_reason": mid["reason"],
            "risk_kind": mid.get("risk_kind"), "estimate_spread": [a["lines"] for a in ordered]}
