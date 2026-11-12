"""Shared command-line plumbing: --config, --dry-run and --apply."""

from __future__ import annotations

import argparse
import json
import sys

from . import config as config_mod
from .linear import LinearClient


def parser(description: str, mutates: bool = True) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--config", help="path to linear.json (default docs/agents/linear.json, or $FLOW_CONFIG)")
    if mutates:
        mode = p.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", default=True, help="show what would change (the default)")
        mode.add_argument("--apply", action="store_true", help="make the changes")
    return p


def load(args) -> dict:
    try:
        return config_mod.load(args.config)
    except (config_mod.ConfigError, ValueError) as exc:
        die(str(exc))


def client(cfg: dict, apply: bool) -> LinearClient:
    return LinearClient(cfg["keychain_service"], apply=apply)


def die(message: str, code: int = 1):
    print(f"error: {message}", file=sys.stderr)
    sys.exit(code)


def heading(text: str) -> None:
    print(f"\n== {text}")


def show_planned(c: LinearClient, limit: int = 20) -> None:
    if not c.planned:
        print("No Linear writes needed.")
        return
    print(f"{len(c.planned)} Linear write(s) planned:")
    for p in c.planned[:limit]:
        print(f"  - {p.name}: {p.describe}")
    if len(c.planned) > limit:
        print(f"  ... and {len(c.planned) - limit} more")


def mode_line(apply: bool) -> str:
    return "APPLY: writing to Linear" if apply else "DRY RUN: nothing is written (pass --apply to write)"


def dump(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, default=str)
