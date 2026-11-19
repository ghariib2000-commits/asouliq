"""مزود البورصة المصرية.

النسخة القديمة كانت تولد أرقامًا عشوائية وتعرضها كأنها مؤشرات حقيقية
"لحظية". هذا ممنوع تمامًا هنا: إلى أن يُربط مصدر مرخّص للبورصة المصرية
(المرحلة 5)، يرجع المزود "غير متاح" بصراحة بدون أي أرقام.
"""

from __future__ import annotations

import logging

from app.clock import now_cairo
from app.providers.base import ProviderResult

logger = logging.getLogger(__name__)


class EgxProvider:
    key = "egx"
    label = "📈 البورصة المصرية"

    def fetch(self) -> ProviderResult:
        logger.info("egx provider: لا يوجد مصدر بيانات مرخّص متصل بعد")
        return ProviderResult(
            provider_key=self.key,
            provider_label=self.label,
            ok=False,
            fetched_at=now_cairo(),
            unavailable_reason=(
                "لم يتم ربط مصدر بيانات مرخّص للبورصة المصرية حتى الآن. "
                "لن نعرض أي أرقام قبل التأكد من صحتها وحق إعادة توزيعها."
            ),
        )
