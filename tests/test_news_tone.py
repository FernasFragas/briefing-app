"""The lexicon that stands in for a vendor's sentiment score.

Finnhub's scored feed is 403 on the free tier, so `S_S` reads a locally derived tone
instead. These tests pin the four rules that keep that substitution from quietly
changing what a score means.
"""

from __future__ import annotations

import pytest

from briefing_app.providers.news_tone import (
    SUMMARY_MAX_CONTRIBUTION,
    score_article_tone,
    tone_label,
)


def test_an_unmeasurable_headline_scores_none_not_zero() -> None:
    """Zero is a reading. None is the absence of one, and the component skips it."""

    assert score_article_tone("Nvidia to present at a conference on Thursday") is None
    assert score_article_tone("") is None


def test_the_longest_phrase_wins_over_a_term_inside_it() -> None:
    """"profit warning" is bearish and contains "profit", which alone is bullish."""

    assert score_article_tone("Profit rises on strong demand") > 0
    assert score_article_tone("Issues profit warning") <= -0.35
    assert score_article_tone("Downgraded to strong sell") <= -0.35


def test_negation_inverts_the_term_it_governs() -> None:
    assert score_article_tone("Chipmaker beats estimates") > 0
    assert score_article_tone("Chipmaker fails to beat estimates") < 0


def test_the_summary_shades_a_headline_but_cannot_overrule_it() -> None:
    headline = "Chipmaker beats estimates and raises guidance"
    bearish_body = (
        "The filing lists a lawsuit, an investigation, layoffs, weak demand, "
        "a shortage and a recall among its risks."
    )

    with_body = score_article_tone(headline, bearish_body)
    without_body = score_article_tone(headline)

    assert with_body < without_body, "a negative body should pull the score down"
    assert with_body > 0, "a bearish body must not flip a strongly bullish headline"
    assert without_body - with_body <= SUMMARY_MAX_CONTRIBUTION + 1e-9


def test_a_summary_alone_still_scores_when_the_headline_is_neutral() -> None:
    score = score_article_tone("Company files quarterly report", "Revenue beats estimates.")
    assert score is not None and score > 0


def test_scores_stay_inside_the_alpha_vantage_range() -> None:
    piled_on = "Bankruptcy, accounting fraud, sec investigation, profit warning, plunges"
    assert score_article_tone(piled_on) == -1.0
    assert score_article_tone("Surges, soars, record profit, beats estimates") == 1.0


@pytest.mark.parametrize(
    "score,label",
    [
        (None, None),
        (-0.6, "Bearish"),
        (-0.35, "Bearish"),
        (-0.2, "Somewhat-Bearish"),
        (0.0, "Neutral"),
        (0.2, "Somewhat-Bullish"),
        (0.35, "Bullish"),
        (0.9, "Bullish"),
    ],
)
def test_labels_use_alpha_vantage_bands_so_a_chain_fallback_stays_comparable(
    score: float | None, label: str | None
) -> None:
    assert tone_label(score) == label


def test_past_tense_headlines_score_because_real_headlines_are_written_that_way() -> None:
    """A probe of 247 live Finnhub headlines found the past tense dominant.

    A present-tense-only lexicon read "Stock Tumbled on Tuesday" as unmeasurable, which
    is the quietest way to lose a signal: it looks like a thin news day, not a gap.
    """

    for headline in (
        "Nvidia stock tumbled on Tuesday",
        "Shares surged after the print",
        "Chipmaker missed estimates",
        "Chief executive resigned",
        "Nasdaq jumped 400 points",
    ):
        assert score_article_tone(headline) is not None, headline
