# Local Operations

This release runs for one local reader on this machine. The chosen scheduler is
`launchd`, not n8n.

## Why launchd

`launchd` is the lighter local scheduler for this app: it does not require Docker or n8n
to stay up, it runs under the logged-in macOS user, and `StartCalendarInterval` fires one
coalesced run when the machine wakes after a missed scheduled time. n8n remains available
only for manual workflow testing; do not enable the n8n schedule while this LaunchAgent is
installed.

The schedule is weekdays at 06:30 in the Mac's local timezone. Keep the Mac timezone on
`Europe/Lisbon` for the current release assumptions.

## First Setup

Run from the repository root:

```bash
cp .env.example .env
```

The local defaults work for deterministic fixture CLI runs. The scheduled job is intended
for live mode: put provider keys in `.env` and set `BRIEFING_DATA_MODE=live` before
installing the LaunchAgent. You can also switch `pipeline.data_mode` in the config used by
`BRIEFING_CONFIG_PATH`. A persisted fixture run is expected to report snapshot-refusal
diagnostics because synthetic rows are blocked from `daily_snapshot`.

The mutating API endpoints require a bearer token. `APP_RUN_TOKEN` wins when set. If it is
blank, the app and ops scripts generate a local token at:

```text
data/ops/run-token
```

The token file is created on first local job/API use with mode `0600` when the filesystem
allows it.

## Run Once

Use this smoke test before installing the schedule, after configuring live mode:

```bash
PYTHONPATH=src .venv/bin/python ops/run_daily.py --data-mode live --force --max-tickers=1
```

The job runs the pipeline in-process and then calls `publish_static_artifacts` for
publishable run statuses. It writes:

```text
data/ops/last-run.json
output/published/latest/dashboard.html
output/published/latest/dashboard.json
output/published/latest/manifest.json
```

## Check Status

This is the visible last-run command:

```bash
PYTHONPATH=src .venv/bin/python ops/status.py
```

It reports the latest local run id, run date, run status, published latest path, and
manifest match. It exits non-zero when the latest run is missing, stale for a weekday,
failed, partial, unpublished, or has a mismatched `latest` manifest.

For machine-readable output:

```bash
PYTHONPATH=src .venv/bin/python ops/status.py --json
```

## Install The Weekday Schedule

Generate the LaunchAgent plist for inspection:

```bash
PYTHONPATH=src .venv/bin/python ops/install_launchd.py
```

Install and load it:

```bash
PYTHONPATH=src .venv/bin/python ops/install_launchd.py --install --load
```

Check the registered job:

```bash
launchctl print "gui/$(id -u)/com.fernando.briefing.daily"
```

The LaunchAgent runs:

```text
.venv/bin/python ops/run_daily.py
```

It inherits `.env`, so `BRIEFING_DATA_MODE=live` is the live-mode switch for unattended
runs.

Logs are written to:

```text
data/ops/launchd.out.log
data/ops/launchd.err.log
```

## Missed Or Failed Runs

A sleeping Mac can miss 06:30. `launchd` starts one coalesced run when the machine wakes,
but multiple missed intervals collapse to one run. The status command is therefore the
source of truth:

```bash
PYTHONPATH=src .venv/bin/python ops/status.py
```

If it reports attention, inspect:

```bash
cat data/ops/last-run.json
tail -100 data/ops/launchd.err.log
tail -100 data/ops/launchd.out.log
```

To verify failure visibility deliberately:

```bash
PYTHONPATH=src .venv/bin/python ops/run_daily.py --simulate-failure
PYTHONPATH=src .venv/bin/python ops/status.py
```

The second command should show an attention item and exit non-zero.

## Find Today's Report

Open the stable latest report:

```bash
open output/published/latest/dashboard.html
```

The archive for each run remains under:

```text
output/published/<run-date>/<run-id>/
```

`output/published/latest/manifest.json` must carry the same `run_id` as the latest local
run recorded in `data/ops/last-run.json`.

## Local API

The API is optional for the local scheduled path. To run it for manual curl checks:

```bash
PYTHONPATH=src .venv/bin/python ops/serve_api.py
```

`ops/serve_api.py` binds to `127.0.0.1:8000` by default. `/health` is open:

```bash
curl -s http://127.0.0.1:8000/health
```

Mutating endpoints fail closed and need the bearer token:

```bash
TOKEN="$(cat data/ops/run-token)"
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/run/daily?force=true&max_tickers=1"
```

The protected endpoints are:

```text
POST /run/daily
POST /run/weekly
POST /delivery/static
POST /score/open-calls
POST /preflight
```

## Docker And n8n

`docker-compose.yml` binds host ports to loopback. The app, Postgres, and n8n are reachable
from this machine only unless Docker is reconfigured.

n8n is not the shipped scheduler. The workflow exports are inactive and retained for
manual testing or for a deliberate scheduler swap later. If n8n is used, set
`APP_RUN_TOKEN` explicitly in `.env`; n8n cannot infer the generated token file.

## Prose Layer

`BriefingLLM` and the numeric guardrails still exist, but the pipeline and dashboard build
do not call them. This is deliberate for the local single-reader release: the numbered
dashboard is the product surface, and generated commentary is not on the critical path.

To wire prose later, the app would need a pipeline/dashboard step that calls `BriefingLLM`
after the deterministic payload is built, writes returned prose into the dashboard model,
keeps `collect_authorized_numbers` and `assert_authorized_numbers` in the path, and adds
tests proving generated prose cannot introduce unsupported numbers.

Until that work is done, README wording should say the bounded prose layer is present but
not wired into the shipped briefing.

## Release Evidence Still Needed

The three consecutive weekday unattended-run evidence cannot be produced instantly. After
installing the LaunchAgent, record the actual run dates and statuses for three weekdays in
the release results handoff.
