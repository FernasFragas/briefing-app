# n8n Assistant Setup

This document covers the optional n8n AI Assistant at `http://localhost:5678/assistant`.
It is not required for the imported briefing workflows to run.

The briefing workflows only need n8n to call the FastAPI app. The Assistant is useful
when you want n8n to help create or edit workflows from the UI.

## Local Docker Setup

Start the full local stack:

```bash
docker compose up -d --build
```

Open:

```text
http://localhost:5678/assistant
```

Use these values in the Assistant setup screens.

| Screen | Field | Value |
|---|---|---|
| Connect a model | Provider | `Self-hosted or OpenAI-compatible endpoint` |
| Connect a model | Base URL | `http://host.docker.internal:11434/v1` |
| Connect a model | API key | `ollama` |
| Connect a model | Model | `mistral:7b` or another local model from `ollama list` |
| Add a code sandbox | Service URL | `http://sandbox-api:8080` |
| Add a code sandbox | API key | value of `N8N_SANDBOX_SERVICE_API_KEY` from `.env` |
| Add web search | Provider | `SearXNG` |
| Add web search | Instance URL | `http://searxng:8080` |

If you are using the local `.env` values added during this setup, the sandbox API key is:

```text
briefing-local-sandbox-key
```

If you recreated `.env` from `.env.example`, use the value you set for
`N8N_SANDBOX_SERVICE_API_KEY`.

## Local Services

The local `docker-compose.yml` includes:

- `n8n`: workflow editor, scheduler, and Assistant UI.
- `sandbox-certs`: one-shot certificate bootstrap for the sandbox stack.
- `sandbox-api`: API that n8n calls when the Assistant needs to run code.
- `sandbox-runner-1`: privileged Docker-in-Docker runner that executes sandbox code.
- `searxng`: local web search provider for the Assistant.

Only n8n is exposed on the host at `http://localhost:5678`. The sandbox and SearXNG
services are internal Docker Compose services and should not publish ports.

## Required Environment

These values are in `.env.example`:

```text
SANDBOX_API_KEYS=change-me-sandbox-api-key
SANDBOX_API_RUNNER_REGISTRATION_TOKEN=change-me-sandbox-registration-token
SANDBOX_API_RUNNER_API_KEY=change-me-sandbox-runner-key
N8N_SANDBOX_SERVICE_API_KEY=change-me-sandbox-api-key
N8N_SANDBOX_SERVICE_URL=http://sandbox-api:8080
N8N_ENABLED_MODULES=instance-ai
N8N_BLOCK_ENV_ACCESS_IN_NODE=false
N8N_INSTANCE_AI_SANDBOX_ENABLED=true
N8N_INSTANCE_AI_SANDBOX_PROVIDER=n8n-sandbox
N8N_INSTANCE_AI_SANDBOX_IMAGE=ghcr.io/n8n-io/n8n-sandbox-service-sandbox:latest
SEARXNG_SECRET=change-me-searxng-secret
N8N_INSTANCE_AI_SEARXNG_URL=http://searxng:8080
```

Keep `N8N_SANDBOX_SERVICE_API_KEY` equal to one value in `SANDBOX_API_KEYS`.
The sandbox key is not your Ollama key.
`N8N_BLOCK_ENV_ACCESS_IN_NODE=false` is also used by the local briefing workflow so it
can read `$env.APP_RUN_TOKEN` and endpoint URLs. Only use this in a trusted local n8n
instance.

## Ollama Choices

For the briefing app itself, the recommended setup is Ollama Cloud:

```text
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=https://ollama.com
OLLAMA_MODEL=gpt-oss:120b
OLLAMA_API_KEY=<ollama-cloud-api-key>
```

In this mode, n8n does not call Ollama. n8n calls the FastAPI app, and the app calls
Ollama Cloud from its own environment.

For the n8n Assistant model screen with a local Ollama daemon, use the
OpenAI-compatible local endpoint:

```text
Base URL: http://host.docker.internal:11434/v1
API key: ollama
Model: mistral:7b
```

The `/v1` suffix matters. `http://host.docker.internal:11434` reaches Ollama, but it
is not the OpenAI-compatible base URL. The local API key can be any non-empty string;
local Ollama requires the field but ignores the value.

Native Ollama API URLs are different:

```text
Local native API from n8n Docker: http://host.docker.internal:11434/api/chat
Ollama Cloud native API: https://ollama.com/api/chat
```

Ollama Cloud direct API calls require:

```text
Authorization: Bearer <OLLAMA_API_KEY>
```

## Verification

Check all containers:

```bash
docker compose ps
```

Check sandbox API from inside n8n:

```bash
docker compose exec n8n wget -qO- http://sandbox-api:8080/healthz
```

Expected response:

```json
{"status":"ok"}
```

Check SearXNG from inside n8n:

```bash
docker compose exec n8n wget -qO- "http://searxng:8080/search?q=n8n&format=json"
```

Expected response: JSON with a `results` array.

Check local Ollama OpenAI-compatible endpoint from inside n8n:

```bash
docker compose exec n8n node -e "fetch('http://host.docker.internal:11434/v1/models', { headers: { Authorization: 'Bearer ollama' } }).then(async r => { console.log(r.status); console.log(await r.text()); }).catch(e => { console.error(e.message); process.exit(1); })"
```

Expected response: status `200` and a model list.

## Common Errors

`The service couldn't complete the test` on the model screen:

- Use `http://host.docker.internal:11434/v1`, not `http://host.docker.internal:11434`.
- Confirm Ollama is running on the host.
- Confirm the model exists with `ollama list`.
- Do not use `localhost` from inside n8n Docker. There, `localhost` means the n8n
  container itself.

`Market Day Guard` fails with `access to env vars denied`:

- Set `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` in the n8n container.
- Restart n8n with `docker compose up -d n8n`.
- This lets local workflows read n8n container environment variables.

Sandbox screen cannot continue:

- Use `http://sandbox-api:8080`.
- Use the value of `N8N_SANDBOX_SERVICE_API_KEY`.
- Do not use `http://sandbox.internal:3200` in this project.
- Confirm `docker compose ps` shows `sandbox-api` healthy.
- If n8n logs show `DB override`, save the sandbox values in the Assistant UI. Saved UI
  settings override env values after the first setup attempt.

Web search screen cannot continue:

- Select `SearXNG`.
- Use `http://searxng:8080`.
- Do not use `http://searxng.internal:8080` in this project.
- Confirm the JSON search verification command returns results.

SearXNG logs show CAPTCHA, rate-limit, or 403 errors:

- Some upstream engines may block or rate-limit requests.
- The local SearXNG service is still wired correctly if the verification command
  returns JSON results.

## n8n Cloud

n8n Cloud hosts n8n, not this FastAPI app. For n8n Cloud, deploy the FastAPI app to a
public HTTPS host such as Fly.io first, then point the workflow HTTP nodes at that URL.

The local Docker service names do not work from n8n Cloud:

```text
http://app:8000
http://sandbox-api:8080
http://searxng:8080
http://host.docker.internal:11434
```

The imported briefing workflow does not need the n8n Assistant, sandbox, or web search.
For the recommended cloud setup:

- n8n Cloud calls the hosted FastAPI app.
- The hosted app calls Ollama Cloud.
- The hosted app stores data in managed Postgres.
- Dashboard artifacts are served publicly or uploaded to object storage.

If you also want to use the n8n Assistant in n8n Cloud, use services that n8n Cloud can
reach over the public internet. Do not use the local Docker URLs from this document.

## References

- n8n Docker Compose setup: https://docs.n8n.io/deploy/host-n8n/install-options/install-using-docker-compose/
- n8n sandbox service API: https://github.com/n8n-io/n8n-sandbox-service/blob/main/docs/API.md
- Ollama OpenAI compatibility: https://docs.ollama.com/api/openai-compatibility
- Ollama Cloud: https://docs.ollama.com/cloud
- Ollama authentication: https://docs.ollama.com/api/authentication
