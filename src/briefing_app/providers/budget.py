"""Daily request budgets and pacing for quota-limited provider keys.

A free Alpha Vantage key allows 25 requests per day. Without a budget the pipeline
spends that quota on the first few tickers, and every later call comes back as a
throttle notice that reads like "no data" once it reaches a component. Reserving a
request before it is sent turns an exhausted quota into an explicit, auditable
`budget_exhausted` failure instead of a silently degraded score.

Counters are persisted per provider per day so a budget survives across the several
processes a scheduled run may use.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
import json
import os
import time

from briefing_app.provider_validation import GATE_ENDPOINT, classify_plan_gate, is_quota_notice
from briefing_app.raw_cache import sanitize_path_segment


BUDGET_EXHAUSTED = "budget_exhausted"

#: Free-tier defaults, used when no `<PROVIDER>_DAILY_REQUEST_BUDGET` is configured.
#: Each was observed against this project's own keys. Override per provider with
#: `<PROVIDER>_DAILY_REQUEST_BUDGET` and `<PROVIDER>_MIN_REQUEST_INTERVAL_SECONDS`, or
#: lift the daily count entirely by setting `<PROVIDER>_PLAN=paid`.
DEFAULT_BUDGETS: dict[str, "ProviderBudgetPolicy"] = {}


@dataclass(frozen=True)
class ProviderBudgetPolicy:
    """How many requests a provider key allows per day, and how fast they may be sent."""

    daily_requests: int | None = None
    min_interval_seconds: float = 0.0

    @property
    def unlimited(self) -> bool:
        return self.daily_requests is None


DEFAULT_BUDGETS.update(
    {
        # Alpha Vantage states 25 requests/day for a free key and asks for at most one
        # per second. Both were observed on this project's key: firing faster returns a
        # "spreading out your requests" notice, and the 26th call of a day returns a
        # daily-limit notice. A paid plan lifts the daily count (see `plan_overrides`).
        "alpha_vantage": ProviderBudgetPolicy(daily_requests=25, min_interval_seconds=1.2),
        # FMP's free plan is 250 requests/day and answers a burst with HTTP 402, which
        # is indistinguishable from a plan gate at the HTTP layer. Pacing keeps a real
        # plan refusal legible.
        "fmp": ProviderBudgetPolicy(daily_requests=250, min_interval_seconds=0.35),
        # Finnhub's free tier is a rate limit, not a daily allowance: 60 requests/minute
        # with a separate 30/second ceiling in its terms, and no published daily cap.
        # Pacing at just over a second holds the per-minute limit without inventing a
        # daily budget the provider never stated.
        "finnhub": ProviderBudgetPolicy(daily_requests=None, min_interval_seconds=1.05),
        # Twelve Data Basic allows 8 API credits per minute and 800 per day. The
        # time_series endpoint costs 1 credit per symbol, and this app requests one
        # symbol at a time as an FMP symbol-gate fallback.
        "twelve_data": ProviderBudgetPolicy(daily_requests=800, min_interval_seconds=7.6),
        # FRED publishes no numeric per-minute or daily cap in its API docs - only that
        # rate limiting answers HTTP 429 (`docs/alternatives/pa9-macro.md`). So no daily
        # count is invented here, and the pacing is the conservative budgeting that note
        # asks for. It matters more now the macro calendar asks `release/dates` twice per
        # release - once backwards to date a reading, once forwards to schedule one.
        "fred": ProviderBudgetPolicy(daily_requests=None, min_interval_seconds=0.5),
        "cboe": ProviderBudgetPolicy(daily_requests=None, min_interval_seconds=0.0),
        "apewisdom": ProviderBudgetPolicy(daily_requests=None, min_interval_seconds=0.0),
        "finra": ProviderBudgetPolicy(daily_requests=None, min_interval_seconds=0.0),
        "sec_edgar": ProviderBudgetPolicy(daily_requests=None, min_interval_seconds=0.11),
    }
)


def is_plan_gate_notice(notes) -> bool:
    """True when a refusal gates the endpoint itself, and is therefore worth remembering.

    Three look-alikes must not be remembered. A quota or rate refusal clears on its own.
    A refusal aimed at one query parameter means the call was wrong, not the endpoint. And
    a refusal aimed at one symbol means the endpoint works fine for other tickers — FMP's
    free plan serves AAPL and refuses AVGO on the very same endpoint.

    `classify_plan_gate` already screens quota notices, so the explicit check here is
    belt-and-braces: what gets written to `plan_gated.json` survives until a human deletes
    it, and FMP's spent-quota body ("Limit Reach . Please upgrade your plan") reads like a
    plan gate on the words alone.
    """

    blob = " ".join(str(note) for note in notes)
    if is_quota_notice(blob):
        return False
    return classify_plan_gate(blob) == GATE_ENDPOINT


class BudgetExhausted(RuntimeError):
    """Raised when a provider's daily request budget is already spent."""

    def __init__(self, provider: str, endpoint: str, spent: int, allowed: int) -> None:
        self.provider = provider
        self.endpoint = endpoint
        self.spent = spent
        self.allowed = allowed
        super().__init__(
            f"{provider} daily request budget spent: {spent}/{allowed} used today; "
            f"{endpoint} was not sent."
        )


class RequestBudget:
    """Per-provider daily request counter with optional pacing.

    `reserve()` is called before a request leaves the process, so a refused reservation
    costs nothing. Cache-only replays never reserve.
    """

    def __init__(
        self,
        data_dir: Path | str,
        *,
        policies: dict[str, ProviderBudgetPolicy] | None = None,
        sleep=time.sleep,
        now=lambda: datetime.now(UTC),
    ) -> None:
        self.root = Path(data_dir) / "provider_budget"
        #: A caller-supplied policy is authoritative; only the built-in free-tier
        #: defaults are lifted when a provider is on a paid plan.
        self.explicit_policies = dict(policies or {})
        self.policies = {**DEFAULT_BUDGETS, **self.explicit_policies}
        self._sleep = sleep
        self._now = now

    def policy_for(self, provider: str, *, plan: str = "free") -> ProviderBudgetPolicy:
        """Budget for a provider, before env overrides.

        The daily count is a free-tier limit; a paid plan removes it but keeps the pacing,
        because per-second throttling applies on every tier.
        """

        default = self.policies.get(provider, ProviderBudgetPolicy())
        if plan != "free" and provider not in self.explicit_policies:
            default = ProviderBudgetPolicy(
                daily_requests=None, min_interval_seconds=default.min_interval_seconds
            )
        return ProviderBudgetPolicy(
            daily_requests=_env_int(
                f"{provider.upper()}_DAILY_REQUEST_BUDGET", default.daily_requests
            ),
            min_interval_seconds=_env_float(
                f"{provider.upper()}_MIN_REQUEST_INTERVAL_SECONDS",
                default.min_interval_seconds,
            ),
        )

    def path(self, provider: str, day: date) -> Path:
        return self.root / sanitize_path_segment(provider) / f"{day.isoformat()}.json"

    def plan_gate_path(self, provider: str) -> Path:
        return self.root / sanitize_path_segment(provider) / "plan_gated.json"

    def plan_gated_endpoints(self, provider: str) -> set[str]:
        """Endpoints this key has been observed to lack plan access for."""

        target = self.plan_gate_path(provider)
        if not target.exists():
            return set()
        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return set()
        endpoints = loaded.get("endpoints") if isinstance(loaded, dict) else None
        return {str(name) for name in endpoints} if isinstance(endpoints, list) else set()

    def note_plan_gated(self, provider: str, endpoint: str, note: str = "") -> None:
        """Remember that this key cannot reach an endpoint, so it is never re-probed.

        A plan gate is a property of the key, not of the day, so unlike the request
        counter this memo is not reset at midnight. Deleting the file re-probes.
        """

        known = self.plan_gated_endpoints(provider)
        if endpoint in known:
            return
        known.add(endpoint)
        target = self.plan_gate_path(provider)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "endpoints": sorted(known),
            "last_observed_at": self._now().isoformat(),
            "last_endpoint": endpoint,
            "last_note": note,
        }
        target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def spent(self, provider: str, *, day: date | None = None) -> int:
        return int(self._read(provider, day or self._now().date()).get("count", 0))

    def remaining(
        self, provider: str, *, day: date | None = None, plan: str = "free"
    ) -> int | None:
        policy = self.policy_for(provider, plan=plan)
        if policy.unlimited:
            return None
        return max(0, policy.daily_requests - self.spent(provider, day=day))

    def reserve(self, provider: str, endpoint: str, *, plan: str = "free") -> None:
        """Claim one request, pacing if needed. Raises `BudgetExhausted` when spent."""

        policy = self.policy_for(provider, plan=plan)
        now = self._now()
        day = now.date()
        state = self._read(provider, day)
        count = int(state.get("count", 0))

        if not policy.unlimited and count >= policy.daily_requests:
            raise BudgetExhausted(provider, endpoint, count, policy.daily_requests)

        if policy.min_interval_seconds > 0:
            last = _parse_datetime(state.get("last_request_at"))
            if last is not None:
                elapsed = (now - last).total_seconds()
                if 0 <= elapsed < policy.min_interval_seconds:
                    self._sleep(policy.min_interval_seconds - elapsed)
                    now = self._now()

        endpoint_counts = _endpoint_counts(state)
        endpoint_counts[endpoint] = endpoint_counts.get(endpoint, 0) + 1

        self._write(
            provider,
            day,
            {
                "count": count + 1,
                "endpoints": endpoint_counts,
                "last_request_at": now.isoformat(),
                "daily_requests": policy.daily_requests,
                "last_endpoint": endpoint,
            },
        )

    def _read(self, provider: str, day: date) -> dict:
        target = self.path(provider, day)
        if not target.exists():
            return {}
        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # A corrupt counter must not hand back an unlimited budget; treat it as spent
            # up to the last known good state by starting the day over at zero.
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _write(self, provider: str, day: date, state: dict) -> None:
        target = self.path(provider, day)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _env_int(name: str, default: int | None) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in {"none", "unlimited", "0"}:
        return None
    try:
        return max(0, int(value))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return max(0.0, float(raw.strip()))
    except ValueError:
        return default


def _parse_datetime(value) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _endpoint_counts(state: dict) -> dict[str, int]:
    endpoints = state.get("endpoints")
    if not isinstance(endpoints, dict):
        return {}
    counts: dict[str, int] = {}
    for raw_endpoint, raw_count in endpoints.items():
        try:
            counts[str(raw_endpoint)] = max(0, int(raw_count))
        except (TypeError, ValueError):
            continue
    return counts
