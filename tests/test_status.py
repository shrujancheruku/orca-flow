import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from flowlib import github, orca, status

from .helpers import cfg

NOW = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)
RUN = "run_1"


def task(tid, title, status_="completed", created="2026-11-22 10:00:00", completed="2026-11-22 10:30:00"):
    return {"id": tid, "task_title": title, "status": status_, "created_at": created,
            "completed_at": completed if status_ == "completed" else None}


def fake_orca(workers=(), tasks=(), messages=(), gates=(), fail=(), run=RUN):
    """An orca runner answering from fixtures; a subcommand in `fail` raises like a failed CLI call."""
    answers = {"run-current": {"runId": run}, "worker-list": {"workers": list(workers)},
               "task-list": {"tasks": list(tasks)}, "inbox": {"messages": list(messages)},
               "gate-list": {"gates": list(gates)}}
    calls = []

    def run_orca(args):
        calls.append(args)
        sub = args[1]
        if sub in fail or "all" in fail:
            raise orca.OrcaError(f"orca orchestration {sub} failed: boom")
        return answers[sub]
    run_orca.calls = calls
    return run_orca


def issue(n, title, labels=(), state="OPEN", blockers=(), milestone=None):
    node = {"number": n, "title": title, "state": state, "labels": {"nodes": [{"name": l} for l in labels]}}
    if blockers is not None:
        node["blockedBy"] = {"nodes": list(blockers)}
    if milestone is not None:
        node["milestone"] = {"title": milestone} if milestone else None
    return node


def pr_node(n=50, draft=True, milestone="M1", checks=("SUCCESS",), state="OPEN", merge_state="CLEAN"):
    contexts = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": c} if c != "IN_PROGRESS"
                else {"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": None} for c in checks]
    return {"number": n, "title": "feat: m1", "state": state, "isDraft": draft, "mergeStateStatus": merge_state,
            "headRefName": "integration/m1",
            "milestone": {"title": milestone},
            "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "SUCCESS", "contexts": {"nodes": contexts}}}}]}}


def fake_gh(milestone_issues=(), owner=(), prs=(), refs=None, fail=False):
    """A gh runner for the footer's GraphQL reads; it answers each part the query asks for."""
    queries = []

    def run_gh(args, stdin=None):
        assert args[:2] == ["api", "graphql"], args
        if fail:
            raise github.GitHubError("gh api failed: HTTP 502")
        q = args[3][len("query="):]
        queries.append(q)
        data = {}
        if "owner: search" in q:
            data["owner"] = {"issueCount": len(owner), "nodes": list(owner)}
        if "repository(" in q:
            repo = {"prs": {"nodes": list(prs)}}
            for n, state in (refs or {}).items():
                if f"r{n}:" in q:
                    repo[f"r{n}"] = {"state": state}
            data["repository"] = repo
        if "milestone: search" in q:
            data["milestone"] = {"issueCount": len(milestone_issues), "nodes": list(milestone_issues)}
        return json.dumps({"data": data})
    run_gh.queries = queries
    return run_gh


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.asks = Path(self.tmp) / "flow" / "asks.jsonl"

    def build(self, orca_runner=None, gh_runner=None, config=None, **kw):
        c = cfg() if config is None else config
        gh = github.Gh("acme/app", runner=gh_runner) if gh_runner else None
        return status.build(cfg=c, asks_file=self.asks, orca_runner=orca_runner or fake_orca(), gh=gh, now=NOW, **kw)

    def plain(self, data):
        return status.render(data, "plain")


class SanitiseTest(unittest.TestCase):
    def test_control_characters_bidi_and_fences_are_stripped(self):
        self.assertEqual(status.clean("a\x1b[31mred\x07\x9b b\u202e c"), "a[31mred b c")
        self.assertEqual(status.clean("x ``` y ```` z"), "x ''' y '''' z")
        self.assertEqual(status.clean("one\ntwo\tthree"), "one two three")

    def test_titles_are_cut(self):
        self.assertEqual(len(status.cut("x" * 200)), status.TITLE_MAX)
        self.assertTrue(status.cut("x" * 200).endswith("…"))

    def test_every_printed_line_is_clean(self):
        gh = fake_gh(owner=[issue(7, "evil \x1b]0;pwn\x07 ```title", ["ready-for-human"], milestone="M1")],
                     milestone_issues=[issue(7, "t", ["ready-for-human"])])
        tmp = tempfile.mkdtemp()
        asks = Path(tmp) / "a.jsonl"
        status.add_ask(asks, "asked \x1b[2J ```now```")
        data = status.build(cfg=cfg(), asks_file=asks, orca_runner=fake_orca(), gh=github.Gh("acme/app", runner=gh),
                            milestone="M1", now=NOW)
        out = "\n".join(status.render(data, "plain"))
        self.assertNotIn("\x1b", out)
        self.assertNotIn("\x07", out)
        self.assertNotIn("```", out)


class InProgressTest(Base):
    def test_live_workers_with_flags(self):
        tasks = [task(f"done{i}", "#1 · build · sonnet", created="2026-11-22 08:00:00",
                      completed="2026-11-22 08:20:00") for i in range(3)]  # build's median: 20m
        tasks += [task("t2", "#2 · build · sonnet", "dispatched", created="2026-11-22 10:00:00"),  # 2h: slow
                  task("t3", "#3 · check · haiku", "dispatched", created="2026-11-22 11:50:00"),
                  task("t4", "#4 · merge · haiku", "dispatched", created="2026-11-22 11:00:00"),
                  task("t5", "#5 · fix · opus", "dispatched", created="2026-11-22 08:00:00")]  # 4h, no median
        workers = [{"dispatchId": "d2", "taskId": "t2", "state": "running", "liveness": "live"},
                   {"dispatchId": "d3", "taskId": "t3", "state": "ready", "liveness": "unverifiable",
                    "attention": ["unverifiable"]},
                   {"dispatchId": "d4", "taskId": "t4", "state": "ready", "liveness": "exited"},
                   {"dispatchId": "d5", "taskId": "t5", "state": "ready", "liveness": "live"},
                   {"dispatchId": "dx", "taskId": "done0", "state": "succeeded", "liveness": "exited"}]
        rows = {r["ticket"]: r for r in status.in_progress(workers, tasks, NOW, 3, 120)}
        self.assertEqual(set(rows), {"#2", "#3", "#4", "#5"})
        self.assertEqual(rows["#2"]["flags"], ["slow (typical 20m)"])
        self.assertEqual(rows["#3"]["flags"], ["no heartbeat"])
        self.assertEqual(rows["#4"]["flags"], ["exited without reporting"])
        self.assertEqual(rows["#5"]["flags"], ["slow (over 2h00m)"])
        self.assertEqual(status.worker_line(rows["#2"]), "#2 build sonnet 2h00m ! slow (typical 20m)")
        self.assertEqual(status.worker_line(rows["#3"]), "#3 check haiku 10m ! no heartbeat")

    def test_threshold_is_configurable(self):
        tasks = [task("t", "#9 · fix · opus", "dispatched", created="2026-11-22 11:00:00")]
        workers = [{"dispatchId": "d", "taskId": "t", "state": "running", "liveness": "live"}]
        self.assertEqual(status.in_progress(workers, tasks, NOW, 3, 120)[0]["flags"], [])
        self.assertEqual(status.in_progress(workers, tasks, NOW, 3, 30)[0]["flags"], ["slow (over 30m)"])
        data = self.build(fake_orca(workers, tasks), config=cfg(status={"slow_minutes": 45}))
        self.assertEqual(data["in_progress"][0]["flags"], ["slow (over 45m)"])

    def test_tally_counts_live_tickets_as_in_progress(self):
        issues = [issue(1, "a", ["ready-for-agent", "integrated"]),
                  issue(2, "b", state="CLOSED"),
                  issue(3, "c", ["ready-for-agent"], blockers=[issue(1, "a", ["integrated"], blockers=None)]),
                  issue(4, "d", ["ready-for-agent"], blockers=[issue(5, "e", ["ready-for-agent"], blockers=None)]),
                  issue(5, "e", ["ready-for-agent"]),
                  issue(6, "f", ["ready-for-human"]),
                  issue(7, "g", ["needs-info"])]
        tasks = [task("t5", "#5 · build · haiku", "dispatched", created="2026-11-22 11:50:00")]
        workers = [{"dispatchId": "d", "taskId": "t5", "state": "running", "liveness": "live"}]
        data = self.build(fake_orca(workers, tasks), fake_gh(milestone_issues=issues), milestone="M1")
        self.assertEqual(data["tally"], {"total": 7, "integrated": 2, "in_progress": 1, "ready_next": 1,
                                         "blocked": 1, "waiting_on_you": 2, "other": 0})
        self.assertIn("M1: 2/7 integrated, 1 in progress, 1 ready next, 1 blocked, 2 waiting on you",
                      self.plain(data))

    def test_a_worker_on_the_integration_pr_shows_beside_the_tally(self):
        tasks = [task("t50", "#50 · fix · opus", "dispatched", created="2026-11-22 11:50:00")]
        workers = [{"dispatchId": "d", "taskId": "t50", "state": "running", "liveness": "live"}]
        data = self.build(fake_orca(workers, tasks), fake_gh(milestone_issues=[issue(1, "a", ["integrated"])]),
                          milestone="M1")
        self.assertEqual(data["tally"]["in_progress"], 0)
        self.assertIn("M1: 1/1 integrated, 0 in progress, 0 ready next, 0 blocked, 0 waiting on you; "
                      "1 worker on the integration PR or outside the tickets", self.plain(data))


class WaitingTest(Base):
    def test_nothing(self):
        data = self.build(gh_runner=fake_gh(), milestone="M1")
        self.assertEqual(self.plain(data), ["In progress: nothing", "M1: 0/0 integrated, 0 in progress, 0 ready next, "
                                            "0 blocked, 0 waiting on you", "Waiting on you: nothing"])

    def test_sections_in_order_and_empty_ones_left_out(self):
        owner = [issue(9, "outside", ["ready-for-human"], milestone="M0"),
                 issue(8, "inside", ["ready-for-human"], milestone="M1"),
                 issue(7, "question", ["needs-info"], milestone="M1")]
        messages = [{"id": "m1", "type": "question", "to": f"run:{RUN}", "handled": False, "subject": "",
                     "body": "Which ref?\nmore", "payload": {"taskId": "t1"}},
                    {"id": "m2", "type": "question", "to": f"run:{RUN}", "handled": True, "body": "old"},
                    {"id": "m3", "type": "worker_done", "to": f"run:{RUN}", "handled": False, "subject": "done"}]
        tasks = [task("t1", "#3 · build · sonnet", "dispatched")]
        ask = status.add_ask(self.asks, "Pick a seed", ticket="#4", where="issue #4")
        data = self.build(fake_orca(tasks=tasks, messages=messages),
                          fake_gh(owner=owner, prs=[pr_node(draft=False)]), milestone="M1")
        self.assertEqual([s["section"] for s in data["waiting"]],
                         ["human", "human-outside", "needs-info", "asks", "worker-questions", "pr"])
        out = self.plain(data)
        heads = [l for l in out if not l.startswith(" ")]
        self.assertEqual(heads[heads.index("Waiting on you"):], [
            "Waiting on you", "\U0001f7e5 Ready for you (1)", "\U0001f7e7 Ready for you, outside the milestone (1)",
            "\U0001f7e8 Needs info (1)", "\U0001f7e6 Coordinator asks (1)",
            "\U0001f7ea Worker questions not yet handled (1)", "\U0001f7e9 Integration PR"])
        self.assertIn("  #9 outside (M0)", out)
        self.assertIn("  #3 build: question: Which ref?", out)

        status.done_ask(self.asks, ask)
        data = self.build(gh_runner=fake_gh(owner=owner[2:]), milestone="M1")
        self.assertEqual([s["section"] for s in data["waiting"]], ["needs-info"])

    def test_without_a_milestone_every_ready_for_human_ticket_is_one_section(self):
        owner = [issue(9, "a", ["ready-for-human"], milestone="M0"), issue(8, "b", ["ready-for-human"], milestone="")]
        data = self.build(gh_runner=fake_gh(owner=owner))
        self.assertEqual([(s["section"], s["count"]) for s in data["waiting"]], [("human", 2)])

    def test_long_sections_are_capped(self):
        owner = [issue(n, f"t{n}", ["needs-info"], milestone="M1") for n in range(1, 21)]
        section = self.build(gh_runner=fake_gh(owner=owner), milestone="M1")["waiting"][0]
        self.assertEqual(section["count"], 20)
        self.assertEqual(len(section["items"]), status.LIST_MAX + 1)
        self.assertEqual(section["items"][-1], "+5 more")


class AsksTest(Base):
    def test_add_done_and_the_file_is_private(self):
        a = status.add_ask(self.asks, "  Merge   now? ", where="PR #50")
        b = status.add_ask(self.asks, "Seed?", ticket="12")
        self.assertEqual([e["text"] for e in status.live_asks(self.asks)], ["Merge now?", "Seed?"])
        self.assertEqual(os.stat(self.asks).st_mode & 0o777, 0o600)
        self.assertTrue(status.done_ask(self.asks, a))
        self.assertFalse(status.done_ask(self.asks, a))
        self.assertEqual([e["id"] for e in status.live_asks(self.asks)], [b])
        self.assertEqual(status.ask_line(status.live_asks(self.asks)[0]), f"[{b}] Seed? (#12)")

    def test_an_ask_whose_ticket_closed_is_dropped_and_cleared(self):
        status.add_ask(self.asks, "about a closed issue", ticket=4)
        status.add_ask(self.asks, "about a merged PR", ticket=5)
        keep = status.add_ask(self.asks, "still open", ticket=6)
        bare = status.add_ask(self.asks, "no ticket")
        gh = fake_gh(refs={4: "CLOSED", 5: "MERGED", 6: "OPEN"})
        data = self.build(gh_runner=gh)
        self.assertEqual(data["waiting"][0]["items"], [f"[{keep}] still open (#6)", f"[{bare}] no ticket"])
        self.assertEqual({e["id"] for e in status.live_asks(self.asks)}, {keep, bare})
        self.assertIn("r4: issueOrPullRequest(number: 4)", gh.queries[0])

    def test_asks_stay_when_github_is_down(self):
        status.add_ask(self.asks, "keep me", ticket=4)
        data = self.build(gh_runner=fake_gh(fail=True))
        self.assertEqual(len(status.live_asks(self.asks)), 1)
        self.assertEqual(data["waiting"][0]["section"], "asks")

    def test_the_file_is_in_the_git_common_dir(self):
        import subprocess
        repo = os.path.join(self.tmp, "repo")
        subprocess.run(["git", "init", "-q", repo], check=True)
        env = os.environ.pop("FLOW_ASKS_FILE", None)
        try:
            path = status.asks_path(repo)
        finally:
            if env is not None:
                os.environ["FLOW_ASKS_FILE"] = env
        self.assertEqual(path, Path(os.path.realpath(repo)) / ".git" / "flow" / "asks.jsonl")


class PrTest(Base):
    def test_a_draft_pr_is_not_ready_until_every_ticket_is_integrated(self):
        gh = fake_gh(prs=[pr_node(draft=True)], milestone_issues=[issue(1, "a", ["integrated"]), issue(2, "b")])
        self.assertEqual(self.build(gh_runner=gh)["waiting"], [])
        gh = fake_gh(prs=[pr_node(draft=True, checks=("SUCCESS", "FAILURE", "IN_PROGRESS", "SKIPPED"))],
                     milestone_issues=[issue(1, "a", ["integrated"]), issue(2, "b", state="CLOSED")])
        data = self.build(gh_runner=gh)
        self.assertEqual(data["milestone"], "M1")  # taken from the PR, with a second read for its issues
        self.assertEqual(len(gh.queries), 2)
        self.assertEqual(data["waiting"][-1]["items"], [
            "PR #50 not ready to merge yet: 1 red, 1 pending (every milestone ticket integrated, still draft): "
            "checks 2 green, 1 red, 1 pending"])

    def test_out_of_draft_is_ready(self):
        data = self.build(gh_runner=fake_gh(prs=[pr_node(draft=False)]), milestone="M1")
        self.assertEqual(data["waiting"][-1]["items"],
                         ["PR #50 ready for you to merge (no longer draft): checks 1 green, 0 red, 0 pending"])

    def test_a_pr_behind_its_base_is_not_ready(self):
        data = self.build(gh_runner=fake_gh(prs=[pr_node(draft=False, merge_state="BEHIND")]), milestone="M1")
        self.assertEqual(data["waiting"][-1]["items"], [
            "PR #50 not ready to merge yet: behind its base (no longer draft): checks 1 green, 0 red, 0 pending"])

    def test_only_integration_branches_in_the_milestone_count(self):
        other = dict(pr_node(51, draft=False), headRefName="renovate/x")
        elsewhere = pr_node(52, draft=False, milestone="M0")
        data = self.build(gh_runner=fake_gh(prs=[other, elsewhere]), milestone="M1")
        self.assertEqual(data["waiting"], [])

    def test_two_integration_prs_without_a_milestone_are_named(self):
        data = self.build(gh_runner=fake_gh(prs=[pr_node(50), pr_node(52, milestone="M0")]))
        self.assertIn("integration PR (2 open: #50, #52; pass --pr)", data["unavailable"])


class DegradeTest(Base):
    def test_orca_down_still_prints_github(self):
        data = self.build(fake_orca(fail=("all",)), fake_gh(owner=[issue(8, "x", ["ready-for-human"], milestone="M1")]),
                          milestone="M1")
        out = self.plain(data)
        self.assertNotIn("In progress: nothing", out)
        self.assertIn("  #8 x", out)
        self.assertTrue(out[-1].startswith("Unavailable: orca run (orca orchestration run-current failed"))

    def test_one_orca_read_failing_keeps_the_others(self):
        tasks = [task("t", "#2 · build · sonnet", "dispatched", created="2026-11-22 11:00:00")]
        workers = [{"dispatchId": "d", "taskId": "t", "state": "running", "liveness": "live"}]
        data = self.build(fake_orca(workers, tasks, fail=("inbox",)), run_id=RUN)
        self.assertEqual(len(data["in_progress"]), 1)
        self.assertTrue(any(u.startswith("orca messages") for u in data["unavailable"]))

    def test_no_run(self):
        data = self.build(fake_orca(run=None), fake_gh())
        self.assertIn("orca run (no current run; pass --run)", data["unavailable"])

    def test_github_down_says_so_and_does_not_claim_nothing(self):
        out = self.plain(self.build(gh_runner=fake_gh(fail=True)))
        self.assertIn("Waiting on you: nothing that could be read", out)
        self.assertIn("GitHub (gh api failed: HTTP 502)", out[-1])

    def test_no_config_and_linear(self):
        data = status.build(cfg=None, asks_file=self.asks, orca_runner=fake_orca(), now=NOW)
        self.assertIn("no docs/agents/flow.json", data["unavailable"][0])
        data = self.build(config=cfg(tracker="linear"))
        self.assertIn("tracker is linear", data["unavailable"][0])

    def test_few_calls(self):
        runner = fake_orca()
        gh = fake_gh(prs=[pr_node()])
        self.build(runner, gh)
        self.assertEqual([c[1] for c in runner.calls], ["run-current", "worker-list", "task-list", "inbox", "gate-list"])
        self.assertEqual(len(gh.queries), 2)


class RenderTest(Base):
    def test_tty_has_colour_and_plain_has_none(self):
        status.add_ask(self.asks, "x")
        data = self.build()
        self.assertTrue(any("\033[" in l for l in status.render(data, "tty")))
        self.assertFalse(any("\033[" in l for l in status.render(data, "plain")))


if __name__ == "__main__":
    unittest.main()
