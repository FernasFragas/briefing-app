"""`S_I` - insider velocity.

US: SEC Form 4 open-market buys and sells over a 90-day window. Automated 10b5-1 plan
sales, option exercises, grants, gifts, and tax-withholding dispositions are excluded -
they are calendar mechanics, not conviction, and counting them is the fastest way to
manufacture an "insider selling" story out of a vesting schedule.

EU: Form 4 does not exist. MAR Article 19 managers' transactions (PDMR / directors'
dealings) stand in, and every result says so rather than presenting EU disclosure as if
it were a Form 4 feed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type, datetime
import re
from typing import Sequence

from briefing_app.components.base import (
    INSIDER,
    QUALITY_MANUAL,
    QUALITY_PRIMARY,
    STATUS_PARTIAL,
    STATUS_VERIFIED,
    ComponentResult,
    SubScore,
    build_evidence_rows,
    clamp,
    combine_sub_scores,
    evidence_from_sub_scores,
    squash,
    worst_quality,
    to_datetime,
    unavailable_component,
)
from briefing_app.models.candidate import Geography
from briefing_app.models.market_data import InsiderTransaction

#: Form 4 transaction codes that represent a real open-market decision.
OPEN_MARKET_CODES: frozenset[str] = frozenset({"P", "S"})

#: Codes that are calendar mechanics, not conviction. Excluded with a diagnostic.
EXCLUDED_CODES: dict[str, str] = {
    "A": "grant or award",
    "M": "option exercise",
    "F": "tax withholding",
    "G": "gift",
    "C": "conversion",
    "X": "in-the-money option exercise",
    "D": "disposition to the issuer",
    "I": "discretionary transaction",
}

#: Phrases in a transaction description that mark it as non-open-market.
_EXCLUDED_PHRASES: tuple[tuple[str, str], ...] = (
    ("10b5-1", "10b5-1 automated plan"),
    ("10b51", "10b5-1 automated plan"),
    ("rule 10b5", "10b5-1 automated plan"),
    ("tax withholding", "tax withholding"),
    ("withheld for taxes", "tax withholding"),
    ("payment of exercise", "option exercise"),
    ("option exercise", "option exercise"),
    ("exercise of", "option exercise"),
    ("grant", "grant or award"),
    ("award", "grant or award"),
    ("gift", "gift"),
    ("vesting", "vesting"),
    ("restricted stock", "grant or award"),
)

#: Conviction weight by role. A CEO or CFO buying is not the same signal as a
#: 10-percent holder rebalancing.
ROLE_WEIGHTS: tuple[tuple[tuple[str, ...], float, str], ...] = (
    (("chief executive", "ceo", "president and ceo"), 1.0, "ceo"),
    (("chief financial", "cfo"), 1.0, "cfo"),
    (("chief operating", "coo", "chief technology", "cto", "chief"), 0.7, "operating_officer"),
    (("evp", "executive vice president", "senior vice president", "svp"), 0.6, "senior_officer"),
    (("director", "chair", "board"), 0.5, "director"),
    (("10%", "ten percent", "beneficial owner"), 0.3, "ten_percent_owner"),
)
DEFAULT_ROLE_WEIGHT = 0.4
DEFAULT_ROLE_LABEL = "other_insider"

#: Form 4 must be filed within two business days, so a 90-day window is the cluster
#: window the framework scores on.
WINDOW_DAYS = 90

#: Net dollar flow that saturates the score, so the reading stays in the unit of the
#: input rather than an opaque constant.
NET_VALUE_SCALE = 5_000_000.0


@dataclass(frozen=True)
class ExcludedTransaction:
    """One filtered row plus the rule that filtered it, so the parser is auditable."""

    insider: str | None
    as_of: date_type
    reason: str
    raw_type: str | None


@dataclass(frozen=True)
class InsiderActivity:
    """The open-market subset of a Form 4 / Article 19 feed."""

    buys: tuple[InsiderTransaction, ...]
    sells: tuple[InsiderTransaction, ...]
    excluded: tuple[ExcludedTransaction, ...]
    buy_value: float
    sell_value: float
    weighted_buy_value: float
    weighted_sell_value: float
    buyer_count: int
    seller_count: int
    latest_as_of: date_type | None

    @property
    def net_value(self) -> float:
        return self.buy_value - self.sell_value

    @property
    def weighted_net_value(self) -> float:
        return self.weighted_buy_value - self.weighted_sell_value

    @property
    def total_value(self) -> float:
        return self.buy_value + self.sell_value


def role_weight(title: str | None) -> tuple[float, str]:
    """Conviction weight and role label for an insider's title.

    Abbreviations are matched as whole words. Substring matching silently promotes every
    "Director" to a CTO, because "director" contains "cto".
    """
    if not title:
        return DEFAULT_ROLE_WEIGHT, DEFAULT_ROLE_LABEL
    lowered = title.strip().lower()
    words = set(re.findall(r"[a-z]+", lowered))
    for needles, weight, label in ROLE_WEIGHTS:
        for needle in needles:
            matched = needle in words if needle.isalpha() and " " not in needle else needle in lowered
            if matched:
                return weight, label
    return DEFAULT_ROLE_WEIGHT, DEFAULT_ROLE_LABEL


def classify_transaction(transaction: InsiderTransaction) -> tuple[str | None, str | None]:
    """Return `(direction, exclusion_reason)`.

    `direction` is "buy" or "sell" for a genuine open-market trade; otherwise it is
    `None` and the reason names the rule that excluded the row.
    """
    haystack = " ".join(
        str(value).lower()
        for value in (
            transaction.transaction_type,
            transaction.acquisition_or_disposal,
            transaction.raw.get("securityTransactionType") if transaction.raw else None,
            transaction.raw.get("transactionCode") if transaction.raw else None,
            transaction.raw.get("footnote") if transaction.raw else None,
            transaction.raw.get("description") if transaction.raw else None,
        )
        if value is not None
    )

    for phrase, reason in _EXCLUDED_PHRASES:
        if phrase in haystack:
            return None, reason

    code = _transaction_code(transaction)
    if code in EXCLUDED_CODES:
        return None, EXCLUDED_CODES[code]

    if code == "P":
        return "buy", None
    if code == "S":
        return "sell", None

    # No usable code: fall back to explicit wording, never to a guess.
    if "purchase" in haystack or haystack.strip() in {"a", "acquisition"}:
        return "buy", None
    if "sale" in haystack or "sold" in haystack or haystack.strip() in {"d", "disposal"}:
        return "sell", None
    return None, "transaction type not recognized as an open-market buy or sell"


def _transaction_code(transaction: InsiderTransaction) -> str | None:
    candidates = [
        transaction.raw.get("transactionCode") if transaction.raw else None,
        transaction.raw.get("transaction_code") if transaction.raw else None,
        transaction.transaction_type,
    ]
    for candidate in candidates:
        if not candidate:
            continue
        text = str(candidate).strip().upper()
        if len(text) == 1 and text.isalpha():
            return text
        # Forms like "P-Purchase" or "S - Sale".
        head = text.split("-")[0].strip()
        if len(head) == 1 and head.isalpha():
            return head
    return None


def _transaction_value(transaction: InsiderTransaction) -> float:
    if transaction.value is not None:
        return abs(float(transaction.value))
    if transaction.shares is not None and transaction.price is not None:
        return abs(float(transaction.shares) * float(transaction.price))
    return 0.0


def extract_activity(
    transactions: Sequence[InsiderTransaction],
    *,
    run_date: date_type,
    window_days: int = WINDOW_DAYS,
) -> InsiderActivity:
    """Split a filing feed into scored open-market trades and excluded noise."""
    buys: list[InsiderTransaction] = []
    sells: list[InsiderTransaction] = []
    excluded: list[ExcludedTransaction] = []
    buy_value = sell_value = weighted_buy = weighted_sell = 0.0
    buyers: set[str] = set()
    sellers: set[str] = set()
    latest: date_type | None = None

    for transaction in transactions:
        age = (run_date - transaction.as_of).days
        if age > window_days or age < 0:
            excluded.append(
                ExcludedTransaction(
                    insider=transaction.insider,
                    as_of=transaction.as_of,
                    reason=f"outside the {window_days}-day window",
                    raw_type=transaction.transaction_type,
                )
            )
            continue

        direction, reason = classify_transaction(transaction)
        if direction is None:
            excluded.append(
                ExcludedTransaction(
                    insider=transaction.insider,
                    as_of=transaction.as_of,
                    reason=reason or "excluded",
                    raw_type=transaction.transaction_type,
                )
            )
            continue

        value = _transaction_value(transaction)
        weight, _label = role_weight(transaction.title)
        identity = (transaction.insider or "unknown").strip().lower()
        latest = transaction.as_of if latest is None else max(latest, transaction.as_of)

        if direction == "buy":
            buys.append(transaction)
            buy_value += value
            weighted_buy += value * weight
            buyers.add(identity)
        else:
            sells.append(transaction)
            sell_value += value
            weighted_sell += value * weight
            sellers.add(identity)

    return InsiderActivity(
        buys=tuple(buys),
        sells=tuple(sells),
        excluded=tuple(excluded),
        buy_value=buy_value,
        sell_value=sell_value,
        weighted_buy_value=weighted_buy,
        weighted_sell_value=weighted_sell,
        buyer_count=len(buyers),
        seller_count=len(sellers),
        latest_as_of=latest,
    )


def build_insider_component(
    *,
    ticker: str,
    geography: Geography | str,
    transactions: Sequence[InsiderTransaction] = (),
    run_date: date_type,
    as_of: datetime | None = None,
    window_days: int = WINDOW_DAYS,
    source: str | None = None,
    source_quality: str = QUALITY_PRIMARY,
    endpoint_or_file: str = "",
    run_id: int | None = None,
) -> ComponentResult:
    """Score `S_I` from a filing feed, or return `n/a` with the reason."""
    geo = Geography(geography)
    clean_ticker = ticker.strip().upper()
    resolved_as_of = to_datetime(as_of or run_date)
    is_eu = not geo.is_us
    default_source = (
        "MAR Article 19 PDMR dealings" if is_eu else "SEC Form 4 open-market transactions"
    )
    resolved_source = source or default_source
    eu_substitutes = (
        ("MAR Article 19 PDMR dealings stand in for SEC Form 4; disclosure thresholds "
         "and timing differ, so cluster counts are not comparable to a US feed.",)
        if is_eu
        else ()
    )

    if not transactions:
        return unavailable_component(
            component=INSIDER,
            ticker=clean_ticker,
            geography=geo,
            as_of=resolved_as_of,
            reason=(
                "no MAR Article 19 disclosures available"
                if is_eu
                else "no Form 4 transactions available"
            ),
            eu_substitutes=eu_substitutes,
        )

    activity = extract_activity(transactions, run_date=run_date, window_days=window_days)
    diagnostics: list[str] = []
    if activity.excluded:
        by_reason: dict[str, int] = {}
        for row in activity.excluded:
            by_reason[row.reason] = by_reason.get(row.reason, 0) + 1
        diagnostics.append(
            "Excluded "
            + ", ".join(f"{count} x {reason}" for reason, count in sorted(by_reason.items()))
            + " before scoring."
        )

    if not activity.buys and not activity.sells:
        return unavailable_component(
            component=INSIDER,
            ticker=clean_ticker,
            geography=geo,
            as_of=resolved_as_of,
            reason=(
                f"no open-market insider trades in the last {window_days} days; "
                f"{len(activity.excluded)} filings were plan, grant, or exercise activity"
            ),
            diagnostics=diagnostics,
            eu_substitutes=eu_substitutes,
        )

    sub_scores = (
        _net_flow_sub_score(activity, window_days),
        _breadth_sub_score(activity),
        _seniority_sub_score(activity),
    )
    score, weights_used, disclosures = combine_sub_scores(sub_scores)
    diagnostics.extend(disclosures)

    if is_eu:
        diagnostics.append(
            "EU name: scored from Article 19 managers' transactions, not Form 4."
        )

    evidence = build_evidence_rows(
        component=INSIDER,
        ticker=clean_ticker,
        as_of=resolved_as_of,
        source=resolved_source,
        endpoint_or_file=endpoint_or_file,
        run_id=run_id,
        values={
            "insider_open_market_buys": len(activity.buys),
            "insider_open_market_sells": len(activity.sells),
            "insider_buy_value": round(activity.buy_value, 2),
            "insider_sell_value": round(activity.sell_value, 2),
            "insider_net_value": round(activity.net_value, 2),
            "insider_distinct_buyers": activity.buyer_count,
            "insider_distinct_sellers": activity.seller_count,
            "insider_excluded_filings": len(activity.excluded),
            "insider_window_days": window_days,
            "s_i": None if score is None else round(score, 4),
        },
        notes={
            "insider_excluded_filings": (
                "10b5-1 plans, option exercises, grants, gifts, and tax withholding are "
                "excluded from the score."
            ),
            "s_i": "EU Article 19 substitute." if is_eu else None,
        },
    )
    evidence.extend(
        evidence_from_sub_scores(INSIDER, clean_ticker, resolved_as_of, sub_scores, run_id=run_id)
    )

    # EU disclosure is issuer- or regulator-published and hand-collected in this stack,
    # so it can never outrank a manual capture no matter what the caller claims.
    quality = worst_quality(source_quality, QUALITY_MANUAL) if is_eu else source_quality
    return ComponentResult(
        component=INSIDER,
        ticker=clean_ticker,
        as_of=resolved_as_of,
        geography=geo,
        available=score is not None,
        score=score,
        validation_status=STATUS_VERIFIED if score is not None else STATUS_PARTIAL,
        source_quality=quality,
        na_reason=None if score is not None else "no insider sub-score could be measured",
        sub_scores=sub_scores,
        weights_used=weights_used,
        source_rows=tuple(
            {
                "insider": transaction.insider,
                "title": transaction.title,
                "role": role_weight(transaction.title)[1],
                "as_of": transaction.as_of.isoformat(),
                "direction": direction,
                "shares": transaction.shares,
                "price": transaction.price,
                "value": _transaction_value(transaction),
                "source": transaction.source,
            }
            for direction, rows in (("buy", activity.buys), ("sell", activity.sells))
            for transaction in rows
        ),
        evidence_rows=tuple(evidence),
        diagnostics=tuple(diagnostics),
        eu_substitutes=eu_substitutes,
    )


def _net_flow_sub_score(activity: InsiderActivity, window_days: int) -> SubScore:
    """Role-weighted net dollar flow: the core conviction reading."""
    if activity.total_value <= 0:
        return SubScore(
            name="net_flow",
            weight=0.60,
            na_reason="open-market trades carried no share count or price",
            sample_size=len(activity.buys) + len(activity.sells),
        )
    score = squash(activity.weighted_net_value, scale=NET_VALUE_SCALE)
    return SubScore(
        name="net_flow",
        weight=0.60,
        score=score,
        detail=(
            f"role-weighted net {activity.weighted_net_value:,.0f} over {window_days}d "
            f"(buys {activity.buy_value:,.0f}, sells {activity.sell_value:,.0f})"
        ),
        as_of=activity.latest_as_of,
        sample_size=len(activity.buys) + len(activity.sells),
        inputs={
            "weighted_net_value": activity.weighted_net_value,
            "buy_value": activity.buy_value,
            "sell_value": activity.sell_value,
        },
    )


def _breadth_sub_score(activity: InsiderActivity) -> SubScore:
    """How many distinct insiders acted, and in which direction.

    One executive buying is an opinion; five buying is a cluster.
    """
    total_people = activity.buyer_count + activity.seller_count
    if total_people == 0:
        return SubScore(
            name="breadth",
            weight=0.25,
            na_reason="no identifiable insiders in the window",
        )
    tilt = (activity.buyer_count - activity.seller_count) / total_people
    conviction = min(1.0, total_people / 4.0)
    return SubScore(
        name="breadth",
        weight=0.25,
        score=clamp(tilt * conviction),
        detail=f"{activity.buyer_count} distinct buyers vs {activity.seller_count} sellers",
        as_of=activity.latest_as_of,
        sample_size=total_people,
        inputs={"buyers": activity.buyer_count, "sellers": activity.seller_count},
    )


def _seniority_sub_score(activity: InsiderActivity) -> SubScore:
    """Whether the flow came from the people closest to the numbers."""
    senior_buy = sum(
        _transaction_value(t) for t in activity.buys if role_weight(t.title)[0] >= 0.7
    )
    senior_sell = sum(
        _transaction_value(t) for t in activity.sells if role_weight(t.title)[0] >= 0.7
    )
    if senior_buy + senior_sell <= 0:
        return SubScore(
            name="seniority",
            weight=0.15,
            na_reason="no CEO, CFO, or senior-officer open-market trades in the window",
        )
    tilt = (senior_buy - senior_sell) / (senior_buy + senior_sell)
    return SubScore(
        name="seniority",
        weight=0.15,
        score=clamp(tilt),
        detail=f"senior-officer buys {senior_buy:,.0f} vs sells {senior_sell:,.0f}",
        as_of=activity.latest_as_of,
        inputs={"senior_buy_value": senior_buy, "senior_sell_value": senior_sell},
    )
