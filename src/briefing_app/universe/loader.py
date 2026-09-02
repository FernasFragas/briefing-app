"""Universe construction: fixed briefing universe and idea-screening candidates.

Two modes, per plan Phase 2:

1. Fixed briefing universe - 8-12 liquid names the user follows.
2. Idea-screening universe - 15-30 raw candidates from sector maps, screens, and
   manual watchlists.

Both produce the same `Candidate` contract. A malformed record never kills the run: it
is collected as a load error and reported alongside the gate output.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml
from pydantic import ValidationError

from briefing_app.config import AppConfig, CandidateDefaults, UniverseSettings
from briefing_app.models.candidate import Candidate, CandidateSource

#: Candidate keys populated from `candidate_defaults` when a record omits them.
_DEFAULTABLE_FIELDS: tuple[str, ...] = (
    "venue",
    "geography",
    "country",
    "currency",
    "sector",
    "thesis",
    "direction",
    "horizon_days",
    "expression_class",
    "broker",
    "permitted_instruments",
    "crowding",
)

#: CSV columns that describe the single catalyst carried on that row.
_CSV_CATALYST_FIELDS: dict[str, str] = {
    "catalyst_name": "name",
    "catalyst_date": "date",
    "catalyst_status": "status",
    "catalyst_kind": "kind",
    "catalyst_source": "source",
    "catalyst_note": "note",
    "catalyst_telegraphed": "telegraphed",
}

_LIST_SEPARATOR = "|"
_TRUTHY = {"1", "true", "yes", "y"}


class UniverseLoadError(RuntimeError):
    """Raised when a candidate file is missing or structurally unreadable."""


@dataclass
class LoadResult:
    """Loaded candidates plus everything that went wrong while loading them."""

    candidates: list[Candidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def extend(self, other: LoadResult) -> None:
        self.candidates.extend(other.candidates)
        self.warnings.extend(other.warnings)
        self.errors.extend(other.errors)


def _split_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return None
    separator = _LIST_SEPARATOR if _LIST_SEPARATOR in text else ","
    return [part.strip() for part in text.split(separator) if part.strip()]


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in _TRUTHY


def _apply_defaults(record: dict[str, Any], defaults: CandidateDefaults) -> dict[str, Any]:
    merged = dict(record)
    default_values = defaults.model_dump()
    for key in _DEFAULTABLE_FIELDS:
        default = default_values[key]
        # An unset default must not mask "field required" with "wrong type".
        if default is not None and merged.get(key) in (None, "", [], {}):
            merged[key] = default
    return merged


def _build_candidate(
    record: dict[str, Any],
    *,
    defaults: CandidateDefaults,
    source: CandidateSource,
    origin: str,
    result: LoadResult,
) -> Candidate | None:
    merged = _apply_defaults(record, defaults)
    merged.setdefault("source", source)
    merged.setdefault("origin", origin)
    try:
        return Candidate.model_validate(merged)
    except ValidationError as exc:
        ticker = record.get("ticker") or "<no ticker>"
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        result.errors.append(f"{origin}: candidate {ticker} rejected - {problems}")
        return None


def _records_from_yaml(payload: Any, origin: str) -> tuple[list[Any], dict[str, Any], Any]:
    """Return `(records, file_defaults, declared_source)` for a YAML candidate file."""
    if isinstance(payload, list):
        return payload, {}, None
    if isinstance(payload, dict):
        for key in ("candidates", "universe", "tickers"):
            if key in payload:
                records = payload[key] or []
                if not isinstance(records, list):
                    raise UniverseLoadError(f"{origin}: `{key}` must be a list.")
                return records, payload.get("defaults") or {}, payload.get("source")
        raise UniverseLoadError(
            f"{origin}: expected a list, or a mapping with a `candidates` key."
        )
    raise UniverseLoadError(f"{origin}: unsupported YAML structure.")


def load_candidates_from_records(
    records: Iterable[Any],
    *,
    defaults: CandidateDefaults,
    source: CandidateSource,
    origin: str,
) -> LoadResult:
    """Build candidates from raw mappings. A bare string is treated as a ticker."""
    result = LoadResult()
    for index, record in enumerate(records, start=1):
        if isinstance(record, str):
            record = {"ticker": record}
        if not isinstance(record, dict):
            result.errors.append(f"{origin}: entry {index} is not a mapping or ticker string.")
            continue
        candidate = _build_candidate(
            record, defaults=defaults, source=source, origin=origin, result=result
        )
        if candidate is not None:
            result.candidates.append(candidate)
    return result


def load_candidates_from_yaml(
    path: Path, *, defaults: CandidateDefaults, source: CandidateSource
) -> LoadResult:
    origin = str(path)
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise UniverseLoadError(f"Candidate file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise UniverseLoadError(f"Could not parse {path}: {exc}") from exc

    if payload is None:
        return LoadResult(warnings=[f"{origin}: file is empty."])

    records, file_defaults, declared_source = _records_from_yaml(payload, origin)
    if file_defaults:
        if not isinstance(file_defaults, dict):
            raise UniverseLoadError(f"{origin}: `defaults` must be a mapping.")
        # File-level defaults override config defaults key by key, never wholesale.
        merged_defaults = CandidateDefaults.model_validate(
            {**defaults.model_dump(), **file_defaults}
        )
    else:
        merged_defaults = defaults
    effective_source = CandidateSource(declared_source) if declared_source else source
    return load_candidates_from_records(
        records, defaults=merged_defaults, source=effective_source, origin=origin
    )


def load_candidates_from_csv(
    path: Path, *, defaults: CandidateDefaults, source: CandidateSource
) -> LoadResult:
    """Manual-watchlist CSV. Repeat a ticker across rows to attach several catalysts."""
    origin = str(path)
    result = LoadResult()
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise UniverseLoadError(f"Candidate file not found: {path}") from exc

    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None:
        return LoadResult(warnings=[f"{origin}: file has no header row."])

    records: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for line_number, row in enumerate(reader, start=2):
        cleaned = {
            (key or "").strip().lower(): (value.strip() if isinstance(value, str) else value)
            for key, value in row.items()
            if key
        }
        ticker = (cleaned.get("ticker") or "").upper()
        if not ticker:
            result.errors.append(f"{origin}:{line_number}: row has no ticker.")
            continue

        catalyst = _catalyst_from_row(cleaned)
        if ticker in records:
            if catalyst:
                records[ticker]["catalysts"].append(catalyst)
            continue

        record: dict[str, Any] = {"ticker": ticker, "catalysts": []}
        for key, value in cleaned.items():
            if key in _CSV_CATALYST_FIELDS or key == "ticker" or value in (None, ""):
                continue
            if key in {"permitted_instruments", "tags"}:
                record[key] = _split_list(value)
            elif key == "thesis_source":
                record["thesis_sources"] = [
                    {
                        "label": value,
                        "kind": cleaned.get("thesis_source_kind") or "unverified",
                    }
                ]
            elif key == "thesis_source_kind":
                continue
            else:
                record[key] = value
        if catalyst:
            record["catalysts"].append(catalyst)
        records[ticker] = record
        order.append(ticker)

    for ticker in order:
        candidate = _build_candidate(
            records[ticker], defaults=defaults, source=source, origin=origin, result=result
        )
        if candidate is not None:
            result.candidates.append(candidate)
    return result


def _catalyst_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    if not row.get("catalyst_date"):
        return None
    catalyst: dict[str, Any] = {}
    for column, key in _CSV_CATALYST_FIELDS.items():
        value = row.get(column)
        if value in (None, ""):
            continue
        catalyst[key] = _as_bool(value) if key == "telegraphed" else value
    catalyst.setdefault("name", row.get("ticker", "catalyst"))
    catalyst.setdefault("status", "estimated")
    return catalyst


def load_candidate_file(
    path: Path, *, defaults: CandidateDefaults, source: CandidateSource
) -> LoadResult:
    if not path.exists():
        raise UniverseLoadError(f"Candidate file not found: {path}")
    if path.suffix.lower() in {".csv", ".tsv"}:
        return load_candidates_from_csv(path, defaults=defaults, source=source)
    return load_candidates_from_yaml(path, defaults=defaults, source=source)


def _check_count(result: LoadResult, label: str, count: int, low: int, high: int) -> None:
    if count == 0:
        return
    if count < low:
        result.warnings.append(f"{label}: {count} candidates loaded, expected at least {low}.")
    elif high and count > high:
        result.warnings.append(f"{label}: {count} candidates loaded, expected at most {high}.")


def load_fixed_universe(config: AppConfig) -> LoadResult:
    """The 8-12 watched names, from inline `universe.fixed` and/or `universe.fixed_files`."""
    settings: UniverseSettings = config.universe
    result = LoadResult()

    if settings.fixed:
        result.extend(
            load_candidates_from_records(
                settings.fixed,
                defaults=config.candidate_defaults,
                source=CandidateSource.FIXED_UNIVERSE,
                origin=f"{config.config_path or 'config'}#universe.fixed",
            )
        )
    for raw_path in settings.fixed_files:
        result.extend(
            load_candidate_file(
                config.resolve_path(raw_path),
                defaults=config.candidate_defaults,
                source=CandidateSource.FIXED_UNIVERSE,
            )
        )

    _check_count(
        result, "Fixed universe", len(result.candidates), settings.fixed_min, settings.fixed_max
    )
    return result


def load_screen_candidates(config: AppConfig) -> LoadResult:
    """The 15-30 raw idea-screening candidates from screens, sector maps, watchlists."""
    settings: UniverseSettings = config.universe
    result = LoadResult()
    for raw_path in settings.candidate_files:
        result.extend(
            load_candidate_file(
                config.resolve_path(raw_path),
                defaults=config.candidate_defaults,
                source=CandidateSource.SCREEN,
            )
        )
    _check_count(
        result,
        "Screening universe",
        len(result.candidates),
        settings.screen_min,
        settings.screen_max,
    )
    return result


def load_universe(config: AppConfig, mode: str | None = None) -> LoadResult:
    """Load the configured universe. Duplicate tickers are kept for the gate to reject."""
    effective_mode = mode or config.universe.mode
    if effective_mode not in {"fixed", "screen", "both"}:
        raise UniverseLoadError(f"Unknown universe mode: {effective_mode}")

    result = LoadResult()
    if effective_mode in {"fixed", "both"}:
        result.extend(load_fixed_universe(config))
    if effective_mode in {"screen", "both"}:
        result.extend(load_screen_candidates(config))

    if not result.candidates:
        result.warnings.append(
            f"Universe mode `{effective_mode}` produced no candidates. "
            "Check universe.fixed, universe.fixed_files, and universe.candidate_files."
        )
    return result
