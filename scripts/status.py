#!/usr/bin/env python3
"""The status footer: what the build has in progress and what waits on you.

  status.py [--run <id>] [--milestone <title>] [--pr <n>] [--plain | --json]
  status.py --ask "<text>" [--ticket <n>] [--where <text>]   record an ask; prints its id
  status.py --done <id>                                       clear it

Run it from the repo. The coordinator prints `status.py --plain` at the end of
every turn of /flow:build. The run defaults to `orca orchestration
run-current`, the integration PR to the one open PR whose branch starts with
`integration/` (in --milestone, when given), and the milestone to that PR's.

In progress: one line per live worker (ticket, role, model, time since its
task was created) with a flag when it has no heartbeat, exited without
reporting, or has run more than `slow_factor` times the median of its role's
finished tasks in this run (`slow_minutes` when there are fewer than 3), then
the milestone's tally.

Waiting on you, in this order, each left out when empty: ready-for-human
tickets in the milestone, ready-for-human tickets outside it, needs-info
tickets, the coordinator's asks, worker questions and escalations Orca has
not marked handled (and pending gates), and the integration PR once it is out
of draft or every milestone ticket is integrated. Nothing: `Waiting on you:
nothing`.

The asks live in `<git common dir>/flow/asks.jsonl` (mode 0600; inside .git,
so never tracked, and shared by every worktree), or `$FLOW_ASKS_FILE`. An ask
tied to an issue or PR that has closed is dropped. The tally line adds
`; N notes carried to the review` when `notes.py` holds any.

Reads only; the footer always exits 0 and names on one `Unavailable:` line
whatever it could not read. `--done` with an unknown id exits 1.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flowlib import cli, config, notes, orca, status  # noqa: E402
from flowlib import github as gh_mod  # noqa: E402


def load_config(args):
    """The config, or None when there is none and no --repo: the footer still prints the rest."""
    try:
        cfg = config.load(args.config)
    except config.ConfigMissing:
        return config.from_dict({"github_repo": args.repo}) if args.repo else None
    except (config.ConfigError, ValueError, OSError) as exc:
        print(f"status: config unusable ({exc})", file=sys.stderr)
        return config.from_dict({"github_repo": args.repo}) if args.repo else None
    if args.repo:
        cfg["github_repo"] = args.repo
    return cfg


def main() -> int:
    p = cli.parser(__doc__, mutates=False)
    p.add_argument("--run", help="Orca Run id (default: orca orchestration run-current)")
    p.add_argument("--milestone", help="the build milestone's title (default: the integration PR's)")
    p.add_argument("--pr", help="the integration PR number (default: the open integration/* PR)")
    out = p.add_mutually_exclusive_group()
    out.add_argument("--plain", action="store_true", help="plain text with an emoji per section, for a chat turn")
    out.add_argument("--json", action="store_true", help="the same data as JSON")
    p.add_argument("--slow-factor", type=float, help="flag a worker past this many times its role's median (default 3)")
    p.add_argument("--slow-minutes", type=float, help="without a median, flag a worker past this (default 120)")
    act = p.add_mutually_exclusive_group()
    act.add_argument("--ask", metavar="TEXT", help="record something you asked the founder; prints its id")
    act.add_argument("--done", metavar="ID", help="clear an ask once answered")
    p.add_argument("--ticket", help="with --ask: the issue or PR it is about (dropped when that closes)")
    p.add_argument("--where", default="", help="with --ask: where the founder answers")
    args = p.parse_args()

    path = status.asks_path(".")
    if args.ask is not None:
        if not " ".join(args.ask.split()):
            cli.die("--ask needs some text")
        try:
            print(status.add_ask(path, args.ask, ticket=args.ticket, where=args.where))
        except gh_mod.GitHubError as exc:
            cli.die(str(exc))
        return 0
    if args.done is not None:
        if status.done_ask(path, args.done):
            print(f"done {args.done}")
            return 0
        print(f"no ask {args.done}")
        return 1

    try:
        pr = gh_mod.ticket_number(args.pr) if args.pr else None
    except gh_mod.GitHubError as exc:
        cli.die(str(exc))
    try:
        cfg = load_config(args)
        gh = None
        if cfg is not None and cfg.get("tracker") == "github":
            gh = gh_mod.Gh(cfg["github_repo"],
                           runner=lambda a, s=None: gh_mod.run_gh(a, s, timeout=status.TIMEOUT))
        data = status.build(cfg=cfg, run_id=args.run, milestone=args.milestone, pr=pr, asks_file=path, notes_file=notes.notes_path("."),
                            orca_runner=lambda a: orca.orca(a, timeout=status.TIMEOUT), gh=gh,
                            slow_factor=args.slow_factor, slow_minutes=args.slow_minutes)
    except Exception as exc:  # noqa: BLE001 - a footer must never break the turn
        print(status.clean(f"Status footer unavailable: {type(exc).__name__}: {exc}"))
        return 0
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        style = "tty" if not args.plain and sys.stdout.isatty() else "plain"
        print("\n".join(status.render(data, style)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
