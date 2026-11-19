"""رابط المدير لكل مصنعٍ وحده — ببيانات مصنعه وحده (5.10.3).

    python3 tools/check_tenant_links.py

مصنعان (حسابان) على الجهاز نفسه:
* لكلٍّ قاعدة بياناتٍ مستقلة (`tenants/<هويته>/gold_erp.db`) وصوره وفهرس
  بحثه بالصورة وذاكرة صوره المصغّرة في مجلّده وحده.
* ولكلٍّ رابط مديرٍ برمزٍ عشوائيٍّ مختلف وسرٍّ ورموز أقفالٍ خاصة به.
* رابط المصنع يعرض موديلاته وجهاته وحده — ولا يفتح رابطُه بياناتِ الآخر
  ولا صورَه، ولو كان الآخر هو المفتوح على الجهاز (يرد «الرابط غير صالح»).
* ورمز دخول رابطٍ أو رمز مديره لا يسري على الآخر.
"""
import datetime
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
T = tempfile.mkdtemp(prefix="tenants_")
os.environ["JADEITE_DATA_DIR"] = T
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import config  # noqa: E402
import main  # noqa: E402
from PyQt5 import QtGui  # noqa: E402

from database.database import db  # noqa: E402
from models import inventory, models_catalog as mc  # noqa: E402
from models.entities import add_entity  # noqa: E402
from services import manager_web as mweb  # noqa: E402
from services import models_web as mw  # noqa: E402
from services import tenant_db  # noqa: E402
from services import vision_search as vs  # noqa: E402

OK, BAD = [], []


def check(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print(("  ✔ " if cond else "  ✘ ") + name + ("" if cond else f"  [{info}]"))


def png(path, rgb):
    im = QtGui.QImage(120, 80, QtGui.QImage.Format_RGB32)
    im.fill(QtGui.QColor(*rgb))
    assert im.save(str(path), "PNG")


D0 = datetime.date.today().isoformat()
F = {}
for tid, model, party, rgb in (("factory-A-1111", "MA1", "جهة المصنع أ", (200, 160, 40)),
                               ("factory-B-2222", "MB1", "جهة المصنع ب", (40, 90, 200))):
    tenant_db.set_active_tenant(tid)
    for _l, f in main.prepare_steps():
        f()
    with db() as c:
        add_entity(c, party, "customer", username="t")
        inventory.create_work_orders_batch(c, [
            {"wo_no": f"{model}-1", "model_no": model, "gold": 10,
             "small_stones": 0, "big_stones": 0, "wage_per_gram": 5}], D0, "t")
        tok = mw.ensure_token(c)
        mw.set_enabled(c, True)
        secret = mw._get(c, mw.K_SECRET)
    png(mc.images_dir() / f"{model}.png", rgb)
    F[tid] = {"db": str(config.DB_PATH), "tok": tok, "secret": secret,
              "model": model, "party": party, "img": str(mc.images_dir()),
              "vision": str(vs._root()), "thumbs": str(mw._disk_path(("x",)).parent)}
A, B = F["factory-A-1111"], F["factory-B-2222"]


def get(path_parts, tok, query=None, pin=None, secret=None):
    h = {}
    if pin:
        h["Cookie"] = f"{mw.COOKIE}={mw._cookie_value(tok, secret, pin)}"
    r = mw.handle("GET", [tok] + path_parts, query or {}, h, None)
    b = r["body"]
    return r["code"], (b.decode("utf-8", "replace") if isinstance(b, bytes) else b)


print("── 1) لكل مصنعٍ ملفّاته وحده")
check("قاعدتا بياناتٍ مختلفتان في مجلّد كل مصنع",
      A["db"] != B["db"] and "factory-A-1111" in A["db"] and "factory-B-2222" in B["db"]
      and pathlib.Path(A["db"]).exists() and pathlib.Path(B["db"]).exists(), (A["db"], B["db"]))
check("وصور الموديلات · فهرس البحث بالصورة · الصور المصغّرة: لكلٍّ مجلّده",
      A["img"] != B["img"] and A["vision"] != B["vision"] and A["thumbs"] != B["thumbs"]
      and all("factory-A" in A[k] for k in ("img", "vision", "thumbs"))
      and all("factory-B" in B[k] for k in ("img", "vision", "thumbs")))

print("── 2) لكل مصنعٍ رابطه")
check("رمز الرابط مختلف (عشوائي طويل لكلٍّ)", A["tok"] != B["tok"]
      and len(A["tok"]) >= 20 and len(B["tok"]) >= 20)
check("وسرّ التوقيع مختلف", A["secret"] != B["secret"])

print("── 3) الرابط يعرض بيانات مصنعه وحده")
tenant_db.set_active_tenant("factory-B-2222")          # المفتوح الآن: ب
code, h = get([], B["tok"], {"tab": "guide"})
check("رابط ب (والمفتوح ب): موديلاته وحده", code == 200 and "MB1" in h and "MA1" not in h)
code, h = get([], A["tok"], {"tab": "guide"})
check("رابط أ والمفتوح ب: «الرابط غير صالح» — لا يُرى شيءٌ من ب",
      code == 404 and "MB1" not in h and "غير صالح" in h, code)
code, _ = get(["img", "MB1"], A["tok"])
check("ولا صور ب برمز أ", code == 404)
code, _ = get(["vis"], A["tok"])
check("ولا البحث بالصورة لـ ب برمز أ", code == 404)
tenant_db.set_active_tenant("factory-A-1111")
code, h = get([], A["tok"], {"tab": "guide"})
check("رابط أ (والمفتوح أ): موديلاته وحده", code == 200 and "MA1" in h and "MB1" not in h)
code, h = get(["img", "MA1"], A["tok"])
check("وصورته", code == 200)
code, h = get([], B["tok"], {"tab": "guide"})
check("ورابط ب والمفتوح أ: غير صالح", code == 404 and "MA1" not in h)
code, h = get(["stmt"], A["tok"], {"q": "جهة"})
check("وجهات أ وحدها في رابطه", B["party"] not in h)

print("── 4) الرموز لكل مصنعٍ وحده")
with db() as c:
    mw.set_pin(c, "1111", "t")                          # رمز دخول رابط أ
    mweb.set_desk_pin(c, "2580", "t")                   # رمز مدير أ
tenant_db.set_active_tenant("factory-B-2222")
with db(readonly=True) as c:
    check("رمز دخول رابط أ ورمز مديره لا يظهران في ب",
          not mw._get(c, mw.K_PIN).strip() and not mweb.has_desk_pin(c))
code, h = get([], B["tok"], {"tab": "guide"})
check("ورابط ب يُفتح بلا رمز (لم يضبط له مديره رمزاً)", code == 200 and "MB1" in h)
tenant_db.set_active_tenant("factory-A-1111")
code, h = get([], A["tok"], {"tab": "guide"})
check("ورابط أ يطلب رمزه", "MA1" not in h and 'name="pin"' in h)
with db(readonly=True) as c:
    ph = mw._get(c, mw.K_PIN).strip()
code, h = get([], A["tok"], {"tab": "guide"}, pin=ph, secret=A["secret"])
check("وبرمزه يُفتح على بياناته", code == 200 and "MA1" in h)

print(f"\n{len(OK)} ✔ · {len(BAD)} ✘")
os._exit(1 if BAD else 0)
