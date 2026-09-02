from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal
import os
from statistics import stdev
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    and_,
    create_engine,
    desc,
    func,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection, Engine


metadata = MetaData()


def _id_type() -> BigInteger:
    return BigInteger().with_variant(Integer, "sqlite")


def _json_type() -> JSON:
    return JSON().with_variant(JSONB, "postgresql")


briefing_run = Table(
    "briefing_run",
    metadata,
    Column("id", _id_type(), primary_key=True, autoincrement=True),
    Column("run_date", Date, nullable=False),
    Column("run_type", Text, nullable=False, default="daily"),
    Column("status", Text, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finished_at", DateTime(timezone=True)),
    Column("output_html_path", Text),
    Column("output_json_path", Text),
    Column("error", _json_type()),
    Column("details", _json_type(), nullable=False, default=dict),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("run_date", "run_type", name="ux_briefing_run_date_type"),
)

daily_snapshot = Table(
    "daily_snapshot",
    metadata,
    Column("ticker", Text, nullable=False),
    Column("snap_date", Date, nullable=False),
    Column("run_id", _id_type(), ForeignKey("briefing_run.id", ondelete="SET NULL")),
    Column("geography", Text),
    Column("spot", Numeric),
    Column("iv_atm", Numeric),
    Column("iv_rank", Numeric),
    Column("expected_move_1w", Numeric),
    Column("expected_move_1m", Numeric),
    Column("pc_ratio_vol", Numeric),
    Column("pc_ratio_oi", Numeric),
    Column("rr_25d", Numeric),
    Column("realized_vol_20d", Numeric),
    Column("component_scores", _json_type(), nullable=False, default=dict),
    Column("cte_score", Numeric),
    Column("confidence_tier", Text),
    Column("expression_class", Text),
    Column("raw", _json_type(), nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("ticker", "snap_date"),
)

evidence_ledger = Table(
    "evidence_ledger",
    metadata,
    Column("id", _id_type(), primary_key=True, autoincrement=True),
    Column("run_id", _id_type(), ForeignKey("briefing_run.id", ondelete="CASCADE"), nullable=False),
    Column("ticker", Text, nullable=False, default="*"),
    Column("component", Text, nullable=False),
    Column("field_name", Text, nullable=False),
    Column("field_value", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("venue", Text, nullable=False, default="*"),
    Column("as_of", DateTime(timezone=True), nullable=False),
    Column("endpoint_or_file", Text, nullable=False, default=""),
    Column("validation_status", Text, nullable=False),
    Column("note", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint(
        "run_id",
        "ticker",
        "component",
        "field_name",
        "source",
        "venue",
        "as_of",
        "endpoint_or_file",
        name="ux_evidence_ledger_natural",
    ),
)

candidate_gate = Table(
    "candidate_gate",
    metadata,
    Column("run_id", _id_type(), ForeignKey("briefing_run.id", ondelete="CASCADE"), nullable=False),
    Column("ticker", Text, nullable=False),
    Column("decision", Text, nullable=False),
    Column("reason", Text),
    Column("catalyst_name", Text),
    Column("catalyst_date", Date),
    Column("catalyst_status", Text),
    Column("expression_class", Text),
    Column("details", _json_type(), nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("run_id", "ticker"),
)

component_score = Table(
    "component_score",
    metadata,
    Column("run_id", _id_type(), ForeignKey("briefing_run.id", ondelete="CASCADE"), nullable=False),
    Column("ticker", Text, nullable=False),
    Column("component", Text, nullable=False),
    Column("score", Numeric),
    Column("original_weight", Numeric),
    Column("weight_used", Numeric),
    Column("validation_status", Text, nullable=False),
    Column("source_quality", Text),
    Column("required", Boolean, nullable=False, default=False),
    Column("missing_reason", Text),
    Column("details", _json_type(), nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("run_id", "ticker", "component"),
)

setup_signal = Table(
    "setup_signal",
    metadata,
    Column("id", _id_type(), primary_key=True, autoincrement=True),
    Column("run_id", _id_type(), ForeignKey("briefing_run.id", ondelete="CASCADE"), nullable=False),
    Column("ticker", Text, nullable=False),
    Column("setup_type", Text, nullable=False),
    Column("horizon", Text, nullable=False),
    Column("expression_class", Text, nullable=False),
    Column("direction", Text),
    Column("confidence_tier", Text),
    Column("cte_score", Numeric),
    Column("grade_letter", Text),
    Column("grade_score", Numeric),
    Column("instrument", Text),
    Column("invalidation", Text),
    Column("catalyst_date", Date),
    Column("range_low", Numeric),
    Column("range_high", Numeric),
    Column("scenario_probabilities", _json_type(), nullable=False, default=dict),
    Column("decision", Text, nullable=False, default="candidate"),
    Column("rationale", Text),
    Column("details", _json_type(), nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("run_id", "ticker", "setup_type", "horizon", name="ux_setup_signal_natural"),
)

call_log = Table(
    "call_log",
    metadata,
    Column("id", _id_type(), primary_key=True, autoincrement=True),
    Column("run_id", _id_type(), ForeignKey("briefing_run.id", ondelete="SET NULL")),
    Column("ticker", Text, nullable=False),
    Column("made_on", Date, nullable=False),
    Column("horizon", Text, nullable=False),
    Column("expression_class", Text, nullable=False),
    Column("predicted_low", Numeric),
    Column("predicted_high", Numeric),
    Column("confidence", Numeric),
    Column("setup_type", Text, nullable=False),
    Column("invalidation", Text),
    Column("catalyst_date", Date),
    Column("actual_close", Numeric),
    Column("inside_range", Boolean),
    Column("resolved_on", Date),
    Column("details", _json_type(), nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint(
        "ticker",
        "made_on",
        "horizon",
        "expression_class",
        "setup_type",
        name="ux_call_log_natural",
    ),
)

source_preflight = Table(
    "source_preflight",
    metadata,
    Column("run_id", _id_type(), ForeignKey("briefing_run.id", ondelete="CASCADE"), nullable=False),
    Column("source", Text, nullable=False),
    Column("endpoint", Text, nullable=False),
    Column("target", Text, nullable=False, default="*"),
    Column("status", Text, nullable=False),
    Column("entitlement_status", Text),
    Column("venue", Text),
    Column("checked_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("as_of", DateTime(timezone=True)),
    Column("latency_ms", Numeric),
    Column("validation_status", Text),
    Column("note", Text),
    Column("details", _json_type(), nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("run_id", "source", "endpoint", "target"),
)


def create_schema(engine: Engine) -> None:
    """Create repository tables for tests and local throwaway databases.

    Production Postgres should be initialized with the SQL files in migrations/.
    """

    metadata.create_all(engine)


def create_engine_from_env() -> Engine:
    database_url = os.environ["DATABASE_URL"]
    return create_engine(database_url, future=True)


class StorageRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    @classmethod
    def from_env(cls) -> "StorageRepository":
        return cls(create_engine_from_env())

    def upsert_briefing_run(
        self,
        *,
        run_date: date,
        status: str,
        run_type: str = "daily",
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        output_html_path: str | None = None,
        output_json_path: str | None = None,
        error: Mapping[str, Any] | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> int:
        values: dict[str, Any] = {
            "run_date": run_date,
            "run_type": run_type,
            "status": status,
            "details": dict(details or {}),
        }
        optional = {
            "started_at": started_at,
            "finished_at": finished_at,
            "output_html_path": output_html_path,
            "output_json_path": output_json_path,
            "error": dict(error) if error is not None else None,
        }
        values.update({key: value for key, value in optional.items() if value is not None})

        with self.engine.begin() as conn:
            return self._upsert_one(
                conn,
                briefing_run,
                values,
                conflict_columns=("run_date", "run_type"),
                returning_column="id",
            )

    def finish_briefing_run(
        self,
        run_id: int,
        *,
        status: str,
        finished_at: datetime,
        output_html_path: str | None = None,
        output_json_path: str | None = None,
        error: Mapping[str, Any] | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        values: dict[str, Any] = {
            "status": status,
            "finished_at": finished_at,
        }
        optional = {
            "output_html_path": output_html_path,
            "output_json_path": output_json_path,
            "error": dict(error) if error is not None else None,
            "details": dict(details) if details is not None else None,
        }
        values.update({key: value for key, value in optional.items() if value is not None})

        if "updated_at" in briefing_run.c:
            values["updated_at"] = func.now()

        with self.engine.begin() as conn:
            conn.execute(update(briefing_run).where(briefing_run.c.id == run_id).values(**values))

    def upsert_daily_snapshot(self, snapshot: Mapping[str, Any]) -> None:
        values = self._prepare_values(daily_snapshot, snapshot, required=("ticker", "snap_date"))
        values.setdefault("component_scores", {})
        values.setdefault("raw", {})
        with self.engine.begin() as conn:
            self._upsert_one(conn, daily_snapshot, values, conflict_columns=("ticker", "snap_date"))

    def upsert_evidence_rows(self, rows: Iterable[Mapping[str, Any]]) -> int:
        count = 0
        with self.engine.begin() as conn:
            for row in rows:
                values = self._prepare_values(
                    evidence_ledger,
                    row,
                    required=(
                        "run_id",
                        "component",
                        "field_name",
                        "field_value",
                        "source",
                        "as_of",
                        "validation_status",
                    ),
                )
                values["field_value"] = str(values["field_value"])
                values.setdefault("ticker", "*")
                values.setdefault("venue", "*")
                values.setdefault("endpoint_or_file", "")
                self._upsert_one(
                    conn,
                    evidence_ledger,
                    values,
                    conflict_columns=(
                        "run_id",
                        "ticker",
                        "component",
                        "field_name",
                        "source",
                        "venue",
                        "as_of",
                        "endpoint_or_file",
                    ),
                )
                count += 1
        return count

    def upsert_candidate_gate(self, gate: Mapping[str, Any]) -> None:
        values = self._prepare_values(candidate_gate, gate, required=("run_id", "ticker", "decision"))
        values.setdefault("details", {})
        with self.engine.begin() as conn:
            self._upsert_one(conn, candidate_gate, values, conflict_columns=("run_id", "ticker"))

    def upsert_component_score(self, score: Mapping[str, Any]) -> None:
        values = self._prepare_values(
            component_score,
            score,
            required=("run_id", "ticker", "component", "validation_status"),
        )
        values.setdefault("required", False)
        values.setdefault("details", {})
        with self.engine.begin() as conn:
            self._upsert_one(
                conn,
                component_score,
                values,
                conflict_columns=("run_id", "ticker", "component"),
            )

    def upsert_setup_signal(self, signal: Mapping[str, Any]) -> int:
        values = self._prepare_values(
            setup_signal,
            signal,
            required=("run_id", "ticker", "setup_type", "horizon", "expression_class"),
        )
        values.setdefault("decision", "candidate")
        values.setdefault("scenario_probabilities", {})
        values.setdefault("details", {})
        with self.engine.begin() as conn:
            return self._upsert_one(
                conn,
                setup_signal,
                values,
                conflict_columns=("run_id", "ticker", "setup_type", "horizon"),
                returning_column="id",
            )

    def upsert_call_log(self, call: Mapping[str, Any]) -> int:
        values = self._prepare_values(
            call_log,
            call,
            required=("ticker", "made_on", "horizon", "expression_class", "setup_type"),
        )
        values.setdefault("details", {})
        with self.engine.begin() as conn:
            return self._upsert_one(
                conn,
                call_log,
                values,
                conflict_columns=("ticker", "made_on", "horizon", "expression_class", "setup_type"),
                returning_column="id",
            )

    def upsert_source_preflight(self, preflight: Mapping[str, Any]) -> None:
        values = self._prepare_values(
            source_preflight,
            preflight,
            required=("run_id", "source", "endpoint", "status"),
        )
        values.setdefault("target", "*")
        values.setdefault("details", {})
        with self.engine.begin() as conn:
            self._upsert_one(
                conn,
                source_preflight,
                values,
                conflict_columns=("run_id", "source", "endpoint", "target"),
            )

    def iv_rank_history(
        self,
        ticker: str,
        *,
        through_date: date | None = None,
        days: int = 252,
    ) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            through_date = through_date or self._latest_snapshot_date(conn, ticker, daily_snapshot.c.iv_rank)
            if through_date is None:
                return []

            stmt = (
                select(daily_snapshot.c.snap_date, daily_snapshot.c.iv_rank)
                .where(
                    and_(
                        daily_snapshot.c.ticker == ticker,
                        daily_snapshot.c.iv_rank.is_not(None),
                        daily_snapshot.c.snap_date <= through_date,
                        daily_snapshot.c.snap_date >= self._window_start(through_date, days),
                    )
                )
                .order_by(daily_snapshot.c.snap_date)
            )
            return [_row_to_dict(row) for row in conn.execute(stmt)]

    def option_metric_history(
        self,
        ticker: str,
        *,
        before_date: date,
        days: int = 252,
    ) -> list[dict[str, Any]]:
        """Trailing ATM IV and put/call ratios, for the self-built baselines.

        `iv_rank_history` reads the stored *rank*, which is `None` until a baseline
        already exists; this returns the raw inputs a rank is computed from, so the
        series can bootstrap itself from runs the pipeline has already persisted.

        `before_date` is exclusive: today's own snapshot must not be part of the history
        today's reading is ranked against.
        """

        with self.engine.connect() as conn:
            stmt = (
                select(
                    daily_snapshot.c.snap_date,
                    daily_snapshot.c.iv_atm,
                    daily_snapshot.c.pc_ratio_vol,
                    daily_snapshot.c.pc_ratio_oi,
                )
                .where(
                    and_(
                        daily_snapshot.c.ticker == ticker,
                        daily_snapshot.c.snap_date < before_date,
                        daily_snapshot.c.snap_date >= self._window_start(before_date, days),
                    )
                )
                .order_by(daily_snapshot.c.snap_date)
            )
            return [_row_to_dict(row) for row in conn.execute(stmt)]

    def pc_baselines(
        self,
        ticker: str,
        *,
        through_date: date | None = None,
        days: int = 252,
    ) -> dict[str, Any]:
        with self.engine.connect() as conn:
            through_date = through_date or self._latest_snapshot_date(
                conn,
                ticker,
                daily_snapshot.c.pc_ratio_vol,
                daily_snapshot.c.pc_ratio_oi,
            )
            if through_date is None:
                baseline = _empty_baseline(ticker, days)
                baseline["pc_ratio_vol"] = _empty_numeric_stats()
                baseline["pc_ratio_oi"] = _empty_numeric_stats()
                return baseline

            stmt = (
                select(
                    daily_snapshot.c.snap_date,
                    daily_snapshot.c.pc_ratio_vol,
                    daily_snapshot.c.pc_ratio_oi,
                )
                .where(
                    and_(
                        daily_snapshot.c.ticker == ticker,
                        or_(
                            daily_snapshot.c.pc_ratio_vol.is_not(None),
                            daily_snapshot.c.pc_ratio_oi.is_not(None),
                        ),
                        daily_snapshot.c.snap_date <= through_date,
                        daily_snapshot.c.snap_date >= self._window_start(through_date, days),
                    )
                )
                .order_by(daily_snapshot.c.snap_date)
            )
            rows = [_row_to_dict(row) for row in conn.execute(stmt)]
            return {
                "ticker": ticker,
                "through_date": through_date,
                "window_days": days,
                "sample_count": len(rows),
                "pc_ratio_vol": _numeric_stats(row["pc_ratio_vol"] for row in rows),
                "pc_ratio_oi": _numeric_stats(row["pc_ratio_oi"] for row in rows),
            }

    def sentiment_baseline(
        self,
        ticker: str,
        *,
        through_date: date | None = None,
        days: int = 7,
    ) -> dict[str, Any]:
        with self.engine.connect() as conn:
            through_date = through_date or self._latest_component_date(conn, ticker, "S_S")
            if through_date is None:
                baseline = _empty_baseline(ticker, days)
                baseline["score"] = _empty_numeric_stats()
                baseline["samples"] = []
                return baseline

            stmt = (
                select(
                    briefing_run.c.run_date,
                    component_score.c.score,
                    component_score.c.validation_status,
                    component_score.c.source_quality,
                    component_score.c.details,
                )
                .select_from(component_score.join(briefing_run, component_score.c.run_id == briefing_run.c.id))
                .where(
                    and_(
                        component_score.c.ticker == ticker,
                        component_score.c.component == "S_S",
                        component_score.c.score.is_not(None),
                        briefing_run.c.run_date <= through_date,
                        briefing_run.c.run_date >= self._window_start(through_date, days),
                    )
                )
                .order_by(briefing_run.c.run_date)
            )
            rows = [_row_to_dict(row) for row in conn.execute(stmt)]
            return {
                "ticker": ticker,
                "through_date": through_date,
                "window_days": days,
                "sample_count": len(rows),
                "score": _numeric_stats(row["score"] for row in rows),
                "samples": rows,
            }

    def realized_vol_history(
        self,
        ticker: str,
        *,
        through_date: date | None = None,
        days: int = 252,
    ) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            through_date = through_date or self._latest_snapshot_date(
                conn,
                ticker,
                daily_snapshot.c.realized_vol_20d,
            )
            if through_date is None:
                return []

            stmt = (
                select(daily_snapshot.c.snap_date, daily_snapshot.c.realized_vol_20d)
                .where(
                    and_(
                        daily_snapshot.c.ticker == ticker,
                        daily_snapshot.c.realized_vol_20d.is_not(None),
                        daily_snapshot.c.snap_date <= through_date,
                        daily_snapshot.c.snap_date >= self._window_start(through_date, days),
                    )
                )
                .order_by(daily_snapshot.c.snap_date)
            )
            return [_row_to_dict(row) for row in conn.execute(stmt)]

    def unresolved_calls(self, *, ticker: str | None = None, as_of: date | None = None) -> list[dict[str, Any]]:
        filters = [call_log.c.resolved_on.is_(None)]
        if ticker is not None:
            filters.append(call_log.c.ticker == ticker)
        if as_of is not None:
            filters.append(call_log.c.made_on <= as_of)

        stmt = (
            select(call_log)
            .where(and_(*filters))
            .order_by(call_log.c.made_on, call_log.c.ticker, call_log.c.horizon)
        )
        with self.engine.connect() as conn:
            return [_row_to_dict(row) for row in conn.execute(stmt)]

    def prior_scorecards(
        self,
        *,
        before_date: date,
        ticker: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        filters = [daily_snapshot.c.snap_date < before_date]
        if ticker is not None:
            filters.append(daily_snapshot.c.ticker == ticker)

        stmt = (
            select(
                daily_snapshot.c.ticker,
                daily_snapshot.c.snap_date,
                daily_snapshot.c.component_scores,
                daily_snapshot.c.cte_score,
                daily_snapshot.c.confidence_tier,
                daily_snapshot.c.expression_class,
            )
            .where(and_(*filters))
            .order_by(desc(daily_snapshot.c.snap_date), daily_snapshot.c.ticker)
            .limit(limit)
        )
        with self.engine.connect() as conn:
            return [_row_to_dict(row) for row in conn.execute(stmt)]

    def evidence_for_run(self, run_id: int, *, ticker: str | None = None) -> list[dict[str, Any]]:
        filters = [evidence_ledger.c.run_id == run_id]
        if ticker is not None:
            filters.append(evidence_ledger.c.ticker == ticker)

        stmt = (
            select(evidence_ledger)
            .where(and_(*filters))
            .order_by(
                evidence_ledger.c.ticker,
                evidence_ledger.c.component,
                evidence_ledger.c.field_name,
                evidence_ledger.c.source,
            )
        )
        with self.engine.connect() as conn:
            return [_row_to_dict(row) for row in conn.execute(stmt)]

    def source_preflight_for_run(self, run_id: int) -> list[dict[str, Any]]:
        stmt = (
            select(source_preflight)
            .where(source_preflight.c.run_id == run_id)
            .order_by(source_preflight.c.source, source_preflight.c.endpoint, source_preflight.c.target)
        )
        with self.engine.connect() as conn:
            return [_row_to_dict(row) for row in conn.execute(stmt)]

    @staticmethod
    def _prepare_values(
        table: Table,
        values: Mapping[str, Any],
        *,
        required: tuple[str, ...],
    ) -> dict[str, Any]:
        row = dict(values)
        unknown = sorted(set(row) - set(table.c.keys()))
        if unknown:
            raise ValueError(f"Unknown columns for {table.name}: {', '.join(unknown)}")

        missing = [key for key in required if key not in row or row[key] is None]
        if missing:
            raise ValueError(f"Missing required columns for {table.name}: {', '.join(missing)}")
        return row

    @staticmethod
    def _window_start(through_date: date, days: int) -> date:
        if days <= 0:
            raise ValueError("days must be positive")
        return through_date - timedelta(days=days - 1)

    @staticmethod
    def _insert_for_connection(conn: Connection, table: Table):
        if conn.dialect.name == "postgresql":
            return postgresql_insert(table)
        if conn.dialect.name == "sqlite":
            return sqlite_insert(table)
        raise NotImplementedError(f"Unsupported database dialect: {conn.dialect.name}")

    @classmethod
    def _upsert_one(
        cls,
        conn: Connection,
        table: Table,
        values: Mapping[str, Any],
        *,
        conflict_columns: tuple[str, ...],
        returning_column: str | None = None,
    ) -> Any:
        insert_stmt = cls._insert_for_connection(conn, table).values(**values)
        update_columns = [
            key
            for key in values
            if key not in set(conflict_columns) | {"id", "created_at", "updated_at"}
        ]
        update_values = {key: getattr(insert_stmt.excluded, key) for key in update_columns}
        if "updated_at" in table.c:
            update_values["updated_at"] = func.now()

        stmt = insert_stmt.on_conflict_do_update(
            index_elements=[table.c[column] for column in conflict_columns],
            set_=update_values,
        )
        if returning_column is not None:
            stmt = stmt.returning(table.c[returning_column])
            return conn.execute(stmt).scalar_one()

        conn.execute(stmt)
        return None

    @staticmethod
    def _latest_snapshot_date(
        conn: Connection,
        ticker: str,
        *metric_columns: Column[Any],
    ) -> date | None:
        filters = [daily_snapshot.c.ticker == ticker]
        if metric_columns:
            filters.append(or_(*(column.is_not(None) for column in metric_columns)))
        stmt = select(func.max(daily_snapshot.c.snap_date)).where(and_(*filters))
        return conn.execute(stmt).scalar_one_or_none()

    @staticmethod
    def _latest_component_date(conn: Connection, ticker: str, component: str) -> date | None:
        stmt = (
            select(func.max(briefing_run.c.run_date))
            .select_from(component_score.join(briefing_run, component_score.c.run_id == briefing_run.c.id))
            .where(
                and_(
                    component_score.c.ticker == ticker,
                    component_score.c.component == component,
                    component_score.c.score.is_not(None),
                )
            )
        )
        return conn.execute(stmt).scalar_one_or_none()


def _empty_baseline(ticker: str, days: int) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "through_date": None,
        "window_days": days,
        "sample_count": 0,
    }


def _numeric_stats(values: Iterable[Any]) -> dict[str, Any]:
    nums = [_as_float(value) for value in values if value is not None]
    return {
        "count": len(nums),
        "mean": sum(nums) / len(nums) if nums else None,
        "stdev": stdev(nums) if len(nums) > 1 else None,
        "min": min(nums) if nums else None,
        "max": max(nums) if nums else None,
    }


def _empty_numeric_stats() -> dict[str, Any]:
    return {
        "count": 0,
        "mean": None,
        "stdev": None,
        "min": None,
        "max": None,
    }


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {key: _normalize_value(value) for key, value in row._mapping.items()}


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def _as_float(value: Any) -> float:
    if isinstance(value, Decimal):
        return float(value)
    return float(value)
