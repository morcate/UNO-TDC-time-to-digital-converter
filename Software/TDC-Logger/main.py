#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: main.py
Version: 1.1.0
Date: 2026-10-26
Author: Gemini
Description: CLI entry point and main orchestration engine for the Serial TDC Logger.
Requirements: pyserial>=3.5, numpy>=1.24.0, matplotlib>=3.7.0
Installation: pip install -r requirements.txt

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

import argparse
import queue
import re
import signal
import sys
import threading
import time
from typing import Optional, Tuple

from config import (
    DEFAULT_BAUD_RATE,
    DEFAULT_MEASUREMENT_MODE,
    HANDSHAKE_MENU_TIMEOUT_SEC,
    HANDSHAKE_START_BYTE,
    HANDSHAKE_STEP_TIMEOUT_SEC,
    MAX_TIME_DAYS,
    SECONDS_PER_DAY,
    SECONDS_PER_HOUR,
    SECONDS_PER_MINUTE,
)
import serial

from serial_manager import SerialManager
from processors import ProcessResult, TdcProcessor
from file_logger import DualFileLogger
from histogram_manager import RootHistogramManager
from gui_protocol import (
    EVT_ARMED,
    EVT_FINISHED,
    EVT_RUNNING,
    EVT_STARTING,
    EVT_STOPPING,
    GuiStreamEmitter,
    configure_stdio_for_gui,
)
from stdin_stop import StdinStopWatcher


DETAILED_HELP_EN = """
==============================================================================
                DETAILED OPERATION & ARCHITECTURE MANUAL
==============================================================================
1. FIRMWARE v2 SESSION & HANDSHAKE:
   - Opening the port typically resets the UNO into the mode menu.
   - Board prompts: SELECT MEASUREMENT MODE (press 1 or 2), then
     "Press any key to start acquisition".
   - --mode {1,2} (default 1) selects the parser and, with -a, the digit sent.
   - -a / --auto-start runs the automatic handshake once:
       wait for mode menu -> send '1' or '2' -> wait for confirmation ->
       wait for start prompt -> send start byte ('a').
   - Without -a, type 1/2 and a start key yourself (keyboard TX still works).
   - Mode is fixed for the whole run (no mid-run change).
   - Non-register text is printed and stored in <NAME>_raw.log only.

2. REGISTER PARSING & ToF CALCULATION:
   - Mode 1 (9 ints): [t1_2 t1_1 t1_0 c1_2 c1_1 c1_0 c2_2 c2_1 c2_0]
       tof = (time1 * 562.5) / (cal2 - cal1)
   - Mode 2 (15 ints): time1[3] clock_count1[3] time2[3] cal1[3] cal2[3]
       tof = 62.5*cc1 + 562.5*(time1-time2)/(cal2-cal1)
   - 24-bit rebuild: REG = (MSB * 65536) + (MID * 256) + LSB.
   - Range filtering:
       * If 0 <= tof < lim_sup : Stop IN -> <NAME>.log (+ hist if -g)
       * If tof >= lim_sup     : Stop OUT (raw only)

3. OUTPUT DIRECTORY & ANTI-OVERWRITE NAMING:
   - Uses the requested base name if free (e.g., ./TEST/), otherwise appends
     an incremental index (./TEST_1/, ./TEST_2/, ...).
   - Generated files inside the folder:
       * <NAME>_raw.log  : All raw serial traffic (with optional -t timestamp).
       * <NAME>.log      : Valid Stop IN ToF measurements only (no timestamp).
       * <NAME>_hist.png : High-resolution (600 DPI) histogram (only with -g).

4. REAL-TIME HISTOGRAM & CERN ROOT STATISTICS (OPTION -g):
   - Stores every valid ToF unbinned; each refresh fully rebuilds the histogram
     (new edges + refill of all samples from scratch — never merges old bins).
   - Live X/Y axis rescaling follows the parsed data range and bin heights.
   - Occupied bins are kept generally at >= 10 entries (less-populated bins included).
   - Mean and Std Dev follow CERN ROOT TH1 unbinned accumulators
     (fTsumw, fTsumwx, fTsumwx2 with unit weights).

5. STOP CONDITIONS (mutually exclusive; both optional):
   - -m / --max-samples N
       Stop after N valid in-range samples (Stop IN). N is a positive integer.
   - -T / --max-time "Nd Nh Nm"
       Stop after an acquisition wall-time limit. Units may be combined, e.g.
       "10d 3h 45m", "2h", "45m", "1d 30m". Order is free; each unit at most once.
       Maximum allowed duration: 31 days. Quote the value if it contains spaces.
   - Only one of --max-samples or --max-time may be set (or neither).

6. USAGE EXAMPLES:
   - Mode 1 auto-handshake, histogram, 10000 samples:
     python main.py start -a --mode 1 -t -m 10000 -l 5000.0 -o TEST -g
   - Mode 2 auto-handshake:
     python main.py start -a --mode 2 -o RUN_M2 -g
   - Time-limited run (10 days, 3 hours, 45 minutes):
     python main.py start -a -T "10d 3h 45m" -o LONG_RUN -g
   - Manual handshake (you type 1/2 and a key), mode-1 parsing:
     python main.py start --mode 1 -o MANUAL
   - Stream only:
     python main.py start -a --stream-only
==============================================================================
"""


# Matches one duration token: integer + unit d/h/m (case-insensitive), optional spaces.
_MAX_TIME_TOKEN_RE = re.compile(r"(\d+)\s*([dhm])", re.IGNORECASE)


def parse_measurement_mode(value: str) -> int:
    """Validate --mode as 1 or 2."""
    try:
        mode = int(value, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"mode must be integer 1 or 2, got {value!r}"
        ) from exc
    if mode not in (1, 2):
        raise argparse.ArgumentTypeError(f"mode must be 1 or 2, got {mode}")
    return mode


def parse_max_samples(value: str) -> int:
    """Validate --max-samples as a positive integer."""
    try:
        n = int(value, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"max-samples must be an integer, got {value!r}"
        ) from exc
    if n <= 0:
        raise argparse.ArgumentTypeError("max-samples must be a positive integer (>= 1)")
    return n


def parse_max_time(value: str) -> float:
    """
    Parse --max-time into seconds.

    Accepted forms (spaces optional between tokens; quote if spaces are used):
      10d 3h 45m | 10d3h45m | 2h | 45m | 1d 30m | 3H 10M

    Rules:
      - Units: d (days), h (hours), m (minutes); each unit at most once.
      - At least one positive component is required.
      - Total duration must not exceed MAX_TIME_DAYS (31) days.
    """
    raw = value.strip()
    if not raw:
        raise argparse.ArgumentTypeError("max-time must not be empty")

    tokens = _MAX_TIME_TOKEN_RE.findall(raw)
    # Reject leftover junk (e.g. '10d xyz', '10', '10s')
    leftover = _MAX_TIME_TOKEN_RE.sub("", raw)
    leftover = re.sub(r"\s+", "", leftover)
    if not tokens or leftover:
        raise argparse.ArgumentTypeError(
            f"invalid max-time {value!r}; use forms like '10d 3h 45m', '2h', '45m' "
            f"(units d/h/m only)"
        )

    days = hours = minutes = 0
    seen_units = set()
    for num_str, unit in tokens:
        u = unit.lower()
        if u in seen_units:
            raise argparse.ArgumentTypeError(
                f"duplicate unit '{u}' in max-time {value!r}"
            )
        seen_units.add(u)
        n = int(num_str)
        if u == "d":
            days = n
        elif u == "h":
            hours = n
        else:
            minutes = n

    total_sec = (
        days * SECONDS_PER_DAY
        + hours * SECONDS_PER_HOUR
        + minutes * SECONDS_PER_MINUTE
    )
    if total_sec <= 0:
        raise argparse.ArgumentTypeError("max-time must be greater than zero")

    max_sec = MAX_TIME_DAYS * SECONDS_PER_DAY
    if total_sec > max_sec:
        raise argparse.ArgumentTypeError(
            f"max-time cannot exceed {MAX_TIME_DAYS} days "
            f"(got {format_duration_seconds(total_sec)})"
        )
    return float(total_sec)


def format_duration_seconds(total_sec: float) -> str:
    """Format a second count back to a compact Nd Nh Nm string for display."""
    sec = int(round(total_sec))
    days, rem = divmod(sec, SECONDS_PER_DAY)
    hours, rem = divmod(rem, SECONDS_PER_HOUR)
    minutes, _ = divmod(rem, SECONDS_PER_MINUTE)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts)


class DetailedHelpAction(argparse.Action):
    """Custom action triggered by -hh to print short help followed by detailed English manual."""

    def __init__(self, option_strings, dest=argparse.SUPPRESS, default=argparse.SUPPRESS, help=None):
        super().__init__(
            option_strings=option_strings,
            dest=dest,
            default=default,
            nargs=0,
            help=help,
        )

    def __call__(self, parser, namespace, values, option_string=None):
        parser.print_help()
        print(DETAILED_HELP_EN)
        parser.exit()


def build_arg_parser() -> argparse.ArgumentParser:
    """Configures a concise CLI parser (-h) with an extended English manual option (-hh)."""
    # Instantiate root parser without verbose description
    parser = argparse.ArgumentParser(prog="main.py")
    parser.add_argument(
        "-hh", "--help-detailed",
        action=DetailedHelpAction,
        help="Show detailed technical documentation and usage examples in English and exit",
    )

    # Register subcommands: start (logging) and ports (list COM devices)
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    start_parser = subparsers.add_parser(
        "start",
        help="Start serial logging session (use 'start -h' for options, 'start -hh' for full manual)",
    )
    ports_parser = subparsers.add_parser(
        "ports",
        help="List detected serial ports ranked for Arduino / USB-UART likelihood",
    )
    # ports_parser kept for future flags; currently no extra options
    _ = ports_parser

    # Extended English help flag (-hh / --help-detailed)
    start_parser.add_argument(
        "-hh", "--help-detailed",
        action=DetailedHelpAction,
        help="Show detailed technical documentation and usage examples in English and exit",
    )

    # Serial port: omit for auto/prompt, or pass -p COMx (also accepts bare '3' on Windows)
    start_parser.add_argument(
        "-p", "--port", type=str, default=None, metavar="COMx",
        help="Serial port (e.g. COM3 or 3). Omit to auto-select Arduino / prompt if ambiguous",
    )
    start_parser.add_argument(
        "-i", "--interactive-port", action="store_true",
        help="Always show the port menu (skip auto-select)",
    )

    # Serial baud rate configuration (-b / --baud)
    start_parser.add_argument(
        "-b", "--baud", type=int, default=DEFAULT_BAUD_RATE, metavar="BPS",
        help=f"Baud rate (default: {DEFAULT_BAUD_RATE})",
    )

    # Measurement mode (parser + handshake digit); fixed for the session
    start_parser.add_argument(
        "--mode", type=parse_measurement_mode, default=DEFAULT_MEASUREMENT_MODE,
        metavar="{1,2}",
        help=f"TDC measurement mode (default: {DEFAULT_MEASUREMENT_MODE})",
    )

    # Automatic firmware handshake (-a): mode digit + start byte
    start_parser.add_argument(
        "-a", "--auto-start", action="store_true",
        help=(
            "Auto firmware handshake: wait for mode menu, send --mode digit, "
            "wait for confirmation and start prompt, then send start byte"
        ),
    )

    # GUI subprocess mode: NDJSON on stdout, no CLI histogram, STOP via stdin
    start_parser.add_argument(
        "--gui",
        action="store_true",
        help=(
            "Machine mode for the desktop GUI: NDJSON events on stdout, "
            "human logs on stderr, no CLI histogram; stop with stdin line STOP"
        ),
    )

    # Raw log timestamping flag (-t / --timestamp)
    start_parser.add_argument(
        "-t", "--timestamp", action="store_true",
        help="Enable line timestamp in <NAME>_raw.log",
    )

    # Mutually exclusive stop conditions: max samples XOR max wall time (or neither)
    stop_group = start_parser.add_mutually_exclusive_group()
    stop_group.add_argument(
        "-m", "--max-samples", type=parse_max_samples, default=None, metavar="N",
        help="Stop after N valid in-range samples (Stop IN); positive integer",
    )
    stop_group.add_argument(
        "-T", "--max-time", type=parse_max_time, default=None, metavar="DURATION",
        help=(
            f"Stop after wall time, e.g. '10d 3h 45m' or '45m' "
            f"(units d/h/m; max {MAX_TIME_DAYS} days; quote if spaces)"
        ),
    )

    # Upper threshold filter for ToF calculation (-l / --lim-sup)
    start_parser.add_argument(
        "-l", "--lim-sup", type=float, default=None, metavar="MAX",
        help="Upper threshold (lim_sup) for valid ToF measurements",
    )

    # Base name for output directory and log files (-o / --out)
    start_parser.add_argument(
        "-o", "--out", type=str, default=None, metavar="NAME",
        help="Base name for output folder and log files",
    )

    # Real-time histogram and high-res export toggle (-g / --hist)
    start_parser.add_argument(
        "-g", "--hist", action="store_true",
        help="Enable real-time ROOT histogram and high-res image export",
    )

    # Raw-only logging mode (--raw-only)
    start_parser.add_argument(
        "--raw-only", action="store_true",
        help="Log only <NAME>_raw.log and disable ToF parsing",
    )

    # Terminal stream-only monitoring mode (--stream-only)
    start_parser.add_argument(
        "--stream-only", action="store_true",
        help="Stream serial output to terminal without saving any files",
    )

    return parser


def _user_print(*args: object, gui_mode: bool = False, **kwargs: object) -> None:
    """Human-readable print: stderr when --gui so stdout stays NDJSON-only."""
    if gui_mode:
        kwargs.setdefault("file", sys.stderr)
        kwargs.setdefault("flush", True)
    print(*args, **kwargs)  # type: ignore[arg-type]


def _log_handshake_line(
    line: str,
    file_logger: Optional[DualFileLogger],
    *,
    gui_mode: bool = False,
    gui_stream: Optional[GuiStreamEmitter] = None,
) -> None:
    """Print and optionally raw-log a firmware banner/handshake line."""
    # GUI serial monitor already shows 'raw'; emit once (not log+raw).
    if gui_stream is not None:
        gui_stream.raw(line)
    else:
        _user_print(line, gui_mode=gui_mode)
    if file_logger is not None:
        try:
            file_logger.log_raw(line, is_measurement=False)
        except OSError as exc:
            _user_print(f"[WARN] raw log write failed: {exc}", gui_mode=gui_mode)


def _wait_for_rx_substring(
    rx_queue: queue.Queue,
    stop_event: threading.Event,
    needle: str,
    timeout_sec: float,
    file_logger: Optional[DualFileLogger],
    label: str,
    *,
    gui_mode: bool = False,
    gui_stream: Optional[GuiStreamEmitter] = None,
) -> str:
    """
    Block until a queued serial line contains needle (case-insensitive).

    Intermediate lines are printed/logged as text. Raises TimeoutError / RuntimeError.
    """
    needle_l = needle.lower()
    deadline = time.monotonic() + timeout_sec
    while not stop_event.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Timeout waiting for {label} ({needle!r})")
        try:
            line = rx_queue.get(timeout=min(0.2, remaining))
        except queue.Empty:
            continue
        _log_handshake_line(
            line, file_logger, gui_mode=gui_mode, gui_stream=gui_stream
        )
        if needle_l in line.lower():
            return line
    raise RuntimeError(f"Stopped while waiting for {label}")


def perform_firmware_handshake(
    serial_mgr: SerialManager,
    rx_queue: queue.Queue,
    stop_event: threading.Event,
    mode: int,
    file_logger: Optional[DualFileLogger] = None,
    *,
    gui_mode: bool = False,
    gui_stream: Optional[GuiStreamEmitter] = None,
) -> None:
    """
    Automatic handshake with firmware v2 (no legacy path).

    1. Wait for mode menu text
    2. Send mode digit ('1' or '2')
    3. Wait for "selected measurement mode"
    4. Wait for start prompt
    5. Send start byte (HANDSHAKE_START_BYTE)
    """
    if mode not in (1, 2):
        raise ValueError(f"invalid mode {mode}")

    _user_print(f"[INFO] Firmware handshake: mode {mode}", gui_mode=gui_mode)

    wait_kw = {"gui_mode": gui_mode, "gui_stream": gui_stream}
    _wait_for_rx_substring(
        rx_queue,
        stop_event,
        "SELECT MEASUREMENT MODE",
        HANDSHAKE_MENU_TIMEOUT_SEC,
        file_logger,
        "mode menu",
        **wait_kw,
    )
    if stop_event.is_set():
        raise RuntimeError("Stopped during handshake")

    mode_byte = str(mode).encode("ascii")
    serial_mgr.write_bytes(mode_byte)
    _user_print(f"[INFO] Sent mode digit: {mode}", gui_mode=gui_mode)

    confirm = _wait_for_rx_substring(
        rx_queue,
        stop_event,
        "selected measurement mode",
        HANDSHAKE_STEP_TIMEOUT_SEC,
        file_logger,
        "mode confirmation",
        **wait_kw,
    )
    if str(mode) not in confirm:
        raise RuntimeError(
            f"Mode mismatch: expected mode {mode} in confirmation line: {confirm!r}"
        )

    _wait_for_rx_substring(
        rx_queue,
        stop_event,
        "Press any key to start",
        HANDSHAKE_STEP_TIMEOUT_SEC,
        file_logger,
        "start prompt",
        **wait_kw,
    )
    if stop_event.is_set():
        raise RuntimeError("Stopped during handshake")

    # Firmware flushes CR/LF after mode select; send a dedicated start key.
    time.sleep(0.05)
    serial_mgr.write_bytes(HANDSHAKE_START_BYTE)
    _user_print(f"[INFO] Sent start byte: {HANDSHAKE_START_BYTE!r}", gui_mode=gui_mode)
    _user_print("[INFO] Handshake complete; acquisition armed.\n", gui_mode=gui_mode)
    if gui_stream is not None:
        gui_stream.evt(EVT_ARMED, mode=mode)


def _handle_rx_line(
    raw_line: str,
    args: argparse.Namespace,
    processor: TdcProcessor,
    file_logger: Optional[DualFileLogger],
    hist_mgr: Optional[RootHistogramManager],
    enable_parsed: bool,
    measurement_start_time: Optional[float],
    *,
    gui_mode: bool = False,
    gui_stream: Optional[GuiStreamEmitter] = None,
) -> Tuple[Optional[float], Optional[ProcessResult]]:
    """
    Process one serial line (shared by the live loop and shutdown drain).

    Returns (measurement_start_time, process_result_or_None).
    """
    def _emit_raw(line: str) -> None:
        if gui_stream is not None:
            gui_stream.raw(line)

    if args.stream_only:
        if gui_stream is not None:
            gui_stream.raw(raw_line)
        else:
            _user_print(raw_line, gui_mode=gui_mode)
        return measurement_start_time, None

    if args.raw_only:
        if gui_stream is None:
            _user_print(raw_line, gui_mode=gui_mode)
        _emit_raw(raw_line)
        if file_logger is not None:
            try:
                file_logger.log_raw(raw_line, is_measurement=True)
            except OSError as exc:
                _user_print(f"[WARN] raw log failed: {exc}", gui_mode=gui_mode)
        return measurement_start_time, None

    result = processor.process_line(raw_line)

    if not result.is_register_line:
        # Single stream to GUI (raw only) — log+raw previously doubled every line
        if gui_stream is not None:
            gui_stream.raw(raw_line)
        else:
            _user_print(raw_line, gui_mode=gui_mode)
        if file_logger is not None:
            try:
                file_logger.log_raw(raw_line, is_measurement=False)
            except OSError as exc:
                _user_print(f"[WARN] raw log failed: {exc}", gui_mode=gui_mode)
        return measurement_start_time, result

    if measurement_start_time is None:
        measurement_start_time = time.monotonic()

    _emit_raw(raw_line)
    if file_logger is not None:
        try:
            file_logger.log_raw(raw_line, is_measurement=True)
        except OSError as exc:
            _user_print(f"[WARN] raw log failed: {exc}", gui_mode=gui_mode)

    if result.computed_value is not None and gui_stream is not None:
        gui_stream.tof(result.computed_value, in_range=bool(result.is_valid_in_range))

    if (
        enable_parsed
        and result.is_valid_in_range
        and result.formatted_output is not None
        and result.computed_value is not None
    ):
        if file_logger is not None:
            try:
                file_logger.log_parsed(result.formatted_output)
            except OSError as exc:
                _user_print(f"[WARN] parsed log failed: {exc}", gui_mode=gui_mode)
        if hist_mgr is not None:
            hist_mgr.add_value(result.computed_value)

    return measurement_start_time, result


def _drain_rx_queue(
    rx_queue: queue.Queue,
    args: argparse.Namespace,
    processor: TdcProcessor,
    file_logger: Optional[DualFileLogger],
    hist_mgr: Optional[RootHistogramManager],
    enable_parsed: bool,
    measurement_start_time: Optional[float],
    max_lines: int = 10000,
    *,
    gui_mode: bool = False,
    gui_stream: Optional[GuiStreamEmitter] = None,
) -> Optional[float]:
    """Consume already-received serial lines so they are logged before exit."""
    # GUI needs a snappy STOP: tighter drain budget
    if gui_mode:
        max_lines = min(max_lines, 500)
    drained = 0
    deadline = time.monotonic() + (0.4 if gui_mode else 5.0)
    while drained < max_lines and time.monotonic() < deadline:
        try:
            raw_line = rx_queue.get_nowait()
        except queue.Empty:
            break
        measurement_start_time, _ = _handle_rx_line(
            raw_line,
            args,
            processor,
            file_logger,
            hist_mgr,
            enable_parsed,
            measurement_start_time,
            gui_mode=gui_mode,
            gui_stream=gui_stream,
        )
        drained += 1
    if drained:
        _user_print(
            f"[INFO] Flushed {drained} queued serial line(s) before exit.",
            gui_mode=gui_mode,
        )
    return measurement_start_time


def _safe_shutdown(
    *,
    stop_event: threading.Event,
    rx_queue: queue.Queue,
    serial_mgr: Optional[SerialManager],
    file_logger: Optional[DualFileLogger],
    hist_mgr: Optional[RootHistogramManager],
    args: argparse.Namespace,
    processor: TdcProcessor,
    enable_parsed: bool,
    measurement_start_time: Optional[float],
    reason: str,
    gui_mode: bool = False,
    gui_stream: Optional[GuiStreamEmitter] = None,
) -> Optional[object]:
    """
    Orderly teardown that prioritizes data durability:

      1. Signal workers to stop
      2. Drain RX queue into logs/histogram
      3. Close serial (join threads)
      4. Flush + fsync log files
      5. Save histogram image (best-effort; never blocks log durability)
    """
    if gui_stream is not None:
        gui_stream.evt(EVT_STOPPING, reason=reason)
    _user_print(f"\n\n[INFO] {reason}", gui_mode=gui_mode)
    _user_print("[INFO] Saving data safely (flush logs, close port)...", gui_mode=gui_mode)

    stop_event.set()

    try:
        _drain_rx_queue(
            rx_queue,
            args,
            processor,
            file_logger,
            hist_mgr,
            enable_parsed,
            measurement_start_time,
            gui_mode=gui_mode,
            gui_stream=gui_stream,
        )
    except Exception as exc:
        _user_print(f"[WARN] Queue drain issue: {exc}", gui_mode=gui_mode)

    if serial_mgr is not None:
        try:
            # Shorter join when driven by GUI so STOP feels responsive
            serial_mgr.close(join_timeout_sec=0.35 if gui_mode else 1.5)
        except Exception as exc:
            _user_print(f"[WARN] Serial close issue: {exc}", gui_mode=gui_mode)

    if file_logger is not None:
        try:
            file_logger.close()  # flush buffers + os.fsync both files
            _user_print("[INFO] Log files flushed and synced to disk.", gui_mode=gui_mode)
        except Exception as exc:
            _user_print(f"[WARN] Log flush issue: {exc}", gui_mode=gui_mode)

    saved_hist_path = None
    if hist_mgr is not None:
        try:
            saved_hist_path = hist_mgr.finalize_and_save()
        except Exception as exc:
            _user_print(
                f"[WARN] Histogram save issue (logs are safe): {exc}",
                gui_mode=gui_mode,
            )

    return saved_hist_path


def run_logger(args: argparse.Namespace) -> None:
    """Main execution loop coordinating serial RX/TX, processing, and disk logging."""
    gui_mode = bool(getattr(args, "gui", False))
    gui_stream: Optional[GuiStreamEmitter] = None
    if gui_mode:
        configure_stdio_for_gui()
        gui_stream = GuiStreamEmitter()
        # CLI must not open its own histogram window when driven by the GUI
        args.hist = False
        gui_stream.evt(EVT_STARTING, mode=int(args.mode))

    # 1. Resolve serial port: -p explicit, else auto Arduino, else menu (-i forces menu)
    try:
        port = SerialManager.resolve_port(
            args.port,
            interactive=bool(args.interactive_port) and not gui_mode,
        )
    except RuntimeError as err:
        if gui_stream is not None:
            gui_stream.err(str(err), code="port")
            gui_stream.evt(EVT_FINISHED, reason="port_error", ok=False)
        _user_print(f"[ERRORE] {err}", gui_mode=gui_mode)
        sys.exit(1)

    # 2. Initialize File Logger, TDC Processor, and Histogram Manager
    enable_parsed = (not args.raw_only) and (not args.stream_only)
    file_logger: Optional[DualFileLogger] = None
    if not args.stream_only:
        try:
            file_logger = DualFileLogger(
                base_name=args.out,
                use_timestamp=args.timestamp,
                enable_parsed=enable_parsed,
            )
        except OSError as exc:
            if gui_stream is not None:
                gui_stream.err(f"Cannot create log files: {exc}", code="fs")
                gui_stream.evt(EVT_FINISHED, reason="fs_error", ok=False)
            _user_print(f"[ERRORE] Cannot create log files: {exc}", gui_mode=gui_mode)
            sys.exit(1)

    processor = TdcProcessor(lim_sup=args.lim_sup, mode=int(args.mode))

    # CLI hist only when -g and not --gui
    hist_mgr: Optional[RootHistogramManager] = None
    if args.hist and enable_parsed and file_logger is not None and not gui_mode:
        try:
            hist_mgr = RootHistogramManager(
                output_folder=file_logger.folder_path,
                base_name=file_logger.folder_path.name,
                enable_gui=True,
            )
        except Exception as exc:
            _user_print(f"[WARN] Histogram init failed: {exc}", gui_mode=gui_mode)
            hist_mgr = None

    # 3. Initialize Serial Manager (no keyboard TX in --gui: stdin is STOP)
    rx_queue: queue.Queue = queue.Queue()
    stop_event = threading.Event()
    serial_mgr: Optional[SerialManager] = SerialManager(
        port=port,
        baudrate=args.baud,
        rx_queue=rx_queue,
        stop_event=stop_event,
        enable_keyboard_tx=not gui_mode,
    )

    # Ctrl+C / SIGTERM → set stop_event so the loop exits into durable shutdown.
    # (On Windows, the TX thread may also see Ctrl+C via msvcrt and set the same event.)
    def _signal_stop(signum, _frame) -> None:
        stop_event.set()

    previous_sigint = signal.getsignal(signal.SIGINT)
    previous_sigterm = None
    try:
        signal.signal(signal.SIGINT, _signal_stop)
    except (ValueError, OSError):
        previous_sigint = None
    if hasattr(signal, "SIGTERM"):
        try:
            previous_sigterm = signal.getsignal(signal.SIGTERM)
            signal.signal(signal.SIGTERM, _signal_stop)
        except (ValueError, OSError):
            previous_sigterm = None

    _user_print("\n--- Configurazione Sessione ---", gui_mode=gui_mode)
    _user_print(f"Porta:        {port} @ {args.baud} baud", gui_mode=gui_mode)
    _user_print(f"TDC mode:     {args.mode}", gui_mode=gui_mode)
    if gui_mode:
        _user_print("GUI link:     NDJSON stdout / STOP on stdin", gui_mode=gui_mode)
    if args.stream_only:
        _user_print("Modalita':    STREAM ONLY (Nessun file salvato su disco)", gui_mode=gui_mode)
    elif file_logger is not None:
        _user_print(f"File Raw:     {file_logger.raw_file_path}", gui_mode=gui_mode)
        if enable_parsed:
            lim_str = f"{args.lim_sup}" if args.lim_sup is not None else "Nessuno (+inf)"
            _user_print(
                f"File Parsed:  {file_logger.parsed_file_path} (lim_sup: {lim_str})",
                gui_mode=gui_mode,
            )
            if hist_mgr is not None:
                _user_print(
                    f"Istogramma:   Attivo (Export HD: {hist_mgr.image_path})",
                    gui_mode=gui_mode,
                )
    if args.auto_start:
        _user_print("Handshake:    AUTO (-a) mode digit + start byte", gui_mode=gui_mode)
    else:
        _user_print(
            "Handshake:    MANUAL (type 1/2 then any key on the console)",
            gui_mode=gui_mode,
        )
    if args.max_samples is not None:
        _user_print(
            f"Stop:         max-samples = {args.max_samples} (Stop IN)",
            gui_mode=gui_mode,
        )
    elif args.max_time is not None:
        _user_print(
            f"Stop:         max-time = {format_duration_seconds(args.max_time)}",
            gui_mode=gui_mode,
        )
    _user_print(
        "In ascolto sulla seriale (CTRL+C or GUI STOP)...\n",
        gui_mode=gui_mode,
    )

    stdin_watcher: Optional[StdinStopWatcher] = None
    if gui_mode:
        stdin_watcher = StdinStopWatcher(on_stop=lambda: stop_event.set())
        stdin_watcher.start()

    try:
        assert serial_mgr is not None
        serial_mgr.open()
    except Exception as e:
        _user_print(f"[ERRORE] Impossibile aprire la porta {port}: {e}", gui_mode=gui_mode)
        if gui_stream is not None:
            gui_stream.err(str(e), code="open")
            gui_stream.evt(EVT_FINISHED, reason="open_error", ok=False)
        if file_logger is not None:
            try:
                file_logger.close()
            except OSError as exc:
                _user_print(f"[WARN] log close: {exc}", gui_mode=gui_mode)
        if stdin_watcher is not None:
            stdin_watcher.stop()
        sys.exit(1)

    # Optional automatic firmware v2 handshake
    if args.auto_start:
        try:
            perform_firmware_handshake(
                serial_mgr=serial_mgr,
                rx_queue=rx_queue,
                stop_event=stop_event,
                mode=int(args.mode),
                file_logger=file_logger,
                gui_mode=gui_mode,
                gui_stream=gui_stream,
            )
        except (TimeoutError, RuntimeError, serial.SerialException) as exc:
            _user_print(f"[ERRORE] Handshake failed: {exc}", gui_mode=gui_mode)
            if gui_stream is not None:
                gui_stream.err(str(exc), code="handshake")
            stop_event.set()
            try:
                serial_mgr.close()
            except Exception as close_exc:
                _user_print(f"[WARN] serial close: {close_exc}", gui_mode=gui_mode)
            if file_logger is not None:
                try:
                    file_logger.close()
                except OSError as fl_exc:
                    _user_print(f"[WARN] log close: {fl_exc}", gui_mode=gui_mode)
            if gui_stream is not None:
                gui_stream.evt(EVT_FINISHED, reason="handshake_error", ok=False)
                gui_stream.close()
            if stdin_watcher is not None:
                stdin_watcher.stop()
            sys.exit(1)

    if gui_stream is not None:
        gui_stream.evt(EVT_RUNNING, mode=int(args.mode))

    measurement_start_time: Optional[float] = None
    max_duration_sec: Optional[float] = args.max_time
    last_ui_update: float = 0.0
    exit_reason = "Session finished."
    saved_hist_path = None
    shutdown_done = False

    def _do_shutdown(reason: str):
        nonlocal saved_hist_path, shutdown_done, measurement_start_time
        if shutdown_done:
            return
        shutdown_done = True
        if stdin_watcher is not None:
            stdin_watcher.stop()
        saved_hist_path = _safe_shutdown(
            stop_event=stop_event,
            rx_queue=rx_queue,
            serial_mgr=serial_mgr,
            file_logger=file_logger,
            hist_mgr=hist_mgr,
            args=args,
            processor=processor,
            enable_parsed=enable_parsed,
            measurement_start_time=measurement_start_time,
            reason=reason,
            gui_mode=gui_mode,
            gui_stream=gui_stream,
        )
        if gui_stream is not None:
            elapsed = 0.0
            if measurement_start_time is not None:
                elapsed = max(0.0, time.monotonic() - measurement_start_time)
            mean = hist_mgr.mean if hist_mgr is not None else None
            sigma = hist_mgr.sigma if hist_mgr is not None else None
            # Mean/sigma without CLI hist: optional later; emit counters always
            gui_stream.stat(
                stop_in=processor.stop_in_count,
                stop_out=processor.stop_out_count,
                corrupted=processor.corrupted_count,
                elapsed_s=elapsed,
                mean=mean,
                sigma=sigma,
                force=True,
            )
            gui_stream.evt(EVT_FINISHED, reason=reason, ok=True)
            gui_stream.close()

    try:
        while not stop_event.is_set():
            try:
                raw_line = rx_queue.get(timeout=0.05)
            except queue.Empty:
                if hist_mgr is not None:
                    hist_mgr.rebuild_and_render(force=False)
                if measurement_start_time and max_duration_sec:
                    if (time.monotonic() - measurement_start_time) >= max_duration_sec:
                        exit_reason = (
                            "Maximum acquisition time reached "
                            f"({format_duration_seconds(max_duration_sec)})."
                        )
                        break
                continue

            measurement_start_time, result = _handle_rx_line(
                raw_line,
                args,
                processor,
                file_logger,
                hist_mgr,
                enable_parsed,
                measurement_start_time,
                gui_mode=gui_mode,
                gui_stream=gui_stream,
            )

            if hist_mgr is not None and result is not None and result.is_register_line:
                hist_mgr.rebuild_and_render(force=False)

            now = time.monotonic()
            hit_sample_limit = (
                args.max_samples is not None
                and processor.stop_in_count >= args.max_samples
            )

            if gui_stream is not None and result is not None and result.is_register_line:
                elapsed = 0.0
                if measurement_start_time is not None:
                    elapsed = max(0.0, now - measurement_start_time)
                mean = hist_mgr.mean if hist_mgr is not None else None
                sigma = hist_mgr.sigma if hist_mgr is not None else None
                gui_stream.stat(
                    stop_in=processor.stop_in_count,
                    stop_out=processor.stop_out_count,
                    corrupted=processor.corrupted_count,
                    elapsed_s=elapsed,
                    mean=mean,
                    sigma=sigma,
                    force=hit_sample_limit,
                )

            if result is not None and result.is_register_line and not gui_mode:
                if (now - last_ui_update) >= 0.1 or hit_sample_limit:
                    target_str = (
                        f"/{args.max_samples}" if args.max_samples is not None else ""
                    )
                    val_str = (
                        f"{result.computed_value:.2f}"
                        if result.computed_value is not None
                        else "ERR"
                    )
                    stats_str = (
                        f"Media: {hist_mgr.mean:.2f} | Sigma: {hist_mgr.sigma:.2f} | "
                        if hist_mgr is not None
                        else ""
                    )
                    status_line = (
                        f"\r[LOGGING] Stop IN: {processor.stop_in_count}{target_str} | "
                        f"Stop OUT: {processor.stop_out_count} | "
                        f"{stats_str}"
                        f"Ultimo ToF: {val_str}    "
                    )
                    sys.stdout.write(status_line)
                    sys.stdout.flush()
                    last_ui_update = now

            if hit_sample_limit:
                exit_reason = (
                    f"Reached max-samples limit ({args.max_samples} Stop IN)."
                )
                break

            if measurement_start_time and max_duration_sec:
                if (now - measurement_start_time) >= max_duration_sec:
                    exit_reason = (
                        "Maximum acquisition time reached "
                        f"({format_duration_seconds(max_duration_sec)})."
                    )
                    break

        if stop_event.is_set() and exit_reason == "Session finished.":
            exit_reason = "Stop requested (Ctrl+C or signal)."

    except KeyboardInterrupt:
        exit_reason = "Manual interrupt (Ctrl+C)."
    finally:
        # Always durable-close even if open() partially failed later or hist crashes
        try:
            _do_shutdown(exit_reason)
        except Exception as exc:
            print(f"[WARN] Shutdown issue: {exc}")
            # Last-resort log flush if shutdown helper failed early
            if file_logger is not None:
                try:
                    file_logger.close()
                except Exception:
                    pass

        # Restore previous signal handlers
        try:
            if previous_sigint is not None:
                signal.signal(signal.SIGINT, previous_sigint)
            if previous_sigterm is not None and hasattr(signal, "SIGTERM"):
                signal.signal(signal.SIGTERM, previous_sigterm)
        except (ValueError, OSError):
            pass

        if not args.stream_only:
            total_valid_frames = processor.stop_in_count + processor.stop_out_count
            print("\n==========================================")
            print("         RIEPILOGO ACQUISIZIONE           ")
            print("==========================================")
            print(f"TDC measurement mode       : {processor.mode}")
            print(f"Misure IN range  (Stop IN) : {processor.stop_in_count}")
            print(f"Misure OUT range (Stop OUT): {processor.stop_out_count}")
            if processor.corrupted_count > 0:
                print(f"Frame corrotti (cal2<=cal1): {processor.corrupted_count}")
            if total_valid_frames > 0:
                ratio = (processor.stop_in_count / total_valid_frames) * 100.0
                print(f"Percentuale Stop IN        : {ratio:.2f}%")
            if hist_mgr is not None and processor.stop_in_count > 0:
                print("------------------------------------------")
                print(f"Statistiche ROOT (Entries  : {int(hist_mgr.fTsumw)})")
                print(f"Media (Mean)               : {hist_mgr.mean:.2f}")
                print(f"Sigma (Std Dev)            : {hist_mgr.sigma:.2f}")
            if file_logger is not None:
                print("------------------------------------------")
                print(f"Salvato Raw   : {file_logger.raw_file_path}")
                if enable_parsed:
                    print(f"Salvato Parsed: {file_logger.parsed_file_path}")
            if saved_hist_path:
                print(f"Salvato Hist  : {saved_hist_path}")
            print("==========================================\n")


if __name__ == "__main__":
    cli_parser = build_arg_parser()
    parsed_args = cli_parser.parse_args()
    if parsed_args.command == "ports":
        SerialManager.print_ports()
        sys.exit(0)
    if parsed_args.command == "start":
        run_logger(parsed_args)
