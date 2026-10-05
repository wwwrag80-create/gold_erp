# -*- coding: utf-8 -*-
"""المشتريات — آجلةٌ على حساب المورد، أو نقداً من الصندوق، أو بتحويلٍ
من البنك — مرتّبةً كما تطلبها الضريبة والمحاسبة:

  • فاتورة المورد: رقمها وتاريخها والمورد برقمه الضريبي، والحساب الذي
    تُحمَّل عليه، والمعالجة الضريبية، والمبلغ صافياً أو شاملاً —
    وطريقة الدفع، ونوع ورقة المورد (ضريبية / مبسطة).
  • سجل المشتريات الضريبية: لكل فاتورةٍ رقمها لدى المورد ورقمه الضريبي
    وصافيها وضريبتها، وإجمالي ضريبة المدخلات القابلة للخصم للفترة.
  • الأصول الثابتة والإهلاك.
"""
from PyQt5 import QtCore, QtWidgets

import config
from database.database import db
from models import editing, entities, purchases
from ui.widgets.common import (Card, date_edit, dstr, enter_chain, err,
                               make_table, mspin, num_item, posted,
                               reload_combo, row_action_buttons, row_height,
                               search_combo, tab_widget, text_item,
                               title_label)
from ui.widgets.table_fit import fit_columns

REG_COLS = ["", "الرقم", "التاريخ", "المورد", "الرقم الضريبي للمورد",
            "فاتورة المورد", "نوعها", "الدفع", "المعالجة", "الخصم",
            "الصافي", "الضريبة", "الإجمالي"]
TYPE_SHORT = {"standard": "ضريبية", "simplified": "مبسطة"}
PAY_SHORT = {"credit": "آجل", "cash": "نقداً", "bank": "بنكي"}
TREAT_SHORT = {"standard": "خاضعة 15%", "blocked": "لا تُسترد",
               "zero": "صفرية", "exempt": "معفاة",
               "unregistered": "غير مسجّل"}


def _m(v):
    return f"{float(v or 0):,.2f}"


def _shrink(cb, chars=10):
    cb.setSizeAdjustPolicy(
        QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
    cb.setMinimumContentsLength(chars)
    cb.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                     QtWidgets.QSizePolicy.Fixed)


def _sub(t):
    lbl = QtWidgets.QLabel(t)
    lbl.setObjectName("cardSub")
    lbl.setAlignment(QtCore.Qt.AlignCenter)
    return lbl


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
        self.tabs = tab_widget()
        self.tabs.addTab(self._build_purchase_tab(), "فاتورة مورد")
        self.tabs.addTab(self._build_register_tab(),
                         "سجل المشتريات الضريبية")
        self.tabs.addTab(self._build_assets_tab(), "الأصول الثابتة والإهلاك")
        self.tabs.currentChanged.connect(self._on_tab)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("المشتريات والقيود الرأسمالية"))
        lay.addWidget(self.tabs)

    # ══════════════════════════ الفاتورة ══════════════════════════
    LINE_COLS = ["", "م", "الحساب", "العدد", "السعر", "المبلغ قبل الضريبة",
                 "الخصم", "الضريبة", "بعد الضريبة"]

    def _build_purchase_tab(self):
        w = QtWidgets.QWidget()
        self.p_lines = []          # أسطر الفاتورة: لكل سطرٍ حسابه
        # ① فاتورة المورد: من · رقمها · متى · ومعالجتها الضريبية
        self.supplier = search_combo("اكتب اسم المورد…")
        self.supplier.currentIndexChanged.connect(self._on_supplier)
        btn_new_sup = QtWidgets.QPushButton("+ مورد جديد")
        btn_new_sup.setObjectName("ghost")
        btn_new_sup.clicked.connect(self.new_supplier)
        self.sup_vat = QtWidgets.QLabel("—")
        # بلا لفّ: النصّ المُلتفّ يجعل الشاشة كلها «ارتفاعاً بحسب العرض»
        # فتحجز للجدول ارتفاعه المفضّل وتظهر شريط تمريرٍ بلا داعٍ
        self.sup_vat.setWordWrap(False)
        self.sup_vat.setMinimumWidth(0)
        self.sup_vat.setSizePolicy(QtWidgets.QSizePolicy.Ignored,
                                   QtWidgets.QSizePolicy.Preferred)
        self.inv_no = QtWidgets.QLineEdit()
        self.inv_no.setPlaceholderText("كما في ورقة المورد")
        self.p_date = date_edit()
        self.kind = QtWidgets.QComboBox()
        self.kind.addItem("مصروف تشغيلي", "expense")
        self.kind.addItem("أصل ثابت (مكينة/معدة)", "asset")
        self.kind.currentIndexChanged.connect(self._on_kind)
        self.treat = QtWidgets.QComboBox()
        for k, lbl in purchases.TAX_TREATMENTS:
            self.treat.addItem(lbl, k)
        self.treat.currentIndexChanged.connect(self._on_treat)
        self.desc = QtWidgets.QLineEdit()
        self.desc.setPlaceholderText("البيان (اسم الأصل إن كان أصلاً)")
        self.life = QtWidgets.QSpinBox()
        self.life.setRange(0, 600)
        self.life.setSuffix(" شهراً")
        self.life.setSpecialValueText("يُحدَّد لاحقاً")
        self.life_lbl = QtWidgets.QLabel("العمر الإنتاجي:")
        self.pay = QtWidgets.QComboBox()
        for k, lbl in purchases.PAY_MODES:
            self.pay.addItem(lbl, k)
        self.pay.currentIndexChanged.connect(self._recalc)
        self.inv_type = QtWidgets.QComboBox()
        for k, lbl in purchases.INVOICE_TYPES:
            self.inv_type.addItem(lbl, k)
        self.inv_type.setToolTip(
            "ضريبية: باسم المصنع ورقمه الضريبي · مبسطة: إيصالٌ بلا بيانات "
            "المشتري (محطة، مطعم، محل تجزئة)")

        # القوائم لا تأخذ عرض أطول خياراتها — وإلا جاوزت الشاشة نافذتها
        # ومدّت الواجهة خارجها لليسار
        for cb in (self.kind, self.treat, self.pay, self.inv_type):
            _shrink(cb)
        sup_row = QtWidgets.QHBoxLayout()
        sup_row.addWidget(self.supplier, 1)
        sup_row.addWidget(btn_new_sup)
        box_head = QtWidgets.QGroupBox("① فاتورة المورد")
        g = QtWidgets.QGridLayout(box_head)
        cells = (
            (0, 0, "المورد:", sup_row), (0, 2, "الرقم الضريبي:",
                                         self.sup_vat),
            (0, 4, "التاريخ:", self.p_date),
            (1, 0, "رقم فاتورة المورد:", self.inv_no),
            (1, 2, "نوع الفاتورة:", self.inv_type),
            (1, 4, "طريقة الدفع:", self.pay),
            (2, 0, "نوع الشراء:", self.kind),
            (2, 2, "المعالجة الضريبية:", self.treat),
            (2, 4, self.life_lbl, self.life))
        for r, c, lbl, wd in cells:
            g.addWidget(lbl if isinstance(lbl, QtWidgets.QWidget)
                        else QtWidgets.QLabel(lbl), r, c)
            if isinstance(wd, QtWidgets.QLayout):
                g.addLayout(wd, r, c + 1)
            else:
                g.addWidget(wd, r, c + 1)
        g.addWidget(QtWidgets.QLabel("البيان:"), 3, 0)
        g.addWidget(self.desc, 3, 1, 1, 5)
        g.setColumnStretch(1, 3)
        g.setColumnStretch(3, 3)
        g.setColumnStretch(5, 2)

        # ② المبالغ والضريبة — سطر إدخالٍ بترتيب ورقة المورد: الحساب ثم
        # العدد ثم السعر ثم المبلغ قبل الضريبة ثم الخصم ثم الضريبة ثم
        # بعد الضريبة. وEnter أو «+ إضافة سطر» يُنزله في الجدول تحته —
        # فاتورةٌ واحدة على أكثر من حساب.
        self.account = QtWidgets.QComboBox()
        _shrink(self.account, 14)
        self.l_qty = mspin()
        self.l_qty.setValue(1)
        self.l_price = mspin()
        self.l_gross = QtWidgets.QLineEdit()
        self.l_gross.setReadOnly(True)
        self.discount = mspin()
        self.vat = mspin()
        self.l_total = QtWidgets.QLineEdit()
        self.l_total.setReadOnly(True)
        for sp in (self.l_qty, self.l_price, self.discount):
            sp.valueChanged.connect(self._line_auto_vat)
        # خانات الأرقام لا تحجز عرض أكبر رقمٍ ممكن (مليار) — فيتّسع
        # السطر في النافذة كلها بلا تمرير
        for wd in (self.l_qty, self.l_price, self.l_gross, self.discount,
                   self.vat, self.l_total):
            wd.setMinimumWidth(64)
        self.vat.valueChanged.connect(self._line_vat_typed)
        self._vat_manual = False
        self.btn_line = QtWidgets.QPushButton("+ إضافة سطر")
        self.btn_line.clicked.connect(self.add_line)
        box_amt = QtWidgets.QGroupBox("② المبالغ والضريبة")
        a = QtWidgets.QGridLayout(box_amt)
        a.setHorizontalSpacing(8)
        for c, (lbl, wd, st) in enumerate((
                ("الحساب", self.account, 5),
                ("العدد", self.l_qty, 1),
                ("السعر", self.l_price, 2),
                ("المبلغ قبل الضريبة", self.l_gross, 2),
                ("الخصم", self.discount, 2),
                (f"الضريبة {config.VAT_RATE * 100:g}%", self.vat, 2),
                ("بعد الضريبة", self.l_total, 2))):
            a.addWidget(_sub(lbl), 0, c)
            a.addWidget(wd, 1, c)
            a.setColumnStretch(c, st)
        a.addWidget(self.btn_line, 1, 7)
        self.lines_tbl = make_table()
        self.lines_tbl.setColumnCount(len(self.LINE_COLS))
        self.lines_tbl.setHorizontalHeaderLabels(self.LINE_COLS)
        self.lines_tbl.setMinimumHeight(104)
        fit_columns(self.lines_tbl, [7, 4, 25, 7, 10, 12, 9, 11, 13])
        a.addWidget(self.lines_tbl, 2, 0, 1, 8)

        self.c_amount = Card("المبلغ", "قبل الخصم")
        self.c_disc = Card("الخصم", "")
        self.c_net = Card("الصافي الخاضع", "يُحمَّل على الحساب")
        self.c_vat = Card("ضريبة المدخلات", "تُخصم في الإقرار")
        self.c_total = Card("إجمالي الفاتورة", "", summary=True)
        cards = QtWidgets.QHBoxLayout()
        for c in (self.c_amount, self.c_disc, self.c_net, self.c_vat,
                  self.c_total):
            cards.addWidget(c, 1)

        btn_save = QtWidgets.QPushButton("✔ ترحيل فاتورة المورد")
        btn_save.clicked.connect(self.save_purchase)
        self.init_edit_mode(btn_save, "فاتورة المشتريات")

        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(box_head)
        lay.addWidget(box_amt, 1)
        lay.addLayout(cards)
        lay.addWidget(self.edit_banner)
        srow = QtWidgets.QHBoxLayout()
        srow.addWidget(btn_save, 1)
        srow.addWidget(self.btn_cancel_edit)
        lay.addLayout(srow)
        enter_chain(self, [self.inv_no, self.desc, self.account, self.l_qty,
                           self.l_price, self.discount, self.vat],
                    on_last=lambda: self.account if self.add_line()
                    else False)
        self._on_kind()
        self._line_auto_vat()
        self._render_lines()
        sa = QtWidgets.QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QtWidgets.QFrame.NoFrame)
        sa.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        sa.setWidget(w)
        return sa

    def _pmode(self):
        return "net"

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
        for acc in accs:
            self.account.addItem(f"{acc['code']} — {acc['name']}",
                                 acc["code"])
        want = cur if self.account.findData(cur) >= 0 else \
            purchases.DEFAULT_ACCOUNT[kind]
        i = self.account.findData(want)
        self.account.setCurrentIndex(max(i, 0))
        self.account.blockSignals(False)
        # أسطرٌ على حساباتٍ لا تصلح لنوع الشراء الجديد لا تبقى
        ok = {acc["code"] for acc in accs}
        if any(li["account_code"] not in ok for li in self.p_lines):
            self.p_lines = [li for li in self.p_lines
                            if li["account_code"] in ok]
            self._render_lines()

    def _on_supplier(self, *_):
        from services.fatoora import profile as pf
        sid = self.supplier.currentData()
        if sid is None:
            self.sup_vat.setText("—")
            return
        with db(readonly=True) as conn:
            e = entities.get_entity(conn, sid)
        v = (e["vat_number"] or "").strip() if e else ""
        self.sup_vat.setText(
            f"✔ {v}" if pf.valid_vat(v) else
            f"⚠ {v or 'فارغ'} — غير صحيح: لا تُخصم ضريبة مدخلاته")
        self.sup_vat.setToolTip(self.sup_vat.text())

    # ── سطر الإدخال ──
    def _calc(self, qty, price, disc, vat=None):
        return purchases.compute_line(qty, price, disc,
                                      self.treat.currentData(), vat)

    def _line_auto_vat(self, *_):
        """العدد أو السعر أو الخصم تغيّر: الضريبة تُحسب من جديد ما لم
        تُكتب يدوياً (سطرٌ بأصنافٍ مختلطة)."""
        no_vat = self.treat.currentData() in purchases.NO_VAT
        c = self._calc(self.l_qty.value(), self.l_price.value(),
                       self.discount.value(),
                       None if not self._vat_manual else self.vat.value())
        if not self._vat_manual or no_vat:
            self.vat.blockSignals(True)
            self.vat.setValue(max(c["vat"], 0))
            self.vat.blockSignals(False)
            self._vat_manual = False
        self.vat.setEnabled(not no_vat)
        self._line_show()

    def _line_vat_typed(self, *_):
        self._vat_manual = True
        self._line_show()

    def _line_show(self):
        c = self._calc(self.l_qty.value(), self.l_price.value(),
                       self.discount.value(), self.vat.value())
        self.l_gross.setText(_m(c["gross"]))
        self.l_total.setText(_m(c["total"]))
        # البطاقات تشمل السطر الجاري قبل إنزاله — فالإجمالي يُرى وهو يُكتب
        if hasattr(self, "c_total"):
            self._recalc()

    def _on_treat(self, *_):
        """المعالجة للفاتورة كلها: ضريبة كل سطرٍ تُحسب بها من جديد."""
        for li in self.p_lines:
            if self.treat.currentData() in purchases.NO_VAT:
                li["vat"], li["vat_manual"] = 0.0, False
            elif not li.get("vat_manual"):
                li["vat"] = self._calc(li["qty"], li["unit_price"],
                                       li["discount"])["vat"]
        self._vat_manual = False
        self._line_auto_vat()
        self._render_lines()

    def _clear_line(self):
        for sp, v in ((self.l_qty, 1), (self.l_price, 0),
                      (self.discount, 0)):
            sp.blockSignals(True)
            sp.setValue(v)
            sp.blockSignals(False)
        self._vat_manual = False
        self._line_auto_vat()

    def add_line(self):
        """ينزل سطر الإدخال في الجدول — ويبقى الحساب كما اختير."""
        code = self.account.currentData()
        if not code:
            err(self, "اختر الحساب")
            return False
        c = self._calc(self.l_qty.value(), self.l_price.value(),
                       self.discount.value(), self.vat.value())
        if c["qty"] <= 0 or c["net"] <= 0:
            if c["gross"] or self.discount.value():
                err(self, "المبلغ بعد الخصم يجب أن يكون أكبر من صفر")
            return False
        self.p_lines.append({
            "account_code": code, "account_label": self.account.currentText(),
            "qty": c["qty"], "unit_price": c["unit_price"],
            "discount": c["discount"], "vat": c["vat"],
            "vat_manual": self._vat_manual})
        self._clear_line()
        self._render_lines()
        return True

    def _edit_line(self, r):
        if not (0 <= r < len(self.p_lines)):
            return
        li = self.p_lines.pop(r)
        i = self.account.findData(li["account_code"])
        if i >= 0:
            self.account.setCurrentIndex(i)
        for sp, v in ((self.l_qty, li["qty"]), (self.l_price, li["unit_price"]),
                      (self.discount, li["discount"])):
            sp.blockSignals(True)
            sp.setValue(v)
            sp.blockSignals(False)
        self.vat.blockSignals(True)
        self.vat.setValue(li["vat"])
        self.vat.blockSignals(False)
        self._vat_manual = bool(li.get("vat_manual"))
        self._line_show()
        self._render_lines()
        self.l_price.setFocus()

    def _del_line(self, r):
        if 0 <= r < len(self.p_lines):
            del self.p_lines[r]
            self._render_lines()

    def _render_lines(self):
        t = self.lines_tbl
        # أزرار الصفوف المحذوفة تُرفع صراحةً — وإلا بقي زرٌّ يتيم مرسوماً
        # في جدولٍ فارغ
        for r in range(t.rowCount()):
            t.removeCellWidget(r, 0)
        t.setRowCount(len(self.p_lines))
        for r, li in enumerate(self.p_lines):
            c = self._calc(li["qty"], li["unit_price"], li["discount"],
                           li["vat"])
            vals = [str(r + 1), li["account_label"], f"{c['qty']:g}",
                    _m(c["unit_price"]), _m(c["gross"]), _m(c["discount"]),
                    _m(c["vat"]), _m(c["total"])]
            for col, v in enumerate(vals, 1):
                t.setItem(r, col, text_item(v) if col == 2 else num_item(v))
        row_action_buttons(t, len(self.p_lines), self._edit_line,
                           self._del_line, edit_tip="تعديل السطر",
                           del_tip="حذف السطر")
        t.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
        t.verticalHeader().setDefaultSectionSize(row_height(t) + 6)
        fit_columns(t)
        t.viewport().update()
        self._recalc()

    def _all_lines(self):
        """أسطر الفاتورة — ومعها سطر الإدخال إن كُتب ولم يُنزَل بعد."""
        out = [dict(li) for li in self.p_lines]
        if self.l_price.value() > 0 and self.account.currentData():
            out.append({"account_code": self.account.currentData(),
                        "account_label": self.account.currentText(),
                        "qty": self.l_qty.value(),
                        "unit_price": self.l_price.value(),
                        "discount": self.discount.value(),
                        "vat": self.vat.value()})
        return out

    def _values(self):
        """(الصافي الخاضع، الضريبة، الخصم قبل الضريبة) كما ستُرحَّل."""
        net = vat = disc = 0.0
        for li in self._all_lines():
            c = self._calc(li["qty"], li["unit_price"], li["discount"],
                           li["vat"])
            net += c["net"]
            vat += c["vat"]
            disc += c["discount"]
        return round(net, 2), round(vat, 2), round(disc, 2)

    def _recalc(self, *_):
        net, vat, disc = self._values()
        tr = self.treat.currentData()
        claim = tr == "standard" and vat > 0
        self.c_amount.set_value(_m(net + disc), "قبل الخصم والضريبة")
        self.c_disc.set_value(_m(disc), "قبل الضريبة" if disc else "لا خصم")
        self.c_net.set_value(_m(net), "يُحمَّل على الحساب" if claim or not vat
                             else f"+ ضريبة لا تُسترد = {_m(net + vat)}")
        self.c_vat.set_value(_m(vat if claim else 0),
                             "تُخصم في الإقرار" if claim else
                             ("لا ضريبة" if not vat else "تُضاف للتكلفة"))
        self.c_total.set_value(_m(net + vat), {
            "credit": "آجل — على حساب المورد، يُسدَّد بسند صرف",
            "cash": "نقداً — يُخصم من الصندوق",
            "bank": "بنكي — يُخصم من البنك"}.get(self.pay.currentData(),
                                                 ""))

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
            lines = self._all_lines()
            if not lines:
                raise ValueError("أضف سطراً واحداً على الأقل: الحساب والعدد"
                                 " والسعر")
            net, vat, disc = self._values()
            if net <= 0:
                raise ValueError("المبلغ بعد الخصم يجب أن يكون أكبر من صفر")
            tr = self.treat.currentData()
            if tr == "standard" and vat and not self.inv_no.text().strip():
                raise ValueError("اكتب رقم فاتورة المورد — ضريبة المدخلات "
                                 "لا تُخصم إلا بفاتورةٍ ضريبية مرقّمة")
            args = (self.kind.currentData(), sid, self.desc.text(), net, vat,
                    dstr(self.p_date), self.user["username"])
            kw = {"supplier_invoice_no": self.inv_no.text(),
                  "tax_treatment": tr,
                  "account_code": lines[0]["account_code"],
                  "price_mode": "net",
                  "life_months": self.life.value(),
                  "discount": disc,
                  "pay_mode": self.pay.currentData(),
                  "invoice_type": self.inv_type.currentData(),
                  "lines": [{"account_code": li["account_code"],
                             "qty": li["qty"],
                             "unit_price": li["unit_price"],
                             "discount": li["discount"],
                             "vat": li["vat"]} for li in lines]}
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
            how = {"credit": "آجلة على", "cash": "نقداً من الصندوق —",
                   "bank": "بتحويل بنكي —"}[res["pay_mode"]]
            posted(self, f"تم ترحيل الفاتورة {res['purchase_no']} {how} "
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
        self.p_lines = []
        self._clear_line()
        self.life.setValue(0)
        self._render_lines()

    # ══════════════════════════ السجل الضريبي ══════════════════════════
    def _build_register_tab(self):
        w = QtWidgets.QWidget()
        today = QtCore.QDate.currentDate()
        self.r_from = date_edit()
        self.r_from.setDate(QtCore.QDate(today.year(), today.month(), 1))
        self.r_to = date_edit()
        btn = QtWidgets.QPushButton("عرض")
        btn.clicked.connect(self.refresh_register)
        btn_print = QtWidgets.QPushButton("🖨 طباعة السجل")
        btn_print.setObjectName("ghost")
        btn_print.clicked.connect(self.print_register)
        top = QtWidgets.QHBoxLayout()
        for lbl, wd in (("من:", self.r_from), ("إلى:", self.r_to)):
            top.addWidget(QtWidgets.QLabel(lbl))
            top.addWidget(wd)
        top.addStretch(1)
        top.addWidget(btn)
        top.addWidget(btn_print)
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
        fit_columns(self.reg, [8, 8, 9, 12, 12, 8, 6, 6, 8, 6, 8, 7, 8])
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
                    TYPE_SHORT.get(p["invoice_type"] or "standard", "—"),
                    PAY_SHORT.get(p["pay_mode"] or "credit", "—"),
                    TREAT_SHORT.get(tr, tr),
                    _m(p["discount"]), _m(p["amount"]), _m(p["vat_amount"]),
                    _m(p["total"])]
            for c, v in enumerate(vals, 1):
                t.setItem(r, c, num_item(v) if c >= 9 else text_item(v))
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

    def print_register(self):
        try:
            from services import print_manager
            print_manager.preview_document(
                self, "purchases_register", 0, date_from=dstr(self.r_from),
                date_to=dstr(self.r_to))
        except Exception as e:
            err(self, e)

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
                plines = purchases.lines_of(conn, source_id)
                life = 0
                if p["asset_id"]:
                    a = conn.execute("SELECT life_months FROM fixed_assets"
                                     " WHERE id=?", (p["asset_id"],)
                                     ).fetchone()
                    life = int(a["life_months"] or 0) if a else 0
            self.refresh()
            self.tabs.setCurrentIndex(0)
            keys = p.keys()
            for combo, col, dflt in ((self.pay, "pay_mode", "credit"),
                                     (self.inv_type, "invoice_type",
                                      "standard")):
                v = (p[col] if col in keys else "") or dflt
                combo.setCurrentIndex(max(combo.findData(v), 0))
            i = self.kind.findData(p["kind"])
            if i >= 0:
                self.kind.setCurrentIndex(i)
            i = self.supplier.findData(p["supplier_id"])
            if i >= 0:
                self.supplier.setCurrentIndex(i)
            self.desc.setText(p["description"] or "")
            self.inv_no.setText((p["supplier_invoice_no"] or "")
                                if "supplier_invoice_no" in keys else "")
            tr = (p["tax_treatment"] if "tax_treatment" in keys else "") \
                or "standard"
            self.treat.blockSignals(True)
            self.treat.setCurrentIndex(max(self.treat.findData(tr), 0))
            self.treat.blockSignals(False)
            # الأسطر كما رُحِّلت — وفاتورةٌ قديمة سطراً واحداً
            self.p_lines = []
            for li in plines:
                code = li["acc_code"] or purchases.DEFAULT_ACCOUNT[p["kind"]]
                ix = self.account.findData(code)
                self.p_lines.append({
                    "account_code": code,
                    "account_label": (self.account.itemText(ix) if ix >= 0
                                      else f"{code} — {li['acc_name'] or ''}"),
                    "qty": float(li["qty"] or 1),
                    "unit_price": float(li["unit_price"] or 0),
                    "discount": float(li["discount"] or 0),
                    "vat": float(li["vat"] or 0), "vat_manual": True})
            self._clear_line()
            self._render_lines()
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
