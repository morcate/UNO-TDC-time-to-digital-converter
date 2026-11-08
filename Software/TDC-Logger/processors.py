#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: processors.py
Version: 2.0.0
Date: 2026-11-07
Author: Gemini
Description: TDC Time-of-Flight parsers for firmware measurement modes 1 and 2.
Requirements: Python 3.8+
Installation: Place in the root directory of the TDC-Logger project.

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
from typing import Deque, List, Optional
import math

from config import (
    DEFAULT_MEASUREMENT_MODE,
    MODE1_REGISTER_BYTES,
    MODE2_REGISTER_BYTES,
    SEPCHAR,
    TDC_CLOCK_FACTOR,
    TDC_CLK_PERIOD_NS,
    TDC_MODE2_NORM_FACTOR,
)


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


def _u24(msb: int, mid: int, lsb: int) -> int:
    """Rebuild a 24-bit unsigned value from three bytes (MSB first on the wire)."""
    return (int(msb) * 65536) + (int(mid) * 256) + int(lsb)


class TdcProcessor(BaseProcessor):
    """
    Firmware v2 register-line parser.

    Mode 1 (9 ints):  time1[3] cal1[3] cal2[3]
        tof = time1 * TDC_CLOCK_FACTOR / (cal2 - cal1)

    Mode 2 (15 ints): time1[3] clock_count1[3] time2[3] cal1[3] cal2[3]
        tof = TDC_CLK_PERIOD_NS * cc1
            + TDC_MODE2_NORM_FACTOR * (time1 - time2) / (cal2 - cal1)

    Mode is fixed for the session (CLI --mode); it does not change mid-run.
    """

    def __init__(
        self,
        lim_sup: Optional[float] = None,
        window_size: int = 1,
        mode: int = DEFAULT_MEASUREMENT_MODE,
    ):
        super().__init__(window_size=window_size)
        if mode not in (1, 2):
            raise ValueError(f"measurement mode must be 1 or 2, got {mode}")
        self.mode: int = int(mode)
        self.lim_sup: float = lim_sup if lim_sup is not None else math.inf
        self.expected_tokens: int = (
            MODE1_REGISTER_BYTES if self.mode == 1 else MODE2_REGISTER_BYTES
        )

    def process_line(self, raw_line: str) -> ProcessResult:
        tokens = [t for t in raw_line.strip().split(SEPCHAR) if t]

        # Text / banner / errors: not enough numeric fields for this mode
        if len(tokens) < self.expected_tokens:
            return ProcessResult(
                is_register_line=False,
                is_valid_in_range=False,
                computed_value=None,
                formatted_output=None,
            )

        try:
            b = [int(tokens[i]) for i in range(self.expected_tokens)]
        except ValueError:
            return ProcessResult(
                is_register_line=False,
                is_valid_in_range=False,
                computed_value=None,
                formatted_output=None,
            )

        if self.mode == 1:
            tof = self._tof_mode1(b)
        else:
            tof = self._tof_mode2(b)

        if tof is None:
            self.corrupted_count += 1
            return ProcessResult(
                is_register_line=True,
                is_valid_in_range=False,
                computed_value=None,
                formatted_output=None,
            )

        if 0.0 <= tof < self.lim_sup:
            self.stop_in_count += 1
            self.history_buffer.append(tof)
            return ProcessResult(
                is_register_line=True,
                is_valid_in_range=True,
                computed_value=tof,
                formatted_output=f"{tof:.3f}",
            )

        self.stop_out_count += 1
        return ProcessResult(
            is_register_line=True,
            is_valid_in_range=False,
            computed_value=tof,
            formatted_output=None,
        )

    @staticmethod
    def _tof_mode1(b: List[int]) -> Optional[float]:
        raw_time = _u24(b[0], b[1], b[2])
        raw_cal1 = _u24(b[3], b[4], b[5])
        raw_cal2 = _u24(b[6], b[7], b[8])
        cal_diff = raw_cal2 - raw_cal1
        if cal_diff <= 0:
            return None
        return float(raw_time * TDC_CLOCK_FACTOR) / float(cal_diff)

    @staticmethod
    def _tof_mode2(b: List[int]) -> Optional[float]:
        raw_time1 = _u24(b[0], b[1], b[2])
        raw_cc1 = _u24(b[3], b[4], b[5])
        raw_time2 = _u24(b[6], b[7], b[8])
        raw_cal1 = _u24(b[9], b[10], b[11])
        raw_cal2 = _u24(b[12], b[13], b[14])
        cal_diff = raw_cal2 - raw_cal1
        if cal_diff <= 0:
            return None
        # Matches firmware printData2 EASYDATA formula
        fine = (TDC_MODE2_NORM_FACTOR * float(raw_time1 - raw_time2)) / float(cal_diff)
        return (TDC_CLK_PERIOD_NS * float(raw_cc1)) + fine
