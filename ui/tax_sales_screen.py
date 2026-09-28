# -*- coding: utf-8 -*-
"""شاشة المبيعات الضريبية — فاتورةٌ باسم الشركة عن أطقمٍ أخذها المندوب.

الإدخال كشاشة «مبيعات/مرتجعات» تماماً: رقم الموديل · رقم التشغيل ·
الوزن · الأجر — وEnter يُنزل السطر في الجدول. والفرق كلّه في المحاسبة:

  • الأطقم بيعت للمندوب من قبل (ذهبها وأجورها في حسابه)، فلا يتحرّك
    هنا مخزونٌ ولا ذهب.
  • الفاتورة باسم الشركة ورقمها الضريبي، وتظهر في كشفها كاملةً بلا رصيد.
  • ولا يُضاف لحساب المندوب إلا الضريبة.

والتبويبات: الفاتورة · إشعار دائن (مرتجع) · إشعار مدين (زيادة) · السجل.
المحاسبة كلّها في `models.tax_sales`؛ هذه الشاشة إدخالٌ وعرض فقط.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

import config
from database.database import db
from models import entities, tax_sales
from services import karat_view as kv
from ui.widgets.common import (Card, confirm_post, date_edit, dstr,
                               enter_chain, err, make_table, mspin,
                               num_item, posted, reload_combo,
                               row_action_buttons, row_height,
                               search_combo, tab_widget, text_item,
                               title_label)
from ui.widgets.table_fit import fit_columns

PAY_SHORT = {"credit": "آجل", "cash": "نقداً", "bank": "بنك / شبكة"}
KIND_LABEL = {"invoice": "فاتورة ضريبية", "credit": "إشعار دائن",
              "debit": "إشعار مدين"}
CREDIT_REASONS = ("مرتجع أطقم من الشركة", "خصم لاحق على الفاتورة",
                  "خطأ في الوزن أو الأجر", "إلغاء جزئي للفاتورة")
DEBIT_REASONS = ("فرق أجر لم يُحتسب", "خطأ بالنقص في الفاتورة",
                 "خدمة إضافية على الأطقم")


def _m(v):
    return f"{float(v or 0):,.2f}"


def _w(v18):
    return f"{kv.g(v18):,.3f}"


def _vat(net):
    return round(float(net) * config.VAT_RATE, 2)


def _scroll(w):
    sa = QtWidgets.QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QtWidgets.QFrame.NoFrame)
    sa.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    sa.setWidget(w)
    return sa


def _sub(t):
    lbl = QtWidgets.QLabel(t)
    lbl.setObjectName("cardSub")
    lbl.setAlignment(QtCore.Qt.AlignCenter)
    return lbl


def _cards(*cards):
    row = QtWidgets.QHBoxLayout()
    for c in cards:
        row.addWidget(c, 1)
    return row


def _fix_rows(t, extra=0):
    t.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
    t.verticalHeader().setDefaultSectionSize(row_height(t) + extra)
    fit_columns(t)


class NewCustomerDialog(QtWidgets.QDialog):
    """عميلٌ جديد برقمه الضريبي — رقمٌ صحيح يجعل فاتورته «ضريبية» لا
    «مبسطة»."""

    def __init__(self, parent, username):
        super().__init__(parent)
        self.username = username
        self.customer_id = None
        self.setWindowTitle("عميل جديد")
        self.setMinimumWidth(460)
        self.name = QtWidgets.QLineEdit()
        self.phone = QtWidgets.QLineEdit()
        self.vat = QtWidgets.QLineEdit()
        self.vat.setPlaceholderText("15 رقماً يبدأ بـ3 وينتهي بـ3")
        self.address = QtWidgets.QLineEdit()
        form = QtWidgets.QFormLayout(self)
        form.addRow("اسم العميل / الشركة:", self.name)
        form.addRow("الجوال:", self.phone)
        form.addRow("الرقم الضريبي:", self.vat)
        form.addRow("العنوان:", self.address)
        btn = QtWidgets.QPushButton("حفظ")
        btn.clicked.connect(self.save)
        form.addRow(btn)

    def save(self):
        from services.fatoora import profile as pf
        try:
            if not self.name.text().strip():
                raise ValueError("أدخل الاسم")
            vat = self.vat.text().strip()
            if vat and not pf.valid_vat(vat):
                raise ValueError("الرقم الضريبي غير صحيح: 15 رقماً يبدأ "
                                 "بـ3 وينتهي بـ3 (أو اتركه فارغاً)")
            with db() as conn:
                self.customer_id = entities.add_entity(
                    conn, self.name.text().strip(), "customer",
                    self.phone.text().strip(), vat, self.username,
                    address=self.address.text().strip())
            self.accept()
        except Exception as e:
            err(self, e)


class RepItemsDialog(QtWidgets.QDialog):
    """أطقم المندوب التي لم تُفوتر ضريبياً — يُحدَّد منها ما يُضاف."""
    COLS = ["", "رقم الموديل", "رقم التشغيل", "الوزن المقيد", "الأجر/جم",
            "الأجور", "فاتورة البيع", "تاريخها"]

    def __init__(self, parent, rep_name, items):
        super().__init__(parent)
        self.setWindowTitle(f"أطقم المندوب {rep_name}")
        self.resize(900, 520)
        self.items = items
        self.t = make_table()
        self.t.setColumnCount(len(self.COLS))
        self.t.setHorizontalHeaderLabels(self.COLS)
        self.t.setRowCount(len(items))
        for r, it in enumerate(items):
            chk = QtWidgets.QTableWidgetItem()
            chk.setFlags(QtCore.Qt.ItemIsUserCheckable
                         | QtCore.Qt.ItemIsEnabled)
            chk.setCheckState(QtCore.Qt.Unchecked)
            self.t.setItem(r, 0, chk)
            vals = [it["model_no"] or "—", it["wo_no"], _w(it["weight"]),
                    _m(kv.rate(it["wage_per_gram"])), _m(it["wages"]),
                    it["invoice_no"], it["invoice_date"]]
            for c, v in enumerate(vals, 1):
                self.t.setItem(r, c, num_item(v) if c in (3, 4, 5)
                               else text_item(v))
        _fix_rows(self.t)
        fit_columns(self.t, [5, 14, 14, 13, 11, 12, 14, 12])
        self.t.cellDoubleClicked.connect(self._toggle)
        b_all = QtWidgets.QPushButton("تحديد الكل")
        b_all.setObjectName("ghost")
        b_all.clicked.connect(self._all)
        b_ok = QtWidgets.QPushButton("✔ إضافة المحدد للفاتورة")
        b_ok.clicked.connect(self.accept)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(b_all)
        row.addStretch(1)
        row.addWidget(b_ok)
        lay = QtWidgets.QVBoxLayout(self)
        if not items:
            lay.addWidget(QtWidgets.QLabel(
                "لا أطقم للمندوب بلا فاتورةٍ ضريبية — بِعها له أولاً من "
                "شاشة «مبيعات/مرتجعات»."))
        lay.addWidget(self.t, 1)
        lay.addLayout(row)

    def _toggle(self, r, _c=0):
        it = self.t.item(r, 0)
        it.setCheckState(QtCore.Qt.Unchecked if it.checkState()
                         else QtCore.Qt.Checked)

    def _all(self):
        for r in range(self.t.rowCount()):
            self.t.item(r, 0).setCheckState(QtCore.Qt.Checked)

    def selected(self):
        return [self.items[r] for r in range(self.t.rowCount())
                if self.t.item(r, 0).checkState()]


class TaxSalesScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.items = []            # أسطر الفاتورة: سطر بيع + أجر الجرام (18)
        self._found = None         # الطقم المستدعى في سطر الإدخال
        self._cn_rows = []
        self._cn_spins = []
        self._reg_rows = []
        self.tabs = tab_widget()
        self.tabs.addTab(_scroll(self._build_invoice_tab()),
                         "فاتورة ضريبية")
        self.tabs.addTab(_scroll(self._build_credit_tab()),
                         "إشعار دائن (مرتجع)")
        self.tabs.addTab(_scroll(self._build_debit_tab()),
                         "إشعار مدين (زيادة)")
        self.tabs.addTab(self._build_register_tab(), "السجل")
        self.tabs.currentChanged.connect(lambda _i: self.refresh())
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("المبيعات الضريبية — فاتورة الشركة عبر "
                                  "المندوب"))
        lay.addWidget(self.tabs, 1)
        self.refresh()

    # ══════════════════════════ ① الأطراف ══════════════════════════
    def _build_invoice_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(self._build_header())
        lay.addWidget(self._build_entry())
        lay.addWidget(self._build_items(), 1)
        self.btn_post = QtWidgets.QPushButton("✔ ترحيل الفاتورة الضريبية")
        self.btn_post.clicked.connect(self.post_invoice)
        btn_clear = QtWidgets.QPushButton("تفريغ")
        btn_clear.setObjectName("ghost")
        btn_clear.clicked.connect(self.clear_invoice)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.btn_post, 1)
        row.addWidget(btn_clear)
        lay.addLayout(row)
        return w

    def _build_header(self):
        box = QtWidgets.QGroupBox("① الشركة والمندوب")
        self.company = search_combo("اكتب اسم الشركة (المشتري)…")
        self.company.currentIndexChanged.connect(self._on_company)
        btn_new = QtWidgets.QPushButton("+ عميل جديد")
        btn_new.setObjectName("ghost")
        btn_new.clicked.connect(self.new_customer)
        self.rep = search_combo("اكتب اسم المندوب…")
        self.rep.currentIndexChanged.connect(self._on_rep)
        self.btn_pick = QtWidgets.QPushButton("📋 أطقم المندوب")
        self.btn_pick.setObjectName("ghost")
        self.btn_pick.clicked.connect(self.pick_items)
        self.inv_date = date_edit()
        self.notes = QtWidgets.QLineEdit()
        self.notes.setPlaceholderText("البيان (اختياري) — يظهر على الفاتورة")
        self.buyer_lbl = QtWidgets.QLabel("—")
        self.buyer_lbl.setWordWrap(True)

        comp_row = QtWidgets.QHBoxLayout()
        comp_row.addWidget(self.company, 1)
        comp_row.addWidget(btn_new)
        rep_row = QtWidgets.QHBoxLayout()
        rep_row.addWidget(self.rep, 1)
        rep_row.addWidget(self.btn_pick)
        g = QtWidgets.QGridLayout(box)
        g.addWidget(QtWidgets.QLabel("الشركة (المشتري):"), 0, 0)
        g.addLayout(comp_row, 0, 1)
        g.addWidget(QtWidgets.QLabel("نوع الفاتورة:"), 0, 2)
        g.addWidget(self.buyer_lbl, 0, 3)
        g.addWidget(QtWidgets.QLabel("المندوب (البائع):"), 1, 0)
        g.addLayout(rep_row, 1, 1)
        g.addWidget(QtWidgets.QLabel("التاريخ:"), 1, 2)
        g.addWidget(self.inv_date, 1, 3)
        g.addWidget(QtWidgets.QLabel("البيان:"), 2, 0)
        g.addWidget(self.notes, 2, 1, 1, 3)
        g.setColumnStretch(1, 3)
        g.setColumnStretch(3, 2)
        return box

    # ══════════════════════════ ② سطر الإدخال ══════════════════════════
    def _build_entry(self):
        box = QtWidgets.QGroupBox("② إدخال الطقم")
        self.l_model = QtWidgets.QLineEdit()
        self.l_model.setReadOnly(True)
        self.l_model.setPlaceholderText("يُملأ تلقائياً")
        self.l_wo = QtWidgets.QLineEdit()
        self.l_wo.setPlaceholderText("امسح الباركود أو اكتب رقم التشغيل")
        self.l_wo.editingFinished.connect(self._wo_lookup)
        self.l_weight = QtWidgets.QLineEdit()
        self.l_weight.setReadOnly(True)
        self.l_wage = mspin()
        self.l_wage.valueChanged.connect(self._line_wages)
        self.l_wages = QtWidgets.QLineEdit()
        self.l_wages.setReadOnly(True)
        self.btn_add = QtWidgets.QPushButton("+ إضافة سطر")
        self.btn_add.clicked.connect(self.add_item)
        fields = [("رقم الموديل", self.l_model, 2),
                  ("رقم التشغيل", self.l_wo, 3),
                  (f"الوزن المقيد ({kv.unit()})", self.l_weight, 2),
                  ("الأجر/جم", self.l_wage, 2),
                  ("الأجور", self.l_wages, 2)]
        g = QtWidgets.QGridLayout(box)
        g.setHorizontalSpacing(6)
        for c, (label, wd, st) in enumerate(fields):
            wd.setMinimumWidth(96)
            g.addWidget(_sub(label), 0, c)
            g.addWidget(wd, 1, c)
            g.setColumnStretch(c, st)
        g.addWidget(self.btn_add, 1, len(fields))
        enter_chain(self, [self.l_wo, self.l_wage],
                    on_last=lambda: self.l_wo if self.add_item() else False,
                    require={self.l_wo: lambda: bool(
                        self.l_wo.text().strip())})
        return box

    # ══════════════════════════ ③ البنود ══════════════════════════
    ITEM_COLS = ["", "م", "رقم الموديل", "رقم التشغيل", "الوزن المقيد",
                 "الأجر/جم", "الأجور", "الضريبة 15%", "الإجمالي",
                 "فاتورة البيع"]

    def _build_items(self):
        box = QtWidgets.QGroupBox("③ بنود الفاتورة")
        self.items_tbl = make_table()
        self.items_tbl.setColumnCount(len(self.ITEM_COLS))
        self.items_tbl.setHorizontalHeaderLabels(self.ITEM_COLS)
        self.items_tbl.setMinimumHeight(240)
        fit_columns(self.items_tbl, [8, 4, 12, 12, 11, 9, 11, 10, 11, 12])
        self.p_weight = Card("إجمالي الوزن المقيد", kv.unit())
        self.p_wages = Card("إجمالي الأجور", "قبل الضريبة")
        self.p_vat = Card(f"الضريبة {config.VAT_RATE * 100:g}%",
                          "تُقيَّد على حساب المندوب", summary=True)
        self.p_total = Card("إجمالي الفاتورة", "في كشف الشركة بلا رصيد")
        v = QtWidgets.QVBoxLayout(box)
        v.addWidget(self.items_tbl, 1)
        v.addLayout(_cards(self.p_weight, self.p_wages, self.p_vat,
                           self.p_total))
        self._render_items()
        return box

    # ── الأطراف ──
    def new_customer(self):
        dlg = NewCustomerDialog(self, self.user["username"])
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self._reload_parties()
            i = self.company.findData(dlg.customer_id)
            if i >= 0:
                self.company.setCurrentIndex(i)

    def _on_company(self, *_):
        from services.fatoora import ledger
        from services.fatoora import profile as pf
        cid = self.company.currentData()
        if cid is None:
            self.buyer_lbl.setText("—")
            return
        try:
            with db(readonly=True) as conn:
                b = pf.buyer(conn, cid) or {}
                live = ledger.enabled(conn)
            if pf.buyer_is_b2b(b):
                txt = f"✔ فاتورة ضريبية — الرقم الضريبي {b['vat']}"
                miss = pf.buyer_problems(b)
                if live and miss:
                    txt += ("\n⚠ أكمل عنوانه من «الربط مع الهيئة ← "
                            "المشترون»: " + "، ".join(miss))
            else:
                txt = "⚠ بلا رقم ضريبي — تصدر «فاتورة ضريبية مبسطة»"
            self.buyer_lbl.setText(txt)
        except Exception as e:                       # noqa: BLE001
            self.buyer_lbl.setText(str(e))

    def _on_rep(self, *_):
        # أطقم مندوبٍ آخر لا تبقى في فاتورةٍ تغيّر مندوبها
        if self.items:
            self.items = []
            self._render_items()
        self._clear_entry()

    # ── سطر الإدخال ──
    def _clear_entry(self):
        self._found = None
        for f in (self.l_model, self.l_wo, self.l_weight, self.l_wages):
            f.clear()
        self.l_wage.blockSignals(True)
        self.l_wage.setValue(0)
        self.l_wage.blockSignals(False)

    def _wo_lookup(self):
        no = self.l_wo.text().strip()
        if not no or (self._found and self._found["wo_no"] == no):
            return
        rid = self.rep.currentData()
        self._found = None
        self.l_model.clear()
        self.l_weight.clear()
        self.l_wages.clear()
        if rid is None:
            err(self, "اختر المندوب أولاً — الأطقم تُستدعى من مبيعاته")
            return
        try:
            with db(readonly=True) as conn:
                it = tax_sales.find_rep_item(
                    conn, rid, no, exclude={x["item_id"] for x in self.items})
        except ValueError as e:
            err(self, e)
            self.l_wo.selectAll()
            return
        self._found = it
        self.l_model.setText(it["model_no"] or "—")
        self.l_weight.setText(_w(it["weight"]))
        self.l_wage.setValue(kv.rate(it["wage_per_gram"]))
        self._line_wages()

    def _line_wages(self, *_):
        if not self._found:
            self.l_wages.clear()
            return
        wages = kv.g(self._found["weight"]) * self.l_wage.value()
        self.l_wages.setText(_m(wages))

    def add_item(self):
        if self._found is None:
            self._wo_lookup()
        if self._found is None:
            return False
        it = dict(self._found)
        it["rate18"] = kv.rate_store(self.l_wage.value())
        self.items.append(it)
        self._clear_entry()
        self._render_items()
        return True

    def pick_items(self):
        rid = self.rep.currentData()
        if rid is None:
            err(self, "اختر المندوب أولاً")
            return
        with db(readonly=True) as conn:
            have = {x["item_id"] for x in self.items}
            avail = [x for x in tax_sales.rep_items(conn, rid)
                     if x["item_id"] not in have]
        dlg = RepItemsDialog(self, self.rep.currentText(), avail)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            for it in dlg.selected():
                it = dict(it)
                it["rate18"] = float(it["wage_per_gram"])
                self.items.append(it)
            self._render_items()

    def _del_item(self, r):
        if 0 <= r < len(self.items):
            del self.items[r]
            self._render_items()

    def _edit_item(self, r):
        """يعيد السطر لخانة الإدخال لتصحيح أجره ثم Enter يُعيده."""
        if 0 <= r < len(self.items):
            it = self.items.pop(r)
            self._found = it
            self.l_wo.setText(it["wo_no"])
            self.l_model.setText(it["model_no"] or "—")
            self.l_weight.setText(_w(it["weight"]))
            self.l_wage.setValue(kv.rate(it["rate18"]))
            self._line_wages()
            self._render_items()
            self.l_wage.setFocus()
            self.l_wage.selectAll()

    def _render_items(self):
        t = self.items_tbl
        t.setRowCount(len(self.items))
        tw = tn = 0.0
        for r, it in enumerate(self.items):
            net = round(float(it["weight"]) * float(it["rate18"]), 2)
            vat = _vat(net)
            tw += float(it["weight"])
            tn += net
            vals = [r + 1, it["model_no"] or "—", it["wo_no"],
                    _w(it["weight"]), _m(kv.rate(it["rate18"])), _m(net),
                    _m(vat), _m(net + vat), it["invoice_no"]]
            for c, v in enumerate(vals, 1):
                t.setItem(r, c, num_item(v) if 4 <= c <= 8
                          else text_item(v))
        row_action_buttons(t, len(self.items), self._edit_item,
                           self._del_item, edit_tip="تصحيح الأجر",
                           del_tip="حذف السطر")
        _fix_rows(t)
        tv = _vat(tn)          # ضريبة المستند على صافيه كلّه
        self.p_weight.set_value(_w(tw))
        self.p_wages.set_value(_m(tn))
        self.p_vat.set_value(_m(tv), "تُقيَّد على حساب المندوب" + (
            f" {self.rep.currentText()}" if self.rep.currentData()
            is not None else ""))
        self.p_total.set_value(_m(tn + tv))

    def clear_invoice(self):
        self.items = []
        self.notes.clear()
        self._clear_entry()
        self._render_items()

    def post_invoice(self):
        try:
            cid, rid = self.company.currentData(), self.rep.currentData()
            if cid is None:
                raise ValueError("اختر الشركة (المشتري)")
            if rid is None:
                raise ValueError("اختر المندوب")
            if self.l_wo.text().strip() and self._found:
                self.add_item()
            if not self.items:
                raise ValueError("أضف رقم تشغيلٍ واحداً على الأقل")
            if not confirm_post(
                    self, f"فاتورة ضريبية باسم «{self.company.currentText()}»"
                    f" — المندوب «{self.rep.currentText()}»\n"
                    f"الأجور {self.p_wages.value_lbl.text()} + الضريبة "
                    f"{self.p_vat.value_lbl.text()} = "
                    f"{self.p_total.value_lbl.text()} ريال\n"
                    f"على حساب المندوب: الضريبة {self.p_vat.value_lbl.text()}"
                    " فقط — والمخزون لا يتغيّر."):
                return
            with db() as conn:
                res = tax_sales.create_rep_invoice(
                    conn, cid, rid, dstr(self.inv_date),
                    [{"sale_item_id": x["item_id"],
                      "wage_per_gram": x["rate18"]} for x in self.items],
                    self.user["username"], self.notes.text())
            self.clear_invoice()
            posted(self, f"تم ترحيل الفاتورة الضريبية {res['doc_no']} باسم "
                         f"{res['customer_name']} — الإجمالي "
                         f"{_m(res['total'])} ريال\nعلى حساب المندوب "
                         f"{res['rep_name']}: الضريبة {_m(res['vat'])}",
                   "tax_sales", res["id"])
        except Exception as e:
            err(self, e)

    # ══════════════════════════ الإشعار الدائن ══════════════════════════
    CN_COLS = ["م", "البيان", "المباع", "المتبقي", "المرتجع", "صافي المرتجع"]

    def _build_credit_tab(self):
        w = QtWidgets.QWidget()
        self.cn_inv = search_combo("اكتب رقم الفاتورة أو اسم الشركة…")
        self.cn_inv.currentIndexChanged.connect(self._load_cn_lines)
        self.cn_date = date_edit()
        self.cn_reason = QtWidgets.QComboBox()
        self.cn_reason.setEditable(True)
        self.cn_reason.addItems(CREDIT_REASONS)
        self.cn_reason.setCurrentIndex(-1)
        self.cn_reason.lineEdit().setPlaceholderText("سبب الإشعار — إلزامي")
        self.cn_notes = QtWidgets.QLineEdit()
        self.cn_info = QtWidgets.QLabel("—")
        self.cn_info.setWordWrap(True)
        head = QtWidgets.QGroupBox("① الفاتورة الأصلية")
        g = QtWidgets.QGridLayout(head)
        g.addWidget(QtWidgets.QLabel("الفاتورة:"), 0, 0)
        g.addWidget(self.cn_inv, 0, 1)
        g.addWidget(QtWidgets.QLabel("تاريخ الإشعار:"), 0, 2)
        g.addWidget(self.cn_date, 0, 3)
        g.addWidget(QtWidgets.QLabel("السبب:"), 1, 0)
        g.addWidget(self.cn_reason, 1, 1)
        g.addWidget(QtWidgets.QLabel("ملاحظات:"), 1, 2)
        g.addWidget(self.cn_notes, 1, 3)
        g.addWidget(self.cn_info, 2, 0, 1, 4)
        g.setColumnStretch(1, 3)
        g.setColumnStretch(3, 2)
        self.cn_tbl = make_table()
        self.cn_tbl.setColumnCount(len(self.CN_COLS))
        self.cn_tbl.setHorizontalHeaderLabels(self.CN_COLS)
        self.cn_tbl.setMinimumHeight(220)
        fit_columns(self.cn_tbl, [5, 37, 13, 13, 17, 15])
        btn_all = QtWidgets.QPushButton("إرجاع المتبقي كاملاً")
        btn_all.setObjectName("ghost")
        btn_all.clicked.connect(self._cn_all)
        lines = QtWidgets.QGroupBox("② ما يُرتجع من كل بند")
        bl = QtWidgets.QVBoxLayout(lines)
        bl.addWidget(self.cn_tbl, 1)
        bl.addWidget(btn_all, 0, QtCore.Qt.AlignLeft)
        self.cn_c_net = Card("صافي المرتجع", "قبل الضريبة")
        self.cn_c_vat = Card("الضريبة المردودة", "", summary=True)
        self.cn_c_total = Card("إجمالي الإشعار", "")
        btn = QtWidgets.QPushButton("✔ ترحيل الإشعار الدائن")
        btn.clicked.connect(self.post_credit)
        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(head)
        lay.addWidget(lines, 1)
        lay.addLayout(_cards(self.cn_c_net, self.cn_c_vat, self.cn_c_total))
        lay.addWidget(btn)
        return w

    def _invoice_label(self, r):
        via = f" — عبر {r['rep_name']}" if r["rep_name"] else ""
        return (f"{r['doc_no']} — {r['customer_name']}{via} — "
                f"{_m(r['total'])} ريال — {r['doc_date']}")

    def _load_cn_lines(self, *_):
        sid = self.cn_inv.currentData()
        self._cn_rows, self._cn_spins = [], []
        self._cn_orig = None
        info = "—"
        if sid is not None:
            with db(readonly=True) as conn:
                s, _l = tax_sales.get(conn, sid)
                left = tax_sales.remaining(conn, sid)
            self._cn_orig = s
            self._cn_rows = list(left.values())
            if s and s["rep_id"]:
                info = (f"الشركة: {s['customer_name']} · المندوب: "
                        f"{s['rep_name']} — الضريبة المردودة تُخصم من حساب "
                        "المندوب، والإشعار يظهر في كشف الشركة بلا رصيد")
            elif s:
                info = (f"العميل: {s['customer_name']} · الدفع: "
                        f"{PAY_SHORT.get(s['pay_mode'], '')} — يُردّ بطريقة "
                        "دفع الفاتورة نفسها")
        self.cn_info.setText(info)
        t = self.cn_tbl
        t.setRowCount(len(self._cn_rows))
        for r, v in enumerate(self._cn_rows):
            li = v["line"]
            wmode = bool(li.get("wo_no"))
            f = _w if wmode else (lambda x: f"{x:g}")
            desc = (f"رقم التشغيل {li['wo_no']}"
                    + (f" · موديل {li['model_no']}" if li["model_no"]
                       else "") if wmode else li["description"])
            vals = [li["line_no"], desc, f(li["qty"]), f(v["qty_left"])]
            for c, val in enumerate(vals):
                t.setItem(r, c, text_item(val) if c == 1 else num_item(val))
            left_view = kv.g(v["qty_left"]) if wmode else v["qty_left"]
            sp = mspin(maximum=max(left_view, 0))
            sp.setDecimals(3 if wmode else 2)
            sp.setEnabled(v["qty_left"] > 1e-9)
            sp.valueChanged.connect(self._cn_recalc)
            t.setCellWidget(r, 4, sp)
            t.setItem(r, 5, num_item(""))
            self._cn_spins.append((sp, wmode))
        _fix_rows(t, 6)
        self._cn_recalc()

    def _cn_all(self):
        for v, (sp, wmode) in zip(self._cn_rows, self._cn_spins):
            sp.setValue(kv.g(v["qty_left"]) if wmode else v["qty_left"])

    def _cn_returns(self):
        out = []
        for v, (sp, wmode) in zip(self._cn_rows, self._cn_spins):
            if sp.value() > 0:
                q = sp.value()
                if wmode:
                    # كامل المتبقي يُؤخذ بقيمته المخزَّنة لا بعد تقريبه
                    q = (v["qty_left"] if abs(q - kv.g(v["qty_left"]))
                         < 0.0005 else kv.store(q))
                out.append({"src_line_id": v["line"]["id"], "qty": q})
        return out

    def _cn_recalc(self, *_):
        by_id = {x["src_line_id"]: x["qty"] for x in self._cn_returns()}
        net = 0.0
        for r, v in enumerate(self._cn_rows):
            li = v["line"]
            q = by_id.get(li["id"], 0)
            n = 0.0
            if q:
                disc = float(li["discount"]) * q / float(li["qty"])
                n = round(q * float(li["unit_price"]) - disc, 2)
            net += n
            it = self.cn_tbl.item(r, 5)
            if it:
                it.setText(_m(n) if q else "")
        rate = float(self._cn_orig["vat_rate"]) if self._cn_orig else \
            config.VAT_RATE
        vat = round(net * rate, 2)
        self.cn_c_net.set_value(_m(net))
        self.cn_c_vat.set_value(_m(vat), (
            f"تُخصم من حساب المندوب {self._cn_orig['rep_name']}"
            if self._cn_orig and self._cn_orig["rep_id"]
            else "تُخصم من ضريبة المخرجات"))
        self.cn_c_total.set_value(_m(net + vat))

    def post_credit(self):
        try:
            sid = self.cn_inv.currentData()
            if sid is None:
                raise ValueError("اختر الفاتورة الضريبية الأصلية")
            reason = self.cn_reason.currentText().strip()
            if not reason:
                raise ValueError("اكتب سبب الإشعار الدائن (إلزامي)")
            rets = self._cn_returns()
            if not rets:
                raise ValueError("اكتب المرتجع في بندٍ واحد على الأقل")
            if not confirm_post(
                    self, f"إشعار دائن على {self.cn_inv.currentText()}\n"
                          f"الإجمالي {self.cn_c_total.value_lbl.text()} ريال"
                          f" — السبب: {reason}"):
                return
            with db() as conn:
                res = tax_sales.create_credit_note(
                    conn, sid, dstr(self.cn_date), rets, reason,
                    self.user["username"], self.cn_notes.text())
            self.cn_reason.setCurrentIndex(-1)
            self.cn_reason.clearEditText()
            self.cn_notes.clear()
            self.refresh()
            posted(self, f"تم ترحيل الإشعار الدائن {res['doc_no']} على "
                         f"{res['ref_no']} — الإجمالي {_m(res['total'])} "
                         "ريال", "tax_sales", res["id"])
        except Exception as e:
            err(self, e)

    # ══════════════════════════ الإشعار المدين ══════════════════════════
    def _build_debit_tab(self):
        w = QtWidgets.QWidget()
        self.dn_inv = search_combo("اكتب رقم الفاتورة أو اسم الشركة…")
        self.dn_inv.currentIndexChanged.connect(self._dn_recalc)
        self.dn_date = date_edit()
        self.dn_amount = mspin()
        self.dn_amount.valueChanged.connect(self._dn_recalc)
        self.dn_desc = QtWidgets.QLineEdit()
        self.dn_desc.setPlaceholderText("بيان الزيادة (اختياري)")
        self.dn_reason = QtWidgets.QComboBox()
        self.dn_reason.setEditable(True)
        self.dn_reason.addItems(DEBIT_REASONS)
        self.dn_reason.setCurrentIndex(-1)
        self.dn_reason.lineEdit().setPlaceholderText("سبب الإشعار — إلزامي")
        self.dn_info = QtWidgets.QLabel("—")
        self.dn_info.setWordWrap(True)
        box = QtWidgets.QGroupBox("زيادةٌ على فاتورةٍ ضريبية سابقة")
        g = QtWidgets.QGridLayout(box)
        g.addWidget(QtWidgets.QLabel("الفاتورة:"), 0, 0)
        g.addWidget(self.dn_inv, 0, 1)
        g.addWidget(QtWidgets.QLabel("تاريخ الإشعار:"), 0, 2)
        g.addWidget(self.dn_date, 0, 3)
        g.addWidget(QtWidgets.QLabel("مبلغ الزيادة قبل الضريبة:"), 1, 0)
        g.addWidget(self.dn_amount, 1, 1)
        g.addWidget(QtWidgets.QLabel("السبب:"), 1, 2)
        g.addWidget(self.dn_reason, 1, 3)
        g.addWidget(QtWidgets.QLabel("البيان:"), 2, 0)
        g.addWidget(self.dn_desc, 2, 1, 1, 3)
        g.addWidget(self.dn_info, 3, 0, 1, 4)
        g.setColumnStretch(1, 3)
        g.setColumnStretch(3, 2)
        self.dn_c_net = Card("الزيادة", "قبل الضريبة")
        self.dn_c_vat = Card(f"الضريبة {config.VAT_RATE * 100:g}%", "")
        self.dn_c_total = Card("إجمالي الإشعار", "", summary=True)
        btn = QtWidgets.QPushButton("✔ ترحيل الإشعار المدين")
        btn.clicked.connect(self.post_debit)
        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(box)
        lay.addLayout(_cards(self.dn_c_net, self.dn_c_vat, self.dn_c_total))
        lay.addWidget(btn)
        lay.addStretch(1)
        return w

    def _dn_recalc(self, *_):
        net = round(self.dn_amount.value(), 2)
        vat = _vat(net)
        self.dn_c_net.set_value(_m(net))
        self.dn_c_vat.set_value(_m(vat))
        self.dn_c_total.set_value(_m(net + vat))
        sid = self.dn_inv.currentData()
        txt = "—"
        if sid is not None:
            with db(readonly=True) as conn:
                s, _l = tax_sales.get(conn, sid)
            if s and s["rep_id"]:
                txt = (f"الزيادة وضريبتها على حساب المندوب {s['rep_name']}"
                       f" — والإشعار يظهر في كشف {s['customer_name']} بلا "
                       "رصيد")
            elif s:
                txt = (f"على {s['customer_name']} — بطريقة دفع الفاتورة "
                       f"({PAY_SHORT.get(s['pay_mode'], '')})")
        self.dn_info.setText(txt)

    def post_debit(self):
        try:
            sid = self.dn_inv.currentData()
            if sid is None:
                raise ValueError("اختر الفاتورة الضريبية الأصلية")
            reason = self.dn_reason.currentText().strip()
            if not reason:
                raise ValueError("اكتب سبب الإشعار المدين (إلزامي)")
            if self.dn_amount.value() <= 0:
                raise ValueError("اكتب مبلغ الزيادة")
            if not confirm_post(
                    self, f"إشعار مدين على {self.dn_inv.currentText()}\n"
                          f"الإجمالي {self.dn_c_total.value_lbl.text()} ريال"
                          f" — السبب: {reason}"):
                return
            with db() as conn:
                res = tax_sales.create_debit_note(
                    conn, sid, dstr(self.dn_date), self.dn_amount.value(),
                    reason, self.user["username"], self.dn_desc.text())
            self.dn_amount.setValue(0)
            self.dn_desc.clear()
            self.dn_reason.setCurrentIndex(-1)
            self.dn_reason.clearEditText()
            self.refresh()
            posted(self, f"تم ترحيل الإشعار المدين {res['doc_no']} على "
                         f"{res['ref_no']} — الإجمالي {_m(res['total'])} "
                         "ريال", "tax_sales", res["id"])
        except Exception as e:
            err(self, e)

    # ══════════════════════════ السجل ══════════════════════════
    REG_COLS = ["", "الرقم", "النوع", "التاريخ", "الشركة (المشتري)",
                "المندوب", "الصافي", "الضريبة", "الإجمالي", "على الفاتورة"]

    def _build_register_tab(self):
        w = QtWidgets.QWidget()
        self.r_from = date_edit()
        today = QtCore.QDate.currentDate()
        self.r_from.setDate(QtCore.QDate(today.year(), today.month(), 1))
        self.r_to = date_edit()
        self.r_q = QtWidgets.QLineEdit()
        self.r_q.setPlaceholderText("رقم المستند أو اسم الشركة أو المندوب…")
        self.r_q.returnPressed.connect(self.refresh_register)
        self.r_kind = QtWidgets.QComboBox()
        self.r_kind.addItem("الكل", None)
        for k, lbl in KIND_LABEL.items():
            self.r_kind.addItem(lbl, k)
        btn = QtWidgets.QPushButton("عرض")
        btn.clicked.connect(self.refresh_register)
        top = QtWidgets.QHBoxLayout()
        for lbl, wd in (("من:", self.r_from), ("إلى:", self.r_to),
                        ("النوع:", self.r_kind)):
            top.addWidget(QtWidgets.QLabel(lbl))
            top.addWidget(wd)
        top.addWidget(self.r_q, 1)
        top.addWidget(btn)
        self.r_c_inv = Card("الفواتير", "")
        self.r_c_crd = Card("الإشعارات", "")
        self.r_c_net = Card("صافي المبيعات الضريبية", "بعد الإشعارات")
        self.r_c_vat = Card("صافي ضريبة المخرجات", "تنتقل للإقرار الضريبي",
                            summary=True)
        self.reg_tbl = make_table()
        self.reg_tbl.setColumnCount(len(self.REG_COLS))
        self.reg_tbl.setHorizontalHeaderLabels(self.REG_COLS)
        fit_columns(self.reg_tbl, [5, 10, 10, 9, 17, 13, 9, 9, 9, 9])
        self.reg_tbl.doubleClicked.connect(
            lambda ix: self._preview_row(ix.row()))
        lay = QtWidgets.QVBoxLayout(w)
        lay.addLayout(top)
        lay.addLayout(_cards(self.r_c_inv, self.r_c_crd, self.r_c_net,
                             self.r_c_vat))
        lay.addWidget(self.reg_tbl, 1)
        return w

    def refresh_register(self):
        d1, d2 = dstr(self.r_from), dstr(self.r_to)
        with db(readonly=True) as conn:
            rows = tax_sales.search(conn, self.r_q.text().strip(), d1, d2,
                                    self.r_kind.currentData())
            tot = tax_sales.totals(conn, d1, d2)
        self._reg_rows = rows
        t = self.reg_tbl
        t.setRowCount(len(rows))
        red = QtGui.QBrush(QtGui.QColor("#a4262c"))
        for r, s in enumerate(rows):
            credit = s["kind"] == "credit"
            vals = [s["doc_no"], KIND_LABEL.get(s["kind"], s["kind"]),
                    s["doc_date"], s["customer_name"], s["rep_name"] or "—",
                    _m(s["net"]), _m(s["vat"]), _m(s["total"]),
                    s["ref_no"] or "—"]
            for c, v in enumerate(vals, 1):
                it = num_item(v) if 6 <= c <= 8 else text_item(v)
                if credit and (6 <= c <= 8 or c == 2):
                    it.setForeground(red)
                t.setItem(r, c, it)
        row_action_buttons(t, len(rows), self._preview_row, None,
                           edit_tip="معاينة وطباعة")
        for r in range(len(rows)):
            box = t.cellWidget(r, 0)
            b = box.findChild(QtWidgets.QToolButton) if box else None
            if b:
                b.setText("👁")
        _fix_rows(t)
        inv, crd, dbt = tot["invoices"], tot["credits"], tot["debits"]
        self.r_c_inv.set_value(_m(inv["total"]), f"{inv['n']} فاتورة")
        self.r_c_crd.set_value(_m(crd["total"] - dbt["total"]),
                               f"{crd['n']} دائن · {dbt['n']} مدين")
        self.r_c_net.set_value(_m(tot["net"]))
        self.r_c_vat.set_value(_m(tot["vat"]))

    def _preview_row(self, r):
        if not (0 <= r < len(self._reg_rows)):
            return
        try:
            from services import print_manager
            print_manager.preview_document(self, "tax_sales",
                                           self._reg_rows[r]["id"])
        except Exception as e:
            err(self, e)

    # ══════════════════════════ التحديث ══════════════════════════
    def _reload_parties(self):
        with db(readonly=True) as conn:
            rows = entities.list_entities(conn, ("customer",))
        reload_combo(self.company, rows, lambda r: r["name"])
        self.rep.blockSignals(True)
        reload_combo(self.rep, rows, lambda r: r["name"])
        self.rep.blockSignals(False)

    def refresh(self):
        i = self.tabs.currentIndex() if hasattr(self, "tabs") else 0
        try:
            if i == 0:
                self._reload_parties()
            elif i == 1:
                with db(readonly=True) as conn:
                    rows = tax_sales.open_invoices(conn)
                reload_combo(self.cn_inv, rows, self._invoice_label)
                self._load_cn_lines()
            elif i == 2:
                with db(readonly=True) as conn:
                    rows = tax_sales.search(conn, kind="invoice", limit=2000)
                reload_combo(self.dn_inv, rows, self._invoice_label)
                self._dn_recalc()
            else:
                self.refresh_register()
        except Exception as e:                       # noqa: BLE001
            err(self, e)
