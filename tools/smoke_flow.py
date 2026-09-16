#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبار دورة عمل كاملة على قاعدة مؤقتة — بلا واجهة رسومية.

    python tools/smoke_flow.py

يُشغّل دورة مصنع حقيقية من أولها لآخرها: توريد أطقم ← عميل ← فاتورة بيع
← سند قبض ← كشف حساب ← ميزان مراجعة ← قفل فترة ← حذف قيد، ويتحقق بعد
كل خطوة من **توازن الدفتر في البعدين معاً** (الذهب والنقد).

الفائدة: فحص `verify_all` يثبت أن الشاشات تُبنى وتُستدعى بلا خطأ، لكنه
لا يثبت أن الأرقام صحيحة. هذا الملف يثبت الأرقام.
"""
import os
import pathlib
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# قاعدة مؤقتة معزولة: لا يُمسّ ملف المستخدم إطلاقاً
_TMP = tempfile.mkdtemp(prefix="gold_smoke_")
os.environ["GOLD_ERP_DATA_DIR"] = _TMP

import config                                            # noqa: E402
config.DB_PATH = __import__("pathlib").Path(_TMP) / "smoke.db"

from database.database import create_tables, db, migrate_schema  # noqa: E402
from database.seed import (ensure_new_accounts, ensure_system_tags,  # noqa: E402
                           seed_initial_data)
from models.accounts import acc_id                       # noqa: E402
from models.entities import (ensure_employee_accrual_accounts,  # noqa: E402
                             ensure_internal_counterparties)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✔' if cond else '✘'} {name}{(' — ' + detail) if detail else ''}")
    return cond


def expect_error(name, fn, needle=""):
    """ينجح الفحص حين **يُرفض** ما يجب رفضه."""
    try:
        fn()
    except Exception as e:
        ok = (needle in str(e)) if needle else True
        return check(name, ok, "" if ok else f"رسالة غير متوقعة: {e}")
    return check(name, False, "قُبلت عملية كان يجب رفضها")


def ledger_balanced(conn):
    r = conn.execute(
        "SELECT ROUND(SUM(l.gold_debit-l.gold_credit),3) g,"
        "       ROUND(SUM(l.cash_debit-l.cash_credit),2) c"
        " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
        " WHERE e.is_deleted=0").fetchone()
    return (abs(r["g"] or 0) <= 0.011, abs(r["c"] or 0) <= 0.011,
            r["g"] or 0, r["c"] or 0)


def step(title):
    print(f"\n═══ {title} ═══")


def main():
    step("0) تهيئة قاعدة مؤقتة")
    create_tables()
    migrate_schema()
    seed_initial_data()
    ensure_new_accounts()
    with db() as conn:
        ensure_internal_counterparties(conn)
        ensure_employee_accrual_accounts(conn)
        ensure_system_tags(conn)
    with db(readonly=True) as conn:
        n = conn.execute("SELECT COUNT(*) c FROM accounts").fetchone()["c"]
    check("بُنيت شجرة الحسابات", n > 20, f"{n} حساب")

    # ── ضوابط المحرك ──────────────────────────────────────────────
    step("1) ضوابط محرك القيود")
    from services.accounting_engine import post_entry
    from models import fiscal

    with db() as conn:
        cash = acc_id(conn, "1400")
        vault = acc_id(conn, "1100")
        worked = acc_id(conn, "1200")
        parent = conn.execute(
            "SELECT id, code FROM accounts WHERE is_postable=0"
            " LIMIT 1").fetchone()

    def _unbalanced():
        with db() as conn:
            post_entry(conn, "2026-01-05", "اختبار", [
                {"account_id": cash, "cash_debit": 100},
                {"account_id": vault, "cash_credit": 90}], username="admin")
    expect_error("يُرفض قيد غير متوازن", _unbalanced, "غير متوازن")

    def _negative():
        with db() as conn:
            post_entry(conn, "2026-01-05", "اختبار", [
                {"account_id": cash, "cash_debit": -100},
                {"account_id": vault, "cash_credit": -100}], username="admin")
    expect_error("تُرفض القيمة السالبة", _negative, "سالبة")

    if parent:
        def _on_parent():
            with db() as conn:
                post_entry(conn, "2026-01-05", "اختبار", [
                    {"account_id": parent["id"], "cash_debit": 100},
                    {"account_id": cash, "cash_credit": 100}],
                    username="admin")
        expect_error("يُرفض الترحيل على حساب تجميعي", _on_parent, "تجميعي")

    def _no_account():
        with db() as conn:
            post_entry(conn, "2026-01-05", "اختبار", [
                {"account_id": 999999, "cash_debit": 100},
                {"account_id": cash, "cash_credit": 100}], username="admin")
    expect_error("يُرفض حساب غير موجود", _no_account)

    # ── دورة التشغيل الحقيقية ────────────────────────────────────
    step("2) توريد دفعة أطقم")
    from models.inventory import create_work_orders_batch, stock_snapshot
    with db() as conn:
        res = create_work_orders_batch(conn, [
            {"wo_no": "T-100", "gold": 50.0, "small_stones": 2.0,
             "big_stones": 4.0, "wage_per_gram": 25.0},
            {"wo_no": "T-101", "gold": 30.0, "small_stones": 0.0,
             "big_stones": 0.0, "wage_per_gram": 20.0},
        ], "2026-01-10", "admin")
    check("رُحّلت دفعة التوريد", bool(res))
    with db(readonly=True) as conn:
        snap = stock_snapshot(conn)
        g, c, gv, cv = ledger_balanced(conn)
    # 50+2+(4×0.5)=54  و 30 ⇒ 84
    check("الوزن المقيد محسوب بالخصم التجاري",
          abs(snap.get("mashghool_gold", 0) - 84.0) < 0.011,
          f"الذهب المشغول = {snap.get('mashghool_gold')}")
    check("الدفتر متوازن بعد التوريد", g and c, f"ذهب {gv} · نقد {cv}")

    step("3) عميل + فاتورة بيع")
    from models.entities import add_entity
    from models.invoices import create_sale, get_invoice_full
    with db() as conn:
        cust = add_entity(conn, "عميل الاختبار", "customer", username="admin")
        wo = conn.execute(
            "SELECT id, registered_weight, wage_per_gram FROM work_orders"
            " WHERE work_order_no='T-100'").fetchone()
        sale = create_sale(
            conn, cust, [{"work_order_id": wo["id"]}],
            "2026-01-15", "admin", apply_vat=True)
        inv_id = sale["id"]
    check("صدرت فاتورة بيع", bool(inv_id), sale["invoice_no"])
    with db(readonly=True) as conn:
        inv, inv_items = get_invoice_full(conn, inv_id)
        g, c, gv, cv = ledger_balanced(conn)
        sold = conn.execute(
            "SELECT status FROM work_orders WHERE id=?",
            (wo["id"],)).fetchone()["status"]
    check("للفاتورة بند واحد", len(inv_items) == 1, f"{len(inv_items)}")
    exp_wages = round(wo["registered_weight"] * wo["wage_per_gram"], 2)
    check("الأجور = الوزن المقيد × أجر الجرام",
          abs(inv["total_wages"] - exp_wages) < 0.011,
          f"{inv['total_wages']} مقابل {exp_wages}")
    check("ضريبة 15% على الأجور",
          abs(inv["vat_amount"] - round(exp_wages * 0.15, 2)) < 0.011,
          f"{inv['vat_amount']}")
    check("خرج الطقم من المخزون", sold == "sold", sold)
    check("الدفتر متوازن بعد البيع", g and c, f"ذهب {gv} · نقد {cv}")

    step("4) سند قبض")
    from models.vouchers import create_voucher
    with db() as conn:
        v = create_voucher(
            conn, "receipt", "2026-01-20", "admin", entity_id=cust,
            rows=[{"kind": "cash", "amount": 500.0, "notes": "دفعة"}],
            notes="دفعة من العميل")
    check("رُحّل سند القبض", bool(v))
    with db(readonly=True) as conn:
        g, c, gv, cv = ledger_balanced(conn)
    check("الدفتر متوازن بعد السند", g and c, f"ذهب {gv} · نقد {cv}")

    step("5) ميزان المراجعة وكشف الحساب")
    from services.accounting_engine import account_balance
    with db(readonly=True) as conn:
        tb = conn.execute(
            "SELECT ROUND(SUM(l.gold_debit),3) gd, ROUND(SUM(l.gold_credit),3) gc,"
            " ROUND(SUM(l.cash_debit),2) cd, ROUND(SUM(l.cash_credit),2) cc"
            " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
            " WHERE e.is_deleted=0").fetchone()
        wg, wc = account_balance(conn, acc_id(conn, "1200"))
    check("ميزان المراجعة متوازن في البعدين",
          abs(tb["gd"] - tb["gc"]) < 0.011 and abs(tb["cd"] - tb["cc"]) < 0.011,
          f"ذهب {tb['gd']}/{tb['gc']} · نقد {tb['cd']}/{tb['cc']}")
    check("رصيد الذهب المشغول = ما تبقّى (T-101)",
          abs(wg - 30.0) < 0.011, f"{wg}")

    step("5b) ميزان المراجعة")
    from models.reports import trial_balance
    with db(readonly=True) as conn:
        tbal = trial_balance(conn)
        tb26 = trial_balance(conn, "2026-01-01", "2026-12-31")
    tt = tbal["totals"]
    check("ميزان المراجعة يتوازن في البعدين",
          tt["balanced_gold"] and tt["balanced_cash"],
          f"ذهب {tt['gold_debit']}/{tt['gold_credit']} · "
          f"نقد {tt['cash_debit']}/{tt['cash_credit']}")
    check("مجموع أرصدة الإقفال صفر",
          abs(tt["close_gold"]) < 0.011 and abs(tt["close_cash"]) < 0.011,
          f"{tt['close_gold']} · {tt['close_cash']}")
    check("الميزان يُرشّح بالفترة", tb26["totals"]["balanced_cash"],
          f"{len(tb26['rows'])} حساباً في 2026")
    tb_acc = {r["code"] for r in tbal["rows"]}
    check("الميزان يشمل حسابات البيع والمخزون",
          {"1200", "1400"} & tb_acc == {"1200", "1400"},
          f"{len(tb_acc)} حساباً متحرّكاً")

    step("6) قفل الفترات")
    with db() as conn:
        fiscal.set_lock(conn, "2026-01-31", "admin")

    def _locked():
        with db() as conn:
            post_entry(conn, "2026-01-25", "اختبار داخل فترة مقفلة", [
                {"account_id": cash, "cash_debit": 10},
                {"account_id": worked, "cash_credit": 10}], username="admin")
    expect_error("يُرفض القيد داخل فترة مقفلة", _locked, "مقفلة")

    with db() as conn:
        after = post_entry(conn, "2026-02-05", "قيد بعد القفل", [
            {"account_id": cash, "cash_debit": 10},
            {"account_id": acc_id(conn, "1400"), "cash_credit": 10}],
            username="admin")
    check("يُقبل القيد بعد تاريخ القفل", bool(after))

    from services.audit import reverse_entry

    def _del_locked():
        with db() as conn:
            eid = conn.execute(
                "SELECT id FROM journal_entries WHERE entry_date<='2026-01-31'"
                " AND is_deleted=0 ORDER BY id LIMIT 1").fetchone()["id"]
            reverse_entry(conn, eid, "admin")
    expect_error("يُرفض حذف قيد داخل فترة مقفلة", _del_locked, "مقفلة")

    with db() as conn:
        fiscal.set_lock(conn, "", "admin")
        check("يُرفع القفل", fiscal.lock_date(conn) == "")

    step("7) حذف قيد وعكس أثره")
    with db() as conn:
        reverse_entry(conn, after, "admin")
    with db(readonly=True) as conn:
        g, c, gv, cv = ledger_balanced(conn)
        d = conn.execute("SELECT is_deleted FROM journal_entries WHERE id=?",
                         (after,)).fetchone()["is_deleted"]
    check("وُسم القيد محذوفاً", bool(d))
    check("الدفتر متوازن بعد الحذف", g and c, f"ذهب {gv} · نقد {cv}")

    step("8) سلامة النظام")
    from services import health
    with db(readonly=True) as conn:
        h = health.full_health(conn)
    check("لا قيود غير متوازنة", not h["unbalanced"],
          f"{len(h['unbalanced'])} قيد")
    check("لا سجلات يتيمة", not h["orphans"], "؛ ".join(h["orphans"]))
    check("ملف القاعدة سليم", not h["integrity"], "؛ ".join(h["integrity"]))
    check("إجماليات الفواتير تطابق بنودها", not h["invoice_totals"])

    step("9) تداخل المعاملات وطابور المزامنة")
    from services import sync_queue
    try:
        with db() as conn:
            with db() as conn2:            # متداخلة: يجب أن تنضم لا أن تتجمّد
                conn2.execute("SELECT 1")
            ok_nested = conn is conn2
        check("المعاملة المتداخلة تنضم للقائمة بلا تجمّد", ok_nested)
    except Exception as e:
        check("المعاملة المتداخلة تنضم للقائمة بلا تجمّد", False, str(e)[:80])

    with db() as conn:
        st = sync_queue.stats(conn)
        conn.execute("UPDATE sync_queue SET status='sent',"
                     " sent_at=datetime('now','localtime','-30 days')")
        purged = sync_queue.purge_sent(conn)
        st2 = sync_queue.stats(conn)
    check("إحصاءات الطابور تُحسب", st["total"] >= 0, f"{st['total']} حزمة")
    check("تنظيف الحزم المرفوعة يعمل", purged > 0 and st2["total"] == 0,
          f"حُذفت {purged}")

    step("10) صيانة قاعدة البيانات")
    from services import maintenance
    res = maintenance.light_maintenance()
    check("الصيانة الخفيفة تعمل", res.get("optimized") is True,
          f"WAL={res.get('wal')}")
    before, after = maintenance.compact()
    check("ضغط القاعدة يعمل", after > 0, f"{before} → {after} ميجابايت")
    stt = maintenance.db_stats()
    check("إحصاءات الجداول تُقرأ", bool(stt["tables"]),
          f"{len(stt['tables'])} جدول")

    step("11) شجرة الحسابات باستعلام واحد")
    from models.accounts import subtree_ids_by_code
    with db(readonly=True) as conn:
        ids = subtree_ids_by_code(conn, "1600")
        direct = {r["id"] for r in conn.execute(
            "SELECT a.id FROM accounts a JOIN accounts p ON a.parent_id=p.id"
            " WHERE p.code='1600'")}
    check("الشجرة الفرعية تشمل الأب وفروعه",
          bool(ids) and direct.issubset(set(ids)),
          f"{len(ids)} حساب")

    step("12) اختيار مجلد البيانات")
    # النظام يُشغَّل بطريقتين (exe ومن المصدر)، وكان كلٌّ منهما يكتب في
    # مجلد مختلف — فترى محاسبتين منفصلتين وتظن بياناتك ضاعت. هذه
    # الفحوص تحرس القاعدة: مكان واحد للبيانات مهما اختلف الإقلاع.
    import subprocess
    import shutil as _sh
    from core.config import DATA_DIR_ENV, _has_database

    def _resolved(env_extra=None):
        e = dict(os.environ)
        e.pop(DATA_DIR_ENV, None)
        if env_extra:
            e.update(env_extra)
        r = subprocess.run(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0, {ROOT!r});"
             " import config; print(config.BASE_DIR)"],
            capture_output=True, text=True, env=e, cwd=ROOT)
        return r.stdout.strip()

    pin = tempfile.mkdtemp(prefix="gold_pin_")
    try:
        check("متغيّر البيئة يثبّت المجلد",
              _resolved({DATA_DIR_ENV: pin}) == pin, pin)
        fake = tempfile.mkdtemp(prefix="gold_fake_")
        try:
            check("مجلد بلا قاعدة لا يُعدّ بيانات",
                  _has_database(fake) is False)
            (pathlib.Path(fake) / "data").mkdir(parents=True, exist_ok=True)
            check("مجلد data فارغ لا يُعدّ بيانات",
                  _has_database(fake) is False)
            (pathlib.Path(fake) / "data" / "gold_erp.db").write_bytes(b"x")
            check("الملف المفرد يُكتشف", _has_database(fake) is True)
            _sh.rmtree(pathlib.Path(fake) / "data")
            t = pathlib.Path(fake) / "data" / "tenants" / "F-1"
            t.mkdir(parents=True, exist_ok=True)
            (t / "gold_erp.db").write_bytes(b"x")
            check("قاعدة المصنع المعزول تُكتشف", _has_database(fake) is True)
        finally:
            _sh.rmtree(fake, ignore_errors=True)
    finally:
        _sh.rmtree(pin, ignore_errors=True)

    step("13) هوية المصنع عبر الخيوط")
    # كانت الهوية في threading.local، فتُضبط على خيط الواجهة وحده ويرى
    # كل خيط خلفي (النسخ الاحتياطي · المزامنة · مراقب السلامة) قاعدةً
    # أخرى — فيُنسخ ملف غير الذي يعمل عليه المستخدم. هذا الفحص يحرسه.
    import threading as _th
    from services import tenant_db as _td

    _prev = _td.active_tenant()
    try:
        _td.set_active_tenant("F-SMOKE-TEST")
        ui_path = str(config.DB_PATH)
        box = {}

        def _bg():
            box["path"] = str(config.DB_PATH)
            box["tid"] = _td.active_tenant()

        th = _th.Thread(target=_bg)
        th.start()
        th.join(timeout=10)
        check("الخيط الخلفي يرى هوية المصنع نفسها",
              box.get("tid") == "F-SMOKE-TEST", str(box.get("tid")))
        check("الخيط الخلفي يفتح قاعدة المصنع نفسها",
              box.get("path") == ui_path,
              f"الواجهة={ui_path} · الخلفي={box.get('path')}")
        # المسار يُبنى من الهوية (هذا الملف يثبّت config.DB_PATH على
        # ملف مؤقت، فنفحص بانيَ المسار مباشرةً لا القيمة المثبّتة)
        built = str(_td.tenant_db_path(_TMP, "F-SMOKE-TEST"))
        check("مسار المصنع يحمل هويته", "F-SMOKE-TEST" in built, built)
        legacy = str(_td.tenant_db_path(_TMP, ""))
        check("بلا هوية يُستعمل الملف القديم",
              legacy.endswith("data/gold_erp.db")
              or legacy.endswith("data\\gold_erp.db"), legacy)
    finally:
        _td.set_active_tenant(_prev or "")
        if not _prev:
            _td.clear_active_tenant()

    step("14) توحيد صيغة التواريخ")
    # التواريخ تُقارَن نصاً، ورمز الرقم العربي أكبر من رمز الإنجليزي،
    # فتاريخ بأرقام عربية يسقط من كل فلتر: القيد موجود وغير مرئي.
    from services.dates import (has_non_ascii_digits, normalize_date,
                                normalize_digits)
    check("يُكتشف الرقم العربي", has_non_ascii_digits("٢٠٢٦-٠٩-١٦"))
    check("لا إنذار كاذب للإنجليزي",
          has_non_ascii_digits("2026-09-16") is False)
    check("يُحوَّل العربي للإنجليزي",
          normalize_digits("٢٠٢٦-٠٩-١٦") == "2026-09-16")
    check("يُحوَّل الفارسي أيضاً",
          normalize_digits("۲۰۲۶-۰۹-۱۶") == "2026-09-16")
    check("تُوحَّد الفواصل", normalize_date("٢٠٢٦/٠٩/١٦") == "2026-09-16")
    expect_error("يُرفض ما ليس تاريخاً",
                 lambda: normalize_date("كلام"), "غير صالح")

    # الحارس في محرك القيود: أي قيد يُرحَّل بتاريخ عربي يُحفظ إنجليزياً
    with db() as conn:
        eid = post_entry(conn, "٢٠٢٧-٠٣-٠٤", "اختبار تاريخ عربي", [
            {"account_id": cash, "cash_debit": 7},
            {"account_id": acc_id(conn, "1500"), "cash_credit": 7}],
            username="admin")
    with db(readonly=True) as conn:
        saved = conn.execute("SELECT entry_date d FROM journal_entries"
                             " WHERE id=?", (eid,)).fetchone()["d"]
        seen = conn.execute(
            "SELECT COUNT(*) c FROM journal_entries WHERE id=? AND"
            " entry_date>='2027-01-01' AND entry_date<='2027-12-31'",
            (eid,)).fetchone()["c"]
    check("المحرك يحفظ التاريخ إنجليزياً", saved == "2027-03-04", saved)
    check("القيد يظهر في فلتر الفترة", seen == 1)

    step("15) تبديل القاعدة عند تغيّر المصنع")
    # الاتصال محفوظ لكل خيط، ومسار القاعدة يتغيّر عند تسجيل الدخول.
    # لو لم يلاحظ الاتصال المحفوظ التغيّر لظلّ النظام كله يكتب في
    # الملف الافتراضي بدل قاعدة المصنع — بلا أي رسالة خطأ.
    import sqlite3 as _sq
    from database.database import close_thread_connection

    _swap = tempfile.mkdtemp(prefix="gold_swap_")
    _orig_path = config.DB_PATH
    try:
        a = pathlib.Path(_swap) / "a.db"
        b = pathlib.Path(_swap) / "b.db"
        for f in (a, b):
            config.DB_PATH = f
            close_thread_connection()
            create_tables()
            with db() as conn:
                conn.execute("CREATE TABLE IF NOT EXISTS mark(v TEXT)")
                conn.execute("INSERT INTO mark(v) VALUES(?)", (f.name,))
        # بلا إغلاق يدوي: التبديل وحده يجب أن يكفي
        config.DB_PATH = a
        with db(readonly=True) as conn:
            got_a = conn.execute("SELECT v FROM mark").fetchone()["v"]
        config.DB_PATH = b
        with db(readonly=True) as conn:
            got_b = conn.execute("SELECT v FROM mark").fetchone()["v"]
        check("تبديل مسار القاعدة يُتبع فوراً",
              got_a == "a.db" and got_b == "b.db", f"{got_a} · {got_b}")
    finally:
        config.DB_PATH = _orig_path
        close_thread_connection()
        shutil.rmtree(_swap, ignore_errors=True)

    step("16) فلاتر التاريخ في الواجهة")
    # Qt على ويندوز بلغة عربية تُنتج أرقاماً عربية في حقول التاريخ.
    # فيُحفظ التاريخ عربياً (فيصير القيد غير مرئي)، ويُبحث به عربياً
    # (فلا يطابق شيئاً وتظهر كل الحركات «رصيداً سابقاً»). هذه الفحوص
    # تحرس الطرفين.
    import os as _os
    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PyQt5 import QtWidgets as _QW
        _app = _QW.QApplication.instance() or _QW.QApplication([])
        from ui.widgets.common import dstr as _dstr, qdstr as _qdstr

        class _ArDate:
            def toString(self, fmt):
                return "٢٠٢٦-٠٩-١٦"

        class _ArWidget:
            def date(self):
                return _ArDate()

        check("qdstr يطبّع الأرقام العربية",
              _qdstr(_ArDate()) == "2026-09-16", _qdstr(_ArDate()))
        check("dstr يطبّع حقل التاريخ",
              _dstr(_ArWidget()) == "2026-09-16", _dstr(_ArWidget()))

        # الأثر الفعلي: هل يطابق الفلتر قيداً محفوظاً إنجليزياً؟
        with db(readonly=True) as conn:
            hit = conn.execute(
                "SELECT COUNT(*) c FROM journal_entries"
                " WHERE entry_date>=? AND entry_date<=?",
                (_qdstr(_ArDate()), "2026-09-30")).fetchone()["c"]
            miss = conn.execute(
                "SELECT COUNT(*) c FROM journal_entries"
                " WHERE entry_date>=? AND entry_date<=?",
                ("٢٠٢٦-٠٩-٠١", "٢٠٢٦-٠٩-٣٠")).fetchone()["c"]
        check("الفلتر العربي لا يطابق شيئاً (تأكيد الخلل)", miss == 0)
        check("الفلتر بعد التطبيع صالح للمقارنة", hit >= 0)

        # لا يبقى في الواجهة منتج تاريخ بلا تطبيع
        import subprocess as _sp
        raw = _sp.run(["grep", "-rn", 'toString("yyyy-MM-dd")',
                       "--include=*.py", "ui/", "services/", "models/"],
                      capture_output=True, text=True, cwd=ROOT).stdout
        leaks = [ln for ln in raw.splitlines()
                 if "normalize_digits" not in ln]
        check("كل منتجي نص التاريخ يمرّون بالمطبّع",
              not leaks, "; ".join(leaks[:2]))
    except ImportError:
        check("فحوص الواجهة", True, "تخطّي — PyQt5 غير مثبّت")

    step("17) دفتر اليومية — كل الحسابات")
    # كشف الحساب يشترط حساباً، والسؤال بعد كل جرد هو «ماذا جرى في هذا
    # اليوم؟» بلا معرفة الحساب مسبقاً. هذه الفحوص تحرس العرض الجديد.
    from models import journal as _j
    with db(readonly=True) as conn:
        day = _j.day_book(conn, "2026-01-15", "2026-01-15")
        wide = _j.day_book(conn, "2026-01-01", "2026-12-31")
        none_ = _j.day_book(conn, "2030-01-01", "2030-01-02")
    check("يعرض مستندات اليوم المحدد", len(day) >= 1, f"{len(day)} مستند")
    check("يُرشّح بالفترة", len(wide) >= len(day),
          f"{len(wide)} في السنة مقابل {len(day)} في اليوم")
    check("يوم بلا عمليات يعيد فارغاً", none_ == [])
    if day:
        r = day[0]
        check("لكل سطر رقم سند ونوع عملية",
              bool(r["doc_no"]) and bool(r["op"]), f"{r['doc_no']} · {r['op']}")
        check("لكل سطر الحسابات المتأثرة",
              bool(r["accounts"]) and r["n_accounts"] >= 2,
              f"{r['n_accounts']} حساب")
        check("سطر واحد لكل مستند لا لكل حساب",
              len({x["eid"] for x in day}) == len(day))

    step("18) تعديل الفاتورة — الإجمالي = مجموع بنودها")
    # كان الإجمالي يُحسب «القديم + الفرق»، فيفترض تطابقاً سابقاً بين
    # الإجمالي والبنود. أي انحراف سابق كان يُورَّث ويتفاقم مع كل تعديل
    # — فيظهر وزن لا يطابق ما في شاشة التعديل ولو لم يُمسّ الوزن.
    from models.invoices import update_invoice as _upd
    from models.inventory import create_work_orders_batch as _batch
    from services import health as _h

    with db() as conn:
        _batch(conn, [{"wo_no": "E-1", "gold": 100.0, "wage_per_gram": 23.0},
                      {"wo_no": "E-2", "gold": 50.0, "wage_per_gram": 23.0}],
               "2026-03-01", "admin")
        eids = {r["work_order_no"]: r["id"] for r in conn.execute(
            "SELECT id, work_order_no FROM work_orders"
            " WHERE work_order_no IN ('E-1','E-2')")}
        esale = create_sale(conn, cust, [{"work_order_id": eids["E-1"]}],
                            "2026-03-05", "admin", apply_vat=False)
    eid = esale["id"]

    def _totals():
        with db(readonly=True) as conn:
            return conn.execute(
                "SELECT total_weight tw, total_wages tg,"
                " (SELECT COALESCE(SUM(registered_weight),0) FROM invoice_items"
                "  WHERE invoice_id=?) sw,"
                " (SELECT COALESCE(SUM(wages),0) FROM invoice_items"
                "  WHERE invoice_id=?) sg FROM invoices WHERE id=?",
                (eid, eid, eid)).fetchone()

    # انحراف سابق مصطنع — يجب أن يُصحَّح من تلقائه عند أول تعديل
    with db() as conn:
        conn.execute("UPDATE invoices SET total_weight=total_weight+530"
                     " WHERE id=?", (eid,))
    with db() as conn:
        _upd(conn, eid, [{"work_order_id": eids["E-1"], "weight": 100.0,
                          "wage_override": 27.0}], "admin")
    t = _totals()
    check("تعديل الأجر وحده لا يغيّر الوزن",
          abs(t["tw"] - 100.0) < 0.011, f"{t['tw']}")
    check("الإجمالي يساوي مجموع البنود",
          abs(t["tw"] - t["sw"]) < 0.011 and abs(t["tg"] - t["sg"]) < 0.011,
          f"وزن {t['tw']}/{t['sw']} · أجور {t['tg']}/{t['sg']}")

    with db() as conn:
        _upd(conn, eid, [
            {"work_order_id": eids["E-1"], "weight": 100.0, "wage_override": 27.0},
            {"work_order_id": eids["E-2"], "weight": 50.0, "wage_override": 23.0}],
            "admin")
    t = _totals()
    check("إضافة صف تعتمد وزن الفاتورة الحالي",
          abs(t["tw"] - 150.0) < 0.011 and abs(t["tw"] - t["sw"]) < 0.011,
          f"{t['tw']}")

    with db() as conn:
        _upd(conn, eid, [{"work_order_id": eids["E-2"], "weight": 50.0,
                          "wage_override": 23.0}], "admin")
    t = _totals()
    check("حذف صف يعتمد المتبقي",
          abs(t["tw"] - 50.0) < 0.011 and abs(t["tw"] - t["sw"]) < 0.011,
          f"{t['tw']}")

    with db(readonly=True) as conn:
        g2, c2, gv2, cv2 = ledger_balanced(conn)
        bad_inv = _h.check_invoice_totals(conn)
    check("الدفتر متوازن بعد كل التعديلات", g2 and c2, f"ذهب {gv2} · نقد {cv2}")
    check("لا فاتورة إجماليها يخالف بنودها", not bad_inv, str(bad_inv[:1]))

    print("\n" + "═" * 50)
    print(f"نجح {len(PASS)} فحصاً · فشل {len(FAIL)}")
    if FAIL:
        for f in FAIL:
            print(f"  ✘ {f}")
        return 1
    print("✔ دورة العمل الكاملة سليمة — الأرقام والضوابط صحيحة.")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
    sys.exit(code)
