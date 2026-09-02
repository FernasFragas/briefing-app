"""The rejection ledger: rejected names persist, accepted names graduate out."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from briefing_app.models.gate import GateDecision, GateReasonCode
from briefing_app.universe.gate import run_gate
from briefing_app.universe.store import JsonGateStore, RejectionRecord
from tests.conftest import RUN_DATE, make_candidate


def gate_report(run_date: date, settings, tickers_without_catalyst=("KO",), extra=()):
    candidates = [make_candidate(ticker="AAA")]
    candidates += [make_candidate(ticker=t, catalysts=[]) for t in tickers_without_catalyst]
    candidates += list(extra)
    return run_gate(candidates, run_date=run_date, settings=settings)


def test_report_is_written_under_the_run_date(tmp_path: Path, settings) -> None:
    store = JsonGateStore(tmp_path)
    report = gate_report(RUN_DATE, settings)
    path = store.save_report(report)

    assert path == tmp_path / "candidate_gate" / RUN_DATE.isoformat() / "gate_report.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["run_id"] == report.run_id
    assert [r["ticker"] for r in payload["results"]] == ["AAA", "KO"]


def test_history_starts_empty_and_accumulates_repeat_rejections(
    tmp_path: Path, settings
) -> None:
    store = JsonGateStore(tmp_path)
    assert store.load_history() == {}

    store.update_history(gate_report(RUN_DATE, settings))
    first = store.load_history()["KO"]
    assert first.occurrences == 1
    assert first.first_flagged_on == RUN_DATE
    assert first.decision is GateDecision.WATCHLIST
    assert first.reason_codes == [GateReasonCode.NO_CATALYST_IN_HORIZON]

    later = RUN_DATE + timedelta(days=7)
    store.update_history(gate_report(later, settings))
    second = store.load_history()["KO"]
    assert second.occurrences == 2
    assert second.first_flagged_on == RUN_DATE
    assert second.last_flagged_on == later


def test_accepted_names_are_cleared_from_the_ledger(tmp_path: Path, settings) -> None:
    store = JsonGateStore(tmp_path)
    store.update_history(gate_report(RUN_DATE, settings))
    assert "KO" in store.load_history()

    # KO comes back with a dated catalyst in the horizon, so it is scored again.
    store.update_history(
        run_gate(
            [make_candidate(ticker="KO")], run_date=RUN_DATE, settings=settings
        )
    )
    assert "KO" not in store.load_history()


def test_cooldown_hides_stale_records_and_restarts_the_streak(
    tmp_path: Path, settings
) -> None:
    store = JsonGateStore(tmp_path)
    store.update_history(gate_report(RUN_DATE, settings), cooldown_days=30)

    much_later = RUN_DATE + timedelta(days=90)
    assert store.active_history(much_later, cooldown_days=30) == {}
    assert "KO" in store.active_history(much_later, cooldown_days=0)

    store.update_history(gate_report(much_later, settings), cooldown_days=30)
    record = store.load_history()["KO"]
    assert record.occurrences == 1
    assert record.first_flagged_on == much_later


def test_gate_and_store_agree_on_the_occurrence_count(tmp_path: Path, settings) -> None:
    store = JsonGateStore(tmp_path)
    cooldown = settings.rejection_cooldown_days
    for offset in range(3):
        run_date = RUN_DATE + timedelta(days=offset)
        history = store.active_history(run_date, cooldown)
        report = run_gate(
            [make_candidate(ticker="KO", catalysts=[])],
            run_date=run_date,
            settings=settings,
            history=history,
        )
        store.update_history(report, cooldown)
        assert report.results[0].occurrences == offset + 1
        assert store.load_history()["KO"].occurrences == offset + 1


def test_a_corrupt_ledger_does_not_stop_a_run(tmp_path: Path) -> None:
    store = JsonGateStore(tmp_path)
    store.history_path.parent.mkdir(parents=True, exist_ok=True)
    store.history_path.write_text("{not json", encoding="utf-8")
    assert store.load_history() == {}


def test_unreadable_record_is_skipped_not_fatal(tmp_path: Path) -> None:
    store = JsonGateStore(tmp_path)
    store.history_path.parent.mkdir(parents=True, exist_ok=True)
    store.history_path.write_text(
        json.dumps(
            {
                "records": {
                    "OK": {
                        "ticker": "OK",
                        "decision": "watchlist",
                        "reason_codes": ["no_catalyst_in_horizon"],
                        "first_flagged_on": "2026-08-01",
                        "last_flagged_on": "2026-08-01",
                        "occurrences": 1,
                    },
                    "BROKEN": {"ticker": "BROKEN"},
                }
            }
        ),
        encoding="utf-8",
    )
    history = store.load_history()
    assert list(history) == ["OK"]


def test_record_activity_window(tmp_path: Path) -> None:
    record = RejectionRecord(
        ticker="KO",
        decision=GateDecision.WATCHLIST,
        first_flagged_on=date(2026, 8, 1),
        last_flagged_on=date(2026, 8, 1),
    )
    assert record.is_active(date(2026, 8, 29), cooldown_days=30) is True
    assert record.is_active(date(2026, 9, 5), cooldown_days=30) is False
    assert record.is_active(date(2027, 1, 1), cooldown_days=0) is True


def test_store_honours_the_data_dir_environment_variable(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("BRIEFING_DATA_DIR", str(tmp_path / "envdata"))
    assert JsonGateStore().root == tmp_path / "envdata" / "candidate_gate"
