"""Throughput failures, and what the client does about them.

Every case here is drawn from live run `daily-2026-09-03-c7e82663`, recorded as
`PC1-RAW-15` through `PC1-RAW-19` in `docs/archive/still-failing.md`. All three
defects share a shape: the entitlement was fine, the provider answered, and the pipeline
still lost the reading because nothing remembered what the answer had been.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
import io
import json
import tempfile

import pytest

from briefing_app.http import HttpFetchResult
from briefing_app.providers.base import (
    REPEAT_REFUSAL,
    BaseProviderClient,
    ProviderDataError,
)
from briefing_app.providers.budget import (
    BUDGET_EXHAUSTED,
    ProviderBudgetPolicy,
    RequestBudget,
)
from briefing_app.settings import AppSettings


RUN_DATE = date(2026, 9, 3)


def make_settings(tmp: Path, *, retries: int = 2) -> AppSettings:
    return AppSettings(
        config_path=Path("config/config.example.yaml"),
        source_registry_path=Path("config/source_registry.yaml"),
        data_dir=tmp / "data",
        output_dir=tmp / "output",
        http_timeout_seconds=1,
        user_agent="briefing-app-test",
        alpha_vantage_api_key=None,
        fmp_api_key=None,
        # Hand-built settings default a provider to `paid`, which lifts the daily count.
        # Every case here is about free-tier metering, so the plan is declared.
        provider_plans={"fmp": "free", "finnhub": "free"},
        network_retries=retries,
        network_retry_backoff_seconds=0.0,
    )


class ProbeClient(BaseProviderClient):
    """A client that is nothing but the base behaviour under test."""

    provider_id = "fmp"


class UnlimitedProbeClient(BaseProviderClient):
    """A provider whose limit is a per-minute rate, so it declares no daily allowance."""

    provider_id = "finnhub"


class ScriptedFetcher:
    """Replays a script of outcomes, one per call, recording how many were sent."""

    def __init__(self, *outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def fetch(self, url: str, timeout_seconds: float, headers: dict[str, str]):
        self.calls += 1
        outcome = self.outcomes[min(self.calls - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, bytes):
            return HttpFetchResult(200, outcome, {"Content-Type": "text/csv"}, url)
        return HttpFetchResult(
            200, json.dumps(outcome).encode("utf-8"), {"Content-Type": "application/json"}, url
        )


def throttled(url: str = "https://example.test/x") -> HTTPError:
    """FMP's own 2026-09-03 refusal, verbatim."""

    return HTTPError(
        url,
        429,
        "Too Many Requests",
        {},
        io.BytesIO(
            b'{"Error Message": "Limit Reach . Please upgrade your plan or visit our '
            b'documentation for more details at https://site.financialmodelingprep.com/"}'
        ),
    )


def build(tmp: str, fetcher, *, client=ProbeClient, retries: int = 2, sleeps=None):
    settings = make_settings(Path(tmp), retries=retries)
    budget = RequestBudget(settings.data_dir, sleep=lambda _s: None)
    return client(
        settings=settings,
        fetcher=fetcher,
        budget=budget,
        sleep=(sleeps.append if sleeps is not None else (lambda _s: None)),
    )


def fetch(client, *, endpoint: str = "grades_consensus", target: str = "AAPL"):
    return client.fetch_json_url(
        endpoint=endpoint,
        target=target,
        url=f"https://example.test/{endpoint}/{target}",
        run_date=RUN_DATE,
        fail_on_invalid=False,
    )


def fetch_text(client, *, endpoint: str = "earnings_calendar", target: str = "AAPL"):
    return client.fetch_text_url(
        endpoint=endpoint,
        target=target,
        url=f"https://example.test/{endpoint}/{target}",
        run_date=RUN_DATE,
        fail_on_invalid=False,
    )


#: Alpha Vantage's free-tier `EARNINGS_CALENDAR` reply, which is a refusal wearing the
#: shape of a CSV: one character per column, so every row is one field wide.
DEGENERATE_CSV = b"I,n,f,o,r,m,a\nt,i,o,n,:, ,p\n"


# --- PC1-RAW-16: the provider's refusal outranks the configured ceiling ----------------


def test_a_throttle_records_the_providers_own_ceiling_for_the_day() -> None:
    """FMP said stop at a counter reading the configured 250 said was fine."""

    with tempfile.TemporaryDirectory() as tmp:
        client = build(tmp, ScriptedFetcher(throttled()))
        response = fetch(client)

        assert response.validation.status == "throttled"
        learned = client.budget.quota_exhausted("fmp")
        assert learned is not None
        assert learned["endpoint"] == "grades_consensus"
        assert learned["configured_limit"] == 250
        # One request had been reserved before it was sent, so the observed count is 1 -
        # nowhere near 250, which is the entire point of recording it.
        assert learned["observed_count"] == 1
        assert "Limit Reach" in learned["note"]


def test_the_rest_of_the_day_stops_at_the_learned_ceiling_not_the_configured_one() -> None:
    """The 2026-09-03 defect: 57 further requests were sent after the first refusal."""

    with tempfile.TemporaryDirectory() as tmp:
        fetcher = ScriptedFetcher(throttled())
        client = build(tmp, fetcher)
        fetch(client, target="AAPL")
        assert fetcher.calls == 1

        # A different ticker, and a different endpoint, on the same key and the same day.
        # The refusal happens in the guard, before the request, so it raises.
        for endpoint, target in (("grades_consensus", "MSFT"), ("earnings_calendar", "DE")):
            with pytest.raises(ProviderDataError) as exc:
                fetch(client, endpoint=endpoint, target=target)
            assert exc.value.status == BUDGET_EXHAUSTED

        assert fetcher.calls == 1, "no request may be sent after the provider said stop"


def test_the_learned_ceiling_survives_into_a_second_run_the_same_day() -> None:
    """It is written beside the counter, so a second process inherits it.

    Two full live runs on 2026-09-03 is what exhausted FMP in the first place; the second
    one must not have to rediscover the limit ticker by ticker.
    """

    with tempfile.TemporaryDirectory() as tmp:
        first = ScriptedFetcher(throttled())
        fetch(build(tmp, first))

        second = ScriptedFetcher({"ok": True})
        with pytest.raises(ProviderDataError) as exc:
            fetch(build(tmp, second), target="NVDA")

        assert second.calls == 0
        assert exc.value.status == BUDGET_EXHAUSTED
        # The message carries the provider's number, not the configured one.
        assert "1 used today" in str(exc.value)


def test_a_rate_limited_provider_is_paced_and_never_retired_for_the_day() -> None:
    """Finnhub's limit is 60/minute. Retiring it for a day would invent an outage."""

    with tempfile.TemporaryDirectory() as tmp:
        fetcher = ScriptedFetcher(throttled(), {"ok": True})
        client = build(tmp, fetcher, client=UnlimitedProbeClient)

        first = fetch(client, endpoint="recommendation_trends")
        assert first.validation.status == "throttled"
        assert client.budget.quota_exhausted("finnhub") is None

        second = fetch(client, endpoint="recommendation_trends", target="MSFT")
        assert second.validation.ok
        assert fetcher.calls == 2


def test_the_counter_keeps_incrementing_after_the_ceiling_is_learned() -> None:
    """A learned ceiling must not silently reset the day's spend."""

    with tempfile.TemporaryDirectory() as tmp:
        client = build(tmp, ScriptedFetcher(throttled()))
        fetch(client)
        assert client.budget.spent("fmp") == 1
        assert client.budget.quota_exhausted("fmp") is not None


# --- PC1-RAW-15: a timeout is not an answer -------------------------------------------


def test_a_transient_timeout_is_retried_and_the_reading_survives() -> None:
    """Five FRED calls timed out on 2026-09-03 and 23 tickers lost the reading."""

    with tempfile.TemporaryDirectory() as tmp:
        fetcher = ScriptedFetcher(TimeoutError("The read operation timed out"), {"value": 1})
        client = build(tmp, fetcher)
        response = fetch(client)

        assert response.validation.ok
        assert response.payload == {"value": 1}
        assert fetcher.calls == 2


def test_retries_back_off_and_give_up_with_the_attempt_count_named() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        sleeps: list[float] = []
        fetcher = ScriptedFetcher(URLError("timed out"))
        client = build(tmp, fetcher, retries=2, sleeps=sleeps)
        client.settings = client.settings.__class__(
            **{**client.settings.__dict__, "network_retry_backoff_seconds": 0.5}
        )
        response = fetch(client)

        assert response.validation.status == "network_error"
        assert "gave up after 3 attempts" in response.validation.notes[0]
        assert fetcher.calls == 3
        # Backoff doubles rather than hammering a source that is already struggling.
        assert sleeps == [0.5, 1.0]


def test_an_http_refusal_is_never_retried() -> None:
    """A refusal is the provider's considered reply; re-sending spends quota to be told
    the same thing, and on a metered key that is how one outage becomes three."""

    with tempfile.TemporaryDirectory() as tmp:
        fetcher = ScriptedFetcher(
            HTTPError("https://example.test/x", 402, "Payment Required", {}, io.BytesIO(b""))
        )
        client = build(tmp, fetcher)
        response = fetch(client)

        assert response.validation.status == "paywalled"
        assert fetcher.calls == 1


def test_every_retry_attempt_meters() -> None:
    """PB8: a retry is a real request. Three attempts is three reservations."""

    with tempfile.TemporaryDirectory() as tmp:
        fetcher = ScriptedFetcher(TimeoutError("timed out"))
        client = build(tmp, fetcher, retries=2)
        fetch(client)
        assert client.budget.spent("fmp") == 3


def test_retrying_stops_when_the_budget_runs_out_mid_attempt() -> None:
    """The exhaustion is what happened, so the exhaustion is what gets reported."""

    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp), retries=5)
        budget = RequestBudget(
            settings.data_dir,
            policies={"fmp": ProviderBudgetPolicy(daily_requests=2)},
            sleep=lambda _s: None,
        )
        fetcher = ScriptedFetcher(TimeoutError("timed out"))
        client = ProbeClient(
            settings=settings, fetcher=fetcher, budget=budget, sleep=lambda _s: None
        )

        with pytest.raises(ProviderDataError) as exc:
            client.fetch_json_url(
                endpoint="grades_consensus",
                target="AAPL",
                url="https://example.test/x",
                run_date=RUN_DATE,
            )

        assert exc.value.status == BUDGET_EXHAUSTED
        assert fetcher.calls == 2


def test_retries_can_be_switched_off() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        fetcher = ScriptedFetcher(TimeoutError("timed out"))
        response = fetch(build(tmp, fetcher, retries=0))
        assert fetcher.calls == 1
        assert "gave up" not in response.validation.notes[0]


# --- PC1-RAW-17: a refusal that repeats is worth remembering for the run ---------------


def test_a_repeated_malformed_body_parks_the_endpoint_for_the_run() -> None:
    """Alpha Vantage's EARNINGS_CALENDAR refuses every time on a free key.

    `malformed` is deliberately outside `ENTITLEMENT_STATUSES`, so nothing retired it and
    the 2026-09-03 run re-sent it per ticker until the day's 25 requests were gone.
    """

    with tempfile.TemporaryDirectory() as tmp:
        fetcher = ScriptedFetcher(DEGENERATE_CSV)
        client = build(tmp, fetcher)

        first = fetch_text(client, target="AMAT")
        second = fetch_text(client, target="AVGO")
        assert first.validation.status == "malformed"
        assert second.validation.status == "malformed"
        assert fetcher.calls == 2

        # Parking refuses before the request is sent, so - like a plan gate - it raises
        # rather than returning a response the caller might mistake for data.
        with pytest.raises(ProviderDataError) as exc:
            client.fetch_text_url(
                endpoint="earnings_calendar",
                target="LMT",
                url="https://example.test/x",
                run_date=RUN_DATE,
            )
        assert exc.value.status == REPEAT_REFUSAL
        assert fetcher.calls == 2, "the third ticker must not cost a request"
        assert client.budget.spent("fmp") == 2


def test_parking_is_per_endpoint_and_per_run() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        fetcher = ScriptedFetcher(DEGENERATE_CSV, DEGENERATE_CSV, {"ok": 1})
        client = build(tmp, fetcher)
        fetch_text(client, target="AMAT")
        fetch_text(client, target="AVGO")

        # A different endpoint on the same client is untouched.
        other = fetch(client, endpoint="grades_consensus", target="AMAT")
        assert other.validation.ok

        # And a new client - meaning a new run - asks again.
        fresh = build(tmp, ScriptedFetcher(b"date,symbol\n2026-09-04,AAPL\n"))
        assert fetch_text(fresh, target="AMAT").validation.ok


def test_a_success_clears_the_refusal_count() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        good = b"date,symbol\n2026-09-04,AAPL\n"
        fetcher = ScriptedFetcher(DEGENERATE_CSV, good, DEGENERATE_CSV)
        client = build(tmp, fetcher)
        for target in ("A", "B", "C"):
            fetch_text(client, target=target)
        # One refusal, one success, one refusal: never two in a row, so never parked.
        assert fetcher.calls == 3


def test_a_missing_payload_never_parks_an_endpoint() -> None:
    """"Root payload is empty" is how three providers answer for QQQ and SPY.

    That is a property of those symbols, not of the endpoint. Parking on it would silence
    a working endpoint for every issuer in the universe.
    """

    with tempfile.TemporaryDirectory() as tmp:
        fetcher = ScriptedFetcher({}, {}, {"ok": 1})
        client = build(tmp, fetcher)
        for target in ("QQQ", "SPY"):
            response = client.fetch_json_url(
                endpoint="grades_consensus",
                target=target,
                url="https://example.test/x",
                run_date=RUN_DATE,
                required_json_paths=("ok",),
                fail_on_invalid=False,
            )
            assert response.validation.status == "missing"

        assert fetch(client, endpoint="grades_consensus", target="AAPL").validation.ok
        assert fetcher.calls == 3


def test_a_parked_endpoint_costs_no_budget() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        client = build(tmp, ScriptedFetcher(DEGENERATE_CSV))
        for target in ("A", "B", "C", "D", "E"):
            try:
                fetch_text(client, target=target)
            except ProviderDataError as exc:
                assert exc.status == REPEAT_REFUSAL
        assert client.budget.spent("fmp") == 2
