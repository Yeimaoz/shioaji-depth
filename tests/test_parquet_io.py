"""Round-trip / atomic / merge-dedup / corrupt / re-queue / prune tests.

Pure pandas — no shioaji SDK. Cross-platform: uses tmp_path (no POSIX-only paths).
"""
import time

import numpy as np
import pandas as pd

from shioaji_depth.parquet_io import MANDATORY_COLS, prune_old, write_depth_parquet

_PRICE_VOLUME_COLS = (
    [f"bid_price_{i}" for i in range(1, 6)]
    + [f"bid_volume_{i}" for i in range(1, 6)]
    + [f"ask_price_{i}" for i in range(1, 6)]
    + [f"ask_volume_{i}" for i in range(1, 6)]
)


def _row(ts_ms, *, depth=5):
    """A Case-A flat 5-level row; tail levels NaN when depth < 5 (淺盤未滿層)."""
    r = {"timestamp_ms": ts_ms}
    for i in range(1, 6):
        filled = i <= depth
        r[f"bid_price_{i}"] = (100.0 - i) if filled else np.nan
        r[f"bid_volume_{i}"] = (i * 1.0) if filled else np.nan
        r[f"ask_price_{i}"] = (101.0 + i) if filled else np.nan
        r[f"ask_volume_{i}"] = (i * 1.0) if filled else np.nan
    return r


def test_roundtrip_schema_caseA(tmp_path):
    write_depth_parquet({"MTX": [_row(1_700_000_000_000)]}, tmp_path)
    out = list(tmp_path.rglob("*.parquet"))
    assert len(out) == 1
    df = pd.read_parquet(out[0])
    for col in MANDATORY_COLS:
        assert col in df.columns
    assert len(MANDATORY_COLS) == 21
    assert str(df["timestamp_ms"].dtype) == "int64"
    assert str(df["bid_price_1"].dtype) == "float64"  # Case A flat double


def test_unfilled_levels_nan_preserved(tmp_path):
    write_depth_parquet({"TMF": [_row(1_700_000_000_000, depth=2)]}, tmp_path)
    df = pd.read_parquet(next(iter(tmp_path.rglob("*.parquet"))))
    assert pd.isna(df["bid_price_3"].iloc[0])  # level 3 unfilled -> NaN
    assert df["bid_price_1"].iloc[0] == 99.0    # best level has value


def test_atomic_no_orphan_on_success(tmp_path):
    write_depth_parquet({"MTX": [_row(1_700_000_000_000)]}, tmp_path)
    assert not list(tmp_path.rglob("*.tmp*"))


def test_merge_dedup_existing(tmp_path):
    write_depth_parquet({"MTX": [_row(1_700_000_000_000)]}, tmp_path)
    write_depth_parquet({"MTX": [_row(1_700_000_000_000)]}, tmp_path)  # same ts
    df = pd.read_parquet(next(iter(tmp_path.rglob("*.parquet"))))
    assert len(df) == 1  # deduped on timestamp_ms


def test_corrupt_existing_sidecar(tmp_path):
    p = tmp_path / "MTX" / "2023-11-14.parquet"
    p.parent.mkdir(parents=True)
    p.write_text("not parquet")
    write_depth_parquet({"MTX": [_row(1_700_000_000_000)]}, tmp_path)
    assert list((tmp_path / "MTX").glob("*.corrupt-*"))


def test_requeue_on_write_failure_bounded(tmp_path):
    # Point at a path we cannot create a directory under (a regular file).
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    buf = {"MTX": [_row(1_700_000_000_000 + i) for i in range(3)]}
    write_depth_parquet(buf, blocker / "subdir")  # must not raise
    assert buf["MTX"]  # rows retained for retry


def test_prune_old(tmp_path):
    old = 1_600_000_000_000
    new = int(time.time() * 1000)
    write_depth_parquet({"MTX": [_row(old)]}, tmp_path)
    write_depth_parquet({"MTX": [_row(new)]}, tmp_path)
    prune_old(tmp_path, retention_days=30)
    files = list(tmp_path.rglob("*.parquet"))
    assert files  # new survives
    names = {f.name for f in files}
    assert not any("2020" in n for n in names)  # old (2020-09) pruned
