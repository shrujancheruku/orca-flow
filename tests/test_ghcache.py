import calendar
import json
import tempfile
import time
import unittest
from pathlib import Path

from flowlib import ghcache, github, status

QUERY = ["api", "graphql", "-f", "query=q"]
REPO = "acme/app"


def stamp(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


class FakeGh:
    """A gh client: read_json counts calls, raises queued errors first, else answers from `answer(args, n)`."""

    def __init__(self, errors=(), answer=None):
        self.calls, self.args, self.errors = 0, [], list(errors)
        self.answer = answer or (lambda args, n: {"n": n})

    def read_json(self, args):
        self.calls += 1
        self.args.append(args)
        if self.errors:
            raise github.GitHubError(self.errors.pop(0))
        return self.answer(args, self.calls)


class Clock:
    def __init__(self, now=1_800_000_000.0):
        self.now = now
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.slept.append(s)
        self.now += s


def rated(remaining, limit=5000, reset_in=1800, now=1_800_000_000.0):
    return lambda args, n: {"data": {"n": n, "rateLimit": {"cost": 23, "remaining": remaining, "limit": limit,
                                                          "resetAt": stamp(now + reset_in)}}}


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "flow" / "github-cache.json"
        self.clock = Clock()

    def cached(self, gh, **kw):
        return ghcache.CachedGitHub(gh, self.path, clock=self.clock, sleep=self.clock.sleep, **kw)


class Pacing(Base):
    def test_reads_github_at_most_once_a_minute(self):
        gh = FakeGh()
        c = self.cached(gh)
        for _ in range(12):  # one minute of 5-second console frames
            self.assertEqual(c.read_json(QUERY), {"n": 1})
            self.clock.now += 5
        self.assertEqual(gh.calls, 1)
        self.clock.now += 1
        self.assertEqual(c.read_json(QUERY), {"n": 2})

    def test_each_query_is_cached_on_its_own(self):
        gh = FakeGh()
        c = self.cached(gh)
        c.read_json(QUERY)
        c.read_json(["api", "graphql", "-f", "query=other"])
        self.assertEqual(gh.calls, 2)

    def test_the_console_status_and_route_share_one_file(self):
        console_gh, footer_gh = FakeGh(), FakeGh()
        self.cached(console_gh).read_json(QUERY)
        self.clock.now += 30
        self.assertEqual(self.cached(footer_gh).read_json(QUERY), {"n": 1})
        self.assertEqual(footer_gh.calls, 0)

    def test_an_unreadable_cache_file_is_ignored(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json")
        self.assertEqual(self.cached(FakeGh()).read_json(QUERY), {"n": 1})
        self.assertIn("reads", json.loads(self.path.read_text()))

    def test_an_error_that_is_no_rate_limit_does_not_pause(self):
        gh = FakeGh(["gh api failed: timed out"])
        c = self.cached(gh)
        with self.assertRaises(github.GitHubError):
            c.read_json(QUERY)
        self.assertEqual(c.notice(), "")
        self.assertEqual(c.read_json(QUERY), {"n": 2})


class RateLimit(Base):
    def test_below_a_fifth_left_answers_are_kept_five_times_as_long(self):
        gh = FakeGh(answer=rated(900, now=self.clock.now))
        c = self.cached(gh)
        c.read_json(QUERY)
        self.clock.now += 61
        c.read_json(QUERY)
        self.assertEqual(gh.calls, 1)
        self.assertIn("GitHub slowed (900 of 5000", c.notice())
        self.clock.now += 240
        c.read_json(QUERY)
        self.assertEqual(gh.calls, 2)

    def test_below_a_twentieth_left_github_pauses_until_the_reset(self):
        start = self.clock.now
        gh = FakeGh(answer=rated(200, reset_in=1200, now=start))
        c = self.cached(gh)
        c.read_json(QUERY)
        until = start + 1200
        self.assertEqual(c.paused_until(), until)
        self.assertIn("GitHub paused until " + time.strftime("%H:%M", time.localtime(until)), c.notice())
        with self.assertRaises(ghcache.Paused):
            c.read_json(["api", "graphql", "-f", "query=new"])
        self.clock.now += 1199
        self.assertEqual(c.read_json(QUERY)["data"]["n"], 1)  # the last answer, stale
        self.assertEqual(gh.calls, 1)
        self.clock.now += 2
        gh.answer = rated(5000, now=self.clock.now)
        c.read_json(QUERY)
        self.assertEqual(gh.calls, 2)
        self.assertEqual(c.notice(), "")

    def test_a_rate_limit_error_pauses_until_the_last_known_reset(self):
        gh = FakeGh(answer=rated(3000, reset_in=900, now=self.clock.now))
        c = self.cached(gh)
        c.read_json(QUERY)
        reset = self.clock.now + 900
        self.clock.now += 61
        gh.errors.append("gh api failed: API rate limit already exceeded for user ID 1.")
        self.assertEqual(c.read_json(QUERY)["data"]["n"], 1)
        self.assertEqual(c.paused_until(), reset)

    def test_a_rate_limit_error_with_no_reset_known_pauses_ten_minutes(self):
        c = self.cached(FakeGh(["API rate limit already exceeded"]))
        with self.assertRaises(github.GitHubError):
            c.read_json(QUERY)
        self.assertEqual(c.paused_until(), self.clock.now + ghcache.PRIMARY_PAUSE)
        self.clock.now += 300
        with self.assertRaisesRegex(ghcache.Paused, "GitHub paused until"):
            c.read_json(QUERY)

    def test_reset_at_is_read_as_utc(self):
        self.assertEqual(ghcache.parse_time("2026-11-24T09:45:00Z"),
                         calendar.timegm((2026, 11, 24, 9, 45, 0, 0, 0, 0)))
        self.assertEqual(ghcache.parse_time(None), 0.0)


class Secondary(Base):
    MSG = "gh api failed: You have exceeded a secondary rate limit. Please wait a few minutes."

    def test_is_retried_with_backoff(self):
        gh = FakeGh([self.MSG, self.MSG])
        c = self.cached(gh)
        self.assertEqual(c.read_json(QUERY), {"n": 3})
        self.assertEqual(self.clock.slept, [5, 10])

    def test_honours_retry_after(self):
        gh = FakeGh([self.MSG + " Retry-After: 12"])
        self.cached(gh).read_json(QUERY)
        self.assertEqual(self.clock.slept, [12])

    def test_a_long_retry_after_pauses_instead_of_blocking(self):
        gh = FakeGh([self.MSG + " Retry-After: 120"])
        c = self.cached(gh, max_sleep=30)
        with self.assertRaises(github.GitHubError):
            c.read_json(QUERY)
        self.assertEqual(self.clock.slept, [])
        self.assertEqual(c.paused_until(), self.clock.now + 120)

    def test_out_of_retries_pauses_a_minute(self):
        c = self.cached(FakeGh([self.MSG] * 3))
        with self.assertRaises(github.GitHubError):
            c.read_json(QUERY)
        self.assertEqual(c.paused_until(), self.clock.now + ghcache.SECONDARY_PAUSE)
        self.assertIn("secondary rate limit", c.notice())


class FooterQueries(unittest.TestCase):
    def test_every_footer_query_asks_for_the_rate_limit(self):
        gh = FakeGh(answer=lambda args, n: {"data": {}})
        status.graphql(gh, "query { a { b } }")
        self.assertTrue(gh.args[0][-1].endswith("rateLimit { cost remaining limit resetAt } }"))

    def test_the_footer_names_the_pause_once(self):
        class Paused:
            def read_json(self, args):
                raise ghcache.Paused("GitHub paused until 09:45 (rate limit; showing its last answer)")

            def notice(self):
                return "GitHub paused until 09:45 (rate limit; showing its last answer)"
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data = status.build(cfg={"tracker": "github", "github_repo": REPO}, run_id=None, milestone="M",
                            asks_file=Path(tmp.name) / "asks.jsonl", orca_runner=lambda a: {}, gh=Paused())
        self.assertEqual([u for u in data["unavailable"] if "GitHub" in u],
                         ["GitHub paused until 09:45 (rate limit; showing its last answer)"])


def issue_answer(labels, body="b"):
    return {"data": {"repository": {"t": {"number": 7, "body": body, "labels": {"nodes": [{"name": l} for l in labels]}}},
                     "rateLimit": {"cost": 1, "remaining": 4000, "limit": 5000, "resetAt": "2030-01-01T00:00:00Z"}}}


class RouteLookup(Base):
    def test_graphql_first(self):
        gh = FakeGh(answer=lambda args, n: issue_answer(["size:S"]))
        facts, source = ghcache.issue_facts(self.cached(gh), REPO, 7)
        self.assertEqual((facts, source), ({"labels": ["size:S"], "body": "b"}, "github"))
        self.assertIn("rateLimit", gh.args[0][-1])

    def test_rest_when_graphql_is_rate_limited(self):
        def answer(args, n):
            return {"labels": [{"name": "size:L"}, {"name": "risk"}], "body": "rest body"}
        gh = FakeGh(["API rate limit already exceeded"], answer=answer)
        facts, source = ghcache.issue_facts(self.cached(gh), REPO, 7)
        self.assertEqual(source, "rest")
        self.assertEqual(facts["labels"], ["size:L", "risk"])
        self.assertEqual(gh.args[1], ["api", "repos/acme/app/issues/7"])

    def test_rest_even_while_paused(self):
        gh = FakeGh(answer=lambda args, n: {"labels": [], "body": None})
        c = self.cached(gh)
        data = c.store.load()
        data["rate"]["paused_until"] = self.clock.now + 600
        c.store.save(data, self.clock.now)
        _, source = ghcache.issue_facts(c, REPO, 7)
        self.assertEqual(source, "rest")
        self.assertEqual(gh.calls, 1)  # GraphQL was not asked

    def test_a_stale_answer_when_rest_fails_too(self):
        gh = FakeGh(answer=lambda args, n: issue_answer(["size:M"]))
        c = self.cached(gh)
        ghcache.issue_facts(c, REPO, 7)
        self.clock.now += 3600
        gh.errors += ["gh api failed: HTTP 502", "gh api failed: HTTP 503"]
        facts, source = ghcache.issue_facts(c, REPO, 7)
        self.assertEqual((facts["labels"], source), (["size:M"], "cache (stale)"))

    def test_nothing_at_all_raises_no_github(self):
        gh = FakeGh(["API rate limit already exceeded", "gh api failed: HTTP 503"])
        with self.assertRaisesRegex(ghcache.NoGitHub, "could not read #7"):
            ghcache.issue_facts(self.cached(gh), REPO, 7)

    def test_wait_blocks_until_it_can_route(self):
        gh = FakeGh(["API rate limit already exceeded", "HTTP 503", "HTTP 503"],
                    answer=lambda args, n: issue_answer(["size:S"]))
        said = []
        c = self.cached(gh)
        facts, source = ghcache.wait_for_issue(c, REPO, 7, max_wait=3600, say=said.append)
        self.assertEqual((facts["labels"], source), (["size:S"], "github"))
        self.assertEqual(len(said), 2)
        self.assertEqual(self.clock.slept, [300, 300])  # the pause is 600s; it waits at most max_poll at a time
        self.assertEqual(gh.calls, 4)  # GraphQL was not asked while paused; REST was

    def test_wait_gives_up_after_max_wait(self):
        gh = FakeGh(["HTTP 503"] * 100)
        c = self.cached(gh)
        with self.assertRaises(ghcache.NoGitHub):
            ghcache.wait_for_issue(c, REPO, 7, max_wait=150, say=lambda m: None, poll=60)
        self.assertEqual(self.clock.slept, [60, 60, 30])


if __name__ == "__main__":
    unittest.main()
