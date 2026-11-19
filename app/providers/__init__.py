"""تسجيل المزودين المتاحين في سجل واحد."""

from __future__ import annotations

from app.providers.base import PriceProvider
from app.providers.egx import EgxProvider
from app.providers.fx import FxProvider
from app.providers.gold_egp import GoldEgyptProvider

PROVIDERS: dict[str, PriceProvider] = {
    provider.key: provider
    for provider in (GoldEgyptProvider(), FxProvider(), EgxProvider())
}


def get_provider(key: str) -> PriceProvider | None:
    return PROVIDERS.get(key)


def available_keys() -> tuple[str, ...]:
    return tuple(PROVIDERS)
