# Changelog

This project follows [Semantic Versioning](https://semver.org/).

## Unreleased

### Features

- `status.py` prints a status footer, and `/flow:build` prints it (`--plain`) at the end of every coordinator turn, so the founder no longer has to ask what is waiting on them. **In progress** lists each live worker with its ticket, role, model and running time, flagged when it has no heartbeat, exited without reporting, or has run more than three times its role's median in the run (two hours when there is no median; `status` in `flow.json` sets both), then the milestone's tally (integrated, in progress, ready next, blocked, waiting on you). **Waiting on you** has one section per source in a fixed order, each left out when empty: `ready-for-human` tickets in the milestone and, apart, outside it; `needs-info` tickets; the coordinator's asks; worker questions and escalations Orca has not marked handled, and pending gates; and the integration PR once it leaves draft or every ticket is integrated, with green, red and pending check counts. The founder merges it. When nothing waits it prints `Waiting on you: nothing`.
- `status.py --ask "<text>" [--ticket <n>] [--where <text>]` records what the coordinator asked the founder and prints an id; `--done <id>` clears it. The asks are in `<git common dir>/flow/asks.jsonl` (mode 0600), inside `.git` so they are never tracked and every worktree of the repo shares them. An ask whose issue or PR has closed or merged is dropped.
- The footer reads little: five `orca` reads and one GraphQL query (two when the milestone comes from the integration PR), filtered by label, milestone or number. Every printed line has control characters, bidi overrides and triple backticks stripped, and titles are cut. A source that fails is named on one `Unavailable:` line and the footer still exits 0. `--json` gives the same data; on a terminal the default output has colour.
- `flowlib.orca.orca()` and `flowlib.github.run_gh()` take a `timeout`.

## 0.8.0 - 2026-11-22

### Features

- `cleanup.py --run <run id>` removes a finished run's worktrees, and `/flow:build` runs it once the integration PR is merged. It goes through `git worktree remove`, because `orca worktree rm` (Orca 1.4.269) stops the worktree's terminals, fails its own git removal and then waits until it times out, leaving the checkout on disk. A worktree is removed only when it has no uncommitted file and its HEAD is on a remote branch; the rest are kept and named. Nothing is forced and no branch is deleted. Orca drops its record of a worktree once the checkout is gone.

## 0.7.0 - 2026-11-22

### Features

- The routing table's defaults live in the plugin (`flowlib/routing.py`), not in each repo's `docs/agents/orchestration.md`. `route.py` and `route_linear.py` route from the defaults with the repo's own rows laid over them, so a release that changes a default changes it in every repo that has not set that row. Before, a repo kept whatever table it was seeded with.
- `flow.json` takes `routing`: the rows a repo sets itself, by key (`"routing": {"fix": {"model": "sonnet", "effort": "medium"}}`). A key the plugin does not ship adds a variant row.
- The table in `orchestration.md` is a copy the plugin writes between `<!-- flow:begin routing -->` markers, with the rows set in the config marked. `seed_docs.py --apply` (and `seed_linear_docs.py`) rewrites it and leaves the rest of the file alone; `/flow:build` runs it at the start of a build, and the route scripts warn when the copy is out of date.
- A table kept by hand is handed over on the first run. A row counts as the repo's own, and moves to `routing`, when it differs from every default the plugin has shipped for that key (`PAST_DEFAULTS`); a row still holding an old default follows the new one. Until the hand-over, the route scripts already route this way and say so.

### Fixes

- `profile.py` reads what Orca really returns, pinned on the first real run: task titles come from `task-list`, the worktree from the worker's `workspace`, times from `worker-show`'s dispatch, and a follow-up sent to a worker takes the title of the worker it continues. Before, every worker was role `unknown` and no ticket was listed.
- Each API message is counted once. A worktree is shared by a ticket's implementer, checker and merger, and a follow-up continues the old session, so a session now goes to the worker chain that started it and is split by time between that chain's dispatches. Before, every worker in a worktree was charged for all of its sessions: the first real run's workers showed $266 against a real $54.
- Round-one approval no longer needs a verdict in Orca's outcome, which only says the checker finished: a ticket with one check or review dispatch and no fixer was approved in round one.
- A follow-up to the same implementer is not an escalation; a change of build model is.

## 0.6.0 - 2026-11-22

### Features

- The integration review and its fixer both route to Opus in the routing table that `/flow:init` writes (`review`, `review.risk` and `fix`; they were Sonnet high, Opus and Sonnet medium). A milestone's review found blocking problems in risk paths that per-ticket checks had passed, and its fixes touch the same code. A repo that already has the table keeps its own rows until it edits them.

## 0.5.0 - 2026-11-14

### Features

- `estimate.py backtest` scores the estimator against closed tickets. A case is a ticket closed as completed by one merged PR that closes nothing else; its actual size is the PR's changed lines with `generated_paths` left out, cut at `size_lines` (`S` 300, `M` 1000 by default, matching the rubric). It prints how often the estimator and the size labels were exact, too small or too big, with a confusion matrix and the spread of real PR sizes. Answers are cached by prompt and model, so comparing two prompts asks only about what changed.
- `estimate.py --style lines` asks the model for the changed lines it expects (code, tests and docs, not generated files) instead of a size, and turns them into S/M/L with `size_lines`. The prompt tells it that breadth, open decisions and long acceptance criteria are not diff size. It is the new default: on 69 closed Issho tickets it got the size exactly right 78% of the time (rubric prompt: 52%) and was off by two sizes once (rubric: 6 times). `--style rubric` keeps the old prompt, and the calibration pass now runs only with it.
- `flow.json` takes `generated_paths` and `size_lines`.
- `Gh.read()` accepts GraphQL queries (never mutations).
- The backtest counts every merged PR that mentioned a ticket while it was open and closes no ticket itself, so a ticket done as a series of PRs is measured whole. Deleting a whole file no longer counts its lines.
- `estimate.py backtest --split dev|test` holds out a fixed quarter of tickets (picked by number) so prompts can be tuned on `dev` and confirmed on `test`. `--closed-after DATE` scores only tickets closed since a date.
- `--samples N` (lines style) asks N times and takes the median line estimate, for `propose` and `backtest`. Answers are cached, so raising N asks only for the rest.
- Proposals keep Haiku's line estimate as `haiku_lines`.
- `--style examples` (opt-in) is the lines prompt plus the K most similar closed tickets (`--examples K`, default 5) and the lines their PRs really changed. Similarity is TF-IDF over title and body, with shared paths counting double (`flowlib/similar.py`). On 69 closed Issho tickets it was no better than the lines prompt (exact 53 against 54, though no misses by two sizes against 1), so `lines` stays the default. The tickets it still misses are sweeping changes ("for every screen"), whose size depends on how many call sites the code has, which no ticket text shows. In the backtest a ticket never sees itself; `--strict-time` also hides tickets closed after it was created.
- `--style facts` (opt-in) is the lines prompt plus counts from the repo for each path and name the ticket mentions: a path's files and lines, a name's number of files using it, or "not in the repo yet" (`flowlib/repofacts.py`). The backtest counts the repo at the last commit before the ticket was filed. On 69 closed Issho tickets it did no better than the lines prompt (exact 51 against 54). Tuning `size_lines` on the estimates didn't help either (dev +2, test +0): Haiku's estimates for real M and L tickets overlap almost completely.
- Risk from paths is looked up in the repo (`repofacts.risk_paths`), in `route.py` and in `estimate.py propose`. A short path, a new file in a risky directory, or a code name that mostly lives under a risk path now counts. A one-word directory pattern like `config/**` no longer matches the bare word "config", and a glob like `apps/*/wrangler.jsonc` needs a matching path, not just "apps/". The backtest now scores this against the risk paths each PR really touched. On 70 closed Issho tickets it catches 17 of 23 risky PRs with 6 false alarms; the literal text match caught 16 with 10. Haiku's `risk_kind` was null on every case, so in practice risk comes from paths.

## 0.4.0 - 2026-11-12

### Features

- The estimator calibrates its sizes. After sizing each ticket alone, one more call sizes all the Haiku-sized tickets against each other, and the proposal keeps `first_size`. A size copied from a label is never changed. Use `--no-calibrate` to skip this step.
- Sizes are measured in coding-agent work (one sitting, about 300 lines, an existing pattern for S), not in ticket length. On look-together's first run, the old scale sized 57 of 66 tickets L.
- Risk is narrower. Haiku has to name one of `risk_kinds` (new in `flow.json`, with defaults for auth, stored formats and migrations, deleting a person's data, money, and secrets), or a configured risk path has to match. Keyword hints are still reported but no longer make a ticket risk, and touching an API is not risk by itself.

## 0.3.0 - 2026-11-12

### Features

- Model names in the routing table are now profiles. Each entry in `models` is either a Claude model id, as before, or `{ "agent": "<orca agent id>", "model": "<that agent's model id>" }`. `route.py` passes `--agent` along with `--model` and `--effort`, so a row can run on Codex, OpenCode (for example through OpenRouter) or another Orca agent. Nothing changes for existing configs: a bare string still means Claude.
- `flowlib/agents.py` is now the only place that knows an agent CLI. It holds the estimator's headless runner and the profiler's transcript location, and only Claude has them so far. Adding another agent means adding an entry to `RUNNERS` and `TRANSCRIPTS` there.
- `orchestration.md` no longer hardcodes `--agent claude`. A brief's subagents (the scout and `code-review`'s reviewers) become their own Orca workers on an agent that has no subagents.

## 0.2.1 - 2026-11-12

### Fixes

- `seed_docs.py` wrote the plugin's install folder into `docs/agents/orchestration.md`, a path that broke on the next plugin version and on other machines. It now writes `${CLAUDE_PLUGIN_ROOT}/scripts` and says what that is.

## 0.2.0 - 2026-11-12

GitHub Issues is now the default tracker, and the plugin is `orca-flow`: Matt Pocock's skills on Orca. All the Linear code moved into an optional adapter.

### Breaking changes

- The repo and marketplace are renamed from `linear-orca-flow` to `orca-flow`. Install with `/plugin install flow@orca-flow`.
- The config is `docs/agents/flow.json` (`schema/flow.schema.json`), with `tracker: "github"` by default. The Linear-only keys moved to `docs/agents/linear.json` in `adapters/linear/`.
- Every Linear script moved to `adapters/linear/scripts/` (`setup_team`, `migrate`, `verify`, `cutover`, `rewrite_refs`, `project_doc`), as did the Linear mapping, refs, client and workspace code, templates, schema, example, wizard and tests. `seed_docs`, `route` and `estimate` there are now `seed_linear_docs`, `route_linear` and `estimate_linear`. The Python package for the Linear code is `linearlib`; the core never imports it.
- Size comes from `size:S|M|L` labels, not a Linear Estimate. Ticket ids are `#N`, so Orca task titles look like `#123 · build · haiku`.
- `profile.py` no longer posts a Linear project update; `--pr <n> --apply` comments the summary on the integration PR. `--project-update` is now `adapters/linear/scripts/project_update.py`.
- `seed_docs.py` no longer replaces `docs/agents/*.md` or the `## Agent skills` section. It adds marked sections beside Matt's text, and never overwrites an existing `orchestration.md`.

### Added

- `setup_labels.py`: creates `size:S`, `size:M`, `size:L`, `risk` and `integrated`, and reports missing triage labels. Dry run by default.
- `/flow:build` for GitHub: build milestones are GitHub Milestones with one integration branch and draft PR; a merged ticket gets the `integrated` label and counts as satisfied for the frontier; the integration PR lists `Closes #N`; workers are created with `orca worktree create --issue`; a Haiku check runs before each merge; the founder merges.
- `estimate.py` proposes `size:` labels, copying and double-checking existing ones, and applies the approved ones with `gh issue edit`.
- `route.py` raises the model for a ticket that touches a configured risk path, not only for the `risk` label.
- `wizard/wizard.sh` covers importing the repo into Orca, the GitHub Slack app (with a `#<prefix>-needs-you` channel) and updating Matt's plugin. A Linear config hands over to `adapters/linear/wizard.sh`.
- `adapters/linear/README.md`, `SETUP.md` and `BUILD.md`.

### Unchanged

- The model routing table and the escalation rule.
- Profiling stays unverified against a real Orca run.

## 0.1.1 - 2026-11-12

Fixes from the first trial migration into a test team.

- Record ids are hash-derived UUIDs stamped as version 4, which Linear requires. Reruns still find what the last run created.
- `setup_team.py` creates only the labels some issue carries. Labels whose meaning becomes a state (`needs-triage`, `wontfix`, `duplicate`, `invalid`; config `labels.state_roles`) are dropped.
- `"initiative": null` runs without an initiative, for workspaces that have them off.
- Blocking relations are found through each blocker's own relations, since `issueRelations` takes no filter.
- The reference rewrite leaves the "Moved from GitHub" footer and each comment's "original" link pointing at GitHub, and a rerun skips text it already wrote.
- Linear errors include the field-level validation message.

## 0.1.0 - 2026-11-12

First release.

- `/flow:setup`: config, team setup, GitHub-to-Linear migration, verify, reference rewrite, seeded docs, estimates and cutover.
- `/flow:build`: `/implement-spec` on Orca workers, with model routing from `docs/agents/orchestration.md`.
- Scripts are dry runs unless given `--apply`, and safe to rerun.
- Profiler for an Orca run: cost by model, role and ticket, as JSON and an HTML viewer. Unverified against a real run.
- Setup wizard for the Linear key, Orca, Triage, the GitHub integration and Slack.
