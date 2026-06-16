# shioaji-depth

Generic Taiwan TAIFEX futures **5-level (五檔)** order-book depth recorder via the
SinoPac shioaji SDK → date-partitioned parquet, with book-invariant validation,
atomic writes, and rolling retention.

> ⚠️ **Read first**
> - Requires a **shioaji account + API key** (the `shioaji` SDK is a vendor dependency).
> - Depth is **LIVE-ONLY** — there is **no back-fill and no archive**. A gap is permanent.
> - Data flows **only during the TW trading session** (day `08:45–13:45`, night
>   `15:00–05:00` next day, Taipei time). Off-hours the recorder is idle by design.
> - Captures the **best 5 levels (五檔)**, **not** the full order book.
> - Must run as a **supervised long-lived daemon** (systemd `Restart=always`, etc.),
>   ideally with `--retention-days`.

## Install

```bash
pip install "shioaji-depth @ git+https://github.com/Yeimaoz/shioaji-depth.git@v0.1.0"
```

## Credentials

Provide your SinoPac (永豐金) shioaji key/secret via environment variables (or a
`.env` file kept outside version control). Never commit a real key.

```bash
export SHIOAJI_API_KEY=<YOUR_API_KEY>
export SHIOAJI_SECRET=<YOUR_API_SECRET>     # or SHIOAJI_SECRET_KEY
```

Missing credentials raise `ShioajiAuthError`.

## Quickstart

### CLI

```bash
python -m shioaji_depth record \
    --symbols MTX,TMF,TXF \
    --data-root ./depth \
    --retention-days 30
```

### Library

```python
import asyncio
from shioaji_depth import DepthRecorder

rec = DepthRecorder(
    ["MTX", "TMF", "TXF"],
    "./depth",
    retention_days=30,        # prune files older than 30 days (hourly)
)
asyncio.run(rec.run())        # credentials read from env / .env
```

## Output schema (Case A flat, 21 mandatory columns)

| Column | Type | Meaning |
|---|---|---|
| `timestamp_ms` | int64 | Exchange **event time**, UTC epoch milliseconds |
| `bid_price_1..5` | float64 | Best-5 bid prices (NaN = unfilled level) |
| `bid_volume_1..5` | float64 | Best-5 bid volumes |
| `ask_price_1..5` | float64 | Best-5 ask prices (NaN = unfilled level) |
| `ask_volume_1..5` | float64 | Best-5 ask volumes |

Optional (with `--diff-vol`): `diff_bid_vol_1..5`, `diff_ask_vol_1..5`.

Files are written to `<data-root>/<symbol>/<YYYY-MM-DD>.parquet`, grouped by
event-time UTC date, atomically (tmp + rename), de-duplicated on `timestamp_ms`.

## vs binance-depth

shioaji-depth records a **thinner** book (5 levels) but carries a real exchange
**event time** (plus optional per-level volume deltas); binance-depth records a
**deeper** 20-level book but only a local receive timestamp.

## License

MIT — see [LICENSE](LICENSE).
