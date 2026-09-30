# -*- coding: utf-8 -*-
"""قائمة التغيرات في حقوق الملكية — معيار المحاسبة الدولي 1 (الفقرة 106).

عمودٌ لكل مكوّن من حقوق الملكية (رأس المال · جاري الشركاء · الأرباح
المبقاة · …) وعمود المجموع، وصفوفٌ تفسّر الانتقال من رصيد أول الفترة
إلى آخرها: صافي الربح، المعاملات مع الملاك، تحويل النتيجة عند الإقفال.
فترة المقارنة أولاً ثم الحالية — ورصيد آخر الفترة يطابق حقوق الملكية
في قائمة المركز المالي.
"""
import csv
from datetime import date

from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from models import statements
from services import karat_view as kv
from ui.reports.income_statement import PERIODS, money, period_range
from ui.widgets.common import (date_edit, dstr, err, info, make_table,
                               title_label)
from ui.widgets.flow_layout import FlowLayout
from ui.widgets.table_tools import enhance as _enhance


class EquityChangesScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.eq = None
        self.rows = []

        self.period = QtWidgets.QComboBox()
        for label, key in PERIODS:
            self.period.addItem(label, key)
        self.period.setCurrentIndex(3)
        self.period.currentIndexChanged.connect(self.apply_period)
        today = date.today()
        self.d_from = date_edit()
        self.d_from.setDate(QtCore.QDate(today.year, 1, 1))
        self.d_to = date_edit()
        self.d_to.setDate(QtCore.QDate(today.year, 12, 31))
        self.dim = QtWidgets.QComboBox()
        self.dim.addItem("النقد (ريال سعودي)", "cash")
        self.dim.addItem(f"الذهب ({kv.unit()})", "gold")
        self.dim.currentIndexChanged.connect(self.load)
        self.cmp_on = QtWidgets.QCheckBox(
            "مقارنة بالفترة المماثلة من السنة السابقة")
        self.cmp_on.setChecked(True)

        btn = QtWidgets.QPushButton("إعداد القائمة")
        btn.setObjectName("homeBtn")
        btn.clicked.connect(self.load)
        btn_print = QtWidgets.QPushButton("🖨 معاينة وطباعة")
        btn_print.clicked.connect(self.print_statement)
        btn_exp = QtWidgets.QPushButton("⬇ تصدير Excel")
        btn_exp.setObjectName("ghost")
        btn_exp.clicked.connect(self.export_csv)
        btn_mov = QtWidgets.QPushButton("🔎 حسابات حقوق الملكية وحركتها")
        btn_mov.setToolTip("حسابات حقوق الملكية بأرصدتها، ومن كلٍّ منها"
                           " كشف حركته في الفترة بأرقام السندات")
        btn_mov.clicked.connect(self.show_movement)

        head = FlowLayout()
        head.setSpacing(6)
        head.addWidget(QtWidgets.QLabel("الفترة:"))
        head.addWidget(self.period)
        head.addWidget(QtWidgets.QLabel("من:"))
        head.addWidget(self.d_from)
        head.addWidget(QtWidgets.QLabel("إلى:"))
        head.addWidget(self.d_to)
        head.addWidget(QtWidgets.QLabel("العملة:"))
        head.addWidget(self.dim)
        head.addWidget(self.cmp_on)
        head.addWidget(btn)
        head.addWidget(btn_mov)
        head.addWidget(btn_print)
        head.addWidget(btn_exp)
        head.addStretch(1)

        self.table = make_table()
        _enhance(self.table, key="equity_changes")
        self.table.doubleClicked.connect(lambda *_: self.show_movement())
        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        lay.addWidget(title_label("قائمة التغيرات في حقوق الملكية"))
        lay.addLayout(head)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.status)
        self.load()

    def apply_period(self):
        kind = self.period.currentData()
        if kind == "custom":
            return
        s, e = period_range(kind, date.today())
        self.d_from.setDate(QtCore.QDate(s.year, s.month, s.day))
        self.d_to.setDate(QtCore.QDate(e.year, e.month, e.day))

    def _params(self):
        f, t = dstr(self.d_from), dstr(self.d_to)
        if f > t:
            raise ValueError("تاريخ «من» بعد تاريخ «إلى»")
        return f, t, self.cmp_on.isChecked(), self.dim.currentData() or "cash"

    def load(self):
        try:
            f, t, cmp, dim = self._params()
            with db(readonly=True) as conn:
                self.eq = statements.equity_changes(conn, f, t, cmp, dim)
            self._render()
        except Exception as e:
            err(self, e)

    def _headers(self):
        return (["البيان"] + [t for _k, t in self.eq["columns"]]
                + ["المجموع"])

    def show_movement(self):
        """حسابات حقوق الملكية بأرصدتها آخر الفترة — ومن كلٍّ منها حركته."""
        from ui.widgets.account_movement import AccountsPicker
        try:
            d1, d2 = dstr(self.d_from), dstr(self.d_to)
            # قيد فتح السنة دفتريٌّ يعكس الإقفال — لا حركة فعلية
            skip = "COALESCE(e.source_table,'')='year_open'"
            with db(readonly=True) as conn:
                items = [(r["code"], r["name"], r["c"] or 0.0, r["g"] or 0.0)
                         for r in conn.execute(
                    "SELECT a.code, a.name,"
                    " -SUM(l.cash_debit-l.cash_credit) c,"
                    " -SUM(l.gold_debit-l.gold_credit) g"
                    " FROM journal_lines l"
                    " JOIN journal_entries e ON e.id=l.entry_id"
                    "  AND e.is_deleted=0"
                    " JOIN accounts a ON a.id=l.account_id"
                    f" WHERE a.type='equity' AND e.entry_date<=? AND NOT"
                    f" ({skip}) GROUP BY a.id ORDER BY a.code", (d2,))]
            AccountsPicker(self, "حسابات حقوق الملكية", items, d1, d2, skip,
                           note=f"الأرصدة (دائنة موجبة) كما في {d2}").exec_()
        except Exception as e:
            err(self, e)

    def _render(self):
        eq = self.eq
        gold = eq["dim"] == "gold"
        self.rows = statements.eq_layout(eq)
        keys = [k for k, _t in eq["columns"]] + ["total"]
        heads = self._headers()
        tbl = self.table
        tbl.setUpdatesEnabled(False)
        try:
            tbl.clear()
            tbl.clearSpans()
            tbl.setColumnCount(len(heads))
            tbl.setHorizontalHeaderLabels(heads)
            tbl.setRowCount(len(self.rows))
            sec_bg = QtGui.QColor("#2B2723")
            tot_bg = QtGui.QColor("#F2EEE4")
            bal_bg = QtGui.QColor("#EFE9DC")
            for i, r in enumerate(self.rows):
                k = r["kind"]
                if k == "sec":
                    vals = [r["label"]] + [""] * (len(heads) - 1)
                else:
                    pad = "\u2003" if k == "line" else ""
                    vals = (["\u200f" + pad + r["label"]]
                            + [money(r["values"].get(c, 0.0), gold)
                               for c in keys])
                for c, v in enumerate(vals):
                    it = QtWidgets.QTableWidgetItem(v)
                    it.setTextAlignment(
                        (QtCore.Qt.AlignRight if c == 0
                         else QtCore.Qt.AlignCenter) | QtCore.Qt.AlignVCenter)
                    f = it.font()
                    if k in ("sec", "sub", "grand", "bal") \
                            or c == len(vals) - 1:
                        f.setBold(True)
                        it.setFont(f)
                    if k == "sec":
                        it.setBackground(sec_bg)
                        it.setForeground(QtGui.QColor("#FFFFFF"))
                    elif k in ("sub", "grand"):
                        it.setBackground(tot_bg)
                    elif k == "bal":
                        it.setBackground(bal_bg)
                    tbl.setItem(i, c, it)
                if k == "sec":
                    tbl.setSpan(i, 0, 1, len(heads))
        finally:
            tbl.setUpdatesEnabled(True)
        try:
            from ui.widgets.table_fit import fit_columns
            n = len(heads) - 1
            fit_columns(tbl, [34] + [66 // n] * n)
        except Exception:
            pass
        unit = kv.unit() if gold else "ريال"
        cur = eq["cur"]["closing"]["total"]
        self.status.setText(
            ("✔ كل عمود: رصيد أول الفترة + الحركات = رصيد آخرها، ويطابق"
             " حقوق الملكية في قائمة المركز المالي" if eq["balanced"]
             else "✘ فرقٌ بين الحركات والأرصدة — راجع القيود")
            + f"   ·   حقوق الملكية آخر الفترة: "
            f"{(kv.g(cur) if gold else cur):,.{3 if gold else 2}f} {unit}")
        self.status.setStyleSheet(
            "color:#0F5A24;font-weight:bold" if eq["balanced"]
            else "color:#9A0018;font-weight:bold")

    def export_csv(self):
        try:
            if not self.eq:
                self.load()
            if not self.eq:
                return
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "حفظ قائمة التغيرات في حقوق الملكية",
                "قائمة_التغيرات_في_حقوق_الملكية.csv", "ملف Excel (*.csv)")
            if not path:
                return
            gold = self.eq["dim"] == "gold"
            keys = [k for k, _t in self.eq["columns"]] + ["total"]
            conv = ((lambda v: round(kv.g(v), 3)) if gold
                    else (lambda v: round(v, 2)))
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh)
                w.writerow(["قائمة التغيرات في حقوق الملكية",
                            self.eq["date_from"], self.eq["date_to"],
                            kv.unit() if gold else "ريال سعودي"])
                w.writerow(self._headers())
                for r in self.rows:
                    if r["kind"] == "sec":
                        w.writerow([r["label"]])
                        continue
                    w.writerow([r["label"]]
                               + [conv(r["values"].get(k, 0.0))
                                  for k in keys])
            info(self, f"حُفظ الملف:\n{path}")
        except Exception as e:
            err(self, e)

    def print_statement(self):
        try:
            f, t, cmp, dim = self._params()
            from services import print_manager
            print_manager.preview_document(
                self, "equity_changes", 0, date_from=f, date_to=t,
                compare=cmp, dim=dim)
        except Exception as e:
            err(self, e)

    def refresh(self):
        if self.eq is not None:
            self.load()
