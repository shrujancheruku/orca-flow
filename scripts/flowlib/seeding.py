"""Pure helpers for seeding docs without overwriting the user's own text.

Everything the plugin writes into a file it shares with the user sits between
two HTML comments:

    <!-- flow:begin name -->
    ...
    <!-- flow:end name -->

A rerun replaces only what is between them. Text outside is never touched.
"""

from __future__ import annotations

import re


class SeedError(Exception):
    pass


def begin(name: str) -> str:
    return f"<!-- flow:begin {name} -->"


def end(name: str) -> str:
    return f"<!-- flow:end {name} -->"


def wrap(name: str, body: str) -> str:
    return f"{begin(name)}\n{body.strip()}\n{end(name)}"


def render(text: str, vals: dict) -> str:
    out = text
    for k, v in vals.items():
        out = out.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{[A-Z_]+\}\}", out)
    if left:
        raise ValueError(f"unfilled placeholders: {sorted(set(left))}")
    return out


def _span(text: str, name: str):
    """(start, end) of the marked block including both comments, or None. Raises on half a block."""
    b, e = text.find(begin(name)), text.find(end(name))
    if b == -1 and e == -1:
        return None
    if b == -1 or e == -1 or e < b:
        raise SeedError(f"found half of the flow:{name} block (a begin or end marker is missing); fix or remove it by hand")
    return b, e + len(end(name))


def upsert(text: str, name: str, body: str) -> str:
    """Replace the named block, or append it at the end of the file."""
    block = wrap(name, body)
    span = _span(text, name)
    if span:
        return text[: span[0]] + block + text[span[1] :]
    return (text.rstrip() + "\n\n" if text.strip() else "") + block + "\n"


def section(text: str, heading: str, level: int):
    """(start, end) of a markdown section at `level`, or None."""
    marks = "#" * level
    m = re.search(rf"^{marks} {re.escape(heading)}\s*$", text, re.MULTILINE)
    if not m:
        return None
    nxt = re.compile(rf"^#{{1,{level}}} ", re.MULTILINE).search(text, m.end())
    return m.start(), (nxt.start() if nxt else len(text))


def upsert_in_agent_skills(text: str, name: str, body: str) -> str:
    """Put the named block at the end of the `## Agent skills` section; create the section if it is missing."""
    block = wrap(name, body)
    span = _span(text, name)
    if span:
        return text[: span[0]] + block + text[span[1] :]
    sec = section(text, "Agent skills", 2)
    if sec is None:
        return (text.rstrip() + "\n\n" if text.strip() else "") + "## Agent skills\n\n" + block + "\n"
    head = text[: sec[1]].rstrip()
    tail = text[sec[1] :]
    return head + "\n\n" + block + "\n" + ("\n" + tail.lstrip("\n") if tail.strip() else "")
