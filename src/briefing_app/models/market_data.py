from __future__ import annotations

from datetime import UTC, date as date_type, datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class OptionType(StrEnum):
    CALL = "C"
    PUT = "P"

    @classmethod
    def _missing_(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip().upper()
            if normalized in {"CALL", "C"}:
                return cls.CALL
            if normalized in {"PUT", "P"}:
                return cls.PUT
        return None


class ValidationStatus(StrEnum):
    VERIFIED = "verified"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    REJECTED = "rejected"


class IssueSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class DataIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    severity: IssueSeverity = IssueSeverity.WARNING
    detail: str
    field_name: str | None = None


class OptionFilterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    min_open_interest: int = Field(default=10, ge=0)
    min_volume: int = Field(default=1, ge=0)
    max_bid_ask_width_pct: float = Field(default=0.25, ge=0)
    max_quote_age_minutes: int | None = Field(default=30, ge=0)


class EvidenceRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    component: str
    field_name: str
    field_value: str
    source: str
    venue: str = "*"
    as_of: datetime
    endpoint_or_file: str = ""
    validation_status: ValidationStatus = ValidationStatus.VERIFIED
    ticker: str = "*"
    note: str | None = None


class Quote(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ticker: str
    venue: str
    as_of: datetime
    price: float
    source: str
    bid: float | None = None
    ask: float | None = None
    open_price: float | None = None
    high: float | None = None
    low: float | None = None
    previous_close: float | None = None
    volume: int | None = None
    currency: str | None = None
    endpoint_or_file: str = ""
    validation_status: ValidationStatus = ValidationStatus.VERIFIED
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ticker")
    @classmethod
    def _clean_ticker(cls, value: str) -> str:
        return value.strip().upper()


class OptionContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    underlying: str
    contract_symbol: str
    expiry: date_type
    strike: float
    option_type: OptionType
    venue: str
    source: str
    bid: float | None = None
    ask: float | None = None
    mid: float | None = None
    last_trade_price: float | None = None
    last_trade_time: datetime | None = None
    volume: int | None = None
    open_interest: int | None = None
    implied_volatility: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    rho: float | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _derive_mid(cls, values: Any) -> Any:
        if not isinstance(values, dict) or values.get("mid") is not None:
            return values
        bid = values.get("bid")
        ask = values.get("ask")
        if bid is None or ask is None:
            return values
        try:
            bid_float = float(bid)
            ask_float = float(ask)
        except (TypeError, ValueError):
            return values
        if bid_float >= 0 and ask_float >= bid_float:
            values = dict(values)
            values["mid"] = (bid_float + ask_float) / 2
        return values

    def liquidity_issues(
        self,
        filters: OptionFilterConfig,
        *,
        reference_time: datetime | None = None,
    ) -> list[DataIssue]:
        issues: list[DataIssue] = []
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            issues.append(
                DataIssue(
                    code="crossed_market",
                    severity=IssueSeverity.ERROR,
                    detail=f"{self.contract_symbol} bid is greater than ask.",
                    field_name="bid_ask",
                )
            )

        if self.bid == 0 and self.ask == 0:
            issues.append(
                DataIssue(
                    code="zero_bid_ask",
                    severity=IssueSeverity.ERROR,
                    detail=f"{self.contract_symbol} has zero bid and ask.",
                    field_name="bid_ask",
                )
            )

        if self.open_interest is None or self.open_interest < filters.min_open_interest:
            issues.append(
                DataIssue(
                    code="low_open_interest",
                    detail=(
                        f"{self.contract_symbol} open interest "
                        f"{self.open_interest} < {filters.min_open_interest}."
                    ),
                    field_name="open_interest",
                )
            )

        if self.volume is None or self.volume < filters.min_volume:
            issues.append(
                DataIssue(
                    code="low_volume",
                    detail=(
                        f"{self.contract_symbol} volume "
                        f"{self.volume} < {filters.min_volume}."
                    ),
                    field_name="volume",
                )
            )

        if (
            self.bid is not None
            and self.ask is not None
            and self.ask >= self.bid
            and self.mid
            and self.mid > 0
        ):
            width_pct = (self.ask - self.bid) / self.mid
            if width_pct > filters.max_bid_ask_width_pct:
                issues.append(
                    DataIssue(
                        code="wide_bid_ask",
                        detail=(
                            f"{self.contract_symbol} bid/ask width "
                            f"{width_pct:.4f} > {filters.max_bid_ask_width_pct:.4f}."
                        ),
                        field_name="bid_ask",
                    )
                )

        if reference_time and filters.max_quote_age_minutes and self.last_trade_time:
            quote_age = _ensure_utc(reference_time) - _ensure_utc(self.last_trade_time)
            if quote_age > timedelta(minutes=filters.max_quote_age_minutes):
                issues.append(
                    DataIssue(
                        code="stale_option_trade",
                        detail=(
                            f"{self.contract_symbol} last trade age "
                            f"{quote_age.total_seconds() / 60:.1f}m exceeds "
                            f"{filters.max_quote_age_minutes}m."
                        ),
                        field_name="last_trade_time",
                    )
                )

        return issues


class OptionChain(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ticker: str
    venue: str
    as_of: datetime
    spot: float
    source: str
    endpoint_or_file: str = ""
    validation_status: ValidationStatus = ValidationStatus.VERIFIED
    contracts: list[OptionContract] = Field(default_factory=list)
    diagnostics: list[DataIssue] = Field(default_factory=list)

    @property
    def call_count(self) -> int:
        return len([c for c in self.contracts if c.option_type is OptionType.CALL])

    @property
    def put_count(self) -> int:
        return len([c for c in self.contracts if c.option_type is OptionType.PUT])

    def filtered(
        self,
        filters: OptionFilterConfig,
        *,
        reference_time: datetime | None = None,
    ) -> "OptionChain":
        kept: list[OptionContract] = []
        diagnostics = list(self.diagnostics)
        rejected_count = 0
        issue_counts: dict[str, int] = {}
        issue_examples: dict[str, str] = {}
        for contract in self.contracts:
            issues = contract.liquidity_issues(filters, reference_time=reference_time)
            if issues:
                rejected_count += 1
                for issue in issues:
                    issue_counts[issue.code] = issue_counts.get(issue.code, 0) + 1
                    issue_examples.setdefault(issue.code, issue.detail)
                continue
            kept.append(contract)

        for code, count in sorted(issue_counts.items()):
            diagnostics.append(
                DataIssue(
                    code=code,
                    severity=IssueSeverity.INFO,
                    detail=(
                        f"Filtered {count} option rows for {code}. "
                        f"Example: {issue_examples[code]}"
                    ),
                )
            )

        if rejected_count:
            diagnostics.append(
                DataIssue(
                    code="filtered_option_rows",
                    severity=IssueSeverity.INFO,
                    detail=f"Filtered {rejected_count} illiquid/stale option rows.",
                )
            )

        # Filtering can only degrade a chain's standing, never promote it. A manual or
        # partial capture that survives the liquidity filter is still a manual capture.
        status = self.validation_status if kept else ValidationStatus.UNAVAILABLE
        return self.model_copy(
            update={
                "contracts": kept,
                "diagnostics": diagnostics,
                "validation_status": status,
            }
        )


class PriceBar(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ticker: str
    date: date_type
    source: str
    open_price: float | None = None
    high: float | None = None
    low: float | None = None
    close: float
    adjusted_close: float | None = None
    volume: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class NewsArticle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ticker: str
    title: str
    source: str
    published_at: datetime
    url: str | None = None
    relevance_score: float | None = None
    sentiment_score: float | None = None
    sentiment_label: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class NewsSentimentBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ticker: str
    as_of: datetime
    source: str
    articles: list[NewsArticle] = Field(default_factory=list)
    validation_status: ValidationStatus = ValidationStatus.VERIFIED
    diagnostics: list[DataIssue] = Field(default_factory=list)


class PutCallSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ticker: str
    as_of: date_type
    source: str
    put_call_ratio: float | None = None
    put_call_volume_ratio: float | None = None
    put_call_open_interest_ratio: float | None = None
    put_volume: int | None = None
    call_volume: int | None = None
    put_open_interest: int | None = None
    call_open_interest: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ticker")
    @classmethod
    def _clean_ticker(cls, value: str) -> str:
        return value.strip().upper()


class CatalystEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ticker: str | None = None
    name: str
    event_date: date_type
    status: str = "estimated"
    kind: str = "other"
    source: str
    country: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class MacroEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    #: The period the reading measures. For CPI this is the first of the month surveyed,
    #: which is NOT when the number became public.
    event_date: datetime
    #: When the reading was actually published, where the provider can say. CPI for July
    #: is dated 2026-07-01 and released 2026-08-19; ageing it from the period start makes a
    #: two-week-old print look two months stale and drops it from S_M. Left `None` by
    #: providers that do not publish release dates, in which case `event_date` is used.
    released_at: datetime | None = None
    source: str
    country: str | None = None
    importance: str | None = None
    actual: str | None = None
    estimate: str | None = None
    previous: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class AnalystSignal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ticker: str
    as_of: date_type
    source: str
    firm: str | None = None
    analyst: str | None = None
    rating: str | None = None
    previous_rating: str | None = None
    action: str | None = None
    price_target: float | None = None
    previous_price_target: float | None = None
    eps_estimate: float | None = None
    revenue_estimate: float | None = None
    period: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ticker")
    @classmethod
    def _clean_ticker(cls, value: str) -> str:
        return value.strip().upper()


class InsiderTransaction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ticker: str
    as_of: date_type
    source: str
    insider: str | None = None
    title: str | None = None
    transaction_type: str | None = None
    acquisition_or_disposal: str | None = None
    shares: float | None = None
    price: float | None = None
    value: float | None = None
    shares_owned: float | None = None
    filing_date: date_type | None = None
    accession_number: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ticker")
    @classmethod
    def _clean_ticker(cls, value: str) -> str:
        return value.strip().upper()


class ShortInterestSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ticker: str | None = None
    isin: str | None = None
    issuer: str | None = None
    holder: str | None = None
    as_of: date_type
    source: str
    venue: str | None = None
    short_volume: int | None = None
    total_volume: int | None = None
    short_interest_pct_float: float | None = None
    disclosed_net_short_pct: float | None = None
    days_to_cover: float | None = None
    borrow_fee_pct: float | None = None
    utilization_pct: float | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class FilingRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ticker: str | None = None
    cik: str | None = None
    form: str
    filed_at: date_type
    report_date: date_type | None = None
    accession_number: str | None = None
    primary_document: str | None = None
    url: str | None = None
    source: str
    raw: dict[str, Any] = Field(default_factory=dict)


class OwnershipChange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ticker: str | None = None
    institution: str
    as_of: date_type
    source: str
    cohort: str | None = None
    shares: float | None = None
    shares_delta: float | None = None
    percent_delta: float | None = None
    estimated_capital_flow: float | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class FundamentalSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ticker: str
    as_of: date_type
    source: str
    period: str | None = None
    fiscal_year: int | None = None
    fiscal_quarter: str | None = None
    currency: str | None = None
    revenue: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    eps: float | None = None
    assets: float | None = None
    liabilities: float | None = None
    operating_cash_flow: float | None = None
    capital_expenditure: float | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ticker")
    @classmethod
    def _clean_ticker(cls, value: str) -> str:
        return value.strip().upper()


class _CalendarBase(BaseModel):
    """Shared completeness contract for event calendars.

    A calendar is the one data shape where *absence* is itself a claim: "no earnings in
    the window" drives the catalyst gate, the event-day range widening, and the
    unmodelled-earnings reject rule. Providers truncate calendars silently (FMP returned
    4 companies for a 9-day window in the source shakedown), so an empty list must never
    be read as "no event". These models carry the evidence for that judgement, and
    `absence_is_evidence` is the only sanctioned way to ask.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    as_of: datetime
    endpoint_or_file: str = ""
    #: Window the caller asked the provider for, when it asked for one.
    requested_start: date_type | None = None
    requested_end: date_type | None = None
    #: Set when the provider capped the response (a row limit, a plan-gated page).
    row_limit_reached: bool = False
    validation_status: ValidationStatus = ValidationStatus.VERIFIED
    diagnostics: list[DataIssue] = Field(default_factory=list)

    @property
    def absence_is_evidence(self) -> bool:
        """True only when "nothing here" can be trusted as "nothing happened".

        Requires a fully verified calendar that was not truncated. Everything else -
        partial, unavailable, or row-capped - means the gap may be the provider's.
        """
        return (
            self.validation_status is ValidationStatus.VERIFIED
            and not self.row_limit_reached
        )

    def covers(self, day: date_type) -> bool:
        """Whether the requested window includes `day`. Unbounded windows cover all."""
        if self.requested_start is not None and day < self.requested_start:
            return False
        if self.requested_end is not None and day > self.requested_end:
            return False
        return True


class CatalystCalendar(_CalendarBase):
    """Dated single-name events (earnings, decisions) plus how complete the pull was."""

    ticker: str | None = None
    events: list[CatalystEvent] = Field(default_factory=list)

    def events_between(self, start: date_type, end: date_type) -> list[CatalystEvent]:
        return [e for e in self.events if start <= e.event_date <= end]


class MacroCalendar(_CalendarBase):
    """Scheduled macro releases plus how complete the pull was."""

    events: list[MacroEvent] = Field(default_factory=list)

    def events_between(self, start: date_type, end: date_type) -> list[MacroEvent]:
        return [e for e in self.events if start <= e.event_date.date() <= end]


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
