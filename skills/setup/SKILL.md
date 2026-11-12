---
name: setup
description: Set up this repo to run Matt Pocock's skills on GitHub Issues and Orca. Linear is an optional adapter.
disable-model-invocation: true
---

Set up the current repo so Matt Pocock's skills track work in GitHub Issues and `/flow:build` runs specs on Orca.

Every script lives in `${CLAUDE_PLUGIN_ROOT}/scripts`, reads `docs/agents/flow.json`, and is a **dry run** until you pass `--apply`. Reruns are safe: each script skips what already exists, and seeding only rewrites the text between its own `<!-- flow:begin ... -->` markers.

Writes to GitHub are the founder's call. Show each dry run, say what `--apply` would change, and wait for a yes before applying.

**Linear.** If the founder wants Linear as the tracker (or is moving from GitHub to Linear), stop here and follow `${CLAUDE_PLUGIN_ROOT}/adapters/linear/SETUP.md` instead. Otherwise continue.

## Steps

1. **Matt's skills.** Check that `docs/agents/issue-tracker.md` exists. If it does not, tell the founder to run `/setup-matt-pocock-skills` first (pick GitHub, keep the default triage labels), and stop until they have.

2. **Config.** Write `docs/agents/flow.json` against `${CLAUDE_PLUGIN_ROOT}/schema/flow.schema.json`; `${CLAUDE_PLUGIN_ROOT}/examples/flow.json` is a filled one. Get `github_repo` from `git remote -v`. Ask the founder about `risk_paths` (the globs where a mistake is costly) and the Slack prefix. Leave the label names at their defaults unless the repo already uses others.
   Done when `python3 -c "import sys; sys.path.insert(0,'${CLAUDE_PLUGIN_ROOT}/scripts'); from flowlib import config; config.load()"` passes.

3. **Labels.** `setup_labels.py` shows which of `size:S`, `size:M`, `size:L`, `risk` and `integrated` are missing; after a yes, `setup_labels.py --apply`. It also checks Matt's five triage labels and reports any that are missing. It creates none of them: if some are missing, tell the founder to rerun `/setup-matt-pocock-skills`.

4. **Docs.** `seed_docs.py` adds an "Orca and milestones" section to `docs/agents/issue-tracker.md` and a "Flow labels" section to `docs/agents/triage-labels.md`, writes `docs/agents/orchestration.md` if it is not there, and adds an Orchestration block to `CLAUDE.md`. Matt's own text is not touched. Read the routing table in `orchestration.md` with the founder; it is theirs to tune.

5. **Sizes.** `estimate.py propose` asks Haiku about each open issue (an existing `size:` label is kept as the proposal and double-checked) and writes `estimate-proposals.json`. The founder sets `"approved": true` on the ones they accept, changing `"size"` first where they disagree. Then `estimate.py apply`, and with their yes `estimate.py apply --apply`.

6. **Wizard.** Ask the founder to run `${CLAUDE_PLUGIN_ROOT}/wizard/wizard.sh` in their own terminal: it covers importing the repo into Orca, the GitHub Slack app and updating Matt's plugin.

7. **Commit.** Commit `docs/agents/flow.json`, the seeded docs and `CLAUDE.md` on a branch, in Conventional Commits.

Done when `setup_labels.py` reports nothing to create and no missing triage labels, and `CLAUDE.md` has the Orchestration block.
