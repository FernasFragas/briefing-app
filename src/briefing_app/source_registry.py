from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from briefing_app.config import load_yaml


@dataclass(frozen=True)
class EndpointDefinition:
    source_id: str
    source_name: str
    id: str
    component: str
    geography: tuple[str, ...]
    priority: str
    source_type: str
    entitlement: str
    staleness_bound: str
    method: str | None = None
    url_template: str | None = None
    credential_env: str | None = None
    cache_provider: str | None = None
    cache_endpoint: str | None = None
    probe_enabled: bool = False
    required_json_paths: tuple[str, ...] = field(default_factory=tuple)
    manual_schema: str | None = None
    note: str = ""
    #: How the probe body is read: a JSON document, a CSV/pipe text feed, or a
    #: spreadsheet download that must never be decoded as UTF-8.
    response_format: str = "json"
    #: False for endpoints the current plan is not expected to cover. They are still
    #: probed and still report their true status; they just do not fail preflight.
    required: bool = True
    #: Seconds to wait before this probe. Alpha Vantage throttles above ~1 req/s and
    #: answers HTTP 200 with a rate-limit notice, which reads as a data failure.
    probe_delay_seconds: float = 0.0
    #: For date-stamped files: how many earlier days to walk back when the file for the
    #: requested date is not published yet (weekends, holidays, T+1 release).
    probe_date_lookback_days: int = 0
    #: Days of history a `{from_date}`/`{to_date}` window covers.
    probe_window_days: int = 90
    #: Overrides the universe symbol when an endpoint needs a specific reference name
    #: (an operating company for filings, say, rather than an ETF trust).
    probe_symbol: str | None = None
    #: Names the raw-cache slot when it is not the symbol, so a preflight probe warms the
    #: same slot the provider client later reads (`CNMS_{trade_date}`, `{cik_padded}`).
    cache_target_template: str | None = None
    #: Filing forms `{accession}`/`{document}` resolve against, newest first.
    probe_filing_forms: tuple[str, ...] = field(default_factory=tuple)
    #: `always` runs on every preflight. `deep` runs only under `preflight --deep`,
    #: for endpoints whose key is metered tightly enough that probing every run would
    #: spend the same quota the pipeline needs.
    probe_tier: str = "always"


@dataclass(frozen=True)
class SourceDefinition:
    id: str
    display_name: str
    priority: str
    geography: tuple[str, ...]
    source_type: str
    components: tuple[str, ...]
    entitlement: str
    staleness_bound: str
    credential_env: str | None
    endpoints: tuple[EndpointDefinition, ...]


@dataclass(frozen=True)
class SourceRegistry:
    version: int
    sources: tuple[SourceDefinition, ...]

    @classmethod
    def from_file(cls, path: Path) -> "SourceRegistry":
        raw = load_yaml(path)
        version = int(raw.get("version", 1))
        sources: list[SourceDefinition] = []

        for raw_source in raw.get("sources", []):
            source = _parse_source(raw_source)
            sources.append(source)

        return cls(version=version, sources=tuple(sources))

    def endpoints(self) -> Iterable[EndpointDefinition]:
        for source in self.sources:
            yield from source.endpoints


def _parse_source(raw_source: dict[str, Any]) -> SourceDefinition:
    source_id = str(raw_source["id"])
    source_name = str(raw_source.get("display_name", source_id))
    priority = str(raw_source.get("priority", "unknown"))
    geography = tuple(str(value).upper() for value in raw_source.get("geography", []))
    source_type = str(raw_source.get("source_type", "registered_dataset"))
    components = tuple(str(value) for value in raw_source.get("components", []))
    entitlement = str(raw_source.get("entitlement", "unknown"))
    staleness_bound = str(raw_source.get("staleness_bound", "unknown"))
    credential_env = raw_source.get("credential_env")

    endpoints = []
    for raw_endpoint in raw_source.get("endpoints", []):
        endpoints.append(
            EndpointDefinition(
                source_id=source_id,
                source_name=source_name,
                id=str(raw_endpoint["id"]),
                component=str(raw_endpoint.get("component", "")),
                geography=geography,
                priority=priority,
                source_type=str(raw_endpoint.get("source_type", source_type)),
                entitlement=str(raw_endpoint.get("entitlement", entitlement)),
                staleness_bound=str(
                    raw_endpoint.get("staleness_bound", staleness_bound)
                ),
                method=raw_endpoint.get("method"),
                url_template=raw_endpoint.get("url_template"),
                credential_env=raw_endpoint.get("credential_env", credential_env),
                cache_provider=raw_endpoint.get("cache_provider", source_id),
                cache_endpoint=raw_endpoint.get("cache_endpoint", raw_endpoint["id"]),
                probe_enabled=bool(raw_endpoint.get("probe_enabled", False)),
                required_json_paths=tuple(
                    str(path) for path in raw_endpoint.get("required_json_paths", [])
                ),
                manual_schema=raw_endpoint.get("manual_schema"),
                note=str(raw_endpoint.get("note", "")),
                response_format=str(raw_endpoint.get("response_format", "json")),
                required=bool(raw_endpoint.get("required", raw_source.get("required", True))),
                probe_delay_seconds=float(
                    raw_endpoint.get(
                        "probe_delay_seconds", raw_source.get("probe_delay_seconds", 0.0)
                    )
                ),
                probe_date_lookback_days=int(
                    raw_endpoint.get("probe_date_lookback_days", 0)
                ),
                probe_window_days=int(raw_endpoint.get("probe_window_days", 90)),
                probe_symbol=raw_endpoint.get("probe_symbol"),
                cache_target_template=raw_endpoint.get("cache_target_template"),
                probe_filing_forms=tuple(
                    str(form) for form in raw_endpoint.get("probe_filing_forms", [])
                ),
                probe_tier=str(
                    raw_endpoint.get("probe_tier", raw_source.get("probe_tier", "always"))
                ),
            )
        )

    return SourceDefinition(
        id=source_id,
        display_name=source_name,
        priority=priority,
        geography=geography,
        source_type=source_type,
        components=components,
        entitlement=entitlement,
        staleness_bound=staleness_bound,
        credential_env=credential_env,
        endpoints=tuple(endpoints),
    )
