from __future__ import annotations

from datetime import UTC, date, datetime
import json
import tempfile
import unittest
import zipfile
import io
from pathlib import Path
from urllib.error import HTTPError

from briefing_app.preflight import (
    HttpFetchResult,
    MANUAL_REQUIRED,
    NO_CREDENTIALS,
    OK,
    PreflightRunner,
    SKIPPED,
    _previous_business_day,
    _refusal_result,
)
from briefing_app.provider_validation import MISSING, PAYWALLED, THROTTLED
from briefing_app.providers.budget import RequestBudget
from briefing_app.settings import AppSettings
from briefing_app.source_registry import SourceRegistry


CBOE_URL_MARK = "cdn.cboe.com"
FINRA_URL_MARK = "cdn.finra.org"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

OPTIONS_PAYLOAD = {
    "data": {
        "timestamp": "2026-08-29T13:30:00Z",
        "current_price": 500.0,
        "options": [
            {
                "option": "SPY260904C00500000",
                "bid": 4.5,
                "ask": 4.7,
                "open_interest": 1224,
            }
        ],
    }
}


def json_result(url: str, payload) -> HttpFetchResult:
    return HttpFetchResult(
        status_code=200,
        body=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        url=url,
    )


class RoutingFetcher:
    """Answers each probe with a body shaped like the real source's."""

    def __init__(self, **overrides) -> None:
        self.calls: list[str] = []
        self.overrides = overrides

    def fetch(self, url: str, timeout_seconds: float, headers: dict[str, str]):
        self.calls.append(url)
        for mark, handler in self.overrides.items():
            if mark in url:
                return handler(url)
        return json_result(url, OPTIONS_PAYLOAD)


class FailingFetcher:
    def fetch(self, url: str, timeout_seconds: float, headers: dict[str, str]):
        raise AssertionError("cache-only preflight should not fetch")


class PreflightTests(unittest.TestCase):
    def test_cboe_probe_writes_cache_and_reports_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = make_test_settings(Path(tmp))
            fetcher = RoutingFetcher()
            report = PreflightRunner(settings=settings, fetcher=fetcher).run(
                run_date=date(2026, 8, 29),
                write_report=True,
            )

            cboe = result_for(report, "cboe_delayed_options", "delayed_options_chain")

            self.assertEqual(cboe.status, OK)
            self.assertEqual(cboe.probe_symbol, "SPY")
            self.assertTrue(cboe.cache_path)
            self.assertTrue(Path(cboe.cache_path).exists())
            self.assertTrue(any(CBOE_URL_MARK in call for call in fetcher.calls))
            self.assertTrue((Path(tmp) / "output" / "preflight" / "latest.json").exists())

    def test_cache_only_replays_cached_probe_without_fetching(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = make_test_settings(Path(tmp))
            PreflightRunner(settings=settings, fetcher=RoutingFetcher()).run(
                run_date=date(2026, 8, 29),
                write_report=False,
            )

            report = PreflightRunner(settings=settings, fetcher=FailingFetcher()).run(
                cache_only=True,
                run_date=date(2026, 8, 29),
                write_report=False,
            )

            cboe = result_for(report, "cboe_delayed_options", "delayed_options_chain")
            self.assertEqual(cboe.status, OK)

    def test_cache_only_keeps_missing_credentials_soft_without_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = make_test_settings(Path(tmp))
            report = PreflightRunner(settings=settings, fetcher=FailingFetcher()).run(
                cache_only=True,
                run_date=date(2026, 8, 29),
                write_report=False,
            )

            alpha = result_for(report, "alpha_vantage", "symbol_search")
            self.assertEqual(alpha.status, NO_CREDENTIALS)

            keyed = {
                f"{result.source_id}.{result.endpoint_id}": result.status
                for result in report.results
                if result.source_id in {"alpha_vantage", "fmp"}
            }
            self.assertTrue(keyed)
            data_failures = {
                name: status
                for name, status in keyed.items()
                if status not in {NO_CREDENTIALS, SKIPPED}
            }
            self.assertEqual(
                data_failures,
                {},
                "an unkeyed cache-only run must not report keyed sources as data failures",
            )

    def test_plan_gated_endpoint_reports_its_status_without_failing_the_run(self) -> None:
        """A known entitlement ceiling must stay visible without masking a regression."""

        def paywalled(url: str) -> HttpFetchResult:
            return HttpFetchResult(
                status_code=402,
                body=b"Restricted Endpoint: not available under your current subscription",
                headers={"Content-Type": "text/plain"},
                url=url,
            )

        with tempfile.TemporaryDirectory() as tmp:
            settings = make_test_settings(Path(tmp), fmp_api_key="key")
            report = PreflightRunner(
                settings=settings,
                fetcher=RoutingFetcher(**{"news/stock": paywalled}),
            ).run(run_date=date(2026, 8, 29), write_report=False)

            news = result_for(report, "fmp", "stock_news")
            self.assertEqual(news.status, PAYWALLED)
            self.assertFalse(news.required)
            self.assertNotIn(
                "fmp.stock_news",
                [
                    f"{result.source_id}.{result.endpoint_id}"
                    for result in report.results
                    if result.required and result.status not in {OK}
                ],
            )

    def test_symbol_gated_refusal_is_not_reported_as_an_endpoint_gate(self) -> None:
        """FMP's free plan gates by symbol too, and answers HTTP 402 either way.

        Reading a symbol gate as an endpoint gate retires a working source; the note has
        to say which one it is, because only an endpoint gate means use the fallback.
        """

        def symbol_gated(url: str) -> HttpFetchResult:
            return HttpFetchResult(
                status_code=402,
                body=(
                    b"Premium Query Parameter: 'Special Endpoint : This value set for "
                    b"'symbol' is not available under your current subscription"
                ),
                headers={"Content-Type": "text/plain"},
                url=url,
            )

        with tempfile.TemporaryDirectory() as tmp:
            settings = make_test_settings(Path(tmp), fmp_api_key="key")
            report = PreflightRunner(
                settings=settings,
                fetcher=RoutingFetcher(**{"stable/quote": symbol_gated}),
            ).run(run_date=date(2026, 8, 29), write_report=False)

            quote = result_for(report, "fmp", "quote")
            self.assertEqual(quote.status, PAYWALLED)
            notes = " ".join(quote.notes)
            self.assertIn("Plan gate is on the SYMBOL", notes)
            self.assertNotIn("Plan gate is on the ENDPOINT", notes)
            self.assertIn("Provider said:", notes)

    def test_refusal_body_is_read_when_the_fetcher_raises(self) -> None:
        """urlopen raises on 4xx, so the explaining body is only on the exception.

        Without reading it every FMP refusal collapses to `HTTP 402: Payment Required`,
        which is exactly the distinction that matters.
        """

        def raising(url: str):
            raise HTTPError(
                url,
                402,
                "Payment Required",
                {},
                io.BytesIO(
                    b"Premium Query Parameter: 'Special Endpoint : This value set for "
                    b"'symbol' is not available under your current subscription"
                ),
            )

        with tempfile.TemporaryDirectory() as tmp:
            settings = make_test_settings(Path(tmp), fmp_api_key="key")
            report = PreflightRunner(
                settings=settings,
                fetcher=RoutingFetcher(**{"stable/quote": raising}),
            ).run(run_date=date(2026, 8, 29), write_report=False)

            quote = result_for(report, "fmp", "quote")
            self.assertEqual(quote.status, PAYWALLED)
            notes = " ".join(quote.notes)
            self.assertIn("Plan gate is on the SYMBOL", notes)
            self.assertIn("Payment Required", notes)

    def test_unreadable_error_stream_still_reports_the_status(self) -> None:
        class Unreadable:
            def read(self):
                raise OSError("stream already consumed")

            def close(self):
                pass

        def raising(url: str):
            raise HTTPError(url, 403, "Forbidden", {}, Unreadable())

        with tempfile.TemporaryDirectory() as tmp:
            settings = make_test_settings(Path(tmp), fmp_api_key="key")
            report = PreflightRunner(
                settings=settings,
                fetcher=RoutingFetcher(**{"stable/quote": raising}),
            ).run(run_date=date(2026, 8, 29), write_report=False)

            quote = result_for(report, "fmp", "quote")
            self.assertEqual(quote.status, PAYWALLED)
            self.assertIn("HTTP 403: Forbidden.", " ".join(quote.notes))

    def test_spent_quota_is_not_reported_as_an_endpoint_gate(self) -> None:
        """FMP words a spent daily budget as "upgrade your plan".

        Reported as an endpoint gate it would tell a reader to retire a working source
        over a refusal that clears at midnight.
        """

        def out_of_quota(url: str):
            raise HTTPError(
                url,
                429,
                "Too Many Requests",
                {},
                io.BytesIO(
                    b'{"Error Message": "Limit Reach . Please upgrade your plan or visit '
                    b'our documentation for more details at https://site.financialmodelingprep.com/"}'
                ),
            )

        with tempfile.TemporaryDirectory() as tmp:
            settings = make_test_settings(Path(tmp), fmp_api_key="key")
            report = PreflightRunner(
                settings=settings,
                fetcher=RoutingFetcher(**{"financialmodelingprep.com": out_of_quota}),
            ).run(run_date=date(2026, 8, 29), write_report=False)

            quote = result_for(report, "fmp", "quote")
            self.assertEqual(quote.status, THROTTLED)
            notes = " ".join(quote.notes)
            self.assertIn("clears on its own", notes)
            self.assertNotIn("Plan gate is on the ENDPOINT", notes)

    def test_quota_body_overrules_a_402_status_line(self) -> None:
        """The status code is not authoritative about what a refusal means.

        FMP has used 429 for a spent budget and 402 for three different plan gates;
        nothing stops it using 402 for the budget too. Labelling a quota `paywalled` is
        the one error that tells a reader to retire a source that is working.
        """

        def quota_as_402(url: str):
            raise HTTPError(
                url,
                402,
                "Payment Required",
                {},
                io.BytesIO(b'{"Error Message": "Limit Reach . Please upgrade your plan"}'),
            )

        with tempfile.TemporaryDirectory() as tmp:
            settings = make_test_settings(Path(tmp), fmp_api_key="key")
            report = PreflightRunner(
                settings=settings,
                fetcher=RoutingFetcher(**{"stable/quote": quota_as_402}),
            ).run(run_date=date(2026, 8, 29), write_report=False)

            quote = result_for(report, "fmp", "quote")
            self.assertEqual(quote.status, THROTTLED)
            self.assertIn("clears on its own", " ".join(quote.notes))

    def test_a_real_gate_on_402_is_still_paywalled(self) -> None:
        """The body only overrules the code toward the safer reading, not away from it."""

        def gate_as_402(url: str):
            raise HTTPError(
                url,
                402,
                "Payment Required",
                {},
                io.BytesIO(
                    b"Restricted Endpoint: This endpoint is not available under your "
                    b"current subscription"
                ),
            )

        with tempfile.TemporaryDirectory() as tmp:
            settings = make_test_settings(Path(tmp), fmp_api_key="key")
            report = PreflightRunner(
                settings=settings,
                fetcher=RoutingFetcher(**{"stable/quote": gate_as_402}),
            ).run(run_date=date(2026, 8, 29), write_report=False)

            quote = result_for(report, "fmp", "quote")
            self.assertEqual(quote.status, PAYWALLED)
            self.assertIn("Plan gate is on the ENDPOINT", " ".join(quote.notes))

    def test_endpoint_gated_refusal_says_to_fall_back(self) -> None:
        def endpoint_gated(url: str) -> HttpFetchResult:
            return HttpFetchResult(
                status_code=402,
                body=b"Restricted Endpoint: This endpoint is not available under your current subscription",
                headers={"Content-Type": "text/plain"},
                url=url,
            )

        with tempfile.TemporaryDirectory() as tmp:
            settings = make_test_settings(Path(tmp), fmp_api_key="key")
            report = PreflightRunner(
                settings=settings,
                fetcher=RoutingFetcher(**{"news/stock": endpoint_gated}),
            ).run(run_date=date(2026, 8, 29), write_report=False)

            news = result_for(report, "fmp", "stock_news")
            self.assertEqual(news.status, PAYWALLED)
            self.assertIn("Plan gate is on the ENDPOINT", " ".join(news.notes))

    def test_a_refusal_never_overwrites_the_days_cached_payload(self) -> None:
        """The cache slot is what `--cache-only` replays, so a refusal must not land in it.

        Providers answer a spent quota with HTTP 200 and a notice body, so a probe that
        writes before validating replaces a good morning payload with an afternoon
        refusal - losing the only copy and poisoning every later deterministic replay.
        """

        good = {"data": {"timestamp": "2026-08-29T13:30:00Z", "options": [{"option": "X"}]}}
        refusal = {
            "Information": "We have detected your API key and our standard API rate "
            "limit is 25 requests per day."
        }
        run_date = date(2026, 8, 29)

        with tempfile.TemporaryDirectory() as tmp:
            settings = make_test_settings(Path(tmp))
            cache_path = (
                settings.data_dir / "raw" / "cboe" / "delayed_options_chain"
                / run_date.isoformat() / "SPY.json"
            )
            cache_path.parent.mkdir(parents=True)
            cache_path.write_text(json.dumps(good), encoding="utf-8")

            report = PreflightRunner(
                settings=settings,
                fetcher=RoutingFetcher(
                    **{CBOE_URL_MARK: lambda url: json_result(url, refusal)}
                ),
            ).run(run_date=run_date, write_report=False)

            cboe = result_for(report, "cboe_delayed_options", "delayed_options_chain")
            self.assertEqual(cboe.status, THROTTLED)
            self.assertIsNone(cboe.cache_path)
            self.assertIn("Not cached", " ".join(cboe.notes))
            self.assertEqual(json.loads(cache_path.read_text()), good)

    def test_a_valid_payload_is_still_cached(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = make_test_settings(Path(tmp))
            report = PreflightRunner(settings=settings, fetcher=RoutingFetcher()).run(
                run_date=date(2026, 8, 29), write_report=False
            )
            cboe = result_for(report, "cboe_delayed_options", "delayed_options_chain")
            self.assertEqual(cboe.status, OK)
            self.assertTrue(cboe.cache_path and Path(cboe.cache_path).exists())

    def test_metered_preflight_probe_increments_budget_but_free_probe_does_not(
        self,
    ) -> None:
        registry = """\
version: 1
sources:
  - id: cboe_delayed_options
    display_name: CBOE public delayed options chain
    priority: primary
    geography: [US]
    source_type: http_json
    components: [S_O]
    entitlement: free_delayed
    staleness_bound: same_session
    endpoints:
      - id: delayed_options_chain
        component: S_O
        method: GET
        url_template: https://cdn.cboe.com/api/global/delayed_quotes/options/{ticker}.json
        cache_provider: cboe
        cache_endpoint: delayed_options_chain
        probe_enabled: true
        probe_symbol: SPY
        required_json_paths: [data.options]
        note: Test CBOE probe.
  - id: alpha_vantage
    display_name: Alpha Vantage
    priority: primary_or_fallback
    geography: [US]
    source_type: http_json
    components: [S_O]
    entitlement: key_required_plan_gated
    staleness_bound: endpoint_specific
    credential_env: ALPHA_VANTAGE_API_KEY
    endpoints:
      - id: symbol_search
        component: reference
        method: GET
        url_template: https://www.alphavantage.co/query?function=SYMBOL_SEARCH&keywords={ticker}&apikey={api_key}
        cache_provider: alpha_vantage
        cache_endpoint: symbol_search
        probe_enabled: true
        probe_symbol: SPY
        required_json_paths: [root]
        note: Test Alpha Vantage always probe.
      - id: news_sentiment
        component: S_S
        method: GET
        url_template: https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers={ticker}&apikey={api_key}
        cache_provider: alpha_vantage
        cache_endpoint: news_sentiment
        probe_enabled: true
        probe_tier: deep
        probe_symbol: SPY
        required_json_paths: [root]
        note: Test Alpha Vantage deep probe.
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "source_registry.yaml"
            registry_path.write_text(registry, encoding="utf-8")
            settings = make_test_settings(
                root,
                alpha_vantage_api_key="key",
                source_registry_path=registry_path,
            )
            budget_day = date(2026, 8, 31)
            budget = RequestBudget(
                settings.data_dir,
                sleep=lambda _: None,
                now=lambda: datetime(2026, 8, 31, tzinfo=UTC),
            )

            report = PreflightRunner(
                settings=settings, fetcher=RoutingFetcher(), budget=budget
            ).run(run_date=date(2026, 8, 29), write_report=False, deep=True)

            self.assertEqual(
                result_for(report, "cboe_delayed_options", "delayed_options_chain").status,
                OK,
            )
            self.assertEqual(result_for(report, "alpha_vantage", "symbol_search").status, OK)
            self.assertEqual(
                result_for(report, "alpha_vantage", "news_sentiment").status,
                OK,
            )
            self.assertEqual(budget.spent("alpha_vantage", day=budget_day), 2)
            ledger = json.loads(
                budget.path("alpha_vantage", budget_day).read_text(encoding="utf-8")
            )
            self.assertEqual(ledger["endpoints"]["symbol_search"], 1)
            self.assertEqual(ledger["endpoints"]["news_sentiment"], 1)
            self.assertFalse((settings.data_dir / "provider_budget" / "cboe").exists())

    def test_shipped_registry_does_not_probe_historical_put_call_ratio(self) -> None:
        """The endpoint spends quota but supplies no dated baseline the app can use."""

        endpoints = [
            endpoint.id
            for endpoint in SourceRegistry.from_file(
                Path("config/source_registry.yaml")
            ).endpoints()
            if endpoint.source_id == "alpha_vantage"
        ]

        self.assertNotIn("historical_put_call_ratio", endpoints)
        self.assertIn("realtime_put_call_ratio", endpoints)

    def test_throttled_csv_endpoint_is_not_reported_as_data(self) -> None:
        """Alpha Vantage hides a CSV refusal inside a valid-looking CSV body.

        Reported as `ok` this becomes "no earnings scheduled", which is exactly the
        reading the registry note warns against.
        """

        def throttled_csv(url: str) -> HttpFetchResult:
            return HttpFetchResult(
                200,
                b"symbol,name,reportDate,fiscalDateEnding,estimate,currency,timeOfTheDay"
                b"\r\nI,n,f,o,r,m,a\r\n",
                {"Content-Type": "application/x-download"},
                url,
            )

        with tempfile.TemporaryDirectory() as tmp:
            settings = make_test_settings(Path(tmp), alpha_vantage_api_key="key")
            report = PreflightRunner(
                settings=settings,
                fetcher=RoutingFetcher(**{"EARNINGS_CALENDAR": throttled_csv}),
            ).run(run_date=date(2026, 8, 29), write_report=False, deep=True)

            earnings = result_for(report, "alpha_vantage", "earnings_calendar")
            self.assertNotEqual(earnings.status, OK)
            self.assertIsNone(earnings.cache_path)

    def test_finra_probe_walks_back_to_the_last_published_session(self) -> None:
        """The consolidated file lands on T+1, so the newest weekday is routinely a 404."""

        published = date(2026, 8, 26).strftime("%Y%m%d")
        body = (
            "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n"
            f"{published}|AAPL|1000|0|5000|Q\n"
        )

        def finra(url: str) -> HttpFetchResult:
            if published in url:
                return HttpFetchResult(
                    200, body.encode("utf-8"), {"Content-Type": "text/plain"}, url
                )
            return HttpFetchResult(404, b"Not Found", {"Content-Type": "text/plain"}, url)

        with tempfile.TemporaryDirectory() as tmp:
            settings = make_test_settings(Path(tmp))
            fetcher = RoutingFetcher(**{FINRA_URL_MARK: finra})
            report = PreflightRunner(settings=settings, fetcher=fetcher).run(
                run_date=date(2026, 8, 29), write_report=False
            )

            finra_result = result_for(report, "finra", "short_sale_volume")
            self.assertEqual(finra_result.status, OK)
            self.assertIn(published, finra_result.url or "")
            self.assertIn(f"CNMS_{published}", finra_result.cache_path or "")

    def test_binary_source_is_cached_verbatim_rather_than_decoded(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("xl/worksheets/sheet1.xml", "<sheet/>" * 400)
        spreadsheet = buffer.getvalue()

        def fca(url: str) -> HttpFetchResult:
            return HttpFetchResult(
                200,
                spreadsheet,
                {"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
                url,
            )

        with tempfile.TemporaryDirectory() as tmp:
            settings = make_test_settings(Path(tmp))
            report = PreflightRunner(
                settings=settings, fetcher=RoutingFetcher(**{"fca.org.uk": fca})
            ).run(run_date=date(2026, 8, 29), write_report=False)

            fca_result = result_for(report, "bundesanzeiger_fca", "fca_short_positions")
            self.assertEqual(fca_result.status, OK)
            self.assertTrue(fca_result.cache_path.endswith(".xlsx"))
            self.assertEqual(Path(fca_result.cache_path).read_bytes(), spreadsheet)

    def test_html_answer_to_a_binary_source_is_not_read_as_a_spreadsheet(self) -> None:
        def blocked(url: str) -> HttpFetchResult:
            return HttpFetchResult(
                200,
                b"<html><body>Access denied</body></html>",
                {"Content-Type": "text/html"},
                url,
            )

        with tempfile.TemporaryDirectory() as tmp:
            settings = make_test_settings(Path(tmp))
            report = PreflightRunner(
                settings=settings, fetcher=RoutingFetcher(**{"fca.org.uk": blocked})
            ).run(run_date=date(2026, 8, 29), write_report=False)

            fca_result = result_for(report, "bundesanzeiger_fca", "fca_short_positions")
            self.assertEqual(fca_result.status, PAYWALLED)

    def test_sec_probes_resolve_a_cik_and_a_real_filing(self) -> None:
        submissions = {
            "cik": "0000320193",
            "filings": {
                "recent": {
                    "form": ["8-K", "4"],
                    "accessionNumber": ["0000320193-26-000018", "0001140361-26-034741"],
                    "primaryDocument": ["aapl-8k.htm", "xslF345X06/form4.xml"],
                }
            },
        }

        def sec(url: str) -> HttpFetchResult:
            if "company_tickers.json" in url:
                return json_result(
                    url, {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
                )
            if "/submissions/" in url:
                return json_result(url, submissions)
            return HttpFetchResult(
                200, b"<html>form 4 body</html>", {"Content-Type": "text/html"}, url
            )

        with tempfile.TemporaryDirectory() as tmp:
            settings = make_test_settings(Path(tmp))
            report = PreflightRunner(
                settings=settings,
                fetcher=RoutingFetcher(**{"sec.gov": sec}),
            ).run(run_date=date(2026, 8, 29), write_report=False)

            self.assertEqual(result_for(report, "sec_edgar", "company_tickers").status, OK)

            submissions_result = result_for(report, "sec_edgar", "company_submissions")
            self.assertEqual(submissions_result.status, OK)
            self.assertIn("CIK0000320193.json", submissions_result.url or "")

            document = result_for(report, "sec_edgar", "filing_document")
            self.assertEqual(document.status, OK)
            self.assertIn("000114036126034741", document.url or "")
            self.assertIn("form4.xml", document.url or "")

    def test_placeholder_user_agent_is_flagged_on_sec_probes(self) -> None:
        """SEC requires a real contact and may throttle a generic agent without warning."""

        with tempfile.TemporaryDirectory() as tmp:
            settings = make_test_settings(
                Path(tmp), user_agent="briefing-app/0.1 contact@example.com"
            )
            report = PreflightRunner(
                settings=settings,
                fetcher=RoutingFetcher(
                    **{
                        "sec.gov": lambda url: json_result(
                            url, {"0": {"cik_str": 320193, "ticker": "AAPL"}}
                        )
                    }
                ),
            ).run(run_date=date(2026, 8, 29), write_report=False)

            tickers = result_for(report, "sec_edgar", "company_tickers")
            self.assertTrue(
                any("placeholder contact" in note for note in tickers.notes),
                tickers.notes,
            )

    def test_manual_source_reports_schema_and_capture_presence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = make_test_settings(Path(tmp))
            capture_dir = (
                settings.data_dir / "manual" / "eurex" / "manual_options_capture"
            )
            capture_dir.mkdir(parents=True)
            (capture_dir / "eurex-2026-08-29.csv").write_text("ticker\n", encoding="utf-8")

            report = PreflightRunner(settings=settings, fetcher=RoutingFetcher()).run(
                run_date=date(2026, 8, 29), write_report=False
            )

            eurex = result_for(report, "manual_eurex_capture", "options_chain_capture")
            self.assertEqual(eurex.status, MANUAL_REQUIRED)
            notes = " ".join(eurex.notes)
            self.assertIn("Capture schema present", notes)
            self.assertIn("eurex-2026-08-29.csv", notes)

    def test_probe_urls_never_carry_the_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = make_test_settings(
                Path(tmp), alpha_vantage_api_key="SECRETKEY", fmp_api_key="SECRETKEY"
            )
            report = PreflightRunner(settings=settings, fetcher=RoutingFetcher()).run(
                run_date=date(2026, 8, 29), write_report=False
            )

            leaked = [
                f"{result.source_id}.{result.endpoint_id}"
                for result in report.results
                if result.url and "SECRETKEY" in result.url
            ]
            self.assertEqual(leaked, [])

    def test_previous_business_day_skips_the_weekend(self) -> None:
        self.assertEqual(_previous_business_day(date(2026, 8, 31)), date(2026, 8, 28))
        self.assertEqual(_previous_business_day(date(2026, 8, 29)), date(2026, 8, 28))


class RefusalReadingTests(unittest.TestCase):
    """The six refusal shapes this API actually produces, read end to end.

    A refusal reaches a reader as both a status and an explanation. Getting one right is
    not getting the refusal right, so these assert the pair together: the status decides
    what the note may claim, and no wording can make a `throttled` response read as a
    reason to retire an endpoint.
    """

    ENDPOINT_GATE = b"Restricted Endpoint: This endpoint is not available under your current subscription"
    SYMBOL_GATE = b"Premium Query Parameter: 'Special Endpoint : This value set for 'symbol' is not available"
    LIMIT_GATE = b"Premium Query Parameter: 'Special Parameters : The values for 'limit' must be between 0 and 5"
    QUOTA = b'{"Error Message": "Limit Reach . Please upgrade your plan"}'
    #: Not observed from this provider, but it is the shape that defeats a wording-only
    #: check: rate language in the status line, plan-gate language in the body, and none
    #: of the quota phrases, because it says "higher limits" rather than "rate limit".
    UPSELL_ON_429 = b"Too Many Requests. Upgrade your plan for higher limits."

    def test_only_a_true_endpoint_gate_tells_a_reader_to_fall_back(self) -> None:
        cases = [
            (402, self.ENDPOINT_GATE, PAYWALLED, "Plan gate is on the ENDPOINT"),
            (402, self.SYMBOL_GATE, PAYWALLED, "Plan gate is on the SYMBOL"),
            (402, self.LIMIT_GATE, PAYWALLED, "Plan gate is on a QUERY PARAMETER"),
            (429, self.QUOTA, THROTTLED, "clears on its own"),
            (402, self.QUOTA, THROTTLED, "clears on its own"),
            (429, self.UPSELL_ON_429, THROTTLED, "clears on its own"),
        ]
        for status_code, body, expected_status, expected_note in cases:
            with self.subTest(code=status_code, body=body[:40]):
                status, notes = _refusal_result(status_code, body)
                joined = " ".join(notes)
                self.assertEqual(status, expected_status)
                self.assertIn(expected_note, joined)
                if expected_status is THROTTLED:
                    self.assertNotIn("Plan gate is on the ENDPOINT", joined)

    def test_the_provider_is_always_quoted(self) -> None:
        """The classification is a reading; the body is the evidence for it."""

        _, notes = _refusal_result(402, self.SYMBOL_GATE)
        self.assertIn("Provider said:", " ".join(notes))

    def test_a_body_never_promotes_a_refusal_to_paywalled(self) -> None:
        """Reconciliation runs one way: toward retrying, never toward retiring."""

        status, _ = _refusal_result(429, self.ENDPOINT_GATE)
        self.assertEqual(status, THROTTLED)


class RegistryShapeTests(unittest.TestCase):
    def test_every_probed_endpoint_has_a_url_template(self) -> None:
        registry = SourceRegistry.from_file(Path("config/source_registry.yaml"))
        broken = [
            f"{endpoint.source_id}.{endpoint.id}"
            for endpoint in registry.endpoints()
            if endpoint.probe_enabled and not endpoint.url_template
        ]
        self.assertEqual(broken, [])

    def test_no_probed_endpoint_still_targets_the_retired_fmp_api(self) -> None:
        """FMP's v3/v4 bases answer HTTP 403 `Legacy Endpoint` regardless of key."""

        registry = SourceRegistry.from_file(Path("config/source_registry.yaml"))
        legacy = [
            f"{endpoint.source_id}.{endpoint.id}"
            for endpoint in registry.endpoints()
            if endpoint.url_template
            and ("financialmodelingprep.com/api/v3" in endpoint.url_template
                 or "financialmodelingprep.com/api/v4" in endpoint.url_template)
        ]
        self.assertEqual(legacy, [])

    def test_per_symbol_fmp_probes_name_a_covered_reference_symbol(self) -> None:
        """FMP free gates by symbol: AVGO/ORCL/MU/QQQ 402 where AAPL/MSFT/SPY do not.

        A probe left on the universe symbol would report the whole endpoint as paywalled
        the day the head of the universe happens to be an uncovered name.
        """

        registry = SourceRegistry.from_file(Path("config/source_registry.yaml"))
        unpinned = [
            endpoint.id
            for endpoint in registry.endpoints()
            if endpoint.source_id == "fmp"
            and endpoint.probe_enabled
            and "{ticker}" in (endpoint.url_template or "")
            and not endpoint.probe_symbol
        ]
        self.assertEqual(unpinned, [])

    def test_analyst_ratings_reads_grades_not_a_vendor_score(self) -> None:
        """`ratings-snapshot` is a vendor scoring model; S_S wants analyst grade counts."""

        registry = SourceRegistry.from_file(Path("config/source_registry.yaml"))
        ratings = next(
            endpoint
            for endpoint in registry.endpoints()
            if endpoint.source_id == "fmp" and endpoint.id == "analyst_ratings"
        )
        self.assertIn("grades-consensus", ratings.url_template or "")

    def test_alpha_vantage_probes_are_paced(self) -> None:
        """Above ~1 req/s Alpha Vantage answers HTTP 200 with a rate-limit notice."""

        registry = SourceRegistry.from_file(Path("config/source_registry.yaml"))
        unpaced = [
            endpoint.id
            for endpoint in registry.endpoints()
            if endpoint.source_id == "alpha_vantage"
            and endpoint.probe_enabled
            and endpoint.probe_delay_seconds < 1.0
        ]
        self.assertEqual(unpaced, [])


def result_for(report, source_id: str, endpoint_id: str):
    return next(
        result
        for result in report.results
        if result.source_id == source_id and result.endpoint_id == endpoint_id
    )


def make_test_settings(
    tmp: Path,
    *,
    alpha_vantage_api_key: str | None = None,
    fmp_api_key: str | None = None,
    user_agent: str = "briefing-app-test",
    source_registry_path: Path = Path("config/source_registry.yaml"),
) -> AppSettings:
    return AppSettings(
        config_path=Path("config/config.example.yaml"),
        source_registry_path=source_registry_path,
        data_dir=tmp / "data",
        output_dir=tmp / "output",
        http_timeout_seconds=1,
        user_agent=user_agent,
        alpha_vantage_api_key=alpha_vantage_api_key,
        fmp_api_key=fmp_api_key,
    )


if __name__ == "__main__":
    unittest.main()
