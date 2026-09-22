# -*- coding: utf-8 -*-
"""الإعدادات والثوابت العامة لنظام محاسبة مصنع الذهب."""
from pathlib import Path

# ── المسارات ──────────────────────────────────────────────
import os
import sys


def _bundle_dir():
    """مجلد الملفات المرفقة (قراءة فقط).

    في نسخة الملف الواحد (--onefile) يفكّ ويندوز المحتوى في مجلد مؤقت
    يُحذف عند الإغلاق، ويشير إليه `sys._MEIPASS`. لذلك يُستخدم للقراءة
    فقط (الأصول والقوالب) ولا تُحفظ فيه بيانات أبداً.
    """
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        return Path(mei)
    return Path(__file__).resolve().parent


def _persistent_dir():
    """مجلد البيانات الثابت خارج التطبيق — D:/TreeSoft_System/Data
    أو %APPDATA%/TreeSoft. يضمن بقاء البيانات عند تحديث أو حذف الـexe.
    """
    import os as _os
    try:
        if _os.name == "nt":
            d = Path("D:/") / "TreeSoft_System" / "Data"
            try:
                d.mkdir(parents=True, exist_ok=True)
                probe = d / ".probe"
                probe.write_text("x", encoding="utf-8")
                probe.unlink()
                return d
            except Exception:
                base = Path(_os.environ.get("APPDATA") or Path.home())
                d = base / "TreeSoft"
                d.mkdir(parents=True, exist_ok=True)
                return d
        d = Path.home() / ".treesoft"
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        return None


DATA_DIR_ENV = "JADEITE_DATA_DIR"


def _has_database(base):
    """هل في هذا المجلد قاعدة بيانات فعلية؟

    يفحص التخطيطين معاً: الملف القديم المفرد، وملفات المصانع المعزولة
    (`data/tenants/<هوية>/`). وجود مجلد `data` فارغ لا يكفي — الاستنساخ
    النظيف ينشئه فارغاً، فاعتباره «بيانات» يخفي بيانات المستخدم الحقيقية.
    """
    try:
        d = Path(base) / "data"
        if (d / "gold_erp.db").exists():
            return True
        t = d / "tenants"
        return t.is_dir() and any(t.glob("*/gold_erp.db"))
    except Exception:
        return False


def _data_dir():
    """مجلد البيانات **الدائم** — لا يُحذف مع إغلاق التطبيق.

    **مكان واحد للبيانات مهما اختلفت طريقة التشغيل.** كان المجلد يختلف
    باختلاف طريقة الإقلاع: نسخة exe تكتب في `D:/TreeSoft_System/Data`،
    والتشغيل من المصدر يكتب بجوار المشروع. فمن يشغّل النظام بالطريقتين
    يرى محاسبتين منفصلتين ويظن أن بياناته ضاعت — بينما `services.storage`
    ينسخ احتياطياً إلى مسار القرص الدائم في الحالتين، فلا يطابق أيٌّ
    منهما الآخر. الترتيب أدناه يجعل المكان واحداً:

      1. `JADEITE_DATA_DIR` — تجاوز صريح (تشغيل نسخ متعددة، أو اختبار).
      2. نسخة exe → المجلد الدائم على القرص كما كان.
      3. من المصدر وبجواره بيانات فعلية → تُحترم ولا تُهجر.
      4. من المصدر بلا بيانات، وعلى الجهاز بيانات دائمة → تُستعمل،
         فتكفي نسخة جديدة من الكود بلا نقل أي ملف يدوياً.
      5. تثبيت جديد تماماً → مجلد المشروع.
    """
    override = (os.environ.get(DATA_DIR_ENV) or "").strip()
    if override:
        d = Path(override).expanduser()
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return d

    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        d = _persistent_dir()
        if d:
            return d
        base = Path(os.environ.get("LOCALAPPDATA")
                    or os.environ.get("APPDATA") or Path.home())
        d = base / "JadeiteERP"
        d.mkdir(parents=True, exist_ok=True)
        return d
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    # هذا الملف داخل core/ فجذر المشروع أعلاه
    project = Path(__file__).resolve().parent.parent
    if _has_database(project):
        return project
    try:
        persistent = _persistent_dir()
        if persistent and _has_database(persistent):
            return persistent
    except Exception:
        pass
    return project


BUNDLE_DIR = _bundle_dir()      # للقراءة: الأصول والقوالب
BASE_DIR = _data_dir()          # للكتابة: القاعدة والإعدادات والنسخ

def _db_path():
    """مسار قاعدة البيانات — **مستقل لكل مصنع**.

    بلا هوية مصنع نشطة يُستخدم الملف الافتراضي (التهيئة الأولى)،
    وبعد تسجيل الدخول يُوجَّه لملف المصنع وحده فلا يرى بيانات غيره.
    """
    try:
        from services.tenant_db import tenant_db_path
        return tenant_db_path(BASE_DIR)
    except Exception:
        return BASE_DIR / "data" / "gold_erp.db"


class _DBPath:
    """كائن يتصرّف كمسار لكن يُعاد حسابه عند كل استخدام."""

    def _p(self):
        return _db_path()

    def __fspath__(self):
        return str(self._p())

    def __str__(self):
        return str(self._p())

    def __repr__(self):
        return repr(self._p())

    def exists(self):
        return self._p().exists()

    def stat(self):
        return self._p().stat()

    def unlink(self, missing_ok=False):
        return self._p().unlink(missing_ok=missing_ok)

    @property
    def parent(self):
        return self._p().parent

    @property
    def name(self):
        return self._p().name

    def with_name(self, n):
        return self._p().with_name(n)

    def with_suffix(self, sfx):
        return self._p().with_suffix(sfx)

    def read_bytes(self):
        return self._p().read_bytes()


DB_PATH = _DBPath()
BACKUP_DIR = BASE_DIR / "backups"
BARCODE_DIR = BASE_DIR / "data" / "barcodes"
# الأصول (الشعارات والأيقونات) تُقرأ من الحزمة إن وُجدت
ICONS_DIR = (BUNDLE_DIR / "assets" / "icons"
             if (BUNDLE_DIR / "assets" / "icons").exists()
             else BASE_DIR / "assets" / "icons")

APP_NAME = "نظام محاسبة مصنع الذهب — عيار 18"
APP_VERSION = "4.13.0"
# بصمة تتغيّر مع كل بناء — تكشف تشغيل نسخة قديمة فوراً
BUILD_STAMP = "2026-09-22"

# ── الثوابت المحاسبية (من وثيقة المتطلبات SRS) ─────────────
VAT_RATE = 0.15               # ضريبة القيمة المضافة: على الأجور فقط
STONE_DISCOUNT_RATE = 0.50    # نسبة خصم وزن الأحجار الافتراضية
BASE_KARAT = 18               # العيار الأساسي: كل القيود الوزنية بمكافئ 18
KARATS = (18, 21, 22, 24)         # عيارات صناديق الكسر
MELTING_LOSS_LIMIT = 0.015    # الحد المعياري لفاقد الصهر (1.5%) — يصدر تنبيه عند تجاوزه

WEIGHT_DECIMALS = 3           # دقة الأوزان (جرام)
CASH_DECIMALS = 2             # دقة المبالغ (ريال)

# ── بيانات المنشأة (الترويسة الرسمية + QR هيئة الزكاة ZATCA) ──
COMPANY_NAME = "مصنع جاديت للتصنيع"
COMPANY_NAME_EN = "Jadeite Factory"
COMPANY_COUNTRY = "المملكة العربية السعودية"
COMPANY_COUNTRY_EN = "Saudi Arabia, Riyadh"
COMPANY_ADDRESS = "الرياض — صناعية الموسى"
COMPANY_ADDRESS_EN = "Industrial City"
COMPANY_CR = "1010851840"                 # السجل التجاري
COMPANY_VAT_NUMBER = "300000000000003"    # يُعدَّل من شاشة الإعدادات
COMPANY_TAGLINE = "للذهب والمجوهرات"

# ── بوابة الدخول ──
# حركةُ شاشة الترحيب (غبار الذهب · الخواتم الدائرة · التلاشي عند
# فتح النظام). تُطفأ هنا — أو بمتغيّر البيئة `GOLD_ERP_NO_ANIM=1` —
# على الأجهزة الضعيفة أو للتشغيل عبر سطح مكتبٍ بعيد، فيظهر كل شيء
# ساكناً في لحظته بلا أن يتغيّر ترتيبُ خطوةٍ واحدة.
SPLASH_ANIMATION = True

# الشعار والترويسة الرسمية (تُستخدَم في كل قوالب الطباعة)
LOGO_PATH = BUNDLE_DIR / "assets" / "logo.png"
# الشعار الذهبي الشفاف لواجهة النظام (شاشة الترحيب)
LOGO_GOLD_PATH = BUNDLE_DIR / "assets" / "logo_gold.png"
LETTERHEAD_PATH = BASE_DIR / "assets" / "letterhead.png"

# ── النسخ الاحتياطي ───────────────────────────────────────
BACKUP_KEEP_LAST = 30         # عدد النسخ الاحتياطية المحتفظ بها

# الأجر الافتراضي للجرام (قابل للتعديل يدوياً في كل فاتورة)
DEFAULT_WAGE_PER_GRAM = 23.0


# ══════════════════════════════════════════════════════════════════
# اتجاه ترتيب الأعمدة في الطباعة
# ------------------------------------------------------------------
# بعض محركات الطباعة (QTextDocument في بعض الإصدارات) لا تطبّق
# direction: rtl على ترتيب أعمدة الجداول، فتظهر الأعمدة معكوسة
# (اسم المصنع بالعربية يساراً بدل يمينه).
#
#   True  = المحرك يطبّق RTL صحيحاً → تُكتب الأعمدة بترتيبها الطبيعي.
#   False = المحرك يتجاهل RTL → يعكس النظام ترتيب الأعمدة فيزيائياً
#           ليخرج المستند صحيحاً على أي محرك.
#
# إن ظهر المستند مقلوباً بعد الطباعة، بدّل هذه القيمة فقط.
# ══════════════════════════════════════════════════════════════════
PRINT_RTL_ENGINE = False
