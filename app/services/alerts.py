"""محرك التنبيهات: قواعد المستخدم، تقييمها مقابل أحدث سعر، ومنع التكرار.

المبادئ:
- قاعدة التنبيه ملك مستخدم واحد ولا يمكن لغيره قراءتها أو حذفها.
- التقييم يتم على أحدث سعر مخزَّن (latest_prices) بعد جلبه من المصدر.
- لا ننبّه على سعر قديم (stale) حتى لا نرسل معلومة مضللة.
- منع التكرار عبر cooldown لكل قاعدة + سجل إرسال (notification_log).
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from app import config
from app.clock import now_cairo
from app.db.connection import connect, session
from app.services import prices

logger = logging.getLogger(__name__)

RULE_ABOVE = "price_above"
RULE_BELOW = "price_below"
RULE_PCT_UP = "pct_change_up"
RULE_PCT_DOWN = "pct_change_down"

RULE_TYPES: tuple[str, ...] = (RULE_ABOVE, RULE_BELOW, RULE_PCT_UP, RULE_PCT_DOWN)

RULE_LABELS: dict[str, str] = {
    RULE_ABOVE: "السعر يصل أو يتجاوز",
    RULE_BELOW: "السعر ينزل إلى أو تحت",
    RULE_PCT_UP: "ارتفاع بنسبة",
    RULE_PCT_DOWN: "انخفاض بنسبة",
}

# مرادفات يقبلها المستخدم في الأمر
TYPE_ALIASES: dict[str, str] = {
    "above": RULE_ABOVE,
    "فوق": RULE_ABOVE,
    "اعلى": RULE_ABOVE,
    "أعلى": RULE_ABOVE,
    "below": RULE_BELOW,
    "تحت": RULE_BELOW,
    "اقل": RULE_BELOW,
    "أقل": RULE_BELOW,
    "up": RULE_PCT_UP,
    "ارتفاع": RULE_PCT_UP,
    "down": RULE_PCT_DOWN,
    "انخفاض": RULE_PCT_DOWN,
}

STATUS_PENDING = "pending"
STATUS_SENT = "sent"
STATUS_FAILED = "failed"


def normalize_rule_type(value: str) -> str | None:
    return TYPE_ALIASES.get((value or "").strip().lower(), TYPE_ALIASES.get((value or "").strip()))


def add_rule(
    telegram_id: int,
    asset_code: str,
    rule_type: str,
    threshold: float,
    db_path: str | Path | None = None,
) -> int | None:
    """ينشئ قاعدة تنبيه. يرجع رقمها، أو None لو غير صالحة/مكررة/تجاوزت الحد."""
    if rule_type not in RULE_TYPES:
        return None
    if rule_type in (RULE_PCT_UP, RULE_PCT_DOWN) and threshold <= 0:
        return None
    if rule_type in (RULE_ABOVE, RULE_BELOW) and threshold <= 0:
        return None

    conn = connect(db_path)
    try:
        asset = conn.execute(
            "SELECT code FROM assets WHERE code = ? AND is_active = 1", (asset_code.upper(),)
        ).fetchone()
        if asset is None:
            return None
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM alert_rules WHERE telegram_id = ? AND is_active = 1",
            (telegram_id,),
        ).fetchone()["c"]
        if total >= config.ALERT_MAX_RULES:
            return None
    finally:
        conn.close()

    try:
        with session(db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO alert_rules (telegram_id, asset_code, rule_type, threshold)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(telegram_id, asset_code, rule_type, threshold) DO NOTHING
                """,
                (telegram_id, asset_code.upper(), rule_type, round(float(threshold), 2)),
            )
            if cursor.rowcount == 0:
                return None
            return int(cursor.lastrowid)
    except sqlite3.IntegrityError:
        logger.warning("تعذر إنشاء تنبيه لمستخدم %s على %s", telegram_id, asset_code)
        return None


def remove_rule(telegram_id: int, rule_id: int, db_path: str | Path | None = None) -> bool:
    with session(db_path) as conn:
        cursor = conn.execute(
            "DELETE FROM alert_rules WHERE id = ? AND telegram_id = ?", (rule_id, telegram_id)
        )
        return cursor.rowcount > 0


def list_rules(telegram_id: int, db_path: str | Path | None = None) -> list[dict]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT r.id, r.asset_code, r.rule_type, r.threshold, r.is_active,
                   r.last_triggered_at, a.name_ar, a.unit
            FROM alert_rules r
            JOIN assets a ON a.code = r.asset_code
            WHERE r.telegram_id = ?
            ORDER BY r.id
            """,
            (telegram_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def count_rules(telegram_id: int, db_path: str | Path | None = None) -> int:
    conn = connect(db_path)
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM alert_rules WHERE telegram_id = ? AND is_active = 1",
                (telegram_id,),
            ).fetchone()["c"]
        )
    finally:
        conn.close()


def assets_with_rules(db_path: str | Path | None = None) -> list[str]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT DISTINCT asset_code FROM alert_rules WHERE is_active = 1 ORDER BY asset_code"
        ).fetchall()
        return [row["asset_code"] for row in rows]
    finally:
        conn.close()


def provider_keys_for(asset_codes: list[str], db_path: str | Path | None = None) -> set[str]:
    if not asset_codes:
        return set()
    placeholders = ",".join("?" for _ in asset_codes)
    conn = connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT DISTINCT provider_key FROM assets WHERE code IN ({placeholders})",
            asset_codes,
        ).fetchall()
        return {row["provider_key"] for row in rows if row["provider_key"]}
    finally:
        conn.close()


def _condition_met(
    rule_type: str, threshold: float, price: float, prev_price: float | None
) -> tuple[bool, float | None]:
    """يرجع (تحقق الشرط، النسبة الفعلية إن وُجدت)."""
    if rule_type == RULE_ABOVE:
        return price >= threshold, None
    if rule_type == RULE_BELOW:
        return price <= threshold, None
    if prev_price is None or prev_price <= 0:
        return False, None

    change_pct = (price - prev_price) / prev_price * 100
    if rule_type == RULE_PCT_UP:
        return change_pct >= threshold, change_pct
    if rule_type == RULE_PCT_DOWN:
        return change_pct <= -abs(threshold), change_pct
    return False, change_pct


def _within_cooldown(last_triggered_at: str | None, now: datetime) -> bool:
    if not last_triggered_at:
        return False
    try:
        last = datetime.fromisoformat(last_triggered_at)
    except ValueError:
        return False
    reference = now if (last.tzinfo is None) == (now.tzinfo is None) else now.replace(tzinfo=None)
    return (reference - last) < timedelta(minutes=config.ALERT_COOLDOWN_MINUTES)


def due_alerts(
    db_path: str | Path | None = None, now: datetime | None = None
) -> list[dict]:
    """كل التنبيهات المستحقة الآن، مع بيانتها الجاهزة للإرسال."""
    moment = now or now_cairo()
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT r.id, r.telegram_id, r.asset_code, r.rule_type, r.threshold,
                   r.last_triggered_at, a.name_ar, a.unit,
                   p.price, p.prev_price, p.fetched_at, p.source
            FROM alert_rules r
            JOIN assets a ON a.code = r.asset_code
            JOIN latest_prices p ON p.asset_code = r.asset_code
            WHERE r.is_active = 1
            """
        ).fetchall()
    finally:
        conn.close()

    due: list[dict] = []
    for row in rows:
        if row["price"] is None:
            continue
        price_row = {"fetched_at": row["fetched_at"]}
        if prices.is_stale(price_row):
            continue  # لا ننبّه على سعر قديم
        if _within_cooldown(row["last_triggered_at"], moment):
            continue

        met, actual_pct = _condition_met(
            row["rule_type"], row["threshold"], float(row["price"]), row["prev_price"]
        )
        if not met:
            continue

        due.append(
            {
                "rule_id": row["id"],
                "telegram_id": row["telegram_id"],
                "asset_code": row["asset_code"],
                "asset_name": row["name_ar"],
                "unit": row["unit"],
                "rule_type": row["rule_type"],
                "threshold": row["threshold"],
                "price": float(row["price"]),
                "prev_price": row["prev_price"],
                "change_pct": actual_pct,
                "source": row["source"],
                "fetched_at": row["fetched_at"],
            }
        )
    return due


def log_notification(
    alert: dict,
    status: str,
    message: str,
    error: str | None = None,
    db_path: str | Path | None = None,
) -> int:
    with session(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO notification_log
                (rule_id, telegram_id, asset_code, message, price, status, error)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert["rule_id"],
                alert["telegram_id"],
                alert["asset_code"],
                message,
                alert["price"],
                status,
                error,
            ),
        )
        return int(cursor.lastrowid)


def mark_triggered(
    rule_id: int, status: str, db_path: str | Path | None = None
) -> None:
    """يسجل وقت الإرسال على القاعدة (أساس منع التكرار)."""
    with session(db_path) as conn:
        conn.execute(
            "UPDATE alert_rules SET last_triggered_at = ? WHERE id = ?",
            (now_cairo().isoformat(), rule_id),
        )
        if status == STATUS_FAILED:
            conn.execute(
                "UPDATE alert_rules SET last_triggered_at = NULL WHERE id = ?", (rule_id,)
            )
