"""5.5 (دوال الخادم 3.2.0): تعديل الحساب وملفّه — القائمة والهوية.

    python3 tools/check_account_profile.py

المدير العام يرتّب قائمة الحساب (ترتيب · أسماء · مجموعات · شاشةٌ داخل
شاشة) ويضع هويته وشعاره، فيُطبَّق ذلك عند دخول الحساب التالي — ويبقى
للمستخدم ما يعدّله بعدها حتى يحفظ المدير ملفاً جديداً. والخادم مُحاكى هنا
(دوال الخادم نفسها تُفحص على PostgreSQL حقيقي في تحقق الإصدار).
"""
import hashlib
import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
T = tempfile.mkdtemp(prefix="acprof_")
os.environ["GOLD_ERP_DATA_DIR"] = T
import config  # noqa: E402

config.DB_PATH = pathlib.Path(T) / "t.db"
import main  # noqa: E402

for _l, f in main.prepare_steps():
    f()
from database.database import db  # noqa: E402
from services import account_profile as ap  # noqa: E402
from services import branding, cloud_auth, plan, tenant  # noqa: E402
from services.auth import ITER  # noqa: E402

OK, BAD = [], []


def check(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print(("  ✔ " if cond else "  ✘ ") + name + ("" if cond else f"  [{info}]"))


def raises(fn, needle=""):
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        return needle in str(e)
    return False


cloud_auth.CACHE = pathlib.Path(T) / "auth_cache.json"
cloud_auth.ADMIN_TOKEN_FILE = pathlib.Path(T) / "admin_token.json"
tenant.update = lambda **k: None
SALT = "11" * 16
PROOF = hashlib.pbkdf2_hmac("sha256", b"pw", bytes.fromhex(SALT), ITER).hex()
S = {"profile": None, "ver": 0, "calls": [], "users": {}}


def fake_rpc(fn, payload, timeout=25):
    S["calls"].append((fn, payload))
    if fn == "rpc_version":
        return "3.2.0"
    if fn == "auth_salt":
        return SALT
    if fn == "auth_login2":
        if payload["p_proof"] != PROOF:
            return []
        return [{"username": "shop1", "tenant_id": "F-S1", "role": "factory",
                 "is_active": True, "full_name": "محل", "admin_token": None}]
    if fn == "auth_plan":
        return [{"plan_type": "shop", "screens": "", "expires_at": None,
                 "max_devices": 0, "devices_used": 1, "device_ok": True}]
    if fn == "auth_profile":
        if payload["p_proof"] != PROOF:
            return []
        have = int(payload.get("p_have") or 0)
        return [{"ver": S["ver"],
                 "data": S["profile"] if S["ver"] > have else None}]
    if fn == "admin_set_profile":
        S["profile"] = payload["p_profile"]
        S["ver"] += 1
        return S["ver"]
    if fn == "admin_get_profile":
        return [{"ver": S["ver"], "data": S["profile"]}]
    if fn == "admin_update_user":
        S["users"][payload["p_username"]] = payload
        return "ok"
    raise ValueError(f"دالة غير متوقعة {fn}")


cloud_auth._rpc = fake_rpc
cloud_auth.save_admin_token("tok-admin")

print("── شجرة القائمة")
dn = ap.default_nodes()
keys = [n["key"] for n in dn] + [c["key"] for n in dn for c in n["children"]]
check("القائمة الافتراضية فيها كل الشاشات مرةً واحدة",
      sorted(k for k in keys if not k.startswith("::")) ==
      sorted(plan.ALL_SCREENS), len(keys))
check("الشاشات المقيّدة بالخطة وحدها",
      [n["key"] for n in ap.default_nodes(["كشف حساب"])] == ["كشف حساب"])
messy = [{"idx": 1, "key": "كشف حساب", "text": " "},
         {"idx": 2, "key": "كشف حساب", "text": "مكرر"},
         {"idx": 3, "key": "شاشة لا وجود لها", "text": "x"},
         {"idx": -1, "key": "::group::فارغة", "text": "فارغة", "children": []}]
cl = ap.clean_nodes(messy)
check("التنظيف: المكرر والمجهول والمجموعة الفارغة تُحذف والاسم الفارغ يعود",
      cl == [{"idx": 1, "key": "كشف حساب", "text": "كشف حساب",
              "expanded": False, "children": []}], cl)

print("── المدير يحفظ الملف")
LOGO = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGA"
        "hKmMIQAAAABJRU5ErkJggg==")
ident = dict(branding.blank(), name="محل الذهب الأبيض", vat="300000000000003",
             address="الرياض", logo_b64=LOGO, hide_logo=False)
nav = [
    {"idx": 1, "key": "مبيعات/مرتجعات", "text": "البيع اليومي",
     "children": [{"idx": 2, "key": "المبيعات الضريبية",
                   "text": "فواتير الضريبة"}]},
    {"idx": -1, "key": "::group::المشتريات·1", "text": "المشتريات كلها",
     "children": [{"idx": 3, "key": "المشتريات الضريبية", "text": "شراء أطقم"},
                  {"idx": 4, "key": "المشتريات", "text": "المشتريات"}]},
    {"idx": 5, "key": "كشف حساب", "text": "كشف حساب"},
]
v1 = cloud_auth.set_profile("F-S1", nav, ident)
sent = json.loads(S["profile"])
check("الإصدار 1 محفوظ", v1 == 1 and S["ver"] == 1)
check("القائمة والهوية في الملف", sent["nav"][0]["text"] == "البيع اليومي"
      and sent["identity"]["name"] == "محل الذهب الأبيض"
      and sent["identity"]["logo_b64"] == LOGO)
check("هوية بلا اسم تُرفض قبل الإرسال",
      raises(lambda: cloud_auth.set_profile("F-S1", nav,
                                            dict(ident, name="")), ""))
_big = __import__("base64").b64encode(
    b"\x89PNG\r\n\x1a\n" + b"\0" * 2_800_000).decode()
check("ملفٌ أكبر من الحد يُرفض", raises(
    lambda: ap.pack(nav, dict(ident, logo_b64=_big)), "كبير"))
check("صورةٌ غير صالحة تُرفض", raises(
    lambda: ap.pack(nav, dict(ident, logo_b64="QUJD")), "غير صالحة"))
prof, ver = cloud_auth.get_profile("F-S1")
check("قراءة الملف من الخادم", ver == 1 and prof["nav"][1]["text"] == "المشتريات كلها")

print("── أول دخولٍ بعد الحفظ: يُطبَّق")
s = cloud_auth.login("shop1", "pw")
lay = json.loads(ap.nav_path().read_text(encoding="utf-8"))
check("ملف القائمة كُتب بصيغة القائمة نفسها",
      lay["version"] == ap.NAV_VERSION and lay["nodes"][0]["text"] == "البيع اليومي")
check("الهوية طُبِّقت", config.COMPANY_NAME == "محل الذهب الأبيض"
      and config.COMPANY_VAT_NUMBER == "300000000000003")
with db(readonly=True) as conn:
    check("الإصدار المطبَّق محفوظ في قاعدة المنشأة", ap.applied_ver(conn) == 1)
ask = [p for f, p in S["calls"] if f == "auth_profile"][-1]
check("الملف يُطلب بإثبات كلمة المرور لا بها",
      ask["p_proof"] == PROOF and "pw" not in json.dumps(ask) and ask["p_have"] == 0)
check("ملف الحساب لا يُخزَّن في ذاكرة الدخول بلا إنترنت",
      "profile" not in (cloud_auth._cache_get("shop1") or {}))

print("── القائمة كما تظهر للحساب")
from PyQt5 import QtWidgets  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
from ui import kit  # noqa: E402
try:
    kit.apply(app)
except Exception:
    pass
from ui.main_window import NAV_KEY_ROLE, MainWindow  # noqa: E402
plan.set_current(None)
win = MainWindow({"username": "shop1", "full_name": "محل", "role": "factory",
                  "role_local": "accountant", "tenant_id": "F-S1",
                  "is_super": False})
top = [win.sidebar.topLevelItem(i) for i in range(win.sidebar.topLevelItemCount())]
txt = [t.text(0) for t in top]
# الشاشات التي لم يضعها المدير تُلحق بجوار جارتها الافتراضية — وترتيبه
# لما وضعه باقٍ كما هو
_pos = [txt.index(x) for x in ("البيع اليومي", "المشتريات كلها", "كشف حساب")
        if x in txt]
check("الترتيب والأسماء كما رتّبها المدير",
      len(_pos) == 3 and _pos == sorted(_pos) and _pos[0] == 0, txt[:5])
kids0 = [top[0].child(i) for i in range(top[0].childCount())]
check("شاشةٌ داخل شاشة", any(k.data(0, NAV_KEY_ROLE) == "المبيعات الضريبية"
                              and k.text(0) == "فواتير الضريبة" for k in kids0),
      [k.text(0) for k in kids0])
_grp = top[txt.index("المشتريات كلها")] if "المشتريات كلها" in txt else None
check("المجموعة الجديدة بشاشاتها", _grp is not None and
      [_grp.child(i).text(0) for i in range(_grp.childCount())]
      == ["شراء أطقم", "المشتريات"])
names = {it.data(0, NAV_KEY_ROLE) for it, _ in win._iter_nav()}
check("لا شاشة تضيع: ما لم يرتّبه المدير يُلحق آخر القائمة",
      set(plan.ALL_SCREENS) <= names, set(plan.ALL_SCREENS) - names)
_adm = top[txt.index("الإدارة والتقارير")] if "الإدارة والتقارير" in txt \
    else None
check("وشاشات الإدارة الناقصة في مجموعتها لا في مجموعة المدير",
      _adm is not None and _adm.childCount() == len(plan.ADMIN_SCREENS)
      and txt.index("الإدارة والتقارير") == len(txt) - 1, txt[-3:])
i_tax = win._index_of("فواتير الضريبة") if hasattr(win, "_index_of") else None
win.close()

print("── المستخدم يعدّل ثم يدخل من جديد: تعديله يبقى")
lay["nodes"][0]["text"] = "مبيعاتي"
ap.nav_path().write_text(json.dumps(lay, ensure_ascii=False), encoding="utf-8")
with db() as conn:
    branding.save(conn, dict(ident, name="اسمي أنا"), "shop1")
cloud_auth.login("shop1", "pw")
lay2 = json.loads(ap.nav_path().read_text(encoding="utf-8"))
check("ترتيب المستخدم باقٍ", lay2["nodes"][0]["text"] == "مبيعاتي")
check("هوية المستخدم باقية", config.COMPANY_NAME == "اسمي أنا")
ask = [p for f, p in S["calls"] if f == "auth_profile"][-1]
check("الجهاز يُخبر بما طُبِّق فلا يُنزَّل الشعار ثانيةً", ask["p_have"] == 1)

print("── المدير يحفظ ملفاً جديداً: يُطبَّق هو")
nav2 = [dict(nav[2], text="كشف الحساب"), nav[0]]
cloud_auth.set_profile("F-S1", nav2, dict(ident, name="محل الذهب — الفرع"))
cloud_auth.login("shop1", "pw")
lay3 = json.loads(ap.nav_path().read_text(encoding="utf-8"))
check("القائمة الجديدة", lay3["nodes"][0]["text"] == "كشف الحساب")
check("الهوية الجديدة", config.COMPANY_NAME == "محل الذهب — الفرع")
with db(readonly=True) as conn:
    check("الإصدار 2 مطبَّق", ap.applied_ver(conn) == 2)
ver_before = S["ver"]


def broken(fn, payload, timeout=25):
    if fn == "auth_profile":
        raise OSError("timeout")
    return fake_rpc(fn, payload, timeout)


cloud_auth._rpc = broken
check("تعذّر جلب الملف لا يمنع الدخول",
      cloud_auth.login("shop1", "pw")["username"] == "shop1")
cloud_auth._rpc = fake_rpc
with db() as conn:
    check("ملفٌ تالف لا يكسر شيئاً", ap.apply(conn, 99, "{not json") == []
          and ap.applied_ver(conn) == 99)

print("── تعديل الحساب")
cloud_auth.update_account("shop1", "صاحب المحل", "newpass", "محل جديد")
u = S["users"]["shop1"]
check("الاسم واسم المصنع يُرسلان", u["p_full_name"] == "صاحب المحل"
      and u["p_factory_name"] == "محل جديد")
check("كلمة المرور تُرسل مجزّأةً لا نصاً",
      "newpass" not in json.dumps(u) and "$" in u["p_hash"])
check("كلمة المرور الجديدة تُسقط الذاكرة القديمة",
      cloud_auth._cache_get("shop1") is None)
check("كلمة مرور قصيرة تُرفض", raises(
    lambda: cloud_auth.update_account("shop1", "", "12", ""), "قصيرة"))
check("بلا تعديل يُرفض", raises(
    lambda: cloud_auth.update_account("shop1"), "لا تعديل"))

print("── محرّر القائمة لدى المدير")
from ui.account_profile_dialog import (AccountProfileDialog, EditAccountDialog,  # noqa: E402
                                       NavEditor)
ed = NavEditor(["كشف حساب", "مبيعات/مرتجعات"])
ed.load([])
check("محرّرٌ فارغ يبدأ بالترتيب الافتراضي",
      len(ed.nodes()) >= 2 and ed.nodes()[0]["key"] == plan.MAIN_SCREENS[0])
ed.load(nav)
def _shape(nodes):
    return [(n["key"], n["text"], _shape(n.get("children") or []))
            for n in nodes]


check("يُحمَّل ملف الحساب كما هو", _shape(ed.nodes())[:3] ==
      _shape(ap.clean_nodes(nav))[:3], _shape(ed.nodes())[:3])
first = ed.tree.topLevelItem(1)
ed.tree.setCurrentItem(first)
ed.ungroup()
keys_top = [ed.tree.topLevelItem(i).data(0, 0x0101)
            for i in range(ed.tree.topLevelItemCount())]
check("فكّ المجموعة يبقي شاشاتها في مكانها",
      keys_top[1:3] == ["المشتريات الضريبية", "المشتريات"], keys_top[:4])
ed.tree.setCurrentItem(ed.tree.topLevelItem(1))
ed.original_name()
check("الاسم الأصلي يعود", ed.tree.topLevelItem(1).text(0) == "المشتريات الضريبية")
gray = [ed.tree.topLevelItem(i) for i in range(ed.tree.topLevelItemCount())
        if ed.tree.topLevelItem(i).data(0, 0x0101) == "المشتريات الضريبية"][0]
check("الشاشة خارج الاشتراك تظهر رماديةً للمدير", "خارج اشتراك" in gray.toolTip(0))
dlg = AccountProfileDialog.create(None, "F-S1", "محل", screens=None,
                                  user={"username": "admin", "is_super": True})
check("نافذة الملف تقرأ الإصدار والهوية من الخادم",
      dlg.ver == S["ver"] and dlg.identity.get("name") == "محل الذهب — الفرع")
import ui.account_profile_dialog as _apd  # noqa: E402
_apd.info = lambda *a, **k: None
dlg.save()
check("الحفظ يرفع إصداراً جديداً", S["ver"] == ver_before + 1)
ea = EditAccountDialog(None, {"username": "shop1", "full_name": "صاحب المحل",
                              "role": "factory"})
_apd.err = lambda _p, e, *a: OK.append("x") if False else BAD.append(f"err {e}")
ea.pw1.setText("abcd1")
ea.pw2.setText("abcd1")
ea.save()
check("نافذة تعديل الحساب ترسل كلمة المرور المجزّأة",
      S["users"]["shop1"]["p_hash"] and S["users"]["shop1"]["p_full_name"] == "")

print("── ملف الخادم")
sql = (ROOT / "cloud" / "admin_rpc.sql").read_text(encoding="utf-8")
for fn in ("admin_update_user(TEXT,TEXT,TEXT,TEXT,TEXT)",
           "admin_set_profile(TEXT,TEXT,TEXT)", "admin_get_profile(TEXT,TEXT)",
           "auth_profile(TEXT,TEXT,INT)"):
    check(f"صلاحية تنفيذ {fn.split('(')[0]}", f"GRANT EXECUTE ON FUNCTION {fn}" in sql)
check("rpc_version = 3.2.0 والعميل يطلبه",
      "SELECT '3.2.0'::TEXT" in sql and cloud_auth.RPC_EXPECTED == "3.2.0")
check("إعادة تشغيل الملف لا تجدّد رموز المدير",
      "NOT IN ('3.0.0', '3.1.0', '3.2.0')" in sql)

print(f"\n{len(OK)} ✔  ·  {len(BAD)} ✘")
sys.exit(1 if BAD else 0)
