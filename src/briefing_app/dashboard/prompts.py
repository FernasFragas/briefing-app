"""Strict prompt templates for T9 prose generation."""

from __future__ import annotations

import json
from typing import Any

from briefing_app.dashboard.build import all_source_labels
from briefing_app.dashboard.models import DashboardPayload, PerTickerSection


MARKET_OVERVIEW_SYSTEM_PROMPT = """You write concise market-overview prose for a trading briefing.
Use only the JSON values and source labels supplied by the user message.
Do not add numerical claims, dates, prices, percentages, counts, targets, or thresholds
that are not present in the JSON. Say unavailable when a needed value is null."""

TICKER_PROSE_SYSTEM_PROMPT = """You write concise per-ticker briefing prose.
Use only the computed grade, setup, score, component, catalyst, and evidence values supplied
in the JSON. Do not add numerical claims, dates, prices, percentages, counts, targets,
or thresholds that are not present in the JSON. Do not recommend a setup that is not
already listed as a candidate setup. Use grade fields exactly as supplied; do not
invent or modify grade scores, grade letters, thesis probabilities, or statuses."""


def market_overview_context(payload: DashboardPayload) -> dict[str, Any]:
    """Computed market-level values and source labels only."""
    return {
        "run_id": payload.run_id,
        "run_date": payload.run_date.isoformat(),
        "market_overview": [point.model_dump(mode="json") for point in payload.market_overview],
        "counts": payload.counts,
        "source_labels": all_source_labels(payload),
    }


def ticker_prose_context(payload: DashboardPayload, ticker: str) -> dict[str, Any]:
    """Computed ticker values and source labels only; no candidate thesis text."""
    section = _section_for(payload, ticker)
    evidence_sources = sorted({row.source for row in section.evidence})
    return {
        "run_id": payload.run_id,
        "run_date": payload.run_date.isoformat(),
        "ticker": section.ticker,
        "trading_idea": _trading_idea_context(payload, section.ticker),
        "gate": _gate_context(section),
        "score": section.score,
        "components": _component_context(section),
        "setups": _setup_context(section),
        "setup_rejections": section.setup_rejections,
        "evidence_sources": evidence_sources,
    }


def market_overview_messages(payload: DashboardPayload) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": MARKET_OVERVIEW_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _json_prompt(
                "Write the market overview from this computed context.",
                market_overview_context(payload),
            ),
        },
    ]


def ticker_prose_messages(payload: DashboardPayload, ticker: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": TICKER_PROSE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _json_prompt(
                f"Write the per-ticker prose for {ticker.strip().upper()}.",
                ticker_prose_context(payload, ticker),
            ),
        },
    ]


def _json_prompt(instruction: str, context: dict[str, Any]) -> str:
    return instruction + "\n\n```json\n" + json.dumps(context, indent=2, sort_keys=True) + "\n```"


def _section_for(payload: DashboardPayload, ticker: str) -> PerTickerSection:
    clean = ticker.strip().upper()
    for section in payload.per_ticker_sections:
        if section.ticker == clean:
            return section
    raise KeyError(f"ticker not found in dashboard payload: {clean}")


def _trading_idea_context(payload: DashboardPayload, ticker: str) -> dict[str, Any] | None:
    for row in payload.trading_ideas:
        if row.ticker == ticker:
            return row.model_dump(mode="json")
    return None


def _gate_context(section: PerTickerSection) -> dict[str, Any] | None:
    if section.gate is None:
        return None
    gate = section.gate
    return {
        "decision": gate.get("decision"),
        "horizon_days": gate.get("horizon_days"),
        "window_start": gate.get("window_start"),
        "window_end": gate.get("window_end"),
        "flags": gate.get("flags", []),
        "primary_catalyst": gate.get("primary_catalyst"),
        "permitted_instruments": gate.get("permitted_instruments", []),
        "leverage_allowed": gate.get("leverage_allowed"),
        "requires_borrow_verification": gate.get("requires_borrow_verification"),
        "earnings_in_horizon": gate.get("earnings_in_horizon"),
        "confidence_multiplier": gate.get("confidence_multiplier"),
    }


def _component_context(section: PerTickerSection) -> list[dict[str, Any]]:
    return [
        {
            "component": component.get("component"),
            "available": component.get("available"),
            "score": component.get("score"),
            "validation_status": component.get("validation_status"),
            "source_quality": component.get("source_quality"),
            "na_reason": component.get("na_reason"),
            "sub_scores": [
                {
                    "name": sub.get("name"),
                    "score": sub.get("score"),
                    "weight_used": sub.get("weight_used"),
                    "available": sub.get("available"),
                    "na_reason": sub.get("na_reason"),
                    "source": sub.get("source"),
                    "as_of": sub.get("as_of"),
                    "sample_size": sub.get("sample_size"),
                }
                for sub in component.get("sub_scores", [])
            ],
        }
        for component in section.components
    ]


def _setup_context(section: PerTickerSection) -> list[dict[str, Any]]:
    return [
        {
            "setup_type": setup.get("setup_type"),
            "decision": setup.get("decision"),
            "expression_class": setup.get("expression_class"),
            "direction": setup.get("direction"),
            "horizon_days": setup.get("horizon_days"),
            "horizon_label": setup.get("horizon_label"),
            "tier": setup.get("tier"),
            "posture": setup.get("posture"),
            "s_cte": setup.get("s_cte"),
            "size_fraction": setup.get("size_fraction"),
            "instrument": setup.get("instrument"),
            "catalyst": setup.get("catalyst"),
            "invalidation": setup.get("invalidation"),
            "range_low": setup.get("range_low"),
            "range_high": setup.get("range_high"),
            "triggers": setup.get("triggers", []),
            "warnings": setup.get("warnings", []),
        }
        for setup in section.setups
    ]
