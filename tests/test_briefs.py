import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from flowlib import briefs

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import brief as brief_script  # noqa: E402

COMMON = ["--repo", "acme/app", "--integration-branch", "integration/m1"]
ARGS = {
    "build": ["--ticket", "7"],
    "check": ["--ticket", "7", "--branch", "me/7-x", "--tip", "abc1234", "--round", "2"],
    "merge": ["--ticket", "7", "--branch", "me/7-x"],
    "review": ["--ticket", "45"],
    "fix": ["--ticket", "45", "--round", "2"],
}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.briefs_dir = Path(self.tmp) / "briefs"

    def run_cli(self, *argv, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        full = ["brief.py", "--briefs-dir", str(self.briefs_dir), *argv]
        with mock.patch.object(sys, "argv", full), mock.patch.object(sys, "stdin", io.StringIO(stdin)), \
                redirect_stdout(out), redirect_stderr(err):
            try:
                code = brief_script.main()
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def brief(self, role, *more):
        code, out, err = self.run_cli("--role", role, *ARGS[role], *COMMON, *more)
        self.assertEqual(code, 0, err)
        return out


class RenderTest(Base):
    def test_each_role_renders_with_no_placeholder_left(self):
        for role in briefs.ROLES:
            with self.subTest(role=role):
                out = self.brief(role)
                self.assertNotIn("{{", out)
                self.assertNotIn("}}", out)
                self.assertIn("acme/app", out)
                self.assertIn("integration/m1", out)

    def test_ticket_and_pr_urls(self):
        self.assertIn("https://github.com/acme/app/issues/7", self.brief("build"))
        self.assertIn("https://github.com/acme/app/pull/45", self.brief("review"))
        self.assertIn("https://github.com/acme/app/pull/45", self.brief("fix"))

    def test_branch_tip_and_round_are_filled(self):
        out = self.brief("check")
        self.assertIn("me/7-x", out)
        self.assertIn("abc1234", out)
        self.assertIn("round 2", out)

    def test_ticket_url_overrides_for_another_tracker(self):
        out = self.brief("build", "--ticket-url", "https://linear.app/acme/issue/ABC-7")
        self.assertIn("https://linear.app/acme/issue/ABC-7", out)

    def test_reads_nothing_and_writes_nothing(self):
        with mock.patch("subprocess.run", side_effect=AssertionError("ran a command")), \
                mock.patch("subprocess.Popen", side_effect=AssertionError("ran a command")):
            self.brief("check")
        self.assertFalse(self.briefs_dir.exists())

    def test_a_template_with_an_unknown_placeholder_is_an_error(self):
        with self.assertRaises(briefs.BriefError):
            briefs.fill("hello {{nope}}", {})


class MissingValueTest(Base):
    def test_a_linear_repo_needs_no_github_repo_with_a_ticket_url(self):
        cfg = Path(self.tmp) / "flow.json"
        cfg.write_text('{"tracker": "linear"}')
        code, out, err = self.run_cli("--config", str(cfg), "--role", "build", "--ticket", "7", "--repo", "acme/app",
                                      "--ticket-url", "https://linear.app/x/ABC-7", *COMMON[2:])
        self.assertEqual(code, 0, err)
        self.assertIn("https://linear.app/x/ABC-7", out)

    def test_missing_required_flag_names_the_flag(self):
        cases = [
            ("build", ["--ticket", "7"], "--integration-branch"),
            ("check", ["--ticket", "7", "--integration-branch", "i/m", "--tip", "abc"], "--branch"),
            ("check", ["--ticket", "7", "--integration-branch", "i/m", "--branch", "b"], "--tip"),
            ("merge", ["--ticket", "7", "--integration-branch", "i/m"], "--branch"),
            ("review", ["--integration-branch", "i/m"], "--ticket"),
        ]
        for role, argv, flag in cases:
            with self.subTest(role=role, flag=flag):
                code, out, err = self.run_cli("--role", role, "--repo", "acme/app", *argv)
                self.assertEqual(code, 1)
                self.assertEqual(out, "")
                self.assertIn(flag, err)

    def test_ticket_missing_names_the_flag(self):
        code, _, err = self.run_cli("--role", "build", *COMMON)
        self.assertEqual(code, 1)
        self.assertIn("--ticket", err)

    def test_a_bad_ticket_is_an_error(self):
        code, _, err = self.run_cli("--role", "build", "--ticket", "abc", *COMMON)
        self.assertEqual(code, 1)
        self.assertIn("abc", err)


class AppendTest(Base):
    def test_extra_file_then_repo_file_order(self):
        self.briefs_dir.mkdir()
        (self.briefs_dir / "build.md").write_text("REPO-OWN-RULE\n")
        extra = Path(self.tmp) / "extra.md"
        extra.write_text("TICKET-SPECIFIC-TEXT\n")
        out = self.brief("build", "--extra", str(extra))
        t, r, e = out.index("Build #7"), out.index("REPO-OWN-RULE"), out.index("TICKET-SPECIFIC-TEXT")
        self.assertLess(t, r)
        self.assertLess(r, e)
        self.assertIn("## Ticket-specific", out)

    def test_extra_from_stdin(self):
        code, out, _ = self.run_cli("--role", "build", *ARGS["build"], *COMMON, "--extra", "-", stdin="FROM-STDIN\n")
        self.assertEqual(code, 0)
        self.assertIn("FROM-STDIN", out)

    def test_no_extra_means_no_heading_and_other_roles_repo_file_ignored(self):
        self.briefs_dir.mkdir()
        (self.briefs_dir / "fix.md").write_text("FIX-ONLY\n")
        out = self.brief("build")
        self.assertNotIn("## Ticket-specific", out)
        self.assertNotIn("FIX-ONLY", out)

    def test_missing_extra_file_is_an_error(self):
        code, _, err = self.run_cli("--role", "build", *ARGS["build"], *COMMON, "--extra", str(Path(self.tmp) / "nope"))
        self.assertEqual(code, 1)
        self.assertIn("--extra", err)


def template(role):
    return (ROOT / "templates" / "briefs" / f"{role}.md").read_text()


class RulesTest(unittest.TestCase):
    """Each rule the ticket lists is in its template: one key phrase per rule."""

    def has(self, role, *phrases):
        text = " ".join(template(role).split())
        for phrase in phrases:
            with self.subTest(role=role, phrase=phrase):
                self.assertIn(phrase, text)

    def test_one_template_per_role(self):
        self.assertEqual(sorted(briefs.ROLES), ["build", "check", "fix", "merge", "review"])
        for role in briefs.ROLES:
            self.assertTrue((ROOT / "templates" / "briefs" / f"{role}.md").is_file())

    def test_build(self):
        self.has("build", "based on the tip of", "test-first", "acceptance criterion", "done list",
                 "resolution comment", "verbatim last lines", "Merge the tip of", "rerun the verify commands",
                 "Never end a turn waiting on a process that may not exit",
                 "search of the vendor's docs or issues for the exact error")

    def test_check(self):
        self.has("check", "read-only", "integration tip to the branch tip", "PASS or FAIL with the file and line",
                 "**FAIL**", "**FIX-FORWARD**", "another open ticket in the milestone owns is not a deviation",
                 "separate `git worktree` with its own install", "shares installed dependencies",
                 "adversarial question", "quotes the spec", "one comment on the ticket")

    def test_merge(self):
        self.has("merge", "git fetch", "Merge the tip of", "A conflict anywhere else stops you", "shared files", "Run the verify commands on the merged tree",
                 "unless nothing new came in", "without force", "fast-forward", "Confirm the pushed tip",
                 "Edit no issue, label or PR")

    def test_review(self):
        self.has("review", "base branch", "`code-review`", "Review checks", "carried notes", "notes.py --markdown",
                 "a lead to confirm in the code, not as a finding", "one review on the integration PR", "verdict first",
                 "inline and ranked", "separate list", "Fix nothing")

    def test_fix(self):
        self.has("fix", "blocking findings and every should-fix", "fails without it", "unbounded",
                 "founder-decision list alone", "one comment on the PR mapping each finding to its commit and its test",
                 "Push the fix branch only", "a merger lands it", "names the job and reproduces the failure")


if __name__ == "__main__":
    unittest.main()
