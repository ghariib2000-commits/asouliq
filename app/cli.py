"""أوامر تشغيل أدوات قاعدة البيانات.

الاستخدام:
    python -m app.cli backup          # نسخة احتياطية + تحقق
    python -m app.cli check           # فحص الترحيلات على نسخة
    python -m app.cli list            # عرض النسخ الموجودة
    python -m app.cli names           # تطبيق الأسماء العربية على الأسهم المسجلة
    python -m app.cli backup check    # الاثنان معًا قبل أي تعديل
"""

from __future__ import annotations

import sys

from app.db.backup import BackupError, backup_database, list_backups
from app.db.upgrade_check import MigrationCheckError, check_migration_on_copy
from app.logging_setup import configure_logging
from app.services.names import apply_arabic_names


def _backup() -> int:
    try:
        info = backup_database()
    except BackupError as exc:
        print(f"[خطأ] فشل النسخ الاحتياطي: {exc}")
        return 1
    size_kb = info.size_bytes / 1024
    print(f"[تم] نسخة احتياطية سليمة: {info.path}")
    print(f"   المستخدمون: {info.users_count} | الحجم: {size_kb:.0f} كيلوبايت")
    print("   للاستعادة: أوقف البوت، انسخ الملف إلى مسار DATABASE_PATH، شغّل البوت.")
    return 0


def _check() -> int:
    try:
        result = check_migration_on_copy()
    except MigrationCheckError as exc:
        print(f"[خطأ] الترحيل غير آمن: {exc}")
        return 1
    print(
        f"[تم] فحص الترحيل ناجح: الإصدار {result.version_before} ← {result.version_after}"
        f" | المستخدمون: {result.users_before} ← {result.users_after}"
    )
    return 0


def _list() -> int:
    backups = list_backups()
    if not backups:
        print("لا توجد نسخ احتياطية بعد.")
        return 0
    for path in backups:
        print(f"- {path.name} ({path.stat().st_size / 1024:.0f} كيلوبايت)")
    return 0


def _names() -> int:
    updated = apply_arabic_names()
    print(f"[تم] تحديث {updated} اسمًا عربيًا في سجل الأصول.")
    return 0


def main(argv: list[str]) -> int:
    # كونسول ويندوز قد يستخدم ترميزًا لا يدعم العربية، فلا نسمح بسقوط الأمر.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    configure_logging()
    commands = {"backup": _backup, "check": _check, "list": _list, "names": _names}
    selected = argv or ["backup", "check"]

    exit_code = 0
    for name in selected:
        handler = commands.get(name)
        if handler is None:
            print(f"أمر غير معروف: {name}. المتاح: {', '.join(commands)}")
            return 2
        exit_code = max(exit_code, handler())
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
