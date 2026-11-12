#!/usr/bin/env python3
"""Create the labels the plugin needs: size:S, size:M, size:L, risk and integrated.

  setup_labels.py            dry run: shows what it would create
  setup_labels.py --apply    runs `gh label create` for each missing label

Safe to rerun: it creates only what is missing, and never edits or deletes a label.
Matt Pocock's five triage labels (needs-triage, needs-info, ready-for-agent,
ready-for-human, wontfix) are made by /setup-matt-pocock-skills. This checks they
exist and reports any that do not; it does not create them.

Names come from docs/agents/flow.json. Without a config, --repo owner/name works.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flowlib import cli, labels  # noqa: E402
from flowlib import github as gh_mod  # noqa: E402


def main() -> int:
    p = cli.parser(__doc__)
    args = p.parse_args()
    cfg = cli.load(args)
    gh = gh_mod.Gh(cfg["github_repo"], apply=args.apply)
    print(cli.mode_line(args.apply))
    print(f"Repo: {gh.repo}")
    try:
        existing = [l["name"] for l in gh.labels()]
        result = labels.plan(existing, cfg)
        for name in result["present"]:
            print(f"  have      {name}")
        for lab in result["create"]:
            print(f"  {'create' if args.apply else 'would create'}  {lab['name']}  ({lab['description']})")
            gh.write(labels.create_args(gh.repo, lab), f"create label {lab['name']}")
    except gh_mod.GitHubError as exc:
        cli.die(str(exc))
    if not result["create"]:
        print("Nothing to create.")
    elif args.apply:
        print(f"Created {len(gh.done)} label(s).")
    else:
        print(f"{len(result['create'])} label(s) would be created. Pass --apply to create them.")
    print("\nMatt Pocock's triage labels:")
    for name in cfg["labels"]["triage"]:
        print(f"  {'MISSING' if name in result['missing_triage'] else 'have   '}  {name}")
    if result["missing_triage"]:
        print("\nMissing triage labels: run /setup-matt-pocock-skills, or create them by hand. This script does not.")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
