"""T11 n8n workflow exports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


WORKFLOW_DIR = Path("workflows")


def test_daily_workflow_has_manual_and_weekday_lisbon_cron() -> None:
    workflow = load_workflow("briefing_daily_delivery.json")

    assert workflow["settings"]["timezone"] == "Europe/Lisbon"
    assert node(workflow, "Manual Trigger")["type"] == "n8n-nodes-base.manualTrigger"

    schedule = node(workflow, "Weekday 06:30 Europe/Lisbon")
    interval = schedule["parameters"]["rule"]["interval"][0]
    assert schedule["type"] == "n8n-nodes-base.scheduleTrigger"
    assert interval == {"field": "cronExpression", "expression": "30 6 * * 1-5"}


def test_daily_workflow_calls_app_with_bearer_token_and_static_delivery() -> None:
    workflow = load_workflow("briefing_daily_delivery.json")
    run_node = node(workflow, "Run Daily Briefing")
    delivery_node = node(workflow, "Publish Static HTML/JSON")

    assert run_node["parameters"]["method"] == "POST"
    assert "http://app:8000/run/daily" in run_node["parameters"]["url"]
    assert run_node["continueOnFail"] is True
    assert auth_header(run_node) == {
        "name": "Authorization",
        "value": "=Bearer {{$env.APP_RUN_TOKEN}}",
    }

    assert delivery_node["parameters"]["method"] == "POST"
    assert "http://app:8000/delivery/static" in delivery_node["parameters"]["url"]
    assert delivery_node["parameters"]["sendBody"] is True
    assert "JSON.stringify($json.body || $json)" in delivery_node["parameters"]["jsonBody"]
    assert auth_header(delivery_node)["value"] == "=Bearer {{$env.APP_RUN_TOKEN}}"


def test_workflows_have_market_day_guard_and_structured_error_branch() -> None:
    for path in ("briefing_daily_delivery.json", "briefing_weekly_delivery.json"):
        workflow = load_workflow(path)
        guard_code = node(workflow, "Market Day Guard")["parameters"]["jsCode"]
        error_code = node(workflow, "Format Error Branch")["parameters"]["jsCode"]

        assert "Europe/Lisbon" in guard_code
        assert "MARKET_HOLIDAYS" in guard_code
        assert "is_market_day" in guard_code
        assert "Sat" in guard_code and "Sun" in guard_code
        for key in ("run_id", "stage", "ticker", "reason"):
            assert key in error_code
        assert_all_connections_resolve(workflow)


def test_optional_weekly_workflow_calls_weekly_endpoint() -> None:
    workflow = load_workflow("briefing_weekly_delivery.json")
    schedule = node(workflow, "Weekly 06:30 Europe/Lisbon")
    run_node = node(workflow, "Run Weekly Briefing")

    assert schedule["parameters"]["rule"]["interval"][0] == {
        "field": "cronExpression",
        "expression": "30 6 * * 1",
    }
    assert "http://app:8000/run/weekly" in run_node["parameters"]["url"]
    assert auth_header(run_node)["value"] == "=Bearer {{$env.APP_RUN_TOKEN}}"


def load_workflow(name: str) -> dict[str, Any]:
    return json.loads((WORKFLOW_DIR / name).read_text(encoding="utf-8"))


def node(workflow: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in workflow["nodes"] if item["name"] == name)


def auth_header(node_data: dict[str, Any]) -> dict[str, str]:
    headers = node_data["parameters"]["headerParameters"]["parameters"]
    return next(header for header in headers if header["name"] == "Authorization")


def assert_all_connections_resolve(workflow: dict[str, Any]) -> None:
    names = {item["name"] for item in workflow["nodes"]}
    for source, connection in workflow["connections"].items():
        assert source in names
        for output in connection["main"]:
            for edge in output:
                assert edge["node"] in names
