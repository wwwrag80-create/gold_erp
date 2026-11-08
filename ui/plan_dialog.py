# -*- coding: utf-8 -*-
"""نافذة خطة الحساب — للمدير العام (5.2.1).

نوع النظام (مصنع · محلات · عميل) ← فتُحدَّد شاشاته الافتراضية، ثم يُعدَّل
ما يظهر منها بعلامة، ومدة الاشتراك (آخر يوم)، وعدد الأجهزة المسموح.
"""
import datetime as _dt

from PyQt5 import QtCore, QtWidgets

from services import plan
from ui import kit

_NOTES = {
    plan.FACTORY: "مصنع: كل الشاشات — التصنيع والوارد والمبيعات والحسابات.",
    plan.SHOP: "محلات: كل شاشات البيع والحسابات — بلا شاشات الورشة "
               "والتصنيع.",
    plan.CUSTOMER: "عميل: يبيع ويرتجع أي طقم برقم تشغيله ووزنه مباشرةً من "
                   "شاشة المبيعات — بلا حاجةٍ إلى شاشة الوارد. ويرى كشوفه "
                   "وسنداته.",
}


class PlanDialog(QtWidgets.QDialog):
    """`values()` ← {type, screens, expires_at, max_devices}."""

    def __init__(self, parent, title, current=None, devices_used=None,
                 on_reset_devices=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setLayoutDirection(QtCore.Qt.RightToLeft)
        self.setMinimumSize(560, 620)
        cur = plan.normalize(current) if current else None
        self._on_reset = on_reset_devices

        # ── نوع النظام ──
        self.kind = kit.ComboBox()
        for k, label in plan.TYPES:
            self.kind.addItem(label, k)
        self.kind_note = QtWidgets.QLabel("")
        self.kind_note.setObjectName("cardSub")
        self.kind_note.setWordWrap(True)

        # ── الشاشات ──
        self.screens = QtWidgets.QListWidget()
        self._items = {}
        for head, names in (("الشاشات الرئيسية", plan.MAIN_SCREENS),
                            ("الإدارة والتقارير", plan.ADMIN_SCREENS)):
            h = QtWidgets.QListWidgetItem(f"— {head} —")
            h.setFlags(QtCore.Qt.NoItemFlags)
            f = h.font()
            f.setBold(True)
            h.setFont(f)
            self.screens.addItem(h)
            for n in names:
                it = QtWidgets.QListWidgetItem(n)
                it.setFlags(QtCore.Qt.ItemIsEnabled
                            | QtCore.Qt.ItemIsUserCheckable)
                it.setCheckState(QtCore.Qt.Unchecked)
                self.screens.addItem(it)
                self._items[n] = it
        b_all = kit.PushButton("تحديد الكل")
        b_all.clicked.connect(lambda: self._check(plan.ALL_SCREENS))
        b_none = kit.PushButton("مسح الكل")
        b_none.clicked.connect(lambda: self._check(()))
        b_def = kit.PushButton("شاشات النوع الافتراضية")
        b_def.clicked.connect(self._preset)
        sb = QtWidgets.QHBoxLayout()
        sb.addWidget(b_all)
        sb.addWidget(b_none)
        sb.addWidget(b_def)
        sb.addStretch(1)

        # ── مدة الاشتراك ──
        self.unlimited = kit.CheckBox("بلا نهاية")
        self.expires = kit.DateEdit()
        self.expires.setCalendarPopup(True)
        self.expires.setDate(QtCore.QDate.currentDate().addYears(1))
        self.unlimited.toggled.connect(
            lambda on: self.expires.setEnabled(not on))
        exp_row = QtWidgets.QHBoxLayout()
        exp_row.addWidget(self.expires)
        for label, months in (("شهر", 1), ("3 أشهر", 3), ("سنة", 12)):
            b = kit.PushButton(f"+ {label}")
            b.clicked.connect(lambda _=False, m=months: self._extend(m))
            exp_row.addWidget(b)
        exp_row.addWidget(self.unlimited)
        exp_row.addStretch(1)

        # ── الأجهزة ──
        self.devices = kit.SpinBox()
        self.devices.setRange(0, 999)
        self.devices.setSpecialValueText("بلا حد")
        self.devices.setValue(1)
        dev_row = QtWidgets.QHBoxLayout()
        dev_row.addWidget(self.devices)
        used = QtWidgets.QLabel(
            f"المسجّل الآن: {devices_used} جهاز" if devices_used is not None
            else "")
        used.setObjectName("cardSub")
        dev_row.addWidget(used)
        if on_reset_devices is not None:
            b_reset = kit.PushButton("تفريغ قائمة الأجهزة")
            b_reset.setToolTip("يُسجَّل كل جهازٍ من جديد عند دخوله التالي "
                               "— لاستبدال جهازٍ تعطّل أو بِيع")
            b_reset.clicked.connect(self._reset_devices)
            dev_row.addWidget(b_reset)
        dev_row.addStretch(1)

        form = QtWidgets.QFormLayout()
        form.addRow("نوع النظام:", self.kind)
        form.addRow("", self.kind_note)
        form.addRow("الاشتراك حتى:", exp_row)
        form.addRow("عدد الأجهزة:", dev_row)

        box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        box.button(QtWidgets.QDialogButtonBox.Ok).setText("حفظ")
        box.button(QtWidgets.QDialogButtonBox.Cancel).setText("إلغاء")
        box.accepted.connect(self._accept)
        box.rejected.connect(self.reject)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(QtWidgets.QLabel("الشاشات التي تظهر في نظامه:"))
        lay.addWidget(self.screens, 1)
        lay.addLayout(sb)
        lay.addWidget(box)

        # القيم الحالية — أو افتراضي «مصنع» لحسابٍ جديد
        if cur:
            i = self.kind.findData(cur["type"])
            self.kind.setCurrentIndex(max(0, i))
            self._check(cur["screens"] or plan.ALL_SCREENS)
            if cur["expires_at"]:
                self.expires.setDate(QtCore.QDate.fromString(
                    cur["expires_at"], "yyyy-MM-dd"))
                self.unlimited.setChecked(False)
            else:
                self.unlimited.setChecked(True)
            self.devices.setValue(cur["max_devices"])
        else:
            self._preset()
        self._note()
        self.kind.currentIndexChanged.connect(self._kind_changed)

    # ── سلوك ──
    def _note(self):
        self.kind_note.setText(_NOTES.get(self.kind.currentData(), ""))

    def _kind_changed(self, *_):
        self._note()
        self._preset()

    def _preset(self):
        self._check(plan.PRESETS.get(self.kind.currentData(),
                                     plan.ALL_SCREENS))

    def _check(self, names):
        names = set(names or ())
        for n, it in self._items.items():
            it.setCheckState(QtCore.Qt.Checked if n in names
                             else QtCore.Qt.Unchecked)

    def _extend(self, months):
        base = self.expires.date()
        today = QtCore.QDate.currentDate()
        if self.unlimited.isChecked() or base < today:
            base = today
        self.unlimited.setChecked(False)
        self.expires.setDate(base.addMonths(months))

    def _reset_devices(self):
        try:
            if self._on_reset():
                kit.notify(self, "فُرّغت قائمة الأجهزة")
        except Exception as e:
            from ui.widgets.common import err
            err(self, e)

    def _accept(self):
        if not self.checked():
            from ui.widgets.common import err
            err(self, "اختر شاشةً واحدة على الأقل")
            return
        self.accept()

    def checked(self):
        return [n for n, it in self._items.items()
                if it.checkState() == QtCore.Qt.Checked]

    def values(self):
        scr = self.checked()
        # كل الشاشات ⇒ قائمة فارغة: «الكل» — فالشاشة الجديدة بعد أي تحديث
        # تظهر له أيضاً
        if set(scr) >= set(plan.ALL_SCREENS):
            scr = []
        exp = ""
        if not self.unlimited.isChecked():
            from ui.widgets.common import dstr
            exp = dstr(self.expires)
        return {"type": self.kind.currentData(), "screens": scr,
                "expires_at": exp, "max_devices": int(self.devices.value())}


def summary(p):
    """سطرٌ مختصر للخطة في الجدول: النوع · حتى · الأجهزة."""
    if not p:
        return ("—", "—", "—")
    p = plan.normalize(p)
    exp = p["expires_at"] or "بلا نهاية"
    left = plan.days_left(p, _dt.date.today())
    if left is not None and left < 0:
        exp += " (منتهٍ)"
    dev = (f"{p['devices_used']} / {p['max_devices']}" if p["max_devices"]
           else f"{p['devices_used']} / بلا حد")
    return (plan.TYPE_LABEL.get(p["type"], p["type"]), exp, dev)
