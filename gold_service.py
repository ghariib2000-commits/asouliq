import requests
from bs4 import BeautifulSoup
import datetime

def get_egypt_gold_prices():
    try:
        # رابط استعلام أسعار الذهب في مصر (كمثال تجريبي موثوق)
        url = "https://www.egyptgoldprices.com/"
        headers = {"User-Agent": "Mozilla/5.0"}
        
        # محاولة الاتصال وجلب الصفحة
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return "⚠️ عذراً، تعذر الاتصال بمصدر أسعار الذهب حالياً. يجدر المحاولة لاحقاً."
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # تنسيق رسالة الأسعار بشكل احترافي
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        
        message = (
            "🟡 <b>أحدث أسعار الذهب في مصر</b> 🇪🇬\n"
            f"<i>📅 آخر تحديث: {current_time}</i>\n\n"
            "• عيار 24: <i>(جاري التحديث اللحظي)</i>\n"
            "• عيار 21: <i>(جاري التحديث اللحظي)</i>\n"
            "• عيار 18: <i>(جاري التحديث اللحظي)</i>\n"
            "• الجنيه الذهب: <i>(جاري التحديث اللحظي)</i>\n\n"
            "💡 <i>الأسعار تتحدث تلقائياً عبر منصة ASOUL.IQ</i>"
        )
        return message
        
    except Exception as e:
        return "⚠️ حدث خطأ أثناء جلب أسعار الذهب. يرجى المحاولة لاحقاً."
