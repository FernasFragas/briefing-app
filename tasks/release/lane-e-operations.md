# Lane E — Local operations

**Implements:** D1 (local, single reader). **Closes:** blockers #4 (endpoint fails open),
#5 (prose layer dead), #6 (delivery unexercised).
**Depends on:** Lane 0 only. Runs in parallel with A, B, C, D.

## Owns — write only these

```
src/briefing_app/api.py
src/briefing_app/delivery.py
tests/test_delivery.py
ops/                             (new directory)
docs/LOCAL-OPS.md                (new)
docker-compose.yml
workflows/
.env.example
```

## Must not touch

`cli.py` (Lane C — it is adding a backfill command there). `README.md` is **Lane F's**: it
makes claims about grading and ordering that Lanes A and B are changing concurrently, so it
is synchronised once at the end rather than by three lanes at once.

---

## Tasks

- [ ] **E1 — Fix the fail-open run token**

  `_require_run_token` (`api.py:21`):

  ```python
  def _require_run_token(authorization: str | None) -> None:
      expected = os.getenv("APP_RUN_TOKEN")
      if not expected:
          return          # <-- no token configured means no authentication at all
      ...
  ```

  Every mutating endpoint — `/run/daily`, `/run/weekly`, `/delivery/static`,
  `/score/open-calls`, `/preflight` — is therefore unauthenticated by default.

  D1 puts this on your own machine, so it is not currently exposed. Fix it anyway: it is a
  few lines, and the cost of leaving a fail-open default in place is that the first time the
  app is ever reachable from anywhere else, anyone who finds it can trigger runs that spend
  the metered Alpha Vantage allowance — 25 requests per day, shared with the live run and
  with Lane C's backfill.

  **Fail closed:** with no token configured, a mutating endpoint refuses. `/health` stays
  open — it carries no data and is what a scheduler probes.

  Make the local path pleasant rather than a reason to disable it: bind to loopback by
  default, and have the app generate and persist a token on first start if none is set, so
  the correct configuration is also the easy one.

  **Acceptance:**
  - With `APP_RUN_TOKEN` unset, every mutating endpoint returns 401 and no run starts.
  - With it set, a correct bearer token succeeds and a wrong one returns 401.
  - `/health` answers without a token.
  - A test covers the unset case specifically — that is the branch that shipped broken.

- [ ] **E2 — Make the daily run happen unattended, and make a missed run visible**

  The n8n schedule is configured for `30 6 * * 1-5`, yet `briefing_run` holds **three runs
  across five days**, one of which was a manual fixture run. The schedule is not firing.
  That stalled clock is the direct cause of the volatility warm-up going nowhere, so this
  is not a cosmetic fix — Lane C's backfill gets the baseline started, and this is what
  keeps it alive.

  Under D1, decide between a local `launchd` job and the existing n8n container, and write
  the reasoning down. `launchd` is the lighter answer for a single local reader and does not
  require the Docker stack to be running; n8n is already configured and gives a UI. Either
  is defensible — pick one and remove or clearly mark the other, so there are not two
  schedulers half-configured.

  **The failure mode you must handle.** A local machine is asleep at 06:30 more often than
  not. `launchd` with `StartCalendarInterval` runs a missed job when the machine wakes, but
  only once and only if configured for it. Whatever you choose:
  - A missed or failed run must be **visible without going to look for it**. A silent gap
    is what produced the current state.
  - The owner should be able to answer "did it run today, and did it succeed?" in one
    command. Add it to `docs/LOCAL-OPS.md`.

  **Acceptance:**
  - The run fires unattended on three consecutive weekdays. This is item 7 of the release
    definition of done and it takes three days of real time — **start this task first.**
  - A deliberately failed run surfaces visibly.
  - One documented command reports the last run's date and status.

- [ ] **E3 — Exercise the publishing path**

  `output/published/` was last written on 2026-09-02 and `output/published/latest/` dates
  from 2026-08-30. The last three dashboards were never published. `publish_static_artifacts`
  (`delivery.py:80`) has therefore not run against current output in five days, across a
  schema change and several payload changes.

  For a single local reader "publishing" means: the finished report lands somewhere stable
  the owner opens, and `latest` actually points at the latest.

  **Acceptance:**
  - A live run's artifacts publish end to end, and `output/published/latest/` contains that
    run's dashboard.
  - `manifest.json` matches the run it claims to describe.
  - The publish step runs as part of the scheduled job, not as a separate thing to remember.

- [ ] **E4 — Resolve the prose layer**

  `BriefingLLM` (`dashboard/llm.py`) is exported from `dashboard/__init__.py` and **called
  by nothing**. Neither `pipeline.py` nor `dashboard/build.py` references it. On the
  2026-09-06 run, **0 of 35** per-ticker sections carry prose. Meanwhile `README.md`
  advertises "Ollama Cloud for bounded LLM prose" and task T8 shipped guardrails
  (`collect_authorized_numbers`, `assert_authorized_numbers`) to police prose that is never
  generated.

  **Recommended, given D1:** keep the code and the guardrails, and stop claiming the
  feature. A single reader who can read the numbers gains little from generated commentary,
  and the guardrail work is sound and worth keeping for when it is wired. Record in
  `docs/LOCAL-OPS.md` that the layer exists, is deliberately unwired, and what wiring it
  would involve.

  This is a small open call rather than one of the eight decisions. If you would rather wire
  it than shelve it, say so — it is a contained piece of work, but it is new scope and it is
  not on the critical path to shipping.

  **Acceptance:** no document claims a working prose layer; `docs/LOCAL-OPS.md` records the
  disposition and the reasoning. (`README.md` is Lane F's — report the wording you want and
  Lane F applies it.)

- [ ] **E5 — Write `docs/LOCAL-OPS.md`**

  Start the daily run; check whether it ran and whether it succeeded; find today's report;
  what to do when a run is missed or fails; where the token lives; and the E4 disposition.
  Written for the owner six months from now, who will have forgotten all of it.

---

## Verify

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_delivery.py -q
PYTHONPATH=src .venv/bin/python -m pytest -q
curl -s localhost:8000/health
curl -s -X POST localhost:8000/run/daily          # expect 401 with no token
```

## Handoff

Report to Lane F: the scheduler chosen, the dates of the three unattended runs (definition
of done item 7), and the README wording you want for the prose layer.
