#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""استرجاع محاسبتك إلى مجلد المصنع النشط.

    python tools/adopt_data.py                 # عرض فقط — لا يغيّر شيئاً
    python tools/adopt_data.py --apply         # ينفّذ بعد تأكيدك

**متى تحتاجها**: مسار قاعدة البيانات يتبع هوية المصنع القادمة من حساب
الدخول السحابي. فلو تغيّرت الهوية (إعادة إنشاء الحساب، أو تبديل مفاتيح
السحابة) فتح النظام مجلداً جديداً فارغاً، وبقيت محاسبتك سليمة تحت
مجلد الهوية السابقة. هذه الأداة تنقلها إلى المجلد النشط.

**الأمان**: تأخذ نسخة من الملف الهدف قبل استبداله، وتتحقق من الأعداد
بعد النسخ. ولا تحذف الأصل أبداً.
"""
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

COUNTS = (("قيود", "journal_entries"), ("فواتير", "invoices"),
          ("جهات", "entities"), ("أطقم", "work_orders"))


def counts_of(path):
    """أعداد السجلات الحيّة — أو None إن لم تكن قاعدة هذا النظام."""
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3)
    except Exception:
        return None
    try:
        con.row_factory = sqlite3.Row
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "journal_entries" not in tables:
            return None
        out = {}
        for label, tbl in COUNTS:
            if tbl in tables:
                try:
                    out[label] = con.execute(
                        f"SELECT COUNT(*) c FROM {tbl}"
                        " WHERE is_deleted=0").fetchone()["c"]
                except Exception:
                    out[label] = 0
        return out
    except Exception:
        return None
    finally:
        try:
            con.close()
        except Exception:
            pass


def fmt(c):
    return " · ".join(f"{k}: {v:,}" for k, v in (c or {}).items())


def tenants_root():
    import config
    return Path(str(config.BASE_DIR)) / "data" / "tenants"


def scan_tenants():
    """كل مجلدات المصانع مرتبةً بالأحدث تعديلاً."""
    root = tenants_root()
    out = []
    if not root.exists():
        return out
    for d in root.iterdir():
        f = d / "gold_erp.db"
        if not f.is_file():
            continue
        c = counts_of(f)
        out.append({
            "id": d.name, "path": f, "counts": c or {},
            "entries": (c or {}).get("قيود", 0),
            "mtime": f.stat().st_mtime,
            "size_mb": round(f.stat().st_size / 1048576, 2)})
    out.sort(key=lambda r: -r["mtime"])
    return out


def main():
    apply = "--apply" in sys.argv
    print("═" * 66)
    print("  استرجاع المحاسبة إلى مجلد المصنع النشط")
    print("═" * 66)

    rows = scan_tenants()
    if not rows:
        print("\n  لا توجد مجلدات مصانع في:", tenants_root())
        print("  شغّل أولاً:  python tools/find_my_data.py")
        return 1

    print(f"\n  مجلد المصانع: {tenants_root()}\n")
    print("  المصانع على هذا الجهاز (الأحدث استعمالاً أولاً):")
    for i, r in enumerate(rows, 1):
        when = datetime.fromtimestamp(r["mtime"]).strftime("%Y-%m-%d %H:%M")
        tag = "★ فيه بيانات" if r["entries"] else "  فارغ"
        print(f"\n   [{i}] {r['id']}   {tag}")
        print(f"       آخر استعمال: {when}   ({r['size_mb']} م.ب)")
        print(f"       {fmt(r['counts']) or 'لا سجلات'}")

    src = max(rows, key=lambda r: r["entries"])
    if not src["entries"]:
        print("\n  ✘ لا يوجد مجلد مصنع فيه قيود. استعمل نسخة احتياطية يدوية")
        print("    (ملف ينتهي بـ _manual) عبر شاشة الصيانة في النظام.")
        return 1

    # المصنع النشط = الأحدث استعمالاً، بشرط ألا يكون هو المصدر نفسه
    target = None
    for r in rows:
        if r["id"] != src["id"]:
            target = r
            break

    print("\n" + "─" * 66)
    print(f"  المصدر  (بياناتك):  {src['id']}")
    print(f"                      {fmt(src['counts'])}")
    if target is None:
        print("\n  ✔ لا يوجد مصنع آخر — بياناتك في المجلد الوحيد.")
        print("    إن كان النظام لا يعرضها فالمشكلة في هوية الدخول لا في")
        print("    الملفات. أخبرني بذلك.")
        return 0
    print(f"\n  الهدف (النشط الآن): {target['id']}")
    print(f"                      {fmt(target['counts']) or 'فارغ'}")
    print(f"                      آخر استعمال: "
          f"{datetime.fromtimestamp(target['mtime']):%Y-%m-%d %H:%M}")

    if not apply:
        print("\n" + "═" * 66)
        print("  هذا عرض فقط — لم يتغيّر شيء.")
        print("\n  تأكّد أن «الهدف» أعلاه هو المصنع الذي يفتحه نظامك،")
        print("  بأن تسجّل الدخول مرة ثم تعيد تشغيل هذه الأداة: المصنع")
        print("  النشط هو الأحدث استعمالاً.")
        print("\n  للتنفيذ:")
        print("      python tools/adopt_data.py --apply")
        print("═" * 66)
        return 0

    print("\n" + "!" * 66)
    print(f"  سيُستبدل ملف المصنع {target['id']} ببياناتك من {src['id']}.")
    print("  تُؤخذ نسخة من الملف الحالي أولاً، والأصل لا يُحذف.")
    print("!" * 66)
    ans = input("\n  اكتب  نعم  للمتابعة: ").strip()
    if ans not in ("نعم", "نعم ", "y", "yes"):
        print("  أُلغيت العملية. لم يتغيّر شيء.")
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    keep = target["path"].with_name(f"before_adopt_{stamp}.db")
    try:
        shutil.copy2(target["path"], keep)
        print(f"\n  ✔ حُفظ الملف السابق: {keep.name}")
    except Exception as e:
        print(f"  ✘ تعذّر حفظ نسخة الهدف: {e}")
        return 1

    # ملفات WAL/SHM القديمة تُزال وإلا خلطت المحتوى القديم بالجديد
    for ext in ("-wal", "-shm"):
        try:
            Path(str(target["path"]) + ext).unlink(missing_ok=True)
        except Exception:
            pass
    try:
        # نسخ عبر واجهة SQLite: يضمّ محتوى WAL المصدر ولا ينقل ملفاً نصفه
        s = sqlite3.connect(f"file:{src['path']}?mode=ro", uri=True, timeout=10)
        try:
            d = sqlite3.connect(str(target["path"]))
            try:
                s.backup(d)
            finally:
                d.close()
        finally:
            s.close()
    except Exception as e:
        print(f"  ✘ فشل النسخ: {e}")
        print(f"     الملف السابق سليم في: {keep}")
        return 1

    after = counts_of(target["path"])
    print(f"  ✔ نُسخت البيانات.")
    print(f"\n  التحقق بعد النسخ: {fmt(after)}")
    ok = after and after.get("قيود", 0) == src["entries"]
    print("\n" + "═" * 66)
    if ok:
        print("  ✔ تمّ. شغّل النظام — ستجد محاسبتك كاملة.")
        print(f"  الأصل باقٍ سليماً في: {src['path']}")
    else:
        print("  ✘ الأعداد لا تطابق المصدر — راجع قبل الاعتماد.")
        print(f"  لاسترجاع الحالة السابقة انسخ: {keep.name}")
    print("═" * 66)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
