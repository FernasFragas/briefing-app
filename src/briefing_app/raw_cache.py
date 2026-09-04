from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import re
from typing import Any


_SAFE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9_.=-]+")


class RawCache:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def path(
        self,
        provider: str,
        endpoint: str,
        run_date: date,
        symbol_or_market: str,
        suffix: str = ".json",
    ) -> Path:
        safe_provider = sanitize_path_segment(provider)
        safe_endpoint = sanitize_path_segment(endpoint)
        safe_symbol = sanitize_path_segment(symbol_or_market)
        return (
            self.data_dir
            / "raw"
            / safe_provider
            / safe_endpoint
            / run_date.isoformat()
            / f"{safe_symbol}{suffix}"
        )

    def write_json(
        self,
        provider: str,
        endpoint: str,
        run_date: date,
        symbol_or_market: str,
        payload: Any,
    ) -> Path:
        target = self.path(provider, endpoint, run_date, symbol_or_market)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, default=str)
            handle.write("\n")
        return target

    def read_json(
        self, provider: str, endpoint: str, run_date: date, symbol_or_market: str
    ) -> Any:
        target = self.path(provider, endpoint, run_date, symbol_or_market)
        with target.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def write_bytes(
        self,
        provider: str,
        endpoint: str,
        run_date: date,
        symbol_or_market: str,
        body: bytes,
        suffix: str,
    ) -> Path:
        """Cache a spreadsheet or document download verbatim.

        Binary sources must never round-trip through JSON: a lossy decode would turn a
        blocked or truncated download into something that still parses.
        """

        target = self.path(provider, endpoint, run_date, symbol_or_market, suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        return target

    def read_bytes(
        self,
        provider: str,
        endpoint: str,
        run_date: date,
        symbol_or_market: str,
        suffix: str,
    ) -> bytes:
        return self.path(provider, endpoint, run_date, symbol_or_market, suffix).read_bytes()

    def exists(
        self,
        provider: str,
        endpoint: str,
        run_date: date,
        symbol_or_market: str,
        suffix: str = ".json",
    ) -> bool:
        return self.path(provider, endpoint, run_date, symbol_or_market, suffix).exists()


def sanitize_path_segment(value: str) -> str:
    cleaned = _SAFE_SEGMENT_RE.sub("_", value.strip())
    cleaned = cleaned.strip("._")
    return cleaned or "unknown"
