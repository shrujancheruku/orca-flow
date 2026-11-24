import os
import stat
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from flowlib import console, github, notes, orca, status, tui

TERM = "term_abc"
PANE = "tab1:leaf1"


def fake_orca(answers=None, fail=()):
    """An orca runner keyed by the first two words of the command; a key in `fail` raises."""
    base = {
        ("terminal", "show"): {"terminal": {"handle": TERM, "connected": True, "tabId": "tab1", "leafId": "leaf1"}},
        ("agent", "list"): {"agents": [
            {"orcaSessionId": "other", "paneKey": "tab9:leaf9", "state": "working", "lastAssistantMessage": "not me"},
            {"orcaSessionId": "sess1", "paneKey": PANE, "state": "waiting", "lastAssistantMessage": "Started #20."},
        ]},
        ("orchestration", "run-list"): {"runs": [
            {"id": "run_old", "objective": "flow:build #19"},
            {"id": "run_other", "objective": "#21 · build · sonnet"},
            {"id": "run_new", "objective": "flow:build #19"},
        ]},
        ("terminal", "send"): {"accepted": True},
        ("terminal", "switch"): {},
        ("agent", "read"): {"entries": [
            {"kind": "message", "role": "user", "text": "/flow:build #19"},
            {"kind": "message", "role": "assistant", "text": "", "tools": [{"name": "Bash"}]},
            {"kind": "message", "role": "assistant", "text": "Merged #20."},
        ]},
    }
    base.update(answers or {})
    calls = []

    def run(args):
        calls.append(args)
        key = tuple(args[:2])
        if key in fail:
            raise orca.OrcaError(f"orca {' '.join(key)} failed: boom")
        if key not in base:
            raise AssertionError(f"unexpected orca call {args}")
        return base[key]
    run.calls = calls
    return run


def footer(waiting=(), rows=(), unavailable=()):
    return {"run": "run_new", "milestone": "Run learnings", "in_progress": list(rows), "tally": None,
            "off_ticket_workers": 0, "notes_carried": 0, "waiting": list(waiting), "unavailable": list(unavailable)}


class Stores(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.asks = Path(self.tmp.name) / "asks.jsonl"
        self.notes = Path(self.tmp.name) / "notes.jsonl"

    def state(self, **over):
        s = {"spec": "#19", "terminal": TERM, "session": None, "run": None}
        s.update(over)
        return s


class Launch(unittest.TestCase):
    def test_spec_ref_takes_an_issue_or_a_linear_id(self):
        self.assertEqual(console.spec_ref("19"), "#19")
        self.assertEqual(console.spec_ref("#19"), "#19")
        self.assertEqual(console.spec_ref("abc-12"), "ABC-12")

    def test_prompt_starts_the_build_and_names_the_run_objective(self):
        text = console.prompt("#19")
        self.assertTrue(text.startswith("/flow:build #19\n"))
        self.assertIn('run-create --objective "flow:build #19"', text)
        self.assertIn("status.py --ask", text)
        self.assertIn("Automerge is off", text)

    def test_prompt_carries_the_milestone_and_automerge(self):
        text = console.prompt("#19", milestone="Run learnings", automerge=True)
        self.assertTrue(text.startswith("/flow:build #19, milestone Run learnings\n"))
        self.assertIn("turned automerge on", text)

    def test_launch_runs_claude_in_a_terminal_of_the_repo(self):
        args = console.launch_args("/r/app", "go", "opus", "high")
        self.assertEqual(args[:6], ["agent", "launch", "--agent", "claude", "--surface", "terminal"])
        self.assertIn("path:/r/app", args)
        self.assertEqual(args[args.index("--model") + 1], "opus")
        self.assertEqual(args[args.index("--effort") + 1], "high")

    def test_no_effort_without_a_model(self):
        # Orca refuses --effort without --model.
        self.assertNotIn("--effort", console.launch_args("/r", "go", None, "high"))

    def test_parse_launch_finds_the_terminal_and_session_anywhere(self):
        found = console.parse_launch({"outcome": {"kind": "terminal", "terminal": {"handle": "term_x"}},
                                      "agent": {"orcaSessionId": "orca_session_id:s1"}})
        self.assertEqual(found, {"terminal": "term_x", "session": "s1"})
        self.assertEqual(console.parse_launch({"ok": 1}), {"terminal": None, "session": None})


class State(Stores):
    def test_round_trip_private_file(self):
        path = Path(self.tmp.name) / "flow" / "console.json"
        console.save_state(path, {"spec": "#19", "terminal": TERM})
        self.assertEqual(console.load_state(path), {"spec": "#19", "terminal": TERM})
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_missing_or_broken_file_is_no_state(self):
        path = Path(self.tmp.name) / "console.json"
        self.assertEqual(console.load_state(path), {})
        path.write_text("not json")
        self.assertEqual(console.load_state(path), {})


class Reading(Stores):
    def test_find_run_takes_the_newest_with_the_objective(self):
        runs = fake_orca()(["orchestration", "run-list"])["runs"]
        self.assertEqual(console.find_run(runs, "#19"), "run_new")
        self.assertIsNone(console.find_run(runs, "#30"))

    def test_coordinator_matched_by_its_terminal_pane(self):
        errors = []
        c = console.read_coordinator(self.state(), fake_orca(), errors)
        self.assertEqual((c["state"], c["last"], c["session"], c["connected"]),
                         ("waiting", "Started #20.", "sess1", True))
        self.assertEqual(errors, [])

    def test_coordinator_matched_by_session_once_known(self):
        run = fake_orca({("terminal", "show"): {"terminal": {"connected": True}}})
        c = console.read_coordinator(self.state(session="sess1"), run, [])
        self.assertEqual(c["last"], "Started #20.")

    def test_a_gone_terminal_reads_as_not_connected(self):
        errors = []
        c = console.read_coordinator(self.state(), fake_orca(fail={("terminal", "show")}), errors)
        self.assertFalse(c["connected"])
        self.assertIsNone(c["state"])
        self.assertIn("coordinator terminal", errors[0])

    def test_snapshot_finds_the_run_and_never_falls_back_to_run_current(self):
        seen = []
        state = self.state()
        snap = console.snapshot(state, fake_orca(), lambda r: seen.append(r) or footer(), self.asks, self.notes)
        self.assertEqual(seen, ["run_new"])
        self.assertEqual((state["run"], state["session"]), ("run_new", "sess1"))
        self.assertEqual(snap["run"], "run_new")

    def test_snapshot_before_the_run_exists_reads_no_status(self):
        run = fake_orca({("orchestration", "run-list"): {"runs": []}})
        snap = console.snapshot(self.state(), run, lambda r: self.fail("read without a run"), self.asks, self.notes)
        self.assertIsNone(snap["status"])
        self.assertIn("waiting for the coordinator to create its run", console.plain(snap))

    def test_snapshot_keeps_going_when_status_breaks(self):
        def broken(_):
            raise RuntimeError("gh down")
        snap = console.snapshot(self.state(run="run_new"), fake_orca(), broken, self.asks, self.notes)
        self.assertIsNone(snap["status"])
        self.assertIn("status (RuntimeError: gh down)", console.plain(snap))

    def test_log_reads_the_conversation(self):
        log = console.read_log("sess1", fake_orca())
        self.assertEqual(log, [("user", "/flow:build #19"), ("assistant", "(tools: Bash)"),
                               ("assistant", "Merged #20.")])
        self.assertIn("not reported", console.read_log(None, fake_orca())[0][1])


class Drawing(Stores):
    def snap(self, data=None, **coord):
        c = {"connected": True, "state": "working", "last": "Merged #20 into the integration branch.",
             "session": "sess1"}
        c.update(coord)
        return {"spec": "#19", "run": "run_new", "coordinator": c, "status": data,
                "asks": status.live_asks(self.asks), "notes": notes.live(self.notes), "errors": [], "read_at": 100.0}

    def test_asks_are_numbered_and_the_footer_supplies_the_rest(self):
        status.add_ask(self.asks, "Turn automerge on?", ticket=19, where="the console")
        waiting = [{"section": "asks", "heading": "Your asks", "items": ["dup"], "count": 1},
                   {"section": "needs-info", "heading": "Needs info", "items": ["#30 Scope"], "count": 1}]
        rows = [{"ticket": "#20", "role": "build", "model": "sonnet", "title": None, "dispatch": "d",
                 "elapsed_s": 600, "flags": []}]
        text = console.plain(self.snap(footer(waiting, rows)), now=103.0)
        self.assertIn("coordinator working · run_new · read 3s ago", text)
        self.assertIn("  1) [", text)
        self.assertIn("Turn automerge on? (#19) — the console", text)
        self.assertIn("Needs info (1)", text)
        self.assertNotIn("dup", text)  # the footer's asks section is replaced, not repeated
        self.assertIn("#20 build sonnet 10m", text)

    def test_nothing_waiting(self):
        self.assertIn("Waiting on you: nothing", console.plain(self.snap(footer())))

    def test_a_long_last_message_is_cut_to_a_few_lines(self):
        lines = [l for l in console.plain(self.snap(footer(), last="word " * 400), width=60).splitlines()
                 if l.startswith("  word")]
        self.assertEqual(len(lines), console.LAST_LINES)
        self.assertTrue(lines[-1].endswith("…"))

    def test_disconnected_coordinator_and_unavailable_sources(self):
        snap = self.snap(footer(unavailable=["GitHub (gh failed)"]), state=None, connected=False, last=None)
        snap["errors"] = ["orca agents (boom)"]
        text = console.plain(snap)
        self.assertIn("coordinator not connected", text)
        self.assertIn("Unavailable: orca agents (boom); GitHub (gh failed)", text)

    def test_a_blocked_coordinator_points_at_its_terminal(self):
        self.assertIn("press o to answer it in Orca", console.plain(self.snap(footer(), state="blocked")))
        self.assertNotIn("press o", console.plain(self.snap(footer())))

    def test_carried_notes_are_listed(self):
        notes.add(self.notes, "worker skipped the README", ticket=22)
        self.assertIn("Carried notes (1)", console.plain(self.snap(footer())))


class Acting(Stores):
    def test_a_reply_is_typed_into_the_coordinator_as_the_founder(self):
        run = fake_orca()
        self.assertEqual(console.send(self.state(), run, "  automerge\n on "), "sent to the coordinator")
        self.assertEqual(run.calls[-1], ["terminal", "send", "--terminal", TERM, "--text", "automerge on",
                                         "--enter", "--wait-submit", "5", "--json"])

    def test_nothing_is_sent_for_an_empty_reply(self):
        run = fake_orca()
        self.assertEqual(console.send(self.state(), run, "  "), "nothing sent")
        self.assertEqual(run.calls, [])

    def test_a_failed_send_says_so(self):
        msg = console.send(self.state(), fake_orca(fail={("terminal", "send")}), "yes")
        self.assertTrue(msg.startswith("not sent:"))

    def test_an_answer_names_its_ask(self):
        text = console.answer_text({"id": "a1b2c3", "text": "Turn automerge on?"}, "yes,  go")
        self.assertEqual(text, "Answer to your ask a1b2c3 (Turn automerge on?): yes, go")


class FakeScreen:
    def getmaxyx(self):
        return (30, 100)


class Keys(Stores):
    def screen(self, run):
        s = tui.Screen(FakeScreen(), self.state(), run, None, self.asks, self.notes, lambda _: None, 5)
        s.draw = lambda: None
        return s

    def test_q_quits_and_other_keys_do_not(self):
        s = self.screen(fake_orca())
        self.assertTrue(s.key(ord("x")))
        self.assertFalse(s.key(ord("q")))

    def test_a_digit_answers_that_ask(self):
        status.add_ask(self.asks, "Turn automerge on?")
        ask = status.live_asks(self.asks)[0]
        run = fake_orca()
        s = self.screen(run)
        s.snap = {"asks": [ask]}
        s.ask_line = lambda label: "yes"
        s.key(ord("1"))
        self.assertEqual(s.message, "sent to the coordinator")
        self.assertIn(f"Answer to your ask {ask['id']}", run.calls[-1][5])

    def test_a_digit_past_the_asks_sends_nothing(self):
        run = fake_orca()
        s = self.screen(run)
        s.snap = {"asks": []}
        s.key(ord("3"))
        self.assertEqual((s.message, run.calls), ("no ask 3", []))

    def test_escape_cancels_a_reply(self):
        run = fake_orca()
        s = self.screen(run)
        s.ask_line = lambda label: None
        s.key(ord("r"))
        self.assertEqual((s.message, run.calls), ("cancelled", []))

    def test_l_opens_the_log_and_goes_back(self):
        s = self.screen(fake_orca())
        s.state["session"] = "sess1"
        s.key(ord("l"))
        self.assertEqual(s.mode, "log")
        self.assertEqual(s.log[-1], ("assistant", "Merged #20."))
        s.key(ord("l"))
        self.assertEqual(s.mode, "main")


class Resilience(Stores):
    def test_the_milestone_the_footer_found_is_saved_for_the_next_read(self):
        state = self.state(run="run_new")
        state.pop("milestone", None)
        console.snapshot(state, fake_orca(), lambda r: footer(), self.asks, self.notes)
        self.assertEqual(state["milestone"], "Run learnings")

    def test_a_milestone_already_set_is_kept(self):
        state = self.state(run="run_new")
        state["milestone"] = "Given"
        console.snapshot(state, fake_orca(), lambda r: footer(), self.asks, self.notes)
        self.assertEqual(state["milestone"], "Given")

    def test_the_header_names_the_console_pid(self):
        snap = console.snapshot(self.state(run="run_new"), fake_orca(), lambda r: footer(), self.asks, self.notes)
        self.assertIn(f"pid {os.getpid()}", console.frame(snap)[0][0])

    def test_a_github_notice_shows_once(self):
        class Paused:
            def notice(self):
                return "GitHub paused until 09:45 (rate limit; showing its last answer)"
        snap = console.snapshot(self.state(run="run_new"), fake_orca(), lambda r: footer(), self.asks, self.notes,
                                Paused())
        self.assertEqual(console.plain(snap).count("GitHub paused until 09:45"), 1)
        snap = console.snapshot(self.state(run="run_new"), fake_orca(),
                                lambda r: footer(unavailable=[Paused().notice()]), self.asks, self.notes, Paused())
        self.assertEqual(console.plain(snap).count("GitHub paused until 09:45"), 1)

    def test_pause_note(self):
        self.assertEqual(console.pause_note(42), "paused for 42s: redrawn, reading again")
        self.assertEqual(console.pause_note(17 * 60 + 5), "paused for 17 min: redrawn, reading again")


class Resuming(Stores):
    def test_sigcont_redraws_reads_at_once_and_says_how_long(self):
        class Scr(FakeScreen):
            cleared = 0

            def clear(self):
                self.cleared += 1
        s = tui.Screen(Scr(), self.state(), fake_orca(), None, self.asks, self.notes, lambda _: None, 5)
        s.last_tick -= 600
        s.on_continue()
        self.assertTrue(s.wake.is_set())
        # no terminal under the tests
        with mock.patch.object(tui.curses, "reset_prog_mode"), mock.patch.object(tui.curses, "curs_set"):
            s.resume()
        self.assertEqual(s.message, "paused for 10 min: redrawn, reading again")
        self.assertEqual(s.scr.cleared, 1)
        self.assertIsNone(s.resumed)


if __name__ == "__main__":
    unittest.main()
