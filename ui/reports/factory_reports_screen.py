# -*- coding: utf-8 -*-
"""الشاشة المجمّعة «تقارير مبيعات وإنتاج المصنع».

حاوية تضم ثلاثة تقارير، يفتح كلٌّ منها أسفل أزرار الاختيار:
تقرير إنتاج خزينة التصنيع · لوحة تحليل مبيعات العملاء · قائمة الدخل.
"""
from PyQt5 import QtWidgets

from ui.reports.income_statement import IncomeStatementScreen
from ui.reports.khazina_report_screen import KhazinaReportScreen
from ui.sales_analytics_screen import SalesAnalyticsScreen
from ui.widgets.common import title_label


class FactoryReportsScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user

        self.khazina = KhazinaReportScreen(user)
        self.analytics = SalesAnalyticsScreen(user)
        self.income = IncomeStatementScreen(user)
        self._screens = [self.khazina, self.analytics, self.income]

        self.stack = QtWidgets.QStackedWidget()
        for w in self._screens:
            self.stack.addWidget(w)

        options = [
            ("🏭 تقرير إنتاج خزينة التصنيع", 0),
            ("📊 لوحة تحليل مبيعات العملاء", 1),
            ("📈 قائمة الدخل", 2),
        ]
        self.buttons = []
        btn_row = QtWidgets.QHBoxLayout()
        for label, idx in options:
            b = QtWidgets.QPushButton(label)
            b.setObjectName("reportTab")
            b.setCheckable(True)
            b.clicked.connect(lambda _, i=idx: self.select(i))
            self.buttons.append(b)
            btn_row.addWidget(b)
        btn_row.addStretch(1)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("تقارير مبيعات وإنتاج المصنع"))
        lay.addLayout(btn_row)
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        lay.addWidget(line)
        lay.addWidget(self.stack, 1)

        self.select(0)

    def select(self, idx):
        self.stack.setCurrentIndex(idx)
        for i, b in enumerate(self.buttons):
            b.setChecked(i == idx)
        scr = self._screens[idx]
        if hasattr(scr, "refresh"):
            scr.refresh()

    def refresh(self):
        cur = self.stack.currentIndex()
        if 0 <= cur < len(self._screens):
            scr = self._screens[cur]
            if hasattr(scr, "refresh"):
                scr.refresh()
