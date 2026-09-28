# -*- coding: utf-8 -*-
"""المبيعات الضريبية — فواتير بالريال **لا تمسّ الذهب ولا المخزون**.

**لماذا شاشةٌ مستقلة**: فاتورة البيع في النظام تُخرج أطقماً من الخزنة
وتُقيّد أوزانها ذهباً. أما هنا فمبيعاتٌ تُحاسَب بالريال وحده (خدمة،
قيمة بضاعة متّفق عليها، تسوية تجارية…) ويُطلب لها فاتورة ضريبية —
فلا طقم يخرج، ولا وزن يُقيَّد، ولا رصيد ذهبٍ يتحرّك.

**القيد** (الأبعاد النقدية وحدها):
    فاتورة:   من حـ/ العميل (آجل) أو الصندوق 1400 أو البنك 1500   الإجمالي
                  إلى حـ/ المبيعات الضريبية 4130                    الصافي
                  إلى حـ/ ضريبة القيمة المضافة — المخرجات 2100      الضريبة
    إشعار دائن (مرتجع ضريبي) — عكسها تماماً:
              من حـ/ مردودات المبيعات الضريبية 4930                الصافي
              من حـ/ ضريبة المخرجات 2100                          الضريبة
                  إلى حـ/ العميل أو الصندوق أو البنك (طريقة الأصل)  الإجمالي

**الضريبة** تُحسب على صافي المستند كلّه (لا جمعاً لضرائب الأسطر) —
القاعدة نفسها التي تتحقّق بها الهيئة — فلا فرق هللةٍ بين الورقة
والإقرار والفاتورة الإلكترونية.

**لا تعديل ولا حذف لفاتورةٍ ضريبية بعد ترحيلها** إلا بإشعار دائن يشير
إليها — ولا يتجاوز الإشعار ما بقي من الأصل سطراً سطراً.
"""
from decimal import Decimal

import config
from models.accounts import acc_id
from models.entities import get_entity
from services.accounting_engine import post_entry
from services.audit import log_action
from services.fatoora.ubl import money

PAY_MODES = (("credit", "آجل — على حساب العميل"),
             ("cash", "نقداً — الصندوق الرئيسي"),
             ("bank", "تحويل بنكي / شبكة — البنك"))
PAY_ACCOUNTS = {"cash": "1400", "bank": "1500"}
REVENUE, RETURNS, VAT_OUT = "4130", "4930", "2100"


def ensure_tables(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tax_sales("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, doc_no TEXT UNIQUE,"
        " kind TEXT NOT NULL CHECK(kind IN ('invoice','credit')),"
        " customer_id INTEGER NOT NULL REFERENCES entities(id),"
        " doc_date TEXT NOT NULL,"
        " pay_mode TEXT NOT NULL DEFAULT 'credit',"
        " vat_rate REAL NOT NULL DEFAULT 0.15,"
        " net REAL NOT NULL, vat REAL NOT NULL, total REAL NOT NULL,"
        " ref_id INTEGER REFERENCES tax_sales(id),"
        " reason TEXT DEFAULT '', notes TEXT DEFAULT '',"
        " qr_base64 TEXT DEFAULT '',"
        " entry_id INTEGER REFERENCES journal_entries(id),"
        " is_deleted INTEGER NOT NULL DEFAULT 0,"
        " created_by TEXT,"
        " created_at TEXT DEFAULT (datetime('now','localtime')))")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tax_sale_lines("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " sale_id INTEGER NOT NULL REFERENCES tax_sales(id),"
        " line_no INTEGER NOT NULL, description TEXT NOT NULL,"
        " qty REAL NOT NULL, unit_price REAL NOT NULL,"
        " discount REAL NOT NULL DEFAULT 0, net REAL NOT NULL,"
        " vat REAL NOT NULL, total REAL NOT NULL,"
        " src_line_id INTEGER REFERENCES tax_sale_lines(id))")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tax_sales_date"
                 " ON tax_sales(doc_date, is_deleted)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tax_sale_lines"
                 " ON tax_sale_lines(sale_id)")


# ══════════════════════════ الحساب ══════════════════════════
def compute(lines, rate=None):
    """أسطرٌ مُتحقَّق منها وإجماليات — بالتقريب الذي تتحقّق به الهيئة.

    السطر: الصافي = الكمية × السعر − الخصم. وضريبة المستند = صافيه ×
    النسبة مقرّبةً مرةً واحدة؛ وضريبة كل سطر للعرض وحده.
    """
    r = Decimal(str(config.VAT_RATE if rate is None else rate))
    out = []
    for i, li in enumerate(lines or [], 1):
        desc = str(li.get("description", "")).strip()
        qty = Decimal(str(li.get("qty") or 0))
        price = Decimal(str(li.get("unit_price") or 0))
        disc = money(li.get("discount") or 0)
        if not desc:
            raise ValueError(f"السطر {i}: اكتب البيان")
        if qty <= 0:
            raise ValueError(f"السطر {i}: الكمية يجب أن تكون أكبر من صفر")
        if price < 0 or disc < 0:
            raise ValueError(f"السطر {i}: لا تُقبل مبالغ سالبة")
        gross = money(qty * price)
        if disc > gross:
            raise ValueError(f"السطر {i}: الخصم أكبر من قيمة السطر")
        net = gross - disc
        vat = money(net * r)
        out.append({"line_no": i, "description": desc, "qty": float(qty),
                    "unit_price": float(price), "discount": float(disc),
                    "net": float(net), "vat": float(vat),
                    "total": float(net + vat),
                    "src_line_id": li.get("src_line_id")})
    if not out:
        raise ValueError("أضف سطراً واحداً على الأقل")
    net = sum((money(li["net"]) for li in out), Decimal("0"))
    vat = money(net * r)
    return out, {"net": float(net), "vat": float(vat),
                 "total": float(net + vat), "rate": float(r)}


def _party_account(conn, cust, pay_mode):
    if pay_mode == "credit":
        return cust["account_id"]
    return acc_id(conn, PAY_ACCOUNTS[pay_mode])


# ══════════════════════════ الإصدار ══════════════════════════
def create_invoice(conn, customer_id, doc_date, lines, username,
                   pay_mode="credit", notes=""):
    ensure_tables(conn)
    cust = get_entity(conn, customer_id)
    if not cust or cust["entity_type"] not in ("customer", "other"):
        raise ValueError("اختر العميل من دليل جهات التعامل")
    if pay_mode not in dict(PAY_MODES):
        raise ValueError("طريقة الدفع غير معروفة")
    rows, t = compute(lines)
    if t["total"] <= 0:
        raise ValueError("إجمالي الفاتورة صفر")
    cur = conn.execute(
        "INSERT INTO tax_sales(kind,customer_id,doc_date,pay_mode,vat_rate,"
        "net,vat,total,notes,created_by) VALUES('invoice',?,?,?,?,?,?,?,?,?)",
        (customer_id, doc_date, pay_mode, t["rate"], t["net"], t["vat"],
         t["total"], (notes or "").strip(), username))
    sid = cur.lastrowid
    no = f"TS-{sid:05d}"
    _save_lines(conn, sid, rows)
    lines_je = [
        {"account_id": _party_account(conn, cust, pay_mode),
         "cash_debit": t["total"],
         "line_desc": f"فاتورة ضريبية {no}"
         + ("" if pay_mode == "credit" else f" — {cust['name']}")},
        {"account_id": acc_id(conn, REVENUE), "cash_credit": t["net"],
         "line_desc": "مبيعات ضريبية (خارج المخزون)"},
    ]
    if t["vat"]:
        lines_je.append({"account_id": acc_id(conn, VAT_OUT),
                         "cash_credit": t["vat"],
                         "line_desc": f"ضريبة مخرجات {no}"})
    entry_id = post_entry(conn, doc_date, f"فاتورة ضريبية {no} — "
                          f"{cust['name']}", lines_je,
                          source_table="tax_sales", source_id=sid,
                          username=username, note=notes)
    conn.execute("UPDATE tax_sales SET doc_no=?, entry_id=? WHERE id=?",
                 (no, entry_id, sid))
    qr = _issue_einvoice(conn, sid, username)
    log_action(conn, username, "create", "tax_sales", sid,
               f"{no} total={t['total']}")
    return {"id": sid, "doc_no": no, "entry_id": entry_id, "qr": qr,
            "customer_name": cust["name"], **t}


def remaining(conn, sale_id):
    """ما بقي من كل سطرٍ في الفاتورة بعد إشعاراتها الدائنة (بالكمية)."""
    out = {}
    for li in conn.execute("SELECT * FROM tax_sale_lines WHERE sale_id=?"
                           " ORDER BY line_no", (sale_id,)):
        used = conn.execute(
            "SELECT COALESCE(SUM(l.qty),0) FROM tax_sale_lines l JOIN"
            " tax_sales s ON s.id=l.sale_id WHERE l.src_line_id=? AND"
            " s.is_deleted=0", (li["id"],)).fetchone()[0]
        out[li["id"]] = {"line": dict(li), "qty_left": round(
            float(li["qty"]) - float(used or 0), 6)}
    return out


def create_credit_note(conn, original_id, doc_date, returns, reason,
                       username, notes=""):
    """إشعار دائن: `returns` = [{src_line_id, qty}] — مرتجعٌ من أسطر الأصل.

    السعر والخصم يُؤخذان من سطر الأصل نفسه (الخصم بنسبة الكمية)، فلا
    يُرَدّ للعميل أكثر مما دفع ولا بسعرٍ غير سعره.
    """
    ensure_tables(conn)
    orig = conn.execute("SELECT * FROM tax_sales WHERE id=? AND is_deleted=0"
                        " AND kind='invoice'", (original_id,)).fetchone()
    if not orig:
        raise ValueError("اختر الفاتورة الضريبية الأصلية")
    if not str(reason or "").strip():
        raise ValueError("اكتب سبب الإشعار الدائن (إلزامي لدى الهيئة)")
    left = remaining(conn, original_id)
    lines = []
    for r in returns or []:
        q = float(r.get("qty") or 0)
        if q <= 0:
            continue
        info = left.get(r.get("src_line_id"))
        if not info:
            raise ValueError("سطرٌ ليس من الفاتورة الأصلية")
        if q > info["qty_left"] + 1e-9:
            raise ValueError(f"«{info['line']['description']}»: المرتجع "
                             f"{q:g} أكبر من المتبقي {info['qty_left']:g}")
        src = info["line"]
        disc = float(src["discount"]) * q / float(src["qty"])
        lines.append({"description": src["description"], "qty": q,
                      "unit_price": src["unit_price"],
                      "discount": float(money(disc)),
                      "src_line_id": src["id"]})
    if not lines:
        raise ValueError("حدّد كمية المرتجع في سطرٍ واحد على الأقل")
    rows, t = compute(lines, orig["vat_rate"])
    cust = get_entity(conn, orig["customer_id"])
    cur = conn.execute(
        "INSERT INTO tax_sales(kind,customer_id,doc_date,pay_mode,vat_rate,"
        "net,vat,total,ref_id,reason,notes,created_by)"
        " VALUES('credit',?,?,?,?,?,?,?,?,?,?,?)",
        (orig["customer_id"], doc_date, orig["pay_mode"], t["rate"],
         t["net"], t["vat"], t["total"], original_id, reason.strip(),
         (notes or "").strip(), username))
    sid = cur.lastrowid
    no = f"TSR-{sid:05d}"
    _save_lines(conn, sid, rows)
    je = [{"account_id": acc_id(conn, RETURNS), "cash_debit": t["net"],
           "line_desc": f"مردود مبيعات ضريبية — {orig['doc_no']}"}]
    if t["vat"]:
        je.append({"account_id": acc_id(conn, VAT_OUT), "cash_debit": t["vat"],
                   "line_desc": f"عكس ضريبة مخرجات {orig['doc_no']}"})
    je.append({"account_id": _party_account(conn, cust, orig["pay_mode"]),
               "cash_credit": t["total"],
               "line_desc": f"إشعار دائن {no} على {orig['doc_no']}"})
    entry_id = post_entry(conn, doc_date, f"إشعار دائن {no} — "
                          f"{cust['name']} — على {orig['doc_no']}", je,
                          source_table="tax_sales", source_id=sid,
                          username=username, note=reason)
    conn.execute("UPDATE tax_sales SET doc_no=?, entry_id=? WHERE id=?",
                 (no, entry_id, sid))
    qr = _issue_einvoice(conn, sid, username)
    log_action(conn, username, "create", "tax_sales", sid,
               f"{no} ref={orig['doc_no']} total={t['total']}")
    return {"id": sid, "doc_no": no, "entry_id": entry_id, "qr": qr,
            "customer_name": cust["name"], "ref_no": orig["doc_no"], **t}


def _save_lines(conn, sid, rows):
    for li in rows:
        conn.execute(
            "INSERT INTO tax_sale_lines(sale_id,line_no,description,qty,"
            "unit_price,discount,net,vat,total,src_line_id)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (sid, li["line_no"], li["description"], li["qty"],
             li["unit_price"], li["discount"], li["net"], li["vat"],
             li["total"], li.get("src_line_id")))


# ══════════════════════════ الفاتورة الإلكترونية ══════════════════════════
def build_doc(conn, sale_id):
    """مستند الفوترة الإلكترونية للفاتورة/الإشعار — بأسطره كما هي."""
    from services.fatoora import ledger
    from services.fatoora import profile as pf
    s = conn.execute("SELECT * FROM tax_sales WHERE id=?",
                     (sale_id,)).fetchone()
    p = pf.load(conn)
    b = pf.buyer(conn, s["customer_id"]) or {}
    std = pf.buyer_is_b2b(b)
    created = str(s["created_at"] or "")
    lines = []
    for li in conn.execute("SELECT * FROM tax_sale_lines WHERE sale_id=?"
                           " ORDER BY line_no", (sale_id,)):
        extra = (f" — {li['qty']:g} × {li['unit_price']:,.2f}"
                 + (f" − خصم {li['discount']:,.2f}" if li["discount"] else ""))
        lines.append({"name": li["description"] + extra, "amount": li["net"]})
    doc = {
        "kind": "invoice" if s["kind"] == "invoice" else "credit",
        "subtype": "standard" if std else "simplified",
        "number": s["doc_no"], "issue_date": s["doc_date"],
        "issue_time": created[11:19] if len(created) >= 19 else "00:00:00",
        "supply_date": s["doc_date"], "seller": ledger._seller(p),
        "buyer": {"name": b.get("name", ""),
                  "vat": b.get("vat", "") if std else "",
                  **({k: b.get(k, "") for k in pf.BUYER_FIELDS}
                     if std else {})},
        "lines": lines, "rate": float(s["vat_rate"]) * 100,
        "payment_means": {"cash": "10", "bank": "42"}.get(
            s["pay_mode"], p.get("payment_means") or "30"),
        "expect_gross": s["total"],
    }
    if s["kind"] == "credit":
        ref = conn.execute("SELECT doc_no FROM tax_sales WHERE id=?",
                           (s["ref_id"],)).fetchone()
        doc["billing_refs"] = [ref["doc_no"] if ref else "—"]
        doc["reason"] = s["reason"] or "مرتجع"
    return doc


def _issue_einvoice(conn, sid, username):
    """مع الربط: مستندٌ مختوم ورمز المرحلة الثانية. وبدونه: رمز المرحلة
    الأولى (خمسة حقول) — فالفاتورة الضريبية المطبوعة تحمل رمزاً دائماً."""
    from services.fatoora import ledger
    if ledger.enabled(conn):
        ledger.ensure_tables(conn)
        res = ledger.issue(conn, "tax_sales", sid, build_doc(conn, sid),
                           username)
        qr = res["qr"]
    else:
        from datetime import datetime

        from services import zatca
        from services.fatoora import profile as pf
        p = pf.load(conn)
        s = conn.execute("SELECT * FROM tax_sales WHERE id=?",
                         (sid,)).fetchone()
        qr = zatca.build_tlv_base64(
            p.get("name") or config.COMPANY_NAME,
            p.get("vat") or config.COMPANY_VAT_NUMBER,
            f"{s['doc_date']}T{datetime.now():%H:%M:%S}", s["total"],
            s["vat"])
    conn.execute("UPDATE tax_sales SET qr_base64=? WHERE id=?", (qr, sid))
    return qr


# ══════════════════════════ القراءة ══════════════════════════
def get(conn, sale_id):
    ensure_tables(conn)
    s = conn.execute(
        "SELECT s.*, e.name customer_name, e.vat_number customer_vat,"
        " r.doc_no ref_no FROM tax_sales s JOIN entities e"
        " ON e.id=s.customer_id LEFT JOIN tax_sales r ON r.id=s.ref_id"
        " WHERE s.id=?", (sale_id,)).fetchone()
    if not s:
        return None, []
    lines = conn.execute("SELECT * FROM tax_sale_lines WHERE sale_id=?"
                         " ORDER BY line_no", (sale_id,)).fetchall()
    return s, lines


def search(conn, q="", date_from=None, date_to=None, kind=None, limit=1000):
    ensure_tables(conn)
    sql = ("SELECT s.*, e.name customer_name, r.doc_no ref_no FROM tax_sales s"
           " JOIN entities e ON e.id=s.customer_id"
           " LEFT JOIN tax_sales r ON r.id=s.ref_id WHERE s.is_deleted=0")
    params = []
    if q:
        sql += " AND (s.doc_no LIKE ? OR e.name LIKE ? OR s.notes LIKE ?)"
        params += [f"%{q}%"] * 3
    if kind:
        sql += " AND s.kind=?"
        params.append(kind)
    if date_from:
        sql += " AND s.doc_date>=?"
        params.append(date_from)
    if date_to:
        sql += " AND s.doc_date<=?"
        params.append(date_to)
    sql += " ORDER BY s.doc_date DESC, s.id DESC LIMIT ?"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def open_invoices(conn):
    """الفواتير التي بقي منها ما يُرتجع — لقائمة الإشعار الدائن."""
    out = []
    for s in search(conn, kind="invoice", limit=2000):
        left = remaining(conn, s["id"])
        if any(v["qty_left"] > 1e-9 for v in left.values()):
            out.append(s)
    return out


def totals(conn, date_from, date_to):
    """إجماليات الفترة: الفواتير − الإشعارات = صافي المبيعات الضريبية."""
    ensure_tables(conn)
    r = conn.execute(
        "SELECT kind, COUNT(*) n, COALESCE(SUM(net),0) net,"
        " COALESCE(SUM(vat),0) vat, COALESCE(SUM(total),0) total"
        " FROM tax_sales WHERE is_deleted=0 AND doc_date BETWEEN ? AND ?"
        " GROUP BY kind", (date_from, date_to)).fetchall()
    d = {x["kind"]: dict(x) for x in r}
    inv = d.get("invoice", {"n": 0, "net": 0, "vat": 0, "total": 0})
    crd = d.get("credit", {"n": 0, "net": 0, "vat": 0, "total": 0})
    return {"invoices": inv, "credits": crd,
            "net": round(inv["net"] - crd["net"], 2),
            "vat": round(inv["vat"] - crd["vat"], 2),
            "total": round(inv["total"] - crd["total"], 2)}
