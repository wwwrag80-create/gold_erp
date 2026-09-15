# -*- coding: utf-8 -*-
"""حوار تسوية أوزان الطقم — يُفتح بالنقر المزدوج على أي طقم في لوحة
الأطقم المتاحة. يعرض الأوزان الحالية، يسمح بتعديلها، ويرحّل الفارق في
حساب الذهب المشغول عبر models.inventory.adjust_wo_weight.
"""
from PyQt5 import QtWidgets

from database.database import db
from models import inventory
from services import gold_math
from ui.widgets.common import ask, err, info, wspin


class WorkOrderAdjustDialog(QtWidgets.QDialog):
    def __init__(self, parent, wo_id, user):
        super().__init__(parent)
        self.wo_id = wo_id
        self.user = user
        self.setWindowTitle("تسوية أوزان الطقم")
        self.setMinimumWidth(440)

        with db() as conn:
            wo = conn.execute(
                "SELECT * FROM work_orders WHERE id=?", (wo_id,)).fetchone()
        if not wo:
            raise ValueError("الطقم غير موجود")
        self.wo = wo
        self.rate = wo["discount_rate"]

        self.gold = wspin()
        self.gold.setValue(wo["gold_weight"])
        self.small = wspin()
        self.small.setValue(wo["small_stones"])
        self.big = wspin()
        self.big.setValue(wo["big_stones"])
        for w in (self.gold, self.small, self.big):
            w.valueChanged.connect(self.recalc)
        self.contra = QtWidgets.QComboBox()
        for code, name in inventory.ADJUST_CONTRA_ACCOUNTS:
            self.contra.addItem(f"{code} — {name}", code)
        self.contra.currentIndexChanged.connect(self.recalc)
        self.notes = QtWidgets.QLineEdit()
        self.notes.setPlaceholderText("بيان التسوية (اختياري)")

        self.preview = QtWidgets.QLabel()
        self.preview.setObjectName("big")
        self.preview.setWordWrap(True)

        form = QtWidgets.QFormLayout()
        form.addRow(QtWidgets.QLabel(
            f"رقم التشغيل: {wo['work_order_no']}  ·  النوع الحالي: "
            f"{wo['item_type'] or '—'}"))
        form.addRow("الذهب (جم):", self.gold)
        form.addRow("الفصوص (جم):", self.small)
        form.addRow("الأحجار (جم):", self.big)
        self.contra_label = QtWidgets.QLabel("الحساب المقابل (للنقص):")
        form.addRow(self.contra_label, self.contra)
        form.addRow("البيان:", self.notes)
        form.addRow(self.preview)

        btn_delete = QtWidgets.QPushButton("🗑 حذف الطقم نهائياً")
        btn_delete.setObjectName("ghost")
        btn_delete.setToolTip(
            "يخرج الطقم من الذهب المشغول مقابل حساب التسويات")
        btn_delete.clicked.connect(self.delete_wo)
        box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        box.accepted.connect(self.save)
        box.rejected.connect(self.reject)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(form)
        brow = QtWidgets.QHBoxLayout()
        brow.addWidget(btn_delete)
        brow.addStretch(1)
        brow.addWidget(box)
        lay.addLayout(brow)
        self.recalc()

    def recalc(self):
        new_reg = gold_math.registered_weight(
            self.gold.value(), self.small.value(), self.big.value(), self.rate)
        diff = round(new_reg - self.wo["registered_weight"], 3)
        item_type = inventory.classify_item(
            self.wo["work_order_no"], self.gold.value(),
            self.small.value(), self.big.value())
        sign = "زيادة" if diff > 0 else ("نقص" if diff < 0 else "بدون فرق")
        # الزيادة: الطرف الدائن آلي (4310) فيُخفى الاختيار.
        # النقص: المستخدم يحدد وجهة النقص.
        is_decrease = diff < 0
        self.contra.setVisible(is_decrease)
        self.contra_label.setVisible(is_decrease)
        contra = self.contra.currentData() or "—"
        if diff > 0:
            entry = (f"القيد: مدين الذهب المشغول (1200) {diff:.2f} جم / "
                     f"دائن تسوية الزيادة في الطقوم "
                     f"({inventory.WO_INCREASE_ACCOUNT}) {diff:.2f} جم")
        elif diff < 0:
            entry = (f"القيد: مدين {contra} {-diff:.2f} جم / "
                     f"دائن الذهب المشغول (1200) {-diff:.2f} جم")
        else:
            entry = "لا فرق وزني — لن يُرحَّل قيد"
        self.preview.setText(
            f"الوزن المقيد الحالي: {self.wo['registered_weight']:.2f} جم  →  "
            f"الجديد: {new_reg:.2f} جم\n"
            f"الفرق: {diff:+.2f} جم ({sign})  ·  النوع بعد التعديل: {item_type}\n"
            f"{entry}")

    def delete_wo(self):
        """يحذف الطقم ويُخرجه من المخزون مقابل حساب التسويات."""
        try:
            with db() as conn:
                wo = conn.execute(
                    "SELECT work_order_no, registered_weight FROM work_orders"
                    " WHERE id=?", (self.wo_id,)).fetchone()
            if not wo:
                raise ValueError("الطقم غير موجود")
            if not ask(self,
                       f"حذف الطقم {wo['work_order_no']} نهائياً؟\n\n"
                       f"سيخرج {wo['registered_weight']:,.2f} جم من "
                       f"الذهب المشغول\nمقابل حساب «تسويات أوزان "
                       f"الطقوم».\n\nالبيان: حذف رقم التشغيل "
                       f"{wo['work_order_no']}\n\nلا يمكن التراجع."):
                return
            with db() as conn:
                r = inventory.adjust_or_delete_wo(
                    conn, self.wo_id, self.user["username"], delete=True,
                    notes=self.notes.text().strip()
                    if hasattr(self, "notes") else "")
            info(self, f"{r['label']}\nخرج {abs(r['diff']):,.2f} جم من "
                       f"الذهب المشغول إلى حساب التسويات.")
            self.accept()
        except Exception as e:
            err(self, e)

    def save(self):
        """يرحّل التسوية عبر الدالة الموحّدة مقابل حساب التسويات.

        تُستخدم `adjust_or_delete_wo` حصراً (لا الدالة القديمة) فيكون
        القيد بتاريخ اليوم وببيان صريح باسم رقم التشغيل، ويظهر صفاً
        مستقلاً في كشف الحساب بنوع «تسوية».
        """
        try:
            with db() as conn:
                r = inventory.adjust_or_delete_wo(
                    conn, self.wo_id, self.user["username"],
                    new_gold=self.gold.value(),
                    new_small=self.small.value(),
                    new_big=self.big.value(),
                    notes=self.notes.text().strip())
            info(self, f"{r['label']}\n"
                       f"الوزن المقيد: {r['old_reg']:,.2f} → "
                       f"{r['new_reg']:,.2f} جم (فرق {r['diff']:+,.2f})\n\n"
                       f"رُحّل الفرق مقابل حساب «تسويات أوزان الطقوم».")
            self.accept()
        except Exception as e:
            err(self, e)
