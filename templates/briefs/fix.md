# Fix PR #{{pr}} (round {{round}})

You are the fixer for the integration review of {{url}} in {{repo}}.

- Review: the latest review on the PR; its findings are the job
- Policy: `docs/agents/orchestration.md` (Verify, Environment) and `CLAUDE.md`
- Integration branch: `{{integration_branch}}`. Work on your own fix branch from its tip.

Steps:

1. Fix the blocking findings and every should-fix.
2. Each behaviour fix ships a test that fails without it. No wait in a test helper is unbounded.
3. A fix for a red CI job names the job and reproduces the failure before fixing it.
4. Leave the founder-decision list alone.
5. Clear each carried note you fixed with `python3 {{flow_scripts}}/notes.py --done <id>`. Each note's id is in brackets: `python3 {{flow_scripts}}/notes.py` lists them, from any worktree, since the store is shared by every worktree of the repo.
6. Run the verify commands on your branch.
7. Post one comment on the PR mapping each finding to its commit and its test.
8. Push the fix branch only; a merger lands it. Report with `worker_done`, giving the branch name and tip SHA.
