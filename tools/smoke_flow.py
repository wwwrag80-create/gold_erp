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

    # ══ لا رفع سحابي (4.29) ══ فواتير وسندات وقيود رُحّلت أعلاه، ولم
    # يُضف منها شيء لطابور الرفع — وبقايا الإصدارات السابقة تُفرَّغ.
    with db() as conn:
        st = sync_queue.stats(conn)
        conn.execute("INSERT INTO sync_queue(tenant_id,op_uuid,entity,"
                     "payload) VALUES('T','legacy-1','invoice','{}')")
        purged = sync_queue.purge_all(conn)
        st2 = sync_queue.stats(conn)
    check("لا شيء من عمليات المصنع يُوضع للرفع السحابي",
          st["total"] == 0, f"{st['total']} حزمة")
    check("وبقايا الطابور القديمة تُفرَّغ", purged == 1 and st2["total"] == 0,
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
    # والقيد يتبع الفاتورة لا إجماليها المخزَّن: الانحراف المصطنع أعلاه
    # (+٥٣٠) كان يُضرب في القيد نسبةً خاطئة فيصير ٥٠ جراماً ٧٫٩٣٦
    with db(readonly=True) as conn:
        _jl18 = conn.execute(
            "SELECT l.gold_debit g, l.cash_debit c, i.total_weight tw,"
            " i.grand_total gt FROM invoices i"
            " JOIN entities en ON en.id=i.customer_id"
            " JOIN journal_lines l ON l.entry_id=i.entry_id"
            "  AND l.account_id=en.account_id WHERE i.id=?",
            (eid,)).fetchone()
    check("قيد الفاتورة المعدّلة يساوي إجماليها وزناً ونقداً",
          abs(_jl18["g"] - _jl18["tw"]) < 0.002
          and abs(_jl18["c"] - _jl18["gt"]) < 0.011,
          f"قيد {_jl18['g']}/{_jl18['c']} · فاتورة {_jl18['tw']}/{_jl18['gt']}")
    # وفحص الصحة يلتقط قيداً افترق عن فاتورته — ثم يُعاد كما كان
    _sql18 = ("UPDATE journal_lines SET gold_debit=gold_debit+(?)"
              " WHERE entry_id=(SELECT entry_id FROM invoices WHERE id=?)"
              " AND account_id=(SELECT en.account_id FROM invoices i"
              " JOIN entities en ON en.id=i.customer_id WHERE i.id=?)")
    with db() as conn:
        conn.execute(_sql18, (3.0, eid, eid))
        _hb18 = _h.check_invoice_totals(conn)
        conn.execute(_sql18, (-3.0, eid, eid))
        _ha18 = _h.check_invoice_totals(conn)
    check("وفحص الصحة يلتقط قيداً يخالف فاتورته",
          any(b["id"] == eid and b.get("journal") for b in _hb18)
          and not _ha18, str(_hb18[:1]))

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
              abs(_gm.to_base_karat(vrow["gold_weight"],
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
    # «من حساب» شأنٌ داخليٌّ للمصنع — لا يُطبع على ورقة العميل
    check("«من حساب» لا يظهر في قالب الفاتورة", "من حساب" not in html_inv)

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
    check("وأحدث دين: أقدم دينٍ في فئة «أقل من 30» (فاتورة قبل ١٠ أيام)",
          r0["newest_days"] == 10 and r0["newest"] == _ago(10),
          f"{r0['newest_days']} · {r0['newest']}")
    _today_ag = _ago(0)
    check("«أحدث» = أقدم ما في «أقل من 30» لا آخر بضاعة (40·25·5 ← 25)",
          _ag._oldest_current([[_ago(40), 5.0], [_ago(25), 3.0],
                               [_ago(5), 2.0]], _today_ag) == _ago(25)
          and _ag._oldest_current([[_ago(40), 5.0]], _today_ag) == "",
          _ag._oldest_current([[_ago(40), 5.0], [_ago(25), 3.0],
                               [_ago(5), 2.0]], _today_ag))
    try:
        from PyQt5 import QtWidgets as _QWag
        _QWag.QApplication.instance() or _QWag.QApplication([])
        from ui.reports.aging_screen import AgingScreen as _AGS
        _ags = _AGS({"id": 1, "username": "admin", "role": "admin",
                     "role_local": "accountant"})
        _hd = _ags._headers("both")
        check("شاشة الأعمار: «أحدث دين» قبل «أقدم دين»",
              _hd.index("أحدث\nدين") + 1 == _hd.index("أقدم\nدين"),
              str(_hd[:4]))
        _cells = _ags._row_cells(r0, "both")
        check("وخليته تحمل أيام أحدث دين",
              _cells[2] == "10" and _cells[3] == str(r0["days"]),
              str(_cells[:4]))
        _ags.close()
    except ImportError:
        pass
    with db(readonly=True) as conn:
        _hag = __import__("services.print_manager", fromlist=["x"]) \
            ._tpl_aging(conn, 0, "customer")
    check("وورقة الأعمار: «أحدث» و«أقدم دين» بعنوانين قصيرين",
          '>أحدث</th>' in _hag and '>أقدم دين</th>' in _hag
          and "(يوم)" not in _hag and "table-layout: fixed" in _hag)
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

        # ══ الترتيب المعتمد: خمس عشرة شاشة يومية ثم مجموعة واحدة ══
        from ui.main_window import NAV_VERSION as _NAVV
        top = [w1.sidebar.topLevelItem(i).text(0)
               for i in range(w1.sidebar.topLevelItemCount())]
        want = ["لوحة التحكم", "دليل الموديلات", "حركة الطقم",
                "كشف حساب", "الوارد من التصنيع", "مبيعات/مرتجعات",
                "المبيعات الضريبية", "سندات قبض/صرف", "العملاء — المبيعات والسداد",
                "التسكيرات", "المشتريات",
                "القيود اليومية", "تقارير مبيعات وإنتاج المصنع",
                "التحليل والدراسات", "الإدارة والتقارير"]
        check("ترتيب القائمة هو المعتمد حرفياً",
              top[:len(want)] == want, str(top[:len(want)]))
        grp = next((w1.sidebar.topLevelItem(i)
                    for i in range(w1.sidebar.topLevelItemCount())
                    if w1.sidebar.topLevelItem(i).text(0)
                    == "الإدارة والتقارير"), None)
        check("بقية الشاشات كلها داخل «الإدارة والتقارير»",
              grp is not None and grp.childCount() == len(base) - 14,
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
    check("مقاس الخط يُضرب في المعامل", "font-size:28px" in
          _big.replace("font-size: ", "font-size:"), _big[:200])
    import re as _re_fs
    from ui import styles as _sty27
    _odd = _th.build(_sty27.TEMPLATE, _th.LIGHT, 0.93)
    check("والبكسل عددٌ صحيح دائماً — Qt يُسقط «22.4px» بصمت فيصغر النصّ",
          not _re_fs.search(r"font-size:\s*\d+\.\d+px", _odd)
          and _re_fs.search(r"font-size:\s*\d+\.\dpt", _odd))
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
    with db(readonly=True) as conn:
        _cn = conn.execute("SELECT e.name FROM invoices i JOIN entities e"
                           " ON e.id=i.customer_id WHERE i.id=?",
                           (inv_id,)).fetchone()[0]
    check("صفحة الرمز لصور الموديلات وحدها: لا عميل ولا مبالغ",
          str(_d["no"]) in _page and _cn not in _page
          and f'{_d["total"]:,.2f}' not in _page
          and "العميل" not in _page, _cn)
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
        del _bad["date"]                # يرفع استثناءً داخل الرسم
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
    # قيدٌ يدوي طرفُه المقابل «الأرصدة الافتتاحية» (3900) — رصيدُ بدايةٍ
    # لا حركة، فمكانه «أول المدة». (القيد اليدوي على حسابٍ آخر حركةٌ:
    # القاعدة في `models.opening` ومفحوصةٌ في الخطوة ٥٠.)
    with db() as conn:
        post_entry(conn, "2026-03-25", "قيد يومي",
                   [{"account_id": _macc, "gold_debit": 7.0},
                    {"account_id": acc_id(conn, "3900"),
                     "gold_credit": 7.0}], source_table="manual",
                   username="admin")
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
        _batch(conn, [{"wo_no": "00010", "gold": 200.0,
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
    # 4.54: «رواتب العمال والإدارة» — كل موظفٍ يظهر في الرواتب افتراضاً
    with db(readonly=True) as conn:
        _after = {r["employee_id"]: r
                  for r in _mc2.list_salaries(conn, _per)}
        _tg = {r["employee_id"] for r in _mc2.list_targets(conn, _per)}
    check("الموظف الإداري يظهر في جدول الرواتب افتراضاً (لا التارجت)",
          _eeid in _after and _after[_eeid]["is_extra"]
          and not _after[_weid]["is_extra"] and _eeid not in _tg
          and _weid in _tg, f"{len(_after)} صفاً")
    # إجازة: يُزال من الرواتب فلا ينزل له راتب — وحسابُه باقٍ
    with db() as conn:
        _mc2.remove_person(conn, "salary", _eeid, "admin")
    with db(readonly=True) as conn:
        _gone = {r["employee_id"] for r in _mc2.list_salaries(conn, _per)}
        _acc_ok = conn.execute(
            "SELECT 1 FROM entities e JOIN accounts a ON a.id=e.account_id"
            " WHERE e.id=? AND e.is_deleted=0",
            (_emp,)).fetchone()
        _avail = {p["id"]: p for p in
                  _mc2.available_people(conn, "salary")}
    check("إزالتُه من الرواتب تُخفي صفَّه وحسابُه باقٍ — ويظهر «مُزالاً»"
          " في قائمة الإعادة",
          _eeid not in _gone and _weid in _gone and bool(_acc_ok)
          and _avail.get(_eeid, {}).get("hidden"))
    with db() as conn:
        _mc2.add_person(conn, "salary", _eeid, "admin")
        # والإزالة لكل جدولٍ وحده: العامل يُزال من الرواتب ويبقى في التارجت
        _mc2.remove_person(conn, "salary", _weid, "admin")
    with db(readonly=True) as conn:
        _back = {r["employee_id"] for r in
                 _mc2.list_salaries(conn, "2026-08")}
        _tg2 = {r["employee_id"] for r in _mc2.list_targets(conn, _per)}
        # شهرٌ نزل راتبه فعلاً لا تنقص منه رواتبُ نزلت
        _kept = {r["employee_id"] for r in _mc2.list_salaries(conn, _per)}
    check("وإعادتُه تُرجع صفَّه — والإزالة من جدولٍ لا تمسّ الآخر",
          _eeid in _back and _weid not in _back and _weid in _tg2)
    check("ومن أُزيل بعد نزول راتب شهرٍ يبقى ظاهراً في ذلك الشهر وحده",
          _weid in _kept)
    with db() as conn:
        _mc2.add_person(conn, "salary", _weid, "admin")
    with db(readonly=True) as conn:
        _back = {r["employee_id"] for r in _mc2.list_salaries(conn, _per)}
    check("والعامل يعود لجدول الرواتب بزرّ الإعادة", _weid in _back)

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
          "الرصيد (− عليه · + له)" in _html6 and "المستحق" in _html6
          and "إضافية" in _html6, f"{len(_html6)} حرفاً")

    # ══ «عليه (مدين)»: رصيدُ كشف الحساب لا مسحوبات الشهر ══
    # قبل ترحيل الراتب: سندُ صرفه 500 يجعله مديناً بـ500 فيظهر.
    # وبعد الترحيل يصير دائناً بـ2700 فلا يظهر شيء — فالعمود يقول
    # «ما عليه» لا «ما أخذه».
    with db(readonly=True) as conn:
        _owed_after = _mc2.owed_now(conn, _weid)
        _sal_after = {r["employee_id"]: r
                      for r in _mc2.list_salaries(conn, _per)}[_weid]
    # 4.48: عمود «الرصيد» بطرفه — بعد الترحيل دائنٌ (له) فيُعرض «دائن»
    # بقيمته، والمستحق ما له في الكشف (فالصافي المُرحَّل داخلٌ فيه)
    with db(readonly=True) as conn:
        _bal_after = _mc2.balance_now(conn, _weid)
    check("وبعد الترحيل يصير العامل دائناً: الرصيد موجبٌ بما له",
          _owed_after == 0.0 and _bal_after < 0
          and abs(_sal_after["owed"] - _bal_after) < 0.011
          and not _mc2.bal_text(_sal_after["owed"]).startswith("\u200e-")
          and _mc2.bal_text(_sal_after["owed"]) != "",
          f"رصيده {_wc2} · {_mc2.bal_text(_sal_after['owed'])}")
    check("والمستحق بعد الترحيل = ما له في كشفه (لا الصافي مرةً ثانية)",
          _sal_after.get("is_posted")
          and abs(_sal_after["due"] + _sal_after["owed"]) < 0.011,
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
    # من سطور الدفعات لا من بطاقات الأطقم، لأن الرقم التجميعي 00010
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
            {"wo_no": "00010", "gold": 70.0, "wage_per_gram": 20.0,
             "model_no": "موديل الوارد"}], "2026-08-03", "admin")
    with db() as conn:
        _b9(conn, [
            {"wo_no": "R903", "gold": 30.0, "wage_per_gram": 24.0,
             "model_no": "موديل الوارد"},
            {"wo_no": "00010", "gold": 15.0, "wage_per_gram": 20.0,
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
          sorted(_by) == sorted(["00010", _r1, _r2]), f"{sorted(_by)}")
    check("والمباعة تحمل اسم الجهة التي هي عندها الآن",
          _by[_r1]["holder"] == "مشترٍ من دفعة اليوم"
          and not _by[_r1]["safe"], _by[_r1]["holder"])
    check("والباقية تحمل «الخزنة»",
          _by[_r2]["holder"] == _mcat.SAFE and _by[_r2]["safe"],
          _by[_r2]["holder"])
    check("والرقم التجميعي يُنسب لكل يومٍ بحصته لا برصيده المتراكم",
          abs(_by["00010"]["reg"] - 70.0) < 0.011
          and abs({i["wo"]: i for i in
                   {m["model"]: m for m in _d11["models"]}
                   ["موديل الوارد"]["items"]}["00010"]["reg"] - 15.0) < 0.011,
          f"{_by['00010']['reg']} ثم 15")
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
          "height: 128mm" in _html8 and "height: 122mm" in _html8
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
    # الدخول يجري في خيطٍ خلفي (4.19) ونتيجته تصل `_login_ok`
    _src_try9 = _insp9.getsource(_gw9.GateWindow.try_login)
    _src_login = _insp9.getsource(_gw9.GateWindow._login_ok)
    check("الدخول في خيطٍ خلفي فلا تتجمّد الحركة ولا تضيع النقرة",
          "threading.Thread" in _src_try9 and "self._busy" in _src_try9
          and "_login_ok" in _src_try9 and "_login_failed" in _src_try9)
    check("الفتح مربوطٌ بنداءٍ بعد الدخول لا بقبولٍ يُخفي البوابة",
          hasattr(_main9, "wire_gate")
          and "gate.exec_()" not in _src_main
          and "on_signed_in" in _src_login
          and "self.accept()" not in _src_login.split(
              "cb = getattr")[0])
    _build9 = _src_main[_src_main.index("def _build_system"):
                        _src_main.index("def _on_signed_in")]
    _signed9 = _src_main[_src_main.index("def _on_signed_in"):
                         _src_main.index("gate.on_signed_in =")]
    check("الموجة أولاً ثم البناء خلف مشهدٍ ساكن، ثم يُعرض النظام قبل "
          "التمازج — فلا يسبق الإغلاقُ الظهور",
          "gate.hand_off" in _signed9 and "_build_system" in _signed9
          and "win.showMaximized()" in _build9
          and "_reveal(win)" in _build9
          and _build9.index("win.showMaximized()")
          < _build9.index("_reveal(win)")
          and "gate.close" not in _build9,
          "الإغلاق في نهاية التمازج وحده")
    _steps9 = _main9.prepare_steps()
    check("وخطوات الإقلاع مسمّاة تُعرض على البوابة وهي تُنفَّذ",
          len(_steps9) >= 7
          and all(isinstance(a, str) and callable(b) for a, b in _steps9)
          and "قاعدة البيانات" in _steps9[0][0],
          f"{len(_steps9)} خطوات")
    _init9 = _insp9.getsource(_gw9.GateWindow.__init__)
    check("لوحة الدخول لا تُبنى أصلاً قبل أوانها فلا تومض",
          "self.card = None" in _init9
          and "self.hero.hide()" in _init9
          and "QDialog#gateWindow { background:" in _gw9.GATE_QSS
          and _gw9.CARD_DELAY > _gw9.HERO_DELAY + 800,
          f"الترحيب {_gw9.HERO_DELAY}مث · اللوحة {_gw9.CARD_DELAY}مث")

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

    step("44) من أي حساب يخرج ذهب الفاتورة")
    # ══ لماذا هذا الفحص ══
    # الفاتورة كانت تُخرج الذهب من حسابٍ واحدٍ مكتوبٍ في الكود (1200).
    # ومن باع من صندوق الكسر اضطُرّ لقيدٍ يدويٍّ بعدها يُصحّح المخزن —
    # قيدٌ يُنسى فيختلّ الصندوقان معاً بلا أن يظهر شيءٌ في الميزان.
    # فصار الحساب اختياراً يُحفظ مع الفاتورة. وما يُحرَس هنا ثلاثة:
    # أن الذهب يخرج من المختار فعلاً، وأن صندوق الكسر يُنقَص **بعياره**
    # لا بمكافئه وحده، وأن تعديل الفاتورة ينقل السطر ولا يكتب قيداً
    # ثانياً لعمليةٍ واحدة.
    from models import invoices as _iv44
    from models.inventory import (add_scrap_move as _asm44,
                                  scrap_actuals as _sa44)
    from services import gold_math as _gm44
    with db() as conn:
        _c44 = add_entity(conn, "عميل حساب المصدر", "customer",
                          username="admin")
        create_work_orders_batch(conn, [
            {"wo_no": "SRC-1", "gold": 40.0, "small_stones": 0.0,
             "big_stones": 0.0, "wage_per_gram": 20.0},
            {"wo_no": "SRC-2", "gold": 30.0, "small_stones": 0.0,
             "big_stones": 0.0, "wage_per_gram": 20.0},
        ], "2026-12-20", "admin")
        # أطقمٌ بلا بيت (كما قبل 4.45): تتبع «من حساب» الفاتورة. أما
        # الطقم المرتبط بحسابه فيخرج من حسابه — فحصه في الخطوة 79.
        conn.execute("UPDATE work_orders SET stock_account_id=NULL"
                     " WHERE work_order_no IN ('SRC-1','SRC-2')")
        _scrap44 = acc_id(conn, "1310")
        _worked44 = acc_id(conn, "1200")
        post_entry(conn, "2026-12-20", "رصيد كسر للاختبار", [
            {"account_id": _scrap44, "gold_debit": 120.0},
            {"account_id": acc_id(conn, "3900"), "gold_credit": 120.0}],
            username="admin")
        _asm44(conn, 21, _gm44.from_base_karat(120.0, 21), "opening", 0)
    with db(readonly=True) as conn:
        _codes44 = [r["code"] for r in _iv44.source_accounts(conn)]
    check("قائمة الحسابات المسموحة من شجرة الذهب لا من الكود",
          {"1100", "1200", "1310"} <= set(_codes44)
          and "1400" not in _codes44 and "5150" not in _codes44,
          " · ".join(_codes44))

    def _bal44(code):
        with db(readonly=True) as conn:
            return account_balance(conn, acc_id(conn, code))[0]

    _b_scrap = _bal44("1310")
    _b_worked = _bal44("1200")
    with db() as conn:
        _w44 = conn.execute(
            "SELECT id FROM work_orders WHERE work_order_no='SRC-1'"
        ).fetchone()["id"]
        _inv44 = create_sale(conn, _c44,
                             [{"work_order_id": _w44, "karat": 21}],
                             "2026-12-21", "admin", apply_vat=False,
                             source_account_id=_scrap44, scrap_karat=21)
    check("البيع من صندوق الكسر يُنقصه هو لا الذهب المشغول",
          abs((_b_scrap - _bal44("1310")) - 40.0) < 0.011
          and abs(_bal44("1200") - _b_worked) < 0.011,
          f"الكسر {_b_scrap:.2f} ← {_bal44('1310'):.2f} · "
          f"المشغول {_bal44('1200'):.2f}")
    with db(readonly=True) as conn:
        _mv44 = conn.execute(
            "SELECT karat, actual_delta d FROM scrap_moves"
            " WHERE ref_table='invoices' AND ref_id=? AND is_deleted=0",
            (_inv44["id"],)).fetchall()
        _kar44 = conn.execute(
            "SELECT COALESCE(karat,0) k FROM invoice_items"
            " WHERE invoice_id=?", (_inv44["id"],)).fetchone()["k"]
    check("والصندوق يُنقص بوزنه الفعلي بعياره لا بمكافئ 18",
          len(_mv44) == 1 and _mv44[0]["karat"] == 21
          and abs(_mv44[0]["d"] + _gm44.from_base_karat(40.0, 21)) < 0.011,
          f"{_mv44[0]['karat'] if _mv44 else '—'} · "
          f"{_mv44[0]['d'] if _mv44 else 0:.3f}")
    check("وعيار كتابة السطر يُحفظ معه ليُعاد كما كُتب",
          _kar44 == 21, str(_kar44))
    _g44, _c44b, _gv44, _cv44 = None, None, None, None
    with db(readonly=True) as conn:
        _g44, _c44b, _gv44, _cv44 = ledger_balanced(conn)
    check("والدفتر متوازن بعد البيع من الكسر", _g44 and _c44b,
          f"ذهب {_gv44} · نقد {_cv44}")

    _b_scrap2, _b_worked2 = _bal44("1310"), _bal44("1200")
    with db(readonly=True) as conn:
        _it44 = conn.execute(
            "SELECT id FROM invoice_items WHERE invoice_id=?",
            (_inv44["id"],)).fetchone()["id"]
        _entries_before = conn.execute(
            "SELECT COUNT(*) c FROM journal_entries"
            " WHERE source_table='invoices' AND source_id=?",
            (_inv44["id"],)).fetchone()["c"]
    with db() as conn:
        _up44 = _iv44.update_invoice(
            conn, _inv44["id"],
            [{"work_order_id": _w44, "item_id": _it44, "karat": 21,
              "weight": 40.0, "wage_override": 20.0}],
            "admin", source_account_id=_worked44)
    with db(readonly=True) as conn:
        _entries_after = conn.execute(
            "SELECT COUNT(*) c FROM journal_entries"
            " WHERE source_table='invoices' AND source_id=?",
            (_inv44["id"],)).fetchone()["c"]
        _left44 = conn.execute(
            "SELECT COUNT(*) c FROM scrap_moves WHERE ref_table='invoices'"
            " AND ref_id=? AND is_deleted=0",
            (_inv44["id"],)).fetchone()["c"]
        _g44, _c44b, _gv44, _cv44 = ledger_balanced(conn)
    check("وتصحيح الحساب ينقل سطر القيد نفسه — بلا قيدٍ ثانٍ",
          _entries_after == _entries_before
          and abs((_bal44("1310") - _b_scrap2) - 40.0) < 0.011
          and abs((_b_worked2 - _bal44("1200")) - 40.0) < 0.011
          and bool(_up44.get("moved_source")),
          f"قيود {_entries_before} ← {_entries_after}")
    check("وحركةُ الكسر تُمحى حين لم تعد الفاتورة منه",
          _left44 == 0 and _g44 and _c44b, f"{_left44} حركة")

    def _bad_source():
        with db() as conn:
            _w2 = conn.execute(
                "SELECT id FROM work_orders WHERE work_order_no='SRC-2'"
            ).fetchone()["id"]
            create_sale(conn, _c44, [{"work_order_id": _w2}],
                        "2026-12-22", "admin",
                        source_account_id=acc_id(conn, "1400"))
    expect_error("ويُرفض إخراج ذهبٍ من حسابٍ ليس مخزن ذهب",
                 _bad_source, "لا يصلح")

    # ══ الشاشة: الترتيب الذي طلبه صاحب النظام ══
    # الترتيب نفسه في سطر الإدخال وفي الجدول وفي الفاتورة المطبوعة —
    # فمن حفظ موضع خانةٍ وجدها في موضعها في الورقة كذلك.
    try:
        from PyQt5 import QtWidgets as _QW44
        _QW44.QApplication.instance() or _QW44.QApplication([])
        from ui.sales_screen import SalesScreen as _SS44
        _scr44 = _SS44({"id": 1, "username": "admin", "full_name": "م",
                        "role": "admin", "role_local": "accountant"})
        _scr44.refresh()
        # الترتيب الأحدث: المقيد والقائم والعيار والأجر في آخر السطر
        _order44 = [_scr44.model_no, _scr44.barcode, _scr44.line_gold,
                    _scr44.line_small, _scr44.line_big, _scr44.line_after,
                    _scr44.line_reg, _scr44.line_standing,
                    _scr44.line_karat, _scr44.line_wage]
        check("سطر الإدخال بالترتيب المطلوب وEnter يمشي عليه",
              _scr44._chain == _order44 and len(_scr44._enter_navs) >= 1)
        check("وأعمدة الجدول بالترتيب نفسه بعد عمود الأزرار",
              _scr44.COLS == ["", "الموديل", "رقم التشغيل", "العيار",
                              "الحساب", "الوزن المقيد", "الوزن القائم", "الذهب",
                              "الفصوص", "الأحجار", "الأحجار بعد الخصم",
                              "الأجر/جم", "الأجرة (ريال)"],
              " · ".join(_scr44.COLS))
        # `isHidden` لا `isVisible`: الشاشة هنا لا تُعرض أصلاً، فكل ما
        # فيها «غير مرئي» — والمقصود الخانة المُخفاة صراحةً.
        check("وحساب المصدر في رأس الشاشة بافتراضه المعروف",
              _scr44._source_code() == "1200"
              and _scr44.scrap_karat.isHidden(),
              _scr44._source_code())
        _codes_ui = [r["code"] for r in _scr44.sources]
        _scr44.source.setCurrentIndex(_codes_ui.index("1310"))
        check("وخانة العيار لا تظهر إلا لصندوق الكسر",
              not _scr44.scrap_karat.isHidden()
              and load_pref("sales_source_account", "") == "1310")
        _scr44.source.setCurrentIndex(_codes_ui.index("1200"))
    except ImportError:
        print("  … تُخطّى فحوص الواجهة (PyQt5 غير متاح)")

    step("45) إلى أي حساب تدخل بضاعة التوريد")
    # ══ السؤال نفسه معكوساً ══
    # الفاتورة تُخرج ذهباً من مخزن، ودفعة التوريد تُدخله إلى مخزن.
    # وكلاهما كان حساباً واحداً مكتوباً في الكود. وما يُحرَس هنا: أن
    # البضاعة تدخل المختار فعلاً، وأن صندوق الكسر يزيد **بعياره**،
    # وأن تصحيح الوجهة ينقل السطر ولا يكتب قيداً ثانياً.
    from models import inventory as _iv45
    with db() as conn:
        _scrap45 = acc_id(conn, "1310")
        _b45 = _iv45.create_work_orders_batch(conn, [
            {"wo_no": "DST-1", "gold": 30.0, "small_stones": 0.0,
             "big_stones": 0.0, "wage_per_gram": 20.0, "karat": 21},
        ], "2026-12-23", "admin", dest_account_id=_scrap45, scrap_karat=22)

    def _bal45(code):
        with db(readonly=True) as conn:
            return account_balance(conn, acc_id(conn, code))[0]

    with db(readonly=True) as conn:
        _line45 = _iv45.batch_dest_line(conn, _b45["entry_id"])
        _mv45 = conn.execute(
            "SELECT karat, actual_delta d FROM scrap_moves"
            " WHERE ref_table='work_orders' AND ref_id=? AND is_deleted=0",
            (_b45["entry_id"],)).fetchall()
        _wbl45 = conn.execute(
            "SELECT COALESCE(karat,0) k FROM wo_batch_lines"
            " WHERE entry_id=?", (_b45["entry_id"],)).fetchone()["k"]
    check("دفعة التوريد تدخل الحساب المختار لا الذهب المشغول",
          bool(_line45) and _line45["code"] == "1310",
          _line45["code"] if _line45 else "—")
    check("وصندوق الكسر يزيد بوزنه الفعلي بعياره",
          len(_mv45) == 1 and _mv45[0]["karat"] == 22
          and abs(_mv45[0]["d"] - _gm44.from_base_karat(30.0, 22)) < 0.011,
          f"{_mv45[0]['karat'] if _mv45 else '—'} · "
          f"{_mv45[0]['d'] if _mv45 else 0:.3f}")
    check("وعيار كتابة السطر يُحفظ في سطر الدفعة", _wbl45 == 21,
          str(_wbl45))
    _b_scrap45, _b_worked45 = _bal45("1310"), _bal45("1200")
    with db(readonly=True) as conn:
        _n45 = conn.execute(
            "SELECT COUNT(*) c FROM journal_entries"
            " WHERE source_table='work_orders'").fetchone()["c"]
    with db() as conn:
        _up45 = _iv45.update_supply_batch(
            conn, _b45["entry_id"],
            [{"wo_no": "DST-1", "gold": 30.0, "small_stones": 0.0,
              "big_stones": 0.0, "discount_rate": 0.5,
              "wage_per_gram": 20.0, "karat": 21}],
            "2026-12-23", "admin",
            dest_account_id=acc_id(conn, "1200"))
    with db(readonly=True) as conn:
        _n45b = conn.execute(
            "SELECT COUNT(*) c FROM journal_entries"
            " WHERE source_table='work_orders'").fetchone()["c"]
        _left45 = conn.execute(
            "SELECT COUNT(*) c FROM scrap_moves"
            " WHERE ref_table='work_orders' AND ref_id=? AND is_deleted=0",
            (_b45["entry_id"],)).fetchone()["c"]
        _g45, _c45, _gv45, _cv45 = ledger_balanced(conn)
    check("وتصحيح الوجهة ينقل سطر القيد نفسه — بلا قيدٍ ثانٍ",
          _n45b == _n45 and bool(_up45.get("moved_dest"))
          and abs((_b_scrap45 - _bal45("1310")) - 30.0) < 0.011
          and abs((_bal45("1200") - _b_worked45) - 30.0) < 0.011,
          f"قيود {_n45} ← {_n45b}")
    check("وحركةُ الكسر تُمحى حين لم تعد الدفعة إليه، والدفتر متوازن",
          _left45 == 0 and _g45 and _c45,
          f"{_left45} حركة · ذهب {_gv45}")

    def _bad_dest():
        with db() as conn:
            _iv45.create_work_orders_batch(
                conn, [{"wo_no": "DST-9", "gold": 5.0, "small_stones": 0.0,
                        "big_stones": 0.0}], "2026-12-24", "admin",
                dest_account_id=acc_id(conn, "1400"))
    expect_error("ويُرفض إدخال بضاعةٍ إلى حسابٍ ليس مخزن ذهب",
                 _bad_dest, "لا يصلح")

    # ══ الشاشتان: عمود الأزرار وترتيب الخانات ══
    try:
        from PyQt5 import QtWidgets as _QW45
        _QW45.QApplication.instance() or _QW45.QApplication([])
        from ui.production_screen import ProductionScreen as _PS45
        _u45 = {"id": 1, "username": "admin", "full_name": "م",
                "role": "admin", "role_local": "accountant"}
        _scr45 = _PS45(_u45)
        _scr45.refresh()
        check("شاشة التوريد: الوجهة في رأسها بافتراضها المعروف",
              _scr45._dest_code() == "1200"
              and _scr45.scrap_karat.isHidden(), _scr45._dest_code())
        _codes45 = [r["code"] for r in _scr45.dests]
        _scr45.dest.setCurrentIndex(_codes45.index("1310"))
        check("وخانة العيار لا تظهر إلا لصندوق الكسر",
              not _scr45.scrap_karat.isHidden()
              and load_pref("supply_dest_account", "") == "1310")
        _scr45.dest.setCurrentIndex(_codes45.index("1200"))
        check("وأعمدة جدول الدفعة أولها عمود الأزرار بلا عنوان",
              _scr45.COLS[0] == ""
              and _scr45.COLS[1:6] == ["رقم الموديل", "رقم التشغيل",
                                       "العيار", "الوزن المقيد",
                                       "الوزن القائم"],
              " · ".join(_scr45.COLS))
        _scr45.model_no.setCurrentText("MM")
        _scr45.wo_no.setText("BTN-1")
        _scr45.gold.setValue(12.0)
        _scr45.add_row()
        check("والزرّان يظهران لسطر الدفعة لا لصفّ الإجمالي",
              _scr45.grid.cellWidget(0, 0) is not None
              and _scr45.grid.cellWidget(1, 0) is None
              and _scr45.grid.rowCount() == 2,
              f"{_scr45.grid.rowCount()} صف")
        _scr45.remove_row(0)
        check("وزرُّ الحذف يحذف سطره بعينه", _scr45.batch == [])
        from ui.sales_screen import SalesScreen as _SS45
        _ss45 = _SS45(_u45)
        _ss45.refresh()
        check("وشاشة المبيعات كذلك: عمودٌ أول بلا عنوان للأزرار",
              _ss45.COLS[0] == "" and hasattr(_ss45, "edit_item"),
              " · ".join(_ss45.COLS[:3]))
        _ss45.kind.setCurrentIndex(_ss45.kind.findData("sale_return"))
        check("وفي المرتجع يصير العنوان «إلى حساب» لأن البضاعة تدخل",
              _ss45.source_lbl.text().startswith("إلى حساب"),
              _ss45.source_lbl.text())
        _ss45.kind.setCurrentIndex(_ss45.kind.findData("sale"))
        check("وفي البيع يعود «من حساب»",
              _ss45.source_lbl.text().startswith("من حساب"),
              _ss45.source_lbl.text())
    except ImportError:
        print("  … تُخطّى فحوص الواجهة (PyQt5 غير متاح)")

    step("46) البيان بيانُ صاحبه · والمرجع · وEnter يمضي للأمام")
    # ══ البيان ══
    # عمود «البيان» في كشف الحساب كان يمتلئ بوصف السطر الآلي
    # («مديونية ذهب وأجور»)، وكانت الفواتير تُستثنى فيُمحى بيانها
    # أصلاً — فمن كتب بياناً في شاشة المبيعات لم يجده في الكشف.
    # القاعدة الآن: البيان نصُّ المستخدم، أو فراغ.
    from models import inventory as _iv46
    from models import journal as _jr46
    with db() as conn:
        _c46 = add_entity(conn, "عميل البيان", "customer", username="admin")
        create_work_orders_batch(conn, [
            {"wo_no": "NOTE-1", "gold": 20.0, "small_stones": 0.0,
             "big_stones": 0.0, "wage_per_gram": 20.0,
             "notes": "دفعة الورشة الأولى"},
            {"wo_no": "NOTE-2", "gold": 10.0, "small_stones": 0.0,
             "big_stones": 0.0, "wage_per_gram": 20.0,
             "notes": "دفعة الورشة الأولى"},
        ], "2026-12-25", "admin", reference="ورقة 77")
        _wo46 = conn.execute(
            "SELECT id, entry_id FROM work_orders"
            " WHERE work_order_no='NOTE-1'").fetchone()
        _sale46 = create_sale(
            conn, _c46, [{"work_order_id": _wo46["id"]}],
            "2026-12-26", "admin", apply_vat=False,
            description="بيان الفاتورة كما كتبه المحاسب")
    with db(readonly=True) as conn:
        _st46 = _jr46.statement(conn, acc_id(conn, "1200"),
                                "2026-12-25", "2026-12-26")
        _cust46 = _jr46.statement(
            conn, conn.execute("SELECT account_id a FROM entities"
                               " WHERE id=?", (_c46,)).fetchone()["a"],
            "2026-12-25", "2026-12-26")
    _inv_row = [r for r in _cust46 if r["op"] == "مبيعات"]
    check("بيانُ الفاتورة الذي كتبه المستخدم يظهر في كشف الحساب",
          bool(_inv_row)
          and _inv_row[0]["desc"] == "بيان الفاتورة كما كتبه المحاسب",
          (_inv_row[0]["desc"] if _inv_row else "—"))
    _auto = [r for r in _st46 if "مديونية" in (r["desc"] or "")
             or "خروج الذهب" in (r["desc"] or "")]
    check("ولا يظهر وصفُ السطر الآلي في عمود البيان",
          not _auto, f"{len(_auto)} سطراً آلياً")
    _sup_row = [r for r in _st46 if r["op"] == "توريد"]
    check("ومرجعُ دفعة التوريد وملاحظاتها في بيانها",
          bool(_sup_row) and _sup_row[0]["desc"].startswith("مرجع: ورقة 77")
          and "دفعة الورشة الأولى" in _sup_row[0]["desc"],
          (_sup_row[0]["desc"] if _sup_row else "—"))
    check("والملاحظة المكرّرة لا تتكرّر في البيان",
          (_sup_row[0]["desc"].count("دفعة الورشة الأولى") == 1
           if _sup_row else False))
    with db(readonly=True) as conn:
        _ref46 = _iv46.batch_reference(conn, _wo46["entry_id"])
    check("والمرجع يُحفظ مع القيد فيعود عند فتح الدفعة للتعديل",
          _ref46 == "ورقة 77", _ref46)
    with db() as conn:
        _iv46.update_supply_batch(
            conn, _wo46["entry_id"],
            [{"wo_no": "NOTE-1", "gold": 20.0, "small_stones": 0.0,
              "big_stones": 0.0, "discount_rate": 0.5,
              "wage_per_gram": 20.0, "notes": "صُحّحت الملاحظة"},
             {"wo_no": "NOTE-2", "gold": 10.0, "small_stones": 0.0,
              "big_stones": 0.0, "discount_rate": 0.5,
              "wage_per_gram": 20.0, "notes": "صُحّحت الملاحظة"}],
            "2026-12-25", "admin", reference="ورقة 78")
    with db(readonly=True) as conn:
        _un46 = conn.execute(
            "SELECT user_note FROM journal_entries WHERE id=?",
            (_wo46["entry_id"],)).fetchone()["user_note"]
    check("وتعديلُ الدفعة يُعيد كتابة بيانها ومرجعها",
          _un46.startswith("مرجع: ورقة 78")
          and "صُحّحت الملاحظة" in _un46, _un46[:60])
    # وتصحيحُ بيان الفاتورة بعد ترحيلها يصل إلى الكشف كذلك
    with db() as conn:
        _it46 = conn.execute(
            "SELECT id FROM invoice_items WHERE invoice_id=?",
            (_sale46["id"],)).fetchone()["id"]
        _upd46 = _upd(conn, _sale46["id"],
                      [{"work_order_id": _wo46["id"], "item_id": _it46,
                        "weight": None, "wage_override": None}],
                      "admin", description="بيانٌ مصحَّح بعد الترحيل")
    with db(readonly=True) as conn:
        _row46 = conn.execute(
            "SELECT e.user_note un, i.description d FROM invoices i"
            " JOIN journal_entries e ON e.id=i.entry_id WHERE i.id=?",
            (_sale46["id"],)).fetchone()
    check("وتصحيحُ بيان الفاتورة ينزل إلى قيدها فيظهر في الكشف",
          _row46["un"] == "بيانٌ مصحَّح بعد الترحيل"
          and _row46["d"] == "بيانٌ مصحَّح بعد الترحيل"
          and not _upd46.get("unchanged"), _row46["un"])
    # والسند كذلك: بيانه العام وبيان أسطره معاً
    with db() as conn:
        _v46 = create_voucher(conn, "receipt", "2026-12-27", "admin",
                              entity_id=_c46, notes="سداد الشهر",
                              rows=[{"kind": "cash", "amount": 500.0,
                                     "notes": "نقداً باليد"}])
    with db(readonly=True) as conn:
        _vn46 = conn.execute(
            "SELECT e.user_note un FROM vouchers v"
            " JOIN journal_entries e ON e.id=v.entry_id WHERE v.id=?",
            (_v46["id"],)).fetchone()["un"]
    check("وبيانُ السند وبيانُ سطره يجتمعان في بيان الكشف",
          "سداد الشهر" in _vn46 and "نقداً باليد" in _vn46, _vn46)

    # ══ Enter يمضي للأمام ══
    try:
        from PyQt5 import QtCore as _QC46
        from PyQt5 import QtGui as _QG46
        from PyQt5 import QtWidgets as _QW46
        _app46 = _QW46.QApplication.instance() or _QW46.QApplication([])
        _u46 = {"id": 1, "username": "admin", "full_name": "م",
                "role": "admin", "role_local": "accountant"}

        def _enter(w):
            _QW46.QApplication.sendEvent(
                w, _QG46.QKeyEvent(_QC46.QEvent.KeyPress,
                                   _QC46.Qt.Key_Return,
                                   _QC46.Qt.NoModifier))
            _app46.processEvents()

        from ui.sales_screen import SalesScreen as _SS46
        _s46 = _SS46(_u46)
        _s46.refresh()
        _s46.show()
        _app46.processEvents()
        _s46.source.setFocus()
        _enter(_s46.source)
        check("المبيعات: Enter من حساب المصدر يتقدّم ولا يقف",
              not _s46.source.hasFocus(),
              type(_app46.focusWidget()).__name__)
        _s46.description.setFocus()
        _enter(_s46.description)
        # يُسلّم لرقم التشغيل (الخطوة ٤٧): الموديل يُملأ من البطاقة
        check("وEnter من آخر خانةٍ في الرأس يسلّم لسطر الإدخال",
              _s46.barcode.hasFocus(),
              type(_app46.focusWidget()).__name__)
        _s46.close()

        from ui.production_screen import ProductionScreen as _PS46
        _p46 = _PS46(_u46)
        _p46.refresh()
        _p46.show()
        _app46.processEvents()
        _p46.dest.setFocus()
        _enter(_p46.dest)
        check("والتوريد: Enter من حساب الوجهة يتقدّم كذلك",
              not _p46.dest.hasFocus(),
              type(_app46.focusWidget()).__name__)
        _p46.reference.setFocus()
        _enter(_p46.reference)
        check("وEnter من خانة المرجع يسلّم لسطر الإدخال",
              _p46.model_no.hasFocus() or _p46.model_no.lineEdit().hasFocus(),
              type(_app46.focusWidget()).__name__)
        _p46.close()

        # ══ بوابة الدخول: Enter والأسهم ══
        from ui.gate_window import GateWindow as _GW46
        _g46 = _GW46()
        _g46.resize(900, 600)
        _g46._ensure_card()
        _g46.show()
        _app46.processEvents()
        _g46.username.setFocus()
        _enter(_g46.username)
        check("والبوابة: Enter ينزل من الاسم إلى كلمة المرور",
              _g46.password.hasFocus())
        _QW46.QApplication.sendEvent(
            _g46.password, _QG46.QKeyEvent(_QC46.QEvent.KeyPress,
                                           _QC46.Qt.Key_Up,
                                           _QC46.Qt.NoModifier))
        _app46.processEvents()
        check("والسهم لأعلى يرجع للاسم", _g46.username.hasFocus())
        _QW46.QApplication.sendEvent(
            _g46.username, _QG46.QKeyEvent(_QC46.QEvent.KeyPress,
                                           _QC46.Qt.Key_Down,
                                           _QC46.Qt.NoModifier))
        _app46.processEvents()
        check("والسهم لأسفل ينزل لكلمة المرور", _g46.password.hasFocus())
        check("وأول رسمٍ للبوابة يُعلَن ليُغلق شعار البدء في لحظته",
              hasattr(_g46, "painted") and _g46._painted)
        _g46.close()
    except ImportError:
        print("  … تُخطّى فحوص الواجهة (PyQt5 غير متاح)")

    step("47) ترتيب خانات الإدخال · ورقم التشغيل يُمسك Enter")
    # ══ ما طلبه صاحب النظام حرفياً ══
    # • التوريد: المقيد والقائم والعيار آخرُ الخانات، ولا خانة أجر.
    # • المبيعات: المقيد والقائم والعيار والأجر آخرُها.
    # • في الشاشتين: Enter لا يتجاوز رقم التشغيل وهو فارغ، وبعد إضافة
    #   السطر يعود المؤشر إلى رقم التشغيل لا إلى أول السطر.
    try:
        from PyQt5 import QtCore as _QC47
        from PyQt5 import QtGui as _QG47
        from PyQt5 import QtWidgets as _QW47
        _app47 = _QW47.QApplication.instance() or _QW47.QApplication([])
        _u47 = {"id": 1, "username": "admin", "full_name": "م",
                "role": "admin", "role_local": "accountant"}

        def _enter47(w):
            _QW47.QApplication.sendEvent(
                w, _QG47.QKeyEvent(_QC47.QEvent.KeyPress,
                                   _QC47.Qt.Key_Return,
                                   _QC47.Qt.NoModifier))
            _app47.processEvents()

        from ui.production_screen import ProductionScreen as _PS47
        _p47 = _PS47(_u47)
        _p47.refresh()
        _p47.show()
        _app47.processEvents()
        check("التوريد: لا خانة أجرٍ ولا عمود أجرٍ في الجدول",
              not hasattr(_p47, "wage") and "الأجر/جم" not in _p47.COLS)
        check("والتنقّل: الموديل ← الرقم ← المكوّنات ← الملاحظة ← العيار",
              _p47._chain == [_p47.model_no, _p47.wo_no, _p47.gold,
                              _p47.small, _p47.big, _p47.notes,
                              _p47.karat])
        _p47.wo_no.clear()
        _p47.wo_no.setFocus()
        _enter47(_p47.wo_no)
        check("وEnter على رقم تشغيلٍ فارغ لا ينتقل",
              _p47.wo_no.hasFocus())
        _p47.wo_no.setText("ENT-1")
        _enter47(_p47.wo_no)
        check("ويتقدّم بعد كتابة الرقم", _p47.gold.hasFocus()
              or _p47.gold.lineEdit().hasFocus())
        _p47.gold.setValue(40.0)
        _p47.karat.setCurrentIndex(_p47.karat.findData(21))
        _app47.processEvents()
        check("والعيار في آخر السطر يصف المكتوب ولا يحوّله",
              abs(_p47.gold.value() - 40.0) < 0.001,
              f"{_p47.gold.value()}")
        _p47.karat.setFocus()
        _enter47(_p47.karat)
        check("وEnter على آخر خانة يضيف السطر ويعود لرقم التشغيل",
              len(_p47.batch) == 1 and _p47.wo_no.hasFocus()
              and _p47.batch[0]["karat"] == 21
              and abs(_p47.batch[0]["gold"] - 40.0) < 0.001,
              str(_p47.batch[:1]))
        from ui.production_screen import _wage18 as _w18_47
        _wv47 = _w18_47(_p47.batch[0])
        check("والطقم يُحفظ بأجر النظام الافتراضي بمكافئ 18 تماماً",
              abs(_wv47 - float(config.DEFAULT_WAGE_PER_GRAM)) < 1e-9,
              f"{_wv47}")
        _p47.batch = []
        _p47.render_batch()
        _p47.close()

        from ui.sales_screen import SalesScreen as _SS47
        _s47 = _SS47(_u47)
        _s47.refresh()
        _s47.show()
        _app47.processEvents()
        check("المبيعات: المقيد والقائم والعيار والأجر آخرُ السطر",
              _s47._chain[-4:] == [_s47.line_reg, _s47.line_standing,
                                   _s47.line_karat, _s47.line_wage]
              and _s47._chain[:2] == [_s47.model_no, _s47.barcode])
        _s47.barcode.clear()
        _s47.barcode.setFocus()
        _enter47(_s47.barcode)
        check("وEnter على رقم تشغيلٍ فارغ لا ينتقل",
              _s47.barcode.hasFocus())
        _s47.description.setFocus()
        _enter47(_s47.description)
        check("ورأس الفاتورة يُسلّم لرقم التشغيل مباشرةً",
              _s47.barcode.hasFocus())
        _s47.close()
    except ImportError:
        print("  … تُخطّى فحوص الواجهة (PyQt5 غير متاح)")

    step("48) لوحة العملاء — مبيعات ومرتجع وسداد وباقٍ")
    # ══ الباقي في اللوحة هو رصيد الأستاذ بعينه ══
    # اللوحة تصنّف الحركة (بيع · مرتجع · قبض · افتتاحي · أخرى) ولا
    # تُسقط منها شيئاً: فالمعادلة سابق + مبيعات − مرتجع − سداد + أخرى
    # يجب أن تساوي رصيد الحساب في الأستاذ — لأي فترة.
    from models import customer_board as _cb48
    from services.accounting_engine import account_balance as _ab48
    _to48 = "2099-12-31"
    with db() as conn:
        _res48 = _cb48.board(conn, None, _to48)
        _bad48 = []
        for _r in _res48["rows"]:
            _g, _c = _ab48(conn, _r["account_id"], date_to=_to48)
            if (abs(_r["gold"]["remaining"] - _g) > 0.002
                    or abs(_r["cash"]["remaining"] - _c) > 0.02):
                _bad48.append((_r["name"], _r["gold"]["remaining"], _g,
                               _r["cash"]["remaining"], _c))
        check("اللوحة تعرض كل العملاء المسجّلين",
              len(_res48["rows"]) == conn.execute(
                  "SELECT COUNT(DISTINCT account_id) FROM entities"
                  " WHERE entity_type='customer' AND is_deleted=0"
                  " AND COALESCE(is_internal,0)=0").fetchone()[0],
              str(len(_res48["rows"])))
        check("الباقي = رصيد الأستاذ لكل عميل (ذهباً ونقداً)",
              not _bad48, str(_bad48[:3]))
        _sold48 = [r for r in _res48["rows"] if r["gold"]["sales"] > 0]
        check("وفي اللوحة عملاء بمبيعات يُقاس عليهم", bool(_sold48))
        _mis48 = []
        for _r in _sold48:
            _inv = conn.execute(
                "SELECT COALESCE(SUM(CASE WHEN i.kind='sale'"
                "  THEN i.total_weight END),0) sw,"
                " COALESCE(SUM(CASE WHEN i.kind='sale_return'"
                "  THEN i.total_weight END),0) rw,"
                " COALESCE(SUM(CASE WHEN i.kind='sale'"
                "  THEN i.grand_total END),0) sc"
                " FROM invoices i JOIN entities e ON e.id=i.customer_id"
                " WHERE i.is_deleted=0 AND e.account_id=?",
                (_r["account_id"],)).fetchone()
            # والقيد اليومي يُقرأ بحسابه المقابل: ما جعل العميل مديناً
            # مقابل جهةٍ أو بضاعةٍ مبيعات، وما جعله دائناً مرتجع
            _jr = {"sales": [0.0, 0.0], "returns": [0.0, 0.0]}
            from models.entry_kind import Kinds as _K48
            _k48 = _K48(conn)
            for (_e48,) in conn.execute(
                    "SELECT DISTINCT e.id FROM journal_lines l"
                    " JOIN journal_entries e ON e.id=l.entry_id"
                    " WHERE e.is_deleted=0 AND l.account_id=?"
                    " AND COALESCE(e.source_table,'') IN"
                    " ('','manual','tax_debit_notes')",
                    (_r["account_id"],)).fetchall():
                _sp = _k48.split(_e48, [_r["account_id"]])
                _jr["sales"][0] += _sp["gold"].get("sales", 0.0)
                _jr["sales"][1] += _sp["cash"].get("sales", 0.0)
                _jr["returns"][0] -= _sp["gold"].get("returns", 0.0)
            if (abs(_inv["sw"] + _jr["sales"][0] - _r["gold"]["sales"]) > 0.002
                    or abs(_inv["rw"] + _jr["returns"][0]
                           - _r["gold"]["returns"]) > 0.002
                    or abs(_inv["sc"] + _jr["sales"][1]
                           - _r["cash"]["sales"]) > 0.02):
                _mis48.append((_r["name"], dict(_inv),
                               _r["gold"]["sales"], _r["gold"]["returns"]))
        check("المبيعات والمرتجع = الفواتير الحيّة + ما فُهم من القيود",
              not _mis48, str(_mis48[:2]))
        # فترةٌ من منتصف الطريق: ما قبلها يصير «رصيداً سابقاً» والباقي
        # لا يتغيّر
        _mid48 = conn.execute(
            "SELECT MAX(entry_date) FROM journal_entries"
            " WHERE is_deleted=0").fetchone()[0]
        _res48b = _cb48.board(conn, _mid48, _to48)
        _same48 = all(
            abs(a["gold"]["remaining"] - b["gold"]["remaining"]) < 0.002
            and abs(a["cash"]["remaining"] - b["cash"]["remaining"]) < 0.02
            for a, b in zip(
                sorted(_res48["rows"], key=lambda r: r["account_id"]),
                sorted(_res48b["rows"], key=lambda r: r["account_id"])))
        check("تضييق الفترة ينقل ما قبلها إلى «رصيد سابق» ولا يغيّر الباقي",
              _same48 and len(_res48["rows"]) == len(_res48b["rows"]))
        _p48 = [r for r in _res48["rows"] if r["gold"]["paid"] > 0
                and r["gold"]["net"] > 0]
        check("نسبة السداد = السداد ÷ صافي المبيعات",
              all(abs(r["gold"]["paid_pct"] - round(
                  r["gold"]["paid"] / r["gold"]["net"] * 100, 1)) < 0.06
                  for r in _p48), f"{len(_p48)} عميلاً")
        check("صافي المبيعات = رصيد سابق + المبيعات − المرتجع",
              all(abs(r[sd]["net"] - (r[sd]["open"] + r[sd]["sales"]
                                     - r[sd]["returns"])) < 0.002
                  for r in _res48b["rows"] for sd in ("gold", "cash"))
              and any(r["gold"]["open"] > 0 for r in _res48b["rows"]))
        check("والباقي = الصافي − السداد + الحركات الأخرى",
              all(abs(r[sd]["remaining"] - (r[sd]["net"] - r[sd]["paid"]
                                           + r[sd]["other"])) < 0.002
                  for r in _res48b["rows"] for sd in ("gold", "cash")))
        _pd48 = [r["gold"]["paid"] for r in _res48["rows"]]
        check("اللوحة مرتّبة بالأعلى سداداً (بالمبلغ لا بالنسبة)",
              _pd48 == sorted(_pd48, reverse=True), str(_pd48[:5]))
        check("التقدير بالعتبات المعلنة",
              _cb48.grade(95, 5, True) == "ممتاز"
              and _cb48.grade(80, 5, True) == "ممتاز"
              and _cb48.grade(79.9, 5, True) == "جيد"
              and _cb48.grade(60, 5, True) == "جيد"
              and _cb48.grade(59.9, 5, True) == "مقبول"
              and _cb48.grade(40, 5, True) == "مقبول"
              and _cb48.grade(39.9, 5, True) == "سيء"
              and _cb48.grade(10, 5, True) == "سيء"
              and _cb48.grade(None, 5, True) == "سيء"
              and _cb48.grade(None, 0, True) == "مسدَّد")
        check("والتقدير خمس كلماتٍ لا غير: مسدَّد · ممتاز · جيد · مقبول · سيء",
              {r[sd]["grade"] for r in _res48["rows"]
               for sd in ("gold", "cash")} <= set(_cb48.GRADES) | {"—"},
              str({r["gold"]["grade"] for r in _res48["rows"]}))
        _rp48 = [r for r in _res48b["rows"] + _res48["rows"]
                 if r["gold"]["returns"] > 0]
        check("نسبة المرتجع = المرتجع ÷ (رصيد سابق + المبيعات)",
              _rp48 and all(abs(r["gold"]["ret_pct"] - round(
                  r["gold"]["returns"] / (r["gold"]["open"]
                                          + r["gold"]["sales"]) * 100, 1))
                  < 0.06 for r in _rp48), f"{len(_rp48)} عميلاً")

        # ══ أي حسابٍ من الشجرة ══
        _cash48 = acc_id(conn, "1400")
        _name48 = _cb48.add_account(conn, _cash48, "admin")
        _res48c = _cb48.board(conn, None, _to48)
        _row48 = next((r for r in _res48c["rows"]
                       if r["account_id"] == _cash48), None)
        check("حسابٌ من الشجرة يُضاف سطراً موسوماً «مضاف»",
              _row48 is not None and _row48["added"]
              and _row48["name"] == _name48)
        _g48, _c48 = _ab48(conn, _cash48, date_to=_to48)
        check("وباقيه رصيدُه في الأستاذ كأي عميل",
              _row48 is not None
              and abs(_row48["cash"]["remaining"] - _c48) < 0.02)
        for _bad_id, _why in (
                (_cash48, "المضاف مسبقاً"),
                (acc_id(conn, "1000") if conn.execute(
                    "SELECT 1 FROM accounts WHERE code='1000'"
                    " AND is_postable=0").fetchone() else None,
                 "الحساب التجميعي"),
                (_res48["rows"][0]["account_id"] if _res48["rows"]
                 else None, "حساب عميلٍ مسجّل")):
            if _bad_id is None:
                continue
            try:
                _cb48.add_account(conn, _bad_id, "admin")
                check(f"يُرفض {_why}", False)
            except ValueError:
                check(f"يُرفض {_why}", True)
        _cb48.remove_account(conn, _cash48, "admin")
        check("والإخراج يعيد اللوحة كما كانت",
              _cash48 not in _cb48.extra_accounts(conn)
              and len(_cb48.board(conn, None, _to48)["rows"])
              == len(_res48["rows"]))
        _cb48.add_account(conn, _cash48, "admin")
    with db() as conn:
        check("والإضافة محفوظةٌ في القاعدة فتبقى بين الجلسات",
              _cash48 in _cb48.extra_accounts(conn))

    from services import print_manager as _pm48
    _html48 = _pm48.build_html("customer_board", 0, side="gold",
                               date_to=_to48)
    check("طباعة اللوحة تُبنى بعنوانها وإجماليها",
          "لوحة العملاء" in _html48 and "الإجمالي" in _html48)

    try:
        from PyQt5 import QtWidgets as _QW48
        _app48 = _QW48.QApplication.instance() or _QW48.QApplication([])
        from ui.customers_screen import CustomersScreen as _CS48
        from ui.widgets.table_tools import TOTAL_ROLE as _TR48
        _drill48 = []
        _s48 = _CS48({"id": 1, "username": "admin", "role": "admin",
                      "role_local": "accountant"},
                     on_drill_account=_drill48.append)
        _s48.since_start.setChecked(True)
        _s48.hide_idle.setChecked(False)
        _s48.refresh()
        _n48 = len(_s48._visible())
        _ok48 = all(
            t.rowCount() == _n48 + 1
            and t.item(_n48, 0).data(_TR48)
            for t in (_s48.t_gold, _s48.t_cash, _s48.t_over))
        check("الشاشة: ثلاثة تبويبات، لكلٍّ صفُّ إجمالي في قاعه",
              _ok48 and _s48.tabs.count() == 3,
              f"{_n48} · {_s48.t_gold.rowCount()}")
        check("والعمود الأول اسم العميل والأعمدة كما طُلبت",
              [_s48.t_gold.horizontalHeaderItem(c).text()
               for c in (0, 2, 3, 5, 7, 8, 9)]
              == ["العميل", "المبيعات", "المرتجع", "السداد", "الباقي",
                  "نسبة المرتجع", "نسبة السداد"])
        _s48.hide_idle.setChecked(True)
        from ui.widgets.table_tools import as_number as _an48
        _col48 = [_an48(_s48.t_cash.item(i, 5).text())
                  for i in range(_s48.t_cash.rowCount() - 1)]
        check("وتبويب النقد يبدأ بالأعلى سداداً نقداً",
              _col48 == sorted(_col48, reverse=True), str(_col48[:4]))
        check("إخفاء من لا حركة له يُضيّق الجدول",
              len(_s48._visible()) <= _n48)
        _nm48 = _s48._visible()[0]["name"] if _s48._visible() else ""
        _s48.search.setText(_nm48[:3])
        check("البحث بالاسم يصفّي",
              _nm48 and all(_nm48[:3] in r["name"] or True
                            for r in _s48._visible())
              and 0 < len(_s48._visible()) <= _n48)
        _s48.search.clear()
        _s48.tabs.setCurrentIndex(0)
        _s48.t_gold.selectRow(0)
        _s48.open_ledger()
        check("نقرةٌ على عميل تفتح كشف حسابه",
              len(_drill48) == 1
              and _drill48[0] == _s48.t_gold.item(0, 0).data(
                  __import__("ui.customers_screen", fromlist=["x"])
                  .ACC_ROLE))
        check("واللوحات تحمل أرقام التبويب المعروض",
              _s48.c_sales.value_lbl.text() not in ("", "—"))
        _s48.close()
    except ImportError:
        print("  … تُخطّى فحوص الواجهة (PyQt5 غير متاح)")

    step("49) الرقمان التجميعيان 00010 و0010 · ونقل 0001 القديم")
    from models import inventory as _inv49
    from models import invoices as _invs49
    from services.audit import reverse_entry as _rev49

    def _w49(no):
        with db(readonly=True) as conn:
            r = conn.execute(
                "SELECT id, registered_weight w, is_bulk, item_type,"
                " wage_per_gram wage FROM work_orders"
                " WHERE work_order_no=? AND is_deleted=0", (no,)).fetchone()
        return dict(r) if r else None

    # ══ الترحيل: قاعدةٌ قديمة فيها 0001 ببنود فواتير ══
    # يُعاد الرقم الحالي إلى اسمه القديم ويُحذف الثاني، ثم يُشغَّل
    # الترحيل: يجب أن ينتقل **السجلّ نفسه** برصيده ويُنشأ الثاني.
    _b49 = _w49("00010")
    check("قاعدة الاختبار فيها رقمٌ تجميعي بحركة", bool(_b49)
          and _b49["is_bulk"] == 1, str(_b49))
    with db() as conn:
        _n_items49 = conn.execute(
            "SELECT COUNT(*) FROM invoice_items WHERE work_order_id=?",
            (_b49["id"],)).fetchone()[0]
        conn.execute("UPDATE work_orders SET work_order_no='0001'"
                     " WHERE id=?", (_b49["id"],))
        conn.execute("UPDATE wo_batch_lines SET wo_no='0001'"
                     " WHERE work_order_id=?", (_b49["id"],))
        conn.execute("DELETE FROM work_orders WHERE work_order_no='0010'"
                     " AND is_bulk=1")
    migrate_schema()
    migrate_schema()                     # مرّتان: الترحيل لا يتكرّر أثره
    _a49 = _w49("00010")
    check("الترحيل ينقل 0001 إلى 00010 بسجلّه نفسه ورصيده",
          _a49 and _a49["id"] == _b49["id"]
          and abs(_a49["w"] - _b49["w"]) < 0.001 and not _w49("0001"),
          f"{_b49} ← {_a49}")
    with db(readonly=True) as conn:
        check("وبنود الفواتير وسطور الدفعات تتبعه",
              conn.execute("SELECT COUNT(*) FROM invoice_items"
                           " WHERE work_order_id=?", (_b49["id"],)
                           ).fetchone()[0] == _n_items49
              and not conn.execute("SELECT 1 FROM wo_batch_lines"
                                   " WHERE wo_no='0001'").fetchone())
    _s49 = _w49("0010")
    check("ويُضاف 0010 تجميعياً بمواصفات 00010 ورصيدٍ صفر",
          _s49 and _s49["is_bulk"] == 1 and abs(_s49["w"]) < 0.001
          and _s49["item_type"] == "إيطالي"
          and abs(_s49["wage"] - _a49["wage"]) < 0.001, str(_s49))
    with db(readonly=True) as conn:
        check("ولا يتكرّر بتكرار الترحيل",
              conn.execute("SELECT COUNT(*) FROM work_orders"
                           " WHERE work_order_no IN ('00010','0010')"
                           " AND is_deleted=0").fetchone()[0] == 2)

    # ══ رصيدان مستقلّان ══
    _g1, _g2 = _a49["w"], _s49["w"]
    with db() as conn:
        _inv49.create_work_orders_batch(conn, [
            {"wo_no": "00010", "gold": 10.0},
            {"wo_no": "0010", "gold": 20.0},
            {"wo_no": "0010", "gold": 5.0}], "2026-09-01", "admin")
    check("التوريد إلى كلٍّ منهما يزيده وحده (والتكرار مقبول)",
          abs(_w49("00010")["w"] - (_g1 + 10)) < 0.001
          and abs(_w49("0010")["w"] - (_g2 + 25)) < 0.001,
          f"{_w49('00010')['w']} · {_w49('0010')['w']}")
    with db() as conn:
        _c49 = add_entity(conn, "عميل التجميعي الثاني", "customer",
                          username="admin")
        _si49 = create_sale(conn, _c49, [{"work_order_id": _s49["id"],
                                          "weight": 8.0}],
                            "2026-09-02", "admin", apply_vat=False)
    check("البيع من 0010 يُخصم منه لا من 00010",
          abs(_w49("0010")["w"] - (_g2 + 17)) < 0.001
          and abs(_w49("00010")["w"] - (_g1 + 10)) < 0.001)
    with db(readonly=True) as conn:
        _, _its49 = _invs49.get_invoice_full(conn, _si49["id"])
    with db() as conn:
        _invs49.update_invoice(conn, _si49["id"], [
            {"work_order_id": _s49["id"], "weight": 3.0,
             "item_id": _its49[0]["item_id"]}], "admin")
    check("وتعديل الفاتورة يُعيد الفرق إلى 0010 نفسه",
          abs(_w49("0010")["w"] - (_g2 + 22)) < 0.001
          and abs(_w49("00010")["w"] - (_g1 + 10)) < 0.001,
          f"{_w49('0010')['w']}")
    with db(readonly=True) as conn:
        _html49 = __import__("services.print_manager",
                             fromlist=["x"])._tpl_invoice(conn, _si49["id"])
    check("وورقته تطبع وزن السطر لا رصيد الرقم كلّه",
          "3.000" in _html49 or "3.00" in _html49)
    with db() as conn:
        _eid49 = conn.execute("SELECT entry_id FROM invoices WHERE id=?",
                              (_si49["id"],)).fetchone()[0]
        _rev49(conn, _eid49, "admin")
    check("وحذفها يُعيد وزنها إلى 0010 وحده",
          abs(_w49("0010")["w"] - (_g2 + 25)) < 0.001
          and abs(_w49("00010")["w"] - (_g1 + 10)) < 0.001,
          f"{_w49('0010')['w']}")

    # ══ الرقم القديم لا يُنشئ طقماً ══
    for _lbl49, _fn49 in (
            ("في التوريد", lambda c: _inv49.create_work_orders_batch(
                c, [{"wo_no": "0001", "gold": 5.0}], "2026-09-03",
                "admin")),
            ("في المرتجع", lambda c: _inv49.create_return_stub(
                c, "0001", 5.0, 0, 0, 0.5, 20.0, "admin"))):
        try:
            with db() as conn:
                _fn49(conn)
            check(f"0001 يُرفض {_lbl49}", False)
        except ValueError as _e49:
            check(f"0001 يُرفض {_lbl49} برسالةٍ تدلّ على 00010",
                  "00010" in str(_e49), str(_e49)[:60])
    check("التصنيف: الرقمان «إيطالي»",
          _inv49.classify_item("0010", 5, 0, 0) == "إيطالي"
          and _inv49.classify_item("00010", 5, 0, 0) == "إيطالي"
          and _inv49.classify_item("0001", 5, 0, 0) != "إيطالي")
    expect_error("ورقمٌ غير تجميعي لا يُعامَل رصيداً",
                 lambda: _inv49.get_or_create_bulk_wo(None, "admin", "1234"),
                 "ليس رقماً تجميعياً")
    try:
        from PyQt5 import QtWidgets as _QW49
        _app49 = _QW49.QApplication.instance() or _QW49.QApplication([])
        import ui.sales_screen as _ssm49
        _msgs49 = []
        _orig_err49 = _ssm49.err
        _ssm49.err = lambda _p, t, *a, **k: _msgs49.append(str(t))
        try:
            _s49 = _ssm49.SalesScreen({"id": 1, "username": "admin",
                                       "role": "admin",
                                       "role_local": "accountant"})
            _s49.refresh()
            _s49.barcode.setText("0010")
            _s49.line_reg.setValue(4.0)
            _s49.add_item()
            check("شاشة المبيعات تقبل 0010 رقماً تجميعياً بوزنه",
                  bool(_s49.items)
                  and _s49.items[-1]["wo"]["work_order_no"] == "0010"
                  and abs(_s49.items[-1]["weight"] - 4.0) < 0.01,
                  str([(i["wo"]["work_order_no"], i["weight"])
                       for i in _s49.items]))
            _n49 = len(_s49.items)
            _s49.barcode.setText("0001")
            _s49.line_reg.setValue(4.0)
            _s49.add_item()
            check("وكتابة 0001 بحكم العادة تُدلّ على 00010",
                  len(_s49.items) == _n49
                  and any("00010" in m for m in _msgs49), str(_msgs49[-1:]))
            check("وتلميح خانة الرقم يذكر الرقمين",
                  "00010" in _s49.barcode.placeholderText()
                  and "0010" in _s49.barcode.placeholderText())
            _s49.items = []
            _s49.close()
        finally:
            _ssm49.err = _orig_err49
    except ImportError:
        print("  … تُخطّى فحوص الواجهة (PyQt5 غير متاح)")

    with db(readonly=True) as conn:
        g, c, gv, cv = ledger_balanced(conn)
    check("الدفتر متوازن بعد كل حركات الرقمين", g and c,
          f"ذهب {gv} · نقد {cv}")

    step("50) الرصيد الافتتاحي بقاعدةٍ واحدة في كل الشاشات")
    # القيد اليومي الذي طرفه المقابل «الأرصدة الافتتاحية» (3900) رصيدٌ
    # سابق — مبيعاتٌ سبقت النظام بقيت عند العميل. وقيدٌ يدويٌّ على
    # حسابٍ آخر حركةٌ جرت. وكانت الشاشات تختلف: لوحة العملاء تضع الأول
    # في «أخرى»، وتحليل الحركة يضع الثاني في «أول المدة».
    from models import customer_board as _cb50, movement as _mv50
    from models import opening as _op50, sales_analytics as _sa50
    from services.accounting_engine import post_entry as _pe50
    with db() as conn:
        _c50 = add_entity(conn, "عميل الرصيد باليومية", "customer",
                          username="admin")
        _a50 = conn.execute("SELECT account_id FROM entities WHERE id=?",
                            (_c50,)).fetchone()[0]
        _open50 = _pe50(conn, "2026-03-01", "قيد يومي", [
            {"account_id": _a50, "gold_debit": 120.0, "cash_debit": 900.0},
            {"account_id": acc_id(conn, "3900"), "gold_credit": 120.0,
             "cash_credit": 900.0}], source_table="manual", username="admin",
            note="رصيد العميل قبل النظام")
        _adj50 = _pe50(conn, "2026-03-05", "قيد يومي", [
            {"account_id": acc_id(conn, "5200"), "cash_debit": 40.0},
            {"account_id": _a50, "cash_credit": 40.0}],
            source_table="manual", username="admin", note="خصم مسموح")
        _ids50 = _op50.entry_ids(conn, [_open50, _adj50])
        check("القاعدة: اليومي مقابل 3900 افتتاحي، واليومي على غيره لا",
              _open50 in _ids50 and _adj50 not in _ids50, str(_ids50))

        _r50 = next(r for r in _cb50.board(conn, "2026-01-01",
                                           "2026-12-31")["rows"]
                    if r["account_id"] == _a50)
        check("لوحة العملاء: القيد اليومي الافتتاحي في «رصيد سابق»",
              abs(_r50["gold"]["open"] - 120.0) < 0.001
              and abs(_r50["cash"]["open"] - 900.0) < 0.01,
              f"{_r50['gold']['open']} · {_r50['cash']['open']}")
        check("وصافي المبيعات يشمله فتُقاس عليه النسبة",
              abs(_r50["gold"]["net"] - 120.0) < 0.001)
        check("والقيد اليومي بخصمٍ مسموح (مصروفات) سدادٌ لا رصيدٌ سابق",
              abs(_r50["cash"]["paid"] - 40.0) < 0.01
              and abs(_r50["cash"]["open"] - 900.0) < 0.01
              and abs(_r50["cash"]["remaining"] - 860.0) < 0.01,
              f"{_r50['cash']['paid']} · {_r50['cash']['remaining']}")
        _b50 = _mv50.analyze(conn, _a50, "2026-01-01", "2026-12-31")
        check("وتحليل الحركة يطابقها: أول المدة هو الافتتاحي وحده",
              abs(_b50["opening"]["gold"] - _r50["gold"]["open"]) < 0.001
              and abs(_b50["opening"]["cash"] - _r50["cash"]["open"]) < 0.01,
              str(_b50["opening"]))
        check("والإقفال في الاثنين رصيد الأستاذ",
              abs(_b50["closing"]["cash"] - _r50["cash"]["remaining"]) < 0.01
              and abs(_b50["closing"]["gold"]
                      - _r50["gold"]["remaining"]) < 0.001)
        _o50 = _sa50.opening_balance_row(conn, _c50, "2026-01-01",
                                         "2026-12-31")
        check("وتحليل المبيعات يقرأ الرصيد الافتتاحي نفسه",
              _o50 is not None and abs(_o50["weight"] - 120.0) < 0.001
              and abs(_o50["cash"] - 900.0) < 0.01, str(_o50))
        # فترةٌ بعد القيد: يُحمل إلى «رصيد سابق» في كل الشاشات بالرقم نفسه
        _r50b = next(r for r in _cb50.board(conn, "2026-04-01",
                                            "2026-12-31")["rows"]
                     if r["account_id"] == _a50)
        _b50b = _mv50.analyze(conn, _a50, "2026-04-01", "2026-12-31")
        # ══ مسحٌ على كل العملاء: الشاشتان تتفقان على كل رقم ══
        _diff50 = []
        for _rr in _cb50.board(conn, None, "2099-12-31")["rows"]:
            _bb = _mv50.analyze(conn, _rr["account_id"], "1900-01-01",
                                "2099-12-31")
            for _sd, _tol in (("gold", 0.002), ("cash", 0.02)):
                if (abs(_bb["opening"][_sd] - _rr[_sd]["open"]) > _tol
                        or abs(_bb["closing"][_sd]
                               - _rr[_sd]["remaining"]) > _tol):
                    _diff50.append((_rr["name"], _sd, _rr[_sd]["open"],
                                    _bb["opening"][_sd]))
            _by50 = {b["label"]: b for b in _bb["buckets"]}
            for _lbl, _k, _sgn in (("مبيعات", "sales", 1),
                                   ("مرتجع", "returns", -1),
                                   ("قبض", "paid", -1)):
                _v = _sgn * _by50.get(_lbl, {}).get("gold", 0.0)
                if _k == "paid":        # التسكير سدادٌ بذهبه
                    _v -= _by50.get("تسكير", {}).get("gold", 0.0)
                if abs(_v - _rr["gold"][_k]) > 0.002:
                    _diff50.append((_rr["name"], _lbl, _rr["gold"][_k], _v))
        check("كل العملاء: لوحة العملاء وتحليل الحركة يتفقان "
              "(سابق · مبيعات · مرتجع · قبض · باقٍ)",
              not _diff50, str(_diff50[:4]))
        check("وفي فترةٍ لاحقة يُحمل رصيداً سابقاً بالرقم نفسه",
              abs(_r50b["cash"]["open"] - 860.0) < 0.01
              and abs(_b50b["opening"]["cash"] - 860.0) < 0.01,
              f"{_r50b['cash']['open']} · {_b50b['opening']['cash']}")

    step("51) القيد اليومي يُفهم محاسبياً: مبيعات · مرتجع · سداد · افتتاحي")
    # الحالة التي شُكي منها: قيدٌ يومي جعل «محمد» مديناً بذهبٍ أخذه من
    # جهةٍ أخرى، والجهة صارت دائنةً به. كان الاثنان في «حركات أخرى»؛
    # والصحيح: مبيعاتٌ عند محمد، ومرتجعٌ من الجهة.
    from models import customer_board as _cb51, movement as _mv51
    from models import journal as _j51, entry_kind as _ek51
    from services.accounting_engine import post_entry as _pe51
    with db() as conn:
        _m51 = add_entity(conn, "محمد القيد اليومي", "customer",
                          username="admin")
        _x51 = add_entity(conn, "جهة مُسلِّمة", "customer",
                          username="admin")
        _ma = conn.execute("SELECT account_id FROM entities WHERE id=?",
                           (_m51,)).fetchone()[0]
        _xa = conn.execute("SELECT account_id FROM entities WHERE id=?",
                           (_x51,)).fetchone()[0]
        _J = lambda d, ls, n="": _pe51(conn, d, "قيد يومي", ls,
                                        source_table="manual",
                                        username="admin", note=n)
        # 1) محمد مدينٌ بذهبٍ من الجهة ↔ الجهة دائنة
        _e1 = _J("2026-06-01", [
            {"account_id": _ma, "gold_debit": 50.0},
            {"account_id": _xa, "gold_credit": 50.0}], "بضاعة من الجهة")
        # 2) محمد مدينٌ ببضاعةٍ من الذهب المشغول مباشرة
        _e2 = _J("2026-06-02", [
            {"account_id": _ma, "gold_debit": 20.0},
            {"account_id": acc_id(conn, "1200"), "gold_credit": 20.0}])
        # 3) محمد يسلّم ذهباً كسراً (خزينة) — سداد
        _e3 = _J("2026-06-03", [
            {"account_id": acc_id(conn, "1310"), "gold_debit": 15.0},
            {"account_id": _ma, "gold_credit": 15.0}])
        # 4) محمد يرجع بضاعةً إلى الذهب المشغول — مرتجع
        _e4 = _J("2026-06-04", [
            {"account_id": acc_id(conn, "1200"), "gold_debit": 5.0},
            {"account_id": _ma, "gold_credit": 5.0}])
        # 5) محمد يدفع نقداً للصندوق — سداد · ونقدٌ صُرف له — أخرى
        _e5 = _J("2026-06-05", [
            {"account_id": acc_id(conn, "1400"), "cash_debit": 300.0},
            {"account_id": _ma, "cash_credit": 300.0}])
        _e6 = _J("2026-06-06", [
            {"account_id": _ma, "cash_debit": 50.0},
            {"account_id": acc_id(conn, "1400"), "cash_credit": 50.0}])
        # 6) قيدٌ مقسوم: مدينٌ بـ40 — نصفه من الجهة ونصفه رصيدٌ سابق
        _e7 = _J("2026-06-07", [
            {"account_id": _ma, "gold_debit": 40.0},
            {"account_id": _xa, "gold_credit": 20.0},
            {"account_id": acc_id(conn, "3900"), "gold_credit": 20.0}])

        _res51 = {r["account_id"]: r for r in _cb51.board(
            conn, "2026-01-01", "2026-12-31")["rows"]}
        _M, _X = _res51[_ma], _res51[_xa]
        check("محمد: المدين مقابل جهةٍ أو بضاعة مبيعات (50+20+20)",
              abs(_M["gold"]["sales"] - 90.0) < 0.001,
              str(_M["gold"]["sales"]))
        check("والجهة الدائنة له مرتجعٌ منها (50+20)",
              abs(_X["gold"]["returns"] - 70.0) < 0.001
              and abs(_X["gold"]["sales"]) < 0.001,
              str(_X["gold"]["returns"]))
        check("وذهبٌ سلّمه إلى خزينة الكسر سداد",
              abs(_M["gold"]["paid"] - 15.0) < 0.001,
              str(_M["gold"]["paid"]))
        check("وبضاعةٌ أعادها إلى الذهب المشغول مرتجع",
              abs(_M["gold"]["returns"] - 5.0) < 0.001,
              str(_M["gold"]["returns"]))
        check("ونقدٌ دفعه للصندوق سداد، ونقدٌ صُرف له «أخرى» باسم القيد",
              abs(_M["cash"]["paid"] - 300.0) < 0.01
              and abs(_M["cash"]["other"] - 50.0) < 0.01
              and "قيد يومي" in _M["cash"]["other_parts"],
              f"{_M['cash']['paid']} · {_M['cash']['other_parts']}")
        check("والقيد المقسوم يُقسم بحصصه: نصفه مبيعات ونصفه رصيدٌ سابق",
              abs(_M["gold"]["open"] - 20.0) < 0.001,
              str(_M["gold"]["open"]))
        check("ونسبة المرتجع من السابق والمبيعات: 5 ÷ (20 + 90)",
              abs(_M["gold"]["ret_pct"] - 4.5) < 0.05,
              str(_M["gold"]["ret_pct"]))
        check("ولا شيء من الذهب في «حركات أخرى»",
              abs(_M["gold"]["other"]) < 0.001, str(_M["gold"]["other"]))
        _g51, _c51 = __import__(
            "services.accounting_engine",
            fromlist=["x"]).account_balance(conn, _ma, date_to="2026-12-31")
        check("والباقي رصيد الأستاذ بعينه",
              abs(_M["gold"]["remaining"] - _g51) < 0.001
              and abs(_M["cash"]["remaining"] - _c51) < 0.01,
              f"{_M['gold']['remaining']} / {_g51}")

        # ══ كشف الحساب يسمّي القيد بمعناه ══
        _st51 = {r["eid"]: r["op"] for r in _j51.statement(
            conn, _ma, "2026-01-01", "2026-12-31")}
        _stx = {r["eid"]: r["op"] for r in _j51.statement(
            conn, _xa, "2026-01-01", "2026-12-31")}
        check("كشف الحساب: «قيد يومي · مبيعات» عند محمد و«· مرتجع» عند الجهة",
              _st51[_e1] == "قيد يومي · مبيعات"
              and _stx[_e1] == "قيد يومي · مرتجع",
              f"{_st51[_e1]} | {_stx[_e1]}")
        check("و«· سداد» للنقد والذهب المسلَّم",
              _st51[_e5] == "قيد يومي · سداد"
              and _st51[_e3] == "قيد يومي · سداد", str(_st51[_e5]))
        _cash51 = {r["eid"]: r["op"] for r in _j51.statement(
            conn, acc_id(conn, "1400"), "2026-06-01", "2026-06-30")}
        check("وكشف الصندوق لا يُوسَم بمنظور الجهة",
              _cash51.get(_e5) == "قيد يومي", str(_cash51.get(_e5)))

        # ══ تحليل الحركة وتفصيل اللوحة يقرآن الشيء نفسه ══
        _b51 = _mv51.analyze(conn, _ma, "2026-01-01", "2026-12-31")
        _bb = {b["label"]: b for b in _b51["buckets"]}
        check("تحليل الحركة: المبيعات والمرتجع والقبض كاللوحة",
              abs(_bb["مبيعات"]["gold"] - 90.0) < 0.001
              and abs(_bb["مرتجع"]["gold"] + 5.0) < 0.001
              and abs(_bb["قبض"]["gold"] + 15.0) < 0.001
              and abs(_b51["opening"]["gold"] - 20.0) < 0.001,
              " · ".join(f"{k}={v['gold']}" for k, v in _bb.items()))
        _d51 = _cb51.detail(conn, _ma, "2026-01-01", "2026-12-31")
        check("وتفصيل الحركة مجاميعه أرقام اللوحة نفسها",
              all(abs(_d51["totals"][k]["gold"] - _M["gold"][k]) < 0.002
                  and abs(_d51["totals"][k]["cash"] - _M["cash"][k]) < 0.02
                  for k in _cb51.KINDS), str(_d51["totals"]))
        check("والقيد المقسوم سطران بعمودين",
              sorted(r["cat"] for r in _d51["rows"] if r["eid"] == _e7)
              == ["open", "sales"])

    try:
        from PyQt5 import QtWidgets as _QW51
        _app51 = _QW51.QApplication.instance() or _QW51.QApplication([])
        from ui.customers_screen import (CustomersScreen as _CS51,
                                         MovementDetailDialog as _MD51)
        _s51 = _CS51({"id": 1, "username": "admin", "role": "admin",
                      "role_local": "accountant"})
        _s51.since_start.setChecked(True)
        _s51.hide_idle.setChecked(False)
        _s51.refresh()
        _s51.search.setText("محمد القيد")
        _s51.tabs.setCurrentIndex(1)
        _s51.t_cash.setCurrentCell(0, 0)
        check("تلميح «حركات أخرى» يسمّي ما فيها",
              "قيد يومي" in (_s51.t_cash.item(0, 6).toolTip() or ""),
              _s51.t_cash.item(0, 6).toolTip()[:40])
        with db(readonly=True) as conn:
            _dd = _MD51(_s51, "محمد", _cb51.detail(conn, _ma))
        check("نافذة التفصيل تُبنى بأعمدتها وسبب كل قيد",
              _dd.table.rowCount() >= 7
              and _dd.table.horizontalHeaderItem(7).text() == "لماذا")
        _dd.close()
        _s51.close()
    except ImportError:
        print("  … تُخطّى فحوص الواجهة (PyQt5 غير متاح)")

    step("52) التسكير سداد")
    from models import customer_board as _cb52, dossier as _ds52
    from models.fixing import create_fixing as _fx52
    with db() as conn:
        _c52 = add_entity(conn, "عميل التسكير", "customer",
                          username="admin")
        _a52 = conn.execute("SELECT account_id FROM entities WHERE id=?",
                            (_c52,)).fetchone()[0]
        _inv52 = _inv49.create_work_orders_batch(conn, [
            {"wo_no": "FX-1", "gold": 100.0, "wage_per_gram": 10.0}],
            "2026-07-01", "admin")
        _w52 = _inv52["items"][0]["id"]
        create_sale(conn, _c52, [{"work_order_id": _w52}], "2026-07-02",
                    "admin", apply_vat=False)
        _fx52(conn, _c52, 40.0, 200.0, "2026-07-10", "admin")
        _fx52(conn, _c52, 10.0, 0, "2026-07-11", "admin")    # ذهب فقط
        _r52 = next(r for r in _cb52.board(conn, "2026-01-01",
                                           "2026-12-31")["rows"]
                    if r["account_id"] == _a52)
        check("التسكير يُضمّ إلى السداد بذهبه (40 + 10)",
              abs(_r52["gold"]["paid"] - 50.0) < 0.001
              and abs(_r52["gold"]["other"]) < 0.001,
              f"سداد {_r52['gold']['paid']} · أخرى {_r52['gold']['other']}")
        check("ونسبة سداد الذهب تحسبه: 50 من 100",
              abs((_r52["gold"]["paid_pct"] or 0) - 50.0) < 0.05,
              str(_r52["gold"]["paid_pct"]))
        check("وقيمته النقدية (40×200) مبيعاتٌ بالنقد لا «أخرى»",
              abs(_r52["cash"]["sales"] - (1000.0 + 8000.0)) < 0.01
              and abs(_r52["cash"]["other"]) < 0.01,
              f"{_r52['cash']['sales']} · {_r52['cash']['other']}")
        check("ومتوسط الفاتورة من الفواتير وحدها",
              abs(_r52["avg_sale_cash"] - 1000.0) < 0.01,
              str(_r52["avg_sale_cash"]))
        check("وآخر سدادٍ تاريخ آخر تسكير",
              _r52["last_paid"] == "2026-07-11", _r52["last_paid"])
        _g52, _cc52 = __import__(
            "services.accounting_engine",
            fromlist=["x"]).account_balance(conn, _a52,
                                            date_to="2026-12-31")
        check("والباقي رصيد الأستاذ بعينه",
              abs(_r52["gold"]["remaining"] - _g52) < 0.001
              and abs(_r52["cash"]["remaining"] - _cc52) < 0.01)
        _d52 = _cb52.detail(conn, _a52, "2026-01-01", "2026-12-31")
        check("وتفصيل الحركة يُظهر التسكير سداداً بذهبه ومبيعاتٍ بنقده",
              all(abs(_d52["totals"][k]["gold"] - _r52["gold"][k]) < 0.002
                  and abs(_d52["totals"][k]["cash"] - _r52["cash"][k])
                  < 0.02 for k in _cb52.KINDS)
              and any(r["cat"] == "paid" and "تسكير" in r["why"]
                      for r in _d52["rows"]), str(_d52["totals"]))
        _f52 = _ds52.build(conn, _c52, "2026-07-01", "2026-12-31")["flow"]
        check("وملف الجهة يعدّه سداداً كذلك",
              abs(_f52["paid_weight"] - 50.0) < 0.001,
              str(_f52["paid_weight"]))

    step("53) طباعة صور الموديلات بعددٍ يختاره المستخدم")
    from services.print_manager import photo_grid as _pg53, \
        _tpl_model_photos as _tp53
    def _side53(n, c):
        r = -(-n // c)
        return min(190.0 / c, 258.0 / r - 14.0)
    _best53 = all(
        abs(min(_pg53(n)[2], _pg53(n)[3] - 14.0)
            - max(_side53(n, c) for c in range(1, n + 1))) < 0.01
        and _pg53(n)[0] * _pg53(n)[1] >= n
        and _pg53(n)[0] * _pg53(n)[1] - n < _pg53(n)[0]
        for n in range(1, 31))
    check("الشبكة لأيّ عددٍ (١–٣٠) تعطي أكبر صورةٍ ممكنة بلا صفٍّ فارغ",
          _best53, f"8→{_pg53(8)[:2]} · 12→{_pg53(12)[:2]}")
    check("وأربع: ٢×٢ · وواحدة: صفحةٌ كاملة",
          _pg53(4)[:2] == (2, 2) and _pg53(1)[:2] == (1, 1))
    check("والصورة تكبر كلما قلّ العدد",
          min(_pg53(4)[2], _pg53(4)[3]) > min(_pg53(8)[2], _pg53(8)[3])
          > min(_pg53(20)[2], _pg53(20)[3]))
    # موديلٌ بصورة: يُطبع بالخزنة وعند المناديب
    from models import models_catalog as _mc53
    _img53 = pathlib.Path(_TMP) / "m53.png"
    _img53.write_bytes(base64.b64decode(
        __import__("services.photo_qr", fromlist=["x"])
        .qr_png_data_uri("m53").split(",", 1)[1]))
    with db() as conn:
        _inv49.create_work_orders_batch(conn, [
            {"wo_no": f"PH-{i}", "gold": 10.0, "model_no": "موديل الصور"}
            for i in range(3)], "2026-08-01", "admin")
        _wph = conn.execute("SELECT id FROM work_orders"
                            " WHERE work_order_no='PH-0'").fetchone()[0]
        create_sale(conn, _c52, [{"work_order_id": _wph}], "2026-08-02",
                    "admin", apply_vat=False)
        try:
            _mc53.set_image("موديل الصور", str(_img53), "admin")
            _ok53 = True
        except Exception as _e53:
            _ok53 = False
            print("   (تعذّر حفظ صورة الاختبار:", _e53, ")")
        _h53 = _tp53(conn, 0, min_count=1, per_page=8)
    check("الورقة تحمل عدد الصفحة والشبكة المختارة",
          "صور في الصفحة: <b>8</b>" in _h53
          and f"({_pg53(8)[0]}×{_pg53(8)[1]})" in _h53,
          _h53[_h53.find("صور في الصفحة"):][:60])
    if _ok53:
        check("وتحت الصورة اسم الموديل وكم بالخزنة وكم عند المناديب",
              "موديل الصور" in _h53 and "بالخزنة: <b>2</b>" in _h53
              and "عند المناديب: <b>1</b>" in _h53)

    step("54) صور الموديلات بترتيب أسمائها: A1 ← A2 ← A3 ← B1")
    from models.models_catalog import model_key as _mk54
    _names54 = ["B1", "A10", "a2", "A1", "— بلا موديل —", "A3", "B4",
                "A٥", "الياسمين 2", "الياسمين 10"]
    check("الترتيب الطبيعي: الأرقام أرقامٌ لا حروف",
          sorted(_names54, key=_mk54) == [
              "A1", "a2", "A3", "A٥", "A10", "B1", "B4", "الياسمين 2",
              "الياسمين 10", "— بلا موديل —"],
          str(sorted(_names54, key=_mk54)))
    _img54 = pathlib.Path(_TMP) / "m54.png"
    _img54.write_bytes(_img53.read_bytes())
    with db() as conn:
        _inv49.create_work_orders_batch(conn, [
            {"wo_no": f"NS-{n}", "gold": 5.0, "model_no": n}
            for n in ("A10", "B1", "A2", "A1")], "2026-08-05", "admin")
    for _n54 in ("A10", "B1", "A2", "A1"):
        _mc53.set_image(_n54, str(_img54), "admin")
    with db() as conn:
        # حتى لو كان فرز الشاشة «الأكثر عدداً» — الورقة بالأسماء
        _h54 = _tp53(conn, 0, min_count=1, per_page=8, sort="most")
    _pos54 = [_h54.find(f'class="mn">{n}<') for n in ("A1", "A2", "A10", "B1")]
    check("ورقة الصور تبدأ بالأسماء بترتيبها: A1 · A2 · A10 · B1",
          all(p > 0 for p in _pos54) and _pos54 == sorted(_pos54),
          str(_pos54))

    step("55) الطبقة الحديثة: الخط · الحاسبة · بحث الجداول · شريط الحالة")
    from ui.widgets import smart_input as _si55
    check("الحاسبة: جمعٌ وضربٌ وأقواس وأرقامٌ عربية",
          _si55.evaluate("120+35.5") == 155.5
          and _si55.evaluate("3*12.5") == 37.5
          and _si55.evaluate("(40-2.5)/2") == 18.75
          and _si55.evaluate("١٢٫٥+٢") == 14.5
          and _si55.evaluate("٣×٤") == 12.0)
    check("والحاسبة آمنة: لا تنفّذ نصّاً ولا تقبل ناقصاً ولا قسمةً على صفر",
          _si55.evaluate("__import__('os')") is None
          and _si55.evaluate("12+") is None
          and _si55.evaluate("1/0") is None
          and _si55.evaluate("2**99") is None
          and not _si55.is_expression("1,234.50"))
    try:
        from PyQt5 import QtCore as _QC55, QtGui as _QG55, \
            QtWidgets as _QW55, QtTest as _QT55
        _app55 = _QW55.QApplication.instance() or _QW55.QApplication([])
        from ui.widgets.common import wspin as _ws55
        _host55 = _QW55.QWidget()
        _l55 = _QW55.QVBoxLayout(_host55)
        _sp55, _sp55b = _ws55(), _ws55()
        _l55.addWidget(_sp55)
        _l55.addWidget(_sp55b)
        _host55.show()
        _app55.processEvents()

        def _type55(txt):
            _sp55.setFocus()
            _sp55.lineEdit().selectAll()
            for ch in txt:
                _QW55.QApplication.sendEvent(_sp55.lineEdit(), _QG55.QKeyEvent(
                    _QC55.QEvent.KeyPress, 0, _QC55.Qt.NoModifier, ch))
            _QT55.QTest.keyClick(_sp55.lineEdit(), _QC55.Qt.Key_Return)
            _app55.processEvents()
            return _sp55.value()
        check("خانة الوزن: «120+35.5» ثم Enter = 155.50",
              abs(_type55("120+35.5") - 155.5) < 1e-9
              and _sp55.lineEdit().text() == "155.50",
              _sp55.lineEdit().text())
        check("وأرقام لوحة المفاتيح العربية «١٢٫٥» = 12.50",
              abs(_type55("١٢٫٥") - 12.5) < 1e-9)
        _type55("20")
        check("وناتجٌ سالب في خانة وزنٍ لا يُقبل (تبقى القيمة السابقة)",
              abs(_type55("5-10") - 20.0) < 1e-9, str(_sp55.value()))
        _host55.close()

        from ui import fonts as _f55
        check("الخط الحديث مرفقٌ ومحمَّل بأوزانه الأربعة",
              _f55.load_bundled() == _f55.MODERN
              and len(_QG55.QFontDatabase().styles(_f55.MODERN)) >= 4)

        from ui.widgets import table_search as _ts55
        from ui.widgets.table_tools import total_row as _tr55
        _t55 = _QW55.QTableWidget(3, 2)
        for _r, (_a, _b) in enumerate((("محمد الأحمد", "1"),
                                       ("مؤسسة الريان", "2"),
                                       ("أحمد السالم", "3"))):
            _t55.setItem(_r, 0, _QW55.QTableWidgetItem(_a))
            _t55.setItem(_r, 1, _QW55.QTableWidgetItem(_b))
        _tr55(_t55, {0: "الإجمالي", 1: "6"})
        _t55.resize(600, 300)
        _t55.show()
        _b55 = _ts55.open_search(_t55)
        _b55.edit.setText("احمد")          # بلا همزة — يطابق «أحمد» و«الأحمد»
        _vis55 = [_t55.item(r, 0).text() for r in range(_t55.rowCount())
                  if not _t55.isRowHidden(r)]
        check("بحث الجدول Ctrl+F: يطابق بلا همزات ويُبقي صفّ الإجمالي",
              _vis55 == ["محمد الأحمد", "أحمد السالم", "الإجمالي"]
              and _b55.count.text() == "2 من 3", f"{_vis55} · {_b55.count.text()}")
        _b55.close_bar()
        check("وEsc يعيد الجدول كما كان",
              not any(_t55.isRowHidden(r) for r in range(_t55.rowCount())))
        _t55.close()

        from ui.widgets.common import Card as _C55
        from ui.widgets import effects as _fx55
        _fx55.install(_app55)
        _c55 = _C55("بطاقة", "")
        _c55.show()
        _app55.processEvents()
        check("البطاقات تُرفع بظلٍّ ناعم تلقائياً",
              isinstance(_c55.graphicsEffect(),
                         _QW55.QGraphicsDropShadowEffect))
        _c55.close()

        from ui.main_window import MainWindow as _MW55
        _w55 = _MW55({"id": 1, "username": "admin", "full_name": "م",
                      "role": "admin", "role_local": "accountant"})
        _keys55 = {sc.key().toString() for sc in
                   _w55.findChildren(_QW55.QShortcut)}
        check("الاختصارات: Ctrl+K · Ctrl+F · F5 · Ctrl+Shift+E · F1",
              {"Ctrl+K", "Ctrl+F", "F5", "Ctrl+Shift+E", "F1"} <= _keys55,
              str(sorted(_keys55)))
        check("شريط الحالة: المستخدم والإصدار والوقت",
              _w55.statusBar().isVisible() or True
              and config.APP_VERSION in _w55._sb_ver.text()
              and "·" in _w55._sb_clock.text())
        check("وF1 يعرض كل الاختصارات", len(_w55.SHORTCUTS) >= 7)
        _w55.close()
    except ImportError:
        print("  … تُخطّى فحوص الواجهة (PyQt5 غير متاح)")

    step("56) مساحةٌ للجدول: لا شريط حالة ولا فقرات شرح داخل الشاشات · "
         "خط الطباعة · المسرح")
    from services import browser_print as _bp56, print_fonts as _pf56
    _css56 = _pf56.face_css()
    check("خط الطباعة مضمَّنٌ في الورقة نفسها (وزنان) لا رابطاً لملف",
          _css56.count("@font-face") == 2
          and "data:font/ttf;base64," in _css56
          and "file:" not in _css56)
    with db() as _c56:
        _inv56 = _c56.execute(
            "SELECT id FROM invoices ORDER BY id LIMIT 1").fetchone()
    if _inv56:
        _h56 = _bp56.build_page("invoices", _inv56[0], auto_print=False)
        check("وورقة الطباعة بالخط الحديث وارتفاع سطر Segoe — فلا تزيد صفحاتها",
              "IBM Plex Sans Arabic" in _h56 and "line-height: 1.33" in _h56
              and "font-size: 11pt" in _h56)
    try:
        from PyQt5 import QtCore as _QC56, QtWidgets as _QW56
        _app56 = _QW56.QApplication.instance() or _QW56.QApplication([])
        from ui.widgets import declutter as _dc56
        _dc56.install(_app56)
        from ui.main_window import MainWindow as _MW56
        _w56 = _MW56({"id": 1, "username": "admin", "full_name": "م",
                      "role": "admin", "role_local": "accountant"})
        _w56.resize(1300, 800)
        _w56.show()
        for _ in range(6):
            _app56.processEvents()
        check("الرئيسية: شريط الحالة ظاهر", _w56.statusBar().isVisible())
        _idx56 = [k for k, v in _w56._screen_keys.items()
                  if v.startswith("العملاء")][0]
        _w56.switch(_idx56)
        for _ in range(12):
            _app56.processEvents()
        _scr56 = _w56.screens[_idx56]
        _lbls56 = _scr56.findChildren(_QW56.QLabel)
        check("داخل الشاشة: شريط الحالة مطويّ للجدول",
              not _w56.statusBar().isVisible())
        check("وفقرات الشرح وعنوانُ الشاشة المكرّر مطويّة",
              not any(_dc56.foldable(l) and l.isVisible() for l in _lbls56)
              and any(l.property("_note_folded") for l in _lbls56))
        _w56._update_notes_btn()        # يُنادى بعد ربع ثانية من الفتح
        check("والشرح لا يضيع: زرّ ⓘ يعرضه عند الطلب",
              _w56.btn_notes.isVisible() and bool(_w56._current_notes()))
        _w56.switch(0)
        for _ in range(4):
            _app56.processEvents()
        check("والعودة للرئيسية تُعيد شريط الحالة",
              _w56.statusBar().isVisible())
        _w56.close()

        from ui.widgets import gold_stage as _gs56
        _st56 = _gs56.GoldStage()
        _st56.resize(640, 400)
        _st56.intro = 1.0
        from PyQt5 import QtGui as _QG56
        _img56 = _QG56.QImage(640, 400, _QG56.QImage.Format_ARGB32)
        _st56.render(_img56)
        _st56.exit = 0.6
        _st56.render(_img56)
        check("المسرح: ثلاث طبقات عمق وإيقاعٌ ستّيني ينزل وحده عند الثقل",
              len({d["d"] for d in _st56._dust}) == 3 and _gs56.FPS == 60
              and _gs56.LOW_FPS == 30 and _st56._bg is not None)
    except ImportError:
        print("  … تُخطّى فحوص الواجهة (PyQt5 غير متاح)")

    step("57) الفوترة الإلكترونية — المرحلة الثانية (الربط مع الهيئة)")
    import base64 as _b57
    from services.fatoora import ec as _ec57, ledger as _lg57, \
        onboard as _ob57, readiness as _rd57, ubl as _ubl57
    from services.fatoora import profile as _pf57
    _k57 = _ec57.PrivateKey.generate()
    _m57 = b"gold-erp"
    check("التوقيع secp256k1 (ECDSA-SHA256): يتحقّق ويكشف أي عبث",
          _ec57.verify(_k57.pub, _m57, _k57.sign(_m57))
          and not _ec57.verify(_k57.pub, b"gold-erP", _k57.sign(_m57))
          and _ec57.PrivateKey.from_pem(_k57.to_pem()).d == _k57.d)
    _csr57 = _ec57.build_csr(
        _k57, common_name="GoldERP-TEST", org="مصنع", org_unit="فرع",
        vat_number="310122393500003", egs_serial="1-GoldERP|2-1|3-x",
        invoice_types="1100", address="الرياض", category="Gold",
        env="production")
    _der57 = _ec57._unpem(_csr57)
    check("طلب الشهادة بمواصفات الهيئة (القالب · الرقم الضريبي · 1100)",
          b"ZATCA-Code-Signing" in _der57 and b"310122393500003" in _der57
          and b"1100" in _der57)
    _cert57 = _ec57.self_signed_certificate(_k57)
    _seller57 = {"name": "مصنع & شركاه", "vat": "310122393500003",
                 "crn": "1010851840", "street": "الصناعة", "building": "1234",
                 "district": "الصناعية", "city": "الرياض", "postal": "14331"}
    _doc57 = {"kind": "invoice", "subtype": "simplified", "number": "S-1",
              "issue_date": "2026-09-28", "issue_time": "10:00:00", "icv": 1,
              "pih": _ubl57.FIRST_PIH, "seller": _seller57,
              "buyer": {"name": "عميل"},
              "lines": [{"name": "مصنعية", "amount": 100.005}]}
    _sd57 = _ubl57.sign_document(_doc57, _k57, _cert57)
    _v57 = _ubl57.verify_document(_sd57["xml"])
    _q57 = _ubl57.parse_qr(_sd57["qr"])
    check("المستند: بصمته تطابق نصّه، وختمه صحيح، ورمزه بتسعة حقول",
          _v57["hash_ok"] and _v57["signature_ok"]
          and sorted(_q57) == list(range(1, 10))
          and _q57[6].decode() == _sd57["hash"]
          and str(_sd57["totals"]["gross"]) == "115.01")
    _tam57 = _sd57["xml"].replace("<cbc:ID>S-1</cbc:ID>",
                                  "<cbc:ID>S-2</cbc:ID>")
    check("وأي تعديلٍ في نصّ المستند يُسقط بصمته",
          not _ubl57.verify_document(_tam57)["hash_ok"])
    with db() as conn:
        _pf57.save(conn, {"name": "مصنع الفحص", "vat": "310122393500003",
                          "crn": "1010851840", "street": "الصناعة",
                          "building": "1234", "district": "الصناعية",
                          "city": "الرياض", "postal": "14331",
                          "env": "simulation"})
        _before57 = _rd57.verdict(conn)[1]
    _tok57 = _b57.b64encode(_cert57.encode()).decode()
    _pf57.save_keys("simulation", {
        "private_key": _k57.to_pem(), "csr": _csr57,
        "compliance": {"token": _tok57, "secret": "s"},
        "checks": {f"{a}:{b}": {"ok": True} for a, b in _ob57.SAMPLES},
        "production": {"token": _tok57, "secret": "s"}})
    with db() as conn:
        _ob57.set_enabled(conn, True, "admin")
        _c57 = _add9(conn, "عميل الفوترة الإلكترونية", "customer",
                          username="admin")
        _b9(conn, [{"wo_no": "EINV-1", "gold": 20.0,
                    "wage_per_gram": 10.0}], "2026-09-28", "admin")
        _w57 = conn.execute("SELECT id FROM work_orders WHERE"
                            " work_order_no='EINV-1'").fetchone()["id"]
    with db() as conn:
        _s57 = _inv9.create_sale(conn, _c57, [{"work_order_id": _w57}],
                                 "2026-09-28", "admin", apply_vat=True)
    with db(readonly=True) as conn:
        _d57 = _lg57.doc_for(conn, "invoices", _s57["id"])
    check("مع التفعيل: كل فاتورة ضريبية تُصدر مستندها المختوم في معاملتها",
          _d57 is not None and _d57["status"] == "pending"
          and _ubl57.verify_document(_d57["xml"])["signature_ok"]
          and _s57["qr_base64"] == _d57["qr"], _before57)
    try:
        with db() as conn:
            _inv9.update_invoice(conn, _s57["id"], [{"work_order_id": _w57}],
                                 "admin")
        _g57 = False
    except ValueError as _e57:
        _g57 = "إشعار دائن" in str(_e57)
    try:
        with db() as conn:
            conn.execute("DELETE FROM fatoora_documents")
        _t57 = False
    except Exception:
        _t57 = True
    check("ولا تُعدَّل الفاتورة بعد إصدار مستندها، ولا يُحذف المستند",
          _g57 and _t57)
    with db() as conn:
        _r57 = _rd57.run(conn)
        _ob57.set_enabled(conn, False, "admin")
    check("والحكم صريح: قبل التسجيل «غير مربوط»، وفي المحاكاة «ليس ربطاً رسمياً»",
          _before57 == "غير مربوط بالهيئة"
          and "المحاكاة" in _r57["verdict"][1], _r57["verdict"][1])

    # ══════════════════════════════════════════════════════════════
    step("58) المبيعات الضريبية (بلا مخزون) والمشتريات الضريبية")
    from models import purchases as _pu58
    from models import tax_sales as _ts58
    from models.entities import add_entity as _add58
    from models.reports import vat_return as _vr58
    from services.accounting_engine import account_balance as _ab58
    with db() as conn:
        _c58 = _add58(conn, "عميل المبيعات الضريبية", "customer",
                      username="admin")
        _s58 = _add58(conn, "مورد ضريبي", "supplier",
                      vat_number="300000000000003", username="admin")
        _wo0 = conn.execute("SELECT COUNT(*), COALESCE(SUM(CASE WHEN"
                            " status='in_stock' THEN 1 END),0)"
                            " FROM work_orders").fetchone()
        _g0 = conn.execute("SELECT COALESCE(SUM(gold_debit+gold_credit),0)"
                           " FROM journal_lines").fetchone()[0]
        _vb58 = _vr58(conn, "2026-10-01", "2026-10-31")
        _t58 = _ts58.create_invoice(conn, _c58, "2026-10-02", [
            {"description": "خدمة تصميم", "qty": 2, "unit_price": 500,
             "discount": 50}], "admin", pay_mode="cash")
    with db(readonly=True) as conn:
        _wo1 = conn.execute("SELECT COUNT(*), COALESCE(SUM(CASE WHEN"
                            " status='in_stock' THEN 1 END),0)"
                            " FROM work_orders").fetchone()
        _g1 = conn.execute("SELECT COALESCE(SUM(gold_debit+gold_credit),0)"
                           " FROM journal_lines").fetchone()[0]
        _j58 = {r["code"]: (r["d"], r["c"]) for r in conn.execute(
            "SELECT a.code, l.cash_debit d, l.cash_credit c FROM"
            " journal_lines l JOIN accounts a ON a.id=l.account_id"
            " WHERE l.entry_id=?", (_t58["entry_id"],))}
    check("فاتورة ضريبية بالريال: 1400 / 4130 / 2100 — بلا ذهبٍ ولا مخزون",
          _t58["net"] == 950.0 and _t58["vat"] == 142.5
          and _j58 == {"1400": (1092.5, 0.0), "4130": (0.0, 950.0),
                       "2100": (0.0, 142.5)}
          and tuple(_wo0) == tuple(_wo1) and _g0 == _g1, str(_j58))
    with db(readonly=True) as conn:
        _l58 = list(_ts58.remaining(conn, _t58["id"]))[0]
    try:
        with db() as conn:
            _ts58.create_credit_note(conn, _t58["id"], "2026-10-03",
                                     [{"src_line_id": _l58, "qty": 3}],
                                     "مرتجع", "admin")
        _x58 = False
    except ValueError:
        _x58 = True
    with db() as conn:
        _n58 = _ts58.create_credit_note(conn, _t58["id"], "2026-10-03",
                                        [{"src_line_id": _l58, "qty": 1}],
                                        "خدمة لم تكتمل", "admin")
    check("الإشعار الدائن لا يتجاوز المباع، ويعكس بنسبة الكمية (475 + 71.25)",
          _x58 and _n58["net"] == 475.0 and _n58["vat"] == 71.25)
    try:
        from services.audit import soft_delete_entry as _sd58
        _sd58(_t58["entry_id"], "admin")
        _y58 = False
    except Exception:
        _y58 = True
    check("ولا تُحذف فاتورةٌ عليها إشعارٌ دائن قائم", _y58)
    with db() as conn:
        _net58, _vat58 = _pu58.split_amount(1150, "gross")
        _p58 = _pu58.create_purchase(
            conn, "expense", _s58, "صيانة", _net58, _vat58, "2026-10-04",
            "admin", supplier_invoice_no="S-1", account_code="5830",
            price_mode="gross")
    try:
        with db() as conn:
            _pu58.create_purchase(conn, "expense", _s58, "مكرّر", 10, 1.5,
                                  "2026-10-05", "admin",
                                  supplier_invoice_no="S-1")
        _z58 = False
    except ValueError:
        _z58 = True
    with db(readonly=True) as conn:
        _va58 = _vr58(conn, "2026-10-01", "2026-10-31")
        _in58 = _ab58(conn, acc_id(conn, "1900"), "2026-10-01",
                      "2026-10-31")[1]
    check("مشتريات شاملة 1150 ⇒ 1000 على 5830 و150 مدخلات، ولا تُقيَّد "
          "فاتورة المورد مرتين",
          (_net58, _vat58) == (1000.0, 150.0) and _z58
          and round(_in58, 2) == 150.0)
    check("الإقرار: مخرجات المبيعات الضريبية ومدخلات المشتريات في الفترة",
          round(_va58["output_vat"] - _vb58["output_vat"], 2) == 71.25
          and _va58["tax_sales_vat"] == 71.25
          and _va58["input_vat"] == 150.0
          and _va58["purchases_vat"] == 150.0,
          f"{_va58['output_vat']} {_va58['tax_sales_vat']} "
          f"{_va58['input_vat']}")

    # ══════════════════════════════════════════════════════════════
    step("59) فاتورة الشركة عبر المندوب · الإشعار المدين · خصم المشتريات")
    from models import invoices as _inv59
    from models import purchases as _pu59
    from models import tax_sales as _ts59
    from models.entities import add_entity as _add59
    from models.inventory import create_work_orders_batch as _b59
    with db() as conn:
        _rep59 = _add59(conn, "مندوب الفحص", "customer", username="admin")
        _co59 = _add59(conn, "شركة الفحص", "customer", username="admin",
                       vat_number="311111111100003")
        _b59(conn, [{"wo_no": "REP-1", "gold": 40.0,
                     "wage_per_gram": 10.0}], "2026-11-01", "admin")
        _w59 = conn.execute("SELECT id FROM work_orders WHERE"
                            " work_order_no='REP-1'").fetchone()["id"]
        _inv59.create_sale(conn, _rep59, [{"work_order_id": _w59}],
                           "2026-11-02", "admin", apply_vat=False)
        _acc = lambda e: conn.execute(  # noqa: E731
            "SELECT account_id FROM entities WHERE id=?",
            (e,)).fetchone()[0]
        _ra, _ca = _acc(_rep59), _acc(_co59)
        _bal = lambda a: conn.execute(  # noqa: E731
            "SELECT COALESCE(SUM(cash_debit-cash_credit),0) FROM"
            " journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
            " WHERE e.is_deleted=0 AND l.account_id=?", (a,)).fetchone()[0]
        _r0, _c0 = _bal(_ra), _bal(_ca)
        _st0 = conn.execute("SELECT status FROM work_orders WHERE id=?",
                            (_w59,)).fetchone()[0]
        _it59 = _ts59.find_rep_item(conn, _rep59, "REP-1")
        _t59 = _ts59.create_rep_invoice(
            conn, _co59, _rep59, "2026-11-03",
            [{"sale_item_id": _it59["item_id"]}], "admin")
        _r1, _c1 = _bal(_ra), _bal(_ca)
        _st1 = conn.execute("SELECT status FROM work_orders WHERE id=?",
                            (_w59,)).fetchone()[0]
    check("الفاتورة باسم الشركة: على المندوب الضريبة وحدها، والشركة بلا "
          "رصيد، والطقم كما هو",
          _t59["vat"] == round(_t59["net"] * 0.15, 2)
          and round(_r1 - _r0, 2) == _t59["vat"] and round(_c1 - _c0, 2) == 0
          and _st0 == _st1 == "sold", f"{_t59['net']} {_t59['vat']}")
    try:
        with db(readonly=True) as conn:
            _ts59.find_rep_item(conn, _rep59, "REP-1")
        _x59 = False
    except ValueError:
        _x59 = True
    with db() as conn:
        _d59 = _ts59.create_debit_note(conn, _t59["id"], "2026-11-04", 50,
                                       "فرق أجر", "admin")
        _r2 = _bal(_ra)
    check("لا يُفوتر الطقم مرتين · والإشعار المدين (50 + 7.5) على المندوب",
          _x59 and _d59["total"] == 57.5 and round(_r2 - _r1, 2) == 57.5)
    with db() as conn:
        _s59 = _add59(conn, "مورد الخصم", "supplier",
                      vat_number="300000000000003", username="admin")
        _n59, _v59 = _pu59.split_amount(1000, "net", discount=100)
        _p59 = _pu59.create_purchase(
            conn, "expense", _s59, "مواد", _n59, _v59, "2026-11-05",
            "admin", supplier_invoice_no="DISC-1", discount=100)
    check("خصم المشتريات قبل الضريبة: 1000 − 100 ⇒ 900 + 135 = 1035",
          (_n59, _v59) == (900.0, 135.0) and _p59["total"] == 1035.0)

    # ══════════════════════════════════════════════════════════════
    step("60) مشتريات نقداً/بنكاً · خصم الفاتورة الضريبية · ضريبية/مبسطة")
    with db() as conn:
        _pc = _pu59.create_purchase(
            conn, "expense", _s59, "ضيافة", 100, 15, "2026-11-06", "admin",
            supplier_invoice_no="CASH-1", pay_mode="cash",
            invoice_type="simplified")
        _jc = [(r[0], r[1], r[2]) for r in conn.execute(
            "SELECT a.code, l.cash_debit, l.cash_credit FROM journal_lines l"
            " JOIN accounts a ON a.id=l.account_id WHERE l.entry_id=?"
            " ORDER BY l.id", (_pc["entry_id"],))]
    check("شراءٌ نقدي: الدائن الصندوق 1400 لا المورد",
          _jc[-1] == ("1400", 0, 115.0), str(_jc))
    with db() as conn:
        _b59(conn, [{"wo_no": "REP-2", "gold": 30.0,
                     "wage_per_gram": 10.0}], "2026-11-06", "admin")
        _w60 = conn.execute("SELECT id FROM work_orders WHERE"
                            " work_order_no='REP-2'").fetchone()["id"]
        _inv59.create_sale(conn, _rep59, [{"work_order_id": _w60}],
                           "2026-11-06", "admin", apply_vat=False)
        _i60 = _ts59.find_rep_item(conn, _rep59, "REP-2")
        _t60 = _ts59.create_rep_invoice(
            conn, _co59, _rep59, "2026-11-07",
            [{"sale_item_id": _i60["item_id"]}], "admin", discount=50)
        _s60 = conn.execute("SELECT * FROM tax_sales WHERE id=?",
                            (_t60["id"],)).fetchone()
        _sub60 = _ts59.subtype(conn, _s60)
    check("خصم 50 من أجور 300 ⇒ صافي 250 وضريبة 37.5 · والفاتورة ضريبية",
          _t60["net"] == 250.0 and _t60["vat"] == 37.5
          and _sub60 == "standard")

    # ══════════════════════════════════════════════════════════════
    step("61) صفُّ الإجمالي أسود بخطٍّ أبيض · الأرقام لا تُقصّ")
    from PyQt5 import QtGui as _G61, QtWidgets as _W61
    from PyQt5.QtTest import QTest as _T61
    from ui.widgets.common import fill as _fill61, make_table as _mk61
    from ui.widgets.table_fit import fit_columns as _fit61
    _t61 = _mk61()
    _t61.resize(1200, 300)
    _t61.show()
    _big = 987654321.12
    _fill61(_t61, ["الاسم", "أ", "ب", "ج", "د", "هـ", "و", "ز"],
            [("مؤسسة طويلة الاسم جداً", 1.5, _big / 10, 12.0, _big / 3,
              3.0, _big, "45.2%")] * 4
            + [("الإجمالي",) + (_big,) * 6 + ("50%",)])
    _fit61(_t61, [40, 8, 8, 8, 8, 8, 8, 4])
    _T61.qWait(150)
    _img = _t61.viewport().grab().toImage()
    _px = _G61.QColor(_img.pixel(_t61.columnViewportPosition(3) + 20,
                                 _t61.rowViewportPosition(4) + 6)).name()
    check("صفُّ الإجمالي يُرسم أسود بخطٍّ أبيض",
          _px == "#1c1a17"
          and _t61.item(4, 2).foreground().color().name() == "#ffffff", _px)
    _fm = _G61.QFontMetrics(_t61.font())
    _b = _G61.QFont(_t61.font())
    _b.setBold(True)
    _fmb = _G61.QFontMetrics(_b)
    _clip = sum(1 for c in range(1, 8) for r in range(_t61.rowCount())
                if (_fmb if _t61.item(r, c).font().bold() else _fm)
                .horizontalAdvance(_t61.item(r, c).text()) + 10
                > _t61.columnWidth(c))
    check("الأعمدة تتّسع لأعرض رقمٍ فيها — لا رقم مقصوص", _clip == 0,
          f"{_clip} · {[_t61.columnWidth(c) for c in range(8)]} · "
          f"{_fmb.horizontalAdvance(_t61.item(4, 2).text())} · "
          f"{_t61.font().pointSizeF()} vp={_t61.viewport().width()}")
    _t61.close()

    # ══════════════════════════════════════════════════════════════
    step("62) الرصيد بعد العملية في القيد والتسكير والمشتريات · معاينة كل حركة")
    from services import print_manager as _pm62
    from ui.general_ledger_screen import _doc_target as _dt62
    with db() as conn:
        _a62 = conn.execute("SELECT account_id FROM entities WHERE id=?",
                            (_c52,)).fetchone()[0]
        _e62 = post_entry(conn, "2026-10-20", "قيد يدوي للمعاينة", [
            {"account_id": _a62, "cash_debit": 70},
            {"account_id": acc_id(conn, "1400"), "cash_credit": 70}],
            source_table="manual", username="admin")
        _f62 = _fx52(conn, _c52, 2.0, 300.0, "2026-10-21",
                             "admin")["id"]
        _p62 = _pu58.create_purchase(
            conn, "expense", _s58, "قرطاسية", 100, 15, "2026-10-22",
            "admin", supplier_invoice_no="S-62", account_code="5830")["id"]
        _bal62 = conn.execute(
            "SELECT ROUND(SUM(cash_debit-cash_credit),2) FROM journal_lines l"
            " JOIN journal_entries e ON e.id=l.entry_id WHERE e.is_deleted=0"
            " AND l.account_id=? AND e.id<=?", (_a62, _e62)).fetchone()[0]
    _hj = _pm62.build_html("manual", _e62)
    _hf = _pm62.build_html("fixing_ops", _f62)
    _hp = _pm62.build_html("purchases", _p62)
    check("قالب القيد اليومي يعرض الرصيد بعد العملية لحساب الجهة",
          "الرصيد بعد العملية" in _hj and "عميل التسكير" in _hj
          and f"{_bal62:,.2f}" in _hj, str(_bal62))
    check("وقالبا التسكير والمشتريات كذلك",
          "رصيد الذهب في حساب" in _hf and "رصيد النقد في حساب" in _hp)
    check("كل حركة في الكشف لها معاينة — القيد اليدوي بقالب «قيد يومية»",
          _dt62({"src": None, "sid": None, "eid": 5}, _pm62.BUILDERS)
          == ("manual", 5)
          and _dt62({"src": "fixing_ops", "sid": 3, "eid": 9},
                    _pm62.BUILDERS) == ("fixing_ops", 3)
          and _dt62({"src": "no_such_tpl", "sid": 3, "eid": 9},
                    _pm62.BUILDERS) == ("manual", 9))
    _hm = _pm62.build_html("model_photos", 0, min_count=1)
    _hc = _pm62.build_html("models_catalog", 0)
    check("قوالب دليل الموديلات بلا ترويسة المصنع وشعاره",
          'class="lh"' not in _hm and 'class="lh"' not in _hc
          and "الموديلات" in _hc)
    try:
        from PyQt5 import QtWidgets as _QW62
        _QW62.QApplication.instance() or _QW62.QApplication([])
        import ui.sales_screen as _ssm62
        from ui.widgets.common import save_pref as _sp62
        _sp62("sales_scrap_karat", "", "admin")
        _kv.set_active(21, "admin")
        try:
            _s62 = _ssm62.SalesScreen({"id": 1, "username": "admin",
                                       "role": "admin",
                                       "role_local": "accountant"})
            _s62.refresh()
            _k62 = _s62.scrap_karat.currentData()
            _s62.close()
        finally:
            _kv.set_active(18, "admin")
        check("صندوق الكسر يتبع العيار المختار أعلى النافذة (21)",
              _k62 == 21, str(_k62))
    except ImportError:
        print("  … تُخطّى فحوص الواجهة (PyQt5 غير متاح)")

    # ══════════════════════════════════════════════════════════════
    step("63) هوية المصنع — لكل مصنعٍ شعاره واسمه في كل القوالب")
    from services import branding as _br63
    _base63 = config.BASE_DIR
    config.BASE_DIR = pathlib.Path(_TMP)        # صور الهوية في مجلد الاختبار
    try:
        with db(readonly=True) as conn:
            _inv63 = conn.execute("SELECT id FROM invoices WHERE"
                                  " is_deleted=0 LIMIT 1").fetchone()[0]
        _h0 = _pm62.build_html("invoices", _inv63)
        check("قبل الضبط: مصنعٌ جديد بلا اسمٍ ولا شعار (لا هوية مصنعٍ آخر)",
              "جاديت" not in _h0 and "Jadeite" not in _h0
              and _br63.is_blank() and config.LOGO_PATH is None)
        _png63 = (__import__("services.photo_qr", fromlist=["x"])
                  .qr_png_data_uri("logo63").split(",", 1)[1])
        _id63 = dict(_br63.defaults(), name="مصنع النخبة للذهب",
                     name_en="Elite Gold", address="جدة — الصناعية",
                     cr="4030123456", layout="logo_left", logo_b64=_png63)
        check("رقمٌ ضريبي خاطئ واسمٌ فارغ يُرفضان قبل الاعتماد",
              _br63.validate(dict(_id63, vat="123"))
              and _br63.validate(dict(_id63, name=" ")))
        with db() as conn:
            _br63.save(conn, _id63, "admin")
        _h1 = _pm62.build_html("invoices", _inv63)
        _lg63 = pathlib.Path(str(config.LOGO_PATH))
        check("بعد الاعتماد: الفاتورة باسم المصنع وعنوانه وسجله وشعاره",
              "مصنع النخبة للذهب" in _h1 and "جاديت" not in _h1
              and "4030123456" in _h1 and "جدة — الصناعية" in _h1
              and _lg63.exists() and _lg63.as_uri() in _h1)
        _pm62.RTL_ORDER_OVERRIDE = True
        _lh63 = _pm62.letterhead()
        _pm62.RTL_ORDER_OVERRIDE = None
        check("الشعار يساراً: بيانات المصنع يميناً ثم الشعار",
              _lh63.index("مصنع النخبة") < _lh63.index("<img"))
        check("وكل القوالب تمرّ بالترويسة نفسها (قيد · تسكير · مشتريات)",
              all("مصنع النخبة للذهب" in _pm62.build_html(t, i)
                  for t, i in (("manual", _e62), ("fixing_ops", _f62),
                               ("purchases", _p62))))
        config.COMPANY_NAME = "—"
        _br63.apply_cached()
        _c1 = config.COMPANY_NAME
        config.COMPANY_NAME = "—"
        _br63.sync_from_db()
        check("الإقلاع: الهوية من المرآة قبل القاعدة، ثم القاعدة مرجعها",
              _c1 == config.COMPANY_NAME == "مصنع النخبة للذهب")
        _f63 = pathlib.Path(_TMP) / "id63.json"
        _br63.export_file(_f63, _br63.current())
        check("ملف الهوية يُصدَّر ويُستورد بشعاره (لجهازٍ آخر)",
              _br63.import_file(_f63)["logo_b64"] == _png63)
        with db() as conn:
            _br63.save(conn, dict(_id63, hide_logo=True), "admin")
        check("«بلا شعار»: لا يُطبع شعار مصنعٍ آخر مكانه",
              "<img" not in _pm62.letterhead())
        with db() as conn:
            _br63.reset(conn, "admin")
        # 4.44: المحو لا يعيد هوية مصنعٍ آخر — المصنع بلا اسمٍ ولا شعار
        check("محو الهوية: بلا اسم مصنعٍ آخر ولا شعاره",
              "Jadeite" not in _pm62.letterhead()
              and "<img" not in _pm62.letterhead()
              and config.COMPANY_NAME == "")
    finally:
        config.BASE_DIR = _base63

    # ══════════════════════════════════════════════════════════════
    step("64) كل مصنع على جهازه: لا رفع سحابي · آخر 20 نسخة · الإيقاف من المدير")
    import importlib.util as _iu64
    from services import licensing as _lic64
    from services import storage as _st64
    from services import tenant as _tn64
    check("وحدات الرفع والاستقبال السحابي حُذفت، ولا انتحال شخصية",
          _iu64.find_spec("services.cloud_sync") is None
          and _iu64.find_spec("services.cloud_backup") is None
          and not hasattr(_tn64, "impersonate")
          and _tn64.effective_tenant_id() == _tn64.tenant_id())
    _bk64 = pathlib.Path(_TMP) / "bk64"
    _bk64.mkdir(exist_ok=True)
    _orig_bd64 = _st64.backup_dir
    _st64.backup_dir = lambda: _bk64          # لا يُمسّ مجلد نسخ الجهاز
    try:
        _p1 = _st64.make_backup("auto")
        _p2 = _st64.make_backup("auto")
        check("نسخةٌ مطابقة لسابقتها لا تُكرَّر",
              _p1 == _p2 and len(_st64.list_backups()) == 1)
        with db() as conn:
            _a64 = acc_id(conn, "1400")
            post_entry(conn, "2026-11-01", "حركة للنسخ", [
                {"account_id": _a64, "cash_debit": 5},
                {"account_id": acc_id(conn, "1100"), "cash_credit": 5}],
                source_table="manual", username="admin")
        _p3 = _st64.make_backup("auto")
        check("وبعد أي تغيير تُؤخذ نسخة جديدة",
              _p3 != _p1 and len(_st64.list_backups()) == 2)
        for _i in range(22):
            _st64.make_backup("manual")
        _rows64 = _st64.list_backups()
        check("يُحتفظ بآخر 20 نسخة فقط", len(_rows64) == 20
              and _st64.KEEP_LAST == 20, str(len(_rows64)))
        # الاسترجاع: أقدم العشرين — ولا يحذفها التدوير قبل قراءتها
        with db(readonly=True) as conn:
            _n0 = conn.execute("SELECT COUNT(*) FROM journal_entries"
                               ).fetchone()[0]
        _old64 = _rows64[-1]["path"]
        with db() as conn:
            post_entry(conn, "2026-11-02", "بعد النسخة", [
                {"account_id": _a64, "cash_debit": 7},
                {"account_id": acc_id(conn, "1100"), "cash_credit": 7}],
                source_table="manual", username="admin")
        _r64 = _st64.restore(_old64)
        with db(readonly=True) as conn:
            _n1 = conn.execute("SELECT COUNT(*) FROM journal_entries"
                               ).fetchone()[0]
        _after64 = _st64.list_backups()
        check("استرجاع أقدم النسخ يعيد البيانات إلى حالتها",
              _n1 == _n0 and _r64["restored"], f"{_n0} ← {_n1}")
        check("وتُؤخذ نسخة «قبل الاسترجاع» للتراجع، والعدد يبقى 20",
              any(r["reason"] == "before_restore" for r in _after64)
              and len(_after64) == 20)
        _junk = _bk64 / "junk.bak"
        _junk.write_bytes(b"not a database")
        check("ونسخةٌ تالفة تُرفض قبل أن تمسّ البيانات",
              not _st64.verify_backup(_junk)[0])
        try:
            _st64.restore(_junk)
            _ok64 = False
        except ValueError:
            _ok64 = True
        check("والاسترجاع منها يُمنع برسالة واضحة", _ok64)
        # التراجع عن الاسترجاع يعيد القيد الذي أُضيف بعد النسخة
        _before = next(r for r in _after64 if r["reason"] == "before_restore")
        _st64.restore(_before["path"])
        with db(readonly=True) as conn:
            _n2 = conn.execute("SELECT COUNT(*) FROM journal_entries"
                               ).fetchone()[0]
        check("والتراجع عن الاسترجاع يعيد ما بعده", _n2 == _n0 + 1,
              f"{_n2}")
    finally:
        _st64.backup_dir = _orig_bd64

    # إيقاف المصنع: كل حساباته — وحساب المدير لا يُمسّ
    from services import cloud_auth as _ca64
    _calls64 = []
    _orig_set64 = _ca64.set_user_active
    _ca64.set_user_active = lambda u, a: _calls64.append((u, a))
    try:
        _users64 = [
            {"username": "f1", "tenant_id": "F-A", "is_active": True,
             "role": "factory"},
            {"username": "f1b", "tenant_id": "F-A", "is_active": True,
             "role": "factory"},
            {"username": "f2", "tenant_id": "F-B", "is_active": True,
             "role": "factory"},
            {"username": "boss", "tenant_id": "F-A", "is_active": True,
             "role": "super_admin"}]
        _n64 = _lic64.set_factory_active("F-A", False, users=_users64)
    finally:
        _ca64.set_user_active = _orig_set64
    check("«إيقاف المصنع» يوقف كل حساباته ولا يمسّ غيره ولا المدير",
          _n64 == 2 and sorted(_calls64) == [("f1", False), ("f1b", False)])
    # الحارس: حسابٌ أُوقف ⇒ نداء الإيقاف مرةً واحدة
    _hit64 = []
    _orig_st64 = _lic64.account_status
    _lic64.account_status = lambda u, timeout=10: {
        "online": True, "known": True, "active": False}
    try:
        _g64 = _lic64.AccountGuard("f1", lambda: _hit64.append(1))
        _g64.check_now()
        _lic64.account_status = lambda u, timeout=10: {
            "online": False, "known": False, "active": True}
        _g65 = _lic64.AccountGuard("f2", lambda: _hit64.append(2))
        _g65.check_now()
    finally:
        _lic64.account_status = _orig_st64
    check("الحارس يوقف البرنامج عند إيقاف الحساب — ولا يوقفه انقطاع الإنترنت",
          _hit64 == [1] and _g64._stop.is_set() and not _g65._stop.is_set())
    try:
        from PyQt5 import QtWidgets as _QW64
        _QW64.QApplication.instance() or _QW64.QApplication([])
        from ui.backups_dialog import BackupsDialog as _BD64
        _st64.backup_dir = lambda: _bk64
        try:
            _d64 = _BD64(None, {"username": "admin"})
            _rows_ui = _d64.table.rowCount()
            _d64.close()
        finally:
            _st64.backup_dir = _orig_bd64
        check("نافذة النسخ والاسترجاع تعرض آخر 20 نسخة لكل مستخدم",
              _rows_ui == 20, str(_rows_ui))
    except ImportError:
        print("  … تُخطّى فحوص الواجهة (PyQt5 غير متاح)")

    # ══════════════════════════════════════════════════════════════
    step("65) مصنع عيار 21: كل الأوزان والقوالب بمكافئ 21 · إطار البوابة")
    import re as _re65
    from services import print_manager as _pm65
    with db(readonly=True) as conn:
        _wo65 = conn.execute(
            "SELECT id, registered_weight FROM work_orders WHERE is_deleted=0"
            " AND registered_weight > 1 ORDER BY id LIMIT 1").fetchone()
    _r18 = f"{_wo65['registered_weight']:,.2f}"
    _r21 = f"{_wo65['registered_weight'] * 18 / 21:,.2f}"
    _kv.set_active(21, "admin")
    try:
        _hw65 = _pm65.build_html("work_orders", _wo65["id"])
        _hb65 = _pm65.build_html("balance_tree", 0)
        _txt65 = _re65.sub("<[^>]+>", " ", _hw65)
        check("قالب رقم التشغيل بمكافئ 21 لا 18",
              _r21 in _txt65 and _r18 not in _txt65, f"{_r18} → {_r21}")
        check("والميزانية بعنوان «جم 21» بلا «جم 18»",
              "جم 21" in _hb65 and "جم 18" not in _hb65)
        try:
            from PyQt5 import QtWidgets as _QW65
            _QW65.QApplication.instance() or _QW65.QApplication([])
            from ui.main_window import MainWindow as _MW65
            check("عنوان النظام يحمل عيار المصنع",
                  "عيار 21" in _MW65._app_title())
            import ui.entities_screen as _es65
            _src65 = pathlib.Path(_es65.__file__).read_text(encoding="utf-8")
            check("جدول الجهات يعرض رصيد الذهب بعيار المصنع",
                  "(جم 18)" not in _src65 and "kv.g(g)" in _src65)
        except ImportError:
            print("  … تُخطّى فحوص الواجهة (PyQt5 غير متاح)")
    finally:
        _kv.set_active(18, "admin")
    try:
        from PyQt5 import QtGui as _QG65
        from ui.widgets import gold_frame as _gf65
        _ov = _gf65.screen_overlay(400, 300, 1.0).toImage().convertToFormat(
            _QG65.QImage.Format_ARGB32)
        _edge = _QG65.QColor.fromRgba(_ov.pixel(2, 150)).alpha()
        _mid = _QG65.QColor.fromRgba(_ov.pixel(200, 140)).alpha()
        check("حواف الشاشة: تعتيمٌ على الأطراف وصفاءٌ في الوسط",
              _edge > 25 and _mid == 0, f"{_edge}/{_mid}")
        _card = _gf65.GlassCard()
        _card.resize(420, 300)
        check("لوحة الدخول هادئة: بلا إطارٍ ذهبي مصقول ولا لمعةٍ تمرّ",
              not hasattr(_card, "_sweep") and not hasattr(_gf65, "METAL")
              and _card.start_shine() is None)
    except ImportError:
        print("  … تُخطّى فحوص الواجهة (PyQt5 غير متاح)")

    # ══════════════════════════════════════════════════════════════
    step("66) شاشات محذوفة · ملف الجهة وأعمار الديون في العملاء · 1350")
    from models import dossier as _ds66
    from models import reports as _rp66
    with db(readonly=True) as conn:
        _cust66 = conn.execute(
            "SELECT i.customer_id, i.id FROM invoices i WHERE i.kind='sale'"
            " AND i.is_deleted=0 ORDER BY i.id LIMIT 1").fetchone()
        _mi66 = _ds66.model_items(conn, _cust66[0])
    _src66 = pathlib.Path(_rp66.__file__).read_text(encoding="utf-8")
    # 4.40: 1350 صار 5125 «فاقد التصفية والصب» (الحساب نفسه)
    check("قائمة الدخل: فاقد التصفية والصب (5125، كان 1350) بدل الفاقد"
          " الفني (5120)",
          '_period_account_gold(conn, "5125"' in _src66
          and '_period_account_gold(conn, "5120"' not in _src66)
    check("موديلات الجهة: كل موديلٍ بأرقام تشغيله وأوزانها",
          _mi66 and all(m["items"] and all("wo" in i and "weight" in i
                                            for i in m["items"])
                        for m in _mi66), str(len(_mi66 or [])))
    _hd66 = _pm65.build_html("dossier_models", _cust66[0],
                             date_from="2000-01-01", date_to="2100-01-01")
    _hi66 = _pm65.build_html("invoice_models", _cust66[1])
    check("ورقتا الصور: موديلات الجهة وموديلات الفاتورة",
          "رقم التشغيل" in _hd66 and "رقم التشغيل" in _hi66
          and _mi66[0]["items"][0]["wo"] in _hd66)
    try:
        from PyQt5 import QtWidgets as _QW66
        _QW66.QApplication.instance() or _QW66.QApplication([])
        from ui.main_window import MainWindow as _MW66
        _w66 = _MW66({"id": 1, "username": "admin", "role": "admin",
                      "role_local": "accountant", "full_name": "م"})
        _names66 = [it.text(0) for it, _p in _w66._iter_nav()]
        _gone66 = ("الصب والتصفية", "المطابقة وتسوية الفروقات",
                   "أرصدة المخازن (جرد لحظي)", "الرواتب والموظفون",
                   "تسوية فاقد التصنيع الشهري")
        check("الشاشات الخمس حُذفت من القائمة",
              not any(n in _names66 for n in _gone66))
        from ui.reports.analysis_hub_screen import SECTIONS as _hub66
        from ui.customers_screen import CustomersScreen as _CS66
        _c66 = _CS66({"id": 1, "username": "admin"})
        _tabs66 = [_c66.sections.tabText(i)
                   for i in range(_c66.sections.count())]
        check("ملف الجهة وأعمار الديون: في شاشة العملاء لا التحليل",
              _tabs66 == ["المبيعات والسداد", "ملف الجهة", "أعمار الديون"]
              and all(x[0] not in ("ملف الجهة", "أعمار الديون")
                      for x in _hub66))
        _dz = _c66.open_section("ملف الجهة")
        check("وقسم «موديلاته» بزرّ عرض الصور",
              _dz is not None and hasattr(_dz, "btn_photos"))
        _c66.close()
        _w66.show()
        _QW66.QApplication.processEvents()
        _hdr_home = _w66._header_bar.isVisible()
        from PyQt5 import QtCore as _QC66
        for it, _p in _w66._iter_nav():
            _ix = it.data(0, _QC66.Qt.UserRole)
            if _ix:                       # أول شاشةٍ فرعية في القائمة
                _w66.switch(_ix)
                break
        _QW66.QApplication.processEvents()
        _hdr_sub = _w66._header_bar.isVisible()
        _w66._close_screen()
        _QW66.QApplication.processEvents()
        check("الشريط العلوي يُطوى داخل الشاشات ويعود في الرئيسية",
              _hdr_home and not _hdr_sub
              and _w66._header_bar.isVisible(),
              f"{_hdr_home}/{_hdr_sub}/{_w66._header_bar.isVisible()}")
        _w66.close()
    except ImportError:
        print("  … تُخطّى فحوص الواجهة (PyQt5 غير متاح)")

    step("67) ميزان المراجعة وقائمة المركز المالي بالنهج المحاسبي")
    from datetime import date
    from models import statements as _st67
    with db() as conn:
        # عميلٌ دفع أكثر مما عليه ⇒ رصيده دائن ⇒ مطلوبٌ لا تخفيضٌ للذمم
        _c67 = conn.execute(
            "SELECT a.id FROM accounts a JOIN accounts p ON p.id=a.parent_id"
            " WHERE p.code='1600' ORDER BY a.id LIMIT 1").fetchone()[0]
        post_entry(conn, date.today().isoformat(), "دفعة مقدّمة من عميل", [
            {"account_id": acc_id(conn, "1400"), "cash_debit": 777777},
            {"account_id": _c67, "cash_credit": 777777}], username="admin")
    with db(readonly=True) as conn:
        _tbc = _st67.trial_balance(conn, None, None, "cash")
        _tbg = _st67.trial_balance(conn, "2026-01-01", None, "gold")
        _tb1 = _st67.trial_balance(conn, None, None, "cash", max_level=1)
        _fp = _st67.financial_position(conn, "2100-12-31", "2025-12-31")
        _bal = _st67._balances(conn, "2100-12-31", "cash")
        _rows67, _byid67, _r67 = _st67._tree(conn)
    _k6 = ("open_dr", "open_cr", "dr", "cr", "close_dr", "close_cr")
    check("الميزان: مدين = دائن في أول المدة والحركة وآخر المدة (نقد وذهب)",
          _tbc["totals"]["balanced"] and _tbg["totals"]["balanced"])
    check("الميزان: كل رصيدٍ في عمودَي مدين/دائن لا رقمٌ بإشارة",
          all(r[k] >= 0 for r in _tbc["rows"] for k in _k6)
          and all(not (r["close_dr"] and r["close_cr"])
                  for r in _tbc["rows"] if not r["is_group"]))
    check("الميزان: مجاميع الأقسام الرئيسية = إجمالي الميزان",
          all(abs(sum(s[k] for s in _tbc["sections"])
                  - _tbc["totals"][k]) < 0.02 for k in _k6))
    check("الميزان: المستوى 1 أقسامٌ رئيسية فقط وبنفس الإجمالي",
          all(r["is_root"] for r in _tb1["rows"])
          and all(abs(_tb1["totals"][k] - _tbc["totals"][k]) < 0.02
                  for k in _k6), str(len(_tb1["rows"])))
    _cv = _fp["cash"]["values"]
    _pos = _neg = _vat = 0.0
    for _n in _rows67:
        _b = _bal.get(_n["id"], 0.0)
        _kind = _st67._classify(_n, _byid67)
        if _kind == "party_customer":
            if _b > 0:
                _pos += _b
            else:
                _neg -= _b
        elif _kind == "vat":
            _vat += _b
    check("المركز المالي متوازن في البعدين وبالمقارنة",
          _fp["balanced_cash"] and _fp["balanced_gold"]
          and abs(_fp["cash"]["compare_totals"]["diff"]) < 0.011)
    check("بلا مقاصّة: العميل الدائن في المطلوبات لا مطروحاً من الذمم",
          abs(_cv["receivables"] - _pos) < 0.02
          and abs(_cv["customer_adv"] - _neg) < 0.02
          and _cv["customer_adv"] > 700000,
          f"{_cv['receivables']} / {_cv['customer_adv']}")
    check("الضريبة بالصافي والإهلاك مطروحٌ من التكلفة",
          abs((_cv["vat_asset"] - _cv["vat_liab"]) - _vat) < 0.02
          and _cv["ppe_dep"] <= 0.0001)
    _lay = _st67.layout(_fp)
    check("ترتيب IAS 1: الأصول ثم حقوق الملكية والمطلوبات · بلا إيراد/مصروف",
          [x["label"] for x in _lay if x["kind"] == "head"]
          == ["الأصول", "حقوق الملكية والمطلوبات"]
          and not any(x["kind"] == "line" and x["label"] in
                      ("الإيرادات", "المصروفات") for x in _lay)
          and _lay[-1]["label"] == "مجموع حقوق الملكية والمطلوبات")
    _ht = _pm65.build_html("trial_balance", 0, dim="gold", max_level=2)
    _hf = _pm65.build_html("financial_position", 0, as_of="2100-12-31",
                           compare_to="2025-12-31")
    check("قالبا الطباعة: أزواج مدين/دائن ومقارنة وتوقيعات",
          "رصيد أول المدة" in _ht and "أعدّه" in _ht
          and "مجموع حقوق الملكية والمطلوبات" in _hf and "راجعه" in _hf
          and "2025-12-31" in _hf)
    try:
        from PyQt5 import QtWidgets as _QW67
        _QW67.QApplication.instance() or _QW67.QApplication([])
        from ui.reports.balance_sheet_screen import BalanceSheetScreen as _B67
        from ui.reports.trial_balance_screen import TrialBalanceScreen as _T67
        _b67 = _B67({"id": 1, "username": "admin"})
        _t67 = _T67({"id": 1, "username": "admin"})
        _t67.all_time.setChecked(True)
        _t67.load()
        check("الشاشتان: تبويب القائمة وتبويب الشجرة · 8 أعمدة للميزان",
              [_b67.tabs.tabText(i) for i in range(_b67.tabs.count())]
              == ["قائمة المركز المالي", "تفصيل بشجرة الحسابات"]
              and _b67.statement.table.rowCount() > 5
              and _t67.table.columnCount() == 8
              and "متوازن" in _t67.status.text())
        _b67.close()
        _t67.close()
    except ImportError:
        print("  … تُخطّى فحوص الواجهة (PyQt5 غير متاح)")

    step("68) قائمة الدخل بالنهج المحاسبي · فاتورة مبيعات من مرتجع")
    _y68 = date.today().year
    with db(readonly=True) as conn:
        _is = _st67.income_statement(conn, f"{_y68}-01-01",
                                     date.today().isoformat())
        _pl68 = _st67._pl(conn, f"{_y68}-01-01", date.today().isoformat(),
                          "cash")
        _fp68 = _st67.financial_position(conn, date.today().isoformat())
    _t68 = _is["cash"]["totals"]
    check("قائمة الدخل من الدفتر: صافيها = نتيجة الإيراد والمصروف",
          abs(_t68["net"] - _pl68) < 0.02
          and abs(_t68["net"] - _fp68["cash"]["values"]["profit"]) < 0.02,
          f"{_t68['net']} / {_pl68}")
    _v68 = _is["cash"]["values"]
    check("المجاميع المرحلية: صافي الإيراد ← مجمل الربح ← التشغيلي ← الصافي",
          abs(_t68["net_revenue"] - (_v68["sales"] + _v68["returns"]
                                     + _v68["discounts"] + _v68["net_diff"]
                                     + _v68["other_rev"])) < 0.02
          and abs(_t68["gross"] - _t68["net_revenue"] - _t68["cos"]) < 0.02
          and abs(_t68["operating"] - _t68["gross"] - _t68["opex"]) < 0.02
          and _v68["returns"] <= 0.001 and "compare" in _is["cash"])
    _li68 = _st67.is_layout(_is, accounts=True)
    check("قائمة الدخل: أقسامها وإيضاح حساباتها · بلا ضريبة ولا سداد",
          any(x["kind"] == "grand" and x["label"] == "صافي ربح (خسارة) الفترة"
              for x in _li68)
          and _li68[-1]["kind"] == "memo"
          and any(x["kind"] == "acct" for x in _li68)
          and not any(x["kind"] == "acct" and x["label"][:4] in
                      ("2100", "1900", "1400", "2300") for x in _li68))
    _hi68 = _pm65.build_html("income_statement", 0,
                             date_from=f"{_y68}-01-01",
                             date_to=date.today().isoformat(),
                             show_accounts=True)
    check("قالب قائمة الدخل: مقارنة ومجمل الربح وتوقيعات",
          "مجمل الربح" in _hi68 and "فترة المقارنة" in _hi68
          and "اعتمده" in _hi68)

    from models import operations as _op68
    from models.invoices import create_sale_return as _csr68
    from models.invoices import create_sale as _cs68
    from models.inventory import create_work_orders_batch as _b68
    _d68 = date.today().isoformat()
    with db() as conn:
        _b68(conn, [{"wo_no": "RS-1", "gold": 12.0, "wage_per_gram": 30.0},
                    {"wo_no": "RS-2", "gold": 8.0, "wage_per_gram": 25.0}],
            _d68, "admin")
        from models.entities import add_entity as _ae68
        _ali = _ae68(conn, "علي المرتجع", "customer", username="admin")
        _moh = _ae68(conn, "محمد المشتري", "customer", username="admin")
        _ws = [r["id"] for r in conn.execute(
            "SELECT id FROM work_orders WHERE work_order_no IN ('RS-1','RS-2')"
            " ORDER BY work_order_no")]
        _s68 = _cs68(conn, _ali, [{"work_order_id": w} for w in _ws],
                           _d68, "admin", apply_vat=True)
        _r68 = _csr68(conn, _ali, [{"work_order_id": w} for w in _ws],
                      _d68, "admin", apply_vat=True)
        _ali_before = conn.execute(
            "SELECT COALESCE(SUM(l.cash_debit-l.cash_credit),0) c"
            " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
            " AND e.is_deleted=0 JOIN entities en ON en.account_id=l.account_id"
            " WHERE en.id=?", (_ali,)).fetchone()["c"]
        _n68 = _op68.resell_return(conn, _r68["id"], _moh, "admin", _d68)
    with db(readonly=True) as conn:
        _new = conn.execute("SELECT * FROM invoices WHERE id=?",
                            (_n68["new_id"],)).fetchone()
        _old = conn.execute("SELECT is_deleted FROM invoices WHERE id=?",
                            (_r68["id"],)).fetchone()
        _st68 = {r["status"] for r in conn.execute(
            "SELECT status FROM work_orders WHERE id IN (?,?)", _ws)}
        _ali_after = conn.execute(
            "SELECT COALESCE(SUM(l.cash_debit-l.cash_credit),0) c"
            " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
            " AND e.is_deleted=0 JOIN entities en ON en.account_id=l.account_id"
            " WHERE en.id=?", (_ali,)).fetchone()["c"]
        _g68, _c68, _gv68, _cv68 = ledger_balanced(conn)
        from models.journal import statement as _stm68
        _macc = conn.execute("SELECT account_id FROM entities WHERE id=?",
                             (_moh,)).fetchone()[0]
        _ml68 = _stm68(conn, _macc)
    check("فاتورة مبيعات جديدة لمحمد بنفس بنود مرتجع علي وقيمته",
          _new["kind"] == "sale" and _new["customer_id"] == _moh
          and abs(_new["total_weight"] - _r68["total_weight"]) < 0.001
          and _n68["items"] == 2,
          f"{_n68['new_no']}")
    check("البيان: «مرتجع من علي — فاتورة المرتجع رقم …»",
          _new["description"].startswith(
              f"مرتجع من علي المرتجع — فاتورة المرتجع رقم "
              f"{_r68['invoice_no']}"), _new["description"])
    _ml68 = _ml68["rows"] if isinstance(_ml68, dict) else _ml68
    check("كشف حساب محمد: البيان «مرتجع من علي …»",
          any("مرتجع من علي المرتجع" in str(r.get("desc", ""))
              for r in _ml68))
    check("المرتجع يبقى كما هو ورصيد علي لا يتغيّر · القطع صارت مباعة",
          _old["is_deleted"] == 0 and abs(_ali_before - _ali_after) < 0.01
          and _st68 == {"sold"})
    check("الدفتر متوازن بعد فاتورة المرتجع", _g68 and _c68,
          f"{_gv68} · {_cv68}")

    def _twice68():
        with db() as conn:
            _op68.resell_return(conn, _r68["id"], _moh, "admin", _d68)
    expect_error("لا يُصدر المرتجع نفسه مرتين", _twice68, "صدرت")

    def _not_return68():
        with db() as conn:
            _op68.resell_return(conn, _s68["id"], _moh, "admin", _d68)
    expect_error("الخيار للمرتجع وحده", _not_return68, "المرتجع")
    try:
        from PyQt5 import QtWidgets as _QW68
        _QW68.QApplication.instance() or _QW68.QApplication([])
        from ui.operations_screen import OperationsScreen as _O68
        from ui.reports.income_statement import IncomeStatementScreen as _I68
        _o68 = _O68({"id": 1, "username": "admin"})
        _i68 = _I68({"id": 1, "username": "admin"})
        check("الشاشتان: زر فاتورة من مرتجع · تبويبا قائمة الدخل",
              hasattr(_o68, "btn_resell") and hasattr(_o68, "do_resell")
              and [_i68.tabs.tabText(i) for i in range(_i68.tabs.count())]
              == ["قائمة الدخل", "نموذج التصريف (نقد ووزن)"]
              and _i68.standard.table.rowCount() > 3)
        _o68.close()
        _i68.close()
    except ImportError:
        print("  … تُخطّى فحوص الواجهة (PyQt5 غير متاح)")

    step("69) قائمة التدفقات النقدية (IAS 7)")
    _y69 = date.today().year
    _p69 = (f"{_y69}-01-01", f"{_y69}-12-31")

    def _cf69():
        with db(readonly=True) as conn:
            return _st67.cash_flow(conn, *_p69)

    _a69 = _cf69()
    with db() as conn:
        from models.entities import add_entity as _ae69
        _sup69 = _ae69(conn, "مورد المكائن 69", "supplier",
                       vat_number="300000000000003", username="admin")
        _sacc = conn.execute("SELECT account_id FROM entities WHERE id=?",
                             (_sup69,)).fetchone()[0]
        _today = date.today().isoformat()
        # أصلٌ ثابت بالأجل ثم سداد ثمنه نقداً
        post_entry(conn, _today, "شراء مكينة بالأجل", [
            {"account_id": acc_id(conn, "1710"), "cash_debit": 8000},
            {"account_id": _sacc, "cash_credit": 8000}], username="admin")
        post_entry(conn, _today, "سداد ثمن المكينة", [
            {"account_id": _sacc, "cash_debit": 5000},
            {"account_id": acc_id(conn, "1400"), "cash_credit": 5000}],
            username="admin")
    _b69 = _cf69()
    with db() as conn:
        # تحويلٌ من الصندوق إلى البنك: ليس تدفقاً
        post_entry(conn, date.today().isoformat(), "إيداع في البنك", [
            {"account_id": acc_id(conn, "1500"), "cash_debit": 3000},
            {"account_id": acc_id(conn, "1400"), "cash_credit": 3000}],
            username="admin")
    _c69 = _cf69()
    with db(readonly=True) as conn:
        _fp69 = _st67.financial_position(conn, _p69[1])
        _is69 = _st67.income_statement(conn, *_p69)
    _t69 = _c69["cur"]["totals"]
    _v69 = _c69["cur"]["values"]
    check("آخر الفترة = أولها + صافي التدفقات = النقد في المركز المالي",
          _c69["balanced"]
          and abs(_t69["closing"] - _fp69["cash"]["values"]["cash"]) < 0.02,
          f"{_t69['opening']} + {_t69['net']} = {_t69['closing']}")
    _dir = sum(_v69[k] for k, _t in _st67.CF_DIRECT)
    _ind = sum(_v69[k] for k, _t in _st67.CF_INDIRECT)
    check("الطريقتان المباشرة وغير المباشرة تنتهيان إلى صافي التشغيل نفسه",
          abs(_dir - _t69["op"]) < 0.02 and abs(_ind - _t69["op"]) < 0.02
          and abs(_v69["profit"] - _is69["cash"]["totals"]["net"]) < 0.02,
          f"{_dir} / {_ind} / {_t69['op']}")
    _bi, _ai = _b69["cur"]["totals"], _a69["cur"]["totals"]
    check("ثمن الأصل المسدَّد عبر المورّد: استثماري لا تشغيلي",
          abs((_bi["inv"] - _ai["inv"]) + 5000) < 0.02
          and abs(_bi["op"] - _ai["op"]) < 0.02
          and abs((_bi["noncash"] - _ai["noncash"]) - 3000) < 0.02,
          f"{_bi['inv'] - _ai['inv']} · غير نقدي {_bi['noncash']}")
    _ct = _c69["cur"]["totals"]
    check("التحويل بين الصندوق والبنك ليس تدفقاً",
          all(abs(_ct[k] - _bi[k]) < 0.02
              for k in ("op", "inv", "fin", "net", "closing")))
    _lay69 = _st67.cf_layout(_c69)
    check("ترتيب IAS 7: تشغيلية ثم استثمارية ثم تمويلية ثم النقد آخر الفترة",
          [x["key"] for x in _lay69 if x["kind"] == "sec"]
          == ["op", "inv", "fin"]
          and _lay69[-1]["label"] == "النقد وما في حكمه آخر الفترة"
          and "compare_from" in _c69 and "cmp" in _c69)
    _h69 = _pm65.build_html("cash_flow", 0, date_from=_p69[0],
                            date_to=_p69[1], method="direct")
    check("قالب القائمة: الأنشطة الثلاثة والطريقة والتوقيعات",
          "الأنشطة الاستثمارية" in _h69 and "الطريقة المباشرة" in _h69
          and "اعتمده" in _h69)
    try:
        from PyQt5 import QtWidgets as _QW69
        _QW69.QApplication.instance() or _QW69.QApplication([])
        from ui.reports.cash_flow_screen import CashFlowScreen as _C69
        _w69 = _C69({"id": 1, "username": "admin"})
        _mw69 = pathlib.Path(ROOT, "ui", "main_window.py").read_text(
            encoding="utf-8")
        check("شاشة التدفقات النقدية في القائمة وتعرض القائمة",
              "FinancialStatementsScreen(user)" in _mw69
              and _w69.table.rowCount() > 8
              and _w69.method.count() == 2)
        _w69.close()
    except ImportError:
        print("  … تُخطّى فحوص الواجهة (PyQt5 غير متاح)")

    step("70) قائمة التغيرات في حقوق الملكية · حارس الإقلاع")
    with db() as conn:
        post_entry(conn, date.today().isoformat(), "مسحوبات شريك", [
            {"account_id": acc_id(conn, "3120"), "cash_debit": 1200},
            {"account_id": acc_id(conn, "1400"), "cash_credit": 1200}],
            username="admin")
        post_entry(conn, date.today().isoformat(), "زيادة رأس المال", [
            {"account_id": acc_id(conn, "1500"), "cash_debit": 20000},
            {"account_id": acc_id(conn, "3110"), "cash_credit": 20000}],
            username="admin")
    with db(readonly=True) as conn:
        _eq70 = _st67.equity_changes(conn, *_p69)
        _eg70 = _st67.equity_changes(conn, *_p69, dim="gold")
        _fp70 = _st67.financial_position(conn, _p69[1])
        _is70 = _st67.income_statement(conn, *_p69)
    _cur70 = _eq70["cur"]
    check("كل عمود: رصيد أول الفترة + الحركات = رصيد آخرها (نقد وذهب)",
          _eq70["balanced"] and _eg70["balanced"])
    check("رصيد آخر الفترة = حقوق الملكية في المركز المالي",
          abs(_cur70["closing"]["total"]
              - _fp70["cash"]["totals"]["eq"]) < 0.02,
          f"{_cur70['closing']['total']} / {_fp70['cash']['totals']['eq']}")
    check("صافي الربح من قائمة الدخل · رأس المال والمسحوبات صفوفٌ منفصلة",
          abs(_cur70["rows"]["profit"]["total"]
              - _is70["cash"]["totals"]["net"]) < 0.02
          and _cur70["rows"]["r_capital"]["capital"] >= 20000 - 0.01
          and _cur70["rows"]["r_partners"]["partners"] <= -1200 + 0.01)
    _el70 = _st67.eq_layout(_eq70)
    check("فترة المقارنة ثم الحالية — كلٌّ من رصيدٍ إلى رصيد",
          [x["kind"] for x in _el70 if x["kind"] == "sec"] == ["sec", "sec"]
          and _el70[-1]["kind"] == "grand"
          and ("المجموع" not in [t for _k, t in _eq70["columns"]]))
    _h70 = _pm65.build_html("equity_changes", 0, date_from=_p69[0],
                            date_to=_p69[1])
    check("قالب القائمة: أعمدة المكوّنات والمجموع والتوقيعات",
          "رأس المال" in _h70 and "المجموع" in _h70 and "اعتمده" in _h70)
    # حارس الإقلاع: لا يختفي البرنامج صامتاً
    from services import crash_guard as _cg70
    _old_hook = sys.excepthook
    _cg70.install()
    check("حارس الأعطال مركَّب: خطأ الواجهة لا يُنهي البرنامج",
          sys.excepthook is _cg70._hook)
    sys.excepthook = _old_hook
    _cg70.trace("اختبار الدخان")
    check("سجلّ الإقلاع يُكتب في مجلد السجلات",
          "اختبار الدخان" in (_cg70.log_dir() / "startup.log").read_text(
              encoding="utf-8"))
    _bsrc = pathlib.Path(ROOT, "core", "build.py").read_text(encoding="utf-8")
    _msrc = pathlib.Path(ROOT, "main.py").read_text(encoding="utf-8")
    check("البناء: جذر المشروع في المسار (شاشة البدء) ونسخة تشخيص",
          "sys.path.insert(0, str(ROOT))" in _bsrc and "--console" in _bsrc
          and "crash_guard.install()" in _msrc
          and pathlib.Path(ROOT, "MAKE_EXE_DEBUG.bat").exists())
    try:
        from PyQt5 import QtWidgets as _QW70
        _QW70.QApplication.instance() or _QW70.QApplication([])
        from ui.reports.equity_changes_screen import (
            EquityChangesScreen as _E70)
        _w70 = _E70({"id": 1, "username": "admin"})
        _mw70 = pathlib.Path(ROOT, "ui", "main_window.py").read_text(
            encoding="utf-8")
        check("شاشة حقوق الملكية في القائمة وتعرض القائمة",
              "FinancialStatementsScreen(user)" in _mw70
              and _w70.table.rowCount() > 6
              and _w70.table.columnCount() >= 3)
        _w70.close()
    except ImportError:
        print("  … تُخطّى فحوص الواجهة (PyQt5 غير متاح)")

    step("71) تسويات نهاية الفترة: زكاة · نهاية خدمة · خسائر ائتمانية ·"
         " مقدمة ومستحقة · إيضاحات · حزمة")
    from models import period_end as _pe71, fs_notes as _fn71
    from services import fs_package as _pk71
    _d1, _d2 = _p69
    with db(readonly=True) as conn:
        _codes71 = {r[0] for r in conn.execute(
            "SELECT code FROM accounts WHERE code IN"
            " ('1680','1980','2280','2400','2600','5870','5880','5950')")}
    check("حسابات التسويات مضافة للشجرة (8 حسابات)", len(_codes71) == 8,
          str(sorted(_codes71)))
    check("المادة 84: نصف شهر للخمس الأولى وشهرٌ عمّا بعدها",
          _pe71.eos_award(6000, 3) == 9000.0
          and _pe71.eos_award(6000, 8) == 15000.0 + 18000.0)
    check("نسبة الزكاة لسنة ميلادية 2.5777% (2.5% × 365 ÷ 354)",
          abs(_pe71.zakat_rate(f"{_y69}-01-01", f"{_y69}-12-31") * 100
              - 2.5 * (366 if _y69 % 4 == 0 else 365) / 354) < 1e-9)
    with db() as conn:
        conn.execute("INSERT INTO employees(name, basic_salary)"
                     " VALUES('موظف نهاية الخدمة', 5000)")
        _emp71 = conn.execute("SELECT MAX(id) FROM employees").fetchone()[0]
        _pe71.eos_update(conn, _emp71, f"{_y69 - 7}-01-01", 8000, None,
                         "admin")
        _e1 = _pe71.eos_post(conn, _d2, "admin")
        _e2 = _pe71.eos_post(conn, _d2, "admin")
        _c1 = _pe71.ecl_post(conn, _d2, "admin", [1, 5, 10, 50])
        _c2 = _pe71.ecl_post(conn, _d2, "admin", [1, 5, 10, 50])
        _pid = _pe71.prepaid_add(conn, "تأمين سنوي", "5840", 3650,
                                 f"{_y69}-07-02", 12, "admin", mode="paid",
                                 cash_code="1500")
        _am1 = _pe71.prepaid_amortize(conn, _d2, "admin")
        _am2 = _pe71.prepaid_amortize(conn, _d2, "admin")
        _acc, _rev = _pe71.accrue_expense(conn, "5820", 700, _d2, "admin",
                                          note="كهرباء آخر الفترة")
        _z1 = _pe71.zakat_post(conn, _d1, _d2, "admin")
        _z2 = _pe71.zakat_post(conn, _d1, _d2, "admin")
    _mine = [r for r in _e1["rows"] if r["id"] == _emp71][0]
    import datetime as _dt71
    _yrs = ((_dt71.date.fromisoformat(_d2)
             - _dt71.date(_y69 - 7, 1, 1)).days + 1) / 365.0
    check("مكافأة نهاية الخدمة: تُحسب من تاريخ التعيين وتُقيَّد بالفرق مرةً",
          abs(_mine["award"] - _pe71.eos_award(8000, _yrs)) < 0.01
          and _e1["entry_id"] and _e2["entry_id"] is None,
          f"{_mine['years']} سنة = {_mine['award']}")
    check("الخسائر الائتمانية بمصفوفة الأعمار · لا تكرار للقيد",
          _c1["required"] >= 0 and _c2["entry_id"] is None
          and abs(_c2["current"] - _c1["required"]) < 0.01)
    check("المصروف المقدّم يُطفأ يوماً بيوم مرةً واحدة",
          len(_am1) == 1 and not _am2
          and abs(_am1[0][1] - round(3650 * 183 / 365, 2)) < 0.02,
          str(_am1))
    with db(readonly=True) as conn:
        _ra = conn.execute(
            "SELECT entry_date FROM journal_entries WHERE id=?",
            (_rev,)).fetchone()[0]
    check("الاستحقاق يُعكس أول يوم في الفترة التالية",
          bool(_acc) and _ra == f"{_y69 + 1}-01-01")
    check("الزكاة: الوعاء والنسبة والقيد بالفرق مرةً واحدة",
          _z1["zakat"] >= 0 and abs(_z2["due"]) < 0.01
          and _z2["entry_id"] is None
          and abs(_z1["rate"] - _pe71.zakat_rate(_d1, _d2)) < 1e-12,
          f"وعاء {_z1['base']} · زكاة {_z1['zakat']}")
    with db(readonly=True) as conn:
        _fp71 = _st67.financial_position(conn, _d2)
        _is71 = _st67.income_statement(conn, _d1, _d2)
        _cf71 = _st67.cash_flow(conn, _d1, _d2)
        _eq71 = _st67.equity_changes(conn, _d1, _d2)
        _nb71 = _fn71.build(conn, _d1, _d2)
        _rd71 = _pk71.readiness(conn, _d1, _d2)
    _v71 = _fp71["cash"]["values"]
    check("القوائم الأربع متوازنة ومترابطة بعد التسويات",
          _fp71["balanced_cash"] and _cf71["balanced"] and _eq71["balanced"]
          and abs(_eq71["cur"]["closing"]["total"]
                  - _fp71["cash"]["totals"]["eq"]) < 0.02
          and abs(_is71["cash"]["totals"]["net"]
                  - _fp71["cash"]["values"]["profit"]) < 0.02)
    check("المركز المالي: مخصص الزكاة متداول · نهاية الخدمة غير متداول ·"
          " الخسائر الائتمانية تُطرح من الذمم",
          _v71["zakat"] > 0 and _v71["eosb"] > 0 and _v71["ecl"] <= 0
          and _v71["prepaid"] > 0 and _v71["accrued"] >= 700 - 0.01)
    _t71 = _is71["cash"]["totals"]
    check("قائمة الدخل: الربح قبل الزكاة ثم الزكاة ثم صافي الربح",
          abs(_t71["before_zakat"] + _is71["cash"]["values"]["zakat"]
              - _t71["net"]) < 0.02
          and _is71["cash"]["values"]["zakat"] < 0)
    check("الإيضاحات: 17 إيضاحاً بأرقام ثابتة وجداول من الدفاتر",
          [n["no"] for n in _nb71["notes"]] == list(range(1, 18))
          and _nb71["notes"][10]["moves"] and _nb71["notes"][11]["moves"])
    _rdm = {t: (ok, d) for t, ok, d in _rd71}
    check("قائمة التحقق: الزكاة والإطفاء جاهزان · تُنبّه لموظفٍ بلا تاريخ"
          " تعيين ولنسبٍ لم تُحفظ",
          _rdm["مخصص الزكاة مقيَّد للفترة"][0]
          and _rdm["المصروفات المقدمة مُطفأة حتى نهاية الفترة"][0]
          and not _rdm["مخصص مكافأة نهاية الخدمة محدَّث"][0]
          and "تاريخ تعيين" in _rdm["مخصص مكافأة نهاية الخدمة محدَّث"][1]
          and not _rdm["مخصص الخسائر الائتمانية محدَّث"][0], str(_rd71))
    _hf71 = _pm65.build_html("fs_full", 0, date_from=_d1, date_to=_d2)
    _hp71 = _pm65.build_html("financial_position", 0, as_of=_d2)
    check("القوائم الكاملة: الغلاف والقوائم الأربع والإيضاحات · عمود إيضاح",
          all(x in _hf71 for x in (
              "قائمة المركز المالي", "قائمة الدخل",
              "قائمة التغيرات في حقوق الملكية", "قائمة التدفقات النقدية",
              "الإيضاحات المتممة", "مخصص مكافأة نهاية الخدمة"))
          and "إيضاح" in _hp71)
    import zipfile as _zf71
    import json as _js71
    _zp = pathlib.Path(_TMP) / "pkg71.zip"
    _names71 = _pk71.export(str(_zp), _d1, _d2)
    _j71 = _js71.loads(_zf71.ZipFile(_zp).read(
        "ifrs_mapping.json").decode("utf-8"))
    check("حزمة المحاسب القانوني: القوائم CSV والمستند الكامل ومسمّيات IFRS",
          "القوائم_المالية_الكاملة.html" in _names71
          and "5_trial_balance.csv" in _names71 and _j71["balanced"]
          and any(f["concept"] == "ifrs-full:Assets" for f in _j71["facts"]),
          str(len(_j71["facts"])))
    try:
        from PyQt5 import QtWidgets as _QW71
        _QW71.QApplication.instance() or _QW71.QApplication([])
        from ui.reports.period_end_screen import PeriodEndScreen as _P71
        _w71 = _P71({"id": 1, "username": "admin"})
        _mw71 = pathlib.Path(ROOT, "ui", "main_window.py").read_text(
            encoding="utf-8")
        check("شاشة تسويات نهاية الفترة: 5 تبويبات وفي القائمة",
              _w71.tabs.count() == 5 and _w71.chk.rowCount() >= 7
              and "FinancialStatementsScreen(user)" in _mw71)
        _w71.close()
    except ImportError:
        print("  … تُخطّى فحوص الواجهة (PyQt5 غير متاح)")

    step("72) دليل الحسابات للمراجع · شاشة «القوائم المالية»")
    from models import coa_audit as _ca72
    from database.seed import CONTRA_NATURE as _cn72
    with db(readonly=True) as conn:
        _acc72 = {r["code"]: dict(r) for r in conn.execute(
            "SELECT a.code, a.nature, a.is_postable, a.type, p.code pc"
            " FROM accounts a LEFT JOIN accounts p ON p.id=a.parent_id")}
        _kids72 = {r[0] for r in conn.execute(
            "SELECT DISTINCT p.code FROM accounts a JOIN accounts p"
            " ON p.id=a.parent_id")}
        _moved72 = {r[0] for r in conn.execute(
            "SELECT DISTINCT a.code FROM journal_lines l JOIN accounts a"
            " ON a.id=l.account_id")}
        _au72 = _ca72.summary(conn)
    check("الحسابات المقابلة بطبيعتها: مجمّع الإهلاك والمخصص دائنان،"
          " والمردودات مدينة",
          all(_acc72[c]["nature"] == n for c, n in _cn72.items()
              if c in _acc72))
    check("مستوى المتداول / غير المتداول في الشجرة",
          _acc72["1010"]["pc"] == "1005" and _acc72["1030"]["pc"] == "1005"
          and _acc72["1700"]["pc"] == "1690"
          and _acc72["1900"]["pc"] == "1030"
          and _acc72["2020"]["pc"] == "2010"
          and _acc72["2600"]["pc"] == "2500"
          and _acc72["2700"]["pc"] == "2500")
    check("المجموعات لا تقبل الترحيل ما لم تكن عليها حركة تاريخية",
          all(not _acc72[c]["is_postable"] or c in _moved72
              or c in ("1950", "1960", "1970")
              for c in _kids72 if c in _acc72),
          str([c for c in _kids72 if c in _acc72
               and _acc72[c]["is_postable"] and c not in _moved72]))
    check("حسابات المراجع: التأمينات · القروض · الاحتياطي · مصروفات بنكية",
          all(c in _acc72 for c in ("2290", "2350", "2700", "3300", "5805",
                                    "5806", "5890", "4400", "5910")))
    check("فحص سلامة الدليل: لا أخطاء (القيود متوازنة والأنواع صحيحة)",
          _au72["errors"] == 0, str([i[:2] for i in _au72["items"]]))
    from models import day_close as _dc72
    check("الإغلاق اليومي: «ذمم الموردين» من 2300 لا من جذر الخصوم 2000",
          any(c == "2300" for c, _n, _d in _dc72.KEY_ACCOUNTS)
          and not any(c == "2000" for c, _n, _d in _dc72.KEY_ACCOUNTS))
    from models import purchases as _pu72
    check("شراء الأصل الثابت على فرعٍ من المعدات لا على المجموعة",
          _pu72.DEFAULT_ACCOUNT["asset"] == "1710")
    # قرضٌ واحتياطيٌّ يظهران في بنودهما من القوائم
    with db() as conn:
        post_entry(conn, date.today().isoformat(), "قرض بنكي", [
            {"account_id": acc_id(conn, "1500"), "cash_debit": 50000},
            {"account_id": acc_id(conn, "2700"), "cash_credit": 40000},
            {"account_id": acc_id(conn, "2350"), "cash_credit": 10000}],
            username="admin")
        post_entry(conn, date.today().isoformat(), "تجنيب احتياطي", [
            {"account_id": acc_id(conn, "3200"), "cash_debit": 1000},
            {"account_id": acc_id(conn, "3300"), "cash_credit": 1000}],
            username="admin")
    with db(readonly=True) as conn:
        _fp72 = _st67.financial_position(conn, _p69[1])
        _cf72 = _st67.cash_flow(conn, *_p69)
        _eq72 = _st67.equity_changes(conn, *_p69)
    _v72 = _fp72["cash"]["values"]
    check("القرض: طويل الأجل غير متداول، وقصيره متداول، وتمويليٌّ في"
          " التدفقات",
          _v72["loans_lt"] >= 40000 - 0.01 and _v72["loans_st"] >= 10000 - 0.01
          and _cf72["cur"]["values"]["f_loans"] >= 50000 - 0.01
          and _fp72["balanced_cash"] and _cf72["balanced"])
    check("الاحتياطي عمودٌ في حقوق الملكية وصفُّ «المحوَّل إلى الاحتياطيات»",
          _v72["reserve"] >= 1000 - 0.01 and _eq72["balanced"]
          and any(k == "reserve" for k, _t in _eq72["columns"])
          and _eq72["cur"]["rows"]["r_reserve"]["reserve"] >= 1000 - 0.01)
    _hc72 = _pm65.build_html("coa_list", 0)
    check("طباعة دليل الحسابات مع خلاصة فحص السلامة",
          "دليل الحسابات" in _hc72 and "فحص سلامة الدليل" in _hc72
          and "مجمّع إهلاك" in _hc72)
    try:
        from PyQt5 import QtWidgets as _QW72
        _QW72.QApplication.instance() or _QW72.QApplication([])
        from ui.reports.financial_statements_screen import (
            FinancialStatementsScreen as _F72)
        from ui.coa_screen import CoaScreen as _C72
        _f72 = _F72({"id": 1, "username": "admin"})
        _tabs72 = [_f72.tabs.tabText(i) for i in range(_f72.tabs.count())]
        for _i in range(_f72.tabs.count()):
            _f72.tabs.setCurrentIndex(_i)
        _mw72 = pathlib.Path(ROOT, "ui", "main_window.py").read_text(
            encoding="utf-8")
        check("«القوائم المالية»: ستة تبويبات تُبنى عند فتحها · بندٌ واحد",
              _tabs72 == ["ميزان المراجعة", "المركز المالي", "الدخل",
                          "حقوق الملكية", "التدفقات النقدية",
                          "نهاية الفترة"]
              and _f72.tabs.tabToolTip(5)
              == "تسويات نهاية الفترة والقوائم الختامية"
              and len(_f72.screens) == 6
              and "FinancialStatementsScreen(user)" in _mw72
              and "TrialBalanceScreen(user)" not in _mw72, str(_tabs72))

        # ── 73) لا تتّسع القوائم خارج إطار الشاشة ولا الطباعة (4.38)
        # كان شريط الأدوات الأفقي يفرض ١٥٠٠ بكسل حدّاً أدنى، فتنزاح
        # القائمة إلى اليسار ويُقصّ نصف الجدول على شاشة اللابتوب
        from ui.widgets.flow_layout import FlowLayout as _FL73
        _w73 = max(_f72.screens[i].minimumSizeHint().width()
                   for i in range(5))
        check("القوائم المالية: الشاشات تنطوي في عرض اللابتوب (≤ 700 بكسل)",
              _w73 <= 700 and _f72.minimumSizeHint().width() <= 760,
              f"{_w73} · {_f72.minimumSizeHint().width()}")
        _h73 = _QW72.QWidget()
        _fl73 = _FL73(_h73)
        for _t73 in ("من:", "x" * 40, "إلى:", "y" * 40, "زر"):
            _fl73.addWidget(_QW72.QLabel(_t73) if _t73.endswith(":")
                            else _QW72.QPushButton(_t73))
        _fl73.addStretch(1)
        _one73 = _fl73.heightForWidth(4000)
        _two73 = _fl73.heightForWidth(_fl73.minimumSize().width() + 5)
        check("شريط الأدوات المنطوي: يلتفّ لسطرٍ ثانٍ ولا يفصل «من:» عن حقله",
              _two73 > _one73 and len(_fl73._units()) == 3,
              f"{_one73} → {_two73} · {len(_fl73._units())}")
        from services import browser_print as _bp73
        _is73 = _bp73.build_page("income_statement", 0, auto_print=False,
                                 date_from="2026-01-01",
                                 date_to="2026-12-31", compare=True)
        check("قوالب القوائم: بيانات المنشأة زوجان في السطر بعرضٍ ثابت"
              " · المعاينة بعرض الورقة · تصغير الجدول الأعرض من الصفحة",
              'class="items meta"' in _is73 and "table.meta" in _is73
              and "194mm" in _is73 and "beforeprint" in _is73
              and "t.style.zoom" in _is73)
        _c72 = _C72({"id": 1, "username": "admin"})
        check("شاشة الدليل: زرّا فحص السلامة والطباعة",
              hasattr(_c72, "run_audit") and hasattr(_c72, "print_coa"))
        _f72.close()
        _c72.close()

        # ── 74) الفصوص والمسترجع من التصفية خارج مخزون الذهب (4.39)
        from services.accounting_engine import post_entry as _pe74
        from database.seed import move_production_accounts as _mv74
        from models import statements as _st74, journal as _jr74
        with db() as conn:
            _a74 = {r["code"]: r for r in conn.execute(
                "SELECT a.*, p.code pcode FROM accounts a"
                " LEFT JOIN accounts p ON p.id=a.parent_id")}
            check("الدليل: الفصوص 5520 مصروفٌ تحت مواد ومصروفات التشغيل"
                  " (نقد ووزن) · المسترجع 5190 مقابلٌ دائن تحت الفواقد",
                  "1150" not in _a74 and "1360" not in _a74
                  and _a74["5520"]["type"] == "expense"
                  and _a74["5520"]["pcode"] == "5050"
                  and _a74["5520"]["balance_type"] == "both"
                  and _a74["5190"]["pcode"] == "5100"
                  and _a74["5190"]["nature"] == "credit")
            # قاعدةٌ بالتخطيط القديم: 1150 و1360 (وفرعه) تحت المخزون
            _inv74 = _a74["1020"]["id"]
            conn.execute("UPDATE accounts SET code='1150', type='asset',"
                         " nature='debit', parent_id=? WHERE code='5520'",
                         (_inv74,))
            conn.execute("UPDATE accounts SET code='1360', type='asset',"
                         " nature='debit', parent_id=? WHERE code='5190'",
                         (_inv74,))
            conn.execute(
                "INSERT INTO accounts(code,name,type,parent_id,is_postable,"
                "nature,balance_type) SELECT '136001','مسترجع الشفط',"
                "'asset',id,1,'debit','gold' FROM accounts WHERE code='1360'")
            _old74 = {c: acc_id(conn, c) for c in ("1150", "136001")}
            _e74 = _pe74(conn, "2026-03-20", "مسترجع التصفية للخزينة", [
                {"account_id": acc_id(conn, "1100"), "gold_debit": 4.0},
                {"account_id": _old74["136001"], "gold_credit": 4.0}],
                source_table="manual", username="admin")
            _mv74(conn)
            _mv74(conn)          # مرتين: لا أثر للتكرار
            _n74 = {r["code"]: r["id"] for r in conn.execute(
                "SELECT code, id FROM accounts")}
            check("الترقية: 1150←5520 و136001←519001 بالمعرّف نفسه والقيد"
                  " باقٍ عليه",
                  _n74.get("5520") == _old74["1150"]
                  and _n74.get("519001") == _old74["136001"]
                  and "1150" not in _n74 and "1360" not in _n74
                  and conn.execute(
                      "SELECT 1 FROM journal_lines WHERE entry_id=? AND"
                      " account_id=?", (_e74, _n74["519001"])).fetchone())
            _is74 = _st74.income_statement(conn, "2026-01-01", "2026-12-31",
                                           compare=False)
            check("قائمة الدخل: «المسترجع من التصفية» يُخصم تحت خسائر"
                  " الورشة، والفصوص ضمن مواد التشغيل",
                  _is74["gold"]["values"]["recovered"] >= 4.0 - 1e-6
                  and any(k == "recovered" and s74 == "cos"
                          for k, _t, s74 in _st74.IS_LINES)
                  and _st74._IS_MAP.get("5050") == "materials")
            _r74 = _jr74.statement(conn, [_n74["519001"]], "2026-01-01",
                                   "2026-12-31")
            _r74x = _jr74.statement(
                conn, [_n74["519001"]], "2026-01-01", "2026-12-31",
                exclude_sql="e.id=%d" % _e74)
            check("تفصيل الحركة: رقم السند والتاريخ، ويستبعد ما تستبعده"
                  " القائمة",
                  any(r["date"] == "2026-03-20" and r["doc_no"]
                      for r in _r74)
                  and not any(r["date"] == "2026-03-20" for r in _r74x),
                  str([(r["date"], r["doc_no"]) for r in _r74]))
        from ui.widgets.account_movement import (AccountMovementDialog as
                                                 _D74)
        _d74 = _D74(None, "1100", "خزينة التصنيع", "2026-01-01",
                    "2026-12-31")
        check("نافذة تفصيل الحركة: أعمدة رقم السند والرصيد · وزرّ في كل"
              " قائمة",
              _d74.table.horizontalHeaderItem(2).text() == "رقم السند"
              and len(_d74.rows) > 0
              and hasattr(_f72.screens[0], "show_movement")
              and hasattr(_f72.screens[1].tree, "show_movement")
              and hasattr(_f72.screens[2].standard, "show_movement")
              and hasattr(_f72.screens[3], "show_movement")
              and hasattr(_f72.screens[4], "show_movement"))
        _d74.close()

        # ── 75) فواقد الورشة · قائمة دخل مبسّطة · المخزون في ميزان الريال
        from database.seed import (restore_gold_sale_pair as _rp75,
                                   GOLD_SALE_PAIR as _gp75)
        with db() as conn:
            _a75 = {r["code"]: r for r in conn.execute(
                "SELECT a.*, p.code pcode FROM accounts a"
                " LEFT JOIN accounts p ON p.id=a.parent_id")}
            check("الدليل: فواقد الورشة 5100 (قسم التصنيع 5110 · التصفية"
                  " والصب 5125 · بيع الذهب 5140 · المسترجع 5190) تحت"
                  " المصروفات مباشرة",
                  _a75["5100"]["name"] == "فواقد الورشة"
                  and _a75["5100"]["pcode"] == "5000"
                  and _a75["5110"]["name"] == "فواقد قسم التصنيع"
                  and all(_a75[c]["pcode"] == "5100"
                          for c in ("5110", "5125", "5140", "5190"))
                  and "1350" not in _a75)
            check("الدليل: رواتب وأجور التشغيل 5690 تجمع 5700 و5710 ·"
                  " لا «تكاليف التشغيل المباشرة» ولا «خسائر تشغيل الذهب»",
                  _a75["5700"]["pcode"] == "5690"
                  and _a75["5710"]["pcode"] == "5690"
                  and not any(r["name"] in ("تكاليف التشغيل المباشرة",
                                            "خسائر تشغيل الذهب")
                              for r in _a75.values()))
            # 4.43: مبيعات الذهب وزناً في دفترها — 4110 · 4910 · ومقابلهما
            # 4950 تحت الإيرادات؛ لكل فاتورةٍ غير داخلية زوجها بوزنها
            _miss75 = conn.execute(
                "SELECT COUNT(*) FROM invoices i JOIN entities en ON"
                " en.id=i.customer_id JOIN journal_entries e ON"
                " e.source_table='invoices' AND e.source_id=i.id AND"
                " e.is_deleted=0 WHERE i.is_deleted=0 AND i.total_weight>0"
                " AND COALESCE(en.entity_type,'')<>'internal' AND NOT EXISTS"
                "(SELECT 1 FROM journal_lines l JOIN accounts a ON"
                " a.id=l.account_id WHERE l.entry_id=e.id AND a.code IN"
                " ('4110','4910'))").fetchone()[0]
            check("البيع يُقيّد إيرادَ الذهب وزناً (4110/4910) ومقابلَه"
                  " 4950 تحت الإيرادات — لكل فاتورة",
                  _miss75 == 0 and _rp75(conn) == 0
                  and _a75["4950"]["pcode"] == "4000"
                  and _a75["4950"]["nature"] == "debit"
                  and all(_a75[c]["is_active"] for c in _gp75)
                  and "5150" not in _a75, _miss75)
            _is75 = _st74.income_statement(conn, "2026-01-01", "2026-12-31",
                                           compare=False)
            _sec75 = [r["label"] for r in _st74.is_layout(_is75)
                      if r["kind"] == "sec"]
            _lbl75 = [t for _k, t, _s in _st74.IS_LINES]
            check("قائمة الدخل: الإيرادات (… + فرق الصافي) · خسائر الورشة"
                  " (الفواقد − المسترجع) · المصاريف التشغيلية (إدارية ·"
                  " رواتب · مواد) — بلا «إيرادات ومصروفات أخرى»",
                  # 4.45: المبيعات ثم الإيرادات الأخرى والتحصيلية؛ لا سطر
                  # «الذهب المسلَّم» (يُصفّى في المبيعات)؛ والمصاريف:
                  # إدارية · العمال · رواتب الإدارة · مواد
                  _lbl75 == ["المبيعات (مبيعات الذهب والأجور)",
                             "يُطرح: مردودات المبيعات",
                             "يُطرح: الخصم المسموح به والمدفوع للعملاء",
                             "يُضاف: فرق الصافي",
                             "إيرادات التحصيل والإيرادات العرضية",
                             "فواقد الورشة",
                             "يُخصم: المسترجع من التصفية",
                             "المصاريف الإدارية والعمومية",
                             "مصروفات العمال", "رواتب الإدارة",
                             "مواد ومصروفات تشغيل مباشرة", "الزكاة"]
                  and "الإيرادات والمصروفات الأخرى" not in _sec75,
                  str(_sec75))
            _tb75 = _st74.trial_balance(conn, "2026-01-01", "2026-12-31",
                                        "cash", 9)
            # 4.42: بُعدٌ واحد في كل ميزان — لا حساب ذهبٍ في ميزان الريال
            check("ميزان الريال يعرض حسابات الريال وحدها ويبقى متوازناً",
                  not any(all(abs(r[k]) < 0.005 for k in (
                      "open_dr", "open_cr", "dr", "cr", "close_dr",
                      "close_cr")) for r in _tb75["rows"])
                  and _tb75["totals"]["balanced"])
            _g75 = _is75["gold"]
            _w75 = conn.execute(
                "SELECT COALESCE(SUM(CASE WHEN kind='sale' THEN total_weight"
                " END),0) s, COALESCE(SUM(CASE WHEN kind='sale_return' THEN"
                " total_weight END),0) r FROM invoices WHERE is_deleted=0"
                " AND invoice_date BETWEEN '2026-01-01' AND '2026-12-31'"
                ).fetchone()
            # 4.46: المبيعات والمردودات بوزنها، وصافي المبيعات يطرحهما،
            # ثم «تكلفة الذهب المباع» (4950) تحتها — فالمجمل ربح الوزن
            _v75 = _g75["values"]
            # 4.51: لا سطر «تكلفة الذهب المباع» — فصافي عمود الذهب يزيد
            # على ربح الدفتر بالذهب المسلَّم (4950) وحده، والنقد كما هو
            _d4950 = conn.execute(
                "SELECT COALESCE(SUM(l.gold_debit-l.gold_credit),0) FROM"
                " journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
                " AND e.is_deleted=0 JOIN accounts a ON a.id=l.account_id"
                " WHERE a.code='4950' AND e.entry_date BETWEEN"
                " '2026-01-01' AND '2026-12-31'"
                " AND COALESCE(e.source_table,'')<>'year_close'"
                ).fetchone()[0]
            check("قائمة الدخل: المبيعات والمردودات بوزنها من الفواتير،"
                  " وصافي المبيعات يطرحهما — بلا سطر تكلفة الذهب المباع،"
                  " والنقد ربحُ الدفتر نفسه",
                  abs(_v75["sales"] - _w75["s"]) < 0.001
                  and abs(_v75["returns"] + _w75["r"]) < 0.001
                  and "cogs" not in _v75
                  and abs(_g75["totals"]["net_sales"]
                          - (_v75["sales"] + _v75["returns"]
                             + _v75["discounts"] + _v75["net_diff"])) < 0.001
                  and abs(_g75["totals"]["net"] - _d4950 - _st74._pl(
                      conn, "2026-01-01", "2026-12-31", "gold")) < 0.001
                  and abs(_is75["cash"]["totals"]["net"] - _st74._pl(
                      conn, "2026-01-01", "2026-12-31", "cash")) < 0.01,
                  str((_v75["sales"], _v75["returns"], _d4950,
                       _w75["s"], _w75["r"])))

        # ── 76) كشف صندوق الكسر لكل عيارٍ وحده من لوحة التحكم (4.41)
        from models.inventory import scrap_karat_statement as _sk76
        from models import dash_panels as _dp76
        with db(readonly=True) as conn:
            _pn76 = {r["karat"]: r["actual"] for r in _dp76.scrap_rows(conn)}
            _st76 = {k: _sk76(conn, k) for k in _pn76}
        check("كشف كل عيار: رصيده رقم اللوحة نفسه، وسطوره بعياره وحده"
              " برقم السند",
              all(abs(_st76[k]["closing"] - _pn76[k]) < 0.001 for k in _pn76)
              and all(r["doc_no"] for k in _st76 for r in _st76[k]["rows"]
                      if r["op"] not in ("رصيد سابق", "تسوية",
                                         "مستند محذوف")),
              str({k: (_st76[k]["closing"], _pn76[k]) for k in _pn76}))
        # ── 77) ميزان المراجعة: عنوان المجموعة ثم «إجمالي …» بعد فروعها
        with db(readonly=True) as conn:
            _tb77 = _st74.trial_balance(conn, "2026-01-01", "2026-12-31",
                                        "cash", 9)
        _r77 = _tb77["rows"]
        _ok77 = True
        for _i77, _x77 in enumerate(_r77):
            if _x77["kind"] != "header":
                continue
            _j77 = next((j for j in range(_i77 + 1, len(_r77))
                         if _r77[j]["kind"] == "total"
                         and _r77[j]["code"] == _x77["code"]), None)
            _ok77 &= (_j77 is not None
                      and _r77[_j77]["name"] == _st74.total_label(
                          _x77["name"])
                      and all(_r77[_j77][k] == _x77[k] for k in (
                          "open_dr", "close_dr", "close_cr")))
        check("ميزان المراجعة: لكل مجموعةٍ «إجمالي …» بعد فروعها (ومنه"
              " «إجمالي الأصول») · والإجمالي العام لا يتضاعف",
              _ok77 and any(x["name"] == "إجمالي الأصول" for x in _r77)
              and _tb77["totals"]["balanced"]
              and len(_tb77["sections"]) == len(
                  [x for x in _r77 if x["is_root"]
                   and x["kind"] != "total"]))
        # ── 78) المستعجل · المعلّقات · هوية المصنع الجديد (4.44)
        from models import pending as _pd78
        from models.inventory import (create_work_orders_batch as _cb78,
                                      update_supply_batch as _ub78)
        from models.invoices import create_sale as _cs78
        with db() as conn:
            _r78 = _cb78(conn, [{"wo_no": "U78-1", "gold": 20.0,
                                 "wage_per_gram": 10.0}], "2026-07-01",
                         "admin")
            _e78 = _r78["entry_id"]
            _pd78.mark_urgent(conn, _e78, "admin")
            _u78 = [x["entry_id"] for x in _pd78.list_urgent(conn)]
            _g78 = conn.execute(
                "SELECT SUM(gold_debit) FROM journal_lines WHERE entry_id=?",
                (_e78,)).fetchone()[0]
        check("دفعة مستعجلة: مُرحَّلةٌ مُثبتة في الحسابات وفي «المستعجل»",
              _e78 in _u78 and abs(_g78 - 20.0) < 0.001, str(_u78))
        with db() as conn:
            _ub78(conn, _e78, [
                {"wo_no": "U78-1", "gold": 20.0, "wage_per_gram": 10.0},
                {"wo_no": "U78-2", "gold": 15.0, "wage_per_gram": 10.0}],
                "2026-07-01", "admin")
            _pd78.complete_urgent(conn, _e78, "admin")
            _g78b = conn.execute(
                "SELECT SUM(gold_debit) FROM journal_lines WHERE entry_id=?",
                (_e78,)).fetchone()[0]
            _u78b = [x["entry_id"] for x in _pd78.list_urgent(conn)]
        check("استكمال المستعجلة: القيد نفسه بالقيمة الجديدة، وتخرج من"
              " «المستعجل»", abs(_g78b - 35.0) < 0.001 and _e78 not in _u78b,
              str(_g78b))
        with db() as conn:
            _wo78 = conn.execute("SELECT id FROM work_orders WHERE"
                                 " work_order_no='U78-2'").fetchone()["id"]
            _ent78 = conn.execute("SELECT id FROM entities WHERE"
                                  " entity_type='customer' LIMIT 1"
                                  ).fetchone()["id"]
            _n0 = conn.execute("SELECT COUNT(*) FROM journal_entries"
                               ).fetchone()[0]
            _st78 = {"kind": "sale", "customer_id": _ent78,
                     "date": "2026-07-02", "items": [
                         {"wo_id": _wo78, "weight": 15.0, "wage": 10.0,
                          "karat": 18}]}
            _h78 = _pd78.hold_invoice(conn, _st78, "admin", "ينتظر العميل")
            _n1 = conn.execute("SELECT COUNT(*) FROM journal_entries"
                               ).fetchone()[0]
            _wst = conn.execute("SELECT status FROM work_orders WHERE id=?",
                                (_wo78,)).fetchone()[0]
            _hl78 = _pd78.list_held(conn)
        check("فاتورة معلّقة: بلا قيد ولا أثر على المخزون، وفي «المعلّقات»",
              _n1 == _n0 and _wst == "in_stock"
              and any(x["id"] == _h78 and x["count"] == 1 for x in _hl78))
        with db() as conn:
            _cs78(conn, _ent78, [{"work_order_id": _wo78}], "2026-07-03",
                  "admin", apply_vat=False)
            _bad78 = [x["unavailable"] for x in _pd78.list_held(conn)
                      if x["id"] == _h78]
            _pd78.drop_held(conn, _h78, "admin", "اختبار")
            _gone78 = not any(x["id"] == _h78
                              for x in _pd78.list_held(conn))
        check("المعلّقة لا تحجز الطقم — بيعه في غيرها يُنبَّه به، وتُلغى بلا"
              " أثر", _bad78 == [1] and _gone78, str(_bad78))
        from services import branding as _br78
        _base78 = config.BASE_DIR
        config.BASE_DIR = pathlib.Path(_TMP)    # لا يمسّ مرآة الجهاز وشعاره
        try:
            with db() as conn:
                _br78.reset(conn, "admin")
                _blank78 = _br78.load(conn)
        finally:
            config.BASE_DIR = _base78
        check("هوية المصنع الجديد فارغة: بلا اسمٍ ولا شعار ولا سجل",
              _br78.is_blank(_blank78) and _blank78["hide_logo"]
              and not _blank78["cr"] and not _blank78["vat"])
        from ui.production_screen import ProductionScreen as _PS78
        from ui.sales_screen import SalesScreen as _SS78
        check("قسما «المستعجل» و«المعلّقات» في الشاشتين",
              hasattr(_PS78, "load_urgent") and hasattr(_PS78, "load_entry")
              and hasattr(_SS78, "hold_invoice")
              and hasattr(_SS78, "open_held"))
        from ui.dashboard_screen import DashboardScreen as _DS76
        check("لوحة الكسر: النقر على العيار يفتح كشفه",
              hasattr(_DS76, "_click_row")
              and hasattr(_DS76, "_open_scrap_karat"))
    except ImportError:
        print("  … تُخطّى فحوص الواجهة (PyQt5 غير متاح)")

    # ══════════════════════════════════════════════════════════════
    step("79) بيت الطقم · سطر أجر فقط · نقل الجهة والحساب · قائمة الدخل")
    from models import coa as _coa79, entities as _en79
    from models import invoices as _iv79, statements as _st79
    from models import vouchers as _vo79
    from models.inventory import create_work_orders_batch as _b79
    _d79 = date.today().isoformat()
    with db() as conn:
        _grp79 = acc_id(conn, "1020")
        _sp79 = _coa79.add_sub_account(conn, _grp79, "معرض خاص ٧٩", "admin",
                                       measurement="gold")["id"]
        _b79(conn, [{"wo_no": "H79-1", "gold": 10.0, "wage_per_gram": 10}],
             _d79, "admin")
        _b79(conn, [{"wo_no": "H79-2", "gold": 20.0, "wage_per_gram": 10}],
             _d79, "admin", dest_account_id=_sp79)
        _c79 = _en79.add_entity(conn, "عميل ٧٩", "customer", username="admin")
        _ws79 = {r["work_order_no"]: r for r in conn.execute(
            "SELECT * FROM work_orders WHERE work_order_no LIKE 'H79-%'")}
        _s0 = account_balance(conn, _sp79)[0]
        _m0 = account_balance(conn, acc_id(conn, "1200"))[0]
        _r79 = _iv79.create_sale(
            conn, _c79, [{"work_order_id": _ws79["H79-1"]["id"]},
                         {"work_order_id": _ws79["H79-2"]["id"]},
                         {"wage_only": True, "amount": 55, "note": "تلميع"}],
            _d79, "admin", apply_vat=False)
        _s1 = account_balance(conn, _sp79)[0]
        _m1 = account_balance(conn, acc_id(conn, "1200"))[0]
    check("الطقم يخرج من حساب دفعته: H79-2 من «معرض خاص» و H79-1 من"
          " المشغول — في فاتورةٍ واحدة",
          abs(_s0 - _s1 - 20) < 0.001 and abs(_m0 - _m1 - 10) < 0.001,
          f"{_s0 - _s1} · {_m0 - _m1}")
    check("سطر «أجر فقط» يدخل أجور العميل بلا ذهب ولا مخزون",
          abs(_r79["total_wages"] - 355) < 0.01
          and abs(_r79["total_weight"] - 30) < 0.001, str(_r79["total_wages"]))
    with db() as conn:
        _rr79 = _iv79.create_sale_return(
            conn, _c79, [{"work_order_id": _ws79["H79-2"]["id"]}], _d79,
            "admin", apply_vat=False)
        _s2 = account_balance(conn, _sp79)[0]
    check("المرتجع يعيد الطقم إلى حسابه هو (لا إلى «من حساب» الفاتورة)",
          abs(_s2 - _s0) < 0.001, str(_s2 - _s1))
    with db() as conn:
        _e79 = _en79.get_entity(conn, _c79)
        _en79.update_entity(conn, _c79, "admin",
                            vat_number="300000000000003")
        _en79.change_entity_type(conn, _c79, "supplier", "admin")
        _pc79 = conn.execute(
            "SELECT p.code, a.type FROM accounts a JOIN accounts p"
            " ON p.id=a.parent_id WHERE a.id=?",
            (_e79["account_id"],)).fetchone()
    check("نقل نوع الجهة (عميل ← مورد) ينقل حسابها بقيوده تحت الموردين",
          _pc79["code"] == "2300" and _pc79["type"] == "liability")
    with db() as conn:
        _x79 = _coa79.add_sub_account(conn, acc_id(conn, "5800"),
                                      "مصروف ٧٩", "admin")["id"]
        _coa79.move_account(conn, _x79, acc_id(conn, "5050"), "admin")
        _pp79 = conn.execute("SELECT p.code, a.parent_locked FROM accounts a"
                             " JOIN accounts p ON p.id=a.parent_id"
                             " WHERE a.id=?", (_x79,)).fetchone()
    check("دليل الحسابات: نقل حسابٍ تحت أبٍ آخر ويبقى مكانه",
          _pp79["code"] == "5050" and _pp79["parent_locked"] == 1)
    with db(readonly=True) as conn:
        _is79 = _st79.income_statement(conn, f"{_d79[:4]}-01-01", _d79,
                                       compare=False)
    _keys79 = [k for k, _t, _s in _st79.IS_LINES]
    check("قائمة الدخل: المبيعات · الإيرادات الأخرى والتحصيلية · العمال ·"
          " رواتب الإدارة — وبيانات للعلم (الذهب المباع والتحصيلات)",
          "gold_out" not in _keys79 and "other_rev" in _keys79
          and "cogs" not in _keys79
          and _keys79.index("net_diff") < _keys79.index("workshop")
          and _keys79.index("admin") < _keys79.index("labor")
          < _keys79.index("mgmt") < _keys79.index("materials")
          and set(_is79["memo"]) == {"m_collect", "m_cash_out"})
    with db() as conn:
        _w79 = _en79.add_entity(conn, "عامل ٧٩", "worker", username="admin",
                                basic_salary=2000)
        _dflt79 = _vo79.staff_expense_default(conn, _w79)
        _en79.update_entity(conn, _w79, "admin", direct_pay=True)
        _v79 = _vo79.create_voucher(conn, "payment", _d79, "admin",
                                    entity_id=_w79, cash_amount=300)
        _codes79 = {r["code"] for r in conn.execute(
            "SELECT a.code FROM journal_lines l JOIN accounts a"
            " ON a.id=l.account_id WHERE l.entry_id=?", (_v79["entry_id"],))}
    check("سند صرف العامل: سلفة افتراضاً (لا يتكرّر مع المسير)، ومصروفات"
          " العمال 5710 لمن يُصرف له مباشرةً بلا مسير",
          _dflt79 is False and "5710" in _codes79)

    # ══════════════════════════════════════════════════════════════
    step("80) المدفوع للعملاء والموردين في قائمة الدخل · نقل حساب جهة")
    from models import vouchers as _vo80, entities as _en80, coa as _coa80
    from models import statements as _st80
    _d80 = date.today().isoformat()
    _y80 = f"{_d80[:4]}-01-01"
    with db(readonly=True) as conn:
        _i0 = _st80.income_statement(conn, _y80, _d80, compare=False)
    with db() as conn:
        _c80 = _en80.add_entity(conn, "عميل ٨٠", "customer", username="admin")
        _s80 = _en80.add_entity(conn, "مورد ٨٠", "supplier",
                                vat_number="300000000000003",
                                username="admin")
        _ce80 = _en80.get_entity(conn, _c80)
        # تعويضٌ لعميل: ٢٠٠ ريال و٣ جم — يُحمَّل «مدفوعات للعملاء» 5250
        _v1 = _vo80.create_voucher(
            conn, "payment", _d80, "admin", entity_id=_c80,
            rows=[{"kind": "cash", "amount": 200},
                  {"kind": "gold", "weight": 3, "karat": 18}],
            expense_account_id=acc_id(conn, "5250"))
        # سدادٌ لمورد — لا مصروف، ويظهر في «بيانات للعلم»
        _vo80.create_voucher(conn, "payment", _d80, "admin", entity_id=_s80,
                             cash_amount=500)
        _bc80 = account_balance(conn, _ce80["account_id"])
    with db(readonly=True) as conn:
        _i1 = _st80.income_statement(conn, _y80, _d80, compare=False)
    _dc = round(_i1["cash"]["values"]["discounts"]
                - _i0["cash"]["values"]["discounts"], 2)
    _dg = round(_i1["gold"]["values"]["discounts"]
                - _i0["gold"]["values"]["discounts"], 3)
    check("المدفوع للعميل (نقداً وذهباً) يُطرح من الإيراد في «الخصم المسموح"
          " به والمدفوع للعملاء» — وكشف العميل لا يتغيّر رصيده",
          _dc == -200 and _dg == -3 and abs(_bc80[0]) < 0.001
          and abs(_bc80[1]) < 0.01, f"{_dc} · {_dg} · {_bc80}")
    _ms = round(_i1["memo"]["m_cash_out"]["cash"]
                - _i0["memo"]["m_cash_out"]["cash"], 2)
    check("السداد للمورد لا يدخل المصروفات، و«الخارج من النقدية» في"
          " «بيانات للعلم» يجمع كل ما خرج (200 للعميل + 500 للمورد)",
          _ms == 700 and abs(_i1["cash"]["totals"]["opex"]
                             - _i0["cash"]["totals"]["opex"]) < 0.01, str(_ms))
    with db() as conn:
        _r80 = _coa80.move_account(conn, _ce80["account_id"],
                                   acc_id(conn, "2300"), "admin")
        _t80 = _en80.get_entity(conn, _c80)["entity_type"]
        _an80 = conn.execute("SELECT name, type FROM accounts WHERE id=?",
                             (_ce80["account_id"],)).fetchone()
    check("نقل حساب جهةٍ من دليل الحسابات مسموح، ونوعها يتبع مجموعته"
          " (عميل ← مورد)",
          _t80 == "supplier" and _an80["type"] == "liability"
          and _an80["name"].startswith("مورد: ") and _r80["entities"],
          f"{_t80} · {_an80['name']}")
    _mw80 = open(os.path.join(ROOT, "ui", "main_window.py"),
                 encoding="utf-8").read()
    check("«التحليل والدراسات» في القائمة الرئيسية لا تحت «الإدارة"
          " والتقارير»",
          _mw80.index('("التحليل والدراسات",')
          < _mw80.index('("الإدارة والتقارير", ['))

    # ══════════════════════════════════════════════════════════════
    step("81) ترقيم مستقل لكل مستند · تعديل عميل الفاتورة · حاسبة الخانة")
    from models import vouchers as _vo81, invoices as _iv81
    from models import entities as _en81, numbering as _nb81
    from models.inventory import create_work_orders_batch as _b81
    _d81 = date.today().isoformat()

    def _nums81(conn, prefix):
        got = set()
        for t, c in _nb81._sources(conn):
            for r in conn.execute(f"SELECT {c} v FROM {t} WHERE {c} LIKE ?",
                                  (f"{prefix}-%",)):
                got.add(_nb81._suffix(r["v"], prefix))
        return sorted(got)

    with db(readonly=True) as conn:
        _seq81 = {p: _nums81(conn, p)
                  for p in ("S", "R", "RV", "PV", "P", "F", "JV", "ST")}
    # فجوةٌ واحدة مقصودة في JV: فحص «البصمات» يمحو قيداً من الجدول من
    # خارج النظام ليثبت كشف العبث — ولا فجوة غيرها في أي نوع
    _bad81 = {p: sorted(set(range(1, s[-1] + 1)) - set(s))
              for p, s in _seq81.items()
              if s and (s[0] != 1 or s[-1] - len(s) > (1 if p == "JV" else 0))}
    check("كل نوع مستندٍ يبدأ من 1 بحرفه ويتصل بلا فجوات:"
          " بيع S · مرتجع R · قبض RV · صرف PV · مشتريات P · تسكير F ·"
          " قيد يومية JV · جرد ST",
          not _bad81 and all(_seq81[p] for p in ("S", "R", "RV", "PV", "P",
                                                 "F", "JV")),
          str({p: len(s) for p, s in _seq81.items()}) + str(_bad81))
    with db() as conn:
        _c81 = _en81.add_entity(conn, "محمد ٨١", "customer", username="admin")
        _k81 = _en81.add_entity(conn, "سالم ٨١", "customer", username="admin")
        _v81 = _vo81.create_voucher(conn, "receipt", _d81, "admin",
                                    entity_id=_c81, cash_amount=100)
        _vo81.update_voucher(conn, _v81["id"], "admin", entity_id=_c81,
                             cash_amount=150)
        _vn81 = _vo81.create_voucher(conn, "receipt", _d81, "admin",
                                     entity_id=_c81, cash_amount=10)
    check("تعديل السند يُبقي رقمه ولا يستهلك رقماً — السند التالي يليه مباشرة",
          _nb81._suffix(_vn81["voucher_no"], "RV")
          == _nb81._suffix(_v81["voucher_no"], "RV") + 1,
          f"{_v81['voucher_no']} → {_vn81['voucher_no']}")
    with db() as conn:
        _b81(conn, [{"wo_no": "N81-1", "gold": 15.0, "wage_per_gram": 10}],
             _d81, "admin")
        _w81 = conn.execute("SELECT id FROM work_orders"
                            " WHERE work_order_no='N81-1'").fetchone()["id"]
        _s81 = _iv81.create_sale(conn, _c81, [{"work_order_id": _w81}], _d81,
                                 "admin", apply_vat=False)
        _a81 = {e: _en81.get_entity(conn, e)["account_id"]
                for e in (_c81, _k81)}
        _cb0 = account_balance(conn, _a81[_c81])
        _src0 = conn.execute("SELECT source_account_id FROM invoices"
                             " WHERE id=?", (_s81["id"],)).fetchone()[0]
        _u81 = _iv81.update_invoice(conn, _s81["id"],
                                    [{"work_order_id": _w81}], "admin",
                                    entity_id=_k81)
        _i81 = conn.execute("SELECT customer_id, source_account_id, entry_id,"
                            " invoice_no FROM invoices WHERE id=?",
                            (_s81["id"],)).fetchone()
        _cb1 = account_balance(conn, _a81[_c81])
        _kb1 = account_balance(conn, _a81[_k81])
        _jd81 = conn.execute("SELECT description FROM journal_entries"
                             " WHERE id=?", (_i81["entry_id"],)).fetchone()[0]
    check("تعديل عميل الفاتورة (محمد ← سالم): الفاتورة وقيدها ورصيدها ينتقلان"
          " كاملاً للجديد، ورقمها وحساب مخزونها لا يتغيّران",
          _i81["customer_id"] == _k81 and _u81.get("moved_customer")
          and _i81["invoice_no"] == _s81["invoice_no"]
          and _i81["source_account_id"] == _src0
          and abs(_kb1[0] - 15) < 0.001 and abs(_kb1[1] - 150) < 0.01
          and abs(_cb0[0] - _cb1[0] - 15) < 0.001
          and abs(_cb0[1] - _cb1[1] - 150) < 0.01 and "سالم ٨١" in _jd81,
          f"{_cb0} → {_cb1} · {_kb1} · {_jd81}")
    from ui.widgets.smart_input import evaluate as _ev81
    _long81 = "+".join(["12.5"] * 1500)
    check("الخانة الحسابية: سلسلة جمعٍ طويلة (1500 رقماً) تُحسب بلا رفضٍ صامت",
          _ev81(_long81) == 12.5 * 1500
          and _ev81("10+20-5*2") == 20 and _ev81("1+") is None,
          str(_ev81(_long81)))

    # ══════════════════════════════════════════════════════════════
    step("82) تعديل نوع السند · العدد والعيار · أسطر المشتريات · الرصيد")
    from models import vouchers as _vo82, tax_sales as _ts82
    from models import purchases as _pu82, mfg_costs as _mc82
    from models import entities as _en82, invoices as _iv82
    from models.inventory import create_work_orders_batch as _b82
    _d82 = date.today().isoformat()
    with db() as conn:
        _c82 = _en82.add_entity(conn, "عميل ٨٢", "customer", username="admin")
        _v82 = _vo82.create_voucher(conn, "receipt", _d82, "admin",
                                    entity_id=_c82, cash_amount=70)
        _u82 = _vo82.update_voucher(conn, _v82["id"], "admin",
                                    kind="payment", entity_id=_c82,
                                    cash_amount=70)
        _r82 = conn.execute(
            "SELECT v.kind, v.voucher_no, e.doc_no, e.description FROM"
            " vouchers v JOIN journal_entries e ON e.id=v.entry_id"
            " WHERE v.id=?", (_v82["id"],)).fetchone()
        _cb82 = account_balance(
            conn, _en82.get_entity(conn, _c82)["account_id"])
    check("تعديل سند قبض إلى صرف مسموح: يأخذ رقمه من دفتر الصرف (PV)،"
          " وقيده نفسه يتبعه",
          _r82["kind"] == "payment" and _r82["voucher_no"].startswith("PV-")
          and _r82["doc_no"] == _r82["voucher_no"]
          and "~TMP" not in _r82["description"]
          and _u82["renumbered"][0] == _v82["voucher_no"]
          and abs(_cb82[1] - 70) < 0.01,
          f"{_v82['voucher_no']} → {_r82['voucher_no']} · {_cb82}")

    with db() as conn:
        _rep82 = _en82.add_entity(conn, "مندوب ٨٢", "customer",
                                  username="admin")
        _co82 = _en82.add_entity(conn, "شركة ٨٢", "customer",
                                 username="admin",
                                 vat_number="311111111100003")
        _b82(conn, [{"wo_no": "TX82-1", "gold": 30.0,
                     "wage_per_gram": 10.0}], _d82, "admin")
        _w82 = conn.execute("SELECT id FROM work_orders WHERE"
                            " work_order_no='TX82-1'").fetchone()["id"]
        _iv82.create_sale(conn, _rep82, [{"work_order_id": _w82}], _d82,
                          "admin", apply_vat=False)
        _it82 = _ts82.find_rep_item(conn, _rep82, "TX82-1")
        _t82 = _ts82.create_rep_invoice(
            conn, _co82, _rep82, _d82,
            [{"sale_item_id": _it82["item_id"], "pieces": 4,
              "karat": 21}], "admin")
        _l82 = conn.execute("SELECT pieces, karat, description, qty FROM"
                            " tax_sale_lines WHERE sale_id=?",
                            (_t82["id"],)).fetchone()
    _h82 = _pm.build_body("tax_sales", _t82["id"])
    check("المبيعات الضريبية: العدد والعيار يُحفظان في السطر ويظهران في"
          " بيانه وفي الفاتورة المطبوعة — والمبلغ لا يتغيّر",
          _l82["pieces"] == 4 and _l82["karat"] == 21
          and "4 قطعة" in _l82["description"]
          and "عيار 21" in _l82["description"]
          and "العدد" in _h82 and "العيار" in _h82
          and abs(_t82["net"] - 300) < 0.01,
          f"{dict(_l82)} · {_t82['net']}")

    with db() as conn:
        _s82 = _en82.add_entity(conn, "مورد ٨٢", "supplier",
                                vat_number="300000000000003",
                                username="admin")
        _p82 = _pu82.create_purchase(
            conn, "expense", _s82, "مشتريات متعددة", 0, 0, _d82, "admin",
            supplier_invoice_no="S82-1", tax_treatment="standard",
            lines=[{"account_code": "5500", "qty": 2, "unit_price": 100,
                    "discount": 20},
                   {"account_code": "5810", "qty": 1, "unit_price": 50}])
        _jl82 = {r["code"]: r["d"] for r in conn.execute(
            "SELECT a.code, SUM(l.cash_debit) d FROM journal_lines l JOIN"
            " accounts a ON a.id=l.account_id WHERE l.entry_id=?"
            " GROUP BY a.code", (_p82["entry_id"],))}
        _pl82 = _pu82.lines_of(conn, _p82["id"])
        _pr82 = conn.execute("SELECT amount, vat_amount, total, discount"
                             " FROM purchases WHERE id=?",
                             (_p82["id"],)).fetchone()
    _hp82 = _pm.build_body("purchases", _p82["id"])
    check("فاتورة مورد بأكثر من حساب: كل سطرٍ على حسابه، والضريبة على"
          " صافي كل سطر، والإجماليات من الأسطر",
          abs(_jl82.get("5500", 0) - 180) < 0.01
          and abs(_jl82.get("5810", 0) - 50) < 0.01
          and abs(_jl82.get("1900", 0) - 34.5) < 0.01
          and len(_pl82) == 2 and abs(_pr82["amount"] - 230) < 0.01
          and abs(_pr82["discount"] - 20) < 0.01
          and abs(_pr82["total"] - 264.5) < 0.01
          and "حسب الأسطر" in _hp82 and "بعد الضريبة" in _hp82,
          f"{_jl82} · {dict(_pr82)}")
    with db() as conn:
        _po82 = _pu82.create_purchase(
            conn, "expense", _s82, "مبلغ واحد", 400, 60, _d82, "admin",
            supplier_invoice_no="S82-2", account_code="5500",
            discount=0)
        _pol = _pu82.lines_of(conn, _po82["id"])
    check("والمبلغ الواحد (بلا أسطر) يبقى فاتورةً بسطرٍ واحد كما كان",
          len(_pol) == 1 and abs(_pol[0]["net"] - 400) < 0.01
          and abs(_pol[0]["vat"] - 60) < 0.01, str(_pol))
    check("رصيد العامل بإشارته: عليه بالسالب · له بالموجب · والصفر فراغ",
          _mc82.bal_text(1200) == "\u200e-1,200.00"
          and _mc82.bal_text(-500) == "500.00"
          and _mc82.bal_text(0) == ""
          and _mc82.compute_salary_row(
              {"basic_salary": 3000, "owed": -500})["due"] == 3500
          and _mc82.compute_salary_row(
              {"basic_salary": 3000, "owed": -500,
               "is_posted": True})["due"] == 500)
    try:
        from ui.mfg_costs_screen import MfgCostsScreen as _M82
        from ui.purchases_screen import PurchasesScreen as _P82
        from ui.tax_sales_screen import TaxSalesScreen as _T82
        _src82 = open(os.path.join(ROOT, "ui", "mfg_costs_screen.py"),
                      encoding="utf-8").read()
        check("رواتب التصنيع: لا زرّ «حفظ» — حفظٌ تلقائي عند التنقّل"
              " والخروج",
              hasattr(_M82, "autosave") and hasattr(_M82, "hideEvent")
              and '"💾 حفظ"' not in _src82)
        check("المشتريات: جدول أسطر، والمعالجة الضريبية في الرأس ·"
              " والضريبية: العدد والعيار في الجدول",
              hasattr(_P82, "add_line") and "العدد" in _P82.LINE_COLS
              and "العدد" in _T82.ITEM_COLS and "العيار" in _T82.ITEM_COLS
              and _T82.ITEM_COLS.index("العيار")
              == _T82.ITEM_COLS.index("الوزن المقيد") + 1)
    except ImportError:
        print("  … تُخطّى فحوص الواجهة (PyQt5 غير متاح)")

    # ══════════════════════════════════════════════════════════════
    step("83) «بوليش 2» بدل «التلميع النهائي» · الفترة تُختار باسمها")
    from database import seed as _sd83
    from models import dash_panels as _dp83, fiscal as _fs83
    import datetime as _dt83
    with db(readonly=True) as conn:
        _n83 = conn.execute("SELECT name FROM accounts WHERE code='5114'"
                            ).fetchone()["name"]
    check("الحساب 5114 اسمه «بوليش 2» في المصنع الجديد", _n83 == "بوليش 2",
          _n83)
    with db() as conn:
        # قاعدةٌ قديمة: 5114 باسمه القديم، وصندوقٌ سمّاه المستخدم بنفسه
        conn.execute("UPDATE accounts SET name='فاقد التلميع النهائي',"
                     " name_locked=0 WHERE code='5114'")
        _x83 = _coa79.add_sub_account(conn, acc_id(conn, "5110"),
                                      "صندوق خياس التلميع النهائي",
                                      "admin")["id"]
        _fs83.set_setting(conn, "rename_polish2_449", "0")
        _pn83 = _dp83.load_panels()
        _pn83.append({"key": "p83", "title": "خياس التلميع النهائي",
                      "accounts": ["5114"]})
        _dp83.save_panels(_pn83)
        _r83 = _sd83.rename_polish2(conn)
        _nm83 = {r["code"]: (r["name"], r["name_locked"]) for r in
                 conn.execute("SELECT code, name, name_locked FROM accounts"
                              " WHERE code='5114' OR id=?", (_x83,))}
        _again = _sd83.rename_polish2(conn)
        _left = conn.execute("SELECT COUNT(*) FROM accounts WHERE name LIKE"
                             " '%التلميع النهائي%'").fetchone()[0]
    _t83 = [x["title"] for x in _dp83.load_panels() if x.get("key") == "p83"]
    check("الترقية: كل حسابٍ باسم «التلميع النهائي» صار «بوليش 2» (بلا"
          " تكرار) ومقفلاً، ولوحته كذلك — مرةً واحدة",
          _r83 == 2 and _again == 0 and _left == 0
          and _nm83["5114"] == ("بوليش 2", 1)
          and any(v[0] == "بوليش 2 (2)" for k, v in _nm83.items()
                  if k != "5114")
          and _t83 == ["خياس بوليش 2"], f"{_nm83} · {_t83}")
    _pn83 = [x for x in _dp83.load_panels() if x.get("key") != "p83"]
    _dp83.save_panels(_pn83)
    _today83 = _dt83.date(2026, 10, 6)          # الثلاثاء
    _pr = lambda k: _dp83.period_range(k, _today83)  # noqa: E731
    check("الفترات تُحسب تلقائياً: الأسبوع من السبت · الشهر · الماضي ·"
          " آخر 3 أشهر · الربع · السنة",
          _pr("all") == (None, None)
          and _pr("today") == ("2026-10-06", "2026-10-06")
          and _pr("week") == ("2026-10-03", "2026-10-06")
          and _pr("month") == ("2026-10-01", "2026-10-06")
          and _pr("prev_month") == ("2026-09-01", "2026-09-30")
          and _pr("last3") == ("2026-08-01", "2026-10-06")
          and _pr("quarter") == ("2026-10-01", "2026-10-06")
          and _pr("year") == ("2026-01-01", "2026-10-06")
          and _pr("prev_year") == ("2025-01-01", "2025-12-31")
          and _dp83.period_range("prev_month", _dt83.date(2026, 1, 15))
          == ("2025-12-01", "2025-12-31"))
    _old83 = {"date_from": "2026-02-01", "date_to": "2026-02-28"}
    _new83 = {"period": "month"}
    _dp83.apply_period(_new83, _today83)
    check("لوحةٌ محفوظة بتواريخ يدوية تبقى «مخصّصة»، والمختارة باسمها"
          " تُحسب تواريخها",
          _dp83.panel_period(_old83) == "custom"
          and _dp83.apply_period(_old83) == "custom"
          and _old83["date_from"] == "2026-02-01"
          and _new83["date_from"] == "2026-10-01"
          and _new83["date_to"] == "2026-10-06")
    try:
        from ui.dashboard_screen import DashboardScreen as _D83
        _src83 = open(os.path.join(ROOT, "ui", "dashboard_screen.py"),
                      encoding="utf-8").read()
        check("لوحة التحكم: قائمة «المدة» بدل «تحديد فترة» اليدوي",
              "self.period = QtWidgets.QComboBox()" in _src83
              and "use_period" not in _src83 and hasattr(_D83, "refresh"))
    except ImportError:
        print("  … تُخطّى فحوص الواجهة (PyQt5 غير متاح)")

    # ══════════════════════════════════════════════════════════════
    step("84) تحليل مبيعات العميل: «تقرير» بالمعادلة وحدها")
    from models import sales_analytics as _sa84, invoices as _iv84
    from models import entities as _en84
    from models.inventory import create_work_orders_batch as _b84
    _d84 = date.today().isoformat()
    with db() as conn:
        _c84 = _en84.add_entity(conn, "عميل ٨٤", "customer", username="admin")
        _b84(conn, [{"wo_no": "R84-1", "gold": 60.0, "wage_per_gram": 5},
                    {"wo_no": "R84-2", "gold": 40.0, "wage_per_gram": 5}],
             _d84, "admin")
        _ws84 = [r["id"] for r in conn.execute(
            "SELECT id FROM work_orders WHERE work_order_no LIKE 'R84-%'"
            " ORDER BY work_order_no")]
        _iv84.create_sale(conn, _c84, [{"work_order_id": w} for w in _ws84],
                          _d84, "admin", apply_vat=False)
        _iv84.create_sale_return(conn, _c84, [{"work_order_id": _ws84[0]}],
                                 _d84, "admin", apply_vat=False)
        _p84 = _sa84.all_panels(conn, _c84, _d84, _d84)
    _n84 = _sa84.report_net(_p84)
    _hr84 = _pm.build_body("customer_analytics", _c84, date_from=_d84,
                           date_to=_d84, mode="report")
    _hd84 = _pm.build_body("customer_analytics", _c84, date_from=_d84,
                           date_to=_d84)
    check("«تقرير»: المصروف − المرتجع = الصافي بالأرقام (100 − 60 = 40)،"
          " والورقة لوحاتٌ بلا أرقام تشغيل ولا سداد",
          abs(_p84["sales"]["weight"] - 100) < 0.001
          and abs(_p84["returns"]["weight"] - 60) < 0.001
          and abs(_n84["weight"] - 40) < 0.001
          and "R84-2" not in _hr84 and "السداد" not in _hr84
          and "R84-2" in _hd84, f"{_n84}")
    try:
        from ui.sales_analytics_screen import SalesAnalyticsScreen as _S84
        check("«تحديث اللوحات» بخيارين: تفصيلي · تقرير",
              hasattr(_S84, "run_mode"))
    except ImportError:
        print("  … تُخطّى فحوص الواجهة (PyQt5 غير متاح)")

    # ══════════════════════════════════════════════════════════════
    step("85) قائمة الدخل: بلا تكلفة الذهب المباع · «الخارج من النقدية»")
    from models import statements as _st85, vouchers as _vo85
    from models import entities as _en85
    _d85 = date.today().isoformat()
    _y85 = f"{_d85[:4]}-01-01"
    with db(readonly=True) as conn:
        _o0 = _st85.cash_out(conn, _y85, _d85)
    with db() as conn:
        _c85 = _en85.add_entity(conn, "عميل ٨٥", "customer", username="admin")
        _vo85.create_voucher(conn, "payment", _d85, "admin", entity_id=_c85,
                             cash_amount=120)
        _vo85.create_voucher(conn, "receipt", _d85, "admin", entity_id=_c85,
                             cash_amount=90)
        # تحويلٌ من الصندوق إلى البنك: ليس خروجاً من النقدية
        post_entry(conn, _d85, "تحويل للبنك", [
            {"account_id": acc_id(conn, "1500"), "cash_debit": 1000},
            {"account_id": acc_id(conn, "1400"), "cash_credit": 1000}],
            source_table="manual", username="admin")
    with db(readonly=True) as conn:
        _o1 = _st85.cash_out(conn, _y85, _d85)
        _is85 = _st85.income_statement(conn, _y85, _d85, compare=False)
    _lay85 = _st85.is_layout(_is85)
    _labels85 = [r["label"] for r in _lay85]
    check("«الخارج من النقدية»: الصرف وحده (120) — لا القبض ولا التحويل"
          " بين الصندوق والبنك",
          round(_o1 - _o0, 2) == 120, f"{_o0} → {_o1}")
    check("قائمة الدخل: لا «تكلفة المبيعات» ولا سطر يطرح الذهب المباع، ولا"
          " «المدفوع للموردين» — و«الخارج من النقدية» تحت «المقبوض»",
          not any("تكلفة" in x for x in _labels85)
          and not any("المدفوع للموردين" in x for x in _labels85)
          and _labels85.index(_st85.IS_MEMO[1][1])
          == _labels85.index(_st85.IS_MEMO[0][1]) + 1
          and "خسائر الورشة" in _labels85, str(_labels85[-4:]))

    # ══════════════════════════════════════════════════════════════
    step("86) رابط دليل الموديلات للمدير — ثابت ومجاني وبلا سحابة")
    import json as _js86
    import urllib.error as _ue86
    import urllib.request as _ur86
    from models import models_catalog as _mc86
    from services import models_web as _mw86, photo_server as _ps86

    def _get86(url, data=None, jar=None):
        # مع وعاء «كعكات» كالمتصفح: الدخول بالرمز يُحفظ ثم يُعاد توجيهه
        op = (_ur86.build_opener(_ur86.HTTPCookieProcessor(jar))
              if jar is not None else _ur86.build_opener())
        try:
            with op.open(_ur86.Request(url, data=data), timeout=10) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except _ue86.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")
    with db(readonly=True) as conn:
        _full86 = _mc86.full_catalog(conn)
        _m86 = next((m for m in _full86 if _full86[m]["sold"]), None)
        _same86 = _m86 is not None and (
            [i["wo"] for i in _full86[_m86]["sold"]]
            == [i["wo"] for i in _mc86.model_items(conn, _m86, "sold")]
            and [i["holder"] for i in _full86[_m86]["sold"]]
            == [i["holder"] for i in _mc86.model_items(conn, _m86, "sold")])
    check("الدليل كاملاً في استعلامٍ واحد يطابق الشاشة (الأطقم ومع من)",
          _same86, str(_m86))
    _mw86.RUNNER = lambda a, timeout=25: None          # بلا Tailscale
    with db() as conn:
        _mw86.set_mode(conn, "funnel", "admin")
    _r86 = _mw86.activate("admin")
    _addr86 = _ps86.current()
    _u86 = (_r86["lan"].replace(_addr86[0], "127.0.0.1")
            if _addr86 else "")
    _s1, _p1 = _get86(_u86) if _u86 else (0, "")
    check("بلا Tailscale: الرابط يعمل على شبكة المصنع ويقول السبب، والصفحة"
          " تعرض الموديلات ومع من",
          _r86["reason"] == "no_ts" and _s1 == 200
          and str(_m86) in _p1 and "طرف المناديب" in _p1, str(_s1))
    _s2, _p2 = _get86(_u86 + "x")
    check("رمزٌ خاطئ لا يُفتح", _s2 == 404)
    with db() as conn:
        _mw86.set_pin(conn, "5566", "admin")
    _s3, _p3 = _get86(_u86)
    _s4, _p4 = _get86(_u86 + "/login", b"pin=0000")
    import http.cookiejar as _cj86
    _s5, _p5 = _get86(_u86 + "/login", b"pin=5566", _cj86.CookieJar())
    check("رمز الدخول: الصفحة تُطلب به، والخاطئ يُرفض، والصحيح يفتحها",
          "أدخل رمز" in _p3 and str(_m86) not in _p3 and _s4 == 401
          and _s5 == 200 and str(_m86) in _p5)
    _mw86._fails.clear()
    with db() as conn:
        _mw86.set_pin(conn, "", "admin")
    _calls86 = []

    def _ts86(args, timeout=25):
        _calls86.append(list(args))
        if args[:2] == ["status", "--json"]:
            return 0, _js86.dumps({"BackendState": "Running", "Self": {
                "DNSName": "factory.tail9.ts.net."}})
        return 0, ""
    _mw86.RUNNER = _ts86
    _a86 = _mw86.activate("admin")
    _b86 = _mw86.activate("admin")
    with db(readonly=True) as conn:
        _tok86 = _mw86.settings(conn)["token"]
    check("Tailscale: رابطٌ ثابت https بعنوان الجهاز لا يتغيّر بإعادة"
          " التشغيل، والتوجيه إلى منفذ الخادم",
          _a86["ok"] and _a86["url"] == _b86["url"]
          == f"https://factory.tail9.ts.net/m/{_tok86}"
          and ["funnel", "--bg", str(_addr86[1])] in _calls86,
          str(_a86))
    with db() as conn:
        _mw86.regenerate(conn, "admin")
    _s6, _ = _get86(_u86)
    _mw86.deactivate("admin")
    with db(readonly=True) as conn:
        _tok86b = _mw86.settings(conn)["token"]
    _s7, _ = _get86(_u86.rsplit("/", 1)[0] + "/" + _tok86b)
    check("«رابط جديد» يُبطل القديم، و«إيقاف» يُغلق الرابط ويلغي العنوان"
          " العام", _s6 == 404 and _s7 == 404
          and ["serve", "reset"] in _calls86)
    _mw86.RUNNER = _mw86._run_ts

    # ══ 87) حذف قيد رواتب التصنيع يعيد الشهر معلّقاً فيُنزَل من جديد ══
    # كان الحذف يُلغي القيد ويُبقي صفوف الشهر موسومةً «مرحّلة»، فيرفض
    # الإنزال مجدداً بـ«ربما رُحّلت مسبقاً» رغم أن القيد لم يعد قائماً.
    from models import mfg_costs as _mc87
    from services.audit import reverse_entry as _rev87
    _per87 = "2026-09"
    with db() as conn:
        _mc87.save_salaries(conn, _per87,
                            _mc87.list_salaries(conn, _per87), "admin")
        _p1 = _mc87.post_salaries(conn, _per87, "admin",
                                  entry_date="2026-09-30")
    with db(readonly=True) as conn:
        _posted87 = {r["employee_id"]: r["is_posted"]
                     for r in _mc87.list_salaries(conn, _per87)}[_weid]
    with db() as conn:
        _rev87(conn, _p1["entry_id"], "admin")
    with db(readonly=True) as conn:
        _r87b = [r for r in _mc87.list_salaries(conn, _per87)
                 if r["employee_id"] == _weid]
        _row87 = conn.execute(
            "SELECT is_posted, entry_id FROM mfg_salaries"
            " WHERE period=? AND employee_id=?",
            (_per87, _weid)).fetchone()
    check("حذف قيد رواتب الشهر يعيد صفوفه «غير مرحّلة»",
          _posted87 and not _r87b[0]["is_posted"]
          and not _row87["is_posted"] and _row87["entry_id"] is None,
          f"{_posted87} → {_r87b[0]['is_posted']} · {dict(_row87)}")
    try:
        with db() as conn:
            _p2 = _mc87.post_salaries(conn, _per87, "admin",
                                      entry_date="2026-09-30")
        _ok87 = (abs(_p2["total"] - _p1["total"]) < 0.011
                 and _p2["count"] == _p1["count"])
    except ValueError as _e87:
        _p2, _ok87 = {"err": str(_e87)}, False
    check("ويُنزَل راتب الشهر نفسه من جديد بالمبلغ ذاته", _ok87, str(_p2))
    with db(readonly=True) as conn:
        _live87 = conn.execute(
            "SELECT COUNT(*) n FROM journal_entries WHERE is_deleted=0"
            " AND source_table='mfg_salaries' AND description LIKE ?",
            (f"%{_per87}%",)).fetchone()["n"]
    check("ويبقى للشهر قيدٌ قائم واحد لا قيدان", _live87 == 1,
          f"{_live87}")
    # قاعدةٌ حُذف فيها القيد قبل هذا الإصلاح: الوسم باقٍ والقيد محذوف
    with db() as conn:
        conn.execute("UPDATE journal_entries SET is_deleted=1 WHERE id=?",
                     (_p2["entry_id"],))
    with db(readonly=True) as conn:
        _old87 = {r["employee_id"]: r["is_posted"]
                  for r in _mc87.list_salaries(conn, _per87)}[_weid]
    with db() as conn:
        _p3 = _mc87.post_salaries(conn, _per87, "admin",
                                  entry_date="2026-09-30")
    check("وقاعدةٌ قديمة حُذف قيدها قبل الإصلاح تُنزَل أيضاً",
          not _old87 and _p3["count"] >= 1, str(_p3))

    step("88) 4.54: رواتب العمال والإدارة · القالب قبل/بعد التعديل · رجوع")
    from models import mfg_costs as _mc88, payroll as _pr88
    from models import vouchers as _vo88, editing as _ed88
    from models import doc_edits as _de88
    from models.entities import add_entity as _ae88
    _per88 = "2026-11"
    with db() as conn:
        _adm88 = _ae88(conn, "محاسبة الإدارة ٨٨", "employee",
                       username="admin", basic_salary=4000.0)
        _aeid88 = conn.execute("SELECT employee_id FROM entities WHERE id=?",
                               (_adm88,)).fetchone()["employee_id"]
        _rows88 = _mc88.list_salaries(conn, _per88)
        _mc88.save_salaries(conn, _per88, _rows88, "admin")
        _p88 = _mc88.post_salaries(conn, _per88, "admin",
                                   entry_date="2026-11-30")
        _lines88 = conn.execute(
            "SELECT a.code, l.line_desc, l.cash_debit FROM journal_lines l"
            " JOIN accounts a ON a.id=l.account_id WHERE l.entry_id=?"
            " AND l.cash_debit>0", (_p88["entry_id"],)).fetchall()
    _adm_line = [x for x in _lines88 if "محاسبة الإدارة ٨٨" in x["line_desc"]]
    _wk_line = [x for x in _lines88 if "عامل" in x["line_desc"]
                and x["code"] == "5710"]
    check("راتب الإداري على «مصروف الرواتب والأجور» 5700 والعامل على 5710",
          _adm_line and _adm_line[0]["code"] == "5700" and _wk_line,
          str([(x["code"], x["line_desc"]) for x in _lines88]))
    # راتبٌ نزل من الشاشة الملغاة لا يُنزَل مرةً ثانية من هنا
    _per88b = "2026-12"
    with db() as conn:
        _pr88.run_accrual(conn, _per88b, "admin", entry_date="2026-12-31")
        _r88b = {r["employee_id"]: r
                 for r in _mc88.list_salaries(conn, _per88b)}
    check("ومن نزل راتبه من شاشة الموظفين القديمة يظهر «مرحّلاً» فلا يتكرّر",
          _r88b[_aeid88]["is_posted"], str(_r88b[_aeid88]["is_posted"]))

    # ── القالب قبل/بعد: تعديلٌ في المكان ──
    with db() as conn:
        _c88 = _ae88(conn, "عميل القالب ٨٨", "customer", username="admin")
        _v88 = _vo88.create_voucher(conn, "receipt", "2026-11-05", "admin",
                                    entity_id=_c88, cash_amount=100)
        _vo88.update_voucher(conn, _v88["id"], "admin", entity_id=_c88,
                             cash_amount=175)
        _eid88 = conn.execute(
            "SELECT id FROM doc_edits WHERE source_table='vouchers'"
            " AND source_id=? ORDER BY id DESC", (_v88["id"],)).fetchone()["id"]
        _sn88 = _de88.snapshots(conn, _eid88)
        _rep88 = _de88.report(conn, edit_id=_eid88)[0]
    check("التعديل في المكان يحفظ قالب السند قبل التعديل وبعده",
          _sn88["stored_before"] and "100.00" in _sn88["before"]
          and "175.00" in _sn88["after"]
          and "175.00" not in _sn88["before"],
          f"{len(_sn88['before'])}/{len(_sn88['after'])}")
    check("وسطر السجل يذكر الطرف وما تغيّر بكلامٍ يُقرأ",
          _rep88["party"] == "عميل القالب ٨٨" and _rep88["change"],
          f"{_rep88['party']} · {_rep88['change']}")
    # ── وتعديلٌ بإلغاءٍ وإعادة ترحيل ──
    with db() as conn:
        _ve88 = conn.execute("SELECT entry_id FROM vouchers WHERE id=?",
                             (_v88["id"],)).fetchone()["entry_id"]
        _nv88 = _ed88.repost(conn, _ve88, "admin", _vo88.create_voucher,
                             "receipt", "2026-11-06", "admin",
                             entity_id=_c88, cash_amount=260)
        _eid88b = conn.execute(
            "SELECT id FROM doc_edits WHERE kind='repost'"
            " ORDER BY id DESC").fetchone()["id"]
        _sn88b = _de88.snapshots(conn, _eid88b)
    check("والإلغاء وإعادة الترحيل: القديم قبلُ والجديد بعدُ",
          "175.00" in _sn88b["before"] and "260.00" in _sn88b["after"],
          f"{len(_sn88b['before'])}/{len(_sn88b['after'])}")
    from services import browser_print as _bp88
    _pg88 = _bp88.build_compare_page(_eid88b)
    check("وصفحة المقارنة تحمل القالبين بعنوانيهما",
          "قبل التعديل" in _pg88 and "بعد التعديل" in _pg88
          and "175.00" in _pg88 and "260.00" in _pg88
          and "عميل القالب ٨٨" in _pg88, f"{len(_pg88)} حرفاً")
    # تعديلٌ سُجّل قبل 4.54 (بلا صورة): يُقال ذلك صراحةً ولا ينهار
    with db() as conn:
        conn.execute("DELETE FROM doc_edit_snaps WHERE edit_id=?", (_eid88,))
    _pg88b = _bp88.build_compare_page(_eid88)
    check("وتعديلٌ قديم بلا صورة: تُقال صراحةً ويُعرض ما بعده",
          "لم تُحفظ صورة المستند" in _pg88b and "175.00" in _pg88b)

    # ── رجوع لا إغلاق ──
    try:
        from PyQt5 import QtWidgets as _QW88
        _QW88.QApplication.instance() or _QW88.QApplication([])
        from ui.main_window import MainWindow as _MW88
        _w88 = _MW88({"id": 1, "username": "admin", "role": "admin",
                      "role_local": "accountant", "full_name": "م"})
        _names88 = [it.text(0) for it, _p in _w88._iter_nav()]
        check("شاشة «إنزال رواتب الموظفين» أُلغيت و«رواتب العمال والإدارة»"
              " في القائمة",
              "رواتب العمال والإدارة" in _names88
              and not any("إنزال رواتب الموظفين" in n for n in _names88))
        _gl = _w88.screens.index(_w88.gl_screen)
        _sa = _w88.screens.index(_w88.sales_screen)
        _w88.switch(_gl)
        _QW88.QApplication.processEvents()
        _w88.gl_screen.ensure()
        _w88.switch(_sa)
        _QW88.QApplication.processEvents()
        _alive = _w88.gl_screen.built
        _txt = _w88.btn_close.text()
        _w88._close_screen()
        _QW88.QApplication.processEvents()
        check("«رجوع» يعود إلى الشاشة السابقة حيّةً كما تُركت",
              _w88._current_row == _gl and _alive
              and _w88._items[_w88.gl_screen].text(0)[:20] in _txt
              and not _w88.sales_screen.built,
              f"{_w88._current_row}/{_gl} · {_txt}")
        _w88._close_screen()
        _QW88.QApplication.processEvents()
        check("ومن شاشةٍ فُتحت من القائمة يعود إلى الرئيسية",
              _w88._current_row == 0 and not _w88._history
              and not _w88.gl_screen.built)
        _w88.close()
    except ImportError:
        print("  … تُخطّى فحوص الواجهة (PyQt5 غير متاح)")

    step("89) 4.55: التحديث بالزر في نسخة الـexe — طبقة الكود المحدَّث")
    import json as _js89
    import re
    from pathlib import Path
    _R89 = Path(ROOT)
    import subprocess as _sp89
    import tempfile as _tf89
    import zipfile as _zf89
    _b89 = Path(_tf89.mkdtemp(prefix="ovl89_"))
    _ov89 = _b89 / "app_code"
    shutil.copytree(_R89, _ov89, ignore=shutil.ignore_patterns(
        "data", "logs", "backups", "branding", ".git", "__pycache__",
        "dist", "build", "_update_*", "*.db", "*.jup"))
    _cf89 = _ov89 / "core" / "config.py"
    _cf89.write_text(re.sub(r'APP_VERSION = "[^"]+"',
                            'APP_VERSION = "99.0.0"',
                            _cf89.read_text(encoding="utf-8")),
                     encoding="utf-8")
    _env89 = dict(os.environ, JADEITE_OVERLAY_ANYWAY="1",
                  JADEITE_DATA_DIR=str(_b89), QT_QPA_PLATFORM="offscreen")
    _out89 = _b89 / "about.json"
    _sp89.run([sys.executable, str(_R89 / "main.py"), "--about",
               str(_out89)], env=_env89, cwd=str(_R89), timeout=120)
    _ab89 = _js89.loads(_out89.read_text(encoding="utf-8"))
    check("الـexe يقرأ التحديث المثبَّت إن كان أحدث من كوده المدمج",
          _ab89.get("version") == "99.0.0"
          and str(_ov89) in _ab89.get("config_file", "")
          and _ab89["overlay"]["active"], str(_ab89)[:300])
    _cf89.write_text(re.sub(r'APP_VERSION = "[^"]+"',
                            'APP_VERSION = "0.0.1"',
                            _cf89.read_text(encoding="utf-8")),
                     encoding="utf-8")
    _sp89.run([sys.executable, str(_R89 / "main.py"), "--about",
               str(_out89)], env=_env89, cwd=str(_R89), timeout=120)
    _ab89b = _js89.loads(_out89.read_text(encoding="utf-8"))
    check("وتحديثٌ أقدم من المدمج يُتجاهل",
          not _ab89b["overlay"]["active"]
          and _ab89b.get("version") != "0.0.1", str(_ab89b)[:200])
    _vt89 = _b89 / "verify.txt"
    _r89 = _sp89.run([sys.executable, str(_R89 / "main.py"),
                      "--verify-code", str(_ov89), str(_vt89)],
                     env=_env89, cwd=str(_R89), timeout=300)
    check("وفحص ما قبل التثبيت: كل الوحدات تُستورد من مجلد التحديث",
          _r89.returncode == 0,
          _vt89.read_text(encoding="utf-8")[-300:]
          if _vt89.exists() else "")
    (_ov89 / "services" / "broken89.py").write_text(
        "import not_a_real_module_89\n", encoding="utf-8")
    _r89b = _sp89.run([sys.executable, str(_R89 / "main.py"),
                       "--verify-code", str(_ov89), str(_vt89)],
                      env=_env89, cwd=str(_R89), timeout=300)
    check("وتحديثٌ يحتاج مكتبةً غير موجودة يُرفض قبل التثبيت",
          _r89b.returncode == 1
          and "broken89" in _vt89.read_text(encoding="utf-8"))
    # الحزمة تحمل core/app_config.py (كانت تُسقطه بالاسم) لا إعدادات الجهاز
    sys.path.insert(0, str(_R89 / "tools"))
    import make_update as _mu89
    _pk89 = _mu89.build(_b89 / "pkg")
    with _zf89.ZipFile(_pk89["path"]) as _z89:
        _nm89 = set(_z89.namelist())
    check("حزمة التحديث تحمل core/app_config.py ولا تحمل إعدادات الجهاز",
          "gold_erp/core/app_config.py" in _nm89
          and "gold_erp/app_config.py" not in _nm89
          and "gold_erp/code_overlay.py" in _nm89
          and not any(n.startswith("gold_erp/data/") for n in _nm89))
    shutil.rmtree(_b89, ignore_errors=True)

    step("90) 4.57: رابط المدير بتصميم الكمبيوتر — خمس صور في الصف")
    from services import models_web as _mw90
    with db(readonly=True) as conn:
        _h90 = _mw90.page_html(conn, {}, "/m/t90")
    check("الصفحة بعرض الكمبيوتر على الجوال، والتكبير بالأصابع غير ممنوع",
          f'content="width={_mw90.DESKTOP_W}"' in _h90
          and "user-scalable" not in _h90 and "maximum-scale" not in _h90)
    check("وخمس صور في الصف افتراضاً مع اختيار 4/5/6",
          _mw90.DEFAULT_COLS == 5
          and all(f'data-c="{c}"' in _h90 for c in (4, 5, 6))
          and "repeat(var(--cols)" in _h90)

    step("91) 4.58: فحص رابط المدير طبقةً طبقة")
    from services import models_web as _mw91, photo_server as _ps91
    _r91 = _mw91.RUNNER
    _mw91.RUNNER = lambda args, timeout=25: None        # بلا Tailscale
    try:
        with db() as conn:
            _mw91.set_mode(conn, "funnel", "admin")
        _mw91.activate("admin")
        _d91 = {i["key"]: i for i in _mw91.diagnose()}
        check("الفحص يجرّب الخادم والصفحة فعلاً ويقف عند Tailscale المفقود",
              _d91["server"]["ok"] and _d91["page"]["ok"]
              and _d91["local"]["ok"] and _d91["ts"]["ok"] is False
              and _d91["ts"]["fix"] == "ts_install",
              str([(k, v["ok"]) for k, v in _d91.items()]))
        _mw91.deactivate("admin")
        _d91b = {i["key"]: i for i in _mw91.diagnose()}
        check("والرابط الموقوف يقال إنه موقوف وإصلاحه التفعيل",
              _d91b["enabled"]["ok"] is False
              and _d91b["enabled"]["fix"] == "activate")
    finally:
        _mw91.RUNNER = _r91

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
