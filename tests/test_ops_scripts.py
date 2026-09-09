from __future__ import annotations

import importlib.util
from datetime import date
import plistlib
import sys
from pathlib import Path

import pytest


def test_run_daily_resolves_explicit_env_and_configured_data_mode(monkeypatch) -> None:
    module = _load_ops_module("run_daily")

    monkeypatch.delenv("BRIEFING_DATA_MODE", raising=False)
    assert module._resolve_data_mode(None, "fixture") == "fixture"
    assert module._resolve_data_mode("live", "fixture") == "live"

    monkeypatch.setenv("BRIEFING_DATA_MODE", "live")
    assert module._resolve_data_mode(None, "fixture") == "live"
    assert module._resolve_data_mode("fixture", "live") == "fixture"

    monkeypatch.setenv("BRIEFING_DATA_MODE", "paper")
    with pytest.raises(ValueError, match="BRIEFING_DATA_MODE"):
        module._resolve_data_mode(None, "fixture")


def test_status_explains_non_clean_job_record(monkeypatch, tmp_path) -> None:
    module = _load_ops_module("status")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text('{"run_id": "daily-2026-09-07"}', encoding="utf-8")
    monkeypatch.setattr(module, "_local_today", lambda: date(2026, 9, 7))

    derived = module._derive_status(
        {
            "ok": False,
            "run": {"run_id": "daily-2026-09-07", "run_date": "2026-09-07", "status": "succeeded"},
            "delivery": {"manifest_path": str(manifest_path)},
            "error": None,
        }
    )

    assert derived["ok"] is False
    assert derived["attention"] == ["latest local job did not complete cleanly"]


def test_install_launchd_creates_log_directory_when_installing(monkeypatch, tmp_path) -> None:
    module = _load_ops_module("install_launchd")
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "configure_environment", lambda: tmp_path)
    target = tmp_path / "LaunchAgents" / module.PLIST_NAME
    monkeypatch.setattr(module, "_user_launch_agent_path", lambda: target)

    assert module.main(["--install"]) == 0
    assert (tmp_path / "data/ops").is_dir()

    with target.open("rb") as handle:
        plist = plistlib.load(handle)
    assert plist["StandardOutPath"] == str(tmp_path / "data/ops/launchd.out.log")
    assert plist["StandardErrorPath"] == str(tmp_path / "data/ops/launchd.err.log")


def _load_ops_module(name: str):
    ops_dir = Path(__file__).resolve().parents[1] / "ops"
    sys.path.insert(0, str(ops_dir))
    spec = importlib.util.spec_from_file_location(f"briefing_ops_{name}", ops_dir / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
