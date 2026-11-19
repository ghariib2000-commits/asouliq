import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.db.connection import connect
from app.db.migrations import current_version, upgrade


class MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "test.db"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _columns(self, table: str) -> set[str]:
        conn = connect(self.db)
        try:
            return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        finally:
            conn.close()

    def test_fresh_database_gets_full_schema(self) -> None:
        applied = upgrade(self.db)

        self.assertEqual(applied, [1])
        self.assertEqual(current_version(self.db), 1)
        self.assertTrue(
            {"telegram_id", "full_name", "consent", "auto_updates", "interests", "joined_at"}
            <= self._columns("users")
        )

    def test_legacy_database_keeps_users_and_gains_missing_column(self) -> None:
        # قاعدة قديمة بدون عمود consent — سبب الخطأ التاريخي
        legacy = sqlite3.connect(self.db)
        legacy.execute("CREATE TABLE users (telegram_id INTEGER PRIMARY KEY, joined_at TIMESTAMP)")
        legacy.execute(
            "INSERT INTO users (telegram_id, joined_at) VALUES (111, '2026-01-01 10:00:00')"
        )
        legacy.commit()
        legacy.close()

        upgrade(self.db)

        self.assertIn("consent", self._columns("users"))
        conn = connect(self.db)
        try:
            row = conn.execute("SELECT * FROM users WHERE telegram_id = 111").fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row, "المستخدم القديم يجب ألا يُفقد أثناء الترحيل")
        self.assertEqual(row["consent"], 0)
        self.assertEqual(row["interests"], "gold,egx")
        self.assertEqual(row["joined_at"], "2026-01-01 10:00:00")

    def test_upgrade_is_idempotent(self) -> None:
        upgrade(self.db)
        second_run = upgrade(self.db)

        self.assertEqual(second_run, [])
        conn = connect(self.db)
        try:
            versions = [r["version"] for r in conn.execute("SELECT version FROM schema_migrations")]
        finally:
            conn.close()
        self.assertEqual(versions, [1])


if __name__ == "__main__":
    unittest.main()
