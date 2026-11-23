# Agent instructions for flow

A Claude Code plugin: Matt Pocock's skills on Orca. Humans: see [README.md](README.md).

## Every change

- Work from an issue and close it from the PR (`Closes #<n>`).
- Python 3.9+, standard library only: no dependency is added. Code lives in `scripts/flowlib/`, the scripts in `scripts/` are thin entry points, and tests are in `tests/`.
- Run `python3 -m unittest` from the repo root; it must pass. A behaviour change ships with a test that fails without it. Tests never call `gh`, `orca` or `claude`: they use the fakes in `tests/helpers.py`.
- Every script that writes is a dry run until `--apply`, and is safe to rerun. `notes.py --add/--done` and `status.py --ask/--done` are exempt: they write only the local bookkeeping files under `<git common dir>/flow/` (`notes.jsonl`, `asks.jsonl`), never the repo's tracked files or GitHub, so they need no `--apply`.
- A change to a script, the build skill or a template updates `README.md` and adds a line under the next version in `CHANGELOG.md`. The release itself (the version in `.claude-plugin/plugin.json` and `marketplace.json`, and the tag) is the owner's: never bump it in a ticket.
- A change to the GitHub path that the Linear adapter mirrors (`adapters/linear/`) is made in both, or the ticket says why not.
- Comment non-obvious logic with the why.
- Commits and PR titles follow Conventional Commits (`fix(status): ...`); no generated-by footer or co-author trailer.
- The repo is public: no secrets, personal data or another repo's private details in code, tests, issues or PRs.

## Agent skills

### Issue tracker

GitHub Issues on shrujancheruku/orca-flow via `gh`. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default labels: needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context. There is no glossary or ADR folder yet; the README and `CHANGELOG.md` hold the reasoning. See `docs/agents/domain.md`.

<!-- flow:begin orchestration -->
### Orchestration

Build a spec with `/flow:build`: Matt's `/implement-spec` run on Orca workers, with models routed by `route.py` from the table in `docs/agents/orchestration.md`. A build milestone is a GitHub Milestone; the founder merges the integration PR. See `docs/agents/orchestration.md`.
<!-- flow:end orchestration -->
