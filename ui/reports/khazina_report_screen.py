# -*- coding: utf-8 -*-
"""تقرير إنتاج خزينة التصنيع: مطابقة المدخلات (ذهب من الصب/الكسر +
فصوص وأحجار عبر قيود اليومية) مقابل المخرجات (الوزن المقيد للأطقم
المُنتَجة) — للمطابقة بين ما استلمته الخزينة وما أنتجته فعلياً."""
from PyQt5 import QtCore, QtWidgets

from database.database import db
from services import karat_view as kv
from models.reports import khazina_tiles, production_inputs_summary
from ui.widgets.common import (Card, big_label, date_edit, dstr, err, fill, make_table, title_label)
from ui.widgets.table_tools import enhance as _enhance


class KhazinaReportScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.d_from = date_edit()
        self.d_from.setDate(QtCore.QDate(QtCore.QDate.currentDate().year(), 1, 1))
        self.d_to = date_edit()
        btn = QtWidgets.QPushButton("إعداد التقرير")
        btn.clicked.connect(self.load)

        head = QtWidgets.QHBoxLayout()
        head.addWidget(QtWidgets.QLabel("من:"))
        head.addWidget(self.d_from)
        head.addWidget(QtWidgets.QLabel("إلى:"))
        head.addWidget(self.d_to)
        head.addWidget(btn)
        head.addStretch(1)

        # لوحتان: الذهب، ومخزن الفصوص والأحجار مجتمعين (حساب 1150)
        self.t_gold = Card("الذهب", "إجمالي أوزان الذهب الصافي المُدخَل")
        self.t_jewels = Card("مخزن الفصوص والأحجار",
                             "رصيد حساب 1150 — الفصوص والأحجار معاً")
        tiles = QtWidgets.QHBoxLayout()
        for c in (self.t_gold, self.t_jewels):
            tiles.addWidget(c)
        self.tiles_layout = tiles
        self.summary = big_label()
        self.table = make_table()
        _enhance(self.table, key="khazina")

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label(
            "تقرير إنتاج خزينة التصنيع — مطابقة المدخلات بالمخرجات"))
        lay.addLayout(head)
        lay.addLayout(self.tiles_layout)
        lay.addWidget(self.summary)
        lay.addWidget(self.table, 1)
        note = QtWidgets.QLabel(
            "المخرجات هنا تعني فقط الوزن المقيد للأطقم المُنتَجة ومُرحَّلة "
            "للذهب المشغول — لا تشمل الفاقد/تسويات الجرد (تلك مغطاة في "
            "شاشتي تسوية الفاقد والجرد الفعلي وتظهر ضمن بند «أخرى» أدناه.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)

    def load(self):
        try:
            with db(readonly=True) as conn:
                r = khazina_tiles(
                    conn, dstr(self.d_from),
                    dstr(self.d_to))
                pin = production_inputs_summary(
                    conn, dstr(self.d_from),
                    dstr(self.d_to))
                # رصيد مخزن الفصوص والأحجار (1150) داخل نفس الاتصال
                try:
                    from models.accounts import acc_id
                    from services.accounting_engine import account_balance
                    inv_g = account_balance(conn, acc_id(conn, "1150"))[0]
                except Exception:
                    inv_g = ((pin.get("jewels") or 0)
                             + (pin.get("stones") or 0))
            self.t_gold.set_value(f"{kv.g(pin['gold']):,.2f} جم",
                                 f"من {pin['count']} أمر تشغيل")
            self.t_jewels.set_value(
                f"{kv.g(inv_g):,.2f} جم",
                f"فصوص {pin['jewels']:,.2f} · أحجار {pin['stones']:,.2f}")
            rows = [
                ("الرصيد الافتتاحي (قبل الفترة)", f"{r['opening']:,.2f}"),
                ("— المدخلات (الوارد للخزينة) —", ""),
                ("إجمالي الذهب الوارد (صب/كسر/تحويل داخلي...)",
                 f"{kv.g(r['gold_in']):,.2f}"),
                ("إجمالي الفصوص والأحجار الواردة (عبر قيود اليومية)",
                 f"{r['jewels_in']:,.2f}"),
                ("إجمالي المدخلات", f"{kv.g(r['total_in']):,.2f}"),
                ("— المخرجات (المنصرف من الخزينة) —", ""),
                (f"الوزن المقيد للأطقم المُنتَجة ({r['production_entries']} عملية توريد)",
                 f"{r['production']:,.2f}"),
                ("أخرى (فاقد/تسويات جرد خلال الفترة)", f"{r['other']:,.2f}"),
                ("الرصيد الختامي الفعلي (من دفتر الأستاذ)", f"{r['closing']:,.2f}"),
            ]
            fill(self.table, ["البند", f"جرامات ({kv.label()})"], rows)
            check = round(r["opening"] + r["total_in"] - r["production"]
                         + r["other"] - r["closing"], 3)
            ok = abs(check) < 0.005
            self.summary.setText(
                f"مدخلات الفترة: {kv.g(r['total_in']):,.2f} جم (منها "
                f"{kv.g(r['jewels_in']):,.2f} "
                f"فصوص وأحجار) | مخرجات الإنتاج: "
                f"{kv.g(r['production']):,.2f} جم | "
                f"{'المطابقة سليمة ✓' if ok else 'تنبيه: فرق غير مفسَّر ' + str(check)}")
        except Exception as e:
            err(self, e)

    def refresh(self):
        pass
