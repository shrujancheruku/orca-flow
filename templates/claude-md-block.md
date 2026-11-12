## Agent skills

### Issue tracker

Issues and specs are tracked in Linear (team {{TEAM_KEY}}) via `orca linear --workspace {{WORKSPACE_ID}}`. Maps and specs are Linear projects. See `docs/agents/issue-tracker.md`.

### Triage labels

Linear native Triage: needs-triage is the Triage state; needs-info, ready-for-agent and ready-for-human are labels; wontfix is Canceled. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Orchestration

Build a spec with `/flow:build`: Matt's `/implement-spec` run on Orca workers, models routed by `route.py` from the table in `docs/agents/orchestration.md`. See `docs/agents/orchestration.md`.
