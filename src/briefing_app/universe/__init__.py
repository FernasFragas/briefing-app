"""Universe construction and the pre-scoring catalyst gate (T2)."""

from briefing_app.universe.gate import evaluate_candidate, make_run_id, run_gate
from briefing_app.universe.loader import (
    LoadResult,
    UniverseLoadError,
    load_candidate_file,
    load_fixed_universe,
    load_screen_candidates,
    load_universe,
)
from briefing_app.universe.pipeline import GateRunOutput, run_candidate_gate
from briefing_app.universe.render import (
    render_accepted_table,
    render_gate_markdown,
    render_rejected_table,
)
from briefing_app.universe.store import GateStore, JsonGateStore, RejectionRecord

__all__ = [
    "GateRunOutput",
    "GateStore",
    "JsonGateStore",
    "LoadResult",
    "RejectionRecord",
    "UniverseLoadError",
    "evaluate_candidate",
    "load_candidate_file",
    "load_fixed_universe",
    "load_screen_candidates",
    "load_universe",
    "make_run_id",
    "render_accepted_table",
    "render_gate_markdown",
    "render_rejected_table",
    "run_candidate_gate",
    "run_gate",
]
