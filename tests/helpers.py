"""مساعدات مشتركة للاختبارات."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.catalog import sync_assets
from app.db.migrations import upgrade


def make_db(root: Path) -> Path:
    """قاعدة اختبار كاملة الترحيل مع سجل الأصول."""
    path = root / "test.db"
    upgrade(path)
    sync_assets(path)
    return path


def temp_dir() -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory()
