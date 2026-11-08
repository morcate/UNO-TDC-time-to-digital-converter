#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: stdin_stop.py
Version: 1.0.0
Date: 2026-11-08
Description: Cooperative STOP watcher on stdin for CLI --gui mode.

License: GPLv3-or-later (see project headers).
"""

from __future__ import annotations

import sys
import threading
from typing import Callable, Optional

from gui_protocol import STOP_COMMAND


class StdinStopWatcher:
    """
    Background thread: read stdin lines; on STOP_COMMAND call on_stop().

    Used so the GUI can write STOP\\n to the CLI subprocess stdin.
    """

    def __init__(self, on_stop: Callable[[], None]) -> None:
        self._on_stop = on_stop
        self._thread: Optional[threading.Thread] = None
        self._stop_local = threading.Event()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_local.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="tdc-stdin-stop",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_local.set()

    def _run(self) -> None:
        try:
            while not self._stop_local.is_set():
                line = sys.stdin.readline()
                if line == "":
                    # EOF: parent closed stdin — treat as stop request
                    try:
                        self._on_stop()
                    except Exception as exc:
                        print(f"[stdin_stop] on_stop error: {exc}", file=sys.stderr, flush=True)
                    break
                if line.strip().upper() == STOP_COMMAND:
                    try:
                        self._on_stop()
                    except Exception as exc:
                        print(f"[stdin_stop] on_stop error: {exc}", file=sys.stderr, flush=True)
                    break
        except Exception as exc:
            print(f"[stdin_stop] reader failed: {exc}", file=sys.stderr, flush=True)
            try:
                self._on_stop()
            except Exception as exc2:
                print(f"[stdin_stop] on_stop after failure: {exc2}", file=sys.stderr, flush=True)
