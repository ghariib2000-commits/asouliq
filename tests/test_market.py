import time
import unittest

from app.clock import now_cairo
from app.providers import PROVIDERS
from app.providers.base import ProviderResult, Quote
from app.services import market


class FakeProvider:
    key = "fake"
    label = "خدمة تجريبية"

    def __init__(self) -> None:
        self.calls = 0

    def fetch(self) -> ProviderResult:
        self.calls += 1
        return ProviderResult(
            provider_key=self.key,
            provider_label=self.label,
            ok=True,
            fetched_at=now_cairo(),
            quotes=(Quote("x", "سعر", 1234.0, "جنيه"),),
        )


class MarketFormattingTests(unittest.TestCase):
    def setUp(self) -> None:
        market.clear_cache()

    def tearDown(self) -> None:
        market.clear_cache()

    def test_unavailable_message_has_no_prices(self) -> None:
        result = ProviderResult(
            provider_key="egx",
            provider_label="📈 البورصة المصرية",
            ok=False,
            fetched_at=now_cairo(),
            unavailable_reason="لا يوجد مصدر مرخّص.",
        )

        message = market.format_result(result)

        self.assertIn("البيانات غير متاحة", message)
        self.assertIn("لا يوجد مصدر مرخّص", message)
        self.assertNotIn("EGX 30", message)

    def test_success_message_shows_source_time_and_estimate_flag(self) -> None:
        result = ProviderResult(
            provider_key="gold",
            provider_label="🟡 أسعار الذهب في مصر",
            ok=True,
            fetched_at=now_cairo(),
            quotes=(Quote("gold_21", "عيار 21", 3760.0, "جنيه/جرام"),),
            sources=("api.gold-api.com",),
            is_estimate=True,
        )

        message = market.format_result(result)

        self.assertIn("3,760", message)
        self.assertIn("api.gold-api.com", message)
        self.assertIn("آخر تحديث", message)
        self.assertIn("تقديري", message)


class MarketCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        market.clear_cache()
        self.fake = FakeProvider()
        PROVIDERS["fake"] = self.fake

    def tearDown(self) -> None:
        PROVIDERS.pop("fake", None)
        market.clear_cache()

    def test_second_request_uses_cache(self) -> None:
        market.get_prices("fake")
        market.get_prices("fake")

        self.assertEqual(self.fake.calls, 1)

    def test_expired_cache_refetches(self) -> None:
        first = market.get_prices("fake")
        # نجعل المدخل منتهي الصلاحية كما لو مرت مدة الـTTL
        with market._cache_lock:
            market._cache["fake"] = (time.monotonic() - 1, first)

        market.get_prices("fake")

        self.assertEqual(self.fake.calls, 2)

    def test_unknown_service_is_reported_unavailable(self) -> None:
        result = market.get_prices("does-not-exist")

        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
