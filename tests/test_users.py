import tempfile
import unittest
from pathlib import Path

from app.db.migrations import upgrade
from app.services import users


class UserServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "test.db"
        upgrade(self.db)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_register_consent_creates_user(self) -> None:
        users.register_consent(1001, "أحمد", self.db)

        row = users.get_user(1001, self.db)
        self.assertIsNotNone(row)
        self.assertEqual(row["consent"], 1)
        self.assertEqual(row["interests"], "gold,egx")
        self.assertTrue(users.has_consent(1001, self.db))

    def test_register_twice_preserves_existing_preferences(self) -> None:
        users.register_consent(1002, "سارة", self.db)
        users.update_preference(1002, "interests", "gold", self.db)

        users.register_consent(1002, "سارة", self.db)

        self.assertEqual(users.interests_of(1002, self.db), ["gold"])
        row = users.get_user(1002, self.db)
        self.assertEqual(row["consent"], 1)

    def test_users_are_isolated(self) -> None:
        users.register_consent(2001, "A", self.db)
        users.register_consent(2002, "B", self.db)

        users.toggle_interest(2001, "egx", self.db)

        self.assertEqual(users.interests_of(2001, self.db), ["gold"])
        self.assertEqual(users.interests_of(2002, self.db), ["gold", "egx"])

    def test_toggle_interest_adds_then_removes(self) -> None:
        users.register_consent(3001, "C", self.db)

        added = users.toggle_interest(3001, "usd", self.db)
        removed = users.toggle_interest(3001, "usd", self.db)

        self.assertIn("usd", added)
        self.assertNotIn("usd", removed)

    def test_toggle_auto_updates_flips_value(self) -> None:
        users.register_consent(4001, "D", self.db)

        self.assertEqual(users.toggle_auto_updates(4001, self.db), 1)
        self.assertEqual(users.toggle_auto_updates(4001, self.db), 0)

    def test_unknown_preference_field_is_rejected(self) -> None:
        users.register_consent(5001, "E", self.db)

        with self.assertRaises(ValueError):
            users.update_preference(5001, "consent; DROP TABLE users", 1, self.db)


if __name__ == "__main__":
    unittest.main()
