"""Atomic, date-partitioned parquet writer for Taiwan TAIFEX 5-level depth.

write_depth_parquet: buffer dict[symbol -> list[row]] -> <root>/<symbol>/<YYYY-MM-DD>.parquet.
  - each row is a "Case A flat" 5-level snapshot: timestamp_ms (event-time, UTC ms)
    + bid_price_1..5 / bid_volume_1..5 / ask_price_1..5 / ask_volume_1..5 (float64,
    NaN for unfilled levels) + optional recv_ms / diff_bid_vol_1..5 / diff_ask_vol_1..5.
  - groupby UTC date (derived from event-time timestamp_ms), merge+dedup existing on
    timestamp_ms (only when the day file already exists), atomic tmp+rename.
  - corrupt existing -> .parquet.corrupt-<ts> sidecar (preserve, don't overwrite).
  - write failure -> re-queue rows in-place, bounded to newest _MAX_BUFFER (OOM guard).

prune_old: delete files whose timestamp_ms.max() < now - retention_days.

This module is vendor-generic: no orchestration policy, no fixed data root, no
hard-coded symbol list. timestamp_ms is the EXCHANGE EVENT TIME in UTC ms
(callers parse the shioaji event-time tuple; see recorder._on_bidask).
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

_MAX_BUFFER = 50_000
_MS_PER_DAY = 86_400_000

# Case A flat schema — 21 mandatory columns (event-time + best-5 price/volume per side).
_PRICE_VOLUME_COLS = (
    [f"bid_price_{i}" for i in range(1, 6)]
    + [f"bid_volume_{i}" for i in range(1, 6)]
    + [f"ask_price_{i}" for i in range(1, 6)]
    + [f"ask_volume_{i}" for i in range(1, 6)]
)
MANDATORY_COLS = ["timestamp_ms"] + _PRICE_VOLUME_COLS


def write_depth_parquet(buffer: dict[str, list[dict]], root: Path) -> int:
    """Flush buffered 5-level depth rows to date-partitioned parquet (atomic).

    Mutates ``buffer`` in place: a symbol's rows are cleared only on a fully
    successful write; on failure they are re-queued (bounded to the newest
    ``_MAX_BUFFER`` rows to guard against OOM).

    Returns the total number of rows written.
    """
    root = Path(root)
    total = 0

    for symbol, rows in list(buffer.items()):
        if not rows:
            continue
        try:
            df = pd.DataFrame(rows)
            df["timestamp_ms"] = df["timestamp_ms"].astype("int64")
            # Price/volume columns are float64 (NaN marks unfilled levels — distinct
            # from a genuine zero-volume best level).
            for col in _PRICE_VOLUME_COLS:
                if col in df.columns:
                    df[col] = df[col].astype("float64")

            for date_str, group in df.groupby(
                pd.to_datetime(df["timestamp_ms"], unit="ms", utc=True).dt.strftime(
                    "%Y-%m-%d"
                )
            ):
                out_dir = root / symbol
                out_dir.mkdir(parents=True, exist_ok=True)
                out_path = out_dir / f"{date_str}.parquet"

                if out_path.exists():
                    try:
                        existing = pd.read_parquet(out_path)
                        group = pd.concat([existing, group], ignore_index=True)
                    except Exception as exc:
                        # Preserve corrupt file as sidecar, log loudly.
                        sidecar = out_path.with_suffix(
                            f".parquet.corrupt-{int(time.time())}"
                        )
                        print(
                            f"  [flush:depth] WARNING: corrupt read {out_path} "
                            f"({type(exc).__name__}: {exc}) — "
                            f"renaming to {sidecar.name}",
                            flush=True,
                        )
                        try:
                            out_path.rename(sidecar)
                        except OSError as rename_err:
                            print(
                                f"  [flush:depth] ERROR: could not rename corrupt "
                                f"file {out_path}: {rename_err}",
                                flush=True,
                            )
                        # Proceed: group contains only the buffered rows.

                    group = group.drop_duplicates(
                        subset=["timestamp_ms"], keep="last"
                    )

                # Atomic write: tmp + rename (atomic on the same filesystem).
                tmp_path = out_path.with_suffix(".tmp.parquet")
                group.to_parquet(tmp_path, compression="zstd", index=False)
                tmp_path.replace(out_path)

            total += len(rows)
            # Clear buffer ONLY on success (all date-groups written).
            buffer[symbol] = []

        except Exception as e:  # noqa: BLE001 — flush must never crash the loop
            print(f"  [flush:depth] {symbol}: {e}", flush=True)
            # Re-queue rows on write failure with bounded cap.
            all_rows = rows  # original rows (not cleared)
            if len(all_rows) > _MAX_BUFFER:
                # Keep newest _MAX_BUFFER rows.
                all_rows = sorted(all_rows, key=lambda r: r["timestamp_ms"])
                all_rows = all_rows[-_MAX_BUFFER:]
            buffer[symbol] = all_rows

    if total:
        print(f"  [flush:depth] {total} records", flush=True)
    return total


def prune_old(root: Path, retention_days: int) -> None:
    """Delete parquet files whose newest row is older than ``retention_days``."""
    root = Path(root)
    cutoff = int(time.time() * 1000) - retention_days * _MS_PER_DAY
    if not root.exists():
        return
    for p in root.rglob("*.parquet"):
        if "tmp" in p.suffixes:
            continue
        try:
            df = pd.read_parquet(p, columns=["timestamp_ms"])
            if df["timestamp_ms"].max() < cutoff:
                p.unlink()
                print(f"  [cleanup] deleted {p.relative_to(root.parent)}", flush=True)
        except Exception:  # noqa: BLE001 — best-effort prune, never crash
            pass
