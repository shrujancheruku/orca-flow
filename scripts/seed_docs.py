#!/usr/bin/env python3
"""Seed the agent docs for the GitHub tracker, beside Matt Pocock's.

  docs/agents/issue-tracker.md   adds an "Orca and milestones" section
  docs/agents/triage-labels.md   adds a "Flow labels" section (when the file exists)
  docs/agents/orchestration.md   created from templates/orchestration.md; afterwards only
                                 its routing table is rewritten
  docs/agents/flow.json          gains `routing` once, for rows a hand-kept table had set
  CLAUDE.md                      adds an "### Orchestration" block under "## Agent skills"

Matt's skill (/setup-matt-pocock-skills) writes issue-tracker.md first; this
refuses to run without it. Our text sits between <!-- flow:begin ... --> and
<!-- flow:end ... --> comments and only that is ever rewritten, so your own
text is safe and a rerun with no change writes nothing. Dry run by default.

Run it again after every plugin release (/flow:build does): the marked text
and the routing table follow the plugin's defaults, except for what the config
sets. A routing table kept by hand from before the plugin owned it is handed
over on the first run: rows that differ from every default the plugin has
shipped are the repo's own, and move to `routing` in the config.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flowlib import cli, routing, seeding  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent
TEMPLATES = PLUGIN / "templates"
MISSING_MATT = "docs/agents/issue-tracker.md is missing. Run /setup-matt-pocock-skills first, then rerun this."


def values(cfg: dict) -> dict:
    size = cfg["labels"]["size"]
    return {
        "REPO": cfg["github_repo"],
        "FLOW_SCRIPTS": "${CLAUDE_PLUGIN_ROOT}/scripts",
        "SLACK_PREFIX": cfg.get("slack_prefix") or "<prefix>",
        "SIZE_S": size["S"],
        "SIZE_M": size["M"],
        "SIZE_L": size["L"],
        "RISK_LABEL": cfg["labels"]["risk"],
        "INTEGRATED_LABEL": cfg["labels"]["integrated"],
        "ROUTING_TABLE": seeding.wrap(routing.BLOCK, routing.render(routing.effective(cfg.get("routing")))),
    }


def template(name: str, vals: dict) -> str:
    return seeding.render((TEMPLATES / name).read_text(), vals)


def routing_plan(orch: Path, cfg: dict, size_word: str = "size") -> list:
    """Plans for an existing orchestration doc: its routing table, and the config when rows move into it."""
    old = orch.read_text()
    overrides = dict(cfg.get("routing") or {})
    moved = {}
    if routing.block_text(old) is None:
        try:
            moved = {k: v for k, v in routing.legacy_overrides(routing.parse_table(old)).items()
                     if k.lower() not in {o.lower() for o in overrides}}
        except routing.RoutingError:
            moved = {}
        overrides.update(moved)
    new = routing.place_block(old, routing.effective(overrides, size_word))
    what = ("up to date" if new == old else
            "update the routing table" if routing.block_text(old) is not None else
            "hand the routing table to the plugin (the rest stays yours)")
    plans = [(orch, new if new != old else None, what)]
    if moved and cfg.get("_path"):
        path = Path(cfg["_path"])
        raw = json.loads(path.read_text())
        raw["routing"] = dict(raw.get("routing") or {}, **moved)
        plans.append((path, json.dumps(raw, indent=2) + "\n",
                      "add routing: the rows your table had set (" + ", ".join(sorted(moved)) + ")"))
    return plans


def plan(root: Path, cfg: dict) -> list:
    """[(path, new content or None, what)]. Pure apart from reading the repo."""
    vals = values(cfg)
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
    if not orch.exists():
        plans.append((orch, template("orchestration.md", vals), "create"))
    else:
        plans += routing_plan(orch, cfg)

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
        plans = plan(root, cfg)
    except (seeding.SeedError, ValueError) as exc:
        cli.die(str(exc))
    for target, content, what in plans:
        shown = target.relative_to(root) if target.is_relative_to(root) else target
        print(f"  {shown}: {what}")
        if content is not None and args.apply:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)


if __name__ == "__main__":
    main()
