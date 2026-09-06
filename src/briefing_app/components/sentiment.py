"""`S_S` - the multi-channel sentiment matrix.

The framework specifies three legs:

    S_S = (S_S1 * 0.45) + (S_S2 * 0.35) + (S_S3 * 0.20)

`S_S1` institutional / analyst, `S_S2` executive and transcript tone, `S_S3` retail and
social momentum. Retail is the 20 percent leg and never the thesis.

**What ships is a two-leg table, and it is written that way on purpose (PC3):**

    S_S = (S_S1 * 0.80) + (S_S3 * 0.20)          S_S2 declared, weight 0.00

`S_S2` has never had a source and, on the evidence in `pa10-executive-tone.md`, never
will on a free tier. Leaving 0.35 in the table and re-normalizing it away every single
run made the printed weights describe a component that does not exist: the report said
`0.45 / 0.35 / 0.20` and the score used `0.80 / - / 0.20`. PC3 asks for the weight of a
structurally absent leg to be dropped rather than perpetually redistributed, so it is.

**This changes no score.** Re-normalizing `0.45 / 0.20` under the retail cap already
yielded `0.80 / 0.20`; the arithmetic is identical and the printed table is now the one
actually used. The leg is still reported, with its reason - a dropped weight is a
recorded decision, not a deletion. Restore it by giving `WEIGHT_EXECUTIVE` its 0.35 back
and taking it off `WEIGHT_INSTITUTIONAL` if a transcript source is ever adopted.

Two of the three legs are decided rather than measured, and the decisions are recorded
here because they change the score:

- **`executive_tone` is permanently n/a (Q1).** Transcripts are unsourceable on every
  free tier this project can reach. Its weight is now stated as 0.00 rather than
  redistributed per run, and the run still says so.
- **Index and ETF candidates carry no analyst leg at all (PC3, 2026-09-03).** An index
  has no issuer, so it has no ratings, no target revisions and no Form 4s. Three
  providers agreed on the 09-03 run: FMP answered an empty root for SPY and 402 for QQQ,
  Finnhub answered an empty root for both. That is a property of the instrument, so it is
  declared rather than rediscovered - and the requests are not sent.
- **Redistribution may not promote a leg past its nominal weight (Q1b, Q3).** That 0.35
  has to go somewhere, and left alone it goes pro rata - which lifts retail attention to
  0.308 and, inside the institutional leg, lets a local news lexicon grow from a sixth of
  `S_S` to two thirds of it purely by analyst coverage going missing. Both are capped, so
  a leg's share stops depending on what else failed.

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

#: The framework's own three-leg split, kept so the shipped table can be compared with
#: the specification it descends from rather than quietly replacing it.
FRAMEWORK_WEIGHTS: dict[str, float] = {
    "institutional": 0.45,
    "executive_tone": 0.35,
    "retail_momentum": 0.20,
}

#: The shipped weights. They are re-normalized only when a leg is unmeasurable, never
#: adjusted to taste - and `executive_tone`'s 0.00 is not an adjustment to taste but the
#: recorded consequence of a leg that can never be measured (see the module docstring).
#: `WEIGHT_INSTITUTIONAL` is 0.80 because that is precisely what re-normalization produced
#: on every run under the retail cap; nothing about the score changes.
WEIGHT_INSTITUTIONAL = 0.80
WEIGHT_EXECUTIVE = 0.0
WEIGHT_RETAIL = 0.20

#: Q3. Re-normalization may not promote retail above its nominal weight.
#:
#: `executive_tone` is permanently n/a, so re-normalization was handing its 0.35 to the
#: surviving legs pro rata and lifting retail from 0.20 to 0.308 - promoting the noisiest,
#: most gameable leg precisely because a better one was missing. The floor of 10 in the
#: attention-momentum denominator means a name going from 0 to 10 mentions scores +1.0,
#: so that 0.308 is a third of `S_S` bought with ten Reddit posts. Redistribution stays
#: the rule; retail is simply not allowed to be what it promotes.
#:
#: The cap also settles what happens when retail is the only measurable channel: a capped
#: leg needs an uncapped one to absorb the remainder, and with none, `S_S` is n/a. Retail
#: is the 20 percent leg and never the thesis - including when it is all there is.
RETAIL_MAX_WEIGHT = WEIGHT_RETAIL

#: Q1. `executive_tone` is not an absent reading, it is a decided one. FMP transcripts
#: answer 402 and Finnhub's 403 on every free tier this project can reach, so the leg is
#: recorded permanently n/a and its 0.35 is redistributed rather than shrinking `S_S`'s
#: confidence. The consequence is stated on every run rather than left to be inferred:
#: with no transcript channel, `S_S` carries no first-party issuer voice at all.
EXECUTIVE_TONE_NA_REASON = (
    "executive and transcript tone is permanently n/a: earnings-call transcripts are "
    "unsourceable on every free tier this project can reach (FMP 402, Finnhub 403). "
    "Its framework weight of 0.35 is declared as 0.00 rather than re-normalized away on "
    "every run, so the printed weights are the ones the score used; the leg is reported, "
    "not scored as neutral"
)

#: PC3, 2026-09-03. An index or fund has no issuer, so the analyst leg is not thin - it
#: does not exist. Stated rather than rediscovered per run, and the fetches are skipped.
INDEX_INSTITUTIONAL_NA_REASON = (
    "analyst coverage is structurally n/a for an index or fund: ratings, target revisions "
    "and issuer filings are published about companies, not about baskets. Confirmed on "
    "2026-09-03 by three providers independently returning nothing for QQQ and SPY "
    "(FMP empty root and HTTP 402, Finnhub empty root), so the requests are no longer sent"
)

#: With no analyst leg, retail attention is all an index candidate has - and Q3 forbids
#: retail from carrying `S_S` alone. So `S_S` is n/a for index candidates by construction,
#: and says which of the two rules put it there.
INDEX_SENTIMENT_NA_REASON = (
    "S_S is structurally n/a for an index or fund: its analyst leg does not exist "
    "(instrument has no issuer) and retail attention is capped at "
    f"{0.20:.2f} and may not carry the component alone. The weight is redistributed "
    "across the available components, not scored as neutral"
)

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

#: Q1b. Explicit weights for the parts of the institutional leg.
#:
#: The leg used to be an unweighted mean of whichever of its parts happened to score, so
#: the news read was `1/N` of it: 17.3% of `S_S` beside three analyst parts, 69.2% on its
#: own. Since the news read is a local lexicon that measures about half the articles it is
#: given, its influence was highest exactly where analyst coverage was thinnest - which is
#: where it is least corroborated. Explicit weights fix each part's share instead.
_INSTITUTIONAL_PART_WEIGHTS: dict[str, float] = {
    "ratings": 0.35,
    "revisions": 0.25,
    "price_target": 0.15,
    "news": 0.25,
}

#: The news read is corroboration inside an analyst leg, never the leg itself, so it is
#: capped at its own nominal share. The cap pins the lexicon at 0.25 of whatever the leg
#: carries however thin analyst coverage gets - and because a capped leg needs an uncapped
#: one to absorb what re-normalization frees, a leg with no analyst part at all is n/a
#: rather than a half-measured lexicon read wearing the institutional label.
NEWS_MAX_LEG_SHARE = _INSTITUTIONAL_PART_WEIGHTS["news"]

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
    issuer_backed: bool = True,
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

    institutional = (
        _institutional_sub_score(
            analyst_signals,
            summary,
            spot=spot,
            run_date=run_date,
            max_age_days=max_age_days,
        )
        if issuer_backed
        else SubScore(
            name="institutional",
            weight=WEIGHT_INSTITUTIONAL,
            na_reason=INDEX_INSTITUTIONAL_NA_REASON,
        )
    )
    executive = _tone_sub_score(
        executive_tone,
        name="executive_tone",
        weight=WEIGHT_EXECUTIVE,
        run_date=run_date,
        max_age_days=max_age_days,
        missing_reason=EXECUTIVE_TONE_NA_REASON,
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
        if political.available and score is None:
            weights_used = dict(weights_used)
            weights_used["political_flow"] = 0.0
            diagnostics.append(
                "political_flow is a capped overlay on a base score, not a score; no base "
                "leg carried S_S, so the overlay was not applied."
            )
        elif political.available:
            adjustment = (political.score or 0.0) * POLITICAL_FLOW_MAX_IMPACT
            unclamped_score = score + adjustment
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
        measurable = [sub.name for sub in base_sub_scores if sub.available]
        if not issuer_backed:
            # A declared outcome, not a measurement failure. Saying "the only measurable
            # channel is retail_momentum" here would invite a search for the analyst data
            # that an index does not have and will never have.
            reason = INDEX_SENTIMENT_NA_REASON
        elif measurable:
            reason = (
                f"the only measurable channel is {', '.join(measurable)}, which is "
                "weight-capped and may not carry S_S alone"
            )
        else:
            reason = "no sentiment channel could be measured"
        return unavailable_component(
            component=SENTIMENT,
            ticker=clean_ticker,
            geography=geo,
            as_of=resolved_as_of,
            reason=reason,
            sub_scores=sub_scores,
            diagnostics=diagnostics,
        )

    if not executive.available:
        diagnostics.append(
            "S_S carries no transcript channel: executive_tone is permanently n/a, so "
            "the component has no first-party issuer voice and reads analyst coverage "
            "beside two proxies - a local news lexicon and an attention counter."
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
        # Completeness is judged on the legs that actually carry weight. `executive_tone`
        # is declared permanently n/a with weight 0.00 (Q1/PC3), and `political_flow` is a
        # capped overlay rather than a base leg -- counting either against completeness
        # made `S_S` structurally incapable of ever reading `verified`, for any name, on
        # any run. That is not a measurement: a name with both weighted legs scored has
        # 100% of the component's weight measured. It matters beyond cosmetics, because
        # `S_S` is in `REQUIRED_COMPONENTS` for V and E, and a component that can never be
        # verified would cap the entire universe at Tier B by construction.
        validation_status=(
            STATUS_VERIFIED
            if all(s.available for s in base_sub_scores if s.weight > 0)
            else STATUS_PARTIAL
        ),
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
    """Analyst ratings and price targets, with the news read as corroboration.

    The parts carry the explicit weights in `_INSTITUTIONAL_PART_WEIGHTS` and are combined
    by the same capped re-normalization the component's legs use, one level down. So the
    news read is 0.25 of the leg whether it sits beside three analyst parts or one, and a
    leg with no analyst part at all is `n/a` rather than a lexicon read at full weight.
    """
    fresh = [s for s in signals if not is_stale(s.as_of, run_date=run_date, max_age_days=90)]
    measured: dict[str, float] = {}
    details: list[str] = []
    latest: date_type | None = max((s.as_of for s in fresh), default=None)

    ratings = [rating_score(s.rating) for s in fresh]
    ratings = [r for r in ratings if r is not None]
    if ratings:
        measured["ratings"] = sum(ratings) / len(ratings)
        details.append(f"{len(ratings)} analyst ratings")

    revisions = [
        _revision_score(s) for s in fresh if _revision_score(s) is not None
    ]
    if revisions:
        measured["revisions"] = sum(revisions) / len(revisions)  # type: ignore[arg-type]
        details.append(f"{len(revisions)} rating or target revisions")

    upside = _price_target_upside(fresh, spot)
    if upside is not None:
        measured["price_target"] = clamp(upside / 0.25)
        details.append(f"consensus target {upside:+.1%} vs spot")

    if summary.delta is not None:
        measured["news"] = clamp(summary.delta * 2.0)
        details.append(
            f"news 24h {summary.recent_score:+.3f} vs 7d {summary.baseline_score:+.3f}"
        )
    elif summary.recent_score is not None:
        measured["news"] = clamp(summary.recent_score * 2.0)
        details.append(f"news 24h {summary.recent_score:+.3f} (no baseline yet)")

    parts = [
        SubScore(
            name=name,
            weight=weight,
            score=measured.get(name),
            na_reason=None if name in measured else f"no {name} reading in the window",
            max_weight=NEWS_MAX_LEG_SHARE if name == "news" else None,
        )
        for name, weight in _INSTITUTIONAL_PART_WEIGHTS.items()
    ]
    score, part_weights, _part_disclosures = combine_sub_scores(parts)

    if score is None:
        return SubScore(
            name="institutional",
            weight=WEIGHT_INSTITUTIONAL,
            na_reason=(
                (
                    "the news read is the only measurable part and is capped at "
                    f"{NEWS_MAX_LEG_SHARE:.2f} of the leg; a local-lexicon tone read "
                    "corroborates analyst coverage rather than standing in for it"
                )
                if measured
                else "no analyst ratings, target revisions, or scored news in the window"
            ),
            sample_size=len(signals),
            inputs={name: round(value, 4) for name, value in measured.items()},
        )

    return SubScore(
        name="institutional",
        weight=WEIGHT_INSTITUTIONAL,
        score=clamp(score),
        detail="; ".join(details),
        source="analyst coverage and news sentiment",
        as_of=latest or (summary.as_of.date() if summary.as_of else None),
        sample_size=len(fresh) + summary.unique_article_count,
        inputs={
            **{name: round(value, 4) for name, value in measured.items()},
            "part_weights_used": {
                name: round(weight, 4)
                for name, weight in part_weights.items()
                if weight > 0
            },
        },
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


#: PC2, 2026-09-03. Below this many mentions on either side of the comparison, the
#: "momentum" is one or two Reddit posts moving.
#:
#: The floor of 10 in the denominator already damps the *magnitude* of a thin reading, but
#: it cannot make it mean anything: 1 mention against 2 is a coin flip wearing a number.
#: This matters because paginating ApeWisdom (below) brings hundreds of one-mention names
#: into range, and converting an honest `n/a` into a fabricated measurement is a worse
#: outcome than the gap it closes.
RETAIL_MIN_MENTIONS = 5


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
    if isinstance(reading, RetailMomentumSnapshot) and _is_thin(reading):
        return SubScore(
            name="retail_momentum",
            weight=WEIGHT_RETAIL,
            max_weight=RETAIL_MAX_WEIGHT,
            na_reason=(
                f"retail attention is too thin to read: {reading.mentions} mentions vs "
                f"{reading.mentions_24h_ago} 24h ago, below the "
                f"{RETAIL_MIN_MENTIONS}-mention floor; a one-post swing is not momentum"
            ),
            source=reading.source,
            as_of=reading.as_of,
            sample_size=reading.mentions,
            inputs={
                "mentions": reading.mentions,
                "mentions_24h_ago": reading.mentions_24h_ago,
                "rank": reading.rank,
            },
        )
    if isinstance(reading, RetailMomentumSnapshot) and reading.mentions_24h_ago is None:
        return SubScore(
            name="retail_momentum",
            weight=WEIGHT_RETAIL,
            max_weight=RETAIL_MAX_WEIGHT,
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
        max_weight=RETAIL_MAX_WEIGHT,
    )


def _is_thin(reading: RetailMomentumSnapshot) -> bool:
    """Whether both sides of the comparison are below the mention floor."""

    prior = reading.mentions_24h_ago
    if prior is None:
        return False
    return max(reading.mentions, prior) < RETAIL_MIN_MENTIONS


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
    max_weight: float | None = None,
) -> SubScore:
    if reading is None:
        return SubScore(
            name=name, weight=weight, na_reason=missing_reason, max_weight=max_weight
        )
    if is_stale(reading.as_of, run_date=run_date, max_age_days=max_age_days):
        return SubScore(
            name=name,
            weight=weight,
            max_weight=max_weight,
            na_reason=(
                f"reading from {reading.as_of.isoformat()} is beyond the "
                f"{max_age_days}-day sentiment staleness bound"
            ),
        )
    return SubScore(
        name=name,
        weight=weight,
        max_weight=max_weight,
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
