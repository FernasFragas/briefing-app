"""Strategy and execution rule engine (T8)."""

from briefing_app.strategy.engine import (
    ChainLiquidity,
    SetupContext,
    evaluate_candidate_setups,
    make_run_id,
    run_strategy_engine,
)
from briefing_app.strategy.invalidation import (
    Invalidation,
    InvalidationBasis,
    build_invalidation,
)
from briefing_app.strategy.leverage import (
    DEFAULT_KNOCKOUT_BUFFER,
    DragSimulation,
    LeverageCheck,
    LeverageError,
    check_leverage,
    knockout_move_pct,
    simulate_daily_reset,
)
from briefing_app.strategy.models import (
    INSTRUMENT_PREFERENCE,
    SETUP_INSTRUMENTS,
    CandidateSetupResult,
    RejectionCode,
    Setup,
    SetupDecision,
    SetupEvidence,
    SetupRejection,
    SetupReport,
    SetupType,
    to_setup_evidence_rows,
    to_setup_signal_rows,
)
from briefing_app.strategy.scenarios import (
    DIVERGENCE_THRESHOLD,
    MIN_CAPTURED_MASS,
    ScenarioRow,
    ScenarioTable,
    build_scenario_table,
)

__all__ = [
    "DEFAULT_KNOCKOUT_BUFFER",
    "DIVERGENCE_THRESHOLD",
    "INSTRUMENT_PREFERENCE",
    "MIN_CAPTURED_MASS",
    "SETUP_INSTRUMENTS",
    "CandidateSetupResult",
    "ChainLiquidity",
    "DragSimulation",
    "Invalidation",
    "InvalidationBasis",
    "LeverageCheck",
    "LeverageError",
    "RejectionCode",
    "ScenarioRow",
    "ScenarioTable",
    "Setup",
    "SetupContext",
    "SetupDecision",
    "SetupEvidence",
    "SetupRejection",
    "SetupReport",
    "SetupType",
    "build_invalidation",
    "build_scenario_table",
    "check_leverage",
    "evaluate_candidate_setups",
    "knockout_move_pct",
    "make_run_id",
    "run_strategy_engine",
    "simulate_daily_reset",
    "to_setup_evidence_rows",
    "to_setup_signal_rows",
]
