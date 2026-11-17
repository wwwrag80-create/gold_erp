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
        self.c_n = Card("الأصناف", "")
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

    def show_totals(self, n, pieces, weight18, gv, wages, riyal,
                    discount=0.0):
        net = round(gv + wages, 2)
        # 5.8.0: الخصم النقدي يُطرح من الوعاء قبل الضريبة
        disc = min(max(0.0, round(float(discount or 0), 2)), net)
        base = round(net - disc, 2)
        vat = tx.doc_vat(base)
        self.c_n.set_value(
            str(n), f"{w(weight18)} {kv.unit()}"
            + (f" · {pieces} قطعة" if pieces else "")
            + ("" if riyal else " — ذهبٌ بالوزن"))
        self.c_gv.set_value(m(gv) if riyal else "—")
        self.c_gv.setVisible(riyal)
        self.c_net.set_value(m(base), (f"{m(net)} − خصم {m(disc)}" if disc
                                       else "قبل الضريبة"))
        self.c_vat.set_value(m(vat))
        self.c_total.set_value(m(base + vat))
        return base, vat, round(base + vat, 2)

    def text(self, card):
        return card.value_lbl.text()


# ══════════════════════════════════════════════════════════════════
#  5.8.0: الإدخال اليدوي الحر · حساب المخزون · الخصم النقدي
# ══════════════════════════════════════════════════════════════════
class ModeBox(QtWidgets.QWidget):
    """مصدر الأسطر: «إدخال يدوي حر» (أي رقم تشغيل بوزنه وعياره — الافتراضي)
    أو «من أطقم الخزنة» (الطريق القديم: الطقم يخرج من خزنتك أو يدخلها)."""
    changed = QtCore.pyqtSignal()

    def __init__(self, vault_text="من أطقم الخزنة", parent=None):
        super().__init__(parent)
        self.b_free = kit.RadioButton("إدخال يدوي حر")
        self.b_free.setToolTip(
            "أي رقم باركود/صنف — ولو تكرّر أو لم يكن عندك — تكتب وزنه وعياره بيدك،"
            "\nويتحرك الوزن في «مخزون الذهب الضريبي» (ويقبل السالب)")
        self.b_vault = kit.RadioButton(vault_text)
        self.b_vault.setToolTip("الطقم الحقيقي في خزنتك برقمه — كما كان")
        g = QtWidgets.QButtonGroup(self)
        g.addButton(self.b_free)
        g.addButton(self.b_vault)
        self.b_free.setChecked(True)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.b_free)
        lay.addSpacing(14)
        lay.addWidget(self.b_vault)
        lay.addStretch(1)
        self.b_free.toggled.connect(lambda *_: self.changed.emit())

    def is_free(self):
        return self.b_free.isChecked()

    def mode(self):
        return "free" if self.is_free() else "vault"

    def set_mode(self, mode):
        (self.b_free if mode != "vault" else self.b_vault).setChecked(True)


def fill_stock_accounts(cb, conn, keep=None):
    """حسابات الإدخال الحر: مخزون الذهب الضريبي أولاً، ثم ما يصلح مثله."""
    from models import tax_free
    cur = keep if keep is not None else cb.currentData()
    cb.blockSignals(True)
    cb.clear()
    for r in tax_free.stock_accounts(conn):
        cb.addItem(f"{r['code']} — {r['name']}", int(r["id"]))
    i = cb.findData(cur) if cur is not None else -1
    cb.setCurrentIndex(i if i >= 0 else 0)
    cb.blockSignals(False)


def discount_spin():
    sp = mspin()
    sp.setToolTip("خصمٌ نقدي على الفاتورة كلها (ريال) — يُطرح من الصافي قبل "
                  "الضريبة، فالضريبة على ما بعد الخصم")
    return sp


def balance_text(conn, account_id):
    """«رصيد الحساب: X جم» — والسالب منبَّهٌ عليه (مسموحٌ به)."""
    from models import tax_free
    try:
        b = tax_free.balance(conn, account_id)
    except Exception:                                # noqa: BLE001
        return ""
    t = f"رصيده الآن: {w(b)} {kv.unit()}"
    return t + (" — سالب (بيعٌ قبل شراء: مسموح)" if b < -0.0005 else "")


# ══════════════════════════════════════════════════════════════════
#  5.8.1: تنسيقٌ واحد للشاشتين — خانةٌ بعنوانٍ فوقها · الدفع من الشجرة ·
#  فترة السجل (شهري · ربع سنوي · سنوي · فترة محددة) · زر «عرض»
# ══════════════════════════════════════════════════════════════════
ITEM_NO = "رقم الباركود/الصنف"          # كان «رقم التشغيل»


def field(caption, widget):
    """خانةٌ بعنوانها الصغير فوقها — كخانات سطر الإدخال تماماً، فيتّسق
    الرأس والسطر ويقصر ارتفاع الشاشة (لا عمود عناوين بجانب الخانات)."""
    w = QtWidgets.QWidget()
    v = QtWidgets.QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(2)
    lbl = QtWidgets.QLabel(caption)
    lbl.setObjectName("cardSub")
    v.addWidget(lbl)
    if isinstance(widget, QtWidgets.QLayout):
        v.addLayout(widget)
    else:
        v.addWidget(widget)
    v.addStretch(1)                  # الخانات تصطفّ من أعلاها في الصف
    w.caption = lbl
    return w


def hbox(*items, stretch=None):
    """صفٌّ أفقي بلا هوامش: عناصرُ وأوزانُ تمدّدها (افتراضاً الأول يتمدّد)."""
    lay = QtWidgets.QHBoxLayout()
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    for i, it in enumerate(items):
        st = (stretch[i] if stretch else (1 if i == 0 else 0))
        if isinstance(it, QtWidgets.QLayout):
            lay.addLayout(it, st)
        else:
            lay.addWidget(it, st)
    return lay


def section(title, dense=True):
    """حاويةٌ بعنوانٍ ذهبي — مدمجة الحشو (الإطار واللون كما هما)."""
    box = QtWidgets.QGroupBox(title)
    if dense:
        box.setProperty("dense", True)
    return box


CREDIT = "credit"


class NewPayAccountDialog(QtWidgets.QDialog):
    """5.8.2: صندوقٌ أو بنكٌ جديد **باسمه** من خانة الدفع نفسها."""

    def __init__(self, parent=None, username="", name=""):
        super().__init__(parent)
        self.setWindowTitle("حساب دفع جديد")
        self.setLayoutDirection(QtCore.Qt.RightToLeft)
        self.username = username
        self.account_id = None
        self.name = kit.LineEdit()
        self.name.setPlaceholderText("مثال: بنك الراجحي · صندوق المعرض")
        self.name.setText(name or "")
        self.b_cash = kit.RadioButton("صندوق نقدي")
        self.b_bank = kit.RadioButton("بنك / شبكة")
        g = QtWidgets.QButtonGroup(self)
        g.addButton(self.b_cash)
        g.addButton(self.b_bank)
        (self.b_bank if "بنك" in (name or "") else self.b_cash).setChecked(
            True)
        ok = kit.PushButton("✔ إضافة")
        ok.clicked.connect(self._save)
        cancel = kit.PushButton("إلغاء")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(field("اسم الحساب", self.name))
        lay.addWidget(field("نوعه", hbox(self.b_cash, self.b_bank,
                                          stretch=[0, 1])))
        note = QtWidgets.QLabel("يُضاف تحت «النقدية وشبه النقدية» في دليل "
                                "الحسابات، ويظهر في كل خانات الدفع وفي "
                                "سندات القبض والصرف.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addLayout(hbox(ok, cancel, stretch=[1, 0]))
        self.resize(420, 220)
        self.name.setFocus()

    def _save(self):
        from database.database import db
        from models.accounts import create_pay_account
        from ui.widgets.common import err
        try:
            with db() as conn:
                self.account_id = create_pay_account(
                    conn, self.name.text(),
                    "cash" if self.b_cash.isChecked() else "bank",
                    self.username)
        except Exception as e:                       # noqa: BLE001
            err(self, e)
            return
        self.accept()


def new_pay_account(parent, username="", name=""):
    """يفتح نافذة الحساب الجديد — ويعيد معرّفه (أو None)."""
    dlg = NewPayAccountDialog(parent, username, name)
    if dlg.exec_() == QtWidgets.QDialog.Accepted:
        return dlg.account_id
    return None


CREDIT = "credit"


def pay_rows_recent(conn):
    """الصناديق والبنوك — آخرها إضافةً أولاً (5.8.3: النقر على الخانة
    يُظهر آخر الحسابات المضافة)."""
    from models.accounts import pay_accounts
    return sorted(pay_accounts(conn), key=lambda r: -int(r["id"]))


def pay_row_label(r):
    from models.accounts import pay_kind
    word = "صندوق" if pay_kind(r["code"]) == "cash" else "بنك"
    return f"{r['name']} ({word})"


def pick_combo(tip=""):
    """قائمةٌ للاختيار فقط (5.8.3) — لا كتابة فيها: النقر عليها يفتحها."""
    cb = kit.ComboBox()          # بسهمها وقائمتها المنبثقة كبقية القوائم
    cb.setEditable(False)
    cb.setMaxVisibleItems(16)
    cb.setCursor(QtCore.Qt.PointingHandCursor)
    cb.setMinimumWidth(170)
    if tip:
        cb.setToolTip(tip)
    return cb


def add_button(tip="صندوق أو بنك جديد — تكتب اسمه فقط، ويُحفظ ويُختار"):
    b = QtWidgets.QToolButton()
    b.setText("+ إضافة")
    b.setObjectName("payAdd")
    b.setCursor(QtCore.Qt.PointingHandCursor)
    b.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
    b.setToolTip(tip)
    return b


class PayCombo(QtWidgets.QWidget):
    """طريقة الدفع (5.8.2): «آجل» ثم الصناديق والبنوك — **اختيارٌ فقط**
    (5.8.3: لا كتابة في الخانة؛ النقر عليها يُظهر الحسابات، آخرها إضافةً
    أولاً)، و«+ إضافة» يُنشئ حساباً جديداً باسمه ويحفظه ويختاره.
    **تُسجَّل على الفاتورة وتُطبع فقط** — لا سند قبضٍ ولا صرفٍ تلقائي؛
    السداد من «سندات قبض/صرف»."""
    changed = QtCore.pyqtSignal()

    def __init__(self, credit_text="آجل — على الحساب", parent=None,
                 username=""):
        super().__init__(parent)
        self.credit_text = credit_text
        self.username = username
        self._allow_credit = True
        self.cb = pick_combo("اختر: آجل أو الصندوق/البنك — تُكتب على الفاتورة"
                             " وتُطبع.\nالسداد نفسه بسندٍ يدوي من «سندات قبض/صرف».")
        self.b_add = add_button()
        self.b_add.clicked.connect(self.add_account)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self.cb, 1)
        lay.addWidget(self.b_add)
        self.cb.currentIndexChanged.connect(lambda *_: self.changed.emit())

    def reload(self, conn, keep=None):
        cur = keep if keep is not None else self.cb.currentData()
        self.cb.blockSignals(True)
        self.cb.clear()
        if self._allow_credit:
            self.cb.addItem(self.credit_text, CREDIT)
        # آخر الحسابات إضافةً أولاً
        for r in pay_rows_recent(conn):
            self.cb.addItem(pay_row_label(r), int(r["id"]))
        i = self.cb.findData(cur) if cur is not None else -1
        self.cb.setCurrentIndex(i if i >= 0 else 0)
        self.cb.blockSignals(False)

    def add_account(self):
        from database.database import db
        aid = new_pay_account(self, self.username, "")
        if aid:
            with db(readonly=True) as conn:
                self.reload(conn, keep=int(aid))
            self.changed.emit()

    def set_allow_credit(self, ok):
        """العميل النقدي يدفع في الحال — لا «آجل» له."""
        ok = bool(ok)
        if ok == self._allow_credit:
            return
        self._allow_credit = ok
        self.cb.blockSignals(True)
        if ok:
            self.cb.insertItem(0, self.credit_text, CREDIT)
        else:
            i = self.cb.findData(CREDIT)
            if i >= 0:
                self.cb.removeItem(i)
            if self.cb.currentIndex() < 0 and self.cb.count():
                self.cb.setCurrentIndex(0)
        self.cb.blockSignals(False)
        self.changed.emit()

    def is_credit(self):
        return self.cb.currentData() in (None, CREDIT)

    def pay(self):
        """(الطريقة، حساب الدفع) كما يُرسل للدفتر — والطريقة يحدّدها
        الدفتر من كود الحساب (صندوق = نقداً · غيره = بنكي)."""
        d = self.cb.currentData()
        if d in (None, CREDIT):
            return CREDIT, None
        return "cash", int(d)

    def text(self):
        return self.cb.currentText() or self.credit_text

    def setFocus(self):
        self.cb.setFocus()


MONTHS = ("يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو",
          "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر")
QUARTERS = ("الربع الأول", "الربع الثاني", "الربع الثالث", "الربع الرابع")


class PeriodBar(QtWidgets.QWidget):
    """فترة السجل بزرٍّ واحد: شهري · ربع سنوي · سنوي · فترة محددة · كل
    الفترات (5.8.3) — والسهمان ينقلان للفترة السابقة أو التالية. `changed`
    عند كل تغيير."""
    changed = QtCore.pyqtSignal()
    MODES = (("month", "شهري"), ("quarter", "ربع سنوي"), ("year", "سنوي"),
             ("custom", "من تاريخ إلى تاريخ"), ("all", "كل الفترات"))

    def __init__(self, pref_key="", parent=None):
        super().__init__(parent)
        from ui.widgets.common import date_edit, load_pref
        self.pref_key = pref_key
        self.anchor = QtCore.QDate.currentDate()
        self.btns = {}
        grp = QtWidgets.QButtonGroup(self)
        grp.setExclusive(True)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        for key, label in self.MODES:
            b = kit.PushButton(label)
            b.setObjectName("dashPanel")
            b.setCheckable(True)
            b.setSizePolicy(QtWidgets.QSizePolicy.Maximum,
                            QtWidgets.QSizePolicy.Fixed)
            b.clicked.connect(lambda _c=False, k=key: self.set_mode(k))
            grp.addButton(b)
            self.btns[key] = b
            lay.addWidget(b)
        lay.addSpacing(10)
        self.b_next = QtWidgets.QToolButton()
        self.b_next.setText("‹")
        self.b_next.setToolTip("الفترة التالية")
        self.b_prev = QtWidgets.QToolButton()
        self.b_prev.setText("›")
        self.b_prev.setToolTip("الفترة السابقة")
        self.b_prev.clicked.connect(lambda: self._shift(-1))
        self.b_next.clicked.connect(lambda: self._shift(1))
        self.lbl = QtWidgets.QLabel("")
        self.lbl.setObjectName("chipTitle")
        self.lbl.setMinimumWidth(150)
        self.lbl.setAlignment(QtCore.Qt.AlignCenter)
        self.d1 = date_edit()
        self.d2 = date_edit()
        self.d1.setDate(QtCore.QDate(self.anchor.year(), self.anchor.month(),
                                     1))
        self.l_from = QtWidgets.QLabel("من:")
        self.l_to = QtWidgets.QLabel("إلى:")
        for wd in (self.b_prev, self.lbl, self.b_next, self.l_from, self.d1,
                   self.l_to, self.d2):
            lay.addWidget(wd)
        self.d1.dateChanged.connect(lambda *_: self._custom_changed())
        self.d2.dateChanged.connect(lambda *_: self._custom_changed())
        mode = str(load_pref(pref_key, "month") or "month") if pref_key \
            else "month"
        self.mode = mode if mode in dict(self.MODES) else "month"
        self.set_mode(self.mode, emit=False)

    def set_mode(self, mode, emit=True):
        from ui.widgets.common import save_pref
        self.mode = mode
        self.btns[mode].setChecked(True)
        custom = mode == "custom"
        for wd in (self.l_from, self.d1, self.l_to, self.d2):
            wd.setVisible(custom)
        for wd in (self.b_prev, self.lbl, self.b_next):
            wd.setVisible(mode not in ("custom", "all"))
        if self.pref_key:
            try:
                save_pref(self.pref_key, mode)
            except Exception:                        # noqa: BLE001
                pass
        self._refresh()
        if emit:
            self.changed.emit()

    def _shift(self, step):
        n = {"month": 1, "quarter": 3, "year": 12}.get(self.mode, 0)
        if n:
            self.anchor = self.anchor.addMonths(step * n)
            self._refresh()
            self.changed.emit()

    def _custom_changed(self):
        if self.mode == "custom":
            self.changed.emit()

    def _refresh(self):
        y, mo = self.anchor.year(), self.anchor.month()
        if self.mode == "month":
            self.lbl.setText(f"{MONTHS[mo - 1]} {y}")
        elif self.mode == "quarter":
            self.lbl.setText(f"{QUARTERS[(mo - 1) // 3]} {y}")
        elif self.mode == "year":
            self.lbl.setText(f"سنة {y}")
        elif self.mode == "all":
            self.lbl.setText("كل الفترات")

    def range(self):
        """(من، إلى) نصّاً بصيغة yyyy-MM-dd."""
        fmt = "yyyy-MM-dd"
        y, mo = self.anchor.year(), self.anchor.month()
        if self.mode == "all":
            return "0000-01-01", "9999-12-31"
        if self.mode == "custom":
            a, b = self.d1.date(), self.d2.date()
            if a > b:
                a, b = b, a
            return a.toString(fmt), b.toString(fmt)
        if self.mode == "month":
            a = QtCore.QDate(y, mo, 1)
            b = a.addMonths(1).addDays(-1)
        elif self.mode == "quarter":
            a = QtCore.QDate(y, (mo - 1) // 3 * 3 + 1, 1)
            b = a.addMonths(3).addDays(-1)
        else:
            a = QtCore.QDate(y, 1, 1)
            b = QtCore.QDate(y, 12, 31)
        return a.toString(fmt), b.toString(fmt)

    def title(self):
        a, b = self.range()
        return (self.lbl.text() if self.mode != "custom"
                else f"من {a} إلى {b}")


def search_button(tip="يعرض كل السندات في كل الفترات حسب الاختيارات"
                  " (النوع وما تكتبه في البحث)"):
    """زرّ «بحث» في السجل (5.8.3)."""
    b = kit.PushButton("🔍  بحث")
    b.setObjectName("primary")
    b.setCursor(QtCore.Qt.PointingHandCursor)
    b.setToolTip(tip)
    b.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)
    return b


def view_buttons(table, col, count, on_view, text="عرض"):
    """زرّ «عرض» في عمودٍ بجانب كل صفٍّ من السجل."""
    for r in range(count):
        b = QtWidgets.QToolButton()
        b.setObjectName("rowAct")
        b.setText(text)
        b.setToolTip("معاينة المستند وطباعته")
        b.setCursor(QtCore.Qt.PointingHandCursor)
        b.clicked.connect(lambda _c=False, i=r: on_view(i))
        box = QtWidgets.QWidget()
        bl = QtWidgets.QHBoxLayout(box)
        bl.setContentsMargins(4, 2, 4, 2)
        bl.addWidget(b)
        table.setCellWidget(r, col, box)
