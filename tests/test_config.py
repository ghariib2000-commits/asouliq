import unittest
from pathlib import Path
from unittest.mock import patch

from app import config


class OwnerCheckTests(unittest.TestCase):
    def test_owner_matches_only_same_id(self) -> None:
        with patch.object(config, "OWNER_TELEGRAM_ID", 555):
            self.assertTrue(config.is_owner(555))
            self.assertFalse(config.is_owner(556))
            self.assertFalse(config.is_owner(None))

    def test_no_owner_configured_denies_everyone(self) -> None:
        with patch.object(config, "OWNER_TELEGRAM_ID", None):
            self.assertFalse(config.is_owner(555))


class EphemeralStorageTests(unittest.TestCase):
    def test_database_inside_project_is_flagged(self) -> None:
        with patch.object(config, "DATABASE_PATH", config.BASE_DIR / "asouliq.db"):
            self.assertTrue(config.database_is_ephemeral())

    def test_database_on_mount_path_is_not_flagged(self) -> None:
        with patch.object(config, "DATABASE_PATH", Path("/data/asouliq.db")):
            self.assertFalse(config.database_is_ephemeral())


if __name__ == "__main__":
    unittest.main()
