# اختبار 5.2.1: خطة الحساب (النوع · الشاشات · الاشتراك · الأجهزة) والبيع
# المباشر لحساب «عميل» — python3 tools/check_plans.py
import sys, os, re, tempfile, pathlib, datetime as dt  # noqa: E401
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
T = tempfile.mkdtemp(prefix="tplan_")
import config  # noqa: E402
config.DB_PATH = pathlib.Path(T) / "t.db"
from services import plan, cloud_auth  # noqa: E402
ok = bad = 0


def check(n, c, d=""):
    global ok, bad
    if c:
        ok += 1
        print("  ✔", n)
    else:
        bad += 1
        print("  ✘", n, d)


def raises(fn, needle=""):
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        return needle in str(e)
    return False


print("── الكتالوج يطابق القائمة")
src = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
block = src[src.index("groups = [\n                (None, ["):src.index("# سجل التعديل الشامل")]
nav = [n for n in re.findall(r'\("([^"]+)"', block) if n != "الإدارة والتقارير"]
check("كل شاشة في القائمة لها مكان في الكتالوج",
      set(nav) == set(plan.ALL_SCREENS),
      set(nav) ^ set(plan.ALL_SCREENS))
check("لا تكرار في الكتالوج", len(plan.ALL_SCREENS) == len(set(plan.ALL_SCREENS)))
for k, names in plan.PRESETS.items():
    check(f"شاشات «{plan.TYPE_LABEL[k]}» من الكتالوج",
          set(names) <= set(plan.ALL_SCREENS))
check("العميل بلا شاشة الوارد",
      "الوارد من التصنيع" not in plan.PRESETS[plan.CUSTOMER])
check("العميل يبيع ويرتجع", "مبيعات/مرتجعات" in plan.PRESETS[plan.CUSTOMER])
check("المحل بلا شاشات الورشة",
      "حسابات الورشة" not in plan.PRESETS[plan.SHOP])

print("── قواعد الخطة")
today = dt.date(2026, 11, 8)
p = plan.normalize({"plan_type": "customer", "screens": '["كشف حساب","مبيعات/مرتجعات"]',
                    "expires_at": "2026-11-10", "max_devices": 2,
                    "devices_used": 1, "device_ok": True})
check("النوع والشاشات تُقرأ", p["type"] == "customer" and p["screens"] == ["كشف حساب", "مبيعات/مرتجعات"])
check("الأيام الباقية", plan.days_left(p, today) == 2)
check("اشتراك سارٍ يدخل", not raises(lambda: plan.check(p, today)))
check("اشتراك منتهٍ يُمنع", raises(lambda: plan.check(dict(p, expires_at="2026-11-07"), today), "انتهى الاشتراك"))
check("جهاز زائد يُمنع", raises(lambda: plan.check(dict(p, device_ok=False), today), "الأجهزة"))
check("بلا نهاية", plan.days_left(dict(p, expires_at=""), today) is None)
check("نوع غير معروف ⇒ مصنع", plan.normalize({"plan_type": "x"})["type"] == "factory")
plan.set_current(p)
check("شاشة محددة تظهر", plan.allowed("كشف حساب"))
check("شاشة غير محددة تُخفى", not plan.allowed("القيود اليومية"))
check("شاشة خارج الكتالوج لا تُحجب", plan.allowed("الحسابات وإيقاف المصانع"))
check("العميل يبيع الطقم مباشرةً", plan.free_sets())
plan.set_current(dict(p, screens=[]))
check("قائمة فارغة = كل الشاشات", plan.allowed("القيود اليومية"))
plan.set_current(None)
check("بلا خطة: كل شيء", plan.allowed("القيود اليومية") and not plan.free_sets())
check("هوية الجهاز ثابتة", plan.device_id() == plan.device_id() and len(plan.device_id()) == 32)

print("── الدخول بالخطة (خادم مُحاكى)")
cloud_auth.CACHE = pathlib.Path(T) / "auth_cache.json"
cloud_auth.ADMIN_TOKEN_FILE = pathlib.Path(T) / "admin_token.json"
import hashlib  # noqa: E402
from services.auth import ITER  # noqa: E402
SALT = "00" * 16
PROOF = hashlib.pbkdf2_hmac("sha256", b"pw", bytes.fromhex(SALT), ITER).hex()
server = {"plan": None, "missing_plan": False, "seen": []}


def fake_rpc(fn, payload, timeout=25):
    server["seen"].append(fn)
    if fn == "auth_salt":
        return SALT
    if fn == "auth_login2":
        if payload["p_proof"] != PROOF:
            return []
        return [{"username": "c1", "tenant_id": "F-T1", "role": "factory",
                 "is_active": True, "full_name": "محل", "admin_token": None}]
    if fn == "auth_plan":
        if server["missing_plan"]:
            raise ValueError("دوال الإدارة غير موجودة على الخادم.")
        check("الخطة تُطلب بإثبات كلمة المرور لا بها", payload["p_proof"] == PROOF and "pw" not in str(payload))
        check("الجهاز يُرسل بصمةً", len(payload["p_device"]) == 32)
        return [server["plan"]] if server["plan"] else []
    raise ValueError(f"دالة غير متوقعة {fn}")


cloud_auth._rpc = fake_rpc
from services import tenant  # noqa: E402
tenant.update = lambda **k: None
fut = (dt.date.today() + dt.timedelta(days=30)).isoformat()
server["plan"] = {"plan_type": "customer", "screens": '["مبيعات/مرتجعات"]',
                  "expires_at": fut, "max_devices": 1, "devices_used": 1,
                  "device_ok": True, "server_today": dt.date.today().isoformat()}
s = cloud_auth.login("c1", "pw")
check("دخول بخطة سارية", s["plan"] and s["plan"]["type"] == "customer")
check("الخطة نافذة في الجلسة", plan.kind() == "customer" and not plan.allowed("كشف حساب"))
check("الخطة محفوظة للعمل بلا إنترنت", (cloud_auth._cache_get("c1") or {}).get("plan", {}).get("type") == "customer")

server["plan"] = dict(server["plan"], expires_at=(dt.date.today() - dt.timedelta(days=1)).isoformat())
check("اشتراك منتهٍ: لا دخول", raises(lambda: cloud_auth.login("c1", "pw"), "انتهى الاشتراك"))
server["plan"] = dict(server["plan"], expires_at=fut, device_ok=False)
check("جهاز زائد: لا دخول", raises(lambda: cloud_auth.login("c1", "pw"), "الأجهزة"))

server["plan"] = dict(server["plan"], device_ok=True,
                      expires_at=(dt.date.today() + dt.timedelta(days=3)).isoformat())
s = cloud_auth.login("c1", "pw")
check("تنبيه قبل الانتهاء", "انتهاء الاشتراك" in (s.get("notice") or ""))

server["missing_plan"] = True
s = cloud_auth.login("c1", "pw")
check("خادمٌ لم يُرقَّ: بلا قيود", s["plan"] is None and plan.current() is None)
server["missing_plan"] = False


# بلا إنترنت: الخطة المحفوظة تنطبق
def offline(fn, payload, timeout=25):
    raise OSError("no network")


server["plan"] = dict(server["plan"], expires_at=fut)
cloud_auth.login("c1", "pw")
cloud_auth._rpc = offline
s = cloud_auth.login("c1", "pw")
check("بلا إنترنت: الخطة المحفوظة نافذة", not s["online"] and plan.kind() == "customer")
d = cloud_auth._cache_read()
d["users"]["c1"]["plan"]["expires_at"] = "2020-01-01"
cloud_auth._cache_write(d)
check("بلا إنترنت: الاشتراك المنتهي يُمنع", raises(lambda: cloud_auth.login("c1", "pw"), "انتهى الاشتراك"))
cloud_auth._rpc = fake_rpc
check("الإصدار 3.0.0 يكفي للإدارة العادية", cloud_auth._ver("3.0.0") >= cloud_auth._ver(cloud_auth.RPC_MIN))
check("الخطط تتطلب 3.1.0", cloud_auth._ver("3.0.0") < cloud_auth._ver("3.1.0") <= cloud_auth._ver(cloud_auth.RPC_EXPECTED))

print("── ملف الخادم")
sql = (ROOT / "cloud" / "admin_rpc.sql").read_text(encoding="utf-8")
for fn in ("auth_plan(TEXT,TEXT,TEXT,TEXT)", "admin_set_plan(TEXT,TEXT,TEXT,TEXT,DATE,INT)",
           "admin_list_plans(TEXT)", "admin_reset_devices(TEXT,TEXT)"):
    check(f"صلاحية تنفيذ {fn.split('(')[0]}", f"GRANT EXECUTE ON FUNCTION {fn}" in sql)
check("rpc_version = 3.1.0", "SELECT '3.1.0'::TEXT" in sql)
check("إعادة تشغيل الملف لا تجدّد رموز المدير", "NOT IN ('3.0.0', '3.1.0')" in sql)
check("جدول الأجهزة محميّ", "ALTER TABLE factory_devices ENABLE ROW LEVEL SECURITY" in sql)

print("── البيع المباشر لحساب «عميل»")
from database.database import create_tables, db, migrate_schema, run_migrations_files  # noqa: E402
from database.seed import ensure_new_accounts, ensure_system_tags, seed_initial_data  # noqa: E402
from models.entities import ensure_employee_accrual_accounts, ensure_internal_counterparties, add_entity  # noqa: E402
from models.accounts import acc_id  # noqa: E402
from models import invoices, inventory  # noqa: E402
create_tables(); migrate_schema(); run_migrations_files(); seed_initial_data(); ensure_new_accounts()
with db() as conn:
    ensure_internal_counterparties(conn); ensure_employee_accrual_accounts(conn); ensure_system_tags(conn)


def bal(conn, code):
    r = conn.execute("SELECT ROUND(COALESCE(SUM(l.gold_debit-l.gold_credit),0),3) g FROM journal_lines l"
                     " JOIN journal_entries e ON e.id=l.entry_id WHERE e.is_deleted=0 AND l.account_id=?",
                     (acc_id(conn, code),)).fetchone()
    return r["g"]


with db() as conn:
    c = add_entity(conn, "عميل مباشر", "customer", username="t")
    cid = c if isinstance(c, int) else c["id"]
    wo = inventory.create_direct_stock(conn, "D501", 12.5, 0, 0, None, 8, "2026-11-08", "t")
    check("الطقم يُسجَّل في المخزون", bool(wo) and wo["status"] != "sold", dict(wo) if wo else None)
    check("قيد المخزون مقابل الأرصدة الافتتاحية", bal(conn, "1200") == 12.5 and bal(conn, "3900") == -12.5,
          (bal(conn, "1200"), bal(conn, "3900")))
    s = invoices.create_sale(conn, cid, [{"work_order_id": wo["id"]}], "2026-11-08", "t")
    check("يُباع بالفاتورة", bool(s.get("invoice_no")))
    check("المخزون يعود صفراً بعد البيع", bal(conn, "1200") == 0, bal(conn, "1200"))
    a = conn.execute("SELECT account_id FROM entities WHERE id=?", (cid,)).fetchone()["account_id"]
    g = conn.execute("SELECT ROUND(SUM(l.gold_debit-l.gold_credit),3) g FROM journal_lines l JOIN journal_entries e"
                     " ON e.id=l.entry_id WHERE e.is_deleted=0 AND l.account_id=?", (a,)).fetchone()["g"]
    check("الذهب على العميل", g == 12.5, g)
    check("رقم مكرر يُرفض", raises(lambda: inventory.create_direct_stock(conn, "D501", 3, 0, 0, None, 8, "2026-11-08", "t"), "مستخدم مسبقاً"))
    check("الرقم التجميعي محجوز", raises(lambda: inventory.create_direct_stock(conn, "0010", 3, 0, 0, None, 8, "2026-11-08", "t"), "محجوز"))
    check("بلا وزن يُرفض", raises(lambda: inventory.create_direct_stock(conn, "D502", 0, 0, 0, None, 8, "2026-11-08", "t"), "وزن"))
    tot = conn.execute("SELECT ROUND(SUM(gold_debit)-SUM(gold_credit),3) g FROM journal_lines l"
                       " JOIN journal_entries e ON e.id=l.entry_id WHERE e.is_deleted=0").fetchone()["g"]
    check("الدفتر متوازن", abs(tot or 0) < 0.001, tot)

print("── القائمة تُخفي ما لم تحدده الإدارة")
from PyQt5 import QtWidgets  # noqa: E402
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
from ui import kit  # noqa: E402
try:
    kit.apply(app)
except Exception:
    pass
from ui.main_window import MainWindow  # noqa: E402
plan.set_current({"plan_type": "customer", "screens": list(plan.PRESETS[plan.CUSTOMER])})
win = MainWindow({"username": "c1", "full_name": "محل", "role": "factory",
                  "role_local": "accountant", "tenant_id": "", "is_super": False})
shown = {it.data(0, 0x0101): it.isHidden() for it, _ in win._iter_nav()}
idx_in = win._index_of("الوارد من التصنيع")
idx_ok = win._index_of("مبيعات/مرتجعات")
check("الوارد مخفي للعميل", not win._plan_allows(idx_in))
check("المبيعات ظاهرة للعميل", win._plan_allows(idx_ok))
hidden = [it.text(0) for it, _ in win._iter_nav() if it.isHidden()]
check("بنود القائمة المخفية = ما لم يُحدَّد", "الوارد من التصنيع" in hidden and "مبيعات/مرتجعات" not in hidden, hidden[:5])
_c_info = []
import ui.main_window as _mw  # noqa: E402
_mw.info = lambda *a, **k: _c_info.append(a[1] if len(a) > 1 else "")
win.switch(idx_in)
check("فتح شاشة غير مفعّلة يُرفض برسالة", win._current_row != idx_in and _c_info and "غير مفعّلة" in _c_info[0])
pal = [x[3] for x in win._palette_static() if x[0] == "screen" or isinstance(x[3], int)]
check("البحث الموحّد لا يعرض المخفية", idx_in not in pal)
win.close()
plan.set_current(None)

print("── نافذة الخطة")
from ui.plan_dialog import PlanDialog, summary  # noqa: E402
d = PlanDialog(None, "اختبار")
check("حساب جديد: مصنع بكل الشاشات وسنة وجهاز", d.values()["type"] == "factory" and d.values()["screens"] == []
      and d.values()["max_devices"] == 1 and d.values()["expires_at"] > dt.date.today().isoformat())
d.kind.setCurrentIndex(d.kind.findData("customer"))
v = d.values()
check("اختيار «عميل» يضع شاشاته", v["type"] == "customer" and set(v["screens"]) == set(plan.PRESETS["customer"]))
d.unlimited.setChecked(True)
d.devices.setValue(0)
check("بلا نهاية وبلا حد", d.values()["expires_at"] == "" and d.values()["max_devices"] == 0)
d2 = PlanDialog(None, "تعديل", current={"plan_type": "shop", "screens": '["كشف حساب"]',
                                         "expires_at": "2027-01-31", "max_devices": 3},
                devices_used=2, on_reset_devices=lambda: True)
v2 = d2.values()
check("الخطة الحالية تُعرض كما هي", v2 == {"type": "shop", "screens": ["كشف حساب"],
                                          "expires_at": "2027-01-31", "max_devices": 3}, v2)
check("ملخص الجدول", summary({"plan_type": "customer", "expires_at": "2020-01-01", "max_devices": 2,
                              "devices_used": 1})[1].endswith("(منتهٍ)"))
from ui.super_admin_screen import SuperAdminScreen  # noqa: E402
sa = SuperAdminScreen({"username": "admin", "is_super": True})
sa.users = [{"username": "c1", "full_name": "محل", "tenant_id": "F-T1", "role": "factory", "is_active": True}]
sa.plans = {"F-T1": plan.normalize({"plan_type": "customer", "expires_at": "2027-01-01", "max_devices": 2,
                                    "devices_used": 1})}
sa._fill_users()
check("جدول الحسابات يعرض النوع والاشتراك والأجهزة",
      sa.users_table.item(0, 4).text() == "عميل" and sa.users_table.item(0, 5).text() == "2027-01-01"
      and sa.users_table.item(0, 6).text() == "1 / 2")

print(f"\n{ok} ✔  ·  {bad} ✘")
sys.exit(1 if bad else 0)
