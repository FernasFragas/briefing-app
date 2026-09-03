from __future__ import annotations

from datetime import UTC, date, datetime
import argparse
import json
import sys

from briefing_app.config import ConfigError, load_config
from briefing_app.models.gate import to_candidate_gate_rows
from briefing_app.pipeline import (
    STATUS_FAILED,
    STATUS_PARTIAL,
    run_daily as run_daily_pipeline,
    run_weekly as run_weekly_pipeline,
)
from briefing_app.preflight import PreflightRunner
from briefing_app.universe.loader import UniverseLoadError
from briefing_app.universe.pipeline import run_candidate_gate
from briefing_app.universe.store import JsonGateStore


def score_open_calls() -> int:
    print(
        "Open-call scoring is not implemented yet. "
        f"Received trigger at {datetime.now(UTC).isoformat()}."
    )
    return 2


def run_preflight_command(args: argparse.Namespace) -> int:
    report = PreflightRunner().run(cache_only=args.cache_only, deep=args.deep)
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 1 if report.hard_failure_count else 0


def run_gate_command(args: argparse.Namespace) -> int:
    """Universe construction plus the catalyst gate (T2)."""
    try:
        config = load_config(args.config)
        output = run_candidate_gate(
            config,
            run_date=args.run_date,
            mode=args.mode,
            store=JsonGateStore(args.data_dir) if args.data_dir else None,
            persist=not args.no_persist,
            output_dir=args.output_dir,
        )
    except (ConfigError, UniverseLoadError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    report = output.report
    if args.format == "json":
        print(report.model_dump_json(indent=2))
    elif args.format == "rows":
        print(json.dumps(to_candidate_gate_rows(report), indent=2, default=str))
    else:
        print(output.markdown)

    if output.report_path:
        print(f"\nGate report: {output.report_path}", file=sys.stderr)
    if output.markdown_path:
        print(f"Gate markdown: {output.markdown_path}", file=sys.stderr)

    # A load error means a declared candidate never reached the gate at all.
    return 1 if report.load_errors else 0


def run_pipeline_command(args: argparse.Namespace, *, run_type: str) -> int:
    try:
        config = load_config(args.config)
        runner = run_daily_pipeline if run_type == "daily" else run_weekly_pipeline
        output = runner(
            config,
            run_date=args.run_date,
            mode=args.mode,
            data_dir=args.data_dir,
            output_dir=args.output_dir,
            data_mode=args.data_mode or config.pipeline.data_mode,
            persist=not args.no_persist,
            force=args.force or not config.pipeline.skip_non_market_days,
            max_tickers=(
                args.max_tickers
                if args.max_tickers is not None
                else config.pipeline.max_tickers
            ),
        )
    except (ConfigError, UniverseLoadError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(output.to_dict(), indent=2, sort_keys=True))
    if output.html_path:
        print(f"\nDashboard HTML: {output.html_path}", file=sys.stderr)
    if output.json_path:
        print(f"Dashboard JSON: {output.json_path}", file=sys.stderr)
    if output.status_path:
        print(f"Run status: {output.status_path}", file=sys.stderr)

    if output.status == STATUS_FAILED:
        return 2
    if output.status == STATUS_PARTIAL:
        return 1
    return 0


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="briefing-app")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("score-open-calls", help="Resolve open call logs (not implemented).")

    daily = subparsers.add_parser("run-daily", help="Run the full daily pipeline.")
    _add_pipeline_args(daily)
    daily.set_defaults(func=lambda args: run_pipeline_command(args, run_type="daily"))

    weekly = subparsers.add_parser("run-weekly", help="Run the full weekly pipeline.")
    _add_pipeline_args(weekly)
    weekly.set_defaults(func=lambda args: run_pipeline_command(args, run_type="weekly"))

    preflight = subparsers.add_parser(
        "preflight", help="Run provider entitlement probes and raw-cache checks."
    )
    preflight.add_argument(
        "--cache-only",
        action="store_true",
        help="Validate cached probe payloads without network calls.",
    )
    preflight.add_argument(
        "--deep",
        action="store_true",
        help=(
            "Also probe endpoints on metered keys. Spends the provider's daily request "
            "budget, so run it when checking entitlements, not on every scheduled run."
        ),
    )
    preflight.set_defaults(func=run_preflight_command)

    gate = subparsers.add_parser(
        "gate", help="Load the universe and run the pre-scoring catalyst gate."
    )
    gate.add_argument("--config", help="Path to config.yaml (default: BRIEFING_CONFIG_PATH).")
    gate.add_argument(
        "--run-date", type=_parse_date, help="Gate date, YYYY-MM-DD (default: today)."
    )
    gate.add_argument(
        "--mode",
        choices=["fixed", "screen", "both"],
        help="Universe mode override (default: universe.mode from config).",
    )
    gate.add_argument(
        "--format",
        choices=["markdown", "json", "rows"],
        default="markdown",
        help="markdown tables, the full report JSON, or candidate_gate table rows.",
    )
    gate.add_argument("--data-dir", help="Override BRIEFING_DATA_DIR for the gate store.")
    gate.add_argument("--output-dir", help="Override BRIEFING_OUTPUT_DIR for the markdown.")
    gate.add_argument(
        "--no-persist",
        action="store_true",
        help="Do not write the report, markdown, or rejection history.",
    )
    gate.set_defaults(func=run_gate_command)
    return parser


def _add_pipeline_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", help="Path to config.yaml (default: BRIEFING_CONFIG_PATH).")
    parser.add_argument(
        "--run-date", type=_parse_date, help="Run date, YYYY-MM-DD (default: today)."
    )
    parser.add_argument(
        "--mode",
        choices=["fixed", "screen", "both"],
        help="Universe mode override (default: universe.mode from config).",
    )
    parser.add_argument(
        "--data-mode",
        choices=["fixture", "live"],
        help="Data source mode (default: pipeline.data_mode from config).",
    )
    parser.add_argument("--data-dir", help="Override BRIEFING_DATA_DIR.")
    parser.add_argument("--output-dir", help="Override BRIEFING_OUTPUT_DIR.")
    parser.add_argument("--max-tickers", type=int, help="Limit accepted tickers processed.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even when the market-day guard would skip the date.",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Do not write dashboards, raw cache, gate history, or run status.",
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if hasattr(args, "func"):
        return args.func(args)
    if args.command == "score-open-calls":
        return score_open_calls()

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
