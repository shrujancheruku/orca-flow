#!/usr/bin/env python3
"""Point GitHub at Linear after the migration.

For each migrated GitHub issue: comment "Moved to ABC-x <url>" (once) and close
it if open. Then write .github/ISSUE_TEMPLATE/config.yml so new issues go to
Linear. GitHub Issues stay enabled so old links keep working.

Dry run by default. --apply comments, closes and writes the file. Safe to
rerun: an issue that already has the "Moved to" comment is skipped.
Run verify.py first; cutover refuses while the mapping file is incomplete.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from linearlib import cli, config as config_mod, github, mapping  # noqa: E402

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "ISSUE_TEMPLATE" / "config.yml"


def moved_line(rec: dict) -> str:
    label = rec.get("identifier") or rec.get("name")
    return f"Moved to {label} {rec['url']}"


def main() -> None:
    p = cli.parser(__doc__)
    p.add_argument("--root", default=".", help="repo root, for the issue template (default: here)")
    p.add_argument("--mapping", help="mapping file (default: mapping_file in the config)")
    p.add_argument("--close-reason", default="not planned", choices=["not planned", "completed"],
                   help="GitHub close reason for open issues (default: not planned)")
    p.add_argument("--github-cache", help="read GitHub issues from this JSON file")
    args = p.parse_args()
    cfg = cli.load(args)
    root = Path(args.root).resolve()
    repo = cfg["github_repo"]
    mpath = args.mapping or str(root / cfg["mapping_file"])
    if not os.path.exists(mpath):
        cli.die(f"no mapping file at {mpath}; run migrate.py --apply first")
    m = mapping.MappingFile.load(mpath, repo)
    if args.github_cache and os.path.exists(args.github_cache):
        with open(args.github_cache) as fh:
            issues = json.load(fh)
    else:
        issues = github.fetch_issues(repo)
    print("APPLY: commenting on and closing GitHub issues" if args.apply else
          "DRY RUN: nothing on GitHub changes (pass --apply)")

    missing = [i["number"] for i in issues if not (m.issue(i["number"]) or m.project(i["number"]))]
    if missing:
        cli.die(f"{len(missing)} issues are not in the mapping file ({sorted(missing)[:10]}...); finish migrate.py")

    counts = {"comment": 0, "close": 0, "skip": 0}
    for issue in sorted(issues, key=lambda i: i["number"]):
        rec = m.issue(issue["number"]) or m.project(issue["number"])
        line = moved_line(rec)
        already = any(c["body"].strip().startswith(f"Moved to {rec.get('identifier') or rec.get('name')}")
                      for c in issue["comments"])
        actions = []
        if not already:
            actions.append("comment")
        if issue["state"] == "OPEN":
            actions.append("close")
        if not actions:
            counts["skip"] += 1
            continue
        print(f"  #{issue['number']}: {' + '.join(actions)}  ({line})")
        for a in actions:
            counts[a] += 1
        if args.apply:
            if "comment" in actions:
                github.gh(["issue", "comment", str(issue["number"]), "--repo", repo, "--body-file", "-"], stdin=line + "\n")
            if "close" in actions:
                github.gh(["issue", "close", str(issue["number"]), "--repo", repo, "--reason", args.close_reason])

    cli.heading("Issue template")
    target = root / ".github" / "ISSUE_TEMPLATE" / "config.yml"
    team_url = f"{config_mod.linear_base_url(cfg)}/team/{cfg['team']['key']}/triage"
    body = TEMPLATE.read_text().replace("{{LINEAR_TEAM_URL}}", team_url).replace("{{TEAM_KEY}}", cfg["team"]["key"])
    if target.exists() and target.read_text() == body:
        print(f"  {target.relative_to(root)}: up to date")
    else:
        print(f"  {'wrote' if args.apply else 'would write'} {target.relative_to(root)} -> {team_url}")
        if args.apply:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body)

    cli.heading("Summary")
    print(f"  comments {counts['comment']}, closes {counts['close']}, already done {counts['skip']}")
    print("  Issues stay enabled on GitHub. Commit the issue template in a PR.")


if __name__ == "__main__":
    main()
