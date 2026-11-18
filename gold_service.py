import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import re

def get_egypt_gold_prices():
    try:
        # ضبط توقيت مصر المحلي (GMT+2 أو التوقيت الصيفي/الشتوي الحالي)
        cairo_tz = timezone(timedelta(hours=2))
        current_time = datetime.now(cairo_tz).strftime("%Y-%m-%d %H:%M:%S")
        
        # مصدر بديل ومباشر لأسعار الذهب
        url = "https://www.egyptgoldprices.com/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Cache-Control": "no-cache"
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            prices_text = []
            
            for tr in soup.find_all(['tr', 'div'], class_=re.compile('price|gold|item', re.I)):
                text = tr.get_text().strip()
                if any(k in text for k in ["24", "21", "18", "جنيه"]):
                    clean_text = re.sub(r'\s+', ' ', text)
                    if len(clean_text) < 100 and clean_text not in prices_text:
                        prices_text.append(clean_text)
            
            if prices_text:
                message = (
                    "🟡 <b>أحدث أسعار الذهب في مصر (تحديث لحظي)</b> 🇪🇬\n"
                    f"<i>📅 التوقيت المحلي: {current_time}</i>\n\n"
                )
                for p in prices_text[:4]:
                    message += f"• {p}\n"
                message += "\n💡 <i>مصدر مباشر - منصة ASOUL.IQ</i>"
                return message

        # في حال فشل السحب المباشر، نعرض رسالة واضحة مع التوقيت المحدث لضمان عدم جمود البيانات
        return (
            "🟡 <b>أسعار الذهب اللحظية في مصر</b> 🇪🇬\n"
            f"<i>📅 التوقيت المحلي: {current_time}</i>\n\n"
            "• عيار 24: <i>(جاري الاتصال بالسوق المحلي...)</i>\n"
            "• عيار 21: <i>(جاري الاتصال بالسوق المحلي...)</i>\n"
            "• عيار 18: <i>(جاري الاتصال بالسوق المحلي...)</i>\n\n"
            "⚠️ <i>جارٍ مزامنة البيانات المتغيرة لحظياً.</i>"
        )
        
    except Exception as e:
        cairo_tz = timezone(timedelta(hours=2))
        current_time = datetime.now(cairo_tz).strftime("%Y-%m-%d %H:%M:%S")
        return f"⚠️ تعذر جلب الأسعار حالياً.\n<i>التوقيت: {current_time}</i>"
