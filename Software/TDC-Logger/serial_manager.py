#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: serial_manager.py
Version: 1.1.0
Date: 2026-11-06
Author: Gemini
Description: Serial port discovery, smart auto-selection, and full-duplex UART handler.
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

    def __init__(self, port: str, baudrate: int, rx_queue: queue.Queue, stop_event: threading.Event):
        self.port = port
        self.baudrate = baudrate
        self.rx_queue = rx_queue
        self.stop_event = stop_event
        self.serial_conn: Optional[serial.Serial] = None
        self.rx_thread: Optional[threading.Thread] = None
        self.tx_thread: Optional[threading.Thread] = None

    @staticmethod
    def rank_ports() -> List[Tuple[int, str, str]]:
        """
        Scan available COM ports and assign a priority score for Arduino detection.

        Priority 1: Official Arduino VID or 'Arduino' in description.
        Priority 2: Common USB-UART bridges (CH340, FTDI, CP210x, PL2303).
        Priority 3: Other standard serial ports.
        """
        ports = serial.tools.list_ports.comports()
        ranked_list: List[Tuple[int, str, str]] = []

        for p in ports:
            desc = p.description or "Unknown Device"
            hwid = p.hwid or ""
            vid = p.vid

            if vid in ARDUINO_OFFICIAL_VIDS or "arduino" in desc.lower():
                priority = 1
                tag = "[Arduino detected]"
            elif vid in COMMON_USB_UART_VIDS or "usb" in hwid.lower():
                priority = 2
                tag = "[USB-Serial candidate]"
            else:
                priority = 3
                tag = ""

            display_str = f"{p.device} - {desc} {tag}".strip()
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
            prio_label = {1: "P1", 2: "P2", 3: "P3"}.get(prio, "P?")
            print(f"  [{idx}] ({prio_label}) {display}{default_marker}")
        print()
        return ranked

    @classmethod
    def resolve_port(
        cls,
        port: Optional[str] = None,
        *,
        auto: bool = True,
        interactive: bool = True,
    ) -> str:
        """
        Resolve the serial port to open with a streamlined policy:

        1. If `port` is given, use it as-is (after basic normalisation).
        2. If `auto` is True:
           - exactly one port overall  -> use it
           - exactly one priority-1 Arduino -> use it
           - exactly one priority-1/2 candidate and nothing else preferred -> use best
        3. If still unresolved and `interactive` is True, prompt the user.
        4. Otherwise raise RuntimeError.
        """
        if port:
            return port.strip()

        ranked = cls.rank_ports()
        if not ranked:
            raise RuntimeError("No serial ports detected on this system.")

        if auto:
            auto_port = cls._try_auto_select(ranked)
            if auto_port is not None:
                print(f"[INFO] Auto-selected serial port: {auto_port}")
                return auto_port

        if interactive:
            return cls.select_port_interactively(ranked)

        raise RuntimeError(
            "Ambiguous serial port selection. Pass -p COMx or run without --no-interactive."
        )

    @staticmethod
    def _try_auto_select(ranked: List[Tuple[int, str, str]]) -> Optional[str]:
        """
        Return a port device string when the choice is unambiguous, else None.

        Rules (first match wins):
        - Single port on the machine.
        - Single official Arduino (priority 1).
        - Single USB-serial candidate (priority <= 2) when no other P1/P2 exists.
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
        print("\n--- Detected serial ports ---")
        for idx, (_, _dev, display) in enumerate(ranked, start=1):
            default_marker = "  <-- DEFAULT" if idx == 1 else ""
            print(f"  [{idx}] {display}{default_marker}")

        while True:
            user_input = input(
                f"\nSelect port [Enter = {default_port}, or type index/name]: "
            ).strip()

            if not user_input:
                return default_port

            if user_input.isdigit():
                choice_idx = int(user_input)
                if 1 <= choice_idx <= len(ranked):
                    return ranked[choice_idx - 1][1]

            for _, dev, _ in ranked:
                if user_input.upper() == dev.upper():
                    return dev

            print("Invalid selection. Try again.")

    def open(self) -> None:
        """Open the hardware UART port and start RX and TX worker threads."""
        self.serial_conn = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            timeout=SERIAL_TIMEOUT_SEC,
        )
        self.rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
        self.tx_thread = threading.Thread(target=self._tx_loop, daemon=True)
        self.rx_thread.start()
        self.tx_thread.start()

    def _rx_loop(self) -> None:
        """Continuously read lines from the serial port and push them to rx_queue."""
        while not self.stop_event.is_set():
            try:
                if self.serial_conn and self.serial_conn.in_waiting > 0:
                    raw_bytes = self.serial_conn.readline()
                    if raw_bytes:
                        line = raw_bytes.decode("utf-8", errors="replace").strip("\r\n")
                        if line:
                            self.rx_queue.put(line)
                else:
                    # Brief sleep when idle to prevent CPU pegging
                    self.stop_event.wait(0.005)
            except (serial.SerialException, OSError):
                self.stop_event.set()
                break

    def _tx_loop(self) -> None:
        """
        Capture user keystrokes to reply to prompts like 'press any key to start'.
        Uses msvcrt on Windows for instant single-key transmission without Enter.
        """
        while not self.stop_event.is_set():
            try:
                if sys.platform == "win32":
                    if msvcrt.kbhit():
                        ch = msvcrt.getch()
                        # Ignore Ctrl+C (0x03) so KeyboardInterrupt is handled by main
                        if ch == b"\x03":
                            self.stop_event.set()
                            break
                        if self.serial_conn and self.serial_conn.is_open:
                            self.serial_conn.write(ch)
                            self.serial_conn.flush()
                    else:
                        self.stop_event.wait(0.02)
                else:
                    # Fallback for non-Windows environments
                    line = sys.stdin.readline()
                    if line and self.serial_conn and self.serial_conn.is_open:
                        self.serial_conn.write(line.encode("utf-8"))
                        self.serial_conn.flush()
            except Exception:
                break

    def close(self) -> None:
        """Safely close the serial port."""
        self.stop_event.set()
        if self.serial_conn and self.serial_conn.is_open:
            try:
                self.serial_conn.close()
            except Exception:
                pass
