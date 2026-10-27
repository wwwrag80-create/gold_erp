# -*- coding: utf-8 -*-
"""أرصدة المخازن — جرد لحظي: دفتري بمكافئ 18 + فعلي لكل عيار."""
from PyQt5 import QtWidgets

from ui import kit

from database.database import db
from services import karat_view as kv
from models.inventory import stock_snapshot
from ui.widgets.common import big_label, fill, make_table, title_label
from ui.widgets.table_tools import enhance as _enhance
from services import numfmt as _nf


class StockReportScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.gold_summary = big_label()
        self.cash_summary = big_label()
        self.boxes = make_table()
        _enhance(self.boxes, key="stock_boxes")
        btn = kit.PushButton("تحديث الجرد")
        btn.clicked.connect(self.refresh)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("أرصدة المخازن — الجرد اللحظي"))
        lay.addWidget(self.gold_summary)
        lay.addWidget(self.cash_summary)
        box = QtWidgets.QGroupBox(
            "صناديق الكسر: الوزن الفعلي بعياره مقابل المكافئ الدفتري "
            f"بـ{kv.label()}")
        bl = QtWidgets.QVBoxLayout(box)
        bl.addWidget(self.boxes)
        lay.addWidget(box, 1)
        lay.addWidget(btn)

    def refresh(self):
        with db(readonly=True) as conn:
            s = stock_snapshot(conn)
        self.gold_summary.setText(
            f"خزينة التصنيع: {_nf.f2(kv.g(s['tazeena_gold']))} جم "
            f"{kv.label()}   |   "
            f"الذهب المشغول: {_nf.f2(kv.g(s['mashghool_gold']))} جم "
            f"({s['wo_count']} طقم بمجموع "
            f"{_nf.f2(kv.g(s['wo_weight']))} جم)")
        self.cash_summary.setText(
            f"الصندوق: {_nf.f2(s['cash_box'])} ريال   |   "
            f"البنك: {_nf.f2(s['bank'])} ريال")
        # الوزن الفعلي وزنٌ حقيقي بعياره — لا يُحوَّل. المكافئ وحده
        # يُقرأ بوحدة المصنع.
        rows = [(f"عيار {k}", actual, kv.g(ledger))
                for k, actual, ledger in s["boxes"]]
        fill(self.boxes, ["الصندوق", "الوزن الفعلي بعياره (جم)",
                          f"المكافئ الدفتري ({kv.unit()})"], rows)
