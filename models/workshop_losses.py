# -*- coding: utf-8 -*-
"""تسوية فواقد الورشة.

**المنطق المحاسبي**: الفاقد خروج فعلي للذهب من خزينة التصنيع بلا
مقابل، فيُثبت مصروفاً بنوعه:

    مدين  حـ/ فاقد <النوع>        بالوزن
    دائن  حـ/ خزينة التصنيع       بالوزن نفسه

فيبقى ميزان الذهب متوازناً، ويُعرف نصيب كل مرحلة تشغيلية من الفاقد
على حدة (بوليش · صب · كاستنج · تلميع · الترا بوليش · وما يُضاف).
"""
import datetime as _dt

from models.accounts import acc_id
from services.accounting_engine import post_entry
from services.audit import log_action

LOSSES_PARENT = "5110"           # فواقد الورشة (حساب أب)
MFG_TREASURY = "1100"            # خزينة التصنيع

SCHEMA = """
CREATE TABLE IF NOT EXISTS workshop_losses(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_no TEXT,
  loss_date TEXT NOT NULL,
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  weight REAL NOT NULL,
  description TEXT DEFAULT '',
  entry_id INTEGER,
  is_deleted INTEGER NOT NULL DEFAULT 0,
  created_by TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
"""


def ensure_schema(conn):
    for stmt in SCHEMA.split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)


def loss_types(conn):
    """أنواع الفاقد = الحسابات الفرعية تحت «فواقد الورشة»."""
    parent = conn.execute("SELECT id FROM accounts WHERE code=?",
                          (LOSSES_PARENT,)).fetchone()
    if not parent:
        return []
    return [dict(r) for r in conn.execute(
        "SELECT id, code, name FROM accounts WHERE parent_id=?"
        " AND is_postable=1 ORDER BY code", (parent["id"],))]


def add_loss_type(conn, name, username):
    """ينشئ نوع فاقد جديداً بحسابه في الدليل تلقائياً."""
    name = (name or "").strip()
    if not name:
        raise ValueError("أدخل اسم نوع الفاقد")
    parent = conn.execute("SELECT id FROM accounts WHERE code=?",
                          (LOSSES_PARENT,)).fetchone()
    if not parent:
        raise ValueError("حساب «فواقد الورشة» غير موجود في الدليل")
    if conn.execute("SELECT 1 FROM accounts WHERE parent_id=? AND name=?",
                    (parent["id"], name)).fetchone():
        raise ValueError(f"نوع الفاقد «{name}» موجود مسبقاً")
    row = conn.execute(
        "SELECT MAX(CAST(code AS INTEGER)) m FROM accounts WHERE parent_id=?",
        (parent["id"],)).fetchone()
    code = str((row["m"] or int(LOSSES_PARENT)) + 1)
    cur = conn.execute(
        "INSERT INTO accounts(code,name,type,parent_id,is_postable,nature,"
        "balance_type) VALUES(?,?,'expense',?,1,'debit','gold')",
        (code, name, parent["id"]))
    log_action(conn, username, "create", "accounts", cur.lastrowid,
               f"نوع فاقد جديد: {name} ({code})")
    return {"id": cur.lastrowid, "code": code, "name": name}


def next_doc_no(conn):
    ensure_schema(conn)
    n = conn.execute("SELECT COUNT(*) c FROM workshop_losses").fetchone()["c"]
    return f"WL-{n + 1:05d}"


def create_loss(conn, account_id, weight, loss_date, username,
                description="", doc_no=None):
    """يرحّل فاقد ورشة: مدين حساب الفاقد / دائن خزينة التصنيع."""
    ensure_schema(conn)
    w = round(float(weight or 0), 3)
    if w <= 0:
        raise ValueError("أدخل وزن الفاقد")
    acc = conn.execute(
        "SELECT id, name FROM accounts WHERE id=? AND is_postable=1",
        (account_id,)).fetchone()
    if not acc:
        raise ValueError("اختر نوع الفاقد")
    date = loss_date or _dt.date.today().isoformat()
    no = doc_no or next_doc_no(conn)
    desc = f"{acc['name']} — {w:,.2f} جم"
    if description.strip():
        desc += f" — {description.strip()}"

    cur = conn.execute(
        "INSERT INTO workshop_losses(doc_no,loss_date,account_id,weight,"
        "description,created_by) VALUES(?,?,?,?,?,?)",
        (no, date, account_id, w, description.strip(), username))
    loss_id = cur.lastrowid

    entry_id = post_entry(
        conn, date, desc,
        [{"account_id": acc["id"], "gold_debit": w, "line_desc": desc},
         {"account_id": acc_id(conn, MFG_TREASURY), "gold_credit": w,
          "line_desc": desc}],
        source_table="workshop_losses", source_id=loss_id,
        username=username, note=description.strip() or desc)
    conn.execute("UPDATE workshop_losses SET entry_id=? WHERE id=?",
                 (entry_id, loss_id))
    log_action(conn, username, "create", "workshop_losses", loss_id,
               f"فاقد {acc['name']}: {w:,.3f} جم")
    return {"id": loss_id, "doc_no": no, "entry_id": entry_id,
            "weight": w, "account": acc["name"]}


def list_losses(conn, date_from=None, date_to=None):
    ensure_schema(conn)
    q = ("SELECT l.*, a.name acc_name, a.code acc_code"
         " FROM workshop_losses l JOIN accounts a ON a.id=l.account_id"
         " WHERE l.is_deleted=0")
    p = []
    if date_from:
        q += " AND l.loss_date>=?"
        p.append(date_from)
    if date_to:
        q += " AND l.loss_date<=?"
        p.append(date_to)
    return [dict(r) for r in conn.execute(q + " ORDER BY l.id DESC", p)]


def period_totals(conn, date_from, date_to):
    """إجمالي الفاقد وزناً لكل نوع خلال الفترة — للملخص الشهري."""
    ensure_schema(conn)
    rows = conn.execute(
        "SELECT a.name, COALESCE(SUM(l.weight),0) w"
        " FROM workshop_losses l JOIN accounts a ON a.id=l.account_id"
        " WHERE l.is_deleted=0 AND l.loss_date BETWEEN ? AND ?"
        " GROUP BY a.id ORDER BY a.code", (date_from, date_to)).fetchall()
    return [(r["name"], round(r["w"], 3)) for r in rows]


def total_weight(conn, date_from, date_to):
    ensure_schema(conn)
    r = conn.execute(
        "SELECT COALESCE(SUM(weight),0) w FROM workshop_losses"
        " WHERE is_deleted=0 AND loss_date BETWEEN ? AND ?",
        (date_from, date_to)).fetchone()
    return round(r["w"] or 0, 3)


def delete_loss(conn, loss_id, username, reason=""):
    """يحذف سند فاقد ويعكس أثره المحاسبي في معاملة واحدة.

    الحذف من الجدول وحده يترك القيد قائماً فيختل الميزان، والعكس بلا
    حذف يُبقي السند ظاهراً وقد رُدّ أثره. لذلك يتمّان معاً أو لا شيء.
    """
    from services.audit import reverse_entry
    ensure_schema(conn)
    row = conn.execute(
        "SELECT l.*, a.name acc_name FROM workshop_losses l"
        " JOIN accounts a ON a.id=l.account_id"
        " WHERE l.id=? AND l.is_deleted=0", (loss_id,)).fetchone()
    if not row:
        raise ValueError("السند غير موجود أو محذوف مسبقاً")

    if row["entry_id"]:
        alive = conn.execute(
            "SELECT is_deleted FROM journal_entries WHERE id=?",
            (row["entry_id"],)).fetchone()
        # نعكس القيد فقط إن كان ما يزال سارياً
        if alive and not alive["is_deleted"]:
            reverse_entry(conn, row["entry_id"], username)

    conn.execute("UPDATE workshop_losses SET is_deleted=1 WHERE id=?",
                 (loss_id,))
    log_action(conn, username, "delete", "workshop_losses", loss_id,
               f"حذف سند فاقد {row['doc_no']} — {row['acc_name']} "
               f"{row['weight']:,.3f} جم"
               + (f" | {reason}" if reason else ""))
    return {"doc_no": row["doc_no"], "weight": row["weight"],
            "account": row["acc_name"]}


def purge_orphans(conn, username="system"):
    """يُخفي السندات التي حُذف قيدها من مكان آخر.

    لو حُذف القيد من دفتر الأستاذ مباشرةً يبقى السند ظاهراً في جدول
    الفواقد بلا أثر محاسبي — وهو تضليل. هذه الدالة تُزامنهما.
    """
    ensure_schema(conn)
    rows = conn.execute(
        "SELECT l.id FROM workshop_losses l"
        " LEFT JOIN journal_entries e ON e.id=l.entry_id"
        " WHERE l.is_deleted=0"
        " AND (e.id IS NULL OR e.is_deleted=1)").fetchall()
    for r in rows:
        conn.execute("UPDATE workshop_losses SET is_deleted=1 WHERE id=?",
                     (r["id"],))
    if rows:
        log_action(conn, username, "sync", "workshop_losses", None,
                   f"إخفاء {len(rows)} سند فاقد حُذف قيده")
    return len(rows)
