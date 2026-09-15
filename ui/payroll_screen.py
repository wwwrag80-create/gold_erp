# -*- coding: utf-8 -*-
"""شاشة الرواتب والموظفين: موظفون وسلف + إقفال الاستحقاق وصرف الرواتب."""
from datetime import datetime

from PyQt5 import QtWidgets

from database.database import db
from models import payroll
from ui.widgets.common import (big_label, date_edit, dstr, enter_chain, err,
                               fill, info, make_table, mspin, reload_combo,
                               search_combo, title_label)


class PayrollScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self._build_employees_tab(), "الموظفون والسلف")
        tabs.addTab(self._build_payroll_tab(), "إقفال وصرف الرواتب")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("الرواتب والأجور — أساس الاستحقاق المحاسبي"))
        lay.addWidget(tabs)

    # ---------- تبويب الموظفين والسلف ----------
    def _build_employees_tab(self):
        w = QtWidgets.QWidget()
        self.emp_name = QtWidgets.QLineEdit()
        self.emp_salary = mspin()
        btn_add = QtWidgets.QPushButton("إضافة الموظف")
        btn_add.clicked.connect(self.add_employee)
        add_box = QtWidgets.QGroupBox("موظف جديد")
        af = QtWidgets.QFormLayout(add_box)
        af.addRow("اسم الموظف:", self.emp_name)
        af.addRow("الراتب الأساسي (ريال):", self.emp_salary)
        af.addRow(btn_add)
        enter_chain(self, [self.emp_name, self.emp_salary], self.add_employee)

        self.adv_emp = search_combo("اكتب اسم الموظف…")
        self.adv_amount = mspin()
        self.adv_pay = QtWidgets.QComboBox()
        self.adv_pay.addItem("الصندوق", "1400")
        self.adv_pay.addItem("البنك", "1500")
        self.adv_date = date_edit()
        self.adv_notes = QtWidgets.QLineEdit()
        btn_adv = QtWidgets.QPushButton("صرف السلفة وترحيل القيد")
        btn_adv.clicked.connect(self.give_advance)
        adv_box = QtWidgets.QGroupBox(
            "سلفة نقدية أثناء الشهر (مدين سلف الموظفين / دائن الصندوق)")
        vf = QtWidgets.QFormLayout(adv_box)
        vf.addRow("الموظف:", self.adv_emp)
        vf.addRow("مبلغ السلفة:", self.adv_amount)
        vf.addRow("الصرف من:", self.adv_pay)
        vf.addRow("التاريخ:", self.adv_date)
        vf.addRow("ملاحظات:", self.adv_notes)
        vf.addRow(btn_adv)
        enter_chain(self, [self.adv_amount, self.adv_notes], self.give_advance)

        self.emp_table = make_table()
        ebox = QtWidgets.QGroupBox("سجل الموظفين والسلف القائمة")
        el = QtWidgets.QVBoxLayout(ebox)
        el.addWidget(self.emp_table)

        lay = QtWidgets.QVBoxLayout(w)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(add_box)
        row.addWidget(adv_box)
        lay.addLayout(row)
        lay.addWidget(ebox, 1)
        return w

    def add_employee(self):
        try:
            with db() as conn:
                payroll.add_employee(conn, self.emp_name.text(),
                                     self.emp_salary.value(),
                                     self.user["username"])
            info(self, "تمت إضافة الموظف")
            self.emp_name.clear()
            self.emp_salary.setValue(0)
            self.refresh()
        except Exception as e:
            err(self, e)

    def give_advance(self):
        try:
            emp_id = self.adv_emp.currentData()
            if emp_id is None:
                raise ValueError("اختر الموظف")
            with db() as conn:
                res = payroll.give_advance(conn, emp_id,
                                           self.adv_amount.value(),
                                           self.adv_pay.currentData(),
                                           dstr(self.adv_date),
                                           self.user["username"],
                                           self.adv_notes.text())
            info(self, f"تم صرف السلفة (قيد {res['entry_id']})\n"
                       f"إجمالي السلف القائمة على الموظف: "
                       f"{res['outstanding']:,.2f} ريال")
            self.adv_amount.setValue(0)
            self.adv_notes.clear()
            self.refresh()
        except Exception as e:
            err(self, e)

    # ---------- تبويب الاستحقاق والصرف ----------
    def _build_payroll_tab(self):
        w = QtWidgets.QWidget()
        self.balances = big_label()
        self.period = QtWidgets.QLineEdit(datetime.now().strftime("%Y-%m"))
        self.period.setMaximumWidth(140)
        btn_accrue = QtWidgets.QPushButton("إقفال رواتب الشهر (قيد الاستحقاق)")
        btn_accrue.clicked.connect(self.run_accrual)
        self.pay_source = QtWidgets.QComboBox()
        self.pay_source.addItem("الصندوق", "1400")
        self.pay_source.addItem("البنك", "1500")
        self.pay_date = date_edit()
        btn_pay = QtWidgets.QPushButton("صرف رواتب الفترة (خصم السلف آلياً)")
        btn_pay.clicked.connect(self.pay_salaries)

        row1 = QtWidgets.QHBoxLayout()
        row1.addWidget(QtWidgets.QLabel("الفترة (YYYY-MM):"))
        row1.addWidget(self.period)
        row1.addWidget(btn_accrue)
        row1.addStretch(1)
        row2 = QtWidgets.QHBoxLayout()
        row2.addWidget(QtWidgets.QLabel("الصرف من:"))
        row2.addWidget(self.pay_source)
        row2.addWidget(QtWidgets.QLabel("تاريخ الصرف:"))
        row2.addWidget(self.pay_date)
        row2.addWidget(btn_pay)
        row2.addStretch(1)

        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(self.balances)
        lay.addLayout(row1)
        lay.addLayout(row2)
        lay.addStretch(1)
        note = QtWidgets.QLabel(
            "لعرض سجل حركات الرواتب (استحقاق/سلف/صرف) أو حذفها منطقياً: "
            "افتح شاشة (سجل العمليات).")
        note.setObjectName("cardSub")
        lay.addWidget(note)
        return w

    def run_accrual(self):
        try:
            with db() as conn:
                res = payroll.run_accrual(conn, self.period.text().strip(),
                                          self.user["username"])
            if not res:
                info(self, "لا يوجد استحقاق جديد لهذه الفترة "
                           "(مُقفلة مسبقاً أو لا موظفون نشطون)")
            else:
                lines = "\n".join(f"• {n}: {a:,.2f} ريال" for n, a in res)
                info(self, f"تم إقفال رواتب {self.period.text()} "
                           f"لعدد {len(res)} موظف:\n{lines}")
            self.refresh()
        except Exception as e:
            err(self, e)

    def pay_salaries(self):
        try:
            with db() as conn:
                res = payroll.pay_salaries(conn, self.period.text().strip(),
                                           self.pay_source.currentData(),
                                           dstr(self.pay_date),
                                           self.user["username"])
            lines = "\n".join(
                f"• {n}: إجمالي {g:,.2f} − سلفة {d:,.2f} = صافي {net:,.2f}"
                for n, g, d, net in res["rows"])
            info(self, f"تم صرف الرواتب (قيد {res['entry_id']}):\n{lines}")
            self.refresh()
        except Exception as e:
            err(self, e)

    def refresh(self):
        with db() as conn:
            emps = payroll.list_employees(conn)
            erows = [(e["name"], e["basic_salary"],
                      payroll.advance_outstanding(conn, e["id"]),
                      payroll.accrued_outstanding(conn, e["id"]),
                      "نشط" if e["is_active"] else "موقوف") for e in emps]
            reload_combo(self.adv_emp, emps, lambda r: r["name"])
            b = payroll.payroll_balances(conn)
        fill(self.emp_table, ["الموظف", "الراتب الأساسي", "سلف قائمة",
                              "مستحق له (دائن)", "الحالة"], erows)
        self.balances.setText(
            f"مصروف الرواتب المتراكم: {b['expense']:,.2f} | "
            f"مستحقات الموظفين غير المصروفة (التزام): {b['accrued']:,.2f} | "
            f"سلف الموظفين القائمة: {b['advances']:,.2f} ريال")
