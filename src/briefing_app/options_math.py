"""Options math and S_O structure metrics.

This module is intentionally provider-agnostic. T4 normalizers can map CBOE,
Alpha Vantage, manual captures, or broker exports into `OptionQuote` /
`PriceBar`; this module only computes deterministic metrics from those typed
inputs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, time
from math import erf, exp, log, sqrt
from statistics import stdev
from typing import Any, Iterable, Literal, Mapping, Sequence

import numpy as np

from briefing_app.models.candidate import ExpressionClass, OPTIONS_DEPENDENT_CLASSES


OptionType = Literal["C", "P"]
DEALER_GAMMA_ASSUMPTION = "dealers short calls, long puts"

#: Share of consolidated daily volume that prints short on an ordinary liquid US name.
#: Much of it is market-maker hedging rather than directional selling, so the baseline is
#: near half and only the excess over it is treated as signal.
SHORT_VOLUME_RATIO_BASELINE: float = 0.50
#: Excess over the baseline that saturates the short-volume contribution at 1.0.
SHORT_VOLUME_RATIO_SPAN: float = 0.30


class OptionsMathError(ValueError):
    """Raised when an options metric cannot be computed from supplied inputs."""


class DistributionError(OptionsMathError):
    """Raised when an implied-density sanity check fails."""


@dataclass(frozen=True)
class PriceRange:
    low: float
    high: float
    midpoint: float

    @property
    def width(self) -> float:
        return self.high - self.low


@dataclass(frozen=True)
class OptionQuote:
    ticker: str
    expiry: date
    strike: float
    option_type: str
    bid: float
    ask: float
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    open_interest: int = 0
    volume: int = 0
    as_of: datetime | None = None
    venue: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", self.ticker.strip().upper())
        object.__setattr__(self, "expiry", _to_date(self.expiry))
        object.__setattr__(self, "strike", _required_float(self.strike, "strike"))
        object.__setattr__(self, "bid", _non_negative_float(self.bid, "bid"))
        object.__setattr__(self, "ask", _non_negative_float(self.ask, "ask"))
        object.__setattr__(self, "iv", _optional_non_negative_float(self.iv, "iv"))
        object.__setattr__(self, "delta", _optional_float(self.delta, "delta"))
        object.__setattr__(self, "gamma", _optional_non_negative_float(self.gamma, "gamma"))
        object.__setattr__(
            self,
            "open_interest",
            _non_negative_int(self.open_interest, "open_interest"),
        )
        object.__setattr__(self, "volume", _non_negative_int(self.volume, "volume"))
        if self.ask < self.bid:
            raise ValueError("ask must be greater than or equal to bid")

        raw_type = str(self.option_type).strip().upper()
        if raw_type in {"CALL", "C"}:
            normalized_type: OptionType = "C"
        elif raw_type in {"PUT", "P"}:
            normalized_type = "P"
        else:
            raise ValueError(f"unknown option type: {self.option_type!r}")
        object.__setattr__(self, "option_type", normalized_type)

    @property
    def mid(self) -> float:
        return mid_price(self.bid, self.ask)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any], *, ticker: str | None = None) -> "OptionQuote":
        """Build from common normalized/provider field names."""

        bid = payload.get("bid")
        ask = payload.get("ask")
        mid = payload.get("mid", payload.get("settlement", payload.get("last_trade_price")))
        if (bid is None or ask is None) and mid is not None:
            bid = mid
            ask = mid

        return cls(
            ticker=str(ticker or payload.get("ticker") or payload.get("underlying") or payload.get("symbol") or ""),
            expiry=_required(payload, "expiry", "expiration", "expiration_date"),
            strike=_required(payload, "strike"),
            option_type=_required(payload, "option_type", "type", "put_call", "right"),
            bid=_required({"bid": bid}, "bid"),
            ask=_required({"ask": ask}, "ask"),
            iv=payload.get("iv", payload.get("implied_volatility")),
            delta=payload.get("delta"),
            gamma=payload.get("gamma"),
            open_interest=payload.get("open_interest", payload.get("oi", 0)),
            volume=payload.get("volume", 0),
            as_of=_to_datetime(payload["as_of"]) if payload.get("as_of") else None,
            venue=payload.get("venue"),
        )


@dataclass(frozen=True)
class PriceBar:
    bar_date: date
    close: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "bar_date", _to_date(self.bar_date))
        object.__setattr__(self, "close", _positive_float(self.close, "close"))

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PriceBar":
        return cls(
            bar_date=_required(payload, "date", "bar_date", "timestamp"),
            close=_required(payload, "close", "adjusted_close"),
        )


@dataclass(frozen=True)
class AtmStraddle:
    expiry: date
    dte: int
    strike: float
    call: OptionQuote
    put: OptionQuote


@dataclass(frozen=True)
class ExpectedMove:
    target_dte: int
    expiry: date
    dte: int
    atm_strike: float
    call_mid: float
    put_mid: float
    iv_atm: float | None
    straddle_points: float
    straddle_pct: float
    iv_points: float | None
    iv_pct: float | None
    divergence_pct: float | None
    divergence_exceeds_threshold: bool
    one_sigma_straddle: PriceRange
    two_sigma_straddle: PriceRange
    one_sigma_iv: PriceRange | None
    two_sigma_iv: PriceRange | None
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class RealizedVolatility:
    lookback_days: int
    trading_days: int
    sample_count: int
    daily_stdev: float
    annualized_vol: float


@dataclass(frozen=True)
class MeasuredSigmaRange:
    low: float
    high: float
    midpoint: float
    lookback_days: int
    horizon_days: int
    trading_days: int
    sigma_pct: float
    event_multiplier: float
    adjusted_sigma_pct: float
    one_sigma: PriceRange
    two_sigma: PriceRange
    #: Calendar span the horizon came from, when it was converted from a DTE.
    calendar_horizon_days: int | None = None


@dataclass(frozen=True)
class RiskReversal25D:
    expiry: date
    call_strike: float
    put_strike: float
    call_delta: float
    put_delta: float
    call_iv: float
    put_iv: float
    rr_25d: float


@dataclass(frozen=True)
class OiCluster:
    expiry: date
    strike: float
    call_open_interest: int
    put_open_interest: int
    total_open_interest: int
    concentration: float


@dataclass(frozen=True)
class PutCallMetrics:
    expiry: date | None
    put_volume: int
    call_volume: int
    put_open_interest: int
    call_open_interest: int
    volume_ratio: float | None
    open_interest_ratio: float | None
    volume_percentile: float | None
    open_interest_percentile: float | None


@dataclass(frozen=True)
class GammaByStrike:
    expiry: date
    strike: float
    call_gamma_units: float
    put_gamma_units: float
    net_dealer_gamma_units: float
    assumption: str = DEALER_GAMMA_ASSUMPTION


@dataclass(frozen=True)
class DistributionPoint:
    strike: float
    density: float
    cdf: float
    probability_above: float


@dataclass(frozen=True)
class ImpliedDistribution:
    expiry: date
    dte: int
    time_years: float
    points: tuple[DistributionPoint, ...]
    mean: float
    forward: float
    #: Integral of the returned (normalized) density. 1.0 by construction.
    total_probability: float
    repaired_negative_density: bool = False
    diagnostics: tuple[str, ...] = ()
    #: Raw Breeden-Litzenberger mass over the fitted strike range, before normalization.
    #: Well below 1.0 means the chain spans only part of the distribution, so tail
    #: probability queries are unreliable no matter how clean the normalized curve looks.
    captured_probability_mass: float = 1.0
    #: Fitted strike range, so a consumer can see what the probabilities are conditioned on.
    strike_low: float | None = None
    strike_high: float | None = None


@dataclass(frozen=True)
class ShortBorrowSnapshot:
    """Short and borrow inputs behind the `short_borrow` leg of S_O.

    `short_volume_ratio` is deliberately a separate field rather than a stand-in for
    `short_interest_pct_float`. FINRA's consolidated daily file reports the share of the
    day's *volume* that printed short - typically 0.45-0.55 for a liquid US name, much of
    it market-maker hedging - while short interest is the share of *float* held short,
    typically 0.01-0.10. Mapping one onto the other would read an ordinary tape as
    maximum squeeze risk.
    """

    verified: bool
    short_interest_pct_float: float | None = None
    days_to_cover: float | None = None
    borrow_fee_pct: float | None = None
    utilization_pct: float | None = None
    #: Share of consolidated daily volume that printed short, 0..1. A flow proxy only.
    short_volume_ratio: float | None = None
    source: str | None = None
    as_of: date | datetime | None = None


@dataclass(frozen=True)
class ShortBorrowMetrics:
    verified: bool
    score: float | None
    squeeze_risk_score: float | None
    inputs_used: tuple[str, ...]
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class OptionsStructureResult:
    ticker: str
    as_of: datetime
    spot: float
    available: bool
    score: float | None
    na_reason: str | None = None
    expected_moves: dict[str, ExpectedMove] = field(default_factory=dict)
    realized_volatility: dict[int, RealizedVolatility] = field(default_factory=dict)
    measured_range: MeasuredSigmaRange | None = None
    iv_rank: float | None = None
    variance_risk_premium: float | None = None
    risk_reversal_25d: RiskReversal25D | None = None
    oi_clusters: tuple[OiCluster, ...] = ()
    put_call: PutCallMetrics | None = None
    gamma_by_strike: tuple[GammaByStrike, ...] = ()
    implied_distribution: ImpliedDistribution | None = None
    short_borrow: ShortBorrowMetrics | None = None
    sub_scores: dict[str, float] = field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()
    evidence_rows: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


def mid_price(bid: float, ask: float) -> float:
    bid_value = _non_negative_float(bid, "bid")
    ask_value = _non_negative_float(ask, "ask")
    if ask_value < bid_value:
        raise ValueError("ask must be greater than or equal to bid")
    return (bid_value + ask_value) / 2.0


def days_to_expiry(as_of: date | datetime, expiry: date | datetime) -> int:
    """Calendar DTE used for option-implied annualization."""

    return (_to_date(expiry) - _to_date(as_of)).days


def select_expiry_by_dte(
    quotes: Sequence[OptionQuote | Mapping[str, Any]],
    *,
    as_of: date | datetime,
    target_dte: int,
) -> date:
    normalized = normalize_option_quotes(quotes)
    expiries = sorted({quote.expiry for quote in normalized if days_to_expiry(as_of, quote.expiry) > 0})
    if not expiries:
        raise OptionsMathError("no unexpired option expiries available")
    return min(expiries, key=lambda expiry: (abs(days_to_expiry(as_of, expiry) - target_dte), expiry))


def select_atm_straddle(
    quotes: Sequence[OptionQuote | Mapping[str, Any]],
    *,
    spot: float,
    as_of: date | datetime,
    expiry: date,
) -> AtmStraddle:
    normalized = [quote for quote in normalize_option_quotes(quotes) if quote.expiry == expiry]
    calls = _quotes_by_strike(normalized, "C")
    puts = _quotes_by_strike(normalized, "P")
    paired_strikes = sorted(set(calls) & set(puts))
    if not paired_strikes:
        raise OptionsMathError(f"no call/put pair available for expiry {expiry.isoformat()}")

    atm_strike = min(paired_strikes, key=lambda strike: (abs(strike - spot), strike))
    dte = days_to_expiry(as_of, expiry)
    if dte <= 0:
        raise OptionsMathError(f"expiry {expiry.isoformat()} is not after as-of date")
    return AtmStraddle(
        expiry=expiry,
        dte=dte,
        strike=atm_strike,
        call=_best_quote(calls[atm_strike]),
        put=_best_quote(puts[atm_strike]),
    )


def compute_expected_move(
    quotes: Sequence[OptionQuote | Mapping[str, Any]],
    *,
    spot: float,
    as_of: date | datetime,
    target_dte: int,
    expiry: date | None = None,
    divergence_threshold: float = 0.25,
) -> ExpectedMove:
    spot_value = _positive_float(spot, "spot")
    selected_expiry = expiry or select_expiry_by_dte(quotes, as_of=as_of, target_dte=target_dte)
    straddle = select_atm_straddle(quotes, spot=spot_value, as_of=as_of, expiry=selected_expiry)

    call_mid = straddle.call.mid
    put_mid = straddle.put.mid
    straddle_points = call_mid + put_mid
    straddle_pct = straddle_points / spot_value

    iv_values = [quote.iv for quote in (straddle.call, straddle.put) if quote.iv is not None]
    iv_atm = (sum(iv_values) / len(iv_values)) if iv_values else None
    iv_pct = iv_atm * sqrt(straddle.dte / 365.0) if iv_atm is not None else None
    iv_points = spot_value * iv_pct if iv_pct is not None else None

    divergence_pct = None
    divergence_exceeds = False
    diagnostics: list[str] = []
    if iv_pct is None:
        diagnostics.append("ATM IV unavailable; expected move from IV not computed.")
    else:
        divergence_pct = abs(straddle_pct - iv_pct) / max(abs(iv_pct), 1e-12)
        divergence_exceeds = divergence_pct > divergence_threshold
        if divergence_exceeds:
            diagnostics.append(
                "Expected move divergence exceeds threshold: "
                f"straddle={straddle_pct:.6f}, iv={iv_pct:.6f}, "
                f"relative_diff={divergence_pct:.6f}, threshold={divergence_threshold:.6f}."
            )

    return ExpectedMove(
        target_dte=target_dte,
        expiry=selected_expiry,
        dte=straddle.dte,
        atm_strike=straddle.strike,
        call_mid=call_mid,
        put_mid=put_mid,
        iv_atm=iv_atm,
        straddle_points=straddle_points,
        straddle_pct=straddle_pct,
        iv_points=iv_points,
        iv_pct=iv_pct,
        divergence_pct=divergence_pct,
        divergence_exceeds_threshold=divergence_exceeds,
        one_sigma_straddle=range_from_points(spot_value, straddle_points),
        two_sigma_straddle=range_from_points(spot_value, straddle_points * 2.0),
        one_sigma_iv=range_from_points(spot_value, iv_points) if iv_points is not None else None,
        two_sigma_iv=range_from_points(spot_value, iv_points * 2.0) if iv_points is not None else None,
        diagnostics=tuple(diagnostics),
    )


def range_from_points(spot: float, points: float) -> PriceRange:
    spot_value = _positive_float(spot, "spot")
    move_points = _non_negative_float(points, "points")
    return PriceRange(
        low=spot_value - move_points,
        high=spot_value + move_points,
        midpoint=spot_value,
    )


def realized_volatility(
    bars: Sequence[PriceBar | Mapping[str, Any] | tuple[date, float]],
    *,
    lookback_days: int,
    trading_days: int = 252,
) -> RealizedVolatility:
    """Annualized realized volatility from log returns.

    Realized volatility uses trading-day annualization (`sqrt(252)` by default),
    separately from option DTE annualization (`sqrt(DTE / 365)`).
    """

    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    if trading_days <= 0:
        raise ValueError("trading_days must be positive")

    normalized = sorted(normalize_price_bars(bars), key=lambda bar: bar.bar_date)
    if len(normalized) < lookback_days + 1:
        raise OptionsMathError(
            f"need at least {lookback_days + 1} closes for {lookback_days} returns; "
            f"got {len(normalized)}"
        )

    window = normalized[-(lookback_days + 1) :]
    returns = [
        log(window[index].close / window[index - 1].close)
        for index in range(1, len(window))
    ]
    daily_stdev = stdev(returns) if len(returns) > 1 else 0.0
    return RealizedVolatility(
        lookback_days=lookback_days,
        trading_days=trading_days,
        sample_count=len(returns),
        daily_stdev=daily_stdev,
        annualized_vol=daily_stdev * sqrt(trading_days),
    )


def trading_days_from_calendar_days(
    calendar_days: int,
    *,
    trading_days: int = 252,
    calendar_days_per_year: int = 365,
) -> int:
    """Convert a calendar span (an option DTE) into trading days.

    Realized volatility is annualized on trading days (`sqrt(252)`) while option DTE is
    a calendar count annualized on `sqrt(365)`. Scaling a trading-day vol by a calendar
    horizon overstates the range by roughly `sqrt(365 / 252)` (about 20 percent), so the
    two conventions must be reconciled explicitly rather than by coincidence.
    """

    if calendar_days <= 0:
        raise ValueError("calendar_days must be positive")
    converted = round(calendar_days * trading_days / calendar_days_per_year)
    return max(1, int(converted))


def build_measured_sigma_range(
    *,
    spot: float,
    realized_vol: float,
    lookback_days: int,
    horizon_days: int,
    trading_days: int = 252,
    event_multiplier: float = 1.0,
    calendar_horizon_days: int | None = None,
) -> MeasuredSigmaRange:
    """Measured-sigma band from realized volatility.

    `horizon_days` is counted in TRADING days, matching `trading_days` (252 by default).
    Convert an option DTE with `trading_days_from_calendar_days` before calling.
    """

    spot_value = _positive_float(spot, "spot")
    vol = _non_negative_float(realized_vol, "realized_vol")
    if horizon_days <= 0:
        raise ValueError("horizon_days must be positive")
    if trading_days <= 0:
        raise ValueError("trading_days must be positive")
    multiplier = _positive_float(event_multiplier, "event_multiplier")

    sigma_pct = vol * sqrt(horizon_days / trading_days)
    adjusted_sigma_pct = sigma_pct * multiplier
    one_sigma_points = spot_value * adjusted_sigma_pct
    two_sigma_points = one_sigma_points * 2.0
    one_sigma = range_from_points(spot_value, one_sigma_points)
    two_sigma = range_from_points(spot_value, two_sigma_points)
    return MeasuredSigmaRange(
        low=one_sigma.low,
        high=one_sigma.high,
        midpoint=spot_value,
        lookback_days=lookback_days,
        horizon_days=horizon_days,
        trading_days=trading_days,
        calendar_horizon_days=calendar_horizon_days,
        sigma_pct=sigma_pct,
        event_multiplier=multiplier,
        adjusted_sigma_pct=adjusted_sigma_pct,
        one_sigma=one_sigma,
        two_sigma=two_sigma,
    )


def percentile_rank(value: float, history: Sequence[float]) -> float | None:
    samples = sorted(_required_float(sample, "history sample") for sample in history if sample is not None)
    if not samples:
        return None
    current = _required_float(value, "value")
    below_or_equal = sum(1 for sample in samples if sample <= current)
    return (below_or_equal / len(samples)) * 100.0


def iv_rank_from_history(current_iv: float | None, history: Sequence[float]) -> float | None:
    if current_iv is None:
        return None
    return percentile_rank(current_iv, history)


def variance_risk_premium(iv_atm: float | None, realized_vol_20d: float | None) -> float | None:
    if iv_atm is None or realized_vol_20d is None:
        return None
    return _non_negative_float(iv_atm, "iv_atm") - _non_negative_float(realized_vol_20d, "realized_vol_20d")


def risk_reversal_25d(
    quotes: Sequence[OptionQuote | Mapping[str, Any]],
    *,
    expiry: date,
) -> RiskReversal25D | None:
    normalized = [quote for quote in normalize_option_quotes(quotes) if quote.expiry == expiry and quote.iv is not None and quote.delta is not None]
    call = _nearest_delta_quote([quote for quote in normalized if quote.option_type == "C"], 0.25)
    put = _nearest_abs_delta_quote([quote for quote in normalized if quote.option_type == "P"], 0.25)
    if call is None or put is None or call.iv is None or put.iv is None or call.delta is None or put.delta is None:
        return None
    return RiskReversal25D(
        expiry=expiry,
        call_strike=call.strike,
        put_strike=put.strike,
        call_delta=call.delta,
        put_delta=put.delta,
        call_iv=call.iv,
        put_iv=put.iv,
        rr_25d=call.iv - put.iv,
    )


def detect_oi_clusters(
    quotes: Sequence[OptionQuote | Mapping[str, Any]],
    *,
    expiry: date | None = None,
    limit: int = 5,
) -> tuple[OiCluster, ...]:
    normalized = normalize_option_quotes(quotes)
    if expiry is not None:
        normalized = [quote for quote in normalized if quote.expiry == expiry]

    grouped: dict[tuple[date, float], dict[str, int]] = {}
    for quote in normalized:
        bucket = grouped.setdefault(
            (quote.expiry, quote.strike),
            {"call": 0, "put": 0},
        )
        key = "call" if quote.option_type == "C" else "put"
        bucket[key] += quote.open_interest

    total_oi = sum(values["call"] + values["put"] for values in grouped.values())
    if total_oi <= 0:
        return ()

    clusters = [
        OiCluster(
            expiry=key[0],
            strike=key[1],
            call_open_interest=values["call"],
            put_open_interest=values["put"],
            total_open_interest=values["call"] + values["put"],
            concentration=(values["call"] + values["put"]) / total_oi,
        )
        for key, values in grouped.items()
        if values["call"] + values["put"] > 0
    ]
    clusters.sort(key=lambda cluster: (-cluster.total_open_interest, cluster.expiry, cluster.strike))
    return tuple(clusters[:limit])


def put_call_metrics(
    quotes: Sequence[OptionQuote | Mapping[str, Any]],
    *,
    expiry: date | None = None,
    volume_history: Sequence[float] = (),
    open_interest_history: Sequence[float] = (),
) -> PutCallMetrics:
    normalized = normalize_option_quotes(quotes)
    if expiry is not None:
        normalized = [quote for quote in normalized if quote.expiry == expiry]

    put_volume = sum(quote.volume for quote in normalized if quote.option_type == "P")
    call_volume = sum(quote.volume for quote in normalized if quote.option_type == "C")
    put_oi = sum(quote.open_interest for quote in normalized if quote.option_type == "P")
    call_oi = sum(quote.open_interest for quote in normalized if quote.option_type == "C")

    volume_ratio = _safe_ratio(put_volume, call_volume)
    oi_ratio = _safe_ratio(put_oi, call_oi)
    return PutCallMetrics(
        expiry=expiry,
        put_volume=put_volume,
        call_volume=call_volume,
        put_open_interest=put_oi,
        call_open_interest=call_oi,
        volume_ratio=volume_ratio,
        open_interest_ratio=oi_ratio,
        volume_percentile=percentile_rank(volume_ratio, volume_history) if volume_ratio is not None else None,
        open_interest_percentile=percentile_rank(oi_ratio, open_interest_history) if oi_ratio is not None else None,
    )


def gamma_by_strike(
    quotes: Sequence[OptionQuote | Mapping[str, Any]],
    *,
    expiry: date | None = None,
    contract_multiplier: int = 100,
    limit: int | None = None,
) -> tuple[GammaByStrike, ...]:
    normalized = normalize_option_quotes(quotes)
    if expiry is not None:
        normalized = [quote for quote in normalized if quote.expiry == expiry]

    grouped: dict[tuple[date, float], dict[str, float]] = {}
    for quote in normalized:
        if quote.gamma is None:
            continue
        bucket = grouped.setdefault(
            (quote.expiry, quote.strike),
            {"call": 0.0, "put": 0.0},
        )
        gamma_units = quote.gamma * quote.open_interest * contract_multiplier
        key = "call" if quote.option_type == "C" else "put"
        bucket[key] += gamma_units

    rows = [
        GammaByStrike(
            expiry=key[0],
            strike=key[1],
            call_gamma_units=values["call"],
            put_gamma_units=values["put"],
            net_dealer_gamma_units=values["put"] - values["call"],
        )
        for key, values in grouped.items()
    ]
    rows.sort(key=lambda row: (-abs(row.net_dealer_gamma_units), row.expiry, row.strike))
    return tuple(rows[:limit] if limit is not None else rows)


def black_scholes_call_price(
    *,
    spot: float,
    strike: float,
    time_years: float,
    volatility: float,
    risk_free_rate: float = 0.0,
    dividend_yield: float = 0.0,
) -> float:
    spot_value = _positive_float(spot, "spot")
    strike_value = _positive_float(strike, "strike")
    vol = _positive_float(volatility, "volatility")
    if time_years <= 0:
        return max(spot_value - strike_value, 0.0)

    sqrt_t = sqrt(time_years)
    d1 = (
        log(spot_value / strike_value)
        + (risk_free_rate - dividend_yield + 0.5 * vol * vol) * time_years
    ) / (vol * sqrt_t)
    d2 = d1 - vol * sqrt_t
    return (
        spot_value * exp(-dividend_yield * time_years) * _normal_cdf(d1)
        - strike_value * exp(-risk_free_rate * time_years) * _normal_cdf(d2)
    )


def density_from_call_prices(
    strikes: Sequence[float],
    call_prices: Sequence[float],
    *,
    time_years: float,
    risk_free_rate: float = 0.0,
    repair_negative: bool = True,
    negative_tolerance: float = 1e-9,
) -> tuple[tuple[DistributionPoint, ...], bool, float, float]:
    """Breeden-Litzenberger density from uniformly spaced call prices.

    Returns `(points, repaired, total_probability, captured_mass)`. `total_probability`
    is measured after normalization, so it is 1.0 by construction; `captured_mass` is
    the raw integral over the supplied strike range, which is the figure that actually
    says whether the chain spans enough of the distribution to trust a probability
    query. A chain covering a sliver around spot still normalizes to 1.0.
    """

    strike_values = np.asarray([_positive_float(value, "strike") for value in strikes], dtype=float)
    price_values = np.asarray([_call_price_float(value) for value in call_prices], dtype=float)
    if len(strike_values) != len(price_values):
        raise ValueError("strikes and call_prices must have the same length")
    if len(strike_values) < 4:
        raise DistributionError("need at least four call prices for density integration")
    if np.any(np.diff(strike_values) <= 0):
        raise DistributionError("strikes must be strictly increasing")

    diffs = np.diff(strike_values)
    if not np.allclose(diffs, diffs[0], rtol=1e-6, atol=1e-9):
        raise DistributionError("density_from_call_prices requires uniformly spaced strikes")

    h = float(diffs[0])
    density = np.exp(risk_free_rate * time_years) * (
        price_values[2:] - (2.0 * price_values[1:-1]) + price_values[:-2]
    ) / (h * h)
    interior_strikes = strike_values[1:-1]

    negative_mask = density < -negative_tolerance
    repaired = False
    if np.any(negative_mask):
        if not repair_negative:
            minimum = float(np.min(density))
            raise DistributionError(f"negative implied density encountered: min={minimum:.12f}")
        density = np.where(density < 0.0, 0.0, density)
        repaired = True
    else:
        density = np.where(density < 0.0, 0.0, density)

    area = _trapezoid(density, interior_strikes)
    if area <= 0.0:
        raise DistributionError("implied density integrates to zero")

    normalized_density = density / area
    cdf_values = _cumulative_trapezoid(normalized_density, interior_strikes)
    total_probability = float(cdf_values[-1])
    if total_probability <= 0.0:
        raise DistributionError("normalized implied density integrates to zero")
    cdf_values = cdf_values / total_probability

    points = tuple(
        DistributionPoint(
            strike=float(strike),
            density=float(value),
            cdf=float(cdf),
            probability_above=float(max(0.0, 1.0 - cdf)),
        )
        for strike, value, cdf in zip(interior_strikes, normalized_density, cdf_values)
    )
    return points, repaired, total_probability, float(area)


def implied_distribution(
    quotes: Sequence[OptionQuote | Mapping[str, Any]],
    *,
    spot: float,
    as_of: date | datetime,
    expiry: date,
    grid_size: int = 101,
    risk_free_rate: float = 0.0,
    dividend_yield: float = 0.0,
    repair_negative: bool = True,
    mean_tolerance_pct: float = 0.08,
    min_captured_mass: float = 0.80,
) -> ImpliedDistribution:
    spot_value = _positive_float(spot, "spot")
    dte = days_to_expiry(as_of, expiry)
    if dte <= 0:
        raise DistributionError("expiry must be after as-of date")
    time_years = dte / 365.0

    calls = [
        quote
        for quote in normalize_option_quotes(quotes)
        if quote.expiry == expiry and quote.option_type == "C" and quote.iv is not None
    ]
    if len({quote.strike for quote in calls}) < 3:
        raise DistributionError("need at least three call strikes with IV for smile fit")

    iv_by_strike: dict[float, list[float]] = {}
    for quote in calls:
        iv_by_strike.setdefault(quote.strike, []).append(float(quote.iv))
    strikes = np.asarray(sorted(iv_by_strike), dtype=float)
    ivs = np.asarray([sum(iv_by_strike[strike]) / len(iv_by_strike[strike]) for strike in strikes], dtype=float)

    degree = min(2, len(strikes) - 1)
    x = np.log(strikes / spot_value)
    coefficients = np.polyfit(x, ivs, degree)
    dense_strikes = np.linspace(float(strikes[0]), float(strikes[-1]), max(grid_size, 7))
    dense_x = np.log(dense_strikes / spot_value)
    fitted_ivs = np.polyval(coefficients, dense_x)

    diagnostics: list[str] = []
    if np.any(fitted_ivs <= 0.0):
        diagnostics.append("Smile fit produced non-positive IV values; clipped to 0.0001.")
        fitted_ivs = np.maximum(fitted_ivs, 0.0001)

    call_prices = [
        black_scholes_call_price(
            spot=spot_value,
            strike=float(strike),
            time_years=time_years,
            volatility=float(vol),
            risk_free_rate=risk_free_rate,
            dividend_yield=dividend_yield,
        )
        for strike, vol in zip(dense_strikes, fitted_ivs)
    ]
    points, repaired, total_probability, captured_mass = density_from_call_prices(
        dense_strikes,
        call_prices,
        time_years=time_years,
        risk_free_rate=risk_free_rate,
        repair_negative=repair_negative,
    )
    if repaired:
        diagnostics.append("Negative density was clipped to zero before normalization.")
    if captured_mass < min_captured_mass:
        diagnostics.append(
            f"Fitted strikes {dense_strikes[0]:.4f}-{dense_strikes[-1]:.4f} capture only "
            f"{captured_mass:.4f} of the implied distribution "
            f"(minimum {min_captured_mass:.4f}); tail probabilities are unreliable."
        )

    point_strikes = np.asarray([point.strike for point in points], dtype=float)
    density = np.asarray([point.density for point in points], dtype=float)
    mean = _trapezoid(point_strikes * density, point_strikes)
    forward = spot_value * exp((risk_free_rate - dividend_yield) * time_years)
    if abs(mean - forward) / spot_value > mean_tolerance_pct:
        diagnostics.append(
            f"Distribution mean {mean:.6f} is outside tolerance of forward {forward:.6f}."
        )

    return ImpliedDistribution(
        expiry=expiry,
        dte=dte,
        time_years=time_years,
        points=points,
        mean=mean,
        forward=forward,
        total_probability=total_probability,
        repaired_negative_density=repaired,
        diagnostics=tuple(diagnostics),
        captured_probability_mass=captured_mass,
        strike_low=float(dense_strikes[0]),
        strike_high=float(dense_strikes[-1]),
    )


def probability_below(distribution: ImpliedDistribution, strike: float) -> float:
    strikes = [point.strike for point in distribution.points]
    cdfs = [point.cdf for point in distribution.points]
    return float(np.interp(_required_float(strike, "strike"), strikes, cdfs, left=0.0, right=1.0))


def probability_above(distribution: ImpliedDistribution, strike: float) -> float:
    return 1.0 - probability_below(distribution, strike)


def short_borrow_metrics(snapshot: ShortBorrowSnapshot | Mapping[str, Any] | None) -> ShortBorrowMetrics | None:
    if snapshot is None:
        return None
    normalized = _normalize_short_borrow(snapshot)
    if not normalized.verified:
        return ShortBorrowMetrics(
            verified=False,
            score=None,
            squeeze_risk_score=None,
            inputs_used=(),
            diagnostics=("Short/borrow data is unverified.",),
        )

    components: list[float] = []
    inputs_used: list[str] = []
    if normalized.short_interest_pct_float is not None:
        components.append(_clamp(normalized.short_interest_pct_float / 30.0, 0.0, 1.0))
        inputs_used.append("short_interest_pct_float")
    if normalized.days_to_cover is not None:
        components.append(_clamp(normalized.days_to_cover / 10.0, 0.0, 1.0))
        inputs_used.append("days_to_cover")
    if normalized.borrow_fee_pct is not None:
        components.append(_clamp(normalized.borrow_fee_pct / 50.0, 0.0, 1.0))
        inputs_used.append("borrow_fee_pct")
    if normalized.utilization_pct is not None:
        components.append(_clamp(normalized.utilization_pct / 100.0, 0.0, 1.0))
        inputs_used.append("utilization_pct")

    diagnostics: list[str] = []
    if normalized.short_volume_ratio is not None:
        # Baseline short volume on a liquid US name sits near SHORT_VOLUME_RATIO_BASELINE,
        # so only the excess over it carries signal. A ratio at or below baseline scores 0
        # rather than negative: this leg measures squeeze risk, not bullishness.
        excess = normalized.short_volume_ratio - SHORT_VOLUME_RATIO_BASELINE
        components.append(_clamp(excess / SHORT_VOLUME_RATIO_SPAN, 0.0, 1.0))
        inputs_used.append("short_volume_ratio")
        diagnostics.append(
            "short_volume_ratio is a daily short-VOLUME flow proxy, not short interest "
            "and not a borrow fee."
        )

    if not components:
        return ShortBorrowMetrics(
            verified=True,
            score=None,
            squeeze_risk_score=None,
            inputs_used=(),
            diagnostics=("Short/borrow snapshot was verified but had no numeric fields.",),
        )

    squeeze_risk_score = sum(components) / len(components)
    return ShortBorrowMetrics(
        verified=True,
        score=_clamp((squeeze_risk_score * 2.0) - 1.0, -1.0, 1.0),
        squeeze_risk_score=squeeze_risk_score,
        inputs_used=tuple(inputs_used),
        diagnostics=tuple(diagnostics),
    )


def standardize_so_score(
    *,
    spot: float,
    quotes: Sequence[OptionQuote | Mapping[str, Any]],
    iv_rank: float | None,
    risk_reversal: RiskReversal25D | None,
    put_call: PutCallMetrics | None,
    gamma_rows: Sequence[GammaByStrike],
    short_borrow: ShortBorrowMetrics | None = None,
) -> tuple[float | None, dict[str, float]]:
    """Combine options sub-metrics into a bounded `S_O` score.

    Positive values indicate options structure leaning bullish or favorably
    asymmetric; negative values indicate bearish pressure. Volatility richness
    and chain liquidity are included as non-directional edge terms, while T8
    still consumes raw IV/range fields for strategy selection.
    """

    normalized_quotes = normalize_option_quotes(quotes)
    sub_scores: dict[str, float] = {}

    if risk_reversal is not None:
        sub_scores["skew"] = _clamp(risk_reversal.rr_25d / 0.10, -1.0, 1.0)

    pc_score = _put_call_score(put_call)
    if pc_score is not None:
        sub_scores["put_call"] = pc_score

    gamma_score = _gamma_direction_score(spot, gamma_rows)
    if gamma_score is not None:
        sub_scores["gamma"] = gamma_score

    liquidity = _liquidity_score(normalized_quotes)
    if liquidity is not None:
        sub_scores["liquidity"] = (liquidity * 2.0) - 1.0

    if iv_rank is not None:
        sub_scores["iv_extreme"] = _clamp(abs(iv_rank - 50.0) / 50.0, 0.0, 1.0)

    if short_borrow is not None and short_borrow.score is not None:
        sub_scores["short_borrow"] = short_borrow.score

    weights = {
        "skew": 0.30,
        "put_call": 0.25,
        "gamma": 0.20,
        "liquidity": 0.10,
        "iv_extreme": 0.10,
        "short_borrow": 0.05,
    }
    available = [(name, sub_scores[name], weights[name]) for name in weights if name in sub_scores]
    if not available:
        return None, {}
    total_weight = sum(weight for _, _, weight in available)
    score = sum(value * (weight / total_weight) for _, value, weight in available)
    return _clamp(score, -1.0, 1.0), sub_scores


def build_options_structure(
    *,
    ticker: str,
    spot: float,
    as_of: date | datetime,
    option_quotes: Any,
    price_bars: Any = (),
    expression_class: ExpressionClass | str | None = None,
    chain_verified: bool = True,
    weekly_target_dte: int = 7,
    monthly_target_dte: int = 30,
    distribution_target_dte: int = 7,
    iv_history: Sequence[float] = (),
    pc_ratio_vol_history: Sequence[float] = (),
    pc_ratio_oi_history: Sequence[float] = (),
    event_multiplier: float = 1.0,
    # Trading days. Left unset, it is converted from the weekly expiry's calendar DTE.
    measured_horizon_days: int | None = None,
    expected_move_divergence_threshold: float = 0.25,
    short_borrow: ShortBorrowSnapshot | Mapping[str, Any] | None = None,
    run_id: int | None = None,
    source: str = "computed",
    venue: str = "*",
    endpoint_or_file: str = "",
    validation_status: str = "computed",
) -> OptionsStructureResult:
    as_of_dt = _to_datetime(as_of)
    spot_value = _positive_float(spot, "spot")
    normalized_quotes = normalize_option_quotes(option_quotes)
    normalized_class = _normalize_expression_class(expression_class)
    diagnostics: list[str] = []

    if not chain_verified or not normalized_quotes:
        reason = "No verified per-strike option chain supplied."
        if normalized_class in OPTIONS_DEPENDENT_CLASSES:
            reason = (
                f"S_O is n/a for class {normalized_class.value}: "
                "a verified per-strike option chain is required."
            )
        rows = _evidence_rows(
            run_id=run_id,
            ticker=ticker,
            as_of=as_of_dt,
            source=source,
            venue=venue,
            endpoint_or_file=endpoint_or_file,
            validation_status=validation_status,
            values={"s_o": "n/a", "chain_verified": chain_verified},
            notes={"s_o": reason},
        )
        return OptionsStructureResult(
            ticker=ticker.strip().upper(),
            as_of=as_of_dt,
            spot=spot_value,
            available=False,
            score=None,
            na_reason=reason,
            diagnostics=(reason,),
            evidence_rows=tuple(rows),
        )

    expected_moves: dict[str, ExpectedMove] = {}
    for label, target_dte in (("weekly", weekly_target_dte), ("monthly", monthly_target_dte)):
        try:
            expected_moves[label] = compute_expected_move(
                normalized_quotes,
                spot=spot_value,
                as_of=as_of_dt,
                target_dte=target_dte,
                divergence_threshold=expected_move_divergence_threshold,
            )
            diagnostics.extend(expected_moves[label].diagnostics)
        except OptionsMathError as exc:
            diagnostics.append(f"{label} expected move unavailable: {exc}")

    distribution_expiry: date | None = None
    try:
        distribution_expiry = select_expiry_by_dte(
            normalized_quotes,
            as_of=as_of_dt,
            target_dte=distribution_target_dte,
        )
    except OptionsMathError as exc:
        diagnostics.append(f"distribution expiry unavailable: {exc}")

    realized: dict[int, RealizedVolatility] = {}
    if price_bars:
        for lookback in (20, 60):
            try:
                realized[lookback] = realized_volatility(price_bars, lookback_days=lookback)
            except OptionsMathError as exc:
                diagnostics.append(f"{lookback}d realized volatility unavailable: {exc}")
    else:
        diagnostics.append("No price history supplied; measured sigma range unavailable.")

    measured_range = None
    if 20 in realized:
        # `measured_horizon_days` is already in trading days; a DTE is not.
        calendar_horizon: int | None = None
        horizon_days = measured_horizon_days
        if horizon_days is None:
            weekly_move = expected_moves.get("weekly")
            calendar_horizon = weekly_move.dte if weekly_move is not None else weekly_target_dte
            horizon_days = trading_days_from_calendar_days(calendar_horizon)
        measured_range = build_measured_sigma_range(
            spot=spot_value,
            realized_vol=realized[20].annualized_vol,
            lookback_days=20,
            horizon_days=horizon_days,
            event_multiplier=event_multiplier,
            calendar_horizon_days=calendar_horizon,
        )

    current_iv = _current_atm_iv(expected_moves)
    computed_iv_rank = iv_rank_from_history(current_iv, iv_history)
    computed_vrp = variance_risk_premium(
        current_iv,
        realized[20].annualized_vol if 20 in realized else None,
    )

    rr_25d = risk_reversal_25d(normalized_quotes, expiry=distribution_expiry) if distribution_expiry else None
    clusters = detect_oi_clusters(normalized_quotes, limit=5)
    pc = put_call_metrics(
        normalized_quotes,
        expiry=distribution_expiry,
        volume_history=pc_ratio_vol_history,
        open_interest_history=pc_ratio_oi_history,
    )
    gamma_rows = gamma_by_strike(normalized_quotes, expiry=distribution_expiry, limit=10)

    distribution = None
    if distribution_expiry is not None:
        try:
            distribution = implied_distribution(
                normalized_quotes,
                spot=spot_value,
                as_of=as_of_dt,
                expiry=distribution_expiry,
            )
            diagnostics.extend(distribution.diagnostics)
        except DistributionError as exc:
            diagnostics.append(f"implied distribution unavailable: {exc}")

    short_metrics = short_borrow_metrics(short_borrow)
    if short_metrics is not None:
        diagnostics.extend(short_metrics.diagnostics)

    score, sub_scores = standardize_so_score(
        spot=spot_value,
        quotes=normalized_quotes,
        iv_rank=computed_iv_rank,
        risk_reversal=rr_25d,
        put_call=pc,
        gamma_rows=gamma_rows,
        short_borrow=short_metrics,
    )

    rows = _evidence_rows(
        run_id=run_id,
        ticker=ticker,
        as_of=as_of_dt,
        source=source,
        venue=venue,
        endpoint_or_file=endpoint_or_file,
        validation_status=validation_status,
        values=_evidence_values(
            spot=spot_value,
            quote_count=len(normalized_quotes),
            chain_verified=chain_verified,
            expected_moves=expected_moves,
            realized=realized,
            measured_range=measured_range,
            iv_rank=computed_iv_rank,
            vrp=computed_vrp,
            rr_25d=rr_25d,
            pc=pc,
            score=score,
        ),
    )

    return OptionsStructureResult(
        ticker=ticker.strip().upper(),
        as_of=as_of_dt,
        spot=spot_value,
        available=True,
        score=score,
        expected_moves=expected_moves,
        realized_volatility=realized,
        measured_range=measured_range,
        iv_rank=computed_iv_rank,
        variance_risk_premium=computed_vrp,
        risk_reversal_25d=rr_25d,
        oi_clusters=clusters,
        put_call=pc,
        gamma_by_strike=gamma_rows,
        implied_distribution=distribution,
        short_borrow=short_metrics,
        sub_scores=sub_scores,
        diagnostics=tuple(diagnostics),
        evidence_rows=tuple(rows),
    )


def normalize_option_quotes(quotes: Any) -> list[OptionQuote]:
    if quotes is None:
        return []
    if isinstance(quotes, OptionQuote):
        return [quotes]
    if hasattr(quotes, "contracts"):
        quotes = getattr(quotes, "contracts")
    if isinstance(quotes, Mapping):
        return [OptionQuote.from_mapping(quotes)]

    normalized: list[OptionQuote] = []
    for quote in quotes:
        if isinstance(quote, OptionQuote):
            normalized.append(quote)
        elif isinstance(quote, Mapping):
            normalized.append(OptionQuote.from_mapping(quote))
        elif hasattr(quote, "contract_symbol") and hasattr(quote, "option_type"):
            normalized.append(_option_quote_from_contract(quote))
        else:
            raise TypeError(f"unsupported option quote type: {type(quote).__name__}")
    return normalized


def normalize_price_bars(bars: Any) -> list[PriceBar]:
    if bars is None:
        return []
    if isinstance(bars, PriceBar):
        return [bars]
    if isinstance(bars, Mapping):
        return [PriceBar.from_mapping(bars)]

    normalized: list[PriceBar] = []
    for bar in bars:
        if isinstance(bar, PriceBar):
            normalized.append(bar)
        elif isinstance(bar, Mapping):
            normalized.append(PriceBar.from_mapping(bar))
        elif hasattr(bar, "date") and hasattr(bar, "close"):
            normalized.append(
                PriceBar(
                    bar_date=getattr(bar, "date"),
                    close=getattr(bar, "adjusted_close", None) or getattr(bar, "close"),
                )
            )
        else:
            bar_date, close = bar
            normalized.append(PriceBar(bar_date=bar_date, close=close))
    return normalized


def _option_quote_from_contract(contract: Any) -> OptionQuote:
    mid = getattr(contract, "mid", None) or getattr(contract, "settlement", None) or getattr(contract, "last_trade_price", None)
    bid = getattr(contract, "bid", None)
    ask = getattr(contract, "ask", None)
    if (bid is None or ask is None) and mid is not None:
        bid = mid
        ask = mid
    raw_option_type = getattr(contract, "option_type")
    return OptionQuote(
        ticker=str(getattr(contract, "underlying", None) or getattr(contract, "ticker", "")),
        expiry=getattr(contract, "expiry"),
        strike=getattr(contract, "strike"),
        option_type=str(getattr(raw_option_type, "value", raw_option_type)),
        bid=bid,
        ask=ask,
        iv=getattr(contract, "implied_volatility", None) or getattr(contract, "iv", None),
        delta=getattr(contract, "delta", None),
        gamma=getattr(contract, "gamma", None),
        open_interest=getattr(contract, "open_interest", None) or 0,
        volume=getattr(contract, "volume", None) or 0,
        as_of=getattr(contract, "last_trade_time", None),
        venue=getattr(contract, "venue", None),
    )


def _quotes_by_strike(quotes: Sequence[OptionQuote], option_type: OptionType) -> dict[float, list[OptionQuote]]:
    grouped: dict[float, list[OptionQuote]] = {}
    for quote in quotes:
        if quote.option_type == option_type:
            grouped.setdefault(quote.strike, []).append(quote)
    return grouped


def _best_quote(quotes: Sequence[OptionQuote]) -> OptionQuote:
    return max(quotes, key=lambda quote: (quote.volume + quote.open_interest, -abs(quote.ask - quote.bid)))


def _nearest_delta_quote(quotes: Sequence[OptionQuote], target_delta: float) -> OptionQuote | None:
    if not quotes:
        return None
    return min(quotes, key=lambda quote: abs((quote.delta or 0.0) - target_delta))


def _nearest_abs_delta_quote(quotes: Sequence[OptionQuote], target_abs_delta: float) -> OptionQuote | None:
    if not quotes:
        return None
    return min(quotes, key=lambda quote: abs(abs(quote.delta or 0.0) - target_abs_delta))


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + erf(value / sqrt(2.0)))


def _trapezoid(values: np.ndarray, x_values: np.ndarray) -> float:
    return float(np.trapezoid(values, x_values))


def _cumulative_trapezoid(values: np.ndarray, x_values: np.ndarray) -> np.ndarray:
    cumulative = np.zeros(len(values), dtype=float)
    for index in range(1, len(values)):
        width = x_values[index] - x_values[index - 1]
        cumulative[index] = cumulative[index - 1] + (0.5 * (values[index] + values[index - 1]) * width)
    return cumulative


def _put_call_score(metrics: PutCallMetrics | None) -> float | None:
    if metrics is None:
        return None

    components: list[float] = []
    for percentile in (metrics.volume_percentile, metrics.open_interest_percentile):
        if percentile is not None:
            components.append(1.0 - (2.0 * (percentile / 100.0)))

    for ratio in (metrics.volume_ratio, metrics.open_interest_ratio):
        if ratio is not None:
            components.append(_clamp(1.0 - ratio, -1.0, 1.0))

    if not components:
        return None
    return _clamp(sum(components) / len(components), -1.0, 1.0)


def _gamma_direction_score(spot: float, rows: Sequence[GammaByStrike]) -> float | None:
    if not rows:
        return None
    total_abs = sum(abs(row.net_dealer_gamma_units) for row in rows)
    if total_abs <= 0.0:
        return None
    dominant = max(rows, key=lambda row: abs(row.net_dealer_gamma_units))
    if dominant.strike == spot:
        return 0.0
    direction = 1.0 if dominant.strike > spot else -1.0
    distance_score = _clamp(abs(dominant.strike - spot) / (spot * 0.05), 0.0, 1.0)
    concentration = abs(dominant.net_dealer_gamma_units) / total_abs
    return _clamp(direction * distance_score * concentration, -1.0, 1.0)


def _liquidity_score(quotes: Sequence[OptionQuote]) -> float | None:
    if not quotes:
        return None
    strikes = {quote.strike for quote in quotes}
    expiries = {quote.expiry for quote in quotes}
    total_oi = sum(quote.open_interest for quote in quotes)
    total_volume = sum(quote.volume for quote in quotes)
    strike_score = _clamp(len(strikes) / 20.0, 0.0, 1.0)
    expiry_score = _clamp(len(expiries) / 4.0, 0.0, 1.0)
    oi_score = _clamp(total_oi / 10000.0, 0.0, 1.0)
    volume_score = _clamp(total_volume / 5000.0, 0.0, 1.0)
    return (strike_score * 0.30) + (expiry_score * 0.20) + (oi_score * 0.30) + (volume_score * 0.20)


def _current_atm_iv(expected_moves: Mapping[str, ExpectedMove]) -> float | None:
    weekly = expected_moves.get("weekly")
    if weekly is not None and weekly.iv_atm is not None:
        return weekly.iv_atm
    monthly = expected_moves.get("monthly")
    if monthly is not None:
        return monthly.iv_atm
    return None


def _normalize_short_borrow(snapshot: ShortBorrowSnapshot | Mapping[str, Any]) -> ShortBorrowSnapshot:
    if isinstance(snapshot, ShortBorrowSnapshot):
        return snapshot
    return ShortBorrowSnapshot(
        verified=bool(snapshot.get("verified", False)),
        short_interest_pct_float=_optional_non_negative_float(snapshot.get("short_interest_pct_float"), "short_interest_pct_float"),
        days_to_cover=_optional_non_negative_float(snapshot.get("days_to_cover"), "days_to_cover"),
        borrow_fee_pct=_optional_non_negative_float(snapshot.get("borrow_fee_pct"), "borrow_fee_pct"),
        utilization_pct=_optional_non_negative_float(snapshot.get("utilization_pct"), "utilization_pct"),
        short_volume_ratio=_optional_non_negative_float(snapshot.get("short_volume_ratio"), "short_volume_ratio"),
        source=snapshot.get("source"),
        as_of=snapshot.get("as_of"),
    )


def _normalize_expression_class(value: ExpressionClass | str | None) -> ExpressionClass | None:
    if value is None:
        return None
    if isinstance(value, ExpressionClass):
        return value
    return ExpressionClass(value)


def _evidence_values(
    *,
    spot: float,
    quote_count: int,
    chain_verified: bool,
    expected_moves: Mapping[str, ExpectedMove],
    realized: Mapping[int, RealizedVolatility],
    measured_range: MeasuredSigmaRange | None,
    iv_rank: float | None,
    vrp: float | None,
    rr_25d: RiskReversal25D | None,
    pc: PutCallMetrics | None,
    score: float | None,
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "spot": spot,
        "option_quote_count": quote_count,
        "chain_verified": chain_verified,
    }
    for label, move in expected_moves.items():
        values[f"{label}_atm_strike"] = move.atm_strike
        values[f"{label}_dte"] = move.dte
        values[f"{label}_expected_move_straddle_pct"] = move.straddle_pct
        values[f"{label}_expected_move_iv_pct"] = move.iv_pct
    for lookback, vol in realized.items():
        values[f"realized_vol_{lookback}d"] = vol.annualized_vol
    if measured_range is not None:
        values["measured_sigma_low"] = measured_range.low
        values["measured_sigma_high"] = measured_range.high
        values["measured_sigma_pct"] = measured_range.adjusted_sigma_pct
    values["iv_rank"] = iv_rank
    values["variance_risk_premium"] = vrp
    values["rr_25d"] = rr_25d.rr_25d if rr_25d is not None else None
    if pc is not None:
        values["pc_ratio_volume"] = pc.volume_ratio
        values["pc_ratio_oi"] = pc.open_interest_ratio
        values["pc_ratio_volume_percentile"] = pc.volume_percentile
        values["pc_ratio_oi_percentile"] = pc.open_interest_percentile
    values["s_o"] = score
    return values


def _evidence_rows(
    *,
    run_id: int | None,
    ticker: str,
    as_of: datetime,
    source: str,
    venue: str,
    endpoint_or_file: str,
    validation_status: str,
    values: Mapping[str, Any],
    notes: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    rows = []
    notes = notes or {}
    for field_name, value in values.items():
        if value is None:
            continue
        rows.append(
            {
                "run_id": run_id,
                "ticker": ticker.strip().upper(),
                "component": "S_O",
                "field_name": field_name,
                "field_value": str(value),
                "source": source,
                "venue": venue,
                "as_of": as_of,
                "endpoint_or_file": endpoint_or_file,
                "validation_status": validation_status,
                "note": notes.get(field_name),
            }
        )
    return rows


def _required(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    raise ValueError(f"missing required field: {'/'.join(keys)}")


def _to_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _to_datetime(value: date | datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=UTC)
    text = str(value)
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = datetime.combine(date.fromisoformat(text[:10]), time.min)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _required_float(value: Any, field_name: str) -> float:
    if value is None or value == "":
        raise ValueError(f"{field_name} is required")
    return float(value)


def _optional_float(value: Any, field_name: str) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _positive_float(value: Any, field_name: str) -> float:
    converted = _required_float(value, field_name)
    if converted <= 0.0:
        raise ValueError(f"{field_name} must be positive")
    return converted


def _non_negative_float(value: Any, field_name: str) -> float:
    converted = _required_float(value, field_name)
    if converted < 0.0:
        raise ValueError(f"{field_name} must be non-negative")
    return converted


#: Black-Scholes returns values around -3e-14 for deep-OTM strikes that are worth zero,
#: so a call price this far below zero is float noise from the pricer rather than a bad
#: input. Anything more negative is still a real error and still raises.
_CALL_PRICE_NOISE_FLOOR: float = -1e-9


def _call_price_float(value: Any) -> float:
    """A call price, tolerating the pricer's own floating-point noise at zero.

    Refusing a `-3.4e-14` price rejected whole legitimate strike windows: a fitted smile
    with every IV positive still produces sub-epsilon negatives on strikes far enough out
    of the money to be worthless. Those are clamped to zero; a genuinely negative price,
    which would mean the smile or the pricer is wrong, still raises.
    """

    converted = _required_float(value, "call_price")
    if converted < _CALL_PRICE_NOISE_FLOOR:
        raise ValueError("call_price must be non-negative")
    return max(converted, 0.0)


def _optional_non_negative_float(value: Any, field_name: str) -> float | None:
    converted = _optional_float(value, field_name)
    if converted is not None and converted < 0.0:
        raise ValueError(f"{field_name} must be non-negative")
    return converted


def _non_negative_int(value: Any, field_name: str) -> int:
    converted = int(value or 0)
    if converted < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return converted


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value
