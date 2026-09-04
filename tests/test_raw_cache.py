from __future__ import annotations

from datetime import date
import tempfile
import unittest
from pathlib import Path

from briefing_app.raw_cache import RawCache, sanitize_path_segment


class RawCacheTests(unittest.TestCase):
    def test_sanitizes_path_segments(self) -> None:
        self.assertEqual(sanitize_path_segment("BRK.B"), "BRK.B")
        self.assertEqual(sanitize_path_segment("RHM DEX/EU"), "RHM_DEX_EU")
        self.assertEqual(sanitize_path_segment(" ... "), "unknown")

    def test_writes_and_reads_date_stamped_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = RawCache(Path(tmp))
            payload = {"data": {"options": [{"symbol": "SPY260116C00500000"}]}}

            path = cache.write_json(
                "cboe",
                "delayed_options_chain",
                date(2026, 8, 29),
                "SPY",
                payload,
            )

            self.assertTrue(path.exists())
            self.assertEqual(
                path.relative_to(tmp).as_posix(),
                "raw/cboe/delayed_options_chain/2026-08-29/SPY.json",
            )
            self.assertEqual(
                cache.read_json(
                    "cboe", "delayed_options_chain", date(2026, 8, 29), "SPY"
                ),
                payload,
            )


if __name__ == "__main__":
    unittest.main()
