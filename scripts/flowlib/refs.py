"""Rewrite GitHub issue references to Linear, leaving pull requests alone.

Pure: rewrite_text() takes the text, the ref table from the mapping file and
the set of PR numbers, and returns the new text plus what it did.

What it rewrites, outside code spans and fenced blocks only:
- [text](https://github.com/OWNER/REPO/issues/N)  -> the Linear URL; "#N" in the text too
- https://github.com/OWNER/REPO/issues/N          -> the Linear URL
- OWNER/REPO#N and bare #N                        -> ABC-x, or a link for a project
What it leaves: PR numbers (reported), unknown numbers (flagged), /pull/ URLs,
hex colours, HTML entities (&#123;), anchors (](#12)), and anything in code.
"""

from __future__ import annotations

import re


def _patterns(repo: str):
    owner, name = (re.escape(p) for p in repo.split("/"))
    base = rf"https?://github\.com/{owner}/{name}/(?P<{{k}}>issues|pull)/(?P<{{n}}>\d+)(?P<{{f}}>#[\w-]+)?"
    link = r"\[(?P<text>[^\]\n]*)\]\(" + base.format(k="lkind", n="lnum", f="lfrag") + r"\)"
    url = base.format(k="ukind", n="unum", f="ufrag")
    xref = rf"(?<![\w/.-]){owner}/{name}#(?P<xnum>\d+)\b"
    bare = r"(?<![\w&#/\\])#(?P<bnum>\d+)(?![\w-])"
    return re.compile("|".join([link, url, xref, bare]), re.IGNORECASE)


_INLINE_CODE = re.compile(r"(`+)(.+?)\1", re.DOTALL)


def _split_inline(line: str):
    """Yield (is_code, segment) pieces of one line."""
    pos = 0
    for m in _INLINE_CODE.finditer(line):
        if m.start() > pos:
            yield False, line[pos : m.start()]
        yield True, m.group(0)
        pos = m.end()
    if pos < len(line):
        yield False, line[pos:]


class Result:
    def __init__(self):
        self.text = ""
        self.rewritten = []  # (number, old, new)
        self.left_pr = []  # numbers left because they are PRs
        self.flagged = []  # (number, snippet) unknown numbers

    @property
    def changed(self) -> bool:
        return bool(self.rewritten)


def rewrite_text(text: str, repo: str, refs: dict, prs: set) -> Result:
    pattern = _patterns(repo)
    result = Result()

    def replace(m: re.Match, segment: str) -> str:
        whole = m.group(0)
        if m.group("lnum") is not None:
            n, kind, frag = int(m.group("lnum")), m.group("lkind").lower(), m.group("lfrag")
            if kind == "pull":
                result.left_pr.append(n)
                return whole
            ref = refs.get(n)
            if not ref:
                result.flagged.append((n, whole))
                return whole
            label = m.group("text")
            label = re.sub(rf"#{n}\b", ref["label"], label)
            new = f"[{label}]({ref['url']})"
            result.rewritten.append((n, whole, new))
            return new
        if m.group("unum") is not None:
            n, kind = int(m.group("unum")), m.group("ukind").lower()
            if kind == "pull":
                result.left_pr.append(n)
                return whole
            ref = refs.get(n)
            if not ref:
                result.flagged.append((n, whole))
                return whole
            result.rewritten.append((n, whole, ref["url"]))
            return ref["url"]
        num = m.group("xnum") or m.group("bnum")
        n = int(num)
        start = m.start()
        if m.group("bnum") is not None and segment[max(0, start - 2) : start] == "](":
            return whole  # an anchor link like [x](#12)
        if n in prs:
            result.left_pr.append(n)
            return whole
        ref = refs.get(n)
        if not ref:
            result.flagged.append((n, whole))
            return whole
        new = ref["label"] if ref["kind"] == "issue" else f"[{ref['label']}]({ref['url']})"
        result.rewritten.append((n, whole, new))
        return new

    out_lines = []
    fence = None
    for line in text.split("\n"):
        stripped = line.lstrip()
        marker = stripped[:3]
        if fence is None and marker in ("```", "~~~"):
            fence = marker
            out_lines.append(line)
            continue
        if fence is not None:
            if stripped.startswith(fence):
                fence = None
            out_lines.append(line)
            continue
        pieces = []
        for is_code, seg in _split_inline(line):
            if is_code:
                pieces.append(seg)
            else:
                pieces.append(pattern.sub(lambda m, s=seg: replace(m, s), seg))
        out_lines.append("".join(pieces))
    result.text = "\n".join(out_lines)
    return result


def is_binary(head: bytes) -> bool:
    return b"\0" in head
