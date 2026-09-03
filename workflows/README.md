# n8n Workflows

See `HOW_TO_RUN_WITH_N8N.md` for the full local runbook.
See `N8N_ASSISTANT_SETUP.md` for the optional local n8n Assistant model, sandbox,
and web search setup.
See `HOW_TO_RUN_WITH_N8N_CLOUD.md` for the hosted n8n Cloud runbook.
See `../docs/DEPLOY_FLY_IO.md` for deploying the FastAPI app to Fly.io and
connecting n8n to it.
See `../docs/DEPLOYMENT_OPTIONS.md` for local, n8n Cloud, Fly.io, and LangChain
orchestration choices.
See `../docs/SOURCE_STATUS.md` for the current source reachability status and fixes.

The local Docker Compose stack also includes the official n8n Assistant sandbox
and web search services. In the n8n sandbox dialog, use `http://sandbox-api:8080`
and the value of `N8N_SANDBOX_SERVICE_API_KEY` from `.env`.
For the web search dialog, select SearXNG and use `http://searxng:8080`.

Import `briefing_daily_delivery.json` into n8n for the weekday run. Import
`briefing_weekly_delivery.json` only when a weekly dashboard is wanted.

The workflows use these environment variables from `docker-compose.yml`:

- `APP_RUN_TOKEN`: bearer token sent to the app.
- `APP_RUN_URL`: daily endpoint override; default `http://app:8000/run/daily`.
- `APP_WEEKLY_RUN_URL`: weekly endpoint override; default `http://app:8000/run/weekly`.
- `STATIC_DELIVERY_URL`: static publishing endpoint; default `http://app:8000/delivery/static`.
- `GENERIC_TIMEZONE`: schedule and guard timezone; default `Europe/Lisbon`.
- `MARKET_HOLIDAYS`: optional comma-separated `YYYY-MM-DD` dates blocked by the guard.
- `N8N_BLOCK_ENV_ACCESS_IN_NODE`: set to `false` locally so workflow expressions can
  read `$env.APP_RUN_TOKEN` and endpoint URLs.

The n8n Assistant services use these local-only environment variables:

- `N8N_SANDBOX_SERVICE_URL`: default `http://sandbox-api:8080`.
- `N8N_SANDBOX_SERVICE_API_KEY`: must match one value in `SANDBOX_API_KEYS`.
- `N8N_INSTANCE_AI_SEARXNG_URL`: default `http://searxng:8080`.

Successful daily or weekly runs are published by the app into:

- `output/published/latest/dashboard.html`
- `output/published/latest/dashboard.json`
- `output/published/latest/manifest.json`

For Ollama Cloud prose generation, configure the FastAPI app environment, not n8n:

- `LLM_PROVIDER=ollama`
- `OLLAMA_BASE_URL=https://ollama.com`
- `OLLAMA_MODEL=gpt-oss:120b`
- `OLLAMA_API_KEY=<ollama-cloud-api-key>`
