# -*- coding: utf-8 -*-
"""معاينة القيد قبل ترحيله — جدولٌ صغير: الحساب · مدين · دائن.

يرى المستخدم **أين سيذهب كل ريال** قبل أن يضغط «ترحيل»: حساب العميل
أو الصندوق، والإيراد، وضريبة المخرجات أو المدخلات — وصفّ إجماليٍّ
يثبت أن المدين يساوي الدائن. فلا يُكتشف خطأ الحساب بعد الترحيل من
كشف الحساب.
"""
from PyQt5 import QtCore, QtWidgets

from ui.widgets.common import num_item, row_height, text_item

COLS = ["الحساب", "البيان", "مدين", "دائن"]


class EntryPreview(QtWidgets.QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.verticalHeader().setVisible(False)
        self.setColumnCount(len(COLS))
        self.setHorizontalHeaderLabels(COLS)
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        hh.setDefaultAlignment(QtCore.Qt.AlignCenter)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setTextElideMode(QtCore.Qt.ElideRight)
        try:        # اسم الحساب أوسع الأعمدة: رقمه واسمه كاملين
            from ui.widgets.table_fit import fit_columns
            fit_columns(self, [40, 26, 17, 17])
        except Exception:
            pass
        self.set_lines([])

    def set_lines(self, lines):
        """`lines` = [(اسم الحساب, البيان, مدين, دائن)] — يُضاف صف الإجمالي."""
        rows = list(lines)
        td = sum(float(r[2] or 0) for r in rows)
        tc = sum(float(r[3] or 0) for r in rows)
        self.setRowCount(len(rows) + 1)
        for i, (acc, desc, d, c) in enumerate(rows):
            self.setItem(i, 0, text_item(acc))
            self.setItem(i, 1, text_item(desc))
            self.setItem(i, 2, num_item(f"{d:,.2f}" if d else ""))
            self.setItem(i, 3, num_item(f"{c:,.2f}" if c else ""))
        n = len(rows)
        ok = abs(td - tc) < 0.005
        self.setItem(n, 0, text_item("الإجمالي — " + (
            "متوازن ✔" if ok else "غير متوازن ✖")))
        self.setItem(n, 1, text_item(""))
        self.setItem(n, 2, num_item(f"{td:,.2f}"))
        self.setItem(n, 3, num_item(f"{tc:,.2f}"))
        for c in range(4):
            it = self.item(n, c)
            f = it.font()
            f.setBold(True)
            it.setFont(f)
        h = row_height(self)
        self.verticalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Fixed)
        self.verticalHeader().setDefaultSectionSize(h)
        self.setFixedHeight(self.horizontalHeader().sizeHint().height()
                            + h * (n + 1) + 6)
