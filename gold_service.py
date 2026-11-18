import requests
from bs4 import BeautifulSoup
from datetime import datetime

def get_egypt_gold_prices():
    """
    دالة لجلب أحدث أسعار الذهب في مصر وتنسيقها بالعربية
    """
    url = "https://egypt.gold-price-today.com/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        prices = {}
        rows = soup.find_all("tr")
        for row in rows:
            cols = [col.get_text(strip=True) for col in row.find_all(["th", "td"])]
            if len(cols) >= 2:
                title = cols[0]
                if "عيار 24" in title and "24" not in prices:
                    prices["24"] = cols[1]
                elif "عيار 21" in title and "21" not in prices:
                    prices["21"] = cols[1]
                elif "عيار 18" in title and "18" not in prices:
                    prices["18"] = cols[1]
                elif "الجنيه الذهب" in title and "pound" not in prices:
                    prices["pound"] = cols[1]

        if "21" in prices:
            now = datetime.now().strftime("%Y-%m-%d | %I:%M %p")
            message = (
                "📊 <b>أسعار الذهب الآن في مصر (منصة ASOULIQ)</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"🟡 <b>عيار 24:</b> {prices.get('24', 'غير متاح')}\n"
                f"🟡 <b>عيار 21:</b> {prices.get('21', 'غير متاح')}\n"
                f"🟡 <b>عيار 18:</b> {prices.get('18', 'غير متاح')}\n"
                f"🪙 <b>الجنيه الذهب:</b> {prices.get('pound', 'غير متاح')}\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"🕒 <i>آخر تحديث: {now}</i>\n"
                "💡 <i>الأسعار استرشادية بدون المصنعية.</i>"
            )
            return message
        else:
            return "⚠️ عذراً، يتم تحديث أسعار الذهب حالياً. يرجى المحاولة لاحقاً."

    except Exception as e:
        print(f"Error fetching gold prices: {e}")
        return "⚠️ تعذر الاتصال بمصدر أسعار الذهب حالياً، يرجى المحاولة لاحقاً."
