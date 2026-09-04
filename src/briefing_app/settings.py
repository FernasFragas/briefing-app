from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path


#: Provider plan tiers. `free` refuses known paid-plan endpoints before a request is
#: sent, so a metered key is never spent on a refusal notice.
PLAN_FREE = "free"
PLAN_PAID = "paid"
DEFAULT_PROVIDER_PLANS = {
    "alpha_vantage": PLAN_FREE,
    "fmp": PLAN_FREE,
    "finnhub": PLAN_FREE,
    "twelve_data": PLAN_FREE,
}


@dataclass(frozen=True)
class AppSettings:
    config_path: Path
    source_registry_path: Path
    data_dir: Path
    output_dir: Path
    http_timeout_seconds: float
    user_agent: str
    alpha_vantage_api_key: str | None
    fmp_api_key: str | None
    #: Defaulted rather than required, so existing constructions keep working. A blank key
    #: reports `no_credentials` at preflight instead of failing a run.
    fred_api_key: str | None = None
    finnhub_api_key: str | None = None
    twelve_data_api_key: str | None = None
    provider_plans: dict[str, str] = field(default_factory=dict)
    #: Extra attempts for a request that failed with a transport error rather than a
    #: refusal. On 2026-09-03 five FRED calls timed out and every one of the 23 scored
    #: tickers lost the reading, because a single slow response had no second chance —
    #: `providers/base.py` retries only what a retry can actually fix.
    network_retries: int = 2
    network_retry_backoff_seconds: float = 0.75

    @classmethod
    def from_env(cls) -> "AppSettings":
        config_path = Path(
            os.getenv("BRIEFING_CONFIG_PATH", "config/config.example.yaml")
        )
        source_registry_path = Path(
            os.getenv("BRIEFING_SOURCE_REGISTRY_PATH", "config/source_registry.yaml")
        )
        data_dir = Path(os.getenv("BRIEFING_DATA_DIR", "data"))
        output_dir = Path(os.getenv("BRIEFING_OUTPUT_DIR", "output"))
        timeout_raw = os.getenv("BRIEFING_HTTP_TIMEOUT_SECONDS", "10")

        return cls(
            config_path=config_path,
            source_registry_path=source_registry_path,
            data_dir=data_dir,
            output_dir=output_dir,
            http_timeout_seconds=float(timeout_raw),
            user_agent=os.getenv(
                "BRIEFING_USER_AGENT", "briefing-app/0.1 contact@example.com"
            ),
            alpha_vantage_api_key=_blank_to_none(os.getenv("ALPHA_VANTAGE_API_KEY")),
            fmp_api_key=_blank_to_none(os.getenv("FMP_API_KEY")),
            fred_api_key=_blank_to_none(os.getenv("FRED_API_KEY")),
            finnhub_api_key=_blank_to_none(os.getenv("FINNHUB_API_KEY")),
            twelve_data_api_key=_blank_to_none(os.getenv("TWELVE_DATA_API_KEY")),
            provider_plans={
                provider: _plan_from_env(f"{provider.upper()}_PLAN", default)
                for provider, default in DEFAULT_PROVIDER_PLANS.items()
            },
            network_retries=max(0, int(os.getenv("BRIEFING_NETWORK_RETRIES", "2"))),
            network_retry_backoff_seconds=max(
                0.0, float(os.getenv("BRIEFING_NETWORK_RETRY_BACKOFF_SECONDS", "0.75"))
            ),
        )

    def provider_plan(self, provider_id: str) -> str:
        """Plan tier for a provider.

        Settings built by hand declare no plans and are therefore ungated; `from_env`
        always populates every known provider, defaulting to `free` so a real run never
        spends a metered key on an endpoint the plan cannot serve.
        """

        return self.provider_plans.get(provider_id, PLAN_PAID)

    def credential(self, env_name: str | None) -> str | None:
        if env_name == "ALPHA_VANTAGE_API_KEY":
            return self.alpha_vantage_api_key
        if env_name == "FMP_API_KEY":
            return self.fmp_api_key
        if env_name == "FRED_API_KEY":
            return self.fred_api_key or _blank_to_none(os.getenv(env_name))
        if env_name == "FINNHUB_API_KEY":
            return self.finnhub_api_key or _blank_to_none(os.getenv(env_name))
        if env_name == "TWELVE_DATA_API_KEY":
            return self.twelve_data_api_key or _blank_to_none(os.getenv(env_name))
        if not env_name:
            return None
        return _blank_to_none(os.getenv(env_name))


def _plan_from_env(env_name: str, default: str) -> str:
    raw = _blank_to_none(os.getenv(env_name))
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {PLAN_PAID, "premium", "pro", "paid_plan"}:
        return PLAN_PAID
    if value == PLAN_FREE:
        return PLAN_FREE
    return default


def _blank_to_none(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value
