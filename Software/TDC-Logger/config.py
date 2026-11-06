#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: config.py
Version: 1.2.0
Date: 2026-10-27
Author: Gemini
Description: Configuration constants and ANSI terminal colors for the serial TDC logger.
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
import sys

# Enable native ANSI escape sequences on Windows 10/11 consoles
if sys.platform == "win32":
    os.system("")


class TermColors:
    """ANSI escape codes for colorized terminal output."""
    RESET: str = "\033[0m"
    BOLD: str = "\033[1m"
    CYAN: str = "\033[96m"       # Serial text prompts, headers, and stream lines
    GREEN: str = "\033[92m"      # Valid in-range measurements (Stop IN) & success info
    YELLOW: str = "\033[93m"     # Out-of-range measurements (Stop OUT), warnings & TX
    RED: str = "\033[91m"        # Errors and corrupted register frames
    MAGENTA: str = "\033[95m"    # CERN ROOT statistics (Mean, Sigma)
    BLUE: str = "\033[94m"       # Configuration headers and file paths


# Serial Port Defaults
DEFAULT_BAUD_RATE: int = 38400
SERIAL_TIMEOUT_SEC: float = 0.1

# Data Parsing & TDC Math Constants
SEPCHAR: str = chr(32)  # ASCII 32 (Space)
TDC_CLOCK_FACTOR: float = 562.5
EXPECTED_REGISTER_BYTES: int = 9

# Disk I/O and Buffering Settings
RAW_FLUSH_EVERY_N: int = 1         # Flush raw file on every line to prevent data loss
PARSED_BUFFER_SIZE: int = 50       # Flush parsed file every 50 valid measurements
FSYNC_INTERVAL_SEC: float = 1.0    # Force OS-level disk synchronization interval

# USB Vendor IDs (VID) for Arduino auto-detection heuristics
ARDUINO_OFFICIAL_VIDS = {
    0x2341,  # Arduino SA
    0x2A03,  # Dog Hunter AG (Arduino.org)
}

COMMON_USB_UART_VIDS = {
    0x1A86,  # QinHeng Electronics (CH340/CH341)
    0x0403,  # FTDI (FT232R)
    0x10C4,  # Silicon Labs (CP210x)
    0x067B,  # Prolific (PL2303)
}