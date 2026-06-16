---
name: shioaji-depth
description: >
  Record Taiwan TAIFEX futures order-book depth (5-level / 五檔 best bid/ask
  price+volume) to date-partitioned parquet via the SinoPac shioaji SDK, with
  book-invariant validation, atomic writes, and rolling retention. USE WHEN the
  user wants to CONTINUOUSLY capture live TW futures depth. CRITICAL: (1) requires
  a shioaji account + API key; (2) depth is LIVE-ONLY — no back-fill, no archive;
  (3) only during the TW trading session; (4) 5-level only, NOT a full order book;
  (5) must run as a supervised long-lived daemon with retention. 需永豐金帳號；
  僅盤中、五檔、不可回補、須常駐 daemon。
---

# shioaji-depth — Taiwan TAIFEX 5-level (五檔) depth recorder

## 1. When to use / when NOT to use

**Use** when you want to *continuously* record live Taiwan TAIFEX futures
5-level depth (e.g. MTX / TMF / TXF) to parquet for later analysis.

**Do NOT use** when:
- You have no shioaji account. For 24/7 crypto depth use `binance-depth` instead.
- You want historical back-fill. Depth here is **live-only** — there is **no archive
  and no way to reconstruct past depth**. A gap is permanent.
- You want per-trade tick data — use a trades package, not this.
- You want OHLCV bars / snapshots — use `shioaji-bars`.
- You want the **full** order book — this captures only the **best 5 levels (五檔)**.
- You want to place orders — this is **read-only**.

## 2. Install

```bash
pip install "shioaji-depth @ git+https://github.com/Yeimaoz/shioaji-depth.git@v0.1.0"
```

Dependencies: `shioaji` (vendor SDK, requires an account), `pandas`, `pyarrow`,
`python-dotenv`.

## 3. Credentials (security)

You need a SinoPac (永豐金) shioaji **API key + secret** (apply via the broker's
console). This skill **never provides or demonstrates a real key**.

Inject them via environment variables (or a `.env` file kept *outside* the repo and
listed in `.gitignore`):

```bash
export SHIOAJI_API_KEY=<YOUR_API_KEY>
export SHIOAJI_SECRET=<YOUR_API_SECRET>     # or SHIOAJI_SECRET_KEY (doc convention)
```

**Iron rule:** the key/secret must **never** appear in git, issues, PRs, or logs.
Examples always use `<YOUR_API_KEY>` placeholders. Missing credentials raise
`ShioajiAuthError` (fail-loud) rather than silently doing nothing.

## 4. ★ Run as a supervised daemon — and only during the session

Depth cannot be back-filled, so a silent death = a permanent hole. **Always** run
under a process supervisor (systemd `Type=simple` + `Restart=always`, or
tmux + a watchdog). A generic systemd unit:

```ini
[Unit]
Description=TAIFEX 5-level depth recorder
After=network-online.target

[Service]
Type=simple
EnvironmentFile=/path/outside/repo/.env
ExecStart=/usr/bin/python -m shioaji_depth record \
    --symbols MTX,TMF,TXF --data-root /path/to/depth --retention-days 30
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Data only flows during the TW trading session — day session `08:45–13:45`,
night session `15:00–05:00` (next day) **Taipei time**. Outside the session the
recorder is **idle**: no callbacks arrive, the buffer stays empty, and flush is a
no-op. **This is normal** — do not mistake an idle off-hours recorder for a dead
connection. Judge the session window using `Asia/Taipei`, never the host's local
clock (a UTC / WSL host can be off by a day).

## 5. Reconnect / session behavior

On a session error the recorder re-logs-in and re-subscribes (this is a SDK-level
re-subscribe, not a bare websocket reconnect). Snapshots that arrive during the
re-login window are lost permanently. Holding a session outside trading hours may
get the session kicked, depending on deployment mode.

## 6. Daily rotate / write semantics

The buffer flushes every `flush-interval` seconds. Rows are grouped by **event-time
UTC date** into `<data-root>/<symbol>/<YYYY-MM-DD>.parquet`. Writes are atomic
(tmp + rename); an existing day file is merged and de-duplicated on `timestamp_ms`;
a corrupt existing file is preserved as a `.parquet.corrupt-<ts>` sidecar (never
overwritten); on a write failure the rows are re-queued in place (bounded to the
newest 50,000 rows as an OOM guard).

## 7. Data schema (5-level, Case A flat)

21 mandatory columns:

| Column | Type | Meaning |
|---|---|---|
| `timestamp_ms` | int64 | **Exchange event time**, UTC epoch milliseconds |
| `bid_price_1..5` | float64 | Best-5 bid prices (NaN for an unfilled level) |
| `bid_volume_1..5` | float64 | Best-5 bid volumes |
| `ask_price_1..5` | float64 | Best-5 ask prices (NaN for an unfilled level) |
| `ask_volume_1..5` | float64 | Best-5 ask volumes |

Optional columns (enable with `--diff-vol`): `diff_bid_vol_1..5`,
`diff_ask_vol_1..5` (per-level volume deltas the SDK reports).

**Five levels = the best 5 price levels only, NOT the complete order book.** A
shallow / far-month contract may have fewer than 5 filled levels — the unfilled
tail levels are stored as `NaN` (distinct from a genuine zero-volume best level).

## 8. Book invariants (5-level)

Each snapshot is validated; violations are dropped and counted in `invalid_count`:
both sides have a best level; all volumes >= 0; bid prices strictly descending;
ask prices strictly ascending; no duplicate price per side; not crossed/touching
(`best_bid < best_ask`). Fewer-than-5 filled levels is tolerated.

## 9. shioaji-depth vs binance-depth

| | shioaji-depth (this) | binance-depth |
|---|---|---|
| Levels | **5** (五檔) | 20 |
| Auth | Requires a broker account + key | Public, no auth |
| Hours | TW session only | 24/7 |
| Event time | **Yes** (exchange event time) | No (local receive time only) |
| Volume deltas | `diff_*_vol` available | Not available |
| Info depth | Thinner book, richer timing | Deeper book, weaker timing |

Honest trade-off: shioaji-depth gives a *thinner* book (5 vs 20 levels) but carries
a real exchange **event time** (and optional per-level volume deltas), whereas
binance-depth gives a *deeper* 20-level book but only a local receive timestamp.

## 10. Notes / limitations

- 5-level is not a full book — do not treat it as complete for full-book spread /
  imbalance analysis.
- Session count and intraday rate limits apply; for multiple contracts prefer a
  single session with multiple subscriptions.
- `--retention-days` performs **deletion** of old files.
- The clock is the exchange **event time**; mind cross-symbol alignment.
- The exact SDK encoding of unfilled tail levels and the simtrade-session flag are
  confirmed against the shioaji type stub; final field shapes should be verified
  with a one-time live callback dump before relying on edge cases.
