# TDC-Logger

Python **CLI** and **desktop GUI** for serial acquisition, parsing, logging, and live histogramming of Time-of-Flight (ToF) data from a custom Arduino UNO shield that implements a **Time-to-Digital Converter (TDC)**.

Parent repository:

`https://github.com/morcate/UNO-TDC-time-to-digital-converter`

---

## Purpose

TDC-Logger is the PC-side companion to the UNO-TDC hardware:

1. Open a full-duplex UART link to the Arduino (default **38400 baud**).
2. Stream the serial monitor (terminal and/or GUI).
3. Parse TDC register frames (mode 1 or 2) into physical ToF values in nanoseconds.
4. Filter measurements with an optional upper limit (`lim_sup`).
5. Log raw traffic and valid ToF values into separate files under a chosen folder.
6. Show a **live ROOT-style histogram** (CLI with `-g`, or embedded in the GUI).
7. Drive firmware mode selection and start via automatic handshake (`-a`).

---

## Folder map (architecture)

```text
TDC-Logger/
├── main.py                 # CLI entry + session loop (--gui NDJSON mode)
├── config.py               # Constants (baud, TDC factors, VIDs, I/O)
├── serial_manager.py       # Port discovery, auto-select, RX/TX threads
├── processors.py           # TDC frame parse + ToF + counters
├── file_logger.py          # Dual-file logger (raw + parsed) with fsync
├── histogram_manager.py    # ROOT-style hist (rebin + refill + axes)
├── hist_config.py          # Histogram style / rebinning / export
├── gui_protocol.py         # NDJSON protocol CLI ↔ GUI
├── stdin_stop.py           # Cooperative STOP watcher for --gui
├── requirements.txt
├── README.md               # This file
├── TDC-Logger.md           # Extra architecture notes
└── gui/                    # Desktop shell (PySide6)
    ├── __main__.py         # python -m gui
    ├── main_window.py      # Layout + wiring
    ├── command_builder.py  # Form → CLI argv (always -a --gui)
    ├── process_worker.py   # QProcess + NDJSON + STOP/KILL
    ├── hist_panel.py       # Embedded MPL hist (≤ 3 Hz)
    ├── serial_panel.py     # Serial monitor (Hack monospace)
    ├── styles.py / widgets.py
    ├── fonts/Hack-Regular.ttf
    ├── _icons/             # Radio/checkbox SVG assets
    └── gui.md
```

### Treemap (logical layers)

```text
TDC-Logger
├── CLI / orchestration .............. main.py
│   ├── argparse (start | ports)
│   ├── --gui NDJSON on stdout, human log on stderr
│   ├── STOP via stdin (gui) or Ctrl+C
│   └── handshake (-a) mode digit + start byte
├── I/O boundary ..................... serial_manager.py + config.py
│   ├── port rank / hot-plug friendly list
│   ├── RX thread → queue.Queue
│   └── TX thread (keyboard; disabled under --gui)
├── Domain logic ..................... processors.py
│   ├── Mode 1: tof = time * 562.5 / (cal2 - cal1)
│   ├── Mode 2: 62.5*cc + 562.5*(t1-t2)/caldiff
│   └── Stop IN / OUT / corrupted counters
├── Persistence ...................... file_logger.py
│   ├── parent folder of -o is honored (absolute or relative)
│   ├── <dir>/<NAME>/<NAME>_raw.log
│   └── <dir>/<NAME>/<NAME>.log
├── Visualization (CLI) .............. histogram_manager.py + hist_config.py
└── Desktop GUI ...................... gui/ (subprocess wrapper)
    ├── always launches: python -u main.py start -a --gui ...
    ├── live hist + serial tabs
    └── STOP → terminate → kill escalation
```

---

## Requirements

- Python **3.8+** (developed/tested with 3.13 on Windows)
- Dependencies (`requirements.txt`):

```text
pyserial>=3.5
numpy>=1.24.0
matplotlib>=3.7.0
PySide6>=6.5.0
```

Install:

```bash
cd Software/TDC-Logger
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
# source .venv/bin/activate
pip install -r requirements.txt
```

---

## Quick start

### Desktop GUI (recommended for interactive use)

```bash
cd Software/TDC-Logger
python -m gui
```

- Select serial port (rescans automatically; Arduino preferred).
- Choose mode, stop condition, options, output name.
- **Browse…** sets the save **folder** (remembered across runs and renames).
- **START** runs the CLI with `-a --gui`; **STOP** / second click **KILL**.
- Corner tab toggles histogram ↔ serial monitor.

### CLI

List ports:

```bash
python main.py ports
```

Typical acquisition (auto handshake, mode 1, histogram):

```bash
python main.py start -a --mode 1 -t -m 10000 -l 5000.0 -o TEST -g
```

Mode 2:

```bash
python main.py start -a --mode 2 -o RUN_M2 -g
```

GUI-linked session (machine protocol; used by the desktop app):

```bash
python -u main.py start -a --gui -p COM5 --mode 1 -m 10000 -o C:\data\session
# Stop: write a line "STOP" to stdin
```

Detailed English manual:

```bash
python main.py start -hh
```

---

## CLI reference

### Commands

| Command | Description |
|---------|-------------|
| `start` | Run a logging / streaming session |
| `ports` | Print detected serial ports with priority tags |

### `start` options

| Flag | Long | Description |
|------|------|-------------|
| `-p` | `--port COMx` | Serial port (`COM3` or bare `3` on Windows). Omit = auto / menu |
| `-i` | `--interactive-port` | Always show the port menu (skip auto-select) |
| `-b` | `--baud BPS` | Baud rate (default **38400**) |
| | `--mode {1,2}` | TDC measurement mode (default **1**); fixed for the session |
| `-a` | `--auto-start` | Auto firmware handshake: mode menu → digit → start byte |
| | `--gui` | NDJSON on stdout; human logs on stderr; no CLI hist; STOP on stdin |
| `-t` | `--timestamp` | Timestamp measurement lines in `*_raw.log` |
| `-m` | `--max-samples N` | Stop after **N** valid in-range (Stop IN) samples |
| `-T` | `--max-time DURATION` | Wall time, e.g. `"10d 3h 45m"` or `45m` (max **31 days**) |
| `-l` | `--lim-sup MAX` | Upper ToF threshold (Stop OUT if `tof >= lim_sup`) |
| `-o` | `--out NAME` | Base path/name for output folder (may include parent directory) |
| `-g` | `--hist` | Live ROOT-style histogram + HD PNG (ignored under `--gui`) |
| | `--raw-only` | Only `*_raw.log`; skip ToF parsing |
| | `--stream-only` | Terminal only; no disk files |
| `-h` / `-hh` | | Short help / full English manual |

### Stop conditions (mutually exclusive)

At most one of `-m` / `-T`, or neither (run until Ctrl+C / GUI STOP).

### Serial port selection

| You want… | Command |
|-----------|---------|
| List ports | `python main.py ports` |
| Auto / menu | `python main.py start …` (no `-p`) |
| Explicit | `python main.py start -p COM5 …` |

Priority: official Arduino VID / name → USB-UART bridges (CH340, FTDI, …) → other COM ports.

### Output layout

Given `-o C:\Logs\runA` (or GUI Browse + name `runA`):

```text
C:\Logs\runA\                 # or runA_1 if runA already exists
├── runA_raw.log
└── runA.log                  # valid ToF lines (unless --raw-only)
```

Bare `-o NAME` creates `./NAME/` under the process working directory.

---

## GUI ↔ CLI protocol (`--gui`)

| Direction | Content |
|-----------|---------|
| CLI → GUI (stdout) | One NDJSON object per line (`t`: `log`, `raw`, `tof`, `stat`, `evt`, `err`) |
| CLI → GUI (stderr) | Human-readable diagnostics |
| GUI → CLI (stdin) | Line `STOP` (cooperative); GUI may escalate to terminate/kill |

Run the CLI with `python -u` so pipes stay line-buffered.

Details: `gui_protocol.py`, `gui/gui.md`.

---

## ToF formulas

**Mode 1** (9 integers):

```text
tof_ns = time * 562.5 / (cal2 - cal1)
```

**Mode 2** (15 integers):

```text
tof_ns = 62.5 * clock_count + 562.5 * (time1 - time2) / (cal2 - cal1)
```

Constants live in `config.py`.

---

## Packaging for distribution

Goal: ship a **Windows desktop app** (and optionally a pip-installable CLI) so users do not need a manual Python setup.

### A. What to ship

| Artifact | Audience |
|----------|----------|
| GUI `.exe` (one-folder or one-file) | Lab PCs, non-developers |
| Optional `tdc-logger` CLI on `PATH` | Scripting / automation |
| Wheel on PyPI or GitHub Releases | Developers |
| Short user note (baud, flash firmware, COM drivers) | Everyone |

### B. Recommended packaging stack

1. **PyInstaller** (primary for Windows GUI)  
2. Optional later: **Briefcase** / **cx_Freeze** / **Inno Setup** or **WiX** for an installer with Start Menu shortcut  
3. **GitHub Actions** to build on tag and attach artifacts to **GitHub Releases**

### C. Step-by-step (Windows GUI with PyInstaller)

#### 1. Freeze dependencies

```bash
cd Software/TDC-Logger
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install pyinstaller
```

#### 2. Smoke-test before freezing

```bash
python -m gui
python main.py ports
python main.py start -hh
```

#### 3. One-folder build (easier debugging)

From `Software/TDC-Logger`:

```bash
pyinstaller ^
  --noconfirm --clean ^
  --name TDC-Logger ^
  --windowed ^
  --paths . ^
  --add-data "gui/fonts;gui/fonts" ^
  --add-data "gui/_icons;gui/_icons" ^
  --hidden-import matplotlib.backends.backend_qtagg ^
  --collect-all PySide6 ^
  --collect-all matplotlib ^
  gui/__main__.py
```

- Output: `dist/TDC-Logger/` containing `TDC-Logger.exe` and dependencies.  
- `--windowed` hides the console; use `--console` while debugging.  
- On Linux/macOS replace `;` with `:` in `--add-data`.

#### 4. Point the frozen GUI at bundled `main.py`

The GUI launches `sys.executable` + `main.py`. In a frozen build, set the CLI entry to a path next to the executable (or embed a second PyInstaller target for `main.py`). Practical options:

- **Option A (simple):** ship `main.py` and the pure-Python modules beside the exe; GUI resolves `_ROOT` relative to the exe and still calls `sys.executable -u main.py …` only if you also ship a minimal Python — **not ideal**.  
- **Option B (recommended):** build **two** PyInstaller targets:
  - `TDC-Logger-GUI.exe` → `gui/__main__.py` (windowed)
  - `TDC-Logger-CLI.exe` → `main.py` (console)
  - GUI `command_builder` / `process_worker` invokes `TDC-Logger-CLI.exe` with the same argv (no `python -u`).
- **Option C:** single process later (in-process session API) — larger refactor; see roadmap.

Until Option B is wired, document that **developer installs** use `python -m gui`, and **release builds** use the dual-exe layout.

#### 5. One-file build (optional)

```bash
pyinstaller --onefile --windowed --name TDC-Logger ...
```

Slower startup; prefer one-folder for lab machines.

#### 6. Smoke-test the frozen app

- Launch GUI from a clean account / machine without a global Python.  
- Plug Arduino, confirm COM list and `(Arduino)` label.  
- START → handshake → ToF → STOP.  
- Confirm logs appear under the Browse folder.  
- Toggle SERIAL / HISTO tabs.

#### 7. Installer (optional)

- **Inno Setup** or **WiX**: install `dist/TDC-Logger/*` to `%LOCALAPPDATA%\Programs\TDC-Logger`, add Start Menu shortcut, optional desktop icon.  
- Request no admin if writing only under the user profile.

#### 8. GitHub Release checklist

1. Tag monorepo: `tdc-logger-vX.Y.Z`.  
2. CI job on Windows:
   - checkout, setup Python, `pip install -r requirements.txt pyinstaller`
   - run PyInstaller
   - upload `dist/TDC-Logger/` as zip + optional installer
3. Release notes: firmware version compatibility, default baud **38400**, CH340/Uno drivers, GPLv3.

### D. Pip / wheel path (developers)

Longer term:

1. Add `pyproject.toml` with project metadata and scripts:

   ```toml
   [project.scripts]
   tdc-logger = "main:main"          # after package layout
   tdc-logger-gui = "gui.__main__:main"
   ```

2. Move modules under a package dir (e.g. `tdc_logger/`) if publishing to PyPI.  
3. `pip install .` or `pipx install tdc-logger`.  
4. Still offer PyInstaller builds for non-Python users.

### E. What not to ship

- `__pycache__/`, `.venv/`, run folders (`session/`, `TEST/`, …)  
- Local QSettings are user-specific (save path) — do not bundle  
- Do not commit large `dist/` / `build/` trees; attach them to Releases only

### F. Minimal CI sketch (GitHub Actions)

```yaml
# .github/workflows/tdc-logger-release.yml (outline)
on:
  push:
    tags: [ 'tdc-logger-v*' ]
jobs:
  windows-gui:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -r Software/TDC-Logger/requirements.txt pyinstaller
      - run: pyinstaller ...   # from Software/TDC-Logger
      - uses: actions/upload-artifact@v4
        with:
          name: TDC-Logger-windows
          path: Software/TDC-Logger/dist/TDC-Logger/
```

---

## Development notes

### Safe shutdown

Ctrl+C or GUI STOP sets a stop event, drains the RX queue into logs, closes the port, flushes + `fsync`s files, then exits. Prefer STOP over killing when possible so data is not lost.

### Histogram (CLI `-g`)

- Unbinned sample store; full rebin + refill  
- Live axis updates; occupancy target ≥ ~10 counts/bin in the core region  
- Settings: `hist_config.py`

### Git workflow (folder inside monorepo)

```bash
# from repository root
git status
git add Software/TDC-Logger
git commit -m "Update TDC-Logger GUI/CLI"
git push origin main
```

Keep run outputs and bytecode out of git (see `.gitignore`).

---

## License

GPLv3-or-later (see file headers). Distributed without warranty; see the GNU GPL for details.
