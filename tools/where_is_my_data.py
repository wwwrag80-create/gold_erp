#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""أين بيانات النظام؟ — تشخيص قبل التشغيل.

    python tools/where_is_my_data.py

يُظهر المجلد الذي سيقرأ منه النظام ويكتب فيه، **ولماذا اختاره**، ويعدّ
ما فيه من قيود وفواتير. يُشغَّل قبل أول إقلاع لنسخة جديدة من الكود
فيُطمئنك أنها ستفتح محاسبتك القائمة لا قاعدة فارغة.

لا يعدّل شيئاً — قراءة فقط.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config                                    # noqa: E402
from core.config import DATA_DIR_ENV, _has_database, _persistent_dir  # noqa: E402


def line(k, v):
    print(f"  {k:<26} {v}")


def main():
    print("═" * 60)
    print("  أين بيانات النظام؟")
    print("═" * 60)

    base = Path(str(config.BASE_DIR))
    db = Path(str(config.DB_PATH))

    # ── لماذا اختير هذا المجلد ──
    override = (os.environ.get(DATA_DIR_ENV) or "").strip()
    if override:
        why = f"تجاوز صريح عبر متغيّر البيئة {DATA_DIR_ENV}"
    elif getattr(sys, "frozen", False):
        why = "نسخة exe — المجلد الدائم على القرص"
    elif _has_database(ROOT):
        why = "بيانات موجودة بجوار المشروع"
    else:
        try:
            p = _persistent_dir()
        except Exception:
            p = None
        if p and _has_database(p):
            why = "بيانات المصنع الدائمة على الجهاز (بلا نقل يدوي)"
        else:
            why = "لا بيانات في أي مكان — تثبيت جديد"

    line("مجلد العمل:", base)
    line("السبب:", why)
    line("ملف القاعدة:", db)
    line("موجود؟", "نعم" if db.exists() else "لا — ستُنشأ قاعدة جديدة")
    if db.exists():
        line("الحجم:", f"{db.stat().st_size / 1048576:.1f} ميجابايت")

    # ── المسارات الأخرى ──
    print("\n" + "─" * 60)
    try:
        from services import storage
        i = storage.info()
        line("مجلد النسخ:", i["backup_dir"])
        line("عدد النسخ:", i["backups"])
        if str(i["data_dir"]) != str(base):
            print("\n  ⚠ مجلد النسخ الاحتياطي يتبع مساراً آخر:")
            line("   storage.data_dir:", i["data_dir"])
    except Exception as e:
        line("تعذّر قراءة مسارات النسخ:", f"{type(e).__name__}: {e}")

    # ── ماذا في القاعدة فعلاً ──
    print("\n" + "─" * 60)
    if not db.exists():
        print("  القاعدة غير موجودة بعد.")
    else:
        try:
            from database.database import db as _db
            with _db(readonly=True) as conn:
                for label, sql in (
                        ("القيود", "SELECT COUNT(*) c FROM journal_entries"
                                   " WHERE is_deleted=0"),
                        ("الفواتير", "SELECT COUNT(*) c FROM invoices"
                                     " WHERE is_deleted=0"),
                        ("الجهات", "SELECT COUNT(*) c FROM entities"
                                   " WHERE is_deleted=0"),
                        ("الأطقم", "SELECT COUNT(*) c FROM work_orders"
                                   " WHERE is_deleted=0"),
                        ("الحسابات", "SELECT COUNT(*) c FROM accounts"),
                ):
                    try:
                        line(f"{label}:", f"{conn.execute(sql).fetchone()['c']:,}")
                    except Exception:
                        line(f"{label}:", "—")
                r = conn.execute(
                    "SELECT MIN(entry_date) a, MAX(entry_date) b"
                    " FROM journal_entries WHERE is_deleted=0").fetchone()
                if r and r["a"]:
                    line("مدى التواريخ:", f"{r['a']}  ←→  {r['b']}")
        except Exception as e:
            print(f"  تعذّرت القراءة: {type(e).__name__}: {e}")

    print("\n" + "═" * 60)
    print(f"  لتثبيت مجلد آخر:  set {DATA_DIR_ENV}=D:\\TreeSoft_System\\Data")
    print("═" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
