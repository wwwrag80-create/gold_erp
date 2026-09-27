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

_BAR_PROP = "_search_bar"


def _norm(text):
    from ui.widgets.common import _norm as base
    from ui.widgets.smart_input import normalize
    return base(normalize(text or ""))


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
        self.edit = QtWidgets.QLineEdit()
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
        self.edit.textChanged.connect(self.apply)
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
        self.reposition()
        self.show()
        self.raise_()
        self.edit.setFocus()
        self.edit.selectAll()
        self.apply(self.edit.text())

    def close_bar(self):
        self.edit.blockSignals(True)
        self.edit.clear()
        self.edit.blockSignals(False)
        self.apply("")
        self.hide()
        self.view.setFocus()

    # ── التصفية ──
    def apply(self, text=None):
        q = _norm(self.edit.text() if text is None else text).strip()
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
                    q in _norm(v.item(r, c).text())
                    for c in range(cols) if v.item(r, c) is not None)
                v.setRowHidden(r, not hit)
                shown += int(hit)
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
        if any(q in _norm(item.text(c)) for c in range(item.columnCount())):
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
        w = w.parentWidget()
    return None


def largest_visible(root):
    best, area = None, 0
    if root is None:
        return None
    for v in root.findChildren((QtWidgets.QTableWidget,
                                QtWidgets.QTreeWidget)):
        if not v.isVisible() or v.objectName() == "sidebar":
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
