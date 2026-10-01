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
                    "payroll_ledger", "mfg_salaries", "shrinkage_ops",
                    "tax_sales"):
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
                    "fixing_ops", "work_orders", "workshop_losses",
                    "tax_sales"):
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
                    "payroll_ledger", "mfg_salaries", "shrinkage_ops",
                    "tax_sales"):
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
                         ("tax_sales", "customer_id"),
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
                    elif tbl == "tax_sales":
                        conn.execute(
                            f"DELETE FROM tax_sale_lines WHERE sale_id IN"
                            f" (SELECT id FROM tax_sales"
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


def group_own_balance(conn, account_id):
    """رصيد الحركة المباشرة على حسابٍ (دون فروعه) — (نقد، ذهب)."""
    r = conn.execute(
        "SELECT COALESCE(SUM(l.cash_debit-l.cash_credit),0) c,"
        " COALESCE(SUM(l.gold_debit-l.gold_credit),0) g"
        " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
        " AND e.is_deleted=0 WHERE l.account_id=?", (account_id,)).fetchone()
    return round(r["c"] or 0.0, 2), round(r["g"] or 0.0, 3)


def reclass_group_balance(conn, group_id, child_id, entry_date, username):
    """ينقل الرصيد المباشر لحسابٍ تجميعي إلى أحد فروعه بقيد تسوية.

    علاجُ ما يُنبّه إليه فحص السلامة («حساب تجميعي عليه حركة مباشرة»):
    رصيد المجموعة يختلط بفروعها فلا يعرف المراجع ما فيها. القيد: مدين
    الفرع / دائن المجموعة (أو العكس) بالنقد والذهب معاً — فيصير رصيد
    المجموعة المباشر صفراً ويظهر كلّه في الفرع. وسجلّ الأصول الثابتة
    المسجَّل على المجموعة يُنقل إلى الفرع معه.
    """
    from services.accounting_engine import post_entry
    from services.audit import log_action
    grp = get_account(conn, group_id)
    child = get_account(conn, child_id)
    if not grp or not child:
        raise ValueError("الحساب غير موجود")
    if child["parent_id"] != grp["id"]:
        raise ValueError("اختر فرعاً مباشراً من فروع المجموعة")
    if not child["is_postable"]:
        raise ValueError("الفرع المختار تجميعي — اختر حساباً يقبل الحركة")
    c, g = group_own_balance(conn, group_id)
    if abs(c) < 0.005 and abs(g) < 0.0005:
        raise ValueError("لا رصيد مباشر على المجموعة لنقله")
    desc = f"إعادة تبويب: نقل رصيد {grp['code']} إلى فرعه {child['code']}"
    to_child = {"account_id": child_id, "line_desc": desc}
    from_grp = {"account_id": group_id, "line_desc": desc}
    for amt, dr, cr in ((c, "cash_debit", "cash_credit"),
                        (g, "gold_debit", "gold_credit")):
        if abs(amt) < (0.005 if dr.startswith("cash") else 0.0005):
            continue
        if amt > 0:
            to_child[dr] = abs(amt)
            from_grp[cr] = abs(amt)
        else:
            to_child[cr] = abs(amt)
            from_grp[dr] = abs(amt)
    eid = post_entry(conn, entry_date, desc, [to_child, from_grp],
                     source_table="manual", username=username, note=desc)
    try:
        conn.execute("UPDATE fixed_assets SET account_id=? WHERE account_id=?",
                     (child_id, group_id))
    except Exception:
        pass
    log_action(conn, username, "update", "accounts", group_id,
               f"reclass {grp['code']} → {child['code']}: {c} / {g}")
    return eid


def child_count_safe(account_id):
    """عدد فروع حساب — باتصال قراءةٍ خاص (لقائمة الفأرة)."""
    from database.database import db
    try:
        with db(readonly=True) as conn:
            return child_count(conn, account_id)
    except Exception:
        return 0


# ══════════════════════════════════════════════════════════════════
#  نقل حسابٍ تحت أبٍ آخر (4.45)
# ══════════════════════════════════════════════════════════════════
#
# الحساب ينتقل **بمعرّفه** — فقيوده كلها تنتقل معه كما هي، ولا يُمسّ
# رصيدٌ ولا مستند. الذي يتغيّر مكانه في الشجرة، وبه نهجه المحاسبي:
#   • النوع والطبيعة يرثهما من أبيه الجديد (كما يرث الحساب المُنشأ
#     تحته) — فحسابٌ نُقل من المصروفات الإدارية إلى مواد التشغيل يظهر
#     في بندها من قائمة الدخل، ومن الأصول إلى الخصوم يظهر في الميزانية
#     مطلوباً لا أصلاً. والحساب المقابل (طبيعته عكس أبيه) يبقى مقابلاً.
#   • نوع القياس (نقد/ذهب) يبقى له — فهو صفة حركته لا مكانه.
#   • الكود يبقى كما هو افتراضاً، ويُعاد ترقيمه تحت الأب الجديد عند
#     الطلب (إلا الحسابات التي يقرؤها النظام بكودها).
#   • يُوسم «منقولاً بيد المستخدم» فلا تُعيده الهيكلة القياسية عند
#     الإقلاع إلى مكانه القديم.
#
# الضوابط: لا يُنقل حسابٌ رئيسي (جذر)، ولا تحت نفسه أو أحد فروعه
# (حلقة)، ولا تحت حسابِ حركةٍ عليه قيود (فيختلط رصيده المباشر بأرصدة
# أبنائه). وحسابُ جهة تعامل يُنقل من هنا كغيره، ونوع الجهة يتبعه:
# تحت «إجمالي الموردين» تصير مورداً، وتحت «إجمالي العملاء» عميلاً.

def _subtree(conn, account_id):
    ids, frontier = [int(account_id)], [int(account_id)]
    while frontier:
        frontier = [r["id"] for r in conn.execute(
            "SELECT id FROM accounts WHERE parent_id IN (%s)"
            % ",".join("?" * len(frontier)), frontier)]
        ids += frontier
    return ids


def _root(conn, account_id):
    cur, guard = get_account(conn, account_id), 0
    while cur is not None and cur["parent_id"] and guard < 30:
        cur = get_account(conn, cur["parent_id"])
        guard += 1
    return cur


def _program_codes():
    """أكواد يقرؤها البرنامج بكودها — لا يُعاد ترقيمها."""
    try:
        from database.seed import ACCOUNTS
        return {a[0] for a in ACCOUNTS}
    except Exception:
        return set()


def move_targets(conn, account_id):
    """الآباء الممكنون: كل حسابٍ نشط ليس الحساب ولا من فروعه، وليس
    حسابَ حركةٍ عليه قيود. يعيد (id, code, name, type, is_postable)."""
    sub = set(_subtree(conn, account_id))
    acc = get_account(conn, account_id)
    out = []
    for r in conn.execute(
            "SELECT id, code, name, type, is_postable, parent_id"
            " FROM accounts WHERE is_active=1 ORDER BY code"):
        if r["id"] in sub or (acc and r["id"] == acc["parent_id"]):
            continue
        if r["is_postable"] and has_movement(conn, r["id"], live_only=False):
            continue
        out.append(r)
    return out


def move_account(conn, account_id, new_parent_id, username, recode=False,
                 entity_ok=False):
    acc = get_account(conn, account_id)
    if not acc:
        raise ValueError("الحساب غير موجود")
    if not acc["parent_id"]:
        raise ValueError(f"«{acc['code']} — {acc['name']}» حسابٌ رئيسي في"
                         " رأس الشجرة — لا يُنقل")
    par = get_account(conn, new_parent_id)
    if not par:
        raise ValueError("اختر الحساب الذي يُنقل تحته")
    if not par["is_active"]:
        raise ValueError(f"«{par['name']}» مجمَّد — نشِّطه أولاً")
    if int(par["id"]) == int(acc["parent_id"]):
        raise ValueError(f"الحساب تحت «{par['name']}» أصلاً")
    sub = _subtree(conn, account_id)
    if int(par["id"]) in sub:
        raise ValueError("لا يُنقل الحساب تحت نفسه أو تحت أحد فروعه")
    if par["is_postable"] and has_movement(conn, par["id"], live_only=False):
        raise ValueError(
            f"«{par['code']} — {par['name']}» حسابُ حركةٍ عليه قيود — لا "
            "يصير أباً لحساب آخر: يختلط رصيده المباشر بأرصدة أبنائه فلا "
            "يُقرأ أيٌّ منهما. اختر حساباً تجميعياً (رئيسياً).")
    old_root, new_root = _root(conn, acc["id"]), _root(conn, par["id"])
    cross = (old_root and new_root and old_root["id"] != new_root["id"])
    # 4.46: لا رفض هنا لحساب جهةٍ أو حسابٍ نظامي — النقل قرارُ المحاسب.
    # حسابُ الجهة يتبعه نوعها بحسب مجموعته الجديدة (بعد النقل أدناه)،
    # والحساب النظامي يبقى بكوده ووسمه فتصله العمليات الآلية كما كانت.
    # الطبيعة: يرثها من أبيه الجديد؛ والحساب المقابل (عكس أبيه) يبقى عكسه
    old_par = get_account(conn, acc["parent_id"])
    contra = old_par is not None and acc["nature"] != old_par["nature"]
    flip = {"debit": "credit", "credit": "debit"}
    new_nature = flip[par["nature"]] if contra else par["nature"]
    for aid in sub:
        r = get_account(conn, aid)
        n = new_nature if r["nature"] == acc["nature"] else flip[new_nature]
        conn.execute("UPDATE accounts SET type=?, nature=? WHERE id=?",
                     (par["type"], n, aid))
    old_code = acc["code"]
    new_code = old_code
    if recode:
        prog = _program_codes()
        q = ",".join("?" * len(sub))
        bad = conn.execute(
            f"SELECT code FROM accounts WHERE id IN ({q}) AND"
            " COALESCE(system_tag,'')<>''", sub).fetchone()
        if bad or any(get_account(conn, a)["code"] in prog for a in sub):
            raise ValueError(
                "حسابٌ يقرؤه النظام بكوده لا يُعاد ترقيمه — يُنقل بكوده"
                " كما هو (ألغِ «إعادة الترقيم»)")
        new_code = next_child_code(conn, par["id"])
        for aid in sub[1:]:
            c = get_account(conn, aid)["code"]
            if c.startswith(old_code):
                cand = new_code + c[len(old_code):]
                if not conn.execute("SELECT 1 FROM accounts WHERE code=?",
                                    (cand,)).fetchone():
                    conn.execute("UPDATE accounts SET code=? WHERE id=?",
                                 (cand, aid))
    conn.execute("UPDATE accounts SET parent_id=?, code=?, parent_locked=1"
                 " WHERE id=?", (par["id"], new_code, acc["id"]))
    # الأب الجديد صار تجميعياً؛ والقديم إن خلا من الأبناء ولا حركة له
    # يعود حساب حركة فلا يبقى مجموعةً فارغة لا تقبل شيئاً
    if par["is_postable"]:
        conn.execute("UPDATE accounts SET is_postable=0 WHERE id=?",
                     (par["id"],))
    if old_par is not None and not child_count(conn, old_par["id"]) \
            and old_par["parent_id"] \
            and not has_movement(conn, old_par["id"], live_only=False):
        conn.execute("UPDATE accounts SET is_postable=1 WHERE id=?",
                     (old_par["id"],))
    recompute_levels(conn)
    # حسابُ جهة تعامل: نوعها يتبع مجموعته الرقابية الجديدة (عميل/مورد/
    # جهة أخرى) — فلا تبقى «عميلاً» وحسابها بين الموردين
    synced = []
    try:
        from models import entities as _ents
        synced = _ents.sync_types_from_tree(conn, sub, username)
    except Exception:
        synced = []
    msg = (f"نقل {old_code} — {acc['name']}: من {old_par['code'] if old_par else '—'}"
           f" إلى {par['code']} — {par['name']}"
           + (f" · الكود {old_code} ← {new_code}" if new_code != old_code
              else "")
           + (f" · النوع {TYPE_LABELS.get(acc['type'])} ← "
              f"{TYPE_LABELS.get(par['type'])}" if cross else "")
           + "".join(f" · الجهة «{n}»: {a} ← {b}" for n, a, b in synced))
    log_action(conn, username, "update", "accounts", acc["id"], msg)
    return {"id": acc["id"], "old_code": old_code, "code": new_code,
            "parent": f"{par['code']} — {par['name']}",
            "type": par["type"], "nature": new_nature,
            "moved": len(sub), "cross": bool(cross), "message": msg,
            "entities": synced}
