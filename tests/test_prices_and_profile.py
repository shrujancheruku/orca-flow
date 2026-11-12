import json
import unittest

from flowlib import estimating, prices, profiler, transcripts

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
        self.assertIn("packages/records/**", prompt)
        self.assertEqual(estimating.parse_answer('Sure: {"size": "s", "risk": false, "reason": "tiny"}'),
                         {"size": "S", "risk": False, "reason": "tiny"})
        with self.assertRaises(ValueError):
            estimating.parse_answer('{"size": "XXL"}')

    def test_claude_json(self):
        self.assertEqual(estimating.parse_claude_json('{"result": "hi", "is_error": false}'), "hi")

    def test_risk_hints(self):
        hints = estimating.risk_hints("Touches packages/records/src/a.ts and auth.", cfg())
        self.assertIn("path packages/records/**", hints)
        self.assertIn("word auth", hints)


if __name__ == "__main__":
    unittest.main()
