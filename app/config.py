"""إعدادات التطبيق: تُقرأ مرة واحدة من متغيرات البيئة.

كل قيمة لها افتراضي آمن حتى يعمل المشروع محليًا بدون أي إعداد،
لكن على Railway يجب ضبط TELEGRAM_TOKEN و DATABASE_PATH.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# ملف .env للاستخدام المحلي فقط. على Railway تأتي القيم من Variables.
load_dotenv(BASE_DIR / ".env")


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _path_from_env(name: str, default: Path) -> Path:
    raw = _env(name)
    if not raw:
        return default
    candidate = Path(raw).expanduser()
    # مسار نسبي (مثل asouliq.db) يُفسَّر بالنسبة لجذر المشروع،
    # والمسار المطلق (مثل /data/asouliq.db على Railway) يُستخدم كما هو.
    return candidate if candidate.is_absolute() else BASE_DIR / candidate


TELEGRAM_TOKEN: str = _env("TELEGRAM_TOKEN")

# نفس المسار الافتراضي للنسخة القديمة حتى لا تنفصل عن الملف الموجود.
DATABASE_PATH: Path = _path_from_env("DATABASE_PATH", BASE_DIR / "asouliq.db")

# معامل السوق المصري في حساب سعر الجرام من السعر العالمي.
GOLD_MARKET_PREMIUM: float = float(_env("GOLD_MARKET_PREMIUM") or "1.018")

# مهلة طلبات HTTP بالثواني.
HTTP_TIMEOUT_SECONDS: float = float(_env("HTTP_TIMEOUT_SECONDS") or "8")

# مدة الاحتفاظ بالسعر في الذاكرة حتى لا نضرب المصدر مع كل ضغطة زر.
PRICE_CACHE_TTL_SECONDS: int = int(_env("PRICE_CACHE_TTL_SECONDS") or "60")

# بعد هذه المدة يُعتبر السعر المخزَّن قديمًا ويُعرض بعلامة تحذير.
PRICE_STALE_MINUTES: int = int(_env("PRICE_STALE_MINUTES") or "30")

# محرك التنبيهات
ALERTS_ENABLED: bool = _env("ALERTS_ENABLED", "1") not in {"0", "false", "False"}
ALERT_INTERVAL_SECONDS: int = int(_env("ALERT_INTERVAL_SECONDS") or "300")
ALERT_COOLDOWN_MINUTES: int = int(_env("ALERT_COOLDOWN_MINUTES") or "60")
ALERT_MAX_RULES: int = int(_env("ALERT_MAX_RULES") or "20")

LOG_LEVEL: str = _env("LOG_LEVEL", "INFO") or "INFO"


def _optional_int(name: str) -> int | None:
    raw = _env(name)
    return int(raw) if raw.isdigit() else None


# معرّف Telegram لمالك البوت — يسمح بأوامر حساسة مثل /backup.
OWNER_TELEGRAM_ID: int | None = _optional_int("OWNER_TELEGRAM_ID")


def database_is_ephemeral() -> bool:
    """هل ملف القاعدة داخل مجلد المشروع؟

    على Railway بدون Volume يُمسح نظام الملفات مع كل Deploy،
    فأي قاعدة داخل المشروع تعني فقدان البيانات. نستخدم هذا الفحص
    لتحذير واضح في السجلات بدل اكتشاف المشكلة بعد ضياع المستخدمين.
    """
    try:
        DATABASE_PATH.resolve().relative_to(BASE_DIR)
    except ValueError:
        return False
    return True


def is_owner(telegram_id: int | None) -> bool:
    return OWNER_TELEGRAM_ID is not None and telegram_id == OWNER_TELEGRAM_ID


def require_telegram_token() -> str:
    """يرجع الـToken أو يوقف التشغيل برسالة واضحة بدل فشل غامض."""
    if not TELEGRAM_TOKEN:
        raise RuntimeError(
            "TELEGRAM_TOKEN غير موجود. اضبطه في Railway Variables أو في ملف .env المحلي."
        )
    return TELEGRAM_TOKEN
