import tempfile
import unittest
from pathlib import Path

from app.clock import now_cairo
from app.providers.base import ProviderResult, Quote
from app.services import prices, users, watchlist
from tests.helpers import make_db


class WatchlistTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = make_db(self.root)
        users.register_consent(1, "أحمد", self.db)
        users.register_consent(2, "سارة", self.db)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_add_and_remove(self) -> None:
        self.assertTrue(watchlist.add(1, "USD", self.db))
        self.assertTrue(watchlist.contains(1, "USD", self.db))

        self.assertTrue(watchlist.remove(1, "USD", self.db))
        self.assertFalse(watchlist.contains(1, "USD", self.db))

    def test_duplicate_add_does_not_duplicate(self) -> None:
        watchlist.add(1, "USD", self.db)
        watchlist.add(1, "USD", self.db)

        self.assertEqual(watchlist.count(1, self.db), 1)

    def test_unknown_asset_is_rejected(self) -> None:
        self.assertFalse(watchlist.add(1, "NOT_REAL", self.db))
        self.assertEqual(watchlist.count(1, self.db), 0)

    def test_users_cannot_see_each_other(self) -> None:
        watchlist.add(1, "USD", self.db)
        watchlist.add(2, "EUR", self.db)

        codes_1 = [item["code"] for item in watchlist.items(1, self.db)]
        codes_2 = [item["code"] for item in watchlist.items(2, self.db)]

        self.assertEqual(codes_1, ["USD"])
        self.assertEqual(codes_2, ["EUR"])

    def test_item_shows_price_host_state(self) -> None:
        watchlist.add(1, "GOLD_21", self.db)
        prices.save_result(
            ProviderResult(
                provider_key="gold",
                provider_label="ذهب",
                ok=True,
                fetched_at=now_cairo(),
                quotes=(Quote("GOLD_21", "ذهب عيار 21", 5750.0, "جنيه/جرام", 2),),
                sources=("api.gold-api.com",),
            ),
            self.db,
        )

        item = watchlist.items(1, self.db)[0]

        self.assertAlmostEqual(item["price"], 5750.0, places=2)
        self.assertEqual(item["unit"], "جنيه/جرام")
        self.assertFalse(item["stale"])

    def test_item_without_price_is_marked_stale(self) -> None:
        watchlist.add(1, "CHF", self.db)

        item = watchlist.items(1, self.db)[0]

        self.assertIsNone(item["price"])
        self.assertTrue(item["stale"])

    def test_removing_other_users_item_does_nothing(self) -> None:
        watchlist.add(1, "USD", self.db)

        self.assertFalse(watchlist.remove(2, "USD", self.db))
        self.assertTrue(watchlist.contains(1, "USD", self.db))


if __name__ == "__main__":
    unittest.main()
