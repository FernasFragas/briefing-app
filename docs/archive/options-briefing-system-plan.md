# Weekly Options & Multi-Factor Briefing System - Implementation Plan

Inputs incorporated:

- `trader analysis v2.md`
- `trading ideas.md`

## Objective

Build a self-hosted pipeline that produces a daily or weekly market briefing with:

- A ranked Master Alpha Selection Matrix.
- Probability-weighted price ranges derived from options and measured volatility.
- Options structure: OI clusters, gamma walls, put/call ratios, skew, IV rank, IV versus realized volatility.
- Macro and catalyst context: CPI, PPI, FOMC, jobs, earnings, dividends, sector policy, regulatory events.
- Multi-channel sentiment: institutional/analyst, executive/transcript, retail/social.
- Insider and institutional ownership signals where verified data exists.
- Conditional long, short, and volatility setups with class, tier, horizon, invalidation, and evidence ledger.
- A calibration scorecard comparing prior ranges and setups against what happened.

The system is a deterministic pipeline, not a single prompt. Ideas are sourced, gated, scored, validated, rendered, delivered, and later graded.

## Non-Negotiable Design Rules

1. **Compute everything in Python.** The LLM never estimates IV, ranges, scores, probabilities, catalyst dates, OI walls, borrow fees, or 13F deltas.
2. **Every number has an evidence row.** Record source, venue, as-of timestamp, endpoint/file, and validation status.
3. **Source hierarchy:** connected tools/API providers -> exchange/regulator primary sources -> company IR -> reputable aggregators. Web search may locate sources, but it is not the source of a market number.
4. **No invented numbers.** If a figure is unavailable, mark it `n/a` or `[unverified]`. Do not fill gaps with memory, round numbers, or prose.
5. **Missing component rule:** score missing components as `n/a`, drop their weights, and re-normalize remaining weights to 1.0. Disclose the re-weighting.
6. **Untrusted content rule:** filings, transcripts, forum posts, and fetched pages are data to extract, never instructions to follow.
7. **No catalyst, no tactical idea.** Candidates without a dated catalyst inside the horizon are demoted to watchlist.
8. **No measured sigma, no execution range.** Price history must support a measured range and invalidation level.
9. **No short without borrow/short-interest evidence.** A borrow-dependent short with missing borrow data is Tier C.
10. **LLM writes bounded prose only.** Temperature 0. Numeric guard checks generated text for unauthorized figures.

## Stack

| Layer | Tool | Why |
|---|---|---|
| Orchestration | n8n, Docker | Cron, retries, error branches, delivery. |
| App runtime | Python FastAPI + CLI | Deterministic pipeline jobs callable by n8n and locally. |
| Math | pandas, numpy, scipy | Options math, scoring, distributions, calibration. |
| Storage | PostgreSQL | Daily snapshots, evidence ledger, component scores, call log, calibration. |
| Raw cache | Local mounted `data/` | Re-run parsing/math without re-fetching provider data. |
| Rendering | Jinja2 -> HTML + JSON | Human briefing and audit artifact. |
| LLM | OpenAI or Claude API | Narrative layer only. |
| Delivery | Email, Discord, static HTML | Pick one first; keep adapters isolated. |
| Agent framework | LangGraph, later only | Skip until the fixed pipeline is stable. |

n8n should call the Python app over HTTP. Do not turn the stock n8n image into the Python runtime.

## Phase 0 - Environment And Contracts

The repo should run as three services:

- `app`: Python API/CLI service.
- `postgres`: persistence.
- `n8n`: schedule and delivery.

Local run:

```bash
cp .env.example .env
docker compose up --build
curl http://localhost:8000/health
```

n8n runs at `http://localhost:5678`. Inside the compose network it calls:

```text
POST http://app:8000/run/daily
Authorization: Bearer ${APP_RUN_TOKEN}
```

Contracts to define before parallel implementation:

| Contract | Purpose |
|---|---|
| `config/config.yaml` schema | Universe, geography, expression classes, providers, thresholds, catalysts, delivery. |
| Raw cache convention | `data/raw/{provider}/{endpoint}/{YYYY-MM-DD}/{symbol-or-market}.json` |
| Source entitlement result | Which providers/endpoints worked, failed, throttled, or returned synthetic data. |
| Evidence ledger row | Component, value, source, venue, as-of, endpoint/file, validation status, note. |
| Candidate model | Ticker, geography, sector, thesis, intended expression class, broker/instrument fit. |
| Normalized option chain | Expiry, strike, type, bid, ask, mid, IV, delta, gamma, OI, volume, timestamp, venue. |
| Metrics JSON v1 | All computed fields passed to templates and LLM. |
| Scoring JSON v1 | Component scores, weights used, missing components, tier, final `S_CTE`. |
| Pipeline API | `GET /health`, `POST /run/daily`, future `POST /run/weekly`, `POST /score/open-calls`. |

**Checkpoint:** `docker compose config` validates; app health endpoint responds; missing market-data keys do not crash boot.

## Phase 1 - Source Registry, Preflight, And Data Integrity

Run a cheap entitlement probe before scoring. Silent data failures are common and more dangerous than hard failures.

### Primary Source Map

| Component | US Source Priority | EU / Non-US Source Priority | Degradation Rule |
|---|---|---|---|
| Options chain / OI / greeks | CBOE delayed options JSON `https://cdn.cboe.com/api/global/delayed_quotes/options/<TICKER>.json`; Alpha Vantage `REALTIME_OPTIONS` only if entitled | Eurex product page via browser or paid feed; manual chain capture; product-level Eurex market statistics as checksum only | If per-strike chain unavailable, `S_O = n/a` and re-weight. |
| Put/call and volume/OI | Alpha Vantage P/C endpoints, CBOE, Barchart/Schaeffer's if subscribed | Eurex product-level stats, broker/manual capture | Percentile against own history only. |
| Short interest / borrow | FINRA short sale volume, exchange short interest, Ortex/S3/IBKR if available | Bundesanzeiger net shorts, FCA aggregate short positions, national SSR registers | Short setups require verified borrow/short-interest. |
| Price history | Alpha Vantage daily adjusted, FMP, exchange/broker feed | Local venue/broker feed, Stooq/Yahoo only if accessible and validated | No price history means no measured sigma and Tier C. |
| Macro | FMP economics, Alpha Vantage macro, FRED, Fed/ECB calendars | Same plus ECB/national calendars | Use latest release and event date. |
| News sentiment | Alpha Vantage `NEWS_SENTIMENT`, FMP news/tipranks, reputable news APIs | Same where covered | Retail/social is never the whole thesis. |
| Insider | SEC EDGAR Form 4, Alpha Vantage/FMP insider endpoints | MAR Article 19 PDMR dealings through issuer IR, BaFin, or national OAM | Automated plans/options exercises excluded. |
| Institutional flow | 13F filings, FMP/SEC filings | Major-holdings notifications, issuer IR, Bundesanzeiger | EU notifications are event signals, not quarterly accumulation waves. |
| Fundamentals/analyst | Company IR, SEC filings, FMP analyst/tipranks/statements | Company IR, exchange filings, FMP where entitled | Aggregator-only data must be labeled. |

### Known Traps To Encode

- Alpha Vantage premium endpoints can return valid-looking sample data with `message`, `Information`, or `Note` fields. Reject these payloads.
- Reject sentinel contracts such as `XXYYZZ`, impossible dates such as `2099-99-99`, and suspiciously uniform values across option legs.
- HTTP 200 is not proof of data. JS-rendered exchange pages may return placeholders. Assert the fields you came for actually exist.
- `optioncharts.io` was identified as paywalled in the source docs. Do not spend implementation time on it unless credentials are later added.
- FMP endpoints may be plan-gated or truncated. Absence from a truncated calendar is not evidence of no event.
- EU per-strike options OI is not freely fetchable with simple HTTP in the source docs. Use browser capture, paid feed, manual capture, or mark `S_O = n/a`.

**Checkpoint:** the pipeline writes a preflight report listing source status before any score is computed.

## Phase 2 - Universe Construction And Catalyst Gate

The briefing can run in two modes:

1. **Fixed briefing universe:** 8-12 liquid names the user follows, favoring US names with weekly options first.
2. **Idea-screening universe:** 15-30 raw candidates from sector maps, quantitative screens, watchlists, and themes.

Each candidate must declare:

- Ticker, exchange, country, sector, currency.
- Intended expression class: `V`, `E`, `P`, or `S`.
- Broker/platform and permitted instruments: shares, ETF, options, factor certificate, knock-out, etc.
- One-line thesis and expected horizon.
- Dated catalyst inside the horizon, marked `Confirmed` or `Estimated`.

Gate rules before scoring:

| Reject / Demote Condition | Treatment |
|---|---|
| No dated catalyst in horizon | Watchlist only; do not score for execution. |
| Tier C after required data pull | Watchlist only. |
| Illiquid options chain | No options-structure setup. |
| Earnings inside holding window but not modeled | Reject tactical range. |
| Short thesis without borrow/short-interest evidence | Reject as short. |
| Thesis rests on one aggregator number with no primary support | Demote or mark unverified. |
| Consensus/crowded trade with widely telegraphed catalyst | Flag crowding and reduce confidence. |

**Checkpoint:** candidate table separates scored names from rejected-at-gate names.

## Phase 3 - Storage Model

Persist both market snapshots and the evidence behind them.

```sql
CREATE TABLE daily_snapshot (
  ticker TEXT,
  snap_date DATE,
  geography TEXT,
  spot NUMERIC,
  iv_atm NUMERIC,
  iv_rank NUMERIC,
  expected_move_1w NUMERIC,
  expected_move_1m NUMERIC,
  pc_ratio_vol NUMERIC,
  pc_ratio_oi NUMERIC,
  rr_25d NUMERIC,
  realized_vol_20d NUMERIC,
  component_scores JSONB,
  cte_score NUMERIC,
  confidence_tier TEXT,
  expression_class TEXT,
  raw JSONB,
  PRIMARY KEY (ticker, snap_date)
);

CREATE TABLE evidence_ledger (
  id SERIAL PRIMARY KEY,
  run_id BIGINT,
  ticker TEXT,
  component TEXT,
  field_name TEXT,
  field_value TEXT,
  source TEXT,
  venue TEXT,
  as_of TIMESTAMPTZ,
  endpoint_or_file TEXT,
  validation_status TEXT,
  note TEXT
);

CREATE TABLE candidate_gate (
  run_id BIGINT,
  ticker TEXT,
  decision TEXT,
  reason TEXT,
  catalyst_name TEXT,
  catalyst_date DATE,
  catalyst_status TEXT
);

CREATE TABLE call_log (
  id SERIAL PRIMARY KEY,
  ticker TEXT,
  made_on DATE,
  horizon TEXT,
  expression_class TEXT,
  predicted_low NUMERIC,
  predicted_high NUMERIC,
  confidence NUMERIC,
  setup_type TEXT,
  invalidation TEXT,
  catalyst_date DATE,
  actual_close NUMERIC,
  inside_range BOOLEAN,
  resolved_on DATE
);
```

**Checkpoint:** one dry run can be replayed entirely from raw cache plus database rows.

## Phase 4 - Options Math And Structure (`S_O`)

This remains the core. It drives both volatility setups and much of the tactical range.

### Expected Move

Compute both methods and compare:

```python
expected_move_pts = call_atm_mid + put_atm_mid
expected_move_pct_straddle = expected_move_pts / spot
expected_move_pct_iv = iv_atm * math.sqrt(dte / 365)
```

Use the expiry matching the horizon: weekly for 1-week, monthly for 1-month. Report 1-sigma and 2-sigma bands. If the two methods diverge beyond a configured threshold, emit a diagnostic and do not silently choose one.

### Measured Sigma

Compute realized-volatility bands from real closes:

- 20-day and 60-day realized volatility.
- Event-day widening multiplier from config or empirical event history.
- Range builder output: low, high, midpoint, lookback, sigma percentage, event adjustment.

No real closes means no tactical range.

### Implied Distribution

Use Breeden-Litzenberger on a cleaned chain:

1. Take mid prices across strikes for one expiry.
2. Fit a smooth curve to implied vol versus strike.
3. Re-price a dense strike grid with Black-Scholes.
4. Take the discrete second difference.
5. Normalize the density.

Sanity checks:

- Density non-negative or repaired with disclosed method.
- Integrates near 1.0.
- Mean sits near forward.
- Probability queries such as `P(close > K)` and `P(close < K)` are computed, not narrated.

### Positioning Metrics

```python
pc_ratio_volume = put_volume / call_volume
pc_ratio_oi = put_oi / call_oi
rr_25d = iv_25d_call - iv_25d_put
iv_rank = percentile_of(iv_atm, iv_history_1y)
vrp = iv_atm - realized_vol_20d
oi_by_strike = concentration_map(chain)
gamma_by_strike = dealer_gamma_map(chain, assumption="dealers short calls, long puts")
```

Add short/borrow where available:

- Short interest percent of float.
- Days to cover.
- Borrow fee and availability/utilization.
- FINRA daily short-volume trend as a flow proxy, not true short interest.
- EU disclosed net short positions as holder-level disclosure, not float-wide SI.

`S_O` combines options richness/cheapness, skew, OI/gamma clusters, put/call percentile, and short/borrow context. Always compare each metric to its own ticker history where history exists.

**Checkpoint:** given a ticker/date, produce metrics JSON and evidence ledger rows for every `S_O` input.

## Phase 5 - Macro, Sentiment, Insider, And Institutional Components

### `S_M` - Macro Context

Score macro from -1.0 to +1.0 using:

- Upcoming CPI, PPI, FOMC/ECB, NFP/jobs, PCE, GDP, retail sales.
- Rates, yield curve, dollar, credit, commodities relevant to the sector.
- Sector policy/regulatory headwinds or tailwinds.
- Geopolitical or commodity shocks where the ticker is exposed.

Every scheduled event needs date, release time if available, source, and relevance note. Macro can override single-name structure, so the renderer should display broad index/sector risk beside single-name scores.

### `S_S` - Multi-Channel Sentiment Matrix

Compute:

```text
S_S = (S_S1 * 0.45) + (S_S2 * 0.35) + (S_S3 * 0.20)
```

Where:

- `S_S1`: institutional / analyst sentiment.
- `S_S2`: executive tone / transcript tone.
- `S_S3`: retail momentum / social chatter.

News sentiment still includes the original 24-hour aggregate, 7-day trailing baseline, delta, article count, and top deduplicated headlines. Retail chatter is only 20 percent of sentiment and never a standalone thesis.

### `S_I` - Insider Velocity

US:

- SEC Form 4 open-market buys/sells over the past 90 days.
- Exclude 10b5-1 plans, options exercises, and tax-withholding sales.
- Tier CEO/CFO highest, then operating executives/board, then 10 percent owners/directors.

EU:

- Use MAR Article 19 PDMR / directors' dealings from issuer IR, BaFin, or national OAMs.

If no verified insider data is available, `S_I = n/a`.

### `S_F` - Institutional Flow

US:

- 13F position changes by cohort.
- Separate active hedge funds from passive index aggregators and sovereign/pension flows.

EU:

- Use major-holdings notifications and issuer IR.
- Treat as event-driven ownership signal, not quarterly accumulation.

If ownership data is plan-gated or stale beyond its release cadence, `S_F = n/a`.

**Checkpoint:** component scores are standardized to -1.0 to +1.0 with evidence rows and missing-component disclosures.

## Phase 6 - Composite Trading Edge Score And Confidence Tier

### US Weights

```text
S_CTE = (0.30 * S_M) + (0.25 * S_O) + (0.20 * S_S) + (0.15 * S_I) + (0.10 * S_F)
```

### EU Weights

```text
S_CTE_EU = (0.35 * S_M) + (0.30 * S_O) + (0.20 * S_S) + (0.10 * S_I) + (0.05 * S_F)
```

When a component is `n/a`, drop its weight and re-normalize the remaining available components. Example: if `S_I` and `S_F` are missing on a US Class V setup, the remaining weights become:

```text
S_M: 0.30 / 0.75 = 0.4000
S_O: 0.25 / 0.75 = 0.3333
S_S: 0.20 / 0.75 = 0.2667
```

Disclose the original weights, missing components, and weights used.

### Score Interpretation

| Score | Posture | Default Treatment |
|---|---|---|
| +0.60 to +1.00 | Strong bullish edge | Eligible long/event expression if Tier A/B. |
| +0.15 to +0.59 | Moderate bullish bias | Smaller long/event expression or watchlist. |
| -0.14 to +0.14 | Neutral / mean reverting | Range-bound volatility structures if `S_O` supports it. |
| -0.15 to -0.59 | Moderate bearish bias | Hedge, reduce exposure, or small bearish expression. |
| -0.60 to -1.00 | Strong bearish edge | Eligible short/put expression only with borrow and Tier A/B. |

### Expression Classes And Required Components

Declare the expression class before the data pull.

| Class | Horizon | Required | Optional |
|---|---|---|---|
| `V` - Vol / options structure | Days to 2 weeks | `S_O`, `S_M` | `S_S`, `S_I`, `S_F` |
| `E` - Event directional | Days to weeks | `S_O`, `S_M`, confirmed dated catalyst | `S_S`, `S_I`, `S_F` |
| `P` - Positional fundamental | Weeks to quarters | `S_M`, `S_S`, `S_I`, `S_F` | `S_O` |
| `S` - Short / borrow-dependent | Any | Everything in `P`, plus verified borrow/short-interest | None |

### Confidence Tier

Tier over the required set only:

| Tier | Required-Component Condition | Treatment |
|---|---|---|
| A | All required components verified from primary/exchange/API sources inside staleness bounds | Full candidate size. |
| B | One required component is aggregator-sourced, partial, or stale beyond ideal bound | Half size. |
| C | Any required component is `n/a`, paywalled, or unverifiable | Watchlist only. |

Universal Tier C floors:

- Missing measured sigma from real closes.
- Missing dated catalyst inside horizon.
- Missing invalidation level.
- Borrow-dependent short missing borrow or short-interest evidence.

**Checkpoint:** scoring output includes `S_CTE`, weights used, expression class, tier, and the required-set verdict in one line.

## Phase 7 - Strategy And Execution Rules

Generate setups in code. The LLM may explain a setup that fired, but it never decides one.

### Volatility / Options Structure (`V`)

Examples:

- **Short premium / iron condor:** `iv_rank > 70`, neutral `S_CTE`, skew not extreme, no unmodeled catalyst inside expiry, liquid chain, range available.
- **Long premium / straddle or calendar:** `iv_rank < 25` or IV cheap versus event risk, catalyst inside 10 days, measured range available.
- **Skew structure:** 25-delta risk reversal materially away from own history and probability distribution supports asymmetric tails.

Required fields: range, expiry, IV rank, VRP, skew, liquidity, invalidation, horizon.

### Event Directional (`E`)

Examples:

- Strong positive or negative `S_CTE` with confirmed catalyst inside horizon.
- Options structure shows breakout/supply level and the event can plausibly resolve the range.
- Vol check states whether the move is already priced.

Required fields: catalyst date, event status, range, invalidation, scenario probabilities, tier.

### Positional Fundamental (`P`)

Examples:

- Multi-week long/short candidate where macro, sentiment, insiders, and institutional flow align.
- Options are optional for tiering, but still useful for expression timing.

Required fields: ownership/insider evidence, macro/sector thesis, sentiment matrix, invalidation.

### Short / Borrow-Dependent (`S`)

Examples:

- Negative `S_CTE`, deteriorating fundamentals or ownership flow, confirmed catalyst, verified borrow/short-interest, and explicit squeeze risk.

Required fields: borrow fee/availability or short-interest source, days to cover where available, catalyst, invalidation, range.

No setup is emitted without:

- Horizon.
- Dated catalyst.
- Invalidation.
- Instrument fit.
- Evidence ledger.
- Tier A/B.

**Checkpoint:** rule engine emits setup candidates and rejected reasons; Tier C names never enter the Tactical Execution Dashboard.

## Phase 8 - Narrative, Rendering, And Guardrails

One LLM call per ticker section plus one overview is acceptable. The prompt must use only computed JSON.

Prompt contract:

```text
You are writing one section of a pre-market institutional briefing.
Use ONLY the numbers and source labels provided.
Do not estimate, infer, or add any figure not present below.
If a field is null or n/a, say unavailable.
Do not give financial advice. Describe the conditional setup, tier, invalidation, and catalyst.
```

Every prompt includes:

- Ticker, venue, timestamp, spot.
- Expression class, confidence tier, required-set verdict.
- `S_M`, `S_O`, `S_S`, `S_I`, `S_F`, `S_CTE`, original weights, weights used.
- Expected move and measured-sigma ranges.
- Distribution probabilities.
- OI/gamma clusters and put/call/skew context.
- Catalyst and event status.
- Evidence summary.
- Setup rule that fired, if any.

Rendered output:

1. Prior scorecard and calibration.
2. Market overview: SPY/QQQ/VIX, macro calendar, rates/commodities context.
3. Weekly Master Alpha Selection Matrix.
4. Rejected-at-gate list with reasons.
5. Evidence Ledger for every ranked name.
6. Tactical Execution Dashboard: top long, top short, top volatility setup.
7. Conditionality Table with event/price triggers and probabilities.
8. Per-ticker sections with ranges, distributions, positioning, news, catalysts, and setup status.

Numeric guard:

- Extract numbers from LLM output.
- Compare to allowed numbers in input JSON.
- Fail or flag if the model introduces unauthorized figures.

**Checkpoint:** full briefing generated for one ticker and one rejected candidate from fixtures.

## Phase 9 - Assembly, Delivery, And Calibration

### Daily / Weekly Job

n8n:

1. Weekday or weekly cron at 06:30 Europe/Lisbon.
2. Market-day check.
3. Call app `POST /run/daily`.
4. Deliver HTML/JSON by configured adapter.
5. Error branch sends run id, failing stage, and failing ticker.

### Calibration Loop

No new dashboard should omit the prior scorecard.

Persist:

- Predicted low/high.
- Scenario probabilities.
- Setup type and class.
- Catalyst date.
- Invalidation.
- Actual close and outcome.

Score:

- 1-sigma containment versus approximately 68 percent target.
- 2-sigma containment versus approximately 95 percent target.
- Midpoint bias.
- Setup outcomes net of estimated spread/fees where available.
- Whether catalyst branch resolved as expected.

Run the system for 4-8 weeks before trusting any signal. Run it for about 3 months before drawing conclusions about expectancy.

## Timeline

| Phase | Effort | Deliverable |
|---|---|---|
| 0 - Environment/contracts | 0.5-1 d | Docker app/postgres/n8n, config schema, API stub. |
| 1 - Source registry/preflight | 1-2 d | Entitlement report, source probes, raw cache rules. |
| 2 - Universe and catalyst gate | 1-2 d | Candidate table, catalyst gate, rejected list. |
| 3 - Storage | 1-2 d | Snapshots, evidence ledger, gate results, call log. |
| 4 - Options math / `S_O` | 4-6 d | Expected move, distribution, OI/gamma, skew, IV/RV. |
| 5 - Macro/sentiment/ownership | 3-5 d | `S_M`, `S_S`, `S_I`, `S_F` with evidence. |
| 6 - Score and tier | 1-2 d | `S_CTE`, missing-component reweighting, class tiers. |
| 7 - Strategy engine | 2-3 d | Rule-based V/E/P/S setups and invalidations. |
| 8 - Narrative/rendering | 2-3 d | HTML/JSON dashboard and LLM numeric guard. |
| 9 - Delivery/calibration | 2-3 d | n8n workflow, scoring loop, operational alerts. |
| Total | ~3 weeks part-time | Working v1 with a small US universe. |

Then run and calibrate for 4-8 weeks before expanding the universe or adding agentic workflow logic.

## What Is Reliable And What Is Not

Genuinely informative:

- Expected move from options prices.
- Implied distribution and skew.
- IV rank and IV versus realized volatility.
- Options OI/gamma clusters when sourced from a real chain.
- Confirmed catalyst calendar.
- Insider/ownership flow when sourced from filings.
- Positioning extremes relative to the ticker's own history.

Useful but fragile:

- News sentiment delta.
- Analyst sentiment.
- Retail/social momentum.
- Gamma "pin" maps, because dealer positioning is assumed.
- EU options structure without a paid feed or verified browser/manual capture.

Do not trust:

- Alpha Vantage premium sample data on a free key.
- JS pages that returned HTTP 200 but no actual data fields.
- Aggregator-only figures with no as-of date.
- Directional calls with no catalyst, no invalidation, or no measured range.

## Common Failure Modes

| Failure | Prevention |
|---|---|
| Synthetic provider payload treated as real data | Reject `message`/`Information`/`Note`, sentinel symbols, impossible dates, uniform legs. |
| Annualization error | Unit-test `sqrt(365)` options convention and realized-vol conventions separately. |
| Stale chain data | Assert quote timestamp and print venue/as-of. |
| Illiquid strikes poisoning smile fit | Filter min OI, min volume, max bid/ask width. |
| Earnings IV read as a signal | Flag earnings/event inside expiry and adjust event range. |
| Missing component scored as zero | Use `n/a`, drop weight, re-normalize, disclose. |
| EU data scored with US assumptions | Use EU weights and EU disclosure substitutes. |
| Short idea without borrow data | Automatic Tier C. |
| LLM invents figures | Temperature 0, explicit prompt ban, numeric guard. |
| Same wire story counted many times | Deduplicate titles and canonical URLs. |
| Same failed name rediscovered weekly | Publish rejected-at-gate list. |
| Silent failure | n8n error branch and persisted run status. |

## Notes

- Check each provider's terms of service for storage and redistribution, especially options data.
- Nothing here is financial advice or a recommendation to trade. The system produces structured, sourced decision inputs.
- Build the data validation and options math before polishing HTML. A beautiful dashboard with wrong vol math is worse than no dashboard.
