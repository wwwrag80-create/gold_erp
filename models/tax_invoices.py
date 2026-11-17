# -*- coding: utf-8 -*-
"""الفاتورة الضريبية بالأطقم (5.5) — بيعٌ ومرتجعٌ يحرّكان المخزون.

**لماذا ليست في `tax_sales`**: تلك فاتورة الشركة عن أطقمٍ بيعت للمندوب من
قبل (لا مخزون يتحرّك). أما المحلّ فيبيع من خزنته: الطقم يخرج بفاتورته
الضريبية ويعود بإشعارها الدائن. فهذه الفواتير **فواتير بيعٍ حقيقية** في
جدول الفواتير نفسه (`invoices`) — بها تبقى سلسلة حركة الطقم وحارس
المخزون وكشوف الحسابات والفوترة الإلكترونية على حالها الصحيح — ويزيد
عليها هنا: طريقة التسعير، وقيمة الذهب بالريال، ومرجع الإشعار الدائن.

**طرق التسعير** (تُختار في كل فاتورة):
  * ``wage``  الأجر فقط: الذهب يُقيَّد وزناً على الطرف، والأجور بالريال،
              والضريبة على الأجور — كفاتورة البيع العادية تماماً.
  * ``gram``  سعر الجرام + الأجر: الفاتورة كلها بالريال — قيمة الذهب
              (الوزن × سعر الجرام) والأجور، والضريبة على الكل.
  * ``piece`` سعر الطقم: مبلغ الطقم بالريال، والضريبة عليه كله. وسعر
              الجرام يُكتب ليُفصل في الدفتر ما هو ذهبٌ عمّا هو مصنعية.

**القيد بالريال كاملاً** (gram · piece) = بيعٌ وتسكيرٌ فوري في قيدٍ واحد:
الذهب الخارج من الخزنة يُسلَّم وزناً إلى مركز التسكير 6100 (كما يفعل
التسكير تماماً) ويقابله بالريال قيمته — فلا يبقى على العميل ذهبٌ،
ويبقى ميزانا الذهب والنقد متوازنين كلٌّ وحده.

**الإشعار الدائن** (مرتجع مبيعات) يشير إلى فاتورته الأصلية ويأخذ منها
طريقتها وسعرها — فلا يُردّ للعميل أكثر مما دفع ولا بسعرٍ غير سعره،
ولا يُرتجع من الطقم أكثر مما بيع منه بتلك الفاتورة.

**ولا تعديل ولا نقل ولا عكس لفاتورةٍ ضريبية بعد إصدارها** — الإشعار
الدائن وحده طريقها (`guard`)، كما تشترط الهيئة.

**نوع الفاتورة** (5.5.1) يُختار صراحةً لا يُستنتج:
  * ``standard``   فاتورة ضريبية — لمحلٍ أو شركة برقمها الضريبي (إلزامي).
  * ``simplified`` فاتورة ضريبية مبسطة — لعميلٍ فرد: من الدليل، أو «عميل
                   نقدي» يُكتب اسمه وجواله على الفاتورة وحدها.
والدفع: آجلٌ على الحساب، أو نقداً، أو شبكة — والنقد والشبكة يُسدَّدان
بسند قبضٍ تلقائي في القيد نفسه، والإشعار الدائن يُردّ بالطريقة نفسها.
"""
import config
from services import numfmt as _nf

TAX_PRICING = (("wage", "الأجر فقط — الذهب بالوزن"),
               ("gram", "سعر الجرام + الأجر — بالريال"),
               ("piece", "سعر الطقم — بالريال"))
PRICING_LABEL = dict(TAX_PRICING)
RIYAL = ("gram", "piece")             # الفاتورة كلها بالريال
BRIDGE = "6100"                       # مركز التسكير (ذهب ↔ نقد)

SUBTYPES = (("standard", "فاتورة ضريبية — لمحلٍ أو شركة"),
            ("simplified", "فاتورة مبسطة — لعميلٍ فرد"))
SUBTYPE_LABEL = {"standard": "فاتورة ضريبية",
                 "simplified": "فاتورة ضريبية مبسطة"}
PAY_MODES = (("credit", "آجل — على حسابه"), ("cash", "نقداً"),
             ("bank", "شبكة / تحويل بنكي"))
PAY_LABEL = dict(PAY_MODES)
PAY_BOX = {"cash": "1400", "bank": "1500"}
WALKIN_NAME = "عميل نقدي — مبيعات مبسطة"
WALKIN_KEY = "walkin_customer_id"


# ══════════════════════════ المخطط ══════════════════════════
def ensure_schema(conn):
    """أعمدة الفاتورة الضريبية — تُضاف مرةً ولا تمسّ الفواتير القائمة."""
    def _add(table, cols):
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not have:
            return
        for col, ddl in cols:
            if col not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    # pricing: '' فاتورة بيعٍ عادية · wage/gram/piece فاتورة ضريبية بالأطقم
    _add("invoices", (("pricing", "TEXT NOT NULL DEFAULT ''"),
                      ("gold_price", "REAL NOT NULL DEFAULT 0"),
                      ("price_karat", "INTEGER NOT NULL DEFAULT 0"),
                      ("gold_value", "REAL NOT NULL DEFAULT 0"),
                      ("ref_invoice_id", "INTEGER"),
                      ("tax_reason", "TEXT NOT NULL DEFAULT ''"),
                      # 5.5.1: نوع الفاتورة والمشتري الفرد والدفع
                      ("tax_subtype", "TEXT NOT NULL DEFAULT ''"),
                      ("buyer_name", "TEXT NOT NULL DEFAULT ''"),
                      ("buyer_phone", "TEXT NOT NULL DEFAULT ''"),
                      ("pay_mode", "TEXT NOT NULL DEFAULT ''"),
                      ("pay_voucher_id", "INTEGER"),
                      # 5.8.1: الصندوق أو البنك الذي قُبض فيه (من الشجرة)
                      ("pay_account_id", "INTEGER")))
    _add("invoice_items", (("gold_value", "REAL NOT NULL DEFAULT 0"),
                           ("pieces", "INTEGER NOT NULL DEFAULT 0"),
                           ("piece_price", "REAL NOT NULL DEFAULT 0"),
                           ("src_item_id", "INTEGER"),
                           # 5.5.2: سعر الجرام لكل سطر — بعيار السطر نفسه
                           ("gold_price", "REAL NOT NULL DEFAULT 0")))
    # عدد قطع الطقم (عقد · حلق · خاتم…) — يُكتب في الشراء ويُقترح في البيع
    _add("work_orders", (("pieces", "INTEGER NOT NULL DEFAULT 0"),))


def is_tax(conn, invoice_id):
    """هل الفاتورة ضريبيةٌ صادرة من شاشة المبيعات الضريبية؟"""
    try:
        r = conn.execute("SELECT pricing FROM invoices WHERE id=?",
                         (int(invoice_id),)).fetchone()
    except Exception:
        return False
    return bool(r and (r["pricing"] or ""))


def guard(conn, invoice_id, action="تعديل"):
    """الفاتورة الضريبية لا تُعدَّل ولا تُنقل ولا تُعكس بعد إصدارها."""
    if is_tax(conn, invoice_id):
        raise ValueError(
            f"لا يصح {action} فاتورةٍ ضريبية بعد إصدارها — هذا ما تشترطه "
            "هيئة الزكاة والضريبة والجمارك.\n\nأصدر «إشعاراً دائناً» (مرتجع "
            "مبيعات) من شاشة المبيعات الضريبية: يُرجع الأطقم ويعكس المبالغ "
            "والضريبة ويشير إلى الفاتورة الأصلية.")


# ══════════════════════════ الحساب ══════════════════════════
def norm(tax):
    """{pricing, gold_price, price_karat, ref_invoice_id, reason} مُتحقَّقاً."""
    if not tax:
        return None
    p = str(tax.get("pricing") or "wage")
    if p not in PRICING_LABEL:
        raise ValueError("طريقة التسعير غير معروفة")
    gp = round(float(tax.get("gold_price") or 0), 4)
    if gp < 0:
        raise ValueError("سعر الجرام لا يكون سالباً")
    if p in RIYAL and gp <= 0:
        raise ValueError("اكتب سعر جرام الذهب — به تُحسب قيمة الذهب بالريال"
                         " وتُفصل عن المصنعية في الدفتر")
    k = int(tax.get("price_karat") or 0)
    if p in RIYAL and k not in (18, 21, 22, 24):
        raise ValueError("عيار سعر الجرام غير معروف")
    st = str(tax.get("subtype") or "")
    if st and st not in dict(SUBTYPES):
        raise ValueError("نوع الفاتورة غير معروف")
    pm = str(tax.get("pay_mode") or "")
    if pm and pm not in PAY_LABEL:
        raise ValueError("طريقة الدفع غير معروفة")
    return {"pricing": p, "gold_price": gp if p in RIYAL else 0.0,
            "price_karat": k if p in RIYAL else 0,
            "ref_invoice_id": tax.get("ref_invoice_id"),
            "reason": str(tax.get("reason") or "").strip(),
            "subtype": st, "pay_mode": pm,
            "discount": round(float(tax.get("discount") or 0), 2),
            "buyer_name": str(tax.get("buyer_name") or "").strip()[:120],
            "buyer_phone": str(tax.get("buyer_phone") or "").strip()[:30]}


def weight_in_karat(w18, karat):
    """الوزن بمكافئ 18 ← وزنه بالعيار المطلوب (الذهب الخالص نفسه)."""
    k = int(karat or 18)
    return float(w18 or 0) * 18.0 / k


def gold_value(w18, tx):
    """قيمة ذهب السطر بالريال: وزنه بعيار السعر × سعر الجرام."""
    if not tx or tx["pricing"] not in RIYAL:
        return 0.0
    return round(weight_in_karat(w18, tx["price_karat"]) * tx["gold_price"],
                 2)


def line_tx(li, tx):
    """تسعير السطر (5.5.2): سعر الجرام يُكتب لكل سطرٍ بعياره — فقيمة ذهبه
    وزنُه بعيار السطر × سعره. وبلا سعرٍ للسطر يبقى سعر الفاتورة."""
    if not tx or tx["pricing"] not in RIYAL:
        return tx
    gp = float(li.get("gold_price") or 0)
    if gp <= 0:
        return tx
    k = int(li.get("karat") or 0) or int(tx.get("price_karat") or 0) or 18
    return dict(tx, gold_price=round(gp, 4), price_karat=k)


def line_amounts(li, tx, wo_no=""):
    """(الأجور، قيمة الذهب) لسطرٍ مُحلَّل — بطريقة تسعير الفاتورة."""
    from services import gold_math
    w = float(li["weight"] or 0)
    tx = line_tx(li, tx)
    if tx["pricing"] in RIYAL and float(tx.get("gold_price") or 0) <= 0:
        raise ValueError(f"اكتب سعر الجرام للطقم {wo_no}")
    gv = gold_value(w, tx)
    if tx["pricing"] == "piece":
        price = round(float(li.get("piece_price") or 0), 2)
        if price <= 0:
            raise ValueError(f"اكتب سعر الطقم {wo_no} بالريال")
        wages = round(price - gv, 2)
        if wages < -0.005:
            raise ValueError(
                f"سعر الطقم {wo_no} ({_nf.f2(price)}) أقل من قيمة ذهبه بسعر"
                f" الجرام ({_nf.f2(gv)}) — راجع السعر أو سعر الجرام")
        return max(0.0, wages), gv
    return gold_math.total_wages(li["wage"], w), gv


def doc_vat(net):
    """ضريبة المستند على صافيه كلّه مقرّبةً مرةً واحدة — قاعدة الهيئة."""
    from decimal import Decimal, ROUND_HALF_UP
    v = Decimal(str(net)) * Decimal(str(config.VAT_RATE))
    return float(v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ══════════════════════════ الإصدار ══════════════════════════
def walkin_customer(conn, create=True):
    """حساب «عميل نقدي» للمبيعات المبسطة لأفرادٍ لا يُفتح لهم حساب — يُنشأ
    مرةً واحدة. اسم المشتري وجواله يُكتبان على الفاتورة وحدها."""
    from models.entities import add_entity, get_entity
    from models.fiscal import get_setting, set_setting
    try:
        eid = int(get_setting(conn, WALKIN_KEY, "0") or 0)
    except (TypeError, ValueError):
        eid = 0
    ent = get_entity(conn, eid) if eid else None
    if ent and not ent["is_deleted"]:
        return eid
    if not create:
        return None
    r = conn.execute("SELECT id FROM entities WHERE name=? AND is_deleted=0"
                     " AND entity_type='customer'", (WALKIN_NAME,)).fetchone()
    eid = r["id"] if r else add_entity(conn, WALKIN_NAME, "customer",
                                       username="system")
    eid = eid if isinstance(eid, int) else eid["id"]
    set_setting(conn, WALKIN_KEY, str(eid), "system")
    return eid


def is_walkin(conn, customer_id):
    return bool(customer_id) and customer_id == walkin_customer(conn, False)


def check_buyer(conn, customer_id, subtype):
    """يتحقّق أن نوع الفاتورة يناسب المشتري — برسالةٍ تقول ما يُفعل."""
    from services.fatoora import profile as pf
    if subtype not in dict(SUBTYPES):
        raise ValueError("اختر نوع الفاتورة: ضريبية لمحلٍ أو شركة، أو "
                         "مبسطة لعميلٍ فرد")
    if subtype == "standard":
        if is_walkin(conn, customer_id):
            raise ValueError("«العميل النقدي» فرد — فاتورته «مبسطة». الفاتورة"
                             " الضريبية لمحلٍ أو شركة برقمها الضريبي")
        b = pf.buyer(conn, customer_id) or {}
        if not pf.buyer_is_b2b(b):
            raise ValueError(
                f"الفاتورة الضريبية لمحلٍ أو شركة برقمها الضريبي — و«"
                f"{b.get('name') or 'العميل'}» بلا رقمٍ ضريبي صحيح (15 رقماً"
                " يبدأ وينتهي بـ3).\n\nأضف رقمه من «التكويد الموحّد لجهات"
                " التعامل»، أو اختر «فاتورة مبسطة» إن كان فرداً.")


def _settle(conn, kind, entity_id, amount, mode, doc_date, username, note,
            account_id=None):
    """سند قبضٍ (بيع) أو صرفٍ (إشعار دائن) تلقائي للنقد والشبكة — في
    الصندوق أو البنك المختار (5.8.1)، وبلا اختيارٍ الصندوق أو البنك."""
    from models import vouchers
    if mode not in PAY_BOX or amount <= 0:
        return None
    code = PAY_BOX[mode]
    if account_id:
        r = conn.execute("SELECT code FROM accounts WHERE id=?",
                         (int(account_id),)).fetchone()
        code = r["code"] if r else code
    return vouchers.create_voucher(
        conn, kind, doc_date, username, entity_id=entity_id,
        cash_amount=round(amount, 2), cash_account_code=code,
        notes=note, expense_account_id=0)


def settle_docs(conn, kind, entity_id, docs, mode, account_id, doc_date,
                username, note):
    """يسدّد مستندات الفاتورة (أو يردّ قيمة الإشعار) بسندٍ واحد ويربطها به."""
    if mode not in PAY_BOX:
        return None
    total = round(sum(float(d["grand_total"]) for d in docs), 2)
    v = _settle(conn, kind, entity_id, total, mode, doc_date, username, note,
                account_id)
    if v:
        for d in docs:
            conn.execute("UPDATE invoices SET pay_voucher_id=?,"
                         " pay_account_id=? WHERE id=?",
                         (v["id"], account_id, d["id"]))
        v = dict(v, paid=total)
    return v


def create_invoice(conn, customer_id, cart, doc_date, username, pricing,
                   gold_price=0.0, price_karat=0, description="",
                   subtype="standard", buyer_name="", buyer_phone="",
                   pay_mode="credit", discount=0.0, pay_account_id=None):
    """فاتورة ضريبية بالأطقم: تخرج من الخزنة كفاتورة البيع تماماً.

    `cart` = [{work_order_id, weight (18 — فارغ = الباقي كله),
               wage_override (18), piece_price, pieces, karat, note}]
    `subtype`: standard (محل/شركة برقمها الضريبي) · simplified (فرد).
    `customer_id` فارغٌ مع المبسطة = «عميل نقدي» (اسمه وجواله على الفاتورة).
    `pay_mode`: credit (على حسابه) · cash · bank — والأخيران يُسدَّدان
    بسند قبضٍ تلقائي بإجمالي الفاتورة.
    """
    from models import invoices as inv
    from models.accounts import resolve_pay
    from models.entities import get_entity
    ensure_schema(conn)
    pay_mode = pay_mode or "credit"
    if pay_mode not in PAY_LABEL:
        raise ValueError("طريقة الدفع غير معروفة")
    # 5.8.1: الصندوق أو البنك المختار يحدّد الطريقة (نقداً / بنكي)
    pay_mode, pay_acc = resolve_pay(conn, pay_mode, pay_account_id)
    if not customer_id:
        if subtype != "simplified":
            raise ValueError("اختر المحل أو الشركة (المشتري)")
        customer_id = walkin_customer(conn)
    ent = get_entity(conn, customer_id)
    if not ent or ent["entity_type"] == "internal":
        raise ValueError("اختر العميل أو الشركة من دليل جهات التعامل")
    check_buyer(conn, customer_id, subtype)
    if is_walkin(conn, customer_id):
        if pay_mode == "credit":
            raise ValueError("«العميل النقدي» يدفع في الحال — اختر «نقداً» أو"
                             " «شبكة»، أو اختر عميلاً من الدليل للبيع الآجل")
        if pricing not in RIYAL:
            raise ValueError("البيع لعميلٍ نقدي بالريال كاملاً — اختر «سعر"
                             " الجرام + الأجر» أو «سعر الطقم» (الأجر وحده يُبقي"
                             " ذهباً على حسابٍ لا صاحب له)")
    tax = {"pricing": pricing, "gold_price": gold_price,
           "price_karat": price_karat, "subtype": subtype,
           "pay_mode": pay_mode, "discount": discount,
           "buyer_name": buyer_name if is_walkin(conn, customer_id) else "",
           "buyer_phone": buyer_phone if is_walkin(conn, customer_id) else ""}
    if float(discount or 0) > 0 and inv.split_cart(conn, cart):
        raise ValueError("الخصم مع فاتورةٍ تجمع أطقماً وإيطالياً (0010 · "
                         "00010) لا يُقسَم — أصدرهما فاتورتين")
    res = inv.create_sale(conn, customer_id, cart, doc_date, username,
                          apply_vat=True, description=description,
                          tax=tax)
    docs = [res] + ([res["split"]] if res.get("split") else [])
    v = settle_docs(conn, "receipt", customer_id, docs, pay_mode, pay_acc,
                    doc_date, username, "سداد " + " · ".join(
                        f"الفاتورة {d['invoice_no']}" for d in docs))
    if v:
        res["voucher_no"] = v["voucher_no"]
        res["paid"] = v["paid"]
    return res


def returnable(conn, invoice_id):
    """ما بقي من كل طقمٍ في الفاتورة الضريبية بعد إشعاراتها الدائنة.

    [{item_id, work_order_id, wo_no, model_no, weight (المبيع), left,
      pieces, wage, piece_price, gold_value, karat}]"""
    ensure_schema(conn)
    from models import tax_free as _tf
    if _tf.is_free(conn, invoice_id):
        return _tf.returnable(conn, invoice_id)
    out = []
    for it in conn.execute(
            "SELECT it.*, w.work_order_no wo_no, w.model_no,"
            " w.standing_gold, w.registered_weight full_w"
            " FROM invoice_items it JOIN work_orders w"
            " ON w.id=it.work_order_id WHERE it.invoice_id=?"
            " ORDER BY it.id", (int(invoice_id),)):
        used = conn.execute(
            "SELECT COALESCE(SUM(r.registered_weight),0) FROM invoice_items r"
            " JOIN invoices i ON i.id=r.invoice_id WHERE r.src_item_id=?"
            " AND i.is_deleted=0 AND i.kind='sale_return'",
            (it["id"],)).fetchone()[0]
        left = round(float(it["registered_weight"] or 0) - float(used or 0),
                     3)
        out.append({"item_id": it["id"], "work_order_id": it["work_order_id"],
                    "wo_no": it["wo_no"], "model_no": it["model_no"] or "",
                    "weight": round(float(it["registered_weight"] or 0), 3),
                    "left": max(0.0, left),
                    "pieces": int(it["pieces"] or 0),
                    "standing": float(it["standing_gold"] or 0),
                    "full": float(it["full_w"] or 0),
                    "wage": float(it["wage_per_gram"] or 0),
                    "wages": float(it["wages"] or 0),
                    "piece_price": float(it["piece_price"] or 0),
                    "gold_value": float(it["gold_value"] or 0),
                    "gold_price": float(it["gold_price"] or 0),
                    "karat": int(it["karat"] or 0)})
    return out


def create_credit_note(conn, original_id, doc_date, returns, reason,
                       username):
    """إشعار دائن (مرتجع مبيعات) من فاتورةٍ ضريبية: `returns` =
    [{item_id, weight (18 — فارغ = الباقي كله)}].

    يعود كل طقمٍ إلى خزنته كمرتجع البيع تماماً، ويُردّ للعميل بسعر
    الفاتورة نفسها وطريقتها — والمرتجع لا يتجاوز الباقي من كل سطر.
    """
    ensure_schema(conn)
    o = conn.execute("SELECT * FROM invoices WHERE id=? AND is_deleted=0"
                     " AND kind='sale'", (int(original_id),)).fetchone()
    if not o or not (o["pricing"] or ""):
        raise ValueError("اختر فاتورةً ضريبية صادرة من شاشة المبيعات"
                         " الضريبية")
    if not str(reason or "").strip():
        raise ValueError("اكتب سبب الإشعار الدائن — يُطبع عليه ويُرسل"
                         " للهيئة")
    if str(doc_date) < str(o["invoice_date"]):
        raise ValueError("تاريخ الإشعار يسبق تاريخ الفاتورة الأصلية")
    from models import tax_free as _tf
    if _tf.is_free(conn, original_id):
        res = _tf.create_credit_note(conn, o, doc_date, returns, reason,
                                     username)
    else:
        res = _vault_credit_note(conn, o, doc_date, returns, reason, username)
    od = dict(o)
    mode = od.get("pay_mode") or ""
    # دُفعت الفاتورة نقداً أو بالشبكة: يُردّ المرتجع بالطريقة نفسها ومن
    # الصندوق أو البنك نفسه (5.8.1 — والإدخال اليدوي كان لا يُردّ)
    docs = [res] + ([res["split"]] if res.get("split") else [])
    v = settle_docs(conn, "payment", o["customer_id"], docs, mode,
                    od.get("pay_account_id"), doc_date, username,
                    f"ردّ قيمة الإشعار {res['invoice_no']} على الفاتورة "
                    f"{o['invoice_no']}")
    if v:
        res["voucher_no"] = v["voucher_no"]
        res["paid"] = v["paid"]
    return res


def _vault_credit_note(conn, o, doc_date, returns, reason, username):
    """الإشعار الدائن لفاتورة أطقم الخزنة — بلا سداد (يسدّده المُستدعي)."""
    from models import invoices as inv
    from models import tax_free as _tf
    original_id = o["id"]
    left = {r["item_id"]: r for r in returnable(conn, original_id)}
    cart = []
    for x in returns or []:
        r = left.get(int(x.get("item_id") or 0))
        if not r:
            raise ValueError("سطرٌ ليس من أسطر الفاتورة الأصلية")
        w = x.get("weight")
        w = r["left"] if w in (None, "", 0) else round(float(w), 3)
        if w <= 0 or r["left"] <= 0:
            raise ValueError(f"الطقم {r['wo_no']} أُرجع كله من قبل")
        if w > r["left"] + 0.0005:
            raise ValueError(
                f"الطقم {r['wo_no']}: المرتجع {_nf.f2(w)} أكبر من الباقي"
                f" من بيعه بهذه الفاتورة ({_nf.f2(r['left'])})")
        # السعر من سطر الأصل: سعر الطقم يُردّ بنسبة الوزن المرتجع
        frac = (w / r["weight"]) if r["weight"] > 0 else 1.0
        cart.append({"work_order_id": r["work_order_id"], "weight": w,
                     "wage_override": r["wage"],
                     "piece_price": round(r["piece_price"] * frac, 2),
                     "pieces": r["pieces"] if frac >= 0.999 else 0,
                     "src_item_id": r["item_id"], "karat": r["karat"],
                     "gold_price": r["gold_price"]})
    if not cart:
        raise ValueError("اختر طقماً واحداً على الأقل للإرجاع")
    od = dict(o)
    # 5.8.0: يُردّ من خصم الأصل بنسبة ما أُرجع من صافيه
    _disc = 0.0
    if float(od.get("discount") or 0) > 0:
        _t = norm({"pricing": o["pricing"], "gold_price": o["gold_price"],
                   "price_karat": o["price_karat"]})
        _rn = 0.0
        for c in cart:
            _w, _g = line_amounts({"weight": c["weight"],
                                   "wage": c["wage_override"],
                                   "piece_price": c["piece_price"],
                                   "karat": c["karat"],
                                   "gold_price": c["gold_price"]}, _t)
            _rn += _w + _g
        _on = float(o["total_wages"] or 0) + float(o["gold_value"] or 0)
        _disc = _tf.share(od["discount"], round(_rn, 2), round(_on, 2))
    tax = {"pricing": o["pricing"], "gold_price": o["gold_price"],
           "price_karat": o["price_karat"], "ref_invoice_id": o["id"],
           "discount": _disc,
           "reason": str(reason).strip(),
           # 5.5.1: الإشعار بنوع فاتورته ومشتريها وطريقة دفعها
           "subtype": od.get("tax_subtype") or "",
           "pay_mode": od.get("pay_mode") or "",
           "buyer_name": od.get("buyer_name") or "",
           "buyer_phone": od.get("buyer_phone") or ""}
    return inv.create_sale_return(conn, o["customer_id"], cart, doc_date,
                                  username, apply_vat=True,
                                  description=str(reason).strip(), tax=tax)


def search(conn, q="", date_from=None, date_to=None, kind=None, limit=500,
           subtype=None):
    """سجل الفواتير والإشعارات الضريبية بالأطقم."""
    ensure_schema(conn)
    from models import tax_free as _tf
    _tf.ensure_schema(conn)
    sql = ("SELECT i.*, e.name customer_name, o.invoice_no ref_no,"
           " (SELECT COUNT(*) FROM invoice_items it WHERE"
           "  it.invoice_id=i.id) + (SELECT COUNT(*) FROM tax_free_lines f"
           "  WHERE f.invoice_id=i.id) n_items"
           " FROM invoices i JOIN entities e ON e.id=i.customer_id"
           " LEFT JOIN invoices o ON o.id=i.ref_invoice_id"
           " WHERE i.is_deleted=0 AND COALESCE(i.pricing,'')<>''")
    args = []
    if kind:
        sql += " AND i.kind=?"
        args.append(kind)
    if subtype:
        sql += " AND COALESCE(i.tax_subtype,'')=?"
        args.append(subtype)
    if date_from:
        sql += " AND i.invoice_date>=?"
        args.append(date_from)
    if date_to:
        sql += " AND i.invoice_date<=?"
        args.append(date_to)
    if q:
        sql += (" AND (i.invoice_no LIKE ? OR e.name LIKE ?"
                " OR i.buyer_name LIKE ? OR i.buyer_phone LIKE ? OR EXISTS ("
                "SELECT 1 FROM invoice_items it JOIN work_orders w"
                " ON w.id=it.work_order_id WHERE it.invoice_id=i.id"
                " AND w.work_order_no LIKE ?) OR EXISTS (SELECT 1 FROM"
                " tax_free_lines f WHERE f.invoice_id=i.id AND f.wo_no"
                " LIKE ?))")
        args += [f"%{q}%"] * 6
    sql += " ORDER BY i.invoice_date DESC, i.id DESC LIMIT ?"
    args.append(int(limit))
    return [dict(r) for r in conn.execute(sql, args)]


def open_invoices(conn):
    """الفواتير الضريبية التي بقي منها ما يُرتجع — لقائمة الإشعار."""
    out = []
    for r in search(conn, kind="sale", limit=2000):
        if any(x["left"] > 0.0005 for x in returnable(conn, r["id"])):
            out.append(r)
    return out


def totals(conn, date_from, date_to):
    """صافي المبيعات الضريبية بالأطقم في الفترة: الوعاء (أجور + ذهب) والضريبة."""
    ensure_schema(conn)
    from models import tax_free as _tf
    _tf.ensure_schema(conn)
    r = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN kind='sale' THEN 1 ELSE -1 END *"
        " (total_wages + gold_value - COALESCE(discount,0))),0) base,"
        " COALESCE(SUM(CASE WHEN kind='sale' THEN 1 ELSE -1 END *"
        " vat_amount),0) vat, COUNT(*) n FROM invoices WHERE is_deleted=0"
        " AND COALESCE(pricing,'')<>'' AND invoice_date BETWEEN ? AND ?",
        (date_from, date_to)).fetchone()
    return {"base": round(r["base"], 2), "vat": round(r["vat"], 2),
            "n": r["n"]}
