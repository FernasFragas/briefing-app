# Decision records

Every product and architecture decision taken on this project, one file per decision.

**These are binding on the task lanes.** A lane that believes a decision is wrong records
the objection in [`tasks/CROSS-LANE.md`](../../../tasks/CROSS-LANE.md); it does not act
against it. A decision is read-only once work starts against it.

**Numbering follows the original `D` numbers.** Decision `D13` is file `0013`. This is
deliberate: the task documents, the cross-lane register and several source comments cite
decisions as `D13`, and renumbering would break every one of those citations for no gain.

## Index

| # | Decision | Round | Status |
|---|---|---|---|
| [0001](0001-ship-target-local-single-reader.md) | Ship target: local, single reader | 1 | Accepted |
| [0002](0002-grading-scale-align.md) | Grading scale: ALIGN — drop the probability term | 1 | Accepted |
| [0003](0003-volatility-warmup-backfill-from-historical-chains.md) | Volatility warm-up: backfill from historical chains | 1 | **Superseded by 0013** |
| [0004](0004-inferred-catalyst-dates-may-score-not-anchor.md) | Inferred catalyst dates may score, may not anchor a trade | 1 | Accepted |
| [0005](0005-score-ceiling-tier-caps-displayed-letter.md) | Score ceiling: the tier caps the displayed letter | 1 | Accepted |
| [0006](0006-index-funds-move-to-market-context.md) | Index funds move to market context | 1 | Accepted |
| [0007](0007-european-names-inactive.md) | European names marked inactive | 1 | Accepted |
| [0008](0008-agent-arrangement-one-tree-file-ownership.md) | One working tree, strict file ownership | 1 | Accepted |
| [0009](0009-degraded-run-reports-partial.md) | A degraded run must report itself as degraded | 2 | Accepted |
| [0010](0010-conviction-and-certainty-as-two-measurements.md) | Conviction and certainty as two labelled measurements | 2 | Accepted |
| [0011](0011-declared-thesis-beside-data-reading.md) | Declared thesis shown beside the data's reading | 2 | Accepted |
| [0012](0012-backfill-funding.md) | Backfill funding | 2 | **Closed by 0013** |
| [0013](0013-volatility-threshold-ten-sessions.md) | Volatility baseline: threshold 20 → 10 sessions | 3 | Accepted |
| [0014](0014-vendor-consistency-measure-before-splice.md) | Vendor consistency: measure the gap before any splice | 3 | Accepted |
| [0015](0015-report-split-supported-and-contradicted.md) | Report split: supported and contradicted theses | 3 | Accepted |
| [0016](0016-live-run-budget-ledger.md) | Live runs: agents spend inside an enforced budget | 3 | Accepted |

## The three rounds

Each round was opened by a problem that only became visible once the previous round's work
was in place. That sequence is the most useful thing this index records.

- **Round 1 (0001–0008), 2026-09-07.** Taken against live run `daily-2026-09-06-e270378b`.
  Grading, presentation, the universe, and the local ship target.
- **Round 2 (0009–0012), 2026-09-07 evening.** Opened by run `daily-2026-09-07-f1b0d2e1`,
  which reported `succeeded` having reached no provider at all. Honest run status, the two
  grade scales, thesis-versus-data, and the backfill funding question.
- **Round 3 (0013–0016), 2026-09-08.** Taken against the measured state of the local store.
  Closes the funding question without paying, splits the report, and puts live spending
  under a ledger.

## Earlier decisions — the Q series

Six decisions predate this record and are numbered `Q1`–`Q6`. They are **closed**, and
their reasoning lives in [`docs/archive/POST-P3-DECISIONS.md`](../../archive/POST-P3-DECISIONS.md),
which carries three stacked supersession notices of its own — read it as history, not as
current guidance.

They are not renumbered into this series because their content is heavily superseded and
because `Q4` in particular is still cited by that name in `pipeline.py`.

| Q | Decision | Where it still binds |
|---|---|---|
| Q1 | `executive_tone` recorded permanently `n/a`, its weight redistributed | `components/sentiment.py` |
| Q1b | The analyst-news leg is capped at its own share; news alone cannot constitute the leg | `components/sentiment.py` |
| Q2 | European names dropped from scoring — later restated as 0007 | `config/universe.example.yaml` |
| Q3 | `retail_momentum` capped at its nominal weight | `components/sentiment.py` |
| Q4 | `S_F` (institutional flow) declared permanently `n/a` | `pipeline.py`, `DECLARED_UNSCORABLE_COMPONENTS` |
| Q5 | Grade band edges left alone | `dashboard/grading.py` |
| Q6 | Alpha Vantage allocation — premise later withdrawn | [`q6-alpha-vantage-allocation.md`](../../research/alternatives/q6-alpha-vantage-allocation.md) |

## Writing a new one

Copy the shape of the most recent file. A record is worth keeping only if it states:

- **the decision**, in one paragraph, in plain words;
- **the evidence it was taken on** — a measurement, with the run or the query that produced
  it, not an impression;
- **what was rejected and why**, because that is what stops the same option being
  re-proposed in three weeks;
- **the cost that was accepted**, stated plainly. Every decision here has one, and the
  records that name it have aged better than the records that do not.
