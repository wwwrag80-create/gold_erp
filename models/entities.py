# -*- coding: utf-8 -*-
"""دليل جهات التعامل الموحّد (Entities & Sub-Ledgers): عملاء، موردون،
شركاء، موظفون، وحسابات داخلية — البوابة الوحيدة لتأسيس الحسابات.
كل جهة تُربط آلياً بحساب فرعي (أو حسابين للشريك) تحت مجموعتها في شجرة
الحسابات، ويُولَّد قيد افتتاحي آلي لأي رصيد افتتاحي نقدي أو وزني."""
from models.accounts import acc_id
from services.accounting_engine import account_balance, post_entry
from services.audit import log_action

# المجموعة الرئيسية في شجرة الحسابات لكل نوع جهة
PARENT_CODE = {"customer": "1600", "supplier": "2300", "employee": "1950",
               "worker": "1970", "other": "1650"}
PARTNER_CAPITAL_PARENT = "3110"
EMPLOYEE_ACCRUED_PARENT = "2200"   # مستحقات الموظفين (خصوم متداولة)
PARTNER_CURRENT_PARENT = "3120"
OPENING_SUSPENSE = "3900"      # الأرصدة الافتتاحية للتسوية

TYPE_LABELS = {"customer": "عميل", "supplier": "مورد", "partner": "شريك",
              "employee": "موظف", "worker": "عامل", "other": "جهة أخرى",
              "internal": "حساب داخلي"}

# حساب مستحقات عمال التصنيع — أب حسابات العمال الفرعية
WORKER_ACCRUED_PARENT = "2250"
ACC_TYPE = {"customer": "asset", "supplier": "liability", "employee": "asset",
            "worker": "asset", "other": "asset"}
PREFIX = {"customer": "عميل: ", "supplier": "مورد: ", "employee": "موظف: ",
          "worker": "عامل: ", "other": "أخرى: "}


ALEF = "أإآٱا"
_NORM_MAP = {**{c: "ا" for c in ALEF}, "ة": "ه", "ى": "ي", "ؤ": "و",
            "ئ": "ي", "\u0640": ""}


def normalize_name(name: str) -> str:
    """تطبيع الاسم العربي لكشف التكرار: توحيد الهمزات والتاء المربوطة
    والألف المقصورة، وحذف التطويل والتشكيل والمسافات الزائدة."""
    s = "".join(_NORM_MAP.get(ch, ch) for ch in (name or "").strip())
    s = "".join(ch for ch in s if not ("\u064b" <= ch <= "\u0652"))
    return " ".join(s.split()).lower()


def find_similar(conn, name, entity_type=None, limit=8):
    """أسماء مشابهة موجودة مسبقاً (للإكمال التلقائي ومنع التكرار)."""
    target = normalize_name(name)
    if not target:
        return []
    rows = list_entities(conn, (entity_type,) if entity_type else None)
    out = []
    for r in rows:
        n = normalize_name(r["name"])
        if target in n or n in target or n.startswith(target[:3]):
            out.append(r)
    return out[:limit]


def name_exists(conn, name, entity_type):
    """هل يوجد اسم مطابق بعد التطبيع (يمنع «الأفق» و«الافق» معاً)؟"""
    target = normalize_name(name)
    for r in conn.execute(
            "SELECT id, name FROM entities WHERE entity_type=? AND is_deleted=0",
            (entity_type,)):
        if normalize_name(r["name"]) == target:
            return r
    return None


def subledger_summary(conn, entity_type):
    """أرصدة الأستاذ المساعد لفئة كاملة (حساب مراقبة تجميعي):
    يعيد (ملخص الفئة، تفاصيل كل جهة)."""
    rows = list_entities(conn, (entity_type,))
    details, tot_cash, tot_gold = [], 0.0, 0.0
    for r in rows:
        g, c = account_balance(conn, r["account_id"])
        cap_g = cap_c = 0.0
        if r["capital_account_id"]:
            cap_g, cap_c = account_balance(conn, r["capital_account_id"])
        details.append({"id": r["id"], "name": r["name"],
                        "phone": r["phone"], "gold": g, "cash": c,
                        "cap_gold": cap_g, "cap_cash": cap_c,
                        "account_id": r["account_id"]})
        tot_cash = round(tot_cash + c + cap_c, 2)
        tot_gold = round(tot_gold + g + cap_g, 3)
    return ({"count": len(details), "total_cash": tot_cash,
             "total_gold": tot_gold, "label": TYPE_LABELS.get(entity_type, "")},
            details)


def _next_child_code(conn, parent_code):
    """أول كود متاح تحت الأب — **مع ضمان عدم تكراره عالمياً**.

    الاعتماد على `MAX` بين الأبناء وحدهم كان يُنتج كوداً مستخدماً تحت
    أب آخر (مثال: أبناء 1950 يصلون إلى 1970 وهو كود «سلف عمال
    التصنيع») فيفشل الإدراج بـ`UNIQUE constraint failed`.

    الآن نبحث عن أول رقم حرّ فعلياً في الشجرة كلها، فلا يتعارض أبداً
    مهما كثرت الجهات.
    """
    parent = conn.execute("SELECT id FROM accounts WHERE code=?",
                          (parent_code,)).fetchone()
    if not parent:
        raise ValueError(f"حساب رئيسي غير موجود في الشجرة: {parent_code}")
    used = {r["code"] for r in conn.execute("SELECT code FROM accounts")}
    row = conn.execute(
        "SELECT MAX(CAST(code AS INTEGER)) m FROM accounts WHERE parent_id=?",
        (parent["id"],)).fetchone()
    n = int(row["m"] or int(parent_code))
    # نتقدّم حتى أول كود غير مستخدم في الشجرة كلها
    for _ in range(100000):
        n += 1
        if str(n) not in used:
            return str(n), parent["id"]
    raise ValueError("تعذّر إيجاد كود حساب متاح — راجع شجرة الحسابات")


def _create_sub_account(conn, parent_code, name, acc_type, balance_type):
    code, parent_id = _next_child_code(conn, parent_code)
    nature = "credit" if acc_type in ("liability", "equity", "revenue") else "debit"
    cur = conn.execute(
        "INSERT INTO accounts(code,name,type,parent_id,is_postable,nature,"
        "balance_type) VALUES(?,?,?,?,1,?,?)",
        (code, name, acc_type, parent_id, nature, balance_type))
    return cur.lastrowid


def _post_opening(conn, entity_name, account_id, open_cash, open_gold,
                  opening_date, username, label="رصيد افتتاحي"):
    """قيد الرصيد الافتتاحي مقابل حساب الأرصدة الافتتاحية للتسوية.
    الموجب = مدين (على الجهة)، السالب = دائن (لها)."""
    if not open_cash and not open_gold:
        return None
    susp = acc_id(conn, OPENING_SUSPENSE)
    ent_line, susp_line = {"account_id": account_id}, {"account_id": susp}
    if open_cash > 0:
        ent_line["cash_debit"] = open_cash
        susp_line["cash_credit"] = open_cash
    elif open_cash < 0:
        ent_line["cash_credit"] = abs(open_cash)
        susp_line["cash_debit"] = abs(open_cash)
    if open_gold > 0:
        ent_line["gold_debit"] = open_gold
        susp_line["gold_credit"] = open_gold
    elif open_gold < 0:
        ent_line["gold_credit"] = abs(open_gold)
        susp_line["gold_debit"] = abs(open_gold)
    ent_line["line_desc"] = f"{label} — {entity_name}"
    return post_entry(conn, opening_date, f"{label} — {entity_name}",
                      [ent_line, susp_line], source_table="entities",
                      username=username)


def add_entity(conn, name, entity_type, phone="", vat_number="", username=None,
               address="", open_cash=0.0, open_gold=0.0,
               opening_date=None, share_percent=0.0, job_title="",
               basic_salary=0.0):
    """يضيف جهة تعامل وينشئ حسابها الفرعي آلياً + قيد رصيدها الافتتاحي.

    عميل  → فرع تحت 1600 (رصيدا ذهب ونقد)
    مورد  → فرع تحت 2300 (الرقم الضريبي إلزامي لدعم الفوترة الإلكترونية)
    شريك  → فرعان: رأس مال تحت 3110 (يستقبل رأس المال التأسيسي) وجارٍ
             تحت 3120 (المسحوبات والتوزيعات والمعاملات اليومية)
    موظف  → حسابان: سلف تحت 1950 «سلف الموظفين» (أصل)، ومستحقات تحت
             2200 «مستحقات الموظفين» (خصم) يستقبل قيد الاستحقاق الشهري
             ويُقفل بسند صرف الراتب
    أخرى  → فرع تحت 1650 «إجمالي الجهات الأخرى» ضمن الأصول المتداولة
             (مدينون آخرون) برصيدي ذهب ونقد وكشف حساب مفصّل
    """
    name = name.strip()
    if not name:
        raise ValueError("أدخل اسم الجهة")
    if entity_type not in ("customer", "supplier", "partner", "employee",
                           "worker", "other"):
        raise ValueError("نوع الجهة غير صحيح")
    if entity_type == "supplier" and not vat_number.strip():
        raise ValueError("الرقم الضريبي إلزامي للموردين (لدعم الفوترة "
                         "الإلكترونية ZATCA)")
    if entity_type in ("employee", "worker"):
        label = "الموظف" if entity_type == "employee" else "العامل"
        if basic_salary <= 0:
            raise ValueError(f"أدخل الراتب الأساسي {'لل' + label[2:]}")
        if open_gold:
            raise ValueError(f"لا يوجد رصيد افتتاحي وزني {'لل' + label[2:]}")
    if entity_type == "partner" and not 0 <= share_percent <= 100:
        raise ValueError("نسبة الحصة يجب أن تكون بين 0 و100")
    dup = name_exists(conn, name, entity_type)
    if dup:
        raise ValueError(
            f"يوجد {TYPE_LABELS[entity_type]} مسجَّل بنفس الاسم: «{dup['name']}»"
            " — اختره من القائمة بدل إنشاء حساب مكرر")

    opening_date = opening_date or "2000-01-01"
    capital_account_id = employee_id = None

    if entity_type == "partner":
        account_id = _create_sub_account(
            conn, PARTNER_CURRENT_PARENT, f"جاري الشريك: {name}", "equity", "both")
        capital_account_id = _create_sub_account(
            conn, PARTNER_CAPITAL_PARENT, f"رأس مال الشريك: {name}", "equity", "both")
    elif entity_type == "employee":
        # حساب السلف (أصل) + حساب المستحقات (خصم) — كل منهما مستقل
        account_id = _create_sub_account(
            conn, PARENT_CODE["employee"], PREFIX["employee"] + name,
            "asset", "cash")
        capital_account_id = _create_sub_account(
            conn, EMPLOYEE_ACCRUED_PARENT, f"مستحقات الموظف: {name}",
            "liability", "cash")
    elif entity_type == "worker":
        # العامل: حسابه الشخصي (سلف) + مستحقاته تحت 2250، مستقلان
        # تماماً عن حسابات الموظفين فلا يختلط قسم التصنيع بالإدارة.
        account_id = _create_sub_account(
            conn, PARENT_CODE["employee"], PREFIX["worker"] + name,
            "asset", "cash")
        capital_account_id = _create_sub_account(
            conn, WORKER_ACCRUED_PARENT, f"مستحقات العامل: {name}",
            "liability", "cash")
    else:
        bal_type = "cash" if entity_type in ("supplier", "employee") else "both"
        account_id = _create_sub_account(
            conn, PARENT_CODE[entity_type], PREFIX[entity_type] + name,
            ACC_TYPE[entity_type], bal_type)

    if entity_type in ("employee", "worker"):
        # كلاهما يُسجَّل في `employees` لتوحيد منطق الرواتب، ويُميَّز
        # بعمود `staff_kind` فتفصل شاشة التصنيع العمال عن الموظفين.
        cur = conn.execute(
            "INSERT INTO employees(name,basic_salary,staff_kind,created_by)"
            " VALUES(?,?,?,?)",
            (name, basic_salary, entity_type, username))
        employee_id = cur.lastrowid

    # الرصيد الافتتاحي: للشريك يُقيَّد رأس المال التأسيسي على حساب رأس
    # المال (دائن بطبيعته)، ولبقية الجهات على حسابها الأساسي.
    if entity_type == "partner":
        opening_entry_id = _post_opening(
            conn, name, capital_account_id, -abs(open_cash), -abs(open_gold),
            opening_date, username, "رأس المال التأسيسي")
    else:
        opening_entry_id = _post_opening(
            conn, name, account_id, open_cash, open_gold, opening_date, username)

    cur = conn.execute(
        "INSERT INTO entities(name,phone,vat_number,address,entity_type,"
        "account_id,capital_account_id,share_percent,job_title,basic_salary,"
        "employee_id,opening_entry_id,created_by)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (name, phone.strip(), vat_number.strip(), address.strip(), entity_type,
         account_id, capital_account_id, share_percent, job_title.strip(),
         basic_salary, employee_id, opening_entry_id, username))
    ent_id = cur.lastrowid
    if opening_entry_id:
        conn.execute("UPDATE journal_entries SET source_id=? WHERE id=?",
                     (ent_id, opening_entry_id))
    log_action(conn, username, "create", "entities", ent_id,
              f"{TYPE_LABELS[entity_type]}: {name}")
    return ent_id


# ══════════════════════════════════════════════════════════════════
#  حدّ الائتمان
# ------------------------------------------------------------------
#  سقفٌ لِما يُسلَّم للجهة قبل أن تسدّد — يُفحص لحظة الترحيل في
#  `services.credit_guard`. **صفرٌ يعني بلا حدّ**، لا حدّاً صفرياً:
#  فالجهات القائمة تبقى بلا سقف حتى يضعه المستخدم صراحةً.
#  الوزن يُخزَّن بمكافئ عيار 18 كسائر أوزان النظام.
# ══════════════════════════════════════════════════════════════════

def set_credit_limit(conn, entity_id, limit_cash=0.0, limit_gold=0.0,
                     username=None):
    """يضبط سقفَي الجهة النقدي والوزني ويوثّق التغيير في التدقيق."""
    e = get_entity(conn, entity_id)
    if not e:
        raise ValueError("الجهة غير موجودة")
    c = round(float(limit_cash or 0), 2)
    g = round(float(limit_gold or 0), 3)
    if c < 0 or g < 0:
        raise ValueError("حدّ الائتمان لا يكون سالباً — الصفر يعني بلا حدّ")
    conn.execute("UPDATE entities SET credit_limit=?, credit_limit_gold=?"
                 " WHERE id=?", (c, g, entity_id))
    try:
        from services.audit import log_action
        log_action(conn, username, "update", "entities", entity_id,
                   f"حدّ الائتمان: نقد {c} · وزن {g}")
    except Exception:
        pass
    return c, g


def credit_limit(conn, entity_id):
    """(السقف النقدي، السقف الوزني) للجهة — وصفران إن لم يُحدَّد."""
    try:
        r = conn.execute(
            "SELECT COALESCE(credit_limit,0) c,"
            " COALESCE(credit_limit_gold,0) g FROM entities WHERE id=?",
            (entity_id,)).fetchone()
    except Exception:
        return 0.0, 0.0          # قاعدة قبل الترقية
    if not r:
        return 0.0, 0.0
    return round(float(r["c"] or 0), 2), round(float(r["g"] or 0), 3)


def add_customer(conn, name, phone="", vat_number="", username=None) -> int:
    """اسم متوافق مع الإصدارات السابقة (إضافة سريعة لعميل)."""
    return add_entity(conn, name, "customer", phone, vat_number, username)


def list_entities(conn, types=None):
    q = "SELECT e.* FROM entities e WHERE e.is_deleted=0"
    params = []
    if types:
        q += " AND e.entity_type IN (%s)" % ",".join("?" * len(types))
        params.extend(types)
    q += " ORDER BY (e.entity_type='internal') DESC, e.entity_type, e.name"
    return conn.execute(q, params).fetchall()


def list_customers(conn):
    """للشاشات التجارية: **كل الجهات المسجّلة بلا استثناء**.

    استبعاد الموظفين والعمال كان يمنع حالة واقعية: موظف بالإدارة يأخذ
    طقماً فيُسجَّل على حسابه الشخصي — وهي عملية سليمة محاسبياً (مدين
    الموظف / دائن الذهب المشغول) تُسدَّد لاحقاً من راتبه أو نقداً.

    فمنعها يدفع المستخدم لتسجيلها على عميل وهمي — وهو تشويه للدفاتر
    أسوأ من السماح بها.
    """
    return list_entities(conn, ("customer", "supplier", "partner",
                                "employee", "worker", "other", "internal"))


def get_entity(conn, entity_id):
    return conn.execute("SELECT * FROM entities WHERE id=?", (entity_id,)).fetchone()


def get_customer(conn, entity_id):
    return get_entity(conn, entity_id)


def balances(conn, entity_id):
    e = get_entity(conn, entity_id)
    if not e:
        raise ValueError("الجهة غير موجودة")
    return account_balance(conn, e["account_id"])


def capital_balance(conn, entity_id):
    e = get_entity(conn, entity_id)
    if not e or not e["capital_account_id"]:
        return (0.0, 0.0)
    return account_balance(conn, e["capital_account_id"])


def partners_share_total(conn):
    r = conn.execute(
        "SELECT COALESCE(SUM(share_percent),0) v FROM entities"
        " WHERE entity_type='partner' AND is_deleted=0").fetchone()
    return round(r["v"], 2)


def can_delete(conn, entity_id) -> bool:
    """يمنع حذف جهة لها رصيد قائم أو حركات (عدا قيد رصيدها الافتتاحي)."""
    e = get_entity(conn, entity_id)
    if not e:
        return False
    accs = [e["account_id"]]
    if e["capital_account_id"]:
        accs.append(e["capital_account_id"])
    for aid in accs:
        used = conn.execute(
            "SELECT 1 FROM journal_lines l JOIN journal_entries j"
            " ON j.id=l.entry_id WHERE l.account_id=? AND j.is_deleted=0"
            " AND j.id IS NOT ? LIMIT 1",
            (aid, e["opening_entry_id"])).fetchone()
        if used:
            return False
    return True


def delete_entity(conn, entity_id, username) -> None:
    if not can_delete(conn, entity_id):
        raise ValueError("لا يمكن حذف جهة لها حركات أو رصيد قائم")
    e = get_entity(conn, entity_id)
    if e["opening_entry_id"]:
        conn.execute("UPDATE journal_entries SET is_deleted=1 WHERE id=?",
                     (e["opening_entry_id"],))
    if e["employee_id"]:
        conn.execute("UPDATE employees SET is_deleted=1 WHERE id=?",
                     (e["employee_id"],))
    conn.execute("UPDATE entities SET is_deleted=1 WHERE id=?", (entity_id,))
    log_action(conn, username, "soft_delete", "entities", entity_id, "")


INTERNAL_COUNTERPARTIES = [
    ("خزينة التصنيع (تحويل داخلي / إعادة تشغيل)", "1100"),
]


def ensure_internal_counterparties(conn, username=None) -> None:
    """أطراف التحويل الداخلي — تشير لحساب قائم فعلاً (آمنة للتكرار)."""
    for name, code in INTERNAL_COUNTERPARTIES:
        acc = conn.execute("SELECT id FROM accounts WHERE code=?", (code,)).fetchone()
        if not acc:
            continue
        # يفحص الوجود بما فيه المحذوف: إعادة إنشاء حساب داخلي
        # مرتبط بحساب قائم تُنتج تكراراً في الشجرة.
        if conn.execute(
                "SELECT 1 FROM entities WHERE entity_type='internal'"
                " AND account_id=?", (acc["id"],)).fetchone():
            continue
        conn.execute(
            "INSERT INTO entities(name,entity_type,account_id,is_internal,created_by)"
            " VALUES(?,'internal',?,1,?)", (name, acc["id"], username))


def accrued_account_id(conn, entity_row):
    """حساب مستحقات الموظف (الطرف الدائن لقيد الاستحقاق)."""
    return entity_row["capital_account_id"] if entity_row else None


def ensure_employee_accrual_accounts(conn, username="system"):
    """يستكمل حساب المستحقات للموظفين المُكوَّدين قبل هذه النسخة، دون
    المساس بأي رصيد قائم — الحساب يُنشأ فارغاً ويستقبل الاستحقاق التالي."""
    rows = conn.execute(
        "SELECT * FROM entities WHERE entity_type='employee' AND is_deleted=0"
        " AND (capital_account_id IS NULL OR capital_account_id=0)").fetchall()
    made = 0
    for r in rows:
        acc = _create_sub_account(
            conn, EMPLOYEE_ACCRUED_PARENT, f"مستحقات الموظف: {r['name']}",
            "liability", "cash")
        conn.execute("UPDATE entities SET capital_account_id=? WHERE id=?",
                     (acc, r["id"]))
        made += 1
    return made
