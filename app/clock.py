"""أدوات الوقت: كل الأوقات المعروضة للمستخدم بتوقيت القاهرة."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

try:  # على Linux/Railway يكون tzdata موجودًا
    from zoneinfo import ZoneInfo

    CAIRO_TZ: timezone | ZoneInfo = ZoneInfo("Africa/Cairo")
except Exception:  # على ويندوز بدون حزمة tzdata نستخدم توقيت ثابت
    CAIRO_TZ = timezone(timedelta(hours=2), "EET")


def now_cairo() -> datetime:
    return datetime.now(CAIRO_TZ)


def format_cairo(moment: datetime) -> str:
    """مثال: 2026-11-19 03:05 م"""
    local = moment.astimezone(CAIRO_TZ)
    period = "م" if local.hour >= 12 else "ص"
    return f"{local.strftime('%Y-%m-%d %I:%M')} {period}"
