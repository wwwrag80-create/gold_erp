# -*- coding: utf-8 -*-
"""المشتريات الضريبية بالأطقم (5.5) — يشتري المحلّ أطقماً من شركةٍ أو مصنع
أو عميل بفاتورةٍ ضريبية، فتدخل خزنته وتُباع من شاشة المبيعات الضريبية.

**الأطقم تُولد في الخزنة بهذه الفاتورة** — برقم تشغيلها في فاتورة المورد
ووزنيها المقيد والقائم وعدد قطعها — كما يولدها «الوارد من التصنيع» في
المصنع تماماً: بطاقتها، وبيتها (الذهب المشغول 1200، والرقمان
التجميعيان 0010 · 00010 في «ايطالي / نواعم» 1210)، وقيدها. فحارس
المخزون وسلسلة حركة الطقم وكشف الخزنة كلها تراها كما ترى الوارد.

**القيد** بطريقة تسعير الفاتورة نفسها (انظر `tax_invoices`):
  * الأجر فقط:   من حـ/ الخزنة (وزناً)        إلى حـ/ المورد (وزناً)
                 من حـ/ تكلفة المصنعية 5530    ┐
                 من حـ/ ضريبة المدخلات 1900   ┘ إلى حـ/ المورد (ريالاً)
  * بالريال (سعر جرام · سعر طقم): الذهب يُشترى عبر مركز التسكير 6100:
                 من حـ/ الخزنة (وزناً)        إلى حـ/ 6100 (وزناً)
                 من حـ/ 6100 (قيمة الذهب) + 5530 (المصنعية) + 1900
                                               إلى حـ/ المورد (المبلغ كله)

**مرتجع المشتريات** يشير إلى فاتورته ويأخذ منها طريقتها وأسعارها، ولا
يُرجع إلا طقماً في الخزنة بوزنه كله (لم يُبع منه شيء)؛ فيخرج من الخزنة
بقيدٍ يعكس الشراء، وتُطوى بطاقته (`is_deleted`) — ليس للمحلّ بعد ذلك —
ويبقى المرتجع دليله في كشف المورد وفي حركة الطقم.

**لا تعديل ولا حذف** لمستندٍ هنا بعد ترحيله: المرتجع طريق التصحيح.
"""
import datetime as _dt

import config
from models import numbering as _numbering
from models import tax_invoices as _tx
from models.accounts import acc_id
from models.entities import get_entity
from services import numfmt as _nf
from services.accounting_engine import post_entry
from services.audit import log_action

PREFIX = {"purchase": "PS", "purchase_return": "PSR"}
KIND_LABEL = {"purchase": "فاتورة مشتريات ضريبية",
              "purchase_return": "مرتجع مشتريات ضريبي"}
COST = "5530"          # تكلفة مصنعية الأطقم المشتراة
VAT_IN = "1900"        # ضريبة القيمة المضافة — المدخلات


def ensure_schema(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS set_purchases("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, doc_no TEXT UNIQUE,"
        " kind TEXT NOT NULL CHECK(kind IN ('purchase','purchase_return')),"
        " supplier_id INTEGER NOT NULL REFERENCES entities(id),"
        " doc_date TEXT NOT NULL, supplier_inv_no TEXT NOT NULL DEFAULT '',"
        " pricing TEXT NOT NULL DEFAULT 'wage', gold_price REAL NOT NULL"
        " DEFAULT 0, price_karat INTEGER NOT NULL DEFAULT 0,"
        " vat_rate REAL NOT NULL DEFAULT 0.15,"
        " total_weight REAL NOT NULL DEFAULT 0, wages REAL NOT NULL DEFAULT 0,"
        " gold_value REAL NOT NULL DEFAULT 0, net REAL NOT NULL DEFAULT 0,"
        " vat REAL NOT NULL DEFAULT 0, total REAL NOT NULL DEFAULT 0,"
        " ref_id INTEGER REFERENCES set_purchases(id),"
        " reason TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',"
        " entry_id INTEGER REFERENCES journal_entries(id),"
        " is_deleted INTEGER NOT NULL DEFAULT 0, created_by TEXT,"
        " created_at TEXT DEFAULT (datetime('now','localtime')))")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS set_purchase_lines("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " doc_id INTEGER NOT NULL REFERENCES set_purchases(id),"
        " line_no INTEGER NOT NULL,"
        " work_order_id INTEGER REFERENCES work_orders(id),"
        " wo_no TEXT NOT NULL, model_no TEXT NOT NULL DEFAULT '',"
        " pieces INTEGER NOT NULL DEFAULT 1,"
        " registered_weight REAL NOT NULL, standing_weight REAL NOT NULL,"
        " karat INTEGER NOT NULL DEFAULT 0,"
        " wage_per_gram REAL NOT NULL DEFAULT 0,"
        " piece_price REAL NOT NULL DEFAULT 0, wages REAL NOT NULL DEFAULT 0,"
        " gold_value REAL NOT NULL DEFAULT 0, net REAL NOT NULL DEFAULT 0,"
        " src_line_id INTEGER REFERENCES set_purchase_lines(id))")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_set_purchases_date"
                 " ON set_purchases(doc_date, is_deleted)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_set_purchase_lines_doc"
                 " ON set_purchase_lines(doc_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_set_purchase_lines_wo"
                 " ON set_purchase_lines(work_order_id)")
    _tx.ensure_schema(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(work_orders)")}
    # 5.5.2: حساب الوجهة (الذهب المشغول · الماس · أي مخزن) وسعر جرام السطر
    for table, col, ddl in (("set_purchases", "dest_account_id", "INTEGER"),
                            ("set_purchase_lines", "gold_price",
                             "REAL NOT NULL DEFAULT 0")):
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if have and col not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    # 5.8.0: عمودا الإدخال الحر والخصم (وحساب مخزون الذهب الضريبي)
    from models import tax_free as _tf
    _tf.ensure_schema(conn)
    if cols and "out_doc" not in cols:
        # مرتجع المشتريات الذي أخرج الطقم من ملك المحلّ — دليلٌ على البطاقة
        conn.execute("ALTER TABLE work_orders ADD COLUMN out_doc TEXT"
                     " NOT NULL DEFAULT ''")


def _supplier(conn, supplier_id):
    ent = get_entity(conn, supplier_id)
    if not ent or ent["entity_type"] == "internal":
        raise ValueError("اختر المورد (شركة · مصنع · عميل) من دليل جهات"
                         " التعامل")
    return ent


def _vat_ok(conn):
    """المشتري (المحل) يخصم ضريبة المدخلات برقمه الضريبي — يُنبَّه إن غاب."""
    return bool(str(getattr(config, "COMPANY_VAT_NUMBER", "") or "").strip())


# ══════════════════════════ الشراء ══════════════════════════
def _prepare_line(conn, i, x, tx, seen, free=False):
    from models.inventory import (assert_not_legacy, is_bulk_no,
                                  model_for)
    wo_no = " ".join(str(x.get("wo_no") or "").split())[:40]
    if not wo_no:
        raise ValueError(f"السطر {i}: اكتب رقم التشغيل كما في فاتورة المورد")
    # 5.8.0: الإدخال الحر — الرقم وصفٌ للسطر (ولو تكرّر أو وُجد في الخزنة)
    bulk = False if free else is_bulk_no(wo_no)
    if not bulk and not free:
        assert_not_legacy(wo_no)
        if wo_no in seen:
            raise ValueError(f"رقم التشغيل {wo_no} مكرّر في الفاتورة")
        seen.add(wo_no)
        if conn.execute("SELECT 1 FROM work_orders WHERE work_order_no=?"
                        " AND is_deleted=0", (wo_no,)).fetchone():
            raise ValueError(f"رقم التشغيل {wo_no} موجود في خزنتك من قبل —"
                             " لكل طقمٍ رقمه")
    reg = round(float(x.get("registered") or 0), 3)
    std = x.get("standing")
    std = reg if std in (None, "", 0) else round(float(std), 3)
    if reg <= 0:
        raise ValueError(f"الطقم {wo_no}: اكتب الوزن المقيد")
    if std + 0.0005 < reg:
        raise ValueError(f"الطقم {wo_no}: الوزن القائم ({_nf.f2(std)}) أقل"
                         f" من المقيد ({_nf.f2(reg)}) — القائم يشمل الأحجار")
    pieces = int(x.get("pieces") or 1)
    if pieces <= 0:
        raise ValueError(f"الطقم {wo_no}: العدد يكون 1 فأكثر")
    _wg = x.get("wage")
    wage = round(float(0 if _wg in (None, "") else _wg), 4)
    if wage < 0:
        raise ValueError(f"الطقم {wo_no}: الأجر لا يكون سالباً")
    karat = int(x.get("karat") or 0)
    li = {"weight": reg, "wage": wage, "piece_price": x.get("piece_price"),
          "karat": karat, "gold_price": x.get("gold_price")}
    wages, gv = _tx.line_amounts(li, tx, wo_no)
    gp = float(_tx.line_tx(li, tx).get("gold_price") or 0) \
        if tx["pricing"] in _tx.RIYAL else 0.0
    return {"wo_no": wo_no, "bulk": bulk,
            "model_no": (" ".join(str(x.get("model_no") or "").split())[:60]
                         if free else
                         model_for(wo_no, x.get("model_no")) or ""),
            "pieces": pieces, "reg": reg, "std": std,
            "karat": karat, "wage": wage, "gold_price": gp,
            "piece_price": (round(float(x.get("piece_price") or 0), 2)
                            if tx["pricing"] == "piece" else 0.0),
            "wages": wages, "gv": gv, "net": round(wages + gv, 2),
            "notes": str(x.get("notes") or "").strip()}


def _post(conn, kind, sup, doc_no, doc_date, tx, set_by_acc, bulk_w, wages,
          gv, vat, total, username, note, discount=0.0):
    """قيد الشراء أو مرتجعه — بطريقة التسعير. `set_by_acc` = {حساب: وزن}
    للأطقم (5.5.2: تدخل الحساب المختار وتخرج منه)، و`bulk_w` وزن التجميعي
    (حساب الإيطالي)."""
    from models.stock_home import italian_account
    riyal = tx["pricing"] in _tx.RIYAL
    buy = kind == "purchase"
    set_w = round(sum(set_by_acc.values()), 3)
    total_w = round(set_w + bulk_w, 3)
    g_in, g_out = ("gold_debit", "gold_credit") if buy else \
        ("gold_credit", "gold_debit")
    c_in, c_out = ("cash_debit", "cash_credit") if buy else \
        ("cash_credit", "cash_debit")
    lines = []
    for acc, w in set_by_acc.items():
        if w > 0:
            lines.append({"account_id": acc, g_in: round(w, 3),
                          "line_desc": ("دخول الأطقم المشتراة" if buy
                                        else "خروج الأطقم المرتجعة للمورد")})
    if bulk_w > 0:
        lines.append({"account_id": italian_account(conn), g_in: bulk_w,
                      "line_desc": "ايطالي / نواعم (0010 · 00010)"})
    if riyal:
        lines.append({"account_id": acc_id(conn, _tx.BRIDGE), g_out: total_w,
                      "line_desc": "ذهبٌ بالريال — تسكيرٌ فوري (الوزن)"})
        if gv:
            lines.append({"account_id": acc_id(conn, _tx.BRIDGE), c_in: gv,
                          "line_desc": "ذهبٌ بالريال — تسكيرٌ فوري (القيمة)"})
        party = {c_out: total}
    else:
        party = {g_out: total_w, c_out: total}
    if wages:
        lines.append({"account_id": acc_id(conn, COST), c_in: wages,
                      "line_desc": "مصنعية الأطقم المشتراة"})
    if vat:
        lines.append({"account_id": acc_id(conn, VAT_IN), c_in: vat,
                      "line_desc": f"ضريبة مدخلات {doc_no}"})
    if discount:
        # 5.8.0: خصمٌ نقدي من المورد — يُنقص ما له ويُقيَّد خصماً مكتسباً
        from models.tax_free import DISC_EARNED
        lines.append({"account_id": acc_id(conn, DISC_EARNED),
                      c_out: discount,
                      "line_desc": ("خصم نقدي من المورد" if buy
                                    else "ردّ الخصم بنسبة المرتجع")})
    lines.append({"account_id": sup["account_id"], **party,
                  "line_desc": f"{KIND_LABEL[kind]} {doc_no}"})
    keys = ("gold_debit", "gold_credit", "cash_debit", "cash_credit")
    lines = [ln for ln in lines
             if any(abs(float(ln.get(k) or 0)) > 1e-9 for k in keys)]
    return post_entry(conn, doc_date,
                      f"{KIND_LABEL[kind]} {doc_no} — {sup['name']}", lines,
                      source_table="set_purchases", username=username,
                      note=note, doc_no=doc_no)


# حساباتٌ تحت مجموعة الذهب لا تدخلها أطقمٌ مشتراة: خزينة التصنيع (تشغيل
# الورش) · الإيطالي (للرقمين التجميعيين وحدهما) · تسويات الأوزان · الكسر
# (بالعيار وحده)
_NOT_DEST = ("1100", "1210", "1250", "1310")


def dest_accounts(conn):
    """الحسابات التي تدخلها أطقم الشراء (5.5.2): الذهب المشغول وحساب
    الألماس وكل حسابٍ يُضاف تحت مجموعة الذهب — ما عدا `_NOT_DEST`."""
    from models.accounts import gold_accounts
    return [r for r in gold_accounts(conn) if r["code"] not in _NOT_DEST]


def check_dest(conn, account_id=None):
    """حساب الوجهة متحقَّقاً — وبلا اختيارٍ فالذهب المشغول كما كان."""
    from models.inventory import resolve_dest
    dest = resolve_dest(conn, account_id)
    if dest not in {int(r["id"]) for r in dest_accounts(conn)}:
        r = conn.execute("SELECT code, name FROM accounts WHERE id=?",
                         (dest,)).fetchone()
        raise ValueError(
            "لا تدخل الأطقم المشتراة إلى "
            + (f"{r['code']} — {r['name']}" if r else str(dest))
            + "\nخزينة التصنيع للتشغيل، والإيطالي للرقمين التجميعيين،"
              " والتسويات والكسر لهما شأنهما — اختر الذهب المشغول أو"
              " حساباً مثله (كالألماس)")
    return dest


def create_purchase(conn, supplier_id, doc_date, supplier_inv_no, lines,
                    username, pricing="wage", gold_price=0.0, price_karat=0,
                    notes="", dest_account_id=None, mode="vault",
                    discount=0.0):
    """فاتورة مشتريات ضريبية بالأطقم — تُدخل الأطقم الخزنة.

    5.8.0 — `mode`: ``vault`` (كما كان: لكل طقمٍ بطاقته في الخزنة برقمٍ
    فريد) · ``free`` (إدخال يدوي: الرقم وصفٌ للسطر ولو تكرّر، والوزن يدخل
    «مخزون الذهب الضريبي» أو الحساب المختار — بلا بطاقات). و`discount`
    خصمٌ نقدي على الفاتورة يُطرح من الوعاء قبل الضريبة.

    `lines` = [{wo_no, model_no, pieces, registered (18), standing (18),
                karat, wage (18) | piece_price, notes}]
    """
    from models.inventory import (adjust_bulk_wo, classify_item,
                                  generate_work_order_barcode)
    from models.stock_home import italian_account
    from services import gold_math
    from models import tax_free as _tf
    ensure_schema(conn)
    _tf.ensure_schema(conn)
    free = mode == "free"
    sup = _supplier(conn, supplier_id)
    # الحساب الذي تدخله الأطقم (وبلا اختيارٍ الذهب المشغول) — وتخرج منه
    # عند بيعها، فهو بيتها (`stock_home`). والإدخال الحر: مخزون الذهب
    # الضريبي أو حسابٌ مثله (لا الذهب المشغول ولا الإيطالي)
    dest = (_tf.check_stock(conn, dest_account_id) if free
            else check_dest(conn, dest_account_id))
    inv_no = str(supplier_inv_no or "").strip()
    if not inv_no:
        raise ValueError("اكتب رقم فاتورة المورد — بها تُخصم ضريبة المدخلات"
                         " ويُراجَع الإقرار")
    dup = conn.execute(
        "SELECT doc_no FROM set_purchases WHERE supplier_id=? AND"
        " supplier_inv_no=? AND kind='purchase' AND is_deleted=0",
        (supplier_id, inv_no)).fetchone()
    if dup:
        raise ValueError(f"فاتورة المورد {inv_no} مسجّلة من قبل ({dup[0]})"
                         " — لا تُقيَّد الفاتورة مرتين")
    tx = _tx.norm({"pricing": pricing, "gold_price": gold_price,
                   "price_karat": price_karat})
    seen = set()
    prep = [_prepare_line(conn, i, x, tx, seen, free=free)
            for i, x in enumerate(lines or [], 1)]
    if not prep:
        raise ValueError("أضف طقماً واحداً على الأقل")
    wages = round(sum(p["wages"] for p in prep), 2)
    gv = round(sum(p["gv"] for p in prep), 2)
    net = round(wages + gv, 2)
    disc = _tf.check_discount(net, discount)
    vat = _tx.doc_vat(round(net - disc, 2))
    total = round(net - disc + vat, 2)
    if total <= 0:
        raise ValueError("إجمالي الفاتورة صفر")
    set_w = round(sum(p["reg"] for p in prep if not p["bulk"]), 3)
    bulk_w = round(sum(p["reg"] for p in prep if p["bulk"]), 3)
    cur = conn.execute(
        "INSERT INTO set_purchases(kind,supplier_id,doc_date,supplier_inv_no,"
        "pricing,gold_price,price_karat,vat_rate,total_weight,wages,"
        "gold_value,net,vat,total,notes,created_by,dest_account_id)"
        " VALUES('purchase',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (supplier_id, doc_date, inv_no, tx["pricing"], tx["gold_price"],
         tx["price_karat"], float(config.VAT_RATE), round(set_w + bulk_w, 3),
         wages, gv, net, vat, total, (notes or "").strip(), username, dest))
    pid = cur.lastrowid
    conn.execute("UPDATE set_purchases SET free_lines=?, discount=? WHERE"
                 " id=?", (int(free), disc, pid))
    doc_no = _numbering.next_no(conn, PREFIX["purchase"])
    entry_id = _post(conn, "purchase", sup, doc_no, doc_date, tx,
                     {dest: set_w}, bulk_w, wages, gv, vat, total, username,
                     f"فاتورة المورد {inv_no}"
                     + (f" — {notes.strip()}" if (notes or "").strip()
                        else ""), discount=disc)
    conn.execute("UPDATE set_purchases SET doc_no=?, entry_id=? WHERE id=?",
                 (doc_no, entry_id, pid))
    conn.execute("UPDATE journal_entries SET source_id=? WHERE id=?",
                 (pid, entry_id))
    for i, p in enumerate(prep, 1):
        if free:
            wid = None              # الحر: لا بطاقة طقمٍ في الخزنة
        elif p["bulk"]:
            wo = adjust_bulk_wo(conn, p["reg"], username, wo_no=p["wo_no"])
            wid = wo["id"]
        else:
            big = round(p["std"] - p["reg"], 3)
            cur = conn.execute(
                "INSERT INTO work_orders(model_no,work_order_no,gross_weight,"
                "stones_weight,gold_weight,small_stones,big_stones,item_type,"
                "stones_after_discount,standing_gold,discount_rate,"
                "registered_weight,wage_per_gram,barcode_path,notes,entry_id,"
                "created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (p["model_no"] or None, p["wo_no"], p["std"], big, p["reg"],
                 0.0, big, classify_item(p["wo_no"], p["reg"], 0.0, big),
                 gold_math.stones_after_discount(big, 1.0), p["std"], 1.0,
                 p["reg"], p["wage"], generate_work_order_barcode(p["wo_no"]),
                 p["notes"], entry_id, username))
            wid = cur.lastrowid
            conn.execute("UPDATE work_orders SET stock_account_id=?, pieces=?"
                         " WHERE id=?", (dest, p["pieces"], wid))
            log_action(conn, username, "create", "work_orders", wid,
                       f"شراء {doc_no} reg={p['reg']}")
        conn.execute(
            "INSERT INTO set_purchase_lines(doc_id,line_no,work_order_id,"
            "wo_no,model_no,pieces,registered_weight,standing_weight,karat,"
            "wage_per_gram,piece_price,wages,gold_value,net,gold_price)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, i, wid, p["wo_no"], p["model_no"], p["pieces"], p["reg"],
             p["std"], p["karat"], p["wage"], p["piece_price"], p["wages"],
             p["gv"], p["net"], p["gold_price"]))
    _ = italian_account
    log_action(conn, username, "create", "set_purchases", pid,
               f"{doc_no} total={total}")
    return {"id": pid, "doc_no": doc_no, "entry_id": entry_id,
            "supplier_name": sup["name"], "net": net, "vat": vat,
            "total": total, "wages": wages, "gold_value": gv,
            "discount": disc, "free": free, "dest_account_id": dest,
            "weight": round(set_w + bulk_w, 3), "n": len(prep),
            "vat_number_set": _vat_ok(conn)}


# ══════════════════════════ المرتجع ══════════════════════════
def returnable(conn, purchase_id):
    """أسطر فاتورة الشراء وما يصلح منها للإرجاع الآن.

    الطقم المفرد: يُرجع كاملاً ما دام في الخزنة بوزنه كله (لم يُبع منه
    شيء). والتجميعي: ما بقي من سطره بعد مرتجعاته، وفي حدود رصيده."""
    ensure_schema(conn)
    from models import tax_free as _tf
    _tf.ensure_schema(conn)
    free = bool((conn.execute("SELECT free_lines FROM set_purchases WHERE"
                              " id=?", (int(purchase_id),)).fetchone()
                 or {"free_lines": 0})["free_lines"])
    out = []
    for ln in conn.execute(
            "SELECT l.*, w.status, w.is_deleted wdel,"
            " COALESCE(w.remaining_weight, w.registered_weight) rem,"
            " w.registered_weight wreg, COALESCE(w.is_bulk,0) bulk"
            " FROM set_purchase_lines l LEFT JOIN work_orders w"
            " ON w.id=l.work_order_id WHERE l.doc_id=? ORDER BY l.line_no",
            (int(purchase_id),)):
        used = conn.execute(
            "SELECT COALESCE(SUM(r.registered_weight),0) FROM"
            " set_purchase_lines r JOIN set_purchases d ON d.id=r.doc_id"
            " WHERE r.src_line_id=? AND d.is_deleted=0", (ln["id"],)
        ).fetchone()[0]
        left = round(float(ln["registered_weight"]) - float(used or 0), 3)
        why = ""
        if left <= 0.0005:
            why = "أُرجع من قبل"
        elif free:
            pass                    # الحر: يُرجع ما بقي من وزنه — بلا خزنة
        elif ln["bulk"]:
            bal = float(ln["wreg"] or 0)
            if bal + 0.0005 < left:
                left = max(0.0, round(bal, 3))
                if left <= 0.0005:
                    why = "رصيد الرقم التجميعي لا يكفي"
        elif ln["wdel"] or ln["status"] != "in_stock" or \
                abs(float(ln["rem"] or 0) - float(ln["wreg"] or 0)) > 0.0005:
            why = "ليس في الخزنة بوزنه كله (بيع منه أو خرج)"
        out.append({"line_id": ln["id"], "work_order_id": ln["work_order_id"],
                    "wo_no": ln["wo_no"], "model_no": ln["model_no"],
                    "pieces": ln["pieces"], "registered": ln["registered_weight"],
                    "standing": ln["standing_weight"], "karat": ln["karat"],
                    "wage": ln["wage_per_gram"],
                    "piece_price": ln["piece_price"],
                    "bulk": bool(ln["bulk"]) and not free, "free": free,
                    "wages": float(ln["wages"] or 0),
                    "gold_value": float(ln["gold_value"] or 0),
                    "net": float(ln["net"] or 0),
                    "gold_price": float(ln["gold_price"] or 0),
                    "left": 0.0 if why else max(0.0, left), "why": why})
    return out


def create_return(conn, purchase_id, doc_date, returns, reason, username):
    """مرتجع مشتريات من فاتورةٍ بعينها: `returns` = [{line_id, weight
    (للتجميعي — فارغ = الباقي)}]. الطقم المفرد يُرجع كاملاً."""
    from models.inventory import adjust_bulk_wo
    ensure_schema(conn)
    o = conn.execute("SELECT * FROM set_purchases WHERE id=? AND is_deleted=0"
                     " AND kind='purchase'", (int(purchase_id),)).fetchone()
    if not o:
        raise ValueError("اختر فاتورة المشتريات الأصلية")
    if not str(reason or "").strip():
        raise ValueError("اكتب سبب المرتجع")
    if str(doc_date) < str(o["doc_date"]):
        raise ValueError("تاريخ المرتجع يسبق تاريخ فاتورة الشراء")
    sup = _supplier(conn, o["supplier_id"])
    tx = _tx.norm({"pricing": o["pricing"], "gold_price": o["gold_price"],
                   "price_karat": o["price_karat"]})
    from models import tax_free as _tf
    free = bool(dict(o).get("free_lines"))
    avail = {r["line_id"]: r for r in returnable(conn, purchase_id)}
    prep = []
    for x in returns or []:
        r = avail.get(int(x.get("line_id") or 0))
        if not r:
            raise ValueError("سطرٌ ليس من أسطر الفاتورة الأصلية")
        if r["why"]:
            raise ValueError(f"الطقم {r['wo_no']}: {r['why']} — لا يُرجع")
        w = r["left"]
        if (r["bulk"] or free) and x.get("weight") not in (None, "", 0):
            w = round(float(x["weight"]), 3)
            if w <= 0 or w > r["left"] + 0.0005:
                raise ValueError(f"{r['wo_no']}: الوزن المرتجع أكبر من الباقي"
                                 f" ({_nf.f2(r['left'])})")
        frac = (w / float(r["registered"])) if r["registered"] else 1.0
        li = {"weight": w, "wage": r["wage"],
              "piece_price": round(float(r["piece_price"] or 0) * frac, 2),
              "karat": r["karat"], "gold_price": r["gold_price"]}
        wages, gv = _tx.line_amounts(li, tx, r["wo_no"])
        prep.append({**r, "w": w, "wages": wages, "gv": gv,
                     "net": round(wages + gv, 2),
                     "pp": li["piece_price"] if tx["pricing"] == "piece"
                     else 0.0,
                     "std_r": round(float(r["standing"]) * frac, 3)})
    if not prep:
        raise ValueError("اختر طقماً واحداً على الأقل للإرجاع")
    wages = round(sum(p["wages"] for p in prep), 2)
    gv = round(sum(p["gv"] for p in prep), 2)
    net = round(wages + gv, 2)
    # 5.8.0: يُردّ من خصم الأصل بنسبة ما أُرجع من صافيه
    disc = _tf.share(dict(o).get("discount") or 0, net, o["net"])
    vat = _tx.doc_vat(round(net - disc, 2))
    total = round(net - disc + vat, 2)
    set_w = round(sum(p["w"] for p in prep if not p["bulk"]), 3)
    bulk_w = round(sum(p["w"] for p in prep if p["bulk"]), 3)
    # 5.5.2: كل طقمٍ يخرج من الحساب الذي هو فيه (بيته) — لا من حسابٍ ثابت
    from models.stock_home import line_account
    by_acc = {}
    for p in prep:
        if p["bulk"]:
            continue
        if free:
            acc = o["dest_account_id"] or _tf.check_stock(conn)
            by_acc[acc] = round(by_acc.get(acc, 0.0) + p["w"], 3)
            continue
        wo = conn.execute("SELECT * FROM work_orders WHERE id=?",
                          (p["work_order_id"],)).fetchone()
        acc = line_account(conn, wo) if wo else None
        acc = acc or o["dest_account_id"] or acc_id(conn, "1200")
        by_acc[acc] = round(by_acc.get(acc, 0.0) + p["w"], 3)
    cur = conn.execute(
        "INSERT INTO set_purchases(kind,supplier_id,doc_date,supplier_inv_no,"
        "pricing,gold_price,price_karat,vat_rate,total_weight,wages,"
        "gold_value,net,vat,total,ref_id,reason,created_by) VALUES("
        "'purchase_return',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (o["supplier_id"], doc_date, o["supplier_inv_no"], tx["pricing"],
         tx["gold_price"], tx["price_karat"], float(config.VAT_RATE),
         round(set_w + bulk_w, 3), wages, gv, net, vat, total, o["id"],
         str(reason).strip(), username))
    rid = cur.lastrowid
    conn.execute("UPDATE set_purchases SET free_lines=?, discount=?,"
                 " dest_account_id=? WHERE id=?",
                 (int(free), disc, o["dest_account_id"], rid))
    doc_no = _numbering.next_no(conn, PREFIX["purchase_return"])
    entry_id = _post(conn, "purchase_return", sup, doc_no, doc_date, tx,
                     by_acc, bulk_w, wages, gv, vat, total, username,
                     f"مرتجع من {o['doc_no']} (فاتورة المورد"
                     f" {o['supplier_inv_no']}) — {str(reason).strip()}",
                     discount=disc)
    conn.execute("UPDATE set_purchases SET doc_no=?, entry_id=? WHERE id=?",
                 (doc_no, entry_id, rid))
    conn.execute("UPDATE journal_entries SET source_id=? WHERE id=?",
                 (rid, entry_id))
    for i, p in enumerate(prep, 1):
        conn.execute(
            "INSERT INTO set_purchase_lines(doc_id,line_no,work_order_id,"
            "wo_no,model_no,pieces,registered_weight,standing_weight,karat,"
            "wage_per_gram,piece_price,wages,gold_value,net,src_line_id)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, i, p["work_order_id"], p["wo_no"], p["model_no"],
             p["pieces"], p["w"], p["std_r"], p["karat"], p["wage"], p["pp"],
             p["wages"], p["gv"], p["net"], p["line_id"]))
        if free:
            continue                # الحر: لا بطاقة طقمٍ تُطوى
        if p["bulk"]:
            adjust_bulk_wo(conn, -p["w"], username, wo_id=p["work_order_id"])
        else:
            # الطقم لم يعد للمحل: تُطوى بطاقته ويبقى المرتجع دليلها
            conn.execute("UPDATE work_orders SET is_deleted=1, out_doc=?"
                         " WHERE id=?", (doc_no, p["work_order_id"]))
            log_action(conn, username, "update", "work_orders",
                       p["work_order_id"], f"أُرجع للمورد بالمرتجع {doc_no}")
    log_action(conn, username, "create", "set_purchases", rid,
               f"{doc_no} ← {o['doc_no']} total={total}")
    return {"id": rid, "doc_no": doc_no, "entry_id": entry_id,
            "supplier_name": sup["name"], "net": net, "vat": vat,
            "total": total, "discount": disc, "free": free,
            "weight": round(set_w + bulk_w, 3), "n": len(prep)}


# ══════════════════════════ القراءة ══════════════════════════
def get(conn, doc_id):
    ensure_schema(conn)
    d = conn.execute(
        "SELECT p.*, e.name supplier_name, o.doc_no ref_no FROM set_purchases"
        " p JOIN entities e ON e.id=p.supplier_id LEFT JOIN set_purchases o"
        " ON o.id=p.ref_id WHERE p.id=?", (int(doc_id),)).fetchone()
    if not d:
        return None
    d = dict(d)
    d["lines"] = [dict(r) for r in conn.execute(
        "SELECT * FROM set_purchase_lines WHERE doc_id=? ORDER BY line_no",
        (int(doc_id),))]
    return d


def search(conn, q="", date_from=None, date_to=None, kind=None, limit=500):
    ensure_schema(conn)
    sql = ("SELECT p.*, e.name supplier_name, o.doc_no ref_no,"
           " (SELECT COUNT(*) FROM set_purchase_lines l WHERE l.doc_id=p.id)"
           " n_items FROM set_purchases p JOIN entities e"
           " ON e.id=p.supplier_id LEFT JOIN set_purchases o ON o.id=p.ref_id"
           " WHERE p.is_deleted=0")
    args = []
    if kind:
        sql += " AND p.kind=?"
        args.append(kind)
    if date_from:
        sql += " AND p.doc_date>=?"
        args.append(date_from)
    if date_to:
        sql += " AND p.doc_date<=?"
        args.append(date_to)
    if q:
        sql += (" AND (p.doc_no LIKE ? OR p.supplier_inv_no LIKE ? OR e.name"
                " LIKE ? OR EXISTS (SELECT 1 FROM set_purchase_lines l WHERE"
                " l.doc_id=p.id AND l.wo_no LIKE ?))")
        args += [f"%{q}%"] * 4
    sql += " ORDER BY p.doc_date DESC, p.id DESC LIMIT ?"
    args.append(int(limit))
    return [dict(r) for r in conn.execute(sql, args)]


def open_purchases(conn):
    """فواتير الشراء التي فيها ما يصلح للإرجاع الآن."""
    return [r for r in search(conn, kind="purchase", limit=2000)
            if any(x["left"] > 0.0005 for x in returnable(conn, r["id"]))]


def totals(conn, date_from, date_to):
    """صافي المشتريات الضريبية بالأطقم في الفترة (للإقرار): الوعاء والضريبة."""
    ensure_schema(conn)
    r = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN kind='purchase' THEN 1 ELSE -1 END"
        " * (net - COALESCE(discount,0))),0) base,"
        " COALESCE(SUM(CASE WHEN kind='purchase' THEN vat"
        " ELSE -vat END),0) vat, COUNT(*) n FROM set_purchases"
        " WHERE is_deleted=0 AND doc_date BETWEEN ? AND ?",
        (date_from, date_to)).fetchone()
    return {"base": round(r["base"], 2), "vat": round(r["vat"], 2),
            "n": r["n"]}


def register_rows(conn, date_from, date_to):
    """سجل المشتريات الضريبية بالأطقم — صفٌّ لكل مستند (للسجل الضريبي)."""
    return [r for r in search(conn, date_from=date_from, date_to=date_to,
                              limit=100000)]


def _today():
    return _dt.date.today().isoformat()
