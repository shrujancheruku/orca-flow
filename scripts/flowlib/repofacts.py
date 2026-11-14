"""Count what a ticket names in the repo, so the estimator sees how much code is there.

A ticket that says "every screen uses `ScreenFrame`" reads the same whether the
app has 3 screens or 40; its diff doesn't. So each path and code name a ticket
puts in backticks (or each bare path) is looked up: a path gets its files and
lines, a name gets the number of files that use it. Generated paths are left out.

`facts` is pure over a tree; `GitTree` reads one from git at a given commit, so a
backtest sees the repo as it was when the ticket was filed.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess

from . import backtest

LINE_REF = re.compile(r":\d[\d,\-]*$")  # app/x.tsx:64-76
BARE_PATH = re.compile(r"(?<![\w`/])(?:[\w.()\[\]-]+/)+[\w.()\[\]*-]+")
NAME = re.compile(r"^[A-Za-z_][\w.]{3,}$")


def mentions(text: str) -> list:
    """Paths and names a ticket mentions, in order, each once."""
    found = re.findall(r"`([^`\n]+)`", text or "")
    found += BARE_PATH.findall(re.sub(r"`[^`\n]*`|\]\([^)]*\)|https?://\S+", " ", text or ""))
    out = []
    for t in found:
        t = LINE_REF.sub("", t.strip()).strip("/").rstrip(".,;:")
        if t.endswith(")") and t.count(")") > t.count("("):  # "(see a/b.go)", but keep app/(tabs)
            t = t[:-1]
        if t and " " not in t and t not in out:
            out.append(t)
    return out


def is_path(token: str) -> bool:
    return "/" in token or bool(re.search(r"\.[a-z]{1,5}$", token))


def _under(p: str, lines: dict) -> list:
    """Files that are `p` or under it, with `p` given from any directory down."""
    return [f for f in lines if f == p or f.endswith("/" + p) or f.startswith(p + "/") or f"/{p}/" in f]


def lookup_path(token: str, lines: dict) -> tuple:
    """(files, lines) under a path, a file, or a glob; a path may be given from any
    directory down (app/x.tsx matches apps/mobile/src/app/x.tsx)."""
    p = token.lstrip("./")
    if any(c in p for c in "*?"):
        hit = [f for f in lines if fnmatch.fnmatch(f, p) or fnmatch.fnmatch(f, "*/" + p)]
    else:
        hit = _under(p, lines)
    return len(hit), sum(lines[f] for f in hit)


def facts(text: str, tree, limit: int = 30) -> list:
    out = []
    for t in mentions(text):
        if len(out) >= limit:
            break
        if is_path(t):
            n, total = lookup_path(t, tree.lines)
            out.append(f"`{t}`: not in the repo yet" if not n else
                       f"`{t}`: {n} file(s), {total} lines")
        elif NAME.match(t):
            n = len(tree.files_with(t))
            out.append(f"`{t}`: not in the repo yet" if not n else f"`{t}`: used in {n} file(s)")
    return out


class GitTree:
    """The repo's text files and their line counts at one commit."""

    def __init__(self, cfg: dict, rev: str = "HEAD", cwd: str = "."):
        self.cfg, self.rev, self.cwd = cfg, rev, cwd
        self.lines = {}
        for row in self._git("grep", "-I", "-c", "", rev).splitlines():
            _, path, count = row.rsplit(":", 2) if row.count(":") >= 2 else ("", "", "0")
            if path and not backtest.is_generated(path, cfg):
                self.lines[path] = int(count)

    def _git(self, *args) -> str:
        out = subprocess.run(["git", "-C", self.cwd, *args], capture_output=True, text=True, check=False)
        return out.stdout  # git grep exits 1 when nothing matches

    def files_with(self, name: str) -> list:
        rows = self._git("grep", "-l", "-w", "-F", "-e", name, self.rev).splitlines()
        paths = [r.split(":", 1)[1] for r in rows if ":" in r]
        return [p for p in paths if not backtest.is_generated(p, self.cfg)]


class _Empty:
    """No repo: paths count only as written, and no name resolves."""
    lines = {}

    def files_with(self, name: str) -> list:
        return []


EMPTY = _Empty()


def rev_before(when: str, cwd: str = ".") -> str:
    """The commit on the current branch's first-parent line just before `when`."""
    out = subprocess.run(["git", "-C", cwd, "rev-list", "-1", "--first-parent", f"--before={when}", "HEAD"],
                         capture_output=True, text=True, check=False).stdout.strip()
    return out or "HEAD"


def _literal(pattern: str, text: str) -> bool:
    """The text names the pattern. A directory pattern (`dir/**`) counts when its
    directory appears as a path; a one-word one like config/ must start a path,
    so the word "config" alone doesn't count. Any other glob counts only when a
    path in the text matches it: `apps/*/wrangler.jsonc` is not just "apps/"."""
    if pattern.endswith("/**") and not any(c in pattern[:-3] for c in "*?["):
        bare = pattern[:-3]
        if "/" in bare or "." in bare:
            return bare.lower() in text.lower()
        return re.search(rf"(?<![\w/.-]){re.escape(bare)}/", text, re.I) is not None
    if not any(c in pattern for c in "*?["):
        return pattern.lower() in text.lower()
    paths = re.findall(r"[\w.()\[\]-]+(?:/[\w.()\[\]-]+)+", text)
    paths = [t.rstrip(".,;:") for t in paths]
    return any(fnmatch.fnmatch(t, pattern) or fnmatch.fnmatch(t, "*/" + pattern) for t in paths)


def risk_paths(text: str, tree, cfg: dict, share: float = 0.5) -> list:
    """The configured risk paths a ticket is likely to touch, each with why: the
    ticket names the path, or names a file or code that mostly lives under it
    (at least `share` of the files the path or name matches)."""
    out = []
    for pattern in cfg.get("risk_paths", []):
        if _literal(pattern, text):
            out.append(f"path {pattern}")
    seen = {o.split(" ", 1)[1] for o in out}
    under = lambda files, pat: [f for f in files if fnmatch.fnmatch(f, pat)]
    for t in mentions(text):
        if is_path(t):
            p = t.lstrip("./")
            files = _under(p, tree.lines)
            why = f"names {t}"
            if not files and "/" in p:
                # a new file: judge it by the directory it goes in
                files = _under(p.rsplit("/", 1)[0], tree.lines)
                why = f"adds {t}"
            files = files or [p]
        elif NAME.match(t):
            files = tree.files_with(t)
            why = f"uses {t}"
        else:
            continue
        for pattern in cfg.get("risk_paths", []):
            if pattern in seen or not files:
                continue
            hit = under(files, pattern)
            # a bare name like handler.go, or a parent directory, mostly matches
            # files elsewhere; count it only when most of what it names is here
            if hit and len(hit) >= share * len(files):
                seen.add(pattern)
                out.append(f"{why} under {pattern}")
    return out
