# /flow:build with Linear as the tracker

Read when `docs/agents/flow.json` says `"tracker": "linear"`. Everything in `skills/build/SKILL.md` holds except where this says otherwise. The policy is the repo's `docs/agents/orchestration.md`, seeded by `seed_linear_docs.py`.

- **Spec and milestone.** The spec is a Linear project labelled `build`; its tickets are issues in that project.
- **Routing.** `python3 ${CLAUDE_PLUGIN_ROOT}/adapters/linear/scripts/route_linear.py --role <role> --ticket <ABC-123> --lookup`. Size comes from the Linear Estimate.
- **Tracker.** Read and write tickets with `orca linear`, as `docs/agents/issue-tracker.md` says.
- **Frontier.** A blocker that is In Review counts as satisfied. Move a ticket to In Review when its work lands on the integration branch, then recompute the frontier.
- **Integration PR.** One integration branch and one draft PR per milestone. The PR body has a `Fixes <ticket>` line per ticket.
- **Profile.** Run `profile.py`, then post the summary with `adapters/linear/scripts/project_update.py --profile profile-<run>.json --project <project id> --apply`.
