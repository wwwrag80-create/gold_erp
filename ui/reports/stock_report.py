# -*- coding: utf-8 -*-
"""أرصدة المخازن — جرد لحظي: دفتري بمكافئ 18 + فعلي لكل عيار."""
from PyQt5 import QtWidgets

from database.database import db
from services import karat_view as kv
from models.inventory import stock_snapshot
from ui.widgets.common import big_label, fill, make_table, title_label
from ui.widgets.table_tools import enhance as _enhance


class StockReportScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.gold_summary = big_label()
        self.cash_summary = big_label()
        self.boxes = make_table()
        _enhance(self.boxes, key="stock_boxes")
        btn = QtWidgets.QPushButton("تحديث الجرد")
        btn.clicked.connect(self.refresh)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("أرصدة المخازن — الجرد اللحظي"))
        lay.addWidget(self.gold_summary)
        lay.addWidget(self.cash_summary)
        box = QtWidgets.QGroupBox(
            "صناديق الكسر: الوزن الفعلي بعياره مقابل المكافئ الدفتري بعيار 18")
        bl = QtWidgets.QVBoxLayout(box)
        bl.addWidget(self.boxes)
        lay.addWidget(box, 1)
        lay.addWidget(btn)

    def refresh(self):
        with db(readonly=True) as conn:
            s = stock_snapshot(conn)
        self.gold_summary.setText(
            f"خزينة التصنيع: {kv.g(s['tazeena_gold']):,.2f} جم "
            f"{kv.label()}   |   "
            f"الذهب المشغول: {kv.g(s['mashghool_gold']):,.2f} جم "
            f"({s['wo_count']} طقم بمجموع "
            f"{kv.g(s['wo_weight']):,.2f} جم)")
        self.cash_summary.setText(
            f"الصندوق: {s['cash_box']:,.2f} ريال   |   "
            f"البنك: {s['bank']:,.2f} ريال")
        # الوزن الفعلي وزنٌ حقيقي بعياره — لا يُحوَّل. المكافئ وحده
        # يُقرأ بوحدة المصنع.
        rows = [(f"عيار {k}", actual, kv.g(ledger))
                for k, actual, ledger in s["boxes"]]
        fill(self.boxes, ["الصندوق", "الوزن الفعلي بعياره (جم)",
                          f"المكافئ الدفتري ({kv.unit()})"], rows)
