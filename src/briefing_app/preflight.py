from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit

from briefing_app.config import first_symbol_for_geography, load_app_config
from briefing_app.http import Fetcher, HttpFetchResult, UrlLibFetcher
from briefing_app.provider_validation import (
    GATE_ENDPOINT,
    GATE_PARAMETER,
    GATE_SYMBOL,
    MALFORMED,
    MISSING,
    OK,
    PAYWALLED,
    THROTTLED,
    ValidationResult,
    classify_plan_gate,
    is_quota_notice,
    validate_binary_payload,
    validate_payload,
    validate_text_data_payload,
    validate_text_payload,
)
from briefing_app.providers.budget import (
    BUDGET_EXHAUSTED,
    BudgetExhausted,
    RequestBudget,
)
from briefing_app.raw_cache import RawCache
from briefing_app.settings import AppSettings
from briefing_app.source_registry import EndpointDefinition, SourceRegistry


NO_CREDENTIALS = "no_credentials"
REGISTERED = "registered"
MANUAL_REQUIRED = "manual_required"
BROWSER_REQUIRED = "browser_required"
NETWORK_ERROR = "network_error"
SKIPPED = "skipped"

#: Placeholder contacts shipped in `.env.example`. SEC EDGAR requires a real one and
#: throttles or blocks a generic agent, so a probe that passes today can fail silently.
PLACEHOLDER_USER_AGENT_MARKERS = ("example.com", "example.org", "your-email", "you@")

#: Directory under the data dir where hand-captured EU files are dropped, one folder per
#: registry `cache_provider`/`cache_endpoint` pair.
MANUAL_CAPTURE_DIR = "manual"


@dataclass(frozen=True)
class PreflightResult:
    source_id: str
    source_name: str
    endpoint_id: str
    component: str
    geography: tuple[str, ...]
    priority: str
    status: str
    entitlement: str
    staleness_bound: str
    probe_symbol: str | None
    url: str | None
    cache_path: str | None
    as_of: str | None
    notes: tuple[str, ...]
    #: False for endpoints the current plan is not expected to cover. They still report
    #: their true status; they just do not fail the run.
    required: bool = True


@dataclass(frozen=True)
class PreflightReport:
    generated_at: str
    run_date: str
    cache_only: bool
    registry_version: int
    results: tuple[PreflightResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def hard_failure_count(self) -> int:
        """Failures on endpoints the pipeline is entitled to depend on.

        A plan-gated endpoint reports `paywalled` honestly but is marked `required: false`
        in the registry, so a known entitlement ceiling does not mask a real regression.
        """

        soft_statuses = {
            OK,
            NO_CREDENTIALS,
            REGISTERED,
            MANUAL_REQUIRED,
            BROWSER_REQUIRED,
            SKIPPED,
        }
        return sum(
            1
            for result in self.results
            if result.required and result.status not in soft_statuses
        )

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for result in self.results:
            counts[result.status] = counts.get(result.status, 0) + 1
        return dict(sorted(counts.items()))


class PreflightRunner:
    def __init__(
        self,
        settings: AppSettings | None = None,
        fetcher: Fetcher | None = None,
        budget: RequestBudget | None = None,
    ):
        self.settings = settings or AppSettings.from_env()
        self.config = load_app_config(self.settings)
        self.registry = SourceRegistry.from_file(self.settings.source_registry_path)
        self.cache = RawCache(self.settings.data_dir)
        self.fetcher = fetcher or UrlLibFetcher()
        self.budget = budget or RequestBudget(self.settings.data_dir)
        self._cik_by_ticker: dict[str, str] | None = None

    def run(
        self,
        *,
        cache_only: bool = False,
        run_date: date | None = None,
        write_report: bool = True,
        deep: bool = False,
    ) -> PreflightReport:
        """Probe the registry.

        `deep` additionally probes endpoints whose key is metered tightly enough that
        probing them every run would spend the quota the pipeline needs. A routine
        preflight leaves that quota alone and reports them as registered.
        """

        resolved_date = run_date or date.today()
        self._cik_by_ticker = None
        results = tuple(
            self._probe_endpoint(endpoint, cache_only, resolved_date, deep=deep)
            for endpoint in self.registry.endpoints()
        )
        report = PreflightReport(
            generated_at=datetime.now(UTC).isoformat(),
            run_date=resolved_date.isoformat(),
            cache_only=cache_only,
            registry_version=self.registry.version,
            results=results,
        )
        if write_report:
            self.write_report(report)
        return report

    def write_report(self, report: PreflightReport) -> tuple[Path, Path]:
        report_dir = self.settings.output_dir / "preflight"
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = report.generated_at.replace(":", "").replace("+", "Z")
        dated_path = report_dir / f"preflight-{stamp}.json"
        latest_path = report_dir / "latest.json"
        payload = report.to_dict()
        for path in (dated_path, latest_path):
            with path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
        return dated_path, latest_path

    def _probe_endpoint(
        self,
        endpoint: EndpointDefinition,
        cache_only: bool,
        run_date: date,
        *,
        deep: bool = False,
    ) -> PreflightResult:
        symbol = self._symbol_for_endpoint(endpoint)
        base_kwargs = {
            "source_id": endpoint.source_id,
            "source_name": endpoint.source_name,
            "endpoint_id": endpoint.id,
            "component": endpoint.component,
            "geography": endpoint.geography,
            "priority": endpoint.priority,
            "entitlement": endpoint.entitlement,
            "staleness_bound": endpoint.staleness_bound,
            "probe_symbol": symbol,
            "required": endpoint.required,
        }

        if endpoint.source_type == "manual_csv":
            return self._manual_capture_result(endpoint, base_kwargs)

        if endpoint.source_type in {"browser_or_file", "manual_or_ir"}:
            return self._manual_capture_result(
                endpoint, base_kwargs, status=BROWSER_REQUIRED
            )

        if not endpoint.probe_enabled:
            return PreflightResult(
                **base_kwargs,
                status=REGISTERED,
                url=endpoint.url_template,
                cache_path=None,
                as_of=None,
                notes=(
                    endpoint.note,
                    "Endpoint registered; probe disabled in the registry.",
                ),
            )

        if endpoint.probe_tier == "deep" and not deep and not cache_only:
            return PreflightResult(
                **base_kwargs,
                status=REGISTERED,
                url=endpoint.url_template,
                cache_path=None,
                as_of=None,
                notes=(
                    endpoint.note,
                    "Metered key: probed only under `preflight --deep`, so a routine run "
                    "leaves the daily request budget to the pipeline.",
                ),
            )

        if not symbol:
            return PreflightResult(
                **base_kwargs,
                status=SKIPPED,
                url=None,
                cache_path=None,
                as_of=None,
                notes=(endpoint.note, "No configured symbol for endpoint geography."),
            )

        credential = self.settings.credential(endpoint.credential_env)
        if endpoint.credential_env and not credential and not cache_only:
            return PreflightResult(
                **base_kwargs,
                status=NO_CREDENTIALS,
                url=None,
                cache_path=None,
                as_of=None,
                notes=(endpoint.note, f"Missing credential: {endpoint.credential_env}."),
            )

        extra_notes: list[str] = []
        try:
            substitutions = self._substitutions(
                endpoint, symbol, credential, run_date, cache_only
            )
        except ProbeContextError as exc:
            return PreflightResult(
                **base_kwargs,
                status=SKIPPED,
                url=endpoint.url_template,
                cache_path=None,
                as_of=None,
                notes=(endpoint.note, str(exc)),
            )

        if endpoint.source_id == "sec_edgar" and _is_placeholder_user_agent(
            self.settings.user_agent
        ):
            extra_notes.append(
                "BRIEFING_USER_AGENT is a placeholder contact; SEC EDGAR requires a real "
                "one and may throttle or block this agent without warning."
            )

        target = _cache_target(endpoint, symbol, substitutions)
        suffix = _cache_suffix(endpoint, endpoint.url_template or "")

        if cache_only:
            return self._cache_only_result(
                endpoint, symbol, target, suffix, run_date, substitutions,
                base_kwargs, extra_notes,
            )

        return self._network_result(
            endpoint, symbol, target, suffix, run_date, substitutions,
            base_kwargs, extra_notes,
        )

    # -- probe execution -------------------------------------------------------

    def _network_result(
        self,
        endpoint: EndpointDefinition,
        symbol: str,
        target: str,
        suffix: str,
        run_date: date,
        substitutions: dict[str, str],
        base_kwargs: dict[str, Any],
        extra_notes: list[str],
    ) -> PreflightResult:
        attempts = _probe_dates(endpoint, substitutions)
        last: PreflightResult | None = None

        for attempt, trade_date in enumerate(attempts):
            attempt_substitutions = dict(substitutions)
            if trade_date is not None:
                attempt_substitutions["trade_date"] = trade_date.strftime("%Y%m%d")
                attempt_substitutions["trade_date_iso"] = trade_date.isoformat()
                target = _cache_target(endpoint, symbol, attempt_substitutions)
            url = self._build_url(endpoint, attempt_substitutions)

            if endpoint.probe_delay_seconds and attempt == 0:
                time.sleep(endpoint.probe_delay_seconds)
            elif attempt:
                time.sleep(max(endpoint.probe_delay_seconds, 0.2))

            try:
                self._reserve_metered_probe(endpoint)
                response = self.fetcher.fetch(
                    url,
                    self.settings.http_timeout_seconds,
                    {"User-Agent": self.settings.user_agent, "Accept": _accept(endpoint)},
                )
            except BudgetExhausted as exc:
                last = PreflightResult(
                    **base_kwargs,
                    status=BUDGET_EXHAUSTED,
                    url=_redact(url),
                    cache_path=None,
                    as_of=None,
                    notes=(endpoint.note, *extra_notes, str(exc)),
                )
            except HTTPError as exc:
                # urlopen raises on 4xx, but the body is where the provider explains
                # itself - and for FMP that body is the only thing separating an endpoint
                # gate from a symbol gate. Both arrive as a bare HTTP 402.
                status, refusal_notes = _refusal_result(
                    exc.code, _error_body(exc), reason=exc.reason
                )
                last = PreflightResult(
                    **base_kwargs,
                    status=status,
                    url=_redact(url),
                    cache_path=None,
                    as_of=None,
                    notes=(endpoint.note, *extra_notes, *refusal_notes),
                )
            except URLError as exc:
                last = PreflightResult(
                    **base_kwargs,
                    status=NETWORK_ERROR,
                    url=_redact(url),
                    cache_path=None,
                    as_of=None,
                    notes=(endpoint.note, *extra_notes, f"Network error: {exc.reason}"),
                )
            except TimeoutError:
                last = PreflightResult(
                    **base_kwargs,
                    status=NETWORK_ERROR,
                    url=_redact(url),
                    cache_path=None,
                    as_of=None,
                    notes=(endpoint.note, *extra_notes, "Network timeout."),
                )
            else:
                last = self._result_from_response(
                    endpoint, target, suffix, run_date, response,
                    base_kwargs, extra_notes,
                )

            if last.status != MISSING or trade_date is None:
                return last

        assert last is not None
        return last

    def _reserve_metered_probe(self, endpoint: EndpointDefinition) -> None:
        if not endpoint.credential_env:
            return
        provider = endpoint.cache_provider or endpoint.source_id
        cache_endpoint = endpoint.cache_endpoint or endpoint.id
        self.budget.reserve(
            provider,
            cache_endpoint,
            plan=self.settings.provider_plan(provider),
        )

    def _result_from_response(
        self,
        endpoint: EndpointDefinition,
        target: str,
        suffix: str,
        run_date: date,
        response: HttpFetchResult,
        base_kwargs: dict[str, Any],
        extra_notes: list[str],
    ) -> PreflightResult:
        if response.status_code >= 400:
            status, refusal_notes = _refusal_result(
                response.status_code, response.body
            )
            return PreflightResult(
                **base_kwargs,
                status=status,
                url=_redact(response.url),
                cache_path=None,
                as_of=None,
                notes=(endpoint.note, *extra_notes, *refusal_notes),
            )

        cache_provider = endpoint.cache_provider or endpoint.source_id
        cache_endpoint = endpoint.cache_endpoint or endpoint.id

        binary = endpoint.response_format == "binary"
        if binary:
            suffix = _cache_suffix(endpoint, response.url)
            validation = validate_binary_payload(response.body)
        else:
            payload = _decode_response(response)
            validation = _validate_decoded_payload(payload, endpoint)

        # A refusal must never reach the cache. Providers answer a spent quota or a plan
        # gate with HTTP 200, so writing unconditionally replaces the day's good payload
        # with the notice - and that slot is what `--cache-only` replays.
        #
        # This deliberately narrows "Raw data is cached before parsing" (Definition of
        # Done for V1). It is a narrowing, not a breach: validation is a shape check, not
        # parsing, so every payload that yields data is still cached untouched before any
        # normalizer sees it. What no longer reaches the cache is a body that yields no
        # data at all, and its provenance survives in this result's notes, which quote
        # the provider verbatim. Do not restore the unconditional write thinking you are
        # fixing a regression against that line.
        cache_path: str | None = None
        if validation.ok and binary:
            cache_path = str(
                self.cache.write_bytes(
                    cache_provider, cache_endpoint, run_date, target, response.body, suffix
                )
            )
        elif validation.ok:
            cache_path = str(
                self.cache.write_json(
                    cache_provider, cache_endpoint, run_date, target, payload
                )
            )
        notes = (endpoint.note, *extra_notes, *validation.notes)
        if not validation.ok:
            notes = (
                *notes,
                "Not cached: a failed probe must not overwrite the day's payload.",
            )

        return PreflightResult(
            **base_kwargs,
            status=validation.status,
            url=_redact(response.url),
            cache_path=cache_path,
            as_of=validation.as_of,
            notes=notes,
        )

    def _cache_only_result(
        self,
        endpoint: EndpointDefinition,
        symbol: str,
        target: str,
        suffix: str,
        run_date: date,
        substitutions: dict[str, str],
        base_kwargs: dict[str, Any],
        extra_notes: list[str],
    ) -> PreflightResult:
        cache_provider = endpoint.cache_provider or endpoint.source_id
        cache_endpoint = endpoint.cache_endpoint or endpoint.id
        candidates = [target]
        for trade_date in _probe_dates(endpoint, substitutions):
            if trade_date is None:
                continue
            dated = dict(substitutions)
            dated["trade_date"] = trade_date.strftime("%Y%m%d")
            dated["trade_date_iso"] = trade_date.isoformat()
            candidates.append(_cache_target(endpoint, symbol, dated))

        for candidate in candidates:
            if self.cache.exists(cache_provider, cache_endpoint, run_date, candidate, suffix):
                if endpoint.response_format == "binary":
                    body = self.cache.read_bytes(
                        cache_provider, cache_endpoint, run_date, candidate, suffix
                    )
                    validation = validate_binary_payload(body)
                else:
                    payload = self.cache.read_json(
                        cache_provider, cache_endpoint, run_date, candidate
                    )
                    validation = _validate_decoded_payload(payload, endpoint)
                cache_path = self.cache.path(
                    cache_provider, cache_endpoint, run_date, candidate, suffix
                )
                return PreflightResult(
                    **base_kwargs,
                    status=validation.status,
                    url=None,
                    cache_path=str(cache_path),
                    as_of=validation.as_of,
                    notes=(endpoint.note, *extra_notes, *validation.notes),
                )

        if endpoint.credential_env and not self.settings.credential(endpoint.credential_env):
            return PreflightResult(
                **base_kwargs,
                status=NO_CREDENTIALS,
                url=None,
                cache_path=None,
                as_of=None,
                notes=(endpoint.note, f"Missing credential: {endpoint.credential_env}."),
            )

        return PreflightResult(
            **base_kwargs,
            status=MISSING,
            url=None,
            cache_path=str(
                self.cache.path(cache_provider, cache_endpoint, run_date, target, suffix)
            ),
            as_of=None,
            notes=(endpoint.note, *extra_notes, "Cache-only mode found no cached payload."),
        )

    def _manual_capture_result(
        self,
        endpoint: EndpointDefinition,
        base_kwargs: dict[str, Any],
        *,
        status: str = MANUAL_REQUIRED,
    ) -> PreflightResult:
        """Report what a manual source still needs, rather than only that it is manual.

        These sources cannot be probed, so the useful check is whether the capture
        schema and a dropped capture file actually exist on disk.
        """

        notes: list[str] = [endpoint.note]

        if endpoint.manual_schema:
            schema_path = Path(endpoint.manual_schema)
            if schema_path.exists():
                notes.append(f"Capture schema present: {schema_path}.")
            else:
                notes.append(f"Capture schema MISSING: {schema_path}.")

        capture_dir = self._manual_capture_dir(endpoint)
        captures = (
            sorted(path.name for path in capture_dir.iterdir() if path.is_file())
            if capture_dir.is_dir()
            else []
        )
        if captures:
            notes.append(
                f"{len(captures)} capture file(s) in {capture_dir}: {', '.join(captures[:5])}."
            )
        else:
            notes.append(f"No capture files in {capture_dir}; drop one there to load it.")

        if status == BROWSER_REQUIRED:
            notes.append("Source requires browser, file, or IR workflow.")

        return PreflightResult(
            **base_kwargs,
            status=status,
            url=endpoint.url_template,
            cache_path=str(capture_dir),
            as_of=None,
            notes=tuple(notes),
        )

    def _manual_capture_dir(self, endpoint: EndpointDefinition) -> Path:
        return (
            self.settings.data_dir
            / MANUAL_CAPTURE_DIR
            / (endpoint.cache_provider or endpoint.source_id)
            / (endpoint.cache_endpoint or endpoint.id)
        )

    # -- URL construction ------------------------------------------------------

    def _symbol_for_endpoint(self, endpoint: EndpointDefinition) -> str | None:
        if endpoint.probe_symbol:
            return endpoint.probe_symbol.strip().upper()
        geography = endpoint.geography[0] if endpoint.geography else "US"
        fallback = "SPY" if geography == "US" else None
        return first_symbol_for_geography(self.config, geography, fallback)

    def _substitutions(
        self,
        endpoint: EndpointDefinition,
        symbol: str,
        credential: str | None,
        run_date: date,
        cache_only: bool,
    ) -> dict[str, str]:
        template = endpoint.url_template or ""
        window_start = run_date - timedelta(days=endpoint.probe_window_days)
        values: dict[str, str] = {
            "ticker": quote(symbol, safe=".=-_"),
            "api_key": quote(credential or "", safe=""),
            "run_date": run_date.isoformat(),
            "from_date": window_start.isoformat(),
            "to_date": run_date.isoformat(),
            "year": str(run_date.year),
            "quarter": str((run_date.month - 1) // 3 + 1),
        }
        cache_target = endpoint.cache_target_template or ""
        needs_cik = "{cik" in template or "{cik" in cache_target
        if needs_cik or "{accession" in template or "{document" in template:
            cik = self._cik_for_ticker(symbol, run_date, cache_only)
            values["cik"] = str(int(cik))
            values["cik_padded"] = f"{int(cik):010d}"
        if "{accession" in template or "{document" in template:
            accession, document = self._recent_filing(
                values["cik_padded"], endpoint.probe_filing_forms, run_date, cache_only
            )
            values["accession"] = accession
            values["document"] = document
        if "{trade_date" in template:
            trade_date = _previous_business_day(run_date)
            values["trade_date"] = trade_date.strftime("%Y%m%d")
            values["trade_date_iso"] = trade_date.isoformat()
        return values

    def _recent_filing(
        self,
        padded_cik: str,
        forms: tuple[str, ...],
        run_date: date,
        cache_only: bool,
    ) -> tuple[str, str]:
        """Pick a real recent filing so the Archives path is probed, not assumed.

        Without this the document endpoint can only ever report `registered`: its URL
        needs an accession number that exists solely inside a submissions payload.
        """

        payload = self._company_submissions_payload(padded_cik, run_date, cache_only)
        recent = ((payload.get("filings") or {}).get("recent") or {})
        wanted = {form.strip().upper() for form in forms} or None
        rows = zip(
            recent.get("form", []),
            recent.get("accessionNumber", []),
            recent.get("primaryDocument", []),
        )
        for form, accession, document in rows:
            if wanted and str(form).strip().upper() not in wanted:
                continue
            if accession and document:
                return str(accession).replace("-", ""), str(document)
        raise ProbeContextError(
            f"No recent {'/'.join(forms) or 'filing'} to probe for CIK {padded_cik}."
        )

    def _company_submissions_payload(
        self, padded_cik: str, run_date: date, cache_only: bool
    ) -> dict[str, Any]:
        if self.cache.exists("sec_edgar", "company_submissions", run_date, padded_cik):
            payload = self.cache.read_json(
                "sec_edgar", "company_submissions", run_date, padded_cik
            )
            if isinstance(payload, dict):
                return payload
        if cache_only:
            raise ProbeContextError(
                "Cache-only mode has no cached SEC submissions to locate a filing in."
            )
        try:
            response = self.fetcher.fetch(
                f"https://data.sec.gov/submissions/CIK{padded_cik}.json",
                self.settings.http_timeout_seconds,
                {"User-Agent": self.settings.user_agent, "Accept": "application/json"},
            )
        except (HTTPError, URLError, TimeoutError) as exc:
            raise ProbeContextError(f"Could not load SEC submissions: {exc}")
        payload = _decode_response(response)
        if not isinstance(payload, dict):
            raise ProbeContextError("SEC submissions response was not a JSON document.")
        self.cache.write_json(
            "sec_edgar", "company_submissions", run_date, padded_cik, payload
        )
        return payload

    def _build_url(
        self, endpoint: EndpointDefinition, substitutions: dict[str, str]
    ) -> str:
        if not endpoint.url_template:
            raise ValueError(
                f"Endpoint has no URL template: {endpoint.source_id}.{endpoint.id}"
            )
        return endpoint.url_template.format(**substitutions)

    def _cik_for_ticker(self, ticker: str, run_date: date, cache_only: bool) -> str:
        """Resolve a ticker to its CIK from EDGAR's own mapping file.

        Probing `submissions/CIK{cik}.json` is the only way to tell a working EDGAR path
        from a registered one, and the mapping is the same file the provider layer uses.
        """

        clean = ticker.strip().upper()
        if self._cik_by_ticker is None:
            payload = self._company_tickers_payload(run_date, cache_only)
            mapping: dict[str, str] = {}
            rows = payload.values() if isinstance(payload, dict) else payload
            for row in rows:
                if isinstance(row, dict) and row.get("ticker") and row.get("cik_str"):
                    mapping[str(row["ticker"]).strip().upper()] = str(row["cik_str"])
            self._cik_by_ticker = mapping

        cik = self._cik_by_ticker.get(clean)
        if not cik:
            raise ProbeContextError(f"No SEC CIK is mapped for {clean}.")
        return cik

    def _company_tickers_payload(self, run_date: date, cache_only: bool) -> Any:
        cached = self.cache.exists("sec_edgar", "company_tickers", run_date, "all")
        if cached:
            return self.cache.read_json("sec_edgar", "company_tickers", run_date, "all")
        if cache_only:
            raise ProbeContextError(
                "Cache-only mode has no cached SEC ticker-to-CIK map to resolve from."
            )
        try:
            response = self.fetcher.fetch(
                "https://www.sec.gov/files/company_tickers.json",
                self.settings.http_timeout_seconds,
                {"User-Agent": self.settings.user_agent, "Accept": "application/json"},
            )
        except (HTTPError, URLError, TimeoutError) as exc:
            raise ProbeContextError(f"Could not load the SEC ticker-to-CIK map: {exc}")
        payload = _decode_response(response)
        self.cache.write_json("sec_edgar", "company_tickers", run_date, "all", payload)
        return payload


class ProbeContextError(RuntimeError):
    """A probe could not be built because a prerequisite lookup was unavailable."""


def _probe_dates(
    endpoint: EndpointDefinition, substitutions: dict[str, str]
) -> list[date | None]:
    """Dates to try for a date-stamped file, newest first.

    FINRA publishes the previous session's file on a T+1 schedule, so the file for the
    most recent weekday is routinely a 404 rather than an outage.
    """

    if "trade_date_iso" not in substitutions:
        return [None]
    start = date.fromisoformat(substitutions["trade_date_iso"])
    dates: list[date | None] = [start]
    cursor = start
    for _ in range(max(endpoint.probe_date_lookback_days, 0)):
        cursor = _previous_business_day(cursor)
        dates.append(cursor)
    return dates


def _previous_business_day(day: date) -> date:
    cursor = day - timedelta(days=1)
    while cursor.weekday() >= 5:
        cursor -= timedelta(days=1)
    return cursor


def _cache_target(
    endpoint: EndpointDefinition, symbol: str, substitutions: dict[str, str]
) -> str:
    if endpoint.cache_target_template:
        return endpoint.cache_target_template.format(symbol=symbol, **substitutions)
    return symbol


def _cache_suffix(endpoint: EndpointDefinition, url: str) -> str:
    if endpoint.response_format != "binary":
        return ".json"
    extension = Path(urlsplit(url).path).suffix.lower()
    return extension if extension in {".xlsx", ".xls", ".csv", ".pdf", ".zip"} else ".bin"


def _accept(endpoint: EndpointDefinition) -> str:
    if endpoint.response_format == "binary":
        return "application/octet-stream,*/*"
    if endpoint.response_format == "text":
        return "text/*,*/*"
    return "application/json,text/*,*/*"


def _error_body(exc: HTTPError) -> bytes:
    try:
        return exc.read() or b""
    except Exception:  # a consumed or unreadable error stream must not mask the status
        return b""


def _refusal_result(
    status_code: int, body: bytes, *, reason: str | None = None
) -> tuple[str, tuple[str, ...]]:
    """Derive a refusal's status and its explanation together, from one decision.

    A refusal reaches a reader through both, and making one of them right is not making
    the refusal right: a status of `throttled` beside a note saying the endpoint is plan
    gated is a report that contradicts itself. So the status decides first and the body
    may only narrow it - never widen it into a claim the status line does not support.

    The status line is not authoritative on its own either. This one API has answered a
    spent daily budget with 429 and three different plan gates with 402, so when the code
    says `paywalled` and the body names a quota, the body wins. That demotion runs one
    way: retrying a genuinely gated source costs a request, while retiring a working one
    costs a component.
    """

    excerpt = body.decode("utf-8", errors="replace").strip().replace("\n", " ")[:300]
    status = _status_from_http_code(status_code)
    if status == PAYWALLED and is_quota_notice(excerpt):
        status = THROTTLED

    notes = [f"HTTP {status_code}: {reason}." if reason else f"HTTP {status_code}."]

    if status == THROTTLED:
        # HTTP 429 is a rate signal in the status line by definition, and a demoted 402
        # has already been read as one. Either way no wording may retire the source:
        # relying on the phrasing is what let "upgrade your plan" mean two things.
        notes.append(
            "Spent quota or rate limit, not a plan gate: it clears on its own. Do not "
            "retire the source on this."
        )
    elif status == PAYWALLED:
        scope = classify_plan_gate(excerpt)
        if scope == GATE_SYMBOL:
            notes.append(
                "Plan gate is on the SYMBOL, not the endpoint: this endpoint works for "
                "other tickers. Probing it against a covered symbol measures the "
                "entitlement; it does not promise coverage for every name in the universe."
            )
        elif scope == GATE_PARAMETER:
            notes.append(
                "Plan gate is on a QUERY PARAMETER, not the endpoint: the endpoint is "
                "entitled and the request is out of plan. Fix the parameter, not the source."
            )
        elif scope == GATE_ENDPOINT:
            notes.append("Plan gate is on the ENDPOINT: fall back to another source.")

    if excerpt:
        notes.append(f"Provider said: {excerpt}")
    return status, tuple(notes)


def _redact(url: str | None) -> str | None:
    """Strip the API key so a report can be pasted into an issue or a doc."""

    if not url:
        return url
    import re

    return re.sub(r"(apikey|api_key|token)=[^&]+", r"\1=REDACTED", url)


def _decode_response(response: HttpFetchResult) -> Any:
    content_type = response.headers.get("Content-Type", "")
    text = response.body.decode("utf-8", errors="replace")
    if "json" in content_type.lower():
        return json.loads(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _validate_decoded_payload(
    payload: Any, endpoint: EndpointDefinition
) -> ValidationResult:
    if isinstance(payload, str):
        if endpoint.response_format == "text":
            return validate_text_data_payload(payload)
        return validate_text_payload(payload)
    return validate_payload(payload, endpoint.required_json_paths, endpoint.source_id)


def _is_placeholder_user_agent(user_agent: str) -> bool:
    lowered = user_agent.lower()
    return any(marker in lowered for marker in PLACEHOLDER_USER_AGENT_MARKERS)


def _status_from_http_code(status_code: int) -> str:
    if status_code == 429:
        return THROTTLED
    if status_code in {401, 402, 403}:
        return PAYWALLED
    if status_code == 404:
        return MISSING
    if status_code >= 500:
        return NETWORK_ERROR
    return MALFORMED
