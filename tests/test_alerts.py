import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from app.clock import now_cairo
from app.providers.base import ProviderResult, Quote
from app.services import alerts, prices, users
from tests.helpers import make_db


def save_price(db, code: str, value: float, minutes_ago: int = 0) -> None:
    prices.save_result(
        ProviderResult(
            provider_key="test",
            provider_label="اختبار",
            ok=True,
            fetched_at=now_cairo() - timedelta(minutes=minutes_ago),
            quotes=(Quote(code, code, value, "جنيه", 2),),
            sources=("test-source",),
        ),
        db,
    )


class AlertRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = make_db(self.root)
        users.register_consent(1, "أحمد", self.db)
        users.register_consent(2, "سارة", self.db)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_create_rule(self) -> None:
        rule_id = alerts.add_rule(1, "USD", alerts.RULE_ABOVE, 55, self.db)

        self.assertIsNotNone(rule_id)
        rules = alerts.list_rules(1, self.db)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["threshold"], 55)

    def test_invalid_inputs_are_rejected(self) -> None:
        self.assertIsNone(alerts.add_rule(1, "NOPE", alerts.RULE_ABOVE, 55, self.db))
        self.assertIsNone(alerts.add_rule(1, "USD", "wrong_type", 55, self.db))
        self.assertIsNone(alerts.add_rule(1, "USD", alerts.RULE_ABOVE, 0, self.db))
        self.assertIsNone(alerts.add_rule(1, "USD", alerts.RULE_PCT_UP, -3, self.db))

    def test_duplicate_rule_is_ignored(self) -> None:
        alerts.add_rule(1, "USD", alerts.RULE_ABOVE, 55, self.db)
        second = alerts.add_rule(1, "USD", alerts.RULE_ABOVE, 55, self.db)

        self.assertIsNone(second)
        self.assertEqual(alerts.count_rules(1, self.db), 1)

    def test_rules_are_isolated_between_users(self) -> None:
        alerts.add_rule(1, "USD", alerts.RULE_ABOVE, 55, self.db)
        alerts.add_rule(2, "EUR", alerts.RULE_BELOW, 50, self.db)

        self.assertEqual([r["asset_code"] for r in alerts.list_rules(1, self.db)], ["USD"])
        self.assertEqual([r["asset_code"] for r in alerts.list_rules(2, self.db)], ["EUR"])

    def test_cannot_delete_other_users_rule(self) -> None:
        rule_id = alerts.add_rule(1, "USD", alerts.RULE_ABOVE, 55, self.db)

        self.assertFalse(alerts.remove_rule(2, rule_id, self.db))
        self.assertTrue(alerts.remove_rule(1, rule_id, self.db))

    def test_arabic_type_aliases(self) -> None:
        self.assertEqual(alerts.normalize_rule_type("فوق"), alerts.RULE_ABOVE)
        self.assertEqual(alerts.normalize_rule_type("تحت"), alerts.RULE_BELOW)
        self.assertEqual(alerts.normalize_rule_type("up"), alerts.RULE_PCT_UP)
        self.assertEqual(alerts.normalize_rule_type("انخفاض"), alerts.RULE_PCT_DOWN)


class AlertEvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = make_db(self.root)
        users.register_consent(1, "أحمد", self.db)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_price_above_triggers_when_reached(self) -> None:
        alerts.add_rule(1, "USD", alerts.RULE_ABOVE, 55, self.db)
        save_price(self.db, "USD", 56.0)

        due = alerts.due_alerts(self.db)

        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["asset_code"], "USD")

    def test_price_above_does_not_trigger_below_threshold(self) -> None:
        alerts.add_rule(1, "USD", alerts.RULE_ABOVE, 55, self.db)
        save_price(self.db, "USD", 54.0)

        self.assertEqual(alerts.due_alerts(self.db), [])

    def test_price_below_triggers(self) -> None:
        alerts.add_rule(1, "USD", alerts.RULE_BELOW, 50, self.db)
        save_price(self.db, "USD", 49.5)

        due = alerts.due_alerts(self.db)
        self.assertEqual(len(due), 1)

    def test_percent_up_uses_previous_price(self) -> None:
        save_price(self.db, "USD", 100.0)
        save_price(self.db, "USD", 102.0)
        alerts.add_rule(1, "USD", alerts.RULE_PCT_UP, 2, self.db)

        due = alerts.due_alerts(self.db)

        self.assertEqual(len(due), 1)
        self.assertAlmostEqual(due[0]["change_pct"], 2.0, places=2)

    def test_percent_down_triggers_only_on_negative_move(self) -> None:
        save_price(self.db, "USD", 100.0)
        save_price(self.db, "USD", 103.0)
        alerts.add_rule(1, "USD", alerts.RULE_PCT_DOWN, 2, self.db)

        self.assertEqual(alerts.due_alerts(self.db), [])

    def test_stale_price_never_triggers(self) -> None:
        alerts.add_rule(1, "USD", alerts.RULE_ABOVE, 55, self.db)
        save_price(self.db, "USD", 60.0, minutes_ago=180)

        self.assertEqual(alerts.due_alerts(self.db), [])

    def test_cooldown_prevents_repeat(self) -> None:
        rule_id = alerts.add_rule(1, "USD", alerts.RULE_ABOVE, 55, self.db)
        save_price(self.db, "USD", 60.0)

        first = alerts.due_alerts(self.db)
        self.assertEqual(len(first), 1)

        alerts.mark_triggered(rule_id, alerts.STATUS_SENT, self.db)

        self.assertEqual(alerts.due_alerts(self.db), [])

    def test_notification_log_records_status(self) -> None:
        alerts.add_rule(1, "USD", alerts.RULE_ABOVE, 55, self.db)
        save_price(self.db, "USD", 60.0)
        due = alerts.due_alerts(self.db)[0]

        alerts.log_notification(due, alerts.STATUS_SENT, "رسالة", None, self.db)

        from app.db.connection import connect

        conn = connect(self.db)
        try:
            row = conn.execute("SELECT status, price FROM notification_log").fetchone()
        finally:
            conn.close()
        self.assertEqual(row["status"], "sent")
        self.assertAlmostEqual(row["price"], 60.0, places=2)


if __name__ == "__main__":
    unittest.main()
