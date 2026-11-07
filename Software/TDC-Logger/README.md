# TDC-Logger

Python CLI application for **serial acquisition, parsing, logging, and live histogramming** of Time-of-Flight (ToF) data from a custom Arduino UNO shield that implements a **Time-to-Digital Converter (TDC)**.

This folder lives under the parent repository:

`https://github.com/morcate/UNO-TDC-time-to-digital-converter`

---

## Purpose

TDC-Logger is the PC-side companion to the UNO-TDC hardware:

1. Open a full-duplex UART link to the Arduino (default **38400 baud**).
2. Stream the serial monitor to the terminal (and optionally to disk).
3. Parse 9-byte TDC register frames into physical ToF values in nanoseconds.
4. Filter measurements with an optional upper limit (`lim_sup`).
5. Log raw traffic and valid ToF values into separate files.
6. Optionally display a **real-time ROOT-style histogram** and export a high-resolution PNG.

---

## Folder map (architecture)

```text
TDC-Logger/
├── main.py                 # CLI entry point and session orchestration
├── config.py               # Constants (baud, TDC factor, VIDs, colors, I/O)
├── serial_manager.py       # Port discovery, auto-select, RX/TX threads
├── processors.py           # TDC frame parse + ToF calculation + counters
├── file_logger.py          # Dual-file logger (raw + parsed) with fsync
├── histogram_manager.py    # Live ROOT-style hist (rebin + refill + axes)
├── hist_config.py          # Histogram style / rebinning / export settings
├── requirements.txt        # Python dependencies
└── README.md               # This file
```

### Treemap (logical layers)

```text
TDC-Logger
├── CLI / orchestration .............. main.py
│   ├── argparse (start | ports)
│   ├── session loop (RX queue drain)
│   ├── stop conditions (-m max-samples XOR -T max-time / Ctrl+C)
│   └── summary printout
├── I/O boundary ..................... serial_manager.py + config.py
│   ├── port rank / auto / interactive
│   ├── RX thread → queue.Queue
│   └── TX thread (keyboard → UART)
├── Domain logic ..................... processors.py + config.py
│   ├── 24-bit register rebuild
│   ├── ToF = time * 562.5 / (cal2 - cal1)
│   └── Stop IN / OUT / corrupted counters
├── Persistence ...................... file_logger.py
│   ├── <NAME>/<NAME>_raw.log
│   └── <NAME>/<NAME>.log
└── Visualization .................... histogram_manager.py + hist_config.py
    ├── unbinned ROOT accumulators
    ├── full rebin + refill from scratch
    ├── live X/Y axis rescaling
    └── HD PNG export
```

### Design choices

| Choice | Rationale |
|--------|-----------|
| Threaded RX/TX + main-thread consumer | Keeps UART responsive while parsing, disk I/O, and matplotlib run on the main thread (safer for GUI). |
| Dual log files | Raw log is the audit trail; parsed log is analysis-ready (one ToF per line). |
| Unbinned sample store for the histogram | Enables true ROOT-like rebinning: new edges, then refill every event (no merge of old bin contents). |
| Occupancy ≥ 10 counts/bin (occupied bins) | Keeps less-populated bins statistically meaningful for Poisson-limited ToF spectra. |
| Incremental folder naming | Avoids overwriting previous runs (`TEST`, `TEST_1`, `TEST_2`, …). |
| `BaseProcessor` ABC | Leaves room for alternate parsers without touching the session loop. |

---

## Requirements

- Python **3.8+** (developed/tested with 3.13 on Windows)
- Dependencies:

```text
pyserial>=3.5
numpy>=1.24.0
matplotlib>=3.7.0
```

Install:

```bash
cd Software/TDC-Logger
pip install -r requirements.txt
```

---

## Quick start

List ports (ranked for Arduino / USB-UART likelihood):

```bash
python main.py ports
```

Typical acquisition with auto-start, timestamps, limit, histogram:

```bash
python main.py start -a -t -m 10000 -l 5000.0 -o TEST -g
```

Stream only (no files):

```bash
python main.py start -a --stream-only
```

Raw capture without ToF parsing:

```bash
python main.py start -p COM3 -t -o RAW_CAPTURE --raw-only
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
| `-a` | `--auto-start` | After 3 s send `a` every 1 s until data arrives |
| `-t` | `--timestamp` | Prefix measurement lines in `*_raw.log` with `YYYY-mm-dd HH:MM:SS.mmm` |
| `-m` | `--max-samples N` | Stop after **N** valid in-range (Stop IN) samples (positive integer) |
| `-T` | `--max-time DURATION` | Stop after wall time, e.g. `"10d 3h 45m"` or `45m` (units **d/h/m**, max **31 days**) |
| `-l` | `--lim-sup MAX` | Upper ToF threshold; values with `tof >= lim_sup` count as Stop OUT |
| `-o` | `--out NAME` | Base name for output folder/files (default: timestamp) |
| `-g` | `--hist` | Enable live ROOT-style histogram + HD PNG export |
| | `--raw-only` | Write only `*_raw.log`; skip ToF parsing |
| | `--stream-only` | Terminal only; no disk files |
| `-h` | `--help` | Short help |
| `-hh` | `--help-detailed` | Full English architecture / usage manual |

### Stop conditions (mutually exclusive)

At most one of the following may be set (or neither — run until Ctrl+C):

| Option | Value | Notes |
|--------|-------|-------|
| `-m` / `--max-samples` | positive integer | Counts **Stop IN** samples only |
| `-T` / `--max-time` | `Nd Nh Nm` | Days / hours / minutes; each unit at most once; total ≤ 31 days |

Examples:

```bash
python main.py start -m 10000 -a -g -o TEST
python main.py start -T "10d 3h 45m" -a -o LONG_RUN
python main.py start -T 2h30m -a          # compact form, no spaces
python main.py start -T 45m -a
```

Passing both `-m` and `-T` is a CLI error (`argparse` mutually exclusive group).

### Serial port selection (simplified)

| You want… | Command |
|-----------|---------|
| List ports | `python main.py ports` |
| Auto / menu | `python main.py start …` (no `-p`) |
| Force menu | `python main.py start -i …` |
| Explicit port | `python main.py start -p COM3 …` or `-p 3` |

When `-p` is omitted and `-i` is not set:

1. **One port total** → use it.
2. **Exactly one Arduino** (official VID / name) → use it (even if other COM ports exist).
3. **Exactly one USB-serial candidate** → use it.
4. Otherwise → interactive menu (Enter = preferred).

### Safe stop (Ctrl+C)

Stopping with **Ctrl+C** (or SIGTERM) runs an ordered shutdown:

1. Signal RX/TX threads to stop
2. **Drain** any lines already queued
3. Close the serial port and join worker threads
4. **Flush + `os.fsync`** both log files (parsed buffer included)
5. Save the histogram image (best-effort; logs are already durable)

Do not use force-kill (`taskkill /F`) if you need the last buffered samples on disk.

---

## TDC parsing

Each valid measurement line is **9 space-separated integers** (ASCII 32):

```text
t2 t1 t0  c1_2 c1_1 c1_0  c2_2 c2_1 c2_0
```

24-bit reconstruction:

```text
REG = MSB * 65536 + MID * 256 + LSB
```

yielding `time`, `cal1`, `cal2`.

**Time-of-Flight (ns):**

```text
tof = (time * 562.5) / (cal2 - cal1)
```

The clock factor **562.5** is defined in `config.TDC_CLOCK_FACTOR` and must match the firmware / hardware calibration model.

### Classification

| Condition | Result |
|-----------|--------|
| Line is not 9 integers | Text/header → terminal + raw log only |
| `cal2 - cal1 <= 0` | Corrupted frame counter++ |
| `0 <= tof < lim_sup` | **Stop IN** → parsed log + histogram |
| otherwise | **Stop OUT** → raw log only |

Default `lim_sup` is `+∞` (all non-negative finite ToF values are Stop IN).

---

## Output files

For `-o TEST` (or the next free `TEST_N`):

```text
TEST/
├── TEST_raw.log     # All serial lines (optional timestamps on measurement lines)
├── TEST.log         # Valid Stop IN ToF values, one per line, 3 decimal places
└── TEST_hist.png    # Only if -g was used (600 DPI by default)
```

- Raw file is flushed frequently; OS `fsync` runs about once per second.
- Parsed file is buffered (50 lines) then flushed; final flush on close.

---

## Live histogram (ROOT guidelines)

Implemented in `histogram_manager.py` / `hist_config.py`.

### Statistics (CERN ROOT TH1, unit weights)

```text
fTsumw   = N
fTsumwx  = Σ x_i
fTsumwx2 = Σ x_i²
mean     = fTsumwx / fTsumw
sigma    = sqrt(max(0, fTsumwx2/fTsumw − mean²))
```

Stats are maintained incrementally on `add_value` and recomputed from scratch on every full rebuild.

### Rebinning = rebuild from scratch

On each refresh cycle (default every 0.5 s when new data arrived):

1. Take the **entire unbinned sample** stored in memory.
2. Recompute ROOT stats from that array.
3. Derive the **X range** from data min/max (+ small margin).
4. Choose the finest uniform `n_bins` such that **occupied bins inside the core window** `[mean ± CORE_SIGMA_MULTIPLIER·σ]` (default ±2σ) generally hold **≥ 10 entries** (`MIN_COUNTS_PER_BIN`), capped by `MAX_BINS` and by `N / 10`.
5. **Refill** all samples into the new edges (`numpy.histogram` over the full array — equivalent to ROOT `Reset` + `SetBins` + `Fill` for every event).
6. **Live-rescale** axes: X = histogram edges (from data min/max + margin), Y = `[0, max(counts) * headroom]`.
7. Redraw step histogram, optional markers, and a TPaveStats-like box (Entries / Mean / Std Dev / Bins).

Far-tail empty bins are allowed. The occupancy floor targets the **less-populated core/shoulder bins**, so they stay around ≥10 counts without collapsing the whole spectrum to a handful of bins because of rare outliers.

Style knobs live only in `hist_config.py` (colors, DPI, titles, margins, `MIN_COUNTS_PER_BIN`, …).

---

## Module reference

### `main.py`

- Builds the argparse CLI (`start`, `ports`, `-hh`).
- Owns the session loop: auto-start TX, queue drain, processor dispatch, logger, histogram refresh, stop conditions, final summary.

### `config.py`

- `DEFAULT_BAUD_RATE = 38400`
- `TDC_CLOCK_FACTOR = 562.5`
- `EXPECTED_REGISTER_BYTES = 9`
- Arduino / USB-UART USB Vendor IDs
- Flush / fsync intervals
- Optional ANSI color codes

### `serial_manager.py`

- `rank_ports()`, `print_ports()`, `resolve_port()`, interactive menu
- `SerialManager.open/close` with daemon RX/TX threads
- Windows: `msvcrt` single-key TX without Enter

### `processors.py`

- `ProcessResult` dataclass
- `TdcProcessor.process_line()` → parse, ToF, range filter, counters

### `file_logger.py`

- Creates `./<NAME>/` with anti-overwrite suffix
- `log_raw` / `log_parsed` / `flush_parsed` / `close` with `os.fsync`

### `histogram_manager.py` / `hist_config.py`

- See [Live histogram](#live-histogram-root-guidelines)

---

## GitHub workflow (this folder inside the monorepo)

Remote (parent repo):

```text
git@github.com:morcate/UNO-TDC-time-to-digital-converter.git
```

Suggested local workflow from the **repository root**:

```bash
# inspect
git status
git diff

# do not commit bytecode or run outputs
# (see .gitignore in this folder)

git add Software/TDC-Logger
git commit -m "Add/update TDC-Logger: CLI logger, ROOT live histogram, docs"
git push origin main
```

Recommendations:

1. Keep run folders (`TEST/`, timestamp dirs) and `__pycache__/` out of git.
2. Prefer small, focused commits under `Software/TDC-Logger/`.
3. Update this README when CLI flags or the ToF formula change.
4. Tag releases at the monorepo level when packaging (see roadmap below).

---

## Roadmap notes (not implemented yet)

### Graphical interface (preparations)

- Extract a thin **service layer** from `main.run_logger` (start/stop session, callbacks for status, ToF, hist snapshot) so both CLI and GUI call the same API.
- Keep `SerialManager`, `TdcProcessor`, `DualFileLogger`, `RootHistogramManager` GUI-agnostic (already mostly true).
- Prefer **PySide6 / Qt** or **Dear PyGui** for a responsive desktop UI; avoid driving heavy widgets from the RX thread — keep the queue + main-thread pattern.
- Histogram: either embed matplotlib `FigureCanvas` or later swap the renderer behind `RootHistogramManager`.
- Port picker UI can reuse `SerialManager.rank_ports()` / `resolve_port()` logic.

### Installable application from GitHub (preparations)

1. Add `pyproject.toml` (`project.scripts` entry point, e.g. `tdc-logger = tdc_logger.main:main`).
2. Repackage modules under a proper package directory (`tdc_logger/`) instead of a flat script folder.
3. Add `LICENSE` (GPLv3 text already referenced in headers) at repo or package level.
4. CI: lint + smoke test of parser on fixture lines; optional GUI-less hist unit test.
5. Windows installers: **PyInstaller** or **briefcase** one-folder/one-file builds; ship a Start-menu shortcut.
6. GitHub Releases: build artifacts on tag; attach `.exe` / `.msi` / wheel.
7. Optional: `winget` / Scoop manifest once a stable release exists.

---

## License

GPLv3-or-later (see file headers). Distributed without warranty; see the GNU GPL for details.
