#!/usr/bin/env python3
"""Print a worker's brief from the role's template, for `worker-start --spec-file -`.

  brief.py --role build --ticket 22 --integration-branch integration/run-learnings
  brief.py --role check --ticket 22 --integration-branch integration/m --branch me/22-x --tip abc1234 [--round 2]
  brief.py --role merge --ticket 22 --integration-branch integration/m --branch me/22-x
  brief.py --role review --ticket 45 --integration-branch integration/m [--base main]
  brief.py --role fix --ticket 45 --integration-branch integration/m [--round 2]

Pipe it: `brief.py ... | orca orchestration worker-start --spec-file - ...`.

--ticket is the issue number (or a Linear ID like ABC-7 for build, check and merge), or for review and fix the integration PR's number
(as for route.py); --pr names the PR instead when the ticket is also needed.
--ticket-url overrides the URL for another tracker. The repo is `github_repo` in
the config (or --repo). Nothing is read from GitHub or Orca, and nothing is written.

--extra <file> (or `-` for stdin; required for review, where an empty file means none) appends the coordinator's ticket-specific text under
a heading: the adversarial question for a check, `notes.py --markdown` for a review.
A repo's own docs/agents/briefs/<role>.md, when present, is appended after the
template and before the extra text.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flowlib import briefs, cli  # noqa: E402
from flowlib import github as gh_mod  # noqa: E402
from flowlib import notes as notes_mod  # noqa: E402


def main() -> int:
    p = cli.parser(__doc__, mutates=False)
    p.add_argument("--role", required=True, choices=briefs.ROLES)
    p.add_argument("--ticket", help="issue number (7 or #7); for review and fix, the integration PR's number")
    p.add_argument("--pr", help="the integration PR's number, for review and fix, when --ticket is something else")
    p.add_argument("--ticket-url", help="the ticket's URL when the tracker is not GitHub")
    p.add_argument("--integration-branch", help="integration/<milestone-slug>")
    p.add_argument("--branch", help="the ticket's branch (check, merge)")
    p.add_argument("--tip", help="the branch's tip SHA (check)")
    p.add_argument("--round", default="1", help="which round of check or fix this is (default 1)")
    p.add_argument("--base", default="main", help="the base branch the integration PR targets (default main)")
    p.add_argument("--extra", metavar="FILE", help="ticket-specific text to append; - reads stdin")
    p.add_argument("--briefs-dir", default="docs/agents/briefs", help="the repo's own briefs (default docs/agents/briefs)")
    args = p.parse_args()
    # With --repo and --ticket-url (a Linear repo) there is nothing to read from the config.
    cfg = {"github_repo": args.repo} if args.repo and args.ticket_url else cli.load(args)

    pr_role = args.role in ("review", "fix")
    try:
        if args.pr or pr_role:
            number = gh_mod.ticket_number(args.pr or args.ticket) if (args.pr or args.ticket) else None
        else:
            # A worker's ticket may be a Linear ID (ABC-7); the parsing is notes.py's.
            number = notes_mod.ticket_ref(args.ticket) if args.ticket else None
    except gh_mod.GitHubError as exc:
        cli.die(str(exc))
    if isinstance(number, str) and not args.ticket_url:
        # A Linear ID has no GitHub issue to link; guessing the URL would send the worker to a page that does not exist.
        cli.die(f"--ticket {number} is a Linear ID: pass --ticket-url")
    kind = "pull" if pr_role else "issues"
    url = args.ticket_url or (f"https://github.com/{cfg.get('github_repo')}/{kind}/{number}" if number else None)
    values = {
        "repo": cfg.get("github_repo"), "ticket": number, "pr": number, "url": url,
        "integration_branch": args.integration_branch, "branch": args.branch, "tip": args.tip,
        "round": args.round, "base": args.base,
    }

    if args.role == "review" and args.extra is None:
        # The review reads its carried notes from the extra text; none must be said, not left out.
        cli.die("--extra is required for --role review (an empty file means no carried notes)")
    extra = None
    if args.extra == "":
        extra = ""  # an empty argument is no text, not a missing flag; testing truthiness would drop the review's notes section
    elif args.extra is not None:
        try:
            extra = sys.stdin.read() if args.extra == "-" else Path(args.extra).read_text(encoding="utf-8")
        except OSError as exc:
            cli.die(f"--extra: {exc}")
    try:
        text = briefs.build(args.role, values, Path(args.briefs_dir) / f"{args.role}.md", extra)
    except briefs.BriefError as exc:
        cli.die(str(exc))
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
