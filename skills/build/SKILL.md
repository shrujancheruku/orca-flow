---
name: build
description: Build a spec from GitHub Issues on Orca workers, with Matt Pocock's /implement-spec as the procedure.
disable-model-invocation: true
---

You are the **coordinator**. Build the named spec (a GitHub issue and its tickets) or one milestone of it. A build milestone is a GitHub Milestone.

If `docs/agents/flow.json` says `"tracker": "linear"`, read `${CLAUDE_PLUGIN_ROOT}/adapters/linear/BUILD.md` instead of the rest of this file.

Read Matt Pocock's `implement-spec` `SKILL.md` (in the `mattpocock-skills` plugin, `skills/engineering/implement-spec/`) and follow its steps. Then read `docs/agents/orchestration.md`: it is the policy, and where it and `implement-spec` differ, it wins. These overrides always hold:

- **Workers.** Each implementer, merger, checker, reviewer and fixer is an Orca worker, not a Claude subagent. Exploration stays a subagent inside a worker. Create each ticket's worker with `orca worktree create --issue <n> ...` then `orca orchestration worker-start --worktree issue:<n> ...`, as `docs/agents/orchestration.md` ("Starting a worker") spells out. Check `orca reference find <issue URL>` first so you do not start a second worker on a ticket.
- **Routing.** Before every worker, run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/route.py --role <role> --ticket <n> --lookup` and pass the `flags` it prints. Pass its `task_title` (`#123 · build · haiku`) as the `--task-title`: the profiler parses it.
- **Tracker.** Read and write tickets with `gh`, as `docs/agents/issue-tracker.md` says. Orca has no GitHub issue commands.
- **Milestone.** One integration branch (`integration/<milestone-slug>`) and one draft PR into main per milestone, opened with `--milestone`. The PR body lists `Closes #<n>` for each ticket, kept current as tickets land, so merging it closes them.
- **Check, then merge.** A Haiku `check` worker verifies each ticket against its acceptance criteria before the merger merges it into the integration branch.
- **Frontier.** When a ticket merges into the integration branch, add the `integrated` label (`gh issue edit <n> --add-label integrated`); do not close it. A blocker that is closed or labelled `integrated` counts as satisfied. Recompute the frontier after every merge.
- **Merging to main.** The founder merges the integration PR. Merge it yourself only when the founder turned automerge on for this run.
- **Stops, holds, escalation and usage limits** follow `docs/agents/orchestration.md`.

When the milestone's last ticket is `integrated` and the integration review is fixed, run the profiler as `docs/agents/orchestration.md` says (`profile.py ... --pr <integration PR> --apply` comments the summary on the integration PR), and report the PR link and the profile summary.
