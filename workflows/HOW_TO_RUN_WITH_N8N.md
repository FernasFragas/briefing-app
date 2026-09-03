# How To Run The Briefing App With n8n

This runbook starts the local stack, imports the n8n workflow, runs it manually, and
shows where the delivered dashboard files land. It also lists the optional local n8n
Assistant setup values for model, sandbox, and web search.

## What n8n Does

n8n is only the scheduler and delivery coordinator. The Python app still performs the
pipeline work:

1. n8n checks the Lisbon-local market day.
2. n8n calls `POST http://app:8000/run/daily` with `Authorization: Bearer $APP_RUN_TOKEN`.
3. The app writes dated dashboard artifacts under `output/dashboard/<run-date>/`.
4. n8n calls `POST http://app:8000/delivery/static`.
5. The app publishes stable latest files under `output/published/latest/`.

The n8n Assistant is optional. The imported briefing workflows do not need the
Assistant, its code sandbox, or web search to execute.

## Prerequisites

- Docker Engine or Docker Desktop is available.
- Docker Compose v2 is available.
- At least 4 GB RAM and 2 vCPUs are recommended when the n8n sandbox runner is enabled.
- Ports `8000`, `5432`, and `5678` are free.
- You are running commands from the repository root.
- Local Ollama is only needed if you want to connect the n8n Assistant to a local
  Ollama model.

## 1. Create Local Environment

Create `.env` from the checked-in example and set a real local token:

```bash
cp .env.example .env
```

Edit `.env`:

```text
APP_RUN_TOKEN=<use-a-long-local-token>
POSTGRES_PASSWORD=<use-a-local-password>
GENERIC_TIMEZONE=Europe/Lisbon
```

The default fixture mode works without market-data provider credentials. Add provider
keys before selecting `pipeline.data_mode=live`:

```text
ALPHA_VANTAGE_API_KEY=
FMP_API_KEY=
FRED_API_KEY=
FINNHUB_API_KEY=
TWELVE_DATA_API_KEY=
```

OpenAI and Anthropic keys are only needed if you choose those legacy LLM providers:

```text
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
```

To use Ollama Cloud for LLM prose instead of OpenAI or Anthropic, set:

```text
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=https://ollama.com
OLLAMA_MODEL=gpt-oss:120b
OLLAMA_API_KEY=<ollama-cloud-api-key>
```

With this cloud path, you do not need a local Ollama container. The app calls
`https://ollama.com/api/chat` directly. Keep the Ollama key in the app environment;
n8n only needs `APP_RUN_TOKEN` to trigger the app.

The optional n8n Assistant sandbox and web search services are already configured in
`.env.example`:

```text
N8N_BLOCK_ENV_ACCESS_IN_NODE=false
N8N_SANDBOX_SERVICE_URL=http://sandbox-api:8080
N8N_SANDBOX_SERVICE_API_KEY=<must-match-SANDBOX_API_KEYS>
N8N_INSTANCE_AI_SEARXNG_URL=http://searxng:8080
```

Keep `N8N_SANDBOX_SERVICE_API_KEY` equal to one value in `SANDBOX_API_KEYS`.
`N8N_BLOCK_ENV_ACCESS_IN_NODE=false` is needed because the checked-in local workflow
reads `$env.APP_RUN_TOKEN`, `$env.APP_RUN_URL`, and related Docker Compose values.

Optional market holidays can be blocked in the n8n guard:

```text
MARKET_HOLIDAYS=2026-01-01,2026-12-25
```

## 2. Start The Stack

```bash
docker compose up -d --build
```

Check that containers are running:

```bash
docker compose ps
```

Check the app health endpoint from the host:

```bash
curl http://localhost:8000/health
```

n8n should be available at:

```text
http://localhost:5678
```

The local Compose stack also starts these n8n Assistant services:

- `sandbox-api`: code sandbox API for the Assistant.
- `sandbox-runner-1`: privileged Docker-in-Docker runner for sandbox execution.
- `searxng`: local web search for the Assistant.

Do not expose these services publicly. n8n reaches them by Docker Compose service name.

## 3. Optional n8n Assistant Setup

Open the Assistant setup UI:

```text
http://localhost:5678/assistant
```

Use these local values:

```text
Model provider: Self-hosted or OpenAI-compatible endpoint
Model Base URL: http://host.docker.internal:11434/v1
Model API key: ollama
Model: mistral:7b or another local model from ollama list

Sandbox Service URL: http://sandbox-api:8080
Sandbox API key: value of N8N_SANDBOX_SERVICE_API_KEY in .env

Web search provider: SearXNG
Web search Instance URL: http://searxng:8080
```

If you are using the local `.env` values added during this setup, the sandbox API key is:

```text
briefing-local-sandbox-key
```

If you recreated `.env` from `.env.example`, use the value you set for
`N8N_SANDBOX_SERVICE_API_KEY`.

More detail: [N8N_ASSISTANT_SETUP.md](N8N_ASSISTANT_SETUP.md).

## 4. Import The Daily Workflow

In the n8n UI:

1. Open `http://localhost:5678`.
2. Complete the n8n first-run owner setup if prompted.
3. Go to `Workflows`.
4. Choose `Import from File`.
5. Select `workflows/briefing_daily_delivery.json`.
6. Save the workflow.

The daily workflow includes:

- Manual trigger.
- Weekday cron at `06:30` in `Europe/Lisbon`.
- Market-day guard.
- Bearer-auth call to `http://app:8000/run/daily`.
- Static publishing call to `http://app:8000/delivery/static`.
- Error branch with `run_id`, `stage`, `ticker`, and `reason`.

## 5. Run It Manually

Open the imported workflow and click `Execute Workflow`.

For a successful fixture run, the final `Delivery Summary` node should contain paths
similar to:

```json
{
  "adapter": "static_html",
  "html_path": "/app/output/published/latest/dashboard.html",
  "json_path": "/app/output/published/latest/dashboard.json",
  "manifest_path": "/app/output/published/latest/manifest.json"
}
```

From the host machine, check:

```bash
ls -la output/published/latest
```

The main files are:

```text
output/published/latest/dashboard.html
output/published/latest/dashboard.json
output/published/latest/manifest.json
```

The dated archive remains under:

```text
output/dashboard/<run-date>/dashboard.html
output/dashboard/<run-date>/dashboard.json
output/published/<run-date>/<run-id>/
```

## 6. Enable The Schedule

After a manual execution succeeds:

1. Open the imported daily workflow in n8n.
2. Toggle it to active.
3. Leave Docker running.

n8n will run the daily workflow on weekdays at `06:30 Europe/Lisbon`. The workflow also
checks `MARKET_HOLIDAYS`, so a listed holiday exits through the market-closed branch.

## 7. Optional Weekly Workflow

Import `workflows/briefing_weekly_delivery.json` only if you want the weekly run. It is
scheduled for Mondays at `06:30 Europe/Lisbon` and calls:

```text
http://app:8000/run/weekly
```

It publishes through the same static delivery endpoint.

## 8. Manual API Smoke Tests

You can test the app without n8n from the host. The bearer token must match `.env`.

```bash
TOKEN=<same-value-as-APP_RUN_TOKEN>
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/run/daily?force=true&max_tickers=1"
```

Use the JSON response body from that command as the payload to static delivery:

```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  --data @run-response.json \
  "http://localhost:8000/delivery/static"
```

## 9. Troubleshooting

`401 Unauthorized` from the app:

- `APP_RUN_TOKEN` must be the same for the `app` and `n8n` services.
- Recreate containers after changing `.env`: `docker compose up -d`.

`Market Day Guard` fails with `access to env vars denied`:

- Confirm the n8n service has `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`.
- Restart n8n after changing it:

```bash
docker compose up -d n8n
```

- This is local-only convenience. It allows workflows in this local n8n instance to
  read n8n container env values, including `APP_RUN_TOKEN`.

Workflow stops at `Market Closed`:

- The current Lisbon-local day is Saturday/Sunday, or the date is listed in `MARKET_HOLIDAYS`.
- Use the manual API smoke test with `force=true` if you only need a local fixture check.

No published files:

- Check the `Run Daily Briefing` node response has status `succeeded` or `partial`.
- Check that `html_path` and `json_path` exist in the app response.
- Check the `Publish Static HTML/JSON` node response for `detail.reason`.

n8n cannot reach Ollama:

- If you are using this app normally, n8n should not call Ollama directly. n8n should
  call `http://app:8000/run/daily`; the app calls Ollama using its own environment.
- If you are configuring the n8n Assistant at `http://localhost:5678/assistant`, use
  Ollama's OpenAI-compatible endpoint:

```text
Provider: Self-hosted or OpenAI-compatible endpoint
Base URL: http://host.docker.internal:11434/v1
API key: ollama
Model: mistral:7b
```

- The `/v1` suffix is required in that Assistant dialog. `http://host.docker.internal:11434`
  reaches the Ollama service, but it is not the OpenAI-compatible base URL.
- The local Ollama API key value can be any non-empty string such as `ollama`; Ollama's
  local OpenAI-compatible API requires the field but ignores the value.
- If an n8n HTTP Request node must call Ollama Cloud directly, use:
  `https://ollama.com/api/chat`, method `POST`, and `Authorization: Bearer <OLLAMA_API_KEY>`.
- If an n8n HTTP Request node must call a local Ollama daemon on your machine, do not
  use `http://localhost:11434`. Inside the n8n Docker container, `localhost` means the
  n8n container itself.
- Use this URL from local Docker n8n to your host Ollama daemon:
  `http://host.docker.internal:11434/api/chat` for native Ollama calls, or
  `http://host.docker.internal:11434/v1` for OpenAI-compatible clients.
- Quick container reachability check:

```bash
docker compose exec n8n node -e "fetch('http://host.docker.internal:11434/api/tags').then(async r => { console.log(r.status); console.log(await r.text()); }).catch(e => { console.error(e.message); process.exit(1); })"
```

- Quick OpenAI-compatible check:

```bash
docker compose exec n8n node -e "fetch('http://host.docker.internal:11434/v1/models', { headers: { Authorization: 'Bearer ollama' } }).then(async r => { console.log(r.status); console.log(await r.text()); }).catch(e => { console.error(e.message); process.exit(1); })"
```

- If that check fails, start Ollama on the host and confirm `ollama list` works. On
  Linux Docker, you may also need to add `host.docker.internal:host-gateway` to the
  n8n service and make Ollama listen on a non-loopback interface.

n8n Assistant asks for a code sandbox:

- This is separate from Ollama and separate from the briefing app workflow.
- The local `docker-compose.yml` includes the official n8n sandbox services:
  `sandbox-certs`, `sandbox-api`, and `sandbox-runner-1`.
- Use these values in the n8n Assistant sandbox screen:

```text
Service URL: http://sandbox-api:8080
API key: the value of N8N_SANDBOX_SERVICE_API_KEY
```

- The sandbox API key must match one of the values in `SANDBOX_API_KEYS` on the
  sandbox API service. It is not your Ollama API key.
- If you are using the local `.env` values added during this setup, the API key is
  `briefing-local-sandbox-key`. Otherwise, use the value you set for
  `N8N_SANDBOX_SERVICE_API_KEY`.
- Do not use `http://sandbox.internal:3200` in this project.
- Do not publish `sandbox-api` or `sandbox-runner-1` ports to your host. n8n reaches
  them through Docker Compose service names.

Start or update the local stack:

```bash
docker compose up -d --build
```

Check that the sandbox API is healthy from inside n8n:

```bash
docker compose exec n8n wget -qO- http://sandbox-api:8080/healthz
```

Check that the runner registered:

```bash
docker compose logs sandbox-api --tail=100
```

If `docker compose logs n8n --tail=100` shows `DB override`, finish the Assistant
sandbox setup in the n8n UI with the values above. The saved UI settings override
the env vars after the first Assistant setup attempt.

You should see `sandbox-api` healthy in:

```bash
docker compose ps
```

n8n Assistant asks for web search:

- Select `SearXNG`.
- The local `docker-compose.yml` includes SearXNG with JSON search enabled.
- Use this value in the n8n Assistant web search screen:

```text
Instance URL: http://searxng:8080
```

- No API key is needed for SearXNG.
- Do not use `http://searxng.internal:8080` in this project.

Check that SearXNG is reachable from inside n8n:

```bash
docker compose exec n8n wget -qO- "http://searxng:8080/search?q=n8n&format=json"
```

Some SearXNG upstream engines can return CAPTCHA, rate-limit, or 403 errors in
the logs. That is not a Docker wiring problem if the command above returns JSON
results.

Inspect service logs:

```bash
docker compose logs app --tail=100
docker compose logs n8n --tail=100
docker compose logs searxng --tail=100
```

Restart the stack:

```bash
docker compose down
docker compose up -d --build
```

## 10. Data Mode Notes

The default configuration uses fixture data:

```text
pipeline.data_mode=fixture
BRIEFING_CONFIG_PATH=/app/config/config.example.yaml
```

That is intentional for local acceptance testing. It exercises candidate loading,
gate, raw cache, scoring, setup rules, dashboard rendering, persistence, n8n delivery,
and static publishing without live provider credentials.

For provider-backed runs, set:

```text
pipeline.data_mode=live
ALPHA_VANTAGE_API_KEY=<your key>
FMP_API_KEY=<your key>
FRED_API_KEY=<your key>
FINNHUB_API_KEY=<your key>
TWELVE_DATA_API_KEY=<your key>
```

Live mode fetches CBOE delayed option chains after the gate, then uses FMP, FRED,
Finnhub, Twelve Data, FINRA, SEC EDGAR, and Alpha Vantage fallbacks for price history,
calendars, news, insider, analyst, macro, and borrow-proxy inputs when those credentials
or cached payloads are available. `S_F` ownership remains blocked by design.

LLM prose generation is separate from fixture market data. Fixture runs can use
`LLM_PROVIDER=ollama` with Ollama Cloud.

## References

- n8n Docker Compose setup: https://docs.n8n.io/deploy/host-n8n/install-options/install-using-docker-compose/
- n8n sandbox service API: https://github.com/n8n-io/n8n-sandbox-service/blob/main/docs/API.md
- Ollama OpenAI compatibility: https://docs.ollama.com/api/openai-compatibility
- Ollama Cloud: https://docs.ollama.com/cloud
