# -*- coding: utf-8 -*-
"""نوع جهة تعامل جديد (5.8.4) — من «التكويد الموحّد» ومن خانة الحساب في
شاشتي المبيعات والمشتريات الضريبية.

يكتب المستخدم اسم النوع (الجمع) واسم الجهة الواحدة منه، ويختار طبيعته:
مدينون لنا كالعملاء أو دائنون لنا كالموردين، وأرصدته ذهباً ونقداً أو نقداً
فقط — فيُنشأ حسابه الرقابي في شجرة الحسابات ويصير نوعاً رسمياً في كل مكان.
"""
from PyQt5 import QtCore, QtWidgets

from ui import kit
from database.database import db
from models import entities, entity_types as et
from ui.widgets.common import err


class NewEntityTypeDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, username="", plural=""):
        super().__init__(parent)
        self.setWindowTitle("نوع جهة جديد")
        self.setLayoutDirection(QtCore.Qt.RightToLeft)
        self.setMinimumWidth(520)
        self.username = username
        self.code = None
        self.plural = kit.LineEdit()
        self.plural.setPlaceholderText("مثال: مكاتب الصيانة · شركات الشحن")
        self.plural.setText(plural or "")
        self.label = kit.LineEdit()
        self.label.setPlaceholderText("مثال: مكتب صيانة — يظهر بجانب كل اسم")
        self.plural.textChanged.connect(self._auto_label)
        self._label_typed = False
        self.label.textEdited.connect(lambda *_: setattr(
            self, "_label_typed", True))
        self.side = {}
        side_box = QtWidgets.QWidget()
        sl = QtWidgets.QVBoxLayout(side_box)
        sl.setContentsMargins(0, 0, 0, 0)
        for k, lbl in et.SIDES:
            rb = QtWidgets.QRadioButton(lbl)
            self.side[k] = rb
            sl.addWidget(rb)
        self.side["asset"].setChecked(True)
        self.bal = kit.ComboBox()
        for k, lbl in et.BALANCES:
            self.bal.addItem(lbl, k)
        self.note = QtWidgets.QLabel("")
        self.note.setObjectName("cardSub")
        self.note.setWordWrap(True)
        for rb in self.side.values():
            rb.toggled.connect(lambda *_: self._sync())
        self.plural.textChanged.connect(lambda *_: self._sync())
        form = QtWidgets.QFormLayout()
        form.addRow("اسم النوع (الجمع):", self.plural)
        form.addRow("اسم الجهة الواحدة:", self.label)
        form.addRow("طبيعة الأرصدة:", side_box)
        form.addRow("الأرصدة:", self.bal)
        bb = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.button(QtWidgets.QDialogButtonBox.Ok).setText("إنشاء النوع")
        bb.button(QtWidgets.QDialogButtonBox.Cancel).setText("إلغاء")
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        v = QtWidgets.QVBoxLayout(self)
        v.addLayout(form)
        v.addWidget(self.note)
        v.addWidget(bb)
        self._sync()

    def _auto_label(self, text):
        if not self._label_typed:
            self.label.setText(text.strip())

    def _side(self):
        return next(k for k, rb in self.side.items() if rb.isChecked())

    def _sync(self):
        side = self._side()
        name = self.plural.text().strip() or "…"
        where = ("«الأصول المتداولة — الذمم المدينة» (1030)" if side == "asset"
                 else "«الخصوم المتداولة» (2010)")
        self.note.setText(
            f"يُنشأ في شجرة الحسابات حسابٌ رقابي «إجمالي {name}» تحت {where}،"
            " وكل جهةٍ من هذا النوع حسابٌ فرعيٌّ تحته. ويظهر النوع في التكويد"
            " الموحّد والسندات والفواتير والكشوف، وله سطرٌ مستقل في الميزانية.")

    def save(self):
        try:
            with db() as conn:
                self.code = et.create(
                    conn, self.plural.text(), self.label.text(), self._side(),
                    self.bal.currentData(), self.username)
            self.accept()
        except Exception as e:                      # noqa: BLE001
            err(self, e)


def new_entity_type(parent, username="", plural=""):
    """يفتح النافذة ويعيد مفتاح النوع الجديد (أو None)."""
    dlg = NewEntityTypeDialog(parent, username, plural)
    if dlg.exec_() == QtWidgets.QDialog.Accepted:
        return dlg.code
    return None


def fill_types(combo, kinds="trade", keep=None):
    """قائمة أنواع الجهات: «trade» العميل والمورد والجهة الأخرى وما أنشأه
    المستخدم، و«all» كل الأنواع."""
    keep = keep if keep is not None else combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    for code, label in entities.all_types():
        if kinds == "trade" and code not in entities.trade_types():
            continue
        combo.addItem(label, code)
    i = combo.findData(keep) if keep is not None else -1
    combo.setCurrentIndex(i if i >= 0 else 0)
    combo.blockSignals(False)
