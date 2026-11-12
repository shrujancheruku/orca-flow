"""Pure parts of the estimator: the prompt, the answer parser and risk hints."""

from __future__ import annotations

import fnmatch
import json
import re

PROMPT = """You size one ticket for a coding agent. Answer with JSON only.

Sizes:
- S: one small change in one or two files, clear acceptance criteria, no design choices.
- M: a few files or one module, some judgement, tests to write.
- L: several modules, new seams or schemas, or open design questions.

Risk means the ticket touches auth, data migrations, data deletion, a public API,
or one of these paths: {risk_paths}.

Ticket {identifier}: {title}

{description}

Answer exactly: {{"size": "S|M|L", "risk": true|false, "reason": "one sentence"}}
"""


def build_prompt(issue: dict, cfg: dict, limit: int = 12000) -> str:
    description = (issue.get("description") or "").strip()
    if len(description) > limit:
        description = description[:limit] + "\n[truncated]"
    return PROMPT.format(
        risk_paths=", ".join(cfg.get("risk_paths") or ["(none named)"]),
        identifier=issue["identifier"],
        title=issue["title"],
        description=description or "(no description)",
    )


def parse_answer(text: str) -> dict:
    """Pull the JSON answer out of the model's reply."""
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        raise ValueError("no JSON in the answer")
    data = json.loads(m.group(0))
    size = str(data.get("size", "")).upper()
    if size not in ("S", "M", "L"):
        raise ValueError(f"bad size {data.get('size')!r}")
    return {"size": size, "risk": bool(data.get("risk")), "reason": str(data.get("reason", ""))[:300]}


def parse_claude_json(stdout: str) -> str:
    """`claude -p --output-format json` prints one object with a `result` string."""
    data = json.loads(stdout)
    if data.get("is_error"):
        raise ValueError(f"claude reported an error: {str(data.get('result'))[:200]}")
    return data.get("result", "")


def risk_hints(text: str, cfg: dict) -> list:
    """Mechanical hints: named risk paths or keywords that appear in the ticket."""
    hints = []
    low = (text or "").lower()
    for pattern in cfg.get("risk_paths", []):
        bare = pattern.rstrip("*").rstrip("/")
        if bare and bare.lower() in low:
            hints.append(f"path {pattern}")
        else:
            for token in re.findall(r"[\w./-]+/[\w./-]+", text or ""):
                if fnmatch.fnmatch(token, pattern):
                    hints.append(f"path {pattern}")
                    break
    for word in cfg.get("risk_keywords", []):
        if re.search(rf"\b{re.escape(word.lower())}", low):
            hints.append(f"word {word}")
    return hints
