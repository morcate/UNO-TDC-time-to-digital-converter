#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: gui/styles.py
Description: Colors/fonts/borders from GUI mockup SVGs + correction sheet.
"""

from __future__ import annotations

from pathlib import Path

BG_APP = "#b7c4c8"
BG_TOP = "#f2f2f2"
BG_SIDE = "#f2f2f2"
BG_SEC = "#93a7ac"
BG_CENTER = "#b7c4c8"
BG_INPUT = "#ffffff"
FG_LOGO = "#bababa"
FG_TEXT = "#000000"
FG_HINT = "#808080"
FG_PLACEHOLDER = "#53676c"
FG_FIELD = "#6f8a91"
ACCENT = "#2c89a0"
BTN_START = "#ffdd55"
BTN_STOP = "#ff5555"
BORDER = "#000000"

TOP_H = 84
SIDE_W = 340
SEC_H = 92
START_W = 136
START_H = 52

INPUT_H = 24

# ~50% thicker chrome lines (1px -> 2px); START was 2px -> 3px
BORDER_W = 2
BTN_BORDER_W = 3
DIVIDER_H = 2

FREEZE_OPACITY = 0.42
SEC_MIN_CONTENT_W = 720

# Corner tab 20% larger than 64px / 8pt
CORNER_TAB = 77
CORNER_FONT = 10

# Font sizes ~10% larger than previous set
FS_LOGO = 44
FS_SAVE = 18
FS_SECTION = 18
FS_BODY = 14
FS_HINT = 13
FS_STAT = 14
FS_PLACEHOLDER = 29
FS_COLON = 15
FS_UNIT = 14
FS_FIELD = 14
FS_PORT = 14
FS_CHEV = 13
FS_SEC = 13
FS_HIST_CHECK = 12
FS_START = 29
FS_RADIO = 14


def _icon_url(name: str) -> str:
    path = (Path(__file__).resolve().parent / "_icons" / name).as_posix()
    return path


_RADIO_OFF = _icon_url("radio_off.svg")
_RADIO_ON = _icon_url("radio_on.svg")
_CHECK_OFF = _icon_url("check_off.svg")
_CHECK_ON = _icon_url("check_on.svg")

APP_QSS = f"""
* {{
    font-family: Arial, Helvetica, sans-serif;
    color: {FG_TEXT};
}}
QMainWindow, QWidget#centralRoot {{
    background-color: {BG_APP};
}}
QFrame#topBar {{
    background-color: {BG_TOP};
    border: none;
    border-bottom: {BORDER_W}px solid {BORDER};
}}
QLabel#saveLabel {{
    color: {FG_TEXT};
    font-size: {FS_SAVE}px;
    font-family: Arial, Helvetica, sans-serif;
}}
QLineEdit#saveField {{
    background-color: {BG_INPUT};
    color: {FG_FIELD};
    border: {BORDER_W}px solid {BORDER};
    padding: 2px 8px;
    font-size: {FS_SAVE}px;
    font-family: Arial, Helvetica, sans-serif;
    min-height: {INPUT_H}px;
    max-height: {INPUT_H + 4}px;
}}
QLineEdit#saveField:focus {{
    color: {FG_TEXT};
}}
QPushButton#browseBtn {{
    background-color: {BG_INPUT};
    color: {FG_TEXT};
    border: {BORDER_W}px solid {BORDER};
    padding: 2px 12px;
    font-size: {FS_SAVE}px;
    font-weight: 400;
    font-family: Arial, Helvetica, sans-serif;
    min-height: {INPUT_H}px;
}}
QFrame#secBar {{
    background-color: {BG_SEC};
    border: none;
    border-bottom: {BORDER_W}px solid {BORDER};
    min-height: {SEC_H}px;
}}
QFrame#secBar QLabel {{
    color: {FG_TEXT};
    font-size: {FS_SEC}px;
    font-family: Arial, Helvetica, sans-serif;
}}
QFrame#secBar QCheckBox {{
    color: {FG_TEXT};
    font-family: Arial, Helvetica, sans-serif;
}}
QFrame#secBar QLineEdit {{
    min-height: {INPUT_H}px;
    max-height: {INPUT_H + 2}px;
    font-size: {FS_SEC}px;
    font-family: Arial, Helvetica, sans-serif;
    color: {FG_FIELD};
}}
QWidget#sidePanel, QWidget#sideInner, QScrollArea#sideScroll {{
    background-color: {BG_SIDE};
    border: none;
}}
QScrollArea#sideScroll {{
    border-right: {BORDER_W}px solid {BORDER};
}}
QScrollArea#sideScroll QScrollBar:vertical {{
    background: {BORDER};
    width: 14px;
    margin: 0;
    border: none;
}}
QScrollArea#sideScroll QScrollBar::handle:vertical {{
    background: #444444;
    min-height: 40px;
    margin: 2px;
    border-radius: 0px;
}}
QScrollArea#sideScroll QScrollBar::add-line:vertical,
QScrollArea#sideScroll QScrollBar::sub-line:vertical {{
    height: 0px;
    border: none;
    background: none;
}}
QScrollArea#sideScroll QScrollBar::add-page:vertical,
QScrollArea#sideScroll QScrollBar::sub-page:vertical {{
    background: {BORDER};
}}
QLabel#sectionTitle {{
    color: {FG_TEXT};
    font-size: {FS_SECTION}px;
    font-weight: 700;
    font-family: Arial, Helvetica, sans-serif;
}}
QLabel#bodyText {{
    color: {FG_TEXT};
    font-size: {FS_BODY}px;
    font-family: Arial, Helvetica, sans-serif;
}}
QLabel#hintText {{
    color: {FG_HINT};
    font-size: {FS_HINT}px;
    padding-left: 24px;
    font-family: Arial, Helvetica, sans-serif;
}}
QLabel#statKey, QLabel#statVal {{
    color: {FG_TEXT};
    font-size: {FS_STAT}px;
    font-family: Arial, Helvetica, sans-serif;
}}
QLabel#placeholderLabel {{
    color: {FG_PLACEHOLDER};
    font-size: {FS_PLACEHOLDER}px;
    font-weight: 700;
    font-family: Arial, Helvetica, sans-serif;
}}
QLabel#colon {{
    color: {FG_TEXT};
    font-size: {FS_COLON}px;
    font-family: Arial, Helvetica, sans-serif;
}}
QLabel#unitSuffix {{
    color: {FG_TEXT};
    font-size: {FS_UNIT}px;
    font-weight: 600;
    background: transparent;
    border: none;
    padding: 0 2px;
}}
QFrame#divider {{
    background-color: {BORDER};
    max-height: {DIVIDER_H}px;
    min-height: {DIVIDER_H}px;
    border: none;
}}
QFrame#portFrame {{
    background-color: {BG_INPUT};
    border: {BORDER_W}px solid {BORDER};
}}
QComboBox#portCombo {{
    background-color: {BG_INPUT};
    color: {FG_FIELD};
    border: none;
    padding: 2px 6px;
    font-size: {FS_PORT}px;
    font-family: Arial, Helvetica, sans-serif;
    min-height: {INPUT_H}px;
}}
QComboBox#portCombo::drop-down {{
    border: none;
    width: 0px;
}}
QComboBox#portCombo::down-arrow {{
    image: none;
    width: 0px;
    height: 0px;
}}
QLabel#portChevron {{
    background-color: {BG_INPUT};
    color: {FG_TEXT};
    font-size: {FS_CHEV}px;
    padding: 0 8px 0 4px;
    border: none;
}}
QLineEdit {{
    background-color: {BG_INPUT};
    color: {FG_FIELD};
    border: {BORDER_W}px solid {BORDER};
    padding: 2px 6px;
    font-size: {FS_FIELD}px;
    font-family: Arial, Helvetica, sans-serif;
    min-height: {INPUT_H}px;
    max-height: {INPUT_H + 4}px;
}}
QLineEdit:focus {{
    color: {FG_TEXT};
}}
QLineEdit:disabled {{
    background-color: #e8e8e8;
    color: #9a9a9a;
    border: {BORDER_W}px solid #888888;
}}
QLineEdit::placeholder {{
    color: {FG_FIELD};
}}
QLineEdit#timeField {{
    background-color: {BG_INPUT};
    color: {FG_FIELD};
    border: {BORDER_W}px solid {BORDER};
    min-width: 48px;
    max-width: 56px;
    min-height: {INPUT_H}px;
    max-height: {INPUT_H + 2}px;
    padding: 1px 2px;
    font-size: {FS_FIELD}px;
    font-family: Arial, Helvetica, sans-serif;
}}
QLineEdit#samplesField, QLineEdit#limField {{
    background-color: {BG_INPUT};
    color: {FG_FIELD};
    border: {BORDER_W}px solid {BORDER};
    min-height: {INPUT_H}px;
    max-height: {INPUT_H + 4}px;
    max-width: 240px;
}}
QRadioButton {{
    color: {FG_TEXT};
    font-size: {FS_RADIO}px;
    spacing: 8px;
    font-family: Arial, Helvetica, sans-serif;
}}
QRadioButton::indicator {{
    width: 14px;
    height: 14px;
    border: none;
    background: transparent;
    image: url({_RADIO_OFF});
}}
QRadioButton::indicator:checked {{
    image: url({_RADIO_ON});
}}
QCheckBox {{
    color: {FG_TEXT};
    font-size: {FS_RADIO}px;
    spacing: 8px;
    font-family: Arial, Helvetica, sans-serif;
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: none;
    background: transparent;
    image: url({_CHECK_OFF});
}}
QCheckBox::indicator:checked {{
    image: url({_CHECK_ON});
}}
QCheckBox#histCheck {{
    font-size: {FS_HIST_CHECK}px;
    font-weight: 700;
    color: {FG_TEXT};
}}
QPushButton#startBtn {{
    background-color: {BTN_START};
    color: {FG_TEXT};
    border: {BTN_BORDER_W}px solid {BORDER};
    border-radius: 12px;
    font-size: {FS_START}px;
    font-weight: 700;
    font-family: Arial, Helvetica, sans-serif;
    min-width: {START_W}px;
    max-width: {START_W}px;
    min-height: {START_H}px;
    max-height: {START_H}px;
    padding: 2px 8px;
}}
QPushButton#startBtn[running="true"] {{
    background-color: {BTN_STOP};
}}
QFrame#centerFrame {{
    background-color: {BG_CENTER};
    border: none;
}}
QWidget#histMenuHost {{
    background: transparent;
}}
"""
