# -*- coding: utf-8 -*-
"""قائمة الدخل (Income Statement) — نموذج تسليم البضاعة للتصريف.

عمودان متجاوران: (النقد/الريال) و(الوزن/الجرام)، بالمنطق:
* الإيراد النقدي = صافي أجور المبيعات (بيع − مرتجع).
* صافي الذهب المباع يُعرض أعلى الشاشة للتوضيح فقط (انتقال أصل).
* فاقد الذهب العيني = الفاقد الفني للصب + الفاقد التشغيلي للتصنيع.
* المصروفات النقدية = إجمالي سندات الصرف.
* صافي الربح النقدي = صافي الأجور − المصروفات.
* صافي حركة الذهب = − إجمالي الفاقد (عجز عيني).
"""
from datetime import date

from PyQt5 import QtCore, QtWidgets

from database.database import db
from services import karat_view as kv
from models.reports import income_statement_consignment
from ui.widgets.common import (date_edit, dstr, err, fill, make_table, title_label)

PERIODS = [("شهري", "month"), ("ربع سنوي", "quarter"), ("نصف سنوي", "half"),
           ("سنوي", "year"), ("مخصص", "custom")]


def period_range(kind, ref: date):
    y = ref.year
    if kind == "month":
        start = date(y, ref.month, 1)
        nxt = date(y + (ref.month == 12), (ref.month % 12) + 1, 1)
    elif kind == "quarter":
        q = (ref.month - 1) // 3
        start = date(y, q * 3 + 1, 1)
        nxt = date(y + (q == 3), ((q + 1) * 3) % 12 + 1, 1)
    elif kind == "half":
        h = 0 if ref.month <= 6 else 1
        start = date(y, h * 6 + 1, 1)
        nxt = date(y + h, 1 if h else 7, 1)
    else:
        return date(y, 1, 1), date(y, 12, 31)
    return start, date.fromordinal(nxt.toordinal() - 1)


class IncomeStatementScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.period = QtWidgets.QComboBox()
        for label, key in PERIODS:
            self.period.addItem(label, key)
        self.period.setCurrentIndex(3)
        self.period.currentIndexChanged.connect(self.apply_period)
        self.d_from = date_edit()
        self.d_from.setDate(QtCore.QDate(QtCore.QDate.currentDate().year(), 1, 1))
        self.d_to = date_edit()
        btn = QtWidgets.QPushButton("إعداد القائمة")
        btn.clicked.connect(self.load)

        head = QtWidgets.QHBoxLayout()
        head.addWidget(QtWidgets.QLabel("الفترة:"))
        head.addWidget(self.period)
        head.addWidget(QtWidgets.QLabel("من:"))
        head.addWidget(self.d_from)
        head.addWidget(QtWidgets.QLabel("إلى:"))
        head.addWidget(self.d_to)
        head.addWidget(btn)
        head.addStretch(1)

        # شريط علوي: صافي الذهب المباع (عرض فقط)
        self.movement = QtWidgets.QLabel("")
        self.movement.setObjectName("eqBar")
        self.movement.setAlignment(QtCore.Qt.AlignCenter)
        self.movement.setWordWrap(True)

        self.table = make_table()

        # شريط سفلي: النتيجة النهائية
        self.result = QtWidgets.QLabel("")
        self.result.setObjectName("eqBar")
        self.result.setAlignment(QtCore.Qt.AlignCenter)
        self.result.setWordWrap(True)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label(
            "قائمة الدخل — نموذج تسليم البضاعة للتصريف (نقد ووزن)"))
        note = QtWidgets.QLabel(
            "الإيراد النقدي الحقيقي = صافي أجور المبيعات. صافي الذهب المباع "
            "للعرض فقط (انتقال أصل لا ربح). فاقد الذهب العيني = فاقد الصب + "
            "فاقد التصنيع. المصروفات من سندات الصرف.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addLayout(head)
        lay.addWidget(self.movement)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.result)

    def apply_period(self):
        kind = self.period.currentData()
        if kind == "custom":
            return
        s, e = period_range(kind, date.today())
        self.d_from.setDate(QtCore.QDate(s.year, s.month, s.day))
        self.d_to.setDate(QtCore.QDate(e.year, e.month, e.day))

    def load(self):
        try:
            f = dstr(self.d_from)
            t = dstr(self.d_to)
            with db(readonly=True) as conn:
                r = income_statement_consignment(conn, f, t)
            self._render(r)
        except Exception as e:
            err(self, e)

    def _render(self, r):
        def m(v):
            return f"{v:,.2f}"

        def g(v):
            """وزن بمكافئ 18 ← بعيار المصنع (كل أوزان القائمة)."""
            return f"{kv.g(v):,.2f}"

        # الشريط العلوي: حجم حركة البضاعة (وزني، عرض فقط)
        self.movement.setText(
            f"حجم حركة البضاعة (للعرض فقط) — صافي الذهب المباع: "
            f"{g(r['net_gold_sold'])} {kv.unit()}   "
            f"(مبيعات {g(r['sales_weight'])} − مرتجعات {g(r['returns_weight'])})")
        self.movement.setStyleSheet(
            "background:#f3ece0; color:#7a5c1e; font-size:12pt;"
            " font-weight:bold; padding:8px; border-radius:6px;")

        rows = [
            ("═══ أولاً: الإيرادات التشغيلية ═══", "", ""),
            (f"    مبيعات ({r['sales_count']} فاتورة)",
             m(r["sales_wages"]), g(r["sales_weight"])),
            (f"    (−) مرتجعات ({r['returns_count']} فاتورة)",
             m(-r["returns_wages"]), g(-r["returns_weight"])),
            ("    صافي المبيعات", m(r["net_wages"]), g(r["net_gold_sold"])),
            ("", "", ""),
            ("    صافي أجور المبيعات (الإيراد النقدي)", m(r["net_wages"]), "—"),
            ("    صافي حركة الذهب المباع (وزناً — انتقال أصل)",
             "—", g(r["net_gold_sold"])),
            ("", "", ""),
            ("═══ ثانياً: خسائر التشغيل العينية (الذهب) ═══", "", ""),
            ("    الفاقد الفني — قسم الصب (5120)", "—", g(r["casting_loss"])),
            ("    الفاقد التشغيلي — قسم التصنيع (5110)", "—",
             g(r["manufacturing_loss"])),
            ("    إجمالي فاقد الذهب", "—", g(r["total_gold_loss"])),
            ("", "", ""),
            ("═══ ثالثاً: المصروفات التشغيلية والعمومية ═══", "", ""),
            (f"    المدفوع عبر سندات الصرف ({r['payments_count']} سند)",
             m(r["expenses_cash"]), "—"),
            ("    إجمالي المصروفات", m(r["expenses_cash"]), "—"),
        ]
        fill(self.table, ["البند", "النقد / الأجور (ريال)",
                          f"الذهب ({kv.unit()})"],
             rows)

        # الشريط السفلي: النتيجة النهائية
        profit = r["net_profit_cash"]
        kind = "ربح" if profit >= 0 else "خسارة"
        color = ("#1e7a34", "#e6f4ea") if profit >= 0 else ("#a61b1b",
                                                             "#fdecea")
        self.result.setText(
            f"صافي ال{kind} النقدي: {m(profit)} ريال "
            f"(صافي الأجور {m(r['net_wages'])} − المصروفات "
            f"{m(r['expenses_cash'])})          "
            f"صافي حركة الذهب العينية: {g(r['net_gold_movement'])} جم "
            f"(عجز عيني = إجمالي الفاقد)")
        self.result.setStyleSheet(
            f"background:{color[1]}; color:{color[0]}; font-size:13pt;"
            f" font-weight:bold; padding:9px; border-radius:6px;")

    def refresh(self):
        pass
