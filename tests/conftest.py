"""Shared builders for the universe and gate tests."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from briefing_app.config import GateSettings
from briefing_app.models.candidate import Candidate

RUN_DATE = date(2026, 8, 29)


def make_catalyst(
    *, days_out: int = 3, status: str = "confirmed", **overrides: Any
) -> dict[str, Any]:
    catalyst: dict[str, Any] = {
        "name": "Quarterly results",
        "date": RUN_DATE + timedelta(days=days_out),
        "status": status,
        "kind": "other",
    }
    catalyst.update(overrides)
    return catalyst


def make_candidate(**overrides: Any) -> Candidate:
    record: dict[str, Any] = {
        "ticker": "TEST",
        "venue": "NASDAQ",
        "geography": "US",
        "sector": "Software",
        "direction": "long",
        "thesis": "Event directional into a dated catalyst.",
        "horizon_days": 10,
        "expression_class": "E",
        "broker": "IBKR",
        "permitted_instruments": ["shares", "options"],
        "catalysts": [make_catalyst()],
        "thesis_sources": [{"label": "Company IR", "kind": "company_ir"}],
    }
    record.update(overrides)
    return Candidate.model_validate(record)


@pytest.fixture
def settings() -> GateSettings:
    """Permissive defaults: every class enabled so tests opt in to each restriction."""
    return GateSettings()


@pytest.fixture
def run_date() -> date:
    return RUN_DATE
