"""Rendering for the gate stage: scored names, rejected-at-gate names, load diagnostics.

Markdown here is the operator-readable artifact for this stage. T9 owns the HTML
dashboard and consumes the same `GateReport` JSON rather than this text.
"""

from __future__ import annotations

from briefing_app.models.gate import CandidateGateResult, GateDecision, GateReport

_NA = "n/a"


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_none_\n"
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(_escape(cell) for cell in row) + " |" for row in rows)
    return "\n".join(lines) + "\n"


def _catalyst_cell(result: CandidateGateResult) -> str:
    catalyst = result.primary_catalyst
    if catalyst is None:
        return _NA
    extra = ""
    if len(result.catalysts_in_horizon) > 1:
        extra = f" +{len(result.catalysts_in_horizon) - 1}"
    return (
        f"{catalyst.name} - {catalyst.event_date.isoformat()} "
        f"({catalyst.status.value}){extra}"
    )


def _flag_cell(result: CandidateGateResult) -> str:
    return ", ".join(flag.code.value for flag in result.flags) or "-"


def render_accepted_table(report: GateReport) -> str:
    """Names that passed the gate and go on to the component data pull."""
    rows = [
        [
            result.ticker,
            result.candidate.venue,
            result.candidate.geography.value,
            result.candidate.expression_class.value,
            result.candidate.direction.value,
            f"{result.horizon_days}d",
            _catalyst_cell(result),
            ", ".join(i.value for i in result.permitted_instruments) or _NA,
            "yes" if result.leverage_allowed else "no",
            _flag_cell(result),
        ]
        for result in report.accepted
    ]
    return _table(
        [
            "Ticker",
            "Venue",
            "Geo",
            "Class",
            "Dir",
            "Horizon",
            "Catalyst (status)",
            "Instruments",
            "Leverage",
            "Flags",
        ],
        rows,
    )


def render_rejected_table(report: GateReport) -> str:
    """The published rejected-at-gate list: demotions and hard rejections."""
    rows = [
        [
            result.ticker,
            result.decision.value,
            ", ".join(code.value for code in result.reason_codes) or _NA,
            result.reason_summary() or _NA,
            result.first_flagged_on.isoformat() if result.first_flagged_on else _NA,
            str(result.occurrences),
        ]
        for result in sorted(
            report.gated_out,
            key=lambda r: (r.decision is not GateDecision.REJECTED, r.ticker),
        )
    ]
    return _table(
        ["Ticker", "Decision", "Reason codes", "Detail", "First flagged", "Runs"], rows
    )


def render_gate_markdown(report: GateReport) -> str:
    """Full gate section: header, scored table, rejected table, load diagnostics."""
    counts = report.counts()
    repeats = sorted(
        (result for result in report.gated_out if result.is_repeat),
        key=lambda result: result.ticker,
    )
    lines = [
        f"# Candidate Gate - {report.run_date.isoformat()}",
        "",
        f"Run id: `{report.run_id}` · Default horizon: {report.default_horizon_days}d · "
        f"Loaded: {counts['total']} · Scored: {counts['accepted']} · "
        f"Watchlist: {counts['watchlist']} · Rejected: {counts['rejected']}",
        "",
        "## Scored candidates",
        "",
        render_accepted_table(report),
        "## Rejected at gate",
        "",
        render_rejected_table(report),
    ]

    if repeats:
        carried = " · ".join(
            f"{result.ticker} ({result.occurrences}x since "
            f"{result.first_flagged_on.isoformat() if result.first_flagged_on else _NA})"
            for result in repeats
        )
        lines += [
            "**Carried from previous runs:** " + carried,
            "",
            "_Published so the same name is not rediscovered and re-pitched each cycle._",
            "",
        ]

    if report.load_warnings:
        lines += ["## Load warnings", ""]
        lines += [f"- {warning}" for warning in report.load_warnings]
        lines += [""]

    if report.load_errors:
        lines += ["## Load errors", ""]
        lines += [f"- {error}" for error in report.load_errors]
        lines += [""]

    return "\n".join(lines)
