"""LLM output guardrails for the briefing renderer.

The prose model is allowed to explain computed values, not create new ones. The numeric
guard is intentionally mechanical: every numeric token in the output must already
appear in the prompt context, either as a numeric value or as part of a source/date
label.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Sequence
import re


_OUTPUT_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?P<prefix>[$€£])?"
    r"(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"(?P<suffix>%|x|d|bp|bps)?"
    r"(?![A-Za-z0-9])"
)
_CONTEXT_NUMBER_RE = re.compile(
    r"(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"(?P<suffix>%|x|d|bp|bps|h)?"
)


@dataclass(frozen=True)
class NumberToken:
    """One numeric token found in prose."""

    token: str
    value: Decimal
    normalized_value: Decimal
    start: int
    end: int


@dataclass(frozen=True)
class NumberViolation:
    """A numeric token that was not authorized by the prompt context."""

    token: str
    value: str
    start: int
    end: int


class NumericGuardError(ValueError):
    """Raised when prose contains an invented number."""

    def __init__(self, violations: Sequence[NumberViolation]) -> None:
        self.violations = tuple(violations)
        detail = ", ".join(f"{v.token} at {v.start}" for v in self.violations)
        super().__init__(f"LLM output contains unauthorized numbers: {detail}")


def assert_authorized_numbers(
    text: str,
    allowed_context: Any,
    *,
    extra_allowed: Iterable[int | float | Decimal | str] = (),
) -> None:
    """Reject output numeric tokens not present in the supplied context."""
    allowed = collect_authorized_numbers(allowed_context)
    for value in extra_allowed:
        allowed.update(_candidate_values(str(value), loose=True))
    violations: list[NumberViolation] = []
    for token in extract_number_tokens(text):
        candidates = _candidate_values(token.token, loose=False)
        if not candidates or candidates.isdisjoint(allowed):
            violations.append(
                NumberViolation(
                    token=token.token,
                    value=str(token.normalized_value),
                    start=token.start,
                    end=token.end,
                )
            )
    if violations:
        raise NumericGuardError(violations)


def collect_authorized_numbers(context: Any) -> set[Decimal]:
    """Collect numeric values and numeric fragments already present in context."""
    allowed: set[Decimal] = set()

    def visit(value: Any) -> None:
        if value is None or isinstance(value, bool):
            return
        if isinstance(value, Decimal):
            allowed.add(_normal_decimal(value))
            return
        if isinstance(value, (int, float)):
            allowed.add(_normal_decimal(Decimal(str(value))))
            return
        if isinstance(value, (datetime, date_type)):
            allowed.update(_candidate_values(value.isoformat(), loose=True))
            return
        if isinstance(value, str):
            allowed.update(_candidate_values(value, loose=True))
            return
        if isinstance(value, Mapping):
            for key, item in value.items():
                visit(key)
                visit(item)
            return
        if isinstance(value, Sequence):
            for item in value:
                visit(item)
            return
        if hasattr(value, "model_dump"):
            visit(value.model_dump(mode="json"))
            return
        if hasattr(value, "to_dict"):
            visit(value.to_dict())

    visit(context)
    return allowed


def extract_number_tokens(text: str) -> list[NumberToken]:
    """Numeric tokens in prose, excluding digits embedded in words like `13F`."""
    tokens: list[NumberToken] = []
    for match in _OUTPUT_NUMBER_RE.finditer(text):
        candidates = _candidate_values(match.group(0), loose=False)
        if not candidates:
            continue
        raw_value = _parse_decimal(match.group("number"))
        if raw_value is None:
            continue
        normalized = min(candidates, key=lambda value: abs(value))
        tokens.append(
            NumberToken(
                token=match.group(0),
                value=raw_value,
                normalized_value=normalized,
                start=match.start(),
                end=match.end(),
            )
        )
    return tokens


def _candidate_values(text: str, *, loose: bool) -> set[Decimal]:
    pattern = _CONTEXT_NUMBER_RE if loose else _OUTPUT_NUMBER_RE
    values: set[Decimal] = set()
    for match in pattern.finditer(text):
        number = _parse_decimal(match.group("number"))
        if number is None:
            continue
        values.add(_normal_decimal(number))
        if loose and number < 0:
            values.add(_normal_decimal(abs(number)))
        suffix = (match.groupdict().get("suffix") or "").lower()
        if suffix == "%":
            values.add(_normal_decimal(number / Decimal("100")))
        elif suffix in {"bp", "bps"}:
            values.add(_normal_decimal(number / Decimal("10000")))
    return values


def _parse_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value.replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _normal_decimal(value: Decimal) -> Decimal:
    if value == 0:
        return Decimal("0")
    return value.normalize()
