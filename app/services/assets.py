"""البحث في سجل الأصول وعرضه."""

from __future__ import annotations

from pathlib import Path

from app.db.connection import connect


def get_asset(code: str, db_path: str | Path | None = None):
    conn = connect(db_path)
    try:
        return conn.execute(
            "SELECT * FROM assets WHERE code = ? AND is_active = 1", (code.upper(),)
        ).fetchone()
    finally:
        conn.close()


def list_assets(kind: str | None = None, db_path: str | Path | None = None) -> list:
    conn = connect(db_path)
    try:
        if kind:
            rows = conn.execute(
                "SELECT * FROM assets WHERE is_active = 1 AND kind = ? ORDER BY code", (kind,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM assets WHERE is_active = 1 ORDER BY kind, code"
            ).fetchall()
        return list(rows)
    finally:
        conn.close()


def search_assets(query: str, limit: int = 8, db_path: str | Path | None = None) -> list:
    term = (query or "").strip()
    if not term:
        return []
    like = f"%{term}%"
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT * FROM assets
            WHERE is_active = 1
              AND (code LIKE ? OR name_ar LIKE ? OR name_en LIKE ? OR symbol LIKE ?)
            ORDER BY CASE WHEN code = ? THEN 0 ELSE 1 END, kind, code
            LIMIT ?
            """,
            (like, like, like, like, term.upper(), limit),
        ).fetchall()
        return list(rows)
    finally:
        conn.close()
