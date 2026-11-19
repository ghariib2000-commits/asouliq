import asyncio
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from app.clock import now_cairo
from app.db.connection import connect
from app.providers.base import ProviderResult, Quote
from app.services import alerts, notifier, prices, users
from tests.helpers import make_db


class FakeBot:
    def __init__(self, error: Exception | None = None) -> None:
        self.messages: list[dict] = []
        self.error = error

    async def send_message(self, chat_id: int, text: str, parse_mode: str | None = None):
        if self.error:
            raise self.error
        self.messages.append({"chat_id": chat_id, "text": text, "parse_mode": parse_mode})


class FakeApplication:
    def __init__(self, bot: FakeBot) -> None:
        self.bot = bot


class NotifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = make_db(self.root)
        users.register_consent(1, "أحمد", self.db)
        prices.save_result(
            ProviderResult(
                provider_key="test",
                provider_label="اختبار",
                ok=True,
                fetched_at=now_cairo() - timedelta(minutes=1),
                quotes=(Quote("USD", "دولار أمريكي", 56.0, "جنيه", 2),),
                sources=("test-source",),
            ),
            self.db,
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_message_includes_price_source_and_disclaimer(self) -> None:
        alerts.add_rule(1, "USD", alerts.RULE_ABOVE, 55, self.db)
        alert = alerts.due_alerts(self.db)[0]

        message = notifier.format_alert(alert)

        self.assertIn("56.00", message)
        self.assertIn("test-source", message)
        self.assertIn("توصية استثمارية", message)

    def test_cycle_sends_and_marks_rule(self) -> None:
        rule_id = alerts.add_rule(1, "USD", alerts.RULE_ABOVE, 55, self.db)
        bot = FakeBot()

        with patch.object(notifier, "refresh_alert_prices", return_value=[]):
            sent = asyncio.run(notifier.run_cycle(FakeApplication(bot), self.db))

        self.assertEqual(sent, 1)
        self.assertEqual(len(bot.messages), 1)
        self.assertEqual(bot.messages[0]["chat_id"], 1)

        conn = connect(self.db)
        try:
            status = conn.execute("SELECT status FROM notification_log").fetchone()["status"]
            triggered = conn.execute(
                "SELECT last_triggered_at FROM alert_rules WHERE id = ?", (rule_id,)
            ).fetchone()["last_triggered_at"]
        finally:
            conn.close()

        self.assertEqual(status, alerts.STATUS_SENT)
        self.assertIsNotNone(triggered)

    def test_send_failure_is_logged_and_rule_retried(self) -> None:
        from telegram.error import TelegramError

        rule_id = alerts.add_rule(1, "USD", alerts.RULE_ABOVE, 55, self.db)
        bot = FakeBot(error=TelegramError("boom"))

        with patch.object(notifier, "refresh_alert_prices", return_value=[]):
            sent = asyncio.run(notifier.run_cycle(FakeApplication(bot), self.db))

        self.assertEqual(sent, 0)
        conn = connect(self.db)
        try:
            status = conn.execute("SELECT status FROM notification_log").fetchone()["status"]
            triggered = conn.execute(
                "SELECT last_triggered_at FROM alert_rules WHERE id = ?", (rule_id,)
            ).fetchone()["last_triggered_at"]
        finally:
            conn.close()

        self.assertEqual(status, alerts.STATUS_FAILED)
        self.assertIsNone(triggered, "الفشل لا يحجب المحاولة القادمة")


if __name__ == "__main__":
    unittest.main()
