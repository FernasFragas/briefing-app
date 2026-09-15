# Release Results — 2026-09-07

> Rounds 1 and 2 below are historical evidence, not current instructions. Their backfill,
> unattended-scheduler, and 20-session targets are superseded by the
> [round-3 results](#round-3-results--2026-09-09). The original live-success claim remains
> withdrawn; no new live run has yet replaced it.

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

---

# Round 3 Results — 2026-09-09

K, L, M and N reported completion in the append-only register before O started. Integration
is verified **offline**, not a completed live acceptance. Lane O sent **zero live requests**.
No owner-named run day was supplied; the required budget command returned **NO**, exit 2.
The live step stopped there. No claim or outcome was fabricated in the ledger.

## Current verification summary

Evidence identifiers below refer to the exact commands and observed outputs following the table.
Fixture and fake-provider tests establish code behavior, not current provider entitlement.

| Item | Status | Evidence |
|---|---|---|
| 1 / O1. Full suite | **Suite passed; clean-tree condition OPEN** | E1: initial exact command exited 1 with 687 passed / 2 failed; final exact command exited 0 with **692 passed**, one third-party warning. No tests removed. HEAD is `545e9e3`; K–N changes were uncommitted at handoff. O preserved the shared tree, did not reset or commit other lanes' work, and does not claim a clean-tree run. Close that condition after the owner-approved integration commit and repeat E1. |
| 2. Live status re-verification | **OPEN — authority/budget** | E3: budget `verdict=no`, exit 2. E4: latest historical run still says `succeeded`, diagnostics `[]`, and has **no `run_health` field**. It is not new evidence. Close with the one owner-dated, preclaimed, budget-approved full daily live run; record its status, diagnostics, provider answers/cache evidence and run health. An honest `partial` is expected, not a failed acceptance by itself. |
| 4. Ten-session publication / provisional below twenty; no fixture rows | **Policy and isolation passed offline; live publication OPEN under 21** | E2 tests all three 9/10/20 boundaries and fixture persistence refusal. E4: all **59** snapshots join to `data_mode=live`; none join to fixture or unknown mode. Existing live ranks remain null. This replaces the original all-names-at-20 target, not the isolation requirement. |
| 7. Three manually launched weekday runs | **OPEN — launch provenance** | Scope explicitly changed to owner-operated, not an uninstalled-scheduler defect. E4 finds completed live records on September 2, 3, 4 and 7, including three successive weekdays; the JSON does not record who/how each was launched. It proves runs, not manual launches. Close with owner-confirmed IDs/launch records for three weekday runs; do not install `launchd`. |
| 8. Current README / handoff | **Updated** | Describes 10/20 provisional defaults, two idea sections, retained-but-unscheduled backfill, and preclaimed budget-governed agent runs. Historical entitlement measurements are explicitly not fresh probes. |
| 9. Total outage is partial; healthy run succeeds | **Both halves passed offline; live acceptance OPEN** | E2 asserts both statuses, outage provider names and the rendered outage banner. E5 prints healthy=`succeeded`, warmup=`succeeded`, outage=`partial` naming CBOE, FMP, Finnhub, Alpha Vantage and FINRA. Both fake runs scoring 4/4 components are synthetic behavior tests, not a claim that an actual outage had data. The single authorized live run is still missing (E3). |
| 10. Warm-up alone does not degrade status | **Passed offline** | E2/E5: all three `3 of 10` warm-up messages leave diagnostics empty and status `succeeded`. Verify the same classification in the eventual live diagnostics. |
| 13 / D12. Funding choice | **Closed by D13** | Decision `0013-volatility-threshold-ten-sessions.md`; the paid-month recommendation was declined, and no bulk backfill is scheduled. This corrects round 2's open decision, not the incomplete live criterion. |
| 15. Previously rank-blocked setup | **Superseded by 21, still OPEN** | No paid backfill is awaited. Live cadence and usable observations now gate the evidence. |
| 16. Three percentile boundaries | **Passed offline** | E2: parametrized 9/10/20 test asserts actual IV rank and both put/call percentile values are null at nine, populated at ten and twenty, with per-leg provisional flags. Three additional cases reject metadata for a missing current percentile even when history is sufficient. |
| 17. Provisional in storage, JSON and page | **Passed offline** | E2 end-to-end fake-provider run starts with ten prior observations, asserts a non-null stored `iv_rank`, all three metadata entries in `daily_snapshot.raw`, the exact `trading_ideas` JSON row, and all three rendered `Provisional — 10 stored sessions` markers. Renderer also pins settled display. Actual live first publication is item 21. |
| 18. Two sections, every idea once, supported order | **Passed offline** | E2 pins partition uniqueness, a multi-row conviction sort, thesis/data labels and disagreement. E5 fresh full-universe fixture has **12 ideas = 6 supported + 6 contradicted**, zero grade-audit failures. E6 audits the existing 16-row live artifact; locked grading file has no diff. |
| 19. Measured put/call gap; IV procedure unexecuted | **OPEN — independent numeric replay missing** | E7 passes 20 backfill/vendor tests, including invocation of the shipping normalizer and options math. M's document records AAPL volume gaps **8.93%, 0%, 55.38%** and OI gaps **3.92%, 0%, 146.34%**, URLs and two hashes, but its command does not retain payloads and none were supplied for O to replay. Reading that table is not independent measurement. Close the evidence gap by supplying the original two payloads and replaying `--payload` for each stored date; any new probes need separate authorization. The IV half is explicitly **UNEXECUTED**, paid-key dependent, with the all-54-pairs decision rule fixed in the document. No splice approved. |
| 20. Prior claims and daily reservation | **Guard passed offline; whole-round audit OPEN** | E3: no active claims, no September 9 Alpha Vantage counter, full reserve 25, spendable 0. E7 asserts both ledger and backfill refuse the completed-run/missing-counter trap. Missing counters do not prove historical zero spend or an intact reservation. M's permitted keyless MarketData probes are explicitly outside the numeric ledger in D16; the broad “every provider request claimed” wording cannot be certified from an empty ledger. O made no live requests. Close with factual tracked-provider claim/outcome and counter reconciliation, plus the authorized daily run. |
| 21. First live provisional rank unlocks a setup | **OPEN — cadence and usable data; conditional September 18** | E4: **3 snapshot dates**, **0 non-null ranks**, **0 completed weekday live runs since K landed September 9**. No September 8 run exists. Most current names have three IV inputs, but JPM/LMT have one and FDX has zero. Seven further usable runs reach ten for the three-input names; the following run can publish. Close only with a non-null live rank **and** a named newly admitted setup, compared with its previous rank-related rejection. |

## E1 — full-suite and worktree evidence

```bash
PYTHONPATH=src .venv/bin/python -m pytest
```

Before O edits: `2 failed, 687 passed, 1 warning in 143.29s`, exit **1**. Failures were
`test_fred_client_requires_key_before_network` and
`test_finnhub_client_requires_key_before_network`. Both received actual local credentials
because CLI unit tests loaded `.env` into the shared pytest process. O stubbed
`configure_environment` in both affected CLI tests, rather than masking the failure with
an altered suite environment.

After code integration: `692 passed, 1 warning in 101.71s`, exit **0**. The additional
three cases cover absent current values on each percentile leg. The warning is the existing
FastAPI/Starlette `httpx` deprecation. Baseline entering round 3: 671 tests; O entered with
689 collected; O exits with 692. No test deletion accounts for either increase.
The final repeat of the exact command also returned `692 passed, 1 warning in 101.21s`,
exit **0**. `git diff --check` returned no output, exit 0; the local Markdown-link check
over the six documentation files O changed returned `broken local links: []`, exit 0.

```bash
git log -1 --oneline
git status --short
```

Output: `545e9e3 Update project development documentation`; modified/untracked K–N source,
tests and docs plus the existing untracked `tasks/AGENT-PROMPTS.md`. The baseline commit
exists, but **the integration tree is not clean**. That O1 premise cannot be reported as met.

## E2 — assertion-backed offline acceptance

```bash
PYTHONPATH=src .venv/bin/python -m pytest -v \
  tests/test_pipeline.py::test_self_built_percentile_boundaries_cover_all_three_gated_legs \
  tests/test_pipeline.py::test_baseline_metadata_requires_a_current_percentile \
  tests/test_pipeline.py::test_fixture_daily_run_reports_snapshot_persistence_refusal \
  tests/test_orchestration.py::test_provisional_baselines_persist_to_live_snapshot_and_dashboard_json \
  tests/test_orchestration.py::test_a_warm_up_only_run_still_reports_succeeded \
  tests/test_orchestration.py::test_a_run_that_reached_no_provider_reports_partial_and_names_them \
  tests/test_render.py::test_dashboard_html_renders_total_provider_outage_banner \
  tests/test_render.py::test_dashboard_html_renders_provisional_baseline_and_crowding_magnitude \
  tests/test_render.py::test_dashboard_html_splits_theses_without_dropping_rows_and_ranks_support \
  tests/test_dashboard.py::test_dashboard_payload_partitions_every_idea_once_and_serializes_the_split
```

Output: `14 passed`, exit **0**. Broader integration command:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_pipeline.py tests/test_orchestration.py tests/test_dashboard.py tests/test_render.py tests/test_backfill.py tests/test_vendor_gap.py
```

Output: `128 passed in 16.00s`, exit **0**.

## E3 — budget and status (read-only, no provider calls)

```bash
PYTHONPATH=src .venv/bin/python ops/live_budget.py --json
PYTHONPATH=src .venv/bin/python ops/status.py --json
```

Budget output, September 9: `verdict: no`, exit **2**; `counter.recorded: false`, nominal
`remaining: 25`, `daily_run.completed: false`, `reserved_requests: 25`,
`reservation_intact: false`, `claims: []`, `spendable_after_reservation: 0`. Reasons:
today's daily run has not completed; no pre-spend claim was named. **NO was obeyed**.

Status output: `ok: false`, exit **2**, attention:
`No local daily run record found at .../data/ops/last-run.json`; the same budget position
is exposed. This ops-wrapper file's absence is not evidence that historical CLI runs
never happened; E4 reads those run files directly.

Resume only after the owner names a day and authorizes proceeding to a properly matched
`daily-run` claim. Recheck that claim immediately before spending. Do not use a backdated
`--date`, invent an outcome, or run merely because nominal remaining capacity is 25.

## E4 — stored observations and actual live runs

Read-only query and JSON audit (the `briefing_run` join key is **id**, not run_id):

```bash
.venv/bin/python - <<'PY'
import json, sqlite3
from pathlib import Path
from datetime import date
c = sqlite3.connect('file:data/briefing.sqlite3?mode=ro', uri=True)
print('sessions:', c.execute('select count(distinct snap_date) from daily_snapshot').fetchone()[0])
print('iv_rank set:', c.execute('select count(*) from daily_snapshot where iv_rank is not null').fetchone()[0])
print('snapshot dates:', c.execute('select snap_date, count(*) from daily_snapshot group by snap_date').fetchall())
print('snapshot modes:', c.execute("select json_extract(r.details, '$.data_mode'), count(*) from daily_snapshot s left join briefing_run r on r.id = s.run_id group by 1").fetchall())
print('per ticker (iv, pc_vol, pc_oi):', c.execute('select ticker, count(iv_atm), count(pc_ratio_vol), count(pc_ratio_oi) from daily_snapshot group by ticker order by ticker').fetchall())
records = [json.loads(p.read_text()) for p in sorted(Path('data/runs').glob('*/*.json'))]
live = [r for r in records if r.get('data_mode') == 'live' and r.get('run_type') == 'daily' and r.get('finished_at')]
weekday = [r for r in live if date.fromisoformat(r['run_date']).weekday() < 5]
print('completed live weekday dates:', sorted({r['run_date'] for r in weekday}))
print('weekday live runs since K landed:', sum(r['run_date'] >= '2026-09-09' for r in weekday))
print('Alpha Vantage counter days:', sorted(p.stem for p in Path('data/provider_budget/alpha_vantage').glob('*.json')))
latest = max(live, key=lambda r: r['finished_at'])
print('latest:', latest['run_id'], latest['status'], latest['diagnostics'], latest.get('run_health', 'ABSENT'))
PY
```

Observed: `sessions: 3`; `iv_rank set: 0`; snapshot dates/counts:
`[('2026-09-03', 23), ('2026-09-06', 18), ('2026-09-07', 18)]`;
modes: `[('live', 59)]`. Completed live weekday dates:
`['2026-09-02', '2026-09-03', '2026-09-04', '2026-09-07']`; since K: **0**.
Alpha Vantage counter dates: August 30, September 2, 3, 4, 6. Latest run:
`daily-2026-09-07-f1b0d2e1 succeeded [] ABSENT`.

Per-ticker `(IV, volume, OI)` counts: AAPL, AMAT, AMZN, COST, CRWV, GM, GOOGL, INTC,
META, MSFT, MU, ORCL, QQQ, SPY and XOM each `(3,3,3)`; JPM/LMT `(1,3,3)`;
FDX `(0,3,3)`; AMD/AVGO/PLTR/SMCI `(1,1,1)`; DE `(0,1,1)`.
The global session count is not every ticker's usable sample count.

### Item 21 cadence projection — dated September 9

If each weekday September **9, 10, 11, 14, 15, 16, 17** adds one usable input to a
three-input ticker, it reaches ten stored observations on September **17**. Since
`option_metric_history(before_date=run_date)` excludes today, September **18** is the
earliest projected first ranked output on that cadence. This is conditional, not a
promised close: the output must actually admit a formerly rank-rejected setup, missing
inputs can delay it, and no September 9 run is yet authorized here. Each missed weekday
shifts the projection; the missing September 8 run already advanced nothing.

Keep recording both **stored observations** and **completed weekday live runs since K**.
The present blocker is operational run cadence/authorization, not waiting for threshold
code. A run without a usable IV input can advance date counts without advancing IV history.
September 6 and 7 are stored run dates referencing the September 4 trading session per M;
do not count them as independent exchange sessions. Changing snapshot dating is outside
this integration and the storage file remains locked.

## E5 — direct offline status and fresh dashboard check

```bash
PYTHONPATH=src .venv/bin/python - <<'PY'
import json, tempfile
from pathlib import Path
from datetime import date
from briefing_app.config import load_config
from briefing_app.pipeline import FixtureDataSource, run_daily
from tests.test_orchestration import RunHealthDataSource, _run_health_run
from ops.audit_dashboard import audit_payload
with tempfile.TemporaryDirectory(prefix='briefing-o-offline-') as temporary:
    root = Path(temporary)
    for name, source in (
        ('healthy', RunHealthDataSource()),
        ('warmup', RunHealthDataSource(issues=tuple(f'{leg} baseline below publish floor: 3 of 10 sessions stored' for leg in ('iv_rank', 'put/call volume percentile', 'put/call open-interest percentile')))),
        ('outage', RunHealthDataSource(answered=(), expected=('cboe','fmp','finnhub','alpha_vantage','finra'))),
    ):
        out = _run_health_run(root/name, source, ['NVDA'])
        print(name, json.dumps({'status':out.status,'diagnostics':out.diagnostics,'run_health':out.run_health.model_dump()}))
    out = run_daily(load_config('config/config.example.yaml'),run_date=date(2026,9,9),data_source=FixtureDataSource(),data_dir=root/'data',output_dir=root/'output',persist=False)
    payload = out.dashboard.model_dump(mode='json')
    counts={key:len(payload[key]) for key in ('trading_ideas','supported_theses','contradicted_theses')}
    print('fresh fixture:',json.dumps({'status':out.status,'data_mode':out.data_mode,'counts':counts,'grade_audit_failures':audit_payload(payload)}))
PY
```

Exit **0**. Healthy and warmup: `status=succeeded`, diagnostics `[]`, components `4/4`,
names `1/1`, expected/answered `['cboe','fmp']`, total outage false. Outage:
`status=partial`, answered `[]`, total outage true, diagnostic explicitly naming all five
expected providers. Fresh fixture: `status=succeeded`, `data_mode=fixture`, idea counts
`12/6/6`, `grade_audit_failures=[]`. All data sources are synthetic; persistence is off
and temporary artifacts do not replace the published live report.

## E6 — unchanged grades, existing live artifact

```bash
PYTHONPATH=src .venv/bin/python ops/audit_dashboard.py output/published/latest/dashboard.json
git diff --numstat -- src/briefing_app/dashboard/grading.py src/briefing_app/storage.py src/briefing_app/strategy/engine.py tests/conftest.py
```

Output: `{"ok": true, "rows_checked": 16}`, exit **0**. Locked-file diff: **empty**.
The old live artifact predates the report split; E5, not this old artifact, verifies fresh
split output. The metadata-only integration changes do not touch grading inputs.

## E7 — isolated ops and vendor/backfill checks

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_ops_scripts.py tests/test_provider_clients.py
PYTHONPATH=src .venv/bin/python -m pytest tests/test_backfill.py tests/test_vendor_gap.py
```

Output: **53 passed** (CLI environment isolation) and **20 passed** (shared normalizer/math,
vendor refusal, live-row reproduction, reserve policy), both exit **0**. The tests do not
reproduce M's measured vendor-gap percentages; original recorded payloads are missing from
the handoff. Paid IV measurement remains unexecuted by design, not quietly marked passed.
