#!/usr/bin/env python3
"""Write the agent docs into a repo from the plugin's templates.

  docs/agents/issue-tracker.md   from templates/issue-tracker-linear.md
  docs/agents/triage-labels.md   from templates/triage-labels-linear.md
  docs/agents/orchestration.md   from templates/orchestration.md (kept if present, unless --force)
  CLAUDE.md                      the "## Agent skills" section, replaced in place

The repo's own "### Domain docs" text is kept. Dry run by default: prints a
diff summary. --apply writes. Rerunning with no config change writes nothing.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from linearlib.config import initiative_name  # noqa: E402
from linearlib import cli, config as config_mod  # noqa: E402

ADAPTER = Path(__file__).resolve().parent.parent
PLUGIN = ADAPTER.parent.parent
TEMPLATES = ADAPTER / "templates"


def values(cfg: dict) -> dict:
    return {
        "TEAM_KEY": cfg["team"]["key"],
        "WORKSPACE_ID": cfg["workspace_id"],
        "INITIATIVE": initiative_name(cfg) or "(none)",
        "FLOW_SCRIPTS": str(PLUGIN / "scripts"),
        "ADAPTER_SCRIPTS": str(ADAPTER / "scripts"),
        "SLACK_PREFIX": cfg.get("slack_prefix") or "<prefix>",
        "LINEAR_TEAM_URL": f"{config_mod.linear_base_url(cfg)}/team/{cfg['team']['key']}/triage",
    }


def render(text: str, vals: dict) -> str:
    out = text
    for k, v in vals.items():
        out = out.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{[A-Z_]+\}\}", out)
    if left:
        raise ValueError(f"unfilled placeholders: {sorted(set(left))}")
    return out


def section(text: str, heading: str, level: int):
    """(start, end) of a markdown section at `level`, or None."""
    marks = "#" * level
    m = re.search(rf"^{marks} {re.escape(heading)}\s*$", text, re.MULTILINE)
    if not m:
        return None
    nxt = re.compile(rf"^#{{1,{level}}} ", re.MULTILINE).search(text, m.end())
    return m.start(), (nxt.start() if nxt else len(text))


def merge_claude_md(current: str, block: str) -> str:
    """Replace the Agent skills section, keeping the repo's own Domain docs text."""
    span = section(current, "Agent skills", 2)
    if span is not None:
        old = current[span[0] : span[1]]
        dom_old = section(old, "Domain docs", 3)
        dom_new = section(block, "Domain docs", 3)
        if dom_old and dom_new:
            block = block[: dom_new[0]] + old[dom_old[0] : dom_old[1]].rstrip() + "\n\n" + block[dom_new[1] :].lstrip()
        return current[: span[0]] + block.rstrip() + "\n" + ("\n" + current[span[1] :] if span[1] < len(current) else "")
    return current.rstrip() + "\n\n" + block.rstrip() + "\n"


def main() -> None:
    p = cli.parser(__doc__)
    p.add_argument("--root", default=".", help="repo root (default: here)")
    p.add_argument("--force", action="store_true", help="overwrite docs/agents/orchestration.md too")
    args = p.parse_args()
    cfg = cli.load(args)
    root = Path(args.root).resolve()
    vals = values(cfg)
    print("APPLY: writing files" if args.apply else "DRY RUN: no file is changed (pass --apply)")

    plans = []
    for src, dst, keep in (
        ("issue-tracker-linear.md", "docs/agents/issue-tracker.md", False),
        ("triage-labels-linear.md", "docs/agents/triage-labels.md", False),
        ("orchestration.md", "docs/agents/orchestration.md", not args.force),
    ):
        target = root / dst
        new = render((TEMPLATES / src).read_text(), vals)
        if target.exists() and keep:
            plans.append((target, None, "kept (the repo's own; --force to replace)"))
            continue
        old = target.read_text() if target.exists() else None
        plans.append((target, new if new != old else None, "up to date" if new == old else ("update" if old else "create")))

    claude = root / "CLAUDE.md"
    current = claude.read_text() if claude.exists() else ""
    block = render((TEMPLATES / "claude-md-block.md").read_text(), vals)
    merged = merge_claude_md(current, block)
    plans.append((claude, merged if merged != current else None, "update Agent skills" if merged != current else "up to date"))

    for target, content, what in plans:
        print(f"  {target.relative_to(root)}: {what}")
        if content is not None and args.apply:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)


if __name__ == "__main__":
    main()
