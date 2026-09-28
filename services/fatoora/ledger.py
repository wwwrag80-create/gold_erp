# -*- coding: utf-8 -*-
"""سجل الفواتير الإلكترونية — العدّاد والسلسلة والإصدار والإرسال.

**ما تشترطه الهيئة وكيف يُحقَّق هنا**:
  · **عدّاد فواتير لا يُعاد ضبطه (ICV)**: رقمٌ يزيد بواحدٍ مع كل مستند،
    فريدٌ في الجدول، ولا يُحذف صفٌّ أبداً — فلا فجوة ولا تكرار.
  · **سلسلة بصمات (PIH)**: كل مستندٍ يحمل بصمة الذي قبله؛ تعديل أي
    مستندٍ سابق يكسر السلسلة من بعده ويُكشف في فحص الجاهزية.
  · **عدم القابلية للتعديل**: مُشغِّلات في قاعدة البيانات تمنع حذف أي
    مستند أو تعديل نصّه وبصمته وأرقامه — حتى من خارج البرنامج.
  · **لا تعديل ولا حذف لفاتورةٍ صدر مستندها**: التصحيح بإشعارٍ دائن
    (مرتجع) يشير إليها — كما يشترط نظام الفوترة.
  · **الإصدار داخل معاملة الفاتورة نفسها**: الفاتورة وقيدها ومستندها
    الإلكتروني يُحفظون معاً أو لا يُحفظ شيء — فلا فاتورة بلا مستند،
    ولا رقمٌ في السلسلة لفاتورةٍ أُلغي حفظها.
  · **الإرسال خارج المعاملة وفي الخلفية**: الشبكة لا تحبس قفل القاعدة
    ولا تُجمّد الواجهة، والمبسطة تُبلَّغ خلال 24 ساعة كما يُشترط.
"""
import json
import threading
from datetime import datetime

from services.fatoora import api, ec, rules, ubl
from services.fatoora import profile as pf

STATUS_LABELS = {
    "pending": "بانتظار الإرسال", "reported": "أُبلغت ✔",
    "cleared": "اعتُمدت ✔", "warning": "قُبلت بتنبيهات",
    "rejected": "مرفوضة ✘", "error": "تعذّر الإرسال — سيُعاد",
}
ACCEPTED = ("reported", "cleared", "warning")
QR_TABLES = ("invoices", "tax_sales")      # جداولٌ تُطبع برمز QR المستند
KIND_LABELS = {"invoice": "فاتورة", "credit": "إشعار دائن",
               "debit": "إشعار مدين"}
SUB_LABELS = {"standard": "ضريبية (B2B)", "simplified": "مبسطة (B2C)"}


# ══════════════════════════ الجداول والحماية ══════════════════════════
DDL = (
    "CREATE TABLE IF NOT EXISTS fatoora_documents("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " source_table TEXT NOT NULL, source_id INTEGER NOT NULL,"
    " doc_no TEXT NOT NULL, kind TEXT NOT NULL, subtype TEXT NOT NULL,"
    " uuid TEXT NOT NULL UNIQUE, icv INTEGER NOT NULL UNIQUE,"
    " pih TEXT NOT NULL, invoice_hash TEXT NOT NULL,"
    " qr TEXT NOT NULL, xml TEXT NOT NULL,"
    " issue_date TEXT, issue_time TEXT,"
    " net REAL, vat REAL, gross REAL, env TEXT,"
    " status TEXT NOT NULL DEFAULT 'pending',"
    " attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT DEFAULT '',"
    " response TEXT DEFAULT '', cleared_xml TEXT DEFAULT '',"
    " cleared_qr TEXT DEFAULT '', submitted_at TEXT,"
    " archived INTEGER NOT NULL DEFAULT 0,"
    " created_by TEXT,"
    " created_at TEXT DEFAULT (datetime('now','localtime')))",
    "CREATE INDEX IF NOT EXISTS idx_fatoora_src"
    " ON fatoora_documents(source_table, source_id, archived)",
    "CREATE INDEX IF NOT EXISTS idx_fatoora_status"
    " ON fatoora_documents(status)",
    "CREATE TRIGGER IF NOT EXISTS fatoora_no_delete"
    " BEFORE DELETE ON fatoora_documents BEGIN"
    " SELECT RAISE(ABORT, 'مستندات الفوترة الإلكترونية لا تُحذف'); END",
    "CREATE TRIGGER IF NOT EXISTS fatoora_no_edit"
    " BEFORE UPDATE OF source_table, source_id, doc_no, kind, subtype,"
    " uuid, icv, pih, invoice_hash, qr, xml, issue_date, issue_time,"
    " net, vat, gross, env ON fatoora_documents BEGIN"
    " SELECT RAISE(ABORT, 'مستند الفوترة الإلكترونية لا يُعدَّل بعد إصداره');"
    " END",
)


def ensure_tables(conn):
    for ddl in DDL:
        conn.execute(ddl)
    pf.ensure_tables(conn)


def _has_table(conn):
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table'"
        " AND name='fatoora_documents'").fetchone())


def enabled(conn):
    """الربط مفعّل = شهادةٌ إنتاجية + تفعيلٌ صريح من المستخدم."""
    try:
        p = pf.load(conn)
        if not p.get("enabled"):
            return False
        tok, _s, src = pf.active_credentials(p.get("env") or "simulation")
        return bool(tok) and src == "production"
    except Exception:
        return False


def doc_for(conn, source_table, source_id):
    if not _has_table(conn):
        return None
    return conn.execute(
        "SELECT * FROM fatoora_documents WHERE source_table=? AND"
        " source_id=? AND archived=0 ORDER BY icv DESC LIMIT 1",
        (source_table, source_id)).fetchone()


def guard_change(conn, source_table, source_id, action="تعديل"):
    """يمنع تعديل/حذف مستندٍ صدرت له فاتورة إلكترونية.

    الهيئة لا تقبل تغيير فاتورةٍ بعد إصدارها — والمخرج النظامي
    إشعارٌ دائن (مرتجع) يشير إليها، أو إشعارٌ مدين للزيادة.
    """
    d = doc_for(conn, source_table, source_id)
    if d is None:
        return
    raise ValueError(
        f"لا يمكن {action} {d['doc_no']}: صدرت له فاتورة إلكترونية "
        f"(ICV {d['icv']} — {STATUS_LABELS.get(d['status'], d['status'])}).\n"
        "نظام الفوترة الإلكترونية لا يسمح بتعديل الفاتورة أو حذفها بعد "
        "إصدارها؛ صحّحها بمرتجع (إشعار دائن) يشير إليها ثم أصدر فاتورةً "
        "صحيحة.")


def _chain_head(conn):
    r = conn.execute("SELECT icv, invoice_hash FROM fatoora_documents"
                     " ORDER BY icv DESC LIMIT 1").fetchone()
    return (int(r["icv"]), r["invoice_hash"]) if r else (0, ubl.FIRST_PIH)


# ══════════════════════════ من الفاتورة إلى المستند ══════════════════════════
def _seller(p):
    return {k: str(p.get(k, "") or "").strip() for k in
            ("name", "vat", "crn", "crn_scheme", "street", "building", "plot",
             "district", "city", "postal")}


def _lines(conn, invoice_id):
    from services import karat_view as kv
    out = []
    for it in conn.execute(
            "SELECT it.*, w.work_order_no, w.model_no FROM invoice_items it"
            " JOIN work_orders w ON w.id=it.work_order_id"
            " WHERE it.invoice_id=? ORDER BY it.id", (invoice_id,)):
        k = int(it["karat"] or 0) or 18
        try:
            w = kv.g(it["registered_weight"], k)      # الوزن بعيار السطر
        except Exception:
            w = it["registered_weight"]
        model = f" · موديل {it['model_no']}" if it["model_no"] else ""
        out.append({
            "name": (f"مصنعية طقم ذهب {it['work_order_no']}{model} — "
                     f"عيار {k}: {w:,.3f} جم"),
            "amount": float(it["wages"] or 0)})
    return out


def _original_refs(conn, invoice_id):
    """فواتير البيع الأصلية لأطقم المرتجع — مرجع الإشعار الدائن."""
    rows = conn.execute(
        "SELECT DISTINCT i2.invoice_no FROM invoice_items it"
        " JOIN invoice_items it2 ON it2.work_order_id=it.work_order_id"
        " JOIN invoices i2 ON i2.id=it2.invoice_id"
        " WHERE it.invoice_id=? AND i2.kind='sale' AND i2.is_deleted=0"
        "   AND i2.id < ? ORDER BY i2.id DESC",
        (invoice_id, invoice_id)).fetchall()
    return [r["invoice_no"] for r in rows][:5]


def build_doc(conn, invoice_id, prof=None):
    """مستند الفاتورة (قبل العدّاد والبصمة) — للإصدار وللمعاينة."""
    p = prof or pf.load(conn)
    inv = conn.execute("SELECT * FROM invoices WHERE id=?",
                       (invoice_id,)).fetchone()
    if not inv:
        raise ValueError("الفاتورة غير موجودة")
    b = pf.buyer(conn, inv["customer_id"]) or {}
    std = pf.buyer_is_b2b(b)
    kind = "invoice" if inv["kind"] == "sale" else "credit"
    created = str(inv["created_at"] or "")
    doc = {
        "kind": kind, "subtype": "standard" if std else "simplified",
        "number": inv["invoice_no"], "issue_date": inv["invoice_date"],
        "issue_time": created[11:19] if len(created) >= 19
        else datetime.now().strftime("%H:%M:%S"),
        "supply_date": inv["invoice_date"],
        "seller": _seller(p),
        "buyer": {"name": b.get("name", ""), "vat": b.get("vat", "")
                  if std else "", **({k: b.get(k, "") for k in
                                      pf.BUYER_FIELDS} if std else {})},
        "lines": _lines(conn, invoice_id),
        "payment_means": p.get("payment_means") or "30",
        "expect_gross": inv["grand_total"],
    }
    if kind == "credit":
        doc["billing_refs"] = _original_refs(conn, invoice_id) or \
            [f"مرتجع {inv['invoice_no']}"]
        doc["reason"] = (inv["description"] or "").strip() or \
            "إرجاع أطقم مباعة"
    return doc


def on_invoice_saved(conn, invoice_id, username=None):
    """يُنادى من حفظ الفاتورة داخل معاملتها — لا يفعل شيئاً ما لم يُفعَّل
    الربط. فاتورة بلا ضريبة أو تحويلٌ داخلي لا يُصدر لهما مستند."""
    if not enabled(conn):
        return None
    inv = conn.execute("SELECT i.*, e.entity_type FROM invoices i"
                       " JOIN entities e ON e.id=i.customer_id"
                       " WHERE i.id=?", (invoice_id,)).fetchone()
    if not inv or inv["entity_type"] == "internal" or not inv["vat_applied"]:
        return None
    ensure_tables(conn)
    return issue(conn, "invoices", invoice_id, build_doc(conn, invoice_id),
                 username)


def issue(conn, source_table, source_id, doc, username=None):
    """يُصدر المستند: عدّادٌ تالٍ · بصمة السابق · ختمٌ · حفظٌ نهائي."""
    p = pf.load(conn)
    env = p.get("env") or "simulation"
    keys = pf.load_keys(env)
    token, _secret, src = pf.active_credentials(env)
    if not (keys.get("private_key") and token):
        raise ValueError("لا توجد شهادة ربط لهذا الجهاز — افتح «الربط مع "
                         "الهيئة» وأكمل التسجيل")
    icv, pih = _chain_head(conn)
    doc = dict(doc, icv=icv + 1, pih=pih)
    errs, _w = rules.check_document(doc)
    if errs:
        raise ValueError("لا يمكن إصدار الفاتورة الإلكترونية — بيانات "
                         "ناقصة:\n• " + "\n• ".join(errs[:8]))
    key = ec.PrivateKey.from_pem(keys["private_key"])
    signed = ubl.sign_document(doc, key, api.token_certificate(token))
    t = signed["totals"]
    conn.execute(
        "INSERT INTO fatoora_documents(source_table,source_id,doc_no,kind,"
        "subtype,uuid,icv,pih,invoice_hash,qr,xml,issue_date,issue_time,"
        "net,vat,gross,env,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
        "?,?,?)",
        (source_table, source_id, doc["number"], doc["kind"], doc["subtype"],
         signed["uuid"], doc["icv"], pih, signed["hash"], signed["qr"],
         signed["xml"], doc["issue_date"], doc["issue_time"],
         float(t["net"]), float(t["vat"]), float(t["gross"]), env, username))
    if source_table in QR_TABLES:
        # الرمز المطبوع على الفاتورة يصير رمز المرحلة الثانية
        conn.execute(f"UPDATE {source_table} SET qr_base64=? WHERE id=?",
                     (signed["qr"], source_id))
    kick()
    return {"icv": doc["icv"], "uuid": signed["uuid"],
            "hash": signed["hash"], "qr": signed["qr"],
            "subtype": doc["subtype"]}


def archive_all(conn):
    """عند مسح بيانات النظام: المستندات تبقى (لا تُحذف نظاماً) وتُعلَّم
    مؤرشفة فلا تُنسب لفواتير جديدة تحمل الأرقام نفسها."""
    if _has_table(conn):
        conn.execute("UPDATE fatoora_documents SET archived=1")


# ══════════════════════════ الإرسال ══════════════════════════
def _apply_result(conn, doc_id, status, payload, error=""):
    fields = {"status": status, "response": json.dumps(payload or {},
                                                        ensure_ascii=False)[:20000],
              "last_error": error[:2000],
              "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    cleared = (payload or {}).get("clearedInvoice")
    if cleared:
        import base64
        try:
            cx = base64.b64decode(cleared).decode("utf-8")
            fields["cleared_xml"] = cx
            import re
            m = re.search(r"<cbc:ID>QR</cbc:ID>\s*<cac:Attachment>\s*"
                          r"<cbc:EmbeddedDocumentBinaryObject[^>]*>([^<]+)<",
                          cx)
            if m:
                fields["cleared_qr"] = m.group(1)
        except Exception:
            pass
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE fatoora_documents SET {sets},"
                 " attempts=attempts+1 WHERE id=?",
                 list(fields.values()) + [doc_id])
    if fields.get("cleared_qr"):
        d = conn.execute("SELECT source_table, source_id FROM"
                         " fatoora_documents WHERE id=?", (doc_id,)).fetchone()
        if d and d["source_table"] in QR_TABLES:
            conn.execute(f"UPDATE {d['source_table']} SET qr_base64=?"
                         " WHERE id=?", (fields["cleared_qr"], d["source_id"]))


def submit_one(doc_row, env):
    """يرسل مستنداً واحداً — يعيد (الحالة, الرد, الخطأ). بلا قاعدة بيانات."""
    token, secret, src = pf.active_credentials(env)
    if src != "production":
        return "error", {}, "لا توجد شهادة إنتاجية"
    try:
        st, payload = api.submit(env, token, secret, doc_row["invoice_hash"],
                                 doc_row["uuid"], doc_row["xml"],
                                 doc_row["subtype"] == "standard")
    except api.ApiError as e:
        return "error", {}, str(e)
    errs, warns = api.messages(payload)
    if st in (200, 202):
        rs = str(payload.get("clearanceStatus") or payload.get(
            "reportingStatus") or "").upper()
        if rs in ("CLEARED", "REPORTED") or st == 202:
            if warns or st == 202:
                return "warning", payload, "؛ ".join(warns)
            return ("cleared" if rs == "CLEARED" else "reported"), payload, ""
        return "rejected", payload, "؛ ".join(errs) or rs
    if st == 400:
        return "rejected", payload, "؛ ".join(errs) or "رفضت الهيئة المستند"
    if st == 409:                       # أُرسل من قبل — مقبولٌ لديها
        return "reported", payload, "مُرسلٌ سابقاً"
    if st in (401, 403):
        return "error", payload, ("رفضت الهيئة بيانات الاعتماد — جدّد "
                                  "الشهادة من «الربط مع الهيئة»")
    return "error", payload, f"ردّ غير متوقع من البوابة ({st})"


def process_queue(limit=25):
    """يرسل المستندات المعلّقة بالترتيب — الشبكة خارج أي معاملة."""
    from database.database import db
    with db(readonly=True) as conn:
        if not _has_table(conn) or not enabled(conn):
            return 0
        env = pf.load(conn).get("env") or "simulation"
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM fatoora_documents WHERE archived=0 AND env=?"
            " AND status IN ('pending','error') AND attempts < 50"
            " ORDER BY icv LIMIT ?", (env, limit))]
    done = 0
    for r in rows:
        status, payload, err = submit_one(r, env)
        with db() as conn:
            _apply_result(conn, r["id"], status, payload, err)
        done += 1
        if status == "error" and not api.LAST.get("reachable", True):
            break                        # الشبكة منقطعة — نعيد لاحقاً
    return done


# ══════════════════════════ العامل الخلفي ══════════════════════════
_wake = threading.Event()
_worker = {"thread": None}


def kick():
    _wake.set()


def start_worker(interval=60):
    """خيطٌ واحد يرسل المعلّق كل دقيقة، أو فور إصدار مستندٍ جديد."""
    t = _worker.get("thread")
    if t is not None and t.is_alive():
        return t

    def _loop():
        import time
        while True:
            _wake.wait(interval)
            _wake.clear()
            time.sleep(2)                # تُغلق معاملة الحفظ أولاً
            try:
                process_queue()
            except Exception as e:       # لا يسقط العامل أبداً
                try:
                    from services.health import log_error
                    log_error("fatoora/process_queue", e)
                except Exception:
                    pass

    t = threading.Thread(target=_loop, daemon=True, name="FatooraSender")
    t.start()
    _worker["thread"] = t
    return t


# ══════════════════════════ الملخّص ══════════════════════════
def summary(conn):
    if not _has_table(conn):
        return {"total": 0, "by_status": {}, "last_icv": 0}
    by = {r["status"]: r["n"] for r in conn.execute(
        "SELECT status, COUNT(*) n FROM fatoora_documents WHERE archived=0"
        " GROUP BY status")}
    icv, _h = _chain_head(conn)
    return {"total": sum(by.values()), "by_status": by, "last_icv": icv}
