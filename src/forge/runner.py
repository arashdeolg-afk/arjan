"""Run project code and stream its output.

One process per project. Output is captured as a sequence of numbered
events (``start`` / ``out`` / ``err`` / ``exit``) that the server relays
over Server-Sent Events; the sequence numbers double as SSE event ids so
a reconnecting client resumes where it left off. Reads happen with
``os.read`` rather than line iteration so prompts written without a
trailing newline (``input("> ")``) appear immediately.
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
import threading
import time

MAX_BUFFER = 1_000_000  # total chars of out/err kept for replay
READ_SIZE = 4096


class RunnerError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class RunProcess:
    def __init__(self, argv: list[str], cwd: str, timeout: float | None = None):
        self._cond = threading.Condition()
        self.events: list[dict] = []
        self._next_seq = 0
        self._buffered = 0
        self.done = False
        self.returncode: int | None = None
        self.started = time.time()

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env.setdefault("PYTHONIOENCODING", "utf-8")
        kwargs: dict = {}
        if os.name == "posix":
            kwargs["start_new_session"] = True
        try:
            self.proc = subprocess.Popen(
                argv,
                cwd=cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                env=env,
                **kwargs,
            )
        except (OSError, ValueError) as e:
            raise RunnerError(f"could not start process: {e}")

        self._append("start", {"command": shlex.join(argv), "pid": self.proc.pid})
        self._readers = [
            threading.Thread(target=self._pump, args=(self.proc.stdout, "out"), daemon=True),
            threading.Thread(target=self._pump, args=(self.proc.stderr, "err"), daemon=True),
        ]
        for t in self._readers:
            t.start()
        threading.Thread(target=self._monitor, daemon=True).start()
        if timeout:
            threading.Timer(timeout, self._timeout_kill, args=(timeout,)).start()

    # ------------------------------------------------------------ internals

    def _append(self, kind: str, data: dict) -> None:
        with self._cond:
            event = {"seq": self._next_seq, "kind": kind, "data": data}
            self._next_seq += 1
            self.events.append(event)
            if kind in ("out", "err"):
                self._buffered += len(data.get("text", ""))
                while self._buffered > MAX_BUFFER and self.events:
                    old = self.events.pop(0)
                    if old["kind"] in ("out", "err"):
                        self._buffered -= len(old["data"].get("text", ""))
            self._cond.notify_all()

    def _pump(self, stream, kind: str) -> None:
        fd = stream.fileno()
        while True:
            try:
                chunk = os.read(fd, READ_SIZE)
            except OSError:
                break
            if not chunk:
                break
            self._append(kind, {"text": chunk.decode("utf-8", "replace")})

    def _monitor(self) -> None:
        for t in self._readers:
            t.join()
        rc = self.proc.wait()
        for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            try:
                if stream:
                    stream.close()
            except OSError:
                pass
        with self._cond:
            self.returncode = rc
        self._append("exit", {"code": rc, "seconds": round(time.time() - self.started, 2)})
        with self._cond:
            self.done = True
            self._cond.notify_all()

    def _timeout_kill(self, timeout: float) -> None:
        if self.proc.poll() is None:
            self._append("err", {"text": f"\n[forge] stopped after {timeout:.0f}s timeout\n"})
            self.stop()

    # ------------------------------------------------------------------ api

    @property
    def running(self) -> bool:
        return self.proc.poll() is None

    def write_input(self, text: str) -> None:
        if not self.running or self.proc.stdin is None:
            raise RunnerError("process is not running", 409)
        try:
            self.proc.stdin.write(text.encode("utf-8"))
            self.proc.stdin.flush()
        except (OSError, ValueError):
            raise RunnerError("process is not accepting input", 409)

    def stop(self) -> None:
        if not self.running:
            return
        try:
            if os.name == "posix":
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            else:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(self.proc.pid)],
                    capture_output=True,
                )
        except (ProcessLookupError, PermissionError, OSError):
            pass
        threading.Timer(2.0, self._hard_kill).start()

    def _hard_kill(self) -> None:
        if self.running:
            try:
                if os.name == "posix":
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                else:
                    self.proc.kill()
            except (ProcessLookupError, PermissionError, OSError):
                pass

    def events_since(self, after_seq: int, wait: float = 15.0) -> tuple[list[dict], bool]:
        """Events with seq > after_seq; blocks up to ``wait`` for news."""
        with self._cond:
            evs = [e for e in self.events if e["seq"] > after_seq]
            if not evs and not self.done:
                self._cond.wait(wait)
                evs = [e for e in self.events if e["seq"] > after_seq]
            return evs, self.done

    def state(self) -> dict:
        return {
            "running": self.running,
            "returncode": self.returncode,
            "started": self.started,
        }


class Runner:
    def __init__(self):
        self._lock = threading.Lock()
        self._runs: dict[str, RunProcess] = {}

    def start(self, pid: str, command: str, cwd: str,
              timeout: float | None = None) -> RunProcess:
        command = (command or "").strip()
        if not command:
            raise RunnerError("this project has no run command — set one in "
                              "project settings")
        try:
            argv = shlex.split(command, posix=(os.name == "posix"))
        except ValueError as e:
            raise RunnerError(f"could not parse run command: {e}")
        if not argv:
            raise RunnerError("empty run command")
        if argv[0] in ("python", "python3"):
            argv[0] = sys.executable
        with self._lock:
            old = self._runs.get(pid)
            if old and old.running:
                old.stop()
            run = RunProcess(argv, cwd, timeout=timeout)
            self._runs[pid] = run
            return run

    def get(self, pid: str) -> RunProcess | None:
        with self._lock:
            return self._runs.get(pid)

    def stop(self, pid: str) -> bool:
        run = self.get(pid)
        if run is None or not run.running:
            return False
        run.stop()
        return True

    def stop_all(self) -> None:
        with self._lock:
            runs = list(self._runs.values())
        for run in runs:
            run.stop()
