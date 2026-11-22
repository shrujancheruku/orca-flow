import unittest

from flowlib import routing

from . import helpers

class RoutingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = routing.effective()

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
        self.assertEqual(self.pick("review"), ("opus", None))
        self.assertEqual(self.pick("review", risk=True)[0], "opus")
        self.assertEqual(self.pick("fix"), ("opus", None))
        self.assertEqual(self.pick("build", variant="escalated")[0], "sonnet")

    def test_the_whole_table_is_pinned(self):
        """The defaults are the policy. Changing a row means changing this test on purpose,
        and adding the old value to PAST_DEFAULTS so hand-kept tables follow."""
        got = {k: (v["model"], v["effort"]) for k, v in self.table.items()}
        self.assertEqual(got, {
            "coordinator": ("opus", "medium"), "scout": ("haiku", "low"),
            "build.s": ("haiku", None), "build.s.risk": ("sonnet", "medium"),
            "build.m": ("sonnet", "medium"), "build.m.risk": ("sonnet", "high"),
            "build.l": ("sonnet", "high"), "build.l.risk": ("opus", None),
            "build.escalated": ("sonnet", "medium"),
            "merge": ("haiku", "low"), "merge.conflict": ("sonnet", "medium"),
            "check": ("haiku", "low"), "review": ("opus", None), "review.risk": ("opus", None),
            "fix": ("opus", None),
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
        self.assertEqual(routing.worker_flags(c, {"haiku": "haiku"}), ["--agent", "claude", "--model", "haiku"])
        c = routing.select(self.table, "build", size="M")
        self.assertEqual(routing.worker_flags(c, {"sonnet": "claude-sonnet-x"}),
                         ["--agent", "claude", "--model", "claude-sonnet-x", "--effort", "medium"])

    def test_a_profile_can_name_another_agent(self):
        table = routing.parse_table(
            "## Model routing\n\n| Key | Model | Effort |\n|---|---|---|\n| build | coder | |\n"
        )
        c = routing.select(table, "build", size="S")
        models = {"coder": {"agent": "opencode", "model": "openrouter/qwen/qwen3-coder"}}
        self.assertEqual(routing.worker_flags(c, models),
                         ["--agent", "opencode", "--model", "openrouter/qwen/qwen3-coder"])
        self.assertEqual(routing.task_title("12", "build", c), "#12 · build · coder")
        with self.assertRaises(routing.RoutingError):
            routing.worker_flags(c, {"haiku": "haiku"})

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


OLD_TABLE = """# Orchestration

## Model routing

Mine, above.

| Key | Role | Model | Effort | Notes |
|---|---|---|---|---|
| build.S | Implementer, size S | haiku | | |
| build.M | Implementer, size M | opus | | tuned here |
| review | Integration review | sonnet | high | |
| review.risk | Integration review, risk | opus | | |
| fix | Fixer | sonnet | medium | |
| build.spike | A spike | haiku | low | ours |

Mine, below.

## Escalation

Stays.
"""


class DefaultsFollowReleasesTest(unittest.TestCase):
    def pick(self, table, role, **kw):
        c = routing.select(table, role, **kw)
        return c["model"], c["effort"]

    def test_a_row_set_in_the_config_wins_and_the_rest_are_defaults(self):
        table = routing.effective({"fix": {"model": "Sonnet", "effort": "medium"}})
        self.assertEqual(self.pick(table, "fix"), ("sonnet", "medium"))
        self.assertTrue(table["fix"]["set"])
        self.assertEqual(self.pick(table, "review"), ("opus", None))
        self.assertIn("Set in `flow.json`.", routing.render(table))

    def test_a_config_can_add_a_variant_row(self):
        table = routing.effective({"build.spike": {"model": "haiku", "effort": None, "role": "A spike"}})
        self.assertEqual(self.pick(table, "build", variant="spike"), ("haiku", None))
        self.assertIn("| build.spike | A spike | haiku |", routing.render(table))

    def test_bad_overrides_are_named(self):
        self.assertEqual(routing.check_overrides({"fix": {"model": "opus"}}), [])
        self.assertIn("routing.fix needs a model", routing.check_overrides({"fix": {"effort": "low"}}))
        self.assertTrue(routing.check_overrides({"deploy": {"model": "opus"}}))
        self.assertTrue(routing.check_overrides(["fix"]))

    def test_a_hand_kept_table_keeps_only_the_rows_the_repo_changed(self):
        """review and fix hold what 0.5.0 shipped, so they are not the repo's choice; build.M and build.spike are."""
        got = routing.legacy_overrides(routing.parse_table(OLD_TABLE))
        self.assertEqual(got, {
            "build.M": {"model": "opus", "effort": None},
            "build.spike": {"model": "haiku", "effort": "low", "role": "A spike", "notes": "ours"},
        })

    def test_routing_from_a_hand_kept_doc_takes_new_defaults_and_keeps_the_repos_rows(self):
        table, warnings = routing.resolve({}, OLD_TABLE)
        self.assertEqual(self.pick(table, "fix"), ("opus", None))
        self.assertEqual(self.pick(table, "review"), ("opus", None))
        self.assertEqual(self.pick(table, "build", size="M"), ("opus", None))
        self.assertEqual(self.pick(table, "build", variant="spike"), ("haiku", "low"))
        self.assertEqual(len(warnings), 1)
        self.assertIn("seed_docs.py --apply", warnings[0])
        self.assertIn("build.M", warnings[0])

    def test_the_config_beats_a_hand_kept_row(self):
        table, _ = routing.resolve({"build.m": {"model": "sonnet", "effort": "high"}}, OLD_TABLE)
        self.assertEqual(self.pick(table, "build", size="M"), ("sonnet", "high"))

    def test_handing_the_table_over_touches_only_the_table(self):
        table, _ = routing.resolve({}, OLD_TABLE)
        out = routing.place_block(OLD_TABLE, table)
        self.assertIn("Mine, above.\n\n<!-- flow:begin routing -->", out)
        self.assertIn("<!-- flow:end routing -->\n\nMine, below.\n\n## Escalation\n\nStays.\n", out)
        self.assertNotIn("| fix | Fixer | sonnet |", out)
        self.assertEqual(routing.place_block(out, table), out)
        again, warnings = routing.resolve({"build.M": {"model": "opus"}, "build.spike": {"model": "haiku", "effort": "low", "role": "A spike", "notes": "ours"}}, out)
        self.assertEqual(warnings, [])

    def test_a_stale_copy_is_reported_and_a_fresh_one_is_not(self):
        fresh = routing.place_block("# Doc\n", routing.effective())
        self.assertEqual(routing.resolve({}, fresh)[1], [])
        stale = fresh.replace("| fix | Fixer for the integration review's findings | opus |", "| fix | Fixer | sonnet |")
        table, warnings = routing.resolve({}, stale)
        self.assertEqual(self.pick(table, "fix"), ("opus", None))
        self.assertIn("out of date", warnings[0])
        self.assertIn("out of date", routing.resolve({"fix": {"model": "sonnet"}}, fresh)[1][0])

    def test_no_doc_is_fine(self):
        table, warnings = routing.resolve({}, None)
        self.assertEqual((self.pick(table, "merge"), warnings), (("haiku", "low"), []))

    def test_linear_reads_estimate(self):
        self.assertIn("Implementer, Estimate S, no `risk`", routing.render(routing.effective(None, "Estimate")))


if __name__ == "__main__":
    unittest.main()
