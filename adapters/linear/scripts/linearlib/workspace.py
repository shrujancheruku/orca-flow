"""Read what the Linear workspace and team already have. Reads only."""

from __future__ import annotations

from . import linear as L


class Workspace:
    def __init__(self, client: L.LinearClient, cfg: dict):
        team = client.query(L.TEAM_QUERY, {"id": cfg["team"]["id"]}).get("team")
        if not team:
            raise L.LinearError(f"team {cfg['team']['id']} not found; check team.id in the config")
        if team["key"] != cfg["team"]["key"]:
            raise L.LinearError(f"team {team['id']} has key {team['key']}, not {cfg['team']['key']}")
        self.team = team
        self.states = {s["name"].lower(): s for s in team["states"]["nodes"]}
        labels = client.paginate(L.LABELS_QUERY, {}, ["issueLabels"])
        # Workspace labels and this team's labels are both usable on the team's issues.
        self.labels = {}
        for lab in labels:
            if lab.get("isGroup"):
                continue
            team_id = (lab.get("team") or {}).get("id")
            if team_id not in (None, team["id"]):
                continue
            key = lab["name"].lower()
            if key not in self.labels or team_id is None:
                self.labels[key] = lab
        self.project_labels = {l["name"].lower(): l for l in client.paginate(L.PROJECT_LABELS_QUERY, {}, ["projectLabels"])}
        self.initiatives = {i["name"].lower(): i for i in client.paginate(L.INITIATIVES_QUERY, {}, ["initiatives"])}
        self.project_statuses = client.paginate(L.PROJECT_STATUSES_QUERY, {}, ["projectStatuses"])

    def state_id(self, name: str):
        s = self.states.get(name.lower())
        return s["id"] if s else None

    def label_id(self, name: str):
        lab = self.labels.get(name.lower())
        return lab["id"] if lab else None

    def project_label_id(self, name: str):
        lab = self.project_labels.get(name.lower())
        return lab["id"] if lab else None

    def initiative_id(self, name: str):
        i = self.initiatives.get(name.lower())
        return i["id"] if i else None

    def project_status_id(self, status_type: str):
        for s in self.project_statuses:
            if s["type"] == status_type:
                return s["id"]
        return None
