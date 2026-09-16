# -*- coding: utf-8 -*-
"""لوحة الإقرار الضريبي (VAT Return Dashboard): ضريبة المخرجات مقابل
ضريبة المدخلات وصافي المستحق أو المسترد — بفترات ضريبية معتمدة."""
import csv
from datetime import date

from PyQt5 import QtWidgets

from database.database import db
from models.reports import vat_return
from ui.widgets.common import (Card, big_label, date_edit, dstr, err, fill, info, make_table, title_label)

PERIODS = [("شهري", "month"), ("ربع سنوي", "quarter"), ("نصف سنوي", "half"),
           ("سنوي", "year"), ("مخصص", "custom")]


def period_range(kind, ref: date):
    y = ref.year
    if kind == "month":
        start = date(y, ref.month, 1)
        end = date(y + (ref.month == 12), (ref.month % 12) + 1, 1)
    elif kind == "quarter":
        q = (ref.month - 1) // 3
        start = date(y, q * 3 + 1, 1)
        end = date(y + (q == 3), ((q + 1) * 3) % 12 + 1, 1)
    elif kind == "half":
        h = 0 if ref.month <= 6 else 1
        start = date(y, h * 6 + 1, 1)
        end = date(y + h, 1 if h else 7, 1)
    else:
        return date(y, 1, 1), date(y, 12, 31)
    return start, date.fromordinal(end.toordinal() - 1)


class VatReturnScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.last = None
        self.period = QtWidgets.QComboBox()
        for label, key in PERIODS:
            self.period.addItem(label, key)
        self.period.setCurrentIndex(1)
        self.period.currentIndexChanged.connect(self.apply_period)
        self.d_from = date_edit()
        self.d_to = date_edit()
        btn = QtWidgets.QPushButton("إعداد الإقرار")
        btn.clicked.connect(self.load)
        btn_exp = QtWidgets.QPushButton("تصدير CSV")
        btn_exp.setObjectName("ghost")
        btn_exp.clicked.connect(self.export_csv)

        head = QtWidgets.QHBoxLayout()
        head.addWidget(QtWidgets.QLabel("الفترة الضريبية:"))
        head.addWidget(self.period)
        head.addWidget(QtWidgets.QLabel("من:"))
        head.addWidget(self.d_from)
        head.addWidget(QtWidgets.QLabel("إلى:"))
        head.addWidget(self.d_to)
        head.addWidget(btn)
        head.addWidget(btn_exp)
        head.addStretch(1)

        self.c_out = Card("ضريبة المخرجات (مبيعات)", "ريال — محصّلة من العملاء")
        self.c_in = Card("ضريبة المدخلات (مشتريات)", "ريال — مدفوعة للموردين")
        self.c_net = Card("صافي التسوية الضريبية", "المخرجات − المدخلات")
        cards = QtWidgets.QHBoxLayout()
        for c in (self.c_out, self.c_in, self.c_net):
            c.setCursor(c.cursor())
            cards.addWidget(c)

        self.table = make_table()
        self.status = big_label()

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("الإقرار الضريبي — ضريبة القيمة المضافة (ZATCA)"))
        lay.addLayout(head)
        lay.addLayout(cards)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.status)
        note = QtWidgets.QLabel(
            "الأرقام تُسحب لحظياً من دفتر الأستاذ (حسابا 2100 المخرجات و1900 "
            "المدخلات) ومن الفواتير الضريبية فقط — الفواتير غير الضريبية "
            "مستبعدة تلقائياً من الوعاء.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.apply_period()

    def apply_period(self):
        kind = self.period.currentData()
        if kind == "custom":
            return
        s, e = period_range(kind, date.today())
        from PyQt5.QtCore import QDate
        self.d_from.setDate(QDate(s.year, s.month, s.day))
        self.d_to.setDate(QDate(e.year, e.month, e.day))

    def load(self):
        try:
            with db(readonly=True) as conn:
                r = vat_return(conn, dstr(self.d_from),
                              dstr(self.d_to))
            self.last = r
            self.c_out.set_value(f"{r['output_vat']:,.2f}",
                                f"وعاء خاضع: {r['sales_base']:,.2f} ريال "
                                f"({r['sales_count']} فاتورة ضريبية)")
            self.c_in.set_value(f"{r['input_vat']:,.2f}",
                               f"وعاء خاضع: {r['purchases_base']:,.2f} ريال "
                               f"({r['purchases_count']} فاتورة مشتريات)")
            self.c_net.set_value(f"{abs(r['net']):,.2f}", r["status"])
            rows = [
                ("— ضريبة المخرجات —", "", ""),
                ("إجمالي مبيعات الأجور الخاضعة للضريبة", f"{r['sales_base']:,.2f}", ""),
                ("الضريبة المحصلة من العملاء (من الفواتير)",
                 "", f"{r['sales_vat']:,.2f}"),
                ("رصيد حساب 2100 — ضريبة المخرجات (دفتر الأستاذ)",
                 "", f"{r['output_vat']:,.2f}"),
                ("— ضريبة المدخلات —", "", ""),
                ("إجمالي المشتريات الخاضعة للضريبة",
                 f"{r['purchases_base']:,.2f}", ""),
                ("الضريبة المدفوعة للموردين (من الفواتير)",
                 "", f"{r['purchases_vat']:,.2f}"),
                ("رصيد حساب 1900 — ضريبة المدخلات (دفتر الأستاذ)",
                 "", f"{r['input_vat']:,.2f}"),
                ("— التسوية —", "", ""),
                ("صافي الضريبة (مخرجات − مدخلات)", "", f"{r['net']:,.2f}"),
            ]
            fill(self.table, ["البند", "الوعاء الخاضع (ريال)", "الضريبة (ريال)"], rows)
            self.status.setText(
                f"الفترة {r['date_from']} إلى {r['date_to']} — {r['status']}: "
                f"{abs(r['net']):,.2f} ريال")
        except Exception as e:
            err(self, e)

    def export_csv(self):
        if not self.last:
            err(self, "أعدّ الإقرار أولاً قبل التصدير")
            return
        try:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "تصدير الإقرار الضريبي",
                f"vat_return_{self.last['date_from']}_{self.last['date_to']}.csv",
                "CSV (*.csv)")
            if not path:
                return
            r = self.last
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["الإقرار الضريبي", r["date_from"], r["date_to"]])
                w.writerow(["البند", "الوعاء الخاضع", "الضريبة"])
                w.writerow(["مبيعات خاضعة (مخرجات)", r["sales_base"], r["sales_vat"]])
                w.writerow(["مشتريات خاضعة (مدخلات)", r["purchases_base"],
                           r["purchases_vat"]])
                w.writerow(["صافي الضريبة", "", r["net"]])
                w.writerow(["الحالة", "", r["status"]])
            info(self, f"تم تصدير الإقرار إلى:\n{path}")
        except Exception as e:
            err(self, e)

    def refresh(self):
        pass
