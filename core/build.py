# -*- coding: utf-8 -*-
"""بناء النسخة التنفيذية (.exe) لنظام جاديت.

ينتج ملفين في `dist/gold_erp/`:
  * `gold_erp.exe`  — التطبيق الرئيسي
  * `updater.exe`   — برنامج التحديث المستقل

الاستخدام:
    pip install pyinstaller
    python build.py               # بناء كامل
    python build.py --clean       # حذف مخلفات البناء أولاً
    python build.py --onefile     # ملف واحد (أبطأ إقلاعاً)
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
OUT = DIST / "gold_erp"

APP_NAME = "gold_erp"
ICON = ROOT / "assets" / "logo.ico"

# ملفات ومجلدات تُرفَق مع التطبيق (بيانات لا كود)
DATA = [
    ("assets", "assets"),
    ("migrations", "migrations"),
    ("cloud", "cloud"),
]

# وحدات يستوردها النظام ديناميكياً فلا يكتشفها PyInstaller وحده
# وحدات تُستورد ديناميكياً فلا يكتشفها PyInstaller وحده.
# نقصان أيٍّ منها يجعل الـexe يفشل صامتاً عند تسجيل الدخول.
HIDDEN = [
    "PyQt5.QtPrintSupport", "PyQt5.QtSvg", "PyQt5.QtNetwork", "sqlite3",
    "gzip", "urllib.request", "urllib.parse", "urllib.error",
    "services.migrations", "services.licensing", "services.cloud_sync",
    "services.tenant", "services.cloud_auth", "services.cloud_backup",
    "services.sync_queue", "services.auth", "services.audit",
    "app_config", "core.app_config", "core.config",
    "qrcode", "PIL", "barcode",
]


def _sep():
    return ";" if sys.platform.startswith("win") else ":"


def _clean():
    for d in (DIST, BUILD):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    for spec in ROOT.glob("*.spec"):
        spec.unlink(missing_ok=True)
    print("✔ نُظّفت مخلفات البناء السابقة")


def _common_args(onefile):
    args = ["--noconfirm", "--clean", "--windowed",
            "--distpath", str(DIST), "--workpath", str(BUILD),
            "--specpath", str(ROOT)]
    args.append("--onefile" if onefile else "--onedir")
    if ICON.exists():
        args += ["--icon", str(ICON)]
    return args


def _bundled_env():
    """يُجهّز ملف .env مُصفّى للإرفاق داخل الـexe.

    يُرفق **الرابط والمفتاح العام فقط** — وهما مصمَّمان للنشر ومحميّان
    بسياسات RLS. أما مفتاح الخدمة وكلمة مرور القاعدة فلا يُرفقان
    إطلاقاً، فمن يفكّ الـexe لا يجد فيهما شيئاً خطيراً.
    """
    import tempfile
    try:
        import app_config
        url = app_config.supabase_url()
        pub = app_config.supabase_key()
    except Exception:
        url = pub = ""
    if not (url and pub):
        print("")
        print("  [ERROR] Cloud settings are missing in .env")
        print("          Open .env and fill these two lines:")
        print("              SUPABASE_URL=https://xxxx.supabase.co")
        print("              SUPABASE_PUBLISHABLE_KEY=sb_publishable_...")
        print("          Without them factory accounts cannot sign in.")
        print("")
        raise SystemExit(1)
    d = Path(tempfile.mkdtemp(prefix="jadeite_env_"))
    (d / ".env").write_text(
        f"SUPABASE_URL={url}\nSUPABASE_PUBLISHABLE_KEY={pub}\n",
        encoding="utf-8")
    print(f"  [OK] Cloud settings bundled: {url}")
    return d / ".env"


def _splash_png():
    """يرسم صورة شاشة البدء التي يعرضها الـexe قبل إقلاع بايثون.

    **الثواني التي لا تغطّيها البوابة**: ملف onefile يفكّ نفسه في
    مجلدٍ مؤقّت قبل أن يبدأ بايثون أصلاً، فالنقرُ لا يُتبعه شيء
    لثوانٍ. شاشةُ بدء PyInstaller تظهر في تلك الفجوة بالذات،
    وتُغلقها البوابةُ حين تفتح — فالتسلسل متّصلٌ من النقرة إلى
    الترحيب.

    تُرجع مساراً أو `None`؛ وفشلُها لا يمنع البناء.
    """
    try:
        import tempfile

        from PyQt5 import QtCore, QtGui, QtWidgets
        app = (QtWidgets.QApplication.instance()
               or QtWidgets.QApplication([]))
        _ = app
        w, h = 520, 300
        img = QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32)
        img.fill(QtGui.QColor("#17120C"))
        p = QtGui.QPainter(img)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
        g = QtGui.QRadialGradient(w / 2, h * 0.42, w * 0.55)
        c0 = QtGui.QColor("#4A3616")
        c0.setAlpha(150)
        c1 = QtGui.QColor("#4A3616")
        c1.setAlpha(0)
        g.setColorAt(0.0, c0)
        g.setColorAt(1.0, c1)
        p.fillRect(0, 0, w, h, QtGui.QBrush(g))
        from ui.gate_window import _emblem
        em = _emblem(96)
        p.drawPixmap(int(w / 2 - 48), 34, em)
        f = QtGui.QFont()
        f.setPointSize(15)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QtGui.QColor("#F6E7B6"))
        p.drawText(QtCore.QRect(0, 150, w, 40),
                   int(QtCore.Qt.AlignCenter), "نظام إدارة مصانع الذهب")
        f.setPointSize(10)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QtGui.QColor("#C9A227"))
        p.drawText(QtCore.QRect(0, 194, w, 30),
                   int(QtCore.Qt.AlignCenter), "جارٍ التشغيل…")
        pen = QtGui.QPen(QtGui.QColor("#8A6F1E"))
        pen.setWidth(2)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawRoundedRect(QtCore.QRectF(6, 6, w - 12, h - 12), 10, 10)
        p.end()
        out = Path(tempfile.mkdtemp(prefix="jadeite_splash_")) / "splash.png"
        img.save(str(out))
        return out if out.exists() else None
    except Exception as e:                       # noqa: BLE001
        print(f"  [i] تعذّر إعداد شاشة البدء ({e}) — يُبنى بدونها")
        return None


def build_app(onefile=False):
    print("── بناء التطبيق الرئيسي ──")
    args = [sys.executable, "-m", "PyInstaller",
            "--name", APP_NAME] + _common_args(onefile)
    for src, dst in DATA:
        p = ROOT / src
        if p.exists():
            args += ["--add-data", f"{p}{_sep()}{dst}"]
    env_file = _bundled_env()
    if env_file:
        args += ["--add-data", f"{env_file}{_sep()}."]
    for h in HIDDEN:
        args += ["--hidden-import", h]
    # ضمّ كل حزم المشروع كاملةً — أضمن من الاعتماد على الاكتشاف
    for pkg in ("services", "models", "ui", "database", "core", "tools"):
        if (ROOT / pkg).is_dir():
            args += ["--collect-submodules", pkg]
    # ضمّ ملفات بيانات المكتبات (خطوط الباركود مثلاً) تحسّباً
    for pkg in ("barcode", "qrcode"):
        args += ["--collect-all", pkg]
    args.append(str(ROOT / "main.py"))

    # شاشة البدء تُجرَّب، وإن رفضتها أداة البناء (بيئةٌ بلا Tk مثلاً)
    # يُعاد البناء بدونها — لا يُحرم العميل من الملف لأجل زينة.
    splash = _splash_png()
    if splash:
        try:
            subprocess.check_call(
                args[:-1] + ["--splash", str(splash), args[-1]])
            print("✔ gold_erp.exe جاهز (بشاشة بدء)")
            return
        except subprocess.CalledProcessError:
            print("  [i] تعذّر ضمّ شاشة البدء — يُعاد البناء بدونها")
    subprocess.check_call(args)
    print("✔ gold_erp.exe جاهز")


def main():
    onefile = "--onefile" in sys.argv
    if "--clean" in sys.argv:
        _clean()
    try:
        build_app(onefile)
    except FileNotFoundError:
        print("")
        print("  [ERROR] PyInstaller is NOT installed.")
        print("  Run this command then try again:")
        print("      python -m pip install pyinstaller")
        print("")
        return 1
    except subprocess.CalledProcessError as e:
        print("")
        print(f"  [ERROR] Build failed (code {e.returncode})")
        print("")
        return 1
    exe = DIST / (f"{APP_NAME}.exe" if sys.platform.startswith("win")
                  else APP_NAME)
    print("")
    print("=" * 52)
    if exe.exists():
        size = exe.stat().st_size / (1024 * 1024)
        print(f"  SUCCESS: {exe}  ({size:.1f} MB)")
    else:
        print("  [ERROR] Output file was not created.")
        print(f"  Expected: {exe}")
        return 1
    print("=" * 52)
    return 0


if __name__ == "__main__":
    sys.exit(main())
