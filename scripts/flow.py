#!/usr/bin/env python3
"""Run /flow:build from a normal terminal, and watch it there.

  flow.py start <spec> [--milestone <title>] [--model opus] [--effort <level>] [--automerge]
                       [--apply] [--no-watch]
  flow.py watch [--once] [--interval <seconds>]

Run it from the repo, outside Claude Code. `start` launches the coordinator as a Claude agent in an
Orca terminal of this repo (`orca agent launch --surface terminal`), told to build <spec> (an issue
number, or a Linear ID under the Linear tracker). Without --apply it prints the launch and the prompt
and starts nothing. With --apply it launches, records the coordinator in
`<git common dir>/flow/console.json` (or $FLOW_CONSOLE_FILE) and opens the console. A rerun while
that coordinator's terminal is still connected starts nothing and opens the console on it.

The coordinator does not depend on this process: quit the console with q and the build goes on;
`watch` opens it again. The console shows the coordinator's state and last message, the live
workers and the milestone tally, what waits on you (the coordinator's asks, numbered, then the
footer's other sections) and the carried notes, refreshed every few seconds.

Keys: r reply to the coordinator; 1-9 answer that ask; l the coordinator's recent conversation;
o bring its terminal to the front in Orca; R refresh now; arrows, j/k, space and PgUp/PgDn scroll;
q quit. A reply is typed into the coordinator's prompt as your own input (`orca terminal send`).

`watch --once`, or `watch` with no terminal, prints one frame as plain text and exits.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flowlib import cli, config, console, orca, status  # noqa: E402
from flowlib import github as gh_mod  # noqa: E402
from flowlib import notes as notes_mod  # noqa: E402


def runner(args):
    return orca.orca(args, timeout=status.TIMEOUT)


def repo_root() -> str:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False)
    if out.returncode != 0:
        cli.die("run flow.py from inside the repo")
    return out.stdout.strip()


def load_config(args):
    try:
        cfg = config.load(args.config)
    except config.ConfigMissing:
        return config.from_dict({"github_repo": args.repo}) if args.repo else None
    except (config.ConfigError, ValueError, OSError) as exc:
        print(f"flow: config unusable ({exc})", file=sys.stderr)
        return None
    if args.repo:
        cfg["github_repo"] = args.repo
    return cfg


def status_reader(cfg, milestone):
    gh = None
    if cfg is not None and cfg.get("tracker") == "github":
        gh = gh_mod.Gh(cfg["github_repo"], runner=lambda a, s=None: gh_mod.run_gh(a, s, timeout=status.TIMEOUT))

    def read(run_id):
        return status.build(cfg=cfg, run_id=run_id, milestone=milestone, asks_file=status.asks_path("."),
                            notes_file=notes_mod.notes_path("."), orca_runner=runner, gh=gh)
    return read


def coordinator_connected(state) -> bool:
    if not state.get("terminal"):
        return False
    errors: list = []
    return bool(console.read_coordinator(dict(state), runner, errors)["connected"])


def cmd_start(args) -> int:
    try:
        spec = console.spec_ref(args.spec)
    except gh_mod.GitHubError as exc:
        cli.die(str(exc))
    path = console.state_path(".")
    old = console.load_state(path)
    if old.get("spec") == spec and coordinator_connected(old):
        print(f"The coordinator for {spec} is already running ({old['terminal']}); opening the console.")
        return cmd_watch(args) if not args.no_watch else 0

    cfg = load_config(args)
    model = args.model or ((cfg or {}).get("models") or {}).get("opus") or "opus"
    text = console.prompt(spec, args.milestone, args.automerge)
    launch = console.launch_args(repo_root(), text, model, args.effort)
    if not args.apply:
        print("DRY RUN: nothing is started (pass --apply to launch the coordinator)")
        shown = ["<the prompt below>" if a == text else shlex.quote(a) for a in launch]
        print("\n$ orca " + " ".join(shown) + " --json\n\n" + text)
        return 0
    try:
        result = orca.orca(launch + ["--json"], timeout=60)
    except orca.OrcaError as exc:
        cli.die(f"the coordinator did not start: {exc}")
    found = console.parse_launch(result)
    if not found["terminal"]:
        cli.die("Orca started something but named no terminal; find it with `orca agent list`")
    state = {"spec": spec, "milestone": args.milestone, "terminal": found["terminal"],
             "session": found["session"], "run": None, "started_at": time.time()}
    console.save_state(path, state)
    print(f"Started the coordinator for {spec} in {found['terminal']}.")
    return 0 if args.no_watch else cmd_watch(args)


def cmd_watch(args) -> int:
    path = console.state_path(".")
    state = console.load_state(path)
    if not state.get("terminal"):
        cli.die("no build to watch: start one with `flow.py start <spec> --apply`")
    cfg = load_config(args)
    read_status = status_reader(cfg, getattr(args, "milestone", None) or state.get("milestone"))
    asks, notes_file = status.asks_path("."), notes_mod.notes_path(".")
    if getattr(args, "once", False) or not (sys.stdin.isatty() and sys.stdout.isatty()):
        snap = console.snapshot(state, runner, read_status, asks, notes_file)
        console.save_state(path, state)
        print(console.plain(snap))
        return 0
    from flowlib import tui  # curses only when there is a screen to draw on
    tui.run(state, runner, read_status, asks, notes_file, lambda s: console.save_state(path, s),
            interval=getattr(args, "interval", None) or console.REFRESH)
    print("Console closed; the build goes on. `flow.py watch` opens it again.")
    return 0


def main() -> int:
    p = cli.parser(__doc__, mutates=False)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start", help="launch the coordinator in Orca and open the console")
    s.add_argument("spec", help="the spec issue: 19, #19, or a Linear ID")
    s.add_argument("--milestone", help="build one milestone of the spec")
    s.add_argument("--model", help="the coordinator's model (default flow.json models.opus, else opus)")
    s.add_argument("--effort", help="the coordinator's reasoning effort (needs a model)")
    s.add_argument("--automerge", action="store_true", help="tell the coordinator automerge is on for this run")
    s.add_argument("--apply", action="store_true", help="launch it (without this, a dry run)")
    s.add_argument("--no-watch", action="store_true", help="launch and exit, without the console")
    s.add_argument("--interval", type=float, help=argparse.SUPPRESS)
    w = sub.add_parser("watch", help="open the console on the running build")
    w.add_argument("--once", action="store_true", help="print one frame as plain text and exit")
    w.add_argument("--interval", type=float, help=f"seconds between reads (default {console.REFRESH})")
    args = p.parse_args()
    return cmd_start(args) if args.cmd == "start" else cmd_watch(args)


if __name__ == "__main__":
    sys.exit(main())
