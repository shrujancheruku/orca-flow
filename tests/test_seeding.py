import json
import os
import re
import tempfile
import unittest
from pathlib import Path

import seed_docs
from flowlib import seeding

from .helpers import cfg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MATT = "# Issue tracker: GitHub\n\nMatt's text.\n"


class MarkerTest(unittest.TestCase):
    def test_append_then_replace_keeps_the_users_text(self):
        once = seeding.upsert("# Mine\n\nKeep.\n", "x", "one")
        self.assertTrue(once.startswith("# Mine\n\nKeep.\n\n<!-- flow:begin x -->"))
        edited = "Above.\n\n" + once + "\nBelow, added by the user.\n"
        twice = seeding.upsert(edited, "x", "two")
        self.assertIn("two", twice)
        self.assertNotIn("one", twice)
        self.assertTrue(twice.startswith("Above."))
        self.assertTrue(twice.rstrip().endswith("Below, added by the user."))
        self.assertEqual(seeding.upsert(twice, "x", "two"), twice)

    def test_half_a_block_is_refused(self):
        with self.assertRaises(seeding.SeedError):
            seeding.upsert("<!-- flow:begin x -->\nstuff\n", "x", "one")

    def test_claude_md_block_goes_at_the_end_of_agent_skills(self):
        cur = "# Rules\n\n## Agent skills\n\n### Issue tracker\n\nGitHub.\n\n### Domain docs\n\nMine.\n\n## Later\n\nStays.\n"
        out = seeding.upsert_in_agent_skills(cur, "orchestration", "### Orchestration\n\nFlow.")
        self.assertIn("GitHub.", out)
        self.assertIn("Mine.", out)
        self.assertLess(out.index("Mine."), out.index("### Orchestration"))
        self.assertLess(out.index("### Orchestration"), out.index("## Later"))
        self.assertTrue(out.rstrip().endswith("Stays."))
        self.assertEqual(seeding.upsert_in_agent_skills(out, "orchestration", "### Orchestration\n\nFlow."), out)

    def test_claude_md_without_the_section_gets_one(self):
        out = seeding.upsert_in_agent_skills("# Rules\n", "o", "### Orchestration")
        self.assertIn("# Rules\n\n## Agent skills\n\n<!-- flow:begin o -->", out)
        self.assertEqual(seeding.upsert_in_agent_skills("", "o", "x").count("## Agent skills"), 1)


class SeedDocsTest(unittest.TestCase):
    def test_every_template_renders(self):
        vals = seed_docs.values(cfg())
        for name in ("orchestration.md", "claude-md-block.md", "issue-tracker-orca-section.md",
                     "triage-labels-flow-section.md"):
            out = seed_docs.template(name, vals)
            self.assertNotIn("{{", out, name)

    def test_this_repos_policy_matches_the_template_on_the_build_rules(self):
        # seed_docs.py rewrites only the routing table, so this repo's own copy is kept in line by hand
        seeded = seed_docs.template("orchestration.md", seed_docs.values(cfg()))
        ours = (Path(__file__).resolve().parent.parent / "docs" / "agents" / "orchestration.md").read_text()
        for phrase in ("it is not merged, except a paperwork-only miss the coordinator rules accepted",
                       "[--coordinator <another coordinator transcript> ...]",
                       "${CLAUDE_PLUGIN_ROOT}/scripts/brief.py --role <role>",
                       "`notes.py --add/--done`, `status.py --ask/--done` and `flow.py watch` are exempt: they write only the local "
                       "bookkeeping files under `<git common dir>/flow/`"):
            for name, text in (("template", seeded), ("docs/agents/orchestration.md", ours)):
                with self.subTest(doc=name, phrase=phrase):
                    self.assertIn(phrase, text)

    def test_seeded_docs_name_no_machine_path(self):
        out = seed_docs.template("orchestration.md", seed_docs.values(cfg()))
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/scripts/route.py", out)
        self.assertNotIn(str(seed_docs.PLUGIN), out)

    def repo(self, tracker=MATT, labels="# Triage\n", claude="# Rules\n\n## Agent skills\n\n### Domain docs\n\nMine.\n"):
        d = tempfile.mkdtemp()
        agents = Path(d, "docs/agents")
        agents.mkdir(parents=True)
        if tracker is not None:
            (agents / "issue-tracker.md").write_text(tracker)
        if labels is not None:
            (agents / "triage-labels.md").write_text(labels)
        if claude is not None:
            Path(d, "CLAUDE.md").write_text(claude)
        return Path(d)

    def apply(self, root):
        for path, content, _ in seed_docs.plan(root, cfg()):
            if content is not None:
                path.write_text(content)

    def test_refuses_without_matts_tracker_doc(self):
        with self.assertRaises(seeding.SeedError) as ctx:
            seed_docs.plan(self.repo(tracker=None), cfg())
        self.assertIn("/setup-matt-pocock-skills", str(ctx.exception))

    def test_seeds_and_a_rerun_writes_nothing(self):
        root = self.repo()
        self.apply(root)
        tracker = (root / "docs/agents/issue-tracker.md").read_text()
        self.assertTrue(tracker.startswith(MATT))
        self.assertIn("## Orca and milestones", tracker)
        self.assertIn("orca worktree create --issue", tracker)
        self.assertIn("Mine.", (root / "CLAUDE.md").read_text())
        self.assertIn("Routing", "Routing " + (root / "docs/agents/orchestration.md").read_text()[:5])
        again = seed_docs.plan(root, cfg())
        self.assertTrue(all(content is None for _, content, _ in again), [w for _, c, w in again])

    def test_a_users_orchestration_doc_keeps_its_text_and_gains_the_routing_table(self):
        root = self.repo()
        (root / "docs/agents/orchestration.md").write_text("# mine\n")
        self.apply(root)
        orch = (root / "docs/agents/orchestration.md").read_text()
        self.assertTrue(orch.startswith("# mine\n\n## Model routing\n\n<!-- flow:begin routing -->"))
        p = root / "docs/agents/issue-tracker.md"
        p.write_text(p.read_text() + "\nMy own note.\n")
        self.apply(root)
        self.assertTrue(p.read_text().rstrip().endswith("My own note."))

    def test_a_new_release_rewrites_only_the_routing_table(self):
        root = self.repo()
        self.apply(root)
        orch = root / "docs/agents/orchestration.md"
        edited = orch.read_text().replace("## Escalation", "## Escalation\n\nOur own rule.").replace(
            "| fix | Fixer for the integration review's findings | opus |", "| fix | Fixer | sonnet |")
        orch.write_text(edited)
        self.apply(root)
        now = orch.read_text()
        self.assertIn("Our own rule.", now)
        self.assertIn("| fix | Fixer for the integration review's findings | opus |", now)

    def test_a_hand_kept_table_is_handed_over_and_its_own_rows_move_to_the_config(self):
        root = self.repo()
        orch = root / "docs/agents/orchestration.md"
        orch.write_text("# Orchestration\n\n## Model routing\n\n| Key | Role | Model | Effort | Notes |\n|---|---|---|---|---|\n"
                        "| build.M | Implementer | opus | | |\n| fix | Fixer | sonnet | medium | |\n\n## Holds\n\nOurs.\n")
        conf = root / "docs/agents/flow.json"
        conf.write_text(json.dumps({"github_repo": "acme/app"}))
        c = cfg()
        c["_path"] = str(conf)
        plans = seed_docs.plan(root, c)
        for path, content, _ in plans:
            if content is not None:
                path.write_text(content)
        self.assertEqual(json.loads(conf.read_text())["routing"], {"build.M": {"model": "opus", "effort": None}})
        text = orch.read_text()
        self.assertIn("| build.M | Implementer, size M | opus |  | Set in `flow.json`. |", text)
        self.assertIn("| fix | Fixer for the integration review's findings | opus |", text)
        self.assertTrue(text.rstrip().endswith("## Holds\n\nOurs."))
        from flowlib import config
        again = seed_docs.plan(root, dict(config.load(str(conf)), _path=str(conf)))
        self.assertTrue(all(content is None for _, content, _ in again if _ is not None), [w for _, c2, w in again])

    def test_missing_triage_file_is_skipped(self):
        plans = seed_docs.plan(self.repo(labels=None), cfg())
        self.assertTrue(any("skipped" in w for _, _, w in plans))


class BoundaryTest(unittest.TestCase):
    def test_core_never_imports_the_adapter(self):
        for base in ("scripts", "tests"):
            for dirpath, _, files in os.walk(os.path.join(ROOT, base)):
                for f in files:
                    if f.endswith(".py") and f != "test_seeding.py":
                        text = open(os.path.join(dirpath, f)).read()
                        self.assertIsNone(re.search(r"^\s*(from|import)\s+(linearlib|adapters)\b", text, re.M), f)


if __name__ == "__main__":
    unittest.main()
