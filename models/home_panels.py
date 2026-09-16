# -*- coding: utf-8 -*-
"""بيانات شاشة البداية الحيّة — ما يجب أن يراه المحاسب فور فتح النظام.

**الفكرة**: الشاشة الأولى كانت شعاراً. والشعار لا يقول شيئاً. وأسئلة
أول الدوام ثابتة لا تتغيّر:

  ماذا جرى أمس واليوم؟ · هل هناك رصيد سالب يجب علاجه قبل أن يكبر؟ ·
  من تأخّر في السداد؟ · ما آخر العمليات المرحَّلة ومن رحّلها؟

كل واحد منها يُجاب اليوم بفتح شاشة والبحث فيها. وهذه الوحدة تجمعها
في استعلامات قليلة يُبنى منها عرضٌ واحد، وكل رقمٍ فيه بابٌ إلى
تفصيله — فالشاشة الأولى تصير نقطة بداية العمل لا لافتةً تُتجاوز.

**قراءة محضة**: لا تكتب شيئاً ولا تُنشئ قيداً. وكل دالة تُرجع بنية
بسيطة جاهزة للعرض، فالواجهة لا تحسب شيئاً بنفسها.
"""
import datetime as _dt

from services.accounting_engine import account_balance

# الحسابات التي يُنبَّه على سالبها — نفس ما يحرسه `services.stock_guard`
# (مخزونٌ مادي لا يُتصوَّر سالباً) مضافاً إليها الصندوق النقدي.
WATCH = (
    ("1100", "خزينة التصنيع", "gold"),
    ("1200", "الذهب المشغول", "gold"),
    ("1310", "صندوق الكسر", "gold"),
    ("1350", "الصب والتصفية", "gold"),
    ("1400", "الصندوق النقدي", "cash"),
)

EPS_GOLD = 0.001
EPS_CASH = 0.01


def today():
    return _dt.date.today().isoformat()


def _acc(conn, code):
    try:
        from models.accounts import acc_id
        return acc_id(conn, code)
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════
#  حركة اليوم
# ══════════════════════════════════════════════════════════════════

def day_pulse(conn, date=None):
    """حركة يومٍ واحد بأرقامها الأربعة: عدد · وزن · نقد داخل/خارج.

    استعلامان مجمَّعان لا مرورٌ على المستندات: الشاشة الأولى يجب أن
    تفتح فوراً، وقراءة كل قيود اليوم لعدّها إسرافٌ لا داعي له.
    """
    d = str(date or today())[:10]
    r = conn.execute(
        "SELECT COUNT(DISTINCT e.id) n,"
        " COALESCE(SUM(l.gold_debit),0) g, COALESCE(SUM(l.cash_debit),0) c"
        " FROM journal_entries e JOIN journal_lines l ON l.entry_id=e.id"
        " WHERE e.is_deleted=0 AND e.entry_date=?", (d,)).fetchone()
    cash = conn.execute(
        "SELECT COALESCE(SUM(l.cash_debit),0) i,"
        " COALESCE(SUM(l.cash_credit),0) o"
        " FROM journal_lines l"
        " JOIN journal_entries e ON e.id=l.entry_id AND e.is_deleted=0"
        " JOIN accounts a ON a.id=l.account_id"
        " WHERE a.code='1400' AND e.entry_date=?", (d,)).fetchone()
    cin = round((cash["i"] if cash else 0) or 0, 2)
    cout = round((cash["o"] if cash else 0) or 0, 2)
    return {
        "date": d,
        "count": int(r["n"] or 0) if r else 0,
        "gold": round((r["g"] if r else 0) or 0, 3),
        "cash": round((r["c"] if r else 0) or 0, 2),
        "cash_in": cin, "cash_out": cout, "cash_net": round(cin - cout, 2),
    }


def treasury(conn, date=None):
    """أرصدة الخزائن والصندوق الآن — البعد الذي يخصّ كلاً منها.

    يعيد قائمة: [{code, name, dim, gold, cash, negative}]. والسالب
    مُعلَّم صراحةً فلا تُعيد الواجهة استنتاجه.
    """
    d = str(date or today())[:10]
    out = []
    for code, name, dim in WATCH:
        aid = _acc(conn, code)
        if aid is None:
            continue
        try:
            g, c = account_balance(conn, aid, date_to=d)
        except Exception:
            continue
        neg = (dim == "gold" and g < -EPS_GOLD) or \
              (dim == "cash" and c < -EPS_CASH)
        out.append({"code": code, "name": name, "dim": dim,
                    "gold": round(g, 3), "cash": round(c, 2),
                    "negative": bool(neg)})
    return out


def negatives(conn, date=None):
    """الأرصدة السالبة وحدها — ما يستحق تنبيهاً أحمر."""
    return [t for t in treasury(conn, date) if t["negative"]]


# ══════════════════════════════════════════════════════════════════
#  أقدم الديون
# ══════════════════════════════════════════════════════════════════

def oldest_debts(conn, limit=5, days=60, entity_type="customer"):
    """أكبر الديون المتأخّرة فوق `days` يوماً — بترتيب الخطورة.

    يُبنى على `models.aging` نفسه فلا تختلف أرقام الشاشة الأولى عن
    أرقام تقرير أعمار الديون — اختلافُ رقمٍ بين شاشتين يهدم الثقة
    بالنظام كله.
    """
    try:
        from models import aging
        rows = aging.report(conn, entity_type=entity_type)
    except Exception:
        return []
    # الفئتان الأخيرتان (61–90 و+90) هما «المتأخّر» عند حدّ 60 يوماً،
    # والأخيرة وحدها عند حدّ 90 — فالحدّ يختار الفئات لا يُصفّي بعدها.
    first = 3 if int(days) >= 90 else 2
    late = []
    for r in rows:
        g = sum(float(x or 0) for x in r["gold_buckets"][first:])
        c = sum(float(x or 0) for x in r["cash_buckets"][first:])
        if g <= EPS_GOLD and c <= EPS_CASH:
            continue
        late.append({"name": r["name"], "code": r["code"],
                     "gold": round(g, 3), "cash": round(c, 2),
                     "days": int(r.get("days") or 0),
                     "oldest": r.get("oldest") or ""})
    late.sort(key=lambda x: (-x["days"], -x["cash"], -x["gold"]))
    return late[:int(limit)]


# ══════════════════════════════════════════════════════════════════
#  آخر العمليات
# ══════════════════════════════════════════════════════════════════

def recent_ops(conn, limit=6):
    """آخر ما رُحِّل — مستنداً مستنداً، بمصدره ليُفتح بالنقر.

    ترتيبٌ بزمن الإنشاء لا بتاريخ القيد: السؤال هنا «ماذا رُحِّل
    للتوّ؟» لا «ماذا جرى في تاريخ كذا؟» — وقيدٌ بتاريخ قديم رُحِّل
    قبل دقيقة يجب أن يظهر أولاً.
    """
    rows = conn.execute(
        "SELECT e.id, e.entry_date d, e.doc_no, e.description dsc,"
        " e.user_note un, e.source_table st, e.source_id sid,"
        " e.created_by who, e.created_at whn,"
        " ROUND(COALESCE(SUM(l.gold_debit),0),3) g,"
        " ROUND(COALESCE(SUM(l.cash_debit),0),2) c"
        " FROM journal_entries e JOIN journal_lines l ON l.entry_id=e.id"
        " WHERE e.is_deleted=0"
        " GROUP BY e.id ORDER BY e.created_at DESC, e.id DESC"
        " LIMIT ?", (int(limit),)).fetchall()
    try:
        from models.journal import _op_label
    except Exception:
        _op_label = None
    out = []
    for r in rows:
        desc = (r["un"] or "").strip() or (r["dsc"] or "").strip()
        label = ""
        if _op_label is not None:
            try:
                label = _op_label(r["st"], r["dsc"] or "")
            except Exception:
                label = ""
        out.append({
            "id": r["id"], "date": r["d"], "op": label or (r["st"] or "قيد"),
            "doc_no": r["doc_no"] or f"#{r['id']}", "desc": desc,
            "gold": r["g"] or 0.0, "cash": r["c"] or 0.0,
            "who": r["who"] or "", "when": (r["whn"] or "")[:16],
            "src": r["st"], "sid": r["sid"]})
    return out


# ══════════════════════════════════════════════════════════════════
#  اللوحة كاملة
# ══════════════════════════════════════════════════════════════════

def snapshot(conn, date=None, debts=5, ops=6):
    """كل ما تحتاجه الشاشة الأولى في نداء واحد.

    أي جزء يتعذّر لا يُسقط البقية: الشاشة الأولى يجب أن تفتح دائماً،
    فقاعدةٌ ناقصة حساباً لا تمنع عرض حركة اليوم.
    """
    d = str(date or today())[:10]
    out = {"date": d, "pulse": {}, "treasury": [], "negatives": [],
           "debts": [], "ops": []}
    for key, fn in (("pulse", lambda: day_pulse(conn, d)),
                    ("treasury", lambda: treasury(conn, d)),
                    ("debts", lambda: oldest_debts(conn, debts)),
                    ("ops", lambda: recent_ops(conn, ops))):
        try:
            out[key] = fn()
        except Exception:
            pass
    out["negatives"] = [t for t in out["treasury"] if t.get("negative")]
    return out
