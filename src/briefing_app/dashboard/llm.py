"""Provider wrapper for bounded dashboard prose generation."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from enum import StrEnum
from typing import Any, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from briefing_app.dashboard.guardrails import assert_authorized_numbers


DEFAULT_OLLAMA_BASE_URL = "https://ollama.com"
DEFAULT_OLLAMA_MODEL = "gpt-oss:120b"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 30.0
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_CLAUDE_MODEL = "claude-3-5-sonnet-latest"


class LLMProvider(StrEnum):
    OPENAI = "openai"
    CLAUDE = "claude"
    OLLAMA = "ollama"


@dataclass(frozen=True)
class LLMResponse:
    provider: LLMProvider
    model: str
    text: str


class LLMProviderError(RuntimeError):
    """Raised when the selected LLM provider cannot return parseable prose."""

    def __init__(self, provider: LLMProvider | str, message: str):
        self.provider = LLMProvider(provider)
        self.message = message
        super().__init__(f"{self.provider.value} provider error: {message}")


class OllamaChatClient(Protocol):
    def chat(
        self,
        *,
        url: str,
        payload: Mapping[str, Any],
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        ...


class UrlLibOllamaChatClient:
    """Tiny HTTP adapter for Ollama's native chat API."""

    def chat(
        self,
        *,
        url: str,
        payload: Mapping[str, Any],
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            url,
            data=body,
            headers=dict(headers),
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            message = detail or str(exc.reason)
            raise LLMProviderError(
                LLMProvider.OLLAMA,
                f"Ollama request failed with HTTP {exc.code}: {message}",
            ) from exc
        except (TimeoutError, URLError, OSError) as exc:
            raise LLMProviderError(
                LLMProvider.OLLAMA,
                f"Ollama request failed: {exc}",
            ) from exc

        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(
                LLMProvider.OLLAMA,
                "Ollama returned a non-JSON response.",
            ) from exc
        if not isinstance(decoded, dict):
            raise LLMProviderError(
                LLMProvider.OLLAMA,
                "Ollama returned an unexpected response shape.",
            )
        return decoded


class BriefingLLM:
    """Small provider switch that always requests deterministic prose."""

    def __init__(
        self,
        *,
        provider: LLMProvider | str,
        model: str,
        max_tokens: int = 700,
        openai_client: Any | None = None,
        anthropic_client: Any | None = None,
        ollama_client: OllamaChatClient | None = None,
        ollama_base_url: str | None = None,
        ollama_api_key: str | None = None,
        ollama_timeout_seconds: float = DEFAULT_OLLAMA_TIMEOUT_SECONDS,
    ) -> None:
        self.provider = LLMProvider(str(provider).strip().lower())
        self.model = model
        self.max_tokens = max_tokens
        self._openai_client = openai_client
        self._anthropic_client = anthropic_client
        self._ollama_client = ollama_client or UrlLibOllamaChatClient()
        self._ollama_api_key_explicit = ollama_api_key is not None
        self.ollama_base_url = _normalize_base_url(
            ollama_base_url or os.getenv("OLLAMA_BASE_URL") or DEFAULT_OLLAMA_BASE_URL
        )
        self.ollama_api_key = _blank_to_none(
            ollama_api_key if ollama_api_key is not None else os.getenv("OLLAMA_API_KEY")
        )
        self.ollama_timeout_seconds = ollama_timeout_seconds

    @classmethod
    def from_env(cls, **overrides: Any) -> "BriefingLLM":
        provider = LLMProvider(os.getenv("LLM_PROVIDER", LLMProvider.OLLAMA.value).strip().lower())
        model = overrides.pop("model", None) or _model_from_env(provider)
        return cls(provider=provider, model=model, **overrides)

    def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        allowed_context: Any,
    ) -> LLMResponse:
        """Generate prose, then reject unauthorized numbers before returning it."""
        if self.provider is LLMProvider.OPENAI:
            text = self._complete_openai(messages)
        elif self.provider is LLMProvider.CLAUDE:
            text = self._complete_claude(messages)
        else:
            text = self._complete_ollama(messages)
        assert_authorized_numbers(text, allowed_context)
        return LLMResponse(provider=self.provider, model=self.model, text=text)

    def _complete_openai(self, messages: Sequence[Mapping[str, str]]) -> str:
        client = self._openai_client
        if client is None:
            from openai import OpenAI

            client = OpenAI()
        response = client.chat.completions.create(
            model=self.model,
            messages=[dict(message) for message in messages],
            temperature=0,
            max_tokens=self.max_tokens,
        )
        return response.choices[0].message.content or ""

    def _complete_claude(self, messages: Sequence[Mapping[str, str]]) -> str:
        client = self._anthropic_client
        if client is None:
            from anthropic import Anthropic

            client = Anthropic()

        system_parts = [message["content"] for message in messages if message["role"] == "system"]
        user_messages = [
            {"role": message["role"], "content": message["content"]}
            for message in messages
            if message["role"] != "system"
        ]
        response = client.messages.create(
            model=self.model,
            system="\n\n".join(system_parts) or None,
            messages=user_messages,
            temperature=0,
            max_tokens=self.max_tokens,
        )
        parts: list[str] = []
        for block in response.content:
            text = getattr(block, "text", None)
            if text is not None:
                parts.append(text)
        return "".join(parts)

    def _complete_ollama(self, messages: Sequence[Mapping[str, str]]) -> str:
        headers = self._ollama_headers()
        payload = {
            "model": self.model,
            "messages": [dict(message) for message in messages],
            "stream": False,
            "options": {
                "temperature": 0,
                "num_predict": self.max_tokens,
            },
        }
        try:
            response = self._ollama_client.chat(
                url=_ollama_chat_url(self.ollama_base_url),
                payload=payload,
                headers=headers,
                timeout_seconds=self.ollama_timeout_seconds,
            )
        except LLMProviderError:
            raise
        except (TimeoutError, URLError, OSError) as exc:
            raise LLMProviderError(
                LLMProvider.OLLAMA,
                f"Ollama request failed: {exc}",
            ) from exc

        message = response.get("message")
        if not isinstance(message, Mapping):
            raise LLMProviderError(
                LLMProvider.OLLAMA,
                "Ollama response is missing message content.",
            )
        content = message.get("content")
        if not isinstance(content, str):
            raise LLMProviderError(
                LLMProvider.OLLAMA,
                "Ollama response message content is not text.",
            )
        return content

    def _ollama_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        requires_cloud_auth = _requires_cloud_auth(self.ollama_base_url)
        if self.ollama_api_key and (requires_cloud_auth or self._ollama_api_key_explicit):
            headers["Authorization"] = f"Bearer {self.ollama_api_key}"
            return headers
        if requires_cloud_auth:
            raise LLMProviderError(
                LLMProvider.OLLAMA,
                "Missing credential: OLLAMA_API_KEY is required for Ollama Cloud.",
            )
        return headers


def _model_from_env(provider: LLMProvider) -> str:
    if provider is LLMProvider.OLLAMA:
        return _env_or_default("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
    if provider is LLMProvider.CLAUDE:
        return _env_or_default("ANTHROPIC_MODEL", DEFAULT_CLAUDE_MODEL)
    return _env_or_default("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)


def _env_or_default(name: str, default: str) -> str:
    return _blank_to_none(os.getenv(name)) or default


def _normalize_base_url(value: str) -> str:
    clean = value.strip()
    if not clean:
        return DEFAULT_OLLAMA_BASE_URL
    return clean.rstrip("/")


def _ollama_chat_url(base_url: str) -> str:
    if base_url.rstrip("/").endswith("/api"):
        return f"{base_url.rstrip('/')}/chat"
    return f"{base_url.rstrip('/')}/api/chat"


def _requires_cloud_auth(base_url: str) -> bool:
    parsed = urlparse(base_url)
    return parsed.scheme == "https" and parsed.netloc.lower() == "ollama.com"


def _blank_to_none(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip()
