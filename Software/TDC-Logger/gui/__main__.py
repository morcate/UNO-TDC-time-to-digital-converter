#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""python -m gui  from Software/TDC-Logger."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure TDC-Logger root is on path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication
        from gui.main_window import MainWindow
    except ImportError as exc:
        print(f"Missing dependency: {exc}", file=sys.stderr)
        print("Install with: pip install PySide6 matplotlib numpy pyserial", file=sys.stderr)
        return 1
    try:
        app = QApplication(sys.argv)
        app.setApplicationName("TDC-Logger")
        app.setStyle("Fusion")  # consistent cross-platform base for mockup QSS
        win = MainWindow()
        win.show()
        return int(app.exec())
    except Exception as exc:
        print(f"GUI failed to start: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
