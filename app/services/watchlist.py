"""قائمة متابعة شخصية لكل مستخدم — معزولة تمامًا بين المستخدمين."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from app.db.connection import connect, session
from app.services import prices

logger = logging.getLogger(__name__)

MAX_ITEMS = 30


def add(telegram_id: int, asset_code: str, db_path: str | Path | None = None) -> bool:
    """يضيف أصلًا. يرجع False لو الأصل غير موجود أو القائمة ممتلئة."""
    code = asset_code.upper()
    conn = connect(db_path)
    try:
        asset = conn.execute(
            "SELECT code FROM assets WHERE code = ? AND is_active = 1", (code,)
        ).fetchone()
        if asset is None:
            return False
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM watchlist WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()["c"]
        if count >= MAX_ITEMS:
            return False
    finally:
        conn.close()

    try:
        with session(db_path) as conn:
            conn.execute(
                "INSERT INTO watchlist (telegram_id, asset_code) VALUES (?, ?) "
                "ON CONFLICT(telegram_id, asset_code) DO NOTHING",
                (telegram_id, code),
            )
    except sqlite3.IntegrityError:
        # المستخدم غير مسجل أو الأصل اختفى بين الفحص والإدخال
        logger.warning("تعذر إضافة %s لمستخدم %s", code, telegram_id)
        return False
    return True


def remove(telegram_id: int, asset_code: str, db_path: str | Path | None = None) -> bool:
    with session(db_path) as conn:
        cursor = conn.execute(
            "DELETE FROM watchlist WHERE telegram_id = ? AND asset_code = ?",
            (telegram_id, asset_code.upper()),
        )
        return cursor.rowcount > 0


def contains(telegram_id: int, asset_code: str, db_path: str | Path | None = None) -> bool:
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM watchlist WHERE telegram_id = ? AND asset_code = ?",
            (telegram_id, asset_code.upper()),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def count(telegram_id: int, db_path: str | Path | None = None) -> int:
    conn = connect(db_path)
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM watchlist WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()["c"]
        )
    finally:
        conn.close()


def items(telegram_id: int, db_path: str | Path | None = None) -> list[dict]:
    """عناصر القائمة مع أحدث سعر وحالة حداثته."""
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT a.code, a.name_ar, a.name_en, a.kind, a.quote_unit, a.unit,
                   a.provider_key,
                   p.price, p.prev_price, p.fetched_at, p.source
            FROM watchlist w
            JOIN assets a ON a.code = w.asset_code
            LEFT JOIN latest_prices p ON p.asset_code = w.asset_code
            WHERE w.telegram_id = ?
            ORDER BY w.created_at, a.code
            """,
            (telegram_id,),
        ).fetchall()
    finally:
        conn.close()

    result = []
    for row in rows:
        price_row = row if row["price"] is not None else None
        result.append(
            {
                "code": row["code"],
                "name_ar": row["name_ar"],
                "name_en": row["name_en"],
                "kind": row["kind"],
                "quote_unit": row["quote_unit"],
                "unit": row["unit"],
                "provider_key": row["provider_key"],
                "price": row["price"],
                "prev_price": row["prev_price"],
                "fetched_at": row["fetched_at"],
                "source": row["source"],
                "stale": prices.is_stale(price_row) if price_row is not None else True,
            }
        )
    return result
