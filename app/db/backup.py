"""نسخ احتياطي آمن لقاعدة SQLite مع تحقق كامل.

يُستخدم sqlite3 Backup API (وليس نسخ الملف) لأن النسخ المباشر لملف
قاعدة تعمل بوضع WAL قد ينتج ملفًا ناقصًا أو تالفًا.

كل نسخة تُتحقق فور إنشائها:
- PRAGMA integrity_check يجب أن يرجع ok
- عدد المستخدمين في النسخة يجب أن يطابق الأصل
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app import config
from app.clock import now_cairo

logger = logging.getLogger(__name__)

DEFAULT_BACKUP_DIR = config.BASE_DIR / "backups"


class BackupError(RuntimeError):
    """فشل النسخ الاحتياطي أو التحقق منه."""


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    users_count: int
    integrity_ok: bool
    size_bytes: int
    created_at: str


def _users_count(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
        return int(row["c"])
    except sqlite3.Error:
        return 0


def _integrity_ok(conn: sqlite3.Connection) -> bool:
    row = conn.execute("PRAGMA integrity_check").fetchone()
    return bool(row) and str(row[0]).lower() == "ok"


def backup_database(
    source: str | Path | None = None,
    backup_dir: str | Path | None = None,
) -> BackupInfo:
    """ينشئ نسخة احتياطية ويتحقق منها، أو يرفع BackupError."""
    source_path = Path(source) if source else config.DATABASE_PATH
    if not source_path.exists():
        raise BackupError(f"قاعدة البيانات غير موجودة: {source_path}")

    target_dir = Path(backup_dir) if backup_dir else DEFAULT_BACKUP_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = now_cairo().strftime("%Y%m%d_%H%M%S")
    target_path = target_dir / f"{source_path.stem}_{stamp}.db"

    source_conn = sqlite3.connect(str(source_path), timeout=30.0)
    source_conn.row_factory = sqlite3.Row
    try:
        users_before = _users_count(source_conn)
        target_conn = sqlite3.connect(str(target_path))
        try:
            source_conn.backup(target_conn)
        finally:
            # لازم إغلاق صريح: Context Manager على الاتصال يcommit ولا يغلق،
            # والاتصال المفتوح يمنع حذف/نقل الملف على ويندوز.
            target_conn.close()
    finally:
        source_conn.close()

    check_conn = sqlite3.connect(str(target_path))
    check_conn.row_factory = sqlite3.Row
    try:
        integrity = _integrity_ok(check_conn)
        users_after = _users_count(check_conn)
    finally:
        check_conn.close()

    if not integrity:
        raise BackupError(f"النسخة الاحتياطية تالفة: {target_path}")
    if users_after != users_before:
        raise BackupError(
            f"عدد المستخدمين غير مطابق: الأصل {users_before} والنسخة {users_after}"
        )

    info = BackupInfo(
        path=target_path,
        users_count=users_after,
        integrity_ok=integrity,
        size_bytes=target_path.stat().st_size,
        created_at=stamp,
    )
    logger.info("نسخة احتياطية سليمة: %s (%d مستخدم)", info.path, info.users_count)
    return info


def list_backups(backup_dir: str | Path | None = None) -> list[Path]:
    directory = Path(backup_dir) if backup_dir else DEFAULT_BACKUP_DIR
    if not directory.exists():
        return []
    return sorted(directory.glob("*.db"), reverse=True)
