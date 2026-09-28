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


_TS_DDL = (
    "CREATE TABLE IF NOT EXISTS tax_sales("
    " id INTEGER PRIMARY KEY AUTOINCREMENT, doc_no TEXT UNIQUE,"
    " kind TEXT NOT NULL CHECK(kind IN ('invoice','credit','debit')),"
    " customer_id INTEGER NOT NULL REFERENCES entities(id),"
    " rep_id INTEGER REFERENCES entities(id),"
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


def _upgrade_v1(conn, sql):
    """ترقية 4.22 ← 4.23: عمود المندوب، وقبول «إشعار مدين» في النوع.

    **لماذا لا يُعاد بناء الجدول**: مع تفعيل المفاتيح الأجنبية يرفض
    SQLite حذف جدولٍ تشير إليه أسطر الفواتير، ولا يُعطَّل التفعيل داخل
    معاملة. وقيد CHECK نصٌّ لا يمسّ البيانات المخزَّنة — فتعديل نصّه في
    المخطط هو الطريق الموثّق لذلك، والعمود يُضاف بـALTER عادي.
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tax_sales)")}
    if "rep_id" not in cols:
        conn.execute("ALTER TABLE tax_sales ADD COLUMN rep_id INTEGER"
                     " REFERENCES entities(id)")
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE type="
                           "'table' AND name='tax_sales'").fetchone()[0]
    new = sql.replace("CHECK(kind IN ('invoice','credit'))",
                      "CHECK(kind IN ('invoice','credit','debit'))")
    if new == sql:
        raise RuntimeError("tax_sales: صيغة قيد النوع غير متوقَّعة")
    ver = conn.execute("PRAGMA schema_version").fetchone()[0]
    conn.execute("PRAGMA writable_schema=ON")
    try:
        conn.execute("UPDATE sqlite_master SET sql=? WHERE type='table'"
                     " AND name='tax_sales'", (new,))
        conn.execute(f"PRAGMA schema_version={int(ver) + 1}")
    finally:
        conn.execute("PRAGMA writable_schema=OFF")


def ensure_tables(conn):
    old = conn.execute("SELECT sql FROM sqlite_master WHERE type='table'"
                       " AND name='tax_sales'").fetchone()
    if not old:
        conn.execute(_TS_DDL)
    elif "'debit'" not in (old[0] or ""):
        _upgrade_v1(conn, old[0])
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tax_sale_lines("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " sale_id INTEGER NOT NULL REFERENCES tax_sales(id),"
        " line_no INTEGER NOT NULL, description TEXT NOT NULL,"
        " qty REAL NOT NULL, unit_price REAL NOT NULL,"
        " discount REAL NOT NULL DEFAULT 0, net REAL NOT NULL,"
        " vat REAL NOT NULL, total REAL NOT NULL,"
        " src_line_id INTEGER REFERENCES tax_sale_lines(id))")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tax_sale_lines)")}
    for col, ddl in (("sale_item_id", "INTEGER"),
                     ("work_order_id", "INTEGER"),
                     ("wo_no", "TEXT DEFAULT ''"),
                     ("model_no", "TEXT DEFAULT ''")):
        if col not in cols:
            conn.execute(f"ALTER TABLE tax_sale_lines ADD COLUMN {col} {ddl}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tax_sales_date"
                 " ON tax_sales(doc_date, is_deleted)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tax_sale_lines"
                 " ON tax_sale_lines(sale_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tax_sale_items"
                 " ON tax_sale_lines(sale_item_id)")


# ══════════════════════════ الحساب ══════════════════════════
_EXTRA = ("sale_item_id", "work_order_id", "wo_no", "model_no")


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
                    "src_line_id": li.get("src_line_id"),
                    **{k: li.get(k) for k in _EXTRA}})
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
                      "src_line_id": src["id"],
                      **{k: src[k] for k in _EXTRA if k in src.keys()}})
    if not lines:
        raise ValueError("حدّد كمية المرتجع في سطرٍ واحد على الأقل")
    rows, t = compute(lines, orig["vat_rate"])
    cust = get_entity(conn, orig["customer_id"])
    cur = conn.execute(
        "INSERT INTO tax_sales(kind,customer_id,rep_id,doc_date,pay_mode,"
        "vat_rate,net,vat,total,ref_id,reason,notes,created_by)"
        " VALUES('credit',?,?,?,?,?,?,?,?,?,?,?,?)",
        (orig["customer_id"], orig["rep_id"], doc_date, orig["pay_mode"],
         t["rate"], t["net"], t["vat"], t["total"], original_id,
         reason.strip(), (notes or "").strip(), username))
    sid = cur.lastrowid
    no = f"TSR-{sid:05d}"
    _save_lines(conn, sid, rows)
    if orig["rep_id"]:
        # عبر المندوب: الضريبة وحدها تُردّ لحسابه، والإشعار يظهر في كشف
        # الشركة كما ظهرت فاتورتها
        rep = get_entity(conn, orig["rep_id"])
        je = [{"account_id": acc_id(conn, VAT_OUT), "cash_debit": t["vat"],
               "line_desc": f"عكس ضريبة {orig['doc_no']} — إشعار {no}"},
              {"account_id": rep["account_id"], "cash_credit": t["vat"],
               "line_desc": f"ضريبة مردودة — إشعار دائن {no} على "
                            f"{orig['doc_no']} ({cust['name']})"}]
        je += _memo(cust, rep, t["total"], f"إشعار دائن {no} على "
                    f"{orig['doc_no']}", credit=True)
    else:
        je = [{"account_id": acc_id(conn, RETURNS), "cash_debit": t["net"],
               "line_desc": f"مردود مبيعات ضريبية — {orig['doc_no']}"}]
        if t["vat"]:
            je.append({"account_id": acc_id(conn, VAT_OUT),
                       "cash_debit": t["vat"],
                       "line_desc": f"عكس ضريبة مخرجات {orig['doc_no']}"})
        je.append({"account_id": _party_account(conn, cust,
                                                orig["pay_mode"]),
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


# ══════════════════════════ عبر المندوب ══════════════════════════
# المندوب اشترى الأطقم من شاشة المبيعات (ذهبها وأجورها في حسابه)، ثم
# باعها لشركةٍ تطلب فاتورةً ضريبية باسمها. فتصدر الفاتورة هنا:
#   • باسم الشركة ورقمها الضريبي (هي المشتري لدى الهيئة)،
#   • وأسطرها أرقام التشغيل بأوزانها وأجورها من فاتورة بيع المندوب،
#   • ولا يُضاف لحساب المندوب إلا **الضريبة** — فالأجور عليه أصلاً،
#   • وتظهر الفاتورة كاملةً في كشف الشركة بسطرين متقابلين (عليها ثم
#     تُسدَّد عن طريق المندوب) فلا يبقى عليها رصيد،
#   • والمخزون والذهب لا يتحرّكان.
#
#     من حـ/ المندوب                  الضريبة
#         إلى حـ/ ضريبة المخرجات 2100  الضريبة
#     من حـ/ الشركة  الإجمالي  ⇄  إلى حـ/ الشركة  الإجمالي   (للاطلاع)

def _memo(company, rep, amount, label, credit=False):
    """سطران متقابلان في حساب الشركة: المستند ظاهرٌ في كشفها بلا رصيد."""
    if not company or not rep or company["id"] == rep["id"] or not amount:
        return []
    a, b = ("cash_credit", "cash_debit") if credit else \
        ("cash_debit", "cash_credit")
    return [{"account_id": company["account_id"], a: amount,
             "line_desc": label},
            {"account_id": company["account_id"], b: amount,
             "line_desc": f"يُسوّى عن طريق المندوب {rep['name']}"}]


def _taxed_weight(conn, item_id):
    """ما فُوتر ضريبياً من سطر البيع — الفواتير الحيّة ناقص إشعاراتها."""
    r = conn.execute(
        "SELECT COALESCE(SUM(CASE s.kind WHEN 'invoice' THEN l.qty"
        " WHEN 'credit' THEN -l.qty ELSE 0 END),0)"
        " FROM tax_sale_lines l JOIN tax_sales s ON s.id=l.sale_id"
        " WHERE l.sale_item_id=? AND s.is_deleted=0", (item_id,)).fetchone()
    return round(float(r[0] or 0), 6)


_ITEMS_SQL = (
    "SELECT ii.id item_id, ii.work_order_id, ii.registered_weight weight,"
    " ii.wage_per_gram, ii.wages, i.id invoice_id, i.invoice_no,"
    " i.invoice_date, i.vat_applied, i.customer_id, w.work_order_no wo_no,"
    " COALESCE(w.model_no,'') model_no, w.status, w.is_bulk"
    " FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id"
    " JOIN work_orders w ON w.id=ii.work_order_id"
    " WHERE i.is_deleted=0 AND i.kind='sale'")


def _still_with(conn, it):
    """الطقم ما زال مباعاً لهذا المندوب (لم يُرتجع ولم يُبَع لغيره)."""
    from models.inventory import is_bulk_no
    if it["is_bulk"] or is_bulk_no(it["wo_no"]):
        return True
    if it["status"] != "sold":
        return False
    last = conn.execute(
        "SELECT ii.id FROM invoice_items ii JOIN invoices i"
        " ON i.id=ii.invoice_id WHERE ii.work_order_id=? AND i.is_deleted=0"
        " ORDER BY i.invoice_date DESC, i.id DESC LIMIT 1",
        (it["work_order_id"],)).fetchone()
    return bool(last) and last["id"] == it["item_id"]


def _has_tdn(conn, invoice_id):
    try:
        return bool(conn.execute(
            "SELECT 1 FROM tax_debit_notes WHERE invoice_id=? AND"
            " is_deleted=0", (invoice_id,)).fetchone())
    except Exception:
        return False


def rep_items(conn, rep_id):
    """أطقم المندوب التي تصلح لفاتورةٍ ضريبية: بيعت له بلا ضريبة، وما
    زالت معه، ولم تُفوتر ضريبياً بعد."""
    ensure_tables(conn)
    out = []
    for it in conn.execute(_ITEMS_SQL + " AND i.customer_id=? AND"
                           " i.vat_applied=0 ORDER BY i.invoice_date, ii.id",
                           (rep_id,)):
        if _taxed_weight(conn, it["item_id"]) > 1e-9 \
                or _has_tdn(conn, it["invoice_id"]):
            continue
        if _still_with(conn, it):
            out.append(dict(it))
    return out


def find_rep_item(conn, rep_id, wo_no, exclude=()):
    """سطر بيع رقم التشغيل للمندوب — أو رسالةٌ تقول لماذا لا يصلح."""
    ensure_tables(conn)
    wo_no = str(wo_no or "").strip()
    if not wo_no:
        raise ValueError("اكتب رقم التشغيل")
    wo = conn.execute("SELECT id FROM work_orders WHERE work_order_no=?"
                      " AND is_deleted=0", (wo_no,)).fetchone()
    if not wo:
        raise ValueError(f"رقم التشغيل {wo_no} غير مسجّل")
    rows = conn.execute(_ITEMS_SQL + " AND ii.work_order_id=?"
                        " ORDER BY i.invoice_date DESC, ii.id DESC",
                        (wo["id"],)).fetchall()
    mine = [r for r in rows if r["customer_id"] == rep_id]
    if not mine:
        raise ValueError(f"رقم التشغيل {wo_no} لم يُبَع لهذا المندوب — "
                         "بِعه له أولاً من شاشة «مبيعات/مرتجعات»")
    last_err = ""
    for it in mine:
        if it["item_id"] in exclude:
            last_err = f"رقم التشغيل {wo_no} مضافٌ في الفاتورة"
            continue
        if it["vat_applied"]:
            last_err = (f"رقم التشغيل {wo_no} بيع بفاتورةٍ ضريبية أصلاً "
                        f"({it['invoice_no']}) — لا يُفوتر مرتين")
            continue
        if _has_tdn(conn, it["invoice_id"]):
            last_err = (f"فاتورة بيع رقم التشغيل {wo_no} ({it['invoice_no']})"
                        " صدر لها إشعار مدين ضريبي — ضريبتها مقيّدة")
            continue
        if _taxed_weight(conn, it["item_id"]) > 1e-9:
            last_err = (f"رقم التشغيل {wo_no} صدرت له فاتورةٌ ضريبية من "
                        "قبل")
            continue
        if not _still_with(conn, it):
            last_err = (f"رقم التشغيل {wo_no} لم يعد مع المندوب "
                        "(أُرجع أو بيع لغيره)")
            continue
        return dict(it)
    raise ValueError(last_err or f"رقم التشغيل {wo_no} لا يصلح")


def _rep_line(it, wage_per_gram=None):
    from services import karat_view as kv
    rate = float(it["wage_per_gram"] if wage_per_gram is None
                 else wage_per_gram)
    desc = (f"موديل {it['model_no'] or '—'} — رقم التشغيل {it['wo_no']} — "
            f"{kv.g(it['weight']):,.3f} {kv.unit()}")
    return {"description": desc, "qty": float(it["weight"]),
            "unit_price": rate, "discount": 0,
            "sale_item_id": it["item_id"],
            "work_order_id": it["work_order_id"], "wo_no": it["wo_no"],
            "model_no": it["model_no"]}


def spread_discount(grosses, discount):
    """يوزّع خصم الفاتورة على أسطرها بنسبة أجور كلٍّ منها.

    الخصم في الفاتورة الإلكترونية يُحمل على السطر (صافي السطر بعد خصمه)
    فيطابق مجموعُ الأسطر إجماليَّ الفاتورة هللةً بهللة. وفرق التقريب
    يُحمَّل على أكبر سطرٍ — فلا يتجاوز خصمُ سطرٍ قيمتَه.
    """
    disc = float(money(discount or 0))
    tot = float(sum(grosses))
    if disc <= 0 or not grosses:
        return [0.0] * len(grosses)
    if disc > tot + 1e-9:
        raise ValueError(f"الخصم {disc:,.2f} أكبر من إجمالي الأجور "
                         f"{tot:,.2f}")
    shares = [float(money(disc * g / tot)) for g in grosses]
    big = max(range(len(grosses)), key=lambda i: grosses[i])
    shares[big] = float(money(shares[big] + disc - sum(shares)))
    return shares


def create_rep_invoice(conn, company_id, rep_id, doc_date, items, username,
                       notes="", discount=0.0):
    """فاتورة ضريبية باسم الشركة عن أطقمٍ بيعت للمندوب.

    `items` = [{sale_item_id, wage_per_gram (اختياري — بمكافئ 18)}].
    `discount` خصمٌ على الفاتورة قبل الضريبة — يُوزَّع على الأسطر.
    """
    ensure_tables(conn)
    comp = get_entity(conn, company_id)
    rep = get_entity(conn, rep_id)
    if not comp or comp["entity_type"] not in ("customer", "other"):
        raise ValueError("اختر الشركة (المشتري) من دليل جهات التعامل")
    if not rep or rep["entity_type"] not in ("customer", "other"):
        raise ValueError("اختر المندوب — العميل الذي بيعت له الأطقم")
    avail = {it["item_id"]: it for it in rep_items(conn, rep_id)}
    lines, seen = [], set()
    for x in items or []:
        iid = x.get("sale_item_id")
        if iid in seen:
            raise ValueError("رقم تشغيلٍ مكرّر في الفاتورة")
        seen.add(iid)
        it = avail.get(iid)
        if not it:
            raise ValueError("سطرٌ لم يعد صالحاً (فُوتر أو أُرجع) — أعد "
                             "إضافته")
        lines.append(_rep_line(it, x.get("wage_per_gram")))
    grosses = [float(money(li["qty"] * li["unit_price"])) for li in lines]
    for li, d in zip(lines, spread_discount(grosses, discount)):
        li["discount"] = d
    rows, t = compute(lines)
    if t["vat"] <= 0:
        raise ValueError("لا أجور في الفاتورة — لا ضريبة عليها")
    cur = conn.execute(
        "INSERT INTO tax_sales(kind,customer_id,rep_id,doc_date,pay_mode,"
        "vat_rate,net,vat,total,notes,created_by)"
        " VALUES('invoice',?,?,?,'credit',?,?,?,?,?,?)",
        (company_id, rep_id, doc_date, t["rate"], t["net"], t["vat"],
         t["total"], (notes or "").strip(), username))
    sid = cur.lastrowid
    no = f"TS-{sid:05d}"
    _save_lines(conn, sid, rows)
    je = [{"account_id": rep["account_id"], "cash_debit": t["vat"],
           "line_desc": f"ضريبة الفاتورة الضريبية {no} — {comp['name']}"},
          {"account_id": acc_id(conn, VAT_OUT), "cash_credit": t["vat"],
           "line_desc": f"ضريبة مخرجات {no}"}]
    je += _memo(comp, rep, t["total"],
                f"فاتورة ضريبية {no} — أجور {t['net']:,.2f} + ضريبة "
                f"{t['vat']:,.2f}")
    entry_id = post_entry(conn, doc_date, f"فاتورة ضريبية {no} — "
                          f"{comp['name']} — المندوب {rep['name']}", je,
                          source_table="tax_sales", source_id=sid,
                          username=username, note=notes)
    conn.execute("UPDATE tax_sales SET doc_no=?, entry_id=? WHERE id=?",
                 (no, entry_id, sid))
    qr = _issue_einvoice(conn, sid, username)
    log_action(conn, username, "create", "tax_sales", sid,
               f"{no} company={comp['name']} rep={rep['name']} "
               f"vat={t['vat']}")
    return {"id": sid, "doc_no": no, "entry_id": entry_id, "qr": qr,
            "customer_name": comp["name"], "rep_name": rep["name"], **t}


def create_debit_note(conn, original_id, doc_date, amount, reason, username,
                      description="", notes=""):
    """إشعار مدين: زيادةٌ على فاتورةٍ ضريبية (فرق سعر أو أجر).

    الزيادة لم تُحمَّل على أحدٍ من قبل، فتُقيَّد كاملةً مع ضريبتها على
    من تُحمَّل عليه الفاتورة: المندوب إن صدرت عبره، وإلا العميل (أو
    الصندوق/البنك بطريقة دفع الأصل). والإيراد في المبيعات الضريبية.
    """
    ensure_tables(conn)
    orig = conn.execute("SELECT * FROM tax_sales WHERE id=? AND is_deleted=0"
                        " AND kind='invoice'", (original_id,)).fetchone()
    if not orig:
        raise ValueError("اختر الفاتورة الضريبية الأصلية")
    if not str(reason or "").strip():
        raise ValueError("اكتب سبب الإشعار المدين (إلزامي لدى الهيئة)")
    amount = float(money(amount or 0))
    if amount <= 0:
        raise ValueError("اكتب مبلغ الزيادة قبل الضريبة")
    desc = (description or "").strip() or f"زيادة على الفاتورة " \
        f"{orig['doc_no']}"
    rows, t = compute([{"description": desc, "qty": 1, "unit_price": amount}],
                      orig["vat_rate"])
    cust = get_entity(conn, orig["customer_id"])
    cur = conn.execute(
        "INSERT INTO tax_sales(kind,customer_id,rep_id,doc_date,pay_mode,"
        "vat_rate,net,vat,total,ref_id,reason,notes,created_by)"
        " VALUES('debit',?,?,?,?,?,?,?,?,?,?,?,?)",
        (orig["customer_id"], orig["rep_id"], doc_date, orig["pay_mode"],
         t["rate"], t["net"], t["vat"], t["total"], original_id,
         reason.strip(), (notes or "").strip(), username))
    sid = cur.lastrowid
    no = f"TSD-{sid:05d}"
    _save_lines(conn, sid, rows)
    if orig["rep_id"]:
        rep = get_entity(conn, orig["rep_id"])
        party = rep["account_id"]
    else:
        rep = None
        party = _party_account(conn, cust, orig["pay_mode"])
    je = [{"account_id": party, "cash_debit": t["total"],
           "line_desc": f"إشعار مدين {no} على {orig['doc_no']}"
                        + (f" ({cust['name']})" if rep else "")},
          {"account_id": acc_id(conn, REVENUE), "cash_credit": t["net"],
           "line_desc": f"زيادة مبيعات ضريبية — {orig['doc_no']}"},
          {"account_id": acc_id(conn, VAT_OUT), "cash_credit": t["vat"],
           "line_desc": f"ضريبة مخرجات — إشعار مدين {no}"}]
    if rep:
        je += _memo(cust, rep, t["total"],
                    f"إشعار مدين {no} على {orig['doc_no']}")
    entry_id = post_entry(conn, doc_date, f"إشعار مدين {no} — "
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
            "unit_price,discount,net,vat,total,src_line_id,sale_item_id,"
            "work_order_id,wo_no,model_no)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, li["line_no"], li["description"], li["qty"],
             li["unit_price"], li["discount"], li["net"], li["vat"],
             li["total"], li.get("src_line_id"), li.get("sale_item_id"),
             li.get("work_order_id"), li.get("wo_no") or "",
             li.get("model_no") or ""))


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
        if li["wo_no"]:
            from services import karat_view as kv
            extra = f" × أجر {kv.rate(li['unit_price']):,.2f} ريال/جم"
        else:
            extra = (f" — {li['qty']:g} × {li['unit_price']:,.2f}"
                     + (f" − خصم {li['discount']:,.2f}"
                        if li["discount"] else ""))
        lines.append({"name": li["description"] + extra, "amount": li["net"]})
    doc = {
        "kind": s["kind"],
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
    if s["kind"] in ("credit", "debit"):
        ref = conn.execute("SELECT doc_no FROM tax_sales WHERE id=?",
                           (s["ref_id"],)).fetchone()
        doc["billing_refs"] = [ref["doc_no"] if ref else "—"]
        doc["reason"] = s["reason"] or ("مرتجع" if s["kind"] == "credit"
                                        else "زيادة")
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
        " r.doc_no ref_no, m.name rep_name FROM tax_sales s JOIN entities e"
        " ON e.id=s.customer_id LEFT JOIN tax_sales r ON r.id=s.ref_id"
        " LEFT JOIN entities m ON m.id=s.rep_id"
        " WHERE s.id=?", (sale_id,)).fetchone()
    if not s:
        return None, []
    lines = conn.execute("SELECT * FROM tax_sale_lines WHERE sale_id=?"
                         " ORDER BY line_no", (sale_id,)).fetchall()
    return s, lines


def search(conn, q="", date_from=None, date_to=None, kind=None, limit=1000):
    ensure_tables(conn)
    sql = ("SELECT s.*, e.name customer_name, e.vat_number customer_vat,"
           " r.doc_no ref_no, m.name rep_name FROM tax_sales s"
           " JOIN entities e ON e.id=s.customer_id"
           " LEFT JOIN entities m ON m.id=s.rep_id"
           " LEFT JOIN tax_sales r ON r.id=s.ref_id WHERE s.is_deleted=0")
    params = []
    if q:
        sql += (" AND (s.doc_no LIKE ? OR e.name LIKE ? OR s.notes LIKE ?"
                " OR m.name LIKE ?)")
        params += [f"%{q}%"] * 4
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


SUBTYPE_LABEL = {"standard": "ضريبية", "simplified": "مبسطة"}


def subtype(conn, s):
    """ضريبية أم مبسطة؟ ما صدر به المستند الإلكتروني إن وُجد، وإلا
    بالرقم الضريبي للمشتري: صحيحٌ ⇒ ضريبية (شركة)، وإلا مبسطة (فرد)."""
    try:
        d = conn.execute(
            "SELECT subtype FROM fatoora_documents WHERE source_table="
            "'tax_sales' AND source_id=? AND archived=0 ORDER BY icv DESC"
            " LIMIT 1", (s["id"],)).fetchone()
        if d:
            return d["subtype"]
    except Exception:
        pass
    from services.fatoora import profile as pf
    vat = s["customer_vat"] if "customer_vat" in s.keys() else None
    if vat is None:
        e = conn.execute("SELECT vat_number FROM entities WHERE id=?",
                         (s["customer_id"],)).fetchone()
        vat = e["vat_number"] if e else ""
    return "standard" if pf.valid_vat(vat) else "simplified"


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
    z = {"n": 0, "net": 0, "vat": 0, "total": 0}
    inv, crd, dbt = (d.get(k, dict(z)) for k in ("invoice", "credit",
                                                   "debit"))
    return {"invoices": inv, "credits": crd, "debits": dbt,
            **{k: round(inv[k] + dbt[k] - crd[k], 2)
               for k in ("net", "vat", "total")}}
