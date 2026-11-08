#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: serial_manager.py
Version: 1.2.0
Date: 2026-11-07
Author: Gemini
Description: Serial port discovery, simple auto-selection, and full-duplex UART handler.
Requirements: pyserial>=3.5
Installation: pip install pyserial

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

import sys
import threading
import queue
from typing import Optional, List, Tuple
import serial
import serial.tools.list_ports

from config import (
    SERIAL_TIMEOUT_SEC,
    ARDUINO_OFFICIAL_VIDS,
    COMMON_USB_UART_VIDS,
)

# Windows-specific non-blocking keyboard input support
if sys.platform == "win32":
    import msvcrt


class SerialManager:
    """Manages port scanning, connection life-cycle, and RX/TX threads."""

    def __init__(
        self,
        port: str,
        baudrate: int,
        rx_queue: queue.Queue,
        stop_event: threading.Event,
        *,
        enable_keyboard_tx: bool = True,
    ):
        self.port = port
        self.baudrate = baudrate
        self.rx_queue = rx_queue
        self.stop_event = stop_event
        self.enable_keyboard_tx = bool(enable_keyboard_tx)
        self.serial_conn: Optional[serial.Serial] = None
        self.rx_thread: Optional[threading.Thread] = None
        self.tx_thread: Optional[threading.Thread] = None

    @staticmethod
    def normalize_port_name(port: str) -> str:
        """
        Normalize user port input.

        On Windows, bare digits become COMn (e.g. '3' -> 'COM3').
        Elsewhere the string is stripped only.
        """
        cleaned = port.strip()
        if not cleaned:
            return cleaned
        if sys.platform == "win32" and cleaned.isdigit():
            return f"COM{cleaned}"
        # Allow com3 / Com3
        if sys.platform == "win32" and cleaned.upper().startswith("COM"):
            return "COM" + cleaned[3:] if cleaned[3:].isdigit() else cleaned.upper()
        return cleaned

    @staticmethod
    def rank_ports() -> List[Tuple[int, str, str]]:
        """
        Scan available COM ports and assign a priority score for Arduino detection.

        Priority 1: Official Arduino VID, or Arduino/Uno/Nano/Mega in
                    description/manufacturer/product.
        Priority 2: Common USB-UART bridges (CH340, FTDI, CP210x, PL2303).
        Priority 3: Other standard serial ports.

        Always re-queries the OS (no cache) so hot-plug is visible.
        """
        try:
            ports = list(serial.tools.list_ports.comports())
        except Exception as exc:
            # Never fail silently — empty list; caller can surface the error
            print(f"[serial_manager] list_ports failed: {exc}", file=sys.stderr)
            return []

        ranked_list: List[Tuple[int, str, str]] = []
        # Whole-word / phrase tokens only — avoid "micro" matching "Microsoft"
        import re

        arduino_re = re.compile(
            r"(?i)(?<!\w)(arduino|genuino|arduino\s*uno|arduino\s*nano|"
            r"arduino\s*mega|arduino\s*leonardo|arduino\s*micro|"
            r"\buno\b|\bnano\b|\bmega\b|\bleonardo\b)(?!\w)"
        )

        for p in ports:
            desc = (p.description or "Unknown Device").strip()
            hwid = (p.hwid or "").strip()
            manufacturer = (getattr(p, "manufacturer", None) or "").strip()
            product = (getattr(p, "product", None) or "").strip()
            serial_no = (getattr(p, "serial_number", None) or "").strip()
            vid = p.vid
            blob = f"{desc} {manufacturer} {product} {hwid}"

            is_arduino = (vid is not None and vid in ARDUINO_OFFICIAL_VIDS) or bool(
                arduino_re.search(blob)
            )
            is_usb_uart = (
                (vid is not None and vid in COMMON_USB_UART_VIDS)
                or "usb" in hwid.lower()
                or "ch340" in blob
                or "ch341" in blob
                or "cp210" in blob
                or "ft232" in blob
                or "pl2303" in blob
            )

            if is_arduino:
                priority = 1
                tag = "[Arduino]"
            elif is_usb_uart:
                # Many Uno clones use CH340 — still preferred over random COM
                priority = 2
                tag = "[USB-Serial]"
            else:
                priority = 3
                tag = ""

            extra = []
            if manufacturer and manufacturer.lower() not in desc.lower():
                extra.append(manufacturer)
            if serial_no:
                extra.append(f"SN:{serial_no}")
            extra_s = f" ({', '.join(extra)})" if extra else ""
            display_str = f"{p.device} - {desc}{extra_s} {tag}".strip()
            ranked_list.append((priority, p.device, display_str))

        ranked_list.sort(key=lambda x: (x[0], x[1]))
        return ranked_list

    @classmethod
    def print_ports(cls) -> List[Tuple[int, str, str]]:
        """Print ranked ports to stdout and return the ranked list."""
        ranked = cls.rank_ports()
        if not ranked:
            print("No serial ports detected on this system.")
            return ranked

        print("\n--- Detected serial ports ---")
        for idx, (prio, _dev, display) in enumerate(ranked, start=1):
            default_marker = "  <-- preferred" if idx == 1 else ""
            prio_label = {1: "Arduino", 2: "USB-Serial", 3: "Other"}.get(prio, "?")
            print(f"  [{idx}] {display}  ({prio_label}){default_marker}")
        print()
        return ranked

    @classmethod
    def resolve_port(
        cls,
        port: Optional[str] = None,
        *,
        interactive: bool = False,
    ) -> str:
        """
        Resolve which serial port to open (simple policy):

        1. If `-p` / port is given → use it (normalized).
        2. Else if exactly one sensible choice exists → auto-select
           (single port, or single Arduino, or single USB-serial candidate).
        3. Else if `interactive` or a TTY is available → prompt (Enter = preferred).
        4. Else raise with a hint to pass `-p` or run `ports`.
        """
        if port:
            return cls.normalize_port_name(port)

        ranked = cls.rank_ports()
        if not ranked:
            raise RuntimeError(
                "No serial ports detected. Plug in the Arduino and run: python main.py ports"
            )

        if not interactive:
            auto_port = cls._try_auto_select(ranked)
            if auto_port is not None:
                # Show a one-line confirmation so the user knows what was chosen
                label = next((d for _p, dev, d in ranked if dev == auto_port), auto_port)
                print(f"[INFO] Using serial port: {label}")
                return auto_port

        # Ambiguous (or forced interactive): menu if possible
        if sys.stdin is not None and sys.stdin.isatty():
            return cls.select_port_interactively(ranked)

        devices = ", ".join(dev for _p, dev, _d in ranked)
        raise RuntimeError(
            "Ambiguous serial ports and no interactive terminal. "
            f"Available: {devices}. Pass -p COMx or run: python main.py ports"
        )

    @staticmethod
    def _try_auto_select(ranked: List[Tuple[int, str, str]]) -> Optional[str]:
        """
        Return a port when the choice is unambiguous, else None.

        - Only one port on the machine.
        - Exactly one official Arduino (priority 1), even if other ports exist.
        - Exactly one USB-serial / Arduino candidate (priority <= 2).
        """
        if len(ranked) == 1:
            return ranked[0][1]

        arduino = [r for r in ranked if r[0] == 1]
        if len(arduino) == 1:
            return arduino[0][1]

        candidates = [r for r in ranked if r[0] <= 2]
        if len(candidates) == 1:
            return candidates[0][1]

        return None

    @classmethod
    def select_port_interactively(
        cls, ranked: Optional[List[Tuple[int, str, str]]] = None
    ) -> str:
        """Display available ports and prompt for selection (Enter = preferred)."""
        if ranked is None:
            ranked = cls.rank_ports()
        if not ranked:
            raise RuntimeError("No serial ports detected on this system.")

        default_port = ranked[0][1]
        print("\n--- Select serial port ---")
        for idx, (_, _dev, display) in enumerate(ranked, start=1):
            default_marker = "  <-- Enter" if idx == 1 else ""
            print(f"  [{idx}] {display}{default_marker}")

        while True:
            try:
                user_input = input(
                    f"\nPort [Enter={default_port}, #, or name]: "
                ).strip()
            except EOFError:
                return default_port

            if not user_input:
                return default_port

            if user_input.isdigit():
                choice_idx = int(user_input)
                if 1 <= choice_idx <= len(ranked):
                    return ranked[choice_idx - 1][1]
                # Bare COM number on Windows (e.g. type 5 for COM5) if listed
                normalized = cls.normalize_port_name(user_input)
                for _, dev, _ in ranked:
                    if normalized.upper() == dev.upper():
                        return dev

            normalized = cls.normalize_port_name(user_input)
            for _, dev, _ in ranked:
                if normalized.upper() == dev.upper() or user_input.upper() == dev.upper():
                    return dev

            print("Invalid selection. Try again (number or COMx).")

    def open(self) -> None:
        """Open the hardware UART port and start RX and TX worker threads."""
        self.serial_conn = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            timeout=SERIAL_TIMEOUT_SEC,
        )
        # Non-daemon so we can join them on clean shutdown and finish pending I/O.
        self.rx_thread = threading.Thread(target=self._rx_loop, name="tdc-rx", daemon=True)
        self.rx_thread.start()
        if self.enable_keyboard_tx:
            self.tx_thread = threading.Thread(target=self._tx_loop, name="tdc-tx", daemon=True)
            self.tx_thread.start()
        else:
            self.tx_thread = None

    def write_bytes(self, data: bytes) -> None:
        """Write raw bytes to the UART (used by firmware handshake)."""
        if not data:
            return
        if self.serial_conn is None or not self.serial_conn.is_open:
            raise serial.SerialException("Serial port is not open")
        self.serial_conn.write(data)
        self.serial_conn.flush()

    def _rx_loop(self) -> None:
        """Continuously read lines from the serial port and push them to rx_queue."""
        while not self.stop_event.is_set():
            try:
                if self.serial_conn and self.serial_conn.is_open and self.serial_conn.in_waiting > 0:
                    raw_bytes = self.serial_conn.readline()
                    if raw_bytes:
                        line = raw_bytes.decode("utf-8", errors="replace").strip("\r\n")
                        if line:
                            self.rx_queue.put(line)
                else:
                    # Brief sleep when idle to prevent CPU pegging
                    self.stop_event.wait(0.005)
            except (serial.SerialException, OSError, ValueError):
                self.stop_event.set()
                break
            except Exception:
                self.stop_event.set()
                break

    def _tx_loop(self) -> None:
        """
        Capture user keystrokes to reply to prompts like 'press any key to start'.
        Uses msvcrt on Windows for instant single-key transmission without Enter.
        Ctrl+C (0x03) requests a clean stop via stop_event (does not kill mid-write).
        """
        while not self.stop_event.is_set():
            try:
                if sys.platform == "win32":
                    if msvcrt.kbhit():
                        ch = msvcrt.getch()
                        # Ctrl+C → request orderly shutdown; main drains queue + flushes logs
                        if ch in (b"\x03", b"\x00\x03"):
                            self.stop_event.set()
                            break
                        if ch == b"\x00" or ch == b"\xe0":
                            # Swallow special-key prefix/second byte
                            if msvcrt.kbhit():
                                msvcrt.getch()
                            continue
                        if self.serial_conn and self.serial_conn.is_open:
                            self.serial_conn.write(ch)
                            self.serial_conn.flush()
                    else:
                        self.stop_event.wait(0.02)
                else:
                    line = sys.stdin.readline()
                    if line and self.serial_conn and self.serial_conn.is_open:
                        self.serial_conn.write(line.encode("utf-8"))
                        self.serial_conn.flush()
            except Exception:
                break

    def close(self, join_timeout_sec: float = 1.5) -> None:
        """
        Stop worker threads, close the serial port, and join threads.

        Order: signal stop → close port (unblocks I/O) → join threads.
        """
        self.stop_event.set()

        conn = self.serial_conn
        self.serial_conn = None
        if conn is not None:
            try:
                if conn.is_open:
                    conn.close()
            except Exception:
                pass

        for thread in (self.rx_thread, self.tx_thread):
            if thread is not None and thread.is_alive():
                thread.join(timeout=join_timeout_sec)
