# How To Run With n8n Cloud

This guide covers the hosted n8n path. In this setup your laptop is not part of the
daily run.

n8n Cloud hosts the n8n editor and workflow execution service. It does not host this
FastAPI app, the local Docker Compose network, local Postgres, local Ollama, the local
sandbox API, or local SearXNG.

## Target Architecture

```text
n8n Cloud
  -> HTTPS request to hosted FastAPI app
  -> app runs the briefing pipeline
  -> app publishes or uploads dashboard artifacts
  -> n8n sends a success/error notification
```

Important: n8n Cloud cannot call Docker Compose service names such as
`http://app:8000`. That hostname only works inside the local Docker Compose network.
n8n Cloud must call a public HTTPS URL.

LLM note: when using Ollama Cloud, the hosted FastAPI app calls Ollama. n8n Cloud
should still call only your app endpoints.

Assistant note: the n8n Assistant is optional and is not required for the imported
briefing workflows. Local Assistant URLs such as `http://sandbox-api:8080`,
`http://searxng:8080`, and `http://host.docker.internal:11434/v1` do not work from
n8n Cloud.

## Current Repo Status

The repo already has:

- FastAPI endpoints:
  - `POST /run/daily`
  - `POST /run/weekly`
  - `POST /delivery/static`
- Bearer-token protection through `APP_RUN_TOKEN`.
- n8n workflow exports:
  - `workflows/briefing_daily_delivery.json`
  - `workflows/briefing_weekly_delivery.json`

For n8n Cloud, you still need to host the FastAPI app somewhere public first.

## Setup Overview

Before importing the workflow into n8n Cloud, prepare these values:

```text
PUBLIC_APP_URL=https://briefing.example.com
APP_RUN_TOKEN=<long-random-token>
DAILY_RUN_URL=https://briefing.example.com/run/daily
WEEKLY_RUN_URL=https://briefing.example.com/run/weekly
STATIC_DELIVERY_URL=https://briefing.example.com/delivery/static
TIMEZONE=Europe/Lisbon
MARKET_HOLIDAYS=2026-01-01,2026-12-25
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=https://ollama.com
OLLAMA_MODEL=gpt-oss:120b
OLLAMA_API_KEY=<ollama-cloud-api-key>
```

Minimum setup order:

1. Deploy the FastAPI app to a public HTTPS host.
2. Set `APP_RUN_TOKEN`, Ollama Cloud, and app environment variables on that host.
3. Confirm `GET /health` works from your browser or terminal.
4. Confirm `POST /run/daily` works with the bearer token.
5. Create or open your n8n Cloud workspace.
6. Import `workflows/briefing_daily_delivery.json`.
7. Replace local Docker URLs with the public HTTPS URLs.
8. Replace `$env.APP_RUN_TOKEN` with an n8n credential or literal setup token.
9. Execute the workflow manually.
10. Activate the schedule only after the manual run succeeds.

The quickest safe first run is:

```text
https://briefing.example.com/run/daily?force=true&max_tickers=1
```

Use `force=true` only for setup checks. The scheduled workflow should let the
market-day guard decide whether to run.

## 1. Host The FastAPI App

Pick one hosting target:

- Render, Railway, Fly.io, DigitalOcean App Platform, AWS, GCP, or Azure.
- A VPS is also fine, but then you are self-hosting infrastructure again.

For the broader local, hosted, and LangChain orchestration choices, see
[DEPLOYMENT_OPTIONS.md](../docs/DEPLOYMENT_OPTIONS.md).

For Fly.io specifically, use
[DEPLOY_FLY_IO.md](../docs/DEPLOY_FLY_IO.md). The short version is:

```text
fly launch --no-deploy --dockerfile Dockerfile
fly secrets set APP_RUN_TOKEN=<long-random-token> OLLAMA_API_KEY=<ollama-cloud-api-key>
fly deploy
```

The hosted app needs:

- Public HTTPS base URL, for example `https://briefing.example.com`.
- Postgres database URL.
- Persistent file storage, object storage, or a public artifact-serving endpoint.
- Outbound HTTPS access to `https://ollama.com`.
- Environment variables listed below.

Minimum app environment variables:

```text
APP_RUN_TOKEN=<long-random-token>
APP_ENV=production
BRIEFING_CONFIG_PATH=/app/config/config.example.yaml
BRIEFING_SOURCE_REGISTRY_PATH=/app/config/source_registry.yaml
BRIEFING_DATA_DIR=/app/data
BRIEFING_OUTPUT_DIR=/app/output
DATABASE_URL=<managed-postgres-url>
GENERIC_TIMEZONE=Europe/Lisbon
ALPHA_VANTAGE_API_KEY=<optional-until-live-data>
FMP_API_KEY=<optional-until-live-data>
FRED_API_KEY=<optional-until-live-data>
FINNHUB_API_KEY=<optional-until-live-data>
TWELVE_DATA_API_KEY=<optional-until-live-data>
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=https://ollama.com
OLLAMA_MODEL=gpt-oss:120b
OLLAMA_API_KEY=<ollama-cloud-api-key>
```

The default fixture pipeline can run without provider keys, but real market-data runs
will need the relevant provider credentials.

On Fly.io, a smoke deploy can omit `DATABASE_URL`, but production should use Fly
Managed Postgres or another managed Postgres provider. Also remember that Fly app root
filesystems are ephemeral; use a Fly Volume or object storage if you need raw cache and
dashboard files to survive restarts.

## 2. Configure Ollama Cloud

Use this path when you do not want to run Ollama locally.

1. Create an Ollama account.
2. Create an Ollama API key.
3. Set the app host environment:

```text
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=https://ollama.com
OLLAMA_API_KEY=<ollama-cloud-api-key>
OLLAMA_MODEL=gpt-oss:120b
```

For direct cloud API access, the app calls:

```text
POST https://ollama.com/api/chat
Authorization: Bearer $OLLAMA_API_KEY
```

Use the cloud model name available to your Ollama account. Ollama's docs show
`gpt-oss:120b` for direct cloud API access. The `*-cloud` suffix is for local Ollama
daemon mode, for example `ollama run gpt-oss:120b-cloud`.

n8n Cloud does not need the Ollama API key unless you later choose to call Ollama
directly from n8n. In the recommended setup, keep the Ollama key only on the app host.

## n8n Assistant In n8n Cloud

You can skip this for the briefing workflow. The imported daily and weekly workflows do
not need the n8n Assistant.

If you also want to use the n8n Assistant inside n8n Cloud, use providers that n8n
Cloud can reach over the public internet:

- Model: use a cloud model endpoint supported by the n8n Assistant. Do not use
  `host.docker.internal` or a local Ollama daemon.
- Code sandbox: use the hosted option shown by n8n Cloud, or a sandbox service exposed
  over HTTPS. Do not use `http://sandbox-api:8080`.
- Web search: use Brave Search with an API key or a public HTTPS SearXNG instance.
  Do not use `http://searxng:8080`.

For local Assistant setup, see
[N8N_ASSISTANT_SETUP.md](N8N_ASSISTANT_SETUP.md).

## 3. Verify The Hosted App

From your machine, test the public app URL:

```bash
curl https://briefing.example.com/health
```

Then test a forced fixture run:

```bash
TOKEN=<same-value-as-APP_RUN_TOKEN>

curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  "https://briefing.example.com/run/daily?force=true&max_tickers=1"
```

The response should include:

```json
{
  "run_id": "daily-...",
  "status": "succeeded",
  "html_path": "...",
  "json_path": "..."
}
```

## 4. Decide How Dashboards Will Be Delivered

The local workflow publishes files under `output/published/latest/`. In n8n Cloud,
container file paths are not useful unless your hosted app also serves those files.

Use one of these delivery patterns:

### Option A: Public Static Endpoint

Add or expose an app route that serves the latest dashboard:

```text
https://briefing.example.com/published/latest/dashboard.html
https://briefing.example.com/published/latest/dashboard.json
```

Then n8n can send those links.

### Option B: Object Storage

Add a delivery adapter that uploads the HTML/JSON to S3, Cloudflare R2, GCS, or Azure
Blob Storage.

Then n8n sends the returned public or signed URL.

### Option C: Email Or Discord From n8n

Have the app return a public dashboard URL or dashboard content, then add an Email,
Gmail, Discord, Slack, or webhook node after the delivery step.

For production, Option B is usually the cleanest because app containers often have
ephemeral filesystems.

## 5. Create n8n Cloud Account

1. Go to n8n Cloud.
2. Start a trial or paid workspace.
3. Open the n8n editor UI.
4. Create or open a project for this workflow.

## 6. Import The Workflow

1. In n8n Cloud, open `Workflows`.
2. Choose `Import from File`.
3. Select `workflows/briefing_daily_delivery.json`.
4. Save the imported workflow.

Optionally import `workflows/briefing_weekly_delivery.json` for the weekly job.

## 7. Replace Docker-Local Values

Open the imported daily workflow and edit these nodes.

### Market Day Guard

The checked-in workflow reads Docker environment variables such as
`$env.GENERIC_TIMEZONE` and `$env.MARKET_HOLIDAYS`.

n8n Cloud does not support arbitrary custom environment variables in the same way a
self-hosted container does. Use literal values in the Code node instead:

```js
const timezone = 'Europe/Lisbon';
const holidays = new Set(['2026-01-01', '2026-12-25']);
```

Keep the rest of the market-day logic unchanged.

### Run Daily Briefing

Replace the URL with your hosted app:

```text
https://briefing.example.com/run/daily
```

Replace the authorization header:

```text
Authorization: Bearer <same-value-as-APP_RUN_TOKEN>
```

Prefer storing the token in an n8n credential rather than hardcoding it in the node.

Do not put `OLLAMA_API_KEY` in this node. The app uses that key server-side.

### Publish Static HTML/JSON

Replace the URL:

```text
https://briefing.example.com/delivery/static
```

Use the same bearer token credential.

If you choose S3/R2/email/Discord delivery instead of `/delivery/static`, replace this
node with the relevant delivery node or webhook call.

## 8. Execute Manually

In n8n Cloud:

1. Open the workflow.
2. Click `Execute workflow`.
3. Check `Market Day Guard`.
4. Check `Run Daily Briefing`.
5. Check `Publish Static HTML/JSON` or your replacement delivery node.

Success should end in `Delivery Summary`.

Failure should end in `Format Error Branch` with:

```json
{
  "run_id": "daily-...",
  "stage": "run_daily",
  "ticker": "*",
  "reason": "..."
}
```

## 9. Add Notification Delivery

After `Delivery Summary`, add one of:

- Email node.
- Gmail node.
- Discord node.
- Slack node.
- HTTP Request node to your own webhook.

Recommended message shape:

```text
Briefing run complete
Run: {{$json.run_id}}
Date: {{$json.run_date}}
HTML: {{$json.html_path}}
JSON: {{$json.json_path}}
Warnings: {{$json.warnings}}
```

If your delivery adapter returns a public URL, use that instead of local file paths.

## 10. Activate The Schedule

After a manual run succeeds:

1. Save the workflow.
2. Toggle the workflow to active.
3. Confirm the schedule node is enabled.

The daily workflow schedule is:

```text
30 6 * * 1-5
```

The workflow settings use:

```text
Europe/Lisbon
```

## 11. Production Checklist

Before trusting the cloud workflow:

- Hosted app health check works over HTTPS.
- `/run/daily` rejects missing or wrong bearer tokens.
- `/run/daily?force=true&max_tickers=1` succeeds.
- Hosted app can reach `https://ollama.com/api/chat`.
- Ollama Cloud key is set only on the app host.
- Preflight has been run and source statuses are understood:
  [SOURCE_STATUS.md](../docs/SOURCE_STATUS.md).
- Dashboard delivery returns a public URL or sends a real notification.
- Error branch includes `run_id`, `stage`, `ticker`, and `reason`.
- Managed Postgres backups are enabled.
- Dashboard artifacts are not stored only on ephemeral container disk.
- n8n workflow execution history is enabled long enough for troubleshooting.

## 12. Common Problems

`http://app:8000` fails:

- Replace it with the public hosted app URL.

`$env.APP_RUN_TOKEN` is empty in n8n Cloud:

- Use an n8n credential or a literal test value while setting up.

Ollama request fails:

- Confirm `LLM_PROVIDER=ollama`.
- Confirm `OLLAMA_BASE_URL=https://ollama.com`.
- Confirm `OLLAMA_API_KEY` is set on the app host.
- Confirm `OLLAMA_MODEL` is available to your Ollama account.

Run succeeds but dashboard link does not open:

- The app returned a container file path, not a public URL.
- Add public static serving or upload artifacts to object storage.

`401 Unauthorized`:

- The token in n8n does not match `APP_RUN_TOKEN` on the hosted app.

Workflow skips:

- The Lisbon-local day is weekend or listed in the market holiday list.

No output after deploy restart:

- Your host may have an ephemeral filesystem.
- Use managed object storage or a persistent disk.

## Recommended Cloud Setup

For the least operational work:

```text
n8n Cloud
  -> hosted FastAPI app on Render/Railway/Fly
  -> app calls Ollama Cloud at https://ollama.com/api/chat
  -> managed Postgres
  -> S3/R2 static dashboard upload
  -> email/Discord notification from n8n
```

This keeps n8n as the scheduler and notification layer, while the Python app remains
the deterministic execution engine.
