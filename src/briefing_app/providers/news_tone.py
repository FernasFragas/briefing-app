"""Local tone scoring for article feeds that publish no sentiment score.

`S_S` reads `NewsArticle.sentiment_score`, so an article feed with no score field
contributes nothing until something fills it. Alpha Vantage was the only feed that
scored its own articles, and PA3 predicted the replacement would not: Finnhub's scored
`/news-sentiment` answered HTTP 403 on the free key (probed 2026-08-31), and Tiingo and
FMP publish articles without a score either. This module is that missing step.

It is a lexicon, not a model. That is a real limitation and the output says so — the
batch names `local tone` as its source so no reader mistakes it for a vendor's scored
feed. Three rules keep the substitute honest:

1. **An unmatched headline scores `None`, never `0.0`.** `_mean_sentiment` skips `None`
   and averages `0.0`, so a neutral zero would quietly pull a real signal toward the
   middle. An unmeasured headline is not a neutral headline — the same rule the
   components already apply to an unmeasured leg.
2. **The longest phrase wins and consumes its span.** "profit warning" is strongly
   bearish and contains "profit", which alone is mildly bullish; "strong sell"
   contains "strong". Matching the longest term at each position and never overlapping
   is what stops the shorter term from scoring the same words a second time, with the
   opposite sign.
3. **The headline outranks the summary.** Summary terms score at a fraction of their
   weight and their total is capped, so a long body can shade a headline but never
   overrule it.
"""

from __future__ import annotations

import re


#: Named in the batch source so the report distinguishes a locally derived tone from a
#: vendor's own scored feed.
TONE_SOURCE = "local tone"

#: Per-term multiplier and aggregate cap for summary text. The headline is the signal;
#: the body is context, and an article whose summary lists five risk factors under a
#: neutral headline is not a bearish article.
SUMMARY_TERM_WEIGHT = 0.4
SUMMARY_MAX_CONTRIBUTION = 0.4

_STRONG = 0.6
_MODERATE = 0.35
_MILD = 0.2

#: Terms are matched on exact word boundaries, so an inflection is a separate entry.
#: The past-tense forms are not padding: a probe of 247 real Finnhub headlines on
#: 2026-09-01 found headlines overwhelmingly written in the past tense ("Stock Tumbled
#: on Tuesday"), which a present-tense-only lexicon scored as unmeasurable.

#: Phrases that reverse the polarity of a term following them. Financial copy negates
#: rarely, but when it does it inverts the whole read: "fails to beat estimates".
_NEGATORS = frozenset(
    {"no", "not", "never", "without", "fail", "fails", "failed", "denies", "denied"}
)
_NEGATION_LOOKBACK_WORDS = 3

_TERM_WEIGHTS: dict[str, float] = {}


def _add(weight: float, terms: tuple[str, ...]) -> None:
    for term in terms:
        _TERM_WEIGHTS[term] = weight


_add(
    _STRONG,
    (
        "beats estimates",
        "beat estimates",
        "beats expectations",
        "tops estimates",
        "tops expectations",
        "raises guidance",
        "raised guidance",
        "raises outlook",
        "raises forecast",
        "boosts guidance",
        "record revenue",
        "record profit",
        "record quarter",
        "blowout quarter",
        "upgraded to buy",
        "upgrades to buy",
        "strong buy",
        "surges",
        "surged",
        "soars",
        "soared",
        "skyrockets",
        "skyrocketed",
        "wins contract",
        "awarded contract",
        "fda approval",
        "regulatory approval",
    ),
)
_add(
    -_STRONG,
    (
        "misses estimates",
        "missed estimates",
        "misses expectations",
        "cuts guidance",
        "cut guidance",
        "lowers guidance",
        "slashes guidance",
        "lowers outlook",
        "slashes outlook",
        "cuts forecast",
        "profit warning",
        "going concern",
        "plunges",
        "plunged",
        "plummets",
        "plummeted",
        "tumbles",
        "tumbled",
        "craters",
        "cratered",
        "downgraded to sell",
        "downgrades to sell",
        "strong sell",
        "bankruptcy",
        "chapter 11",
        "accounting fraud",
        "securities fraud",
        "sec investigation",
        "criminal probe",
        "class action",
        "product recall",
        "halts production",
        "trading halt",
    ),
)
_add(
    _MODERATE,
    (
        "upgrade",
        "upgraded",
        "upgrades",
        "outperform",
        "overweight",
        "outperforms",
        "buyback",
        "share repurchase",
        "raises dividend",
        "dividend increase",
        "special dividend",
        "beats",
        "exceeds",
        "new contract",
        "strategic partnership",
        "strong demand",
        "robust demand",
        "rallies",
        "rallied",
        "climbs",
        "climbed",
        "jumps",
        "jumped",
        "gains",
        "gained",
    ),
)
_add(
    -_MODERATE,
    (
        "downgrade",
        "downgraded",
        "downgrades",
        "underperform",
        "underweight",
        "lawsuit",
        "sued",
        "investigation",
        "probe",
        "subpoena",
        "antitrust",
        "layoffs",
        "job cuts",
        "restructuring",
        "misses",
        "missed",
        "warns",
        "warned",
        "warning",
        "delays",
        "delayed",
        "shortage",
        "weak demand",
        "soft demand",
        "slumps",
        "slumped",
        "slides",
        "slid",
        "declines",
        "declined",
        "falls",
        "fell",
        "drops",
        "dropped",
        "sinks",
        "sank",
        "steps down",
        "stepped down",
        "resigns",
        "resigned",
        "recall",
    ),
)
_add(
    _MILD,
    (
        "optimistic",
        "bullish",
        "growth",
        "improves",
        "improved",
        "recovery",
        "momentum",
        "rises",
        "rose",
        "higher",
        "profit",
        "beat",
        "wins",
        "approval",
        "expansion",
        "strong",
    ),
)
_add(
    -_MILD,
    (
        "concern",
        "concerns",
        "risk",
        "risks",
        "pressure",
        "slowdown",
        "bearish",
        "lower",
        "loss",
        "losses",
        "caution",
        "cautious",
        "uncertainty",
        "headwind",
        "headwinds",
        "weak",
    ),
)


#: Alternation ordered longest-first so the leftmost match at any position is the
#: longest term starting there, and `finditer` never returns overlapping spans — which
#: together give rule 2 without a second pass.
_TERM_RE = re.compile(
    r"(?<![a-z0-9])("
    + "|".join(
        re.escape(term) for term in sorted(_TERM_WEIGHTS, key=len, reverse=True)
    )
    + r")(?![a-z0-9])"
)

_WORD_RE = re.compile(r"[a-z0-9]+")
_PUNCTUATION_RE = re.compile(r"[^a-z0-9]+")


def score_article_tone(headline: str, summary: str = "") -> float | None:
    """Tone of one article in `[-1, 1]`, or `None` when nothing in it was measurable.

    The range and the label bands below match Alpha Vantage's documented scale, so a
    run that falls back from Finnhub to Alpha Vantage mid-chain does not silently
    change what a given score means.
    """

    headline_total, headline_hits = _weigh(headline)
    summary_total, summary_hits = _weigh(summary)
    if not headline_hits and not summary_hits:
        return None

    summary_contribution = summary_total * SUMMARY_TERM_WEIGHT
    summary_contribution = max(
        -SUMMARY_MAX_CONTRIBUTION, min(SUMMARY_MAX_CONTRIBUTION, summary_contribution)
    )
    total = headline_total + summary_contribution
    return round(max(-1.0, min(1.0, total)), 4)


def tone_label(score: float | None) -> str | None:
    """Alpha Vantage's five bands, so the two feeds' labels remain comparable."""

    if score is None:
        return None
    if score <= -0.35:
        return "Bearish"
    if score <= -0.15:
        return "Somewhat-Bearish"
    if score < 0.15:
        return "Neutral"
    if score < 0.35:
        return "Somewhat-Bullish"
    return "Bullish"


def _weigh(text: str) -> tuple[float, int]:
    """Summed term weights and the hit count for one block of text."""

    if not text:
        return 0.0, 0
    normalized = _PUNCTUATION_RE.sub(" ", text.lower())
    total = 0.0
    hits = 0
    for match in _TERM_RE.finditer(normalized):
        weight = _TERM_WEIGHTS[match.group(1)]
        if _is_negated(normalized, match.start()):
            weight = -weight
        total += weight
        hits += 1
    return total, hits


def _is_negated(text: str, start: int) -> bool:
    words = _WORD_RE.findall(text[:start])
    return any(word in _NEGATORS for word in words[-_NEGATION_LOOKBACK_WORDS:])
