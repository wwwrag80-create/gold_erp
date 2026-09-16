# -*- coding: utf-8 -*-
"""شاشة إنزال رواتب الموظفين — استحقاق نهاية الشهر (أساس الاستحقاق).

تعمل بالجلب التلقائي: عند اختيار الشهر تُسحب كل حسابات الموظفين
النشطين ورواتبهم المسجّلة في ملفاتهم التعريفية وتُعرض في شبكة بيانات،
ثم يُرحَّل **قيد يومية واحد** مفصّل بسطرين لكل موظف:

    مدين  حـ/ مصروف الرواتب والأجور (5700)   براتب الموظف
    دائن  حـ/ حساب الموظف نفسه               براتبه

فيظهر في كشف حساب المصروفات سطرٌ باسم كل موظف (لا «مذكورين»)، وفي كشف
حساب الموظف تظهر السلف مدينةً والراتب دائناً والصافي آلياً.
"""
import calendar

from PyQt5 import QtCore, QtWidgets

from database.database import db
from models import payroll
from ui.widgets.common import (ask, big_label, date_edit, dstr, err, fill, info, make_table, title_label)

MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو",
          "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]

COLS = ["الموظف", "المسمى الوظيفي", "الراتب المسجل (ريال)",
        "السلف القائمة", "صافي المستحق", "الحالة"]


class PayrollRunScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.rows = []

        today = QtCore.QDate.currentDate()
        self.month = QtWidgets.QComboBox()
        for i, m in enumerate(MONTHS, 1):
            self.month.addItem(m, i)
        self.month.setCurrentIndex(today.month() - 1)
        self.year = QtWidgets.QSpinBox()
        self.year.setRange(2000, 2100)
        self.year.setValue(today.year())
        self.month.currentIndexChanged.connect(self.load)
        self.year.valueChanged.connect(self.load)

        self.date = date_edit()
        btn_load = QtWidgets.QPushButton("↻ جلب الموظفين والرواتب")
        btn_load.clicked.connect(self.load)
        self.btn_post = QtWidgets.QPushButton("💾 حفظ وترحيل الرواتب")
        self.btn_post.setObjectName("homeBtn")
        self.btn_post.clicked.connect(self.post)

        head = QtWidgets.QHBoxLayout()
        head.addWidget(QtWidgets.QLabel("شهر الاستحقاق:"))
        head.addWidget(self.month)
        head.addWidget(self.year)
        head.addWidget(QtWidgets.QLabel("تاريخ القيد:"))
        head.addWidget(self.date)
        head.addWidget(btn_load)
        head.addStretch(1)
        head.addWidget(self.btn_post)

        self.table = make_table()
        self.summary = big_label()
        self.hint = QtWidgets.QLabel(
            "الرواتب تُجلب آلياً من الملف التعريفي لكل موظف ولا تُدخل "
            "يدوياً. القيد يُرحَّل بتاريخ آخر يوم في الشهر، ويُفصَّل بسطرين "
            "لكل موظف داخل سند واحد.")
        self.hint.setObjectName("cardSub")
        self.hint.setWordWrap(True)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label(
            "إنزال رواتب الموظفين — استحقاق نهاية الشهر"))
        lay.addWidget(self.hint)
        lay.addLayout(head)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.summary)

    # ── الفترة ──
    def period(self):
        return f"{int(self.year.value()):04d}-{int(self.month.currentData()):02d}"

    def period_label(self):
        return f"{MONTHS[self.month.currentIndex()]} {int(self.year.value())}"

    def accrual_date(self):
        """التاريخ الفعلي للإجراء (يختاره المستخدم، واليوم افتراضياً)."""
        return dstr(self.date)

    # ── الجلب الآلي ──
    def load(self):
        try:
            per = self.period()
            data, total, pending = [], 0.0, 0
            with db() as conn:
                for e in payroll.list_employees(conn, active_only=True,
                                                kind="employee"):
                    salary = round(e["basic_salary"] or 0, 2)
                    done = conn.execute(
                        "SELECT 1 FROM payroll_ledger WHERE employee_id=?"
                        " AND period=? AND kind='accrual' AND is_deleted=0",
                        (e["id"], per)).fetchone()
                    adv = payroll.advance_outstanding(conn, e["id"])
                    net = round(salary - min(adv, salary), 2)
                    if salary <= 0:
                        state = "بلا راتب مسجل"
                    elif done:
                        state = "مُرحَّل مسبقاً"
                    else:
                        state = "جاهز للترحيل"
                        total += salary
                        pending += 1
                    data.append((e["name"], e["job_title"] or "—",
                                 f"{salary:,.2f}", f"{adv:,.2f}",
                                 f"{net:,.2f}", state))
                    self.rows.append(e["id"])
            self.rows = []
            fill(self.table, COLS, data)
            self.summary.setText(
                f"شهر {self.period_label()} — تاريخ القيد: {self.accrual_date()}"
                f"   |   {len(data)} موظف نشط   |   "
                f"{pending} جاهز للترحيل بإجمالي {total:,.2f} ريال")
            self.btn_post.setEnabled(pending > 0)
        except Exception as e:
            err(self, e)

    # ── الترحيل ──
    def post(self):
        try:
            per = self.period()
            with db() as conn:
                pend = [e for e in payroll.list_employees(
                            conn, active_only=True, kind="employee")
                        if (e["basic_salary"] or 0) > 0 and not conn.execute(
                            "SELECT 1 FROM payroll_ledger WHERE employee_id=?"
                            " AND period=? AND kind='accrual' AND is_deleted=0",
                            (e["id"], per)).fetchone()]
            if not pend:
                raise ValueError(
                    f"لا توجد رواتب معلّقة لشهر {self.period_label()} — "
                    "ربما رُحّلت مسبقاً")
            total = round(sum(e["basic_salary"] for e in pend), 2)
            if not ask(self,
                       f"ترحيل رواتب {self.period_label()}؟\n\n"
                       f"عدد الموظفين: {len(pend)}\n"
                       f"إجمالي الاستحقاق: {total:,.2f} ريال\n"
                       f"تاريخ القيد: {self.accrual_date()}\n\n"
                       f"سيُنشأ سند واحد بسطرين لكل موظف."):
                return
            with db() as conn:
                res = payroll.run_accrual(conn, per, self.user["username"],
                                          entry_date=self.accrual_date())
            info(self, f"تم ترحيل رواتب {self.period_label()}.\n"
                       f"عدد الموظفين: {len(res)}\n"
                       f"إجمالي الاستحقاق: {total:,.2f} ريال\n\n"
                       f"يظهر في كشف مصروف الرواتب سطرٌ باسم كل موظف، "
                       f"وفي كشف حساب الموظف راتبه دائناً.")
            self.load()
        except Exception as e:
            err(self, e)

    def refresh(self):
        self.load()
