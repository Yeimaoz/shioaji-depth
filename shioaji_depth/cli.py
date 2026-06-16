"""Command-line entrypoint for shioaji-depth.

    python -m shioaji_depth record --symbols MTX,TMF,TXF --data-root ./depth

Runs a supervised-friendly recorder loop. Depth is LIVE-ONLY and cannot be
back-filled; run under a process supervisor (systemd Restart=always, etc.).

Credentials are read from env / .env (SHIOAJI_API_KEY + SHIOAJI_SECRET or
SHIOAJI_SECRET_KEY) — NEVER passed as CLI flags.
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .recorder import DepthRecorder


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shioaji-depth")
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record", help="record TAIFEX 5-level (五檔) BidAsk to parquet")
    rec.add_argument(
        "--symbols",
        required=True,
        help="comma-separated TAIFEX shortcodes, e.g. MTX,TMF,TXF",
    )
    rec.add_argument(
        "--data-root",
        required=True,
        type=Path,
        help="output directory; files written to <data-root>/<symbol>/<date>.parquet",
    )
    rec.add_argument(
        "--flush-interval",
        type=int,
        default=60,
        help="seconds between buffer flushes (default: 60)",
    )
    rec.add_argument(
        "--retention-days",
        type=int,
        default=None,
        help="prune files older than N days (default: disabled, keep forever)",
    )
    rec.add_argument(
        "--diff-vol",
        action="store_true",
        help="also record diff_bid_vol_1..5 / diff_ask_vol_1..5 columns",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    if args.command == "record":
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
        recorder = DepthRecorder(
            symbols,
            args.data_root,
            flush_interval_s=args.flush_interval,
            retention_days=args.retention_days,
            record_diff_vol=args.diff_vol,
        )
        asyncio.run(recorder.run())


if __name__ == "__main__":
    main()
