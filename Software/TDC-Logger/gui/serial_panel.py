#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: gui/serial_panel.py
Description: Scrollable serial / log monitor for GUI mode (Hack monospace).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QTextCursor
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget

# Bundled Warp-like terminal face (SIL OFL Hack)
_BUNDLED_HACK = Path(__file__).resolve().parent / "fonts" / "Hack-Regular.ttf"
_HACK_LOADED = False

# Prefer Hack (bundled or system), then common monospace fallbacks.
_SERIAL_FONT_CANDIDATES = (
    "Hack",
    "Hack Nerd Font",
    "Hack Nerd Font Mono",
    "JetBrains Mono",
    "Cascadia Mono",
    "Cascadia Code",
    "Consolas",
    "Courier New",
    "monospace",
)


def _ensure_bundled_hack() -> None:
    """Register gui/fonts/Hack-Regular.ttf once so QFont('Hack') resolves."""
    global _HACK_LOADED
    if _HACK_LOADED:
        return
    try:
        if _BUNDLED_HACK.is_file():
            fid = QFontDatabase.addApplicationFont(str(_BUNDLED_HACK))
            if fid == -1:
                print(f"[serial_panel] failed to load bundled font: {_BUNDLED_HACK}")
            else:
                _HACK_LOADED = True
    except Exception as exc:
        print(f"[serial_panel] font load error: {exc}")


def _pick_serial_font(point_size: int = 11) -> QFont:
    """Resolve Hack (Warp-like) or the best available monospace face."""
    _ensure_bundled_hack()
    try:
        available = {name.casefold() for name in QFontDatabase.families()}
    except Exception:
        available = set()

    chosen = "monospace"
    for name in _SERIAL_FONT_CANDIDATES:
        if name.casefold() in available or name == "monospace":
            chosen = name
            break

    font = QFont(chosen)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    font.setPointSize(int(point_size))
    return font


class SerialMonitorPanel(QWidget):
    """Append-only text view with a hard line cap and corner-tab clearance."""

    def __init__(self, max_lines: int = 2000, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._max_lines = max(200, int(max_lines))

        # Live serial text fills the panel; NO DATA is a centered overlay (same as hist).
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        # Padding clears the SERIAL/HISTO triangle button for live text only
        self._view.setStyleSheet(
            "QPlainTextEdit {"
            "  background-color: #000000;"
            "  color: #e8e8e8;"
            "  border: 1px solid #000000;"
            "  padding-top: 52px;"
            "  padding-left: 64px;"
            "  padding-right: 12px;"
            "  padding-bottom: 12px;"
            "  font-family: 'Hack', 'Hack Nerd Font Mono', 'JetBrains Mono',"
            "               'Cascadia Mono', Consolas, 'Courier New', monospace;"
            "  font-size: 12pt;"
            "}"
        )
        self._view.setFont(_pick_serial_font(12))
        root.addWidget(self._view)

        # True geometric center of the panel (matches LiveHistPanel empty label)
        self._placeholder = QLabel("NO DATA", self)
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._placeholder.setStyleSheet(
            "color: #53676c; font-size: 29px; font-weight: 700; font-family: Arial;"
            "background: transparent; border: none;"
        )
        self._placeholder.raise_()
        self._has_text = False
        self._set_empty_visible(True)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._layout_empty_label()

    def _layout_empty_label(self) -> None:
        if hasattr(self, "_placeholder"):
            self._placeholder.setGeometry(self.rect())

    def _set_empty_visible(self, visible: bool) -> None:
        self._layout_empty_label()
        self._placeholder.setVisible(bool(visible))
        if visible:
            self._placeholder.raise_()

    def clear(self) -> None:
        self._view.clear()
        self._has_text = False
        self._set_empty_visible(True)

    def show_placeholder_if_empty(self) -> None:
        if not self._has_text:
            self._set_empty_visible(True)

    def append_line(self, text: str) -> None:
        try:
            if not self._has_text:
                self._has_text = True
                self._set_empty_visible(False)
            self._view.appendPlainText(text.rstrip("\n"))
            doc = self._view.document()
            while doc.blockCount() > self._max_lines:
                cursor = QTextCursor(doc.firstBlock())
                cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                cursor.removeSelectedText()
                cursor.deleteChar()
            self._view.moveCursor(QTextCursor.MoveOperation.End)
        except Exception as exc:
            self._has_text = True
            self._set_empty_visible(False)
            self._view.appendPlainText(f"[monitor error] {exc}")
