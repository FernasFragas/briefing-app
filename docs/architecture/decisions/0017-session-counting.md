# 0017 — How the volatility baseline counts sessions

| | |
|---|---|
| **Status** | **Accepted** 2026-09-09. Drafted as PROPOSED; all three open questions answered by the owner the same day. Implementation not started and not yet owned. |
| **Date** | 2026-09-09 |
| **Round** | 3 follow-up (ship audit, Prompt B) |
| **Relates to** | 0013 (the floor of ten), 0003 and 0014 (the failure class this repeats) |

> **The decision, in one paragraph.** The volatility baseline counts **distinct exchange
> sessions**, not stored snapshot dates. Each chain's own `data.last_trade_time` is persisted
> on the stored row and history is de-duplicated by `(ticker, session)` on read — option B2
> below. When two captures describe the same session, **the latest capture wins**. All three
> stored rows are kept; nothing is deleted. The accepted cost is that the first provisional
> reading moves from Friday 18 September to **Monday 21 September**. See
> [What the owner decided](#what-the-owner-decided-2026-09-09) for the exact wording and the
> one judgement call left inside it.

---

## Vocabulary, spelled out once

| Term | What it means here |
|---|---|
| **IV — implied volatility** | How much movement the options market is pricing into a stock. Higher means the market expects a bigger move. |
| **ATM — at the money** | The option whose strike price sits closest to the current share price. `iv_atm` is the implied volatility of that option. |
| **OI — open interest** | The number of option contracts currently outstanding. `pc_ratio_oi` is puts divided by calls on that measure. |
| **OPRA — Options Price Reporting Authority** | The US industry feed that consolidates options quotes and trades from every exchange. CBOE's delayed chain is derived from it, which is why "CBOE data" and "exchange data" are not independent of each other. |
| **Exchange session** | One actual trading day on the market. Friday 4 September is one session no matter how many times we read it. |
| **Snapshot date** | The calendar date the briefing was run and a row was stored. Not the same thing as a session. |
| **Percentile / rank** | Where today's reading sits inside its own history. "IV rank 80" means today is higher than 80% of the stored history. |
| **Provisional** | The label 0013 requires on any reading computed over 10–19 observations. |

---

## The decision to be taken

The baseline counts **stored snapshot dates**. It should arguably count **distinct exchange
sessions**. They are not the same thing, and today they differ for 17 of the 18 report
tickers.

## The problem, with the evidence

**The limitation is already written down and nothing enforces it.**
`docs/architecture/VOLATILITY-BASELINE.md` line 43 says: *"Stored run dates are not
necessarily distinct exchange sessions: weekend and holiday runs can capture the same
trading session."* That sentence is correct and no code acts on it.

**Where the counting happens.** `StorageRepository.option_metric_history`
(`storage.py:505-539`) selects on `snap_date` with no trading-day filter and no
de-duplication. `pipeline.py:2798` then applies the floor as `if len(series) < min_sessions`,
where `series` is the list of non-null values — that is, a count of **rows**. The same
number is published as `{"sessions": len(series)}` and rendered as
*"Provisional — N stored sessions"*. **The published field is already named `sessions` and
already counts rows**, so the page states something that is not true today.

**The guard that exists does not guard this.** `is_market_day` is defined at
`pipeline.py:511` and called in exactly one place, `pipeline.py:628`, to decide whether to
run at all — and `--force` bypasses it. It never touches history. Worse, its `holidays`
parameter is never supplied by any caller and **no holiday calendar exists anywhere in the
repository** (verified: the only matches for `holidays` in `src/`, `config/` and `ops/` are
the parameter's own definition). So `is_market_day(2026-09-07)` returns `True` — Labor Day
passed the guard as a normal market day.

### What the store actually holds

Verified 2026-09-09, offline, by reading `data/raw/cboe/delayed_options_chain/<run-date>/<TICKER>.json`
and matching each row against its chain's own `data.last_trade_time`:

| Stored snapshot date | Day | Tickers | Exchange session(s) actually captured |
|---|---|---:|---|
| 2026-09-03 | Thursday | 23 | **21 tickers → session 09-03; 2 tickers (FDX, LMT) → session 09-02** |
| 2026-09-06 | Sunday | 18 | all 18 → session **09-04** |
| 2026-09-07 | Monday, Labor Day | 18 | all 18 → session **09-04** |

**Three snapshot dates, and every ticker has only two distinct exchange sessions** — 09-03
and 09-04 for sixteen of them, 09-02 and 09-04 for FDX and LMT. Across the whole universe
three sessions appear (09-02, 09-03, 09-04), but **no single ticker has more than two**, and
the baseline is computed per ticker. **4 September is counted twice for all 18.**

### The detail that kills the obvious fix

On 2026-09-03, a normal trading day, **FDX and LMT carried a stale chain** — their reads
describe the 09-02 session. A calendar filter would not have caught either, because 09-03
is a perfectly good trading day.

**And it recurs.** The 2026-09-04 capture shows FDX stale again, carrying session 09-03
while the other 20 tickers carry 09-04. So this is a per-ticker property of the delayed
feed, not a one-off. **Any rule that works has to key on each chain's own `last_trade_time`,
per ticker — never on the run date.**

### Where session identity lives today: nowhere in the database

This is the fact that sizes every option below, and it was not obvious.

- `daily_snapshot` has no session column. Its `raw` payload holds only `components` and
  `scoring`; the per-component `as_of` is the **run date** (`S_O as_of = 2026-09-07` on a
  row whose chain is session 09-04).
- `evidence_ledger.as_of` is the **capture timestamp, not the session**. FDX on run 1 records
  `2026-09-03 10:02:55` for a chain whose last trade was 09-02.
- The cause is one line: `normalizers.py:207` reads
  `as_of = parse_datetime(payload.get("timestamp") or data.get("last_trade_time"))`. CBOE
  always supplies `timestamp`, so the capture time always wins and **the session is
  discarded at normalization**.

The true session survives only in the raw JSON files under `data/raw/cboe/`. Those files are
present for all three stored dates, so the three existing rows **can be repaired offline at
zero cost** — but nothing in the database can currently tell two reads of one session apart.

## Why this matters, stated once

The floor of ten is the headline of 0013. If duplicate reads of one session count toward it,
the floor is reached early and the percentile is computed over a series containing repeated
observations. A rank is a *position within a distribution*; duplicating a point moves that
position. The number would publish, look settled, and mean something other than what the
document says it means. That is the failure class 0003 and 0014 exist to prevent — this time
**inside one vendor rather than between two**.

---

## The options

Every count below is measured from the real store, not illustrated. Publication dates assume
the briefing runs **every weekday from today, 2026-09-09 (Wednesday)**, one new session per
run, and no US market holiday falls before 2026-09-30 (none does). History excludes today's
own row, so a reading publishes on the first run that already has ten prior observations.

**Reference schedule:** run 1 = Wed 09-09, run 8 = **Fri 09-18**, run 9 = **Mon 09-21**,
run 10 = Tue 09-22, run 11 = Wed 09-23.

### Option A — leave it: count snapshot dates, document the caveat harder

1. **Stored series today.** For 15 of 18 tickers, `iv_atm` = **3 observations**; all 18
   tickers have `pc_ratio_vol` and `pc_ratio_oi` = **3 observations**. Exceptions: FDX has
   **0** implied-volatility observations (null on all three dates), JPM has **1**, LMT has
   **1**.
2. **First provisional rank.** Run 8 — **Friday 2026-09-18**.
3. **What the number would mean.** "Where today sits among the last ten stored readings,
   one of which is a repeat of another." For the first published rank, 4 September would
   occupy 2 of the 10 points.
4. **The three stored rows.** All kept, unchanged. No data cost.
5. **Good:** zero work, earliest publication, nothing can break. **Bad:** the page prints
   *"N stored sessions"* where N counts rows, so the label is false whenever a weekend,
   holiday or stale chain is in the window. The error is invisible to the reader and to us.
6. **Implementation:** none. Documentation only, in files this lane may write.

### Option B — de-duplicate on the chain's own `last_trade_time`, per ticker

Two sub-forms, and they are not equivalent.

- **B1 — de-duplicate at query time by re-reading the raw CBOE files.** No schema change,
  but it couples the history query to the raw file tree. Rejected as **strictly worse than
  B2**: the raw files are overwritten by a later capture on the same date (the evidence
  ledger holds two different `as_of` values for the 09-03 AAPL file, 14:04:14 and 17:14:21,
  proving overwrite happens), they are not part of the database's integrity guarantees, and
  a purged or archived raw tree would silently change published history.
- **B2 — persist the session on the row at write time, then de-duplicate on read.** This is
  the real option B.

1. **Stored series today.** 15 of 18 tickers: `iv_atm` **3 → 2**. All 18 tickers:
   `pc_ratio_vol` and `pc_ratio_oi` **3 → 2**. FDX implied volatility stays **0**; JPM stays
   **1**; LMT stays **1** (its single reading is the 09-06 row, which is a valid read of the
   09-04 session and is *kept*).
2. **First provisional rank.** Run 9 — **Monday 2026-09-21**. One run later than A.
   JPM and LMT implied volatility: run 10, Tue 09-22. FDX implied volatility: not before
   run 11, Wed 09-23, **and possibly never — see the open unknown below**.
3. **What the number would mean.** "Where today sits among the last ten *distinct trading
   days* we have readings for." That is what a reader already assumes it means.
4. **The three stored rows.** All three **kept**. Nothing is dropped. The duplicate is
   resolved at read time, so the underlying evidence stays auditable — which matters, because
   the two 09-04 reads disagree with each other by 146% on open interest (recorded in
   `docs/research/alternatives/vendor-consistency.md`).
5. **Good:** it is the only option that fixes the actual defect, including the per-ticker
   stale chains that no calendar can catch; it destroys no data; and it makes the published
   `sessions` label true. **Bad:** it is the largest change of the five; it needs a tie-break
   rule when two rows share a session (see the open question); and it delays first
   publication by one run.
6. **Implementation and ownership.** Needs (a) the session persisted — a `daily_snapshot`
   column or a `raw` field, written from `data.last_trade_time`; (b) a one-time offline
   repair of the three stored rows from the raw files, which are present; (c) de-duplication
   in `option_metric_history`. **This touches `src/briefing_app/storage.py`, which NO lane
   owns this round**, and `pipeline.py`/`normalizers.py`, which Lane K owns. It cannot be
   done without a cross-lane entry assigning ownership. Rough size: small-to-moderate — one
   migration, one query change, one write-path change, and tests. The repair script is a
   handful of lines because the raw files are already on disk.

### Option C — refuse to store a snapshot whose session is already stored for that ticker

1. **Stored series today.** Unchanged: **3 observations**, because the rows already exist.
   C only governs future writes.
2. **First provisional rank.** Run 8 — **Friday 2026-09-18** — *with the duplicate still
   inside the window*. Only if C is paired with a one-time cleanup does it become run 9,
   Monday 09-21.
3. **What the number would mean.** Going forward, "ten distinct sessions". For the first
   several weeks, "ten stored rows, two of which are the same day" — the two readings differ,
   so the flaw is live, not theoretical.
4. **The three stored rows.** Kept as-is if C is write-only; if paired with cleanup, **one
   row is deleted**. Deleting the 09-07 row would discard the *later* read of 09-04 — and
   the two reads disagree materially, so deletion destroys evidence that the vendor-consistency
   record currently relies on. **That is a real cost and it is why C-with-cleanup is worse
   than B2, which keeps both rows and simply stops counting one.**
5. **Good:** conceptually simple, and it makes the store itself honest rather than fixing
   history at read time. **Bad:** it does nothing about the rows already stored unless it
   deletes them; it silently discards a legitimately captured reading whenever a stale chain
   repeats a session, so a run can produce nothing and look fine; and it needs the same
   session-persistence work as B2 anyway.
6. **Implementation:** same prerequisite as B2 (session must be known at write time), plus a
   write-path refusal. Same ownership problem. Comparable size, minus the read-side change.

### Option D — filter history to exchange trading days by calendar

**This is the option the evidence rules out, and it is worth being explicit about why,
because it is the intuitive fix.**

1. **Stored series today**, using the shipped `is_market_day` (weekday test, no holiday list):
   09-06 (Sunday) is dropped, **09-07 (Labor Day) is kept** because it is a Monday. Result:
   `pc_ratio_vol` and `pc_ratio_oi` = **2** for all 18 tickers — the right number by
   accident, since it happens to keep exactly one of the two 09-04 reads. But **LMT's only
   implied-volatility observation is destroyed**: it lives on the 09-06 row, a perfectly
   valid read of the Friday session that happens to have been captured on a Sunday. LMT goes
   **1 → 0**.
   With a *proper* holiday calendar added, 09-07 is dropped too and **every ticker falls to 1
   observation**, losing the 09-04 session entirely.
2. **First provisional rank.** Run 9, Mon 09-21 for the put/call readings; LMT implied
   volatility slips to run 11, **Wed 09-23**. With a real holiday calendar, run 10 (Tue
   09-22) across the board.
3. **What the number would mean.** "Where today sits among the last ten readings taken on
   weekdays" — which is a statement about *when we looked*, not about *what we looked at*.
4. **The three stored rows.** Kept in the database, but one or two are **excluded from every
   future calculation**. Real data captured at real cost stops counting.
5. **Good:** no schema change; uses a function that already exists. **Bad:** it is wrong in
   both directions at once. It **discards valid data** (a weekend capture of Friday's session
   is good data) and it **fails to catch the actual error** (FDX and LMT on 09-03 were stale
   on a normal trading day, twice). It also depends on a holiday calendar that does not
   exist and would have to be sourced and maintained.
6. **Implementation:** small, and that cheapness is the trap. **Recommend discarding: D is
   strictly worse than B2** — it costs data B2 keeps, and it misses errors B2 catches.

### Option E — raise the floor to compensate for expected duplication

1. **Stored series today.** Unchanged at **3** rows; only the threshold moves.
2. **First provisional rank.** Depends entirely on the compensation chosen: floor 11 → run 9
   (Mon 09-21); floor 12 → run 10 (Tue 09-22); floor 13 → run 11 (Wed 09-23). To *guarantee*
   ten distinct sessions at the observed duplication rate — **3 of 8 runs so far landed on
   non-trading days (30 Aug Sunday, 6 Sep Sunday, 7 Sep Labor Day), 37.5%** — the floor would
   need to be about **16**, which publishes on run 14, **Mon 2026-09-28**.
3. **What the number would mean.** "Where today sits among the last N stored readings, some
   unknown number of which are repeats." The rank is still computed over duplicated points;
   only the sample is bigger.
4. **The three stored rows.** All kept, unchanged.
5. **Good:** a one-line configuration change (`self_built_series_min_sessions`), no new
   concepts. **Bad:** it treats a correctness defect as a sample-size problem. The
   duplication rate is not a constant — it is a function of the owner's manual run cadence,
   so any compensating number is a guess that silently goes wrong when the cadence changes.
   And it costs *more* delay than fixing it properly: a floor of 16 publishes a week later
   than B2's Monday 21 September, and still publishes a rank over a series with repeats.
6. **Implementation:** trivial — `config/config.example.yaml`, Lane K's file. But it buys the
   wrong thing.

### Option F — disclose rather than fix: publish both counts

Not in the original list; added because it is the cheapest honest answer and the project
already uses this pattern.

1. **Stored series today.** Unchanged at **3** rows, of which 2 distinct sessions.
2. **First provisional rank.** Run 8 — **Friday 2026-09-18**, same as A.
3. **What the number would mean.** The page would say something like *"10 readings over 8
   sessions"* and force the provisional marker whenever the two counts differ. The reader is
   told exactly what they are looking at.
4. **The three stored rows.** All kept, unchanged.
5. **Good:** it makes the existing false label true at low cost, it is consistent with 0013's
   principle that a limitation must be visible rather than hidden, and it composes with any
   later fix. **Bad:** it discloses the defect instead of correcting it. The headline
   percentile is still computed over duplicated points, and a reader who acts on the number
   rather than the footnote is still misled. **It needs the same session-persistence work as
   B2 to know the second number at all** — which is most of B2's cost for less of B2's
   benefit.
6. **Implementation:** session persistence (as B2), plus a metadata field and a render change
   in Lane L's files. Moderate.

---

## What I do not know, stated rather than hidden

- **Whether FDX will ever produce an implied-volatility reading.** Its `iv_atm` is null on
  all three stored dates. Three attempts is not proof of a permanent gap, and I have not
  diagnosed the cause. Under every option above, FDX's IV rank publishes late or never.
- **Whether today's run captures today's session.** On trading days the pattern has held —
  the 09-03 capture at 17:14 UTC carried a 09-03 12:59 last trade — but FDX broke it twice.
  The projections assume one new session per weekday run for well-behaved tickers; a stale
  chain pushes that ticker back by one run each time it occurs.
- ~~**The right tie-break when two rows share a session.**~~ **Answered by the owner on
  2026-09-09: keep the latest.** Left in place because the reasoning still matters — this was
  not settleable from the evidence, and the record should show that it was decided rather
  than derived. For AAPL the two 09-04 reads differ by 146% on the put/call open-interest
  ratio, and for LMT the earlier read has an implied-volatility value while the later one
  does not. See [What the owner decided](#what-the-owner-decided-2026-09-09), which also
  records how the remaining ambiguity in "the latest" was resolved.
- **Why the repeated captures disagree at all.** Still not diagnosed. The 09-04 session is
  read twice, a day apart, and returns materially different volume and open interest — 146%
  apart for AAPL, roughly 490-fold for LMT's open-interest ratio. Whether that is late
  OPRA-derived settlement data, a changing contract universe, or something else is unknown,
  and this decision does not depend on the answer: it de-duplicates the reads either way.
  It does mean the winning capture is not demonstrably the *correct* one, only the later one.
- **Whether other providers have the same problem.** I examined the CBOE options chain only.
  The macro leg is already known to carry a related date trap — a reading is dated by the
  period it measures rather than by its release, recorded as trap 8 in `HANDOFF.md` — but I
  did not audit it here, and this record makes no claim about it.

---

## Recommendation

*Written before the owner answered; retained unchanged as the reasoning the decision was
taken on. It was accepted in full — see the next section.*

**Adopt option B2: persist each chain's own `last_trade_time` on the stored row, and
de-duplicate the history by (ticker, session) when reading it.** Keep all three stored rows;
repair their session values offline from the raw CBOE files already on disk.

The cost, stated in the same breath: **first publication moves from Friday 18 September to
Monday 21 September — one extra run, three calendar days** — and it requires writing to
`src/briefing_app/storage.py`, which no lane owns this round, so ownership must be assigned
before anyone touches it. It is also the largest of the five changes.

It is the only option that survives the FDX and LMT evidence. A calendar cannot see a stale
chain; a bigger floor cannot either; and disclosure tells the reader about a defect we could
instead remove. Options D and E are recommended for **rejection** on the evidence above — D
because it destroys valid data while missing the real error, E because it treats a
correctness defect as a sample-size problem and costs more delay than the fix.

## What the owner decided, 2026-09-09

Three questions were put to the owner and all three were answered on the day this record was
drafted.

1. **"Fix first, publish 21 Sep"** — accept the one-run delay rather than publish a rank over
   a series containing a repeated session. This adopts **option B2**.
2. **"Trading days only from now on"** — the briefing will not deliberately be launched on
   weekends and holidays.
3. **"Keep the latest"** — when two captures describe the same exchange session, the later
   capture is the one that counts.

**Answer 2 reduces the problem but does not remove it, and this record must say so plainly.**
Three things survive a weekday-only cadence, which is why answer 1 is still needed:

- The duplicate rows **already exist** and fall inside the first ten-observation window.
- The stale-chain case is **unaffected** — FDX and LMT were stale on ordinary trading days.
- **The cadence cannot be enforced by the code that exists.** `is_market_day` has no holiday
  list, so it returned `True` for Labor Day; a weekday-only policy executed by hand will let
  every market holiday through exactly as 7 September was let through. If the owner wants the
  policy enforced rather than remembered, that is a separate, small piece of work: supply a
  holiday calendar to the existing parameter.

### The one judgement call inside "keep the latest", and how it was resolved

"Keep the latest" admits two readings, and they differ on exactly one value in the entire
store.

- **Row-wise:** take the later row whole. LMT's 09-07 row wins, and because its `iv_atm` is
  NULL, **LMT's only implied-volatility observation (0.1977, on the 09-06 row) is discarded.**
  LMT goes 1 → 0 and its first IV rank slips from Tue 09-22 to Wed 09-23.
- **Per reading:** for each of the three readings independently, take the latest capture that
  actually carries a value. LMT's put/call ratios come from 09-07; its `iv_atm` stays 0.1977.

**Resolved as per-reading**, and the reasoning is recorded so it can be reversed in one line
if the owner disagrees. Both readings are "the latest wins" wherever two captures actually
compete; they differ only where one capture has a value and the other has nothing at all. A
NULL is the absence of a measurement, not a competing measurement that happens to be newer,
so treating it as one would discard evidence without gaining any. **This is the only place in
the store where the two interpretations diverge** — verified: LMT is the sole ticker with an
`iv_atm` on 09-06 and none on 09-07.

> **An observation this surfaced, recorded because it is worse than the case already on file.**
> LMT's two captures of session 09-04 differ far more violently than AAPL's. Put/call volume
> reads 1.8521 on the 09-06 capture and 0.0196 on the 09-07 capture; open interest reads
> **10.5 against 0.0215, a factor of roughly 490**. The AAPL discrepancy recorded in
> `docs/research/alternatives/vendor-consistency.md` is 146% on the same session. This
> strengthens both this decision and 0014's refusal: a series this unstable *within* one
> vendor's own repeated reads of one session cannot absorb a second vendor. It also means
> "keep the latest" is picking a winner between two readings that disagree by two orders of
> magnitude, which is a reason to implement the rule visibly rather than silently — see the
> implementation note below.

### What the store looks like under the decision

Per ticker, after de-duplicating by `(ticker, session)` with the latest capture winning per
reading:

| Reading | 15 of 18 tickers | JPM | LMT | FDX |
|---|---:|---:|---:|---:|
| `iv_atm` | 2 | 1 | 1 | 0 |
| `pc_ratio_vol` | 2 | 2 | 2 | 2 |
| `pc_ratio_oi` | 2 | 2 | 2 | 2 |

First provisional publication, running every weekday from 2026-09-09: **Monday 2026-09-21**
for all 18 tickers' put/call readings and 15 tickers' IV rank; **Tuesday 2026-09-22** for JPM
and LMT's IV rank; **Wednesday 2026-09-23 at the earliest** for FDX, which may never publish
one — see the unknowns above.

### Implementation note carried by this decision

Because the winning capture can disagree with the discarded one by orders of magnitude, the
de-duplication must not be silent. Whatever implements this should record, per de-duplicated
session, that a duplicate existed and which capture won — in the run diagnostics at minimum.
0009's principle applies: a run that quietly resolved a 490-fold disagreement should say so.

## Does this block shipping?

**It blocks definition-of-done item 21, and nothing else. It can ship open.**

Item 21 requires a live run to produce a setup previously rejected for want of a volatility
rank. Whatever is published to satisfy it must mean what the page says it means — so the
counting rule has to be settled **before the first rank publishes**, not before the code
ships. On the owner's answer that is Monday 21 September, which is the real deadline.

Items 1–20 are untouched: no grade, gate, report section or run status depends on how history
is counted. Today the question is inert in the strongest possible sense — **`iv_rank` is NULL
on every stored row and no percentile has ever been published**, so nothing currently in the
product is wrong. The exposure begins on the first run that clears the floor.


---

## Correction, 2026-09-09 — LMT, after the tie-break was settled

**This record's projected counts were written before its closing question was answered, and
one of them does not survive the answer.** Option B2 above projects `iv_atm` **1** for LMT.
Measured after implementation, it is **0**.

LMT's 2026-09-04 session has two captures. The 09-06 capture carries `iv_atm = 0.1977`; the
09-07 capture carries none. The owner answered the closing question **row-level: the later
capture wins, whole** — so the 09-07 row supersedes the 09-06 row and the reading goes with
it. This record anticipated exactly that: *"for LMT 'keep the latest' silently discards its
only implied-volatility observation."*

The alternative — de-duplicating per field rather than per row — would have kept the reading
by pairing it with `pc_ratio_vol` from the other capture, two readings of one session that
differ by **95x** (1.8521 against 0.0196). Declined: splicing disagreeing captures into one
observation is the failure 0014 refuses between vendors, and it is no better inside one.

**Corrected counts, measured from the repaired store:**

| Series | Held per ticker |
|---|---|
| `iv_atm` | **2** for 15 of 18; **1** JPM; **0** FDX; **0** LMT |
| `pc_ratio_vol`, `pc_ratio_oi` | **2** for all 18 |

First `iv_rank` publication moves for LMT only: from Tuesday 2026-09-22 to Wednesday
2026-09-23 at the earliest. Everything else in B2 stands as written.
