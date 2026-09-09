# Release Results — 2026-09-07

## Verification Summary

| Item | Status | Evidence |
|---|---|---|
| 1. Full suite green | Passed | `PYTHONPATH=src .venv/bin/python -m pytest -q` passed; `pytest --collect-only` reported 641 tests collected. |
| 2. Live run clean | **Failed — verification was invalid** (corrected 2026-09-08) | Withdrawn. The original evidence (`daily-2026-09-07-f1b0d2e1`, `status=succeeded`, `failures=0`, `diagnostics=0`) was read from a status that could not fail: per-ticker problems accumulated in a local `issues` list that never reached `output.diagnostics`, so `_final_status` returned `succeeded` for a run that made zero requests to Financial Modeling Prep, Finnhub and Alpha Vantage and wrote no raw cache. Lane G (D9) closed that; re-verify against the corrected status. **`partial` is the expected and correct result** for the current data situation, and this item should be read against items 9 and 10 rather than requiring zero diagnostics. |
| 3. Ideas ordered correctly | Passed | Published ideas are all `WATCHLIST`; within that bucket they sort by `grade_score` descending: 100.0, 100.0, 98.41, 70.18, 55.12, 50.33, 14.46, then zero-score rows by ticker. |
| 4. 20-session volatility baseline and no fixture rows | **Blocked** (see round 2) | Fixture contamination is purged: `select count(*) from daily_snapshot where run_id = 2` returned `0`. Current live store still has only 3 sessions for most report names and `0` non-null `iv_rank` rows. Run `backfill-iv` over multiple days, or with a higher Alpha Vantage plan, to finish this item. |
| 5. SPY and QQQ in market context | Passed | `trading_ideas` has no `SPY` or `QQQ`; `market_overview` contains `SPY market context` and `QQQ market context`. |
| 6. Grades recompute from dashboard JSON | Passed | `PYTHONPATH=src .venv/bin/python ops/audit_dashboard.py output/published/latest/dashboard.json` returned `ok=true`, `rows_checked=16`. |
| 7. Three unattended weekday runs | Pending | Cannot be produced inside one session. `docs/operations/LOCAL-OPS.md` and `ops/install_launchd.py` define the `launchd` setup; record three actual weekday runs after installation. |
| 8. README claims match behavior | Passed with caveat | README now describes ALIGN grading, letter caps, local `launchd`, optional n8n, unwired prose, IV backfill, and fixture snapshot refusal. Hosted docs remain as optional references. |

## Live Run

```text
run_id: daily-2026-09-07-f1b0d2e1
run_date: 2026-09-07
data_mode: live
status: succeeded
failures: 0
diagnostics: 0
scored tickers: 18
trading ideas: 16
tradeable: 0
watchlist: 18
```

The run produced:

```text
output/dashboard/2026-09-07/dashboard.html
output/dashboard/2026-09-07/dashboard.json
data/runs/2026-09-07/daily-2026-09-07-f1b0d2e1.json
```

The static publish step wrote:

```text
output/published/2026-09-07/daily-2026-09-07-f1b0d2e1/dashboard.html
output/published/2026-09-07/daily-2026-09-07-f1b0d2e1/dashboard.json
output/published/latest/dashboard.html
output/published/latest/dashboard.json
output/published/latest/manifest.json
```

`output/published/latest/manifest.json` reports the same run id and has `source_status =
succeeded`, `failures = 0`, `diagnostics = 0`.

## Letter Distribution

On the live run, all trading idea rows are `WATCHLIST`.

```text
C: 6
F: 10
```

Scores span 0.0 to 100.0 under ALIGN. All rows are Tier C on the current live data, so the
displayed-letter cap correctly prevents high-certainty presentation even when the numeric
conviction score is high.

## Backfill State

`backfill-iv --dry-run` on 2026-09-07 planned 360 pairs:

```text
18 gate-accepted US tickers x 20 sessions
34 already stored
326 remaining
25 Alpha Vantage requests remaining today
14 estimated free-plan days
```

The local database backup before purge is:

```text
data/briefing.sqlite3.backup-20260907-before-fixture-purge
```

After purge, `daily_snapshot` has no run `2` rows. Current session counts are still below
the 20-session release target, so volatility rank remains withheld.

## Operations

The shipped local scheduler is `launchd`, implemented by:

```text
ops/install_launchd.py
ops/run_daily.py
ops/status.py
ops/serve_api.py
```

The API now fails closed for mutating endpoints. With `APP_RUN_TOKEN` unset, protected
endpoints generate/read a local token file and return 401 unless the caller supplies the
matching bearer token. `/health` stays open.

A simulated ops failure was verified with temp data/output roots. `ops/status.py --json`
returned non-zero and reported:

```text
no run recorded for today (2026-09-07)
latest run status is missing
latest local job recorded an error
```

`ops/run_daily.py --help` confirms the local runner accepts `--data-mode {fixture,live}`.
For unattended runs, set `BRIEFING_DATA_MODE=live` in `.env` before loading the
LaunchAgent.

## Left Open Deliberately

- The 20-session volatility baseline cannot be completed instantly on the free Alpha
  Vantage allowance. The resumable backfill command is ready; run it until every live
  report ticker has 20 sessions.
- The three consecutive unattended weekday runs require actual weekdays after installing
  the LaunchAgent.
- The bounded prose layer remains present but unwired by design for the local single-reader
  release.


---

# Round 2 Results — 2026-09-08

Round 2 (Lanes G–J) was opened by the round-1 live run that reported `succeeded` having
reached no providers. Lanes G, H, I and J are complete. **Baseline: 671 tests passing,
zero failures** (`PYTHONPATH=src .venv/bin/python -m pytest`, exit 0, verified
2026-09-08).

## Round 2 verification summary

| Item | Status | Evidence |
|---|---|---|
| 9. Degraded run reports `partial`, healthy run does not | Passed | All 36 `issues.append` points classified `normal`/`degraded`/`outage` in `pipeline.py::_issue_severity`, tabulated in `docs/architecture/RUN-HEALTH.md`. Escalated issues reach `output.diagnostics`; no second status rule was written. A test asserts the table matches the file, so a new recording point fails the suite until classified. Both halves verified: the live-path run in the suite emits three warm-up notices plus a `no_credentials` line and stays `succeeded` with zero diagnostics and 4/4 components. |
| 10. Warm-up does not mark a run partial | Passed | `iv rank baseline still building: N of 20` is classified `normal` by design and asserted by test. |
| 11. Conviction and certainty legible as two measurements | Passed | Separate columns plus an on-page legend; `tests/test_render.py::test_dashboard_html_explains_and_renders_conviction_and_certainty_separately`. Ordering by conviction still pinned by the round-1 multi-row test. |
| 12. Declared thesis shown beside the data's reading | Passed | `posture` and `composite_score` on `TradingIdeaRow` and in `dashboard.json`; disagreement marked and asserted on exactly one of two rows by `tests/test_render.py::test_dashboard_html_marks_only_theses_that_disagree_with_the_data_reading`. Grades unchanged by the task. |
| 13. D12 closed by a written recommendation | **Research complete; decision open** | `docs/research/alternatives/historical-options-sources.md` (423 lines). Quiver answered directly and negatively. Owner has not yet chosen. |
| 14. Backfilled value reproduces a stored live value | Passed | `tests/test_backfill.py::test_backfill_reproduces_a_row_the_live_path_stored` compares two **stored** rows, not two in-memory structures. The round-1 test it replaces built both sides with the same function and could not have caught a divergence. |
| 15. A previously blocked setup becomes available | **Not met — blocked on D12** | No backfill request has been sent; `iv_rank` is NULL on all stored rows. This remains the only criterion that proves the work delivered a visible difference. |

## What round 2 changed about the shipping picture

Two findings from Lane J invalidate premises round 1 and D12 were written on:

1. **The "wait 14 days on the free tier" option does not exist.** Alpha Vantage
   `HISTORICAL_OPTIONS` is not on the free plan: it answers HTTP 200 with a sample payload
   that validates as `synthetic`. Waiting yields 25 refusals a day, indefinitely. Nothing
   synthetic can reach the store, but the requests are spent. The backfill now stops on the
   first `synthetic` answer and after three consecutive failures of any kind.
2. **The stored live rows and any Alpha Vantage backfill are different vendors.** Every
   stored `iv_atm`/`pc_ratio_*` came from **CBOE**, captured intraday
   (`config.providers.options = [cboe, alpha_vantage]`; the evidence ledger records
   `CBOE delayed options` for all 1,235 `S_O` rows). Alpha Vantage historical chains are
   the session close. An IV rank is a percentile of one series, so splicing the two
   produces exactly the invisible wrong answer D3 was written to avoid. The backfill now
   refuses to write on a vendor mismatch and stamps `chain_source`, `chain_venue`,
   `chain_as_of` and `live_options_provider` on every row.

**Consequence for the owner's decision:** buying one month of Alpha Vantage premium fills
the history from a vendor the live path does not use. Making that history comparable needs
a further choice — backfill every session from one vendor and stop mixing, or move the live
options lead to match — and that choice is not yet made.

## Definition-of-done items still open

| Item | Why |
|---|---|
| 2 / 9 live re-verification | Needs one live run against the corrected status. Not run: no network spend was authorised for Lane G, and the shared 25/day Alpha Vantage allowance is contended. Expect `partial`. |
| 4, 15 | Blocked on D12, which is open. |
| 7 (three unattended weekday runs) | Owner declined the `launchd` scheduler and runs the briefing by hand, to keep the shared request allowance under manual control. Recorded as owner-operated rather than as a gap. |

## Round 2 files

```text
docs/architecture/RUN-HEALTH.md                                (new, 282 lines)
docs/research/alternatives/historical-options-sources.md   (new, 423 lines)
docs/operations/IV-BACKFILL.md                               (extended, 257 lines)
docs/product/REPORT-LAYOUT.md                             (extended)
src/briefing_app/pipeline.py                      (severity, escalation, RunHealth)
src/briefing_app/backfill.py, cli.py              (reservation, vendor guard)
src/briefing_app/dashboard/                       (conviction/certainty, thesis, banner)
```
