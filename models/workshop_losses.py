# -*- coding: utf-8 -*-
"""تسوية فواقد الورشة — عمليات خزينة التصنيع (صرف · قبض).

**المنطق المحاسبي**: كل عمليةٍ طرفُها خزينة التصنيع، والطرف الآخر
حسابٌ يُختار (أنواع الفاقد تحت «فواقد الورشة» ويُضاف إليها):

    صرف (فاقد خرج من الخزينة):   مدين حـ/ <الحساب>   ·  دائن حـ/ خزينة التصنيع
    قبض (ذهب عاد إلى الخزينة):   مدين حـ/ خزينة التصنيع  ·  دائن حـ/ <الحساب>

فيبقى ميزان الذهب متوازناً، ويُعرف نصيب كل مرحلة تشغيلية من الفاقد
صافياً (المصروف ناقص المسترجع). ولكل عمليةٍ سندُها المطبوع (4.77).
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


KINDS = {"payment": "صرف", "receipt": "قبض"}


def ensure_schema(conn):
    for stmt in SCHEMA.split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(workshop_losses)")}
    if "kind" not in cols:
        # السندات السابقة كلها فواقد مصروفة من الخزينة
        conn.execute("ALTER TABLE workshop_losses ADD COLUMN kind TEXT"
                     " NOT NULL DEFAULT 'payment'")


def loss_types(conn):
    """أنواع الفاقد = الحسابات الفرعية تحت «فواقد الورشة»."""
    parent = conn.execute("SELECT id FROM accounts WHERE code=?",
                          (LOSSES_PARENT,)).fetchone()
    if not parent:
        return []
    return [dict(r) for r in conn.execute(
        "SELECT id, code, name FROM accounts WHERE parent_id=?"
        " AND is_postable=1 ORDER BY code", (parent["id"],))]


def accounts(conn):
    """كل حسابٍ قابلٍ للترحيل في الدليل — الطرف الآخر لعملية الخزينة
    (4.78: أي حسابٍ لا خياراتٌ محدودة). خزينة التصنيع نفسها مستثناة."""
    return [dict(r) for r in conn.execute(
        "SELECT id, code, name FROM accounts WHERE is_postable=1"
        " AND COALESCE(is_active,1)=1 AND code<>? ORDER BY code",
        (MFG_TREASURY,))]


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
    # العدّ يشمل المحذوف: لا يُعاد رقمُ سندٍ حُذف فيلتبس بغيره
    n = conn.execute("SELECT COUNT(*) c FROM workshop_losses").fetchone()["c"]
    return f"WL-{n + 1:05d}"


def create_loss(conn, account_id, weight, loss_date, username,
                description="", doc_no=None, kind="payment"):
    """يرحّل عملية خزينة التصنيع.

    `kind="payment"` صرف: مدين الحساب / دائن خزينة التصنيع (الفاقد).
    `kind="receipt"` قبض: مدين خزينة التصنيع / دائن الحساب (ما استُرجع).
    """
    ensure_schema(conn)
    if kind not in KINDS:
        raise ValueError("اختر نوع العملية: صرف أو قبض")
    w = round(float(weight or 0), 3)
    if w <= 0:
        raise ValueError("أدخل وزن الفاقد")
    acc = conn.execute(
        "SELECT id, name FROM accounts WHERE id=? AND is_postable=1",
        (account_id,)).fetchone()
    if not acc:
        raise ValueError("اختر الحساب")
    if acc["id"] == acc_id(conn, MFG_TREASURY):
        raise ValueError("الطرف الآخر لا يكون خزينة التصنيع نفسها")
    date = loss_date or _dt.date.today().isoformat()
    no = doc_no or next_doc_no(conn)
    desc = f"{KINDS[kind]} خزينة التصنيع — {acc['name']} — {w:,.2f} جم"
    if description.strip():
        desc += f" — {description.strip()}"

    cur = conn.execute(
        "INSERT INTO workshop_losses(doc_no,loss_date,account_id,weight,"
        "description,created_by,kind) VALUES(?,?,?,?,?,?,?)",
        (no, date, account_id, w, description.strip(), username, kind))
    loss_id = cur.lastrowid

    treasury = acc_id(conn, MFG_TREASURY)
    out, back = (acc["id"], treasury) if kind == "payment" else \
        (treasury, acc["id"])
    entry_id = post_entry(
        conn, date, desc,
        [{"account_id": out, "gold_debit": w, "line_desc": desc},
         {"account_id": back, "gold_credit": w, "line_desc": desc}],
        source_table="workshop_losses", source_id=loss_id,
        username=username, note=description.strip() or desc)
    conn.execute("UPDATE workshop_losses SET entry_id=? WHERE id=?",
                 (entry_id, loss_id))
    log_action(conn, username, "create", "workshop_losses", loss_id,
               f"{KINDS[kind]} خزينة التصنيع — {acc['name']}: {w:,.3f} جم")
    return {"id": loss_id, "doc_no": no, "entry_id": entry_id,
            "weight": w, "account": acc["name"], "kind": kind}


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
        "SELECT a.name, COALESCE(SUM(CASE WHEN l.kind='receipt'"
        " THEN -l.weight ELSE l.weight END),0) w"
        " FROM workshop_losses l JOIN accounts a ON a.id=l.account_id"
        " WHERE l.is_deleted=0 AND l.loss_date BETWEEN ? AND ?"
        " GROUP BY a.id ORDER BY a.code", (date_from, date_to)).fetchall()
    return [(r["name"], round(r["w"], 3)) for r in rows]


def total_weight(conn, date_from, date_to):
    ensure_schema(conn)
    r = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN kind='receipt' THEN -weight"
        " ELSE weight END),0) w FROM workshop_losses"
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
               f"حذف سند {KINDS.get(row['kind'], 'صرف')} {row['doc_no']}"
               f" — {row['acc_name']} "
               f"{row['weight']:,.3f} جم"
               + (f" | {reason}" if reason else ""))
    return {"doc_no": row["doc_no"], "weight": row["weight"],
            "account": row["acc_name"], "kind": row["kind"]}


def get_loss(conn, loss_id):
    """سند واحد بحسابه وقيده — لقالب طباعته."""
    ensure_schema(conn)
    r = conn.execute(
        "SELECT l.*, a.name acc_name, a.code acc_code"
        " FROM workshop_losses l JOIN accounts a ON a.id=l.account_id"
        " WHERE l.id=?", (loss_id,)).fetchone()
    return dict(r) if r else None


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
