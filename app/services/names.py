"""تطبيق الأسماء العربية على الأصول المسجلة (للبيانات القديمة)."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from app.db.connection import session
from app.egx_names_ar import EGX_NAMES_AR

logger = logging.getLogger(__name__)


def apply_arabic_names(db_path: str | Path | None = None) -> int:
    """يحدّث name_ar للأسهم المعروفة بالترجمة اليدوية. يرجع عدد الصفوف المحدثة."""
    if not EGX_NAMES_AR:
        return 0

    updated = 0
    try:
        with session(db_path) as conn:
            for code, name_ar in EGX_NAMES_AR.items():
                cursor = conn.execute(
                    "UPDATE assets SET name_ar = ? WHERE code = ? AND name_ar != ?",
                    (name_ar, code, name_ar),
                )
                updated += cursor.rowcount
    except sqlite3.OperationalError as exc:
        # قاعدة لم تُهيأ بعد: لا شيء نترجمه.
        logger.warning("تعذر تطبيق الأسماء العربية (قاعدة غير جاهزة؟): %s", exc)
        return 0

    if updated:
        logger.info("تم تحديث %d اسمًا عربيًا", updated)
    return updated
