# Changelog

This project follows [Semantic Versioning](https://semver.org/).

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
