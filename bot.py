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

# تهيئة قاعدة البيانات ونظام الموافقة (Opt-In)
def init_db():
    conn = sqlite3.connect("asouliq.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            full_name TEXT,
            consent INTEGER DEFAULT 0,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

# أمر البدء /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = user.id
    
    conn = sqlite3.connect("asouliq.db")
    cursor = conn.cursor()
    cursor.execute("SELECT consent FROM users WHERE telegram_id = ?", (chat_id,))
    row = cursor.fetchone()
    conn.close()

    if row and row[0] == 1:
        await update.message.reply_text(
            f"أهلاً بك مجدداً يا {user.first_name} في منصة **ASOULIQ** المالية! 📊\n\n"
            "اختر ما ترغب في متابعته من الأوامر التالية:\n"
            "🟡 /gold - أسعار الذهب اليوم في مصر\n"
            "📈 /egx - مؤشرات وتوصيات البورصة المصرية\n"
            "ℹ️ /help - للمساعدة والدعم"
        )
    else:
        keyboard = [
            [InlineKeyboardButton("✅ أوافق وأرغب في متابعة الأسواق", callback_data="consent_yes")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"مرحباً بك يا {user.first_name} في منصة **ASOULIQ** لأسواق المال والذهب في مصر. 🇪🇬\n\n"
            "للاستفادة من خدمات التنبيهات وأسعار الذهب والأسهم، يرجى تأكيد موافقتك على استخدام الخدمة بالضغط على الزر أدناه:",
            reply_markup=reply_markup
        )

# معالجة الموافقة
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "consent_yes":
        user = query.from_user
        chat_id = user.id
        
        conn = sqlite3.connect("asouliq.db")
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (telegram_id, full_name, consent) 
            VALUES (?, ?, 1)
            ON CONFLICT(telegram_id) DO UPDATE SET consent=1
        """, (chat_id, user.full_name))
        conn.commit()
        conn.close()
        
        await query.edit_message_text(
            "✅ **تم تسجيل موافقتك بنجاح!**\n\n"
            "أهلاً بك في عائلة ASOULIQ. يمكنك الآن استخدام:\n"
            "🟡 الأمر `/gold` لمعرفة أسعار الذهب.\n"
            "📈 الأمر `/egx` لمتابعة البورصة والأسهم."
        )

# دالة التحقق من الموافقة قبل تنفيذ أي أمر مالي
def check_user_consent(chat_id):
    conn = sqlite3.connect("asouliq.db")
    cursor = conn.cursor()
    cursor.execute("SELECT consent FROM users WHERE telegram_id = ?", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    return row and row[0] == 1

# أمر أسعار الذهب
async def gold_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_user.id
    if not check_user_consent(chat_id):
        await update.message.reply_text("⚠️ عذراً، يرجى الضغط على زر الموافقة بإرسال الأمر /start أولاً.")
        return
    
    message = get_egypt_gold_prices()
    await update.message.reply_text(message, parse_mode="HTML")

# أمر أسهم ومؤشرات البورصة المصرية
async def egx_market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_user.id
    if not check_user_consent(chat_id):
        await update.message.reply_text("⚠️ عذراً، يرجى الضغط على زر الموافقة بإرسال الأمر /start أولاً.")
        return
    
    message = get_egx_market_data()
    await update.message.reply_text(message, parse_mode="HTML")

# التشغيل الرئيسي
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("gold", gold_price))
    app.add_handler(CommandHandler("egx", egx_market))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("🤖 Bot ASOULIQ is running with Gold & EGX Services...")
    app.run_polling()

if __name__ == "__main__":
    main()