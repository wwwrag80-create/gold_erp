# -*- coding: utf-8 -*-
"""أدوات الشاشتين الضريبيتين بالأطقم (5.5): المبيعات والمشتريات.

الشاشتان تتشاركان طريقة التسعير وحساب السطر والبطاقات — فيُكتب ذلك هنا
مرةً واحدة، ويبقى الحساب نفسه الذي يرحّله الدفتر (`models.tax_invoices`):

* **الأجر فقط**: الذهب بالوزن، والضريبة على الأجور.
* **جرام + أجر**: الوزن × (سعر الجرام + الأجر) — كلّه بالريال، والضريبة
  على الإجمالي.
* **بالقطعة**: سعر الطقم بالريال — والضريبة على الإجمالي، وسعر الجرام
  يفصل قيمة الذهب عن المصنعية في الدفتر.

الأوزان والأجور تُعرض بعيار العرض (`karat_view`) وتُخزَّن بمكافئ 18.
"""
from PyQt5 import QtCore, QtWidgets

from ui import kit

import config
from models import tax_invoices as tx
from services import karat_view as kv
from services import numfmt as _nf
from ui.widgets.common import StatChip as Card
from ui.widgets.common import mspin, row_height
from ui.widgets.table_fit import fit_columns

KARATS = (18, 21, 22, 24)


def m(v):
    return _nf.f2(float(v or 0))


def w(v18):
    return _nf.f2(kv.g(v18))


def scroll(widget):
    sa = QtWidgets.QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QtWidgets.QFrame.NoFrame)
    sa.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    sa.setWidget(widget)
    return sa


def sub(text):
    lbl = QtWidgets.QLabel(text)
    lbl.setObjectName("cardSub")
    lbl.setAlignment(QtCore.Qt.AlignCenter)
    return lbl


def cards(*items):
    row = QtWidgets.QHBoxLayout()
    for c in items:
        row.addWidget(c, 1)
    return row


def fix_rows(t, extra=0):
    t.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
    t.verticalHeader().setDefaultSectionSize(row_height(t) + extra)
    fit_columns(t)


def karat_combo():
    """خانة عيار السطر — الوزن والأجر/جم يُكتبان ويُعرضان به."""
    cb = kit.ComboBox()
    for k in KARATS:
        cb.addItem(f"عيار {k}", k)
    set_karat(cb, kv.active())
    return cb


def set_karat(cb, k):
    i = cb.findData(int(k or kv.active()))
    cb.blockSignals(True)
    cb.setCurrentIndex(i if i >= 0 else 0)
    cb.blockSignals(False)


def wk(v18, karat):
    """الوزن بعيار السطر (المخزَّن بمكافئ 18)."""
    return _nf.f2(kv.g(v18, int(karat or kv.active())))


def wspin():
    """خانة وزنٍ بمنزلتين (بعيار العرض)."""
    sp = mspin(maximum=1_000_000.0)
    sp.setDecimals(2)
    return sp


class PricingBox(QtWidgets.QWidget):
    """طريقة التسعير وسعر الجرام وعياره — تُختار في كل فاتورة.

    `changed` تُطلق عند أي تغيير فيُعاد حساب الأسطر."""
    changed = QtCore.pyqtSignal()

    def __init__(self, parent=None, with_price=True):
        super().__init__(parent)
        # 5.5.2: سعر الجرام صار في سطر الإدخال (لكل طقمٍ بعياره) — فالرأس
        # يحمل طريقة التسعير وحدها (`with_price=False`)
        self.with_price = bool(with_price)
        self.mode = kit.ComboBox()
        for key, label in tx.TAX_PRICING:
            self.mode.addItem(label, key)
        self.mode.setToolTip(
            "الأجر فقط: الذهب يُقيَّد وزناً والضريبة على الأجور\n"
            "جرام + أجر: الوزن × (سعر الجرام + الأجر) بالريال — الضريبة على"
            " الإجمالي\nبالقطعة: سعر الطقم بالريال — الضريبة على الإجمالي")
        self.price = mspin()
        self.price.setToolTip("سعر جرام الذهب بالعيار المختار بجانبه — به "
                              "تُحسب قيمة الذهب بالريال")
        self.karat = kit.ComboBox()
        for k in KARATS:
            self.karat.addItem(f"عيار {k}", k)
        i = self.karat.findData(int(kv.active()))
        self.karat.setCurrentIndex(i if i >= 0 else 0)
        self.l_price = QtWidgets.QLabel("سعر الجرام:")
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.mode, 3)
        lay.addWidget(self.l_price)
        lay.addWidget(self.price, 2)
        lay.addWidget(self.karat, 1)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.price.valueChanged.connect(lambda *_: self.changed.emit())
        self.karat.currentIndexChanged.connect(lambda *_: self.changed.emit())
        self._mode_changed()

    def _mode_changed(self, *_):
        riyal = self.pricing() in tx.RIYAL and self.with_price
        for wd in (self.l_price, self.price, self.karat):
            wd.setVisible(riyal)
        self.changed.emit()

    def pricing(self):
        return self.mode.currentData() or "wage"

    def is_piece(self):
        return self.pricing() == "piece"

    def is_riyal(self):
        return self.pricing() in tx.RIYAL

    def values(self):
        """{pricing, gold_price, price_karat} كما يُرسل للدفتر."""
        return {"pricing": self.pricing(),
                "gold_price": self.price.value() if self.is_riyal() else 0.0,
                "price_karat": (int(self.karat.currentData() or 18)
                                if self.is_riyal() else 0)}

    def checked(self):
        """التسعير مُتحقَّقاً — أو ValueError برسالةٍ واضحة."""
        return tx.norm(self.values())

    def preview(self):
        """للعرض: التسعير ولو بلا سعر جرامٍ بعد (قيمة الذهب صفر)."""
        try:
            return tx.norm(self.values()), ""
        except ValueError as e:
            v = self.values()
            return ({"pricing": v["pricing"], "gold_price": 0.0,
                     "price_karat": v["price_karat"] or 18,
                     "ref_invoice_id": None, "reason": ""}, str(e))

    def set_values(self, pricing, gold_price=0.0, karat=0):
        i = self.mode.findData(pricing or "wage")
        self.mode.setCurrentIndex(i if i >= 0 else 0)
        self.price.setValue(float(gold_price or 0))
        j = self.karat.findData(int(karat or kv.active()))
        if j >= 0:
            self.karat.setCurrentIndex(j)

    def label(self):
        p = self.values()
        if p["pricing"] in tx.RIYAL and self.with_price:
            return (f"{tx.PRICING_LABEL[p['pricing']]} — سعر الجرام "
                    f"{m(p['gold_price'])} عيار {p['price_karat']}")
        return tx.PRICING_LABEL[p["pricing"]]


def line_pricing(pricing, gold_price=0.0, karat=0):
    """تسعير سطرٍ للعرض: طريقة الفاتورة وسعر جرام السطر بعياره."""
    riyal = pricing in tx.RIYAL
    return {"pricing": pricing,
            "gold_price": float(gold_price or 0) if riyal else 0.0,
            "price_karat": int(karat or kv.active()) if riyal else 0,
            "ref_invoice_id": None, "reason": ""}


def line_calc(weight18, wage18, piece_price, t):
    """(الأجور، قيمة الذهب، الصافي، خطأ) لسطرٍ بتسعير الفاتورة."""
    li = {"weight": float(weight18 or 0), "wage": float(wage18 or 0),
          "piece_price": float(piece_price or 0)}
    try:
        wages, gv = tx.line_amounts(li, t)
        return wages, gv, round(wages + gv, 2), ""
    except ValueError as e:
        try:
            gv = tx.gold_value(li["weight"], t)
        except Exception:                            # noqa: BLE001
            gv = 0.0
        return 0.0, gv, 0.0, str(e)


class TotalsRow(QtWidgets.QWidget):
    """بطاقات المستند: العدد · الوزن · قيمة الذهب · المصنعية · الصافي ·
    الضريبة · الإجمالي — والضريبة على صافي المستند كلّه مرةً واحدة."""

    def __init__(self, vat_title="الضريبة", vat_sub=""):
        super().__init__()
        # العدد والوزن في لوحةٍ واحدة — ست لوحاتٍ تتّسع لشاشة 1366
        self.c_n = Card("الأطقم", "")
        self.c_w = self.c_n
        self.c_gv = Card("قيمة الذهب", "بالريال")
        # 5.5.2: لا لوحة «مصنعية» — الصافي يغني عنها
        self.c_net = Card("الصافي الخاضع", "قبل الضريبة")
        self.c_vat = Card(f"{vat_title} {config.VAT_RATE * 100:g}%", vat_sub)
        # 5.6.0: الإجمالي شامل الضريبة هو الرقم البارز — لا الضريبة
        self.c_total = Card("الإجمالي شامل الضريبة", "", summary=True)
        lay = cards(self.c_n, self.c_gv, self.c_net, self.c_vat,
                    self.c_total)
        lay.setContentsMargins(0, 0, 0, 0)
        self.setLayout(lay)

    def show_totals(self, n, pieces, weight18, gv, wages, riyal):
        net = round(gv + wages, 2)
        vat = tx.doc_vat(net)
        self.c_n.set_value(
            str(n), f"{w(weight18)} {kv.unit()}"
            + (f" · {pieces} قطعة" if pieces else "")
            + ("" if riyal else " — ذهبٌ بالوزن"))
        self.c_gv.set_value(m(gv) if riyal else "—")
        self.c_gv.setVisible(riyal)
        self.c_net.set_value(m(net))
        self.c_vat.set_value(m(vat))
        self.c_total.set_value(m(net + vat))
        return net, vat, round(net + vat, 2)

    def text(self, card):
        return card.value_lbl.text()
