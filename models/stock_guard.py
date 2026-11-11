# -*- coding: utf-8 -*-
"""حارس المخزون الصارم (5.3.2) — الذهب المشغول · ايطالي/نواعم · حركة الأطقم.

**الوعد**: لا تُحفظ عمليةٌ تجعل الدفاتر تختلف عن الواقع. يعمل عند كل حفظ
في النظام — من أي شاشةٍ أو طريق (فاتورة، سند، قيد يدوي، تعديل، حذف،
تحويل…) — لحظةَ ما قبل التثبيت النهائي، فإن وجد خللاً أُلغيت العملية كلها
(لا يُحفظ نصفها) وظهرت للمستخدم رسالةٌ بالسبب وما يفعله.

يفحص ثلاثة أشياء، **ما مسّته العملية فقط**:

1. **الذهب المشغول (1200)** = أوزان الأطقم الموجودة فعلاً في الخزنة (بيتها
   الذهب المشغول). قيدٌ يدوي أو سندٌ على الحساب، أو حذفُ طقمٍ في الخزنة، أو
   أي طريقٍ يغيّر أحدهما دون الآخر ⇒ مرفوض.
2. **ايطالي / نواعم (1210)** = رصيد بطاقتي 0010 و00010.
3. **حركة كل طقمٍ مسّته العملية** منتظمة: لا بيعَ وهو خارج الخزنة، ولا
   مرتجعَ وهو فيها، ولا جزءَ أكبر مما بقي، ولا حركةَ بتاريخٍ يسبق توريده.

**والقديم لا يُعطّل العمل**: فرقٌ قائم قبل الحارس (من بياناتٍ قديمة) يُحفظ
«خطَّ أساس» — العملية تُرفض إن **غيّرته**، لا لأنه موجود. وكذلك سلسلةُ طقمٍ
مكسورةٌ من قبل: تُرفض العملية إن **أضافت** كسراً جديداً. والقائم يُعرض
في «سلامة المخزون» ليُصلَح بمستندٍ صحيح.

**كيف يعرف ما مسّته العملية**: مشغّلاتٌ مؤقتة (TEMP TRIGGER) على الاتصال
تسجّل في جدولٍ مؤقت كل سطر قيدٍ وطقمٍ وفاتورةٍ تغيّر — بلا كلفةٍ تُذكر،
وتُمحى مع التراجع تلقائياً لأن الجدول جزءٌ من المعاملة.
"""
import contextlib
import json
import threading

from services import numfmt as _nf

TOL = 0.011                       # فرق ميزان لا يُعدّ خللاً
STATE_TABLE = "stock_guard_state"
_LOCAL = threading.local()

_TRIGGERS = (
    # أسطر القيود: الحساب الذي تغيّر رصيده
    ("sg_jl_i", "AFTER INSERT ON main.journal_lines",
     "INSERT INTO sg_touch VALUES('acc', NEW.account_id);"),
    ("sg_jl_d", "AFTER DELETE ON main.journal_lines",
     "INSERT INTO sg_touch VALUES('acc', OLD.account_id);"),
    ("sg_jl_u", "AFTER UPDATE ON main.journal_lines",
     "INSERT INTO sg_touch VALUES('acc', NEW.account_id);"
     "INSERT INTO sg_touch VALUES('acc', OLD.account_id);"),
    # حذف قيدٍ أو تغيير تاريخه
    ("sg_je_u", "AFTER UPDATE ON main.journal_entries",
     "INSERT INTO sg_touch VALUES('je', NEW.id);"),
    # الأطقم
    ("sg_wo_i", "AFTER INSERT ON main.work_orders",
     "INSERT INTO sg_touch VALUES('wo', NEW.id);"),
    ("sg_wo_u", "AFTER UPDATE ON main.work_orders",
     "INSERT INTO sg_touch VALUES('wo', NEW.id);"),
    ("sg_wo_d", "AFTER DELETE ON main.work_orders",
     "INSERT INTO sg_touch VALUES('wo', OLD.id);"),
    # أسطر الفواتير: الطقم وفاتورته
    ("sg_it_i", "AFTER INSERT ON main.invoice_items",
     "INSERT INTO sg_touch VALUES('wo', NEW.work_order_id);"
     "INSERT INTO sg_touch VALUES('inv', NEW.invoice_id);"),
    ("sg_it_d", "AFTER DELETE ON main.invoice_items",
     "INSERT INTO sg_touch VALUES('wo', OLD.work_order_id);"
     "INSERT INTO sg_touch VALUES('inv', OLD.invoice_id);"),
    ("sg_it_u", "AFTER UPDATE ON main.invoice_items",
     "INSERT INTO sg_touch VALUES('wo', NEW.work_order_id);"
     "INSERT INTO sg_touch VALUES('wo', OLD.work_order_id);"
     "INSERT INTO sg_touch VALUES('inv', NEW.invoice_id);"),
    # الفاتورة نفسها: تاريخها أو حذفها يغيّر سلسلة أطقمها
    ("sg_inv_u", "AFTER UPDATE ON main.invoices",
     "INSERT INTO sg_touch VALUES('inv', NEW.id);"),
)


class StockGuardError(ValueError):
    """عمليةٌ رُفضت لأنها تُحدث فرقاً بين الدفاتر والواقع."""


# ─────────────────────────────── التثبيت على الاتصال
def install(conn):
    """يضع المشغّلات المؤقتة على هذا الاتصال (مرةً واحدة). يعيد True إن
    صار الحارس جاهزاً — وقاعدةٌ لم تُنشأ جداولها بعد تُجرَّب لاحقاً."""
    try:
        have = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_temp_master WHERE type='trigger'"
            " AND name LIKE 'sg_%'")}
        if len(have) >= len(_TRIGGERS):
            return True
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        need = {"journal_lines", "journal_entries", "work_orders",
                "invoice_items", "invoices"}
        if not need <= tables:
            return False
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS sg_touch"
                     "(kind TEXT, ref INTEGER)")
        for name, when, body in _TRIGGERS:
            if name not in have:
                conn.execute(f"CREATE TEMP TRIGGER IF NOT EXISTS {name}"
                             f" {when} BEGIN {body} END")
        return True
    except Exception:
        return False


# ─────────────────────────────── تجاوزٌ صريح للعمليات النظامية
@contextlib.contextmanager
def allow(reason="", conn=None):
    """عمليةٌ نظامية تُصلح الفرق نفسه (ترقية، تسوية جرد…) — بلا فحص.

    مع `conn`: ما كتبته الكتلة يُعتمد خطَّ أساسٍ جديداً عند خروجها، فلا
    يُفحص عند تثبيت المعاملة (المعاملة كلها تُلغى إن فشل شيءٌ بعدها،
    وخطّ الأساس معها لأنه في القاعدة نفسها)."""
    prev = getattr(_LOCAL, "allow", None)
    _LOCAL.allow = reason or "تجاوز"
    try:
        yield
    finally:
        _LOCAL.allow = prev
    if conn is not None:
        rebase(conn)


def rebase(conn, why=""):
    """يعتمد الوضع الحالي خطَّ أساس (بعد عمليةٍ نظامية مقصودة) — وتغيّرُ
    الفرق بها يُسجَّل في السجل ليُرى."""
    try:
        conn.execute("DELETE FROM sg_touch")
    except Exception:
        pass
    try:
        if _get(conn, "ready") != "1":
            return
        _absorb(conn, worked(conn), italian(conn), why)
    except Exception:
        pass


def _absorb(conn, w, it, why=""):
    for key, cur, label in (("worked_diff", w, "الذهب المشغول"),
                            ("italian_diff", it, "ايطالي/نواعم")):
        if cur is None:
            continue
        old = _get(conn, key)
        if old is not None and abs(float(old) - cur["diff"]) > TOL:
            try:
                from services.audit import log_action
                log_action(conn, "system", "stock_guard_drift", "accounts",
                           None, f"{label}: فرق الدفتر عن الواقع تغيّر من "
                           f"{_g(float(old))} إلى {_g(cur['diff'])} جم"
                           + (f" — {why}" if why else
                              " — خارج العمليات المعتادة"))
            except Exception:
                pass
        if old is None or abs(float(old) - cur["diff"]) > 0.0005:
            _set(conn, key, cur["diff"])


def _bypassed():
    return bool(getattr(_LOCAL, "allow", None))


# ─────────────────────────────── الأرقام
def _acc(conn, code):
    r = conn.execute("SELECT id FROM accounts WHERE code=?",
                     (code,)).fetchone()
    return int(r["id"]) if r else None


def _gl(conn, acc_id):
    if not acc_id:
        return 0.0
    r = conn.execute(
        "SELECT COALESCE(SUM(l.gold_debit-l.gold_credit),0) g"
        " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
        " WHERE e.is_deleted=0 AND l.account_id=?", (acc_id,)).fetchone()
    return round(float(r["g"] or 0.0), 3)


def worked(conn):
    """{"gl", "stock", "diff", "count"} للذهب المشغول — الدفتر والخزنة."""
    fin = _acc(conn, "1200")
    if not fin:
        return None
    cols = {r[1] for r in conn.execute("PRAGMA table_info(work_orders)")}
    svc = " AND COALESCE(is_service,0)=0" if "is_service" in cols else ""
    home = (" AND COALESCE(stock_account_id, ?)=?"
            if "stock_account_id" in cols else "")
    rem = ("COALESCE(remaining_weight, registered_weight)"
           if "remaining_weight" in cols else "registered_weight")
    p = [fin, fin] if home else []
    r = conn.execute(
        f"SELECT COUNT(*) n, COALESCE(SUM({rem}),0) w FROM work_orders"
        " WHERE is_deleted=0 AND status='in_stock' AND COALESCE(is_bulk,0)=0"
        + svc + home, p).fetchone()
    gl = _gl(conn, fin)
    st = round(float(r["w"] or 0.0), 3)
    return {"gl": gl, "stock": st, "diff": round(gl - st, 3),
            "count": int(r["n"] or 0)}


def italian(conn):
    """{"gl", "stock", "diff"} لحساب ايطالي/نواعم — الدفتر والبطاقتان."""
    try:
        from models import italian as _it
        a = _it.account_id(conn)
        if not a:
            return None
        cards = round(sum(c["balance"] for c in _it.cards(conn)), 3)
        gl = _it.account_balance(conn)
    except Exception:
        return None
    return {"gl": gl, "stock": cards, "diff": round(gl - cards, 3),
            "count": None}


# ─────────────────────────────── خطّ الأساس (في القاعدة نفسها)
def _state_table(conn):
    conn.execute(f"CREATE TABLE IF NOT EXISTS {STATE_TABLE}"
                 "(key TEXT PRIMARY KEY, val TEXT)")


def _get(conn, key):
    try:
        r = conn.execute(f"SELECT val FROM {STATE_TABLE} WHERE key=?",
                         (key,)).fetchone()
        return None if r is None else r["val"]
    except Exception:
        return None


def _set(conn, key, val):
    _state_table(conn)
    conn.execute(f"INSERT INTO {STATE_TABLE}(key,val) VALUES(?,?)"
                 " ON CONFLICT(key) DO UPDATE SET val=excluded.val",
                 (key, str(val)))


def _chain_bad(conn, wo_ids):
    """{معرّف فاتورة: رقم الطقم} — الحركات الكاسرة لسلاسل هذه الأطقم:
    بيعٌ وهو خارج الخزنة، مرتجعٌ وهو فيها، جزءٌ أكبر مما بقي، أو حركةٌ
    بتاريخٍ يسبق توريده."""
    from models import wo_moves as wm
    ids = [int(i) for i in wo_ids if i]
    if not ids:
        return {}
    singles = set(wm._singles(conn, ids))
    out = {}
    for wid in singles:
        wo = wm._wo(conn, wid)
        if wo is None:
            continue
        for m in wm.violations(wm.moves_of(conn, wid), wm.birth(wo),
                               wm._full(wo)):
            out[int(m["id"])] = wo["work_order_no"]
    if singles:
        q = ",".join("?" * len(singles))
        for r in conn.execute(
                "SELECT i.id, w.work_order_no FROM invoice_items it"
                " JOIN invoices i ON i.id=it.invoice_id AND i.is_deleted=0"
                " JOIN work_orders w ON w.id=it.work_order_id"
                " JOIN journal_entries e ON e.id=w.entry_id"
                f" WHERE it.work_order_id IN ({q})"
                " AND i.kind IN ('sale','sale_return')"
                " AND i.invoice_date < e.entry_date", list(singles)):
            out[int(r["id"])] = r["work_order_no"]
    return out


def init(conn, force=False):
    """يحفظ خطّ الأساس — يُستدعى في تجهيز القاعدة عند كل إقلاع.

    أول مرة: الفروق القائمة والسلاسل المكسورة القديمة تُسجَّل كما هي (فلا
    يتعطّل العمل بسببها). وبعدها: يُحدَّث رقمها إن تغيّر من خارج الحارس.
    """
    _state_table(conn)
    w = worked(conn)
    it = italian(conn)
    _absorb(conn, w, it, "عند الإقلاع")
    if force or _get(conn, "legacy_bad") is None:
        try:
            from models import wo_moves as wm
            bad = {}
            for wo, inv_ids in wm.irregular(conn, limit=100000):
                for i in inv_ids:
                    bad[int(i)] = wo["work_order_no"]
            ids = [r[0] for r in conn.execute(
                "SELECT DISTINCT it.work_order_id FROM invoice_items it"
                " JOIN invoices i ON i.id=it.invoice_id AND i.is_deleted=0"
                " JOIN work_orders w ON w.id=it.work_order_id"
                " JOIN journal_entries e ON e.id=w.entry_id"
                " WHERE i.kind IN ('sale','sale_return')"
                " AND i.invoice_date < e.entry_date")]
            bad.update(_chain_bad(conn, ids))
        except Exception:
            bad = {}
        _set(conn, "legacy_bad", json.dumps(sorted(bad)))
    _set(conn, "ready", "1")
    try:                     # ما كتبه تجهيز الإقلاع لا يُفحص
        conn.execute("DELETE FROM sg_touch")
    except Exception:
        pass


def ensure_ready(conn):
    """قاعدةٌ لم يُحفظ لها خطّ أساس (أول تشغيلٍ بالإصدار أو قاعدةٌ جديدة):
    يُحفظ الآن — في أول معاملة كتابة، قبل أن تكتب شيئاً."""
    try:
        if _get(conn, "ready") != "1":
            init(conn)
    except Exception:
        pass


def _legacy(conn):
    try:
        return set(json.loads(_get(conn, "legacy_bad") or "[]"))
    except Exception:
        return set()


# ─────────────────────────────── الفحص قبل التثبيت
def mode():
    """"on" (الافتراضي: يرفض) · "report" (يسجّل ولا يرفض — للاختبار) ·
    "off" (معطّل). من `JADEITE_STOCK_GUARD`."""
    import os
    v = (os.environ.get("JADEITE_STOCK_GUARD") or "on").strip().lower()
    return {"0": "off", "off": "off", "report": "report"}.get(v, "on")


REPORTED = []          # ما سُجّل في وضع "report" (للاختبارات)


def check(conn):
    """يُستدعى في `db()` قبل COMMIT. يرفع `StockGuardError` إن خالفت
    العملية — فتُلغى كلها. لا يفعل شيئاً إن لم تمسّ العملية مخزوناً.

    عطلٌ داخل الحارس نفسه لا يوقف العمل — يُسجَّل في سجل الأخطاء."""
    try:
        rows = conn.execute("SELECT kind, ref FROM sg_touch").fetchall()
    except Exception:
        return
    if not rows:
        return
    try:
        conn.execute("DELETE FROM sg_touch")
        if _bypassed() or mode() == "off" or _get(conn, "ready") != "1":
            return
        problems = _problems(conn, rows)
    except StockGuardError:
        raise
    except Exception as ex:
        try:
            from services.health import log_error
            log_error("stock_guard.check", ex)
        except Exception:
            pass
        return
    if not problems:
        return
    msg = ("رُفضت العملية ولم يُحفظ منها شيء — حمايةً للحسابات:\n\n"
           + "\n\n".join(problems))
    if mode() == "report":
        import traceback
        REPORTED.append((msg, "".join(traceback.format_stack(limit=14))))
        rebase(conn)
        try:
            from models import wo_moves as wm
            bad = {}
            for wo, ids in wm.irregular(conn, limit=100000):
                bad.update({int(i): wo["work_order_no"] for i in ids})
            _set(conn, "legacy_bad", json.dumps(sorted(set(bad) | _legacy(conn))))
        except Exception:
            pass
        return
    raise StockGuardError(msg)


def _problems(conn, rows):
    accs = {r["ref"] for r in rows if r["kind"] == "acc"}
    wos = {r["ref"] for r in rows if r["kind"] == "wo" and r["ref"]}
    invs = {r["ref"] for r in rows if r["kind"] == "inv" and r["ref"]}
    jes = {r["ref"] for r in rows if r["kind"] == "je" and r["ref"]}
    if invs:
        q = ",".join("?" * len(invs))
        wos |= {r[0] for r in conn.execute(
            f"SELECT work_order_id FROM invoice_items WHERE invoice_id IN ({q})",
            list(invs))}
    if jes:
        # قيد توريدٍ تغيّر تاريخه أو حُذف: أطقمه
        q = ",".join("?" * len(jes))
        wos |= {r[0] for r in conn.execute(
            f"SELECT id FROM work_orders WHERE is_deleted=0 AND entry_id IN ({q})",
            list(jes))}
    wos.discard(None)
    problems = []

    fin, ita = _acc(conn, "1200"), _acc(conn, "1210")
    if jes or wos or (fin and fin in accs):
        w = worked(conn)
        if w is not None:
            base = float(_get(conn, "worked_diff") or 0.0)
            if abs(w["diff"] - base) > TOL:
                problems.append(_worked_msg(w, base))
            elif abs(w["diff"] - base) > 0.0005:
                _set(conn, "worked_diff", w["diff"])
    if jes or wos or (ita and ita in accs):
        it = italian(conn)
        if it is not None:
            base = float(_get(conn, "italian_diff") or 0.0)
            if abs(it["diff"] - base) > TOL:
                problems.append(_italian_msg(it, base))
            elif abs(it["diff"] - base) > 0.0005:
                _set(conn, "italian_diff", it["diff"])
    if wos:
        bad = _chain_bad(conn, wos)
        legacy = _legacy(conn)
        new = {i: no for i, no in bad.items() if i not in legacy}
        if new:
            problems.append(_chain_msg(conn, new))
        else:
            # ما أُصلح من القديم يخرج من القائمة
            q = ",".join("?" * len(wos))
            mine = {r[0] for r in conn.execute(
                "SELECT invoice_id FROM invoice_items"
                f" WHERE work_order_id IN ({q})", list(wos))}
            keep = (legacy - mine) | set(bad)
            if keep != legacy:
                _set(conn, "legacy_bad", json.dumps(sorted(keep)))
    return problems


def _g(v):
    return _nf.f2(v)


def _worked_msg(w, base):
    delta = round(w["diff"] - base, 3)
    more = "أكثر" if delta > 0 else "أقل"
    return (f"• الذهب المشغول (1200): كانت العملية ستجعل رصيد الحساب "
            f"{more} من أوزان الأطقم الموجودة فعلاً في الخزنة بـ "
            f"{_g(abs(delta))} جم.\n"
            "  الحساب يتحرّك مع الأطقم وحدها: التوريد يُدخل، والبيع يُخرج، "
            "والمرتجع يُعيد. لا يُقبل قيدٌ يدوي أو سندٌ على هذا الحساب، ولا "
            "حذفُ طقمٍ في الخزنة أو تعديلُ وزنه دون مستنده.")


def _italian_msg(it, base):
    delta = round(it["diff"] - base, 3)
    return (f"• ايطالي / نواعم (1210): كانت العملية ستجعل رصيد الحساب "
            f"يختلف عن رصيد بطاقتي 0010 و00010 بـ {_g(abs(delta))} جم.\n"
            "  الحساب يتحرّك مع الرقمين التجميعيين وحدهما (توريد · بيع · "
            "مرتجع) — لا بقيدٍ يدوي ولا بسند.")


def _chain_msg(conn, new):
    q = ",".join("?" * len(new))
    rows = conn.execute(
        "SELECT id, invoice_no, invoice_date, kind FROM invoices"
        f" WHERE is_deleted=0 AND id IN ({q})", list(new)).fetchall()
    lines = []
    for r in rows[:12]:
        kind = "بيع" if r["kind"] == "sale" else "مرتجع"
        lines.append(f"   - الطقم {new[r['id']]}: {kind} {r['invoice_no'] or ''}"
                     f" بتاريخ {r['invoice_date']}")
    more = (f"\n   … و{len(rows) - 12} غيرها" if len(rows) > 12 else "")
    return ("• حركة الأطقم: كانت العملية ستجعل حركة طقمٍ غير منتظمة — بيعٌ "
            "وهو ليس في الخزنة، أو مرتجعٌ وهو فيها، أو وزنٌ أكبر مما بقي، أو "
            "حركةٌ بتاريخٍ يسبق توريده أو حركته السابقة:\n"
            + "\n".join(lines) + more
            + "\n  راجع تاريخ المستند أو ترتيب الحركات (بيع ثم مرتجع ثم بيع…).")


# ─────────────────────────────── التقرير (شاشة سلامة المخزون)
def report(conn):
    """الوضع الآن: الحسابان مقابل الواقع، والسلاسل المكسورة القائمة."""
    w = worked(conn)
    it = italian(conn)
    legacy = _legacy(conn)
    rows = []
    if legacy:
        q = ",".join("?" * len(legacy))
        rows = [dict(r) for r in conn.execute(
            "SELECT i.id, i.invoice_no, i.invoice_date, i.kind,"
            " COALESCE(e.name,'—') party FROM invoices i"
            " LEFT JOIN entities e ON e.id=i.customer_id"
            f" WHERE i.id IN ({q}) AND i.is_deleted=0"
            " ORDER BY i.invoice_date, i.id", sorted(legacy))]
    return {"worked": w, "italian": it, "broken": rows,
            "ready": _get(conn, "ready") == "1"}
