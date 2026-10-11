# -*- coding: utf-8 -*-
"""طلبات العملاء من دليل الموديلات (4.59).

العميل يقلّب صور الموديلات ويختار: «من هذا ثلاثة، ومن ذاك اثنان».
كان ذلك يُكتب في ورقةٍ أو رسالة، فيضيع أو يُنسى أيُّ موديلٍ بأيّ عدد.
الطلب هنا سجلٌّ له رقمه (`OR-00001`)، واسم العميل، والموديلات بعددها،
وحالته (مفتوح · مُسلَّم · ملغى) — ويُطبع بصور موديلاته بالعدد الذي
يختاره المستخدم في الصفحة، كطباعة صور الدليل.

**ولا أثر محاسبي له إطلاقاً**: الطلب نيّةُ شراء لا بيع — لا قيد ولا
مخزون ولا رصيد. البيع يقع في شاشة المبيعات كالمعتاد.

**وما يلزم تصنيعه** يُحسب من الخزنة الآن: الموديل المطلوب منه خمسة
وفي الخزنة اثنان ينقصه ثلاثة — لطلبٍ واحد، وللطلبات المفتوحة كلها
مجتمعةً (خلاصة التصنيع).
"""
import datetime as _dt

from services.audit import log_action

PREFIX = "OR"
STATUSES = {"open": "مفتوح", "done": "مُسلَّم", "cancelled": "ملغى"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS model_orders(
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  order_no      TEXT    NOT NULL,
  customer_name TEXT    NOT NULL,
  entity_id     INTEGER,
  order_date    TEXT    NOT NULL,
  due_date      TEXT,
  status        TEXT    NOT NULL DEFAULT 'open',
  notes         TEXT    NOT NULL DEFAULT '',
  created_by    TEXT,
  created_at    TEXT    DEFAULT (datetime('now','localtime')),
  updated_at    TEXT,
  is_deleted    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS model_order_lines(
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id  INTEGER NOT NULL REFERENCES model_orders(id),
  model_no  TEXT    NOT NULL,
  qty       INTEGER NOT NULL DEFAULT 1,
  note      TEXT    NOT NULL DEFAULT '',
  seq       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_model_order_lines_order
  ON model_order_lines(order_id);
CREATE INDEX IF NOT EXISTS idx_model_orders_status
  ON model_orders(status, is_deleted);
"""


def ensure_schema(conn):
    for stmt in SCHEMA.split(";"):
        if stmt.strip():
            conn.execute(stmt)


def _stock(conn):
    """{الموديل: (بالخزنة، عند المناديب)} من الأطقم الآن."""
    out = {}
    for r in conn.execute(
            "SELECT TRIM(model_no) m,"
            " SUM(CASE WHEN status='in_stock' THEN 1 ELSE 0 END) i,"
            " SUM(CASE WHEN status='sold' THEN 1 ELSE 0 END) o"
            " FROM work_orders WHERE is_deleted=0 AND model_no IS NOT NULL"
            " AND TRIM(model_no)<>'' GROUP BY TRIM(model_no)"):
        out[r["m"]] = (int(r["i"] or 0), int(r["o"] or 0))
    return out


def catalog(conn):
    """كل الموديلات التي يُطلب منها: المسجّلة في الأطقم، ومعها ما له
    صورةٌ في الدليل وإن لم تُنتج منه قطعة بعد (تصميمٌ يُعرض للعميل)."""
    from models import models_catalog as mc
    stock = _stock(conn)
    imgs = mc.models_with_images(conn)
    names = set(stock)
    known_safe = {mc._safe_name(n) for n in names}
    names |= {s for s in imgs if s not in known_safe}
    out = []
    for n in names:
        i, o = stock.get(n, (0, 0))
        out.append({"model": n, "in_count": i, "out_count": o,
                    "has_image": mc._safe_name(n) in imgs})
    out.sort(key=lambda m: mc.model_key(m["model"]))
    return out


def _clean_lines(lines):
    """يدمج الموديل المكرّر ويطرح الفارغ — والترتيب كما أُدخل."""
    merged, order = {}, []
    for ln in lines or []:
        m = str((ln.get("model") if isinstance(ln, dict) else ln[0])
                or "").strip()
        if not m:
            continue
        q = int((ln.get("qty") if isinstance(ln, dict) else ln[1]) or 0)
        note = str((ln.get("note") if isinstance(ln, dict) else "") or "")
        if q <= 0:
            continue
        if m not in merged:
            merged[m] = {"model": m, "qty": 0, "note": note.strip()}
            order.append(m)
        merged[m]["qty"] += q
        if note.strip() and not merged[m]["note"]:
            merged[m]["note"] = note.strip()
    return [merged[m] for m in order]


def save_order(conn, customer_name, lines, username, order_id=None,
               entity_id=None, order_date=None, due_date=None, notes=""):
    """يحفظ الطلب (جديداً أو تعديلاً لطلبٍ قائم) ويعيد رقمه."""
    ensure_schema(conn)
    name = str(customer_name or "").strip()
    if not name:
        raise ValueError("اكتب اسم العميل")
    items = _clean_lines(lines)
    if not items:
        raise ValueError("اختر موديلاً واحداً على الأقل بعددٍ أكبر من صفر")
    date = str(order_date or _dt.date.today().isoformat())[:10]
    due = str(due_date)[:10] if due_date else None
    if order_id:
        cur = conn.execute("SELECT * FROM model_orders WHERE id=?"
                           " AND is_deleted=0", (order_id,)).fetchone()
        if not cur:
            raise ValueError("الطلب غير موجود")
        conn.execute(
            "UPDATE model_orders SET customer_name=?, entity_id=?,"
            " order_date=?, due_date=?, notes=?,"
            " updated_at=datetime('now','localtime') WHERE id=?",
            (name, entity_id, date, due, str(notes or ""), order_id))
        conn.execute("DELETE FROM model_order_lines WHERE order_id=?",
                     (order_id,))
        oid, no = int(order_id), cur["order_no"]
        action = "update"
    else:
        from models import numbering
        no = numbering.next_no(conn, PREFIX)
        oid = conn.execute(
            "INSERT INTO model_orders(order_no,customer_name,entity_id,"
            "order_date,due_date,notes,created_by) VALUES(?,?,?,?,?,?,?)",
            (no, name, entity_id, date, due, str(notes or ""),
             username)).lastrowid
        action = "create"
    for i, ln in enumerate(items):
        conn.execute(
            "INSERT INTO model_order_lines(order_id,model_no,qty,note,seq)"
            " VALUES(?,?,?,?,?)", (oid, ln["model"], ln["qty"],
                                   ln["note"], i))
    pieces = sum(ln["qty"] for ln in items)
    log_action(conn, username, action, "model_orders", oid,
               f"طلب {no} — {name}: {len(items)} موديل · {pieces} قطعة")
    return {"id": oid, "order_no": no, "models": len(items),
            "pieces": pieces}


def get_order(conn, order_id):
    """الطلب بأسطره، ومع كل موديل ما بالخزنة منه الآن وما ينقصه."""
    ensure_schema(conn)
    from models import models_catalog as mc
    o = conn.execute("SELECT * FROM model_orders WHERE id=? AND"
                     " is_deleted=0", (order_id,)).fetchone()
    if not o:
        return None
    stock = _stock(conn)
    imgs = mc.models_with_images(conn)
    lines = []
    for r in conn.execute("SELECT * FROM model_order_lines WHERE"
                          " order_id=? ORDER BY seq, id", (order_id,)):
        i, o_n = stock.get(r["model_no"], (0, 0))
        lines.append({"model": r["model_no"], "qty": int(r["qty"]),
                      "note": r["note"] or "", "in_count": i,
                      "short": max(0, int(r["qty"]) - i),
                      "has_image": mc._safe_name(r["model_no"]) in imgs})
    d = dict(o)
    d["status_label"] = STATUSES.get(d["status"], d["status"])
    d["lines"] = lines
    d["models"] = len(lines)
    d["pieces"] = sum(x["qty"] for x in lines)
    d["short"] = sum(x["short"] for x in lines)
    return d


def list_orders(conn, status="open", q=""):
    """الطلبات — الأحدث أولاً، والبحث باسم العميل أو رقم الطلب أو موديل."""
    ensure_schema(conn)
    sql = ("SELECT o.*, (SELECT COUNT(*) FROM model_order_lines l"
           "  WHERE l.order_id=o.id) n_models,"
           " (SELECT COALESCE(SUM(qty),0) FROM model_order_lines l"
           "  WHERE l.order_id=o.id) n_pieces"
           " FROM model_orders o WHERE o.is_deleted=0")
    p = []
    if status and status != "all":
        sql += " AND o.status=?"
        p.append(status)
    q = str(q or "").strip()
    if q:
        sql += (" AND (o.customer_name LIKE ? OR o.order_no LIKE ? OR"
                " EXISTS (SELECT 1 FROM model_order_lines l WHERE"
                " l.order_id=o.id AND l.model_no LIKE ?))")
        p += [f"%{q}%"] * 3
    sql += " ORDER BY o.order_date DESC, o.id DESC"
    stock = _stock(conn)
    out = []
    for r in conn.execute(sql, p).fetchall():
        d = dict(r)
        d["status_label"] = STATUSES.get(d["status"], d["status"])
        short = 0
        for ln in conn.execute("SELECT model_no, qty FROM"
                               " model_order_lines WHERE order_id=?",
                               (r["id"],)):
            short += max(0, int(ln["qty"])
                         - stock.get(ln["model_no"], (0, 0))[0])
        d["short"] = short
        out.append(d)
    return out


def count_open(conn):
    try:
        ensure_schema(conn)
        return int(conn.execute(
            "SELECT COUNT(*) n FROM model_orders WHERE is_deleted=0"
            " AND status='open'").fetchone()["n"])
    except Exception:
        return 0


def set_status(conn, order_id, status, username):
    if status not in STATUSES:
        raise ValueError("حالة غير معروفة")
    ensure_schema(conn)
    o = conn.execute("SELECT order_no FROM model_orders WHERE id=? AND"
                     " is_deleted=0", (order_id,)).fetchone()
    if not o:
        raise ValueError("الطلب غير موجود")
    conn.execute("UPDATE model_orders SET status=?,"
                 " updated_at=datetime('now','localtime') WHERE id=?",
                 (status, order_id))
    log_action(conn, username, "update", "model_orders", order_id,
               f"طلب {o['order_no']} ← {STATUSES[status]}")
    return True


def delete_order(conn, order_id, username):
    """حذفٌ منطقي — الطلب لا يظهر ويبقى أثره في سجل التتبع."""
    ensure_schema(conn)
    o = conn.execute("SELECT order_no FROM model_orders WHERE id=?",
                     (order_id,)).fetchone()
    if not o:
        raise ValueError("الطلب غير موجود")
    conn.execute("UPDATE model_orders SET is_deleted=1 WHERE id=?",
                 (order_id,))
    log_action(conn, username, "soft_delete", "model_orders", order_id,
               f"حذف الطلب {o['order_no']}")
    return True


def production(conn):
    """خلاصة التصنيع: ما تطلبه الطلبات **المفتوحة** كلها مجتمعةً من كل
    موديل، وما في الخزنة منه، وما يلزم تصنيعه — الأكثر نقصاً أولاً."""
    ensure_schema(conn)
    stock = _stock(conn)
    agg = {}
    for r in conn.execute(
            "SELECT l.model_no m, l.qty q, o.customer_name c"
            " FROM model_order_lines l JOIN model_orders o"
            " ON o.id=l.order_id WHERE o.is_deleted=0 AND o.status='open'"):
        a = agg.setdefault(r["m"], {"model": r["m"], "qty": 0,
                                    "customers": set()})
        a["qty"] += int(r["q"] or 0)
        a["customers"].add(r["c"])
    out = []
    for a in agg.values():
        i = stock.get(a["model"], (0, 0))[0]
        out.append({"model": a["model"], "qty": a["qty"],
                    "customers": sorted(a["customers"]),
                    "in_count": i, "short": max(0, a["qty"] - i)})
    from models import models_catalog as mc
    out.sort(key=lambda x: (-x["short"], mc.model_key(x["model"])))
    return out


def open_for_customer(conn, entity_id=None, name=""):
    """الطلبات المفتوحة لعميلٍ — لتنبيه شاشة المبيعات عند اختياره.

    خفيفةٌ عمداً (استعلامٌ واحد بلا صورٍ ولا خزنة): تُستدعى كلما تبدّل
    العميل في الفاتورة.
    """
    name = str(name or "").strip()
    if not entity_id and not name:
        return []
    try:
        rows = conn.execute(
            "SELECT o.id, o.order_no, o.order_date, o.due_date,"
            " (SELECT COUNT(*) FROM model_order_lines l"
            "  WHERE l.order_id=o.id) n_models,"
            " (SELECT COALESCE(SUM(qty),0) FROM model_order_lines l"
            "  WHERE l.order_id=o.id) n_pieces"
            " FROM model_orders o WHERE o.is_deleted=0 AND o.status='open'"
            " AND (o.entity_id=? OR (? <> '' AND TRIM(o.customer_name)=?))"
            " ORDER BY o.order_date, o.id",
            (entity_id or -1, name, name)).fetchall()
    except Exception:                 # قاعدةٌ لم تُرحَّل بعد
        return []
    return [dict(r) for r in rows]


def share_text(order):
    """الطلب نصّاً يُلصق في واتساب كما هو."""
    lines = [f"طلب {order['order_no']} — {order['customer_name']}",
             f"التاريخ: {order['order_date']}"
             + (f" · التسليم: {order['due_date']}"
                if order.get("due_date") else "")]
    for i, ln in enumerate(order["lines"], 1):
        lines.append(f"{i}. الموديل {ln['model']} × {ln['qty']}"
                     + (f" — {ln['note']}" if ln.get("note") else ""))
    lines.append(f"المجموع: {order['models']} موديل · "
                 f"{order['pieces']} قطعة")
    if order.get("notes"):
        lines.append(f"ملاحظات: {order['notes']}")
    return "\n".join(lines)
