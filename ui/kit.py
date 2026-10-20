# -*- coding: utf-8 -*-
"""مكتبة الواجهات الحديثة — QFluentWidgets من مدخلٍ واحد (4.69).

**لماذا طبقةٌ لا استيرادٌ مباشر**: الشاشات لا تعرف من أين يأتي الزر.
تطلب `kit.PushButton` و`kit.LineEdit` و`kit.TableWidget`، وهذا الملف
يعطيها مكوّن QFluentWidgets الحديث إن كانت المكتبة مثبّتة، أو مكوّن
Qt الأصلي إن لم تكن. فيبقى النظام يعمل على أي جهاز: نسخة EXE قديمة
بُنيت قبل المكتبة تتلقّى هذا التحديث وتفتح بالشكل الكلاسيكي بلا خطأ،
والنسخة المبنية بالمكتبة تفتح بالمكوّنات الحديثة.

**التوافق**: كل مكوّنٍ هنا **ابنٌ** لصنف Qt الذي حلّ محلّه (`PushButton`
زرٌّ من `QPushButton`، والجدول `QTableWidget`، والحقل `QLineEdit`)،
فكل سطرٍ في الشاشات يعمل كما كان: `setItem` و`text()` و`clicked`.
والقائمة المنسدلة تبقى `QComboBox` بكل واجهتها، وتُبدَّل **قائمتها
المنبثقة** وحدها بقائمة Fluent المتحرّكة.

**الاتجاه العربي**: المكتبة كُتبت لليسار ← اليمين. فما يُرسم بإحداثيات
ثابتة يُصحَّح هنا: زرّا الرقم يسار الخانة والنصّ يمينها، ونصف الدائرة
في الجدول على حافّته الخارجية، وشريط التحديد على يمين السطر.

**الإيقاف**: `GOLD_ERP_UI=classic` في البيئة، أو خيار «الواجهة الحديثة»
في قائمة ⚙ عرض (يُحفظ في `ui_kit.json` بمجلد البيانات، ويُطبّق عند
التشغيل التالي — المكوّنات تُختار مرةً واحدة عند الإقلاع).
"""
import contextlib
import io
import json
import os
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets

ENV = "GOLD_ERP_UI"
PREF_FILE = "ui_kit.json"
LIBRARY = "PyQt-Fluent-Widgets"
LICENSE = "GPLv3 (أو ترخيص تجاري من مؤلّفها)"

# أسماء أزرارٍ لها تصميمٌ خاص في `ui.styles` (لوحات · روابط · شريط)
# فتبقى بشكلها الكلاسيكي — Fluent يعيد رسم الزر العام وحده.
CLASSIC_NAMES = frozenset((
    "dashPanel", "homeRow", "statusLink", "updateReady", "closeBtn",
    "homeBtn", "notesBtn", "goldStripBtn",
))
# حاوياتٌ داكنة أو خاصة: أزرارها بتصميم الشريط لا بتصميم Fluent
CLASSIC_HOSTS = frozenset(("header", "subbar", "goldStrip", "statusbar"))


def _pref_path():
    try:
        import config
        return Path(config.BASE_DIR) / PREF_FILE
    except Exception:
        return None


def preferred():
    """هل اختار المستخدم الواجهة الحديثة؟ (افتراضياً: نعم)."""
    env = (os.environ.get(ENV) or "").strip().lower()
    if env in ("classic", "0", "off", "qt"):
        return False
    if env in ("fluent", "1", "on"):
        return True
    p = _pref_path()
    try:
        if p is not None and p.exists():
            return bool(json.loads(p.read_text("utf-8")).get("fluent", True))
    except Exception:
        pass
    return True


def set_preferred(on):
    """يحفظ الاختيار على هذا الجهاز — يُطبّق عند التشغيل التالي."""
    p = _pref_path()
    if p is None:
        return False
    try:
        p.write_text(json.dumps({"fluent": bool(on)}), "utf-8")
        return True
    except Exception:
        return False


def _load():
    """يستورد المكتبة بهدوء — ويعيد (الوحدة، سبب الغياب)."""
    if not preferred():
        return None, "أُوقفت من الإعدادات"
    try:
        # المكتبة تطبع إعلاناً عند استيرادها؛ لا مكان له في نافذة البرنامج
        with contextlib.redirect_stdout(io.StringIO()):
            import qfluentwidgets as _qf
        return _qf, ""
    except Exception as e:                      # noqa: BLE001
        return None, f"المكتبة غير مثبّتة ({type(e).__name__}: {e})"


qf, REASON = _load()
ACTIVE = qf is not None

# مقاس الخط وألوان المظهر — يضبطها `apply` من `ui.theme`
_STATE = {"scale": 1.0, "dark": False, "translator": None}


def status():
    """حالة المكتبة للعرض في «حول النظام» وأدوات الفحص."""
    return {
        "active": ACTIVE,
        "library": LIBRARY,
        "version": getattr(qf, "__version__", "") if ACTIVE else "",
        "reason": REASON,
        "license": LICENSE,
    }


def _tokens():
    from ui import theme
    return theme.LIGHT, theme.DARK


def _px(size):
    """مقاس خطٍّ بالبكسل مضروباً في معامل الواجهة الحالي."""
    return max(9, int(round(float(size) * _STATE["scale"])))


def _custom(widget, make):
    """ورقة نمطٍ خاصة بالمكوّن للوضعين: `make(لوحة)` ← نصّ QSS.

    تُضاف إلى أوراق المكوّن في مدير المكتبة **بتطبيقٍ واحد** — وتُعاد
    كتابتها وحدها عند تبديل الفاتح/الليلي. (طريقة المكتبة نفسها
    `setCustomStyleSheet` تطبّق الورقة مرتين، مرةً لكل وضع: كلفةٌ تتضاعف
    على مئات الأزرار في صفوف الجداول.)
    """
    if not ACTIVE:
        return
    try:
        _add_sheet(widget, _FnSheet(make))
    except Exception:
        pass


RLM = "\u200f"


def _rtl_text(text):
    """نصّ بندٍ في قائمة: اتجاه فقرته عربي وإن بدأ برقمٍ أو كلمةٍ لاتينية.

    قوائم المكتبة ترسم النصّ بفقرةٍ يسارية؛ فـ«1200 — الذهب المشغول»
    و«تصدير إلى Excel/CSV…» تنقلب أجزاؤها. علامة الاتجاه (RLM) في
    أوله تثبّت الفقرة عربيةً ولا تُرى.
    """
    text = str(text or "")
    if QtWidgets.QApplication.isRightToLeft() and not text.startswith(RLM):
        return RLM + text
    return text


def _rtl(widget):
    try:
        return widget.layoutDirection() == QtCore.Qt.RightToLeft
    except Exception:
        return True


def _field_height(widget, extra=14):
    """ارتفاع الخانة من قياس خطّها — لا 33 بكسلاً ثابتة.

    Fluent يثبّت الخانة على 33: يكفي خطاً بحجم 14، ويقصّ خطّ النظام
    المكبَّر (16 بكسلاً فأكثر). فيُشتقّ من الخط الفعلي بعد تطبيق النمط.

    والقياس عند «تهيئة» الخانة لا عند إنشائها (4.71): فرض التهيئة مبكراً
    يجعل كل نقلٍ لاحق للشاشة أثناء بنائها يعيد أنماط الخانة كلها.
    """
    if ACTIVE:
        _after_polish(widget, lambda w: _measure_field(w, extra))
        return None
    widget.ensurePolished()
    return _measure_field(widget, extra)


def _measure_field(widget, extra):
    try:
        fm = QtGui.QFontMetrics(widget.font())
        h = max(33, fm.height() + extra)
    except Exception:
        h = 36
    widget.setMinimumHeight(h)
    widget.setMaximumHeight(16777215)
    return h


# ══════════════════════════════════════════════════════════════════
#  المظهر: لون الذهب والخط والوضع الليلي
# ══════════════════════════════════════════════════════════════════

# أيام التقويم وأشهره بالعربية — لا يحملها ملف ترجمة المكتبة العربي.
# تُكتب على عناصر التقويم مباشرةً بعد إنشائه (`_arabize_calendar`):
# مترجمٌ بايثوني (QTranslator مشتقّ) يستدعيه Qt من داخل بنائه للنوافذ
# كان يُسقط البرنامج في بعض الشاشات — فلا مترجم بايثوني إطلاقاً.
AR_CALENDAR = {
    "Mo": "ن", "Tu": "ث", "We": "ر", "Th": "خ", "Fr": "ج", "Sa": "س",
    "Su": "ح",
    "Jan": "يناير", "Feb": "فبراير", "Mar": "مارس", "Apr": "أبريل",
    "May": "مايو", "Jun": "يونيو", "Jul": "يوليو", "Aug": "أغسطس",
    "Sep": "سبتمبر", "Oct": "أكتوبر", "Nov": "نوفمبر", "Dec": "ديسمبر",
}


def _arabize_calendar(view):
    """أيام الأسبوع وأسماء الأشهر في تقويم Fluent بالعربية."""
    for lb in view.findChildren(QtWidgets.QLabel, "weekDayLabel"):
        lb.setText(AR_CALENDAR.get(lb.text(), lb.text()))
    for lw in view.findChildren(QtWidgets.QListWidget):
        for i in range(lw.count()):
            it = lw.item(i)
            ar = AR_CALENDAR.get(it.text())
            if ar:
                it.setText(ar)


# لون الفعل في Fluent: الوضع الفاتح يأخذه كما هو، والليلي يشتقّ منه
# درجةً أفتح — فيُعطى ذهباً أعمق لتخرج الدرجة المشتقّة ذهباً لا أصفر.
THEME_GOLD = {"light": "#9A7B22", "dark": "#B08E2A"}


def _refresh_roots():
    """تُستبدل بالفعلية حين تتوفّر المكتبة."""


def install_root(widget):
    """النافذة تحمل أوراق المكتبة لكل ما فيها — بلا عمل في الوضع الكلاسيكي."""


def apply(app, name="light", scale=1.0):
    """يزامن Fluent مع مظهر النظام — يُستدعى من `ui.theme.apply`."""
    _STATE["scale"] = float(scale or 1.0)
    _STATE["dark"] = name == "dark"
    if not ACTIVE:
        return False
    try:
        from ui import fonts as _fonts
        fam = _fonts.family()
    except Exception:
        fam = "Segoe UI"
    try:
        qf.setFontFamilies([fam, "Segoe UI", "Tahoma"])
        qf.setTheme(qf.Theme.DARK if _STATE["dark"] else qf.Theme.LIGHT,
                    lazy=True)
        qf.setThemeColor(THEME_GOLD["dark" if _STATE["dark"] else "light"],
                         lazy=True)
        _refresh_roots()            # أوراق المكتبة على النوافذ بالوضع الجديد
        RowDelegate._INK.clear()    # حبر الجداول المحفوظ يُقرأ من جديد
    except Exception:
        return False
    # نصوص المكتبة الداخلية بالعربية (قص · نسخ · لصق · موافق · إلغاء)
    if _STATE["translator"] is None and app is not None:
        # **تركيب مترجمٍ يقلب اتجاه النظام كلّه**: Qt 5 يعيد ضبط اتجاه
        # التطبيق مع كل تغيير لغة من نصٍّ في المترجم نفسه، وملف المكتبة
        # لا يحمله — فكانت الواجهة كلها تنقلب يساراً ← يميناً. فيُحفظ
        # الاتجاه قبل التركيب ويُعاد بعده.
        direction = app.layoutDirection()
        try:
            tr = QtCore.QTranslator(app)
            if tr.load(":/qfluentwidgets/i18n/qfluentwidgets.ar_AR.qm"):
                app.installTranslator(tr)
                _STATE["translator"] = tr
        except Exception:
            pass
        app.setLayoutDirection(direction)
    return True


def icon(name):
    """أيقونة Fluent باسمها (PRINT · SYNC · SAVE …) أو أيقونة فارغة."""
    if ACTIVE:
        try:
            return getattr(qf.FluentIcon, str(name).upper()).icon()
        except Exception:
            pass
    return QtGui.QIcon()


# ══════════════════════════════════════════════════════════════════
#  المكوّنات
# ══════════════════════════════════════════════════════════════════

if ACTIVE:
    from qfluentwidgets.common import style_sheet as _ss
    from qfluentwidgets.common.style_sheet import StyleSheetBase as _SheetBase

    class _FnSheet(_SheetBase):
        """ورقةٌ تُبنى من لوحة النظام للوضع الجاري (فاتح/ليلي)."""

        def __init__(self, make):
            self.make = make
            # ورقةٌ تحمل النافذةُ نسختها المحصورة (4.71) — تُترك لها هناك
            self.root = getattr(make, "kit_root", None)

        def content(self, theme=None):
            if theme is None or theme == qf.Theme.AUTO:
                dark = qf.isDarkTheme()
            else:
                dark = theme == qf.Theme.DARK
            light, darkp = _tokens()
            return self.make(darkp if dark else light)

    def _add_sheet(widget, sheet):
        _ss.addStyleSheet(widget, sheet)

    # ══ سرعة: المكتبة تقرأ ملف النمط وتعيد تصييره مع **كل** مكوّن ══
    # ملفّاتها ثابتة، وتصييرها دالّةٌ في (النصّ، لون الذهب، الخط، الوضع)
    # — فيُحفظ الناتج ويُعاد. مئات الأزرار في جدولٍ واحد كانت تقرأ الملف
    # نفسه وتصيّره مئات المرات.
    _FILE_CACHE, _RENDER_CACHE = {}, {}
    _orig_file, _orig_render = _ss.getStyleSheetFromFile, _ss.renderQss

    def _cached_file(file):
        if isinstance(file, str):
            v = _FILE_CACHE.get(file)
            if v is None:
                v = _FILE_CACHE[file] = _orig_file(file)
            return v
        return _orig_file(file)

    def _cached_render(qss):
        try:
            cfg = _ss.qconfig
            key = (qss, cfg.get(cfg.themeColor).name(),
                   tuple(cfg.get(cfg.fontFamilies)), qf.isDarkTheme())
        except Exception:
            return _orig_render(qss)
        v = _RENDER_CACHE.get(key)
        if v is None:
            if len(_RENDER_CACHE) > 512:
                _RENDER_CACHE.clear()
            v = _RENDER_CACHE[key] = _orig_render(qss)
        return v

    _ss.getStyleSheetFromFile = _cached_file
    _ss.renderQss = _cached_render

    # ══ سرعة الفتح (4.71): ورقة كل مكوّن تُطبَّق عند ظهوره الأول ══
    # كل مكوّنٍ من المكتبة يحمل ورقة نمطٍ خاصّة به. وQt حين يُنقل فرعٌ
    # من الواجهة إلى أبٍ جديد (الشاشة إلى حاضنها، ثم إلى تبويب، ثم إلى
    # منطقة التمرير…) **يعيد قراءة ورقة كل مكوّنٍ فيه وتطبيقها** — وتُبنى
    # الشاشة وتُنقل أربع مرّاتٍ أو خمساً قبل أن تُرى. فكان فتح الشاشة
    # أبطأ بمرّتين ونصف مما كان قبل المكتبة.
    # الآن: المكوّن الذي لم يظهر بعد تُحفظ ورقته جانباً، وتُطبَّق مرّةً
    # واحدة عند «تهيئته» (QEvent.Polish) — وهي تجري عند الظهور الأول،
    # بعد أن استقرّ في مكانه، وقبل حساب التخطيط والرسم. فالمظهر نفسه،
    # والنقل أثناء البناء صار بلا كلفة.
    _ROOT_KEY = "kitFluentRoot"
    _PENDING = object()             # ورقةٌ تُحسب عند التهيئة من مصادرها

    # ══ أوراق المكتبة على النافذة مرةً واحدة (4.71) ══
    # أوراق هذه المكوّنات محدِّداتها **أسماء أصنافها هي** (`LineEdit` ·
    # `PushButton` · `SpinBox` …) فلا تمسّ غيرها: تُضمّ في ورقةٍ واحدة على
    # النافذة الرئيسية، فيقرؤها Qt مرةً ويطبّقها بفهرسه على كل مكوّن.
    # ورقة النافذة تغلب ورقة التطبيق كما كانت ورقة المكوّن تغلبها — فلا
    # يتغيّر شيءٌ في المظهر. وما فيها محدِّداتٌ عامّة (`QLabel` في الرسائل،
    # `QHeaderView` في الجداول …) يبقى على مكوّنه وحده.
    # (ورقة الأزرار تبقى على كل زرّ — مقصورةً على صنفه: أزرارٌ كثيرة تُعاد
    # عمداً لنمط النظام الكلاسيكي، وورقة النافذة كانت ستصلها. وورقة القوائم
    # المنسدلة لا تُضمّ: قائمتنا `QComboBox` بنمط النظام واسمها `ComboBox`
    # كاسم صنف المكتبة الذي تخاطبه تلك الورقة)
    _ROOT_SOURCES = tuple(getattr(qf.FluentStyleSheet, n) for n in (
        "LINE_EDIT", "SPIN_BOX", "CHECK_BOX", "MENU")
        if hasattr(qf.FluentStyleSheet, n))
    _ROOTS = []

    _TABLES = ("TableWidget", "TableView")
    _SPINS = ("SpinBox", "DoubleSpinBox", "DateEdit")

    def _scope(qss, owners, head):
        """قواعد ورقةٍ صُمّمت لمكوّنٍ واحد تُحصر في أصنافه على النافذة:
        محدِّدٌ يبدأ بصنف المكوّن (`head`) يُبدَّل باسم الصنف، وما سواه
        (أبناؤه: الرأس · زرّ التقويم …) يُحصر داخله — والترتيب كما هو."""
        text = _re.sub(r"/\*.*?\*/", "", qss or "", flags=_re.S)
        out = []
        for m in _RULE.finditer(text):
            sels = []
            for sel in m.group(1).split(","):
                sel = sel.strip()
                if not sel:
                    continue
                rest = sel[len(head):]
                own = sel.startswith(head) and not rest[:1].isalnum()
                for o in owners:
                    sels.append(o + rest if own else f"{o} {sel}")
            if sels:
                out.append(", ".join(sels) + " {" + m.group(2) + "}")
        return "\n".join(out)

    def _root_extra():
        light, darkp = _tokens()
        t = darkp if qf.isDarkTheme() else light
        parts = [
            _scope(_ss.getStyleSheet(qf.FluentStyleSheet.TABLE_VIEW),
                   _TABLES, "QTableView"),
            _scope(_ss.getStyleSheet(_Part(_header_qss(t))),
                   _TABLES, "QTableView"),
        ]
        app = QtWidgets.QApplication.instance()
        if app is None or app.layoutDirection() == QtCore.Qt.RightToLeft:
            parts.append(_scope(_ss.getStyleSheet(_Part(_spin_rtl_qss(True)(t))),
                                _SPINS, "QAbstractSpinBox"))
            parts.append(_scope(_ss.getStyleSheet(_Part(_date_qss(True)(t))),
                                ("DateEdit",), "QAbstractSpinBox"))
        return "\n".join(parts)

    def _root_qss():
        base = "\n".join(_ss.getStyleSheet(src) for src in _ROOT_SOURCES)
        return base + "\n" + _root_extra()

    def install_root(widget):
        """يجعل النافذة حاملةً أوراق المكتبة لكل ما فيها."""
        import weakref
        widget.setProperty(_ROOT_KEY, True)
        _ROOTS.append(weakref.ref(widget))
        QtWidgets.QWidget.setStyleSheet(widget, _root_qss())

    def _refresh_roots():
        alive = []
        qss = None
        for ref in _ROOTS:
            w = ref()
            if w is None:
                continue
            try:
                if qss is None:
                    qss = _root_qss()
                QtWidgets.QWidget.setStyleSheet(w, qss)
                alive.append(ref)
            except RuntimeError:
                pass
        _ROOTS[:] = alive

    def _under_root(widget):
        w = widget
        while w is not None:
            if w.property(_ROOT_KEY):
                return True
            w = w.parentWidget()
        return False

    # ── ورقة المكتبة مقصورةً على ما يخصّ المكوّن ──
    # ورقة الأزرار وحدها 7.5 ك.ب لعشرين صنفاً من الأزرار؛ الزرّ الواحد
    # يحتاج قواعد صنفه وآبائه. تُحذف القواعد التي لا يُطابق محدِّدٌ فيها
    # المكوّن ولا أحداً من أبنائه، بترتيبها وثقلها كما هي.
    import re as _re
    _RULE = _re.compile(r"([^{}]+)\{([^{}]*)\}")
    _HEAD = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]*")
    _FILTERED = {}

    def _names(widget):
        out = set()
        mo = widget.metaObject()
        while mo is not None:
            out.add(mo.className())
            mo = mo.superClass()
        for ch in widget.findChildren(QtWidgets.QWidget):
            out.add(ch.metaObject().className())
        return out

    def _filtered_content(source, names, theme):
        key = (source, theme, qf.isDarkTheme(), frozenset(names))
        v = _FILTERED.get(key)
        if v is None:
            text = _re.sub(r"/\*.*?\*/", "", source.content(theme), flags=_re.S)
            keep = []
            for m in _RULE.finditer(text):
                for sel in m.group(1).split(","):
                    head = _HEAD.match(sel.strip())
                    if head is None or head.group(0) in names:
                        keep.append(m.group(0))
                        break
            if len(_FILTERED) > 256:
                _FILTERED.clear()
            v = _FILTERED[key] = "\n".join(keep)
        return v

    class _Part(_SheetBase):
        def __init__(self, text):
            self.text = text

        def content(self, theme=None):
            return self.text

    def _effective_qss(widget, theme=qf.Theme.AUTO):
        """ورقة المكوّن من مصادره: ما تحمله النافذة يُترك لها، وأوراق
        المكتبة الباقية مقصورةٌ على صنفه، وأوراقنا المخصّصة كما هي."""
        compose = _ss.styleSheetManager.source(widget)
        if compose is None:
            return None
        root = _under_root(widget)
        names = None
        parts = []
        for src in list(compose.sources):
            if root and (src in _ROOT_SOURCES
                         or src is qf.FluentStyleSheet.TABLE_VIEW
                         or getattr(src, "root", None)):
                continue
            if isinstance(src, qf.FluentStyleSheet):
                if names is None:
                    names = _names(widget)
                parts.append(_ss.getStyleSheet(
                    _Part(_filtered_content(src, names, theme))))
            else:
                parts.append(_ss.getStyleSheet(src, theme))
        return "\n".join(p for p in parts if p and p.strip())

    def _set_now(widget, qss):
        if (qss or "").rstrip() != widget.styleSheet().rstrip():
            QtWidgets.QWidget.setStyleSheet(widget, qss or "")

    class _Polisher(QtCore.QObject):
        def eventFilter(self, obj, e):
            if e.type() == QtCore.QEvent.Polish:
                obj.removeEventFilter(self)
                obj.__dict__.pop("_kit_hooked", None)
                mark = obj.__dict__.pop("_kit_qss", None)
                if mark is _PENDING:
                    qss = _effective_qss(obj)
                    if qss is not None:
                        _set_now(obj, qss)
                elif isinstance(mark, str):
                    _set_now(obj, mark)
                fns = obj.__dict__.pop("_kit_polish_fns", None)
                if fns:
                    # الخط من الأوراق يُطبَّق في التهيئة نفسها — قبل القياس
                    obj.style().polish(obj)
                    for fn in fns:
                        try:
                            fn(obj)
                        except Exception:
                            pass
            return False

    _POLISHER = _Polisher()

    def _hook(widget):
        # علامةٌ في بايثون لا خاصيةٌ في Qt: الخاصية تولّد حدثاً، وأزرار
        # المكتبة تعيد تعريف `setProperty` في بايثون
        if not widget.__dict__.get("_kit_hooked"):
            widget.__dict__["_kit_hooked"] = True
            widget.installEventFilter(_POLISHER)

    def _after_polish(widget, fn):
        """يُنفَّذ `fn(widget)` عند تهيئة المكوّن — أو الآن إن كان قد تهيّأ."""
        if widget.testAttribute(QtCore.Qt.WA_WState_Polished):
            fn(widget)
            return
        widget.__dict__.setdefault("_kit_polish_fns", []).append(fn)
        _hook(widget)

    def _current_qss(widget):
        mark = widget.__dict__.get("_kit_qss")
        if mark is _PENDING:
            return _effective_qss(widget) or ""
        return mark if isinstance(mark, str) else widget.styleSheet()

    def _apply_sources(widget, theme=qf.Theme.AUTO):
        """يطبّق ورقة المكوّن من مصادره الآن إن كان قد تهيّأ، وإلا عند تهيئته."""
        if widget.testAttribute(QtCore.Qt.WA_WState_Polished):
            qss = _effective_qss(widget, theme)
            if qss is not None:
                _set_now(widget, qss)
            return
        _hook(widget)
        widget.__dict__["_kit_qss"] = _PENDING

    def _lazy_set(widget, source, theme=qf.Theme.AUTO, register=True):
        if register:
            _ss.styleSheetManager.register(source, widget)
            _apply_sources(widget, theme)
            return
        qss = _ss.getStyleSheet(source, theme)
        if widget.testAttribute(QtCore.Qt.WA_WState_Polished):
            _set_now(widget, qss)
        else:
            _hook(widget)
            widget.__dict__["_kit_qss"] = qss

    def _lazy_add(widget, source, theme=qf.Theme.AUTO, register=True):
        if register:
            _ss.styleSheetManager.register(source, widget, reset=False)
            _apply_sources(widget, theme)
            return
        qss = _current_qss(widget) + "\n" + _ss.getStyleSheet(source, theme)
        if widget.testAttribute(QtCore.Qt.WA_WState_Polished):
            _set_now(widget, qss)
        else:
            _hook(widget)
            widget.__dict__["_kit_qss"] = qss

    # الدالّتان اللتان تمرّ بهما كل أوراق المكتبة (`FluentStyleSheet.X.apply`
    # وأوراقنا المخصّصة) — تُستبدلان في وحدتها فيصل التأجيل إلى الجميع
    _ss.setStyleSheet = _lazy_set
    _ss.addStyleSheet = _lazy_add

    # ── مراقبٌ واحد لكل مكوّن بدل اثنين ──
    # المكتبة تركّب على كل مكوّنٍ مراقبَين في بايثون (ورقته المخصّصة ·
    # ورقته المؤجّلة عند تبديل الوضع)، وكلاهما يُستدعى مع **كل حدث** يصل
    # المكوّن. مراقبٌ واحد يقوم بالعملين.
    _CUSTOM_KEYS = (_ss.CustomStyleSheet.LIGHT_QSS_KEY,
                    _ss.CustomStyleSheet.DARK_QSS_KEY)

    class _Watcher(QtCore.QObject):
        def eventFilter(self, obj, e):
            t = e.type()
            if t == QtCore.QEvent.DynamicPropertyChange:
                if bytes(e.propertyName()).decode() in _CUSTOM_KEYS:
                    _apply_sources(obj)
            elif t == QtCore.QEvent.Paint and obj.property("dirty-qss"):
                obj.setProperty("dirty-qss", False)
                if obj in _ss.styleSheetManager.widgets:
                    _apply_sources(obj)
            return False

    _WATCHER = _Watcher()

    def _register(self, source, widget, reset=True):
        if isinstance(source, str):
            source = _ss.StyleSheetFile(source)
        if widget not in self.widgets:
            widget.destroyed.connect(lambda: self.deregister(widget))
            widget.installEventFilter(_WATCHER)
            self.widgets[widget] = _ss.StyleSheetCompose(
                [source, _ss.CustomStyleSheet(widget)])
        if not reset:
            self.source(widget).add(source)
        else:
            self.widgets[widget] = _ss.StyleSheetCompose(
                [source, _ss.CustomStyleSheet(widget)])

    _ss.StyleSheetManager.register = _register

    from qfluentwidgets.components.widgets.table_view import (
        TableItemDelegate as _FluentDelegate)
    # تهيئة خيار الخلية في المكتبة (خطٌّ 13 بكسلاً ولون نصٍّ ثابت) نستبدلها
    # في كل جداولنا — وبقاؤها دالّةَ بايثون على الصنف يجعل Qt يمرّ ببايثون
    # في قياس كل خلية. فتُرفع عنه، وتبقى لقوائم المكتبة التي ترثها (4.71)
    try:
        from qfluentwidgets.components.widgets.list_view import (
            ListItemDelegate as _ListDelegate)
        _fi = _FluentDelegate.__dict__.get("initStyleOption")
        if _fi is not None:
            if "initStyleOption" not in _ListDelegate.__dict__:
                _ListDelegate.initStyleOption = _fi
            del _FluentDelegate.initStyleOption
    except Exception:
        pass
    from qfluentwidgets.components.widgets.menu import (
        MenuAnimationType as _MenuAni)
    from qfluentwidgets.components.widgets.combo_box import (
        ComboBoxMenu as _ComboMenu)
    from qfluentwidgets.common.style_sheet import (
        styleSheetManager as _qss_manager)
    from qfluentwidgets.components.widgets.menu import (
        IndicatorMenuItemDelegate as _IndicatorDelegate,
        MenuItemDelegate as _MenuItemDelegate)

    class _RtlIndicatorDelegate(_IndicatorDelegate):
        """شريط البند المختار على يمين القائمة بالعربية لا يسارها."""

        def paint(self, painter, option, index):
            view = self.parent()
            if view is None or not view.isRightToLeft():
                return super().paint(painter, option, index)
            _MenuItemDelegate.paint(self, painter, option, index)
            if not option.state & QtWidgets.QStyle.State_Selected:
                return
            painter.save()
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(qf.themeColor())
            painter.drawRoundedRect(
                QtCore.QRectF(option.rect.right() - 9, 11 + option.rect.y(),
                              3, 15), 1.5, 1.5)
            painter.restore()

    def _rtl_menu(menu, indicator=False):
        """قائمة Fluent باتجاه النظام: النصّ والأيقونة من اليمين."""
        d = QtWidgets.QApplication.layoutDirection()
        menu.setLayoutDirection(d)
        try:
            menu.view.setLayoutDirection(d)
            if indicator:
                menu.view.setItemDelegate(_RtlIndicatorDelegate(menu.view))
        except Exception:
            pass
        return menu

    def _ghost_qss(t):
        return f"""
        QPushButton {{ color: {t['ink']}; background: {t['surface']};
            border: 1px solid {t['line2']}; border-bottom: 1px solid {t['line3']};
            border-radius: 6px; }}
        QPushButton:hover {{ background: {t['hover']}; border-color: {t['line3']}; }}
        QPushButton:pressed {{ background: {t['goldSoft2']}; color: {t['muted']}; }}
        QPushButton:disabled {{ color: {t['disFg']}; background: {t['disField']};
            border: 1px solid {t['line']}; }}"""

    def _primary_dark_qss(t):
        # Fluent يرفع لون الفعل في الوضع الليلي إلى أقصى سطوعه فيخرج
        # الذهب أصفرَ فاقعاً على الأسطح الكبيرة — فيُعطى ذهب لوحة النظام
        return f"""
        QPushButton {{ color: #1A1305; background-color: {t['gold']};
            border: 1px solid {t['goldHi']}; border-bottom: 1px solid #7A5F14;
            border-radius: 6px; }}
        QPushButton:hover {{ background-color: {t['goldHi']}; }}
        QPushButton:pressed {{ background-color: #A8861F;
            color: rgba(26,19,5,0.75); }}
        QPushButton:disabled {{ color: {t['disFg']}; background-color: {t['disBg']};
            border: 1px solid {t['line2']}; }}"""

    def _primary_qss(t):
        # الفاتح يبقى ذهب Fluent نفسه (لون الفعل = ذهب النظام)؛ والليلي يُصحَّح
        return _primary_dark_qss(t) if t is _tokens()[1] else ""

    def _danger_qss(t):
        return f"""
        QPushButton {{ color: #FFFFFF; background: {t['red']};
            border: 1px solid {t['redHi']}; border-bottom: 1px solid #6E1F1F;
            border-radius: 6px; }}
        QPushButton:hover {{ background: {t['redHi']}; }}
        QPushButton:pressed {{ background: #7E2424; color: rgba(255,255,255,0.75); }}"""

    class PushButton(qf.PrimaryPushButton):
        """زرّ Fluent يقرأ دوره من اسمه كما كان النمط يقرؤه.

        بلا اسم ⇒ زرّ الفعل الأساسي (ذهبيّ ممتلئ). `ghost` ⇒ الزرّ
        الثانوي المحدّد بإطار. `danger` ⇒ الحذف والإلغاء بالأحمر. وأزرار
        التصاميم الخاصة (لوحات لوحة التحكم · الشريط الداكن) تُعاد إلى
        نمطها الكلاسيكي فلا يكسرها الزرّ الجديد.
        """

        # الدور يُقرأ من الاسم ويُطبَّق **مرةً واحدة عند أول ظهور**: الشاشات
        # تسمّي الزرّ بعد إنشائه، وتطبيق النمط مع كل خطوةٍ كان يضاعف
        # كلفة الزرّ أربع مرات
        _SHEETS = {"ghost": _ghost_qss, "danger": _danger_qss,
                   "primary": _primary_qss}

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._kit_done = None
            self._kit_resolved = False
            self.setCursor(QtCore.Qt.PointingHandCursor)
            self._kit_kind = self._kit_kind_of(self.objectName())

        @staticmethod
        def _kit_kind_of(name):
            name = str(name or "")
            if name in CLASSIC_NAMES:
                return "classic"
            if name == "ghost":
                return "ghost"
            if name in ("danger", "dangerBtn"):
                return "danger"
            return "primary"

        def setObjectName(self, name):
            super().setObjectName(name)
            self._kit_kind = self._kit_kind_of(name)
            if self.isVisible():
                self._kit_style()

        def _kit_style(self):
            kind = self._kit_kind
            if kind == self._kit_done:
                return
            if self._kit_done is not None and kind != "classic":
                # تغيّر الدور بعد الظهور (نادر): يُعاد بناء الأوراق من الأصل
                qf.setStyleSheet(self, qf.FluentStyleSheet.BUTTON)
            self._kit_done = kind
            if kind == "classic":
                self._kit_detach()
                return
            _custom(self, self._SHEETS[kind])

        def _kit_detach(self):
            """يعيد الزرّ لنمط النظام وحده — خارج تحديثات Fluent."""
            try:
                _qss_manager.deregister(self)
            except Exception:
                pass
            QtWidgets.QPushButton.setStyleSheet(self, "")

        def showEvent(self, e):
            # زرٌّ داخل الشريط الداكن أو شريط السعر: لا يُعرف مكانه إلا
            # بعد أن يوضع — فيُفحص عند أول ظهور
            if not self._kit_resolved:
                self._kit_resolved = True
                w = self.parentWidget()
                while w is not None:
                    if w.objectName() in CLASSIC_HOSTS:
                        self._kit_kind = "classic"
                        break
                    w = w.parentWidget()
            self._kit_style()
            super().showEvent(e)

    class _RtlTextMargins:
        """أزرار الخانة (مسح · بحث · إظهار) في طرفها **الأيسر** بالعربية،
        فهامش النصّ يُترك هناك لا على اليمين كما تفترض المكتبة.

        المكتبة تضبط الهامش من مواضع كثيرة (`setClearButtonEnabled` في
        خانة البحث وكلمة المرور، و`_adjustTextMargins`) — فيُعكس عند
        المصبّ الواحد: `setTextMargins`.
        """

        def setTextMargins(self, *args):
            if len(args) == 1:
                m = args[0]
                left, top, right, bottom = (m.left(), m.top(), m.right(),
                                            m.bottom())
            else:
                left, top, right, bottom = args
            if _rtl(self):
                left, right = right, left
            QtWidgets.QLineEdit.setTextMargins(self, left, top, right, bottom)

    def _edit_menu(widget, pos):
        """قائمة التحرير بالعربية وأيقونات Fluent."""
        from qfluentwidgets.components.widgets.menu import LineEditMenu
        try:
            LineEditMenu(widget).exec_(pos)
        except Exception:
            m = widget.createStandardContextMenu()
            m.exec_(pos)

    class LineEdit(_RtlTextMargins, qf.LineEdit):
        """حقل Fluent: خطٌّ ذهبيٌّ أسفله عند التركيز، وزرّ مسحٍ عند الطلب.

        الإكمال التلقائي يبقى إكمال Qt نفسه (`QCompleter`): الشاشات
        تبني عليه منطق الاختيار، فلا يُستبدل بقائمة لا تعرفه.
        """

        def __init__(self, *args, **kwargs):
            text = None
            if args and isinstance(args[0], str):
                text, args = args[0], args[1:]
            super().__init__(*args, **kwargs)
            _field_height(self)
            if text:
                self.setText(text)

        def setCompleter(self, completer):
            QtWidgets.QLineEdit.setCompleter(self, completer)

        def completer(self):
            return QtWidgets.QLineEdit.completer(self)

        def contextMenuEvent(self, e):
            _edit_menu(self, e.globalPos())

    class SearchLineEdit(_RtlTextMargins, qf.SearchLineEdit):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            _field_height(self)

        def setCompleter(self, completer):
            QtWidgets.QLineEdit.setCompleter(self, completer)

        def completer(self):
            return QtWidgets.QLineEdit.completer(self)

    class PasswordLineEdit(_RtlTextMargins, qf.PasswordLineEdit):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            _field_height(self)

    # محدِّدٌ بثقل محدِّدات المكتبة نفسها (`DateEdit[symbolVisible=false]`)
    # فيغلبها لأنه يأتي بعدها — `QAbstractSpinBox` وحده أخفّ فيُهمَل
    _SPIN_SEL = ("QAbstractSpinBox, QAbstractSpinBox[symbolVisible=true], "
                 "QAbstractSpinBox[transparent=true]")
    _SPIN_OFF = ("QAbstractSpinBox[symbolVisible=false], "
                 "QAbstractSpinBox:read-only")

    def _spin_rtl_qss(compact):
        side = 34 if compact else 80

        def make(_t):
            return (f"{_SPIN_SEL} {{ padding: 0px 10px 0px {side}px; }}"
                    f"{_SPIN_OFF} {{ padding: 0px 10px; }}")
        make.kit_root = "spin" if compact else None
        return make

    def _date_qss(rtl):
        pad = "0px 10px 0px 40px" if rtl else "0px 40px 0px 10px"

        def make(_t):
            # وزرّ التقويم في ورقة الخانة نفسها — لا ورقةَ خاصّة له
            return (f"{_SPIN_SEL}, {_SPIN_OFF} {{ padding: {pad}; }}"
                    "QToolButton#kitCalendar { border: none; background: "
                    "transparent; border-radius: 4px; padding: 0; }"
                    "QToolButton#kitCalendar:hover { background: "
                    "rgba(127,127,127,0.16); }")
        make.kit_root = "date" if rtl else None
        return make

    from qfluentwidgets.components.widgets import spin_box as _qsb

    class _SpinFix:
        """أزرار الزيادة والنقص يسار الرقم بالعربية — والحشو معها."""

        _kit_compact = False

        def _kit_init(self):
            _field_height(self, 12)
            if _rtl(self):
                _custom(self, _spin_rtl_qss(self._kit_compact))

        def setSymbolVisible(self, isVisible):
            # المكتبة تعيد هنا «نمط البرنامج» كلّه للخانة (`setStyle`)
            # لتُقرأ خاصية `symbolVisible` من جديد — فيُبنى للخانة محرّك
            # أنماطٍ خاصّ ويُعاد تطبيق كل الأوراق عليها وعلى أبنائها. وكل
            # خانة رقمٍ أو تاريخ تمرّ بهذا عند بنائها (4.71). يكفي إعلام
            # النمط الحالي بتغيّر الخاصية — وقبل الظهور لا شيء يُعاد أصلاً
            isVisible = bool(isVisible)
            self.setProperty("symbolVisible", isVisible)
            for name in ("compactSpinButton", "upButton", "downButton"):
                b = getattr(self, name, None)
                if b is not None:
                    b.setVisible(isVisible)
            if self.testAttribute(QtCore.Qt.WA_WState_Polished):
                st = self.style()
                st.unpolish(self)
                st.polish(self)
                self.update()

        def setButtonSymbols(self, symbols):
            super().setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
            # «بلا أزرار» في Qt = «بلا رموز» في Fluent
            try:
                self.setSymbolVisible(
                    symbols != QtWidgets.QAbstractSpinBox.NoButtons)
            except Exception:
                pass

        def contextMenuEvent(self, e):
            _edit_menu(self.lineEdit(), e.globalPos())

        def focusInEvent(self, e):
            # الصيغة المدمجة تفتح لوحة السهمين مع **كل** تركيز — وخانات
            # الأوزان تُعبر بـEnter عشرات المرات في الفاتورة، فتنبثق
            # اللوحة فوق الخانة التالية في كل مرة. اللوحة بالنقر وحده.
            for k in type(self).__mro__:
                if k.__module__.startswith("PyQt5"):
                    return k.focusInEvent(self, e)

    class _LazyCompact(_SpinFix):
        """الصيغة المدمجة بلا لوحة السهمين مسبقاً (4.71).

        المكتبة تبني لكل خانة رقمٍ **نافذةً منبثقة** كاملة (لوحة السهمين
        بظلّها وزرّيها) عند إنشائها — وفاتورةٌ واحدة فيها عشرات الخانات،
        ولا تُفتح اللوحة إلا بالنقر على زرّها الصغير. فصارت تُبنى عند أول
        نقرةٍ عليها وحدها: كانت الخانة تكلّف 18 م.ث وصارت كالكلاسيكية.
        """

        _kit_compact = True

        def _kit_compact_init(self, args, kwargs):
            parent = args[0] if args else kwargs.get("parent")
            _qsb.SpinBoxBase.__init__(self, parent)
            self.spinFlyoutView = None
            self.spinFlyout = None
            self.compactSpinButton = _qsb.CompactSpinButton(self)
            self.hBoxLayout.setContentsMargins(0, 0, 0, 0)
            self.hBoxLayout.addWidget(self.compactSpinButton, 0,
                                      QtCore.Qt.AlignRight)
            self.hBoxLayout.setAlignment(QtCore.Qt.AlignRight
                                         | QtCore.Qt.AlignVCenter)
            self.compactSpinButton.clicked.connect(self._showFlyout)
            self._kit_init()

        def _kit_flyout(self):
            if self.spinFlyout is None:
                view = _qsb.SpinFlyoutView(self)
                self.spinFlyoutView = view
                self.spinFlyout = _qsb.Flyout(view, self, False)
                view.upButton.clicked.connect(self.stepUp)
                view.downButton.clicked.connect(self.stepDown)
                acc = self.isAccelerated()
                view.upButton.setAutoRepeat(acc)
                view.downButton.setAutoRepeat(acc)
                self.spinFlyout.hide()

        def _showFlyout(self):
            self._kit_flyout()
            _qsb.CompactSpinBoxBase._showFlyout(self)

        def setAccelerated(self, on):
            QtWidgets.QAbstractSpinBox.setAccelerated(self, on)
            if self.spinFlyoutView is not None:
                self.spinFlyoutView.upButton.setAutoRepeat(on)
                self.spinFlyoutView.downButton.setAutoRepeat(on)

    class SpinBox(_LazyCompact, qf.CompactSpinBox):
        # الصيغة المدمجة: زرٌّ صغير واحد يفتح السهمين — خانات العدد في
        # النظام ضيّقة، وزرّا Fluent العريضان (80 بكسلاً) يأكلان الرقم
        def __init__(self, *args, **kwargs):
            self._kit_compact_init(args, kwargs)

    class DoubleSpinBox(_LazyCompact, qf.CompactDoubleSpinBox):
        def __init__(self, *args, **kwargs):
            self._kit_compact_init(args, kwargs)

    # أساسها `SpinBoxBase` لا `DateEdit` المكتبة: تلك تبني زرّي سهمين
    # بأوراقهما ثم نخفيهما فوراً — والخانة تُكتب بالأرقام وزرّ التقويم
    # بجانبها (4.71)
    class DateEdit(_SpinFix, _qsb.SpinBoxBase, QtWidgets.QDateEdit):
        """خانة تاريخٍ تُكتب بالأرقام، وزرّ تقويم Fluent بجانبها.

        `setCalendarPopup` يبقى مقبولاً (الشاشات تستدعيه)، والتقويم
        المنبثق تقويم المكتبة الحديث لا تقويم Qt الرمادي.
        """

        _kit_compact = True

        def __init__(self, *args, **kwargs):
            date = None
            if args and isinstance(args[0], QtCore.QDate):
                date, args = args[0], args[1:]
            super().__init__(*args, **kwargs)
            self.setSymbolVisible(False)
            self._kit_init()
            self.setDisplayFormat("yyyy-MM-dd")
            self._cal_btn = QtWidgets.QToolButton(self)
            self._cal_btn.setObjectName("kitCalendar")
            self._cal_btn.setIcon(icon("CALENDAR"))
            self._cal_btn.setCursor(QtCore.Qt.PointingHandCursor)
            self._cal_btn.setToolTip("اختيار التاريخ من التقويم")
            self._cal_btn.setFixedSize(30, 26)
            self._cal_btn.clicked.connect(self._kit_calendar)
            self.hBoxLayout.setContentsMargins(4, 3, 4, 3)
            self.hBoxLayout.addWidget(self._cal_btn, 0, QtCore.Qt.AlignRight)
            self.hBoxLayout.setAlignment(QtCore.Qt.AlignRight
                                         | QtCore.Qt.AlignVCenter)
            _custom(self, _date_qss(_rtl(self)))
            self.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            if date is not None:
                self.setDate(date)

        def setCalendarPopup(self, on):
            # التقويم زرٌّ دائم في الخانة؛ منبثق Qt يبقى مطفأً فلا يظهر
            # تقويمان لنقرةٍ واحدة
            QtWidgets.QDateEdit.setCalendarPopup(self, False)

        def _kit_calendar(self):
            try:
                from qfluentwidgets.components.date_time.calendar_view import (
                    CalendarView)
                view = CalendarView(self.window())
                # أسماء الأشهر من لغة الأداة: عربية (والأرقام تبقى لاتينية)
                view.setLocale(QtCore.QLocale(QtCore.QLocale.Arabic,
                                              QtCore.QLocale.SaudiArabia))
                _arabize_calendar(view)
                view.setDate(self.date())
                view.dateChanged.connect(self.setDate)
                pos = self.mapToGlobal(QtCore.QPoint(0, self.height() + 2))
                if _rtl(self):
                    pos.setX(pos.x() + self.width() - view.sizeHint().width())
                view.exec(pos)
                self._kit_view = view
            except Exception:
                pass

    class CheckBox(qf.CheckBox):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.setCursor(QtCore.Qt.PointingHandCursor)

    class RadioButton(qf.RadioButton):
        """زرّ اختيار Fluent — الدائرة يمين النصّ بالعربية.

        المكتبة ترسم الدائرة عند x=11 والنصّ من x=29 بإحداثياتٍ ثابتة،
        فبالاتجاه العربي يخرج النصّ خارج الزرّ ولا يُرى. هنا يُعكس
        الرسم: الدائرة على اليمين، والنصّ قبلها محاذىً لليمين.
        """

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.setCursor(QtCore.Qt.PointingHandCursor)

        def paintEvent(self, e):
            if not _rtl(self):
                return super().paintEvent(e)
            p = QtGui.QPainter(self)
            p.setRenderHints(QtGui.QPainter.Antialiasing
                             | QtGui.QPainter.TextAntialiasing)
            p.save()
            p.translate(self.width(), 0)
            p.scale(-1, 1)
            self._drawIndicator(p)
            p.restore()
            if not self.isEnabled():
                p.setOpacity(0.36)
            p.setFont(self.font())
            p.setPen(self.textColor())
            p.drawText(QtCore.QRect(0, 0, self.width() - 29, self.height()),
                       int(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight
                           | QtCore.Qt.AlignAbsolute), self.text())
            p.end()

    class Switch(qf.SwitchButton):
        """مفتاح تشغيل/إيقاف بنصٍّ عربي — بواجهة `QCheckBox` المألوفة."""

        toggled = QtCore.pyqtSignal(bool)

        def __init__(self, text="", parent=None, checked=False):
            super().__init__(parent=parent)
            self.setOnText(text or "مفعّل")
            self.setOffText(text or "متوقّف")
            self.setChecked(bool(checked))
            self.checkedChanged.connect(self.toggled.emit)

    # ══ القائمة المنسدلة: QComboBox بقائمة Fluent ══
    # فوق هذا العدد تبقى قائمة Qt: Fluent يعيد قياس القائمة مع كل بند
    MENU_MAX = 250

    class ComboBox(QtWidgets.QComboBox):
        """`QComboBox` كما هو — وقائمته المنبثقة قائمة Fluent.

        كل ما تستعمله الشاشات (`addItem(نص، بيانات)` · `findData` ·
        `currentData` · `setModel` · الإكمال) هو Qt نفسه. الذي يتغيّر
        **النافذة المنبثقة** وحدها: حوافّ مستديرة وظلّ وحركة انسدال
        وتحديدٌ بشريطٍ ذهبي — وهي ما يراه المستخدم كل مرة.
        """

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._kit_menu = None
            self.setCursor(QtCore.Qt.PointingHandCursor)

        def showPopup(self):
            n = self.count()
            if not ACTIVE or n == 0 or n > MENU_MAX:
                return super().showPopup()
            try:
                self._kit_show_menu()
            except Exception:
                super().showPopup()

        def hidePopup(self):
            m = self._kit_menu
            if m is not None:
                try:
                    m.close()
                except Exception:
                    pass
                self._kit_menu = None
            super().hidePopup()

        def _kit_show_menu(self):
            menu = _rtl_menu(_ComboMenu(self), indicator=True)
            model = self.model()
            col = self.modelColumn()
            cur = self.currentIndex()
            acts = []
            for i in range(self.count()):
                idx = model.index(i, col, self.rootModelIndex())
                if (self.itemData(i, QtCore.Qt.AccessibleDescriptionRole)
                        == "separator"):
                    menu.addSeparator()
                    acts.append(None)
                    continue
                a = QtWidgets.QAction(self.itemIcon(i),
                                      _rtl_text(self.itemText(i)), menu)
                a.setEnabled(bool(model.flags(idx) & QtCore.Qt.ItemIsEnabled))
                a.triggered.connect(lambda _c=False, x=i: self._kit_pick(x))
                menu.addAction(a)
                acts.append(a)
            if menu.view.width() < self.width():
                menu.view.setMinimumWidth(self.width())
                menu.adjustSize()
            menu.setMaxVisibleItems(max(6, self.maxVisibleItems()))
            menu.setAttribute(QtCore.Qt.WA_DeleteOnClose)
            if 0 <= cur < len(acts) and acts[cur] is not None:
                menu.setDefaultAction(acts[cur])
            menu.closedSignal.connect(self._kit_closed)
            self._kit_menu = menu
            # حافّة القائمة على حافّة الخانة نفسها — يمينها بالعربية
            ml = menu.layout().contentsMargins()
            if _rtl(self):
                x = self.width() - menu.width() + ml.right()
            else:
                x = -ml.left()
            down = self.mapToGlobal(QtCore.QPoint(x, self.height()))
            up = self.mapToGlobal(QtCore.QPoint(x, 0))
            hd = menu.view.heightForAnimation(down, _MenuAni.DROP_DOWN)
            hu = menu.view.heightForAnimation(up, _MenuAni.PULL_UP)
            if hd >= hu:
                menu.view.adjustSize(down, _MenuAni.DROP_DOWN)
                menu.exec(down, aniType=_MenuAni.DROP_DOWN)
            else:
                menu.view.adjustSize(up, _MenuAni.PULL_UP)
                menu.exec(up, aniType=_MenuAni.PULL_UP)

        def _kit_closed(self):
            self._kit_menu = None

        def _kit_pick(self, i):
            if i != self.currentIndex():
                self.setCurrentIndex(i)
            self.activated[int].emit(i)
            self.activated[str].emit(self.itemText(i))
            try:
                self.textActivated.emit(self.itemText(i))
            except Exception:
                pass

        def paintEvent(self, e):
            super().paintEvent(e)
            if self.isEditable():
                return
            # سهم Fluent الرفيع في طرف الخانة بدل سهم Qt الرمادي
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            s = 10
            x = 12 if _rtl(self) else self.width() - 12 - s
            y = (self.height() - s) // 2
            try:
                qf.FluentIcon.ARROW_DOWN.render(
                    p, QtCore.QRectF(x, y, s, s))
            except Exception:
                pass
            p.end()

    # ══ الجداول ══
    class RowDelegate(_FluentDelegate):
        """رسّام صفوف Fluent مصحَّحٌ للاتجاه العربي وللجداول المحاسبية.

        · الصفّ شريطٌ واحد متّصل: الاستدارة على حافّتيه الخارجيتين
          (العمود الأول يمين الجدول بالعربية) لا بين خاناته.
        · شريط التحديد الذهبي على **يمين** السطر المحدد.
        · خطّ الخانة خطّ الجدول نفسه (مقاس النظام) لا 13 بكسلاً ثابتة،
          ولونها لونُ الخلية إن لُوِّنت (صفّ الإجمالي، المبالغ السالبة).
        """

        def _edge_cols(self, view):
            # يُسأل عنه في رسم **كل خلية**: يُحسب مرةً ويُحفظ حتى يتغيّر
            # الرأس (نقل عمود · إخفاؤه · تغيّر عدد الأعمدة) — 4.71
            edges = self.__dict__.get("_kit_edges")
            if edges is not None:
                return edges
            hh = view.horizontalHeader()
            if self.__dict__.get("_kit_hh") is not hh:
                self._kit_hh = hh
                # دالّة الصنف لا `lambda` تمسك بالرسّام: تلك حلقةٌ (رسّام ←
                # رأس ← وصلة ← lambda ← رسّام) يكنسها جامع بايثون والوصلة
                # باقية في Qt — فتُستدعى دالّةٌ مكنوسة عند تغيّر الخط وينهار
                # البرنامج. دالّة الصنف تُمسك بضعف وتنفكّ بزوال الرسّام
                for sig in (hh.sectionMoved, hh.sectionCountChanged,
                            hh.sectionResized, hh.geometriesChanged):
                    sig.connect(self._kit_drop_edges)
            first = last = None
            for v in range(hh.count()):
                lg = hh.logicalIndex(v)
                if hh.isSectionHidden(lg):
                    continue
                if first is None:
                    first = lg
                last = lg
            self._kit_edges = (first, last)
            return first, last

        def _kit_drop_edges(self, *_a):
            self.__dict__.pop("_kit_edges", None)

        def _drawBackground(self, painter, option, index):
            r = 5
            view = self.parent()
            first, last = self._edge_cols(view)
            col = index.column()
            rtl = view.isRightToLeft()
            rect = option.rect
            start, end = col == first, col == last
            if start and end:
                painter.drawRoundedRect(rect.adjusted(4, 0, -4, 0), r, r)
            elif start:
                # الحافّة الخارجية للعمود الأول: يمينٌ بالعربية
                painter.drawRoundedRect(
                    rect.adjusted(-r - 1, 0, -4, 0) if rtl
                    else rect.adjusted(4, 0, r + 1, 0), r, r)
            elif end:
                painter.drawRoundedRect(
                    rect.adjusted(4, 0, r + 1, 0) if rtl
                    else rect.adjusted(-r - 1, 0, -4, 0), r, r)
            else:
                painter.drawRect(rect.adjusted(-1, 0, 1, 0))

        def _drawIndicator(self, painter, option, index):
            y, h = option.rect.y(), option.rect.height()
            ph = round(0.35 * h if self.pressedRow == index.row()
                       else 0.257 * h)
            painter.setBrush(qf.themeColor())
            if self.parent().isRightToLeft():
                x = option.rect.right() - 6
            else:
                x = option.rect.left() + 4
            painter.drawRoundedRect(QtCore.QRectF(x, ph + y, 3, h - 2 * ph),
                                    1.5, 1.5)

        # التحرير داخل الخانة بمحرّر Qt المعتاد: الشاشات التي تعدّل من
        # الجدول (الأجر · الأوزان) تبني على سلوكه، ومحرّر المكتبة يضيف
        # زرّ مسحٍ ويغيّر حجم الخانة أثناء الكتابة
        def createEditor(self, parent, option, index):
            return QtWidgets.QStyledItemDelegate.createEditor(
                self, parent, option, index)

        def updateEditorGeometry(self, editor, option, index):
            QtWidgets.QStyledItemDelegate.updateEditorGeometry(
                self, editor, option, index)

        # ══ القياس بلا بايثون (4.71) ══
        # الصفوف تُقاس على محتواها، وQt يعيد قياس **كل خلية** مع كل تحديثٍ
        # للجدول أو تغيّرٍ في عرض أعمدته. وكان القياس يمرّ بثلاث طبقاتٍ من
        # بايثون لكل خلية (قياس المكتبة ← القياس الأصلي ← تهيئة خيار الخلية
        # المعاد تعريفها) — فصار طبقةً رقيقة واحدة فوق قياس Qt نفسه.
        # تهيئة الخيار هي تهيئة Qt الأصلية (تهيئة المكتبة رُفعت عن صنفها
        # عند التحميل — انظر `_FluentDelegate` أعلاه): تأخذ خطّ الخلية
        # ولونها من بياناتها كما كانت تفعل نسختنا. ولون النصّ الافتراضي
        # (حبر الوضع) ولونه عند التحديد يُضبطان قبل الرسم في `paint`.

        def sizeHint(self, option, index):
            # كالمكتبة: هامشان رأسيّان لحدّ الصفّ المستدير (2 + 2)
            s = QtWidgets.QStyledItemDelegate.sizeHint(self, option, index)
            return QtCore.QSize(s.width(), s.height() + 4)

        _INK = {}

        def paint(self, painter, option, index):
            ink = RowDelegate._INK.get(_STATE["dark"])
            if ink is None:
                light, dark = _tokens()
                ink = RowDelegate._INK[_STATE["dark"]] = QtGui.QColor(
                    (dark if _STATE["dark"] else light)["ink"])
            brush = index.data(QtCore.Qt.ForegroundRole)
            fg = QtGui.QBrush(brush).color() if brush is not None else ink
            # «النصّ» يُستبدل بلون الخلية إن كان لها لون (التهيئة الأصلية)،
            # و«النصّ المحدَّد» يبقى لون الخلية نفسه — لا أبيض فوق التظليل
            option.palette.setColor(QtGui.QPalette.Text, ink)
            option.palette.setColor(QtGui.QPalette.HighlightedText, fg)
            _FluentDelegate.paint(self, painter, option, index)

    # حشو الخلية كحشو الجدول الكلاسيكي (8 × 5) **عمداً**: الأزرار والخانات
    # المزروعة في الخلايا (✕ حذف · العدد) تأخذ مساحة الخلية ناقصاً حشوها —
    # فحشوٌ أعرض كان يقصّ «✕» إلى نقطة في عمودٍ ضيّق.
    def _header_qss(t):
        return f"""
        QHeaderView::section {{ color: {t['hdrFg']}; font-weight: bold;
            font-size: {_px(15)}px; background-color: {t['hdrBg']};
            border: none; border-bottom: 2px solid {t['hdrLine']};
            border-left: 1px solid {t['hdrLine2']}; padding: 6px 8px; }}
        QHeaderView::section:horizontal {{ height: {_px(34)}px; }}
        QHeaderView::section:hover {{ background-color: {t['goldSoft2']}; }}
        QTableView {{ background: {t['surface']}; border-radius: 10px;
            font-size: {_px(17)}px; font-weight: 500; }}
        QTableView[isBorderVisible=true] {{ border: 1px solid {t['line']}; }}
        QTableView::item {{ padding: 8px 5px; }}"""
    _header_qss.kit_root = "table"

    from qfluentwidgets.components.widgets import table_view as _qtv
    from qfluentwidgets.components.widgets.scroll_bar import (
        SmoothScrollDelegate as _RealSmooth)

    class _LazySmooth(QtCore.QObject):
        """التمرير الناعم يُبنى عند أول ظهورٍ للجدول (4.71).

        المكتبة تبني لكل جدول شريطَي تمريرٍ مرسومَين (مجرىً وزرّا سهمٍ
        ومقبضٌ وحركاتٌ لكلٍّ منهما) لحظة إنشائه — وشاشةٌ بتبويبات فيها
        جداول لا تُرى حتى يُنقر تبويبها. فيُسجَّل هنا ما يُطلب من سياسة
        الأشرطة، ويُبنى المفوَّض الحقيقي عند الظهور الأول ويُعاد عليه.
        """

        def __init__(self, parent, useAni=False):
            super().__init__(parent)
            self._view, self._ani, self._pol, self._hooks = parent, useAni, {}, []
            self.real = None
            QtWidgets.QAbstractScrollArea.setVerticalScrollBarPolicy(
                parent, QtCore.Qt.ScrollBarAlwaysOff)
            QtWidgets.QAbstractScrollArea.setHorizontalScrollBarPolicy(
                parent, QtCore.Qt.ScrollBarAlwaysOff)
            parent.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
            parent.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
            parent.setVerticalScrollBarPolicy = lambda p: self._pol.__setitem__("v", p)
            parent.setHorizontalScrollBarPolicy = lambda p: self._pol.__setitem__("h", p)
            parent.installEventFilter(self)

        def eventFilter(self, obj, e):
            if e.type() == QtCore.QEvent.Show and self.real is None:
                self.materialize()
            return False

        def materialize(self):
            if self.real is not None:
                return self.real
            view = self._view
            view.removeEventFilter(self)
            real = _RealSmooth(view, self._ani)       # يعيد ربط دوالّ السياسة
            if "v" in self._pol:
                real.setVerticalScrollBarPolicy(self._pol["v"])
            if "h" in self._pol:
                real.setHorizontalScrollBarPolicy(self._pol["h"])
            self.real = real
            view.scrollDelagate = real
            for fn in self._hooks:
                try:
                    fn(real)
                except Exception:
                    pass
            self._hooks = []
            return real

        def on_ready(self, fn):
            if self.real is not None:
                fn(self.real)
            else:
                self._hooks.append(fn)

        @property
        def vScrollBar(self):
            return self.materialize().vScrollBar

        @property
        def hScrollBar(self):
            return self.materialize().hScrollBar

    # الجداول وحدها (وحدة table_view): غيرها من المكتبة يبقى كما هو.
    # والجدول يبني رسّامنا مباشرةً بدل رسّام المكتبة الذي كان يُستبدل
    _qtv.SmoothScrollDelegate = _LazySmooth
    _qtv.TableItemDelegate = RowDelegate

    class _TableKit:
        """ما يلزم جداول Fluent لتقوم مقام جداول النظام."""

        def _kit_init(self):
            # الرسّام رسّامنا من البداية (`_qtv.TableItemDelegate` أدناه) —
            # كان الجدول يبني رسّام المكتبة ثم يُستبدل، فيبقى مرشّحا
            # تلميحاته يعترضان كل حدثٍ في الجدول بلا عمل
            if not isinstance(self.itemDelegate(), RowDelegate):
                self.setItemDelegate(RowDelegate(self))
            self.setBorderVisible(True)
            # استدارة الحواف في ورقة الرأس نفسها (`QTableView { border-radius }`)
            # — `setBorderRadius` كان يضيف للجدول ورقةً خاصّة ثالثة
            self.setSelectRightClickedRow(True)
            _custom(self, _header_qss)
            self._kit_watch()
            sd = getattr(self, "scrollDelagate", None)
            if isinstance(sd, _LazySmooth):
                sd.on_ready(lambda _r: self._kit_rtl_scrollbar())
            else:
                self._kit_rtl_scrollbar()

        def setBorderVisible(self, isVisible):
            # المكتبة تعيد «نمط البرنامج» كلّه للجدول هنا (`setStyle`)؛
            # يكفي إعلام النمط بتغيّر الخاصية — وقبل الظهور لا شيء يُعاد
            self.setProperty("isBorderVisible", bool(isVisible))
            if self.testAttribute(QtCore.Qt.WA_WState_Polished):
                st = self.style()
                st.unpolish(self)
                st.polish(self)
                self.update()

        def _kit_rtl_scrollbar(self):
            # شريط التمرير الرفيع يمين الجدول دائماً في المكتبة؛ بالعربية
            # مكانه اليسار — فلا يغطّي العمود الأول (رقم المستند/الاسم)
            sd = getattr(self, "scrollDelagate", None)
            vb = getattr(sd, "vScrollBar", None)
            if vb is None or not hasattr(vb, "_adjustPos"):
                return
            orig = vb._adjustPos

            def _adjust(size, _vb=vb, _orig=orig, _view=self):
                _orig(size)
                if _rtl(_view):
                    _vb.move(1, 1)
            vb._adjustPos = _adjust
            # الشريط وُضع لحظة بنائه (يميناً) — يُعاد وضعه الآن
            _adjust(self.size())

        def _kit_watch(self):
            # التحديد من الشيفرة (`setCurrentCell` · `selectRow` · البحث)
            # يصل الرسّام أيضاً، لا نقرة الفأرة وحدها
            sm = self.selectionModel()
            if sm is not None and sm is not getattr(self, "_kit_sm", None):
                self._kit_sm = sm
                sm.selectionChanged.connect(
                    lambda *_: self.updateSelectedRows())

        def setShowGrid(self, show):
            # شبكة الخطوط تقطع الصفوف المستديرة؛ الفصل بتناوب الألوان
            QtWidgets.QTableView.setShowGrid(self, False)

    class TableWidget(_TableKit, qf.TableWidget):
        """`QTableWidget` بصفوف Fluent: تمريرٌ ناعم وتظليلٌ عند المرور
        وشريط تحديد ذهبي — وكل واجهة `QTableWidget` كما هي."""

        def __init__(self, *args, **kwargs):
            rows = cols = None
            if len(args) >= 2 and all(isinstance(a, int) for a in args[:2]):
                rows, cols, args = args[0], args[1], args[2:]
            super().__init__(*args, **kwargs)
            self._kit_init()
            if rows is not None:
                self.setRowCount(rows)
                self.setColumnCount(cols)

        def setCurrentCell(self, row, column, command=None):
            # المكتبة تمرّر الخلية نفسها، فخانةٌ بلا عنصر (زرّ في الصف)
            # كانت تُلغي التحديد بدل أن تحدّد صفّها
            if command is None:
                QtWidgets.QTableWidget.setCurrentCell(self, row, column)
            else:
                QtWidgets.QTableWidget.setCurrentCell(self, row, column,
                                                      command)
            self.updateSelectedRows()

    class TableView(_TableKit, qf.TableView):
        """`QTableView` بصفوف Fluent — للجداول المبنية على نموذج بيانات."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._kit_init()

        def setModel(self, model):
            super().setModel(model)
            self._kit_watch()

else:
    PushButton = QtWidgets.QPushButton
    LineEdit = QtWidgets.QLineEdit
    SpinBox = QtWidgets.QSpinBox
    DoubleSpinBox = QtWidgets.QDoubleSpinBox
    CheckBox = QtWidgets.QCheckBox
    RadioButton = QtWidgets.QRadioButton
    ComboBox = QtWidgets.QComboBox
    TableWidget = QtWidgets.QTableWidget
    TableView = QtWidgets.QTableView
    RowDelegate = None

    class SearchLineEdit(QtWidgets.QLineEdit):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.setClearButtonEnabled(True)

    class PasswordLineEdit(QtWidgets.QLineEdit):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.setEchoMode(QtWidgets.QLineEdit.Password)

    class DateEdit(QtWidgets.QDateEdit):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.setDisplayFormat("yyyy-MM-dd")

    class Switch(QtWidgets.QCheckBox):
        def __init__(self, text="", parent=None, checked=False):
            super().__init__(text, parent)
            self.setChecked(bool(checked))


def CellButton(text="", tip="", parent=None):
    """زرٌّ صغير **داخل صفّ جدول** (معاينة · طباعة · كشف حساب).

    خفيفٌ عمداً: زرّ Fluent يحمل ورقة نمطٍ خاصة به يحلّلها Qt لكل زرٍّ
    على حدة — مقبولٌ لعشرين زرّاً في شاشة، ومكلفٌ لأربعمئة في جدول
    أرشيفٍ من مئة صفّ (كان يضاعف زمن فتحه ثماني مرات). هذا زرٌّ يأخذ
    شكله من نمط النظام العام (`QToolButton#rowAct`) بلا ورقةٍ خاصة.
    """
    b = QtWidgets.QToolButton(parent)
    b.setObjectName("rowAct")
    b.setText(text)
    if tip:
        b.setToolTip(tip)
    b.setCursor(QtCore.Qt.PointingHandCursor)
    b.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
    return b


# ══════════════════════════════════════════════════════════════════
#  النوافذ: رسائل · إشعارات · قوائم · انتظار
# ══════════════════════════════════════════════════════════════════

# دوال `QMessageBox` الأصلية — إن استبدلتها أداة فحصٍ (لإسكات النوافذ)
# تُحترم: الرسالة تمرّ عبرها لا عبر نافذة Fluent لا تعرفها الأداة.
_QMB = QtWidgets.QMessageBox
_ORIG = {n: getattr(_QMB, n) for n in
         ("information", "warning", "critical", "question")}


def _patched(name):
    try:
        return getattr(_QMB, name) != _ORIG[name]
    except Exception:
        return False


def _host(parent):
    """النافذة العليا الظاهرة التي تُغطّى بقناع الرسالة — أو لا شيء."""
    try:
        w = parent.window() if parent is not None else None
    except Exception:
        w = None
    if w is None:
        w = QtWidgets.QApplication.activeWindow()
    try:
        if w is not None and w.isVisible() and w.width() > 320:
            return w
    except Exception:
        pass
    return None


KINDS = {
    # النوع: (أيقونة Fluent، لونها، دالة QMessageBox المقابلة)
    "info": ("INFO", "#9A7B22", "information"),
    "success": ("COMPLETED", "#0F7B3A", "information"),
    "warning": ("INFO", "#B7791F", "warning"),
    "error": ("CLOSE", "#B42318", "critical"),
    "question": ("HELP", "#9A7B22", "question"),
}


if ACTIVE:
    class MessageDialog(qf.MessageBoxBase):
        """رسالة Fluent: بطاقةٌ فوق قناعٍ معتم، بعنوانٍ وأيقونةٍ ملوّنة
        وأزرارٍ عربية — تظهر وتختفي بتلاشٍ ناعم."""

        def __init__(self, parent, title, text, kind="info",
                     buttons=(("ok", "موافق", "primary"),), detail=""):
            super().__init__(parent)
            self.choice = None
            name, color, _fn = KINDS.get(kind, KINDS["info"])
            head = QtWidgets.QHBoxLayout()
            head.setSpacing(12)
            ic = qf.IconWidget(getattr(qf.FluentIcon, name), self.widget)
            ic.setFixedSize(28, 28)
            try:
                ic.setIcon(getattr(qf.FluentIcon, name).colored(
                    QtGui.QColor(color), QtGui.QColor(color)))
            except Exception:
                pass
            ttl = qf.SubtitleLabel(str(title), self.widget)
            head.addWidget(ic)
            head.addWidget(ttl, 1)
            self.viewLayout.addLayout(head)
            body = qf.BodyLabel(str(text), self.widget)
            body.setWordWrap(True)
            body.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            body.setMinimumWidth(380)
            self.viewLayout.addWidget(body)
            if detail:
                d = qf.CaptionLabel(str(detail), self.widget)
                d.setWordWrap(True)
                self.viewLayout.addWidget(d)
            # أزرار الحوار: الأولى الأساسية، والبقية ثانوية بترتيبها
            self.yesButton.hide()
            self.cancelButton.hide()
            self._buttons = {}
            first = None
            for key, label, role in buttons:
                b = PushButton(label, self.buttonGroup)
                if role != "primary":
                    b.setObjectName("ghost")
                b.setAttribute(QtCore.Qt.WA_LayoutUsesWidgetRect)
                b.clicked.connect(lambda _c=False, k=key: self._pick(k))
                self.buttonLayout.addWidget(b, 1, QtCore.Qt.AlignVCenter)
                self._buttons[key] = b
                first = first or b
            if first is not None:
                first.setFocus()
            self.widget.setMinimumWidth(460)

        def _pick(self, key):
            self.choice = key
            self.accept()

        def keyPressEvent(self, e):
            if e.key() == QtCore.Qt.Key_Escape:
                self.choice = None
                self.reject()
                return
            super().keyPressEvent(e)


def message(parent, text, title="", kind="info",
            buttons=(("ok", "موافق", "primary"),), detail="",
            default=None):
    """رسالةٌ بأزرارٍ معلومة — تعيد مفتاح الزرّ المضغوط (أو `default`).

    بلا مكتبة أو بلا نافذةٍ ظاهرة تُغطّى: `QMessageBox` كما كان.
    """
    host = _host(parent)
    fn_name = KINDS.get(kind, KINDS["info"])[2]
    if ACTIVE and host is not None and not _patched(fn_name):
        try:
            dlg = MessageDialog(host, title, text, kind, buttons, detail)
            dlg.exec_()
            return dlg.choice if dlg.choice is not None else default
        except Exception:
            pass
    return _classic(parent, text, title, kind, buttons, detail, default)


def _classic(parent, text, title, kind, buttons, detail, default):
    qmb = QtWidgets.QMessageBox
    if len(buttons) == 1 and not detail:
        getattr(qmb, KINDS.get(kind, KINDS["info"])[2])(
            parent, title, str(text))
        return buttons[0][0]
    if (len(buttons) == 2 and kind == "question" and not detail
            and _patched("question")):
        r = qmb.question(parent, title, str(text), qmb.Yes | qmb.No)
        return buttons[0][0] if r == qmb.Yes else default
    box = qmb(parent)
    box.setWindowTitle(title)
    box.setIcon({"error": qmb.Critical, "warning": qmb.Warning,
                 "question": qmb.Question}.get(kind, qmb.Information))
    box.setText(str(text))
    if detail:
        box.setInformativeText(str(detail))
    keyed = {}
    for key, label, role in buttons:
        r = (qmb.AcceptRole if role == "primary"
             else qmb.RejectRole if key in ("cancel", "no", "later")
             else qmb.ActionRole)
        keyed[box.addButton(label, r)] = key
    box.exec_()
    return keyed.get(box.clickedButton(), default)


def notify(parent, text, kind="success", title="", ms=2400):
    """إشعارٌ عابر أعلى النافذة (InfoBar) لا يحتاج «موافق».

    `ms` سالبٌ ⇒ ثابتٌ لا يختفي وحده (يُغلق بزرّه أو بـ`close()`).
    يعيد عنصر الإشعار، أو `None` إن لم تكن نافذةٌ ظاهرة.
    """
    try:
        win = parent.window() if parent is not None else None
    except Exception:
        win = None
    if win is None:
        return None
    if ACTIVE:
        try:
            fn = {"success": qf.InfoBar.success, "warning": qf.InfoBar.warning,
                  "error": qf.InfoBar.error}.get(kind, qf.InfoBar.info)
            bar = fn(title=str(title or ""), content=str(text),
                     orient=QtCore.Qt.Horizontal, isClosable=True,
                     position=qf.InfoBarPosition.TOP,
                     duration=(-1 if int(ms) < 0 else max(800, int(ms))),
                     parent=win)
            bar.setObjectName("kitNotify")
            return bar
        except Exception:
            pass
    return None


def popup_menu(parent, items, global_pos):
    """قائمةٌ منبثقة من [(نص، دالة، أيقونة)] و`None` للفاصل.

    Fluent: قائمةٌ مستديرة بظلٍّ وحركة انسدال، والنقرة تستدعي دالتها.
    كلاسيكي: `QMenu` كما كان. الدالة `None` ⇒ بندٌ معطّل للعرض.
    """
    if ACTIVE:
        try:
            m = _rtl_menu(qf.RoundMenu(parent=parent))
            for it in items:
                if it is None:
                    m.addSeparator()
                    continue
                label, fn = it[0], it[1]
                ic = it[2] if len(it) > 2 else None
                a = QtWidgets.QAction(icon(ic) if isinstance(ic, str)
                                      else (ic or QtGui.QIcon()),
                                      _rtl_text(label), m)
                if fn is None:
                    a.setEnabled(False)
                else:
                    a.triggered.connect(lambda _c=False, f=fn: f())
                m.addAction(a)
            pos = QtCore.QPoint(global_pos)
            if QtWidgets.QApplication.isRightToLeft():
                # القائمة تنفتح يسار المؤشر بالعربية كما تفعل قوائم Qt
                m.adjustSize()
                pos.setX(pos.x() - m.width()
                         + m.layout().contentsMargins().right() * 2)
            m.exec(pos, ani=True)
            return m
        except Exception:
            pass
    m = QtWidgets.QMenu(parent)
    acts = {}
    for it in items:
        if it is None:
            m.addSeparator()
            continue
        a = m.addAction(it[0])
        if it[1] is None:
            a.setEnabled(False)
        else:
            acts[a] = it[1]
    chosen = m.exec_(global_pos)
    if chosen in acts:
        acts[chosen]()
    return m


class busy_tip:
    """بطاقة «جارٍ التنفيذ…» بدائرةٍ دوّارة في زاوية النافذة.

    تظهر بعد مهلةٍ قصيرة (`delay_ms`) فقط — العمل الذي ينتهي فوراً لا
    يومض بشيء. وعند الانتهاء تتحوّل علامة ✓ ثم تتلاشى.
    """

    def __init__(self, parent, text="جارٍ التنفيذ…", title="لحظة من فضلك",
                 delay_ms=600):
        self.parent, self.text, self.title = parent, text, title
        self.delay_ms = int(delay_ms)
        self.tip = None
        self._t0 = 0.0

    def tick(self, elapsed_ms):
        """يُستدعى من حلقة الانتظار: يُظهر البطاقة متى تجاوزت المهلة."""
        if self.tip is not None or not ACTIVE or elapsed_ms < self.delay_ms:
            return
        try:
            win = self.parent.window() if self.parent is not None else None
            if win is None or not win.isVisible():
                return
            tip = qf.StateToolTip(self.title, self.text, win)
            m = 18
            x = m if _rtl(win) else win.width() - tip.width() - m
            tip.move(x, m + 46)
            tip.show()
            tip.raise_()
            self.tip = tip
        except Exception:
            self.tip = False

    def done(self, ok=True):
        tip = self.tip
        self.tip = None
        if not tip:
            return
        try:
            if ok:
                tip.setContent("تمّ ✓")
                tip.setState(True)
            else:
                tip.close()
        except Exception:
            pass


def all_names():
    """أسماء المكوّنات المتاحة من الطبقة — لأدوات الفحص."""
    return ("PushButton", "CellButton", "LineEdit", "SearchLineEdit",
            "PasswordLineEdit",
            "SpinBox", "DoubleSpinBox", "DateEdit", "CheckBox",
            "RadioButton", "Switch", "ComboBox", "TableWidget", "TableView")
