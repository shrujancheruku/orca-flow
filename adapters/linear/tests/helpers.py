from linearlib import config


def cfg(**over):
    raw = {
        "workspace_id": "ws",
        "workspace_url_key": "acme",
        "team": {"key": "ABC", "id": "team-1"},
        "keychain_service": "linear-test",
        "github_repo": "acme/app",
        "initiative": {"name": "App MVP"},
        "labels": {"workspace": ["wayfinder:task"]},
        "risk_paths": ["packages/records/**"],
    }
    raw.update(over)
    return config.from_dict(raw)


def issue(number, title="Do a thing", state="OPEN", reason="", labels=(), parent=None, sub=(), blocked_by=(),
          body="", comments=()):
    return {
        "number": number,
        "title": title,
        "body": body,
        "url": f"https://github.com/acme/app/issues/{number}",
        "state": state,
        "state_reason": reason,
        "created_at": "2026-10-01T10:00:00Z",
        "closed_at": "2026-10-02T10:00:00Z" if state == "CLOSED" else None,
        "author": "founder",
        "labels": list(labels),
        "parent": parent,
        "sub_issues": list(sub),
        "sub_issue_total": len(sub),
        "blocked_by": list(blocked_by),
        "comments": list(comments),
        "comment_total": len(comments),
    }
