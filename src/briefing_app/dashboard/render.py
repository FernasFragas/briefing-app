"""Jinja2 rendering for the self-contained T9 dashboard."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from jinja2 import Environment, select_autoescape

from briefing_app.dashboard.models import DashboardPayload


def render_dashboard_json(payload: DashboardPayload, *, indent: int = 2) -> str:
    """Plain JSON audit artifact."""
    return payload.audit_json(indent=indent)


def render_dashboard_html(payload: DashboardPayload) -> str:
    """Render self-contained HTML with inline CSS and no external assets."""
    env = Environment(autoescape=select_autoescape(("html", "xml")))
    env.filters["display"] = _display
    env.filters["score"] = _score
    env.filters["join_or_unavailable"] = _join_or_unavailable
    env.filters["json_pretty"] = _json_pretty
    return env.from_string(_TEMPLATE).render(payload=payload)


def write_dashboard_artifacts(
    payload: DashboardPayload,
    output_dir: Path,
    *,
    html_filename: str = "dashboard.html",
    json_filename: str = "dashboard.json",
) -> tuple[Path, Path]:
    """Write HTML and JSON dashboard artifacts and return their paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / html_filename
    json_path = output_dir / json_filename
    html_path.write_text(render_dashboard_html(payload), encoding="utf-8")
    json_path.write_text(render_dashboard_json(payload), encoding="utf-8")
    return html_path, json_path


def _display(value: Any) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped.lower() in {"n/a", "na", "null", "none"}:
            return "unavailable"
        return stripped
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _score(value: Any) -> str:
    if value is None:
        return "unavailable"
    try:
        return f"{float(value):+.2f}"
    except (TypeError, ValueError):
        return _display(value)


def _join_or_unavailable(values: Any, separator: str = ", ") -> str:
    if not values:
        return "unavailable"
    if isinstance(values, str):
        return _display(values)
    return separator.join(_display(value) for value in values) or "unavailable"


def _json_pretty(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, indent=2, sort_keys=True)


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Briefing Dashboard {{ payload.run_date.isoformat() }}</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f7f5;
      --panel: #ffffff;
      --text: #202124;
      --muted: #5f6368;
      --line: #d8d9d6;
      --accent: #0f766e;
      --warn: #8a4b0f;
      --bad: #9f1239;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      overflow-x: hidden;
    }
    header {
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      padding: 18px 24px;
    }
    main { max-width: 1280px; width: 100%; margin: 0 auto; padding: 20px 24px 40px; overflow-x: hidden; }
    h1 { font-size: 22px; margin: 0 0 4px; font-weight: 700; }
    h2 { font-size: 16px; margin: 28px 0 10px; }
    h3 { font-size: 14px; margin: 18px 0 8px; }
    .meta, .muted { color: var(--muted); }
    .grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
    .metric {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      min-height: 82px;
    }
    .metric strong { display: block; font-size: 13px; margin-bottom: 6px; }
    table {
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      border: 1px solid var(--line);
    }
    th, td {
      border-bottom: 1px solid var(--line);
      padding: 8px 10px;
      text-align: left;
      vertical-align: top;
      overflow-wrap: anywhere;
    }
    th { font-size: 12px; color: var(--muted); background: #eeeeeb; }
    tr:last-child td { border-bottom: 0; }
    .table-scroll {
      max-width: 100%;
      overflow-x: auto;
      background: var(--panel);
      border: 1px solid var(--line);
    }
    .table-scroll table { min-width: 1120px; border: 0; }
    .ideas-table th, .ideas-table td { white-space: nowrap; }
    .ideas-table td:last-child { white-space: normal; min-width: 220px; }
    .grade-cell { font-weight: 700; }
    .empty {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      color: var(--muted);
    }
    .slot {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
    }
    .slot-name { color: var(--muted); font-size: 12px; text-transform: uppercase; }
    .ticker-section {
      border-top: 1px solid var(--line);
      padding-top: 18px;
      margin-top: 22px;
    }
    .pill {
      display: inline-block;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 1px 8px;
      margin: 1px 2px 1px 0;
      background: #fafafa;
      font-size: 12px;
    }
    .bad { color: var(--bad); }
    .warn { color: var(--warn); }
    .detail-section {
      margin-top: 12px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .detail-section > summary {
      cursor: pointer;
      padding: 12px;
      font-weight: 700;
      color: var(--text);
    }
    .detail-section > section { padding: 0 12px 12px; }
    pre {
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      background: #f1f3f2;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      font-size: 12px;
    }
    @media (max-width: 800px) {
      header { padding: 14px 16px; }
      main { padding: 14px 16px 28px; }
      .grid { grid-template-columns: 1fr; }
      table { display: block; overflow-x: auto; }
      .table-scroll table { display: table; overflow-x: visible; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Briefing Dashboard</h1>
    <div class="meta">Run {{ payload.run_id }} · {{ payload.run_date.isoformat() }} · generated {{ payload.generated_at.isoformat() }} · data {{ payload.data_mode }}</div>
  </header>
  <main>
    <section id="trading-ideas">
      <h2>Trading Ideas</h2>
      {% if payload.trading_ideas %}
      <div class="table-scroll" role="region" aria-label="Trading ideas">
        <table class="ideas-table">
          <thead>
            <tr><th>Ticker</th><th>Setup</th><th>Grade</th><th>Tier</th><th>Thesis</th><th>S_CTE</th><th>Status</th><th>Catalyst</th><th>Blocked Reason</th><th>Penalties</th><th>Headline</th></tr>
          </thead>
          <tbody>
          {% for row in payload.trading_ideas %}
            <tr>
              <td>{{ row.ticker }}</td>
              <td>{{ row.setup_type|display }}</td>
              <td class="grade-cell">{{ row.grade_letter|display }}{% if row.grade_score is not none %} <span class="muted">({{ row.grade_score|display }})</span>{% endif %}</td>
              <td>{{ row.tier|display }}</td>
              <td>{{ row.thesis_band|display }}{% if row.thesis_probability is not none %} <span class="muted">({{ row.thesis_probability|display }})</span>{% endif %}</td>
              <td>{{ row.s_cte|score }}</td>
              <td>{{ row.status }}</td>
              <td>{% if row.catalyst %}{{ row.catalyst.name|display }}{% if row.catalyst.date %} · {{ row.catalyst.date }}{% endif %}{% if row.catalyst.status %} · {{ row.catalyst.status }}{% endif %}{% else %}unavailable{% endif %}</td>
              <td>{{ row.blocked_reason|display }}</td>
              <td>{{ row.grade_penalties|join_or_unavailable }}</td>
              <td>{{ row.headline|display }}</td>
            </tr>
          {% endfor %}
          </tbody>
        </table>
      </div>
      {% else %}<div class="empty">no scored ideas this run</div>{% endif %}
    </section>

    <section id="per-ticker-sections">
      <h2>Analysis / Per-Stock</h2>
      {% if payload.per_ticker_sections %}
      {% for section in payload.per_ticker_sections %}
      <article class="ticker-section">
        <h3>{{ section.ticker }}</h3>
        {% if section.prose %}<p>{{ section.prose }}</p>{% endif %}
        <div class="muted">Gate: {{ section.gate.decision if section.gate else "unavailable" }} · Score: {{ section.score.s_cte|score if section.score else "unavailable" }}</div>
        <h3>Components</h3>
        {% if section.components %}
        <table>
          <thead><tr><th>Component</th><th>Score</th><th>Status</th><th>Quality</th><th>Legs</th><th>Absent Legs</th><th>n/a Reason</th></tr></thead>
          <tbody>
          {% for component in section.components %}
            <tr>
              <td>{{ component.component }}</td>
              <td>{{ component.score|score }}</td>
              <td>{{ component.validation_status|display }}</td>
              <td>{{ component.source_quality|display }}</td>
              <td>{% if component.legs_summary is defined %}{{ component.legs_summary|display }}{% if component.leg_count_note is defined and component.leg_count_note %}<div class="muted">{{ component.leg_count_note }}</div>{% endif %}{% else %}unavailable{% endif %}</td>
              <td>{% if component.absent_legs is defined and component.absent_legs %}{% for leg in component.absent_legs %}<span class="pill">{{ leg.name }}: {{ leg.reason }}</span>{% endfor %}{% else %}unavailable{% endif %}</td>
              <td>{{ component.na_reason|display }}</td>
            </tr>
          {% endfor %}
          </tbody>
        </table>
        {% else %}<div class="empty">unavailable</div>{% endif %}
        <h3>Setups</h3>
        {% if section.setups %}
        <table>
          <thead><tr><th>Setup</th><th>Decision</th><th>Instrument</th><th>Tier</th><th>Horizon</th><th>Invalidation</th></tr></thead>
          <tbody>
          {% for setup in section.setups %}
            <tr>
              <td>{{ setup.setup_type }}</td>
              <td>{{ setup.decision }}</td>
              <td>{{ setup.instrument|display }}</td>
              <td>{{ setup.tier|display }}</td>
              <td>{{ setup.horizon_label|display }}</td>
              <td>{{ setup.invalidation.description if setup.invalidation else "unavailable" }}</td>
            </tr>
          {% endfor %}
          </tbody>
        </table>
        {% else %}<div class="empty">unavailable</div>{% endif %}
      </article>
      {% endfor %}
      {% else %}<div class="empty">unavailable</div>{% endif %}
    </section>

    <section id="market-overview">
      <h2>Market Overview</h2>
      {% if payload.market_overview %}
      <div class="grid">
        {% for point in payload.market_overview %}
        <div class="metric">
          <strong>{{ point.label }}</strong>
          <div>{{ point.value|display }}</div>
          <div class="muted">{{ point.source }}{% if point.as_of %} · {{ point.as_of }}{% endif %}</div>
          {% if point.note %}<div class="muted">{{ point.note }}</div>{% endif %}
        </div>
        {% endfor %}
      </div>
      {% else %}<div class="empty">unavailable</div>{% endif %}
    </section>

    <details class="detail-section">
      <summary>Master Alpha Selection Matrix</summary>
      <section id="master-alpha-selection-matrix">
      {% if payload.master_alpha_selection_matrix %}
      <table>
        <thead>
          <tr><th>Ticker</th><th>Gate</th><th>Class</th><th>Direction</th><th>S_CTE</th><th>Tier</th><th>Posture</th><th>Setup</th><th>Missing</th><th>Flags</th></tr>
        </thead>
        <tbody>
        {% for row in payload.master_alpha_selection_matrix %}
          <tr>
            <td>{{ row.ticker }}</td>
            <td>{{ row.gate_decision|display }}</td>
            <td>{{ row.expression_class|display }}</td>
            <td>{{ row.direction|display }}</td>
            <td>{{ row.s_cte|score }}</td>
            <td>{{ row.tier|display }}</td>
            <td>{{ row.posture|display }}</td>
            <td>{{ row.top_setup|display }}</td>
            <td>{{ row.missing_components|join_or_unavailable }}</td>
            <td>{{ row.flags|join_or_unavailable }}</td>
          </tr>
        {% endfor %}
        </tbody>
      </table>
      {% else %}<div class="empty">unavailable</div>{% endif %}
      </section>
    </details>

    <details class="detail-section">
      <summary>Prior Scorecard</summary>
      <section id="prior-scorecard">
      {% if payload.prior_scorecard %}
      <table>
        <thead><tr><th>Ticker</th><th>Date</th><th>S_CTE</th><th>Tier</th><th>Class</th><th>Components</th></tr></thead>
        <tbody>
        {% for row in payload.prior_scorecard %}
          <tr>
            <td>{{ row.ticker }}</td>
            <td>{{ row.snap_date|display }}</td>
            <td>{{ row.cte_score|score }}</td>
            <td>{{ row.confidence_tier|display }}</td>
            <td>{{ row.expression_class|display }}</td>
            <td>{{ row.component_scores|json_pretty }}</td>
          </tr>
        {% endfor %}
        </tbody>
      </table>
      {% else %}<div class="empty">unavailable</div>{% endif %}
      </section>
    </details>

    <details class="detail-section">
      <summary>Tactical Execution Dashboard</summary>
      <section id="tactical-execution-dashboard">
      <div class="grid">
      {% for name, setup in payload.tactical_execution_dashboard.model_dump().items() %}
        <div class="slot">
          <div class="slot-name">{{ name.replace("_", " ") }}</div>
          {% if setup %}
            <strong>{{ setup.ticker }} · {{ setup.setup_type }}</strong>
            <div>{{ setup.instrument|display }} · Tier {{ setup.tier|display }} · S_CTE {{ setup.s_cte|score }}</div>
            <div class="muted">{{ setup.horizon_label|display }} · invalidation {{ setup.invalidation.description if setup.invalidation else "unavailable" }}</div>
          {% else %}
            <div>unavailable</div>
          {% endif %}
        </div>
      {% endfor %}
      </div>
      </section>
    </details>

    <details class="detail-section">
      <summary>Conditionality Table</summary>
      <section id="conditionality-table">
      {% if payload.conditionality_table %}
      <table>
        <thead><tr><th>Ticker</th><th>Setup</th><th>Decision</th><th>Catalyst</th><th>Invalidation</th><th>Triggers</th><th>Warnings</th><th>Rejected Rules</th></tr></thead>
        <tbody>
        {% for row in payload.conditionality_table %}
          <tr>
            <td>{{ row.ticker }}</td>
            <td>{{ row.setup_type }}</td>
            <td>{{ row.decision }}</td>
            <td>{% if row.catalyst %}{{ row.catalyst.name }} · {{ row.catalyst.date }} · {{ row.catalyst.status }}{% else %}unavailable{% endif %}</td>
            <td>{% if row.invalidation %}{{ row.invalidation.description }}{% else %}unavailable{% endif %}</td>
            <td>{{ row.triggers|join_or_unavailable }}</td>
            <td>{{ row.warnings|join_or_unavailable }}</td>
            <td>{% if row.rejections %}{% for rejection in row.rejections %}<span class="pill">{{ rejection.code }}</span>{% endfor %}{% else %}unavailable{% endif %}</td>
          </tr>
        {% endfor %}
        </tbody>
      </table>
      {% else %}<div class="empty">unavailable</div>{% endif %}
      </section>
    </details>

    <details class="detail-section">
      <summary>Rejected At Gate</summary>
      <section id="rejected-at-gate">
      {% if payload.rejected_at_gate %}
      <table>
        <thead><tr><th>Ticker</th><th>Decision</th><th>Reason Codes</th><th>Detail</th><th>First Flagged</th><th>Runs</th></tr></thead>
        <tbody>
        {% for row in payload.rejected_at_gate %}
          <tr>
            <td>{{ row.ticker }}</td>
            <td>{{ row.decision }}</td>
            <td>{{ row.reason_codes|join_or_unavailable }}</td>
            <td>{{ row.detail|display }}</td>
            <td>{{ row.first_flagged_on|display }}</td>
            <td>{{ row.occurrences }}</td>
          </tr>
        {% endfor %}
        </tbody>
      </table>
      {% else %}<div class="empty">unavailable</div>{% endif %}
      </section>
    </details>

    <details class="detail-section">
      <summary>Evidence Ledger</summary>
      <section id="evidence-ledger">
      {% if payload.evidence_ledger %}
      <table>
        <thead><tr><th>Ticker</th><th>Component</th><th>Field</th><th>Value</th><th>Source</th><th>As Of</th><th>Status</th></tr></thead>
        <tbody>
        {% for row in payload.evidence_ledger %}
          <tr>
            <td>{{ row.ticker }}</td>
            <td>{{ row.component }}</td>
            <td>{{ row.field_name }}</td>
            <td>{{ row.field_value|display }}</td>
            <td>{{ row.source }}</td>
            <td>{{ row.as_of|display }}</td>
            <td>{{ row.validation_status }}</td>
          </tr>
        {% endfor %}
        </tbody>
      </table>
      {% else %}<div class="empty">unavailable</div>{% endif %}
      </section>
    </details>
  </main>
</body>
</html>
"""
