"""Append-only local stores under the git common dir, and the carried notes built on one.

The coordinator's asks (`asks.jsonl`, read by the status footer) and the notes it
carries to the integration review (`notes.jsonl`) are the same kind of file: one
JSON record per line, an `add` and a `done` op, kept inside `.git` so they are
never tracked and every worktree of the repo shares them. The storage rules live
here once; `status.py` uses them for the asks.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import github as gh_mod
from .text import clean, cut

TIMEOUT = 20  # seconds for the git call


def store_path(name: str, env_var: str, cwd: str = ".") -> Path:
    """`$<env_var>`, else `<git common dir>/flow/<name>` (inside .git, so never tracked and shared by
    every worktree of the repo), else a per-repo file under the user's cache dir when the directory
    is not a git checkout."""
    env = os.environ.get(env_var)
    if env:
        return Path(env)
    try:
        out = subprocess.run(["git", "-C", cwd, "rev-parse", "--git-common-dir"],
                             capture_output=True, text=True, check=False, timeout=TIMEOUT)
        if out.returncode == 0 and out.stdout.strip():
            # Relative to `cwd` in the main checkout (".git"), absolute from a linked worktree.
            return (Path(cwd) / out.stdout.strip()).resolve() / "flow" / name
    except (OSError, subprocess.TimeoutExpired):
        pass
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    key = hashlib.sha1(os.path.abspath(cwd).encode()).hexdigest()[:12]
    return cache / "flow" / key / name


def append(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        if os.fstat(fd).st_mode & 0o077:
            os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            os.write(fd, (json.dumps(rec, separators=(",", ":")) + "\n").encode("utf-8"))
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def live(path: Path) -> list:
    """The live records, oldest first. A line that is not JSON is skipped; no file is no records."""
    entries: dict = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or not isinstance(rec.get("id"), str):
            continue
        if rec.get("op") == "add":
            entries[rec["id"]] = rec
        elif rec.get("op") == "done":
            entries.pop(rec["id"], None)
    return list(entries.values())


def add(path: Path, text: str, ticket=None, **extra) -> str:
    rec_id = secrets.token_hex(3)
    rec = {"op": "add", "id": rec_id, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "text": " ".join(str(text).split())[:500]}
    rec.update(extra)
    if ticket is not None:
        rec["ticket"] = ticket  # already normalised by the caller: `ticket_ref` for notes, `ticket_number` for asks
    append(path, rec)
    return rec_id


LINEAR_ID = re.compile(r"[A-Za-z][A-Za-z0-9]*-[0-9]+")


def ticket_ref(ref):
    """123 / "#123" -> 123 (a GitHub issue); "abc-123" -> "ABC-123" (a Linear issue). Notes take both
    because the Linear adapter's coordinator records them too; the asks and the footer stay GitHub-only."""
    text = str(ref).strip()
    if LINEAR_ID.fullmatch(text):
        return text.upper()
    try:
        return gh_mod.ticket_number(text)
    except gh_mod.GitHubError:
        raise gh_mod.GitHubError(f"{ref!r} is not a ticket like 123, #123 or ABC-123") from None


def _ticket_key(t):
    # GitHub numbers first in number order, then Linear IDs by team and number, no ticket last.
    if t is None:
        return (2, "", 0)
    if isinstance(t, int):
        return (0, "", t)
    team, _, num = str(t).rpartition("-")
    return (1, team, int(num) if num.isdigit() else 0)


def _ticket_label(t) -> str:
    return f"#{t}" if isinstance(t, int) else clean(str(t))


def done(path: Path, rec_id: str) -> bool:
    """Clear a record; False when no live record has that id (nothing is written then)."""
    if not any(e["id"] == rec_id for e in live(path)):
        return False
    append(path, {"op": "done", "id": rec_id})
    return True


# -- the carried notes --------------------------------------------------------

def notes_path(cwd: str = ".") -> Path:
    return store_path("notes.jsonl", "FLOW_NOTES_FILE", cwd)


def note_line(entry: dict) -> str:
    ref = _ticket_label(entry["ticket"]) if entry.get("ticket") else "no ticket"
    return clean(f"[{entry['id']}] {ref}: {entry.get('text', '')}")


def markdown(entries: list) -> str:
    """The live notes as a Markdown list grouped by ticket (GitHub numbers in order, then Linear IDs, no ticket last);
    empty when there are none."""
    groups: dict = {}
    for e in entries:
        t = e.get("ticket")
        groups.setdefault(t if isinstance(t, (int, str)) and t != "" else None, []).append(e)
    lines = []
    for t in sorted(groups, key=_ticket_key):
        lines.append(f"- {_ticket_label(t)}" if t is not None else "- No ticket")
        lines.extend(f"  - {clean(e.get('text', ''))} (`{clean(e['id'])}`)" for e in groups[t])
    return "\n".join(lines)
