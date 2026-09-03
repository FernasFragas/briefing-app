"""T9 dashboard schema, rendering, and LLM guardrails."""

from briefing_app.dashboard.build import all_source_labels, build_dashboard_payload
from briefing_app.dashboard.guardrails import (
    NumericGuardError,
    NumberToken,
    NumberViolation,
    assert_authorized_numbers,
    collect_authorized_numbers,
    extract_number_tokens,
)
from briefing_app.dashboard.llm import BriefingLLM, LLMProvider, LLMProviderError, LLMResponse
from briefing_app.dashboard.models import (
    ConditionalityRow,
    DashboardPayload,
    EvidenceLedgerRow,
    MarketOverviewPoint,
    MasterAlphaRow,
    PerTickerSection,
    PriorScorecardRow,
    RejectedGateRow,
    TacticalDashboard,
)
from briefing_app.dashboard.prompts import (
    MARKET_OVERVIEW_SYSTEM_PROMPT,
    TICKER_PROSE_SYSTEM_PROMPT,
    market_overview_context,
    market_overview_messages,
    ticker_prose_context,
    ticker_prose_messages,
)
from briefing_app.dashboard.render import (
    render_dashboard_html,
    render_dashboard_json,
    write_dashboard_artifacts,
)

__all__ = [
    "ConditionalityRow",
    "DashboardPayload",
    "EvidenceLedgerRow",
    "MarketOverviewPoint",
    "MasterAlphaRow",
    "PerTickerSection",
    "PriorScorecardRow",
    "RejectedGateRow",
    "TacticalDashboard",
    "BriefingLLM",
    "LLMProvider",
    "LLMProviderError",
    "LLMResponse",
    "MARKET_OVERVIEW_SYSTEM_PROMPT",
    "NumericGuardError",
    "NumberToken",
    "NumberViolation",
    "TICKER_PROSE_SYSTEM_PROMPT",
    "all_source_labels",
    "assert_authorized_numbers",
    "build_dashboard_payload",
    "collect_authorized_numbers",
    "extract_number_tokens",
    "market_overview_context",
    "market_overview_messages",
    "render_dashboard_html",
    "render_dashboard_json",
    "ticker_prose_context",
    "ticker_prose_messages",
    "write_dashboard_artifacts",
]
