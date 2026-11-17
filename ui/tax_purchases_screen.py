# -*- coding: utf-8 -*-
"""شاشة المشتريات الضريبية (5.5) — شراء أطقمٍ بفاتورةٍ ضريبية تدخل الخزنة.

كشاشة المبيعات الضريبية تماماً: رقم التشغيل ← العدد ← الوزن ← العيار ←
الأجر (أو سعر الطقم)، والتسعير يُختار في كل فاتورة. الوزن وزن الذهب
المقيد وحده بعيار السطر (5.5.1). والمحاسبة
في `models.set_purchases`:

* الأطقم تدخل الخزنة ببطاقاتها (والرقمان التجميعيان إلى حساب الإيطالي).
* ضريبة المدخلات تُقيَّد في حسابها وتنتقل للإقرار الضريبي.
* **مرتجع المشتريات** من فاتورةٍ بعينها: الطقم يُرجع ما دام في الخزنة
  بوزنه كله، ويظهر في كشف المورد «مرتجع مشتريات».
* 5.8.2: **المشتريات العامة** (مصروفات وأصول — كانت شاشةً مستقلة) قسمٌ
  هنا، والسجل يجمع الذهب والمشتريات العامة كلها كما في الإقرار. وطريقة
  الدفع في فاتورة الذهب تُكتب عليها فقط — والسداد بسند صرفٍ يدوي.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from ui import kit

from database.database import db
from models import entities, inventory
from models import set_purchases as sp
from models import tax_invoices as tx
from services import karat_view as kv
from ui import tax_trade_kit as tk
from ui.widgets.common import StatChip as Card
from ui.widgets.common import (confirm_post, date_edit, dstr, enter_chain,
                               err, guard_click, load_pref, make_table, mspin,
                               num_item, posted, reload_combo,
                               row_action_buttons, save_pref, search_combo,
                               tab_widget, text_item, title_label)
from ui.widgets.table_fit import fit_columns

MODE_PREF = "tax_purchase_line_mode"   # 5.8.0: آخر مصدرٍ اختاره المستخدم
RETURN_REASONS = ("عيبٌ في الطقم", "اختلاف الوزن عن الفاتورة",
                  "إلغاء جزئي للشراء", "إرجاع الفاتورة كاملة")


def _parties(conn):
    return [r for r in entities.list_entities(conn)
            if r["entity_type"] != "internal"]


class PurchaseInvoiceTab(QtWidgets.QWidget):
    # 5.5.2: لا عمود «مصنعية» (الصافي يغني عنه) — وسعر الجرام لكل سطر
    # 5.8.1: «رقم الباركود/الصنف» بدل رقم التشغيل، ولا عمود موديل
    COLS = ["", "م", tk.ITEM_NO, "العدد", "الوزن", "العيار",
            "سعر الجرام", "الأجر/جم", "قيمة الذهب", "الصافي"]
    C_GP, C_RATE, C_GV, C_NET = 6, 7, 8, 9

    def __init__(self, user):
        super().__init__()
        self.user = user
        self.items = []
        self._wage18 = 0.0
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 0, 4, 4)
        lay.setSpacing(6)
        lay.addWidget(self._build_header())
        lay.addWidget(self._build_entry())
        lay.addWidget(self._build_items(), 1)
        self.btn_post = kit.PushButton("✔ ترحيل فاتورة المشتريات الضريبية")
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
        self.src_mode.set_mode(str(load_pref(MODE_PREF, "free") or "free"))
        self.src_mode.changed.connect(self._mode_changed)
        self._pricing_changed()

    # ══════════ المصدر: يدوي حر · أطقم الخزنة (5.8.0) ══════════
    def _free(self):
        return self.src_mode.is_free()

    def _mode_changed(self):
        save_pref(MODE_PREF, self.src_mode.mode(), self.user.get("username"))
        self.items = []
        self._clear_entry()
        with db(readonly=True) as conn:
            self._reload_dest(conn)
        self._render()

    def _show_balance(self):
        if not self._free() or self.dest.currentData() is None:
            self.dest_bal.setText("")
            return
        try:
            with db(readonly=True) as conn:
                self.dest_bal.setText(tk.balance_text(
                    conn, self.dest.currentData()))
        except Exception:                            # noqa: BLE001
            self.dest_bal.setText("")

    def _build_header(self):
        box = tk.section("① بيانات الفاتورة")
        self.supplier = search_combo("اكتب اسم المورد…")
        b_new = kit.PushButton("+ جديد")
        b_new.setObjectName("ghost")
        b_new.setToolTip("مورد جديد في دليل جهات التعامل")
        b_new.clicked.connect(self.new_supplier)
        self.sup_inv = kit.LineEdit()
        self.sup_inv.setPlaceholderText("إلزامي")
        self.date = date_edit()
        self.pricing = tk.PricingBox(with_price=False)
        # 5.8.2: الدفع «آجل» أو صندوقٌ/بنك — يُكتب على الفاتورة فقط، والسداد
        # بسند صرفٍ يدوي من «سندات قبض/صرف»
        self.pay = tk.PayCombo("آجل — على حساب المورد",
                               username=self.user.get("username", ""))
        # «حساب المخزون»: الحساب الذي يدخله وزن الفاتورة (ومنه يخرج)
        self.dest = kit.ComboBox()
        self.dest.setToolTip("الحساب الذي يدخله وزن هذه الفاتورة — ومنه "
                             "يخرج عند بيعه")
        self.dest.currentIndexChanged.connect(self._dest_changed)
        b_acc = kit.PushButton("+")
        b_acc.setObjectName("ghost")
        b_acc.setToolTip("حساب مخزونٍ جديد")
        b_acc.clicked.connect(self.new_account)
        self.notes = kit.LineEdit()
        self.notes.setPlaceholderText("اختياري")
        # 5.8.0: يدوي حر (افتراضي) أو أطقمٌ تدخل الخزنة ببطاقاتها
        self.src_mode = tk.ModeBox("إلى أطقم الخزنة")
        self.dest_bal = QtWidgets.QLabel("")
        self.dest_bal.setObjectName("cardSub")
        self.disc = tk.discount_spin()
        self.disc.setToolTip("خصمٌ نقدي من المورد على الفاتورة كلها (ريال) — "
                             "يُطرح من الصافي قبل الضريبة")
        self.disc.valueChanged.connect(lambda *_: self._render())
        dest_f = tk.field("حساب المخزون", tk.hbox(self.dest, b_acc))
        dest_f.layout().addWidget(self.dest_bal)
        r1 = tk.hbox(tk.field("المورد", tk.hbox(self.supplier, b_new)),
                     tk.field("رقم فاتورة المورد", self.sup_inv),
                     tk.field("التاريخ", self.date),
                     tk.field("الدفع", self.pay), stretch=[5, 2, 1, 3])
        r2 = tk.hbox(tk.field("طريقة التسعير", self.pricing),
                     tk.field("الأصناف", self.src_mode), dest_f,
                     tk.field("خصم نقدي (ريال)", self.disc),
                     tk.field("ملاحظات", self.notes),
                     stretch=[3, 3, 3, 1, 2])
        v = QtWidgets.QVBoxLayout(box)
        v.setSpacing(6)
        v.addLayout(r1)
        v.addLayout(r2)
        return box

    # ── «إلى حساب» ──
    def _dest_pref(self):
        return ("tax_purchase_dest_free" if self._free()
                else "tax_purchase_dest")

    def _reload_dest(self, conn, want=None):
        from models import tax_free
        keep = want if want is not None else (
            str(load_pref(self._dest_pref(), "")).strip())
        self.dest.blockSignals(True)
        self.dest.clear()
        rows = (tax_free.stock_accounts(conn) if self._free()
                else sp.dest_accounts(conn))
        for r in rows:
            self.dest.addItem(f"{r['code']} — {r['name']}", int(r["id"]))
        i = -1
        if keep:
            i = self.dest.findData(int(keep)) if str(keep).isdigit() else -1
            if i < 0:
                i = next((j for j in range(self.dest.count())
                          if self.dest.itemText(j).startswith(f"{keep} ")),
                         -1)
        if i < 0:
            first = tax_free.TAX_STOCK if self._free() else "1200"
            i = next((j for j in range(self.dest.count())
                      if self.dest.itemText(j).startswith(f"{first} ")), 0)
        self.dest.setCurrentIndex(i)
        self.dest.blockSignals(False)
        self._show_balance()

    def _dest_changed(self, *_):
        if self.dest.currentData():
            save_pref(self._dest_pref(), str(self.dest.currentData()),
                      self.user.get("username"))
        self._show_balance()

    def new_account(self):
        from ui.sales_screen import NewSourceDialog
        dlg = NewSourceDialog(self, self.user["username"])
        dlg.setWindowTitle("حساب جديد تدخله الأطقم")
        dlg.name.setPlaceholderText("مثال: الألماس · ذهب مشغول المعرض")
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            with db(readonly=True) as conn:
                self._reload_dest(conn, dlg.account_id)
            self._dest_changed()

    def _build_entry(self):
        box = tk.section("② إدخال الصنف كما في فاتورة المورد")
        self.e_wo = kit.LineEdit()
        self.e_wo.setPlaceholderText("الرقم كما في فاتورة المورد")
        self.e_wo.editingFinished.connect(self._check_no)
        self.e_pieces = kit.SpinBox()
        self.e_pieces.setRange(1, 999)
        self.e_pieces.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.e_pieces.setAlignment(QtCore.Qt.AlignCenter)
        self.e_reg = tk.wspin()
        self.e_reg.setToolTip("وزن الذهب المقيد كما في فاتورة المورد — "
                              "بالعيار المختار بجانبه")
        self.e_reg.valueChanged.connect(self._line_changed)
        # 5.8.1: لا خانة موديل — يبقى الحقل مخفياً للتوافق
        self.e_model = kit.LineEdit()
        self.e_model.setVisible(False)
        self.e_karat = tk.karat_combo()
        self.e_karat.currentIndexChanged.connect(self._rate_typed)
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
        fields = [(tk.ITEM_NO, self.e_wo, 4), ("العدد", self.e_pieces, 1),
                  ("الوزن", self.e_reg, 2), ("العيار", self.e_karat, 2),
                  ("gp", self.e_gp, 2), (None, self.e_rate, 2),
                  ("صافي السطر", self.e_net, 2)]
        g = QtWidgets.QGridLayout(box)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(2)
        # عمود «سعر الجرام» يُطوى مع خانته في «الأجر فقط» — فلا فجوة
        self._egrid, self._gp_col = g, 4
        for c, (label, wd, st) in enumerate(fields):
            wd.setMinimumWidth(88)
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
        box = tk.section("③ أصناف الفاتورة")
        self.tbl = make_table()
        self.tbl.setColumnCount(len(self.COLS))
        self.tbl.setHorizontalHeaderLabels(self.COLS)
        self.tbl.setMinimumHeight(220)
        fit_columns(self.tbl, [8, 4, 16, 6, 10, 7, 10, 10, 11, 12])
        self.totals = tk.TotalsRow("ضريبة المدخلات", "تُخصم في الإقرار")
        self.hint = QtWidgets.QLabel("")
        self.hint.setObjectName("cardSub")
        self.hint.setWordWrap(True)
        v = QtWidgets.QVBoxLayout(box)
        v.addWidget(self.tbl, 1)
        v.addWidget(self.hint)
        v.addWidget(self.totals)
        return box

    def new_supplier(self):
        from ui.tax_sales_screen import NewCustomerDialog
        dlg = NewCustomerDialog(self, self.user["username"], "supplier")
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self.reload()
            i = self.supplier.findData(dlg.customer_id)
            if i >= 0:
                self.supplier.setCurrentIndex(i)

    def _k(self):
        return int(self.e_karat.currentData() or kv.active())

    def _pricing_changed(self):
        piece, riyal = self.pricing.is_piece(), self.pricing.is_riyal()
        self.l_rate.setText("سعر الطقم (ريال)" if piece else "الأجر/جم")
        self.l_gp.setVisible(riyal)
        self.e_gp.setVisible(riyal)
        self._egrid.setColumnStretch(self._gp_col, 2 if riyal else 0)
        self.l_gp.setText("سعر الجرام" + (" (للفصل)" if piece else ""))
        hdr = list(self.COLS)
        hdr[self.C_RATE] = "سعر الطقم" if piece else "الأجر/جم"
        self.tbl.setHorizontalHeaderLabels(hdr)
        self.tbl.setColumnHidden(self.C_GP, not riyal)
        self.tbl.setColumnHidden(self.C_GV, not riyal)
        self._rate_typed()
        self._render()

    def _line_pricing(self, gold_price=None, karat=None):
        return tk.line_pricing(
            self.pricing.pricing(),
            self.e_gp.value() if gold_price is None else gold_price,
            self._k() if karat is None else karat)

    def _check_no(self):
        no = self.e_wo.text().strip()
        if self._free() or not no or inventory.is_bulk_no(no):
            return                   # الحر: الرقم وصفٌ — ولو تكرّر
        if any(x["wo_no"] == no for x in self.items):
            err(self, f"الرقم {no} مكرّر في الفاتورة")
            self.e_wo.selectAll()
            return
        with db(readonly=True) as conn:
            have = inventory.get_wo_by_no(conn, no)
        if have is not None:
            err(self, f"الرقم {no} موجود في خزنتك من قبل — لكل طقمٍ "
                      "رقمه")
            self.e_wo.selectAll()

    def _rate_typed(self, *_):
        if not self.pricing.is_piece():
            self._wage18 = kv.rate_store(self.e_rate.value(), self._k())
        self._line_changed()

    def _w18(self, sp_):
        return kv.store(sp_.value(), self._k())

    def _line_changed(self, *_):
        if self.e_reg.value() <= 0:
            self.e_net.clear()
            return
        t = self._line_pricing()
        piece = self.e_rate.value() if self.pricing.is_piece() else 0
        _a, _b, net, why = tk.line_calc(self._w18(self.e_reg), self._wage18,
                                        piece, t)
        self.e_net.setText(tk.m(net) if not why else "—")
        self.e_net.setToolTip(why)

    def _clear_entry(self):
        self.e_wo.clear()
        self.e_model.clear()
        self.e_net.clear()
        self.e_pieces.setValue(1)
        for s in (self.e_reg, self.e_rate):
            s.blockSignals(True)
            s.setValue(0)
            s.blockSignals(False)
        self._wage18 = 0.0

    def add_item(self):
        no = self.e_wo.text().strip()
        if not no:
            return False
        try:
            if not self._free() and not inventory.is_bulk_no(no):
                if any(x["wo_no"] == no for x in self.items):
                    raise ValueError(f"الرقم {no} مكرّر في الفاتورة")
                with db(readonly=True) as conn:
                    if inventory.get_wo_by_no(conn, no) is not None:
                        raise ValueError(f"الرقم {no} موجود في خزنتك"
                                         " من قبل — لكل طقمٍ رقمه")
            reg = self._w18(self.e_reg)
            if reg <= 0:
                raise ValueError("اكتب الوزن")
            if self.pricing.is_riyal() and self.e_gp.value() <= 0:
                self.e_gp.setFocus()
                raise ValueError(f"اكتب سعر الجرام (عيار {self._k()})")
            if self.pricing.is_piece() and self.e_rate.value() <= 0:
                raise ValueError("اكتب سعر الطقم بالريال")
        except ValueError as e:
            err(self, e)
            return False
        self.items.append({
            "wo_no": no, "pieces": self.e_pieces.value(), "reg18": reg,
            "model": self.e_model.text().strip(),
            "karat": self._k(), "wage18": self._wage18,
            "gold_price": (self.e_gp.value() if self.pricing.is_riyal()
                           else 0.0),
            "piece_price": (self.e_rate.value() if self.pricing.is_piece()
                            else 0.0)})
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
        self.e_wo.setText(it["wo_no"])
        self.e_pieces.setValue(int(it["pieces"]))
        tk.set_karat(self.e_karat, it["karat"])
        self.e_model.setText(it["model"])
        for s, v in ((self.e_reg, kv.g(it["reg18"], it["karat"])),
                     (self.e_rate, it["piece_price"] if self.pricing.is_piece()
                      else kv.rate(it["wage18"], it["karat"]))):
            s.blockSignals(True)
            s.setValue(v)
            s.blockSignals(False)
        self._wage18 = it["wage18"]
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
            wg, gv, net, why = tk.line_calc(it["reg18"], it["wage18"],
                                            it["piece_price"], tp)
            if why:
                bad.append(f"{it['wo_no']}: {why}")
            tw += it["reg18"]
            tgv += gv
            twg += wg
            npcs += int(it["pieces"])
            k = it["karat"]
            vals = [r + 1, it["wo_no"], str(it["pieces"]),
                    tk.wk(it["reg18"], k), str(k),
                    tk.m(it.get("gold_price") or 0) if riyal else "—",
                    tk.m(it["piece_price"]) if piece
                    else tk.m(kv.rate(it["wage18"], k)),
                    tk.m(gv) if riyal else "—",
                    tk.m(net) if not why else "—"]
            for c, v in enumerate(vals, 1):
                cell = text_item(v) if c == 2 else num_item(v)
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
            "الذهب يُقيَّد للمورد وزناً، والضريبة على الأجور وحدها"
            if not riyal else
            "الفاتورة كلها بالريال: الصافي = الوزن × (سعر الجرام + الأجر)"
            " — والضريبة عليه كله" if not piece else
            "الفاتورة كلها بالريال: الصافي سعر الطقم — والضريبة عليه كله"))

    def clear(self):
        self.items = []
        self.sup_inv.clear()
        self.notes.clear()
        self.disc.blockSignals(True)
        self.disc.setValue(0)
        self.disc.blockSignals(False)
        self._show_balance()
        self._clear_entry()
        self._render()

    def post(self):
        try:
            sid = self.supplier.currentData()
            if sid is None:
                raise ValueError("اختر المورد")
            if not self.sup_inv.text().strip():
                raise ValueError("اكتب رقم فاتورة المورد — بها تُخصم ضريبة "
                                 "المدخلات")
            if self.e_wo.text().strip() and self.e_reg.value() > 0:
                if not self.add_item():
                    return
            if not self.items:
                raise ValueError("أضف طقماً واحداً على الأقل")
            for it in self.items:
                t = self._line_pricing(it.get("gold_price") or 0, it["karat"])
                why = tk.line_calc(it["reg18"], it["wage18"],
                                   it["piece_price"], t)[3]
                if why:
                    raise ValueError(f"{it['wo_no']}: {why}")
            if self.dest.currentData() is None:
                raise ValueError("اختر الحساب الذي تدخله الأطقم («إلى حساب»)")
            T = self.totals
            free = self._free()
            disc = self.disc.value()
            pay, pay_acc = self.pay.pay()
            pay_txt = self.pay.text()
            if not confirm_post(
                    self, f"فاتورة مشتريات ضريبية من «"
                          f"{self.supplier.currentText()}» رقم "
                          f"{self.sup_inv.text().strip()} — "
                          f"{self.pricing.label()} · الدفع: {pay_txt}\n"
                          f"{len(self.items)} صنف · "
                          f"الصافي {T.text(T.c_net)}"
                          + (f" (بعد خصم {tk.m(disc)})" if disc else "")
                          + f" + ضريبة المدخلات {T.text(T.c_vat)} = "
                          f"{T.text(T.c_total)} ريال\n"
                          + (f"الوزن يدخل «{self.dest.currentText()}» "
                             "(إدخال يدوي — بلا بطاقات أطقم)." if free else
                             f"الأطقم تدخل «{self.dest.currentText()}»."),
                    self.date):
                return
            v = self.pricing.values()
            if self.pricing.is_riyal():
                # سعر الفاتورة سعرُ أول سطر — ولكل سطرٍ سعره بعياره
                v["gold_price"] = self.items[0]["gold_price"]
                v["price_karat"] = self.items[0]["karat"]
            lines = [{"wo_no": it["wo_no"], "model_no": it["model"],
                      "pieces": it["pieces"], "registered": it["reg18"],
                      "standing": it["reg18"], "karat": it["karat"],
                      "wage": it["wage18"], "piece_price": it["piece_price"],
                      "gold_price": it.get("gold_price") or 0}
                     for it in self.items]
            with db() as conn:
                res = sp.create_purchase(
                    conn, sid, dstr(self.date), self.sup_inv.text().strip(),
                    lines, self.user["username"], v["pricing"],
                    v["gold_price"], v["price_karat"], self.notes.text(),
                    dest_account_id=self.dest.currentData(),
                    mode=self.src_mode.mode(), discount=disc,
                    pay_mode=pay, pay_account_id=pay_acc)
            self.clear()
            msg = (f"تم ترحيل فاتورة المشتريات {res['doc_no']} من "
                   f"{res['supplier_name']} — {res['n']} صنف\n"
                   f"الإجمالي {tk.m(res['total'])} ريال (ضريبة المدخلات "
                   f"{tk.m(res['vat'])})")
            if pay != "credit":
                msg += (f"\nالدفع: {pay_txt} — سجّل الصرف من «سندات قبض/صرف»")
            if not res.get("vat_number_set"):
                msg += ("\n⚠ رقمك الضريبي غير مسجّل في بيانات المنشأة — "
                        "سجّله لتُخصم ضريبة المدخلات في الإقرار")
            posted(self, msg, "set_purchase", res["id"])
        except Exception as e:
            err(self, e)

    def reload(self):
        with db(readonly=True) as conn:
            rows = _parties(conn)
            self._reload_dest(conn)
            self.pay.reload(conn)
        reload_combo(self.supplier, rows, lambda r: r["name"])


class PurchaseReturnTab(QtWidgets.QWidget):
    # 5.8.1: «رقم الباركود/الصنف» ولا موديل — ونوع التسعير وسعر السطر
    COLS = ["", tk.ITEM_NO, "العدد", "الوزن", "العيار", "نوع التسعير",
            "السعر", "الحالة", "وزن المرتجع", "صافي المرتجع"]
    C_SPIN, C_NET = 8, 9

    def __init__(self, user):
        super().__init__()
        self.user = user
        self._rows, self._spins, self._orig = [], [], None
        self.doc = search_combo("اكتب رقم الفاتورة أو المورد…")
        self.doc.currentIndexChanged.connect(self._load)
        self.date = date_edit()
        self.reason = kit.ComboBox()
        self.reason.setEditable(True)
        self.reason.addItems(RETURN_REASONS)
        self.reason.setCurrentIndex(-1)
        self.reason.lineEdit().setPlaceholderText("سبب المرتجع — إلزامي")
        self.info = QtWidgets.QLabel("—")
        self.info.setObjectName("cardSub")
        self.info.setWordWrap(True)
        head = tk.section("① فاتورة المشتريات الأصلية")
        hv = QtWidgets.QVBoxLayout(head)
        hv.setSpacing(6)
        hv.addLayout(tk.hbox(tk.field("الفاتورة", self.doc),
                             tk.field("تاريخ المرتجع", self.date),
                             tk.field("سبب المرتجع", self.reason),
                             stretch=[5, 1, 3]))
        hv.addWidget(self.info)
        self.tbl = make_table()
        self.tbl.setColumnCount(len(self.COLS))
        self.tbl.setHorizontalHeaderLabels(self.COLS)
        self.tbl.setMinimumHeight(220)
        fit_columns(self.tbl, [4, 13, 5, 8, 6, 10, 15, 13, 11, 10])
        self.tbl.itemChanged.connect(self._checked)
        lines = tk.section("② الأصناف المرتجعة للمورد")
        bl = QtWidgets.QVBoxLayout(lines)
        bl.addWidget(self.tbl, 1)
        self.totals = tk.TotalsRow("ضريبة المدخلات المردودة")
        btn = kit.PushButton("✔ ترحيل مرتجع المشتريات")
        btn.setMinimumHeight(40)
        btn.clicked.connect(self.post)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 0, 4, 4)
        lay.setSpacing(6)
        lay.addWidget(head)
        lay.addWidget(lines, 1)
        lay.addWidget(self.totals)
        lay.addWidget(btn)

    @staticmethod
    def _label(r):
        return (f"{r['doc_no']} — {r['supplier_name']} — فاتورة المورد "
                f"{r['supplier_inv_no']} — {tk.m(r['total'])} ريال — "
                f"{r['doc_date']}")

    def reload(self):
        with db(readonly=True) as conn:
            rows = sp.open_purchases(conn)
        reload_combo(self.doc, rows, self._label)
        self._load()

    def _load(self, *_):
        did = self.doc.currentData()
        self._rows, self._spins, self._orig = [], [], None
        info = "—"
        if did is not None:
            with db(readonly=True) as conn:
                self._orig = sp.get(conn, did)
                self._rows = sp.returnable(conn, did)
            o = self._orig
            free = bool(o.get("free_lines"))
            disc = float(o.get("discount") or 0)
            from models.accounts import pay_label
            with db(readonly=True) as conn:
                ptxt = pay_label(conn, o.get("pay_mode") or "credit",
                                 o.get("pay_account_id"))
            info = (f"المورد: {o['supplier_name']} · نوع التسعير: "
                    f"{tx.PRICING_LABEL.get(o['pricing'], '')}"
                    + f" · الدفع: {ptxt}"
                    + (f" · خصم الأصل {tk.m(disc)} — يُردّ منه بنسبة المرتجع"
                       if disc else "")
                    + ("\nيُرجع من كل سطرٍ ما بقي من وزنه (كله أو جزءٌ منه)"
                       if free else
                       "\nالطقم يُرجع كاملاً ما دام في الخزنة بوزنه كله")
                    + " — ويظهر في كشف المورد «مرتجع مشتريات ضريبي»"
                    + ("." if (o.get("pay_mode") or "credit") == "credit"
                       else " — والاسترداد النقدي بسند قبضٍ يدوي."))
        self.info.setText(info)
        t = self.tbl
        t.blockSignals(True)
        t.setRowCount(len(self._rows))
        for r, x in enumerate(self._rows):
            ok = x["left"] > 0.0005
            chk = QtWidgets.QTableWidgetItem()
            chk.setFlags((QtCore.Qt.ItemIsUserCheckable
                          | QtCore.Qt.ItemIsEnabled) if ok
                         else QtCore.Qt.NoItemFlags)
            chk.setCheckState(QtCore.Qt.Unchecked)
            t.setItem(r, 0, chk)
            k = int(x["karat"] or kv.active())
            kind, price = self._price_txt(x, k)
            free = bool(x.get("free"))
            state = x["why"] or (("يُرجع منه حتى " + tk.wk(x["left"], k))
                                 if free and ok else
                                 "في الخزنة — يُرجع" if ok else "—")
            vals = [x["wo_no"], str(x["pieces"] or "—"),
                    tk.wk(x["registered"], k), str(k), kind, price, state]
            for c, v in enumerate(vals, 1):
                t.setItem(r, c, text_item(v) if c in (1, 5, 6, 7)
                          else num_item(v))
            s = tk.wspin()
            s.setMaximum(max(kv.g(x["left"], k), 0))
            # الطقم المفرد يُرجع كاملاً — والتجميعي والحر بوزنٍ يُكتب
            s.setEnabled(ok and (x["bulk"] or free))
            s.setToolTip("وزن المرتجع بعيار السطر")
            s.valueChanged.connect(lambda _v, i=r: self._spin_moved(i))
            t.setCellWidget(r, self.C_SPIN, s)
            t.setItem(r, self.C_NET, num_item(""))
            self._spins.append(s)
        t.blockSignals(False)
        tk.fix_rows(t, 6)
        self._recalc()

    def _price_txt(self, x, k):
        """(نوع التسعير، السعر كما اشتُري) لسطر الفاتورة الأصلية."""
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

    def _spin_moved(self, r):
        it = self.tbl.item(r, 0)
        if it is not None and (it.flags() & QtCore.Qt.ItemIsEnabled):
            self.tbl.blockSignals(True)
            it.setCheckState(QtCore.Qt.Checked if self._spins[r].value() > 0
                             else QtCore.Qt.Unchecked)
            self.tbl.blockSignals(False)
        self._recalc()

    def _checked(self, item):
        if item.column() != 0 or item.row() >= len(self._spins):
            return
        x, s = self._rows[item.row()], self._spins[item.row()]
        s.blockSignals(True)
        k = int(x["karat"] or kv.active())
        s.setValue(kv.g(x["left"], k)
                   if item.checkState() == QtCore.Qt.Checked else 0)
        s.blockSignals(False)
        self._recalc()

    def _returns(self):
        out = []
        for r, (x, s) in enumerate(zip(self._rows, self._spins)):
            it = self.tbl.item(r, 0)
            if it is None or it.checkState() != QtCore.Qt.Checked:
                continue
            if x["bulk"] or x.get("free"):
                v = s.value()
                if v <= 0:
                    continue
                k = int(x["karat"] or kv.active())
                w18 = (x["left"] if abs(v - kv.g(x["left"], k)) <= 0.0051
                       else kv.store(v, k))
                out.append({"line_id": x["line_id"], "weight": w18})
            else:
                out.append({"line_id": x["line_id"], "weight": None})
        return out

    def _recalc(self, *_):
        o = self._orig
        t = None
        if o:
            t = tx.norm({"pricing": o["pricing"],
                         "gold_price": o["gold_price"],
                         "price_karat": o["price_karat"]})
        by = {r["line_id"]: r["weight"] for r in self._returns()}
        tw = tgv = twg = 0.0
        n = npcs = 0
        for r, x in enumerate(self._rows):
            cell = self.tbl.item(r, self.C_NET)
            if x["line_id"] not in by or t is None:
                if cell:
                    cell.setText("")
                continue
            w18 = by[x["line_id"]] or x["left"]
            frac = w18 / x["registered"] if x["registered"] else 1.0
            wg, gv, net, _why = tk.line_calc(
                w18, x["wage"], (x["piece_price"] or 0) * frac, t)
            tw += w18
            tgv += gv
            twg += wg
            n += 1
            npcs += int(x["pieces"] or 0) if frac >= 0.999 else 0
            if cell:
                cell.setText(tk.m(net))
        disc = 0.0
        if o and float(o.get("discount") or 0) > 0:
            from models import tax_free
            disc = tax_free.share(o["discount"], round(tgv + twg, 2),
                                  float(o.get("net") or 0))
        self.totals.show_totals(n, npcs, tw, tgv, twg,
                                bool(o and o["pricing"] in tx.RIYAL), disc)

    def post(self):
        try:
            did = self.doc.currentData()
            if did is None:
                raise ValueError("اختر فاتورة المشتريات الأصلية")
            reason = self.reason.currentText().strip()
            if not reason:
                raise ValueError("اكتب سبب المرتجع (إلزامي)")
            rets = self._returns()
            if not rets:
                raise ValueError("حدّد طقماً واحداً على الأقل للإرجاع")
            T = self.totals
            if not confirm_post(
                    self, f"مرتجع مشتريات على {self._orig['doc_no']} — "
                          f"{self._orig['supplier_name']}\n{len(rets)} صنف — "
                          f"الإجمالي {T.text(T.c_total)} ريال — السبب: "
                          f"{reason}\n"
                          + ("يخرج الوزن للمورد."
                             if self._orig.get("free_lines") else
                             "تخرج الأطقم من الخزنة للمورد."),
                    self.date):
                return
            with db() as conn:
                res = sp.create_return(conn, did, dstr(self.date), rets,
                                       reason, self.user["username"])
            self.reason.setCurrentIndex(-1)
            self.reason.clearEditText()
            self.reload()
            posted(self, f"تم ترحيل مرتجع المشتريات {res['doc_no']} إلى "
                         f"{res['supplier_name']} — الإجمالي "
                         f"{tk.m(res['total'])} ريال",
                   "set_purchase", res["id"])
        except Exception as e:
            err(self, e)


class PurchaseRegisterTab(QtWidgets.QWidget):
    """سجل المشتريات الضريبية (5.8.2): الذهب والمشتريات العامة ومرتجعاتهما
    — فترةٌ بزر (شهري · ربع سنوي · سنوي · من تاريخ إلى تاريخ) والبحث في كل
    الفترات، وأعمدته:
    رقم الفاتورة · التاريخ · النوع · المورد · الوزن · الأجور · الخصم ·
    الضريبة · الإجمالي — وبجانبه «عرض»."""
    COLS = ["رقم الفاتورة", "التاريخ", "النوع", "المورد", "فاتورة المورد",
            "الوزن", "الأجور / المبلغ", "قيمة الذهب", "الخصم", "الضريبة",
            "الإجمالي", ""]
    C_GV, C_VIEW = 7, 11

    def __init__(self, user):
        super().__init__()
        from ui.widgets.common import live_search
        self.user = user
        self._rows = []
        self.period = tk.PeriodBar("tax_purchase_reg_period")
        self.period.changed.connect(self.reload)
        self.q = kit.LineEdit()
        self.q.setPlaceholderText("بحث في كل الفترات: رقم الفاتورة · فاتورة"
                                  " المورد · المورد · رقم الباركود/الصنف…")
        live_search(self.q, self.reload)
        # 5.8.3: «بحث» يعرض كل السندات في كل الفترات حسب الاختيارات
        self.b_search = tk.search_button()
        self.b_search.clicked.connect(self.search_all)
        self.q.returnPressed.connect(self.search_all)
        self.kind = kit.ComboBox()
        for k, lbl in sp.REG_KINDS:
            self.kind.addItem(lbl, k or None)
        self.kind.currentIndexChanged.connect(lambda *_: self.reload())
        self.empty = QtWidgets.QLabel("")
        self.empty.setObjectName("cardSub")
        self.c_n = Card("المستندات", "")
        self.c_base = Card("صافي المشتريات الخاضعة", "بعد المرتجعات والخصم")
        self.c_vat = Card("ضريبة المدخلات القابلة للخصم",
                          "تنتقل للإقرار الضريبي")
        self.c_total = Card("الإجمالي شامل الضريبة", "", summary=True)
        self.tbl = make_table()
        self.tbl.setColumnCount(len(self.COLS))
        self.tbl.setHorizontalHeaderLabels(self.COLS)
        fit_columns(self.tbl, [9, 8, 12, 13, 8, 7, 9, 8, 7, 8, 9, 6])
        self.tbl.doubleClicked.connect(guard_click(
            lambda ix: self._preview(ix.row())))
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 0, 4, 4)
        lay.setSpacing(6)
        lay.addLayout(tk.hbox(self.period, self.q, self.kind, self.b_search,
                              stretch=[0, 3, 1, 0]))
        lay.addLayout(tk.cards(self.c_n, self.c_base, self.c_vat,
                               self.c_total))
        lay.addWidget(self.empty)
        lay.addWidget(self.tbl, 1)

    def search_all(self):
        """كل السندات في كل الفترات — بالنوع المختار وما كُتب في البحث."""
        if self.period.mode != "all":
            self.period.set_mode("all")          # يعيد التحميل
        else:
            self.reload()

    def reload(self, *_):
        q = self.q.text().strip()
        a, b = (("0000-01-01", "9999-12-31") if q else self.period.range())
        with db(readonly=True) as conn:
            rows = sp.tax_register(conn, a, b, q, self.kind.currentData())
        self._rows = rows
        t = self.tbl
        t.setRowCount(0)
        t.setRowCount(len(rows) + (1 if rows else 0))
        red = QtGui.QBrush(QtGui.QColor("#a4262c"))
        tot = {"w": 0.0, "wg": 0.0, "gv": 0.0, "d": 0.0, "v": 0.0, "t": 0.0,
               "base": 0.0, "claim": 0.0}
        any_gv = False
        for r, s in enumerate(rows):
            ret = s["ret"]
            sg = -1 if ret else 1
            any_gv = any_gv or s["gold_value"] > 0
            for k, key in (("w", "weight"), ("wg", "wages"),
                           ("gv", "gold_value"), ("d", "discount"),
                           ("v", "vat"), ("t", "total"), ("base", "base"),
                           ("claim", "claim")):
                tot[k] += sg * float(s.get(key) or 0)
            vals = [s["no"], s["date"], s["kind_label"], s["party"],
                    s["sup_inv"] or "—",
                    tk.w(s["weight"]) if s["weight"] is not None else "—",
                    tk.m(s["wages"]),
                    tk.m(s["gold_value"]) if s["gold_value"] else "—",
                    tk.m(s["discount"]) if s["discount"] else "—",
                    tk.m(s["vat"]), tk.m(s["total"])]
            for c, v in enumerate(vals):
                it = num_item(v) if c >= 5 else text_item(v)
                if ret and (c >= 5 or c == 2):
                    it.setForeground(red)
                tip = s.get("description") or (
                    f"على الفاتورة {s['ref_no']}" if s.get("ref_no") else "")
                if tip and c in (0, 2):
                    it.setToolTip(tip)
                t.setItem(r, c, it)
        tk.view_buttons(t, self.C_VIEW, len(rows), self._preview)
        if rows:
            from ui.widgets.common import style_total_row
            n = len(rows)
            vals = ["الإجمالي", "", f"{n} مستند", "", "", tk.w(tot["w"]),
                    tk.m(tot["wg"]), tk.m(tot["gv"]) if any_gv else "—",
                    tk.m(tot["d"]), tk.m(tot["v"]), tk.m(tot["t"]), ""]
            for c, v in enumerate(vals):
                t.setItem(n, c, num_item(v) if c >= 5 else text_item(v))
            style_total_row(t, n)
        t.setColumnHidden(self.C_GV, not any_gv)
        tk.fix_rows(t, 4)
        self.c_n.set_value(str(len(rows)),
                           f"نتائج البحث «{q}» في كل الفترات" if q
                           else self.period.title())
        self.c_base.set_value(tk.m(tot["base"]))
        self.c_vat.set_value(tk.m(tot["claim"]))
        self.c_total.set_value(tk.m(tot["t"]))
        self.empty.setText("" if rows else (
            f"لا نتائج لـ«{q}»." if q else
            "لا مستندات بهذه الاختيارات في كل الفترات." if
            self.period.mode == "all" else
            f"لا مستندات في {self.period.title()} — اختر «سنوي» أو فترةً "
            "أخرى بالسهمين، أو اضغط «🔍 بحث» لكل السندات في كل الفترات."))
        self.empty.setVisible(not rows)

    def _preview(self, r):
        if not (0 <= r < len(self._rows)):
            return
        try:
            from services import print_manager
            row = self._rows[r]
            print_manager.preview_document(
                self, "set_purchase" if row["src"] == "set_purchases"
                else "purchase", row["id"])
        except Exception as e:
            err(self, e)


def _general_purchases(user):
    """شاشة المشتريات العامة (مصروفات وأصول) قسماً هنا — بلا عنوانها
    الكبير (العنوان للشاشة الأم)."""
    from ui.purchases_screen import PurchasesScreen
    w = PurchasesScreen(user)
    for lbl in w.findChildren(QtWidgets.QLabel):
        if lbl.objectName() == "title":
            lbl.setVisible(False)
            break
    return w


class TaxPurchasesScreen(QtWidgets.QWidget):
    """المشتريات الضريبية: فاتورة ذهب · مرتجع مشتريات · المشتريات العامة
    (مصروفات وأصول — 5.8.2: كانت شاشةً مستقلة) · السجل."""

    def __init__(self, user):
        super().__init__()
        from ui.widgets.lazy_tabs import LazyTabs
        self.user = user
        self.tabs = tab_widget()
        # 5.6.0: التبويب يُبنى عند أول فتحٍ له — فتُفتح الشاشة أسرع
        self._lazy = LazyTabs(self.tabs)
        self._lazy.add("🧾  فاتورة مشتريات ذهب",
                       lambda: PurchaseInvoiceTab(user), wrap=tk.scroll)
        self._lazy.add("↩  مرتجع مشتريات", lambda: PurchaseReturnTab(user),
                       wrap=tk.scroll)
        # 5.8.2: المشتريات العامة قسمٌ من هذه الشاشة (لم تعد شاشةً مستقلة)
        self._gen = self.tabs.count()
        self._lazy.add("🛒  المشتريات العامة (مصروفات وأصول)",
                       lambda: _general_purchases(user), wrap=tk.scroll)
        self._reg = self.tabs.count()
        self._lazy.add("☰  السجل", lambda: PurchaseRegisterTab(user))
        self.tabs.currentChanged.connect(lambda _i: self.refresh())
        lay = QtWidgets.QVBoxLayout(self)
        lay.setSpacing(4)
        lay.addWidget(title_label("المشتريات الضريبية"))
        lay.addWidget(self.tabs, 1)
        self.refresh()

    @property
    def inv_tab(self):
        return self._lazy.get(0)

    @property
    def ret_tab(self):
        return self._lazy.get(1)

    @property
    def gen_tab(self):
        return self._lazy.get(self._gen) if self._gen is not None else None

    @property
    def reg_tab(self):
        return self._lazy.get(self._reg)

    def load_document(self, source_id):
        """فتح فاتورة مشتريات عامة للتعديل (من الكشوف وسجل التعديل)."""
        if self._gen is None:
            return
        self.tabs.setCurrentIndex(self._gen)
        w = self.gen_tab
        if w is not None and hasattr(w, "load_document"):
            w.load_document(source_id)

    def refresh(self):
        w = self._lazy.current()
        try:
            if w is None:
                return
            if hasattr(w, "reload"):
                w.reload()
            elif hasattr(w, "refresh"):
                w.refresh()
        except Exception as e:                       # noqa: BLE001
            err(self, e)
