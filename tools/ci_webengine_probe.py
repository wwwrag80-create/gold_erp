# -*- coding: utf-8 -*-
"""فحص محرّك الويب على مشغّل GitHub (ويندوز) — لتشخيص المشهد ثلاثي الأبعاد.

يفتح صفحةً في QWebEngineView ويقول ما حدث خلال مهلة: هل حُمّلت؟ هل توقّفت
عملية العرض (ورمزها)؟ ما رسائل الصفحة؟ — بلا الملف التنفيذي (بايثون مباشرة)
ليُعرف هل العطل من البيئة أم من التحزيم. للفحص وحده.

    python tools/ci_webengine_probe.py simple|gate [ثوانٍ]
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from PyQt5 import QtCore  # noqa: E402

QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts, True)
from PyQt5 import QtWebEngineWidgets as W, QtWidgets  # noqa: E402

what = sys.argv[1] if len(sys.argv) > 1 else "simple"
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 15
app = QtWidgets.QApplication(sys.argv)
t0 = time.time()
log = []


def note(s):
    log.append(f"{time.time() - t0:5.2f}s {s}")
    print(log[-1], flush=True)


class Page(W.QWebEnginePage):
    def javaScriptConsoleMessage(self, lvl, msg, line, src):
        note(f"console[{lvl}] {msg[:200]}")


v = W.QWebEngineView()
p = Page(v)
v.setPage(p)
p.loadFinished.connect(lambda ok: note(f"loadFinished {ok}"))
p.renderProcessTerminated.connect(
    lambda st, code: note(f"renderProcessTerminated status={int(st)} code={code} ({code & 0xffffffff:#x})"))
v.resize(1280, 720)
v.show()
note("env QTWEBENGINE_CHROMIUM_FLAGS=" + os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
     + " DISABLE_SANDBOX=" + os.environ.get("QTWEBENGINE_DISABLE_SANDBOX", ""))
if what == "gate":
    url = QtCore.QUrl.fromLocalFile(str(ROOT / "assets" / "gate3d" / "index.html"))
    url.setQuery("soft=1&autostart=1")
    v.load(url)
else:
    v.setHtml("<html><body style='background:#000;color:#fc0'>hi<script>"
              "var c=document.createElement('canvas');var g=c.getContext('webgl2')||c.getContext('webgl');"
              "var d=g&&g.getExtension('WEBGL_debug_renderer_info');"
              "console.log('PROBE gl='+(g?(d?g.getParameter(d.UNMASKED_RENDERER_WEBGL):g.getParameter(g.RENDERER)):'none'));"
              "</script></body></html>")


def done():
    img = v.grab()
    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    tag = os.environ.get("PROBE_TAG", what)
    img.save(str(out / f"probe-{tag}.png"))
    note("end")
    app.quit()


QtCore.QTimer.singleShot(int(secs * 1000), done)
app.exec_()
