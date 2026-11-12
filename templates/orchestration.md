# Orchestration

How a spec gets built here. `/flow:build` follows this file. Tickets are GitHub issues, a build milestone is a GitHub Milestone, and `gh` is the only tracker tool (Orca has no GitHub issue commands).

## Layers

- **Procedure:** Matt Pocock's `/implement-spec`, unmodified. Read its `SKILL.md` and follow it.
- **Policy:** this file. Where it and `implement-spec` differ, this file wins.
- **Executor:** Orca. The implementer, merger, checker, fixer and reviewer are Orca workers. Short read-only jobs (exploration, `code-review`'s two reviewers) are subagents inside a worker. On an agent with no subagents, they become their own Orca workers.
- **Tracker:** GitHub Issues. See `docs/agents/issue-tracker.md`.
- **Measurement:** `{{FLOW_SCRIPTS}}/profile.py`.

`${CLAUDE_PLUGIN_ROOT}` is the installed `flow` plugin's folder. `/flow:build` expands it; outside it, run `claude plugin list` to find the path.

## Model routing

Before every worker, run `python3 {{FLOW_SCRIPTS}}/route.py --role <role> --ticket <n> --lookup` and pass the `flags` (`--agent`, `--model`, `--effort`) and `task_title` it prints. Read the row from this table each time; never route from memory. The Model column names a profile in `models` in `docs/agents/flow.json`, which says which Orca agent and model id it runs on. Always pass `--model`: the user's own settings default to Opus.

| Key | Role | Model | Effort | Notes |
|---|---|---|---|---|
| coordinator | Coordinator | opus | medium | The session running `/flow:build`. |
| scout | Exploration or scout | haiku | low | A subagent inside a worker. |
| build.S | Implementer, size S, no `risk` | haiku | | Escalates once; see Escalation. |
| build.S.risk | Implementer, size S, `risk` | sonnet | medium | |
| build.M | Implementer, size M | sonnet | medium | |
| build.M.risk | Implementer, size M, `risk` | sonnet | high | |
| build.L | Implementer, size L | sonnet | high | |
| build.L.risk | Implementer, size L, `risk` | opus | | |
| build.escalated | Implementer after an escalation | sonnet | medium | A fresh worker on the same branch. |
| merge | Merger | haiku | low | |
| merge.conflict | Merger on a real conflict | sonnet | medium | |
| check | Spec check before a ticket merges into the integration branch | haiku | low | One per ticket. |
| review | Integration `code-review`, once per milestone | sonnet | high | |
| review.risk | Integration `code-review`, milestone has `risk` tickets | opus | | |
| fix | Fixer | sonnet | medium | |

Size comes from the issue's `{{SIZE_S}}`, `{{SIZE_M}}` or `{{SIZE_L}}` label. The `{{RISK_LABEL}}` label, or a ticket that names a path in `risk_paths` in `docs/agents/flow.json`, raises the model to the `.risk` row. A ticket with no size label routes as M and `route.py` warns; run `estimate.py propose` for the founder to approve sizes.

For `review`, pass the integration PR's number as `--ticket`.

Put the model in the Orca task title: `#123 · build · haiku`. The profiler reads it.

## Starting a worker

1. `orca reference find https://github.com/{{REPO}}/issues/<n> --json` first. If a workspace or agent is already attached to the issue, resume or read it instead of starting another. (Orca wants the issue URL; a bare number is not supported.)
2. `orca worktree create --issue <n> --name "<n>-<slug>" --base-branch integration/<milestone-slug> --no-parent --json` makes the ticket's worktree and links it to the issue.
3. `orca orchestration worker-start --worktree issue:<n> --task-title "<task_title from route.py>" <flags from route.py> --spec-file -`, with the brief on stdin. The brief holds context pointers: the issue URL, the spec, the exploration notes, the integration branch.

The merger, checker, fixer and reviewer start the same way: a `--task-title` of the shape `#<n> · <role> · <model>`, and the flags from `route.py`.

## Escalation

1. An S implementer on Haiku escalates once when any of these happens:
   - it stops and the stop cannot be resolved by an answer;
   - CI fails on its branch a second time;
   - review asks for changes a second time.
2. Start a fresh worker with `route.py --role build --variant escalated` on the same branch. Tell it what the first worker tried.
3. A second escalation goes to the founder: comment on the issue, add `needs-info`, remove `ready-for-agent`.

## Holds

Before dispatching a ticket, compare its touch map (the paths in its "What to build" section) with:

- open PRs,
- tickets in progress,
- exclusive holds the founder named.

Overlap means wait. Shared registries (one file per entry plus an index) do not count as overlap.

## Frontier

A ticket is on the frontier when it is open, labelled `ready-for-agent`, unassigned, has no Orca workspace on it (`orca reference find`), and every blocker is closed or labelled `{{INTEGRATED_LABEL}}`. An `{{INTEGRATED_LABEL}}` blocker counts as done: its work is already on the integration branch, though the issue stays open until the integration PR merges into main.

Blockers are the issue's native dependencies (`gh api repos/{{REPO}}/issues/<n>/dependencies/blocked_by`), or the `Blocked by: #<n>` line at the top of the body where dependencies are off.

`implement-spec` warns that the frontier goes stale because the issues it waits on stay open. Track merges yourself: when a merger lands a ticket, add `{{INTEGRATED_LABEL}}` to it and recompute.

## Branches and merging

- A build milestone is a GitHub Milestone. Its tickets carry that milestone.
- One integration branch (`integration/<milestone-slug>`) and one draft PR into main per milestone. Open the draft after the first merge, with `--milestone`.
- The Haiku `check` worker passes a ticket before it merges into the integration branch. A failed check goes back to the implementer; it is not merged.
- A ticket merged into the integration branch gets the `{{INTEGRATED_LABEL}}` label (`gh issue edit <n> --add-label {{INTEGRATED_LABEL}}`). Do not close it.
- The integration PR body has one `Closes #<n>` line per ticket, kept current as tickets land. When the founder merges the PR into main, GitHub closes those tickets.
- The founder merges integration PRs.

## Automerge

Off. The coordinator never merges an integration PR on its own.

The founder may turn it on for one run by telling the coordinator. Then the coordinator merges the integration PR when CI is green and the integration review passed. It ends with that run.

## Usage limits

On the first usage-limit error from any worker:

1. Stop dispatching.
2. Comment "Paused: usage limit, resets at <time>" on each ticket in progress.
3. Resume after the reset.

Wait out the limit on the same models. Switching model to dodge a limit breaks the profile.

## Stops

A worker stops and reports with `orca orchestration send --type escalation` for one of these reasons:

- `held-path`: the ticket needs a path someone else holds.
- `no-spec`: the ticket has no acceptance criteria.
- `ambiguous`: the ticket reads two ways.
- `adr-conflict`: the ticket contradicts an ADR or `docs/current-state.md`.
- `human-only`: a step only the founder can take.
- `verify-outside-ticket`: proof needs work outside the ticket.
- `already-done`: the work is already on the integration branch.

## Profiling

At the end of each milestone, run:

```
python3 {{FLOW_SCRIPTS}}/profile.py --run <run id> --coordinator <coordinator transcript> --pr <integration PR number> --apply
```

Read the HTML it writes. `--pr ... --apply` has the coordinator post the summary as a comment on the integration PR. The profile is unverified until the first real run.

## Slack

Agents write to GitHub only. The GitHub Slack app posts for `{{REPO}}`: `#{{SLACK_PREFIX}}-prs` hears pull requests, reviews and comments, and `#{{SLACK_PREFIX}}-needs-you` hears issues labelled `ready-for-human` or `needs-info`.
