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
from app.services import alerts, assets, market, prices, reports, users, watchlist

logger = logging.getLogger(__name__)

BACK_BUTTON = "🔙 العودة للقائمة الرئيسية"


def main_menu_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(provider.label, callback_data=f"fetch_{key}")]
        for key, provider in PROVIDERS.items()
    ]
    rows.append(
        [
            InlineKeyboardButton("⭐ قائمتي", callback_data="menu_watchlist"),
            InlineKeyboardButton("🔍 البحث", callback_data="menu_search"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton("🔔 تنبيهاتي", callback_data="menu_alerts"),
            InlineKeyboardButton("📬 التقرير اليومي", callback_data="menu_report"),
        ]
    )
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

    rows.append([InlineKeyboardButton("📬 التقرير اليومي", callback_data="menu_report")])
    rows.append([InlineKeyboardButton(BACK_BUTTON, callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)


def report_view(telegram_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """حالة التقرير اليومي + أزرار التفعيل/الإيقاف."""
    settings = reports.get_settings(telegram_id)
    if settings and settings["enabled"] == 1:
        status = (
            "✅ مُفعّل يوميًا الساعة "
            f"<b>{reports.format_time(settings['hour'], settings['minute'])}</b> بتوقيت القاهرة"
        )
        toggle = InlineKeyboardButton("🔕 إيقاف التقرير", callback_data="report_off")
    else:
        status = "🔕 متوقف"
        toggle = InlineKeyboardButton("✅ تفعيل التقرير", callback_data="report_on")

    text = (
        "📬 <b>التقرير اليومي</b>\n\n"
        f"الحالة: {status}\n\n"
        "في الموعد بيوصلك ملخص <b>قائمتك ⭐</b> بأسعارها ونسبة التغير، "
        "مع تنبيه للأسعار القديمة.\n\n"
        "الأوامر:\n"
        "<code>/report 09:00</code> — تحديد الموعد وتفعيله\n"
        "<code>/report off</code> — إيقاف\n\n"
        "<i>محتاج أصول في قائمتك أولًا: /search ثم إضافة.</i>"
    )
    keyboard = InlineKeyboardMarkup(
        [[toggle], [InlineKeyboardButton(BACK_BUTTON, callback_data="main_menu")]]
    )
    return text, keyboard


def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(BACK_BUTTON, callback_data="main_menu")]])


def _chunk(buttons: list[InlineKeyboardButton], size: int = 2) -> list[list[InlineKeyboardButton]]:
    return [buttons[i : i + size] for i in range(0, len(buttons), size)]


def watchlist_view(telegram_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """يبني نص ولوحة قائمة المتابعة مع حالة حداثة كل سعر."""
    items = watchlist.items(telegram_id)
    if not items:
        return (
            "⭐ <b>قائمتي</b>\n\nالقائمة فاضية.\n"
            "ابعت /search واسم الأصل أو كوده لإضافته (مثال: <code>/search دولار</code>).",
            InlineKeyboardMarkup([[InlineKeyboardButton(BACK_BUTTON, callback_data="main_menu")]]),
        )

    lines = [f"⭐ <b>قائمتي</b> ({len(items)} أصل)", ""]
    for item in items:
        if item["price"] is None:
            price_text = "بدون سعر محدث"
        else:
            price_text = f"{item['price']:,.2f} {item['unit']}"
            if item["stale"]:
                price_text += " ⚠️ سعر قديم"
        lines.append(f"• <b>{item['name_ar']}</b> ({item['code']}): {price_text}")

    remove_buttons = [
        InlineKeyboardButton(f"🗑 {item['code']}", callback_data=f"wl_del:{item['code']}")
        for item in items
    ]
    keyboard = _chunk(remove_buttons)
    keyboard.append([InlineKeyboardButton("🔄 تحديث الأسعار", callback_data="wl_refresh")])
    keyboard.append([InlineKeyboardButton(BACK_BUTTON, callback_data="main_menu")])
    return "\n".join(lines), InlineKeyboardMarkup(keyboard)


def search_view(term: str, telegram_id: int) -> tuple[str, InlineKeyboardMarkup]:
    results = assets.search_assets(term)
    if not results:
        return (
            f"🔍 مفيش نتائج لـ «{term}».\nجرّب كود الأصل مثل <code>USD</code> أو <code>GOLD_21</code>.",
            _back_keyboard(),
        )

    lines = [f"🔍 <b>نتائج البحث عن «{term}»</b>", ""]
    rows = []
    for asset in results:
        lines.append(f"• <b>{asset['name_ar']}</b> — <code>{asset['code']}</code>")
        if watchlist.contains(telegram_id, asset["code"]):
            rows.append(
                [InlineKeyboardButton(f"✅ إزالة {asset['code']}", callback_data=f"wl_del:{asset['code']}")]
            )
        else:
            rows.append(
                [InlineKeyboardButton(f"➕ إضافة {asset['code']}", callback_data=f"wl_add:{asset['code']}")]
            )
    rows.append([InlineKeyboardButton(BACK_BUTTON, callback_data="main_menu")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def alerts_view(telegram_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """قائمة تنبيهات المستخدم مع زر حذف لكل واحد."""
    rules = alerts.list_rules(telegram_id)
    heading = "🔔 <b>تنبيهاتي</b>"
    usage = (
        "لإضافة تنبيه:\n"
        "<code>/alert USD above 55</code> — لما السعر يوصل 55\n"
        "<code>/alert GOLD_21 below 5500</code> — لما ينزل 5500\n"
        "<code>/alert USD up 2</code> — لما يرتفع 2%\n"
        "<code>/alert USD down 2</code> — لما ينزل 2%"
    )

    if not rules:
        return (
            f"{heading}\n\nمفيش تنبيهات لحد الآن.\n\n{usage}",
            _back_keyboard(),
        )

    lines = [f"{heading} ({len(rules)})", ""]
    buttons = []
    for rule in rules:
        is_pct = rule["rule_type"] in (alerts.RULE_PCT_UP, alerts.RULE_PCT_DOWN)
        suffix = "%" if is_pct else f" {rule['unit']}"
        lines.append(
            f"• <b>#{rule['id']}</b> {rule['name_ar']} ({rule['asset_code']}): "
            f"{alerts.RULE_LABELS[rule['rule_type']]} {rule['threshold']:,.2f}{suffix}"
        )
        buttons.append(
            InlineKeyboardButton(f"🗑 #{rule['id']} {rule['asset_code']}", callback_data=f"al_del:{rule['id']}")
        )

    lines.append("")
    lines.append("<i>الحذف بالضغط على الزر. الإضافة بالأوامر:</i>")
    lines.append("<code>/alert USD above 55</code>")

    keyboard = _chunk(buttons)
    keyboard.append([InlineKeyboardButton(BACK_BUTTON, callback_data="main_menu")])
    return "\n".join(lines), InlineKeyboardMarkup(keyboard)


def _refresh_watchlist_prices(telegram_id: int) -> None:
    """يجلب أسعار مزودي أصول القائمة فقط، مرة واحدة لكل مزود."""
    keys = {item["code"] for item in watchlist.items(telegram_id)}
    providers = set()
    for code in keys:
        asset = assets.get_asset(code)
        if asset is not None:
            providers.add(asset["provider_key"])
    for key in providers:
        prices.refresh(key)


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


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if update.message is None or user is None:
        return
    if not users.has_consent(user.id):
        await update.message.reply_text("⚠️ يرجى إرسال /start والموافقة أولاً.")
        return

    term = " ".join(context.args or []).strip()
    if not term:
        await update.message.reply_text(
            "🔍 اكتب اسم الأصل أو كوده بعد الأمر.\nأمثلة:\n"
            "<code>/search دولار</code>\n<code>/search GOLD_21</code>",
            parse_mode="HTML",
        )
        return

    context.user_data["last_search"] = term
    text, keyboard = search_view(term, user.id)
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


async def watchlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if update.message is None or user is None:
        return
    if not users.has_consent(user.id):
        await update.message.reply_text("⚠️ يرجى إرسال /start والموافقة أولاً.")
        return

    text, keyboard = await asyncio.to_thread(watchlist_view, user.id)
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


async def _send_prices(query, service_key: str) -> None:
    """الجلب والتخزين يتمان في Thread حتى لا يتجمد البوت أثناء انتظار الشبكة."""
    result = await asyncio.to_thread(prices.refresh, service_key)
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

    elif data == "menu_search":
        await query.edit_message_text(
            "🔍 <b>البحث عن أصل</b>\n\n"
            "ابعت الأمر ده مع اسم الأصل أو كوده:\n"
            "<code>/search دولار</code>\n<code>/search GOLD_21</code>",
            reply_markup=_back_keyboard(),
            parse_mode="HTML",
        )

    elif data == "menu_alerts":
        text, keyboard = alerts_view(telegram_id)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    elif data == "menu_report":
        text, keyboard = report_view(telegram_id)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    elif data == "report_on":
        reports.enable(telegram_id)
        await query.answer("✅ تم تفعيل التقرير اليومي")
        text, keyboard = report_view(telegram_id)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    elif data == "report_off":
        reports.disable(telegram_id)
        await query.answer("🔕 تم إيقاف التقرير اليومي")
        text, keyboard = report_view(telegram_id)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    elif data.startswith("al_del:"):
        try:
            rule_id = int(data.split(":", 1)[1])
        except ValueError:
            await query.answer("رقم غير صالح")
            return
        removed = alerts.remove_rule(telegram_id, rule_id)
        await query.answer("🗑 تم حذف التنبيه" if removed else "التنبيه غير موجود")
        text, keyboard = alerts_view(telegram_id)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    elif data == "menu_watchlist":
        await query.edit_message_text(
            "⭐ <b>قائمتي</b>\n\nجاري تحميل أسعار أصولك...",
            reply_markup=_back_keyboard(),
            parse_mode="HTML",
        )
        try:
            await asyncio.to_thread(_refresh_watchlist_prices, telegram_id)
        except Exception:  # noqa: BLE001 - فشل المصدر لا يجب أن يمنع عرض القائمة
            logger.exception("فشل تحديث أسعار القائمة")
        text, keyboard = await asyncio.to_thread(watchlist_view, telegram_id)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    elif data == "wl_refresh":
        await asyncio.to_thread(_refresh_watchlist_prices, telegram_id)
        text, keyboard = await asyncio.to_thread(watchlist_view, telegram_id)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    elif data.startswith(("wl_add:", "wl_del:")):
        action, _, code = data.partition(":")
        if action == "wl_add":
            added = watchlist.add(telegram_id, code)
            await query.answer("✅ تمت الإضافة" if added else "⚠️ تعذر الإضافة", show_alert=False)
        else:
            removed = watchlist.remove(telegram_id, code)
            await query.answer("🗑 تمت الإزالة" if removed else "الأصل غير موجود", show_alert=False)

        last_search = context.user_data.get("last_search")
        if last_search:
            text, keyboard = search_view(last_search, telegram_id)
        else:
            text, keyboard = watchlist_view(telegram_id)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    elif data == "toggle_auto":
        users.toggle_auto_updates(telegram_id)
        await query.edit_message_reply_markup(reply_markup=settings_keyboard(telegram_id))

    elif data.startswith("toggle_int_"):
        users.toggle_interest(telegram_id, data.replace("toggle_int_", ""))
        await query.edit_message_reply_markup(reply_markup=settings_keyboard(telegram_id))

    elif data.startswith("fetch_"):
        await _send_prices(query, data.replace("fetch_", ""))


async def alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if update.message is None or user is None:
        return
    if not users.has_consent(user.id):
        await update.message.reply_text("⚠️ يرجى إرسال /start والموافقة أولاً.")
        return

    text, keyboard = alerts_view(user.id)
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


async def alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/alert <كود الأصل> <نوع التنبيه> <القيمة>"""
    user = update.effective_user
    if update.message is None or user is None:
        return
    if not users.has_consent(user.id):
        await update.message.reply_text("⚠️ يرجى إرسال /start والموافقة أولاً.")
        return

    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text(
            "🔔 <b>طريقة إضافة تنبيه</b>\n\n"
            "<code>/alert USD above 55</code>\n"
            "<code>/alert GOLD_21 below 5500</code>\n"
            "<code>/alert USD up 2</code>\n"
            "<code>/alert USD down 2</code>\n\n"
            "الأنواع المقبولة: above/فوق، below/تحت، up/ارتفاع، down/انخفاض.",
            parse_mode="HTML",
        )
        return

    code, raw_type, raw_value = args[0], args[1], args[2]
    rule_type = alerts.normalize_rule_type(raw_type)
    if rule_type is None:
        await update.message.reply_text(
            "⚠️ نوع تنبيه غير معروف. استخدم: above, below, up, down"
        )
        return

    try:
        threshold = float(raw_value.replace("%", "").replace(",", ""))
    except ValueError:
        await update.message.reply_text("⚠️ القيمة لازم تكون رقمًا، مثال: 55 أو 2.5")
        return

    asset = assets.get_asset(code)
    if asset is None:
        await update.message.reply_text(
            f"⚠️ الأصل <code>{code}</code> غير موجود. جرّب /search للبحث.", parse_mode="HTML"
        )
        return

    rule_id = alerts.add_rule(user.id, asset["code"], rule_type, threshold)
    if rule_id is None:
        await update.message.reply_text(
            "⚠️ تعذر إنشاء التنبيه: قد يكون مكررًا أو وصلت للحد الأقصى "
            f"({config.ALERT_MAX_RULES} تنبيه) أو القيمة غير صالحة."
        )
        return

    is_pct = rule_type in (alerts.RULE_PCT_UP, alerts.RULE_PCT_DOWN)
    suffix = "%" if is_pct else f" {asset['unit']}"
    await update.message.reply_text(
        f"✅ تم إنشاء التنبيه <b>#{rule_id}</b>\n"
        f"{asset['name_ar']} ({asset['code']}): {alerts.RULE_LABELS[rule_type]} "
        f"{threshold:,.2f}{suffix}\n\n"
        f"<i>يتم الفحص كل {config.ALERT_INTERVAL_SECONDS // 60} دقيقة تقريبًا، "
        f"وبحد أدنى {config.ALERT_COOLDOWN_MINUTES} دقيقة بين كل تنبيه وآخر لنفس القاعدة.</i>",
        parse_mode="HTML",
    )


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/report [HH:MM | on | off] — التقرير اليومي لقائمة المتابعة."""
    user = update.effective_user
    if update.message is None or user is None:
        return
    if not users.has_consent(user.id):
        await update.message.reply_text("⚠️ يرجى إرسال /start والموافقة أولاً.")
        return

    args = context.args or []
    if not args:
        text, keyboard = report_view(user.id)
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)
        return

    action = args[0].strip().lower()
    if action in ("off", "إيقاف", "ايقاف", "stop"):
        reports.disable(user.id)
        await update.message.reply_text("🔕 تم إيقاف التقرير اليومي.")
        return

    if action in ("on", "تفعيل", "start"):
        settings = reports.enable(user.id)
    else:
        parsed = reports.parse_time(action)
        if parsed is None:
            await update.message.reply_text(
                "⚠️ موعد غير صالح. استخدم 24 ساعة مثل:\n"
                "<code>/report 09:00</code>\n<code>/report 21:30</code>\n"
                "أو <code>/report off</code> للإيقاف.",
                parse_mode="HTML",
            )
            return
        reports.set_schedule(user.id, parsed[0], parsed[1])
        settings = reports.get_settings(user.id) or {}

    when = reports.format_time(settings.get("hour", 9), settings.get("minute", 0))
    lines = [
        f"✅ <b>تم تفعيل التقرير اليومي</b> الساعة <b>{when}</b> بتوقيت القاهرة.",
        "",
        "يوصلك ملخص قائمتك ⭐ في الموعد، ولو الموعد لسه ما جاش النهارده يبدأ من بكرة.",
    ]
    if not watchlist.items(user.id):
        lines.append("")
        lines.append("⚠️ قائمتك فاضية حاليًا — أضف أصولًا بـ /search عشان يبقى للتقرير محتوى.")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


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
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("watchlist", watchlist_command))
    app.add_handler(CommandHandler("alerts", alerts_command))
    app.add_handler(CommandHandler("alert", alert_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("backup", backup_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_error_handler(on_error)
