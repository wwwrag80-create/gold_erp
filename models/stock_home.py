# -*- coding: utf-8 -*-
"""حساب المخزن الذي يقيم فيه الطقم — «بيته» في الدفتر.

**القاعدة المحاسبية**: الطقم أصلٌ في حسابٍ بعينه. دفعةٌ وُرّدت إلى
«الذهب المشغول» تبقى أطقمها فيه، ودفعةٌ وُرّدت إلى حسابٍ أنشأه المصنع
لبضاعةٍ خاصة تبقى أطقمها في ذلك الحساب. فإذا بِيع الطقم **خرج من
حسابه هو** لا من حسابٍ يُختار في الفاتورة؛ وإذا رُجّع **عاد إلى حسابه**.
وبهذا يطابق رصيد كل حسابٍ مخزني ما فيه من أطقم فعلاً — وهو ما تقوم
عليه المطابقة والجرد.

كان «من حساب» في الفاتورة يقرّر للفاتورة كلها، فطقمٌ وُرّد إلى حسابٍ
خاص ثم بِيع في فاتورةٍ «من الذهب المشغول» يُنقص المشغول ويبقى رصيده
في حسابه الخاص — رصيدان خاطئان من عمليةٍ واحدة.

  • `work_orders.stock_account_id` — بيت الطقم. يُكتب عند التوريد
    (حساب الوجهة)، وعند البضاعة الافتتاحية (الذهب المشغول)، وعند مرتجع
    طقمٍ جديد لم يُعرف من قبل (الحساب المختار في المرتجع).
  • فارغ ⇒ يتبع «من حساب» في الفاتورة (الرقم التجميعي، وما لم يُعرف
    بيته).
  • `invoice_items.stock_account_id` — الحساب الذي خرج منه السطر أو
    عاد إليه فعلاً. فارغ ⇒ حساب الفاتورة. يُحفظ مع السطر فلا يتغيّر
    تاريخ فاتورةٍ إن انتقل الطقم إلى بيتٍ آخر بعدها.

**سطر الأجر فقط**: أجرٌ يُحمَّل على العميل بلا طقم ولا ذهب (تلميع،
تعديل مقاس، أجرةٌ فاتت). بنود الفاتورة تُشير إلى طقمٍ دائماً، فيُشار
إلى طقمٍ خدميٍّ واحد «أجر» لا وزن له ولا حالة تتغيّر — يحرسه مُطلِق
في القاعدة فلا يصير «بالمخزون» من أي مسار.
"""
from services.audit import log_action

SERVICE_WO_NO = "أجر"


def ensure_schema(conn):
    wcols = {r["name"] for r in conn.execute("PRAGMA table_info(work_orders)")}
    if wcols and "stock_account_id" not in wcols:
        conn.execute("ALTER TABLE work_orders ADD COLUMN stock_account_id"
                     " INTEGER REFERENCES accounts(id)")
    if wcols and "is_service" not in wcols:
        conn.execute("ALTER TABLE work_orders ADD COLUMN is_service"
                     " INTEGER NOT NULL DEFAULT 0")
    icols = {r["name"] for r in conn.execute(
        "PRAGMA table_info(invoice_items)")}
    if icols and "stock_account_id" not in icols:
        conn.execute("ALTER TABLE invoice_items ADD COLUMN stock_account_id"
                     " INTEGER REFERENCES accounts(id)")
    if icols and "line_note" not in icols:
        conn.execute("ALTER TABLE invoice_items ADD COLUMN line_note"
                     " TEXT NOT NULL DEFAULT ''")
    ecols = {r["name"] for r in conn.execute("PRAGMA table_info(entities)")}
    if ecols and "direct_pay" not in ecols:
        # عاملٌ/موظفٌ يُصرف له مباشرةً بلا مسير رواتب: ما يُصرف له مصروف
        conn.execute("ALTER TABLE entities ADD COLUMN direct_pay"
                     " INTEGER NOT NULL DEFAULT 0")
    vcols = {r["name"] for r in conn.execute("PRAGMA table_info(vouchers)")}
    if vcols and "staff_expense" not in vcols:
        # سند صرفٍ لعاملٍ/موظف حُمِّل مصروفاً (models.vouchers)
        conn.execute("ALTER TABLE vouchers ADD COLUMN staff_expense"
                     " INTEGER NOT NULL DEFAULT 0")
    # الطقم الخدمي لا تتغيّر حالته من أي مسار (حذف فاتورة، تعديلها،
    # إلغاء عملية): تُتجاهل الكتابة بصمت فيبقى «مباعاً» بلا وزن.
    conn.execute(
        "CREATE TRIGGER IF NOT EXISTS trg_service_wo_status"
        " BEFORE UPDATE OF status ON work_orders"
        " WHEN OLD.is_service=1 AND NEW.status<>OLD.status"
        " BEGIN SELECT RAISE(IGNORE); END")
    if wcols:
        backfill(conn)


def _gold_ids(conn):
    from models import accounts as _a
    try:
        return {int(r["id"]) for r in _a.gold_accounts(conn)}
    except Exception:
        return set()


def backfill(conn):
    """يعيّن بيتاً لكل طقمٍ قائم لم يُعيَّن له — مرةً واحدة لكل طقم.

    آخر ما أدخله المخزن هو بيته: مرتجعٌ أعاده إلى حسابٍ (حساب ذلك
    المرتجع)، وإلا فالقيد الذي ورّده (سطره المدين). وما لا يُعرف له
    واحدٌ منهما يبقى فارغاً فيتبع حساب الفاتورة كما كان.
    """
    gold = _gold_ids(conn)
    rows = conn.execute(
        "SELECT id, entry_id FROM work_orders WHERE stock_account_id IS NULL"
        " AND is_bulk=0 AND COALESCE(is_service,0)=0").fetchall()
    n = 0
    for w in rows:
        acc = None
        r = conn.execute(
            "SELECT COALESCE(it.stock_account_id, i.source_account_id) a"
            "  FROM invoice_items it JOIN invoices i ON i.id=it.invoice_id"
            " WHERE it.work_order_id=? AND i.kind='sale_return'"
            "   AND i.is_deleted=0 ORDER BY i.invoice_date DESC, i.id DESC"
            " LIMIT 1", (w["id"],)).fetchone()
        if r and r["a"]:
            acc = int(r["a"])
        if acc is None and w["entry_id"]:
            for ln in conn.execute(
                    "SELECT account_id FROM journal_lines WHERE entry_id=?"
                    " AND COALESCE(gold_debit,0)>0 ORDER BY id",
                    (w["entry_id"],)):
                if not gold or int(ln["account_id"]) in gold:
                    acc = int(ln["account_id"])
                    break
        if acc is not None:
            conn.execute("UPDATE work_orders SET stock_account_id=?"
                         " WHERE id=?", (acc, w["id"]))
            n += 1
    return n


def home_of(wo):
    """بيت الطقم من صفّه — أو None (يتبع حساب العملية)."""
    try:
        if wo["is_bulk"]:
            return None
        v = wo["stock_account_id"]
    except (IndexError, KeyError):
        return None
    return int(v) if v else None


def home_account(conn, wo, fallback_id=None):
    """الحساب الذي يخرج منه الطقم أو يعود إليه."""
    h = home_of(wo)
    if h:
        ok = conn.execute("SELECT 1 FROM accounts WHERE id=? AND"
                          " is_active=1 AND is_postable=1",
                          (h,)).fetchone()
        if ok:
            return h
    if fallback_id:
        return int(fallback_id)
    from models.accounts import acc_id, FINISHED_GOLD
    return acc_id(conn, FINISHED_GOLD)


def bind(conn, wo_id, account_id):
    conn.execute("UPDATE work_orders SET stock_account_id=? WHERE id=?"
                 " AND is_bulk=0 AND COALESCE(is_service,0)=0",
                 (account_id, wo_id))


def service_wo(conn, username="system"):
    """الطقم الخدمي «أجر» — يُنشأ مرةً عند أول سطر أجر."""
    r = conn.execute("SELECT * FROM work_orders WHERE is_service=1"
                     " AND is_deleted=0 ORDER BY id LIMIT 1").fetchone()
    if r:
        return r
    cur = conn.execute(
        "INSERT INTO work_orders(work_order_no, gross_weight, gold_weight,"
        " registered_weight, wage_per_gram, is_bulk, status, notes,"
        " is_service, created_by) VALUES(?,0,0,0,0,0,'sold',?,1,?)",
        (SERVICE_WO_NO, "سطر أجرٍ فقط في الفواتير — بلا ذهب ولا مخزون",
         username))
    log_action(conn, username, "create", "work_orders", cur.lastrowid,
               "الطقم الخدمي لأسطر الأجر فقط")
    return conn.execute("SELECT * FROM work_orders WHERE id=?",
                        (cur.lastrowid,)).fetchone()


def is_service(wo):
    try:
        return bool(wo["is_service"])
    except (IndexError, KeyError):
        return False
