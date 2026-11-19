# -*- coding: utf-8 -*-
"""نافذة «إقفال السنة وبدء الجديدة» (5.9) — من زرّ «السنة» في أعلى البرنامج.

تعرض نتيجة السنة قبل الإقفال وما سيحدث بالضبط، ثم تُقفلها بنقرة
(`models.fiscal_years.close_year`): نسخةٌ احتياطية، قيد الإقفال، قفل السنة.
"""
from PyQt5 import QtCore, QtWidgets

from ui import kit
from database.database import db
from models import closing, fiscal_years
from services import karat_view as kv
from services import numfmt as _nf
from ui.widgets.common import err, info


class YearCloseDialog(QtWidgets.QDialog):
    def __init__(self, parent, user, year):
        super().__init__(parent)
        self.user = user or {}
        self.year = int(year)
        self.result_data = None
        self.setWindowTitle(f"إقفال سنة {self.year} وبدء سنة {self.year + 1}")
        self.setLayoutDirection(QtCore.Qt.RightToLeft)
        self.setMinimumWidth(560)
        lay = QtWidgets.QVBoxLayout(self)
        head = QtWidgets.QLabel(
            f"<h2 style='margin:0'>📅 إقفال سنة {self.year} وبدء سنة "
            f"{self.year + 1}</h2>")
        lay.addWidget(head)
        with db(readonly=True) as conn:
            why = fiscal_years.check_close(conn, self.year)
            prev = closing.year_end_preview(conn, self.year)
        net_c, net_g = prev["net_cash"], prev["net_gold"]
        word = "ربح" if net_c >= 0 else "خسارة"
        summary = QtWidgets.QLabel(
            f"<b>نتيجة سنة {self.year}:</b> {word} نقدي "
            f"<b>{_nf.f2(abs(net_c))}</b> ريال · ذهب "
            f"<b>{_nf.f2(kv.g(net_g))}</b> {kv.unit()} — من "
            f"{len(prev['items'])} حساب إيرادٍ ومصروف.")
        summary.setWordWrap(True)
        lay.addWidget(summary)
        steps = QtWidgets.QLabel(
            "<b>ما سيحدث:</b><ol style='margin-top:4px'>"
            "<li>نسخةٌ احتياطية كاملة قبل أي تغيير.</li>"
            f"<li>قيد الإقفال بتاريخ 31-12-{self.year}: تُصفَّر الإيرادات "
            "والمصروفات ويُرحَّل صافي النتيجة إلى الأرباح المحتجزة (أو جاري "
            "الشركاء).</li>"
            f"<li>تُقفل سنة {self.year}: لا يُضاف فيها قيدٌ ولا يُعدَّل ولا "
            "يُحذف — وتبقى محفوظةً كاملة، تفتحها من زرّ «السنة» متى شئت.</li>"
            f"<li>تبدأ سنة {self.year + 1}: أرصدة العملاء والمصانع والصناديق "
            "والبنوك والذهب والمخزون تنتقل كما هي («رصيدٌ سابق» في كل كشف)، "
            "والإيرادات والمصروفات تبدأ من صفر.</li></ol>")
        steps.setWordWrap(True)
        steps.setTextFormat(QtCore.Qt.RichText)
        lay.addWidget(steps)
        self.to_partners = kit.CheckBox(
            "ترحيل صافي النتيجة إلى جاري الشركاء بدل الأرباح المحتجزة")
        lay.addWidget(self.to_partners)
        self.warn = QtWidgets.QLabel(why)
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet("color:#9A1414;font-weight:bold")
        self.warn.setVisible(bool(why))
        lay.addWidget(self.warn)
        row = QtWidgets.QHBoxLayout()
        self.btn = kit.PushButton(f"🔒 إقفال {self.year} وبدء {self.year + 1}")
        self.btn.setObjectName("primary")
        self.btn.setEnabled(not why)
        self.btn.clicked.connect(self.run)
        cancel = kit.PushButton("إلغاء")
        cancel.clicked.connect(self.reject)
        row.addWidget(self.btn)
        row.addStretch(1)
        row.addWidget(cancel)
        lay.addLayout(row)

    def run(self):
        try:
            with db() as conn:
                self.result_data = fiscal_years.close_year(
                    conn, self.year, self.user.get("username"),
                    to_partners=self.to_partners.isChecked())
        except Exception as e:
            err(self, e)
            return
        r = self.result_data
        info(self, f"أُقفلت سنة {r['year']} وبدأت سنة {r['next']}.\n\n"
                   "• الأرصدة انتقلت كما هي، والإيرادات والمصروفات بدأت من صفر.\n"
                   f"• سنة {r['year']} محفوظة: تفتحها من زرّ «السنة» متى شئت.\n"
                   + ("• أُخذت نسخةٌ احتياطية قبل الإقفال." if r.get("backup")
                      else ""))
        self.accept()
