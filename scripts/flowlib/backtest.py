"""Pure parts of the estimator backtest: which closed tickets count, how big their PR really was, the score.

A case is a ticket closed as completed by exactly one merged PR that closes
nothing else, so the PR's diff is that ticket's work. Its actual size is the
PR's changed lines without `generated_paths`, cut at `size_lines`.
"""

from __future__ import annotations

import fnmatch

from . import config, estimating

SIZES = config.SIZES


def is_generated(path: str, cfg: dict) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in cfg.get("generated_paths", []))


def measure(pr: dict, cfg: dict) -> dict:
    """Changed lines and files in one PR, generated paths left out.

    GitHub lists at most 100 files per PR here; past that the unlisted files
    count in full, since we can't tell which of them are generated.
    """
    files = (pr.get("files") or {}).get("nodes") or []
    kept = [f for f in files if not is_generated(f["path"], cfg)]
    dropped = sum(f["additions"] + f["deletions"] for f in files if is_generated(f["path"], cfg))
    truncated = pr.get("changedFiles", len(files)) > len(files)
    lines = pr["additions"] + pr["deletions"] - dropped
    n_files = pr.get("changedFiles", len(files)) - (len(files) - len(kept))
    return {"lines": lines, "files": n_files, "generated_lines": dropped, "truncated": truncated}


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
        m = measure(pr, cfg)
        out.append({
            "number": node["number"],
            "title": node["title"],
            "body": node.get("body") or "",
            "label_size": config.size_from_labels(cfg, labels),
            "pr": pr["number"],
            **m,
            "actual": actual_size(m["lines"], cfg),
        })
    return out


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
