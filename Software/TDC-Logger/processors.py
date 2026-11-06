#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: processors.py
Version: 1.0.0
Date: 2026-10-26
Author: Gemini
Description: Scalable data processing pipeline and TDC Time-of-Flight register calculator.
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

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from typing import Optional, Deque
import math

from config import SEPCHAR, TDC_CLOCK_FACTOR, EXPECTED_REGISTER_BYTES


@dataclass
class ProcessResult:
    """Data structure representing the outcome of processing a single serial line."""
    is_register_line: bool          # True if line matched register format, False if text/header
    is_valid_in_range: bool         # True if tof < lim_sup (Stop IN)
    computed_value: Optional[float] # Calculated value (e.g., tof)
    formatted_output: Optional[str] # String to write to the parsed log file


class BaseProcessor(ABC):
    """Abstract base class for scalable real-time data processors."""

    def __init__(self, window_size: int = 1):
        self.history_buffer: Deque[float] = deque(maxlen=window_size)
        self.stop_in_count: int = 0
        self.stop_out_count: int = 0
        self.corrupted_count: int = 0

    @abstractmethod
    def process_line(self, raw_line: str) -> ProcessResult:
        """Processes a raw string line and returns a ProcessResult."""
        pass


class TdcProcessor(BaseProcessor):
    """
    Parses 9 space-separated register bytes (3x 24-bit registers: time, cal1, cal2),
    computes Time-of-Flight (ToF), and filters against an upper threshold (lim_sup).
    """

    def __init__(self, lim_sup: Optional[float] = None, window_size: int = 1):
        super().__init__(window_size=window_size)
        self.lim_sup: float = lim_sup if lim_sup is not None else math.inf

    def process_line(self, raw_line: str) -> ProcessResult:
        # Split using SEPCHAR (ASCII 32 space); filter out accidental empty tokens from multiple spaces
        tokens = [t for t in raw_line.strip().split(SEPCHAR) if t]

        # Discriminate between text prompts (e.g., "Press any key to start") and register lines
        if len(tokens) < EXPECTED_REGISTER_BYTES:
            return ProcessResult(
                is_register_line=False,
                is_valid_in_range=False,
                computed_value=None,
                formatted_output=None,
            )

        # Verify that the first 9 tokens are valid integers (handles negative sign if any)
        try:
            b = [int(tokens[i]) for i in range(EXPECTED_REGISTER_BYTES)]
        except ValueError:
            # Line has >= 9 words, but they are text words rather than numerical registers
            return ProcessResult(
                is_register_line=False,
                is_valid_in_range=False,
                computed_value=None,
                formatted_output=None,
            )

        # Reconstruct 24-bit registers: (MSB * 65536) + (MID * 256) + LSB
        raw_time = (b[0] * 65536) + (b[1] * 256) + b[2]
        raw_cal1 = (b[3] * 65536) + (b[4] * 256) + b[5]
        raw_cal2 = (b[6] * 65536) + (b[7] * 256) + b[8]

        cal_diff = raw_cal2 - raw_cal1

        # Guard against division by zero or corrupted negative calibration delta
        if cal_diff <= 0:
            self.corrupted_count += 1
            return ProcessResult(
                is_register_line=True,
                is_valid_in_range=False,
                computed_value=None,
                formatted_output=None,
            )

        # Compute Time-of-Flight (tof)
        tof = float(raw_time * TDC_CLOCK_FACTOR) / float(cal_diff)

        # Range filtering: valid in-range measurement if 0 <= tof < lim_sup
        if 0.0 <= tof < self.lim_sup:
            self.stop_in_count += 1
            self.history_buffer.append(tof)
            return ProcessResult(
                is_register_line=True,
                is_valid_in_range=True,
                computed_value=tof,
                formatted_output=f"{tof:.3f}",
            )
        else:
            self.stop_out_count += 1
            return ProcessResult(
                is_register_line=True,
                is_valid_in_range=False,
                computed_value=tof,
                formatted_output=None,
            )