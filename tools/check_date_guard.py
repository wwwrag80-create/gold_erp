# اختبار 5.2.7: تنبيه التاريخ قبل الترحيل · «بتاريخٍ مغاير» في سلامة السجل ·
# «الوارد» من شاشة الوارد وحدها — python3 tools/check_date_guard.py
import sys, os, tempfile, pathlib, datetime  # noqa: E401
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
T = tempfile.mkdtemp(prefix="tdg_")
import config  # noqa: E402
config.DB_PATH = pathlib.Path(T) / "t.db"
from database.database import create_tables, db, migrate_schema, run_migrations_files  # noqa: E402
from database.seed import ensure_new_accounts, ensure_system_tags, seed_initial_data  # noqa: E402
from models.entities import ensure_employee_accrual_accounts, ensure_internal_counterparties, add_entity  # noqa: E402
from models import invoices, inventory, vouchers, date_drift, models_catalog as mc  # noqa: E402
create_tables(); migrate_schema(); run_migrations_files(); seed_initial_data(); ensure_new_accounts()
with db() as conn:
    ensure_internal_counterparties(conn); ensure_employee_accrual_accounts(conn); ensure_system_tags(conn)
ok = bad = 0


def check(n, c, d=""):
    global ok, bad
    print(("  ✔ " if c else "  ✘ ") + n, "" if c else d)
    ok += bool(c)
    bad += (not c)


today = datetime.date.today()
d0 = today.isoformat()
d3 = (today - datetime.timedelta(days=3)).isoformat()
with db() as conn:
    A = add_entity(conn, "عميل", "customer", username="t")
    A = A if isinstance(A, int) else A["id"]
    inventory.create_work_orders_batch(conn, [
        {"wo_no": "S1", "model_no": "M1", "gold": 10, "small_stones": 0, "big_stones": 0, "wage_per_gram": 10},
        {"wo_no": "S2", "model_no": "M1", "gold": 11, "small_stones": 0, "big_stones": 0, "wage_per_gram": 10}],
        d3, "t")
    inventory.opening_stock_batch(conn, [{"wo_no": "O1", "model_no": "M2", "gold": 12, "small_stones": 0,
                                          "big_stones": 0, "wage_per_gram": 10}], d0, "t")
    stub = inventory.create_return_stub(conn, "R9", 9, 0, 0, None, None, "t")
    invoices.create_sale_return(conn, A, [{"work_order_id": stub["id"]}], d0, "t", apply_vat=False)
    s_old = invoices.create_sale(conn, A, [{"work_order_id": conn.execute(
        "SELECT id FROM work_orders WHERE work_order_no='S1'").fetchone()[0]}], d3, "t", apply_vat=False)
    s_now = invoices.create_sale(conn, A, [{"work_order_id": conn.execute(
        "SELECT id FROM work_orders WHERE work_order_no='S2'").fetchone()[0]}], d0, "t", apply_vat=False)
    v_old = vouchers.create_voucher(conn, "receipt", d3, "t", entity_id=A, rows=[{"kind": "cash", "amount": 100}])
with db(readonly=True) as conn:
    rec = mc.received(conn, d3, d0)
    wos = sorted(i["wo"] for m in rec["models"] for i in m["items"])
    check("«الوارد»: أطقم شاشة الوارد وحدها — لا مرتجعٌ ولا رصيدٌ افتتاحي", wos == ["S1", "S2"], wos)
    days = [x["date"] for x in mc.received_days(conn)]
    check("وأيام الوارد بلا يوم المرتجع والرصيد الافتتاحي", days == [d3], days)
    dr = date_drift.drifted(conn, d0, d0)
    nos = {r["doc_no"] for r in dr}
    check("سلامة السجل: الفاتورة والسند والتوريد المرحّلة بتاريخٍ قديم",
          s_old["invoice_no"] in nos and v_old["voucher_no"] in nos, nos)
    check("ولا تظهر فاتورةٌ بتاريخ يومها", s_now["invoice_no"] not in nos, nos)
    r = next(x for x in dr if x["doc_no"] == s_old["invoice_no"])
    check("والفرق بالأيام والجهة والمستخدم", r["days"] == -3 and r["party"] == "عميل" and r["who"] == "t", r)
# تنبيه التاريخ في الواجهة
from PyQt5 import QtCore, QtWidgets  # noqa: E402
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
from ui import kit  # noqa: E402
from ui.widgets import common  # noqa: E402
calls = []


def fake(parent, text, title, kind, buttons=(), detail="", default=None):
    calls.append((title, kind, detail))
    return answer[0]


kit.message = fake
answer = ["ok"]
w = QtWidgets.QWidget()
w.date = common.date_edit()
calls.clear()
answer = ["post"]
r1 = common.confirm_post(w, "x")
check("تاريخ اليوم: تأكيد الترحيل وحده بلا تنبيه", r1 and len(calls) == 1 and calls[0][1] == "question", calls)
w.date.setDate(QtCore.QDate.currentDate().addDays(-2))
calls.clear()
answer = ["cancel"]
r2 = common.confirm_post(w, "x")
check("تاريخٌ مغاير + «إلغاء»: لا ترحيل", (not r2) and len(calls) == 1 and calls[0][1] == "warning"
      and "يومان" in calls[0][2], calls)
calls.clear()
seq = iter(["ok", "post"])
kit.message = lambda *a, **k: (calls.append(a[3] if len(a) > 3 else k.get("kind")), next(seq))[1]
r3 = common.confirm_post(w, "x")
check("تاريخٌ مغاير + «موافق»: يُكمل إلى الترحيل طبيعياً", r3 and calls == ["warning", "question"], calls)
print(f"{ok} ✔ · {bad} ✘")
sys.exit(1 if bad else 0)
