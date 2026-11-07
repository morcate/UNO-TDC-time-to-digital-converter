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


DETAILED_HELP_EN = """
==============================================================================
                DETAILED OPERATION & ARCHITECTURE MANUAL
==============================================================================
1. BIDIRECTIONAL UART & AUTO-START (ARDUINO):
   - Non-numerical text strings (e.g., 'Press any key to start') are printed
     to the terminal and logged exclusively to <NAME>_raw.log without
     affecting measurement counters.
   - Any key pressed on the keyboard is immediately transmitted over TX.
   - With '-a' (--auto-start), the application waits 3 seconds after startup
     and transmits 'a' every 1 second until serial data is received.

2. 24-BIT TDC REGISTER PARSING & ToF CALCULATION:
   - Each valid register frame must contain 9 space-separated (ASCII 32)
     integers: [t2 t1 t0 c1_2 c1_1 c1_0 c2_2 c2_1 c2_0].
   - 24-bit reconstruction: REG = (MSB * 65536) + (MID * 256) + LSB.
   - Time-of-Flight formula: tof = (time * 562.5) / (cal2 - cal1).
   - Range filtering:
       * If 0 <= tof < lim_sup : increments Stop IN and writes the value
                                 (formatted to 3 decimal places) to <NAME>.log.
       * If tof >= lim_sup     : increments Stop OUT and discards the value
                                 from <NAME>.log (still saved in <NAME>_raw.log).

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
   - Full run with auto-start, histogram, and 10000 valid samples:
     python main.py start -a -t -m 10000 -l 5000.0 -o TEST -g
   - Time-limited run (10 days, 3 hours, 45 minutes):
     python main.py start -a -T "10d 3h 45m" -o LONG_RUN -g
   - Terminal stream monitor without saving files:
     python main.py start -a --stream-only
   - Raw capture only without TDC parsing:
     python main.py start -p COM3 -t -o RAW_CAPTURE --raw-only
==============================================================================
"""


# Matches one duration token: integer + unit d/h/m (case-insensitive), optional spaces.
_MAX_TIME_TOKEN_RE = re.compile(r"(\d+)\s*([dhm])", re.IGNORECASE)


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

    # Automatic trigger character transmission (-a / --auto-start)
    start_parser.add_argument(
        "-a", "--auto-start", action="store_true",
        help="Wait 3s, then send 'a' every 1s until serial data is received",
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

def _handle_rx_line(
    raw_line: str,
    args: argparse.Namespace,
    processor: TdcProcessor,
    file_logger: Optional[DualFileLogger],
    hist_mgr: Optional[RootHistogramManager],
    enable_parsed: bool,
    measurement_start_time: Optional[float],
) -> Tuple[Optional[float], Optional[ProcessResult]]:
    """
    Process one serial line (shared by the live loop and shutdown drain).

    Returns (measurement_start_time, process_result_or_None).
    """
    if args.stream_only:
        print(raw_line)
        return measurement_start_time, None

    if args.raw_only:
        print(raw_line)
        if file_logger is not None:
            file_logger.log_raw(raw_line, is_measurement=True)
        return measurement_start_time, None

    result = processor.process_line(raw_line)

    if not result.is_register_line:
        print(raw_line)
        if file_logger is not None:
            file_logger.log_raw(raw_line, is_measurement=False)
        return measurement_start_time, result

    if measurement_start_time is None:
        measurement_start_time = time.monotonic()

    if file_logger is not None:
        file_logger.log_raw(raw_line, is_measurement=True)

    if (
        enable_parsed
        and result.is_valid_in_range
        and result.formatted_output is not None
        and result.computed_value is not None
    ):
        if file_logger is not None:
            file_logger.log_parsed(result.formatted_output)
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
) -> Optional[float]:
    """Consume already-received serial lines so they are logged before exit."""
    drained = 0
    while drained < max_lines:
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
        )
        drained += 1
    if drained:
        print(f"[INFO] Flushed {drained} queued serial line(s) before exit.")
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
) -> Optional[object]:
    """
    Orderly teardown that prioritizes data durability:

      1. Signal workers to stop
      2. Drain RX queue into logs/histogram
      3. Close serial (join threads)
      4. Flush + fsync log files
      5. Save histogram image (best-effort; never blocks log durability)
    """
    print(f"\n\n[INFO] {reason}")
    print("[INFO] Saving data safely (flush logs, close port)...")

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
        )
    except Exception as exc:
        print(f"[WARN] Queue drain issue: {exc}")

    if serial_mgr is not None:
        try:
            serial_mgr.close()
        except Exception as exc:
            print(f"[WARN] Serial close issue: {exc}")

    if file_logger is not None:
        try:
            file_logger.close()  # flush buffers + os.fsync both files
            print("[INFO] Log files flushed and synced to disk.")
        except Exception as exc:
            print(f"[WARN] Log flush issue: {exc}")

    saved_hist_path = None
    if hist_mgr is not None:
        try:
            saved_hist_path = hist_mgr.finalize_and_save()
        except Exception as exc:
            print(f"[WARN] Histogram save issue (logs are safe): {exc}")

    return saved_hist_path


def run_logger(args: argparse.Namespace) -> None:
    """Main execution loop coordinating serial RX/TX, processing, and disk logging."""
    # 1. Resolve serial port: -p explicit, else auto Arduino, else menu (-i forces menu)
    try:
        port = SerialManager.resolve_port(
            args.port,
            interactive=bool(args.interactive_port),
        )
    except RuntimeError as err:
        print(f"[ERRORE] {err}")
        sys.exit(1)

    # 2. Initialize File Logger, TDC Processor, and Histogram Manager
    enable_parsed = (not args.raw_only) and (not args.stream_only)
    file_logger: Optional[DualFileLogger] = None
    if not args.stream_only:
        file_logger = DualFileLogger(
            base_name=args.out,
            use_timestamp=args.timestamp,
            enable_parsed=enable_parsed,
        )

    processor = TdcProcessor(lim_sup=args.lim_sup)

    # Instantiate histogram manager strictly when -g / --hist is requested
    hist_mgr: Optional[RootHistogramManager] = None
    if args.hist and enable_parsed and file_logger is not None:
        hist_mgr = RootHistogramManager(
            output_folder=file_logger.folder_path,
            base_name=file_logger.folder_path.name,
            enable_gui=True,
        )

    # 3. Initialize Serial Manager
    rx_queue: queue.Queue = queue.Queue()
    stop_event = threading.Event()
    serial_mgr: Optional[SerialManager] = SerialManager(
        port=port,
        baudrate=args.baud,
        rx_queue=rx_queue,
        stop_event=stop_event,
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

    print("\n--- Configurazione Sessione ---")
    print(f"Porta:        {port} @ {args.baud} baud")
    if args.stream_only:
        print("Modalita':    STREAM ONLY (Nessun file salvato su disco)")
    elif file_logger is not None:
        print(f"File Raw:     {file_logger.raw_file_path}")
        if enable_parsed:
            lim_str = f"{args.lim_sup}" if args.lim_sup is not None else "Nessuno (+inf)"
            print(f"File Parsed:  {file_logger.parsed_file_path} (lim_sup: {lim_str})")
            if hist_mgr is not None:
                print(f"Istogramma:   Attivo (Export HD: {hist_mgr.image_path})")
    if args.auto_start:
        print("Auto-Start:   Attivo (Invio 'a' dopo 3s, poi ogni 1s)")
    if args.max_samples is not None:
        print(f"Stop:         max-samples = {args.max_samples} (Stop IN)")
    elif args.max_time is not None:
        print(f"Stop:         max-time = {format_duration_seconds(args.max_time)}")
    print("In ascolto sulla seriale (Premi CTRL+C per terminare in qualsiasi momento)...\n")

    try:
        assert serial_mgr is not None
        serial_mgr.open()
    except Exception as e:
        print(f"[ERRORE] Impossibile aprire la porta {port}: {e}")
        if file_logger is not None:
            file_logger.close()
        sys.exit(1)

    measurement_start_time: Optional[float] = None
    max_duration_sec: Optional[float] = args.max_time
    last_ui_update: float = 0.0
    exit_reason = "Session finished."
    saved_hist_path = None
    shutdown_done = False

    # Auto-start state tracking (waits 3s from start, then sends 'a' every 1s)
    auto_start_active: bool = bool(args.auto_start)
    auto_start_sent_once: bool = False
    next_auto_send_time: float = time.monotonic() + 3.0

    def _do_shutdown(reason: str):
        nonlocal saved_hist_path, shutdown_done, measurement_start_time
        if shutdown_done:
            return
        shutdown_done = True
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
        )

    try:
        while not stop_event.is_set():
            # Handle automatic 'a' transmission if enabled
            if auto_start_active:
                now_auto = time.monotonic()
                if now_auto >= next_auto_send_time:
                    if serial_mgr.serial_conn and serial_mgr.serial_conn.is_open:
                        try:
                            serial_mgr.serial_conn.write(b"a")
                            serial_mgr.serial_conn.flush()
                        except (serial.SerialException, OSError, AttributeError):
                            stop_event.set()
                            exit_reason = "Serial port error during auto-start."
                            break
                    print("a")
                    auto_start_sent_once = True
                    next_auto_send_time = now_auto + 1.0

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

            if auto_start_active and auto_start_sent_once:
                auto_start_active = False

            measurement_start_time, result = _handle_rx_line(
                raw_line,
                args,
                processor,
                file_logger,
                hist_mgr,
                enable_parsed,
                measurement_start_time,
            )

            if hist_mgr is not None and result is not None and result.is_register_line:
                hist_mgr.rebuild_and_render(force=False)

            # Status line only for register frames in full/parsed modes
            now = time.monotonic()
            hit_sample_limit = (
                args.max_samples is not None
                and processor.stop_in_count >= args.max_samples
            )
            if result is not None and result.is_register_line:
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
