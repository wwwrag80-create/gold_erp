# -*- coding: utf-8 -*-
"""المشتريات — آجلة إلزامياً على حساب المورد (لا سداد نقدي مباشر من
هذه الشاشة؛ السداد حصراً عبر شاشة السندات) + الأصول والإهلاك الشهري."""
from PyQt5 import QtWidgets

import config
from database.database import db
from models import editing, entities, purchases
from ui.widgets.common import (confirm_post, date_edit, dstr, enter_chain,
                               err, mspin, posted, reload_combo,
                               search_combo, title_label)


class NewSupplierDialog(QtWidgets.QDialog):
    def __init__(self, parent, username):
        super().__init__(parent)
        self.username = username
        self.supplier_id = None
        self.setWindowTitle("مورد جديد")
        self.name = QtWidgets.QLineEdit()
        self.phone = QtWidgets.QLineEdit()
        self.vat = QtWidgets.QLineEdit()
        form = QtWidgets.QFormLayout(self)
        form.addRow("اسم المورد:", self.name)
        form.addRow("الجوال:", self.phone)
        form.addRow("الرقم الضريبي (إلزامي):", self.vat)
        btn = QtWidgets.QPushButton("حفظ")
        btn.clicked.connect(self.save)
        form.addRow(btn)

    def save(self):
        try:
            if not self.name.text().strip():
                raise ValueError("أدخل اسم المورد")
            if not confirm_post(self, "فاتورة مشتريات"):
                return

            with db() as conn:
                self.supplier_id = entities.add_entity(
                    conn, self.name.text().strip(), "supplier",
                    self.phone.text().strip(), self.vat.text().strip(),
                    self.username)
            self.accept()
        except Exception as e:
            err(self, e)


from ui.widgets.edit_mode import EditModeMixin


class PurchasesScreen(EditModeMixin, QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self._build_purchase_tab(), "فاتورة مشتريات آجلة")
        tabs.addTab(self._build_assets_tab(), "الأصول الثابتة والإهلاك")
        tabs.currentChanged.connect(self._ensure_assets)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("المشتريات والقيود الرأسمالية"))
        lay.addWidget(tabs)

    # ---------- تبويب المشتريات ----------
    def _build_purchase_tab(self):
        w = QtWidgets.QWidget()
        self.kind = QtWidgets.QComboBox()
        self.kind.addItem("مصروف تشغيلي", "expense")
        self.kind.addItem("أصل ثابت (مكينة/معدة)", "asset")
        self.supplier = search_combo("اكتب اسم المورد…")
        btn_new_sup = QtWidgets.QPushButton("+ مورد جديد")
        btn_new_sup.setObjectName("ghost")
        btn_new_sup.clicked.connect(self.new_supplier)
        self.desc = QtWidgets.QLineEdit()
        self.amount = mspin()
        self.amount.valueChanged.connect(
            lambda v: self.vat.setValue(round(v * config.VAT_RATE, 2)))
        self.vat = mspin()
        self.p_date = date_edit()

        sup_row = QtWidgets.QHBoxLayout()
        sup_row.addWidget(self.supplier, 1)
        sup_row.addWidget(btn_new_sup)

        form = QtWidgets.QFormLayout()
        form.addRow("نوع الفاتورة:", self.kind)
        form.addRow("المورد:", sup_row)
        form.addRow("البيان (اسم الأصل إن كان أصلاً):", self.desc)
        form.addRow("المبلغ قبل الضريبة:", self.amount)
        form.addRow("ضريبة المدخلات 15%:", self.vat)
        form.addRow("التاريخ:", self.p_date)

        btn_save = QtWidgets.QPushButton(
            "ترحيل الفاتورة آجلة (مدين الأصل/المصروف — دائن المورد)")
        btn_save.clicked.connect(self.save_purchase)
        self.init_edit_mode(btn_save, "فاتورة المشتريات")

        lay = QtWidgets.QVBoxLayout(w)
        lay.addLayout(form)
        enter_chain(self, [self.desc, self.amount, self.vat], self.save_purchase)
        lay.addWidget(self.edit_banner)
        srow = QtWidgets.QHBoxLayout()
        srow.addWidget(btn_save, 1)
        srow.addWidget(self.btn_cancel_edit)
        lay.addLayout(srow)
        lay.addStretch(1)
        note = QtWidgets.QLabel(
            "كل المشتريات آجلة إلزامياً — لا سداد نقدي مباشر من هذه الشاشة. "
            "لسداد المورد لاحقاً: شاشة (السندات والخصومات) → سند صرف → اختر "
            "المورد نفسه كجهة تعامل. لعرض سجل الفواتير السابقة: شاشة "
            "(سجل العمليات).")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)
        return w

    def new_supplier(self):
        dlg = NewSupplierDialog(self, self.user["username"])
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self.refresh()
            idx = self.supplier.findData(dlg.supplier_id)
            if idx >= 0:
                self.supplier.setCurrentIndex(idx)

    def save_purchase(self):
        try:
            # التحقق من حياة القيد **قبل** فتح المعاملة — لا داخلها
            self.verify_edit_target()
            sid = self.supplier.currentData()
            if sid is None:
                raise ValueError("اختر المورد (أو أضف مورداً جديداً)")
            args = (self.kind.currentData(), sid, self.desc.text(),
                    self.amount.value(), self.vat.value(), dstr(self.p_date),
                    self.user["username"])
            with db() as conn:
                if self.is_editing:
                    res = editing.repost(
                        conn, self.editing_entry_id, self.user["username"],
                        purchases.create_purchase, *args)
                else:
                    res = purchases.create_purchase(conn, *args)
            posted(self, f"تم ترحيل الفاتورة {res['purchase_no']} آجلة على "
                       f"المورد {res['supplier_name']} — الإجمالي "
                       f"{res['total']:,.2f} ريال", "purchases", res["id"])
            self.end_edit()
            self.desc.clear()
            self.amount.setValue(0)
            self.vat.setValue(0)
            self.refresh()
        except Exception as e:
            err(self, e)

    # ---------- تبويب الأصول والإهلاك ----------
    def _build_assets_tab(self):
        """شاشة الأصول والإهلاك كاملةً — لا جدولَ عرضٍ خاوياً.

        **ما كان هنا**: جدولُ قراءةٍ بأربعة أعمدة وسطرٌ يقول «لا يوجد
        إهلاك تراكمي ولا مصروف إهلاك في النظام» — وهو نصٌّ صار غير
        صحيح بعد أن بُني الإهلاك، وتبويبٌ لا يُفعل فيه شيء.

        **ولماذا هنا**: الأصل يُشترى في هذه الشاشة نفسها، فإهلاكُه
        بجانب شرائه لا في بندٍ آخر من القائمة.

        والبناء كسول: لا تُبنى حتى يُفتح التبويب، فلا تتأخّر شاشة
        المشتريات من أجل تبويبٍ قد لا يُفتح.
        """
        w = QtWidgets.QWidget()
        QtWidgets.QVBoxLayout(w).setContentsMargins(0, 0, 0, 0)
        self._assets_holder = w
        self._assets_screen = None
        return w

    def _ensure_assets(self, index):
        """يبني تبويب الأصول عند أول فتحٍ له."""
        if index != 1 or self._assets_screen is not None:
            return
        try:
            from ui.reports.assets_screen import AssetsScreen
            self._assets_screen = AssetsScreen(self.user, embedded=True)
        except Exception as e:                       # noqa: BLE001
            lbl = QtWidgets.QLabel(f"تعذّر فتح الأصول والإهلاك:\n{e}")
            lbl.setObjectName("warn")
            lbl.setWordWrap(True)
            self._assets_screen = lbl
        self._assets_holder.layout().addWidget(self._assets_screen)

    def load_document(self, source_id):
        try:
            with db() as conn:
                p = editing.load_document(conn, "purchases", source_id)
                if not p:
                    raise ValueError("الفاتورة غير موجودة")
                eid = editing.entry_of(conn, "purchases", source_id)
            self.refresh()
            i = self.kind.findData(p["kind"])
            if i >= 0:
                self.kind.setCurrentIndex(i)
            i = self.supplier.findData(p["supplier_id"])
            if i >= 0:
                self.supplier.setCurrentIndex(i)
            self.desc.setText(p["description"] or "")
            self.amount.setValue(p["amount"] or 0)
            self.vat.setValue(p["vat_amount"] or 0)
            self.begin_edit(eid, source_id)
        except Exception as e:
            err(self, e)

    def refresh(self):
        with db() as conn:
            reload_combo(self.supplier, entities.list_entities(conn, ("supplier",)),
                         lambda r: r["name"])
        # تبويب الأصول يُحدِّث نفسه — ولا يُبنى قبل أن يُفتح
        scr = getattr(self, "_assets_screen", None)
        fn = getattr(scr, "refresh", None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass
