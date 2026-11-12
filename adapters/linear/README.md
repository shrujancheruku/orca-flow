# Linear adapter

Optional. The plugin's default tracker is GitHub Issues. Use this adapter when a team wants **Linear** as the tracker, or wants to **migrate a repo's GitHub issues to Linear** and keep working from there.

Nothing in the core (`scripts/`, `skills/`, `templates/`) imports from here. The adapter imports the core's routing, estimating and profiler code.

## When to use it

- A team that tracks work in Linear and wants Matt Pocock's skills to follow suit.
- A repo that has GitHub issues today and should move to Linear, with comments, sub-issues and blockers carried over.

If you are happy on GitHub Issues, you do not need any of this.

## Turn it on

In `docs/agents/flow.json` set `"tracker": "linear"`. The Linear-only keys (workspace, team, states, projects, estimate scale) go in `docs/agents/linear.json`; the tracker-neutral ones (`github_repo`, `risk_paths`, `slack_prefix`, `models`) may sit in either file, and `linear.json` wins. The schema is `schema/linear.schema.json`, and `examples/look-together.json` is a filled `linear.json`. Then run `/flow:setup`, which follows `SETUP.md`.

Needs macOS (the Linear key lives in the Keychain), `LINEAR_KEYCHAIN_SERVICE` overrides the Keychain service.

## What is here

| Path | Does |
| --- | --- |
| `scripts/setup_team.py` | Adds the In Review state, the estimate scale, labels, project labels and the initiative. |
| `scripts/migrate.py` | Moves GitHub issues, comments, sub-issues and blockers to Linear. Records every id in `docs/agents/linear-mapping.json`, so a failed run resumes. |
| `scripts/verify.py` | Read only. Checks every migrated issue and project against GitHub. |
| `scripts/rewrite_refs.py` | Rewrites `#N` issue refs in your markdown to Linear links. PR numbers stay. |
| `scripts/cutover.py` | Comments "Moved to" on each GitHub issue, closes it, and points new issues at Linear. |
| `scripts/project_doc.py` | Reads and edits a project's summary and content, for wayfinder and to-spec. |
| `scripts/seed_linear_docs.py` | Writes the Linear versions of the agent docs and the `CLAUDE.md` block. |
| `scripts/route_linear.py`, `scripts/estimate_linear.py` | Routing and size proposals from the Linear Estimate. |
| `scripts/project_update.py` | Posts a profile summary to a Linear project. |
| `wizard.sh` | The setup steps only you can do: Linear key, Orca's Linear connection, Triage, the GitHub integration, Slack. |
| `SETUP.md`, `BUILD.md` | What `/flow:setup` and `/flow:build` do differently with Linear. |
| `templates/`, `schema/`, `examples/`, `tests/` | The Linear docs, config schema, example and tests. |

Each script is a dry run until you pass `--apply`, and each is safe to rerun.

## How work maps to Linear

| Matt's skills | Linear |
| --- | --- |
| A phase of work | An initiative (optional: `"initiative": null`) |
| A wayfinder map | A project labelled `wayfinder` |
| A spec | A project labelled `build` |
| A ticket | An issue in that project |
| Blocked by | A blocking relation |
| needs-triage | The Triage state |
| needs-info | Triage + the `needs-info` label |
| ready-for-agent / ready-for-human | Todo + the label |
| wontfix | Canceled |

In Review means merged into the milestone's integration branch, and the frontier counts it as done.
