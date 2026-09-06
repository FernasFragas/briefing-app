"""`S_S` - the sentiment matrix, its exact weights, and news deduplication.

Acceptance: the weighted score is computed exactly, a missing channel is re-normalized
away rather than scored as zero, and the same wire story counted ten times is counted
once.

Also pins the weight decisions (Q1, Q1b, Q3, PC3): `executive_tone` is permanently n/a
and now carries a declared 0.00 rather than a per-run redistribution, the news read is a
fixed 0.25 of the institutional leg however thin analyst coverage gets, re-normalization
may not promote retail past 0.20 nor let a capped leg carry `S_S` alone, and an index or
fund has no analyst leg to weight at all.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from briefing_app.components import (
    POLITICAL_FLOW_MAX_IMPACT,
    WEIGHT_EXECUTIVE,
    WEIGHT_INSTITUTIONAL,
    WEIGHT_RETAIL,
    SubScore,
    ToneReading,
    build_sentiment_component,
    canonical_url,
    combine_sub_scores,
    deduplicate_articles,
    normalize_title,
    rating_score,
    summarize_news,
)
from briefing_app.components.sentiment import (
    EXECUTIVE_TONE_NA_REASON,
    RETAIL_MIN_MENTIONS,
    FRAMEWORK_WEIGHTS,
    INDEX_INSTITUTIONAL_NA_REASON,
    INDEX_SENTIMENT_NA_REASON,
    NEWS_MAX_LEG_SHARE,
    RETAIL_MAX_WEIGHT,
)
from briefing_app.models.market_data import (
    AnalystSignal,
    NewsArticle,
    NewsSentimentBatch,
    PoliticalTrade,
    RetailMomentumSnapshot,
)

RUN_DATE = date(2026, 8, 29)
NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def article(
    title: str,
    *,
    hours_ago: float = 1.0,
    sentiment: float | None = 0.2,
    url: str | None = None,
    source: str = "Reuters",
) -> NewsArticle:
    return NewsArticle(
        ticker="NVDA",
        title=title,
        source=source,
        published_at=NOW - timedelta(hours=hours_ago),
        url=url,
        sentiment_score=sentiment,
    )


def batch(*articles: NewsArticle) -> NewsSentimentBatch:
    return NewsSentimentBatch(
        ticker="NVDA", as_of=NOW, source="Alpha Vantage NEWS_SENTIMENT", articles=list(articles)
    )


def analyst(rating: str = "Buy", **kwargs: object) -> AnalystSignal:
    """A rating with no revision and no target, so it scores the `ratings` part alone.

    Most tests below are not about the institutional leg but need it to score, because a
    news read alone no longer constitutes it (Q1b).
    """
    return AnalystSignal(
        ticker="NVDA",
        as_of=RUN_DATE,
        source="FMP grades-consensus",
        rating=rating,
        **kwargs,  # type: ignore[arg-type]
    )


# --- the weighting contract ---------------------------------------------------------


def test_all_three_channels_use_the_declared_weights_exactly() -> None:
    result = build_sentiment_component(
        ticker="NVDA",
        geography="US",
        run_date=RUN_DATE,
        news=batch(article("Only story", sentiment=0.25)),
        analyst_signals=[analyst()],
        executive_tone=ToneReading(score=0.4, source="Q2 transcript", as_of=RUN_DATE),
        retail_momentum=ToneReading(score=-0.5, source="Stocktwits", as_of=RUN_DATE),
        as_of=NOW,
    )

    institutional = result.sub_score("institutional")
    assert institutional is not None and institutional.available
    expected = (
        institutional.score * WEIGHT_INSTITUTIONAL
        + 0.4 * WEIGHT_EXECUTIVE
        + (-0.5) * WEIGHT_RETAIL
    )
    assert result.score == pytest.approx(expected)
    assert result.weights_used == pytest.approx(
        {
            "institutional": WEIGHT_INSTITUTIONAL,
            "executive_tone": WEIGHT_EXECUTIVE,
            "retail_momentum": WEIGHT_RETAIL,
        }
    )


def test_missing_channel_is_renormalized_never_scored_as_zero() -> None:
    result = build_sentiment_component(
        ticker="NVDA",
        geography="US",
        run_date=RUN_DATE,
        news=batch(article("Only story", sentiment=0.25)),
        analyst_signals=[analyst()],
        executive_tone=ToneReading(score=0.4, source="Q2 transcript", as_of=RUN_DATE),
        as_of=NOW,
    )

    institutional = result.sub_score("institutional")
    retail = result.sub_score("retail_momentum")
    assert retail is not None and retail.score is None and retail.na_reason

    # 0.45 and 0.35 re-normalize to 0.5625 / 0.4375, not to 0.45 / 0.35 with a zero leg.
    total = WEIGHT_INSTITUTIONAL + WEIGHT_EXECUTIVE
    assert result.weights_used["institutional"] == pytest.approx(WEIGHT_INSTITUTIONAL / total)
    assert result.weights_used["executive_tone"] == pytest.approx(WEIGHT_EXECUTIVE / total)
    assert result.weights_used["retail_momentum"] == 0.0
    assert result.score == pytest.approx(
        institutional.score * (WEIGHT_INSTITUTIONAL / total) + 0.4 * (WEIGHT_EXECUTIVE / total)
    )
    # A zero-weighted leg would have dragged the score toward neutral; it did not.
    assert any("re-normalized" in d for d in result.diagnostics)


def test_component_is_na_when_no_channel_can_be_measured() -> None:
    result = build_sentiment_component(
        ticker="NVDA", geography="US", run_date=RUN_DATE, as_of=NOW
    )

    assert result.available is False
    assert result.score is None
    assert result.na_reason == "no sentiment channel could be measured"
    assert all(sub.na_reason for sub in result.sub_scores)


def test_stale_tone_reading_is_dropped_with_its_reason() -> None:
    result = build_sentiment_component(
        ticker="NVDA",
        geography="US",
        run_date=RUN_DATE,
        news=batch(article("Story", sentiment=0.1)),
        analyst_signals=[analyst()],
        retail_momentum=ToneReading(
            score=0.9, source="Stocktwits", as_of=date(2026, 8, 1)
        ),
        as_of=NOW,
    )

    retail = result.sub_score("retail_momentum")
    assert retail is not None and retail.score is None
    assert "staleness bound" in (retail.na_reason or "")


def test_retail_momentum_snapshot_scores_attention_delta() -> None:
    result = build_sentiment_component(
        ticker="NVDA",
        geography="US",
        run_date=RUN_DATE,
        news=batch(article("Story", sentiment=0.25)),
        analyst_signals=[analyst()],
        retail_momentum=RetailMomentumSnapshot(
            ticker="NVDA",
            as_of=RUN_DATE,
            source="ApeWisdom all-stocks",
            mentions=254,
            mentions_24h_ago=56,
            upvotes=679,
            rank=1,
            rank_24h_ago=3,
        ),
        as_of=NOW,
    )

    retail = result.sub_score("retail_momentum")
    assert retail is not None and retail.score == pytest.approx((254 - 56) / 254)
    assert retail.source == "ApeWisdom all-stocks"
    assert "attention, not sentiment" in (retail.detail or "")
    # Q3: 0.45 / 0.20 would re-normalize retail to 0.308. It is held at its nominal
    # 0.20 and the institutional leg absorbs the rest.
    assert result.weights_used["retail_momentum"] == pytest.approx(RETAIL_MAX_WEIGHT)
    assert result.weights_used["institutional"] == pytest.approx(1.0 - RETAIL_MAX_WEIGHT)


def test_retail_attention_level_without_delta_is_not_scored_as_momentum() -> None:
    result = build_sentiment_component(
        ticker="NVDA",
        geography="US",
        run_date=RUN_DATE,
        news=batch(article("Story", sentiment=0.25)),
        analyst_signals=[analyst()],
        retail_momentum=RetailMomentumSnapshot(
            ticker="NVDA",
            as_of=RUN_DATE,
            source="ApeWisdom all-stocks",
            mentions=254,
        ),
        as_of=NOW,
    )

    retail = result.sub_score("retail_momentum")
    assert retail is not None and retail.score is None
    assert "attention level alone is not momentum" in (retail.na_reason or "")
    assert result.weights_used["retail_momentum"] == 0.0


# --- the four weight decisions ------------------------------------------------------


def test_executive_tone_is_recorded_permanently_na_and_redistributed() -> None:
    """Q1. The leg is a decision, not a gap, and the run says what that costs."""
    result = build_sentiment_component(
        ticker="NVDA",
        geography="US",
        run_date=RUN_DATE,
        news=batch(article("Story", sentiment=0.25)),
        analyst_signals=[analyst()],
        retail_momentum=ToneReading(score=0.4, source="ApeWisdom", as_of=RUN_DATE),
        as_of=NOW,
    )

    executive = result.sub_score("executive_tone")
    assert executive is not None and executive.score is None
    assert executive.na_reason == EXECUTIVE_TONE_NA_REASON
    assert "permanently n/a" in EXECUTIVE_TONE_NA_REASON
    # Redistributed, not scored as neutral and not shrinking the component's confidence.
    assert result.weights_used["executive_tone"] == 0.0
    assert result.score is not None
    assert sum(result.weights_used[name] for name in ("institutional", "retail_momentum")) == (
        pytest.approx(1.0)
    )
    assert any("no transcript channel" in item for item in result.diagnostics)


def test_news_holds_a_fixed_share_of_the_institutional_leg() -> None:
    """Q1b. 0.25 of the leg beside three analyst parts and beside one."""
    full = build_sentiment_component(
        ticker="NVDA",
        geography="US",
        run_date=RUN_DATE,
        news=batch(article("Story", sentiment=0.25)),
        analyst_signals=[
            analyst(previous_rating="Hold", price_target=230.0, previous_price_target=190.0)
        ],
        spot=180.0,
        as_of=NOW,
    )
    thin = build_sentiment_component(
        ticker="NVDA",
        geography="US",
        run_date=RUN_DATE,
        news=batch(article("Story", sentiment=0.25)),
        analyst_signals=[analyst()],
        as_of=NOW,
    )

    full_leg = full.sub_score("institutional")
    thin_leg = thin.sub_score("institutional")
    assert full_leg is not None and thin_leg is not None
    assert set(full_leg.inputs["part_weights_used"]) == {
        "ratings",
        "revisions",
        "price_target",
        "news",
    }
    assert set(thin_leg.inputs["part_weights_used"]) == {"ratings", "news"}
    # An unweighted mean gave news 1/4 of the leg here and 1/2 there; a plain
    # re-normalization over 0.35 and 0.25 would give it 0.4167.
    assert full_leg.inputs["part_weights_used"]["news"] == pytest.approx(NEWS_MAX_LEG_SHARE)
    assert thin_leg.inputs["part_weights_used"]["news"] == pytest.approx(NEWS_MAX_LEG_SHARE)
    assert thin_leg.inputs["part_weights_used"]["ratings"] == pytest.approx(
        1.0 - NEWS_MAX_LEG_SHARE
    )


def test_news_alone_does_not_constitute_the_institutional_leg() -> None:
    """Q1b. Where analyst coverage is thinnest the lexicon is least corroborated."""
    result = build_sentiment_component(
        ticker="NVDA",
        geography="US",
        run_date=RUN_DATE,
        news=batch(article("Story", sentiment=0.25)),
        retail_momentum=ToneReading(score=0.4, source="ApeWisdom", as_of=RUN_DATE),
        as_of=NOW,
    )

    institutional = result.sub_score("institutional")
    assert institutional is not None and institutional.score is None
    assert "capped" in (institutional.na_reason or "")
    assert institutional.inputs["news"] == pytest.approx(0.5)
    # Retail is the only channel left, and it may not carry S_S on its own either.
    assert result.available is False
    assert "weight-capped" in (result.na_reason or "")


def test_retail_is_capped_at_its_nominal_weight_when_executive_tone_is_absent() -> None:
    """Q3, as re-stated by PC3. Retail stays at 0.20; it is now there by construction.

    Under the framework's `0.45 / 0.35 / 0.20`, dropping `executive_tone` re-normalized
    retail to 0.308 and the cap pulled it back to 0.20. The shipped table declares
    `0.80 / 0.00 / 0.20` instead, so retail is already at its nominal weight and the cap
    has nothing to pull back - which is why no ceiling disclosure is emitted here any
    more. The guarantee is unchanged and the numbers are identical; only the mechanism
    that produces them moved from runtime re-normalization to the printed weights.
    `test_retail_alone_cannot_carry_the_component` covers the case where the cap still
    binds.
    """
    result = build_sentiment_component(
        ticker="NVDA",
        geography="US",
        run_date=RUN_DATE,
        news=batch(article("Story", sentiment=0.25)),
        analyst_signals=[analyst()],
        retail_momentum=RetailMomentumSnapshot(
            ticker="NVDA",
            as_of=RUN_DATE,
            source="ApeWisdom all-stocks",
            mentions=10,
            mentions_24h_ago=0,
        ),
        as_of=NOW,
    )

    retail = result.sub_score("retail_momentum")
    institutional = result.sub_score("institutional")
    assert retail is not None and institutional is not None
    # Ten mentions from a standing start still score maximum bullish - which is exactly
    # why the leg's share may not grow when a better one goes missing.
    assert retail.score == pytest.approx(1.0)
    assert result.weights_used["retail_momentum"] == pytest.approx(WEIGHT_RETAIL)
    assert result.weights_used["institutional"] == pytest.approx(1.0 - WEIGHT_RETAIL)
    assert result.score == pytest.approx(
        institutional.score * (1.0 - WEIGHT_RETAIL) + 1.0 * WEIGHT_RETAIL
    )
    # The invariant Q3 exists to protect, asserted directly rather than through the
    # disclosure that used to announce it: retail never exceeds its nominal share.
    assert result.weights_used["retail_momentum"] <= WEIGHT_RETAIL + 1e-9
    assert not any("ceiling" in item for item in result.diagnostics)
    # The dropped leg is still reported, with its reason - a 0.00 weight is a recorded
    # decision, not a deletion.
    executive = result.sub_score("executive_tone")
    assert executive is not None and executive.available is False
    assert "permanently n/a" in (executive.na_reason or "")


def test_retail_alone_cannot_carry_the_component() -> None:
    """Q3. Retail is the 20 percent leg and never the thesis, including when alone."""
    result = build_sentiment_component(
        ticker="NVDA",
        geography="US",
        run_date=RUN_DATE,
        retail_momentum=ToneReading(score=0.9, source="ApeWisdom", as_of=RUN_DATE),
        as_of=NOW,
    )

    retail = result.sub_score("retail_momentum")
    assert retail is not None and retail.score == pytest.approx(0.9)
    assert result.available is False
    assert result.score is None
    assert "retail_momentum" in (result.na_reason or "")
    assert any("Every measurable leg is weight-capped" in i for i in result.diagnostics)


def test_political_overlay_is_not_applied_without_a_base_score() -> None:
    """The overlay adjusts a score; it never becomes one."""
    result = build_sentiment_component(
        ticker="NVDA",
        geography="US",
        run_date=RUN_DATE,
        political_flow=[
            PoliticalTrade(
                ticker="NVDA",
                chamber="senate",
                politician="Example Senator",
                transaction_type="Purchase",
                transaction_date=RUN_DATE - timedelta(days=2),
                disclosure_date=RUN_DATE - timedelta(days=1),
                amount_min=100001,
                amount_max=250000,
                source="FMP senate-latest",
            )
        ],
        as_of=NOW,
    )

    assert result.available is False
    assert result.score is None


# --- the weight ceiling itself ------------------------------------------------------


def test_capped_leg_is_held_at_its_ceiling_and_the_rest_absorbs_the_excess() -> None:
    score, weights, disclosures = combine_sub_scores(
        [
            SubScore(name="major", weight=0.45, score=1.0),
            SubScore(name="minor", weight=0.20, score=-1.0, max_weight=0.20),
        ]
    )

    assert weights == pytest.approx({"major": 0.80, "minor": 0.20})
    assert score == pytest.approx(0.80 - 0.20)
    assert any("above its 0.20 ceiling" in item for item in disclosures)


def test_a_ceiling_reached_only_by_absorbing_another_leg_still_binds() -> None:
    """Absorbing a capped leg's excess can push an absorber past its own ceiling."""
    score, weights, _ = combine_sub_scores(
        [
            SubScore(name="major", weight=0.50, score=1.0, max_weight=0.55),
            SubScore(name="mid", weight=0.30, score=1.0),
            SubScore(name="minor", weight=0.20, score=1.0, max_weight=0.10),
        ]
    )

    # minor 0.20 -> 0.10 lifts major to 0.5625, over its own 0.55, so it caps in turn and
    # the only uncapped leg takes what is left.
    assert weights == pytest.approx({"major": 0.55, "mid": 0.35, "minor": 0.10})
    assert score == pytest.approx(1.0)


def test_a_component_of_nothing_but_capped_legs_is_na() -> None:
    score, weights, disclosures = combine_sub_scores(
        [
            SubScore(name="major", weight=0.45, na_reason="no source"),
            SubScore(name="minor", weight=0.20, score=0.9, max_weight=0.20),
        ]
    )

    assert score is None
    assert weights == {"major": 0.0, "minor": 0.0}
    assert any("Every measurable leg is weight-capped" in i for i in disclosures)


def test_political_flow_applies_capped_overlay_without_reweighting_base_legs() -> None:
    result = build_sentiment_component(
        ticker="NVDA",
        geography="US",
        run_date=RUN_DATE,
        news=batch(article("Story", sentiment=0.25)),
        analyst_signals=[analyst()],
        political_flow=[
            PoliticalTrade(
                ticker="NVDA",
                chamber="senate",
                politician="Example Senator",
                politician_id="S000001",
                transaction_type="Purchase",
                transaction_date=RUN_DATE - timedelta(days=2),
                disclosure_date=RUN_DATE - timedelta(days=1),
                amount_range="$100,001 - $250,000",
                amount_min=100001,
                amount_max=250000,
                source="FMP senate-latest",
                source_url="https://efdsearch.senate.gov/search/view/ptr/example",
            )
        ],
        as_of=NOW,
    )

    institutional = result.sub_score("institutional")
    political = result.sub_score("political_flow")
    assert institutional is not None and institutional.score is not None
    assert political is not None and political.score == pytest.approx(1.0)
    assert result.weights_used["institutional"] == pytest.approx(1.0)
    assert result.weights_used["political_flow"] == pytest.approx(POLITICAL_FLOW_MAX_IMPACT)
    assert result.score == pytest.approx(institutional.score + POLITICAL_FLOW_MAX_IMPACT)
    fields = {row["field_name"] for row in result.evidence_rows}
    assert {"political_flow_adjustment", "political_flow_trade"} <= fields


def test_configured_political_flow_without_matching_trades_is_na() -> None:
    result = build_sentiment_component(
        ticker="NVDA",
        geography="US",
        run_date=RUN_DATE,
        news=batch(article("Story", sentiment=0.25)),
        analyst_signals=[analyst()],
        political_flow=[],
        as_of=NOW,
    )

    institutional = result.sub_score("institutional")
    political = result.sub_score("political_flow")
    assert institutional is not None and institutional.score is not None
    assert political is not None and political.score is None
    assert result.weights_used["political_flow"] == 0.0
    assert result.score == pytest.approx(institutional.score)
    assert any("political_flow is n/a" in item for item in result.diagnostics)


# --- news deduplication and the 24h / 7d read ---------------------------------------


def test_titles_and_urls_normalize_for_deduplication() -> None:
    assert normalize_title("NVIDIA lands major deal!") == normalize_title(
        "  Nvidia lands  major deal  "
    )
    assert canonical_url("https://www.reuters.com/a/?utm_source=x") == "reuters.com/a"
    assert canonical_url("https://reuters.com/a") == "reuters.com/a"
    assert canonical_url(None) is None


def test_syndicated_copies_are_counted_once() -> None:
    articles = [
        article("Nvidia lands major deal", url="https://reuters.com/a", hours_ago=3),
        article("NVIDIA lands major deal!", url="https://syndicated.test/b", hours_ago=2),
        article("Nvidia lands major deal", url="https://reuters.com/a?utm=x", hours_ago=1),
        article("Different story entirely", url="https://wsj.com/c", hours_ago=1),
    ]
    unique = deduplicate_articles(articles)
    assert len(unique) == 2


def test_news_summary_reports_24h_baseline_delta_and_headlines() -> None:
    summary = summarize_news(
        batch(
            article("Fresh one", hours_ago=2, sentiment=0.6, url="https://a.test/1"),
            article("Fresh two", hours_ago=5, sentiment=0.4, url="https://a.test/2"),
            article("Older one", hours_ago=72, sentiment=0.1, url="https://a.test/3"),
            article("Older two", hours_ago=100, sentiment=-0.1, url="https://a.test/4"),
        ),
        now=NOW,
    )

    assert summary.article_count == 4
    assert summary.recent_count == 2 and summary.baseline_count == 2
    assert summary.recent_score == pytest.approx(0.5)
    assert summary.baseline_score == pytest.approx(0.0)
    assert summary.delta == pytest.approx(0.5)
    assert len(summary.top_headlines) == 4
    assert summary.top_headlines[0]["title"] == "Fresh one"


def test_baseline_absent_reports_no_delta_rather_than_zero() -> None:
    summary = summarize_news(batch(article("Only fresh", hours_ago=1, sentiment=0.3)), now=NOW)
    assert summary.recent_score == pytest.approx(0.3)
    assert summary.baseline_score is None
    assert summary.delta is None


def test_articles_without_scores_do_not_average_to_zero() -> None:
    summary = summarize_news(
        batch(article("Unscored", hours_ago=1, sentiment=None, url="https://a.test/1")),
        now=NOW,
    )
    assert summary.recent_count == 1
    assert summary.recent_score is None


# --- the institutional leg ----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Strong Buy", 1.0),
        ("Outperform", 0.6),
        ("Hold", 0.0),
        ("Underweight", -0.6),
        ("Sell", -1.0),
        ("Not a rating", None),
        (None, None),
    ],
)
def test_rating_text_maps_to_a_score(text: str | None, expected: float | None) -> None:
    assert rating_score(text) == expected


def test_upgrade_and_raised_target_read_bullish() -> None:
    result = build_sentiment_component(
        ticker="NVDA",
        geography="US",
        run_date=RUN_DATE,
        analyst_signals=[
            AnalystSignal(
                ticker="NVDA",
                as_of=date(2026, 8, 25),
                source="FMP",
                rating="Buy",
                previous_rating="Hold",
                price_target=230.0,
                previous_price_target=190.0,
            )
        ],
        spot=180.0,
        as_of=NOW,
    )

    institutional = result.sub_score("institutional")
    assert institutional is not None and institutional.score is not None
    assert institutional.score > 0
    assert institutional.sample_size >= 1


def test_source_rows_and_evidence_carry_as_of_dates() -> None:
    result = build_sentiment_component(
        ticker="NVDA",
        geography="US",
        run_date=RUN_DATE,
        news=batch(article("Story", sentiment=0.2, url="https://a.test/1")),
        analyst_signals=[analyst()],
        as_of=NOW,
    )

    assert result.source_rows, "top headlines are the source rows for S_S"
    assert all("published_at" in row for row in result.source_rows)
    fields = {row["field_name"] for row in result.evidence_rows}
    assert {"news_article_count", "news_score_24h", "s_s"} <= fields
    assert all(row["as_of"] is not None for row in result.evidence_rows)
    assert all(row["component"] == "S_S" for row in result.evidence_rows)


# --- PC3: the shipped weight table, and the leg an index does not have -----------------


def test_the_shipped_weights_are_the_ones_the_score_uses() -> None:
    """PC3. The printed table used to describe a component that did not exist.

    The framework specifies `0.45 / 0.35 / 0.20`, but `executive_tone` has never had a
    source and never will on a free tier, so every run re-normalized it away and scored
    `0.80 / - / 0.20`. Dropping the weight of a structurally absent leg is exactly what
    PC3 asks for: the table now says what the arithmetic does.
    """

    assert FRAMEWORK_WEIGHTS == {
        "institutional": 0.45,
        "executive_tone": 0.35,
        "retail_momentum": 0.20,
    }
    assert WEIGHT_EXECUTIVE == 0.0
    assert WEIGHT_INSTITUTIONAL + WEIGHT_RETAIL == pytest.approx(1.0)
    # The dropped 0.35 went to the institutional leg, which is where re-normalization was
    # sending it anyway under the retail cap.
    assert WEIGHT_INSTITUTIONAL == pytest.approx(
        FRAMEWORK_WEIGHTS["institutional"] + FRAMEWORK_WEIGHTS["executive_tone"]
    )


def test_restating_the_weights_changed_no_score() -> None:
    """The whole claim of the PC3 change: identical arithmetic, honest table."""

    result = build_sentiment_component(
        ticker="NVDA",
        geography="US",
        run_date=RUN_DATE,
        news=batch(article("Story", sentiment=0.4)),
        analyst_signals=[analyst()],
        retail_momentum=ToneReading(score=0.5, source="ApeWisdom", as_of=RUN_DATE),
        as_of=NOW,
    )

    institutional = result.sub_score("institutional")
    assert institutional is not None and institutional.score is not None
    # What the pre-PC3 code produced, by re-normalizing 0.45/0.20 under the retail cap.
    assert result.score == pytest.approx(institutional.score * 0.80 + 0.5 * 0.20)
    assert result.weights_used["institutional"] == pytest.approx(0.80)
    assert result.weights_used["retail_momentum"] == pytest.approx(0.20)


def test_a_zero_weight_leg_is_reported_without_claiming_a_renormalization() -> None:
    result = build_sentiment_component(
        ticker="NVDA",
        geography="US",
        run_date=RUN_DATE,
        news=batch(article("Story", sentiment=0.4)),
        analyst_signals=[analyst()],
        as_of=NOW,
    )

    executive = result.sub_score("executive_tone")
    assert executive is not None and executive.weight == 0.0
    assert executive.na_reason == EXECUTIVE_TONE_NA_REASON
    disclosure = next(d for d in result.diagnostics if d.startswith("executive_tone is n/a"))
    assert disclosure.endswith("it carries no weight, so nothing was re-normalized.")
    # The old wording claimed arithmetic that no longer happens.
    assert "weight was dropped and the remainder re-normalized" not in disclosure


def test_an_index_candidate_has_no_analyst_leg_at_all() -> None:
    """PC3. Three providers returned nothing for QQQ and SPY, and all three were right.

    An index has no issuer, so nothing publishes ratings about it. Handing the component
    analyst signals anyway must not resurrect a leg the instrument cannot have.
    """

    result = build_sentiment_component(
        ticker="SPY",
        geography="US",
        run_date=RUN_DATE,
        issuer_backed=False,
        news=batch(article("Index story", sentiment=0.4)),
        analyst_signals=[analyst()],
        retail_momentum=ToneReading(score=0.9, source="ApeWisdom", as_of=RUN_DATE),
        as_of=NOW,
    )

    institutional = result.sub_score("institutional")
    assert institutional is not None
    assert institutional.available is False
    assert institutional.na_reason == INDEX_INSTITUTIONAL_NA_REASON

    # Retail is all that is left, and Q3 forbids it from carrying the component alone.
    assert result.available is False
    assert result.na_reason == INDEX_SENTIMENT_NA_REASON
    assert "structurally n/a" in (result.na_reason or "")
    # The reason must not invite a search for data that does not exist.
    assert "weight-capped and may not carry S_S alone" not in (result.na_reason or "")


def test_an_issuer_with_no_coverage_still_reads_as_a_measurement_gap() -> None:
    """The index reason is reserved for indices; a thin issuer is a different thing."""

    result = build_sentiment_component(
        ticker="CRWV",
        geography="US",
        run_date=RUN_DATE,
        retail_momentum=ToneReading(score=0.9, source="ApeWisdom", as_of=RUN_DATE),
        as_of=NOW,
    )

    assert result.available is False
    assert "weight-capped" in (result.na_reason or "")
    assert result.na_reason != INDEX_SENTIMENT_NA_REASON


# --- PC2: paginating ApeWisdom brought one-mention names into range --------------------


def test_a_one_mention_swing_is_recorded_as_too_thin_to_read() -> None:
    """PC2. Reading the whole feed must not manufacture readings out of noise.

    COST, DE, JPM, LMT and XOM were all on ApeWisdom pages 2-3 on 2026-09-03 - with one
    mention each. Scoring that would replace an honest `n/a` with a coin flip wearing a
    number, which is a worse outcome than the gap it closes.
    """

    result = build_sentiment_component(
        ticker="COST",
        geography="US",
        run_date=RUN_DATE,
        news=batch(article("Story", sentiment=0.4)),
        analyst_signals=[analyst()],
        retail_momentum=RetailMomentumSnapshot(
            ticker="COST",
            as_of=RUN_DATE,
            source="ApeWisdom all-stocks",
            mentions=1,
            mentions_24h_ago=2,
            rank=184,
        ),
        as_of=NOW,
    )

    retail = result.sub_score("retail_momentum")
    assert retail is not None
    assert retail.available is False
    assert "too thin to read" in (retail.na_reason or "")
    assert f"{RETAIL_MIN_MENTIONS}-mention floor" in (retail.na_reason or "")
    # The component still scores; it just scores without a leg it cannot measure.
    assert result.available is True
    assert result.weights_used["retail_momentum"] == 0.0


def test_a_name_at_the_floor_still_reads() -> None:
    """The floor screens noise, not modest attention."""

    result = build_sentiment_component(
        ticker="DE",
        geography="US",
        run_date=RUN_DATE,
        news=batch(article("Story", sentiment=0.4)),
        analyst_signals=[analyst()],
        retail_momentum=RetailMomentumSnapshot(
            ticker="DE",
            as_of=RUN_DATE,
            source="ApeWisdom all-stocks",
            mentions=RETAIL_MIN_MENTIONS,
            mentions_24h_ago=1,
            rank=120,
        ),
        as_of=NOW,
    )

    retail = result.sub_score("retail_momentum")
    assert retail is not None and retail.available is True
    assert result.weights_used["retail_momentum"] == pytest.approx(WEIGHT_RETAIL)
