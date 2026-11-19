"""مزود العملات الأجنبية مقابل الجنيه المصري (18 عملة).

يُجلب سعر الصرف مرة واحدة لكل العملات من مصدر واحد، ثم يُحسب سعر كل
عملة بالجنيه. العملات التي تُسعَّر لكل 100 وحدة (الين) تُضرب في وحدة
التسعير الخاصة بها من سجل الأصول.
"""

from __future__ import annotations

import logging
from datetime import datetime

from app import config
from app.catalog import CURRENCIES
from app.clock import now_cairo
from app.providers.base import ProviderResult, Quote
from app.providers.gold_egp import ER_API_URL, _get_json

logger = logging.getLogger(__name__)


class FxProvider:
    key = "fx"
    label = "💱 العملات الأجنبية مقابل الجنيه"

    def fetch(self) -> ProviderResult:
        fetched_at: datetime = now_cairo()

        try:
            payload = _get_json(ER_API_URL)
            rates = payload["rates"]
            egp_per_usd = float(rates["EGP"])
            source_updated_at = str(payload.get("time_last_update_utc") or "")
        except Exception as exc:  # noqa: BLE001 - أي فشل يعني "لا بيانات"
            logger.warning("fx provider: تعذر جلب أسعار الصرف: %s", exc)
            return ProviderResult(
                provider_key=self.key,
                provider_label=self.label,
                ok=False,
                fetched_at=fetched_at,
                error="تعذر جلب أسعار الصرف من المصدر.",
                sources=(ER_API_URL,),
            )

        quotes: list[Quote] = []
        for asset in CURRENCIES:
            usd_to_currency = rates.get(asset.code)
            if not usd_to_currency:
                logger.warning("fx provider: المصدر لا يوفر %s", asset.code)
                continue
            try:
                per_unit_egp = egp_per_usd / float(usd_to_currency)
            except (TypeError, ValueError, ZeroDivisionError):
                continue

            value = round(per_unit_egp * asset.quote_unit, 2)
            quotes.append(
                Quote(
                    code=asset.code,
                    label=asset.name_ar,
                    value=value,
                    unit=asset.unit,
                    decimals=2,
                    source_updated_at=source_updated_at,
                )
            )

        if not quotes:
            return ProviderResult(
                provider_key=self.key,
                provider_label=self.label,
                ok=False,
                fetched_at=fetched_at,
                error="لم تصل أي عملة صالحة من المصدر.",
                sources=(ER_API_URL,),
            )

        return ProviderResult(
            provider_key=self.key,
            provider_label=self.label,
            ok=True,
            fetched_at=fetched_at,
            quotes=tuple(quotes),
            sources=("open.er-api.com",),
            footnotes=(
                f"سعر الدولار المرجعي: {egp_per_usd:,.2f} جنيه"
                + (f" (تحديث المصدر: {source_updated_at})" if source_updated_at else ""),
                "الأسعار محسوبة من سعر الصرف الرسمي وقد تختلف عن أسعار البنوك بهامش.",
            ),
            meta={"egp_per_usd": egp_per_usd},
        )
