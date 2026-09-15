# -*- coding: utf-8 -*-
"""
محرك القيود المزدوجة ثنائي البعد — قلب النظام.

كل سطر قيد: (حساب، مركز تكلفة اختياري، مدين ذهب، دائن ذهب، مدين نقد، دائن نقد).
الأوزان دائماً بمكافئ عيار 18. لا يُرحَّل قيد إلا إذا توازن الميزانان
(الوزني والنقدي) كلٌّ على حدة. كل الشاشات تمر من هنا حصراً.
"""
import config

GOLD_TOL = 0.011   # سماحية تقريب الأوزان (3 منازل)
CASH_TOL = 0.011   # سماحية تقريب المبالغ (منزلتان)


def _r3(x): return round(float(x or 0), config.WEIGHT_DECIMALS)
def _r2(x): return round(float(x or 0), config.CASH_DECIMALS)


_AMOUNT_KEYS = ("gold_debit", "gold_credit", "cash_debit", "cash_credit")


def validate_lines(lines):
    """يتحقق من توازن الميزانين ويعيد المجاميع، أو يرفع ValueError."""
    if not lines:
        raise ValueError("لا توجد أسطر في القيد")
    # قيمة سالبة في أي طرف تُوازن حسابياً لكنها تقلب معنى الحركة:
    # «مدين ‎−100» يظهر في الكشف كأنه دائن، ويُفسد أعمدة الميزان
    # وتقارير الأعمار. الصواب أن تُكتب في الطرف المقابل موجبةً.
    for i, l in enumerate(lines, 1):
        for k in _AMOUNT_KEYS:
            if float(l.get(k) or 0) < 0:
                raise ValueError(
                    f"السطر {i}: قيمة سالبة في «{k}» — اكتبها في الطرف "
                    "المقابل بقيمة موجبة بدل السالب")
        if not l.get("account_id"):
            raise ValueError(f"السطر {i}: بلا حساب")
    gd = sum(_r3(l.get("gold_debit")) for l in lines)
    gc = sum(_r3(l.get("gold_credit")) for l in lines)
    cd = sum(_r2(l.get("cash_debit")) for l in lines)
    cc = sum(_r2(l.get("cash_credit")) for l in lines)
    if gd + gc + cd + cc == 0:
        raise ValueError("القيد فارغ: كل القيم أصفار")
    if abs(gd - gc) > GOLD_TOL:
        raise ValueError(f"ميزان الذهب غير متوازن: مدين {gd:.2f} ≠ دائن {gc:.2f}")
    if abs(cd - cc) > CASH_TOL:
        raise ValueError(f"ميزان النقد غير متوازن: مدين {cd:.2f} ≠ دائن {cc:.2f}")
    return gd, gc, cd, cc


# بادئة رقم المستند بحسب نوع العملية
_DOC_PREFIX = {
    "invoices": "INV", "vouchers": "VCH", "work_orders": "PRD",
    "melting_ops": "MLT", "fixing_ops": "FIX", "purchases": "PUR",
    "payroll_ledger": "PAY", "mfg_salaries": "WSL", "shrinkage_ops": "SHR",
}


def _verify_entry_posted(conn, entry_id):
    """يتحقق أن القيد كُتب فعلاً ومتوازن — قبل إنهاء المعاملة.

    هذا خط الدفاع الأخير ضد «العملية تُحفظ بلا أثر محاسبي»: لو فشل
    كتابة الأسطر لأي سبب، تُرفع العملية كاملةً بدل بقاء مستند يتيم.
    """
    if not entry_id:
        raise RuntimeError("فشل ترحيل القيد المحاسبي — أُلغيت العملية")
    r = conn.execute(
        "SELECT COUNT(*) n,"
        " COALESCE(SUM(gold_debit),0) gd, COALESCE(SUM(gold_credit),0) gc,"
        " COALESCE(SUM(cash_debit),0) cd, COALESCE(SUM(cash_credit),0) cc"
        " FROM journal_lines WHERE entry_id=?", (entry_id,)).fetchone()
    if (r["n"] or 0) < 2:
        raise RuntimeError(
            f"القيد {entry_id} ناقص ({r['n']} سطر) — أُلغيت العملية")
    if abs(r["gd"] - r["gc"]) > GOLD_TOL:
        raise RuntimeError(
            f"ميزان الذهب غير متوازن بعد الترحيل "
            f"({r['gd']:.3f} ≠ {r['gc']:.3f}) — أُلغيت العملية")
    if abs(r["cd"] - r["cc"]) > CASH_TOL:
        raise RuntimeError(
            f"ميزان النقد غير متوازن بعد الترحيل "
            f"({r['cd']:.2f} ≠ {r['cc']:.2f}) — أُلغيت العملية")
    return True


def post_entry(conn, entry_date, description, lines,
               source_table=None, source_id=None, username=None, note=""):
    """ترحيل قيد متوازن ضمن معاملة conn المفتوحة، ويعيد رقم القيد.

    `description` وسم داخلي للتتبع فقط ولا يُعرض في كشوف الحساب.
    `note` هو «البيان» الحقيقي: لا يُملأ إلا بما يكتبه المستخدم صراحةً
    في الشاشة، ويبقى فارغاً فيما عدا ذلك."""
    validate_lines(lines)
    # قفل الفترات: لا يُرحَّل قيد بتاريخ داخل فترة أُقفلت
    from models import fiscal
    fiscal.assert_open(conn, entry_date)

    ids = sorted({int(l["account_id"]) for l in lines})
    qs = ",".join("?" * len(ids))
    accs = {r["id"]: r for r in conn.execute(
        f"SELECT id, code, name, is_active, is_postable"
        f" FROM accounts WHERE id IN ({qs})", ids)}
    for aid in ids:
        acc = accs.get(aid)
        if acc is None:
            raise ValueError(f"حساب غير موجود (id={aid}) — أُلغيت العملية")
        if not acc["is_active"]:
            raise ValueError(
                f"الحساب «{acc['name']}» مجمَّد — لا يقبل الحركات. "
                "نشِّطه من شاشة دليل الحسابات أو اختر حساباً آخر.")
        # الترحيل على حساب تجميعي (غير قابل للترحيل) يُضاعف الرصيد في
        # الميزان: مرةً بحركته المباشرة ومرةً بمجموع أبنائه — فتظهر
        # أرقام لا تُطابق أي كشف. هذا هو أخطر خلل صامت في شجرة
        # الحسابات، ومنعه من أصل التصميم أسلم من اكتشافه لاحقاً.
        if not acc["is_postable"]:
            raise ValueError(
                f"الحساب «{acc['code']} — {acc['name']}» حساب تجميعي "
                "(رئيسي) لا يقبل الترحيل المباشر. اختر حساباً فرعياً "
                "تابعاً له.")
    cur = conn.execute(
        "INSERT INTO journal_entries(entry_date,description,user_note,"
        "source_table,source_id,created_by) VALUES(?,?,?,?,?,?)",
        (entry_date, description, (note or "").strip(), source_table,
         source_id, username))
    entry_id = cur.lastrowid
    for l in lines:
        conn.execute(
            "INSERT INTO journal_lines(entry_id,account_id,"
            "gold_debit,gold_credit,cash_debit,cash_credit,line_desc)"
            " VALUES(?,?,?,?,?,?,?)",
            (entry_id, l["account_id"],
             _r3(l.get("gold_debit")), _r3(l.get("gold_credit")),
             _r2(l.get("cash_debit")), _r2(l.get("cash_credit")),
             l.get("line_desc", "")))
    # ══ ضمان محاسبي: لا عملية بلا أثر ══
    # يتحقق أن القيد كُتب فعلاً وأسطره متوازنة قبل إنهاء المعاملة.
    # أي خلل هنا يُلغي العملية كاملةً بدل حفظها بلا أثر محاسبي.
    # مفتاح الترتيب: افتراضياً معرّف القيد نفسه
    try:
        conn.execute("UPDATE journal_entries SET sort_key=COALESCE("
                     "sort_key, id) WHERE id=?", (entry_id,))
    except Exception:
        pass

    # رقم مستند موحّد لكل قيد — يوثّق العملية ويجعلها قابلة للتتبّع
    if not conn.execute("SELECT doc_no FROM journal_entries WHERE id=?",
                        (entry_id,)).fetchone()["doc_no"]:
        prefix = _DOC_PREFIX.get(source_table, "JV")
        conn.execute("UPDATE journal_entries SET doc_no=? WHERE id=?",
                     (f"{prefix}-{entry_id:05d}", entry_id))

    _verify_entry_posted(conn, entry_id)

    # كل قيد يُدرَج في طابور المزامنة بحزمته الكاملة (القيد وأسطره)
    try:
        from services import sync_queue
        if source_table not in ("invoices", "vouchers"):
            sync_queue.enqueue(conn, "journal",
                               sync_queue.bundle_entry(conn, entry_id))
    except Exception:
        pass          # المزامنة لا تعطّل العملية المحلية أبداً
    return entry_id


def account_balance(conn, account_id, date_from=None, date_to=None):
    """(رصيد الذهب، رصيد النقد) بصيغة مدين−دائن. الموجب = مدين."""
    q = ("SELECT COALESCE(SUM(l.gold_debit-l.gold_credit),0) g,"
         "       COALESCE(SUM(l.cash_debit-l.cash_credit),0) c"
         " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
         " WHERE e.is_deleted=0 AND l.account_id=?")
    params = [account_id]
    if date_from:
        q += " AND e.entry_date>=?"; params.append(date_from)
    if date_to:
        q += " AND e.entry_date<=?"; params.append(date_to)
    row = conn.execute(q, params).fetchone()
    return _r3(row["g"]), _r2(row["c"])


def balance_by_code(conn, code, **kw):
    row = conn.execute("SELECT id FROM accounts WHERE code=?", (code,)).fetchone()
    if not row:
        raise ValueError(f"حساب غير موجود: {code}")
    return account_balance(conn, row["id"], **kw)
