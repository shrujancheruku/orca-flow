"""Worker briefs: one template per role, filled with context pointers.

`templates/briefs/<role>.md` holds `{{name}}` placeholders. A template is filled from
values the coordinator passes; nothing is read from GitHub or Orca. A repo's own
`docs/agents/briefs/<role>.md` and the coordinator's ticket-specific text follow it.
"""

from __future__ import annotations

from pathlib import Path

ROLES = ("build", "check", "merge", "review", "fix")
TEMPLATES = Path(__file__).resolve().parent.parent.parent / "templates" / "briefs"

# placeholder -> the flag that supplies it, for the error a missing value gives.
FLAGS = {
    "repo": "--repo",
    "ticket": "--ticket",
    "pr": "--ticket",
    "url": "--ticket",
    "integration_branch": "--integration-branch",
    "branch": "--branch",
    "tip": "--tip",
    "round": "--round",
    "base": "--base",
}


class BriefError(Exception):
    pass


def placeholders(text: str) -> list:
    out, rest = [], text
    while "{{" in rest:
        _, _, rest = rest.partition("{{")
        name, close, rest = rest.partition("}}")
        if not close:
            raise BriefError("a template has an unclosed {{")
        if name.strip() not in out:
            out.append(name.strip())
    return out


def fill(text: str, values: dict) -> str:
    """Substitute every placeholder. One with no value is an error naming the flag that supplies it."""
    for name in placeholders(text):
        if name not in FLAGS:
            raise BriefError(f"the template has an unknown placeholder {{{{{name}}}}}")
        if not values.get(name):
            raise BriefError(f"{FLAGS[name]} is required for this role")
        text = text.replace("{{" + name + "}}", str(values[name]))
    return text


def template(role: str) -> str:
    return (TEMPLATES / f"{role}.md").read_text(encoding="utf-8")


def build(role: str, values: dict, repo_file: Path | None = None, extra: str | None = None) -> str:
    """The filled template, then the repo's own file for the role when present, then the extra text."""
    parts = [fill(template(role), values).rstrip()]
    if repo_file is not None and repo_file.is_file():
        parts.append(repo_file.read_text(encoding="utf-8").strip())
    if role == "review" and extra is not None and not extra.strip():
        extra = "No carried notes."
    if extra is not None and extra.strip():
        parts.append("## Ticket-specific\n\n" + extra.strip())
    return "\n\n".join(parts) + "\n"
