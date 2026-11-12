"""The labels the plugin adds on top of Matt Pocock's five, and the plan to create the missing ones.

Pure. setup_labels.py reads the repo's labels and runs the creates.
"""

from __future__ import annotations

SIZE_COLOR = "c5def5"
SIZE_DESCRIPTION = {
    "S": "Small: one change in a file or two. Routes to Haiku.",
    "M": "Medium: a few files or one module. Routes to Sonnet, medium effort.",
    "L": "Large: several modules or open design. Routes to Sonnet, high effort.",
}


def wanted(cfg: dict) -> list:
    """Every label the plugin creates: three sizes, risk and integrated."""
    labels = [
        {"name": cfg["labels"]["size"][s], "color": SIZE_COLOR, "description": SIZE_DESCRIPTION[s]}
        for s in ("S", "M", "L")
    ]
    labels.append({"name": cfg["labels"]["risk"], "color": "b60205",
                   "description": "Touches auth, migrations, data deletion, a public API or a risk path. Raises the model."})
    labels.append({"name": cfg["labels"]["integrated"], "color": "0e8a16",
                   "description": "Merged into the milestone's integration branch. Counts as done for blocking."})
    return labels


def plan(existing_names, cfg: dict) -> dict:
    """{"create": [label...], "present": [name...], "missing_triage": [name...]}. Names compare case-insensitively."""
    have = {n.lower() for n in existing_names}
    create, present = [], []
    for lab in wanted(cfg):
        if lab["name"].lower() in have:
            present.append(lab["name"])
        else:
            create.append(lab)
    return {
        "create": create,
        "present": present,
        "missing_triage": [n for n in cfg["labels"]["triage"] if n.lower() not in have],
    }


def create_args(repo: str, label: dict) -> list:
    return ["label", "create", label["name"], "--repo", repo, "--color", label["color"],
            "--description", label["description"]]
