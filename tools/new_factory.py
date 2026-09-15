# -*- coding: utf-8 -*-
"""تجهيز نسخة جاهزة للتسليم لمصنع جديد.

يفعل كل شيء بخطوة واحدة:
 1. يولّد هوية فريدة للمصنع (tenant_id).
 2. يسجّله في السحابة (جدول factories).
 3. يُنشئ حساب دخول لصاحب المصنع (كلمة مرور مُجزّأة).
 4. ينسخ النظام نظيفاً بلا بياناتك، ويضع فيه إعداداته.
 5. يضغطه ملفاً واحداً جاهزاً للإرسال.

الاستخدام:
    python tools/new_factory.py
"""
import json
import shutil
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app_config          # noqa: E402
from services.auth import hash_password  # noqa: E402

# ملفات ومجلدات لا تُنسخ للمصنع الجديد (بياناتك وأسرارك)
EXCLUDE = {
    "data", "backups", "dist", "build", "__pycache__",
    ".env", ".setup_done", "config.ini", ".git",
}


def _ask(label, default="", secret=False):
    import getpass
    prompt = f"  {label}" + (f" [{default}]" if default else "") + ": "
    val = (getpass.getpass(prompt) if secret else input(prompt)).strip()
    return val or default


def _post(url, key, path, body, method="POST"):
    req = urllib.request.Request(
        f"{url.rstrip('/')}{path}",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method=method,
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "Prefer": "return=minimal"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status


def register_cloud(url, key, tid, name, username, password):
    """يسجّل المصنع وحساب صاحبه في السحابة."""
    try:
        _post(url, key, "/rest/v1/factories",
              {"tenant_id": tid, "name": name, "is_active": True})
        print(f"  ✔ سُجّل المصنع في السحابة")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print("  ✘ جدول factories غير موجود في السحابة.")
            print("    شغّل أولاً:  SETUP_CLOUD.bat")
            return False
        if e.code in (401, 403):
            print("  ✘ المفتاح غير مصرَّح — تحتاج مفتاح service_role")
            print("    أضفه في .env:  SUPABASE_SERVICE_KEY=...")
            return False
        if e.code == 409:
            print("  ⚠ المصنع مسجّل مسبقاً — سنتابع")
        else:
            print(f"  ✘ خطأ {e.code}")
            return False
    except Exception as e:
        print(f"  ✘ تعذّر الاتصال بالسحابة: {e}")
        return False

    if username and password:
        try:
            _post(url, key, "/rest/v1/factory_users",
                  {"tenant_id": tid, "username": username,
                   "password_hash": hash_password(password),
                   "role": "owner", "is_active": True})
            print(f"  ✔ أُنشئ حساب الدخول: {username}")
        except Exception as e:
            print(f"  ⚠ تعذّر إنشاء الحساب: {e}")
    return True


def build_copy(tid, name, url, key, out_dir):
    """ينسخ النظام نظيفاً ويضع إعدادات المصنع فيه."""
    target = out_dir / "gold_erp"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    for item in ROOT.iterdir():
        if item.name in EXCLUDE:
            continue
        dst = target / item.name
        if item.is_dir():
            shutil.copytree(item, dst,
                            ignore=shutil.ignore_patterns(
                                "__pycache__", "*.pyc"))
        else:
            shutil.copy2(item, dst)

    # مجلدات فارغة للبيانات
    (target / "data").mkdir(exist_ok=True)
    (target / "backups").mkdir(exist_ok=True)

    # إعدادات المصنع: الرابط والمفتاح العام فقط — بلا أسرار
    (target / ".env").write_text(
        "# اعدادات الاتصال السحابي - لا تعدلها\n"
        f"SUPABASE_URL={url}\n"
        f"SUPABASE_PUBLISHABLE_KEY={key}\n",
        encoding="utf-8")

    # هوية المصنع الثابتة
    (target / "data" / "tenant.json").write_text(
        json.dumps({"tenant_id": tid, "factory_name": name,
                    "cloud_url": url, "cloud_key": key,
                    "sync_enabled": True, "sync_interval_sec": 30,
                    "role": "factory", "license_key": ""},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    return target


def build_exe(tid, name, url, key, safe, out_dir):
    """يبني ملفاً تنفيذياً واحداً يحمل هوية المصنع وإعداداته داخله."""
    import subprocess
    import tempfile

    # إعدادات المصنع تُرفق داخل الملف التنفيذي
    stage = Path(tempfile.mkdtemp(prefix="jadeite_"))
    (stage / "data").mkdir(parents=True, exist_ok=True)
    (stage / "data" / "tenant.json").write_text(
        json.dumps({"tenant_id": tid, "factory_name": name,
                    "cloud_url": url, "cloud_key": key,
                    "sync_enabled": True, "sync_interval_sec": 30,
                    "role": "factory", "license_key": ""},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (stage / ".env").write_text(
        f"SUPABASE_URL={url}\nSUPABASE_PUBLISHABLE_KEY={key}\n",
        encoding="utf-8")

    sep = ";" if sys.platform.startswith("win") else ":"
    exe_name = f"gold_erp_{safe}"
    args = ["pyinstaller", "--name", exe_name, "--onefile", "--windowed",
            "--noconfirm", "--clean",
            "--distpath", str(out_dir),
            "--workpath", str(stage / "build"),
            "--specpath", str(stage)]
    icon = ROOT / "assets" / "logo.ico"
    if icon.exists():
        args += ["--icon", str(icon)]
    for src, dst in (("assets", "assets"), ("migrations", "migrations"),
                     ("cloud", "cloud")):
        p = ROOT / src
        if p.exists():
            args += ["--add-data", f"{p}{sep}{dst}"]
    # إعدادات هذا المصنع تحديداً
    args += ["--add-data", f"{stage / 'data'}{sep}data"]
    args += ["--add-data", f"{stage / '.env'}{sep}."]
    for h in ("PyQt5.QtPrintSupport", "PyQt5.QtSvg", "sqlite3",
              "services.migrations", "services.updater_client",
              "services.licensing", "services.cloud_sync",
              "services.tenant", "qrcode", "PIL"):
        args += ["--hidden-import", h]
    args.append(str(ROOT / "main.py"))

    try:
        subprocess.check_call(args)
    except FileNotFoundError:
        print("  ✘ PyInstaller غير مثبَّت — نفّذ: pip install pyinstaller")
        return None
    except subprocess.CalledProcessError as e:
        print(f"  ✘ فشل البناء (رمز {e.returncode})")
        return None
    finally:
        shutil.rmtree(stage, ignore_errors=True)

    for cand in (out_dir / f"{exe_name}.exe", out_dir / exe_name):
        if cand.exists():
            return cand
    return out_dir / f"{exe_name}.exe"


def main():
    print("═" * 56)
    print("  تجهيز نسخة لمصنع جديد")
    print("═" * 56)

    url = app_config.supabase_url()
    key = (app_config.supabase_service_key()
           or app_config.supabase_key())
    pub = app_config.supabase_key()
    if not url or not pub:
        print("  ✘ إعدادات السحابة ناقصة في ملف .env")
        return 1
    print(f"  السحابة: {url}")
    if not app_config.supabase_service_key():
        print("  ⚠ لا يوجد مفتاح service_role — قد يفشل التسجيل.")
        print("    أضفه في .env:  SUPABASE_SERVICE_KEY=...")
    print("-" * 56)

    name = _ask("اسم المصنع")
    if not name:
        print("  ✘ الاسم مطلوب")
        return 1
    username = _ask("اسم مستخدم صاحب المصنع", "admin")
    password = _ask("كلمة المرور", "admin")

    tid = f"F-{uuid.uuid4().hex[:12].upper()}"
    print("-" * 56)
    print(f"  هوية المصنع: {tid}")
    print("-" * 56)

    register_cloud(url, key, tid, name, username, password)

    out = ROOT / "dist" / "factories"
    out.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in name if c.isalnum() or c in " -_")[:30].strip()
    safe = safe.replace(" ", "_") or "factory"

    print("-" * 56)
    print("  جارٍ بناء ملف تنفيذي واحد… (3-10 دقائق)")
    print("-" * 56)
    exe = build_exe(tid, name, url, pub, safe, out)
    if not exe:
        return 1

    print("═" * 56)
    print("  ✔ جاهز للإرسال — ملف تنفيذي واحد:")
    print(f"     {exe}")
    print()
    print("  سلّم صاحب المصنع:")
    print("     الملف أعلاه فقط")
    print(f"     اسم المستخدم : {username}")
    print(f"     كلمة المرور  : {password}")
    print()
    print("  ينقر عليه نقرتين ويدخل — بلا تثبيت ولا فكّ ضغط.")
    print("═" * 56)
    return 0


if __name__ == "__main__":
    sys.exit(main())
