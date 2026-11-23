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
        rec["ticket"] = gh_mod.ticket_number(ticket)
    append(path, rec)
    return rec_id


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
    ref = f"#{entry['ticket']}" if entry.get("ticket") else "no ticket"
    return clean(f"[{entry['id']}] {ref}: {entry.get('text', '')}")


def markdown(entries: list) -> str:
    """The live notes as a Markdown list grouped by ticket (tickets in number order, no ticket last);
    empty when there are none."""
    groups: dict = {}
    for e in entries:
        t = e.get("ticket")
        groups.setdefault(t if isinstance(t, int) else None, []).append(e)
    lines = []
    for t in sorted(groups, key=lambda k: (k is None, k or 0)):
        lines.append(f"- #{t}" if t is not None else "- No ticket")
        lines.extend(f"  - {clean(e.get('text', ''))} (`{clean(e['id'])}`)" for e in groups[t])
    return "\n".join(lines)
