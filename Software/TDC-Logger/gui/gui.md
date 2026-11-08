# gui/ — TDC-Logger desktop shell

## Treemap

```text
gui/
├── __init__.py
├── __main__.py          # python -m gui
├── command_builder.py   # form state → CLI argv (-a --gui always)
├── process_worker.py    # QProcess + NDJSON reader + STOP
├── hist_panel.py        # MPL embed, ≤3 Hz redraw
├── serial_panel.py      # serial/log monitor
├── main_window.py       # mockup layout + wiring
└── gui.md
```

## Architecture

```text
MainWindow
  → build_cli_argv (always -a --gui)
  → CliProcessController.start(argv)
       CLI main.py --gui
         stdout NDJSON → parse → signals
         stdin STOP ← request_stop()
  → LiveHistPanel (tof in-range only, 3 Hz)
  → SerialMonitorPanel (raw + log + stderr)
```

## Run

```bash
cd Software/TDC-Logger
pip install -r requirements.txt
python -m gui
```

## Packaging

See parent **[README.md — Packaging for distribution](../README.md#packaging-for-distribution)** for PyInstaller dual-exe layout, installer, and GitHub Releases steps.
