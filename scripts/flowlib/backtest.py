"""Pure parts of the estimator backtest: which closed tickets count, how big their PR really was, the score.

A case is a ticket closed as completed by exactly one merged PR that closes
nothing else. Its work is that PR plus the merged PRs that mentioned the ticket
while it was open and close no ticket themselves: a ticket done as a series of
PRs is closed only by the last one. Its actual size is their changed lines
without `generated_paths` or deleted files, cut at `size_lines`.
"""

from __future__ import annotations

import fnmatch
import hashlib

from . import config, estimating

SIZES = config.SIZES


def is_generated(path: str, cfg: dict) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in cfg.get("generated_paths", []))


def _lines(f: dict) -> int:
    return f["additions"] + f["deletions"]


def measure(pr: dict, cfg: dict) -> dict:
    """Changed lines and files in one PR, generated paths and deleted files left out.

    Deleting a whole file is cheap for an agent however long the file was, so
    its lines don't count; the edits that removing it forces elsewhere do. The
    file still counts as touched. GitHub lists at most 100 files per PR here;
    past that the unlisted files count in full, since we can't tell which of
    them are generated or deleted.
    """
    files = (pr.get("files") or {}).get("nodes") or []
    generated = [f for f in files if is_generated(f["path"], cfg)]
    deleted = [f for f in files if f.get("changeType") == "DELETED" and not is_generated(f["path"], cfg)]
    changed = pr.get("changedFiles", len(files))
    return {
        "lines": _lines(pr) - sum(map(_lines, generated)) - sum(map(_lines, deleted)),
        "files": changed - len(generated),
        "generated_lines": sum(map(_lines, generated)),
        "deleted_lines": sum(map(_lines, deleted)),
        "truncated": changed > len(files),
    }


def _mentioning_prs(node: dict, closing: int) -> list:
    """Merged PRs that mentioned the ticket while it was open and close no ticket."""
    out, seen = [], {closing}
    opened, closed = node.get("createdAt") or "", node.get("closedAt") or "9999"
    for item in (node.get("timelineItems") or {}).get("nodes") or []:
        pr = (item or {}).get("source") or {}
        if not pr.get("merged") or pr.get("number") in seen:
            continue
        if pr["closingIssuesReferences"]["totalCount"] or not (opened <= (pr.get("mergedAt") or "") <= closed):
            continue
        seen.add(pr["number"])
        out.append(pr)
    return out


def touched_risk(paths, cfg: dict) -> list:
    """The configured risk paths a PR changed: the truth a risk guess is scored on."""
    return sorted({pat for pat in cfg.get("risk_paths", []) for p in paths if fnmatch.fnmatch(p, pat)})


def risk_score(rows: list, key: str) -> dict:
    """How often a non-empty `key` (the risk reasons guessed from the ticket)
    matched a PR that touched a risk path."""
    caught = sum(1 for r in rows if r.get(key) and r["risk_touched"])
    missed = sum(1 for r in rows if not r.get(key) and r["risk_touched"])
    false = sum(1 for r in rows if r.get(key) and not r["risk_touched"])
    return {"risky": caught + missed, "caught": caught, "missed": missed, "false": false, "n": len(rows)}


def format_risk_score(name: str, s: dict) -> str:
    return (f"{name}: {s['risky']} of {s['n']} PR(s) touched a risk path; caught {s['caught']}, "
            f"missed {s['missed']}, {s['false']} false alarm(s).")


def actual_size(lines: int, cfg: dict) -> str:
    return estimating.size_for_lines(lines, cfg)


def cases(nodes: list, cfg: dict) -> list:
    """The closed issues a backtest can use, each with its PR measured."""
    out = []
    for node in nodes:
        if node.get("stateReason") != "COMPLETED":
            continue
        prs = [p for p in node["closedByPullRequestsReferences"]["nodes"] if p.get("merged")]
        if len(prs) != 1 or prs[0]["closingIssuesReferences"]["totalCount"] != 1:
            continue
        pr = prs[0]
        labels = [l["name"] for l in node["labels"]["nodes"]]
        extra = _mentioning_prs(node, pr["number"])
        parts = [measure(p, cfg) for p in [pr] + extra]
        m = {k: sum(p[k] for p in parts) for k in ("lines", "files", "generated_lines", "deleted_lines")}
        m["truncated"] = any(p["truncated"] for p in parts)
        paths = {f["path"] for p in [pr] + extra for f in (p.get("files") or {}).get("nodes") or []}
        out.append({
            "number": node["number"],
            "title": node["title"],
            "body": node.get("body") or "",
            "created_at": node.get("createdAt"),
            "closed_at": node.get("closedAt"),
            "label_size": config.size_from_labels(cfg, labels),
            "pr": pr["number"],
            "other_prs": [p["number"] for p in extra],
            **m,
            "actual": actual_size(m["lines"], cfg),
            "risk_touched": touched_risk(paths, cfg),
        })
    return out


def in_split(number: int, split: str) -> bool:
    """A fixed quarter of tickets is held out as `test`, picked by number so it
    never moves. Tune prompts on `dev` and look at `test` only to confirm."""
    if split == "all":
        return True
    held_out = hashlib.sha256(str(number).encode()).digest()[0] % 4 == 0
    return held_out if split == "test" else not held_out


def score(rows: list, key: str) -> dict:
    """How the sizes under `key` compare with `actual`, over the rows that have one."""
    rows = [r for r in rows if r.get(key) in SIZES]
    rank = {s: i for i, s in enumerate(SIZES)}
    matrix = {p: {a: 0 for a in SIZES} for p in SIZES}
    under = over = far = 0
    for r in rows:
        p, a = r[key], r["actual"]
        matrix[p][a] += 1
        diff = rank[p] - rank[a]
        under += diff < 0
        over += diff > 0
        far += abs(diff) == 2
    n = len(rows)
    exact = n - under - over
    return {"n": n, "exact": exact, "under": under, "over": over, "far": far, "matrix": matrix}


def format_score(name: str, s: dict) -> str:
    if not s["n"]:
        return f"{name}: no cases"
    pct = lambda k: f"{s[k]} ({100 * s[k] / s['n']:.0f}%)"
    lines = [
        f"{name}: {s['n']} case(s). Exact {pct('exact')}, too small {pct('under')}, "
        f"too big {pct('over')}, off by two sizes {pct('far')}.",
        "  predicted \\ actual    S    M    L",
    ]
    for p in SIZES:
        row = s["matrix"][p]
        lines.append(f"  {p:<20} {row['S']:>4} {row['M']:>4} {row['L']:>4}")
    return "\n".join(lines)


def distribution(rows: list) -> str:
    """The spread of actual changed lines, so `size_lines` can be set from history."""
    lines = sorted(r["lines"] for r in rows)
    if not lines:
        return "no cases"
    q = lambda f: lines[round(f * (len(lines) - 1))]
    counts = {s: sum(1 for r in rows if r["actual"] == s) for s in SIZES}
    return (f"Changed lines (generated left out), p10 {q(.1)}, p25 {q(.25)}, median {q(.5)}, "
            f"p75 {q(.75)}, p90 {q(.9)}. Actual sizes: S {counts['S']}, M {counts['M']}, L {counts['L']}.")


def format_lines_error(rows: list) -> str:
    """How far estimated lines were from actual ones, as a ratio, for the lines style."""
    ratios = sorted(max(r["estimate_lines"], 1) / max(r["lines"], 1)
                    for r in rows if r.get("estimate_lines") is not None)
    if not ratios:
        return "Lines: no estimates"
    within = sum(1 for x in ratios if 0.5 <= x <= 2)
    median = ratios[len(ratios) // 2]
    return (f"Lines: median estimate/actual {median:.2f}, within 2x of actual "
            f"{within} of {len(ratios)} ({100 * within / len(ratios):.0f}%).")
