#!/usr/bin/env python3
"""Post a profile summary to a Linear project as a project update.

  project_update.py --profile profile-<run>.json --project <project id> [--apply]

The Linear counterpart of the integration-PR comment the GitHub path uses.
Dry run by default.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "scripts"))

from flowlib import profiler  # noqa: E402
from linearlib import cli  # noqa: E402
from linearlib import linear as L  # noqa: E402

PROJECT_UPDATE = """mutation($input: ProjectUpdateCreateInput!) {
  projectUpdateCreate(input: $input) { success projectUpdate { id url } } }"""


def main() -> None:
    p = cli.parser(__doc__)
    p.add_argument("--profile", required=True, help="the JSON profile.py wrote")
    p.add_argument("--project", required=True, help="Linear project id")
    p.add_argument("--health", default="onTrack", choices=["onTrack", "atRisk", "offTrack"])
    args = p.parse_args()
    cfg = cli.load(args)
    with open(args.profile) as fh:
        profile = json.load(fh)
    body = profiler.summary_body(profile, profile.get("prices_as_of", "unknown"))
    print(body)
    client = cli.client(cfg, args.apply)
    client.mutate("projectUpdateCreate", PROJECT_UPDATE,
                  {"input": {"projectId": args.project, "body": body, "health": args.health}},
                  f"post the run summary to project {args.project}")
    if not args.apply:
        cli.show_planned(client)


if __name__ == "__main__":
    try:
        main()
    except L.LinearError as exc:
        cli.die(str(exc))
