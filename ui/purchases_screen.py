# -*- coding: utf-8 -*-
"""المشتريات — آجلة إلزامياً على حساب المورد (السداد حصراً من شاشة
السندات)، مرتّبةً كما تطلبها الضريبة والمحاسبة:

  • فاتورة المورد: رقمها وتاريخها والمورد برقمه الضريبي، والحساب الذي
    تُحمَّل عليه، والمعالجة الضريبية، والمبلغ صافياً أو شاملاً —
    ثم **القيد قبل ترحيله**.
  • سجل المشتريات الضريبية: لكل فاتورةٍ رقمها لدى المورد ورقمه الضريبي
    وصافيها وضريبتها، وإجمالي ضريبة المدخلات القابلة للخصم للفترة.
  • الأصول الثابتة والإهلاك.
"""
from PyQt5 import QtCore, QtWidgets

from database.database import db
from models import editing, entities, purchases
from ui.widgets.common import (Card, date_edit, dstr, enter_chain, err,
                               make_table, mspin, num_item, posted,
                               reload_combo, row_height, search_combo,
                               tab_widget, text_item, title_label)
from ui.widgets.entry_preview import EntryPreview
from ui.widgets.table_fit import fit_columns

REG_COLS = ["", "الرقم", "التاريخ", "المورد", "الرقم الضريبي للمورد",
            "فاتورة المورد", "البيان", "المعالجة", "الصافي", "الضريبة",
            "الإجمالي"]
TREAT_SHORT = {"standard": "خاضعة 15%", "blocked": "لا تُسترد",
               "zero": "صفرية", "exempt": "معفاة",
               "unregistered": "غير مسجّل"}


def _m(v):
    return f"{float(v or 0):,.2f}"


class NewSupplierDialog(QtWidgets.QDialog):
    def __init__(self, parent, username):
        super().__init__(parent)
        self.username = username
        self.supplier_id = None
        self.setWindowTitle("مورد جديد")
        self.setMinimumWidth(460)
        self.name = QtWidgets.QLineEdit()
        self.phone = QtWidgets.QLineEdit()
        self.vat = QtWidgets.QLineEdit()
        self.vat.setPlaceholderText("15 رقماً يبدأ بـ3 وينتهي بـ3")
        form = QtWidgets.QFormLayout(self)
        form.addRow("اسم المورد:", self.name)
        form.addRow("الجوال:", self.phone)
        form.addRow("الرقم الضريبي:", self.vat)
        btn = QtWidgets.QPushButton("حفظ المورد")
        btn.clicked.connect(self.save)
        form.addRow(btn)

    def save(self):
        from services.fatoora import profile as pf
        try:
            if not self.name.text().strip():
                raise ValueError("أدخل اسم المورد")
            vat = self.vat.text().strip()
            if vat and not pf.valid_vat(vat):
                if QtWidgets.QMessageBox.question(
                        self, "الرقم الضريبي",
                        "الرقم الضريبي ليس بالصيغة الصحيحة (15 رقماً يبدأ "
                        "بـ3 وينتهي بـ3) — لن تُخصم ضريبة مدخلات فواتير هذا "
                        "المورد حتى يُصحَّح.\nحفظه كما هو؟",
                        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
                ) != QtWidgets.QMessageBox.Yes:
                    return
            with db() as conn:
                self.supplier_id = entities.add_entity(
                    conn, self.name.text().strip(), "supplier",
                    self.phone.text().strip(), vat, self.username)
            self.accept()
        except Exception as e:
            err(self, e)


from ui.widgets.edit_mode import EditModeMixin


class PurchasesScreen(EditModeMixin, QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self._vat_touched = False
        self.tabs = tab_widget()
        self.tabs.addTab(self._build_purchase_tab(), "فاتورة مورد (آجلة)")
        self.tabs.addTab(self._build_register_tab(),
                         "سجل المشتريات الضريبية")
        self.tabs.addTab(self._build_assets_tab(), "الأصول الثابتة والإهلاك")
        self.tabs.currentChanged.connect(self._on_tab)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("المشتريات والقيود الرأسمالية"))
        lay.addWidget(self.tabs)

    # ══════════════════════════ الفاتورة ══════════════════════════
    def _build_purchase_tab(self):
        w = QtWidgets.QWidget()
        self.kind = QtWidgets.QComboBox()
        self.kind.addItem("مصروف تشغيلي", "expense")
        self.kind.addItem("أصل ثابت (مكينة/معدة)", "asset")
        self.kind.currentIndexChanged.connect(self._on_kind)
        self.supplier = search_combo("اكتب اسم المورد…")
        self.supplier.currentIndexChanged.connect(self._on_supplier)
        btn_new_sup = QtWidgets.QPushButton("+ مورد جديد")
        btn_new_sup.setObjectName("ghost")
        btn_new_sup.clicked.connect(self.new_supplier)
        self.sup_vat = QtWidgets.QLabel("—")
        self.sup_vat.setWordWrap(True)
        self.inv_no = QtWidgets.QLineEdit()
        self.inv_no.setPlaceholderText("رقم الفاتورة كما في ورقة المورد")
        self.p_date = date_edit()
        self.desc = QtWidgets.QLineEdit()
        self.desc.setPlaceholderText("البيان (اسم الأصل إن كان أصلاً)")
        self.account = QtWidgets.QComboBox()
        self.account.currentIndexChanged.connect(self._recalc)
        self.life = QtWidgets.QSpinBox()
        self.life.setRange(0, 600)
        self.life.setSuffix(" شهراً")
        self.life.setSpecialValueText("يُحدَّد لاحقاً")
        self.life_lbl = QtWidgets.QLabel("العمر الإنتاجي:")

        sup_row = QtWidgets.QHBoxLayout()
        sup_row.addWidget(self.supplier, 1)
        sup_row.addWidget(btn_new_sup)
        g = QtWidgets.QGridLayout()
        g.addWidget(QtWidgets.QLabel("المورد:"), 0, 0)
        g.addLayout(sup_row, 0, 1)
        g.addWidget(QtWidgets.QLabel("الرقم الضريبي:"), 0, 2)
        g.addWidget(self.sup_vat, 0, 3)
        g.addWidget(QtWidgets.QLabel("رقم فاتورة المورد:"), 1, 0)
        g.addWidget(self.inv_no, 1, 1)
        g.addWidget(QtWidgets.QLabel("تاريخ الفاتورة:"), 1, 2)
        g.addWidget(self.p_date, 1, 3)
        g.addWidget(QtWidgets.QLabel("نوع الفاتورة:"), 2, 0)
        g.addWidget(self.kind, 2, 1)
        g.addWidget(QtWidgets.QLabel("يُحمَّل على حساب:"), 2, 2)
        g.addWidget(self.account, 2, 3)
        g.addWidget(QtWidgets.QLabel("البيان:"), 3, 0)
        g.addWidget(self.desc, 3, 1)
        g.addWidget(self.life_lbl, 3, 2)
        g.addWidget(self.life, 3, 3)
        g.setColumnStretch(1, 3)
        g.setColumnStretch(3, 2)
        box_head = QtWidgets.QGroupBox("فاتورة المورد")
        box_head.setLayout(g)

        self.treat = QtWidgets.QComboBox()
        for k, lbl in purchases.TAX_TREATMENTS:
            self.treat.addItem(lbl, k)
        self.treat.currentIndexChanged.connect(self._auto_vat)
        self.pmode = QtWidgets.QComboBox()
        for k, lbl in purchases.PRICE_MODES:
            self.pmode.addItem(lbl, k)
        self.pmode.currentIndexChanged.connect(self._auto_vat)
        self.amount = mspin()
        self.amount.valueChanged.connect(self._auto_vat)
        self.vat = mspin()
        self.vat.valueChanged.connect(self._on_vat_edit)
        self.amount_lbl = QtWidgets.QLabel("المبلغ:")
        t = QtWidgets.QGridLayout()
        t.addWidget(QtWidgets.QLabel("المعالجة الضريبية:"), 0, 0)
        t.addWidget(self.treat, 0, 1)
        t.addWidget(QtWidgets.QLabel("طريقة إدخال المبلغ:"), 0, 2)
        t.addWidget(self.pmode, 0, 3)
        t.addWidget(self.amount_lbl, 1, 0)
        t.addWidget(self.amount, 1, 1)
        t.addWidget(QtWidgets.QLabel("الضريبة:"), 1, 2)
        t.addWidget(self.vat, 1, 3)
        t.setColumnStretch(1, 3)
        t.setColumnStretch(3, 2)
        box_tax = QtWidgets.QGroupBox("المبلغ والضريبة")
        box_tax.setLayout(t)

        self.c_net = Card("الصافي قبل الضريبة", "يُحمَّل على الحساب")
        self.c_vat = Card("ضريبة المدخلات القابلة للخصم", "حساب 1900")
        self.c_total = Card("المستحق للمورد", "آجل — يُسدَّد بسند صرف",
                            summary=True)
        col = QtWidgets.QVBoxLayout()
        for c in (self.c_total, self.c_net, self.c_vat):
            col.addWidget(c)
        col.addStretch(1)
        self.preview = EntryPreview()
        box_je = QtWidgets.QGroupBox("القيد الذي سيُرحَّل")
        bj = QtWidgets.QVBoxLayout(box_je)
        bj.addWidget(self.preview)
        bj.addStretch(1)
        bottom = QtWidgets.QHBoxLayout()
        bottom.addLayout(col, 2)
        bottom.addWidget(box_je, 5)

        btn_save = QtWidgets.QPushButton("✔ ترحيل فاتورة المورد آجلة")
        btn_save.clicked.connect(self.save_purchase)
        self.init_edit_mode(btn_save, "فاتورة المشتريات")

        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(box_head)
        lay.addWidget(box_tax)
        lay.addLayout(bottom, 1)
        enter_chain(self, [self.inv_no, self.desc, self.amount, self.vat],
                    self.save_purchase)
        lay.addWidget(self.edit_banner)
        srow = QtWidgets.QHBoxLayout()
        srow.addWidget(btn_save, 1)
        srow.addWidget(self.btn_cancel_edit)
        lay.addLayout(srow)
        self._on_kind()
        sa = QtWidgets.QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QtWidgets.QFrame.NoFrame)
        sa.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        sa.setWidget(w)
        return sa

    def _on_kind(self, *_):
        kind = self.kind.currentData()
        asset = kind == "asset"
        self.life.setVisible(asset)
        self.life_lbl.setVisible(asset)
        try:
            with db(readonly=True) as conn:
                accs = purchases.purchase_accounts(conn, kind)
        except Exception:
            accs = []
        cur = self.account.currentData()
        self.account.blockSignals(True)
        self.account.clear()
        for a in accs:
            self.account.addItem(f"{a['code']} — {a['name']}", a["code"])
        want = cur if self.account.findData(cur) >= 0 else \
            purchases.DEFAULT_ACCOUNT[kind]
        i = self.account.findData(want)
        self.account.setCurrentIndex(max(i, 0))
        self.account.blockSignals(False)
        self._recalc()

    def _on_supplier(self, *_):
        from services.fatoora import profile as pf
        sid = self.supplier.currentData()
        if sid is None:
            self.sup_vat.setText("—")
        else:
            with db(readonly=True) as conn:
                e = entities.get_entity(conn, sid)
            v = (e["vat_number"] or "").strip() if e else ""
            self.sup_vat.setText(
                f"✔ {v}" if pf.valid_vat(v) else
                f"⚠ {v or 'فارغ'} — غير صحيح: لا تُخصم ضريبة مدخلاته")
        self._recalc()

    def _auto_vat(self, *_):
        """المبلغ أو المعالجة أو طريقة الإدخال تغيّرت: الضريبة تُحسب من
        جديد. وتعديلها يدوياً بعد ذلك مقبول (فاتورةٌ بأصنافٍ مختلطة)."""
        tr = self.treat.currentData()
        no_vat = tr in purchases.NO_VAT
        _net, vat = purchases.split_amount(self.amount.value(),
                                           self.pmode.currentData(), tr)
        self.vat.blockSignals(True)
        self.vat.setValue(vat)
        self.vat.blockSignals(False)
        self.vat.setEnabled(not no_vat)
        self.pmode.setEnabled(not no_vat)
        self.amount_lbl.setText(
            "المبلغ شامل الضريبة:" if self.pmode.currentData() == "gross"
            and not no_vat else "المبلغ قبل الضريبة:")
        self._vat_touched = False
        self._recalc()

    def _on_vat_edit(self, *_):
        self._vat_touched = True
        self._recalc()

    def _values(self):
        """(الصافي، الضريبة) كما سيُرحَّلان."""
        tr = self.treat.currentData()
        if tr in purchases.NO_VAT:
            return round(self.amount.value(), 2), 0.0
        vat = round(self.vat.value(), 2)
        if self.pmode.currentData() == "gross":
            return round(self.amount.value() - vat, 2), vat
        return round(self.amount.value(), 2), vat

    def _recalc(self, *_):
        net, vat = self._values()
        tr = self.treat.currentData()
        claim = tr == "standard" and vat > 0
        cost = net if claim or not vat else round(net + vat, 2)
        total = round(net + vat, 2)
        self.c_net.set_value(_m(net), "يُحمَّل على الحساب" if claim or not vat
                             else f"+ ضريبة لا تُسترد = {_m(cost)}")
        self.c_vat.set_value(_m(vat if claim else 0),
                             "حساب 1900" if claim else
                             ("لا ضريبة" if not vat else "تُضاف للتكلفة"))
        self.c_total.set_value(_m(total))
        if total <= 0:
            self.preview.set_lines([])
            return
        acc = self.account.currentText() or "الحساب"
        sid = self.supplier.currentData()
        sup = (f"حساب المورد — {self.supplier.currentText()}"
               if sid is not None else "حساب المورد (اختره)")
        lines = [(acc, self.desc.text().strip() or "البيان", cost, 0)]
        if claim:
            lines.append(("1900 — ضريبة القيمة المضافة — المدخلات",
                          "ضريبة مدخلات", vat, 0))
        lines.append((sup, "مشتريات آجلة", 0, total))
        self.preview.set_lines(lines)

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
            net, vat = self._values()
            tr = self.treat.currentData()
            if tr == "standard" and vat and not self.inv_no.text().strip():
                raise ValueError("اكتب رقم فاتورة المورد — ضريبة المدخلات "
                                 "لا تُخصم إلا بفاتورةٍ ضريبية مرقّمة")
            args = (self.kind.currentData(), sid, self.desc.text(), net, vat,
                    dstr(self.p_date), self.user["username"])
            kw = {"supplier_invoice_no": self.inv_no.text(),
                  "tax_treatment": tr,
                  "account_code": self.account.currentData(),
                  "price_mode": self.pmode.currentData(),
                  "life_months": self.life.value()}
            with db() as conn:
                if self.is_editing:
                    res = editing.repost(
                        conn, self.editing_entry_id, self.user["username"],
                        purchases.create_purchase, *args, **kw)
                else:
                    res = purchases.create_purchase(conn, *args, **kw)
            was_edit = self.is_editing
            self.end_edit()
            self._clear()
            self.refresh()
            posted(self, f"تم ترحيل الفاتورة {res['purchase_no']} آجلة على "
                       f"المورد {res['supplier_name']} — الإجمالي "
                       f"{res['total']:,.2f} ريال"
                       + (f" (ضريبة مدخلات {res['claimed_vat']:,.2f})"
                          if res["claimed_vat"] else ""),
                   "purchases", res["id"], editing=was_edit)
        except Exception as e:
            err(self, e)

    def _clear(self):
        self.desc.clear()
        self.inv_no.clear()
        self.amount.setValue(0)
        self.vat.setValue(0)
        self.life.setValue(0)

    # ══════════════════════════ السجل الضريبي ══════════════════════════
    def _build_register_tab(self):
        w = QtWidgets.QWidget()
        today = QtCore.QDate.currentDate()
        self.r_from = date_edit()
        self.r_from.setDate(QtCore.QDate(today.year(), today.month(), 1))
        self.r_to = date_edit()
        btn = QtWidgets.QPushButton("عرض")
        btn.clicked.connect(self.refresh_register)
        top = QtWidgets.QHBoxLayout()
        for lbl, wd in (("من:", self.r_from), ("إلى:", self.r_to)):
            top.addWidget(QtWidgets.QLabel(lbl))
            top.addWidget(wd)
        top.addStretch(1)
        top.addWidget(btn)
        self.r_n = Card("فواتير الموردين", "")
        self.r_net = Card("صافي المشتريات", "قبل الضريبة")
        self.r_other = Card("صفرية ومعفاة وغير مسجّل", "")
        self.r_vat = Card("ضريبة المدخلات القابلة للخصم",
                          "تنتقل للإقرار الضريبي", summary=True)
        cards = QtWidgets.QHBoxLayout()
        for c in (self.r_n, self.r_net, self.r_other, self.r_vat):
            cards.addWidget(c, 1)
        self.reg = make_table()
        self.reg.setColumnCount(len(REG_COLS))
        self.reg.setHorizontalHeaderLabels(REG_COLS)
        fit_columns(self.reg, [9, 8, 9, 14, 13, 9, 15, 8, 9, 8, 9])
        self._reg_rows = []
        lay = QtWidgets.QVBoxLayout(w)
        lay.addLayout(top)
        lay.addLayout(cards)
        lay.addWidget(self.reg, 1)
        return w

    def refresh_register(self):
        with db(readonly=True) as conn:
            rows, tot, by = purchases.vat_register(
                conn, dstr(self.r_from), dstr(self.r_to))
        self._reg_rows = rows
        t = self.reg
        t.setRowCount(len(rows))
        for r, p in enumerate(rows):
            tr = p["tax_treatment"] or "standard"
            vals = [p["purchase_no"], p["purchase_date"], p["supplier_name"],
                    p["supplier_vat"] or "—", p["supplier_invoice_no"] or "—",
                    p["description"], TREAT_SHORT.get(tr, tr),
                    _m(p["amount"]), _m(p["vat_amount"]), _m(p["total"])]
            for c, v in enumerate(vals, 1):
                t.setItem(r, c, num_item(v) if c >= 8 else text_item(v))
        for r in range(len(rows)):
            box = QtWidgets.QWidget()
            h = QtWidgets.QHBoxLayout(box)
            h.setContentsMargins(2, 0, 2, 0)
            h.setSpacing(3)
            for icon, tip, fn in (("👁", "معاينة وطباعة", self._preview_row),
                                  ("✎", "تعديل الفاتورة", self._edit_row)):
                b = QtWidgets.QToolButton()
                b.setObjectName("rowAct")
                b.setText(icon)
                b.setToolTip(tip)
                b.setCursor(QtCore.Qt.PointingHandCursor)
                b.clicked.connect(lambda _=False, i=r, f=fn: f(i))
                h.addWidget(b)
            h.addStretch(1)
            t.setCellWidget(r, 0, box)
        t.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
        t.verticalHeader().setDefaultSectionSize(row_height(t))
        fit_columns(t)
        other = sum(v["net"] for k, v in by.items()
                    if k in purchases.NO_VAT)
        self.r_n.set_value(str(tot["n"]), _m(tot["total"]) + " ريال")
        self.r_net.set_value(_m(tot["net"]))
        self.r_other.set_value(_m(other))
        self.r_vat.set_value(_m(tot["claimed"]))

    def _preview_row(self, r):
        if 0 <= r < len(self._reg_rows):
            try:
                from services import print_manager
                print_manager.preview_document(self, "purchases",
                                               self._reg_rows[r]["id"])
            except Exception as e:
                err(self, e)

    def _edit_row(self, r):
        if 0 <= r < len(self._reg_rows):
            self.tabs.setCurrentIndex(0)
            self.load_document(self._reg_rows[r]["id"])

    # ══════════════════════════ الأصول والإهلاك ══════════════════════════
    def _build_assets_tab(self):
        """شاشة الأصول والإهلاك كاملةً — تُبنى عند أول فتحٍ لتبويبها،
        فلا تتأخّر شاشة المشتريات من أجل تبويبٍ قد لا يُفتح."""
        w = QtWidgets.QWidget()
        QtWidgets.QVBoxLayout(w).setContentsMargins(0, 0, 0, 0)
        self._assets_holder = w
        self._assets_screen = None
        return w

    def _on_tab(self, index):
        if index == 1:
            self.refresh_register()
        elif index == 2:
            self._ensure_assets(index)

    def _ensure_assets(self, index=2):
        """يبني تبويب الأصول عند أول فتحٍ له."""
        if index != 2 or self._assets_screen is not None:
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
                acc = conn.execute("SELECT code FROM accounts WHERE id=?",
                                   (p["account_id"],)).fetchone() \
                    if "account_id" in p.keys() and p["account_id"] else None
                life = 0
                if p["asset_id"]:
                    a = conn.execute("SELECT life_months FROM fixed_assets"
                                     " WHERE id=?", (p["asset_id"],)
                                     ).fetchone()
                    life = int(a["life_months"] or 0) if a else 0
            self.refresh()
            self.tabs.setCurrentIndex(0)
            keys = p.keys()
            i = self.kind.findData(p["kind"])
            if i >= 0:
                self.kind.setCurrentIndex(i)
            if acc is not None:
                i = self.account.findData(acc["code"])
                if i >= 0:
                    self.account.setCurrentIndex(i)
            i = self.supplier.findData(p["supplier_id"])
            if i >= 0:
                self.supplier.setCurrentIndex(i)
            self.desc.setText(p["description"] or "")
            self.inv_no.setText((p["supplier_invoice_no"] or "")
                                if "supplier_invoice_no" in keys else "")
            tr = (p["tax_treatment"] if "tax_treatment" in keys else "") \
                or "standard"
            pm = (p["price_mode"] if "price_mode" in keys else "") or "net"
            self.treat.setCurrentIndex(max(self.treat.findData(tr), 0))
            self.pmode.setCurrentIndex(max(self.pmode.findData(pm), 0))
            self.amount.setValue((p["total"] if pm == "gross"
                                  else p["amount"]) or 0)
            self.vat.setValue(p["vat_amount"] or 0)      # كما رُحِّلت
            self.life.setValue(life)
            self._recalc()
            self.begin_edit(eid, source_id)
        except Exception as e:
            err(self, e)

    def refresh(self):
        with db() as conn:
            reload_combo(self.supplier,
                         entities.list_entities(conn, ("supplier",)),
                         lambda r: r["name"])
        if getattr(self, "tabs", None) is not None \
                and self.tabs.currentIndex() == 1:
            self.refresh_register()
        # تبويب الأصول يُحدِّث نفسه — ولا يُبنى قبل أن يُفتح
        scr = getattr(self, "_assets_screen", None)
        fn = getattr(scr, "refresh", None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass
