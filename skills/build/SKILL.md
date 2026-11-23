---
name: build
description: Build a spec from GitHub Issues on Orca workers, with Matt Pocock's /implement-spec as the procedure.
disable-model-invocation: true
---

You are the **coordinator**. Build the named spec (a GitHub issue and its tickets) or one milestone of it. A build milestone is a GitHub Milestone.

If `docs/agents/flow.json` says `"tracker": "linear"`, read `${CLAUDE_PLUGIN_ROOT}/adapters/linear/BUILD.md` instead of the rest of this file.

Read Matt Pocock's `implement-spec` `SKILL.md` (in the `mattpocock-skills` plugin, `skills/engineering/implement-spec/`) and follow its steps. Then read `docs/agents/orchestration.md`: it is the policy, and where it and `implement-spec` differ, it wins. These overrides always hold:

- **Sync first.** Before the first worker, run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/seed_docs.py`. If it lists a change (a plugin release moved a default, or the routing table is still kept by hand), run it with `--apply` and commit the files it names on the integration branch as `docs(agents): sync the flow plugin's defaults`. It rewrites only the text between its own markers, and `routing` in `flow.json` when a hand-kept table had rows of its own. If `route.py` later warns that the table is out of date, do the same.
- **Workers.** Each implementer, merger, checker, reviewer and fixer is an Orca worker, not a Claude subagent. Exploration stays a subagent inside a worker. Create each ticket's worker with `orca worktree create --issue <n> ...` then `orca orchestration worker-start --worktree issue:<n> ...`, as `docs/agents/orchestration.md` ("Starting a worker") spells out. Check `orca reference find <issue URL>` first so you do not start a second worker on a ticket.
- **Routing.** Before every worker, run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/route.py --role <role> --ticket <n> --lookup` and pass the `flags` it prints. Pass its `task_title` (`#123 · build · haiku`) as the `--task-title`: the profiler parses it.
- **Tracker.** Read and write tickets with `gh`, as `docs/agents/issue-tracker.md` says. Orca has no GitHub issue commands.
- **Milestone.** One integration branch (`integration/<milestone-slug>`) and one draft PR into main per milestone, opened with `--milestone`. The PR body lists `Closes #<n>` for each ticket, kept current as tickets land, so merging it closes them.
- **Check, then merge.** A Haiku `check` worker verifies each ticket against its acceptance criteria before the merger merges it into the integration branch.
- **Rulings.** A `check` that fails only on paperwork (docs wording, a missing README row, how the proof is written up) while every acceptance criterion about behaviour passed may be ruled accepted, instead of a round back to the implementer and a second check: comment the ruling on the ticket, record the miss with `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/notes.py --add "<what is missing>" --ticket <n>`, and merge. A fail on behaviour, a criterion, safety or a risk path always goes back to the implementer. The integration review's brief includes the output of `notes.py --markdown`, and the fixer clears each note it fixes with `notes.py --done <id>`. The status footer counts the notes still carried.
- **Frontier.** When a ticket merges into the integration branch, add the `integrated` label (`gh issue edit <n> --add-label integrated`); do not close it. A blocker that is closed or labelled `integrated` counts as satisfied. Recompute the frontier after every merge.
- **Merging to main.** The founder merges the integration PR. Merge it yourself only when the founder turned automerge on for this run.
- **Stops, holds, escalation and usage limits** follow `docs/agents/orchestration.md`.
- **Status footer.** End every turn with the output of `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/status.py --plain`, verbatim, in a fenced `text` block: what is in progress and what waits on the founder. When you ask the founder something, record it then with `status.py --ask "<question>" [--ticket <n>] [--where <where they answer>]`, and clear it with `status.py --done <id>` once answered. It reads GitHub Issues; with the Linear tracker it shows only Orca and the asks.

- **Cleanup.** Once the integration PR is merged, run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/cleanup.py --run <run id>` from the repo, read what it would remove and what it keeps and why, then run it with `--apply`. Never remove a run's worktrees with `orca worktree rm`: it hangs and leaves each checkout behind. The script removes them with `git worktree remove`, never forces, and keeps any worktree with uncommitted files or a HEAD on no remote branch. Branches stay.

- **Before ready.** A fix round that passes locally is not done. After the fixer's work lands on the integration branch, wait for the integration PR's checks on that tip (`gh pr checks <PR>`): a red check is another fix round (a fresh `fix` worker, told which job failed and given its log), never a reason to mark the PR ready. Then read `gh pr view <PR> --json mergeStateStatus`: when it is `BEHIND` or `DIRTY`, a `merge` worker merges the base branch into the integration branch, runs the verify commands on the merged tree and pushes without force, and the checks are waited on again. Only a PR that is green on its final tip and up to date with its base is marked ready.

When the milestone's last ticket is `integrated`, the integration review is fixed and the PR is green and up to date as "Before ready" says, run the profiler as `docs/agents/orchestration.md` says (`profile.py ... --pr <integration PR> --apply` comments the summary on the integration PR), and report the PR link and the profile summary.
