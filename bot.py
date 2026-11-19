"""نقطة تشغيل البوت — متوافقة مع Procfile الحالي (python bot.py)."""

from __future__ import annotations

import logging

from telegram.ext import ApplicationBuilder

from app import config
from app.bot.handlers import register_handlers
from app.catalog import sync_assets
from app.db.migrations import current_version, upgrade
from app.logging_setup import configure_logging
from app.services import notifier

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
    sync_assets()

    application = (
        ApplicationBuilder()
        .token(token)
        # محرك التنبيهات يعمل كـTask داخل نفس العملية — لا Polling ثانٍ.
        .post_init(notifier.start_background)
        .post_shutdown(notifier.stop_background)
        .build()
    )
    register_handlers(application)

    logger.info("🤖 ASOUL.IQ bot is running (polling)...")
    application.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
