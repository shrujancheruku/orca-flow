"""The status footer: what a /flow:build run has in progress, and what waits on the founder.

The coordinator prints `status.py --plain` at the end of every turn, so the
founder never has to ask "what's waiting on me?" mid-run. A Stop hook would be
the natural place, but a Stop hook's stdout does not reach the terminal, so
the build skill tells the coordinator to print it instead.

Sources, each read at most once per footer:

  orca   worker-list (live workers), task-list --full (titles, created_at and
         completed_at, for how long a worker has run and what is typical for
         its role), inbox --terminal run:<id> (worker questions and escalations
         Orca has not marked handled), gate-list (pending decision gates)
  gh     one GraphQL read (two when the milestone comes from the integration
         PR), through the cache in flowlib.ghcache that the console and route.py
         share, so an answer under a minute old is reused and the rate limit is
         watched: the milestone's issues with their labels and native blockers, the
         open issues labelled ready-for-human or needs-info, the integration
         PR with its checks, and the state of each ask's ticket or PR. Every
         query is label-, milestone- or number-filtered, never the backlog.
  asks   a small local file the same script writes (`--ask`, `--done`), so no
         model has to remember what it asked the founder.

A source that fails is named on one `Unavailable:` line and the rest still
prints: this is a footer and must never break a turn.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

from . import ghcache
from . import github as gh_mod
from . import notes as notes_mod
from . import orca as orca_mod
from . import routing
from .text import BIDI, TITLE_MAX, clean, cut  # noqa: F401 - re-exported: callers use status.clean

LIST_MAX = 15  # lines kept per section; the rest is "+N more"
TIMEOUT = 20  # seconds per subprocess: a hung CLI must not hang the turn
DONE_STATES = {"succeeded", "failed", "cancelled", "canceled", "stopped"}
TYPICAL_MIN_SAMPLES = 3

# Matt Pocock's five triage roles, in the order flow.json's labels.triage lists them.
TRIAGE_ROLES = ("needs-triage", "needs-info", "ready-for-agent", "ready-for-human", "wontfix")

SECTIONS = (  # (id, heading, plain marker), in the order they print
    ("human", "Ready for you", "\U0001f7e5"),
    ("needs-info", "Needs info", "\U0001f7e8"),
    ("asks", "Coordinator asks", "\U0001f7e6"),
    ("worker-questions", "Worker questions not yet handled", "\U0001f7ea"),
    ("pr", "Integration PR", "\U0001f7e9"),
)
ANSI = {"human": 31, "needs-info": 33, "asks": 34, "worker-questions": 35, "pr": 32}
NOTHING = "Waiting on you: nothing"


# -- text ---------------------------------------------------------------------

def duration(seconds) -> str:
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m"
    return f"{minutes // 60}h{minutes % 60:02d}m"


def parse_time(value):
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(orca_mod.utc(value)).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


# -- the asks file ------------------------------------------------------------
# The storage is shared with the carried notes (flowlib/notes.py); these keep the asks' names.

def asks_path(cwd: str = ".") -> Path:
    """Where the coordinator's asks live: `$FLOW_ASKS_FILE`, else `<git common dir>/flow/asks.jsonl`."""
    return notes_mod.store_path("asks.jsonl", "FLOW_ASKS_FILE", cwd)


def live_asks(path: Path) -> list:
    return notes_mod.live(path)


def add_ask(path: Path, text: str, ticket=None, where: str = "") -> str:
    number = None if ticket is None else gh_mod.ticket_number(ticket)
    return notes_mod.add(path, text, number, where=" ".join(str(where).split())[:200])


def done_ask(path: Path, ask_id: str) -> bool:
    return notes_mod.done(path, ask_id)


def ask_line(entry: dict, width: int | None = 120) -> str:
    """One ask on one line, cut to `width`; `width=None` keeps the whole question (the console wraps it)."""
    ref = f" (#{entry['ticket']})" if entry.get("ticket") else ""
    where = f" — {entry['where']}" if entry.get("where") else ""
    line = f"[{entry['id']}] {entry.get('text', '')}{ref}{where}"
    return clean(line) if width is None else cut(line, width)


# -- orca ---------------------------------------------------------------------

def _orca(args, runner):
    return runner(args + ["--json"])


def read_orca(run_id, runner, unavailable: list) -> dict:
    """{run, workers, tasks, messages, gates}; each part that could not be read is [] and named in `unavailable`."""
    out = {"run": run_id, "workers": [], "tasks": [], "messages": [], "gates": []}
    if not run_id:
        try:
            run_id = (_orca(["orchestration", "run-current"], runner) or {}).get("runId")
        except orca_mod.OrcaError as exc:
            unavailable.append(f"orca run ({exc})")
            return out
        if not run_id:
            unavailable.append("orca run (no current run; pass --run)")
            return out
    out["run"] = run_id
    reads = (
        ("workers", ["orchestration", "worker-list", "--run", run_id, "--limit", "100"], "workers"),
        ("tasks", ["orchestration", "task-list", "--run", run_id, "--full"], "tasks"),
        ("messages", ["orchestration", "inbox", "--terminal", f"run:{run_id}", "--limit", "100"], "messages"),
        ("gates", ["orchestration", "gate-list", "--run", run_id], "gates"),
    )
    for key, args, field in reads:
        try:
            data = _orca(args, runner)
            out[key] = [x for x in (data.get(field) if isinstance(data, dict) else data) or [] if isinstance(x, dict)]
        except (orca_mod.OrcaError, AttributeError, TypeError) as exc:
            unavailable.append(f"orca {key} ({exc})")
    return out


def role_of(title: str) -> dict:
    parsed = routing.parse_task_title(title or "")
    return parsed or {"ticket": None, "role": None, "model": None}


def typical_durations(tasks: list) -> dict:
    """{role: median seconds} from the run's completed tasks, for roles with enough samples."""
    by_role: dict = {}
    for t in tasks:
        start, end = parse_time(t.get("created_at")), parse_time(t.get("completed_at"))
        role = role_of(t.get("task_title") or t.get("title")).get("role")
        if t.get("status") == "completed" and start and end and role and end > start:
            by_role.setdefault(role, []).append((end - start).total_seconds())
    return {r: statistics.median(v) for r, v in by_role.items() if len(v) >= TYPICAL_MIN_SAMPLES}


def in_progress(workers: list, tasks: list, now: datetime, slow_factor: float, slow_minutes: float) -> list:
    """One record per live worker, oldest first, with its attention flags."""
    by_id = {t.get("id"): t for t in tasks}
    typical = typical_durations(tasks)
    rows = []
    for w in workers:
        if str(w.get("state") or "").lower() in DONE_STATES:
            continue
        task = by_id.get(w.get("taskId")) or {}
        title = task.get("task_title") or task.get("title") or task.get("display_name") or w.get("taskId") or "?"
        parsed = role_of(title)
        started = parse_time(task.get("created_at"))
        elapsed = (now - started).total_seconds() if started else None
        flags = []
        liveness = str(w.get("liveness") or "").lower()
        if liveness == "unverifiable":
            flags.append("no heartbeat")
        elif liveness == "exited":
            flags.append("exited without reporting")
        for a in w.get("attention") or []:
            if str(a).lower() not in ("unverifiable",) and str(a) not in flags:
                flags.append(str(a))
        usual = typical.get(parsed.get("role"))
        if elapsed is not None:
            if usual and elapsed > slow_factor * usual:
                flags.append(f"slow (typical {duration(usual)})")
            elif not usual and elapsed > slow_minutes * 60:
                flags.append(f"slow (over {duration(slow_minutes * 60)})")
        rows.append({"ticket": parsed["ticket"], "role": parsed["role"], "model": parsed["model"],
                     "title": None if parsed["ticket"] else clean(title), "dispatch": w.get("dispatchId"),
                     "elapsed_s": int(elapsed) if elapsed is not None else None, "flags": flags})
    rows.sort(key=lambda r: -(r["elapsed_s"] or 0))
    return rows


def worker_questions(messages: list, gates: list, tasks: list, run_id: str) -> list:
    """Questions and escalations to the coordinator that Orca has not marked handled, then pending gates."""
    titles = {t.get("id"): t.get("task_title") or t.get("title") or "" for t in tasks}
    items = []
    for m in messages:
        if m.get("type") not in ("question", "escalation") or m.get("handled") is not False:
            continue
        if m.get("to") and m.get("to") != f"run:{run_id}":
            continue
        who = role_of(titles.get((m.get("payload") or {}).get("taskId"), ""))
        prefix = f"{who['ticket']} {who['role']}: " if who.get("ticket") else ""
        text = m.get("subject") or (m.get("body") or "").split("\n", 1)[0]
        items.append(cut(f"{prefix}{m.get('type')}: {text}", 110))
    for g in gates:
        if str(g.get("status") or "").lower() not in ("pending", "open", "waiting"):
            continue
        text = orca_mod.first(g, "question", "prompt", "title", "subject") or g.get("id") or "?"
        items.append(cut(f"gate: {text}", 110))
    return items


# -- GitHub -------------------------------------------------------------------

ISSUE_FIELDS = "number title state labels(first: 30) { nodes { name } }"
PR_FIELDS = """number title state isDraft mergeStateStatus headRefName milestone { title }
  commits(last: 1) { nodes { commit { statusCheckRollup { state
    contexts(first: 100) { nodes { __typename ... on CheckRun { status conclusion } ... on StatusContext { state } } }
  } } } }"""


def _q(text: str) -> str:
    return json.dumps(str(text))  # a GraphQL string literal; JSON's escaping is the same


def _search(alias: str, query: str, fields: str, first: int = 100) -> str:
    return f"{alias}: search(query: {_q(query)}, type: ISSUE, first: {first}) {{ issueCount nodes {{ ... on Issue {{ {fields} }} }} }}"


def milestone_part(repo: str, milestone: str) -> str:
    fields = f"{ISSUE_FIELDS} blockedBy(first: 20) {{ nodes {{ {ISSUE_FIELDS} }} }}"
    return _search("milestone", f"repo:{repo} is:issue milestone:{_q(milestone)}", fields)


def first_query(repo: str, labels: dict, milestone, pr, refs) -> str:
    owner, name = repo.split("/")
    owned = ",".join(_q(labels[k]) for k in ("human", "info"))
    parts = [_search("owner", f"repo:{repo} is:issue is:open label:{owned}",
                     f"{ISSUE_FIELDS} milestone {{ title }}", 50)]
    repo_parts = []
    if pr:
        repo_parts.append(f"pr: pullRequest(number: {int(pr)}) {{ {PR_FIELDS} }}")
    else:
        repo_parts.append("prs: pullRequests(states: OPEN, first: 30, orderBy: {field: CREATED_AT, direction: DESC}) "
                          f"{{ nodes {{ {PR_FIELDS} }} }}")
    for n in sorted(set(refs)):
        repo_parts.append(f"r{int(n)}: issueOrPullRequest(number: {int(n)}) "
                          "{ ... on Issue { state } ... on PullRequest { state } }")
    parts.append(f"repository(owner: {_q(owner)}, name: {_q(name)}) {{ {' '.join(repo_parts)} }}")
    if milestone:
        parts.append(milestone_part(repo, milestone))
    return "query { " + " ".join(parts) + " }"


def graphql(gh, query: str) -> dict:
    # Every footer query reports what it cost and what is left, so the reader (flowlib.ghcache) can
    # slow down, then stop, before the hour's limit runs out instead of after.
    if query.startswith("query {") and "rateLimit" not in query:
        query = query[:-1].rstrip() + f" {ghcache.RATE_FIELDS} }}"
    data = gh.read_json(["api", "graphql", "-f", f"query={query}"]) or {}
    if data.get("errors") and not data.get("data"):
        raise gh_mod.GitHubError(f"GraphQL: {data['errors'][0].get('message', 'error')}")
    return data.get("data") or {}


def label_names(node) -> set:
    return {l["name"] for l in ((node or {}).get("labels") or {}).get("nodes") or []}


def pick_pr(data: dict, milestone, unavailable: list):
    repo = data.get("repository") or {}
    if "pr" in repo:
        return repo.get("pr")
    prs = [p for p in (repo.get("prs") or {}).get("nodes") or [] if (p.get("headRefName") or "").startswith("integration/")]
    if milestone:
        prs = [p for p in prs if ((p.get("milestone") or {}).get("title")) == milestone]
    if len(prs) > 1:
        unavailable.append(f"integration PR ({len(prs)} open: {', '.join('#%d' % p['number'] for p in prs)}; pass --pr)")
        return None
    return prs[0] if prs else None


def check_counts(pr: dict) -> dict:
    nodes = ((pr.get("commits") or {}).get("nodes") or [{}])
    rollup = ((nodes[-1] if nodes else {}).get("commit") or {}).get("statusCheckRollup") or {}
    counts = {"green": 0, "red": 0, "pending": 0}
    for c in ((rollup.get("contexts") or {}).get("nodes") or []):
        if c.get("__typename") == "StatusContext":
            state = c.get("state")
            key = "green" if state == "SUCCESS" else "pending" if state in ("PENDING", "EXPECTED") else "red"
        else:
            if c.get("status") != "COMPLETED":
                key = "pending"
            else:
                key = "green" if c.get("conclusion") in ("SUCCESS", "NEUTRAL", "SKIPPED") else "red"
        counts[key] += 1
    return counts


def tally(issues: list, live: set, labels: dict) -> dict:
    """Integrated / in progress / ready next / blocked / waiting on you, from the milestone's issues."""
    def done(node):
        return node.get("state") == "CLOSED" or labels["integrated"] in label_names(node)

    out = {"total": len(issues), "integrated": 0, "in_progress": 0, "ready_next": 0, "blocked": 0,
           "waiting_on_you": 0, "other": 0}
    for i in issues:
        names = label_names(i)
        if done(i):
            out["integrated"] += 1
        elif f"#{i['number']}" in live:
            out["in_progress"] += 1
        elif names & {labels["human"], labels["info"]}:
            out["waiting_on_you"] += 1
        elif labels["agent"] in names:
            blockers = ((i.get("blockedBy") or {}).get("nodes") or [])
            out["blocked" if any(not done(b) for b in blockers) else "ready_next"] += 1
        else:
            out["other"] += 1
    return out


def read_github(gh, repo, labels, milestone, pr_number, refs, unavailable: list) -> dict:
    out = {"milestone": milestone, "issues": None, "owner": None, "owner_count": 0, "pr": None, "ref_states": {}}
    try:
        data = graphql(gh, first_query(repo, labels, milestone, pr_number, refs))
    except ghcache.Paused:
        return out  # build() names the pause once, from gh.notice()
    except (gh_mod.GitHubError, ValueError) as exc:
        unavailable.append(f"GitHub ({exc})")
        return out
    owner = data.get("owner") or {}
    out["owner"] = [n for n in owner.get("nodes") or [] if n]
    out["owner_count"] = owner.get("issueCount") or len(out["owner"])
    repo_data = data.get("repository") or {}
    for n in refs:
        node = repo_data.get(f"r{int(n)}")
        if node and node.get("state"):
            out["ref_states"][int(n)] = node["state"]
    out["pr"] = pick_pr(data, milestone, unavailable)
    if not milestone and out["pr"]:
        milestone = (out["pr"].get("milestone") or {}).get("title")
        out["milestone"] = milestone
        if milestone:
            try:
                data.update(graphql(gh, "query { " + milestone_part(repo, milestone) + " }"))
            except ghcache.Paused:
                pass
            except (gh_mod.GitHubError, ValueError) as exc:
                unavailable.append(f"milestone issues ({exc})")
    if "milestone" in data:
        out["issues"] = [n for n in (data["milestone"] or {}).get("nodes") or [] if n]
    return out


# -- the footer ---------------------------------------------------------------

def section(sid: str, items: list, count: int) -> dict:
    heading = dict((s[0], s[1]) for s in SECTIONS)[sid]
    if count > len(items):
        items = items + [f"+{count - len(items)} more"]
    return {"section": sid, "heading": heading, "count": count, "items": items}


def issue_line(node: dict, note: str = "") -> str:
    return f"#{node['number']} {cut(node.get('title', ''))}{note}"


def waiting(gh_data: dict, labels: dict, asks: list, questions: list, tly) -> list:
    milestone = gh_data.get("milestone")
    sections = {}
    owner = gh_data.get("owner")
    if owner is not None:
        if milestone:
            # A build is about its milestone: tickets outside it are not this run's to wait on.
            owner = [n for n in owner if (n.get("milestone") or {}).get("title") == milestone]
        human = [n for n in owner if labels["human"] in label_names(n)]
        info = [n for n in owner if labels["info"] in label_names(n)]
        truncated = gh_data.get("owner_count", 0) > len(gh_data.get("owner") or [])
        if human:
            sections["human"] = [issue_line(n) for n in human]
        if info:
            sections["needs-info"] = [issue_line(n) for n in info]
        if truncated:
            last = "needs-info" if info else "human"
            more = gh_data["owner_count"] - len(gh_data["owner"])
            note = (f"+{more} more not read across the repo (the query keeps 50); some may be in this milestone"
                    if milestone else f"+{more} more not read (the query keeps 50)")
            sections.setdefault(last, []).append(note)
    if asks:
        sections["asks"] = [ask_line(a) for a in asks]
    if questions:
        sections["worker-questions"] = questions
    pr = gh_data.get("pr")
    if pr and pr.get("state", "OPEN") == "OPEN":
        all_in = bool(tly) and tly["total"] > 0 and tly["integrated"] == tly["total"]
        if not pr.get("isDraft") or all_in:
            c = check_counts(pr)
            why = "every milestone ticket integrated" if all_in else "no longer draft"
            draft = ", still draft" if pr.get("isDraft") else ""
            # "Ready to merge" only when it can be merged: a red or running check, or a branch
            # behind or in conflict with its base, is the coordinator's to clear first.
            merge_state = {"BEHIND": "behind its base", "DIRTY": "conflicts with its base"}.get(pr.get("mergeStateStatus"))
            blocks = [b for b in (merge_state, f"{c['red']} red" if c["red"] else "",
                                  f"{c['pending']} pending" if c["pending"] else "") if b]
            verdict = f"not ready to merge yet: {', '.join(blocks)}" if blocks else "ready for you to merge"
            sections["pr"] = [f"PR #{pr['number']} {verdict} ({why}{draft}): "
                              f"checks {c['green']} green, {c['red']} red, {c['pending']} pending"]
    out = []
    for sid, _, _ in SECTIONS:
        if sections.get(sid):
            items = sections[sid]
            out.append(section(sid, items[:LIST_MAX], len(items)))
    return out


def label_config(cfg) -> dict:
    triage = list((cfg or {}).get("labels", {}).get("triage") or TRIAGE_ROLES)
    triage += list(TRIAGE_ROLES[len(triage):])
    role = dict(zip(TRIAGE_ROLES, triage))
    return {"human": role["ready-for-human"], "info": role["needs-info"], "agent": role["ready-for-agent"],
            "integrated": (cfg or {}).get("labels", {}).get("integrated") or "integrated"}


def build(*, cfg, run_id=None, milestone=None, pr=None, asks_file: Path, notes_file=None, orca_runner, gh=None,
          now=None, slow_factor=None, slow_minutes=None) -> dict:
    """The footer's data. `cfg` None (no config) or a Linear config skips GitHub; `gh` None means no GitHub."""
    now = now or datetime.now(timezone.utc)
    settings = (cfg or {}).get("status") or {}
    slow_factor = slow_factor or settings.get("slow_factor") or 3
    slow_minutes = slow_minutes or settings.get("slow_minutes") or 120
    labels = label_config(cfg)
    unavailable: list = []

    run = read_orca(run_id, orca_runner, unavailable)
    rows = in_progress(run["workers"], run["tasks"], now, slow_factor, slow_minutes)
    questions = worker_questions(run["messages"], run["gates"], run["tasks"], run["run"]) if run["run"] else []

    asks = live_asks(asks_file)
    refs = [a["ticket"] for a in asks if isinstance(a.get("ticket"), int)]
    gh_data = {"milestone": milestone, "issues": None, "owner": None, "pr": None, "ref_states": {}}
    if cfg is None:
        unavailable.append("GitHub (no docs/agents/flow.json; pass --repo owner/name)")
    elif cfg.get("tracker") != "github":
        unavailable.append(f"tickets (tracker is {cfg.get('tracker')}; the footer reads GitHub Issues only)")
    elif gh is not None:
        gh_data = read_github(gh, cfg["github_repo"], labels, milestone, pr, refs, unavailable)
        notice = gh.notice() if hasattr(gh, "notice") else ""
        if notice:
            unavailable.append(notice)
    # An ask whose ticket or PR closed (or merged) is settled: drop it, and clear it in the file.
    kept = []
    for a in asks:
        if gh_data["ref_states"].get(a.get("ticket")) in ("CLOSED", "MERGED"):
            done_ask(asks_file, a["id"])
        else:
            kept.append(a)

    live_tickets = {r["ticket"] for r in rows if r["ticket"]}
    tly = tally(gh_data["issues"], live_tickets, labels) if gh_data["issues"] is not None else None
    # Review, fix and merge workers run on the integration PR's number, which is no milestone
    # ticket: without this the tally reads "0 in progress" under a live worker.
    off_ticket = 0
    if gh_data["issues"] is not None:
        numbers = {f"#{i['number']}" for i in gh_data["issues"]}
        off_ticket = sum(1 for r in rows if r["ticket"] not in numbers)
    return {"run": run["run"], "milestone": gh_data.get("milestone"), "in_progress": rows, "tally": tly,
            "off_ticket_workers": off_ticket,
            "notes_carried": len(notes_mod.live(notes_file)) if notes_file else 0,
            "waiting": waiting(gh_data, labels, kept, questions, tly), "unavailable": [clean(u) for u in unavailable]}


def worker_line(r: dict) -> str:
    who = " ".join(x for x in (r["ticket"], r["role"], r["model"]) if x) or cut(r.get("title") or "?", 40)
    when = duration(r["elapsed_s"]) if r["elapsed_s"] is not None else "?"
    flags = f" ! {', '.join(r['flags'])}" if r["flags"] else ""
    return clean(f"{who} {when}{flags}")


def tally_line(data: dict) -> str:
    t = data["tally"]
    extra = f", {t['other']} other" if t.get("other") else ""
    n = data.get("off_ticket_workers") or 0
    if n:
        extra += f"; {n} worker{'s' if n > 1 else ''} on the integration PR or outside the tickets"
    k = data.get("notes_carried") or 0
    if k:
        extra += f"; {k} note{'s' if k > 1 else ''} carried to the review"
    return clean(f"{cut(data['milestone'] or 'milestone', 40)}: {t['integrated']}/{t['total']} integrated, "
                 f"{t['in_progress']} in progress, {t['ready_next']} ready next, {t['blocked']} blocked, "
                 f"{t['waiting_on_you']} waiting on you{extra}")


def render(data: dict, style: str = "plain") -> list:
    """Lines for `plain` (an emoji marker per section, no ANSI) or `tty` (ANSI colour)."""
    colour = style == "tty"
    markers = {s[0]: s[2] for s in SECTIONS}

    def head(text, sid=None, code=1):
        if colour:
            return f"\033[1;{ANSI.get(sid, 0) if sid else code}m{text}\033[0m"
        return f"{markers[sid]} {text}" if sid else text

    lines = []
    rows = data["in_progress"]
    if data["run"]:
        lines.append(head(f"In progress ({len(rows)})" if rows else "In progress: nothing", code=36))
        for r in rows:
            line = "  " + worker_line(r)
            lines.append(f"\033[31m{line}\033[0m" if colour and r["flags"] else line)
    if data["tally"]:
        lines.append(tally_line(data))
    if not data["waiting"]:
        # With a source unread, "nothing" would claim more than the footer knows.
        lines.append(head(NOTHING if not data["unavailable"] else NOTHING + " that could be read", code=32))
    else:
        lines.append(head("Waiting on you", code=1))
        for s in data["waiting"]:
            lines.append(head(f"{s['heading']} ({s['count']})" if s["section"] != "pr" else s["heading"], s["section"]))
            lines.extend("  " + clean(i) for i in s["items"])
    if data["unavailable"]:
        lines.append(clean("Unavailable: " + "; ".join(cut(u, 100) for u in data["unavailable"])))
    return lines
