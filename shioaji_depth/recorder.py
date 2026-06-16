"""Taiwan TAIFEX futures 5-level (五檔) order-book depth recorder.

DepthRecorder logs into shioaji, resolves each shortcode to its rolling
front-month contract, subscribes to the BidAsk FOP stream, and on each
``on_bidask_fop_v1`` callback parses the best-5 levels into a flat row,
validates the book, buffers it, and periodically flushes to date-partitioned
parquet via parquet_io.

KEY SDK FACTS (confirmed against shioaji._core.BidAskFOPv1 type stub):
- ``bid_price`` / ``ask_price`` are ``List[str]`` — must be ``float(str)``-converted.
- ``bid_volume`` / ``ask_volume`` / ``diff_bid_vol`` / ``diff_ask_vol`` are ``List[int]``.
- ``datetime`` is a 7-tuple ``(year, month, day, hour, minute, second, microsecond)``,
  NAIVE local time → must be localized to Asia/Taipei, then converted to UTC ms.
- ``simtrade`` (bool) marks simulated-trading-session ticks; these are dropped.

Depth is LIVE-ONLY: it cannot be back-filled (no archive). Data only flows
during the TW trading session; outside it the recorder is idle (no callbacks,
flush is a no-op) — this is normal, not a fault.

NOTE: the "未滿 5 層的真實表示" (how the SDK encodes fewer than 5 filled levels)
and the precise simtrade-filter behavior require a one-time live callback dump to
fully confirm. See README / SKILL.md "[NEEDS-ACCOUNT]". This module assumes
shorter lists / 0-price entries mark unfilled tail levels.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .contracts import resolve_contract
from .parquet_io import prune_old, write_depth_parquet
from .session import login

logger = logging.getLogger(__name__)

_TPE = ZoneInfo("Asia/Taipei")
_CLEANUP_INTERVAL_S = 3600  # prune retention hourly
_DEPTH = 5  # 五檔 — best 5 levels per side


def _event_tuple_to_utc_ms(dt_tuple: Any) -> int:
    """Convert a shioaji naive Asia/Taipei 7-tuple to UTC epoch milliseconds.

    The shioaji ``datetime`` field is ``(year, month, day, hour, minute, second,
    microsecond)`` in NAIVE Taipei local time. We localize to Asia/Taipei first,
    then convert to UTC — never assume it is already UTC.
    """
    y, mo, d, h, mi, s, us = (int(x) for x in dt_tuple[:7])
    local = datetime(y, mo, d, h, mi, s, us, tzinfo=_TPE)
    return int(local.timestamp() * 1000)


def _to_float(x: Any) -> float:
    """Parse a shioaji price (str) to float; NaN on empty / unparseable."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return math.nan
    return v


def validate_book(
    bid_p: list[float],
    bid_v: list[float],
    ask_p: list[float],
    ask_v: list[float],
) -> bool:
    """Return True iff the (partial) 5-level book satisfies all invariants.

    Tolerates fewer than 5 filled levels (淺盤): only the levels actually present
    are checked. Invariants:
    1. Both sides have at least a best level (non-empty).
    2. All quantities >= 0.
    3. Bid prices strictly descending (best bid first).
    4. Ask prices strictly ascending (best ask first).
    5. No duplicate price on the same side.
    6. best_bid < best_ask (not crossed, not touching).
    """
    if not bid_p or not ask_p:
        return False
    if any(q < 0 for q in bid_v) or any(q < 0 for q in ask_v):
        return False
    # Bids strictly descending.
    if any(bid_p[i] <= bid_p[i + 1] for i in range(len(bid_p) - 1)):
        return False
    # Asks strictly ascending.
    if any(ask_p[i] >= ask_p[i + 1] for i in range(len(ask_p) - 1)):
        return False
    # No duplicate prices per side (covered by strict ordering above, but explicit).
    if len(bid_p) != len(set(bid_p)) or len(ask_p) != len(set(ask_p)):
        return False
    # No crossed / touching book.
    if bid_p[0] >= ask_p[0]:
        return False
    return True


class DepthRecorder:
    """Records TAIFEX 5-level (五檔) BidAsk snapshots for a set of symbols.

    Args:
        symbols: TAIFEX shortcodes, e.g. ["MTX", "TMF", "TXF"].
        data_root: directory under which <symbol>/<YYYY-MM-DD>.parquet are written.
        api_key / secret: credentials; default to env (SHIOAJI_API_KEY / SHIOAJI_SECRET).
        flush_interval_s: seconds between buffer flushes.
        retention_days: if set, files older than this many days are pruned hourly;
            if None, retention pruning is disabled (files kept forever).
        record_diff_vol: also persist diff_bid_vol_1..5 / diff_ask_vol_1..5 columns.
    """

    invalid_count: dict[str, int]

    def __init__(
        self,
        symbols: list[str],
        data_root: Path,
        *,
        api_key: str | None = None,
        secret: str | None = None,
        flush_interval_s: int = 60,
        retention_days: int | None = None,
        record_diff_vol: bool = False,
    ) -> None:
        self.symbols = list(symbols)
        self._api_key = api_key
        self._secret = secret
        self.flush_interval_s = flush_interval_s
        self.retention_days = retention_days
        self.record_diff_vol = record_diff_vol
        self._data_root = Path(data_root)
        self._buf: dict[str, list[dict]] = {s: [] for s in self.symbols}
        self.invalid_count = {s: 0 for s in self.symbols}
        self._code_to_symbol: dict[str, str] = {}
        self._api: Any = None
        self._last_flush = time.time()
        self._last_cleanup = time.time()

    def _parse_bidask(self, bidask: Any) -> dict | None:
        """Parse a shioaji BidAskFOPv1 into a Case-A flat row, or None if dropped.

        Drops simtrade ticks and books that fail invariants (counted by caller).
        """
        # bid_price / ask_price are List[str] -> float; volumes are List[int].
        bid_p = [_to_float(p) for p in (getattr(bidask, "bid_price", None) or [])]
        ask_p = [_to_float(p) for p in (getattr(bidask, "ask_price", None) or [])]
        bid_v = [float(v) for v in (getattr(bidask, "bid_volume", None) or [])]
        ask_v = [float(v) for v in (getattr(bidask, "ask_volume", None) or [])]

        # A filled level needs a finite, non-zero price; trailing 0/NaN prices
        # mark unfilled tail levels in a shallow book.
        def _trim(prices: list[float], vols: list[float]) -> tuple[list[float], list[float]]:
            out_p: list[float] = []
            out_v: list[float] = []
            for i in range(min(len(prices), len(vols), _DEPTH)):
                if not math.isfinite(prices[i]) or prices[i] == 0.0:
                    break
                out_p.append(prices[i])
                out_v.append(vols[i])
            return out_p, out_v

        bid_p, bid_v = _trim(bid_p, bid_v)
        ask_p, ask_v = _trim(ask_p, ask_v)

        if not validate_book(bid_p, bid_v, ask_p, ask_v):
            return None

        row: dict[str, Any] = {
            "timestamp_ms": _event_tuple_to_utc_ms(getattr(bidask, "datetime"))
        }
        for i in range(1, _DEPTH + 1):
            idx = i - 1
            row[f"bid_price_{i}"] = bid_p[idx] if idx < len(bid_p) else math.nan
            row[f"bid_volume_{i}"] = bid_v[idx] if idx < len(bid_v) else math.nan
            row[f"ask_price_{i}"] = ask_p[idx] if idx < len(ask_p) else math.nan
            row[f"ask_volume_{i}"] = ask_v[idx] if idx < len(ask_v) else math.nan

        if self.record_diff_vol:
            dbv = list(getattr(bidask, "diff_bid_vol", None) or [])
            dav = list(getattr(bidask, "diff_ask_vol", None) or [])
            for i in range(1, _DEPTH + 1):
                idx = i - 1
                row[f"diff_bid_vol_{i}"] = float(dbv[idx]) if idx < len(dbv) else math.nan
                row[f"diff_ask_vol_{i}"] = float(dav[idx]) if idx < len(dav) else math.nan

        return row

    def _on_bidask(self, symbol: str, bidask: Any) -> None:
        """Handle one BidAsk callback for ``symbol``: parse, validate, buffer."""
        # Drop simulated-trading-session ticks.
        if getattr(bidask, "simtrade", False):
            return
        row = self._parse_bidask(bidask)
        if row is None:
            self.invalid_count[symbol] += 1
            if self.invalid_count[symbol] % 100 == 1:
                print(
                    f"  [depth:{symbol}] WARNING: dropped invalid book "
                    f"(total_dropped={self.invalid_count[symbol]})",
                    flush=True,
                )
            return
        self._buf[symbol].append(row)

    def _flush(self) -> None:
        """Flush buffered rows to parquet (no-op on empty buffer)."""
        write_depth_parquet(self._buf, self._data_root)
        self._last_flush = time.time()

    def _cleanup(self) -> None:
        """Prune files older than retention_days (no-op if retention disabled)."""
        if self.retention_days is not None:
            prune_old(self._data_root, self.retention_days)
        self._last_cleanup = time.time()

    def _resolve_all(self) -> dict[Any, str]:
        """Resolve every shortcode -> contract; build code->symbol reverse map."""
        contracts: dict[Any, str] = {}
        for sym in self.symbols:
            c = resolve_contract(self._api, sym)
            contracts[c] = sym
            code = getattr(c, "code", None)
            if code is not None:
                self._code_to_symbol[str(code)] = sym
        return contracts

    def _make_callback(self):
        """Build an on_bidask_fop_v1 callback that routes by contract code."""

        def _cb(exchange: Any, bidask: Any) -> None:  # noqa: ARG001 — shioaji signature
            code = str(getattr(bidask, "code", ""))
            symbol = self._code_to_symbol.get(code)
            if symbol is None:
                return
            self._on_bidask(symbol, bidask)

        return _cb

    async def run(self) -> None:
        """Login, subscribe BidAsk for all symbols, flush+prune periodically.

        Blocks until cancelled. Outside the TW trading session there are no
        callbacks (idle) — flush is a no-op and this is NOT treated as an error.
        On a session error, re-login + re-subscribe (not a bare WS reconnect).
        """
        import shioaji as sj

        print(f"DepthRecorder: {len(self.symbols)} symbols x BidAsk FOP (五檔)")
        print(f"  depth -> {self._data_root}")
        if self.retention_days is not None:
            print(f"  rolling {self.retention_days}-day retention")
        else:
            print("  retention disabled (files kept forever)")

        while True:
            try:
                self._api = login(api_key=self._api_key, secret=self._secret)
                contracts = self._resolve_all()
                callback = self._make_callback()
                self._api.on_bidask_fop_v1()(callback)
                for contract in contracts:
                    self._api.quote.subscribe(
                        contract, quote_type=sj.constant.QuoteType.BidAsk
                    )

                self._cleanup()  # prune stale files on (re)start

                # Idle-tolerant flush/prune loop; callbacks fire in the SDK thread.
                while True:
                    await asyncio.sleep(self.flush_interval_s)
                    self._flush()
                    if time.time() - self._last_cleanup > _CLEANUP_INTERVAL_S:
                        self._cleanup()
            except asyncio.CancelledError:
                self._flush()  # best-effort final flush
                raise
            except Exception as e:  # noqa: BLE001 — re-login on any session error
                print(f"  [depth] session error, re-login in 5s: {e}", flush=True)
                await asyncio.sleep(5)
