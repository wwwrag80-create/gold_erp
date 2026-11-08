# -*- coding: utf-8 -*-
"""لا حذف للمستندات — العكس بمستندٍ جديد (5.2.1).

رقم الفاتورة أو السند أو القيد لا يختفي أبداً: حذفُه يترك فجوةً في
التسلسل تُثير الشك عند أي مراجعة أو رقابة. فالإلغاء **مستندٌ جديد**
برقمٍ جديد يعكس الأول، ويبقى الأول ظاهراً في كشوفه برقمه:

  · فاتورة بيع        ← فاتورة مرتجع بالأطقم والأوزان والأجور نفسها
  · فاتورة مرتجع      ← فاتورة بيع بها
  · سند قبض           ← سند صرف بأسطره نفسها (والعكس)
  · قيد يومية يدوي    ← قيد عكسي (مدينه دائن ودائنه مدين)

وكل عكسٍ يُسجَّل في `doc_reversals`: فلا يُعكس المستند مرتين، ولا يُعكس
مستندُ العكس نفسه (فيدور التلاعب في حلقة)، ويُعرف من كل طرفٍ صاحبُه.
"""
import datetime as _dt

from services.accounting_engine import post_entry
from services.audit import log_action

INVOICE_OPPOSITE = {"sale": "sale_return", "sale_return": "sale"}
VOUCHER_OPPOSITE = {"receipt": "payment", "payment": "receipt"}
# مصادر يُعكس قيدها بقيدٍ مقابل (ما لا جدول أثرٍ جانبيٍّ له)
MIRROR_SOURCES = (None, "", "manual")


def ensure_schema(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS doc_reversals("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " src_entry_id INTEGER NOT NULL UNIQUE,"
        " rev_entry_id INTEGER NOT NULL,"
        " src_table TEXT, src_id INTEGER, src_no TEXT,"
        " rev_table TEXT, rev_id INTEGER, rev_no TEXT,"
        " created_by TEXT,"
        " created_at TEXT DEFAULT (datetime('now','localtime')))")


def supported(conn, entry_id):
    """هل يُعكس هذا القيد بمستندٍ جديد؟ (وإلا يُلغى بأثره كما كان)"""
    e = conn.execute("SELECT source_table FROM journal_entries WHERE id=?",
                     (entry_id,)).fetchone()
    return bool(e) and (e["source_table"] in ("invoices", "vouchers")
                        or e["source_table"] in MIRROR_SOURCES)


def reversal_of(conn, entry_id):
    """صفّ العكس الذي ألغى هذا القيد — أو None."""
    ensure_schema(conn)
    return conn.execute("SELECT * FROM doc_reversals WHERE src_entry_id=?",
                        (entry_id,)).fetchone()


def reverses(conn, entry_id):
    """صفّ العكس إن كان هذا القيد نفسه مستندَ عكس — أو None."""
    ensure_schema(conn)
    return conn.execute("SELECT * FROM doc_reversals WHERE rev_entry_id=?",
                        (entry_id,)).fetchone()


def _mirror_lines(conn, entry_id, tag):
    out = []
    for l in conn.execute(
            "SELECT account_id, gold_debit, gold_credit, cash_debit,"
            " cash_credit, line_desc FROM journal_lines WHERE entry_id=?"
            " ORDER BY id", (entry_id,)):
        out.append({"account_id": l["account_id"],
                    "gold_debit": l["gold_credit"] or 0,
                    "gold_credit": l["gold_debit"] or 0,
                    "cash_debit": l["cash_credit"] or 0,
                    "cash_credit": l["cash_debit"] or 0,
                    "line_desc": f"{tag}: {l['line_desc'] or ''}".strip()})
    return out


def _reverse_invoice(conn, e, username, day):
    from models import invoices
    inv = conn.execute("SELECT * FROM invoices WHERE id=? AND is_deleted=0",
                       (e["source_id"],)).fetchone()
    if not inv:
        raise ValueError("الفاتورة غير موجودة")
    opp = INVOICE_OPPOSITE.get(inv["kind"])
    if not opp:
        raise ValueError("نوع فاتورة لا يُعكس")
    cart = []
    for it in conn.execute(
            "SELECT it.*, COALESCE(w.is_service,0) svc FROM invoice_items it"
            " JOIN work_orders w ON w.id=it.work_order_id"
            " WHERE it.invoice_id=? ORDER BY it.id", (inv["id"],)):
        if it["svc"]:
            cart.append({"wage_only": True, "amount": it["wages"],
                         "note": it["line_note"] or ""})
        else:
            cart.append({"work_order_id": it["work_order_id"],
                         "weight": it["registered_weight"],
                         "wage_override": it["wage_per_gram"],
                         "karat": it["karat"], "diamond": it["diamond"],
                         "note": it["line_note"] or ""})
    if not cart:
        raise ValueError("الفاتورة بلا بنود — لا شيء يُعكس")
    word = "مرتجع" if opp == "sale_return" else "بيع"
    # `_save` مباشرةً لا `create_*`: العكس صورةُ الفاتورة كما هي — فلا
    # تُقسَّم إلى أطقمٍ وإيطالي ولو اجتمعا فيها (فاتورةٌ قبل 5.2.0)
    res = invoices._save(
        conn, opp, inv["customer_id"], cart, day, username,
        bool(inv["vat_applied"]),
        f"عكس الفاتورة {inv['invoice_no']}",
        qr_enabled=bool(inv["qr_enabled"]),
        source_account_id=inv["source_account_id"],
        scrap_karat=inv["scrap_karat"] or None)
    return ("invoices", res["id"], res["invoice_no"], res["entry_id"],
            f"عُكست الفاتورة {inv['invoice_no']} بفاتورة {word} "
            f"{res['invoice_no']} — وتبقى الأولى برقمها في الكشف")


def _reverse_voucher(conn, e, username, day):
    from models import numbering
    from models.inventory import add_scrap_move
    v = conn.execute("SELECT * FROM vouchers WHERE id=? AND is_deleted=0",
                     (e["source_id"],)).fetchone()
    if not v:
        raise ValueError("السند غير موجود")
    opp = VOUCHER_OPPOSITE[v["kind"]]
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(vouchers)")]
    skip = {"id", "voucher_no", "kind", "voucher_date", "notes", "entry_id",
            "is_deleted", "created_by", "created_at"}
    keep = [c for c in cols if c not in skip]
    note = f"عكس السند {v['voucher_no']}"
    cur = conn.execute(
        f"INSERT INTO vouchers(kind,voucher_date,notes,created_by"
        f"{''.join(',' + c for c in keep)}) VALUES(?,?,?,?"
        f"{',?' * len(keep)})",
        [opp, day, note, username] + [v[c] for c in keep])
    nid = cur.lastrowid
    no = numbering.next_no(conn, "RV" if opp == "receipt" else "PV")
    label = "سند قبض" if opp == "receipt" else "سند صرف"
    eid = post_entry(conn, day, f"{label} {no} — {note}",
                     _mirror_lines(conn, e["id"], note),
                     source_table="vouchers", source_id=nid,
                     username=username, note=note, doc_no=no)
    conn.execute("UPDATE vouchers SET voucher_no=?, entry_id=? WHERE id=?",
                 (no, eid, nid))
    for ln in conn.execute("SELECT * FROM voucher_lines WHERE voucher_id=?"
                           " ORDER BY id", (v["id"],)).fetchall():
        conn.execute(
            "INSERT INTO voucher_lines(voucher_id,line_kind,gold_weight,"
            "gold_karat,gold_equiv18,cash_amount,line_notes)"
            " VALUES(?,?,?,?,?,?,?)",
            (nid, ln["line_kind"], ln["gold_weight"], ln["gold_karat"],
             ln["gold_equiv18"], ln["cash_amount"], ln["line_notes"]))
    # صندوق الكسر بعياره: ما دخله القبض يخرج بالعكس (والعكس)
    for m in conn.execute(
            "SELECT karat, actual_delta FROM scrap_moves WHERE ref_table="
            "'vouchers' AND ref_id=? AND COALESCE(is_deleted,0)=0",
            (v["id"],)).fetchall():
        add_scrap_move(conn, m["karat"], -float(m["actual_delta"] or 0),
                       "vouchers", nid)
    word = "صرف" if opp == "payment" else "قبض"
    return ("vouchers", nid, no, eid,
            f"عُكس السند {v['voucher_no']} بسند {word} {no} — ويبقى الأول"
            " برقمه في الكشف")


def _reverse_manual(conn, e, username, day):
    no_old = e["doc_no"] or str(e["id"])
    note = f"عكس القيد {no_old}"
    eid = post_entry(conn, day, note, _mirror_lines(conn, e["id"], note),
                     source_table="manual", username=username, note=note)
    no = conn.execute("SELECT doc_no FROM journal_entries WHERE id=?",
                      (eid,)).fetchone()["doc_no"]
    return ("manual", eid, no, eid,
            f"عُكس القيد {no_old} بالقيد {no} — ويبقى الأول برقمه")


def reverse(conn, entry_id, username, day=None):
    """يعكس المستند بمستندٍ جديد — ويعيد رسالةً بما حدث."""
    ensure_schema(conn)
    e = conn.execute("SELECT * FROM journal_entries WHERE id=?",
                     (entry_id,)).fetchone()
    if not e:
        raise ValueError("القيد غير موجود")
    if e["is_deleted"]:
        raise ValueError("القيد ملغى مسبقاً")
    done = reversal_of(conn, entry_id)
    if done:
        raise ValueError(f"هذا المستند عُكس مسبقاً بالمستند {done['rev_no']}"
                         " — لا يُعكس مرتين")
    back = reverses(conn, entry_id)
    if back:
        raise ValueError(f"هذا مستند عكسٍ للمستند {back['src_no']} — لا "
                         "يُعكس (وإن أردت إعادة العملية فسجّلها من جديد)")
    day = day or _dt.date.today().isoformat()
    from models import fiscal
    fiscal.assert_open(conn, day)
    src = e["source_table"]
    if src == "invoices":
        out = _reverse_invoice(conn, e, username, day)
    elif src == "vouchers":
        out = _reverse_voucher(conn, e, username, day)
    elif src in MIRROR_SOURCES:
        out = _reverse_manual(conn, e, username, day)
    else:
        raise ValueError("هذا النوع من العمليات يُلغى بأثره من شاشته")
    rev_table, rev_id, rev_no, rev_eid, msg = out
    src_no = e["doc_no"] or str(e["id"])
    if src == "invoices":
        r = conn.execute("SELECT invoice_no FROM invoices WHERE id=?",
                         (e["source_id"],)).fetchone()
        src_no = r["invoice_no"] if r else src_no
    elif src == "vouchers":
        r = conn.execute("SELECT voucher_no FROM vouchers WHERE id=?",
                         (e["source_id"],)).fetchone()
        src_no = r["voucher_no"] if r else src_no
    conn.execute(
        "INSERT INTO doc_reversals(src_entry_id,rev_entry_id,src_table,"
        "src_id,src_no,rev_table,rev_id,rev_no,created_by)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (entry_id, rev_eid, src, e["source_id"], src_no, rev_table, rev_id,
         rev_no, username))
    log_action(conn, username, "reverse", src or "manual",
               e["source_id"] or entry_id, f"{src_no} ← {rev_no}")
    return msg
