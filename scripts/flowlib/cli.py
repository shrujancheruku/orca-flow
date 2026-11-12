"""Shared command-line plumbing: --config, --repo, --dry-run and --apply."""

from __future__ import annotations

import argparse
import sys

from . import config as config_mod


def parser(description: str, mutates: bool = True) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", help="path to flow.json (default docs/agents/flow.json, or $FLOW_CONFIG)")
    p.add_argument("--repo", help="owner/name; overrides github_repo, and stands in for a missing config")
    if mutates:
        mode = p.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", default=True, help="show what would change (the default)")
        mode.add_argument("--apply", action="store_true", help="make the changes")
    return p


def load(args, need_github: bool = True) -> dict:
    """The config, with --repo applied. --repo alone is enough when there is no config file."""
    repo = getattr(args, "repo", None)
    try:
        try:
            cfg = config_mod.load(args.config)
        except config_mod.ConfigMissing:
            if not repo:
                raise
            cfg = config_mod.from_dict({"github_repo": repo})
        if repo:
            cfg["github_repo"] = repo
        if need_github:
            config_mod.require_github(cfg)
    except config_mod.ConfigError as exc:
        die(str(exc))
    return cfg


def die(message: str, code: int = 1):
    print(f"error: {message}", file=sys.stderr)
    sys.exit(code)


def heading(text: str) -> None:
    print(f"\n== {text}")


def mode_line(apply: bool) -> str:
    return "APPLY: writing to GitHub" if apply else "DRY RUN: nothing is written (pass --apply to write)"
