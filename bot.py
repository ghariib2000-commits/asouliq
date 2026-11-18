import os
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from dotenv import load_dotenv
from gold_service import get_egypt_gold_prices
from egx_service import get_egx_market_data

# تحميل متغيرات البيئة
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

# سجل الخدمات القابل للتوسع
AVAILABLE_SERVICES = {
    "gold": {
        "name": "🟡 أسعار الذهب في مصر",
        "handler": get_egypt_gold_prices
    },
    "egx": {
        "name": "📈 البورصة المصرية والتوصيات",
        "handler": get_egx_market_data
    }
}

# تهيئة قاعدة البيانات وإنشاء الجداول من الصفر نظيفة
def init_db():
    conn = sqlite3.connect("asouliq.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            full_name TEXT,
            consent INTEGER DEFAULT 0,
            auto_updates INTEGER DEFAULT 0,
            interests TEXT DEFAULT 'gold,egx',
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

def get_user(chat_id):
    conn = sqlite3.connect("asouliq.db")
    cursor = conn.cursor()
    cursor.execute("SELECT consent, auto_updates, interests FROM users WHERE telegram_id = ?", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def update_user_pref(chat_id, field, value):
    conn = sqlite3.connect("asouliq.db")
    cursor = conn.cursor()
    cursor.execute(f"UPDATE users SET {field} = ? WHERE telegram_id = ?", (value, chat_id))
    conn.commit()
    conn.close()

# القوائم التفاعلية
def main_menu_keyboard():
    keyboard = []
    for key, service in AVAILABLE_SERVICES.items():
        keyboard.append([InlineKeyboardButton(service["name"], callback_data=f"fetch_{key}")])
    
    keyboard.append([InlineKeyboardButton("⚙️ إعدادات المتابعة والتنبيهات", callback_data="menu_settings")])
    return InlineKeyboardMarkup(keyboard)

def settings_keyboard(chat_id):
    user_data = get_user(chat_id)
    auto_updates = user_data[1] if user_data else 0
    interests = user_data[2].split(",") if (user_data and user_data[2]) else []

    auto_text = "🔔 التحديث التلقائي: مُفعّل (اضغط للإيقاف)" if auto_updates == 1 else "🔕 التحديث التلقائي: متوقف"
    
    keyboard = [
        [InlineKeyboardButton(auto_text, callback_data="toggle_auto")]
    ]
    
    for key, service in AVAILABLE_SERVICES.items():
        status_icon = "✅" if key in interests else "⬜"
        keyboard.append([InlineKeyboardButton(f"{status_icon} متابعة: {service['name']}", callback_data=f"toggle_int_{key}")])
        
    keyboard.append([InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

# معالجة الأوامر
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = user.id
    user_data = get_user(chat_id)

    if user_data and user_data[0] == 1:
        await update.message.reply_text(
            f"أهلاً بك يا {user.first_name} في منصة **ASOULIQ** المالية! 📊\n"
            "اختر الخدمة التي تريد الاطلاع عليها الآن أو اضبط إعداداتك:",
            reply_markup=main_menu_keyboard()
        )
    else:
        keyboard = [[InlineKeyboardButton("✅ أوافق على شروط الخدمة وأرغب في البدء", callback_data="consent_yes")]]
        await update.message.reply_text(
            f"مرحباً بك يا {user.first_name} في منصة **ASOULIQ** لأسواق المال في مصر. 🇪🇬\n\n"
            "يرجى تأكيد موافقتك للوصول إلى القوائم التفاعلية والأسعار:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    chat_id = user.id
    data = query.data

    if data == "consent_yes":
        conn = sqlite3.connect("asouliq.db")
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (telegram_id, full_name, consent, auto_updates, interests) 
            VALUES (?, ?, 1, 0, 'gold,egx')
            ON CONFLICT(telegram_id) DO UPDATE SET consent=1
        """, (chat_id, user.full_name))
        conn.commit()
        conn.close()

        await query.edit_message_text(
            "✅ **تم تفعيل حسابك بنجاح!**\n\n"
            "يمكنك الآن اختيار أي خدمة لمعرفة الأسعار فوراً، أو الدخول إلى الإعدادات لتخصيص تنبيهاتك:",
            reply_markup=main_menu_keyboard()
        )
        return

    user_data = get_user(chat_id)
    if not user_data or user_data[0] != 1:
        await query.edit_message_text("⚠️ يرجى إرسال /start والموافقة أولاً.")
        return

    if data == "main_menu":
        await query.edit_message_text(
            "📊 **القائمة الرئيسية - منصة ASOULIQ**\nاختر الخدمة المطلوبة:",
            reply_markup=main_menu_keyboard()
        )

    elif data == "menu_settings":
        await query.edit_message_text(
            "⚙️ **إعدادات التفضيلات والمتابعة:**\n\n"
            "• يمكنك تفعيل أو إيقاف استلام التحديثات.\n"
            "• يمكنك تحديد الأقسام التي تهمك:",
            reply_markup=settings_keyboard(chat_id)
        )

    elif data == "toggle_auto":
        new_status = 0 if user_data[1] == 1 else 1
        update_user_pref(chat_id, "auto_updates", new_status)
        await query.edit_message_reply_markup(reply_markup=settings_keyboard(chat_id))

    elif data.startswith("toggle_int_"):
        service_key = data.replace("toggle_int_", "")
        current_interests = user_data[2].split(",") if user_data[2] else []
        
        if service_key in current_interests:
            current_interests.remove(service_key)
        else:
            current_interests.append(service_key)
            
        updated_str = ",".join(filter(None, current_interests))
        update_user_pref(chat_id, "interests", updated_str)
        await query.edit_message_reply_markup(reply_markup=settings_keyboard(chat_id))

    elif data.startswith("fetch_"):
        service_key = data.replace("fetch_", "")
        if service_key in AVAILABLE_SERVICES:
            result_message = AVAILABLE_SERVICES[service_key]["handler"]()
            back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]])
            await query.edit_message_text(result_message, parse_mode="HTML", reply_markup=back_btn)

# التشغيل الرئيسي
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("🤖 ASOULIQ Interactive & Scalable Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
