import os
import unittest

import project_doc
import seed_linear_docs

from .helpers import cfg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class SeedTest(unittest.TestCase):
    def test_every_template_renders(self):
        vals = seed_linear_docs.values(cfg())
        for name in ("issue-tracker-linear.md", "triage-labels-linear.md", "orchestration.md", "claude-md-block.md",
                     "ISSUE_TEMPLATE/config.yml"):
            with open(os.path.join(ROOT, "templates", name)) as fh:
                out = seed_linear_docs.render(fh.read(), vals)
            self.assertNotIn("{{", out, name)

    def test_claude_md_block_replaces_the_section_and_keeps_domain_docs(self):
        current = ("# Rules\n\nKeep these.\n\n## Agent skills\n\n### Issue tracker\n\nGitHub.\n\n"
                   "### Domain docs\n\nMulti-context: see CONTEXT-MAP.md.\n\n## Later\n\nStays.\n")
        block = "## Agent skills\n\n### Issue tracker\n\nLinear.\n\n### Domain docs\n\nSingle-context.\n\n### Orchestration\n\nFlow.\n"
        out = seed_linear_docs.merge_claude_md(current, block)
        self.assertIn("Linear.", out)
        self.assertNotIn("GitHub.", out)
        self.assertIn("Multi-context: see CONTEXT-MAP.md.", out)
        self.assertNotIn("Single-context.", out)
        self.assertIn("### Orchestration", out)
        self.assertTrue(out.startswith("# Rules\n\nKeep these.\n\n## Agent skills"))
        self.assertTrue(out.rstrip().endswith("## Later\n\nStays."))
        self.assertEqual(seed_linear_docs.merge_claude_md(out, block), out)

    def test_claude_md_block_appends_when_missing(self):
        out = seed_linear_docs.merge_claude_md("# Rules\n", "## Agent skills\n\nX\n")
        self.assertEqual(out, "# Rules\n\n## Agent skills\n\nX\n")


class ProjectDocTest(unittest.TestCase):
    def test_append_to_existing_section(self):
        content = "## Notes\n\n- n\n\n## Decisions so far\n\n- one\n\n## Out of scope\n\n- x\n"
        out = project_doc.append_to_section(content, "Decisions so far", "- two")
        self.assertIn("- one\n- two\n\n## Out of scope", out)

    def test_append_creates_missing_section(self):
        out = project_doc.append_to_section("## Notes\n\n- n\n", "Decisions so far", "- two")
        self.assertTrue(out.endswith("## Decisions so far\n\n- two\n"))


if __name__ == "__main__":
    unittest.main()
