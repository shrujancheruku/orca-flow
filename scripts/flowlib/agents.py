"""Profiles: what a model name in the routing table runs on.

This is the only module that knows an agent CLI. The routing table names a
profile (haiku, sonnet, ...), and `models` in flow.json maps each profile to
an Orca agent and that agent's model id:

    "models": {"haiku": "haiku"}                                  # claude, model haiku
    "models": {"coder": {"agent": "opencode", "model": "openrouter/x/y"}}

Only Claude has a headless runner (the estimator) and a transcript reader (the
profiler). To add another agent, add its entry to RUNNERS and TRANSCRIPTS.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

DEFAULT_AGENT = "claude"


class AgentError(Exception):
    pass


def profile(name: str, models: dict) -> dict:
    """{"name", "agent", "model"} for one profile name from the routing table."""
    key = (name or "").strip().lower()
    if key not in models:
        raise AgentError(f"unknown model {name!r}: add it to `models` in flow.json")
    entry = models[key]
    if isinstance(entry, str):
        entry = {"model": entry}
    if not isinstance(entry, dict) or not entry.get("model"):
        raise AgentError(f"models.{key} needs a model id")
    return {"name": key, "agent": entry.get("agent") or DEFAULT_AGENT, "model": entry["model"]}


def check_models(models) -> list:
    if not isinstance(models, dict) or not models:
        return ["models must map each routing-table model name to a model id or {agent, model}"]
    problems = []
    for name in models:
        try:
            profile(name, models)
        except AgentError as exc:
            problems.append(str(exc))
    return problems


# --- headless one-shot calls (the estimator) ---

def parse_claude_json(stdout: str) -> str:
    """`claude -p --output-format json` prints one object with a `result` string."""
    data = json.loads(stdout)
    if data.get("is_error"):
        raise ValueError(f"claude reported an error: {str(data.get('result'))[:200]}")
    return data.get("result", "")


RUNNERS = {
    "claude": (lambda model: ["claude", "-p", "--model", model, "--output-format", "json"], parse_claude_json),
}


def ask(prof: dict, prompt: str, timeout: int) -> str:
    """Send one prompt headless and return the answer text."""
    if prof["agent"] not in RUNNERS:
        raise AgentError(f"no headless runner for agent {prof['agent']!r}; add one to flowlib/agents.py")
    argv, parse = RUNNERS[prof["agent"]]
    out = subprocess.run(argv(prof["model"]), input=prompt, capture_output=True, text=True,
                         timeout=timeout, check=False)
    if out.returncode != 0:
        raise RuntimeError(f"{prof['agent']} exited {out.returncode}: {out.stderr.strip()[:200]}")
    return parse(out.stdout)


# --- where an agent keeps its transcripts (the profiler) ---

def _claude_root() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    return Path(base).expanduser() / "projects"


TRANSCRIPTS = {"claude": _claude_root}


def transcript_root(agent: str):
    """The folder an agent's transcripts live under, or None when we cannot read that agent yet."""
    fn = TRANSCRIPTS.get(agent)
    return fn() if fn else None
