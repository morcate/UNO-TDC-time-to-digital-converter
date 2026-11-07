# TDC-Logger — folder architecture

English architecture note for `Software/TDC-Logger`. Full user documentation lives in `README.md`.

## Treemap

```text
TDC-Logger/
│
├── Entry & CLI
│   └── main.py
│       • argparse: start | ports | -hh detailed manual
│       • stop: -m/--max-samples XOR -T/--max-time (Nd Nh Nm, ≤31d)
│       • session orchestration (queue, stop conditions, summary)
│       • wires SerialManager + TdcProcessor + DualFileLogger + RootHistogramManager
│
├── Configuration
│   └── config.py
│       • baud 38400, TDC_CLOCK_FACTOR 562.5, 9-byte frames
│       • Arduino / USB-UART VIDs, flush/fsync policy, ANSI colors
│
├── Serial I/O
│   └── serial_manager.py
│       • rank / auto-select / interactive / list ports
│       • full-duplex UART: RX → queue, keyboard TX (msvcrt on Windows)
│
├── Parsing domain
│   └── processors.py
│       • BaseProcessor ABC + TdcProcessor
│       • 24-bit rebuild, ToF formula, Stop IN/OUT/corrupt counters
│
├── Persistence
│   └── file_logger.py
│       • ./NAME/ with anti-overwrite suffix
│       • NAME_raw.log (audit) + NAME.log (valid ToF)
│
└── Live visualization
    ├── histogram_manager.py
    │   • ROOT TH1 unbinned stats (fTsumw, fTsumwx, fTsumwx2)
    │   • rebin = new edges + refill entire sample from scratch
    │   • live X/Y rescaling from parsed data
    │   • occupied bins generally ≥ 10 counts
    └── hist_config.py
        • style, DPI, occupancy, axis margins (English labels)
```

## Architectural choices

1. **Main-thread consumer, threaded I/O** — matplotlib and file writes stay off the RX thread.
2. **Unbinned hist source of truth** — rebinning never merges previous bin arrays; it always re-fills from the raw ToF list (ROOT-like).
3. **Dual logs** — raw stream for debugging firmware/UART; parsed ToF for analysis.
4. **Processor ABC** — future alternate formats can plug in without rewriting `main.py`.
5. **Config modules** — tune baud/TDC factor and hist style without touching algorithms.

## Data flow

```text
Arduino UART
    → SerialManager RX thread
        → queue.Queue
            → main loop
                → TdcProcessor
                    → DualFileLogger (raw always; parsed if Stop IN)
                    → RootHistogramManager.add_value (if -g and Stop IN)
                → rebuild_and_render (throttled)
```

## Related docs

- User manual and GitHub workflow: `README.md`
- Parent hardware/firmware repo README: `../../README.md`
