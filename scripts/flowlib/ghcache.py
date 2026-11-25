"""GitHub reads shared through one small cache file, paced against the GraphQL rate limit.

The console, the status footer and `route.py` all read GitHub during a build, and they share one
5,000-point hourly GraphQL limit with the coordinator's and the workers' own `gh` calls. When the
console spent it, the build's `gh` stalled and `route.py` could not route. So every read goes
through `CachedGitHub`:

- An answer younger than `fresh` seconds (60) is reused, by any of the three: the cache is a file
  under `<git common dir>/flow/` (`github-cache.json`, beside `console.json`), so a footer printed
  right after a console refresh costs nothing.
- Every footer query asks for `rateLimit { cost remaining limit resetAt }` (status.graphql adds it),
  and the last answer is kept in the same file. Below SLOW_AT (20%) of the limit left, answers are
  reused for SLOW_FACTOR times as long. Below STOP_AT (5%), GitHub is not asked again until the
  window resets, and `notice()` says "GitHub paused until HH:MM".
- A primary rate limit error pauses the same way, until the reset GitHub last reported (or
  PRIMARY_PAUSE). A secondary one (too many requests too fast) is retried with backoff, waiting what
  GitHub says in Retry-After when gh passes it on, then pauses for SECONDARY_PAUSE.
- While paused, a read with an earlier answer gets that answer (stale); one with none raises
  `Paused`, so a caller can fall back (route.py reads REST, which has its own limit).

The file is rewritten whole through a temporary file and `os.replace`, so two processes never see a
half-written cache; when both write at once, the later one wins, which costs at most one extra read.
"""

from __future__ import annotations

import calendar
import json
import os
import re
import tempfile
import time
from pathlib import Path

from . import github as gh_mod
from . import notes as notes_mod

FRESH = 60  # seconds an answer is reused for
SLOW_AT = 0.20  # below this share of the hour's limit left, reuse answers for longer
SLOW_FACTOR = 5
STOP_AT = 0.05  # below this, stop asking until the window resets
PRIMARY_PAUSE = 600  # after a rate-limit error with no reset time known
SECONDARY_PAUSE = 60  # GitHub's advice: wait at least a minute after a secondary limit
KEEP = 24 * 3600  # entries older than this are dropped when the file is written
RATE_FIELDS = "rateLimit { cost remaining limit resetAt }"
EXIT_NO_GITHUB = 75  # EX_TEMPFAIL: GitHub could not be read, try again later


class Paused(gh_mod.GitHubError):
    """GitHub is paused for the rate limit and there is no earlier answer to give."""


def cache_path(cwd: str = ".") -> Path:
    return notes_mod.store_path("github-cache.json", "FLOW_GITHUB_CACHE", cwd)


def rate_kind(message: str):
    """"secondary", "primary" or None, from a gh error message."""
    text = str(message).lower()
    if "secondary rate limit" in text or "abuse" in text:
        return "secondary"
    if "rate limit" in text:
        return "primary"
    return None


def retry_after(message: str):
    """Seconds from a Retry-After GitHub passed on through gh, or None."""
    m = re.search(r"retry[- ]after[\"':\s]*(\d+)", str(message), re.I)
    return int(m.group(1)) if m else None


def parse_time(stamp) -> float:
    """GitHub's ISO 8601 `resetAt` ("2026-11-24T09:45:00Z") as epoch seconds; 0 when unreadable."""
    try:
        return float(calendar.timegm(time.strptime(str(stamp).replace("Z", ""), "%Y-%m-%dT%H:%M:%S")))
    except (TypeError, ValueError, OverflowError):
        return 0.0


class Store:
    """The cache: {"reads": {key: {"at", "answer"}}, "rate": {...}}, in a file or (path None) in memory."""

    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.memory = {"reads": {}, "rate": {}}

    def load(self) -> dict:
        if self.path is None:
            return self.memory
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"reads": {}, "rate": {}}
        if not isinstance(data, dict):
            return {"reads": {}, "rate": {}}
        data.setdefault("reads", {})
        data.setdefault("rate", {})
        return data

    def save(self, data: dict, now: float) -> None:
        data["reads"] = {k: v for k, v in data["reads"].items() if now - v.get("at", 0) < KEEP}
        if self.path is None:
            self.memory = data
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".github-cache.")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, self.path)
        except OSError:
            pass  # a cache that cannot be written only costs extra reads


class CachedGitHub:
    """Stands in for a `gh` client's `read_json`. `sleep` is injected so tests never wait."""

    def __init__(self, gh, path=None, fresh: float = FRESH, clock=time.time, sleep=time.sleep,
                 retries: int = 2, max_sleep: float = 30):
        self.gh, self.store, self.fresh = gh, Store(path), fresh
        self.clock, self.sleep, self.retries, self.max_sleep = clock, sleep, retries, max_sleep

    # -- state ----------------------------------------------------------------

    def rate(self) -> dict:
        return self.store.load()["rate"]

    def paused_until(self) -> float:
        until = float(self.rate().get("paused_until") or 0)
        return until if until > self.clock() else 0.0

    def share_left(self, rate: dict | None = None):
        rate = self.rate() if rate is None else rate
        if not rate.get("limit") or rate.get("remaining") is None:
            return None
        return rate["remaining"] / rate["limit"]

    def max_age(self, rate: dict) -> float:
        left = self.share_left(rate)
        return self.fresh * (SLOW_FACTOR if left is not None and left < SLOW_AT else 1)

    def notice(self) -> str:
        """One line for the Unavailable line, or "" when GitHub is read as usual."""
        rate = self.rate()
        until = self.paused_until()
        if until:
            why = rate.get("reason") or "rate limit"
            return f"GitHub paused until {time.strftime('%H:%M', time.localtime(until))} ({why}; showing its last answer)"
        left = self.share_left(rate)
        if left is not None and left < SLOW_AT:
            return (f"GitHub slowed ({rate['remaining']} of {rate['limit']} GraphQL points left this hour; "
                    f"read every {int(self.max_age(rate) // 60)} min)")
        return ""

    def stale(self, args: list):
        """The last answer to `args`, however old, or None."""
        kept = self.store.load()["reads"].get(json.dumps(args))
        return kept["answer"] if kept else None

    # -- reading --------------------------------------------------------------

    def read_json(self, args: list):
        key = json.dumps(args)
        now = self.clock()
        data = self.store.load()
        kept = data["reads"].get(key)
        if kept and now - kept.get("at", 0) < self.max_age(data["rate"]):
            return kept["answer"]
        if float(data["rate"].get("paused_until") or 0) > now:
            if kept:
                return kept["answer"]
            raise Paused(self.notice() or "GitHub paused for the rate limit")
        try:
            answer = self._ask(args)
        except gh_mod.GitHubError as exc:
            data = self.store.load()  # another process may have written meanwhile
            self._pause_for(data["rate"], exc, self.clock())
            self.store.save(data, self.clock())
            if kept and rate_kind(str(exc)):
                return kept["answer"]
            raise
        now = self.clock()
        data = self.store.load()
        data["reads"][key] = {"at": now, "answer": answer}
        self._note_rate(data["rate"], answer, now)
        self.store.save(data, now)
        return answer

    def _ask(self, args: list):
        """One read, retried with backoff on a secondary rate limit."""
        for attempt in range(self.retries + 1):
            try:
                return self.gh.read_json(args)
            except gh_mod.GitHubError as exc:
                if rate_kind(str(exc)) != "secondary" or attempt == self.retries:
                    raise
                wait = retry_after(str(exc)) or 5 * 2 ** attempt
                if wait > self.max_sleep:
                    raise  # too long to block a footer or a frame on; pause instead
                self.sleep(wait)
        raise AssertionError("unreachable")  # pragma: no cover

    def _pause_for(self, rate: dict, exc: Exception, now: float) -> None:
        kind = rate_kind(str(exc))
        if kind == "secondary":
            rate["paused_until"] = now + (retry_after(str(exc)) or SECONDARY_PAUSE)
            rate["reason"] = "secondary rate limit"
        elif kind == "primary":
            reset = parse_time(rate.get("resetAt"))
            rate["paused_until"] = reset if reset > now else now + PRIMARY_PAUSE
            rate["reason"] = "rate limit"

    def _note_rate(self, rate: dict, answer, now: float) -> None:
        got = ((answer or {}).get("data") or {}).get("rateLimit") if isinstance(answer, dict) else None
        if not isinstance(got, dict) or got.get("remaining") is None:
            return
        rate.update({k: got.get(k) for k in ("cost", "remaining", "limit", "resetAt")})
        rate["read_at"] = now
        left = self.share_left(rate)
        if left is not None and left < STOP_AT:
            reset = parse_time(rate.get("resetAt"))
            rate["paused_until"] = reset if reset > now else now + PRIMARY_PAUSE
            rate["reason"] = f"{rate['remaining']} of {rate['limit']} points left"
        elif float(rate.get("paused_until") or 0) <= now:
            rate.pop("paused_until", None)
            rate.pop("reason", None)


# -- one ticket's labels and body, for route.py ----------------------------------

class NoGitHub(gh_mod.GitHubError):
    """Neither GraphQL, REST nor the cache could give the ticket; route.py exits EXIT_NO_GITHUB."""


def issue_query(repo: str, number: int) -> str:
    owner, name = repo.split("/")
    fields = "number body labels(first: 30) { nodes { name } }"
    # issueOrPullRequest: a review routes on the integration PR's number, which `issue` would refuse
    return (f"query {{ repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) {{ "
            f"t: issueOrPullRequest(number: {int(number)}) {{ ... on Issue {{ {fields} }} ... on PullRequest {{ {fields} }} }} }} "
            f"{RATE_FIELDS} }}")


def _from_graphql(answer):
    node = (((answer or {}).get("data") or {}).get("repository") or {}).get("t")
    if not node:
        errors = (answer or {}).get("errors") or [{}]
        raise gh_mod.GitHubError(f"GraphQL: {errors[0].get('message', 'no such issue')}")
    return {"labels": [l["name"] for l in (node.get("labels") or {}).get("nodes") or []], "body": node.get("body") or ""}


def issue_facts(cached: CachedGitHub, repo: str, number: int):
    """({"labels", "body"}, source) for one ticket; source is "github", "rest" or "cache (stale)".

    GraphQL through the cache first. When that fails (a rate limit, a pause, a timeout), REST
    (`gh api repos/<repo>/issues/<n>`), which counts against GitHub's separate REST limit, so a
    spent GraphQL hour still routes. Then the last GraphQL answer, however old: a ticket's size and
    risk labels rarely change mid-build. NoGitHub when none of them answers.
    """
    args = ["api", "graphql", "-f", f"query={issue_query(repo, number)}"]
    failures = []
    try:
        return _from_graphql(cached.read_json(args)), "github"
    except (gh_mod.GitHubError, ValueError) as exc:
        failures.append(f"GraphQL: {exc}")
    try:
        # straight to gh, not through the cache: the pause there is for the GraphQL limit only
        issue = cached.gh.read_json(["api", f"repos/{repo}/issues/{int(number)}"]) or {}
        return {"labels": [l["name"] for l in issue.get("labels") or []], "body": issue.get("body") or ""}, "rest"
    except (gh_mod.GitHubError, ValueError, TypeError, KeyError) as exc:
        failures.append(f"REST: {exc}")
    try:
        kept = cached.stale(args)
        if kept is not None:
            return _from_graphql(kept), "cache (stale)"
    except gh_mod.GitHubError:
        pass
    raise NoGitHub("could not read #%d from GitHub (%s)" % (int(number), "; ".join(failures)))


def wait_for_issue(cached: CachedGitHub, repo: str, number: int, max_wait: float, say=print,
                   poll: float = 60, max_poll: float = 300):
    """issue_facts, asked again until it answers or `max_wait` seconds pass (then NoGitHub). It sleeps
    until a known pause ends, else `poll` seconds, never more than `max_poll` at a time, and says each
    wait through `say`, so a coordinator blocks on one command instead of a hand-rolled retry loop."""
    deadline = cached.clock() + max_wait
    while True:
        try:
            return issue_facts(cached, repo, number)
        except NoGitHub as exc:
            now = cached.clock()
            if now >= deadline:
                raise
            until = cached.paused_until()
            wait = min(max((until - now) if until else poll, 1), max_poll, deadline - now)
            say(f"route.py: {exc}; asking again in {int(wait)}s")
            cached.sleep(wait)
