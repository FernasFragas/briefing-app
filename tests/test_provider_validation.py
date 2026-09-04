from __future__ import annotations

import unittest

from briefing_app.provider_validation import (
    GATE_ENDPOINT,
    GATE_PARAMETER,
    GATE_SYMBOL,
    MALFORMED,
    MISSING,
    OK,
    PLACEHOLDER,
    SYNTHETIC,
    THROTTLED,
    classify_plan_gate,
    is_quota_notice,
    validate_payload,
    validate_text_data_payload,
    validate_text_payload,
)


class ProviderValidationTests(unittest.TestCase):
    def test_accepts_payload_with_required_path(self) -> None:
        result = validate_payload(
            {"data": {"options": [{"option": "SPY260116C00500000"}]}},
            ("data.options",),
            "cboe_delayed_options",
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.status, OK)

    def test_rejects_missing_required_path(self) -> None:
        result = validate_payload({"data": {"options": []}}, ("data.options",))

        self.assertFalse(result.ok)
        self.assertEqual(result.status, MISSING)

    def test_rejects_alpha_vantage_message_payload(self) -> None:
        result = validate_payload(
            {
                "message": "This endpoint is premium-only.",
                "data": [
                    {
                        "contractID": "XXYYZZ999999C00020000",
                        "expiration": "2099-99-99",
                        "open_interest": 100,
                    }
                ],
            },
            ("data",),
            "alpha_vantage",
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, SYNTHETIC)

    def test_rejects_alpha_vantage_rate_limit_payload(self) -> None:
        result = validate_payload(
            {"note": "Thank you for using Alpha Vantage. Our standard API rate limit is 25 requests per day."},
            (),
            "alpha_vantage",
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, THROTTLED)

    def test_rejects_twelve_data_api_credits_payload_as_throttled(self) -> None:
        result = validate_payload(
            {"status": "error", "message": "You have run out of API credits for today."},
            (),
            "twelve_data",
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, THROTTLED)

    def test_rejects_suspicious_uniform_options(self) -> None:
        result = validate_payload(
            {
                "data": [
                    {
                        "contractID": f"TEST260116C{i:08d}",
                        "open_interest": 100,
                        "volume": 50,
                    }
                    for i in range(10)
                ]
            },
            ("data",),
            "alpha_vantage",
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, SYNTHETIC)

    def test_rejects_js_placeholder_text(self) -> None:
        result = validate_text_payload("<div>loading...</div>")

        self.assertFalse(result.ok)
        self.assertEqual(result.status, PLACEHOLDER)


class PlanGateClassificationTests(unittest.TestCase):
    """Verbatim provider bodies, captured live against the project's own keys.

    FMP answers an out-of-plan endpoint, an out-of-plan symbol, an out-of-plan query
    parameter and a spent daily budget all with the same HTTP 402/429 shape. Only the
    body separates them, and only the endpoint case means the source is unusable, so
    these strings are pinned rather than paraphrased.
    """

    #: Captured 2026-08-30 from stable/news/stock with a free key.
    ENDPOINT_GATE = (
        "Restricted Endpoint: This endpoint is not available under your current "
        "subscription please visit our subscription page to upgrade your plan at "
        "https://financialmodelingprep.com/"
    )
    #: Captured 2026-08-30 from stable/quote?symbol=AVGO with a free key. AAPL, MSFT and
    #: SPY answered 200 in the same second; AVGO, ORCL, MU and QQQ answered this.
    SYMBOL_GATE = (
        "Premium Query Parameter: 'Special Endpoint : This value set for 'symbol' is not "
        "available under your current subscription please visit our subscription page to "
        "upgrade your plan at https://financialmodelingprep.com/"
    )
    #: Captured 2026-08-30 from stable/income-statement?symbol=AAPL&limit=8.
    LIMIT_GATE = (
        "Premium Query Parameter: 'Special Parameters : The values for 'limit' must be "
        "between 0 and 5 based on your current subscription. Please visit our "
        "subscription page to upgrade your plan at https://financialmodelingprep.com/"
    )
    #: Captured 2026-08-30 from stable/analyst-estimates?symbol=AAPL&period=quarter.
    PERIOD_GATE = (
        "Premium Query Parameter: 'Special Endpoint : This value set for 'period' is not "
        "available under your current subscription please visit our subscription page to "
        "upgrade your plan at https://financialmodelingprep.com/"
    )
    #: Captured 2026-08-30 once the free daily budget was spent. Note it says "upgrade
    #: your plan" while meaning nothing of the sort.
    FMP_QUOTA = (
        '{ "Error Message": "Limit Reach . Please upgrade your plan or visit our '
        'documentation for more details at https://site.financialmodelingprep.com/" }'
    )
    #: Captured 2026-08-30 once the free Alpha Vantage daily budget was spent.
    ALPHA_VANTAGE_QUOTA = (
        "Thank you for using Alpha Vantage! We have detected your API key and our "
        "standard API rate limit is 25 requests per day. Please subscribe to any of the "
        "premium plans at https://www.alphavantage.co/premium/ to instantly remove all "
        "daily rate limits."
    )

    def test_endpoint_gate_is_the_only_one_that_retires_a_source(self) -> None:
        self.assertEqual(classify_plan_gate(self.ENDPOINT_GATE), GATE_ENDPOINT)

    def test_symbol_gate_is_not_an_endpoint_gate(self) -> None:
        self.assertEqual(classify_plan_gate(self.SYMBOL_GATE), GATE_SYMBOL)

    def test_parameter_gates_are_not_endpoint_gates(self) -> None:
        self.assertEqual(classify_plan_gate(self.LIMIT_GATE), GATE_PARAMETER)
        self.assertEqual(classify_plan_gate(self.PERIOD_GATE), GATE_PARAMETER)

    def test_spent_quota_is_never_a_plan_gate(self) -> None:
        """FMP words a spent budget as "upgrade your plan"; it clears at midnight."""

        for body in (self.FMP_QUOTA, self.ALPHA_VANTAGE_QUOTA):
            with self.subTest(body=body[:40]):
                self.assertTrue(is_quota_notice(body))
                self.assertIsNone(classify_plan_gate(body))
                self.assertEqual(validate_text_payload(body).status, THROTTLED)

    #: Captured 2026-08-30 from EARNINGS_CALENDAR once the free daily budget was spent.
    #: The header is real; the single data row is "Informa" - the first seven characters
    #: of "Information" - one per column, truncated to the header's width.
    THROTTLED_CSV = (
        "symbol,name,reportDate,fiscalDateEnding,estimate,currency,timeOfTheDay\r\n"
        "I,n,f,o,r,m,a\r\n"
    )

    def test_a_refusal_shaped_like_csv_is_not_data(self) -> None:
        result = validate_text_data_payload(self.THROTTLED_CSV)
        self.assertFalse(result.ok)
        self.assertEqual(result.status, MALFORMED)

    def test_real_delimited_feeds_still_validate(self) -> None:
        for body in (
            "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n"
            "20260828|AAPL|1000|0|5000|Q\n",
            "symbol,name,reportDate\nAAPL,APPLE INC,2026-10-29\n",
            "symbol,name,reportDate\n",
        ):
            with self.subTest(body=body[:30]):
                self.assertTrue(validate_text_data_payload(body).ok)

    def test_an_ordinary_body_is_not_a_gate(self) -> None:
        self.assertIsNone(classify_plan_gate(""))
        self.assertIsNone(classify_plan_gate("Date|Symbol|ShortVolume\n20260828|A|1"))


if __name__ == "__main__":
    unittest.main()
