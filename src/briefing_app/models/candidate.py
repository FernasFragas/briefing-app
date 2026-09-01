"""Candidate contract shared by universe construction, the catalyst gate, and scoring.

Owned by T2. Downstream tasks (T7 scoring, T8 setup rules, T9 rendering) consume
these models rather than redefining their own candidate shape.
"""

from __future__ import annotations

from datetime import date as date_type
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalise(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _lookup(cls: type[StrEnum], value: Any, aliases: dict[str, str]) -> Any:
    """Case- and separator-insensitive enum lookup with an explicit alias table."""
    if not isinstance(value, str):
        return None
    key = _normalise(value)
    for member in cls:
        if _normalise(member.value) == key or _normalise(member.name) == key:
            return member
    canonical = aliases.get(key)
    return cls(canonical) if canonical is not None else None


_GEOGRAPHY_ALIASES = {
    "usa": "US",
    "united_states": "US",
    "north_america": "US",
    "eu": "EU",
    "euro": "EU",
    "eurozone": "EU",
    "europe": "EU",
    "de": "EU",
    "germany": "EU",
    "france": "EU",
    "netherlands": "EU",
    "gb": "UK",
    "gbr": "UK",
    "united_kingdom": "UK",
}


class Geography(StrEnum):
    """Coarse venue geography. Drives the S_CTE weight profile and EU degradations."""

    US = "US"
    EU = "EU"
    UK = "UK"
    OTHER = "OTHER"

    @classmethod
    def _missing_(cls, value: Any) -> Any:
        return _lookup(cls, value, _GEOGRAPHY_ALIASES)

    @property
    def is_us(self) -> bool:
        return self is Geography.US

    @property
    def weight_profile(self) -> str:
        """`US` uses the US S_CTE weights; everything else uses the EU/non-US weights."""
        return "US" if self.is_us else "EU"


class ExpressionClass(StrEnum):
    """Declared BEFORE the data pull. Determines the required-component set."""

    V = "V"  # vol / options structure
    E = "E"  # event directional
    P = "P"  # positional fundamental
    S = "S"  # short / borrow-dependent

    @classmethod
    def _missing_(cls, value: Any) -> Any:
        return _lookup(
            cls,
            value,
            {
                "vol": "V",
                "volatility": "V",
                "event": "E",
                "event_directional": "E",
                "positional": "P",
                "fundamental": "P",
                "short": "S",
                "borrow": "S",
            },
        )


#: Classes whose required-component set includes `S_O` (a real per-strike chain).
OPTIONS_DEPENDENT_CLASSES: frozenset[ExpressionClass] = frozenset(
    {ExpressionClass.V, ExpressionClass.E}
)


class Direction(StrEnum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"

    @classmethod
    def _missing_(cls, value: Any) -> Any:
        return _lookup(cls, value, {"buy": "long", "sell": "short", "flat": "neutral"})


class CatalystStatus(StrEnum):
    """`Confirmed` is IR/exchange sourced. `Estimated` is cadence-inferred."""

    CONFIRMED = "confirmed"
    ESTIMATED = "estimated"

    @classmethod
    def _missing_(cls, value: Any) -> Any:
        return _lookup(
            cls,
            value,
            {"conf": "confirmed", "est": "estimated", "inferred": "estimated"},
        )


class Instrument(StrEnum):
    SHARES = "shares"
    ETF = "etf"
    OPTIONS = "options"
    FUTURES = "futures"
    FACTOR_CERTIFICATE = "factor_certificate"
    KNOCK_OUT = "knock_out"
    WARRANT = "warrant"
    CFD = "cfd"

    @classmethod
    def _missing_(cls, value: Any) -> Any:
        return _lookup(
            cls,
            value,
            {
                "share": "shares",
                "stock": "shares",
                "stocks": "shares",
                "equity": "shares",
                "equities": "shares",
                "option": "options",
                "etfs": "etf",
                "future": "futures",
                "factor_cert": "factor_certificate",
                "factor_certificates": "factor_certificate",
                "knockout": "knock_out",
                "knock_outs": "knock_out",
                "turbo": "knock_out",
                "warrants": "warrant",
                "cfds": "cfd",
            },
        )


#: Expressions that carry embedded leverage. An `Estimated` catalyst never authorises
#: one of these (plan Phase 2, `trading ideas.md` Stage 2/6).
DEFAULT_LEVERAGED_INSTRUMENTS: tuple[Instrument, ...] = (
    Instrument.FACTOR_CERTIFICATE,
    Instrument.KNOCK_OUT,
    Instrument.WARRANT,
    Instrument.CFD,
    Instrument.FUTURES,
)

#: Instruments that can actually express each class. A candidate whose platform
#: permits none of these cannot be traded, so it is not an idea.
DEFAULT_CLASS_INSTRUMENT_FIT: dict[ExpressionClass, tuple[Instrument, ...]] = {
    ExpressionClass.V: (Instrument.OPTIONS,),
    ExpressionClass.E: (
        Instrument.OPTIONS,
        Instrument.SHARES,
        Instrument.ETF,
        Instrument.FUTURES,
        Instrument.FACTOR_CERTIFICATE,
        Instrument.KNOCK_OUT,
        Instrument.WARRANT,
        Instrument.CFD,
    ),
    ExpressionClass.P: (Instrument.SHARES, Instrument.ETF, Instrument.OPTIONS),
    ExpressionClass.S: (
        Instrument.OPTIONS,
        Instrument.SHARES,
        Instrument.CFD,
        Instrument.KNOCK_OUT,
        Instrument.FACTOR_CERTIFICATE,
    ),
}


class SourceKind(StrEnum):
    """Where a thesis input came from. Aggregator-only theses are demoted or flagged."""

    PRIMARY = "primary"
    EXCHANGE = "exchange"
    REGULATOR = "regulator"
    COMPANY_IR = "company_ir"
    BROKER = "broker"
    AGGREGATOR = "aggregator"
    NEWS = "news"
    UNVERIFIED = "unverified"

    @classmethod
    def _missing_(cls, value: Any) -> Any:
        return _lookup(cls, value, {"ir": "company_ir", "filing": "regulator"})


#: Source kinds that count as primary support under the source hierarchy (Rule 1/3).
PRIMARY_SOURCE_KINDS: frozenset[SourceKind] = frozenset(
    {
        SourceKind.PRIMARY,
        SourceKind.EXCHANGE,
        SourceKind.REGULATOR,
        SourceKind.COMPANY_IR,
    }
)


class Crowding(StrEnum):
    CONSENSUS = "consensus"
    NEUTRAL = "neutral"
    CONTRARIAN = "contrarian"

    @classmethod
    def _missing_(cls, value: Any) -> Any:
        return _lookup(cls, value, {"crowded": "consensus", "none": "neutral"})


class CandidateSource(StrEnum):
    FIXED_UNIVERSE = "fixed_universe"
    SCREEN = "screen"
    SECTOR_MAP = "sector_map"
    WATCHLIST = "watchlist"
    MANUAL = "manual"

    @classmethod
    def _missing_(cls, value: Any) -> Any:
        return _lookup(cls, value, {"fixed": "fixed_universe", "screener": "screen"})


#: Catalyst kinds that force an event-day range widening downstream (T5/T8).
EARNINGS_CATALYST_KINDS: frozenset[str] = frozenset(
    {"earnings", "results", "trading_update", "capital_markets_day"}
)


class Catalyst(BaseModel):
    """A dated event inside (or outside) the trading horizon."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, frozen=True)

    name: str
    event_date: date_type = Field(alias="date")
    status: CatalystStatus
    kind: str = "other"
    source: str | None = None
    telegraphed: bool = False
    note: str | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("catalyst name must not be blank")
        return cleaned

    @field_validator("kind")
    @classmethod
    def _normalise_kind(cls, value: str) -> str:
        return _normalise(value) or "other"

    @property
    def is_confirmed(self) -> bool:
        return self.status is CatalystStatus.CONFIRMED

    @property
    def is_earnings(self) -> bool:
        return self.kind in EARNINGS_CATALYST_KINDS

    def label(self) -> str:
        return f"{self.name} ({self.event_date.isoformat()}, {self.status.value})"


class ThesisSource(BaseModel):
    """One sourced input behind the thesis, used for the aggregator-only gate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    kind: SourceKind = SourceKind.UNVERIFIED
    url: str | None = None
    as_of: date_type | None = None

    @property
    def is_primary(self) -> bool:
        return self.kind in PRIMARY_SOURCE_KINDS


class Candidate(BaseModel):
    """A tradeable idea entering the catalyst gate.

    Every field the gate needs must be declared by the candidate itself; the gate
    never infers geography, class, or instrument fit from market data.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ticker: str
    name: str | None = None
    venue: str
    geography: Geography
    country: str | None = None
    currency: str | None = None
    sector: str | None = None
    direction: Direction = Direction.LONG
    thesis: str
    horizon_days: int | None = Field(default=None, gt=0)
    expression_class: ExpressionClass
    broker: str | None = None
    permitted_instruments: list[Instrument] = Field(min_length=1)
    catalysts: list[Catalyst] = Field(default_factory=list)
    thesis_sources: list[ThesisSource] = Field(default_factory=list)
    borrow_source: str | None = None
    crowding: Crowding = Crowding.NEUTRAL
    source: CandidateSource = CandidateSource.MANUAL
    origin: str | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None

    @field_validator("ticker")
    @classmethod
    def _clean_ticker(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if not cleaned:
            raise ValueError("ticker must not be blank")
        return cleaned

    @field_validator("venue", "thesis")
    @classmethod
    def _clean_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be blank")
        return cleaned

    @field_validator("permitted_instruments")
    @classmethod
    def _dedupe_instruments(cls, value: list[Instrument]) -> list[Instrument]:
        seen: list[Instrument] = []
        for instrument in value:
            if instrument not in seen:
                seen.append(instrument)
        return seen

    @field_validator("catalysts")
    @classmethod
    def _sort_catalysts(cls, value: list[Catalyst]) -> list[Catalyst]:
        # Earliest first; a Confirmed date outranks an Estimated one on the same day.
        return sorted(value, key=lambda c: (c.event_date, 0 if c.is_confirmed else 1))

    @property
    def weight_profile(self) -> str:
        return self.geography.weight_profile

    @property
    def has_primary_thesis_support(self) -> bool:
        return any(source.is_primary for source in self.thesis_sources)

    def effective_horizon_days(self, default_horizon_days: int) -> int:
        return self.horizon_days if self.horizon_days is not None else default_horizon_days

    def catalysts_between(self, start: date_type, end: date_type) -> list[Catalyst]:
        return [c for c in self.catalysts if start <= c.event_date <= end]
