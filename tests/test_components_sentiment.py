"""`S_S` - the sentiment matrix, its exact weights, and news deduplication.

Acceptance: the weighted score is computed exactly (45/35/20), a missing channel is
re-normalized away rather than scored as zero, and the same wire story counted ten times
is counted once.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from briefing_app.components import (
    POLITICAL_FLOW_MAX_IMPACT,
    WEIGHT_EXECUTIVE,
    WEIGHT_INSTITUTIONAL,
    WEIGHT_RETAIL,
    ToneReading,
    build_sentiment_component,
    canonical_url,
    deduplicate_articles,
    normalize_title,
    rating_score,
    summarize_news,
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


# --- the weighting contract ---------------------------------------------------------


def test_all_three_channels_use_the_declared_weights_exactly() -> None:
    result = build_sentiment_component(
        ticker="NVDA",
        geography="US",
        run_date=RUN_DATE,
        news=batch(article("Only story", sentiment=0.25)),
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
    total = WEIGHT_INSTITUTIONAL + WEIGHT_RETAIL
    assert result.weights_used["retail_momentum"] == pytest.approx(WEIGHT_RETAIL / total)


def test_retail_attention_level_without_delta_is_not_scored_as_momentum() -> None:
    result = build_sentiment_component(
        ticker="NVDA",
        geography="US",
        run_date=RUN_DATE,
        news=batch(article("Story", sentiment=0.25)),
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


def test_political_flow_applies_capped_overlay_without_reweighting_base_legs() -> None:
    result = build_sentiment_component(
        ticker="NVDA",
        geography="US",
        run_date=RUN_DATE,
        news=batch(article("Story", sentiment=0.25)),
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
    assert institutional is not None and institutional.score == pytest.approx(0.5)
    assert political is not None and political.score == pytest.approx(1.0)
    assert result.weights_used["institutional"] == pytest.approx(1.0)
    assert result.weights_used["political_flow"] == pytest.approx(POLITICAL_FLOW_MAX_IMPACT)
    assert result.score == pytest.approx(0.5 + POLITICAL_FLOW_MAX_IMPACT)
    fields = {row["field_name"] for row in result.evidence_rows}
    assert {"political_flow_adjustment", "political_flow_trade"} <= fields


def test_configured_political_flow_without_matching_trades_is_na() -> None:
    result = build_sentiment_component(
        ticker="NVDA",
        geography="US",
        run_date=RUN_DATE,
        news=batch(article("Story", sentiment=0.25)),
        political_flow=[],
        as_of=NOW,
    )

    political = result.sub_score("political_flow")
    assert political is not None and political.score is None
    assert result.weights_used["political_flow"] == 0.0
    assert result.score == pytest.approx(0.5)
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
        as_of=NOW,
    )

    assert result.source_rows, "top headlines are the source rows for S_S"
    assert all("published_at" in row for row in result.source_rows)
    fields = {row["field_name"] for row in result.evidence_rows}
    assert {"news_article_count", "news_score_24h", "s_s"} <= fields
    assert all(row["as_of"] is not None for row in result.evidence_rows)
    assert all(row["component"] == "S_S" for row in result.evidence_rows)
