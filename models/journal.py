# -*- coding: utf-8 -*-
"""القيود اليدوية (افتتاحية/تسوية) وقوائم القيود وكشوف الحسابات."""
from services.accounting_engine import post_entry


def manual_entry(conn, entry_date, description, lines, username):
    """قيد يومية يدوي — نص المستخدم هنا هو البيان الحقيقي."""
    if not description.strip():
        raise ValueError("أدخل بيان القيد")
    return post_entry(conn, entry_date, description.strip(), lines,
                      source_table="manual", username=username,
                      note=description.strip())


def list_entries(conn, limit=300):
    return conn.execute(
        "SELECT e.id, e.entry_date, e.description, e.source_table, e.source_id,"
        " e.is_deleted, e.created_by,"
        " COALESCE(SUM(l.gold_debit),0) gd, COALESCE(SUM(l.cash_debit),0) cd"
        " FROM journal_entries e LEFT JOIN journal_lines l ON l.entry_id=e.id"
        " GROUP BY e.id ORDER BY e.id DESC LIMIT ?", (limit,)).fetchall()


def search_manual_entries(conn, q="", date_from=None, date_to=None, limit=200):
    sql = ("SELECT e.id, e.entry_date, e.description, e.is_deleted, e.created_by,"
          # سجل القيود يعرض المحذوف عمداً (يشمل المحذوف منطقياً)
          # ليبقى أثر التدقيق كاملاً، وعمود «الحالة» يميّزه للمستخدم.
          " COALESCE(SUM(l.gold_debit),0) gd, COALESCE(SUM(l.cash_debit),0) cd"
          " FROM journal_entries e LEFT JOIN journal_lines l ON l.entry_id=e.id"
          " WHERE (e.source_table IS NULL OR e.source_table='manual')")
    params = []
    if q:
        sql += " AND (e.description LIKE ? OR CAST(e.id AS TEXT) LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if date_from:
        sql += " AND e.entry_date>=?"; params.append(date_from)
    if date_to:
        sql += " AND e.entry_date<=?"; params.append(date_to)
    sql += " GROUP BY e.id ORDER BY e.id DESC LIMIT ?"; params.append(limit)
    return conn.execute(sql, params).fetchall()


def entry_lines(conn, entry_id):
    return conn.execute(
        "SELECT l.*, a.code acode, a.name aname"
        " FROM journal_lines l JOIN accounts a ON a.id=l.account_id"
        " WHERE l.entry_id=? ORDER BY l.id", (entry_id,)).fetchall()


OP_LABELS = {
    "invoices": "مبيعات", "vouchers": "سند", "work_orders": "توريد",
    "wo_adjust": "تسوية",
    "melting_ops": "صب وتصفية", "fixing_ops": "تسكير",
    "shrinkage_ops": "تسوية فاقد", "stocktakes": "جرد",
    "purchases": "مشتريات", "entities": "رصيد افتتاحي",
    "payroll_ledger": "راتب", "tax_debit_notes": "إشعار ضريبي",
    None: "قيد يومي",
}

# رقم المستند لكل نوع عملية (جدول المصدر → عمود الرقم)
DOC_NO_COL = {
    "invoices": "invoice_no", "vouchers": "voucher_no",
    "purchases": "purchase_no", "melting_ops": "op_no",
    "fixing_ops": "op_no", "shrinkage_ops": "op_no",
    "work_orders": "work_order_no", "tax_debit_notes": "note_no",
}


def _doc_info(conn, src, sid, cache):
    """رقم المستند ونوع العملية الدقيق (صرف/قبض، مبيعات/مرتجع)."""
    if not src or not sid:
        return "", OP_LABELS.get(src, OP_LABELS[None])
    key = (src, sid)
    if key in cache:
        return cache[key]
    no, label = "", OP_LABELS.get(src, src)
    col = DOC_NO_COL.get(src)
    if col:
        try:
            r = conn.execute(f"SELECT {col} n FROM {src} WHERE id=?",
                             (sid,)).fetchone()
            no = (r["n"] if r and r["n"] else "") or ""
        except Exception:
            no = ""
    if src == "vouchers":
        r = conn.execute("SELECT kind FROM vouchers WHERE id=?", (sid,)).fetchone()
        if r:
            label = "قبض" if r["kind"] == "receipt" else "صرف"

    elif src == "invoices":
        r = conn.execute("SELECT kind FROM invoices WHERE id=?", (sid,)).fetchone()
        if r:
            label = "مرتجع" if r["kind"] == "sale_return" else "مبيعات"
    cache[key] = (no, label)
    return no, label


SHORT_NAMES = {
    "1100": "خزينة التصنيع", "1150": "فصوص وأحجار",
    "1200": "الذهب المشغول", "1250": "تسويات الأوزان",
    "1300": "صناديق الكسر",
    "1310": "صندوق الكسر",
    "1350": "الصهر والتصفية",
    "1400": "صندوق النقدي", "1410": "نثرية", "1500": "البنك",
    "1700": "أصول ثابتة", "1900": "ضريبة مدخلات",
    "1950": "سلف الموظفين", "1960": "عهد",
    "2100": "ضريبة مخرجات", "2150": "تسوية ضريبة",
    "2200": "مستحقات موظفين", "2300": "الموردون",
    "2900": "تسويات مباشرة",
    "3110": "رأس المال", "3120": "جاري الشركاء",
    "3200": "أرباح محتجزة", "3210": "أرباح العام",
    "3900": "أرصدة افتتاحية",
    "4100": "إيرادات أجور", "4200": "إيرادات أخرى",
    "4300": "أرباح فروقات",
    "5110": "فاقد التصنيع", "5120": "فاقد الصب",
    "5130": "خسائر الجرد", "5700": "مصروف الرواتب",
    "5800": "إدارية وعمومية",
}


def short_name(code, name):
    """اسم فني مختصر للحساب المقابل — بلا حشو.

    حسابات الجهات (عملاء/موردون/موظفون) تُعرض باسم الجهة مفرداً بعد
    إزالة البادئة الوصفية مثل «عميل: » أو «مورد: ».
    """
    if code and code in SHORT_NAMES:
        return SHORT_NAMES[code]
    n = (name or "").strip()
    for pref in ("عميل:", "مورد:", "موظف:", "شريك:", "جهة:", "حساب"):
        if n.startswith(pref):
            n = n[len(pref):].strip(" :")
            break
    # يُقتطع أي شرح بين قوسين أو بعد شرطة
    for sep in ("(", "—", " - ", "/"):
        if sep in n:
            n = n.split(sep)[0].strip()
    # حد أقصى كلمتان — بلا حشو ولا توسّع زائد في الجداول
    words = n.split()
    if len(words) > 2:
        n = " ".join(words[:2])
    return n or "—"


def _counterparty(conn, entry_id, account_id, cache, dim=None, ldesc=None):
    """اسم الحساب المقابل في نفس القيد — وجهة الحركة.

    `dim`: "gold" أو "cash" لعرض مقابل البُعد المعني فقط، فيظهر سطر
    الذهب مقابل صناديق الكسر وسطر النقد مقابل صندوق النقدي.
    """
    key = (entry_id, dim, ldesc or "")
    if key in cache:
        names = cache[key]
    else:
        cond = ""
        # القيود المفصّلة (كالرواتب) تحمل بياناً مطابقاً لكل زوج أسطر،
        # فيُشتق المقابل من السطر المناظر بنفس البيان لا من القيد كله.
        params_extra = []
        if ldesc:
            cond += " AND l.line_desc=?"
            params_extra.append(ldesc)
        if dim == "gold":
            cond += " AND (l.gold_debit>0 OR l.gold_credit>0)"
        elif dim == "cash":
            cond += " AND (l.cash_debit>0 OR l.cash_credit>0)"
        # يُجلب النوع أيضاً لترتيب الأفضلية: الحسابات الحقيقية (أصول
        # وخصوم وجهات) أولى بالعرض من الحسابات الفنية (إيراد/مصروف).
        names = [(short_name(r["code"], r["name"]), r["type"])
                 for r in conn.execute(
            "SELECT DISTINCT a.id, a.code, a.name, a.type FROM journal_lines l"
            " JOIN accounts a ON a.id=l.account_id WHERE l.entry_id=?"
            + cond + " ORDER BY l.id", [entry_id] + params_extra)]
        # لو لم يعطِ الترشيح ببيان السطر مقابلاً (سطر مفرد لا زوج)،
        # نرجع للبحث في القيد كله.
        if params_extra and len(names) < 2:
            base = ""
            if dim == "gold":
                base = " AND (l.gold_debit>0 OR l.gold_credit>0)"
            elif dim == "cash":
                base = " AND (l.cash_debit>0 OR l.cash_credit>0)"
            names = [(short_name(r["code"], r["name"]), r["type"])
                     for r in conn.execute(
                "SELECT DISTINCT a.id, a.code, a.name, a.type"
                " FROM journal_lines l"
                " JOIN accounts a ON a.id=l.account_id WHERE l.entry_id=?"
                + base + " ORDER BY l.id", (entry_id,))]
        cache[key] = names
    self_name = None
    r = conn.execute("SELECT code, name FROM accounts WHERE id=?",
                     (account_id,)).fetchone()
    if r:
        self_name = short_name(r["code"], r["name"])
    others = [(n, t) for n, t in names if n != self_name]
    if not others:
        return "—"
    # أفضلية العرض: الطرف الحقيقي المقابل لا الحساب الفني.
    # فتحُ كشف العميل لعملية بيع يُظهر «الذهب المشغول»، وفتحُ كشف
    # الذهب المشغول يُظهر «محمد» — لا تكرار لاسم نوع العملية.
    real = [n for n, t in others if t not in ("revenue", "expense")]
    others = real or [n for n, _ in others]
    if len(others) == 1:
        return others[0]
    # عدة صناديق كسر ⇒ اسم جامع مختصر
    if all(n.startswith("كسر") for n in others):
        return "صندوق الكسر"
    return others[0]        # الأول فقط — بلا «وآخرون» ولا أعداد


def _op_label(source_table, entry_desc):
    if source_table:
        return OP_LABELS.get(source_table, source_table)
    return "قيد يومية يدوي"


def statement(conn, account_id, date_from=None, date_to=None):
    """كشف حساب مزدوج بأعمدة مرتبة:

    التاريخ | نوع العملية | رقم السند | اسم الجهة/الحساب المقابل |
    البيان (فارغ ما لم يكتب المستخدم ملاحظة) | مدين/دائن/رصيد ذهب |
    مدين/دائن/رصيد نقد.
    """
    rows, params = [], [account_id]
    gb = cb = 0.0
    if date_from:
        op = conn.execute(
            "SELECT COALESCE(SUM(l.gold_debit-l.gold_credit),0) g,"
            " COALESCE(SUM(l.cash_debit-l.cash_credit),0) c"
            " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
            " WHERE e.is_deleted=0 AND l.account_id=? AND e.entry_date<?",
            (account_id, date_from)).fetchone()
        gb, cb = round(op["g"], 3), round(op["c"], 2)
        rows.append({"date": date_from, "eid": "", "op": "رصيد سابق",
                     "doc_no": "", "name": "—", "desc": "",
                     "src": None, "sid": None,
                     "gd": 0, "gc": 0, "gbal": gb,
                     "cd": 0, "cc": 0, "cbal": cb})
    q = ("SELECT e.entry_date d, e.id eid, e.user_note un,"
         " e.source_table st, e.source_id sid,"
         " l.gold_debit gd, l.gold_credit gc, l.cash_debit cd, l.cash_credit cc,"
         " l.line_desc ld, e.doc_no jdoc,"
         " (SELECT i.kind FROM invoices i WHERE i.id=e.source_id) _kind"
         " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
         " WHERE e.is_deleted=0 AND l.account_id=?")
    if date_from:
        q += " AND e.entry_date>=?"; params.append(date_from)
    if date_to:
        q += " AND e.entry_date<=?"; params.append(date_to)
    # الترتيب بمفتاح ثابت لا بمعرّف القيد: القيد المُعاد ترحيله بعد
    # التعديل يرث مفتاح سلفه فيبقى في موضعه الزمني نفسه.
    q += " ORDER BY e.entry_date, COALESCE(e.sort_key, e.id), e.id, l.id"
    dcache, ccache = {}, {}

    # دمج أسطر القيد الواحد على نفس الحساب: الذهب في سطر إجمالي واحد
    # (مهما تعددت الأعيرة) والنقد في سطر مستقل — وتفاصيل الأعيرة
    # تُعرض بمعاينة السند نفسه.
    merged = []
    for r in conn.execute(q, params):
        # الدمج يشترط تطابق القيد **وبيان السطر** معاً: فالفاتورة تُدمج
        # في سطر واحد، بينما قيد الرواتب يبقى مفصّلاً بسطر لكل موظف
        # لأن بيان كل سطر يحمل اسمه.
        key = (r["eid"], (r["ld"] or "").strip())
        if merged and merged[-1]["_eid"] == key:
            m = merged[-1]
            m["gd"] = round(m["gd"] + r["gd"], 3)
            m["gc"] = round(m["gc"] + r["gc"], 3)
            m["cd"] = round(m["cd"] + r["cd"], 2)
            m["cc"] = round(m["cc"] + r["cc"], 2)
            continue
        merged.append({"_eid": key, "d": r["d"], "eid": r["eid"],
                       "un": ("" if r["st"] == "invoices"
                              else (r["un"] or (r["ld"] or ""))),
                       "st": r["st"], "sid": r["sid"],
                       "_kind": r["_kind"], "_ld": (r["ld"] or "").strip(),
                       "jdoc": r["jdoc"],
                       "gd": r["gd"], "gc": r["gc"],
                       "cd": r["cd"], "cc": r["cc"]})

    # سطر واحد متكامل لكل مستند يجمع الوزن والنقد معاً
    split = merged

    for r in split:
        gb = round(gb + r["gd"] - r["gc"], 3)
        cb = round(cb + r["cd"] - r["cc"], 2)
        doc_no, label = _doc_info(conn, r["st"], r["sid"], dcache)
        # قيود التسوية تُميَّز عن التوريد بوصف القيد نفسه
        if r["st"] == "work_orders" and (r["un"] or "").startswith(
                ("حذف رقم التشغيل", "زيادة في رقم التشغيل",
                 "تعديل وزن رقم التشغيل")):
            label = "تسوية"
        rows.append({"date": r["d"], "eid": r["eid"], "op": label,
                     "doc_no": doc_no or r.get("jdoc") or f"#{r['eid']}",
                     "name": (_counterparty(
                         conn, r["eid"], account_id, ccache,
                         "gold" if (r["gd"] or r["gc"]) else
                         ("cash" if (r["cd"] or r["cc"]) else None),
                         ldesc=(r.get("_ld") or None))),
                     "desc": r["un"] or "",
                     "src": r["st"], "sid": r["sid"],
                     "gd": r["gd"], "gc": r["gc"], "gbal": gb,
                     "cd": r["cd"], "cc": r["cc"], "cbal": cb})
    return rows


# ══════════════════════════════════════════════════════════════════
#  دفتر اليومية — كل الحركات في فترة، بلا تحديد حساب
# ══════════════════════════════════════════════════════════════════

ALL_ACCOUNTS = "*"


def day_book(conn, date_from=None, date_to=None, kind=None, limit=3000):
    """كل عمليات الفترة على **جميع الحسابات** — سطر لكل مستند.

    كشف الحساب يتطلب اختيار حساب، والرصيد التراكمي فيه لا معنى له
    عبر الحسابات. لكن السؤال المتكرر بعد كل جرد أو مراجعة هو: «ماذا
    جرى في هذا اليوم؟» — لمعرفة مصدر خطأ دون معرفة حسابه مسبقاً.

    فهذا عرض مختلف: سطر واحد لكل قيد، فيه رقم السند ونوع العملية
    والحسابات التي مسّها وإجمالي وزنه ونقده ومن أنشأه. بلا أرصدة
    تراكمية لأنها بلا معنى هنا.
    """
    q = ("SELECT e.id eid, e.entry_date d, e.doc_no jdoc, e.user_note un,"
         " e.description dsc, e.source_table st, e.source_id sid,"
         " e.created_by who, e.created_at whn,"
         " ROUND(SUM(l.gold_debit),3) gd, ROUND(SUM(l.cash_debit),2) cd,"
         " COUNT(l.id) nlines"
         " FROM journal_entries e JOIN journal_lines l ON l.entry_id=e.id"
         " WHERE e.is_deleted=0")
    params = []
    if date_from:
        q += " AND e.entry_date>=?"
        params.append(date_from)
    if date_to:
        q += " AND e.entry_date<=?"
        params.append(date_to)
    q += (" GROUP BY e.id"
          " ORDER BY e.entry_date, COALESCE(e.sort_key, e.id), e.id"
          " LIMIT ?")
    params.append(int(limit))

    dcache = {}
    out = []
    for r in conn.execute(q, params):
        doc_no, label = _doc_info(conn, r["st"], r["sid"], dcache)
        if kind and kind not in (label or ""):
            continue
        # الحسابات التي مسّها القيد — مختصرةً فتُقرأ في سطر
        accs = [f"{a['code']} {a['name']}" for a in conn.execute(
            "SELECT DISTINCT a.code, a.name FROM journal_lines l"
            " JOIN accounts a ON a.id=l.account_id"
            " WHERE l.entry_id=? ORDER BY a.code", (r["eid"],))]
        shown = " · ".join(accs[:3])
        if len(accs) > 3:
            shown += f" … (+{len(accs) - 3})"
        out.append({
            "date": r["d"], "eid": r["eid"], "op": label,
            "doc_no": doc_no or r["jdoc"] or f"#{r['eid']}",
            "accounts": shown, "n_accounts": len(accs),
            "desc": (r["un"] or "").strip() or (r["dsc"] or "").strip(),
            "gold": r["gd"] or 0.0, "cash": r["cd"] or 0.0,
            "who": r["who"] or "", "when": r["whn"] or "",
            "src": r["st"], "sid": r["sid"]})
    return out
