"""Turn a run's workers and their transcript summaries into a cost profile.

Pure. profile.py gathers the inputs from Orca and the transcript folders.
"""

from __future__ import annotations

from collections import defaultdict

from . import routing
from .transcripts import parse_ts

APPROVED_WORDS = ("approved", "approve", "pass", "passed", "lgtm")
CHANGES_WORDS = ("changes", "request_changes", "changes_requested", "reject", "fail")


def _verdict(outcome: str):
    text = (outcome or "").lower()
    if any(w in text for w in CHANGES_WORDS):
        return "changes"
    if any(w in text for w in APPROVED_WORDS):
        return "approved"
    return None


def _merge_models(into: dict, by_model: dict) -> None:
    for model, slot in by_model.items():
        tgt = into.setdefault(model, {"cost": 0.0, "messages": 0})
        tgt["cost"] += slot.get("cost", 0.0)
        tgt["messages"] += slot.get("messages", 0)


def utilisation(workers: list, slots: int) -> dict:
    """Share of slot time busy between the first start and the last end."""
    spans = []
    for w in workers:
        s, e = parse_ts(w.get("started_at")), parse_ts(w.get("ended_at"))
        if s and e and e >= s:
            spans.append((s, e))
    if not spans or slots <= 0:
        return {"slots": slots, "busy_seconds": 0, "wall_seconds": 0, "utilisation": None, "peak_concurrency": 0}
    start = min(s for s, _ in spans)
    end = max(e for _, e in spans)
    wall = (end - start).total_seconds()
    busy = sum((e - s).total_seconds() for s, e in spans)
    events = sorted([(s, 1) for s, _ in spans] + [(e, -1) for _, e in spans], key=lambda x: (x[0], x[1]))
    cur = peak = 0
    for _, d in events:
        cur += d
        peak = max(peak, cur)
    return {
        "slots": slots,
        "busy_seconds": busy,
        "wall_seconds": wall,
        "utilisation": (busy / (slots * wall)) if wall > 0 else None,
        "peak_concurrency": peak,
    }


def build_profile(run_id: str, workers: list, coordinator: dict | None, merged: list, slots: int) -> dict:
    """
    workers: [{dispatch_id, task_title, started_at, ended_at, outcome, transcripts: [summary]}]
    coordinator: a transcript summary for the coordinator session, or None
    merged: ticket identifiers that merged in this run
    """
    tickets = defaultdict(lambda: {"cost": 0.0, "by_model": {}, "by_role": defaultdict(float), "workers": 0,
                                   "build_models": [], "reviews": []})
    by_model, by_role = {}, defaultdict(float)
    worker_rows = []
    unparsed_titles = []
    for w in workers:
        parsed = routing.parse_task_title(w.get("task_title", ""))
        cost = sum(t["cost"] for t in w.get("transcripts", []))
        models = {}
        for t in w.get("transcripts", []):
            _merge_models(models, t["by_model"])
        _merge_models(by_model, models)
        if parsed is None:
            unparsed_titles.append(w.get("task_title", ""))
            role, ticket, routed = "unknown", None, None
        else:
            role, ticket, routed = parsed["role"], parsed["ticket"], parsed["model"]
        by_role[role] += cost
        if ticket:
            t = tickets[ticket]
            t["cost"] += cost
            t["workers"] += 1
            t["by_role"][role] += cost
            _merge_models(t["by_model"], models)
            if role == "build":
                t["build_models"].append(routed)
            if role in ("review", "check"):
                t["reviews"].append(_verdict(w.get("outcome", "")))
        worker_rows.append({
            "dispatch_id": w.get("dispatch_id"),
            "task_title": w.get("task_title"),
            "ticket": ticket,
            "role": role,
            "routed_model": routed,
            "models": models,
            "cost": cost,
            "transcripts": len(w.get("transcripts", [])),
            "started_at": w.get("started_at"),
            "ended_at": w.get("ended_at"),
            "outcome": w.get("outcome"),
        })

    ticket_rows = []
    escalations = 0
    reviewed = approved_first = 0
    for ident, t in sorted(tickets.items()):
        escalated = len(t["build_models"]) > 1
        escalations += int(escalated)
        rounds = sum(1 for v in t["reviews"] if v is not None)
        first = next((v for v in t["reviews"] if v is not None), None)
        if first is not None:
            reviewed += 1
            approved_first += int(first == "approved")
        ticket_rows.append({
            "ticket": ident,
            "cost": t["cost"],
            "by_model": t["by_model"],
            "by_role": dict(t["by_role"]),
            "workers": t["workers"],
            "escalated": escalated,
            "build_models": t["build_models"],
            "review_rounds": rounds,
            "round_one_approved": first == "approved" if first else None,
            "merged": ident in merged,
        })

    merged_rows = [r for r in ticket_rows if r["merged"]]
    merged_cost = sum(r["cost"] for r in merged_rows)
    total = sum(r["cost"] for r in worker_rows) + (coordinator["cost"] if coordinator else 0.0)
    return {
        "run_id": run_id,
        "total_cost": total,
        "coordinator_cost": coordinator["cost"] if coordinator else None,
        "by_model": by_model,
        "by_role": dict(by_role),
        "merged_tickets": len(merged_rows),
        "cost_per_merged_ticket": (merged_cost / len(merged_rows)) if merged_rows else None,
        "escalations": escalations,
        "review_round_one_approval": (approved_first / reviewed) if reviewed else None,
        "reviewed_tickets": reviewed,
        "slots": utilisation(workers, slots),
        "coordinator_context": coordinator["contexts"] if coordinator else [],
        "tickets": ticket_rows,
        "workers": worker_rows,
        "unparsed_task_titles": unparsed_titles,
    }


def project_update_body(profile: dict, prices_as_of: str) -> str:
    """A short milestone note for a Linear project update."""
    def money(v):
        return "n/a" if v is None else f"${v:,.2f}"

    def pct(v):
        return "n/a" if v is None else f"{v * 100:.0f}%"

    lines = [
        f"**Run {profile['run_id']}**: cost profile (API list-price proxy, prices as of {prices_as_of}).",
        "",
        f"- Merged tickets: {profile['merged_tickets']}, {money(profile['cost_per_merged_ticket'])} each.",
        f"- Total: {money(profile['total_cost'])}; coordinator {money(profile['coordinator_cost'])}.",
        f"- Escalations: {profile['escalations']}. Round-one review approval: {pct(profile['review_round_one_approval'])}.",
        f"- Slot use: {pct(profile['slots']['utilisation'])} of {profile['slots']['slots']} slots, peak {profile['slots']['peak_concurrency']}.",
    ]
    if profile["by_model"]:
        parts = ", ".join(f"{m} {money(v['cost'])}" for m, v in sorted(profile["by_model"].items()))
        lines.append(f"- By model: {parts}.")
    return "\n".join(lines)
