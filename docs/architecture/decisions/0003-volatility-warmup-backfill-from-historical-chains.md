# 0003 — Volatility warm-up: backfill from historical option chains

| | |
|---|---|
| **Status** | **Superseded by [0013](0013-volatility-threshold-ten-sessions.md).** The bulk backfill it directs was declined; the warm-up is shortened instead. The correctness requirement it states survives and is still binding on the backfill tool. |
| **Date** | 2026-09-07 |
| **Round** | 1 |
| **Original identifier** | `D3` — cited by that name throughout the task documents |

---

Replay past option chains into `daily_snapshot` so the 20-session baseline already exists,
rather than waiting ~4 weeks of trading days for it to accumulate.

- `AlphaVantageClient.fetch_historical_options(ticker, option_date=...)` already exists
  (`providers/alpha_vantage.py:169`) and is registered (`config/source_registry.yaml:173`).
  This is wiring, not a new integration.
- **Cost:** ~360 requests for 18 tickers x 20 sessions. The free plan allows 25/day, so on
  the free plan the backfill itself takes ~15 days. A premium plan makes it minutes. The
  owner has not committed to a paid plan; Lane C must therefore make the backfill
  **resumable across days** and report its own progress.
- **The correctness trap, and it is the whole task:** a backfilled implied-volatility
  reading must be computed by *exactly* the same code path as a live one. If it is not,
  the percentile compares two different quantities and produces a confident, wrong answer.
  Lane C's acceptance criteria are built around proving this.
