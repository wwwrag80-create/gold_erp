# -*- coding: utf-8 -*-
"""ميزان المراجعة — الحساب حساباً بأرصدته وحركته في البعدين.

الميزانية وقائمة الدخل تعرضان **نتيجة** الدفتر مجمَّعةً؛ وميزان
المراجعة يعرض الدفتر نفسه ويُثبت أنه متوازن. وهو أول ما يطلبه
المحاسب أو المدقّق، وأول مكان يظهر فيه أي خلل: حساب برصيد غير
متوقّع يُرى هنا فوراً بدل أن يذوب داخل مجموع.
"""
import csv
from datetime import date

from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from services import karat_view as kv
from models.reports import trial_balance
from ui.widgets.common import (big_label, date_edit, dstr, err, fill, info, make_table, title_label)
from ui.widgets.table_tools import enhance as _enhance

COLS = ["الكود", "الحساب", "النوع",
        "افتتاح ذهب 18", "مدين ذهب 18", "دائن ذهب 18", "إقفال ذهب 18",
        "افتتاح نقد", "مدين نقد", "دائن نقد", "إقفال نقد"]

TYPE_AR = {"asset": "أصل", "liability": "خصم", "equity": "حقوق ملكية",
           "revenue": "إيراد", "expense": "مصروف", "bridge": "وسيط"}


class TrialBalanceScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.last = None

        today = date.today()
        self.d_from = date_edit()
        self.d_from.setDate(QtCore.QDate(today.year, 1, 1))
        self.d_to = date_edit()
        self.d_to.setDate(QtCore.QDate(today.year, 12, 31))
        self.all_time = QtWidgets.QCheckBox("كل المدة (بلا تحديد فترة)")
        self.all_time.stateChanged.connect(self._toggle_period)
        self.show_zero = QtWidgets.QCheckBox("إظهار الحسابات الصفرية")

        btn = QtWidgets.QPushButton("إعداد الميزان")
        btn.setObjectName("homeBtn")
        btn.clicked.connect(self.load)
        btn_exp = QtWidgets.QPushButton("تصدير CSV")
        btn_exp.setObjectName("ghost")
        btn_exp.clicked.connect(self.export_csv)
        btn_print = QtWidgets.QPushButton("طباعة")
        btn_print.setObjectName("ghost")
        btn_print.clicked.connect(self.print_report)

        head = QtWidgets.QHBoxLayout()
        head.addWidget(QtWidgets.QLabel("من:"))
        head.addWidget(self.d_from)
        head.addWidget(QtWidgets.QLabel("إلى:"))
        head.addWidget(self.d_to)
        head.addWidget(self.all_time)
        head.addWidget(self.show_zero)
        head.addWidget(btn)
        head.addWidget(btn_exp)
        head.addWidget(btn_print)
        head.addStretch(1)

        self.table = make_table()
        _enhance(self.table, key="trial_balance")
        self.status = big_label()

        note = QtWidgets.QLabel(
            "رصيد أول المدة هو محصّلة كل الحركة السابقة للتاريخ «من»، "
            "والمدين والدائن هما حجم حركة الفترة نفسها، ورصيد الإقفال = "
            "أول المدة + مدين − دائن. الميزان سليم حين يتساوى مدين الفترة "
            "مع دائنها ويصفر مجموع أرصدة الإقفال — في الذهب والنقد معاً.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("ميزان المراجعة — بالأرصدة والحركة"))
        lay.addWidget(note)
        lay.addLayout(head)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.status)

    def _toggle_period(self):
        on = not self.all_time.isChecked()
        self.d_from.setEnabled(on)
        self.d_to.setEnabled(on)

    # ══════════════════════════════════════════════════════════════

    def _range(self):
        if self.all_time.isChecked():
            return None, None
        return (dstr(self.d_from),
                dstr(self.d_to))

    def load(self):
        try:
            d1, d2 = self._range()
            if d1 and d2 and d1 > d2:
                raise ValueError("تاريخ «من» بعد تاريخ «إلى»")
            with db(readonly=True) as conn:
                tb = trial_balance(conn, d1, d2,
                                   include_zero=self.show_zero.isChecked())
            self.last = tb
            rows = [(r["code"], r["name"], TYPE_AR.get(r["type"], r["type"]),
                     _g(r["open_gold"]), _g(r["gold_debit"]),
                     _g(r["gold_credit"]), _g(r["close_gold"]),
                     _c(r["open_cash"]), _c(r["cash_debit"]),
                     _c(r["cash_credit"]), _c(r["close_cash"]))
                    for r in tb["rows"]]
            t = tb["totals"]
            rows.append(("", "الإجمالي", "",
                         _g(t["open_gold"]), _g(t["gold_debit"]),
                         _g(t["gold_credit"]), _g(t["close_gold"]),
                         _c(t["open_cash"]), _c(t["cash_debit"]),
                         _c(t["cash_credit"]), _c(t["close_cash"])))
            fill(self.table, [kv.rename(c) for c in COLS], rows)
            self._bold_last_row()
            ok_g, ok_c = t["balanced_gold"], t["balanced_cash"]
            msg = [f"{len(tb['rows'])} حساباً متحرّكاً"]
            msg.append("ميزان الذهب: " + ("✔ متوازن" if ok_g else
                       f"✘ فرق {t['gold_debit'] - t['gold_credit']:,.3f} جم"))
            msg.append("ميزان النقد: " + ("✔ متوازن" if ok_c else
                       f"✘ فرق {t['cash_debit'] - t['cash_credit']:,.2f} ريال"))
            self.status.setText("   |   ".join(msg))
            if not (ok_g and ok_c):
                self.status.setStyleSheet("color:#b00020;")
            else:
                self.status.setStyleSheet("")
        except Exception as e:
            err(self, e)

    def _bold_last_row(self):
        try:
            r = self.table.rowCount() - 1
            if r < 0:
                return
            f = QtGui.QFont()
            f.setBold(True)
            for c in range(self.table.columnCount()):
                it = self.table.item(r, c)
                if it:
                    it.setFont(f)
        except Exception:
            pass

    def export_csv(self):
        try:
            if not self.last:
                raise ValueError("أعِدّ الميزان أولاً")
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "حفظ ميزان المراجعة", "trial_balance.csv",
                "ملف CSV (*.csv)")
            if not path:
                return
            # utf-8-sig ليفتح إكسل العربية بلا رموز مشوّهة
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow([f"ميزان المراجعة",
                            f"من {self.last['date_from'] or 'البداية'}",
                            f"إلى {self.last['date_to'] or 'اليوم'}"])
                w.writerow(COLS)
                for r in self.last["rows"]:
                    w.writerow([r["code"], r["name"],
                                TYPE_AR.get(r["type"], r["type"]),
                                r["open_gold"], r["gold_debit"],
                                r["gold_credit"], r["close_gold"],
                                r["open_cash"], r["cash_debit"],
                                r["cash_credit"], r["close_cash"]])
                t = self.last["totals"]
                w.writerow(["", "الإجمالي", "", t["open_gold"],
                            t["gold_debit"], t["gold_credit"],
                            t["close_gold"], t["open_cash"], t["cash_debit"],
                            t["cash_credit"], t["close_cash"]])
            info(self, f"حُفظ الملف:\n{path}")
        except Exception as e:
            err(self, e)

    def print_report(self):
        try:
            if not self.last:
                self.load()
            if not self.last:
                raise ValueError("أعِدّ الميزان أولاً")
            from services import browser_print
            browser_print.open_document(
                "trial_balance", 0,
                date_from=self.last["date_from"] or None,
                date_to=self.last["date_to"] or None,
                include_zero=self.show_zero.isChecked())
        except Exception as e:
            err(self, e)

    def refresh(self):
        if self.last:
            self.load()


def _g(v):
    """وزن مخزَّن بمكافئ 18 ← معروضاً بعيار المصنع.

    كل أوزان الميزان تمرّ من هنا، فالتحويل في موضع واحد.
    """
    v = kv.g(v)
    return f"{v:,.3f}" if abs(v) >= 0.0005 else "—"


def _c(v):
    return f"{v:,.2f}" if abs(v) >= 0.005 else "—"
