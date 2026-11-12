import unittest

from flowlib import github, labels

from .helpers import cfg


class GuardTest(unittest.TestCase):
    def test_dry_run_records_and_never_runs(self):
        ran = []
        gh = github.Gh("acme/app", apply=False, runner=lambda a, s=None: ran.append(a) or "")
        self.assertIsNone(gh.write(["label", "create", "x"], "make x"))
        self.assertEqual(ran, [])
        self.assertEqual([p.describe for p in gh.planned], ["make x"])

    def test_apply_runs_the_write(self):
        ran = []
        gh = github.Gh("acme/app", apply=True, runner=lambda a, s=None: ran.append(a) or "ok")
        gh.write(["label", "create", "x"], "make x")
        self.assertEqual(ran, [["label", "create", "x"]])
        self.assertEqual(gh.done, ["make x"])

    def test_read_refuses_writes(self):
        gh = github.Gh("acme/app", runner=lambda a, s=None: "[]")
        for bad in (["label", "create", "x"], ["issue", "edit", "1"], ["pr", "comment", "1"],
                    ["api", "-X", "POST", "x"], ["api", "x", "-f", "a=b"]):
            with self.assertRaises(github.GitHubError, msg=bad):
                gh.read(bad)
        self.assertEqual(gh.read(["api", "repos/a/b/milestones"]), "[]")
        self.assertEqual(gh.read(["label", "list"]), "[]")

    def test_ticket_number(self):
        self.assertEqual([github.ticket_number(x) for x in (12, "12", "#12")], [12, 12, 12])
        with self.assertRaises(github.GitHubError):
            github.ticket_number("ABC-1")


class LabelPlanTest(unittest.TestCase):
    def test_creates_only_what_is_missing_and_reports_triage(self):
        plan = labels.plan(["bug", "Size:S", "needs-info", "ready-for-agent"], cfg())
        self.assertEqual([l["name"] for l in plan["create"]], ["size:M", "size:L", "risk", "integrated"])
        self.assertEqual(plan["present"], ["size:S"])
        self.assertEqual(plan["missing_triage"], ["needs-triage", "ready-for-human", "wontfix"])

    def test_rerun_after_create_is_empty(self):
        names = [l["name"] for l in labels.wanted(cfg())] + list(cfg()["labels"]["triage"])
        plan = labels.plan(names, cfg())
        self.assertEqual((plan["create"], plan["missing_triage"]), ([], []))

    def test_create_command(self):
        lab = labels.wanted(cfg())[0]
        args = labels.create_args("acme/app", lab)
        self.assertEqual(args[:5], ["label", "create", "size:S", "--repo", "acme/app"])
        self.assertIn("--color", args)


if __name__ == "__main__":
    unittest.main()
