# -*- coding: utf-8 -*-
"""شاشة المبيعات الضريبية — فواتير بالريال **لا تمسّ الذهب ولا المخزون**.

ثلاثة تبويبات بترتيب العمل نفسه:
  • فاتورة ضريبية جديدة: العميل وطريقة الدفع، ثم سطر إدخالٍ (البيان ·
    الكمية · السعر · الخصم) يُضاف بـEnter، ثم البنود وإجمالياتها، ثم
    **معاينة القيد** قبل الترحيل.
  • إشعار دائن: اختر الفاتورة، واكتب كمية المرتجع لكل سطر (لا يتجاوز
    المتبقي)، والسبب إلزامي.
  • السجل: الفواتير والإشعارات لفترة، بإجماليات الصافي والضريبة.

المحاسبة كلّها في `models.tax_sales`؛ هذه الشاشة إدخالٌ وعرض فقط.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

import config
from database.database import db
from models import entities, tax_sales
from models.accounts import acc_id
from ui.widgets.common import (Card, confirm_post, date_edit, dstr,
                               enter_chain, err, make_table, mspin,
                               num_item, posted, reload_combo,
                               row_action_buttons, row_height,
                               search_combo, tab_widget, text_item,
                               title_label)
from ui.widgets.entry_preview import EntryPreview
from ui.widgets.table_fit import fit_columns

LINE_COLS = ["", "م", "البيان", "الكمية", "سعر الوحدة", "الخصم",
             "الصافي", "الضريبة", "الإجمالي"]
CN_COLS = ["م", "البيان", "الكمية المباعة", "المتبقي", "سعر الوحدة",
           "كمية المرتجع", "صافي المرتجع"]
REG_COLS = ["", "الرقم", "النوع", "التاريخ", "العميل", "الدفع", "الصافي",
            "الضريبة", "الإجمالي", "على الفاتورة"]
PAY_SHORT = {"credit": "آجل", "cash": "نقداً", "bank": "بنك / شبكة"}
REASONS = ("مرتجع بضاعة أو خدمة", "خصم لاحق على الفاتورة",
           "خطأ في السعر أو الكمية", "إلغاء جزئي للفاتورة")


def _m(v):
    return f"{float(v or 0):,.2f}"


def _acc_name(conn, code):
    r = conn.execute("SELECT name FROM accounts WHERE code=?",
                     (code,)).fetchone()
    return f"{code} — {r['name']}" if r else code


def _scroll(w):
    """التبويب داخل منطقة تمرير — على شاشةٍ صغيرة لا يُقصّ منه شيء."""
    sa = QtWidgets.QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QtWidgets.QFrame.NoFrame)
    sa.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    sa.setWidget(w)
    return sa


def _bottom(cards, preview):
    """الإجماليات عموداً بجانب معاينة القيد — لا فوقها."""
    col = QtWidgets.QVBoxLayout()
    for c in cards:
        col.addWidget(c)
    col.addStretch(1)
    box_je = QtWidgets.QGroupBox("القيد الذي سيُرحَّل")
    bl = QtWidgets.QVBoxLayout(box_je)
    bl.addWidget(preview)
    bl.addStretch(1)
    row = QtWidgets.QHBoxLayout()
    row.addLayout(col, 2)
    row.addWidget(box_je, 5)
    return row


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
        self.vat.setPlaceholderText("15 رقماً يبدأ بـ3 وينتهي بـ3 — "
                                    "فارغ للمستهلك")
        self.address = QtWidgets.QLineEdit()
        form = QtWidgets.QFormLayout(self)
        form.addRow("اسم العميل:", self.name)
        form.addRow("الجوال:", self.phone)
        form.addRow("الرقم الضريبي:", self.vat)
        form.addRow("العنوان:", self.address)
        btn = QtWidgets.QPushButton("حفظ العميل")
        btn.clicked.connect(self.save)
        form.addRow(btn)

    def save(self):
        from services.fatoora import profile as pf
        try:
            if not self.name.text().strip():
                raise ValueError("أدخل اسم العميل")
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


class TaxSalesScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.lines = []            # أسطر الفاتورة قيد الإعداد
        self._edit_row = None      # سطرٌ يُعدَّل من الجدول
        self._cn_rows = []         # أسطر الفاتورة المختارة للإشعار
        self.tabs = tab_widget()
        self.tabs.addTab(_scroll(self._build_invoice_tab()),
                         "فاتورة ضريبية جديدة")
        self.tabs.addTab(_scroll(self._build_credit_tab()), "إشعار دائن")
        self.tabs.addTab(self._build_register_tab(), "السجل")
        self.tabs.currentChanged.connect(lambda _i: self.refresh())
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("المبيعات الضريبية — بالريال، "
                                  "بلا أثرٍ على الذهب أو المخزون"))
        lay.addWidget(self.tabs, 1)
        self.refresh()

    # ══════════════════════════ الفاتورة ══════════════════════════
    def _build_invoice_tab(self):
        w = QtWidgets.QWidget()
        self.customer = search_combo("اكتب اسم العميل…")
        self.customer.currentIndexChanged.connect(self._on_customer)
        btn_new = QtWidgets.QPushButton("+ عميل جديد")
        btn_new.setObjectName("ghost")
        btn_new.clicked.connect(self.new_customer)
        self.pay_mode = QtWidgets.QComboBox()
        for key, label in tax_sales.PAY_MODES:
            self.pay_mode.addItem(label, key)
        self.pay_mode.currentIndexChanged.connect(self._recalc)
        self.inv_date = date_edit()
        self.notes = QtWidgets.QLineEdit()
        self.notes.setPlaceholderText("ملاحظة تظهر على الفاتورة (اختياري)")
        self.buyer_lbl = QtWidgets.QLabel("—")
        self.buyer_lbl.setWordWrap(True)

        cust_row = QtWidgets.QHBoxLayout()
        cust_row.addWidget(self.customer, 1)
        cust_row.addWidget(btn_new)
        head = QtWidgets.QGridLayout()
        head.addWidget(QtWidgets.QLabel("العميل:"), 0, 0)
        head.addLayout(cust_row, 0, 1)
        head.addWidget(QtWidgets.QLabel("التاريخ:"), 0, 2)
        head.addWidget(self.inv_date, 0, 3)
        head.addWidget(QtWidgets.QLabel("طريقة الدفع:"), 1, 0)
        head.addWidget(self.pay_mode, 1, 1)
        head.addWidget(QtWidgets.QLabel("نوع الفاتورة:"), 1, 2)
        head.addWidget(self.buyer_lbl, 1, 3)
        head.addWidget(QtWidgets.QLabel("ملاحظات:"), 2, 0)
        head.addWidget(self.notes, 2, 1, 1, 3)
        head.setColumnStretch(1, 3)
        head.setColumnStretch(3, 2)
        box_head = QtWidgets.QGroupBox("بيانات الفاتورة")
        box_head.setLayout(head)

        # سطر الإدخال — بترتيب أعمدة الفاتورة
        self.l_desc = QtWidgets.QLineEdit()
        self.l_desc.setPlaceholderText("البيان: خدمة، صنف، أتعاب…")
        self.l_qty = mspin()
        self.l_qty.setValue(1)
        self.l_price = mspin()
        self.l_disc = mspin()
        self.btn_add = QtWidgets.QPushButton("+ إضافة السطر")
        self.btn_add.clicked.connect(self.add_line)
        entry = QtWidgets.QGridLayout()
        for c, (lbl, wd) in enumerate((("البيان", self.l_desc),
                                       ("الكمية", self.l_qty),
                                       ("سعر الوحدة (قبل الضريبة)",
                                        self.l_price),
                                       ("الخصم (ريال)", self.l_disc))):
            entry.addWidget(QtWidgets.QLabel(lbl), 0, c)
            entry.addWidget(wd, 1, c)
        entry.addWidget(self.btn_add, 1, 4)
        entry.setColumnStretch(0, 4)
        for c in (1, 2, 3):
            entry.setColumnStretch(c, 1)
        enter_chain(self, [self.l_desc, self.l_qty, self.l_price,
                           self.l_disc], self.add_line)

        self.lines_tbl = make_table()
        self.lines_tbl.setColumnCount(len(LINE_COLS))
        self.lines_tbl.setHorizontalHeaderLabels(LINE_COLS)
        self.lines_tbl.setMinimumHeight(220)
        fit_columns(self.lines_tbl, [8, 4, 27, 8, 11, 9, 11, 10, 12])
        box_lines = QtWidgets.QGroupBox("بنود الفاتورة")
        bl = QtWidgets.QVBoxLayout(box_lines)
        bl.addLayout(entry)
        bl.addWidget(self.lines_tbl, 1)

        # الإجماليات ومعاينة القيد
        self.c_net = Card("الإجمالي الخاضع للضريبة", "غير شامل الضريبة")
        self.c_vat = Card(f"ضريبة القيمة المضافة "
                          f"{config.VAT_RATE * 100:g}%", "ضريبة مخرجات 2100")
        self.c_total = Card("الإجمالي شامل الضريبة", "", summary=True)
        self.preview = EntryPreview()

        btn_post = QtWidgets.QPushButton("✔ ترحيل الفاتورة الضريبية")
        btn_post.clicked.connect(self.post_invoice)
        btn_clear = QtWidgets.QPushButton("تفريغ")
        btn_clear.setObjectName("ghost")
        btn_clear.clicked.connect(self.clear_invoice)
        brow = QtWidgets.QHBoxLayout()
        brow.addWidget(btn_post, 1)
        brow.addWidget(btn_clear)

        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(box_head)
        lay.addWidget(box_lines, 1)
        lay.addLayout(_bottom((self.c_total, self.c_net, self.c_vat),
                              self.preview))
        lay.addLayout(brow)
        self._render_lines()
        return w

    def new_customer(self):
        dlg = NewCustomerDialog(self, self.user["username"])
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self._reload_customers()
            i = self.customer.findData(dlg.customer_id)
            if i >= 0:
                self.customer.setCurrentIndex(i)

    def _on_customer(self, *_):
        from services.fatoora import ledger
        from services.fatoora import profile as pf
        cid = self.customer.currentData()
        if cid is None:
            self.buyer_lbl.setText("—")
            self._recalc()
            return
        try:
            with db(readonly=True) as conn:
                b = pf.buyer(conn, cid) or {}
                live = ledger.enabled(conn)
            if pf.buyer_is_b2b(b):
                txt = f"فاتورة ضريبية — الرقم الضريبي للمشتري {b['vat']}"
                miss = pf.buyer_problems(b)
                if live and miss:
                    txt += ("\n⚠ أكمل عنوانه الوطني من «الربط مع هيئة "
                            "الزكاة والضريبة ← المشترون»: " + "، ".join(miss))
            else:
                txt = "فاتورة ضريبية مبسطة — عميلٌ بلا رقم ضريبي"
            self.buyer_lbl.setText(txt)
        except Exception as e:                       # noqa: BLE001
            self.buyer_lbl.setText(str(e))
        self._recalc()

    def _entry_line(self):
        return {"description": self.l_desc.text().strip(),
                "qty": self.l_qty.value(),
                "unit_price": self.l_price.value(),
                "discount": self.l_disc.value()}

    def add_line(self):
        li = self._entry_line()
        if not li["description"] and not li["unit_price"]:
            return self.l_desc
        try:
            tax_sales.compute([li])            # يتحقّق من السطر وحده
        except ValueError as e:
            err(self, str(e).replace("السطر 1: ", ""))
            return False
        if self._edit_row is not None and self._edit_row < len(self.lines):
            self.lines[self._edit_row] = li
        else:
            self.lines.append(li)
        self._edit_row = None
        self.btn_add.setText("+ إضافة السطر")
        self.l_desc.clear()
        self.l_qty.setValue(1)
        self.l_price.setValue(0)
        self.l_disc.setValue(0)
        self._render_lines()
        return self.l_desc

    def _edit_line(self, i):
        li = self.lines[i]
        self.l_desc.setText(li["description"])
        self.l_qty.setValue(li["qty"])
        self.l_price.setValue(li["unit_price"])
        self.l_disc.setValue(li["discount"])
        self._edit_row = i
        self.btn_add.setText("✔ حفظ تعديل السطر")
        self.l_desc.setFocus()

    def _del_line(self, i):
        if 0 <= i < len(self.lines):
            del self.lines[i]
        self._edit_row = None
        self.btn_add.setText("+ إضافة السطر")
        self._render_lines()

    def _render_lines(self):
        t = self.lines_tbl
        rows, _tot = ([], None)
        if self.lines:
            try:
                rows, _tot = tax_sales.compute(self.lines)
            except ValueError:
                rows = []
        t.setRowCount(len(rows))
        for r, li in enumerate(rows):
            vals = [li["line_no"], li["description"], f"{li['qty']:g}",
                    _m(li["unit_price"]), _m(li["discount"]), _m(li["net"]),
                    _m(li["vat"]), _m(li["total"])]
            for c, v in enumerate(vals, 1):
                t.setItem(r, c, text_item(v) if c == 2 else num_item(v))
        row_action_buttons(t, len(rows), self._edit_line, self._del_line)
        fit_columns(t)
        t.verticalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Fixed)
        t.verticalHeader().setDefaultSectionSize(row_height(t))
        self._recalc()

    def _recalc(self, *_):
        try:
            _rows, t = tax_sales.compute(self.lines) if self.lines else (
                [], {"net": 0, "vat": 0, "total": 0})
        except ValueError:
            t = {"net": 0, "vat": 0, "total": 0}
        self.c_net.set_value(_m(t["net"]))
        self.c_vat.set_value(_m(t["vat"]))
        self.c_total.set_value(_m(t["total"]))
        if not t["total"]:
            self.preview.set_lines([])
            return
        mode = self.pay_mode.currentData()
        try:
            with db(readonly=True) as conn:
                if mode == "credit":
                    cid = self.customer.currentData()
                    e = entities.get_entity(conn, cid) if cid else None
                    party = (f"حساب العميل — {e['name']}" if e
                             else "حساب العميل (اختره)")
                else:
                    party = _acc_name(conn, tax_sales.PAY_ACCOUNTS[mode])
                rev = _acc_name(conn, tax_sales.REVENUE)
                vat = _acc_name(conn, tax_sales.VAT_OUT)
        except Exception:
            party, rev, vat = "العميل", tax_sales.REVENUE, "2100"
        lines = [(party, "إجمالي الفاتورة", t["total"], 0),
                 (rev, "المبيعات الضريبية", 0, t["net"])]
        if t["vat"]:
            lines.append((vat, "ضريبة المخرجات", 0, t["vat"]))
        self.preview.set_lines(lines)

    def clear_invoice(self):
        self.lines = []
        self._edit_row = None
        self.btn_add.setText("+ إضافة السطر")
        self.notes.clear()
        for f in (self.l_desc,):
            f.clear()
        self.l_qty.setValue(1)
        self.l_price.setValue(0)
        self.l_disc.setValue(0)
        self._render_lines()

    def post_invoice(self):
        try:
            # سطرٌ مكتوب ولم يُضف — يُضاف تلقائياً بدل أن يضيع
            if self.l_desc.text().strip() and self.l_price.value():
                if self.add_line() is False:
                    return
            cid = self.customer.currentData()
            if cid is None:
                raise ValueError("اختر العميل (أو أضف عميلاً جديداً)")
            if not self.lines:
                raise ValueError("أضف بنداً واحداً على الأقل")
            _rows, t = tax_sales.compute(self.lines)
            if not confirm_post(
                    self, f"فاتورة ضريبية للعميل «{self.customer.currentText()}»"
                    f"\nالصافي {_m(t['net'])} + الضريبة {_m(t['vat'])} = "
                    f"{_m(t['total'])} ريال\n"
                    f"{self.pay_mode.currentText()}\n"
                    "لا أثر على الذهب ولا على المخزون."):
                return
            with db() as conn:
                res = tax_sales.create_invoice(
                    conn, cid, dstr(self.inv_date), self.lines,
                    self.user["username"], self.pay_mode.currentData(),
                    self.notes.text())
            self.clear_invoice()
            self.refresh()
            posted(self, f"تم ترحيل الفاتورة الضريبية {res['doc_no']} — "
                         f"{res['customer_name']} — الإجمالي "
                         f"{_m(res['total'])} ريال (منها ضريبة "
                         f"{_m(res['vat'])})", "tax_sales", res["id"])
        except Exception as e:
            err(self, e)

    # ══════════════════════════ الإشعار الدائن ══════════════════════════
    def _build_credit_tab(self):
        w = QtWidgets.QWidget()
        self.cn_inv = search_combo("اكتب رقم الفاتورة أو اسم العميل…")
        self.cn_inv.currentIndexChanged.connect(self._load_cn_lines)
        self.cn_date = date_edit()
        self.cn_reason = QtWidgets.QComboBox()
        self.cn_reason.setEditable(True)
        self.cn_reason.addItems(REASONS)
        self.cn_reason.setCurrentIndex(-1)
        self.cn_reason.lineEdit().setPlaceholderText(
            "سبب الإشعار — إلزامي")
        self.cn_notes = QtWidgets.QLineEdit()
        self.cn_info = QtWidgets.QLabel("—")
        self.cn_info.setWordWrap(True)
        head = QtWidgets.QGridLayout()
        head.addWidget(QtWidgets.QLabel("الفاتورة الأصلية:"), 0, 0)
        head.addWidget(self.cn_inv, 0, 1)
        head.addWidget(QtWidgets.QLabel("تاريخ الإشعار:"), 0, 2)
        head.addWidget(self.cn_date, 0, 3)
        head.addWidget(QtWidgets.QLabel("سبب الإشعار:"), 1, 0)
        head.addWidget(self.cn_reason, 1, 1)
        head.addWidget(QtWidgets.QLabel("ملاحظات:"), 1, 2)
        head.addWidget(self.cn_notes, 1, 3)
        head.addWidget(self.cn_info, 2, 0, 1, 4)
        head.setColumnStretch(1, 3)
        head.setColumnStretch(3, 2)
        box_head = QtWidgets.QGroupBox("الإشعار الدائن")
        box_head.setLayout(head)

        self.cn_tbl = make_table()
        self.cn_tbl.setColumnCount(len(CN_COLS))
        self.cn_tbl.setHorizontalHeaderLabels(CN_COLS)
        self.cn_tbl.setMinimumHeight(200)
        fit_columns(self.cn_tbl, [5, 30, 11, 10, 12, 16, 14])
        btn_all = QtWidgets.QPushButton("إرجاع المتبقي كاملاً")
        btn_all.setObjectName("ghost")
        btn_all.clicked.connect(self._cn_all)
        box_lines = QtWidgets.QGroupBox("ما يُرتجع من كل بند")
        bl = QtWidgets.QVBoxLayout(box_lines)
        bl.addWidget(self.cn_tbl, 1)
        bl.addWidget(btn_all, 0, QtCore.Qt.AlignLeft)

        self.cn_c_net = Card("صافي المرتجع", "يُخصم من المبيعات الضريبية")
        self.cn_c_vat = Card("الضريبة المستردّة", "تُخصم من ضريبة المخرجات")
        self.cn_c_total = Card("إجمالي الإشعار", "", summary=True)
        self.cn_preview = EntryPreview()
        btn_post = QtWidgets.QPushButton("✔ ترحيل الإشعار الدائن")
        btn_post.clicked.connect(self.post_credit)

        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(box_head)
        lay.addWidget(box_lines, 1)
        lay.addLayout(_bottom((self.cn_c_total, self.cn_c_net,
                               self.cn_c_vat), self.cn_preview))
        lay.addWidget(btn_post)
        return w

    def _reload_open_invoices(self):
        with db(readonly=True) as conn:
            rows = tax_sales.open_invoices(conn)
        reload_combo(self.cn_inv, rows, lambda r: (
            f"{r['doc_no']} — {r['customer_name']} — {_m(r['total'])} ريال"
            f" — {r['doc_date']}"))

    def _load_cn_lines(self, *_):
        sid = self.cn_inv.currentData()
        self._cn_rows = []
        info = "—"
        if sid is not None:
            with db(readonly=True) as conn:
                s, _lines = tax_sales.get(conn, sid)
                left = tax_sales.remaining(conn, sid)
            self._cn_rows = [v for v in left.values()]
            if s:
                info = (f"العميل: {s['customer_name']} · الدفع: "
                        f"{dict(tax_sales.PAY_MODES)[s['pay_mode']]} · "
                        f"الإجمالي {_m(s['total'])} ريال — الإشعار يُردّ "
                        "بطريقة دفع الفاتورة نفسها")
        self.cn_info.setText(info)
        t = self.cn_tbl
        t.setRowCount(len(self._cn_rows))
        self._cn_spins = []
        for r, v in enumerate(self._cn_rows):
            li = v["line"]
            vals = [li["line_no"], li["description"], f"{li['qty']:g}",
                    f"{v['qty_left']:g}", _m(li["unit_price"])]
            for c, val in enumerate(vals):
                t.setItem(r, c, text_item(val) if c == 1 else num_item(val))
            sp = mspin(maximum=max(v["qty_left"], 0))
            sp.setEnabled(v["qty_left"] > 1e-9)
            sp.valueChanged.connect(self._cn_recalc)
            t.setCellWidget(r, 5, sp)
            t.setItem(r, 6, num_item(""))
            self._cn_spins.append(sp)
        t.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
        t.verticalHeader().setDefaultSectionSize(row_height(t) + 6)
        fit_columns(t)
        self._cn_recalc()

    def _cn_all(self):
        for v, sp in zip(self._cn_rows, getattr(self, "_cn_spins", [])):
            sp.setValue(v["qty_left"])

    def _cn_returns(self):
        return [{"src_line_id": v["line"]["id"], "qty": sp.value()}
                for v, sp in zip(self._cn_rows, getattr(self, "_cn_spins", []))
                if sp.value() > 0]

    def _cn_recalc(self, *_):
        lines = []
        for r, (v, sp) in enumerate(zip(self._cn_rows,
                                        getattr(self, "_cn_spins", []))):
            li, q = v["line"], sp.value()
            net = 0.0
            if q > 0:
                disc = float(li["discount"]) * q / float(li["qty"])
                net = round(q * float(li["unit_price"]) - disc, 2)
                lines.append({"description": li["description"], "qty": q,
                              "unit_price": li["unit_price"],
                              "discount": round(disc, 2)})
            it = self.cn_tbl.item(r, 6)
            if it:
                it.setText(_m(net) if q > 0 else "")
        rate = None
        sid = self.cn_inv.currentData()
        t = {"net": 0, "vat": 0, "total": 0}
        if lines and sid is not None:
            try:
                with db(readonly=True) as conn:
                    s = conn.execute("SELECT vat_rate, pay_mode, customer_id"
                                     " FROM tax_sales WHERE id=?",
                                     (sid,)).fetchone()
                    rate = s["vat_rate"]
                    _r, t = tax_sales.compute(lines, rate)
                    if s["pay_mode"] == "credit":
                        e = entities.get_entity(conn, s["customer_id"])
                        party = f"حساب العميل — {e['name']}"
                    else:
                        party = _acc_name(
                            conn, tax_sales.PAY_ACCOUNTS[s["pay_mode"]])
                    ret = _acc_name(conn, tax_sales.RETURNS)
                    vat = _acc_name(conn, tax_sales.VAT_OUT)
                je = [(ret, "مردودات المبيعات الضريبية", t["net"], 0)]
                if t["vat"]:
                    je.append((vat, "عكس ضريبة المخرجات", t["vat"], 0))
                je.append((party, "إجمالي الإشعار", 0, t["total"]))
                self.cn_preview.set_lines(je)
            except Exception:
                self.cn_preview.set_lines([])
        else:
            self.cn_preview.set_lines([])
        self.cn_c_net.set_value(_m(t["net"]))
        self.cn_c_vat.set_value(_m(t["vat"]))
        self.cn_c_total.set_value(_m(t["total"]))

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
                raise ValueError("اكتب كمية المرتجع في بندٍ واحد على الأقل")
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

    # ══════════════════════════ السجل ══════════════════════════
    def _build_register_tab(self):
        w = QtWidgets.QWidget()
        self.r_from = date_edit()
        today = QtCore.QDate.currentDate()
        self.r_from.setDate(QtCore.QDate(today.year(), today.month(), 1))
        self.r_to = date_edit()
        self.r_q = QtWidgets.QLineEdit()
        self.r_q.setPlaceholderText("رقم المستند أو اسم العميل…")
        self.r_q.returnPressed.connect(self.refresh_register)
        self.r_kind = QtWidgets.QComboBox()
        self.r_kind.addItem("الكل", None)
        self.r_kind.addItem("الفواتير", "invoice")
        self.r_kind.addItem("الإشعارات الدائنة", "credit")
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
        self.r_c_crd = Card("الإشعارات الدائنة", "")
        self.r_c_net = Card("صافي المبيعات الضريبية", "بعد الإشعارات")
        self.r_c_vat = Card("صافي ضريبة المخرجات", "تنتقل للإقرار الضريبي",
                            summary=True)
        cards = QtWidgets.QHBoxLayout()
        for c in (self.r_c_inv, self.r_c_crd, self.r_c_net, self.r_c_vat):
            cards.addWidget(c, 1)
        self.reg_tbl = make_table()
        self.reg_tbl.setColumnCount(len(REG_COLS))
        self.reg_tbl.setHorizontalHeaderLabels(REG_COLS)
        fit_columns(self.reg_tbl, [5, 10, 11, 9, 20, 8, 10, 9, 10, 10])
        self.reg_tbl.doubleClicked.connect(
            lambda ix: self._preview_row(ix.row()))
        lay = QtWidgets.QVBoxLayout(w)
        lay.addLayout(top)
        lay.addLayout(cards)
        lay.addWidget(self.reg_tbl, 1)
        self._reg_rows = []
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
            # الإشعار الدائن يُطرح: مبالغه بالأحمر لا بإشارة سالب —
            # الإشارة في الواجهة العربية تقفز يميناً ويساراً
            credit = s["kind"] == "credit"
            vals = [s["doc_no"], "إشعار دائن" if credit else "فاتورة ضريبية",
                    s["doc_date"], s["customer_name"],
                    PAY_SHORT.get(s["pay_mode"], s["pay_mode"]),
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
        t.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
        t.verticalHeader().setDefaultSectionSize(row_height(t))
        fit_columns(t)
        inv, crd = tot["invoices"], tot["credits"]
        self.r_c_inv.set_value(_m(inv["total"]), f"{inv['n']} فاتورة")
        self.r_c_crd.set_value(_m(crd["total"]), f"{crd['n']} إشعار")
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
    def _reload_customers(self):
        with db(readonly=True) as conn:
            rows = entities.list_entities(conn, ("customer",))
        reload_combo(self.customer, rows, lambda r: r["name"])

    def refresh(self):
        try:
            with db() as conn:
                tax_sales.ensure_tables(conn)
                acc_id(conn, tax_sales.REVENUE)       # يتحقّق من الدليل
        except Exception:
            pass
        i = self.tabs.currentIndex() if hasattr(self, "tabs") else 0
        try:
            if i == 0:
                self._reload_customers()
            elif i == 1:
                self._reload_open_invoices()
                self._load_cn_lines()
            else:
                self.refresh_register()
        except Exception as e:                       # noqa: BLE001
            err(self, e)
