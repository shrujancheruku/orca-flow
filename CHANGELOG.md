# Changelog

This project follows [Semantic Versioning](https://semver.org/).

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
