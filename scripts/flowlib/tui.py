"""The console's curses screen. The data and the actions live in flowlib.console; this is drawing and keys.

A reader thread refreshes the snapshot so a slow `gh` or `orca` call never freezes the keyboard; the
screen redraws twice a second from the newest snapshot it has.
"""

from __future__ import annotations

import curses
import threading

from . import console

# -1 is the terminal's own foreground, so text follows the theme (light or dark) instead of palette white/black.
COLOURS = {"title": (curses.COLOR_CYAN, curses.A_BOLD), "head": (-1, curses.A_BOLD),
           "warn": (curses.COLOR_YELLOW, curses.A_BOLD), "dim": (-1, curses.A_DIM),
           "keys": (-1, curses.A_REVERSE), "": (-1, 0)}


def run(state: dict, runner, read_status, asks_file, notes_file, save, interval: float = console.REFRESH) -> None:
    curses.wrapper(lambda scr: Screen(scr, state, runner, read_status, asks_file, notes_file, save, interval).loop())


class Screen:
    def __init__(self, scr, state, runner, read_status, asks_file, notes_file, save, interval):
        self.scr, self.state, self.runner = scr, state, runner
        self.args = (read_status, asks_file, notes_file)
        self.save, self.interval = save, interval
        self.snap = None
        self.message = "reading…"
        self.mode = "main"
        self.log: list = []
        self.top = 0
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.attrs = {}

    # -- the reader -----------------------------------------------------------

    def reader(self):
        while not self.stop.is_set():
            try:
                snap = console.snapshot(self.state, self.runner, *self.args)
                self.save(self.state)
                with self.lock:
                    self.snap = snap
                    if self.message in ("reading…", "refreshing…"):
                        self.message = ""
            except Exception as exc:  # noqa: BLE001 - keep reading; say what broke
                with self.lock:
                    self.message = f"read failed: {type(exc).__name__}: {exc}"
            self.wake.wait(self.interval)
            self.wake.clear()

    # -- drawing --------------------------------------------------------------

    def setup(self):
        curses.curs_set(0)
        curses.use_default_colors()
        for i, (name, (fg, attr)) in enumerate(COLOURS.items(), 1):
            try:
                curses.init_pair(i, fg, -1)
                self.attrs[name] = curses.color_pair(i) | attr
            except curses.error:  # a terminal without colours
                self.attrs[name] = attr
        self.scr.timeout(500)

    def lines(self, width):
        if self.mode == "log":
            out = [("Coordinator conversation (newest last) · [l] or Esc to go back", "title"), ("", "")]
            for role, text in self.log:
                out.append((role, "head"))
                out.extend((l, "") for l in console._wrap(text, width))
            return out
        with self.lock:
            snap = self.snap
        if snap is None:
            return [(f"flow · {self.state['spec']} · reading…", "title")]
        return console.frame(snap, width)

    def draw(self):
        self.scr.erase()
        h, w = self.scr.getmaxyx()
        body = self.lines(w - 1)
        self.top = max(0, min(self.top, len(body) - (h - 1)))
        for row, (text, style) in enumerate(body[self.top:self.top + h - 1]):
            self.put(row, text, self.attrs.get(style, 0), w)
        bar = self.message or console.KEYS
        self.put(h - 1, bar.ljust(w - 1), self.attrs.get("keys", 0), w)
        self.scr.refresh()

    def put(self, row, text, attr, width):
        try:
            self.scr.addnstr(row, 0, text, width - 1, attr)
        except curses.error:  # the bottom-right cell, or a screen resized mid-draw
            pass

    def ask_line(self, label: str):
        """A one-line editor on the bottom row; None on Esc."""
        h, w = self.scr.getmaxyx()
        self.scr.timeout(-1)
        curses.curs_set(1)
        buf = ""
        try:
            while True:
                shown = (label + buf)[-(w - 2):]
                self.put(h - 1, shown.ljust(w - 1), self.attrs.get("keys", 0), w)
                self.scr.move(h - 1, min(len(shown), w - 2))
                self.scr.refresh()
                ch = self.scr.get_wch()
                if ch in ("\n", "\r", curses.KEY_ENTER):
                    return buf
                if ch == "\x1b":
                    return None
                if ch in ("\x7f", "\b", curses.KEY_BACKSPACE):
                    buf = buf[:-1]
                elif ch == "\x15":  # Ctrl+U clears the line
                    buf = ""
                elif isinstance(ch, str) and ch.isprintable():
                    buf += ch
        finally:
            curses.curs_set(0)
            self.scr.timeout(500)

    # -- keys -----------------------------------------------------------------

    def loop(self):
        self.setup()
        threading.Thread(target=self.reader, daemon=True).start()
        try:
            while True:
                self.draw()
                ch = self.scr.getch()
                if ch == -1 or ch == curses.KEY_RESIZE:
                    continue
                if not self.key(ch):
                    return
        finally:
            self.stop.set()
            self.wake.set()

    def key(self, ch) -> bool:
        """Handle one key; False quits."""
        h, _ = self.scr.getmaxyx()
        c = chr(ch) if 0 <= ch < 256 else ""
        if c == "q":
            return False
        if ch in (curses.KEY_DOWN, ord("j")):
            self.top += 1
        elif ch in (curses.KEY_UP, ord("k")):
            self.top = max(0, self.top - 1)
        elif ch == curses.KEY_NPAGE or c == " ":
            self.top += h - 2
        elif ch == curses.KEY_PPAGE:
            self.top = max(0, self.top - (h - 2))
        elif self.mode == "log" and c in ("l", "\x1b"):
            self.mode, self.top = "main", 0
        elif c == "l":
            self.message = "reading the conversation…"
            self.draw()
            self.log = console.read_log(self.state.get("session"), self.runner)
            self.mode, self.message = "log", ""
            self.top = 10 ** 6  # clamped in draw: open at the newest entry
        elif c == "r":
            text = self.ask_line("Reply to the coordinator (Enter sends, Esc cancels): ")
            self.message = "cancelled" if text is None else console.send(self.state, self.runner, text)
            self.wake.set()
        elif c.isdigit() and c != "0":
            with self.lock:
                asks = list(self.snap["asks"]) if self.snap else []
            n = int(c)
            if n > len(asks):
                self.message = f"no ask {n}"
            else:
                ask = asks[n - 1]
                text = self.ask_line(f"Answer {n} [{ask['id']}]: ")
                self.message = ("cancelled" if text is None
                                else console.send(self.state, self.runner, console.answer_text(ask, text)))
                self.wake.set()
        elif c == "o":
            self.message = console.show_in_orca(self.state, self.runner)
        elif c in ("R",):
            self.message = "refreshing…"
            self.wake.set()
        else:
            self.message = ""
        return True
