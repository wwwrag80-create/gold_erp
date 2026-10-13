# -*- coding: utf-8 -*-
"""جدولٌ محاسبي على نموذج بيانات — `QTableView` لا `QTableWidget` (4.69).

**لماذا نموذج**: `QTableWidget` يُنشئ عنصراً لكل خلية؛ ألف مستندٍ في
تسعة أعمدة تسعة آلاف عنصر تُبنى قبل أن يُرى سطر. هنا البيانات قائمةٌ
واحدة في الذاكرة، والجدول يطلب منها ما يظهر على الشاشة وحده — فيفتح
سجلٌّ بعشرة آلاف سطرٍ كما يفتح بعشرة.

وما يكسبه المحاسب فوق السرعة:

· **فرزٌ رقمي صحيح**: النقر على «الإجمالي» يرتّب 9,500 قبل 10,200 — لا
  «1» قبل «9» كما يرتّب النصّ.
· **تصفيةٌ فورية** في كل الأعمدة بتطبيعٍ عربي («الافق» تجد «الأفق»)
  بلا رجوعٍ إلى القاعدة.
· **صفّ إجمالي حيّ**: مجموع أعمدة المبالغ والأوزان **لما يظهر الآن** —
  صفِّ النتائج ويتغيّر المجموع معها، ويبقى آخر الجدول مهما رُتّب.
· **السالب بالأحمر** والأرقام بفواصل الآلاف ومحاذاةٍ واحدة.
· نسخٌ وتصديرٌ إلى Excel من الزرّ الأيمن، وبحث Ctrl+F كبقية الجداول.

يُرسم بصفوف Fluent (`ui.kit.TableView`) إن وُجدت المكتبة، أو `QTableView`
بنمط النظام إن غابت.
"""
import csv
import datetime as _dt

from PyQt5 import QtCore, QtGui, QtWidgets

from ui import kit

TEXT, MONEY, WEIGHT, NUMBER = "text", "money", "weight", "number"
SUMMED = (MONEY, WEIGHT)
TOTAL_LABEL = "الإجمالي"

try:                                    # دقة الأوزان من إعداد النظام (3)
    import config as _cfg
    _WD = int(getattr(_cfg, "WEIGHT_DECIMALS", 3))
except Exception:
    _WD = 3
SORT_ROLE = QtCore.Qt.UserRole + 1


def _norm(text):
    from ui.widgets.common import _norm as n
    return n(str(text or ""))


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def guess_kinds(headers, rows):
    """نوع كل عمود من عنوانه وقيمه: أرقامٌ تُجمع، ومعرّفاتٌ لا تُجمع.

    «رقم القيد» و«الرقم» أعدادٌ لكنها أسماءُ مستندات — جمعها هراء.
    """
    kinds = []
    sample = rows[:200]
    for c, h in enumerate(headers):
        vals = [r[c] for r in sample if c < len(r) and r[c] not in (None, "")]
        numeric = bool(vals) and all(_num(v) is not None for v in vals)
        if not numeric:
            kinds.append(TEXT)
        elif "رقم" in h or h in ("الرقم", "العدد"):
            kinds.append(NUMBER)
        elif any(k in h for k in ("وزن", "ذهب", "مكافئ", "الفاقد", "منصرف",
                                  "متوقع", "فعلي", "الأحجار", "(جم", " جم")):
            # «جم» وحدها تطابق «الإجمالي» — فتُطلب وحدةً لا مقطعاً
            kinds.append(WEIGHT)
        else:
            kinds.append(MONEY)
    return kinds


def fmt(v, kind):
    if v is None:
        return ""
    n = _num(v)
    if n is None:
        return str(v)
    if kind == NUMBER:
        return str(int(n)) if n == int(n) else str(n)
    if kind == WEIGHT:
        return f"{n:,.{_WD}f}"
    return f"{n:,.2f}"


class LedgerModel(QtCore.QAbstractTableModel):
    """الصفوف كما جاءت من القاعدة (قيمٌ خام) — والتنسيق عند العرض.

    الصفّ قد يحمل قيماً أكثر من الأعمدة (رقم القيد خلف آخر عمود): تبقى
    مع صفّها لمن يطلبها (`row_values`) ولا تُعرض.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.headers, self.kinds, self.rows = [], [], []
        self.totals = None          # قيم صفّ الإجمالي أو None

    # ── البيانات ──
    def set_data(self, headers, rows, kinds=None):
        self.beginResetModel()
        self.headers = [str(h) for h in headers]
        self.rows = [list(r) for r in rows]
        self.kinds = list(kinds or guess_kinds(self.headers, self.rows))
        while len(self.kinds) < len(self.headers):
            self.kinds.append(TEXT)
        self.totals = None
        self.endResetModel()

    def has_sums(self):
        return any(k in SUMMED for k in self.kinds)

    def set_totals(self, values):
        """يضع صفّ الإجمالي (أو يرفعه بـ`None`) دون إعادة بناء الجدول."""
        had = self.totals is not None
        n = len(self.rows)
        if values is None:
            if had:
                self.beginRemoveRows(QtCore.QModelIndex(), n, n)
                self.totals = None
                self.endRemoveRows()
            return
        if not had:
            self.beginInsertRows(QtCore.QModelIndex(), n, n)
            self.totals = list(values)
            self.endInsertRows()
        else:
            self.totals = list(values)
            self.dataChanged.emit(self.index(n, 0),
                                  self.index(n, len(self.headers) - 1))

    def is_total(self, row):
        return self.totals is not None and row == len(self.rows)

    def row_values(self, row):
        if 0 <= row < len(self.rows):
            return list(self.rows[row])
        return None

    # ── واجهة النموذج ──
    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else (
            len(self.rows) + (1 if self.totals is not None else 0))

    def columnCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if (orientation == QtCore.Qt.Horizontal and role == QtCore.Qt.DisplayRole
                and 0 <= section < len(self.headers)):
            return self.headers[section]
        return None

    def _raw(self, r, c):
        if self.is_total(r):
            return self.totals[c] if c < len(self.totals) else None
        row = self.rows[r]
        return row[c] if c < len(row) else None

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None
        r, c = index.row(), index.column()
        kind = self.kinds[c] if c < len(self.kinds) else TEXT
        v = self._raw(r, c)
        total = self.is_total(r)
        if role == QtCore.Qt.DisplayRole:
            return fmt(v, kind)
        if role == SORT_ROLE:
            n = _num(v)
            return n if n is not None else _norm(v)
        if role == QtCore.Qt.TextAlignmentRole:
            if kind != TEXT:
                # `AlignAbsolute`: بدونها يقلب Qt «اليمين» في الواجهة العربية
                return int(QtCore.Qt.AlignRight | QtCore.Qt.AlignAbsolute
                           | QtCore.Qt.AlignVCenter)
            return int(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        if role == QtCore.Qt.ForegroundRole:
            if total:
                return QtGui.QBrush(_total_colors()[1])
            n = _num(v)
            if n is not None and n < 0 and kind in SUMMED:
                return QtGui.QBrush(_red())
            return None
        if role == QtCore.Qt.BackgroundRole and total:
            return QtGui.QBrush(_total_colors()[0])
        if role == QtCore.Qt.FontRole and total:
            f = QtWidgets.QApplication.font()
            f.setBold(True)
            return f
        if role == QtCore.Qt.ToolTipRole:
            s = fmt(v, kind)
            return s if len(s) > 14 else None
        return None


def _total_colors():
    try:
        from ui.widgets.common import total_colors
        return total_colors()
    except Exception:
        return QtGui.QColor("#1C1A17"), QtGui.QColor("#FFFFFF")


def _red():
    try:
        from ui import theme
        return QtGui.QColor(theme.palette(theme.current_theme())["redText"])
    except Exception:
        return QtGui.QColor("#9A1414")


class LedgerProxy(QtCore.QSortFilterProxyModel):
    """فرزٌ بالقيمة لا بالنصّ، وتصفيةٌ عربية — وصفّ الإجمالي آخراً دائماً."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._q = ""
        self.setSortRole(SORT_ROLE)

    def set_query(self, text):
        self._q = _norm(text).strip()
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        m = self.sourceModel()
        if m.is_total(row) or not self._q:
            return True
        cols = m.columnCount()
        values = m.rows[row]
        return any(self._q in _norm(fmt(values[c], m.kinds[c]))
                   for c in range(min(cols, len(values))))

    def lessThan(self, left, right):
        m = self.sourceModel()
        asc = self.sortOrder() == QtCore.Qt.AscendingOrder
        if m.is_total(left.row()):
            return not asc
        if m.is_total(right.row()):
            return asc
        a, b = left.data(SORT_ROLE), right.data(SORT_ROLE)
        if isinstance(a, float) and isinstance(b, float):
            return a < b
        if isinstance(a, float) != isinstance(b, float):
            return isinstance(a, float)        # الأرقام قبل النصوص
        return str(a) < str(b)


class LedgerView(kit.TableView):
    """جدول الكشوف الكبيرة: `set_data` · `set_filter` · `current_values`."""

    rowActivated = QtCore.pyqtSignal(list)

    def __init__(self, parent=None, totals=True):
        super().__init__(parent)
        self.setObjectName("ledgerView")
        self.source = LedgerModel(self)
        self.proxy = LedgerProxy(self)
        self.proxy.setSourceModel(self.source)
        self.setModel(self.proxy)
        self._totals = bool(totals)
        self.setSortingEnabled(True)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.setWordWrap(False)
        self.setTextElideMode(QtCore.Qt.ElideRight)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        hh.setDefaultAlignment(QtCore.Qt.AlignCenter)
        hh.setHighlightSections(False)
        hh.setSortIndicatorShown(True)
        try:
            from ui.widgets.common import row_height
            self.verticalHeader().setDefaultSectionSize(row_height(self))
        except Exception:
            pass
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.doubleClicked.connect(self._activated)
        # بلا فرزٍ في أول عرض: الترتيب ترتيب القاعدة (الأحدث أولاً)
        hh.setSortIndicator(-1, QtCore.Qt.AscendingOrder)

    # ── البيانات ──
    def set_data(self, headers, rows, kinds=None):
        hh = self.horizontalHeader()
        col, order = hh.sortIndicatorSection(), hh.sortIndicatorOrder()
        self.source.set_data(headers, rows, kinds)
        self._refresh_totals()
        if 0 <= col < len(headers):
            self.sortByColumn(col, order)
        else:
            self.proxy.sort(-1)
            hh.setSortIndicator(-1, QtCore.Qt.AscendingOrder)

    def set_filter(self, text):
        self.proxy.set_query(text)
        self._refresh_totals()

    def _refresh_totals(self):
        m = self.source
        if not (self._totals and m.rows and m.has_sums()):
            m.set_totals(None)
            return
        shown = [self.proxy.mapToSource(self.proxy.index(i, 0)).row()
                 for i in range(self.proxy.rowCount())]
        shown = [r for r in shown if not m.is_total(r)]
        vals = []
        for c, kind in enumerate(m.kinds[:len(m.headers)]):
            if kind in SUMMED:
                vals.append(sum(_num(m.rows[r][c]) or 0.0 for r in shown
                                if c < len(m.rows[r])))
            else:
                vals.append(None)
        # العنوان في أول عمودٍ نصّي — حيث تبحث عنه العين
        for c, kind in enumerate(m.kinds[:len(m.headers)]):
            if kind not in SUMMED:
                vals[c] = f"{TOTAL_LABEL} ({len(shown):,})"
                break
        m.set_totals(vals)

    # ── القراءة ──
    def shown_count(self):
        n = self.proxy.rowCount()
        return n - (1 if self.source.totals is not None else 0)

    def current_source_row(self):
        idx = self.currentIndex()
        if not idx.isValid():
            return -1
        r = self.proxy.mapToSource(idx).row()
        return -1 if self.source.is_total(r) else r

    def current_values(self):
        """القيم الخام للسطر المحدد (مع ما خلف آخر عمود) — أو None."""
        return self.source.row_values(self.current_source_row())

    def select_first(self):
        if self.shown_count() > 0:
            self.setCurrentIndex(self.proxy.index(0, 0))

    def rows_matrix(self, include_header=True):
        """ما يظهر الآن (بعد التصفية والفرز) — نصوصٌ للتصدير والنسخ."""
        out = [list(self.source.headers)] if include_header else []
        for i in range(self.proxy.rowCount()):
            out.append([self.proxy.index(i, c).data() or ""
                        for c in range(self.proxy.columnCount())])
        return out

    # ── التصدير والنسخ ──
    def copy_all(self):
        text = "\n".join("\t".join(r) for r in self.rows_matrix())
        QtWidgets.QApplication.clipboard().setText(text)
        return True

    def export_csv(self, parent=None, suggested="كشف"):
        from ui.widgets.common import err, info
        parent = parent or self.window()
        try:
            if not self.source.rows:
                info(parent, "لا توجد بيانات للتصدير.", "تصدير")
                return None
            stamp = _dt.datetime.now().strftime("%Y-%m-%d_%H%M")
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                parent, "حفظ الكشف", f"{suggested}_{stamp}.csv",
                "ملف Excel/CSV (*.csv)")
            if not path:
                return None
            if not path.lower().endswith(".csv"):
                path += ".csv"
            # `utf-8-sig`: علامة الترتيب التي يقرأ بها Excel العربية سليمة
            with open(path, "w", encoding="utf-8-sig", newline="") as fh:
                csv.writer(fh).writerows(self.rows_matrix())
            info(parent, f"حُفظ الكشف:\n{path}", "تم التصدير")
            return path
        except Exception as e:
            err(parent, f"تعذّر التصدير: {e}")
            return None

    def _menu(self, pos):
        items = [("نسخ الجدول (يُلصق في Excel)", self.copy_all, "COPY"),
                 ("تصدير إلى Excel/CSV…", lambda: self.export_csv(), "DOWNLOAD")]
        kit.popup_menu(self, items, self.viewport().mapToGlobal(pos))

    def _activated(self, idx):
        vals = self.current_values()
        if vals is not None:
            self.rowActivated.emit(vals)
