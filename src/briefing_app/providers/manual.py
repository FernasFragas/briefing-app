from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from briefing_app.models.market_data import (
    DataIssue,
    InsiderTransaction,
    IssueSeverity,
    OptionChain,
    OptionContract,
    OptionFilterConfig,
    OptionType,
    OwnershipChange,
    ShortInterestSnapshot,
    ValidationStatus,
)
from briefing_app.providers.normalizers import (
    parse_compact_or_iso_date,
    parse_date,
    parse_datetime,
    to_float,
    to_int,
)


def load_eurex_manual_options_capture(
    path: str | Path,
    *,
    ticker: str,
    spot: float,
    filters: OptionFilterConfig | None = None,
    reference_time: datetime | None = None,
) -> OptionChain:
    """Load a hand-captured Eurex chain (Stage 3A Track B).

    Pasted data is user-sourced, not primary-verified, so the chain is marked PARTIAL:
    it caps the name at Tier B downstream. Never return VERIFIED from this path.
    """

    capture_path = Path(path)
    rows = _read_csv(capture_path)
    contracts: list[OptionContract] = []
    diagnostics: list[DataIssue] = [
        DataIssue(
            code="manual_options_capture",
            severity=IssueSeverity.WARNING,
            detail=(
                "Chain came from a manual capture, not a primary feed. "
                "Reconcile the summed open interest against Eurex product-level "
                "market statistics; the name is capped at Tier B."
            ),
        )
    ]
    as_of: datetime | None = None
    venue = "EUREX"

    for row in rows:
        venue = row.get("venue") or venue
        as_of = parse_datetime(row.get("as_of")) if row.get("as_of") else as_of
        expiry = parse_compact_or_iso_date(row["expiry"])
        option_type = OptionType(row["type"])
        strike = to_float(row.get("strike"))
        if strike is None:
            continue
        contract_symbol = (
            row.get("contract_symbol")
            or f"{ticker.upper()}-{expiry.isoformat()}-{option_type.value}-{strike:g}"
        )
        contracts.append(
            OptionContract(
                underlying=ticker.strip().upper(),
                contract_symbol=contract_symbol,
                expiry=expiry,
                strike=strike,
                option_type=option_type,
                venue=venue,
                source="Eurex manual options capture",
                bid=to_float(row.get("bid")),
                ask=to_float(row.get("ask")),
                mid=to_float(row.get("mid")) or to_float(row.get("settlement")),
                last_trade_price=to_float(row.get("settlement")),
                volume=to_int(row.get("volume")),
                open_interest=to_int(row.get("open_interest")),
                raw=row,
            )
        )

    if as_of is None:
        diagnostics.append(
            DataIssue(
                code="missing_capture_timestamp",
                severity=IssueSeverity.ERROR,
                detail=(
                    "Capture has no as_of column; load time was substituted. "
                    "Record the page timestamp before using this chain as evidence."
                ),
                field_name="as_of",
            )
        )

    chain = OptionChain(
        ticker=ticker.strip().upper(),
        venue=venue,
        as_of=as_of or datetime.now().astimezone(),
        spot=spot,
        source="Eurex manual options capture",
        endpoint_or_file=str(capture_path),
        validation_status=(
            ValidationStatus.PARTIAL if contracts else ValidationStatus.UNAVAILABLE
        ),
        contracts=contracts,
        diagnostics=diagnostics,
    )
    if filters is None:
        return chain
    return chain.filtered(filters, reference_time=reference_time)


def load_eu_short_disclosures_csv(path: str | Path) -> list[ShortInterestSnapshot]:
    rows = _read_csv(Path(path))
    disclosures: list[ShortInterestSnapshot] = []
    for row in rows:
        position_date = (
            row.get("position_date")
            or row.get("date")
            or row.get("Position Date")
            or row.get("Position date")
        )
        if not position_date:
            continue
        disclosures.append(
            ShortInterestSnapshot(
                ticker=(row.get("ticker") or row.get("Ticker") or None),
                isin=row.get("isin") or row.get("ISIN"),
                issuer=row.get("issuer") or row.get("Issuer"),
                holder=row.get("holder") or row.get("Position Holder") or row.get("position_holder"),
                as_of=parse_compact_or_iso_date(position_date),
                source="EU disclosed net short positions",
                disclosed_net_short_pct=to_float(
                    row.get("net_short_position")
                    or row.get("Net Short Position")
                    or row.get("position_pct")
                ),
                raw=row,
            )
        )
    return disclosures


def load_eu_mar_article_19_csv(
    path: str | Path,
    *,
    ticker: str | None = None,
) -> list[InsiderTransaction]:
    rows = _read_csv(Path(path))
    transactions: list[InsiderTransaction] = []
    for row in rows:
        symbol = (ticker or row.get("ticker") or row.get("Ticker") or "").strip().upper()
        transaction_date = (
            row.get("transaction_date")
            or row.get("Transaction Date")
            or row.get("date")
            or row.get("Date")
            or row.get("notification_date")
        )
        if not symbol or not transaction_date:
            continue
        shares = to_float(row.get("shares") or row.get("Shares") or row.get("volume"))
        price = to_float(row.get("price") or row.get("Price"))
        transactions.append(
            InsiderTransaction(
                ticker=symbol,
                as_of=parse_date(transaction_date),
                source="EU MAR Article 19 manual capture",
                insider=row.get("person") or row.get("Person") or row.get("insider"),
                title=row.get("role") or row.get("Role") or row.get("title"),
                transaction_type=(
                    row.get("transaction_type")
                    or row.get("Transaction Type")
                    or row.get("transaction")
                ),
                acquisition_or_disposal=(
                    row.get("acquisition_or_disposal")
                    or row.get("Acquisition/Disposal")
                    or row.get("direction")
                ),
                shares=shares,
                price=price,
                value=(
                    to_float(row.get("value") or row.get("Value"))
                    or (shares * price if shares is not None and price is not None else None)
                ),
                filing_date=parse_date(row["notification_date"])
                if row.get("notification_date")
                else None,
                raw=row,
            )
        )
    return transactions


def load_eu_major_holdings_csv(
    path: str | Path,
    *,
    ticker: str | None = None,
) -> list[OwnershipChange]:
    rows = _read_csv(Path(path))
    changes: list[OwnershipChange] = []
    for row in rows:
        symbol = (ticker or row.get("ticker") or row.get("Ticker") or "").strip().upper()
        institution = (
            row.get("institution")
            or row.get("Institution")
            or row.get("holder")
            or row.get("Shareholder")
        )
        as_of = (
            row.get("position_date")
            or row.get("notification_date")
            or row.get("date")
            or row.get("Date")
        )
        if not institution or not as_of:
            continue
        changes.append(
            OwnershipChange(
                ticker=symbol or None,
                institution=institution,
                as_of=parse_date(as_of),
                source="EU major holdings manual capture",
                cohort=row.get("cohort") or row.get("threshold"),
                shares=to_float(row.get("shares") or row.get("Shares")),
                shares_delta=to_float(row.get("shares_delta") or row.get("Change in shares")),
                percent_delta=to_float(
                    row.get("percent_delta")
                    or row.get("Percent Delta")
                    or row.get("voting_rights_pct")
                ),
                estimated_capital_flow=to_float(row.get("value") or row.get("Value")),
                raw=row,
            )
        )
    return changes


def _read_csv(path: Path) -> list[dict[str, Any]]:
    """Read a hand-made CSV. Short rows leave `None` values, which must not crash."""

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [
            {
                key.strip(): (value.strip() if isinstance(value, str) else value)
                for key, value in row.items()
                if key is not None
            }
            for row in csv.DictReader(handle)
        ]
