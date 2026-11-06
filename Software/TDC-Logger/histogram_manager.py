#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: histogram_manager.py
Version: 2.0.0
Date: 2026-11-06
Author: Gemini
Description: Real-time ROOT-style histogram with full rebin-from-scratch and live axis rescaling.
Requirements: numpy>=1.24.0, matplotlib>=3.7.0
Installation: pip install numpy matplotlib

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

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np

import hist_config as hc


class RootHistogramManager:
    """
    Live histogram manager following CERN ROOT TH1 conventions:

    - Unbinned accumulators fTsumw / fTsumwx / fTsumwx2 for Mean and Std Dev
      (same formulas as TH1::Fill + TH1::GetMean / TH1::GetStdDev with unit weights).
    - Rebinning always rebuilds the histogram from scratch: new edges are chosen,
      then every stored measurement is filled again into the new bins (no in-place
      merge of existing bin contents).
    - Live axis rescaling: X and Y limits track the data range and bin heights.
    - Binning policy: choose the finest uniform binning such that occupied bins
      generally hold at least MIN_COUNTS_PER_BIN entries (default 10).
    """

    def __init__(self, output_folder: Path, base_name: str, enable_gui: bool = False):
        self.enable_gui = enable_gui
        self.image_path = output_folder / f"{base_name}_hist.{hc.SAVE_FORMAT}"

        # Raw unbinned sample storage (source of truth for every full rebuild)
        self._data: List[float] = []

        # CERN ROOT TH1 unbinned accumulators (unit weight w_i = 1)
        self.fTsumw: float = 0.0
        self.fTsumwx: float = 0.0
        self.fTsumwx2: float = 0.0
        self.mean: float = 0.0
        self.sigma: float = 0.0

        # Last successful binning state (after a full refill)
        self.current_nbins: int = 0
        self._last_counts: Optional[np.ndarray] = None
        self._last_edges: Optional[np.ndarray] = None
        self._x_range: Tuple[float, float] = (0.0, 1.0)
        self._y_max: float = 1.0

        self._last_rebin_time: float = 0.0
        self._dirty: bool = False

        self.fig: Optional[plt.Figure] = None
        self.ax: Optional[plt.Axes] = None

        if self.enable_gui:
            plt.ion()
            self.fig, self.ax = plt.subplots(figsize=hc.FIG_SIZE, dpi=hc.GUI_DPI)
            if self.fig.canvas.manager is not None:
                self.fig.canvas.manager.set_window_title(f"Real-Time Histogram - {base_name}")
            self._setup_axes_style()
            self.fig.tight_layout()
            self.fig.show()
            self.fig.canvas.flush_events()

    # ------------------------------------------------------------------ stats
    @staticmethod
    def compute_root_stats_from_array(arr: np.ndarray) -> Tuple[float, float, float, float, float]:
        """
        Compute statistics strictly following CERN ROOT TH1 (unit weights):

            fTsumw   = sum(w_i) = N
            fTsumwx  = sum(w_i * x_i)
            fTsumwx2 = sum(w_i * x_i^2)
            mean     = fTsumwx / fTsumw
            sigma    = sqrt(max(0, fTsumwx2/fTsumw - mean^2))
        """
        n_entries = int(arr.size)
        if n_entries == 0:
            return 0.0, 0.0, 0.0, 0.0, 0.0

        f_tsumw = float(n_entries)
        f_tsumwx = float(np.sum(arr, dtype=np.float64))
        f_tsumwx2 = float(np.sum(np.square(arr, dtype=np.float64), dtype=np.float64))

        mean = f_tsumwx / f_tsumw
        variance = (f_tsumwx2 / f_tsumw) - (mean * mean)
        sigma = math.sqrt(max(0.0, variance))
        return f_tsumw, f_tsumwx, f_tsumwx2, mean, sigma

    def add_value(self, val: float) -> None:
        """Store a new unbinned measurement and update incremental ROOT accumulators."""
        self._data.append(float(val))
        self._dirty = True

        self.fTsumw += 1.0
        self.fTsumwx += float(val)
        self.fTsumwx2 += float(val) * float(val)
        self.mean = self.fTsumwx / self.fTsumw
        variance = (self.fTsumwx2 / self.fTsumw) - (self.mean * self.mean)
        self.sigma = math.sqrt(max(0.0, variance))

    # --------------------------------------------------------------- binning
    @staticmethod
    def _data_axis_range(arr: np.ndarray) -> Tuple[float, float]:
        """
        Compute X-axis range from data with a small relative margin so that
        the extreme samples sit inside the first/last bins (ROOT-like).
        """
        x_min = float(np.min(arr))
        x_max = float(np.max(arr))

        if math.isclose(x_min, x_max, rel_tol=1e-12, abs_tol=1e-12):
            # Degenerate sample: invent a symmetric window around the point
            pad = max(0.5, abs(x_min) * 0.05) if x_min != 0.0 else 0.5
            return x_min - pad, x_max + pad

        span = x_max - x_min
        margin = max(span * hc.AXIS_X_MARGIN_FRACTION, span * 1e-9)
        return x_min - margin, x_max + margin

    def _binning_satisfies_occupancy(
        self,
        counts: np.ndarray,
        edges: np.ndarray,
        mean: float,
        sigma: float,
    ) -> bool:
        """
        Return True when less-populated bins generally meet MIN_COUNTS_PER_BIN.

        Policy (ROOT-practical for peaked ToF spectra):
        - Evaluate occupancy primarily inside the core window
          [mean - CORE_SIGMA_MULTIPLIER*sigma, mean + CORE_SIGMA_MULTIPLIER*sigma].
        - Every *occupied* core bin must have >= MIN_COUNTS_PER_BIN entries so
          the less-populated shoulder bins stay statistically meaningful.
        - Empty bins (far tails) are allowed; extreme outliers outside the core
          do not force an overly coarse global binning.
        - If the core is empty/degenerate, fall back to all occupied bins.
        """
        centers = 0.5 * (edges[:-1] + edges[1:])
        half = hc.CORE_SIGMA_MULTIPLIER * max(float(sigma), 0.0)

        if half > 0.0:
            core_mask = (centers >= (mean - half)) & (centers <= (mean + half))
        else:
            core_mask = np.ones(centers.shape, dtype=bool)

        core_counts = counts[core_mask]
        occupied_core = core_counts[core_counts > 0]

        if occupied_core.size == 0:
            occupied = counts[counts > 0]
            if occupied.size == 0:
                return False
            return bool(int(np.min(occupied)) >= hc.MIN_COUNTS_PER_BIN)

        return bool(int(np.min(occupied_core)) >= hc.MIN_COUNTS_PER_BIN)

    def _choose_nbins_and_fill(
        self,
        arr: np.ndarray,
        x_low: float,
        x_high: float,
        mean: float,
        sigma: float,
    ) -> Tuple[np.ndarray, np.ndarray, int]:
        """
        Full rebin + refill from scratch.

        1. Choose the largest uniform n_bins in [1, MAX_BINS] compatible with
           the occupancy policy (and with the average-count upper bound).
        2. Build fresh edges over [x_low, x_high] (live data-driven range).
        3. Fill the new histogram by histogramming the entire unbinned sample
           (equivalent to TH1::Reset + SetBins + Fill for every stored value).
        """
        n_total = int(arr.size)

        # Not enough statistics yet: keep a coarse fixed binning
        if n_total < hc.MIN_COUNTS_PER_BIN * 2:
            n_bins = max(1, min(hc.INITIAL_BINS, n_total))
            counts, edges = np.histogram(arr, bins=n_bins, range=(x_low, x_high))
            return counts.astype(np.float64), edges.astype(np.float64), n_bins

        # Hard upper bound: average occupancy would otherwise drop below threshold
        max_by_avg = max(1, n_total // hc.MIN_COUNTS_PER_BIN)
        max_possible = min(hc.MAX_BINS, max_by_avg)

        chosen_counts: Optional[np.ndarray] = None
        chosen_edges: Optional[np.ndarray] = None
        chosen_nbins = 1

        # Search from fine -> coarse; first success is the highest resolution that
        # still keeps less-populated core bins generally above MIN_COUNTS_PER_BIN.
        for candidate in range(max_possible, 0, -1):
            counts, edges = np.histogram(arr, bins=candidate, range=(x_low, x_high))
            if candidate == 1 or self._binning_satisfies_occupancy(
                counts, edges, mean, sigma
            ):
                chosen_counts = counts
                chosen_edges = edges
                chosen_nbins = candidate
                break

        assert chosen_counts is not None and chosen_edges is not None
        return (
            chosen_counts.astype(np.float64),
            chosen_edges.astype(np.float64),
            chosen_nbins,
        )

    # ----------------------------------------------------------------- draw
    def _setup_axes_style(self) -> None:
        """Apply static style from hist_config (title/labels/grid)."""
        if self.ax is None:
            return
        self.ax.set_title(hc.PLOT_TITLE)
        self.ax.set_xlabel(hc.X_AXIS_LABEL)
        self.ax.set_ylabel(hc.Y_AXIS_LABEL)
        if hc.SHOW_GRID:
            self.ax.grid(
                True,
                color=hc.GRID_COLOR,
                linestyle=hc.GRID_LINE_STYLE,
                linewidth=hc.GRID_LINE_WIDTH,
                alpha=hc.GRID_ALPHA,
            )

    def _apply_live_axis_limits(self, counts: np.ndarray, edges: np.ndarray) -> None:
        """
        Live rescaling of both axes from the current filled histogram.

        X: exact edges of the freshly built histogram (data-driven range).
        Y: from 0 to max(bin content) * headroom, never below 1.
        """
        if self.ax is None:
            return

        x_left = float(edges[0])
        x_right = float(edges[-1])
        if math.isclose(x_left, x_right, rel_tol=1e-12, abs_tol=1e-12):
            x_right = x_left + 1.0

        y_peak = float(np.max(counts)) if counts.size else 0.0
        y_top = max(1.0, y_peak * hc.AXIS_Y_HEADROOM)

        self._x_range = (x_left, x_right)
        self._y_max = y_top

        self.ax.set_xlim(x_left, x_right)
        self.ax.set_ylim(0.0, y_top)

    def _draw_histogram(self, counts: np.ndarray, edges: np.ndarray) -> None:
        """Redraw the full histogram, markers, stats box, and live axes."""
        if self.ax is None or self.fig is None:
            return

        centers = 0.5 * (edges[:-1] + edges[1:])

        self.ax.clear()
        self._setup_axes_style()

        # Step histogram (ROOT "hist" drawing style)
        self.ax.stairs(
            counts,
            edges,
            fill=(hc.HIST_STYLE == "stepfilled"),
            facecolor=hc.HIST_FILL_COLOR if hc.HIST_STYLE == "stepfilled" else None,
            edgecolor=hc.HIST_LINE_COLOR,
            linewidth=hc.HIST_LINE_WIDTH,
            linestyle=hc.HIST_LINE_STYLE,
            alpha=hc.HIST_FILL_ALPHA if hc.HIST_STYLE == "stepfilled" else 1.0,
        )
        if hc.HIST_STYLE == "stepfilled":
            # Crisp contour on top of translucent fill
            self.ax.stairs(
                counts,
                edges,
                fill=False,
                edgecolor=hc.HIST_LINE_COLOR,
                linewidth=hc.HIST_LINE_WIDTH,
                linestyle=hc.HIST_LINE_STYLE,
            )

        if hc.SHOW_MARKERS:
            self.ax.plot(
                centers,
                counts,
                linestyle="None",
                marker=hc.MARKER_SYMBOL,
                markersize=hc.MARKER_SIZE,
                markerfacecolor=hc.MARKER_FACE_COLOR,
                markeredgecolor=hc.MARKER_EDGE_COLOR,
                markeredgewidth=hc.MARKER_EDGE_WIDTH,
            )

        if hc.SHOW_STATS_BOX:
            # ROOT TPaveStats-like box (Entries / Mean / Std Dev / Bins)
            stats_text = (
                f"Entries : {int(self.fTsumw)}\n"
                f"Mean    : {self.mean:.3f}\n"
                f"Std Dev : {self.sigma:.3f}\n"
                f"Bins    : {self.current_nbins}"
            )
            self.ax.text(
                0.97,
                0.95,
                stats_text,
                transform=self.ax.transAxes,
                fontsize=hc.STATS_FONT_SIZE,
                family="monospace",
                verticalalignment="top",
                horizontalalignment="right",
                bbox=dict(
                    boxstyle="square,pad=0.5",
                    facecolor=hc.STATS_BOX_BG_COLOR,
                    edgecolor=hc.STATS_BOX_EDGE_COLOR,
                    alpha=hc.STATS_BOX_ALPHA,
                ),
            )

        self._apply_live_axis_limits(counts, edges)
        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()

    # ----------------------------------------------------------- public API
    def rebuild_and_render(self, force: bool = False) -> None:
        """
        Full rebuild cycle (ROOT-style rebin + refill + redraw).

        Steps:
          1. Recompute unbinned ROOT statistics from the entire sample.
          2. Derive live X range from the data.
          3. Choose new uniform binning and refill every stored value from scratch.
          4. Rescale axes and redraw the canvas.
        """
        if not self._data:
            return

        now = time.monotonic()
        if not force and (not self._dirty or (now - self._last_rebin_time) < hc.REBIN_INTERVAL_SEC):
            # Keep GUI event loop alive even when skipping a heavy rebuild
            if self.enable_gui and self.fig is not None:
                self.fig.canvas.flush_events()
            return

        self._last_rebin_time = now
        self._dirty = False

        # 1) Unbinned sample -> ROOT stats from scratch
        arr = np.asarray(self._data, dtype=np.float64)
        (
            self.fTsumw,
            self.fTsumwx,
            self.fTsumwx2,
            self.mean,
            self.sigma,
        ) = self.compute_root_stats_from_array(arr)

        # 2) Live data-driven axis window
        x_low, x_high = self._data_axis_range(arr)
        self._x_range = (x_low, x_high)

        # 3) Full rebin + refill from scratch (never merge old bin contents)
        counts, edges, n_bins = self._choose_nbins_and_fill(
            arr, x_low, x_high, self.mean, self.sigma
        )
        self._last_counts = counts
        self._last_edges = edges
        self.current_nbins = n_bins

        if not self.enable_gui:
            return

        # 4) Redraw with live axis rescaling
        self._draw_histogram(counts, edges)

    def finalize_and_save(self) -> Optional[Path]:
        """Force a last full rebuild and export the high-resolution image."""
        if not self._data:
            if self.enable_gui and self.fig is not None:
                plt.close(self.fig)
            return None

        if not self.enable_gui:
            return None

        self.rebuild_and_render(force=True)
        if self.fig is not None:
            self.fig.savefig(
                self.image_path,
                dpi=hc.SAVE_DPI,
                format=hc.SAVE_FORMAT,
                bbox_inches="tight",
            )
            plt.ioff()
            plt.close(self.fig)
            return self.image_path
        return None
