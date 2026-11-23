"""Text safe to print, shared by the status footer and the notes list."""

from __future__ import annotations

import re
import unicodedata

TITLE_MAX = 60

BIDI = re.compile("[‪-‮⁦-⁩]")  # embedding, override and isolate controls


def clean(text) -> str:
    """A line safe to print: control characters and bidi overrides dropped (an ESC would
    inject terminal escapes), whitespace runs collapsed, and three or more backticks turned
    into quotes (they would close the fenced block the coordinator prints this in)."""
    text = "".join(" " if c in "\t\n\r" else c for c in str(text)
                   if c in "\t\n\r" or unicodedata.category(c) != "Cc")  # C0, DEL and C1, ESC among them
    text = BIDI.sub("", text)
    text = re.sub(r"`{3,}", lambda m: "'" * len(m.group()), text)
    return " ".join(text.split())


def cut(text, width: int = TITLE_MAX) -> str:
    text = clean(text)
    return text if len(text) <= width else text[: max(width - 1, 1)] + "…"
