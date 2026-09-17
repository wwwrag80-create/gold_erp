# -*- coding: utf-8 -*-
"""خادم صور الموديلات المحلي — لفتح صور الفاتورة من الجوال بـ QR.

**المشكلة**: صور الموديلات ملفات على جهاز المصنع. ورمز QR يحمل نصاً
لا ملفاً، والجوال لا يفتح مساراً على جهاز آخر. فلا سبيل لأن يرى من
بيده الفاتورة الورقية شكل الأطقم التي فيها.

**الحل**: خادم صغير داخل النظام نفسه يعرض صفحة صور الفاتورة على شبكة
المصنع المحلية، ورمز QR يحمل عنوانها. يصوّر الموظف الرمز بجواله
المتصل بشبكة المصنع فتفتح الصور فوراً.

**الحدود المقصودة**:
* لا يخرج شيء إلى الإنترنت إطلاقاً — الصفحة على الشبكة المحلية وحدها.
* الرابط يحمل رمزاً عشوائياً لكل فاتورة لا يمكن تخمينه، ولا يعرض إلا
  صور تلك الفاتورة. وينتهي بانتهاء تشغيل النظام.
* الخادم **لا يكتب شيئاً**: قراءة صور فقط، بلا أي مسار يقبل بيانات.
* فشل تشغيله لأي سبب (منفذ مشغول · جدار حماية) لا يعطّل الطباعة —
  تُطبع الفاتورة بلا رمز، وهذا ما تفعله `qr_for_invoice` عند العجز.
"""
import html
import mimetypes
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DEFAULT_PORT = 8733
TTL_SECONDS = 12 * 3600          # الرابط يعيش يوم عمل واحد

_lock = threading.Lock()
_state = {"server": None, "port": None, "host": None}
_docs = {}                       # token → {"no":…, "items":[…], "at":…}


# ══════════════════════════════════════════════════════════════════
#  عنوان الجهاز على الشبكة المحلية
# ══════════════════════════════════════════════════════════════════

def lan_ip():
    """عنوان الجهاز على شبكة المصنع (لا 127.0.0.1 فالجوال لا يبلغه)."""
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # لا يُرسل شيئاً فعلياً — يكشف البطاقة التي تخرج منها الشبكة
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"
    finally:
        if s is not None:
            try:
                s.close()
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════
#  السجل المؤقت للفواتير المنشورة
# ══════════════════════════════════════════════════════════════════

def _prune():
    now = time.time()
    for tok in [t for t, d in _docs.items() if now - d["at"] > TTL_SECONDS]:
        _docs.pop(tok, None)


def register(invoice_no, items, page=None):
    """يسجّل صفحة فاتورة ويعيد رمزها.

    `items`: [(الموديل, المسار)] — الصور تُقدَّم من `/img/<رمز>/<فهرس>`.
    `page(src_fn)`: دالةٌ تبني صفحة HTML كاملة، تتلقّى دالةً تعيد عنوان
    صورة كل موديل. بلا `page` تُعرض الصور وحدها كما كان.
    """
    with _lock:
        _prune()
        tok = secrets.token_urlsafe(12)
        _docs[tok] = {"no": str(invoice_no), "items": list(items),
                      "page": page, "at": time.time()}
        return tok


def _doc(tok):
    with _lock:
        d = _docs.get(tok)
        if d and time.time() - d["at"] > TTL_SECONDS:
            _docs.pop(tok, None)
            return None
        return d


# ══════════════════════════════════════════════════════════════════
#  الخادم
# ══════════════════════════════════════════════════════════════════

_PAGE = """<!DOCTYPE html>
<html dir="rtl" lang="ar"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>صور فاتورة {no}</title>
<style>
 body {{ font-family: system-ui, "Segoe UI", Tahoma, sans-serif;
        margin: 0; padding: 14px; background: #F5F2EA; color: #2b2723; }}
 h1 {{ font-size: 18px; margin: 0 0 12px; }}
 .g {{ display: grid; gap: 12px;
      grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); }}
 .c {{ background: #fff; border: 1px solid #ddd; border-radius: 10px;
      overflow: hidden; }}
 .c img {{ width: 100%; height: 170px; object-fit: cover; display: block; }}
 .t {{ padding: 7px; font-size: 13px; text-align: center;
      border-top: 1px solid #eee; }}
 .e {{ padding: 24px; text-align: center; color: #777; }}
</style></head><body>
<h1>صور موديلات الفاتورة {no}</h1>
<div class="g">{cards}</div>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    server_version = "JadeitePhotos/1.0"

    def log_message(self, *_a):
        pass                    # لا نلوّث سجل النظام بكل طلب صورة

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body if isinstance(body, bytes) else str(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except Exception:
            pass

    def do_GET(self):                                  # noqa: N802
        parts = [p for p in self.path.split("?")[0].split("/") if p]
        if len(parts) == 2 and parts[0] == "inv":
            return self._page(parts[1])
        if len(parts) == 3 and parts[0] == "img":
            return self._image(parts[1], parts[2])
        self._send(404, "<h3>غير موجود</h3>")

    def _page(self, tok):
        d = _doc(tok)
        if not d:
            return self._send(404, "<h3>انتهت صلاحية الرابط</h3>")
        # صفحةٌ جاهزة من `invoice_share` (الفاتورة ثم موديلاتها).
        # الصور تبقى تُقدَّم من هنا: الملفات على هذا الجهاز وحده.
        builder = d.get("page")
        if callable(builder):
            try:
                return self._send(200, builder(
                    lambda i: f"/img/{tok}/{i}"))
            except Exception:
                pass          # تعذّر بناء الصفحة ⇒ العرض المبسّط أدناه
        cards = []
        for i, (model, _path) in enumerate(d["items"]):
            m = html.escape(str(model))
            cards.append(
                f'<div class="c"><img src="/img/{tok}/{i}" alt="{m}">'
                f'<div class="t">{m}</div></div>')
        body = ("".join(cards) if cards
                else '<div class="e">لا توجد صور محفوظة لموديلات '
                     'هذه الفاتورة.</div>')
        self._send(200, _PAGE.format(no=html.escape(d["no"]), cards=body))

    def _image(self, tok, idx):
        d = _doc(tok)
        if not d:
            return self._send(404, "انتهت صلاحية الرابط", "text/plain")
        try:
            # الفهرس وحده يُقبل — فلا يمكن طلب أي مسار آخر على الجهاز
            _model, path = d["items"][int(idx)]
            raw = Path(path).read_bytes()
        except Exception:
            return self._send(404, "لا توجد صورة", "text/plain")
        ctype = mimetypes.guess_type(str(path))[0] or "image/jpeg"
        self._send(200, raw, ctype)


def ensure_running(port=DEFAULT_PORT):
    """يشغّل الخادم مرة واحدة ويعيد (العنوان, المنفذ) أو None عند العجز."""
    with _lock:
        if _state["server"] is not None:
            return _state["host"], _state["port"]
    for p in range(port, port + 10):
        try:
            srv = ThreadingHTTPServer(("0.0.0.0", p), _Handler)
        except OSError:
            continue             # المنفذ مشغول — جرّب التالي
        except Exception:
            return None
        srv.daemon_threads = True
        t = threading.Thread(target=srv.serve_forever, daemon=True,
                             name="photo-server")
        t.start()
        with _lock:
            _state.update({"server": srv, "port": p, "host": lan_ip()})
            return _state["host"], _state["port"]
    return None


def publish_invoice(invoice_no, items, port=DEFAULT_PORT):
    """ينشر صور فاتورة ويعيد رابطها، أو None إن تعذّر تشغيل الخادم."""
    return publish_page(invoice_no, items, None, port)


def publish_page(invoice_no, items, page=None, port=DEFAULT_PORT):
    """ينشر صفحة فاتورة (وصورها) على شبكة المصنع ويعيد رابطها.

    **حدٌّ لا مفرّ منه**: العنوان المعاد عنوانٌ خاص (`192.168.x.x`)، لا
    يبلغه إلا جهازٌ على شبكة المصنع نفسها وما دام النظام يعمل. فهذا
    الرابط للموظف لا للعميل الذي يخرج بالورقة — ولذلك يُجرَّب النشر
    السحابي أولاً في `services.invoice_share`.
    """
    if not items and page is None:
        return None
    addr = ensure_running(port)
    if not addr:
        return None
    host, p = addr
    return f"http://{host}:{p}/inv/{register(invoice_no, items, page)}"


def stop():
    """يوقف الخادم — عند إغلاق النظام."""
    with _lock:
        srv = _state.get("server")
        _state.update({"server": None, "port": None, "host": None})
        _docs.clear()
    if srv is not None:
        try:
            srv.shutdown()
            srv.server_close()
        except Exception:
            pass
    return True
