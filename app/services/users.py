"""عمليات المستخدمين.

كل دالة تقبل db_path اختياريًا حتى تعمل الاختبارات على قاعدة مؤقتة
بدون لمس قاعدة التطوير أو الإنتاج.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from app.db.connection import connect, session

logger = logging.getLogger(__name__)

DEFAULT_INTERESTS = "gold,egx"
ALLOWED_PREFERENCE_FIELDS = frozenset({"auto_updates", "interests"})


def get_user(telegram_id: int, db_path: str | Path | None = None) -> sqlite3.Row | None:
    conn = connect(db_path)
    try:
        return conn.execute(
            "SELECT telegram_id, full_name, consent, auto_updates, interests, joined_at "
            "FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
    finally:
        conn.close()


def has_consent(telegram_id: int, db_path: str | Path | None = None) -> bool:
    user = get_user(telegram_id, db_path)
    return bool(user and user["consent"] == 1)


def register_consent(
    telegram_id: int, full_name: str, db_path: str | Path | None = None
) -> None:
    """يسجل المستخدم أو يحدّث موافقته دون المساس بتفضيلاته الموجودة."""
    with session(db_path) as conn:
        conn.execute(
            """
            INSERT INTO users (telegram_id, full_name, consent, interests)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                consent   = 1,
                full_name = COALESCE(excluded.full_name, users.full_name)
            """,
            (telegram_id, full_name, DEFAULT_INTERESTS),
        )


def update_preference(
    telegram_id: int, field: str, value: object, db_path: str | Path | None = None
) -> None:
    """تحديث تفضيل واحد فقط من قائمة مسموحة (منع SQL Injection)."""
    if field not in ALLOWED_PREFERENCE_FIELDS:
        raise ValueError(f"حقل تفضيل غير مسموح: {field}")
    with session(db_path) as conn:
        conn.execute(
            f"UPDATE users SET {field} = ? WHERE telegram_id = ?",
            (value, telegram_id),
        )


def interests_of(telegram_id: int, db_path: str | Path | None = None) -> list[str]:
    user = get_user(telegram_id, db_path)
    if not user or not user["interests"]:
        return []
    return [item for item in str(user["interests"]).split(",") if item]


def toggle_interest(
    telegram_id: int, service_key: str, db_path: str | Path | None = None
) -> list[str]:
    current = interests_of(telegram_id, db_path)
    if service_key in current:
        current.remove(service_key)
    else:
        current.append(service_key)
    update_preference(telegram_id, "interests", ",".join(current), db_path)
    return current


def toggle_auto_updates(telegram_id: int, db_path: str | Path | None = None) -> int:
    user = get_user(telegram_id, db_path)
    new_value = 0 if (user and user["auto_updates"] == 1) else 1
    update_preference(telegram_id, "auto_updates", new_value, db_path)
    return new_value
