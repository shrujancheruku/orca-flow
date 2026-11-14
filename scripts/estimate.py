#!/usr/bin/env python3
"""Propose `size:` labels (and the `risk` label) for the founder to approve.

  estimate.py propose  reads the open issues, copies any existing `size:` label
                       as the proposal, and asks the `--model` profile (Haiku by default, headless
                       on your Claude subscription) to double-check it or, where there is no
                       label, to size the issue. A last call sizes the
                       Haiku-sized issues against each other. It writes a proposals file and
                       changes nothing on GitHub.
  estimate.py apply    reads the proposals file and, with --apply, edits only the
                       issues marked "approved": true, through
                       `gh issue edit --add-label` (and --remove-label for an
                       old size label that the new one replaces).
  estimate.py backtest sizes closed tickets the same way propose does and scores
                       the answers against what each ticket's merged PR changed
                       (generated_paths left out, cut at size_lines). It also scores
                       the size labels those tickets carried. Answers are cached in
                       --out by prompt, so a rerun asks only about what changed.
                       `--no-model` scores the labels alone, for free.

Risk paths and label names come from docs/agents/flow.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flowlib import agents, backtest, cli, config, estimating, proposals  # noqa: E402
from flowlib import github as gh_mod  # noqa: E402


def save(path: str, cfg: dict, items: list) -> None:
    with open(path, "w") as fh:
        json.dump({"repo": cfg["github_repo"], "proposals": items}, fh, indent=2)
        fh.write("\n")


def propose(args, cfg) -> None:
    gh = gh_mod.Gh(cfg["github_repo"])
    issues = gh.issues(state="open", milestone=args.milestone)
    if args.only:
        wanted = {gh_mod.ticket_number(n) for n in args.only}
        issues = [i for i in issues if i["number"] in wanted]
    elif args.unsized_only:
        issues = [i for i in issues if config.size_from_labels(cfg, i["labels"]) is None]
    issues = issues[: args.limit] if args.limit else issues
    print(f"{len(issues)} issue(s). Asking {args.model} about each; GitHub is not changed.")
    items = []
    if os.path.exists(args.out):
        with open(args.out) as fh:
            items = json.load(fh).get("proposals", [])
    done = {p["number"] for p in items}
    try:
        prof = agents.profile(args.model, cfg["models"])
    except agents.AgentError as exc:
        cli.die(str(exc))
    for issue in issues:
        if issue["number"] in done:
            continue
        ident = f"#{issue['number']}"
        prompt = estimating.build_prompt({"identifier": ident, "title": issue["title"], "description": issue["body"]},
                                         cfg, style=args.style)
        answer = None
        try:
            answer = estimating.parse_answer(agents.ask(prof, prompt, args.timeout), cfg, style=args.style)
        except (agents.AgentError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            print(f"  {ident}: no answer ({exc})")
        hints = estimating.risk_hints(f"{issue['title']}\n{issue['body'] or ''}", cfg)
        try:
            item = proposals.make_proposal(issue, cfg, answer, hints)
        except ValueError:
            continue
        items.append(item)
        flag = "" if item["agrees"] is None else ("  agrees" if item["agrees"] else "  DISAGREES")
        print(f"  {ident}: {item['size']} ({item['source']}){' risk' if item['risk'] else ''}{flag}  {item['reason']}")
        save(args.out, cfg, items)
    sized = [p for p in items if p["source"] == "haiku"]
    # Calibration re-picks sizes from the rubric, which is the breadth-for-size
    # bias the lines style exists to avoid, and it has not been backtested. So it
    # runs only with the rubric style.
    if args.calibrate and args.style == "rubric" and len(sized) > 1:
        print(f"\nCalibrating {len(sized)} size(s) against each other.")
        first = [dict(p, size=p.get("first_size", p["size"])) for p in sized]
        try:
            text = agents.ask(prof, estimating.build_calibration_prompt(first), args.timeout * 2)
            changed = proposals.calibrate(items, estimating.parse_calibration(text, {p["number"] for p in sized}))
        except (agents.AgentError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            print(f"  calibration failed ({exc}); sizes stay as each ticket was sized alone")
        else:
            for p in items:
                if p["number"] in changed:
                    print(f"  #{p['number']}: {p['first_size']} -> {p['size']}  {p['reason']}")
            save(args.out, cfg, items)
    counts = {s: sum(1 for p in items if p["size"] == s) for s in ("S", "M", "L")}
    print(f"\nSizes: S {counts['S']}, M {counts['M']}, L {counts['L']}; risk {sum(1 for p in items if p['risk'])}.")
    print(f"\nWrote {args.out}. Set \"approved\": true on the entries you accept (change \"size\" first to override), "
          "then run `estimate.py apply --apply`.")


def apply(args, cfg) -> None:
    gh = gh_mod.Gh(cfg["github_repo"], apply=args.apply)
    print(cli.mode_line(args.apply))
    with open(args.out) as fh:
        items = json.load(fh)["proposals"]
    approved = [p for p in items if p.get("approved") is True]
    print(f"{len(approved)} of {len(items)} proposal(s) approved.")
    existing = {l["name"].lower() for l in gh.labels()}
    needed = list(cfg["labels"]["size"].values()) + [cfg["labels"]["risk"]]
    missing = [n for n in needed if n.lower() not in existing]
    if approved and missing:
        cli.die(f"labels missing on {cfg['github_repo']}: {', '.join(missing)}. Run setup_labels.py --apply first.")
    for p in approved:
        current = gh.issue(p["number"])["labels"]
        edits = proposals.label_edits(p, cfg, current)
        if not edits["add"] and not edits["remove"]:
            print(f"  #{p['number']}: already {p['size']}")
            continue
        gh.write(proposals.edit_args(gh.repo, p["number"], edits),
                 f"#{p['number']}: +{','.join(edits['add']) or '-'} -{','.join(edits['remove']) or '-'}")
    if not args.apply:
        gh.show_planned(limit=200)
    else:
        print(f"Edited {len(gh.done)} issue(s).")


def backtest_run(args, cfg) -> None:
    gh = gh_mod.Gh(cfg["github_repo"])
    rows = backtest.cases(gh.closed_with_prs(), cfg)
    if args.only:
        wanted = {gh_mod.ticket_number(n) for n in args.only}
        rows = [r for r in rows if r["number"] in wanted]
    rows = rows[: args.limit] if args.limit else rows
    out = args.out
    cache = {}
    if os.path.exists(out):
        with open(out) as fh:
            cache = {r["number"]: r for r in json.load(fh).get("cases", [])}
    print(f"{len(rows)} closed ticket(s) with one merged PR each. GitHub is not changed.")
    prof = None
    if args.model_calls:
        try:
            prof = agents.profile(args.model, cfg["models"])
        except agents.AgentError as exc:
            cli.die(str(exc))
    for r in rows:
        ident = f"#{r['number']}"
        prompt = estimating.build_prompt({"identifier": ident, "title": r["title"], "description": r["body"]},
                                         cfg, style=args.style)
        # Keyed by prompt and model, so a changed rubric or prompt is asked again
        # and an unchanged one is free.
        sha = hashlib.sha256(f"{args.model}\n{prompt}".encode()).hexdigest()[:16]
        old = cache.get(r["number"], {})
        if old.get("prompt_sha") == sha and old.get("estimate") in config.SIZES:
            r.update({k: old[k] for k in ("estimate", "estimate_reason", "estimate_lines", "prompt_sha") if k in old})
            if r.get("estimate_lines") is not None:
                # size_lines may have changed since the answer was cached
                r["estimate"] = estimating.size_for_lines(r["estimate_lines"], cfg)
        elif prof:
            try:
                answer = estimating.parse_answer(agents.ask(prof, prompt, args.timeout), cfg, style=args.style)
            except (agents.AgentError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
                print(f"  {ident}: no answer ({exc})")
            else:
                r.update(estimate=answer["size"], estimate_reason=answer["reason"], prompt_sha=sha)
                said = answer["size"]
                if "lines" in answer:
                    r["estimate_lines"] = answer["lines"]
                    said += f" ({answer['lines']} lines)"
                print(f"  {ident}: said {said}, was {r['actual']} ({r['lines']} lines)")
        cache[r["number"]] = r
        save_backtest(out, cfg, args.model, args.style, rows)
    save_backtest(out, cfg, args.model, args.style, rows)
    print()
    print(backtest.distribution(rows))
    print()
    print(backtest.format_score(f"Estimator ({args.model}, {args.style} prompt)", backtest.score(rows, "estimate")))
    if any(r.get("estimate_lines") is not None for r in rows):
        print(backtest.format_lines_error(rows))
    print()
    print(backtest.format_score("Size labels", backtest.score(rows, "label_size")))
    rank = {s: i for i, s in enumerate(config.SIZES)}
    far = [r for r in rows if r.get("estimate") in rank and abs(rank[r["estimate"]] - rank[r["actual"]]) == 2]
    if far:
        print("\nOff by two sizes:")
        for r in far:
            guess = f" ({r['estimate_lines']} lines)" if r.get("estimate_lines") is not None else ""
            print(f"  #{r['number']}: said {r['estimate']}{guess}, was {r['actual']} ({r['lines']} lines, PR #{r['pr']}). "
                  f"{r.get('estimate_reason', '')}")
    print(f"\nWrote {out}.")


def save_backtest(path: str, cfg: dict, model: str, style: str, rows: list) -> None:
    with open(path, "w") as fh:
        json.dump({"repo": cfg["github_repo"], "model": model, "style": style, "size_lines": cfg["size_lines"],
                   "generated_paths": cfg.get("generated_paths", []),
                   "cases": [{k: v for k, v in r.items() if k != "body"} for r in rows]}, fh, indent=2)
        fh.write("\n")


def main() -> None:
    p = cli.parser(__doc__)
    p.add_argument("command", choices=["propose", "apply", "backtest"])
    p.add_argument("--out",
                   help="proposals file (default: ./estimate-proposals.json; backtest: ./estimate-backtest.json)")
    p.add_argument("--model", default="haiku", help="model alias for propose (default haiku)")
    p.add_argument("--milestone", help="only issues in this GitHub Milestone (title)")
    p.add_argument("--unsized-only", action="store_true", help="skip issues that already have a size: label (no double-check)")
    p.add_argument("--limit", type=int, help="ask about at most this many issues")
    p.add_argument("--only", nargs="*", help="only these issues, e.g. 12 13")
    p.add_argument("--no-calibrate", dest="calibrate", action="store_false",
                   help="skip the pass that sizes the tickets against each other")
    p.add_argument("--timeout", type=int, default=180, help="seconds per model call")
    # lines is the default: on Issho's 69 closed tickets it sized 78% exactly
    # against the rubric prompt's 52% (backtest, 2026-11-14).
    p.add_argument("--style", choices=estimating.STYLES, default="lines",
                   help="lines (default): the model estimates changed lines and size_lines turns them into "
                        "S/M/L. rubric: it picks S/M/L from the rubric")
    p.add_argument("--no-model", dest="model_calls", action="store_false",
                   help="backtest: ask no model; score the labels and any cached answers")
    args = p.parse_args()
    args.out = args.out or (f"estimate-backtest-{args.style}.json" if args.command == "backtest" else "estimate-proposals.json")
    cfg = cli.load(args)
    try:
        {"propose": propose, "apply": apply, "backtest": backtest_run}[args.command](args, cfg)
    except gh_mod.GitHubError as exc:
        cli.die(str(exc))


if __name__ == "__main__":
    main()
