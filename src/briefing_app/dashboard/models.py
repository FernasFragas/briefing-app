"""Dashboard JSON contract for T9.

The dashboard is an audit artifact first and a presentation surface second. It is built
from values computed by earlier stages: the renderer and the LLM layer may format those
values, but neither may invent them.
"""

from __future__ import annotations

from datetime import date as date_type, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


JsonValue = str | int | float | bool | None


class MarketOverviewPoint(BaseModel):
    """One sourced market-level value available to the prose generator."""

    model_config = ConfigDict(extra="forbid")

    label: str
    value: JsonValue = None
    source: str
    as_of: str | None = None
    note: str | None = None


class PriorScorecardRow(BaseModel):
    """Prior calibration or scorecard row shown before new recommendations."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    snap_date: str | None = None
    component_scores: dict[str, float | None] = Field(default_factory=dict)
    cte_score: float | None = None
    confidence_tier: str | None = None
    expression_class: str | None = None

    @field_validator("ticker")
    @classmethod
    def _clean_ticker(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if not cleaned:
            raise ValueError("ticker must not be blank")
        return cleaned


class MasterAlphaRow(BaseModel):
    """One row in the Master Alpha Selection Matrix."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    venue: str | None = None
    geography: str | None = None
    expression_class: str | None = None
    direction: str | None = None
    gate_decision: str | None = None
    s_cte: float | None = None
    tier: str | None = None
    posture: str | None = None
    component_scores: dict[str, float | None] = Field(default_factory=dict)
    missing_components: list[str] = Field(default_factory=list)
    source_quality: dict[str, str | None] = Field(default_factory=dict)
    primary_catalyst: dict[str, Any] | None = None
    top_setup: str | None = None
    tradeable_setup_count: int = 0
    flags: list[str] = Field(default_factory=list)


class RejectedGateRow(BaseModel):
    """Demotions and hard rejections from the pre-scoring gate."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    decision: str
    reason_codes: list[str] = Field(default_factory=list)
    detail: str | None = None
    first_flagged_on: str | None = None
    occurrences: int = 0


class EvidenceLedgerRow(BaseModel):
    """A display-safe evidence row shaped like the T3 evidence ledger."""

    model_config = ConfigDict(extra="forbid")

    ticker: str = "*"
    component: str
    field_name: str
    field_value: str
    source: str
    venue: str = "*"
    as_of: str | None = None
    endpoint_or_file: str = ""
    validation_status: str = "verified"
    note: str | None = None


class TacticalDashboard(BaseModel):
    """Top setup slots. Tier C watchlist rows are excluded upstream."""

    model_config = ConfigDict(extra="forbid")

    top_long: dict[str, Any] | None = None
    top_short: dict[str, Any] | None = None
    top_volatility: dict[str, Any] | None = None


class ConditionalityRow(BaseModel):
    """Triggers, stops, warnings, and refused setup reasons for one ticker/setup."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    setup_type: str
    decision: str
    catalyst: dict[str, Any] | None = None
    invalidation: dict[str, Any] | None = None
    triggers: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    rejections: list[dict[str, str]] = Field(default_factory=list)


class PerTickerSection(BaseModel):
    """Everything rendered under a ticker heading."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    gate: dict[str, Any] | None = None
    score: dict[str, Any] | None = None
    components: list[dict[str, Any]] = Field(default_factory=list)
    setups: list[dict[str, Any]] = Field(default_factory=list)
    setup_rejections: list[dict[str, str]] = Field(default_factory=list)
    evidence: list[EvidenceLedgerRow] = Field(default_factory=list)
    prose: str | None = None


class TradingIdeaRow(BaseModel):
    """One graded idea. Python computes the grade; prose layers may only format it.

    `grade_letter` is `None` for an unscored name: a ticker that never produced a
    `ScoringResult` is listed so its absence is visible, not graded on partial data.
    """

    model_config = ConfigDict(extra="forbid")

    ticker: str
    setup_type: str | None = None
    grade_letter: str | None = None
    grade_score: float | None = None
    thesis_probability: float | None = None
    thesis_band: str | None = None
    s_cte: float | None = None
    tier: str | None = None
    status: str
    catalyst: dict[str, Any] | None = None
    blocked_reason: str | None = None
    grade_penalties: list[str] = Field(default_factory=list)
    headline: str = ""


class DashboardPayload(BaseModel):
    """Top-level dashboard artifact consumed by HTML, JSON, and LLM prompt layers."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "dashboard.v2"
    run_id: str
    run_date: date_type
    generated_at: datetime
    #: Which data source produced this run: "fixture", "live", or "unknown" when the
    #: builder was not told. Every number below means something different per mode, so it
    #: is recorded rather than inferred from the sources named in the evidence ledger.
    data_mode: str = "unknown"
    trading_ideas: list[TradingIdeaRow] = Field(default_factory=list)
    prior_scorecard: list[PriorScorecardRow] = Field(default_factory=list)
    market_overview: list[MarketOverviewPoint] = Field(default_factory=list)
    master_alpha_selection_matrix: list[MasterAlphaRow] = Field(default_factory=list)
    rejected_at_gate: list[RejectedGateRow] = Field(default_factory=list)
    evidence_ledger: list[EvidenceLedgerRow] = Field(default_factory=list)
    tactical_execution_dashboard: TacticalDashboard = Field(default_factory=TacticalDashboard)
    conditionality_table: list[ConditionalityRow] = Field(default_factory=list)
    per_ticker_sections: list[PerTickerSection] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)

    def audit_json(self, *, indent: int = 2) -> str:
        """Plain JSON audit artifact. No prose post-processing or external assets."""
        return self.model_dump_json(indent=indent)

    @property
    def counts(self) -> dict[str, int]:
        return {
            "matrix": len(self.master_alpha_selection_matrix),
            "rejected_at_gate": len(self.rejected_at_gate),
            "evidence_rows": len(self.evidence_ledger),
            "conditionality_rows": len(self.conditionality_table),
            "tickers": len(self.per_ticker_sections),
        }
