#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: gui_protocol.py
Version: 1.0.0
Date: 2026-11-08
Description: NDJSON protocol between TDC-Logger CLI (--gui) and the desktop GUI.

Protocol version 1: one UTF-8 JSON object per line on stdout.
Human-readable diagnostics go to stderr when --gui is active.

License: GPLv3-or-later (see project headers).
"""

from __future__ import annotations

import json
import sys
import threading
import time
from typing import Any, Dict, Optional, TextIO


PROTOCOL_VERSION: int = 1

# Event type tags
T_LOG = "log"
T_RAW = "raw"
T_TOF = "tof"
T_STAT = "stat"
T_EVT = "evt"
T_ERR = "err"

# Lifecycle event names
EVT_STARTING = "starting"
EVT_ARMED = "armed"
EVT_RUNNING = "running"
EVT_STOPPING = "stopping"
EVT_FINISHED = "finished"

# Cooperative stop line on CLI stdin (plain text, one line)
STOP_COMMAND: str = "STOP"


class GuiStreamEmitter:
    """
    Thread-safe NDJSON writer for CLI --gui mode.

    - stdout: machine protocol only
    - Optional rate limit for 'stat' messages
    - 'tof' is emitted per sample (UART <= ~1 kHz is acceptable)
    """

    def __init__(
        self,
        out: Optional[TextIO] = None,
        stat_interval_sec: float = 0.34,
    ) -> None:
        self._out: TextIO = out if out is not None else sys.stdout
        self._lock = threading.Lock()
        self._stat_interval = max(0.05, float(stat_interval_sec))
        self._last_stat_mono: float = 0.0
        self._closed = False

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def _emit(self, payload: Dict[str, Any]) -> None:
        payload = dict(payload)
        payload.setdefault("v", PROTOCOL_VERSION)
        try:
            line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            # Never fail silently: report protocol encoding errors on stderr
            print(f"[gui_protocol] encode error: {exc}", file=sys.stderr, flush=True)
            return
        with self._lock:
            if self._closed:
                return
            try:
                self._out.write(line + "\n")
                self._out.flush()
            except OSError as exc:
                print(f"[gui_protocol] stdout write failed: {exc}", file=sys.stderr, flush=True)

    def log(self, msg: str) -> None:
        self._emit({"t": T_LOG, "msg": str(msg)})

    def raw(self, line: str) -> None:
        self._emit({"t": T_RAW, "line": str(line)})

    def tof(self, value: float, *, in_range: bool) -> None:
        self._emit({"t": T_TOF, "v": float(value), "in": bool(in_range)})

    def stat(
        self,
        *,
        stop_in: int,
        stop_out: int,
        corrupted: int = 0,
        elapsed_s: float = 0.0,
        mean: Optional[float] = None,
        sigma: Optional[float] = None,
        force: bool = False,
    ) -> None:
        now = time.monotonic()
        if not force and (now - self._last_stat_mono) < self._stat_interval:
            return
        self._last_stat_mono = now
        body: Dict[str, Any] = {
            "t": T_STAT,
            "in": int(stop_in),
            "out": int(stop_out),
            "bad": int(corrupted),
            "elapsed_s": float(elapsed_s),
        }
        if mean is not None:
            body["mean"] = float(mean)
        if sigma is not None:
            body["sigma"] = float(sigma)
        self._emit(body)

    def evt(self, name: str, **extra: Any) -> None:
        body: Dict[str, Any] = {"t": T_EVT, "name": str(name)}
        body.update(extra)
        self._emit(body)

    def err(self, msg: str, code: Optional[str] = None) -> None:
        body: Dict[str, Any] = {"t": T_ERR, "msg": str(msg)}
        if code is not None:
            body["code"] = str(code)
        self._emit(body)


def parse_gui_line(line: str) -> Dict[str, Any]:
    """
    Parse one NDJSON protocol line from CLI stdout.

    Raises ValueError if the line is not valid protocol JSON.
    """
    text = line.strip()
    if not text:
        raise ValueError("empty protocol line")
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise ValueError("protocol line must be a JSON object")
    if "t" not in obj:
        raise ValueError("protocol object missing 't'")
    return obj


def configure_stdio_for_gui() -> None:
    """Best-effort line buffering for stdout/stderr under --gui."""
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except Exception as exc:
        print(f"[gui_protocol] stdout reconfigure failed: {exc}", file=sys.stderr, flush=True)
    try:
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except Exception as exc:
        print(f"[gui_protocol] stderr reconfigure failed: {exc}", file=sys.stderr, flush=True)
