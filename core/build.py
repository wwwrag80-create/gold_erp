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
