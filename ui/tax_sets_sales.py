# -*- coding: utf-8 -*-
"""المبيعات الضريبية بالأطقم (5.5) — فاتورةٌ تخرج بها الأطقم من الخزنة.

**نوع الفاتورة يُختار أولاً** (5.5.1):
  * ضريبية — لمحلٍ أو شركة برقمها الضريبي (إلزامي).
  * مبسطة — لعميلٍ فرد: من الدليل، أو «عميل نقدي» بلا حساب يُكتب اسمه
    وجواله على الفاتورة، ويدفع في الحال (نقداً أو شبكة).

الإدخال: رقم التشغيل ← العدد ← الوزن ← العيار ← الأجر (أو سعر الطقم) —
وEnter يُنزل السطر. الوزن هو **وزن الذهب المقيد** وحده، والعيار عيار
السطر: به يُكتب الوزن والأجر ويُعرضان. والمحاسبة في `models.tax_invoices`:

* الفاتورة فاتورة بيعٍ حقيقية: الأطقم تخرج من خزنتها، وتظهر في كشف العميل
  وحركة الطقم والإقرار الضريبي. والنقد والشبكة يُسدَّدان بسند قبضٍ تلقائي.
* **الإشعار الدائن = مرتجع مبيعات**: يُختار من فاتورةٍ ضريبية سابقة،
  فتعود أطقمه للخزنة ويظهر في كشف الحساب «مرتجع مبيعات» بسعر الأصل،
  ويُردّ المبلغ بطريقة دفع الفاتورة نفسها.
* الفاتورة الضريبية لا تُعدَّل بعد إصدارها — التصحيح بالإشعار وحده.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from ui import kit

from database.database import db
from models import entities, inventory
from models import tax_invoices as tx
from services import karat_view as kv
from ui import tax_trade_kit as tk
from ui.widgets.common import (confirm_post, date_edit, dstr, enter_chain,
                               err, guard_click, make_table, mspin, num_item,
                               posted, reload_combo, row_action_buttons,
                               search_combo, text_item)
from ui.widgets.table_fit import fit_columns

CREDIT_REASONS = ("مرتجع أطقم من العميل", "إلغاء جزئي للفاتورة",
                  "خطأ في الوزن أو السعر", "إلغاء الفاتورة كاملة")
KIND_LABEL = {"sale": "فاتورة", "sale_return": "مرتجع (إشعار دائن)"}
SUB_SHORT = {"standard": "ضريبية", "simplified": "مبسطة"}
WALKIN = 0                     # بند «عميل نقدي» في قائمة المشتري
MODE_PREF = "tax_sales_line_mode"   # 5.8.0: آخر مصدرٍ اختاره المستخدم


def _wo_pieces(wo):
    try:
        return max(1, int(wo["pieces"] or 1))
    except (KeyError, IndexError, TypeError, ValueError):
        return 1


def _buyer_label(row):
    """اسم المشتري في القوائم والسجل: الفرد باسمه المكتوب على الفاتورة."""
    name = (row.get("buyer_name") or "").strip()
    return name or row.get("customer_name") or "—"


class SetsInvoiceTab(QtWidgets.QWidget):
    """فاتورةٌ ضريبية (أو مبسطة) بالأطقم من الخزنة."""

    # 5.5.2: لا عمود «مصنعية» (الصافي يغني عنه) — وسعر الجرام عمودٌ لكل سطر
    COLS = ["", "م", "رقم التشغيل", "العدد", "الوزن", "العيار", "الموديل",
            "سعر الجرام", "الأجر/جم", "قيمة الذهب", "الصافي"]
    C_GP, C_RATE, C_GV, C_NET = 7, 8, 9, 10

    def __init__(self, user, new_customer=None):
        super().__init__()
        self.user = user
        self._new_customer = new_customer
        self.items = []
        self._wo = None              # الطقم المستدعى في سطر الإدخال
        self._avail18 = 0.0          # الباقي منه في الخزنة (مكافئ 18)
        self._wage18 = 0.0
        self._k_shown = int(kv.active())
        self._parties = []
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self._build_header())
        lay.addWidget(self._build_entry())
        lay.addWidget(self._build_items(), 1)
        self.btn_post = kit.PushButton("✔ ترحيل الفاتورة")
        self.btn_post.setObjectName("primary")
        self.btn_post.setMinimumHeight(40)
        self.btn_post.clicked.connect(self.post)
        b_clear = kit.PushButton("تفريغ")
        b_clear.setObjectName("ghost")
        b_clear.clicked.connect(self.clear)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.btn_post, 1)
        row.addWidget(b_clear)
        lay.addLayout(row)
        self.pricing.changed.connect(self._pricing_changed)
        from ui.widgets.common import load_pref
        self.src_mode.set_mode(str(load_pref(MODE_PREF, "free") or "free"))
        self.src_mode.changed.connect(self._mode_changed)
        self._type_changed()
        self._pricing_changed()
        self._mode_changed(initial=True)

    # ══════════ المصدر: يدوي حر · من أطقم الخزنة (5.8.0) ══════════
    def _free(self):
        return self.src_mode.is_free()

    def _mode_changed(self, initial=False):
        free = self._free()
        if not initial:
            from ui.widgets.common import save_pref
            save_pref(MODE_PREF, self.src_mode.mode(),
                      (self.user or {}).get("username"))
            if self.items:
                self.items = []
            self._clear_entry()
        self.acc_lbl.setVisible(free)
        self.acc.setVisible(free)
        self.acc_bal.setVisible(free)
        self.e_model.setReadOnly(not free)
        self.e_model.setPlaceholderText("اختياري" if free else "تلقائي")
        self.e_wo.setPlaceholderText(
            "اكتب رقم التشغيل كما تريده (ولو تكرّر)" if free
            else "امسح الباركود أو اكتب رقم التشغيل")
        self.e_reg.setToolTip(
            "وزن الذهب بعيار السطر — تكتبه بيدك" if free else
            "وزن الذهب المقيد بعيار السطر — الباقي في الخزنة مقترحاً؛ أقلّ "
            "منه = بيع جزءٍ من الطقم")
        self._show_balance()
        self._render()

    def _show_balance(self):
        if not self._free() or self.acc.currentData() is None:
            self.acc_bal.setText("")
            return
        try:
            with db(readonly=True) as conn:
                self.acc_bal.setText(tk.balance_text(conn,
                                                     self.acc.currentData()))
        except Exception:                            # noqa: BLE001
            self.acc_bal.setText("")

    # ══════════ ① نوع الفاتورة والمشتري ══════════
    def _build_header(self):
        box = QtWidgets.QGroupBox("① نوع الفاتورة والمشتري")
        self.b_std = kit.RadioButton("ضريبية — لمحلٍ أو شركة")
        self.b_std.setToolTip("المشتري منشأةٌ برقمها الضريبي — تخصم ضريبة "
                              "هذه الفاتورة من إقرارها")
        self.b_simple = kit.RadioButton("مبسطة — لعميلٍ فرد")
        self.b_simple.setToolTip("لفردٍ بلا رقمٍ ضريبي: من الدليل، أو «عميل "
                                 "نقدي» يُكتب اسمه على الفاتورة")
        grp = QtWidgets.QButtonGroup(self)
        grp.addButton(self.b_std)
        grp.addButton(self.b_simple)
        self.b_std.setChecked(True)
        self.b_std.toggled.connect(lambda *_: self._type_changed())
        self.date = date_edit()
        self.cust_lbl = QtWidgets.QLabel("المحل / الشركة:")
        self.customer = search_combo("اكتب اسم المشتري…")
        self.customer.currentIndexChanged.connect(self._on_customer)
        self.b_new = kit.PushButton("+ جديد")
        self.b_new.setObjectName("ghost")
        self.b_new.clicked.connect(self.new_customer)
        self.buyer_lbl = QtWidgets.QLabel("—")
        self.buyer_lbl.setObjectName("cardSub")
        self.buyer_lbl.setWordWrap(True)
        self.w_name = kit.LineEdit()
        self.w_name.setPlaceholderText("اسم المشتري (يُطبع على الفاتورة)")
        self.w_phone = kit.LineEdit()
        self.w_phone.setPlaceholderText("الجوال (اختياري)")
        self.walkin_box = QtWidgets.QWidget()
        wl = QtWidgets.QHBoxLayout(self.walkin_box)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addWidget(self.w_name, 2)
        wl.addWidget(self.w_phone, 1)
        self.pricing = tk.PricingBox(with_price=False)
        self.pay = kit.ComboBox()
        for k, lbl in tx.PAY_MODES:
            self.pay.addItem(lbl, k)
        self.pay.setToolTip("النقد والشبكة يُسدَّدان بسند قبضٍ تلقائي بإجمالي "
                            "الفاتورة — والآجل يبقى على حساب المشتري")
        self.notes = kit.LineEdit()
        self.notes.setPlaceholderText("البيان (اختياري)")
        # 5.8.0: مصدر الأسطر — يدوي حر (افتراضي) أو من أطقم الخزنة
        self.src_mode = tk.ModeBox("من أطقم الخزنة — يخرج الطقم من خزنتك")
        self.acc = kit.ComboBox()
        self.acc.setToolTip("الحساب الذي يخرج منه وزن الإدخال اليدوي — مخزون "
                            "الذهب الضريبي افتراضاً (يقبل السالب)")
        self.acc.currentIndexChanged.connect(lambda *_: self._show_balance())
        self.acc_lbl = QtWidgets.QLabel("من حساب:")
        self.acc_bal = QtWidgets.QLabel("")
        self.acc_bal.setObjectName("cardSub")
        self.disc = tk.discount_spin()
        self.disc.valueChanged.connect(lambda *_: self._render())

        types = QtWidgets.QHBoxLayout()
        types.addWidget(self.b_std)
        types.addSpacing(18)
        types.addWidget(self.b_simple)
        types.addStretch(1)
        crow = QtWidgets.QHBoxLayout()
        crow.addWidget(self.customer, 1)
        crow.addWidget(self.b_new)
        g = QtWidgets.QGridLayout(box)
        g.setVerticalSpacing(6)
        g.addWidget(QtWidgets.QLabel("النوع:"), 0, 0)
        g.addLayout(types, 0, 1, 1, 3)
        g.addWidget(QtWidgets.QLabel("التاريخ:"), 0, 4)
        g.addWidget(self.date, 0, 5)
        g.addWidget(self.cust_lbl, 1, 0)
        g.addLayout(crow, 1, 1)
        g.addWidget(self.walkin_box, 1, 2, 1, 2)
        g.addWidget(self.buyer_lbl, 1, 2, 1, 4)
        g.addWidget(QtWidgets.QLabel("التسعير:"), 2, 0)
        g.addWidget(self.pricing, 2, 1)
        g.addWidget(QtWidgets.QLabel("الدفع:"), 2, 2)
        g.addWidget(self.pay, 2, 3)
        g.addWidget(QtWidgets.QLabel("البيان:"), 2, 4)
        g.addWidget(self.notes, 2, 5)
        g.addWidget(QtWidgets.QLabel("الأسطر:"), 3, 0)
        g.addWidget(self.src_mode, 3, 1)
        accw = QtWidgets.QHBoxLayout()
        accw.addWidget(self.acc, 1)
        accw.addWidget(self.acc_bal)
        g.addWidget(self.acc_lbl, 3, 2)
        g.addLayout(accw, 3, 3)
        g.addWidget(QtWidgets.QLabel("خصم نقدي:"), 3, 4)
        g.addWidget(self.disc, 3, 5)
        g.setColumnStretch(1, 4)
        g.setColumnStretch(3, 2)
        g.setColumnStretch(5, 2)
        return box

    # ══════════ ② سطر الإدخال ══════════
    def _build_entry(self):
        box = QtWidgets.QGroupBox("② إدخال الطقم")
        self.e_wo = kit.LineEdit()
        self.e_wo.setPlaceholderText("امسح الباركود أو اكتب رقم التشغيل")
        self.e_wo.editingFinished.connect(self._lookup)
        self.e_pieces = kit.SpinBox()
        self.e_pieces.setRange(1, 999)
        self.e_pieces.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.e_pieces.setAlignment(QtCore.Qt.AlignCenter)
        self.e_reg = tk.wspin()
        self.e_reg.setToolTip("وزن الذهب المقيد بعيار السطر — الباقي في "
                              "الخزنة مقترحاً؛ أقلّ منه = بيع جزءٍ من الطقم")
        self.e_reg.valueChanged.connect(self._line_changed)
        self.e_karat = tk.karat_combo()
        self.e_karat.currentIndexChanged.connect(self._karat_changed)
        self.e_model = kit.LineEdit()
        self.e_model.setReadOnly(True)
        self.e_model.setPlaceholderText("تلقائي")
        # سعر الجرام بعيار السطر — يبقى من سطرٍ لسطر (يظهر بالتسعير بالريال)
        self.e_gp = mspin()
        self.e_gp.setToolTip("سعر جرام الذهب بعيار هذا السطر — قيمة الذهب ="
                             " الوزن × سعر الجرام")
        self.e_gp.valueChanged.connect(self._line_changed)
        self.l_gp = tk.sub("سعر الجرام")
        self.e_rate = mspin()
        self.e_rate.valueChanged.connect(self._rate_typed)
        self.e_net = kit.LineEdit()
        self.e_net.setReadOnly(True)
        self.l_rate = tk.sub("الأجر/جم")
        self.btn_add = kit.PushButton("+ إضافة سطر")
        self.btn_add.clicked.connect(self.add_item)
        fields = [("رقم التشغيل", self.e_wo, 3), ("العدد", self.e_pieces, 1),
                  ("الوزن", self.e_reg, 2), ("العيار", self.e_karat, 2),
                  ("الموديل", self.e_model, 2), ("gp", self.e_gp, 2),
                  (None, self.e_rate, 2), ("صافي السطر", self.e_net, 2)]
        g = QtWidgets.QGridLayout(box)
        g.setHorizontalSpacing(6)
        for c, (label, wd, st) in enumerate(fields):
            wd.setMinimumWidth(86)
            lbl = (self.l_rate if label is None else
                   self.l_gp if label == "gp" else tk.sub(label))
            g.addWidget(lbl, 0, c)
            g.addWidget(wd, 1, c)
            g.setColumnStretch(c, st)
        g.addWidget(self.btn_add, 1, len(fields))
        enter_chain(self, [self.e_wo, self.e_pieces, self.e_reg, self.e_karat,
                           self.e_gp, self.e_rate],
                    on_last=lambda: self.e_wo if self.add_item() else False,
                    require={self.e_wo: lambda: bool(
                        self.e_wo.text().strip())})
        return box

    def _build_items(self):
        box = QtWidgets.QGroupBox("③ بنود الفاتورة")
        self.tbl = make_table()
        self.tbl.setColumnCount(len(self.COLS))
        self.tbl.setHorizontalHeaderLabels(self.COLS)
        self.tbl.setMinimumHeight(200)
        fit_columns(self.tbl, [8, 4, 13, 6, 10, 7, 10, 10, 9, 11, 12])
        self.totals = tk.TotalsRow("ضريبة المخرجات")
        self.hint = QtWidgets.QLabel("")
        self.hint.setObjectName("cardSub")
        self.hint.setWordWrap(True)
        v = QtWidgets.QVBoxLayout(box)
        v.addWidget(self.tbl, 1)
        v.addWidget(self.hint)
        v.addWidget(self.totals)
        return box

    # ══════════ النوع والمشتري ══════════
    def _std(self):
        return self.b_std.isChecked()

    def _subtype(self):
        return "standard" if self._std() else "simplified"

    def _is_walkin(self):
        return (not self._std()) and self.customer.currentData() == WALKIN

    def _type_changed(self):
        std = self._std()
        self.cust_lbl.setText("المحل / الشركة:" if std else "العميل:")
        self.b_new.setToolTip("منشأةٌ جديدة برقمها الضريبي" if std
                              else "عميلٌ فرد جديد في الدليل")
        self.btn_post.setText("✔ ترحيل الفاتورة الضريبية" if std
                              else "✔ ترحيل الفاتورة المبسطة")
        self._fill_parties()
        # تغيير النوع يبدأ المشتري من جديد — لا يبقى مشتري النوع الآخر
        if std:
            if hasattr(self.customer, "clear_selection"):
                self.customer.clear_selection()
            else:
                self.customer.setCurrentIndex(-1)
        else:
            self.customer.setCurrentIndex(0)
        self._on_customer()

    def _fill_parties(self):
        from services.fatoora import profile as pf
        rows = self._parties
        if self._std():
            shown = [r for r in rows if pf.valid_vat(r.get("vat") or "")]
        else:
            shown = [{"id": WALKIN, "name": "👤 عميل نقدي — بلا حساب"}] + rows
        reload_combo(self.customer, shown, lambda r: r["name"])
        if not self._std() and self.customer.currentData() is None:
            self.customer.setCurrentIndex(0)

    def new_customer(self):
        if self._new_customer is None:
            return
        cid = self._new_customer(self, self._std())
        if cid:
            self.reload()
            i = self.customer.findData(cid)
            if i >= 0:
                self.customer.setCurrentIndex(i)

    def _on_customer(self, *_):
        from services.fatoora import profile as pf
        walk = self._is_walkin()
        self.walkin_box.setVisible(walk)
        self.buyer_lbl.setVisible(not walk)
        if walk:
            if self.pay.currentData() == "credit":
                self.pay.setCurrentIndex(self.pay.findData("cash"))
            return
        cid = self.customer.currentData()
        if cid is None:
            self.buyer_lbl.setText("—" if not self._std() else
                                   "المنشآت ذات الرقم الضريبي وحدها — «+ جديد»"
                                   " لمنشأةٍ برقمها")
            return
        try:
            from services.fatoora import ledger
            with db(readonly=True) as conn:
                b = pf.buyer(conn, cid) or {}
                live = ledger.enabled(conn)
            if self._std():
                txt = f"✔ الرقم الضريبي {b.get('vat') or '—'}"
                # العنوان يلزم المستند الإلكتروني وحده (الربط مع الهيئة)
                miss = pf.buyer_problems(b) if live else []
                if miss:
                    txt += " · ينقص عنوانه: " + "، ".join(miss)
            else:
                txt = "فاتورة مبسطة — بلا رقم ضريبي للمشتري"
            self.buyer_lbl.setText(txt)
        except Exception as e:                       # noqa: BLE001
            self.buyer_lbl.setText(str(e))

    # ══════════ التسعير والعيار ══════════
    def _k(self):
        return int(self.e_karat.currentData() or kv.active())

    def _pricing_changed(self):
        piece, riyal = self.pricing.is_piece(), self.pricing.is_riyal()
        self.l_rate.setText("سعر الطقم (ريال)" if piece else "الأجر/جم")
        self.e_rate.blockSignals(True)
        self.e_rate.setValue(0 if piece else kv.rate(self._wage18, self._k()))
        self.e_rate.blockSignals(False)
        # سعر الجرام لا يلزم «الأجر فقط» — يظهر بالريال وحده
        self.l_gp.setVisible(riyal)
        self.e_gp.setVisible(riyal)
        self.l_gp.setText("سعر الجرام" + (" (للفصل)" if piece else ""))
        hdr = list(self.COLS)
        hdr[self.C_RATE] = "سعر الطقم" if piece else "الأجر/جم"
        self.tbl.setHorizontalHeaderLabels(hdr)
        self.tbl.setColumnHidden(self.C_GP, not riyal)
        self.tbl.setColumnHidden(self.C_GV, not riyal)
        self._line_changed()
        self._render()

    def _line_pricing(self, gold_price=None, karat=None):
        return tk.line_pricing(
            self.pricing.pricing(),
            self.e_gp.value() if gold_price is None else gold_price,
            self._k() if karat is None else karat)

    def _karat_changed(self, *_):
        """تبديل العيار يعيد كتابة الوزن والأجر/جم به — والذهب نفسه ثابت."""
        old, new = self._k_shown, self._k()
        w18 = self._w18(old)
        self._k_shown = new
        self.e_reg.blockSignals(True)
        self.e_reg.setValue(kv.g(w18, new) if w18 else 0)
        self.e_reg.blockSignals(False)
        if not self.pricing.is_piece():
            self.e_rate.blockSignals(True)
            self.e_rate.setValue(kv.rate(self._wage18, new))
            self.e_rate.blockSignals(False)
        self._line_changed()

    # ══════════ سطر الإدخال ══════════
    def _clear_entry(self):
        self._wo = None
        self._avail18 = 0.0
        self._wage18 = 0.0
        for f in (self.e_wo, self.e_model, self.e_net):
            f.clear()
        self.e_pieces.setValue(1)
        for sp in (self.e_reg, self.e_rate):
            sp.blockSignals(True)
            sp.setValue(0)
            sp.blockSignals(False)

    def _lookup(self):
        if self._free():
            self._line_changed()      # الإدخال اليدوي: لا خزنة يُسأل منها
            return
        no = self.e_wo.text().strip()
        if not no or (self._wo is not None
                      and self._wo["work_order_no"] == no):
            return
        self._wo = None
        try:
            from models import invoices as inv
            from models import wo_moves as wm
            with db(readonly=True) as conn:
                wo = inventory.get_wo_by_no(conn, no)
                if wo is None:
                    raise ValueError(f"رقم التشغيل {no} غير موجود في خزنتك")
                if any(x["wo_id"] == wo["id"] for x in self.items
                       if not x["bulk"]):
                    raise ValueError(f"الطقم {no} مضافٌ في الفاتورة من قبل")
                bulk = bool(wo["is_bulk"])
                avail = (0.0 if bulk
                         else wm.default_weight(conn, wo, wm.SALE))
                why = (None if bulk else
                       wm.refusal(conn, wo, wm.SALE, dstr(self.date), avail))
                if why == "none-left":
                    raise ValueError(f"الطقم {no} ليس في الخزنة"
                                     + inv._where_is(conn, wo["id"]))
                if why:
                    raise ValueError(why)
        except ValueError as e:
            err(self, e)
            self.e_wo.selectAll()
            return
        self._wo = dict(wo)
        self._wo["bulk"] = bulk
        self._avail18 = float(avail)
        self._wage18 = float(wo["wage_per_gram"] or 0)
        self.e_model.setText(wo["model_no"] or ("ايطالي" if bulk else "—"))
        self.e_pieces.setValue(_wo_pieces(wo))
        self.e_reg.blockSignals(True)
        self.e_reg.setValue(kv.g(avail, self._k()))
        self.e_reg.blockSignals(False)
        if not self.pricing.is_piece():
            self.e_rate.blockSignals(True)
            self.e_rate.setValue(kv.rate(self._wage18, self._k()))
            self.e_rate.blockSignals(False)
        self._line_changed()

    def _w18(self, k=None):
        """وزن السطر بمكافئ 18 — الباقي كما خُزِّن إن لم يُغيَّر."""
        k = int(k or self._k())
        v = self.e_reg.value()
        if self._avail18 and abs(v - kv.g(self._avail18, k)) <= 0.0051:
            return self._avail18
        return kv.store(v, k)

    def _rate_typed(self, *_):
        if not self.pricing.is_piece():
            self._wage18 = kv.rate_store(self.e_rate.value(), self._k())
        self._line_changed()

    def _line_changed(self, *_):
        if self._wo is None and not (self._free()
                                     and self.e_wo.text().strip()):
            self.e_net.clear()
            return
        t = self._line_pricing()
        piece = self.e_rate.value() if self.pricing.is_piece() else 0
        _wg, _gv, net, why = tk.line_calc(self._w18(), self._wage18, piece, t)
        self.e_net.setText(tk.m(net) if not why else "—")
        self.e_net.setToolTip(why)

    def add_item(self):
        free = self._free()
        if free:
            no = " ".join(self.e_wo.text().split())
            if not no:
                err(self, "اكتب رقم التشغيل")
                self.e_wo.setFocus()
                return False
            # الإدخال اليدوي: الرقم وصفٌ للسطر — لا بطاقة ولا باقٍ في الخزنة
            self._wo = {"id": None, "work_order_no": no, "bulk": False}
            self._avail18 = 0.0
        if self._wo is None:
            self._lookup()
        if self._wo is None:
            return False
        w18 = self._w18()
        if w18 <= 0:
            err(self, "اكتب الوزن")
            self.e_reg.setFocus()
            return False
        if not free and not self._wo["bulk"] and \
                w18 > self._avail18 + 0.0005:
            err(self, f"الوزن أكبر من الباقي في الخزنة "
                      f"({tk.wk(self._avail18, self._k())} عيار {self._k()})")
            return False
        if self.pricing.is_riyal() and self.e_gp.value() <= 0:
            err(self, f"اكتب سعر الجرام (عيار {self._k()})")
            self.e_gp.setFocus()
            return False
        if self.pricing.is_piece() and self.e_rate.value() <= 0:
            err(self, "اكتب سعر الطقم بالريال")
            self.e_rate.setFocus()
            return False
        if free and not self.pricing.is_piece():
            self._wage18 = kv.rate_store(self.e_rate.value(), self._k())
        self.items.append({
            "wo_id": self._wo["id"], "wo_no": self._wo["work_order_no"],
            "model": " ".join(self.e_model.text().split()),
            "bulk": self._wo["bulk"], "free": free,
            "pieces": self.e_pieces.value(), "w18": w18,
            "avail18": self._avail18, "karat": self._k(),
            "wage18": self._wage18,
            "gold_price": (self.e_gp.value() if self.pricing.is_riyal()
                           else 0.0),
            "piece_price": (self.e_rate.value() if self.pricing.is_piece()
                            else 0.0), "wo": self._wo})
        self._clear_entry()
        self._render()
        return True

    def _del(self, r):
        if 0 <= r < len(self.items):
            del self.items[r]
            self._render()

    def _edit(self, r):
        if not (0 <= r < len(self.items)):
            return
        it = self.items.pop(r)
        self._wo = it["wo"]
        self._avail18 = it["avail18"]
        self._wage18 = it["wage18"]
        tk.set_karat(self.e_karat, it["karat"])
        self._k_shown = self._k()
        self.e_wo.setText(it["wo_no"])
        self.e_model.setText(it["model"])
        self.e_pieces.setValue(int(it["pieces"]))
        self.e_reg.blockSignals(True)
        self.e_reg.setValue(kv.g(it["w18"], it["karat"]))
        self.e_reg.blockSignals(False)
        self.e_rate.blockSignals(True)
        self.e_rate.setValue(it["piece_price"] if self.pricing.is_piece()
                             else kv.rate(it["wage18"], it["karat"]))
        self.e_rate.blockSignals(False)
        if it.get("gold_price"):
            self.e_gp.blockSignals(True)
            self.e_gp.setValue(it["gold_price"])
            self.e_gp.blockSignals(False)
        self._line_changed()
        self._render()
        self.e_rate.setFocus()
        self.e_rate.selectAll()

    def _render(self):
        t = self.tbl
        # الصفوف تُفرَّغ أولاً فتذهب أزرارها معها — لا تبقى أزرار سطرٍ قديم
        t.setRowCount(0)
        t.setRowCount(len(self.items))
        piece, riyal = self.pricing.is_piece(), self.pricing.is_riyal()
        tw = tgv = twg = 0.0
        npcs = 0
        bad = []
        red = QtGui.QBrush(QtGui.QColor("#a4262c"))
        for r, it in enumerate(self.items):
            tp = self._line_pricing(it.get("gold_price") or 0, it["karat"])
            wg, gv, net, why = tk.line_calc(it["w18"], it["wage18"],
                                            it["piece_price"], tp)
            if why:
                bad.append(f"{it['wo_no']}: {why}")
            tw += it["w18"]
            tgv += gv
            twg += wg
            npcs += int(it["pieces"])
            k = it["karat"]
            vals = [r + 1, it["wo_no"], str(it["pieces"]),
                    tk.wk(it["w18"], k), str(k), it["model"] or "—",
                    tk.m(it.get("gold_price") or 0) if riyal else "—",
                    tk.m(it["piece_price"]) if piece
                    else tk.m(kv.rate(it["wage18"], k)),
                    tk.m(gv) if riyal else "—",
                    tk.m(net) if not why else "—"]
            for c, v in enumerate(vals, 1):
                cell = (text_item(v) if c in (2, 6) else num_item(v))
                if why and c == self.C_NET:
                    cell.setForeground(red)
                    cell.setToolTip(why)
                t.setItem(r, c, cell)
        row_action_buttons(t, len(self.items), self._edit, self._del,
                           edit_tip="تصحيح السطر", del_tip="حذف السطر")
        tk.fix_rows(t, 10)
        self.totals.show_totals(len(self.items), npcs, tw, tgv, twg, riyal,
                                self.disc.value())
        msgs = bad
        self.hint.setText("⚠ " + " · ".join(msgs) if msgs else (
            "الذهب يُقيَّد على المشتري وزناً، والضريبة على الأجور وحدها"
            if not riyal else
            "الفاتورة كلها بالريال: الصافي = الوزن × (سعر الجرام + الأجر)"
            " — والضريبة عليه كله" if not piece else
            "الفاتورة كلها بالريال: الصافي سعر الطقم — والضريبة عليه كله"))

    # ══════════ الترحيل ══════════
    def clear(self):
        self.items = []
        self.notes.clear()
        self.disc.blockSignals(True)
        self.disc.setValue(0)
        self.disc.blockSignals(False)
        self._show_balance()
        self.w_name.clear()
        self.w_phone.clear()
        self._clear_entry()
        self._render()

    def post(self):
        try:
            cid = self.customer.currentData()
            walk = self._is_walkin()
            if cid is None:
                raise ValueError("اختر المحل أو الشركة" if self._std()
                                 else "اختر العميل أو «عميل نقدي»")
            if self.e_wo.text().strip() and self._wo is not None:
                if not self.add_item():
                    return
            if not self.items:
                raise ValueError("أضف رقم تشغيلٍ واحداً على الأقل")
            for it in self.items:
                t = self._line_pricing(it.get("gold_price") or 0, it["karat"])
                _a, _b, _n, why = tk.line_calc(it["w18"], it["wage18"],
                                               it["piece_price"], t)
                if why:
                    raise ValueError(f"{it['wo_no']}: {why}")
            buyer = (self.w_name.text().strip() or "عميل نقدي") if walk \
                else self.customer.currentText()
            T = self.totals
            pay = self.pay.currentData()
            free = self._free()
            disc = self.disc.value()
            where = (f"الوزن يخرج من «{self.acc.currentText()}» (ولو صار "
                     "رصيده سالباً)." if free else "الأطقم تخرج من الخزنة.")
            if not confirm_post(
                    self, f"{tx.SUBTYPE_LABEL[self._subtype()]} — «{buyer}»\n"
                    f"{self.pricing.label()} · الدفع: {tx.PAY_LABEL[pay]}\n"
                    f"{len(self.items)} طقم · الصافي {T.text(T.c_net)}"
                    + (f" (بعد خصم {tk.m(disc)})" if disc else "")
                    + f" + الضريبة {T.text(T.c_vat)} = {T.text(T.c_total)}"
                    f" ريال\n{where}"
                    + ("\nويُسدَّد الإجمالي بسند قبضٍ تلقائي."
                       if pay != "credit" else ""), self.date):
                return
            v = self.pricing.values()
            if self.pricing.is_riyal():
                # سعر الفاتورة سعرُ أول سطر — ولكل سطرٍ سعره بعياره
                v["gold_price"] = self.items[0]["gold_price"]
                v["price_karat"] = self.items[0]["karat"]
            cart = [{"work_order_id": it["wo_id"], "weight": it["w18"],
                     "wage_override": it["wage18"],
                     "piece_price": it["piece_price"],
                     "pieces": it["pieces"], "karat": it["karat"],
                     "gold_price": it.get("gold_price") or 0}
                    for it in self.items]
            with db() as conn:
                if free:
                    from models import tax_free
                    res = tax_free.create_sale(
                        conn, None if walk else cid,
                        [{"wo_no": it["wo_no"], "model_no": it["model"],
                          "pieces": it["pieces"], "weight": it["w18"],
                          "karat": it["karat"], "wage": it["wage18"],
                          "piece_price": it["piece_price"],
                          "gold_price": it.get("gold_price") or 0}
                         for it in self.items],
                        dstr(self.date), self.user["username"], v["pricing"],
                        v["gold_price"], v["price_karat"],
                        self.notes.text().strip(), subtype=self._subtype(),
                        buyer_name=self.w_name.text().strip() if walk else "",
                        buyer_phone=(self.w_phone.text().strip() if walk
                                     else ""),
                        pay_mode=pay, account_id=self.acc.currentData(),
                        discount=disc)
                else:
                    res = tx.create_invoice(
                        conn, None if walk else cid, cart, dstr(self.date),
                        self.user["username"], v["pricing"], v["gold_price"],
                        v["price_karat"], self.notes.text().strip(),
                        subtype=self._subtype(),
                        buyer_name=self.w_name.text().strip() if walk else "",
                        buyer_phone=(self.w_phone.text().strip() if walk
                                     else ""),
                        pay_mode=pay, discount=disc)
            self.clear()
            msg = (f"تم ترحيل {tx.SUBTYPE_LABEL[self._subtype()]} "
                   f"{res['invoice_no']} — «{buyer}» — الإجمالي "
                   f"{tk.m(res['grand_total'])} ريال")
            if res.get("split"):
                msg += (f"\nوالإيطالي بفاتورةٍ مستقلة {res['split']['invoice_no']}"
                        f" — {tk.m(res['split']['grand_total'])} ريال")
            if res.get("voucher_no"):
                msg += (f"\nسُدِّد {tk.m(res['paid'])} ريال بسند القبض "
                        f"{res['voucher_no']} ({tx.PAY_LABEL[pay]})")
            posted(self, msg, "invoice", res["id"])
        except Exception as e:
            err(self, e)

    def reload(self):
        with db(readonly=True) as conn:
            tk.fill_stock_accounts(self.acc, conn)
            walk = tx.walkin_customer(conn, False)
            self._parties = [
                {"id": r["id"], "name": r["name"],
                 "vat": (r["vat_number"] if "vat_number" in r.keys()
                         else "") or ""}
                for r in entities.list_entities(conn)
                if r["entity_type"] != "internal" and r["id"] != walk]
        self._fill_parties()
        self._on_customer()
        self._show_balance()


class SetsCreditTab(QtWidgets.QWidget):
    """الإشعار الدائن = مرتجع مبيعات من فاتورةٍ ضريبية بالأطقم."""

    # 5.8.0: «وزن المرتجع» باسمه، ونوع تسعير السطر وسعره كما بِيع
    COLS = ["", "رقم التشغيل", "العدد", "الوزن المباع", "الباقي", "العيار",
            "الموديل", "نوع التسعير", "السعر", "وزن المرتجع", "صافي المرتجع"]
    C_SPIN, C_NET = 9, 10

    def __init__(self, user):
        super().__init__()
        self.user = user
        self._rows = []
        self._spins = []
        self._orig = None
        self.inv = search_combo("اكتب رقم الفاتورة أو اسم المشتري…")
        self.inv.currentIndexChanged.connect(self._load)
        self.date = date_edit()
        self.reason = kit.ComboBox()
        self.reason.setEditable(True)
        self.reason.addItems(CREDIT_REASONS)
        self.reason.setCurrentIndex(-1)
        self.reason.lineEdit().setPlaceholderText("سبب الإشعار — إلزامي")
        self.info = QtWidgets.QLabel("—")
        self.info.setObjectName("cardSub")
        self.info.setWordWrap(True)
        head = QtWidgets.QGroupBox("① الفاتورة الأصلية")
        g = QtWidgets.QGridLayout(head)
        g.addWidget(QtWidgets.QLabel("الفاتورة:"), 0, 0)
        g.addWidget(self.inv, 0, 1)
        g.addWidget(QtWidgets.QLabel("تاريخ الإشعار:"), 0, 2)
        g.addWidget(self.date, 0, 3)
        g.addWidget(QtWidgets.QLabel("السبب:"), 1, 0)
        g.addWidget(self.reason, 1, 1, 1, 3)
        g.addWidget(self.info, 2, 0, 1, 4)
        g.setColumnStretch(1, 3)
        g.setColumnStretch(3, 2)
        self.tbl = make_table()
        self.tbl.setColumnCount(len(self.COLS))
        self.tbl.setHorizontalHeaderLabels(self.COLS)
        self.tbl.setMinimumHeight(220)
        fit_columns(self.tbl, [4, 11, 5, 9, 9, 6, 9, 11, 16, 11, 10])
        self.tbl.itemChanged.connect(self._checked)
        b_all = kit.PushButton("إرجاع الباقي كله")
        b_all.setObjectName("ghost")
        b_all.clicked.connect(self._all)
        lines = QtWidgets.QGroupBox("② الأطقم المرتجعة")
        bl = QtWidgets.QVBoxLayout(lines)
        bl.addWidget(self.tbl, 1)
        bl.addWidget(b_all, 0, QtCore.Qt.AlignLeft)
        self.totals = tk.TotalsRow("الضريبة المردودة",
                                   "تُخصم من ضريبة المخرجات")
        btn = kit.PushButton("✔ ترحيل مرتجع المبيعات (إشعار دائن)")
        btn.clicked.connect(self.post)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(head)
        lay.addWidget(lines, 1)
        lay.addWidget(self.totals)
        lay.addWidget(btn)

    @staticmethod
    def _label(r):
        sub = SUB_SHORT.get(r.get("tax_subtype") or "", "")
        return (f"{r['invoice_no']} — {_buyer_label(r)}"
                + (f" ({sub})" if sub else "")
                + f" — {tk.m(r['grand_total'])} ريال — {r['invoice_date']}")

    def reload(self):
        with db(readonly=True) as conn:
            rows = tx.open_invoices(conn)
        reload_combo(self.inv, rows, self._label)
        self._load()

    def _load(self, *_):
        iid = self.inv.currentData()
        self._rows, self._spins, self._orig = [], [], None
        info = "—"
        if iid is not None:
            with db(readonly=True) as conn:
                self._orig = dict(conn.execute(
                    "SELECT i.*, e.name customer_name FROM invoices i JOIN"
                    " entities e ON e.id=i.customer_id WHERE i.id=?",
                    (iid,)).fetchone())
                self._rows = tx.returnable(conn, iid)
            o = self._orig
            pm = o.get("pay_mode") or "credit"
            free = bool(o.get("free_lines"))
            disc = float(o.get("discount") or 0)
            with db(readonly=True) as conn:
                acc = conn.execute("SELECT code, name FROM accounts WHERE"
                                   " id=?", (o.get("source_account_id"),)
                                   ).fetchone()
            where = (f"ويعود الوزن إلى «{acc['code']} — {acc['name']}»"
                     if free and acc else "وتعود الأطقم للخزنة")
            info = (f"{tx.SUBTYPE_LABEL.get(o.get('tax_subtype') or '', 'فاتورة')}"
                    f" · المشتري: {_buyer_label(o)} · نوع التسعير: "
                    f"{tx.PRICING_LABEL.get(o['pricing'], '')}"
                    + (" · إدخال يدوي" if free else " · من أطقم الخزنة")
                    + (f" · خصم الأصل {tk.m(disc)} — يُردّ منه بنسبة المرتجع"
                       if disc else "")
                    + f"\nيُردّ بسعر الفاتورة نفسها {where} — "
                    + ("ويُخصم من حساب المشتري (آجل)." if pm == "credit"
                       else f"ويُردّ المبلغ {tx.PAY_LABEL[pm]} بسند صرفٍ "
                            "تلقائي."))
        self.info.setText(info)
        t = self.tbl
        t.blockSignals(True)
        t.setRowCount(0)
        t.setRowCount(len(self._rows))
        for r, x in enumerate(self._rows):
            k = int(x["karat"] or kv.active())
            chk = QtWidgets.QTableWidgetItem()
            chk.setFlags(QtCore.Qt.ItemIsUserCheckable
                         | QtCore.Qt.ItemIsEnabled)
            chk.setCheckState(QtCore.Qt.Unchecked)
            t.setItem(r, 0, chk)
            kind, price = self._price_txt(x, k)
            vals = [x["wo_no"], str(x["pieces"] or "—"),
                    tk.wk(x["weight"], k), tk.wk(x["left"], k), str(k),
                    x["model_no"] or "—", kind, price]
            for c, v in enumerate(vals, 1):
                t.setItem(r, c, text_item(v) if c in (1, 6, 7, 8)
                          else num_item(v))
            sp = tk.wspin()
            sp.setMaximum(max(kv.g(x["left"], k), 0))
            sp.setEnabled(x["left"] > 0.0005)
            sp.setToolTip("وزن المرتجع بعيار السطر — الباقي كله أو جزءٌ منه")
            sp.valueChanged.connect(lambda _v, i=r: self._spin_moved(i))
            t.setCellWidget(r, self.C_SPIN, sp)
            t.setItem(r, self.C_NET, num_item(""))
            self._spins.append(sp)
        t.blockSignals(False)
        tk.fix_rows(t, 6)
        self._recalc()

    def _price_txt(self, x, k):
        """(نوع التسعير، السعر كما بِيع) لسطر الفاتورة الأصلية."""
        p = (self._orig or {}).get("pricing") or "wage"
        rate = tk.m(kv.rate(x.get("wage") or 0, k))
        if p == "piece":
            return ("سعر الطقم",
                    f"{tk.m(x.get('piece_price') or 0)} ريال للطقم"
                    + (f" (جرام {tk.m(x.get('gold_price') or 0)})"
                       if x.get("gold_price") else ""))
        if p == "gram":
            return ("جرام + أجر",
                    f"جرام {tk.m(x.get('gold_price') or 0)} + أجر {rate}")
        return ("الأجر فقط", f"أجر {rate}/جم")

    @staticmethod
    def _kx(x):
        return int(x["karat"] or kv.active())

    def _checked(self, item):
        if item.column() != 0 or item.row() >= len(self._spins):
            return
        x, sp = self._rows[item.row()], self._spins[item.row()]
        on = item.checkState() == QtCore.Qt.Checked
        sp.blockSignals(True)
        sp.setValue(kv.g(x["left"], self._kx(x)) if on else 0)
        sp.blockSignals(False)
        self._recalc()

    def _spin_moved(self, r):
        it = self.tbl.item(r, 0)
        if it is not None:
            self.tbl.blockSignals(True)
            it.setCheckState(QtCore.Qt.Checked if self._spins[r].value() > 0
                             else QtCore.Qt.Unchecked)
            self.tbl.blockSignals(False)
        self._recalc()

    def _all(self):
        for r in range(len(self._rows)):
            it = self.tbl.item(r, 0)
            if it is not None and self._spins[r].isEnabled():
                it.setCheckState(QtCore.Qt.Checked)

    def _returns(self):
        out = []
        for x, sp in zip(self._rows, self._spins):
            v = sp.value()
            if v <= 0:
                continue
            k = self._kx(x)
            w18 = (x["left"] if abs(v - kv.g(x["left"], k)) <= 0.0051
                   else kv.store(v, k))
            out.append({"item_id": x["item_id"], "weight": w18})
        return out

    def _recalc(self, *_):
        by = {r["item_id"]: r["weight"] for r in self._returns()}
        tw = tgv = twg = 0.0
        n = npcs = 0
        for r, x in enumerate(self._rows):
            w18 = by.get(x["item_id"], 0.0)
            cell = self.tbl.item(r, self.C_NET)
            if not w18:
                if cell:
                    cell.setText("")
                continue
            frac = w18 / x["weight"] if x["weight"] > 0 else 1.0
            gv = round(x["gold_value"] * frac, 2)
            wg = round(x["wages"] * frac, 2)
            tw += w18
            tgv += gv
            twg += wg
            n += 1
            npcs += int(x["pieces"] or 0) if frac >= 0.999 else 0
            if cell:
                cell.setText(tk.m(gv + wg))
        riyal = bool(self._orig and self._orig["pricing"] in tx.RIYAL)
        # 5.8.0: يُردّ من خصم الأصل بنسبة صافي المرتجع
        disc = 0.0
        o = self._orig or {}
        if float(o.get("discount") or 0) > 0:
            from models import tax_free
            disc = tax_free.share(o["discount"], round(tgv + twg, 2),
                                  round(float(o.get("total_wages") or 0)
                                        + float(o.get("gold_value") or 0), 2))
        self.totals.show_totals(n, npcs, tw, tgv, twg, riyal, disc)

    def post(self):
        try:
            iid = self.inv.currentData()
            if iid is None:
                raise ValueError("اختر الفاتورة الأصلية")
            reason = self.reason.currentText().strip()
            if not reason:
                raise ValueError("اكتب سبب الإشعار الدائن (إلزامي)")
            rets = self._returns()
            if not rets:
                raise ValueError("حدّد طقماً واحداً على الأقل للإرجاع")
            T = self.totals
            pm = self._orig.get("pay_mode") or "credit"
            if not confirm_post(
                    self, f"مرتجع مبيعات (إشعار دائن) على "
                          f"{self._orig['invoice_no']} — "
                          f"{_buyer_label(self._orig)}\n{len(rets)} طقم — "
                          f"الإجمالي {T.text(T.c_total)} ريال — السبب: "
                          f"{reason}\n"
                          + ("يعود الوزن إلى حساب الفاتورة"
                             if self._orig.get("free_lines")
                             else "تعود الأطقم للخزنة")
                          + (f"، ويُردّ المبلغ {tx.PAY_LABEL[pm]}."
                             if pm != "credit" else "."), self.date):
                return
            with db() as conn:
                res = tx.create_credit_note(conn, iid, dstr(self.date), rets,
                                            reason, self.user["username"])
            ref = self._orig["invoice_no"]
            self.reason.setCurrentIndex(-1)
            self.reason.clearEditText()
            self.reload()
            msg = (f"تم ترحيل مرتجع المبيعات {res['invoice_no']} على {ref}"
                   f" — الإجمالي {tk.m(res['grand_total'])} ريال")
            if res.get("voucher_no"):
                msg += (f"\nرُدَّ {tk.m(res['paid'])} ريال بسند الصرف "
                        f"{res['voucher_no']}")
            posted(self, msg, "invoice", res["id"])
        except Exception as e:
            err(self, e)


class SetsRegisterTab(QtWidgets.QWidget):
    """سجل الفواتير الضريبية والمبسطة بالأطقم ومرتجعاتها."""

    COLS = ["", "الرقم", "المستند", "النوع", "التاريخ", "المشتري",
            "التسعير", "الدفع", "الوزن", "الصافي", "الضريبة", "الإجمالي",
            "على الفاتورة"]

    def __init__(self, user):
        super().__init__()
        self.user = user
        self._rows = []
        self.d1 = date_edit()
        today = QtCore.QDate.currentDate()
        self.d1.setDate(QtCore.QDate(today.year(), today.month(), 1))
        self.d2 = date_edit()
        self.q = kit.LineEdit()
        self.q.setPlaceholderText("رقم الفاتورة أو المشتري أو جواله أو رقم "
                                  "التشغيل…")
        self.q.returnPressed.connect(self.reload)
        self.kind = kit.ComboBox()
        self.kind.addItem("فواتير ومرتجعات", None)
        for k, lbl in KIND_LABEL.items():
            self.kind.addItem(lbl, k)
        self.sub = kit.ComboBox()
        self.sub.addItem("ضريبية ومبسطة", None)
        for k, lbl in SUB_SHORT.items():
            self.sub.addItem(lbl, k)
        b = kit.PushButton("عرض")
        b.clicked.connect(self.reload)
        top = QtWidgets.QHBoxLayout()
        for lbl, wd in (("من:", self.d1), ("إلى:", self.d2),
                        ("المستند:", self.kind), ("النوع:", self.sub)):
            top.addWidget(QtWidgets.QLabel(lbl))
            top.addWidget(wd)
        top.addWidget(self.q, 1)
        top.addWidget(b)
        from ui.widgets.common import StatChip as Card
        self.c_n = Card("المستندات", "")
        self.c_base = Card("صافي المبيعات الخاضعة", "بعد المرتجعات")
        self.c_vat = Card("صافي ضريبة المخرجات", "تنتقل للإقرار الضريبي",
                          summary=True)
        self.tbl = make_table()
        self.tbl.setColumnCount(len(self.COLS))
        self.tbl.setHorizontalHeaderLabels(self.COLS)
        fit_columns(self.tbl, [5, 9, 10, 7, 8, 14, 10, 7, 7, 8, 7, 8, 8])
        self.tbl.doubleClicked.connect(guard_click(
            lambda ix: self._preview(ix.row())))
        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(top)
        lay.addLayout(tk.cards(self.c_n, self.c_base, self.c_vat))
        lay.addWidget(self.tbl, 1)

    def reload(self):
        a, b = dstr(self.d1), dstr(self.d2)
        with db(readonly=True) as conn:
            rows = tx.search(conn, self.q.text().strip(), a, b,
                             self.kind.currentData(),
                             subtype=self.sub.currentData())
            tot = tx.totals(conn, a, b)
        self._rows = rows
        t = self.tbl
        t.setRowCount(0)
        t.setRowCount(len(rows))
        red = QtGui.QBrush(QtGui.QColor("#a4262c"))
        for r, s in enumerate(rows):
            ret = s["kind"] == "sale_return"
            # 5.8.0: الصافي الخاضع (بعد الخصم النقدي) — به تُحسب الضريبة
            net = (float(s["total_wages"] or 0) + float(s["gold_value"] or 0)
                   - float(s.get("discount") or 0))
            vals = [s["invoice_no"], KIND_LABEL.get(s["kind"], s["kind"]),
                    SUB_SHORT.get(s.get("tax_subtype") or "", "—"),
                    s["invoice_date"], _buyer_label(s),
                    tx.PRICING_LABEL.get(s["pricing"], "").split(" — ")[0],
                    tx.PAY_LABEL.get(s.get("pay_mode") or "", "—")
                    .split(" — ")[0],
                    tk.w(s["total_weight"]), tk.m(net),
                    tk.m(s["vat_amount"]), tk.m(s["grand_total"]),
                    s["ref_no"] or "—"]
            for c, v in enumerate(vals, 1):
                it = num_item(v) if 8 <= c <= 11 else text_item(v)
                if ret and (8 <= c <= 11 or c == 2):
                    it.setForeground(red)
                t.setItem(r, c, it)
        row_action_buttons(t, len(rows), self._preview, None,
                           edit_tip="معاينة وطباعة")
        for r in range(len(rows)):
            box = t.cellWidget(r, 0)
            bt = box.findChild(QtWidgets.QToolButton) if box else None
            if bt:
                bt.setText("👁")
        tk.fix_rows(t)
        self.c_n.set_value(str(tot["n"]))
        self.c_base.set_value(tk.m(tot["base"]))
        self.c_vat.set_value(tk.m(tot["vat"]))

    def _preview(self, r):
        if not (0 <= r < len(self._rows)):
            return
        try:
            from services import print_manager
            print_manager.preview_document(self, "invoice",
                                           self._rows[r]["id"])
        except Exception as e:
            err(self, e)
