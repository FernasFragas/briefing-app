from __future__ import annotations

from dataclasses import dataclass
from typing import Any


#: Keys a provider uses to explain a failure inside an HTTP 200 body. Alpha Vantage
#: uses `message`/`Information`/`Note`; FMP answers a plan-gated endpoint with
#: `Error Message: ACCESS DENIED`. A payload carrying one of these is a failed call.
TRAP_KEYS = {"message", "information", "note", "error", "error message", "errors"}
SENTINEL_STRINGS = {"XXYYZZ", "2099-99-99", "9999-99-99"}

#: Multi-word phrases providers use to refuse a call the plan does not cover. FMP answers
#: a restricted endpoint with plain text, and its retired v3/v4 API with `Legacy Endpoint`.
#: Phrases, not bare words, so a news or filing body cannot trip them.
PLAN_GATE_PHRASES = (
    "restricted endpoint",
    "current subscription",
    "upgrade your plan",
    "legacy endpoint",
)

#: Phrases naming a refusal that clears on its own. These must be tested BEFORE any plan
#: gate, because a provider can describe a spent quota in plan-gate language: FMP answers
#: an exhausted daily budget with `Limit Reach . Please upgrade your plan`, which would
#: otherwise classify as a permanent endpoint gate and retire a working source.
QUOTA_NOTICES = (
    "rate limit",
    "requests per day",
    "daily rate limit",
    "limit reach",
    "frequency",
    "quota",
    "api credits",
)


def is_quota_notice(body: str) -> bool:
    """True when a refusal is about spend or rate rather than entitlement."""

    return any(term in body.lower() for term in QUOTA_NOTICES)


#: What a plan refusal actually covers. FMP answers all three with HTTP 402 and a plain
#: text body, but they mean very different things: `endpoint` means use the fallback,
#: `symbol` means the endpoint works and this ticker does not, and `parameter` means the
#: call itself is wrong. Collapsing them into "paywalled" loses the only actionable part.
GATE_ENDPOINT = "endpoint"
GATE_SYMBOL = "symbol"
GATE_PARAMETER = "parameter"


def classify_plan_gate(body: str) -> str | None:
    """Name what a plan-gated refusal covers, or None when it is not a plan gate."""

    lowered = body.strip().lower()
    if not lowered:
        return None
    if is_quota_notice(lowered):
        # A spent budget is not an entitlement ceiling, however the provider words it.
        return None
    if "restricted endpoint" in lowered or "legacy endpoint" in lowered:
        return GATE_ENDPOINT
    if "premium query parameter" in lowered or "special parameters" in lowered:
        if "'symbol'" in lowered or "for 'symbol" in lowered:
            return GATE_SYMBOL
        return GATE_PARAMETER
    if "premium endpoint" in lowered:
        return GATE_ENDPOINT
    if any(term in lowered for term in PLAN_GATE_PHRASES):
        return GATE_ENDPOINT
    return None

OK = "ok"
MISSING = "missing"
THROTTLED = "throttled"
PAYWALLED = "paywalled"
MALFORMED = "malformed"
SYNTHETIC = "synthetic"
PLACEHOLDER = "placeholder"
TRUNCATED = "truncated"


@dataclass(frozen=True)
class ValidationResult:
    status: str
    ok: bool
    notes: tuple[str, ...] = ()
    as_of: str | None = None


def validate_payload(
    payload: Any,
    required_json_paths: tuple[str, ...] = (),
    provider_id: str | None = None,
) -> ValidationResult:
    if isinstance(payload, str):
        return validate_text_payload(payload)

    if not isinstance(payload, (dict, list)):
        return ValidationResult(MALFORMED, False, ("Payload is not JSON-like.",))

    trap_result = _trap_key_result(payload, provider_id)
    if trap_result is not None:
        return trap_result

    if _contains_sentinel(payload):
        return ValidationResult(
            SYNTHETIC,
            False,
            ("Payload contains sentinel symbols or impossible dates.",),
        )

    uniform_note = _uniform_options_note(payload)
    if uniform_note:
        return ValidationResult(SYNTHETIC, False, (uniform_note,))

    for path in required_json_paths:
        if path == "root":
            if _is_empty(payload):
                return ValidationResult(MISSING, False, ("Root payload is empty.",))
            continue

        value = get_path(payload, path)
        if _is_empty(value):
            return ValidationResult(
                MISSING, False, (f"Required JSON path is missing or empty: {path}",)
            )

    return ValidationResult(OK, True, as_of=_extract_as_of(payload))


def validate_text_payload(payload: str) -> ValidationResult:
    stripped = payload.strip()
    if not stripped:
        return ValidationResult(MISSING, False, ("Response body is empty.",))

    lowered = stripped.lower()
    if "loading" in lowered or "please enable javascript" in lowered:
        return ValidationResult(
            PLACEHOLDER,
            False,
            ("Response appears to be a JavaScript placeholder, not data.",),
        )
    if is_quota_notice(lowered):
        return ValidationResult(THROTTLED, False, ("Response indicates throttling.",))
    if "access denied" in lowered or "forbidden" in lowered:
        return ValidationResult(PAYWALLED, False, ("Response indicates denied access.",))
    if any(term in lowered for term in ("premium", "not entitled", "permission")):
        return ValidationResult(PAYWALLED, False, ("Response indicates plan-gated access.",))
    if any(term in lowered for term in PLAN_GATE_PHRASES):
        return ValidationResult(
            PAYWALLED, False, ("Response indicates a plan-gated or retired endpoint.",)
        )
    return ValidationResult(MALFORMED, False, ("Response is not JSON.",))


def validate_text_data_payload(payload: str) -> ValidationResult:
    """Validate data endpoints that legitimately answer with CSV, pipe text, or HTML."""

    text_validation = validate_text_payload(payload)
    if text_validation.status in {MISSING, PAYWALLED, PLACEHOLDER, THROTTLED}:
        return text_validation
    degenerate = _degenerate_row_note(payload)
    if degenerate:
        return ValidationResult(MALFORMED, False, (degenerate,))
    return ValidationResult(OK, True)


def _degenerate_row_note(text: str) -> str | None:
    """Catch a refusal that a CSV endpoint smuggled into the shape of data.

    Alpha Vantage answers a throttled CSV endpoint with HTTP 200, the real header, and
    one row carrying the refusal text spread a character per column and truncated to the
    header's width, so `Information` arrives as `I,n,f,o,r,m,a`. It parses as valid CSV
    and every keyword check misses it, which is the worst possible outcome here: a
    refusal that reads as "no events scheduled" rather than as a failed call.

    Real rows in these feeds carry dates, tickers and volumes, so a body whose every data
    row is entirely single characters is a refusal, not a thin day.
    """

    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return None

    delimiter = "|" if "|" in lines[0] else ","
    if delimiter not in lines[0]:
        return None

    data_rows = lines[1:]
    degenerate_rows = [
        row
        for row in data_rows
        if all(len(field.strip()) <= 1 for field in row.split(delimiter))
    ]
    if len(degenerate_rows) != len(data_rows):
        return None
    return (
        "Delimited body has no row wider than one character per column; this is a "
        f"provider refusal wearing the shape of data, not a thin result: {lines[1][:80]}"
    )


#: Leading bytes for the container formats a binary source may legitimately answer with.
BINARY_MAGIC = {
    b"PK\x03\x04": "zip/xlsx",
    b"\xd0\xcf\x11\xe0": "ole2/xls",
    b"%PDF": "pdf",
}


def validate_binary_payload(
    body: bytes,
    *,
    minimum_bytes: int = 1024,
    expected_formats: tuple[str, ...] = (),
) -> ValidationResult:
    """Validate a spreadsheet or document download.

    A blocked or interstitial response still arrives as HTTP 200, so a body that decodes
    as text is treated as the site answering with a page instead of the file.
    """

    if not body:
        return ValidationResult(MISSING, False, ("Response body is empty.",))

    magic = next(
        (label for prefix, label in BINARY_MAGIC.items() if body.startswith(prefix)),
        None,
    )
    if magic is None:
        head = body[:2048].decode("utf-8", errors="replace")
        text_validation = validate_text_payload(head)
        if text_validation.status in {PAYWALLED, PLACEHOLDER, THROTTLED}:
            return text_validation
        return ValidationResult(
            MALFORMED,
            False,
            ("Response is not a recognised binary document; a page was returned.",),
        )

    if expected_formats and magic not in expected_formats:
        return ValidationResult(
            MALFORMED,
            False,
            (f"Binary format {magic} is not one of {', '.join(expected_formats)}.",),
        )

    if len(body) < minimum_bytes:
        return ValidationResult(
            TRUNCATED,
            False,
            (f"Binary body is only {len(body)} bytes; expected at least {minimum_bytes}.",),
        )

    return ValidationResult(OK, True, (f"Binary {magic} download, {len(body)} bytes.",))


def get_path(payload: Any, dotted_path: str) -> Any:
    current = payload
    for segment in dotted_path.split("."):
        if isinstance(current, dict):
            if segment not in current:
                return None
            current = current[segment]
        elif isinstance(current, list):
            try:
                current = current[int(segment)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current


def _trap_key_result(payload: Any, provider_id: str | None) -> ValidationResult | None:
    if isinstance(payload, dict):
        for key, raw_value in payload.items():
            if key.lower() in TRAP_KEYS:
                if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
                    # An empty `error`/`note` field is the provider saying nothing is
                    # wrong. Only a populated one is a failure notice.
                    continue
                value = str(raw_value)
                lowered = value.lower()
                if is_quota_notice(lowered):
                    return ValidationResult(THROTTLED, False, (f"{key}: {value}",))
                if any(
                    term in lowered
                    for term in ("premium", "entitled", "access", "permission")
                ) or any(term in lowered for term in PLAN_GATE_PHRASES):
                    status = SYNTHETIC if provider_id == "alpha_vantage" else PAYWALLED
                    return ValidationResult(status, False, (f"{key}: {value}",))
                status = SYNTHETIC if provider_id == "alpha_vantage" else MALFORMED
                return ValidationResult(status, False, (f"{key}: {value}",))

        for value in payload.values():
            result = _trap_key_result(value, provider_id)
            if result is not None:
                return result

    if isinstance(payload, list):
        for item in payload:
            result = _trap_key_result(item, provider_id)
            if result is not None:
                return result
    return None


def _contains_sentinel(payload: Any) -> bool:
    if isinstance(payload, str):
        return any(sentinel in payload for sentinel in SENTINEL_STRINGS)
    if isinstance(payload, dict):
        return any(_contains_sentinel(value) for value in payload.values())
    if isinstance(payload, list):
        return any(_contains_sentinel(value) for value in payload)
    return False


def _uniform_options_note(payload: Any) -> str | None:
    options = _extract_options(payload)
    if len(options) < 10:
        return None

    for key in ("open_interest", "volume"):
        values = [str(option.get(key)) for option in options if key in option]
        if len(values) >= 10 and len(set(values)) == 1:
            return f"Suspiciously uniform option {key} across {len(values)} legs."
    return None


def _extract_options(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("options"), list):
            return [item for item in data["options"] if isinstance(item, dict)]
        if isinstance(payload.get("options"), list):
            return [item for item in payload["options"] if isinstance(item, dict)]
        if isinstance(payload.get("data"), list):
            return [item for item in payload["data"] if isinstance(item, dict)]
    return []


def _extract_as_of(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None

    for key in ("timestamp", "as_of", "asOf"):
        value = payload.get(key)
        if value:
            return str(value)

    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("timestamp", "as_of", "asOf", "last_trade_time"):
            value = data.get(key)
            if value:
                return str(value)
    return None


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}
