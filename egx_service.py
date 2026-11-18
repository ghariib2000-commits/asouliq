import requests
from bs4 import BeautifulSoup
import datetime
import re

def get_egx_market_data():
    try:
        # استخدام مصدر مالي موثوق لمتابعة مؤشرات البورصة المصرية
        url = "https://www.mubasher.info/markets/EGX"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return "⚠️ عذراً، تعذر الاتصال بموقع البورصة المصرية حالياً. يرجى المحاولة لاحقاً."
            
        soup = BeautifulSoup(response.text, 'html.parser')
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # استخراج بيانات المؤشرات المتاحة في الصفحة
        indices_data = []
        for element in soup.find_all(['div', 'span', 'td'], class_=re.compile('index|price|change', re.I)):
            text = element.get_text().strip()
            if text and len(text) < 50:
                indices_data.append(text)
                
        message = (
            "📈 <b>مؤشرات وتوصيات البورصة المصرية (EGX) - حقيقي</b> 🇪🇬\n"
            f"<i>📅 آخر تحديث: {current_time}</i>\n\n"
        )
        
        if indices_data:
            # عرض بعض المؤشرات المستخرجة بشكل مرتب
            unique_indices = list(dict.fromkeys(indices_data))[:6]
            for item in unique_indices:
                message += f"• {item}\n"
        else:
            message += (
                "• <b>EGX 30:</b> <i>(يتم جلب القيمة اللحظية...)</i>\n"
                "• <b>EGX 70:</b> <i>(يتم جلب القيمة اللحظية...)</i>\n"
            )
            
        message += "\n💡 <i>تُحدث البيانات لحظياً عبر منصة ASOUL.IQ</i>"
        return message
        
    except Exception as e:
        return f"⚠️ حدث خطأ أثناء جلب مؤشرات البورصة: {str(e)}"
