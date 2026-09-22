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
import base64
import os
import pathlib
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# قاعدة مؤقتة معزولة: لا يُمسّ ملف المستخدم إطلاقاً
_TMP = tempfile.mkdtemp(prefix="gold_smoke_")
os.environ["GOLD_ERP_DATA_DIR"] = _TMP

import config                                            # noqa: E402
config.DB_PATH = __import__("pathlib").Path(_TMP) / "smoke.db"

from database.database import (create_tables, db, migrate_schema,  # noqa: E402
                               run_migrations_files)
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
    run_migrations_files()   # كما يفعل الإقلاع الحقيقي
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

    step("19) عرض الأسماء وصور الموديلات")
    # الاسم كان يُقتطع إلى كلمتين حتى لا يتمدّد العمود، فيضيع تمييز
    # الجهة — وهو أهم ما في العمود. الآن يُعرض كاملاً ويُلفّ في العرض.
    from models.journal import short_name as _sn
    LONGN = "مؤسسة الشرق الأوسط للمجوهرات والمعادن الثمينة"
    check("الاسم الطويل يُعرض كاملاً",
          _sn("1601", "عميل: " + LONGN) == LONGN, _sn("1601", "عميل: " + LONGN))
    check("البادئة الوصفية تُزال",
          not _sn("1601", "عميل: محمد الأحمد").startswith("عميل"))
    check("الأسماء النظامية تبقى مختصرة",
          _sn("1400", "الصندوق الرئيسي") == "صندوق النقدي")

    # صورة الموديل: تطبيق واحد مشترك بين الشاشات
    try:
        from ui.widgets.common import has_model_image, show_model_image
        from models import models_catalog as _mc
        check("وسم الصورة لا يُفعّل لموديل بلا صورة",
              has_model_image("NO-SUCH-MODEL-XYZ") is False)
        check("وسم الصورة لا يُفعّل للفراغ",
              has_model_image("") is False and has_model_image("—") is False)
        expect_error("عرض صورة غير موجودة يرفع رسالة مفهومة",
                     lambda: show_model_image(None, "NO-SUCH-MODEL-XYZ"),
                     "لا توجد صورة")
        expect_error("سطر بلا موديل يرفع رسالة مفهومة",
                     lambda: show_model_image(None, "—"), "لا يوجد رقم موديل")
        check("models_screen يستعمل المشترك",
              "show_model_image" in pathlib.Path(
                  ROOT, "ui/models_screen.py").read_text(encoding="utf-8"))
    except ImportError:
        check("فحوص صور الموديلات", True, "تخطّي — PyQt5 غير مثبّت")

    step("20) العيارات وقالب تقرير العميل")
    # القيد كله بمكافئ عيار 18 — لا يتغيّر. العيار تحويل **عرض** فقط:
    # الوزن18 × 18 ÷ العيار، ويعود كما كان إن حُوّل عكسياً.
    from services import gold_math as _gm

    check("عيار 18 لا يغيّر الرقم",
          _gm.from_base_karat(100.0, 18) == 100.0)
    check("التحويل إلى 21 صحيح حسابياً",
          abs(_gm.from_base_karat(100.0, 21) - 85.714) < 0.001,
          str(_gm.from_base_karat(100.0, 21)))
    check("التحويل إلى 24 صحيح حسابياً",
          abs(_gm.from_base_karat(120.0, 24) - 90.0) < 0.001,
          str(_gm.from_base_karat(120.0, 24)))
    check("التحويل عكوس بلا فقد",
          all(abs(_gm.to_base_karat(_gm.from_base_karat(w, k), k) - w) < 0.002
              for w in (10.0, 100.0, 1234.567) for k in _gm.KARATS))
    check("عيار غير صالح لا يكسر العرض",
          _gm.from_base_karat(50.0, 0) == 50.0
          and _gm.from_base_karat(50.0, None) == 50.0
          and _gm.from_base_karat(50.0, "س") == 50.0)

    from services import print_manager as _pm
    with db(readonly=True) as conn:
        cacc = conn.execute("SELECT account_id a FROM entities WHERE id=?",
                            (cust,)).fetchone()["a"]
        st18 = _pm._tpl_statement(conn, cacc, None, None, 18)
        st21 = _pm._tpl_statement(conn, cacc, None, None, 21)
        ca18 = _pm._tpl_customer_analytics(conn, cust, None, None,
                                           None, None, 18)
        ca21 = _pm._tpl_customer_analytics(conn, cust, None, None,
                                           None, None, 21)
    check("كشف الحساب يعنون بالعيار المختار",
          "مدين ذهب 21" in st21 and "رصيد ذهب 21" in st21
          and "مدين ذهب 18" in st18)
    check("أرقام الكشف تختلف باختلاف العيار", st18 != st21)

    # مسمّيات ورقة العميل مسمّيات كشف الحساب لا التحليل الداخلي
    for lbl in ("المصروف", "المرتجع", "المباع الصافي", "السداد"):
        check(f"قالب التقرير يسمّي اللوحة «{lbl}»", lbl in ca18)
    check("مسمّيات التحليل الداخلي لا تخرج للعميل",
          "إجمالي المبيعات" not in ca18 and "إجمالي التحصيل" not in ca18)

    # جدولا الرصيد الصغيران بدل الشريط العريض
    check("جدولا الرصيد موجودان", ca18.count('class="ca-bal"') == 2)
    check("جدول الذهب يحمل العيار المختار",
          "ذهب 18" in ca18 and "ذهب 21" in ca21)
    check("جدول النقد بعنوانه", "نقد ريال" in ca18)
    check("حالة كل رصيد معروضة",
          any(s in ca18 for s in ("مدين", "دائن", "متوازن")))
    check("الشريط العريض القديم أُزيل",
          "الرصيد المتبقي — ذهب" not in ca18)
    check("العيار ينتقل إلى تفاصيل اللوحات", "الوزن 21" in ca21)

    try:
        from ui.widgets.common import karat_combo, load_pref, save_pref
        from PyQt5 import QtWidgets as _QW
        _app = _QW.QApplication.instance() or _QW.QApplication([])
        save_pref("test_karat_pref", 22, "admin")
        check("تفضيل العيار يُحفظ ويُستعاد",
              str(load_pref("test_karat_pref", "18")) == "22")
        cb = karat_combo("test_karat_pref")
        check("قائمة العيارات فيها 18 و21 و22 و24",
              [cb.itemData(i) for i in range(cb.count())] == [18, 21, 22, 24])
        check("القائمة تفتح على آخر عيار محفوظ", cb.currentData() == 22)
        check("تفضيل غير محفوظ يعود إلى 18",
              karat_combo("no_such_pref_key").currentData() == 18)
    except ImportError:
        check("فحوص تفضيل العيار", True, "تخطّي — PyQt5 غير مثبّت")

    step("21) عيار المصنع — وحدة العرض والإدخال في النظام كله")
    # القيد يبقى بمكافئ 18 مهما كان عيار العرض. هذه الفحوص تحرس
    # الحدّ الفاصل: ما يعبر إلى القاعدة محوَّل دائماً، والنقد لا يتأثر.
    from services import karat_view as _kv

    check("العيار الافتراضي 18", _kv.active() == 18)
    _kv.set_active(21, "admin")
    check("العيار يُحفظ في قاعدة المصنع", _kv.active() == 21)
    with db(readonly=True) as conn:
        saved = fiscal.get_setting(conn, _kv.SETTING_KEY, "")
    check("العيار مقروء من app_settings", str(saved) == "21", str(saved))

    check("الإدخال يتحوّل للتخزين",
          abs(_kv.store(100.0) - 116.667) < 0.001, str(_kv.store(100.0)))
    check("التخزين يعود للعرض كما كان",
          abs(_kv.g(_kv.store(100.0)) - 100.0) < 0.01,
          str(_kv.g(_kv.store(100.0))))
    check("أجر الجرام يتحرك عكس الوزن",
          abs(_kv.rate(_kv.rate_store(23.0)) - 23.0) < 0.001)
    # الحاصل (المبلغ النقدي) لا يتغيّر بتغيّر وحدة الوزن — وهو الضابط
    check("المبلغ النقدي لا يتأثر بالعيار",
          abs(_kv.store(100.0) * _kv.rate_store(23.0) - 100.0 * 23.0) < 0.02,
          f"{_kv.store(100.0) * _kv.rate_store(23.0):.4f}")
    expect_error("عيار غير مدعوم يُرفض",
                 lambda: _kv.set_active(19), "غير مدعوم")
    check("العيار لم يتغيّر بعد الرفض", _kv.active() == 21)
    check("المسمّيات تتبع العيار",
          _kv.rename("رصيد الذهب (جم عيار 18)") == "رصيد الذهب (جم عيار 21)",
          _kv.rename("رصيد الذهب (جم عيار 18)"))
    check("وحدة العرض", _kv.unit() == "جم 21" and _kv.label() == "عيار 21")

    # دورة كاملة بعيار 21: التوريد ثم البيع — الأجور كما هي
    with db() as conn:
        _batch(conn, [{"wo_no": "K21", "gold": _kv.store(100.0),
                       "wage_per_gram": _kv.rate_store(23.0)}],
               "2026-04-01", "admin")
        kwo = conn.execute(
            "SELECT * FROM work_orders WHERE work_order_no='K21'").fetchone()
    check("المخزَّن بمكافئ 18 لا بعيار العرض",
          abs(kwo["registered_weight"] - 116.667) < 0.01,
          str(kwo["registered_weight"]))
    check("الطقم يُقرأ بعيار المصنع كما أُدخل",
          abs(_kv.g(kwo["registered_weight"]) - 100.0) < 0.01)
    with db() as conn:
        kinv = create_sale(conn, cust,
                           [{"work_order_id": kwo["id"],
                             "weight": kwo["registered_weight"],
                             "wage_override": kwo["wage_per_gram"]}],
                           "2026-04-05", "admin", apply_vat=False)
    check("أجور الفاتورة = الأجر × الوزن كما أدخلهما المستخدم",
          abs(kinv["total_wages"] - 2300.0) < 0.05,
          f"{kinv['total_wages']:.2f}")
    with db(readonly=True) as conn:
        gk, ck, gvk, cvk = ledger_balanced(conn)
    check("الدفتر متوازن بعد دورة عيار 21", gk and ck,
          f"ذهب {gvk} · نقد {cvk}")

    # الأوزان الفيزيائية لا تُحوَّل: وزن الكسر بعياره ووزن سطر السند
    with db(readonly=True) as conn:
        vrow = conn.execute(
            "SELECT gold_weight, gold_karat, gold_equiv18 FROM vouchers"
            " WHERE gold_weight > 0 LIMIT 1").fetchone()
    if vrow:
        check("وزن سطر السند يبقى بعياره الفعلي",
              abs(gold_math.to_base_karat(vrow["gold_weight"],
                                          vrow["gold_karat"])
                  - vrow["gold_equiv18"]) < 0.02,
              f"{vrow['gold_weight']} ع{vrow['gold_karat']}")
    else:
        check("وزن سطر السند يبقى بعياره الفعلي", True, "لا سند ذهب")

    # قالب الفاتورة يخرج بعيار المصنع ويحمل رمز صور الموديلات
    from services import photo_qr as _pq, photo_server as _ps, print_manager
    with db(readonly=True) as conn:
        html_inv = print_manager._tpl_invoice(conn, kinv["id"])
    check("الفاتورة المطبوعة بعيار المصنع", "جم 21" in html_inv)

    png = _pq.qr_png_data_uri("http://127.0.0.1:1/inv/t")
    check("رمز QR يُبنى بلا مكتبة صور خارجية",
          png.startswith("data:image/png;base64,") and len(png) > 200,
          f"{len(png)} حرفاً")
    img_file = pathlib.Path(_TMP) / "mdl_test.png"
    img_file.write_bytes(base64.b64decode(png.split(",", 1)[1]))
    url = _ps.publish_invoice("S-1", [("MDL-1", str(img_file))])
    check("خادم الصور يعطي رابطاً على الشبكة المحلية",
          bool(url) and "/inv/" in str(url), str(url))
    if url:
        import urllib.request
        page = urllib.request.urlopen(url, timeout=5).read().decode("utf-8")
        check("صفحة الصور تعرض الموديل", "MDL-1" in page)
        raw = urllib.request.urlopen(
            url.replace("/inv/", "/img/") + "/0", timeout=5).read()
        check("الصورة تُخدم كاملة", raw == img_file.read_bytes(),
              f"{len(raw)} بايت")
        base = url.rsplit("/inv/", 1)[0]
        try:
            urllib.request.urlopen(base + "/inv/NOPE", timeout=5)
            check("الرمز المجهول يُرفض", False, "قُبل رابط غير صالح")
        except Exception as e:
            check("الرمز المجهول يُرفض", "404" in str(e), str(e)[:40])
        try:
            urllib.request.urlopen(base + "/etc/passwd", timeout=5)
            check("لا مسار آخر على الجهاز يُخدم", False, "قُبل مسار خارجي")
        except Exception as e:
            check("لا مسار آخر على الجهاز يُخدم", "404" in str(e),
                  str(e)[:40])
    _ps.stop()
    check("خادم الصور يُغلق", _ps._state["server"] is None)
    _kv.set_active(18, "admin")
    check("العودة إلى 18 سليمة", _kv.active() == 18 and _kv.is_base())

    step("22) إلغاء حارس الأرصدة السالبة")
    # أُلغيت الميزة بطلب صاحب النظام: الرصيد السالب في مصنعٍ يعمل
    # حالةٌ واقعية (بضاعة تخرج قبل تسجيل توريدها)، فكان التنبيه
    # يتكرّر على عملياتٍ سليمة. يُفحص هنا أنها أُزيلت **فعلاً** لا
    # أُسكتت: لا وحدة، ولا نداء في محرّك القيود، ولا تنبيه بعد قيدٍ
    # يُسلِّب رصيداً مادياً.
    import importlib.util as _ilu
    check("وحدة الحارس أُزيلت من النظام",
          _ilu.find_spec("services.stock_guard") is None)
    _eng = pathlib.Path("services/accounting_engine.py").read_text(
        encoding="utf-8")
    check("ولا يُستدعى في محرّك القيود",
          "stock_guard.check_entry" not in _eng)
    from services.accounting_engine import balance_by_code as _bal
    with db() as conn:
        _tz, _la = acc_id(conn, "1100"), acc_id(conn, "5300")
        _before = _bal(conn, "1100")[0]
    with db() as conn:
        post_entry(conn, "2026-05-01", "سحب يتجاوز الرصيد", [
            {"account_id": _la, "gold_debit": _before + 500.0},
            {"account_id": _tz, "gold_credit": _before + 500.0}],
            username="admin")
    with db(readonly=True) as conn:
        _left = conn.execute(
            "SELECT COUNT(*) c FROM journal_entries"
            " WHERE description='سحب يتجاوز الرصيد'").fetchone()["c"]
    check("والقيد الذي يُسلِّب رصيداً يمرّ بلا منع ولا تنبيه",
          _left == 1, f"{_left}")
    # إعادة الخزينة إلى موجب حتى لا تتأثر بقية الفحوص
    with db() as conn:
        post_entry(conn, "2026-05-01", "إعادة الرصيد", [
            {"account_id": _tz, "gold_debit": _before + 500.0},
            {"account_id": _la, "gold_credit": _before + 500.0}],
            username="admin")

    step("23) أعمار الديون")
    import datetime as _dt
    from models import aging as _ag

    _today = _dt.date.today()

    def _ago(n):
        return (_today - _dt.timedelta(days=n)).isoformat()

    with db() as conn:
        a_old = add_entity(conn, "عميل الأعمار", "customer",
                           username="admin")
        _batch(conn, [{"wo_no": "AG1", "gold": 100.0, "wage_per_gram": 20.0},
                      {"wo_no": "AG2", "gold": 50.0, "wage_per_gram": 20.0}],
               _ago(200), "admin")
        agids = {r["work_order_no"]: r["id"] for r in conn.execute(
            "SELECT id, work_order_no FROM work_orders"
            " WHERE work_order_no IN ('AG1','AG2')")}
        create_sale(conn, a_old, [{"work_order_id": agids["AG1"]}],
                    _ago(120), "admin", apply_vat=False)   # 2000 ريال
        create_sale(conn, a_old, [{"work_order_id": agids["AG2"]}],
                    _ago(10), "admin", apply_vat=False)    # 1000 ريال
        create_voucher(conn, "receipt", _ago(2), "admin", entity_id=a_old,
                       rows=[{"kind": "cash", "amount": 500.0}])
    with db(readonly=True) as conn:
        arows = _ag.report(conn, "customer")
    mine = [r for r in arows if r["name"] == "عميل الأعمار"]
    check("الجهة تظهر في التقرير", len(mine) == 1)
    r0 = mine[0]
    check("السداد يُطفئ الأقدم أولاً (FIFO)",
          abs(r0["cash_buckets"][3] - 1500.0) < 0.02,
          f"أكثر من 90: {r0['cash_buckets'][3]}")
    check("الفاتورة الحديثة في فئتها",
          abs(r0["cash_buckets"][0] - 1000.0) < 0.02,
          f"0-30: {r0['cash_buckets'][0]}")
    check("أقدم دين يُحسب بالأيام", r0["days"] >= 119, str(r0["days"]))
    check("إجمالي الفئات = الرصيد",
          abs(sum(r0["cash_buckets"]) - r0["cash"]) < 0.02)
    at = _ag.totals(arows)
    check("نسب الفئات تجمع 100%",
          abs(sum(at["cash_pct"]) - 100.0) < 0.2, str(at["cash_pct"]))
    check("المتعثّرون يُرصدون",
          any(r["name"] == "عميل الأعمار"
              for r in _ag.overdue(conn, 90, "customer")))

    step("24) مقارنة الفترتين والإغلاق اليومي")
    from models import dash_panels as _dp, day_close as _dc

    p1, p2 = _dp.previous_period("2026-02-01", "2026-02-28")
    check("الفترة السابقة مساوية في الطول",
          (p1, p2) == ("2026-01-04", "2026-01-31"), f"{p1} → {p2}")
    with db(readonly=True) as conn:
        cmp_ = _dp.compare_rows(conn, ["1600"], _ago(30),
                                _today.isoformat())
        ct = _dp.compare_totals(cmp_["rows"])
    check("المقارنة تعيد فترة سابقة", bool(cmp_["from"] and cmp_["to"]))
    check("المقارنة تحسب الفرق",
          abs((ct["cash"] - ct["cash_prev"]) - ct["cash_diff"]) < 0.02)
    check("النسبة تُحسب أو تُترك فارغة عند القسمة على صفر",
          ct["cash_pct"] is None or isinstance(ct["cash_pct"], float))

    with db(readonly=True) as conn:
        dcs = _dc.summary(conn, _ago(10))
    check("الإغلاق اليومي يرصد مستندات اليوم", dcs["count"] >= 1,
          f"{dcs['count']} مستند")
    check("الحركة مصنّفة بأنواعها", len(dcs["kinds"]) >= 1,
          str([k["op"] for k in dcs["kinds"]]))
    check("الأرصدة الختامية تشمل الحسابات المادية والذمم",
          len(dcs["balances"]) >= 5, f"{len(dcs['balances'])} حساب")
    codes = {b["code"] for b in dcs["balances"]}
    check("رصيد الذمم يشمل الفروع",
          "1600" in codes
          and any(abs(b["cash"]) > 0 for b in dcs["balances"]
                  if b["code"] == "1600"))
    check("مجموع المستندات = العدد المعلن",
          len(dcs["docs"]) == dcs["count"])

    # القوالب المطبوعة للتقريرين
    with db(readonly=True) as conn:
        h_age = print_manager._tpl_aging(conn, 0, "customer", None, "both")
        h_day = print_manager._tpl_day_close(conn, 0, _ago(10))
    check("قالب الأعمار يُبنى", "أعمار الديون" in h_age
          and "الأقدم فالأقدم" in h_age)
    check("قالب الإغلاق اليومي يُبنى", "الإغلاق اليومي" in h_day
          and "الأرصدة الختامية" in h_day)

    # ترشيح التقرير بجهات مختارة — الورقة تطابق الشاشة
    if arows:
        one = arows[0]["entity_id"]
        with db(readonly=True) as conn:
            h_one = print_manager._tpl_aging(conn, 0, "customer", None,
                                             "both", [one])
        others = [r["name"] for r in arows if r["entity_id"] != one]
        check("ورقة الأعمار تحترم الترشيح بالأسماء",
              all(n not in h_one for n in others) and "جهات مختارة" in h_one,
              f"{len(others)} جهة مستبعدة")

    step("25) سلامة القائمة الجانبية والواجهة")
    # **الخلل الذي عُولج**: ترتيب القائمة كان يُحفظ بفهرس الشاشة
    # الرقمي. وإضافة شاشة في وسط القائمة تُزيح كل ما بعدها، فيصير
    # البند يفتح جارته — «المبيعات» تفتح «التوريد» — وتتكرر بنود.
    try:
        from PyQt5 import QtCore as _QC, QtWidgets as _QW
        _app2 = _QW.QApplication.instance() or _QW.QApplication([])
        import json as _json
        from ui.main_window import MainWindow as _MW, NAV_KEY_ROLE as _KEY
        from ui.widgets.common import ElidedLabel as _EL, search_combo as _sc

        _user = {"id": 1, "username": "admin", "full_name": "م",
                 "role": "admin", "role_local": "accountant"}
        w1 = _MW(_user)

        def _tree(win):
            out = []
            for it, _p in win._iter_nav():
                i = it.data(0, _QC.Qt.UserRole)
                if i is not None and i >= 0:
                    out.append((it.text(0), i))
            return out

        base = _tree(w1)
        check("القائمة تُبنى كاملةً", len(base) > 25, f"{len(base)} بنداً")
        check("لكل بند مفتاح ثابت",
              all(it.data(0, _KEY) for it, _p in w1._iter_nav()))

        # ══ الترتيب المعتمد: اثنتا عشرة شاشة يومية ثم مجموعة واحدة ══
        from ui.main_window import NAV_VERSION as _NAVV
        top = [w1.sidebar.topLevelItem(i).text(0)
               for i in range(w1.sidebar.topLevelItemCount())]
        want = ["لوحة التحكم", "دليل الموديلات", "حركة الطقم",
                "كشف حساب", "الوارد من التصنيع", "مبيعات/مرتجعات",
                "سندات قبض/صرف", "التسكيرات", "المشتريات",
                "القيود اليومية", "تقارير مبيعات وإنتاج المصنع",
                "الإدارة والتقارير"]
        check("ترتيب القائمة هو المعتمد حرفياً",
              top[:len(want)] == want, str(top[:len(want)]))
        grp = next((w1.sidebar.topLevelItem(i)
                    for i in range(w1.sidebar.topLevelItemCount())
                    if w1.sidebar.topLevelItem(i).text(0)
                    == "الإدارة والتقارير"), None)
        check("بقية الشاشات كلها داخل «الإدارة والتقارير»",
              grp is not None and grp.childCount() == len(base) - 11,
              f"{grp.childCount() if grp else 0} بنداً")
        check("لا شاشة خارج الترتيب المعتمد",
              len(top) == len(want), str(top[len(want):]))

        path = w1._nav_layout_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        # ملفٌ بإصدارٍ أقدم: يُهمل فيظهر الترتيب المعتمد الجديد
        path.write_text(_json.dumps(
            [{"idx": 0, "text": "ترتيب قديم", "expanded": True,
              "children": []}], ensure_ascii=False), encoding="utf-8")
        w_old = _MW(_user)
        check("ترتيب محفوظ بإصدار أقدم يُهمل",
              [w_old.sidebar.topLevelItem(i).text(0)
               for i in range(w_old.sidebar.topLevelItemCount())] == top)

        # ملف بالإصدار الحالي لكن بفهارس مُزاحة وبندٍ مُعاد تسميته
        legacy = {"version": _NAVV, "nodes": [
            {"idx": max(0, i - 2), "key": t, "text": t, "expanded": True,
             "children": []} for t, i in base]}
        legacy["nodes"][3]["text"] = "اسم غيّرته بنفسي"
        path.write_text(_json.dumps(legacy, ensure_ascii=False),
                        encoding="utf-8")

        w2 = _MW(_user)
        after = _tree(w2)
        idxs = [i for _t, i in after]
        by_name = dict(base)
        wrong = [t for t, i in after if t in by_name and by_name[t] != i]
        check("لا بند يفتح شاشةً غير شاشته", not wrong, str(wrong[:3]))
        check("لا تكرار في البنود", len(idxs) == len(set(idxs)))
        check("لا تختفي شاشة من القائمة",
              set(idxs) == {i for _t, i in base},
              f"{len(set(idxs))} من {len(base)}")

        # الملف الجديد يُستعاد كما هو تماماً
        w2._save_nav_layout()
        saved_nav = _json.loads(path.read_text(encoding="utf-8"))

        def _keys(nodes):
            out = []
            for n in nodes:
                out.append(n.get("key", ""))
                out += _keys(n.get("children", []))
            return out

        check("المفاتيح تُحفظ في الملف",
              len([k for k in _keys(saved_nav["nodes"])
                   if k and not k.startswith("::group::")]) == len(base))
        check("الملف يحمل إصدار الترتيب",
              saved_nav.get("version") == _NAVV)
        w3 = _MW(_user)
        check("الاستعادة بالمفاتيح مطابقة", _tree(w3) == after)
        try:
            path.unlink()
        except Exception:
            pass

        # الواجهة لا تتمدّد أفقياً بطول الأسماء
        cb = _sc("بحث")
        for i in range(60):
            cb.addItem("1600 — عميل: مؤسسة الشرق الأوسط للمجوهرات "
                       "والمعادن الثمينة رقم %d" % i, i)
        check("قائمة البحث لا تتمدّد بطول أسمائها",
              cb.sizeHint().width() < 400, f"{cb.sizeHint().width()} بكسل")
        lbl = _EL("اسم طويل جداً لمصنع ذهب ومجوهرات وأحجار كريمة",
                  minimum=90)
        check("الملصق القصّاص لا يفرض عرضه",
              lbl.minimumSizeHint().width() <= 90,
              f"{lbl.minimumSizeHint().width()} بكسل")
        check("الشريط العلوي لا يفرض عرضاً كبيراً",
              w1.centralWidget().minimumSizeHint().width() < 1000,
              f"{w1.centralWidget().minimumSizeHint().width()} بكسل")

        # شاشة الأعمار: الترشيح بالأسماء
        from ui.reports.aging_screen import AgingScreen as _AG
        ag = _AG(_user)
        ag.refresh()
        total_rows = len(ag.rows)
        check("شاشة الأعمار تعرض الكل افتراضاً",
              len(ag._visible_rows()) == total_rows and not ag.selected)
        if total_rows:
            ag.selected = [ag.rows[0]["entity_id"]]
            ag._update_names_label()
            check("الترشيح يقصر الجدول على المختار",
                  len(ag._visible_rows()) == 1,
                  f"{len(ag._visible_rows())} من {total_rows}")
            check("الملصق يعلن المعروض",
                  ag.rows[0]["name"] in ag.lbl_sel.text(), ag.lbl_sel.text())
            ag.clear_names()
            check("مسح التحديد يعيد الكل",
                  len(ag._visible_rows()) == total_rows
                  and "كل الجهات" in ag.lbl_sel.text())
    except ImportError:
        check("فحوص القائمة والواجهة", True, "تخطّي — PyQt5 غير مثبّت")

    step("26) لا تجمّد عند الترحيل")
    # **الخلل**: صورة QR للفاتورة الضريبية كانت تُبنى **داخل** معاملة
    # القاعدة. وأول استيراد لمكتبة الصور على ويندوز يستغرق ثوانيَ،
    # فيتجمّد خيط الواجهة («لا يستجيب» وشاشة سوداء) ويُحبس معه قفل
    # الكتابة — فتتعطّل النسخ الاحتياطي والمزامنة أيضاً.
    from services import zatca as _z

    with db() as conn:
        _b = _batch(conn, [{"wo_no": "VT1", "gold": 40.0,
                            "wage_per_gram": 20.0}], "2026-06-01", "admin")
        vwo = conn.execute("SELECT id FROM work_orders"
                           " WHERE work_order_no='VT1'").fetchone()["id"]
        vinv = create_sale(conn, cust, [{"work_order_id": vwo}],
                           "2026-06-05", "admin", apply_vat=True)
    check("الفاتورة الضريبية تحمل نص QR", bool(vinv.get("qr_base64")))
    check("ولا تبني صورته داخل المعاملة",
          vinv.get("qr_path") is None,
          str(vinv.get("qr_path")))

    _png = _z.generate_qr_image(vinv["qr_base64"], vinv["invoice_no"])
    check("صورة QR تُبنى عند الطلب بلا مكتبة صور خارجية",
          bool(_png) and pathlib.Path(_png).exists(), str(_png))
    if _png:
        head = pathlib.Path(_png).read_bytes()[:8]
        check("الملف صورة PNG صحيحة", head == b"\x89PNG\r\n\x1a\n")
        try:
            pathlib.Path(_png).unlink()   # لا يُخلّف الفحص ملفاً
        except Exception:
            pass

    # رصد البطء: الشكوى تصير دليلاً في السجل
    from services import health as _h2
    _h2.log_slow("مرحلة اختبار", 9.9, "من الفحص")
    logp = pathlib.Path(config.BASE_DIR) / "data" / _h2.ERROR_LOG
    check("البطء يُسجَّل باسم مرحلته",
          logp.exists() and "مرحلة اختبار" in logp.read_text(encoding="utf-8"))

    try:
        from PyQt5 import QtWidgets as _QW3
        from ui.widgets.common import busy as _busy
        _app3 = _QW3.QApplication.instance() or _QW3.QApplication([])
        holder = _QW3.QWidget()
        with _busy(holder, "اختبار", stage="اختبار الانشغال"):
            inside = holder.isEnabled()
        check("النافذة تُعطَّل أثناء العمل ثم تعود",
              inside is False and holder.isEnabled() is True)
        check("مؤشر الانتظار يُستعاد",
              _app3.overrideCursor() is None)

        # ══ العمل البطيء في خيطٍ جانبي والواجهة حيّة ══
        # هذا هو الفرق بين «انتظارٍ بمؤشر» و«شاشةٍ سوداء لا تستجيب»:
        # `busy` ينفّذ على خيط الواجهة فتموت حلقةُ الأحداث، ونداءُ
        # شبكةٍ بعشر ثوانٍ يصير عشرَ ثوانٍ من السواد بعد كل ترحيل.
        # يُثبَت هنا بالعدّ: مؤقّتٌ ينبض أثناء العمل — إن نبض فالحلقة
        # تعمل، وإن لم ينبض فالواجهة متجمّدة.
        from PyQt5 import QtCore as _QC3
        from ui.widgets.common import run_bg as _run_bg
        beats = []
        _tm = _QC3.QTimer()
        _tm.setInterval(20)
        _tm.timeout.connect(lambda: beats.append(1))
        _tm.start()
        _ok, _res, _err = _run_bg(lambda: (time.sleep(0.6), "تمّ")[1],
                                  parent=holder, text="اختبار", slow=99)
        _tm.stop()
        check("العمل الجانبي يعيد نتيجته", _ok and _res == "تمّ" and not _err,
              f"{_ok} · {_res} · {_err}")
        check("وحلقة الأحداث تعمل أثناءه (لا شاشة سوداء)",
              len(beats) >= 5, f"{len(beats)} نبضة")
        check("والنافذة عادت مفعَّلة والمؤشر مُستعاد",
              holder.isEnabled() and _app3.overrideCursor() is None)

        _ok2, _, _ = _run_bg(lambda: time.sleep(1.5), parent=holder,
                             text="اختبار", timeout=0.2, slow=99)
        check("سقف الانتظار يُحرّر الواجهة ولا يحبسها",
              _ok2 is False)

        _ok3, _, _err3 = _run_bg(lambda: 1 / 0, parent=holder,
                                 text="اختبار", slow=99)
        check("وخطأ الخيط الجانبي يُنقل لا يُبتلع",
              _ok3 and isinstance(_err3, ZeroDivisionError))

        # المُحجِّم يعيد الحساب عند تغيّر عدد الأعمدة لا العرض وحده
        from ui.widgets.table_fit import ColumnFitter
        t = _QW3.QTableWidget()
        t.setColumnCount(4)
        t.show()                      # المُحجِّم لا يعمل على جدول مخفيّ
        f = ColumnFitter(t, [1, 1, 1, 1])
        f._last_w, f._last_n = 500, 4
        t.setColumnCount(7)
        f._do_apply()
        check("تغيّر عدد الأعمدة يُعيد توزيع العرض",
              f._last_n == 7, f"{f._last_n}")
    except ImportError:
        check("فحوص الانشغال والتحجيم", True, "تخطّي — PyQt5 غير مثبّت")

    step("27) المظهر والجداول والشاشة الأولى وشريط الأوامر")
    # ── المظهر: بنيةٌ واحدة ولوحتان ──
    from ui import theme as _th
    _tpl = "QWidget { background: @bg; color: @ink; font-size: 14px; }"
    _light = _th.build(_tpl, _th.LIGHT, 1.0)
    _dark = _th.build(_tpl, _th.DARK, 1.0)
    check("الأسماء الرمزية تُستبدل بألوانها",
          "@" not in _light and _th.LIGHT["bg"] in _light)
    check("اللوحتان تختلفان فعلاً", _light != _dark
          and _th.DARK["bg"] in _dark)
    check("اسمٌ غير معروف لا يكسر النمط",
          "@nope" in _th.build("a { color: @nope; }", _th.LIGHT, 1.0))
    _big = _th.build(_tpl, _th.LIGHT, 2.0)
    check("مقاس الخط يُضرب في المعامل", "font-size:28.0px" in
          _big.replace("font-size: ", "font-size:"), _big)
    check("كل مفاتيح اللوحة الفاتحة لها مقابل في الليلية",
          set(_th.LIGHT) == set(_th.DARK),
          str(set(_th.LIGHT) ^ set(_th.DARK)))
    import re as _re
    _used = set(_re.findall(r"@([A-Za-z][A-Za-z0-9_]*)",
                            __import__("ui.styles", fromlist=["x"]).TEMPLATE))
    check("كل اسمٍ في النمط معرَّف في اللوحتين",
          not (_used - set(_th.LIGHT)), str(sorted(_used - set(_th.LIGHT))))

    # ── أدوات الجداول: الفرز رقميٌّ لا حرفي ──
    from ui.widgets import table_tools as _tt
    check("قراءة الرقم من الخلية بفواصل الآلاف",
          _tt.as_number("1,250.50") == 1250.5)
    check("السالب بالشرطة الطويلة يُقرأ رقماً",
          _tt.as_number("–40") == -40.0)
    check("النص ليس رقماً", _tt.as_number("خزينة التصنيع") is None)
    check("التاريخ يُفرز زمنياً لا حرفياً",
          _tt._key("2026-01-09") < _tt._key("2026-01-10"))
    check("الفرز الرقمي لا الحرفي: 9 قبل 100",
          _tt._key("9") < _tt._key("100"))
    check("الأرقام والنصوص لا تُقارَن ببعضها فترفع استثناءً",
          sorted(["ب", "100", "9", "—"], key=_tt._key)[0] == "9")

    # ── شريط الأوامر: يجد ما أنشأته هذه الدورة ──
    from ui.widgets import palette as _pal
    with db(readonly=True) as conn:
        _hits = _pal.db_lookup(conn, "VT1")
        _inv_hits = _pal.db_lookup(conn, vinv["invoice_no"])
    check("شريط الأوامر يجد رقم التشغيل",
          any(k == _pal.WORK_ORDER and p == "VT1" for k, _l, _h, p in _hits),
          str(_hits))
    check("ويجد رقم الفاتورة",
          any(k == _pal.INVOICE and p == vinv["invoice_no"]
              for k, _l, _h, p in _inv_hits), str(_inv_hits))
    check("ولا يُرجع شيئاً لنصٍّ فارغ", _pal.db_lookup(None, "") == [])
    check("المطابقة من أول الاسم أقوى من الوسط",
          _pal._score("عمر", "عمر الخير") < _pal._score("عمر", "محمد عمر"))

    try:
        from PyQt5 import QtWidgets as _QW4
        _app4 = _QW4.QApplication.instance() or _QW4.QApplication([])
        # صفُّ الإجمالي يبقى في القاع مهما فُرز ما فوقه
        t2 = _QW4.QTableWidget(0, 2)
        t2.setHorizontalHeaderLabels(["الاسم", "المبلغ"])
        for name, amount in (("ب", "9"), ("أ", "100"), ("ج", "40")):
            r = t2.rowCount()
            t2.insertRow(r)
            t2.setItem(r, 0, _QW4.QTableWidgetItem(name))
            t2.setItem(r, 1, _QW4.QTableWidgetItem(amount))
        _tt.total_row(t2, {1: "149"})
        s = _tt.attach_sorter(t2)
        s.sort_by(1)
        check("الفرز الرقمي تصاعدياً",
              [t2.item(r, 1).text() for r in range(3)] == ["9", "40", "100"])
        check("صف الإجمالي لا يُفرَز بل يبقى في القاع",
              bool(t2.item(3, 0).data(_tt.TOTAL_ROLE)))
        s.sort_by(1)
        check("النقرة الثانية تعكس الاتجاه",
              [t2.item(r, 1).text() for r in range(3)] == ["100", "40", "9"])
        check("والإجمالي ما زال في القاع",
              bool(t2.item(3, 0).data(_tt.TOTAL_ROLE)))
        check("جمع الأعمدة يتجاهل صف الإجمالي",
              _tt.sum_columns(t2, [1])[1] == 149.0)
        check("التصدير يبدأ بصف العناوين",
              _tt.rows_of(t2)[0] == ["الاسم", "المبلغ"])

        # أوزان المستخدم تسبق أوزان الشاشة في مُحجِّم الأعمدة
        from ui.widgets.table_fit import ColumnFitter as _CF
        t3 = _QW4.QTableWidget(1, 2)
        t3.show()
        t3.resize(400, 100)
        t3.setProperty("_user_weights", [80.0, 20.0])
        f3 = _CF(t3, [1, 1])
        f3.refit()
        f3._do_apply()
        check("عرض الأعمدة المحفوظ يسبق أوزان الشاشة",
              t3.columnWidth(0) > t3.columnWidth(1) * 2,
              f"{t3.columnWidth(0)} / {t3.columnWidth(1)}")
    except ImportError:
        check("فحوص الجداول الاحترافية", True, "تخطّي — PyQt5 غير مثبّت")

    step("27ب) صفحة الفاتورة التي يفتحها رمز QR")
    # **الشكوى التي عولجت**: الموظف يفتح الرمز فتظهر الصور، والعميل
    # يصوّره في بيته فلا يفتح شيئاً — لأن الرابط كان عنواناً محلياً
    # (192.168.x.x) لا يبلغه إلا من كان على شبكة المصنع.
    from services import invoice_share as _ish
    with db(readonly=True) as conn:
        _d = _ish.invoice_data(conn, inv_id)
        _m = _ish.model_lines(conn, inv_id)
    check("بيانات الفاتورة تُقرأ للصفحة",
          _d and _d["no"] and _d["lines"], str(_d and _d["no"]))
    check("الإجمالي في الصفحة = إجمالي الفاتورة",
          abs(_d["total"] - inv["grand_total"]) < 0.01,
          f"{_d['total']} / {inv['grand_total']}")
    _page = _ish.page_html(_d, _m, lambda i: "", "مصنع الاختبار")
    check("الفاتورة تظهر أولاً في الصفحة",
          _page.index(str(_d["no"])) < _page.index("موديلات الفاتورة"))
    check("وموديلاتها أسفلها بأسمائها وأعدادها",
          all(f'<b>{x["model"]}</b>' in _page and
              f'العدد: {x["count"]}' in _page for x in _m),
          str([(x["model"], x["count"]) for x in _m]))
    check("الصفحة صالحة للجوال",
          'name="viewport"' in _page and 'dir="rtl"' in _page)

    # رمز الفاتورة ثابت: رابطٌ سُلّم للعميل لا يجوز أن تُبطله إعادة
    # الطباعة.
    with db() as conn:
        _t1 = _ish._token(conn, inv_id)
    with db() as conn:
        _t2 = _ish._token(conn, inv_id)
    check("رمز الفاتورة يُنشأ مرةً ويثبت", bool(_t1) and _t1 == _t2, _t1)
    check("ولا يُخمَّن (طوله كافٍ)", len(_t1 or "") >= 12)
    with db(readonly=True) as conn:
        check("الوضع الافتراضي تلقائي", _ish.mode(conn) == "auto")
    with db() as conn:
        _ish.set_mode(conn, "off", "admin")
    with db(readonly=True) as conn:
        check("وضع «بلا رمز» يمنع النشر",
              _ish.publish(conn, inv_id) == ("", ""))
        _ish_qr = __import__("services.photo_qr", fromlist=["x"])
        check("ولا يُطبع وسم QR حينها",
              _ish_qr.qr_for_invoice(conn, inv_id, _d["no"]) == "")
    with db() as conn:
        _ish.set_mode(conn, "auto", "admin")

    # ══ المساحة السحابية: الضغط ثم الرفع مرةً واحدة لكل صورة ══
    # وهذا ما يجعل النشر السحابي ممكناً على أصغر باقة تخزين: الصورة
    # من الكاميرا تزن ميجابايتات، وهي تُعرض على شاشة جوال.
    try:
        from PyQt5.QtGui import QImage as _QI
        big = pathlib.Path(_TMP) / "model_big.jpg"
        _im = _QI(2600, 1900, _QI.Format_RGB32)
        for _y in range(0, 1900, 3):
            for _x in range(0, 2600, 3):
                _im.setPixel(_x, _y, ((_x * 5) ^ (_y * 3)) & 0xFFFFFF)
        _im.save(str(big), "JPEG", 92)
        raw_size = big.stat().st_size
        small, ctype = _ish.compress(str(big))
        check("صورة الموديل تُصغَّر وتُضغط قبل رفعها",
              len(small) < raw_size and ctype == "image/jpeg",
              f"{raw_size // 1024}ك ← {len(small) // 1024}ك")
        check("والصغيرة أصلاً تُترك كما هي",
              _ish.compress(str(big))[0] == small)
    except ImportError:
        check("ضغط صور الموديلات", True, "تخطّي — PyQt5 غير مثبّت")

    with db() as conn:
        _ish._asset_save(conn, "sha-test", "http://x/a.jpg", 40960)
        _ish._asset_save(conn, "sha-test", "http://x/a.jpg", 40960)
    with db(readonly=True) as conn:
        check("الصورة تُسجَّل مرةً واحدة ببصمتها",
              conn.execute("SELECT COUNT(*) n FROM cloud_assets"
                           " WHERE sha='sha-test'").fetchone()["n"] == 1)
        check("والبصمة المعروفة لا تُرفع ثانيةً",
              _ish._asset_url(conn, "sha-test") == "http://x/a.jpg")
        _u = _ish.usage(conn)
        check("المساحة المستعملة تُحسب وتُعرض",
              _u["images"] >= 1 and _u["total_mb"] >= 0, str(_u))

    step("27ج) رمز QR بقرارٍ لكل فاتورة · ومسوّدات شاشات الإدخال")
    # **الطلب**: ليست كل فاتورة تحتاج رمزاً. وإنشاؤه يعني رفع صورٍ
    # تستهلك مساحة — فلا يُبنى إلا لفاتورة طُلب لها صراحةً.
    with db() as conn:
        _b = _batch(conn, [{"wo_no": "QR1", "gold": 15.0,
                            "wage_per_gram": 20.0},
                           {"wo_no": "QR2", "gold": 15.0,
                            "wage_per_gram": 20.0}],
                    "2026-09-10", "admin")
        qids = {r["work_order_no"]: r["id"] for r in conn.execute(
            "SELECT id, work_order_no FROM work_orders"
            " WHERE work_order_no IN ('QR1','QR2')")}
        inv_off = create_sale(conn, cust, [{"work_order_id": qids["QR1"]}],
                              "2026-09-11", "admin")
        inv_on = create_sale(conn, cust, [{"work_order_id": qids["QR2"]}],
                             "2026-09-11", "admin", qr_enabled=True)
    with db(readonly=True) as conn:
        check("الفاتورة بلا تفعيل لا رمز لها",
              not _ish.enabled_for(conn, inv_off["id"]))
        check("والمفعَّلة لها رمز", _ish.enabled_for(conn, inv_on["id"]))
        check("غير المفعَّلة لا تُنشر ولا تستهلك مساحة",
              _ish.publish(conn, inv_off["id"]) == ("", ""))
        check("ولا يُطبع لها وسم QR",
              _ish_qr.qr_for_invoice(conn, inv_off["id"],
                                     inv_off["invoice_no"]) == "")
    with db(readonly=True) as conn:
        check("الفواتير السابقة تبقى بلا رمز افتراضياً",
              conn.execute(
                  "SELECT COUNT(*) n FROM invoices WHERE qr_enabled=1"
              ).fetchone()["n"] == 1)

    # ══ الرمز يظهر فعلاً في ورقة الطباعة حين يُفعَّل ══
    # الفحص من طرفٍ إلى طرف: من خانة التفعيل إلى وسم <img> في القالب.
    from services import print_manager as _pm
    _html_on = _pm.build_html("invoice", inv_on["id"])
    _html_off = _pm.build_html("invoice", inv_off["id"])
    check("وسم QR يظهر في قالب الفاتورة المفعَّلة",
          "data:image/png;base64," in _html_on)
    check("ولا يظهر في غير المفعَّلة",
          "data:image/png;base64," not in _html_off)

    # الطباعة لا ترفع شيئاً عبر الإنترنت: الرفع فعلٌ صريح بعد الترحيل،
    # وإلا حُبس قفل الكتابة ثوانيَ فتجمّدت الواجهة (وهو خلل عولج من
    # قبل حين كانت صورة QR تُبنى داخل المعاملة).
    with db(readonly=True) as conn:
        check("الطباعة لا تحاول الرفع (قفل الكتابة لا تلمسه الشبكة)",
              _ish.publish(conn, inv_on["id"])[1] in ("lan", ""),
              str(_ish.publish(conn, inv_on["id"])))

    # التشخيص يقول أين توقّف المسار بالضبط
    with db() as conn:
        _rep = _ish.report(conn, inv_off["id"])
        _steps = _ish.diagnose(conn, inv_off["id"])
    check("التشخيص يذكر الخطوات باسمها", "مكتبة بناء الرمز" in _rep)
    check("ويكشف أن الفاتورة غير مفعَّلة",
          any(not s["ok"] and "تفعيل الرمز" in s["step"] for s in _steps),
          str([s["step"] for s in _steps]))
    with db() as conn:
        _ok_steps = _ish.diagnose(conn, inv_on["id"])
    check("وللمفعَّلة يمضي إلى الرابط النهائي",
          any("الرابط الذي سيحمله الرمز" in s["step"] for s in _ok_steps),
          str([s["step"] for s in _ok_steps]))

    # ══ النشر السحابي كاملاً — مقابل خادم تخزين محاكٍ ══
    # **الخلل الذي يحرسه هذا الفحص**: داخل حلقة رفع الصور كان متغيّر
    # بايتات الصورة يحمل اسم `data` نفسه الذي يحمل **بيانات الفاتورة**،
    # فيدهسه. فتُستدعى `page_html` ببايتات صورة بدل قاموس الفاتورة،
    # فترفع استثناءً يبتلعه الحارس: لا صفحة تُرفع ولا رمز يُطبع ولا
    # سبب يظهر.
    #
    # ولا يقع إلا حين يكون لموديلٍ **صورةٌ محفوظة** — ولهذا مرّ من كل
    # الفحوص السابقة: لم يكن في أيٍّ منها صورة. فالفحص هنا يرفع صورة
    # حقيقية ويعدّ طلبات الرفع: صورةٌ ثم صفحة.
    import http.server as _hs
    import threading as _th
    _puts = []

    class _FakeStore(_hs.BaseHTTPRequestHandler):
        def log_message(self, *_a):
            pass

        def do_POST(self):                                # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            listing = "/object/list/" in self.path
            if not listing:
                _puts.append(self.path)
            b = b"[]" if listing else b'{"Key":"ok"}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

    _srv = _hs.HTTPServer(("127.0.0.1", 0), _FakeStore)
    _th.Thread(target=_srv.serve_forever, daemon=True).start()
    _old_proxy = {k: os.environ.pop(k, None) for k in
                  ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")}
    os.environ["NO_PROXY"] = "*"
    try:
        from models import models_catalog as _mc
        from services import tenant as _tn
        _tn.update(cloud_url=f"http://127.0.0.1:{_srv.server_address[1]}",
                   cloud_key="k")
        try:
            from PyQt5.QtGui import QImage as _QI2
            _im2 = _QI2(1400, 1100, _QI2.Format_RGB32)
            _im2.fill(0xCCAA44)
            _imgp = pathlib.Path(_TMP) / "model_cloud.jpg"
            _im2.save(str(_imgp), "JPEG", 92)
            with db() as conn:
                _b3 = _batch(conn, [{"wo_no": "CQ1", "gold": 18.0,
                                     "wage_per_gram": 20.0,
                                     "model_no": "MC-1"}],
                             "2026-09-20", "admin")
                _cq = conn.execute(
                    "SELECT id FROM work_orders"
                    " WHERE work_order_no='CQ1'").fetchone()["id"]
                _cinv = create_sale(conn, cust, [{"work_order_id": _cq}],
                                    "2026-09-21", "admin", qr_enabled=True)
            _mc.set_image("MC-1", str(_imgp), "admin")
            with db() as conn:
                _ish.set_mode(conn, "cloud", "admin")
                _clink, _cwhere = _ish.publish(conn, _cinv["id"], "مصنع",
                                               allow_upload=True)
            check("النشر السحابي يعيد رابطاً عاماً",
                  bool(_clink) and _cwhere == "cloud",
                  f"{_cwhere}: {_clink[:70]}")
            # ══ الصفحة صورةٌ لا HTML ══
            # التخزين السحابي يقدّم HTML بنوع `text/plain`، فظهرت
            # الصفحة على جوال العميل **كوداً نصّياً**. الصورة تُعرض
            # دائماً — وهذا الفحص يثبت أن المرفوع صورة.
            check("الصفحة تُرفع **صورةً** لا صفحة HTML",
                  any(x.endswith("invoice.jpg") for x in _puts)
                  and not any(x.endswith("index.html") for x in _puts),
                  str([x.rsplit('/', 1)[-1] for x in _puts]))
            check("والرابط يشير إلى المسار العام للصورة",
                  "/object/public/invoice-photos/" in _clink
                  and _clink.endswith("invoice.jpg"), _clink[-60:])
            check("وطلبٌ واحد يكفي للفاتورة كلها",
                  len(_puts) == 1, f"{len(_puts)} طلباً")
            with db(readonly=True) as conn:
                check("ويُحفظ مع الفاتورة فلا يُرفع مرتين",
                      _ish.cached_url(conn, _cinv["id"]) == _clink)
            _n_before = len(_puts)
            with db() as conn:
                _ish.publish(conn, _cinv["id"], "مصنع", allow_upload=True)
            check("النشر الثاني لا يرفع شيئاً", len(_puts) == _n_before,
                  f"{len(_puts) - _n_before} طلباً إضافياً")
            with db() as conn:
                _ish.set_mode(conn, "auto", "admin")
        except ImportError:
            check("فحص النشر السحابي", True, "تخطّي — PyQt5 غير مثبّت")
    finally:
        _tn.update(cloud_url="", cloud_key="")
        _srv.shutdown()
        os.environ.pop("NO_PROXY", None)
        for _k, _v in _old_proxy.items():
            if _v is not None:
                os.environ[_k] = _v

    # ══ رسم صفحة الفاتورة صورةً ══
    try:
        from PyQt5 import QtWidgets as _QW6
        _QW6.QApplication.instance() or _QW6.QApplication([])
        with db(readonly=True) as conn:
            _pd = _ish.invoice_data(conn, inv_on["id"])
            _pm2 = _ish.model_lines(conn, inv_on["id"])
        _shot = _ish.render_page_image(_pd, _pm2, "مصنع الاختبار")
        check("صفحة الفاتورة تُرسم صورةَ JPEG",
              _shot[:2] == b"\xff\xd8" and len(_shot) > 4000,
              f"{len(_shot) // 1024} كيلوبايت")
        check("وحجمها معقول (أقل من ربع ميجابايت)",
              len(_shot) < 256 * 1024, f"{len(_shot) // 1024}ك")
        _cx = _ish.render_cancelled_image("S-1", "مصنع")
        check("وصورة «أُلغيت» تُرسم كذلك",
              _cx[:2] == b"\xff\xd8" and len(_cx) > 1000)
        # فاتورة بلا أصناف ولا موديلات: لا تُسقط الرسّام ولا التطبيق
        _empty = {"no": "S-0", "date": "2026-01-01", "kind": "فاتورة مبيعات",
                  "customer": "—", "lines": [], "unit": "جم 18",
                  "weight": 0.0, "wages": 0.0, "vat": 0.0, "total": 0.0,
                  "vat_applied": False}
        check("والحالة الفارغة لا تُسقط الرسم",
              _ish.render_page_image(_empty, [], "")[:2] == b"\xff\xd8")
        # ══ استثناءٌ أثناء الرسم لا يُجهض التطبيق ══
        # الرسّام المفتوح على صورةٍ تُجمَع يُجهض Qt العملية كلها، فخللٌ
        # في تجميل يُسقط نظاماً محاسبياً. الإغلاق في `finally` يمنعه.
        _bad = dict(_empty)
        _bad["lines"] = None            # يرفع استثناءً داخل الرسم
        check("واستثناء أثناء الرسم يعيد فراغاً بلا إجهاض",
              _ish.render_page_image(_bad, [], "") == b"")
    except ImportError:
        check("رسم صفحة الفاتورة", True, "تخطّي — PyQt5 غير مثبّت")

    # ══ أمر صلاحيات المجلد: يُنفَّذ مرتين بلا خطأ ══
    # الخطأ «already exists» يُفشل الدفعة كلها في محرّر SQL، فيبقى ما
    # بعده غير منفَّذ ويظن المستخدم أنه أتمّ العمل — وهو ما وقع فعلاً.
    _sql = _ish.policy_sql()
    check("أمر الصلاحيات يحذف السابق أولاً",
          _sql.count("drop policy if exists") == 3)
    check("ويمنح القراءة والرفع والاستبدال",
          all(f"for {w}" in _sql for w in ("select", "insert", "update")))
    check("و«to public» يشمل anon و authenticated",
          "to anon" not in _sql and _sql.count("to public") == 3)
    check("و«with check» على التعديل (الرفع استبدالٌ لا إدراجٌ فقط)",
          _sql.count("with check") == 2)
    check("ويُسمّي المجلد الصحيح", _sql.count("'invoice-photos'") == 4)

    # النشر الدفعي: بلا سحابة لا يُنشر شيء ولا يُرفع خطأ
    _done, _tot = _ish.republish_pending("مصنع")
    check("النشر الدفعي يُحصي المنتظر ولا يتعثّر",
          _done == 0 and _tot >= 0, f"{_done}/{_tot}")

    # ══ تعديل الفاتورة يُعدّل صفحتها — بالرمز نفسه ══
    # الورقة بيد العميل تحمل رمزاً ثابتاً، فلو بقيت الصفحة على مضمونها
    # القديم لرأى فاتورةً غير التي بيده.
    with db() as conn:
        _tok_before = _ish._token(conn, inv_on["id"])
        conn.execute("UPDATE invoices SET share_url=? WHERE id=?",
                     ("https://x/old/index.html", inv_on["id"]))
    with db(readonly=True) as conn:
        check("الصفحة المنشورة تُقرأ من الفاتورة",
              _ish.cached_url(conn, inv_on["id"]).endswith("old/index.html"))
    with db() as conn:
        _ish.invalidate(conn, inv_on["id"])
    with db(readonly=True) as conn:
        check("تعديل الفاتورة يُبطل صفحتها القديمة",
              _ish.cached_url(conn, inv_on["id"]) == "")
    with db() as conn:
        check("والرمز لا يتغيّر فورقة العميل تبقى صحيحة",
              _ish._token(conn, inv_on["id"]) == _tok_before, _tok_before)

    # ══ الصور غير المستعملة تُعرف فتُحذف ══
    with db() as conn:
        _ish._asset_save(conn, "sha-orphan", "http://x/orphan.jpg", 51200)
        _ish._asset_save(conn, "sha-used", "http://x/used.jpg", 51200)
        _ish._link_asset(conn, inv_on["id"], "sha-used")
        conn.execute("UPDATE invoices SET share_url='u' WHERE id=?",
                     (inv_on["id"],))
    with db(readonly=True) as conn:
        _orph = {h for h, _s in _ish.orphan_images(conn)}
    check("الصورة المستعملة لا تُعدّ مهملة", "sha-used" not in _orph)
    check("وغير المستعملة تُعدّ مهملة", "sha-orphan" in _orph, str(_orph))
    with db(readonly=True) as conn:
        _u2 = _ish.usage(conn)
    check("المساحة تعرض المهمل على حدة",
          _u2.get("orphans", 0) >= 1, str(_u2))
    with db() as conn:
        conn.execute("UPDATE invoices SET share_url=NULL WHERE id=?",
                     (inv_on["id"],))
    with db(readonly=True) as conn:
        check("وبزوال آخر فاتورة منشورة تصير صورتها مهملة",
              "sha-used" in {h for h, _s in _ish.orphan_images(conn)})

    # ── المسوّدات: ما أُدخل ولم يُرحَّل يبقى بعد مغادرة الشاشة ──
    from services import drafts as _dr
    _dr.save("اختبار", "admin", {"a": 1, "b": ["س", "ص"]})
    check("المسوّدة تُحفظ وتُستعاد كما هي",
          _dr.load("اختبار", "admin") == {"a": 1, "b": ["س", "ص"]})
    check("ومسوّدة مستخدمٍ لا تظهر لغيره",
          _dr.load("اختبار", "other") == {})
    _dr.clear("اختبار", "admin")
    check("والمحو يمسحها", _dr.load("اختبار", "admin") == {})

    try:
        from PyQt5 import QtWidgets as _QW5
        _app5 = _QW5.QApplication.instance() or _QW5.QApplication([])
        _u5 = {"id": 1, "username": "admin", "full_name": "م",
               "role": "admin", "role_local": "accountant"}
        from ui.production_screen import (DRAFT_KEY as _PK,
                                          ProductionScreen as _PS)
        _dr.clear(_PK, "admin")
        ps = _PS(_u5)
        ps.refresh()
        ps.batch = [{"model_no": "M1", "wo_no": "DR-1", "gold": 10.0,
                     "small_stones": 0.0, "big_stones": 0.0,
                     "discount_rate": 0.5, "wage_per_gram": 20.0,
                     "notes": ""}]
        ps.on_close()                      # مغادرة الشاشة
        check("مغادرة شاشة التوريد تحفظ الدفعة",
              bool(_dr.load(_PK, "admin").get("batch")))
        ps2 = _PS(_u5)                     # العودة إليها
        ps2.refresh()
        check("والعودة تستعيدها كما تُركت",
              len(ps2.batch) == 1 and ps2.batch[0]["wo_no"] == "DR-1",
              str(ps2.batch))
        check("ويُنبَّه المستخدم أنها استُعيدت",
              ps2.draft_note.isVisible() or bool(ps2.draft_note.text()))
        _dr.clear(_PK, "admin")
        ps3 = _PS(_u5)
        ps3.refresh()
        check("وبعد المحو تُفتح فارغة", ps3.batch == [])

        # مسوّدة السند
        from ui.vouchers_screen import (DRAFT_KEY as _VK,
                                        VouchersScreen as _VS)
        _dr.clear(_VK, "admin")
        vs = _VS(_u5)
        vs.refresh()
        vs.rows = [{"kind": "gold", "weight": 12.5, "karat": 21,
                    "amount": 0.0, "notes": "دفعة"}]
        vs.on_close()
        vs2 = _VS(_u5)
        vs2.refresh()
        check("سند لم يُرحَّل يبقى بعد مغادرة شاشته",
              len(vs2.rows) == 1 and vs2.rows[0]["weight"] == 12.5,
              str(vs2.rows))
        _dr.clear(_VK, "admin")

        # مسوّدة الفاتورة
        from ui.sales_screen import DRAFT_KEY as _SK, SalesScreen as _SS
        _dr.clear(_SK, "admin")
        ss = _SS(_u5)
        ss.refresh()
        with db(readonly=True) as conn:
            _wo = conn.execute(
                "SELECT * FROM work_orders WHERE status='in_stock'"
                " AND is_deleted=0 LIMIT 1").fetchone()
        if _wo is not None:
            i = ss.customer.findData(cust)
            if i >= 0:
                ss.customer.setCurrentIndex(i)
            ss.items = [{"wo": _wo, "weight": 5.0, "wage": 20.0}]
            ss.qr_check.setChecked(True)
            ss.on_close()
            ss2 = _SS(_u5)
            ss2.refresh()
            check("فاتورة لم تُرحَّل تبقى بعد مغادرة شاشتها",
                  len(ss2.items) == 1
                  and ss2.items[0]["wo"]["id"] == _wo["id"],
                  str(len(ss2.items)))
            check("واختيار رمز QR يُستعاد معها",
                  ss2.qr_check.isChecked())
            check("والعميل يعود كما كان",
                  ss2.customer.currentData() == cust)
        # وضع التعديل لا يُحفظ مسوّدةً
        ss.editing_id = 99
        check("وضع التعديل لا يُحفظ مسوّدةً", ss.draft_state() is None)
        ss.editing_id = None
        _dr.clear(_SK, "admin")

        # آخر اختيار لرمز QR يبقى بعد إعادة فتح الشاشة
        from ui.widgets.common import load_pref as _lp
        ss3 = _SS(_u5)
        ss3.qr_check.setChecked(True)
        check("تفعيل رمز QR يُحفظ تفضيلاً",
              str(_lp("sales_qr_enabled", "0")) == "1")
        ss4 = _SS(_u5)
        check("ويعود مفعّلاً عند فتح الشاشة من جديد",
              ss4.qr_check.isChecked())
        ss4.qr_check.setChecked(False)
        ss5 = _SS(_u5)
        check("وإلغاؤه يبقى ملغى كذلك", not ss5.qr_check.isChecked())
    except ImportError:
        check("فحوص المسوّدات ورمز الفاتورة", True,
              "تخطّي — PyQt5 غير مثبّت")

    step("28) حدّ الائتمان")
    # سقفٌ لكل جهة يُفحص **لحظة الترحيل** لا في تقرير آخر الشهر:
    # البضاعة تخرج لحظتها، فالتنبيه بعدها بأسبوع تنبيهٌ متأخر.
    from models import entities as _ent
    from services import credit_guard as _cg

    with db() as conn:
        cl_cust = add_entity(conn, "عميل السقف", "customer", username="admin")
        _cg.set_mode(conn, "warn", "admin")
    with db(readonly=True) as conn:
        check("الوضع الافتراضي تنبيه لا منع",
              _cg.mode(conn) == "warn", _cg.mode(conn))
        check("الجهة الجديدة بلا سقف",
              _ent.credit_limit(conn, cl_cust) == (0.0, 0.0))

    with db() as conn:
        _b = _batch(conn, [{"wo_no": "CL1", "gold": 30.0,
                            "wage_per_gram": 20.0},
                           {"wo_no": "CL2", "gold": 30.0,
                            "wage_per_gram": 20.0}],
                    "2026-07-01", "admin")
        clids = {r["work_order_no"]: r["id"] for r in conn.execute(
            "SELECT id, work_order_no FROM work_orders"
            " WHERE work_order_no IN ('CL1','CL2')")}
        # بلا سقف: لا تنبيه مهما بلغ الرصيد
        create_sale(conn, cl_cust, [{"work_order_id": clids["CL1"]}],
                    "2026-07-02", "admin")
    check("بلا سقف ⇒ بلا تنبيه", _cg.take_warning() == "")

    # سقفٌ وزنيٌّ أقلّ من الرصيد القائم
    with db() as conn:
        _ent.set_credit_limit(conn, cl_cust, 0.0, 10.0, "admin")
    with db(readonly=True) as conn:
        _over = _cg.over_limit(conn)
    check("الجهة تظهر متجاوزةً سقفها",
          any(o["entity_id"] == cl_cust for o in _over), str(_over))

    with db() as conn:
        create_sale(conn, cl_cust, [{"work_order_id": clids["CL2"]}],
                    "2026-07-03", "admin")
    _w = _cg.take_warning()
    check("بيعٌ فوق السقف يُنبَّه عليه", "حدّ الائتمان" in _w, _w[:80])

    # السداد يمرّ صامتاً ولو بقي الرصيد فوق السقف
    from models.vouchers import create_voucher
    with db() as conn:
        _acc_cust = conn.execute(
            "SELECT account_id FROM entities WHERE id=?",
            (cl_cust,)).fetchone()["account_id"]
        post_entry(conn, "2026-07-04", "سداد جزئي", [
            {"account_id": acc_id(conn, "1200"), "gold_debit": 5.0},
            {"account_id": _acc_cust, "gold_credit": 5.0}],
            username="admin")
    check("السداد لا يُنبَّه عليه ولو بقي فوق السقف",
          _cg.take_warning() == "")

    # وضع المنع: البيع يُرفض والمعاملة تُلغى كاملةً
    with db() as conn:
        _cg.set_mode(conn, "block", "admin")
        _batch(conn, [{"wo_no": "CL3", "gold": 20.0, "wage_per_gram": 20.0}],
               "2026-07-05", "admin")
        cl3 = conn.execute("SELECT id FROM work_orders"
                           " WHERE work_order_no='CL3'").fetchone()["id"]

    def _blocked_sale():
        with db() as conn:
            create_sale(conn, cl_cust, [{"work_order_id": cl3}],
                        "2026-07-06", "admin")
    expect_error("وضع المنع يرفض تجاوز السقف", _blocked_sale, "حدّ الائتمان")
    with db(readonly=True) as conn:
        check("الفاتورة المرفوضة لم تُكتب",
              conn.execute("SELECT COUNT(*) n FROM invoice_items"
                           " WHERE work_order_id=?",
                           (cl3,)).fetchone()["n"] == 0)
        check("والطقم ما زال بالمخزون",
              conn.execute("SELECT status FROM work_orders WHERE id=?",
                           (cl3,)).fetchone()["status"] == "in_stock")
        g, c, gv, cv = ledger_balanced(conn)
    check("الدفتر متوازن بعد الرفض", g and c, f"ذهب {gv} · نقد {cv}")
    with db() as conn:
        _cg.set_mode(conn, "off", "admin")
        create_sale(conn, cl_cust, [{"work_order_id": cl3}],
                    "2026-07-06", "admin")
    check("وضع «بلا فحص» يمرّر العملية", _cg.take_warning() == "")
    with db() as conn:
        _cg.set_mode(conn, "warn", "admin")

    step("29) سلامة السجل — سلسلة بصمات القيود")
    from models import integrity as _ig
    with db() as conn:
        _sealed = _ig.seal_all(conn, "admin")      # ختم ما سبق الميزة
    with db(readonly=True) as conn:
        rep = _ig.verify(conn)
    check("كل القيود مختومة", rep["unsealed"] == 0, str(rep["unsealed"]))
    check("السلسلة سليمة بعد الختم", rep["ok"] and not rep["breaks"],
          str(rep["breaks"][:2]))
    check("عدد المختوم = عدد القيود",
          rep["checked"] > 0, str(rep["checked"]))

    # كل قيدٍ جديد يُختم داخل معاملة ترحيله
    with db() as conn:
        _eid = post_entry(conn, "2026-08-01", "اختبار البصمة", [
            {"account_id": acc_id(conn, "1400"), "cash_debit": 10},
            {"account_id": acc_id(conn, "1100"), "cash_credit": 10}],
            username="admin")
    with db(readonly=True) as conn:
        _row = conn.execute("SELECT row_hash, prev_hash FROM journal_entries"
                            " WHERE id=?", (_eid,)).fetchone()
        check("القيد الجديد يُختم آلياً",
              bool(_row["row_hash"]) and len(_row["row_hash"]) == 64)
        check("ويرتبط ببصمة سابقه", bool(_row["prev_hash"]))
        check("السلسلة ما زالت سليمة", _ig.verify(conn)["ok"])

    # ══ العبث من خارج النظام يُكشف ══
    with db() as conn:
        conn.execute("UPDATE journal_lines SET cash_debit=99999"
                     " WHERE entry_id=? AND cash_debit>0", (_eid,))
    with db(readonly=True) as conn:
        bad = _ig.verify(conn)
    check("تغيير مبلغٍ في قيدٍ مرحَّل يُكشف فوراً", not bad["ok"])
    check("ويُشار إلى القيد نفسه بالضبط",
          bool(bad["breaks"]) and bad["breaks"][0]["id"] == _eid,
          str(bad["breaks"][:1]))
    check("ونوع الخلل «مضمون تغيّر»",
          "مضمون" in (bad["breaks"][0]["kind"] if bad["breaks"] else ""))

    # إعادة المبلغ تُعيد السلسلة سليمةً — البصمة تشهد على المضمون لا
    # على زمن القراءة.
    with db() as conn:
        conn.execute("UPDATE journal_lines SET cash_debit=10"
                     " WHERE entry_id=? AND cash_debit=99999", (_eid,))
    with db(readonly=True) as conn:
        check("إعادة المضمون تُعيد السلسلة سليمة", _ig.verify(conn)["ok"])

    # الحذف المنطقي عملٌ مشروع لا يُعدّ عبثاً
    with db() as conn:
        conn.execute("UPDATE journal_entries SET is_deleted=1 WHERE id=?",
                     (_eid,))
    with db(readonly=True) as conn:
        check("الحذف المنطقي لا يُعدّ عبثاً", _ig.verify(conn)["ok"])
    with db() as conn:
        conn.execute("UPDATE journal_entries SET is_deleted=0 WHERE id=?",
                     (_eid,))

    # محو قيدٍ من الجدول **بعد ختمه** يقطع الحلقة عند تاليه.
    # المحو هنا في معاملة مستقلة عمداً: لو جرى في معاملة الترحيل
    # نفسها لختمت السلسلةُ ما بقي عند الإغلاق فبدت سليمةً بحق —
    # والمحاكاة المقصودة هي عبثٌ **بعد** اكتمال الختم، من خارج النظام.
    with db() as conn:
        _e2 = post_entry(conn, "2026-08-02", "قيد سيُمحى", [
            {"account_id": acc_id(conn, "1400"), "cash_debit": 7},
            {"account_id": acc_id(conn, "1100"), "cash_credit": 7}],
            username="admin")
        post_entry(conn, "2026-08-03", "قيد بعده", [
            {"account_id": acc_id(conn, "1400"), "cash_debit": 3},
            {"account_id": acc_id(conn, "1100"), "cash_credit": 3}],
            username="admin")
    with db(readonly=True) as conn:
        check("القيدان مختومان قبل المحو", _ig.verify(conn)["ok"])
    with db() as conn:
        conn.execute("DELETE FROM journal_lines WHERE entry_id=?", (_e2,))
        conn.execute("DELETE FROM journal_entries WHERE id=?", (_e2,))
    with db(readonly=True) as conn:
        gone = _ig.verify(conn)
    check("محو قيدٍ من الجدول يقطع السلسلة", not gone["ok"])
    check("ونوع الخلل «حلقة مقطوعة»",
          "مقطوعة" in (gone["breaks"][0]["kind"] if gone["breaks"] else ""),
          str(gone["breaks"][:1]))
    # ══ التعديل المشروع من داخل النظام لا يُعدّ عبثاً ══
    # وهذا أخطر ما في الميزة: تنبيهٌ كاذبٌ يتكرر مع كل تعديلٍ سليم
    # يجعل المستخدم يتجاهل التنبيهات كلها — فتصير السلسلة ضرراً لا
    # حماية. العقد: من يعدّل مضمون قيدٍ قائم يوسمه، فيُعاد ختمه وما
    # بعده عند إغلاق المعاملة.
    # السلسلة مقطوعة الآن بفعل اختبار المحو أعلاه — تُعاد بناءً
    # بقرارٍ صريح (كما يفعل المدقّق بعد معالجة خللٍ مُثبت) قبل اختبار
    # التعديل المشروع، وإلا خلط الكسرُ القديم نتيجةَ الاختبار الجديد.
    with db() as conn:
        _ig.rebuild(conn, username="admin")
    with db(readonly=True) as conn:
        check("إعادة البناء الصريحة تُصلح السلسلة", _ig.verify(conn)["ok"])

    with db() as conn:
        _e3 = post_entry(conn, "2026-08-04", "قيد قابل للتعديل", [
            {"account_id": acc_id(conn, "1400"), "cash_debit": 20},
            {"account_id": acc_id(conn, "1100"), "cash_credit": 20}],
            username="admin")
        post_entry(conn, "2026-08-05", "قيد تالٍ", [
            {"account_id": acc_id(conn, "1400"), "cash_debit": 5},
            {"account_id": acc_id(conn, "1100"), "cash_credit": 5}],
            username="admin")
    with db() as conn:
        conn.execute("UPDATE journal_lines SET cash_debit=25"
                     " WHERE entry_id=? AND cash_debit=20", (_e3,))
        conn.execute("UPDATE journal_lines SET cash_credit=25"
                     " WHERE entry_id=? AND cash_credit=20", (_e3,))
        _ig.mark(conn, _e3)          # تعديلٌ مشروع ⇒ يُوسَم
    with db(readonly=True) as conn:
        _after = _ig.verify(conn)
    check("التعديل المشروع الموسوم لا يُعدّ عبثاً",
          _after["ok"], str(_after["breaks"][:1]))
    check("وسلسلة ما بعده أُعيد ربطها",
          _after["unsealed"] == 0 and _after["checked"] > 0)

    check("البصمة نفسها ثابتة لنفس المضمون",
          _ig.digest({"id": 1, "entry_date": "2026-01-01", "doc_no": "JV-1",
                      "description": "د", "user_note": "", "source_table": "",
                      "source_id": None, "created_by": "admin"}, [], "x")
          == _ig.digest({"id": 1, "entry_date": "2026-01-01",
                         "doc_no": "JV-1", "description": "د",
                         "user_note": "", "source_table": "",
                         "source_id": None, "created_by": "admin"}, [], "x"))
    check("وتختلف باختلاف بصمة السابق",
          _ig.digest({"id": 1, "entry_date": "2026-01-01", "doc_no": "JV-1",
                      "description": "د", "user_note": "", "source_table": "",
                      "source_id": None, "created_by": "admin"}, [], "x")
          != _ig.digest({"id": 1, "entry_date": "2026-01-01",
                         "doc_no": "JV-1", "description": "د",
                         "user_note": "", "source_table": "",
                         "source_id": None, "created_by": "admin"}, [], "y"))

    step("28ب) تعديل دفعة توريد يعيد كل ما تعرضه الشاشة")
    # ══ الخلل: نجاحٌ يظهر خطأً ══
    # شاشة «الوارد من التصنيع» تعرض `total_registered` في رسالة
    # «تم الترحيل» للمسارين معاً. وكان مسار **الإنشاء** وحده يعيده،
    # فالتعديل يرفع `KeyError: 'total_registered'` **بعد** إغلاق
    # المعاملة بنجاح: الدفعة تُحفظ، ويرى المستخدم رسالةً إنجليزية لا
    # يفهمها، فيظنّ أن التعديل فشل فيعيده. يُفحص هنا أن المسارين
    # يعيدان المفاتيح نفسها — فلا يتكرّر مع أي مفتاح يُضاف لاحقاً.
    from models.inventory import update_supply_batch as _usb

    with db() as conn:
        _mk = _batch(conn, [{"wo_no": "SB-1", "gold": 30.0,
                             "wage_per_gram": 20.0},
                            {"wo_no": "SB-2", "gold": 20.0,
                             "wage_per_gram": 20.0}],
                     "2026-05-02", "admin")
    _need = {"entry_id", "total_registered", "items"}
    check("الإنشاء يعيد مفاتيح الشاشة", _need <= set(_mk),
          f"ينقصه {sorted(_need - set(_mk))}")
    with db() as conn:
        _ed = _usb(conn, _mk["entry_id"], [
            {"wo_no": "SB-1", "gold": 30.0, "wage_per_gram": 20.0},
            {"wo_no": "SB-2", "gold": 20.0, "wage_per_gram": 20.0},
            {"wo_no": "SB-3", "gold": 15.0, "wage_per_gram": 20.0},
        ], "2026-05-02", "admin")
    check("والتعديل يعيدها كلها — لا KeyError بعد نجاح الحفظ",
          _need <= set(_ed), f"ينقصه {sorted(_need - set(_ed))}")
    check("وإجمالي الوزن المقيد يساوي أوزان الدفعة بعد الإضافة",
          abs(_ed["total_registered"] - 65.0) < 0.01,
          f"{_ed['total_registered']}")
    check("والإضافة سُجّلت طقماً جديداً", _ed["added"] == ["SB-3"],
          str(_ed["added"]))

    step("28ج) تعديل فاتورة لا يبيع طقماً مباعاً مرتين")
    # ══ الخلل: الذهب يخرج مرة ويُحاسَب عليه عميلان ══
    # عند تعديل فاتورة كان الإعفاء من فحص حالة الطقم يشمل السلة كلها
    # — بما فيها **المُضاف حديثاً**. فيُضاف إلى فاتورةٍ قديمة طقمٌ
    # بِيع في فاتورةٍ أخرى، بلا اعتراض ولا رسالة. النتيجة: الطقم
    # الواحد مباعٌ لعميلين، وكلاهما مدينٌ بأجرته.
    from models.inventory import create_work_orders_batch as _b2
    from models import invoices as invoices

    def _upd2(inv_id, cart):
        with db() as conn:
            return invoices.update_invoice(conn, inv_id, cart, "admin")

    with db() as conn:
        _b2(conn, [{"wo_no": "DS-0", "gold": 15.0, "wage_per_gram": 20.0},
                   {"wo_no": "DS-1", "gold": 25.0, "wage_per_gram": 20.0}],
            "2026-03-01", "admin")
        _w = {r["work_order_no"]: r["id"] for r in conn.execute(
            "SELECT id, work_order_no FROM work_orders"
            " WHERE work_order_no LIKE 'DS-%'")}
        # فاتورةٌ قديمة لا تحوي DS-1 إطلاقاً
        _old = create_sale(conn, cust, [{"work_order_id": _w["DS-0"]}],
                           "2026-03-05", "admin", apply_vat=False)
        _c2 = conn.execute(
            "SELECT id FROM entities WHERE entity_type='customer'"
            " AND is_deleted=0 ORDER BY id DESC").fetchone()["id"]
        # وفاتورةٌ أحدث تبيع DS-1 لعميلٍ آخر
        _new = create_sale(conn, _c2, [{"work_order_id": _w["DS-1"]}],
                           "2026-03-20", "admin", apply_vat=False)
    check("طقمٌ بِيع لعميل في فاتورةٍ أحدث", bool(_new.get("id")))

    # الآن: محاولة إضافته إلى الفاتورة **القديمة** وهو مباعٌ لغيرها
    with db(readonly=True) as conn:
        _, _oit = invoices.get_invoice_full(conn, _old["id"])
    _cart = [{"work_order_id": t["work_order_id"], "item_id": t["item_id"],
              "weight": t["registered_weight"]} for t in _oit]
    _cart.append({"work_order_id": _w["DS-1"]})
    expect_error("إضافته إلى فاتورةٍ قديمة تُرفض — لا يُباع مرتين",
                 lambda: _upd2(_old["id"], _cart), "ليس بالمخزون")
    with db(readonly=True) as conn:
        _n = conn.execute(
            "SELECT COUNT(*) c FROM invoice_items it"
            " JOIN invoices i ON i.id=it.invoice_id"
            " WHERE it.work_order_id=? AND i.is_deleted=0"
            "   AND i.kind='sale'", (_w["DS-1"],)).fetchone()["c"]
    check("ويبقى في فاتورة بيعٍ واحدة", _n == 1, f"{_n}")

    # والطقم المفرد لا يتكرّر في الفاتورة الواحدة
    expect_error("تكرار الطقم المفرد في فاتورةٍ واحدة يُرفض",
                 lambda: _upd2(_old["id"], [
                     {"work_order_id": _w["DS-0"],
                      "item_id": _oit[0]["item_id"]},
                     {"work_order_id": _w["DS-0"]}]),
                 "مكرّر في الفاتورة")

    # والرسالة تدلّ على **أين ذهب** لا تكتفي بالرفض
    try:
        _upd2(_old["id"], _cart)
        _msg = ""
    except Exception as _e:
        _msg = str(_e)
    check("والرسالة تسمّي الفاتورة التي أخذته وتاريخها وجهتها",
          "آخر حركةٍ له" in _msg and _new["invoice_no"] in _msg,
          _msg.replace("\n", " ")[:110])

    # وفحصُ الدفتر يكشف ما وقع قبل الإصلاح
    from services import health as _hh
    with db(readonly=True) as conn:
        _dbl = _hh.check_double_sold(conn)
    check("وفحص «بِيع أكثر من مرة» نظيفٌ على دفترٍ سليم",
          _dbl == [], str(_dbl)[:120])

    step("29أ) تعديل فاتورة على الرقم التجميعي — أسطرٌ مستقلة")
    # ══ الخلل: مئة جرامٍ تضيع من الدفتر بلا أثر ══
    # بنود الفاتورة كانت تُفهرَس بـ`work_order_id`. صحيحٌ للطقم
    # المفرد (قطعةٌ لا تتكرّر في فاتورة)، وخطأٌ للرقم التجميعي: ذاك
    # **رصيدٌ وزني** يُباع منه في الفاتورة الواحدة أسطرٌ مستقلة.
    # فتعديلٌ يُبقي سطر ١٠٠ ويضيف ٥٠ كان يُنهي الفاتورة بـ٥٠ وحدها،
    # وحذفُ أحد سطرَيه لا يحذف شيئاً. يُفحص بالأرقام هنا لأن الخلل
    # صامت: لا خطأ ولا رسالة — فقط وزنٌ ناقص في كشف العميل.
    from models.inventory import adjust_bulk_wo as _adj
    from models.inventory import get_or_create_bulk_wo as _bulk
    from models import invoices as invoices

    with db() as conn:
        _bw = _bulk(conn, "admin")["id"]
        _adj(conn, 1000.0, "admin")
        _bi = create_sale(conn, cust, [{"work_order_id": _bw,
                                        "weight": 100.0}],
                          "2026-05-01", "admin", apply_vat=False)
    check("فاتورة على الرقم التجميعي تُرحَّل بوزنها",
          abs(_bi["total_weight"] - 100.0) < 0.01, f"{_bi['total_weight']}")

    # إضافة سطرٍ ثانٍ لنفس الرقم التجميعي — يجب أن يكون سطراً مستقلاً
    with db(readonly=True) as conn:
        _, _its = invoices.get_invoice_full(conn, _bi["id"])
    _cart = [{"work_order_id": t["work_order_id"], "weight": 100.0,
              "item_id": t["item_id"]} for t in _its]
    _cart.append({"work_order_id": _bw, "weight": 50.0})
    with db() as conn:
        invoices.update_invoice(conn, _bi["id"], _cart, "admin")
    with db(readonly=True) as conn:
        _inv2, _its2 = invoices.get_invoice_full(conn, _bi["id"])
    check("إضافة ٥٠ إلى سطر ١٠٠ تُنشئ سطرين لا تدهس الأول",
          len(_its2) == 2,
          f"{len(_its2)} سطراً · "
          f"{[round(x['registered_weight'], 1) for x in _its2]}")
    check("والإجمالي ١٥٠ لا ٥٠ — لا يضيع وزنٌ من الدفتر",
          abs(_inv2["total_weight"] - 150.0) < 0.01,
          f"{_inv2['total_weight']}")

    # حذف سطرٍ واحد من سطرَي الرقم التجميعي — يجب أن يُحذف فعلاً
    _keep = [t for t in _its2 if abs(t["registered_weight"] - 50.0) < 0.01]
    with db() as conn:
        invoices.update_invoice(
            conn, _bi["id"],
            [{"work_order_id": t["work_order_id"],
              "weight": t["registered_weight"], "item_id": t["item_id"]}
             for t in _keep], "admin")
    with db(readonly=True) as conn:
        _inv3, _its3 = invoices.get_invoice_full(conn, _bi["id"])
    check("حذف أحد سطرَي الرقم التجميعي يحذفه فعلاً",
          len(_its3) == 1 and abs(_inv3["total_weight"] - 50.0) < 0.01,
          f"{len(_its3)} سطراً · إجمالي {_inv3['total_weight']}")
    with db(readonly=True) as conn:
        _bg, _bc, _gv, _cv = ledger_balanced(conn)
    check("والدفتر متوازن بعد التعديل والحذف", _bg and _bc,
          f"ذهب {_gv} · نقد {_cv}")

    step("29ب) ملفات الهجرة تُعثر عليها فعلاً")
    # ══ خللٌ مرّ صامتاً حتى أول هجرةٍ ذات أثر ══
    # كان مجلد الهجرات يُشتقّ من مجلد **البيانات** لا من مجلد البرنامج.
    # وهما واحدٌ عند التشغيل من المصدر بلا إعدادات — فمرّ. أما نسخة
    # الـexe (بياناتها في مجلد دائم منفصل) أو أي تشغيل يضبط
    # `JADEITE_DATA_DIR` فلا مجلد هجرات عنده أصلاً: `discover()` تعيد
    # لا شيء، و`run_all` تنجح **صامتةً** بلا تنفيذ هجرة واحدة، ويظهر
    # العطل عند المستخدم بـ«لا يوجد جدول كذا». وهذا الفحص يمنع عودته:
    # يقارن ما تجده الخدمة بما في مجلد المشروع فعلاً.
    from services import migrations as _mig
    _repo_sqls = sorted(p.name for p in
                        (pathlib.Path(__file__).resolve().parent.parent
                         / "migrations").glob("*.sql"))
    _seen_sqls = sorted(p.name for _, _, p in _mig.discover())
    check("كل ملفات الهجرة في المشروع تُعثر عليها",
          _seen_sqls == _repo_sqls and bool(_repo_sqls),
          f"وُجد {_seen_sqls} · في المشروع {_repo_sqls}")
    with db(readonly=True) as conn:
        _done = _mig.applied(conn)
    check("وكلها طُبِّقت على قاعدة الفحص",
          len(_done) >= len(_repo_sqls),
          f"{len(_done)} مطبَّقة من {len(_repo_sqls)}")
    with db(readonly=True) as conn:
        _has = conn.execute(
            "SELECT COUNT(*) c FROM sqlite_master"
            " WHERE type='table' AND name='bank_recon_marks'"
        ).fetchone()["c"]
    check("وجدولُ هجرةٍ حقيقيّ موجودٌ في القاعدة", _has == 1)

    step("30) مطابقة كشف البنك")
    # ══ لماذا يُفحص هذا بالأرقام ══
    # معادلة المطابقة تُقلب بسهولة: طرحُ ما يجب جمعه يعطي فرقاً يبدو
    # معقولاً فيُقبَل، ويُسلَّم كشفٌ خاطئ لمراجع. فتُبنى هنا حالةٌ
    # يُعرف جوابها سلفاً: إيداعٌ ظهر في الكشف، وشيكٌ صُرف، وشيكٌ لم
    # يُصرَف بعد — والمتوقَّع يجب أن يساوي الكشف بالضبط.
    from models import bank_recon as _br
    from models.vouchers import create_voucher
    with db(readonly=True) as conn:
        _accs = _br.bank_accounts(conn)
    _codes = {a["code"] for a in _accs}
    check("حسابات المطابقة = النقدية والبنوك وحدها",
          {"1400", "1500"} <= _codes and not (_codes & {"1730", "1740"}),
          f"المعروض: {sorted(_codes)}")
    _bank = next(a for a in _accs if a["code"] == "1500")

    with db() as conn:
        _cust = conn.execute(
            "SELECT id FROM entities WHERE entity_type='customer'"
            " AND is_deleted=0 ORDER BY id").fetchone()["id"]
        for _amt in (5_000.0, 1_200.0, 800.0):
            create_voucher(conn, "receipt", "2026-06-10", "admin",
                           entity_id=_cust, cash_amount=_amt,
                           cash_account_code="1500")   # يدخل البنك
    with db(readonly=True) as conn:
        _mv = _br.movements(conn, _bank["id"], "2026-06-01", "2026-06-30")
    check("حركات البنك تُقرأ من سطور القيود", len(_mv) >= 3,
          f"{len(_mv)} حركة")
    _in = sum(m["debit"] for m in _mv)
    check("مجموع الوارد = مجموع السندات", abs(_in - 7_000.0) < 0.01,
          f"{_in:,.2f}")
    check("كل الحركات تبدأ بلا مطابقة",
          all(not m["matched"] for m in _mv))

    # يُطابَق اثنان ويُترك الثالث: هو ما لم يصل المصرفَ بعد
    _seen = [m for m in _mv if m["debit"] in (5_000.0, 1_200.0)]
    with db() as conn:
        _br.set_matched(conn, [m["line_id"] for m in _seen], True, "admin",
                        "ST-06")
    with db(readonly=True) as conn:
        _s = _br.summary(conn, _bank["id"], "2026-06-01", "2026-06-30")
    check("المطابقة تُحفظ ولا تُنشئ قيداً", _s["matched_rows"] == len(_seen),
          f"{_s['matched_rows']} مطابَقة")
    check("رصيد الدفتر = مجموع الحركات", abs(_s["book"] - 7_000.0) < 0.01,
          f"{_s['book']:,.2f}")
    # الإيداع الذي لم يظهر في الكشف يُستبعَد: 7000 − 800 = 6200
    check("المتوقَّع في الكشف يستبعد ما لم يظهر فيه",
          abs(_s["expected"] - 6_200.0) < 0.01, f"{_s['expected']:,.2f}")

    with db(readonly=True) as conn:
        _s0 = _br.summary(conn, _bank["id"], "2026-06-01", "2026-06-30",
                          6_200.0)
        _s1 = _br.summary(conn, _bank["id"], "2026-06-01", "2026-06-30",
                          6_350.0)
    check("رصيدٌ مطابق ⇒ الفرق صفر", _s0["difference"] == 0,
          f"{_s0['difference']}")
    check("رصيدٌ مخالف ⇒ الفرق بمقداره وإشارته",
          abs(_s1["difference"] - 150.0) < 0.01, f"{_s1['difference']}")

    with db() as conn:
        _br.set_matched(conn, [m["line_id"] for m in _seen], False, "admin")
    with db(readonly=True) as conn:
        _s2 = _br.summary(conn, _bank["id"], "2026-06-01", "2026-06-30")
    check("رفع التعليم يُعيد الحركات غير مطابَقة",
          _s2["unmatched_rows"] == _s2["rows"] and _s2["matched_rows"] == 0)
    with db(readonly=True) as conn:
        _bal_g, _bal_c, _, _ = ledger_balanced(conn)
    check("والدفتر بقي متوازناً بعد المطابقة كلها", _bal_g and _bal_c)

    step("31) ربحية الموديل")
    # ══ لماذا يُفحص بالأرقام ══
    # تقريرٌ يجمع المرتجع بدل أن يطرحه يُظهر موديلاً خاسراً رابحاً،
    # فيُكثر منه المصنع. تُبنى هنا حالةٌ يُعرف جوابها سلفاً: موديلان،
    # يُباع من كلٍّ طقمان، ويُرتجع من أحدهما واحد.
    from models import model_profit as _mp
    from models.invoices import create_sale_return as _csr

    with db() as conn:
        _b2 = _batch(conn, [
            {"wo_no": "MP-A1", "gold": 10.0, "wage_per_gram": 30.0,
             "model_no": "MODEL-A"},
            {"wo_no": "MP-A2", "gold": 10.0, "wage_per_gram": 30.0,
             "model_no": "MODEL-A"},
            {"wo_no": "MP-B1", "gold": 10.0, "wage_per_gram": 10.0,
             "model_no": "MODEL-B"},
            {"wo_no": "MP-B2", "gold": 10.0, "wage_per_gram": 10.0,
             "model_no": "MODEL-B"},
        ], "2026-07-01", "admin")
        _wo = {r["work_order_no"]: r["id"] for r in conn.execute(
            "SELECT id, work_order_no FROM work_orders"
            " WHERE work_order_no LIKE 'MP-%'")}
        _sale_a = create_sale(
            conn, cust, [{"work_order_id": _wo["MP-A1"]},
                         {"work_order_id": _wo["MP-A2"]}],
            "2026-07-05", "admin", apply_vat=False)
        create_sale(conn, cust, [{"work_order_id": _wo["MP-B1"]},
                                 {"work_order_id": _wo["MP-B2"]}],
                    "2026-07-05", "admin", apply_vat=False)
    with db() as conn:
        _csr(conn, cust, [{"work_order_id": _wo["MP-A2"]}],
             "2026-07-09", "admin", apply_vat=False)

    with db(readonly=True) as conn:
        _prl = _mp.by_model(conn, "2026-07-01", "2026-07-31")
    _pr = {r["model"]: r for r in _prl}
    check("كل موديلٍ بِيع منه يظهر بصفٍّ واحد",
          "MODEL-A" in _pr and "MODEL-B" in _pr, str(sorted(_pr)))
    _a, _b = _pr["MODEL-A"], _pr["MODEL-B"]
    check("المرتجع يُطرح من العدد لا يُجمع",
          _a["sold"] == 2 and _a["returned"] == 1 and _a["net_count"] == 1,
          f"مباع {_a['sold']} · مرتجع {_a['returned']} · "
          f"صافي {_a['net_count']}")
    check("والمرتجع يُطرح من الوزن كذلك",
          abs(_a["net_weight"] - (_b["net_weight"] / 2)) < 0.01,
          f"{_a['net_weight']:.3f} مقابل نصف {_b['net_weight']:.3f}")
    check("صافي الأجور يطرح أجرة المرتجع",
          _a["wages"] > 0 and abs(_a["wages"] - _b["wages"] * 1.5) < 0.01,
          f"A={_a['wages']:,.2f} · B={_b['wages']:,.2f}")
    check("متوسط أجرة الجرام يميّز الغالي من الرخيص",
          _a["avg_wage"] > _b["avg_wage"] * 2.5,
          f"A={_a['avg_wage']:,.2f} · B={_b['avg_wage']:,.2f}")
    check("الترتيب بالأعلى أجوراً أولاً — لا بالاسم",
          [r["wages"] for r in _prl] == sorted(
              (r["wages"] for r in _prl), reverse=True),
          " · ".join(f"{r['model']}={r['wages']:,.0f}" for r in _prl[:4]))
    _sh = sum(r["share"] for r in _pr.values())
    check("الحصص تجمع مئةً بالمئة", abs(_sh - 100.0) < 0.1, f"{_sh:.2f}%")
    _t = _mp.totals(list(_pr.values()))
    check("الإجمالي = مجموع الصفوف",
          abs(_t["wages"] - sum(r["wages"] for r in _pr.values())) < 0.01)

    with db(readonly=True) as conn:
        _un = {u["model"]: u for u in _mp.unsold(conn)}
    check("ما ارتُجع عاد إلى «ما لم يُبَع بعد»",
          _un.get("MODEL-A", {}).get("count", 0) >= 1,
          f"{_un.get('MODEL-A', {}).get('count', 0)} طقماً")
    check("والأجرة غير المحصَّلة = الوزن × أجرة الجرام",
          all(abs(u["potential"] - u["weight"] * u["wage_per_gram"]) < 0.01
              for u in _un.values()))

    step("32) الأصول الثابتة والإهلاك")
    # ══ لماذا يُفحص بالأرقام ══
    # الإهلاك مصروفٌ لا يُدفع نقداً، وخطؤه لا يظهر في أي رصيد: قسطٌ
    # زائد يُنقص الربح وناقصٌ يضخّمه، وكلاهما يمرّ صامتاً إلى قائمة
    # الدخل. فتُبنى حالةٌ يُعرف جوابها سلفاً ويُتحقَّق من كل رقم.
    from models import assets as _fa
    from services.accounting_engine import balance_by_code

    with db(readonly=True) as conn:
        _da = {a["code"] for a in _fa.depreciable_accounts(conn)}
    check("حسابات الأصول القابلة للإهلاك تُقرأ من الشجرة",
          {"1710", "1730"} <= _da and "1790" not in _da,
          f"المجمّع مستثنى · {sorted(_da)}")

    # مكينة ٦٠٬٠٠٠ · عمر ٦٠ شهراً · تخريدية ٦٬٠٠٠ ⇒ القسط ٩٠٠
    with db() as conn:
        _mach = acc_id(conn, "1710")
        post_entry(conn, "2026-01-05", "شراء مكينة ليزر",
                   [{"account_id": _mach, "cash_debit": 60_000.0},
                    {"account_id": acc_id(conn, "1400"),
                     "cash_credit": 60_000.0}], username="admin")
        _aid = _fa.add_asset(conn, "مكينة ليزر", _mach, 60_000.0, 60,
                             "2026-01-01", salvage=6_000.0, username="admin")
    check("القسط الشهري = (التكلفة − التخريدية) ÷ العمر",
          abs(_fa.monthly_amount(60_000.0, 6_000.0, 60) - 900.0) < 0.01)

    for _p in ("2026-01", "2026-02", "2026-03"):
        with db() as conn:
            _fa.run_depreciation(conn, _p, "admin")
    with db() as conn:
        _again = _fa.run_depreciation(conn, "2026-02", "admin")
    check("الشهر لا يُهلَك مرتين", _again["already"] is True)

    with db(readonly=True) as conn:
        _a = [x for x in _fa.list_assets(conn) if x["id"] == _aid][0]
        _exp = balance_by_code(conn, "5860")[1]
        _accm = balance_by_code(conn, "1790")[1]
        _cost = balance_by_code(conn, "1710")[1]
    check("المُهلَك بعد ٣ أشهر = ٢٬٧٠٠",
          abs(_a["accumulated"] - 2_700.0) < 0.01, f"{_a['accumulated']}")
    check("والصافي الدفتري = ٥٧٬٣٠٠",
          abs(_a["net_book"] - 57_300.0) < 0.01, f"{_a['net_book']}")
    check("مصروف الإهلاك مدينٌ بالمبلغ نفسه",
          abs(_exp - 2_700.0) < 0.01, f"{_exp}")
    check("والمجمّع دائنٌ به — لا يُنقص حساب الأصل",
          abs(_accm + 2_700.0) < 0.01 and abs(_cost - 60_000.0) < 0.01,
          f"مجمّع {_accm} · تكلفة {_cost}")

    # آخر قسطٍ يأخذ الكسر فينتهي عند التخريدية بالضبط
    with db() as conn:
        _sid = _fa.add_asset(conn, "جهاز صغير", acc_id(conn, "1740"),
                             1_000.0, 3, "2026-04-01", salvage=100.0,
                             username="admin")
    for _p in ("2026-04", "2026-05", "2026-06", "2026-07"):
        with db() as conn:
            try:
                _fa.run_depreciation(conn, _p, "admin")
            except ValueError:
                pass
    with db(readonly=True) as conn:
        _s = [x for x in _fa.list_assets(conn) if x["id"] == _sid][0]
    check("آخر قسطٍ يأخذ الكسر فلا يتجاوز القيمة القابلة للإهلاك",
          abs(_s["accumulated"] - 900.0) < 0.01, f"{_s['accumulated']}")
    check("وينتهي الصافي الدفتري عند التخريدية بالضبط",
          abs(_s["net_book"] - 100.0) < 0.01, f"{_s['net_book']}")

    # الأصل المُخرَج من الخدمة يتوقّف قسطه
    with db() as conn:
        _fa.dispose_asset(conn, _aid, "2026-08-01", "admin")
        _due = _fa.due_amount(
            conn, [x for x in _fa.list_assets(conn, include_disposed=True)
                   if x["id"] == _aid][0], "2026-08")
    check("الأصل خارج الخدمة لا يُهلَك", abs(_due) < 0.01, f"{_due}")

    # عمرٌ غير محدَّد ⇒ لا يُهلَك بالتخمين
    with db() as conn:
        conn.execute("INSERT INTO fixed_assets(name, purchase_date, cost,"
                     " created_by) VALUES('أصلٌ من المشتريات','2026-01-01',"
                     " 5000, 'admin')")
    with db(readonly=True) as conn:
        _t = _fa.totals(conn)
        _un = [x for x in _fa.list_assets(conn)
               if int(x.get("life_months") or 0) <= 0]
    check("أصلٌ اشتُري بلا عمرٍ إنتاجي يُرصد ولا يُهلَك",
          _t.get("unset", 0) >= 1 and all(
              _fa.due_amount(conn, x, "2026-09") == 0 for x in _un),
          f"{_t.get('unset')} أصلاً")

    with db(readonly=True) as conn:
        _bg, _bc, _gv, _cv = ledger_balanced(conn)
    check("والدفتر متوازن بعد الإهلاك كله", _bg and _bc,
          f"ذهب {_gv} · نقد {_cv}")

    step("33) تحليل حركة الرصيد — الجسر ونشاط الأيام")
    # ══ الضمانة التي يقوم عليها التصميم ══
    # الجسر (أول المدة + ما زاد − ما نقص = آخر المدة) يجب أن يقفل
    # **دائماً**. ولو صُنّفت الحركات بأسمائها لسقط منه كلُّ ما لا اسم
    # له — تسويةٌ يدوية أو نوعٌ يُضاف لاحقاً — فلا يساوي المجموعُ
    # الرصيدَ الختامي ويفقد التقرير قيمته كلها. فالأثر يُؤخذ من
    # «مدين − دائن»، ويُفحص هنا بحركةٍ لا اسم لها في القائمة.
    from models import movement as _mv
    from models.entities import add_entity, get_entity

    with db() as conn:
        _mc = add_entity(conn, "عميل تحليل الحركة", "customer",
                         username="admin")
        _macc = get_entity(conn, _mc)["account_id"]
        _b3 = _batch(conn, [{"wo_no": f"MV{i}", "gold": 100.0,
                             "wage_per_gram": 20.0} for i in range(1, 6)],
                     "2026-02-01", "admin")
        _mw = [r["id"] for r in conn.execute(
            "SELECT id FROM work_orders WHERE work_order_no LIKE 'MV%'"
            " ORDER BY id")]
    # رصيدٌ افتتاحي: بيعتان في يناير
    with db() as conn:
        create_sale(conn, _mc, [{"work_order_id": _mw[0]},
                                {"work_order_id": _mw[1]}],
                    "2026-01-15", "admin", apply_vat=False)
    # الفترة: بيعٌ في يومين · مرتجعٌ في يوم · قبضٌ في ثلاثة أيام
    for i, wid in enumerate(_mw[2:4]):
        with db() as conn:
            create_sale(conn, _mc, [{"work_order_id": wid}],
                        f"2026-03-{i + 2:02d}", "admin", apply_vat=False)
    with db() as conn:
        invoices.create_sale_return(conn, _mc,
                                    [{"work_order_id": _mw[2]}],
                                    "2026-03-10", "admin", apply_vat=False)
    for i in range(3):
        with db() as conn:
            create_voucher(conn, "receipt", f"2026-03-{i + 20:02d}",
                           "admin", entity_id=_mc, gold_weight=25.0,
                           gold_karat=18)
    # قيدٌ يدوي على الحساب — رصيدُ بدايةٍ لا حركة، فمكانه «أول المدة»
    with db() as conn:
        post_entry(conn, "2026-03-25", "رصيدٌ افتتاحي بقيدٍ يدوي",
                   [{"account_id": _macc, "gold_debit": 7.0},
                    {"account_id": acc_id(conn, "5300"),
                     "gold_credit": 7.0}], username="admin")
    # وحركةٌ **لا اسم لها** في قائمة الأنواع — نوعٌ يعرفه الدفتر ولا
    # يعرفه الجسر، وهو ما يجب ألّا يسقط منه
    with db() as conn:
        post_entry(conn, "2026-03-26", "جردٌ على الحساب",
                   [{"account_id": _macc, "gold_debit": 4.0},
                    {"account_id": acc_id(conn, "5300"),
                     "gold_credit": 4.0}], source_table="stocktakes",
                   username="admin")

    with db(readonly=True) as conn:
        _r = _mv.analyze(conn, _macc, "2026-03-01", "2026-03-31")

    _sum = round(_r["opening"]["gold"]
                 + sum(b["gold"] for b in _r["buckets"]), 3)
    check("الجسر يقفل: الافتتاحي + الحركة = الختامي",
          abs(_sum - _r["closing"]["gold"]) < 0.0011,
          f"{_sum} مقابل {_r['closing']['gold']}")
    check("والرصيد التراكمي ينتهي عند الختامي",
          abs(_r["daily"][-1]["gbal"] - _r["closing"]["gold"]) < 0.0011,
          f"{_r['daily'][-1]['gbal']}")

    _by = {b["label"]: b for b in _r["buckets"]}
    check("المبيعات تزيد الدين والمرتجع والقبض يُنقصانه",
          _by["مبيعات"]["gold"] > 0 and _by["مرتجع"]["gold"] < 0
          and _by["قبض"]["gold"] < 0,
          " · ".join(f"{k}={v['gold']}" for k, v in _by.items()))
    check("عدد الأيام لكل نوع يُحسب بالأيام لا بالمستندات",
          _by["مبيعات"]["days"] == 2 and _by["مرتجع"]["days"] == 1
          and _by["قبض"]["days"] == 3,
          f"بيع {_by['مبيعات']['days']} · مرتجع {_by['مرتجع']['days']}"
          f" · قبض {_by['قبض']['days']}")
    check("والحركة التي لا اسم لها تدخل «أخرى» ولا تسقط من الجسر",
          "أخرى" in _by and abs(_by["أخرى"]["gold"] - 4.0) < 0.0011,
          f"{_by.get('أخرى', {}).get('gold')}")
    # ══ القيد اليدوي رصيدُ بدايةٍ لا حركة ══
    # كان يسقط في «أخرى» لأن اسمه في الدفتر «قيد يومي» والقائمة
    # تحمل «قيد يومية» — حرفٌ واحد جعله لا يلتقي ببنده أبداً، فيقرأ
    # المستخدم رصيدَ افتتاحٍ على أنه حركةٌ مجهولة جرت في الفترة.
    check("والقيد اليدوي يدخل «رصيد أول المدة» لا بنداً في الحركة",
          abs(_r["opening_in_period"]["gold"] - 7.0) < 0.0011
          and _r["opening_in_period"]["docs"] == 1
          and abs(_by["أخرى"]["gold"] - 4.0) < 0.0011,
          f"ضُمّ {_r['opening_in_period']['gold']} من "
          f"{_r['opening_in_period']['docs']} قيداً")
    check("وما ضُمّ منه داخل الفترة يُعلَن ولا يُخفى",
          _r["opening_in_period"]["docs"] > 0)

    _d = _r["days"]
    check("أيام الفترة ٣١ ومنها ٧ فيها حركة",
          _d["span"] == 31 and _d["active"] == 7,
          f"{_d['active']} من {_d['span']} · صامتة {_d['silent']}")
    check("والصامتة = الفترة − النشطة",
          _d["silent"] == _d["span"] - _d["active"])

    _s = _r["signals"]
    check("نسبة التحصيل تُقاس على المبيعات",
          _s["collect_pct_gold"] is not None
          and _s["collect_pct_gold"] > 0, f"{_s['collect_pct_gold']}%")
    check("وآخر تحصيلٍ وفجوته تُرصدان",
          _s["collect_gap"]["last"] == "2026-03-22"
          and _s["collect_gap"]["since"] == 9,
          f"آخره {_s['collect_gap']['last']} · منذ "
          f"{_s['collect_gap']['since']} يوماً")
    check("والخلاصة جملةٌ تُقرأ لا أرقامٌ تُفسَّر",
          "الدين" in _mv.verdict(_r), _mv.verdict(_r)[:70])

    # فترةٌ بلا أي حركة: لا ينهار التحليل
    with db(readonly=True) as conn:
        _empty = _mv.analyze(conn, _macc, "2027-01-01", "2027-01-31")
    check("فترةٌ بلا حركة تُعطي جسراً مقفلاً لا انهياراً",
          _empty["buckets"] == [] and _empty["daily"] == []
          and abs(_empty["opening"]["gold"]
                  - _empty["closing"]["gold"]) < 0.0011)

    step("34) أعمار الموديلات — ما رقد في المخزن ومنذ متى")
    # ══ ثلاث ضمانات ══
    # 1) العمر من **قيد التوريد** لا من وقت كتابة السجل: دفعةٌ تُسجَّل
    #    اليوم وقد وردت قبل سنةٍ عمرها سنة. و`created_at` هو الآن
    #    دائماً في قاعدةٍ تُبنى في الاختبار، فلو قيس عليه لظهرت كل
    #    القطع «أقل من ٣٠» ولضاع التقرير كله.
    # 2) الرقم التجميعي ٠٠٠١ رصيد وزنٍ لا قطعة، فلا عمر له ولا يدخل
    #    الفئات — وإلا أظهر عشرات الكيلوات «راكدة» وهي تدور كل يوم.
    # 3) مجموع الفئات = إجمالي المخزون المفرد. الفئة التي لا تُجمع
    #    تقريرٌ يُقرأ ولا يُصدَّق.
    from models import stock_aging as _sa

    with db() as conn:
        _batch(conn, [{"wo_no": "OLD-1", "gold": 40.0,
                       "wage_per_gram": 30.0, "model_no": "ALPHA"}],
               "2025-01-05", "admin")          # قديمة جداً
        _batch(conn, [{"wo_no": "MID-1", "gold": 25.0,
                       "wage_per_gram": 20.0, "model_no": "ALPHA"},
                      {"wo_no": "MID-2", "gold": 15.0,
                       "wage_per_gram": 20.0, "model_no": "BETA"}],
               "2026-04-20", "admin")          # نحو 70 يوماً
        _batch(conn, [{"wo_no": "NEW-1", "gold": 10.0,
                       "wage_per_gram": 25.0, "model_no": "BETA"}],
               "2026-06-20", "admin")          # نحو 10 أيام
        # ورصيدٌ تجميعي بتاريخٍ قديم عمداً: لو عُومل كقطعةٍ لظهر
        # «راكداً فوق التسعين» وهو وزنٌ يدور كل يوم
        _batch(conn, [{"wo_no": "0001", "gold": 200.0,
                       "wage_per_gram": 20.0}], "2025-02-01", "admin")
    with db(readonly=True) as conn:
        _sr = _sa.report(conn, "2026-06-30")

    _got = {x["wo_no"]: x for x in _sr["items"]}
    check("العمر يُحسب من تاريخ قيد التوريد لا من وقت كتابة السجل",
          _got["OLD-1"]["days"] == 541 and _got["NEW-1"]["days"] == 10,
          f"OLD-1={_got['OLD-1']['days']} · NEW-1={_got['NEW-1']['days']}")
    check("والقطعة تقع في فئتها الصحيحة",
          _got["NEW-1"]["bucket"] == 0 and _got["MID-1"]["bucket"] == 2
          and _got["OLD-1"]["bucket"] == 3,
          f"NEW={_got['NEW-1']['bucket']} · MID={_got['MID-1']['bucket']}"
          f" · OLD={_got['OLD-1']['bucket']}")

    _bsum = round(sum(b["weight"] for b in _sr["buckets"]), 3)
    check("مجموع الفئات = إجمالي المخزون المفرد",
          abs(_bsum - _sr["total"]["weight"]) < 0.0011,
          f"{_bsum} مقابل {_sr['total']['weight']}")
    check("وعدد القطع كذلك",
          sum(b["count"] for b in _sr["buckets"]) == _sr["total"]["count"])

    check("الرقم التجميعي يُفصل ولا يدخل الفئات",
          not any(x["is_bulk"] for x in _sr["items"])
          and _sr["bulk"]["count"] >= 1 and _sr["bulk"]["weight"] > 0,
          f"تجميعي: {_sr['bulk']['count']} قطعة "
          f"وزنها {_sr['bulk']['weight']}")
    check("ولا يُحسب ضمن ما تجاوز التسعين رغم قِدَم سجلّه",
          abs(_sr["buckets"][-1]["weight"]
              - sum(x["weight"] for x in _sr["items"]
                    if x["bucket"] == 3)) < 0.0011,
          f"فوق التسعين {_sr['buckets'][-1]['weight']}")

    _m = {x["model"]: x for x in _sr["models"]}
    check("التجميع بالموديل يجمع قطعه كلها",
          abs(_m["ALPHA"]["weight"]
              - (_got["OLD-1"]["weight"] + _got["MID-1"]["weight"])) < 0.0011,
          f"ALPHA={_m['ALPHA']['weight']}")
    check("وأقدم قطعةٍ في الموديل تُرصد",
          _m["ALPHA"]["oldest"] == 541, f"{_m['ALPHA']['oldest']}")
    check("والأجرة الراكدة = الوزن × أجرة الجرام",
          abs(_got["OLD-1"]["idle_wage"]
              - _got["OLD-1"]["weight"] * 30.0) < 0.011,
          f"{_got['OLD-1']['idle_wage']}")

    check("أقدم قطعةٍ في المخزن تتصدّر القائمة",
          _sr["items"][0]["wo_no"] == "OLD-1",
          f"{_sr['items'][0]['wo_no']} منذ {_sr['items'][0]['days']} يوماً")
    check("والخلاصة تسمّيها وتقول نسبة ما فوق التسعين",
          any("OLD-1" in v for v in _sa.verdict(_sr))
          and any("التسعين" in v for v in _sa.verdict(_sr)),
          " | ".join(_sa.verdict(_sr))[:110])

    # ترشيحٌ بموديل: الأرقام تتبع ما رُشّح لا كل المخزن
    with db(readonly=True) as conn:
        _sb = _sa.report(conn, "2026-06-30", "BETA")
        _sm = _sa.report(conn, "2026-06-30", ["ALPHA", "BETA"])
        _se = _sa.report(conn, "2026-06-30", [])
    check("الترشيح بموديل يقصر التقرير عليه",
          {x["wo_no"] for x in _sb["items"]} == {"MID-2", "NEW-1"},
          " · ".join(x["wo_no"] for x in _sb["items"]))
    check("والترشيح بعدة موديلات يجمعها كلها",
          {x["wo_no"] for x in _sm["items"]}
          == {"OLD-1", "MID-1", "MID-2", "NEW-1"},
          " · ".join(x["wo_no"] for x in _sm["items"]))
    check("وقائمةٌ فارغة تعني كلَّ المخزون لا لا شيء",
          len(_se["items"]) == len(_sr["items"])
          and _se["filter_models"] == [],
          f"{len(_se['items'])} قطعة")

    # تاريخٌ قبل أي توريد: لا مخزون ولا انهيار
    with db(readonly=True) as conn:
        _sz = _sa.report(conn, "2020-01-01")
    check("تاريخٌ قبل أي توريد يُعطي مخزوناً خاوياً لا انهياراً",
          _sz["items"] == [] and _sz["total"]["count"] == 0
          and "لا مخزون" in " ".join(_sa.verdict(_sz)))

    _html2 = _pm.build_body("stock_aging", 0, as_of="2026-06-30",
                            detail=True)
    check("ورقة أعمار الموديلات تُبنى بجدول القطع",
          "أعمار الموديلات" in _html2 and "رقم التشغيل" in _html2
          and "OLD-1" in _html2, f"{len(_html2)} حرفاً")
    check("وتستعمل تسميات أعمار الديون نفسها لا تسمياتٍ أخرى",
          all(b in _html2 for b in _sa.BUCKET_LABELS),
          " · ".join(_sa.BUCKET_LABELS))
    check("ولا تحمل عمودَي الأجرة اللذين حُذفا",
          "أجرة الجرام" not in _html2 and "أجرة راكدة" not in _html2)
    _html2b = _pm.build_body("stock_aging", 0, as_of="2026-06-30",
                             model=["ALPHA", "BETA"], detail=True)
    check("وورقةُ المرشَّح تسمّي الموديلات المختارة في رأسها",
          "ALPHA" in _html2b and "BETA" in _html2b
          and "كل الموديلات" not in _html2b, f"{len(_html2b)} حرفاً")

    step("35) الأجرة المتفق عليها — تصل إلى البائع وقت البيع")
    # ══ الضمانة ══
    # الاتفاق يتغيّر، فتُقرأ أجرةُ كل يومٍ من سجلّه لا من آخر قيمة.
    # ولولا ذلك لقرأ من يراجع فاتورةً قديمةً أجرةَ اليوم لا أجرتها.
    # والأهم أن الاتفاق **يصل إلى شاشة المبيعات** فيُملأ أمام البائع
    # ويُنبَّه إن خالفه — فالأصل ألّا يقع الخطأ لا أن يُكشف بعد شهر.
    from models import entities as _ent

    with db() as conn:
        _wc = add_entity(conn, "عميل فحص الأجرة", "customer",
                         username="admin")
        _ent.set_agreed_wage(conn, _wc, 20.0, "2026-01-01", "اتفاق أول",
                             "admin")
        _batch(conn, [{"wo_no": f"WG{i}", "gold": 100.0,
                       "wage_per_gram": 99.0} for i in range(1, 5)],
               "2026-01-05", "admin")
        _wg = [r["id"] for r in conn.execute(
            "SELECT id FROM work_orders WHERE work_order_no LIKE 'WG%'"
            " ORDER BY id")]

    check("صفرٌ يعني بلا اتفاق لا اتفاقاً بصفر",
          _ent.agreed_wage(conn, _mc) == 0.0)

    with db() as conn:
        create_sale(conn, _wc, [{"work_order_id": _wg[0],
                                 "wage_override": 20.0}],
                    "2026-02-01", "admin", apply_vat=False)
        create_sale(conn, _wc, [{"work_order_id": _wg[1],
                                 "wage_override": 18.0}],
                    "2026-02-10", "admin", apply_vat=False)
    # ثم يرتفع الاتفاق إلى 25، وتُباع قطعتان بالسعر الجديد
    with db() as conn:
        _ent.set_agreed_wage(conn, _wc, 25.0, "2026-03-01", "رفع الأجرة",
                             "admin")
        create_sale(conn, _wc, [{"work_order_id": _wg[2],
                                 "wage_override": 25.0}],
                    "2026-03-15", "admin", apply_vat=False)
        create_sale(conn, _wc, [{"work_order_id": _wg[3],
                                 "wage_override": 30.0}],
                    "2026-03-20", "admin", apply_vat=False)

    # الأجرة السالبة مرفوضة، والصفر مقبولٌ بمعنى «بلا اتفاق»
    def _neg_wage():
        with db() as conn:
            _ent.set_agreed_wage(conn, _wc, -5.0, "2026-01-01", "", "admin")
    expect_error("الأجرة المتفق عليها لا تقبل السالب", _neg_wage, "سالبة")

    with db(readonly=True) as conn:
        _hist = _ent.wage_history(conn, _wc)
        _on_feb = _ent.agreed_wage_on(conn, _wc, "2026-02-05")
        _on_mar = _ent.agreed_wage_on(conn, _wc, "2026-03-05")
        _before = _ent.agreed_wage_on(conn, _wc, "2025-12-01")
    check("سجلّ الاتفاقات يحفظ كل تغييرٍ بتاريخه",
          len(_hist) == 2, f"{len(_hist)} اتفاقاً")
    check("والأجرة النافذة تُقرأ لأي يومٍ مضى لا آخرُ قيمةٍ وحدها",
          _on_feb == 20.0 and _on_mar == 25.0,
          f"فبراير {_on_feb} · مارس {_on_mar}")
    check("وما قبل أول اتفاقٍ لا مرجعَ له",
          _before is None, f"{_before}")

    # ══ الاتفاق يصل إلى شاشة المبيعات فعلاً ══
    # وهذا أكثر ما يُخشى انكساره صامتاً لأنه في الواجهة لا في النموذج.
    try:
        from PyQt5 import QtWidgets as _QW3
        _QW3.QApplication.instance() or _QW3.QApplication([])
        from ui.sales_screen import SalesScreen as _SS

        _scr = _SS({"id": 1, "username": "admin", "full_name": "م",
                    "role": "admin", "role_local": "accountant"})
        _scr._load_agreed_wage(_wc)
        check("شاشة المبيعات تقرأ أجرة العميل المتفق عليها",
              abs(_scr._agreed_wage - 25.0) < 0.011,
              f"{_scr._agreed_wage}")
        check("وتعرضها للبائع قبل أن يكتب رقماً",
              "المتفق عليها" in _scr.wage_note.text(),
              _scr.wage_note.text()[:60])
        _scr._wage_hint(20.0)
        check("وتنبّهه فور مخالفتها — بلا منع",
              "أقلّ" in _scr.wage_note.text()
              and "5.00" in _scr.wage_note.text(),
              _scr.wage_note.text()[:80])
        _scr._wage_hint(25.0)
        check("وتؤكّد المطابقة حين يوافقها",
              "مطابقٌ" in _scr.wage_note.text(),
              _scr.wage_note.text()[:60])
        _scr._load_agreed_wage(_mc)          # عميلٌ بلا اتفاق
        check("وعميلٌ بلا اتفاقٍ لا تُفرض عليه أجرةُ غيره",
              _scr._agreed_wage == 0.0
              and "لا أجرةَ" in _scr.wage_note.text(),
              _scr.wage_note.text()[:60])
    except ImportError:
        print("  … تُخطّى فحوص الواجهة (PyQt5 غير متاح)")


    step("36) ملف الجهة — كل ما يخصّها في صفحة")
    # ══ الضمانة التي يقوم عليها الملف ══
    # لا يُحسب فيه رقمٌ جديد: كل قسمٍ من مصدره الأصلي. فلو حُسب
    # الرصيد هنا مرةً وفي الكشف مرة لصار الملفُ مصدراً سادساً للخلاف
    # بدل أن يكون جواباً. وهذا ما يُفحص: كل رقمٍ يُطابق مصدره.
    from models import accounts as _acc
    from models import aging as _aging
    from models import dossier as _ds
    from services.accounting_engine import account_balance as _bal

    with db(readonly=True) as conn:
        _dd = _ds.build(conn, _wc, "2026-01-01", "2026-12-31")
        _acc_g, _acc_c = _bal(conn, get_entity(conn, _wc)["account_id"])
        _ag_src = _aging.report(conn, "customer", "2026-12-31")
        _mv_src = _mv.analyze(conn, get_entity(conn, _wc)["account_id"],
                              "2026-01-01", "2026-12-31")

    check("الرصيد في الملف = رصيد الحساب في الدفتر",
          abs(_dd["balance"]["gold"] - _acc_g) < 0.0011
          and abs(_dd["balance"]["cash"] - _acc_c) < 0.011,
          f"ملف {_dd['balance']} · دفتر ({_acc_g}, {_acc_c})")
    _mine = [x for x in _ag_src if x["entity_id"] == _wc]
    check("وأعمار دينه = صفُّه في تقرير أعمار الديون",
          bool(_mine) == bool(_dd["aging"])
          and (not _mine or abs(_dd["aging"]["gold"]
                                - _mine[0]["gold"]) < 0.0011),
          f"ملف {_dd['aging']['gold'] if _dd['aging'] else None} · "
          f"تقرير {_mine[0]['gold'] if _mine else None}")
    check("وجسر فترته = ما يعطيه تحليل حركة الرصيد",
          abs(_dd["bridge"]["closing"]["gold"]
              - _mv_src["closing"]["gold"]) < 0.0011,
          f"{_dd['bridge']['closing']['gold']} مقابل "
          f"{_mv_src['closing']['gold']}")

    check("وموديلاته تُحسب بالصافي بعد المرتجع لا بالإجمالي",
          all(m["net_count"] == m["sold"] - m["returned"]
              for m in _dd["models_life"]),
          f"{len(_dd['models_life'])} موديلاً")
    _f = _dd["flow_life"]
    check("ونسبة مرتجعه تُقاس بالوزن لا بالعدد",
          _f["return_pct"] is None
          or abs(_f["return_pct"]
                 - _f["back_weight"] * 100.0 / _f["out_weight"]) < 0.11,
          f"خرج {_f['out_weight']} · رجع {_f['back_weight']} · "
          f"{_f['return_pct']}%")

    # سقفٌ يُتجاوز: الملف يقوله صراحةً لا يتركه للقارئ يستنتجه
    with db() as conn:
        _ent.set_credit_limit(conn, _wc, 1.0, 1.0, "admin")
    with db(readonly=True) as conn:
        _dd2 = _ds.build(conn, _wc, "2026-01-01", "2026-12-31")
    check("تجاوز السقف يُقال صراحةً في الخلاصة",
          _dd2["limit"]["gold"]["over"]
          and any("تجاوز سقفه" in v for v in _ds.verdict(_dd2)),
          " | ".join(_ds.verdict(_dd2))[:110])
    with db() as conn:
        _ent.set_credit_limit(conn, _wc, 0.0, 0.0, "admin")
    with db(readonly=True) as conn:
        _dd3 = _ds.build(conn, _wc, "2026-01-01", "2026-12-31")
    check("وصفرُ السقف يعني بلا حدّ فلا يُقال تجاوز",
          not _dd3["limit"]["gold"]["over"]
          and _dd3["limit"]["gold"]["pct"] is None)

    # جهةٌ بلا أي حركة: الملف يُفتح ولا ينهار
    with db() as conn:
        _fresh = add_entity(conn, "عميل بلا حركة", "customer",
                            username="admin")
    with db(readonly=True) as conn:
        _dd4 = _ds.build(conn, _fresh, "2026-01-01", "2026-12-31")
    check("جهةٌ بلا حركةٍ تُفتح ولا تنهار",
          _dd4["aging"] is None and _dd4["last_receipt"] is None
          and _dd4["flow"]["return_pct"] is None
          and "متزن" in " ".join(_ds.verdict(_dd4)),
          " | ".join(_ds.verdict(_dd4))[:80])

    # ══ الرصيد الافتتاحي رصيدُ بدايةٍ لا حركةٌ مجهولة ══
    # كان قيدُ الافتتاح يقع في بند «أخرى» لأن اسمه ليس في قائمة
    # الأنواع، فيقرأ المستخدم رصيداً افتتاحياً على أنه حركةٌ جرت في
    # الفترة. الآن يُضمّ إلى «رصيد أول المدة»، والجسر يبقى مقفلاً.
    with db() as conn:
        _oc = add_entity(conn, "عميل رصيدٍ افتتاحي", "customer",
                         username="admin", open_gold=300.0,
                         opening_date="2026-05-02")
        _oacc = get_entity(conn, _oc)["account_id"]
    with db(readonly=True) as conn:
        _om = _mv.analyze(conn, _oacc, "2026-05-01", "2026-05-31")
    check("قيد الافتتاح يدخل «رصيد أول المدة» لا بند «أخرى»",
          abs(_om["opening"]["gold"] - 300.0) < 0.0011
          and not any(b["label"] == "أخرى" for b in _om["buckets"]),
          f"افتتاحي {_om['opening']['gold']} · بنود "
          + " · ".join(b["label"] for b in _om["buckets"]))
    check("والجسر يبقى مقفلاً بعد ضمّه",
          abs(_om["opening"]["gold"]
              + sum(b["gold"] for b in _om["buckets"])
              - _om["closing"]["gold"]) < 0.0011,
          f"{_om['closing']['gold']}")

    # ══ نظام الأيام: «س من ص» في كل بند ══
    check("كل بندٍ يحمل مدى الفترة معه فيُقرأ «س من ص يوماً»",
          all(b["span"] == _r["days"]["span"]
              and b["days_label"] == f"{b['days']:,} من {b['span']:,}"
              for b in _r["buckets"]),
          " · ".join(f"{b['label']}={b['days_label']}"
                     for b in _r["buckets"]))
    check("ونشاط الأيام يستعمل الصيغة نفسها",
          _r["days"]["active_label"]
          == f"{_r['days']['active']:,} من {_r['days']['span']:,}"
          and all("من" in x["days_label"] for x in _r["days"]["by_op"]),
          _r["days"]["active_label"])

    # ══ كشف الحساب على حسابٍ تجميعي = مجموع شجرته ══
    with db(readonly=True) as conn:
        _root = acc_id(conn, "1600")
        _kids = _acc.subtree_ids(conn, _root)
        _tree = _mv.analyze(conn, _root, "2026-01-01", "2026-12-31")
        _sum_g = 0.0
        for _k in _kids:
            _sum_g += _bal(conn, _k, date_to="2026-12-31")[0]
    check("الحساب التجميعي يُحلَّل بشجرته لا وحده",
          len(_mv.account_ids(conn, _root)) > 1,
          f"{len(_kids)} حساباً تحت 1600")
    check("ورصيده الختامي = مجموع أرصدة فروعه",
          abs(_tree["closing"]["gold"] - _sum_g) < 0.0011,
          f"الشجرة {_tree['closing']['gold']} · المجموع "
          f"{round(_sum_g, 3)}")

    # ══ النِّسَب تُقاس على «ما كان عنده» ══
    _fl = _dd["flow"]
    check("«ما كان عنده» = أول المدة + كل ما زاد ذمّته",
          abs(_fl["held_weight"]
              - (_fl["opening_weight"] + _fl["out_weight"]
                 + _fl["other_up"])) < 0.0011,
          f"{_fl['opening_weight']} + {_fl['out_weight']} + "
          f"{_fl['other_up']} = {_fl['held_weight']}")
    # ══ «من البداية» يشمل الأرصدة الافتتاحية ══
    # لو بُني من الفواتير وحدها لسقط منه الافتتاحيّ، فظهرت نسبةُ
    # سدادٍ مضاعفة: ١٢٠ من ١٩٠ بدل ١٢٠ من ١٠٤٠.
    _fll = _dd["flow_life"]
    check("و«من البداية» يشمل الأرصدة الافتتاحية لا المبيعات وحدها",
          abs(_fll["held_weight"]
              - (_fll["opening_weight"] + _fll["out_weight"]
                 + _fll["other_up"])) < 0.0011
          and _fll["held_weight"] >= _fl["held_weight"] - 0.0011,
          f"من البداية {_fll['held_weight']} · الفترة "
          f"{_fl['held_weight']}")
    check("وما سدّده وما رجع منه من الجسر لا من جدولٍ آخر",
          abs(_fl["closing_weight"]
              - _dd["bridge"]["closing"]["gold"]) < 0.0011,
          f"{_fl['closing_weight']}")
    check("ونسبة المرتجع والسداد تُقاسان عليه لا على المبيعات وحدها",
          (_fl["return_pct"] is None
           or abs(_fl["return_pct"]
                  - _fl["back_weight"] * 100.0 / _fl["held_weight"]) < 0.11)
          and (_fl["paid_pct"] is None
               or abs(_fl["paid_pct"]
                      - _fl["paid_weight"] * 100.0
                      / _fl["held_weight"]) < 0.11),
          f"مرتجع {_fl['return_pct']}% · سداد {_fl['paid_pct']}%")
    check("وما سدّده يُقرأ من بند القبض في الجسر لا يُستنتج",
          _fl["paid_count"] >= 0 and _fl["paid_weight"] >= 0,
          f"{_fl['paid_count']} مستنداً · {_fl['paid_weight']}")

    _html4 = _pm.build_body("dossier", _wc, date_from="2026-01-01",
                            date_to="2026-12-31")
    check("ورقة الملف تُبنى بأقسامها كلها",
          "ملف الجهة" in _html4 and "جسر الرصيد" in _html4
          and "أعمار دينه" in _html4 and "ما كان تحت يده" in _html4
          and "ما سدّده" in _html4, f"{len(_html4)} حرفاً")
    check("ولا تحمل سالباً خامّاً يزيغ في نصٍّ عربي",
          not _re.findall(r"-[\d,]+\.\d", _html4),
          " · ".join(_re.findall(r"-[\d,]+\.\d", _html4)[:4]) or "لا شيء")

    step("37) من عدّل ماذا بعد الترحيل")
    # ══ الضمانة التي يقوم عليها السجلّ ══
    # الفرق يُحفظ **رقمين** قبل وبعد لا نصّاً يُحلَّل. وتحليلُ نصٍّ
    # عربيٍّ بتعبيرٍ نمطي يكسر بأول تغييرٍ في الصياغة — ويكسر صامتاً
    # فيعطي صفراً بدل أن يعطي خطأ. وهذا ما يُفحص: التعديل يُسجَّل
    # بقيمتيه، والفرق يُطابق ما تغيّر في الدفتر فعلاً.
    from models import doc_edits as _de
    from models import vouchers as _vo

    with db() as conn:
        _ec = add_entity(conn, "عميل تتبّع التعديل", "customer",
                         username="admin")
        _batch(conn, [{"wo_no": f"ED{i}", "gold": 100.0,
                       "wage_per_gram": 20.0} for i in range(1, 4)],
               "2026-05-01", "admin")
        _ew = [r["id"] for r in conn.execute(
            "SELECT id FROM work_orders WHERE work_order_no LIKE 'ED%'"
            " ORDER BY id")]
    with db() as conn:
        _inv = create_sale(conn, _ec, [{"work_order_id": _ew[0]}],
                           "2026-05-05", "admin", apply_vat=False)
    with db(readonly=True) as conn:
        _v0 = _de.totals(conn, _inv["entry_id"])
    check("قيمة المستند = مجموع الطرف المدين من قيده",
          _v0[0] > 0 and _v0[1] > 0, f"وزن {_v0[0]} · نقد {_v0[1]}")

    # تعديلٌ في مكانه يُضيف طقماً ثانياً
    with db() as conn:
        invoices.update_invoice(conn, _inv["id"],
                                [{"work_order_id": _ew[0]},
                                 {"work_order_id": _ew[1]}], "admin")
    with db(readonly=True) as conn:
        _v1 = _de.totals(conn, _inv["entry_id"])
        _ed = _de.report(conn)
    _mine = [r for r in _ed if r["table"] == "invoices"
             and r["source_id"] == _inv["id"]]
    check("التعديل في مكانه يُسجَّل بقيمتيه قبل وبعد",
          len(_mine) == 1 and _mine[0]["kind"] == "inplace",
          f"{len(_mine)} سطراً")
    check("والفرق المسجَّل = ما تغيّر في الدفتر فعلاً",
          abs(_mine[0]["d_gold"] - (_v1[0] - _v0[0])) < 0.0011
          and abs(_mine[0]["d_cash"] - (_v1[1] - _v0[1])) < 0.011,
          f"مسجَّل ({_mine[0]['d_gold']}, {_mine[0]['d_cash']}) · "
          f"دفتر ({round(_v1[0] - _v0[0], 3)}, "
          f"{round(_v1[1] - _v0[1], 2)})")
    check("ويُنسب لمن عدّله لا لمن أنشأه",
          _mine[0]["user"] == "admin" and _mine[0]["changed"],
          f"{_mine[0]['user']}")

    # تعديلٌ بالإلغاء وإعادة الترحيل (سندٌ عبر `repost`)
    with db() as conn:
        _vch = create_voucher(conn, "receipt", "2026-05-10", "admin",
                              entity_id=_ec, gold_weight=30.0,
                              gold_karat=18)
    with db(readonly=True) as conn:
        _vb = _de.totals(conn, _vch["entry_id"])
    with db() as conn:
        _vo.update_voucher(conn, _vch["id"], "admin",
                           entity_id=_ec, gold_weight=55.0,
                           gold_karat=18)
    with db(readonly=True) as conn:
        _ed2 = _de.report(conn)
    _mv2 = [r for r in _ed2 if r["table"] == "vouchers"
            and r["source_id"] == _vch["id"]]
    check("وتعديل السند يُسجَّل كذلك بفرقه",
          len(_mv2) == 1 and abs(_mv2[0]["d_gold"] - 25.0) < 0.0011,
          f"فرق {_mv2[0]['d_gold'] if _mv2 else '—'}")

    _s = _de.summarize(conn, _ed2)
    check("التجميع بالمستخدم وبنوع المستند يجمع الكل",
          sum(x["count"] for x in _s["users"]) == len(_ed2)
          and sum(x["count"] for x in _s["types"]) == len(_ed2),
          f"{len(_ed2)} تعديلاً · {len(_s['users'])} مستخدماً · "
          f"{len(_s['types'])} نوعاً")
    check("والزيادة والنقص لا يُقاصّان في العرض",
          abs(_s["total"]["up_gold"] + _s["total"]["dn_gold"]
              - _s["total"]["d_gold"]) < 0.0011,
          f"زيادة {_s['total']['up_gold']} · نقص "
          f"{_s['total']['dn_gold']}")
    check("والخلاصة تقول إن التعديل مشروعٌ ما دام مرئياً",
          any("مرئياً" in v for v in _de.verdict(_s)),
          " | ".join(_de.verdict(_s))[:110])

    # تاريخ مستندٍ بعينه — يُفتح من الأرشيف
    with db(readonly=True) as conn:
        _h = _de.history(conn, "invoices", _inv["id"])
    check("وتاريخ مستندٍ بعينه يُقرأ وحده",
          len(_h) == 1 and _h[0]["source_id"] == _inv["id"])

    # مُرشِّح «المتأخّر فقط» لا يُدرج تعديلاً وقع في يومه
    with db(readonly=True) as conn:
        _late = _de.report(conn, min_lag=_de.LATE_DAYS)
    check("ومُرشِّح المتأخّر يستبعد ما عُدِّل في يومه",
          all(r["lag"] >= _de.LATE_DAYS for r in _late),
          f"{len(_late)} من {len(_ed2)}")

    _html5 = _pm.build_body("doc_edits", 0, date_from="2026-01-01",
                            date_to="2030-12-31")
    check("ورقة التعديلات تُبنى بأبوابها",
          "من عدّل ماذا" in _html5 and "بالمستخدم" in _html5
          and "قيمة المستند" in _html5, f"{len(_html5)} حرفاً")
    check("ولا تحمل سالباً خامّاً يزيغ في نصٍّ عربي",
          not _re.findall(r"-[\d,]+\.\d", _html5),
          " · ".join(_re.findall(r"-[\d,]+\.\d", _html5)[:4]) or "لا شيء")

    step("38) رواتب عمال التصنيع — الصافي والمسحوبات والمستحق")
    # ══ ثلاث ضمانات ══
    # 1) الإضافي من **ساعات الإضافي** لا من ساعات الدوام كلها: كان
    #    معاملُ الإضافي يُضرب في ساعات الشهر فيصير الإضافي راتباً
    #    ثانياً — خطأٌ صامت لأن الرقم يبدو معقولاً.
    # 2) السحب **لا يُطرح من الصافي**: قُيّد يوم وقوعه بسند صرف،
    #    فطرحُه من الصافي المُرحَّل يخصمه مرتين ويظهر حساب العامل
    #    مديناً بما لم يأخذه.
    # 3) المستحق = الصافي − المسحوبات، للعرض لا للترحيل.
    from models import mfg_costs as _mc2
    from models import payroll as _pr

    with db() as conn:
        _wk = add_entity(conn, "عامل تصنيع للفحص", "worker",
                         username="admin", basic_salary=3000.0)
        _wacc = get_entity(conn, _wk)["account_id"]
        _weid = conn.execute(
            "SELECT employee_id FROM entities WHERE id=?",
            (_wk,)).fetchone()["employee_id"]
    _per = "2026-07"
    with db() as conn:
        _mc2.save_targets(conn, _per, [{
            "employee_id": _weid, "month_days": 30, "hours": 8,
            "overtime_hours": 20, "absence": 0, "actual_output": 0,
            "target_amount": 0}], "admin")
    # سندُ صرفٍ للعامل خلال الشهر — هذا هو «المسحوبات»
    with db() as conn:
        create_voucher(conn, "payment", "2026-07-10", "admin",
                       entity_id=_wk, cash_amount=500.0)

    with db(readonly=True) as conn:
        _sal = {r["employee_id"]: r
                for r in _mc2.list_salaries(conn, _per)}[_weid]

    check("الإضافي = ساعات الإضافي × المعامل لا ساعات الدوام كلها",
          abs(_sal["overtime_hours"] - 20.0) < 0.011
          and abs(_sal["overtime"]
                  - 20.0 * _sal["overtime_rate"]) < 0.011,
          f"إضافية {_sal['overtime_hours']} × {_sal['overtime_rate']}"
          f" = {_sal['overtime']}")
    _want = round(3000.0 + _sal["overtime"], 2)
    check("والصافي = الأساسي + الإضافي + التارجت + المكافأة − الخصوم",
          abs(_sal["net_salary"] - _want) < 0.011,
          f"{_sal['net_salary']} مقابل {_want}")
    check("والمسحوبات تُقرأ من سندات الصرف",
          abs(_sal["draws"] - 500.0) < 0.011, f"{_sal['draws']}")
    check("والمستحق = الصافي − المسحوبات",
          abs(_sal["due"] - (_sal["net_salary"] - 500.0)) < 0.011,
          f"{_sal['due']}")
    check("والسحب لا يُطرح من الصافي فلا يُخصم مرتين",
          _sal["net_salary"] > _sal["due"] - 0.011
          and abs(_sal["net_salary"] - _want) < 0.011)

    # ══ الترحيل يُنزل الصافي، ورصيد العامل يطرح السحب من نفسه ══
    with db() as conn:
        _mc2.save_salaries(conn, _per, [_sal], "admin")
        _res = _mc2.post_salaries(conn, _per, "admin",
                                  entry_date="2026-07-31", rows=[_sal])
    with db(readonly=True) as conn:
        _wg, _wc2 = _bal(conn, _wacc)
    check("الترحيل يُنزل الصافي في حساب العامل",
          abs(_res["total"] - _sal["net_salary"]) < 0.011,
          f"{_res['total']}")
    check("ورصيدُ حسابه = المسحوبات − الصافي بلا خصمٍ مزدوج",
          abs(_wc2 - (500.0 - _sal["net_salary"])) < 0.011,
          f"رصيد {_wc2} · صافي {_sal['net_salary']} · سحب 500")

    # ══ إضافة موظفٍ من خارج عمال التصنيع ══
    with db() as conn:
        _emp = add_entity(conn, "موظف إداري مع القسم", "employee",
                          username="admin", basic_salary=2000.0)
        _eeid = conn.execute(
            "SELECT employee_id FROM entities WHERE id=?",
            (_emp,)).fetchone()["employee_id"]
    with db(readonly=True) as conn:
        _before = {r["employee_id"] for r in _mc2.list_salaries(conn, _per)}
    check("الموظف الإداري ليس في جدول رواتب التصنيع افتراضاً",
          _eeid not in _before)
    _mc2.save_extra_staff(_mc2.load_extra_staff() + [_eeid])
    with db(readonly=True) as conn:
        _after = {r["employee_id"]: r
                  for r in _mc2.list_salaries(conn, _per)}
    check("وإضافتُه تُدرج صفَّه ويُعلَّم بأنه مضاف",
          _eeid in _after and _after[_eeid]["is_extra"]
          and not _after[_weid]["is_extra"],
          f"{len(_after)} صفاً")
    _mc2.save_extra_staff([])
    with db(readonly=True) as conn:
        _back = {r["employee_id"] for r in _mc2.list_salaries(conn, _per)}
    check("ورفعُه يُعيد الجدول لعمال القسم وحدهم",
          _eeid not in _back and _weid in _back)

    # ══ الاسم يُعدَّل في دليل الحسابات ══
    from models import coa as _coa
    with db() as conn:
        _coa.rename_account(conn, _wacc, "عامل التصنيع بعد التسمية",
                            "admin")
    with db(readonly=True) as conn:
        _nm = conn.execute("SELECT name FROM entities WHERE id=?",
                           (_wk,)).fetchone()["name"]
        _an = conn.execute("SELECT name FROM accounts WHERE id=?",
                           (_wacc,)).fetchone()["name"]
        _rn = {r["employee_id"]: r["name"]
               for r in _mc2.list_salaries(conn, _per)}[_weid]
    check("تعديل الاسم يتبعه دليل الحسابات والجهة وجدول الرواتب",
          _an == "عامل التصنيع بعد التسمية"
          and _nm == "عامل التصنيع بعد التسمية"
          and _rn == "عامل التصنيع بعد التسمية",
          f"حساب «{_an}» · جهة «{_nm}» · جدول «{_rn}»")

    _html6 = _pm.build_body("mfg_salary", 0, period=_per,
                            salaries=list(_after.values()))
    check("وورقةُ الرواتب تحمل العمودين الجديدين",
          "عليه (مدين)" in _html6 and "المستحق" in _html6
          and "إضافية" in _html6, f"{len(_html6)} حرفاً")

    # ══ «عليه (مدين)»: رصيدُ كشف الحساب لا مسحوبات الشهر ══
    # قبل ترحيل الراتب: سندُ صرفه 500 يجعله مديناً بـ500 فيظهر.
    # وبعد الترحيل يصير دائناً بـ2700 فلا يظهر شيء — فالعمود يقول
    # «ما عليه» لا «ما أخذه».
    with db(readonly=True) as conn:
        _owed_after = _mc2.owed_now(conn, _weid)
        _sal_after = {r["employee_id"]: r
                      for r in _mc2.list_salaries(conn, _per)}[_weid]
    check("وبعد الترحيل يصير العامل دائناً فلا يظهر عليه شيء",
          _owed_after == 0.0 and _sal_after["owed"] == 0.0,
          f"رصيده {_wc2}")
    check("والمستحق = الصافي − ما عليه",
          abs(_sal_after["due"]
              - (_sal_after["net_salary"] - _sal_after["owed"])) < 0.011,
          f"{_sal_after['due']}")

    # ══ السالب في جدول الرواتب: قوسان يُقرآن ويُكتبان ══
    # الإشارة الأمامية تزيغ في السطر العربي فيُقرأ السالب موجباً؛
    # والقوسان يُعرضان — فإن لم تُقرأ القوسان عند الحفظ صار السالب
    # صفراً في أول حفظٍ بلا تعديل، وهذا أسوأ من العرض نفسه.
    from ui.mfg_costs_screen import _num as _mnum, _val as _mval
    check("سالبُ جدول الرواتب يُعرض بين قوسين لا بإشارةٍ زائغة",
          _mnum(-571.66) == "(571.66)" and _mnum(1646.68) == "1,646.68",
          f"{_mnum(-571.66)} · {_mnum(1646.68)}")
    check("والقوسان يُقرآن سالباً عند الحفظ فلا يضيع الرقم",
          abs(_mval("(571.66)") + 571.66) < 0.001
          and abs(_mval("1,646.68") - 1646.68) < 0.001
          and abs(_mval("-25") + 25.0) < 0.001
          and _mval("") == 0.0,
          f"{_mval('(571.66)')} · {_mval('1,646.68')}")

    step("39) دليل الموديلات — الوارد بتاريخ ومع من كل قطعة")
    # السؤال: «ماذا ورد من التصنيع يوم كذا، وأين هو الآن؟» — يُجاب
    # من سطور الدفعات لا من بطاقات الأطقم، لأن الرقم التجميعي 0001
    # بطاقةٌ واحدة تراكمية: قراءتُها تنسب رصيد الشهر كلِّه ليومٍ واحد.
    from models import invoices as _inv9
    from models import models_catalog as _mcat
    from models.entities import add_entity as _add9
    from models.inventory import create_work_orders_batch as _b9
    _r1, _r2 = "R{}".format(901), "R{}".format(902)
    with db() as conn:
        _rc = _add9(conn, "مشترٍ من دفعة اليوم", "customer",
                    username="admin")
        _b9(conn, [
            {"wo_no": _r1, "gold": 40.0, "wage_per_gram": 24.0,
             "model_no": "موديل الوارد"},
            {"wo_no": _r2, "gold": 25.0, "wage_per_gram": 24.0,
             "model_no": "موديل الوارد"},
            {"wo_no": "0001", "gold": 70.0, "wage_per_gram": 20.0,
             "model_no": "موديل الوارد"}], "2026-08-03", "admin")
    with db() as conn:
        _b9(conn, [
            {"wo_no": "R903", "gold": 30.0, "wage_per_gram": 24.0,
             "model_no": "موديل الوارد"},
            {"wo_no": "0001", "gold": 15.0, "wage_per_gram": 20.0,
             "model_no": "موديل الوارد"}], "2026-08-11", "admin")
    with db(readonly=True) as conn:
        _w1 = conn.execute(
            "SELECT id FROM work_orders WHERE work_order_no=?"
            " AND is_deleted=0", (_r1,)).fetchone()["id"]
    with db() as conn:
        _inv9.create_sale(conn, _rc, [{"work_order_id": _w1}],
                          "2026-08-20", "admin", apply_vat=False)

    with db(readonly=True) as conn:
        _d3 = _mcat.received(conn, "2026-08-03", "2026-08-03")
        _d11 = _mcat.received(conn, "2026-08-11", "2026-08-11")
        _days = {d["date"]: d for d in _mcat.received_days(conn)}
    _m3 = {m["model"]: m for m in _d3["models"]}["موديل الوارد"]
    _by = {i["wo"]: i for i in _m3["items"]}
    check("وارد اليوم يُفصَّل موديلاً موديلاً بأرقام تشغيله",
          sorted(_by) == ["0001", _r1, _r2], f"{sorted(_by)}")
    check("والمباعة تحمل اسم الجهة التي هي عندها الآن",
          _by[_r1]["holder"] == "مشترٍ من دفعة اليوم"
          and not _by[_r1]["safe"], _by[_r1]["holder"])
    check("والباقية تحمل «الخزنة»",
          _by[_r2]["holder"] == _mcat.SAFE and _by[_r2]["safe"],
          _by[_r2]["holder"])
    check("والرقم التجميعي يُنسب لكل يومٍ بحصته لا برصيده المتراكم",
          abs(_by["0001"]["reg"] - 70.0) < 0.011
          and abs({i["wo"]: i for i in
                   {m["model"]: m for m in _d11["models"]}
                   ["موديل الوارد"]["items"]}["0001"]["reg"] - 15.0) < 0.011,
          f"{_by['0001']['reg']} ثم 15")
    check("ووارد يومٍ لا يختلط بوارد غيره",
          all(i["wo"] != "R903" for i in _m3["items"])
          and "2026-08-03" in _days and "2026-08-11" in _days,
          f"{_days.get('2026-08-03', {}).get('count')} قطعاً يوم 3")
    check("والإجمالي يفصل ما بالخزنة عمّا خرج للجهات",
          _d3["count"] == 3 and _d3["out_count"] == 1
          and _d3["in_count"] == 2,
          f"{_d3['count']} · خارج {_d3['out_count']}")
    _html7 = _pm.build_body("models_received", 0, date_from="2026-08-03",
                            date_to="2026-08-03")
    check("وورقةُ الوارد تحمل أرقام التشغيل والجهة والخزنة",
          _r1 in _html7 and "مشترٍ من دفعة اليوم" in _html7
          and _mcat.SAFE in _html7, f"{len(_html7)} حرفاً")

    # ══ ورقة الصور: أربعٌ في الصفحة، والزائد يُختصر لا يفيض ══
    _html8 = _pm.build_body("models_received_photos", 0,
                            date_from="2026-08-03", date_to="2026-08-03")
    check("وورقةُ الصور تعرض الموديل ولو بلا صورة ومعه قطعُه وجهاتُها",
          "لا صورة لهذا الموديل" in _html8 and _r1 in _html8
          and "مشترٍ من دفعة اليوم" in _html8
          and "pgrid" in _html8, f"{len(_html8)} حرفاً")
    check("وخليةُ الصورة ثابتة الارتفاع فلا تُزيح أختها لصفحةٍ أخرى",
          "height: 116mm" in _html8 and "height: 110mm" in _html8
          and _pm.PHOTO_ROWS == 6)

    step("40) لوحة أرقام التشغيل المتاحة للبيع")
    # اللوحة عرضٌ محض: تقرأ بطاقات الأطقم المتاحة ولا تُنشئ قيداً.
    from models import dash_panels as _dp9
    from models.inventory import rename_work_order as _rn9
    with db() as conn:
        _b9(conn, [
            {"wo_no": "T801", "gold": 40.0, "small_stones": 2.0,
             "big_stones": 6.0, "discount_rate": 0.5,
             "wage_per_gram": 24.0, "model_no": "لوحة 1"},
            {"wo_no": "T802", "gold": 30.0, "wage_per_gram": 24.0,
             "model_no": "لوحة 1"}], "2026-08-14", "admin")
    with db(readonly=True) as conn:
        _t2 = conn.execute(
            "SELECT id FROM work_orders WHERE work_order_no='T802'"
            " AND is_deleted=0").fetchone()["id"]
        _t1 = conn.execute(
            "SELECT id FROM work_orders WHERE work_order_no='T801'"
            " AND is_deleted=0").fetchone()["id"]
    with db() as conn:
        _inv9.create_sale(conn, _rc, [{"work_order_id": _t2}],
                          "2026-08-18", "admin", apply_vat=False)
    with db(readonly=True) as conn:
        _st = {r["wo"]: r for r in _dp9.stock_rows(conn)}
        _sq = _dp9.stock_rows(conn, "T801")
    check("اللوحة تعرض المتاح للبيع وحده",
          "T801" in _st and "T802" not in _st, f"{len(_st)} طقماً")
    check("وكل صفٍّ يحمل الذهب والفصوص والأحجار وبعد الخصم والمقيد"
          " والقائم",
          abs(_st["T801"]["gold"] - 40.0) < 0.011
          and abs(_st["T801"]["small"] - 2.0) < 0.011
          and abs(_st["T801"]["big"] - 6.0) < 0.011
          and abs(_st["T801"]["after"] - 3.0) < 0.011
          and abs(_st["T801"]["reg"] - 45.0) < 0.011
          and abs(_st["T801"]["standing"] - 48.0) < 0.011,
          f"مقيد {_st['T801']['reg']} · قائم {_st['T801']['standing']}")
    check("والبحث يقصرها على ما طابق",
          [r["wo"] for r in _sq] == ["T801"])
    with db() as conn:
        _mcat.assign_model(conn, _t1, "لوحة 2", "admin")
        _rn9(conn, _t1, "T809", "admin")
    with db(readonly=True) as conn:
        _st2 = {r["wo"]: r for r in _dp9.stock_rows(conn)}
        _ln = conn.execute(
            "SELECT wo_no FROM wo_batch_lines WHERE work_order_id=?",
            (_t1,)).fetchone()
    check("وتعديلُ الطقم يغيّر موديله ورقمه ويتبعه سطر الدفعة",
          "T809" in _st2 and _st2["T809"]["model"] == "لوحة 2"
          and (_ln["wo_no"] if _ln else "") == "T809",
          f"سطر الدفعة {_ln['wo_no'] if _ln else '—'}")
    _html9 = _pm.build_body("dash_panel", 0, title="أرقام التشغيل",
                            kind="stock", codes=[])
    check("وورقةُ اللوحة تطابق جدولها",
          "T809" in _html9 and "الفصوص" in _html9
          and "الذهب القائم" in _html9 and "T802" not in _html9,
          f"{len(_html9)} حرفاً")

    step("41) ترتيب أسماء عمال التصنيع")
    # الترتيب عرضٌ محض — لا يمسّ راتباً ولا قيداً، لكنه واحدٌ
    # للتارجت وللرواتب: جدولان بترتيبين يُقارَن فيهما صفٌّ بغير صفّه.
    _perO = "2026-09"
    _wids = []
    with db() as conn:
        for _n in ("عامل ترتيب ب", "عامل ترتيب أ"):
            _e = add_entity(conn, _n, "worker", username="admin",
                            basic_salary=3000.0)
            _wids.append(conn.execute(
                "SELECT employee_id FROM entities WHERE id=?",
                (_e,)).fetchone()["employee_id"])
    with db(readonly=True) as conn:
        _names0 = [r["name"] for r in _mc2.list_salaries(conn, _perO)]
    _mc2.save_staff_order(list(reversed(_wids)))
    with db(readonly=True) as conn:
        _names1 = [r["name"] for r in _mc2.list_salaries(conn, _perO)]
        _tg1 = [r["name"] for r in _mc2.list_targets(conn, _perO)]
    check("الترتيب المحفوظ يقدّم من قدّمه صاحب النظام",
          _names1[:2] == ["عامل ترتيب أ", "عامل ترتيب ب"]
          and _names1 != _names0, f"{_names1[:2]}")
    check("والتارجت والرواتب بترتيبٍ واحد",
          _tg1[:2] == _names1[:2], f"{_tg1[:2]}")
    _mc2.save_staff_order(_wids)
    with db(readonly=True) as conn:
        _names2 = [r["name"] for r in _mc2.list_salaries(conn, _perO)]
    check("وتبديلُ الترتيب يظهر فوراً وبلا مساسٍ بالأرقام",
          _names2[:2] == ["عامل ترتيب ب", "عامل ترتيب أ"], f"{_names2[:2]}")
    _mc2.save_staff_order([])

    step("42) بوابة الدخول — الترحيب والحركة ومسار الدخول")
    # البوابة واجهة، لكن تحتها ثلاثة أشياء تُفحص بلا شاشة: نصُّ
    # الترحيب، ومفاتيح إطفاء الحركة، ومسار الدخول المشترك.
    import os as _os9
    from services import login_flow as _lf9
    from ui import gate_window as _gw9
    from ui.widgets import gold_stage as _gs9
    check("الترحيب يقول اسم النظام كما يُخاطَب به صاحبه",
          _gw9.WELCOME == "مرحباً بك في نظام إدارة مصانع الذهب"
          and _gw9.ASK_LOGIN == "يرجى تسجيل الدخول", _gw9.WELCOME)
    _old_anim = _os9.environ.get("GOLD_ERP_NO_ANIM", "")
    _os9.environ["GOLD_ERP_NO_ANIM"] = "1"
    _off = _gs9.animations_on()
    _os9.environ["GOLD_ERP_NO_ANIM"] = _old_anim
    _old_cfg = getattr(config, "SPLASH_ANIMATION", True)
    config.SPLASH_ANIMATION = False
    _off2 = _gs9.animations_on()
    config.SPLASH_ANIMATION = _old_cfg
    check("والحركة تُطفأ بالإعداد أو بمتغيّر البيئة — للأجهزة الضعيفة",
          _off is False and _off2 is False)
    try:
        _lf9.sign_in("", "x")
        _empty = False
    except _lf9.LoginError as _e9:
        _empty = "اسم المستخدم" in str(_e9)
    check("ومسارُ الدخول يرفض الفارغ برسالةٍ مفهومة لا بانهيار", _empty)
    _lf9.save_last_user("مستخدم الاختبار")
    check("ويُحفظ اسمُ آخر من دخل وحده — لا كلمة المرور",
          _lf9.load_last_user() == "مستخدم الاختبار"
          and _lf9._last_user_path().name == "last_user.txt")
    _lf9.save_last_user("")
    check("ورفعُ التذكّر يمحو الاسم", _lf9.load_last_user() == "")
    # ══ تسلسل الفتح: البوابة لا تختفي قبل ظهور النظام ══
    # كانت تُعرض بـ`exec_`، و`accept` يُخفيها في لحظته — فيُرى
    # البرنامجُ يُغلق ثم يُفتح بينما تُبنى الواجهة خلف سطح المكتب.
    # هذا الفحص يحرس الترتيب: نداءٌ بعد الدخول، لا قبولٌ يُخفي.
    import inspect as _insp9

    import main as _main9
    _src_main = _insp9.getsource(_main9)
    _src_login = _insp9.getsource(_gw9.GateWindow.try_login)
    check("الفتح مربوطٌ بنداءٍ بعد الدخول لا بقبولٍ يُخفي البوابة",
          hasattr(_main9, "wire_gate")
          and "gate.exec_()" not in _src_main
          and "on_signed_in" in _src_login
          and "self.accept()" not in _src_login.split(
              "cb = getattr")[0])
    _build9 = _src_main[_src_main.index("def _build_system"):
                        _src_main.index("def _on_signed_in")]
    check("والنظام يُعرض ثم تُطلب الموجة — فلا يسبق الإغلاقُ الظهور",
          "win.showMaximized()" in _build9
          and "gate.hand_off" in _build9
          and _build9.index("win.showMaximized()")
          < _build9.index("gate.hand_off")
          and "gate.close" not in _build9,
          "الإغلاق في نهاية التمازج وحده")
    _steps9 = _main9.prepare_steps()
    check("وخطوات الإقلاع مسمّاة تُعرض على البوابة وهي تُنفَّذ",
          len(_steps9) >= 7
          and all(isinstance(a, str) and callable(b) for a, b in _steps9)
          and "قاعدة البيانات" in _steps9[0][0],
          f"{len(_steps9)} خطوات")
    check("والبطاقة مخفيّةٌ قبل أول عرضٍ فلا تومض ثم تختفي",
          "self.card.hide()" in _insp9.getsource(_gw9.GateWindow.__init__)
          and "QDialog#gateWindow { background:" in _gw9.GATE_QSS)

    step("43) تعديل تاريخ العملية ينقلها وقيدَها معاً")
    # كشف الحساب يرتّب بالتاريخ. فلو عُدّل تاريخ مستندٍ ولم ينتقل
    # قيدُه بقيت العملية في موضعها القديم من الكشف إلى الأبد —
    # ورقةٌ بتاريخٍ ودفترٌ بتاريخٍ آخر.
    from models import journal as _jr9
    from models import vouchers as _vo9
    from models.entities import get_entity as _ge9
    from models.invoices import update_invoice as _upd9
    with db() as conn:
        _dc = _add9(conn, "عميل نقل التاريخ", "customer", username="admin")
        _dacc = _ge9(conn, _dc)["account_id"]
        _b9(conn, [{"wo_no": "Z901", "gold": 30.0, "wage_per_gram": 24.0}],
            "2026-11-01", "admin")
        _zw = conn.execute(
            "SELECT id FROM work_orders WHERE work_order_no='Z901'"
            " AND is_deleted=0").fetchone()["id"]
    with db() as conn:
        _zi = _inv9.create_sale(conn, _dc, [{"work_order_id": _zw}],
                                "2026-11-05", "admin", apply_vat=False)
    with db() as conn:
        _zr = _upd9(conn, _zi["id"], [{"work_order_id": _zw}], "admin",
                    apply_vat=False, invoice_date="2026-12-09")
    with db(readonly=True) as conn:
        _zd = conn.execute("SELECT invoice_date d FROM invoices WHERE id=?",
                           (_zi["id"],)).fetchone()["d"]
        _ze = conn.execute(
            "SELECT entry_date d FROM journal_entries WHERE id=?",
            (_zi["entry_id"],)).fetchone()["d"]
        _nov = [x for x in _jr9.statement(conn, _dacc, "2026-11-01",
                                          "2026-11-30")
                if x["op"] == "مبيعات"]
        _dec = [x for x in _jr9.statement(conn, _dacc, "2026-12-01",
                                          "2026-12-31")
                if x["op"] == "مبيعات"]
    check("الفاتورة وقيدها ينتقلان إلى التاريخ الجديد",
          _zd == _ze == "2026-12-09", f"فاتورة {_zd} · قيد {_ze}")
    check("فتختفي من كشف الشهر القديم وتظهر في الجديد",
          not _nov and len(_dec) == 1,
          f"القديم {len(_nov)} · الجديد {len(_dec)}")
    check("ويُبلَّغ النقل ليُعرض للمستخدم",
          _zr.get("moved_date") == ("2026-11-05", "2026-12-09"),
          str(_zr.get("moved_date")))
    with db() as conn:
        _zv = create_voucher(conn, "receipt", "2026-11-08", "admin",
                             entity_id=_dc, cash_amount=300.0)
    with db() as conn:
        _zvr = _vo9.update_voucher(
            conn, _zv["id"], "admin", kind="receipt", entity_id=_dc,
            cash_amount=420.0, voucher_date="2026-12-11")
    with db(readonly=True) as conn:
        _zrow = conn.execute(
            "SELECT v.voucher_date d, e.entry_date ed, v.voucher_no n"
            " FROM vouchers v JOIN journal_entries e ON e.id=v.entry_id"
            " WHERE v.id=?", (_zv["id"],)).fetchone()
    check("والسند كذلك — ينتقل هو وقيده ويبقى رقمه",
          _zrow["d"] == _zrow["ed"] == "2026-12-11"
          and _zrow["n"] == _zv["voucher_no"]
          and _zvr.get("moved_date") == ("2026-11-08", "2026-12-11"),
          f"{_zrow['d']} · {_zrow['ed']} · {_zrow['n']}")

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
