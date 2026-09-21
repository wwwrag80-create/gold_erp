# -*- coding: utf-8 -*-
"""من عدّل ماذا بعد الترحيل — ومتى، وكم تغيّرت قيمته.

**السؤال الذي وُجد لأجله**: التعديل مشروعٌ في هذا النظام — فالخطأ
يقع، والصواب أن يُصحَّح لا أن يُترك. لكن سجل التتبع يقول «عُدِّلت
الفاتورة S-00042» ولا يقول **كم تغيّرت**. فمن أراد أن يعرف أن
فاتورةً نقص وزنها كيلواً بعد شهرٍ من ترحيلها فتح قيدها وجمع بيده —
ولا أحد يفعل.

**والرقابة تبدأ من أن يكون التعديل مرئياً**: تعديلٌ يُرى يُسأل عنه،
وتعديلٌ لا يُرى لا يُسأل. وهذه ليست تهمةً لأحد؛ هي ما يطلبه أي مدقّق
في أول يومٍ من عمله.

**ولا يُقرأ الفرق من نصّ التفصيل في `audit_log`**: النصّ للإنسان لا
للحاسب، وتحليله بتعبيرٍ نمطي يكسر بأول تغييرٍ في صياغته — ويكسر
صامتاً فيعطي صفراً بدل أن يعطي خطأ. فتُحفظ القيمتان **رقمين** قبل
وبعد، ويُحسب الفرق منهما.

**وقيمة المستند = مجموع الطرف المدين من قيده**: مقياسٌ واحد يصلح
لكل نوع — فاتورةٍ وسندٍ وصهرٍ وقيدٍ يدوي — لأن القيد متوازنٌ
بالضرورة، فمجموع مدينه هو حجمه. فلا يحتاج كل نوعٍ قاعدةً خاصة، ولا
يسقط نوعٌ يُضاف مستقبلاً.

**والمؤشر الذي يُقرأ قبل كل شيء**: كم مضى بين ترحيل المستند وتعديله.
تعديلٌ بعد دقيقتين تصحيحُ إدخال، وتعديلٌ بعد أربعين يوماً — بعد أن
أُغلق الشهر وصُدِّرت الميزانية — شيءٌ آخر يُسأل عنه.

كتابةُ السجلّ وحدها ما يُكتب هنا؛ والتقارير قراءةٌ محضة.
"""
import datetime as _dt

KINDS = {"inplace": "عُدّل في مكانه", "repost": "أُلغي وأُعيد ترحيله"}

# **حدّ «التعديل المتأخّر»**: شهرٌ من الترحيل. ما دونه تصحيحُ إدخالٍ
# في دورة العمل نفسها، وما فوقه يقع بعد أن أُغلق الشهر وصُدِّرت
# أرقامه — فهو الذي يُراجَع أولاً.
LATE_DAYS = 30

# تسميات المستندات — تُقرأ من `editing.EDITABLE` ليبقى المصدر واحداً
try:
    from models.editing import EDITABLE as _EDITABLE
except Exception:                                    # pragma: no cover
    _EDITABLE = {}
LABELS = {k: v[0] for k, v in _EDITABLE.items()}
LABELS.setdefault("invoices", "فاتورة مبيعات/مرتجع")
LABELS.setdefault("vouchers", "سند قبض/صرف")
LABELS.setdefault("work_orders", "توريد/إنتاج")


def totals(conn, entry_id):
    """قيمة المستند وزناً ونقداً = مجموع الطرف المدين من قيده."""
    if not entry_id:
        return (0.0, 0.0)
    try:
        r = conn.execute(
            "SELECT ROUND(COALESCE(SUM(gold_debit),0),3) g,"
            " ROUND(COALESCE(SUM(cash_debit),0),2) c"
            " FROM journal_lines WHERE entry_id=?", (entry_id,)).fetchone()
    except Exception:
        return (0.0, 0.0)
    return (float(r["g"] or 0.0), float(r["c"] or 0.0)) if r else (0.0, 0.0)


def _entry_meta(conn, entry_id):
    """تاريخ المستند ولحظة ترحيله — ومنهما يُقاس تأخّر التعديل."""
    if not entry_id:
        return ("", "")
    try:
        r = conn.execute(
            "SELECT entry_date, COALESCE(created_at,'') created_at"
            " FROM journal_entries WHERE id=?", (entry_id,)).fetchone()
    except Exception:
        return ("", "")
    return (str(r["entry_date"])[:10], str(r["created_at"])) if r else ("", "")


def record(conn, source_table, source_id, username, before,
           after=None, doc_no="", entry_id=None, new_entry_id=None,
           kind="inplace", note=""):
    """يسجّل تعديلاً وقع على مستندٍ مُرحَّل.

    `before` زوج (وزن، نقد) قبل التعديل — يُلتقط قبل أن يُمسّ القيد.
    `after` يُشتقّ من القيد الجديد (أو القائم) إن لم يُمرَّر.

    **لا يُفشل العملية أبداً**: تسجيل الرقابة لا يجوز أن يمنع تصحيحاً
    محاسبياً صحيحاً. فإن تعذّرت الكتابة — قاعدةٌ لم تُرقَّ بعد مثلاً —
    مضى التعديل وسقط سطر السجل وحده.
    """
    try:
        tgt = new_entry_id or entry_id
        if after is None:
            after = totals(conn, tgt)
        d_date, posted = _entry_meta(conn, entry_id or tgt)
        conn.execute(
            "INSERT INTO doc_edits(source_table,source_id,doc_no,entry_id,"
            " new_entry_id,doc_date,posted_at,username,kind,"
            " old_gold,new_gold,old_cash,new_cash,note)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (source_table, int(source_id or 0), str(doc_no or ""),
             entry_id, new_entry_id, d_date, posted, username,
             kind if kind in KINDS else "inplace",
             round(float(before[0] or 0.0), 3),
             round(float(after[0] or 0.0), 3),
             round(float(before[1] or 0.0), 2),
             round(float(after[1] or 0.0), 2), str(note or "")))
    except Exception:
        pass


def begin(conn, source_table, source_id, username, entry_id,
          doc_no="", kind="repost", note=""):
    """يفتح سطر تعديلٍ بقيمة المستند **قبل** أن يُمسّ قيده.

    يُستعمل في التعديل الذي يُلغي المستند ويعيد ترحيله: القيمة
    القديمة تُلتقط قبل العكس، والجديدة بعد أن يُرحَّل البديل. ويُقفل
    السطر بـ`finish`. وقوعهما في معاملةٍ واحدة يضمن ألّا يبقى سطرٌ
    نصفُ مكتوب.
    """
    record(conn, source_table, source_id, username,
           totals(conn, entry_id), after=(0.0, 0.0), doc_no=doc_no,
           entry_id=entry_id, new_entry_id=None, kind=kind, note=note)


def finish(conn, source_table, source_id, new_entry_id, new_id=None):
    """يُتمّ آخر سطرٍ مفتوحٍ لهذا المستند بقيمته بعد التعديل."""
    try:
        r = conn.execute(
            "SELECT id FROM doc_edits WHERE source_table=? AND source_id=?"
            " AND new_entry_id IS NULL ORDER BY id DESC LIMIT 1",
            (source_table, int(source_id or 0))).fetchone()
        if not r:
            return
        g, c = totals(conn, new_entry_id)
        conn.execute(
            "UPDATE doc_edits SET new_entry_id=?, new_gold=?, new_cash=?,"
            " source_id=COALESCE(?, source_id) WHERE id=?",
            (new_entry_id, round(g, 3), round(c, 2), new_id, r["id"]))
    except Exception:
        pass


def _days(a, b):
    try:
        d1 = _dt.date.fromisoformat(str(a)[:10])
        d2 = _dt.date.fromisoformat(str(b)[:10])
        return (d2 - d1).days
    except Exception:
        return None


def report(conn, date_from=None, date_to=None, username=None,
           source_table=None, min_lag=0):
    """التعديلات في فترة — الأكبر أثراً أولاً.

    `date_from`/`date_to` على **لحظة التعديل** لا على تاريخ المستند:
    السؤال «ماذا عُدِّل هذا الأسبوع» لا «أيّ مستنداتِ هذا الأسبوع
    عُدِّلت».
    """
    q = ("SELECT * FROM doc_edits WHERE 1=1")
    p = []
    if date_from:
        q += " AND substr(edited_at,1,10)>=?"
        p.append(str(date_from)[:10])
    if date_to:
        q += " AND substr(edited_at,1,10)<=?"
        p.append(str(date_to)[:10])
    if username:
        q += " AND username=?"
        p.append(username)
    if source_table:
        q += " AND source_table=?"
        p.append(source_table)
    q += " ORDER BY edited_at DESC, id DESC"
    try:
        rows = conn.execute(q, p).fetchall()
    except Exception:
        rows = []                                # قاعدة قبل الترقية

    out = []
    for r in rows:
        dg = round(float(r["new_gold"]) - float(r["old_gold"]), 3)
        dc = round(float(r["new_cash"]) - float(r["old_cash"]), 2)
        lag = _days(r["posted_at"] or r["doc_date"], r["edited_at"])
        if min_lag and (lag is None or lag < min_lag):
            continue
        out.append({
            "id": r["id"], "table": r["source_table"],
            "label": LABELS.get(r["source_table"], r["source_table"]),
            "source_id": r["source_id"], "doc_no": r["doc_no"] or "—",
            "doc_date": r["doc_date"] or "—",
            "edited_at": str(r["edited_at"] or "")[:16],
            "user": r["username"] or "—",
            "kind": r["kind"], "kind_label": KINDS.get(r["kind"], r["kind"]),
            "old_gold": float(r["old_gold"]), "new_gold": float(r["new_gold"]),
            "old_cash": float(r["old_cash"]), "new_cash": float(r["new_cash"]),
            "d_gold": dg, "d_cash": dc, "lag": lag,
            "changed": abs(dg) > 0.0005 or abs(dc) > 0.005,
            "note": r["note"] or "",
        })
    return out


def summarize(conn, rows):
    """إجماليات التقرير ومؤشراته — ولوحاتُ الشاشة منها."""
    by_user, by_type = {}, {}
    tot = {"count": len(rows), "changed": 0, "up_gold": 0.0,
           "dn_gold": 0.0, "up_cash": 0.0, "dn_cash": 0.0,
           "late": 0, "max_lag": 0}
    for r in rows:
        u = by_user.setdefault(r["user"], {"name": r["user"], "count": 0,
                                           "d_gold": 0.0, "d_cash": 0.0,
                                           "late": 0})
        t = by_type.setdefault(r["table"], {"label": r["label"], "count": 0,
                                            "d_gold": 0.0, "d_cash": 0.0})
        for acc in (u, t):
            acc["count"] += 1
            acc["d_gold"] = round(acc["d_gold"] + r["d_gold"], 3)
            acc["d_cash"] = round(acc["d_cash"] + r["d_cash"], 2)
        if r["changed"]:
            tot["changed"] += 1
        # **الزيادة والنقص لا يُقاصّان في العرض**: تعديلٌ أضاف كيلواً
        # وآخر أنقص كيلواً صافيهما صفر — ويبدو أن شيئاً لم يقع.
        key = "up_gold" if r["d_gold"] > 0 else "dn_gold"
        tot[key] = round(tot[key] + r["d_gold"], 3)
        key = "up_cash" if r["d_cash"] > 0 else "dn_cash"
        tot[key] = round(tot[key] + r["d_cash"], 2)
        if r["lag"] is not None:
            tot["max_lag"] = max(tot["max_lag"], r["lag"])
            if r["lag"] >= LATE_DAYS:
                tot["late"] += 1
                u["late"] += 1
    tot["d_gold"] = round(tot["up_gold"] + tot["dn_gold"], 3)
    tot["d_cash"] = round(tot["up_cash"] + tot["dn_cash"], 2)
    return {
        "total": tot,
        "users": sorted(by_user.values(), key=lambda x: -x["count"]),
        "types": sorted(by_type.values(), key=lambda x: -x["count"]),
        "biggest": (max(rows, key=lambda r: abs(r["d_cash"])
                        + abs(r["d_gold"]) * 1000.0) if rows else None),
    }


def history(conn, source_table, source_id):
    """تاريخ تعديلات مستندٍ بعينه — يُفتح من الأرشيف أو من الكشف."""
    return [r for r in report(conn)
            if r["table"] == source_table and r["source_id"] == source_id]


def verdict(s, fmt=None, money=None):
    """جملٌ تُقرأ — والتعديل مشروعٌ ما دام مرئياً."""
    fmt = fmt or (lambda v: f"{v:,.3f}")
    money = money or (lambda v: f"{v:,.2f}")
    t = s["total"]
    out = []
    if not t["count"]:
        return ["لم يُعدَّل مستندٌ مُرحَّل في هذه الفترة."]
    out.append(
        f"{t['count']:,} تعديلاً على مستنداتٍ مُرحَّلة، منها "
        f"{t['changed']:,} غيّر قيمة المستند.")
    if abs(t["d_gold"]) > 0.0005 or abs(t["d_cash"]) > 0.005:
        out.append(
            f"صافي ما تغيّر: {fmt(t['d_gold'])} وزناً و"
            f"{money(t['d_cash'])} نقداً.")
    if t["late"]:
        out.append(
            f"و{t['late']:,} منها وقع بعد {LATE_DAYS} يوماً أو أكثر من "
            f"الترحيل (أقصاها {t['max_lag']:,} يوماً) — هذه التي "
            "تُراجَع أولاً.")
    if s["users"]:
        u = s["users"][0]
        out.append(
            f"أكثر من عدّل: {u['name']} بـ {u['count']:,} تعديلاً"
            + (f" منها {u['late']:,} متأخّر." if u["late"] else "."))
    b = s["biggest"]
    if b is not None and b["changed"]:
        out.append(
            f"وأكبر تغيّرٍ في القيمة: {b['label']} {b['doc_no']} — "
            f"وزناً {fmt(b['d_gold'])} ونقداً {money(b['d_cash'])}"
            + (f" بعد {b['lag']:,} يوماً." if b["lag"] is not None else "."))
    out.append("والتعديل مشروعٌ في هذا النظام؛ المقصود أن يكون مرئياً.")
    return out
