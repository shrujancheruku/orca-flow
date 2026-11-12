"""Load and check docs/agents/linear.json.

The config holds every per-repo value. Nothing project-specific lives in code.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

DEFAULT_PATH = "docs/agents/linear.json"

DEFAULTS = {
    "states": {
        "triage": "Triage",
        "backlog": "Backlog",
        "todo": "Todo",
        "in_progress": "In Progress",
        "in_review": "In Review",
        "done": "Done",
        "canceled": "Canceled",
        "duplicate": "Duplicate",
    },
    "labels": {
        "needs_info": "needs-info",
        "ready_for_agent": "ready-for-agent",
        "ready_for_human": "ready-for-human",
        "risk": "risk",
        "wayfinder_prefix": "wayfinder:",
        "retired": ["wayfinder:map"],
        "rename": {"bug": "Bug", "enhancement": "Feature"},
        "size_prefix": "size:",
        "unmapped": "keep",
        "workspace": [],
    },
    "project_labels": {"wayfinder": "wayfinder", "build": "build"},
    "projects": {
        "map_labels": ["wayfinder:map"],
        "map_title_prefixes": ["Map:"],
        "spec_title_prefixes": ["Spec:"],
        "extra": [],
        "names": {},
        "summary_sections": ["Problem Statement"],
    },
    "estimate_scale": {
        "linear_type": "tShirt",
        "sizes": {"S": 2, "M": 3, "L": 5},
    },
    "risk_paths": [],
    "risk_keywords": ["auth", "migration", "delete", "public api"],
    "mapping_file": "docs/agents/linear-mapping.json",
    "orchestration_doc": "docs/agents/orchestration.md",
    "models": {"haiku": "haiku", "sonnet": "sonnet", "opus": "opus"},
    "slack_prefix": "",
}

REQUIRED = [
    ("workspace_id",),
    ("workspace_url_key",),
    ("team", "key"),
    ("team", "id"),
    ("keychain_service",),
    ("github_repo",),
    ("initiative", "name"),
]


class ConfigError(Exception):
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
    problems = []
    for path in REQUIRED:
        node = cfg
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        if node in (None, ""):
            problems.append("missing " + ".".join(path))
    repo = cfg.get("github_repo", "")
    if repo and repo.count("/") != 1:
        problems.append("github_repo must be owner/name")
    sizes = cfg.get("estimate_scale", {}).get("sizes", {})
    if set(sizes) != {"S", "M", "L"}:
        problems.append("estimate_scale.sizes needs exactly S, M and L")
    elif not sizes["S"] < sizes["M"] < sizes["L"]:
        problems.append("estimate_scale.sizes must rise S < M < L")
    if cfg.get("labels", {}).get("unmapped") not in ("keep", "drop"):
        problems.append("labels.unmapped must be keep or drop")
    return problems


def from_dict(raw: dict) -> dict:
    cfg = _merge(DEFAULTS, {k: v for k, v in raw.items() if k != "$schema"})
    env_service = os.environ.get("LINEAR_KEYCHAIN_SERVICE")
    if env_service:
        cfg["keychain_service"] = env_service
    problems = check(cfg)
    if problems:
        raise ConfigError("config problems: " + "; ".join(problems))
    return cfg


def load(path: str | None = None) -> dict:
    p = Path(path or os.environ.get("FLOW_CONFIG") or DEFAULT_PATH)
    if not p.exists():
        raise ConfigError(f"no config at {p}. Copy examples/*.json or run /flow:setup.")
    with p.open() as fh:
        raw = json.load(fh)
    cfg = from_dict(raw)
    cfg["_path"] = str(p)
    return cfg


def owner_name(cfg: dict) -> tuple:
    owner, name = cfg["github_repo"].split("/")
    return owner, name


def linear_base_url(cfg: dict) -> str:
    return f"https://linear.app/{cfg['workspace_url_key']}"
