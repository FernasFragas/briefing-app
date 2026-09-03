"""T11 static delivery adapter and API endpoint."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from briefing_app.api import app
from briefing_app.delivery import DeliveryError, publish_static_artifacts


def test_static_delivery_publishes_latest_and_archive_paths(tmp_path) -> None:
    output_root = tmp_path / "output"
    run_output = run_payload(output_root, container_paths=True)

    result = publish_static_artifacts(run_output, output_root=output_root)

    assert result.adapter == "static_html"
    assert result.run_id == run_output["run_id"]
    assert result.latest_html_path.read_text(encoding="utf-8") == "<!doctype html>\n"
    assert json.loads(result.latest_json_path.read_text(encoding="utf-8"))["run_id"] == run_output["run_id"]
    assert result.archive_html_path.exists()
    assert result.archive_json_path.exists()

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["adapter"] == "static_html"
    assert manifest["latest_html_path"] == str(result.latest_html_path)
    assert manifest["source_status"] == "succeeded"


def test_static_delivery_rejects_failed_or_missing_artifacts(tmp_path) -> None:
    output_root = tmp_path / "output"
    failed = run_payload(output_root) | {"status": "failed"}
    with pytest.raises(DeliveryError) as failed_error:
        publish_static_artifacts(failed, output_root=output_root)
    assert failed_error.value.to_dict() == {
        "run_id": failed["run_id"],
        "stage": "delivery_static",
        "ticker": "*",
        "reason": "run status 'failed' is not publishable",
    }

    missing = run_payload(output_root)
    Path(missing["html_path"]).unlink()
    with pytest.raises(DeliveryError) as missing_error:
        publish_static_artifacts(missing, output_root=output_root)
    assert "html_path does not exist" in missing_error.value.reason


def test_static_delivery_endpoint_requires_token_and_returns_error_contract(
    tmp_path,
    monkeypatch,
) -> None:
    output_root = tmp_path / "output"
    payload = run_payload(output_root, container_paths=True)
    monkeypatch.setenv("APP_RUN_TOKEN", "secret-token")
    monkeypatch.setenv("BRIEFING_OUTPUT_DIR", str(output_root))
    client = TestClient(app)

    assert client.post("/delivery/static", json=payload).status_code == 401

    response = client.post(
        "/delivery/static",
        json=payload,
        headers={"Authorization": "Bearer secret-token"},
    )
    assert response.status_code == 200
    delivered = response.json()
    assert delivered["adapter"] == "static_html"
    assert Path(delivered["latest_html_path"]).exists()
    assert Path(delivered["latest_json_path"]).exists()

    failed = payload | {"status": "failed"}
    error_response = client.post(
        "/delivery/static",
        json=failed,
        headers={"Authorization": "Bearer secret-token"},
    )
    assert error_response.status_code == 500
    assert error_response.json()["detail"] == {
        "run_id": payload["run_id"],
        "stage": "delivery_static",
        "ticker": "*",
        "reason": "run status 'failed' is not publishable",
    }


def test_app_daily_endpoint_output_can_be_published_by_static_delivery(
    tmp_path,
    monkeypatch,
) -> None:
    output_root = tmp_path / "output"
    data_root = tmp_path / "data"
    monkeypatch.setenv("APP_RUN_TOKEN", "secret-token")
    monkeypatch.setenv("BRIEFING_OUTPUT_DIR", str(output_root))
    monkeypatch.setenv("BRIEFING_DATA_DIR", str(data_root))
    monkeypatch.setenv("BRIEFING_CONFIG_PATH", "config/config.example.yaml")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = TestClient(app)
    headers = {"Authorization": "Bearer secret-token"}

    run_response = client.post(
        "/run/daily?run_date=2026-08-28&force=true&max_tickers=1",
        headers=headers,
    )
    assert run_response.status_code == 200
    run_output = run_response.json()
    assert run_output["status"] == "succeeded"
    assert Path(run_output["html_path"]).exists()
    assert Path(run_output["json_path"]).exists()

    delivery_response = client.post("/delivery/static", json=run_output, headers=headers)
    assert delivery_response.status_code == 200
    delivered = delivery_response.json()
    assert Path(delivered["latest_html_path"]).exists()
    assert Path(delivered["latest_json_path"]).exists()
    assert json.loads(Path(delivered["manifest_path"]).read_text(encoding="utf-8"))[
        "run_id"
    ] == run_output["run_id"]


def run_payload(output_root: Path, *, container_paths: bool = False) -> dict[str, object]:
    run_id = "daily-2026-08-28-fixture"
    run_date = "2026-08-28"
    dashboard_dir = output_root / "dashboard" / run_date
    dashboard_dir.mkdir(parents=True, exist_ok=True)
    html_path = dashboard_dir / "dashboard.html"
    json_path = dashboard_dir / "dashboard.json"
    html_path.write_text("<!doctype html>\n", encoding="utf-8")
    json_path.write_text(json.dumps({"run_id": run_id}) + "\n", encoding="utf-8")

    if container_paths:
        html_value = f"/app/output/dashboard/{run_date}/dashboard.html"
        json_value = f"/app/output/dashboard/{run_date}/dashboard.json"
    else:
        html_value = str(html_path)
        json_value = str(json_path)

    return {
        "run_id": run_id,
        "run_type": "daily",
        "run_date": run_date,
        "status": "succeeded",
        "html_path": html_value,
        "json_path": json_value,
        "failures": [],
        "diagnostics": [],
    }
