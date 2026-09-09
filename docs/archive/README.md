# Archive — finished and superseded documents

**Nothing in this directory is current. No agent should act on any of it.**

These files are kept because several of them record *why an approach was rejected*, and
that reasoning is the most expensive thing to reconstruct — this project has already
re-investigated the same Alpha Vantage question twice for want of it. Read them as history.

Each entry below says what the document was, when it closed, and what replaced it. If the
answer you want is not in the "replaced by" column, the document is probably not worth
opening.

---

## The build plans — delivered

### `options-briefing-system-plan.md` — 608 lines
The original system plan. Objective, architecture, component formulas, and the phased build
for the whole application. Written before any code existed; everything it specifies has
since shipped or been deliberately dropped.

**Replaced by** [`docs/architecture/ARCHITECTURE.md`](../architecture/ARCHITECTURE.md) for
the design, and [`docs/product/SPEC-graded-ideas-report.md`](../product/SPEC-graded-ideas-report.md)
for the scoring formulas as they actually stand.

**Still worth opening for:** the original objective and the reasoning behind the component
split into `S_O`, `S_M`, `S_S`, `S_I` and `S_F`. Nothing else has restated that from
scratch.

### `implementation-tasks.md` — 575 lines
The parallel task breakdown derived from the plan above. The first use of the
one-tree-with-file-ownership arrangement that the lane documents still use today.

**Replaced by** [`tasks/README.md`](../../tasks/README.md) and the lane documents.

---

## The provider work — complete

### `provider-alternatives-wiring-tasks.md` — 278 lines
The audit: the provider-readiness matrix, the coverage gaps, and the research verdicts for
every source considered. The *why*.

### `provider-alternatives-implementation.md` — 420 lines
The tickets derived from that audit. The *how*. Notable for locking the rule that governed
every provider decision until 2026-09-08: **free tiers only, and a ticket that finds a paid
option better must stop and ask.**

**Replaced by** [`docs/research/SOURCE_STATUS.md`](../research/SOURCE_STATUS.md) for the
current per-endpoint state, and [`docs/research/alternatives/`](../research/alternatives/)
for the per-source studies, which are the living continuation of this work.

**Still worth opening for:** the coverage matrix, which is the only place the whole provider
surface is laid out side by side.

### `eu-coverage-implementation.md` — 494 lines
European symbol mapping. Specified in full, **never started**, and blocked by a premise the
file itself did not check — its own 2026-09-03 review banner says tasks E1 to E6 would have
produced no observable effect on a live run.

**Superseded by** decision [0007](../architecture/decisions/0007-european-names-inactive.md),
which marks the European names inactive rather than building coverage for them.

**Still worth opening for:** the review banner. It is a good worked example of a plan
invalidated by a premise nobody checked, which is the failure this project keeps guarding
against.

---

## The decision and defect records — closed

### `POST-P3-DECISIONS.md` — 323 lines
The Q1–Q6 decisions, taken 2026-09-02 against the first working live run. **Carries three
stacked supersession notices of its own**, dated 09-02, 09-03 and 09-06, each correcting
claims made below it.

**Read the banners before the body.** The decisions it reaches still hold and are summarised
in the [decision index](../architecture/decisions/README.md#earlier-decisions--the-q-series);
the measurements it reports do not.

**Still worth opening for:** section 1, which diagnoses why the macro component failed for
all 24 names — a sector-name mismatch between two configuration files. It is the clearest
example in the repository of a scoring failure with a one-string cause.

### `still-failing.md` — 294 lines
The `PC1` defect ledger, generated 2026-09-03 from a preflight report and a live run. Every
Phase-C task had to cite an open row here.

**Replaced by** [`docs/architecture/RUN-HEALTH.md`](../architecture/RUN-HEALTH.md), which
classifies every failure the pipeline can record, and by
[`docs/research/SOURCE_STATUS.md`](../research/SOURCE_STATUS.md) for endpoint state.

**Note:** `tests/test_provider_resilience.py` cites rows `PC1-RAW-15` through `PC1-RAW-19`
from this file in its module docstring. That citation is why this file is archived rather
than deleted.

### `handoff-2026-09-03-full.md` — 892 lines
The complete session handoff as it stood on 2026-09-09, before it was reduced to an
onboarding page. Six documents in one: system state, work queue, closed phase history,
questions and answers, non-obvious constraints, commands, and a document map.

**Replaced by** [`HANDOFF.md`](../../HANDOFF.md) at the repository root, which keeps only
what a fresh session cannot infer from the code.

**Still worth opening for:** the `N6`, `N7` and `N8` grading investigations in section 2.
They record six alternative scoring formulas computed on real data and rejected, with the
numbers. Decision [0002](../architecture/decisions/0002-grading-scale-align.md) is the
conclusion; this is the working.
