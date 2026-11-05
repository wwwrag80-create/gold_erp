# -*- coding: utf-8 -*-
"""حساب «ايطالي / نواعم» — كشف الرقمين التجميعيين 0010 و00010 (5.1.9).

الرقمان رصيدٌ وزني يزيد بالتوريد والمرتجع وينقص بالبيع، ولا حساب لهما
في الدليل (وزنهما داخل الذهب المشغول). فكشفُهما يُبنى من المستندات
نفسها، سطراً لكل حركة:

  · توريد / رصيد افتتاحي  ← سطور دفعات التوريد (`wo_batch_lines`) بقيدٍ قائم
  · بيع                   ← بنود فواتير البيع: إلى العميل (دائن)
  · مرتجع                 ← بنود فواتير المرتجع: من العميل (مدين)

والرصيد المسجَّل على بطاقتي الرقمين هو ما تعرضه لوحة التحكم ودليل
الموديلات. إن خالف مجموعَ المستندات (رصيدٌ دخل قبل أن تُحفظ سطور
الدفعات، أو تعديلٌ قديم لم يُحرّكه) ظهر الفرق سطراً أولاً باسمه —
فيتطابق آخر الكشف مع ما تعرضه الشاشات، ولا يُخفى الفرق.
"""
from models.inventory import BULK_WO_NOS
from models.accounts import ITALIAN_GOLD as ACC_CODE   # 1210 (5.2.0)

CODE = "@italian"                      # رمزه في لوحات لوحة التحكم
NAME = "ايطالي / نواعم"
EPS = 0.0005

# ترتيب حركات اليوم الواحد: الوارد قبل الصادر
_RANK = {"open": 0, "supply": 1, "return": 2, "sale": 3}
LABEL = {"open": "رصيد سابق غير مفصّل", "opening": "رصيد افتتاحي",
         "supply": "توريد", "sale": "بيع", "return": "مرتجع"}


def cards(conn):
    """بطاقتا الرقمين القائمتان: [{id, no, balance}]."""
    q = ",".join("?" * len(BULK_WO_NOS))
    return [{"id": r["id"], "no": r["work_order_no"],
             "balance": round(float(r["registered_weight"] or 0), 3)}
            for r in conn.execute(
                "SELECT id, work_order_no, registered_weight FROM work_orders"
                f" WHERE is_bulk=1 AND is_deleted=0 AND work_order_no IN ({q})"
                " ORDER BY work_order_no DESC", list(BULK_WO_NOS))]


def movements(conn, ids=None):
    """كل حركات الرقمين من المستندات — بترتيبها: [{date, kind, doc,
    party, no, debit, credit, ref}]."""
    if ids is None:
        ids = [c["id"] for c in cards(conn)]
    ids = [int(i) for i in ids]
    if not ids:
        return []
    q = ",".join("?" * len(ids))
    out = []
    for r in conn.execute(
            "SELECT e.entry_date d, e.id eid, COALESCE(e.doc_no,'') ref,"
            " e.description dsc, l.registered_weight w, l.id lid,"
            " w.work_order_no no"
            " FROM wo_batch_lines l"
            " JOIN journal_entries e ON e.id=l.entry_id AND e.is_deleted=0"
            " JOIN work_orders w ON w.id=l.work_order_id"
            f" WHERE l.work_order_id IN ({q})", ids):
        w = round(float(r["w"] or 0), 3)
        if abs(w) < EPS:
            continue
        opening = "افتتاحي" in (r["dsc"] or "")
        doc = r["ref"] or f"دفعة {r['eid']}"     # رقم الدفعة أو مرجعها
        out.append({"date": r["d"] or "", "kind": "supply",
                    "label": LABEL["opening" if opening else "supply"],
                    "doc": doc,
                    "party": ("رصيد افتتاحي مخزني" if opening
                              else "من خزينة التصنيع"),
                    "no": r["no"], "debit": max(w, 0.0),
                    "credit": max(-w, 0.0), "ref": ("entry", r["eid"]),
                    "_id": r["lid"]})
    for r in conn.execute(
            "SELECT i.invoice_date d, i.id iid, i.invoice_no inv, i.kind k,"
            " COALESCE(en.name,'—') party, it.registered_weight w,"
            " it.id itid, w.work_order_no no"
            " FROM invoice_items it"
            " JOIN invoices i ON i.id=it.invoice_id AND i.is_deleted=0"
            " LEFT JOIN entities en ON en.id=i.customer_id"
            " JOIN work_orders w ON w.id=it.work_order_id"
            f" WHERE it.work_order_id IN ({q})", ids):
        w = round(float(r["w"] or 0), 3)
        if abs(w) < EPS:
            continue
        sale = r["k"] == "sale"
        out.append({"date": r["d"] or "", "kind": "sale" if sale
                    else "return", "label": LABEL["sale" if sale
                                                   else "return"],
                    "doc": r["inv"] or "",
                    "party": ("إلى " if sale else "من ") + r["party"],
                    "no": r["no"], "debit": 0.0 if sale else w,
                    "credit": w if sale else 0.0,
                    "ref": ("invoice", r["iid"]), "_id": r["itid"]})
    out.sort(key=lambda m: (m["date"], _RANK[m["kind"]], m["_id"]))
    return out


def statement(conn, date_from=None, date_to=None):
    """الكشف: رصيدٌ أول (ما قبل الفترة) ثم الحركات برصيدٍ جارٍ، والإجمالي.

    `gap` = رصيد البطاقتين − مجموع المستندات: يُعرض سطراً أول باسمه."""
    cs = cards(conn)
    mv = movements(conn, [c["id"] for c in cs])
    card_total = round(sum(c["balance"] for c in cs), 3)
    doc_total = round(sum(m["debit"] - m["credit"] for m in mv), 3)
    gap = round(card_total - doc_total, 3)
    d1, d2 = str(date_from or ""), str(date_to or "")
    before = [m for m in mv if d1 and m["date"] < d1]
    inside = [m for m in mv if (not d1 or m["date"] >= d1)
              and (not d2 or m["date"] <= d2)]
    opening = round(gap + sum(m["debit"] - m["credit"] for m in before), 3)
    rows, bal = [], opening
    if abs(gap) > 0.005 and not d1:
        # بلا فترة: الفرق سطرٌ أول باسمه (لا رصيدٌ أول صامت)
        rows.append({"date": "", "kind": "open", "label": LABEL["open"],
                     "doc": "", "party": "قبل تفصيل الحركة في النظام",
                     "no": "", "debit": max(gap, 0.0),
                     "credit": max(-gap, 0.0), "balance": gap, "ref": None})
        opening = 0.0
        bal = gap
    for m in inside:
        bal = round(bal + m["debit"] - m["credit"], 3)
        rows.append({**{k: v for k, v in m.items() if k != "_id"},
                     "balance": bal})
    deb = round(sum(r["debit"] for r in rows), 3)
    cred = round(sum(r["credit"] for r in rows), 3)
    return {"cards": cs, "opening": opening, "rows": rows,
            "debit": deb, "credit": cred, "closing": round(bal, 3),
            "card_total": card_total, "doc_total": doc_total, "gap": gap,
            "date_from": d1, "date_to": d2,
            "counts": {k: sum(1 for r in rows if r["kind"] == k)
                       for k in ("supply", "sale", "return")}}


def panel_row(conn, date_from=None, date_to=None):
    """صفّه في لوحة التحكم: مدين الفترة ودائنها ورصيدها — كحسابٍ عادي."""
    st = statement(conn, date_from, date_to)
    deb = st["debit"]
    cred = st["credit"]
    if st["date_from"]:
        # كالحسابات: صافي حركة الفترة (والرصيد الأول خارجها)
        bal = round(deb - cred, 3)
    else:
        bal = st["closing"]
    return {"code": CODE, "name": f"{NAME} (0010 · 00010)",
            "gold_debit": deb, "gold_credit": cred, "gold_balance": bal,
            "cash_debit": 0.0, "cash_credit": 0.0, "cash_balance": 0.0,
            "virtual": True}


# ══════════════════════════════════════════════════════════════════
#  5.2.0 — حساب «ايطالي / نواعم» رسمي في المخزون (1210)
# ------------------------------------------------------------------
#  كان وزن الرقمين داخل الذهب المشغول (1200). الترقية — مرةً واحدة —
#  تفصله في حسابه بتاريخه، لا بقيدٍ واحد يخفي الحركة:
#   ١) بنود الفواتير القائمة على 0010 و00010 (الخارجة من المشغول) تُنسب
#      إلى حساب الإيطالي، ويُعاد بناء قيد كل فاتورة منها.
#   ٢) حصتهما في قيود التوريد والرصيد الافتتاحي تُنقل إلى سطرٍ على حسابه.
#   ٣) ما بقي فرقاً بين رصيد البطاقتين ورصيد الحساب (رصيدٌ قديم بلا
#      مستندات) يُنقل بقيد تحويلٍ ظاهر من الذهب المشغول.
#  فيكون رصيد الحساب = رصيد البطاقتين، ويخلو الذهب المشغول من الإيطالي.
#  لا فاتورة تُحذف ولا يتغيّر رقمها، ولا يتغيّر مجموع المخزون.
# ══════════════════════════════════════════════════════════════════
MIGRATION_KEY = "italian_account_5_2_0"


def account_id(conn):
    r = conn.execute("SELECT id FROM accounts WHERE code=?",
                     (ACC_CODE,)).fetchone()
    return int(r["id"]) if r else None


def account_balance(conn):
    a = account_id(conn)
    if not a:
        return 0.0
    r = conn.execute(
        "SELECT COALESCE(SUM(l.gold_debit),0)-COALESCE(SUM(l.gold_credit),0) b"
        " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
        " WHERE e.is_deleted=0 AND l.account_id=?", (a,)).fetchone()
    return round(float(r["b"] or 0), 3)


def migrate(conn, username="system", today=None):
    """الترقية مرةً واحدة — يعيد ملخّصها، أو None إن سبقت."""
    import datetime as _dt
    from models.fiscal import get_setting, set_setting
    from models.accounts import acc_id, FINISHED_GOLD
    if get_setting(conn, MIGRATION_KEY):
        return None
    ita = account_id(conn)
    if not ita:
        return None
    fin = acc_id(conn, FINISHED_GOLD)
    bulk_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM work_orders WHERE is_bulk=1")]
    out = {"invoices": 0, "entries": 0, "transfer": 0.0}
    if bulk_ids:
        q = ",".join("?" * len(bulk_ids))
        # ١) الفواتير — ما خرج من المشغول أو عاد إليه
        items = conn.execute(
            "SELECT it.id, it.invoice_id FROM invoice_items it"
            " JOIN invoices i ON i.id=it.invoice_id AND i.is_deleted=0"
            f" WHERE it.work_order_id IN ({q})"
            " AND COALESCE(it.stock_account_id, i.source_account_id, ?)=?",
            bulk_ids + [fin, fin]).fetchall()
        invs = sorted({r["invoice_id"] for r in items})
        for r in items:
            conn.execute("UPDATE invoice_items SET stock_account_id=?"
                         " WHERE id=?", (ita, r["id"]))
        from models.invoices import _rebuild_invoice_entry
        for iid in invs:
            if conn.execute("SELECT entry_id FROM invoices WHERE id=?",
                            (iid,)).fetchone()["entry_id"]:
                _rebuild_invoice_entry(conn, iid)
        out["invoices"] = len(invs)
        # ٢) التوريد والرصيد الافتتاحي — من سطر الذهب المشغول وحده
        from models.inventory import split_italian_line
        for r in conn.execute(
                "SELECT DISTINCT l.entry_id FROM wo_batch_lines l"
                " JOIN journal_entries e ON e.id=l.entry_id AND e.is_deleted=0"
                f" WHERE l.work_order_id IN ({q})", bulk_ids).fetchall():
            if abs(split_italian_line(conn, r["entry_id"],
                                      only_from=fin)) > 0.0005:
                out["entries"] += 1
    # ٣) ما بقي: رصيد البطاقتين − رصيد الحساب
    card = round(sum(c["balance"] for c in cards(conn)), 3)
    diff = round(card - account_balance(conn), 3)
    if abs(diff) > 0.0005:
        from services.accounting_engine import post_entry
        day = today or _dt.date.today().isoformat()
        desc = "تحويل رصيد ايطالي / نواعم (0010 · 00010) من الذهب المشغول"
        if diff > 0:
            lines = [{"account_id": ita, "gold_debit": diff,
                      "line_desc": "رصيد الرقمين التجميعيين قبل تفصيل الحركة"},
                     {"account_id": fin, "gold_credit": diff,
                      "line_desc": "خروج وزن الإيطالي من الذهب المشغول"}]
        else:
            lines = [{"account_id": fin, "gold_debit": -diff,
                      "line_desc": "عودة فرق الإيطالي إلى الذهب المشغول"},
                     {"account_id": ita, "gold_credit": -diff,
                      "line_desc": "تسوية حساب الإيطالي برصيد البطاقتين"}]
        post_entry(conn, day, desc, lines,
                   username=username, note="ترقية 5.2.0")
        out["transfer"] = diff
    set_setting(conn, MIGRATION_KEY, (today or _dt.date.today().isoformat()),
                username)
    from services.audit import log_action
    log_action(conn, username, "update", "accounts", ita,
               f"ترقية حساب الإيطالي: {out}")
    return out
