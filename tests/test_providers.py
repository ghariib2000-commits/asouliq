import unittest
from unittest.mock import patch

from app import config
from app.providers.egx import EgxProvider
from app.providers.gold_egp import TROY_OUNCE_GRAMS, GoldEgyptProvider


def fake_source(url: str) -> dict:
    if "er-api" in url:
        return {"rates": {"EGP": 50.0}}
    return {"price": 3000.0}


class GoldProviderTests(unittest.TestCase):
    def test_calculates_grams_with_transparent_math(self) -> None:
        with patch("app.providers.gold_egp._get_json", side_effect=fake_source):
            with patch.object(config, "GOLD_MARKET_PREMIUM", 1.018):
                result = GoldEgyptProvider().fetch()

        self.assertTrue(result.ok)
        self.assertTrue(result.is_estimate)
        self.assertEqual(len(result.quotes), 4)

        expected_24 = (3000.0 / TROY_OUNCE_GRAMS) * 50.0 * 1.018
        values = {quote.code: quote.value for quote in result.quotes}
        self.assertAlmostEqual(values["gold_24"], round(expected_24, 2), places=2)
        self.assertAlmostEqual(values["gold_21"], round(expected_24 * 21 / 24, 2), places=2)
        self.assertAlmostEqual(values["gold_18"], round(expected_24 * 18 / 24, 2), places=2)
        self.assertAlmostEqual(values["gold_pound"], round(expected_24 * 21 / 24 * 8, 2), places=2)
        self.assertIn("api.gold-api.com", result.sources)
        self.assertIn("open.er-api.com", result.sources)

    def test_failure_returns_no_numbers_at_all(self) -> None:
        with patch("app.providers.gold_egp._get_json", side_effect=OSError("network down")):
            result = GoldEgyptProvider().fetch()

        self.assertFalse(result.ok)
        self.assertEqual(result.quotes, ())
        self.assertIsNotNone(result.error)


class EgxProviderTests(unittest.TestCase):
    def test_never_reports_fabricated_prices(self) -> None:
        result = EgxProvider().fetch()

        self.assertFalse(result.ok)
        self.assertEqual(result.quotes, ())
        self.assertIsNotNone(result.unavailable_reason)
        self.assertNotIn("microsecond", str(result.meta))


if __name__ == "__main__":
    unittest.main()
