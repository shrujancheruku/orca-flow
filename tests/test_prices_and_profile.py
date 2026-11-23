import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from flowlib import agents, estimating, prices, profiler, transcripts

from .helpers import cfg


class PriceTest(unittest.TestCase):
    def test_longest_key_wins(self):
        self.assertEqual(prices.match_key("claude-opus-4-1-20250805"), "opus-4-1")
        self.assertEqual(prices.match_key("claude-opus-4-20250514"), "opus-4")
        self.assertEqual(prices.match_key("claude-sonnet-5-5"), "sonnet-5-5")
        self.assertIsNone(prices.match_key("gpt-9"))

    def test_message_cost(self):
        usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000,
                 "cache_read_input_tokens": 1_000_000, "cache_creation_input_tokens": 1_000_000}
        # sonnet-4-6: 3 + 15 + 0.30 + 3.75
        self.assertAlmostEqual(prices.message_cost("claude-sonnet-4-6", usage), 22.05)

    def test_haiku_5_5_long_tier(self):
        short = {"input_tokens": 100_000, "output_tokens": 0}
        long = {"input_tokens": 100_001, "output_tokens": 0}
        self.assertAlmostEqual(prices.message_cost("claude-haiku-5-5", short), 0.01)
        self.assertAlmostEqual(prices.message_cost("claude-haiku-5-5", long), 100_001 * 0.50 / 1e6)

    def test_unpriced_model(self):
        self.assertIsNone(prices.message_cost("mystery", {"input_tokens": 5}))


def rec(mid, model, ts, inp=1000, out=100):
    return {"timestamp": ts, "message": {"id": mid, "model": model,
                                         "usage": {"input_tokens": inp, "output_tokens": out}}}


class TranscriptTest(unittest.TestCase):
    def test_usage_counted_once_per_message(self):
        lines = [json.dumps(rec("m1", "claude-haiku-4-5", "2026-11-10T10:00:00Z"))] * 3
        lines.append(json.dumps(rec("m2", "claude-haiku-4-5", "2026-11-10T10:01:00Z")))
        s = transcripts.summarise(transcripts.read_jsonl(lines))
        self.assertEqual(s["messages"], 2)
        self.assertAlmostEqual(s["cost"], 2 * (1000 * 1 + 100 * 5) / 1e6)

    def test_encoded_project_dir(self):
        self.assertEqual(transcripts.encode_project_dir("/Users/a/code/my.app"), "-Users-a-code-my-app")


class ProfileTest(unittest.TestCase):
    def test_profile(self):
        def summ(model, cost):
            return {"cost": cost, "by_model": {model: {"cost": cost, "messages": 1}}, "contexts": []}

        workers = [
            {"dispatch_id": "d1", "task_title": "#1 · build · haiku", "started_at": "2026-11-10T10:00:00Z",
             "ended_at": "2026-11-10T11:00:00Z", "outcome": "stopped", "transcripts": [summ("claude-haiku-4-5", 1.0)]},
            {"dispatch_id": "d2", "task_title": "#1 · build · sonnet", "started_at": "2026-11-10T11:00:00Z",
             "ended_at": "2026-11-10T12:00:00Z", "outcome": "done", "transcripts": [summ("claude-sonnet-4-6", 3.0)]},
            {"dispatch_id": "d3", "task_title": "#1 · check · haiku", "started_at": "2026-11-10T12:00:00Z",
             "ended_at": "2026-11-10T12:10:00Z", "outcome": "approved", "transcripts": [summ("claude-haiku-4-5", 0.5)]},
            {"dispatch_id": "d4", "task_title": "#2 · build · sonnet", "started_at": "2026-11-10T10:00:00Z",
             "ended_at": "2026-11-10T12:00:00Z", "outcome": "done", "transcripts": [summ("claude-sonnet-4-6", 2.0)]},
            {"dispatch_id": "d5", "task_title": "#2 · check · haiku", "started_at": "2026-11-10T12:00:00Z",
             "ended_at": "2026-11-10T12:10:00Z", "outcome": "changes requested", "transcripts": [summ("claude-haiku-4-5", 0.5)]},
        ]
        p = profiler.build_profile("run1", workers, None, ["#1"], slots=2)
        self.assertEqual(p["escalations"], 1)
        self.assertAlmostEqual(p["cost_per_merged_ticket"], 4.5)
        self.assertAlmostEqual(p["review_round_one_approval"], 0.5)
        self.assertEqual(p["slots"]["peak_concurrency"], 2)
        self.assertAlmostEqual(p["by_role"]["build"], 6.0)
        self.assertIn("Merged tickets: 1", profiler.summary_body(p, "2026-11-04"))


class EstimatingTest(unittest.TestCase):
    def test_prompt_and_answer(self):
        prompt = estimating.build_prompt({"identifier": "#1", "title": "Add a field", "description": "Small."}, cfg())
        self.assertIn("#1: Add a field", prompt)
        self.assertIn("deleting a person's data", prompt)
        self.assertEqual(estimating.parse_answer('Sure: {"size": "s", "risk_kind": null, "reason": "tiny"}', cfg()),
                         {"size": "S", "risk": False, "risk_kind": None, "reason": "tiny"})
        with self.assertRaises(ValueError):
            estimating.parse_answer('{"size": "XXL"}', cfg())

    def test_risk_is_only_a_configured_kind(self):
        kind = "deleting a person's data"
        a = estimating.parse_answer('{"size": "M", "risk_kind": "Deleting a person\'s data", "reason": "r"}', cfg())
        self.assertEqual((a["risk"], a["risk_kind"]), (True, kind))
        a = estimating.parse_answer('{"size": "M", "risk_kind": "a public API", "reason": "r"}', cfg())
        self.assertEqual((a["risk"], a["risk_kind"]), (False, None))

    def test_calibration_round_trip(self):
        prompt = estimating.build_calibration_prompt(
            [{"number": 3, "title": "Scaffold", "size": "L", "reason": "big"},
             {"number": 4, "title": "Logger", "size": "L", "reason": "one module"}])
        self.assertIn("#4 [L] Logger: one module", prompt)
        out = estimating.parse_calibration(
            '{"sizes": {"3": {"size": "L", "reason": "a"}, "#4": {"size": "s", "reason": "b"},'
            ' "9": {"size": "M"}, "x": {}, "5": {"size": "XL"}}}', {3, 4, 5})
        self.assertEqual(out, {3: {"size": "L", "reason": "a"}, 4: {"size": "S", "reason": "b"}})

    def test_claude_json(self):
        self.assertEqual(agents.parse_claude_json('{"result": "hi", "is_error": false}'), "hi")

    def test_risk_hints(self):
        hints = estimating.risk_hints("Touches packages/records/src/a.ts and auth.", cfg())
        self.assertIn("path packages/records/**", hints)
        self.assertIn("word auth", hints)


if __name__ == "__main__":
    unittest.main()


class OrcaFieldsAndAttributionTest(unittest.TestCase):
    """The shapes Orca really returns, pinned on the first real run."""

    def test_worker_record_reads_the_pinned_fields(self):
        from flowlib import orca
        raw = {"dispatchId": "ctx_1", "taskId": "task_1", "state": "succeeded",
               "workspace": "repo-id::/Users/me/orca/workspaces/app/12-thing"}
        detail = {"dispatch": {"dispatchedAt": "2026-11-22 05:10:40", "completedAt": "2026-11-22T05:25:00.368Z",
                               "followUpOf": "ctx_0"},
                  "projection": {"outcome": "succeeded"}, "terminal": {"title": "worker-task_1"}}
        w = orca.worker_record(raw, detail, {"task_1": "#12 · build · sonnet"})
        self.assertEqual(w["task_title"], "#12 · build · sonnet")
        self.assertEqual(w["worktree"], "/Users/me/orca/workspaces/app/12-thing")
        self.assertEqual(w["started_at"], "2026-11-22T05:10:40+00:00")
        self.assertEqual(w["ended_at"], "2026-11-22T05:25:00.368Z")
        self.assertEqual((w["follow_up_of"], w["outcome"]), ("ctx_0", "succeeded"))

    def test_a_session_goes_to_one_chain_and_a_message_to_one_dispatch(self):
        from flowlib import transcripts
        wt = "/w/12"
        workers = [
            {"dispatch_id": "build", "worktree": wt, "started_at": "2026-11-22T01:00:00+00:00", "follow_up_of": None},
            {"dispatch_id": "check", "worktree": wt, "started_at": "2026-11-22T02:00:00+00:00", "follow_up_of": None},
            {"dispatch_id": "fixes", "worktree": wt, "started_at": "2026-11-22T03:00:00+00:00", "follow_up_of": "build"},
            {"dispatch_id": "other", "worktree": "/w/13", "started_at": "2026-11-22T01:30:00+00:00", "follow_up_of": None},
        ]
        sessions = [
            {"session": "s-build", "worktree": wt, "first_at": "2026-11-22T01:00:05+00:00"},
            {"session": "s-check", "worktree": wt, "first_at": "2026-11-22T02:00:03+00:00"},
        ]
        got = transcripts.assign(workers, sessions)
        three = transcripts.parse_ts("2026-11-22T03:00:00+00:00")
        self.assertEqual(got["build"], [("s-build", None, three)])
        self.assertEqual(got["fixes"], [("s-build", three, None)])
        self.assertEqual(got["check"], [("s-check", None, None)])
        self.assertEqual(got["other"], [])

    def test_a_window_counts_only_its_own_messages(self):
        from flowlib import transcripts
        def rec(i, at):
            return {"timestamp": at, "message": {"id": f"m{i}", "model": "claude-sonnet-4-6",
                                                 "usage": {"input_tokens": 1000000, "output_tokens": 0}}}
        records = [rec(1, "2026-11-22T01:00:00Z"), rec(2, "2026-11-22T03:00:00Z"), rec(3, "2026-11-22T04:00:00Z")]
        cut = transcripts.parse_ts("2026-11-22T03:00:00+00:00")
        before = transcripts.summarise(records, None, cut)
        after = transcripts.summarise(records, cut, None)
        self.assertEqual((before["messages"], after["messages"]), (1, 2))
        self.assertAlmostEqual(before["cost"] + after["cost"], transcripts.summarise(records)["cost"])

    def test_one_check_and_no_fixer_is_a_round_one_approval(self):
        def w(i, title, outcome="succeeded"):
            return {"dispatch_id": f"d{i}", "task_title": title, "outcome": outcome, "transcripts": []}
        p = profiler.build_profile("r", [
            w(1, "#1 · build · sonnet"), w(2, "#1 · check · haiku"),
            w(3, "#2 · build · sonnet"), w(4, "#2 · check · haiku"), w(5, "#2 · build · sonnet"), w(6, "#2 · check · haiku"),
            w(7, "#9 · review · opus"), w(8, "#9 · fix · opus"),
        ], None, ["#1", "#2"], 4)
        rows = {t["ticket"]: t for t in p["tickets"]}
        self.assertEqual([rows[k]["round_one_approved"] for k in ("#1", "#2", "#9")], [True, False, False])
        self.assertFalse(rows["#2"]["escalated"])
        self.assertAlmostEqual(p["review_round_one_approval"], 1 / 3)


class CoordinatorSessionsTest(unittest.TestCase):
    """A run can span several coordinator sessions: each transcript counts, an API message once."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def write(self, name, *recs):
        path = self.dir / name
        path.write_text("".join(json.dumps(r) + "\n" for r in recs))
        return str(path)

    def test_two_transcripts_are_summed(self):
        a = self.write("a.jsonl", rec("m1", "claude-haiku-4-5", "2026-11-10T10:00:00Z"))
        b = self.write("b.jsonl", rec("m2", "claude-haiku-4-5", "2026-11-10T11:00:00Z"),
                       rec("m3", "claude-sonnet-4-6", "2026-11-10T11:01:00Z"))
        s, missing = transcripts.summarise_files([a, b])
        self.assertEqual(missing, [])
        self.assertEqual((s["sessions"], s["messages"]), (2, 3))
        expected = transcripts.summarise_file(a)["cost"] + transcripts.summarise_file(b)["cost"]
        self.assertAlmostEqual(s["cost"], expected)
        self.assertEqual(s["by_model"]["claude-haiku-4-5"]["messages"], 2)
        self.assertEqual(s["by_model"]["claude-sonnet-4-6"]["messages"], 1)

    def test_a_message_repeated_across_two_files_is_counted_once(self):
        # a resumed session repeats the earlier messages, so m2 is in both files
        a = self.write("a.jsonl", rec("m1", "claude-haiku-4-5", "2026-11-10T10:00:00Z"),
                       rec("m2", "claude-haiku-4-5", "2026-11-10T10:01:00Z"))
        b = self.write("b.jsonl", rec("m2", "claude-haiku-4-5", "2026-11-10T10:01:00Z"),
                       rec("m3", "claude-haiku-4-5", "2026-11-10T10:02:00Z"))
        s, _ = transcripts.summarise_files([a, b])
        self.assertEqual(s["messages"], 3)
        self.assertAlmostEqual(s["cost"], 3 * (1000 * 1 + 100 * 5) / 1e6)

    def test_one_transcript_given_twice_counts_once_in_any_spelling(self):
        # no id on the message, so it is keyed by path and line: a second spelling must not count it again
        plain = {"timestamp": "2026-11-10T10:01:00Z",
                 "message": {"model": "claude-haiku-4-5", "usage": {"input_tokens": 1000, "output_tokens": 100}}}
        a = self.write("a.jsonl", rec("m1", "claude-haiku-4-5", "2026-11-10T10:00:00Z"), plain)
        (self.dir / "t").mkdir()
        other_spelling = str(self.dir / "t" / ".." / "a.jsonl")
        once, _ = transcripts.summarise_files([a])
        for paths in ([a, a], [a, other_spelling]):
            with self.subTest(paths=paths):
                s, missing = transcripts.summarise_files(paths)
                self.assertEqual(missing, [])
                self.assertEqual((s["sessions"], s["messages"]), (1, 2))
                self.assertAlmostEqual(s["cost"], once["cost"])

    def test_a_repeated_id_keeps_its_first_copy_in_one_file_as_across_files(self):
        first = rec("m1", "claude-haiku-4-5", "2026-11-10T10:00:00Z", inp=1000)
        second = rec("m1", "claude-haiku-4-5", "2026-11-10T10:00:00Z", inp=5000)
        one = transcripts.summarise(transcripts.read_jsonl([json.dumps(first), json.dumps(second)]))
        a = self.write("a.jsonl", first)
        b = self.write("b.jsonl", second)
        two, _ = transcripts.summarise_files([a, b])
        self.assertEqual(one["by_model"]["claude-haiku-4-5"]["input"], 1000)
        self.assertEqual(two["by_model"]["claude-haiku-4-5"]["input"], 1000)

    def test_naive_and_aware_timestamps_mix_as_utc(self):
        aware = self.write("aware.jsonl", rec("m1", "claude-haiku-4-5", "2026-01-01T00:01:00Z"))
        naive = self.write("naive.jsonl", rec("m2", "claude-haiku-4-5", "2026-01-01T00:02:00"))
        s, _ = transcripts.summarise_files([naive, aware])
        self.assertEqual(s["messages"], 2)
        self.assertEqual(s["first_at"], "2026-01-01T00:01:00+00:00")
        self.assertEqual(s["last_at"], "2026-01-01T00:02:00+00:00")

    def test_context_series_runs_in_time_order_across_files(self):
        late = self.write("late.jsonl", rec("m2", "claude-haiku-4-5", "2026-11-10T12:00:00Z"))
        early = self.write("early.jsonl", rec("m1", "claude-haiku-4-5", "2026-11-10T09:00:00Z"))
        s, _ = transcripts.summarise_files([late, early])
        ats = [c["at"] for c in s["contexts"]]
        self.assertEqual(ats, sorted(ats))
        self.assertEqual(len(ats), 2)

    def test_a_missing_path_or_one_without_usage_is_reported_by_name(self):
        gone = str(self.dir / "gone.jsonl")
        plain = self.write("plain.jsonl", {"timestamp": "2026-11-10T10:00:00Z", "type": "user"})
        good = self.write("good.jsonl", rec("m1", "claude-haiku-4-5", "2026-11-10T10:00:00Z"))
        s, missing = transcripts.summarise_files([gone, plain, good])
        self.assertEqual(missing, [gone, plain])
        self.assertEqual((s["sessions"], s["messages"]), (1, 1))
        s, missing = transcripts.summarise_files([gone])
        self.assertIsNone(s)
        self.assertEqual(missing, [gone])

    def test_summary_line_for_zero_one_and_several_sessions(self):
        def body(coordinator):
            return profiler.summary_body(profiler.build_profile("r", [], coordinator, [], 1), "2026-11-04")

        def coord(sessions):
            return {"cost": 12.34, "by_model": {}, "contexts": [], "sessions": sessions}

        self.assertIn("coordinator not counted.", body(None))
        self.assertIn("coordinator $12.34 over 1 session.", body(coord(1)))
        self.assertIn("coordinator $12.34 over 3 sessions.", body(coord(3)))

    def test_cli_repeated_flag_and_missing_path_error(self):
        script = Path(__file__).resolve().parent.parent / "scripts" / "profile.py"
        workers = self.dir / "workers.json"
        workers.write_text(json.dumps([{"dispatchId": "ctx_1", "taskId": "task_1", "state": "succeeded",
                                        "workspace": "repo::/no/such/worktree"}]))
        a = self.write("a.jsonl", rec("m1", "claude-haiku-4-5", "2026-11-10T10:00:00Z"))
        b = self.write("b.jsonl", rec("m2", "claude-haiku-4-5", "2026-11-10T11:00:00Z"))
        c = self.write("c.jsonl", rec("m3", "claude-haiku-4-5", "2026-11-10T12:00:00Z"))
        out = self.dir / "profile.json"
        base = [sys.executable, str(script), "--run", "r1", "--workers-json", str(workers), "--allow-missing",
                "--out", str(out)]
        done = subprocess.run(base + ["--coordinator", a, b, "--coordinator", c],
                              capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(done.returncode, 0, done.stderr)
        profile = json.loads(out.read_text())
        self.assertEqual(profile["coordinator_sessions"], 3)
        self.assertIn("over 3 sessions", done.stdout)

        gone = str(self.dir / "missing.jsonl")
        strict = [part for part in base if part != "--allow-missing"]
        failed = subprocess.run(strict + ["--coordinator", a, gone], capture_output=True, text=True)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn(gone, failed.stderr)
