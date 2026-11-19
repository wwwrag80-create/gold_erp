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


BASE = f"/m/{TOK}"
SEC_PIN = {"v": ""}          # رمزٌ يفتح صفحة الرموز (5.9: لكل زيارة)


def sec_open(pin):
    return call("POST", "ops/unlock", body={"csrf": mw._csrf(TOK, SECRET),
                                            "pin": pin, "next": BASE + "/sec"})


def sec(**data):
    data["csrf"] = mw._csrf(TOK, SECRET)
    _c, b = call("POST", "sec", body=data)
    r = json.loads(b)
    if r.get("locked") and SEC_PIN["v"]:
        sec_open(SEC_PIN["v"])                 # كما يفعل المدير: يفتحها برمزها
        _c, b = call("POST", "sec", body=data)
        r = json.loads(b)
    return r


print("── 1) صفحة الرموز والأقفال في الرابط")
code, h = call("GET", "sec")
check("تُفتح من الرابط (ورابطها في الرأس والتنقل)", code == 200
      and "الرموز والأقفال" in h and "رمز اللوحات المقفلة" in h
      and 'href="/m/' in h and "/sec" in h)
r = sec(kind="panel", act="set", pin="4321", pin2="4321")
SEC_PIN["v"] = "4321"
check("ضبط رمز اللوحات من الرابط (أول مرة بلا رمزٍ حالي)", r.get("ok")
      and mweb.OPS_COOKIE in JAR, r)
with db(readonly=True) as c:
    check("ويُحفظ مشفّراً لا نصّاً", mweb.has_ops_pin(c)
          and "4321" not in mweb._get(c, mweb.K_OPS_PIN))
r = sec(kind="panel", act="set", cur="1111", pin="5555", pin2="5555")
check("تغييره برمزٍ حالي خاطئ يُرفض", not r.get("ok")
      and "الحالي" in r.get("error", ""), r)
r = sec(kind="panel", act="set", cur="4321", pin="5555", pin2="5555")
SEC_PIN["v"] = "5555"
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
SEC_PIN["v"] = "7777"
sec_open("7777")
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

print("── 7) صفحة الرموز تُقفل عند الخروج منها (5.9)")
JAR.pop("mwsec", None)
code, h = call("GET", "sec")
check("بلا فتحٍ لهذه الزيارة: صفحة الرمز", 'name="pin"' in h and "فتح الرموز" in h)
sec_open("0000")
check("ورمزٌ خاطئ لا يفتحها", "mwsec" not in JAR)
sec_open("7777")
code, h = call("GET", "sec")
check("وبرمز اللوحات تُفتح", "mwsec" in JAR and "رمز المدير" in h and 'name="pin"' not in h)
check("وفيها زرّ «قفل وخروج»", "قفل وخروج" in h)
code, h = call("GET", "boxes")
check("الخروج إلى أي صفحةٍ أخرى يمحو فتحها", "mwsec" not in JAR)
code, h = call("GET", "sec")
check("فتعود تطلب الرمز", 'name="pin"' in h)

print("── 8) رمز المدير: قفل التعديل والحذف في البرنامج (5.9)")
r = sec(kind="desk", act="set", pin="2580", pin2="2580")
with db(readonly=True) as c:
    check("ضبط رمز المدير من الرابط يُفعّل القفل", r.get("ok")
          and mweb.has_desk_pin(c) and mweb.desk_locked(c)
          and "2580" not in mweb._get(c, mweb.K_DESK_PIN), r)
r = sec(kind="desk", act="dopen", cur="1111")
check("فتح القفل برمزٍ خاطئ مرفوض", not r.get("ok"), r)
r = sec(kind="desk", act="dopen", cur="2580")
with db(readonly=True) as c:
    check("وبرمز المدير يُفتح", r.get("ok") and not mweb.desk_locked(c), r)
r = sec(kind="desk", act="dlock", cur="2580")
with db(readonly=True) as c:
    check("ويُقفل من جديد", r.get("ok") and mweb.desk_locked(c), r)
JAR.pop("mwsec", None)
sec_open("2580")
code, h = call("GET", "sec")
check("ورمز المدير يفتح صفحة الرموز أيضاً", 'name="pin"' not in h and "رمز المدير" in h)

from services import desk_guard  # noqa: E402
asked = []
answer = {"v": "2580"}


def _prompt(action):
    asked.append(action)
    return answer["v"]


desk_guard.set_prompt(_prompt)
desk_guard.reset()
from models import entities as _ent  # noqa: E402
with db() as c:
    B = add_entity(c, "جهة القفل", "customer", username="t")
answer["v"] = "9999"
try:
    with db() as c:
        _ent.update_entity(c, B, "t", name="جهة القفل 2")
    blocked = False
except desk_guard.ManagerCodeRequired as e:
    blocked = "غير صحيح" in str(e)
with db(readonly=True) as c:
    nm = c.execute("SELECT name FROM entities WHERE id=?", (B,)).fetchone()[0]
check("تعديل جهةٍ في البرنامج برمزٍ خاطئ: يُرفض ولا يُغيَّر شيء", blocked
      and nm == "جهة القفل" and asked and "تعديل الجهات" in asked[-1], (blocked, nm, asked))
answer["v"] = None
try:
    with db() as c:
        _ent.update_entity(c, B, "t", name="جهة القفل 2")
    cancelled = False
except desk_guard.ManagerCodeRequired:
    cancelled = True
check("وإلغاء نافذة الرمز يلغي التعديل", cancelled)
answer["v"] = "2580"
n0 = len(asked)
with db() as c:
    _ent.update_entity(c, B, "t", name="جهة القفل 2")
with db(readonly=True) as c:
    nm = c.execute("SELECT name FROM entities WHERE id=?", (B,)).fetchone()[0]
check("وبرمز المدير يُعدَّل", nm == "جهة القفل 2" and len(asked) == n0 + 1)
with db() as c:
    rv = vouchers.create_voucher(c, "receipt", D0, "t", entity_id=B,
                                 rows=[{"kind": "cash", "amount": 5}])
    vid = rv["id"] if isinstance(rv, dict) else rv
    eid = c.execute("SELECT entry_id FROM vouchers WHERE id=?", (vid,)).fetchone()[0]
n1 = len(asked)
from models import doc_delete as _dd  # noqa: E402
with db() as c:
    _dd.delete(c, eid, "t", "فحص")
from models import numbering as _nb  # noqa: E402
with db(readonly=True) as c:
    vno = c.execute("SELECT voucher_no FROM vouchers WHERE id=?", (vid,)).fetchone()[0]
check("وخلال الدقيقة نفسها يمرّ الحذف بلا سؤالٍ ثانٍ (والسند حُذف وعُكس قيده)",
      bool(eid) and len(asked) == n1 and _nb.RETIRED in str(vno), (eid, vno, len(asked) - n1))
desk_guard.reset()
with db() as c:
    rv = vouchers.create_voucher(c, "receipt", D0, "t", entity_id=B,
                                 rows=[{"kind": "cash", "amount": 6}])
    eid2 = c.execute("SELECT entry_id FROM vouchers WHERE id=?", (rv["id"],)).fetchone()[0]
answer["v"] = "0000"
try:
    with db() as c:
        _dd.delete(c, eid2, "t", "فحص")
    del_blocked = False
except desk_guard.ManagerCodeRequired:
    del_blocked = True
with db(readonly=True) as c:
    vno2 = c.execute("SELECT voucher_no FROM vouchers WHERE id=?", (rv["id"],)).fetchone()[0]
check("وحذف مستندٍ برمزٍ خاطئ يُرفض ويبقى المستند كما هو", del_blocked
      and _nb.RETIRED not in str(vno2) and "حذف المستندات" in asked[-1], vno2)
desk_guard.reset()
answer["v"] = "1"
import threading  # noqa: E402
res = {}


def _bg():
    try:
        with db() as c:
            _ent.update_entity(c, B, "t", name="من الرابط")
        res["ok"] = True
    except Exception as e:
        res["err"] = str(e)


t = threading.Thread(target=_bg)
t.start()
t.join()
check("الرابط (خيط الخادم) لا يُسأل رمز البرنامج — له قفله", res.get("ok"), res)
with db() as c:
    vouchers.create_voucher(c, "receipt", D0, "t", entity_id=B,
                            rows=[{"kind": "cash", "amount": 7}])
check("والتسجيل الجديد لا يطلب الرمز", True)
with db() as c:
    mweb.set_desk_locked(c, False, "t")
n2 = len(asked)
with db() as c:
    _ent.update_entity(c, B, "t", name="بلا قفل")
check("وإن فتحه المدير: التعديل بلا سؤال", len(asked) == n2)
with db() as c:
    mweb.set_desk_locked(c, True, "t")

print("── 9) نافذة «رابط المدير» في دليل الموديلات (5.9)")
import ui.desk_prompt as dp  # noqa: E402
dp_answer = {"v": "1234"}
dp.ask_manager_code = lambda action: dp_answer["v"]
mld_err = []
mld.err = lambda parent, msg: mld_err.append(str(msg))
check("لمستخدم المصنع: برمزٍ خاطئ لا تُفتح",
      ModelsLinkDialog.allowed(None, {"username": "f", "role": "factory"}) is False
      and mld_err and "غير صحيح" in mld_err[-1])
dp_answer["v"] = "2580"
check("وبرمز المدير تُفتح",
      ModelsLinkDialog.allowed(None, {"username": "f", "role": "factory"}) is True)
check("والمدير العام يفتحها بلا رمز (منها يعيد الضبط)",
      ModelsLinkDialog.allowed(None, {"username": "admin", "role": "super_admin"}) is True)
mweb.reset_codes("admin")
with db(readonly=True) as c:
    check("وإعادة الضبط تُلغي رمز المدير وتفتح القفل", not mweb.has_desk_pin(c)
          and not mweb.desk_locked(c))
dp_answer["v"] = None
check("وبلا رمز مدير: النافذة تُفتح بلا سؤال",
      ModelsLinkDialog.allowed(None, {"username": "f", "role": "factory"}) is True)

print(f"\n{len(OK)} ✔ · {len(BAD)} ✘")
os._exit(1 if BAD else 0)
