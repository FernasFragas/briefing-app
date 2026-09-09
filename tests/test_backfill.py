from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from sqlalchemy import create_engine, select

from briefing_app.backfill import (
    BACKFILL_RUN_TYPE,
    DEFAULT_COMPLETED_RUN_RESERVE,
    DEFAULT_LIVE_RUN_RESERVE,
    MAX_CONSECUTIVE_FAILURES,
    build_backfill_snapshot_row,
    plan_budget_reservation,
    run_iv_backfill,
    session_dates,
    snapshot_row_from_structure,
    vendor_splice_report,
)
from briefing_app.config import AppConfig
from briefing_app.http import HttpFetchResult
from briefing_app.models.candidate import ExpressionClass
from briefing_app.models.market_data import OptionFilterConfig, ValidationStatus
from briefing_app.models.scoring import ScoringResult
from briefing_app.options_math import build_options_structure
from briefing_app.provider_validation import OK, ValidationResult
from briefing_app.providers.alpha_vantage import AlphaVantageClient
from briefing_app.providers.base import ProviderDataError, ProviderResponse
from briefing_app.providers.budget import ProviderBudgetPolicy, RequestBudget
from briefing_app.providers.normalizers import normalize_alpha_vantage_options_chain
from briefing_app.scoring import to_daily_snapshot_row
from briefing_app.settings import AppSettings
from briefing_app.storage import StorageRepository, briefing_run, create_schema


def test_backfilled_metrics_reproduce_stored_live_metrics_to_full_precision() -> None:
    config = AppConfig.model_validate({})
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    create_schema(engine)
    repo = StorageRepository(engine)
    snap_date = date(2026, 9, 3)
    run_id = repo.upsert_briefing_run(
        run_date=snap_date,
        status="succeeded",
        details={"data_mode": "live"},
    )
    payload = _alpha_options_payload(snap_date, spot=100.0, iv=0.42)
    filters = OptionFilterConfig.model_validate(config.option_filters.model_dump())
    chain = normalize_alpha_vantage_options_chain(
        "NVDA",
        payload,
        filters=filters,
        endpoint_or_file="live-realtime-options.json",
        reference_time=datetime(2026, 9, 3, 20, tzinfo=UTC),
    )
    live_structure = build_options_structure(
        ticker="NVDA",
        spot=chain.spot,
        as_of=chain.as_of,
        option_quotes=chain,
        price_bars=(),
        chain_verified=(
            chain.validation_status is ValidationStatus.VERIFIED and bool(chain.contracts)
        ),
        run_id=run_id,
        source=chain.source,
        venue=chain.venue,
        endpoint_or_file=chain.endpoint_or_file,
        validation_status=chain.validation_status.value,
    )
    live_row = snapshot_row_from_structure(
        live_structure,
        snap_date=snap_date,
        run_id=run_id,
        raw={"source_kind": "live"},
    )
    repo.upsert_daily_snapshot(live_row)

    backfilled = build_backfill_snapshot_row(
        "NVDA",
        snap_date,
        payload,
        config=config,
        endpoint_or_file="historical-options.json",
        fetched_at=datetime(2026, 9, 4, 9, tzinfo=UTC),
    )
    stored_live = repo.daily_snapshot_for("NVDA", snap_date)

    assert stored_live is not None
    for field in ("iv_atm", "pc_ratio_vol", "pc_ratio_oi", "expected_move_1w"):
        assert backfilled[field] == live_row[field]
        assert round(backfilled[field], 10) == stored_live[field]
    assert backfilled["raw"]["backfill"]["computed_with"] == [
        "briefing_app.providers.normalizers.normalize_alpha_vantage_options_chain",
        "briefing_app.options_math.build_options_structure",
    ]


def test_backfill_resumes_by_skipping_complete_metric_rows(tmp_path: Path) -> None:
    config = AppConfig.model_validate({})
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    create_schema(engine)
    repo = StorageRepository(engine)
    run_id = repo.upsert_briefing_run(
        run_date=date(2026, 9, 3),
        status="succeeded",
        details={"data_mode": "live"},
    )
    repo.upsert_daily_snapshot(
        {
            "run_id": run_id,
            "ticker": "NVDA",
            "snap_date": date(2026, 9, 3),
            "iv_atm": 0.40,
            "pc_ratio_vol": 0.80,
            "pc_ratio_oi": 0.90,
        }
    )
    client = FakeHistoricalOptionsClient()

    result = run_iv_backfill(
        config,
        repository=repo,
        settings=_settings(tmp_path),
        client=client,
        tickers=["NVDA"],
        run_date=date(2026, 9, 7),
        end_date=date(2026, 9, 4),
        sessions=2,
        # This test is about resuming, not about the two guards. Both are acknowledged
        # explicitly so the guard cannot pass by accident, and so that a reader sees the
        # acknowledgement rather than an unexplained green.
        live_run_reserve=0,
        allow_vendor_splice=True,
    )

    assert result.stored == 1
    assert result.skipped == 1
    assert client.calls == [("NVDA", date(2026, 9, 4), False)]
    row = repo.daily_snapshot_for("NVDA", date(2026, 9, 4))
    assert row is not None
    assert row["raw"]["source_kind"] == "iv_backfill"
    with engine.connect() as conn:
        run_type = conn.execute(
            select(briefing_run.c.run_type).where(briefing_run.c.id == result.storage_run_id)
        ).scalar_one()
    assert run_type == BACKFILL_RUN_TYPE

    second_client = FakeHistoricalOptionsClient()
    second = run_iv_backfill(
        config,
        repository=repo,
        settings=_settings(tmp_path),
        client=second_client,
        tickers=["NVDA"],
        run_date=date(2026, 9, 7),
        end_date=date(2026, 9, 4),
        sessions=2,
        live_run_reserve=0,
        allow_vendor_splice=True,
    )

    assert second.stored == 0
    assert second.skipped == 2
    assert second_client.calls == []


def test_provider_budget_refusal_mid_run_returns_progress_without_exception(
    tmp_path: Path,
) -> None:
    """A provider that names its real ceiling mid-run stops the backfill, not the process.

    Reworked for the J2 reservation. The backfill now stops at its own cap before it can
    reach a ceiling it already knows about, so the case still worth covering is the one
    the reservation cannot foresee: the provider refusing at a number lower than the
    configured allowance, which is exactly what FMP did on 2026-09-03. The fetcher below
    records that refusal after its first call, so the second request meets a budget that
    has learned the real ceiling.
    """

    config = AppConfig.model_validate({})
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    create_schema(engine)
    repo = StorageRepository(engine)
    settings = _settings(tmp_path)
    budget = RequestBudget(
        tmp_path,
        policies={
            "alpha_vantage": ProviderBudgetPolicy(
                daily_requests=5,
                min_interval_seconds=0.0,
            )
        },
        now=lambda: datetime(2026, 9, 7, 9, tzinfo=UTC),
    )
    client = AlphaVantageClient(
        settings=settings,
        fetcher=QuotaLearningFetcher(budget),
        budget=budget,
    )

    result = run_iv_backfill(
        config,
        repository=repo,
        settings=settings,
        client=client,
        budget=budget,
        tickers=["NVDA"],
        run_date=date(2026, 9, 7),
        end_date=date(2026, 9, 4),
        sessions=2,
        # The subject here is the provider's own budget refusal, so the backfill's
        # reservation is stood down deliberately rather than left to mask it.
        live_run_reserve=0,
        allow_vendor_splice=True,
    )

    assert result.stored == 1
    assert result.remaining == 1
    assert result.budget_exhausted is True
    assert any("budget spent" in item for item in result.diagnostics)


def test_dry_run_reports_plan_without_fetching_or_spending(tmp_path: Path) -> None:
    budget_day = date(2026, 9, 7)
    budget = RequestBudget(
        tmp_path,
        policies={"alpha_vantage": ProviderBudgetPolicy(daily_requests=25)},
        now=lambda: datetime(2026, 9, 7, 9, tzinfo=UTC),
    )

    result = run_iv_backfill(
        AppConfig.model_validate({}),
        settings=_settings(tmp_path),
        budget=budget,
        client=FailingHistoricalOptionsClient(),
        tickers=["NVDA", "MSFT"],
        run_date=budget_day,
        end_date=date(2026, 9, 4),
        sessions=2,
        dry_run=True,
    )

    assert result.status == "dry_run"
    assert result.requested_pairs == 4
    assert result.remaining == 4
    assert result.estimated_days_at_allowance == 1
    assert budget.spent("alpha_vantage", day=budget_day) == 0


def test_session_dates_are_weekdays_in_chronological_order() -> None:
    assert session_dates(end_date=date(2026, 9, 7), sessions=3) == (
        date(2026, 9, 3),
        date(2026, 9, 4),
        date(2026, 9, 7),
    )


class FakeHistoricalOptionsClient:
    def __init__(self, payload: dict | None = None) -> None:
        self.calls: list[tuple[str, date, bool]] = []
        self._payload = payload

    def fetch_historical_options(
        self,
        ticker: str,
        *,
        run_date: date,
        option_date: date | None = None,
        cache_only: bool = False,
    ) -> ProviderResponse:
        requested_date = option_date or run_date
        self.calls.append((ticker, requested_date, cache_only))
        return _response(
            ticker,
            requested_date,
            self._payload
            or _alpha_options_payload(requested_date, spot=100.0, iv=0.40),
        )


class FailingHistoricalOptionsClient:
    def fetch_historical_options(self, *args: object, **kwargs: object) -> ProviderResponse:
        raise AssertionError("dry-run must not fetch historical options")


class PayloadFetcher:
    def fetch(
        self,
        url: str,
        timeout_seconds: float,
        headers: dict[str, str],
    ) -> HttpFetchResult:
        params = parse_qs(urlparse(url).query)
        ticker = params["symbol"][0]
        option_date = date.fromisoformat(params["date"][0])
        payload = _alpha_options_payload(option_date, spot=100.0, iv=0.40)
        return HttpFetchResult(
            200,
            json.dumps(payload).encode("utf-8"),
            {"Content-Type": "application/json"},
            url,
        )


class QuotaLearningFetcher(PayloadFetcher):
    """Serves one payload, then records the provider's own stop signal for the day."""

    def __init__(self, budget: RequestBudget) -> None:
        self._budget = budget
        self.calls = 0

    def fetch(
        self,
        url: str,
        timeout_seconds: float,
        headers: dict[str, str],
    ) -> HttpFetchResult:
        result = super().fetch(url, timeout_seconds, headers)
        self.calls += 1
        if self.calls == 1:
            self._budget.note_quota_exhausted(
                "alpha_vantage",
                "historical_options",
                "Error Message: Limit Reach",
            )
        return result


def _settings(tmp_path: Path, *, plan: str = "paid") -> AppSettings:
    return AppSettings(
        config_path=Path("config/config.example.yaml"),
        source_registry_path=Path("config/source_registry.yaml"),
        data_dir=tmp_path,
        output_dir=tmp_path / "output",
        http_timeout_seconds=1,
        user_agent="briefing-app-test",
        alpha_vantage_api_key="av-key",
        fmp_api_key=None,
        provider_plans={"alpha_vantage": plan},
        network_retries=0,
    )


def _response(ticker: str, option_date: date, payload: dict) -> ProviderResponse:
    return ProviderResponse(
        provider="alpha_vantage",
        endpoint="historical_options",
        target=f"{ticker}_{option_date.isoformat()}",
        url=f"https://provider.test/options?symbol={ticker}&date={option_date.isoformat()}",
        payload=payload,
        cache_path=None,
        validation=ValidationResult(OK, True),
        fetched_at=datetime(2026, 9, 7, 9, tzinfo=UTC),
    )


def _alpha_options_payload(option_date: date, *, spot: float, iv: float) -> dict:
    expiry = option_date + timedelta(days=7)
    return {
        "timestamp": datetime.combine(option_date, datetime.min.time(), tzinfo=UTC).isoformat(),
        "underlying_price": spot,
        "data": [
            _contract("NVDA", expiry, "C", 95, 5.20, 5.40, iv + 0.02, 140, 1100, 0.68),
            _contract("NVDA", expiry, "P", 95, 0.80, 0.90, iv + 0.02, 90, 900, -0.30),
            _contract("NVDA", expiry, "C", 100, 2.40, 2.60, iv, 200, 1000, 0.52),
            _contract("NVDA", expiry, "P", 100, 2.10, 2.30, iv, 160, 950, -0.48),
            _contract("NVDA", expiry, "C", 105, 0.95, 1.05, iv + 0.01, 120, 850, 0.30),
            _contract("NVDA", expiry, "P", 105, 5.60, 5.80, iv + 0.01, 110, 800, -0.66),
        ],
    }


def _contract(
    ticker: str,
    expiry: date,
    option_type: str,
    strike: float,
    bid: float,
    ask: float,
    iv: float,
    volume: int,
    open_interest: int,
    delta: float,
) -> dict:
    return {
        "contractID": f"{ticker}{expiry.strftime('%y%m%d')}{option_type}{int(strike * 1000):08d}",
        "expiration": expiry.isoformat(),
        "strike": str(strike),
        "type": "call" if option_type == "C" else "put",
        "bid": str(bid),
        "ask": str(ask),
        "implied_volatility": str(iv),
        "volume": str(volume),
        "open_interest": str(open_interest),
        "delta": str(delta),
        "gamma": "0.02",
    }


# --------------------------------------------------------------------------------------
# J1 — a backfilled reading must equal a live one
# --------------------------------------------------------------------------------------


def test_backfill_reproduces_a_row_the_live_path_stored(tmp_path: Path) -> None:
    """The J1 reproduction: a *stored live* row, rebuilt by a real backfill run.

    This is deliberately not the same claim as
    `test_backfilled_metrics_reproduce_stored_live_metrics_to_full_precision`, which
    builds both sides with `backfill.snapshot_row_from_structure`. That proves the
    backfill agrees with itself. The live pipeline stores its rows through
    `scoring.to_daily_snapshot_row`, from a `build_options_structure` call carrying four
    arguments the backfill never passes — `price_bars`, `expression_class`,
    `event_multiplier` and the stored histories. So here the live side is built the way
    `pipeline.py` builds it, stored through `StorageRepository`, and compared against a
    row that `run_iv_backfill` fetched, computed and stored end to end.
    """

    config = AppConfig.model_validate({})
    snap_date = date(2026, 9, 3)
    payload = _alpha_options_payload(snap_date, spot=100.0, iv=0.42)

    live_repo = _repo()
    live_run_id = live_repo.upsert_briefing_run(
        run_date=snap_date,
        status="succeeded",
        details={"data_mode": "live"},
    )
    chain = normalize_alpha_vantage_options_chain(
        "NVDA",
        payload,
        filters=OptionFilterConfig.model_validate(config.option_filters.model_dump()),
        endpoint_or_file="live-realtime-options.json",
        reference_time=datetime(2026, 9, 3, 20, tzinfo=UTC),
    )
    live_structure = build_options_structure(
        ticker="NVDA",
        spot=chain.spot,
        as_of=chain.as_of,
        option_quotes=chain,
        # Everything below this line is what the live path passes and the backfill does
        # not. If any of it moved a stored metric, this test would fail.
        price_bars=_price_bars(snap_date),
        expression_class=ExpressionClass.V,
        pc_ratio_vol_history=[0.80] * 20,
        pc_ratio_oi_history=[0.90] * 20,
        iv_history=[0.30] * 20,
        event_multiplier=1.35,
        chain_verified=(
            chain.validation_status is ValidationStatus.VERIFIED and bool(chain.contracts)
        ),
        run_id=live_run_id,
        source=chain.source,
        venue=chain.venue,
        endpoint_or_file=chain.endpoint_or_file,
        validation_status=chain.validation_status.value,
    )
    live_repo.upsert_daily_snapshot(
        to_daily_snapshot_row(
            ScoringResult(ticker="NVDA", expression_class=ExpressionClass.V),
            snap_date=snap_date,
            run_id=live_run_id,
            options_structure=live_structure,
        )
    )

    backfill_repo = _repo()
    result = run_iv_backfill(
        config,
        repository=backfill_repo,
        settings=_settings(tmp_path),
        client=FakeHistoricalOptionsClient(payload=payload),
        tickers=["NVDA"],
        run_date=date(2026, 9, 7),
        end_date=snap_date,
        sessions=1,
        live_run_reserve=0,
        allow_vendor_splice=True,
    )

    assert result.stored == 1
    stored_live = live_repo.daily_snapshot_for("NVDA", snap_date)
    stored_backfill = backfill_repo.daily_snapshot_for("NVDA", snap_date)
    assert stored_live is not None
    assert stored_backfill is not None

    # The three series the self-built baseline is a percentile of, plus the spot and
    # expected moves the report quotes. Exact equality: a rounded comparison would hide
    # precisely the small, systematic offset this test exists to catch.
    for column in (
        "spot",
        "iv_atm",
        "pc_ratio_vol",
        "pc_ratio_oi",
        "expected_move_1w",
        "expected_move_1m",
        "rr_25d",
    ):
        assert stored_backfill[column] == stored_live[column], column

    # And the one field that is honestly not reproduced: realized volatility needs price
    # bars, which a historical option chain does not carry. It is asserted rather than
    # left implicit so nobody reads a NULL there as a bug.
    assert stored_live["realized_vol_20d"] is not None
    assert stored_backfill["realized_vol_20d"] is None


def test_live_and_backfill_row_builders_agree_field_for_field() -> None:
    """`scoring.to_daily_snapshot_row` and `backfill.snapshot_row_from_structure` are
    two copies of one field mapping, in two files, owned by two lanes. Nothing else
    fails if they drift, and a drift would silently change which quantity the percentile
    is built from. This pins them together.
    """

    config = AppConfig.model_validate({})
    snap_date = date(2026, 9, 3)
    chain = normalize_alpha_vantage_options_chain(
        "NVDA",
        _alpha_options_payload(snap_date, spot=100.0, iv=0.42),
        filters=OptionFilterConfig.model_validate(config.option_filters.model_dump()),
        endpoint_or_file="chain.json",
        reference_time=datetime(2026, 9, 3, 20, tzinfo=UTC),
    )
    structure = build_options_structure(
        ticker="NVDA",
        spot=chain.spot,
        as_of=chain.as_of,
        option_quotes=chain,
        price_bars=_price_bars(snap_date),
        iv_history=[0.30] * 20,
        chain_verified=True,
        source=chain.source,
        venue=chain.venue,
        endpoint_or_file=chain.endpoint_or_file,
        validation_status=chain.validation_status.value,
    )

    live_row = to_daily_snapshot_row(
        ScoringResult(ticker="NVDA", expression_class=ExpressionClass.V),
        snap_date=snap_date,
        run_id=1,
        options_structure=structure,
    )
    backfill_row = snapshot_row_from_structure(structure, snap_date=snap_date, run_id=1)

    for column in (
        "ticker",
        "snap_date",
        "spot",
        "iv_atm",
        "iv_rank",
        "expected_move_1w",
        "expected_move_1m",
        "pc_ratio_vol",
        "pc_ratio_oi",
        "rr_25d",
        "realized_vol_20d",
    ):
        assert backfill_row[column] == live_row[column], column


def test_backfill_refuses_to_splice_a_second_vendor_into_the_live_series(
    tmp_path: Path,
) -> None:
    """Same functions is not the same series.

    The live path reads `config.providers.options[0]`, which is CBOE by default and is
    what every stored `iv_atm` in this project was computed from. This backfill reads
    Alpha Vantage historical chains. A percentile across both compares two vendors'
    quotes captured at two times of day, so the run refuses until a human says otherwise.
    """

    config = AppConfig.model_validate({})
    assert config.providers.options[0] == "cboe"

    splice = vendor_splice_report(config)
    assert splice is not None
    assert splice["live_options_provider"] == "cboe"
    assert splice["backfill_provider"] == "alpha_vantage"

    repo = _repo()
    client = FakeHistoricalOptionsClient()
    blocked = run_iv_backfill(
        config,
        repository=repo,
        settings=_settings(tmp_path),
        client=client,
        tickers=["NVDA"],
        run_date=date(2026, 9, 7),
        end_date=date(2026, 9, 4),
        sessions=1,
        live_run_reserve=0,
    )

    assert blocked.status == "blocked"
    assert blocked.stored == 0
    assert client.calls == []
    assert "vendor splice" in blocked.blocked_reason

    acknowledged = run_iv_backfill(
        config,
        repository=repo,
        settings=_settings(tmp_path),
        client=client,
        tickers=["NVDA"],
        run_date=date(2026, 9, 7),
        end_date=date(2026, 9, 4),
        sessions=1,
        live_run_reserve=0,
        allow_vendor_splice=True,
    )

    assert acknowledged.stored == 1
    row = repo.daily_snapshot_for("NVDA", date(2026, 9, 4))
    assert row is not None
    # Provenance on the row itself, so a mixed series can be told apart afterwards.
    assert row["raw"]["backfill"]["chain_source"] == "Alpha Vantage options"
    assert row["raw"]["backfill"]["live_options_provider"] == "cboe"


def test_vendor_splice_is_not_reported_when_the_live_path_uses_the_same_vendor() -> None:
    config = AppConfig.model_validate({"providers": {"options": ["alpha_vantage", "cboe"]}})
    assert vendor_splice_report(config) is None


# --------------------------------------------------------------------------------------
# J2 — the backfill may not starve the daily run
# --------------------------------------------------------------------------------------


def test_reservation_holds_the_whole_allowance_before_the_live_run_has_finished(
    tmp_path: Path,
) -> None:
    """The measured live run has spent all 25 on 2 of the 5 days recorded, so before it
    has run there is no such thing as a spare request."""

    budget = _budget(tmp_path, daily_requests=25)
    reservation = plan_budget_reservation(
        budget,
        _settings(tmp_path, plan="free"),
        run_date=date(2026, 9, 7),
        repository=_repo(),
    )

    assert reservation.live_run_completed is False
    assert reservation.reserved_for_live_run == DEFAULT_LIVE_RUN_RESERVE
    assert reservation.remaining_today == 25
    assert reservation.spendable == 0
    assert reservation.blocks_all_requests is True


def test_backfill_sends_nothing_while_the_allowance_is_reserved(tmp_path: Path) -> None:
    repo = _repo()
    client = FakeHistoricalOptionsClient()

    result = run_iv_backfill(
        AppConfig.model_validate({}),
        repository=repo,
        settings=_settings(tmp_path, plan="free"),
        budget=_budget(tmp_path, daily_requests=25),
        client=client,
        tickers=["NVDA"],
        run_date=date(2026, 9, 7),
        end_date=date(2026, 9, 4),
        sessions=2,
        allow_vendor_splice=True,
    )

    assert client.calls == []
    assert result.stored == 0
    assert result.requests_sent == 0
    assert result.status == "blocked"
    assert "reserved for the daily run" in result.blocked_reason


def test_backfill_spends_only_what_is_spare_once_the_live_run_has_finished(
    tmp_path: Path,
) -> None:
    """After the daily run has finished, its requests are spent and what is left is
    genuinely spare — less a floor kept back so a re-run still reaches its providers."""

    repo = _repo()
    repo.finish_briefing_run(
        repo.upsert_briefing_run(
            run_date=date(2026, 9, 7),
            run_type="daily",
            status="running",
            details={"data_mode": "live"},
        ),
        status="succeeded",
        finished_at=datetime(2026, 9, 7, 12, tzinfo=UTC),
        details={"data_mode": "live"},
    )
    budget = _budget(tmp_path, daily_requests=25)
    for _ in range(17):
        budget.reserve("alpha_vantage", "global_quote")

    reservation = plan_budget_reservation(
        budget,
        _settings(tmp_path, plan="free"),
        run_date=date(2026, 9, 7),
        repository=repo,
    )
    assert reservation.live_run_completed is True
    assert reservation.reserved_for_live_run == DEFAULT_COMPLETED_RUN_RESERVE
    assert reservation.remaining_today == 8
    assert reservation.spendable == 2

    client = FakeHistoricalOptionsClient()
    result = run_iv_backfill(
        AppConfig.model_validate({}),
        repository=repo,
        settings=_settings(tmp_path, plan="free"),
        budget=budget,
        client=client,
        tickers=["NVDA", "MSFT", "AMD"],
        run_date=date(2026, 9, 7),
        end_date=date(2026, 9, 4),
        sessions=2,
        allow_vendor_splice=True,
    )

    assert result.requests_sent == 2
    assert len(client.calls) == 2
    assert result.stored == 2
    assert result.remaining == 4
    assert any("daily-run reservation" in item for item in result.diagnostics)
    # 6 pairs were planned and 2 were sent, so what stopped the run was the reservation
    # and not the work running out. The live run's floor survives: 8 remaining, minus the
    # 2 the backfill was allowed, leaves exactly the 6 held back for it.
    assert result.requests_sent <= result.reservation.spendable
    assert result.reservation.remaining_today - result.requests_sent == (
        DEFAULT_COMPLETED_RUN_RESERVE
    )


def test_an_unmetered_plan_reserves_nothing(tmp_path: Path) -> None:
    reservation = plan_budget_reservation(
        RequestBudget(tmp_path, now=lambda: datetime(2026, 9, 7, 9, tzinfo=UTC)),
        _settings(tmp_path, plan="paid"),
        run_date=date(2026, 9, 7),
        repository=_repo(),
    )

    assert reservation.spendable is None
    assert reservation.reserved_for_live_run == 0
    assert reservation.blocks_all_requests is False


def test_cache_only_replay_reserves_nothing(tmp_path: Path) -> None:
    reservation = plan_budget_reservation(
        _budget(tmp_path, daily_requests=25),
        _settings(tmp_path, plan="free"),
        run_date=date(2026, 9, 7),
        repository=_repo(),
        unmetered=True,
    )

    assert reservation.spendable is None
    assert reservation.reserved_for_live_run == 0


def test_dry_run_reports_the_reservation_it_would_be_held_to(tmp_path: Path) -> None:
    result = run_iv_backfill(
        AppConfig.model_validate({}),
        settings=_settings(tmp_path, plan="free"),
        budget=_budget(tmp_path, daily_requests=25),
        client=FailingHistoricalOptionsClient(),
        tickers=["NVDA"],
        run_date=date(2026, 9, 7),
        end_date=date(2026, 9, 4),
        sessions=2,
        dry_run=True,
    )

    payload = result.to_dict()
    assert payload["reservation"]["reserved_for_live_run"] == DEFAULT_LIVE_RUN_RESERVE
    assert payload["reservation"]["spendable"] == 0
    assert payload["vendor_splice"]["live_options_provider"] == "cboe"


def test_repeated_failures_stop_the_run_before_they_spend_the_allowance(
    tmp_path: Path,
) -> None:
    """Alpha Vantage answers `HISTORICAL_OPTIONS` on a free key with a sample payload
    that validates as `synthetic`, and `providers/base.py` parks only `malformed`. Left
    to itself the backfill would ask 25 times a day, store nothing, and leave the live
    run with an empty allowance."""

    repo = _repo()
    client = AlwaysFailingClient(status="unavailable")
    result = run_iv_backfill(
        AppConfig.model_validate({}),
        repository=repo,
        settings=_settings(tmp_path, plan="free"),
        budget=_budget(tmp_path, daily_requests=25),
        client=client,
        tickers=["NVDA", "MSFT", "AMD", "INTC", "AMAT"],
        run_date=date(2026, 9, 7),
        end_date=date(2026, 9, 4),
        sessions=2,
        live_run_reserve=0,
        allow_vendor_splice=True,
    )

    assert client.calls == MAX_CONSECUTIVE_FAILURES
    assert result.failed == MAX_CONSECUTIVE_FAILURES
    assert result.stored == 0
    assert any("consecutive failures" in item for item in result.diagnostics)


def test_a_synthetic_payload_stops_the_run_on_the_first_answer(tmp_path: Path) -> None:
    repo = _repo()
    client = AlwaysFailingClient(status="synthetic")
    result = run_iv_backfill(
        AppConfig.model_validate({}),
        repository=repo,
        settings=_settings(tmp_path, plan="free"),
        budget=_budget(tmp_path, daily_requests=25),
        client=client,
        tickers=["NVDA", "MSFT", "AMD"],
        run_date=date(2026, 9, 7),
        end_date=date(2026, 9, 4),
        sessions=2,
        live_run_reserve=0,
        allow_vendor_splice=True,
    )

    assert client.calls == 1
    assert result.stored == 0
    assert repo.daily_snapshot_for("NVDA", date(2026, 9, 4)) is None


class AlwaysFailingClient:
    def __init__(self, *, status: str) -> None:
        self.status = status
        self.calls = 0

    def fetch_historical_options(self, ticker: str, **kwargs: object) -> ProviderResponse:
        self.calls += 1
        raise ProviderDataError(
            "alpha_vantage",
            "historical_options",
            self.status,
            ("Payload contains sentinel symbols or impossible dates.",),
        )


def _repo() -> StorageRepository:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    create_schema(engine)
    return StorageRepository(engine)


def _budget(tmp_path: Path, *, daily_requests: int) -> RequestBudget:
    return RequestBudget(
        tmp_path,
        policies={
            "alpha_vantage": ProviderBudgetPolicy(
                daily_requests=daily_requests,
                min_interval_seconds=0.0,
            )
        },
        now=lambda: datetime(2026, 9, 7, 9, tzinfo=UTC),
    )


def _price_bars(snap_date: date) -> list[dict]:
    return [
        {"date": (snap_date - timedelta(days=offset)).isoformat(), "close": 100 + offset * 0.5}
        for offset in range(40)
    ]
