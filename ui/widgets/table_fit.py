# -*- coding: utf-8 -*-
"""تحجيم الجداول المتجاوب — حل موحّد لكل شاشات النظام.

**المشكلة التي يحلّها**: كل شاشة كانت تضبط أعمدتها بطريقتها، فتتعارض
الإعدادات ويعود الجدول للتمدد الأفقي. وأجهزة المستخدمين تختلف: شاشة
13 بوصة وأخرى 27 بوصة — فالعرض الثابت لا يصلح للاثنين.

**الحل**: مُحجِّم واحد يُركَّب على أي جدول، يوزّع العرض المتاح
بأوزان نسبية، ويُعيد الحساب تلقائياً عند أي تغيّر في حجم النافذة —
فيظهر الجدول كاملاً على أي جهاز بلا تمرير أفقي.
"""
from PyQt5 import QtCore, QtWidgets


class ColumnFitter(QtCore.QObject):
    """يوزّع أعمدة الجدول على العرض المتاح ويحافظ على التوزيع.

    يعمل بمرشّح أحداث على منفذ العرض، فيلتقط كل تغيّر حجم مهما كان
    مصدره — تكبير النافذة أو تغيير دقة الشاشة أو طيّ الشريط الجانبي.
    """

    def __init__(self, table, weights, min_px=42):
        super().__init__(table)
        self.table = table
        self.weights = list(weights)
        self.min_px = min_px
        self._busy = False
        self._last_w = -1
        self._last_n = -1
        # مؤقّت تهدئة: تغييرات الحجم المتتالية تُجمَّع في نداء واحد.
        # بدونه يُطلق كل `setColumnWidth` حدثَ تغيير حجم جديداً فتنشأ
        # سلسلة لا تنتهي تُجمّد الواجهة عند إظهار/إخفاء الشريط الجانبي.
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._do_apply)
        try:
            hh = table.horizontalHeader()
            hh.setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
            hh.setStretchLastSection(False)
            hh.setMinimumSectionSize(min_px)
            table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            table.setWordWrap(True)
            table.setTextElideMode(QtCore.Qt.ElideNone)
            table.viewport().installEventFilter(self)
        except Exception:
            pass
        self.apply()

    def set_weights(self, weights):
        self.weights = list(weights)
        self._last_w = self._last_n = -1
        self.apply()

    def refit(self):
        """يُجبر إعادة الحساب — بعد تعبئة بيانات جديدة."""
        self._last_w = self._last_n = -1
        self.apply()

    def eventFilter(self, obj, ev):
        try:
            if ev.type() == QtCore.QEvent.Resize and not self._busy:
                self._timer.start()      # تهدئة بدل تنفيذ فوري
        except Exception:
            pass
        return False

    def apply(self):
        """يطلب إعادة التوزيع (مؤجَّلة بالتهدئة)."""
        try:
            self._timer.start()
        except Exception:
            self._do_apply()

    def _do_apply(self):
        """يحسب عرض كل عمود من نصيبه في الأوزان."""
        if self._busy:
            return
        t0 = self.table
        # لا عمل على جدول مخفيّ: يُعاد التوزيع عند ظهوره
        try:
            if not t0.isVisible():
                return
        except Exception:
            pass
        self._busy = True
        try:
            t = self.table
            n = t.columnCount()
            if n <= 0:
                return
            # ══ اختيار المستخدم يسبق أوزان الشاشة ══
            # من وسّع عمود «البيان» يريده موسَّعاً في كل مرة. وأوزان
            # الشاشة تُمرَّر مع كل إعادة تعبئة، فلولا هذه الأسبقية
            # لمحت كلُّ عملية تحديث ما اختاره بعد ثوانٍ من اختياره.
            w = self.weights
            try:
                saved = t.property("_user_weights")
            except Exception:
                saved = None
            if saved and len(saved) == n:
                w = list(saved)
            # أوزان متساوية إن لم تُحدَّد أو تغيّر عدد الأعمدة
            if len(w) != n:
                w = [1] * n
            avail = t.viewport().width()
            if not isinstance(avail, int) or avail < 200:
                avail = max(200, t.width() - 22)
            # لا نعيد الحساب إن لم يتغيّر العرض فعلياً — يمنع الدوران.
            # **وعدد الأعمدة شرطٌ مثله**: شاشة تبدّل أعمدتها (كشف
            # الحساب ↔ اليومية · تقرير يغيّر بعده) كانت تحتفظ بعروض
            # الأعمدة القديمة، فيبقى الجدول أضيق من إطاره ويظهر فراغ
            # أبيض في طرفه لا يملؤه شيء.
            if avail == self._last_w and n == self._last_n:
                return
            self._last_w, self._last_n = avail, n
            # **العمود المخفيّ لا يأخذ حصّة**: كان يُحجز له الحدّ الأدنى
            # ويُحسب في المجموع، فيضيق آخرُ عمودٍ ظاهر بقدره ويبقى في
            # طرف الجدول فراغٌ أبيض لا يملؤه شيء.
            shown = [i for i in range(n) if not t.isColumnHidden(i)]
            if not shown:
                return
            total = float(sum(w[i] for i in shown)) or 1.0
            used = 0
            for i in shown[:-1]:
                px = max(self.min_px, int(avail * w[i] / total))
                t.setColumnWidth(i, px)
                used += px
            t.setColumnWidth(shown[-1], max(self.min_px, avail - used - 2))
            # ملاحظة: كان هنا `resizeRowsToContents()` للجداول الصغيرة،
            # فيصير ارتفاع كل صفٍّ بقدر محتواه: صفٌّ بيانه سطرٌ يبقى
            # قصيراً وصفٌّ بيانه طويل يعلو ثلاثة أضعاف — وهو ما شُكي
            # منه بـ«صفٌّ واسع وصفٌّ قصير وصفٌّ كبير». ارتفاع الصف
            # صار من شأن `fill`/`bulk_rows`/`ledger_rows`: واحدٌ
            # دائماً، وما طال من النصّ يُقصّ ويبقى في التلميح.
        except Exception:
            pass
        finally:
            self._busy = False


def fit_columns(table, weights=None, min_px=42):
    """يُركّب المُحجِّم على جدول ويعيده.

    يُستدعى مرة واحدة بعد إنشاء الجدول؛ ويكفي `fitter.apply()` بعد كل
    تعبئة بيانات (أو تلقائياً عند تغيّر الحجم).
    """
    existing = table.property("_fitter")
    if existing is not None:
        if weights:
            existing.set_weights(weights)
        else:
            existing.refit()
        return existing
    f = ColumnFitter(table, weights or [], min_px)
    table.setProperty("_fitter", f)
    return f


# ══════════════════════════════════════════════════════════════════
# التناسب مع حجم الشاشة
# ══════════════════════════════════════════════════════════════════

def screen_scale(app=None):
    """معامل تناسب من عرض شاشة المستخدم.

    شاشة 1366 → 0.85 · شاشة 1920 → 1.0 · شاشة 2560 → 1.15
    فتصغر الخطوط والحشو على الأجهزة الصغيرة وتكبر على الكبيرة.
    """
    try:
        app = app or QtWidgets.QApplication.instance()
        g = app.primaryScreen().availableGeometry()
        w = g.width()
        if not isinstance(w, int) or w <= 0:
            return 1.0
        if w <= 1366:
            return 0.85
        if w <= 1600:
            return 0.92
        if w <= 1920:
            return 1.0
        return 1.12
    except Exception:
        return 1.0


def apply_screen_scale(app=None):
    """يضبط خط التطبيق بحسب حجم الشاشة — مرة واحدة عند الإقلاع."""
    try:
        app = app or QtWidgets.QApplication.instance()
        s = screen_scale(app)
        f = app.font()
        base = f.pointSize()
        if isinstance(base, int) and base > 0:
            f.setPointSize(max(7, int(round(base * s))))
            app.setFont(f)
        return s
    except Exception:
        return 1.0
