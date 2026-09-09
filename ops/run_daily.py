from __future__ import annotations

import argparse
from datetime import date
import json
import os
import sys
from typing import Any

from _common import configure_environment, last_run_path, utc_now_iso, write_json


DATA_MODES = {"fixture", "live"}


def main(argv: list[str] | None = None) -> int:
    configure_environment()

    from briefing_app.api import resolve_run_token, run_token_path
    from briefing_app.config import load_config
    from briefing_app.delivery import PUBLISHABLE_STATUSES, publish_static_artifacts
    from briefing_app.pipeline import run_daily

    parser = argparse.ArgumentParser(
        description="Run the local daily briefing and publish latest static artifacts."
    )
    parser.add_argument("--run-date", help="Run date in YYYY-MM-DD format. Defaults to today.")
    parser.add_argument("--force", action="store_true", help="Run even when the market-day guard would skip.")
    parser.add_argument("--max-tickers", type=int, help="Limit tickers for smoke tests.")
    parser.add_argument(
        "--data-mode",
        choices=sorted(DATA_MODES),
        help="Override pipeline.data_mode for this local job.",
    )
    parser.add_argument(
        "--simulate-failure",
        action="store_true",
        help="Write a failed ops status and exit non-zero without running the pipeline.",
    )
    args = parser.parse_args(argv)

    record: dict[str, Any] = {
        "schema_version": 1,
        "job": "daily-local",
        "started_at": utc_now_iso(),
        "finished_at": None,
        "ok": False,
        "token_file": str(run_token_path()),
        "run": None,
        "delivery": None,
        "error": None,
    }
    exit_code = 1

    try:
        resolve_run_token()
        if args.simulate_failure:
            raise RuntimeError("simulated local daily failure")

        config = load_config()
        data_mode = _resolve_data_mode(args.data_mode, config.pipeline.data_mode)
        effective_date = date.fromisoformat(args.run_date) if args.run_date else None
        max_tickers = (
            args.max_tickers
            if args.max_tickers is not None
            else config.pipeline.max_tickers
        )
        output = run_daily(
            config,
            run_date=effective_date,
            force=args.force or not config.pipeline.skip_non_market_days,
            max_tickers=max_tickers,
            data_mode=data_mode,
        )
        run_payload = output.to_dict()
        record["run"] = run_payload

        if output.status in PUBLISHABLE_STATUSES:
            record["delivery"] = publish_static_artifacts(
                run_payload,
                output_root=os.getenv("BRIEFING_OUTPUT_DIR") or "output",
            ).to_dict()
        else:
            record["error"] = f"run status {output.status!r} is not publishable"

        record["ok"] = (
            output.status == "succeeded"
            and record["delivery"] is not None
            and not run_payload.get("diagnostics")
            and not run_payload.get("failures")
        )
        exit_code = 0 if record["ok"] else 2
    except Exception as exc:  # noqa: BLE001 - the status file is the visible failure surface.
        record["error"] = {"type": type(exc).__name__, "message": str(exc)}
        exit_code = 1
    finally:
        record["finished_at"] = utc_now_iso()
        write_json(last_run_path(), record)
        print(json.dumps(_summary(record), sort_keys=True), flush=True)

    return exit_code


def _resolve_data_mode(explicit: str | None, configured: str) -> str:
    data_mode = explicit or os.getenv("BRIEFING_DATA_MODE") or configured
    if data_mode not in DATA_MODES:
        raise ValueError(
            "BRIEFING_DATA_MODE must be one of: " + ", ".join(sorted(DATA_MODES))
        )
    return data_mode


def _summary(record: dict[str, Any]) -> dict[str, Any]:
    run = record.get("run") or {}
    delivery = record.get("delivery") or {}
    return {
        "job": record.get("job"),
        "ok": record.get("ok"),
        "run_id": run.get("run_id"),
        "run_date": run.get("run_date"),
        "status": run.get("status"),
        "published_latest": delivery.get("latest_html_path"),
        "error": record.get("error"),
        "status_file": str(last_run_path()),
    }


if __name__ == "__main__":
    raise SystemExit(main())
