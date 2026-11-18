"""5.8.6: الرموز والأقفال من رابط المدير نفسه — و«فرز» الكشف بالعملية.

    python3 tools/check_link_security.py

* صفحة «الرموز والأقفال» في الرابط: رمز اللوحات يُضبط منها، وتغييره أو
  إلغاؤه يطلب الرمز الحالي (والخاطئ يُرفض)، واللوحات المقفلة يختارها المدير
  (كشف الحساب · الأرباح … تطلب الرمز، وما لم يُختر مفتوح)، ورمز قفل التعديل
  والحذف ورمز الدخول كذلك، والسماح بالتسجيل.
* إعادة الضبط من البرنامج (المدير العام) تُلغي الرموز ويظهر ذلك في الرابط.
* «فرز» في كشف الحساب: قائمة العمليات ومجموع كل صفّ.
"""
import datetime
import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
T = tempfile.mkdtemp(prefix="linksec_")
os.environ["GOLD_ERP_DATA_DIR"] = T
import config  # noqa: E402

config.DB_PATH = pathlib.Path(T) / "t.db"
import main  # noqa: E402

for _l, f in main.prepare_steps():
    f()
from database.database import db  # noqa: E402
from models import vouchers  # noqa: E402
from models.entities import add_entity  # noqa: E402
from services import manager_web as mweb  # noqa: E402
from services import models_web as mw  # noqa: E402

OK, BAD = [], []


def check(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print(("  ✔ " if cond else "  ✘ ") + name + ("" if cond else f"  [{info}]"))


D0 = datetime.date.today().isoformat()
with db() as c:
    A = add_entity(c, "محل الفرز", "customer", username="t")
    vouchers.create_voucher(c, "receipt", D0, "t", entity_id=A,
                            rows=[{"kind": "cash", "amount": 100}])
    vouchers.create_voucher(c, "payment", D0, "t", entity_id=A,
                            rows=[{"kind": "cash", "amount": 40}])
    TOK = mw.ensure_token(c)
    mw.set_enabled(c, True)
    SECRET = mw._get(c, mw.K_SECRET)
    A_CODE = c.execute("SELECT a.code FROM entities e JOIN accounts a ON"
                       " a.id=e.account_id WHERE e.id=?", (A,)).fetchone()[0]
JAR = {}


def call(method, path, query=None, body=None):
    headers = {}
    if JAR:
        headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in JAR.items())
    parts = [TOK] + [p for p in path.split("/") if p]
    raw = (json.dumps(body, ensure_ascii=False).encode("utf-8")
           if body is not None else None)
    r = mw.handle(method, parts, query or {}, headers, raw)
    for k, v in (r.get("headers") or {}).items():
        if k.lower() == "set-cookie":
            name, val = v.split(";", 1)[0].split("=", 1)
            if val:
                JAR[name] = val
            else:
                JAR.pop(name, None)
    b = r["body"]
    return r["code"], (b.decode("utf-8", "replace")
                       if isinstance(b, bytes) else b)


def sec(**data):
    data["csrf"] = mw._csrf(TOK, SECRET)
    _c, b = call("POST", "sec", body=data)
    return json.loads(b)


print("── 1) صفحة الرموز والأقفال في الرابط")
code, h = call("GET", "sec")
check("تُفتح من الرابط (ورابطها في الرأس والتنقل)", code == 200
      and "الرموز والأقفال" in h and "رمز اللوحات المقفلة" in h
      and 'href="/m/' in h and "/sec" in h)
r = sec(kind="panel", act="set", pin="4321", pin2="4321")
check("ضبط رمز اللوحات من الرابط (أول مرة بلا رمزٍ حالي)", r.get("ok")
      and mweb.OPS_COOKIE in JAR, r)
with db(readonly=True) as c:
    check("ويُحفظ مشفّراً لا نصّاً", mweb.has_ops_pin(c)
          and "4321" not in mweb._get(c, mweb.K_OPS_PIN))
r = sec(kind="panel", act="set", cur="1111", pin="5555", pin2="5555")
check("تغييره برمزٍ حالي خاطئ يُرفض", not r.get("ok")
      and "الحالي" in r.get("error", ""), r)
r = sec(kind="panel", act="set", cur="4321", pin="5555", pin2="5555")
check("وبالرمز الحالي يتغيّر (والجهاز يبقى داخلاً)", r.get("ok"), r)
code, h = call("GET", "ops")
check("لوحة التسجيل تفتح بالمفتاح الجديد", "بيع" in h and 'name="pin"'
      not in h)

print("── 2) اللوحات المقفلة يختارها المدير")
r = sec(kind="panel", act="panels", panels=["ops", "tax", "stmt", "pnl"])
check("حفظ اللوحات المقفلة", r.get("ok"), r)
saved = dict(JAR)
JAR.pop(mweb.OPS_COOKIE, None)
code, h = call("GET", "stmt", {"code": A_CODE})
check("كشف الحساب (مقفل) يطلب الرمز", 'name="pin"' in h
      and "لوحة مقفلة" in h)
code, h = call("GET", "", {"tab": "pnl"})
check("والأرباح والخسائر (مقفلة) كذلك", 'name="pin"' in h)
code, h = call("GET", "boxes")
check("والصناديق (غير مختارة) مفتوحة", 'name="pin"' not in h
      and "الصناديق" in h)
code, h = call("GET", "")
check("وعلى المقفلة 🔒 في الرئيسية", "كشف حساب 🔒" in h
      and "الصناديق 🔒" not in h)
code, h = call("GET", "sec")
check("وصفحة الرموز نفسها تطلب رمز اللوحات", 'name="pin"' in h)
JAR.update(saved)
code, h = call("GET", "stmt", {"code": A_CODE})
check("وبالرمز يُفتح الكشف", 'name="pin"' not in h and "محل الفرز" in h)

print("── 3) «فرز» الكشف بالعملية")
check("قائمة «فرز» بجانب البحث، ولكل صفٍّ عمليته ومجموعه",
      'id="mop"' in h and 'id="mopsum"' in h and 'data-op="' in h
      and "data-sum=" in h and "فرز: كل العمليات" in h)
ops = set(__import__("re").findall(r'data-op="([^"]+)"', h))
check("عمليات الكشف في الصفوف (قبض · صرف)", len(ops) >= 2, ops)

print("── 4) رمز قفل التعديل والحذف ورمز الدخول")
r = sec(kind="edit", act="set", pin="2468", pin2="2468")
with db(readonly=True) as c:
    check("رمز قفل التعديل والحذف من الرابط", r.get("ok")
          and mweb.has_edit_pin(c), r)
r = sec(kind="edit", act="clear", cur="0000")
check("وإلغاؤه بلا رمزه الصحيح مرفوض", not r.get("ok"), r)
r = sec(kind="login", act="set", pin="9999", pin2="9999")
check("رمز دخول الرابط من الرابط — والجهاز يبقى داخلاً", r.get("ok")
      and mw.COOKIE in JAR, r)
code, h = call("GET", "boxes")
check("فلا يُطلب منه الدخول من جديد", "الصناديق" in h)
other = dict(JAR)
JAR.clear()
code, h = call("GET", "boxes")
check("وجهازٌ آخر بلا الرمز يُطلب منه الدخول", 'name="pin"' in h)
JAR.update(other)
r = sec(kind="ops", act="ops")
with db(readonly=True) as c:
    check("إيقاف التسجيل من الرابط نفسه", r.get("ok")
          and not mweb.ops_enabled(c), r)
r = sec(kind="ops", act="ops")
with db(readonly=True) as c:
    check("والسماح به", mweb.ops_enabled(c))

print("── 5) إعادة الضبط من البرنامج (المدير العام)")
mweb.reset_codes("admin")
with db(readonly=True) as c:
    check("تُلغى الرموز كلها", not mweb.has_ops_pin(c)
          and not mweb.has_edit_pin(c) and not mw._get(c, mw.K_PIN))
JAR.clear()
code, h = call("GET", "sec")
check("ويرى المدير في الرابط أنها أُعيد ضبطها", "أُعيد ضبط الرموز" in h)
r = sec(kind="panel", act="set", pin="7777", pin2="7777")
code, h = call("GET", "sec")
check("وتختفي الملاحظة بعد أن يضبطها من جديد", r.get("ok")
      and "أُعيد ضبط الرموز" not in h)

print("── 6) نافذة الرابط في البرنامج بلا رموز")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5 import QtWidgets  # noqa: E402
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
from ui.models_link_dialog import ModelsLinkDialog  # noqa: E402
import ui.models_link_dialog as mld  # noqa: E402
mld.ModelsLinkDialog._load = lambda self: None
d = ModelsLinkDialog(None, {"username": "f", "role": "factory"})
shown = [w for w in d.findChildren(QtWidgets.QLineEdit)
         if w.echoMode() == QtWidgets.QLineEdit.Password and w.isVisibleTo(d)]
check("لا خانة رمزٍ في نافذة البرنامج", not shown, len(shown))
check("ولا زرّ إعادة الضبط لمستخدم المصنع", not d.btn_reset.isVisibleTo(d))
d2 = ModelsLinkDialog(None, {"username": "admin", "role": "super_admin"})
check("وللمدير العام زرّ «إعادة ضبط رموز الرابط»",
      d2.btn_reset.isVisibleTo(d2))

print(f"\n{len(OK)} ✔ · {len(BAD)} ✘")
os._exit(1 if BAD else 0)
