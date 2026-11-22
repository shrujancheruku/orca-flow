#!/usr/bin/env python3
"""Remove a finished run's worktrees.

  cleanup.py --run <run id>           what would be removed, and what is kept and why
  cleanup.py --run <run id> --apply   remove them

Run it from the repo, after the milestone's integration PR is merged. A
worktree is removed only when it has no uncommitted file and its HEAD is on a
remote branch; anything else is kept and named. Branches are never deleted.

It uses `git worktree remove`, not `orca worktree rm`, which hangs and leaves
the checkout behind (see flowlib/cleanup.py). Orca drops its own record of a
worktree once the checkout is gone.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flowlib import cleanup, cli, orca  # noqa: E402


def main() -> None:
    p = cli.parser(__doc__)
    p.add_argument("--run", required=True, help="Orca Run id")
    p.add_argument("--root", default=".", help="repo root (default: here)")
    args = p.parse_args()
    root = os.path.abspath(args.root)
    try:
        workers = orca.list_workers(args.run)
    except orca.OrcaError as exc:
        cli.die(str(exc))
    paths = cleanup.worktree_paths(workers)
    if not paths:
        cli.die(f"run {args.run} has no workers")
    print("APPLY: removing worktrees" if args.apply else "DRY RUN: nothing is removed (pass --apply)")
    failed = 0
    for path in paths:
        go, why = cleanup.inspect(path, root)
        if go and args.apply:
            ok, message = cleanup.remove(path, root)
            why = "removed" if ok else f"not removed: {message}"
            failed += int(not ok)
        print(f"  {path}: {why}")
    if args.apply:
        cleanup.run_git(["worktree", "prune"], root)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
