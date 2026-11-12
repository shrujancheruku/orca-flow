# Changelog

This project follows [Semantic Versioning](https://semver.org/).

## 0.1.0 - 2026-11-12

First release.

- `/flow:setup`: config, team setup, GitHub-to-Linear migration, verify, reference rewrite, seeded docs, estimates and cutover.
- `/flow:build`: `/implement-spec` on Orca workers, with model routing from `docs/agents/orchestration.md`.
- Scripts are dry runs unless given `--apply`, and safe to rerun.
- Profiler for an Orca run: cost by model, role and ticket, as JSON and an HTML viewer. Unverified against a real run.
- Setup wizard for the Linear key, Orca, Triage, the GitHub integration and Slack.
