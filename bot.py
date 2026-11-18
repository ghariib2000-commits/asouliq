import os
import sqlite3
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# تحميل المفتاح السري
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

# دالة تهيئة قاعدة البيانات
def init_db():
    conn = sqlite3.connect("asouliq.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE,
            full_name TEXT,
            phone_number TEXT,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            registration_status TEXT DEFAULT 'started',
            whatsapp_consent INTEGER DEFAULT 0,
            consent_date TIMESTAMP,
            allowed_message_types TEXT DEFAULT 'none',
            subscription_status TEXT DEFAULT 'free',
            unsubscribed_at TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

# دالة الترحيب وطلب رقم الهاتف
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    telegram_id = user.id
    full_name = f"{user.first_name} {user.last_name or ''}".strip()

    try:
        conn = sqlite3.connect("asouliq.db")
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (telegram_id, full_name, registration_status)
            VALUES (?, ?, 'started')
            ON CONFLICT(telegram_id) DO UPDATE SET full_name = excluded.full_name
        """, (telegram_id, full_name))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"خطأ في حفظ المستخدم: {e}")

    contact_button = KeyboardButton(text="📍 مشاركة رقم الهاتف", request_contact=True)
    reply_markup = ReplyKeyboardMarkup([[contact_button]], resize_keyboard=True, one_time_keyboard=True)

    welcome_message = (
        f"أهلاً بك يا {user.first_name} في منصة ASOULIQ لتكنولوجيا المحفظة والأسواق المالية! 🚀\n"
        "لإتمام عملية التسجيل وتفعيل الحساب، برجاء الضغط على زر «مشاركة رقم الهاتف» بالأسفل."
    )
    await update.message.reply_text(welcome_message, reply_markup=reply_markup)

# دالة التحقق من رقم الهاتف
async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    contact = update.message.contact

    if contact and contact.phone_number and contact.user_id == user.id:
        phone_number = contact.phone_number
        if not phone_number.startswith("+"):
            phone_number = f"+{phone_number}"
        telegram_id = user.id

        try:
            conn = sqlite3.connect("asouliq.db")
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users 
                SET phone_number = ?, registration_status = 'completed' 
                WHERE telegram_id = ?
            """, (phone_number, telegram_id))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"خطأ في تحديث رقم الهاتف: {e}")

        await update.message.reply_text(
            "✅ تم توثيق رقم هاتفك وتسجيلك بنجاح في منصة ASOULIQ! أنت جاهز لتلقي التنبيهات والتحليلات المالية.", 
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        await update.message.reply_text("⚠️ عذراً، يجب مشاركة رقم هاتفك الشخصي من خلال الزر الرسمي بالأسفل.")

# دالة لوحة الإدارة للمالك
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = sqlite3.connect("asouliq.db")
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        
        cursor.execute("SELECT full_name, phone_number, joined_at FROM users ORDER BY id DESC LIMIT 5")
        recent_users = cursor.fetchall()
        
        conn.close()

        report = (
            "📊 **لوحة تحكم إدارة ASOULIQ (نظام تيليجرام):**\n\n"
            f"👥 إجمالي المستخدمين المسجلين: **{total_users}**\n\n"
            "--- **آخر المستخدمين:** ---\n"
        )
        
        if recent_users:
            for idx, user in enumerate(recent_users, 1):
                name, phone, joined = user
                phone_display = phone or "لم يشارك الرقم"
                report += f"{idx}. {name} | {phone_display}\n🕒 {joined}\n\n"
        else:
            report += "لا يوجد مستخدمون مسجلون حتى الآن."

        report += "\n💡 **لإرسال رسالة إذاعة جماعية:** اكتب الأمر `/broadcast` متبوعاً بالرسالة."
        await update.message.reply_text(report, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"حدث خطأ أثناء جلب بيانات الإدارة: {e}")

# دالة الإذاعة الجماعية (إرسال رسالة لكل المستخدمين)
async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # التأكد من وجود نص للرسالة بعد الأمر
    message_text = " ".join(context.args)
    if not message_text:
        await update.message.reply_text("⚠️ برجاء كتابة النص المراد إرساله بعد الأمر. مثال:\n`/broadcast تنبيه هام: ارتفاع أسعار الذهب اليوم!`", parse_mode="Markdown")
        return

    try:
        conn = sqlite3.connect("asouliq.db")
        cursor = conn.cursor()
        cursor.execute("SELECT telegram_id FROM users")
        users = cursor.fetchall()
        conn.close()

        success_count = 0
        fail_count = 0

        for user in users:
            chat_id = user[0]
            try:
                await context.bot.send_message(chat_id=chat_id, text=f"📢 **تنبيه من إدارة ASOULIQ:**\n\n{message_text}", parse_mode="Markdown")
                success_count += 1
            except Exception as e:
                print(f"فشل الإرسال للمستخدم {chat_id}: {e}")
                fail_count += 1

        await update.message.reply_text(f"✅ تمت عملية الإذاعة بنجاح!\n- تم الإرسال إلى: {success_count} مستخدم\n- فشل الإرسال إلى: {fail_count} مستخدم")
    except Exception as e:
        await update.message.reply_text(f"حدث خطأ أثناء تنفيذ الإذاعة: {e}")

def main():
    if not TOKEN:
        print("خطأ: لم يتم العثور على التوكن السري في ملف .env!")
        return

    init_db()

    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("broadcast", broadcast_message))
    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))

    print("جاري تشغيل بوت ASOULIQ بنظام تيليجرام المتكامل والإذاعة... يعمل بنجاح!")
    app.run_polling()

if __name__ == "__main__":
    main()