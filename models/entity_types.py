# -*- coding: utf-8 -*-
"""أنواع جهات التعامل التي يُنشئها المستخدم (5.8.4).

إلى جانب الأنواع الثابتة (عميل · مورد · شريك · موظف · عامل · جهة أخرى)
يُنشئ المستخدم نوعاً جديداً باسمه — «مكاتب الصيانة» أو «شركات الشحن»
مثلاً — فيصير نوعاً رسمياً في كل مكان:

* **في شجرة الحسابات**: حسابٌ رقابي (تجميعي) باسم «إجمالي <الجمع>» —
  تحت «الذمم المدينة» (1030) إن كانت الجهات مدينةً لنا كالعملاء، أو تحت
  «الخصوم المتداولة» (2010) إن كانت دائنةً كالموردين. وكل جهةٍ من النوع
  حسابٌ فرعيٌّ تحته بكودٍ من كوده (103001 ← 10300101).
* **في الميزانية والقوائم**: سطرٌ مستقل لكل نوع، ورصيده يُقسَم بإشارة كل
  حساب (المدين أصول والدائن خصوم) كالعملاء والموردين تماماً.
* **في التكويد الموحّد والسندات والكشوف والفواتير**: يُختار من قوائم
  الأنواع، ويظهر اسمه بجانب كل جهةٍ منه.

النوع التجاري الجديد ينتقل بين العميل والمورد والجهة الأخرى (وينقل
حسابه تحت مجموعته) كما تنتقل الأنواع الثابتة بينها.
"""
from services.audit import log_action

CODE_PREFIX = "x_"                 # مفتاح النوع في `entities.entity_type`
ASSET_PARENT = "1030"              # الأصول المتداولة — الذمم المدينة
LIABILITY_PARENT = "2010"          # الخصوم المتداولة
SIDES = (("asset", "مدينون لنا (أصول) — مثل العملاء"),
         ("liability", "دائنون لنا (خصوم) — مثل الموردين"))
BALANCES = (("both", "ذهب ونقد"), ("cash", "نقد فقط"))

_CACHE = {"key": None, "rows": None}


def ensure_schema(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS entity_types("
        " code TEXT PRIMARY KEY,"
        " label TEXT NOT NULL,"            # المفرد: «مكتب صيانة»
        " plural TEXT NOT NULL,"           # الجمع: «مكاتب الصيانة»
        " side TEXT NOT NULL DEFAULT 'asset',"
        " balance_type TEXT NOT NULL DEFAULT 'both',"
        " account_id INTEGER,"
        " created_by TEXT,"
        " created_at TEXT DEFAULT CURRENT_TIMESTAMP,"
        " is_active INTEGER NOT NULL DEFAULT 1)")


def _key():
    try:
        import config
        return str(config.DB_PATH)
    except Exception:                       # noqa: BLE001
        return ""


def _read(conn):
    try:
        rows = conn.execute(
            "SELECT t.*, a.code acode FROM entity_types t"
            " LEFT JOIN accounts a ON a.id=t.account_id"
            " WHERE t.is_active=1 ORDER BY t.created_at, t.code").fetchall()
    except Exception:                       # noqa: BLE001 — قاعدة قبل الترقية
        return {}
    out = {}
    for r in rows:
        d = dict(r)
        d["parent_code"] = d.pop("acode") or ""
        d["prefix"] = f"{d['label']}: "
        out[d["code"]] = d
    return out


def reload(conn=None):
    """يقرأ الأنواع من القاعدة الحالية (أو من اتصالٍ مفتوح)."""
    if conn is None:
        try:
            from database.database import db
            with db(readonly=True) as c:
                rows = _read(c)
        except Exception:                   # noqa: BLE001
            rows = {}
    else:
        rows = _read(conn)
    _CACHE["key"], _CACHE["rows"] = _key(), rows
    return rows


def all_types(conn=None):
    """{المفتاح: صفّه} لكل نوعٍ أنشأه المستخدم — بترتيب إنشائه."""
    if conn is not None:
        return reload(conn)
    if _CACHE["rows"] is None or _CACHE["key"] != _key():
        return reload()
    return _CACHE["rows"]


def get(code):
    """صفّ النوع أو None — ومفتاحٌ مجهول يُعاد البحث عنه مرةً في القاعدة
    (نوعٌ أنشأه اتصالٌ آخر بعد آخر قراءة)."""
    if not isinstance(code, str) or not code.startswith(CODE_PREFIX):
        return None
    rows = all_types()
    if code not in rows:
        rows = reload()
    return rows.get(code)


def is_custom(code):
    return get(code) is not None


def codes(conn=None):
    return tuple(all_types(conn).keys())


def create(conn, plural, label="", side="asset", balance_type="both",
           username=None):
    """ينشئ نوعاً جديداً وحسابه الرقابي في الشجرة — ويعيد مفتاحه."""
    from models import coa
    from models.entities import TYPE_LABELS, normalize_name
    ensure_schema(conn)
    plural = (plural or "").strip()
    label = (label or "").strip() or plural
    if not plural:
        raise ValueError("اكتب اسم النوع — مثال: «مكاتب الصيانة»")
    if side not in dict(SIDES):
        raise ValueError("اختر طبيعة النوع: مدينون لنا أو دائنون لنا")
    if balance_type not in dict(BALANCES):
        raise ValueError("اختر الأرصدة: ذهب ونقد، أو نقد فقط")
    taken = {normalize_name(v) for v in dict.values(TYPE_LABELS)}
    taken |= {normalize_name(x) for x in ("العملاء", "الموردون", "الموردين",
                                          "الشركاء", "الموظفون", "الموظفين",
                                          "العمال", "الجهات الأخرى")}
    for r in _read(conn).values():
        taken |= {normalize_name(r["label"]), normalize_name(r["plural"])}
    if normalize_name(plural) in taken or normalize_name(label) in taken:
        raise ValueError(f"يوجد نوعٌ بهذا الاسم: «{plural}»")
    parent_code = ASSET_PARENT if side == "asset" else LIABILITY_PARENT
    par = conn.execute("SELECT id, account_level FROM accounts WHERE code=?",
                       (parent_code,)).fetchone()
    if not par:
        raise ValueError(f"حساب المجموعة {parent_code} غير موجود في الشجرة")
    acc_code = coa.next_child_code(conn, par["id"])
    acc_id = conn.execute(
        "INSERT INTO accounts(code,name,type,parent_id,is_postable,nature,"
        "balance_type,account_level) VALUES(?,?,?,?,0,?,?,?)",
        (acc_code, f"إجمالي {plural}", side, par["id"],
         "debit" if side == "asset" else "credit", balance_type,
         (par["account_level"] or 1) + 1)).lastrowid
    n = conn.execute("SELECT COUNT(*) FROM entity_types").fetchone()[0]
    code = f"{CODE_PREFIX}{n + 1}"
    while conn.execute("SELECT 1 FROM entity_types WHERE code=?",
                       (code,)).fetchone():
        n += 1
        code = f"{CODE_PREFIX}{n + 1}"
    conn.execute(
        "INSERT INTO entity_types(code,label,plural,side,balance_type,"
        "account_id,created_by) VALUES(?,?,?,?,?,?,?)",
        (code, label, plural, side, balance_type, acc_id, username))
    log_action(conn, username, "create", "entity_types", acc_id,
               f"نوع جهة جديد: {plural} (الحساب {acc_code})")
    reload(conn)
    return code


def control_codes(side=None):
    """أكواد الحسابات الرقابية للأنواع (لجانبٍ واحد إن طُلب)."""
    return tuple(r["parent_code"] for r in all_types().values()
                 if r["parent_code"] and (side is None or r["side"] == side))
