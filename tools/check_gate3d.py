# -*- coding: utf-8 -*-
"""فحص مشهد الدخول ثلاثي الأبعاد (5.3) — ملفّاته وبديله وحارسه.

    python tools/check_gate3d.py

لا يحتاج كرت شاشة: يفحص ما يمكن فحصه بلا عرض (الملفّات، والمجسّمات داخل
data.js، وأن الصفحة لا تطلب شيئاً من الإنترنت، والبديل حين يتعذّر المشهد،
وحارس السلاسة، وضمّ الملفّات في حزمة التحديث والـexe). أمّا الصورة نفسها
فتُفحص بالعين من لقطات `tools/gate3d` (انظر build.mjs).
"""
import base64
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

OK, BAD = [], []


def check(name, cond, info=""):
    (OK if cond else BAD).append(name + (f" — {info}" if info and not cond else ""))
    print(("  ✔ " if cond else "  ✘ ") + name + (f"  ({info})" if info else ""))


def main():
    d = ROOT / "assets" / "gate3d"
    print("── الملفّات")
    for f in ("index.html", "gate3d.js", "data.js"):
        check(f"assets/gate3d/{f} موجود", (d / f).exists())
    html = (d / "index.html").read_text(encoding="utf-8")
    check("الصفحة لا تطلب شيئاً من الشبكة",
          not re.search(r"""(src|href)\s*=\s*["']?(https?:)?//""", html))
    check("الصفحة تحمل data.js ثم gate3d.js",
          html.find("data.js") < html.find("gate3d.js") and "data.js" in html)

    print("── المجسّمات داخل data.js")
    raw = (d / "data.js").read_text(encoding="utf-8")
    m = re.search(r"window\.GATE3D_DATA=(\{.*\});", raw, re.S)
    check("data.js يعرّف GATE3D_DATA", bool(m))
    data = json.loads(m.group(1)) if m else {}
    for key in ("bars", "logo"):
        b64 = str(data.get(key, ""))
        ok = b64.startswith("data:model/gltf-binary;base64,")
        blob = base64.b64decode(b64.split(",", 1)[1]) if ok else b""
        check(f"مجسّم {key}: glTF ثنائي", blob[:4] == b"glTF",
              f"{len(blob) // 1024} ك.ب")
        # الأسماء تُقرأ في المشهد (BarCast · BarMint · LogoEmblem …)
        js_len = int.from_bytes(blob[12:16], "little") if len(blob) > 20 else 0
        meta = json.loads(blob[20:20 + js_len]) if js_len else {}
        names = {n.get("name", "") for n in meta.get("nodes", [])}
        want = {"bars": ("BarCast", "BarMint"),
                "logo": ("LogoEmblem", "LogoName", "LogoTagline")}[key]
        check(f"  عُقد {key}: {' · '.join(want)}",
              all(any(n.startswith(w) for n in names) for w in want),
              ", ".join(sorted(names))[:120])
        exts = meta.get("extensionsUsed", [])
        check(f"  {key} مضغوط بـ meshopt",
              "EXT_meshopt_compression" in exts, ",".join(exts))

    print("── المشهد (gate3d.js)")
    js = (d / "gate3d.js").read_text(encoding="utf-8")
    for api in ("setLogoRect", "setExit", "hideLogo", "pause", "resume",
                "GATE3D:"):
        check(f"واجهة المشهد: {api}", api in js)
    check("يكشف الرسم بالمعالج (يسلّم للمقطع)",
          "swiftshader" in js and "llvmpipe" in js)
    # (والصفحة نفسها ممنوعةٌ من الشبكة في `gate3d_stage`:
    #  LocalContentCanAccessRemoteUrls=False وأيُّ انتقالٍ لغير ملفٍّ محلّي يُرفض)
    check("لا طلبَ صريحاً إلى الشبكة",
          not re.search(r"""(fetch|open)\(\s*["'`]https?:""", js))
    stage_src = (ROOT / "ui" / "widgets" / "gate3d_stage.py").read_text(
        encoding="utf-8")
    check("عزل Chromium مطفأٌ للصفحة المحلّية (يُسقط العرض في الـexe الواحد)",
          'os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")' in stage_src)
    check("الصفحة ممنوعةٌ من الشبكة في المتصفّح المدمج",
          '("LocalContentCanAccessRemoteUrls", False)' in stage_src
          and "def acceptNavigationRequest" in stage_src)
    node = shutil.which("node")
    if node:
        r = subprocess.run([node, "--check", str(d / "gate3d.js")],
                           capture_output=True, text=True)
        check("gate3d.js سليم البناء (node --check)", r.returncode == 0,
              r.stderr[:160])
    src = ROOT / "tools" / "gate3d"
    for f in ("src/main.js", "build.mjs", "package.json", "make_models.py",
              "fonts/Cinzel_700Bold.ttf", "fonts/Cinzel-OFL.txt"):
        check(f"مصدر: tools/gate3d/{f}", (src / f).exists())
    pkg = json.loads((src / "package.json").read_text(encoding="utf-8"))
    deps = pkg.get("devDependencies", {})
    check("إصدارات أدوات البناء مثبّتة بالضبط",
          all(re.fullmatch(r"\d+\.\d+\.\d+", v) for v in deps.values()),
          json.dumps(deps))

    print("── البديل والحارس (بلا كرت شاشة)")
    from PyQt5 import QtWidgets
    from ui.widgets import gate3d_stage as g3
    from ui.widgets.cinema_stage import CinemaStage
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    _ = app
    check("why_not يذكر سبباً هنا (لا عرض)", bool(g3.why_not()), g3.why_not())
    os.environ["JADEITE_GATE3D"] = "0"
    check("JADEITE_GATE3D=0 يطفئه", g3.why_not() == "أُطفئ بالإعداد")
    os.environ.pop("JADEITE_GATE3D", None)
    w = QtWidgets.QWidget()
    st = g3.make_stage(w)
    check("make_stage يعطي المقطع المصوَّر حين يتعذّر المشهد",
          isinstance(st, CinemaStage), type(st).__name__)
    check("حارس السلاسة: تأخّرٌ دائم يُرفض",
          g3.too_slow([60.0] * 80 + [0.0] * 10))
    check("حارس السلاسة: قفزاتٌ عابرة لا تُرفض",
          not g3.too_slow([2.0] * 80 + [900.0] * 10))
    check("حارس السلاسة: بلا عيّنات لا حكم", not g3.too_slow([]))

    from ui.gate_window import GateWindow
    import config
    keep = getattr(config, "LOGO_GOLD_PATH", None)
    try:
        config.LOGO_GOLD_PATH = ROOT / "assets" / "logo_gold.png"
        check("شعار JADEITE الأصلي يُرسم مجسّماً",
              GateWindow._is_jadeite_logo())
        config.LOGO_GOLD_PATH = ROOT / "data" / "branding" / "logo_abc.png"
        check("شعار مصنعٍ خاص يبقى صورته", not GateWindow._is_jadeite_logo())
        config.LOGO_GOLD_PATH = None
        check("بلا شعار: لا مجسّم", not GateWindow._is_jadeite_logo())
    finally:
        config.LOGO_GOLD_PATH = keep
    gate = GateWindow()
    check("البوابة تُبنى بالمقطع حين يتعذّر المشهد",
          not gate._3d and isinstance(gate.stage, CinemaStage))
    gate.close()

    print("── الحزم")
    sys.path.insert(0, str(ROOT / "tools"))
    import make_update
    files = {str(rel).replace("\\", "/") for _p, rel in make_update._files()}
    check("حزمة التحديث تحمل ملفّات المشهد",
          all(f"assets/gate3d/{f}" in files
              for f in ("index.html", "gate3d.js", "data.js")))
    check("حزمة التحديث بلا node_modules ولا مخرجات Blender",
          not any("node_modules" in f or f.startswith("tools/gate3d/build/")
                  for f in files))
    bsrc = (ROOT / "core" / "build.py").read_text(encoding="utf-8")
    check("الـexe يضمّ محرّك الويب (QtWebEngine)",
          "PyQt5.QtWebEngineWidgets" in bsrc and "_webengine_args()" in bsrc)
    check("الـexe يضمّ مجلد assets (ومنه gate3d)", '("assets", "assets")' in bsrc)
    bat = (ROOT / "MAKE_EXE.bat").read_text(encoding="utf-8")
    check("MAKE_EXE.bat يثبّت PyQtWebEngine", "PyQtWebEngine" in bat)

    print()
    print(f"{len(OK)} ✔   {len(BAD)} ✘")
    for b in BAD:
        print("  ✘", b)
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
