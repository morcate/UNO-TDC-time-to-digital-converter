#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: hist_config.py
Version: 2.0.0
Date: 2026-11-06
Author: Gemini
Description: Graphical style and dynamic rebinning configuration for real-time ROOT histograms.
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

from typing import Tuple

# ---------------------------------------------------------------------------
# Rebinning policy (ROOT-style: rebuild + refill from the unbinned sample)
# ---------------------------------------------------------------------------
# Minimum entries required in occupied bins inside the core window
# [mean ± CORE_SIGMA_MULTIPLIER * sigma]. Less-populated shoulder bins should
# generally stay at or above this threshold (ROOT-practical occupancy).
MIN_COUNTS_PER_BIN: int = 10

# Core half-width in units of Std Dev used by the occupancy policy.
CORE_SIGMA_MULTIPLIER: float = 2.0

# Coarse bin count used only while N is still below ~2 * MIN_COUNTS_PER_BIN.
INITIAL_BINS: int = 10

# Hard ceiling on the number of uniform bins after the occupancy constraint.
MAX_BINS: int = 50

# How often the histogram is fully rebuilt and the GUI is refreshed.
REBIN_INTERVAL_SEC: float = 0.5

# Fractional padding applied to [x_min, x_max] when setting the live X axis
# and the histogram range (keeps extreme samples inside the outer bins).
AXIS_X_MARGIN_FRACTION: float = 0.02

# Y-axis headroom above the tallest bin (1.15 => 15% free space on top).
AXIS_Y_HEADROOM: float = 1.15

# ---------------------------------------------------------------------------
# Figure and high-resolution export
# ---------------------------------------------------------------------------
FIG_SIZE: Tuple[float, float] = (10.0, 6.0)
GUI_DPI: int = 100
SAVE_DPI: int = 600
SAVE_FORMAT: str = "png"  # 'png' | 'pdf' | 'svg'

# ---------------------------------------------------------------------------
# Histogram line / fill style (ROOT-like step histogram)
# ---------------------------------------------------------------------------
HIST_STYLE: str = "stepfilled"  # 'step' or 'stepfilled'
HIST_LINE_COLOR: str = "#003366"
HIST_LINE_WIDTH: float = 1.8
HIST_LINE_STYLE: str = "-"
HIST_FILL_COLOR: str = "#6699CC"
HIST_FILL_ALPHA: float = 0.35

# ---------------------------------------------------------------------------
# Bin-center markers
# ---------------------------------------------------------------------------
SHOW_MARKERS: bool = True
MARKER_SYMBOL: str = "o"
MARKER_SIZE: float = 4.5
MARKER_FACE_COLOR: str = "#CC0000"
MARKER_EDGE_COLOR: str = "#800000"
MARKER_EDGE_WIDTH: float = 1.0

# ---------------------------------------------------------------------------
# Axes, grid, labels (English)
# ---------------------------------------------------------------------------
PLOT_TITLE: str = "Time-of-Flight (ToF) Distribution"
X_AXIS_LABEL: str = "ToF [ns]"
Y_AXIS_LABEL: str = "Counts / bin"
SHOW_GRID: bool = True
GRID_COLOR: str = "#CCCCCC"
GRID_LINE_STYLE: str = "--"
GRID_LINE_WIDTH: float = 0.6
GRID_ALPHA: float = 0.7

# ---------------------------------------------------------------------------
# ROOT TPaveStats-style box
# ---------------------------------------------------------------------------
SHOW_STATS_BOX: bool = True
STATS_BOX_BG_COLOR: str = "#FFFFFF"
STATS_BOX_EDGE_COLOR: str = "#000000"
STATS_BOX_ALPHA: float = 0.9
STATS_FONT_SIZE: int = 10
