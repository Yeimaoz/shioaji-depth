"""TwDepthRecorder tests with a mock shioaji BidAskFOPv1 payload.

The fake payload mirrors the real shioaji._core.BidAskFOPv1 stub:
- bid_price / ask_price are List[str] (NOT float) -> exercises str->float conversion.
- bid_volume / ask_volume / diff_*_vol are List[int].
- datetime is a 7-tuple naive Asia/Taipei local time -> exercises 7-tuple->UTC ms.

NOTE: the exact representation of unfilled tail levels and the simtrade-filter
behavior are confirmed against the type stub here; final shape requires a live
callback dump ([NEEDS-ACCOUNT]).
"""
import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from shioaji_depth.recorder import TwDepthRecorder

_TPE = ZoneInfo("Asia/Taipei")


class FakeBidAskFOP:
    """Mirror of shioaji._core.BidAskFOPv1 (only the fields we parse)."""

    def __init__(
        self,
        *,
        code="MXFR1",
        dt=(2023, 11, 14, 9, 0, 0, 0),
        bid_price=("100", "99", "98", "97", "96"),
        bid_volume=(1, 2, 3, 4, 5),
        ask_price=("101", "102", "103", "104", "105"),
        ask_volume=(1, 2, 3, 4, 5),
        diff_bid_vol=(0, 0, 0, 0, 0),
        diff_ask_vol=(0, 0, 0, 0, 0),
        simtrade=False,
    ):
        self.code = code
        self.datetime = dt
        self.bid_price = list(bid_price)   # List[str] — real SDK type
        self.bid_volume = list(bid_volume)
        self.ask_price = list(ask_price)   # List[str] — real SDK type
        self.ask_volume = list(ask_volume)
        self.diff_bid_vol = list(diff_bid_vol)
        self.diff_ask_vol = list(diff_ask_vol)
        self.simtrade = simtrade


def _rec(tmp_path, **kw):
    return TwDepthRecorder(["MTX"], tmp_path, api_key="K", secret="S", **kw)


def test_on_bidask_appends_valid(tmp_path):
    r = _rec(tmp_path)
    r._on_bidask("MTX", FakeBidAskFOP())
    assert len(r._buf["MTX"]) == 1


def test_str_prices_converted_to_float(tmp_path):
    r = _rec(tmp_path)
    r._on_bidask("MTX", FakeBidAskFOP())
    row = r._buf["MTX"][0]
    assert isinstance(row["bid_price_1"], float)
    assert row["bid_price_1"] == 100.0   # "100" (str) -> 100.0 (float)
    assert row["ask_price_1"] == 101.0   # "101" (str) -> 101.0 (float)
    assert row["bid_volume_1"] == 1.0


def test_event_tuple_converted_to_utc_ms(tmp_path):
    r = _rec(tmp_path)
    # 7-tuple naive Asia/Taipei time.
    r._on_bidask("MTX", FakeBidAskFOP(dt=(2023, 11, 14, 9, 0, 0, 0)))
    row = r._buf["MTX"][0]
    # Asia/Taipei 09:00 == 01:00 UTC (TWT is UTC+8, no DST).
    expected = int(
        datetime(2023, 11, 14, 9, 0, 0, 0, tzinfo=_TPE).timestamp() * 1000
    )
    assert row["timestamp_ms"] == expected
    # Sanity: 2023-11-14 09:00 TWT == 2023-11-14 01:00 UTC.
    utc = datetime.fromtimestamp(row["timestamp_ms"] / 1000, tz=timezone.utc)
    assert utc.hour == 1


def test_partial_book_unfilled_levels_nan(tmp_path):
    r = _rec(tmp_path)
    # Only 2 filled levels; trailing prices are "0" (unfilled marker).
    r._on_bidask(
        "MTX",
        FakeBidAskFOP(
            bid_price=("100", "99", "0", "0", "0"),
            bid_volume=(1, 2, 0, 0, 0),
            ask_price=("101", "102", "0", "0", "0"),
            ask_volume=(1, 2, 0, 0, 0),
        ),
    )
    row = r._buf["MTX"][0]
    assert row["bid_price_1"] == 100.0
    assert row["bid_price_2"] == 99.0
    assert math.isnan(row["bid_price_3"])  # unfilled tail level -> NaN
    assert math.isnan(row["ask_volume_5"])


def test_flat_schema_21_keys(tmp_path):
    r = _rec(tmp_path)
    r._on_bidask("MTX", FakeBidAskFOP())
    row = r._buf["MTX"][0]
    assert set(row.keys()) == {
        "timestamp_ms",
        *[f"bid_price_{i}" for i in range(1, 6)],
        *[f"bid_volume_{i}" for i in range(1, 6)],
        *[f"ask_price_{i}" for i in range(1, 6)],
        *[f"ask_volume_{i}" for i in range(1, 6)],
    }


def test_diff_vol_optional_columns(tmp_path):
    r = _rec(tmp_path, record_diff_vol=True)
    r._on_bidask("MTX", FakeBidAskFOP(diff_bid_vol=(3, 0, 0, 0, 0)))
    row = r._buf["MTX"][0]
    assert row["diff_bid_vol_1"] == 3.0
    assert "diff_ask_vol_5" in row


def test_on_bidask_drops_invalid_and_counts(tmp_path):
    r = _rec(tmp_path)
    # Crossed book: best_bid (101) >= best_ask (100).
    r._on_bidask(
        "MTX",
        FakeBidAskFOP(
            bid_price=("101", "0", "0", "0", "0"),
            bid_volume=(1, 0, 0, 0, 0),
            ask_price=("100", "0", "0", "0", "0"),
            ask_volume=(1, 0, 0, 0, 0),
        ),
    )
    assert len(r._buf["MTX"]) == 0
    assert r.invalid_count["MTX"] == 1


def test_simtrade_dropped(tmp_path):
    r = _rec(tmp_path)
    r._on_bidask("MTX", FakeBidAskFOP(simtrade=True))
    assert len(r._buf["MTX"]) == 0
    # Simtrade is filtered before validation, so it is not counted as invalid.
    assert r.invalid_count["MTX"] == 0


def test_idle_flush_no_callback_not_error(tmp_path):
    # Outside the trading session: no callbacks, empty buffer, flush is a no-op.
    r = _rec(tmp_path)
    r._flush()  # must not raise on empty buffer
    assert all(len(v) == 0 for v in r._buf.values())


def test_callback_routes_by_code(tmp_path):
    r = _rec(tmp_path)
    r._code_to_symbol = {"MXFR1": "MTX"}
    cb = r._make_callback()
    cb("TAIFEX", FakeBidAskFOP(code="MXFR1"))
    assert len(r._buf["MTX"]) == 1
    # Unknown code is ignored.
    cb("TAIFEX", FakeBidAskFOP(code="ZZZR1"))
    assert len(r._buf["MTX"]) == 1


def test_valid_row_persists_round_trip(tmp_path):
    import pandas as pd

    r = _rec(tmp_path)
    r._on_bidask("MTX", FakeBidAskFOP())
    r._flush()
    df = pd.read_parquet(next(iter(tmp_path.rglob("*.parquet"))))
    assert len(df) == 1
    assert str(df["timestamp_ms"].dtype) == "int64"
    assert df["bid_price_1"].iloc[0] == 100.0
