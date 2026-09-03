from __future__ import annotations

import csv
from datetime import UTC, date, datetime, time, timedelta
from html import unescape
from html.parser import HTMLParser
import io
import re
from typing import Any, Iterable, Mapping, Sequence
import xml.etree.ElementTree as ET

from briefing_app.models.market_data import (
    AnalystSignal,
    CatalystCalendar,
    CatalystEvent,
    DataIssue,
    FilingRecord,
    FundamentalSnapshot,
    InsiderTransaction,
    IssueSeverity,
    MacroCalendar,
    MacroEvent,
    NewsArticle,
    NewsSentimentBatch,
    OptionChain,
    OptionContract,
    OptionFilterConfig,
    OptionType,
    OwnershipChange,
    PoliticalTrade,
    PriceBar,
    PutCallSnapshot,
    Quote,
    RetailMomentumSnapshot,
    ShortInterestSnapshot,
    ValidationStatus,
)
from briefing_app.providers.news_tone import TONE_SOURCE, score_article_tone, tone_label
from briefing_app.provider_validation import validate_payload


class NormalizationError(ValueError):
    pass


_OCC_CONTRACT_RE = re.compile(r"^(.+?)(\d{6})([CP])(\d{8})$")


#: Bodies a CSV endpoint returns when it is throttled, plan-gated, or JS-gated. A CSV
#: reader turns these into zero rows, which downstream reads as "no events".
_NON_CSV_PREFIXES = ("{", "[", "<")

_SEC_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$|^\d{2}-\d{2}-\d{4}$|^\d{8}$")

_SEC_FORM4_TRANSACTION_LABELS: dict[str, str] = {
    "P": "P-Purchase",
    "S": "S-Sale",
    "A": "A-Grant/Award",
    "M": "M-Option Exercise",
    "F": "F-Tax Withholding",
    "G": "G-Gift",
    "C": "C-Conversion",
    "X": "X-Option Exercise",
    "D": "D-Disposition To Issuer",
    "I": "I-Discretionary Transaction",
}

_SEC_FORM4_ROLE_LABELS: tuple[tuple[str, str], ...] = (
    ("isDirector", "Director"),
    ("isOfficer", "Officer"),
    ("isTenPercentOwner", "10% Owner"),
    ("isOther", "Other"),
)

_MONEY_RE = re.compile(r"[\$€£]?\s*([0-9][0-9,]*(?:\.[0-9]+)?)")


def _reject_non_csv_body(text: str, source: str) -> None:
    stripped = (text or "").strip()
    if not stripped:
        raise NormalizationError(f"{source} returned an empty body, not CSV.")
    if stripped.startswith(_NON_CSV_PREFIXES):
        raise NormalizationError(
            f"{source} returned {stripped[:120]!r} instead of CSV; "
            "treat as a failed call, never as an empty calendar."
        )


def _calendar_rows(payload: Any, source: str, provider_id: str) -> list[Any]:
    """Rows of a list-shaped calendar endpoint.

    An empty list is a legitimate (if unhelpful) answer and is graded by the caller.
    A mapping where a list belongs is an error object - the shape FMP returns for a
    plan-gated endpoint - and must never be read as zero events.
    """

    validation = validate_payload(payload, (), provider_id)
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "results", "calendar", "events"):
            nested = payload.get(key)
            if isinstance(nested, list):
                return nested
        raise NormalizationError(
            f"{source} returned a mapping where a list of events was expected: "
            f"{sorted(payload)[:6]}. Treat as a failed call, not an empty calendar."
        )
    raise NormalizationError(f"{source} returned {type(payload).__name__}, not a list.")


def _empty_calendar_issue(source: str) -> DataIssue:
    return DataIssue(
        code="empty_calendar",
        severity=IssueSeverity.WARNING,
        detail=(
            f"{source} returned no events. Absence from a provider calendar is not "
            "evidence that no event is scheduled."
        ),
    )


def _row_limit_issue(source: str) -> DataIssue:
    return DataIssue(
        code="calendar_row_limit_reached",
        severity=IssueSeverity.WARNING,
        detail=f"{source} hit its row limit; the window is only partially covered.",
    )


def _build_catalyst_calendar(
    events: list[CatalystEvent],
    *,
    ticker: str,
    source: str,
    as_of: datetime | None,
    total_rows: int,
    requested_start: date | None = None,
    requested_end: date | None = None,
    row_limit_reached: bool = False,
    endpoint_or_file: str = "",
) -> CatalystCalendar:
    """Wrap events with the completeness verdict for a ticker-filtered calendar."""

    diagnostics: list[DataIssue] = []
    status = ValidationStatus.VERIFIED

    if total_rows == 0:
        status = ValidationStatus.UNAVAILABLE
        diagnostics.append(_empty_calendar_issue(source))
    elif not events:
        # The provider answered, but not about this name. On a market-wide calendar
        # that is exactly what truncation looks like, so it is not a clean "no event".
        status = ValidationStatus.PARTIAL
        diagnostics.append(
            DataIssue(
                code="ticker_absent_from_calendar",
                severity=IssueSeverity.WARNING,
                detail=(
                    f"{source} returned {total_rows} rows, none for {ticker}. A truncated "
                    "market-wide calendar looks identical to a genuinely empty one."
                ),
            )
        )

    if row_limit_reached:
        status = ValidationStatus.PARTIAL
        diagnostics.append(_row_limit_issue(source))

    return CatalystCalendar(
        ticker=ticker,
        source=source,
        as_of=as_of or datetime.now(UTC),
        endpoint_or_file=endpoint_or_file,
        requested_start=requested_start,
        requested_end=requested_end,
        row_limit_reached=row_limit_reached,
        validation_status=status,
        diagnostics=diagnostics,
        events=events,
    )


def option_filters_from_config(config: Any) -> OptionFilterConfig:
    raw = getattr(config, "option_filters", None)
    if raw is None and hasattr(config, "model_extra"):
        raw = config.model_extra.get("option_filters")
    return OptionFilterConfig.model_validate(raw or {})


def normalize_cboe_option_chain(
    ticker: str,
    payload: dict[str, Any],
    *,
    filters: OptionFilterConfig | None = None,
    endpoint_or_file: str = "",
    reference_time: datetime | None = None,
) -> OptionChain:
    validation = validate_payload(payload, ("data.options",), "cboe_delayed_options")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    data = payload.get("data") or {}
    raw_options = data.get("options") or []
    as_of = parse_datetime(payload.get("timestamp") or data.get("last_trade_time"))
    spot = to_float(data.get("current_price") or data.get("close"))
    if spot is None:
        raise NormalizationError("CBOE payload has no current_price or close.")
    venue = "CBOE"

    contracts: list[OptionContract] = []
    diagnostics: list[DataIssue] = []
    for row in raw_options:
        if not isinstance(row, dict):
            diagnostics.append(
                DataIssue(code="malformed_option_row", detail="Option row is not a mapping.")
            )
            continue
        symbol = row.get("option") or row.get("symbol") or row.get("contractID")
        try:
            parsed = parse_occ_contract(str(symbol))
        except ValueError as exc:
            diagnostics.append(
                DataIssue(
                    code="unparseable_contract_symbol",
                    detail=f"{symbol}: {exc}",
                    field_name="option",
                )
            )
            continue

        contracts.append(
            OptionContract(
                underlying=parsed["underlying"],
                contract_symbol=str(symbol),
                expiry=parsed["expiry"],
                strike=parsed["strike"],
                option_type=parsed["option_type"],
                venue=venue,
                source="CBOE delayed options",
                bid=to_float(row.get("bid")),
                ask=to_float(row.get("ask")),
                mid=midpoint(row.get("bid"), row.get("ask")),
                last_trade_price=to_float(row.get("last_trade_price")),
                last_trade_time=parse_datetime(row.get("last_trade_time")),
                volume=to_int(row.get("volume")),
                open_interest=to_int(row.get("open_interest")),
                implied_volatility=to_float(row.get("iv")),
                delta=to_float(row.get("delta")),
                gamma=to_float(row.get("gamma")),
                theta=to_float(row.get("theta")),
                vega=to_float(row.get("vega")),
                rho=to_float(row.get("rho")),
                raw=row,
            )
        )

    chain = OptionChain(
        ticker=ticker.strip().upper(),
        venue=venue,
        as_of=as_of,
        spot=spot,
        source="CBOE delayed options",
        endpoint_or_file=endpoint_or_file,
        contracts=contracts,
        diagnostics=diagnostics,
        validation_status=ValidationStatus.VERIFIED if contracts else ValidationStatus.UNAVAILABLE,
    )
    if filters is None:
        return chain
    return chain.filtered(filters, reference_time=reference_time)


def normalize_alpha_vantage_options_chain(
    ticker: str,
    payload: dict[str, Any],
    *,
    spot: float | None = None,
    filters: OptionFilterConfig | None = None,
    endpoint_or_file: str = "",
    reference_time: datetime | None = None,
) -> OptionChain:
    validation = validate_payload(payload, ("data",), "alpha_vantage")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    clean_ticker = ticker.strip().upper()
    raw_options = _payload_rows(payload, "data", "options")
    as_of = parse_datetime(
        payload.get("timestamp")
        or payload.get("as_of")
        or payload.get("last_updated")
        or _first_row_value(raw_options, "date", "last_trade_date", "last_trade_time")
    )
    spot_value = (
        to_float(spot)
        or to_float(
            _pick(
                payload,
                "underlying_price",
                "underlyingPrice",
                "spot",
                "current_price",
                "price",
            )
        )
    )
    diagnostics: list[DataIssue] = []
    if spot_value is None:
        spot_value = 0.0
        diagnostics.append(
            DataIssue(
                code="missing_underlying_spot",
                detail=(
                    "Alpha Vantage options payload did not include an underlying "
                    "spot price; downstream calculations must supply quote spot."
                ),
            )
        )

    contracts: list[OptionContract] = []
    for row in raw_options:
        if not isinstance(row, dict):
            diagnostics.append(
                DataIssue(code="malformed_option_row", detail="Option row is not a mapping.")
            )
            continue

        symbol = _pick(row, "contractID", "contract_id", "option", "symbol")
        parsed: dict[str, Any] = {}
        if symbol:
            try:
                parsed = parse_occ_contract(str(symbol))
            except ValueError:
                parsed = {}
        if symbol and not parsed and str(symbol).strip().upper() == clean_ticker:
            symbol = None

        expiry = parsed.get("expiry")
        raw_expiry = _pick(row, "expiration", "expiration_date", "expiry", "maturity")
        if expiry is None and raw_expiry:
            expiry = parse_date(raw_expiry)

        strike = parsed.get("strike")
        if strike is None:
            strike = to_float(_pick(row, "strike", "strike_price", "strikePrice"))

        option_type = parsed.get("option_type")
        raw_type = _pick(row, "type", "option_type", "optionType", "putCall")
        if option_type is None and raw_type:
            option_type = OptionType(raw_type)

        if not symbol:
            symbol = _synthetic_contract_symbol(clean_ticker, expiry, option_type, strike)
        if expiry is None or strike is None or option_type is None or not symbol:
            diagnostics.append(
                DataIssue(
                    code="incomplete_option_row",
                    detail="Alpha Vantage option row is missing symbol, expiry, strike, or type.",
                )
            )
            continue

        bid = to_float(_pick(row, "bid", "bid_price", "bidPrice"))
        ask = to_float(_pick(row, "ask", "ask_price", "askPrice"))
        contracts.append(
            OptionContract(
                underlying=clean_ticker,
                contract_symbol=str(symbol).strip().upper(),
                expiry=expiry,
                strike=strike,
                option_type=option_type,
                venue="Alpha Vantage",
                source="Alpha Vantage options",
                bid=bid,
                ask=ask,
                mid=midpoint(bid, ask)
                or to_float(_pick(row, "mark", "mid", "midpoint", "last", "last_price")),
                last_trade_price=to_float(_pick(row, "last", "last_price", "lastTradePrice")),
                last_trade_time=parse_datetime(
                    _pick(row, "last_trade_time", "last_trade_date", "date")
                )
                if _pick(row, "last_trade_time", "last_trade_date", "date")
                else None,
                volume=to_int(_pick(row, "volume", "contract_volume")),
                open_interest=to_int(_pick(row, "open_interest", "openInterest")),
                implied_volatility=to_float(
                    _pick(row, "implied_volatility", "impliedVolatility", "iv")
                ),
                delta=to_float(row.get("delta")),
                gamma=to_float(row.get("gamma")),
                theta=to_float(row.get("theta")),
                vega=to_float(row.get("vega")),
                rho=to_float(row.get("rho")),
                raw=row,
            )
        )

    chain = OptionChain(
        ticker=clean_ticker,
        venue="Alpha Vantage",
        as_of=as_of,
        spot=spot_value,
        source="Alpha Vantage options",
        endpoint_or_file=endpoint_or_file,
        validation_status=ValidationStatus.VERIFIED if contracts else ValidationStatus.UNAVAILABLE,
        contracts=contracts,
        diagnostics=diagnostics,
    )
    if filters is None:
        return chain
    return chain.filtered(filters, reference_time=reference_time)


def normalize_alpha_vantage_put_call_ratio(
    ticker: str,
    payload: dict[str, Any],
) -> list[PutCallSnapshot]:
    """Alpha Vantage put/call ratios.

    Two shapes are served. A dated series arrives under `data`; the realtime and
    historical endpoints instead answer
    `{symbol, date, put_call_ratio_full_chain, put_call_ratio_by_expiration: [...]}`,
    where the whole-chain figure is the reading and the per-expiration rows are detail.
    Neither is validated on a required `data` key, because the second shape has none.
    """

    validation = validate_payload(payload, (), "alpha_vantage")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    clean_ticker = ticker.strip().upper()
    full_chain = _full_chain_put_call_snapshot(clean_ticker, payload)
    if full_chain is not None:
        return [full_chain]

    rows = _payload_rows(payload, "data", "history", "items")
    if not rows:
        raise NormalizationError(
            "Alpha Vantage put/call payload carried no ratio series or whole-chain value."
        )
    snapshots: list[PutCallSnapshot] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        date_value = _pick(row, "date", "as_of", "timestamp")
        ratio = to_float(_pick(row, "put_call_ratio", "putCallRatio", "pcr"))
        volume_ratio = to_float(
            _pick(row, "put_call_volume_ratio", "putCallVolumeRatio", "volume_put_call_ratio")
        )
        oi_ratio = to_float(
            _pick(
                row,
                "put_call_open_interest_ratio",
                "putCallOpenInterestRatio",
                "open_interest_put_call_ratio",
            )
        )
        put_volume = to_int(_pick(row, "put_volume", "putVolume"))
        call_volume = to_int(_pick(row, "call_volume", "callVolume"))
        put_oi = to_int(_pick(row, "put_open_interest", "putOpenInterest"))
        call_oi = to_int(_pick(row, "call_open_interest", "callOpenInterest"))
        if volume_ratio is None and put_volume is not None and call_volume:
            volume_ratio = put_volume / call_volume
        if oi_ratio is None and put_oi is not None and call_oi:
            oi_ratio = put_oi / call_oi
        if ratio is None:
            ratio = volume_ratio or oi_ratio
        if ratio is None and volume_ratio is None and oi_ratio is None:
            continue
        snapshots.append(
            PutCallSnapshot(
                ticker=clean_ticker,
                as_of=parse_date(date_value or payload.get("timestamp") or payload.get("as_of")),
                source="Alpha Vantage put/call",
                put_call_ratio=ratio,
                put_call_volume_ratio=volume_ratio,
                put_call_open_interest_ratio=oi_ratio,
                put_volume=put_volume,
                call_volume=call_volume,
                put_open_interest=put_oi,
                call_open_interest=call_oi,
                raw=row,
            )
        )

    if snapshots:
        return snapshots
    return [_aggregate_put_call_snapshot(clean_ticker, rows, "Alpha Vantage put/call")]


def _full_chain_put_call_snapshot(
    ticker: str, payload: Any
) -> PutCallSnapshot | None:
    """Read the whole-chain put/call figure from the realtime/historical payload shape."""

    if not isinstance(payload, dict):
        return None
    ratio = to_float(
        _pick(payload, "put_call_ratio_full_chain", "putCallRatioFullChain")
    )
    if ratio is None:
        return None
    by_expiration = payload.get("put_call_ratio_by_expiration")
    as_of = _pick(payload, "date", "as_of", "timestamp")
    return PutCallSnapshot(
        ticker=ticker,
        as_of=parse_date(as_of) if as_of else date.today(),
        source="Alpha Vantage put/call",
        put_call_ratio=ratio,
        raw={
            "put_call_ratio_full_chain": ratio,
            "put_call_ratio_by_expiration": by_expiration,
        },
    )


def parse_occ_contract(contract_symbol: str) -> dict[str, Any]:
    match = _OCC_CONTRACT_RE.match(contract_symbol.strip().upper())
    if not match:
        raise ValueError("expected OCC-style symbol with yymmdd, C/P, and strike")

    underlying, yymmdd, option_type, strike_raw = match.groups()
    year = 2000 + int(yymmdd[:2])
    expiry = date(year, int(yymmdd[2:4]), int(yymmdd[4:6]))
    return {
        "underlying": underlying,
        "expiry": expiry,
        "option_type": OptionType(option_type),
        "strike": int(strike_raw) / 1000,
    }


def normalize_alpha_vantage_quote(ticker: str, payload: dict[str, Any]) -> Quote:
    validation = validate_payload(payload, ("Global Quote",), "alpha_vantage")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)
    quote = payload["Global Quote"]
    price = to_float(_pick(quote, "05. price", "price"))
    if price is None:
        raise NormalizationError("Alpha Vantage quote has no price.")
    latest_day = _pick(quote, "07. latest trading day", "latest trading day")
    return Quote(
        ticker=ticker,
        venue="Alpha Vantage",
        as_of=parse_datetime(latest_day),
        price=price,
        source="Alpha Vantage GLOBAL_QUOTE",
        open_price=to_float(_pick(quote, "02. open", "open")),
        high=to_float(_pick(quote, "03. high", "high")),
        low=to_float(_pick(quote, "04. low", "low")),
        previous_close=to_float(_pick(quote, "08. previous close", "previous close")),
        volume=to_int(_pick(quote, "06. volume", "volume")),
        raw=quote,
    )


def normalize_fmp_quote(ticker: str, payload: Any) -> Quote:
    rows = payload if isinstance(payload, list) else [payload]
    if not rows or not isinstance(rows[0], dict):
        raise NormalizationError("FMP quote payload is empty or malformed.")
    row = rows[0]
    price = to_float(row.get("price"))
    if price is None:
        raise NormalizationError("FMP quote has no price.")
    return Quote(
        ticker=ticker,
        venue=str(row.get("exchange") or row.get("exchangeShortName") or "FMP"),
        as_of=parse_datetime(row.get("timestamp") or row.get("date")),
        price=price,
        source="FMP quote",
        open_price=to_float(row.get("open")),
        high=to_float(row.get("dayHigh")),
        low=to_float(row.get("dayLow")),
        previous_close=to_float(row.get("previousClose")),
        volume=to_int(row.get("volume")),
        raw=row,
    )


def normalize_alpha_vantage_daily_adjusted(
    ticker: str, payload: dict[str, Any]
) -> list[PriceBar]:
    return _alpha_vantage_daily_bars(
        ticker, payload, source="Alpha Vantage TIME_SERIES_DAILY_ADJUSTED"
    )


def _alpha_vantage_daily_bars(
    ticker: str, payload: dict[str, Any], *, source: str
) -> list[PriceBar]:
    validation = validate_payload(payload, ("Time Series (Daily)",), "alpha_vantage")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    series = payload["Time Series (Daily)"]
    bars: list[PriceBar] = []
    for day, row in sorted(series.items()):
        close = to_float(_pick(row, "4. close", "close"))
        if close is None:
            continue
        bars.append(
            PriceBar(
                ticker=ticker.strip().upper(),
                date=date.fromisoformat(day),
                source=source,
                open_price=to_float(_pick(row, "1. open", "open")),
                high=to_float(_pick(row, "2. high", "high")),
                low=to_float(_pick(row, "3. low", "low")),
                close=close,
                adjusted_close=to_float(_pick(row, "5. adjusted close", "adjusted close")),
                volume=to_int(_pick(row, "6. volume", "volume")),
                raw=row,
            )
        )
    return bars


def normalize_alpha_vantage_daily(ticker: str, payload: dict[str, Any]) -> list[PriceBar]:
    """Unadjusted `TIME_SERIES_DAILY`. Same shape as the adjusted series, minus column 5."""

    return _alpha_vantage_daily_bars(
        ticker, payload, source="Alpha Vantage TIME_SERIES_DAILY"
    )


def normalize_fmp_historical_price_eod(ticker: str, payload: Any) -> list[PriceBar]:
    """FMP `historical-price-eod/full`, the free-plan daily OHLCV series.

    FMP returns newest-first; bars come back oldest-first so realized-volatility windows
    read the same way as the Alpha Vantage series.
    """

    validation = validate_payload(payload, ("root",), "fmp")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    clean_ticker = ticker.strip().upper()
    bars: list[PriceBar] = []
    for row in _payload_rows(payload, "root", "historical"):
        if not isinstance(row, dict):
            continue
        day = _pick(row, "date", "priceDate")
        close = to_float(_pick(row, "close", "adjClose", "price"))
        if not day or close is None:
            continue
        bars.append(
            PriceBar(
                ticker=clean_ticker,
                date=parse_date(day),
                source="FMP historical-price-eod",
                open_price=to_float(row.get("open")),
                high=to_float(row.get("high")),
                low=to_float(row.get("low")),
                close=close,
                adjusted_close=to_float(_pick(row, "adjClose", "adjustedClose")),
                volume=to_int(row.get("volume")),
                raw=row,
            )
        )
    bars.sort(key=lambda bar: bar.date)
    return bars


def normalize_twelve_data_time_series(ticker: str, payload: Any) -> list[PriceBar]:
    """Twelve Data `/time_series` daily OHLCV, normalized oldest-first."""

    validation = validate_payload(payload, ("values",), "twelve_data")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)
    if not isinstance(payload, dict):
        raise NormalizationError("Twelve Data time_series payload is not a mapping.")

    clean_ticker = ticker.strip().upper()
    bars: list[PriceBar] = []
    for row in payload.get("values") or []:
        if not isinstance(row, dict):
            continue
        day = _pick(row, "datetime", "date")
        close = to_float(row.get("close"))
        if not day or close is None:
            continue
        bars.append(
            PriceBar(
                ticker=clean_ticker,
                date=parse_date(str(day).split()[0]),
                source="Twelve Data time_series",
                open_price=to_float(row.get("open")),
                high=to_float(row.get("high")),
                low=to_float(row.get("low")),
                close=close,
                volume=to_int(row.get("volume")),
                raw=row,
            )
        )
    bars.sort(key=lambda bar: bar.date)
    return bars


def normalize_fmp_grades_consensus(ticker: str, payload: Any) -> list[AnalystSignal]:
    """FMP `grades-consensus`: analyst counts per bucket, as one dated rating signal.

    The endpoint reports a standing consensus rather than dated rating actions, so the
    signal is stamped with `as_of` supplied by the caller's run date via `raw`, and the
    rating is the bucket holding the most analysts.
    """

    validation = validate_payload(payload, ("root",), "fmp")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    clean_ticker = ticker.strip().upper()
    signals: list[AnalystSignal] = []
    for row in _payload_rows(payload, "root"):
        if not isinstance(row, dict):
            continue
        buckets = {
            "strong buy": to_int(row.get("strongBuy")) or 0,
            "buy": to_int(row.get("buy")) or 0,
            "hold": to_int(row.get("hold")) or 0,
            "sell": to_int(row.get("sell")) or 0,
            "strong sell": to_int(row.get("strongSell")) or 0,
        }
        if not any(buckets.values()):
            continue
        rating = _pick(row, "consensus") or max(buckets, key=buckets.__getitem__)
        as_of = _pick(row, "date", "publishedDate")
        signals.append(
            AnalystSignal(
                ticker=clean_ticker,
                as_of=parse_date(as_of) if as_of else date.today(),
                source="FMP grades-consensus",
                firm=None,
                analyst=None,
                rating=str(rating),
                action="consensus",
                period="current",
                raw=row,
            )
        )
    return signals


def normalize_fmp_price_target_consensus(ticker: str, payload: Any) -> list[AnalystSignal]:
    """FMP `price-target-consensus`: the standing consensus target as one signal."""

    validation = validate_payload(payload, ("root",), "fmp")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    clean_ticker = ticker.strip().upper()
    signals: list[AnalystSignal] = []
    for row in _payload_rows(payload, "root"):
        if not isinstance(row, dict):
            continue
        target = to_float(_pick(row, "targetConsensus", "targetMedian"))
        if target is None:
            continue
        as_of = _pick(row, "date", "publishedDate")
        signals.append(
            AnalystSignal(
                ticker=clean_ticker,
                as_of=parse_date(as_of) if as_of else date.today(),
                source="FMP price-target-consensus",
                rating=None,
                action="price_target_consensus",
                price_target=target,
                period="current",
                raw=row,
            )
        )
    return signals


def normalize_finnhub_recommendation_trends(
    ticker: str, payload: Any
) -> list[AnalystSignal]:
    """Finnhub `stock/recommendation`: analyst counts per bucket, one row per month.

    Deliberately the same shape as `normalize_fmp_grades_consensus` — buy/hold/sell
    counts, with the rating taken from the fullest bucket. Finnhub also publishes a
    vendor score elsewhere; mapping to that instead would give the analyst leg a second
    feed whose numbers cannot be compared with the first, which is not redundancy.

    Every dated row is kept rather than only the newest. The rows are monthly, the
    component ages them itself, and consecutive months are what make a rating *change*
    visible — the signal the level alone does not carry.
    """

    validation = validate_payload(payload, ("root",), "finnhub")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    clean_ticker = ticker.strip().upper()
    signals: list[AnalystSignal] = []
    for row in _payload_rows(payload, "root"):
        if not isinstance(row, dict):
            continue
        symbol = str(_pick(row, "symbol") or "").strip().upper()
        if symbol and symbol != clean_ticker:
            continue
        buckets = {
            "strong buy": to_int(row.get("strongBuy")) or 0,
            "buy": to_int(row.get("buy")) or 0,
            "hold": to_int(row.get("hold")) or 0,
            "sell": to_int(row.get("sell")) or 0,
            "strong sell": to_int(row.get("strongSell")) or 0,
        }
        as_of = _pick(row, "period", "date")
        if not as_of or not any(buckets.values()):
            continue
        signals.append(
            AnalystSignal(
                ticker=clean_ticker,
                as_of=parse_date(as_of),
                source="Finnhub recommendation-trends",
                rating=max(buckets, key=buckets.__getitem__),
                action="consensus",
                period="current",
                raw=row,
            )
        )
    signals.sort(key=lambda signal: signal.as_of, reverse=True)
    return signals


def normalize_finnhub_company_news(ticker: str, payload: Any) -> NewsSentimentBatch:
    """Finnhub `company-news`, with tone derived locally.

    The free tier serves articles but not scores — `/news-sentiment` is 403 — so each
    article's tone comes from `news_tone`, and the batch source says `local tone` so
    the report never presents a lexicon read as a vendor's scored feed. An article no
    term matched keeps `sentiment_score=None`, which the component skips rather than
    averaging in as neutral.
    """

    validation = validate_payload(payload, ("root",), "finnhub")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    clean_ticker = ticker.strip().upper()
    articles: list[NewsArticle] = []
    for row in _payload_rows(payload, "root"):
        if not isinstance(row, dict):
            continue
        headline = _pick(row, "headline", "title")
        published_at = _pick(row, "datetime", "published_at")
        if not headline or not published_at:
            continue
        if not _finnhub_row_mentions(row, clean_ticker):
            continue
        summary = str(_pick(row, "summary") or "")
        score = score_article_tone(str(headline), summary)
        articles.append(
            NewsArticle(
                ticker=clean_ticker,
                title=str(headline),
                source=str(_pick(row, "source") or "Finnhub"),
                published_at=parse_datetime(published_at),
                url=_none_or_str(_pick(row, "url", "link")),
                sentiment_score=score,
                sentiment_label=tone_label(score),
                raw=row,
            )
        )
    return NewsSentimentBatch(
        ticker=clean_ticker,
        as_of=parse_datetime(_first_row_value(articles, "published_at") or None),
        source=f"Finnhub company_news ({TONE_SOURCE})",
        articles=articles,
        validation_status=ValidationStatus.VERIFIED if articles else ValidationStatus.PARTIAL,
    )


def _finnhub_row_mentions(row: dict[str, Any], ticker: str) -> bool:
    """Keep a row unless its `related` list names other tickers and not this one.

    `company-news` is already symbol-scoped, so a blank `related` is normal metadata
    rather than evidence the story is about someone else. Only a populated list that
    excludes the ticker is grounds to drop the row.
    """

    related = str(_pick(row, "related") or "").strip().upper()
    if not related:
        return True
    return ticker in {part.strip() for part in related.split(",") if part.strip()}


def normalize_fmp_economic_indicators(
    payload: Any, *, indicator: str, source: str = "FMP economic-indicators"
) -> list[MacroEvent]:
    """FMP `economic-indicators`: one released series, oldest-first.

    The endpoint publishes released levels with no consensus estimate, so each event
    carries `actual` and the preceding release as `previous` and leaves `estimate`
    empty. A surprise cannot be computed from this; a release-over-release change can.
    """

    validation = validate_payload(payload, ("root",), "fmp")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    rows: list[tuple[datetime, float, dict[str, Any]]] = []
    for row in _payload_rows(payload, "root"):
        if not isinstance(row, dict):
            continue
        when = _pick(row, "date", "period")
        value = to_float(row.get("value"))
        if not when or value is None:
            continue
        rows.append((parse_datetime(when), value, row))
    rows.sort(key=lambda item: item[0])

    clean_indicator = str(_pick(rows[0][2], "name") or indicator) if rows else indicator
    events: list[MacroEvent] = []
    previous: float | None = None
    for when, value, row in rows:
        events.append(
            MacroEvent(
                name=clean_indicator,
                event_date=when,
                source=source,
                country=_none_or_str(row.get("country")) or "US",
                actual=str(value),
                previous=None if previous is None else str(previous),
                raw=row,
            )
        )
        previous = value
    return events


def normalize_fmp_treasury_rates(payload: Any) -> dict[str, list[MacroEvent]]:
    """FMP `treasury-rates` into two dated series: the 10-year yield and the 10y-2y curve."""

    validation = validate_payload(payload, ("root",), "fmp")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    rows: list[tuple[datetime, dict[str, Any]]] = []
    for row in _payload_rows(payload, "root"):
        if isinstance(row, dict) and row.get("date"):
            rows.append((parse_datetime(row["date"]), row))
    rows.sort(key=lambda item: item[0])

    series: dict[str, list[MacroEvent]] = {"treasury_10y": [], "yield_curve": []}
    previous: dict[str, float] = {}
    for when, row in rows:
        ten = to_float(row.get("year10"))
        two = to_float(row.get("year2"))
        readings = {"treasury_10y": ten}
        if ten is not None and two is not None:
            readings["yield_curve"] = ten - two
        for name, value in readings.items():
            if value is None:
                continue
            series[name].append(
                MacroEvent(
                    name=name,
                    event_date=when,
                    source="FMP treasury-rates",
                    country="US",
                    actual=str(round(value, 4)),
                    previous=(
                        None if name not in previous else str(round(previous[name], 4))
                    ),
                    raw=row,
                )
            )
            previous[name] = value
    return series


def normalize_alpha_vantage_news_sentiment(
    ticker: str, payload: dict[str, Any]
) -> NewsSentimentBatch:
    validation = validate_payload(payload, ("feed",), "alpha_vantage")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)
    articles: list[NewsArticle] = []
    clean_ticker = ticker.strip().upper()
    for row in payload.get("feed", []):
        if not isinstance(row, dict):
            continue
        ticker_sentiment = _ticker_sentiment(row, clean_ticker)
        articles.append(
            NewsArticle(
                ticker=clean_ticker,
                title=str(row.get("title") or ""),
                source=str(row.get("source") or "Alpha Vantage"),
                published_at=parse_datetime(row.get("time_published")),
                url=row.get("url"),
                relevance_score=to_float(ticker_sentiment.get("relevance_score")),
                sentiment_score=to_float(
                    ticker_sentiment.get("ticker_sentiment_score")
                    or row.get("overall_sentiment_score")
                ),
                sentiment_label=ticker_sentiment.get("ticker_sentiment_label")
                or row.get("overall_sentiment_label"),
                raw=row,
            )
        )
    return NewsSentimentBatch(
        ticker=clean_ticker,
        as_of=parse_datetime(payload.get("time_published") or None),
        source="Alpha Vantage NEWS_SENTIMENT",
        articles=articles,
        validation_status=ValidationStatus.VERIFIED if articles else ValidationStatus.PARTIAL,
    )


def normalize_alpha_vantage_earnings_calendar_csv(
    ticker: str,
    csv_text: str,
    *,
    as_of: datetime | None = None,
    requested_start: date | None = None,
    requested_end: date | None = None,
    endpoint_or_file: str = "",
) -> CatalystCalendar:
    """Alpha Vantage EARNINGS_CALENDAR CSV.

    The endpoint answers with a JSON error body when the key is rate-limited or the
    plan does not cover it, which `csv.DictReader` happily parses into nothing. Guard
    that first: an unreadable calendar is not an empty calendar.
    """

    clean_ticker = ticker.strip().upper()
    source = "Alpha Vantage EARNINGS_CALENDAR"
    _reject_non_csv_body(csv_text, source)

    reader = csv.DictReader(io.StringIO(csv_text))
    events: list[CatalystEvent] = []
    total_rows = 0
    for row in reader:
        total_rows += 1
        symbol = (row.get("symbol") or row.get("ticker") or "").strip().upper()
        if symbol and symbol != clean_ticker:
            continue
        report_date = row.get("reportDate") or row.get("fiscalDateEnding")
        if not report_date:
            continue
        events.append(
            CatalystEvent(
                ticker=clean_ticker,
                name="Earnings",
                event_date=date.fromisoformat(report_date),
                status="confirmed" if row.get("reportDate") else "estimated",
                kind="earnings",
                source=source,
                raw=row,
            )
        )

    return _build_catalyst_calendar(
        events,
        ticker=clean_ticker,
        source=source,
        as_of=as_of,
        total_rows=total_rows,
        requested_start=requested_start,
        requested_end=requested_end,
        endpoint_or_file=endpoint_or_file,
    )


def normalize_alpha_vantage_economic_indicator(
    payload: dict[str, Any],
    *,
    name: str | None = None,
    country: str = "US",
) -> list[MacroEvent]:
    validation = validate_payload(payload, ("data",), "alpha_vantage")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    indicator_name = name or str(payload.get("name") or payload.get("function") or "Economic indicator")
    events: list[MacroEvent] = []
    for row in _payload_rows(payload, "data"):
        if not isinstance(row, dict):
            continue
        event_date = _pick(row, "date", "timestamp")
        value = _pick(row, "value", "actual")
        if not event_date or value in (None, ""):
            continue
        events.append(
            MacroEvent(
                name=indicator_name,
                event_date=parse_datetime(event_date),
                source="Alpha Vantage economic indicator",
                country=country,
                actual=_none_or_str(value),
                raw=row,
            )
        )
    return events


def normalize_alpha_vantage_insider_transactions(
    ticker: str,
    payload: dict[str, Any],
) -> list[InsiderTransaction]:
    validation = validate_payload(payload, ("data",), "alpha_vantage")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    clean_ticker = ticker.strip().upper()
    transactions: list[InsiderTransaction] = []
    for row in _payload_rows(payload, "data"):
        if not isinstance(row, dict):
            continue
        transaction_date = _pick(row, "transaction_date", "transactionDate", "date")
        filing_date = _pick(row, "filing_date", "filingDate")
        if not transaction_date and not filing_date:
            continue
        shares = to_float(_pick(row, "shares", "shares_transacted", "transaction_shares"))
        price = to_float(_pick(row, "share_price", "price", "transaction_price"))
        transactions.append(
            InsiderTransaction(
                ticker=clean_ticker,
                as_of=parse_date(transaction_date or filing_date),
                source="Alpha Vantage INSIDER_TRANSACTIONS",
                insider=_none_or_str(_pick(row, "executive", "name", "insider")),
                title=_none_or_str(_pick(row, "executive_title", "title")),
                transaction_type=_none_or_str(
                    _pick(row, "transaction_type", "transactionType", "security_type")
                ),
                acquisition_or_disposal=_none_or_str(
                    _pick(row, "acquisition_or_disposal", "acquisitionOrDisposition")
                ),
                shares=shares,
                price=price,
                value=_transaction_value(row, shares, price),
                shares_owned=to_float(_pick(row, "shares_owned", "sharesOwned")),
                filing_date=parse_date(filing_date) if filing_date else None,
                accession_number=_none_or_str(_pick(row, "accession_number", "accessionNumber")),
                raw=row,
            )
        )
    return transactions


def normalize_alpha_vantage_institutional_holdings(
    ticker: str,
    payload: dict[str, Any],
) -> list[OwnershipChange]:
    """Alpha Vantage INSTITUTIONAL_HOLDINGS.

    Holder rows sit under `holdings`, not `data`, and use `holder_name`/`shares_held`/
    `shares_changed`/`last_reported`; the root carries the aggregates. Older payloads
    used a `data` list, so both key sets are accepted.
    """

    validation = validate_payload(payload, (), "alpha_vantage")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    clean_ticker = ticker.strip().upper()
    rows = _payload_rows(payload, "holdings", "data")
    changes: list[OwnershipChange] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        institution = _pick(row, "holder_name", "institution", "holder", "owner", "name")
        as_of = _pick(
            row, "last_reported", "date", "report_date", "reportDate", "as_of"
        )
        if not institution or not as_of:
            continue
        changes.append(
            OwnershipChange(
                ticker=clean_ticker,
                institution=str(institution),
                as_of=parse_date(as_of),
                source="Alpha Vantage INSTITUTIONAL_HOLDINGS",
                cohort=_none_or_str(_pick(row, "change_type", "type", "cohort")),
                shares=to_float(
                    _pick(row, "shares_held", "shares", "total_shares", "sharesHeld")
                ),
                shares_delta=to_float(
                    _pick(row, "shares_changed", "change", "shares_delta", "changeInShares")
                ),
                percent_delta=to_float(
                    _pick(
                        row,
                        "shares_changed_percentage",
                        "change_percentage",
                        "percent_delta",
                        "changeInSharesPercentage",
                    )
                ),
                estimated_capital_flow=to_float(
                    _pick(row, "market_value", "marketValue", "estimated_capital_flow")
                ),
                raw=row,
            )
        )
    if not changes and not rows:
        raise NormalizationError(
            "Alpha Vantage institutional holdings payload carried no holder rows."
        )
    return changes


def normalize_fmp_economic_calendar(
    payload: Any,
    *,
    as_of: datetime | None = None,
    requested_start: date | None = None,
    requested_end: date | None = None,
    row_limit_reached: bool = False,
    endpoint_or_file: str = "",
) -> MacroCalendar:
    """FMP economic calendar. A denied or capped response must not read as "no events"."""

    rows = _calendar_rows(payload, "FMP economic_calendar", "fmp")
    events: list[MacroEvent] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("event") or row.get("name")
        event_date = row.get("date")
        if not name or not event_date:
            continue
        events.append(
            MacroEvent(
                name=str(name),
                event_date=parse_datetime(event_date),
                source="FMP economic_calendar",
                country=row.get("country"),
                importance=row.get("impact") or row.get("importance"),
                actual=_none_or_str(row.get("actual")),
                estimate=_none_or_str(row.get("estimate")),
                previous=_none_or_str(row.get("previous")),
                raw=row,
            )
        )

    diagnostics: list[DataIssue] = []
    status = ValidationStatus.VERIFIED
    if not events:
        status = ValidationStatus.UNAVAILABLE
        diagnostics.append(_empty_calendar_issue("FMP economic_calendar"))
    if row_limit_reached:
        status = ValidationStatus.PARTIAL
        diagnostics.append(_row_limit_issue("FMP economic_calendar"))

    return MacroCalendar(
        source="FMP economic_calendar",
        as_of=as_of or datetime.now(UTC),
        endpoint_or_file=endpoint_or_file,
        requested_start=requested_start,
        requested_end=requested_end,
        row_limit_reached=row_limit_reached,
        validation_status=status,
        diagnostics=diagnostics,
        events=events,
    )


def normalize_fmp_stock_news(ticker: str, payload: Any) -> NewsSentimentBatch:
    validation = validate_payload(payload, ("root",), "fmp")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    clean_ticker = ticker.strip().upper()
    articles: list[NewsArticle] = []
    for row in _payload_rows(payload, "root"):
        if not isinstance(row, dict):
            continue
        title = _pick(row, "title", "headline")
        published_at = _pick(row, "publishedDate", "date", "published_at")
        if not title or not published_at:
            continue
        articles.append(
            NewsArticle(
                ticker=clean_ticker,
                title=str(title),
                source=str(_pick(row, "site", "publisher", "source") or "FMP"),
                published_at=parse_datetime(published_at),
                url=_pick(row, "url", "link"),
                sentiment_score=to_float(_pick(row, "sentimentScore", "sentiment_score")),
                sentiment_label=_none_or_str(_pick(row, "sentiment", "sentimentLabel")),
                raw=row,
            )
        )
    return NewsSentimentBatch(
        ticker=clean_ticker,
        as_of=parse_datetime(_first_row_value(articles, "published_at") or None),
        source="FMP stock_news",
        articles=articles,
        validation_status=ValidationStatus.VERIFIED if articles else ValidationStatus.PARTIAL,
    )


def normalize_fmp_congress_trades(
    payload: Any,
    *,
    chamber: str,
) -> list[PoliticalTrade]:
    """FMP `senate-latest` / `house-latest` congressional disclosure rows."""

    validation = validate_payload(payload, ("root",), "fmp")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    clean_chamber = chamber.strip().lower()
    source = f"FMP {clean_chamber}-latest"
    trades: list[PoliticalTrade] = []
    for row in _payload_rows(payload, "root"):
        if not isinstance(row, dict):
            continue
        ticker = _pick(row, "symbol", "ticker")
        transaction_date = _pick(row, "transactionDate", "transaction_date", "date")
        if not ticker or not transaction_date:
            continue

        disclosure_date = _pick(
            row,
            "disclosureDate",
            "disclosure_date",
            "filingDate",
            "filedDate",
            "reportDate",
        )
        amount_range = _none_or_str(_pick(row, "amount", "amountRange", "transactionAmount"))
        amount_min, amount_max = _money_bounds(amount_range)
        first = _none_or_str(_pick(row, "firstName", "first_name"))
        last = _none_or_str(_pick(row, "lastName", "last_name"))
        office = _none_or_str(_pick(row, "office", "representative", "politician"))
        politician = office or " ".join(part for part in (first, last) if part) or None

        trades.append(
            PoliticalTrade(
                ticker=str(ticker),
                chamber=clean_chamber,
                transaction_date=parse_date(transaction_date),
                source=source,
                politician=politician,
                politician_id=_none_or_str(
                    _pick(row, "senateID", "houseID", "bioguideId", "politicianId")
                ),
                transaction_type=_none_or_str(_pick(row, "type", "transactionType")),
                disclosure_date=parse_date(disclosure_date) if disclosure_date else None,
                amount_range=amount_range,
                amount_min=amount_min,
                amount_max=amount_max,
                owner=_none_or_str(_pick(row, "owner", "ownership")),
                asset_type=_none_or_str(_pick(row, "assetType", "asset_type")),
                district=_none_or_str(_pick(row, "district", "stateDistrict")),
                source_url=_none_or_str(_pick(row, "link", "url", "sourceUrl")),
                raw=row,
            )
        )
    return trades


def normalize_apewisdom_retail_momentum(
    payload: Any,
    *,
    as_of: date,
) -> list[RetailMomentumSnapshot]:
    """ApeWisdom all-stocks attention rows, normalized without implying sentiment."""

    validation = validate_payload(payload, (), "apewisdom")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    snapshots: list[RetailMomentumSnapshot] = []
    for row in _payload_rows(payload, "results", "data", "stocks", "root"):
        if not isinstance(row, dict):
            continue
        ticker = _pick(row, "ticker", "symbol")
        mentions = to_int(_pick(row, "mentions", "mentions_total"))
        if not ticker or mentions is None:
            continue
        snapshots.append(
            RetailMomentumSnapshot(
                ticker=str(ticker),
                as_of=as_of,
                source="ApeWisdom all-stocks",
                mentions=mentions,
                mentions_24h_ago=to_int(
                    _pick(row, "mentions_24h_ago", "mentions24hAgo", "mentions_previous")
                ),
                upvotes=to_int(_pick(row, "upvotes", "upvote_count")),
                rank=to_int(_pick(row, "rank")),
                rank_24h_ago=to_int(_pick(row, "rank_24h_ago", "rank24hAgo")),
                raw=row,
            )
        )
    return snapshots


def normalize_fmp_earnings_calendar(
    ticker: str,
    payload: Any,
    *,
    as_of: datetime | None = None,
    requested_start: date | None = None,
    requested_end: date | None = None,
    row_limit_reached: bool = False,
    endpoint_or_file: str = "",
) -> CatalystCalendar:
    """FMP earnings calendar, filtered to one ticker.

    This endpoint is market-wide and observed truncated (4 companies for a 9-day
    window). If it returned rows but none for this ticker, the gap may be the
    provider's, so the calendar comes back partial rather than confidently empty.
    """

    clean_ticker = ticker.strip().upper()
    source = "FMP earning_calendar"
    rows = _calendar_rows(payload, source, "fmp")
    events: list[CatalystEvent] = []
    total_rows = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        total_rows += 1
        symbol = str(_pick(row, "symbol", "ticker") or clean_ticker).strip().upper()
        event_date = _pick(row, "date", "reportDate")
        if symbol != clean_ticker or not event_date:
            continue
        events.append(
            CatalystEvent(
                ticker=clean_ticker,
                name="Earnings",
                event_date=parse_date(event_date),
                status="confirmed" if _pick(row, "time", "eps", "revenue") else "estimated",
                kind="earnings",
                source=source,
                raw=row,
            )
        )

    return _build_catalyst_calendar(
        events,
        ticker=clean_ticker,
        source=source,
        as_of=as_of,
        total_rows=total_rows,
        requested_start=requested_start,
        requested_end=requested_end,
        row_limit_reached=row_limit_reached,
        endpoint_or_file=endpoint_or_file,
    )


def normalize_fmp_insider_trades(ticker: str, payload: Any) -> list[InsiderTransaction]:
    validation = validate_payload(payload, ("root",), "fmp")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    clean_ticker = ticker.strip().upper()
    transactions: list[InsiderTransaction] = []
    for row in _payload_rows(payload, "root"):
        if not isinstance(row, dict):
            continue
        transaction_date = _pick(row, "transactionDate", "transaction_date", "date")
        filing_date = _pick(row, "filingDate", "filing_date")
        if not transaction_date and not filing_date:
            continue
        shares = to_float(
            _pick(row, "securitiesTransacted", "shares", "transactionShares")
        )
        price = to_float(_pick(row, "price", "transactionPrice"))
        transactions.append(
            InsiderTransaction(
                ticker=clean_ticker,
                as_of=parse_date(transaction_date or filing_date),
                source="FMP insider-trading",
                insider=_none_or_str(_pick(row, "reportingName", "name", "insider")),
                title=_none_or_str(_pick(row, "typeOfOwner", "title")),
                transaction_type=_none_or_str(_pick(row, "transactionType", "type")),
                acquisition_or_disposal=_none_or_str(
                    _pick(row, "acquistionOrDisposition", "acquisitionOrDisposition")
                ),
                shares=shares,
                price=price,
                value=_transaction_value(row, shares, price),
                shares_owned=to_float(_pick(row, "securitiesOwned", "sharesOwned")),
                filing_date=parse_date(filing_date) if filing_date else None,
                accession_number=_none_or_str(_pick(row, "accessionNumber", "link")),
                raw=row,
            )
        )
    return transactions


def normalize_fmp_analyst_ratings(ticker: str, payload: Any) -> list[AnalystSignal]:
    validation = validate_payload(payload, ("root",), "fmp")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    clean_ticker = ticker.strip().upper()
    signals: list[AnalystSignal] = []
    for row in _payload_rows(payload, "root"):
        if not isinstance(row, dict):
            continue
        as_of = _pick(row, "date", "publishedDate", "fiscalDateEnding")
        if not as_of:
            continue
        signals.append(
            AnalystSignal(
                ticker=clean_ticker,
                as_of=parse_date(as_of),
                source="FMP analyst",
                firm=_none_or_str(_pick(row, "analystCompany", "firm", "company")),
                analyst=_none_or_str(_pick(row, "analystName", "analyst")),
                rating=_none_or_str(_pick(row, "rating", "ratingRecommendation", "newGrade")),
                previous_rating=_none_or_str(_pick(row, "previousRating", "previousGrade")),
                action=_none_or_str(_pick(row, "action", "gradingCompany")),
                price_target=to_float(
                    _pick(row, "priceTarget", "adjPriceTarget", "targetPrice")
                ),
                previous_price_target=to_float(
                    _pick(row, "previousPriceTarget", "previousTargetPrice")
                ),
                eps_estimate=to_float(
                    _pick(row, "estimatedEpsAvg", "epsAvg", "eps_estimate")
                ),
                revenue_estimate=to_float(
                    _pick(row, "estimatedRevenueAvg", "revenueAvg", "revenue_estimate")
                ),
                period=_none_or_str(_pick(row, "period", "fiscalPeriod")),
                raw=row,
            )
        )
    return signals


def normalize_fmp_income_statement(ticker: str, payload: Any) -> list[FundamentalSnapshot]:
    validation = validate_payload(payload, ("root",), "fmp")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    clean_ticker = ticker.strip().upper()
    snapshots: list[FundamentalSnapshot] = []
    for row in _payload_rows(payload, "root"):
        if not isinstance(row, dict):
            continue
        as_of = _pick(row, "date", "fillingDate", "acceptedDate", "calendarYear")
        if not as_of:
            continue
        snapshots.append(
            FundamentalSnapshot(
                ticker=clean_ticker,
                as_of=parse_date(as_of),
                source="FMP income-statement",
                period=_none_or_str(_pick(row, "period")),
                fiscal_year=to_int(_pick(row, "calendarYear", "fiscalYear")),
                fiscal_quarter=_none_or_str(_pick(row, "period", "fiscalQuarter")),
                currency=_none_or_str(_pick(row, "reportedCurrency", "currency")),
                revenue=to_float(row.get("revenue")),
                gross_profit=to_float(row.get("grossProfit")),
                operating_income=to_float(row.get("operatingIncome")),
                net_income=to_float(row.get("netIncome")),
                eps=to_float(_pick(row, "eps", "epsdiluted")),
                raw=row,
            )
        )
    return snapshots


def normalize_fmp_balance_sheet_statement(
    ticker: str, payload: Any
) -> list[FundamentalSnapshot]:
    validation = validate_payload(payload, ("root",), "fmp")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    clean_ticker = ticker.strip().upper()
    snapshots: list[FundamentalSnapshot] = []
    for row in _payload_rows(payload, "root"):
        if not isinstance(row, dict):
            continue
        as_of = _pick(row, "date", "fillingDate", "acceptedDate", "calendarYear")
        if not as_of:
            continue
        snapshots.append(
            FundamentalSnapshot(
                ticker=clean_ticker,
                as_of=parse_date(as_of),
                source="FMP balance-sheet-statement",
                period=_none_or_str(_pick(row, "period")),
                fiscal_year=to_int(_pick(row, "calendarYear", "fiscalYear")),
                fiscal_quarter=_none_or_str(_pick(row, "period", "fiscalQuarter")),
                currency=_none_or_str(_pick(row, "reportedCurrency", "currency")),
                assets=to_float(_pick(row, "totalAssets", "assets")),
                liabilities=to_float(_pick(row, "totalLiabilities", "liabilities")),
                raw=row,
            )
        )
    return snapshots


def normalize_fmp_cash_flow_statement(
    ticker: str, payload: Any
) -> list[FundamentalSnapshot]:
    validation = validate_payload(payload, ("root",), "fmp")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    clean_ticker = ticker.strip().upper()
    snapshots: list[FundamentalSnapshot] = []
    for row in _payload_rows(payload, "root"):
        if not isinstance(row, dict):
            continue
        as_of = _pick(row, "date", "fillingDate", "acceptedDate", "calendarYear")
        if not as_of:
            continue
        snapshots.append(
            FundamentalSnapshot(
                ticker=clean_ticker,
                as_of=parse_date(as_of),
                source="FMP cash-flow-statement",
                period=_none_or_str(_pick(row, "period")),
                fiscal_year=to_int(_pick(row, "calendarYear", "fiscalYear")),
                fiscal_quarter=_none_or_str(_pick(row, "period", "fiscalQuarter")),
                currency=_none_or_str(_pick(row, "reportedCurrency", "currency")),
                operating_cash_flow=to_float(
                    _pick(row, "operatingCashFlow", "netCashProvidedByOperatingActivities")
                ),
                capital_expenditure=to_float(
                    _pick(row, "capitalExpenditure", "capitalExpenditures")
                ),
                raw=row,
            )
        )
    return snapshots


def normalize_fmp_institutional_ownership(
    ticker: str,
    payload: Any,
) -> list[OwnershipChange]:
    validation = validate_payload(payload, ("root",), "fmp")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    clean_ticker = ticker.strip().upper()
    changes: list[OwnershipChange] = []
    for row in _payload_rows(payload, "root"):
        if not isinstance(row, dict):
            continue
        institution = _pick(row, "holder", "investorName", "institution", "ownerName")
        as_of = _pick(row, "date", "reportDate", "acceptedDate")
        if not institution or not as_of:
            continue
        changes.append(
            OwnershipChange(
                ticker=clean_ticker,
                institution=str(institution),
                as_of=parse_date(as_of),
                source="FMP institutional ownership",
                cohort=_none_or_str(_pick(row, "type", "securityType")),
                shares=to_float(
                    _pick(row, "shares", "sharesNumber", "numberOfShares")
                ),
                shares_delta=to_float(
                    _pick(row, "changeInSharesNumber", "sharesDelta", "change")
                ),
                percent_delta=to_float(
                    _pick(row, "changeInSharesPercentage", "ownershipPercent")
                ),
                estimated_capital_flow=to_float(
                    _pick(row, "marketValue", "value", "estimatedCapitalFlow")
                ),
                raw=row,
            )
        )
    return changes


def normalize_fmp_sec_filings(ticker: str | None, payload: Any) -> list[FilingRecord]:
    validation = validate_payload(payload, ("root",), "fmp")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    clean_ticker = ticker.strip().upper() if ticker else None
    records: list[FilingRecord] = []
    for row in _payload_rows(payload, "root"):
        if not isinstance(row, dict):
            continue
        form = _pick(row, "type", "form", "formType")
        filed_at = _pick(row, "fillingDate", "filingDate", "acceptedDate", "date")
        if not form or not filed_at:
            continue
        records.append(
            FilingRecord(
                ticker=clean_ticker or _none_or_str(_pick(row, "symbol", "ticker")),
                cik=_none_or_str(row.get("cik")),
                form=str(form),
                filed_at=parse_date(filed_at),
                report_date=parse_date(_pick(row, "periodOfReport", "reportDate"))
                if _pick(row, "periodOfReport", "reportDate")
                else None,
                accession_number=_none_or_str(_pick(row, "accessionNumber", "accession")),
                primary_document=_none_or_str(_pick(row, "finalLink", "link")),
                url=_none_or_str(_pick(row, "finalLink", "link")),
                source="FMP sec_filings",
                raw=row,
            )
        )
    return records


def normalize_finra_short_volume(text: str) -> list[ShortInterestSnapshot]:
    """FINRA daily short-sale volume (pipe-delimited).

    A daily-flow proxy, never true short interest. An unreadable body must raise:
    zero short volume is a claim about the tape, not a way to say "the file failed".
    """

    _reject_non_csv_body(text, "FINRA short sale volume")
    if "|" not in text.splitlines()[0]:
        raise NormalizationError(
            "FINRA short sale volume body is not pipe-delimited; treat as a failed call."
        )

    reader = csv.DictReader(io.StringIO(text), delimiter="|")
    rows: list[ShortInterestSnapshot] = []
    for row in reader:
        symbol = row.get("Symbol") or row.get("symbol")
        trade_date = row.get("Date") or row.get("date")
        if not symbol or not trade_date:
            continue
        rows.append(
            ShortInterestSnapshot(
                ticker=symbol.strip().upper(),
                as_of=parse_compact_or_iso_date(trade_date),
                source="FINRA short sale volume",
                venue=row.get("Market") or row.get("market"),
                short_volume=to_int(row.get("ShortVolume") or row.get("short_volume")),
                total_volume=to_int(row.get("TotalVolume") or row.get("total_volume")),
                raw=row,
            )
        )
    return rows


def _median_period_gap_days(periods: Sequence[date]) -> int | None:
    """Typical spacing between observations, used to infer where a period ends.

    Derived from the series itself rather than declared, so the same rule serves monthly,
    quarterly and daily series without being told which is which.
    """

    gaps = sorted(
        (later - earlier).days for earlier, later in zip(periods, periods[1:])
    )
    if not gaps:
        return None
    return gaps[len(gaps) // 2]


def _release_carrying_period(
    period: date, period_end: date, release_dates: Sequence[date]
) -> date | None:
    """The publication that carries a period, or `None` when the calendar cannot say.

    A figure is published *after* the period it measures has finished, so the release
    carrying July is the first one on or after 1 August - not the one that falls inside
    July, which published June. Matching on "first release at or after the period start"
    is off by exactly one release, and would date every monthly reading a month early.

    `None` rather than a guess: an observation the calendar does not reach keeps ageing
    from its period, which is the previous behaviour rather than a fabricated date.
    """

    if period_end <= period:
        return None
    for candidate in release_dates:
        if candidate >= period_end:
            return candidate
    return None


def normalize_fred_series_observations(
    payload: Any,
    *,
    series_id: str,
    source: str = "FRED",
    release_dates: Sequence[date] | None = None,
) -> list[MacroEvent]:
    """FRED `series/observations`, oldest-first.

    FRED writes a missing observation as the literal string `"."` - a real value in the
    series for days a daily series does not publish, such as a market holiday on `DGS10`.
    Those rows are skipped rather than coerced, because a holiday is not a reading of zero.

    Like the FMP feed, this publishes released levels with no consensus estimate, so each
    event carries `actual` and the preceding release as `previous` and leaves `estimate`
    empty: a release-over-release change is computable, a surprise is not.
    """

    validation = validate_payload(payload, ("observations",), "fred")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    rows: list[tuple[datetime, float]] = []
    for row in (payload.get("observations") or []):
        if not isinstance(row, dict):
            continue
        when = _clean_text(row.get("date"))
        raw_value = _clean_text(row.get("value"))
        if not when or raw_value in (None, "."):
            continue
        value = to_float(raw_value)
        if value is None:
            continue
        rows.append((parse_datetime(when), value))
    rows.sort(key=lambda item: item[0])

    ordered_releases = sorted(release_dates or ())
    periods = [when.date() for when, _ in rows]
    gap_days = _median_period_gap_days(periods)
    events: list[MacroEvent] = []
    previous: float | None = None
    for index, (when, value) in enumerate(rows):
        period = when.date()
        # The period ends where the next one begins; for the newest observation there is
        # no next, so the series' own typical spacing stands in.
        if index + 1 < len(periods):
            period_end = periods[index + 1]
        elif gap_days:
            period_end = period + timedelta(days=gap_days)
        else:
            period_end = period
        released = _release_carrying_period(period, period_end, ordered_releases)
        raw: dict[str, Any] = {
            "series_id": series_id,
            "date": when.date().isoformat(),
            "value": value,
        }
        if released is not None:
            raw["released_at"] = released.isoformat()
        events.append(
            MacroEvent(
                name=series_id,
                event_date=when,
                released_at=(
                    datetime.combine(released, time.min, tzinfo=UTC)
                    if released is not None
                    else None
                ),
                source=source,
                country="US",
                actual=str(value),
                previous=None if previous is None else str(previous),
                raw=raw,
            )
        )
        previous = value
    return events


def normalize_fred_release_dates(
    payload: Any,
    *,
    release_name: str | None = None,
    source: str = "FRED release calendar",
) -> list[MacroEvent]:
    """FRED `release/dates`: scheduled publication dates for one release.

    These are calendar entries, not readings - they carry a date and a name and no value,
    which is exactly what a dated catalyst needs.

    An empty list is a legitimate answer and returns no events: a monthly release has no
    date inside most thirty-day windows. A payload with no `release_dates` key at all is a
    failed call - FRED's error body is a mapping of `error_code` and `error_message` - and
    must never read as "nothing is scheduled". Same distinction `_calendar_rows` draws for
    the list-shaped calendars.
    """

    validation = validate_payload(payload, (), "fred")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)
    if not isinstance(payload, Mapping) or not isinstance(
        payload.get("release_dates"), list
    ):
        raise NormalizationError(
            "FRED release/dates returned no release_dates list. Treat as a failed call, "
            "not an empty calendar."
        )

    events: list[MacroEvent] = []
    for row in (payload.get("release_dates") or []):
        if not isinstance(row, dict):
            continue
        when = _clean_text(row.get("date"))
        if not when:
            continue
        # A single-release query returns `{"release_id": 10, "date": "..."}` with no name;
        # only the all-releases query names them. The date is the content of a calendar
        # entry, so a nameless row is kept and labelled from its release id.
        release_id = _clean_text(row.get("release_id"))
        name = (
            _clean_text(row.get("release_name"))
            or release_name
            or (f"FRED release {release_id}" if release_id else None)
        )
        if not name:
            continue
        events.append(
            MacroEvent(
                name=name,
                event_date=parse_datetime(when),
                source=source,
                country="US",
                importance="scheduled",
                raw={k: v for k, v in row.items() if k in ("release_id", "date", "release_name")},
            )
        )
    events.sort(key=lambda event: event.event_date)
    return events


#: Spacing at or below which a release is a routine posting rather than a dated catalyst.
#:
#: Measured, not assumed, and the measurement moved the number. Verified 2026-09-02 with
#: nine releases mapped: H.15, Interest Rate Spreads and ICE BofA Indices publish every
#: business day, and H.10 Foreign Exchange Rates, Spot Prices and NYMEX Natural Gas
#: publish every 7 days. Weekly was first assumed to be catalyst-shaped, on the strength of
#: jobless claims; every weekly release this app actually maps turned out to be a *price
#: posting* instead, and 14 of them in a 30-day window pushed `event_risk` from 0.47 to its
#: 1.0 ceiling while burying CPI and GDP.
#:
#: What separates the two is not cadence but whether publication carries information: a
#: spot price is continuously observable and its posting tells a reader nothing, while CPI
#: is unknown until it prints. Cadence is only a proxy for that, and it is a proxy that
#: cannot see the difference at exactly 7 days - so a genuinely traded weekly statistical
#: release (weekly jobless claims, were it ever mapped) would be excluded here too. Revisit
#: with a named exception list the first time such a series is added; today there are none,
#: and inventing the machinery for zero members would be the worse error.
#:
#: This number decides which factors can ever appear as dated events, and the per-series
#: consequence of it is written down two modules away, in `FRED_MACRO_SERIES`
#: (`providers/fred.py`). Nothing enforces that link - changing this value silently
#: falsifies that comment, which is exactly what happened when it moved from `<` to `<=`.
#: Update both.
CALENDAR_MIN_RELEASE_GAP_DAYS = 7


def build_fred_macro_calendar(
    events: Sequence[MacroEvent],
    *,
    as_of: datetime | None = None,
    requested_start: date | None = None,
    requested_end: date | None = None,
    endpoint_or_file: str = "",
    source: str = "FRED release calendar",
) -> MacroCalendar:
    """Scheduled FRED releases, assembled into a calendar with its completeness verdict.

    Takes the events of every release fetched for the window - the caller normalizes each
    release separately, since `release/dates` answers about one release at a time - and
    grades the result the way the FMP calendar is graded: nothing fetched is
    `unavailable`, never a clean "nothing is scheduled".

    Releases are grouped by name because each carries its own cadence, and one that
    publishes weekly or more often is dropped as routine rather than kept as a catalyst.
    A window where every release was routine is `partial`, not `unavailable`: the provider
    answered, this reader chose not to count the answer.
    """

    by_release: dict[str, list[MacroEvent]] = {}
    for event in events:
        by_release.setdefault(event.name, []).append(event)

    kept: list[MacroEvent] = []
    diagnostics: list[DataIssue] = []
    for name, release_events in by_release.items():
        dates = sorted(event.event_date.date() for event in release_events)
        gap = _median_period_gap_days(dates)
        if gap is not None and gap <= CALENDAR_MIN_RELEASE_GAP_DAYS:
            diagnostics.append(
                DataIssue(
                    code="routine_release_excluded",
                    severity=IssueSeverity.INFO,
                    detail=(
                        f"{name} publishes every {gap} day(s) in the requested window; a "
                        "release on that cadence is a routine posting, not a dated "
                        "catalyst, and was left out of the calendar."
                    ),
                )
            )
            continue
        kept.extend(release_events)

    status = ValidationStatus.VERIFIED
    if not events:
        status = ValidationStatus.UNAVAILABLE
        diagnostics.insert(0, _empty_calendar_issue(source))
    elif not kept:
        status = ValidationStatus.PARTIAL
        diagnostics.insert(
            0,
            DataIssue(
                code="all_releases_routine",
                severity=IssueSeverity.WARNING,
                detail=(
                    f"{source} returned {len(events)} scheduled dates, every one of them "
                    "on a release that publishes weekly or more often. The window holds "
                    "no dated catalyst this reader recognises."
                ),
            ),
        )

    kept.sort(key=lambda event: (event.event_date, event.name))
    return MacroCalendar(
        source=source,
        as_of=as_of or datetime.now(UTC),
        endpoint_or_file=endpoint_or_file,
        requested_start=requested_start,
        requested_end=requested_end,
        validation_status=status,
        diagnostics=diagnostics,
        events=kept,
    )


def normalize_sec_company_submissions(
    ticker: str | None,
    payload: dict[str, Any],
) -> list[FilingRecord]:
    """EDGAR company submissions.

    An empty `filings.recent` legitimately means no recent filings; a payload with no
    `filings` block at all is a malformed response and must not read as "no Form 4s".
    """

    validation = validate_payload(payload, ("filings",), "sec_edgar")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    recent = ((payload.get("filings") or {}).get("recent") or {})
    forms = recent.get("form") or []
    filing_dates = recent.get("filingDate") or []
    report_dates = recent.get("reportDate") or []
    accessions = recent.get("accessionNumber") or []
    primary_documents = recent.get("primaryDocument") or []
    cik = str(payload.get("cik") or "").lstrip("0") or None

    records: list[FilingRecord] = []
    for index, form in enumerate(forms):
        filed_at = _list_get(filing_dates, index)
        if not filed_at:
            continue
        accession = _list_get(accessions, index)
        primary_document = _list_get(primary_documents, index)
        url = None
        if cik and accession and primary_document:
            accession_path = str(accession).replace("-", "")
            url = (
                "https://www.sec.gov/Archives/edgar/data/"
                f"{cik}/{accession_path}/{primary_document}"
            )
        report_date = _list_get(report_dates, index)
        records.append(
            FilingRecord(
                ticker=ticker.strip().upper() if ticker else None,
                cik=cik,
                form=str(form),
                filed_at=date.fromisoformat(filed_at),
                report_date=date.fromisoformat(report_date) if report_date else None,
                accession_number=accession,
                primary_document=primary_document,
                url=url,
                source="SEC EDGAR company submissions",
                raw={"index": index},
            )
        )
    return records


def normalize_sec_company_tickers(payload: Any) -> dict[str, int]:
    validation = validate_payload(payload, ("root",), "sec_edgar")
    if not validation.ok:
        raise NormalizationError("; ".join(validation.notes) or validation.status)

    rows = payload.values() if isinstance(payload, dict) else payload
    mapping: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = _pick(row, "ticker", "symbol")
        cik = _pick(row, "cik_str", "cik", "cikStr")
        if not ticker or cik in (None, ""):
            continue
        mapping[str(ticker).strip().upper()] = int(cik)
    return mapping


def normalize_sec_form4_ownership_document(
    ticker: str | None,
    text: str,
    *,
    filing_date: date | str | None = None,
    accession_number: str | None = None,
    primary_document: str | None = None,
    endpoint_or_file: str = "",
) -> list[InsiderTransaction]:
    """Normalize a SEC Form 4 ownership document into non-derivative transactions.

    The EDGAR primary document must be the source XML. A rendered HTML body is refused
    rather than scraped - the raw XML sits at the same accession path once the XSL prefix
    is stripped, and a half-correct scrape would emit insider numbers that look sourced.
    Empty, malformed, or rowless documents raise so a failed filing fetch cannot
    masquerade as "no insider activity".
    """

    source = "SEC Form 4"
    stripped = _require_sec_document_text(text, source)
    document_root = _parse_sec_xml_document(stripped, ("ownershipDocument",))
    if document_root is None:
        return _normalize_sec_form4_html(
            ticker,
            stripped,
            filing_date=filing_date,
            accession_number=accession_number,
            primary_document=primary_document,
            endpoint_or_file=endpoint_or_file,
        )

    ownership_root = _sec_root_or_descendant(document_root, "ownershipDocument")
    if ownership_root is None:
        raise NormalizationError("SEC Form 4 document did not contain ownershipDocument XML.")

    clean_ticker = _sec_clean_ticker(
        ticker or _sec_text(ownership_root, "issuer", "issuerTradingSymbol")
    )
    if not clean_ticker:
        raise NormalizationError(
            "SEC Form 4 document has no issuer trading symbol and no ticker was passed."
        )

    filed_at = _sec_optional_date(filing_date)
    period = _sec_optional_date(_sec_text(ownership_root, "periodOfReport"))
    owners = _sec_reporting_owners(ownership_root)
    reporting_owner = _sec_primary_reporting_owner(owners)
    footnotes = _sec_footnotes(ownership_root)
    metadata = _sec_document_metadata(
        accession_number=accession_number,
        primary_document=primary_document,
        endpoint_or_file=endpoint_or_file,
    )

    transactions: list[InsiderTransaction] = []
    for row in _sec_descendants(ownership_root, "nonDerivativeTransaction"):
        transaction_date = _sec_text(row, "transactionDate", "value") or _sec_text(
            row, "transactionDate"
        )
        as_of = _sec_optional_date(transaction_date) or period or filed_at
        if as_of is None:
            continue

        transaction_code = _sec_clean_code(
            _sec_text(row, "transactionCoding", "transactionCode")
        )
        acquisition_or_disposal = _sec_clean_code(
            _sec_text(
                row,
                "transactionAmounts",
                "transactionAcquiredDisposedCode",
                "value",
            )
            or _sec_text(row, "transactionAcquiredDisposedCode", "value")
        )
        shares = _sec_number_from_text(
            _sec_text(row, "transactionAmounts", "transactionShares", "value")
            or _sec_text(row, "transactionShares", "value")
        )
        price = _sec_number_from_text(
            _sec_text(row, "transactionAmounts", "transactionPricePerShare", "value")
            or _sec_text(row, "transactionPricePerShare", "value")
        )
        shares_owned = _sec_number_from_text(
            _sec_text(
                row,
                "postTransactionAmounts",
                "sharesOwnedFollowingTransaction",
                "value",
            )
            or _sec_text(row, "sharesOwnedFollowingTransaction", "value")
        )
        security_title = _sec_text(row, "securityTitle", "value") or _sec_text(
            row, "securityTitle"
        )
        direct_or_indirect = _sec_text(
            row, "ownershipNature", "directOrIndirectOwnership", "value"
        )
        ownership_nature = _sec_text(row, "ownershipNature", "natureOfOwnership", "value")
        linked_footnotes = _sec_linked_footnotes(row, footnotes)

        raw: dict[str, Any] = {
            "issuerTradingSymbol": clean_ticker,
            "securityTitle": security_title,
            "transactionCode": transaction_code,
            "acquisitionOrDisposalCode": acquisition_or_disposal,
            "directOrIndirectOwnership": direct_or_indirect,
            "natureOfOwnership": ownership_nature,
            "reportingOwner": reporting_owner,
            "reportingOwners": owners,
            **metadata,
        }
        if linked_footnotes:
            raw["footnote"] = " ".join(linked_footnotes)

        transactions.append(
            InsiderTransaction(
                ticker=clean_ticker,
                as_of=as_of,
                source=source,
                insider=_none_or_str(reporting_owner.get("name")),
                title=_none_or_str(reporting_owner.get("title")),
                transaction_type=_sec_form4_transaction_type(transaction_code),
                acquisition_or_disposal=acquisition_or_disposal,
                shares=shares,
                price=price,
                value=_transaction_value(raw, shares, price),
                shares_owned=shares_owned,
                filing_date=filed_at,
                accession_number=accession_number,
                raw=raw,
            )
        )

    if not transactions:
        raise NormalizationError(
            "SEC Form 4 document carried no non-derivative transaction rows."
        )
    return transactions


#: Form 4 Table I transaction codes. Only `P` and `S` are open-market trades; the insider
#: component filters on the code itself, so this map exists to label rather than to decide.
_SEC_FORM4_TRANSACTION_TYPES: dict[str, str] = {
    "P": "open-market purchase",
    "S": "open-market sale",
    "A": "grant or award",
    "C": "conversion of derivative",
    "D": "disposition to issuer",
    "E": "expiration of short derivative",
    "F": "tax withholding",
    "G": "gift",
    "H": "expiration of long derivative",
    "I": "discretionary transaction",
    "J": "other acquisition or disposition",
    "K": "equity swap",
    "L": "small acquisition",
    "M": "option exercise",
    "O": "out-of-the-money option exercise",
    "S/A": "amended open-market sale",
    "U": "tender of shares",
    "V": "voluntary early report",
    "W": "will or inheritance",
    "X": "in-the-money option exercise",
    "Z": "voting trust deposit",
}

#: Key under which a document-level note is stored so every row inherits it. Form 4 carries
#: its Rule 10b5-1 indicator as a document-level element, not a per-row footnote, and the
#: insider component only ever inspects per-row text.
_SEC_DOCUMENT_FOOTNOTE_KEY = "__document__"


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _sec_tag(element: ET.Element) -> str:
    """Local tag name, with any XML namespace stripped.

    13F information tables are namespaced and Form 4 documents are not, so every lookup
    goes through this rather than matching qualified names.
    """

    tag = element.tag
    if isinstance(tag, str) and tag.startswith("{"):
        return tag.rpartition("}")[2]
    return tag if isinstance(tag, str) else ""


def _require_sec_document_text(text: Any, source: str) -> str:
    """Reject an empty body outright.

    A blank document must raise rather than normalize to zero rows: "the fetch failed" and
    "this insider did nothing" are different claims and only one of them is evidence.
    """

    stripped = "" if text is None else str(text).strip()
    if not stripped:
        raise NormalizationError(f"{source} document body was empty; treat as a failed call.")
    return stripped


def _parse_sec_xml_document(
    text: str, root_names: tuple[str, ...]
) -> ET.Element | None:
    """Parse an EDGAR document as XML, or return `None` so a caller can fall back.

    Returns `None` only when the body is not the XML shape asked for - a malformed body
    that claims to be one of `root_names` raises instead.
    """

    start = text.find("<?xml")
    if start == -1:
        for name in root_names:
            start = text.find(f"<{name}")
            if start != -1:
                break
    if start == -1:
        return None
    try:
        root = ET.fromstring(text[start:])
    except ET.ParseError:
        return None
    wanted = {name.lower() for name in root_names}
    if _sec_tag(root).lower() in wanted:
        return root
    for element in root.iter():
        if _sec_tag(element).lower() in wanted:
            return root
    return None


def _sec_root_or_descendant(root: ET.Element, name: str) -> ET.Element | None:
    if _sec_tag(root).lower() == name.lower():
        return root
    return next(
        (element for element in root.iter() if _sec_tag(element).lower() == name.lower()),
        None,
    )


def _sec_descendants(root: ET.Element, name: str) -> list[ET.Element]:
    return [element for element in root.iter() if _sec_tag(element).lower() == name.lower()]


def _sec_child(element: ET.Element, name: str) -> ET.Element | None:
    return next(
        (child for child in element if _sec_tag(child).lower() == name.lower()), None
    )


def _sec_text(element: ET.Element | None, *path: str) -> str | None:
    """Text at a nested path of local tag names, or `None` if any step is missing."""

    cursor = element
    for name in path:
        if cursor is None:
            return None
        cursor = _sec_child(cursor, name)
    if cursor is None:
        return None
    return _clean_text(cursor.text)


def _sec_clean_ticker(value: Any) -> str:
    text = _clean_text(value)
    return text.upper() if text else ""


def _sec_clean_code(value: Any) -> str | None:
    text = _clean_text(value)
    return text.upper() if text else None


def _sec_optional_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _clean_text(value)
    if not text:
        return None
    try:
        return parse_compact_or_iso_date(text)
    except (ValueError, NormalizationError):
        return None


def _sec_number_from_text(value: Any) -> float | None:
    text = _clean_text(value)
    if not text:
        return None
    return to_float(text.replace(",", "").replace("$", ""))


def _sec_form4_transaction_type(code: str | None) -> str | None:
    if not code:
        return None
    return _SEC_FORM4_TRANSACTION_TYPES.get(code.upper(), code.upper())


def _sec_document_metadata(
    *,
    accession_number: str | None,
    primary_document: str | None,
    endpoint_or_file: str = "",
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if accession_number:
        metadata["accessionNumber"] = accession_number
    if primary_document:
        metadata["primaryDocument"] = primary_document
    if endpoint_or_file:
        metadata["endpointOrFile"] = endpoint_or_file
    return metadata


def _sec_reporting_owners(root: ET.Element) -> list[dict[str, Any]]:
    owners: list[dict[str, Any]] = []
    for owner in _sec_descendants(root, "reportingOwner"):
        relationship = _sec_child(owner, "reportingOwnerRelationship")
        owners.append(
            {
                "cik": _sec_text(owner, "reportingOwnerId", "rptOwnerCik"),
                "name": _sec_text(owner, "reportingOwnerId", "rptOwnerName"),
                # `_sec_text` already tolerates a `None` element, and an ElementTree
                # element with no children is falsy - so these must not be guarded by
                # truthiness, or a childless relationship block would drop the title.
                "title": _sec_text(relationship, "officerTitle"),
                "isDirector": _sec_text(relationship, "isDirector"),
                "isOfficer": _sec_text(relationship, "isOfficer"),
                "isTenPercentOwner": _sec_text(relationship, "isTenPercentOwner"),
            }
        )
    return owners


def _sec_primary_reporting_owner(owners: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    for owner in owners:
        if owner.get("name"):
            return dict(owner)
    return dict(owners[0]) if owners else {}


def _sec_footnotes(root: ET.Element) -> dict[str, str]:
    """Footnote id to text, plus a document-level note for a Rule 10b5-1 filing.

    The 10b5-1 indicator is a document-level element, but the insider component only reads
    per-row text, so it is carried under `_SEC_DOCUMENT_FOOTNOTE_KEY` and attached to every
    row by `_sec_linked_footnotes`. Without that, planned-sale filings would be scored as
    discretionary open-market sales.
    """

    footnotes: dict[str, str] = {}
    for note in _sec_descendants(root, "footnote"):
        identifier = _clean_text(note.get("id"))
        text = _clean_text("".join(note.itertext()))
        if identifier and text:
            footnotes[identifier] = text
    flag = (_sec_text(root, "aff10b5One") or "").strip().lower()
    if flag in {"true", "1", "yes"}:
        footnotes[_SEC_DOCUMENT_FOOTNOTE_KEY] = (
            "Filed with the Rule 10b5-1 plan indicator set."
        )
    return footnotes


def _sec_linked_footnotes(
    row: ET.Element, footnotes: Mapping[str, str]
) -> list[str]:
    linked: list[str] = []
    document_note = footnotes.get(_SEC_DOCUMENT_FOOTNOTE_KEY)
    if document_note:
        linked.append(document_note)
    for reference in _sec_descendants(row, "footnoteId"):
        identifier = _clean_text(reference.get("id"))
        text = footnotes.get(identifier or "")
        if text and text not in linked:
            linked.append(text)
    return linked


def _normalize_sec_form4_html(
    ticker: str | None,
    text: str,
    *,
    filing_date: date | str | None = None,
    accession_number: str | None = None,
    primary_document: str | None = None,
    endpoint_or_file: str = "",
) -> list[InsiderTransaction]:
    """Refuse a rendered Form 4 rather than scrape it.

    EDGAR serves every Form 4 as both XML and an XSL-rendered HTML table, and the raw XML
    is always available at the same accession path - `_edgar_raw_document` in the pipeline
    strips the `xslF345X06/` prefix to reach it. A half-correct scrape of the rendering
    would produce insider numbers that look sourced, so this refuses instead and names the
    fix.
    """

    raise NormalizationError(
        "SEC Form 4 body was not XML. EDGAR serves the source XML at the same accession "
        "path with the XSL rendering prefix removed; fetch that instead of the rendered "
        f"HTML (accession {accession_number or 'unknown'})."
    )


def _sec_13f_manager_name(root: ET.Element) -> str | None:
    return _sec_text(root, "coverPage", "filingManager", "name") or _sec_text(
        root, "filingManager", "name"
    )


def _sec_13f_period(root: ET.Element) -> date | None:
    return _sec_optional_date(
        _sec_text(root, "coverPage", "periodOfReport") or _sec_text(root, "periodOfReport")
    )


def normalize_sec_13f_information_table_snapshot(
    text: str,
    *,
    institution: str | None = None,
    period_of_report: date | str | None = None,
    accession_number: str | None = None,
    filing_date: date | str | None = None,
    primary_document: str | None = None,
    endpoint_or_file: str = "",
    ticker_by_cusip: Mapping[str, str] | None = None,
) -> list[OwnershipChange]:
    """Normalize SEC 13F information-table rows as position snapshots.

    Official EDGAR information tables are holdings snapshots. They do not carry
    issuer-level deltas, and standalone table documents usually do not carry the filing
    manager or report period either. Pass that manager/period context from the filing
    record or cover page; this normalizer leaves `shares_delta` and `percent_delta` as
    `None` rather than inventing changes from a single filing.
    """

    source = "SEC Form 13F information table"
    stripped = _require_sec_document_text(text, source)
    document_root = _parse_sec_xml_document(stripped, ("informationTable", "infoTable"))

    manager = _clean_text(institution)
    period = _sec_optional_date(period_of_report)
    if document_root is not None:
        manager = manager or _sec_13f_manager_name(document_root)
        period = period or _sec_13f_period(document_root)

    if not manager:
        raise NormalizationError(
            "SEC 13F information tables do not reliably carry manager context; "
            "pass institution metadata from the filing record or cover page."
        )
    if period is None:
        raise NormalizationError(
            "SEC 13F information tables do not reliably carry the report period; "
            "pass period_of_report from the filing record or cover page."
        )

    metadata = _sec_document_metadata(
        accession_number=accession_number,
        primary_document=primary_document,
        endpoint_or_file=endpoint_or_file,
    )
    filed_at = _sec_optional_date(filing_date)

    if document_root is None:
        return _normalize_sec_13f_information_table_html(
            stripped,
            institution=manager,
            period=period,
            filing_date=filed_at,
            metadata=metadata,
            ticker_by_cusip=ticker_by_cusip,
        )

    rows = _sec_descendants(document_root, "infoTable")
    if _sec_tag_name(document_root) == "infoTable":
        rows = [document_root]

    changes: list[OwnershipChange] = []
    for row in rows:
        issuer = _sec_text(row, "nameOfIssuer")
        title_class = _sec_text(row, "titleOfClass")
        cusip = _sec_text(row, "cusip")
        value_thousands = _sec_number_from_text(_sec_text(row, "value"))
        shares = _sec_number_from_text(
            _sec_text(row, "shrsOrPrnAmt", "sshPrnamt")
            or _sec_text(row, "sshPrnamt")
            or _sec_text(row, "shares")
        )
        shares_type = _sec_text(row, "shrsOrPrnAmt", "sshPrnamtType") or _sec_text(
            row, "sshPrnamtType"
        )

        if not issuer and shares is None and value_thousands is None:
            continue

        raw: dict[str, Any] = {
            "nameOfIssuer": issuer,
            "titleOfClass": title_class,
            "cusip": cusip,
            "valueThousands": value_thousands,
            "sshPrnamt": shares,
            "sshPrnamtType": shares_type,
            "investmentDiscretion": _sec_text(row, "investmentDiscretion"),
            "snapshotOnly": True,
            "deltaLimitation": (
                "EDGAR 13F information tables are single-filing snapshots; "
                "issuer-level deltas require a prior filing for the same manager."
            ),
            **metadata,
        }
        if filed_at is not None:
            raw["filingDate"] = filed_at.isoformat()

        changes.append(
            OwnershipChange(
                ticker=_sec_lookup_ticker_by_cusip(ticker_by_cusip, cusip),
                institution=manager,
                as_of=period,
                source=source,
                cohort=None,
                shares=shares,
                shares_delta=None,
                percent_delta=None,
                estimated_capital_flow=(
                    value_thousands * 1000 if value_thousands is not None else None
                ),
                raw=raw,
            )
        )

    if not changes:
        raise NormalizationError("SEC 13F information table carried no holdings rows.")
    return changes


def _ticker_sentiment(row: dict[str, Any], ticker: str) -> dict[str, Any]:
    for item in row.get("ticker_sentiment", []) or []:
        if isinstance(item, dict) and str(item.get("ticker", "")).upper() == ticker:
            return item
    return {}


def parse_datetime(value: Any) -> datetime:
    if value in (None, ""):
        return datetime.now(UTC)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, UTC)

    text = str(value).strip()
    if re.fullmatch(r"\d{8}T\d{6}", text):
        return datetime.strptime(text, "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_date(value: Any) -> date:
    """A provider's date field as a `date`.

    An absent value (`None` or empty) still resolves to today: "this row carried no date"
    is a shape every caller already guards with `if not as_of: continue`, and changing it
    would alter behaviour far beyond the failure this guard exists for.

    A value that is *present but unparseable* is different, and it raises
    `NormalizationError` rather than the bare `ValueError` `datetime.fromisoformat` would.
    Every normalizer is called inside `except NormalizationError`, so an unrecognised date
    now degrades that one leg into a recorded issue instead of escaping the call site and
    failing the whole ticker.

    The case that forced this: Alpha Vantage's `HISTORICAL_PUT_CALL_RATIO` answers with the
    sentinel `"date": "latest"` instead of a calendar date. `"N/A"`, `"-"` and `"0000-00-00"`
    fail the same way and are just as common. Note that the existing per-site guards do not
    help here - they test for a *missing* date, and every one of these is a truthy string.

    `NormalizationError` subclasses `ValueError`, so any caller already catching `ValueError`
    is unaffected.
    """

    if value in (None, ""):
        return datetime.now(UTC).date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    try:
        if re.fullmatch(r"\d{4}", text):
            return date(int(text), 12, 31)
        if re.fullmatch(r"\d{8}", text):
            return parse_compact_or_iso_date(text)
        return parse_datetime(text).date()
    except NormalizationError:
        # Already the catchable kind; re-wrapping would double the message.
        raise
    except ValueError as exc:
        raise NormalizationError(f"unparseable date {text!r}: {exc}") from exc


def parse_compact_or_iso_date(value: Any) -> date:
    text = str(value).strip()
    if re.fullmatch(r"\d{8}", text):
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    return date.fromisoformat(text)


def midpoint(bid: Any, ask: Any) -> float | None:
    bid_float = to_float(bid)
    ask_float = to_float(ask)
    if bid_float is None or ask_float is None or ask_float < bid_float:
        return None
    return (bid_float + ask_float) / 2


def to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value: Any) -> int | None:
    number = to_float(value)
    if number is None:
        return None
    return int(number)


def _money_bounds(value: str | None) -> tuple[float | None, float | None]:
    if not value:
        return None, None
    numbers = [float(match.group(1).replace(",", "")) for match in _MONEY_RE.finditer(value)]
    if not numbers:
        return None, None
    if len(numbers) == 1:
        low = numbers[0]
        return low, None if "over" in value.lower() else low
    return min(numbers[:2]), max(numbers[:2])


def _pick(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            return row[key]
    return None


def _none_or_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _list_get(values: Iterable[Any], index: int) -> Any:
    if not isinstance(values, list) or index >= len(values):
        return None
    return values[index]


def _payload_rows(payload: Any, *keys: str) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []

    for key in keys:
        if key == "root":
            continue
        value = payload.get(key)
        rows = _rows_from_value(value)
        if rows:
            return rows

    for fallback_key in ("data", "feed", "results", "items", "history"):
        rows = _rows_from_value(payload.get(fallback_key))
        if rows:
            return rows

    if "root" in keys:
        return [payload]
    return []


def _rows_from_value(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for nested_key in ("options", "items", "rows", "history", "data"):
            nested = value.get(nested_key)
            if isinstance(nested, list):
                return nested
        return [value]
    return []


def _first_row_value(rows: Iterable[Any], *keys: str) -> Any:
    for row in rows:
        if isinstance(row, dict):
            value = _pick(row, *keys)
        else:
            value = next((getattr(row, key) for key in keys if hasattr(row, key)), None)
        if value not in (None, ""):
            return value
    return None


def _synthetic_contract_symbol(
    ticker: str,
    expiry: date | None,
    option_type: OptionType | None,
    strike: float | None,
) -> str | None:
    if expiry is None or option_type is None or strike is None:
        return None
    strike_component = f"{int(round(strike * 1000)):08d}"
    return f"{ticker}{expiry:%y%m%d}{option_type.value}{strike_component}"


def _row_option_type(row: dict[str, Any]) -> OptionType | None:
    raw_type = _pick(row, "type", "option_type", "optionType", "putCall")
    if raw_type:
        try:
            return OptionType(raw_type)
        except ValueError:
            return None
    symbol = _pick(row, "contractID", "contract_id", "option", "symbol")
    if symbol:
        try:
            return parse_occ_contract(str(symbol))["option_type"]
        except ValueError:
            return None
    return None


def _aggregate_put_call_snapshot(
    ticker: str,
    rows: list[Any],
    source: str,
) -> PutCallSnapshot:
    put_volume = 0
    call_volume = 0
    put_open_interest = 0
    call_open_interest = 0
    saw_option_row = False

    for row in rows:
        if not isinstance(row, dict):
            continue
        option_type = _row_option_type(row)
        if option_type is None:
            continue
        saw_option_row = True
        volume = to_int(_pick(row, "volume", "contract_volume")) or 0
        open_interest = to_int(_pick(row, "open_interest", "openInterest")) or 0
        if option_type is OptionType.PUT:
            put_volume += volume
            put_open_interest += open_interest
        else:
            call_volume += volume
            call_open_interest += open_interest

    if not saw_option_row:
        raise NormalizationError("No option rows available to derive put/call ratio.")

    volume_ratio = put_volume / call_volume if call_volume else None
    oi_ratio = put_open_interest / call_open_interest if call_open_interest else None
    return PutCallSnapshot(
        ticker=ticker,
        as_of=parse_date(
            _first_row_value(rows, "date", "last_trade_date", "last_trade_time")
        ),
        source=source,
        put_call_ratio=volume_ratio or oi_ratio,
        put_call_volume_ratio=volume_ratio,
        put_call_open_interest_ratio=oi_ratio,
        put_volume=put_volume,
        call_volume=call_volume,
        put_open_interest=put_open_interest,
        call_open_interest=call_open_interest,
        raw={"derived_from_rows": len(rows)},
    )


def _transaction_value(row: dict[str, Any], shares: float | None, price: float | None) -> float | None:
    explicit = to_float(_pick(row, "value", "transactionValue", "transaction_value"))
    if explicit is not None:
        return explicit
    if shares is None or price is None:
        return None
    return shares * price
