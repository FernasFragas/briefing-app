# Run health — what makes a run `partial`

**Implements D9.** Owner: Lane G. Companion code: `_issue_severity`, `_assess_run_health`
and `_aggregated_issue_diagnostics` in `src/briefing_app/pipeline.py`; the table below is
pinned by `test_every_issue_recording_point_has_a_declared_severity` in
`tests/test_pipeline.py`.

---

## The defect this closes

`_final_status` has always been two lines, and the rule itself is fine:

```python
if output.failures or output.diagnostics:
    return STATUS_PARTIAL
return STATUS_SUCCEEDED
```

The problem was what reached `output.diagnostics`. Per-ticker problems accumulated in a
local `issues` list with 36 recording points, were turned into evidence rows, and stopped
there. So run `daily-2026-09-07-f1b0d2e1` — zero requests to three providers, no raw cache
written, every name stripped of price closes, nothing tradeable — reported `succeeded`
with **0 failures and 0 diagnostics**.

Lane G did not add a second status rule. It made the existing one see the whole run.

## The risk, and why the table exists

D9 records the risk the owner accepted: *if every routine condition escalates, `partial`
becomes the new constant and carries exactly as little information as `succeeded` does
today.* Both halves have to hold, and both are asserted by tests:

| Half | Test |
|---|---|
| A run that reached no provider is `partial` and names them | `test_a_run_that_reached_no_provider_reports_partial_and_names_them` |
| A healthy run — including a warm-up baseline — is still `succeeded` | `test_a_warm_up_only_run_still_reports_succeeded`, `test_a_clean_fixture_run_reports_succeeded_with_no_health_diagnostics` |

## Severity levels

| Severity | Meaning | Marks the run |
|---|---|---|
| **normal** | An expected condition of a healthy system. Recorded in the evidence ledger, never escalated. | no |
| **degraded** | Real data is missing and the output is weaker for it. | **partial** |
| **outage** | A source that should have answered was never reached. | **partial**, listed first |

---

## The dividing line, in one sentence each

**Warm-up is normal.** The IV and put/call baselines are built from this application's own
persisted snapshots. They start empty and fill one session per run, so
`iv rank baseline still building: 3 of 20 sessions stored` is true every single day for
roughly four weeks and says nothing about today. Escalating it would make `partial` the
constant on day one.

**An entitlement fact is normal.** `no_credentials`, `plan_gated` and `paywalled` are
decided by what the owner has configured and paid for. They are identical every run,
already reported by preflight, and change only when the owner changes them. They are also
the reason the healthy live run stays green: the shipped news chain leads with Finnhub and
falls through to Alpha Vantage when no Finnhub key is set, and a fallback doing its job is
health, not failure.

**A configuration statement is normal.** `<provider> is configured for <leg>, but no live
provider hook is wired` means the chain named a provider this module has no code for and
moved on to the next one. It is a property of `config.yaml`, identical every run. Whether
the leg actually came back empty is caught by the component and name counts below, not by
this line.

**An unreadable answer is degraded.** A provider answered and the payload could not be
normalized into the app's types. Real data is missing, the component is weaker, and
somebody should look — which is exactly the `degraded` definition.

**An unreachable source is an outage.** `budget_exhausted`, `throttled` and
`network_error` all mean the source was there and the run did not get to it. This is the
2026-09-07 signature and the case D9 says *must* mark the run partial.

### The three that were genuinely hard

1. **`no_credentials` (`pipeline.py:2977`, `:2315`, `:2870`).** The strongest argument for
   `outage` is that a missing key is precisely how a provider goes unreached. The argument
   that won: it is a *standing* fact, not a run event; it never clears on its own; and the
   healthy live-path run in the suite emits it for Finnhub every time while producing a
   fully scored name from the fallback. Classifying it `outage` would print an outage
   banner on a run whose output is complete. The genuine damage from a missing key —
   nothing was fetched — is caught instead by `providers_expected`, which excludes
   uncredentialled providers, and by the component and name counts.

2. **`<provider> is configured for <leg>, but no live provider hook is wired`
   (10 recording points).** Defensible either way. If a leg's chain contained *only*
   unwired providers, the leg would silently produce nothing and this line would be the
   only trace. It is `normal` anyway, because the line fires per provider per leg per
   ticker and would carpet the diagnostics of every run, while the outcome it warns about
   — an empty leg — is visible in `components_scored / components_defined`. The severity
   sits on the *outcome*, not on the chain walk that produced it.

3. **`cached FMP <endpoint> <date> ignored: …` (`pipeline.py:3559`).** This is a *prior*
   day's cached payload failing to re-read while today's own fetch was fine. Called
   `degraded`: the political-flow window is genuinely short of days, and a corrupt cache
   file is worth seeing. The cost, accepted knowingly: a corrupt file keeps the run
   `partial` until it ages out of the window. If that proves noisy in practice it is a
   candidate to demote, and it is written here so the argument is available.

---

## The table — all 36 recording points

Line numbers are `src/briefing_app/pipeline.py`. The test asserts this set matches the file
exactly, so a new `issues.append` fails the suite until it is classified here.

| Line | Issue | Severity | Why |
|---|---|---|---|
| 1885 | FMP historical price EOD normalization failed | degraded | Prices answered and were unreadable; every downstream number is worse. |
| 1907 | Twelve Data time series normalization failed | degraded | As above, on the price fallback. |
| 1936 | Alpha Vantage daily / daily-adjusted normalization failed | degraded | As above, on the last price source. |
| 1941 | unwired provider for `prices` | normal | Configuration statement; chain moves on. |
| 1973 | unwired provider for `macro calendar` | normal | Configuration statement; chain moves on. |
| 1994 | FMP economic calendar normalization failed | degraded | `S_M` loses its dated calendar. |
| 2072 | FRED release upcoming-dates normalization failed | degraded | The forward macro window is short. |
| 2129 | unwired provider for `macro readings` | normal | Configuration statement; chain moves on. |
| 2149 | FMP economic indicator normalization failed | degraded | One macro factor drops out of `S_M`. |
| 2176 | FMP treasury rates normalization failed | degraded | `treasury_10y` and `yield_curve` drop out. |
| 2227 | Alpha Vantage earnings normalization failed | degraded | The catalyst date is unconfirmed (D4 territory). |
| 2253 | FMP earnings normalization failed | degraded | As above, on the lead earnings source. |
| 2255 | unwired provider for `earnings` | normal | Configuration statement; chain moves on. |
| 2287 | Alpha Vantage news normalization failed | degraded | `S_S` loses a news batch. |
| 2303 | FMP stock news normalization failed | degraded | `S_S` loses a news batch. |
| 2315 | Finnhub company news unavailable (*status*) | **by status** | See the status table below. |
| 2318 | unwired provider for `news` | normal | Configuration statement; chain moves on. |
| 2370 | unwired provider for `political` | normal | Configuration statement; chain moves on. |
| 2400 | FMP senate/house latest normalization failed | degraded | `political_flow` loses a chamber. |
| 2426 | unwired provider for `retail` | normal | Configuration statement; chain moves on. |
| 2458 | ApeWisdom retail momentum page normalization failed | degraded | Attention feed truncated mid-read. |
| 2500 | unwired provider for `analyst` | normal | Configuration statement; chain moves on. |
| 2539 | FMP/Finnhub analyst normalization failed | degraded | `S_S` loses its analyst leg. |
| 2589 | FRED series reported no release id | degraded | The calendar join key is absent; ageing cannot be computed. |
| 2645 | FRED release dates normalization failed | degraded | As 2072, on the historical side. |
| 2716 | FRED series observations normalization failed | degraded | One macro factor drops out of `S_M`. |
| 2743 | no database configured, so no self-built baselines | degraded | Not a warm-up: the baselines can never build. |
| 2768 | *baseline still building: N of 20 sessions stored* | **normal** | The warm-up working as designed (D9, explicit). |
| 2798 | unwired provider for `short_interest` | normal | Configuration statement; chain moves on. |
| 2838 | FINRA short volume normalization failed | degraded | `short_borrow` loses its only free source. |
| 2870 | SEC EDGAR Form 4 index unavailable (*status*) | **by status** | See the status table below. |
| 2905 | SEC Form 4 document normalization failed | degraded | `S_I` loses one filing. |
| 2954 | unwired provider for `insider` | normal | Configuration statement; chain moves on. |
| 2962 | Alpha Vantage / FMP insider normalization failed | degraded | `S_I` loses a source. |
| 2977 | *any* `_optional_response` fetch unavailable (*status*) | **by status** | The shared recording point; see below. |
| 3559 | cached FMP political payload ignored | degraded | Prior-day cache unreadable; the flow window is short. |

### The three "by status" points, resolved

`_provider_error_message` renders `"<label> unavailable (<status>)"`. The status is the only
thing separating "we hold no key for this" from "it was there and we could not reach it",
so the split is made on the status and never on the wording.

| Status | Severity | Why |
|---|---|---|
| `no_credentials` | normal | The owner configured no key. Standing fact, reported by preflight. |
| `plan_gated` | normal | The endpoint needs a paid plan the owner has not bought. Standing fact. |
| `paywalled` | normal | As `plan_gated`, detected in the response body. |
| `budget_exhausted` | **outage** | The daily allowance was spent, so the source was never reached. |
| `throttled` | **outage** | The provider refused to serve this run. |
| `network_error` | **outage** | The provider was not reached at all. |
| `repeat_refusal` | degraded | The endpoint answered badly twice and was parked for the run. |
| `missing` | degraded | An empty root payload — an answer, but not a usable one. |
| `malformed` | degraded | The body could not be parsed. |
| `synthetic` | degraded | The provider returned a placeholder rather than data. |
| `placeholder` | degraded | As `synthetic`. |
| `truncated` | degraded | A partial body. |
| *anything else* | degraded | See the default below. |

**The default is `degraded`, deliberately.** An unclassified problem that someone bothered
to record is more likely to be a real gap than a routine one, and a wrong `degraded` is
visible and gets corrected while a wrong `normal` is the exact defect D9 exists to close.
No known recording point relies on it — `test_no_recording_point_relies_on_the_unclassified_default`
asserts that every row above matches an explicit rule.

---

## Beyond the issue list: what else marks a run `partial`

The issue table alone would not have caught 2026-09-07, because a run that never asks for
anything records comparatively few issues. Three outcome checks run alongside it, all of
them in `_assess_run_health`.

### 1. A provider that was never reached

`providers_expected` is the **lead** provider of each consumed chain — the first entry that
is both wired into `LiveDataSource` and has its credential configured. Three exclusions,
and all three are load-bearing:

- a provider with no hook in this module was never going to be asked;
- a provider with no configured credential was never going to answer;
- **a fallback behind a healthy lead is meant to go unused.**

Without the third, a run in which FMP answered every price request would report Twelve Data
and Alpha Vantage as unanswered, and every healthy run would carry an outage banner. The
legs read are `options`, `prices`, `news`, `earnings`, `macro`, `analyst`, `insider`,
`political`, `retail`, `short_interest`. `quotes`, `put_call` and `institutional` are
excluded because no code path consumes them.

Any expected provider absent from every ticker's answers produces one `outage:` diagnostic.

### 2. Total provider outage (G3)

Distinct from partial degradation and named separately: **every expected provider
unanswered**, with at least one ticker pull having completed. It sets
`RunHealth.total_provider_outage`, which Lane H's banner renders in its own style, and
emits:

```
outage: no provider was reached on 2026-09-07. cboe, fmp, fred, finnhub, sec_edgar,
apewisdom, finra were each expected to answer and none did, so every number in this
report was computed without fresh provider data.
```

It does **not** fail the run. D9 chose to keep the day's snapshot, because the volatility
baseline being built over 14 days cannot afford to lose sessions.

The "at least one ticker completed" guard matters: a run in which every ticker raised has
no provider answers because nothing got far enough to ask. That is already a failure, and
calling it an outage as well would put a second, wrong name on it.

### 3. A gated name that produced no score

A name that passed the gate, was pulled without raising, and still produced no `S_CTE` is
one `degraded:` diagnostic naming the names. Tickers that raised are excluded — they
already carry their own failure diagnostic, and counting them twice is noise.

---

## Aggregation

Eighteen names each missing prices is **one** diagnostic naming the eighteen, not eighteen
diagnostics. Issues are grouped by `(severity, message)` across every ticker, sorted
outage-first, and rendered as:

```
outage: FMP historical price EOD unavailable (budget_exhausted): … [all 18 names]
degraded: FMP stock news normalization failed: … [2 of 18 names: AMD, NVDA]
```

A run-wide issue that hit every name collapses to `all N names`; a subset is listed by
ticker so a reader can tell two names from eighteen. A diagnostics list nobody can read is
the same failure in a new costume.

---

## The completeness summary (G4)

`PipelineRunOutput.run_health` is a `briefing_app.dashboard.models.RunHealth` — the shape
Lane H owns and renders. It is on the run output, in `dashboard.json`, in the saved status
file at `data/runs/<date>/<run-id>.json`, and in the `briefing_run.details` column.

| Field | Meaning |
|---|---|
| `components_scored` / `components_defined` | Component slots that produced a score, over slots attempted. Components in `DECLARED_UNSCORABLE_COMPONENTS` (`S_F`, by decision Q4) are excluded from **both**: counting a permanent, deliberate `n/a` would leave every run one component short of complete forever. |
| `names_scored` / `names_gated` | Names with an `S_CTE`, over names the run attempted after the gate. |
| `providers_answered` | Providers that returned at least one response, across all tickers. |
| `providers_expected` | Chain leads, as defined above. |
| `total_provider_outage` | The G3 flag. |

`RunHealth` is `extra="forbid"`. A new field is a change to a model Lane H owns and goes
through `tasks/CROSS-LANE.md`, not into this document.

## Verifying it on a live run

```bash
PYTHONPATH=src .venv/bin/python -m briefing_app.cli run-daily --data-mode live --force
```

Then read the status file, not the console:

```bash
python3 -c "import json,sys; d=json.load(open(sys.argv[1])); \
print(d['status']); print(*d['diagnostics'], sep='\n'); print(d['run_health'])" \
  data/runs/$(date +%F)/*.json
```

`partial` with diagnostics naming what is missing is the correct outcome for the current
data situation. `succeeded` with zero diagnostics on a run whose `run_health` shows an
unanswered provider means this has stopped working.
