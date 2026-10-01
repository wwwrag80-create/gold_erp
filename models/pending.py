# -*- coding: utf-8 -*-
"""ما لم يكتمل بعد: الدفعات المستعجلة · والفواتير المعلّقة.

**الدفعة المستعجلة** (الوارد من التصنيع): دفعةٌ من عشرة أطقم وصل منها
طقمان واحتيج إليهما الآن. تُرحَّل الواصلة **فوراً** بقيدها المعتاد
(من حـ/ الذهب المشغول إلى حـ/ خزينة التصنيع) — فهي في المخزن فعلاً،
وتُثبت في الحسابات بوزنها. وتبقى في «المستعجل» علامةً على أن الدفعة لم
تكتمل. فإذا وصل الباقي فُتحت للاستكمال: تُضاف أطقمها ويُعدَّل القيد
نفسه **بالفرق** (لا قيدٌ عكسي ثم جديد)، ويُطبع مستندها بقيمتها الجديدة،
وتخرج من المستعجل. الجدول هنا علامةٌ على القيد لا يحمل رقماً مالياً.

**الفاتورة المعلّقة** (المبيعات والمرتجعات): فاتورةٌ بدأ إعدادها ولم
تُثبت — العميل لم يؤكّد، أو ينتظر طقماً. تُحفظ بنودها **بلا قيد ولا
أثرٍ على المخزون أو الذمم**؛ فالفاتورة لا وجود محاسبياً لها حتى تُرحَّل.
وعند فتحها تعود إلى شاشة الإصدار كما كانت، وتُثبت بالترحيل المعتاد
فتخرج من المعلّقات. والطقم في فاتورةٍ معلّقة يبقى في المخزن متاحاً:
التعليق لا يحجزه — وإن بِيع في غيرها قبل استكمالها نُبّه عند فتحها.
"""
import json

from services.audit import log_action


def ensure_schema(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS urgent_batches("
        " entry_id INTEGER PRIMARY KEY,"
        " note TEXT DEFAULT '',"
        " created_by TEXT, created_at TEXT DEFAULT"
        "  (datetime('now','localtime')),"
        " completed_at TEXT, completed_by TEXT)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS held_invoices("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " kind TEXT NOT NULL DEFAULT 'sale',"
        " customer_id INTEGER,"
        " payload TEXT NOT NULL,"
        " note TEXT DEFAULT '',"
        " created_by TEXT, created_at TEXT DEFAULT"
        "  (datetime('now','localtime')),"
        " updated_at TEXT)")


# ══════════════════════════════════════════════════════════════════
#  الدفعات المستعجلة
# ══════════════════════════════════════════════════════════════════

def mark_urgent(conn, entry_id, username, note=""):
    """يضع دفعةً مُرحَّلة في «المستعجل» (أو يعيدها إليه)."""
    ensure_schema(conn)
    e = conn.execute("SELECT id FROM journal_entries WHERE id=? AND"
                     " is_deleted=0 AND source_table='work_orders'",
                     (entry_id,)).fetchone()
    if not e:
        raise ValueError("الدفعة غير موجودة أو ليست دفعة توريد")
    conn.execute(
        "INSERT INTO urgent_batches(entry_id, note, created_by)"
        " VALUES(?,?,?) ON CONFLICT(entry_id) DO UPDATE SET"
        " completed_at=NULL, completed_by=NULL,"
        " note=COALESCE(NULLIF(excluded.note,''), note)",
        (entry_id, note or "", username))
    log_action(conn, username, "update", "journal_entries", entry_id,
               "دفعة مستعجلة — تُستكمل لاحقاً")


def complete_urgent(conn, entry_id, username):
    """يُخرج الدفعة من «المستعجل»: اكتملت."""
    ensure_schema(conn)
    n = conn.execute(
        "UPDATE urgent_batches SET completed_at=datetime('now','localtime'),"
        " completed_by=? WHERE entry_id=? AND completed_at IS NULL",
        (username, entry_id)).rowcount
    if n:
        log_action(conn, username, "update", "journal_entries", entry_id,
                   "اكتملت الدفعة المستعجلة")
    return bool(n)


def is_urgent(conn, entry_id):
    ensure_schema(conn)
    return bool(conn.execute(
        "SELECT 1 FROM urgent_batches WHERE entry_id=? AND"
        " completed_at IS NULL", (entry_id,)).fetchone())


def list_urgent(conn):
    """الدفعات المستعجلة المفتوحة — الأقدم أولاً.

    كل صف: entry_id · التاريخ · المرجع · الوجهة · عدد الأطقم · الوزن
    المقيد · أول طقم (للفتح) · منذ متى · الملاحظة.
    """
    ensure_schema(conn)
    out = []
    for r in conn.execute(
            "SELECT u.entry_id, u.note, u.created_at, e.entry_date,"
            " e.doc_no FROM urgent_batches u JOIN journal_entries e"
            " ON e.id=u.entry_id AND e.is_deleted=0"
            " WHERE u.completed_at IS NULL ORDER BY e.entry_date, u.entry_id"
            ).fetchall():
        eid = r["entry_id"]
        lines = conn.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(registered_weight),0) w"
            " FROM wo_batch_lines WHERE entry_id=?", (eid,)).fetchone()
        n, w = lines["n"], lines["w"]
        if not n:
            x = conn.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(registered_weight),0) w"
                " FROM work_orders WHERE entry_id=? AND is_deleted=0",
                (eid,)).fetchone()
            n, w = x["n"], x["w"]
        dest = conn.execute(
            "SELECT a.name FROM journal_lines l JOIN accounts a"
            " ON a.id=l.account_id WHERE l.entry_id=? AND l.gold_debit>0"
            " ORDER BY l.id LIMIT 1", (eid,)).fetchone()
        out.append({"entry_id": eid, "date": r["entry_date"],
                    "reference": r["doc_no"] or "", "note": r["note"] or "",
                    "dest": dest["name"] if dest else "",
                    "count": n, "weight": round(w or 0, 3),
                    "created_at": r["created_at"] or ""})
    return out


# ══════════════════════════════════════════════════════════════════
#  الفواتير المعلّقة
# ══════════════════════════════════════════════════════════════════

def hold_invoice(conn, state, username, note="", held_id=None):
    """يحفظ فاتورةً معلّقة — بلا قيد ولا أثر. يعيد رقمها في المعلّقات.

    `state`: وصف الشاشة كما تعيده `SalesScreen.draft_state()` (النوع
    والطرف والتاريخ والمصدر وأرقام الأطقم بأوزانها وأجورها).
    `held_id`: فاتورة معلّقة فُتحت ثم عُلّقت ثانيةً — تُحدَّث لا تتكرّر.
    """
    ensure_schema(conn)
    if not state or not state.get("items"):
        raise ValueError("لا بنود في الفاتورة — أضف طقماً قبل تعليقها")
    payload = json.dumps(state, ensure_ascii=False)
    if held_id and conn.execute("SELECT 1 FROM held_invoices WHERE id=?",
                                (held_id,)).fetchone():
        conn.execute(
            "UPDATE held_invoices SET kind=?, customer_id=?, payload=?,"
            " note=?, updated_at=datetime('now','localtime') WHERE id=?",
            (state.get("kind") or "sale", state.get("customer_id"),
             payload, note or "", held_id))
        hid = held_id
    else:
        hid = conn.execute(
            "INSERT INTO held_invoices(kind, customer_id, payload, note,"
            " created_by) VALUES(?,?,?,?,?)",
            (state.get("kind") or "sale", state.get("customer_id"),
             payload, note or "", username)).lastrowid
    log_action(conn, username, "create", "held_invoices", hid,
               f"فاتورة معلّقة ({len(state['items'])} بند) — بلا قيد")
    return hid


def get_held(conn, held_id):
    ensure_schema(conn)
    r = conn.execute("SELECT * FROM held_invoices WHERE id=?",
                     (held_id,)).fetchone()
    if not r:
        raise ValueError("الفاتورة المعلّقة غير موجودة")
    return json.loads(r["payload"])


def drop_held(conn, held_id, username=None, reason="أُثبتت"):
    """يحذف المعلّقة — بعد ترحيلها أو بإلغائها."""
    ensure_schema(conn)
    n = conn.execute("DELETE FROM held_invoices WHERE id=?",
                     (held_id,)).rowcount
    if n and username:
        log_action(conn, username, "delete", "held_invoices", held_id,
                   f"فاتورة معلّقة: {reason}")
    return bool(n)


def list_held(conn):
    """المعلّقات — الأحدث أولاً، مع ما يلزم لقراءتها دون فتحها.

    `unavailable`: أطقمٌ فيها لم تعد في المخزن (بِيعت في فاتورةٍ أخرى
    بعد التعليق) — تُنبَّه عند العرض والفتح.
    """
    ensure_schema(conn)
    out = []
    for r in conn.execute(
            "SELECT h.*, e.name cname FROM held_invoices h LEFT JOIN"
            " entities e ON e.id=h.customer_id ORDER BY h.id DESC"
            ).fetchall():
        try:
            st = json.loads(r["payload"])
        except Exception:
            st = {}
        items = st.get("items") or []
        bad = 0
        if st.get("kind", "sale") == "sale":
            for it in items:
                wo = conn.execute(
                    "SELECT status, is_deleted FROM work_orders WHERE id=?",
                    (it.get("wo_id"),)).fetchone()
                if wo is None or wo["is_deleted"] or (
                        wo["status"] or "in_stock") != "in_stock":
                    bad += 1
        out.append({
            "id": r["id"], "kind": r["kind"],
            "customer": r["cname"] or "—",
            "date": st.get("date") or "", "count": len(items),
            "weight": round(sum(float(i.get("weight") or 0)
                                for i in items), 3),
            "wages": round(sum(float(i.get("weight") or 0)
                               * float(i.get("wage") or 0)
                               for i in items), 2),
            "note": r["note"] or "", "created_by": r["created_by"] or "",
            "created_at": r["updated_at"] or r["created_at"] or "",
            "unavailable": bad})
    return out
