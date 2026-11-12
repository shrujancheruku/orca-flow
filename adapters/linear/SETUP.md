# /flow:setup with Linear as the tracker

Followed by `/flow:setup` when the founder wants Linear. Every script here is in `${CLAUDE_PLUGIN_ROOT}/adapters/linear/scripts`, reads `docs/agents/linear.json` (the tracker-neutral keys may sit in `docs/agents/flow.json`, which should say `"tracker": "linear"`), and is a **dry run** until you pass `--apply`. Reruns are safe.

Writes to Linear and GitHub are the founder's call. Show each dry run, say what `--apply` would change, and wait for a yes before applying. The Linear API key stays in the Keychain; read it only through the scripts.

## Steps

1. **Wizard.** Ask the founder to run `${CLAUDE_PLUGIN_ROOT}/adapters/linear/wizard.sh` in their own terminal once the config exists (step 2). It stores the key, connects Orca, turns Triage on, and sets up GitHub and Slack. Until the key is stored, do steps 2 and 3 by asking.

2. **Config.** Write `docs/agents/linear.json` against `${CLAUDE_PLUGIN_ROOT}/adapters/linear/schema/linear.schema.json`. `adapters/linear/examples/` holds a filled one. Get the team key and id from `orca linear team list --workspace all --json`, the repo from `git remote -v`, and the initiative name (the current phase) and Keychain service from the founder. Look at the repo's GitHub labels (`gh label list`) and map-like or spec-like issues, and set `labels` and `projects` to fit. Ask about `risk_paths`.
   Done when `python3 -c "import sys; sys.path.insert(0,'${CLAUDE_PLUGIN_ROOT}/adapters/linear/scripts'); from linearlib import config; config.load()"` passes.

3. **Team.** `setup_team.py`: the In Review state, the estimate scale, the labels, the project labels and the initiative.

4. **Migrate.** `migrate.py --github-cache <scratch file>` fetches once and prints the plan. Check it with the founder:
   - every map and spec became a project, with the right name and summary;
   - the state counts match the open and closed issues;
   - the unmapped labels are meant to be kept or dropped.
   Fix the config and rerun until the plan is right. Then `--apply`. A failed run resumes from `docs/agents/linear-mapping.json`.

5. **Verify.** `verify.py` until it reports no problems. Do not go on with a problem open.

6. **References.** `rewrite_refs.py` turns `#N` issue refs in the repo's markdown into Linear links. PR numbers stay. Read the flagged lines and fix the ones that are wrong by hand.

7. **Docs.** `seed_linear_docs.py` writes `docs/agents/issue-tracker.md`, `docs/agents/triage-labels.md`, `docs/agents/orchestration.md` and the `## Agent skills` block in `CLAUDE.md`. These replace GitHub-tracker versions of the same files, so check the diff with the founder. Read the orchestration routing table with the founder; it is theirs to tune.

8. **Estimates.** `estimate_linear.py propose` asks Haiku for a size per open ticket and writes `estimate-proposals.json`. The founder marks the ones they accept `"approved": true`. Then `estimate_linear.py apply --apply`.

9. **Cutover.** Last, after the founder has looked at the issues in Linear. `cutover.py` comments "Moved to" on each GitHub issue, closes the open ones, and writes `.github/ISSUE_TEMPLATE/config.yml` so new issues go to Linear.

10. **Commit.** Commit the config, the mapping file, the seeded docs, the rewritten refs and the issue template on a branch, in Conventional Commits.

Done when `verify.py` is clean, every GitHub issue says where it moved, and `CLAUDE.md` points at Linear.
