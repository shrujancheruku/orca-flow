#!/usr/bin/env python3
"""Seed the agent docs for the GitHub tracker, beside Matt Pocock's.

  docs/agents/issue-tracker.md   adds an "Orca and milestones" section
  docs/agents/triage-labels.md   adds a "Flow labels" section (when the file exists)
  docs/agents/orchestration.md   created from templates/orchestration.md; never replaced
  CLAUDE.md                      adds an "### Orchestration" block under "## Agent skills"

Matt's skill (/setup-matt-pocock-skills) writes issue-tracker.md first; this
refuses to run without it. Our text sits between <!-- flow:begin ... --> and
<!-- flow:end ... --> comments and only that is ever rewritten, so your own
text is safe and a rerun with no change writes nothing. Dry run by default.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flowlib import cli, seeding  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent
TEMPLATES = PLUGIN / "templates"
MISSING_MATT = "docs/agents/issue-tracker.md is missing. Run /setup-matt-pocock-skills first, then rerun this."


def values(cfg: dict) -> dict:
    size = cfg["labels"]["size"]
    return {
        "REPO": cfg["github_repo"],
        "FLOW_SCRIPTS": str(PLUGIN / "scripts"),
        "SLACK_PREFIX": cfg.get("slack_prefix") or "<prefix>",
        "SIZE_S": size["S"],
        "SIZE_M": size["M"],
        "SIZE_L": size["L"],
        "RISK_LABEL": cfg["labels"]["risk"],
        "INTEGRATED_LABEL": cfg["labels"]["integrated"],
    }


def template(name: str, vals: dict) -> str:
    return seeding.render((TEMPLATES / name).read_text(), vals)


def plan(root: Path, vals: dict) -> list:
    """[(path, new content or None, what)]. Pure apart from reading the repo."""
    tracker = root / "docs/agents/issue-tracker.md"
    if not tracker.exists():
        raise seeding.SeedError(MISSING_MATT)
    plans = []

    def marked(path: Path, name: str, tmpl: str):
        old = path.read_text()
        new = seeding.upsert(old, name, template(tmpl, vals))
        plans.append((path, new if new != old else None, "up to date" if new == old else
                      ("update the flow section" if f"flow:begin {name}" in old else "add the flow section")))

    marked(tracker, "orca-milestones", "issue-tracker-orca-section.md")

    labels = root / "docs/agents/triage-labels.md"
    if labels.exists():
        marked(labels, "flow-labels", "triage-labels-flow-section.md")
    else:
        plans.append((labels, None, "skipped (Matt's file is absent; the triage skill may not be installed)"))

    orch = root / "docs/agents/orchestration.md"
    new = template("orchestration.md", vals)
    if not orch.exists():
        plans.append((orch, new, "create"))
    else:
        plans.append((orch, None, "kept (yours; the routing table is yours to tune)" if orch.read_text() != new
                      else "up to date"))

    claude = root / "CLAUDE.md"
    old = claude.read_text() if claude.exists() else ""
    merged = seeding.upsert_in_agent_skills(old, "orchestration", template("claude-md-block.md", vals))
    plans.append((claude, merged if merged != old else None,
                  "up to date" if merged == old else "update the Orchestration block"))
    return plans


def main() -> None:
    p = cli.parser(__doc__)
    p.add_argument("--root", default=".", help="repo root (default: here)")
    args = p.parse_args()
    cfg = cli.load(args)
    root = Path(args.root).resolve()
    print("APPLY: writing files" if args.apply else "DRY RUN: no file is changed (pass --apply)")
    try:
        plans = plan(root, values(cfg))
    except (seeding.SeedError, ValueError) as exc:
        cli.die(str(exc))
    for target, content, what in plans:
        print(f"  {target.relative_to(root)}: {what}")
        if content is not None and args.apply:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)


if __name__ == "__main__":
    main()
