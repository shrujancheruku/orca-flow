#!/usr/bin/env python3
"""Notes the coordinator carries from a ticket's merge to the integration review.

  notes.py --add "<text>" --ticket <n>   record a note; prints its id
  notes.py --done <id>                   clear one (the fixer, once it has fixed it)
  notes.py                               list the live notes, oldest first
  notes.py --markdown                    the live notes as a Markdown list grouped by
                                         ticket, for the review brief; nothing when none

A note is a miss the coordinator ruled "accepted, merging": a check that failed
only on paperwork. See "Rulings" in skills/build/SKILL.md.

Notes live in `<git common dir>/flow/notes.jsonl` (mode 0600; inside .git, so
never tracked, and shared by every worktree), or `$FLOW_NOTES_FILE`. Printed
text has control characters and bidi overrides stripped. `--done` with an
unknown id exits 1.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flowlib import cli, notes  # noqa: E402
from flowlib import github as gh_mod  # noqa: E402


def main() -> int:
    p = cli.parser(__doc__, mutates=False)
    act = p.add_mutually_exclusive_group()
    act.add_argument("--add", metavar="TEXT", help="record a note carried to the integration review; prints its id")
    act.add_argument("--done", metavar="ID", help="clear a note once it is fixed")
    act.add_argument("--markdown", action="store_true", help="the live notes as a Markdown list grouped by ticket")
    p.add_argument("--ticket", help="with --add: the ticket the note is about")
    args = p.parse_args()

    path = notes.notes_path(".")
    if args.add is not None:
        if not " ".join(args.add.split()):
            cli.die("--add needs some text")
        if args.ticket is None:
            cli.die("--add needs --ticket <n>")
        try:
            print(notes.add(path, args.add, ticket=args.ticket))
        except gh_mod.GitHubError as exc:
            cli.die(str(exc))
        return 0
    if args.done is not None:
        if notes.done(path, args.done):
            print(f"done {args.done}")
            return 0
        print(f"no note {args.done}")
        return 1
    live = notes.live(path)
    if args.markdown:
        if live:
            print(notes.markdown(live))
    else:
        for entry in live:
            print(notes.note_line(entry))
    return 0


if __name__ == "__main__":
    sys.exit(main())
