import os
import unittest

from flowlib import routing

from . import helpers

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

    def test_the_whole_table_is_pinned(self):
        """The routing table is the policy. Changing a row means changing this test on purpose."""
        got = {k: (v["model"], v["effort"]) for k, v in self.table.items()}
        self.assertEqual(got, {
            "coordinator": ("opus", "medium"), "scout": ("haiku", "low"),
            "build.s": ("haiku", None), "build.s.risk": ("sonnet", "medium"),
            "build.m": ("sonnet", "medium"), "build.m.risk": ("sonnet", "high"),
            "build.l": ("sonnet", "high"), "build.l.risk": ("opus", None),
            "build.escalated": ("sonnet", "medium"),
            "merge": ("haiku", "low"), "merge.conflict": ("sonnet", "medium"),
            "check": ("haiku", "low"), "review": ("sonnet", "high"), "review.risk": ("opus", None),
            "fix": ("sonnet", "medium"),
        })

    def test_size_label_and_risk_pick_the_row(self):
        c = helpers.cfg()
        f = routing.ticket_facts(c, ["size:L", "ready-for-agent"])
        self.assertEqual((f["size"], f["risk"]), ("L", False))
        f = routing.ticket_facts(c, ["size:L", "risk"])
        self.assertEqual(routing.select(self.table, "build", size=f["size"], risk=f["risk"])["model"], "opus")
        f = routing.ticket_facts(c, ["size:S"], paths=["packages/records/src/a.ts"])
        self.assertTrue(f["risk"])
        self.assertIn("path packages/records/**", f["risk_reasons"])
        f = routing.ticket_facts(c, ["size:S"], body="Add db/migrations/004_x.sql")
        self.assertTrue(f["risk"])
        self.assertEqual(routing.ticket_facts(c, [])["size"], None)
        self.assertEqual(routing.ticket_facts(c, ["size:S", "size:M"])["size"], "M")

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
        title = routing.task_title("123", "build", c)
        self.assertEqual(title, "#123 · build · haiku")
        self.assertEqual(routing.task_title("#123", "build", c), title)
        self.assertEqual(routing.parse_task_title(title), {"ticket": "#123", "role": "build", "model": "haiku"})
        # a bare milestone name and the Linear adapter's ids still parse
        self.assertEqual(routing.parse_task_title("ABC-7 · check · haiku")["ticket"], "ABC-7")
        self.assertIsNone(routing.parse_task_title("just a title"))

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
