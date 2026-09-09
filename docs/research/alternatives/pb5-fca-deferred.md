# PB5 (FCA half) - Deferred, With Reason

Date: 2026-08-31.

Scope: the FCA half of PB5 in `docs/archive/provider-alternatives-wiring-tasks.md`, which reads:
"Wire FCA shorts into the pipeline - it is fetchable and `ok` today, only unconsumed, so it
does not wait on a second EU source."

**Verdict: correct on the facts, wrong on the benefit. Deferred until the universe holds a
UK-listed name.**

## Premise check

| Claim | Verified | Finding |
|---|---|---|
| FCA short positions is fetchable without key or session | ✅ | Registry entry `fca.fca_short_positions`, plain XLSX, `probe_enabled: true`, `ok` on the 2026-08-31 preflight. |
| It is unconsumed by the pipeline | ✅ | `grep -c fca src/briefing_app/pipeline.py` → 0. |
| "The loaders are already written" | ❌ | That refers to the **manual** EU loaders in `providers/manual.py`. There is no FCA client, no XLSX parser and no normalizer - `grep -rn fca src/briefing_app/providers/*.py` returns nothing. Wiring it is a build, not a connection. |
| It would benefit the current universe | ❌ | **The decisive one.** See below. |

## Why it is deferred

The FCA register covers **UK** issuers. The configured universe contains none:

```
venues:       ARCA 1, NASDAQ 28, NYSE 3, XETRA 3, BORSA_ITALIANA 1, EURONEXT 1
UK-listed:    NONE
```

The five EU names are German (`RHM.DE`, XETRA), Italian (`LDO.MI`) and Dutch (Euronext).
Every one of them is disclosed to its own national OAM, not to the FCA. Wiring FCA today
would download a 3.1 MB spreadsheet on every run and match zero rows.

Building a client, an XLSX parser, a normalizer, a probe and tests for a source that cannot
match anything in the universe is machinery that would be maintained without ever being
exercised - and an unexercised path is exactly how the SEC EDGAR normalizer became 19
undefined helpers that still looked implemented.

## What would reopen it

Any of:

1. **A UK name enters the universe** - an LSE listing makes this immediately worth wiring,
   and the registry entry is already probed and `ok`.
2. **Bundesanzeiger or another national OAM becomes fetchable** (PA5). The German register
   is what `RHM.DE` actually needs, and an FCA parser is a reasonable template for it, so
   the two are better built together than apart.

## Cost when reopened

Small and known: an `FcaClient` on the existing `base.py` contract, an XLSX reader
(`openpyxl` is already available via pandas), a normalizer to the existing
`ShortInterestSnapshot`, and pipeline consumption on the `short_interest` leg behind FINRA
for EU/UK names. No new model, no credential, no budget line.
