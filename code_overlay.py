# -*- coding: utf-8 -*-
"""تحديث نسخة الـexe بزرّ «⬆ تحديث» — طبقة الكود المحدَّث (4.55).

**المشكلة**: الـexe ملفٌ واحد يحمل الكود في داخله. فحزمة التحديث كانت
تُنسخ إلى مجلد البيانات ولا يقرؤها أحد: يقول البرنامج «اكتمل التحديث»
ثم يعمل بكوده القديم كما هو.

**الحل**: الحزمة تُثبَّت في مجلدٍ مستقل بجوار البيانات
(`<مجلد البيانات>/app_code`). وعند كل تشغيل يسأل الـexe — قبل أن
يستورد أي شاشة — هل في `app_code` إصدارٌ **أحدث** من المدمج فيه؟ إن
كان، قُدِّم مستورِدٌ يقرأ وحدات النظام (models · services · ui …)
من ذلك المجلد قبل النسخة المدمجة. وإلا عمل الـexe بكوده هو.

**ضمانات الإقلاع**:
  · الإصدار يُقارن: ملف exe مبنيّ من كودٍ أحدث يتجاهل طبقةً أقدم منه.
  · عدّاد محاولات: طبقةٌ لم يكتمل بها الإقلاع مرتين متتاليتين تُعطَّل
    تلقائياً (يُعاد تسمية مجلدها) ويعود الـexe إلى كوده المدمج.
  · `boot_ok()` تُصفّر العدّاد حين تظهر بوابة الدخول.

هذا الملف نفسه لا يُستبدل من الطبقة أبداً: هو الذي يقرّر — فيبقى
ثابتاً داخل الـexe كما بُني.
"""
import importlib.abc
import importlib.machinery
import os
import re
import sys
import time
from pathlib import Path

DIRNAME = "app_code"
ENV = "JADEITE_CODE_DIR"
MARK = ".boot_pending"
READY = ".ready"           # مجلد `app_code.new` فُحص وينتظر التبديل
MAX_TRIES = 2
# لا يُقرآن من الطبقة: المُحمِّل نفسه، ونقطة الدخول (تعمل المدمجة)
_SKIP = {"code_overlay", "main"}

STATE = {"active": False, "dir": None, "version": None,
         "embedded": None, "reason": ""}


def frozen():
    return bool(getattr(sys, "frozen", False))


def _vtuple(v):
    out = []
    for part in str(v or "").split("."):
        digits = "".join(c for c in part if c.isdigit())
        out.append(int(digits) if digits else 0)
    while len(out) < 4:
        out.append(0)
    return tuple(out[:4])


def read_version(code_dir):
    """إصدار الكود في المجلد — من `core/config.py` قراءةً لا استيراداً."""
    try:
        txt = (Path(code_dir) / "core" / "config.py").read_text(
            encoding="utf-8")
        m = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', txt, re.M)
        return m.group(1) if m else ""
    except Exception:
        return ""


def names_in(code_dir):
    """أسماء وحدات النظام العليا في المجلد (حزمٌ وملفات)."""
    root = Path(code_dir)
    out = set()
    try:
        for p in root.iterdir():
            if p.is_dir() and (p / "__init__.py").exists():
                out.add(p.name)
            elif p.is_file() and p.suffix == ".py":
                out.add(p.stem)
    except Exception:
        pass
    return out - _SKIP


class _Finder(importlib.abc.MetaPathFinder):
    """يقدّم وحدات النظام من مجلد الطبقة على المدمجة في الـexe.

    يوضع أول `sys.meta_path` فيسبق مستورِد PyInstaller أيّاً كان
    إصداره. وما لا يجده في المجلد يتركه لغيره (يعود `None`).
    """

    def __init__(self, root, names):
        self.root = str(root)
        self.names = frozenset(names)

    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] not in self.names:
            return None
        parts = fullname.split(".")
        search = [os.path.join(self.root, *parts[:-1])]
        spec = importlib.machinery.PathFinder.find_spec(fullname, search)
        if spec is None:
            # وحدةٌ لا يحملها التحديث: تُقرأ من الـexe نفسه. حزمتها الأم
            # صارت من مجلد التحديث، فلا يجدها مستورِد PyInstaller بالمسار
            # إلا إن سُئل عنها في مجلده هو صراحةً.
            mei = getattr(sys, "_MEIPASS", None)
            if mei:
                spec = importlib.machinery.PathFinder.find_spec(
                    fullname, [os.path.join(mei, *parts[:-1])])
        return spec


def _purge(names):
    """يُسقط ما استُورد من المدمج قبل التفعيل (الإعدادات خاصةً)."""
    for mod in list(sys.modules):
        if mod.partition(".")[0] in names:
            sys.modules.pop(mod, None)


def install(code_dir):
    """يفعّل الطبقة من مجلدٍ بعينه — بلا شروط (للفحص وللتشغيل)."""
    code_dir = Path(code_dir).resolve()
    names = names_in(code_dir)
    if not names:
        raise ValueError(f"لا كود في {code_dir}")
    _purge(names)
    sys.meta_path.insert(0, _Finder(code_dir, names))
    importlib.invalidate_caches()
    os.environ[ENV] = str(code_dir)
    STATE.update(active=True, dir=str(code_dir),
                 version=read_version(code_dir))
    return names


def _base_and_version():
    """مجلد البيانات والإصدار المدمج — من إعدادات الـexe نفسه."""
    import core.config as _c                       # المدمج
    return Path(_c.BASE_DIR), str(getattr(_c, "APP_VERSION", "0"))


def code_dir(base=None):
    if base is None:
        base, _v = _base_and_version()
    return Path(base) / DIRNAME


def disable(cdir, why=""):
    """يُعطّل طبقةً لا تُقلع: يُعاد تسمية مجلدها ويُبقى للتشخيص."""
    cdir = Path(cdir)
    try:
        if not cdir.exists():
            return None
        dest = cdir.with_name(
            f"{DIRNAME}_failed_{time.strftime('%Y%m%d_%H%M%S')}")
        cdir.rename(dest)
        try:
            (dest / "WHY.txt").write_text(why or "", encoding="utf-8")
        except Exception:
            pass
        # يُبقى آخر اثنين فقط
        olds = sorted(cdir.parent.glob(f"{DIRNAME}_failed_*"))
        for d in olds[:-2]:
            import shutil
            shutil.rmtree(d, ignore_errors=True)
        return dest
    except Exception:
        return None


def swap_in(base, stamp=None):
    """يبدّل `app_code.new` (المفحوص) بـ`app_code` القائم.

    القائم يُحفظ في `_update_rollback/<الوقت>/app_code` للرجوع إليه.
    """
    base = Path(base)
    live = base / DIRNAME
    new = base / (DIRNAME + ".new")
    if not (new / READY).exists():
        return None
    stamp = stamp or time.strftime("%Y%m%d_%H%M%S")
    snap = None
    if live.exists():
        snap = base / "_update_rollback" / stamp / DIRNAME
        snap.parent.mkdir(parents=True, exist_ok=True)
        live.rename(snap)
    new.rename(live)
    try:
        (live / READY).unlink()
    except Exception:
        pass
    return snap


def activate(count=True):
    """يُستدعى أول الإقلاع: يفعّل الطبقة إن كانت أحدث وسليمة.

    `count=False` للتشخيص (`--about`): لا يُحسب محاولة إقلاع.
    """
    if not frozen() and not os.environ.get("JADEITE_OVERLAY_ANYWAY"):
        STATE["reason"] = "تشغيل من المصدر"
        return None
    try:
        base, emb = _base_and_version()
    except Exception as e:                          # noqa: BLE001
        STATE["reason"] = f"تعذّر قراءة الإعدادات: {e}"
        return None
    STATE["embedded"] = emb
    # تحديثٌ فُحص ولم يُبدَّل (مجلدٌ كان قيد الاستعمال): يُبدَّل الآن
    try:
        swap_in(base)
    except Exception:
        pass
    cdir = code_dir(base)
    if not (cdir / "core" / "config.py").exists():
        STATE["reason"] = "لا تحديث مثبَّت"
        return None
    ver = read_version(cdir)
    if _vtuple(ver) <= _vtuple(emb):
        STATE["reason"] = f"المدمج {emb} ليس أقدم من {ver or '؟'}"
        return None
    mark = cdir / MARK
    try:
        tries = int((mark.read_text(encoding="utf-8") or "0").strip())
    except Exception:
        tries = 0
    if count and tries >= MAX_TRIES:
        disable(cdir, f"لم يكتمل الإقلاع بالإصدار {ver} "
                      f"{tries} مرات متتالية")
        STATE["reason"] = "عُطّل تحديثٌ لم يُقلع"
        return None
    if count:
        try:
            mark.write_text(str(tries + 1), encoding="utf-8")
        except Exception:
            pass
    install(cdir)
    STATE["embedded"] = emb
    return dict(STATE)


def boot_ok():
    """اكتمل الإقلاع بالطبقة — يُصفَّر عدّاد المحاولات."""
    if not STATE["active"]:
        return
    try:
        (Path(STATE["dir"]) / MARK).unlink()
    except Exception:
        pass


def on_fatal(err=""):
    """عطلٌ أوقف الإقلاع والطبقة مفعّلة: تُعطَّل ليعمل المدمج."""
    if not STATE["active"] or not STATE["dir"]:
        return None
    return disable(STATE["dir"], f"عطل عند الإقلاع: {err}")


def verify(cdir, out=print):
    """فحص طبقةٍ قبل اعتمادها — يجري داخل الـexe نفسه.

    1. الترجمة: كل ملف بايثون يُترجم.
    2. الاستيراد: كل وحدةٍ من وحدات النظام تُستورد **من المجلد** بمكتبات
       الـexe — فوحدةٌ تحتاج مكتبةً غير مضمّنة فيه تُكشف هنا لا عند
       العميل.
    """
    cdir = Path(cdir).resolve()
    bad = []
    for p in sorted(cdir.rglob("*.py")):
        try:
            compile(p.read_text(encoding="utf-8-sig"), str(p), "exec")
        except Exception as e:                      # noqa: BLE001
            bad.append(f"ترجمة {p.relative_to(cdir)}: {e}")
    if bad:
        for b in bad:
            out(b)
        return False
    names = install(cdir)
    try:
        from PyQt5 import QtWidgets
        _app = (QtWidgets.QApplication.instance()
                or QtWidgets.QApplication(["verify"]))
        _ = _app
    except Exception as e:                          # noqa: BLE001
        out(f"Qt: {e}")
    mods = []
    for top in sorted(names):
        if top in ("tools",):
            continue
        base = cdir / top
        if base.is_dir():
            for p in sorted(base.rglob("*.py")):
                rel = p.relative_to(cdir).with_suffix("")
                parts = list(rel.parts)
                if parts[-1] == "__init__":
                    parts = parts[:-1]
                mods.append(".".join(parts))
        else:
            mods.append(top)
    n = 0
    for m in mods:
        try:
            mod = importlib.import_module(m)
            f = str(getattr(mod, "__file__", "") or "")
            if f and not f.startswith(str(cdir)):
                bad.append(f"{m}: حُمّل من خارج التحديث ({f})")
            n += 1
        except Exception as e:                      # noqa: BLE001
            bad.append(f"استيراد {m}: {type(e).__name__}: {e}")
    for b in bad:
        out(b)
    out(f"وحدات: {n} · أخطاء: {len(bad)} · الإصدار {read_version(cdir)}")
    return not bad
