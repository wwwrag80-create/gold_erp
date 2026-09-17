# -*- coding: utf-8 -*-
"""سجل تدقيق محصَّن — سلسلة بصماتٍ تكشف أي عبثٍ بالقيود من خارج النظام.

**المشكلة**: النظام يمنع تعديل القيد من داخله (التعديل عندنا إلغاءٌ
بقيد عكسي ثم ترحيلٌ جديد)، وسجل التدقيق يوثّق من فعل ماذا. لكن كل
ذلك يقوم على أن أحداً لم يفتح ملف قاعدة البيانات ببرنامج خارجي
ويغيّر رقماً. وملف SQLite ملفٌ على القرص: من وصل إليه غيّر فيه ما شاء
بلا أن يترك في النظام أثراً.

**العلاج — سلسلة بصمات (Hash chain)**: لكل قيد بصمة `sha256` تُحسب من
**مضمونه وبصمة القيد الذي قبله معاً**. فتغيير رقمٍ في قيدٍ قديم يُفسد
بصمته، وفسادها يُفسد بصمة ما بعده، وهكذا إلى آخر السلسلة. والمعبث لا
يستطيع إعادة بناء السلسلة إلا بإعادة حساب كل قيدٍ تالٍ — وهو ما لا
يفعله برنامجٌ عام يحرّر جدولاً.

**ما تحميه البصمة ومالا تحميه**:

* تحمي **مضمون القيد**: تاريخه · بيانه · رقم مستنده · مصدره · من
  أنشأه · وكل سطرٍ فيه بحسابه ومبالغه الأربعة.
* **لا تشمل حالة الحذف** (`is_deleted`) ولا زمنه: الحذف المنطقي عملٌ
  مشروع يجري من داخل النظام ويُوثَّق في سجل التدقيق، فإدخاله في
  البصمة يجعل كل حذفٍ سليم يبدو عبثاً — وتنبيهٌ يتكرر بلا سبب هو
  أسرع طريق إلى تجاهل التنبيهات كلها.

**القيود القديمة**: قاعدة تعمل منذ شهور فيها قيود بلا بصمة. تُختم
دفعةً واحدة بمضمونها الحالي، وهذا هو خطُّ الأساس المعلَن: السلسلة
تشهد على ما بعد الختم لا على ما قبله. وهذا يُقال صراحةً في الشاشة
ولا يُوهَم المستخدم بغيره.
"""
import hashlib
import threading

GENESIS = "0" * 64
_FMT_GOLD = "{:.3f}"
_FMT_CASH = "{:.2f}"


def _canon(entry, lines):
    """النص المعياري الذي تُحسب منه البصمة.

    الترتيب والتنسيق ثابتان تماماً: أي اختلافٍ في ترتيب الأسطر أو في
    عدد المنازل العشرية ينتج بصمةً مختلفة لقيدٍ لم يتغيّر — فتُعلَن
    السلامةُ خللاً. الأسطر تُرتَّب بمعرّفها، والأرقام تُكتب بمنازل
    ثابتة (3 للوزن و2 للنقد) كما تُخزَّن.
    """
    head = "|".join((
        str(entry["id"]),
        str(entry["entry_date"] or ""),
        str(entry["doc_no"] or ""),
        str(entry["description"] or ""),
        str(entry["user_note"] or ""),
        str(entry["source_table"] or ""),
        str(entry["source_id"] if entry["source_id"] is not None else ""),
        str(entry["created_by"] or ""),
    ))
    body = ";".join(
        "|".join((str(l["account_id"]),
                  _FMT_GOLD.format(float(l["gold_debit"] or 0)),
                  _FMT_GOLD.format(float(l["gold_credit"] or 0)),
                  _FMT_CASH.format(float(l["cash_debit"] or 0)),
                  _FMT_CASH.format(float(l["cash_credit"] or 0)),
                  str(l["line_desc"] or "")))
        for l in lines)
    return head + "#" + body


def digest(entry, lines, prev_hash):
    """بصمة القيد مضمومةً إلى بصمة سابقه — وهذا ما يصنع السلسلة."""
    raw = (prev_hash or GENESIS) + "\n" + _canon(entry, lines)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ══════════════════════════════════════════════════════════════════
#  السلسلة **تشمل المحذوف** — وهذا شرطُ عملها لا إغفالٌ فيها
# ------------------------------------------------------------------
#  استعلامات هذا الملف لا تُرشّح `is_deleted`، بما فيه المحذوف
#  منطقياً، لسببين:
#
#  1. **الاستمرارية**: كل حلقةٍ تُبنى على بصمة سابقتها. فإسقاط قيدٍ
#     محذوف من المرور يقطع السلسلة عند موضعه ويجعل كل ما بعده يبدو
#     مختلاً — تنبيهٌ كاذب يتكرر مع كل حذفٍ سليم.
#  2. **المنع**: لو خرج المحذوف من الفحص لصار إخفاءُ قيدٍ بتغيير
#     `is_deleted` من خارج النظام كافياً لإخراجه من السلسلة بلا أثر —
#     وهو بالضبط ما وُجدت السلسلة لكشفه.
#
#  ولهذا أيضاً لا تدخل حالة الحذف في حساب البصمة نفسها (انظر رأس
#  الملف): الحذف يُوثَّق في سجل التدقيق، والبصمة تشهد على المضمون.
# ══════════════════════════════════════════════════════════════════

def _entry(conn, entry_id):
    e = conn.execute(
        "SELECT id, entry_date, doc_no, description, user_note,"
        " source_table, source_id, created_by, row_hash, prev_hash"
        " FROM journal_entries WHERE id=?", (entry_id,)).fetchone()
    if e is None:
        return None, []
    lines = conn.execute(
        "SELECT account_id, gold_debit, gold_credit, cash_debit,"
        " cash_credit, line_desc FROM journal_lines"
        " WHERE entry_id=? ORDER BY id", (entry_id,)).fetchall()
    return e, lines


def last_hash(conn, before_id=None):
    """بصمة آخر قيدٍ مختوم — رأس السلسلة الذي يُبنى عليه التالي.

    يشمل المحذوف منطقياً: الحلقة تُبنى على سابقتها مهما كانت حالتها
    (الشرح كاملاً فوق).
    """
    q = ("SELECT row_hash FROM journal_entries"
         " WHERE row_hash IS NOT NULL AND row_hash<>''")
    p = []
    if before_id is not None:
        q += " AND id<?"
        p.append(int(before_id))
    q += " ORDER BY id DESC LIMIT 1"
    try:
        r = conn.execute(q, p).fetchone()
    except Exception:
        return GENESIS
    return (r["row_hash"] if r else GENESIS) or GENESIS


def seal_entry(conn, entry_id):
    """يختم قيداً رُحّل للتوّ بوصله بآخر حلقةٍ في السلسلة.

    يُستدعى داخل معاملة الترحيل نفسها، فالقيد وبصمته يُكتبان معاً أو
    لا يُكتبان — ولا يبقى قيدٌ بلا بصمة بسبب انقطاعٍ في المنتصف.
    """
    e, lines = _entry(conn, entry_id)
    if e is None:
        return None
    prev = last_hash(conn, before_id=entry_id)
    h = digest(e, lines, prev)
    conn.execute("UPDATE journal_entries SET row_hash=?, prev_hash=?"
                 " WHERE id=?", (h, prev, entry_id))
    return h


# ══════════════════════════════════════════════════════════════════
#  الختم عند **إغلاق المعاملة** لا عند كتابة القيد
# ------------------------------------------------------------------
#  القيد لا يكتمل بسطر `INSERT` وحده: عملياتٌ كثيرة في النظام تُكمله
#  بعده **داخل المعاملة نفسها** — ربط `source_id` بالمستند الذي
#  أنشأه (دفعة التوريد · الجرد · الرصيد الافتتاحي)، وتنقيح وصفه في
#  السندات ونقل المستندات. فختمُه لحظة كتابته يلتقط صورةً ناقصة،
#  ثم يُعلَن الاكتمالُ المشروع بعدها «عبثاً» — وتنبيهٌ كاذبٌ يتكرر
#  هو أسرع طريق إلى تجاهل التنبيهات كلها.
#
#  لذلك: يُوسَم القيد هنا، ويُختم في `seal_pending` التي تُستدعى مرةً
#  واحدة قبل `COMMIT` — حين يكون القيد قد بلغ صورته النهائية.
#
#  والوسم لكل خيط على حدة: الترحيل يجري في خيط الواجهة والنسخ
#  الاحتياطي في خيط آخر، فوسمٌ مشترك بينهما قد يختم قيد معاملةٍ لم
#  تُغلق بعد.
# ══════════════════════════════════════════════════════════════════

_local = threading.local()


def _marks():
    s = getattr(_local, "marks", None)
    if s is None:
        s = set()
        _local.marks = s
    return s


def mark(conn, entry_id):
    """يوسم قيداً ليُختم عند إغلاق المعاملة.

    يُستدعى من `post_entry` لكل قيدٍ جديد، ومن كل موضعٍ يعدّل مضمون
    قيدٍ قائم تعديلاً مشروعاً من داخل النظام.
    """
    try:
        _marks().add(int(entry_id))
    except Exception:
        pass


def _rebuild_from(conn, entry_id):
    """يعيد بناء السلسلة من قيدٍ فما بعده.

    تعديلُ قيدٍ قديم يغيّر بصمته، وبصمتُه مخزَّنة في القيد الذي يليه
    (`prev_hash`) — فالحلقة تنقطع عنده. إعادة البناء تصله بما بعده
    من جديد. وهي عمليةٌ نادرة (التعديل في هذا النظام إلغاءٌ بقيد
    عكسي في الغالب) وتُسجَّل في التدقيق: من يعيد كتابة التاريخ من
    داخل النظام يترك أثراً، وهذا هو المطلوب — السلسلة تكشف العبث من
    **خارج** النظام، وسجل التدقيق يوثّق ما جرى من داخله.

    وإعادة البناء تشمل المحذوف منطقياً: حلقةٌ متروكة بلا إعادة ربط
    تقطع السلسلة عند موضعها (الشرح كاملاً فوق).
    """
    # بما فيه المحذوف منطقياً: حلقةٌ متروكة تقطع السلسلة عند موضعها.
    rows = conn.execute(
        "SELECT id FROM journal_entries WHERE id>=? ORDER BY id",
        (int(entry_id),)).fetchall()
    prev = last_hash(conn, before_id=entry_id)
    n = 0
    for r in rows:
        e, lines = _entry(conn, r["id"])
        if e is None:
            continue
        h = digest(e, lines, prev)
        if (e["row_hash"] or "") != h or (e["prev_hash"] or "") != prev:
            conn.execute("UPDATE journal_entries SET row_hash=?, prev_hash=?"
                         " WHERE id=?", (h, prev, r["id"]))
            n += 1
        prev = h
    return n


def seal_pending(conn, username=None):
    """يختم كل قيدٍ وُسم في هذه المعاملة — تُستدعى قبل `COMMIT`.

    ثلاث حالات:

    * قيدٌ جديد بلا بصمة ⇒ يُختم ويوصل بآخر حلقة.
    * قيدٌ مختوم لم يتغيّر مضمونه ⇒ لا شيء.
    * قيدٌ مختوم تغيّر مضمونه بتعديلٍ مشروع ⇒ يُعاد ختمه **وما بعده**
      لتتصل السلسلة، ويُسجَّل ذلك في التدقيق.

    الخروج فوريٌّ حين لا وسم — وهي الحال في كل معاملة قراءة وفي كل
    معاملة لا تمسّ قيداً، فلا تدفع بقية عمليات النظام ثمن هذه الميزة.
    """
    marks = _marks()
    if not marks:
        return 0
    ids = sorted(marks)
    marks.clear()
    sealed = rebuilt = 0
    for eid in ids:
        e, lines = _entry(conn, eid)
        if e is None:
            continue
        stored = (e["row_hash"] or "").strip()
        if not stored:
            prev = last_hash(conn, before_id=eid)
            conn.execute(
                "UPDATE journal_entries SET row_hash=?, prev_hash=?"
                " WHERE id=?", (digest(e, lines, prev), prev, eid))
            sealed += 1
            continue
        prev = (e["prev_hash"] or GENESIS).strip() or GENESIS
        if digest(e, lines, prev) != stored:
            rebuilt += _rebuild_from(conn, eid)
    if rebuilt:
        try:
            from services.audit import log_action
            log_action(conn, username, "update", "journal_entries", ids[0],
                       f"إعادة بناء سلسلة البصمات بعد تعديل مشروع "
                       f"({rebuilt} قيداً)")
        except Exception:
            pass
    return sealed + rebuilt


def rebuild(conn, from_id=None, username=None):
    """يعيد بناء السلسلة كلها (أو من قيدٍ فما بعده) — **بقرارٍ صريح**.

    تُستعمل بعد معالجة خللٍ مُثبت: نسخةٌ احتياطية استُعيدت، أو سجلات
    مُسحت بأداة صيانة، أو تعديلٌ مشروع جرى بنسخةٍ قديمة من النظام لم
    تكن توسم. بلا هذا الباب تبقى الشاشة حمراء إلى الأبد فتفقد معناها.

    **وهي مسجَّلة في التدقيق دائماً**: من يعيد بناء السلسلة يترك
    أثراً باسمه وزمنه — فالباب مفتوحٌ لكنه ليس خفياً.
    """
    n = _rebuild_from(conn, int(from_id or 1))
    try:
        from services.audit import log_action
        log_action(conn, username, "update", "journal_entries",
                   int(from_id or 1),
                   f"إعادة بناء سلسلة البصمات بقرارٍ صريح ({n} قيداً)")
    except Exception:
        pass
    return n


def seal_all(conn, username=None):
    """يختم كل قيدٍ بلا بصمة — خطُّ الأساس لقاعدةٍ تعمل منذ قبل الميزة.

    يعيد عدد ما خُتم. يُنفَّذ مرةً واحدة عادةً، وتكراره لا يضرّ لأنه
    لا يمسّ قيداً مختوماً.

    الختم يشمل المحذوف منطقياً: قيدٌ يُترك بلا بصمة ثغرةٌ في السلسلة
    مهما كانت حالته (الشرح كاملاً فوق).
    """
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM journal_entries"
        " WHERE row_hash IS NULL OR row_hash='' ORDER BY id")]
    for eid in ids:
        seal_entry(conn, eid)
    if ids:
        try:
            from services.audit import log_action
            log_action(conn, username, "update", "journal_entries", None,
                       f"ختم {len(ids)} قيداً في سلسلة البصمات")
        except Exception:
            pass
    return len(ids)


def verify(conn, max_breaks=50):
    """يتحقّق من السلسلة كلها ويعيد تقريراً بما وُجد.

    يمرّ على القيود المختومة بترتيب معرّفاتها، ويعيد حساب بصمة كل
    واحدٍ من مضمونه الحالي وبصمة سابقه المخزَّنة. فيُكتشف نوعان من
    الخلل:

    * **مضمونٌ تغيّر**: البصمة المعادة لا تطابق المخزَّنة.
    * **حلقةٌ مقطوعة**: بصمة السابق المخزَّنة في القيد لا تطابق بصمة
      القيد الذي قبله فعلاً — أي أن قيداً حُذف من الجدول حذفاً مادياً
      أو أُدخل بينهما.

    القيود غير المختومة تُعدّ ولا تُعدّ خللاً: هي ما سبق تفعيل الميزة.

    المرور يشمل المحذوف منطقياً — وهو شرط استمرار السلسلة ومنع
    الإخفاء بتغيير حالة الحذف (الشرح كاملاً فوق).
    """
    out = {"checked": 0, "unsealed": 0, "breaks": [], "ok": True,
           "first_sealed": None, "last_sealed": None}
    try:
        rows = conn.execute(
            "SELECT id, entry_date, doc_no, description, user_note,"
            " source_table, source_id, created_by, row_hash, prev_hash"
            " FROM journal_entries ORDER BY id").fetchall()
    except Exception:
        return out
    prev_seen = GENESIS
    for e in rows:
        stored = (e["row_hash"] or "").strip()
        if not stored:
            out["unsealed"] += 1
            continue
        out["checked"] += 1
        if out["first_sealed"] is None:
            out["first_sealed"] = e["id"]
        out["last_sealed"] = e["id"]
        lines = conn.execute(
            "SELECT account_id, gold_debit, gold_credit, cash_debit,"
            " cash_credit, line_desc FROM journal_lines"
            " WHERE entry_id=? ORDER BY id", (e["id"],)).fetchall()
        stored_prev = (e["prev_hash"] or GENESIS).strip() or GENESIS
        kind = ""
        if stored_prev != prev_seen:
            kind = "حلقة مقطوعة (قيدٌ حُذف أو أُدخل خارج النظام)"
        elif digest(e, lines, stored_prev) != stored:
            kind = "مضمون القيد تغيّر بعد ترحيله"
        if kind and len(out["breaks"]) < int(max_breaks):
            out["breaks"].append({
                "id": e["id"], "doc_no": e["doc_no"] or f"#{e['id']}",
                "date": e["entry_date"], "who": e["created_by"] or "",
                "desc": (e["user_note"] or e["description"] or "").strip(),
                "kind": kind})
        if kind:
            out["ok"] = False
        prev_seen = stored
    return out


def status(conn):
    """ملخّصٌ سريع للعرض: مختوم · غير مختوم · سليم أم لا."""
    r = verify(conn)
    return {"sealed": r["checked"], "unsealed": r["unsealed"],
            "ok": r["ok"], "breaks": len(r["breaks"]),
            "first": r["first_sealed"], "last": r["last_sealed"]}
