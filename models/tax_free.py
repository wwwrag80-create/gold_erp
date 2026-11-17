# -*- coding: utf-8 -*-
"""الإدخال اليدوي الحر في المبيعات والمشتريات الضريبية (5.8.0).

**لماذا**: في سوق الذهب يأتي الطقم برقم تشغيل مورّده — وقد يبيعك عميلٌ
«الرقم 1» بوزن 10، ويبيعك مندوبٌ آخر «الرقم 1» بوزن 30. ويبيع المحلّ
بالفاتورة الضريبية ما ليس في خزنته بعدُ. فالرقم هنا **وصفٌ للسطر** يُكتب
يدوياً مع وزنه وعياره، لا بطاقة طقمٍ في الخزنة.

**أين يذهب الوزن**: إلى «مخزون الذهب الضريبي» 1230 (أو حسابٍ يختاره
المستخدم من حسابات الذهب — عدا الذهب المشغول والإيطالي): الشراء يُدخل فيه
الوزن والبيع يُخرجه، **ويقبل السالب** (بيعٌ قبل شراء). أما أطقم الخزنة
الحقيقية وحساب الذهب المشغول وحمايته فلا تُمسّ — ومن أراد البيع من الخزنة
اختار في الشاشة «من أطقم الخزنة» فسار على الطريق القديم كما هو.

**المستند**: فاتورة البيع الحر فاتورة بيعٍ حقيقية في جدول `invoices`
(رقمها وقيدها وضريبتها ونوعها ومشتريها وفاتورتها الإلكترونية وإشعارها
الدائن) — وأسطرها في `tax_free_lines` لا في `invoice_items` (تلك لأطقم
الخزنة). والقيد هو قيد فاتورة البيع نفسه (`invoices._entry_lines`) بحساب
المخزون المختار.

**الخصم النقدي** (للمستند كله): يُطرح من الوعاء قبل الضريبة — الضريبة على
(الصافي − الخصم) — ويُقيَّد في «خصم مسموح به نقداً» 5200 في المبيعات،
و«خصم مكتسب من الموردين» 4600 في المشتريات. والإشعار الدائن يردّ من الخصم
بنسبة ما أُرجع.
"""
from services import numfmt as _nf

TAX_STOCK = "1230"                 # مخزون الذهب الضريبي (متاجرة بالوزن)
DISC_ALLOWED = "5200"              # خصم مسموح به نقداً (المبيعات)
DISC_EARNED = "4600"               # خصم مكتسب من الموردين (المشتريات)
GUARDED = ("1200", "1210")         # تحت حماية المخزون — لا يدخلها الحر
MODES = (("free", "إدخال يدوي حر — أي رقم تشغيل بوزنه وعياره"),
         ("vault", "من أطقم الخزنة — يخرج الطقم من خزنتك"))
MODE_LABEL = {"free": "إدخال يدوي", "vault": "من أطقم الخزنة"}

_ACCOUNTS = (
    (TAX_STOCK, "مخزون الذهب الضريبي (متاجرة بالوزن)", "asset", "1020", "gold",
     "debit"),
    (DISC_EARNED, "خصم مكتسب من الموردين", "revenue", "4000", "cash",
     "credit"),
    # 5.8.1: المشتريات الضريبية ومردوداتها ومقابل وزنها
    ("5540", "المشتريات الضريبية", "expense", "5050", "both", "debit"),
    ("5545", "مردودات المشتريات الضريبية", "expense", "5050", "both",
     "credit"),
    ("5549", "الذهب المستلم للمخزون (مقابل المشتريات وزناً)", "expense",
     "5050", "gold", "credit"),
)


# ══════════════════════════ المخطط ══════════════════════════
def ensure_schema(conn):
    """جدول الأسطر الحرة وأعمدتها، والحسابان — مرةً ولا تمسّ القائم."""
    from models import tax_invoices as _tx
    _tx.ensure_schema(conn)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tax_free_lines("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " invoice_id INTEGER NOT NULL REFERENCES invoices(id)"
        " ON DELETE CASCADE,"
        " line_no INTEGER NOT NULL, wo_no TEXT NOT NULL,"
        " model_no TEXT NOT NULL DEFAULT '', pieces INTEGER NOT NULL DEFAULT 1,"
        " weight REAL NOT NULL, karat INTEGER NOT NULL DEFAULT 18,"
        " wage_per_gram REAL NOT NULL DEFAULT 0,"
        " piece_price REAL NOT NULL DEFAULT 0,"
        " gold_price REAL NOT NULL DEFAULT 0,"
        " gold_value REAL NOT NULL DEFAULT 0, wages REAL NOT NULL DEFAULT 0,"
        " net REAL NOT NULL DEFAULT 0,"
        " src_line_id INTEGER REFERENCES tax_free_lines(id),"
        " notes TEXT NOT NULL DEFAULT '')")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tax_free_lines_inv"
                 " ON tax_free_lines(invoice_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tax_free_lines_src"
                 " ON tax_free_lines(src_line_id)")
    for table, cols in (("invoices", (("free_lines",
                                       "INTEGER NOT NULL DEFAULT 0"),
                                      ("discount", "REAL NOT NULL DEFAULT 0"))),
                        ("set_purchases", (("free_lines",
                                            "INTEGER NOT NULL DEFAULT 0"),
                                           ("discount",
                                            "REAL NOT NULL DEFAULT 0")))):
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not have:
            continue
        for col, ddl in cols:
            if col not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    ensure_accounts(conn)


def ensure_accounts(conn):
    """الحسابان الجديدان لقاعدةٍ قائمة (والتأسيس يضيفهما من الدليل).

    لا يُضاف شيءٌ قبل تأسيس الدليل: قاعدةٌ جديدة تُبنى جداولها أولاً ثم
    يُؤسَّس دليلها كاملاً — وحسابٌ يسبقه يجعل التأسيس يظنّ أنه تمّ."""
    for code, name, typ, parent, bal, nature in _ACCOUNTS:
        if conn.execute("SELECT 1 FROM accounts WHERE code=?",
                        (code,)).fetchone():
            continue
        p = conn.execute("SELECT id FROM accounts WHERE code=?",
                         (parent,)).fetchone()
        if not p:
            continue                 # الدليل لم يُؤسَّس بعد — يضيفه التأسيس
        conn.execute(
            "INSERT INTO accounts(code,name,type,parent_id,is_postable,"
            "nature,balance_type) VALUES(?,?,?,?,1,?,?)",
            (code, name, typ, p["id"] if p else None, nature, bal))


def is_free(conn, invoice_id):
    try:
        r = conn.execute("SELECT free_lines FROM invoices WHERE id=?",
                         (int(invoice_id),)).fetchone()
    except Exception:
        return False
    return bool(r and r["free_lines"])


# ══════════════════════════ الحسابات ══════════════════════════
def stock_accounts(conn):
    """حسابات الذهب التي يدخلها/يخرج منها الإدخال الحر: مخزون الذهب
    الضريبي أولاً، ثم ما يصلح وجهةً للأطقم — عدا المحميّة."""
    from models import set_purchases as sp
    ensure_schema(conn)
    rows = [r for r in sp.dest_accounts(conn) if r["code"] not in GUARDED]
    rows.sort(key=lambda r: (r["code"] != TAX_STOCK, r["code"]))
    return rows


def check_stock(conn, account_id=None):
    """حساب الإدخال الحر متحقَّقاً — وبلا اختيارٍ: مخزون الذهب الضريبي."""
    from models.accounts import acc_id
    ensure_schema(conn)
    if not account_id:
        return acc_id(conn, TAX_STOCK)
    ok = {int(r["id"]) for r in stock_accounts(conn)}
    if int(account_id) not in ok:
        r = conn.execute("SELECT code, name FROM accounts WHERE id=?",
                         (int(account_id),)).fetchone()
        raise ValueError(
            "الإدخال اليدوي لا يمسّ "
            + (f"«{r['code']} — {r['name']}»" if r else "هذا الحساب")
            + "\nالذهب المشغول والإيطالي لأطقم الخزنة الحقيقية وحدها (تحت"
              " حماية المخزون). اختر «مخزون الذهب الضريبي» أو «من أطقم"
              " الخزنة».")
    return int(account_id)


def balance(conn, account_id=None):
    """رصيد حساب الإدخال الحر وزناً (مكافئ 18) — قد يكون سالباً."""
    acc = check_stock(conn, account_id)
    r = conn.execute(
        "SELECT COALESCE(SUM(l.gold_debit-l.gold_credit),0) FROM"
        " journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
        " WHERE e.is_deleted=0 AND l.account_id=?", (acc,)).fetchone()
    return round(float(r[0] or 0), 3)


# ══════════════════════════ الأسطر والخصم ══════════════════════════
def prepare_line(i, x, tx):
    """سطرٌ حر مُتحقَّقاً: رقم التشغيل (نصٌّ حر — ولو تكرّر) · الموديل ·
    العدد · الوزن (مكافئ 18) · العيار · الأجر (18) أو سعر الطقم · سعر الجرام."""
    from models import tax_invoices as _tx
    wo_no = " ".join(str(x.get("wo_no") or "").split())[:40]
    if not wo_no:
        raise ValueError(f"السطر {i}: اكتب رقم التشغيل")
    w = round(float(x.get("weight") or 0), 4)
    if w <= 0:
        raise ValueError(f"الطقم {wo_no}: اكتب الوزن")
    k = int(x.get("karat") or 0)
    if k not in (18, 21, 22, 24):
        raise ValueError(f"الطقم {wo_no}: اختر العيار")
    pieces = int(x.get("pieces") or 1)
    if pieces <= 0:
        raise ValueError(f"الطقم {wo_no}: العدد يكون 1 فأكثر")
    _wg = x.get("wage")
    wage = round(float(0 if _wg in (None, "") else _wg), 4)
    if wage < 0:
        raise ValueError(f"الطقم {wo_no}: الأجر لا يكون سالباً")
    li = {"weight": w, "wage": wage, "piece_price": x.get("piece_price"),
          "karat": k, "gold_price": x.get("gold_price")}
    wages, gv = _tx.line_amounts(li, tx, wo_no)
    gp = (float(_tx.line_tx(li, tx).get("gold_price") or 0)
          if tx["pricing"] in _tx.RIYAL else 0.0)
    return {"wo_no": wo_no,
            "model_no": " ".join(str(x.get("model_no") or "").split())[:60],
            "pieces": pieces, "weight": w, "karat": k, "wage": wage,
            "piece_price": (round(float(x.get("piece_price") or 0), 2)
                            if tx["pricing"] == "piece" else 0.0),
            "gold_price": gp, "wages": wages, "gv": gv,
            "net": round(wages + gv, 2),
            "notes": str(x.get("notes") or "").strip()[:120]}


def check_discount(net, discount):
    d = round(float(discount or 0), 2)
    if d < 0:
        raise ValueError("الخصم لا يكون سالباً")
    if d and d >= round(net, 2):
        raise ValueError(f"الخصم ({_nf.f2(d)}) يجب أن يكون أقل من صافي "
                         f"الفاتورة ({_nf.f2(net)})")
    return d


def share(total, part, whole):
    """نصيب جزءٍ من مبلغٍ بالنسبة — للخصم في المرتجع."""
    if not whole or not total:
        return 0.0
    return round(float(total) * float(part) / float(whole), 2)


def spread(amounts, discount):
    """يوزّع الخصم على الأسطر بنسبها (للفاتورة الإلكترونية: كل سطرٍ بصافيه
    بعد الخصم) — والمجموع يطابق (الصافي − الخصم) بالهللة."""
    amounts = [round(float(a or 0), 2) for a in amounts]
    d = round(float(discount or 0), 2)
    tot = round(sum(amounts), 2)
    if d <= 0 or tot <= 0:
        return amounts
    out, used = [], 0.0
    for i, a in enumerate(amounts):
        if i == len(amounts) - 1:
            cut = round(d - used, 2)
        else:
            cut = round(d * a / tot, 2)
            used = round(used + cut, 2)
        out.append(round(a - cut, 2))
    return out


# ══════════════════════════ البيع ══════════════════════════
def create_sale(conn, customer_id, lines, doc_date, username, pricing,
                gold_price=0.0, price_karat=0, description="",
                subtype="standard", buyer_name="", buyer_phone="",
                pay_mode="credit", account_id=None, discount=0.0,
                pay_account_id=None):
    """فاتورة مبيعات ضريبية بالإدخال اليدوي: `lines` = [{wo_no, model_no,
    pieces, weight (18), karat, wage (18) | piece_price, gold_price}].
    `pay_account_id` (5.8.1) الصندوق أو البنك الذي يُقبض فيه."""
    from models import tax_invoices as _tx
    from models.accounts import resolve_pay
    from models.entities import get_entity
    ensure_schema(conn)
    pay_mode = pay_mode or "credit"
    if pay_mode not in _tx.PAY_LABEL:
        raise ValueError("طريقة الدفع غير معروفة")
    pay_mode, pay_acc = resolve_pay(conn, pay_mode, pay_account_id)
    if not customer_id:
        if subtype != "simplified":
            raise ValueError("اختر المحل أو الشركة (المشتري)")
        customer_id = _tx.walkin_customer(conn)
    ent = get_entity(conn, customer_id)
    if not ent or ent["entity_type"] == "internal":
        raise ValueError("اختر العميل أو الشركة من دليل جهات التعامل")
    _tx.check_buyer(conn, customer_id, subtype)
    walk = _tx.is_walkin(conn, customer_id)
    if walk:
        if pay_mode == "credit":
            raise ValueError("«العميل النقدي» يدفع في الحال — اختر «نقداً» أو"
                             " «شبكة»، أو اختر عميلاً من الدليل للبيع الآجل")
        if pricing not in _tx.RIYAL:
            raise ValueError("البيع لعميلٍ نقدي بالريال كاملاً — اختر «سعر"
                             " الجرام + الأجر» أو «سعر الطقم»")
    tx = _tx.norm({"pricing": pricing, "gold_price": gold_price,
                   "price_karat": price_karat, "subtype": subtype,
                   "pay_mode": pay_mode,
                   "buyer_name": buyer_name if walk else "",
                   "buyer_phone": buyer_phone if walk else ""})
    prep = [prepare_line(i, x, tx) for i, x in enumerate(lines or [], 1)]
    if not prep:
        raise ValueError("أضف طقماً واحداً على الأقل")
    acc = check_stock(conn, account_id)
    res = _save(conn, "sale", ent, prep, doc_date, username, tx, acc,
                discount, description)
    _tx.record_pay(conn, [res], pay_acc)      # 5.8.2: بلا سندٍ تلقائي
    return res


def _save(conn, kind, ent, prep, doc_date, username, tx, acc, discount,
          description, ref=None):
    """يحفظ فاتورة البيع الحر أو إشعارها الدائن بقيدها ومستندها."""
    from datetime import datetime

    import config
    from models import invoices as inv
    from models import numbering as _numbering
    from models import tax_invoices as _tx
    from models.accounts import acc_id
    from services import zatca
    from services.accounting_engine import post_entry
    from services.audit import log_action
    wages = round(sum(p["wages"] for p in prep), 2)
    gv = round(sum(p["gv"] for p in prep), 2)
    net = round(wages + gv, 2)
    disc = check_discount(net, discount)
    vat = _tx.doc_vat(round(net - disc, 2))
    grand = round(net - disc + vat, 2)
    total_w = round(sum(p["weight"] for p in prep), 3)
    riyal = tx["pricing"] in _tx.RIYAL
    _d, lines = inv._entry_lines(conn, kind, False, ent, [(acc, total_w)],
                                 wages, vat, grand, True, gold_value=gv,
                                 riyal=riyal, tax_rev=True)
    if disc:
        lines.append({"account_id": acc_id(conn, DISC_ALLOWED),
                      ("cash_debit" if kind == "sale" else "cash_credit"):
                      disc, "line_desc": "خصم نقدي على الفاتورة"
                      if kind == "sale" else "ردّ الخصم بنسبة المرتجع"})
    sub = tx.get("subtype") or ""
    desc = (("فاتورة ضريبية" + (" مبسطة" if sub == "simplified" else "")
             if kind == "sale" else "إشعار دائن — مرتجع مبيعات ضريبي")
            + f" ({_tx.PRICING_LABEL[tx['pricing']].split(' — ')[0]})"
            + f" — {ent['name']}")
    ts = f"{doc_date}T{datetime.now():%H:%M:%S}"
    qr_b64 = zatca.build_tlv_base64(config.COMPANY_NAME,
                                    config.COMPANY_VAT_NUMBER, ts, grand, vat)
    cur = conn.execute(
        "INSERT INTO invoices(kind,customer_id,invoice_date,wage_per_gram,"
        "total_weight,total_wages,vat_amount,grand_total,qr_base64,"
        "vat_applied,qr_enabled,description,source_account_id,scrap_karat,"
        "created_by) VALUES(?,?,?,?,?,?,?,?,?,1,0,?,?,0,?)",
        (kind, ent["id"], doc_date, prep[0]["wage"], total_w, wages, vat,
         grand, qr_b64, (description or "").strip(), acc, username))
    inv_id = cur.lastrowid
    conn.execute(
        "UPDATE invoices SET pricing=?, gold_price=?, price_karat=?,"
        " gold_value=?, ref_invoice_id=?, tax_reason=?, tax_subtype=?,"
        " buyer_name=?, buyer_phone=?, pay_mode=?, free_lines=1, discount=?"
        " WHERE id=?",
        (tx["pricing"], tx["gold_price"], tx["price_karat"], gv,
         ref["id"] if ref else None, tx.get("reason") or "", sub,
         tx.get("buyer_name") or "", tx.get("buyer_phone") or "",
         tx.get("pay_mode") or "", disc, inv_id))
    inv_no = _numbering.next_no(conn, "S" if kind == "sale" else "R")
    entry_id = post_entry(conn, doc_date, f"{desc} — {inv_no}", lines,
                          source_table="invoices", source_id=inv_id,
                          username=username, note=description, doc_no=inv_no)
    conn.execute("UPDATE invoices SET invoice_no=?, entry_id=? WHERE id=?",
                 (inv_no, entry_id, inv_id))
    for i, p in enumerate(prep, 1):
        conn.execute(
            "INSERT INTO tax_free_lines(invoice_id,line_no,wo_no,model_no,"
            "pieces,weight,karat,wage_per_gram,piece_price,gold_price,"
            "gold_value,wages,net,src_line_id,notes)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (inv_id, i, p["wo_no"], p["model_no"], p["pieces"], p["weight"],
             p["karat"], p["wage"], p["piece_price"], p["gold_price"], p["gv"],
             p["wages"], p["net"], p.get("src_line_id"), p["notes"]))
    inv._verify_posted(conn, inv_id, entry_id)
    # الفاتورة الإلكترونية داخل المعاملة نفسها (لا تعمل ما لم يُفعَّل الربط)
    from services.fatoora import ledger as _fatoora
    _edoc = _fatoora.on_invoice_saved(conn, inv_id, username)
    if _edoc:
        qr_b64 = _edoc["qr"]
    log_action(conn, username, "create", "invoices", inv_id,
               f"{inv_no} free vat=1 disc={disc}")
    accr = conn.execute("SELECT code, name FROM accounts WHERE id=?",
                        (acc,)).fetchone()
    return {"id": inv_id, "invoice_no": inv_no, "total_weight": total_w,
            "total_wages": wages, "gold_value": gv, "net": net,
            "discount": disc, "vat": vat, "grand_total": grand,
            "pricing": tx["pricing"], "qr_base64": qr_b64,
            "entry_id": entry_id, "vat_applied": True, "free": True,
            "source_account_id": acc,
            "source_name": f"{accr['code']} — {accr['name']}" if accr else "",
            "customer_name": ent["name"], "n": len(prep)}


# ══════════════════════════ الإشعار الدائن ══════════════════════════
def lines_of(conn, invoice_id):
    ensure_schema(conn)
    return [dict(r) for r in conn.execute(
        "SELECT * FROM tax_free_lines WHERE invoice_id=? ORDER BY line_no",
        (int(invoice_id),))]


def returnable(conn, invoice_id):
    """أسطر الفاتورة الحرة وما بقي من كل سطرٍ بعد إشعاراتها الدائنة —
    بصيغة `tax_invoices.returnable` نفسها (item_id = رقم السطر الحر)."""
    out = []
    for ln in lines_of(conn, invoice_id):
        used = conn.execute(
            "SELECT COALESCE(SUM(r.weight),0) FROM tax_free_lines r JOIN"
            " invoices i ON i.id=r.invoice_id WHERE r.src_line_id=? AND"
            " i.is_deleted=0 AND i.kind='sale_return'", (ln["id"],)
        ).fetchone()[0]
        left = round(float(ln["weight"]) - float(used or 0), 4)
        out.append({"item_id": ln["id"], "work_order_id": None,
                    "wo_no": ln["wo_no"], "model_no": ln["model_no"],
                    "weight": round(float(ln["weight"]), 4),
                    "left": max(0.0, left), "pieces": int(ln["pieces"] or 0),
                    "standing": 0.0, "full": float(ln["weight"]),
                    "wage": float(ln["wage_per_gram"] or 0),
                    "wages": float(ln["wages"] or 0),
                    "piece_price": float(ln["piece_price"] or 0),
                    "gold_value": float(ln["gold_value"] or 0),
                    "gold_price": float(ln["gold_price"] or 0),
                    "net": float(ln["net"] or 0),
                    "karat": int(ln["karat"] or 18), "free": True})
    return out


def create_credit_note(conn, o, doc_date, returns, reason, username):
    """إشعار دائن لفاتورةٍ حرة: `returns` = [{item_id, weight (18 — فارغ =
    الباقي)}]. يعود الوزن إلى حساب الفاتورة، ويُردّ بسعر الأصل وطريقته،
    ومن الخصم بنسبة ما أُرجع."""
    from models import tax_invoices as _tx
    from models.entities import get_entity
    od = dict(o)
    tx = _tx.norm({"pricing": o["pricing"], "gold_price": o["gold_price"],
                   "price_karat": o["price_karat"],
                   "subtype": od.get("tax_subtype") or "",
                   "pay_mode": od.get("pay_mode") or "",
                   "buyer_name": od.get("buyer_name") or "",
                   "buyer_phone": od.get("buyer_phone") or ""})
    tx["ref_invoice_id"] = o["id"]
    tx["reason"] = str(reason).strip()
    left = {r["item_id"]: r for r in returnable(conn, o["id"])}
    prep = []
    for x in returns or []:
        r = left.get(int(x.get("item_id") or 0))
        if not r:
            raise ValueError("سطرٌ ليس من أسطر الفاتورة الأصلية")
        w = x.get("weight")
        w = r["left"] if w in (None, "", 0) else round(float(w), 4)
        if w <= 0 or r["left"] <= 0:
            raise ValueError(f"الطقم {r['wo_no']} أُرجع كله من قبل")
        if w > r["left"] + 0.0005:
            raise ValueError(
                f"الطقم {r['wo_no']}: المرتجع {_nf.f2(w)} أكبر من الباقي من "
                f"بيعه بهذه الفاتورة ({_nf.f2(r['left'])})")
        frac = (w / r["weight"]) if r["weight"] > 0 else 1.0
        p = prepare_line(len(prep) + 1, {
            "wo_no": r["wo_no"], "model_no": r["model_no"],
            "pieces": r["pieces"] if frac >= 0.999 else 1, "weight": w,
            "karat": r["karat"], "wage": r["wage"],
            "piece_price": round(r["piece_price"] * frac, 2),
            "gold_price": r["gold_price"]}, tx)
        p["src_line_id"] = r["item_id"]
        prep.append(p)
    if not prep:
        raise ValueError("اختر طقماً واحداً على الأقل للإرجاع")
    o_net = round(float(o["total_wages"] or 0) + float(o["gold_value"] or 0),
                  2)
    r_net = round(sum(p["net"] for p in prep), 2)
    disc = share(od.get("discount") or 0, r_net, o_net)
    ent = get_entity(conn, o["customer_id"])
    return _save(conn, "sale_return", ent, prep, doc_date, username, tx,
                 o["source_account_id"] or check_stock(conn), disc,
                 str(reason).strip(), ref=o)


def doc_lines(conn, invoice_id):
    """أسطر الفاتورة الحرة للعرض والطباعة والفاتورة الإلكترونية."""
    return lines_of(conn, invoice_id)
