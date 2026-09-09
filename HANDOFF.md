# Onboarding — what a fresh session cannot infer from the code

Last reviewed **2026-09-09**. This file holds only what reading the repository will not
tell you: the traps, the constraints that look arbitrary but are not, and the commands worth
knowing. **Everything else has moved** — see [Where everything lives](#where-everything-lives).

The full 892-line handoff this replaces is preserved at
[`docs/archive/handoff-2026-09-03-full.md`](docs/archive/handoff-2026-09-03-full.md).

---

## Read these first, in this order

1. [`docs/architecture/decisions/README.md`](docs/architecture/decisions/README.md) — the
   sixteen decisions that bind everything. Do not re-litigate one; if you think it is wrong,
   write that in [`tasks/CROSS-LANE.md`](tasks/CROSS-LANE.md).
2. [`tasks/README.md`](tasks/README.md) — what is being built now, who owns which file, and
   the definition of done.
3. Your own lane document in [`tasks/lanes/`](tasks/lanes/), if you have one.

---

## Where the system stands

**Baseline: 671 tests passing, zero failures.** Round 3 is open; no lane has started.

Live provider chains actually in force — `config.providers`, verified on the last live run:

| Leg | Chain | The thing to know |
|---|---|---|
| Options chain `S_O` | `[cboe, alpha_vantage]` | **CBOE carries the live path.** It is keyless and free, so a run with no API credentials still stores options data |
| IV rank, put/call percentiles `S_O` | self-built from `daily_snapshot` | Warm-up gated; withheld until the threshold, and it says so |
| Insider `S_I` | `[sec_edgar, alpha_vantage, fmp]` | Form 4 only; 10b5-1, exercises and tax withholding excluded |
| Borrow `S_O` | `[finra]` | Daily short **volume**, not short interest. Labelled a proxy on its own field |
| Macro `S_M` | `[fred, fmp]` | Aged by **release** date, not period date. See trap 8 |
| News `S_S` | `[finnhub, alpha_vantage, fmp]` | Finnhub does not score its own news; tone is a local lexicon read, ~50% of articles measurable |
| Analyst `S_S` | `[fmp, finnhub]` | Fallback, not a merge. **US names only** — Finnhub's free tier is US-only |
| Prices | `[fmp, twelve_data, alpha_vantage]` | Twelve Data backs the six FMP-gated US symbols |
| Political `S_S` | `[fmp senate, fmp house]` | Two market-wide requests per run, locally filtered, capped ±0.05 overlay |
| Retail `S_S` | `[apewisdom]` | Keyless attention feed. Mention *delta*, not sentiment |

`LIVE_UNSCORABLE_LEGS` = `executive_tone`, `risk_reversal_history`. `S_F` (institutional
flow) is permanently `n/a` by decision Q4.

**Credentials:** Alpha Vantage, Financial Modeling Prep, FRED, Finnhub and Twelve Data are
all set and verified. `QUIVER_API_KEY` is empty and optional — Quiver serves no options data
at all and Financial Modeling Prep covers political flow.

**The Alpha Vantage free allowance is 25 requests per day**, shared by the daily run and any
agent work. It is the single most contended resource in the project.

---

## The ten things that will catch you

These are ordered by how much time they cost when missed. Every one has already happened.

1. **Verify the premise before building. This repository's doctrine, and it keeps paying.**
   A ticket said the EDGAR normalizers "already exist and pass tests" — both were
   scaffolding, 19 helpers referenced and none defined, importing cleanly because Python
   resolves names at call time. Two research tasks closed on *disproof*: the gap was an
   unsupplied argument, not a missing vendor. Another found the leg already served by a
   provider that was already keyed.

2. **Probe through the shipping client, never `curl`.** A `curl` probe proves an entitlement
   and misses the bug. Probing through the real client is what caught the news lexicon
   scoring "Stock Tumbled" as unmeasurable — headlines are written in the past tense and the
   lexicon was present-tense only. Coverage went 47% → 50% once inflections were added.

3. **The fixture path lies about coverage.** Fixture `S_S` reports `available=True` with all
   three legs present and `na_reason=None`, including legs with no live source. Any claim
   about leg coverage must come from a live run or a hand-built `ComponentResult` — never a
   fixture run. `LIVE_UNSCORABLE_LEGS` and `_refuse_fabricated_legs` exist to catch this.

4. **A refusal is never cached, and a cached payload is not evidence.** 47 files under
   `data/raw/alpha_vantage/` were once refusals wearing HTTP 200, and were purged.
   Entitlement is proven only by a probe whose validation passed on the run that wrote it —
   and *non*-entitlement the same way. Reading "Alpha Vantage refuses everything" off one
   exhausted-quota probe is what produced a withdrawn premise.

5. **Financial Modeling Prep's HTTP 402 has four meanings** — endpoint gate, symbol gate,
   parameter gate, and an exhausted quota wearing plan-gate language.
   `provider_validation.py` classifies them. Never memoise a bare 402 as an endpoint gate.

6. **A symbol boundary is not an endpoint gate.** Finnhub answers 403 both for a premium
   endpoint and for a non-US symbol. Memoising the second as the first would retire
   `company_news` for the whole universe on the first European ticker. `FinnhubClient`
   raises the symbol refusal directly, never through `_response`.

7. **One endpoint can answer two questions, and the raw cache keys on the target.**
   `fred.release_dates` is asked backwards (which release carried this reading) and forwards
   (what is scheduled next), for the same release on the same run date. The `window`
   argument gives the forward call its own slot; without it the second write overwrites the
   first and the ageing join silently reads a file of future dates.

8. **Two off-by-one traps, already hit and fixed.** A macro reading is dated by the **period
   it measures**, not its release — ageing from the period start made a two-week-old
   inflation print read as two months stale. And the release carrying a period is the first
   one after that period **ends**; matching on "first release after the period start" is off
   by exactly one release and looks correct.

9. **A required component must be *capable* of reading `verified`, or it caps the whole
   universe.** Adding `S_S` to `REQUIRED_COMPONENTS` was correct and did nothing, because
   `S_S` judged its own completeness over legs that can never be available. The result was
   19 rows at Tier B and nothing above — a constant tier again, one letter lower. Before
   putting a component in a required set, check that some real run can make it `verified`.

10. **The grade's two halves key off different fields, and both are needed to recompute a
    row.** `_effective_weights()` branches on the **thesis band**; `alignment()` branches on
    the **direction**. They agree for `above spot` / `below spot` / `within 1 sigma` and
    diverge for `beyond ±1 sigma`, where a long skew structure takes the *neutral* weight
    split but the *directional* alignment branch. That is why `direction` is published on
    `TradingIdeaRow`: without it, two rows with identical published fields grade differently
    and neither can be checked.

---

## Useful commands

```bash
# Tests — the baseline is 671 passing, zero failures
PYTHONPATH=src .venv/bin/python -m pytest

# Fixture run (deterministic, no keys, spends no allowance)
PYTHONPATH=src .venv/bin/python -m briefing_app.cli run-daily \
  --config config/config.example.yaml --force

# Read the graded ideas table
jq -r '.trading_ideas[] | [.grade_letter,.grade_score,.ticker,.status,.blocked_reason] | @tsv' \
  output/dashboard/$(date +%F)/dashboard.json | column -t -s$'\t'

# Recompute every grade from the published document — the fastest proof that a
# presentation change did not become a grading change
PYTHONPATH=src .venv/bin/python ops/audit_dashboard.py output/published/latest/dashboard.json

# Which legs can the live path not score?
PYTHONPATH=src .venv/bin/python -c "
import sys; sys.path.insert(0,'src')
from briefing_app.pipeline import LIVE_UNSCORABLE_LEGS
[print(f'{k}: {v}') for k,v in LIVE_UNSCORABLE_LEGS.items()]"

# Live provider chains actually in force
PYTHONPATH=src .venv/bin/python -c "
import sys; sys.path.insert(0,'src')
from briefing_app.config import load_config
c=load_config('config/config.example.yaml')
[print(f'{l:15} {getattr(c.providers,l)}') for l in
 ('options','prices','news','earnings','macro','analyst','insider',
  'institutional','put_call','political','retail','short_interest')]"

# Volatility baseline state — how far the warm-up has got
.venv/bin/python -c "
import sqlite3; c = sqlite3.connect('data/briefing.sqlite3')
print('sessions:', c.execute('select count(distinct snap_date) from daily_snapshot').fetchone()[0])
print('iv_rank set:', c.execute('select count(*) from daily_snapshot where iv_rank is not null').fetchone()[0])"

# Did the daily run actually happen, and did it spend anything?
ls data/runs/ | tail -5
ls data/provider_budget/alpha_vantage/ | tail -5

# What the news lexicon makes of a headline
PYTHONPATH=src .venv/bin/python -c "
import sys; sys.path.insert(0,'src')
from briefing_app.providers.news_tone import score_article_tone, tone_label
h='Chipmaker beats estimates and raises guidance'
s=score_article_tone(h); print(h, '->', s, tone_label(s))"
```

---

## Where everything lives

| Looking for | Go to |
|---|---|
| Why something was decided | [`docs/architecture/decisions/`](docs/architecture/decisions/) |
| What is being built now | [`tasks/README.md`](tasks/README.md), [`tasks/lanes/`](tasks/lanes/) |
| What the report is meant to say | [`docs/product/`](docs/product/) |
| How the system is put together | [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md) |
| Why a run said `partial` | [`docs/architecture/RUN-HEALTH.md`](docs/architecture/RUN-HEALTH.md) |
| Whether a data source works | [`docs/research/SOURCE_STATUS.md`](docs/research/SOURCE_STATUS.md) |
| Whether a source was already investigated | [`docs/research/alternatives/`](docs/research/alternatives/) |
| How to run or deploy it | [`docs/operations/`](docs/operations/) |
| Something that used to be true | [`docs/archive/README.md`](docs/archive/README.md) |

Full map: [`docs/README.md`](docs/README.md).
