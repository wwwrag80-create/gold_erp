# اختبار 5.2.4: «المبيعات» (أطقم فواتير مختارة وأين صارت) · البحث بالوزن — python3 tools/check_sales_sets.py
import sys, os, tempfile, pathlib  # noqa: E401
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
T = tempfile.mkdtemp(prefix="tss_")
import config  # noqa: E402
config.DB_PATH = pathlib.Path(T) / "t.db"
from database.database import create_tables, db, migrate_schema, run_migrations_files  # noqa: E402
from database.seed import ensure_new_accounts, ensure_system_tags, seed_initial_data  # noqa: E402
from models.entities import ensure_employee_accrual_accounts, ensure_internal_counterparties, add_entity  # noqa: E402
from models import invoices, inventory, sales_sets, set_lookup, operations  # noqa: E402
create_tables(); migrate_schema(); run_migrations_files(); seed_initial_data(); ensure_new_accounts()
with db() as conn:
    ensure_internal_counterparties(conn); ensure_employee_accrual_accounts(conn); ensure_system_tags(conn)
ok = bad = 0


def check(n, c, d=""):
    global ok, bad
    print(("  ✔ " if c else "  ✘ ") + n, "" if c else d)
    ok += bool(c)
    bad += (not c)


def _id(x):
    return x if isinstance(x, int) else x["id"]


with db() as conn:
    A = _id(add_entity(conn, "محل الياسمين", "customer", username="t"))
    B = _id(add_entity(conn, "مندوب سالم", "customer", username="t"))
    inventory.create_work_orders_batch(conn, [
        {"wo_no": f"{800 + i}", "model_no": "M7", "gold": 11 + i, "small_stones": 0.3,
         "big_stones": 0.6, "wage_per_gram": 10} for i in range(5)], "2026-11-01", "t")
    W = {r[1]: r[0] for r in conn.execute("SELECT id, work_order_no FROM work_orders")}
    s1 = invoices.create_sale(conn, A, [{"work_order_id": W[x]} for x in ("800", "801", "802")],
                              "2026-11-02", "t", apply_vat=False)
    invoices.create_sale_return(conn, A, [{"work_order_id": W["801"]}, {"work_order_id": W["802"]}],
                                "2026-11-03", "t", apply_vat=False)
    invoices.create_sale(conn, B, [{"work_order_id": W["802"]}], "2026-11-04", "t", apply_vat=False)
    s2 = invoices.create_sale(conn, A, [{"work_order_id": W["803"]}], "2026-11-05", "t", apply_vat=False)
    s3 = invoices.create_sale(conn, A, [{"work_order_id": W["804"]}], "2026-11-06", "t", apply_vat=False)
with db() as conn:
    operations.transfer_invoice(conn, s3["id"], B, "t")     # يُعكس s3 ويصدر لمندوب سالم
with db() as conn:
    picks = sales_sets.pick_list(conn, A)
    nos = [p["invoice_no"] for p in picks]
    check("قائمة الاختيار: فواتير مبيعات الجهة بلا مستندات العكس",
          s1["invoice_no"] in nos and s2["invoice_no"] in nos and all(p["invoice_no"].startswith("S") for p in picks), nos)
    check("والفاتورة المعكوسة معلَّمة بمستند عكسها",
          any(p["invoice_no"] == s3["invoice_no"] and p["reversed_by"] for p in picks), picks)
    rows = {r["wo_no"]: r for r in sales_sets.track(conn, [s1["id"], s2["id"], s3["id"]])}
    check("800 مباع معه وعند محل الياسمين", rows["800"]["status"] == "with" and "الياسمين" in rows["800"]["where"], rows["800"])
    check("801 مرتجع برقم مرتجعه ومكانه الخزنة", rows["801"]["status"] == "returned" and rows["801"]["ret_no"].startswith("R-")
          and rows["801"]["where"] == "الخزنة", rows["801"])
    check("802 مرتجع ثم بِيع لغيره: عند مندوب سالم", rows["802"]["status"] == "returned" and rows["802"]["where"] == "عند مندوب سالم", rows["802"])
    check("804 فاتورته ملغاة بعكس", rows["804"]["status"] == "reversed", rows["804"])
    sm = sales_sets.summary(list(rows.values()))
    check("الإجماليات: معه 2 · مرتجع 2 (خزنة 1 · غيره 1) · ملغاة 1",
          (sm["with"]["n"], sm["returned"]["n"], sm["ret_treasury"]["n"], sm["ret_others"]["n"], sm["reversed"]["n"]) == (2, 2, 1, 1, 1), sm)
    near = set_lookup.near_weight(conn, 12.5, "reg", limit=3)
    check("البحث بالوزن المقيد: الأقرب أولاً", [n["work_order_no"] for n in near][:1] == ["801"]
          and near[0]["diff"] <= near[1]["diff"], [(n["work_order_no"], n["diff"]) for n in near])
    nst = set_lookup.near_weight(conn, 12.9, "standing", limit=2)
    check("البحث بالوزن القائم (ذهب + فصوص + أحجار)", nst[0]["work_order_no"] == "801" and nst[0]["diff"] == 0, [(n["work_order_no"], n["standing"]) for n in nst])
    d = set_lookup.details(conn, conn.execute("SELECT * FROM work_orders WHERE work_order_no='800'").fetchone())
    check("تفاصيل الطقم: ذهب وفصوص وأحجار ومقيد وقائم", abs(d["gold"] - 11) < 1e-6 and abs(d["small"] - 0.3) < 1e-6
          and abs(d["big"] - 0.6) < 1e-6 and abs(d["standing"] - 11.9) < 1e-6, d)
from services import print_manager  # noqa: E402
html = print_manager.build_html("sales_sets", 0, invoice_ids=[s1["id"], s2["id"]])
check("الطباعة: الأطقم وحالها وإلى من ذهبت", "عند مندوب سالم" in html and "مرتجع" in html and "800" in html)
print(f"{ok} ✔ · {bad} ✘")
sys.exit(1 if bad else 0)
