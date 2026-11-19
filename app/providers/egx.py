"""مزود البورصة المصرية من مصدر مجاني عام (TradingView Scanner).

يجلب في طلب واحد كل أسهم EGX (الرمز، الاسم، السعر، نسبة التغير، الحجم،
القطاع) وطلبًا ثانيًا للمؤشرات الثلاثة EGX30 / EGX70 / EGX100.

⚠️ ملاحظة ترخيص مهمة: هذه بيانات سوق مجانية من مصدر عام غير مرخّص
لإعادة التوزيع التجاري. صالحة للاستخدام الشخصي/التجريبي. قبل تحويل
المشروع لمنتج تجاري مدفوع يجب الانتقال لمصدر مرخّص (EGID أو EODHD).

لا تُعرض أي أرقام عند فشل المصدر — لا قيم افتراضية ولا تقديرات.
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

SCAN_URL = "https://scanner.tradingview.com/egypt/scan"

INDEX_TICKERS: dict[str, str] = {
    "EGX30": "EGX 30",
    "EGX70EWI": "EGX 70",
    "EGX100EWI": "EGX 100",
}

STOCK_COLUMNS = ["name", "description", "close", "change", "volume", "sector"]


def _scan(body: dict) -> dict:
    request = urllib.request.Request(
        SCAN_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ASOULIQ/2.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=config.HTTP_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _stocks_body() -> dict:
    return {
        "filter": [{"left": "type", "operation": "in_range", "right": ["stock"]}],
        "options": {"lang": "en"},
        "markets": ["egypt"],
        "columns": STOCK_COLUMNS,
        "sort": {"sortBy": "name", "sortOrder": "asc"},
        "range": [0, 400],
    }


class EgxProvider:
    key = "egx"
    label = "📈 البورصة المصرية"

    def fetch(self) -> ProviderResult:
        fetched_at: datetime = now_cairo()

        try:
            payload = _scan(_stocks_body())
            rows = payload.get("data") or []
        except Exception as exc:  # noqa: BLE001 - فشل المصدر = لا بيانات
            logger.warning("egx provider: تعذر جلب أسهم البورصة: %s", exc)
            return ProviderResult(
                provider_key=self.key,
                provider_label=self.label,
                ok=False,
                fetched_at=fetched_at,
                error="تعذر جلب أسعار البورصة المصرية من المصدر.",
                sources=("scanner.tradingview.com",),
            )

        quotes: list[Quote] = []
        for row in rows:
            values = row.get("d") or []
            if len(values) < 6 or values[2] is None:
                continue
            ticker = (values[0] or "").strip().upper()
            if not ticker:
                continue
            try:
                price = float(values[2])
            except (TypeError, ValueError):
                continue
            quotes.append(
                Quote(
                    code=ticker,
                    label=(values[1] or ticker),
                    value=price,
                    unit="جنيه",
                    decimals=2,
                    change_pct=float(values[3]) if values[3] is not None else None,
                )
            )

        indices: dict[str, float] = {}
        try:
            index_payload = _scan(
                {
                    "symbols": {"tickers": [f"EGX:{t}" for t in INDEX_TICKERS]},
                    "columns": ["name", "description", "close", "change"],
                }
            )
            for row in index_payload.get("data") or []:
                values = row.get("d") or []
                if len(values) < 4 or values[2] is None:
                    continue
                code = str(values[0])
                quotes.append(
                    Quote(
                        code=code,
                        label=INDEX_TICKERS.get(code, str(values[1] or code)),
                        value=float(values[2]),
                        unit="نقطة",
                        decimals=2,
                        change_pct=float(values[3]) if values[3] is not None else None,
                    )
                )
                indices[code] = float(values[2])
        except Exception as exc:  # noqa: BLE001 - المؤشرات إضافة وليست شرطًا
            logger.warning("egx provider: تعذر جلب المؤشرات: %s", exc)

        if not quotes:
            return ProviderResult(
                provider_key=self.key,
                provider_label=self.label,
                ok=False,
                fetched_at=fetched_at,
                error="المصدر لم يرجع أي سهم صالح.",
                sources=("scanner.tradingview.com",),
            )

        return ProviderResult(
            provider_key=self.key,
            provider_label=self.label,
            ok=True,
            fetched_at=fetched_at,
            quotes=tuple(quotes),
            sources=("scanner.tradingview.com",),
            footnotes=("أسعار البورصة المصرية من مصدر سوق مجاني عام.",),
            meta={
                "auto_register": True,
                "register_kind": "equity",
                "indices": indices,
                "stocks_count": sum(1 for q in quotes if q.unit == "جنيه"),
            },
        )
