"""Invalidation-level generation.

Plan Phase 6: a missing invalidation level is a universal Tier C floor, so a setup that
cannot be given one is not emitted. Levels are drawn, in priority order, from:

1. An option wall (open-interest cluster) sitting between spot and the measured 1 sigma
   edge - a real level with size behind it beats a statistical one.
2. The measured 1 sigma edge from real closes.

Non-price failure conditions (catalyst slips, borrow disappears) are always recorded
alongside the level, because a thesis can fail without the price going anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_type
from enum import StrEnum
from typing import Any, Sequence

from briefing_app.models.candidate import Catalyst, Direction
from briefing_app.options_math import MeasuredSigmaRange, OiCluster


class InvalidationBasis(StrEnum):
    OPTION_WALL = "option_wall"
    MEASURED_SIGMA = "measured_sigma"
    MIXED = "mixed"


@dataclass(frozen=True)
class Invalidation:
    """Where the thesis is wrong, and what else would falsify it without a price move."""

    direction: Direction
    basis: InvalidationBasis
    description: str
    lower_level: float | None = None
    upper_level: float | None = None
    conditions: tuple[str, ...] = ()
    sources: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        if self.lower_level is None and self.upper_level is None:
            raise ValueError("an invalidation needs at least one price level")

    @property
    def levels(self) -> tuple[float | None, float | None]:
        return (self.lower_level, self.upper_level)

    @property
    def primary_level(self) -> float:
        """The level that breaks this direction first."""
        if self.direction is Direction.SHORT:
            return self.upper_level if self.upper_level is not None else float(self.lower_level)
        return self.lower_level if self.lower_level is not None else float(self.upper_level)

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction.value,
            "basis": self.basis.value,
            "description": self.description,
            "lower_level": self.lower_level,
            "upper_level": self.upper_level,
            "primary_level": self.primary_level,
            "conditions": list(self.conditions),
            "sources": list(self.sources),
        }


def build_invalidation(
    *,
    direction: Direction,
    spot: float,
    measured_range: MeasuredSigmaRange | None,
    oi_clusters: Sequence[OiCluster] = (),
    catalyst: Catalyst | None = None,
    horizon_end: date_type | None = None,
    extra_conditions: Sequence[str] = (),
    two_sigma_for_neutral: bool = True,
) -> Invalidation | None:
    """Generate the invalidation for one setup, or `None` when nothing supports a level.

    A neutral (premium-selling) setup is invalidated on either side, so it gets both
    edges - the 2 sigma edges by default, since a 1 sigma touch is the expected case
    for a short-premium structure rather than a failure of it.
    """

    if measured_range is None or spot <= 0.0:
        return None

    conditions = list(_failure_conditions(catalyst, horizon_end))
    conditions.extend(condition for condition in extra_conditions if condition)
    sources: list[str] = [
        f"measured sigma {measured_range.adjusted_sigma_pct:.2%} over "
        f"{measured_range.horizon_days} trading days ({measured_range.lookback_days}d lookback)"
    ]

    if direction is Direction.NEUTRAL:
        band = measured_range.two_sigma if two_sigma_for_neutral else measured_range.one_sigma
        label = "2 sigma" if two_sigma_for_neutral else "1 sigma"
        return Invalidation(
            direction=direction,
            basis=InvalidationBasis.MEASURED_SIGMA,
            description=(
                f"either measured {label} edge breached: below {band.low:.2f} or "
                f"above {band.high:.2f}"
            ),
            lower_level=band.low,
            upper_level=band.high,
            conditions=tuple(conditions),
            sources=tuple(sources),
        )

    adverse_is_down = direction is not Direction.SHORT
    sigma_level = (
        measured_range.one_sigma.low if adverse_is_down else measured_range.one_sigma.high
    )
    wall = _nearest_wall(spot, sigma_level, oi_clusters, adverse_is_down=adverse_is_down)

    if wall is not None:
        level = wall.strike
        basis = InvalidationBasis.MIXED
        description = (
            f"close beyond the {wall.strike:.2f} open-interest wall "
            f"({wall.total_open_interest:,} contracts, {wall.expiry.isoformat()}), "
            f"inside the measured 1 sigma edge at {sigma_level:.2f}"
        )
        sources.append(
            f"open-interest cluster {wall.strike:.2f} on {wall.expiry.isoformat()} "
            f"({wall.concentration:.1%} of clustered OI)"
        )
    else:
        level = sigma_level
        basis = InvalidationBasis.MEASURED_SIGMA
        side = "below" if adverse_is_down else "above"
        description = f"close {side} the measured 1 sigma edge at {sigma_level:.2f}"

    return Invalidation(
        direction=direction,
        basis=basis,
        description=description,
        lower_level=level if adverse_is_down else None,
        upper_level=None if adverse_is_down else level,
        conditions=tuple(conditions),
        sources=tuple(sources),
    )


def _nearest_wall(
    spot: float,
    sigma_level: float,
    clusters: Sequence[OiCluster],
    *,
    adverse_is_down: bool,
) -> OiCluster | None:
    """The heaviest OI strike between spot and the sigma edge, on the adverse side."""
    if adverse_is_down:
        inside = [c for c in clusters if sigma_level <= c.strike < spot]
    else:
        inside = [c for c in clusters if spot < c.strike <= sigma_level]
    if not inside:
        return None
    return max(inside, key=lambda cluster: (cluster.total_open_interest, cluster.concentration))


def _failure_conditions(
    catalyst: Catalyst | None, horizon_end: date_type | None
) -> list[str]:
    conditions: list[str] = []
    if catalyst is not None:
        conditions.append(
            f"{catalyst.name} does not occur on {catalyst.event_date.isoformat()} "
            "or is withdrawn"
        )
        if not catalyst.is_confirmed:
            conditions.append(
                f"{catalyst.name} date stays Estimated at the open of the holding window"
            )
    if horizon_end is not None:
        conditions.append(f"thesis unresolved by {horizon_end.isoformat()}")
    return conditions
