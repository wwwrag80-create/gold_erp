# -*- coding: utf-8 -*-
"""إدارة الفترات المالية: القيد الافتتاحي (تاريخ القطع) والإقفال السنوي.

يتيح بدء استخدام النظام في أي تاريخ (لا 1 يناير حصراً) بإدخال أرصدة
أول المدة، ثم إقفال السنة آلياً وتدوير الأرصدة للسنة الجديدة.
"""
import calendar

from models.accounts import acc_id
from services.accounting_engine import CASH_TOL, GOLD_TOL, post_entry
from services.audit import log_action

SUSPENSE = "3900"          # الأرصدة الافتتاحية للتسوية
RETAINED = "3200"          # الأرباح المحتجزة
CURRENT_PL = "3210"        # أرباح وخسائر العام الحالي
PARTNERS = "3120"          # جاري الشركاء


def create_opening_entry(conn, rows, entry_date, username, notes=""):
    """قيد افتتاحي بتاريخ القطع الذي يختاره المستخدم.

    `rows`: [{"code": "1400", "cash": 5000, "gold": 0}, ...]
    القيم الموجبة تُقيَّد مدينة (أصول)، والسالبة دائنة (خصوم/حقوق
    ملكية). أي فرق متبقٍّ يُرحَّل تلقائياً إلى حساب الأرصدة الافتتاحية
    (3900) ليخرج القيد متوازناً في البعدين.
    """
    lines, tg, tc = [], 0.0, 0.0
    for r in rows:
        code = str(r.get("code") or "").strip()
        if not code:
            continue
        cash = round(float(r.get("cash") or 0), 2)
        gold = round(float(r.get("gold") or 0), 3)
        if not cash and not gold:
            continue
        aid = acc_id(conn, code)
        ln = {"account_id": aid,
              "line_desc": r.get("desc") or "رصيد افتتاحي"}
        if gold > 0:
            ln["gold_debit"] = gold
        elif gold < 0:
            ln["gold_credit"] = -gold
        if cash > 0:
            ln["cash_debit"] = cash
        elif cash < 0:
            ln["cash_credit"] = -cash
        lines.append(ln)
        tg = round(tg + gold, 3)
        tc = round(tc + cash, 2)
    if not lines:
        raise ValueError("أدخل رصيداً واحداً على الأقل")

    # الطرف المقابل الموازن: حساب الأرصدة الافتتاحية
    susp = acc_id(conn, SUSPENSE)
    bal = {"account_id": susp, "line_desc": "الطرف الموازن للقيد الافتتاحي"}
    if abs(tg) > GOLD_TOL:
        if tg > 0:
            bal["gold_credit"] = tg
        else:
            bal["gold_debit"] = -tg
    if abs(tc) > CASH_TOL:
        if tc > 0:
            bal["cash_credit"] = tc
        else:
            bal["cash_debit"] = -tc
    if len(bal) > 2:
        lines.append(bal)

    entry_id = post_entry(
        conn, entry_date, f"قيد افتتاحي — أرصدة أول المدة ({entry_date})",
        lines, source_table="opening_entry", username=username, note=notes)
    log_action(conn, username, "create", "opening_entry", entry_id,
               f"opening {entry_date} cash={tc} gold={tg}")
    return {"entry_id": entry_id, "date": entry_date,
            "total_cash": tc, "total_gold": tg, "lines": len(lines)}


def year_end_preview(conn, year):
    """معاينة الإقفال: صافي النتيجة وأرصدة الإيراد والمصروف قبل التصفير."""
    d1, d2 = f"{year}-01-01", f"{year}-12-31"
    rows = conn.execute(
        "SELECT a.id, a.code, a.name, a.type,"
        " ROUND(SUM(l.gold_debit-l.gold_credit),3) g,"
        " ROUND(SUM(l.cash_debit-l.cash_credit),2) c"
        " FROM accounts a JOIN journal_lines l ON l.account_id=a.id"
        " JOIN journal_entries e ON e.id=l.entry_id AND e.is_deleted=0"
        " WHERE a.type IN ('revenue','expense') AND e.entry_date BETWEEN ? AND ?"
        " GROUP BY a.id HAVING (g<>0 OR c<>0)", (d1, d2)).fetchall()
    items = [{"id": r["id"], "code": r["code"], "name": r["name"],
              "type": r["type"], "gold": r["g"] or 0.0, "cash": r["c"] or 0.0}
             for r in rows]
    # الإيراد دائن (سالب) والمصروف مدين (موجب) ⇒ الربح = -(مجموعهما)
    net_c = round(-sum(i["cash"] for i in items), 2)
    net_g = round(-sum(i["gold"] for i in items), 3)
    return {"year": year, "items": items, "net_cash": net_c, "net_gold": net_g}


def run_year_end_closing(conn, year, username, to_partners=False,
                         open_next_year=False):
    """الإقفال السنوي الآلي:

    1. تصفير كل حسابات الإيرادات والمصروفات بقيد إقفال بتاريخ 31-12.
    2. ترحيل صافي الربح/الخسارة إلى الأرباح المحتجزة (أو جاري الشركاء).
    3. (اختياري) قيد تدوير صريح للسنة الجديدة.

    **ملاحظة محاسبية مهمة**: هذا النظام يستخدم دفتر أستاذ مستمراً، فأرصدة
    الميزانية (الأصول والخصوم وحقوق الملكية) تنتقل للسنة الجديدة تلقائياً
    بحكم استمرارية الدفتر — ولا تحتاج قيد تدوير. لذلك `open_next_year`
    معطَّل افتراضياً: تفعيله يُنشئ قيدَي إقفال وافتتاح متعاكسين (صافيهما
    صفر) لمن يريد فصلاً دفترياً صريحاً بين السنتين دون مضاعفة الأرصدة.
    """
    prev = year_end_preview(conn, year)
    if not prev["items"]:
        raise ValueError(f"لا توجد حركات إيراد أو مصروف في سنة {year}")
    last_day = f"{year}-12-31"

    # (1) قيد الإقفال: عكس رصيد كل حساب نتيجة
    lines = []
    for it in prev["items"]:
        ln = {"account_id": it["id"],
              "line_desc": f"إقفال {it['name']} لسنة {year}"}
        if it["gold"] > 0:
            ln["gold_credit"] = it["gold"]
        elif it["gold"] < 0:
            ln["gold_debit"] = -it["gold"]
        if it["cash"] > 0:
            ln["cash_credit"] = it["cash"]
        elif it["cash"] < 0:
            ln["cash_debit"] = -it["cash"]
        lines.append(ln)

    target_code = PARTNERS if to_partners else RETAINED
    target = acc_id(conn, target_code)
    res = {"account_id": target,
           "line_desc": f"ترحيل صافي نتيجة سنة {year}"}
    # الربح (net موجب) يُقيَّد دائناً في حقوق الملكية
    if abs(prev["net_gold"]) > GOLD_TOL:
        if prev["net_gold"] > 0:
            res["gold_credit"] = prev["net_gold"]
        else:
            res["gold_debit"] = -prev["net_gold"]
    if abs(prev["net_cash"]) > CASH_TOL:
        if prev["net_cash"] > 0:
            res["cash_credit"] = prev["net_cash"]
        else:
            res["cash_debit"] = -prev["net_cash"]
    if len(res) > 2:
        lines.append(res)

    close_entry = post_entry(
        conn, last_day,
        f"قيد الإقفال السنوي {year} — تصفير النتيجة وترحيل الصافي",
        lines, source_table="year_close", username=username)

    # (2) تدوير أرصدة الميزانية كقيد افتتاحي للسنة التالية
    opening_entry = None
    if open_next_year:
        rows = conn.execute(
            "SELECT a.id, a.code,"
            " ROUND(SUM(l.gold_debit-l.gold_credit),3) g,"
            " ROUND(SUM(l.cash_debit-l.cash_credit),2) c"
            " FROM accounts a JOIN journal_lines l ON l.account_id=a.id"
            " JOIN journal_entries e ON e.id=l.entry_id AND e.is_deleted=0"
            " WHERE a.type IN ('asset','liability','equity')"
            " AND e.entry_date<=? GROUP BY a.id HAVING (g<>0 OR c<>0)",
            (last_day,)).fetchall()
        op_lines = []
        for r in rows:
            ln = {"account_id": r["id"],
                  "line_desc": f"رصيد مُدوَّر من سنة {year}"}
            g, c = r["g"] or 0.0, r["c"] or 0.0
            if g > 0:
                ln["gold_debit"] = g
            elif g < 0:
                ln["gold_credit"] = -g
            if c > 0:
                ln["cash_debit"] = c
            elif c < 0:
                ln["cash_credit"] = -c
            op_lines.append(ln)
        if op_lines:
            # قيد إغلاق دفتري بتاريخ 31-12 يعكس الأرصدة (يصفّر الدفتر)
            rev_lines = []
            for ln in op_lines:
                r = {"account_id": ln["account_id"],
                     "line_desc": f"إغلاق دفتري لسنة {year}"}
                if "gold_debit" in ln:
                    r["gold_credit"] = ln["gold_debit"]
                if "gold_credit" in ln:
                    r["gold_debit"] = ln["gold_credit"]
                if "cash_debit" in ln:
                    r["cash_credit"] = ln["cash_debit"]
                if "cash_credit" in ln:
                    r["cash_debit"] = ln["cash_credit"]
                rev_lines.append(r)
            post_entry(
                conn, last_day,
                f"إغلاق دفتري لأرصدة الميزانية — سنة {year}",
                rev_lines, source_table="year_close", username=username)
            # ثم قيد افتتاحي بنفس الأرصدة في 01-01 من السنة الجديدة
            opening_entry = post_entry(
                conn, f"{year + 1}-01-01",
                f"قيد افتتاحي آلي لسنة {year + 1} — تدوير أرصدة الميزانية",
                op_lines, source_table="year_open", username=username)

    log_action(conn, username, "create", "year_close", close_entry,
               f"closing {year} net_cash={prev['net_cash']}")
    return {"year": year, "close_entry": close_entry,
            "opening_entry": opening_entry,
            "net_cash": prev["net_cash"], "net_gold": prev["net_gold"],
            "closed_accounts": len(prev["items"]),
            "target": target_code}
