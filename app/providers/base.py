"""واجهة موحدة لمزودي البيانات.

أي مزود جديد (EGX، عملات، معادن) يُنفذ نفس الواجهة، فيمكن تغيير
المصدر بدون تعديل محرك الأسعار أو التنبيهات أو واجهة Telegram.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Quote:
    """سعر واحد جاهز للعرض."""

    code: str
    label: str
    value: float
    unit: str
    decimals: int = 0


@dataclass(frozen=True)
class ProviderResult:
    """نتيجة محاولة جلب سعر من مزود.

    ok=False تعني: لا توجد بيانات حقيقية، ولا يجوز عرض أرقام.
    """

    provider_key: str
    provider_label: str
    ok: bool
    fetched_at: datetime
    quotes: tuple[Quote, ...] = ()
    sources: tuple[str, ...] = ()
    footnotes: tuple[str, ...] = ()
    is_estimate: bool = False
    unavailable_reason: str | None = None
    error: str | None = None
    meta: dict = field(default_factory=dict)


@runtime_checkable
class PriceProvider(Protocol):
    key: str
    label: str

    def fetch(self) -> ProviderResult: ...
