from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import unittest

from sqlalchemy import create_engine, select

from briefing_app.storage import (
    StorageRepository,
    briefing_run,
    call_log,
    create_schema,
    daily_snapshot,
    evidence_ledger,
    setup_signal,
)


class StorageRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        create_schema(self.engine)
        self.repo = StorageRepository(self.engine)

    def test_upserts_are_idempotent_for_run_snapshot_call_and_evidence(self) -> None:
        run_date = date(2026, 8, 27)
        run_id = self.repo.upsert_briefing_run(run_date=run_date, status="running")
        rerun_id = self.repo.upsert_briefing_run(run_date=run_date, status="succeeded")

        self.assertEqual(run_id, rerun_id)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(briefing_run.c.id)).all(), [(run_id,)])

        self.repo.upsert_daily_snapshot(
            {
                "run_id": run_id,
                "ticker": "AAPL",
                "snap_date": run_date,
                "iv_rank": 40,
                "pc_ratio_vol": 0.70,
                "pc_ratio_oi": 0.90,
                "realized_vol_20d": 0.24,
                "component_scores": {"S_O": 0.20},
                "cte_score": 0.21,
                "confidence_tier": "B",
                "expression_class": "V",
            }
        )
        self.repo.upsert_daily_snapshot(
            {
                "run_id": run_id,
                "ticker": "AAPL",
                "snap_date": run_date,
                "iv_rank": 42,
                "pc_ratio_vol": 0.72,
                "pc_ratio_oi": 0.92,
                "realized_vol_20d": 0.25,
                "component_scores": {"S_O": 0.25},
                "cte_score": 0.23,
                "confidence_tier": "A",
                "expression_class": "V",
            }
        )
        with self.engine.connect() as conn:
            snapshots = conn.execute(select(daily_snapshot)).all()
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(float(snapshots[0]._mapping["iv_rank"]), 42.0)

        as_of = datetime(2026, 8, 27, 12, tzinfo=UTC)
        self.repo.upsert_evidence_rows(
            [
                {
                    "run_id": run_id,
                    "ticker": "AAPL",
                    "component": "S_O",
                    "field_name": "iv_rank",
                    "field_value": "40",
                    "source": "fixture",
                    "venue": "CBOE",
                    "as_of": as_of,
                    "endpoint_or_file": "fixtures/options/aapl.json",
                    "validation_status": "pending",
                }
            ]
        )
        self.repo.upsert_evidence_rows(
            [
                {
                    "run_id": run_id,
                    "ticker": "AAPL",
                    "component": "S_O",
                    "field_name": "iv_rank",
                    "field_value": 42,
                    "source": "fixture",
                    "venue": "CBOE",
                    "as_of": as_of,
                    "endpoint_or_file": "fixtures/options/aapl.json",
                    "validation_status": "verified",
                }
            ]
        )
        evidence = self.repo.evidence_for_run(run_id, ticker="AAPL")
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["field_value"], "42")
        self.assertEqual(evidence[0]["validation_status"], "verified")

        call_id = self.repo.upsert_call_log(
            {
                "run_id": run_id,
                "ticker": "AAPL",
                "made_on": run_date,
                "horizon": "1w",
                "expression_class": "V",
                "setup_type": "iron_condor",
                "predicted_low": 220,
                "predicted_high": 240,
            }
        )
        recalled_id = self.repo.upsert_call_log(
            {
                "run_id": run_id,
                "ticker": "AAPL",
                "made_on": run_date,
                "horizon": "1w",
                "expression_class": "V",
                "setup_type": "iron_condor",
                "predicted_low": 221,
                "predicted_high": 241,
            }
        )
        self.assertEqual(call_id, recalled_id)
        with self.engine.connect() as conn:
            calls = conn.execute(select(call_log)).all()
            self.assertEqual(len(calls), 1)
            self.assertEqual(float(calls[0]._mapping["predicted_low"]), 221.0)

    def test_seed_history_queries_are_deterministic(self) -> None:
        run_ids = []
        for offset, run_date in enumerate(
            [date(2026, 8, 24), date(2026, 8, 25), date(2026, 8, 26)]
        ):
            run_id = self.repo.upsert_briefing_run(run_date=run_date, status="succeeded")
            run_ids.append(run_id)
            self.repo.upsert_daily_snapshot(
                {
                    "run_id": run_id,
                    "ticker": "AAPL",
                    "snap_date": run_date,
                    "iv_rank": 30 + (offset * 10),
                    "pc_ratio_vol": 0.80 + (offset * 0.10),
                    "pc_ratio_oi": 1.10 + (offset * 0.20),
                    "realized_vol_20d": 0.20 + (offset * 0.01),
                    "component_scores": {"S_S": 0.10 + (offset * 0.05)},
                    "cte_score": 0.20 + (offset * 0.05),
                    "confidence_tier": "B",
                    "expression_class": "E",
                }
            )
            self.repo.upsert_component_score(
                {
                    "run_id": run_id,
                    "ticker": "AAPL",
                    "component": "S_S",
                    "score": 0.10 + (offset * 0.05),
                    "validation_status": "verified",
                    "source_quality": "fixture",
                }
            )

        self.repo.upsert_call_log(
            {
                "run_id": run_ids[-1],
                "ticker": "AAPL",
                "made_on": date(2026, 8, 26),
                "horizon": "1w",
                "expression_class": "E",
                "setup_type": "event_long",
                "predicted_low": 225,
                "predicted_high": 245,
            }
        )

        iv_history = self.repo.iv_rank_history("AAPL", through_date=date(2026, 8, 26), days=3)
        self.assertEqual([row["iv_rank"] for row in iv_history], [30.0, 40.0, 50.0])

        pc_baseline = self.repo.pc_baselines("AAPL", through_date=date(2026, 8, 26), days=3)
        self.assertEqual(pc_baseline["sample_count"], 3)
        self.assertAlmostEqual(pc_baseline["pc_ratio_vol"]["mean"], 0.90)
        self.assertAlmostEqual(pc_baseline["pc_ratio_oi"]["mean"], 1.30)

        sentiment = self.repo.sentiment_baseline("AAPL", through_date=date(2026, 8, 26), days=3)
        self.assertEqual(sentiment["sample_count"], 3)
        self.assertAlmostEqual(sentiment["score"]["mean"], 0.15)

        realized = self.repo.realized_vol_history("AAPL", through_date=date(2026, 8, 26), days=3)
        self.assertEqual([row["realized_vol_20d"] for row in realized], [0.20, 0.21, 0.22])

        unresolved = self.repo.unresolved_calls(ticker="AAPL", as_of=date(2026, 8, 27))
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]["setup_type"], "event_long")

        prior = self.repo.prior_scorecards(before_date=date(2026, 8, 27), ticker="AAPL", limit=2)
        self.assertEqual([row["snap_date"] for row in prior], [date(2026, 8, 26), date(2026, 8, 25)])
        self.assertEqual(prior[0]["confidence_tier"], "B")

    def test_setup_signal_round_trips_grade_fields_and_natural_key_update(self) -> None:
        run_date = date(2026, 8, 27)
        run_id = self.repo.upsert_briefing_run(run_date=run_date, status="succeeded")

        signal_id = self.repo.upsert_setup_signal(
            {
                "run_id": run_id,
                "ticker": "AAPL",
                "setup_type": "event_long",
                "horizon": "1w",
                "expression_class": "E",
                "grade_letter": "A",
                "grade_score": 0.92,
            }
        )
        updated_id = self.repo.upsert_setup_signal(
            {
                "run_id": run_id,
                "ticker": "AAPL",
                "setup_type": "event_long",
                "horizon": "1w",
                "expression_class": "E",
                "grade_letter": "B",
                "grade_score": 0.81,
            }
        )

        self.assertEqual(signal_id, updated_id)
        with self.engine.connect() as conn:
            signals = conn.execute(select(setup_signal)).all()
        self.assertEqual(len(signals), 1)
        row = signals[0]._mapping
        self.assertEqual(row["grade_letter"], "B")
        self.assertEqual(float(row["grade_score"]), 0.81)

    def test_setup_signal_allows_null_grade_fields_and_remains_idempotent(self) -> None:
        run_date = date(2026, 8, 28)
        run_id = self.repo.upsert_briefing_run(run_date=run_date, status="succeeded")

        signal = {
            "run_id": run_id,
            "ticker": "MSFT",
            "setup_type": "momentum_short",
            "horizon": "1m",
            "expression_class": "D",
            "grade_letter": None,
            "grade_score": None,
        }
        signal_id = self.repo.upsert_setup_signal(signal)
        repeated_id = self.repo.upsert_setup_signal(signal)

        self.assertEqual(signal_id, repeated_id)
        with self.engine.connect() as conn:
            signals = conn.execute(select(setup_signal)).all()
        self.assertEqual(len(signals), 1)
        row = signals[0]._mapping
        self.assertIsNone(row["grade_letter"])
        self.assertIsNone(row["grade_score"])


if __name__ == "__main__":
    unittest.main()


class SelfBuiltSeriesTest(unittest.TestCase):
    """The IV and put/call baselines are built from the app's own persisted snapshots."""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        create_schema(self.engine)
        self.repo = StorageRepository(self.engine)
        self.run_id = self.repo.upsert_briefing_run(
            run_date=date(2026, 8, 31), status="succeeded"
        )

    def _store(self, day: date, *, iv: float, pc_vol: float) -> None:
        self.repo.upsert_daily_snapshot(
            {
                "run_id": self.run_id,
                "ticker": "NVDA",
                "snap_date": day,
                "iv_atm": iv,
                "pc_ratio_vol": pc_vol,
                "pc_ratio_oi": pc_vol + 0.1,
            }
        )

    def test_history_returns_the_raw_inputs_a_rank_is_computed_from(self) -> None:
        """`iv_rank_history` reads the stored rank, which is None until a baseline exists.

        The series has to bootstrap from `iv_atm`, or it can never start.
        """

        for offset in range(1, 6):
            self._store(date(2026, 8, 31) - timedelta(days=offset), iv=0.30 + offset / 100, pc_vol=0.8)

        rows = self.repo.option_metric_history("NVDA", before_date=date(2026, 8, 31))
        self.assertEqual(len(rows), 5)
        self.assertEqual([row["iv_atm"] for row in rows][0], 0.35)
        self.assertTrue(all(row["pc_ratio_vol"] is not None for row in rows))

        # iv_rank is still empty, which is exactly why the raw series is needed.
        self.assertEqual(self.repo.iv_rank_history("NVDA"), [])

    def test_todays_snapshot_is_excluded_from_its_own_baseline(self) -> None:
        today = date(2026, 8, 31)
        self._store(today, iv=0.99, pc_vol=9.9)
        self._store(today - timedelta(days=1), iv=0.30, pc_vol=0.8)

        rows = self.repo.option_metric_history("NVDA", before_date=today)
        self.assertEqual([row["iv_atm"] for row in rows], [0.30])
