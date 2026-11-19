import unittest
from unittest.mock import patch

from app.providers.fx import FxProvider

PAYLOAD = {
    "rates": {"EGP": 50.0, "USD": 1.0, "EUR": 0.9, "JPY": 150.0, "SAR": 3.75},
    "time_last_update_utc": "Thu, 19 Nov 2026 00:00:00 +0000",
}


class FxProviderTests(unittest.TestCase):
    def test_converts_to_egyptian_pounds(self) -> None:
        with patch("app.providers.fx._get_json", return_value=PAYLOAD):
            result = FxProvider().fetch()

        self.assertTrue(result.ok)
        values = {quote.code: quote.value for quote in result.quotes}

        self.assertAlmostEqual(values["USD"], 50.0, places=2)
        self.assertAlmostEqual(values["EUR"], round(50.0 / 0.9, 2), places=2)
        self.assertAlmostEqual(values["SAR"], round(50.0 / 3.75, 2), places=2)

    def test_yen_is_priced_per_hundred_units(self) -> None:
        with patch("app.providers.fx._get_json", return_value=PAYLOAD):
            result = FxProvider().fetch()

        yen = next(q for q in result.quotes if q.code == "JPY")
        self.assertAlmostEqual(yen.value, round(50.0 / 150.0 * 100, 2), places=2)
        self.assertEqual(yen.unit, "جنيه/100 وحدة")

    def test_source_failure_returns_no_prices(self) -> None:
        with patch("app.providers.fx._get_json", side_effect=OSError("down")):
            result = FxProvider().fetch()

        self.assertFalse(result.ok)
        self.assertEqual(result.quotes, ())
        self.assertIsNotNone(result.error)

    def test_unavailable_currencies_are_skipped_not_faked(self) -> None:
        payload = {"rates": {"EGP": 50.0, "USD": 1.0}}
        with patch("app.providers.fx._get_json", return_value=payload):
            result = FxProvider().fetch()

        self.assertTrue(result.ok)
        self.assertEqual([q.code for q in result.quotes], ["USD"])


if __name__ == "__main__":
    unittest.main()
