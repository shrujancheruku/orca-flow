# Orchestration

How a spec gets built here. `/flow:build` follows this file.

## Layers

- **Procedure:** Matt Pocock's `/implement-spec`, unmodified. Read its `SKILL.md` and follow it.
- **Policy:** this file. Where it and `implement-spec` differ, this file wins.
- **Executor:** Orca. The implementer, merger, fixer and reviewer are Orca workers, started with `orca orchestration worker-start`. Short read-only jobs (exploration, `code-review`'s two reviewers) are Claude subagents inside a worker.
- **Tracker:** Linear. See `docs/agents/issue-tracker.md`.
- **Measurement:** `{{FLOW_SCRIPTS}}/profile.py`.

## Model routing

Before every `worker-start`, run `python3 {{ADAPTER_SCRIPTS}}/route_linear.py --role <role> --ticket {{TEAM_KEY}}-<n> --lookup` and pass the `flags` and `task_title` it prints. Read the row from this table each time; never route from memory. Always pass `--model`: the user's own settings default to Opus.

| Key | Role | Model | Effort | Notes |
|---|---|---|---|---|
| coordinator | Coordinator | opus | medium | The session running `/flow:build`. |
| scout | Exploration or scout | haiku | low | A subagent inside a worker. |
| build.S | Implementer, Estimate S, no `risk` | haiku | | Escalates once; see Escalation. |
| build.S.risk | Implementer, Estimate S, `risk` | sonnet | medium | |
| build.M | Implementer, Estimate M | sonnet | medium | |
| build.M.risk | Implementer, Estimate M, `risk` | sonnet | high | |
| build.L | Implementer, Estimate L | sonnet | high | |
| build.L.risk | Implementer, Estimate L, `risk` | opus | | |
| build.escalated | Implementer after an escalation | sonnet | medium | A fresh worker on the same branch. |
| merge | Merger | haiku | low | |
| merge.conflict | Merger on a real conflict | sonnet | medium | |
| check | Spec check before a ticket merges into the integration branch | haiku | low | One per ticket. |
| review | Integration `code-review`, once per milestone | sonnet | high | |
| review.risk | Integration `code-review`, milestone has `risk` tickets | opus | | |
| fix | Fixer | sonnet | medium | |

Size comes from the Linear Estimate, banded by `estimate_scale` in `docs/agents/linear.json`. A ticket with no estimate routes as M and `route_linear.py` warns; run `{{ADAPTER_SCRIPTS}}/estimate_linear.py propose` for the founder to approve.

Put the model in the Orca task title: `{{TEAM_KEY}}-123 · build · haiku`. The profiler reads it.

## Escalation

1. An S implementer on Haiku escalates once when any of these happens:
   - it stops and the stop cannot be resolved by an answer;
   - CI fails on its branch a second time;
   - review asks for changes a second time.
2. Start a fresh worker with `{{ADAPTER_SCRIPTS}}/route_linear.py --role build --variant escalated` on the same branch. Tell it what the first worker tried.
3. A second escalation goes to the founder: comment on the Linear ticket, add `needs-info`, move it to Triage.

## Holds

Before dispatching a ticket, compare its touch map (the paths in its "What to build" section) with:

- open PRs,
- tickets in progress,
- exclusive holds the founder named.

Overlap means wait. Shared registries (one file per entry plus an index) do not count as overlap.

## Frontier

A ticket is on the frontier when it is in Todo, unassigned, and every blocker is In Review, Done or Canceled. In Review counts as done for blocking: its work is already on the integration branch.

`implement-spec` warns that the frontier goes stale. Track merges yourself: when a merger lands a ticket, move it to In Review and recompute.

## Branches and merging

- One integration branch and one draft PR per milestone (Linear project).
- A ticket merged into the integration branch moves to In Review.
- The integration PR body has one `Fixes {{TEAM_KEY}}-<n>` line per ticket. When the founder merges it, Linear's GitHub integration moves those tickets to Done.
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
python3 {{FLOW_SCRIPTS}}/profile.py --run <run id> --coordinator <coordinator transcript>
```

Read the HTML it writes. Post the summary to the milestone's project with `python3 {{ADAPTER_SCRIPTS}}/project_update.py --profile profile-<run id>.json --project <project id> --apply`.

## Slack

Agents write to Linear only. The Linear Slack app posts to `#{{SLACK_PREFIX}}-work` and `#{{SLACK_PREFIX}}-needs-you`; the GitHub Slack app posts to `#{{SLACK_PREFIX}}-prs`.
