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
