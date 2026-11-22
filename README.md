# flow

[Matt Pocock's skills](https://github.com/mattpocock/skills) on Orca. A Claude Code plugin.

Matt's skills are used as published. This plugin never edits them. It changes their behaviour only through the docs it seeds into your repo (`docs/agents/*.md`, between its own `<!-- flow:begin ... -->` markers) and the `## Agent skills` block in `CLAUDE.md`.

GitHub Issues is the tracker. Linear is an optional adapter ([`adapters/linear/`](adapters/linear/README.md)), for a team that wants Linear or a repo moving from GitHub to Linear.

## Layers

| Layer | What | Where |
| --- | --- | --- |
| Procedure | Matt's `/implement-spec`: a task graph, a frontier, one integration branch | Matt's plugin, unmodified |
| Policy | `/flow:build`: how each role is run, routed, checked and merged | `skills/build`, `docs/agents/orchestration.md` |
| Executor | Orca: each role is a worker in its own worktree | `orca` |
| Measurement | The profiler: cost by model, role and ticket | `scripts/profile.py` |

## What you get

- `/flow:setup` sets up a repo: config, labels, seeded docs and size proposals.
- `/flow:build` builds a spec. It follows `/implement-spec`, runs each role as an Orca worker, and picks each worker's model from a routing table: the plugin's defaults, with the rows you set in `docs/agents/flow.json`.
- `wizard/wizard.sh` walks you through the steps only you can do: importing the repo into Orca, the GitHub Slack app, and updating Matt's plugin.

## Model routing

The defaults live in the plugin (`flowlib/routing.py`), so a new release changes every row you have not set. To set a row, name it under `routing` in `docs/agents/flow.json` (`"routing": {"fix": {"model": "sonnet", "effort": "medium"}}`). `route.py` routes from the two on every dispatch. Your repo's `docs/agents/orchestration.md` holds a copy of the result between the plugin's markers; `seed_docs.py --apply` rewrites it, `/flow:build` runs that at the start of each build, and `route.py` warns when the copy is out of date. Size comes from the `size:S|M|L` label. The `risk` label, or a ticket that names a path in `risk_paths`, raises the model. A ticket names a risk path when it writes the path out, names a file under it (`identity/service.go` is enough, and a new file counts by its directory), or names code that mostly lives under it. A one-word directory like `config/**` counts only as the start of a path, so the word "config" alone doesn't. `route.py` and `estimate.py` look names up in the checked-out repo, so run them from it.

| Role | Model | Effort |
| --- | --- | --- |
| Implementer, S | Haiku | |
| Implementer, M | Sonnet | medium |
| Implementer, L | Sonnet | high |
| Implementer, L + risk | Opus | |
| Scout | Haiku | low |
| Merger | Haiku | low (Sonnet on a real conflict) |
| Per-ticket check | Haiku | low |
| Integration review | Opus | |
| Fixer | Opus | |
| Coordinator | Opus | medium |

One escalation: a Haiku implementer that fails twice is replaced by Sonnet on the same branch. S + risk and M + risk have rows too; see the seeded table.

## How work maps to GitHub

| Matt's skills / flow | GitHub |
| --- | --- |
| A spec | An issue |
| A ticket | An issue, linked to the spec |
| Blocked by | Native issue dependencies (or a `Blocked by:` line) |
| The five triage roles | Labels `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix` (Matt's setup skill makes them) |
| A build milestone | A GitHub **Milestone** |
| The milestone's build | One integration branch and one draft PR into main |
| A ticket merged into the integration branch | The `integrated` label. The issue stays open; the frontier counts it as done. |
| Closing tickets | `Closes #N` lines in the integration PR body: the founder merges it, GitHub closes them |
| Size and risk | Labels `size:S`, `size:M`, `size:L`, `risk` |
| A worker | An Orca worktree created with `--issue <n>`, task title `#123 · build · haiku` |
| The end-of-milestone cost summary | A comment on the integration PR |

The founder merges integration PRs. Automerge is opt-in per run.

## Needs

- Python 3.9+ (standard library only), `gh`, `orca` and `claude`.
- Matt Pocock's skills plugin, set up in the repo with `/setup-matt-pocock-skills`.

## Quick start

```
/plugin marketplace add <path or git url of this repo>
/plugin install flow@orca-flow
```

In the repo you want to set up:

1. `/setup-matt-pocock-skills` (pick GitHub, keep the default triage labels), if you have not.
2. `/flow:setup`. It writes `docs/agents/flow.json`, creates the missing labels, seeds the docs and proposes sizes.
3. `wizard/wizard.sh` in your own terminal, for Orca and Slack.
4. `/flow:build` on a spec's milestone.

## Config

Every per-repo value is in `docs/agents/flow.json`: `tracker`, `github_repo`, the label names, `risk_paths`, `generated_paths` and `size_lines` (for the backtest), `slack_prefix`, the model aliases and `status` (when the status footer calls a worker slow). The schema is `schema/flow.schema.json`; `examples/flow.json` is a filled one. Scripts look for the config at `--config`, then `$FLOW_CONFIG`, then `docs/agents/flow.json`. `--repo owner/name` stands in for a missing config.

## Scripts

All in `scripts/`. Each that writes is a dry run until you pass `--apply`, and each is safe to rerun.

| Script | Does |
| --- | --- |
| `setup_labels.py` | Creates `size:S`, `size:M`, `size:L`, `risk` and `integrated` with `gh label create`. Checks Matt's five triage labels exist and reports any that do not; it creates none of them. |
| `seed_docs.py` | Adds an "Orca and milestones" section to `issue-tracker.md`, a "Flow labels" section to `triage-labels.md`, writes `orchestration.md` if absent, and adds the Orchestration block to `CLAUDE.md`. Only the text between its markers is rewritten, which in `orchestration.md` is the routing table. Rerun it after a plugin release. A routing table kept by hand before 0.7.0 is handed over on the first run: rows that differ from every default the plugin has shipped move to `routing` in `flow.json`. |
| `estimate.py` | `propose` copies existing `size:` labels, asks Haiku (through `flowlib/agents.py`: `claude -p --model haiku --output-format json`) to double-check them and to size the rest, and writes a file for you to approve. `apply --apply` edits only the approved ones, with `gh issue edit --add-label`. |
| `estimate.py backtest` | Sizes closed tickets the way `propose` does and scores the answers against what each one's merged PR changed (`generated_paths` left out, cut at `size_lines`), next to the size labels those tickets had. Answers are cached by prompt, so after a rubric change a rerun asks only again where the prompt changed. `--style lines` asks for expected changed lines instead of a size (cut at `size_lines`); `--style rubric` is the original prompt. `--split dev|test` holds out a fixed quarter of tickets, `--closed-after` scores only recent ones, and `--samples N` takes the median of N estimates, `--style examples` adds similar closed tickets with their real sizes to the prompt, and `--style facts` adds the repo's counts for the paths and names the ticket mentions. Both are opt-in; neither beat `lines` on Issho. Other PRs that mentioned a ticket count toward its size, and deleted files don't. `--no-model` scores the labels alone. Writes nothing to GitHub. |
| `route.py` | Picks a worker's model and effort from the plugin's defaults and your `routing` rows, and prints its task title. |
| `cleanup.py` | Removes a finished run's worktrees with `git worktree remove`, after the integration PR merges. Keeps and names any with uncommitted files or a HEAD on no remote branch; never forces; branches stay. `orca worktree rm` is not used: it hangs and leaves the checkout behind. |
| `status.py` | The status footer `/flow:build` prints at the end of every coordinator turn (`--plain`; `--json` for the same data). **In progress**: each live worker of the run (ticket, role, model, time since its task was created), flagged when it has no heartbeat, exited without reporting, or has run past `status.slow_factor` (3) times its role's median in the run (`status.slow_minutes`, 120, with fewer than 3 finished), then the milestone's tally: integrated, in progress, ready next, blocked, waiting on you. **Waiting on you**, in this order and each left out when empty: `ready-for-human` tickets in the milestone, those outside it, `needs-info` tickets, the coordinator's asks, worker questions and escalations Orca has not marked handled (and pending gates), and the integration PR once it is out of draft or every milestone ticket is integrated, with its check counts; else `Waiting on you: nothing`. `--ask "<text>" [--ticket <n>] [--where <text>]` records an ask and prints its id, `--done <id>` clears it; an ask whose issue or PR closed is dropped. Asks live in `<git common dir>/flow/asks.jsonl` (inside `.git`, so never tracked and shared by every worktree; mode 0600), or `$FLOW_ASKS_FILE`. Reads only: five `orca` reads and one or two label-, milestone- or number-filtered GraphQL reads. Whatever it cannot read is named on one `Unavailable:` line, and it exits 0. "Handled" is Orca's flag on a message; the footer cannot tell whether the coordinator answered it, only whether Orca marked it handled. Blockers are GitHub's native issue dependencies, not `Blocked by:` lines. GitHub Issues only. |
| `profile.py` | Costs an Orca run by model, role and ticket. Writes JSON and an HTML view. `--pr <n> --apply` comments the summary on the integration PR. |

## Tests

```
python3 -m unittest
```

## Status

0.2.0. GitHub is the default tracker; Linear moved to an adapter (see `CHANGELOG.md` for the breaking changes). The GitHub path has been dry-run against a real repo. Profiling and the Orca worker fields have not yet been checked against a real run.

## License

MIT
