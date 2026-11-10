# -*- coding: utf-8 -*-
"""مستنداتٌ رُحّلت بتاريخٍ غير يوم تسجيلها (5.2.7) — لشاشة «سلامة السجل».

فاتورةٌ سُجّلت اليوم بتاريخ أمس أو الشهر الماضي قد تكون مقصودة (مستندٌ تأخّر
إدخاله) وقد تكون خطأً أو تلاعباً بالأرصدة القديمة. الترحيل بها صار يسأل
أولاً (تنبيه التاريخ)، وهنا يُرى كل ما رُحّل كذلك: تاريخ المستند، ويوم
تسجيله في النظام، والفرق بينهما، ومن سجّله.

يوم التسجيل: وقت إنشاء المستند نفسه (الفاتورة · السند) — فتعديلها لاحقاً
لا يجعلها «مغايرة» — وإلا فوقت إنشاء القيد. قراءةٌ محضة.
"""
import datetime as _dt

# أرصدةٌ افتتاحية وإقفالٌ وتسويات نهاية الفترة: تاريخها يومُ القطع أو آخر
# الفترة بطبيعتها — تُعرض بخيارٍ صريح لا افتراضاً
SYSTEM_SOURCES = ("opening_entry", "entities", "year_close", "year_open",
                  "accrual", "accrual_rev", "depreciation", "prepaid_amort")

_SQL = """
SELECT * FROM (
  SELECT e.id eid, e.entry_date d, e.source_table st, e.source_id sid,
         e.created_by who, e.description dsc, e.user_note un,
         COALESCE(CASE e.source_table
           WHEN 'invoices' THEN (SELECT i.created_at FROM invoices i
                                  WHERE i.id=e.source_id)
           WHEN 'vouchers' THEN (SELECT v.created_at FROM vouchers v
                                  WHERE v.id=e.source_id)
         END, e.created_at) reg
    FROM journal_entries e
   WHERE e.is_deleted=0)
 WHERE reg IS NOT NULL AND substr(reg,1,10)<>d
"""


def _days(a, b):
    try:
        return (_dt.date.fromisoformat(str(a)[:10])
                - _dt.date.fromisoformat(str(b)[:10])).days
    except ValueError:
        return 0


def drifted(conn, reg_from=None, reg_to=None, include_system=False,
            limit=3000):
    """[{eid,date,registered,days,op,doc_no,party,gold,cash,who,desc,src,
    sid}] — الأحدث تسجيلاً أولاً. `days` سالبٌ لمستندٍ بتاريخٍ سابق ليوم
    تسجيله (الأغلب)، وموجبٌ لتاريخٍ لاحق."""
    from models import journal
    sql, args = _SQL, []
    if reg_from:
        sql += " AND substr(reg,1,10)>=?"
        args.append(str(reg_from)[:10])
    if reg_to:
        sql += " AND substr(reg,1,10)<=?"
        args.append(str(reg_to)[:10])
    if not include_system:
        sql += (" AND COALESCE(st,'') NOT IN ("
                + ",".join("?" * len(SYSTEM_SOURCES)) + ")")
        args += list(SYSTEM_SOURCES)
    sql += " ORDER BY reg DESC, eid DESC LIMIT ?"
    args.append(int(limit))
    cache, out = {}, []
    for r in conn.execute(sql, args).fetchall():
        doc_no, label = journal._doc_info(conn, r["st"], r["sid"], cache)
        t = conn.execute(
            "SELECT COALESCE(SUM(gold_debit),0) g, COALESCE(SUM(cash_debit),0)"
            " c FROM journal_lines WHERE entry_id=?", (r["eid"],)).fetchone()
        party = ""
        if r["st"] in ("invoices", "vouchers") and r["sid"]:
            p = conn.execute(
                f"SELECT e.name FROM {r['st']} x LEFT JOIN entities e"
                " ON e.id=x.customer_id WHERE x.id=?",
                (r["sid"],)).fetchone()
            party = (p["name"] if p else "") or ""
        out.append({
            "eid": r["eid"], "date": r["d"], "registered": r["reg"] or "",
            "days": _days(r["d"], r["reg"]), "op": label,
            "doc_no": doc_no or f"#{r['eid']}", "party": party,
            "gold": round(float(t["g"] or 0), 3),
            "cash": round(float(t["c"] or 0), 2),
            "who": r["who"] or "",
            "desc": (r["un"] or "").strip() or (r["dsc"] or "").strip(),
            "src": r["st"], "sid": r["sid"]})
    return out


def days_text(n):
    """«قبل يوم تسجيله بـ3 أيام» · «بعده بيومين»."""
    k = abs(int(n))
    span = ("يومٌ واحد" if k == 1 else "يومان" if k == 2
            else f"{k} أيام" if 3 <= k <= 10 else f"{k} يوماً")
    return (f"أقدم بـ{span}" if n < 0 else f"أحدث بـ{span}") if n else "—"
