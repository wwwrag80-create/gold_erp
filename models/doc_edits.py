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


# ══════════════════════════════════════════════════════════════════
# صورة المستند قبل التعديل وبعده (4.54)
# ══════════════════════════════════════════════════════════════════
# الرقمان (قبل · بعد) يقولان **كم** تغيّر، ولا يقولان **ماذا**: أيُّ
# طقمٍ رُفع من الفاتورة، وأيُّ أجرٍ تبدّل. والتعديل في مكانه يمحو
# الصورة القديمة من القاعدة — فلا تُستعاد بعده أبداً. لذلك يُلتقط
# **قالب الطباعة نفسه** لحظة التعديل: قبل أن يُمسّ المستند وبعد أن
# يستقرّ، فيُرى المستند كما طُبع وكما صار.
_SNAP_SQL = (
    "CREATE TABLE IF NOT EXISTS doc_edit_snaps("
    " edit_id INTEGER PRIMARY KEY,"
    " before_html BLOB, after_html BLOB)")

# نوع المستند ← قالب طباعته (ما لا قالب له يُطبع قيدُه)
_TPL = {"invoices": "invoices", "vouchers": "vouchers",
        "purchases": "purchases", "tax_sales": "tax_sales",
        "fixing_ops": "fixing_ops", "melting_ops": "melting_ops"}
_WO = ("work_orders", "wo_supply", "wo_adjust")


def _ensure_snaps(conn):
    conn.execute(_SNAP_SQL)


def _target(conn, source_table, source_id, entry_id):
    """القالب ومعرّف المستند فيه — وإلا قيدُ اليومية نفسه."""
    try:
        if source_table in _TPL and source_id:
            return _TPL[source_table], int(source_id)
        if source_table in _WO:
            r = None
            if source_id and entry_id:
                r = conn.execute(
                    "SELECT id FROM work_orders WHERE id=? AND entry_id=?",
                    (source_id, entry_id)).fetchone()
            if not r and entry_id:
                r = conn.execute(
                    "SELECT id FROM work_orders WHERE entry_id=?"
                    " ORDER BY id LIMIT 1", (entry_id,)).fetchone()
            if r:
                return "work_orders", int(r["id"])
    except Exception:
        pass
    return ("journal", int(entry_id)) if entry_id else (None, None)


def render(conn, source_table, source_id, entry_id):
    """جسم قالب المستند كما يُطبع في المتصفح — أو "" إن تعذّر."""
    kind, did = _target(conn, source_table, source_id, entry_id)
    if not kind:
        return ""
    try:
        from services import print_manager as pm
    except Exception:
        return ""
    prev = pm.RTL_ORDER_OVERRIDE
    pm.RTL_ORDER_OVERRIDE = True        # نسخة المتصفح: RTL صحيح
    try:
        try:
            return pm.en(pm.BUILDERS[kind](conn, did))
        except Exception:
            if kind != "journal" and entry_id:
                try:
                    return pm.en(pm.BUILDERS["journal"](conn, entry_id))
                except Exception:
                    return ""
            return ""
    finally:
        pm.RTL_ORDER_OVERRIDE = prev


def capture(conn, source_table, source_id, entry_id):
    """صورة القالب الآن مضغوطةً للحفظ — `None` إن تعذّرت."""
    import zlib
    html = render(conn, source_table, source_id, entry_id)
    return zlib.compress(html.encode("utf-8"), 6) if html else None


def _save_snap(conn, edit_id, before=None, after=None):
    """لا يُفشل التعديل أبداً — الصورة رقابةٌ لا شرطُ صحة."""
    if not edit_id or (before is None and after is None):
        return
    try:
        _ensure_snaps(conn)
        conn.execute("INSERT OR IGNORE INTO doc_edit_snaps(edit_id)"
                     " VALUES(?)", (edit_id,))
        if before is not None:
            conn.execute("UPDATE doc_edit_snaps SET before_html=?"
                         " WHERE edit_id=?", (before, edit_id))
        if after is not None:
            conn.execute("UPDATE doc_edit_snaps SET after_html=?"
                         " WHERE edit_id=?", (after, edit_id))
    except Exception:
        pass


def snapshots(conn, edit_id):
    """صورتا المستند قبل التعديل وبعده لسطرٍ من السجل.

    المحفوظ لحظة التعديل أولاً. وما سبق هذا الإصدار: المُعاد ترحيله
    مستندُه القديم محذوفٌ حذفاً منطقياً لا فعلياً فيُرسم من القاعدة،
    والمعدَّل في مكانه لا صورة له قبل التعديل — فيقال ذلك صراحةً.
    """
    import zlib
    r = conn.execute("SELECT * FROM doc_edits WHERE id=?",
                     (edit_id,)).fetchone()
    if not r:
        raise ValueError("سطر التعديل غير موجود")
    snap = None
    try:
        _ensure_snaps(conn)
        snap = conn.execute("SELECT * FROM doc_edit_snaps WHERE edit_id=?",
                            (edit_id,)).fetchone()
    except Exception:
        snap = None

    def _un(b):
        try:
            return zlib.decompress(b).decode("utf-8") if b else ""
        except Exception:
            return ""

    before = _un(snap["before_html"]) if snap else ""
    after = _un(snap["after_html"]) if snap else ""
    stored_before = bool(before)
    if not before and r["kind"] == "repost" and r["entry_id"]:
        old = conn.execute(
            "SELECT source_table, source_id FROM journal_entries"
            " WHERE id=?", (r["entry_id"],)).fetchone()
        if old:
            before = render(conn, old["source_table"] or r["source_table"],
                            old["source_id"], r["entry_id"])
    if not after:
        after = render(conn, r["source_table"], r["source_id"],
                       r["new_entry_id"] or r["entry_id"])
    return {"row": dict(r), "before": before, "after": after,
            "stored_before": stored_before}


def record(conn, source_table, source_id, username, before,
           after=None, doc_no="", entry_id=None, new_entry_id=None,
           kind="inplace", note="", before_html=None, snap_after=True):
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
        cur = conn.execute(
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
        return None
    _save_snap(conn, cur.lastrowid, before_html,
               capture(conn, source_table, source_id, tgt)
               if snap_after else None)
    return cur.lastrowid


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
           entry_id=entry_id, new_entry_id=None, kind=kind, note=note,
           before_html=capture(conn, source_table, source_id, entry_id),
           snap_after=False)


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
        return
    _save_snap(conn, r["id"], after=capture(
        conn, source_table, new_id or source_id, new_entry_id))


def _days(a, b):
    try:
        d1 = _dt.date.fromisoformat(str(a)[:10])
        d2 = _dt.date.fromisoformat(str(b)[:10])
        return (d2 - d1).days
    except Exception:
        return None


def _party(conn, entry_id):
    """الطرف في المستند: أول جهةٍ لها سطرٌ في قيده (عميل · مورد · عامل)."""
    if not entry_id:
        return ""
    try:
        r = conn.execute(
            "SELECT en.name FROM journal_lines l"
            " JOIN entities en ON en.account_id=l.account_id"
            "  AND en.is_deleted=0"
            " WHERE l.entry_id=? AND COALESCE(en.entity_type,'')"
            "  NOT IN ('internal') ORDER BY l.id LIMIT 1",
            (entry_id,)).fetchone()
        return r["name"] if r else ""
    except Exception:
        return ""


def _doc_no_of(conn, entry_id):
    if not entry_id:
        return ""
    try:
        r = conn.execute("SELECT doc_no FROM journal_entries WHERE id=?",
                         (entry_id,)).fetchone()
        return (r["doc_no"] or "") if r else ""
    except Exception:
        return ""


def describe(note, dg=0.0, dc=0.0):
    """ما الذي تغيّر — بكلامٍ يُقرأ لا برموز.

    السجل يحفظ «+1 · ~2 · -0» اختصاراً؛ وهنا يُقال: أُضيف سطر، وعُدّل
    سطران. وما لا ملاحظة له يُوصف بأثره على القيمة.
    """
    import re
    parts = []
    txt = str(note or "").strip(" ·")
    m = re.match(r"^\+(\d+) · ~(\d+) · -(\d+)\s*(?:·\s*)?(.*)$", txt)
    if m:
        a, u, d, rest = int(m.group(1)), int(m.group(2)), \
            int(m.group(3)), m.group(4)
        if a:
            parts.append(f"أُضيف {a} سطر")
        if u:
            parts.append(f"عُدّل {u} سطر")
        if d:
            parts.append(f"حُذف {d} سطر")
        txt = rest.strip(" ·")
    if txt:
        parts.extend("تعديل البيان" if x.strip() == "البيان" else x.strip()
                     for x in txt.split("·") if x.strip())
    if not parts:
        if abs(dg) > 0.0005 or abs(dc) > 0.005:
            parts.append("تغيّرت قيمة المستند")
        else:
            parts.append("بلا تغيير في القيمة")
    return " · ".join(parts)


def report(conn, date_from=None, date_to=None, username=None,
           source_table=None, min_lag=0, edit_id=None):
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
    if edit_id:
        q += " AND id=?"
        p.append(int(edit_id))
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
            "change": describe(r["note"], dg, dc),
            "party": _party(conn, r["new_entry_id"] or r["entry_id"]),
            "entry_id": r["entry_id"], "new_entry_id": r["new_entry_id"],
        })
        # المُعاد ترحيله قد يأخذ رقماً جديداً: يُعرض القديم ← الجديد
        nd = _doc_no_of(conn, r["new_entry_id"]) \
            if r["kind"] == "repost" else ""
        out[-1]["new_doc_no"] = nd
        out[-1]["doc_label"] = (
            f"{out[-1]['doc_no']} ← {nd}"
            if nd and nd != (r["doc_no"] or "") else out[-1]["doc_no"])
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
