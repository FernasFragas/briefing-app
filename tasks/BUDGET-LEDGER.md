# Live provider budget ledger

> **A lane that has not claimed its allowance here has not been granted one.** Append a
> claim before any live provider request; do not edit or delete an existing claim or outcome.

This is the D16 record for the shared Alpha Vantage free allowance: 25 requests per Lisbon
day. Provider clients keep the factual counter in `data/provider_budget/<provider>/`; this
ledger records which lane has committed the still-available part before it spends.

## Claims

Append one row before spending. `kind` is `lane` for a post-daily-run lane request, or
`daily-run` only for Lane O's owner-authorised daily briefing. Keep the claim ID unique.

| Claim ID | Date | Lane | Provider | Requests | Kind | Purpose |
| --- | --- | --- | --- | ---: | --- | --- |

## Outcomes

After the claimed command finishes, append an outcome. `Requests spent` is the number the
provider counter increased for that command, not a forecast. Multiple outcomes may refer to
one claim, but their total may not exceed the claimed number.

| Claim ID | Requests spent | Result |
| --- | ---: | --- |

## Worked example (not an active claim)

The following shows the two append-only rows for a hypothetical provider check. It is an
example only: the checker reads only the `Claims` and `Outcomes` sections above.

| Claim ID | Date | Lane | Provider | Requests | Kind | Purpose |
| --- | --- | --- | --- | ---: | --- | --- |
| 2026-01-15-example-1 | 2026-01-15 | Example | alpha_vantage | 2 | lane | Verify a documented endpoint after the daily run |

| Claim ID | Requests spent | Result |
| --- | ---: | --- |
| 2026-01-15-example-1 | 2 | completed; validation passed |
