"""Qt stub يحاكي PyQt5 بدقة كافية لكشف الأخطاء الحقيقية.

الأهم: لا يبتلع الأسماء المجهولة. PyQt5 الحقيقي يرفع AttributeError
لأي اسم خارج واجهته، ولهذا يجب أن يفعل الـstub الشيء نفسه — وإلا
اختفت أخطاء مثل «دالة مربوطة بزر وغير معرَّفة» أو «خاصية تُستخدم قبل
إنشائها».

القاعدة: أسماء Qt بصيغة camelCase (setText، currentIndex) أو ضمن قائمة
الأسماء المفردة المعروفة → تُقبل. أي اسم آخر (snake_case أو كلمة من
مفرداتنا مثل crumb أو print_statement) → AttributeError كما في الواقع.
"""
import sys, types

class _Sig:
    def __init__(self, *a, **k): self._s = []
    def connect(self, f=None, *a, **k):
        if f is not None:
            if not callable(f):
                raise TypeError(f"connect() requires a callable, got {f!r}")
            self._s.append(f)
    def disconnect(self, *a, **k): pass
    def emit(self, *a, **k):
        for f in list(self._s): f(*a, **k)

_SIGNALS = ("clicked", "currentIndexChanged", "valueChanged", "textChanged",
            "returnPressed", "doubleClicked", "itemSelectionChanged",
            "currentRowChanged", "accepted", "rejected", "cellChanged",
            "editingFinished", "toggled", "stateChanged", "activated",
            "itemClicked", "customContextMenuRequested", "paintRequested",
            "triggered", "pressed", "released",
            "timeout", "done", "failed", "finished", "started",
            "itemChanged", "rowsMoved", "rowsInserted", "dataChanged")

# أسماء Qt المفردة (بلا حرف كبير) التي يجب قبولها
_QT_WORDS = {
    "start", "stop", "quit", "wait", "run", "emit", "isRunning",
    "singleShot", "currentTime", "toString",
    "show", "hide", "close", "update", "repaint", "font", "layout", "parent",
    "window", "style", "width", "height", "geometry", "accept", "reject",
    "done", "move", "resize", "count", "text", "value", "clear", "model",
    "sender", "date", "time", "item", "row", "column", "index", "header",
    "children", "raise_", "exec_", "print_", "pos", "size", "rect", "grab",
    "cursor", "palette", "icon", "title", "action", "menu", "widget",
    "selectAll", "adjustSize", "activateWindow", "deleteLater", "expandAll",
    "collapseAll", "expand", "collapse", "sortItems", "topLevelItem",
    "invisibleRootItem", "viewport", "mapToGlobal", "indexAt", "addWidget",
    "addLayout", "addRow", "addItem", "addTab", "addAction", "addStretch",
    "addSeparator", "insertRow", "insertTopLevelItem", "appendRow",
    "removeRows", "resizeColumnsToContents", "resizeColumnToContents",
    "expandToDepth", "scrollToBottom", "setFocus", "selectedItems",
    "blockSignals", "installEventFilter", "removeEventFilter", "isEnabled",
    "isVisible", "isChecked", "isExpanded", "toPlainText", "toString",
    "year", "month", "day", "currentDate", "currentDateTime", "fromString",
    "addMonths", "addDays", "siblingAtColumn", "isValid", "data", "flags",
}

def _is_qt_name(name):
    if name.startswith("__"): return False
    if name in _QT_WORDS or name in _SIGNALS: return True
    if name.endswith("_") and name[:-1].isalpha(): return True   # exec_ / raise_
    # camelCase: يبدأ صغيراً ويحوي حرفاً كبيراً وبلا شرطة سفلية
    return ("_" not in name and any(c.isupper() for c in name)
            and name[0].islower())

class _Idx(int):
    """يحاكي QModelIndex ويصلح كعدد صحيح في الوقت نفسه، لأن
    currentIndex() تعيد رقماً في QComboBox وQModelIndex في العروض."""
    def isValid(self): return int(self) >= 0
    def siblingAtColumn(self, *a): return self
    def parent(self): return _Idx(-1)
    def row(self): return int(self)
    def column(self): return 0
    def data(self, *a): return None
    def model(self): return _W()


class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith("__"): raise AttributeError(name)
        return _W()          # ثوابت الأصناف: Qt.Vertical ...

class _W(metaclass=_Meta):
    def __init__(self, *a, **k):
        for n in _SIGNALS:
            object.__setattr__(self, n, _Sig())
    def __getattr__(self, name):
        if _is_qt_name(name):
            return _W()
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'")
    def __call__(self, *a, **k): return _W()
    def __setattr__(self, k, v): object.__setattr__(self, k, v)
    def value(self): return 0.0
    def text(self, *a): return ""
    def toPlainText(self): return ""
    def currentData(self, *a): return None
    def currentText(self): return ""
    def currentRow(self): return -1
    def currentIndex(self): return _Idx(-1)
    def rowCount(self): return 0
    def columnCount(self): return 0
    def findData(self, *a, **k): return -1
    def isChecked(self): return False
    def count(self): return 0
    def item(self, *a): return None
    def selectedItems(self): return []
    def toString(self, *a): return "2026-01-01"
    def year(self): return 2026
    def month(self): return 1
    def day(self): return 1
    def exec_(self): return 0
    def topLevelItem(self, *a): return None
    def indexAt(self, *a): return _Idx(-1)
    def itemFromIndex(self, *a): return None
    def indexFromItem(self, *a): return _Idx(0)
    def __int__(self): return 0
    def __index__(self): return 0
    def __bool__(self): return False
    def __iter__(self): return iter(())
    def __len__(self): return 0
    def __or__(self, other): return self
    def __ror__(self, other): return self
    def __and__(self, other): return self
    def __rand__(self, other): return self
    def __invert__(self): return self

def _mk(name):
    m = types.ModuleType(name)
    def _ga(k):
        if k.startswith("__"): raise AttributeError(k)
        return _W
    m.__getattr__ = _ga
    sys.modules[name] = m
    return m

pq = _mk("PyQt5")
for sub in ("QtWidgets", "QtCore", "QtGui", "QtPrintSupport"):
    setattr(pq, sub, _mk(f"PyQt5.{sub}"))
