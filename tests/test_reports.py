import asyncio
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from telegram.error import Forbidden

from app.clock import now_cairo
from app.db.connection import session
from app.providers.base import ProviderResult, Quote
from app.services import alerts, prices, reports, users, watchlist
from tests.helpers import make_db


class FakeBot:
    def __init__(self, error: Exception | None = None) -> None:
        self.messages: list[dict] = []
        self.error = error

    async def send_message(self, chat_id: int, text: str, parse_mode: str | None = None):
        if self.error:
            raise self.error
        self.messages.append({"chat_id": chat_id, "text": text})


class FakeApplication:
    def __init__(self, bot: FakeBot) -> None:
        self.bot = bot


class ParseTimeTests(unittest.TestCase):
    def test_accepts_common_formats(self) -> None:
        self.assertEqual(reports.parse_time("09:00"), (9, 0))
        self.assertEqual(reports.parse_time("21:30"), (21, 30))
        self.assertEqual(reports.parse_time("9"), (9, 0))
        self.assertEqual(reports.parse_time("9.5"), (9, 5))
        self.assertEqual(reports.parse_time(" ٠٩:٣٠ "), (9, 30))

    def test_rejects_invalid(self) -> None:
        for bad in ("", "24:00", "12:60", "abc", "-1:00", "12:aa", "99"):
            self.assertIsNone(reports.parse_time(bad), bad)


class ScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = make_db(Path(self._tmp.name))
        users.register_consent(1, "أحمد", self.db)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_set_and_read_schedule(self) -> None:
        reports.set_schedule(1, 8, 15, self.db)

        settings = reports.get_settings(1, self.db)

        self.assertEqual(settings["enabled"], 1)
        self.assertEqual((settings["hour"], settings["minute"]), (8, 15))

    def test_disable_keeps_saved_time(self) -> None:
        reports.set_schedule(1, 8, 15, self.db)
        reports.disable(1, self.db)

        settings = reports.get_settings(1, self.db)

        self.assertEqual(settings["enabled"], 0)
        self.assertEqual(settings["hour"], 8)

    def test_enable_without_schedule_uses_default(self) -> None:
        settings = reports.enable(1, self.db)

        self.assertEqual(settings["enabled"], 1)
        self.assertEqual(settings["hour"], reports.DEFAULT_HOUR)

    def test_invalid_schedule_rejected(self) -> None:
        with self.assertRaises(ValueError):
            reports.set_schedule(1, 25, 0, self.db)


class DueReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = make_db(Path(self._tmp.name))
        users.register_consent(1, "أحمد", self.db)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _due_at(self, hours: int, minutes: int) -> list[dict]:
        moment = now_cairo().replace(hour=hours, minute=minutes, second=0, microsecond=0)
        return reports.due_reports(moment, self.db)

    def test_not_due_before_time(self) -> None:
        reports.set_schedule(1, 10, 0, self.db)

        self.assertEqual(self._due_at(9, 59), [])

    def test_due_at_time_and_within_grace(self) -> None:
        reports.set_schedule(1, 10, 0, self.db)
        self.assertEqual(len(self._due_at(10, 0)), 1)

        reports.disable(1, self.db)
        reports.set_schedule(1, 10, 0, self.db)
        self.assertEqual(len(self._due_at(10, 30)), 1)

    def test_not_due_after_grace_window(self) -> None:
        reports.set_schedule(1, 10, 0, self.db)

        self.assertEqual(self._due_at(13, 0), [])

    def test_not_due_twice_same_day(self) -> None:
        reports.set_schedule(1, 10, 0, self.db)
        today = now_cairo().date().isoformat()
        reports.mark_sent(1, today, self.db)

        self.assertEqual(self._due_at(10, 5), [])

    def test_disabled_never_due(self) -> None:
        reports.set_schedule(1, 10, 0, self.db)
        reports.disable(1, self.db)

        self.assertEqual(self._due_at(10, 5), [])


class ReportContentTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = make_db(Path(self._tmp.name))
        users.register_consent(1, "أحمد", self.db)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _price(self, price: float, prev: float | None = None, minutes_ago: int = 1) -> None:
        prices.save_result(
            ProviderResult(
                provider_key="test",
                provider_label="اختبار",
                ok=True,
                fetched_at=now_cairo() - timedelta(minutes=minutes_ago),
                quotes=(Quote("USD", "دولار أمريكي", price, "جنيه", 2),),
                sources=("test-source",),
            ),
            self.db,
        )
        if prev is not None:
            with session(self.db) as conn:
                conn.execute(
                    "UPDATE latest_prices SET prev_price = ? WHERE asset_code = 'USD'", (prev,)
                )

    def test_empty_watchlist_sends_nothing(self) -> None:
        self.assertIsNone(reports.build_report(1, self.db))

    def test_report_shows_price_and_change(self) -> None:
        watchlist.add(1, "USD", self.db)
        self._price(56.0, prev=50.0)

        text = reports.build_report(1, self.db)

        self.assertIn("دولار أمريكي", text)
        self.assertIn("56.00", text)
        self.assertIn("+12.00%", text)
        self.assertIn("توصية استثمارية", text)

    def test_report_marks_stale_prices(self) -> None:
        watchlist.add(1, "USD", self.db)
        self._price(56.0, minutes_ago=60 * 24)

        text = reports.build_report(1, self.db)

        self.assertIn("أسعار قديمة", text)

    def test_report_mentions_active_alerts(self) -> None:
        watchlist.add(1, "USD", self.db)
        self._price(56.0)
        alerts.add_rule(1, "USD", alerts.RULE_ABOVE, 100, self.db)

        text = reports.build_report(1, self.db)

        self.assertIn("تنبيهات نشطة", text)


class SendDueReportsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = make_db(Path(self._tmp.name))
        users.register_consent(1, "أحمد", self.db)
        watchlist.add(1, "USD", self.db)
        prices.save_result(
            ProviderResult(
                provider_key="test",
                provider_label="اختبار",
                ok=True,
                fetched_at=now_cairo(),
                quotes=(Quote("USD", "دولار أمريكي", 56.0, "جنيه", 2),),
                sources=("test",),
            ),
            self.db,
        )
        reports.set_schedule(1, 9, 0, self.db)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _send(self, bot: FakeBot) -> int:
        moment = now_cairo().replace(hour=9, minute=1)
        with patch.object(reports, "due_reports", return_value=reports.due_reports(moment, self.db)), \
             patch.object(reports, "refresh_report_prices", return_value=[]):
            return asyncio.run(reports.send_due_reports(FakeApplication(bot), self.db))

    def test_sends_once_per_day(self) -> None:
        bot = FakeBot()

        self.assertEqual(self._send(bot), 1)
        self.assertEqual(len(bot.messages), 1)
        self.assertIn("تقريرك اليومي", bot.messages[0]["text"])

        self.assertEqual(self._send(bot), 0)
        self.assertEqual(len(bot.messages), 1)

    def test_blocked_bot_disables_report(self) -> None:
        bot = FakeBot(error=Forbidden("blocked"))

        self.assertEqual(self._send(bot), 0)

        settings = reports.get_settings(1, self.db)
        self.assertEqual(settings["enabled"], 0)


if __name__ == "__main__":
    unittest.main()
