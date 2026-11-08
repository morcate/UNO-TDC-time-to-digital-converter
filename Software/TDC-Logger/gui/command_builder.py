#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: gui/command_builder.py
Description: Map GUI form state to TDC-Logger CLI argv (always includes -a and --gui).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class GuiFormState:
    """User selections from the mockup sidebar / top bar."""

    port: str = ""
    mode: int = 1
    # acquire_until: "user" | "time" | "samples"
    acquire_until: str = "samples"
    time_days: int = 0
    time_hours: int = 0
    time_minutes: int = 10
    max_samples: int = 10000
    timestamps: bool = False
    save_raw: bool = True
    lim_sup_enabled: bool = False
    lim_sup_ns: float = 27000.0
    output_name: str = "session"
    output_dir: str = ""
    baud: int = 38400


class CommandBuildError(ValueError):
    """Invalid form state for building a CLI command."""


def build_cli_argv(state: GuiFormState, main_py: Path, python_exe: str) -> List[str]:
    """
    Build subprocess argv for:
      python -u main.py start -a --gui ...
    """
    if not state.port or not str(state.port).strip():
        raise CommandBuildError("Serial port is required")
    if state.mode not in (1, 2):
        raise CommandBuildError("Measurement mode must be 1 or 2")

    out_name = (state.output_name or "session").strip()
    if not out_name:
        raise CommandBuildError("Output name is required")

    # Resolve -o: if directory set, use path/name stem
    out_arg = out_name
    if state.output_dir:
        out_dir = Path(state.output_dir)
        if not out_dir.is_dir():
            raise CommandBuildError(f"Output directory does not exist: {out_dir}")
        out_arg = str(out_dir / Path(out_name).stem)

    argv: List[str] = [
        python_exe,
        "-u",
        str(main_py),
        "start",
        "-a",
        "--gui",
        "-p",
        str(state.port).strip(),
        "--mode",
        str(int(state.mode)),
        "-b",
        str(int(state.baud)),
        "-o",
        out_arg,
    ]

    if state.timestamps:
        argv.append("-t")

    if state.acquire_until == "time":
        d = max(0, int(state.time_days))
        h = max(0, min(23, int(state.time_hours)))
        m = max(0, min(59, int(state.time_minutes)))
        if d == 0 and h == 0 and m == 0:
            raise CommandBuildError("Time limit must be greater than zero")
        if d > 30:
            raise CommandBuildError("Time limit days cannot exceed 30")
        parts = []
        if d:
            parts.append(f"{d}d")
        if h:
            parts.append(f"{h}h")
        if m:
            parts.append(f"{m}m")
        argv.extend(["-T", " ".join(parts)])
    elif state.acquire_until == "samples":
        n = int(state.max_samples)
        if n < 1:
            raise CommandBuildError("Number of measurements must be >= 1")
        argv.extend(["-m", str(n)])
    elif state.acquire_until == "user":
        pass
    else:
        raise CommandBuildError(f"Unknown acquire_until: {state.acquire_until}")

    if state.lim_sup_enabled:
        lim = float(state.lim_sup_ns)
        if lim <= 0:
            raise CommandBuildError("Ignore-above threshold must be positive")
        argv.extend(["-l", str(lim)])

    # save_raw unchecked => parsed only is not supported by CLI dual logger today;
    # when False we still write both (document). Future: dedicated flag.
    _ = state.save_raw

    return argv


def argv_to_preview(argv: List[str]) -> str:
    """Shell-ish preview string for the UI (display only)."""
    parts: List[str] = []
    for a in argv:
        if " " in a or a == "":
            parts.append(f'"{a}"')
        else:
            parts.append(a)
    return " ".join(parts)
