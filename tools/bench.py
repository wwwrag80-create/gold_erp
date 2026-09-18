#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""قياس أداء المسارات الساخنة على دفتر بحجم واقعي.

    python tools/bench.py [عدد_القيود]

يبني قاعدة مؤقتة بعدد كبير من القيود ثم يقيس زمن العمليات التي
يلمسها المستخدم كل يوم: فتح معاملة، قراءة رصيد، لوحة التحكم، كشف
حساب، فحص السلامة، وإحصاءات طابور المزامنة.

الغرض: ألّا يُقال «النظام أسرع» بلا رقم. شغّله قبل أي تعديل على طبقة
القاعدة وبعده، وقارن.
"""
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

_TMP = tempfile.mkdtemp(prefix="gold_bench_")
import pathlib                                           # noqa: E402
import config                                            # noqa: E402
config.DB_PATH = pathlib.Path(_TMP) / "bench.db"

from database.database import (create_tables, db, migrate_schema,  # noqa: E402
                               run_migrations_files)
from database.seed import (ensure_new_accounts, ensure_system_tags,  # noqa: E402
                           seed_initial_data)
from models.accounts import acc_id                       # noqa: E402
from models.entities import (add_entity,                 # noqa: E402
                             ensure_employee_accrual_accounts,
                             ensure_internal_counterparties)

N_ENTRIES = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
N_CUSTOMERS = 200


def timed(label, fn, repeat=1):
    t0 = time.perf_counter()
    for _ in range(repeat):
        out = fn()
    ms = (time.perf_counter() - t0) * 1000 / repeat
    print(f"  {label:<44} {ms:9.2f} ms")
    return ms, out


def build():
    print(f"بناء دفتر اختباري: {N_ENTRIES:,} قيد · {N_CUSTOMERS} عميل …")
    create_tables(); migrate_schema(); run_migrations_files()
    seed_initial_data(); ensure_new_accounts()
    with db() as conn:
        ensure_internal_counterparties(conn)
        ensure_employee_accrual_accounts(conn)
        ensure_system_tags(conn)
    t0 = time.perf_counter()
    with db() as conn:
        cust_accs = []
        for i in range(N_CUSTOMERS):
            eid = add_entity(conn, f"عميل {i:04d}", "customer",
                             username="bench")
            cust_accs.append(conn.execute(
                "SELECT account_id FROM entities WHERE id=?",
                (eid,)).fetchone()["account_id"])
        cash = acc_id(conn, "1400")
        # الإدراج المباشر: الغرض حجم الدفتر لا صحة العمليات
        for i in range(N_ENTRIES):
            d = f"2025-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}"
            cur = conn.execute(
                "INSERT INTO journal_entries(doc_no,sort_key,entry_date,"
                "description,source_table,source_id,created_by)"
                " VALUES(?,?,?,?,?,?,?)",
                (f"BN-{i:06d}", i, d, "قيد قياس", "bench", i, "bench"))
            eid = cur.lastrowid
            acc = cust_accs[i % N_CUSTOMERS]
            amt = 100 + (i % 900)
            conn.execute(
                "INSERT INTO journal_lines(entry_id,account_id,cash_debit,"
                "cash_credit,gold_debit,gold_credit) VALUES(?,?,?,0,0,0)",
                (eid, acc, amt))
            conn.execute(
                "INSERT INTO journal_lines(entry_id,account_id,cash_debit,"
                "cash_credit,gold_debit,gold_credit) VALUES(?,?,0,?,0,0)",
                (eid, cash, amt))
            # حزمة مزامنة لكل قيد — كما يفعل النظام فعلياً
            conn.execute(
                "INSERT INTO sync_queue(tenant_id,op_uuid,entity,payload,"
                "status,sent_at) VALUES('bench',?,?,?,'sent',"
                "datetime('now','localtime','-30 days'))",
                (f"u{i}", "journal", '{"entry": %d, "pad": "%s"}' % (i, "x" * 400)))
        conn.execute("ANALYZE")
    print(f"  جاهز في {time.perf_counter() - t0:.1f} ثانية")
    size = config.DB_PATH.stat().st_size / 1048576
    print(f"  حجم القاعدة: {size:.1f} ميجابايت\n")
    return cust_accs


def main():
    cust_accs = build()
    from models import dash_panels as dp
    from services import health, sync_queue
    from services.accounting_engine import account_balance

    print("زمن العمليات (متوسط):")
    timed("فتح معاملة قراءة فارغة", lambda: _noop(readonly=True), repeat=50)
    timed("فتح معاملة كتابة فارغة", lambda: _noop(readonly=False), repeat=50)

    def bal():
        with db(readonly=True) as conn:
            return account_balance(conn, cust_accs[0])
    timed("رصيد حساب عميل", bal, repeat=10)

    def panel():
        with db(readonly=True) as conn:
            return dp.account_rows(conn, ["1600", "1400", "1200"])
    timed("لوحة التحكم (شجرة العملاء كاملة)", panel, repeat=5)

    def stats():
        with db(readonly=True) as conn:
            return sync_queue.stats(conn)
    timed("إحصاءات طابور المزامنة", stats, repeat=10)

    def dbl():
        with db(readonly=True) as conn:
            return health.check_double_entry(conn)
    timed("فحص توازن كل القيود", dbl, repeat=3)

    def stmt():
        with db(readonly=True) as conn:
            return conn.execute(
                "SELECT e.entry_date, e.doc_no, l.cash_debit, l.cash_credit"
                " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
                " WHERE e.is_deleted=0 AND l.account_id=?"
                " ORDER BY e.entry_date, e.id", (cust_accs[0],)).fetchall()
    timed("كشف حساب عميل كامل", stmt, repeat=10)

    def purge():
        with db() as conn:
            return sync_queue.purge_sent(conn)
    ms, n = timed("تنظيف طابور المزامنة", purge)
    print(f"      حُذفت {n:,} حزمة مرفوعة")
    print(f"      حجم القاعدة بعد التنظيف: "
          f"{config.DB_PATH.stat().st_size / 1048576:.1f} ميجابايت")


def _noop(readonly):
    with db(readonly=readonly) as conn:
        conn.execute("SELECT 1")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
