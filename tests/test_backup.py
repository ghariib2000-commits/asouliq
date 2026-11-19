import tempfile
import unittest
from pathlib import Path

from app.db.backup import BackupError, backup_database, list_backups
from app.db.migrations import upgrade
from app.db.upgrade_check import MigrationCheckError, check_migration_on_copy
from app.services import users


class BackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = self.root / "live.db"
        self.backups = self.root / "backups"
        upgrade(self.db)
        users.register_consent(9001, "مستخدم قديم", self.db)
        users.register_consent(9002, "مستخدمة قديمة", self.db)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_backup_is_valid_and_keeps_users(self) -> None:
        info = backup_database(self.db, self.backups)

        self.assertTrue(info.path.exists())
        self.assertTrue(info.integrity_ok)
        self.assertEqual(info.users_count, 2)
        self.assertEqual(len(list_backups(self.backups)), 1)

    def test_missing_database_raises(self) -> None:
        with self.assertRaises(BackupError):
            backup_database(self.root / "missing.db", self.backups)

    def test_restore_from_backup_keeps_data(self) -> None:
        info = backup_database(self.db, self.backups)
        self.db.unlink()  # محاكاة فقدان القاعدة

        restored = self.root / "restored.db"
        import shutil

        shutil.copy2(info.path, restored)

        self.assertEqual(users.interests_of(9001, restored), ["gold", "egx"])
        self.assertTrue(users.has_consent(9002, restored))


class MigrationCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = self.root / "live.db"
        upgrade(self.db)
        users.register_consent(7001, "قديم", self.db)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_migration_on_copy_keeps_users_and_does_not_touch_original(self) -> None:
        result = check_migration_on_copy(self.db, self.root)

        self.assertTrue(result.integrity_ok)
        self.assertEqual(result.users_before, 1)
        self.assertEqual(result.users_after, 1)
        self.assertEqual(result.applied, [])  # القاعدة محدثة بالفعل

    def test_missing_database_raises(self) -> None:
        with self.assertRaises(MigrationCheckError):
            check_migration_on_copy(self.root / "missing.db", self.root)


if __name__ == "__main__":
    unittest.main()
