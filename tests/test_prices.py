import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from app.clock import now_cairo
from app.providers.base import ProviderResult, Quote
from app.services import prices
from tests.helpers import make_db


def make_result(codes=("USD", "GOLD_21"), minutes_ago: int = 0) -> ProviderResult:
    return ProviderResult(
        provider_key="test",
        provider_label="اختبار",
        ok=True,
        fetched_at=now_cairo() - timedelta(minutes=minutes_ago),
        quotes=tuple(Quote(code, code, 10.5, "جنيه", 2) for code in codes),
        sources=("test-source",),
    )


class PriceStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = make_db(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_saves_and_updates_price(self) -> None:
        prices.save_result(make_result(), self.db)
        first = prices.latest("USD", self.db)
        self.assertAlmostEqual(first["price"], 10.5, places=2)
        self.assertEqual(first["source"], "test-source")

        result = make_result()
        result = ProviderResult(
            provider_key="test",
            provider_label="اختبار",
            ok=True,
            fetched_at=result.fetched_at,
            quotes=(Quote("USD", "USD", 11.0, "جنيه", 2),),
            sources=("test-source",),
        )
        prices.save_result(result, self.db)

        second = prices.latest("USD", self.db)
        self.assertAlmostEqual(second["price"], 11.0, places=2)

    def test_unregistered_asset_is_skipped(self) -> None:
        saved = prices.save_result(make_result(codes=("NOPE",)), self.db)

        self.assertEqual(saved, 0)
        self.assertIsNone(prices.latest("NOPE", self.db))

    def test_failed_result_saves_nothing(self) -> None:
        failed = ProviderResult(
            provider_key="test",
            provider_label="اختبار",
            ok=False,
            fetched_at=now_cairo(),
            error="down",
        )
        self.assertEqual(prices.save_result(failed, self.db), 0)

    def test_staleness_detection(self) -> None:
        prices.save_result(make_result(minutes_ago=90), self.db)
        row = prices.latest("USD", self.db)

        self.assertTrue(prices.is_stale(row, max_minutes=30))

        prices.save_result(make_result(minutes_ago=0), self.db)
        fresh = prices.latest("USD", self.db)
        self.assertFalse(prices.is_stale(fresh, max_minutes=30))


if __name__ == "__main__":
    unittest.main()
