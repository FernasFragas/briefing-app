# EU Coverage — Symbol Mapping Implementation

Written 2026-09-02. Reviewed 2026-09-03. Status: **specified, not started, and blocked by
a premise this file did not check.**

> ## Review, 2026-09-03 — read this before starting E1
>
> Four things changed or were found wrong. The first one blocks the whole file.
>
> 1. **E1–E6 would produce no observable effect on a live run.** `run_daily` iterates
>    `gate_report.accepted` only (`pipeline.py:502` and `:532`), and every EU name is
>    **gate-rejected before any provider request is made** — `universe/gate.py:162-172`
>    refuses an options-dependent class on a non-US name whenever `eu_options_track` is
>    `C`, which it is (`config/config.example.yaml:55`). `OPTIONS_DEPENDENT_CLASSES` is
>    `{V, E}` and all four EU names are `V` or `E`, so **not one of them reaches
>    `pull_ticker`**. Confirmed on live run `daily-2026-09-03-06a2dfb4`: ASML.AS, LDO.MI,
>    RHM.DE and SIE.DE each have `components=0`, `setups=0`, no score, and **zero provider
>    requests**. E3's three call sites are unreachable for these tickers today, and E5's
>    acceptance criterion — "`RHM.DE` produces price bars, a news batch and analyst
>    signals" — **cannot be met on a live run** as the system stands. See
>    [§1a](#1a-the-premise-this-file-missed-the-gate-rejects-before-the-fetch).
> 2. **The scope is four names, not two.** `universe.mode` is `both`, so
>    `candidates.example.yaml` contributes **ASML.AS** and **SIE.DE** alongside the
>    universe file's RHM.DE and LDO.MI. E1 must probe four; E5 must edit two config files.
> 3. **`S_F` in [§5](#5-what-this-does-not-close) is out of date.** It is no longer "no
>    source for any name" — it was **declared permanently n/a** on 2026-09-02 (Q4).
> 4. **[§6](#6-the-decision-this-reopens) blames the wrong mechanism.** `REQUIRED_COMPONENTS`
>    is not what stops these names; the gate is. Changing the scoring model alone would not
>    let a single EU row through.
>
> **The recommendation at the end of §6 is inverted by finding 1.** "Do E1–E6, then decide"
> assumed the work would produce a real `RHM.DE` row to look at. It would not. The gate
> decision has to come first, or at minimum in the same change. See the revised
> [§6](#6-the-decision-this-reopens).
>
> Line references throughout have been re-anchored to the 2026-09-03 tree.

Tickets are numbered **E1–E6**. This is a *third* numbering scheme in this repo — `tasks/`
uses Stages 1–5 (`T1`–`T9`) and `provider-alternatives-implementation.md` uses Waves 0–3
(`I0`–`I16`). A bare "E-ticket" always means this file. The prefix is deliberate: these
tickets could have been `I17`+, but they reopen a **Phase A verdict** rather than continue
Phase B wiring, and folding them into the I-series would hide that.

**What this changes:** `RHM.DE` and `LDO.MI` currently reach the briefing with no market
data of any kind. This gets them price history, news and analyst coverage from providers
already wired and already keyed. It does **not** make them tradeable — see
[What this does not close](#what-this-does-not-close).

---

## 1. Premise check

The repo's doctrine is verify the premise before building. The premise here is a **stale
deferral**, and it is stale for a reason worth naming.

`docs/alternatives/pa5-eu-sources.md` rejects EU coverage, and `HANDOFF.md` Q2 records
`RHM.DE` / `LDO.MI` as "permanently Tier C". Both are correct **about options chains** and
both were written when Alpha Vantage was believed to be refusing every function. That
belief has since been withdrawn: the 2026-08-31 reading was a spent daily quota misread as
an entitlement refusal — the same quota-vs-entitlement trap `docs/SOURCE_STATUS.md` already
documents for FMP's 402, applied to AV and not caught.

With AV alive, the EU question is no longer "is there any source" but "which symbol do we
ask each provider for". Nobody had asked, because the deferral had closed the question.

### Evidence, 2026-09-02

Alpha Vantage `SYMBOL_SEARCH?keywords=Rheinmetall` returns six listings. Three matter:

| Symbol | Region | Currency | What it is |
|---|---|---|---|
| `RHM.DEX` | XETRA | EUR | The primary listing — the venue `universe.example.yaml` already declares |
| `RHM.FRK` | Frankfurt | EUR | Secondary German listing |
| `RNMBY` | United States | USD | Unsponsored ADR — **no exchange suffix** |

Probe results:

| Leg | Symbol | Result |
|---|---|---|
| Price history — AV `TIME_SERIES_DAILY` | `RHM.DEX` | ✅ **100 bars, newest 2026-09-01** |
| News — Finnhub `company-news` | `RNMBY` | ✅ 3 articles (Aug window) |
| Analyst — Finnhub `stock/recommendation` | `RNMBY` | ✅ 4 monthly rows |
| Quote / prices — FMP `quote` | `RHM.DE` **and** `RNMBY` | ❌ HTTP 402 symbol gate on both |
| Options chain — CBOE delayed | `RNMBY`, `RNMBF` | ❌ HTTP 403 AccessDenied on both |

**These probes were raw HTTP, not through the shipping clients.** That is exactly the
weaker evidence PB3 warned about — a `curl`-equivalent proves the entitlement and misses
the client, the validator and the normalizer. **E1 exists to redo them properly, and no
other ticket starts until it passes.**

### Why the ADR unlocks Finnhub

`FinnhubClient` refuses an exchange-suffixed symbol before spending a request
(`src/briefing_app/providers/finnhub.py:122-148`): any suffix longer than one character is
treated as a foreign exchange and refused, which is why `RHM.DE` is refused without a
request. `RNMBY` carries no suffix, so it passes the guard and reaches a free-tier endpoint
that answers. The guard is correct and must not be relaxed — the ADR is a genuinely US
listing, not a workaround.

### 1a. The premise this file missed — the gate rejects before the fetch

§1 checked whether a *source* exists. It did not check whether the pipeline would ever
*ask*. It would not.

```
pipeline.py:502    accepted = gate_report.accepted
pipeline.py:532    for gate_result in accepted:
pipeline.py:534        data = source.pull_ticker(...)
```

Only accepted candidates are pulled. And:

```
universe/gate.py:162   # Rule: classes that require S_O cannot run on a non-US name with no chain source.
universe/gate.py:163   needs_chain = candidate.expression_class in OPTIONS_DEPENDENT_CLASSES
universe/gate.py:164   if needs_chain and not candidate.geography.is_us:
universe/gate.py:165       if settings.eu_options_track == "C":
universe/gate.py:168           code=GateReasonCode.EU_OPTIONS_UNAVAILABLE
```

`OPTIONS_DEPENDENT_CLASSES` is `{V, E}` (`models/candidate.py:99-101`),
`eu_options_track` is `C` (`config/config.example.yaml:55`), and
`EU_OPTIONS_UNAVAILABLE` maps to `WATCHLIST` (`models/gate.py:59`). All four EU names are
`V` or `E`. So every one is diverted to watchlist **before** `pull_ticker` runs.

Live confirmation, `daily-2026-09-03-06a2dfb4`:

| Ticker | Class | Gate decision | Components | Provider requests |
|---|---|---|---:|---:|
| RHM.DE | E | watchlist — `eu_options_unavailable` | 0 | 0 |
| LDO.MI | E | watchlist — `eu_options_unavailable` | 0 | 0 |
| ASML.AS | V | watchlist — `eu_options_unavailable` | 0 | 0 |
| SIE.DE | E | watchlist — `leverage_requires_confirmed_catalyst`, `eu_options_unavailable` | 0 | 0 |

**What this does and does not invalidate.** The symbol research in §1 stands — those
probes were about provider entitlement, and entitlement is unchanged. D1–D4 stand. What
fails is the *sequencing claim*: E1–E6 do not produce a "real `RHM.DE` row" to base the A2
decision on, because the row is never populated. The mapping would be correct, tested, and
inert on the live path.

**Consequence for the ticket order.** E2/E3/E4 remain worth building — they are the
mechanism, and their tests exercise `pull_ticker` directly, so they can be proven without
the gate. But E5's live acceptance and the §6 recommendation both depend on a gate
decision that this file treated as downstream. It is upstream. See the revised §6.

---

## 2. Design decisions

### D1 — One company, two symbols, two jobs

| Use | Symbol | Why |
|---|---|---|
| Prices, quote | `RHM.DEX` | The position is in EUR on XETRA. This is the instrument being sized |
| News, analyst | `RNMBY` | Issuer-level information about the same company |

**Never source prices from the ADR.** `RNMBY` is an unsponsored ADR: a USD proxy at a
conversion ratio, with its own liquidity and its own spread. Realized vol computed from it
would not describe the XETRA position, and realized vol feeds the measured sigma range that
the whole risk framing rests on. Mapping prices to the ADR would be a silent, plausible,
wrong number — the failure mode this repo spends the most effort preventing.

News and analyst are different: they are statements about the issuer, not about a venue's
order book. Attributing them to `RHM.DE` is honest.

### D2 — The mapping is declared per candidate, never inferred

A new `provider_symbols` field on `Candidate`, defaulting to empty. When a provider has no
entry, the leg uses `candidate.ticker` exactly as today, so **no US name changes
behaviour**.

Rejected alternative: deriving the provider symbol from `venue` + `ticker` (`XETRA` →
`.DEX`). AV's suffixes are not a clean function of venue, the ADR cannot be derived from the
local line at all, and a derivation that is right four times and wrong once is worse than a
declaration. This matches the file's existing stance: *"Every field the gate needs must be
declared by the candidate itself; the gate never infers geography, class, or instrument fit
from market data"* (`models/candidate.py:309-313`).

### D3 — Coverage sourced through a proxy listing must say so

`NewsSentimentBatch` and `AnalystSignal` must carry the candidate's own ticker (`RHM.DE`),
because that is the row they score, but the **source label must name the ADR**. Precedent:
`providers/news_tone.py` labels a lexicon read `local tone` rather than letting it pass as a
vendor score. The same rule applies here — a reader must be able to see that Rheinmetall's
news came through `RNMBY` and is thinner than a primary-listing feed (3 articles vs NVDA's
247).

Concretely: the request uses the provider symbol; the normalizer is passed the candidate
ticker; the batch source string names both.

### D4 — What must NOT be mapped

- **Options (`_pull_alpha_vantage_chain`, CBOE).** CBOE answers 403 for both ADR lines, and
  an ADR with no listed options has no chain to find. Adding a mapping here would convert a
  clean "no source" into a per-run 403.

  **The ASML trap, added 2026-09-03.** This rule is about to look wrong for one name.
  Rheinmetall's US line is an *unsponsored* ADR with no listed options, so "no chain
  exists" and "do not map" happen to coincide. ASML's US line is a **sponsored** NASDAQ
  listing and is liquid, so a CBOE chain very likely *does* resolve for it — E1 must probe
  this and record the answer. **A chain that resolves does not close `S_O` for ASML.AS.**
  A USD option on the NASDAQ line does not price a EUR position on Euronext: different
  underlying, different currency, different session, different implied surface. This is
  D1's argument — realized vol must describe the instrument actually held — applied to
  implied vol, where it binds harder, because the measured sigma range and every
  option-derived leg rest on it. Mapping it would be the same silent, plausible, wrong
  number D1 exists to prevent, and it would be *more* convincing because the data would
  look complete. **The rule is "the chain must be on the instrument being sized", not
  "no chain exists".**
- **FMP, any leg.** 402 on both `RHM.DE` and `RNMBY` — the gate is on the symbol, and no
  mapping escapes it. FMP is simply out for this name.

### D5 — Scope is the four EU names the run actually loads

**Corrected 2026-09-03. This said "two"; the run loads four.** `universe.mode` is `both`
(`config/config.example.yaml:8`), so the fixed file and the candidate file both contribute:

| Ticker | Declared in | Class | `permitted_instruments` | Symbols known? |
|---|---|---|---|---|
| `RHM.DE` | `universe.example.yaml:273` | E | `[shares]` | ✅ `RHM.DEX` / `RNMBY`, probed raw |
| `LDO.MI` | `universe.example.yaml:298` | E | `[shares]` | ❌ unverified |
| `ASML.AS` | `candidates.example.yaml:214` | V | `[shares, options]` | ❌ unverified — and see the ASML trap in D4 |
| `SIE.DE` | `candidates.example.yaml:292` | E | `[knock_out, factor_certificate]` | ❌ unverified |

`LDO.MI`'s symbols are still an assumption — AV likely lists `LDO.MIL` plus a
`FINMY`-shaped ADR — and it is written here as an assumption on purpose. The same now
applies to ASML.AS and SIE.DE, which have never been probed at all.

`SIE.DE` is worth noting separately: it carries a second gate reason
(`leverage_requires_confirmed_catalyst`), so even a resolved chain would not admit it while
its catalyst is `estimated`. Symbol mapping is not its binding constraint.

---

## 3. Tickets

### E1 — Re-probe through the shipping clients *(blocks everything below)*

Repeat every probe in §1 through `AlphaVantageClient` and `FinnhubClient` rather than raw
HTTP, so the evidence covers URL construction, `validate_payload`, and the normalizers.
**Three of the four names have never been probed at all.**

- **Watch for — revised 2026-09-03.** AV's daily budget is 25 against a 23-ticker scored
  universe, so it is spent most days: it hit 25/25 on 2026-09-03 across three live runs
  plus a deep preflight. Two things have changed since this warning was written, and both
  help:
  - `earnings: [fmp, alpha_vantage]` (Q6/N4a) stopped AV spending up to 24 requests/day on
    a call that always refuses, so the budget is now genuinely available on a quiet day.
  - The budget file now records a **learned ceiling**: if a provider refuses on quota,
    `quota_exhausted` appears in `data/provider_budget/<provider>/<date>.json`. **Check that
    key before probing.** If it is present, the day is spent and any refusal you see will be
    `budget_exhausted`, not an entitlement verdict — the exact misread that created this
    ticket, now visible rather than inferred.
  - AV entitlements were separately proven by `preflight --deep` on 2026-09-03: all eight
    required AV endpoints returned `ok`. So a refusal during E1 is about the *symbol*, not
    the key.
- **Files:** a throwaway probe script; no source changes.
- **Acceptance:** every cell below is either confirmed with a row count, or recorded as
  refused with its status. All four names get a verdict either way.

| Ticker | Prices (AV) | News / analyst (Finnhub) | Options (CBOE) |
|---|---|---|---|
| `RHM.DE` | `RHM.DEX` — confirmed raw, re-confirm via client | `RNMBY` — confirmed raw, re-confirm via client | 403 on both lines; re-confirm |
| `LDO.MI` | *(unverified — probe)* | *(unverified — probe)* | *(probe)* |
| `ASML.AS` | *(unverified — probe)* | *(unverified — probe)* | **probe, and see D4's ASML trap** — a chain that resolves is the wrong instrument, not a solution |
| `SIE.DE` | *(unverified — probe)* | *(unverified — probe)* | *(probe)* |

### E2 — `provider_symbols` on the candidate model

- **Files:** `src/briefing_app/models/candidate.py`
- Add `provider_symbols: dict[str, str] = Field(default_factory=dict)` to `Candidate`.
  The model is `extra="forbid"`, so the field must exist before any YAML can declare it.
- Normalize keys to lowercase provider ids (`alpha_vantage`, `finnhub`) and values with the
  same `.strip().upper()` treatment `_clean_ticker` applies, so `rhm.dex` and `RHM.DEX`
  cannot become two different cache targets.
- Reject an unknown provider id at validation time rather than ignoring it silently — a
  typo'd key that never fires is indistinguishable from a leg that has no source.
- **Acceptance:** a candidate with no `provider_symbols` validates unchanged; one with a
  bad provider id fails loudly.

### E3 — Thread the mapping into the three legs

- **Files:** `src/briefing_app/pipeline.py`
- `candidate` is already bound in the live path (`pipeline.py:1301`), so the mapping is
  available without changing `CandidateGateResult`.
- Add a helper — `_provider_symbol(candidate, provider, default)` — returning the mapped
  symbol or the candidate's ticker.
- Apply it at exactly three call sites *(line anchors re-checked 2026-09-03; they moved
  when the PC2/PC3/PC4 pass edited this file, so re-grep rather than trusting them)*:
  - `_price_bars` (`pipeline.py:1621`) — the Alpha Vantage branch only. FMP and Twelve Data
    branches keep the plain ticker; both gate this symbol regardless.
  - `_news_batch` (`pipeline.py:2032`) — the Finnhub branch.
  - `_analyst_signals` (`pipeline.py:2241`) — the Finnhub branch. **Note:** this call site
    is now conditional on `issuer_backed` (PC3, index/fund names skip it). EU names are
    issuers, so the branch is reached — but the mapping goes inside the call, not around
    the condition.
- **These three call sites are unreachable for EU names today.** See §1a. Their tests must
  drive `pull_ticker` directly rather than going through `run_daily`, or they will pass
  vacuously.
- **The request symbol and the record symbol differ.** Pass the provider symbol to the
  client; pass `candidate.ticker` to the normalizer. Getting this backwards produces rows
  keyed `RNMBY` that no downstream consumer will match to the `RHM.DE` idea, and
  `LIVE_UNSCORABLE_LEGS` / `_refuse_fabricated_legs` will not catch it, because the leg
  genuinely has data — just under the wrong name.
- **Acceptance:** with the mapping set, a **direct `pull_ticker` call** for `RHM.DE`
  produces price bars, a news batch and analyst signals, all carrying
  `ticker == "RHM.DE"`; with it unset, every US name issues byte-identical requests to
  today. *(Amended 2026-09-03: "produces" cannot be asserted through `run_daily`, because
  the gate never accepts the name — §1a.)*

### E4 — Source labelling for proxy-listed coverage

- **Files:** `src/briefing_app/providers/normalizers.py`
- Where a batch or signal was fetched under a different symbol, the `source` string names
  it — e.g. `Finnhub company_news via RNMBY (local tone)`.
- **Acceptance:** a test asserts the ADR symbol appears in the source of an ADR-sourced
  batch, and does **not** appear for a directly-sourced one. Same shape as the existing
  `"local tone" in batch.source` assertion.

### E5 — Declare the mapping for the two EU names

- **Files:** `config/universe.example.yaml` **and `config/candidates.example.yaml`** —
  two files, not one (D5).
- Add `provider_symbols` to `RHM.DE` (`universe.example.yaml:273`), `LDO.MI`
  (`universe.example.yaml:298`), `ASML.AS` (`candidates.example.yaml:214`) and `SIE.DE`
  (`candidates.example.yaml:292`), using only symbols E1 confirmed.
- **Update the stale probe table at `universe.example.yaml:183-213`.** It currently records
  `RHM.DE`/`LDO.MI` as `402 symbol gate / 403 AccessDenied` with the conclusion "no options
  chain at all", and attributes the price-history gap to AV "currently refusing every
  function". The options half is still true; the AV half is withdrawn. Strike rather than
  delete, following the precedent set in `SOURCE_STATUS.md` — a quota-vs-entitlement misread
  is exactly what that file exists to teach.
- **A second correction in the same table.** Beyond the AV half, it also says
  *"Class P would avoid S_O but is not in `enabled_expression_classes`, and P requires S_I
  and S_F, which have no live source either."* `S_F` is no longer "no live source" — it was
  **declared permanently n/a** on 2026-09-02 (Q4), which is a stronger statement, not a
  weaker one: class P is now permanently unreachable for every name, not merely unsourced
  today. Restate rather than strike; the conclusion hardens.

```yaml
  - ticker: RHM.DE
    venue: XETRA
    provider_symbols:
      # Prices come from the XETRA line: the position is in EUR and realized vol
      # must describe the instrument actually held. News and analyst come from the
      # US ADR, which is the same issuer and clears Finnhub's US-only guard.
      alpha_vantage: RHM.DEX
      finnhub: RNMBY
```

### E6 — Fix the EU preflight probe symbol

- **Files:** `config/config.example.yaml:294` *(was 287; re-checked 2026-09-03)*
- `preflight.default_probe_symbols.EU` is still `RHM` — a symbol that exists on no provider
  in this system. `preflight.py` `_symbol_for_endpoint` falls back to it for any
  EU-geography endpoint with no explicit `probe_symbol`, so every such probe has been asking
  for a symbol that cannot resolve.
- **This ticket is independent of the gate blocker** and can land on its own. It is the only
  E-ticket whose acceptance is observable today, because preflight does not go through the
  candidate gate.
- Set it to whichever symbol E1 confirms, and note in a comment that the value must be a
  *provider* symbol, not a candidate ticker.
- **Acceptance:** a preflight run shows the EU-geography endpoints probing a symbol that
  resolves, or failing for a reason that is about the endpoint rather than the symbol.

---

## 4. Test plan

Mirrors the pattern the FRED calendar work used — client, normalizer, orchestration:

1. **Model** — a candidate with and without `provider_symbols`; an unknown provider id
   raises.
2. **Mapping helper** — mapped provider returns the mapped symbol; unmapped returns the
   ticker; unrelated providers are unaffected.
3. **Orchestration, the important one** — a fake fetcher asserting that with `RHM.DE`
   declared, the AV price URL contains `RHM.DEX`, the Finnhub URLs contain `RNMBY`, and the
   resulting models all carry `ticker == "RHM.DE"`.
4. **Regression** — a US candidate with no mapping issues exactly the URLs it does today.
   This is the test that protects 500-plus existing assertions from a silent rename.
5. **Negative** — no options or FMP call is ever made with a mapped symbol (D4).

---

## 5. What this does not close

*Updated 2026-09-03.*

| Leg | Status after this work | Why |
|---|---|---|
| **`S_O` options** | ❌ Still absent | No free EU per-strike chain exists (PA5 stands); Rheinmetall's ADR has no listed options (CBOE 403 on both lines). For ASML a chain may well resolve on the US line — and it is the wrong instrument, not a solution (D4) |
| **`S_F` institutional** | ⛔ **Declared permanently n/a** *(was: "still absent")* | Not a sourcing gap any more. Q4 closed it on 2026-09-02: a curated filer universe, a new table and a two-quarter diff are not justified by 0.10 of the US weight. The chain is `institutional: []` — nothing fetched, nothing probed. This **hardens** the §6 argument: class P is permanently unreachable, not merely unsourced |
| **`S_I` insider** | ❌ Still absent for EU | EDGAR is US-only; EU MAR Art. 19 remains `browser_required` with a loader that has never been fed. Tracked as `PC1-PF-14` in `docs/alternatives/still-failing.md` |
| **`S_M` macro** | ⚠️ Scores, but on US series | FRED is a US publisher. A German defence name would be scored against US macro factors. ECB Data Portal / Eurostat were named in PA9 and never implemented |
| **Gate admission** | ❌ **Unchanged — and this is the blocker** | `eu_options_track: C` diverts every options-dependent non-US name to watchlist before any fetch (§1a). Nothing in E1–E6 touches this |

**`S_O` is the one that decides everything**, and no amount of symbol mapping reaches it.
What §1a adds is that `S_O` does not merely *demote* these names — via the gate it stops
them being fetched at all.

---

## 6. The decision this reopens

```python
# src/briefing_app/models/scoring.py:33
REQUIRED_COMPONENTS = {
    V: {"S_O", "S_M"},
    E: {"S_O", "S_M"},              # RHM.DE is class E
    P: {"S_M", "S_S", "S_I", "S_F"},
    S: {"S_M", "S_S", "S_I", "S_F"},
}
```

> **Corrected 2026-09-03.** This section blamed `REQUIRED_COMPONENTS`. That is the *second*
> obstacle, not the first. EU names never reach scoring, so the required-set never runs for
> them — the **gate** turns them away (`universe/gate.py:162-172`). Editing
> `REQUIRED_COMPONENTS` alone would change nothing observable. Both mechanisms have to
> agree before an EU row exists, and the gate is the one to settle first.

`RHM.DE` is class `E`, so the gate refuses it under `eu_options_track: C`; if it somehow
got past, `S_O` is in its required set and it would be demoted anyway. The deeper problem
is that **no expression class in this system grades a shares-only position**: `V`/`E`
require an options chain, `P`/`S` avoid it but require `S_F` — which is now **permanently
n/a by declaration**, so those classes are permanently unreachable rather than temporarily
unsourced — and only `[V, E]` are enabled (`config/config.example.yaml:44`).

There is also a latent inconsistency: `RHM.DE` declares `permitted_instruments: [shares]`
while carrying `expression_class: E`, which demands options data for a position that cannot
use options.

So **A2 / Q2 should be re-asked, because its premise has changed.** It was decided as "keep
as context or drop" when the answer was *no data at any price*. After E1–E6 the answer would
be *everything except options*, which is a materially better argument for keeping them —
**but only if the gate lets the data be fetched at all.** Four paths, the first of which is
new and is the one that unblocks the rest:

0. **Let watchlist-bound EU names be fetched and scored anyway** *(added 2026-09-03)*. The
   gate's job is to decide what is *tradeable*; it currently also decides what is *knowable*,
   by short-circuiting the fetch. Separating those — pull and score a watchlist row, then let
   `S_O = n/a` demote it honestly — is what makes option 1 mean anything, and is the
   precondition for E5's acceptance criterion being testable live. It is a pipeline change
   (`pipeline.py:502`/`:532` iterate `accepted`), not a config one, and it has a cost: 4 more
   names × the per-ticker request count, against budgets that already ran out three times on
   2026-09-03. **Decide this before starting E2.**
1. **Accept Tier C.** `RHM.DE` becomes a well-informed watchlist row instead of an empty
   one. Cheapest — but **only reachable via option 0**, since without it the row stays
   empty no matter how good the mapping is. This is the correction that matters most in
   this section.
2. **Manual Eurex capture.** The schema (`schemas/eurex_options_manual_capture.csv`) and
   loader (`load_eurex_manual_options_capture`) already exist and have never been used;
   `data/manual/` does not exist. Unblocks `S_O` properly, at the cost of recurring manual
   capture.
3. **A shares-only expression class** requiring `{S_M, S_S}` but not `S_O`. This is a
   scoring-model change, not configuration: the measured sigma range, IV rank and event-day
   widening are all options-derived, so this decides that an idea can be graded without an
   implied distribution. It affects US names too.

~~**Recommendation: do E1–E6, then decide.** The decision is easier to make looking at a real
`RHM.DE` row with real price history and real news than it is in the abstract.~~

**Revised recommendation, 2026-09-03.** The original reasoning was sound and its premise was
false: E1–E6 do not produce a real `RHM.DE` row to look at, because the gate never lets one
be built (§1a). Revised order:

1. **E1 first, unchanged.** It is cheap, it is blocked by nothing, and it answers a question
   worth having either way: *do these four names have resolvable provider symbols at all?*
   If the answer for three of four is no, the rest of this file is moot and the A2 decision
   is easy.
2. **E6 next, also unblocked.** The EU preflight probe symbol is wrong today and fixing it
   costs one config line. It is the only ticket whose acceptance is observable now.
3. **Then decide option 0** — whether a watchlist row deserves a data pull. This is the real
   fork, and it is a pipeline and budget question, not a symbol-mapping one.
4. **E2–E5 only if option 0 is yes.** Otherwise they are correct, tested, and inert: the
   mapping would be exercised by unit tests and never by a run.

The honest summary is that this file solved the wrong half of the problem well. The symbol
research is good and still stands; the sequencing assumed a pipeline that fetches what it
watchlists, and it does not.

---

## 7. Documents to update when this lands

| File | Change |
|---|---|
| `docs/alternatives/pa5-eu-sources.md` | Add a dated banner: the options verdict stands, the "no EU data" conclusion is narrowed to "no EU *options* data" |
| `docs/SOURCE_STATUS.md` | New banner in the existing style — AV serves EU venue symbols, Finnhub serves EU issuers via US ADRs |
| `config/universe.example.yaml` | E5 — the mapping plus the struck probe table |
| `HANDOFF.md` | Q2 restated with its new premise; add the mapping to the wired-legs table |
| `provider-alternatives-wiring-tasks.md` | The EU row of the coverage matrix moves from "capture-gated" to "capture-gated for `S_O` only". Note that **PB4's EU remainder and A2 are still open** there, and Phase C has since run: `PC1-PF-12`…`PC1-PF-15` are the EU capture rows |
| `docs/alternatives/still-failing.md` | *(added 2026-09-03)* The Phase C ledger, and the current gate for this work. EU captures are `PC1-PF-12`…`PC1-PF-15`, open. If option 0 in §6 is taken, the four EU names become live rows and belong on the next regeneration |
| `config/candidates.example.yaml` | *(added 2026-09-03)* E5 — `ASML.AS` and `SIE.DE` mappings; D5 |
| `docs/alternatives/pa2-iv-history-and-chain-failover.md` | *(added 2026-09-03)* If E1 finds a resolvable US chain for ASML, record there that it was **rejected as the wrong instrument** (D4), so the next audit does not re-find it and read it as a win |
