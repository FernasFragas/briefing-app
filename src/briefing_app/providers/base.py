from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
import json
from typing import Any
from urllib.error import HTTPError, URLError

from briefing_app.http import Fetcher, UrlLibFetcher
from briefing_app.providers.budget import (
    BUDGET_EXHAUSTED,
    BudgetExhausted,
    RequestBudget,
    is_plan_gate_notice,
)
from briefing_app.provider_validation import (
    MALFORMED,
    MISSING,
    OK,
    PAYWALLED,
    PLACEHOLDER,
    THROTTLED,
    ValidationResult,
    SYNTHETIC,
    is_quota_notice,
    validate_payload,
    validate_text_data_payload,
    validate_text_payload,
)
from briefing_app.raw_cache import RawCache
from briefing_app.settings import AppSettings


NO_CREDENTIALS = "no_credentials"
NETWORK_ERROR = "network_error"
PLAN_GATED = "plan_gated"

#: The only statuses that may retire an endpoint. A plan-gate memo outlives the process,
#: so it is driven by what the refusal *is*, never by wording alone: a throttled response
#: whose body happens to upsell ("Upgrade your plan for higher limits") reads like a gate
#: on phrases but is a rate signal by definition, and HTTP 429 says so in the status line.
ENTITLEMENT_STATUSES = frozenset({PAYWALLED, SYNTHETIC, PLAN_GATED})


class ProviderDataError(RuntimeError):
    def __init__(self, provider: str, endpoint: str, status: str, notes: tuple[str, ...]):
        self.provider = provider
        self.endpoint = endpoint
        self.status = status
        self.notes = notes
        super().__init__(f"{provider}.{endpoint} failed validation: {status}: {'; '.join(notes)}")


@dataclass(frozen=True)
class ProviderResponse:
    provider: str
    endpoint: str
    target: str
    url: str | None
    payload: Any
    cache_path: str | None
    validation: ValidationResult
    fetched_at: datetime
    status_code: int | None = None


class BaseProviderClient:
    provider_id: str

    #: Cache endpoints this provider serves only on a paid plan. On the free plan they
    #: answer HTTP 200 with a refusal notice, which costs a request from the daily
    #: budget and yields nothing, so they are refused before the request is sent.
    premium_endpoints: frozenset[str] = frozenset()

    def __init__(
        self,
        settings: AppSettings | None = None,
        cache: RawCache | None = None,
        fetcher: Fetcher | None = None,
        budget: RequestBudget | None = None,
    ) -> None:
        self.settings = settings or AppSettings.from_env()
        self.cache = cache or RawCache(self.settings.data_dir)
        self.fetcher = fetcher or UrlLibFetcher()
        self.budget = budget or RequestBudget(self.settings.data_dir)

    @property
    def plan(self) -> str:
        return self.settings.provider_plan(self.provider_id)

    def _guard_request(self, endpoint: str) -> None:
        """Refuse a request the plan cannot serve or the daily budget cannot afford.

        Both refusals happen before the request is sent, so neither spends quota.
        """

        if self.plan == "free" and endpoint in self.premium_endpoints:
            raise ProviderDataError(
                self.provider_id,
                endpoint,
                PLAN_GATED,
                (
                    f"{self.provider_id}.{endpoint} requires a paid plan; "
                    f"{self.provider_id.upper()}_PLAN is 'free'.",
                ),
            )
        if endpoint in self.budget.plan_gated_endpoints(self.provider_id):
            raise ProviderDataError(
                self.provider_id,
                endpoint,
                PLAN_GATED,
                (
                    f"{self.provider_id}.{endpoint} was previously refused as plan-gated "
                    f"for this key; delete "
                    f"{self.budget.plan_gate_path(self.provider_id)} to re-probe.",
                ),
            )
        try:
            self.budget.reserve(self.provider_id, endpoint, plan=self.plan)
        except BudgetExhausted as exc:
            raise ProviderDataError(
                self.provider_id, endpoint, BUDGET_EXHAUSTED, (str(exc),)
            ) from exc

    def fetch_json_url(
        self,
        *,
        endpoint: str,
        target: str,
        url: str,
        run_date: date,
        required_json_paths: tuple[str, ...] = (),
        validation_provider_id: str | None = None,
        cache_only: bool = False,
        fail_on_invalid: bool = True,
    ) -> ProviderResponse:
        if cache_only:
            payload = self.cache.read_json(self.provider_id, endpoint, run_date, target)
            cache_path = self.cache.path(self.provider_id, endpoint, run_date, target)
            validation = validate_payload(
                payload,
                required_json_paths,
                validation_provider_id or self.provider_id,
            )
            return self._response(
                endpoint, target, url, payload, str(cache_path), validation, fail_on_invalid
            )

        self._guard_request(endpoint)
        try:
            fetch_result = self.fetcher.fetch(
                url,
                self.settings.http_timeout_seconds,
                {"User-Agent": self.settings.user_agent, "Accept": "application/json,text/*,*/*"},
            )
        except HTTPError as exc:
            validation = _http_error_validation(exc)
            return self._response(endpoint, target, url, None, None, validation, fail_on_invalid)
        except (TimeoutError, URLError) as exc:
            validation = ValidationResult(NETWORK_ERROR, False, (f"Network error: {exc}",))
            return self._response(endpoint, target, url, None, None, validation, fail_on_invalid)

        payload = _decode_response(fetch_result.body, fetch_result.headers)
        validation = validate_payload(
            payload,
            required_json_paths,
            validation_provider_id or self.provider_id,
        )
        cache_path = self._cache_valid_payload(
            endpoint, target, run_date, payload, validation
        )
        return self._response(
            endpoint,
            target,
            fetch_result.url,
            payload,
            cache_path,
            validation,
            fail_on_invalid,
            status_code=fetch_result.status_code,
        )

    def fetch_text_url(
        self,
        *,
        endpoint: str,
        target: str,
        url: str,
        run_date: date,
        cache_only: bool = False,
        fail_on_invalid: bool = True,
    ) -> ProviderResponse:
        if cache_only:
            payload = self.cache.read_json(self.provider_id, endpoint, run_date, target)
            cache_path = self.cache.path(self.provider_id, endpoint, run_date, target)
            text = payload if isinstance(payload, str) else json.dumps(payload)
            validation = validate_text_data_payload(text)
            return self._response(endpoint, target, url, text, str(cache_path), validation, fail_on_invalid)

        self._guard_request(endpoint)
        try:
            fetch_result = self.fetcher.fetch(
                url,
                self.settings.http_timeout_seconds,
                {"User-Agent": self.settings.user_agent, "Accept": "text/*,*/*"},
            )
        except HTTPError as exc:
            validation = _http_error_validation(exc)
            return self._response(endpoint, target, url, None, None, validation, fail_on_invalid)
        except (TimeoutError, URLError) as exc:
            validation = ValidationResult(NETWORK_ERROR, False, (f"Network error: {exc}",))
            return self._response(endpoint, target, url, None, None, validation, fail_on_invalid)

        text = fetch_result.body.decode("utf-8", errors="replace")
        validation = validate_text_data_payload(text)
        cache_path = self._cache_valid_payload(
            endpoint, target, run_date, text, validation
        )
        return self._response(
            endpoint,
            target,
            fetch_result.url,
            text,
            cache_path,
            validation,
            fail_on_invalid,
            status_code=fetch_result.status_code,
        )

    def _cache_valid_payload(
        self,
        endpoint: str,
        target: str,
        run_date: date,
        payload: Any,
        validation: ValidationResult,
    ) -> str | None:
        """Cache a payload only once it has been validated.

        The cache is the `cache_only` replay source, so writing before validating lets a
        refusal overwrite the day's good payload — and providers answer a spent quota with
        HTTP 200, so the refusal arrives looking like a normal response. A late run on an
        exhausted budget would otherwise destroy the morning's data and replay the notice
        in its place. The refusal is not lost: it reaches the evidence ledger through the
        validation notes.
        """

        if not validation.ok:
            return None
        return str(
            self.cache.write_json(self.provider_id, endpoint, run_date, target, payload)
        )

    def _response(
        self,
        endpoint: str,
        target: str,
        url: str | None,
        payload: Any,
        cache_path: str | None,
        validation: ValidationResult,
        fail_on_invalid: bool,
        *,
        status_code: int | None = None,
    ) -> ProviderResponse:
        if (
            not validation.ok
            and validation.status in ENTITLEMENT_STATUSES
            and is_plan_gate_notice(validation.notes)
        ):
            # The key cannot reach this endpoint at all. Remember it so the next run
            # spends its quota on endpoints that can actually answer.
            self.budget.note_plan_gated(
                self.provider_id, endpoint, "; ".join(validation.notes)
            )
        if fail_on_invalid and not validation.ok:
            raise ProviderDataError(self.provider_id, endpoint, validation.status, validation.notes)
        return ProviderResponse(
            provider=self.provider_id,
            endpoint=endpoint,
            target=target,
            url=url,
            payload=payload,
            cache_path=cache_path,
            validation=validation,
            fetched_at=datetime.now(UTC),
            status_code=status_code,
        )


def require_credential(settings: AppSettings, env_name: str, provider: str) -> str:
    credential = settings.credential(env_name)
    if not credential:
        raise ProviderDataError(
            provider,
            "credential",
            NO_CREDENTIALS,
            (f"Missing credential: {env_name}.",),
        )
    return credential


def _decode_response(body: bytes, headers: dict[str, str]) -> Any:
    text = body.decode("utf-8", errors="replace")
    if "json" in headers.get("Content-Type", "").lower():
        return json.loads(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _http_error_validation(exc: HTTPError) -> ValidationResult:
    """Build a validation result from an HTTP error, keeping the provider's own words.

    `urlopen` raises on 4xx/5xx, so the explanatory body hangs off the exception rather
    than a response. Discarding it reduces every refusal to a bare status code — and FMP
    answers a gated endpoint, an uncovered symbol, a bad parameter and a spent quota all
    with the same code, distinguishable only by that body.
    """

    notes = (f"HTTP {exc.code}: {exc.reason}",)
    body = _read_error_body(exc)
    status = _status_from_http_code(exc.code)
    if body:
        notes += (body,)
        # The body outranks the code. FMP sends 402 for a gated endpoint, an uncovered
        # symbol, a bad parameter and sometimes a spent quota, so reading the code alone
        # can label a refusal that clears at midnight as one that needs a paid plan —
        # which is the difference between waiting and retiring a working source.
        if is_quota_notice(body):
            status = THROTTLED
    return ValidationResult(status, False, notes)


def _read_error_body(exc: HTTPError, *, limit: int = 400) -> str:
    try:
        raw = exc.read()
    except Exception:  # noqa: BLE001 - the stream may be consumed, closed, or absent.
        return ""
    if not raw:
        return ""
    return raw.decode("utf-8", errors="replace").strip()[:limit]


def _status_from_http_code(status_code: int) -> str:
    if status_code == 429:
        return THROTTLED
    if status_code in {401, 402, 403}:
        return PAYWALLED
    if status_code == 404:
        return MISSING
    if status_code >= 500:
        return NETWORK_ERROR
    return MALFORMED
