# -*- coding: utf-8 -*-
"""شاشة التسكير: تسوية مديونية الذهب لأي جهة تعامل بأحد وضعين —
تسكير بسعر (وزن × سعر يزيد الرصيد النقدي)، أو تسكير ذهب فقط (يخفّض
الوزن دون أي أثر نقدي عند ترك المبلغ فارغاً أو صفراً)."""
from PyQt5 import QtWidgets

from database.database import db
from models import editing, entities, fixing
from ui.widgets.common import (confirm_post, big_label, date_edit, dstr, enter_chain, err,
                               info, mspin, reload_combo, search_combo,
                               title_label, wspin)


from ui.widgets.edit_mode import EditModeMixin


class FixingScreen(EditModeMixin, QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user

        self.customer = search_combo("اكتب اسم الجهة…")
        self.customer.currentIndexChanged.connect(self.show_balances)
        self.balances = big_label()
        self.weight = wspin()
        self.price = mspin()
        self.gold_only = QtWidgets.QCheckBox(
            "تسكير ذهب فقط (بدون مبلغ نقدي)")
        self.gold_only.stateChanged.connect(self.toggle_gold_only)
        self.amount = big_label("المبلغ = 0.00 ريال")
        self.weight.valueChanged.connect(self.recalc)
        self.price.valueChanged.connect(self.recalc)
        self.date = date_edit()

        btn_save = QtWidgets.QPushButton("تنفيذ التسكير وترحيل القيد")
        btn_save.clicked.connect(self.save)
        self.init_edit_mode(btn_save, "التسكير")

        form = QtWidgets.QFormLayout()
        form.addRow("الجهة (عميل/مورد/شريك/داخلي):", self.customer)
        form.addRow(self.balances)
        form.addRow("الوزن المراد تسكيره (جم عيار 18):", self.weight)
        form.addRow(self.gold_only)
        form.addRow("سعر الجرام اليوم (ريال):", self.price)
        form.addRow(self.amount)
        form.addRow("التاريخ:", self.date)

        box = QtWidgets.QGroupBox(
            "القطع: ينقص الرصيد الوزني (ذهب) للجهة المختارة ويزيد رصيدها "
            "النقدي/الجاري (الوزن × السعر)")
        bl = QtWidgets.QVBoxLayout(box)
        bl.addLayout(form)
        bl.addWidget(self.edit_banner)
        srow = QtWidgets.QHBoxLayout()
        srow.addWidget(btn_save, 1)
        srow.addWidget(self.btn_cancel_edit)
        bl.addLayout(srow)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("عملية التسكير — Gold Price Fixing"))
        enter_chain(self, [self.weight, self.price], self.save)
        lay.addWidget(box)
        lay.addStretch(1)
        note = QtWidgets.QLabel(
            "لعرض سجل عمليات التسكير السابقة: افتح شاشة (سجل العمليات).")
        note.setObjectName("cardSub")
        lay.addWidget(note)

    def toggle_gold_only(self):
        """وضع الذهب فقط: يُعطِّل حقلي السعر والمبلغ ويصفّرهما."""
        go = self.gold_only.isChecked()
        self.price.setEnabled(not go)
        if go:
            self.price.setValue(0)
        self.recalc()

    def recalc(self):
        if self.gold_only.isChecked():
            self.amount.setText("تسكير ذهب فقط — لا مبلغ نقدي")
        else:
            self.amount.setText(
                f"المبلغ = {self.weight.value() * self.price.value():,.2f} ريال")

    def show_balances(self):
        cid = self.customer.currentData()
        if cid is None:
            self.balances.setText("")
            return
        if not confirm_post(self, "عملية تسكير"):
            return

        with db() as conn:
            g, c = entities.balances(conn, cid)
        self.balances.setText(
            f"الرصيد الحالي — ذهب: {g:,.2f} جم | نقد/جاري: {c:,.2f} ريال")

    def save(self):
        try:
            # التحقق من حياة القيد **قبل** فتح المعاملة — لا داخلها
            self.verify_edit_target()
            cid = self.customer.currentData()
            if cid is None:
                raise ValueError("اختر الجهة")
            with db() as conn:
                if self.is_editing:
                    res = editing.repost(
                        conn, self.editing_entry_id, self.user["username"],
                        fixing.create_fixing, cid, self.weight.value(),
                        (0 if self.gold_only.isChecked()
                         else self.price.value()),
                        dstr(self.date), self.user["username"])
                else:
                    res = fixing.create_fixing(
                        conn, cid, self.weight.value(),
                        (0 if self.gold_only.isChecked()
                         else self.price.value()),
                        dstr(self.date), self.user["username"])
            msg = (f"تم تسكير {res['weight']:,.2f} جم ذهباً فقط ({res['op_no']})"
                   if res.get("gold_only")
                   else f"تم التسكير {res['op_no']} بمبلغ "
                        f"{res['amount']:,.2f} ريال")
            info(self, msg)
            self.end_edit()
            self.weight.setValue(0)
            self.refresh()
        except Exception as e:
            err(self, e)

    def load_document(self, source_id):
        """يفتح عملية تسكير قائمة للتعديل ويعبّئ حقولها."""
        try:
            with db() as conn:
                op = editing.load_document(conn, "fixing_ops", source_id)
                if not op:
                    raise ValueError("العملية غير موجودة")
                eid = editing.entry_of(conn, "fixing_ops", source_id)
            self.refresh()
            idx = self.customer.findData(op["entity_id"])
            if idx >= 0:
                self.customer.setCurrentIndex(idx)
            self.weight.setValue(op["weight"])
            self.gold_only.setChecked((op["price"] or 0) <= 0)
            self.price.setValue(op["price"] or 0)
            self.begin_edit(eid, source_id)
        except Exception as e:
            err(self, e)

    def refresh(self):
        with db() as conn:
            reload_combo(self.customer, entities.list_entities(conn),
                        lambda r: (("🏭 " if r["is_internal"] else
                                   f"[{entities.TYPE_LABELS[r['entity_type']]}] ")
                                  + r["name"]))
        self.show_balances()
        self.recalc()
