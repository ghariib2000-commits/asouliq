"""نقطة تشغيل البوت — متوافقة مع Procfile الحالي (python bot.py)."""

from __future__ import annotations

import logging

from telegram.ext import ApplicationBuilder

from app import config
from app.bot.handlers import register_handlers
from app.db.migrations import current_version, upgrade
from app.logging_setup import configure_logging

logger = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    token = config.require_telegram_token()

    logger.info("قاعدة البيانات: %s", config.DATABASE_PATH)
    if config.database_is_ephemeral():
        logger.warning(
            "تنبيه: قاعدة البيانات داخل مجلد المشروع. بدون Volume على Railway "
            "ستُفقد البيانات مع كل Deploy. اضبط DATABASE_PATH على مسار Volume دائم."
        )

    applied = upgrade()
    if applied:
        logger.info("ترحيلات مطبقة الآن: %s", applied)
    logger.info("إصدار قاعدة البيانات الحالي: %s", current_version())

    application = ApplicationBuilder().token(token).build()
    register_handlers(application)

    logger.info("🤖 ASOUL.IQ bot is running (polling)...")
    application.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
