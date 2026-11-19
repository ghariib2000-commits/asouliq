"""التحقق من الترحيلات على نسخة من القاعدة قبل لمس القاعدة الحقيقية.

هذه أداة الأمان الأساسية: ننسخ القاعدة، نطبق الترحيل على النسخة،
نتأكد أن عدد المستخدمين لم يتغير، ثم نحذف النسخة المؤقتة.
"""

from __future__ import annotations

import logging
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app import config
from app.db.migrations import current_version, upgrade

logger = logging.getLogger(__name__)


class MigrationCheckError(RuntimeError):
    """فشل التحقق من الترحيل — لا يجوز تشغيله على القاعدة الحقيقية."""


@dataclass(frozen=True)
class MigrationCheck:
    version_before: int
    version_after: int
    applied: list[int]
    users_before: int
    users_after: int
    integrity_ok: bool


def _count_users(path: Path) -> int:
    conn = sqlite3.connect(str(path))
    try:
        return int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def check_migration_on_copy(
    source: str | Path | None = None,
    workdir: str | Path | None = None,
) -> MigrationCheck:
    source_path = Path(source) if source else config.DATABASE_PATH
    if not source_path.exists():
        raise MigrationCheckError(f"قاعدة البيانات غير موجودة: {source_path}")

    with tempfile.TemporaryDirectory(dir=workdir) as tmp:
        copy_path = Path(tmp) / "migration_check.db"

        src = sqlite3.connect(str(source_path), timeout=30.0)
        try:
            dst = sqlite3.connect(str(copy_path))
            try:
                src.backup(dst)
            finally:
                dst.close()  # إغلاق صريح وإلا فشل حذف النسخة المؤقتة على ويندوز
        finally:
            src.close()

        users_before = _count_users(copy_path)
        version_before = _read_version(copy_path)
        applied = upgrade(copy_path)

        conn = sqlite3.connect(str(copy_path))
        try:
            integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0]).lower() == "ok"
        finally:
            conn.close()

        users_after = _count_users(copy_path)
        version_after = current_version(copy_path)

    if not integrity:
        raise MigrationCheckError("النسخة بعد الترحيل تالفة (integrity_check فشل).")
    if users_after != users_before:
        raise MigrationCheckError(
            f"فقدان بيانات محتمل: المستخدمون قبل {users_before} وبعد {users_after}"
        )

    logger.info(
        "فحص الترحيل ناجح على نسخة: الإصدار %s → %s، مستخدمون %d",
        version_before,
        version_after,
        users_after,
    )
    return MigrationCheck(
        version_before=version_before,
        version_after=version_after,
        applied=applied,
        users_before=users_before,
        users_after=users_after,
        integrity_ok=integrity,
    )


def _read_version(path: Path) -> int:
    conn = sqlite3.connect(str(path))
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        return int(row[0] or 0)
    except sqlite3.Error:
        return 0
    finally:
        conn.close()
