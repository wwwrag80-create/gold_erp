# -*- coding: utf-8 -*-
"""المشتريات (تشغيلية/أصول) — آجلةٌ على حساب المورد (تُسدَّد لاحقاً بسند
صرف)، أو نقداً من الصندوق، أو بتحويلٍ من البنك.

وتُسجَّل **كما تطلبها الضريبة**: رقم فاتورة المورد (ولا تُقيَّد الفاتورة
نفسها مرتين)، ومعالجتها الضريبية، والحساب الذي تُحمَّل عليه، وإدخال
المبلغ صافياً أو شاملاً — فيخرج منها سجل المشتريات الضريبية وضريبة
المدخلات القابلة للخصم في الإقرار."""
import config
from models import numbering as _numbering
from models.accounts import acc_id
from models.entities import get_entity
from services.accounting_engine import post_entry
from services.audit import log_action

# ══ المعالجة الضريبية لفاتورة المورد ══
# ضريبة المدخلات لا تُخصم إلا بفاتورةٍ ضريبية من موردٍ مسجّل. وما عدا
# ذلك: لا ضريبة أصلاً (صفرية/معفاة/مورد غير مسجّل)، أو ضريبةٌ مدفوعة لا
# تُسترد (الضيافة مثلاً) فتُحمَّل على التكلفة لا على حساب 1900.
TAX_TREATMENTS = (
    ("standard", "خاضعة 15% — ضريبة مدخلات قابلة للخصم"),
    ("blocked", "خاضعة — ضريبة غير قابلة للاسترداد (تُضاف للتكلفة)"),
    ("zero", "خاضعة بنسبة صفر 0%"),
    ("exempt", "معفاة من الضريبة"),
    ("unregistered", "مورد غير مسجّل في الضريبة"),
)
NO_VAT = ("zero", "exempt", "unregistered")
PAY_MODES = (("credit", "آجل — على حساب المورد"),
             ("cash", "نقداً — يُخصم من الصندوق"),
             ("bank", "تحويل بنكي — يُخصم من البنك"))
PAY_ACCOUNTS = {"cash": "1400", "bank": "1500"}
# ورقة المورد: «فاتورة ضريبية» (باسم المصنع ورقمه الضريبي) أو «مبسطة»
# (بلا بيانات المشتري — كإيصال محطة أو مطعم). كلتاهما تُثبت ضريبة
# المدخلات، والفرق يُحفظ ليظهر في السجل عند الفحص الضريبي.
INVOICE_TYPES = (("standard", "فاتورة ضريبية"),
                 ("simplified", "فاتورة ضريبية مبسطة"))
PRICE_MODES = (("net", "المبلغ قبل الضريبة"),
               ("gross", "المبلغ شامل الضريبة"))
VAT_IN = "1900"
# الأصل الثابت يُقيَّد على فرعٍ من «الممتلكات والمعدات» لا على المجموعة
DEFAULT_ACCOUNT = {"expense": "5500", "asset": "1710"}
# مصروفاتٌ لا تُشترى من مورد: الإهلاك قيدٌ آلي، والرواتب من شاشتها،
# والخصومات والفروقات تسويات — فلا تظهر في قائمة حساب المصروف.
_NOT_PURCHASABLE = ("5860", "5700", "5710", "5200", "5250", "5300", "5600")


def split_amount(value, price_mode="net", treatment="standard", rate=None,
                 discount=0.0):
    """(الصافي، الضريبة) من المبلغ المكتوب — بطريقة إدخاله، بعد خصمه.

    الخصم بطريقة المبلغ نفسها: من المبلغ قبل الضريبة إن كُتب صافياً،
    ومن الشامل إن كُتب شاملاً.

    شامل الضريبة: الصافي = المبلغ × 100 ÷ 115 والضريبة الباقي — فلا تضيع
    هللة بين الصافي والضريبة والإجمالي المكتوب على فاتورة المورد.
    """
    r = config.VAT_RATE if rate is None else rate
    v = round(float(value or 0) - float(discount or 0), 2)
    if treatment in NO_VAT:
        return v, 0.0
    if price_mode == "gross":
        net = round(v / (1 + r), 2)
        return net, round(v - net, 2)
    return v, round(v * r, 2)


def purchase_accounts(conn, kind):
    """الحسابات التي يُقيَّد عليها الشراء: مصروفٌ نقدي أو أصلٌ ثابت."""
    if kind == "asset":
        from models.assets import depreciable_accounts
        return depreciable_accounts(conn)
    return [dict(r) for r in conn.execute(
        "SELECT id, code, name FROM accounts WHERE type='expense'"
        " AND is_active=1 AND is_postable=1 AND balance_type<>'gold'"
        " AND code NOT IN (%s) ORDER BY code"
        % ",".join("?" * len(_NOT_PURCHASABLE)), _NOT_PURCHASABLE)]


def ensure_schema(conn):
    """أسطر فاتورة المورد (4.48): لكل سطرٍ حسابه وعدده وسعره وخصمه
    وضريبته — فاتورةٌ واحدة تُحمَّل على أكثر من حساب."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS purchase_lines("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " purchase_id INTEGER NOT NULL REFERENCES purchases(id),"
        " line_no INTEGER NOT NULL,"
        " account_id INTEGER NOT NULL REFERENCES accounts(id),"
        " description TEXT NOT NULL DEFAULT '',"
        " qty REAL NOT NULL DEFAULT 1, unit_price REAL NOT NULL DEFAULT 0,"
        " gross REAL NOT NULL DEFAULT 0, discount REAL NOT NULL DEFAULT 0,"
        " net REAL NOT NULL DEFAULT 0, vat REAL NOT NULL DEFAULT 0,"
        " total REAL NOT NULL DEFAULT 0,"
        " asset_id INTEGER REFERENCES fixed_assets(id))")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_purchase_lines"
                 " ON purchase_lines(purchase_id)")


def lines_of(conn, purchase_id):
    """أسطر الفاتورة — وفاتورةٌ قديمة بلا أسطر تُقرأ سطراً واحداً."""
    import sqlite3
    try:        # قراءةٌ فقط (قد تكون المعاملة للقراءة) — الجدول من الترقية
        rows = conn.execute(
            "SELECT l.*, a.code acc_code, a.name acc_name FROM purchase_lines"
            " l JOIN accounts a ON a.id=l.account_id WHERE l.purchase_id=?"
            " ORDER BY l.line_no", (purchase_id,)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    if rows:
        return [dict(r) for r in rows]
    p = conn.execute(
        "SELECT p.*, a.code acc_code, a.name acc_name FROM purchases p"
        " LEFT JOIN accounts a ON a.id=p.account_id WHERE p.id=?",
        (purchase_id,)).fetchone()
    if not p:
        return []
    disc = float(p["discount"] or 0)
    net = float(p["amount"] or 0)
    return [{"line_no": 1, "account_id": p["account_id"],
             "acc_code": p["acc_code"], "acc_name": p["acc_name"],
             "description": p["description"] or "", "qty": 1.0,
             "unit_price": round(net + disc, 2), "gross": round(net + disc, 2),
             "discount": disc, "net": net,
             "vat": float(p["vat_amount"] or 0),
             "total": float(p["total"] or 0), "asset_id": p["asset_id"]}]


def compute_line(qty, unit_price, discount=0.0, treatment="standard",
                 vat=None, rate=None):
    """سطرٌ بترتيب ورقة المورد: العدد × السعر = المبلغ قبل الضريبة، ثم
    الخصم، ثم الضريبة على الصافي (أو ما كُتب يدوياً)، ثم بعد الضريبة."""
    r = config.VAT_RATE if rate is None else rate
    qty = float(qty or 0)
    gross = round(qty * float(unit_price or 0), 2)
    disc = round(float(discount or 0), 2)
    net = round(gross - disc, 2)
    if treatment in NO_VAT:
        v = 0.0
    elif vat is None:
        v = round(net * r, 2)
    else:
        v = round(float(vat or 0), 2)
    return {"qty": qty, "unit_price": float(unit_price or 0),
            "gross": gross, "discount": disc, "net": net, "vat": v,
            "total": round(net + v, 2)}


def _resolve_account(conn, kind, account_code):
    code = (account_code or DEFAULT_ACCOUNT[kind]).strip()
    ok = {a["code"]: a for a in purchase_accounts(conn, kind)}
    if code not in ok:
        raise ValueError("اختر حساب " + ("الأصل الثابت" if kind == "asset"
                                         else "المصروف") + " من القائمة")
    return ok[code]


def create_purchase(conn, kind, supplier_id, description, amount, vat_amount,
                    purchase_date, username, supplier_invoice_no="",
                    tax_treatment="standard", account_code=None,
                    price_mode="net", life_months=0, discount=0.0,
                    pay_mode="credit", invoice_type="standard", lines=None):
    """فاتورة مورد آجلة — `amount` الصافي الخاضع (بعد الخصم وقبل الضريبة)
    و`vat_amount` ضريبته، و`discount` خصم المورد قبل الضريبة (للبيان).

    الخصم التجاري يُنقص التكلفة نفسها — فالمصروف أو الأصل يُقيَّد بصافيه
    بعد الخصم، والضريبة على الصافي، كما في ورقة المورد.

    `lines` (4.48): أسطرٌ لكلٍّ حسابها — [{account_code, qty, unit_price,
    discount, vat (اختياري), description}] — فتُهمَل حينها `amount`
    و`vat_amount` و`discount` و`account_code` وتُجمع من الأسطر. وبلا
    أسطر تُقرأ الفاتورة سطراً واحداً كما كانت.

    القيد:
        من حـ/ المصروف أو الأصل       الصافي (+ الضريبة إن لم تُسترد)
        من حـ/ ضريبة المدخلات 1900     الضريبة (الخاضعة القابلة للخصم)
            إلى حـ/ المورد             الإجمالي
    """
    from services.fatoora import profile as pf
    if kind not in ("expense", "asset"):
        raise ValueError("نوع الفاتورة غير صحيح")
    if tax_treatment not in dict(TAX_TREATMENTS):
        raise ValueError("المعالجة الضريبية غير معروفة")
    if price_mode not in dict(PRICE_MODES):
        price_mode = "net"
    if pay_mode not in dict(PAY_MODES):
        raise ValueError("طريقة الدفع غير معروفة")
    if invoice_type not in dict(INVOICE_TYPES):
        invoice_type = "standard"
    sup = get_entity(conn, supplier_id)
    if not sup or sup["entity_type"] != "supplier":
        raise ValueError("اختر مورداً من دليل جهات التعامل")
    ensure_schema(conn)
    description = (description or "").strip()
    supplier_invoice_no = (supplier_invoice_no or "").strip()
    if lines is None:
        # فاتورةٌ بمبلغٍ واحد: سطرٌ واحد على الحساب المختار
        _a = round(float(amount or 0), 2)
        _d = round(float(discount or 0), 2)
        lines = [{"account_code": account_code, "qty": 1,
                  "unit_price": round(_a + _d, 2), "discount": _d,
                  "vat": round(float(vat_amount or 0), 2),
                  "description": description}]
    rows = []
    for i, li in enumerate(lines or [], 1):
        c = compute_line(li.get("qty", 1), li.get("unit_price"),
                         li.get("discount"), tax_treatment, li.get("vat"))
        if c["qty"] <= 0:
            raise ValueError(f"السطر {i}: العدد يجب أن يكون أكبر من صفر")
        if c["unit_price"] < 0 or c["discount"] < 0 or c["vat"] < 0:
            raise ValueError(f"السطر {i}: لا تُقبل مبالغ سالبة")
        if c["net"] <= 0:
            raise ValueError(f"السطر {i}: المبلغ بعد الخصم يجب أن يكون"
                             " أكبر من صفر")
        if tax_treatment in NO_VAT and li.get("vat"):
            raise ValueError(f"«{dict(TAX_TREATMENTS)[tax_treatment]}» لا "
                             "ضريبة فيها — اجعل الضريبة صفراً أو غيّر "
                             "المعالجة")
        if c["vat"] > round(c["net"] * config.VAT_RATE, 2) + 1:
            raise ValueError(f"السطر {i}: الضريبة أكبر من 15% من صافيه —"
                             " راجع المبلغين")
        c["acc"] = _resolve_account(conn, kind, li.get("account_code"))
        c["description"] = (str(li.get("description") or "").strip()
                            or description)
        c["line_no"] = i
        rows.append(c)
    if not rows:
        raise ValueError("أضف سطراً واحداً على الأقل")
    if not description:
        description = rows[0]["description"]
    if not description:
        raise ValueError("أدخل بيان الفاتورة")
    amount = round(sum(r["net"] for r in rows), 2)
    vat_amount = round(sum(r["vat"] for r in rows), 2)
    discount = round(sum(r["discount"] for r in rows), 2)
    if amount <= 0:
        raise ValueError("أدخل مبلغ الفاتورة")
    if tax_treatment == "standard" and vat_amount:
        if not pf.valid_vat(sup["vat_number"]):
            raise ValueError(
                f"لا تُخصم ضريبة المدخلات إلا بفاتورةٍ ضريبية من موردٍ "
                f"مسجّل. الرقم الضريبي للمورد «{sup['name']}» "
                f"({sup['vat_number'] or 'فارغ'}) غير صحيح — 15 رقماً يبدأ "
                "بـ3 وينتهي بـ3. صحّحه من دليل جهات التعامل، أو اختر "
                "«ضريبة غير قابلة للاسترداد».")
    if supplier_invoice_no:
        dup = conn.execute(
            "SELECT purchase_no FROM purchases WHERE is_deleted=0 AND"
            " supplier_id=? AND supplier_invoice_no=?",
            (supplier_id, supplier_invoice_no)).fetchone()
        if dup:
            raise ValueError(f"فاتورة المورد رقم {supplier_invoice_no} "
                             f"مسجّلة من قبل ({dup['purchase_no']}) — لا "
                             "تُقيَّد مرتين")
    claim = tax_treatment == "standard" and vat_amount > 0
    total = round(amount + vat_amount, 2)
    for r in rows:
        r["cost"] = r["net"] if claim or not r["vat"] else r["total"]
    cost = round(sum(r["cost"] for r in rows), 2)
    acc = rows[0]["acc"]

    asset_id = None
    if kind == "asset":
        # كل سطرٍ أصلٌ مستقل بتكلفته وحسابه — يُهلَك وحده
        for r in rows:
            cur = conn.execute(
                "INSERT INTO fixed_assets(name,purchase_date,cost,created_by,"
                "account_id,start_date,life_months) VALUES(?,?,?,?,?,?,?)",
                (r["description"] if len(rows) == 1 else
                 f"{r['description']} — {r['acc']['name']} ({r['line_no']})",
                 purchase_date, r["cost"], username,
                 r["acc"]["id"], purchase_date, int(life_months or 0)))
            r["asset_id"] = cur.lastrowid
        asset_id = rows[0]["asset_id"]

    ref = f" — فاتورة المورد {supplier_invoice_no}" if supplier_invoice_no \
        else ""
    # سطرٌ مدين لكل حساب (أسطر الحساب الواحد تُجمع)
    by_acc = {}
    for r in rows:
        k = r["acc"]["id"]
        if k in by_acc:
            by_acc[k]["cash_debit"] = round(by_acc[k]["cash_debit"]
                                            + r["cost"], 2)
            if r["description"] not in by_acc[k]["line_desc"]:
                by_acc[k]["line_desc"] += f" · {r['description']}"
        else:
            by_acc[k] = {"account_id": k, "cash_debit": r["cost"],
                         "line_desc": r["description"]
                         + ("" if claim or not r["vat"]
                            else " (شامل ضريبة لا تُسترد)")}
    lines = list(by_acc.values())
    if claim:
        lines.append({"account_id": acc_id(conn, VAT_IN),
                      "cash_debit": vat_amount,
                      "line_desc": "ضريبة مدخلات" + ref})
    if pay_mode == "credit":
        lines.append({"account_id": sup["account_id"], "cash_credit": total,
                      "line_desc": "مشتريات آجلة" + ref})
    else:
        # نقداً/بنكاً: الدفع من الصندوق أو البنك مباشرةً — والمورد لا
        # يبقى له رصيد
        lines.append({"account_id": acc_id(conn, PAY_ACCOUNTS[pay_mode]),
                      "cash_credit": total,
                      "line_desc": f"مشتريات {'نقداً' if pay_mode == 'cash' else 'بتحويل بنكي'}"
                                   f" — {sup['name']}" + ref})

    cur = conn.execute(
        "INSERT INTO purchases(purchase_date,supplier,supplier_id,kind,"
        "description,amount,vat_amount,total,asset_id,created_by,"
        "supplier_invoice_no,tax_treatment,account_id,price_mode,discount,"
        "pay_mode,invoice_type)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (purchase_date, sup["name"], supplier_id, kind, description,
         amount, vat_amount, total, asset_id, username, supplier_invoice_no,
         tax_treatment, acc["id"], price_mode, discount, pay_mode,
         invoice_type))
    p_id = cur.lastrowid
    for r in rows:
        conn.execute(
            "INSERT INTO purchase_lines(purchase_id,line_no,account_id,"
            "description,qty,unit_price,gross,discount,net,vat,total,"
            "asset_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (p_id, r["line_no"], r["acc"]["id"], r["description"], r["qty"],
             r["unit_price"], r["gross"], r["discount"], r["net"], r["vat"],
             r["total"], r.get("asset_id")))
    p_no = _numbering.next_no(conn, "P")
    label = "شراء أصل ثابت" if kind == "asset" else "مشتريات تشغيلية"
    how = {"credit": "آجلة", "cash": "نقداً", "bank": "بتحويل بنكي"}[pay_mode]
    entry_id = post_entry(
        conn, purchase_date,
        f"{label} {how} {p_no} — المورد {sup['name']}{ref} — {description}",
        lines, source_table="purchases", source_id=p_id, username=username,
        note=description, doc_no=p_no)
    conn.execute("UPDATE purchases SET purchase_no=?, entry_id=? WHERE id=?",
                 (p_no, entry_id, p_id))
    log_action(conn, username, "create", "purchases", p_id, p_no)
    return {"id": p_id, "purchase_no": p_no, "total": total,
            "pay_mode": pay_mode,
            "asset_id": asset_id, "entry_id": entry_id,
            "supplier_name": sup["name"], "claimed_vat": vat_amount
            if claim else 0.0, "cost": cost, "lines": len(rows)}


def vat_register(conn, date_from, date_to):
    """سجل المشتريات الضريبية للفترة — ما يُطلب عند الفحص الضريبي:
    رقم فاتورة المورد ورقمه الضريبي والصافي والضريبة لكل فاتورة."""
    rows = conn.execute(
        "SELECT p.*, COALESCE(e.name, p.supplier) supplier_name,"
        " e.vat_number supplier_vat, a.code acc_code, a.name acc_name"
        " FROM purchases p LEFT JOIN entities e ON e.id=p.supplier_id"
        " LEFT JOIN accounts a ON a.id=p.account_id"
        " WHERE p.is_deleted=0 AND p.purchase_date BETWEEN ? AND ?"
        " ORDER BY p.purchase_date, p.id", (date_from, date_to)).fetchall()
    tot = {"n": len(rows), "net": 0.0, "vat": 0.0, "claimed": 0.0,
           "total": 0.0, "discount": 0.0}
    by = {}
    for r in rows:
        tr = r["tax_treatment"] or "standard"
        tot["net"] += r["amount"] or 0
        tot["vat"] += r["vat_amount"] or 0
        tot["total"] += r["total"] or 0
        tot["discount"] += r["discount"] or 0
        if tr == "standard":
            tot["claimed"] += r["vat_amount"] or 0
        b = by.setdefault(tr, {"n": 0, "net": 0.0, "vat": 0.0})
        b["n"] += 1
        b["net"] += r["amount"] or 0
        b["vat"] += r["vat_amount"] or 0
    tot = {k: round(v, 2) if isinstance(v, float) else v
           for k, v in tot.items()}
    return rows, tot, by


def list_assets(conn):
    """سجل الأصول الثابتة بقيمتها الدفترية فقط (بلا إهلاك)."""
    return conn.execute(
        "SELECT * FROM fixed_assets WHERE is_deleted=0 ORDER BY id").fetchall()


def recent_purchases(conn, limit=20):
    return conn.execute(
        "SELECT * FROM purchases WHERE is_deleted=0 ORDER BY id DESC LIMIT ?",
        (limit,)).fetchall()


def search_purchases(conn, q="", date_from=None, date_to=None, limit=200):
    sql = ("SELECT p.*, COALESCE(e.name, p.supplier) supplier_name"
          " FROM purchases p LEFT JOIN entities e ON e.id=p.supplier_id"
          " WHERE p.is_deleted=0")
    params = []
    if q:
        sql += (" AND (p.purchase_no LIKE ? OR p.description LIKE ?"
               " OR p.supplier LIKE ? OR e.name LIKE ?)")
        params += [f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%"]
    if date_from:
        sql += " AND p.purchase_date>=?"; params.append(date_from)
    if date_to:
        sql += " AND p.purchase_date<=?"; params.append(date_to)
    sql += " ORDER BY p.id DESC LIMIT ?"; params.append(limit)
    return conn.execute(sql, params).fetchall()


