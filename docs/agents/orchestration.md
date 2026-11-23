# Orchestration

How a spec gets built here. `/flow:build` follows this file. Tickets are GitHub issues, a build milestone is a GitHub Milestone, and `gh` is the only tracker tool (Orca has no GitHub issue commands).

## Layers

- **Procedure:** Matt Pocock's `/implement-spec`, unmodified. Read its `SKILL.md` and follow it.
- **Policy:** this file. Where it and `implement-spec` differ, this file wins.
- **Executor:** Orca. The implementer, merger, checker, fixer and reviewer are Orca workers. Short read-only jobs (exploration, `code-review`'s two reviewers) are subagents inside a worker. On an agent with no subagents, they become their own Orca workers.
- **Tracker:** GitHub Issues. See `docs/agents/issue-tracker.md`.
- **Measurement:** `${CLAUDE_PLUGIN_ROOT}/scripts/profile.py`.

`${CLAUDE_PLUGIN_ROOT}` is the installed `flow` plugin's folder. `/flow:build` expands it; outside it, run `claude plugin list` to find the path.

## Model routing

Before every worker, run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/route.py --role <role> --ticket <n> --lookup` and pass the `flags` (`--agent`, `--model`, `--effort`) and `task_title` it prints. Never route from memory: the script decides, and the table below is a copy of what it uses. The Model column names a profile in `models` in `docs/agents/flow.json`, which says which Orca agent and model id it runs on. Always pass `--model`: the user's own settings default to Opus.

<!-- flow:begin routing -->
| Key | Role | Model | Effort | Notes |
|---|---|---|---|---|
| coordinator | Coordinator | opus | medium | The session running `/flow:build`. |
| scout | Exploration or scout | haiku |  | A subagent inside a worker. |
| build.S | Implementer, size S, no `risk` | haiku |  | Escalates once; see Escalation. |
| build.S.risk | Implementer, size S, `risk` | sonnet | medium |  |
| build.M | Implementer, size M | sonnet | medium |  |
| build.M.risk | Implementer, size M, `risk` | sonnet | high |  |
| build.L | Implementer, size L | sonnet | high |  |
| build.L.risk | Implementer, size L, `risk` | opus |  |  |
| build.escalated | Implementer after an escalation | sonnet | medium | A fresh worker on the same branch. |
| merge | Merger | haiku |  |  |
| merge.conflict | Merger on a real conflict | sonnet | medium |  |
| check | Spec check before a ticket merges into the integration branch | haiku |  | One per ticket. |
| review | Integration `code-review`, once per milestone | opus |  |  |
| review.risk | Integration `code-review`, milestone has `risk` tickets | opus |  | Same as `review`; kept so `--risk` resolves. |
| fix | Fixer for the integration review's findings | opus |  |  |

The flow plugin writes this table from its defaults and from `routing` in `docs/agents/flow.json`. To change a row, set it there (`"routing": {"fix": {"model": "sonnet", "effort": "medium"}}`), not here: a row you have not set follows the plugin's default and changes with its releases.
<!-- flow:end routing -->

Size comes from the issue's `size:S`, `size:M` or `size:L` label. The `risk` label, or a ticket that names a path in `risk_paths` in `docs/agents/flow.json`, raises the model to the `.risk` row. A ticket with no size label routes as M and `route.py` warns; run `estimate.py propose` for the founder to approve sizes.

For `review`, pass the integration PR's number as `--ticket`.

Put the model in the Orca task title: `#123 · build · haiku`. The profiler reads it.

## Starting a worker

1. `orca reference find https://github.com/shrujancheruku/orca-flow/issues/<n> --json` first. If a workspace or agent is already attached to the issue, resume or read it instead of starting another. (Orca wants the issue URL; a bare number is not supported.)
2. `orca worktree create --issue <n> --name "<n>-<slug>" --base-branch integration/<milestone-slug> --no-parent --json` makes the ticket's worktree and links it to the issue.
3. `orca orchestration worker-start --worktree issue:<n> --task-title "<task_title from route.py>" <flags from route.py> --spec-file -`, with the brief on stdin, printed by `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/brief.py --role <role> --ticket <n> --integration-branch <branch>` (see "Briefs" in the build skill). The brief holds context pointers: the issue URL, the spec, the exploration notes, the integration branch.

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

`README.md`, `CHANGELOG.md` and `skills/build/SKILL.md` are shared files: every ticket adds to them, so they are not overlap. Each ticket adds its own lines without reordering what is there, and the merger keeps both sides.

## Frontier

A ticket is on the frontier when it is open, labelled `ready-for-agent`, unassigned, has no Orca workspace on it (`orca reference find`), and every blocker is closed or labelled `integrated`. An `integrated` blocker counts as done: its work is already on the integration branch, though the issue stays open until the integration PR merges into main.

Blockers are the issue's native dependencies (`gh api repos/shrujancheruku/orca-flow/issues/<n>/dependencies/blocked_by`), or the `Blocked by: #<n>` line at the top of the body where dependencies are off.

`implement-spec` warns that the frontier goes stale because the issues it waits on stay open. Track merges yourself: when a merger lands a ticket, add `integrated` to it and recompute.

## Branches and merging

- A build milestone is a GitHub Milestone. Its tickets carry that milestone.
- One integration branch (`integration/<milestone-slug>`) and one draft PR into main per milestone. Open the draft after the first merge, with `--milestone`.
- The Haiku `check` worker passes a ticket before it merges into the integration branch. A failed check goes back to the implementer; it is not merged, except a paperwork-only miss the coordinator rules accepted and records with `notes.py --add` (see "Rulings" in the build skill).
- A ticket merged into the integration branch gets the `integrated` label (`gh issue edit <n> --add-label integrated`). Do not close it.
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

## Verify

Every implementer, from the worktree root, before reporting done:

1. `python3 -m unittest` passes. It needs no network, `gh`, `orca` or `claude`.
2. Each script the ticket changes still runs as a dry run (`python3 scripts/<name>.py --help`, and without `--apply` where it needs no live run).
3. `README.md` and `CHANGELOG.md` say what changed, as `CLAUDE.md` requires.

There is no CI in this repo yet, so the merger runs the same commands on the merged tree, and "green on the integration PR" means these commands pass on its tip.

A ticket's proof is a resolution comment on the ticket: each criterion beside the test that proves it, and the last lines of the test run.

## Environment

- Workers never run a script with `--apply` against a real repo, never post to GitHub except their own ticket's resolution comment, and never start, stop or remove another run's Orca workers or worktrees. Behaviour against Orca and GitHub is proven with the fakes in `tests/helpers.py`.
- A worker may read live state (`orca ... --json`, `gh ... view`) to learn a field's real shape, and records what it saw in a test fixture with names and ids replaced.

## Review checks

The `check` worker and the integration review read `CLAUDE.md`, `README.md` and the ticket. They check that every criterion has a test that fails without the change, that nothing outside the standard library is imported, that a writing script stays a dry run without `--apply`, that the README and changelog match the behaviour, that the Linear adapter was considered, and that no version was bumped.

## Profiling

At the end of each milestone, run:

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/profile.py --run <run id> --coordinator <coordinator transcript> [--coordinator <another coordinator transcript> ...] --pr <integration PR number> --apply
```

Read the HTML it writes. `--pr ... --apply` has the coordinator post the summary as a comment on the integration PR. The profile is unverified until the first real run.

## Slack

Not set up for this repo. Agents write to GitHub only.
