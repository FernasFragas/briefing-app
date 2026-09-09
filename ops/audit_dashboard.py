from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


NEUTRAL_BAND = 0.15
DIRECTIONAL_FULL_CONVICTION = 0.35
LETTER_BANDS: tuple[tuple[float, str], ...] = (
    (90.0, "A+"),
    (82.0, "A"),
    (74.0, "B+"),
    (66.0, "B"),
    (58.0, "C+"),
    (50.0, "C"),
    (35.0, "D"),
    (0.0, "F"),
)
TIER_LETTER_CAPS = {"A": "A+", "B": "B+", "C": "C"}
LETTER_RANK = {letter: rank for rank, (_, letter) in enumerate(LETTER_BANDS)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Recompute dashboard trading idea grades from dashboard.json."
    )
    parser.add_argument(
        "dashboard_json",
        nargs="?",
        default="output/published/latest/dashboard.json",
        help="Path to dashboard.json (default: output/published/latest/dashboard.json).",
    )
    args = parser.parse_args(argv)

    payload = json.loads(Path(args.dashboard_json).read_text(encoding="utf-8"))
    failures = audit_payload(payload)
    if failures:
        print(json.dumps({"ok": False, "failures": failures}, indent=2, sort_keys=True))
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "rows_checked": len(
                    [row for row in payload.get("trading_ideas", []) if row.get("grade_score") is not None]
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def audit_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for row in payload.get("trading_ideas", []):
        if row.get("grade_score") is None:
            continue
        expected_score = recompute_score(row)
        expected_letter = recompute_letter(expected_score, row.get("tier"))
        actual_score = round(float(row["grade_score"]), 2)
        actual_letter = row.get("grade_letter")
        if actual_score != expected_score or actual_letter != expected_letter:
            failures.append(
                {
                    "ticker": row.get("ticker"),
                    "actual_score": actual_score,
                    "expected_score": expected_score,
                    "actual_letter": actual_letter,
                    "expected_letter": expected_letter,
                }
            )
    return failures


def recompute_score(row: dict[str, Any]) -> float:
    s_cte = row.get("s_cte")
    direction = row.get("direction")
    if s_cte is None or direction is None:
        raise ValueError(f"{row.get('ticker')}: graded row is missing s_cte or direction")
    support = alignment(float(s_cte), str(direction))
    penalty_total = float(row.get("grade_penalty_total") or 0.0)
    return round(max((100.0 * support) - penalty_total, 0.0), 2)


def alignment(s_cte: float, direction: str) -> float:
    normalized = direction.strip().lower()
    if normalized == "long":
        return min(1.0, abs(s_cte) / DIRECTIONAL_FULL_CONVICTION) if s_cte > 0 else 0.0
    if normalized == "short":
        return min(1.0, abs(s_cte) / DIRECTIONAL_FULL_CONVICTION) if s_cte < 0 else 0.0
    return min(max(1.0 - (abs(s_cte) / NEUTRAL_BAND), 0.0), 1.0)


def recompute_letter(score: float, tier: str | None) -> str:
    base_letter = "F"
    for boundary, letter in LETTER_BANDS:
        if score >= boundary:
            base_letter = letter
            break
    if tier is None:
        return base_letter
    cap = TIER_LETTER_CAPS[str(tier)]
    if LETTER_RANK[base_letter] < LETTER_RANK[cap]:
        return cap
    return base_letter


if __name__ == "__main__":
    raise SystemExit(main())
