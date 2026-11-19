"""التقرير اليومي: المستخدم يختار موعدًا، ويصله فيه ملخص قائمته.

المبادئ:
- التقرير يُبنى من أسعار مخزّنة، ونحدّث أسعار المستحقين فقط باحترام تباعد المزود.
- لا تكرار: last_sent_on يمنع تقريرين في نفس اليوم.
- نافذة سماح محدودة: لو كان البوت متوقفًا وقت الموعد لا نرسل تقريرًا متأخرًا
  ساعات (معلومة قديمة أسوأ من عدمها).
- سعر قديم أو مفقود يظهر بصراحة، ولا نرسل أي رقم غير موجود.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from html import escape
from pathlib import Path

from telegram.error import Forbidden, RetryAfter, TelegramError

from app.clock import now_cairo
from app.db.connection import connect, session
from app.services import alerts, prices, watchlist

logger = logging.getLogger(__name__)

GRACE_MINUTES = 120
DEFAULT_HOUR = 9
DEFAULT_MINUTE = 0

WEEKDAYS_AR = ("الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد")

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def parse_time(text: str) -> tuple[int, int] | None:
    """يقبل 09:00 أو 9:5 أو 21.30 أو 9. يرجع (ساعة، دقيقة) أو None."""
    raw = (text or "").strip().translate(_ARABIC_DIGITS).replace(".", ":")
    if not raw:
        return None
    if ":" in raw:
        hours_text, _, minutes_text = raw.partition(":")
        if not hours_text.isdigit() or not minutes_text.isdigit():
            return None
        hour, minute = int(hours_text), int(minutes_text)
    else:
        if not raw.isdigit():
            return None
        hour, minute = int(raw), 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def format_time(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def set_schedule(
    telegram_id: int, hour: int, minute: int, db_path: str | Path | None = None
) -> None:
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("موعد غير صالح")
    with session(db_path) as conn:
        conn.execute(
            """
            INSERT INTO report_settings (telegram_id, enabled, hour, minute)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                enabled = 1,
                hour    = excluded.hour,
                minute  = excluded.minute,
                updated_at = datetime('now')
            """,
            (telegram_id, hour, minute),
        )


def enable(telegram_id: int, db_path: str | Path | None = None) -> dict:
    """يفعّل التقرير بالموعد المحفوظ، أو 09:00 افتراضيًا."""
    current = get_settings(telegram_id, db_path)
    hour, minute = (current["hour"], current["minute"]) if current else (DEFAULT_HOUR, DEFAULT_MINUTE)
    set_schedule(telegram_id, hour, minute, db_path)
    return get_settings(telegram_id, db_path) or {}


def disable(telegram_id: int, db_path: str | Path | None = None) -> None:
    with session(db_path) as conn:
        conn.execute(
            """
            INSERT INTO report_settings (telegram_id, enabled) VALUES (?, 0)
            ON CONFLICT(telegram_id) DO UPDATE SET
                enabled = 0,
                updated_at = datetime('now')
            """,
            (telegram_id,),
        )


def get_settings(telegram_id: int, db_path: str | Path | None = None) -> dict | None:
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT telegram_id, enabled, hour, minute, last_sent_on "
            "FROM report_settings WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def due_reports(
    now: datetime | None = None, db_path: str | Path | None = None
) -> list[dict]:
    """التقارير المستحقة الآن: الموعد مرّ، داخل نافذة السماح، ولم يُرسل اليوم."""
    moment = now or now_cairo()
    today = moment.date().isoformat()

    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT telegram_id, hour, minute, last_sent_on "
            "FROM report_settings WHERE enabled = 1"
        ).fetchall()
    finally:
        conn.close()

    due: list[dict] = []
    for row in rows:
        if row["last_sent_on"] == today:
            continue
        scheduled = moment.replace(hour=row["hour"], minute=row["minute"], second=0, microsecond=0)
        late_minutes = (moment - scheduled).total_seconds() / 60
        if late_minutes < 0 or late_minutes > GRACE_MINUTES:
            continue
        due.append(dict(row))
    return due


def mark_sent(telegram_id: int, day: str, db_path: str | Path | None = None) -> None:
    with session(db_path) as conn:
        conn.execute(
            "UPDATE report_settings SET last_sent_on = ? WHERE telegram_id = ?",
            (day, telegram_id),
        )


def _change_text(price: float, prev_price: float | None) -> str:
    if prev_price is None or prev_price <= 0:
        return ""
    pct = (price - prev_price) / prev_price * 100
    if abs(pct) < 0.005:
        return " — بدون تغير"
    arrow = "▲" if pct > 0 else "▼"
    return f" {arrow} {pct:+.2f}%"


def build_report(
    telegram_id: int,
    db_path: str | Path | None = None,
    moment: datetime | None = None,
) -> str | None:
    """نص التقرير، أو None لو قائمة المستخدم فاضية (لا نرسل رسالة فارغة)."""
    items = watchlist.items(telegram_id, db_path)
    if not items:
        return None

    current = moment or now_cairo()
    day = current.date().isoformat()
    weekday = WEEKDAYS_AR[current.weekday()]

    lines = [
        f"📬 <b>تقريرك اليومي — {weekday} {day}</b>",
        "<i>بتوقيت القاهرة</i>",
        "",
        f"⭐ <b>أصولك ({len(items)})</b>",
    ]

    stale: list[str] = []
    for item in items:
        name = escape(str(item["name_ar"]))
        code = escape(str(item["code"]))
        if item["price"] is None:
            lines.append(f"• {name} ({code}): <i>بدون سعر محدث</i>")
            continue
        change = _change_text(float(item["price"]), item["prev_price"])
        lines.append(
            f"• {name} ({code}): <b>{float(item['price']):,.2f}</b> "
            f"{escape(str(item['unit']))}{change}"
        )
        if item["stale"]:
            stale.append(code)

    if stale:
        lines.append("")
        lines.append(f"⚠️ أسعار قديمة (تحتاج تحديثًا): {', '.join(stale)}")

    rules = alerts.count_rules(telegram_id, db_path)
    if rules:
        lines.append(f"🔔 تنبيهات نشطة: {rules}")

    lines.append("")
    lines.append("<i>ملخص آلي وليس توصية استثمارية.</i>")
    lines.append("<i>لتغيير الموعد: /report HH:MM — للإيقاف: /report off</i>")
    return "\n".join(lines)


def refresh_report_prices(telegram_ids: list[int], db_path: str | Path | None = None) -> list[str]:
    """يحدّث أسعار أصول المستحقين فقط، مرة لكل مزود وباحترام التباعد."""
    keys: set[str] = set()
    for telegram_id in telegram_ids:
        for item in watchlist.items(telegram_id, db_path):
            if item.get("provider_key"):
                keys.add(str(item["provider_key"]))

    refreshed: list[str] = []
    for key in sorted(keys):
        result = prices.refresh_if_due(key, db_path)
        if result is not None and result.ok:
            refreshed.append(key)
    return refreshed


async def send_due_reports(application, db_path: str | Path | None = None) -> int:
    """يرسل التقارير المستحقة. يرجع عدد الرسائل المرسلة بنجاح."""
    due = await asyncio.to_thread(due_reports, None, db_path)
    if not due:
        return 0

    try:
        await asyncio.to_thread(
            refresh_report_prices, [row["telegram_id"] for row in due], db_path
        )
    except Exception:  # noqa: BLE001 - فشل مصدر لا يجب أن يمنع التقرير
        logger.exception("فشل تحديث أسعار التقارير")

    today = now_cairo().date().isoformat()
    sent = 0

    for row in due:
        telegram_id = row["telegram_id"]
        text = await asyncio.to_thread(build_report, telegram_id, db_path)
        if text:
            try:
                await application.bot.send_message(
                    chat_id=telegram_id, text=text, parse_mode="HTML"
                )
            except Forbidden:
                logger.info("المستخدم %s أوقف البوت — تم إيقاف تقريره اليومي", telegram_id)
                await asyncio.to_thread(disable, telegram_id, db_path)
                continue
            except RetryAfter as exc:
                logger.warning("Telegram rate limit في التقرير اليومي: %s", exc)
                continue
            except TelegramError as exc:
                logger.warning("فشل إرسال التقرير اليومي: %s", exc)
                continue
            sent += 1

        # نسجل اليوم حتى لا يتكرر التقرير، حتى لو كانت القائمة فاضية.
        await asyncio.to_thread(mark_sent, telegram_id, today, db_path)

    if sent:
        logger.info("تقارير يومية أُرسلت: %d", sent)
    return sent
