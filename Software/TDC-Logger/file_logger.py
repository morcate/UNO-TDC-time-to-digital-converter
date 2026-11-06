#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: file_logger.py
Version: 1.0.0
Date: 2026-10-26
Author: Gemini
Description: Directory and dual-file (raw and parsed) buffered logger with OS-level fsync.
Requirements: Python 3.8+
Installation: Place in the root directory of the serial_logger project.

License:
This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from config import RAW_FLUSH_EVERY_N, PARSED_BUFFER_SIZE, FSYNC_INTERVAL_SEC


class DualFileLogger:
    """
    Manages the output folder ./<NAME>/ and handles safe writing to:
    - ./<NAME>/<NAME>_raw.log (all serial traffic, frequent flush)
    - ./<NAME>/<NAME>.log (valid parsed measurements, buffered write)
    """

    def __init__(self, base_name: Optional[str], use_timestamp: bool, enable_parsed: bool = True):
        self.use_timestamp = use_timestamp
        self.enable_parsed = enable_parsed

        # Determine base name and strip any user-supplied extension (.log, .txt)
        if base_name:
            clean_name = Path(base_name).stem
        else:
            clean_name = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Use base name if available; otherwise append incremental index (_1, _2, ...)
        if (Path.cwd() / clean_name).exists():
            idx = 1
            while (Path.cwd() / f"{clean_name}_{idx}").exists():
                idx += 1
            clean_name = f"{clean_name}_{idx}"

        self.folder_path = Path.cwd() / clean_name
        self.folder_path.mkdir(parents=True, exist_ok=True)

        self.raw_file_path = self.folder_path / f"{clean_name}_raw.log"
        self.parsed_file_path = self.folder_path / f"{clean_name}.log"

        self._raw_file = open(self.raw_file_path, mode="a", encoding="utf-8")
        self._parsed_file = (
            open(self.parsed_file_path, mode="a", encoding="utf-8")
            if self.enable_parsed
            else None
        )

        self._raw_counter = 0
        self._parsed_buffer: List[str] = []
        self._last_fsync_time = time.monotonic()

    @staticmethod
    def _get_timestamp_prefix() -> str:
        """Returns ISO-like timestamp with millisecond precision."""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + " "

    def log_raw(self, line: str, is_measurement: bool = True) -> None:
        """Writes a line to <NAME>_raw.log and forces immediate flush."""
        prefix = self._get_timestamp_prefix() if (self.use_timestamp and is_measurement) else ""
        self._raw_file.write(f"{prefix}{line}\n")
        self._raw_counter += 1

        if self._raw_counter >= RAW_FLUSH_EVERY_N:
            self._raw_file.flush()
            self._raw_counter = 0
            self._check_fsync()

    def log_parsed(self, formatted_value: str) -> None:
        """Buffers valid calculated measurements and writes them to <NAME>.log."""
        if not self._parsed_file:
            return

        self._parsed_buffer.append(f"{formatted_value}\n")

        if len(self._parsed_buffer) >= PARSED_BUFFER_SIZE:
            self.flush_parsed()

    def flush_parsed(self) -> None:
        """Flushes the in-memory parsed measurement buffer to disk."""
        if self._parsed_file and self._parsed_buffer:
            self._parsed_file.writelines(self._parsed_buffer)
            self._parsed_file.flush()
            self._parsed_buffer.clear()
            self._check_fsync()

    def _check_fsync(self) -> None:
        """Periodically forces OS disk synchronization to prevent data loss on power failure."""
        now = time.monotonic()
        if (now - self._last_fsync_time) >= FSYNC_INTERVAL_SEC:
            os.fsync(self._raw_file.fileno())
            if self._parsed_file:
                os.fsync(self._parsed_file.fileno())
            self._last_fsync_time = now

    def close(self) -> None:
        """Flushes all remaining buffers, syncs to disk, and closes file descriptors."""
        try:
            self.flush_parsed()
            if self._raw_file and not self._raw_file.closed:
                self._raw_file.flush()
                os.fsync(self._raw_file.fileno())
                self._raw_file.close()
            if self._parsed_file and not self._parsed_file.closed:
                self._parsed_file.flush()
                os.fsync(self._parsed_file.fileno())
                self._parsed_file.close()
        except Exception:
            pass