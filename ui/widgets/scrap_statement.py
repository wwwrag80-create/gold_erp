# -*- coding: utf-8 -*-
"""كشف صندوق الكسر لعيارٍ واحد — من لوحة التحكم.

النقر على «عيار 18» في لوحة صناديق الكسر يفتح حركة الكسر 18 وحده:
الوارد والصادر بالوزن الفعلي، والرصيد المتراكم بعياره وبمكافئه —
بتاريخ كل حركة ورقم سندها والجهة المقابلة. والنقر المزدوج على سطرٍ
يفتح السند نفسه. (كشف الحساب 1310 يخلط الأعيرة لأنها حسابٌ واحد.)

4.79: بحثٌ في الكشف (خانةٌ فوقه و Ctrl+F) يُبقي الأسطر المطابقة، و«معاينة»
و«طباعة» تُخرجان ما يظهر — نتيجة البحث وحدها إن كان بحث، وإلا الكشف كله.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from ui import kit

from database.database import db
from services import karat_view as kv
from ui.widgets.common import err, make_table, title_label
from services import numfmt as _nf
from ui.widgets.common import guard_click


def _w(v):
    return _nf.f2(v) if abs(v) >= 0.005 else ""


class ScrapKaratDialog(QtWidgets.QDialog):
    def __init__(self, parent, karat, date_from=None, date_to=None):
        super().__init__(parent)
        self.karat = int(karat)
        self.date_from = date_from or None
        self.date_to = date_to or None
        self.rows = []
        self.setWindowTitle(f"كشف صندوق الكسر — عيار {self.karat}")
        self.setLayoutDirection(QtCore.Qt.RightToLeft)
        self.resize(1120, 620)

        per = (f"من {self.date_from} إلى {self.date_to or 'اليوم'}"
               if self.date_from else
               (f"حتى {self.date_to}" if self.date_to else "كل الحركات"))
        sub = QtWidgets.QLabel(
            f"{per} · الأوزان فعلية بعيار {self.karat} · النقر المزدوج على"
            " أي سطر يفتح السند الذي أنشأه")
        sub.setWordWrap(True)
        self.table = make_table()
        self.table.doubleClicked.connect(guard_click(lambda *_: self.open_selected()))
        self.summary = QtWidgets.QLabel("")
        self.summary.setObjectName("big")
        self.summary.setWordWrap(True)

        # ── البحث: خانةٌ ظاهرة، و Ctrl+F يضع المؤشر فيها ──
        self.search = kit.LineEdit()
        self.search.setPlaceholderText(
            "🔍 ابحث في الكشف: رقم سند · جهة · بيان · وزن…  (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_search)
        self.found = QtWidgets.QLabel("")
        srow = QtWidgets.QHBoxLayout()
        srow.addWidget(self.search, 1)
        srow.addWidget(self.found)
        sc = QtWidgets.QShortcut(QtGui.QKeySequence.Find, self)
        sc.activated.connect(self.focus_search)
        self._find_sc = sc

        b_open = kit.PushButton("👁 فتح السند المحدد")
        b_open.setObjectName("homeBtn")
        b_open.clicked.connect(self.open_selected)
        b_prev = kit.PushButton("🖨 معاينة")
        b_prev.setToolTip("معاينة الكشف — نتيجة البحث وحدها إن كان بحث")
        b_prev.clicked.connect(self.preview)
        b_print = kit.PushButton("طباعة")
        b_print.clicked.connect(self.print_now)
        b_close = kit.PushButton("إغلاق")
        b_close.setObjectName("ghost")
        b_close.clicked.connect(self.reject)
        btns = QtWidgets.QHBoxLayout()
        btns.addWidget(b_open)
        btns.addWidget(b_prev)
        btns.addWidget(b_print)
        btns.addStretch(1)
        btns.addWidget(b_close)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label(f"صندوق الكسر — عيار {self.karat}"))
        lay.addWidget(sub)
        lay.addLayout(srow)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.summary)
        lay.addLayout(btns)
        self.load()

    def load(self):
        from models.inventory import scrap_karat_statement
        with db(readonly=True) as conn:
            st = scrap_karat_statement(conn, self.karat, self.date_from,
                                       self.date_to)
        self.rows = st["rows"]
        k = self.karat
        cols = [("التاريخ", 9), ("نوع العملية", 10), ("رقم السند", 9),
                ("الجهة / الحساب المقابل", 17), ("البيان", 14),
                (f"وارد\nعيار {k}", 9), (f"صادر\nعيار {k}", 9),
                (f"الرصيد\nعيار {k}", 11),
                (f"الرصيد\nبمكافئ {kv.active()}", 12)]
        t = self.table
        t.setUpdatesEnabled(False)
        try:
            t.clear()
            t.setColumnCount(len(cols))
            t.setHorizontalHeaderLabels([c for c, _w0 in cols])
            t.setRowCount(len(self.rows))
            bold = QtGui.QFont(t.font())
            bold.setBold(True)
            for i, r in enumerate(self.rows):
                vals = [r["date"] or "", r["op"], str(r["doc_no"] or ""),
                        r["name"], r["desc"], _w(r["inw"]), _w(r["outw"]),
                        f"{_nf.f2(r['bal'])}", f"{_nf.f2(kv.g(r['bal18']))}"]
                for c, s in enumerate(vals):
                    it = QtWidgets.QTableWidgetItem(s)
                    it.setTextAlignment(
                        (QtCore.Qt.AlignRight if c in (3, 4)
                         else QtCore.Qt.AlignCenter) | QtCore.Qt.AlignVCenter)
                    if c in (3, 4) and s:
                        it.setToolTip(s)
                    if c in (2, 7) or r["op"] == "رصيد سابق":
                        it.setFont(bold)
                    t.setItem(i, c, it)
        finally:
            t.setUpdatesEnabled(True)
        try:
            from ui.widgets.table_fit import fit_columns
            fit_columns(t, [w for _c, w in cols])
        except Exception:
            pass
        self.apply_search()
        n = sum(1 for r in self.rows if r["op"] != "رصيد سابق")
        self.summary.setText(
            f"عدد الحركات: {n}\n"
            f"عيار {k}: أول الفترة {_nf.f2(st['opening'])} · وارد"
            f" {_nf.f2(st['total_in'])} · صادر {_nf.f2(st['total_out'])} ·"
            f" الرصيد {_nf.f2(st['closing'])} جم")

    # ══ البحث ══
    def focus_search(self):
        self.search.setFocus()
        self.search.selectAll()

    def _query(self):
        from ui.widgets.table_search import _norm
        return _norm(self.search.text()).strip()

    def apply_search(self, *_):
        """يُبقي الأسطر التي تحوي ما كُتب (بتجاهل الهمزات والأرقام العربية)."""
        from ui.widgets.table_search import _norm
        q = self._query()
        t = self.table
        shown = 0
        for i in range(t.rowCount()):
            hit = not q or any(
                q in _norm(t.item(i, c).text())
                for c in range(t.columnCount()) if t.item(i, c) is not None)
            t.setRowHidden(i, not hit)
            shown += int(hit)
        self.found.setText(f"{shown:,} من {t.rowCount():,}" if q else "")

    def visible_rows(self):
        """أرقام الأسطر الظاهرة — None إن لم يكن بحث (الكشف كله)."""
        if not self._query():
            return None
        return [i for i in range(self.table.rowCount())
                if not self.table.isRowHidden(i)]

    def _print_kw(self):
        return {"date_from": self.date_from, "date_to": self.date_to,
                "only": self.visible_rows(),
                "query": self.search.text().strip()}

    def preview(self):
        try:
            from services import print_manager
            print_manager.preview_document(self, "scrap_karat", self.karat,
                                           **self._print_kw())
        except Exception as e:
            err(self, e)

    def print_now(self):
        try:
            from services import print_manager
            print_manager.print_document(self, "scrap_karat", self.karat,
                                         **self._print_kw())
        except Exception as e:
            err(self, e)

    def open_selected(self):
        try:
            i = self.table.currentRow()
            if not (0 <= i < len(self.rows)):
                raise ValueError("اختر سطراً من الكشف أولاً")
            r = self.rows[i]
            if not r.get("eid"):
                raise ValueError("هذا السطر ليس سنداً واحداً"
                                 " (رصيد سابق أو تسوية)")
            from services import print_manager
            from ui.general_ledger_screen import _doc_target
            target = _doc_target(r, print_manager.BUILDERS)
            if target is None:
                raise ValueError("لا مستند مرتبط بهذا السطر")
            print_manager.preview_document(self, *target)
        except Exception as e:
            err(self, e)
