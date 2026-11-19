"""5.10: البحث بالصورة في دليل الموديلات (رابط المدير) — جانب جهاز المصنع.

    python3 tools/check_vision.py

* زرّ «📷 بحث بالصورة» في لوحة الدليل، وصفحة `/vis` بموديلات الدليل
  (صورها وإصداراتها، وما بالخزنة وما عند المناديب وتفاصيلهم).
* الصفحة معزولة (COOP/COEP) وسياستها تسمح بـWebAssembly وحده — لا eval.
* حزمة الأدوات: تُقدَّم ملفاتها المسموحة وحدها، مضغوطةً لمن يقبل، وتُفكّ
  بعد مطابقة البصمة فقط، ولا تُقبل فيها مساراتٌ أو ملفاتٌ غريبة.
* الفهرس: يُحفظ برمز تحقّق الصفحة وحده، ولا يقبل بصمةً تالفة ولا صورةً
  غير موجودة أو بإصدارٍ قديم — ويُقرأ كما حُفظ.
* كله خلف دخول الرابط، ويُقفل مع لوحة «الدليل» إن قفلها المدير.
* الخادم يرسل الملف الكبير قطعاً من القرص (لا في الذاكرة).
"""
import base64
import datetime
import gzip
import hashlib
import io
import json
import os
import pathlib
import struct
import sys
import tempfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
T = tempfile.mkdtemp(prefix="vision_")
os.environ["GOLD_ERP_DATA_DIR"] = T
import config  # noqa: E402

config.DB_PATH = pathlib.Path(T) / "t.db"
import main  # noqa: E402

for _l, f in main.prepare_steps():
    f()
from database.database import db  # noqa: E402
from models import inventory, invoices, models_catalog as mc  # noqa: E402
from models.entities import add_entity  # noqa: E402
from services import manager_web as mweb  # noqa: E402
from services import models_web as mw  # noqa: E402
from services import vision_search as vs  # noqa: E402

OK, BAD = [], []


def check(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print(("  ✔ " if cond else "  ✘ ") + name + ("" if cond else f"  [{info}]"))


# ── حزمةٌ صغيرة للتجربة (بلا تنزيل) ──
PK = pathlib.Path(T) / "pack"
PK.mkdir()
MAN = {"id": "test-model-1", "input": 224, "pool": "cls+mean", "skip": 1,
       "mean": [0.5] * 3, "std": [0.5] * 3}
(PK / "manifest.json").write_text(json.dumps(MAN), encoding="utf-8")
(PK / "model.onnx").write_bytes(os.urandom(3 * 1024 * 1024 + 17))
for f in vs.GZ_OK:
    (PK / f).write_bytes(b"x" * 5000)
    (PK / (f + ".gz")).write_bytes(gzip.compress(b"x" * 5000))
(PK / "LICENSES.txt").write_text("MIT", encoding="utf-8")
os.environ[vs.ENV_DIR] = str(PK)

D0 = datetime.date.today().isoformat()
with db() as c:
    A = add_entity(c, "مندوب الصور", "customer", username="t")
    inventory.create_work_orders_batch(c, [
        {"wo_no": f"{900 + i}", "model_no": ("V1", "V2", "V3")[i % 3],
         "gold": 10 + i, "small_stones": .2, "big_stones": .1,
         "wage_per_gram": 10} for i in range(6)], D0, "t")
    W = {r[1]: r[0] for r in c.execute("SELECT id, work_order_no FROM work_orders")}
    invoices.create_sale(c, A, [{"work_order_id": W["900"]}], D0, "t",
                         apply_vat=False)
    TOK = mw.ensure_token(c)
    mw.set_enabled(c, True)
    SECRET = mw._get(c, mw.K_SECRET)
from PyQt5 import QtGui  # noqa: E402


def png(path, w, h, rgb):
    im = QtGui.QImage(w, h, QtGui.QImage.Format_RGB32)
    im.fill(QtGui.QColor(*rgb))
    assert im.save(str(path), "PNG")


for i, m in enumerate(("V1", "V2")):                     # V3 بلا صورة
    png(mc.images_dir() / f"{m}.png", 300, 200, (250, 240 - 40 * i, 200))
CSRF = mw._csrf(TOK, SECRET)
BASE = f"/m/{TOK}"


def call(method, path, query=None, body=None, headers=None, cookie=True):
    with db(readonly=True) as c:
        pin = mw._get(c, mw.K_PIN).strip()
    h = dict(headers or {})
    if cookie and pin:
        h["Cookie"] = f"{mw.COOKIE}={mw._cookie_value(TOK, SECRET, pin)}"
    parts = [TOK] + [p for p in path.split("/") if p]
    raw = (json.dumps(body, ensure_ascii=False).encode("utf-8")
           if isinstance(body, (dict, list)) else body)
    return mw.handle(method, parts, query or {}, h, raw)


def text(r):
    b = r.get("body") or b""
    return b.decode("utf-8", "replace") if isinstance(b, bytes) else b


def vec(dim, seed=1):
    import random
    rnd = random.Random(seed)
    q = bytes((rnd.randrange(256) for _ in range(dim)))
    return base64.b64encode(struct.pack("<f", 0.01) + q).decode()


print("── 1) زرّ الدليل وصفحة البحث بالصورة")
r = call("GET", "", {"tab": "guide"})
check("لوحة الدليل فيها «📷 بحث بالصورة» إلى /vis",
      "📷 بحث بالصورة" in text(r) and f'{BASE}/vis"' in text(r))
r2 = call("GET", "", {"tab": "received"})
check("ولا يظهر في لوحة «الوارد»", "📷 بحث بالصورة" not in text(r2))
r = call("GET", "vis")
page = text(r)
check("صفحة /vis تُفتح", r["code"] == 200 and "تصوير الطقم" in page, r["code"])
blob = json.loads(page.split('<script id="vis-data" type="application/json">')[1]
                  .split("</script>")[0])
cat = {c["m"]: c for c in blob["catalog"]}
check("بيانات الصفحة: الموديلات ذوات الصور وحدها (V1 · V2)",
      sorted(cat) == ["V1", "V2"], sorted(cat))
check("ولكلٍّ صورته وإصدارها", cat["V1"]["img"].startswith(f"{BASE}/img/V1?v=")
      and cat["V1"]["v"])
check("وما بالخزنة وما عند المناديب (V1: 1 مباع لمندوب الصور · 1 بالخزنة)",
      cat["V1"]["out"] == 1 and cat["V1"]["in"] == 1
      and cat["V1"]["sold"][0][2] == "مندوب الصور"
      and cat["V1"]["sold"][0][0] == "900", cat["V1"])
check("ورمز التحقّق في الصفحة", blob["csrf"] == CSRF)
hd = r["headers"]
check("الصفحة معزولة (COOP/COEP) لتعمل كل الأنوية",
      hd.get("Cross-Origin-Opener-Policy") == "same-origin"
      and hd.get("Cross-Origin-Embedder-Policy") == "require-corp")
csp = hd.get("Content-Security-Policy", "")
check("وسياستها: WebAssembly وحده بلا eval ولا مصادر خارجية",
      "'wasm-unsafe-eval'" in csp and "'unsafe-eval'" not in csp
      and "default-src 'none'" in csp and "http" not in csp, csp)
check("وسكربت الصفحة من الجهاز نفسه", f'{BASE}/vis/app.js?v=' in page)
r = call("GET", "vis/app.js", {"v": "1"})
check("app.js يُقدَّم ويُحفظ طويلاً", r["code"] == 200
      and b"__vis" in r["body"] and "immutable" in r["headers"]["Cache-Control"])
check("وصفحة لا تقبل JSON مكسوراً: «</» مهرَّب داخل البيانات",
      "</script>" not in page.split('type="application/json">')[1].split("</script>")[0])

print("── 2) الحزمة: الحال وملفاتها")
r = call("GET", "vis/status")
st = json.loads(text(r))
check("الحال: جاهزة، ومعها إعداد النموذج", st["state"] == "ready"
      and st["manifest"]["id"] == "test-model-1", st)
r = call("GET", "vis/pack/model.onnx")
check("النموذج يُرسل من القرص قطعاً (لا في الذاكرة) ويُحفظ طويلاً",
      r.get("file") == str(PK / "model.onnx")
      and "immutable" in r["headers"]["Cache-Control"], r.get("file"))
r = call("GET", "vis/pack/ort-wasm-simd-threaded.wasm",
         headers={"Accept-Encoding": "gzip, br"})
check("المحرّك مضغوطاً لمن يقبل الضغط", r.get("file", "").endswith(".wasm.gz")
      and r["headers"].get("Content-Encoding") == "gzip"
      and r["ctype"] == "application/wasm")
r = call("GET", "vis/pack/ort-wasm-simd-threaded.wasm")
check("وغير مضغوط لمن لا يقبل", r.get("file", "").endswith(".wasm")
      and "Content-Encoding" not in r["headers"])
for bad in ("..%2F..%2Ft.db", "t.db", "manifest.json.gz", "x.onnx"):
    r = call("GET", f"vis/pack/{bad}")
    if r["code"] != 404:
        break
check("ولا ملفٌّ خارج القائمة (مسارات · قاعدة البيانات)", r["code"] == 404)

print("── 3) الفهرس: الحفظ والتحقّق")
V = mw._img_versions()
k1, k2 = mw._vkey("V1"), mw._vkey("V2")
good = {k1: {"v": V[k1], "e": [vec(32, 1), vec(32, 2)], "k": ["f", "p"]}}
r = call("POST", "vis/index", body={"model": "test-model-1", "dim": 32,
                                    "items": good})
check("بلا رمز التحقّق: مرفوض", r["code"] == 403, r["code"])
r = call("POST", "vis/index", body={"model": "test-model-1", "dim": 32,
                                    "items": good},
         headers={"X-Csrf": "wrong"})
check("برمزٍ خاطئ: مرفوض", r["code"] == 403)
r = call("POST", "vis/index", body={"model": "test-model-1", "dim": 32,
                                    "items": good},
         headers={"X-Csrf": CSRF})
check("برمز الصفحة: حُفظ", r["code"] == 200 and json.loads(text(r))["ok"] == 1,
      text(r))
bad_items = {
    k2: {"v": "قديم", "e": [vec(32)]},                       # إصدارٌ قديم
    "لا-يوجد": {"v": "1", "e": [vec(32)]},                    # صورةٌ غير موجودة
}
r = call("POST", "vis/index", body={"model": "test-model-1", "dim": 32,
                                    "items": bad_items}, headers={"X-Csrf": CSRF})
check("صورةٌ غير موجودة أو بإصدارٍ قديم: لا تُقبل", json.loads(text(r))["ok"] == 0)
r = call("POST", "vis/index", body={"model": "test-model-1", "dim": 32, "items": {
    k2: {"v": V[k2], "e": [base64.b64encode(b"short").decode()]}}},
    headers={"X-Csrf": CSRF})
check("بصمةٌ تالفة (طولٌ خاطئ): لا تُقبل", json.loads(text(r))["ok"] == 0)
r = call("POST", "vis/index", body={"model": "test-model-1", "dim": 32, "items": {
    k2: {"v": V[k2], "e": [vec(32)] * 17}}}, headers={"X-Csrf": CSRF})
check("أكثر من 16 بصمة للموديل: لا تُقبل", json.loads(text(r))["ok"] == 0)
r = call("POST", "vis/index", body={"model": "نموذج-آخر", "dim": 32,
                                    "items": good}, headers={"X-Csrf": CSRF})
check("بصماتٌ من نموذجٍ آخر: مرفوضة", r["code"] == 400)
r = call("POST", "vis/index", body=b"{not json", headers={"X-Csrf": CSRF})
check("جسمٌ ليس JSON: مرفوض بلا عطل", r["code"] == 400)
idx = json.loads(text(call("GET", "vis/index")))
check("يُقرأ الفهرس كما حُفظ", idx["model"] == "test-model-1"
      and idx["dim"] == 32 and list(idx["items"]) == [k1]
      and idx["items"][k1]["e"] == good[k1]["e"]
      and idx["items"][k1]["k"] == ["f", "p"], idx)
# صورةٌ تُستبدل: إصدارها يتغيّر فلا تُطابَق بصمتها القديمة في الصفحة
import time as _t  # noqa: E402
_t.sleep(1.1)
png(mc.images_dir() / "V1.png", 310, 200, (10, 10, 10))
with db(readonly=True) as c:
    cat2 = {x["m"]: x for x in vs.catalog(c, BASE)}
check("صورةٌ استُبدلت: إصدارٌ جديد فيُعاد حساب بصمتها",
      cat2["V1"]["v"] != idx["items"][k1]["v"])
(mc.images_dir() / "V2.png").unlink()
r = call("POST", "vis/index", body={"model": "test-model-1", "dim": 32, "items": {}},
         headers={"X-Csrf": CSRF})
idx = json.loads(text(call("GET", "vis/index")))
check("وصورةٌ حُذفت من الدليل: تسقط بصمتها", k2 not in idx["items"])

print("── 4) الدخول والقفل")
with db() as c:
    mw.set_pin(c, "4321", "t")
r = call("GET", "vis", cookie=False)
check("برمز دخولٍ للرابط: /vis بلا دخول ⇒ صفحة الدخول", r["code"] == 200
      and "تصوير الطقم" not in text(r) and "pin" in text(r))
r = call("GET", "vis/index", cookie=False)
check("والفهرس بلا دخول لا يُقرأ (صفحة الدخول بدله)",
      '"model"' not in text(r) and "pin" in text(r))
r = call("GET", "vis")
check("وبالدخول تُفتح", "تصوير الطقم" in text(r))
with db() as c:
    mweb.set_ops_pin(c, "7777", "t")
    mweb._set(c, mweb.K_LOCKED, json.dumps(["guide"]), "t")
r = call("GET", "vis")
check("لوحة «الدليل» مقفلة برمز اللوحات ⇒ /vis تطلب الرمز",
      "تصوير الطقم" not in text(r) and r["code"] == 200)
r = call("GET", "vis/index")
check("والفهرس والحزمة كذلك (403)", r["code"] == 403
      and call("GET", "vis/pack/model.onnx")["code"] == 403)
with db() as c:
    mweb._set(c, mweb.K_LOCKED, json.dumps(["ops"]), "t")
check("وتُفتح إن رُفع القفل عن الدليل", "تصوير الطقم" in text(call("GET", "vis")))

print("── 5) تثبيت الحزمة: البصمة والمحتوى")
os.environ.pop(vs.ENV_DIR)


def mkzip(names, extra=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(n, (PK / n).read_bytes() if (PK / n).exists() else b"x")
        for n, b in (extra or {}).items():
            z.writestr(n, b)
    p = pathlib.Path(T) / f"p{len(names)}{len(extra or {})}.zip"
    p.write_bytes(buf.getvalue())
    return p


full = list(vs.PACK_FILES) + [f + ".gz" for f in vs.GZ_OK]
for bad, why in ((mkzip(full, {"../evil.txt": b"x"}), "مسار خارج المجلد"),
                 (mkzip(full, {"run.exe": b"x"}), "ملف غريب"),
                 (mkzip([n for n in full if n != "model.onnx"]), "ناقصة")):
    try:
        vs.install_zip(bad, "abc")
        ok = False
    except ValueError:
        ok = True
    check(f"حزمةٌ مرفوضة: {why}", ok and not (vs._root() / "evil.txt").exists())
p = mkzip(full)
sha = hashlib.sha256(p.read_bytes()).hexdigest()
vs.PACK_SHA = sha
vs.install_zip(p, sha)
check("حزمةٌ سليمة: تُفكّ وتُعتمد", vs.pack_ready()
      and (vs.pack_dir() / "model.onnx").stat().st_size == (PK / "model.onnx").stat().st_size)
vs.PACK_SHA = "0" * 64
check("وبصمةٌ مختلفة في البرنامج ⇒ لا تُعتمد (تُنزَّل من جديد)", not vs.pack_ready())


class _Resp(io.BytesIO):
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


import urllib.request  # noqa: E402
_orig = urllib.request.urlopen
urllib.request.urlopen = lambda req, timeout=0: _Resp(p.read_bytes())
try:
    vs.download("https://example.invalid/p.zip", "f" * 64, p.stat().st_size)
    ok = False
except ValueError as e:
    ok = "لا تطابق" in str(e)
check("تنزيلٌ لا تطابق بصمته: يُرفض ويُحذف", ok
      and not (vs._root() / (vs.PACK_FILE + ".part")).exists())
try:
    vs.download("http://example.invalid/p.zip", sha, 1)
    ok = False
except ValueError:
    ok = True
check("ورابطٌ غير مشفّر: مرفوض قبل الاتصال", ok)
vs.download("https://example.invalid/p.zip", sha, p.stat().st_size)
vs.PACK_SHA = sha
check("وتنزيلٌ بالبصمة الصحيحة: يُعتمد", vs.pack_ready())
urllib.request.urlopen = _orig

print("── 6) الخادم يرسل الملف الكبير قطعاً")
from services import photo_server  # noqa: E402
big = pathlib.Path(T) / "big.bin"
big.write_bytes(os.urandom(2_500_000))
photo_server._routes["vt"] = lambda m, parts, q, h, b: {
    "code": 200, "file": str(big), "ctype": "application/octet-stream",
    "headers": {"Cache-Control": "private, max-age=60"}}
url = photo_server.ensure_running() if hasattr(photo_server, "ensure_running") else None
if not url:
    import threading
    srv = photo_server._bind(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
else:
    port = photo_server.current()[1]
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with op.open(f"http://127.0.0.1:{port}/vt/x", timeout=20) as resp:
    data = resp.read()
    cl = resp.headers.get("Content-Length")
check("ملفٌّ 2.5 م.ب يصل كاملاً مطابقاً", data == big.read_bytes()
      and cl == str(big.stat().st_size), (len(data), cl))

print("── 7) لا تجمّد أثناء تنزيل الحزمة (5.10.1)")
import threading as _th  # noqa: E402


class _Slow(io.BytesIO):
    headers = {"Content-Length": "600000"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        _t.sleep(0.15)
        return super().read(min(n, 50000))


vs.PACK_SHA = "e" * 64
vs._dl.update(state="", thread=None, at=0)
import shutil as _sh  # noqa: E402
_sh.rmtree(vs._root() / vs.PACK_TAG, ignore_errors=True)
urllib.request.urlopen = lambda req, timeout=0: _Slow(b"x" * 600000)
_res = []


def _poll():
    for _ in range(6):
        _res.append(vs.ensure_async()["state"])
        vs.status()
        _t.sleep(0.2)


_w = _th.Thread(target=_poll, daemon=True)
_w.start()
_w.join(8)
check("الصفحة تسأل والحزمة تُنزَّل: كل طلبٍ يعود فوراً (لا تجمّد)",
      not _w.is_alive() and _res and set(_res) == {"downloading"}, _res)
r = call("GET", "vis")
check("وصفحة /vis تُفتح أثناء التنزيل", r["code"] == 200 and "تصوير الطقم" in text(r))
urllib.request.urlopen = _orig

print(f"\n{len(OK)} ✔ · {len(BAD)} ✘")
os._exit(1 if BAD else 0)
