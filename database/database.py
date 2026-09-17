# -*- coding: utf-8 -*-
"""طبقة قاعدة البيانات: الاتصال، المخطط الكامل، ومساعد المعاملات."""
import sqlite3
import threading
from contextlib import contextmanager

import config

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  full_name TEXT DEFAULT '',
  role TEXT NOT NULL DEFAULT 'accountant' CHECK(role IN ('accountant','sales')),
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS accounts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name_locked INTEGER NOT NULL DEFAULT 0,
  code TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  account_level INTEGER NOT NULL DEFAULT 1,
  is_active INTEGER NOT NULL DEFAULT 1,
  system_tag TEXT,
  type TEXT NOT NULL CHECK(type IN ('asset','liability','equity','revenue','expense','bridge')),
  parent_id INTEGER REFERENCES accounts(id),
  is_postable INTEGER NOT NULL DEFAULT 1,
  nature TEXT NOT NULL DEFAULT 'debit' CHECK(nature IN ('debit','credit')),
  balance_type TEXT NOT NULL DEFAULT 'cash'
    CHECK(balance_type IN ('cash','gold','both'))
);

CREATE TABLE IF NOT EXISTS entities(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  phone TEXT DEFAULT '',
  vat_number TEXT DEFAULT '',
  address TEXT DEFAULT '',
  entity_type TEXT NOT NULL DEFAULT 'customer'
    CHECK(entity_type IN ('customer','supplier','partner','employee','worker','other','internal')),
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  capital_account_id INTEGER REFERENCES accounts(id),
  share_percent REAL NOT NULL DEFAULT 0,
  job_title TEXT DEFAULT '',
  basic_salary REAL NOT NULL DEFAULT 0,
  employee_id INTEGER REFERENCES employees(id),
  opening_entry_id INTEGER REFERENCES journal_entries(id),
  -- سقف الائتمان: نقداً بالريال ووزناً بمكافئ عيار 18. صفرٌ = بلا حدّ.
  credit_limit REAL NOT NULL DEFAULT 0,
  credit_limit_gold REAL NOT NULL DEFAULT 0,
  is_internal INTEGER NOT NULL DEFAULT 0,
  is_deleted INTEGER NOT NULL DEFAULT 0,
  created_by TEXT, created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS work_orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  model_no TEXT,
  work_order_no TEXT NOT NULL,
  gross_weight REAL NOT NULL,
  stones_weight REAL NOT NULL DEFAULT 0,
  gold_weight REAL NOT NULL DEFAULT 0,
  small_stones REAL NOT NULL DEFAULT 0,
  big_stones REAL NOT NULL DEFAULT 0,
  item_type TEXT DEFAULT '',
  stones_after_discount REAL NOT NULL DEFAULT 0,
  standing_gold REAL NOT NULL DEFAULT 0,
  discount_rate REAL NOT NULL DEFAULT 0.5,
  registered_weight REAL NOT NULL,
  wage_per_gram REAL NOT NULL DEFAULT 23.0,
  is_bulk INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'in_stock' CHECK(status IN ('in_stock','sold')),
  barcode_path TEXT,
  notes TEXT DEFAULT '',
  entry_id INTEGER REFERENCES journal_entries(id),
  is_deleted INTEGER NOT NULL DEFAULT 0,
  created_by TEXT, created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- منظور شجرة الحسابات بالمسميات القياسية المطلوبة (مصدر البيانات
-- الوحيد هو جدول accounts نفسه، فلا يوجد تكرار أو تعارض بين جدولين).
CREATE VIEW IF NOT EXISTS accounts_tree AS
  SELECT id              AS account_id,
         code            AS account_code,
         name            AS account_name,
         parent_id       AS parent_id,
         type            AS account_type,
         nature          AS account_nature,
         is_postable     AS is_transactional,
         account_level   AS account_level,
         CASE balance_type WHEN 'cash' THEN 'CASH_ONLY'
                           WHEN 'gold' THEN 'GOLD_ONLY'
                           ELSE 'BOTH' END AS measurement_type,
         is_active       AS is_active,
         system_tag      AS system_tag
  FROM accounts;

CREATE TABLE IF NOT EXISTS journal_entries(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_no TEXT,
  sort_key INTEGER,
  entry_date TEXT NOT NULL,
  user_note TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL,
  source_table TEXT, source_id INTEGER,
  -- سلسلة بصمات القيود: بصمة هذا القيد وبصمة سابقه (models/integrity.py)
  row_hash TEXT, prev_hash TEXT,
  is_deleted INTEGER NOT NULL DEFAULT 0,
  deleted_by TEXT, deleted_at TEXT,
  created_by TEXT, created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS journal_lines(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  gold_debit REAL NOT NULL DEFAULT 0,
  gold_credit REAL NOT NULL DEFAULT 0,
  cash_debit REAL NOT NULL DEFAULT 0,
  cash_credit REAL NOT NULL DEFAULT 0,
  line_desc TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_lines_account ON journal_lines(account_id);
CREATE INDEX IF NOT EXISTS idx_lines_entry   ON journal_lines(entry_id);


CREATE UNIQUE INDEX IF NOT EXISTS ux_work_orders_no_live
  ON work_orders(work_order_no) WHERE is_deleted=0;

CREATE TABLE IF NOT EXISTS invoices(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_no TEXT UNIQUE,
  kind TEXT NOT NULL CHECK(kind IN ('sale','sale_return')),
  customer_id INTEGER NOT NULL REFERENCES entities(id),
  invoice_date TEXT NOT NULL,
  wage_per_gram REAL NOT NULL,
  total_weight REAL NOT NULL,
  total_wages REAL NOT NULL,
  vat_amount REAL NOT NULL,
  grand_total REAL NOT NULL,
  qr_base64 TEXT DEFAULT '',
  -- رمز صفحة الفاتورة للجوال ورابطها المنشور (services/invoice_share.py).
  -- `qr_enabled` قرارٌ لكل فاتورة على حدة يتخذه المستخدم في شاشة
  -- المبيعات: لا يُنشأ رمز ولا يُرفع شيء لفاتورة لم تُفعَّل.
  share_token TEXT, share_url TEXT,
  qr_enabled INTEGER NOT NULL DEFAULT 0,
  vat_applied INTEGER NOT NULL DEFAULT 1,
  description TEXT DEFAULT '',
  entry_id INTEGER REFERENCES journal_entries(id),
  is_deleted INTEGER NOT NULL DEFAULT 0,
  created_by TEXT, created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS invoice_items(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
  work_order_id INTEGER NOT NULL REFERENCES work_orders(id),
  registered_weight REAL NOT NULL,
  wage_per_gram REAL NOT NULL DEFAULT 0,
  wages REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tax_debit_notes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  note_no TEXT UNIQUE,
  invoice_id INTEGER REFERENCES invoices(id),
  note_date TEXT NOT NULL,
  base_amount REAL NOT NULL DEFAULT 0,
  vat_amount REAL NOT NULL,
  entry_id INTEGER REFERENCES journal_entries(id),
  is_deleted INTEGER NOT NULL DEFAULT 0,
  created_by TEXT, created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS voucher_lines(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  voucher_id INTEGER NOT NULL REFERENCES vouchers(id) ON DELETE CASCADE,
  line_kind TEXT NOT NULL CHECK(line_kind IN ('gold','cash')),
  gold_weight REAL NOT NULL DEFAULT 0,
  gold_karat INTEGER NOT NULL DEFAULT 18,
  gold_equiv18 REAL NOT NULL DEFAULT 0,
  cash_amount REAL NOT NULL DEFAULT 0,
  line_notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS vouchers(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  voucher_no TEXT UNIQUE,
  kind TEXT NOT NULL CHECK(kind IN ('receipt','payment')),
  customer_id INTEGER REFERENCES entities(id),
  target_account_id INTEGER NOT NULL REFERENCES accounts(id),
  voucher_date TEXT NOT NULL,
  gold_weight REAL NOT NULL DEFAULT 0,
  gold_karat INTEGER NOT NULL DEFAULT 18,
  gold_equiv18 REAL NOT NULL DEFAULT 0,
  cash_amount REAL NOT NULL DEFAULT 0,
  cash_account_code TEXT DEFAULT '1400',
  net_diff REAL NOT NULL DEFAULT 0,
  disc_cash REAL NOT NULL DEFAULT 0,
  disc_gold REAL NOT NULL DEFAULT 0,
  notes TEXT DEFAULT '',
  entry_id INTEGER REFERENCES journal_entries(id),
  is_deleted INTEGER NOT NULL DEFAULT 0,
  created_by TEXT, created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS melting_ops(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  op_no TEXT UNIQUE,
  kind TEXT NOT NULL DEFAULT 'disbursement'
    CHECK(kind IN ('disbursement','receipt','close','legacy')),
  equiv18 REAL NOT NULL DEFAULT 0,
  op_date TEXT NOT NULL,
  w18 REAL NOT NULL DEFAULT 0,
  w21 REAL NOT NULL DEFAULT 0,
  expected24 REAL NOT NULL,
  actual24 REAL NOT NULL,
  loss24 REAL NOT NULL,
  loss_ratio REAL NOT NULL,
  exceeded INTEGER NOT NULL DEFAULT 0,
  notes TEXT DEFAULT '',
  entry_id INTEGER REFERENCES journal_entries(id),
  is_deleted INTEGER NOT NULL DEFAULT 0,
  created_by TEXT, created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS melting_lines(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  op_id INTEGER NOT NULL REFERENCES melting_ops(id),
  karat INTEGER NOT NULL CHECK(karat IN (18,21,24)),
  weight REAL NOT NULL,
  equiv18 REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS fixing_ops(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  op_no TEXT UNIQUE,
  op_date TEXT NOT NULL,
  customer_id INTEGER NOT NULL REFERENCES entities(id),
  weight REAL NOT NULL,
  price REAL NOT NULL,
  amount REAL NOT NULL,
  entry_id INTEGER REFERENCES journal_entries(id),
  is_deleted INTEGER NOT NULL DEFAULT 0,
  created_by TEXT, created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS fixed_assets(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  purchase_date TEXT NOT NULL,
  cost REAL NOT NULL,
  is_deleted INTEGER NOT NULL DEFAULT 0,
  created_by TEXT, created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS purchases(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  purchase_no TEXT UNIQUE,
  purchase_date TEXT NOT NULL,
  supplier TEXT DEFAULT '',
  supplier_id INTEGER REFERENCES entities(id),
  kind TEXT NOT NULL CHECK(kind IN ('expense','asset')),
  description TEXT NOT NULL,
  amount REAL NOT NULL,
  vat_amount REAL NOT NULL DEFAULT 0,
  total REAL NOT NULL,
  pay_account_code TEXT NOT NULL DEFAULT '1400',
  asset_id INTEGER REFERENCES fixed_assets(id),
  entry_id INTEGER REFERENCES journal_entries(id),
  is_deleted INTEGER NOT NULL DEFAULT 0,
  created_by TEXT, created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS scrap_moves(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  karat INTEGER NOT NULL,
  actual_delta REAL NOT NULL,
  ref_table TEXT, ref_id INTEGER,
  is_deleted INTEGER NOT NULL DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS employees(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  staff_kind TEXT DEFAULT 'employee',
  basic_salary REAL NOT NULL DEFAULT 0,
  is_active INTEGER NOT NULL DEFAULT 1,
  is_deleted INTEGER NOT NULL DEFAULT 0,
  created_by TEXT, created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS payroll_ledger(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  employee_id INTEGER NOT NULL REFERENCES employees(id),
  period TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('accrual','advance','payment')),
  amount REAL NOT NULL,
  advance_deducted REAL NOT NULL DEFAULT 0,
  entry_id INTEGER REFERENCES journal_entries(id),
  notes TEXT DEFAULT '',
  is_deleted INTEGER NOT NULL DEFAULT 0,
  created_by TEXT, created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS shrinkage_ops(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  op_no TEXT UNIQUE,
  op_date TEXT NOT NULL,
  period TEXT DEFAULT '',
  weight REAL NOT NULL,
  notes TEXT DEFAULT '',
  entry_id INTEGER REFERENCES journal_entries(id),
  is_deleted INTEGER NOT NULL DEFAULT 0,
  created_by TEXT, created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS stocktakes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stocktake_no TEXT UNIQUE,
  mode TEXT NOT NULL CHECK(mode IN ('bulk','itemized')),
  account_id INTEGER REFERENCES accounts(id),
  stocktake_date TEXT NOT NULL,
  ledger_value REAL NOT NULL DEFAULT 0,
  actual_value REAL NOT NULL DEFAULT 0,
  diff REAL NOT NULL DEFAULT 0,
  matched_count INTEGER NOT NULL DEFAULT 0,
  missing_count INTEGER NOT NULL DEFAULT 0,
  excess_count INTEGER NOT NULL DEFAULT 0,
  notes TEXT DEFAULT '',
  entry_id INTEGER REFERENCES journal_entries(id),
  is_deleted INTEGER NOT NULL DEFAULT 0,
  created_by TEXT, created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS stocktake_lines(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stocktake_id INTEGER NOT NULL REFERENCES stocktakes(id) ON DELETE CASCADE,
  work_order_id INTEGER REFERENCES work_orders(id),
  work_order_no TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('matched','missing','excess')),
  registered_weight REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_stocktake_lines_st ON stocktake_lines(stocktake_id);

CREATE TABLE IF NOT EXISTS sync_queue(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id TEXT NOT NULL,
  op_uuid TEXT NOT NULL UNIQUE,
  entity TEXT NOT NULL,
  payload TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
         CHECK(status IN ('pending','sent','failed')),
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now','localtime')),
  sent_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_sync_status ON sync_queue(status, id);

-- سطور دفعة التوريد: حصة كل طقم في الدفعة كما أُدخلت.
-- الرقم التجميعي 0001 سجل تراكمي واحد، فقراءة وزنه من work_orders
-- عند التعديل تُظهر الرصيد الكلي لا ما أُدخل في هذه الدفعة — وهو
-- خطأ يُفسد التعديل. هذا الجدول يحفظ الحصة الأصلية لكل سطر.
CREATE TABLE IF NOT EXISTS wo_batch_lines(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id INTEGER NOT NULL REFERENCES journal_entries(id),
  work_order_id INTEGER REFERENCES work_orders(id),
  model_no TEXT,
  wo_no TEXT NOT NULL,
  gold REAL NOT NULL DEFAULT 0,
  small_stones REAL NOT NULL DEFAULT 0,
  big_stones REAL NOT NULL DEFAULT 0,
  discount_rate REAL NOT NULL DEFAULT 0.5,
  registered_weight REAL NOT NULL DEFAULT 0,
  wage_per_gram REAL NOT NULL DEFAULT 0,
  notes TEXT DEFAULT '',
  seq INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_wbl_entry ON wo_batch_lines(entry_id);

-- فهارس الأداء: كشوف الحسابات والتقارير تُرشّح بالتاريخ والحساب معاً،
-- وبدونها يُمسح جدول القيود كاملاً في كل استعلام.
CREATE INDEX IF NOT EXISTS idx_entries_date   ON journal_entries(entry_date);
CREATE INDEX IF NOT EXISTS idx_entries_live   ON journal_entries(is_deleted, entry_date);
CREATE INDEX IF NOT EXISTS idx_entries_src    ON journal_entries(source_table, source_id);
CREATE INDEX IF NOT EXISTS idx_lines_acc_ent  ON journal_lines(account_id, entry_id);
CREATE INDEX IF NOT EXISTS idx_inv_cust       ON invoices(customer_id, invoice_date);
CREATE INDEX IF NOT EXISTS idx_inv_live       ON invoices(is_deleted, kind);
CREATE INDEX IF NOT EXISTS idx_items_inv      ON invoice_items(invoice_id);
CREATE INDEX IF NOT EXISTS idx_items_wo       ON invoice_items(work_order_id);
CREATE INDEX IF NOT EXISTS idx_vch_cust       ON vouchers(customer_id, voucher_date);
CREATE INDEX IF NOT EXISTS idx_wo_status      ON work_orders(status, is_deleted);
CREATE INDEX IF NOT EXISTS idx_wo_no          ON work_orders(work_order_no);
CREATE INDEX IF NOT EXISTS idx_acc_parent     ON accounts(parent_id);
CREATE INDEX IF NOT EXISTS idx_ent_type       ON entities(entity_type, is_deleted);

-- إعدادات عامة (مفتاح/قيمة): تاريخ قفل الفترات وغيره.
CREATE TABLE IF NOT EXISTS app_settings(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL DEFAULT '',
  updated_by TEXT,
  updated_at TEXT DEFAULT (datetime('now','localtime'))
);

-- أي صورة يستعملها أي فاتورة منشورة — لمعرفة الصور التي لم تعد
-- مستعملة فتُحذف من التخزين (services/invoice_share.py)
CREATE TABLE IF NOT EXISTS invoice_assets(
  invoice_id INTEGER NOT NULL,
  sha TEXT NOT NULL,
  PRIMARY KEY(invoice_id, sha)
);

-- مسوّدات شاشات الإدخال: ما أُدخل ولم يُرحَّل بعد (services/drafts.py).
-- ليست قيداً ولا تمسّ رقماً محاسبياً — نصٌّ يصف ما كان في الشاشة.
CREATE TABLE IF NOT EXISTS screen_drafts(
  screen TEXT NOT NULL,
  username TEXT NOT NULL DEFAULT '',
  payload TEXT NOT NULL DEFAULT '',
  updated_at TEXT DEFAULT (datetime('now','localtime')),
  PRIMARY KEY(screen, username)
);

-- سجل ما رُفع للتخزين السحابي — المفتاح بصمة محتوى الصورة، فتُرفع
-- كل صورة مرة واحدة مهما تكرّرت في الفواتير (services/invoice_share.py)
CREATE TABLE IF NOT EXISTS cloud_assets(
  sha TEXT PRIMARY KEY,
  url TEXT NOT NULL,
  size_bytes INTEGER NOT NULL DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT,
  action TEXT NOT NULL,
  table_name TEXT,
  record_id INTEGER,
  details TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
"""


def get_connection() -> sqlite3.Connection:
    """اتصال بمعاملات صريحة بالكامل.

    `isolation_level=None` يوقف الإدارة الضمنية للمعاملات في مكتبة
    sqlite3 (التي كانت تفتح وتغلق المعاملات تلقائياً ويمكن أن تُثبّت
    نصف عملية عند حدوث خطأ صامت). بدلاً منها نفتح المعاملة بأنفسنا
    بـ BEGIN IMMEDIATE ونغلقها بـ COMMIT أو ROLLBACK صراحةً.
    """
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.DB_PATH), timeout=30.0,
                           isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")     # قراءة أثناء الكتابة
    conn.execute("PRAGMA synchronous = FULL;")     # لا فقد عند انقطاع
    conn.execute("PRAGMA busy_timeout = 30000;")   # انتظار القفل بدل الفشل
    # ذاكرة مؤقتة أكبر وجداول مؤقتة في الذاكرة: التقارير الكبيرة
    # (الميزان والأستاذ العام) تُبنى دون قراءة القرص مراراً.
    conn.execute("PRAGMA cache_size = -20000;")    # ‎~20 ميجابايت
    conn.execute("PRAGMA temp_store = MEMORY;")
    return conn


# ══════════════════════════════════════════════════════════════════
#  اتصال واحد لكل خيط + معاملة قابلة للتداخل
# ══════════════════════════════════════════════════════════════════
#  كان كل استدعاء لـ db() يفتح ملف القاعدة من جديد ويعيد ضبط خمس
#  PRAGMA ثم يغلقه. وشاشة واحدة قد تستدعيه عشرات المرات عند كل
#  تحديث — فيظهر «تأخير» لا سبب له. الاتصال المحفوظ لكل خيط يلغي
#  هذا العبء كاملاً، ويبقى كل خيط معزولاً عن الآخر تماماً.
_local = threading.local()


def _state():
    st = getattr(_local, "st", None)
    if st is None:
        st = _local.st = {"conn": None, "depth": 0, "readonly": False,
                          "path": None}
    return st


def _thread_conn():
    """اتصال هذا الخيط بالقاعدة **النشطة حالياً**.

    مسار القاعدة ليس ثابتاً: `config.DB_PATH` يُحسب من هوية المصنع
    التي يضبطها تسجيل الدخول. والإقلاع يهيّئ الجداول قبل الدخول على
    الملف الافتراضي، فلو احتفظ الخيط باتصاله الأول لظلّ يقرأ ويكتب
    في الملف القديم بعد الدخول — فيعمل النظام كله على قاعدة غير
    قاعدة المصنع بلا أي رسالة خطأ.

    لذلك نقارن المسار المحفوظ بالمسار المطلوب عند كل فتح معاملة،
    ونجدّد الاتصال إن تغيّر. (لا يُستدعى إلا خارج أي معاملة، فلا
    يُستبدل اتصال وسط عملية.)
    """
    st = _state()
    try:
        want = str(config.DB_PATH)
    except Exception:
        want = st["path"]
    if st["conn"] is not None and st["path"] != want:
        _drop_thread_conn()
    if st["conn"] is None:
        st["conn"] = get_connection()
        st["path"] = want
    return st["conn"]


def _drop_thread_conn():
    """يتخلّص من اتصال صار في حالة غير معروفة بعد خطأ."""
    st = _state()
    conn, st["conn"], st["path"] = st["conn"], None, None
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


def close_thread_connection():
    """يغلق اتصال الخيط الحالي — يُستدعى عند إنهاء خيط طويل العمر."""
    _drop_thread_conn()


@contextmanager
def db(readonly: bool = False):
    """**معاملة ذرّية صارمة**: BEGIN … COMMIT / ROLLBACK.

    أي استثناء داخل الكتلة يُلغي **كل** ما كُتب فيها (القيود والمخزون
    وحركة الطقم والفواتير معاً) ثم يُعاد رفعه لتظهر رسالة الخطأ
    للمستخدم — فلا تُحفظ نصف عملية أبداً.

    `readonly=True` يفتح المعاملة بـ BEGIN DEFERRED فلا تحجز قفل
    الكتابة. القراءة الخالصة (التقارير والمراقبة الخلفية) كانت تحجز
    القفل بلا داعٍ فتُجمّد حفظ الفواتير طوال مدة الاستعلام.

    الاستدعاء المتداخل داخل معاملة قائمة **ينضم إليها** بدل فتح
    اتصال ثانٍ يتنازع مع الأول على القفل حتى ينتهي وقت الانتظار.
    """
    st = _state()
    if st["depth"] > 0:                    # متداخلة: انضم للمعاملة القائمة
        if st["readonly"] and not readonly:
            raise RuntimeError(
                "محاولة كتابة داخل معاملة قراءة — أُلغيت العملية")
        st["depth"] += 1
        try:
            yield st["conn"]
        finally:
            st["depth"] -= 1
        return

    begin = "BEGIN DEFERRED" if readonly else "BEGIN IMMEDIATE"
    conn = _thread_conn()
    try:
        conn.execute(begin)
    except sqlite3.Error:
        # الاتصال المحفوظ تعطّل (ملف استُبدل أو معاملة عالقة): نجدّده
        _drop_thread_conn()
        conn = _thread_conn()
        conn.execute(begin)
    st["depth"], st["readonly"] = 1, readonly
    try:
        yield conn
        # ══ ختم القيود قبل الإغلاق ══
        # آخر لحظةٍ يكون فيها القيد قد بلغ صورته النهائية: ما وُسم في
        # هذه المعاملة يُختم الآن في سلسلة البصمات (models/integrity).
        # داخل المعاملة نفسها فالقيد وبصمته يُثبَّتان معاً أو لا
        # يُثبَّتان. وفشل الختم لا يُلغي عملاً سليماً — السلسلة أداة
        # كشفٍ لا شرطَ صحةٍ محاسبية، وقيدٌ غير مختوم يظهر في شاشة
        # «سلامة السجل» ليُختم هناك.
        if not readonly:
            try:
                from models import integrity
                integrity.seal_pending(conn)
            except Exception:
                pass
        conn.execute("COMMIT")
    except BaseException:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            _drop_thread_conn()          # لا نُبقي اتصالاً مشكوكاً فيه
        raise
    finally:
        st["depth"], st["readonly"] = 0, False


def db_read():
    """معاملة قراءة فقط — لا تحجز قفل الكتابة."""
    return db(readonly=True)


def create_tables() -> None:
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)      # executescript يُثبّت بنفسه
    finally:
        conn.close()


def migrate_schema() -> None:
    """ترقية قواعد البيانات القائمة دون فقد بيانات (إضافة أعمدة/جداول جديدة)."""
    with db() as conn:
        # 1) invoices.vat_applied [ترقية سابقة]
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(invoices)")]
        if cols and "vat_applied" not in cols:
            conn.execute("ALTER TABLE invoices ADD COLUMN vat_applied"
                         " INTEGER NOT NULL DEFAULT 1")

        # 2) work_orders.entry_id [ترقية سابقة]
        wo_cols = [r["name"] for r in conn.execute("PRAGMA table_info(work_orders)")]
        if wo_cols and "entry_id" not in wo_cols:
            conn.execute("ALTER TABLE work_orders ADD COLUMN entry_id"
                         " INTEGER REFERENCES journal_entries(id)")

        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}

        # 3) customers → entities: إعادة تسمية + تعميم لجهات تعامل متعددة
        #    (عميل/مورد/شريك/داخلي). SQLite يحدّث تلقائياً كل مراجع FK في
        #    الجداول الأخرى (invoices, vouchers, fixing_ops) عند إعادة التسمية.
        if "customers" in tables and "entities" not in tables:
            cust_cols = [r["name"] for r in conn.execute("PRAGMA table_info(customers)")]
            if "is_internal" not in cust_cols:
                conn.execute("ALTER TABLE customers ADD COLUMN is_internal"
                             " INTEGER NOT NULL DEFAULT 0")
            conn.execute("ALTER TABLE customers RENAME TO entities")
            tables.discard("customers")
            tables.add("entities")

        if "entities" in tables:
            ent_cols = [r["name"] for r in conn.execute("PRAGMA table_info(entities)")]
            if "is_internal" not in ent_cols:
                conn.execute("ALTER TABLE entities ADD COLUMN is_internal"
                             " INTEGER NOT NULL DEFAULT 0")
                ent_cols.append("is_internal")
            if "entity_type" not in ent_cols:
                conn.execute("ALTER TABLE entities ADD COLUMN entity_type"
                             " TEXT NOT NULL DEFAULT 'customer'")
                conn.execute("UPDATE entities SET entity_type='internal'"
                             " WHERE is_internal=1")
                ent_cols.append("entity_type")
            if "capital_account_id" not in ent_cols:
                conn.execute("ALTER TABLE entities ADD COLUMN capital_account_id"
                             " INTEGER REFERENCES accounts(id)")

        # 4) vouchers: توجيه شامل — دعم (جهة تعامل) أو (حساب مباشر من
        #    الشجرة) بدل الاقتصار على عميل. يتطلب إعادة بناء الجدول لتخفيف
        #    قيد NOT NULL عن customer_id وإضافة target_account_id.
        if "vouchers" in tables:
            v_cols = [r["name"] for r in conn.execute("PRAGMA table_info(vouchers)")]
            # الشرط الدقيق: جدول سندات بالصيغة القديمة فعلاً (به customer_id
            # ولا يحوي التوجيه الجديد) — وإلا يُترك كما هو. وأي فشل غير
            # متوقع لا يجوز أن يمنع إقلاع النظام.
            if ("target_account_id" not in v_cols and "customer_id" in v_cols
                    and "entities" in tables):
                conn.execute("ALTER TABLE vouchers RENAME TO vouchers_old")
                conn.execute("""
                    CREATE TABLE vouchers(
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      voucher_no TEXT UNIQUE,
                      kind TEXT NOT NULL CHECK(kind IN ('receipt','payment')),
                      customer_id INTEGER REFERENCES entities(id),
                      target_account_id INTEGER NOT NULL REFERENCES accounts(id),
                      voucher_date TEXT NOT NULL,
                      gold_weight REAL NOT NULL DEFAULT 0,
                      gold_karat INTEGER NOT NULL DEFAULT 18,
                      gold_equiv18 REAL NOT NULL DEFAULT 0,
                      cash_amount REAL NOT NULL DEFAULT 0,
                      cash_account_code TEXT DEFAULT '1400',
                      net_diff REAL NOT NULL DEFAULT 0,
                      disc_cash REAL NOT NULL DEFAULT 0,
                      disc_gold REAL NOT NULL DEFAULT 0,
                      notes TEXT DEFAULT '',
                      entry_id INTEGER REFERENCES journal_entries(id),
                      is_deleted INTEGER NOT NULL DEFAULT 0,
                      created_by TEXT, created_at TEXT DEFAULT (datetime('now','localtime'))
                    )""")
                conn.execute("""
                    INSERT INTO vouchers(id,voucher_no,kind,customer_id,
                      target_account_id,voucher_date,gold_weight,gold_karat,
                      gold_equiv18,cash_amount,cash_account_code,net_diff,
                      disc_cash,disc_gold,notes,entry_id,is_deleted,created_by,
                      created_at)
                    SELECT o.id,o.voucher_no,o.kind,o.customer_id,e.account_id,
                      o.voucher_date,o.gold_weight,o.gold_karat,o.gold_equiv18,
                      o.cash_amount,o.cash_account_code,o.net_diff,o.disc_cash,
                      o.disc_gold,o.notes,o.entry_id,o.is_deleted,o.created_by,
                      o.created_at
                    FROM vouchers_old o JOIN entities e ON e.id=o.customer_id
                """)
                conn.execute("DROP TABLE vouchers_old")
            elif "target_account_id" not in v_cols and "entity_id" in v_cols:
                pass          # صيغة حديثة بأعمدة مختصرة — لا تحويل مطلوب

        # 5) purchases: مورد كجهة تعامل مهيكلة (المشتريات آجلة إلزامياً)
        p_cols = [r["name"] for r in conn.execute("PRAGMA table_info(purchases)")]
        if p_cols and "supplier_id" not in p_cols:
            conn.execute("ALTER TABLE purchases ADD COLUMN supplier_id"
                         " INTEGER REFERENCES entities(id)")

        # 6) accounts: طبيعة الحساب (مدين/دائن) ونوع الرصيد المقبول
        a_cols = [r["name"] for r in conn.execute("PRAGMA table_info(accounts)")]
        if a_cols and "nature" not in a_cols:
            conn.execute("ALTER TABLE accounts ADD COLUMN nature TEXT NOT NULL"
                         " DEFAULT 'debit'")
            conn.execute("UPDATE accounts SET nature='credit'"
                         " WHERE type IN ('liability','equity','revenue')")
        if a_cols and "balance_type" not in a_cols:
            conn.execute("ALTER TABLE accounts ADD COLUMN balance_type TEXT"
                         " NOT NULL DEFAULT 'cash'")
            # الحسابات الوزنية والمزدوجة المعروفة بالكود (البقية نقدية)
            conn.execute("UPDATE accounts SET balance_type='gold' WHERE code IN"
                         " ('1100','1150','1200','1300','1310','1320','1330',"
                         "'5100','5110','5120','5130','5300')")
            conn.execute("UPDATE accounts SET balance_type='both' WHERE code IN"
                         " ('1600','3100','3110','3120','6000','6100')"
                         " OR parent_id IN (SELECT id FROM accounts WHERE"
                         " code IN ('1600','3110','3120'))"
                         " OR code LIKE '16%' OR code LIKE '311%'"
                         " OR code LIKE '312%'")
            conn.execute("UPDATE accounts SET balance_type='cash' WHERE code IN"
                         " ('1950','2300') OR parent_id IN (SELECT id FROM"
                         " accounts WHERE code IN ('1950','2300'))"
                         " OR code LIKE '195%' OR code LIKE '23%'")

        # 6b) work_orders: تفكيك الأوزان (ذهب/فصوص/أحجار/بعد الخصم/قائم)
        wcols = [r["name"] for r in conn.execute("PRAGMA table_info(work_orders)")]
        if wcols and "wage_per_gram" not in wcols:
            conn.execute("ALTER TABLE work_orders ADD COLUMN wage_per_gram"
                         " REAL NOT NULL DEFAULT 23.0")
        if wcols and "is_bulk" not in wcols:
            conn.execute("ALTER TABLE work_orders ADD COLUMN is_bulk"
                         " INTEGER NOT NULL DEFAULT 0")
        if wcols and "gold_weight" not in wcols:
            for col in ("gold_weight", "small_stones", "big_stones",
                       "stones_after_discount", "standing_gold"):
                conn.execute(f"ALTER TABLE work_orders ADD COLUMN {col}"
                             " REAL NOT NULL DEFAULT 0")
            # ترحيل البيانات القديمة: الإجمالي كان يشمل الأحجار
            conn.execute(
                "UPDATE work_orders SET gold_weight=gross_weight-stones_weight,"
                " big_stones=stones_weight, small_stones=0,"
                " stones_after_discount=registered_weight-(gross_weight-stones_weight),"
                " standing_gold=gross_weight")

        # 6c) إلغاء مراكز التكلفة نهائياً من كل الجداول
        for tbl in ("journal_lines", "employees", "entities", "melting_ops",
                   "shrinkage_ops", "purchases", "fixed_assets"):
            try:
                cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({tbl})")]
                if "cost_center_id" in cols:
                    conn.execute(f"ALTER TABLE {tbl} DROP COLUMN cost_center_id")
            except Exception:
                pass          # جدول غير موجود في هذه النسخة — يُتجاهل بأمان
        try:
            conn.execute("DROP TABLE IF EXISTS cost_centers")
        except Exception:
            pass

        # 6d) invoices.description + invoice_items.wage_per_gram + tax_debit_notes
        icols = [r["name"] for r in conn.execute("PRAGMA table_info(invoices)")]
        if icols and "description" not in icols:
            conn.execute("ALTER TABLE invoices ADD COLUMN description"
                         " TEXT DEFAULT ''")
        iicols = [r["name"] for r in conn.execute("PRAGMA table_info(invoice_items)")]
        if iicols and "wage_per_gram" not in iicols:
            conn.execute("ALTER TABLE invoice_items ADD COLUMN wage_per_gram"
                         " REAL NOT NULL DEFAULT 0")
            # يُشتق رجعياً من الأجور والوزن المسجَّلين للسطر إن أمكن
            conn.execute(
                "UPDATE invoice_items SET wage_per_gram="
                " CASE WHEN registered_weight>0 THEN"
                " ROUND(wages/registered_weight, 2) ELSE 0 END")

        # 6e) إلغاء الإهلاك: إسقاط جدول قيود الإهلاك إن كان فارغاً،
        #     وإسقاط حقلي القيمة التخريدية والعمر الإنتاجي دائماً.
        try:
            has_dep = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
                " AND name='depreciation_runs'").fetchone()
            if has_dep:
                n = conn.execute("SELECT COUNT(*) c FROM depreciation_runs"
                                 " WHERE is_deleted=0").fetchone()["c"]
                if not n:          # لا تاريخ إهلاك — يُسقط الجدول بأمان
                    conn.execute("DROP TABLE depreciation_runs")
        except Exception:
            pass                   # يوجد تاريخ إهلاك سابق — يُحتفظ به للرقابة
        try:
            acols = [r["name"] for r in conn.execute("PRAGMA table_info(fixed_assets)")]
            for col in ("salvage", "life_years"):
                if col in acols:
                    conn.execute(f"ALTER TABLE fixed_assets DROP COLUMN {col}")
        except Exception:
            pass

        # 6f) تفرّد رقم التشغيل يسري على الأرقام الحية فقط، حتى يمكن
        #     إعادة استخدام رقم أُلغي منطقياً عند تعديل دفعة توريد.
        wsql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table'"
            " AND name='work_orders'").fetchone()
        if wsql and "work_order_no TEXT UNIQUE" in (wsql["sql"] or ""):
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(work_orders)")]
            names = ",".join(cols)
            conn.execute("ALTER TABLE work_orders RENAME TO work_orders_old")
            conn.execute(f"""
                CREATE TABLE work_orders(
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  work_order_no TEXT NOT NULL,
                  gross_weight REAL NOT NULL,
                  stones_weight REAL NOT NULL DEFAULT 0,
                  gold_weight REAL NOT NULL DEFAULT 0,
                  small_stones REAL NOT NULL DEFAULT 0,
                  big_stones REAL NOT NULL DEFAULT 0,
                  stones_after_discount REAL NOT NULL DEFAULT 0,
                  standing_gold REAL NOT NULL DEFAULT 0,
                  discount_rate REAL NOT NULL DEFAULT 0.5,
                  registered_weight REAL NOT NULL,
                  wage_per_gram REAL NOT NULL DEFAULT 23.0,
                  is_bulk INTEGER NOT NULL DEFAULT 0,
                  status TEXT NOT NULL DEFAULT 'in_stock'
                    CHECK(status IN ('in_stock','sold')),
                  barcode_path TEXT,
                  notes TEXT DEFAULT '',
                  entry_id INTEGER REFERENCES journal_entries(id),
                  is_deleted INTEGER NOT NULL DEFAULT 0,
                  created_by TEXT,
                  created_at TEXT DEFAULT (datetime('now','localtime'))
                )""")
            conn.execute(f"INSERT INTO work_orders({names})"
                         f" SELECT {names} FROM work_orders_old")
            conn.execute("DROP TABLE work_orders_old")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_work_orders_no_live"
                " ON work_orders(work_order_no) WHERE is_deleted=0")

        # 22) رقم الموديل: تصنيف تصميمي للأطقم
        cols = [r["name"] for r in conn.execute(
            "PRAGMA table_info(work_orders)")]
        if cols and "model_no" not in cols:
            conn.execute("ALTER TABLE work_orders ADD COLUMN model_no TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_wo_model"
                         " ON work_orders(model_no)")

        # 21) جدول فواقد الورشة
        from models.workshop_losses import SCHEMA as _WL
        for _st in _WL.split(";"):
            _st = _st.strip()
            if _st:
                conn.execute(_st)

        # 25) قفل الأسماء اليدوية
        # التسميات القياسية تُفرض عند كل إقلاع، فتمسح ما يسمّيه
        # المستخدم بنفسه — ويضيع عمله عند كل تحديث. هذا العمود يميّز
        # الاسم اليدوي فيُستثنى من الفرض.
        cols = [r["name"] for r in conn.execute(
            "PRAGMA table_info(accounts)")]
        if cols and "name_locked" not in cols:
            conn.execute("ALTER TABLE accounts ADD COLUMN"
                         " name_locked INTEGER NOT NULL DEFAULT 0")

        # 24) دمج صندوق الصافي 24 في صندوق الكسر
        # كلاهما ذهب خام؛ فصلهما كان يفرض متابعة رصيدين لبضاعة
        # واحدة. تُنقل حركات 1330 إلى 1310 ثم يُحذف — والأرصدة
        # تُجمع تلقائياً فلا يختل أي ميزان.
        try:
            src = conn.execute(
                "SELECT id FROM accounts WHERE code='1330'").fetchone()
            dst = conn.execute(
                "SELECT id FROM accounts WHERE code='1310'").fetchone()
            if src and dst:
                conn.execute(
                    "UPDATE journal_lines SET account_id=?"
                    " WHERE account_id=?", (dst["id"], src["id"]))
                conn.execute("UPDATE entities SET account_id=?"
                             " WHERE account_id=?", (dst["id"], src["id"]))
                conn.execute("DELETE FROM accounts WHERE id=?",
                             (src["id"],))
                conn.execute(
                    "UPDATE accounts SET name='صندوق الكسر (18 · 21 · 22 · 24)'"
                    " WHERE code='1310' AND COALESCE(name_locked,0)=0")
        except Exception:
            pass

        # 23) مفتاح ترتيب ثابت للقيد
        # الترتيب بمعرّف القيد يجعل القيد المُعاد ترحيله بعد التعديل
        # ينزل لآخر يومه (معرّفه أكبر) — فتتحرّك العملية من مكانها
        # في الكشف. المفتاح الثابت يُورَّث من القيد الأصلي فيبقى
        # مكان العملية وتاريخها كما كانا.
        cols = [r["name"] for r in conn.execute(
            "PRAGMA table_info(journal_entries)")]
        if cols and "sort_key" not in cols:
            conn.execute("ALTER TABLE journal_entries"
                         " ADD COLUMN sort_key INTEGER")
            conn.execute("UPDATE journal_entries SET sort_key=id"
                         " WHERE sort_key IS NULL")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entries_sort"
                         " ON journal_entries(entry_date, sort_key)")

        # 20) رقم مستند موحّد لكل قيد — يوثّق العملية ويربطها
        cols = [r["name"] for r in conn.execute(
            "PRAGMA table_info(journal_entries)")]
        if cols and "doc_no" not in cols:
            conn.execute("ALTER TABLE journal_entries ADD COLUMN doc_no TEXT")
            # ترقيم القيود القائمة بأثر رجعي
            for r in conn.execute(
                    "SELECT id FROM journal_entries ORDER BY id"):
                conn.execute("UPDATE journal_entries SET doc_no=?"
                             " WHERE id=?", (f"JV-{r['id']:05d}", r["id"]))

        # 19) توحيد صناديق الكسر: 1320 و1325 تُدمجان في 1310
        row = conn.execute("SELECT id FROM accounts WHERE code='1310'").fetchone()
        if row:
            main = row["id"]
            for old in ("1320", "1325"):
                r = conn.execute("SELECT id FROM accounts WHERE code=?",
                                 (old,)).fetchone()
                if not r:
                    continue
                conn.execute("UPDATE journal_lines SET account_id=?"
                             " WHERE account_id=?", (main, r["id"]))
                conn.execute("DELETE FROM accounts WHERE id=?", (r["id"],))
            conn.execute("UPDATE accounts SET name='صندوق الكسر (18 · 21 · 22)'"
                         " WHERE code='1310'")
            conn.execute("UPDATE accounts SET name='صندوق الصافي عيار 24'"
                         " WHERE code='1330'")

        # 18) تمييز العمال عن الموظفين + قبول نوع 'worker'
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(employees)")]
        if cols and "staff_kind" not in cols:
            conn.execute("ALTER TABLE employees ADD COLUMN staff_kind TEXT"
                         " DEFAULT 'employee'")
            conn.execute("UPDATE employees SET staff_kind='employee'"
                         " WHERE COALESCE(staff_kind,'')=''")
        # قيد CHECK القديم لا يقبل 'worker'. إعادة بناء الجدول داخل
        # معاملة مفتوحة تفشل (PRAGMA foreign_keys لا يُطبَّق حينها)،
        # فنكتفي بإسقاط القيد نهائياً: التحقق من نوع الجهة يتم في
        # `models/entities.py` وهو المصدر الوحيد لإنشاء الجهات.
        ddl = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table'"
            " AND name='entities'").fetchone()
        if ddl and "'worker'" not in (ddl["sql"] or ""):
            conn.execute("PRAGMA writable_schema=ON")
            fixed = (ddl["sql"] or "").replace(
                "'employee','other'", "'employee','worker','other'")
            conn.execute(
                "UPDATE sqlite_master SET sql=? WHERE type='table'"
                " AND name='entities'", (fixed,))
            conn.execute("PRAGMA writable_schema=OFF")

        # 17) جداول تكاليف ورواتب قسم التصنيع
        # تُنفَّذ عبارةً عبارة لا executescript، لأن الأخير يُنهي
        # المعاملة الصريحة ويُفشل COMMIT.
        from models.mfg_costs import SCHEMA as _MFG
        for _stmt in _MFG.split(";"):
            _stmt = _stmt.strip()
            if _stmt:
                conn.execute(_stmt)

        # 16) دعم تعدد المصانع: هوية المصنع على السجلات الرئيسية
        #     (الاستعلامات المحلية لا تُرشَّح بها حفاظاً على السرعة —
        #      الفصل الفعلي يقع في السحابة حيث تجتمع كل المصانع).
        from services import tenant as _tn
        tid = _tn.tenant_id()
        for tbl in ("journal_entries", "invoices", "vouchers",
                    "work_orders", "accounts", "entities", "audit_log"):
            cols = [r["name"] for r in conn.execute(
                f"PRAGMA table_info({tbl})")]
            if cols and "tenant_id" not in cols:
                conn.execute(
                    f"ALTER TABLE {tbl} ADD COLUMN tenant_id TEXT DEFAULT ''")
                conn.execute(
                    f"UPDATE {tbl} SET tenant_id=? WHERE COALESCE(tenant_id,'')=''",
                    (tid,))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_queue(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tenant_id TEXT NOT NULL,
              op_uuid TEXT NOT NULL UNIQUE,
              entity TEXT NOT NULL,
              payload TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending'
                     CHECK(status IN ('pending','sent','failed')),
              attempts INTEGER NOT NULL DEFAULT 0,
              last_error TEXT DEFAULT '',
              created_at TEXT DEFAULT (datetime('now','localtime')),
              sent_at TEXT
            )""")

        # 15) أسطر السند المتعددة (أعيرة مختلفة + نقد في سند واحد)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS voucher_lines(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              voucher_id INTEGER NOT NULL REFERENCES vouchers(id)
                         ON DELETE CASCADE,
              line_kind TEXT NOT NULL CHECK(line_kind IN ('gold','cash')),
              gold_weight REAL NOT NULL DEFAULT 0,
              gold_karat INTEGER NOT NULL DEFAULT 18,
              gold_equiv18 REAL NOT NULL DEFAULT 0,
              cash_amount REAL NOT NULL DEFAULT 0,
              line_notes TEXT DEFAULT ''
            )""")
        # ترحيل السندات القديمة إلى أسطر (مرة واحدة)
        has_any = conn.execute(
            "SELECT 1 FROM voucher_lines LIMIT 1").fetchone()
        if not has_any:
            for v in conn.execute(
                    "SELECT id, gold_weight, gold_karat, gold_equiv18,"
                    " cash_amount FROM vouchers WHERE is_deleted=0").fetchall():
                if v["gold_weight"]:
                    conn.execute(
                        "INSERT INTO voucher_lines(voucher_id,line_kind,"
                        "gold_weight,gold_karat,gold_equiv18)"
                        " VALUES(?,'gold',?,?,?)",
                        (v["id"], v["gold_weight"], v["gold_karat"],
                         v["gold_equiv18"]))
                if v["cash_amount"]:
                    conn.execute(
                        "INSERT INTO voucher_lines(voucher_id,line_kind,"
                        "cash_amount) VALUES(?,'cash',?)",
                        (v["id"], v["cash_amount"]))

        # 14) نقل تسويات الزيادة من حساب الإيراد (4310) إلى مخزون
        #     مستقل ضمن الأصول (1250) — الذهب لا يُخلق من العدم، فالزيادة
        #     تحويل مخزني بين الأصول لا إيراد.
        old = conn.execute("SELECT id FROM accounts WHERE code='4310'").fetchone()
        if old:
            new = conn.execute(
                "SELECT id FROM accounts WHERE code='1250'").fetchone()
            if new:
                conn.execute("UPDATE journal_lines SET account_id=?"
                             " WHERE account_id=?", (new["id"], old["id"]))
                conn.execute("DELETE FROM accounts WHERE id=?", (old["id"],))

        # 13) حقوق الملكية ثنائية البعد: تقبل النقد والذهب معاً، وجعل
        #     رأس المال وجاري الشركاء حسابات تقبل الحركة مباشرة.
        for code in ("3110", "3120", "3200", "3210"):
            conn.execute("UPDATE accounts SET balance_type='both'"
                         " WHERE code=? AND balance_type<>'both'", (code,))
        for code in ("3110", "3120"):
            conn.execute("UPDATE accounts SET is_postable=1"
                         " WHERE code=? AND is_postable=0", (code,))

        # 12) نوع الطقم (تصنيف آلي): أحجار / زركون / ألماس / إيطالي
        wcols = [r["name"] for r in conn.execute(
            "PRAGMA table_info(work_orders)")]
        if wcols and "item_type" not in wcols:
            conn.execute("ALTER TABLE work_orders ADD COLUMN item_type"
                         " TEXT DEFAULT ''")
            # تصنيف الأطقم القائمة أثرياً بنفس القاعدة
            for w in conn.execute(
                    "SELECT id, work_order_no, gold_weight, small_stones,"
                    " big_stones FROM work_orders").fetchall():
                if w["work_order_no"] == "0001":
                    t = "إيطالي"
                elif (w["big_stones"] or 0) > 0:
                    t = "أحجار"
                elif (w["small_stones"] or 0) > 0:
                    t = "زركون"
                else:
                    t = "ألماس"
                conn.execute("UPDATE work_orders SET item_type=? WHERE id=?",
                             (t, w["id"]))

        # 11) تسويات مباشرة: السماح بإشعارات بلا فاتورة + عمود المبلغ
        tcols = [r["name"] for r in conn.execute(
            "PRAGMA table_info(tax_debit_notes)")]
        if tcols:
            # invoice_id يجب أن يقبل NULL (تسوية غير مرتبطة بفاتورة).
            # نكتشف قيد NOT NULL بمحاولة إدراج تجريبية داخل savepoint.
            need_rebuild = False
            conn.execute("SAVEPOINT chk_tdn")
            try:
                conn.execute(
                    "INSERT INTO tax_debit_notes(invoice_id,note_no,note_date,"
                    "vat_amount,created_by) VALUES(NULL,'__chk__','2000-01-01',"
                    "0,'__chk__')")
                conn.execute("ROLLBACK TO chk_tdn")
            except Exception:
                conn.execute("ROLLBACK TO chk_tdn")
                need_rebuild = True
            conn.execute("RELEASE chk_tdn")
            if "base_amount" not in tcols:
                conn.execute("ALTER TABLE tax_debit_notes ADD COLUMN"
                             " base_amount REAL NOT NULL DEFAULT 0")
            if need_rebuild:
                conn.execute("ALTER TABLE tax_debit_notes RENAME TO _tdn_old")
                conn.execute("""
                    CREATE TABLE tax_debit_notes(
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      note_no TEXT UNIQUE,
                      invoice_id INTEGER REFERENCES invoices(id),
                      note_date TEXT NOT NULL,
                      base_amount REAL NOT NULL DEFAULT 0,
                      vat_amount REAL NOT NULL,
                      entry_id INTEGER REFERENCES journal_entries(id),
                      is_deleted INTEGER NOT NULL DEFAULT 0,
                      created_by TEXT,
                      created_at TEXT DEFAULT (datetime('now','localtime'))
                    )""")
                old = [r["name"] for r in conn.execute(
                    "PRAGMA table_info(_tdn_old)")]
                shared = [c for c in ("id", "note_no", "invoice_id",
                                      "note_date", "base_amount", "vat_amount",
                                      "entry_id", "is_deleted", "created_by",
                                      "created_at") if c in old]
                cols = ",".join(shared)
                conn.execute(f"INSERT INTO tax_debit_notes({cols})"
                             f" SELECT {cols} FROM _tdn_old")
                conn.execute("DROP TABLE _tdn_old")

        # 10) شجرة الحسابات الديناميكية: المستوى، التنشيط، الوسم النظامي
        acols = [r["name"] for r in conn.execute("PRAGMA table_info(accounts)")]
        if acols:
            if "account_level" not in acols:
                conn.execute("ALTER TABLE accounts ADD COLUMN account_level"
                             " INTEGER NOT NULL DEFAULT 1")
            if "is_active" not in acols:
                conn.execute("ALTER TABLE accounts ADD COLUMN is_active"
                             " INTEGER NOT NULL DEFAULT 1")
            if "system_tag" not in acols:
                conn.execute("ALTER TABLE accounts ADD COLUMN system_tag TEXT")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_accounts_system_tag"
                " ON accounts(system_tag) WHERE system_tag IS NOT NULL")
            conn.execute("""
                CREATE VIEW IF NOT EXISTS accounts_tree AS
                  SELECT id AS account_id, code AS account_code,
                         name AS account_name, parent_id AS parent_id,
                         type AS account_type, nature AS account_nature,
                         is_postable AS is_transactional,
                         account_level AS account_level,
                         CASE balance_type WHEN 'cash' THEN 'CASH_ONLY'
                                           WHEN 'gold' THEN 'GOLD_ONLY'
                                           ELSE 'BOTH' END AS measurement_type,
                         is_active AS is_active, system_tag AS system_tag
                  FROM accounts""")

        # 9) البيان الحقيقي: ملاحظة المستخدم فقط (فارغة افتراضياً)
        jcols = [r["name"] for r in conn.execute("PRAGMA table_info(journal_entries)")]
        if jcols and "user_note" not in jcols:
            conn.execute("ALTER TABLE journal_entries ADD COLUMN user_note"
                         " TEXT NOT NULL DEFAULT ''")

        # 8) دورة الصهر والتصفية المرحلية: نوع العملية + أسطر العيارات
        mcols = [r["name"] for r in conn.execute("PRAGMA table_info(melting_ops)")]
        if mcols and "kind" not in mcols:
            conn.execute("ALTER TABLE melting_ops ADD COLUMN kind TEXT"
                         " NOT NULL DEFAULT 'legacy'")
            conn.execute("ALTER TABLE melting_ops ADD COLUMN equiv18 REAL"
                         " NOT NULL DEFAULT 0")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS melting_lines(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              op_id INTEGER NOT NULL REFERENCES melting_ops(id),
              karat INTEGER NOT NULL CHECK(karat IN (18,21,24)),
              weight REAL NOT NULL,
              equiv18 REAL NOT NULL
            )""")

        # 7) entities: توسعة لتشمل الموظفين والشركاء (راتب، مركز تكلفة،
        #    نسبة شراكة، عنوان...) — يتطلب إعادة بناء الجدول لتوسيع قيد
        #    CHECK على entity_type ليقبل 'employee' و'other'.
        ent_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='entities'"
        ).fetchone()
        if ent_sql and ("'employee'" not in ent_sql["sql"]
                        or "'other'" not in ent_sql["sql"]):
            old = [r["name"] for r in conn.execute("PRAGMA table_info(entities)")]
            conn.execute("ALTER TABLE entities RENAME TO entities_old")
            conn.execute("""
                CREATE TABLE entities(
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL,
                  phone TEXT DEFAULT '',
                  vat_number TEXT DEFAULT '',
                  address TEXT DEFAULT '',
                  entity_type TEXT NOT NULL DEFAULT 'customer'
                    CHECK(entity_type IN ('customer','supplier','partner',
                                          'employee','other','internal')),
                  account_id INTEGER NOT NULL REFERENCES accounts(id),
                  capital_account_id INTEGER REFERENCES accounts(id),
                  share_percent REAL NOT NULL DEFAULT 0,
                  job_title TEXT DEFAULT '',
                  basic_salary REAL NOT NULL DEFAULT 0,
                  employee_id INTEGER REFERENCES employees(id),
                  opening_entry_id INTEGER REFERENCES journal_entries(id),
                  is_internal INTEGER NOT NULL DEFAULT 0,
                  is_deleted INTEGER NOT NULL DEFAULT 0,
                  created_by TEXT, created_at TEXT DEFAULT (datetime('now','localtime'))
                )""")
            carry = [c for c in ("id", "name", "phone", "vat_number", "address",
                                "entity_type", "account_id", "capital_account_id",
                                "share_percent", "job_title", "basic_salary",
                                "employee_id", "opening_entry_id", "is_internal",
                                "is_deleted", "created_by", "created_at")
                     if c in old]
            cols = ",".join(carry)
            conn.execute(f"INSERT INTO entities({cols}) SELECT {cols} FROM entities_old")
            conn.execute("DROP TABLE entities_old")

        # 11) جدول الإعدادات العام (قفل الفترات وغيره)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS app_settings("
            " key TEXT PRIMARY KEY,"
            " value TEXT NOT NULL DEFAULT '',"
            " updated_by TEXT,"
            " updated_at TEXT DEFAULT (datetime('now','localtime')))")

        # 12) فهارس الأداء المتأخرة — تُنشأ على القواعد القائمة أيضاً.
        #     بدون idx_sync_sent كان تنظيف الطابور يمسح الجدول كاملاً،
        #     وبدون idx_audit_when كان سجل التدقيق يُرتَّب بلا فهرس.
        for ddl in (
            "CREATE INDEX IF NOT EXISTS idx_sync_sent"
            " ON sync_queue(status, sent_at)",
            "CREATE INDEX IF NOT EXISTS idx_audit_when"
            " ON audit_log(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_audit_table"
            " ON audit_log(table_name, record_id)",
            "CREATE INDEX IF NOT EXISTS idx_vch_live"
            " ON vouchers(is_deleted, voucher_date)",
            "CREATE INDEX IF NOT EXISTS idx_inv_date"
            " ON invoices(invoice_date)",
            "CREATE INDEX IF NOT EXISTS idx_items_wo_live"
            " ON invoice_items(work_order_id, invoice_id)",
            "CREATE INDEX IF NOT EXISTS idx_pay_emp"
            " ON payroll_ledger(employee_id, period, is_deleted)",
        ):
            try:
                conn.execute(ddl)
            except Exception:
                pass          # جدول غير موجود في قاعدة قديمة جداً

        # 17) حدّ الائتمان لكل جهة — سقفٌ نقديٌّ ووزنيٌّ يُفحص لحظة
        #     الترحيل (`services.credit_guard`). صفرٌ = بلا حدّ، فالقاعدة
        #     القائمة تعمل بعد الترقية كما كانت تماماً حتى يضع المستخدم
        #     سقفاً لمن يريد.
        ent_cols = [r["name"] for r in conn.execute(
            "PRAGMA table_info(entities)")]
        if ent_cols:
            for col in ("credit_limit", "credit_limit_gold"):
                if col not in ent_cols:
                    conn.execute(
                        f"ALTER TABLE entities ADD COLUMN {col}"
                        " REAL NOT NULL DEFAULT 0")

        # 22) ربط الفاتورة بالصور التي تستعملها — فتُعرف الصور التي
        #     لم تعد مستعملة وتُحذف من التخزين بدل أن تتراكم.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS invoice_assets(
              invoice_id INTEGER NOT NULL,
              sha TEXT NOT NULL,
              PRIMARY KEY(invoice_id, sha)
            )""")

        # 21) مسوّدات شاشات الإدخال — ما أُدخل ولم يُرحَّل بعد.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS screen_drafts(
              screen TEXT NOT NULL,
              username TEXT NOT NULL DEFAULT '',
              payload TEXT NOT NULL DEFAULT '',
              updated_at TEXT DEFAULT (datetime('now','localtime')),
              PRIMARY KEY(screen, username)
            )""")

        # 20) سجل ما رُفع للتخزين السحابي من صور الموديلات.
        #     المفتاح بصمة محتوى الصورة: فموديلٌ في مئة فاتورة تُرفع
        #     صورته مرةً واحدة وتشير إليها المئة كلها — وهذا ما يجعل
        #     المساحة المستهلكة جزءاً يسيراً بدل أن تتضاعف مع كل فاتورة.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cloud_assets(
              sha TEXT PRIMARY KEY,
              url TEXT NOT NULL,
              size_bytes INTEGER NOT NULL DEFAULT 0,
              created_at TEXT DEFAULT (datetime('now','localtime'))
            )""")

        # 19) صفحة الفاتورة للجوال (`services.invoice_share`): رمزٌ
        #     عشوائي ثابت لكل فاتورة ورابطها المنشور. ثباتهما مقصود —
        #     رابطٌ سُلّم للعميل يجب أن يبقى يعمل بعد إعادة الطباعة.
        inv_cols = [r["name"] for r in conn.execute(
            "PRAGMA table_info(invoices)")]
        if inv_cols:
            for col in ("share_token", "share_url"):
                if col not in inv_cols:
                    conn.execute(
                        f"ALTER TABLE invoices ADD COLUMN {col} TEXT")
            # الفواتير السابقة تبقى بلا رمز: القرار للمستخدم فاتورةً
            # فاتورة، ولا يُرفع شيء لفاتورة لم يطلب لها رمزاً.
            if "qr_enabled" not in inv_cols:
                conn.execute("ALTER TABLE invoices ADD COLUMN qr_enabled"
                             " INTEGER NOT NULL DEFAULT 0")

        # 18) سلسلة بصمات القيود — سجل تدقيق محصَّن (`models.integrity`).
        #     العمودان يبقيان فارغين للقيود السابقة حتى تُختم دفعةً
        #     واحدة من شاشة «سلامة السجل»، والفهرس يجعل قراءة رأس
        #     السلسلة فورية وهي تُقرأ مع كل ترحيل.
        je_cols = [r["name"] for r in conn.execute(
            "PRAGMA table_info(journal_entries)")]
        if je_cols:
            for col in ("row_hash", "prev_hash"):
                if col not in je_cols:
                    conn.execute(
                        f"ALTER TABLE journal_entries ADD COLUMN {col} TEXT")
            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_je_sealed"
                             " ON journal_entries(row_hash)")
            except Exception:
                pass


def run_migrations_files():
    """ينفّذ ملفات الهجرة المرقّمة مرة واحدة لكل إصدار.

    يُستدعى عند الإقلاع بعد `migrate_schema()`: إن لم توجد هجرات
    معلّقة لم يفعل شيئاً (سريع)، وإن فشلت هجرة تراجعت وحدها وبقيت
    القاعدة سليمة لإعادة المحاولة.
    """
    from services import migrations
    with db() as conn:
        return migrations.run_all(conn)
