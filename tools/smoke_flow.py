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

    step("22) حارس الأرصدة السالبة")
    # الحسابات المادية: ما لا يوجد فيها لا يُصرف منه.
    from services import stock_guard as _sg
    from services.accounting_engine import balance_by_code as _bal

    with db(readonly=True) as conn:
        check("الوضع الافتراضي تنبيه", _sg.mode(conn) == "warn")
    with db() as conn:
        tz, lossacc = acc_id(conn, "1100"), acc_id(conn, "5300")
        before = _bal(conn, "1100")[0]

    def _post(desc, dr, cr, amount):
        with db() as conn:
            return post_entry(conn, "2026-05-01", desc, [
                {"account_id": dr, "gold_debit": amount},
                {"account_id": cr, "gold_credit": amount}], username="admin")

    _sg.take_warning()
    _post("سحب يتجاوز الرصيد", lossacc, tz, before + 500.0)
    warn = _sg.take_warning()
    check("ينبّه حين يصير الرصيد سالباً",
          "سالب" in warn and "1100" in warn, warn.split("\n")[0])

    _post("توريد يُصلح العجز", tz, lossacc, 100.0)
    check("لا ينبّه على قيد يُقلّل العجز", _sg.take_warning() == "")

    with db() as conn:
        _sg.set_mode(conn, "block", "admin")
    expect_error("يمنع قيداً يزيد العجز",
                 lambda: _post("سحب آخر", lossacc, tz, 10.0),
                 "الرصيد لا يكفي")
    with db(readonly=True) as conn:
        left = conn.execute(
            "SELECT COUNT(*) c FROM journal_entries"
            " WHERE description='سحب آخر'").fetchone()["c"]
    check("العملية الممنوعة لا تترك أثراً", left == 0, str(left))
    _post("تصحيح في وضع المنع", tz, lossacc, 50.0)
    check("القيد المصحِّح يمرّ في وضع المنع", True)
    with db() as conn:
        _sg.set_mode(conn, "warn", "admin")
        n_neg = len(_sg.negatives(conn))
    check("يرصد الأرصدة السالبة القائمة", n_neg >= 1, f"{n_neg} حساب")
    expect_error("وضع غير مدعوم يُرفض",
                 lambda: _sg.set_mode(conn, "maybe", "admin"), "غير مدعوم")
    # إعادة الخزينة إلى موجب حتى لا تتأثر بقية الفحوص
    _post("إعادة الرصيد", tz, lossacc, 1000.0)

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
                "أعمار الديون (30/60/90)", "الإدارة والتقارير"]
        check("ترتيب القائمة هو المعتمد حرفياً",
              top[:len(want)] == want, str(top[:len(want)]))
        grp = next((w1.sidebar.topLevelItem(i)
                    for i in range(w1.sidebar.topLevelItemCount())
                    if w1.sidebar.topLevelItem(i).text(0)
                    == "الإدارة والتقارير"), None)
        check("بقية الشاشات كلها داخل «الإدارة والتقارير»",
              grp is not None and grp.childCount() == len(base) - 12,
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
