from flowlib import config


def cfg(**over):
    raw = {
        "github_repo": "acme/app",
        "risk_paths": ["packages/records/**", "**/migrations/**"],
        "slack_prefix": "app",
    }
    raw.update(over)
    return config.from_dict(raw)
