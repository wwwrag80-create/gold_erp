# -*- coding: utf-8 -*-
"""المبيعات الضريبية بالأطقم (5.5) — فاتورةٌ تخرج بها الأطقم من الخزنة.

الإدخال: رقم التشغيل ← العدد ← الوزن المقيد ← الوزن القائم ← الأجر (أو
سعر الطقم) — وEnter يُنزل السطر. والتسعير يُختار في كل فاتورة (الأجر فقط
· جرام + أجر · بالقطعة)، والمحاسبة كلّها في `models.tax_invoices`:

* الفاتورة فاتورة بيعٍ حقيقية: الأطقم تخرج من خزنتها، وتظهر في كشف العميل
  وحركة الطقم والإقرار الضريبي.
* **الإشعار الدائن = مرتجع مبيعات**: يُختار من فاتورةٍ ضريبية سابقة،
  فتعود أطقمه للخزنة ويظهر في كشف الحساب «مرتجع مبيعات» بسعر الأصل.
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
KIND_LABEL = {"sale": "فاتورة ضريبية", "sale_return": "مرتجع مبيعات"}


def _wo_pieces(wo):
    try:
        return max(1, int(wo["pieces"] or 1))
    except (KeyError, IndexError, TypeError, ValueError):
        return 1


class SetsInvoiceTab(QtWidgets.QWidget):
    """فاتورةٌ ضريبية بالأطقم من الخزنة."""

    COLS = ["", "م", "رقم التشغيل", "العدد", "الوزن المقيد", "الوزن القائم",
            "الموديل", "الأجر/جم", "قيمة الذهب", "المصنعية", "الصافي"]

    def __init__(self, user, new_customer=None):
        super().__init__()
        self.user = user
        self._new_customer = new_customer
        self.items = []
        self._wo = None              # الطقم المستدعى في سطر الإدخال
        self._avail18 = 0.0          # الباقي منه في الخزنة (مكافئ 18)
        self._wage18 = 0.0
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self._build_header())
        lay.addWidget(self._build_entry())
        lay.addWidget(self._build_items(), 1)
        self.btn_post = kit.PushButton("✔ ترحيل الفاتورة الضريبية")
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

    # ── ① العميل والتسعير ──
    def _build_header(self):
        box = QtWidgets.QGroupBox("① العميل وطريقة التسعير")
        self.customer = search_combo("اكتب اسم العميل أو الشركة…")
        self.customer.currentIndexChanged.connect(self._on_customer)
        b_new = kit.PushButton("+ عميل جديد")
        b_new.setObjectName("ghost")
        b_new.clicked.connect(self.new_customer)
        self.buyer_lbl = QtWidgets.QLabel("—")
        self.buyer_lbl.setWordWrap(True)
        self.date = date_edit()
        self.pricing = tk.PricingBox()
        self.notes = kit.LineEdit()
        self.notes.setPlaceholderText("البيان (اختياري) — يظهر على الفاتورة")
        crow = QtWidgets.QHBoxLayout()
        crow.addWidget(self.customer, 1)
        crow.addWidget(b_new)
        g = QtWidgets.QGridLayout(box)
        g.setVerticalSpacing(6)
        g.addWidget(QtWidgets.QLabel("العميل:"), 0, 0)
        g.addLayout(crow, 0, 1)
        g.addWidget(QtWidgets.QLabel("نوع الفاتورة:"), 0, 2)
        g.addWidget(self.buyer_lbl, 0, 3)
        g.addWidget(QtWidgets.QLabel("التاريخ:"), 0, 4)
        g.addWidget(self.date, 0, 5)
        g.addWidget(QtWidgets.QLabel("التسعير:"), 1, 0)
        g.addWidget(self.pricing, 1, 1)
        g.addWidget(QtWidgets.QLabel("البيان:"), 1, 2)
        g.addWidget(self.notes, 1, 3, 1, 3)
        g.setColumnStretch(1, 4)
        g.setColumnStretch(3, 3)
        return box

    # ── ② سطر الإدخال ──
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
        self.e_reg.setToolTip("الوزن المقيد — الباقي في الخزنة مقترحاً؛ "
                              "أقلّ منه = بيع جزءٍ من الطقم")
        self.e_reg.valueChanged.connect(self._line_changed)
        self.e_std = kit.LineEdit()
        self.e_std.setReadOnly(True)
        self.e_std.setToolTip("الوزن القائم من بطاقة الطقم (بنسبة المباع)")
        self.e_model = kit.LineEdit()
        self.e_model.setReadOnly(True)
        self.e_model.setPlaceholderText("يُملأ تلقائياً")
        self.e_rate = mspin()
        self.e_rate.valueChanged.connect(self._rate_typed)
        self.e_net = kit.LineEdit()
        self.e_net.setReadOnly(True)
        self.l_rate = tk.sub("الأجر/جم")
        self.btn_add = kit.PushButton("+ إضافة سطر")
        self.btn_add.clicked.connect(self.add_item)
        fields = [("رقم التشغيل", self.e_wo, 3), ("العدد", self.e_pieces, 1),
                  ("الوزن المقيد", self.e_reg, 2),
                  ("الوزن القائم", self.e_std, 2),
                  ("الموديل", self.e_model, 2), (None, self.e_rate, 2),
                  ("صافي السطر", self.e_net, 2)]
        g = QtWidgets.QGridLayout(box)
        g.setHorizontalSpacing(6)
        for c, (label, wd, st) in enumerate(fields):
            wd.setMinimumWidth(92)
            g.addWidget(self.l_rate if label is None else tk.sub(label), 0, c)
            g.addWidget(wd, 1, c)
            g.setColumnStretch(c, st)
        g.addWidget(self.btn_add, 1, len(fields))
        enter_chain(self, [self.e_wo, self.e_pieces, self.e_reg, self.e_rate],
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
        fit_columns(self.tbl, [8, 4, 12, 6, 10, 10, 10, 9, 10, 10, 11])
        self.totals = tk.TotalsRow("ضريبة المخرجات")
        self.hint = QtWidgets.QLabel("")
        self.hint.setObjectName("cardSub")
        self.hint.setWordWrap(True)
        v = QtWidgets.QVBoxLayout(box)
        v.addWidget(self.tbl, 1)
        v.addWidget(self.hint)
        v.addWidget(self.totals)
        return box

    # ── الأطراف ──
    def new_customer(self):
        if self._new_customer is None:
            return
        cid = self._new_customer(self)
        if cid:
            self.reload()
            i = self.customer.findData(cid)
            if i >= 0:
                self.customer.setCurrentIndex(i)

    def _on_customer(self, *_):
        from services.fatoora import profile as pf
        cid = self.customer.currentData()
        if cid is None:
            self.buyer_lbl.setText("—")
            return
        try:
            with db(readonly=True) as conn:
                b = pf.buyer(conn, cid) or {}
            self.buyer_lbl.setText(
                f"✔ فاتورة ضريبية — الرقم الضريبي {b['vat']}"
                if pf.buyer_is_b2b(b) else
                "⚠ بلا رقم ضريبي — تصدر «فاتورة ضريبية مبسطة»")
        except Exception as e:                       # noqa: BLE001
            self.buyer_lbl.setText(str(e))

    # ── التسعير ──
    def _pricing_changed(self):
        piece = self.pricing.is_piece()
        self.l_rate.setText("سعر الطقم (ريال)" if piece else
                            f"الأجر/جم ({kv.label()})")
        self.e_rate.blockSignals(True)
        self.e_rate.setValue(0 if piece else kv.rate(self._wage18))
        self.e_rate.blockSignals(False)
        hdr = list(self.COLS)
        hdr[7] = "سعر الطقم" if piece else "الأجر/جم"
        self.tbl.setHorizontalHeaderLabels(hdr)
        self._line_changed()
        self._render()

    # ── سطر الإدخال ──
    def _clear_entry(self):
        self._wo = None
        self._avail18 = 0.0
        self._wage18 = 0.0
        for f in (self.e_wo, self.e_std, self.e_model, self.e_net):
            f.clear()
        self.e_pieces.setValue(1)
        for sp in (self.e_reg, self.e_rate):
            sp.blockSignals(True)
            sp.setValue(0)
            sp.blockSignals(False)

    def _lookup(self):
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
        self.e_reg.setValue(kv.g(avail))
        self.e_reg.blockSignals(False)
        if not self.pricing.is_piece():
            self.e_rate.blockSignals(True)
            self.e_rate.setValue(kv.rate(self._wage18))
            self.e_rate.blockSignals(False)
        self._line_changed()

    def _w18(self):
        """وزن السطر بمكافئ 18 — الباقي كما خُزِّن إن لم يُغيَّر."""
        v = self.e_reg.value()
        if self._avail18 and abs(v - kv.g(self._avail18)) <= 0.0051:
            return self._avail18
        return kv.store(v)

    def _rate_typed(self, *_):
        if not self.pricing.is_piece():
            self._wage18 = kv.rate_store(self.e_rate.value())
        self._line_changed()

    def _std18(self, wo, w18):
        full = float(wo["registered_weight"] or 0)
        std = float(wo["standing_gold"] or 0)
        if wo.get("bulk") or full <= 0:
            return w18
        return round(std * w18 / full, 3)

    def _line_changed(self, *_):
        if self._wo is None:
            self.e_net.clear()
            self.e_std.clear()
            return
        w18 = self._w18()
        self.e_std.setText(tk.w(self._std18(self._wo, w18)))
        t, _why = self.pricing.preview()
        piece = self.e_rate.value() if self.pricing.is_piece() else 0
        _wg, _gv, net, why = tk.line_calc(w18, self._wage18, piece, t)
        self.e_net.setText(tk.m(net) if not why else "—")
        self.e_net.setToolTip(why)

    def add_item(self):
        if self._wo is None:
            self._lookup()
        if self._wo is None:
            return False
        w18 = self._w18()
        if w18 <= 0:
            err(self, "اكتب الوزن المقيد")
            return False
        if not self._wo["bulk"] and w18 > self._avail18 + 0.0005:
            err(self, f"الوزن أكبر من الباقي في الخزنة "
                      f"({tk.w(self._avail18)})")
            return False
        if self.pricing.is_piece() and self.e_rate.value() <= 0:
            err(self, "اكتب سعر الطقم بالريال")
            self.e_rate.setFocus()
            return False
        self.items.append({
            "wo_id": self._wo["id"], "wo_no": self._wo["work_order_no"],
            "model": self.e_model.text(), "bulk": self._wo["bulk"],
            "pieces": self.e_pieces.value(), "w18": w18,
            "avail18": self._avail18,
            "std18": self._std18(self._wo, w18), "wage18": self._wage18,
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
        self.e_wo.setText(it["wo_no"])
        self.e_model.setText(it["model"])
        self.e_pieces.setValue(int(it["pieces"]))
        self.e_reg.blockSignals(True)
        self.e_reg.setValue(kv.g(it["w18"]))
        self.e_reg.blockSignals(False)
        self.e_rate.blockSignals(True)
        self.e_rate.setValue(it["piece_price"] if self.pricing.is_piece()
                             else kv.rate(it["wage18"]))
        self.e_rate.blockSignals(False)
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
            wg, gv, net, why = tk.line_calc(it["w18"], it["wage18"],
                                            it["piece_price"], tp)
            if why:
                bad.append(f"{it['wo_no']}: {why}")
            tw += it["w18"]
            tgv += gv
            twg += wg
            npcs += int(it["pieces"])
            vals = [r + 1, it["wo_no"], str(it["pieces"]), tk.w(it["w18"]),
                    tk.w(it["std18"]), it["model"] or "—",
                    tk.m(it["piece_price"]) if piece
                    else tk.m(kv.rate(it["wage18"])),
                    tk.m(gv) if riyal else "—", tk.m(wg),
                    tk.m(net) if not why else "—"]
            for c, v in enumerate(vals, 1):
                cell = (text_item(v) if c in (2, 6) else num_item(v))
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
            "الذهب يُقيَّد على العميل وزناً، والضريبة على الأجور وحدها"
            if not riyal else
            "الفاتورة كلها بالريال — قيمة الذهب والمصنعية خاضعتان للضريبة"))

    # ── الترحيل ──
    def clear(self):
        self.items = []
        self.notes.clear()
        self._clear_entry()
        self._render()

    def post(self):
        try:
            cid = self.customer.currentData()
            if cid is None:
                raise ValueError("اختر العميل")
            if self.e_wo.text().strip() and self._wo is not None:
                if not self.add_item():
                    return
            if not self.items:
                raise ValueError("أضف رقم تشغيلٍ واحداً على الأقل")
            t = self.pricing.checked()
            for it in self.items:
                _a, _b, _n, why = tk.line_calc(it["w18"], it["wage18"],
                                               it["piece_price"], t)
                if why:
                    raise ValueError(why)
            T = self.totals
            if not confirm_post(
                    self, f"فاتورة ضريبية باسم «{self.customer.currentText()}»"
                    f" — {self.pricing.label()}\n{len(self.items)} طقم · "
                    f"الصافي {T.text(T.c_net)} + الضريبة {T.text(T.c_vat)} = "
                    f"{T.text(T.c_total)} ريال\nالأطقم تخرج من الخزنة.",
                    self.date):
                return
            v = self.pricing.values()
            cart = [{"work_order_id": it["wo_id"], "weight": it["w18"],
                     "wage_override": it["wage18"],
                     "piece_price": it["piece_price"],
                     "pieces": it["pieces"], "karat": int(kv.active())}
                    for it in self.items]
            with db() as conn:
                res = tx.create_invoice(
                    conn, cid, cart, dstr(self.date), self.user["username"],
                    v["pricing"], v["gold_price"], v["price_karat"],
                    self.notes.text().strip())
            self.clear()
            msg = (f"تم ترحيل الفاتورة الضريبية {res['invoice_no']} باسم "
                   f"{res['customer_name']} — الإجمالي "
                   f"{tk.m(res['grand_total'])} ريال")
            if res.get("split"):
                msg += (f"\nوالإيطالي بفاتورةٍ مستقلة {res['split']['invoice_no']}"
                        f" — {tk.m(res['split']['grand_total'])} ريال")
            posted(self, msg, "invoice", res["id"])
        except Exception as e:
            err(self, e)

    def reload(self):
        with db(readonly=True) as conn:
            rows = [r for r in entities.list_entities(conn)
                    if r["entity_type"] != "internal"]
        reload_combo(self.customer, rows, lambda r: r["name"])


class SetsCreditTab(QtWidgets.QWidget):
    """الإشعار الدائن = مرتجع مبيعات من فاتورةٍ ضريبية بالأطقم."""

    COLS = ["", "رقم التشغيل", "العدد", "المباع", "الباقي", "الوزن القائم",
            "الموديل", "المرتجع", "صافي المرتجع"]

    def __init__(self, user):
        super().__init__()
        self.user = user
        self._rows = []
        self._spins = []
        self._orig = None
        self.inv = search_combo("اكتب رقم الفاتورة أو اسم العميل…")
        self.inv.currentIndexChanged.connect(self._load)
        self.date = date_edit()
        self.reason = kit.ComboBox()
        self.reason.setEditable(True)
        self.reason.addItems(CREDIT_REASONS)
        self.reason.setCurrentIndex(-1)
        self.reason.lineEdit().setPlaceholderText("سبب الإشعار — إلزامي")
        self.info = QtWidgets.QLabel("—")
        self.info.setWordWrap(True)
        head = QtWidgets.QGroupBox("① الفاتورة الضريبية الأصلية")
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
        fit_columns(self.tbl, [5, 13, 7, 11, 11, 11, 11, 15, 13])
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
        return (f"{r['invoice_no']} — {r['customer_name']} — "
                f"{tx.PRICING_LABEL.get(r['pricing'], '')} — "
                f"{tk.m(r['grand_total'])} ريال — {r['invoice_date']}")

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
            info = (f"العميل: {o['customer_name']} · "
                    f"{tx.PRICING_LABEL.get(o['pricing'], '')}"
                    + (f" — سعر الجرام {tk.m(o['gold_price'])} عيار "
                       f"{o['price_karat']}" if o["pricing"] in tx.RIYAL
                       else "")
                    + "\nيُردّ بسعر الفاتورة نفسها، وتعود الأطقم للخزنة،"
                      " ويظهر في كشف الحساب «مرتجع مبيعات».")
        self.info.setText(info)
        t = self.tbl
        t.blockSignals(True)
        t.setRowCount(len(self._rows))
        for r, x in enumerate(self._rows):
            chk = QtWidgets.QTableWidgetItem()
            chk.setFlags(QtCore.Qt.ItemIsUserCheckable
                         | QtCore.Qt.ItemIsEnabled)
            chk.setCheckState(QtCore.Qt.Unchecked)
            t.setItem(r, 0, chk)
            std = (x["standing"] * x["weight"] / x["full"]
                   if x["full"] > 0 else x["weight"])
            vals = [x["wo_no"], str(x["pieces"] or "—"), tk.w(x["weight"]),
                    tk.w(x["left"]), tk.w(std), x["model_no"] or "—"]
            for c, v in enumerate(vals, 1):
                t.setItem(r, c, text_item(v) if c in (1, 6) else num_item(v))
            sp = tk.wspin()
            sp.setMaximum(max(kv.g(x["left"]), 0))
            sp.setEnabled(x["left"] > 0.0005)
            sp.valueChanged.connect(lambda _v, i=r: self._spin_moved(i))
            t.setCellWidget(r, 7, sp)
            t.setItem(r, 8, num_item(""))
            self._spins.append(sp)
        t.blockSignals(False)
        tk.fix_rows(t, 6)
        self._recalc()

    def _checked(self, item):
        if item.column() != 0 or item.row() >= len(self._spins):
            return
        x, sp = self._rows[item.row()], self._spins[item.row()]
        on = item.checkState() == QtCore.Qt.Checked
        sp.blockSignals(True)
        sp.setValue(kv.g(x["left"]) if on else 0)
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
            w18 = (x["left"] if abs(v - kv.g(x["left"])) <= 0.0051
                   else kv.store(v))
            out.append({"item_id": x["item_id"], "weight": w18})
        return out

    def _recalc(self, *_):
        by = {r["item_id"]: r["weight"] for r in self._returns()}
        tw = tgv = twg = 0.0
        n = npcs = 0
        for r, x in enumerate(self._rows):
            w18 = by.get(x["item_id"], 0.0)
            cell = self.tbl.item(r, 8)
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
        self.totals.show_totals(n, npcs, tw, tgv, twg, riyal)

    def post(self):
        try:
            iid = self.inv.currentData()
            if iid is None:
                raise ValueError("اختر الفاتورة الضريبية الأصلية")
            reason = self.reason.currentText().strip()
            if not reason:
                raise ValueError("اكتب سبب الإشعار الدائن (إلزامي)")
            rets = self._returns()
            if not rets:
                raise ValueError("حدّد طقماً واحداً على الأقل للإرجاع")
            T = self.totals
            if not confirm_post(
                    self, f"مرتجع مبيعات (إشعار دائن) على "
                          f"{self._orig['invoice_no']}\n{len(rets)} طقم — "
                          f"الإجمالي {T.text(T.c_total)} ريال — السبب: "
                          f"{reason}\nتعود الأطقم للخزنة.", self.date):
                return
            with db() as conn:
                res = tx.create_credit_note(conn, iid, dstr(self.date), rets,
                                            reason, self.user["username"])
            self.reason.setCurrentIndex(-1)
            self.reason.clearEditText()
            self.reload()
            posted(self, f"تم ترحيل مرتجع المبيعات {res['invoice_no']} على "
                         f"{self._label_no(iid)} — الإجمالي "
                         f"{tk.m(res['grand_total'])} ريال",
                   "invoice", res["id"])
        except Exception as e:
            err(self, e)

    @staticmethod
    def _label_no(iid):
        with db(readonly=True) as conn:
            r = conn.execute("SELECT invoice_no FROM invoices WHERE id=?",
                             (iid,)).fetchone()
        return r[0] if r else ""


class SetsRegisterTab(QtWidgets.QWidget):
    """سجل الفواتير الضريبية بالأطقم ومرتجعاتها."""

    COLS = ["", "الرقم", "النوع", "التاريخ", "العميل", "التسعير", "الوزن",
            "قيمة الذهب", "المصنعية", "الضريبة", "الإجمالي", "على الفاتورة"]

    def __init__(self, user):
        super().__init__()
        self.user = user
        self._rows = []
        self.d1 = date_edit()
        today = QtCore.QDate.currentDate()
        self.d1.setDate(QtCore.QDate(today.year(), today.month(), 1))
        self.d2 = date_edit()
        self.q = kit.LineEdit()
        self.q.setPlaceholderText("رقم الفاتورة أو العميل أو رقم التشغيل…")
        self.q.returnPressed.connect(self.reload)
        self.kind = kit.ComboBox()
        self.kind.addItem("الكل", None)
        for k, lbl in KIND_LABEL.items():
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
        from ui.widgets.common import StatChip as Card
        self.c_n = Card("المستندات", "")
        self.c_base = Card("صافي المبيعات الخاضعة", "بعد المرتجعات")
        self.c_vat = Card("صافي ضريبة المخرجات", "تنتقل للإقرار الضريبي",
                          summary=True)
        self.tbl = make_table()
        self.tbl.setColumnCount(len(self.COLS))
        self.tbl.setHorizontalHeaderLabels(self.COLS)
        fit_columns(self.tbl, [5, 9, 9, 8, 14, 11, 7, 8, 8, 7, 8, 8])
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
                             self.kind.currentData())
            tot = tx.totals(conn, a, b)
        self._rows = rows
        t = self.tbl
        t.setRowCount(len(rows))
        red = QtGui.QBrush(QtGui.QColor("#a4262c"))
        for r, s in enumerate(rows):
            ret = s["kind"] == "sale_return"
            riyal = s["pricing"] in tx.RIYAL
            vals = [s["invoice_no"], KIND_LABEL.get(s["kind"], s["kind"]),
                    s["invoice_date"], s["customer_name"],
                    tx.PRICING_LABEL.get(s["pricing"], ""),
                    tk.w(s["total_weight"]),
                    tk.m(s["gold_value"]) if riyal else "—",
                    tk.m(s["total_wages"]), tk.m(s["vat_amount"]),
                    tk.m(s["grand_total"]), s["ref_no"] or "—"]
            for c, v in enumerate(vals, 1):
                it = num_item(v) if 6 <= c <= 10 else text_item(v)
                if ret and (6 <= c <= 10 or c == 2):
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
