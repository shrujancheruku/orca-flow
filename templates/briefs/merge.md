# Merge #{{ticket}}

You are the merger for ticket #{{ticket}} in {{repo}}.

- Ticket: {{url}}
- Policy: `docs/agents/orchestration.md` (Verify, Branches and merging) and `CLAUDE.md`
- Branch: `{{branch}}`. Integration branch: `{{integration_branch}}`.

Steps:

1. `git fetch`.
2. Merge the tip of `origin/{{integration_branch}}` into `{{branch}}`. `README.md`, `CHANGELOG.md` and `skills/build/SKILL.md` are shared files: keep both sides. A conflict anywhere else stops you: report it with `orca orchestration send --type escalation`, naming the files.
3. Run the verify commands on the merged tree, unless nothing new came in.
4. Push `{{branch}}` without force, then fast-forward `{{integration_branch}}` to it.
5. Confirm the pushed tip (`git ls-remote origin {{integration_branch}}`) and report it with `worker_done`.
6. Edit no issue, label or PR.
