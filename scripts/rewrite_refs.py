#!/usr/bin/env python3
"""Rewrite GitHub issue references in repo files to Linear ones.

Uses the mapping file that migrate.py wrote. Issue numbers become ABC-x and
issue URLs become Linear URLs; a map or spec number becomes a link to its
project. Pull request numbers are left as they are and listed. Unknown
numbers are left and flagged. Code spans and fenced blocks are never touched.

Dry run by default: prints each change. --apply edits the files in place.
Reads no Linear data and makes no network calls except `gh pr list`.
"""

from __future__ import annotations

import fnmatch
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flowlib import cli, github, mapping, refs  # noqa: E402

SKIP_DIRS = {".git", "node_modules", ".venv", "dist", "build", ".expo", ".next"}


def files(root: Path, globs: list, excludes: list) -> list:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(name, g) for g in globs) and not any(
                fnmatch.fnmatch(rel, e) for e in excludes
            ):
                out.append(path)
    return sorted(out)


def main() -> None:
    p = cli.parser(__doc__)
    p.add_argument("--root", default=".", help="repo root (default: current directory)")
    p.add_argument("--glob", action="append", help="file globs to scan (default *.md); repeatable")
    p.add_argument("--exclude", action="append", default=[], help="globs to skip; repeatable")
    p.add_argument("--mapping", help="mapping file (default: mapping_file in the config)")
    p.add_argument("--prs-from", help="a file of PR numbers, one per line, instead of asking gh")
    p.add_argument("--quiet", action="store_true", help="print only per-file counts")
    args = p.parse_args()
    cfg = cli.load(args)
    root = Path(args.root).resolve()
    mpath = args.mapping or str(root / cfg["mapping_file"])
    if not os.path.exists(mpath):
        cli.die(f"no mapping file at {mpath}; run migrate.py --apply first")
    table = mapping.MappingFile.load(mpath, cfg["github_repo"]).ref_table()
    if args.prs_from:
        prs = {int(x) for x in Path(args.prs_from).read_text().split() if x.strip().isdigit()}
    else:
        prs = github.fetch_pr_numbers(cfg["github_repo"])
    globs = args.glob or ["*.md"]
    excludes = args.exclude + [os.path.relpath(mpath, root)]
    print(("APPLY: editing files" if args.apply else "DRY RUN: no file is changed (pass --apply to edit)"))

    totals = Counter()
    flagged = Counter()
    for path in files(root, globs, excludes):
        raw = path.read_bytes()
        if refs.is_binary(raw[:8192]):
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        res = refs.rewrite_text(text, cfg["github_repo"], table, prs)
        for n, snippet in res.flagged:
            flagged[n] += 1
        if not res.changed and not res.flagged:
            continue
        rel = path.relative_to(root)
        totals["files"] += int(res.changed)
        totals["rewritten"] += len(res.rewritten)
        totals["left_pr"] += len(res.left_pr)
        totals["flagged"] += len(res.flagged)
        print(f"\n{rel}: {len(res.rewritten)} rewritten, {len(res.left_pr)} PR refs left, {len(res.flagged)} flagged")
        if not args.quiet:
            for n, old, new in res.rewritten[:50]:
                print(f"  #{n}: {old}  ->  {new}")
            for n, snippet in res.flagged:
                print(f"  FLAG #{n}: {snippet} (not in the mapping and not a PR)")
        if args.apply and res.changed:
            path.write_text(res.text, encoding="utf-8")

    cli.heading("Totals")
    print(f"  files changed {totals['files']}, refs rewritten {totals['rewritten']}, "
          f"PR refs left {totals['left_pr']}, flagged {totals['flagged']}")
    if flagged:
        print("  flagged numbers: " + ", ".join(f"#{n}" for n in sorted(flagged)))


if __name__ == "__main__":
    main()
