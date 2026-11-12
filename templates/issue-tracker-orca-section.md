## Orca and milestones

Added by the `flow` plugin. The conventions above stand; this is what `/flow:build` adds. The policy is in `docs/agents/orchestration.md`.

- **Milestone.** A build milestone is a GitHub Milestone. Put a ticket in it with `gh issue edit <n> --milestone "<title>"`; list its tickets with `gh issue list --milestone "<title>" --state all`. Milestones are read and made through `gh api repos/{{REPO}}/milestones`.
- **Integration branch and PR.** One branch and one draft PR into main per milestone. The PR body lists `Closes #<n>` for each ticket, so merging it closes them. The founder merges it.
- **`{{INTEGRATED_LABEL}}`.** A ticket merged into the integration branch gets this label and stays open. The frontier counts an `{{INTEGRATED_LABEL}}` blocker as satisfied, so a ticket whose blocker is on the integration branch can start. This is the fix for the stale frontier in the **Frontier query** above.
- **`{{SIZE_S}}`, `{{SIZE_M}}`, `{{SIZE_L}}` and `{{RISK_LABEL}}`.** Size picks the worker's model; `{{RISK_LABEL}}`, or a ticket that touches a path in `risk_paths` (`docs/agents/flow.json`), raises it. Propose sizes with `estimate.py propose`; the founder approves.
- **Worktrees.** `orca worktree create --issue <n> --base-branch integration/<slug>` links a worktree to the issue; `orca reference find https://github.com/{{REPO}}/issues/<n>` finds the workspace or agent already on it. Orca has no GitHub issue commands, so read and write issues with `gh`.
