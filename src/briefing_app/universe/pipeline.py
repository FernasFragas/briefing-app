"""Stage entrypoint: load the universe, gate it, persist it, render it.

T10 calls `run_candidate_gate` as the first stage of the daily run; the CLI calls it
directly so the gate can be inspected before any provider work exists.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date as date_type
from pathlib import Path

from briefing_app.config import AppConfig
from briefing_app.models.gate import GateReport
from briefing_app.universe.gate import run_gate
from briefing_app.universe.loader import load_universe
from briefing_app.universe.render import render_gate_markdown
from briefing_app.universe.store import GateStore, JsonGateStore

DEFAULT_OUTPUT_DIR = "output"
GATE_OUTPUT_SUBDIR = "candidate_gate"
MARKDOWN_FILENAME = "candidate_gate.md"


@dataclass
class GateRunOutput:
    report: GateReport
    markdown: str
    report_path: Path | None = None
    markdown_path: Path | None = None


def _output_root(output_dir: str | Path | None) -> Path:
    base = Path(output_dir or os.getenv("BRIEFING_OUTPUT_DIR") or DEFAULT_OUTPUT_DIR)
    return base / GATE_OUTPUT_SUBDIR


def run_candidate_gate(
    config: AppConfig,
    *,
    run_date: date_type | None = None,
    mode: str | None = None,
    store: GateStore | None = None,
    persist: bool = True,
    output_dir: str | Path | None = None,
    run_id: str | None = None,
) -> GateRunOutput:
    """Run universe construction and the catalyst gate for one date."""
    effective_date = run_date or date_type.today()
    gate_store = store or JsonGateStore()

    loaded = load_universe(config, mode)
    history = gate_store.active_history(effective_date, config.gate.rejection_cooldown_days)

    report = run_gate(
        loaded.candidates,
        run_date=effective_date,
        settings=config.gate,
        history=history,
        run_id=run_id,
        load_warnings=loaded.warnings,
        load_errors=loaded.errors,
    )
    markdown = render_gate_markdown(report)
    output = GateRunOutput(report=report, markdown=markdown)

    if persist:
        output.report_path = gate_store.save_report(report)
        gate_store.update_history(report, config.gate.rejection_cooldown_days)
        markdown_path = _output_root(output_dir) / effective_date.isoformat() / MARKDOWN_FILENAME
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(markdown, encoding="utf-8")
        output.markdown_path = markdown_path

    return output
