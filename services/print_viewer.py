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
  .jv-bar .jv-sep { width: 1px; height: 24px; background: #5A5146; }
  .jv-bar button.on { background: #F3EBD3; color: #2B2723;
    border-color: #F3EBD3; font-weight: bold; }
  .jv-bar .jv-c { width: 20px; height: 20px; padding: 0; border-radius: 50%;
    border: 2px solid #5A5146; }
  .jv-bar .jv-c.on { border-color: #fff; box-shadow: 0 0 0 2px #B8933A; }
  /* التعليقات على الورقة (4.97): تظليلٌ ونصّ — تُطبع معها */
  .sheet { position: relative; }
  .jv-ann { position: absolute; z-index: 5; }
  .jv-box { border-radius: 3px; mix-blend-mode: multiply;
    pointer-events: none; }
  .jv-note { min-width: 30px; min-height: 18px; padding: 1px 4px;
    font-weight: bold; font-size: 12pt; line-height: 1.35;
    white-space: pre-wrap; outline: none; cursor: text;
    background: rgba(255,255,255,.0); }
  .jv-note:focus { outline: 1.5px dashed #B8933A; background: #fff; }
  body.jv-mode-hl .sheet { cursor: crosshair; user-select: none; }
  body.jv-mode-tx .sheet { cursor: text; }
  @media print { .jv-note:focus { outline: none; } }
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
        '<span class="jv-sep"></span>'
        '<button id="jvhl" onclick="jvMode(\'hl\')" title="اسحب على الورقة'
        ' لتظليل جزءٍ منها">🖍 تظليل</button>'
        '<button id="jvtx" onclick="jvMode(\'tx\')" title="انقر في أي مكانٍ'
        ' من الورقة واكتب">✎ نص</button>'
        + "".join(
            f'<button class="jv-c" data-c="{c}" style="background:{c}"'
            f' onclick="jvColor(this)" title="{t}"></button>'
            for c, t in (("#FFE14D", "أصفر"), ("#9BE89B", "أخضر"),
                         ("#FFB3C7", "وردي"), ("#9CC9FF", "أزرق"),
                         ("#C62828", "أحمر (للنص)"))) +
        '<button onclick="jvUndo()" title="تراجع عن آخر تظليل أو نص">↶</button>'
        '<button onclick="jvClear()" title="مسح كل التظليل والنصوص">🧹</button>'
        '<span class="jv-sep"></span>'
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
        # ══ التظليل والنص (4.97) ══ مواضعها نسبةً إلى الورقة نفسها
        # (`.sheet`) بلا أثر التكبير — فتُطبع حيث وُضعت
        "var mode='',col='#FFE14D',tcol='#C62828',stack=[],drag=null;"
        "function sh(){return document.querySelector('.sheet');}"
        "function pt(e){var s=sh(),r=s.getBoundingClientRect(),k=z/100;"
        "return {x:(e.clientX-r.left)/k,y:(e.clientY-r.top)/k};}"
        "window.jvMode=function(m){mode=(mode===m)?'':m;"
        "document.body.classList.toggle('jv-mode-hl',mode==='hl');"
        "document.body.classList.toggle('jv-mode-tx',mode==='tx');"
        "document.getElementById('jvhl').classList.toggle('on',mode==='hl');"
        "document.getElementById('jvtx').classList.toggle('on',mode==='tx');};"
        "window.jvColor=function(b){var c=b.getAttribute('data-c');"
        "if(c==='#C62828'){tcol=c;}else{col=c;tcol=(c==='#FFE14D')?"
        "'#C62828':c;}"
        "var bs=document.querySelectorAll('.jv-c');"
        "for(var i=0;i<bs.length;i++){bs[i].classList.toggle('on',bs[i]===b);}};"
        "function ink(c){return c==='#9BE89B'?'#1B7A2E':c==='#FFB3C7'?"
        "'#B0124A':c==='#9CC9FF'?'#1F5FB4':'#C62828';}"
        "window.jvUndo=function(){var el=stack.pop();"
        "if(el&&el.parentNode){el.parentNode.removeChild(el);}};"
        "window.jvClear=function(){var a=document.querySelectorAll('.jv-ann');"
        "for(var i=0;i<a.length;i++){a[i].parentNode.removeChild(a[i]);}"
        "stack=[];};"
        "document.addEventListener('mousedown',function(e){"
        "var s=sh();if(!s||!s.contains(e.target)){return;}"
        "if(mode==='hl'){e.preventDefault();var p=pt(e);"
        "var b=document.createElement('div');b.className='jv-ann jv-box';"
        "b.style.background=col;b.style.opacity='.55';"
        "b.style.left=p.x+'px';b.style.top=p.y+'px';"
        "b.style.width='0px';b.style.height='0px';s.appendChild(b);"
        "drag={b:b,x:p.x,y:p.y};return;}"
        "if(mode==='tx'&&!(e.target.classList&&"
        "e.target.classList.contains('jv-note'))){e.preventDefault();"
        "var q=pt(e);var n=document.createElement('div');"
        "n.className='jv-ann jv-note';n.contentEditable='true';"
        "n.style.color=(tcol==='#C62828'?'#C62828':ink(tcol));"
        "n.style.left=q.x+'px';n.style.top=(q.y-10)+'px';s.appendChild(n);"
        "stack.push(n);n.focus();setTimeout(function(){"
        "if(document.activeElement!==n){n.focus();}},0);"
        "n.addEventListener('blur',function(){if(!n.textContent.trim()){"
        "if(n.parentNode){n.parentNode.removeChild(n);}"
        "var i=stack.indexOf(n);if(i>=0){stack.splice(i,1);}}});}});"
        "document.addEventListener('mousemove',function(e){if(!drag){return;}"
        "var p=pt(e),b=drag.b;"
        "b.style.left=Math.min(p.x,drag.x)+'px';"
        "b.style.top=Math.min(p.y,drag.y)+'px';"
        "b.style.width=Math.abs(p.x-drag.x)+'px';"
        "b.style.height=Math.abs(p.y-drag.y)+'px';});"
        "document.addEventListener('mouseup',function(){if(!drag){return;}"
        "var b=drag.b;drag=null;"
        "if(parseFloat(b.style.width)<4||parseFloat(b.style.height)<4){"
        "b.parentNode.removeChild(b);}else{stack.push(b);}});"
        "document.addEventListener('keydown',function(e){"
        "if(e.key==='Escape'&&mode){jvMode(mode);if(document.activeElement)"
        "{document.activeElement.blur();}return;}"
        "if(e.key==='Escape'){window.close();}"
        "if((e.ctrlKey||e.metaKey)&&e.key==='z'&&!(document.activeElement&&"
        "document.activeElement.isContentEditable)){e.preventDefault();"
        "jvUndo();}"
        "if((e.ctrlKey||e.metaKey)&&(e.key==='+'||e.key==='=')){"
        "e.preventDefault();jvZoom(1);}"
        "if((e.ctrlKey||e.metaKey)&&e.key==='-'){e.preventDefault();"
        "jvZoom(-1);}});"
        "})();</script>")
