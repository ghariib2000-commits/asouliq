"""واجهة Telegram: أزرار وقوائم فقط، بدون أي منطق أسعار أو قاعدة بيانات.

كل العمليات التشغيلية تتم في app/services، فيمكن اختبارها بدون Telegram.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from app import config
from app.db.backup import BackupError, backup_database
from app.providers import PROVIDERS
from app.services import market, users

logger = logging.getLogger(__name__)

BACK_BUTTON = "🔙 العودة للقائمة الرئيسية"


def main_menu_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(provider.label, callback_data=f"fetch_{key}")]
        for key, provider in PROVIDERS.items()
    ]
    rows.append(
        [InlineKeyboardButton("⚙️ إعدادات المتابعة والتنبيهات", callback_data="menu_settings")]
    )
    return InlineKeyboardMarkup(rows)


def settings_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    user = users.get_user(telegram_id)
    auto_updates = user["auto_updates"] if user else 0
    interests = users.interests_of(telegram_id)

    auto_text = (
        "🔔 التحديث التلقائي: مُفعّل (اضغط للإيقاف)"
        if auto_updates == 1
        else "🔕 التحديث التلقائي: متوقف"
    )
    rows = [[InlineKeyboardButton(auto_text, callback_data="toggle_auto")]]

    for key, provider in PROVIDERS.items():
        status_icon = "✅" if key in interests else "⬜"
        rows.append(
            [InlineKeyboardButton(f"{status_icon} متابعة: {provider.label}", callback_data=f"toggle_int_{key}")]
        )

    rows.append([InlineKeyboardButton(BACK_BUTTON, callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)


def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(BACK_BUTTON, callback_data="main_menu")]])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.message is None:
        return

    if users.has_consent(user.id):
        await update.message.reply_text(
            f"أهلاً بك يا {user.first_name} في منصة <b>ASOUL.IQ</b> المالية 📊\n"
            "اختر الخدمة التي تريد الاطلاع عليها الآن أو اضبط إعداداتك:",
            reply_markup=main_menu_keyboard(),
            parse_mode="HTML",
        )
        return

    await update.message.reply_text(
        f"مرحباً بك يا {user.first_name} في منصة <b>ASOUL.IQ</b> لأسواق المال في مصر 🇪🇬\n\n"
        "يرجى تأكيد موافقتك للوصول إلى القوائم التفاعلية والأسعار:",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("✅ أوافق على شروط الخدمة وأرغب في البدء", callback_data="consent_yes")]]
        ),
        parse_mode="HTML",
    )


async def _send_prices(query, service_key: str) -> None:
    """الجلب يتم في Thread حتى لا يتجمد البوت أثناء انتظار الشبكة."""
    result = await asyncio.to_thread(market.get_prices, service_key)
    await query.edit_message_text(
        market.format_result(result),
        parse_mode="HTML",
        reply_markup=_back_keyboard(),
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.from_user is None:
        return
    await query.answer()

    telegram_id = query.from_user.id
    data = query.data or ""

    if data == "consent_yes":
        users.register_consent(telegram_id, query.from_user.full_name)
        logger.info("مستخدم جديد أكمل الموافقة: %s", telegram_id)
        await query.edit_message_text(
            "✅ <b>تم تفعيل حسابك بنجاح!</b>\n\n"
            "يمكنك الآن اختيار أي خدمة لمعرفة الأسعار، أو الدخول إلى الإعدادات:",
            reply_markup=main_menu_keyboard(),
            parse_mode="HTML",
        )
        return

    if not users.has_consent(telegram_id):
        await query.edit_message_text("⚠️ يرجى إرسال /start والموافقة أولاً.")
        return

    if data == "main_menu":
        await query.edit_message_text(
            "📊 <b>القائمة الرئيسية — ASOUL.IQ</b>\nاختر الخدمة المطلوبة:",
            reply_markup=main_menu_keyboard(),
            parse_mode="HTML",
        )

    elif data == "menu_settings":
        await query.edit_message_text(
            "⚙️ <b>إعدادات التفضيلات والمتابعة:</b>\n\n"
            "• يمكنك تفعيل أو إيقاف استلام التحديثات.\n"
            "• يمكنك تحديد الأقسام التي تهمك:",
            reply_markup=settings_keyboard(telegram_id),
            parse_mode="HTML",
        )

    elif data == "toggle_auto":
        users.toggle_auto_updates(telegram_id)
        await query.edit_message_reply_markup(reply_markup=settings_keyboard(telegram_id))

    elif data.startswith("toggle_int_"):
        users.toggle_interest(telegram_id, data.replace("toggle_int_", ""))
        await query.edit_message_reply_markup(reply_markup=settings_keyboard(telegram_id))

    elif data.startswith("fetch_"):
        await _send_prices(query, data.replace("fetch_", ""))


async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يرسل نسخة من قاعدة البيانات إلى مالك البوت فقط.

    الطريقة الآمنة الوحيدة لأخذ نسخة من قاعدة Railway بدون وصول للوحة.
    لا تعمل أبدًا لأي مستخدم آخر.
    """
    user = update.effective_user
    if update.message is None:
        return
    if not config.is_owner(user.id if user else None):
        await update.message.reply_text("هذا الأمر متاح لمالك البوت فقط.")
        return

    workdir = Path(tempfile.mkdtemp(prefix="asouliq_backup_"))
    try:
        info = await asyncio.to_thread(backup_database, None, workdir)
        with info.path.open("rb") as handle:
            await update.message.reply_document(
                document=handle,
                filename=info.path.name,
                caption=f"نسخة احتياطية سليمة — المستخدمون: {info.users_count}",
            )
        logger.info("تم إرسال نسخة احتياطية للمالك (%d مستخدم)", info.users_count)
    except BackupError as exc:
        logger.error("فشل النسخ الاحتياطي: %s", exc)
        await update.message.reply_text(f"فشل إنشاء النسخة: {exc}")
    finally:
        for leftover in workdir.glob("*"):
            leftover.unlink(missing_ok=True)
        workdir.rmdir()


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يسجل الأخطاء بدل أن يموت البوت بصمت."""
    logger.exception("خطأ غير متوقع أثناء معالجة تحديث", exc_info=context.error)


def register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("backup", backup_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_error_handler(on_error)
