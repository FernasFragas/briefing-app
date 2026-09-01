# Options Briefing Application - Parallel Implementation Tasks

Source plan: `options-briefing-system-plan.md`

Additional strategy/source inputs:

- `trader analysis v2.md`
- `trading ideas.md`

## Objective

Build a self-hosted options-first, multi-factor briefing application. Python computes all ranges, probabilities, component scores, tiers, setup rules, and calibration. The LLM only turns computed and sourced fields into bounded prose. n8n schedules and delivers the run.

## Target Shape

- `app`: Python FastAPI + CLI service for ingestion, normalization, scoring, rendering, and calibration jobs.
- `postgres`: snapshots, evidence ledger, candidate gates, component scores, call log, run status.
- `n8n`: cron, retries, manual trigger, delivery, failure notification.
- `data/`: date-stamped raw provider payloads and manual captures.
- `output/`: HTML/JSON dashboards, preflight reports, calibration reports.
- `config/`: universe, geography, expression classes, source priority, thresholds, manual catalysts, delivery.

Keep Python outside the n8n container. n8n calls `app:8000` over HTTP.

## Shared Contracts To Create First

These contracts unblock parallel work.

| Contract | Purpose | Owner Task |
|---|---|---|
| `config/config.yaml` schema | Universe, expression classes, provider priority, thresholds, catalysts, delivery | T0 |
| Source registry | Source hierarchy, region support, endpoint names, staleness bounds, entitlement status | T1 |
| Raw cache path convention | `data/raw/{provider}/{endpoint}/{YYYY-MM-DD}/{symbol-or-market}.json` | T1 |
| Manual capture schemas | EU options and other paywalled/manual data imports | T1 |
| Evidence ledger schema | Value, component, source, venue, as-of, validation status, note | T3 |
| Candidate model | Ticker, geography, sector, thesis, catalyst, expression class, instrument fit | T2 |
| Normalized market models | Quote, option chain, short/borrow, news, catalyst, filing, ownership | T4 |
| Metrics JSON v1 | Input contract for math, renderer, and LLM prompts | T5/T7 |
| Scoring JSON v1 | `S_M`, `S_O`, `S_S`, `S_I`, `S_F`, weights used, `S_CTE`, tier | T7 |
| Pipeline API | `GET /health`, `POST /run/daily`, `POST /run/weekly`, `POST /score/open-calls` | T0/T10 |

## Dependency Map

1. T0 lands the runnable scaffold.
2. T1 defines source registry/preflight. T2, T3, T5, T6, T7, T8, and T9 can build against fixtures in parallel.
3. T4 depends on T1 source contracts and sample payloads, but can begin with fixtures.
4. T5 and T6 produce component metrics independently.
5. T7 depends on component score contracts from T5/T6 and candidate contract from T2.
6. T8 depends on T7 class/tier output and range metrics from T5.
7. T9 depends on T7/T8 JSON contracts, but can build with fake data.
8. T10 integrates everything into one run.
9. T11 and T12 complete scheduling, delivery, and calibration.
10. T13 adds optional Quiver congressional trading signals after T4/T6 source contracts exist.
11. T14 adds Ollama Cloud as the preferred LLM provider for dashboard prose.

## Parallel Workstreams

### T0 - Foundation And Containers

Can start: immediately

Deliverables:

- Python package skeleton under `src/briefing_app`.
- `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`.
- `config/config.example.yaml`.
- App health endpoint and placeholder job endpoints.
- Local commands documented.

Acceptance:

- `docker compose config` validates.
- `docker compose up --build app postgres` starts both services.
- `GET /health` returns service status.
- Missing market-data and LLM keys do not crash boot.

### T1 - Source Registry, Preflight, And Raw Cache

Can run in parallel with: T2, T3, T5, T6, T7, T8, T9

Deliverables:

- Source registry for US and EU/non-US coverage.
- Entitlement probes for configured sources.
- Raw cache writer and cache replay mode.
- Provider error taxonomy: stale, missing, throttled, paywalled, malformed, synthetic, placeholder, truncated.
- Hard rejection for Alpha Vantage sample/premium trap fields: `message`, `Information`, `Note`, sentinel symbols such as `XXYYZZ`, impossible dates, suspicious uniform legs.
- Validation that HTTP 200 responses actually contain required fields.
- Manual capture schema for EU per-strike options:

```csv
venue,as_of,expiry,strike,type,settlement,open_interest,volume
EUREX,2026-08-13,2026-09-18,1800,C,42.10,1240,85
```

Acceptance:

- Preflight report lists each source, endpoint, status, entitlement, and notes.
- CBOE delayed chain probe writes a valid raw file for one US ticker.
- Synthetic/sample payload fixture is rejected.
- Cache replay works without network.

### T2 - Universe Construction And Catalyst Gate

Can run in parallel with: T1, T3, T5, T6, T7, T8, T9

Deliverables:

- Fixed universe loader for 8-12 watched tickers.
- Idea-screening candidate loader for 15-30 candidates from sector maps/screens/manual watchlists.
- Candidate fields: ticker, venue, geography, sector, direction, thesis, intended expression class, broker/platform, permitted instruments.
- Catalyst gate requiring at least one dated catalyst in horizon, marked Confirmed or Estimated.
- Rejected-at-gate table with reasons.

Acceptance:

- No-catalyst candidates are demoted before scoring.
- Estimated catalyst cannot authorize leveraged expressions.
- Rejected names are persisted and rendered so they are not rediscovered each cycle.

### T3 - Storage And Migrations

Can run in parallel with: T1, T2, T5, T6, T7, T8, T9

Deliverables:

- Migrations for:
  - `daily_snapshot`
  - `briefing_run`
  - `evidence_ledger`
  - `candidate_gate`
  - `component_score`
  - `setup_signal`
  - `call_log`
  - `source_preflight`
- Repository layer for idempotent writes.
- History queries for IV rank, P/C baselines, sentiment baselines, realized vol, unresolved calls, and prior scorecards.

Acceptance:

- Fresh Postgres initializes schema.
- Upserts are idempotent by ticker/date/run.
- Evidence rows can reconstruct every number shown in a briefing.
- Seed fixtures return deterministic history queries.

### T4 - Provider Clients And Normalization

Can run in parallel with: T3, T5, T6, T7, T8, T9 once T1 contracts exist

Deliverables:

- CBOE delayed options-chain client as primary US options source.
- Alpha Vantage client for quote, daily adjusted history, P/C, news sentiment, earnings, macro, insider/institutional endpoints where entitled.
- FMP client for economics, news, analyst/tipranks, calendar, insider, 13F, statements where entitled.
- FINRA short-sale volume importer.
- SEC EDGAR Form 4/13F ingestion path or adapter.
- EU adapters/capture loaders for Eurex manual/browser chain data, Bundesanzeiger/FCA short disclosures, MAR Article 19, major holdings.
- Normalized models for quotes, options, price history, macro events, catalysts, news, sentiment, filings, short/borrow, ownership.

Acceptance:

- Provider payload fixtures normalize to the same typed models.
- Illiquid or stale option rows are filtered with diagnostics.
- Truncated calendars and paywalled endpoints are marked partial/unavailable, not interpreted as zero.

### T5 - Options Math And Structure Engine (`S_O`)

Can run in parallel with: T1, T2, T3, T4, T6, T7, T8, T9 using fixtures

Deliverables:

- ATM strike selection and mid-price calculation.
- Expected move from ATM straddle and ATM IV for weekly/monthly expiries.
- 1-sigma and 2-sigma price ranges.
- 20-day and 60-day realized volatility.
- Measured sigma range builder with event-day widening.
- IV rank, variance risk premium, 25-delta risk reversal.
- OI cluster detection by strike and expiry.
- Put/call volume and OI ratios with percentile versus own history.
- Gamma-by-strike map with assumption explicitly labeled.
- Implied distribution via smoothed IV smile and discrete second derivative.
- Short/borrow sub-score where verified data exists.
- `S_O` standardization to -1.0 to +1.0.

Acceptance:

- Unit tests verify DTE and annualization conventions.
- Known fixture produces stable expected move and range values.
- Method A/B divergence is surfaced as a diagnostic.
- Distribution normalizes near 1 and rejects unrepaired negative density.
- `S_O` is `n/a` when no verified per-strike chain exists for required classes.

### T6 - Macro, Sentiment, Insider, And Institutional Components

Can run in parallel with: T1, T2, T3, T4, T5, T7, T8, T9 using fixtures

Deliverables:

- `S_M` macro component from scheduled releases, rates, commodities, sector policy, and regulatory/geopolitical context.
- 30-day catalyst calendar with confirmed/estimated status.
- `S_S` sentiment component:
  - Institutional/analyst weight 45%.
  - Executive/transcript tone weight 35%.
  - Retail/social momentum weight 20%.
- News deduplication, 24-hour score, 7-day baseline, delta, article count, top headlines.
- `S_I` insider velocity:
  - US Form 4 open-market buys/sells over 90 days.
  - Exclude 10b5-1, option exercise, and tax-withholding activity.
  - EU MAR Article 19/PDMR substitute.
- `S_F` institutional flow:
  - US 13F active/passive/sovereign cohort deltas.
  - EU major-holdings notification substitute.

Acceptance:

- Each component returns score, sub-scores, source rows, as-of dates, and `n/a` reasons.
- Sentiment weighted score is computed exactly.
- Insider parser excludes non-open-market noise.
- EU substitutes use EU notes and never silently use US assumptions.

### T7 - Composite Score, Missing-Component Reweighting, And Confidence Tier

Can run in parallel with: T8/T9 after fixture contracts exist; final integration after T5/T6

Deliverables:

- US `S_CTE` formula:

```text
S_CTE = (0.30 * S_M) + (0.25 * S_O) + (0.20 * S_S) + (0.15 * S_I) + (0.10 * S_F)
```

- EU formula:

```text
S_CTE_EU = (0.35 * S_M) + (0.30 * S_O) + (0.20 * S_S) + (0.10 * S_I) + (0.05 * S_F)
```

- Missing-component drop and re-normalization.
- Disclosure of original weights, missing components, and weights used.
- Expression classes:
  - `V`: vol/options structure.
  - `E`: event directional.
  - `P`: positional fundamental.
  - `S`: short/borrow-dependent.
- Required-component tiering:
  - Tier A: required set verified.
  - Tier B: one required component partial/aggregator/stale.
  - Tier C: any required component unavailable/unverifiable.
- Universal Tier C floors: missing measured sigma, missing catalyst, missing invalidation, missing borrow for `S`.

Acceptance:

- Components can be `n/a` without biasing the score toward neutral.
- A Tier C name never appears in the Tactical Execution Dashboard.
- Class is declared before data pull and stored in the evidence ledger.
- Score interpretation maps to bullish, neutral, bearish, or watchlist posture.

### T8 - Strategy And Execution Rule Engine

Can run in parallel with: T1, T2, T3, T5, T6, T7, T9 using fixture scores

Deliverables:

- Rule-based setup engine for:
  - Short premium / iron condor.
  - Long premium / straddle or calendar.
  - Skew structures.
  - Event directional long/put/vertical.
  - Positional long.
  - Borrow-dependent short.
  - Watchlist/no-trade.
- Instrument-fit checks using configured broker/platform permitted instruments.
- Invalidation-level generation from measured ranges, option walls, or fundamental/catalyst failure conditions.
- Scenario probability table from implied distribution and measured-sigma branch logic.
- Factor certificate/knock-out leverage guard:
  - Daily-reset drag simulation.
  - No leveraged expression on estimated catalyst.
  - Reject when routine daily move approaches `1 / leverage`.

Acceptance:

- Every emitted setup has horizon, dated catalyst, invalidation, class, tier, evidence, and instrument.
- Short setup cannot emit without borrow/short-interest evidence.
- Leveraged setup cannot emit without catalyst, stop, range, and drag check.
- Rule thresholds are unit-tested at boundaries.

### T9 - Briefing Renderer, LLM Guardrails, And Output Schema

Can run in parallel with: T1, T2, T3, T5, T6, T7, T8 using fake dashboard JSON

Deliverables:

- Dashboard JSON schema containing:
  - Prior scorecard.
  - Market overview.
  - Master Alpha Selection Matrix.
  - Rejected-at-gate list.
  - Evidence Ledger.
  - Tactical Execution Dashboard.
  - Conditionality Table.
  - Per-ticker sections.
- Strict prompt templates for market overview and per-ticker prose.
- LLM wrapper with temperature 0 and provider switch for OpenAI/Claude.
- Numeric guard that rejects unauthorized numbers in LLM output.
- Jinja2 HTML renderer.
- Plain JSON audit artifact.

Acceptance:

- Null/`n/a` fields render as unavailable.
- LLM receives computed values and source labels only.
- Invented-number fixture fails the guard.
- HTML can be read without external dependencies.

### T10 - End-To-End Pipeline Orchestration

Can start after: T1/T2/T3/T4/T5/T6/T7/T8/T9 initial slices

Deliverables:

- `run_daily` and `run_weekly` orchestration commands.
- Market-day check.
- Preflight -> candidate load -> catalyst gate -> data pull -> normalize -> compute -> score -> tier -> setup rules -> render -> persist.
- Partial-failure handling by ticker/stage.
- Run status persisted with run id.

Acceptance:

- One command generates a complete dashboard for a 1-2 ticker fixture universe.
- Every displayed number traces to raw cache and evidence ledger.
- Failed ticker appears in diagnostics without hiding the run status.
- Prior calibration appears before new recommendations when available.

### T11 - n8n Workflow And Delivery

Can start after: T0; full integration after T10

Deliverables:

- Weekday 06:30 Europe/Lisbon cron workflow.
- Optional weekly dashboard cron.
- Market-day guard.
- HTTP request to `http://app:8000/run/daily`.
- Bearer token from n8n credential/env.
- Delivery adapter: email, Discord, or static HTML publishing.
- Error branch with run id, stage, ticker, and reason.

Acceptance:

- Manual n8n execution triggers the app endpoint.
- Failed app response follows error branch.
- Successful run delivers or publishes the generated HTML/JSON.

### T12 - Scoring, Backtesting, And Observability

Can run throughout; final integration after T10/T11

Deliverables:

- `call_log` writes for generated ranges, scenarios, and setup signals.
- Open-call resolver job.
- Calibration report:
  - 1-sigma containment versus approximately 68%.
  - 2-sigma containment versus approximately 95%.
  - Midpoint bias.
  - Setup hit rate and outcome by expression class.
  - Catalyst-branch outcome.
- Structured logs with run id, ticker, phase, provider, component, and validation status.
- Queries or lightweight dashboard for missed runs, failed sources, failed tickers, and calibration drift.

Acceptance:

- Open calls resolve idempotently.
- New dashboard can include the prior scorecard.
- Calibration query answers whether ranges are too wide, too tight, or biased.
- Failures are visible without reading container logs manually.

### T13 - Quiver Congressional Trading Signal

Can start after: T1/T4/T6; final integration after T7

Goal:

- Use Quiver Quantitative congressional trading data, starting with Nancy Pelosi:
  `https://www.quiverquant.com/congresstrading/politician/Nancy%20Pelosi-P000197`

Important source decision:

- Prefer the official Quiver API over scraping the politician page.
- The page is useful for human verification, but the API is the stable ingestion path.
- Quiver API example pattern:
  `GET https://api.quiverquant.com/beta/historical/congresstrading/{ticker}`
  with `Authorization: Bearer <QUIVER_API_KEY>`.

Deliverables:

- Add `QUIVER_API_KEY` to `.env.example`, settings, config docs, and n8n/cloud runbooks.
- Add Quiver to `config/source_registry.yaml`.
- Provider client:
  - Fetch congressional trades by ticker.
  - Optionally filter representative/politician to `Nancy Pelosi` / `P000197`.
  - Cache raw payloads before parsing:
    `data/raw/quiver/congress_trading/{YYYY-MM-DD}/{ticker}.json`
- Normalized model for congressional trades:
  - representative
  - politician id when present
  - ticker
  - transaction type: purchase/sale/exchange/unknown
  - transaction date
  - report/file date
  - amount/range
  - owner/house/party when present
  - source URL/API endpoint
- Scoring integration:
  - Add a capped `political_flow` sub-score inside `S_S`.
  - Purchase = bullish, sale = bearish, unknown/exchange = `n/a`.
  - Weight by recency, disclosed amount range, and disclosure lag.
  - Cap impact so congressional trades cannot dominate `S_S`.
  - Treat Quiver as aggregator source quality unless backed by original congressional disclosure.
- Evidence ledger rows for every used trade:
  - ticker
  - politician
  - transaction
  - transaction date
  - report date
  - amount range
  - source
- Dashboard/report output:
  - Show recent congressional buys/sells per ticker.
  - Mark delayed or stale disclosures clearly.
  - Do not use the signal as a standalone recommendation.

Acceptance:

- Missing Quiver key marks this source `no_credentials`, not failure.
- Cached Quiver payload replay works without network.
- Pelosi trade fixture produces a positive `political_flow` score for purchases and negative score for sales.
- The final `S_S` changes only through the capped sub-score.
- Evidence ledger links every score impact to the raw Quiver response.
- If Quiver returns paywalled/throttled/malformed data, the sub-score is `n/a` and remaining `S_S` legs reweight normally.

### T14 - Ollama Cloud LLM Provider

Can start after: T9

Goal:

- Use Ollama Cloud for dashboard prose instead of OpenAI or Anthropic.
- Keep all computed numbers, scores, options math, setup rules, and guardrails in Python.
- Ollama only rewrites bounded prose from already-computed JSON.
- n8n still triggers the FastAPI app; n8n does not call Ollama directly.

Source/API decision:

- Preferred production/cloud path:
  `POST https://ollama.com/api/chat`
  with `Authorization: Bearer <OLLAMA_API_KEY>`.
- Optional local relay path:
  `POST http://host.docker.internal:11434/api/chat`
  with a signed-in local Ollama daemon and a `*-cloud` model.
- Send `stream: false` so the current wrapper can parse one JSON response.
- Use deterministic options:
  `temperature: 0`
  and map `max_tokens` to Ollama `num_predict`.
- Do not expose a local Ollama daemon publicly.

Deliverables:

- Add environment variables:
  - `LLM_PROVIDER=ollama`
  - `OLLAMA_BASE_URL=https://ollama.com`
  - `OLLAMA_API_KEY=<ollama-cloud-api-key>`
  - `OLLAMA_MODEL=gpt-oss:120b` or another Ollama Cloud model available to the account.
  - Optional local relay model: `gpt-oss:120b-cloud`.
- Document that no local `ollama` Docker service is required for the direct cloud API path.
- Update `src/briefing_app/dashboard/llm.py`:
  - Add `LLMProvider.OLLAMA`.
  - Add `ollama_base_url` or env-based configuration.
  - Add `_complete_ollama()`.
  - Request `POST {OLLAMA_BASE_URL}/api/chat`.
  - Include `Authorization: Bearer $OLLAMA_API_KEY` when `OLLAMA_BASE_URL` is `https://ollama.com`.
  - Payload includes `model`, `messages`, `stream: false`, `options.temperature: 0`, `options.num_predict`.
  - Parse `response["message"]["content"]`.
  - Keep `assert_authorized_numbers()` after generation.
- Update config/docs:
  - `.env.example`
  - `docker-compose.yml`
  - local n8n runbook
  - n8n Cloud runbook with caveat that n8n Cloud cannot call a laptop-local Ollama.
- Add tests:
  - Provider enum accepts `ollama`.
  - Fake Ollama response returns text.
  - Numeric guard still rejects invented numbers.
  - Ollama Cloud request sends bearer auth.
  - Ollama request uses `stream: false` and `temperature: 0`.
  - Missing/unreachable Ollama returns a clear provider error.
  - Existing OpenAI/Claude tests still pass.

Acceptance:

- Setting `LLM_PROVIDER=ollama` uses Ollama without requiring `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`.
- Direct cloud config works with:
  `OLLAMA_BASE_URL=https://ollama.com`.
- A fixture prose request succeeds against a fake Ollama client.
- Unauthorized numeric output from Ollama is rejected exactly like OpenAI/Claude output.
- Host-installed relay path is documented:
  `app -> http://host.docker.internal:11434/api/chat`.
- n8n Cloud docs clearly state the hosted FastAPI app calls Ollama Cloud; n8n Cloud only calls the app.

## Suggested Parallel Execution

### Wave 0 - Day 0

- T0: Docker, app skeleton, config example, API stubs.
- T1: source registry and raw cache contract.
- T3: migration draft aligned to evidence/scoring requirements.

### Wave 1 - Days 1-3

- T1: entitlement probes and synthetic-data traps.
- T2: candidate loader and catalyst gate from fixtures.
- T4: provider clients and normalizers from saved payloads.
- T5: options math from hand-built chain fixtures.
- T6: macro/sentiment/insider/institutional components from fixtures.
- T7: scoring/tiering against fixture component JSON.
- T8: setup rules against fixture scores.
- T9: renderer and LLM numeric guard against fake dashboard JSON.

### Wave 2 - Days 4-7

- T4/T5/T6: connect real US data path, starting with CBOE options and price history.
- T7/T8: integrate real component scores into setup rules.
- T10: connect first end-to-end run for 1-2 US tickers.
- T11: n8n stub calls app endpoint.

### Wave 3 - Days 8-12

- T3/T10: persist evidence ledger and call logs.
- T9: final dashboard sections: scorecard, matrix, rejected list, evidence ledger, tactical dashboard.
- T11: delivery and error branch.
- T12: resolver and first calibration report.
- T13: Quiver source registration, fixtures, and capped `political_flow` scoring leg.
- T14: Ollama Cloud provider support for dashboard prose generation.

### Wave 4 - Weeks 2-10

- Run daily/weekly with a small US universe.
- Compare CBOE chain outputs against a broker platform weekly.
- Add EU names only with manual/browser/paid options capture or explicit `S_O = n/a` degradation.
- Do not add LangGraph until deterministic jobs are stable.

## Definition Of Done For V1

- n8n triggers the Python app on schedule.
- Preflight probes run and source status is recorded.
- Raw data is cached before parsing.
- Candidate catalyst gate publishes accepted and rejected names.
- Daily snapshots, evidence ledger, component scores, setup signals, and call log are persisted.
- `S_O`, `S_M`, `S_S`, `S_I`, `S_F`, `S_CTE`, weights used, class, and tier are computed in Python.
- Missing components are re-weighted, never scored as zero.
- Tier C names do not appear in the Tactical Execution Dashboard.
- HTML and JSON dashboards render with evidence and rejected-gate sections.
- LLM prose passes numeric guard.
- Prior calls are scored against actuals and included in the next dashboard.

## Local Container Commands

```bash
cp .env.example .env
docker compose up --build
curl http://localhost:8000/health
```

n8n will be available at `http://localhost:5678`. The scheduler should call the app at `http://app:8000/run/daily` from inside the compose network.
