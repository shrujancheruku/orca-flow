import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from flowlib import github as gh_mod
from flowlib import notes, status

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import notes as notes_script  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = Path(self.tmp) / "flow" / "notes.jsonl"

    def run_cli(self, *argv):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"FLOW_NOTES_FILE": str(self.path)}), \
                mock.patch.object(sys, "argv", ["notes.py", *argv]), redirect_stdout(out):
            code = notes_script.main()
        return code, out.getvalue()


class StoreTest(Base):
    def test_add_prints_an_id_and_done_clears_it(self):
        code, out = self.run_cli("--add", "README row missing", "--ticket", "#7")
        self.assertEqual(code, 0)
        note_id = out.strip()
        self.assertEqual([e["id"] for e in notes.live(self.path)], [note_id])
        self.assertEqual(self.run_cli("--done", note_id), (0, f"done {note_id}\n"))
        self.assertEqual(notes.live(self.path), [])
        self.assertEqual(self.run_cli("--done", note_id)[0], 1)  # already cleared

    def test_a_linear_id_is_accepted_grouped_and_printed(self):
        for argv in (("--add", "one", "--ticket", "abc-12"), ("--add", "two", "--ticket", "ABC-3"),
                     ("--add", "gh", "--ticket", "#7"), ("--add", "bad", "--ticket", "ABC-")):
            if argv[-1] == "ABC-":
                with self.assertRaises(SystemExit), mock.patch("sys.stderr", io.StringIO()):
                    self.run_cli(*argv)
            else:
                self.assertEqual(self.run_cli(*argv)[0], 0)
        listing = self.run_cli()[1]
        self.assertIn("ABC-12: one", listing)
        md = self.run_cli("--markdown")[1].splitlines()
        self.assertEqual([l for l in md if not l.startswith("  ")], ["- #7", "- ABC-3", "- ABC-12"])

    def test_status_asks_still_take_only_github_numbers(self):
        with self.assertRaises(gh_mod.GitHubError):
            status.add_ask(self.path, "x", ticket="ABC-1")

    def test_add_needs_text_and_a_ticket(self):
        for argv in (["--add", "  "], ["--add", "text"]):
            with self.assertRaises(SystemExit), mock.patch("sys.stderr", io.StringIO()):
                self.run_cli(*argv, *(["--ticket", "3"] if argv[1] == "  " else []))
        self.assertFalse(self.path.exists())

    def test_list_is_oldest_first_one_line_with_its_ticket(self):
        a = notes.add(self.path, "first", ticket=3)
        b = notes.add(self.path, "second", ticket=2)
        self.assertEqual(self.run_cli()[1], f"[{a}] #3: first\n[{b}] #2: second\n")

    def test_list_is_silent_when_empty(self):
        self.assertEqual(self.run_cli(), (0, ""))

    def test_markdown_groups_by_ticket(self):
        a = notes.add(self.path, "wording", ticket=5)
        b = notes.add(self.path, "no README row", ticket=2)
        c = notes.add(self.path, "proof summarised", ticket=5)
        code, out = self.run_cli("--markdown")
        self.assertEqual(code, 0)
        self.assertEqual(out, f"- #2\n  - no README row (`{b}`)\n- #5\n  - wording (`{a}`)\n  - proof summarised (`{c}`)\n")

    def test_markdown_prints_nothing_when_none(self):
        self.assertEqual(self.run_cli("--markdown"), (0, ""))
        a = notes.add(self.path, "x", ticket=1)
        notes.done(self.path, a)
        self.assertEqual(self.run_cli("--markdown"), (0, ""))

    def test_the_file_is_private(self):
        notes.add(self.path, "x", ticket=1)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        os.chmod(self.path, 0o644)
        notes.add(self.path, "y", ticket=1)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_the_file_is_in_the_git_common_dir_and_the_env_overrides_it(self):
        repo = os.path.join(self.tmp, "repo")
        subprocess.run(["git", "init", "-q", repo], check=True)
        with mock.patch.dict(os.environ):
            os.environ.pop("FLOW_NOTES_FILE", None)
            path = notes.notes_path(repo)
        self.assertEqual(path, Path(os.path.realpath(repo)) / ".git" / "flow" / "notes.jsonl")
        with mock.patch.dict(os.environ, {"FLOW_NOTES_FILE": "/x/n.jsonl"}):
            self.assertEqual(notes.notes_path(repo), Path("/x/n.jsonl"))

    def test_a_non_json_line_is_skipped(self):
        a = notes.add(self.path, "kept", ticket=1)
        with open(self.path, "a") as f:
            f.write("not json\n[1,2]\n")
        b = notes.add(self.path, "after", ticket=1)
        self.assertEqual([e["id"] for e in notes.live(self.path)], [a, b])

    def test_printed_text_has_controls_and_bidi_stripped(self):
        notes.add(self.path, "bad \x1b[2J ‮evil‬ ```x```", ticket=4)
        for out in (self.run_cli()[1], self.run_cli("--markdown")[1]):
            self.assertNotIn("\x1b", out)
            self.assertNotIn("‮", out)
            self.assertNotIn("```", out)

    def test_notes_and_asks_share_one_store_but_not_one_file(self):
        self.assertEqual(status.asks_path(".").name, "asks.jsonl")
        self.assertEqual(notes.notes_path(".").name, "notes.jsonl")
        # `status` reads the asks through the notes store code, not a copy of it.
        with mock.patch.object(notes, "live", return_value=["sentinel"]) as live:
            self.assertEqual(status.live_asks(self.path), ["sentinel"])
        live.assert_called_once_with(self.path)
        a = status.add_ask(self.path, "an ask", where="here")
        self.assertEqual(notes.live(self.path)[0]["id"], a)


if __name__ == "__main__":
    unittest.main()
