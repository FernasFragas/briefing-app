# Briefing App

Options-first trading briefing application that loads a configured universe, validates
market-data sources, computes component scores and strategy setups, then publishes
auditable dashboard artifacts. n8n is used for scheduling and delivery; Python owns the
actual pipeline logic.

## Tech Stack

- Python 3.14
- FastAPI and Uvicorn
- Pydantic and PyYAML
- SQLAlchemy, psycopg, and Postgres
- pandas, NumPy, and SciPy
- Jinja2 dashboard rendering
- Ollama Cloud for bounded LLM prose
- Docker Compose for local app, Postgres, n8n, sandbox, and SearXNG
- SearXNG for local n8n Assistant web search
- pytest for tests

## Architecture

```mermaid
graph LR
  N8N[n8n] --> API[FastAPI app]
  API --> PIPE[briefing pipeline]
  PIPE --> SRC[data providers and fixtures]
  SRC --> CACHE[raw cache]
  CACHE --> SCORE[gate, components, scoring]
  SCORE --> STRAT[strategy setups]
  STRAT --> DASH[dashboard JSON and HTML]
  DASH --> LLM[Ollama Cloud prose guard]
  LLM --> DASH
  DASH --> DB[(Postgres)]
  DASH --> OUT[output artifacts]
  OUT --> PUB[static delivery]
  PUB --> N8N
  N8N -. Assistant code .-> SANDBOX[n8n sandbox]
  N8N -. Assistant search .-> SEARCH[SearXNG]
```

See [Architecture Design](docs/ARCHITECTURE.md) for the folder organization and more
detail.

## Main Folders

- `src/briefing_app/`: application code.
- `config/`: example runtime configuration and source registry.
- `workflows/`: n8n workflow exports and runbooks.
- `migrations/`: Postgres schema migrations.
- `schemas/`: manual capture schemas.
- `tests/`: pytest suite.
- `data/`: raw cache.
- `output/`: generated dashboard and delivery artifacts.

## Project Docs

- Architecture: [ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Deployment choices: [DEPLOYMENT_OPTIONS.md](docs/DEPLOYMENT_OPTIONS.md)
- Source status and fixes: [SOURCE_STATUS.md](docs/SOURCE_STATUS.md)

## Local Run

Run the full local stack with the FastAPI app, Postgres, n8n, and the n8n
Assistant sandbox and web search services:

```bash
cp .env.example .env
docker compose up -d --build
```

Then open:

```text
http://localhost:8000/health
http://localhost:5678
```

Useful commands:

```bash
PYTHONPATH=src .venv/bin/python -m briefing_app.cli preflight
PYTHONPATH=src .venv/bin/python -m briefing_app.cli run-daily --force --max-tickers 1
PYTHONPATH=src .venv/bin/python -m briefing_app.cli run-daily --data-mode live --force --max-tickers 1
PYTHONPATH=src .venv/bin/python -m pytest
```

`pipeline.data_mode: fixture` remains the default for deterministic local runs. Use
`live` after configuring provider credentials; the run pulls CBOE delayed option chains
and uses FMP, Twelve Data, Finnhub, FRED, FINRA, SEC EDGAR and Alpha Vantage fallbacks
when those keys or public feeds are present.

### Reading the graded ideas table

The dashboard opens on a table of trading ideas, each carrying one certainty grade. Read it
from the JSON artifact with:

```bash
jq -r '.trading_ideas[]
  | [.status, .ticker, .grade_letter, .grade_score, .thesis_band, .blocked_reason]
  | @tsv' output/dashboard/$(date +%F)/dashboard.json | column -t -s$'\t'
```

The grade combines the probability of the setup's own thesis band with how well `S_CTE`
supports it, and is then **capped by the confidence tier**: Tier A can reach `A+`, Tier B
stops at `B+`, Tier C stops at `C`. A high probability computed from unverified data
therefore cannot present as a high-certainty idea. `grade_penalties` names each deduction,
and `thesis_band` names the band the probability was read from — the column is
`P(thesis band)`, never `P(profit)`.

Rows are ordered by actionability first: `TRADEABLE`, then `WATCHLIST`, then `BLOCKED`,
then `UNSCORED`. Grade descending is the tie-break inside each status bucket, so a lower
grade executable setup appears ahead of a higher-grade setup that cannot be traded today.

Directional theses use the favorable side of spot (`above spot` / `below spot`), not the
one-sigma breakout tail. Volatility theses still use the sigma bands directly.

Rows that were never scored carry `grade_letter: null` rather than a low grade: a name the
pipeline could not score is listed so its absence is visible, not graded on partial data.
Every non-`TRADEABLE` row states why in `blocked_reason`.

Every run records the mode it actually ran in — `data_mode` in the run status file, in
`dashboard.json`, in the `briefing_run` details column, and in the dashboard header — taken
from the data source that ran rather than from the requested setting, so an explicit
`--data-mode` or an injected data source cannot mislabel a run. Fixture rows are labelled
`synthetic`, never `verified`, which floors the required `S_O` to Tier C: **a fixture run
can produce a dashboard but never a tradeable call.** Fixture mode also refuses to feed any
leg the live path has no source for (`LIVE_UNSCORABLE_LEGS` in `pipeline.py`) — today
`executive_tone` and the risk-reversal history — so a leg that scores in fixture mode is
one that can score live.

### Live mode and provider plans

Live runs are shaped by what each key is actually entitled to, which is not the same as
what each provider documents:

- **Request budgets are enforced before a call is sent.** A free Alpha Vantage key allows
  25 requests a day; spending it silently is what previously made live runs fragile.
  Budgets are persisted per provider per day under
  `$BRIEFING_DATA_DIR/provider_budget/` and tuned with `ALPHA_VANTAGE_DAILY_REQUEST_BUDGET`,
  `FMP_DAILY_REQUEST_BUDGET`, and `TWELVE_DATA_DAILY_REQUEST_BUDGET`. Historical
  Alpha Vantage put/call history is no longer scheduled; P/C baselines are self-built
  from persisted option snapshots. Finnhub adds up to 2 requests per ticker but publishes
  no daily cap — only a per-minute rate — so it is paced rather than
  budgeted. Twelve Data backs up price history only when FMP gates a symbol; its Basic
  plan is budgeted at 800 requests/day and paced at 8 credits/minute.
- **Local runs persist by default even without Postgres.** If `DATABASE_URL` is unset and
  `BRIEFING_LOCAL_SQLITE` is not `0`, `false`, or `no`, the pipeline creates
  `$BRIEFING_DATA_DIR/briefing.sqlite3`. That lets the self-built IV and put/call
  baselines warm up during ordinary local live runs. Set `BRIEFING_LOCAL_SQLITE=0` to
  keep the old no-database behavior.
- **Premium endpoints are refused up front** when `ALPHA_VANTAGE_PLAN`, `FMP_PLAN`, or
  `TWELVE_DATA_PLAN` is `free`, so a metered key is never spent being told no. An endpoint
  that turns out to be plan-gated at runtime is recorded in
  `provider_budget/<provider>/plan_gated.json` and not retried; delete that file to
  re-probe after upgrading a plan.
- **A refusal is never scored as zero.** A plan gate, a spent budget, a throttle, and an
  empty body each land in the evidence ledger with their own status, and the affected
  component is re-weighted as unavailable.

Free-plan coverage on the current keys, as measured rather than as documented:

- **Alpha Vantage is not treated as dead.** It remains a metered fallback where useful,
  but the scheduled `HISTORICAL_PUT_CALL_RATIO` path was removed because it contributes
  nothing over self-built P/C baselines and spends the 25/day budget. See
  `docs/SOURCE_STATUS.md`.
- **FMP** serves price history, earnings calendar, analyst and price-target consensus, the
  congressional disclosure feeds and macro indicators — but only for a subset of symbols
  (AAPL, MSFT, NVDA, LMT and SPY answer; AVGO, ORCL, MU, QQQ, CRWV and AMAT return HTTP
  402). Its dated economic calendar, news, insider and institutional endpoints are
  plan-gated.
- **Twelve Data** is wired as the price-history fallback after FMP and before Alpha
  Vantage. It covers AVGO, ORCL, MU, QQQ, CRWV and AMAT on the verified key; RHM.DE and
  LDO.MI remain paid-plan gated.
- **Primary records lead where one exists**: SEC EDGAR Form 4 for `S_I`, FRED for `S_M`,
  FINRA's consolidated file for the borrow proxy, CBOE for the options chain.
- **`S_M` requires declared sector exposure.** The shipped example config now covers every
  sector in the 24-ticker live report and normalizes `Defense`; an undeclared sector still
  scores `S_M` as `n/a` by design.
- **Finnhub** serves company news and analyst recommendation trends. Its free tier is a
  rate limit (60/min) rather than a daily allowance, and it is **US-only** — an
  exchange-suffixed symbol is refused before a request is sent. It does not score its own
  news, so tone is derived locally by `providers/news_tone.py` and labelled `local tone`
  rather than passed off as a vendor score.
- **`S_F` (institutional) is declared permanently `n/a`** (Q4). It was blocked by design
  rather than by wiring — `docs/alternatives/pb1-13f-blocker.md` — and closing it properly
  needs a curated filer universe, a table and a two-quarter diff for 0.10 of the US weight.
  Nothing is fetched for it, in either run mode, so nothing is spent; its weight is
  redistributed across the components that did score. The reason travels with the run in
  `pipeline.DECLARED_UNSCORABLE_COMPONENTS`. Note that `S_F` is in the required set for
  expression classes `P` and `S`, so both stay Tier C while this stands; the shipped
  config enables only `V` and `E`.

Full local+n8n setup: [HOW_TO_RUN_WITH_N8N.md](workflows/HOW_TO_RUN_WITH_N8N.md).
Optional n8n Assistant setup: [N8N_ASSISTANT_SETUP.md](workflows/N8N_ASSISTANT_SETUP.md).

For the local n8n Assistant sandbox dialog, use:

```text
Service URL: http://sandbox-api:8080
API key: value of N8N_SANDBOX_SERVICE_API_KEY in .env
```

For the local n8n Assistant web search dialog, select SearXNG and use:

```text
Instance URL: http://searxng:8080
```

## Deploy

Recommended hosted setup:

```text
n8n Cloud -> Fly.io FastAPI app -> Ollama Cloud + providers + Postgres
```

Use Fly.io for the Python app, not for the local Docker Compose stack. n8n remains the
scheduler and calls the app over HTTPS.

- Fly.io app deployment: [DEPLOY_FLY_IO.md](docs/DEPLOY_FLY_IO.md)
- n8n Cloud workflow setup: [HOW_TO_RUN_WITH_N8N_CLOUD.md](workflows/HOW_TO_RUN_WITH_N8N_CLOUD.md)
- Deployment and orchestration options: [DEPLOYMENT_OPTIONS.md](docs/DEPLOYMENT_OPTIONS.md)

## n8n

- Local n8n guide: [HOW_TO_RUN_WITH_N8N.md](workflows/HOW_TO_RUN_WITH_N8N.md)
- n8n Assistant guide: [N8N_ASSISTANT_SETUP.md](workflows/N8N_ASSISTANT_SETUP.md)
- n8n Cloud guide: [HOW_TO_RUN_WITH_N8N_CLOUD.md](workflows/HOW_TO_RUN_WITH_N8N_CLOUD.md)
