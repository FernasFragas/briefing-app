"""Scoring JSON v1 - the composite-score contract T7 emits and T8/T9 consume.

T7 owns the arithmetic (component standardization, missing-component re-weighting,
required-set tiering). This module owns only the *shape* of that output plus the
constants both sides have to agree on: the two weight profiles, the required-component
set per expression class, and the score-to-posture band table from the plan.

T8 builds against this contract with fixture scores while T7 is still in flight.
"""

from __future__ import annotations

from datetime import date as date_type
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from briefing_app.models.candidate import ExpressionClass, Geography

#: Component keys, in disclosure order.
COMPONENTS: tuple[str, ...] = ("S_M", "S_O", "S_S", "S_I", "S_F")

#: `S_CTE = (0.30 * S_M) + (0.25 * S_O) + (0.20 * S_S) + (0.15 * S_I) + (0.10 * S_F)`
US_WEIGHTS: dict[str, float] = {"S_M": 0.30, "S_O": 0.25, "S_S": 0.20, "S_I": 0.15, "S_F": 0.10}

#: `S_CTE_EU = (0.35 * S_M) + (0.30 * S_O) + (0.20 * S_S) + (0.10 * S_I) + (0.05 * S_F)`
EU_WEIGHTS: dict[str, float] = {"S_M": 0.35, "S_O": 0.30, "S_S": 0.20, "S_I": 0.10, "S_F": 0.05}

WEIGHTS_BY_PROFILE: dict[str, dict[str, float]] = {"US": US_WEIGHTS, "EU": EU_WEIGHTS}

#: Tiering runs over the required set only. `S` is `P` plus verified borrow evidence.
REQUIRED_COMPONENTS: dict[ExpressionClass, frozenset[str]] = {
    ExpressionClass.V: frozenset({"S_O", "S_M"}),
    ExpressionClass.E: frozenset({"S_O", "S_M"}),
    ExpressionClass.P: frozenset({"S_M", "S_S", "S_I", "S_F"}),
    ExpressionClass.S: frozenset({"S_M", "S_S", "S_I", "S_F"}),
}

#: Score-band edges from the Score Interpretation table (plan Phase 6).
NEUTRAL_BAND: float = 0.15
STRONG_BAND: float = 0.60


def weights_for(geography: Geography | str) -> dict[str, float]:
    profile = Geography(geography).weight_profile
    return dict(WEIGHTS_BY_PROFILE[profile])


class ConfidenceTier(StrEnum):
    """Confidence over the required set. `C` is watchlist-only, never executable."""

    A = "A"
    B = "B"
    C = "C"

    @property
    def is_tradeable(self) -> bool:
        """Tier C names never enter the Tactical Execution Dashboard."""
        return self is not ConfidenceTier.C

    @property
    def size_fraction(self) -> float:
        """Full size at A, half at B, nothing at C."""
        return {ConfidenceTier.A: 1.0, ConfidenceTier.B: 0.5, ConfidenceTier.C: 0.0}[self]

    def floor_to(self, other: "ConfidenceTier") -> "ConfidenceTier":
        """Most severe tier wins. Used by the T8 universal Tier C floors."""
        return max(self, other, key=lambda tier: _TIER_SEVERITY[tier])


_TIER_SEVERITY: dict[ConfidenceTier, int] = {
    ConfidenceTier.A: 0,
    ConfidenceTier.B: 1,
    ConfidenceTier.C: 2,
}


class Posture(StrEnum):
    """How the composite score reads, before any setup rule fires."""

    STRONG_BULLISH = "strong_bullish"
    MODERATE_BULLISH = "moderate_bullish"
    NEUTRAL = "neutral"
    MODERATE_BEARISH = "moderate_bearish"
    STRONG_BEARISH = "strong_bearish"
    WATCHLIST = "watchlist"

    @classmethod
    def from_score(cls, score: float | None) -> "Posture":
        """No score means no posture: the name is watchlist until one exists."""
        if score is None:
            return cls.WATCHLIST
        if score >= STRONG_BAND:
            return cls.STRONG_BULLISH
        if score >= NEUTRAL_BAND:
            return cls.MODERATE_BULLISH
        if score > -NEUTRAL_BAND:
            return cls.NEUTRAL
        if score > -STRONG_BAND:
            return cls.MODERATE_BEARISH
        return cls.STRONG_BEARISH

    @property
    def is_bullish(self) -> bool:
        return self in (Posture.STRONG_BULLISH, Posture.MODERATE_BULLISH)

    @property
    def is_bearish(self) -> bool:
        return self in (Posture.STRONG_BEARISH, Posture.MODERATE_BEARISH)

    @property
    def is_strong(self) -> bool:
        return self in (Posture.STRONG_BULLISH, Posture.STRONG_BEARISH)


class ComponentScore(BaseModel):
    """One standardized component, with the disclosure T7 owes the evidence ledger."""

    model_config = ConfigDict(extra="forbid")

    component: str
    score: float | None = Field(default=None, ge=-1.0, le=1.0)
    original_weight: float = 0.0
    weight_used: float = 0.0
    validation_status: str = "computed"
    source_quality: str | None = None
    required: bool = False
    missing_reason: str | None = None
    as_of: date_type | None = None

    @field_validator("component")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.strip().upper()

    @property
    def is_available(self) -> bool:
        return self.score is not None


class ScoringResult(BaseModel):
    """One ticker's composite score, tier, and the weights actually used.

    A component that is `n/a` is dropped and the remaining weights are re-normalized,
    so a missing component never pulls `S_CTE` toward neutral.
    """

    model_config = ConfigDict(extra="forbid")

    ticker: str
    expression_class: ExpressionClass
    geography: Geography = Geography.US
    s_cte: float | None = Field(default=None, ge=-1.0, le=1.0)
    tier: ConfidenceTier = ConfidenceTier.C
    components: list[ComponentScore] = Field(default_factory=list)
    tier_reasons: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @field_validator("ticker")
    @classmethod
    def _clean_ticker(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if not cleaned:
            raise ValueError("ticker must not be blank")
        return cleaned

    @property
    def posture(self) -> Posture:
        return Posture.from_score(self.s_cte)

    @property
    def weight_profile(self) -> str:
        return self.geography.weight_profile

    @property
    def original_weights(self) -> dict[str, float]:
        return weights_for(self.geography)

    def component(self, name: str) -> ComponentScore | None:
        key = name.strip().upper()
        return next((c for c in self.components if c.component == key), None)

    def score_of(self, name: str) -> float | None:
        found = self.component(name)
        return found.score if found is not None else None

    @property
    def available_components(self) -> list[str]:
        return [c.component for c in self.components if c.is_available]

    @property
    def missing_components(self) -> list[str]:
        available = set(self.available_components)
        return [name for name in COMPONENTS if name not in available]

    @property
    def weights_used(self) -> dict[str, float]:
        return {c.component: c.weight_used for c in self.components if c.is_available}

    @property
    def required_components(self) -> frozenset[str]:
        return REQUIRED_COMPONENTS[self.expression_class]

    @property
    def missing_required(self) -> list[str]:
        return [name for name in self.missing_components if name in self.required_components]

    @property
    def required_set_verdict(self) -> str:
        if self.tier is ConfidenceTier.C:
            return "unavailable"
        if self.tier is ConfidenceTier.B:
            return "degraded"
        return "verified"

    def disclosure(self) -> dict[str, Any]:
        """One-line disclosure: original weights, missing components, weights used."""
        return {
            "ticker": self.ticker,
            "expression_class": self.expression_class.value,
            "geography": self.geography.value,
            "weight_profile": self.weight_profile,
            "s_cte": self.s_cte,
            "tier": self.tier.value,
            "posture": self.posture.value,
            "original_weights": self.original_weights,
            "weights_used": self.weights_used,
            "missing_components": self.missing_components,
            "missing_required": self.missing_required,
            "required_set_verdict": self.required_set_verdict,
            "tier_reasons": list(self.tier_reasons),
        }
