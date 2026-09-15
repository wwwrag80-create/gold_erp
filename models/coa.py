# -*- coding: utf-8 -*-
"""شجرة الحسابات الديناميكية (Dynamic Chart of Accounts).

مصدر الحقيقة الوحيد هو جدول `accounts`، ويُعرَض بالمسميات القياسية
عبر المنظور `accounts_tree`:

    account_id · account_code · account_name · parent_id ·
    account_type · account_nature · is_transactional ·
    account_level · measurement_type · is_active · system_tag

القواعد المحاسبية المطبَّقة:

* **الوراثة**: الحساب الفرعي يرث نوع الأب وطبيعته ونوع قياسه آلياً،
  فلا يُطلب من المستخدم سوى الاسم — منعاً للأخطاء المحاسبية.
* **الترميز الآلي**: كود الابن يُشتق من كود الأب تسلسلياً.
* **الحساب الأب يصبح تجميعياً**: بمجرد أن يصير له أبناء يتوقف عن قبول
  الحركات المباشرة (ما لم تكن له حركة تاريخية فعلية).
* **منع الحذف الآمن**: أي حساب له حركة أو أبناء لا يُحذف إطلاقاً —
  يُجمَّد بدلاً من ذلك حفاظاً على توازن الدفاتر.
* **الوسم النظامي**: العمليات الآلية تصل إلى حساباتها عبر وسم ثابت
  (VAT_PAYABLE، GOLD_LOSS...) لا عبر رقم حساب مكتوب في الكود.
"""
from services.audit import log_action

TYPE_LABELS = {"asset": "أصول", "liability": "خصوم", "equity": "حقوق ملكية",
               "revenue": "إيرادات", "expense": "مصروفات",
               "bridge": "حساب وسيط"}
NATURE_LABELS = {"debit": "مدين", "credit": "دائن"}
MEASURE_LABELS = {"cash": "نقد فقط (CASH_ONLY)",
                  "gold": "ذهب فقط (GOLD_ONLY)",
                  "both": "نقد وذهب (BOTH)"}
MEASURE_ENUM = {"cash": "CASH_ONLY", "gold": "GOLD_ONLY", "both": "BOTH"}


def get_account(conn, account_id):
    return conn.execute("SELECT * FROM accounts WHERE id=?",
                        (account_id,)).fetchone()


def by_tag(conn, tag):
    """يعيد رقم الحساب الموسوم نظامياً (أو None إن لم يُوسم بعد)."""
    r = conn.execute("SELECT id FROM accounts WHERE system_tag=?",
                     (tag,)).fetchone()
    return r["id"] if r else None


def set_tag(conn, account_id, tag, username="system"):
    """يربط وسماً نظامياً بحساب — الوسم فريد على مستوى النظام."""
    tag = (tag or "").strip().upper() or None
    if tag:
        other = conn.execute(
            "SELECT id, name FROM accounts WHERE system_tag=? AND id<>?",
            (tag, account_id)).fetchone()
        if other:
            raise ValueError(
                f"الوسم «{tag}» مرتبط مسبقاً بالحساب «{other['name']}»")
    conn.execute("UPDATE accounts SET system_tag=? WHERE id=?",
                 (tag, account_id))
    log_action(conn, username, "update", "accounts", account_id,
               f"system_tag={tag}")


def tree_rows(conn, include_inactive=True):
    """كل الحسابات مرتبة هرمياً للعرض في QTreeView."""
    q = ("SELECT id, code, name, parent_id, type, nature, is_postable,"
         " account_level, balance_type, is_active, system_tag"
         " FROM accounts")
    if not include_inactive:
        q += " WHERE is_active=1"
    return conn.execute(q + " ORDER BY code").fetchall()


def has_movement(conn, account_id, live_only=True):
    """هل للحساب حركة في القيود؟

    `live_only=True` (الافتراضي) يتجاهل القيود المحذوفة منطقياً —
    فالحساب الذي حُذفت كل حركاته لم يعد له أثر في أي ميزان، ومنعه من
    الحذف بسببها حبسٌ بلا سبب.

    `live_only=False` يشمل المحذوف — يُستخدم عند الحاجة لمعرفة إن كان
    للحساب تاريخ أصلاً (لأغراض التدقيق).
    """
    q = ("SELECT 1 FROM journal_lines l"
         " JOIN journal_entries e ON e.id=l.entry_id"
         " WHERE l.account_id=?")
    if live_only:
        q += " AND e.is_deleted=0"
    return conn.execute(q + " LIMIT 1", (account_id,)).fetchone() is not None


def child_count(conn, account_id):
    return conn.execute(
        "SELECT COUNT(*) c FROM accounts WHERE parent_id=?",
        (account_id,)).fetchone()["c"]


def next_child_code(conn, parent_id):
    """الترميز الآلي: يشتق كود الابن من كود الأب.

    * إن كان للأب أبناء بالفعل، يواصل تسلسلهم بنفس طولهم
      (1600 → 1601، 1602...).
    * إن لم يكن له أبناء، يبدأ بلاحقة من خانتين (112 → 11201).
    """
    parent = get_account(conn, parent_id)
    if not parent:
        raise ValueError("الحساب الأب غير موجود")
    pcode = parent["code"]
    kids = [r["code"] for r in conn.execute(
        "SELECT code FROM accounts WHERE parent_id=? ORDER BY code",
        (parent_id,))]
    same = [k for k in kids if k.startswith(pcode) and len(k) > len(pcode)
            and k[len(pcode):].isdigit()]
    if same:
        width = len(same[-1]) - len(pcode)
        nxt = max(int(k[len(pcode):]) for k in same) + 1
        cand = f"{pcode}{str(nxt).zfill(width)}"
    else:
        cand = f"{pcode}01"
    while conn.execute("SELECT 1 FROM accounts WHERE code=?",
                       (cand,)).fetchone():
        cand = str(int(cand) + 1)
    return cand


def add_sub_account(conn, parent_id, name, username, measurement=None):
    """يضيف حساباً فرعياً يرث نوع الأب وطبيعته آلياً.

    لا يُطلب من المستخدم سوى الاسم؛ ونوع القياس يرث الأب أيضاً ما لم
    يُحدَّد صراحةً."""
    name = (name or "").strip()
    if not name:
        raise ValueError("أدخل اسم الحساب")
    parent = get_account(conn, parent_id)
    if not parent:
        raise ValueError("اختر الحساب الأب")
    if not parent["is_active"]:
        raise ValueError("لا يمكن الإضافة تحت حساب مجمَّد — نشِّطه أولاً")
    dup = conn.execute(
        "SELECT 1 FROM accounts WHERE parent_id=? AND name=?",
        (parent_id, name)).fetchone()
    if dup:
        raise ValueError(f"يوجد حساب فرعي بنفس الاسم تحت «{parent['name']}»")
    code = next_child_code(conn, parent_id)
    level = (parent["account_level"] or 1) + 1
    cur = conn.execute(
        "INSERT INTO accounts(code,name,type,parent_id,is_postable,nature,"
        "balance_type,account_level,is_active) VALUES(?,?,?,?,1,?,?,?,1)",
        (code, name, parent["type"], parent_id, parent["nature"],
         measurement or parent["balance_type"], level))
    new_id = cur.lastrowid
    # الأب صار تجميعياً — يتوقف عن قبول الحركات ما لم تكن له حركة سابقة
    if not has_movement(conn, parent_id):
        conn.execute("UPDATE accounts SET is_postable=0 WHERE id=?",
                     (parent_id,))
    log_action(conn, username, "create", "accounts", new_id,
               f"{code} — {name} تحت {parent['code']}")
    return {"id": new_id, "code": code, "name": name, "level": level,
            "type": parent["type"], "nature": parent["nature"],
            "measurement": measurement or parent["balance_type"]}


def rename_account(conn, account_id, new_name, username):
    new_name = (new_name or "").strip()
    if not new_name:
        raise ValueError("أدخل الاسم الجديد")
    acc = get_account(conn, account_id)
    if not acc:
        raise ValueError("الحساب غير موجود")
    # `name_locked` يحمي الاسم من الفرض القياسي عند كل إقلاع
    conn.execute("UPDATE accounts SET name=?, name_locked=1 WHERE id=?",
                 (new_name, account_id))

    # ══ مزامنة اسم الجهة المرتبطة ══
    # اسم الجهة يُخزَّن في `entities.name` أيضاً، وهو ما تقرأه أرصدة
    # الأستاذ المساعد والكشوف المجمّعة. تركه بلا تحديث يجعل الاسم
    # القديم يظهر هناك بينما الجديد في دفتر الأستاذ — تناقض يربك
    # المستخدم ويطعن في مصداقية النظام.
    # يشمل المحذوف عمداً: الجهة المحذوفة منطقياً قد تُستعاد لاحقاً،
    # فاسمها يجب أن يبقى متسقاً مع حسابها.
    ent = conn.execute(
        "SELECT id, name, entity_type FROM entities"
        " WHERE account_id=? OR capital_account_id=?",
        (account_id, account_id)).fetchone()
    if ent:
        # البادئة الوصفية («عميل: » مثلاً) تُزال من اسم الجهة
        clean = new_name
        for pre in ("عميل: ", "مورد: ", "موظف: ", "عامل: ", "أخرى: ",
                    "شريك: ", "مستحقات الموظف: ", "مستحقات العامل: ",
                    "رأس مال الشريك: ", "جاري الشريك: "):
            if clean.startswith(pre):
                clean = clean[len(pre):]
                break
        if clean and clean != ent["name"]:
            conn.execute("UPDATE entities SET name=? WHERE id=?",
                         (clean, ent["id"]))
            # وحسابات الجهة الأخرى (المستحقات مثلاً) تتبع الاسم نفسه
            for col, pre in (("account_id", None),
                             ("capital_account_id", None)):
                pass
            # سجل الموظف/العامل إن وُجد
            try:
                conn.execute(
                    "UPDATE employees SET name=? WHERE id="
                    " (SELECT employee_id FROM entities WHERE id=?)",
                    (clean, ent["id"]))
            except Exception:
                pass

    log_action(conn, username, "update", "accounts", account_id,
               f"rename «{acc['name']}» → «{new_name}»")
    return new_name


def set_active(conn, account_id, active, username):
    """تجميد الحساب أو تنشيطه — البديل الآمن عن الحذف."""
    acc = get_account(conn, account_id)
    if not acc:
        raise ValueError("الحساب غير موجود")
    active = 1 if active else 0
    if not active and child_count(conn, account_id):
        kids = conn.execute(
            "SELECT COUNT(*) c FROM accounts WHERE parent_id=? AND is_active=1",
            (account_id,)).fetchone()["c"]
        if kids:
            raise ValueError(
                "لا يمكن تجميد حساب له حسابات فرعية نشطة — جمِّد الفروع أولاً")
    conn.execute("UPDATE accounts SET is_active=? WHERE id=?",
                 (active, account_id))
    log_action(conn, username, "update", "accounts", account_id,
               "activate" if active else "freeze")
    return bool(active)


def delete_account(conn, account_id, username):
    """حذف حساب — ممنوع تماماً إن كانت له أي حركة أو فروع أو وسم نظامي."""
    acc = get_account(conn, account_id)
    if not acc:
        raise ValueError("الحساب غير موجود")
    if has_movement(conn, account_id):
        raise ValueError(
            f"لا يمكن حذف الحساب «{acc['name']}» — توجد حركات محاسبية "
            "سارية مرتبطة به.\nجمِّد الحساب بدلاً من حذفه للحفاظ على "
            "توازن الدفاتر وسلامة القيود التاريخية.")
    # ══ تنظيف القيود المحذوفة منطقياً ══
    # نحذف **القيد كاملاً بكل أطرافه** لا سطر الحساب وحده — حذف طرف
    # واحد يترك الطرف المقابل وحيداً فيختل ميزان القيود كلها.
    dead = [r["id"] for r in conn.execute(
        "SELECT DISTINCT e.id FROM journal_entries e"
        " JOIN journal_lines l ON l.entry_id=e.id"
        " WHERE l.account_id=? AND e.is_deleted=1", (account_id,))]
    if dead:
        qs = ",".join("?" * len(dead))
        for tbl in ("invoices", "vouchers", "purchases", "melting_ops",
                    "fixing_ops", "work_orders", "workshop_losses",
                    "payroll_ledger", "mfg_salaries", "shrinkage_ops"):
            try:
                conn.execute(f"UPDATE {tbl} SET entry_id=NULL"
                             f" WHERE entry_id IN ({qs})", dead)
            except Exception:
                pass
        conn.execute(f"DELETE FROM journal_lines WHERE entry_id IN ({qs})",
                     dead)
        conn.execute(f"DELETE FROM journal_entries WHERE id IN ({qs})",
                     dead)
    if child_count(conn, account_id):
        raise ValueError("لا يمكن حذف حساب له حسابات فرعية — احذف الفروع أولاً")
    if acc["system_tag"]:
        raise ValueError(
            f"الحساب موسوم نظامياً ({acc['system_tag']}) وتعتمد عليه عمليات "
            "آلية — جمِّده بدلاً من حذفه")
    linked = conn.execute(
        "SELECT 1 FROM entities WHERE (account_id=? OR capital_account_id=?)"
        " AND is_deleted=0 LIMIT 1", (account_id, account_id)).fetchone()
    if linked:
        raise ValueError("الحساب مرتبط بجهة تعامل مُكوَّدة — لا يمكن حذفه")
    conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
    log_action(conn, username, "delete", "accounts", account_id,
               f"{acc['code']} — {acc['name']}")
    return True


def transactional_accounts(conn):
    """الحسابات المتاحة لحقول الإدخال الذكية: فرعية تقبل الحركة ونشطة."""
    return conn.execute(
        "SELECT id, code, name, balance_type, system_tag FROM accounts"
        " WHERE is_postable=1 AND is_active=1 ORDER BY code").fetchall()


def measurement_of(conn, account_id):
    """نوع القياس: cash / gold / both — تُبنى عليه حقول السندات."""
    r = conn.execute("SELECT balance_type FROM accounts WHERE id=?",
                     (account_id,)).fetchone()
    return r["balance_type"] if r else "both"


def recompute_levels(conn):
    """يعيد حساب عمق كل حساب في الشجرة (1 رئيسي، 2 فرعي، 3 تحليلي...)."""
    rows = conn.execute("SELECT id, parent_id FROM accounts").fetchall()
    parent = {r["id"]: r["parent_id"] for r in rows}
    for aid in parent:
        lvl, cur, guard = 1, parent[aid], 0
        while cur and guard < 20:
            lvl += 1
            cur = parent.get(cur)
            guard += 1
        conn.execute("UPDATE accounts SET account_level=? WHERE id=?",
                     (lvl, aid))
    return len(rows)


def delete_subtree(conn, account_id, username, force=False):
    """يحذف حساباً **وكل فروعه** تحته.

    **الضمان المحاسبي**: الحذف مرفوض إن كان لأي حساب في الشجرة الفرعية
    حركة محاسبية — لأن حذفه يترك قيوداً معلّقة ويكسر الميزان. تُحذف
    الحسابات الفارغة وحدها، ومع `force` تُجمَّد ذوات الحركة بدل حذفها
    فلا يضيع أثرها المحاسبي.
    """
    acc = conn.execute("SELECT * FROM accounts WHERE id=?",
                       (account_id,)).fetchone()
    if not acc:
        raise ValueError("الحساب غير موجود")

    # كل الشجرة الفرعية (الأب وأبناؤه وأحفاده) — استعلام واحد
    from models.accounts import subtree_ids
    ids = subtree_ids(conn, account_id)

    qs = ",".join("?" * len(ids))
    moved = {r["account_id"] for r in conn.execute(
        f"SELECT DISTINCT l.account_id FROM journal_lines l"
        f" JOIN journal_entries e ON e.id=l.entry_id"
        f" WHERE e.is_deleted=0 AND l.account_id IN ({qs})", ids)}
    # الجهة المرتبطة **بلا حركة** تُحذف مع حسابها؛ أما ذات الحركة
    # فمحميّة لأن حذف حسابها يُيتّم قيودها.
    protected = set(moved)

    if protected and not force:
        names = [r["name"] for r in conn.execute(
            f"SELECT name FROM accounts WHERE id IN "
            f"({','.join('?' * len(protected))})", list(protected))][:5]
        raise ValueError(
            f"لا يمكن الحذف: {len(protected)} حساب في هذه الشجرة له حركة "
            f"محاسبية أو جهة مرتبطة.\n" + " · ".join(names)
            + "\n\nاستخدم خيار «تجميد ذوات الحركة» للحفاظ على الأثر.")

    frozen = deleted = 0
    # نحذف من الأعمق للأعلى فلا تنكسر روابط الأبناء
    for aid in reversed(ids):
        if aid in protected:
            conn.execute("UPDATE accounts SET is_active=0 WHERE id=?", (aid,))
            frozen += 1
            continue
        # جهة مرتبطة بلا حركة: تُحذف معه فلا يبقى مرجع معلّق
        try:
            conn.execute("DELETE FROM entities WHERE account_id=?", (aid,))
            conn.execute("DELETE FROM accounts WHERE id=?", (aid,))
            deleted += 1
        except Exception:
            # مرجع لا يُحل: نجمّده بدل كسر تكامل القاعدة
            conn.execute("UPDATE accounts SET is_active=0 WHERE id=?", (aid,))
            frozen += 1

    log_action(conn, username, "delete", "accounts", account_id,
               f"حذف شجرة «{acc['name']}»: {deleted} محذوف · "
               f"{frozen} مجمَّد (له حركة)")
    return {"root": acc["name"], "deleted": deleted, "frozen": frozen,
            "total": len(ids)}


def purge_account_tree(conn, account_id, username, confirm_text=""):
    """يحذف حساباً وكل فروعه **وحركاته المحاسبية** نهائياً.

    ⚠ إجراء لا رجعة فيه ويؤثر على الميزانية.

    **المنطق المحاسبي**: حذف حساب له حركة يترك قيوداً غير متوازنة —
    لذلك تُحذف **القيود كاملةً** (بكل أطرافها) لا أسطر الحساب وحدها.
    فيبقى كل قيد باقٍ متوازناً، وتتحدّث الميزانية تلقائياً بنقصان
    ما حُذف. أي مستند مصدري (فاتورة · سند) يُعلَّم محذوفاً كذلك،
    فلا يبقى مستند بلا قيد.
    """
    acc = conn.execute("SELECT code, name FROM accounts WHERE id=?",
                       (account_id,)).fetchone()
    if not acc:
        raise ValueError("الحساب غير موجود")
    if confirm_text.strip() != "حذف نهائي":
        raise ValueError(
            "للحذف النهائي اكتب عبارة التأكيد: حذف نهائي")

    # الشجرة الفرعية كاملة — استعلام واحد
    from models.accounts import subtree_ids
    ids = subtree_ids(conn, account_id)
    qs = ",".join("?" * len(ids))

    # القيود التي تمسّ أياً من هذه الحسابات
    entries = [r["entry_id"] for r in conn.execute(
        f"SELECT DISTINCT entry_id FROM journal_lines"
        f" WHERE account_id IN ({qs})", ids)]

    # ملاحظة: كل الاستعلامات التالية تشمل المحذوف عمداً — الحذف
    # النهائي يمسح السجل من الوجود، فترشيح `is_deleted` هنا يترك
    # سجلات محذوفة منطقياً معلّقة بلا حساب.
    docs = 0
    if entries:
        eq = ",".join("?" * len(entries))
        # المستندات المصدرية تُعلَّم محذوفة فلا تبقى بلا قيد
        for tbl in ("invoices", "vouchers", "purchases", "melting_ops",
                    "fixing_ops", "work_orders", "workshop_losses"):
            try:
                cur = conn.execute(
                    f"UPDATE {tbl} SET is_deleted=1"
                    f" WHERE entry_id IN ({eq})", entries)
                docs += cur.rowcount or 0
            except Exception:
                pass
        # نفصل مراجع المستندات عن القيود قبل حذفها، وإلا رفض القيد
        # المرجعي (FOREIGN KEY) الحذف.
        for tbl in ("invoices", "vouchers", "purchases", "melting_ops",
                    "fixing_ops", "work_orders", "workshop_losses",
                    "payroll_ledger", "mfg_salaries", "shrinkage_ops"):
            try:
                conn.execute(f"UPDATE {tbl} SET entry_id=NULL"
                             f" WHERE entry_id IN ({eq})", entries)
            except Exception:
                pass
        conn.execute(f"DELETE FROM journal_lines WHERE entry_id IN ({eq})",
                     entries)
        conn.execute(f"DELETE FROM journal_entries WHERE id IN ({eq})",
                     entries)

    # الجهات المرتبطة: نحذف ما يشير إليها أولاً ثم الجهة نفسها
    ent_ids = [r["id"] for r in conn.execute(
        f"SELECT id FROM entities WHERE account_id IN ({qs})", ids)]
    if ent_ids:
        eq2 = ",".join("?" * len(ent_ids))
        for tbl, col in (("invoice_items", None), ("invoices", "customer_id"),
                         ("voucher_lines", None), ("vouchers", "customer_id"),
                         ("purchases", "supplier_id"),
                         ("fixing_ops", "customer_id")):
            try:
                if col:
                    # أسطر المستند تُحذف بحذف رأسه (ON DELETE CASCADE
                    # غير مضمون)، فنحذفها صراحةً أولاً
                    if tbl == "invoices":
                        conn.execute(
                            f"DELETE FROM invoice_items WHERE invoice_id IN"
                            f" (SELECT id FROM invoices"
                            f"  WHERE {col} IN ({eq2}))", ent_ids)
                    elif tbl == "vouchers":
                        conn.execute(
                            f"DELETE FROM voucher_lines WHERE voucher_id IN"
                            f" (SELECT id FROM vouchers"
                            f"  WHERE {col} IN ({eq2}))", ent_ids)
                    conn.execute(f"DELETE FROM {tbl}"
                                 f" WHERE {col} IN ({eq2})", ent_ids)
            except Exception:
                pass
        try:
            conn.execute(f"DELETE FROM employees WHERE id IN"
                         f" (SELECT employee_id FROM entities"
                         f"  WHERE id IN ({eq2})"
                         f"    AND employee_id IS NOT NULL)", ent_ids)
        except Exception:
            pass
        conn.execute(f"DELETE FROM entities WHERE id IN ({eq2})", ent_ids)
    for aid in reversed(ids):
        try:
            conn.execute("DELETE FROM accounts WHERE id=?", (aid,))
        except Exception:
            conn.execute("UPDATE accounts SET is_active=0 WHERE id=?",
                         (aid,))

    log_action(conn, username, "purge", "accounts", account_id,
               f"حذف نهائي لشجرة «{acc['name']}»: {len(ids)} حساب · "
               f"{len(entries)} قيد · {docs} مستند")
    return {"root": acc["name"], "accounts": len(ids),
            "entries": len(entries), "docs": docs}
