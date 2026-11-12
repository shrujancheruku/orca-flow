## Flow labels

Added by the `flow` plugin, beside the five roles above. They are not triage roles.

| Label | Meaning |
| --- | --- |
| `{{SIZE_S}}`, `{{SIZE_M}}`, `{{SIZE_L}}` | Size of a ticket. Routes the implementer's model. |
| `{{RISK_LABEL}}` | Touches auth, migrations, data deletion, a public API or a path in `risk_paths`. Raises the model. |
| `{{INTEGRATED_LABEL}}` | Merged into the milestone's integration branch; the issue stays open until the integration PR merges into main. |

`setup_labels.py` creates them.
