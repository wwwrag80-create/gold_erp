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
    python build.py --console     # نسخة تشخيص بنافذة سوداء تُظهر أي خطأ
                                  # (gold_erp_debug.exe)
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# ══ جذر المشروع في مسار الاستيراد ══
# `MAKE_EXE.bat` يشغّل `python core\build.py`، فيكون مسار الاستيراد
# الأول هو مجلد core/ لا جذر المشروع — فيفشل `from ui…` في رسم صورة
# شاشة البدء («No module named 'ui'») ويُبنى الـexe **بلا شاشة بدء**.
# وملف onefile يفكّ نفسه ثوانيَ قبل أن يبدأ بايثون، فينقر المستخدم ولا
# يرى شيئاً ويظنّ البرنامج لا يعمل.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
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
    "services.migrations", "services.licensing", "services.storage",
    "services.tenant", "services.cloud_auth", "services.branding",
    "services.sync_queue", "services.auth", "services.audit",
    "ui.backups_dialog", "ui.factory_identity_dialog",
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


def _common_args(onefile, console=False):
    # نسخة التشخيص بنافذة سوداء: أي خطأ يمنع الإقلاع يُقرأ فيها مباشرة
    args = ["--noconfirm", "--clean",
            "--console" if console else "--windowed",
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
        # ══ بطاقةُ تحميلٍ لا شعارٌ منبثق (4.19) ══
        # كان الشعار وحده يظهر فجأةً ثم يختفي فتظهر البوابة — مشهدان
        # بلا رابط. الآن البطاقة تقول ما يجري: الشعار واسم النظام وسطر
        # «جارٍ تشغيل النظام…» وخطٌّ ذهبي كشريط تقدّم. ثم تظهر البوابة
        # من الشفافية حولها وتُغلق البطاقة حين يكتمل المشهد الداكن.
        w, h = 560, 330
        img = QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32_Premultiplied)
        img.fill(QtGui.QColor("#17120C"))
        from ui.widgets.gold_stage import GoldStage
        stage = GoldStage()
        stage.resize(w, h)
        stage.intro = 0.22
        stage.t = 0.6
        stage.logo_center = QtCore.QPointF(w / 2, h * 0.34)
        stage.render(img)
        p = QtGui.QPainter(img)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        # إطارٌ ذهبيٌّ رفيع — بطاقةٌ لها حدود لا صورةٌ سائبة
        p.setPen(QtGui.QPen(QtGui.QColor(201, 162, 39, 150), 1.2))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawRect(QtCore.QRectF(0.6, 0.6, w - 1.2, h - 1.2))
        from ui.gate_window import _emblem
        em = _emblem(118)
        p.drawPixmap(QtCore.QPointF(w / 2 - 59, h * 0.34 - 59), em)
        try:
            from ui import fonts as _f
            fam = _f.load_bundled() or "Segoe UI"
        except Exception:
            fam = "Segoe UI"
        f = QtGui.QFont(fam, 17)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QtGui.QColor("#F6E7B6"))
        p.drawText(QtCore.QRectF(0, h * 0.58, w, 40), QtCore.Qt.AlignCenter,
                   "نظام إدارة مصانع الذهب")
        f2 = QtGui.QFont(fam, 10)
        p.setFont(f2)
        p.setPen(QtGui.QColor("#CDBB8A"))
        p.drawText(QtCore.QRectF(0, h * 0.58 + 40, w, 26),
                   QtCore.Qt.AlignCenter, "جارٍ تشغيل النظام…")
        # شريط التقدّم: مسارٌ خافت وثلثُه ذهبٌ متدرّج
        bw, by = w * 0.46, h * 0.87
        bx = (w - bw) / 2
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(201, 162, 39, 45))
        p.drawRoundedRect(QtCore.QRectF(bx, by, bw, 3), 1.5, 1.5)
        # يمتلئ من اليمين — اتجاه القراءة العربية
        g = QtGui.QLinearGradient(bx + bw, 0, bx + bw * 0.62, 0)
        g.setColorAt(0.0, QtGui.QColor("#F0D98A"))
        g.setColorAt(1.0, QtGui.QColor(201, 162, 39, 0))
        p.setBrush(QtGui.QBrush(g))
        p.drawRoundedRect(QtCore.QRectF(bx + bw * 0.62, by, bw * 0.38, 3),
                          1.5, 1.5)
        p.end()
        _ = QtCore
        out = Path(tempfile.mkdtemp(prefix="jadeite_splash_")) / "splash.png"
        img.save(str(out))
        return out if out.exists() else None
    except Exception as e:                       # noqa: BLE001
        print(f"  [i] تعذّر إعداد شاشة البدء ({e}) — يُبنى بدونها")
        return None


def build_app(onefile=False, console=False):
    print("── بناء التطبيق الرئيسي ──")
    name = APP_NAME + ("_debug" if console else "")
    args = [sys.executable, "-m", "PyInstaller",
            "--name", name] + _common_args(onefile, console)
    for src, dst in DATA:
        p = ROOT / src
        if p.exists():
            args += ["--add-data", f"{p}{_sep()}{dst}"]
    env_file = _bundled_env()
    if env_file:
        args += ["--add-data", f"{env_file}{_sep()}."]
    for h in HIDDEN:
        args += ["--hidden-import", h]
    # الوحدة الجديدة تُضمّ صراحةً — هي التي تُظهر أي عطل إقلاع
    args += ["--hidden-import", "services.crash_guard"]
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
    console = "--console" in sys.argv
    if "--clean" in sys.argv:
        _clean()
    try:
        build_app(onefile, console)
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
    name = APP_NAME + ("_debug" if console else "")
    exe = DIST / (f"{name}.exe" if sys.platform.startswith("win")
                  else name)
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
