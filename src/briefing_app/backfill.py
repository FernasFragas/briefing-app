"""Historical option-chain replay for self-built volatility baselines."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from math import ceil
import os
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import create_engine, select

from briefing_app.config import AppConfig, load_config
from briefing_app.models.candidate import Geography
from briefing_app.models.market_data import OptionFilterConfig, ValidationStatus
from briefing_app.options_math import OptionsStructureResult, build_options_structure
from briefing_app.pipeline import SELF_BUILT_SERIES_MIN_SESSIONS
from briefing_app.provider_validation import SYNTHETIC
from briefing_app.providers.alpha_vantage import AlphaVantageClient
from briefing_app.providers.base import PLAN_GATED, ProviderDataError, ProviderResponse
from briefing_app.providers.budget import BUDGET_EXHAUSTED, RequestBudget
from briefing_app.providers.normalizers import normalize_alpha_vantage_options_chain
from briefing_app.settings import AppSettings
from briefing_app.storage import LOCAL_SQLITE_FILENAME, StorageRepository, briefing_run
from briefing_app.universe.gate import run_gate
from briefing_app.universe.loader import load_universe


BACKFILL_RUN_TYPE = "iv_backfill"
BACKFILL_SOURCE_KIND = "iv_backfill"
BACKFILL_PROVIDER = "alpha_vantage"
BACKFILL_ENDPOINT = "historical_options"

#: Statuses a finished `briefing_run` may carry and still count as "today's live run has
#: already spent what it needed". A failed run spent nothing worth protecting.
LIVE_RUN_DONE_STATUSES = frozenset({"succeeded", "partial"})

#: Requests held back for the daily live run before the backfill may spend anything.
#:
#: 25 is the whole free Alpha Vantage allowance, and that is deliberate. The live run's
#: own counters (`data/provider_budget/alpha_vantage/`) record what it actually spent:
#: 6 on 2026-08-30, **25** on 2026-09-02, **25** on 2026-09-03, 4 on 2026-09-04, 2 on
#: 2026-09-06. It reached the ceiling on two of the five days measured, and nothing tells
#: you in advance which kind of day today is. Reserving less than the observed peak means
#: guessing, and the cost of guessing wrong is the provider-less run this reservation
#: exists to prevent. So before the live run has finished, the backfill's share is zero.
DEFAULT_LIVE_RUN_RESERVE = 25

#: Held back once today's live run has already finished. Its requests are spent by then,
#: so what remains is genuinely spare — except that a re-run is always possible, and the
#: largest spend by a run that did *not* hit the ceiling was 6. That is the floor kept
#: back so a repeat run still reaches its providers.
DEFAULT_COMPLETED_RUN_RESERVE = 6

#: Consecutive fetch failures that stop the run.
#:
#: `providers/base.py` parks an endpoint after two identical refusals, but only for
#: statuses in `REPEATABLE_REFUSAL_STATUSES`, which is `{malformed}` alone. Alpha
#: Vantage answers `HISTORICAL_OPTIONS` on a free key with a plausible sample payload
#: that validates as `synthetic` (`docs/research/SOURCE_STATUS.md`), and nothing parks that. Left
#: unbounded, one such backfill spends every remaining request of the day, stores
#: nothing, and starves the live run — the exact outcome J2 exists to prevent.
MAX_CONSECUTIVE_FAILURES = 3


class HistoricalOptionsClient(Protocol):
    def fetch_historical_options(
        self,
        ticker: str,
        *,
        run_date: date,
        option_date: date | None = None,
        cache_only: bool = False,
    ) -> ProviderResponse:
        ...


@dataclass(frozen=True)
class BackfillPair:
    ticker: str
    snap_date: date

    def to_dict(self) -> dict[str, str]:
        return {"ticker": self.ticker, "snap_date": self.snap_date.isoformat()}


@dataclass(frozen=True)
class BudgetReservation:
    """How much of today's provider allowance the backfill may spend.

    The daily run and the backfill draw on one Alpha Vantage allowance. Whatever the
    backfill spends first, the live run cannot spend later — and a live run that reaches
    no provider is worse than a baseline that warms up slowly. So the live run's need is
    subtracted before the backfill sees a number, and only the difference is spendable.
    """

    provider: str
    plan: str
    daily_allowance: int | None
    spent_today: int
    remaining_today: int | None
    reserved_for_live_run: int
    live_run_completed: bool
    #: Requests the backfill may send today. `None` means unmetered (a paid plan).
    spendable: int | None
    reason: str

    @property
    def blocks_all_requests(self) -> bool:
        return self.spendable is not None and self.spendable <= 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "plan": self.plan,
            "daily_allowance": self.daily_allowance,
            "spent_today": self.spent_today,
            "remaining_today": self.remaining_today,
            "reserved_for_live_run": self.reserved_for_live_run,
            "live_run_completed": self.live_run_completed,
            "spendable": self.spendable,
            "reason": self.reason,
        }


@dataclass
class BackfillResult:
    run_date: date
    tickers: tuple[str, ...]
    dates: tuple[date, ...]
    dry_run: bool
    requested_pairs: int
    already_stored: int
    stored: int = 0
    skipped: int = 0
    failed: int = 0
    remaining: int = 0
    estimated_days_at_allowance: int | None = None
    budget_remaining_today: int | None = None
    budget_exhausted: bool = False
    requests_sent: int = 0
    reservation: BudgetReservation | None = None
    vendor_splice: dict[str, Any] | None = None
    blocked_reason: str | None = None
    storage_run_id: int | None = None
    diagnostics: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.dry_run:
            return "dry_run"
        if self.blocked_reason is not None:
            return "blocked"
        if self.failed or self.budget_exhausted or self.remaining:
            return "partial"
        return "succeeded"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "run_date": self.run_date.isoformat(),
            "storage_run_id": self.storage_run_id,
            "dry_run": self.dry_run,
            "tickers": list(self.tickers),
            "dates": [day.isoformat() for day in self.dates],
            "requested_pairs": self.requested_pairs,
            "already_stored": self.already_stored,
            "stored": self.stored,
            "skipped": self.skipped,
            "failed": self.failed,
            "remaining": self.remaining,
            "estimated_days_at_allowance": self.estimated_days_at_allowance,
            "budget_remaining_today": self.budget_remaining_today,
            "budget_exhausted": self.budget_exhausted,
            "requests_sent": self.requests_sent,
            "reservation": self.reservation.to_dict() if self.reservation else None,
            "vendor_splice": self.vendor_splice,
            "blocked_reason": self.blocked_reason,
            "diagnostics": list(self.diagnostics),
        }


def run_iv_backfill(
    config: AppConfig | None = None,
    *,
    repository: StorageRepository | None = None,
    settings: AppSettings | None = None,
    client: HistoricalOptionsClient | None = None,
    budget: RequestBudget | None = None,
    tickers: Sequence[str] | None = None,
    run_date: date | None = None,
    end_date: date | None = None,
    start_date: date | None = None,
    sessions: int = SELF_BUILT_SERIES_MIN_SESSIONS,
    data_dir: str | Path | None = None,
    dry_run: bool = False,
    cache_only: bool = False,
    max_requests: int | None = None,
    live_run_reserve: int | None = None,
    allow_vendor_splice: bool = False,
) -> BackfillResult:
    loaded_config = config or load_config()
    base_settings = settings or AppSettings.from_env()
    if data_dir is not None:
        base_settings = replace(base_settings, data_dir=Path(data_dir))
    effective_run_date = run_date or datetime.now(UTC).date()
    effective_end_date = end_date or _previous_weekday(effective_run_date - timedelta(days=1))
    selected_tickers = _normalize_tickers(tickers) or default_backfill_tickers(
        loaded_config,
        run_date=effective_run_date,
    )
    if not selected_tickers:
        raise ValueError("no US tickers selected for IV backfill")
    selected_dates = session_dates(
        end_date=effective_end_date,
        sessions=sessions,
        start_date=start_date,
    )
    if not selected_dates:
        raise ValueError("no weekday option dates selected for IV backfill")

    repo = repository or _repository_for_backfill(
        base_settings.data_dir,
        dry_run=dry_run,
    )
    backfill_budget = budget or RequestBudget(base_settings.data_dir)
    pairs = tuple(
        BackfillPair(ticker, snap_date)
        for snap_date in selected_dates
        for ticker in selected_tickers
    )
    already_stored = _stored_pair_count(repo, pairs)
    result = BackfillResult(
        run_date=effective_run_date,
        tickers=selected_tickers,
        dates=selected_dates,
        dry_run=dry_run,
        requested_pairs=len(pairs),
        already_stored=already_stored,
    )
    _refresh_progress(result, repo, pairs, backfill_budget, base_settings)

    result.vendor_splice = vendor_splice_report(loaded_config)
    if result.vendor_splice is not None:
        result.diagnostics.append(result.vendor_splice["detail"])

    # `cache_only` replays payloads already on disk, so it reserves nothing and cannot
    # take a request the live run needs.
    result.reservation = plan_budget_reservation(
        backfill_budget,
        base_settings,
        run_date=effective_run_date,
        repository=repo,
        reserve=live_run_reserve,
        unmetered=cache_only,
    )
    result.diagnostics.append(result.reservation.reason)

    if dry_run:
        result.diagnostics.append(
            "dry run only: no provider requests sent and no daily_snapshot rows written"
        )
        return result

    if repo is None:
        raise ValueError("a repository is required for a non-dry-run IV backfill")

    if result.vendor_splice is not None and not allow_vendor_splice:
        result.blocked_reason = result.vendor_splice["detail"]
        result.diagnostics.append(
            "refusing to write: pass allow_vendor_splice=True (CLI --allow-vendor-splice) "
            "only once the owner has accepted that the backfilled sessions come from a "
            "different vendor than the live ones they will be ranked against"
        )
        return result

    if result.reservation.blocks_all_requests:
        result.blocked_reason = (
            f"{result.reservation.provider} allowance is reserved for the daily run: "
            f"{result.reservation.remaining_today} left today, "
            f"{result.reservation.reserved_for_live_run} held back"
        )
        return result

    result.storage_run_id = repo.upsert_briefing_run(
        run_date=effective_run_date,
        run_type=BACKFILL_RUN_TYPE,
        status="running",
        started_at=datetime.now(UTC),
        details={
            "data_mode": "live",
            "source_kind": BACKFILL_SOURCE_KIND,
            "provider": BACKFILL_PROVIDER,
            "endpoint": BACKFILL_ENDPOINT,
            "sessions_requested": len(selected_dates),
        },
    )

    fetcher = client or AlphaVantageClient(
        settings=base_settings,
        budget=backfill_budget,
    )
    request_cap = _request_cap(max_requests, result.reservation)
    requests_sent = 0
    consecutive_failures = 0
    for pair in pairs:
        if repo.option_metrics_are_stored(pair.ticker, pair.snap_date):
            result.skipped += 1
            continue
        if request_cap is not None and requests_sent >= request_cap:
            result.diagnostics.append(
                f"request cap reached: {requests_sent}/{request_cap} requests sent"
                + (
                    ""
                    if max_requests is not None and request_cap == max_requests
                    else " (daily-run reservation)"
                )
            )
            break
        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            result.diagnostics.append(
                f"stopping after {consecutive_failures} consecutive failures: the endpoint "
                "is not answering and further requests would spend the daily run's allowance"
            )
            break

        try:
            response = fetcher.fetch_historical_options(
                pair.ticker,
                run_date=pair.snap_date,
                option_date=pair.snap_date,
                cache_only=cache_only,
            )
            requests_sent += 1
            snapshot = build_backfill_snapshot_row(
                pair.ticker,
                pair.snap_date,
                response.payload,
                config=loaded_config,
                repository=repo,
                run_id=result.storage_run_id,
                endpoint_or_file=response.cache_path or response.url or "",
                fetched_at=response.fetched_at,
            )
            repo.upsert_daily_snapshot(snapshot)
            result.stored += 1
            consecutive_failures = 0
        except ProviderDataError as exc:
            consecutive_failures += 1
            result.diagnostics.append(
                f"{pair.ticker} {pair.snap_date.isoformat()} historical options unavailable: {exc}"
            )
            if exc.status == BUDGET_EXHAUSTED:
                result.budget_exhausted = True
                break
            if exc.status in (PLAN_GATED, SYNTHETIC):
                # The key cannot reach this endpoint at all. `synthetic` is Alpha
                # Vantage's premium-sample answer, and unlike `malformed` nothing in
                # `providers/base.py` parks it, so it must be stopped here.
                result.failed += 1
                break
            result.failed += 1
        except Exception as exc:  # noqa: BLE001 - one bad chain must not hide progress.
            consecutive_failures += 1
            result.failed += 1
            result.diagnostics.append(
                f"{pair.ticker} {pair.snap_date.isoformat()} backfill failed: {exc}"
            )

    result.requests_sent = requests_sent
    _refresh_progress(result, repo, pairs, backfill_budget, base_settings)
    repo.finish_briefing_run(
        result.storage_run_id,
        status=result.status,
        finished_at=datetime.now(UTC),
        details={
            "data_mode": "live",
            "source_kind": BACKFILL_SOURCE_KIND,
            "provider": BACKFILL_PROVIDER,
            "endpoint": BACKFILL_ENDPOINT,
            "stored": result.stored,
            "skipped": result.skipped,
            "failed": result.failed,
            "remaining": result.remaining,
            "budget_exhausted": result.budget_exhausted,
            "requests_sent": result.requests_sent,
            "reservation": result.reservation.to_dict() if result.reservation else None,
            "diagnostics": result.diagnostics,
        },
    )
    return result


def build_backfill_snapshot_row(
    ticker: str,
    snap_date: date,
    payload: dict[str, Any],
    *,
    config: AppConfig,
    repository: StorageRepository | None = None,
    run_id: int | None = None,
    endpoint_or_file: str = "",
    fetched_at: datetime | None = None,
) -> dict[str, Any]:
    """Normalize a historical chain and extract the same metrics the live path stores."""

    clean_ticker = ticker.strip().upper()
    filters = OptionFilterConfig.model_validate(config.option_filters.model_dump())
    reference_time = fetched_at or datetime.combine(snap_date, datetime.min.time(), tzinfo=UTC)
    chain = normalize_alpha_vantage_options_chain(
        clean_ticker,
        payload,
        filters=filters,
        endpoint_or_file=endpoint_or_file,
        reference_time=reference_time,
    )
    iv_history, pc_vol_history, pc_oi_history = _stored_histories(
        repository, clean_ticker, snap_date
    )
    structure = build_options_structure(
        ticker=clean_ticker,
        spot=chain.spot,
        as_of=chain.as_of or reference_time,
        option_quotes=chain,
        price_bars=(),
        chain_verified=_chain_is_verified(chain),
        iv_history=iv_history,
        pc_ratio_vol_history=pc_vol_history,
        pc_ratio_oi_history=pc_oi_history,
        run_id=run_id,
        source=chain.source,
        venue=chain.venue,
        endpoint_or_file=chain.endpoint_or_file,
        validation_status=chain.validation_status.value,
    )
    return snapshot_row_from_structure(
        structure,
        snap_date=snap_date,
        run_id=run_id,
        raw={
            "source_kind": BACKFILL_SOURCE_KIND,
            "backfill": {
                "provider": BACKFILL_PROVIDER,
                "endpoint": BACKFILL_ENDPOINT,
                "option_date": snap_date.isoformat(),
                "endpoint_or_file": endpoint_or_file,
                # Provenance, so a mixed-vendor series can be told apart after the fact.
                # A live row records its chain source only in `evidence_ledger`; a
                # backfilled row carries it here, on the row itself.
                "chain_source": chain.source,
                "chain_venue": chain.venue,
                "chain_as_of": (chain.as_of or reference_time).isoformat(),
                "live_options_provider": (
                    config.providers.options[0] if config.providers.options else None
                ),
                "computed_with": [
                    "briefing_app.providers.normalizers.normalize_alpha_vantage_options_chain",
                    "briefing_app.options_math.build_options_structure",
                ],
                "history_sessions": {
                    "iv_atm": len(iv_history),
                    "pc_ratio_vol": len(pc_vol_history),
                    "pc_ratio_oi": len(pc_oi_history),
                },
            },
        },
    )


def snapshot_row_from_structure(
    structure: OptionsStructureResult,
    *,
    snap_date: date,
    run_id: int | None = None,
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    weekly = structure.expected_moves.get("weekly")
    monthly = structure.expected_moves.get("monthly")
    realized_20 = structure.realized_volatility.get(20)
    return {
        "run_id": run_id,
        "ticker": structure.ticker,
        "snap_date": snap_date,
        "spot": structure.spot,
        "iv_atm": weekly.iv_atm if weekly else None,
        "iv_rank": structure.iv_rank,
        "expected_move_1w": weekly.straddle_pct if weekly else None,
        "expected_move_1m": monthly.straddle_pct if monthly else None,
        "pc_ratio_vol": (
            structure.put_call.volume_ratio if structure.put_call is not None else None
        ),
        "pc_ratio_oi": (
            structure.put_call.open_interest_ratio if structure.put_call is not None else None
        ),
        "rr_25d": (
            structure.risk_reversal_25d.rr_25d
            if structure.risk_reversal_25d is not None
            else None
        ),
        "realized_vol_20d": realized_20.annualized_vol if realized_20 else None,
        "raw": raw or {},
    }


def plan_budget_reservation(
    budget: RequestBudget,
    settings: AppSettings,
    *,
    run_date: date,
    repository: StorageRepository | None = None,
    reserve: int | None = None,
    unmetered: bool = False,
) -> BudgetReservation:
    """Decide how many requests the backfill may spend without starving the daily run.

    The policy, in one line: **the live run is paid first, and the backfill spends only
    what is left over after it.**

    - A paid plan has no daily ceiling, so there is nothing to divide and nothing is held
      back.
    - `--cache-only` sends no requests, so it reserves nothing.
    - Before today's live run has finished, the reserve is the full observed peak of what
      that run needs (`DEFAULT_LIVE_RUN_RESERVE`). On a 25/day key that leaves the
      backfill zero, which is the honest answer: the measured live run has used all 25.
    - Once today's live run has finished, its requests are already spent. What remains is
      spare, less a small floor (`DEFAULT_COMPLETED_RUN_RESERVE`) so a re-run still works.
    """

    plan = settings.provider_plan(BACKFILL_PROVIDER)
    policy = budget.policy_for(BACKFILL_PROVIDER, plan=plan)
    spent = budget.spent(BACKFILL_PROVIDER, day=run_date)
    remaining = budget.remaining(BACKFILL_PROVIDER, day=run_date, plan=plan)
    live_run_completed = _live_run_completed(repository, run_date)

    if unmetered:
        return BudgetReservation(
            provider=BACKFILL_PROVIDER,
            plan=plan,
            daily_allowance=policy.daily_requests,
            spent_today=spent,
            remaining_today=remaining,
            reserved_for_live_run=0,
            live_run_completed=live_run_completed,
            spendable=None,
            reason="cache-only replay sends no requests, so nothing is reserved",
        )

    if policy.unlimited:
        return BudgetReservation(
            provider=BACKFILL_PROVIDER,
            plan=plan,
            daily_allowance=None,
            spent_today=spent,
            remaining_today=None,
            reserved_for_live_run=0,
            live_run_completed=live_run_completed,
            spendable=None,
            reason=(
                f"{BACKFILL_PROVIDER} plan '{plan}' has no daily request ceiling, so the "
                "backfill cannot take a request the daily run needs"
            ),
        )

    if reserve is None:
        reserve = (
            _env_int("BACKFILL_COMPLETED_RUN_RESERVE", DEFAULT_COMPLETED_RUN_RESERVE)
            if live_run_completed
            else _env_int("BACKFILL_LIVE_RUN_RESERVE", DEFAULT_LIVE_RUN_RESERVE)
        )
    reserve = max(0, reserve)
    spendable = max(0, (remaining or 0) - reserve)
    if live_run_completed:
        reason = (
            f"today's live run has finished; {remaining} of "
            f"{policy.daily_requests} {BACKFILL_PROVIDER} requests remain and {reserve} "
            f"stay held back for a re-run, leaving {spendable} spendable"
        )
    else:
        reason = (
            f"today's live run has not finished; {reserve} of the {policy.daily_requests} "
            f"{BACKFILL_PROVIDER} requests are reserved for it, leaving {spendable} "
            "spendable"
        )
    return BudgetReservation(
        provider=BACKFILL_PROVIDER,
        plan=plan,
        daily_allowance=policy.daily_requests,
        spent_today=spent,
        remaining_today=remaining,
        reserved_for_live_run=reserve,
        live_run_completed=live_run_completed,
        spendable=spendable,
        reason=reason,
    )


def vendor_splice_report(config: AppConfig) -> dict[str, Any] | None:
    """Flag a backfill whose chains come from a different vendor than the live ones.

    D3's correctness trap is usually read as "call the same functions". The same
    functions are not enough: an IV rank is a percentile of *one* series, and a series
    whose old points are one vendor's chain and whose new points are another's is not one
    series. The live path takes `config.providers.options[0]`; this backfill takes Alpha
    Vantage historical chains. When those differ, say so before anything is written.
    """

    live_order = tuple(config.providers.options)
    live_primary = live_order[0] if live_order else None
    if live_primary is None or live_primary == BACKFILL_PROVIDER:
        return None
    return {
        "live_options_provider": live_primary,
        "backfill_provider": BACKFILL_PROVIDER,
        "detail": (
            f"vendor splice: live option chains come from '{live_primary}' "
            f"(config.providers.options) while this backfill reads "
            f"'{BACKFILL_PROVIDER}' {BACKFILL_ENDPOINT}. A percentile built across both "
            "compares two vendors' quotes, taken at two different times of day, and "
            "reports a confident number for a comparison that was never made"
        ),
    }


def _request_cap(max_requests: int | None, reservation: BudgetReservation | None) -> int | None:
    caps = [cap for cap in (max_requests, reservation.spendable if reservation else None)
            if cap is not None]
    return min(caps) if caps else None


def _live_run_completed(repository: StorageRepository | None, run_date: date) -> bool:
    """True when a non-backfill run for this date has already finished.

    Its provider requests are spent by then, so what is left in the day's counter is
    genuinely spare rather than money the live run is about to need.
    """

    if repository is None:
        return False
    stmt = select(briefing_run.c.status, briefing_run.c.finished_at).where(
        briefing_run.c.run_date == run_date,
        briefing_run.c.run_type != BACKFILL_RUN_TYPE,
    )
    try:
        with repository.engine.connect() as conn:
            rows = conn.execute(stmt).all()
    except Exception:  # noqa: BLE001 - a missing table must not block the backfill.
        return False
    return any(
        row.finished_at is not None and str(row.status) in LIVE_RUN_DONE_STATUSES
        for row in rows
    )


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def default_backfill_tickers(config: AppConfig, *, run_date: date) -> tuple[str, ...]:
    loaded = load_universe(config, config.universe.mode)
    gate_report = run_gate(
        loaded.candidates,
        run_date=run_date,
        settings=config.gate,
        run_id=f"{BACKFILL_RUN_TYPE}-{run_date.isoformat()}",
        load_warnings=loaded.warnings,
        load_errors=loaded.errors,
    )
    seen: set[str] = set()
    tickers: list[str] = []
    for result in gate_report.accepted:
        candidate = result.candidate
        if candidate.geography is not Geography.US:
            continue
        ticker = candidate.ticker.strip().upper()
        if ticker in seen:
            continue
        seen.add(ticker)
        tickers.append(ticker)
    return tuple(tickers)


def session_dates(
    *,
    end_date: date,
    sessions: int,
    start_date: date | None = None,
) -> tuple[date, ...]:
    if sessions <= 0:
        raise ValueError("sessions must be positive")
    if start_date is not None:
        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")
        dates: list[date] = []
        cursor = start_date
        while cursor <= end_date:
            if cursor.weekday() < 5:
                dates.append(cursor)
            cursor += timedelta(days=1)
        return tuple(dates)

    dates = []
    cursor = end_date
    while len(dates) < sessions:
        if cursor.weekday() < 5:
            dates.append(cursor)
        cursor -= timedelta(days=1)
    return tuple(reversed(dates))


def _repository_for_backfill(data_dir: Path, *, dry_run: bool) -> StorageRepository | None:
    if os.getenv("DATABASE_URL"):
        return StorageRepository.from_env()

    sqlite_path = data_dir / LOCAL_SQLITE_FILENAME
    if dry_run:
        if not sqlite_path.exists():
            return None
        return StorageRepository(create_engine(f"sqlite+pysqlite:///{sqlite_path}", future=True))

    return StorageRepository.local_sqlite(data_dir)


def _stored_pair_count(
    repository: StorageRepository | None,
    pairs: Sequence[BackfillPair],
) -> int:
    if repository is None:
        return 0
    return sum(
        1
        for pair in pairs
        if repository.option_metrics_are_stored(pair.ticker, pair.snap_date)
    )


def _refresh_progress(
    result: BackfillResult,
    repository: StorageRepository | None,
    pairs: Sequence[BackfillPair],
    budget: RequestBudget,
    settings: AppSettings,
) -> None:
    stored = _stored_pair_count(repository, pairs)
    result.remaining = max(0, len(pairs) - stored)
    plan = settings.provider_plan(BACKFILL_PROVIDER)
    policy = budget.policy_for(BACKFILL_PROVIDER, plan=plan)
    result.budget_remaining_today = budget.remaining(BACKFILL_PROVIDER, plan=plan)
    if policy.daily_requests is None:
        result.estimated_days_at_allowance = None
    elif policy.daily_requests <= 0:
        result.estimated_days_at_allowance = None
    else:
        result.estimated_days_at_allowance = ceil(result.remaining / policy.daily_requests)


def _stored_histories(
    repository: StorageRepository | None,
    ticker: str,
    snap_date: date,
) -> tuple[list[float], list[float], list[float]]:
    if repository is None:
        return [], [], []
    rows = repository.option_metric_history(ticker, before_date=snap_date)
    iv_history = [float(row["iv_atm"]) for row in rows if row.get("iv_atm") is not None]
    pc_vol_history = [
        float(row["pc_ratio_vol"]) for row in rows if row.get("pc_ratio_vol") is not None
    ]
    pc_oi_history = [
        float(row["pc_ratio_oi"]) for row in rows if row.get("pc_ratio_oi") is not None
    ]
    return (
        iv_history if len(iv_history) >= SELF_BUILT_SERIES_MIN_SESSIONS else [],
        pc_vol_history if len(pc_vol_history) >= SELF_BUILT_SERIES_MIN_SESSIONS else [],
        pc_oi_history if len(pc_oi_history) >= SELF_BUILT_SERIES_MIN_SESSIONS else [],
    )


def _chain_is_verified(chain: Any) -> bool:
    return (
        getattr(chain, "validation_status", None) is ValidationStatus.VERIFIED
        and bool(getattr(chain, "contracts", ()))
    )


def _normalize_tickers(tickers: Sequence[str] | None) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in tickers or ():
        for part in str(raw).split(","):
            ticker = part.strip().upper()
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            result.append(ticker)
    return tuple(result)


def _previous_weekday(day: date) -> date:
    cursor = day
    while cursor.weekday() >= 5:
        cursor -= timedelta(days=1)
    return cursor
