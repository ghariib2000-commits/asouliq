"""محرك ترحيلات مُصدَّر بإصدارات (Schema Migrations).

القواعد المتبعة:
- كل ترحيل له رقم إصدار ثابت ولا يُعدَّل بعد تطبيقه على قاعدة حقيقية.
- يُسجَّل كل ترحيل في جدول schema_migrations.
- لا نستخدم DROP TABLE / DROP COLUMN.
- أخطاء الترحيل تظهر كأخطاء ولا تُكتم.
- يشغَّل الترحيل داخل Transaction فيصبح كل ترحيل إما كاملًا أو لا شيء.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from app.db.connection import connect, session

logger = logging.getLogger(__name__)

CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL,
    applied_at TEXT    NOT NULL DEFAULT (datetime('now'))
)
"""

# أعمدة جدول users التي يجب أن توجد. أوصاف ALTER TABLE بسيطة
# لأن SQLite لا يسمح بإضافة عمود بقيمة افتراضية غير ثابتة.
USER_COLUMN_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("full_name", "TEXT"),
    ("consent", "INTEGER NOT NULL DEFAULT 0"),
    ("auto_updates", "INTEGER NOT NULL DEFAULT 0"),
    ("interests", "TEXT DEFAULT 'gold,egx'"),
    ("joined_at", "TEXT"),
)


def _create_users_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            telegram_id  INTEGER PRIMARY KEY,
            full_name    TEXT,
            consent      INTEGER NOT NULL DEFAULT 0,
            auto_updates INTEGER NOT NULL DEFAULT 0,
            interests    TEXT DEFAULT 'gold,egx',
            joined_at    TEXT DEFAULT (datetime('now'))
        )
        """
    )


def _ensure_user_columns(conn: sqlite3.Connection) -> None:
    """يضيف الأعمدة الناقصة فقط، ويسجل كل عمود يضيفه.

    هذا هو الإصلاح الجذري لخطأ no such column: consent — القاعدة القديمة
    كانت بدون هذا العمود، وبدلًا من كتم كل خطأ نسجل ما حدث بالضبط.
    """
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    for name, definition in USER_COLUMN_DEFINITIONS:
        if name in existing:
            continue
        conn.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
        logger.info("migration 001: أضيف العمود الناقص users.%s", name)


def _migration_001_initial(conn: sqlite3.Connection) -> None:
    _create_users_table(conn)
    _ensure_user_columns(conn)


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


def _migration_002_assets_and_watchlist(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS assets (
            code         TEXT PRIMARY KEY,
            kind         TEXT NOT NULL,
            name_ar      TEXT NOT NULL,
            name_en      TEXT,
            symbol       TEXT,
            sector       TEXT,
            quote_unit   INTEGER NOT NULL DEFAULT 1,
            unit         TEXT NOT NULL DEFAULT 'جنيه',
            provider_key TEXT NOT NULL DEFAULT '',
            is_active    INTEGER NOT NULL DEFAULT 1,
            created_at   TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_assets_kind ON assets(kind)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS latest_prices (
            asset_code  TEXT PRIMARY KEY REFERENCES assets(code),
            price       REAL NOT NULL,
            currency    TEXT NOT NULL DEFAULT 'EGP',
            source      TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            fetched_at  TEXT NOT NULL,
            provider_key TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS watchlist (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
            asset_code  TEXT    NOT NULL REFERENCES assets(code),
            created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
            UNIQUE (telegram_id, asset_code)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(telegram_id)")


def _migration_003_alerts(conn: sqlite3.Connection) -> None:
    # عمودان لتتبع السعر السابق (أساس تنبيهات النسبة المئوية).
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(latest_prices)")}
    if "prev_price" not in existing:
        conn.execute("ALTER TABLE latest_prices ADD COLUMN prev_price REAL")
    if "prev_fetched_at" not in existing:
        conn.execute("ALTER TABLE latest_prices ADD COLUMN prev_fetched_at TEXT")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_rules (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id       INTEGER NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
            asset_code        TEXT    NOT NULL REFERENCES assets(code),
            rule_type         TEXT    NOT NULL CHECK (rule_type IN
                                  ('price_above','price_below','pct_change_up','pct_change_down')),
            threshold         REAL    NOT NULL,
            is_active         INTEGER NOT NULL DEFAULT 1,
            last_triggered_at TEXT,
            created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
            UNIQUE (telegram_id, asset_code, rule_type, threshold)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_alert_rules_asset ON alert_rules(asset_code, is_active)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_alert_rules_user ON alert_rules(telegram_id)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notification_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_id     INTEGER REFERENCES alert_rules(id) ON DELETE CASCADE,
            telegram_id INTEGER NOT NULL,
            asset_code  TEXT    NOT NULL,
            message     TEXT    NOT NULL,
            price       REAL,
            status      TEXT    NOT NULL DEFAULT 'pending',
            error       TEXT,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_notification_rule ON notification_log(rule_id, created_at)"
    )


def _migration_004_report_settings(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS report_settings (
            telegram_id  INTEGER PRIMARY KEY REFERENCES users(telegram_id) ON DELETE CASCADE,
            enabled      INTEGER NOT NULL DEFAULT 1,
            hour         INTEGER NOT NULL DEFAULT 9 CHECK (hour BETWEEN 0 AND 23),
            minute       INTEGER NOT NULL DEFAULT 0 CHECK (minute BETWEEN 0 AND 59),
            last_sent_on TEXT,
            updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_report_due ON report_settings(enabled, hour, minute)"
    )


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "initial_users_and_migrations_table", _migration_001_initial),
    Migration(2, "assets_latest_prices_watchlist", _migration_002_assets_and_watchlist),
    Migration(3, "alert_rules_and_notification_log", _migration_003_alerts),
    Migration(4, "report_settings", _migration_004_report_settings),
)


def upgrade(
    db_path: str | Path | None = None,
    migrations: Sequence[Migration] = MIGRATIONS,
) -> list[int]:
    """يطبق الترحيلات غير المطبقة، ويرجع أرقام الإصدارات التي طُبقت الآن."""
    applied_now: list[int] = []
    with session(db_path) as conn:
        conn.execute(CREATE_MIGRATIONS_TABLE)
        applied = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}
        for migration in migrations:
            if migration.version in applied:
                continue
            with conn:  # معاملة مستقلة لكل ترحيل
                migration.apply(conn)
                conn.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                    (migration.version, migration.name),
                )
            logger.info("تم تطبيق الترحيل %s (%s)", migration.version, migration.name)
            applied_now.append(migration.version)
    return applied_now


def current_version(db_path: str | Path | None = None) -> int:
    """أعلى إصدار مُطبق، أو 0 لو القاعدة جديدة."""
    conn = connect(db_path)
    try:
        row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
        return int(row["v"] or 0)
    finally:
        conn.close()
