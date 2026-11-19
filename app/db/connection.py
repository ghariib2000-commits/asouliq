"""إنشاء اتصالات SQLite بإعدادات آمنة.

WAL يسمح بقراءة وكتابة متزامنة (مهم عند تشغيل محرك التنبيهات
جنب البوت)، وforeign_keys يمنع بيانات يتيمة، وtimeout يمنع
خطأ "database is locked" الفوري.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app import config


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else config.DATABASE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextmanager
def session(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """اتصال يُغلق تلقائيًا، ويُرجع التغييرات عند نجاح الكتلة فقط."""
    conn = connect(db_path)
    try:
        with conn:  # commit / rollback تلقائي
            yield conn
    finally:
        conn.close()
