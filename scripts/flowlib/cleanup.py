"""Decide which of a run's worktrees are safe to remove, and remove them with git.

`orca worktree rm` (Orca 1.4.269) stops the worktree's terminals, then its own
`git worktree remove` fails and the command waits until it times out, leaving
the checkout on disk and the worktree marked as removing. Plain
`git worktree remove`, run from the repo, works, and Orca drops its record of
a worktree once the checkout is gone. So cleanup goes through git.

Nothing is forced: a worktree with uncommitted files, or whose HEAD is on no
remote branch, is kept and named.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def run_git(args: list, cwd: str) -> tuple:
    out = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, check=False)
    return out.returncode, out.stdout.strip(), out.stderr.strip()


def worktree_paths(workers: list) -> list:
    """The distinct worktree paths a run's workers ran in, from Orca's `workspace` ("<repo id>::<path>")."""
    paths = []
    for w in workers:
        workspace = w.get("workspace") or ""
        path = workspace.split("::", 1)[1] if "::" in workspace else w.get("worktree") or ""
        if path and path not in paths:
            paths.append(path)
    return sorted(paths)


def verdict(exists: bool, is_main: bool, dirty: list, remotes: list) -> tuple:
    """(remove?, why) for one worktree. Pure."""
    if not exists:
        return False, "already gone"
    if is_main:
        return False, "kept: the repo's own checkout"
    if dirty:
        return False, f"kept: {len(dirty)} uncommitted file(s), e.g. {dirty[0]}"
    if not remotes:
        return False, "kept: its HEAD is on no remote branch (push it, or remove it by hand)"
    return True, f"remove (HEAD is on {remotes[0]})"


def inspect(path: str, repo_root: str) -> tuple:
    """verdict() for a path, reading git."""
    p = Path(path)
    if not p.is_dir():
        return verdict(False, False, [], [])
    is_main = p.resolve() == Path(repo_root).resolve() or (p / ".git").is_dir()
    code, status, _ = run_git(["status", "--porcelain"], path)
    dirty = [line[3:] for line in status.splitlines()] if code == 0 else ["(git status failed)"]
    _, remotes, _ = run_git(["branch", "-r", "--contains", "HEAD", "--format=%(refname:short)"], path)
    return verdict(True, is_main, dirty, [r for r in remotes.splitlines() if r and "->" not in r])


def remove(path: str, repo_root: str) -> tuple:
    """(ok, message). Never --force: git refuses a worktree with changes, which is the point."""
    code, _, err = run_git(["worktree", "remove", path], repo_root)
    return code == 0, err or "removed"
