"""The flow console: start /flow:build from a normal terminal, and watch it there.

The coordinator is a Claude agent in an Orca terminal (`orca agent launch --surface terminal`), not a
child of this process: Orca wakes it with orchestration mail as it would any coordinator, and it keeps
running when the console quits. The console only reads Orca, GitHub and the local stores, and passes
the founder's replies on.

Everything that talks to Orca takes a `runner(args) -> dict` (flowlib.orca.orca in use, a fake in
tests); the caller appends nothing, this module adds `--json`.
"""

from __future__ import annotations

import json
import os
import textwrap
import time
from pathlib import Path

from . import notes as notes_mod
from . import orca as orca_mod
from . import status as status_mod
from .text import clean, cut

REFRESH = 5  # seconds between reads: each read is a handful of CLI calls
LOG_LIMIT = 20
LAST_LINES = 4  # lines of the coordinator's last message on the main view


def objective(spec: str) -> str:
    """The run objective the coordinator is told to create, so the console can find its run from any
    terminal: `run-current` only answers inside the coordinator's own terminal."""
    return f"flow:build {spec}"


def spec_ref(spec) -> str:
    """19 / "#19" -> "#19"; "abc-12" -> "ABC-12" (a Linear spec)."""
    ref = notes_mod.ticket_ref(spec)
    return f"#{ref}" if isinstance(ref, int) else ref


def prompt(spec: str, milestone: str | None = None, automerge: bool = False) -> str:
    target = f"{spec}, milestone {milestone}" if milestone else spec
    lines = [
        f"/flow:build {target}",
        "",
        "You were started from the flow console in the founder's terminal. Additions to the build skill:",
        f'- Before the first worker, bind the run: `orca orchestration run-create --objective "{objective(spec)}" --json`.'
        " The console finds the run by that objective.",
        "- The founder reads the console, not this terminal. Record every question for them with"
        " `status.py --ask` (the console lists it, numbered) and wait for their reply here.",
    ]
    lines.append("- The founder turned automerge on for this run." if automerge
                 else "- Automerge is off: the founder merges the integration PR.")
    return "\n".join(lines)


def launch_args(repo_path: str, text: str, model: str | None, effort: str | None) -> list:
    args = ["agent", "launch", "--agent", "claude", "--surface", "terminal",
            "--worktree", f"path:{repo_path}", "--prompt", text]
    if model:
        args += ["--model", model]
        if effort:  # Orca refuses --effort without --model
            args += ["--effort", effort]
    return args


def parse_launch(result) -> dict:
    """The terminal handle (and the agent's session id, when Orca already has one) from a launch
    result. The result's shape is not documented, so look for the values rather than a path."""
    terminal = session = None
    for path, value in orca_mod.walk(result):
        if not isinstance(value, str):
            continue
        key = path[-1].lower() if path else ""
        if terminal is None and value.startswith("term_"):
            terminal = value
        if session is None and key in ("orcasessionid", "orca_session_id"):
            session = value.split(":", 1)[1] if value.startswith("orca_session_id:") else value
    return {"terminal": terminal, "session": session}


# -- the console's own record --------------------------------------------------

def state_path(cwd: str = ".") -> Path:
    return notes_mod.store_path("console.json", "FLOW_CONSOLE_FILE", cwd)


def load_state(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(path: Path, state: dict) -> None:
    """Local bookkeeping inside .git, like the asks and notes: written without --apply."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
    os.replace(tmp, path)


# -- reading -------------------------------------------------------------------

def _call(runner, args):
    return runner(args + ["--json"])


def find_run(runs: list, spec: str):
    """The newest run whose objective is the console's, else None."""
    want = objective(spec)
    ids = [r.get("id") for r in runs if isinstance(r, dict) and r.get("objective") == want]
    return ids[-1] if ids else None


def read_coordinator(state: dict, runner, errors: list) -> dict:
    """{connected, state, last, session}; fills state["session"] once the agent reports to Orca."""
    out = {"connected": None, "state": None, "last": None, "session": state.get("session")}
    pane = None
    try:
        term = (_call(runner, ["terminal", "show", "--terminal", state["terminal"]]) or {}).get("terminal") or {}
        out["connected"] = bool(term.get("connected"))
        if term.get("tabId") and term.get("leafId"):
            # An agent's paneKey in `agent list` is "<tabId>:<leafId>" of the terminal it runs in.
            pane = f"{term['tabId']}:{term['leafId']}"
    except orca_mod.OrcaError as exc:
        out["connected"] = False
        errors.append(f"coordinator terminal ({exc})")
    try:
        agents = (_call(runner, ["agent", "list"]) or {}).get("agents") or []
    except orca_mod.OrcaError as exc:
        errors.append(f"orca agents ({exc})")
        return out
    for a in agents:
        if not isinstance(a, dict):
            continue
        if (out["session"] and a.get("orcaSessionId") == out["session"]) or (pane and a.get("paneKey") == pane):
            out["state"] = a.get("state")
            out["last"] = a.get("lastAssistantMessage")
            out["session"] = a.get("orcaSessionId") or out["session"]
            break
    return out


def read_log(session, runner, limit: int = LOG_LIMIT) -> list:
    """The coordinator's recent conversation as (role, text) pairs, oldest first."""
    if not session:
        return [("console", "the coordinator has not reported to Orca yet")]
    try:
        data = _call(runner, ["agent", "read", f"orca_session_id:{session}", "--limit", str(limit)]) or {}
    except orca_mod.OrcaError as exc:
        return [("console", f"could not read the conversation ({exc})")]
    out = []
    for e in data.get("entries") or []:
        if not isinstance(e, dict):
            continue
        text = (e.get("text") or "").strip()
        if not text and e.get("tools"):
            names = ", ".join(t.get("name", "?") for t in e["tools"] if isinstance(t, dict))
            text = f"(tools: {names})"
        if text:
            out.append((e.get("role") or e.get("kind") or "?", text))
    return out


def snapshot(state: dict, runner, read_status, asks_file: Path, notes_file: Path) -> dict:
    """Everything one frame shows. `read_status(run_id)` is status.build bound to the config and GitHub;
    the console passes it the run it found, never None, so the footer's `run-current` fallback (which
    would answer for whatever terminal the console runs in) is not used."""
    errors: list = []
    coord = read_coordinator(state, runner, errors)
    if coord["session"]:
        state["session"] = coord["session"]
    if not state.get("run"):
        try:
            state["run"] = find_run((_call(runner, ["orchestration", "run-list"]) or {}).get("runs") or [],
                                    state["spec"])
        except orca_mod.OrcaError as exc:
            errors.append(f"orca runs ({exc})")
    data = None
    if state.get("run"):
        try:
            data = read_status(state["run"])
        except Exception as exc:  # noqa: BLE001 - one bad read must not take the console down
            errors.append(f"status ({type(exc).__name__}: {exc})")
    return {"spec": state["spec"], "run": state.get("run"), "coordinator": coord, "status": data,
            "asks": status_mod.live_asks(asks_file), "notes": notes_mod.live(notes_file),
            "errors": [clean(e) for e in errors], "read_at": time.time()}


# -- drawing -------------------------------------------------------------------

KEYS = "[r] reply  [1-9] answer ask  [l] log  [o] show in Orca  [q] quit"


def _wrap(text: str, width: int, indent: str = "  ", max_lines: int | None = None) -> list:
    lines = []
    for para in str(text or "").splitlines() or [""]:
        lines.extend(textwrap.wrap(clean(para), max(width - len(indent), 20)) or [""])
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines - 1] + [lines[max_lines - 1].rstrip()[: max(width - len(indent) - 1, 1)] + "…"]
    return [indent + l for l in lines]


def _hang(text: str, width: int, indent: str = "  ", hang: str = "     ") -> list:
    """`text` wrapped whole to `width`, first line at `indent` and the rest under its text at `hang`."""
    return textwrap.wrap(clean(text), max(width, len(hang) + 1), initial_indent=indent,
                         subsequent_indent=hang) or [indent]


def coordinator_label(coord: dict, data: dict | None) -> str:
    """The coordinator's state for the title line. Orca says "done" whenever the agent's turn ends, even
    with workers still running or a task of its own open (QA it runs itself, dispatched to its own
    terminal with model `coordinator`), so "done" is said only when nothing in the run is in progress."""
    state = coord["state"]
    if not state:
        return "not connected" if coord["connected"] is False else "starting"
    rows = (data or {}).get("in_progress") or []
    if state != "done" or not rows:
        return state
    own = [r for r in rows if r.get("model") == "coordinator"]
    if own:
        return "working on " + ", ".join(" ".join(x for x in (r["ticket"], r["role"]) if x) for r in own)
    return f"waiting on {len(rows)} in progress"


def frame(snap: dict, width: int = 100, now: float | None = None) -> list:
    """The view as (text, style) lines; style is one of "title", "head", "warn", "dim", "keys" or ""."""
    now = now or time.time()
    coord = snap["coordinator"]
    who = coordinator_label(coord, snap["status"])
    age = int(max(now - snap["read_at"], 0))
    out = [(cut(f"flow · {snap['spec']} · coordinator {who} · {snap['run'] or 'no run yet'} · read {age}s ago",
                width), "title"), ("", "")]

    out.append(("Coordinator", "head"))
    if coord["state"] == "blocked":
        # Orca's "blocked" is an agent held on its own prompt (a permission or a choice), which shows only in
        # its terminal: the console cannot answer it, so say where it is.
        out.append(("  blocked on a prompt in its terminal: press o to answer it in Orca", "warn"))
    if coord["last"]:
        out.extend((l, "") for l in _wrap(coord["last"], width, max_lines=LAST_LINES))
    else:
        out.append(("  nothing said yet", "dim"))
    out.append(("", ""))

    data = snap["status"]
    if data is None:
        out.append(("In progress: waiting for the coordinator to create its run", "dim"))
    else:
        rows = data["in_progress"]
        out.append((f"In progress ({len(rows)})" if rows else "In progress: nothing", "head"))
        for r in rows:
            out.append(("  " + status_mod.worker_line(r), "warn" if r["flags"] else ""))
        if data.get("tally"):
            out.append((status_mod.tally_line(data), "dim"))
    out.append(("", ""))

    # The asks come from the store, numbered so a key answers one; the rest is the footer's list.
    asks = snap["asks"]
    others = [s for s in (data or {}).get("waiting", []) if s["section"] != "asks"]
    if not asks and not others:
        out.append(("Waiting on you: nothing", "head"))
    else:
        out.append(("Waiting on you", "head"))
        if asks:
            out.append((f"Questions from the coordinator ({len(asks)})", "warn"))
            for i, a in enumerate(asks[:9], 1):
                # Never cut: the founder answers from this text, so wrap it to fit the terminal.
                out.extend((l, "") for l in _hang(f"{i}) {status_mod.ask_line(a, None)}", width))
        for s in others:
            out.append((s["heading"] if s["section"] == "pr" else f"{s['heading']} ({s['count']})", "warn"))
            out.extend(("  " + cut(clean(i), width - 2), "") for i in s["items"])
    if snap["notes"]:
        out.append(("", ""))
        out.append((f"Carried notes ({len(snap['notes'])})", "head"))
        out.extend(("  " + cut(notes_mod.note_line(n), width - 2), "dim") for n in snap["notes"][:5])

    unavailable = list(snap["errors"]) + list((data or {}).get("unavailable") or [])
    if unavailable:
        out.append(("", ""))
        out.append((cut("Unavailable: " + "; ".join(cut(u, 100) for u in unavailable), width), "dim"))
    return out


def plain(snap: dict, width: int = 100, now: float | None = None) -> str:
    return "\n".join(text for text, _ in frame(snap, width, now))


# -- acting --------------------------------------------------------------------

def answer_text(ask: dict, answer: str) -> str:
    """A reply to one ask, naming it so the coordinator can clear it with `status.py --done`."""
    return f"Answer to your ask {ask['id']} ({cut(clean(ask.get('text', '')), 160)}): {' '.join(answer.split())}"


def send_args(terminal: str, text: str) -> list:
    # Typed into the coordinator's own prompt, as the founder: `orchestration send` would arrive as
    # agent mail, and an answer such as "automerge on" is the founder's to give, not another agent's.
    return ["terminal", "send", "--terminal", terminal, "--text", " ".join(text.split()), "--enter",
            "--wait-submit", "5"]


def send(state: dict, runner, text: str) -> str:
    """Send `text` to the coordinator; a one-line result for the status bar."""
    if not " ".join(text.split()):
        return "nothing sent"
    try:
        _call(runner, send_args(state["terminal"], text))
    except orca_mod.OrcaError as exc:
        return clean(f"not sent: {exc}")
    return "sent to the coordinator"


def show_in_orca(state: dict, runner) -> str:
    try:
        _call(runner, ["terminal", "switch", "--terminal", state["terminal"]])
    except orca_mod.OrcaError as exc:
        return clean(f"could not switch: {exc}")
    return "the coordinator's terminal is in front in Orca"
