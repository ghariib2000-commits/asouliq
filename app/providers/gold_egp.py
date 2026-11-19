"""مزود أسعار الذهب في مصر اعتمادًا على بيانات حقيقية.

طريقة الحساب (شفافة وقابلة للتحقق):
    1. سعر الأونصة عالميًا بالدولار   (api.gold-api.com)
    2. سعر الدولار مقابل الجنيه       (open.er-api.com)
    3. سعر جرام 24 = (الأونصة ÷ 31.1035) × سعر الدولار × معامل السوق
    4. عيار 21 = 24 × 21/24 ، عيار 18 = 24 × 18/24 ، الجنيه الذهب = 21 × 8

السعر الناتج سعر تقديري محسوب، وليس سعرًا من صاغة، لذلك يُعرض دائمًا
مع المصدرين ووقت التحديث وتنبيه واضح للمستخدم.
لا توجد أي أرقام ثابتة في الكود تُعرض عند فشل المصدر.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from datetime import datetime

from app import config
from app.clock import now_cairo
from app.providers.base import ProviderResult, Quote

logger = logging.getLogger(__name__)

ER_API_URL = "https://open.er-api.com/v6/latest/USD"
GOLD_API_URL = "https://api.gold-api.com/price/XAU"
TROY_OUNCE_GRAMS = 31.1035


def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "ASOULIQ/2.0"})
    with urllib.request.urlopen(request, timeout=config.HTTP_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


class GoldEgyptProvider:
    key = "gold"
    label = "🟡 أسعار الذهب في مصر"

    def fetch(self) -> ProviderResult:
        fetched_at: datetime = now_cairo()

        try:
            fx_payload = _get_json(ER_API_URL)
            usd_egp = float(fx_payload["rates"]["EGP"])
            # المصدر يحدّث سعر الصرف مرة يوميًا، فنعرض تاريخ تحديثه
            # حتى لا يظن المستخدم أن سعر الدولار لحظي.
            fx_updated = str(fx_payload.get("time_last_update_utc") or "")
        except Exception as exc:  # noqa: BLE001 - أي فشل للمصدر يعني "لا بيانات"
            logger.warning("gold provider: تعذر جلب سعر الدولار: %s", exc)
            return ProviderResult(
                provider_key=self.key,
                provider_label=self.label,
                ok=False,
                fetched_at=fetched_at,
                error="تعذر جلب سعر الدولار مقابل الجنيه من المصدر.",
                sources=(ER_API_URL,),
            )

        try:
            gold_payload = _get_json(GOLD_API_URL)
            ounce_usd = float(gold_payload["price"])
            gold_updated = str(gold_payload.get("updatedAt") or "")
        except Exception as exc:  # noqa: BLE001
            logger.warning("gold provider: تعذر جلب سعر الأونصة: %s", exc)
            return ProviderResult(
                provider_key=self.key,
                provider_label=self.label,
                ok=False,
                fetched_at=fetched_at,
                error="تعذر جلب سعر الذهب العالمي من المصدر.",
                sources=(GOLD_API_URL,),
            )

        if usd_egp <= 0 or ounce_usd <= 0:
            return ProviderResult(
                provider_key=self.key,
                provider_label=self.label,
                ok=False,
                fetched_at=fetched_at,
                error="وصلت قيم غير صالحة من المصدر (صفر أو أقل).",
            )

        gram_24 = (ounce_usd / TROY_OUNCE_GRAMS) * usd_egp * config.GOLD_MARKET_PREMIUM
        gram_21 = gram_24 * 21 / 24
        gram_18 = gram_24 * 18 / 24
        gold_pound = gram_21 * 8  # الجنيه الذهب = 8 جرام عيار 21

        quotes = (
            Quote("GOLD_24", "عيار 24", round(gram_24, 2), "جنيه/جرام"),
            Quote("GOLD_21", "عيار 21", round(gram_21, 2), "جنيه/جرام"),
            Quote("GOLD_18", "عيار 18", round(gram_18, 2), "جنيه/جرام"),
            Quote("GOLD_POUND", "الجنيه الذهب", round(gold_pound, 2), "جنيه"),
        )

        return ProviderResult(
            provider_key=self.key,
            provider_label=self.label,
            ok=True,
            fetched_at=fetched_at,
            quotes=quotes,
            sources=("api.gold-api.com", "open.er-api.com"),
            footnotes=(
                f"سعر الأونصة العالمية: ${ounce_usd:,.2f}"
                + (f" (تحديث: {gold_updated})" if gold_updated else ""),
                f"سعر الدولار: {usd_egp:,.2f} جنيه"
                + (f" (تحديث المصدر: {fx_updated})" if fx_updated else ""),
                "السعر تقديري محسوب من السعر العالمي وسعر الصرف، وقد يختلف عن سعر الصاغة.",
            ),
            is_estimate=True,
            meta={"ounce_usd": ounce_usd, "usd_egp": usd_egp, "gold_updated_at": gold_updated},
        )
