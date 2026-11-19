import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from app import config
from app.clock import now_cairo
from app.providers.base import ProviderResult, Quote
from app.services import prices
from tests.helpers import make_db


class RefreshCadenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = make_db(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _save(self, provider_key: str, minutes_ago: int) -> None:
        prices.save_result(
            ProviderResult(
                provider_key=provider_key,
                provider_label="اختبار",
                ok=True,
                fetched_at=now_cairo() - timedelta(minutes=minutes_ago),
                quotes=(Quote("USD", "دولار", 50.0, "جنيه", 2),),
                sources=("test",),
            ),
            self.db,
        )

    def test_newest_fetch_time(self) -> None:
        self._save("fx", minutes_ago=10)

        newest = prices.newest_fetched_at("fx", self.db)
        age = prices.seconds_since_fetch(newest)

        self.assertIsNotNone(newest)
        self.assertAlmostEqual(age, 600, delta=30)

    def test_seconds_since_fetch_handles_bad_value(self) -> None:
        self.assertIsNone(prices.seconds_since_fetch("not-a-date"))

    def test_provider_intervals_are_configured(self) -> None:
        self.assertGreater(config.PROVIDER_REFRESH_SECONDS["gold"], 0)
        self.assertGreaterEqual(
            config.PROVIDER_REFRESH_SECONDS["fx"], config.PROVIDER_REFRESH_SECONDS["gold"]
        )


if __name__ == "__main__":
    unittest.main()
