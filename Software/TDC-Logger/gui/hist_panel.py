#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: gui/hist_panel.py
Description: Matplotlib-embedded live ToF histogram; redraw at most 3 Hz.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from histogram_manager import RootHistogramManager  # noqa: E402
import hist_config as hc  # noqa: E402


class LiveHistPanel(QWidget):
    """
    Uses RootHistogramManager (enable_gui=False) for ROOT stats + rebin,
    draws on an embedded canvas. Redraw <= 3 Hz and only if dirty/params change.
    """

    MAX_HZ = 3.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fig = Figure(figsize=(6, 4), dpi=100, facecolor="#ffffff")
        self._ax = self._fig.add_subplot(111)
        self._ax.set_facecolor("#ffffff")
        self._canvas = FigureCanvasQTAgg(self._fig)
        self._canvas.setStyleSheet("background-color: #ffffff; border: 1px solid #000000;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._canvas)

        # Same empty-state placement as serial panel: true center of the panel
        self._empty_label = QLabel("NO DATA", self)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._empty_label.setStyleSheet(
            "color: #53676c; font-size: 29px; font-weight: 700; font-family: Arial;"
            "background: transparent; border: none;"
        )
        self._empty_label.raise_()

        self._mgr = RootHistogramManager(
            output_folder=Path("."),
            base_name="gui_live",
            enable_gui=False,
        )
        self._dirty = False
        self._last_draw = 0.0
        self._auto_bins = True
        self._auto_range = True
        self._fixed_bins = 40
        self._fixed_range: Tuple[float, float] = (100.0, 10000.0)

        self._timer = QTimer(self)
        self._timer.setInterval(int(1000 / self.MAX_HZ))
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()
        self._draw_empty()

    def clear(self) -> None:
        self._mgr = RootHistogramManager(
            output_folder=Path("."),
            base_name="gui_live",
            enable_gui=False,
        )
        self._dirty = True
        self._draw_empty()

    def add_tof(self, value: float) -> None:
        try:
            self._mgr.add_value(float(value))
            self._dirty = True
        except Exception as exc:
            # surface on axes title
            self._ax.set_title(f"Hist error: {exc}")
            self._canvas.draw_idle()

    def set_auto_bins(self, enabled: bool) -> None:
        self._auto_bins = bool(enabled)
        self._dirty = True

    def set_auto_range(self, enabled: bool) -> None:
        self._auto_range = bool(enabled)
        self._dirty = True

    def set_fixed_bins(self, n: int) -> None:
        self._fixed_bins = max(1, min(500, int(n)))
        self._dirty = True

    def set_fixed_range(self, xmin: float, xmax: float) -> None:
        if xmax <= xmin:
            xmax = xmin + 1.0
        self._fixed_range = (float(xmin), float(xmax))
        self._dirty = True

    def _on_tick(self) -> None:
        if not self._dirty:
            return
        now = time.monotonic()
        if (now - self._last_draw) < (1.0 / self.MAX_HZ):
            return
        self._last_draw = now
        self._dirty = False
        try:
            self._redraw()
        except Exception as exc:
            self._ax.set_title(f"Redraw error: {exc}")
            self._canvas.draw_idle()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._layout_empty_label()

    def _layout_empty_label(self) -> None:
        if hasattr(self, "_empty_label"):
            self._empty_label.setGeometry(self.rect())

    def _set_empty_visible(self, visible: bool) -> None:
        if not hasattr(self, "_empty_label"):
            return
        self._layout_empty_label()
        self._empty_label.setVisible(bool(visible))
        if visible:
            self._empty_label.raise_()

    def _draw_empty(self) -> None:
        self._ax.clear()
        self._ax.set_title(hc.PLOT_TITLE)
        self._ax.set_xlabel(hc.X_AXIS_LABEL)
        self._ax.set_ylabel(hc.Y_AXIS_LABEL)
        # NO DATA is a QLabel overlay (matches serial panel position), not axes text
        self._fig.tight_layout()
        self._canvas.draw_idle()
        self._set_empty_visible(True)

    def _redraw(self) -> None:
        if not self._mgr._data:
            self._draw_empty()
            return
        self._set_empty_visible(False)

        # Force stats + binning computation
        self._mgr.rebuild_and_render(force=True)
        arr = np.asarray(self._mgr._data, dtype=np.float64)

        if self._auto_range:
            x_low, x_high = self._mgr._data_axis_range(arr)
        else:
            x_low, x_high = self._fixed_range

        if self._auto_bins:
            counts, edges, n_bins = self._mgr._choose_nbins_and_fill(
                arr, x_low, x_high, self._mgr.mean, self._mgr.sigma
            )
        else:
            counts, edges = np.histogram(
                arr, bins=self._fixed_bins, range=(x_low, x_high)
            )
            n_bins = self._fixed_bins
            counts = counts.astype(np.float64)
            edges = edges.astype(np.float64)

        self._ax.clear()
        self._ax.set_title(hc.PLOT_TITLE)
        self._ax.set_xlabel(hc.X_AXIS_LABEL)
        self._ax.set_ylabel(hc.Y_AXIS_LABEL)
        if hc.SHOW_GRID:
            self._ax.grid(
                True,
                color=hc.GRID_COLOR,
                linestyle=hc.GRID_LINE_STYLE,
                linewidth=hc.GRID_LINE_WIDTH,
                alpha=hc.GRID_ALPHA,
            )
        self._ax.stairs(
            counts,
            edges,
            fill=(hc.HIST_STYLE == "stepfilled"),
            facecolor=hc.HIST_FILL_COLOR if hc.HIST_STYLE == "stepfilled" else None,
            edgecolor=hc.HIST_LINE_COLOR,
            linewidth=hc.HIST_LINE_WIDTH,
            alpha=hc.HIST_FILL_ALPHA if hc.HIST_STYLE == "stepfilled" else 1.0,
        )
        y_top = max(1.0, float(np.max(counts)) * hc.AXIS_Y_HEADROOM)
        self._ax.set_xlim(float(edges[0]), float(edges[-1]))
        self._ax.set_ylim(0.0, y_top)
        stats = (
            f"Entries : {int(self._mgr.fTsumw)}\n"
            f"Mean    : {self._mgr.mean:.3f}\n"
            f"Std Dev : {self._mgr.sigma:.3f}\n"
            f"Bins    : {n_bins}"
        )
        self._ax.text(
            0.97,
            0.95,
            stats,
            transform=self._ax.transAxes,
            fontsize=hc.STATS_FONT_SIZE,
            family="monospace",
            va="top",
            ha="right",
            bbox=dict(
                boxstyle="square,pad=0.4",
                facecolor=hc.STATS_BOX_BG_COLOR,
                edgecolor=hc.STATS_BOX_EDGE_COLOR,
                alpha=hc.STATS_BOX_ALPHA,
            ),
        )
        self._fig.tight_layout()
        self._canvas.draw_idle()
