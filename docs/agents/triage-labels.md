# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Edit the "Label in our tracker" column to match whatever vocabulary you actually use.

<!-- flow:begin flow-labels -->
## Flow labels

Added by the `flow` plugin, beside the five roles above. They are not triage roles.

| Label | Meaning |
| --- | --- |
| `size:S`, `size:M`, `size:L` | Size of a ticket. Routes the implementer's model. |
| `risk` | Touches auth, migrations, data deletion, a public API or a path in `risk_paths`. Raises the model. |
| `integrated` | Merged into the milestone's integration branch; the issue stays open until the integration PR merges into main. |

`setup_labels.py` creates them.
<!-- flow:end flow-labels -->
