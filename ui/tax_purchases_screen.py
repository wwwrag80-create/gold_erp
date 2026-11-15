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
                               err, guard_click, make_table, mspin, num_item,
                               posted, reload_combo, row_action_buttons,
                               search_combo, tab_widget, text_item,
                               title_label)
from ui.widgets.table_fit import fit_columns

RETURN_REASONS = ("عيبٌ في الطقم", "اختلاف الوزن عن الفاتورة",
                  "إلغاء جزئي للشراء", "إرجاع الفاتورة كاملة")


def _parties(conn):
    return [r for r in entities.list_entities(conn)
            if r["entity_type"] != "internal"]


class PurchaseInvoiceTab(QtWidgets.QWidget):
    COLS = ["", "م", "رقم التشغيل", "العدد", "الوزن", "العيار", "الموديل",
            "الأجر/جم", "قيمة الذهب", "المصنعية", "الصافي"]

    def __init__(self, user):
        super().__init__()
        self.user = user
        self.items = []
        self._wage18 = 0.0
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self._build_header())
        lay.addWidget(self._build_entry())
        lay.addWidget(self._build_items(), 1)
        self.btn_post = kit.PushButton("✔ ترحيل فاتورة المشتريات الضريبية")
        self.btn_post.clicked.connect(self.post)
        b_clear = kit.PushButton("تفريغ")
        b_clear.setObjectName("ghost")
        b_clear.clicked.connect(self.clear)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.btn_post, 1)
        row.addWidget(b_clear)
        lay.addLayout(row)
        self.pricing.changed.connect(self._pricing_changed)
        self._pricing_changed()

    def _build_header(self):
        box = QtWidgets.QGroupBox("① المورد وفاتورته وطريقة التسعير")
        self.supplier = search_combo("اكتب اسم المورد…")
        b_new = kit.PushButton("+ مورد جديد")
        b_new.setObjectName("ghost")
        b_new.clicked.connect(self.new_supplier)
        self.sup_inv = kit.LineEdit()
        self.sup_inv.setPlaceholderText("رقم فاتورة المورد — إلزامي")
        self.date = date_edit()
        self.pricing = tk.PricingBox()
        self.notes = kit.LineEdit()
        self.notes.setPlaceholderText("ملاحظات (اختياري)")
        srow = QtWidgets.QHBoxLayout()
        srow.addWidget(self.supplier, 1)
        srow.addWidget(b_new)
        g = QtWidgets.QGridLayout(box)
        g.setVerticalSpacing(6)
        g.addWidget(QtWidgets.QLabel("المورد:"), 0, 0)
        g.addLayout(srow, 0, 1)
        g.addWidget(QtWidgets.QLabel("رقم فاتورة المورد:"), 0, 2)
        g.addWidget(self.sup_inv, 0, 3)
        g.addWidget(QtWidgets.QLabel("التاريخ:"), 0, 4)
        g.addWidget(self.date, 0, 5)
        g.addWidget(QtWidgets.QLabel("التسعير:"), 1, 0)
        g.addWidget(self.pricing, 1, 1)
        g.addWidget(QtWidgets.QLabel("ملاحظات:"), 1, 2)
        g.addWidget(self.notes, 1, 3, 1, 3)
        g.setColumnStretch(1, 4)
        g.setColumnStretch(3, 3)
        return box

    def _build_entry(self):
        box = QtWidgets.QGroupBox("② إدخال الطقم كما في فاتورة المورد")
        self.e_wo = kit.LineEdit()
        self.e_wo.setPlaceholderText("رقم التشغيل")
        self.e_wo.editingFinished.connect(self._check_no)
        self.e_pieces = kit.SpinBox()
        self.e_pieces.setRange(1, 999)
        self.e_pieces.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.e_pieces.setAlignment(QtCore.Qt.AlignCenter)
        self.e_reg = tk.wspin()
        self.e_reg.setToolTip("وزن الذهب المقيد كما في فاتورة المورد — "
                              "بالعيار المختار بجانبه")
        self.e_reg.valueChanged.connect(self._line_changed)
        self.e_model = kit.LineEdit()
        self.e_model.setPlaceholderText("اختياري")
        self.e_karat = tk.karat_combo()
        self.e_karat.currentIndexChanged.connect(self._rate_typed)
        self.e_rate = mspin()
        self.e_rate.valueChanged.connect(self._rate_typed)
        self.e_net = kit.LineEdit()
        self.e_net.setReadOnly(True)
        self.l_rate = tk.sub("الأجر/جم")
        self.btn_add = kit.PushButton("+ إضافة سطر")
        self.btn_add.clicked.connect(self.add_item)
        fields = [("رقم التشغيل", self.e_wo, 3), ("العدد", self.e_pieces, 1),
                  ("الوزن", self.e_reg, 2), ("العيار", self.e_karat, 2),
                  ("الموديل", self.e_model, 2), (None, self.e_rate, 2),
                  ("صافي السطر", self.e_net, 2)]
        g = QtWidgets.QGridLayout(box)
        g.setHorizontalSpacing(6)
        for c, (label, wd, st) in enumerate(fields):
            wd.setMinimumWidth(88)
            g.addWidget(self.l_rate if label is None else tk.sub(label), 0, c)
            g.addWidget(wd, 1, c)
            g.setColumnStretch(c, st)
        g.addWidget(self.btn_add, 1, len(fields))
        enter_chain(self, [self.e_wo, self.e_pieces, self.e_reg, self.e_karat,
                           self.e_model, self.e_rate],
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
        fit_columns(self.tbl, [8, 4, 11, 6, 9, 9, 9, 6, 9, 9, 9, 10])
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
        piece = self.pricing.is_piece()
        self.l_rate.setText("سعر الطقم (ريال)" if piece else "الأجر/جم")
        hdr = list(self.COLS)
        hdr[7] = "سعر الطقم" if piece else "الأجر/جم"
        self.tbl.setHorizontalHeaderLabels(hdr)
        self._rate_typed()
        self._render()

    def _check_no(self):
        no = self.e_wo.text().strip()
        if not no or inventory.is_bulk_no(no):
            return
        if any(x["wo_no"] == no for x in self.items):
            err(self, f"رقم التشغيل {no} مكرّر في الفاتورة")
            self.e_wo.selectAll()
            return
        with db(readonly=True) as conn:
            have = inventory.get_wo_by_no(conn, no)
        if have is not None:
            err(self, f"رقم التشغيل {no} موجود في خزنتك من قبل — لكل طقمٍ "
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
        t, _why = self.pricing.preview()
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
            if not inventory.is_bulk_no(no):
                if any(x["wo_no"] == no for x in self.items):
                    raise ValueError(f"رقم التشغيل {no} مكرّر في الفاتورة")
                with db(readonly=True) as conn:
                    if inventory.get_wo_by_no(conn, no) is not None:
                        raise ValueError(f"رقم التشغيل {no} موجود في خزنتك"
                                         " من قبل — لكل طقمٍ رقمه")
            reg = self._w18(self.e_reg)
            if reg <= 0:
                raise ValueError("اكتب الوزن")
            if self.pricing.is_piece() and self.e_rate.value() <= 0:
                raise ValueError("اكتب سعر الطقم بالريال")
        except ValueError as e:
            err(self, e)
            return False
        self.items.append({
            "wo_no": no, "pieces": self.e_pieces.value(), "reg18": reg,
            "model": self.e_model.text().strip(),
            "karat": self._k(), "wage18": self._wage18,
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
        self._line_changed()
        self._render()
        self.e_rate.setFocus()
        self.e_rate.selectAll()

    def _render(self):
        t = self.tbl
        # الصفوف تُفرَّغ أولاً فتذهب أزرارها معها — لا تبقى أزرار سطرٍ قديم
        t.setRowCount(0)
        t.setRowCount(len(self.items))
        tp, why_p = self.pricing.preview()
        piece, riyal = self.pricing.is_piece(), self.pricing.is_riyal()
        tw = tgv = twg = 0.0
        npcs = 0
        bad = []
        red = QtGui.QBrush(QtGui.QColor("#a4262c"))
        for r, it in enumerate(self.items):
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
                    tk.wk(it["reg18"], k), str(k), it["model"] or "—",
                    tk.m(it["piece_price"]) if piece
                    else tk.m(kv.rate(it["wage18"], k)),
                    tk.m(gv) if riyal else "—", tk.m(wg),
                    tk.m(net) if not why else "—"]
            for c, v in enumerate(vals, 1):
                cell = text_item(v) if c in (2, 6) else num_item(v)
                if why and c == 10:
                    cell.setForeground(red)
                    cell.setToolTip(why)
                t.setItem(r, c, cell)
        row_action_buttons(t, len(self.items), self._edit, self._del,
                           edit_tip="تصحيح السطر", del_tip="حذف السطر")
        tk.fix_rows(t, 10)
        self.totals.show_totals(len(self.items), npcs, tw, tgv, twg, riyal)
        msgs = ([why_p] if (why_p and self.items) else []) + bad
        self.hint.setText("⚠ " + " · ".join(msgs) if msgs else (
            "الذهب يُقيَّد للمورد وزناً، والضريبة على الأجور وحدها"
            if not riyal else
            "الفاتورة كلها بالريال — قيمة الذهب والمصنعية خاضعتان للضريبة"))

    def clear(self):
        self.items = []
        self.sup_inv.clear()
        self.notes.clear()
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
            t = self.pricing.checked()
            for it in self.items:
                why = tk.line_calc(it["reg18"], it["wage18"],
                                   it["piece_price"], t)[3]
                if why:
                    raise ValueError(why)
            T = self.totals
            if not confirm_post(
                    self, f"فاتورة مشتريات ضريبية من «"
                          f"{self.supplier.currentText()}» رقم "
                          f"{self.sup_inv.text().strip()} — "
                          f"{self.pricing.label()}\n{len(self.items)} طقم · "
                          f"الصافي {T.text(T.c_net)} + ضريبة المدخلات "
                          f"{T.text(T.c_vat)} = {T.text(T.c_total)} ريال\n"
                          "الأطقم تدخل الخزنة.", self.date):
                return
            v = self.pricing.values()
            lines = [{"wo_no": it["wo_no"], "model_no": it["model"],
                      "pieces": it["pieces"], "registered": it["reg18"],
                      "standing": it["reg18"], "karat": it["karat"],
                      "wage": it["wage18"], "piece_price": it["piece_price"]}
                     for it in self.items]
            with db() as conn:
                res = sp.create_purchase(
                    conn, sid, dstr(self.date), self.sup_inv.text().strip(),
                    lines, self.user["username"], v["pricing"],
                    v["gold_price"], v["price_karat"], self.notes.text())
            self.clear()
            msg = (f"تم ترحيل فاتورة المشتريات {res['doc_no']} من "
                   f"{res['supplier_name']} — {res['n']} طقم دخلت الخزنة\n"
                   f"الإجمالي {tk.m(res['total'])} ريال (ضريبة المدخلات "
                   f"{tk.m(res['vat'])})")
            if not res.get("vat_number_set"):
                msg += ("\n⚠ رقمك الضريبي غير مسجّل في بيانات المنشأة — "
                        "سجّله لتُخصم ضريبة المدخلات في الإقرار")
            posted(self, msg, "set_purchase", res["id"])
        except Exception as e:
            err(self, e)

    def reload(self):
        with db(readonly=True) as conn:
            rows = _parties(conn)
        reload_combo(self.supplier, rows, lambda r: r["name"])


class PurchaseReturnTab(QtWidgets.QWidget):
    COLS = ["", "رقم التشغيل", "العدد", "الوزن", "العيار", "الموديل",
            "الحالة", "المرتجع", "صافي المرتجع"]

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
        self.info.setWordWrap(True)
        head = QtWidgets.QGroupBox("① فاتورة المشتريات الأصلية")
        g = QtWidgets.QGridLayout(head)
        g.addWidget(QtWidgets.QLabel("الفاتورة:"), 0, 0)
        g.addWidget(self.doc, 0, 1)
        g.addWidget(QtWidgets.QLabel("تاريخ المرتجع:"), 0, 2)
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
        fit_columns(self.tbl, [5, 12, 6, 10, 10, 10, 18, 14, 12])
        self.tbl.itemChanged.connect(self._checked)
        lines = QtWidgets.QGroupBox("② الأطقم المرتجعة للمورد")
        bl = QtWidgets.QVBoxLayout(lines)
        bl.addWidget(self.tbl, 1)
        self.totals = tk.TotalsRow("ضريبة المدخلات المردودة")
        btn = kit.PushButton("✔ ترحيل مرتجع المشتريات")
        btn.clicked.connect(self.post)
        lay = QtWidgets.QVBoxLayout(self)
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
            info = (f"المورد: {o['supplier_name']} · "
                    f"{tx.PRICING_LABEL.get(o['pricing'], '')}"
                    + (f" — سعر الجرام {tk.m(o['gold_price'])} عيار "
                       f"{o['price_karat']}" if o["pricing"] in tx.RIYAL
                       else "")
                    + "\nالطقم يُرجع كاملاً ما دام في الخزنة بوزنه كله، "
                      "ويظهر في كشف المورد «مرتجع مشتريات».")
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
            vals = [x["wo_no"], str(x["pieces"] or "—"),
                    tk.wk(x["registered"], k), str(k), x["model_no"] or "—",
                    x["why"] or ("في الخزنة — يُرجع" if ok else "—")]
            for c, v in enumerate(vals, 1):
                t.setItem(r, c, text_item(v) if c in (1, 5, 6)
                          else num_item(v))
            s = tk.wspin()
            s.setMaximum(max(kv.g(x["left"], k), 0))
            # الطقم المفرد يُرجع كاملاً — والتجميعي بوزنٍ يُكتب
            s.setEnabled(ok and x["bulk"])
            s.valueChanged.connect(lambda _v, i=r: self._recalc())
            t.setCellWidget(r, 7, s)
            t.setItem(r, 8, num_item(""))
            self._spins.append(s)
        t.blockSignals(False)
        tk.fix_rows(t, 6)
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
            if x["bulk"]:
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
            cell = self.tbl.item(r, 8)
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
        self.totals.show_totals(n, npcs, tw, tgv, twg,
                                bool(o and o["pricing"] in tx.RIYAL))

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
                          f"{self._orig['supplier_name']}\n{len(rets)} طقم — "
                          f"الإجمالي {T.text(T.c_total)} ريال — السبب: "
                          f"{reason}\nتخرج الأطقم من الخزنة للمورد.",
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
                         f"{tk.m(res['total'])} ريال", "set_purchase",
                   res["id"])
        except Exception as e:
            err(self, e)


class PurchaseRegisterTab(QtWidgets.QWidget):
    COLS = ["", "الرقم", "النوع", "التاريخ", "المورد", "فاتورة المورد",
            "التسعير", "الوزن", "قيمة الذهب", "المصنعية", "الضريبة",
            "الإجمالي", "على الفاتورة"]

    def __init__(self, user):
        super().__init__()
        self.user = user
        self._rows = []
        self.d1 = date_edit()
        today = QtCore.QDate.currentDate()
        self.d1.setDate(QtCore.QDate(today.year(), today.month(), 1))
        self.d2 = date_edit()
        self.q = kit.LineEdit()
        self.q.setPlaceholderText("رقم المستند أو فاتورة المورد أو المورد أو"
                                  " رقم التشغيل…")
        self.q.returnPressed.connect(self.reload)
        self.kind = kit.ComboBox()
        self.kind.addItem("الكل", None)
        for k, lbl in sp.KIND_LABEL.items():
            self.kind.addItem(lbl, k)
        b = kit.PushButton("عرض")
        b.clicked.connect(self.reload)
        top = QtWidgets.QHBoxLayout()
        for lbl, wd in (("من:", self.d1), ("إلى:", self.d2),
                        ("النوع:", self.kind)):
            top.addWidget(QtWidgets.QLabel(lbl))
            top.addWidget(wd)
        top.addWidget(self.q, 1)
        top.addWidget(b)
        self.c_n = Card("المستندات", "")
        self.c_base = Card("صافي المشتريات الخاضعة", "بعد المرتجعات")
        self.c_vat = Card("صافي ضريبة المدخلات", "تنتقل للإقرار الضريبي",
                          summary=True)
        self.tbl = make_table()
        self.tbl.setColumnCount(len(self.COLS))
        self.tbl.setHorizontalHeaderLabels(self.COLS)
        fit_columns(self.tbl, [5, 8, 10, 8, 12, 9, 10, 7, 8, 8, 7, 8, 8])
        self.tbl.doubleClicked.connect(guard_click(
            lambda ix: self._preview(ix.row())))
        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(top)
        lay.addLayout(tk.cards(self.c_n, self.c_base, self.c_vat))
        lay.addWidget(self.tbl, 1)

    def reload(self):
        a, b = dstr(self.d1), dstr(self.d2)
        with db(readonly=True) as conn:
            rows = sp.search(conn, self.q.text().strip(), a, b,
                             self.kind.currentData())
            tot = sp.totals(conn, a, b)
        self._rows = rows
        t = self.tbl
        t.setRowCount(len(rows))
        red = QtGui.QBrush(QtGui.QColor("#a4262c"))
        for r, s in enumerate(rows):
            ret = s["kind"] == "purchase_return"
            riyal = s["pricing"] in tx.RIYAL
            vals = [s["doc_no"], sp.KIND_LABEL.get(s["kind"], s["kind"]),
                    s["doc_date"], s["supplier_name"], s["supplier_inv_no"],
                    tx.PRICING_LABEL.get(s["pricing"], ""),
                    tk.w(s["total_weight"]),
                    tk.m(s["gold_value"]) if riyal else "—",
                    tk.m(s["wages"]), tk.m(s["vat"]), tk.m(s["total"]),
                    s["ref_no"] or "—"]
            for c, v in enumerate(vals, 1):
                it = num_item(v) if 7 <= c <= 11 else text_item(v)
                if ret and (7 <= c <= 11 or c == 2):
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
            print_manager.preview_document(self, "set_purchase",
                                           self._rows[r]["id"])
        except Exception as e:
            err(self, e)


class TaxPurchasesScreen(QtWidgets.QWidget):
    """المشتريات الضريبية: فاتورة بالأطقم · مرتجع مشتريات · السجل."""

    def __init__(self, user):
        super().__init__()
        self.user = user
        self.inv_tab = PurchaseInvoiceTab(user)
        self.ret_tab = PurchaseReturnTab(user)
        self.reg_tab = PurchaseRegisterTab(user)
        self.tabs = tab_widget()
        self.tabs.addTab(tk.scroll(self.inv_tab), "فاتورة مشتريات ضريبية")
        self.tabs.addTab(tk.scroll(self.ret_tab), "مرتجع مشتريات")
        self.tabs.addTab(self.reg_tab, "السجل")
        self.tabs.currentChanged.connect(lambda _i: self.refresh())
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("المشتريات الضريبية"))
        lay.addWidget(self.tabs, 1)
        self.refresh()

    def refresh(self):
        w = self.tabs.currentWidget()
        if isinstance(w, QtWidgets.QScrollArea):
            w = w.widget()
        try:
            if w is not None and hasattr(w, "reload"):
                w.reload()
        except Exception as e:                       # noqa: BLE001
            err(self, e)
