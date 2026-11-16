# -*- coding: utf-8 -*-
"""حذف المستند وعكس قيده — ورقمه يتحرّر للمستند التالي (5.7.0).

بطلب صاحب النظام: فاتورة المبيعات والمرتجع وسند القبض والصرف والقيد
اليومي والتسكير **تُحذف** إذا أُدخلت خطأً — لا تبقى برقمها مع مستندٍ
يعكسها — ولا يبقى رقمها فجوةً في الدفتر: أول مستندٍ جديد من نوعها يأخذه
(`models.numbering.release`).

والحذف **محاسبيٌّ لا مادّي**، في معاملةٍ واحدة لا تتجزأ:

  1. يُعكس أثر المستند كاملاً بمحرّك الإلغاء المركزي نفسه
     (`services.audit.reverse_entry`): قيده، وحالة أطقمه ورصيد الرقم
     التجميعي، وحركات صندوق الكسر بعيارها.
  2. حركة الطقم تُفحص قبل الحفظ: حذفٌ يجعل سلسلة طقمٍ غير منتظمة (مرتجعٌ
     بلا بيع، أو بيعٌ مرتين) يُرفض كله بأسماء الأطقم ولا يُحفظ منه شيء.
  3. يُعاد تسمية المحذوف (`S-00005·محذوف·12`) فيتحرّر رقمه، ويبقى أثره
     في سجل التتبع وحده — لا في الكشوف ولا الأرصدة.

**ما لا يُحذف — نظاماً**:

  · الفاتورة الضريبية (عليها ضريبة القيمة المضافة أو صدرت لها فاتورة
    إلكترونية): هيئة الزكاة والضريبة والجمارك تمنع حذف الفاتورة بعد
    إصدارها أو إعادة استعمال رقمها — تُعكس بمرتجعٍ (إشعار دائن) يشير
    إليها (`reverse_vat`).
  · مستندٌ عُكس بمستندٍ آخر: يُحذف مستند العكس أولاً.
  · مستندٌ في فترةٍ مقفلة.
"""
from services.audit import log_action, reverse_entry

KINDS = {"sale": "فاتورة المبيعات", "sale_return": "فاتورة المرتجع",
         "receipt": "سند القبض", "payment": "سند الصرف",
         "manual": "القيد اليومي", "fixing": "التسكير"}
INVOICE_KINDS = ("sale", "sale_return")
MANUAL_SOURCES = (None, "", "manual")

VAT_MSG = ("فاتورةٌ ضريبية (عليها ضريبة القيمة المضافة) — لا تُحذف نظاماً"
           " ولا يُعاد استعمال رقمها: هيئة الزكاة والضريبة والجمارك تمنع"
           " حذف الفاتورة بعد إصدارها.\nتُلغى بـ«عكس»: مرتجعٌ يعكسها كاملةً"
           " ويشير إليها، وتبقى هي برقمها.")


def _doc(conn, entry_id):
    """(صفّ القيد، وصف مستنده)."""
    e = conn.execute("SELECT * FROM journal_entries WHERE id=?",
                     (int(entry_id),)).fetchone()
    if not e:
        raise ValueError("المستند غير موجود")
    src, sid = e["source_table"], e["source_id"]
    d = {"eid": e["id"], "src": src, "sid": sid, "date": e["entry_date"],
         "deleted": bool(e["is_deleted"]), "no": e["doc_no"] or "",
         "kind": None, "table": None, "col": None, "rec_id": None,
         "vat": False, "party_id": None}
    if src == "invoices" and sid:
        r = conn.execute("SELECT id, kind, invoice_no, vat_applied,"
                         " customer_id FROM invoices WHERE id=?",
                         (sid,)).fetchone()
        if r:
            d.update(kind=r["kind"], no=r["invoice_no"] or d["no"],
                     table="invoices", col="invoice_no", rec_id=r["id"],
                     vat=bool(r["vat_applied"]), party_id=r["customer_id"])
    elif src == "vouchers" and sid:
        r = conn.execute("SELECT id, kind, voucher_no, customer_id"
                         " FROM vouchers WHERE id=?", (sid,)).fetchone()
        if r:
            d.update(kind=r["kind"], no=r["voucher_no"] or d["no"],
                     table="vouchers", col="voucher_no", rec_id=r["id"],
                     party_id=r["customer_id"])
    elif src == "fixing_ops" and sid:
        r = conn.execute("SELECT id, op_no, customer_id FROM fixing_ops"
                         " WHERE id=?", (sid,)).fetchone()
        if r:
            d.update(kind="fixing", no=r["op_no"] or d["no"],
                     table="fixing_ops", col="op_no", rec_id=r["id"],
                     party_id=r["customer_id"])
    elif src in MANUAL_SOURCES:
        d["kind"] = "manual"
    return e, d


def describe(conn, entry_id):
    """وصف المستند للواجهات: نوعه ورقمه وهل يُحذف (أو يُعكس) ولماذا."""
    try:
        e, d = _doc(conn, entry_id)
    except ValueError as ex:
        return {"eid": entry_id, "kind": None, "can_delete": False,
                "can_reverse": False, "why": str(ex)}
    d["label"] = KINDS.get(d["kind"], "")
    try:
        check(conn, entry_id)
        d["can_delete"], d["why"] = True, ""
    except ValueError as ex:
        d["can_delete"], d["why"] = False, str(ex)
    # الفاتورة الضريبية تُعكس بمرتجع بدل الحذف
    d["can_reverse"] = False
    if not d["can_delete"] and d["kind"] in INVOICE_KINDS and d["vat"]:
        try:
            _check_reverse(conn, e, d)
            d["can_reverse"] = True
        except ValueError:
            pass
    return d


def check(conn, entry_id):
    """يرفع ValueError بسببٍ مفهوم إن كان المستند لا يُحذف — وإلا يعيد
    وصفه. يُسأل قبل التأكيد وفي الحذف نفسه."""
    e, d = _doc(conn, entry_id)
    if d["deleted"]:
        raise ValueError("المستند محذوف مسبقاً")
    if d["kind"] not in KINDS:
        raise ValueError("هذا النوع من العمليات يُلغى من شاشته في البرنامج")
    if d["kind"] in INVOICE_KINDS:
        if d["vat"]:
            raise ValueError(VAT_MSG)
        from models import tax_invoices as _txg
        _txg.guard(conn, d["rec_id"], "حذف")
        from services.fatoora import ledger as _fatoora
        _fatoora.guard_change(conn, "invoices", d["rec_id"], "حذف")
        dep = conn.execute(
            "SELECT note_no FROM tax_debit_notes WHERE invoice_id=?"
            " AND COALESCE(is_deleted,0)=0", (d["rec_id"],)).fetchone()
        if dep:
            raise ValueError(f"على الفاتورة إشعار مدين ({dep['note_no']}) —"
                             " احذفه أولاً")
    from models import reversal
    r = reversal.reversal_of(conn, e["id"])
    if r:
        raise ValueError(f"هذا المستند عُكس بالمستند {r['rev_no']} — احذف"
                         " مستند العكس أولاً ثم احذفه إن شئت")
    from models import fiscal
    fiscal.assert_open(conn, e["entry_date"])
    return d


def _check_reverse(conn, e, d):
    from models import reversal
    if d["deleted"]:
        raise ValueError("المستند محذوف مسبقاً")
    if reversal.reversal_of(conn, e["id"]):
        raise ValueError("عُكس مسبقاً")
    if reversal.reverses(conn, e["id"]):
        raise ValueError("مستند عكس — لا يُعكس")


def _invoice_wos(conn, invoice_id):
    return [r[0] for r in conn.execute(
        "SELECT work_order_id FROM invoice_items WHERE invoice_id=?",
        (invoice_id,))]


def retire(conn, d, username, why="حذف"):
    """يُحرِّر رقم المستند: يُعاد تسمية المحذوف ويُعطى رقمه للمستند التالي."""
    from models import numbering
    no = d.get("no") or ""
    if not no or numbering.RETIRED in no:
        return ""
    new = numbering.retire_name(no, d.get("rec_id") or d["eid"])
    if d.get("table"):
        conn.execute(f"UPDATE {d['table']} SET {d['col']}=? WHERE id=?",
                     (new, d["rec_id"]))
    conn.execute("UPDATE journal_entries SET doc_no=? WHERE id=?",
                 (new, d["eid"]))
    numbering.release(conn, no, username)
    return no


def delete(conn, entry_id, username, reason=""):
    """يحذف المستند ويعكس قيده ويُحرِّر رقمه — داخل معاملة conn."""
    d = check(conn, entry_id)
    from models import reversal
    back = reversal.reverses(conn, d["eid"])
    wos = _invoice_wos(conn, d["rec_id"]) if d["kind"] in INVOICE_KINDS \
        else []
    if wos:
        from models.operations import _one_move
        with _one_move(conn, wos, username):
            reverse_entry(conn, d["eid"], username)
    else:
        reverse_entry(conn, d["eid"], username)
    no = retire(conn, d, username)
    if back:
        # كان مستندَ عكسٍ لغيره: بحذفه يعود الأصل سارياً كما كان
        conn.execute("DELETE FROM doc_reversals WHERE rev_entry_id=?",
                     (d["eid"],))
    label = KINDS[d["kind"]]
    log_action(conn, username, "delete_doc", d["table"] or "manual",
               d["rec_id"] or d["eid"],
               f"حذف {label} {no or d['eid']} نهائياً وعكس قيده — الرقم"
               f" حُرِّر للمستند التالي" + (f" | {reason}" if reason else ""))
    msg = (f"حُذف {label} {no} وعُكس قيده — وأول {label} جديد يأخذ رقمه."
           if no else f"حُذف {label} وعُكس قيده.")
    if back:
        msg += f"\nوكان عكساً للمستند {back['src_no']} — فعاد ساريًا."
    return {"ok": True, "no": no, "kind": d["kind"], "label": label,
            "src": d["src"], "sid": d["rec_id"], "msg": msg}


def reverse_vat(conn, entry_id, username):
    """الفاتورة الضريبية تُعكس بمرتجعٍ يشير إليها (لا تُحذف)."""
    e, d = _doc(conn, entry_id)
    if d["kind"] not in INVOICE_KINDS:
        raise ValueError("العكس هنا لفواتير المبيعات والمرتجع")
    _check_reverse(conn, e, d)
    from models import reversal
    msg = reversal.reverse(conn, d["eid"], username, day=d["date"])
    return {"ok": True, "no": d["no"], "kind": d["kind"],
            "label": KINDS[d["kind"]], "msg": msg}


# ══════════════════════════════════════════════════════════════════
#  للبرنامج المكتبي — بمعاملةٍ مستقلة
# ══════════════════════════════════════════════════════════════════

def confirm_text(entry_id):
    """نصّ التأكيد قبل الحذف بحسب نوع المستند."""
    from database.database import db
    with db(readonly=True) as conn:
        d = describe(conn, entry_id)
    if d.get("can_delete"):
        return (f"حذف {d['label']} {d.get('no') or ''} نهائياً؟\n\n"
                "يُعكس قيده كاملاً (الأرصدة والأطقم وصندوق الكسر)، ويختفي من"
                " الكشوف، وأول مستندٍ جديد من نوعه يأخذ رقمه — فلا فجوة في"
                " الأرقام.")
    if d.get("can_reverse"):
        return (f"{d['label']} {d.get('no') or ''} ضريبية — لا تُحذف نظاماً."
                "\n\nعكسها بمرتجعٍ يشير إليها؟ (تبقى برقمها ويُلغى أثرها)")
    return (f"إلغاء العملية (القيد {entry_id})؟\n\n"
            + (d.get("why") or "تُلغى بأثرها كما في شاشتها."))


def delete_document(entry_id, username, reason=""):
    """حذف من شاشات البرنامج: النوع المدعوم يُحذف ويتحرّر رقمه، والفاتورة
    الضريبية تُعكس بمرتجع، وما سواهما يُلغى كما كان (`soft_delete_entry`)."""
    from database.database import db
    from services.audit import soft_delete_entry
    with db(readonly=True) as conn:
        d = describe(conn, entry_id)
    if d.get("kind") in KINDS and not d.get("can_delete") \
            and not d.get("can_reverse"):
        raise ValueError(d.get("why") or "لا يُحذف هذا المستند")
    if d.get("can_reverse"):
        with db() as conn:
            return reverse_vat(conn, entry_id, username)["msg"]
    if not d.get("can_delete"):
        return soft_delete_entry(int(entry_id), username)
    with db() as conn:
        res = delete(conn, entry_id, username, reason)
    if res["src"] == "invoices" and res["sid"]:
        _announce_cancel(res["sid"])
    return res["msg"]


def _announce_cancel(invoice_id):
    """صفحة الفاتورة المنشورة (إن نُشرت) تُعلن إلغاءها — في خيطٍ جانبي."""
    try:
        import threading
        import config
        from services import invoice_share
        threading.Thread(target=invoice_share.mark_cancelled,
                         args=(invoice_id, config.COMPANY_NAME),
                         daemon=True, name="InvoiceCancelNotice").start()
    except Exception:
        pass
