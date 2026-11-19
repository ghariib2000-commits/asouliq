"""تشغيل التنبيهات: دورة دورية داخل نفس عملية البوت.

لا نشغّل عملية ثانية ولا Polling إضافي — الدورة عبارة عن Task داخل
الـEvent Loop نفسه، فلا يحدث Conflict مع getUpdates.

كل دورة:
    1. تحدد الأصول التي لها تنبيهات.
    2. تجلب أسعار مزوديها مرة واحدة (لا مرة لكل مستخدم).
    3. تقيّم القواعد وتُرسل المستحق فقط.
    4. تسجل نتيجة كل إرسال في notification_log.
    5. ترسل التقارير اليومية المستحقة (app/services/reports.py).
"""

from __future__ import annotations

import asyncio
import logging

from telegram.error import Forbidden, RetryAfter, TelegramError

from app import config
from app.clock import format_cairo
from app.services import alerts, prices, reports

logger = logging.getLogger(__name__)

_background_task: asyncio.Task | None = None


def format_alert(alert: dict) -> str:
    """رسالة التنبيه كما تصل للمستخدم، مع المصدر والوقت."""
    header = f"🔔 <b>تنبيه: {alert['asset_name']}</b> ({alert['asset_code']})"
    price_text = f"السعر الآن: <b>{alert['price']:,.2f}</b> {alert['unit']}"

    if alert["rule_type"] == alerts.RULE_ABOVE:
        reason = f"وصل إلى الحد الذي حددته: {alert['threshold']:,.2f}"
    elif alert["rule_type"] == alerts.RULE_BELOW:
        reason = f"نزل إلى الحد الذي حددته: {alert['threshold']:,.2f}"
    elif alert["rule_type"] == alerts.RULE_PCT_UP:
        change = alert.get("change_pct")
        change_text = f" ({change:+.2f}%)" if change is not None else ""
        reason = f"ارتفع بنسبة تجاوزت {alert['threshold']:,.2f}%{change_text}"
    else:
        change = alert.get("change_pct")
        change_text = f" ({change:+.2f}%)" if change is not None else ""
        reason = f"انخفض بنسبة تجاوزت {alert['threshold']:,.2f}%{change_text}"

    lines = [
        header,
        price_text,
        reason,
        f"<i>📅 {format_cairo_from_iso(alert['fetched_at'])}</i>",
    ]
    if alert.get("source"):
        lines.append(f"<i>🔗 المصدر: {alert['source']}</i>")
    lines.append("")
    lines.append("<i>هذا تنبيه آلي من ASOUL.IQ وليس توصية استثمارية.</i>")
    return "\n".join(lines)


def format_cairo_from_iso(value: str) -> str:
    from datetime import datetime

    try:
        return format_cairo(datetime.fromisoformat(str(value)))
    except (TypeError, ValueError):
        return "غير معروف"


def refresh_alert_prices(db_path=None) -> list[str]:
    """يجلب أسعار الأصول التي عليها تنبيهات فقط، مرة لكل مزود،

    ويحترم التباعد الأدنى لكل مزود حتى لا نضرب الطبقة المجانية
    للـAPI بلا داعي (سعر الصرف مصدره يتحدث يوميًا أصلًا).
    """
    codes = alerts.assets_with_rules(db_path)
    refreshed: list[str] = []
    for provider_key in alerts.provider_keys_for(codes, db_path):
        result = prices.refresh_if_due(provider_key, db_path)
        if result is not None and result.ok:
            refreshed.append(provider_key)
    return refreshed


async def run_cycle(application, db_path=None) -> int:
    """دورة واحدة كاملة. ترجع عدد الرسائل المرسلة بنجاح."""
    sent = 0
    try:
        await asyncio.to_thread(refresh_alert_prices, db_path)
    except Exception:  # noqa: BLE001 - فشل مصدر لا يجب أن يوقف التنبيهات

        logger.exception("فشل تحديث أسعار التنبيهات")

    due = await asyncio.to_thread(alerts.due_alerts, db_path)
    for alert in due:
        message = format_alert(alert)
        try:
            await application.bot.send_message(
                chat_id=alert["telegram_id"], text=message, parse_mode="HTML"
            )
        except RetryAfter as exc:
            # تجاوزنا حد Telegram: نسجلها فشلًا ونحاول الدورة القادمة.
            logger.warning("Telegram rate limit: %s", exc)
            await asyncio.to_thread(
                alerts.log_notification, alert, alerts.STATUS_FAILED, message, "rate_limited", db_path
            )
            continue
        except Forbidden:
            logger.info("المستخدم %s أوقف البوت", alert["telegram_id"])
            await asyncio.to_thread(
                alerts.log_notification, alert, alerts.STATUS_FAILED, message, "blocked", db_path
            )
            continue
        except TelegramError as exc:
            logger.warning("فشل إرسال تنبيه: %s", exc)
            await asyncio.to_thread(
                alerts.log_notification, alert, alerts.STATUS_FAILED, message, str(exc)[:200], db_path
            )
            continue

        sent += 1
        await asyncio.to_thread(
            alerts.log_notification, alert, alerts.STATUS_SENT, message, None, db_path
        )
        await asyncio.to_thread(alerts.mark_triggered, alert["rule_id"], alerts.STATUS_SENT, db_path)

    if due:
        logger.info("دورة التنبيهات: مستحق %d، أُرسل %d", len(due), sent)

    # التقارير اليومية تعمل في نفس الدورة — لا عملية ولا Polling إضافي.
    try:
        await reports.send_due_reports(application, db_path)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - التقارير لا تُسقط دورة التنبيهات
        logger.exception("فشل إرسال التقارير اليومية")

    return sent


def _loop(application, interval: int, db_path) -> None:
    async def runner() -> None:
        # مهلة قصيرة عند البداية حتى يكتمل تشغيل البوت.
        await asyncio.sleep(45)
        while True:
            try:
                await run_cycle(application, db_path)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - الدورة لا تسقط أبدًا
                logger.exception("خطأ غير متوقع في دورة التنبيهات")
            await asyncio.sleep(interval)

    global _background_task
    _background_task = asyncio.create_task(runner())


async def start_background(application) -> None:
    if not config.ALERTS_ENABLED:
        logger.info("محرك التنبيهات معطّل (ALERTS_ENABLED=0)")
        return
    _loop(application, config.ALERT_INTERVAL_SECONDS, None)
    logger.info("محرك التنبيهات يعمل كل %d ثانية", config.ALERT_INTERVAL_SECONDS)


async def stop_background(application=None) -> None:
    global _background_task
    if _background_task is not None:
        _background_task.cancel()
        _background_task = None
        logger.info("تم إيقاف محرك التنبيهات")
