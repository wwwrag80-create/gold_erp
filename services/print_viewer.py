# -*- coding: utf-8 -*-
"""عارض الطباعة (4.96) — القالب في نافذةٍ خاصةٍ بالنظام، لا في المتصفح.

كانت المعاينة تُفتح في المتصفح الافتراضي (فايرفوكس مثلاً) بشريط عنوانه
وتبويباته وطباعته. والقوالب مصمَّمة لمحرّك متصفحٍ كامل (جداول بعرض
الورقة · الاتجاه العربي · الصور)، ومحرّك Qt المضمّن لا يبلغ ذلك.

فتُفتح الآن في **نافذة عارضٍ مستقلة** بمحرّك ويندوز المدمج (Edge — جزءٌ
من ويندوز 10/11 — أو كروم إن وُجد) في وضع «التطبيق»: نافذةٌ بلا شريط عنوانٍ
ولا تبويبات، فيها القالب كورقةٍ وشريط أدواتٍ عربي: طباعة · حفظ PDF ·
عمودي/أفقي · تكبير وتصغير · إغلاق. و«طباعة» تفتح نافذة الطباعة الكاملة:
اختيار الطابعة والنسخ والصفحات والهوامش والمقاس والحفظ PDF.

وإن لم يوجد المحرّك (جهازٌ قديم) فالمعاينة الاحتياطية داخل النظام (Qt).
"""
import os
import subprocess
import threading
from pathlib import Path

_ENGINE = [None, False]          # [المسار، فُحص؟]

_REL = (r"Microsoft\Edge\Application\msedge.exe",
        r"Google\Chrome\Application\chrome.exe")


def _from_registry():
    try:
        import winreg
    except ImportError:           # ليس ويندوز
        return None
    for name in ("msedge.exe", "chrome.exe"):
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(
                        hive, "SOFTWARE\\Microsoft\\Windows\\CurrentVersion"
                        "\\App Paths\\" + name) as k:
                    p = winreg.QueryValue(k, None)
                if p and os.path.isfile(p.strip('"')):
                    return p.strip('"')
            except OSError:
                continue
    return None


def engine():
    """مسار محرّك العارض (Edge ثم كروم) — أو None. يُفحص مرةً واحدة."""
    if _ENGINE[1]:
        return _ENGINE[0]
    path = None
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles(x86)"),
                     os.environ.get("ProgramFiles"),
                     os.environ.get("LOCALAPPDATA")):
            if path or not base:
                continue
            for rel in _REL:
                p = os.path.join(base, rel)
                if os.path.isfile(p):
                    path = p
                    break
        path = path or _from_registry()
    _ENGINE[0], _ENGINE[1] = path, True
    return path


def available():
    return engine() is not None


def launch(page_path):
    """يفتح الصفحة في نافذة العارض — True إن فُتحت.

    في خيطٍ مستقل: إقلاع المحرّك أول مرة يأخذ ثانيةً أو اثنتين، وخيط
    الواجهة لا ينتظره (فلا يقول ويندوز «لا يستجيب»)."""
    exe = engine()
    if not exe:
        return False
    uri = Path(str(page_path)).resolve().as_uri()
    args = [exe, f"--app={uri}", "--new-window", "--no-first-run",
            "--no-default-browser-check", "--disable-features=Translate",
            "--window-size=1200,900"]

    def _go():
        try:
            flags = 0
            if os.name == "nt":
                flags = (getattr(subprocess, "DETACHED_PROCESS", 0x8)
                         | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP",
                                   0x200))
            subprocess.Popen(args, close_fds=True, creationflags=flags,
                             stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except Exception:
            pass
    try:
        threading.Thread(target=_go, daemon=True,
                         name="JadeiteViewer").start()
    except Exception:
        _go()
    return True


# ══ شريط أدوات العارض — يظهر على الشاشة وحدها ولا يُطبع ══
VIEWER_CSS = """
<style>
  @media screen {
    html, body { background: #E7E3DA; }
    body { padding-top: 64px; }
    .sheet { background: #fff; margin: 14px auto 28px;
             box-shadow: 0 3px 16px rgba(0,0,0,.18); }
  }
  .jv-bar { position: fixed; top: 0; left: 0; right: 0; z-index: 99;
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    padding: 9px 14px; background: #2B2723; color: #F3EBD3;
    box-shadow: 0 2px 10px rgba(0,0,0,.25); font-size: 12pt; }
  .jv-bar .jv-t { font-weight: bold; margin-inline-end: auto;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .jv-bar button { font-family: inherit; font-size: 11.5pt; cursor: pointer;
    padding: 6px 14px; border-radius: 8px; border: 1px solid #5A5146;
    background: #3A342D; color: #F3EBD3; }
  .jv-bar button:hover { background: #4A4239; }
  .jv-bar button.pri { background: #B8933A; border-color: #B8933A;
    color: #fff; font-weight: bold; }
  .jv-bar button.pri:hover { background: #A07E2C; }
  .jv-bar .jv-z { min-width: 46px; text-align: center; }
  .jv-bar .jv-h { font-size: 9.5pt; color: #BFB4A0; }
</style>
"""


def toolbar(title, landscape=False):
    """شريط العارض: طباعة · PDF · عمودي/أفقي · تكبير · إغلاق."""
    import html as _h
    return (
        '<div class="jv-bar noprint">'
        f'<span class="jv-t">{_h.escape(title or "معاينة الطباعة")}</span>'
        '<button class="pri" onclick="window.print()" title="Ctrl+P —'
        ' اختر الطابعة والنسخ والصفحات والهوامش">🖨 طباعة</button>'
        '<button onclick="window.print()" title="من قائمة الطابعات اختر'
        ' «حفظ بصيغة PDF»">📄 حفظ PDF</button>'
        '<button onclick="jvOrient()" title="اتجاه الورقة">⟲ <span'
        f' id="jvo">{"أفقي" if landscape else "عمودي"}</span></button>'
        '<button onclick="jvZoom(-1)" title="تصغير">−</button>'
        '<span class="jv-z" id="jvz">100%</span>'
        '<button onclick="jvZoom(1)" title="تكبير">+</button>'
        '<button onclick="window.close()" title="Esc">✕ إغلاق</button>'
        '</div>'
        f'<style id="jvpage"></style><style id="jvzoom"></style>'
        "<script>(function(){"
        f"var land={'true' if landscape else 'false'},z=100;"
        "window.jvOrient=function(){land=!land;"
        "document.getElementById('jvo').textContent=land?'أفقي':'عمودي';"
        "document.getElementById('jvpage').textContent=land?"
        "'@page{size:A4 landscape}@media screen{.sheet{width:281mm}}"
        ".sheet{min-height:180mm}':"
        "'@page{size:A4 portrait}@media screen{.sheet{width:194mm}}"
        ".sheet{min-height:265mm}';"
        "window.dispatchEvent(new Event('load'));};"
        "window.jvZoom=function(d){z=Math.max(50,Math.min(200,z+d*10));"
        "document.getElementById('jvz').textContent=z+'%';"
        "document.getElementById('jvzoom').textContent="
        "'@media screen{.sheet{zoom:'+(z/100)+'}}';};"
        "document.addEventListener('keydown',function(e){"
        "if(e.key==='Escape'){window.close();}"
        "if((e.ctrlKey||e.metaKey)&&(e.key==='+'||e.key==='=')){"
        "e.preventDefault();jvZoom(1);}"
        "if((e.ctrlKey||e.metaKey)&&e.key==='-'){e.preventDefault();"
        "jvZoom(-1);}});"
        "})();</script>")
