# flow

A Claude Code plugin. It runs [Matt Pocock's skills](https://github.com/mattpocock/skills) with Linear as the issue tracker and Orca as the executor. It also moves a repo's GitHub issues to Linear.

Matt's skills are used as published. This plugin never edits them. It changes their behaviour only through the docs it seeds into your repo (`docs/agents/*.md`) and the `## Agent skills` block in `CLAUDE.md`.

## What you get

- `/flow:setup` sets up a repo: config, Linear team, migration, verify, reference rewrite, seeded docs, estimates and cutover.
- `/flow:build` builds a spec. It follows Matt's `/implement-spec`, runs each role as an Orca worker, and picks each worker's model from a routing table you own.
- `wizard/wizard.sh` walks you through the steps only you can do: the Linear API key, Orca's Linear connection, Triage, the GitHub integration and Slack.

## How work maps to Linear

| Matt's skills | Linear |
| --- | --- |
| A phase of work | An initiative |
| A wayfinder map | A project labelled `wayfinder`. The Destination is the summary; the rest is the content. |
| A spec | A project labelled `build` |
| A ticket | An issue in that project |
| Blocked by | A blocking relation |
| needs-triage | The Triage state |
| needs-info | Triage + the `needs-info` label |
| ready-for-agent / ready-for-human | Todo + the label |
| wontfix | Canceled |

One team per app. In Review means merged into the milestone's integration branch, and the frontier counts it as done.

## Needs

- macOS (the Linear key lives in the Keychain), Python 3.9+, `gh`, `orca` and `claude`.
- Matt Pocock's skills plugin.
- A Linear workspace with a team for the app.

## Install

```
/plugin marketplace add <path or git url of this repo>
/plugin install flow@linear-orca-flow
```

Then, in the repo you want to set up, run `/flow:setup`.

## Config

Every per-repo value is in `docs/agents/linear.json`. The schema is `schema/linear.schema.json`; `examples/` has a filled one. Scripts look for the config at `--config`, then `$FLOW_CONFIG`, then `docs/agents/linear.json`. `LINEAR_KEYCHAIN_SERVICE` overrides the Keychain service.

## Scripts

All in `scripts/`. Each is a dry run until you pass `--apply`, and each is safe to rerun: it skips what already exists.

| Script | Does |
| --- | --- |
| `setup_team.py` | Adds the In Review state, the estimate scale, labels, project labels and the initiative. |
| `migrate.py` | Moves GitHub issues, comments, sub-issues and blockers to Linear. Records every id in `docs/agents/linear-mapping.json`, so a failed run resumes. |
| `verify.py` | Read only. Checks every migrated issue and project against GitHub. |
| `rewrite_refs.py` | Rewrites `#N` issue refs in your markdown to Linear links. PR numbers stay. |
| `seed_docs.py` | Writes the agent docs and the `CLAUDE.md` block. |
| `estimate.py` | `propose` asks Haiku for sizes and writes a file for you to approve. `apply` writes only the approved ones. |
| `cutover.py` | Comments "Moved to" on each GitHub issue, closes it, and points new issues at Linear. |
| `project_doc.py` | Reads and edits a project's summary and content, for wayfinder and to-spec. |
| `route.py` | Picks a worker's model and effort from the routing table. |
| `profile.py` | Costs an Orca run by model, role and ticket. Writes JSON and an HTML view. |

## Tests

```
python3 -m unittest
```

## Status

0.1.0. The migration has been dry-run against a real repo. Profiling and the Orca worker fields have not yet been checked against a real run. See `CHANGELOG.md`.

## License

MIT
