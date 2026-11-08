#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: gui/main_window.py
Description: GUI shell matching mockups + gui_corrections.txt behavior.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QPointF, QRectF, QSettings, QTimer
from PySide6.QtGui import (
    QColor,
    QDoubleValidator,
    QFont,
    QIntValidator,
    QPainter,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from serial_manager import SerialManager  # noqa: E402
from gui.command_builder import (  # noqa: E402
    CommandBuildError,
    GuiFormState,
    build_cli_argv,
)
from gui.process_worker import CliProcessController  # noqa: E402
from gui.hist_panel import LiveHistPanel  # noqa: E402
from gui.serial_panel import SerialMonitorPanel  # noqa: E402
from gui.widgets import (  # noqa: E402
    ClearDefaultLineEdit,
    ElongatingComboBox,
    UnitIntEdit,
    bold_font,
)
from gui import styles as S  # noqa: E402

SAMPLES_DEFAULT = 10000
SAMPLES_MIN_NONEMPTY = 1000
SAMPLES_MAX = 10_000_000_000
DAYS_MAX = 30


def _divider() -> QFrame:
    d = QFrame()
    d.setObjectName("divider")
    d.setFixedHeight(getattr(S, "DIVIDER_H", 2))
    return d


def _section_title(text: str) -> QLabel:
    t = QLabel(text)
    t.setObjectName("sectionTitle")
    return t


class CornerTab(QWidget):
    """Dog-ear toggle: SERIAL (over hist) / HISTO (over serial)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label = "SERIAL"
        self._dark = True
        tab = int(getattr(S, "CORNER_TAB", 77))
        self.setFixedSize(tab, tab)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._handler = None

    def set_handler(self, fn) -> None:
        self._handler = fn

    def set_mode(self, show_serial: bool) -> None:
        if show_serial:
            self._label = "HISTO"
            self._dark = False
        else:
            self._label = "SERIAL"
            self._dark = True
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._handler:
            try:
                self._handler()
            except Exception as exc:
                print(f"CornerTab: {exc}", file=sys.stderr)
        super().mousePressEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        fill = QColor(S.BORDER) if self._dark else QColor("#ffffff")
        p.setBrush(fill)
        w, h = float(self.width()), float(self.height())
        p.drawPolygon(QPolygonF([QPointF(0, 0), QPointF(w, 0), QPointF(0, h)]))
        edge = float(getattr(S, "BORDER_W", 2))
        p.setPen(QPen(QColor(S.BORDER), edge))
        p.drawLine(QPointF(0, 0), QPointF(w, 0))
        p.drawLine(QPointF(w, 0), QPointF(0, h))

        text_color = QColor("#ffffff") if self._dark else QColor(S.BORDER)
        p.setPen(text_color)
        font = QFont("Arial", int(getattr(S, "CORNER_FONT", 10)))
        font.setBold(True)
        p.setFont(font)
        p.save()
        p.translate(w * 0.26, h * 0.40)
        p.rotate(-45.0)
        p.drawText(QRectF(-34, -10, 72, 20), int(Qt.AlignmentFlag.AlignCenter), self._label)
        p.restore()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TDC-Logger")
        self.resize(1400, 900)
        self.setMinimumHeight(700)
        self.setStyleSheet(S.APP_QSS)

        self._root = _ROOT
        self._main_py = self._root / "main.py"
        self._running = False
        self._show_serial = False
        self._session_started = False
        self._cli = CliProcessController(self)
        self._freeze_effects: list[QGraphicsOpacityEffect] = []
        self._port_refreshing = False
        # Hot-plug: rescan COM ports while idle (Arduino often appears after GUI start)
        self._port_timer = QTimer(self)
        self._port_timer.setInterval(2000)
        self._port_timer.timeout.connect(self._refresh_ports_if_idle)
        # Persist save folder across acquisitions / app restarts
        self._settings = QSettings("UNO-TDC", "TDC-Logger")
        self._save_dir = self._load_save_dir()

        central = QWidget()
        central.setObjectName("centralRoot")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._top_bar = self._build_top()
        root.addWidget(self._top_bar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        root.addLayout(body, 1)

        side_host = QWidget()
        side_host.setObjectName("sidePanel")
        side_host.setFixedWidth(S.SIDE_W)
        self._side_host = side_host
        sh = QHBoxLayout(side_host)
        sh.setContentsMargins(0, 0, 0, 0)
        sh.setSpacing(0)
        self._side = self._build_side()
        sh.addWidget(self._side, 1)
        body.addWidget(side_host)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        body.addLayout(right, 1)
        self._sec_bar = self._build_sec()
        right.addWidget(self._sec_bar)
        right.addWidget(self._build_center(), 1)

        self._connect_cli()
        self._set_running(False)
        self._refresh_ports(force_default=True)
        self._sync_acq_enabled()
        self._sync_hist_enabled()
        self._apply_min_width()
        self._update_preview()
        self._port_timer.start()

    # ============================================================== TOP BAR
    def _build_top(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("topBar")
        bar.setFixedHeight(S.TOP_H)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(28, 0, 28, 0)
        lay.setSpacing(12)

        logo = QLabel()
        logo_px = int(getattr(S, "FS_LOGO", 44))
        logo.setText(
            f'<span style="font-family:Arial;font-size:{logo_px}px;font-weight:700;color:{S.FG_LOGO};">TDC</span>'
            f'<span style="font-family:Arial;font-size:{logo_px}px;font-weight:400;color:{S.FG_LOGO};">-Logger</span>'
        )
        lay.addWidget(logo, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addStretch(1)

        save = QLabel("Save data as:")
        save.setObjectName("saveLabel")
        lay.addWidget(save, 0, Qt.AlignmentFlag.AlignVCenter)

        last_name = str(self._settings.value("save/name", "session") or "session")
        self._out_name = ClearDefaultLineEdit(last_name or "session", object_name="saveField")
        if last_name and last_name != "session":
            self._out_name.set_committed_text(last_name)
        self._out_name.setFixedWidth(360)
        lay.addWidget(self._out_name, 0, Qt.AlignmentFlag.AlignVCenter)

        self._browse_btn = QPushButton("Browse...")
        self._browse_btn.setObjectName("browseBtn")
        self._browse_btn.clicked.connect(self._browse)
        lay.addWidget(self._browse_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        # Hidden mirror; real source of truth is _save_dir (persisted)
        self._out_dir = QLineEdit(str(self._save_dir))
        self._out_dir.hide()
        self._out_name.textChanged.connect(self._on_save_name_changed)
        return bar

    # ============================================================== SIDEBAR
    def _build_side(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("sideScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        inner = QWidget()
        inner.setObjectName("sideInner")
        scroll.setWidget(inner)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(20, 18, 16, 18)
        # Double-ish spacing between options / after titles
        lay.setSpacing(12)

        # --- Serial port ---
        lay.addWidget(_section_title("Serial port:"))
        lay.addSpacing(6)
        sub = QLabel("Select the serial port:")
        sub.setObjectName("bodyText")
        lay.addWidget(sub)

        port_frame = QFrame()
        port_frame.setObjectName("portFrame")
        self._port_frame = port_frame
        pf = QHBoxLayout(port_frame)
        pf.setContentsMargins(0, 0, 0, 0)
        pf.setSpacing(0)
        self._port = ElongatingComboBox()
        self._port.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._port.currentIndexChanged.connect(self._sync_port_combo_font)
        # Rescan OS COM list every time the user opens the dropdown
        self._port.set_before_popup(lambda: self._refresh_ports(force_default=False))
        chev = QLabel("\\/")
        chev.setObjectName("portChevron")
        chev.setFixedWidth(28)
        chev.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chev.setToolTip("Open port list (rescans for Arduino)")
        chev.mousePressEvent = lambda e: self._port.showPopup()  # type: ignore[method-assign]
        pf.addWidget(self._port, 1)
        pf.addWidget(chev, 0)
        lay.addWidget(port_frame)
        lay.addSpacing(8)
        lay.addWidget(_divider())
        lay.addSpacing(16)

        # --- Measurement mode ---
        lay.addWidget(_section_title("Measurement mode:"))
        lay.addSpacing(6)
        self._mode_grp = QButtonGroup(self)
        self._m1 = QRadioButton("Measurement mode 1")
        self._m2 = QRadioButton("Measurement mode 2")
        self._m1.setChecked(True)
        self._mode_grp.addButton(self._m1, 1)
        self._mode_grp.addButton(self._m2, 2)
        lay.addWidget(self._m1)
        h = QLabel("Range is 14 ns to 2.7 us")
        h.setObjectName("hintText")
        lay.addWidget(h)
        lay.addSpacing(8)
        lay.addWidget(self._m2)
        h = QLabel("Range is 250 ns to 4 ms")
        h.setObjectName("hintText")
        lay.addWidget(h)
        lay.addSpacing(8)
        lay.addWidget(_divider())
        lay.addSpacing(16)

        # --- Acquire until ---
        lay.addWidget(_section_title("Acquire until:"))
        lay.addSpacing(6)
        self._acq_grp = QButtonGroup(self)
        self._acq_user = QRadioButton("User input")
        self._acq_time = QRadioButton("Time elapsed:")
        self._acq_samp = QRadioButton("Number of measurements:")
        self._acq_samp.setChecked(True)
        for i, b in enumerate((self._acq_user, self._acq_time, self._acq_samp)):
            self._acq_grp.addButton(b, i)
            b.toggled.connect(self._sync_acq_enabled)

        lay.addWidget(self._acq_user)
        lay.addSpacing(8)
        lay.addWidget(self._acq_time)

        time_row = QHBoxLayout()
        time_row.setContentsMargins(22, 2, 0, 6)
        time_row.setSpacing(4)
        # Allow typing beyond max; clamp on focus-out via _on_time_committed
        self._days = UnitIntEdit("d", value=0, maximum=999, minimum=0)
        self._hours = UnitIntEdit("h", value=0, maximum=99, minimum=0)
        self._mins = UnitIntEdit("m", value=10, maximum=99, minimum=0)
        self._days.valueCommitted.connect(self._on_time_committed)
        self._hours.valueCommitted.connect(self._on_time_committed)
        self._mins.valueCommitted.connect(self._on_time_committed)
        time_row.addWidget(self._days)
        colon = QLabel(":")
        colon.setObjectName("colon")
        time_row.addWidget(colon)
        time_row.addWidget(self._hours)
        colon2 = QLabel(":")
        colon2.setObjectName("colon")
        time_row.addWidget(colon2)
        time_row.addWidget(self._mins)
        time_row.addStretch(1)
        lay.addLayout(time_row)

        lay.addSpacing(8)
        lay.addWidget(self._acq_samp)
        samp_row = QHBoxLayout()
        samp_row.setContentsMargins(22, 2, 0, 6)
        self._samples = ClearDefaultLineEdit(str(SAMPLES_DEFAULT), object_name="samplesField")
        self._samples.setValidator(QIntValidator(0, 2_147_483_647, self._samples))
        self._samples.editingFinished.connect(self._on_samples_committed)
        samp_row.addWidget(self._samples)
        samp_row.addStretch(1)
        lay.addLayout(samp_row)

        lay.addSpacing(8)
        lay.addWidget(_divider())
        lay.addSpacing(16)

        # --- Additional options ---
        lay.addWidget(_section_title("Additional options:"))
        lay.addSpacing(6)
        self._chk_ts = QCheckBox("Include timestamps in the .log file")
        self._chk_raw = QCheckBox("Also save the raw serial log")
        self._chk_raw.setChecked(True)
        self._chk_lim = QCheckBox("Ignore measurements bigger than:")
        self._lim = ClearDefaultLineEdit("27000", object_name="limField")
        self._lim.setValidator(QDoubleValidator(1.0, 1e12, 3, self._lim))
        self._lim.setEnabled(False)
        self._lim_unit = QLabel("ns")
        self._lim_unit.setObjectName("unitSuffix")
        self._lim_unit.setEnabled(False)
        self._chk_lim.toggled.connect(self._lim.setEnabled)
        self._chk_lim.toggled.connect(self._lim_unit.setEnabled)
        self._chk_ts.toggled.connect(self._update_preview)
        self._chk_raw.toggled.connect(self._update_preview)
        self._chk_lim.toggled.connect(self._update_preview)
        self._lim.textChanged.connect(self._update_preview)
        lay.addWidget(self._chk_ts)
        lay.addSpacing(8)
        lay.addWidget(self._chk_raw)
        lay.addSpacing(8)
        lay.addWidget(self._chk_lim)
        lim_row = QHBoxLayout()
        lim_row.setContentsMargins(22, 2, 0, 0)
        lim_row.setSpacing(6)
        lim_row.addWidget(self._lim)
        lim_row.addWidget(self._lim_unit)
        lim_row.addStretch(1)
        lay.addLayout(lim_row)
        lay.addStretch(1)

        self._port.currentIndexChanged.connect(self._update_preview)
        self._m1.toggled.connect(self._update_preview)
        self._m2.toggled.connect(self._update_preview)
        return scroll

    # ============================================================== SEC BAR
    def _build_sec(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("secBar")
        bar.setFixedHeight(S.SEC_H)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 8, 16, 8)
        lay.setSpacing(12)

        # 2 rows x 6 conceptual columns (stats + hist menu)
        grid_host = QWidget()
        grid_host.setObjectName("histMenuHost")
        self._hist_menu_host = grid_host
        g = QGridLayout(grid_host)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(8)

        self._k_el = QLabel("Time elapsed:")
        self._v_el = QLabel("—")
        self._k_in = QLabel("In range:")
        self._v_in = QLabel("—")
        self._k_en = QLabel("Entries:")
        self._v_en = QLabel("—")
        self._k_out = QLabel("Out of range:")
        self._v_out = QLabel("—")
        for lab in (self._k_el, self._k_in, self._k_en, self._k_out, self._v_el, self._v_in, self._v_en, self._v_out):
            lab.setObjectName("statKey" if lab in (self._k_el, self._k_in, self._k_en, self._k_out) else "statVal")
            lab.setStyleSheet(f"color: {S.FG_TEXT}; font-family: Arial;")
        for lab in (self._v_el, self._v_in, self._v_en, self._v_out):
            lab.setMinimumWidth(56)

        # Col 0–3: stats
        g.addWidget(self._k_el, 0, 0)
        g.addWidget(self._v_el, 0, 1)
        g.addWidget(self._k_in, 0, 2)
        g.addWidget(self._v_in, 0, 3)
        g.addWidget(self._k_en, 1, 0)
        g.addWidget(self._v_en, 1, 1)
        g.addWidget(self._k_out, 1, 2)
        g.addWidget(self._v_out, 1, 3)

        # Col 4: AUTO checkboxes
        self._auto_bin = QCheckBox("AUTO BINNING")
        self._auto_bin.setObjectName("histCheck")
        self._auto_bin.setChecked(True)
        self._auto_rng = QCheckBox("AUTO RANGE")
        self._auto_rng.setObjectName("histCheck")
        self._auto_rng.setChecked(True)
        g.addWidget(self._auto_bin, 0, 4, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        g.addWidget(self._auto_rng, 1, 4, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # Col 5: labels  |  Col 6 (7th conceptual column): aligned text inputs
        bins_lab = QLabel("Bins:")
        bins_lab.setStyleSheet(f"color: {S.FG_TEXT};")
        rng_lab = QLabel("Range:")
        rng_lab.setStyleSheet(f"color: {S.FG_TEXT};")
        g.addWidget(bins_lab, 0, 5, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        g.addWidget(rng_lab, 1, 5, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._bins = ClearDefaultLineEdit("40")
        self._xmin = ClearDefaultLineEdit("100")
        self._xmax = ClearDefaultLineEdit("10000")
        self._bins.setFixedWidth(56)
        self._xmin.setFixedWidth(64)
        self._xmax.setFixedWidth(72)
        for sp in (self._xmin, self._xmax, self._bins):
            sp.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Row0 col6: bins value left-aligned with xmin
        bins_in = QHBoxLayout()
        bins_in.setContentsMargins(0, 0, 0, 0)
        bins_in.setSpacing(4)
        bins_in.addWidget(self._bins, 0, Qt.AlignmentFlag.AlignLeft)
        bins_in.addStretch(1)
        bins_in_w = QWidget()
        bins_in_w.setLayout(bins_in)

        # Row1 col6: xmin  ns -  xmax  ns  (same left edge as bins box)
        rng_in = QHBoxLayout()
        rng_in.setContentsMargins(0, 0, 0, 0)
        rng_in.setSpacing(4)
        dash = QLabel("ns -")
        dash.setStyleSheet(f"color: {S.FG_TEXT};")
        ns2 = QLabel("ns")
        ns2.setStyleSheet(f"color: {S.FG_TEXT};")
        rng_in.addWidget(self._xmin, 0, Qt.AlignmentFlag.AlignLeft)
        rng_in.addWidget(dash)
        rng_in.addWidget(self._xmax)
        rng_in.addWidget(ns2)
        rng_in.addStretch(1)
        rng_in_w = QWidget()
        rng_in_w.setLayout(rng_in)

        g.addWidget(bins_in_w, 0, 6)
        g.addWidget(rng_in_w, 1, 6)
        g.setColumnStretch(6, 1)
        g.setColumnMinimumWidth(6, 220)

        self._auto_bin.toggled.connect(self._on_hist_opts)
        self._auto_rng.toggled.connect(self._on_hist_opts)
        self._bins.textChanged.connect(self._on_hist_opts)
        self._xmin.textChanged.connect(self._on_hist_opts)
        self._xmax.textChanged.connect(self._on_hist_opts)

        lay.addWidget(grid_host, 1)

        self._btn = QPushButton("START")
        self._btn.setObjectName("startBtn")
        self._btn.setFixedSize(S.START_W, S.START_H)
        self._btn.setProperty("running", False)
        self._btn.clicked.connect(self._start_stop)
        lay.addWidget(self._btn, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Pre-start: hide histogram menu (stats + hist controls)
        self._set_hist_menu_visible(False)
        return bar

    def _set_hist_menu_visible(self, visible: bool) -> None:
        self._hist_menu_host.setVisible(bool(visible))

    # ============================================================== CENTER
    def _build_center(self) -> QWidget:
        self._center = QFrame()
        self._center.setObjectName("centerFrame")
        lay = QVBoxLayout(self._center)
        lay.setContentsMargins(0, 0, 0, 0)

        self._stack = QStackedWidget()
        # 0: idle placeholder — NO DATA (same center + type as hist/serial overlays)
        idle = QWidget()
        idle.setStyleSheet(f"background-color: {S.BG_CENTER};")
        il = QVBoxLayout(idle)
        il.setContentsMargins(0, 0, 0, 0)
        self._idle_label = QLabel("NO DATA")
        self._idle_label.setObjectName("placeholderLabel")
        self._idle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._idle_label.setStyleSheet(
            "color: #53676c; font-size: 29px; font-weight: 700; font-family: Arial;"
            "background: transparent; border: none;"
        )
        il.addWidget(self._idle_label, 1)
        # 1: hist
        self._hist = LiveHistPanel()
        # 2: serial
        self._serial = SerialMonitorPanel()
        self._stack.addWidget(idle)
        self._stack.addWidget(self._hist)
        self._stack.addWidget(self._serial)
        lay.addWidget(self._stack)

        self._ear = CornerTab(self._center)
        self._ear.set_handler(self._toggle_view)
        self._ear.move(0, 0)
        self._ear.raise_()
        self._ear.set_mode(False)
        return self._center

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        if hasattr(self, "_ear"):
            self._ear.move(0, 0)
            self._ear.raise_()
        self._apply_min_width()

    def _apply_min_width(self) -> None:
        """Block horizontal shrink once sec-bar columns would collide."""
        try:
            need = S.SIDE_W + S.SEC_MIN_CONTENT_W + S.START_W + 48
            if self.minimumWidth() != need:
                self.setMinimumWidth(need)
        except Exception as exc:
            print(f"min width: {exc}", file=sys.stderr)

    # ============================================================== LOGIC
    def _connect_cli(self) -> None:
        # Serial traffic → raw; CLI diagnostics → log (do not wire both to the same
        # text for the same payload — that doubles handshake lines).
        self._cli.line_log.connect(self._serial.append_line)
        self._cli.line_raw.connect(self._serial.append_line)
        self._cli.tof_value.connect(self._on_tof)
        self._cli.stats.connect(self._on_stats)
        self._cli.event.connect(lambda n, _p: self._serial.append_line(f"[evt] {n}"))
        self._cli.error.connect(lambda m: self._serial.append_line(f"[error] {m}"))
        self._cli.finished.connect(self._on_finished)
        self._cli.state_changed.connect(self._set_running)
        self._cli.stop_requested.connect(self._on_stop_requested)

    def _load_save_dir(self) -> Path:
        """Restore last Browse folder, falling back to project root."""
        raw = str(self._settings.value("save/dir", "") or "").strip()
        if raw:
            p = Path(raw)
            try:
                if p.is_dir():
                    return p.resolve()
            except OSError:
                pass
        return self._root.resolve()

    def _set_save_dir(self, directory: str | Path) -> None:
        """Remember output folder for this session and future launches."""
        try:
            p = Path(directory).expanduser().resolve()
        except OSError as exc:
            QMessageBox.warning(self, "Output folder", f"Invalid folder: {exc}")
            return
        if not p.is_dir():
            QMessageBox.warning(self, "Output folder", f"Folder does not exist:\n{p}")
            return
        self._save_dir = p
        self._out_dir.setText(str(p))
        self._settings.setValue("save/dir", str(p))

    def _on_save_name_changed(self, _text: str = "") -> None:
        name = self._out_name.text_or_default().strip() or "session"
        self._settings.setValue("save/name", Path(name).stem)
        self._update_preview()

    def _browse(self) -> None:
        start = str(self._save_dir) if self._save_dir.is_dir() else str(self._root)
        d = QFileDialog.getExistingDirectory(self, "Output folder", start)
        if d:
            self._set_save_dir(d)

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        # Rescan when the window is activated (user plugged board, alt-tab back)
        try:
            from PySide6.QtCore import QEvent

            if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
                if not self._running:
                    self._refresh_ports(force_default=False)
        except Exception as exc:
            print(f"changeEvent port refresh: {exc}", file=sys.stderr)

    def _refresh_ports_if_idle(self) -> None:
        if self._running or self._port_refreshing:
            return
        # Skip while dropdown is open to avoid clearing the popup mid-click
        try:
            if self._port.view() is not None and self._port.view().isVisible():
                return
        except Exception:
            pass
        self._refresh_ports(force_default=False)

    def _refresh_ports(self, *, force_default: bool = False) -> None:
        if self._port_refreshing:
            return
        self._port_refreshing = True
        try:
            prev = str(self._port.currentData() or "")
            try:
                ranked = SerialManager.rank_ports()
            except Exception as exc:
                QMessageBox.warning(self, "Ports", str(exc))
                return

            # Build new entries without nuking selection until we know the index
            self._port.blockSignals(True)
            self._port.clear()
            if not ranked:
                self._port.addItem("(no ports — plug in Arduino)", "")
                self._port.blockSignals(False)
                self._sync_port_combo_font()
                self._update_preview()
                return

            for prio, dev, disp in ranked:
                if prio == 1:
                    label = f"{dev} (Arduino)"
                elif prio == 2:
                    label = f"{dev} (USB-Serial)"
                else:
                    label = dev
                self._port.addItem(label, dev)
                idx = self._port.count() - 1
                self._port.setItemData(idx, disp, Qt.ItemDataRole.ToolTipRole)
                self._port.setItemData(idx, QColor("#ffffff"), Qt.ItemDataRole.BackgroundRole)
                self._port.setItemData(idx, QColor("#000000"), Qt.ItemDataRole.ForegroundRole)
                if prio == 1:
                    self._port.setItemData(
                        idx, bold_font(self._port.font()), Qt.ItemDataRole.FontRole
                    )

            # Keep previous selection if still present; else prefer Arduino / USB-Serial
            select_idx = 0
            if prev and not force_default:
                for i in range(self._port.count()):
                    if str(self._port.itemData(i) or "") == prev:
                        select_idx = i
                        break
                else:
                    prev = ""
            if not prev or force_default:
                select_idx = 0
                for i, (prio, _dev, _d) in enumerate(ranked):
                    if prio == 1:
                        select_idx = i
                        break
                else:
                    for i, (prio, _dev, _d) in enumerate(ranked):
                        if prio == 2:
                            select_idx = i
                            break

            self._port.setCurrentIndex(select_idx)
            self._port.blockSignals(False)
            self._sync_port_combo_font()
            self._update_preview()
        finally:
            self._port_refreshing = False

    def _sync_port_combo_font(self) -> None:
        try:
            idx = self._port.currentIndex()
            f = self._port.itemData(idx, Qt.ItemDataRole.FontRole)
            if isinstance(f, QFont):
                self._port.setFont(f)
            else:
                nf = QFont("Arial")
                nf.setBold(False)
                self._port.setFont(nf)
        except Exception:
            pass

    def _sync_acq_enabled(self) -> None:
        t = self._acq_time.isChecked() and not self._running
        s = self._acq_samp.isChecked() and not self._running
        for w in (self._days, self._hours, self._mins):
            w.setEnabled(t)
            w.setReadOnly(not t)
        self._samples.setEnabled(s)
        self._samples.setReadOnly(not s)
        self._update_preview()

    def _sync_hist_enabled(self) -> None:
        self._bins.setEnabled(not self._auto_bin.isChecked())
        self._bins.setReadOnly(self._auto_bin.isChecked())
        self._xmin.setEnabled(not self._auto_rng.isChecked())
        self._xmax.setEnabled(not self._auto_rng.isChecked())
        self._xmin.setReadOnly(self._auto_rng.isChecked())
        self._xmax.setReadOnly(self._auto_rng.isChecked())

    def _on_time_committed(self) -> None:
        """On leaving any time field: clamp d/h/m and fix 0/0/0 → 0/0/10."""
        try:
            d = self._days.value()
            h = self._hours.value()
            m = self._mins.value()
            # Max values as soon as the field is exited
            if d > DAYS_MAX:
                d = DAYS_MAX
                self._days.set_value(d)
            if h > 23:
                h = 23
                self._hours.set_value(h)
            if m > 59:
                m = 59
                self._mins.set_value(m)
            # Re-read after clamps
            d = self._days.value()
            h = self._hours.value()
            m = self._mins.value()
            # Zero duration → default 10 minutes
            if d == 0 and h == 0 and m == 0:
                self._days.set_value(0)
                self._hours.set_value(0)
                self._mins.set_value(10)
        except Exception as exc:
            print(f"time commit: {exc}", file=sys.stderr)
        self._update_preview()

    def _on_samples_committed(self) -> None:
        try:
            raw = self._samples.text().strip()
            if not raw:
                self._samples.set_committed_text(str(SAMPLES_DEFAULT))
                return
            v = self._parse_int_field(raw, SAMPLES_DEFAULT)
            if v <= 0:
                v = SAMPLES_MIN_NONEMPTY
            if v > SAMPLES_MAX:
                v = SAMPLES_MAX
            self._samples.set_committed_text(str(v))
        except Exception as exc:
            print(f"samples commit: {exc}", file=sys.stderr)
        self._update_preview()

    def _clamp_days_on_start(self) -> None:
        if self._days.value() > DAYS_MAX:
            self._days.set_value(DAYS_MAX)

    @staticmethod
    def _parse_int_field(text: str, default: int = 0) -> int:
        digits = "".join(ch for ch in str(text) if ch.isdigit() or ch == "-")
        if not digits or digits == "-":
            return default
        try:
            return int(digits)
        except ValueError:
            return default

    @staticmethod
    def _parse_float_field(text: str, default: float = 0.0) -> float:
        cleaned = str(text).lower().replace("ns", "").replace(",", ".").strip()
        num = "".join(ch for ch in cleaned if ch.isdigit() or ch in ".-+")
        if not num:
            return default
        try:
            return float(num)
        except ValueError:
            return default

    def _on_hist_opts(self) -> None:
        self._sync_hist_enabled()
        self._hist.set_auto_bins(self._auto_bin.isChecked())
        self._hist.set_auto_range(self._auto_rng.isChecked())
        self._hist.set_fixed_bins(
            max(1, self._parse_int_field(self._bins.text_or_default(), 40))
        )
        self._hist.set_fixed_range(
            self._parse_float_field(self._xmin.text_or_default(), 100.0),
            self._parse_float_field(self._xmax.text_or_default(), 10000.0),
        )

    def _form(self) -> GuiFormState:
        acq = "user"
        if self._acq_time.isChecked():
            acq = "time"
        elif self._acq_samp.isChecked():
            acq = "samples"
        name = self._out_name.text_or_default().strip() or "session"
        # If the user pasted a full path into the name field, split dir/name
        name_path = Path(name)
        out_dir = self._save_dir
        out_stem = name_path.stem or "session"
        if len(name_path.parts) > 1:
            # Full/relative path typed in the name box
            candidate_parent = name_path.parent
            try:
                if candidate_parent.is_dir():
                    out_dir = candidate_parent.resolve()
                    out_stem = name_path.stem or out_stem
            except OSError:
                pass
        samples = self._parse_int_field(self._samples.text_or_default(), SAMPLES_DEFAULT)
        if samples <= 0:
            samples = SAMPLES_MIN_NONEMPTY
        samples = min(SAMPLES_MAX, samples)
        return GuiFormState(
            port=str(self._port.currentData() or ""),
            mode=1 if self._m1.isChecked() else 2,
            acquire_until=acq,
            time_days=min(DAYS_MAX, self._days.value()),
            time_hours=min(23, self._hours.value()),
            time_minutes=min(59, max(0, self._mins.value())),
            max_samples=samples,
            timestamps=self._chk_ts.isChecked(),
            save_raw=self._chk_raw.isChecked(),
            lim_sup_enabled=self._chk_lim.isChecked(),
            lim_sup_ns=self._parse_float_field(self._lim.text_or_default(), 27000.0),
            output_name=out_stem,
            output_dir=str(out_dir),
        )

    def _update_preview(self) -> None:
        pass

    def _apply_freeze(self, frozen: bool) -> None:
        """Stronger frosted opacity on sidebar + save controls while running."""
        targets = [self._side_host, self._out_name, self._browse_btn]
        # Clear old effects
        for w in targets:
            w.setGraphicsEffect(None)
        self._freeze_effects.clear()
        if not frozen:
            self._side.setEnabled(True)
            self._out_name.setEnabled(True)
            self._browse_btn.setEnabled(True)
            return
        self._side.setEnabled(False)
        self._out_name.setEnabled(False)
        self._browse_btn.setEnabled(False)
        for w in targets:
            eff = QGraphicsOpacityEffect(w)
            eff.setOpacity(S.FREEZE_OPACITY)
            w.setGraphicsEffect(eff)
            self._freeze_effects.append(eff)

    def _set_running(self, running: bool) -> None:
        self._running = bool(running)
        self._apply_freeze(running)
        # Don't rescan COM while the CLI holds the port open
        if running:
            self._port_timer.stop()
        else:
            if not self._port_timer.isActive():
                self._port_timer.start()
            self._refresh_ports(force_default=False)
        if running:
            self._session_started = True
            self._set_hist_menu_visible(True)
            self._btn.setEnabled(True)
            self._btn.setText("STOP")
            self._btn.setProperty("running", True)
            if not self._show_serial:
                self._stack.setCurrentIndex(1)
        else:
            # Pre-start only: hide hist menu. After a session, keep final stats visible.
            self._set_hist_menu_visible(self._session_started)
            self._btn.setEnabled(True)
            self._btn.setText("START")
            self._btn.setProperty("running", False)
            if not self._show_serial:
                # Idle NO DATA only before any acquisition; after session keep hist
                self._stack.setCurrentIndex(1 if self._session_started else 0)
            else:
                self._stack.setCurrentIndex(2)
                self._serial.show_placeholder_if_empty()
        self._btn.style().unpolish(self._btn)
        self._btn.style().polish(self._btn)
        self._sync_acq_enabled()
        self._ear.raise_()

    def _toggle_view(self) -> None:
        self._show_serial = not self._show_serial
        if self._show_serial:
            self._stack.setCurrentIndex(2)
            self._serial.show_placeholder_if_empty()
            self._ear.set_mode(True)
        else:
            self._stack.setCurrentIndex(1 if self._running else 0)
            self._ear.set_mode(False)
        self._ear.raise_()

    def _on_stop_requested(self) -> None:
        """Immediate UI reaction; second click force-kills via request_stop()."""
        self._btn.setEnabled(True)
        self._btn.setText("KILL")
        self._btn.setProperty("running", True)
        self._btn.style().unpolish(self._btn)
        self._btn.style().polish(self._btn)
        self._serial.append_line("[gui] STOP requested (click again to force kill)")

    def _start_stop(self) -> None:
        if self._running:
            try:
                # Second click while already stopping forces kill (handled in worker)
                self._cli.request_stop()
            except Exception as exc:
                QMessageBox.critical(self, "Stop", str(exc))
                self._btn.setEnabled(True)
            return
        try:
            # Days clamp only on START
            self._clamp_days_on_start()
            self._on_time_committed()
            self._on_samples_committed()
            st = self._form()
            if not st.port:
                raise CommandBuildError("No serial port selected")
            # Keep chosen folder sticky for next run / next name change
            if st.output_dir:
                self._set_save_dir(st.output_dir)
            self._settings.setValue("save/name", st.output_name)
            argv = build_cli_argv(st, self._main_py, sys.executable)
            # CLI cwd = save folder so relative -o still lands in the right place
            workdir = st.output_dir or str(self._save_dir) or str(self._root)
            self._serial.clear()
            self._hist.clear()
            self._on_hist_opts()
            self._show_serial = False
            self._ear.set_mode(False)
            self._stack.setCurrentIndex(1)
            self._set_hist_menu_visible(True)
            self._cli.start(argv, workdir=workdir)
        except CommandBuildError as exc:
            QMessageBox.warning(self, "Invalid settings", str(exc))
        except Exception as exc:
            QMessageBox.critical(self, "Start failed", str(exc))
            self._set_running(False)

    def _on_tof(self, v: float, in_range: bool) -> None:
        if in_range:
            self._hist.add_tof(v)

    def _on_stats(self, st: dict) -> None:
        try:
            elapsed = float(st.get("elapsed_s", 0.0))
            h = int(elapsed // 3600)
            m = int((elapsed % 3600) // 60)
            s = int(elapsed % 60)
            self._v_el.setText(f"{h}h {m}m" if h else f"{m}m {s}s")
            inn = int(st.get("in", 0))
            out = int(st.get("out", 0))
            self._v_en.setText(str(inn + out))
            self._v_in.setText(str(inn))
            self._v_out.setText(str(out))
        except Exception as exc:
            self._serial.append_line(f"[stats error] {exc}")

    def _on_finished(self, code: int) -> None:
        self._set_running(False)
        self._serial.append_line(f"[cli exited] code={code}")

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            if self._cli.is_running():
                self._cli.request_stop()
                self._cli.kill()
        except Exception as exc:
            print(f"closeEvent: {exc}", file=sys.stderr)
        super().closeEvent(event)
