# Documentation map

Documentation is split by **who reads it and what they do with it**.

| Directory | For | Contains |
|---|---|---|
| [`product/`](product/) | Anyone asking what the system is meant to produce | The report specification, its layout, and the gate policy |
| [`architecture/`](architecture/) | Anyone changing how it works | The design, run-health semantics, and every decision record |
| [`research/`](research/) | Anyone about to investigate a data source | Per-endpoint status and twenty per-source studies |
| [`operations/`](operations/) | Anyone running it | Local operation, the backfill, the request budget, deployment |
| [`archive/`](archive/) | Nobody, day to day | Finished and superseded documents, each explained in its index |

**Task documents are not here.** Work an agent executes lives in
[`tasks/`](../tasks/): the lane documents, the file-ownership map, the cross-lane register
and the verification results. The split is deliberate — an agent opening `tasks/` should
find only actionable work, and a reader opening `docs/` should never be handed a task list.

**Starting cold?** Read [`HANDOFF.md`](../HANDOFF.md) at the repository root. It holds the
traps and constraints that reading the code will not tell you.

---

## product/

| File | What it is |
|---|---|
| [`SPEC-graded-ideas-report.md`](product/SPEC-graded-ideas-report.md) | The specification for the graded report: component formulas, weights, tiers, letter bands. **Current** — carries the G1–G5 grading amendments |
| [`REPORT-LAYOUT.md`](product/REPORT-LAYOUT.md) | What the rendered report shows and why: conviction versus certainty, thesis versus data reading |
| [`GATE-POLICY.md`](product/GATE-POLICY.md) | Which candidates reach the report, and which setup types genuinely depend on a catalyst date |

## architecture/

| File | What it is |
|---|---|
| [`ARCHITECTURE.md`](architecture/ARCHITECTURE.md) | How the pipeline is put together |
| [`RUN-HEALTH.md`](architecture/RUN-HEALTH.md) | What makes a run `partial`. Every issue the pipeline can record, classified `normal` / `degraded` / `outage`, pinned by a test |
| [`decisions/`](architecture/decisions/) | Sixteen decision records, one per decision, with status and supersession. **Binding on the task lanes** |

## research/

| File | What it is |
|---|---|
| [`SOURCE_STATUS.md`](research/SOURCE_STATUS.md) | Per-endpoint state across every provider: `ok`, `paywalled`, `synthetic`, `browser_required`. Regenerated from credentialed deep preflight runs |
| [`alternatives/`](research/alternatives/) | Twenty studies, one per sourcing question. **Check here before investigating any data source** — the answer is often already written down, with the requests that produced it |

Two worth knowing about by name:

- [`historical-options-sources.md`](research/alternatives/historical-options-sources.md) —
  the survey that closed the backfill funding question. Answers Quiver, Tradier,
  MarketData.app, DoltHub and Polygon directly, each with the probe that settled it.
- [`q6-alpha-vantage-allocation.md`](research/alternatives/q6-alpha-vantage-allocation.md) —
  which legs the contended 25-request daily allowance should carry.

## operations/

| File | What it is |
|---|---|
| [`LOCAL-OPS.md`](operations/LOCAL-OPS.md) | Running the briefing locally, the scripts under `ops/`, and what a failed run looks like |
| [`IV-BACKFILL.md`](operations/IV-BACKFILL.md) | The volatility backfill tool: what it does, its vendor guard, and why it is not currently scheduled |
| [`DEPLOYMENT_OPTIONS.md`](operations/DEPLOYMENT_OPTIONS.md) | Hosting options, assessed. Reference only — the ship target is local |
| [`DEPLOY_FLY_IO.md`](operations/DEPLOY_FLY_IO.md) | One worked deployment path. Reference only, same reason |

The n8n workflow automations stay in [`workflows/`](../workflows/) beside the workflow JSON
files they document — separating them would leave both halves harder to use.

## archive/

Finished and superseded documents, about 3,600 lines. **Nothing there is current.**
[`archive/README.md`](archive/README.md) says, per document, what it was, when it closed and
what replaced it — read that rather than opening files speculatively.
