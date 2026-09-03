"""Runner tests: streamed output, stdin, stop, and event replay."""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from forge.runner import Runner, RunnerError  # noqa: E402


def collect(run, deadline=10.0):
    """Drain events until the run finishes (or the deadline passes)."""
    events, last = [], -1
    end = time.time() + deadline
    while time.time() < end:
        new, done = run.events_since(last, wait=0.25)
        events.extend(new)
        if new:
            last = new[-1]["seq"]
        if done and not new:
            return events
    raise AssertionError(f"run did not finish; events so far: {events}")


def text_of(events, kind):
    return "".join(e["data"].get("text", "") for e in events if e["kind"] == kind)


class TestRunner(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.runner = Runner()

    def tearDown(self) -> None:
        self.runner.stop_all()
        self.tmp.cleanup()

    def start(self, code, **kw):
        return self.runner.start("proj", f'python3 -c "{code}"', self.tmp.name, **kw)

    def test_stdout_stderr_and_exit_code(self):
        run = self.start("import sys; print('to out'); "
                         "print('to err', file=sys.stderr); sys.exit(3)")
        events = collect(run)
        self.assertIn("to out", text_of(events, "out"))
        self.assertIn("to err", text_of(events, "err"))
        exits = [e for e in events if e["kind"] == "exit"]
        self.assertEqual(len(exits), 1)
        self.assertEqual(exits[0]["data"]["code"], 3)
        self.assertEqual(run.returncode, 3)

    def test_start_event_carries_command(self):
        run = self.start("pass")
        events = collect(run)
        self.assertEqual(events[0]["kind"], "start")
        self.assertIn("-c", events[0]["data"]["command"])

    def test_stdin_reaches_the_program(self):
        run = self.start("name = input(); print(f'hi {name}!')")
        deadline = time.time() + 5
        while time.time() < deadline:  # wait until the process is up
            if run.running:
                break
            time.sleep(0.05)
        run.write_input("forge\n")
        events = collect(run)
        self.assertIn("hi forge!", text_of(events, "out"))

    def test_prompt_without_newline_is_streamed(self):
        run = self.start("input('type here > ')")
        deadline = time.time() + 5
        seen = ""
        while time.time() < deadline and "type here >" not in seen:
            new, _done = run.events_since(-1, wait=0.25)
            seen = text_of(new, "out")
        self.assertIn("type here >", seen)
        run.write_input("done\n")
        collect(run)

    def test_stop_kills_a_long_run(self):
        run = self.start("import time; print('sleeping'); time.sleep(60)")
        deadline = time.time() + 5
        while time.time() < deadline:
            new, _done = run.events_since(-1, wait=0.25)
            if "sleeping" in text_of(new, "out"):
                break
        self.assertTrue(self.runner.stop("proj"))
        events = collect(run)
        exits = [e for e in events if e["kind"] == "exit"]
        self.assertEqual(len(exits), 1)
        self.assertNotEqual(exits[0]["data"]["code"], 0)

    def test_timeout_stops_the_run(self):
        run = self.start("import time; time.sleep(60)", timeout=0.5)
        events = collect(run)
        self.assertIn("timeout", text_of(events, "err"))

    def test_new_run_replaces_old_one(self):
        first = self.start("import time; time.sleep(60)")
        second = self.start("print('second')")
        self.assertIs(self.runner.get("proj"), second)
        events = collect(second)
        self.assertIn("second", text_of(events, "out"))
        collect(first)  # the replaced run must also reach its exit event

    def test_replay_from_seq(self):
        run = self.start("print('a'); print('b')")
        collect(run)
        replayed, done = run.events_since(0, wait=0)
        self.assertTrue(done)
        self.assertTrue(all(e["seq"] > 0 for e in replayed))
        self.assertIn("exit", [e["kind"] for e in replayed])

    def test_empty_and_bad_commands_rejected(self):
        with self.assertRaises(RunnerError):
            self.runner.start("proj", "", self.tmp.name)
        with self.assertRaises(RunnerError):
            self.runner.start("proj", "   ", self.tmp.name)
        with self.assertRaises(RunnerError):
            self.runner.start("proj", 'python3 "unclosed', self.tmp.name)

    def test_missing_binary_is_a_runner_error(self):
        with self.assertRaises(RunnerError):
            self.runner.start("proj", "definitely-not-a-real-binary-xyz",
                              self.tmp.name)

    def test_input_after_exit_is_rejected(self):
        run = self.start("pass")
        collect(run)
        with self.assertRaises(RunnerError):
            run.write_input("late")


if __name__ == "__main__":
    unittest.main()
