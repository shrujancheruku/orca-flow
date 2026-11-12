"""Load and check docs/agents/flow.json, the plugin's per-repo config.

Small on purpose: the tracker, the repo, the label names, the risk paths, the
Slack prefix and the model profiles (flowlib/agents.py). The Linear adapter keeps its own keys in
docs/agents/linear.json (see adapters/linear/).
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

from . import agents

DEFAULT_PATH = "docs/agents/flow.json"
TRACKERS = ("github", "linear")
SIZES = ("S", "M", "L")

DEFAULTS = {
    "tracker": "github",
    "labels": {
        "size": {"S": "size:S", "M": "size:M", "L": "size:L"},
        "risk": "risk",
        "integrated": "integrated",
        # Matt Pocock's five roles. His setup skill creates them; we only check.
        "triage": ["needs-triage", "needs-info", "ready-for-agent", "ready-for-human", "wontfix"],
    },
    "risk_paths": [],
    "risk_keywords": ["auth", "migration", "delete", "public api"],
    "orchestration_doc": "docs/agents/orchestration.md",
    "models": {"haiku": "haiku", "sonnet": "sonnet", "opus": "opus"},
    "slack_prefix": "",
}

REQUIRED = [("github_repo",)]


class ConfigError(Exception):
    pass


class ConfigMissing(ConfigError):
    pass


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def check(cfg: dict) -> list:
    """Return a list of problems. Empty means the config is usable."""
    problems = agents.check_models(cfg.get("models"))
    if cfg.get("tracker") not in TRACKERS:
        problems.append(f"tracker must be one of {', '.join(TRACKERS)}")
    repo = cfg.get("github_repo", "")
    if not repo:
        problems.append("missing github_repo")
    elif repo.count("/") != 1:
        problems.append("github_repo must be owner/name")
    size = cfg.get("labels", {}).get("size", {})
    if set(size) != set(SIZES) or not all(isinstance(v, str) and v for v in size.values()):
        problems.append("labels.size needs a name for each of S, M and L")
    elif len(set(size.values())) != 3:
        problems.append("labels.size names must differ")
    for key in ("risk", "integrated"):
        if not cfg.get("labels", {}).get(key):
            problems.append(f"missing labels.{key}")
    return problems


def from_dict(raw: dict) -> dict:
    cfg = _merge(DEFAULTS, {k: v for k, v in raw.items() if k != "$schema"})
    problems = check(cfg)
    if problems:
        raise ConfigError("config problems: " + "; ".join(problems))
    return cfg


def load(path: str | None = None) -> dict:
    p = Path(path or os.environ.get("FLOW_CONFIG") or DEFAULT_PATH)
    if not p.exists():
        raise ConfigMissing(f"no config at {p}. Copy examples/flow.json or run /flow:setup.")
    with p.open() as fh:
        raw = json.load(fh)
    cfg = from_dict(raw)
    cfg["_path"] = str(p)
    return cfg


def require_github(cfg: dict) -> None:
    """The core scripts are GitHub-only; a Linear repo uses the adapter's."""
    if cfg["tracker"] != "github":
        raise ConfigError(
            f"tracker is {cfg['tracker']!r}: use the scripts in adapters/linear/scripts "
            "(see adapters/linear/README.md)"
        )


def size_label(cfg: dict, size: str) -> str:
    return cfg["labels"]["size"][size]


def size_from_labels(cfg: dict, labels) -> str | None:
    """S, M or L from a ticket's label names, or None. Larger wins if several are set."""
    names = {str(l).lower() for l in labels}
    found = [s for s in SIZES if cfg["labels"]["size"][s].lower() in names]
    return found[-1] if found else None


def has_risk_label(cfg: dict, labels) -> bool:
    return cfg["labels"]["risk"].lower() in {str(l).lower() for l in labels}


def owner_name(cfg: dict) -> tuple:
    owner, name = cfg["github_repo"].split("/")
    return owner, name
