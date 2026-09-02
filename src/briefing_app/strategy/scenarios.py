"""Scenario probability table.

Bands come from the measured-sigma range (real closes, T5), because that is the range
the invalidation and the calibration scorecard are both cut from. Probabilities come
from the implied distribution when a verified chain supports one, with the measured
lognormal branch computed alongside it so the two can be compared rather than one
silently standing in for the other.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import erf, log, sqrt
from typing import Any, Sequence

from briefing_app.options_math import (
    ImpliedDistribution,
    MeasuredSigmaRange,
    probability_below,
)

#: Implied and measured probabilities this far apart on one band are worth printing.
#:
#: Raised 0.10 -> 0.20 on 2026-08-31. A variance risk premium is normal, not a defect:
#: implied vol routinely runs ~1.3x trailing realized, and on the cached CBOE SPY chain
#: that alone produced a within-1-sigma gap of 0.117 (implied 0.566 vs measured 0.683) at
#: 8 DTE. At 0.10 the flag fired on ordinary VRP, so it fired on nearly every real row -
#: and a warning that is always on carries no information. 0.20 corresponds to implied
#: vol around 1.55x realized, which is genuinely worth a reader's attention.
DIVERGENCE_THRESHOLD: float = 0.20

#: Below this captured mass the fitted chain covers too little of the distribution for
#: its tail probabilities to be trusted, so the measured branch leads instead.
MIN_CAPTURED_MASS: float = 0.90


@dataclass(frozen=True)
class ScenarioRow:
    """One price band, its probability, and where that probability came from."""

    label: str
    lower: float | None
    upper: float | None
    probability: float
    implied_probability: float | None
    measured_probability: float | None
    source: str

    @property
    def divergence(self) -> float | None:
        if self.implied_probability is None or self.measured_probability is None:
            return None
        return self.implied_probability - self.measured_probability

    @property
    def diverges(self) -> bool:
        divergence = self.divergence
        return divergence is not None and abs(divergence) >= DIVERGENCE_THRESHOLD

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "lower": self.lower,
            "upper": self.upper,
            "probability": self.probability,
            "implied_probability": self.implied_probability,
            "measured_probability": self.measured_probability,
            "source": self.source,
            "divergence": self.divergence,
        }


@dataclass(frozen=True)
class ScenarioTable:
    """The full band table for one ticker over one horizon."""

    ticker: str
    spot: float
    horizon_days: int
    rows: tuple[ScenarioRow, ...]
    source: str
    diagnostics: tuple[str, ...] = ()

    @property
    def probability_in_one_sigma(self) -> float:
        return sum(row.probability for row in self.rows if row.label == "within 1 sigma")

    @property
    def probability_above_one_sigma(self) -> float:
        return sum(
            row.probability
            for row in self.rows
            if row.label in ("1 to 2 sigma up", "above 2 sigma")
        )

    @property
    def probability_below_one_sigma(self) -> float:
        return sum(
            row.probability
            for row in self.rows
            if row.label in ("1 to 2 sigma down", "below 2 sigma")
        )

    @property
    def diverging_rows(self) -> tuple[ScenarioRow, ...]:
        return tuple(row for row in self.rows if row.diverges)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "spot": self.spot,
            "horizon_days": self.horizon_days,
            "source": self.source,
            "rows": [row.to_dict() for row in self.rows],
            "probability_in_one_sigma": self.probability_in_one_sigma,
            "probability_above_one_sigma": self.probability_above_one_sigma,
            "probability_below_one_sigma": self.probability_below_one_sigma,
            "diagnostics": list(self.diagnostics),
        }

    def probabilities(self) -> dict[str, float]:
        """Flat label -> probability map, for the `setup_signal` JSON column."""
        return {row.label: row.probability for row in self.rows}


def build_scenario_table(
    *,
    ticker: str,
    measured_range: MeasuredSigmaRange,
    spot: float | None = None,
    distribution: ImpliedDistribution | None = None,
    horizon_days: int | None = None,
) -> ScenarioTable:
    """Five bands cut at the +/-1 and +/-2 sigma edges of the measured range."""

    reference_spot = float(spot if spot is not None else measured_range.midpoint)
    boundaries = (
        measured_range.two_sigma.low,
        measured_range.one_sigma.low,
        measured_range.one_sigma.high,
        measured_range.two_sigma.high,
    )
    labels = (
        "below 2 sigma",
        "1 to 2 sigma down",
        "within 1 sigma",
        "1 to 2 sigma up",
        "above 2 sigma",
    )

    diagnostics: list[str] = []
    measured_cdfs = _measured_cdfs(reference_spot, measured_range.adjusted_sigma_pct, boundaries)

    implied_cdfs: tuple[float, ...] | None = None
    if distribution is not None:
        if distribution.captured_probability_mass < MIN_CAPTURED_MASS:
            diagnostics.append(
                f"implied distribution captured only "
                f"{distribution.captured_probability_mass:.1%} of the probability mass; "
                "measured-sigma branch leads"
            )
        else:
            implied_cdfs = tuple(probability_below(distribution, level) for level in boundaries)
            outside = [
                level
                for level in boundaries
                if (distribution.strike_low is not None and level < distribution.strike_low)
                or (distribution.strike_high is not None and level > distribution.strike_high)
            ]
            if outside:
                diagnostics.append(
                    "band edges "
                    + ", ".join(f"{level:.2f}" for level in outside)
                    + " fall outside the fitted strike range; those tails are extrapolated"
                )

    source = "implied_distribution" if implied_cdfs is not None else "measured_sigma"
    measured_bands = _bands_from_cdfs(measured_cdfs)
    implied_bands = _bands_from_cdfs(implied_cdfs) if implied_cdfs is not None else None

    rows: list[ScenarioRow] = []
    for index, label in enumerate(labels):
        implied = implied_bands[index] if implied_bands is not None else None
        measured = measured_bands[index]
        rows.append(
            ScenarioRow(
                label=label,
                lower=boundaries[index - 1] if index > 0 else None,
                upper=boundaries[index] if index < len(boundaries) else None,
                probability=implied if implied is not None else measured,
                implied_probability=implied,
                measured_probability=measured,
                source=source,
            )
        )

    return ScenarioTable(
        ticker=ticker.strip().upper(),
        spot=reference_spot,
        horizon_days=(
            horizon_days
            if horizon_days is not None
            else (measured_range.calendar_horizon_days or measured_range.horizon_days)
        ),
        rows=tuple(rows),
        source=source,
        diagnostics=tuple(diagnostics),
    )


def _bands_from_cdfs(cdfs: Sequence[float]) -> tuple[float, ...]:
    """Turn cumulative boundary probabilities into the mass inside each band."""
    edges = [0.0, *cdfs, 1.0]
    return tuple(max(0.0, edges[i + 1] - edges[i]) for i in range(len(edges) - 1))


def _measured_cdfs(
    spot: float, sigma_pct: float, boundaries: Sequence[float]
) -> tuple[float, ...]:
    """Lognormal CDF at each band edge, using the measured sigma as the return vol.

    Lognormal rather than normal: prices are bounded below at zero, and at the 2 sigma
    edge of a high-vol name the normal model puts visible mass below zero.
    """
    if sigma_pct <= 0.0 or spot <= 0.0:
        return tuple(0.0 if level < spot else 1.0 for level in boundaries)
    return tuple(_lognormal_cdf(level, spot, sigma_pct) for level in boundaries)


def _lognormal_cdf(level: float, spot: float, sigma_pct: float) -> float:
    if level <= 0.0:
        return 0.0
    # Zero-drift over the horizon: the measured range is centred on spot by construction.
    z = (log(level / spot) + (0.5 * sigma_pct * sigma_pct)) / sigma_pct
    return _normal_cdf(z)


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + erf(value / sqrt(2.0)))
