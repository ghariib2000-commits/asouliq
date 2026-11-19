import tempfile
import unittest
from pathlib import Path

from app.catalog import ASSETS, CURRENCIES, GOLD_ASSETS, count_by_kind, sync_assets
from app.db.connection import connect
from app.services import assets
from tests.helpers import make_db


class CatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = make_db(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_all_eighteen_currencies_and_gold_are_seeded(self) -> None:
        self.assertEqual(len(CURRENCIES), 18)
        self.assertEqual(len(GOLD_ASSETS), 4)
        self.assertEqual(len(ASSETS), 22)

        conn = connect(self.db)
        try:
            kinds = count_by_kind(conn)
        finally:
            conn.close()

        self.assertEqual(kinds["currency"], 18)
        self.assertEqual(kinds["commodity"], 4)

    def test_sync_is_idempotent(self) -> None:
        sync_assets(self.db)
        sync_assets(self.db)

        conn = connect(self.db)
        try:
            total = conn.execute("SELECT COUNT(*) AS c FROM assets").fetchone()["c"]
        finally:
            conn.close()
        self.assertEqual(total, 22)

    def test_yen_uses_hundred_unit_quoting(self) -> None:
        yen = assets.get_asset("JPY", self.db)

        self.assertEqual(yen["quote_unit"], 100)
        self.assertEqual(yen["unit"], "جنيه/100 وحدة")

    def test_search_by_arabic_name_and_code(self) -> None:
        by_name = assets.search_assets("دولار", db_path=self.db)
        by_code = assets.search_assets("usd", db_path=self.db)

        self.assertTrue(any(a["code"] == "USD" for a in by_name))
        self.assertTrue(any(a["code"] == "USD" for a in by_code))

    def test_search_returns_empty_for_unknown_term(self) -> None:
        self.assertEqual(assets.search_assets("لايوجد", db_path=self.db), [])


if __name__ == "__main__":
    unittest.main()
