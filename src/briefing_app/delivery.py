"""Delivery adapters used by the n8n workflow (T11)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
import json
import os
import shutil


PUBLISHABLE_STATUSES = frozenset({"succeeded", "partial"})
DEFAULT_PUBLISH_SUBDIR = "published"


class DeliveryError(RuntimeError):
    """Raised when a run output cannot be delivered."""

    def __init__(
        self,
        reason: str,
        *,
        run_id: str | None = None,
        stage: str = "delivery_static",
        ticker: str = "*",
    ) -> None:
        self.run_id = run_id
        self.stage = stage
        self.ticker = ticker
        self.reason = reason
        super().__init__(reason)

    def to_dict(self) -> dict[str, str | None]:
        return {
            "run_id": self.run_id,
            "stage": self.stage,
            "ticker": self.ticker,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class StaticDeliveryResult:
    """Result returned after publishing dashboard artifacts to the static output tree."""

    adapter: str
    run_id: str
    run_date: str | None
    source_status: str
    published_at: datetime
    source_html_path: Path
    source_json_path: Path
    archive_html_path: Path
    archive_json_path: Path
    latest_html_path: Path
    latest_json_path: Path
    manifest_path: Path
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "run_id": self.run_id,
            "run_date": self.run_date,
            "source_status": self.source_status,
            "published_at": self.published_at.isoformat(),
            "source_html_path": str(self.source_html_path),
            "source_json_path": str(self.source_json_path),
            "archive_html_path": str(self.archive_html_path),
            "archive_json_path": str(self.archive_json_path),
            "latest_html_path": str(self.latest_html_path),
            "latest_json_path": str(self.latest_json_path),
            "manifest_path": str(self.manifest_path),
            "warnings": list(self.warnings),
        }


def publish_static_artifacts(
    run_output: Mapping[str, Any],
    *,
    output_root: str | Path | None = None,
    publish_subdir: str = DEFAULT_PUBLISH_SUBDIR,
) -> StaticDeliveryResult:
    """Publish generated dashboard HTML/JSON into stable static paths.

    The pipeline writes immutable run artifacts under `output/dashboard/<date>/`.
    n8n calls this adapter after a publishable app response so consumers can use stable
    `published/latest/*` links while the dated archive remains reconstructable.
    """

    root = _output_root(output_root)
    run_id = _required_text(run_output, "run_id")
    run_date = _optional_text(run_output, "run_date")
    source_status = _required_text(run_output, "status")
    if source_status not in PUBLISHABLE_STATUSES:
        raise DeliveryError(
            f"run status {source_status!r} is not publishable",
            run_id=run_id,
        )

    source_html = _artifact_path(run_output, "html_path", root, run_id)
    source_json = _artifact_path(run_output, "json_path", root, run_id)
    archive_dir = root / publish_subdir / (run_date or "undated") / run_id
    latest_dir = root / publish_subdir / "latest"
    archive_dir.mkdir(parents=True, exist_ok=True)
    latest_dir.mkdir(parents=True, exist_ok=True)

    archive_html = archive_dir / "dashboard.html"
    archive_json = archive_dir / "dashboard.json"
    latest_html = latest_dir / "dashboard.html"
    latest_json = latest_dir / "dashboard.json"

    shutil.copyfile(source_html, archive_html)
    shutil.copyfile(source_json, archive_json)
    shutil.copyfile(source_html, latest_html)
    shutil.copyfile(source_json, latest_json)

    warnings = []
    if source_status == "partial":
        warnings.append("Run completed with partial failures; dashboard was still published.")

    result = StaticDeliveryResult(
        adapter="static_html",
        run_id=run_id,
        run_date=run_date,
        source_status=source_status,
        published_at=datetime.now(UTC),
        source_html_path=source_html,
        source_json_path=source_json,
        archive_html_path=archive_html,
        archive_json_path=archive_json,
        latest_html_path=latest_html,
        latest_json_path=latest_json,
        manifest_path=latest_dir / "manifest.json",
        warnings=warnings,
    )
    _write_manifest(result, run_output)
    return result


def _write_manifest(result: StaticDeliveryResult, run_output: Mapping[str, Any]) -> None:
    manifest = {
        **result.to_dict(),
        "diagnostics": list(run_output.get("diagnostics") or []),
        "failures": list(run_output.get("failures") or []),
    }
    text = json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n"
    result.manifest_path.write_text(text, encoding="utf-8")
    archive_manifest = result.archive_html_path.parent / "manifest.json"
    archive_manifest.write_text(text, encoding="utf-8")


def _output_root(output_root: str | Path | None) -> Path:
    root = Path(output_root or os.getenv("BRIEFING_OUTPUT_DIR") or "output")
    return root.expanduser().resolve()


def _artifact_path(
    run_output: Mapping[str, Any],
    field: str,
    output_root: Path,
    run_id: str,
) -> Path:
    raw = _required_text(run_output, field)
    candidates = _path_candidates(raw, output_root)
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved.exists() and resolved.is_file():
            if not resolved.is_relative_to(output_root):
                raise DeliveryError(
                    f"{field} is outside output root: {resolved}",
                    run_id=run_id,
                )
            return resolved
    raise DeliveryError(f"{field} does not exist: {raw}", run_id=run_id)


def _path_candidates(raw: str, output_root: Path) -> list[Path]:
    path = Path(raw)
    candidates = [path]
    if path.is_absolute():
        for marker in (Path("/app/output"), Path("/output")):
            try:
                candidates.append(output_root / path.relative_to(marker))
            except ValueError:
                continue
    else:
        candidates.append(output_root / path)
        try:
            candidates.append(output_root / path.relative_to("output"))
        except ValueError:
            pass
    return candidates


def _required_text(run_output: Mapping[str, Any], field: str) -> str:
    value = _optional_text(run_output, field)
    if value is None:
        raise DeliveryError(f"missing required field {field!r}")
    return value


def _optional_text(run_output: Mapping[str, Any], field: str) -> str | None:
    value = run_output.get(field)
    if value is None:
        return None
    text = str(value).strip()
    return text or None
