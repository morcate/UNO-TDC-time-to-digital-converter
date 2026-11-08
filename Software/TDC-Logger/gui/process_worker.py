#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: gui/process_worker.py
Description: Start/stop CLI subprocess and parse NDJSON stdout for the GUI.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gui_protocol import (  # noqa: E402
    STOP_COMMAND,
    T_ERR,
    T_EVT,
    T_LOG,
    T_RAW,
    T_STAT,
    T_TOF,
    parse_gui_line,
)

# Cooperative stop → terminate → kill deadlines (ms)
_STOP_TERMINATE_MS = 1200
_STOP_KILL_MS = 2500


class CliProcessController(QObject):
    """Owns a QProcess running main.py start ... --gui."""

    line_log = Signal(str)
    line_raw = Signal(str)
    tof_value = Signal(float, bool)  # value, in_range
    stats = Signal(dict)
    event = Signal(str, dict)
    error = Signal(str)
    finished = Signal(int)  # exit code
    state_changed = Signal(bool)  # running?
    stop_requested = Signal()  # immediate UI feedback (before process exits)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self._stdout_buf = ""
        self._stderr_buf = ""
        self._stopping = False
        self._proc.readyReadStandardOutput.connect(self._on_stdout)
        self._proc.readyReadStandardError.connect(self._on_stderr)
        self._proc.finished.connect(self._on_finished)
        self._proc.errorOccurred.connect(self._on_proc_error)

        self._term_timer = QTimer(self)
        self._term_timer.setSingleShot(True)
        self._term_timer.timeout.connect(self._escalate_terminate)
        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.timeout.connect(self._escalate_kill)

    def is_running(self) -> bool:
        return self._proc.state() != QProcess.ProcessState.NotRunning

    def is_stopping(self) -> bool:
        return bool(self._stopping)

    def start(self, argv: List[str], workdir: Optional[str] = None) -> None:
        if self.is_running():
            raise RuntimeError("Acquisition already running")
        if len(argv) < 2:
            raise ValueError("argv too short")
        self._cancel_stop_timers()
        self._stopping = False
        program = argv[0]
        args = argv[1:]
        if workdir:
            self._proc.setWorkingDirectory(workdir)
        self._stdout_buf = ""
        self._stderr_buf = ""
        # Ensure stdin is a writable pipe for STOP
        self._proc.setInputChannelMode(QProcess.InputChannelMode.ManagedInputChannel)
        self.state_changed.emit(True)
        self._proc.start(program, args)
        if not self._proc.waitForStarted(5000):
            self.state_changed.emit(False)
            raise RuntimeError(f"Failed to start process: {self._proc.errorString()}")

    def request_stop(self) -> None:
        """
        Non-blocking cooperative STOP, then escalate.

        Must never block the Qt UI thread for seconds.
        """
        if not self.is_running():
            return
        if self._stopping:
            # Second click → kill immediately
            self._escalate_kill()
            return

        self._stopping = True
        self.stop_requested.emit()

        try:
            data = (STOP_COMMAND + "\n").encode("utf-8")
            written = self._proc.write(data)
            if written < 0:
                self.error.emit("Failed to write STOP to CLI stdin")
            # Do not block the UI; flush is best-effort with a tiny wait
            self._proc.waitForBytesWritten(50)
            # Closing write channel delivers EOF → stdin watcher also stops
            try:
                self._proc.closeWriteChannel()
            except Exception:
                pass
        except Exception as exc:
            self.error.emit(f"Failed to send STOP: {exc}")

        # Escalate if graceful path is too slow
        self._term_timer.start(_STOP_TERMINATE_MS)
        self._kill_timer.start(_STOP_KILL_MS)

    def kill(self) -> None:
        self._cancel_stop_timers()
        if self.is_running():
            self._proc.kill()

    def _cancel_stop_timers(self) -> None:
        self._term_timer.stop()
        self._kill_timer.stop()

    def _escalate_terminate(self) -> None:
        if not self.is_running():
            return
        try:
            self.line_log.emit("[gui] STOP slow — terminating CLI process…")
            self._proc.terminate()
        except Exception as exc:
            self.error.emit(f"terminate failed: {exc}")

    def _escalate_kill(self) -> None:
        if not self.is_running():
            return
        try:
            self.line_log.emit("[gui] FORCE KILL CLI process")
            self._proc.kill()
        except Exception as exc:
            self.error.emit(f"kill failed: {exc}")

    def _on_stdout(self) -> None:
        try:
            chunk = bytes(self._proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        except Exception as exc:
            self.error.emit(f"stdout read error: {exc}")
            return
        self._stdout_buf += chunk
        while "\n" in self._stdout_buf:
            line, self._stdout_buf = self._stdout_buf.split("\n", 1)
            line = line.strip("\r")
            if not line:
                continue
            try:
                obj = parse_gui_line(line)
            except ValueError as exc:
                self.error.emit(f"Bad protocol line: {exc} | {line[:120]}")
                continue
            self._dispatch(obj)

    def _on_stderr(self) -> None:
        try:
            chunk = bytes(self._proc.readAllStandardError()).decode("utf-8", errors="replace")
        except Exception as exc:
            self.error.emit(f"stderr read error: {exc}")
            return
        self._stderr_buf += chunk
        while "\n" in self._stderr_buf:
            line, self._stderr_buf = self._stderr_buf.split("\n", 1)
            line = line.strip("\r")
            if line:
                self.line_log.emit(line)

    def _dispatch(self, obj: dict) -> None:
        t = obj.get("t")
        try:
            if t == T_LOG:
                self.line_log.emit(str(obj.get("msg", "")))
            elif t == T_RAW:
                self.line_raw.emit(str(obj.get("line", "")))
            elif t == T_TOF:
                self.tof_value.emit(float(obj["v"]), bool(obj.get("in", True)))
            elif t == T_STAT:
                self.stats.emit(obj)
            elif t == T_EVT:
                name = str(obj.get("name", ""))
                self.event.emit(name, obj)
            elif t == T_ERR:
                self.error.emit(str(obj.get("msg", "unknown error")))
            else:
                self.error.emit(f"Unknown event type: {t!r}")
        except Exception as exc:
            self.error.emit(f"Dispatch error: {exc}")

    def _on_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        self._cancel_stop_timers()
        self._stopping = False
        self.state_changed.emit(False)
        self.finished.emit(int(exit_code))

    def _on_proc_error(self, err: QProcess.ProcessError) -> None:
        # Crashed / failed start — surface once; ignore benign kill noise while stopping
        if self._stopping and err in (
            QProcess.ProcessError.Crashed,
            QProcess.ProcessError.Timedout,
            QProcess.ProcessError.WriteError,
            QProcess.ProcessError.ReadError,
        ):
            return
        self.error.emit(f"Process error: {err.name} — {self._proc.errorString()}")
        if not self.is_running():
            self._cancel_stop_timers()
            self._stopping = False
            self.state_changed.emit(False)
