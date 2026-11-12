import os
import tempfile
import unittest

from flowlib import config, mapping

from .helpers import cfg, issue


class ConfigTest(unittest.TestCase):
    def test_missing_required_keys_are_named(self):
        with self.assertRaises(config.ConfigError) as ctx:
            config.from_dict({"workspace_id": "ws"})
        self.assertIn("team.key", str(ctx.exception))

    def test_sizes_must_rise(self):
        with self.assertRaises(config.ConfigError):
            cfg(estimate_scale={"linear_type": "linear", "sizes": {"S": 3, "M": 2, "L": 5}})

    def test_env_overrides_keychain_service(self):
        os.environ["LINEAR_KEYCHAIN_SERVICE"] = "other"
        try:
            self.assertEqual(cfg()["keychain_service"], "other")
        finally:
            del os.environ["LINEAR_KEYCHAIN_SERVICE"]


class LabelMappingTest(unittest.TestCase):
    def setUp(self):
        self.cfg = cfg()

    def test_bug_and_enhancement_become_linear_types(self):
        out = mapping.map_labels(["bug", "enhancement"], self.cfg)
        self.assertEqual(out["labels"], ["Bug", "Feature"])

    def test_map_label_is_retired(self):
        out = mapping.map_labels(["wayfinder:map"], self.cfg)
        self.assertEqual(out["labels"], [])
        self.assertEqual(out["dropped"], ["wayfinder:map"])

    def test_wayfinder_and_triage_labels_carry_over(self):
        out = mapping.map_labels(["wayfinder:grilling", "ready-for-agent", "needs-info"], self.cfg)
        self.assertEqual(out["labels"], ["wayfinder:grilling", "ready-for-agent", "needs-info"])
        self.assertEqual(out["unmapped"], [])

    def test_size_label_becomes_estimate(self):
        out = mapping.map_labels(["size:L"], self.cfg)
        self.assertEqual(out["estimate"], 5)
        self.assertEqual(out["labels"], [])

    def test_record_ids_are_stable_version_4_uuids(self):
        import uuid
        a = mapping.stable_id("issue", "198")
        self.assertEqual(a, mapping.stable_id("issue", "198"))
        self.assertEqual(uuid.UUID(a).version, 4)

    def test_state_role_labels_are_dropped(self):
        out = mapping.map_labels(["needs-triage", "wontfix", "duplicate", "invalid"], self.cfg)
        self.assertEqual(out["labels"], [])
        self.assertEqual(out["unmapped"], [])

    def test_unmapped_label_is_kept_and_reported(self):
        out = mapping.map_labels(["documentation"], self.cfg)
        self.assertEqual(out["labels"], ["documentation"])
        self.assertEqual(out["unmapped"], ["documentation"])

    def test_unmapped_label_can_be_dropped(self):
        out = mapping.map_labels(["documentation"], cfg(labels={"unmapped": "drop"}))
        self.assertEqual(out["labels"], [])


class StateMappingTest(unittest.TestCase):
    def setUp(self):
        self.cfg = cfg()

    def state(self, in_project=False, **kw):
        return mapping.issue_state(issue(1, **kw), self.cfg, in_project)

    def test_closed_states(self):
        self.assertEqual(self.state(state="CLOSED", reason="COMPLETED"), "done")
        self.assertEqual(self.state(state="CLOSED", reason="NOT_PLANNED"), "canceled")
        self.assertEqual(self.state(state="CLOSED", reason="DUPLICATE"), "duplicate")

    def test_needs_info_stays_in_triage(self):
        self.assertEqual(self.state(labels=["needs-info"], in_project=True), "triage")

    def test_ready_labels_go_to_todo(self):
        self.assertEqual(self.state(labels=["ready-for-agent"]), "todo")
        self.assertEqual(self.state(labels=["ready-for-human"]), "todo")

    def test_wayfinder_ticket_goes_to_todo(self):
        self.assertEqual(self.state(labels=["wayfinder:research"]), "todo")

    def test_unlabelled_incoming_issue_goes_to_triage(self):
        self.assertEqual(self.state(), "triage")


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.cfg = cfg()
        body = "## Destination\n\nShip the thing.\n\n## Notes\n\n- a note\n\n## Decisions so far\n\n- none"
        self.issues = [
            issue(1, "Map: The app", labels=["wayfinder:map"], sub=[2, 3], body=body),
            issue(2, "Research X", labels=["wayfinder:research"], parent=1, state="CLOSED", reason="COMPLETED"),
            issue(3, "Grill Y", labels=["wayfinder:grilling"], parent=1, blocked_by=[2]),
            issue(4, "Spec: The app", labels=["ready-for-agent"], sub=[5], body="## Problem Statement\n\nUsers hurt."),
            issue(5, "Build Z", labels=["ready-for-agent"], parent=4, blocked_by=[1]),
            issue(6, "Bug report", labels=["bug"], sub=[7]),
            issue(7, "Part of the bug", parent=6),
        ]
        self.plan = mapping.build_plan(self.issues, self.cfg)

    def test_maps_and_specs_become_projects(self):
        kinds = {p["number"]: (p["kind"], p["label"], p["status_type"]) for p in self.plan["projects"]}
        self.assertEqual(kinds, {1: ("map", "wayfinder", "started"), 4: ("spec", "build", "started")})

    def test_same_names_get_their_kind(self):
        names = sorted(p["name"] for p in self.plan["projects"])
        self.assertEqual(names, ["The app (map)", "The app (spec)"])

    def test_destination_is_the_summary_and_the_rest_the_content(self):
        p = next(p for p in self.plan["projects"] if p["number"] == 1)
        self.assertEqual(p["description"], "Ship the thing.")
        self.assertIn("## Notes", p["content"])
        self.assertNotIn("## Destination", p["content"])

    def test_spec_summary_comes_from_the_problem_statement(self):
        p = next(p for p in self.plan["projects"] if p["number"] == 4)
        self.assertEqual(p["description"], "Users hurt.")

    def test_children_of_projects_get_the_project_not_a_parent(self):
        by = {i["number"]: i for i in self.plan["issues"]}
        self.assertEqual((by[3]["project_number"], by[3]["parent_number"]), (1, None))
        self.assertEqual((by[7]["project_number"], by[7]["parent_number"]), (None, 6))

    def test_blocking_between_issues_becomes_a_relation(self):
        pairs = [(r["blocker"], r["blocked"]) for r in self.plan["relations"]]
        self.assertEqual(pairs, [(2, 3)])
        self.assertEqual([(s["blocker"], s["blocked"]) for s in self.plan["skipped_relations"]], [(1, 5)])

    def test_ids_are_stable_across_runs(self):
        again = mapping.build_plan(self.issues, self.cfg)
        self.assertEqual([i["id"] for i in again["issues"]], [i["id"] for i in self.plan["issues"]])

    def test_comment_keeps_author_and_date(self):
        c = {"id": "IC_1", "url": "https://github.com/acme/app/issues/2#issuecomment-9", "created_at": "2026-10-03T00:00:00Z",
             "body": "Found it.", "author": "someone"}
        plan = mapping.build_plan([issue(2, comments=[c])], self.cfg)
        body = plan["issues"][0]["comments"][0]["body"]
        self.assertTrue(body.startswith("**@someone** on GitHub, 2026-10-03"))
        self.assertTrue(body.endswith("Found it."))


class MappingFileTest(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "map.json")
            m = mapping.MappingFile(path, "acme/app", "ABC")
            m.record_issue(2, "id-2", "ABC-1", "https://linear.app/acme/issue/ABC-1")
            m.record_project(1, "pid-1", "The app", "https://linear.app/acme/project/the-app")
            m.record_comment("IC_1", "cid-1")
            m.record_relation("rid", 2, 3)
            m.save()
            back = mapping.MappingFile.load(path, "acme/app")
            self.assertEqual(back.data, m.data)
            self.assertEqual(back.ref_table()[2], {"kind": "issue", "label": "ABC-1", "url": "https://linear.app/acme/issue/ABC-1"})
            self.assertEqual(back.ref_table()[1]["kind"], "project")

    def test_refuses_another_repos_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "map.json")
            mapping.MappingFile(path, "acme/app").save()
            with self.assertRaises(ValueError):
                mapping.MappingFile.load(path, "acme/other")


class EstimateBandTest(unittest.TestCase):
    def test_bands(self):
        c = cfg()
        self.assertEqual([mapping.estimate_to_size(v, c) for v in (1, 2, 3, 5, 8)], ["S", "S", "M", "L", "L"])
        self.assertIsNone(mapping.estimate_to_size(None, c))


if __name__ == "__main__":
    unittest.main()
