# -*- coding: utf-8 -*-
"""مراقب سلامة النظام — طبقة أمان بمعايير أنظمة ERP.

**الغرض**: لا يكفي أن يعمل النظام؛ يجب أن **يُثبت** أنه يعمل، وأن
يُنذر قبل وقوع الخلل لا بعده. هذه الوحدة تراقب ثلاثة أمور:

1. **سلامة القيد المزدوج** — أي اختلال في ميزان الذهب أو النقد
   يُكتشف فوراً بدل أن يظهر في تقرير بعد شهر.
2. **سلامة قاعدة البيانات** — فحص دوري خفيف يكشف التلف مبكراً.
3. **سجل الأخطاء** — كل استثناء يُسجَّل بمكانه وزمنه، فيُشخَّص
   الخلل بدل التخمين.
"""
import datetime as _dt
import json
import threading
import traceback
from pathlib import Path

import config

ERROR_LOG = "system_errors.log"
MAX_LOG_KB = 512


# ══════════════════════════════════════════════════════════════════
# 1) سجل الأخطاء
# ══════════════════════════════════════════════════════════════════

def _log_path():
    d = Path(config.BASE_DIR) / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d / ERROR_LOG


def log_slow(stage, seconds, extra=""):
    """يسجّل عمليةً استغرقت أطول مما ينبغي.

    التجمّد اللحظي («لا يستجيب») أصعب ما يُشخَّص، لأنه يزول قبل أن
    يصل الخبر. تسجيل مرحلته وزمنها يحوّل الشكوى إلى دليل: نعرف أي
    خطوة تحديداً أبطأت، على جهاز المستخدم لا على جهاز التطوير.
    """
    try:
        p = _log_path()
        stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"[{stamp}] بطء: {stage} — {seconds:.1f} ثانية"
                    + (f" | {extra}" if extra else "") + "\n")
        return True
    except Exception:
        return False


def log_error(where, exc, extra=""):
    """يسجّل استثناءً بمكانه وأثره الكامل.

    الأخطاء الصامتة تُفقد الثقة بالنظام؛ تسجيلها يجعل التشخيص
    دقيقاً بدل التخمين، ولا يزعج المستخدم أثناء عمله.
    """
    try:
        p = _log_path()
        # تدوير السجل فلا يكبر بلا حد
        if p.exists() and p.stat().st_size > MAX_LOG_KB * 1024:
            p.write_text("", encoding="utf-8")
        stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tb = "".join(traceback.format_exception(
            type(exc), exc, exc.__traceback__))[-2000:]
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"\n{'=' * 60}\n[{stamp}] {where}\n")
            if extra:
                f.write(f"سياق: {extra}\n")
            f.write(tb)
        return True
    except Exception:
        return False


def recent_errors(n=20):
    """آخر الأخطاء المسجّلة — لعرضها في شاشة الصيانة."""
    try:
        p = _log_path()
        if not p.exists():
            return []
        blocks = p.read_text(encoding="utf-8").split("=" * 60)
        return [b.strip() for b in blocks if b.strip()][-n:]
    except Exception:
        return []


def clear_errors():
    try:
        _log_path().write_text("", encoding="utf-8")
        return True
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════
# 2) فحص سلامة القيد المزدوج
# ══════════════════════════════════════════════════════════════════

def check_double_entry(conn):
    """يتحقق أن كل قيد متوازن في الذهب والنقد معاً.

    اختلال قيد واحد يُفسد كل التقارير بعده، فاكتشافه فوراً أهم من
    أي ميزة. يعيد قائمة القيود المختلّة (فارغة = سليم).
    """
    from services.accounting_engine import CASH_TOL, GOLD_TOL
    # الترشيح داخل SQL عبر HAVING: الصيغة السابقة كانت تجلب **كل**
    # قيود الدفتر إلى بايثون ثم تتجاهل 99.99% منها. على دفتر فيه عشرات
    # الآلاف من القيود يعني ذلك ميجابايتات تُنقل كل نصف ساعة بلا فائدة.
    rows = conn.execute(
        "SELECT e.id, e.doc_no, e.entry_date, e.description,"
        " ROUND(SUM(l.gold_debit),3) gd, ROUND(SUM(l.gold_credit),3) gc,"
        " ROUND(SUM(l.cash_debit),2) cd, ROUND(SUM(l.cash_credit),2) cc"
        " FROM journal_entries e JOIN journal_lines l ON l.entry_id=e.id"
        " WHERE e.is_deleted=0 GROUP BY e.id"
        " HAVING ABS(SUM(l.gold_debit)-SUM(l.gold_credit)) > ?"
        "     OR ABS(SUM(l.cash_debit)-SUM(l.cash_credit)) > ?"
        " LIMIT 500", (GOLD_TOL, CASH_TOL)).fetchall()
    bad = []
    for r in rows:
        dg = abs((r["gd"] or 0) - (r["gc"] or 0))
        dc = abs((r["cd"] or 0) - (r["cc"] or 0))
        if dg > GOLD_TOL or dc > CASH_TOL:
            bad.append({
                "id": r["id"], "doc_no": r["doc_no"] or f"#{r['id']}",
                "date": r["entry_date"],
                "description": (r["description"] or "")[:50],
                "gold_diff": round(dg, 3), "cash_diff": round(dc, 2)})
    return bad


def check_orphans(conn):
    """يكشف السجلات اليتيمة: مستند بلا قيد أو قيد بلا أسطر."""
    out = []
    r = conn.execute(
        "SELECT COUNT(*) c FROM journal_entries e"
        " WHERE e.is_deleted=0 AND NOT EXISTS"
        " (SELECT 1 FROM journal_lines l WHERE l.entry_id=e.id)").fetchone()
    if r["c"]:
        out.append(f"{r['c']} قيد بلا أسطر")
    for tbl, label in (("invoices", "فاتورة"), ("vouchers", "سند")):
        try:
            r = conn.execute(
                f"SELECT COUNT(*) c FROM {tbl} t WHERE t.is_deleted=0"
                f" AND (t.entry_id IS NULL OR NOT EXISTS"
                f" (SELECT 1 FROM journal_entries e"
                f"  WHERE e.id=t.entry_id AND e.is_deleted=0))").fetchone()
            if r["c"]:
                out.append(f"{r['c']} {label} بلا قيد محاسبي")
        except Exception:
            pass
    return out


def check_db_integrity(conn):
    """فحص سلامة ملف قاعدة البيانات (كشف التلف مبكراً)."""
    try:
        r = conn.execute("PRAGMA quick_check(1)").fetchone()
        v = list(r)[0] if r else "unknown"
        return [] if str(v).lower() == "ok" else [f"تلف محتمل: {v}"]
    except Exception as e:
        return [f"تعذّر الفحص: {type(e).__name__}"]


def check_invoice_totals(conn):
    """يطابق إجماليات الفاتورة مع مجموع بنودها.

    التعديل في المكان يغيّر البنود والإجماليات معاً؛ لو انفصلا لسبب
    ما لظهرت الفاتورة بمبلغ لا يطابق تفصيلها — وهو خلل يمرّ صامتاً
    في الطباعة والكشوف. هذا الفحص يلتقطه فوراً.
    """
    bad = []
    for r in conn.execute(
            "SELECT i.id, i.invoice_no,"
            " ROUND(i.total_weight,3) tw, ROUND(i.total_wages,2) tg,"
            " ROUND(COALESCE(SUM(it.registered_weight),0),3) sw,"
            " ROUND(COALESCE(SUM(it.wages),0),2) sg"
            " FROM invoices i"
            " LEFT JOIN invoice_items it ON it.invoice_id=i.id"
            " WHERE i.is_deleted=0 GROUP BY i.id"
            " HAVING ABS(i.total_weight"
            "   - COALESCE(SUM(it.registered_weight),0)) > 0.011"
            "     OR ABS(i.total_wages"
            "   - COALESCE(SUM(it.wages),0)) > 0.011"
            " LIMIT 500"):
        dw = abs((r["tw"] or 0) - (r["sw"] or 0))
        dg = abs((r["tg"] or 0) - (r["sg"] or 0))
        if dw > 0.011 or dg > 0.011:
            bad.append({"invoice": r["invoice_no"], "id": r["id"],
                        "weight_diff": round(dw, 3),
                        "wages_diff": round(dg, 2)})
    return bad


# الحسابات المادية: ما فيها موجودٌ فعلاً في الخزنة أو الدرج
NEGATIVE_WATCH = {
    "1100": "خزينة التصنيع",
    "1200": "الذهب المشغول",
    "1310": "صندوق الكسر",
    "1350": "الصب والتصفية",
    "1400": "الصندوق النقدي",
    "1500": "البنك",
}


def check_negative_stock(conn):
    """أرصدةٌ مادية صارت سالبة — قراءةٌ لا مَنع.

    **لماذا هنا لا عند الترحيل**: كان في النظام حارسٌ يفحص كل قيدٍ
    لحظةَ ترحيله وينبّه. وأُلغي لأن الرصيد السالب في مصنعٍ يعمل حالةٌ
    واقعية — بضاعةٌ تخرج قبل أن يُسجَّل توريدها — فكان التنبيه يتكرّر
    على عملياتٍ سليمة حتى صار يُتجاهَل، وهذا أسوأ من غيابه.

    لكنّ السالب **الباقي** آخرَ الشهر خللٌ حقيقي: توريدٌ لم يُسجَّل،
    أو وزنٌ خرج مرتين، أو عيارٌ أُدخل خطأ. فمكانه تقريرٌ يُقرأ عند
    المراجعة لا نافذةٌ تقاطع البيع. تُقرأ الأرصدة كما هي، ولا يُمنع
    شيء ولا يُكتب شيء.
    """
    bad = []
    for code, name in NEGATIVE_WATCH.items():
        r = conn.execute(
            "SELECT COALESCE(SUM(l.gold_debit-l.gold_credit),0) g,"
            "       COALESCE(SUM(l.cash_debit-l.cash_credit),0) c"
            " FROM journal_lines l"
            " JOIN journal_entries e ON e.id=l.entry_id"
            " JOIN accounts a ON a.id=l.account_id"
            " WHERE a.code=? AND e.is_deleted=0", (code,)).fetchone()
        g = round(float(r["g"] or 0), 3)
        c = round(float(r["c"] or 0), 2)
        # هامشٌ يتجاوز خطأ التقريب وحده — لا يُقلق على مليغرام
        if g < -0.011 or c < -0.011:
            bad.append({"code": code, "name": name,
                        "gold": g if g < -0.011 else 0.0,
                        "cash": c if c < -0.011 else 0.0})
    return bad


def full_health(conn):
    """تقرير صحة شامل — يُعرض في شاشة الصيانة."""
    unbalanced = check_double_entry(conn)
    orphans = check_orphans(conn)
    integrity = check_db_integrity(conn)
    errors = recent_errors(5)
    inv_bad = check_invoice_totals(conn)
    try:
        negatives = check_negative_stock(conn)
    except Exception:
        negatives = []
    # السالب **لا يُفشل** التقرير: حالةٌ تُراجَع لا خللٌ في الدفتر،
    # والدفتر قد يكون متوازناً تماماً ورصيدُه سالب.
    ok = not (unbalanced or orphans or integrity or inv_bad)
    return {
        "invoice_totals": inv_bad,
        "negatives": negatives,
        "ok": ok,
        "unbalanced": unbalanced,
        "orphans": orphans,
        "integrity": integrity,
        "recent_errors": len(recent_errors(100)),
        "last_errors": errors,
    }


# ══════════════════════════════════════════════════════════════════
# 3) مراقب دوري خفيف
# ══════════════════════════════════════════════════════════════════

class HealthWorker(threading.Thread):
    """فحص دوري صامت — ينذر عند أول اختلال بدل انتظار التقارير."""

    def __init__(self, interval=1800, on_alert=None):
        super().__init__(daemon=True, name="JadeiteHealth")
        self.interval = interval
        self.on_alert = on_alert
        self._stop = threading.Event()
        self.last = {"when": "", "ok": True, "issues": []}

    def stop(self):
        self._stop.set()

    def run(self):
        if self._stop.wait(timeout=120):
            return
        while True:
            try:
                from database.database import db
                # فحص قراءة خالص: `BEGIN IMMEDIATE` كان يحجز قفل
                # الكتابة طوال مسح جدول القيود كاملاً — فيتجمّد حفظ
                # أي مستند في تلك اللحظة بلا سبب ظاهر للمستخدم.
                with db(readonly=True) as conn:
                    unbalanced = check_double_entry(conn)
                    orphans = check_orphans(conn)
                issues = []
                if unbalanced:
                    issues.append(f"{len(unbalanced)} قيد غير متوازن")
                issues += orphans
                self.last = {
                    "when": _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "ok": not issues, "issues": issues}
                if issues and callable(self.on_alert):
                    self.on_alert(issues)
            except Exception as e:
                log_error("HealthWorker", e)
            if self._stop.wait(timeout=self.interval):
                return


_worker = None


def start_health_worker(interval=1800, on_alert=None):
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = HealthWorker(interval, on_alert)
        _worker.start()
    return _worker


def status():
    return dict(_worker.last) if _worker else {
        "when": "", "ok": True, "issues": []}
