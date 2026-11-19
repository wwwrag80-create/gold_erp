# -*- coding: utf-8 -*-
"""البحث بالصورة في دليل الموديلات (5.10) — من «رابط المدير».

يصوّر المدير بجواله طقماً حقيقياً أمامه (أو قطعةً منه)، فيعرض له الرابط
أقرب موديلات الدليل إليه — مع ما بالخزنة منه وما عند المناديب وتفاصيلهم.

**كيف يقارن صورةً واقعية بصورٍ ثلاثية الأبعاد؟** بنموذج رؤيةٍ مدرَّب
(`manifest.json` في حزمة الأدوات) يحوّل كل صورة إلى «بصمة» رقمية تصف
شكلها: الزخارف وتوزيعها وهيئة القلادة والحلق — لا ألوان البكسلات. والبصمات
المتقاربة صورٌ لتصميمٍ واحد ولو اختلفت الإضاءة والخلفية والزاوية. ولكل
موديلٍ عدّة بصمات: الطقم كاملاً، وكلُّ قطعةٍ فيه وحدها، ونوافذ منه — فتُطابَق
صورةُ قطعةٍ واحدة كما تُطابَق صورةُ الطقم.

**أين يعمل؟** في متصفّح الجوال نفسه (ONNX Runtime Web): الصورة لا تغادر
الجوال، ولا يُرفع شيءٌ لأي خدمة. جهاز المصنع يقدّم:
  * **حزمة الأدوات** (النموذج ومحرّكه) — تُنزَّل مرةً واحدة من إصدار
    المشروع على GitHub، وتُطابَق بصمتها (SHA-256) قبل استعمالها؛
  * **فهرس الدليل** — بصمات صور الموديلات. يحسبها أول متصفّحٍ يفتح الصفحة
    ويحفظها هنا، فلا تُحسب ثانيةً إلا لصورةٍ تغيّرت.

**الحماية**: كل مسارات `/vis` خلف دخول الرابط نفسه، وتُقفل مع لوحة «الدليل»
إن قفلها المدير؛ والكتابة الوحيدة (حفظ الفهرس) برمز تحقّق الصفحة (CSRF)
وبتحقّقٍ صارم من كل بصمة — ولا تمسّ قاعدة البيانات.
"""
import base64
import hashlib
import hmac
import html
import json
import os
import re
import threading
import time
import zipfile
from pathlib import Path

# ── حزمة الأدوات (تُنشر في إصدار GitHub بالاسم نفسه) ──
PACK_TAG = "vision-pack-1"
PACK_FILE = "vision-pack-1.zip"
PACK_SHA = ""
PACK_SIZE = 0
PACK_URL = ("https://github.com/wwwrag80-create/gold_erp/releases/download/"
            f"{PACK_TAG}/{PACK_FILE}")
# تجاوزٌ للتجربة: مجلّد حزمةٍ جاهز (بلا تنزيل)
ENV_DIR = "JADEITE_VISION_PACK_DIR"
# ما يُقبل من الحزمة — أسماءٌ مسطّحة لا مسارات
PACK_FILES = ("manifest.json", "model.onnx", "ort.wasm.min.js",
              "ort-wasm-simd-threaded.wasm", "ort-wasm-simd-threaded.mjs",
              "LICENSES.txt")
GZ_OK = ("ort.wasm.min.js", "ort-wasm-simd-threaded.wasm",
         "ort-wasm-simd-threaded.mjs")
CTYPES = {".js": "text/javascript; charset=utf-8",
          ".mjs": "text/javascript; charset=utf-8",
          ".wasm": "application/wasm", ".onnx": "application/octet-stream",
          ".json": "application/json", ".txt": "text/plain; charset=utf-8"}

MAX_VIEWS = 12          # بصمات الموديل الواحد (الطقم · القطع · النوافذ)
MAX_DIM = 2048

_lock = threading.Lock()
_dl = {"state": "", "done": 0, "total": 0, "error": "", "thread": None}


# ══════════════════════════════════════════════════════════════════
#  حزمة الأدوات
# ══════════════════════════════════════════════════════════════════

def _root():
    import config
    d = Path(str(config.DB_PATH)).parent / "vision"
    d.mkdir(parents=True, exist_ok=True)
    return d


def pack_dir():
    over = (os.environ.get(ENV_DIR) or "").strip()
    if over:
        return Path(over)
    return _root() / PACK_TAG


def pack_ready():
    d = pack_dir()
    if (os.environ.get(ENV_DIR) or "").strip():
        return (d / "manifest.json").is_file() and (d / "model.onnx").is_file()
    ok = d / ".ok"
    try:
        return ok.read_text(encoding="utf-8").strip() == PACK_SHA and \
            all((d / f).is_file() for f in PACK_FILES)
    except OSError:
        return False


def manifest():
    try:
        return json.loads((pack_dir() / "manifest.json").read_text(
            encoding="utf-8"))
    except Exception:
        return {}


def status():
    """حال الحزمة للصفحة: ready · downloading · error · missing."""
    if pack_ready():
        return {"state": "ready"}
    with _lock:
        if _dl["state"] in ("downloading", "error"):
            return {"state": _dl["state"], "done": _dl["done"],
                    "total": _dl["total"] or PACK_SIZE,
                    "error": _dl["error"]}
    return {"state": "missing", "total": PACK_SIZE}


def ensure_async():
    """يبدأ تنزيل الحزمة في الخلفية إن لم تكن جاهزة ولا جارية."""
    if pack_ready() or not PACK_SHA:
        return status()
    with _lock:
        t = _dl.get("thread")
        if t is not None and t.is_alive():
            return status()
        _dl.update(state="downloading", done=0, total=PACK_SIZE, error="")
        t = threading.Thread(target=_download_safe, name="vision-pack",
                             daemon=True)
        _dl["thread"] = t
        t.start()
    return status()


def _download_safe():
    try:
        download()
        with _lock:
            _dl.update(state="", error="")
    except Exception as e:                       # noqa: BLE001
        with _lock:
            _dl.update(state="error", error=_why(e))
        try:
            from services.health import log_error
            log_error("vision_search/download", e)
        except Exception:
            pass


def _why(e):
    s = f"{type(e).__name__}: {e}"
    if "CERTIFICATE" in s.upper() or "SSL" in s.upper():
        return "تعذّر الاتصال الآمن بالإنترنت (شهادة/وكيل) — " + s[:160]
    if "timed out" in s or "Timeout" in s:
        return "انقطع الاتصال أو بطُؤ — يُعاد المحاولة لاحقاً"
    return s[:200]


def download(url=None, sha=None, size=None, progress=None):
    """ينزّل الحزمة ويطابق بصمتها ثم يفكّها — أو يرفع خطأً واضحاً.

    لا تُعتمد إلا بعد تطابق SHA-256 كاملاً؛ والملف التالف يُحذف. والأسماء
    في الملف المضغوط تُقبل من قائمةٍ ثابتة وحدها (لا مسارات)."""
    import urllib.request
    url = url or PACK_URL
    sha = (sha or PACK_SHA).lower()
    size = int(size or PACK_SIZE or 0)
    if not url.lower().startswith("https://"):
        raise ValueError("رابط الحزمة غير مشفّر")
    if not sha:
        raise ValueError("بصمة الحزمة غير معروفة")
    root = _root()
    part = root / (PACK_FILE + ".part")
    cap = int(size * 1.05) + (1 << 20) if size else 400 << 20
    h = hashlib.sha256()
    got = 0
    req = urllib.request.Request(url, headers={"User-Agent": "Jadeite-Vision"})
    with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as fh:
        total = int(r.headers.get("Content-Length") or size or 0)
        with _lock:
            _dl["total"] = total
        while True:
            b = r.read(1 << 18)
            if not b:
                break
            got += len(b)
            if got > cap:
                raise ValueError("حجم الحزمة أكبر من المتوقّع")
            h.update(b)
            fh.write(b)
            with _lock:
                _dl["done"] = got
            if progress:
                progress(got, total)
    if h.hexdigest() != sha:
        part.unlink(missing_ok=True)
        raise ValueError("بصمة الحزمة لا تطابق — رُفضت")
    install_zip(part, sha)
    part.unlink(missing_ok=True)
    return pack_dir()


def install_zip(zpath, sha):
    """يفكّ الحزمة (بعد مطابقة بصمتها) إلى مجلّدها — كلّها أو لا شيء."""
    dst = _root() / PACK_TAG
    tmp = _root() / (PACK_TAG + ".tmp")
    if tmp.exists():
        _rmtree(tmp)
    tmp.mkdir(parents=True)
    allowed = set(PACK_FILES) | {f + ".gz" for f in GZ_OK}
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        for n in names:
            if n not in allowed:
                raise ValueError(f"ملفٌّ غير متوقّع في الحزمة: {n[:60]}")
        for n in names:
            with z.open(n) as src, open(tmp / n, "wb") as out:
                while True:
                    b = src.read(1 << 20)
                    if not b:
                        break
                    out.write(b)
    for f in PACK_FILES:
        if not (tmp / f).is_file():
            raise ValueError(f"الحزمة ناقصة: {f}")
    (tmp / ".ok").write_text(sha, encoding="utf-8")
    if dst.exists():
        _rmtree(dst)
    tmp.replace(dst)
    return dst


def _rmtree(p):
    import shutil
    shutil.rmtree(p, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════
#  فهرس الدليل (بصمات صور الموديلات)
# ══════════════════════════════════════════════════════════════════

def model_id():
    return str(manifest().get("id") or "")


def _index_path(mid):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", mid)[:60] or "x"
    return _root() / f"index-{safe}.json"


def load_index(mid=None):
    mid = mid or model_id()
    if not mid:
        return {"model": "", "dim": 0, "items": {}}
    try:
        d = json.loads(_index_path(mid).read_text(encoding="utf-8"))
        if d.get("model") == mid and isinstance(d.get("items"), dict):
            return d
    except Exception:
        pass
    return {"model": mid, "dim": 0, "items": {}}


def _check_vec(s, dim):
    """بصمةٌ واحدة: base64 لـ[مقياس float32 · dim × int8]."""
    if not isinstance(s, str) or len(s) > 8 + (4 + dim) * 4 // 3 + 4:
        return False
    try:
        raw = base64.b64decode(s, validate=True)
    except Exception:
        return False
    if len(raw) != 4 + dim:
        return False
    import struct
    sc = struct.unpack("<f", raw[:4])[0]
    return sc == sc and 0 < sc < 1e3


def merge_index(items, mid, dim, versions=None):
    """يضيف بصمات موديلات (من المتصفّح) إلى الفهرس بعد تحقّقٍ صارم.

    `items`: {مفتاح الصورة: {"v": إصدارها, "e": [بصمات], "k": [أنواعها]}}
    يُقبل المفتاح إن كانت صورته موجودةً بالإصدار نفسه الآن — فلا تُحفظ
    بصمةُ صورةٍ قديمة أو مختلَقة. ويعيد عدد ما قُبل."""
    if not mid or mid != model_id():
        raise ValueError("نموذج غير مطابق")
    dim = int(dim)
    if not 16 <= dim <= MAX_DIM:
        raise ValueError("بُعد غير صالح")
    if versions is None:
        from services.models_web import _img_versions
        versions = _img_versions()
    ok = 0
    with _lock:
        idx = load_index(mid)
        if idx.get("dim") and int(idx["dim"]) != dim:
            idx = {"model": mid, "dim": dim, "items": {}}
        idx["dim"] = dim
        for key, it in (items or {}).items():
            if not isinstance(it, dict) or not isinstance(key, str):
                continue
            ver = versions.get(key)
            if not ver or it.get("v") != ver:
                continue
            vecs = it.get("e")
            kinds = it.get("k") or []
            if not isinstance(vecs, list) or not 1 <= len(vecs) <= MAX_VIEWS:
                continue
            if not all(_check_vec(v, dim) for v in vecs):
                continue
            kinds = [str(k)[:8] for k in kinds][:len(vecs)] \
                if isinstance(kinds, list) else []
            idx["items"][key] = {"v": ver, "e": vecs, "k": kinds}
            ok += 1
        # ما زالت صورته من الدليل يُحذف
        for key in [k for k in idx["items"] if k not in versions]:
            idx["items"].pop(key, None)
        p = _index_path(mid)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(idx, separators=(",", ":")),
                       encoding="utf-8")
        tmp.replace(p)
    return ok


# ══════════════════════════════════════════════════════════════════
#  بيانات الصفحة: الموديلات بصورها وأماكنها
# ══════════════════════════════════════════════════════════════════

def catalog(conn, base):
    """كل موديلٍ له صورة: رابطها وإصدارها، وما بالخزنة وما عند المناديب."""
    from models import models_catalog as mc
    from services import models_web as mw
    imgs = mw._img_versions()
    full = mc.full_catalog(conn)
    out = []
    for m in mc.list_models(conn):
        name = m["model"]
        key = mw._vkey(name)
        ver = imgs.get(key)
        if not ver:
            continue
        g = full.get(name, {"sold": [], "in_stock": []})
        out.append({
            "m": str(name), "k": key, "v": ver,
            "img": mw._img_url(base, name, ver),
            "full": mw._img_url(base, name, ver, True),
            "in": m["in_count"], "inw": mw._w(m["in_weight"]),
            "out": m["out_count"], "outw": mw._w(m["out_weight"]),
            "sold": [[str(i["wo"]), mw._w(i["reg"]), str(i["holder"]),
                      str(i["date"])] for i in g["sold"]],
            "stock": [[str(i["wo"]), mw._w(i["reg"]), str(i["date"])]
                      for i in g["in_stock"]],
        })
    return out


# ══════════════════════════════════════════════════════════════════
#  المسارات: /m/<رمز>/vis/…
# ══════════════════════════════════════════════════════════════════

# الصفحة معزولةٌ عن غيرها (COOP/COEP) ليعمل المحرّك بكل أنوية المعالج،
# ولا يُحمَّل فيها شيءٌ من خارج جهاز المصنع. و'wasm-unsafe-eval' لتشغيل
# WebAssembly وحده (لا eval لنصوص).
CSP = ("default-src 'none'; img-src 'self' blob: data:;"
       " style-src 'unsafe-inline';"
       " script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval';"
       " connect-src 'self'; worker-src 'self' blob:; manifest-src 'self';"
       " form-action 'self'; base-uri 'none'")
ISO = {"Cross-Origin-Opener-Policy": "same-origin",
       "Cross-Origin-Embedder-Policy": "require-corp",
       "Cross-Origin-Resource-Policy": "same-origin"}


def _resp(code, body, ctype="text/html; charset=utf-8", headers=None):
    from services import models_web as mw
    h = dict(ISO)
    h["Content-Security-Policy"] = CSP
    h.update(headers or {})
    r = mw._resp(code, body, ctype, h)
    r["headers"]["Content-Security-Policy"] = CSP
    return r


def _json(obj, code=200):
    return _resp(code, json.dumps(obj, ensure_ascii=False,
                                  separators=(",", ":")),
                 "application/json; charset=utf-8",
                 {"Cache-Control": "no-store"})


def _app_js():
    import config
    p = Path(config.BUNDLE_DIR) / "assets" / "vision" / "vis.js"
    if not p.is_file():
        p = Path(__file__).resolve().parent.parent / "assets" / "vision" \
            / "vis.js"
    return p


def route(method, rest, query, headers, body, base, csrf):
    """معالج `/vis…` (بعد دخول الرابط)."""
    from database.database import db
    from services import manager_web
    with db(readonly=True) as conn:
        gate_ok = manager_web.panel_open(conn, "guide", headers, csrf)
        if not gate_ok:
            if not rest and method == "GET":
                return manager_web.tab_gate(conn, "guide", headers, csrf,
                                            base)
            return _json({"error": "locked"}, 403)
    if not rest:
        if method != "GET":
            return _json({"error": "method"}, 405)
        ensure_async()
        with db(readonly=True) as conn:
            page = page_html(conn, base, csrf)
        return manager_web.sec_exit(_resp(200, page), method, ["vis"],
                                    headers, base)
    head = rest[0]
    if head == "status" and method == "GET":
        st = ensure_async()
        if st["state"] == "ready":
            st["manifest"] = manifest()
        return _json(st)
    if head == "app.js" and method == "GET":
        p = _app_js()
        try:
            data = p.read_bytes()
        except OSError:
            return _json({"error": "missing"}, 404)
        return _resp(200, data, CTYPES[".js"],
                     {"Cache-Control": "private, max-age=31536000, immutable"
                      if query.get("v") else "no-cache"})
    if head == "pack" and len(rest) == 2 and method == "GET":
        return _pack_file(rest[1], headers)
    if head == "index":
        if method == "GET":
            return _json(load_index())
        if method == "POST":
            got = (headers.get("X-Csrf") or "") if headers is not None else ""
            if not hmac.compare_digest(str(got), str(csrf)):
                return _json({"error": "csrf"}, 403)
            try:
                d = json.loads((body or b"").decode("utf-8"))
                n = merge_index(d.get("items"), str(d.get("model") or ""),
                                int(d.get("dim") or 0))
            except Exception as e:               # noqa: BLE001
                return _json({"error": str(e)[:120]}, 400)
            return _json({"ok": n})
    return _json({"error": "not found"}, 404)


def _pack_file(name, headers):
    if name not in PACK_FILES or not pack_ready():
        return _json({"error": "not ready"}, 404)
    d = pack_dir()
    p = d / name
    ext = os.path.splitext(name)[1]
    h = dict(ISO)
    h["Cache-Control"] = "private, max-age=31536000, immutable"
    h["Content-Security-Policy"] = CSP
    h["X-Content-Type-Options"] = "nosniff"
    acc = (headers.get("Accept-Encoding") or "") if headers is not None else ""
    gz = d / (name + ".gz")
    if name in GZ_OK and "gzip" in acc and gz.is_file():
        h["Content-Encoding"] = "gzip"
        h["Vary"] = "Accept-Encoding"
        p = gz
    return {"code": 200, "file": str(p), "ctype": CTYPES.get(ext,
            "application/octet-stream"), "headers": h, "body": b""}


# ══════════════════════════════════════════════════════════════════
#  الصفحة
# ══════════════════════════════════════════════════════════════════

def _e(v):
    return html.escape(str(v if v is not None else ""), quote=True)


def _app_ver():
    try:
        st = _app_js().stat()
        return f"{int(st.st_mtime):x}{st.st_size:x}"
    except OSError:
        return "0"


def page_html(conn, base, csrf):
    from services import karat_view as kv
    from services import models_web as mw
    cat = catalog(conn, base)
    data = {"base": base, "csrf": csrf, "pack": PACK_TAG,
            "unit": kv.unit(), "catalog": cat}
    # JSON داخل <script type=application/json>: يُهرَّب «</» فلا يُغلق الوسم
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")) \
        .replace("</", "<\\/")
    co = mw._company().strip()
    title = "البحث بالصورة" + (f" — {_e(co)}" if co else "")
    return f"""<!DOCTYPE html>
<html dir="rtl" lang="ar"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex,nofollow">
<title>{title}</title><style>{_CSS}</style></head><body>
<header><a class="back" href="{_e(base)}/?tab=guide">→ الدليل</a>
<h1>📷 البحث بالصورة</h1><span></span></header>
<main>
<section id="intro" class="card">
 <p class="lead">صوِّر الطقم أو القطعة التي أمامك، فيعرض لك النظام أقرب
 موديلات الدليل إليها — مع ما بالخزنة وما عند المناديب.</p>
 <div class="btns">
  <label class="big"><input id="cam" type="file" accept="image/*"
   capture="environment" hidden>📷 تصوير الطقم</label>
  <label class="alt"><input id="gal" type="file" accept="image/*"
   hidden>🖼 صورة من الجوال</label>
 </div>
 <ul class="tips">
  <li>صوِّر من الأمام، والقطعة تملأ أغلب الصورة.</li>
  <li>خلفيةٌ سادة وإضاءةٌ جيدة بلا لمعانٍ قوي — والأفضل بلا فلاش.</li>
  <li>لقطعةٍ واحدة من الطقم (قلادة · حلق · خاتم) صوّرها وحدها.</li>
 </ul>
</section>
<section id="prep" class="card status" hidden>
 <div id="prepT">تجهيز أداة البحث…</div>
 <div class="bar"><i id="prepB"></i></div>
 <div id="prepS" class="small"></div>
</section>
<section id="crop" class="card" hidden>
 <div class="ctitle">حدِّد القطعة بالإطار (اسحبه أو اسحب زواياه)</div>
 <div id="stage"><canvas id="cv"></canvas><div id="box"><i class="h tl"></i>
 <i class="h tr"></i><i class="h bl"></i><i class="h br"></i></div></div>
 <div class="btns">
  <button id="go" class="big" type="button">🔍 ابحث</button>
  <button id="full" class="alt" type="button">الصورة كاملة</button>
 </div>
</section>
<section id="res" hidden>
 <div class="rhead"><img id="qimg" alt=""><div><b id="rT">أقرب الموديلات</b>
 <div id="rS" class="small"></div></div></div>
 <div class="btns">
  <label class="alt"><input id="cam2" type="file" accept="image/*"
   capture="environment" hidden>📷 صورة أخرى</label>
  <label class="alt" id="addL"><input id="add" type="file" accept="image/*"
   capture="environment" hidden>➕ لقطة ثانية للطقم نفسه (أدق)</label>
 </div>
 <div id="list"></div>
</section>
<div id="err" class="card err" hidden></div>
</main>
<script id="vis-data" type="application/json">{blob}</script>
<script src="{_e(base)}/vis/app.js?v={_app_ver()}"></script>
</body></html>"""


_CSS = """
:root{--gold:#b8891f;--ink:#2b2318;--line:#e6dccb;--in:#1e7a46;--out:#9a5b0f;
--bg:#f6f2ea}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font-family:system-ui,-apple-system,"Segoe UI",Tahoma,sans-serif;font-size:15px}
header{position:sticky;top:0;z-index:5;display:flex;align-items:center;
justify-content:space-between;gap:8px;padding:10px 14px;
background:linear-gradient(90deg,#2b2318,#4a3a22);color:#f7ecd3}
header h1{font-size:17px;margin:0}
header a.back{color:#f7ecd3;text-decoration:none;font-size:14px;
border:1px solid rgba(255,255,255,.3);border-radius:18px;padding:4px 12px}
main{max-width:760px;margin:0 auto;padding:12px 12px 40px}
.card{background:#fff;border:1px solid var(--line);border-radius:14px;
padding:14px;margin-bottom:12px}
.lead{margin:0 0 12px;line-height:1.7}
.btns{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}
.big,.alt{display:inline-flex;align-items:center;justify-content:center;
gap:6px;border-radius:12px;padding:12px 16px;font-size:16px;font-weight:700;
cursor:pointer;border:0;font-family:inherit}
.big{background:var(--gold);color:#fff;flex:1 1 200px}
.alt{background:#f1e9da;color:var(--ink);flex:1 1 160px;font-size:14.5px}
.tips{margin:6px 0 0;padding-inline-start:18px;color:#6b5d48;font-size:13.5px;
line-height:1.8}
.status .bar{height:10px;background:#efe6d6;border-radius:6px;overflow:hidden;
margin:10px 0 6px}
.status .bar i{display:block;height:100%;width:0;background:var(--gold);
transition:width .3s}
.small{font-size:12.5px;color:#7a6c57}
.err{border-color:#e5b4ae;background:#fff4f2;color:#8f2a1f}
.ctitle{font-weight:700;margin-bottom:8px}
#stage{position:relative;touch-action:none;user-select:none;margin:0 auto;
max-width:100%}
#cv{display:block;width:100%;height:auto;border-radius:10px;background:#222}
#box{position:absolute;border:2px solid #ffd76a;border-radius:6px;
box-shadow:0 0 0 9999px rgba(0,0,0,.45);touch-action:none}
#box .h{position:absolute;width:26px;height:26px;background:#ffd76a;
border-radius:50%;border:3px solid #fff}
#box .tl{top:-13px;left:-13px}#box .tr{top:-13px;right:-13px}
#box .bl{bottom:-13px;left:-13px}#box .br{bottom:-13px;right:-13px}
.rhead{display:flex;gap:10px;align-items:center;margin:4px 0 6px}
.rhead img{width:64px;height:64px;object-fit:cover;border-radius:10px;
border:1px solid var(--line)}
.hit{display:grid;grid-template-columns:110px 1fr;gap:10px;background:#fff;
border:1px solid var(--line);border-radius:14px;padding:10px;margin-bottom:10px}
.hit.top{border:2px solid var(--gold)}
.hit img{width:110px;height:110px;object-fit:contain;background:#fff;
border-radius:10px;border:1px solid #f0e8da}
.hit h2{font-size:17px;margin:0 0 4px;display:flex;justify-content:space-between;
gap:6px;align-items:center}
.sim{font-size:12.5px;border-radius:14px;padding:3px 9px;white-space:nowrap;
font-weight:700}
.s-hi{background:#e3f3e8;color:#1e6b3d}.s-mid{background:#fbf1d8;color:#7d5c10}
.s-lo{background:#f3eee6;color:#7a6c57}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0}
.chip{font-size:12.5px;border-radius:14px;padding:3px 9px;font-weight:600}
.chip.in{background:#e7f4ec;color:var(--in)}
.chip.out{background:#fbefe0;color:var(--out)}
details{grid-column:1/-1}
summary{cursor:pointer;font-size:13.5px;color:#6b5d48;padding:4px 0}
table{width:100%;border-collapse:collapse;font-size:13px;margin:6px 0}
th{background:#f6f0e4;font-weight:700;padding:6px 4px;text-align:right}
td{padding:6px 4px;border-bottom:1px solid #f1eadc}
td.n{font-variant-numeric:tabular-nums;white-space:nowrap}
h3{font-size:13.5px;margin:8px 0 2px}
h3.in{color:var(--in)}h3.out{color:var(--out)}
.more{display:block;width:100%;margin-top:4px}
"""
