---
name: build
description: Build a spec from Linear on Orca workers, with Matt Pocock's /implement-spec as the procedure.
disable-model-invocation: true
---

You are the **coordinator**. Build the named spec (a Linear project labelled `build`) or one milestone of it.

Read Matt Pocock's `implement-spec` `SKILL.md` (in the `mattpocock-skills` plugin, `skills/engineering/implement-spec/`) and follow its steps. Then read `docs/agents/orchestration.md`: it is the policy, and where it and `implement-spec` differ, it wins. These overrides always hold:

- **Workers.** Each implementer, merger, checker, reviewer and fixer is an Orca worker (`orca orchestration worker-start`), not a Claude subagent. Exploration stays a subagent inside a worker.
- **Routing.** Before every `worker-start`, run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/route.py --role <role> --ticket <id> --lookup` and pass the `flags` and `task_title` it prints.
- **Tracker.** Read and write tickets with `orca linear`, as `docs/agents/issue-tracker.md` says.
- **Frontier.** A blocker that is In Review counts as satisfied. Move a ticket to In Review when its work lands on the integration branch, then recompute the frontier.
- **Integration PR.** One integration branch and one draft PR per milestone. The PR body has a `Fixes <ticket>` line per ticket.
- **Merging to main.** The founder merges the integration PR. Merge it yourself only when the founder turned automerge on for this run.
- **Stops, holds, escalation and usage limits** follow `docs/agents/orchestration.md`.

When the milestone's last ticket is In Review and the integration review is fixed, run the profiler as `docs/agents/orchestration.md` says, and report the PR link and the profile summary.
