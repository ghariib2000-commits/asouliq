import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.providers.egx import EgxProvider
from app.services import assets, prices
from tests.helpers import make_db

STOCKS = {
    "totalCount": 3,
    "data": [
        {"s": "EGX:COMI", "d": ["COMI", "Commercial International Bank", 126.75, 1.5, 1651136, "Finance"]},
        {"s": "EGX:HRHO", "d": ["HRHO", "EFG Holding", 25.4, -2.1, 2543032, "Finance"]},
        {"s": "EGX:BAD", "d": ["BAD", "No Price Co", None, 0.0, 0, "Other"]},
    ],
}

INDICES = {
    "data": [
        {"s": "EGX:EGX30", "d": ["EGX30", "EGX 30 Index", 51428.6, -0.22]},
    ]
}


def fake_scan(body: dict) -> dict:
    return INDICES if "symbols" in body else STOCKS


class EgxProviderTests(unittest.TestCase):
    def test_parses_stocks_and_skips_missing_prices(self) -> None:
        with patch("app.providers.egx._scan", side_effect=fake_scan):
            result = EgxProvider().fetch()

        self.assertTrue(result.ok)
        codes = {q.code: q for q in result.quotes}
        self.assertIn("COMI", codes)
        self.assertNotIn("BAD", codes)
        self.assertAlmostEqual(codes["COMI"].value, 126.75, places=2)
        self.assertAlmostEqual(codes["COMI"].change_pct, 1.5, places=2)
        self.assertEqual(codes["COMI"].unit, "جنيه")

    def test_includes_index_with_points_unit(self) -> None:
        with patch("app.providers.egx._scan", side_effect=fake_scan):
            result = EgxProvider().fetch()

        index = next(q for q in result.quotes if q.code == "EGX30")
        self.assertEqual(index.unit, "نقطة")
        self.assertAlmostEqual(index.value, 51428.6, places=1)

    def test_failure_returns_no_numbers(self) -> None:
        with patch("app.providers.egx._scan", side_effect=OSError("blocked")):
            result = EgxProvider().fetch()

        self.assertFalse(result.ok)
        self.assertEqual(result.quotes, ())
        self.assertIsNotNone(result.error)

    def test_indices_failure_still_returns_stocks(self) -> None:
        def only_stocks(body: dict) -> dict:
            if "symbols" in body:
                raise OSError("indices down")
            return STOCKS

        with patch("app.providers.egx._scan", side_effect=only_stocks):
            result = EgxProvider().fetch()

        self.assertTrue(result.ok)
        self.assertEqual({q.code for q in result.quotes}, {"COMI", "HRHO"})


class EgxAutoRegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = make_db(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_unknown_stock_becomes_asset_and_price(self) -> None:
        with patch("app.providers.egx._scan", side_effect=fake_scan):
            result = EgxProvider().fetch()

        saved = prices.save_result(result, self.db)

        self.assertGreater(saved, 0)
        comi = assets.get_asset("COMI", self.db)
        self.assertIsNotNone(comi)
        self.assertEqual(comi["kind"], "equity")
        self.assertEqual(comi["provider_key"], "egx")
        self.assertAlmostEqual(prices.latest("COMI", self.db)["price"], 126.75, places=2)

    def test_index_is_not_registered_as_equity(self) -> None:
        with patch("app.providers.egx._scan", side_effect=fake_scan):
            result = EgxProvider().fetch()

        prices.save_result(result, self.db)

        index = assets.get_asset("EGX30", self.db)
        self.assertEqual(index["kind"], "index")


if __name__ == "__main__":
    unittest.main()
