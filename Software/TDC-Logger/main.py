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
import sys
import threading
import time
from typing import Optional

from config import DEFAULT_BAUD_RATE
from serial_manager import SerialManager
from processors import TdcProcessor
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

5. USAGE EXAMPLES:
   - Full run with auto-start, histogram, and 10000 valid measurements:
     python main.py start -a -t -m 10000 -l 5000.0 -o TEST -g
   - Terminal stream monitor without saving files:
     python main.py start -a --stream-only
   - Raw capture only without TDC parsing:
     python main.py start -p COM3 -t -o RAW_CAPTURE --raw-only
==============================================================================
"""


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

    # Serial port selection (-p / --port)
    start_parser.add_argument(
        "-p", "--port", type=str, default=None, metavar="COMx",
        help="Serial port (e.g., COM3). If omitted: auto-select when unambiguous, else prompt",
    )
    start_parser.add_argument(
        "--no-auto-port", action="store_true",
        help="Disable automatic port selection; always prompt when -p is omitted",
    )
    start_parser.add_argument(
        "--no-interactive", action="store_true",
        help="Never prompt for a port (fail if -p missing and auto-select is ambiguous)",
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

    # Stop condition by maximum valid Stop IN count (-m / --max-measures)
    start_parser.add_argument(
        "-m", "--max-measures", type=int, default=None, metavar="N",
        help="Stop after N valid in-range measurements (Stop IN)",
    )

    # Stop condition by maximum elapsed time in minutes (-d / --duration)
    start_parser.add_argument(
        "-d", "--duration", type=float, default=None, metavar="MIN",
        help="Maximum logging duration in minutes",
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

def run_logger(args: argparse.Namespace) -> None:
    """Main execution loop coordinating serial RX/TX, processing, and disk logging."""
    # 1. Resolve serial port (explicit -p, smart auto-select, or interactive prompt)
    try:
        port = SerialManager.resolve_port(
            args.port,
            auto=not args.no_auto_port,
            interactive=not args.no_interactive,
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
    serial_mgr = SerialManager(
        port=port,
        baudrate=args.baud,
        rx_queue=rx_queue,
        stop_event=stop_event,
    )

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
    print("In ascolto sulla seriale (Premi CTRL+C per terminare in qualsiasi momento)...\n")

    try:
        serial_mgr.open()
    except Exception as e:
        print(f"[ERRORE] Impossibile aprire la porta {port}: {e}")
        if file_logger is not None:
            file_logger.close()
        sys.exit(1)

    measurement_start_time: Optional[float] = None
    max_duration_sec: Optional[float] = args.duration * 60.0 if args.duration else None
    last_ui_update: float = 0.0

    # Auto-start state tracking (waits 3s from start, then sends 'a' every 1s)
    auto_start_active: bool = bool(args.auto_start)
    auto_start_sent_once: bool = False
    next_auto_send_time: float = time.monotonic() + 3.0

    try:
        while not stop_event.is_set():
            # Handle automatic 'a' transmission if enabled
            if auto_start_active:
                now_auto = time.monotonic()
                if now_auto >= next_auto_send_time:
                    if serial_mgr.serial_conn and serial_mgr.serial_conn.is_open:
                        serial_mgr.serial_conn.write(b"a")
                        serial_mgr.serial_conn.flush()
                    print("a")
                    auto_start_sent_once = True
                    next_auto_send_time = now_auto + 1.0

            try:
                raw_line = rx_queue.get(timeout=0.05)
            except queue.Empty:
                if hist_mgr is not None:
                    hist_mgr.rebuild_and_render(force=False)
                # Check duration timeout even if serial stops sending data
                if measurement_start_time and max_duration_sec:
                    if (time.monotonic() - measurement_start_time) >= max_duration_sec:
                        print("\n\n[INFO] Tempo massimo di acquisizione raggiunto.")
                        break
                continue

            # Stop auto-start once new serial lines arrive after the first 'a' was sent
            if auto_start_active and auto_start_sent_once:
                auto_start_active = False

            # Mode 1: Stream-only (display on terminal, no disk I/O)
            if args.stream_only:
                print(raw_line)
                continue

            # Mode 2: Raw-only (display on terminal and save only to _raw.log)
            if args.raw_only:
                print(raw_line)
                if file_logger is not None:
                    file_logger.log_raw(raw_line, is_measurement=True)
                continue

            # Mode 3: Full TDC register processing
            result = processor.process_line(raw_line)

            if not result.is_register_line:
                # Prompt or header from Arduino (e.g., "Press any key to start")
                print(raw_line)
                if file_logger is not None:
                    file_logger.log_raw(raw_line, is_measurement=False)
                continue

            # Start duration timer upon receiving the first valid register frame
            if measurement_start_time is None:
                measurement_start_time = time.monotonic()

            # Save raw register string to <NAME>_raw.log
            if file_logger is not None:
                file_logger.log_raw(raw_line, is_measurement=True)

            # Save valid ToF to <NAME>.log and update ROOT histogram if -g is active
            if result.is_valid_in_range and result.formatted_output is not None and result.computed_value is not None:
                if file_logger is not None:
                    file_logger.log_parsed(result.formatted_output)
                if hist_mgr is not None:
                    hist_mgr.add_value(result.computed_value)

            # Update real-time histogram if -g is active
            if hist_mgr is not None:
                hist_mgr.rebuild_and_render(force=False)

            # Throttle terminal UI updates to ~10 Hz to prevent Windows console lag
            now = time.monotonic()
            if (now - last_ui_update) >= 0.1 or (
                args.max_measures and processor.stop_in_count >= args.max_measures
            ):
                target_str = f"/{args.max_measures}" if args.max_measures else ""
                val_str = f"{result.computed_value:.2f}" if result.computed_value is not None else "ERR"
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

            # Check Stop Condition 1: Max Valid Measurements (-m)
            if args.max_measures and processor.stop_in_count >= args.max_measures:
                print(f"\n\n[INFO] Raggiunto il limite di {args.max_measures} misure valide (Stop IN).")
                break

            # Check Stop Condition 2: Max Duration (-d)
            if measurement_start_time and max_duration_sec:
                if (now - measurement_start_time) >= max_duration_sec:
                    print("\n\n[INFO] Tempo massimo di acquisizione raggiunto.")
                    break

    except KeyboardInterrupt:
        print("\n\n[INFO] Interruzione manuale (CTRL+C) rilevata.")
    finally:
        serial_mgr.close()
        if file_logger is not None:
            file_logger.close()
        saved_hist_path = hist_mgr.finalize_and_save() if hist_mgr is not None else None

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
