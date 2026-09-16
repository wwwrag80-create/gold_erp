#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""إصلاح التواريخ المكتوبة بأرقام عربية.

    python tools/fix_dates.py              # فحص فقط — لا يغيّر شيئاً
    python tools/fix_dates.py --apply      # الإصلاح بعد تأكيدك

**المشكلة**: التواريخ تُحفظ نصاً وتُقارَن نصاً. ورمز الرقم العربي `٠`
في يونيكود أكبر من رمز `9`، فتاريخ مثل `٢٠٢٦-٠٩-١٦` يفشل في شرط
«أصغر من أو يساوي» ويسقط من **كل** فلتر تاريخ: الكشوف والتقارير
وميزان المراجعة والإقفال. القيد موجود في القاعدة لكنه غير مرئي في أي
شاشة — بلا رسالة خطأ ولا بيانات.

**العلاج**: تحويل تلك التواريخ إلى أرقام إنجليزية. القيمة لا تتغيّر —
`٢٠٢٦-٠٩-١٦` و`2026-09-16` هما اليوم نفسه — يتغيّر تمثيلها فقط، فلا
أثر محاسبي إطلاقاً، ولا تتغيّر أي أرصدة.

**الأمان**: يأخذ نسخة كاملة من القاعدة قبل أي تعديل، ويعمل في معاملة
واحدة (إما الكل أو لا شيء)، ويتحقق بعد الإصلاح.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.dates import has_non_ascii_digits, normalize_date  # noqa: E402

# (الجدول، عمود التاريخ) — كل أعمدة التاريخ في المخطط
DATE_COLUMNS = [
    ("journal_entries", "entry_date"),
    ("invoices", "invoice_date"),
    ("tax_debit_notes", "note_date"),
    ("vouchers", "voucher_date"),
    ("melting_ops", "op_date"),
    ("fixing_ops", "op_date"),
    ("purchases", "purchase_date"),
    ("fixed_assets", "purchase_date"),
    ("shrinkage_ops", "op_date"),
    ("stocktakes", "stocktake_date"),
]


def scan(conn):
    """يجمع كل القيم المعطوبة: [(جدول, عمود, معرّف, قديم, جديد)]."""
    bad, errors = [], []
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    for tbl, col in DATE_COLUMNS:
        if tbl not in tables:
            continue
        try:
            rows = conn.execute(
                f"SELECT id, {col} v FROM {tbl} WHERE {col} IS NOT NULL")
        except Exception:
            continue
        for r in rows:
            v = r["v"]
            if not has_non_ascii_digits(v):
                continue
            try:
                bad.append((tbl, col, r["id"], v, normalize_date(v)))
            except Exception as e:
                errors.append((tbl, col, r["id"], v, str(e)[:60]))
    return bad, errors


def main():
    apply = "--apply" in sys.argv
    import config
    from database.database import db

    print("═" * 66)
    print("  فحص التواريخ المكتوبة بأرقام عربية")
    print("═" * 66)
    print(f"\n  القاعدة: {config.DB_PATH}\n")

    with db(readonly=True) as conn:
        bad, errors = scan(conn)

    if errors:
        print(f"  ⚠ {len(errors)} قيمة ليست تاريخاً صالحاً أصلاً:")
        for t, c, i, v, e in errors[:10]:
            print(f"      {t}.{c} #{i}: «{v}» — {e}")
        print("      هذه تحتاج تصحيحاً يدوياً من الشاشة.\n")

    if not bad:
        print("  ✔ لا توجد تواريخ بأرقام عربية — القاعدة سليمة.")
        return 0 if not errors else 1

    by_table = {}
    for t, c, i, old, new in bad:
        by_table.setdefault(f"{t}.{c}", []).append((i, old, new))
    print(f"  ✘ {len(bad)} تاريخاً بأرقام عربية — وهي **غير مرئية** في")
    print("     أي شاشة تُرشّح بالتاريخ:\n")
    for key, items in sorted(by_table.items()):
        print(f"     {key}: {len(items)}")
        for i, old, new in items[:3]:
            print(f"        #{i}:  {old}  ←  {new}")
        if len(items) > 3:
            print(f"        … و{len(items) - 3} غيرها")

    if not apply:
        print("\n" + "═" * 66)
        print("  هذا فحص فقط — لم يتغيّر شيء.")
        print("\n  الإصلاح يغيّر **تمثيل** التاريخ لا قيمته:")
        print("  ٢٠٢٦-٠٩-١٦ و 2026-09-16 هما اليوم نفسه.")
        print("  لا أثر محاسبي، ولا تتغيّر أي أرصدة.")
        print("\n  للتنفيذ:")
        print("      python tools/fix_dates.py --apply")
        print("═" * 66)
        return 1

    # ── نسخة أمان قبل أي تعديل ──
    src = Path(str(config.DB_PATH))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    keep = src.with_name(f"before_fixdates_{stamp}.db")
    try:
        import sqlite3
        s = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=10)
        try:
            d = sqlite3.connect(str(keep))
            try:
                s.backup(d)
            finally:
                d.close()
        finally:
            s.close()
        print(f"\n  ✔ نسخة أمان: {keep.name}")
    except Exception as e:
        print(f"\n  ✘ تعذّرت نسخة الأمان — أُلغي الإصلاح: {e}")
        return 1

    print("\n" + "!" * 66)
    print(f"  سيُصحَّح {len(bad)} تاريخاً في {len(by_table)} عموداً.")
    print("!" * 66)
    if input("\n  اكتب  نعم  للمتابعة: ").strip() not in ("نعم", "y", "yes"):
        print("  أُلغيت العملية. لم يتغيّر شيء.")
        try:
            keep.unlink()
        except Exception:
            pass
        return 0

    # معاملة واحدة: إما كل التصحيحات أو لا شيء
    n = 0
    with db() as conn:
        for tbl, col, rid, old, new in bad:
            conn.execute(f"UPDATE {tbl} SET {col}=? WHERE id=? AND {col}=?",
                         (new, rid, old))
            n += 1

    with db(readonly=True) as conn:
        left, _ = scan(conn)
    print(f"\n  ✔ صُحِّح {n} تاريخاً.")
    print("\n" + "═" * 66)
    if left:
        print(f"  ⚠ بقي {len(left)} — أعد التشغيل أو راجعها يدوياً.")
        print(f"  للتراجع انسخ: {keep.name}")
        return 1
    print("  ✔ كل التواريخ صارت بأرقام إنجليزية.")
    print("  شغّل النظام — ستظهر كل قيودك في الكشوف والتقارير.")
    print(f"  نسخة ما قبل الإصلاح محفوظة: {keep.name}")
    print("═" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
