from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
DEFAULT_ENV_FILE = REPO_ROOT / ".env"


def configure_environment() -> Path:
    """Prepare a launchd-friendly process environment."""

    os.chdir(REPO_ROOT)
    src = str(SRC_DIR)
    if src not in sys.path:
        sys.path.insert(0, src)
    load_env_file(DEFAULT_ENV_FILE)
    _normalize_repo_path_env(
        "BRIEFING_CONFIG_PATH",
        "BRIEFING_SOURCE_REGISTRY_PATH",
        "BRIEFING_DATA_DIR",
        "BRIEFING_OUTPUT_DIR",
        "APP_RUN_TOKEN_FILE",
    )
    os.environ.setdefault("BRIEFING_CONFIG_PATH", "config/config.example.yaml")
    os.environ.setdefault("BRIEFING_SOURCE_REGISTRY_PATH", "config/source_registry.yaml")
    os.environ.setdefault("BRIEFING_DATA_DIR", "data")
    os.environ.setdefault("BRIEFING_OUTPUT_DIR", "output")
    os.environ.setdefault("BRIEFING_LOCAL_SQLITE", "1")
    os.environ.setdefault("APP_RUN_TOKEN_FILE", "data/ops/run-token")
    os.environ.setdefault("GENERIC_TIMEZONE", "Europe/Lisbon")
    return REPO_ROOT


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = _clean_env_value(value)


def data_dir() -> Path:
    return Path(os.getenv("BRIEFING_DATA_DIR") or "data").expanduser()


def output_dir() -> Path:
    return Path(os.getenv("BRIEFING_OUTPUT_DIR") or "output").expanduser()


def ops_dir() -> Path:
    return data_dir() / "ops"


def last_run_path() -> Path:
    return ops_dir() / "last-run.json"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def _clean_env_value(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        return cleaned[1:-1]
    return cleaned


def _normalize_repo_path_env(*names: str) -> None:
    for name in names:
        value = os.environ.get(name)
        if not value:
            continue
        if value == "/app":
            os.environ[name] = str(REPO_ROOT)
        elif value.startswith("/app/"):
            os.environ[name] = str(REPO_ROOT / value.removeprefix("/app/"))
