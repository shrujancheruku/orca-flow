"""Size proposals: what the estimator writes for the founder, and the label edits an approval turns into.

Pure. estimate.py gathers the issues, asks Haiku and runs the edits.
"""

from __future__ import annotations

from . import config


def make_proposal(issue: dict, cfg: dict, answer: dict | None, hints: list) -> dict:
    """One entry for the proposals file.

    An existing `size:` label is copied as the proposal and Haiku double-checks
    it; a disagreement is recorded, never acted on. With no label, Haiku's size
    is the proposal.
    """
    existing = config.size_from_labels(cfg, issue["labels"])
    haiku = answer["size"] if answer else None
    size = existing or haiku
    if size is None:
        raise ValueError(f"#{issue['number']}: no existing size and no answer")
    reason = answer["reason"] if answer else ""
    if existing and haiku and haiku != existing:
        reason = f"label says {existing}, Haiku says {haiku}: {reason}"
    return {
        "number": issue["number"],
        "identifier": f"#{issue['number']}",
        "title": issue["title"],
        "size": size,
        "source": "label" if existing else "haiku",
        "existing_size": existing,
        "haiku_size": haiku,
        "agrees": (haiku == existing) if (existing and haiku) else None,
        "risk": config.has_risk_label(cfg, issue["labels"]) or bool(answer and answer["risk"]),
        "risk_hints": hints,
        "reason": reason,
        "approved": False,
    }


def label_edits(proposal: dict, cfg: dict, current_labels: list) -> dict:
    """The labels to add and remove so the issue carries exactly the approved size, plus `risk` if proposed."""
    wanted = config.size_label(cfg, proposal["size"])
    have = {l.lower() for l in current_labels}
    sizes = cfg["labels"]["size"]
    add, remove = [], []
    if wanted.lower() not in have:
        add.append(wanted)
    remove += [name for name in sizes.values() if name.lower() in have and name.lower() != wanted.lower()]
    risk = cfg["labels"]["risk"]
    if proposal.get("risk") and risk.lower() not in have:
        add.append(risk)
    return {"add": add, "remove": remove}


def edit_args(repo: str, number: int, edits: dict) -> list:
    args = ["issue", "edit", str(number), "--repo", repo]
    for name in edits["add"]:
        args += ["--add-label", name]
    for name in edits["remove"]:
        args += ["--remove-label", name]
    return args
