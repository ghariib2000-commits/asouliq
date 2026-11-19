"""سجل الأصول: التعريف الوحيد لكل أصل يدعمه النظام.

هذا الملف هو المصدر الوحيد للحقيقة (single source of truth) لأكواد الأصول
وأسمائها ووحدات التسعير، ويُستخدم في الترحيل والمزودين والبحث والقوائم.

إضافة أصل جديد = سطر هنا فقط، ثم sync_assets عند التشغيل.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.db.connection import session

logger = logging.getLogger(__name__)

KIND_CURRENCY = "currency"
KIND_COMMODITY = "commodity"
KIND_EQUITY = "equity"
KIND_INDEX = "index"


@dataclass(frozen=True)
class AssetDefinition:
    code: str
    kind: str
    name_ar: str
    name_en: str
    quote_unit: int = 1
    unit: str = "جنيه"
    symbol: str | None = None
    sector: str | None = None
    provider_key: str = ""


# العملات الـ18 مقابل الجنيه المصري.
# quote_unit=100 للعملات التي تُسعَّر لكل 100 وحدة (الين الياباني).
CURRENCIES: tuple[AssetDefinition, ...] = (
    AssetDefinition("USD", KIND_CURRENCY, "دولار أمريكي", "US Dollar", provider_key="fx"),
    AssetDefinition("EUR", KIND_CURRENCY, "يورو", "Euro", provider_key="fx"),
    AssetDefinition("GBP", KIND_CURRENCY, "جنيه إسترليني", "British Pound", provider_key="fx"),
    AssetDefinition("CAD", KIND_CURRENCY, "دولار كندي", "Canadian Dollar", provider_key="fx"),
    AssetDefinition("DKK", KIND_CURRENCY, "كرونة دنماركية", "Danish Krone", provider_key="fx"),
    AssetDefinition("NOK", KIND_CURRENCY, "كرونة نرويجية", "Norwegian Krone", provider_key="fx"),
    AssetDefinition("SEK", KIND_CURRENCY, "كرونة سويدية", "Swedish Krona", provider_key="fx"),
    AssetDefinition("CHF", KIND_CURRENCY, "فرنك سويسري", "Swiss Franc", provider_key="fx"),
    AssetDefinition(
        "JPY", KIND_CURRENCY, "ين ياباني", "Japanese Yen",
        quote_unit=100, unit="جنيه/100 وحدة", provider_key="fx",
    ),
    AssetDefinition("SAR", KIND_CURRENCY, "ريال سعودي", "Saudi Riyal", provider_key="fx"),
    AssetDefinition("KWD", KIND_CURRENCY, "دينار كويتي", "Kuwaiti Dinar", provider_key="fx"),
    AssetDefinition("AED", KIND_CURRENCY, "درهم إماراتي", "UAE Dirham", provider_key="fx"),
    AssetDefinition("AUD", KIND_CURRENCY, "دولار أسترالي", "Australian Dollar", provider_key="fx"),
    AssetDefinition("BHD", KIND_CURRENCY, "دينار بحريني", "Bahraini Dinar", provider_key="fx"),
    AssetDefinition("OMR", KIND_CURRENCY, "ريال عماني", "Omani Rial", provider_key="fx"),
    AssetDefinition("QAR", KIND_CURRENCY, "ريال قطري", "Qatari Riyal", provider_key="fx"),
    AssetDefinition("JOD", KIND_CURRENCY, "دينار أردني", "Jordanian Dinar", provider_key="fx"),
    AssetDefinition("CNY", KIND_CURRENCY, "يوان صيني", "Chinese Yuan", provider_key="fx"),
)

GOLD_ASSETS: tuple[AssetDefinition, ...] = (
    AssetDefinition(
        "GOLD_24", KIND_COMMODITY, "ذهب عيار 24", "Gold 24K",
        unit="جنيه/جرام", provider_key="gold",
    ),
    AssetDefinition(
        "GOLD_21", KIND_COMMODITY, "ذهب عيار 21", "Gold 21K",
        unit="جنيه/جرام", provider_key="gold",
    ),
    AssetDefinition(
        "GOLD_18", KIND_COMMODITY, "ذهب عيار 18", "Gold 18K",
        unit="جنيه/جرام", provider_key="gold",
    ),
    AssetDefinition(
        "GOLD_POUND", KIND_COMMODITY, "الجنيه الذهب", "Gold Pound",
        provider_key="gold",
    ),
)

ASSETS: tuple[AssetDefinition, ...] = CURRENCIES + GOLD_ASSETS


def sync_assets(db_path: str | Path | None = None, definitions=ASSETS) -> int:
    """يثبّت تعريفات الأصول في جدول assets (idempotent).

    لا يحذف أصولًا موجودة، فيمكن إضافة أصول جديدة لاحقًا بدون ترحيل.
    """
    with session(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO assets (code, kind, name_ar, name_en, symbol, sector, quote_unit, unit, provider_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                kind        = excluded.kind,
                name_ar     = excluded.name_ar,
                name_en     = excluded.name_en,
                symbol      = excluded.symbol,
                sector      = excluded.sector,
                quote_unit  = excluded.quote_unit,
                unit        = excluded.unit,
                provider_key= excluded.provider_key,
                is_active   = 1
            """,
            [
                (
                    a.code,
                    a.kind,
                    a.name_ar,
                    a.name_en,
                    a.symbol,
                    a.sector,
                    a.quote_unit,
                    a.unit,
                    a.provider_key,
                )
                for a in definitions
            ],
        )
    logger.info("تمت مزامنة %d أصل", len(definitions))
    return len(definitions)


def unit_label(quote_unit: int) -> str:
    return "جنيه" if quote_unit == 1 else f"جنيه لكل {quote_unit} وحدة"


def find_definition(code: str) -> AssetDefinition | None:
    wanted = code.upper()
    return next((a for a in ASSETS if a.code == wanted), None)


def count_by_kind(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT kind, COUNT(*) AS c FROM assets GROUP BY kind")
    return {row["kind"]: row["c"] for row in rows}
