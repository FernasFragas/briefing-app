"""Persistence for gate results and the rolling rejected-at-gate ledger.

Rejected names are persisted so the same name is not rediscovered and re-pitched every
cycle. The JSON store is the default and needs no database; T3 can add a Postgres
implementation of `GateStore` writing the same rows via
`briefing_app.models.gate.to_candidate_gate_rows`.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date as date_type, timedelta
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from briefing_app.models.gate import GateDecision, GateReasonCode, GateReport

DEFAULT_DATA_DIR = "data"
GATE_SUBDIR = "candidate_gate"
HISTORY_FILENAME = "rejection_history.json"
REPORT_FILENAME = "gate_report.json"


class RejectionRecord(BaseModel):
    """How long a ticker has been failing the gate, and for what."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    decision: GateDecision
    reason_codes: list[GateReasonCode] = Field(default_factory=list)
    headline: str | None = None
    first_flagged_on: date_type
    last_flagged_on: date_type
    occurrences: int = 1
    last_run_id: str | None = None

    def is_active(self, as_of: date_type, cooldown_days: int) -> bool:
        if cooldown_days <= 0:
            return True
        return self.last_flagged_on >= as_of - timedelta(days=cooldown_days)


class GateStore(Protocol):
    """Storage contract for the gate. Implemented by `JsonGateStore` and, later, T3."""

    def load_history(self) -> dict[str, RejectionRecord]: ...

    def active_history(
        self, as_of: date_type, cooldown_days: int
    ) -> dict[str, RejectionRecord]: ...

    def save_report(self, report: GateReport) -> Path: ...

    def update_history(
        self, report: GateReport, cooldown_days: int = 0
    ) -> dict[str, RejectionRecord]: ...


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    )
    try:
        with handle:
            handle.write(text)
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise


class JsonGateStore:
    """File-backed gate store under `data/candidate_gate/`."""

    def __init__(self, data_dir: str | Path | None = None) -> None:
        base = Path(data_dir or os.getenv("BRIEFING_DATA_DIR") or DEFAULT_DATA_DIR)
        self.root = base / GATE_SUBDIR

    @property
    def history_path(self) -> Path:
        return self.root / HISTORY_FILENAME

    def report_path(self, report: GateReport) -> Path:
        return self.root / report.run_date.isoformat() / REPORT_FILENAME

    def load_history(self) -> dict[str, RejectionRecord]:
        if not self.history_path.exists():
            return {}
        try:
            payload = json.loads(self.history_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # A corrupt ledger must not stop a run; it only costs repeat detection.
            return {}
        records = payload.get("records", payload) if isinstance(payload, dict) else {}
        history: dict[str, RejectionRecord] = {}
        for ticker, raw in records.items():
            try:
                history[ticker] = RejectionRecord.model_validate(raw)
            except ValueError:
                continue
        return history

    def active_history(
        self, as_of: date_type, cooldown_days: int
    ) -> dict[str, RejectionRecord]:
        return {
            ticker: record
            for ticker, record in self.load_history().items()
            if record.is_active(as_of, cooldown_days)
        }

    def save_report(self, report: GateReport) -> Path:
        path = self.report_path(report)
        _atomic_write(path, report.model_dump_json(indent=2))
        return path

    def update_history(
        self, report: GateReport, cooldown_days: int = 0
    ) -> dict[str, RejectionRecord]:
        """Advance the ledger: gated-out names accumulate, accepted names graduate out.

        A record that has gone quiet for longer than the cooldown starts a fresh streak,
        so the count matches what the gate saw in `active_history`.
        """
        history = self.load_history()

        for result in report.results:
            if result.is_scored:
                history.pop(result.ticker, None)
                continue
            existing = history.get(result.ticker)
            if existing is not None and not existing.is_active(report.run_date, cooldown_days):
                existing = None
            first_flagged_on = existing.first_flagged_on if existing else report.run_date
            occurrences = (existing.occurrences + 1) if existing else 1
            history[result.ticker] = RejectionRecord(
                ticker=result.ticker,
                decision=result.decision,
                reason_codes=result.reason_codes,
                headline=result.reason_summary() or None,
                first_flagged_on=first_flagged_on,
                last_flagged_on=report.run_date,
                occurrences=occurrences,
                last_run_id=report.run_id,
            )

        payload = {
            "updated_on": report.run_date.isoformat(),
            "last_run_id": report.run_id,
            "records": {
                ticker: json.loads(record.model_dump_json())
                for ticker, record in sorted(history.items())
            },
        }
        _atomic_write(self.history_path, json.dumps(payload, indent=2))
        return history
