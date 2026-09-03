from __future__ import annotations

from datetime import date

from briefing_app.providers.base import BaseProviderClient, ProviderResponse
from briefing_app.providers.normalizers import (
    normalize_sec_company_submissions,
    normalize_sec_company_tickers,
)


class SecEdgarClient(BaseProviderClient):
    provider_id = "sec_edgar"
    data_base_url = "https://data.sec.gov"
    sec_base_url = "https://www.sec.gov"

    def fetch_company_tickers(
        self, *, run_date: date, cache_only: bool = False
    ) -> ProviderResponse:
        return self.fetch_json_url(
            endpoint="company_tickers",
            target="all",
            url=f"{self.sec_base_url}/files/company_tickers.json",
            run_date=run_date,
            required_json_paths=("root",),
            validation_provider_id=self.provider_id,
            cache_only=cache_only,
        )

    def fetch_company_submissions(
        self,
        cik: str | int,
        *,
        run_date: date,
        cache_only: bool = False,
    ) -> ProviderResponse:
        padded_cik = f"{int(cik):010d}"
        return self.fetch_json_url(
            endpoint="company_submissions",
            target=padded_cik,
            url=f"{self.data_base_url}/submissions/CIK{padded_cik}.json",
            run_date=run_date,
            required_json_paths=("filings.recent.form",),
            validation_provider_id=self.provider_id,
            cache_only=cache_only,
        )

    def fetch_company_submissions_by_ticker(
        self,
        ticker: str,
        *,
        run_date: date,
        cache_only: bool = False,
    ) -> ProviderResponse:
        clean_ticker = ticker.strip().upper()
        tickers = self.fetch_company_tickers(run_date=run_date, cache_only=cache_only)
        ticker_to_cik = normalize_sec_company_tickers(tickers.payload)
        cik = ticker_to_cik[clean_ticker]
        return self.fetch_company_submissions(cik, run_date=run_date, cache_only=cache_only)

    def fetch_filing_document(
        self,
        cik: str | int,
        accession_number: str,
        primary_document: str,
        *,
        run_date: date,
        cache_only: bool = False,
    ) -> ProviderResponse:
        clean_cik = str(int(cik))
        accession_path = accession_number.replace("-", "")
        target = f"{clean_cik}_{accession_path}_{primary_document}"
        return self.fetch_text_url(
            endpoint="filing_document",
            target=target,
            url=(
                f"{self.sec_base_url}/Archives/edgar/data/"
                f"{clean_cik}/{accession_path}/{primary_document}"
            ),
            run_date=run_date,
            cache_only=cache_only,
        )

    def get_recent_filings(
        self,
        ticker_or_cik: str | int,
        *,
        run_date: date,
        forms: set[str] | None = None,
        cache_only: bool = False,
    ):
        if isinstance(ticker_or_cik, int) or str(ticker_or_cik).strip().isdigit():
            response = self.fetch_company_submissions(
                ticker_or_cik,
                run_date=run_date,
                cache_only=cache_only,
            )
            ticker = None
        else:
            ticker = str(ticker_or_cik).strip().upper()
            response = self.fetch_company_submissions_by_ticker(
                ticker,
                run_date=run_date,
                cache_only=cache_only,
            )

        records = normalize_sec_company_submissions(ticker, response.payload)
        if not forms:
            return records
        clean_forms = {form.strip().upper() for form in forms}
        return [record for record in records if record.form.upper() in clean_forms]
