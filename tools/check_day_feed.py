# اختبار 5.2.6: «حركة اليوم» في رابط المدير — python3 tools/check_day_feed.py
import sys, os, tempfile, pathlib, datetime  # noqa: E401
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
T = tempfile.mkdtemp(prefix="tdf_")
import config  # noqa: E402
config.DB_PATH = pathlib.Path(T) / "t.db"
from database.database import create_tables, db, migrate_schema, run_migrations_files  # noqa: E402
from database.seed import ensure_new_accounts, ensure_system_tags, seed_initial_data  # noqa: E402
from models.entities import ensure_employee_accrual_accounts, ensure_internal_counterparties, add_entity  # noqa: E402
from models import invoices, inventory, vouchers, day_feed  # noqa: E402
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


today = datetime.date.today()
d0, d1 = today.isoformat(), (today - datetime.timedelta(days=1)).isoformat()
with db() as conn:
    A = _id(add_entity(conn, "عميل اليوم", "customer", username="t"))
    inventory.create_work_orders_batch(conn, [
        {"wo_no": f"{900 + i}", "model_no": ("Q1", "Q2")[i % 2], "gold": 8 + i, "small_stones": 0.2,
         "big_stones": 0.3, "wage_per_gram": 10} for i in range(5)] + [
        {"wo_no": "0010", "gold": 60, "small_stones": 0, "big_stones": 0, "wage_per_gram": 5}], d1, "t")
    W = {r[1]: r[0] for r in conn.execute("SELECT id, work_order_no FROM work_orders")}
    invoices.create_sale(conn, A, [{"work_order_id": W[f"{900 + i}"]} for i in range(3)]
                         + [{"work_order_id": W["0010"], "weight": 4.5}], d0, "t", apply_vat=False)
    invoices.create_sale_return(conn, A, [{"work_order_id": W["901"]}], d0, "t", apply_vat=False)
    vouchers.create_voucher(conn, "receipt", d0, "t", entity_id=A,
                            rows=[{"kind": "gold", "weight": 12, "karat": 21}, {"kind": "cash", "amount": 900}])
with db(readonly=True) as conn:
    day = day_feed.day(conn, d0)
    keys = [g["key"] for g in day["groups"]]
    check("مستندات اليوم مصنّفة: مبيعات · مرتجع · قبض", keys[:3] == ["sale", "sale_return", "receipt"], keys)
    sale = next(g for g in day["groups"] if g["key"] == "sale")
    det = [d["detail"] for d in sale["docs"]]
    models = {m["model"]: m["count"] for x in det for m in x["models"]}
    check("الفاتورة بموديلاتها وعدد قطع كلٍّ منها", models == {"Q1": 2, "Q2": 1}, models)
    check("والايطالي بوزنه في فاتورته", any(x["italian"] and abs(x["italian_weight"] - 4.5) < 1e-6 for x in det), det)
    rc = next(g for g in day["groups"] if g["key"] == "receipt")["docs"][0]["detail"]
    check("سند القبض بأعيرته ونقده", [k["karat"] for k in rc["karats"]] == [21] and rc["cash"] == 900, rc)
    y = day_feed.day(conn, d1)
    check("أمس: التوريد بأطقمه", any(g["key"] == "supply" and g["totals"]["sets"] == 5 for g in y["groups"]),
          [(g["key"], g["totals"]) for g in y["groups"]])
    from services import models_web
    html = models_web.page_html(conn, {"tab": "day"}, "/m/x")
    check("صفحة الرابط: تبويب «حركة اليوم» و«عرض» لكل مستند",
          "حركة اليوم" in html and html.count('class="dayd"') == day["count"] and "عيار 21" in html)
    html_y = models_web.page_html(conn, {"tab": "day", "d": d1}, "/m/x")
    check("واختيار يومٍ آخر (أمس)", "الوارد من التصنيع" in html_y and "أمس" in html_y)
    html_bad = models_web.page_html(conn, {"tab": "day", "d": "x';--"}, "/m/x")
    check("تاريخٌ غير صالح في الرابط يُعرض اليوم بأمان", "حركة اليوم" in html_bad and "x';--" not in html_bad)
# 5.2.8: كل مصدرٍ باسم شاشته بالعربية — لا اسم الجدول (كان «workshop_losses» يظهر في رابط المدير)
import re  # noqa: E402
from models.journal import OP_LABELS, _doc_info  # noqa: E402
from services.accounting_engine import _DOC_PREFIX  # noqa: E402
miss = [k for k in _DOC_PREFIX if not re.search(r"[؀-ۿ]", OP_LABELS.get(k, ""))]
check("كل مصادر القيود لها اسمٌ عربي", not miss, miss)
with db(readonly=True) as conn:
    check("فواقد الورشة باسم شاشتها", _doc_info(conn, "workshop_losses", 1, {})[1] == "تسوية فواقد الورشة",
          _doc_info(conn, "workshop_losses", 1, {}))
print(f"{ok} ✔ · {bad} ✘")
sys.exit(1 if bad else 0)
