"""تخزين وقراءة أحدث الأسعار.

السعر يُجلب مرة واحدة لكل مزود (market.get_prices)، ثم تُحفظ أسعاره
هنا لتُستخدم في القوائم والتنبيهات بدون إعادة ضرب المصدر.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from app import config
from app.clock import now_cairo
from app.db.connection import connect, session
from app.providers.base import ProviderResult
from app.services import market

logger = logging.getLogger(__name__)


def save_result(result: ProviderResult, db_path: str | Path | None = None) -> int:
    """يحفظ أسعار نتيجة ناجحة. يتخطى أي أصل غير مسجل في assets."""
    if not result.ok or not result.quotes:
        return 0

    source = ", ".join(result.sources) or result.provider_key
    fetched_at = result.fetched_at.isoformat()
    saved = 0

    with session(db_path) as conn:
        known = {row["code"] for row in conn.execute("SELECT code FROM assets")}
        for quote in result.quotes:
            if quote.code not in known:
                logger.warning("سعر لأصل غير مسجل تم تجاوزه: %s", quote.code)
                continue

            # نحفظ السعر السابق الصالح لتنبيهات النسبة المئوية.
            previous = conn.execute(
                "SELECT price, prev_price, prev_fetched_at FROM latest_prices WHERE asset_code = ?",
                (quote.code,),
            ).fetchone()
            if previous is None:
                prev_price, prev_fetched_at = None, None
            elif float(previous["price"]) == float(quote.value):
                prev_price, prev_fetched_at = previous["prev_price"], previous["prev_fetched_at"]
            else:
                prev_price, prev_fetched_at = previous["price"], fetched_at

            conn.execute(
                """
                INSERT INTO latest_prices
                    (asset_code, price, currency, source, updated_at, fetched_at,
                     provider_key, prev_price, prev_fetched_at)
                VALUES (?, ?, 'EGP', ?, ?, ?, ?, ?, ?)
                ON CONFLICT(asset_code) DO UPDATE SET
                    price         = excluded.price,
                    source        = excluded.source,
                    updated_at    = excluded.updated_at,
                    fetched_at    = excluded.fetched_at,
                    provider_key  = excluded.provider_key,
                    prev_price    = excluded.prev_price,
                    prev_fetched_at= excluded.prev_fetched_at
                """,
                (
                    quote.code,
                    quote.value,
                    source,
                    quote.source_updated_at or fetched_at,
                    fetched_at,
                    result.provider_key,
                    prev_price,
                    prev_fetched_at,
                ),
            )
            saved += 1
    return saved


def refresh(service_key: str, db_path: str | Path | None = None, force: bool = False) -> ProviderResult:
    """يجلب أسعار مزود ثم يحفظها، ويرجع النتيجة كما هي."""
    result = market.get_prices(service_key, force=force)
    if result.ok:
        saved = save_result(result, db_path)
        logger.info("تم تخزين %d سعر من %s", saved, service_key)
    return result


def latest(asset_code: str, db_path: str | Path | None = None):
    conn = connect(db_path)
    try:
        return conn.execute(
            "SELECT asset_code, price, currency, source, updated_at, fetched_at, provider_key "
            "FROM latest_prices WHERE asset_code = ?",
            (asset_code,),
        ).fetchone()
    finally:
        conn.close()


def latest_for(codes: list[str], db_path: str | Path | None = None) -> dict[str, object]:
    if not codes:
        return {}
    placeholders = ",".join("?" for _ in codes)
    conn = connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT * FROM latest_prices WHERE asset_code IN ({placeholders})", codes
        ).fetchall()
        return {row["asset_code"]: row for row in rows}
    finally:
        conn.close()


def newest_fetched_at(provider_key: str, db_path: str | Path | None = None):
    """أحدث وقت جلب لأي أصل يتبع هذا المزود (None لو لا يوجد)."""
    conn = connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT MAX(p.fetched_at) AS newest
            FROM latest_prices p
            JOIN assets a ON a.code = p.asset_code
            WHERE a.provider_key = ?
            """,
            (provider_key,),
        ).fetchone()
        return row["newest"] if row else None
    finally:
        conn.close()


def seconds_since_fetch(value, now=None) -> float | None:
    try:
        fetched = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=config_zone())
    reference = now or datetime.now(fetched.tzinfo)
    return (reference - fetched).total_seconds()


def config_zone():
    return now_cairo().tzinfo


def is_stale(row, max_minutes: int | None = None) -> bool:
    """هل السعر أقدم من الحد المسموح؟ (افتراضيًا من الإعدادات)"""
    limit = max_minutes if max_minutes is not None else config.PRICE_STALE_MINUTES
    try:
        fetched = datetime.fromisoformat(str(row["fetched_at"]))
    except (TypeError, ValueError):
        return True
    reference = datetime.now(fetched.tzinfo) if fetched.tzinfo else datetime.now()
    return (reference - fetched).total_seconds() > limit * 60
