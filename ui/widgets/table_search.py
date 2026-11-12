# -*- coding: utf-8 -*-
"""بحثٌ فوريّ داخل أي جدول — Ctrl+F من أي شاشة.

**لماذا**: الجداول هنا تطول إلى مئات الأسطر (كشف حساب سنة، دليل
الموديلات، أعمار الديون). وكان البحث عن سطرٍ بعينه تمريراً بالعين —
أو شاشةً لها خانة بحثها الخاصة وأخرى بلا خانة.

**الآن**: Ctrl+F على أي جدول يُظهر شريطاً صغيراً في أسفله؛ ما يُكتب فيه
يُبقي الأسطر التي تحويه ويُخفي غيرها لحظةً بلحظة، ويقول «٣ من ١٢٠».
البحث يتجاهل الهمزات والتاء المربوطة والألف المقصورة (كما في كل بحث
النظام)، وأرقامه العربية كالإنجليزية. وصفّ الإجمالي يبقى ظاهراً دائماً.
Esc يغلق الشريط ويعيد الجدول كما كان — فلا يتغيّر فيه شيء.

عرضٌ محض: لا يمسّ بيانات الجدول ولا ترتيبه ولا أي رقم.
"""
from PyQt5 import QtCore, QtWidgets

from ui import kit

_BAR_PROP = "_search_bar"
# نصٌّ خفيّ يُبحث فيه مع نصّ السطر (5.2.4) — على خلية العمود الأول.
# كشف الحساب يضع فيه أرقام تشغيل أطقم الفاتورة: فمن كتب رقم تشغيلٍ ظهرت
# الفواتير التي هو فيها، ولو لم يُكتب الرقم في السطر نفسه.
SEARCH_ROLE = QtCore.Qt.UserRole + 91   # (77: صفّ الإجمالي)


def _extra(table, row):
    try:
        it = table.item(row, 0)
        return str(it.data(SEARCH_ROLE) or "") if it is not None else ""
    except Exception:
        return ""


def _norm(text):
    from ui.widgets.common import _norm as base
    from ui.widgets.smart_input import normalize
    return base(normalize(text or ""))


# 5.3.5: الأرقام تُعرض بفواصل الآلاف («6,469.00») ويكتبها المستخدم بلا
# فاصل («6469») — فلا يطابق النصُّ النصَّ والرقمُ موجودٌ في الكشف. تُحذف
# الفواصل من الطرفين حين يكون المكتوب رقماً، فيُوجد في عمودي الذهب
# (مدين · دائن) وعمودي الأجور/النقد وفي كل جدول.
_SEPS = str.maketrans("", "", ",٬ \u066c")
_NUMQ = __import__("re").compile(r"^[-+]?[\d.,٬\s]*\d[\d.,٬\s]*$")


def matcher(q):
    """دالةُ مطابقة لنصّ البحث (مطبَّعاً): تطابق النصّ كما هو، والرقمَ
    بلا فواصل آلاف إن كان المكتوب رقماً."""
    q = (q or "").strip()
    if not q:
        return lambda _t: True
    if _NUMQ.match(q):
        qn = q.translate(_SEPS)
        return lambda t: q in t or qn in (t or "").translate(_SEPS)
    return lambda t: q in (t or "")


def _is_total(table, row):
    try:
        from ui.widgets.table_tools import TOTAL_ROLE
        it = table.item(row, 0)
        return bool(it is not None and it.data(TOTAL_ROLE))
    except Exception:
        return False


class SearchBar(QtWidgets.QFrame):
    """الشريط العائم فوق الجدول."""

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.setObjectName("tableSearch")
        self.edit = kit.LineEdit()
        self.edit.setObjectName("tableSearchInput")
        self.edit.setPlaceholderText("🔍 ابحث في الجدول…")
        self.edit.setClearButtonEnabled(True)
        self.edit.setMinimumWidth(240)
        self.count = QtWidgets.QLabel("")
        self.count.setObjectName("tableSearchCount")
        close = QtWidgets.QToolButton()
        close.setText("✕")
        close.setToolTip("إغلاق البحث (Esc)")
        close.clicked.connect(self.close_bar)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(6)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.count)
        lay.addWidget(close)
        # (5.2.9) الجدول الكبير يُصفّى بعد أن تهدأ الكتابة لا مع كل حرف
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(220)
        self._timer.timeout.connect(lambda: self.apply())
        self.edit.textChanged.connect(self._typed)
        self.edit.returnPressed.connect(self._now)
        self.edit.installEventFilter(self)
        view.installEventFilter(self)
        self.hide()

    # ── الموضع: أسفل الجدول من جهة البداية (يمين العربية) ──
    # أسفلُه لا أعلاه: أعلاه رأسُ الأعمدة، وتغطيتُه تُخفي أسماء ما يُبحث
    # فيه. والأسفل يغطّي أسطراً تُصفّى أصلاً فيقلّ عددها.
    def reposition(self):
        self.adjustSize()
        w = min(max(380, self.sizeHint().width()), self.view.width() - 16)
        h = self.sizeHint().height()
        self.resize(w, h)
        x = (self.view.width() - w - 10
             if self.view.layoutDirection() == QtCore.Qt.RightToLeft else 10)
        self.move(max(0, x), max(0, self.view.height() - h - 10))

    def eventFilter(self, obj, ev):
        if obj is self.edit and ev.type() == QtCore.QEvent.KeyPress:
            if ev.key() == QtCore.Qt.Key_Escape:
                self.close_bar()
                return True
        if obj is self.view and ev.type() == QtCore.QEvent.Resize \
                and self.isVisible():
            self.reposition()
        return False

    def open_bar(self):
        hint = self.view.property("searchHint")
        if hint:
            self.edit.setPlaceholderText(str(hint))
        self.reposition()
        self.show()
        self.raise_()
        self.edit.setFocus()
        self.edit.selectAll()
        self.apply(self.edit.text())

    def close_bar(self):
        self._timer.stop()
        self.edit.blockSignals(True)
        self.edit.clear()
        self.edit.blockSignals(False)
        self.apply("")
        self.hide()
        self.view.setFocus()

    # ── التصفية ──
    BIG = 300          # فوقه تُدمج الحروف المتتابعة في تصفيةٍ واحدة

    def _rows(self):
        try:
            m = self.view.model()
            return m.rowCount() if m is not None else 0
        except Exception:
            return 0

    def _typed(self, text):
        if self._rows() > self.BIG and self.edit.hasFocus():
            self._timer.start()
        else:
            self._timer.stop()
            self.apply(text)

    def _now(self):
        if self._timer.isActive():
            self._timer.stop()
            self.apply()

    def apply(self, text=None):
        v = self.view
        # إخفاء الصفوف وإظهارها بلا رسمٍ بينها — رسمةٌ واحدة في الآخر
        try:
            v.setUpdatesEnabled(False)
            self._apply(text)
        finally:
            try:
                v.setUpdatesEnabled(True)
            except Exception:
                pass

    def _apply(self, text=None):
        q = _norm(self.edit.text() if text is None else text).strip()
        has = matcher(q)
        v = self.view
        shown = total = 0
        if isinstance(v, QtWidgets.QTableWidget):
            cols = v.columnCount()
            for r in range(v.rowCount()):
                if _is_total(v, r):
                    v.setRowHidden(r, False)
                    continue
                total += 1
                hit = not q or any(
                    has(_norm(v.item(r, c).text()))
                    for c in range(cols) if v.item(r, c) is not None) \
                    or has(_norm(_extra(v, r)))
                v.setRowHidden(r, not hit)
                shown += int(hit)
        elif hasattr(v, "set_filter"):
            # جدول النموذج (`ledger_view`): التصفية في النموذج نفسه
            v.set_filter(q)
            shown, total = v.shown_count(), len(v.source.rows)
        elif isinstance(v, QtWidgets.QTreeWidget):
            root = v.invisibleRootItem()
            for i in range(root.childCount()):
                top = root.child(i)
                total += 1
                hit = not q or self._tree_hit(top, q)
                top.setHidden(not hit)
                shown += int(hit)
        self.count.setText("" if not q else f"{shown:,} من {total:,}")

    def _tree_hit(self, item, q):
        has = matcher(q)
        if any(has(_norm(item.text(c))) for c in range(item.columnCount())):
            return True
        return any(self._tree_hit(item.child(i), q)
                   for i in range(item.childCount()))


def bar_for(view):
    b = view.property(_BAR_PROP)
    if not isinstance(b, SearchBar):
        b = SearchBar(view)
        view.setProperty(_BAR_PROP, b)
    return b


def target_view(start=None):
    """الجدول المقصود: ما عليه التركيز، وإلا أكبر جدولٍ ظاهر في الشاشة."""
    w = start or QtWidgets.QApplication.focusWidget()
    while w is not None:
        if isinstance(w, SearchBar):
            return w.view
        if isinstance(w, (QtWidgets.QTableWidget, QtWidgets.QTreeWidget)):
            return w
        if hasattr(w, "set_filter") and isinstance(w, QtWidgets.QTableView):
            return w
        w = w.parentWidget()
    return None


def largest_visible(root):
    best, area = None, 0
    if root is None:
        return None
    for v in root.findChildren((QtWidgets.QTableWidget,
                                QtWidgets.QTreeWidget,
                                QtWidgets.QTableView)):
        if not v.isVisible() or v.objectName() == "sidebar":
            continue
        if (isinstance(v, QtWidgets.QTableView)
                and not isinstance(v, QtWidgets.QTableWidget)
                and not hasattr(v, "set_filter")):
            continue
        a = v.width() * v.height()
        if a > area:
            best, area = v, a
    return best


def open_search(view):
    if view is None:
        return None
    b = bar_for(view)
    b.open_bar()
    return b


def active_filter(root):
    """(الجدول، نصّ البحث) إن كان في `root` جدولٌ يرشّحه البحث الآن.

    تستعمله الطباعة (5.0.1): الورقة تُطبع بما يظهر على الشاشة، فإن رشّح
    البحث جدولاً طُبع ذلك الجدول كما هو لا كل أسطره من القاعدة."""
    if root is None:
        return None
    try:
        views = root.findChildren(QtWidgets.QAbstractItemView)
    except Exception:
        return None
    for v in views:
        b = v.property(_BAR_PROP)
        if not isinstance(b, SearchBar):
            continue
        try:
            q = (b.edit.text() or "").strip()
            if q and b.isVisible() and v.isVisible():
                return v, q
        except Exception:
            continue
    return None
