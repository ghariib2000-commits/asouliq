"""محرك الأسعار: جلب مرة واحدة، تخزين مؤقت، وتنسيق آمن للعرض.

مبدأ التصميم: السعر يُجلب مرة واحدة لكل مزود ويُقدم لكل المستخدمين،
فلا نضرب مصدر البيانات بعدد المستخدمين.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Iterable

from app import config
from app.clock import format_cairo, now_cairo
from app.providers import get_provider
from app.providers.base import ProviderResult, Quote

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[float, ProviderResult]] = {}
_cache_lock = threading.Lock()


def get_prices(service_key: str, force: bool = False) -> ProviderResult:
    """يرجع نتيجة المزود من الذاكرة إن كانت حديثة، وإلا يجلبها."""
    provider = get_provider(service_key)
    if provider is None:
        return ProviderResult(
            provider_key=service_key,
            provider_label=service_key,
            ok=False,
            fetched_at=now_cairo(),
            unavailable_reason="خدمة غير معروفة.",
        )

    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(service_key)
        if not force and cached and cached[0] > now:
            return cached[1]

    result = provider.fetch()
    with _cache_lock:
        _cache[service_key] = (now + config.PRICE_CACHE_TTL_SECONDS, result)

    if result.ok:
        logger.info("تم جلب %s بنجاح (%d سعر)", service_key, len(result.quotes))
    else:
        logger.warning("فشل جلب %s: %s", service_key, result.error or result.unavailable_reason)
    return result


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _format_quote(quote: Quote) -> str:
    value = f"{quote.value:,.{quote.decimals}f}"
    return f"• <b>{quote.label}:</b> {value} {quote.unit}"


def format_result(result: ProviderResult) -> str:
    """يحوّل النتيجة إلى رسالة HTML واضحة المصدر والوقت."""
    header = f"<b>{result.provider_label}</b>"
    timestamp = f"<i>📅 آخر تحديث: {format_cairo(result.fetched_at)}</i>"

    if not result.ok:
        lines = [header, timestamp, ""]
        problem = result.unavailable_reason or result.error or "تعذر جلب البيانات."
        lines.append(f"⛔ <b>البيانات غير متاحة حاليًا.</b>\n{problem}")
        if result.sources:
            lines.append("")
            lines.append(f"<i>🔗 المصدر: {', '.join(result.sources)}</i>")
        return "\n".join(lines)

    lines = [header, timestamp, ""]
    lines.extend(_format_quote(quote) for quote in result.quotes)

    if result.footnotes:
        lines.append("")
        lines.extend(f"<i>{note}</i>" for note in result.footnotes)

    if result.is_estimate:
        lines.append("")
        lines.append("⚠️ <i>سعر تقديري وليس عرضًا من صاغة.</i>")

    if result.sources:
        lines.append("")
        lines.append(f"<i>🔗 المصدر: {', '.join(result.sources)}</i>")

    return "\n".join(lines)


def format_quotes(quotes: Iterable[Quote]) -> str:
    """مساعد صغير لصياغة قائمة أسعار (يُستخدم في الاختبارات والتقارير)."""
    return "\n".join(_format_quote(quote) for quote in quotes)
