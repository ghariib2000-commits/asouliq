import re
import tempfile
import unittest
from pathlib import Path

from app.clock import now_cairo
from app.db.connection import session
from app.egx_names_ar import EGX_NAMES_AR as NAMES
from app.egx_names_ar import arabic_name
from app.providers.base import ProviderResult, Quote
from app.services import names, prices
from tests.helpers import make_db

ARABIC = re.compile(r"[\u0600-\u06FF]")


def q(code: str, label: str, value: float) -> Quote:
    return Quote(code=code, label=label, value=value, unit="جنيه", decimals=2)


def egx_result(quotes) -> ProviderResult:
    return ProviderResult(
        provider_key="egx",
        provider_label="📈 البورصة المصرية",
        ok=True,
        fetched_at=now_cairo(),
        quotes=tuple(quotes),
        sources=("scanner.tradingview.com",),
        meta={"auto_register": True, "register_kind": "equity"},
    )


class ArabicNameMapTests(unittest.TestCase):
    def test_covers_almost_all_egx_stocks(self) -> None:
        self.assertGreaterEqual(len(NAMES), 290)

    def test_keys_are_clean_tickers(self) -> None:
        for code in NAMES:
            self.assertEqual(code, code.strip().upper())
            self.assertNotIn(" ", code)

    def test_values_are_arabic(self) -> None:
        for code, name in NAMES.items():
            self.assertTrue(ARABIC.search(name), f"{code} بلا حروف عربية: {name}")
            self.assertGreaterEqual(len(name.strip()), 3, code)

    def test_no_duplicate_names(self) -> None:
        duplicates = {n for n in NAMES.values() if list(NAMES.values()).count(n) > 1}
        self.assertEqual(duplicates, set())

    def test_lookup_is_case_insensitive(self) -> None:
        self.assertEqual(arabic_name("comi"), NAMES["COMI"])
        self.assertIsNone(arabic_name("NOPE"))
        self.assertIsNone(arabic_name(""))


class ArabicNameStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = make_db(Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _name_ar(self, code: str) -> str:
        with session(self.db) as conn:
            return conn.execute(
                "SELECT name_ar, name_en FROM assets WHERE code = ?", (code,)
            ).fetchone()["name_ar"]

    def test_mapped_stock_registers_with_arabic_name(self) -> None:
        prices.save_result(
            egx_result([q("COMI", "Commercial International Bank", 126.75)]), self.db
        )
        self.assertEqual(self._name_ar("COMI"), NAMES["COMI"])

    def test_unmapped_stock_keeps_english_name(self) -> None:
        prices.save_result(egx_result([q("NEWCO", "New Company", 5.0)]), self.db)
        self.assertEqual(self._name_ar("NEWCO"), "New Company")

    def test_existing_arabic_name_survives_refetch(self) -> None:
        prices.save_result(
            egx_result([q("COMI", "Commercial International Bank", 126.75)]), self.db
        )
        prices.save_result(
            egx_result([q("COMI", "Commercial International Bank", 127.10)]), self.db
        )
        self.assertEqual(self._name_ar("COMI"), NAMES["COMI"])

    def test_backfill_updates_old_english_rows(self) -> None:
        with session(self.db) as conn:
            conn.execute(
                "INSERT INTO assets (code, kind, name_ar, name_en, unit, provider_key) "
                "VALUES ('COMI', 'equity', 'Commercial International Bank', "
                "'Commercial International Bank', 'جنيه', 'egx')"
            )

        updated = names.apply_arabic_names(self.db)

        self.assertGreaterEqual(updated, 1)
        self.assertEqual(self._name_ar("COMI"), NAMES["COMI"])

    def test_arabic_search_finds_company(self) -> None:
        from app.services import assets

        prices.save_result(
            egx_result([q("SWDY", "El Sewedy Electric Company", 250.0)]), self.db
        )
        found = assets.search_assets("السويدي", db_path=self.db)
        self.assertEqual([row["code"] for row in found], ["SWDY"])


if __name__ == "__main__":
    unittest.main()
