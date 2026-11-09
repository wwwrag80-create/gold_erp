# اختبار 5.2.4: عمليات الإدارة (تحويل · تعديل بنود · عكس نوع · دمج) بلا حذف — python3 tools/check_ops_reversal.py
import sys, os, tempfile, pathlib  # noqa: E401
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
T = tempfile.mkdtemp(prefix="tops_")
import config
config.DB_PATH = pathlib.Path(T) / "t.db"
from database.database import create_tables, db, migrate_schema, run_migrations_files
from database.seed import ensure_new_accounts, ensure_system_tags, seed_initial_data
from models.entities import ensure_employee_accrual_accounts, ensure_internal_counterparties, add_entity
from models import invoices, inventory, operations, wo_moves
create_tables(); migrate_schema(); run_migrations_files(); seed_initial_data(); ensure_new_accounts()
with db() as conn:
    ensure_internal_counterparties(conn); ensure_employee_accrual_accounts(conn); ensure_system_tags(conn)
ok = bad = 0
def check(n, c, d=""):
    global ok, bad
    print(("  ✔ " if c else "  ✘ ") + n, "" if c else d); ok += bool(c); bad += (not c)
def bal(conn, eid):
    a = conn.execute("SELECT account_id FROM entities WHERE id=?", (eid,)).fetchone()[0]
    r = conn.execute("SELECT ROUND(COALESCE(SUM(l.gold_debit-l.gold_credit),0),3), ROUND(COALESCE(SUM(l.cash_debit-l.cash_credit),0),2) FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id WHERE e.is_deleted=0 AND l.account_id=?", (a,)).fetchone()
    return tuple(r)
def balanced(conn):
    r = conn.execute("SELECT ROUND(SUM(gold_debit)-SUM(gold_credit),3), ROUND(SUM(cash_debit)-SUM(cash_credit),2) FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id WHERE e.is_deleted=0").fetchone()
    return abs(r[0] or 0) < .001 and abs(r[1] or 0) < .01
def live(conn, no):
    return conn.execute("SELECT is_deleted FROM invoices WHERE invoice_no=?", (no,)).fetchone()[0] == 0
with db() as conn:
    A = add_entity(conn, "عميل أ", "customer", username="t"); B = add_entity(conn, "عميل ب", "customer", username="t")
    A = A if isinstance(A, int) else A["id"]; B = B if isinstance(B, int) else B["id"]
    inventory.create_work_orders_batch(conn, [{"wo_no": f"X{i}", "gold": 10 + i, "small_stones": 0, "big_stones": 0, "wage_per_gram": 10} for i in range(6)] + [{"wo_no": "00010", "gold": 100, "small_stones": 0, "big_stones": 0, "wage_per_gram": 5}], "2026-11-01", "t")
    W = {r[1]: r[0] for r in conn.execute("SELECT id, work_order_no FROM work_orders")}
    s = invoices.create_sale(conn, A, [{"work_order_id": W["X0"]}, {"work_order_id": W["X1"]}], "2026-11-02", "t", apply_vat=False)
# 1) تحويل
with db() as conn:
    r = operations.transfer_invoice(conn, s["id"], B, "t")
    check("تحويل: الأصل باقٍ برقمه", live(conn, s["invoice_no"]))
    check("تحويل: مستند عكس جديد", bool(r["rev_no"]) and live(conn, r["rev_no"]), r)
    check("تحويل: ذمة أ صفر وذمة ب عليها البيع", bal(conn, A) == (0.0, 0.0) and bal(conn, B)[0] > 0, (bal(conn, A), bal(conn, B)))
    st = [conn.execute("SELECT status FROM work_orders WHERE id=?", (W[x],)).fetchone()[0] for x in ("X0", "X1")]
    check("تحويل: الأطقم مباعة (عند ب)", st == ["sold", "sold"], st)
    check("تحويل: حركة منتظمة", not wo_moves.bad_ids(conn, [W["X0"], W["X1"]]))
    check("تحويل: القيود متوازنة", balanced(conn))
    new_id = r["new_id"]; new_no = r["new_no"]
# 2) تعديل البنود: إزالة X1 وإضافة X2
with db() as conn:
    b0 = bal(conn, B)
    r = operations.edit_invoice_items(conn, new_id, [{"work_order_id": W["X0"]}, {"work_order_id": W["X2"]}], "t")
    check("تعديل: الأصل باقٍ ومستند عكس", live(conn, new_no) and r["rev_no"] and live(conn, r["rev_no"]), r)
    st = {x: conn.execute("SELECT status FROM work_orders WHERE id=?", (W[x],)).fetchone()[0] for x in ("X0", "X1", "X2")}
    check("تعديل: X1 عاد للخزنة، X0 وX2 مباعان", st == {"X0": "sold", "X1": "in_stock", "X2": "sold"}, st)
    b1 = bal(conn, B)
    check("تعديل: ذمة ب = X0 + X2", abs(b1[0] - (10 + 12)) < .01, b1)
    check("تعديل: حركة منتظمة ومتوازنة", not wo_moves.bad_ids(conn, list(W.values())) and balanced(conn))
# 3) عكس النوع على الرقم التجميعي
with db() as conn:
    s2 = invoices.create_sale(conn, A, [{"work_order_id": W["00010"], "weight": 8}], "2026-11-03", "t", apply_vat=False)
    a0 = bal(conn, A)
    r = operations.flip_invoice_kind(conn, s2["id"], "t")
    a1 = bal(conn, A)
    check("عكس النوع: الأصل باقٍ ومستند عكس", live(conn, s2["invoice_no"]) and r["rev_no"], r)
    check("عكس النوع: الذمة من +8 إلى −8", abs(a0[0] - a1[0] - 16) < .01, (a0, a1))
    check("عكس النوع: متوازنة", balanced(conn))
# 4) الدمج
with db() as conn:
    m1 = invoices.create_sale(conn, A, [{"work_order_id": W["X3"]}], "2026-11-04", "t", apply_vat=False)
    m2 = invoices.create_sale(conn, A, [{"work_order_id": W["X4"]}, {"work_order_id": W["00010"], "weight": 5}], "2026-11-05", "t", apply_vat=False)
    a0 = bal(conn, A)
    r = operations.merge_invoices(conn, [m1["id"], m2["id"]], "t")
    a1 = bal(conn, A)
    n = conn.execute("SELECT COUNT(*) FROM invoice_items WHERE invoice_id=?", (m1["id"],)).fetchone()[0]
    check("دمج: الباقية برقمها وفيها بنداها", r["invoice_no"] == m1["invoice_no"] and n == 2, (r, n))
    check("دمج: المدموجة باقية برقمها ولها مستند عكس", live(conn, m2["invoice_no"]) and r["reversals"] and live(conn, r["reversals"][0]), r)
    check("دمج: ذمة أ لم تتغير", a0 == a1, (a0, a1))
    st = conn.execute("SELECT status FROM work_orders WHERE id=?", (W["X4"],)).fetchone()[0]
    check("دمج: X4 مباع وحركته منتظمة", st == "sold" and not wo_moves.bad_ids(conn, list(W.values())), st)
    check("دمج: متوازنة", balanced(conn))
    lw = invoices.last_wage(conn, W["X4"])
    check("آخر أجر لا يأخذ من فاتورةٍ معكوسة أو مستند عكس", lw and lw["invoice_no"] == m1["invoice_no"], lw)
print(f"{ok} ✔ · {bad} ✘")
sys.exit(1 if bad else 0)
