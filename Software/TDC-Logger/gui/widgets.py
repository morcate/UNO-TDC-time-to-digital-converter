#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: gui/widgets.py
Description: Small reusable GUI controls (unit fields, elongating combo).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QKeyEvent, QFocusEvent, QMouseEvent
from PySide6.QtWidgets import QComboBox, QLineEdit, QListView, QWidget

from gui import styles as S


class UnitIntEdit(QLineEdit):
    """
    Integer field with a non-deletable unit suffix inside the text (e.g. 10m).
    Number is shown as two digits when possible; unit always trails the digits.
    """

    valueCommitted = Signal()

    def __init__(
        self,
        unit: str,
        value: int = 0,
        maximum: int = 99,
        minimum: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._unit = unit[-1] if unit else ""
        self._min = int(minimum)
        self._max = int(maximum)
        self._editing = False
        self.setObjectName("timeField")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.set_value(value)
        self.textChanged.connect(self._on_text_changed)

    def unit(self) -> str:
        return self._unit

    def value(self) -> int:
        digits = "".join(ch for ch in self.text() if ch.isdigit())
        if not digits:
            return self._min
        try:
            return int(digits)
        except ValueError:
            return self._min

    def set_value(self, value: int, *, pad: bool = True) -> None:
        v = max(self._min, min(self._max, int(value)))
        body = f"{v:02d}" if pad and v < 100 else str(v)
        self.blockSignals(True)
        self.setText(f"{body}{self._unit}")
        self.blockSignals(False)

    def clamp_to_max(self) -> None:
        self.set_value(self.value(), pad=True)

    def focusInEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        self._editing = True
        super().focusInEvent(event)
        # Select digits only so typing replaces the number, not the unit
        n = len(self.text()) - (1 if self._unit else 0)
        if n > 0:
            self.setSelection(0, n)

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        self._editing = False
        self.set_value(self.value(), pad=True)
        super().focusOutEvent(event)
        self.valueCommitted.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        text = event.text()
        unit_pos = max(0, len(self.text()) - (1 if self._unit else 0))

        if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            # Never erase the unit character
            start = self.selectionStart()
            end = start + self.selectionLength() if start >= 0 else -1
            cursor = self.cursorPosition()
            if self._unit and start >= 0 and end > start:
                if end > unit_pos:
                    end = unit_pos
                if start >= unit_pos:
                    event.accept()
                    return
                # rewrite selection without unit
                digits = self.text()[:unit_pos]
                new_digits = digits[:start] + digits[end:]
                self._apply_digits(new_digits, cursor=start)
                event.accept()
                return
            if key == Qt.Key.Key_Backspace and cursor > unit_pos:
                self.setCursorPosition(unit_pos)
                event.accept()
                return
            if key == Qt.Key.Key_Delete and cursor >= unit_pos:
                event.accept()
                return
            if key == Qt.Key.Key_Backspace and cursor > 0 and cursor <= unit_pos:
                digits = self.text()[:unit_pos]
                new_digits = digits[: cursor - 1] + digits[cursor:]
                self._apply_digits(new_digits, cursor=cursor - 1)
                event.accept()
                return
            if key == Qt.Key.Key_Delete and cursor < unit_pos:
                digits = self.text()[:unit_pos]
                new_digits = digits[:cursor] + digits[cursor + 1 :]
                self._apply_digits(new_digits, cursor=cursor)
                event.accept()
                return
            event.accept()
            return

        if text and text.isdigit():
            start = self.selectionStart()
            length = self.selectionLength()
            digits = "".join(ch for ch in self.text() if ch.isdigit())
            if start >= 0 and length > 0:
                # Replace selection within digit region
                unit_pos = len(digits)
                s = min(start, unit_pos)
                e = min(start + length, unit_pos)
                new_digits = digits[:s] + text + digits[e:]
                cursor = s + len(text)
            else:
                cursor = min(self.cursorPosition(), len(digits))
                new_digits = digits[:cursor] + text + digits[cursor:]
                cursor = cursor + len(text)
            # Cap length while typing (allow temp overflow until focus-out clamp)
            if len(new_digits) > 4:
                new_digits = new_digits[:4]
                cursor = min(cursor, 4)
            self._apply_digits(new_digits, cursor=cursor, pad=False)
            event.accept()
            return

        if key in (
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
            Qt.Key.Key_Home,
            Qt.Key.Key_End,
            Qt.Key.Key_Tab,
            Qt.Key.Key_Backtab,
        ):
            super().keyPressEvent(event)
            # Keep caret out of unit
            unit_pos = max(0, len(self.text()) - (1 if self._unit else 0))
            if self.cursorPosition() > unit_pos:
                self.setCursorPosition(unit_pos)
            return

        # Block other character input
        if text:
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        super().mousePressEvent(event)
        unit_pos = max(0, len(self.text()) - (1 if self._unit else 0))
        if self.cursorPosition() > unit_pos:
            self.setCursorPosition(unit_pos)

    def _apply_digits(self, digits: str, cursor: int = 0, pad: bool = False) -> None:
        digits = "".join(ch for ch in digits if ch.isdigit())
        if pad:
            try:
                v = int(digits) if digits else self._min
            except ValueError:
                v = self._min
            self.set_value(v, pad=True)
            return
        body = digits if digits else ""
        self.blockSignals(True)
        self.setText(f"{body}{self._unit}")
        self.blockSignals(False)
        self.setCursorPosition(max(0, min(cursor, len(body))))

    def _on_text_changed(self, _text: str) -> None:
        # Repair unit if stripped somehow
        if self._unit and not self.text().endswith(self._unit):
            digits = "".join(ch for ch in self.text() if ch.isdigit())
            self.blockSignals(True)
            self.setText(f"{digits}{self._unit}")
            self.blockSignals(False)


class ClearDefaultLineEdit(QLineEdit):
    """Gray default value that clears on first focus if still the default."""

    def __init__(
        self,
        default: str,
        parent: QWidget | None = None,
        object_name: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._default = default
        self._touched = False
        if object_name:
            self.setObjectName(object_name)
        self.setPlaceholderText(default)
        self.setText("")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def focusInEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        super().focusInEvent(event)
        if not self._touched and not self.text():
            # placeholder already hides on focus in most styles; keep empty
            pass

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        super().focusOutEvent(event)
        if not self.text().strip():
            self._touched = False
            self.setPlaceholderText(self._default)

    def text_or_default(self) -> str:
        t = self.text().strip()
        return t if t else self._default

    def set_committed_text(self, text: str) -> None:
        self._touched = True
        self.setText(text)


class ElongatingComboBox(QComboBox):
    """
    White combo whose popup opens downward and matches the combo width,
    visually elongating the field.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("portCombo")
        self.setMaxVisibleItems(12)
        self._before_popup = None  # optional Callable[[], None]
        view = QListView(self)
        view.setUniformItemSizes(True)
        view.setStyleSheet(
            "QListView {"
            "  background-color: #ffffff;"
            "  color: #000000;"
            "  border: 1px solid #000000;"
            "  border-top: none;"
            "  outline: 0;"
            "}"
            "QListView::item {"
            "  background-color: #ffffff;"
            "  color: #000000;"
            "  min-height: 24px;"
            "  padding: 4px 8px;"
            "  font-family: Arial;"
            "}"
            "QListView::item:selected {"
            f"  background-color: {S.ACCENT};"
            "  color: #000000;"
            "}"
            "QListView::item:hover {"
            "  background-color: #d7e6ea;"
            "  color: #000000;"
            "}"
        )
        self.setView(view)
        self.setStyleSheet(
            "QComboBox {"
            "  background-color: #ffffff;"
            f"  color: {S.FG_FIELD};"
            "  border: none;"
            "  padding: 2px 6px;"
            "  font-family: Arial;"
            "  font-size: 13px;"
            "}"
            "QComboBox QAbstractItemView {"
            "  background-color: #ffffff;"
            "  color: #000000;"
            "  border: 1px solid #000000;"
            "  border-top: none;"
            "  outline: 0;"
            "}"
        )

    def set_before_popup(self, fn) -> None:
        """Hook run immediately before the dropdown opens (e.g. rescan COM ports)."""
        self._before_popup = fn

    def showPopup(self) -> None:  # noqa: N802
        if callable(self._before_popup):
            try:
                self._before_popup()
            except Exception as exc:
                print(f"[port combo] before_popup failed: {exc}")
        super().showPopup()
        try:
            popup = self.view().window()
            # Match the combo (or outer frame if parent is portFrame) width
            target = self.parentWidget() if self.parentWidget() is not None else self
            width = max(self.width(), target.width())
            popup.setFixedWidth(width)
            # Force below the field
            below = self.mapToGlobal(self.rect().bottomLeft())
            if target is not self:
                below = target.mapToGlobal(target.rect().bottomLeft())
            popup.move(below.x(), below.y() - 1)
        except Exception:
            # Popup still usable even if geometry tweak fails
            pass


def bold_font(base: QFont | None = None) -> QFont:
    f = QFont(base) if base is not None else QFont("Arial")
    f.setFamily("Arial")
    f.setBold(True)
    return f
