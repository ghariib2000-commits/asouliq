"""إعداد السجلات (Logging).

ملاحظة أمنية: لا نسجل قيم الـToken أو أي مفتاح. نسجل الأحداث فقط.
"""

from __future__ import annotations

import logging
import sys

from app import config

_CONFIGURED = False


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))
    root.handlers.clear()
    root.addHandler(handler)

    # مكتبة Telegram مزعجة في وضع INFO، ونريد أخطاءها فقط.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    _CONFIGURED = True
