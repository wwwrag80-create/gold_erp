# -*- coding: utf-8 -*-
"""محرّك المظهر — لوحة ألوان واحدة ومقاس خط واحد للنظام كله.

**لماذا محرّك لا ملف ألوان**: النمط كان نصاً واحداً بألوان مكتوبة في
مواضعها، فتغيير لونٍ واحد يعني البحث عنه في مئة سطر — ووضعٌ ليليّ
يعني نسخة ثانية من النص كله تتباعد عن الأولى مع كل تعديل.

هنا الشكل مفصول عن اللون: `ui.styles.TEMPLATE` يكتب البنية بأسماء
رمزية (`@ink` · `@surface` · `@gold`)، وهذا الملف يعطي كل اسمٍ قيمته
من لوحة المظهر المختار. فالبنية واحدة والمظاهر تتعدّد بلا تكرار سطر.

**ومقاس الخط**: من يعمل ثماني ساعات على أرقام يحتاج تكبيرها، ومن
يعمل على شاشة صغيرة يحتاج تصغيرها. المقاس معاملُ ضربٍ يمرّ على كل
`font-size` في النمط وعلى خط التطبيق معاً — فتكبر الواجهة كلها
متناسقةً لا الجداول وحدها.

الاختيار يُحفظ في `app_settings` مع بيانات المصنع: يتبع المستخدم
أينما فُتح النظام، ويبقى بعد كل تحديث.
"""
import re

from PyQt5 import QtCore, QtGui

PREF_THEME = "ui_theme"
PREF_SCALE = "ui_font_scale"

# ══════════════════════════════════════════════════════════════════
#  اللوحات
# ------------------------------------------------------------------
#  الأسماء وظيفية لا لونية: `surface` لا «أبيض»، و`ink` لا «أسود» —
#  فالمعنى يبقى صحيحاً في الوضعين، والداكن ليس عكساً آلياً للفاتح بل
#  لوحةٌ مقروءة بذاتها (التباين محسوب، والذهب يبقى ذهباً لا أصفر).
# ══════════════════════════════════════════════════════════════════

LIGHT = {
    # ══ حبرٌ أعمق (4.19) ══ النصّ أسودُ صريح لا رماديٌّ داكن، والرمادي
    # الثانوي والذهبي والأخضر والأحمر كلٌّ درجةٌ أغمق — تباينٌ أعلى
    # على السطح الأبيض فيُقرأ الرقم من بعيد بلا إجهاد. الخلفيات
    # (الأزرار والتظليل) كما هي؛ الذي تغيّر لونُ الكتابة وحده.
    "ink": "#0B0907", "ink2": "#000000", "muted": "#4A443A",
    "bg": "#F7F5F0", "surface": "#FFFFFF", "surface2": "#FAF8F3",
    "hover": "#FBF7EC", "focusBg": "#FFFDF6",
    "line": "#E3DDD0", "line2": "#D6CFC0", "line3": "#C0B79F",
    "grid": "#EDE8DC",
    "gold": "#9A7B22", "goldHi": "#B08E2A", "goldDim": "#5E4A0C",
    "goldSoft": "#F3E9CE", "goldSoft2": "#F7EFD9", "goldSel": "#EFDFAE",
    "goldEdge": "#E0CC8F", "goldEdge2": "#B99B33", "goldBright": "#C9A227",
    "goldRing": "#E4C665", "goldPale": "#F0E0AE",
    "green": "#0F5A24", "red": "#A33131", "redHi": "#BE3C3C",
    "redSoft": "#E2C3C3", "redText": "#9A1414",
    "disBg": "#DED8CB", "disFg": "#7C7566", "disField": "#F2EFE8",
    "barBg": "#2B2723", "barBtn": "#3A342D", "barBtnHi": "#4A4239",
    "barEdge": "#4E463C", "barFg": "#F3EEE2",
    "hdrBg": "#F1ECE0", "hdrFg": "#1E1A14", "hdrLine": "#D8CDB4",
    "hdrLine2": "#E6E0D2",
    "sideItem": "#FCFAF5", "scroll": "#D8D1C2", "scrollHi": "#C0B79F",
    "tipBg": "#2B2723", "tipFg": "#F3EEE2",
    # ══ نبرة الإبراز: صفُّ الإجمالي ولوحتا الرصيد ══
    # كهرمانٌ خافت — يميّز الخلاصة عن التفصيل بلا صراخ.
    # أفتحُ من الذهب وأدفأُ من السطح، فتلتقطه العين أولاً
    # ويبقى النصّ فوقه مقروءاً.
    "sumBg": "#FDF3E2", "sumBg2": "#FAEBD2",
    "sumEdge": "#E6C68A", "sumInk": "#5A3806",
}

DARK = {
    "ink": "#FAF6EE", "ink2": "#FFFFFF", "muted": "#C6BDAB",
    "bg": "#15130F", "surface": "#1E1C17", "surface2": "#232019",
    "hover": "#2A261D", "focusBg": "#241F15",
    "line": "#332E25", "line2": "#3E382C", "line3": "#554D3C",
    "grid": "#2C2820",
    "gold": "#C9A227", "goldHi": "#E0B93E", "goldDim": "#D2AF46",
    "goldSoft": "#3A3120", "goldSoft2": "#332B1C", "goldSel": "#4A3E24",
    "goldEdge": "#6B5A2E", "goldEdge2": "#A98C33", "goldBright": "#E4C665",
    "goldRing": "#E4C665", "goldPale": "#6B5A2E",
    "green": "#72DE91", "red": "#B24A4A", "redHi": "#CC5C5C",
    "redSoft": "#5E3030", "redText": "#FFB3B3",
    "disBg": "#2A2721", "disFg": "#8C8573", "disField": "#201E19",
    "barBg": "#0F0E0B", "barBtn": "#272219", "barBtnHi": "#332E23",
    "barEdge": "#3A3429", "barFg": "#F3EEE2",
    "hdrBg": "#272218", "hdrFg": "#F1E9D7", "hdrLine": "#4E4530",
    "hdrLine2": "#322C21",
    "sideItem": "#1C1A15", "scroll": "#3A3429", "scrollHi": "#554D3C",
    "tipBg": "#3A342A", "tipFg": "#F6F1E6",
    # النبرة نفسها في الداكن: كهرمانٌ معتم لا أصفرُ ساطع
    "sumBg": "#302716", "sumBg2": "#3A2F1B",
    "sumEdge": "#6E5626", "sumInk": "#FFD68C",
}

THEMES = (("light", "☀ فاتح", LIGHT), ("dark", "🌙 ليلي", DARK))

# مقاسات الخط — معامل ضرب على كل حجم في النمط
SCALES = ((0.90, "صغير"), (1.00, "عادي"), (1.12, "كبير"),
          (1.25, "أكبر"), (1.40, "الأكبر"))

_TOKEN = re.compile(r"@([A-Za-z][A-Za-z0-9_]*)")
_FSIZE = re.compile(r"(font-size\s*:\s*)([0-9]+(?:\.[0-9]+)?)\s*(px|pt)")


def palette(name):
    """لوحة المظهر باسمه — والفاتح لأي اسم غير معروف."""
    for key, _label, tk in THEMES:
        if key == name:
            return tk
    return LIGHT


def is_dark(name=None):
    return (name or current_theme()) == "dark"


# ══════════════════════════════════════════════════════════════════
#  التفضيل المحفوظ
# ══════════════════════════════════════════════════════════════════

def current_theme():
    """اسم المظهر المحفوظ — والفاتح إن لم يُختر شيء."""
    try:
        from ui.widgets.common import load_pref
        v = str(load_pref(PREF_THEME, "light")).strip().lower()
        return v if v in {k for k, _l, _t in THEMES} else "light"
    except Exception:
        return "light"


def current_scale():
    """معامل مقاس الخط المحفوظ — ومحصورٌ في المدى المعقول."""
    try:
        from ui.widgets.common import load_pref
        v = float(str(load_pref(PREF_SCALE, "1.0")).strip() or 1.0)
    except Exception:
        return 1.0
    return min(1.6, max(0.8, v))


def set_theme(name, username=None):
    from ui.widgets.common import save_pref
    save_pref(PREF_THEME, str(name), username)


def set_scale(value, username=None):
    from ui.widgets.common import save_pref
    save_pref(PREF_SCALE, f"{float(value):.2f}", username)


# ══════════════════════════════════════════════════════════════════
#  البناء والتطبيق
# ══════════════════════════════════════════════════════════════════

def build(template, tokens, scale=1.0):
    """يستبدل الأسماء الرمزية بألوانها ويضرب كل مقاس خط في المعامل.

    اسمٌ غير معروف يُترك كما هو بدل أن يكسر النمط كله — فخطأ مطبعي
    في لونٍ واحد لا يُفقد النظام هويته البصرية.
    """
    out = _TOKEN.sub(
        lambda m: tokens.get(m.group(1), m.group(0)), template)
    s = float(scale or 1.0)
    if abs(s - 1.0) > 0.001:
        def _fix(m):
            val = float(m.group(2)) * s
            return f"{m.group(1)}{val:.1f}{m.group(3)}"
        out = _FSIZE.sub(_fix, out)
    return out


def apply(app, theme=None, scale=None):
    """يطبّق المظهر والمقاس على التطبيق كله — فوراً وبلا إعادة تشغيل.

    Qt يعيد رسم كل النوافذ المفتوحة عند تغيير ورقة الأنماط، فالتبديل
    يُرى في اللحظة نفسها على كل شاشة ظاهرة.
    """
    from ui import styles
    name = theme or current_theme()
    s = current_scale() if scale is None else float(scale)
    # المقاس الفعّال = اختيار المستخدم × تناسب حجم شاشته. كان تناسب
    # الشاشة يُضبط على خط التطبيق ثم تدهسه ورقة الأنماط بمقاس ثابت،
    # فيذهب أثره كله. ضربهما هنا يجعل الاثنين يعملان معاً.
    try:
        from ui.widgets.table_fit import screen_scale
        s = s * float(screen_scale())
    except Exception:
        pass
    # الخط الحديث حروفُه العربية أكثر تماسكاً من «Segoe UI» بقليل —
    # فيُعوَّض بـ5% ليبقى النصّ بالحجم الذي اعتاده المستخدم أو أكبر
    try:
        from ui import fonts as _fonts
        if _fonts.family() == _fonts.MODERN:
            s *= 1.05
    except Exception:
        pass
    s = min(2.0, max(0.7, s))
    tk = palette(name)
    app.setLayoutDirection(QtCore.Qt.RightToLeft)
    # شكل الأرقام إنجليزي دائماً — تفصيلٌ محاسبي لا تجميلي، شرحه في
    # `services.dates` و`ui.widgets.common.qdstr`.
    QtCore.QLocale.setDefault(
        QtCore.QLocale(QtCore.QLocale.English, QtCore.QLocale.UnitedStates))
    # الخط المرفق (IBM Plex Sans Arabic) أو الكلاسيكي — `ui.fonts`
    try:
        from ui import fonts as _fonts
        fam = _fonts.family()
    except Exception:
        fam = "Segoe UI"
    f = QtGui.QFont(fam, max(7, int(round(10 * s))))
    # الخط الحديث بوزنه **المتوسط** نصّاً عادياً: خطوطُ الحرف أسمك قليلاً
    # فيبدو الأسود أسودَ فعلاً والملوّن أوضح — والعريض يبقى عريضاً
    if fam == getattr(_fonts, "MODERN", ""):
        f.setWeight(QtGui.QFont.Medium)
    # تنعيمٌ كامل للحواف وتلميحٌ خفيف: أوضح على شاشات اليوم
    f.setHintingPreference(QtGui.QFont.PreferNoHinting)
    f.setStyleStrategy(QtGui.QFont.PreferAntialias)
    app.setFont(f)
    app.setStyleSheet(build(styles.TEMPLATE, tk, s))
    # الظلال الناعمة تحت البطاقات (`ui.widgets.effects`) — تُركَّب على
    # ما يظهر من الآن، ويُعاد تلوين ما ظهر بلون المظهر الجديد
    try:
        from ui.widgets import effects
        effects.install(app)
        effects.refresh_all()
    except Exception:
        pass
    # فقرات الشرح تُطوى في الشاشات لتتّسع للجدول (`ui.widgets.declutter`)
    try:
        from ui.widgets import declutter
        declutter.install(app)
    except Exception:
        pass
    return name, s
