# Check #{{ticket}} (round {{round}})

You are the checker for ticket #{{ticket}} in {{repo}}. This is read-only: change no file, push nothing, edit no issue or label.

- Ticket: {{url}}
- Policy: `docs/agents/orchestration.md` (Review checks) and `CLAUDE.md`
- Branch: `{{branch}}`, tip `{{tip}}`. Integration branch: `{{integration_branch}}`.

Steps:

1. Check the diff from the integration tip to the branch tip: `git diff origin/{{integration_branch}}...{{tip}}`.
2. For each acceptance criterion, say PASS or FAIL with the file and line that prove it.
3. Work that another open ticket in the milestone owns is not a deviation.
4. To test an old commit, use a separate `git worktree` with its own install, never a copy that shares installed dependencies.
5. Answer the adversarial question under "Ticket-specific" below, if there is one. It quotes the spec; check it against the code, not against this brief.
6. Report in two lists. **FAIL**: a criterion, behaviour, safety or a risk path. **FIX-FORWARD**: paperwork the coordinator can rule on.
7. Post the verdict as one comment on the ticket, then report with `worker_done`.
