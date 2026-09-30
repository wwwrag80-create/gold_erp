# -*- coding: utf-8 -*-
"""الميزانية العمومية — قائمة المركز المالي بالنهج المحاسبي المعتمد.

تبويبان:

1. **قائمة المركز المالي** — بترتيب معيار المحاسبة الدولي 1 (IAS 1)
   الذي يطلبه المراجع القانوني وهيئة الزكاة والضريبة والجمارك:
   الأصول غير المتداولة ثم المتداولة، ثم حقوق الملكية، ثم المطلوبات
   غير المتداولة والمتداولة؛ كما في تاريخ ومقارنةً بنهاية السنة
   السابقة؛ بلا مقاصّة بين الجهات المدينة والدائنة؛ والإهلاك مطروحاً
   من التكلفة؛ وصافي ربح الفترة في حقوق الملكية. السالب بين قوسين.
   نقرتان على أي بند تعرضان الحسابات التي كوّنته.

2. **تفصيل بشجرة الحسابات** — الأرصدة كما هي في الشجرة بمستوياتها،
   للتحليل الداخلي.
"""
import csv
from datetime import date

from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from models import balance_tree, statements
from services import karat_view as kv
from ui.widgets.common import (big_label, date_edit, dstr, err, info,
                               make_table, tab_widget, title_label)
from ui.widgets.flow_layout import FlowLayout
from ui.widgets.table_tools import enhance as _enhance

COLS = ["الحساب", "الكود", "النقد / الأجور (ريال)", "الذهب (جم 18)"]


def _cols():
    return ["الحساب", "الكود", "النقد / الأجور (ريال)",
            f"الذهب ({kv.unit()})"]


def money(v, gold=False):
    """مبلغ القائمة: السالب بين قوسين والصفر شرطة."""
    if gold:
        v = kv.g(v or 0.0)
        if abs(v) < 0.0005:
            return "—"
        s = f"{abs(v):,.3f}"
    else:
        v = v or 0.0
        if abs(v) < 0.005:
            return "—"
        s = f"{abs(v):,.2f}"
    return f"({s})" if v < 0 else s


# ══════════════════════════════════════════════════════════════════
#  1) قائمة المركز المالي
# ══════════════════════════════════════════════════════════════════
class FinancialPositionTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.fp = None
        self.rows = []

        today = date.today()
        self.as_of = date_edit()
        self.cmp_on = QtWidgets.QCheckBox("مقارنة بـ:")
        self.cmp_on.setChecked(True)
        self.cmp_to = date_edit()
        self.cmp_to.setDate(QtCore.QDate(today.year - 1, 12, 31))
        self.cmp_on.stateChanged.connect(
            lambda _s: self.cmp_to.setEnabled(self.cmp_on.isChecked()))

        btn = QtWidgets.QPushButton("إعداد القائمة")
        btn.setObjectName("homeBtn")
        btn.clicked.connect(self.load)
        btn_print = QtWidgets.QPushButton("🖨 معاينة وطباعة")
        btn_print.clicked.connect(self.print_sheet)
        btn_exp = QtWidgets.QPushButton("⬇ تصدير Excel")
        btn_exp.setObjectName("ghost")
        btn_exp.clicked.connect(self.export_csv)

        head = FlowLayout()
        head.setSpacing(6)
        head.addWidget(QtWidgets.QLabel("كما في:"))
        head.addWidget(self.as_of)
        head.addWidget(self.cmp_on)
        head.addWidget(self.cmp_to)
        head.addWidget(btn)
        head.addWidget(btn_print)
        head.addWidget(btn_exp)
        head.addStretch(1)

        self.table = make_table()
        _enhance(self.table, key="financial_position")
        self.table.cellDoubleClicked.connect(self.show_detail)
        self.status = big_label()
        self.status.setWordWrap(True)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(4)
        lay.addLayout(head)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.status)

    def _params(self):
        as_of = dstr(self.as_of)
        cmp_to = dstr(self.cmp_to) if self.cmp_on.isChecked() else ""
        if cmp_to and cmp_to >= as_of:
            raise ValueError("تاريخ المقارنة يجب أن يسبق تاريخ القائمة")
        return as_of, cmp_to

    def load(self):
        try:
            as_of, cmp_to = self._params()
            with db(readonly=True) as conn:
                fp = statements.financial_position(conn, as_of, cmp_to)
            self.fp = fp
            self.rows = statements.layout(fp)
            self._render()
        except Exception as e:
            err(self, e)

    def _headers(self):
        fp = self.fp
        d1, d2 = fp["as_of"], fp["compare_to"]
        h = ["البيان", f"ريال\n{d1}"]
        if d2:
            h.append(f"ريال\n{d2}")
        h.append(f"ذهب ({kv.unit()})\n{d1}")
        if d2:
            h.append(f"ذهب ({kv.unit()})\n{d2}")
        return h

    def _values(self, r):
        cmp = bool(self.fp["compare_to"])
        v = [money(r["cash"])]
        if cmp:
            v.append(money(r["cash_cmp"]))
        v.append(money(r["gold"], True))
        if cmp:
            v.append(money(r["gold_cmp"], True))
        return v

    def _render(self):
        heads = self._headers()
        tbl = self.table
        tbl.setUpdatesEnabled(False)
        try:
            tbl.clear()
            tbl.clearSpans()
            tbl.setColumnCount(len(heads))
            tbl.setHorizontalHeaderLabels(heads)
            tbl.setRowCount(len(self.rows))
            dark, sec_bg = QtGui.QColor("#2B2723"), QtGui.QColor("#EFE9DC")
            tot_bg = QtGui.QColor("#F2EEE4")
            for i, r in enumerate(self.rows):
                k = r["kind"]
                if k in ("head", "sec"):
                    vals = [r["label"]] + [""] * (len(heads) - 1)
                else:
                    pad = "\u2003\u2003" if k in ("line", "net") else ""
                    vals = [pad + r["label"]] + self._values(r)
                for c, v in enumerate(vals):
                    it = QtWidgets.QTableWidgetItem(v)
                    it.setTextAlignment(
                        (QtCore.Qt.AlignRight if c == 0
                         else QtCore.Qt.AlignCenter) | QtCore.Qt.AlignVCenter)
                    f = it.font()
                    if k != "line":
                        f.setBold(k != "net")
                        f.setItalic(k == "net")
                        it.setFont(f)
                    if k == "head":
                        it.setBackground(dark)
                        it.setForeground(QtGui.QColor("#FFFFFF"))
                    elif k == "sec":
                        it.setBackground(sec_bg)
                    elif k in ("sub", "total", "grand"):
                        it.setBackground(tot_bg)
                    if k == "line":
                        it.setToolTip("نقرتان لعرض الحسابات المكوّنة للبند")
                    tbl.setItem(i, c, it)
                if k in ("head", "sec"):
                    tbl.setSpan(i, 0, 1, len(heads))
        finally:
            tbl.setUpdatesEnabled(True)
        try:
            from ui.widgets.table_fit import fit_columns
            n = len(heads) - 1
            fit_columns(tbl, [40] + [60 // n] * n)
        except Exception:
            pass
        fp = self.fp
        ct, gt = fp["cash"]["totals"], fp["gold"]["totals"]
        ok = fp["balanced_cash"] and fp["balanced_gold"]
        self.status.setText(
            ("✔ القائمة متوازنة: مجموع الأصول = حقوق الملكية + المطلوبات"
             if ok else
             f"✘ فرق — نقد: {ct['diff']:,.2f} ريال · ذهب: "
             f"{kv.g(gt['diff']):,.3f} {kv.unit()}")
            + f"   ·   الأصول: {ct['assets']:,.2f} ريال · "
            f"{kv.g(gt['assets']):,.3f} {kv.unit()}"
            + "   ·   نقرتان على أي بند لعرض حساباته")
        self.status.setStyleSheet(
            "color:#0F5A24;font-weight:bold" if ok
            else "color:#9A0018;font-weight:bold")

    def show_detail(self, row, _col=0):
        if not self.fp or row >= len(self.rows):
            return
        r = self.rows[row]
        key = r.get("key")
        if r["kind"] != "line" or not key:
            return
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(f"تفصيل البند — {r['label']}")
        dlg.setLayoutDirection(QtCore.Qt.RightToLeft)
        dlg.resize(620, 420)
        t = make_table()
        heads = ["الكود", "الحساب", "ريال", f"ذهب ({kv.unit()})"]
        acc = {}
        for dim in ("cash", "gold"):
            for code, name, amt in self.fp[dim]["detail"].get(key, []):
                e = acc.setdefault((code, name), {"cash": 0.0, "gold": 0.0})
                e[dim] += amt
        t.setColumnCount(4)
        t.setHorizontalHeaderLabels(heads)
        items = sorted(acc.items())
        t.setRowCount(len(items))
        for i, ((code, name), v) in enumerate(items):
            for c, s in enumerate((code, name, money(v["cash"]),
                                   money(v["gold"], True))):
                it = QtWidgets.QTableWidgetItem(s)
                it.setTextAlignment(QtCore.Qt.AlignRight if c == 1
                                    else QtCore.Qt.AlignCenter)
                t.setItem(i, c, it)
        note = QtWidgets.QLabel(
            "صافي ربح الفترة من قائمة الدخل — من أول السنة المالية حتى تاريخ"
            " القائمة." if key == "profit" else
            f"عدد الحسابات: {len(items)} — كما في {self.fp['as_of']}")
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.addWidget(title_label(r["label"]))
        lay.addWidget(t, 1)
        lay.addWidget(note)
        try:
            from ui.widgets.table_fit import fit_columns
            fit_columns(t, [14, 46, 20, 20])
        except Exception:
            pass
        dlg.exec_()

    def export_csv(self):
        try:
            if not self.fp:
                self.load()
            if not self.fp:
                return
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "حفظ قائمة المركز المالي", "قائمة_المركز_المالي.csv",
                "ملف Excel (*.csv)")
            if not path:
                return
            cmp = bool(self.fp["compare_to"])
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["قائمة المركز المالي", f"كما في {self.fp['as_of']}"])
                w.writerow([h.replace("\n", " — ")
                            for h in self._headers()])
                for r in self.rows:
                    if r["kind"] in ("head", "sec"):
                        w.writerow([r["label"]])
                        continue
                    vals = [round(r["cash"], 2)]
                    if cmp:
                        vals.append(round(r["cash_cmp"], 2))
                    vals.append(round(kv.g(r["gold"]), 3))
                    if cmp:
                        vals.append(round(kv.g(r["gold_cmp"]), 3))
                    w.writerow([r["label"]] + vals)
            info(self, f"حُفظ الملف:\n{path}")
        except Exception as e:
            err(self, e)

    def print_sheet(self):
        try:
            as_of, cmp_to = self._params()
            from services import print_manager
            print_manager.preview_document(
                self, "financial_position", 0, as_of=as_of,
                compare_to=cmp_to)
        except Exception as e:
            err(self, e)


# ══════════════════════════════════════════════════════════════════
#  2) تفصيل بشجرة الحسابات
# ══════════════════════════════════════════════════════════════════
class AccountTreeTab(QtWidgets.QWidget):
    """الأرصدة كما في تاريخ بشجرة الحسابات ومستوياتها."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = None
        self.d_to = date_edit()

        self.level = QtWidgets.QComboBox()
        self.level.setMaximumWidth(160)
        for i, lbl in ((1, "1 — الأقسام الرئيسية"),
                       (2, "2 — المجموعات"),
                       (3, "3 — الفروع"),
                       (4, "4 — التفصيل"),
                       (5, "5 — التفصيل الكامل"),
                       (9, "الكل — بلا حدود")):
            self.level.addItem(lbl, i)
        self.level.setCurrentIndex(2)
        self.level.currentIndexChanged.connect(self.load)

        self.zero = QtWidgets.QCheckBox("إخفاء الصفرية")
        self.zero.setChecked(True)
        self.zero.stateChanged.connect(self.load)

        btn = QtWidgets.QPushButton("عرض الأرصدة")
        btn.clicked.connect(self.load)
        btn_print = QtWidgets.QPushButton("🖨 طباعة")
        btn_print.clicked.connect(self.print_sheet)

        head = FlowLayout()
        head.setSpacing(6)
        head.addWidget(QtWidgets.QLabel("كما في:"))
        head.addWidget(self.d_to, 0)
        head.addWidget(QtWidgets.QLabel("المستوى:"))
        head.addWidget(self.level, 0)
        head.addWidget(self.zero, 0)
        head.addWidget(btn, 0)
        head.addWidget(btn_print, 0)
        head.addStretch(1)

        self.table = make_table()
        _enhance(self.table, key="balance_sheet")
        self.summary = big_label()
        self.summary.setWordWrap(True)
        self.check = big_label()
        self.check.setWordWrap(True)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(4)
        lay.addLayout(head)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.summary)
        lay.addWidget(self.check)

    def load(self):
        try:
            lvl = self.level.currentData() or 3
            with db(readonly=True) as conn:
                b = balance_tree.balance_sheet_tree(
                    conn, date_to=dstr(self.d_to), date_from=None,
                    max_level=int(lvl), hide_zero=self.zero.isChecked())
            self.data = b
            self._render(b)
        except Exception as e:
            err(self, e)

    def _render(self, b):
        rows, marks = [], []
        for sec in b["sections"]:
            if not sec["rows"] and abs(sec["gold"]) < 0.001 \
                    and abs(sec["cash"]) < 0.01:
                continue
            marks.append((len(rows), True, 0))
            rows.append((f"◄ {sec['title']}", sec["code"],
                         f"{sec['cash']:,.2f}",
                         f"{kv.g(sec['gold']):,.2f}"))
            for r in sec["rows"]:
                if r["level"] == 1:
                    continue          # الجذر معروض في العنوان
                indent = "    " * (r["level"] - 1)
                marks.append((len(rows), False, r["level"]))
                rows.append((f"{indent}{r['name']}", r["code"],
                             f"{r['cash']:,.2f}",
                             f"{kv.g(r['gold']):,.2f}"))
            rows.append(("", "", "", ""))

        self.table.setUpdatesEnabled(False)
        try:
            self.table.setColumnCount(len(COLS))
            self.table.setHorizontalHeaderLabels(_cols())
            self.table.setRowCount(len(rows))
            for i, row in enumerate(rows):
                for c, val in enumerate(row):
                    it = QtWidgets.QTableWidgetItem(str(val))
                    it.setTextAlignment(
                        QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
                        if c == 0 else QtCore.Qt.AlignCenter)
                    self.table.setItem(i, c, it)
            for idx, is_sec, lvl in marks:
                for c in range(len(COLS)):
                    it = self.table.item(idx, c)
                    if it is None:
                        continue
                    f = it.font()
                    if is_sec:
                        f.setBold(True)
                        it.setFont(f)
                        it.setBackground(QtGui.QColor("#EFE9DC"))
                    elif lvl <= 2:
                        f.setBold(True)
                        it.setFont(f)
        finally:
            self.table.setUpdatesEnabled(True)
        try:
            from ui.widgets.table_fit import fit_columns
            fit_columns(self.table, [34, 12, 27, 27])
        except Exception:
            pass

        ag, ac = b["assets"]
        rg, rc = b["right_side"]
        self.summary.setText(
            f"الأصول — نقد: {ac:,.2f} ريال · ذهب: "
            f"{kv.g(ag):,.2f} {kv.unit()}"
            f"       |       الخصوم + حقوق الملكية + النتيجة — "
            f"نقد: {rc:,.2f} ريال · ذهب: {kv.g(rg):,.2f} {kv.unit()}")
        ok = b["balanced_cash"] and b["balanced_gold"]
        self.check.setText(
            "✔ الأرصدة متوازنة في البعدين" if ok else
            f"✘ عجز — فرق النقد: {b['diff_cash']:,.2f} ريال · "
            f"فرق الذهب: {kv.g(b['diff_gold']):,.2f} {kv.unit()}")
        self.check.setStyleSheet(
            "color:#0F5A24;font-weight:bold" if ok
            else "color:#8A1010;font-weight:bold")

    def print_sheet(self):
        try:
            from services import print_manager
            print_manager.preview_document(
                self, "balance_tree", 0, date_to=dstr(self.d_to),
                max_level=int(self.level.currentData() or 3),
                hide_zero=self.zero.isChecked())
        except Exception as e:
            err(self, e)


class BalanceSheetScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.statement = FinancialPositionTab(self)
        self.tree = AccountTreeTab(self)
        self.tabs = tab_widget()
        self.tabs.addTab(self.statement, "قائمة المركز المالي")
        self.tabs.addTab(self.tree, "تفصيل بشجرة الحسابات")
        self.tabs.currentChanged.connect(self._tab_changed)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        lay.addWidget(title_label("الميزانية العمومية — قائمة المركز المالي"))
        lay.addWidget(self.tabs, 1)
        self.statement.load()

    # توافقٌ مع من يقرأ الأسماء القديمة
    @property
    def data(self):
        return self.tree.data

    def _tab_changed(self, i):
        if i == 1 and self.tree.data is None:
            self.tree.load()

    def load(self):
        self.statement.load()
        if self.tree.data is not None:
            self.tree.load()

    def refresh(self):
        self.load()
