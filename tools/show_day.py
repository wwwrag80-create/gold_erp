#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ماذا حدث في يوم معيّن؟ — عرض سريع لكل مستنداته.

    python tools/show_day.py 2026-11-01      # يوم بعينه
    python tools/show_day.py --future        # كل ما تاريخه بعد اليوم
    python tools/show_day.py --outliers      # التواريخ الشاذة (مستقبلية أو قديمة جداً)

يعرض القيود بأرقام سنداتها وبيانها وأطرافها بالمبالغ، ومعها الفواتير
والسندات والمستندات الأخرى في ذلك اليوم — فيُعرف مصدر أي حركة غريبة
بلا تنقّل بين الشاشات.

قراءة فقط — لا يعدّل شيئاً.
"""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def pick_db():
    """قاعدة المصنع صاحبة أكبر عدد قيود (انظر tools/fix_dates.py)."""
    from tools.fix_dates import pick_database
    return pick_database()


def _w(v, d=2):
    return f"{v:,.{d}f}" if v else "—"


def show_entries(conn, d1, d2, label):
    rows = conn.execute(
        "SELECT id, doc_no, entry_date, description, user_note,"
        " source_table, source_id, created_by, created_at"
        " FROM journal_entries WHERE is_deleted=0"
        " AND entry_date>=? AND entry_date<=?"
        " ORDER BY entry_date, id", (d1, d2)).fetchall()
    if not rows:
        print(f"  لا توجد قيود {label}.")
        return 0
    print(f"  {len(rows)} قيداً {label}:\n")
    for e in rows:
        print(f"  ── {e['doc_no'] or '#' + str(e['id'])}"
              f"   {e['entry_date']}   [{e['source_table'] or 'يدوي'}]")
        desc = (e["description"] or "").strip()
        note = (e["user_note"] or "").strip()
        if desc:
            print(f"     الوصف : {desc}")
        if note:
            print(f"     البيان : {note}")
        who = e["created_by"] or "—"
        print(f"     أنشأه  : {who}   في {e['created_at'] or '—'}")
        for l in conn.execute(
                "SELECT a.code, a.name, l.gold_debit gd, l.gold_credit gc,"
                " l.cash_debit cd, l.cash_credit cc, l.line_desc"
                " FROM journal_lines l JOIN accounts a ON a.id=l.account_id"
                " WHERE l.entry_id=? ORDER BY l.id", (e["id"],)):
            parts = []
            if l["gd"]:
                parts.append(f"مدين ذهب {_w(l['gd'], 3)}")
            if l["gc"]:
                parts.append(f"دائن ذهب {_w(l['gc'], 3)}")
            if l["cd"]:
                parts.append(f"مدين نقد {_w(l['cd'])}")
            if l["cc"]:
                parts.append(f"دائن نقد {_w(l['cc'])}")
            print(f"        {l['code']:<6} {l['name'][:30]:<32}"
                  f" {' · '.join(parts)}")
        print()
    return len(rows)


def show_docs(conn, d1, d2):
    """المستندات المصدرية في المدى نفسها."""
    specs = [
        ("invoices", "invoice_date", "invoice_no", "فاتورة"),
        ("vouchers", "voucher_date", "voucher_no", "سند"),
        ("purchases", "purchase_date", None, "مشتريات"),
        ("melting_ops", "op_date", None, "صهر"),
        ("fixing_ops", "op_date", None, "تسكير"),
    ]
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    any_found = False
    for tbl, datecol, nocol, label in specs:
        if tbl not in tables:
            continue
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({tbl})")}
        if datecol not in cols:
            continue
        sel = f"id, {datecol} d"
        if nocol and nocol in cols:
            sel += f", {nocol} no"
        try:
            rows = conn.execute(
                f"SELECT {sel} FROM {tbl} WHERE {datecol}>=? AND {datecol}<=?"
                + (" AND is_deleted=0" if "is_deleted" in cols else "")
                + f" ORDER BY {datecol}, id", (d1, d2)).fetchall()
        except Exception:
            continue
        for r in rows:
            any_found = True
            num = (r["no"] if nocol and nocol in cols else None) or f"#{r['id']}"
            print(f"  · {label}: {num}   {r['d']}")
    if any_found:
        print()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")
            and not a == "--db" and "=" not in a]
    today = date.today().isoformat()

    import config
    target, why = pick_db()
    config.DB_PATH = target
    from database.database import db

    print("═" * 68)
    print(f"  القاعدة: {target}")
    print(f"  ({why})")
    print("═" * 68 + "\n")

    with db(readonly=True) as conn:
        if "--future" in sys.argv:
            print(f"■ كل ما تاريخه بعد اليوم ({today})\n")
            n = show_entries(conn, _after(today), "9999-12-31",
                             "بتاريخ مستقبلي")
            show_docs(conn, _after(today), "9999-12-31")
            return 0 if n == 0 else 0

        if "--outliers" in sys.argv:
            print("■ التواريخ الشاذة\n")
            r = conn.execute(
                "SELECT MIN(entry_date) a, MAX(entry_date) b,"
                " COUNT(*) c FROM journal_entries"
                " WHERE is_deleted=0").fetchone()
            print(f"  مدى التواريخ: {r['a']}  ←→  {r['b']}"
                  f"   ({r['c']:,} قيد)\n")
            rows = conn.execute(
                "SELECT entry_date d, COUNT(*) c FROM journal_entries"
                " WHERE is_deleted=0 AND (entry_date>? OR entry_date<'2000-01-01')"
                " GROUP BY entry_date ORDER BY entry_date", (today,)).fetchall()
            if not rows:
                print("  ✔ لا توجد تواريخ مستقبلية ولا قديمة بشكل غير منطقي.")
                return 0
            print("  ⚠ تواريخ تستحق المراجعة:")
            for r in rows:
                print(f"     {r['d']}  —  {r['c']} قيد")
            print(f"\n  لعرض أيٍّ منها:  python tools/show_day.py {rows[0]['d']}")
            return 0

        if not args:
            print("  حدّد تاريخاً، مثلاً:")
            print("      python tools/show_day.py 2026-11-01")
            print("      python tools/show_day.py --outliers")
            print("      python tools/show_day.py --future")
            return 1

        from services.dates import normalize_date
        try:
            d = normalize_date(args[0])
        except Exception as e:
            print(f"  ✘ {e}")
            return 1
        print(f"■ حركات يوم {d}\n")
        show_docs(conn, d, d)
        show_entries(conn, d, d, f"في {d}")
    return 0


def _after(d):
    """اليوم التالي — لاستبعاد اليوم نفسه من «المستقبلي»."""
    from datetime import date as _d, timedelta
    return (_d.fromisoformat(d) + timedelta(days=1)).isoformat()


if __name__ == "__main__":
    sys.exit(main())
