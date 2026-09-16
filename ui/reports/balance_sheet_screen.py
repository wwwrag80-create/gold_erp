# -*- coding: utf-8 -*-
"""شاشة الميزانية العمومية الشجرية.

تُبنى من **شجرة الحسابات نفسها** لا من قائمة أكواد ثابتة — فكل حساب
يضيفه المستخدم يظهر تلقائياً تحت جذره، ويستحيل أن يختل التوازن بسبب
حساب منسيّ.

اختيار المستوى يحدّد عمق التفصيل، كما في أنظمة ERP:
    1 → الأقسام · 2 → المجموعات · 3 → الفروع · 4+ → التفصيل الكامل
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from services import karat_view as kv
from models import balance_tree
from ui.widgets.common import (big_label, date_edit, dstr, err, make_table,
                               title_label)
from ui.widgets.table_tools import enhance as _enhance

COLS = ["الحساب", "الكود", "النقد / الأجور (ريال)", "الذهب (جم 18)"]


def _cols():
    return ["الحساب", "الكود", "النقد / الأجور (ريال)",
            f"الذهب ({kv.unit()})"]


class BalanceSheetScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.data = None

        self.d_from = date_edit()
        self.d_from.setDate(
            QtCore.QDate(QtCore.QDate.currentDate().year(), 1, 1))
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

        btn = QtWidgets.QPushButton("إعداد الميزانية")
        btn.clicked.connect(self.load)
        btn_print = QtWidgets.QPushButton("🖨 طباعة")
        btn_print.clicked.connect(self.print_sheet)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(QtWidgets.QLabel("من:"))
        head.addWidget(self.d_from, 0)
        head.addWidget(QtWidgets.QLabel("إلى:"))
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
        self.check = big_label()

        note = QtWidgets.QLabel(
            "الميزانية تُبنى من شجرة الحسابات كاملةً — أي حساب تضيفه "
            "يظهر تلقائياً تحت جذره فلا يختل التوازن.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        lay.addWidget(title_label("الميزانية العمومية — ثنائية البعد"))
        lay.addWidget(note)
        lay.addLayout(head)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.summary)
        lay.addWidget(self.check)
        self.load()

    # ══════════ العرض ══════════
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
                        try:
                            it.setBackground(QtGui.QColor("#EFE9DC"))
                        except Exception:
                            pass
                    elif lvl <= 2:
                        f.setBold(True)
                        it.setFont(f)
        finally:
            try:
                self.table.setUpdatesEnabled(True)
            except Exception:
                pass
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
            "✔ الميزانية متوازنة في البعدين" if ok else
            f"✘ عجز — فرق النقد: {b['diff_cash']:,.2f} ريال · "
            f"فرق الذهب: {kv.g(b['diff_gold']):,.2f} {kv.unit()}")
        try:
            self.check.setStyleSheet(
                "color:#1E6B33;font-weight:bold" if ok
                else "color:#8B1E1E;font-weight:bold")
        except Exception:
            pass

    def print_sheet(self):
        try:
            from services import print_manager
            print_manager.preview_document(
                self, "balance_tree", 0, date_to=dstr(self.d_to),
                max_level=int(self.level.currentData() or 3),
                hide_zero=self.zero.isChecked())
        except Exception as e:
            err(self, e)

    def refresh(self):
        self.load()
