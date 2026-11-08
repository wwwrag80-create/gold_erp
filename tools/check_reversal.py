# اختبار 5.2.1: لا حذف — العكس بمستندٍ جديد — python3 tools/check_reversal.py
import sys, os, tempfile, pathlib  # noqa: E401
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
T = tempfile.mkdtemp(prefix="trev_")
import config  # noqa: E402
config.DB_PATH = pathlib.Path(T) / "t.db"
from database.database import create_tables, db, migrate_schema, run_migrations_files  # noqa: E402
from database.seed import ensure_new_accounts, ensure_system_tags, seed_initial_data  # noqa: E402
from models.entities import ensure_employee_accrual_accounts, ensure_internal_counterparties, add_entity  # noqa: E402
from models.accounts import acc_id  # noqa: E402
from models import invoices, inventory, vouchers, journal  # noqa: E402
from services.audit import soft_delete_entry  # noqa: E402
ok = bad = 0


def check(n, c, d=""):
    global ok, bad
    if c:
        ok += 1
        print("  ✔", n)
    else:
        bad += 1
        print("  ✘", n, d)


create_tables(); migrate_schema(); run_migrations_files(); seed_initial_data(); ensure_new_accounts()
with db() as conn:
    ensure_internal_counterparties(conn); ensure_employee_accrual_accounts(conn); ensure_system_tags(conn)


def party_bal(conn, eid):
    a = conn.execute("SELECT account_id FROM entities WHERE id=?", (eid,)).fetchone()["account_id"]
    r = conn.execute("SELECT ROUND(COALESCE(SUM(l.gold_debit-l.gold_credit),0),3) g,"
                     " ROUND(COALESCE(SUM(l.cash_debit-l.cash_credit),0),2) c FROM journal_lines l"
                     " JOIN journal_entries e ON e.id=l.entry_id WHERE e.is_deleted=0 AND l.account_id=?",
                     (a,)).fetchone()
    return (r["g"], r["c"])


def balanced(conn):
    r = conn.execute("SELECT ROUND(SUM(gold_debit)-SUM(gold_credit),3) g, ROUND(SUM(cash_debit)-SUM(cash_credit),2) c"
                     " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id WHERE e.is_deleted=0").fetchone()
    return abs(r["g"] or 0) < 0.001 and abs(r["c"] or 0) < 0.01


with db() as conn:
    cust = add_entity(conn, "عميل العكس", "customer", username="t")
    cid = cust if isinstance(cust, int) else cust["id"]
    inventory.create_work_orders_batch(conn, [
        {"wo_no": "R100", "gold": 20, "small_stones": 0, "big_stones": 0, "wage_per_gram": 10},
        {"wo_no": "00010", "gold": 40, "small_stones": 0, "big_stones": 0, "wage_per_gram": 5}],
        "2026-11-01", "t")
    wo = {r["work_order_no"]: r["id"] for r in conn.execute("SELECT id, work_order_no FROM work_orders")}
    s = invoices.create_sale(conn, cid, [{"work_order_id": wo["R100"]},
                                         {"wage_only": True, "amount": 30}], "2026-11-02", "t", apply_vat=True)
    s_entry, s_no = s["entry_id"], s["invoice_no"]
    before = party_bal(conn, cid)
with db() as conn:
    pass
msg = soft_delete_entry(s_entry, "t")
print("   ", msg)
with db() as conn:
    inv = conn.execute("SELECT * FROM invoices WHERE invoice_no=?", (s_no,)).fetchone()
    check("فاتورة البيع باقية برقمها (لا حذف)", inv and inv["is_deleted"] == 0)
    rv = conn.execute("SELECT * FROM invoices WHERE kind='sale_return' AND description LIKE ?", (f"%{s_no}%",)).fetchone()
    check("وفاتورة مرتجع جديدة برقمٍ جديد تعكسها", rv is not None and rv["invoice_no"].startswith("R-"), rv and rv["invoice_no"])
    check("ذمّة العميل صفر بعد العكس (ذهب وأجور وضريبة)", party_bal(conn, cid) == (0.0, 0.0), (before, party_bal(conn, cid)))
    st = conn.execute("SELECT status FROM work_orders WHERE id=?", (wo["R100"],)).fetchone()["status"]
    check("والطقم عاد إلى المخزون", st == "in_stock", st)
    check("والقيود متوازنة", balanced(conn))
try:
    soft_delete_entry(s_entry, "t")
    check("لا يُعكس مرتين", False)
except ValueError as e:
    check("لا يُعكس مرتين", "مسبقاً" in str(e), e)
try:
    soft_delete_entry(rv["entry_id"], "t")
    check("ومستند العكس لا يُعكس", False)
except ValueError as e:
    check("ومستند العكس لا يُعكس", "عكس" in str(e), e)

# مرتجع ← بيع
with db() as conn:
    r = invoices.create_sale(conn, cid, [{"work_order_id": wo["00010"], "weight": 10}], "2026-11-03", "t", apply_vat=False)
    rr = invoices.create_sale_return(conn, cid, [{"work_order_id": wo["00010"], "weight": 4}], "2026-11-04", "t", apply_vat=False)
    card0 = conn.execute("SELECT registered_weight FROM work_orders WHERE id=?", (wo["00010"],)).fetchone()[0]
print("   ", soft_delete_entry(rr["entry_id"], "t"))
with db() as conn:
    sv = conn.execute("SELECT * FROM invoices WHERE kind='sale' AND description LIKE ?", (f"%{rr['invoice_no']}%",)).fetchone()
    card1 = conn.execute("SELECT registered_weight FROM work_orders WHERE id=?", (wo["00010"],)).fetchone()[0]
    check("عكس المرتجع = فاتورة بيع جديدة، و00010 ينقص 4", sv is not None and abs(card0 - card1 - 4) < 0.001, (card0, card1))
    check("والمرتجع باق برقمه", conn.execute("SELECT is_deleted FROM invoices WHERE id=?", (rr["id"],)).fetchone()[0] == 0)

# سند قبض ← سند صرف
with db() as conn:
    b_pre = party_bal(conn, cid)
    v = vouchers.create_voucher(conn, "receipt", "2026-11-05", "t", entity_id=cid,
                                rows=[{"kind": "gold", "weight": 6, "karat": 21}, {"kind": "cash", "amount": 500}])
    b0 = party_bal(conn, cid)
    box0 = conn.execute("SELECT COALESCE(SUM(actual_delta),0) FROM scrap_moves WHERE karat=21 AND is_deleted=0").fetchone()[0]
print("   ", soft_delete_entry(v["entry_id"], "t"))
with db() as conn:
    pv = conn.execute("SELECT * FROM vouchers WHERE kind='payment' AND notes LIKE ?", (f"%{v['voucher_no']}%",)).fetchone()
    check("عكس سند القبض = سند صرف جديد PV", pv is not None and pv["voucher_no"].startswith("PV-"), pv and pv["voucher_no"])
    check("والقبض باق برقمه", conn.execute("SELECT is_deleted FROM vouchers WHERE id=?", (v["id"],)).fetchone()[0] == 0)
    box1 = conn.execute("SELECT COALESCE(SUM(actual_delta),0) FROM scrap_moves WHERE karat=21 AND is_deleted=0").fetchone()[0]
    check("وصندوق كسر 21 عاد كما كان (−6)", abs(box0 - box1 - 6) < 0.001, (box0, box1))
    b1 = party_bal(conn, cid)
    check("وذمّة العميل عادت كما قبل القبض بالضبط", b1 == b_pre and b0 != b_pre, (b_pre, b0, b1))
    n_lines = conn.execute("SELECT COUNT(*) FROM voucher_lines WHERE voucher_id=?", (pv["id"],)).fetchone()[0]
    check("وأسطر السند منسوخة (ذهب ونقد)", n_lines == 2, n_lines)
    check("والقيود متوازنة", balanced(conn))

# قيد يدوي ← قيد عكسي
with db() as conn:
    jid = journal.create_manual_entry(conn, "2026-11-06", "قيد تجربة", [
        {"account_id": acc_id(conn, "1400"), "cash_debit": 100},
        {"account_id": acc_id(conn, "1500"), "cash_credit": 100}], "t") if hasattr(journal, "create_manual_entry") else None
    if jid is None:
        from services.accounting_engine import post_entry
        jid = post_entry(conn, "2026-11-06", "قيد تجربة", [
            {"account_id": acc_id(conn, "1400"), "cash_debit": 100},
            {"account_id": acc_id(conn, "1500"), "cash_credit": 100}], source_table="manual", username="t")
    jno = conn.execute("SELECT doc_no FROM journal_entries WHERE id=?", (jid,)).fetchone()[0]
print("   ", soft_delete_entry(jid, "t"))
with db() as conn:
    check("القيد اليدوي باق برقمه", conn.execute("SELECT is_deleted FROM journal_entries WHERE id=?", (jid,)).fetchone()[0] == 0)
    rj = conn.execute("SELECT * FROM journal_entries WHERE description LIKE ?", (f"%عكس القيد {jno}%",)).fetchone()
    check("وقيدٌ عكسي جديد برقم JV", rj is not None and str(rj["doc_no"]).startswith("JV-") and rj["doc_no"] != jno, rj and rj["doc_no"])
    c = conn.execute("SELECT ROUND(COALESCE(SUM(l.cash_debit-l.cash_credit),0),2) FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
                     " WHERE e.is_deleted=0 AND l.account_id=?", (acc_id(conn, "1500"),)).fetchone()[0]
    check("والبنك عاد صفراً", abs(c) < 0.005, c)
    check("ولا مستند محذوف في الدفتر", conn.execute("SELECT COUNT(*) FROM journal_entries WHERE is_deleted=1").fetchone()[0] == 0)
# تحويل سندٍ لجهةٍ أخرى من «إدارة وتحويل العمليات»: يبقى القديم برقمه ويُعكس
from models import operations  # noqa: E402
with db() as conn:
    c2 = add_entity(conn, "عميل التحويل", "customer", username="t")
    c2 = c2 if isinstance(c2, int) else c2["id"]
    c3 = add_entity(conn, "عميل المستلم", "customer", username="t")
    c3 = c3 if isinstance(c3, int) else c3["id"]
    v2 = vouchers.create_voucher(conn, "receipt", "2026-11-07", "t", entity_id=c2,
                                 rows=[{"kind": "cash", "amount": 250}])
    r = operations.transfer_voucher(conn, v2["id"], c3, "t")
    check("تحويل السند: القديم باق برقمه", conn.execute("SELECT is_deleted FROM vouchers WHERE id=?", (v2["id"],)).fetchone()[0] == 0)
    rv = conn.execute("SELECT * FROM vouchers WHERE notes LIKE ?", (f"%عكس السند {v2['voucher_no']}%",)).fetchone()
    check("ومعكوسٌ بسند صرف بتاريخه", rv is not None and rv["kind"] == "payment" and rv["voucher_date"] == "2026-11-07")
    check("والجهة الأولى عادت صفراً", party_bal(conn, c2) == (0, 0), party_bal(conn, c2))
    check("والمستلم عليه السند الجديد", party_bal(conn, c3)[1] == -250 and r["new_no"] != v2["voucher_no"], party_bal(conn, c3))
    check("ولا مستند محذوف بعد التحويل", conn.execute("SELECT COUNT(*) FROM journal_entries WHERE is_deleted=1").fetchone()[0] == 0)
print(f"\n{'✔' if not bad else '✘'} {ok} نجح · {bad} فشل")
sys.exit(1 if bad else 0)
