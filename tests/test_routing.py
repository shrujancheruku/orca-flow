import os
import unittest

from flowlib import routing

DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "orchestration.md")


class RoutingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(DOC) as fh:
            cls.table = routing.parse_table(fh.read())

    def pick(self, role, **kw):
        c = routing.select(self.table, role, **kw)
        return c["model"], c["effort"]

    def test_seeded_table(self):
        self.assertEqual(self.pick("coordinator"), ("opus", "medium"))
        self.assertEqual(self.pick("scout"), ("haiku", "low"))
        self.assertEqual(self.pick("build", size="S"), ("haiku", None))
        self.assertEqual(self.pick("build", size="M"), ("sonnet", "medium"))
        self.assertEqual(self.pick("build", size="L"), ("sonnet", "high"))
        self.assertEqual(self.pick("build", size="L", risk=True), ("opus", None))
        self.assertEqual(self.pick("merge"), ("haiku", "low"))
        self.assertEqual(self.pick("merge", variant="conflict")[0], "sonnet")
        self.assertEqual(self.pick("check"), ("haiku", "low"))
        self.assertEqual(self.pick("review"), ("sonnet", "high"))
        self.assertEqual(self.pick("review", risk=True)[0], "opus")
        self.assertEqual(self.pick("fix"), ("sonnet", "medium"))
        self.assertEqual(self.pick("build", variant="escalated")[0], "sonnet")

    def test_small_risky_ticket_is_not_haiku(self):
        self.assertNotEqual(self.pick("build", size="S", risk=True)[0], "haiku")

    def test_flags_always_name_the_model(self):
        c = routing.select(self.table, "build", size="S")
        self.assertEqual(routing.worker_flags(c, {"haiku": "haiku"}), ["--model", "haiku"])
        c = routing.select(self.table, "build", size="M")
        self.assertEqual(routing.worker_flags(c, {"sonnet": "claude-sonnet-x"}),
                         ["--model", "claude-sonnet-x", "--effort", "medium"])

    def test_task_title_round_trip(self):
        c = routing.select(self.table, "build", size="S")
        title = routing.task_title("ABC-123", "build", c)
        self.assertEqual(title, "ABC-123 · build · haiku")
        self.assertEqual(routing.parse_task_title(title), {"ticket": "ABC-123", "role": "build", "model": "haiku"})

    def test_bad_inputs(self):
        with self.assertRaises(routing.RoutingError):
            routing.select(self.table, "painter")
        with self.assertRaises(routing.RoutingError):
            routing.select(self.table, "build", size="XL")
        with self.assertRaises(routing.RoutingError):
            routing.parse_table("# nothing here")

    def test_most_specific_row_wins(self):
        table = routing.parse_table(
            "## Model routing\n\n| Key | Model | Effort |\n|---|---|---|\n| build | sonnet | medium |\n| build.S | haiku | |\n"
        )
        self.assertEqual(routing.select(table, "build", size="S")["model"], "haiku")
        self.assertEqual(routing.select(table, "build", size="L", risk=True)["model"], "sonnet")


if __name__ == "__main__":
    unittest.main()
