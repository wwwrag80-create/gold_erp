# -*- coding: utf-8 -*-
"""شاشة تسوية فاقد التصنيع الشهرية: مطابقة خزينة التصنيع مع الجرد الفعلي."""
from datetime import datetime

from PyQt5 import QtWidgets

from database.database import db
from services import karat_view as kv
from models import editing, shrinkage
from services.accounting_engine import balance_by_code
from ui.widgets.common import (big_label, date_edit, dstr, err, info,
                               title_label, wspin)


from ui.widgets.edit_mode import EditModeMixin


class ShrinkageScreen(EditModeMixin, QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.tazeena = big_label()
        self.weight = wspin()
        self.date = date_edit()
        self.period = QtWidgets.QLineEdit(datetime.now().strftime("%Y-%m"))
        self.period.setMaximumWidth(140)
        self.notes = QtWidgets.QLineEdit()
        btn_save = QtWidgets.QPushButton("ترحيل قيد تسوية الفاقد")
        btn_save.clicked.connect(self.save)
        self.init_edit_mode(btn_save, "تسوية الفاقد")

        form = QtWidgets.QFormLayout()
        form.addRow(
            f"وزن الفاقد بتقرير مدير التصنيع ({kv.unit()}):",
            self.weight)
        form.addRow("الفترة (YYYY-MM):", self.period)
        form.addRow("التاريخ:", self.date)
        form.addRow("ملاحظات (خياسات/جلي/تشغيل):", self.notes)

        box = QtWidgets.QGroupBox(
            "القيد الآلي: مدين صندوق فاقد الذهب — قسم التصنيع / "
            "دائن خزينة التصنيع")
        bl = QtWidgets.QVBoxLayout(box)
        bl.addLayout(form)
        bl.addWidget(self.edit_banner)
        srow = QtWidgets.QHBoxLayout()
        srow.addWidget(btn_save, 1)
        srow.addWidget(self.btn_cancel_edit)
        bl.addLayout(srow)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("تسوية فاقد التصنيع الشهرية"))
        lay.addWidget(self.tazeena)
        lay.addWidget(box)
        lay.addStretch(1)
        note = QtWidgets.QLabel(
            "لعرض سجل تسويات الفاقد السابقة أو حذفها منطقياً: افتح شاشة "
            "(سجل العمليات).")
        note.setObjectName("cardSub")
        lay.addWidget(note)

    def save(self):
        try:
            # التحقق من حياة القيد **قبل** فتح المعاملة — لا داخلها
            self.verify_edit_target()
            args = (kv.store(self.weight.value()), dstr(self.date),
                    self.period.text().strip(), self.user["username"],
                    self.notes.text())
            with db() as conn:
                if self.is_editing:
                    res = editing.repost(
                        conn, self.editing_entry_id, self.user["username"],
                        shrinkage.create_shrinkage, *args)
                else:
                    res = shrinkage.create_shrinkage(conn, *args)
            info(self, f"تم ترحيل التسوية {res['op_no']} "
                       f"بوزن {kv.g(res['weight']):.2f} {kv.unit()}")
            self.end_edit()
            self.weight.setValue(0)
            self.notes.clear()
            self.refresh()
        except Exception as e:
            err(self, e)

    def load_document(self, source_id):
        try:
            with db() as conn:
                op = editing.load_document(conn, "shrinkage_ops", source_id)
                if not op:
                    raise ValueError("العملية غير موجودة")
                eid = editing.entry_of(conn, "shrinkage_ops", source_id)
            self.weight.setValue(kv.g(op["weight"]))
            self.period.setText(op["period"] or "")
            self.notes.setText(op["notes"] or "")
            self.begin_edit(eid, source_id)
        except Exception as e:
            err(self, e)

    def refresh(self):
        with db() as conn:
            g = balance_by_code(conn, "1100")[0]
            loss = balance_by_code(conn, "5110")[0]
        self.tazeena.setText(
            f"رصيد خزينة التصنيع الدفتري: {kv.g(g):,.2f} جم "
            f"{kv.label()} | "
            f"مجمع فاقد التصنيع: {kv.g(loss):,.2f} جم")
