"""`S_S` - the multi-channel sentiment matrix.

    S_S = (S_S1 * 0.45) + (S_S2 * 0.35) + (S_S3 * 0.20)

`S_S1` institutional / analyst, `S_S2` executive and transcript tone, `S_S3` retail and
social momentum. Retail is the 20 percent leg and never the thesis.

News sentiment is reported in full alongside the score - 24-hour aggregate, 7-day
trailing baseline, the delta between them, article count, and top deduplicated
headlines - because the delta is the useful part and the level alone is not. The same
wire story syndicated across ten sites is one story, so articles are deduplicated by
canonical URL and by normalized title before anything is averaged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date as date_type, datetime, timedelta
from typing import Sequence
from urllib.parse import urlsplit
import re

from briefing_app.components.base import (
    QUALITY_AGGREGATOR,
    QUALITY_PRIMARY,
    SENTIMENT,
    STATUS_PARTIAL,
    STATUS_VERIFIED,
    ComponentResult,
    SubScore,
    build_evidence_rows,
    clamp,
    combine_sub_scores,
    evidence_from_sub_scores,
    is_stale,
    to_datetime,
    unavailable_component,
    worst_quality,
)
from briefing_app.models.candidate import Geography
from briefing_app.models.market_data import (
    AnalystSignal,
    NewsArticle,
    NewsSentimentBatch,
    PoliticalTrade,
    RetailMomentumSnapshot,
)

#: The weights are fixed by the framework. They are re-normalized only when a leg is
#: unmeasurable, never adjusted to taste.
WEIGHT_INSTITUTIONAL = 0.45
WEIGHT_EXECUTIVE = 0.35
WEIGHT_RETAIL = 0.20

#: Sentiment is a rolling read; anything older than a week is not current sentiment.
MAX_AGE_DAYS = 7

#: Congressional disclosures are useful context but can arrive weeks after the trade.
#: Apply them as a score adjustment, not as another reweighted base leg.
POLITICAL_FLOW_MAX_IMPACT = 0.05
POLITICAL_FLOW_WINDOW_DAYS = 90
POLITICAL_DISCLOSURE_LAG_DAYS = 45

#: Windows for the news read.
RECENT_WINDOW_HOURS = 24
BASELINE_WINDOW_DAYS = 7

#: Rating text mapped to a directional score.
_RATING_SCORES: tuple[tuple[tuple[str, ...], float], ...] = (
    (("strong buy", "conviction buy"), 1.0),
    (("buy", "outperform", "overweight", "accumulate"), 0.6),
    (("hold", "neutral", "market perform", "equal weight", "sector perform"), 0.0),
    (("underperform", "underweight", "reduce"), -0.6),
    (("strong sell", "sell"), -1.0),
)

_TITLE_NOISE = re.compile(r"[^a-z0-9 ]+")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class NewsSummary:
    """The news block reported beside `S_S`, whether or not it feeds a leg."""

    article_count: int
    unique_article_count: int
    duplicates_removed: int
    recent_count: int
    baseline_count: int
    recent_score: float | None
    baseline_score: float | None
    delta: float | None
    top_headlines: tuple[dict[str, str], ...] = ()
    as_of: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "article_count": self.article_count,
            "unique_article_count": self.unique_article_count,
            "duplicates_removed": self.duplicates_removed,
            "recent_count": self.recent_count,
            "baseline_count": self.baseline_count,
            "recent_score": self.recent_score,
            "baseline_score": self.baseline_score,
            "delta": self.delta,
            "top_headlines": [dict(h) for h in self.top_headlines],
            "as_of": self.as_of.isoformat() if self.as_of else None,
        }


@dataclass(frozen=True)
class ToneReading:
    """A tone score supplied by a caller that has parsed a transcript or a social feed.

    Neither transcripts nor social feeds are fetched by this stack today, so these legs
    are `n/a` unless a reading is passed in. That is the honest default: an unmeasured
    channel is not a neutral channel.
    """

    score: float
    source: str
    as_of: date_type
    detail: str | None = None
    sample_size: int = 0
    inputs: dict[str, object] = field(default_factory=dict)


def normalize_title(title: str) -> str:
    """Collapse a headline to a comparison key so syndicated copies collide."""
    lowered = _TITLE_NOISE.sub(" ", title.strip().lower())
    return _WHITESPACE.sub(" ", lowered).strip()


def canonical_url(url: str | None) -> str | None:
    """Drop the query string and fragment so tracking parameters do not defeat dedup."""
    if not url:
        return None
    parts = urlsplit(url.strip())
    if not parts.netloc:
        return None
    host = parts.netloc.lower().removeprefix("www.")
    return f"{host}{parts.path.rstrip('/')}"


def deduplicate_articles(articles: Sequence[NewsArticle]) -> list[NewsArticle]:
    """One story counted once. Canonical URL first, then normalized title."""
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    unique: list[NewsArticle] = []
    for article in sorted(articles, key=lambda a: a.published_at, reverse=True):
        url_key = canonical_url(article.url)
        title_key = normalize_title(article.title)
        if url_key and url_key in seen_urls:
            continue
        if title_key and title_key in seen_titles:
            continue
        if url_key:
            seen_urls.add(url_key)
        if title_key:
            seen_titles.add(title_key)
        unique.append(article)
    return unique


def summarize_news(
    batch: NewsSentimentBatch | None,
    *,
    now: datetime,
    top_n: int = 5,
) -> NewsSummary:
    """24-hour score, 7-day baseline, delta, counts, and top deduplicated headlines."""
    articles = list(batch.articles) if batch else []
    unique = deduplicate_articles(articles)

    recent_cutoff = now - timedelta(hours=RECENT_WINDOW_HOURS)
    baseline_cutoff = now - timedelta(days=BASELINE_WINDOW_DAYS)
    recent = [a for a in unique if _aware(a.published_at) >= recent_cutoff]
    baseline = [
        a for a in unique if baseline_cutoff <= _aware(a.published_at) < recent_cutoff
    ]

    recent_score = _mean_sentiment(recent)
    baseline_score = _mean_sentiment(baseline)
    delta = (
        recent_score - baseline_score
        if recent_score is not None and baseline_score is not None
        else None
    )

    return NewsSummary(
        article_count=len(articles),
        unique_article_count=len(unique),
        duplicates_removed=len(articles) - len(unique),
        recent_count=len(recent),
        baseline_count=len(baseline),
        recent_score=recent_score,
        baseline_score=baseline_score,
        delta=delta,
        top_headlines=tuple(
            {
                "title": a.title,
                "source": a.source,
                "published_at": a.published_at.isoformat(),
                "url": a.url or "",
                "sentiment": "" if a.sentiment_score is None else f"{a.sentiment_score:.3f}",
            }
            for a in unique[:top_n]
        ),
        as_of=batch.as_of if batch else None,
    )


def rating_score(rating: str | None) -> float | None:
    if not rating:
        return None
    lowered = rating.strip().lower()
    for needles, score in _RATING_SCORES:
        if any(needle in lowered for needle in needles):
            return score
    return None


def build_sentiment_component(
    *,
    ticker: str,
    geography: Geography | str,
    run_date: date_type,
    news: NewsSentimentBatch | None = None,
    analyst_signals: Sequence[AnalystSignal] = (),
    spot: float | None = None,
    executive_tone: ToneReading | None = None,
    retail_momentum: ToneReading | RetailMomentumSnapshot | None = None,
    political_flow: Sequence[PoliticalTrade] | None = None,
    as_of: datetime | None = None,
    max_age_days: int = MAX_AGE_DAYS,
    source_quality: str = QUALITY_AGGREGATOR,
    endpoint_or_file: str = "",
    run_id: int | None = None,
) -> ComponentResult:
    """Score `S_S` exactly per the 45/35/20 matrix, re-normalizing only for missing legs."""
    geo = Geography(geography)
    clean_ticker = ticker.strip().upper()
    resolved_as_of = to_datetime(as_of or run_date)
    now = resolved_as_of

    summary = summarize_news(news, now=now)
    diagnostics: list[str] = []
    if summary.duplicates_removed:
        diagnostics.append(
            f"Deduplicated {summary.duplicates_removed} syndicated copies of "
            f"{summary.article_count} articles before scoring."
        )

    institutional = _institutional_sub_score(
        analyst_signals,
        summary,
        spot=spot,
        run_date=run_date,
        max_age_days=max_age_days,
    )
    executive = _tone_sub_score(
        executive_tone,
        name="executive_tone",
        weight=WEIGHT_EXECUTIVE,
        run_date=run_date,
        max_age_days=max_age_days,
        missing_reason=(
            "no executive or transcript tone reading supplied; transcripts are not "
            "fetched by this stack"
        ),
    )
    retail = _retail_sub_score(
        retail_momentum,
        run_date=run_date,
        max_age_days=max_age_days,
    )
    base_sub_scores = (institutional, executive, retail)

    score, weights_used, disclosures = combine_sub_scores(base_sub_scores)
    diagnostics.extend(disclosures)

    political = (
        _political_flow_sub_score(
            [trade for trade in political_flow if trade.ticker == clean_ticker],
            run_date=run_date,
        )
        if political_flow is not None
        else None
    )
    sub_scores = base_sub_scores + ((political,) if political is not None else ())
    if political is not None:
        if political.available:
            adjustment = (political.score or 0.0) * POLITICAL_FLOW_MAX_IMPACT
            base_score = score or 0.0
            unclamped_score = base_score + adjustment
            score = clamp(unclamped_score)
            weights_used = dict(weights_used)
            weights_used["political_flow"] = POLITICAL_FLOW_MAX_IMPACT
            diagnostics.append(
                "political_flow applied as a capped +/-"
                f"{POLITICAL_FLOW_MAX_IMPACT:.2f} S_S overlay; STOCK Act filings can "
                "lag up to 45 days, so treat it as context rather than edge."
            )
            if score != unclamped_score:
                diagnostics.append("political_flow adjustment was clipped at the S_S bounds.")
        else:
            weights_used = dict(weights_used)
            weights_used["political_flow"] = 0.0
            diagnostics.append(
                f"political_flow is n/a ({political.na_reason}); capped overlay absent."
            )

    if score is None:
        return unavailable_component(
            component=SENTIMENT,
            ticker=clean_ticker,
            geography=geo,
            as_of=resolved_as_of,
            reason="no sentiment channel could be measured",
            sub_scores=sub_scores,
            diagnostics=diagnostics,
        )

    if not institutional.available:
        diagnostics.append(
            "Institutional leg is n/a, so the score leans on channels the framework "
            "weights lower. Treat with matching confidence."
        )

    evidence = build_evidence_rows(
        component=SENTIMENT,
        ticker=clean_ticker,
        as_of=resolved_as_of,
        source=news.source if news else "computed",
        endpoint_or_file=endpoint_or_file,
        run_id=run_id,
        values={
            "news_article_count": summary.article_count,
            "news_unique_article_count": summary.unique_article_count,
            "news_duplicates_removed": summary.duplicates_removed,
            "news_score_24h": _round(summary.recent_score),
            "news_baseline_7d": _round(summary.baseline_score),
            "news_sentiment_delta": _round(summary.delta),
            "analyst_signal_count": len(analyst_signals) or None,
            "political_flow_score": _round(political.score)
            if political and political.available
            else None,
            "political_flow_adjustment": _round(
                (political.score or 0.0) * POLITICAL_FLOW_MAX_IMPACT
            )
            if political and political.available
            else None,
            "s_s": round(score, 4),
        },
        notes={
            "news_sentiment_delta": "24-hour aggregate minus the 7-day trailing baseline.",
            "political_flow_adjustment": (
                "Capped overlay; congressional disclosures can lag up to 45 days."
            ),
            "s_s": (
                f"weights used - institutional {weights_used['institutional']:.4f}, "
                f"executive {weights_used['executive_tone']:.4f}, "
                f"retail {weights_used['retail_momentum']:.4f}"
                + (
                    f", political overlay {weights_used['political_flow']:.4f}"
                    if political is not None
                    else ""
                )
            ),
        },
    )
    evidence.extend(
        evidence_from_sub_scores(SENTIMENT, clean_ticker, resolved_as_of, sub_scores, run_id=run_id)
    )
    if political is not None:
        evidence.extend(
            _political_trade_evidence_rows(
                [trade for trade in political_flow or () if trade.ticker == clean_ticker],
                run_id=run_id,
            )
        )

    quality = worst_quality(source_quality, QUALITY_AGGREGATOR if analyst_signals else source_quality)
    return ComponentResult(
        component=SENTIMENT,
        ticker=clean_ticker,
        as_of=resolved_as_of,
        geography=geo,
        available=True,
        score=score,
        validation_status=STATUS_VERIFIED if all(s.available for s in sub_scores) else STATUS_PARTIAL,
        source_quality=quality,
        sub_scores=sub_scores,
        weights_used=weights_used,
        source_rows=tuple(summary.to_dict()["top_headlines"]),
        evidence_rows=tuple(evidence),
        diagnostics=tuple(diagnostics),
    )


def _institutional_sub_score(
    signals: Sequence[AnalystSignal],
    summary: NewsSummary,
    *,
    spot: float | None,
    run_date: date_type,
    max_age_days: int,
) -> SubScore:
    """Analyst ratings and price targets, with the news delta as a secondary read."""
    fresh = [s for s in signals if not is_stale(s.as_of, run_date=run_date, max_age_days=90)]
    parts: list[tuple[str, float]] = []
    details: list[str] = []
    latest: date_type | None = max((s.as_of for s in fresh), default=None)

    ratings = [rating_score(s.rating) for s in fresh]
    ratings = [r for r in ratings if r is not None]
    if ratings:
        parts.append(("ratings", sum(ratings) / len(ratings)))
        details.append(f"{len(ratings)} analyst ratings")

    revisions = [
        _revision_score(s) for s in fresh if _revision_score(s) is not None
    ]
    if revisions:
        parts.append(("revisions", sum(revisions) / len(revisions)))  # type: ignore[arg-type]
        details.append(f"{len(revisions)} rating or target revisions")

    upside = _price_target_upside(fresh, spot)
    if upside is not None:
        parts.append(("price_target", clamp(upside / 0.25)))
        details.append(f"consensus target {upside:+.1%} vs spot")

    if summary.delta is not None:
        parts.append(("news_delta", clamp(summary.delta * 2.0)))
        details.append(
            f"news 24h {summary.recent_score:+.3f} vs 7d {summary.baseline_score:+.3f}"
        )
    elif summary.recent_score is not None:
        parts.append(("news_level", clamp(summary.recent_score * 2.0)))
        details.append(f"news 24h {summary.recent_score:+.3f} (no baseline yet)")

    if not parts:
        return SubScore(
            name="institutional",
            weight=WEIGHT_INSTITUTIONAL,
            na_reason=(
                "no analyst ratings, target revisions, or scored news in the window"
            ),
            sample_size=len(signals),
        )

    score = sum(value for _name, value in parts) / len(parts)
    return SubScore(
        name="institutional",
        weight=WEIGHT_INSTITUTIONAL,
        score=clamp(score),
        detail="; ".join(details),
        source="analyst coverage and news sentiment",
        as_of=latest or (summary.as_of.date() if summary.as_of else None),
        sample_size=len(fresh) + summary.unique_article_count,
        inputs={name: round(value, 4) for name, value in parts},
    )


def _revision_score(signal: AnalystSignal) -> float | None:
    """Direction of a change, which carries more information than the level."""
    current = rating_score(signal.rating)
    previous = rating_score(signal.previous_rating)
    if current is not None and previous is not None and current != previous:
        return clamp(current - previous)
    if signal.price_target and signal.previous_price_target:
        change = (signal.price_target - signal.previous_price_target) / signal.previous_price_target
        return clamp(change / 0.15)
    action = (signal.action or "").strip().lower()
    if "upgrade" in action or "raise" in action:
        return 0.6
    if "downgrade" in action or "lower" in action or "cut" in action:
        return -0.6
    return None


def _price_target_upside(
    signals: Sequence[AnalystSignal], spot: float | None
) -> float | None:
    if not spot or spot <= 0:
        return None
    targets = [s.price_target for s in signals if s.price_target and s.price_target > 0]
    if not targets:
        return None
    return (sum(targets) / len(targets)) / spot - 1.0


def _retail_tone_reading(
    reading: ToneReading | RetailMomentumSnapshot | None,
) -> ToneReading | None:
    if reading is None or isinstance(reading, ToneReading):
        return reading

    prior = reading.mentions_24h_ago
    if prior is None:
        return None
    delta = reading.mentions - prior
    denominator = max(reading.mentions, prior, 10)
    score = clamp(delta / denominator)
    return ToneReading(
        score=score,
        source=reading.source,
        as_of=reading.as_of,
        detail=(
            f"ApeWisdom attention momentum: {reading.mentions} mentions vs "
            f"{prior} 24h ago; counts measure attention, not sentiment."
        ),
        sample_size=reading.mentions,
        inputs={
            "mentions": reading.mentions,
            "mentions_24h_ago": prior,
            "mentions_delta": delta,
            "upvotes": reading.upvotes,
            "rank": reading.rank,
            "rank_24h_ago": reading.rank_24h_ago,
        },
    )


def _retail_sub_score(
    reading: ToneReading | RetailMomentumSnapshot | None,
    *,
    run_date: date_type,
    max_age_days: int,
) -> SubScore:
    if isinstance(reading, RetailMomentumSnapshot) and reading.mentions_24h_ago is None:
        return SubScore(
            name="retail_momentum",
            weight=WEIGHT_RETAIL,
            na_reason=(
                "ApeWisdom row did not include mentions_24h_ago; attention level alone "
                "is not momentum"
            ),
            source=reading.source,
            as_of=reading.as_of,
            sample_size=reading.mentions,
            inputs={
                "mentions": reading.mentions,
                "upvotes": reading.upvotes,
                "rank": reading.rank,
            },
        )
    return _tone_sub_score(
        _retail_tone_reading(reading),
        name="retail_momentum",
        weight=WEIGHT_RETAIL,
        run_date=run_date,
        max_age_days=max_age_days,
        missing_reason="no retail or social momentum reading supplied",
    )


def _political_flow_sub_score(
    trades: Sequence[PoliticalTrade],
    *,
    run_date: date_type,
) -> SubScore:
    if not trades:
        return SubScore(
            name="political_flow",
            weight=POLITICAL_FLOW_MAX_IMPACT,
            na_reason="no congressional disclosure rows matched this ticker",
        )

    scored: list[tuple[PoliticalTrade, float, float]] = []
    skipped = 0
    for trade in trades:
        direction = _political_trade_direction(trade.transaction_type)
        if direction is None:
            skipped += 1
            continue
        weight = _political_trade_weight(trade, run_date=run_date)
        if weight <= 0:
            skipped += 1
            continue
        scored.append((trade, direction, weight))

    if not scored:
        return SubScore(
            name="political_flow",
            weight=POLITICAL_FLOW_MAX_IMPACT,
            na_reason="matched congressional rows were stale, non-directional, or exchanges",
            sample_size=len(trades),
        )

    weighted = sum(direction * weight for _trade, direction, weight in scored)
    total_weight = sum(weight for _trade, _direction, weight in scored)
    score = clamp(weighted / total_weight)
    buys = sum(1 for _trade, direction, _weight in scored if direction > 0)
    sells = sum(1 for _trade, direction, _weight in scored if direction < 0)
    lags = [
        max(0, (trade.disclosure_date - trade.transaction_date).days)
        for trade, _direction, _weight in scored
        if trade.disclosure_date is not None
    ]
    latest = max(
        (trade.disclosure_date or trade.transaction_date for trade, _direction, _weight in scored),
        default=None,
    )
    return SubScore(
        name="political_flow",
        weight=POLITICAL_FLOW_MAX_IMPACT,
        score=score,
        detail=(
            f"{len(scored)} directional congressional disclosures "
            f"({buys} buys, {sells} sells); capped +/-"
            f"{POLITICAL_FLOW_MAX_IMPACT:.2f} S_S overlay, context not edge."
        ),
        source="FMP congressional disclosures",
        as_of=latest,
        sample_size=len(scored),
        inputs={
            "buy_count": buys,
            "sell_count": sells,
            "skipped_count": skipped,
            "avg_disclosure_lag_days": round(sum(lags) / len(lags), 2) if lags else None,
            "max_s_s_adjustment": POLITICAL_FLOW_MAX_IMPACT,
        },
    )


def _political_trade_direction(transaction_type: str | None) -> float | None:
    lowered = (transaction_type or "").strip().lower()
    if not lowered:
        return None
    if lowered.startswith("p") or "purchase" in lowered or "buy" in lowered:
        return 1.0
    if lowered.startswith("s") or "sale" in lowered or "sell" in lowered:
        return -1.0
    return None


def _political_trade_weight(trade: PoliticalTrade, *, run_date: date_type) -> float:
    transaction_age = (run_date - trade.transaction_date).days
    if transaction_age < 0 or transaction_age > POLITICAL_FLOW_WINDOW_DAYS:
        return 0.0

    recency_weight = 1.0 - (transaction_age / POLITICAL_FLOW_WINDOW_DAYS)
    if trade.disclosure_date is None:
        lag_weight = 0.25
    else:
        lag_days = max(0, (trade.disclosure_date - trade.transaction_date).days)
        lag_weight = max(
            0.10,
            1.0 - (min(lag_days, POLITICAL_DISCLOSURE_LAG_DAYS) / POLITICAL_DISCLOSURE_LAG_DAYS),
        )
    return recency_weight * lag_weight * _political_amount_weight(trade)


def _political_amount_weight(trade: PoliticalTrade) -> float:
    low = trade.amount_min
    high = trade.amount_max
    if low is None and high is None:
        return 0.25
    if low is None:
        midpoint = high or 0.0
    elif high is None:
        midpoint = low * 2.0
    else:
        midpoint = (low + high) / 2.0
    if midpoint >= 1_000_000:
        return 1.0
    if midpoint >= 250_000:
        return 0.85
    if midpoint >= 100_000:
        return 0.70
    if midpoint >= 50_000:
        return 0.55
    if midpoint >= 15_000:
        return 0.40
    return 0.25


def _political_trade_evidence_rows(
    trades: Sequence[PoliticalTrade],
    *,
    run_id: int | None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for trade in trades:
        direction = _political_trade_direction(trade.transaction_type)
        if direction is None:
            continue
        disclosure = (
            f", disclosed {trade.disclosure_date.isoformat()}"
            if trade.disclosure_date
            else ""
        )
        rows.append(
            {
                "run_id": run_id,
                "ticker": trade.ticker,
                "component": SENTIMENT,
                "field_name": "political_flow_trade",
                "field_value": (
                    f"{trade.transaction_type or 'transaction'}"
                    + (f" {trade.amount_range}" if trade.amount_range else "")
                ),
                "source": trade.source,
                "venue": "*",
                "as_of": to_datetime(trade.disclosure_date or trade.transaction_date),
                "endpoint_or_file": trade.source_url or "",
                "validation_status": STATUS_VERIFIED,
                "note": (
                    f"{trade.chamber} disclosure by {trade.politician or 'unknown'}; "
                    f"transaction {trade.transaction_date.isoformat()}{disclosure}; "
                    "STOCK Act disclosure lag means this is context, not edge."
                ),
            }
        )
    return rows


def _tone_sub_score(
    reading: ToneReading | None,
    *,
    name: str,
    weight: float,
    run_date: date_type,
    max_age_days: int,
    missing_reason: str,
) -> SubScore:
    if reading is None:
        return SubScore(name=name, weight=weight, na_reason=missing_reason)
    if is_stale(reading.as_of, run_date=run_date, max_age_days=max_age_days):
        return SubScore(
            name=name,
            weight=weight,
            na_reason=(
                f"reading from {reading.as_of.isoformat()} is beyond the "
                f"{max_age_days}-day sentiment staleness bound"
            ),
        )
    return SubScore(
        name=name,
        weight=weight,
        score=clamp(reading.score),
        detail=reading.detail,
        source=reading.source,
        as_of=reading.as_of,
        sample_size=reading.sample_size,
        inputs=dict(reading.inputs),
    )


def _mean_sentiment(articles: Sequence[NewsArticle]) -> float | None:
    scored = [a.sentiment_score for a in articles if a.sentiment_score is not None]
    if not scored:
        return None
    return sum(scored) / len(scored)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)
