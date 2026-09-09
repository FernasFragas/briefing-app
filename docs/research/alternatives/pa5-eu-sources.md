# PA5 - Fetchable EU Sources

Research date: 2026-08-31.

**Verdict: reject for the load-bearing gap. No free API serves EU per-strike option chains
with open interest. The capture dependency stands, and the honest consequence is that EU
names are Tier C by construction.**

## Premise check

The premise was corrected once already (FCA is fetchable, so it belongs to PB5 wiring, not to
research) and that correction holds. What remains genuinely capture-gated:

| Source | Status | Needed for |
|---|---|---|
| Eurex per-strike chains | `manual_required` | `S_O` for RHM.DE, LDO.MI, ASML.AS |
| Bundesanzeiger net shorts | `browser_required` | German short disclosure |
| EU OAM MAR Art. 19 / major holdings | `browser_required` | `S_I` / `S_F` for EU names |

`data/manual/` still does not exist — no capture has ever been dropped.

## Candidates

| Candidate | What it actually serves | Verdict |
|---|---|---|
| **Eurex reference data API** | Free, GraphQL/JSON, but **reference data only** — contract specifications, not quotes, not open interest, not per-strike prices | **Reject.** It answers "what contracts exist", and the gap is "what are they worth and how much OI". Different question. |
| **ESMA registers** | Machine-to-machine web services exist, but the short-selling dataset is the **exempted-shares register** (~160k exemption records) — a list of shares *out of scope* of SSR disclosure | **Reject.** Not net short positions. An exemption list cannot substitute for a disclosure feed. |
| `esma_data_py` | Official ESMA Python package wrapping the register downloads | **Reject** for this gap — a convenient client for the same wrong dataset. Worth remembering if an ESMA dataset ever becomes relevant. |
| Euronext Data Shop delayed API | Delayed data exists as a **commercial data-shop product** | **Reject** — paid, and licensing for redistribution is the restrictive kind. Spec only if EU coverage ever justifies a purchase. |
| National OAMs beyond Bundesanzeiger | Each member state publishes separately; no pan-EU API exists | **Reject as a class** — the per-country integration cost is unbounded for a universe with two EU names. |

## The structural finding

There is no pan-EU equivalent of CBOE's unauthenticated chain endpoint. EU options data is
sold, not published: Eurex gives away *reference* data and charges for *market* data. That is
a market-structure fact, not a gap in the search, and it will not change because a future
audit looks again.

This is worth recording plainly because the project's own config already anticipated it:
`eu_options_track: C` with the note *"C nothing available -> S_O = n/a, so V/E on non-US names
are demoted."* The research confirms the config was right.

## Consequence, and what it implies for the universe

Both EU names in the universe are Tier C **by construction**, not by accident:

- `S_O` is `n/a` — no chain, and `REQUIRED_COMPONENTS` makes `S_O` required for both V and E.
- Class `P` would avoid `S_O`, but it is not in `enabled_expression_classes`, and it requires
  `S_I` and `S_F`, which have no EU source either (`browser_required`).

So RHM.DE and LDO.MI can never exceed Tier C, and under the grading design that caps them at a
`C` grade permanently. They will appear in the report every day as watchlist rows with a
named reason — which is honest, and also arguably noise.

**That is a universe decision, not a sourcing one**, and it belongs with **A2**: either accept
permanent Tier C EU names as context, or drop them. Recording it here so the next audit does
not re-run this search expecting a different answer.

## What would reopen this

Only a change in market structure or entitlement, cited with a date:

1. Eurex publishing delayed *market* data free (not reference data).
2. A national OAM exposing a real API for MAR Art. 19 / major holdings.
3. A decision to pay for an EU chain, at which point this becomes a cost question with a
   specced monthly figure rather than a search.

Per PC2, anti-bot and licensing rejections above are **not** re-litigated at the next audit.

## Evidence

- Registry statuses (`manual_required`, `browser_required`) from the 2026-08-31 preflight.
- Universe composition verified 2026-08-31: venues XETRA 3, BORSA_ITALIANA 1, EURONEXT 1,
  and zero UK listings.
- `eu_options_track: C` and `enabled_expression_classes: [V, E]` read from
  `config/config.example.yaml`.

Sources: [Eurex free reference data API](https://www.eurex.com/ex-en/data/free-reference-data-api), [ESMA databases and registers](https://www.esma.europa.eu/publications-and-data/databases-and-registers), [ESMA SSR exempted shares dataset](https://opendata.best/catalog/eu_esma_ssr_exempted_shares), [Euronext delayed data](https://live.euronext.com/en/datashop/delayed-data)
