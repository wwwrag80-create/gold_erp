# -*- coding: utf-8 -*-
"""شجرة الحسابات ومراكز التكلفة — دوال استعلام مشتركة."""


def acc_id(conn, code: str) -> int:
    row = conn.execute("SELECT id FROM accounts WHERE code=?", (code,)).fetchone()
    if not row:
        raise ValueError(f"حساب غير موجود في الشجرة: {code}")
    return row["id"]


def account_name(conn, account_id: int) -> str:
    row = conn.execute("SELECT code,name FROM accounts WHERE id=?", (account_id,)).fetchone()
    return f"{row['code']} — {row['name']}" if row else str(account_id)


def list_postable(conn):
    """الحسابات المتاحة لحقول الإدخال في كل الشاشات: تقرأ مباشرة من
    شجرة الحسابات — فرعية تقبل الحركة (is_transactional) ونشطة غير
    مجمَّدة (is_active). أي حساب يُضاف في الشجرة يظهر هنا فوراً."""
    return conn.execute(
        "SELECT id, code, name, balance_type FROM accounts"
        " WHERE is_postable=1 AND is_active=1 ORDER BY code").fetchall()


def list_tree(conn):
    return conn.execute(
        "SELECT id, code, name, type, parent_id, is_postable FROM accounts ORDER BY code").fetchall()


def subtree_ids(conn, root_id):
    """معرّفات الحساب وكل فروعه وأحفاده — باستعلام **واحد**.

    كان كل موضع يمشي الشجرة باستعلام لكل عقدة. الحساب التجميعي
    للعملاء وحده قد يضمّ مئات الفروع، فتُنفَّذ مئات الاستعلامات في كل
    تحديث للوحة التحكم — وهذا ما يجعل النظام يبطؤ مع نموّ عدد
    العملاء لا مع حجم العمل. استعلام CTE تكراري واحد يكفي.

    `LIMIT 5000` و`depth` حارسان: لو وُجدت حلقة في الشجرة (حساب أبوه
    أحد أحفاده) لدار الاستعلام بلا نهاية وتجمّد النظام.
    """
    rows = conn.execute(
        "WITH RECURSIVE sub(id, depth) AS ("
        "  SELECT id, 0 FROM accounts WHERE id=?"
        "  UNION"
        "  SELECT a.id, s.depth+1 FROM accounts a"
        "   JOIN sub s ON a.parent_id=s.id WHERE s.depth < 20"
        ") SELECT id FROM sub LIMIT 5000", (root_id,)).fetchall()
    return [r["id"] for r in rows]


def subtree_ids_by_code(conn, code):
    """كسابقتها لكن بكود الحساب. تعيد [] إن لم يوجد."""
    row = conn.execute("SELECT id FROM accounts WHERE code=?",
                       (code,)).fetchone()
    return subtree_ids(conn, row["id"]) if row else []


# ══════════════════════════════════════════════════════════════════
#  مخازن الذهب — «من أي حساب يخرج؟» و«إلى أي حساب يدخل؟»
# ------------------------------------------------------------------
#  الفاتورة تُخرج ذهباً من مخزن، ودفعة التوريد تُدخله إلى مخزن.
#  وكلاهما كان حساباً واحداً مكتوباً في الكود (1200 الذهب المشغول)،
#  فمن باع من صندوق الكسر أو ورّد إليه احتاج قيداً يدوياً بعدها
#  يُصحّح المخزن — قيدٌ يُنسى فيختلّ الصندوقان بلا أثرٍ في الميزان.
#
#  المسموح هنا: كل حسابٍ **قابل للترحيل** تحت مجموعة الذهب والمخازن
#  (1020). لا حساب عميلٍ ولا صندوق نقدٍ ولا مصروف — فالبضاعة تدخل
#  مخزناً وتخرج منه، لا من ذمّة.
#
#  وهذه الدوال هنا لا في `invoices` ولا في `inventory`: الاثنان
#  يستعملانها، و`invoices` يستورد `inventory` — فوضعها في أيٍّ منهما
#  يصنع استيراداً دائرياً. و`accounts` أسفل الجميع.
# ══════════════════════════════════════════════════════════════════
GOLD_GROUP = "1020"              # الأصول المتداولة — الذهب والمخازن
FINISHED_GOLD = "1200"           # الذهب المشغول (بضاعة تامة)
SCRAP_BOX = "1310"               # صندوق الكسر (18 · 21 · 22 · 24)


def gold_accounts(conn):
    """مخازن الذهب المتاحة للاختيار — من الشجرة لا من قائمةٍ في الكود.

    فالحساب الذي يضيفه المصنع اليوم يظهر في القوائم فوراً بلا تعديل
    برنامج.
    """
    ids = subtree_ids_by_code(conn, GOLD_GROUP)
    if not ids:
        return []
    qs = ",".join("?" * len(ids))
    return conn.execute(
        f"SELECT id, code, name, balance_type FROM accounts"
        f" WHERE id IN ({qs}) AND is_postable=1 AND is_active=1"
        f" ORDER BY code", ids).fetchall()


def is_scrap_account(conn, account_id):
    """هل هذا الحساب صندوق الكسر؟ — فيلزم بيان العيار المخصوم منه."""
    if not account_id:
        return False
    r = conn.execute("SELECT code FROM accounts WHERE id=?",
                     (account_id,)).fetchone()
    return bool(r) and r["code"] == SCRAP_BOX


def resolve_gold_account(conn, account_id=None, default_code=FINISHED_GOLD,
                         verb="يخرج منه"):
    """يتحقق من مخزن الذهب ويعيده — وبلا اختيارٍ يعيد الافتراضي.

    التحقق هنا لا في الشاشة: أي طريقٍ يصل إلى الترحيل (استيراد،
    تحويل مستند، اختبار) يمرّ من هنا، فلا يُرحَّل ذهبٌ على حساب
    مصروفاتٍ أو ذمّةِ عميلٍ بحال.
    """
    default_id = acc_id(conn, default_code)
    if not account_id or int(account_id) == int(default_id):
        return default_id
    allowed = {r["id"] for r in gold_accounts(conn)}
    if int(account_id) not in allowed:
        r = conn.execute("SELECT code, name FROM accounts WHERE id=?",
                         (account_id,)).fetchone()
        raise ValueError(
            f"لا يصلح حساباً {verb} ذهب العملية: "
            + (f"{r['code']} — {r['name']}" if r else str(account_id))
            + "\n\nالمسموح: الحسابات القابلة للترحيل تحت مجموعة الذهب "
              "والمخازن (خزينة التصنيع · الذهب المشغول · صندوق الكسر · "
              "وما يُضاف تحتها).")
    return int(account_id)


