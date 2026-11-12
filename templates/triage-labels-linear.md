# Triage Labels

The skills speak in terms of five canonical triage roles. Linear's native Triage is on for team `{{TEAM_KEY}}`, so some roles are states, not labels.

| Role in mattpocock/skills | In our Linear | Meaning |
| --- | --- | --- |
| `needs-triage` | state **Triage** | Maintainer needs to evaluate this issue |
| `needs-info` | state **Triage** + label `needs-info` | Waiting on reporter for more information |
| `ready-for-agent` | state **Todo** + label `ready-for-agent` | Fully specified, ready for an AFK agent |
| `ready-for-human` | state **Todo** + label `ready-for-human` | Requires human implementation |
| `wontfix` | state **Canceled** | Will not be actioned |

When a skill says to apply a role, set the state and the label together. For example, `ready-for-agent` is:

```
orca linear status set {{TEAM_KEY}}-123 --to Todo --workspace {{WORKSPACE_ID}}
orca linear label add {{TEAM_KEY}}-123 --label ready-for-agent --workspace {{WORKSPACE_ID}}
```

Moving a ticket out of a role removes its label: `orca linear label remove ...`.

Other mappings:

- Duplicates go to state **Duplicate**, with a `duplicate-of` relation to the original.
- Issue types are Linear labels: `Bug` and `Feature`.
- `risk` marks tickets that touch auth, migrations, data deletion, a public API or a path in `risk_paths` in `docs/agents/linear.json`. Routing reads it.

Triage is for incoming requests only. Tickets from `/to-tickets` and `/wayfinder` go straight to Todo.
