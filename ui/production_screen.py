# -*- coding: utf-8 -*-
"""الوارد من التصنيع — ثلاث طبقات: وجهة الدفعة وتاريخها (وإلى أي
حساب تدخل البضاعة)، ثم سطر إدخال الطقم بترتيب الورقة نفسه والتنقّل فيه
بـEnter والأسهم، ثم الدفعة في جدولٍ أول عمودٍ فيه زرّا تعديل السطر
وحذفه.

تفكيك أوزان رقم التشغيل: الذهب | الفصوص | الأحجار | الأحجار بعد الخصم |
الوزن المقيد (الأثر المالي والمخزني) | الذهب القائم (للإحصاء فقط، بلا
أثر محاسبي). ولكل سطرٍ عيارُ كتابته، والقيد بمكافئ 18 دائماً.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

import config
from database.database import db
from models import inventory
from models.accounts import acc_id
from services import drafts, gold_math, karat_view as kv
from ui.widgets.common import (busy, confirm_post, posted, ask, big_label,
                               date_edit, dstr, enter_chain, err, fill,
                               load_pref, make_table, mspin,
                               row_action_buttons, save_pref, title_label,
                               wspin)
from ui.widgets.table_fit import fit_columns

DRAFT_KEY = "production"


# ══════════════════════════════════════════════════════════════════
#  حدود التخزين: الدفعة على الشاشة بعيار سطرها، وفي القاعدة بمكافئ 18
# ══════════════════════════════════════════════════════════════════

def _bk(b):
    """عيار السطر — وصفرُه يعني عيار المصنع (أسطرٌ سابقة لهذا الخيار)."""
    return int(b.get("karat") or kv.active())


def _wage18(b):
    """أجر البطاقة بمكافئ 18 — كما هو، بلا تقريبٍ ذهاباً وإياباً.

    لا خانة أجرٍ في الشاشة: الأجر المحفوظ في السطر يمرّ إلى القاعدة
    كما جاء. وأسطرُ المسوّدات القديمة (وقد كُتب فيها الأجر بعيار
    العرض) تُحوَّل مرةً واحدة.
    """
    if b.get("wage18") is not None:
        return round(float(b["wage18"]), 6)
    if b.get("wage_per_gram") is not None:
        return kv.rate_store(b.get("wage_per_gram") or 0, _bk(b))
    return float(config.DEFAULT_WAGE_PER_GRAM)


def _to_store(b):
    """سطر دفعة كما يراه المستخدم ← كما يُخزَّن (مكافئ 18)."""
    k = _bk(b)
    return {**b, "karat": k,
            "gold": kv.store(b.get("gold"), k),
            "small_stones": kv.store(b.get("small_stones"), k),
            "big_stones": kv.store(b.get("big_stones"), k),
            "wage_per_gram": _wage18(b)}


def _to_view(b):
    """سطر دفعة كما هو مخزَّن ← كما يُعرض بعيار كتابته.

    الأجر يُحمل كما خُزِّن (`wage18`): تعديلُ دفعةٍ لا يمسّ أجر
    أطقمها وليس في الشاشة ما يغيّره.
    """
    k = _bk(b)
    w = dict(b)
    stored = w.pop("wage_per_gram", None)
    return {**w, "karat": k,
            "gold": kv.g(b.get("gold"), k),
            "small_stones": kv.g(b.get("small_stones"), k),
            "big_stones": kv.g(b.get("big_stones"), k),
            "wage18": (float(stored) if stored is not None
                       else float(config.DEFAULT_WAGE_PER_GRAM))}


class DiscountDialog(QtWidgets.QDialog):
    """نافذة صغيرة لتحديد نسبة الخصم التجاري على الأحجار."""

    def __init__(self, parent, current_rate):
        super().__init__(parent)
        self.setWindowTitle("نسبة الخصم على الأحجار")
        self.rate = QtWidgets.QDoubleSpinBox()
        self.rate.setDecimals(1)
        self.rate.setRange(0, 100)
        self.rate.setSuffix(" %")
        self.rate.setValue(current_rate * 100)
        form = QtWidgets.QFormLayout(self)
        form.addRow(QtWidgets.QLabel(
            "نسبة الخصم التجاري المخصومة من وزن الأحجار.\n"
            "الأحجار بعد الخصم = وزن الأحجار × (1 − النسبة)."))
        form.addRow("نسبة الخصم:", self.rate)
        box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def value(self):
        return self.rate.value() / 100.0


from ui.widgets.edit_mode import EditModeMixin


class NewDestDialog(QtWidgets.QDialog):
    """حساب مخزنٍ جديد تدخل إليه بضاعة التوريد.

    يُضاف تحت مجموعة الذهب والمخازن فيرث طبيعتها — الاسم وحده يُسأل
    عنه، والكود والنوع والطبيعة من الشجرة.
    """

    def __init__(self, parent, username):
        super().__init__(parent)
        self.username = username
        self.account_id = None
        self.setWindowTitle("حساب مخزن جديد")
        self.setMinimumWidth(420)
        self.name = QtWidgets.QLineEdit()
        self.name.setPlaceholderText("مثال: مخزن الوارد الجديد")
        note = QtWidgets.QLabel(
            "يُنشأ الحساب تحت «الأصول المتداولة — الذهب والمخازن» "
            "بقياسٍ وزني، فيصلح فوراً حساباً تدخل إليه بضاعة التوريد "
            "ويظهر له كشف حسابٍ مستقل.")
        note.setWordWrap(True)
        note.setObjectName("cardSub")
        form = QtWidgets.QFormLayout(self)
        form.addRow(note)
        form.addRow("اسم الحساب:", self.name)
        box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        box.accepted.connect(self.save)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def save(self):
        try:
            from models import accounts as _a
            from models import coa
            with db() as conn:
                res = coa.add_sub_account(
                    conn, acc_id(conn, _a.GOLD_GROUP),
                    self.name.text().strip(), self.username,
                    measurement="gold")
            self.account_id = res["id"]
            self.accept()
        except Exception as e:
            err(self, e)


class ProductionScreen(EditModeMixin, QtWidgets.QWidget):
    """الوارد من التصنيع — ثلاث طبقات كشاشة المبيعات تماماً.

      ① **الوجهة والتاريخ** — يُملأ مرةً للدفعة كلها: تاريخ الترحيل،
        ثم **إلى أي حساب** تدخل البضاعة (الذهب المشغول افتراضاً،
        ويُضاف حسابٌ جديد من الشاشة)، والعيار إن كانت الوجهة صندوق
        الكسر.
      ② **سطر الإدخال** — يتكرّر مع كل طقم: الموديل ← رقم التشغيل
        ← الذهب ← الفصوص ← الأحجار ← بعد الخصم ← ملاحظات ← المقيد ←
        القائم ← العيار. وEnter والأسهم تتنقّل بين الخانات، ولا
        يتجاوز Enter رقم التشغيل وهو فارغ، وبعد الإضافة يعود إليه.
      ③ **الدفعة** — جدولٌ أول عمودٍ فيه زرّا تعديل السطر وحذفه،
        والإجمالي تحته، ثم الترحيل بقيدٍ مجمّعٍ واحد.

    **ما لا يتغيّر**: الوزن المقيد وحده صاحب الأثر المالي والمخزني،
    وكل وزنٍ يعبر إلى القاعدة بمكافئ عيار 18 مهما كان عيار الإدخال.
    """

    # العمود الأول بلا عنوان: فيه زرّا تعديل السطر وحذفه.
    # عمود الأجر حُذف مع خانته: التوريد لا يُسأل فيه عن أجر.
    COLS = ["", "رقم الموديل", "رقم التشغيل", "العيار", "الوزن المقيد",
            "الوزن القائم", "الذهب", "الفصوص", "الأحجار",
            "الأحجار بعد الخصم", "نسبة الخصم", "ملاحظات"]
    COL_W = [6, 10, 10, 6, 9, 9, 8, 8, 8, 9, 7, 10]

    def __init__(self, user):
        super().__init__()
        self.user = user
        self.batch = []
        self.rate = config.STONE_DISCOUNT_RATE
        self.dests = []
        self._calc = False
        self._w18 = [0.0, 0.0, 0.0]   # ظلُّ أوزان السطر بمكافئ 18

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label(
            "الوارد من التصنيع — خزينة التصنيع إلى مخزن البضاعة"))
        lay.addWidget(self._build_header())
        lay.addWidget(self._build_entry())
        lay.addWidget(self._build_batch(), 1)

    # ══════════════════════════════════════════════════════════════
    #  ① الوجهة والتاريخ
    # ══════════════════════════════════════════════════════════════

    def _build_header(self):
        box = QtWidgets.QGroupBox("① وجهة الدفعة وتاريخها")
        self.date = date_edit()
        # ══ إلى أي حساب تدخل البضاعة ══
        # كانت تدخل الذهب المشغول وحده مهما كانت حقيقتها، فمن ورّد
        # إلى صندوق الكسر احتاج قيداً يدوياً بعدها يُصحّح المخزن —
        # قيدٌ يُنسى فيختلّ الصندوقان. وآخر اختيارٍ يُحفظ ويعود.
        self.dest = QtWidgets.QComboBox()
        self.dest.setMinimumWidth(260)
        self.dest.setToolTip(
            "الحساب الذي تدخل إليه بضاعة هذه الدفعة — الطرف المدين "
            "من قيدها. والدائن خزينة التصنيع كما هو دائماً.")
        self.dest.currentIndexChanged.connect(self._dest_changed)
        self.scrap_karat = QtWidgets.QComboBox()
        self.scrap_karat.setMaximumWidth(120)
        for k in config.KARATS:
            self.scrap_karat.addItem(f"عيار {k}", k)
        self.scrap_karat.setToolTip(
            "صندوق الكسر حسابٌ واحد يضمّ الأعيرة الأربعة — وهذا يقول "
            "إلى أي عيارٍ أُضيف الوزن فعلاً.")
        self.scrap_karat.currentIndexChanged.connect(self._save_dest_pref)
        self.scrap_lbl = QtWidgets.QLabel("عيار الإضافة:")
        btn_new_dest = QtWidgets.QPushButton("+ حساب")
        btn_new_dest.setObjectName("ghost")
        btn_new_dest.setToolTip("إضافة حساب مخزنٍ جديد تدخل إليه البضاعة")
        btn_new_dest.clicked.connect(self.new_dest)
        # ══ مرجع العملية ══
        # ورقةُ الورشة ورقمُ الطلب وكشفُ التسليم — للدفعة مرجعٌ خارج
        # النظام يعود إليه المحاسب حين يُسأل «من أين جاءت هذه؟».
        # يُحفظ مع القيد ويظهر في بيان كشف الحساب وحده مُسمّى، فلا
        # يلتبس برقم التشغيل ولا برقم القيد.
        self.reference = QtWidgets.QLineEdit()
        self.reference.setPlaceholderText("رقم ورقة الورشة أو الطلب…")
        self.reference.setToolTip(
            "مرجع هذه الدفعة — يظهر في بيان كشف الحساب هكذا: "
            "«مرجع: …»، ويعود معها عند فتحها للتعديل.")
        self.tazeena_label = big_label()
        self.tazeena_label.setWordWrap(True)

        g = QtWidgets.QGridLayout(box)
        g.setHorizontalSpacing(10)
        g.addWidget(QtWidgets.QLabel("تاريخ الترحيل:"), 0, 0)
        g.addWidget(self.date, 0, 1)
        g.addWidget(QtWidgets.QLabel("إلى حساب:"), 0, 2)
        g.addWidget(self.dest, 0, 3)
        g.addWidget(self.scrap_lbl, 0, 4)
        g.addWidget(self.scrap_karat, 0, 5)
        g.addWidget(btn_new_dest, 0, 6)
        g.addWidget(QtWidgets.QLabel("المرجع:"), 1, 0)
        g.addWidget(self.reference, 1, 1, 1, 6)
        g.addWidget(self.tazeena_label, 2, 0, 1, 7)
        g.setColumnStretch(3, 3)
        # ══ Enter يمضي إلى الأمام في الشاشة كلها ══
        # رأسُ الشاشة سلسلةٌ أولى تُسلّم لسطر الإدخال، فالدفعة كلها
        # بضغطات Enter متتابعة بلا انتقالٍ إلى الفأرة.
        self._head_chain = [self.date, self.dest, self.scrap_karat,
                            self.reference]
        enter_chain(self, self._head_chain, on_last=lambda: self.model_no)
        return box

    # ══════════════════════════════════════════════════════════════
    #  ② سطر الإدخال
    # ══════════════════════════════════════════════════════════════

    def _build_entry(self):
        box = QtWidgets.QGroupBox(
            "② إدخال الطقم  —  Enter ينتقل للخانة التالية · "
            "الأسهم ← → تتنقّل · Enter على آخر خانة يضيف السطر")
        # رقم الموديل: تصنيف وصفي يجمع الأطقم المتشابهة تصميماً.
        # يُدخَل قبل رقم التشغيل ويبقى ثابتاً لأطقم الدفعة الواحدة،
        # فيُدخل مرة ويُربط بكل ما بعده حتى يُغيّره المستخدم.
        self.model_no = QtWidgets.QComboBox()
        self.model_no.setEditable(True)
        self.model_no.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.model_no.lineEdit().setPlaceholderText("رقم الموديل")
        self.wo_no = QtWidgets.QLineEdit()
        # المقيد والقائم **مشتقّان** من المكوّنات لا يُكتبان: إدخالهما
        # يدوياً يجعل السطر يناقض نفسه (مجموعٌ لا يساوي أجزاءه).
        self.reg = wspin()
        self.reg.setReadOnly(True)
        self.reg.setToolTip(
            "الوزن المقيد = الذهب + الفصوص + الأحجار بعد الخصم — "
            "وهو وحده صاحب الأثر المالي والمخزني. يُحسب تلقائياً.")
        self.standing = wspin()
        self.standing.setReadOnly(True)
        self.standing.setToolTip(
            "الذهب القائم = الذهب + الفصوص + الأحجار قبل الخصم — "
            "للمعرفة والإحصاء، بلا أثرٍ محاسبي.")
        # ══ لا خانة أجرٍ في التوريد ══
        # الأجر يُتّفق عليه عند **البيع** مع العميل، لا عند الاستلام
        # من الورشة. فخانته هنا كانت تُملأ برقمٍ افتراضيٍّ لا يعني
        # شيئاً ويقف عندها المؤشر في كل سطر. يُحفظ للطقم الأجر
        # الافتراضي للنظام كما كان يُحفظ، وشاشة المبيعات تقدّم عليه
        # اتفاق العميل.
        self.karat = QtWidgets.QComboBox()
        for k in config.KARATS:
            self.karat.addItem(f"عيار {k}", k)
        self.karat.setToolTip(
            "عيار الأوزان المكتوبة في هذا السطر. القيد يُخزَّن بمكافئ 18 "
            "دائماً — والأرقام تبقى كما كُتبت، والعيار يقول بأي "
            "عيارٍ كُتبت.")
        self._karat_now = kv.active()
        i = self.karat.findData(self._karat_now)
        if i >= 0:
            self.karat.setCurrentIndex(i)
        self.karat.currentIndexChanged.connect(self._karat_changed)
        self.gold = wspin()
        self.small = wspin()
        self.big = wspin()
        self.after = wspin()
        self.after.setReadOnly(True)
        self.after.setToolTip(
            "الأحجار بعد الخصم = وزن الأحجار × (1 − نسبة الخصم)")
        self.btn_rate = QtWidgets.QPushButton(f"خصم {self.rate*100:.0f}%")
        self.btn_rate.setObjectName("ghost")
        self.btn_rate.setMaximumWidth(96)
        self.btn_rate.clicked.connect(self.edit_rate)
        self.notes = QtWidgets.QLineEdit()
        # ثلاث منازلٍ لا منزلتان في خانات الوزن: تبديل العيار يقسم
        # ويضرب، وتقريبُ منزلتين يُرجع 40.01 بدل 40.000 بعد ذهابٍ
        # وإياب — فيبدو للمستخدم أن الرقم تغيّر من تلقاء نفسه.
        for w in (self.reg, self.standing, self.gold, self.small,
                  self.big, self.after):
            w.setDecimals(3)
        for w in (self.gold, self.small, self.big):
            w.valueChanged.connect(self._parts_typed)
        btn_add = QtWidgets.QPushButton("+ إضافة")
        btn_add.clicked.connect(self.add_row)

        def _sub(t):
            lbl = QtWidgets.QLabel(t)
            lbl.setObjectName("cardSub")
            lbl.setAlignment(QtCore.Qt.AlignCenter)
            return lbl

        after_box = QtWidgets.QWidget()
        ab = QtWidgets.QHBoxLayout(after_box)
        ab.setContentsMargins(0, 0, 0, 0)
        ab.setSpacing(3)
        ab.addWidget(self.after, 1)
        ab.addWidget(self.btn_rate)

        # الترتيب كما طلبه صاحب النظام: ما يُكتب أولاً (الموديل
        # والرقم والمكوّنات والملاحظة)، ثم ما يُقرأ في الآخر: المقيد
        # والقائم المحسوبان، والعيار الذي يصف ما كُتب.
        fields = [
            ("رقم الموديل", self.model_no, 2),
            ("رقم التشغيل", self.wo_no, 2),
            ("الذهب", self.gold, 2),
            ("الفصوص", self.small, 2),
            ("الأحجار", self.big, 2),
            ("الأحجار بعد الخصم", after_box, 3),
            ("ملاحظات", self.notes, 2),
            ("الوزن المقيد", self.reg, 2),
            ("الوزن القائم", self.standing, 2),
            ("العيار", self.karat, 2),
        ]
        g = QtWidgets.QGridLayout(box)
        g.setHorizontalSpacing(6)
        for c, (label, widget, stretch) in enumerate(fields):
            widget.setMinimumWidth(86)
            g.addWidget(_sub(label), 0, c)
            g.addWidget(widget, 1, c)
            g.setColumnStretch(c, stretch)
        g.addWidget(btn_add, 1, len(fields))

        # ترتيب التنقّل هو ترتيب الخانات القابلة للكتابة: المشتقّات
        # (المقيد والقائم وبعد الخصم) تُتخطّى فلا يقف المؤشر عندها.
        # ورقم التشغيل **إلزامي**: Enter لا يتجاوزه وهو فارغ. وبعد
        # إضافة السطر يعود المؤشر إليه لا إلى الموديل — الموديل ثابتٌ
        # لأطقم الدفعة، والرقم هو ما يتغيّر في كل سطر.
        self._chain = [self.model_no, self.wo_no, self.gold, self.small,
                       self.big, self.notes, self.karat]
        enter_chain(self, self._chain, on_last=self._add_from_enter,
                    require={self.wo_no:
                             lambda: bool(self.wo_no.text().strip())})
        return box

    def _add_from_enter(self):
        """Enter على آخر خانة: يُضاف السطر ويعود المؤشر لرقم التشغيل.

        وإن رُفض السطر (وزنٌ ناقص مثلاً) يبقى المؤشر حيث هو ليُصحَّح
        — لا يقفز إلى أول السطر فيضيع موضع الخطأ.
        """
        return self.wo_no if self.add_row() else False

    # ══════════════════════════════════════════════════════════════
    #  ③ الدفعة
    # ══════════════════════════════════════════════════════════════

    def _build_batch(self):
        box = QtWidgets.QGroupBox("③ الدفعة الحالية — قبل الترحيل")
        self.grid = make_table()
        hint = QtWidgets.QLabel(
            "✎ يفتح السطر كاملاً للتصحيح   ·   ✕ يحذفه من الدفعة "
            "  ·   كلاهما في أول عمودٍ من الجدول")
        hint.setObjectName("cardSub")
        self.totals = big_label()
        btn_post = QtWidgets.QPushButton(
            "ترحيل الدفعة (قيد محاسبي مجمّع واحد)")
        btn_post.clicked.connect(self.post_batch)
        self.init_edit_mode(btn_post, "التوريد")
        # يظهر حين تُستعاد دفعة لم تُرحَّل — فلا يظن المستخدم أن
        # أسطراً ظهرت من تلقاء نفسها.
        self.draft_note = QtWidgets.QLabel("")
        self.draft_note.setObjectName("ok")
        self.draft_note.setWordWrap(True)
        self.draft_note.setVisible(False)

        v = QtWidgets.QVBoxLayout(box)
        v.addWidget(self.grid, 1)
        v.addWidget(hint)
        v.addWidget(self.totals)
        v.addWidget(self.draft_note)
        v.addWidget(self.edit_banner)
        prow = QtWidgets.QHBoxLayout()
        prow.addWidget(btn_post, 1)
        prow.addWidget(self.btn_cancel_edit)
        v.addLayout(prow)
        return box

    # ══════════════════════════════════════════════════════════════
    #  حساب الوجهة
    # ══════════════════════════════════════════════════════════════

    def _reload_dests(self, conn):
        """يملأ قائمة المخازن ويعيد آخر اختيارٍ محفوظ."""
        want = str(load_pref("supply_dest_account", "")).strip()
        self.dests = inventory.dest_accounts(conn)
        self.dest.blockSignals(True)
        self.dest.clear()
        for r in self.dests:
            self.dest.addItem(f"{r['name']} ({r['code']})", r["id"])
        idx = -1
        for i, r in enumerate(self.dests):
            if want and r["code"] == want:
                idx = i
                break
        if idx < 0:
            from models import accounts as _a
            for i, r in enumerate(self.dests):
                if r["code"] == _a.FINISHED_GOLD:
                    idx = i
                    break
        if idx >= 0:
            self.dest.setCurrentIndex(idx)
        self.dest.blockSignals(False)
        k = str(load_pref("supply_scrap_karat", "")).strip()
        if k.isdigit():
            i = self.scrap_karat.findData(int(k))
            if i >= 0:
                self.scrap_karat.blockSignals(True)
                self.scrap_karat.setCurrentIndex(i)
                self.scrap_karat.blockSignals(False)
        self._sync_scrap_box()

    def _dest_code(self):
        i = self.dest.currentIndex()
        return self.dests[i]["code"] if 0 <= i < len(self.dests) else ""

    def _is_scrap_dest(self):
        from models import accounts as _a
        return self._dest_code() == _a.SCRAP_BOX

    def _sync_scrap_box(self):
        """خانة العيار لا تظهر إلا لصندوق الكسر — فلا تُسأل عمّا لا يعني."""
        on = self._is_scrap_dest()
        self.scrap_lbl.setVisible(on)
        self.scrap_karat.setVisible(on)

    def _dest_changed(self, *_):
        self._sync_scrap_box()
        self._save_dest_pref()

    def _save_dest_pref(self, *_):
        code = self._dest_code()
        if code:
            save_pref("supply_dest_account", code,
                      self.user.get("username"))
        save_pref("supply_scrap_karat",
                  str(self.scrap_karat.currentData() or ""),
                  self.user.get("username"))

    def _select_dest(self, code=None, karat=None):
        if code:
            for i, r in enumerate(self.dests):
                if r["code"] == code:
                    self.dest.setCurrentIndex(i)
                    break
        if karat:
            i = self.scrap_karat.findData(int(karat))
            if i >= 0:
                self.scrap_karat.setCurrentIndex(i)
        self._sync_scrap_box()

    def new_dest(self):
        dlg = NewDestDialog(self, self.user["username"])
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            with db(readonly=True) as conn:
                self._reload_dests(conn)
            i = self.dest.findData(dlg.account_id)
            if i >= 0:
                self.dest.setCurrentIndex(i)

    # ══════════════════════════════════════════════════════════════
    #  سطر الإدخال
    # ══════════════════════════════════════════════════════════════

    def _k(self):
        """عيار السطر المختار الآن."""
        return int(self.karat.currentData() or kv.active())

    def edit_rate(self):
        dlg = DiscountDialog(self, self.rate)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self.rate = dlg.value()
            self.btn_rate.setText(f"خصم {self.rate*100:.0f}%")
            self.recalc()

    def _snap_w18(self):
        """لقطةٌ ظلّيةٌ لمكوّنات السطر بمكافئ 18 — مرجعُ تبديل العيار.

        **لماذا**: الخانة تعرض ثلاث منازل، وتبديل العيار قسمةٌ ثم
        ضرب. فوزنٌ كُتب 40.000 يعود 39.999 بعد ذهابٍ وإياب، فيظن
        المستخدم أن الرقم تغيّر وحده. الظلُّ لا يُقرَّب.
        """
        self._w18 = [kv.store(w.value(), self._karat_now)
                     for w in (self.gold, self.small, self.big)]

    def recalc(self, *_):
        """المشتقّات تتبع المكوّنات فوراً — بعيار السطر كما كُتبت."""
        if self._calc:
            return
        self._calc = True
        try:
            after = gold_math.stones_after_discount(self.big.value(),
                                                    self.rate)
            reg = gold_math.registered_weight(
                self.gold.value(), self.small.value(), self.big.value(),
                self.rate)
            standing = gold_math.standing_gold(
                self.gold.value(), self.small.value(), self.big.value())
            self.after.setValue(after)
            self.reg.setValue(reg)
            self.standing.setValue(standing)
        finally:
            self._calc = False

    def _parts_typed(self, *_):
        """مكوّنٌ كتبه المستخدم: تُحسب المشتقّات ثم تُؤخذ اللقطة.

        اللقطة هنا لا في `recalc`: تبديل العيار يستدعي `recalc` بعد
        أن يكتب الأوزان من الظلّ، فلو أخذت اللقطة هناك لدهست الظلَّ
        الدقيق بقيمةٍ مقرَّبة وضاع ما يحرسه.
        """
        if self._calc:
            return
        self.recalc()
        self._snap_w18()

    def _karat_changed(self, *_):
        """العيار في آخر السطر **يصف** ما كُتب قبله — لا يحوّله.

        الأوزان في التوريد تُكتب باليد من ورقة الورشة. فمن كتب 40 ثم
        اختار عيار 21 يعني «أربعون جراماً عيار 21» — لا أن تتحوّل
        الأربعون إلى 34.29. الأرقام تبقى كما كُتبت، والعيار يقول
        بأي عيارٍ تُقرأ، والتحويل إلى مكافئ 18 عند الترحيل وحده.
        """
        self._karat_now = self._k()
        self._snap_w18()

    def _clear_entry(self):
        """يُفرغ سطر الإدخال — والعيار والموديل يبقيان.

        الموديل يبقى عمداً: الدفعة الواحدة أطقمُ موديلٍ واحدٍ غالباً،
        فإعادة كتابته في كل سطرٍ عملٌ بلا فائدة. (وفي المبيعات يُمسح
        لأن كل سطرٍ هناك طقمٌ مستقل قد يكون من موديلٍ آخر.)
        """
        self._calc = True
        try:
            self.wo_no.clear()
            for w in (self.gold, self.small, self.big, self.after,
                      self.reg, self.standing):
                w.setValue(0)
            self.notes.clear()
        finally:
            self._calc = False

    def add_row(self):
        try:
            wo_no = self.wo_no.text().strip()
            if not wo_no:
                raise ValueError("أدخل رقم التشغيل")
            if any(b["wo_no"] == wo_no for b in self.batch):
                raise ValueError(
                    f"رقم التشغيل {wo_no} مضاف مسبقاً في هذه الدفعة")
            if self.gold.value() + self.small.value() + self.big.value() <= 0:
                raise ValueError("أدخل وزناً واحداً على الأقل")
            self.batch.append({
                "model_no": self.model_no.currentText().strip(),
                "wo_no": wo_no, "gold": self.gold.value(),
                "small_stones": self.small.value(),
                "big_stones": self.big.value(), "discount_rate": self.rate,
                # أجر البطاقة الافتراضي بمكافئ 18 مباشرةً — لا خانة له
                # في الشاشة، فلا يمرّ بتحويل عيارٍ يقرّبه.
                "wage18": float(config.DEFAULT_WAGE_PER_GRAM),
                "karat": self._k(),
                "notes": self.notes.text().strip()})
            self._clear_entry()
            self.wo_no.setFocus()
            self.render_batch()
            return True
        except Exception as e:
            err(self, e)
            return False

    def edit_row(self, row=None):
        """يفتح السطر كاملاً للتصحيح — بخانات سطر الإدخال نفسها.

        `row` يأتي من زرّ السطر نفسه؛ وبلا رقمٍ يعمل على المحدَّد.
        """
        r = self.grid.currentRow() if row is None else int(row)
        if not (0 <= r < len(self.batch)):
            err(self, "اختر سطراً من الجدول أولاً")
            return
        b = self.batch[r]
        k0 = int(b.get("karat") or kv.active())
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(f"تعديل السطر — {b['wo_no']}")
        dlg.setMinimumWidth(460)
        w_model = QtWidgets.QLineEdit(str(b.get("model_no") or ""))
        w_no = QtWidgets.QLineEdit(str(b["wo_no"]))
        w_karat = QtWidgets.QComboBox()
        for kk in config.KARATS:
            w_karat.addItem(f"عيار {kk}", kk)
        i = w_karat.findData(k0)
        if i >= 0:
            w_karat.setCurrentIndex(i)
        w_gold, w_small, w_big = wspin(), wspin(), wspin()
        w_gold.setValue(b["gold"])
        w_small.setValue(b["small_stones"])
        w_big.setValue(b["big_stones"])
        w_rate = mspin()
        w_rate.setValue(b["discount_rate"] * 100)
        w_notes = QtWidgets.QLineEdit(str(b.get("notes") or ""))
        prev = QtWidgets.QLabel("")
        prev.setObjectName("cardSub")

        def _calc():
            reg = gold_math.registered_weight(
                w_gold.value(), w_small.value(), w_big.value(),
                w_rate.value() / 100.0)
            standing = gold_math.standing_gold(
                w_gold.value(), w_small.value(), w_big.value())
            u = kv.unit(int(w_karat.currentData() or k0))
            prev.setText(f"الوزن المقيد: {reg:,.2f} {u}   ·   "
                         f"الذهب القائم: {standing:,.2f} {u}")
        for w in (w_gold, w_small, w_big, w_rate):
            w.valueChanged.connect(_calc)
        w_karat.currentIndexChanged.connect(_calc)
        _calc()

        f = QtWidgets.QFormLayout()
        f.addRow("رقم الموديل:", w_model)
        f.addRow("رقم التشغيل:", w_no)
        # بترتيب سطر الإدخال نفسه: المكوّنات ثم الملاحظة ثم العيار
        f.addRow("الذهب:", w_gold)
        f.addRow("الفصوص:", w_small)
        f.addRow("الأحجار:", w_big)
        f.addRow("نسبة الخصم %:", w_rate)
        f.addRow("ملاحظات:", w_notes)
        f.addRow("العيار:", w_karat)
        f.addRow(prev)
        box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save
            | QtWidgets.QDialogButtonBox.Cancel)
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.addLayout(f)
        lay.addWidget(box)
        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return
        no = w_no.text().strip()
        if not no:
            err(self, "أدخل رقم التشغيل")
            return
        if any(x is not b and x["wo_no"] == no for x in self.batch):
            err(self, f"رقم التشغيل {no} مضاف مسبقاً في هذه الدفعة")
            return
        if w_gold.value() + w_small.value() + w_big.value() <= 0:
            err(self, "أدخل وزناً واحداً على الأقل")
            return
        b.update({
            "model_no": w_model.text().strip(),
            "wo_no": no, "gold": w_gold.value(),
            "small_stones": w_small.value(), "big_stones": w_big.value(),
            "discount_rate": w_rate.value() / 100.0,
            "karat": int(w_karat.currentData() or k0),
            "notes": w_notes.text().strip()})
        self.render_batch()

    def remove_row(self, row=None):
        r = self.grid.currentRow() if row is None else int(row)
        if 0 <= r < len(self.batch):
            self.batch.pop(r)
            self.render_batch()

    def render_batch(self):
        rows = []
        total18 = 0.0
        for b in self.batch:
            k = int(b.get("karat") or kv.active())
            after = gold_math.stones_after_discount(b["big_stones"],
                                                    b["discount_rate"])
            reg = gold_math.registered_weight(b["gold"], b["small_stones"],
                                              b["big_stones"],
                                              b["discount_rate"])
            standing = gold_math.standing_gold(b["gold"], b["small_stones"],
                                               b["big_stones"])
            rows.append(("", b.get("model_no") or "—", b["wo_no"],
                         f"عيار {k}", reg, standing, b["gold"],
                         b["small_stones"], b["big_stones"], after,
                         f"{b['discount_rate']*100:.0f}%",
                         b["notes"] or "—"))
            # الإجمالي يُجمع بمكافئ 18: أسطرٌ بأعيرةٍ مختلفة لا يصحّ
            # جمعها كما تُعرض.
            total18 += kv.store(reg, k)
        if rows:
            u = kv.active()
            rows.append(("", "الإجمالي", f"{len(self.batch)} طقم",
                         f"عيار {u}", round(kv.g(total18), 3),
                         "", "", "", "", "", "", ""))
        fill(self.grid, self._headers(), rows)
        fit_columns(self.grid, self.COL_W)
        if rows:
            self._bold_row(len(rows) - 1)
            row_action_buttons(self.grid, len(self.batch),
                               on_edit=self.edit_row,
                               on_delete=self.remove_row,
                               edit_tip="تعديل هذا السطر كاملاً",
                               del_tip="حذف هذا السطر من الدفعة")
        self.totals.setText(
            f"عدد أطقم الدفعة: {len(self.batch)}   |   إجمالي الوزن "
            f"المقيد: {kv.g(total18):,.2f} {kv.unit()}")
        self.recalc()

    def _headers(self):
        """عناوين الجدول — بلا لاحقة عيارٍ لأن لكل سطرٍ عياره."""
        return list(self.COLS)

    def _bold_row(self, r):
        """صفُّ الإجمالي يُعلَّم فلا يُقرأ سطراً من الدفعة."""
        try:
            from ui import theme
            pal = theme.palette(theme.current_theme())
            bg = QtGui.QColor(pal.get("sumBg", "#FDF3E2"))
            ink = QtGui.QColor(pal.get("sumInk", "#7A4F10"))
        except Exception:
            bg, ink = QtGui.QColor("#FDF3E2"), QtGui.QColor("#7A4F10")
        for c in range(self.grid.columnCount()):
            item = self.grid.item(r, c)
            if item is None:
                continue
            f = item.font()
            f.setBold(True)
            item.setFont(f)
            item.setBackground(bg)
            item.setForeground(ink)

    # ══════════════════════════════════════════════════════════════
    #  مسوّدة الدفعة غير المرحَّلة
    # --------------------------------------------------------------
    #  الشاشة تُغلق عند الانتقال لغيرها، فدفعةٌ من عشرين طقماً كانت
    #  تضيع بخروجةٍ واحدة لمراجعة رقم. الشرح في `services/drafts.py`.
    # ══════════════════════════════════════════════════════════════

    def draft_state(self):
        """أسطر الدفعة كما هي — وهي قواميس بسيطة تُحفظ كما هي.

        الأوزان هنا **بعيار سطرها** لا بمكافئ 18، تماماً كما يراها
        المستخدم في الجدول، فتعود كما تركها. والتحويل يبقى في مكانه
        الوحيد: لحظة الترحيل.
        """
        if getattr(self, "is_editing", False):
            return None          # وضع التعديل لا يُحفظ مسوّدةً
        if not self.batch:
            return None
        return {"date": dstr(self.date), "karat": kv.active(),
                "dest": self._dest_code(),
                "scrap_karat": self.scrap_karat.currentData(),
                "reference": self.reference.text().strip(),
                "batch": [dict(b) for b in self.batch]}

    def apply_draft(self, d):
        if not d or not d.get("batch"):
            return False
        # المسوّدة محفوظة بعيار العرض وقت حفظها. لو بدّل المستخدم عيار
        # المصنع بينهما لصارت الأرقام بوحدةٍ أخرى — فلا تُستعاد بل
        # تُترك للمستخدم قراراً واعياً بدل أوزانٍ صامتة بوحدةٍ خاطئة.
        if int(d.get("karat") or kv.active()) != kv.active():
            return False
        self.batch = [dict(b) for b in d["batch"]]
        if d.get("date"):
            self.date.setDate(QtCore.QDate.fromString(d["date"],
                                                      "yyyy-MM-dd"))
        self._select_dest(d.get("dest"), d.get("scrap_karat"))
        self.reference.setText(d.get("reference") or "")
        self.render_batch()
        return True

    def _restore_draft(self):
        if getattr(self, "_draft_done", False):
            return
        self._draft_done = True
        try:
            if self.apply_draft(drafts.load(DRAFT_KEY,
                                            self.user.get("username"))):
                self.draft_note.setText(
                    "↩ استُعيدت دفعة لم تُرحَّل بعد — أكملها أو احذف "
                    "أسطرها.")
                self.draft_note.setVisible(True)
        except Exception:
            pass

    def on_close(self):
        """يُستدعى من `LazyScreen.release` عند مغادرة الشاشة."""
        try:
            drafts.save(DRAFT_KEY, self.user.get("username"),
                        self.draft_state())
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════
    #  الترحيل
    # ══════════════════════════════════════════════════════════════

    def post_batch(self):
        if not self.batch:
            err(self, "أضف طقماً واحداً على الأقل إلى الدفعة قبل الترحيل")
            return
        dest_id = self.dest.currentData()
        karat = (self.scrap_karat.currentData()
                 if self._is_scrap_dest() else None)
        if not ask(self, f"ترحيل {len(self.batch)} طقم إلى "
                         f"{self.dest.currentText()}"
                         + (f" (عيار {karat})" if karat else "")
                         + " بقيد محاسبي مجمّع واحد؟"):
            return
        try:
            # التحقق من حياة القيد **قبل** فتح المعاملة — لا داخلها
            self.verify_edit_target()
            if not confirm_post(
                    self, f"دفعة توريد أطقم\n\n"
                          f"إلى حساب: {self.dest.currentText()}"
                          + (f" — عيار {karat}" if karat else "")
                          + f"\nعدد الأطقم: {len(self.batch)}\n"
                            f"التاريخ: {dstr(self.date)}"):
                return

            # الحد الفاصل: ما تحته يُخزَّن بمكافئ 18 دائماً مهما كان
            # عيار السطر — فالميزان لا يتزن إلا بوحدة واحدة.
            batch = [_to_store(b) for b in self.batch]
            with busy(self, "جارٍ ترحيل الدفعة…", stage="ترحيل توريد"):
                with db() as conn:
                    if self.is_editing:
                        # تحديث **تفاضلي** لا إعادة إنشاء: المباع يبقى
                        # كما هو، والموجود يُعدَّل، والجديد يُضاف —
                        # والقيد يُعدَّل بالفرق الصافي وحده.
                        res = inventory.update_supply_batch(
                            conn, self.editing_entry_id, batch,
                            dstr(self.date), self.user["username"],
                            dest_account_id=dest_id, scrap_karat=karat,
                            reference=self.reference.text().strip())
                    else:
                        res = inventory.create_work_orders_batch(
                            conn, batch, dstr(self.date),
                            self.user["username"],
                            dest_account_id=dest_id, scrap_karat=karat,
                            reference=self.reference.text().strip())
            # ══ ما بعد هذه النقطة: المعاملة أُغلقت بنجاح ══
            # بناء الرسالة عرضٌ لا ترحيل. خطأٌ فيه كان يظهر للمستخدم
            # «خطأ» على عمليةٍ **تمّت وحُفظت** — فيعيدها ظانّاً أنها
            # فشلت. (وقع فعلاً: مفتاح `total_registered` كان ناقصاً في
            # مسار التعديل، فظهر `KeyError` إنجليزيّ بعد نجاح الحفظ.)
            if res.get("delta") is not None:
                # ملخّص التعديل التفاضلي
                parts = []
                if res.get("added"):
                    parts.append(f"أُضيف {len(res['added'])} طقم")
                if res.get("updated"):
                    parts.append(f"عُدّل {len(res['updated'])}")
                if res.get("removed"):
                    parts.append(f"حُذف {len(res['removed'])}")
                if res.get("kept_sold"):
                    parts.append(
                        f"{len(res['kept_sold'])} مباع بقي كما هو")
                lines = ("   ·   ".join(parts)
                         + f"\nصافي التغيّر في مخزن الوجهة: "
                           f"{kv.g(res['delta']):+.3f} {kv.unit()}")
                if res.get("moved_dest"):
                    lines += (f"\nوحساب الوجهة نُقل من "
                              f"{res['moved_dest'][0]} إلى "
                              f"{res['moved_dest'][1]}.")
            else:
                lines = "\n".join(f"• {i['work_order_no']}: مقيد "
                                  f"{kv.g(i['registered_weight']):.2f} / قائم "
                                  f"{kv.g(i['standing_gold']):.2f} {kv.unit()}"
                                  for i in res["items"])
                if res.get("dest_name"):
                    lines = f"إلى حساب: {res['dest_name']}\n" + lines
            was_editing = bool(self.is_editing)
            posted(self, f"تم ترحيل الدفعة بقيد رقم {res.get('entry_id')}\n"
                       f"إجمالي الوزن المقيد: "
                       f"{kv.g(res.get('total_registered') or 0):.2f} "
                       f"{kv.unit()}\n{lines}", "work_orders",
                   (res.get("items") or [{}])[0].get("id"),
                   editing=was_editing)
            self.end_edit()
            self.batch = []
            self.reference.clear()
            # المسوّدة تُمحى فور الترحيل: بديلٌ عن الذاكرة لا عن الدفتر
            drafts.clear(DRAFT_KEY, self.user.get("username"))
            self.draft_note.setVisible(False)
            self.render_batch()
            self.refresh()
        except Exception as e:
            err(self, e)

    def load_document(self, source_id):
        """يفتح دفعة توريد قائمة للتعديل: يُنزل كل أطقم القيد المجمّع
        نفسه في الجدول (لأن عكس القيد يعكس الدفعة كاملة)."""
        try:
            with db() as conn:
                wo = conn.execute(
                    "SELECT * FROM work_orders WHERE id=?", (source_id,)).fetchone()
                if not wo:
                    raise ValueError("رقم التشغيل غير موجود")
                # الطقم المباع يُعدَّل توريده أيضاً: تصحيح وزن مُدخل
                # خطأً واجب سواء بقي بالمخزن أو خرج. القيد العكسي
                # يُلغي أثر التوريد القديم كاملاً ويُرحَّل الجديد،
                # فالميزان يبقى سليماً وفاتورة البيع تظل قائمة على
                # الطقم نفسه بوزنه المصحَّح.
                # نقرأ **حصة الدفعة** من سطورها المحفوظة لا من رصيد
                # الطقم: الرقم التجميعي 0001 تراكمي، فرصيده يشمل كل
                # الدفعات السابقة ولا يمثل ما أُدخل هنا.
                lines = conn.execute(
                    "SELECT * FROM wo_batch_lines WHERE entry_id=?"
                    " ORDER BY seq, id", (wo["entry_id"],)).fetchall()
                if lines:
                    rows = lines
                    src = "batch"
                else:
                    rows = conn.execute(
                        "SELECT * FROM work_orders WHERE entry_id=?"
                        " AND is_deleted=0 ORDER BY id",
                        (wo["entry_id"],)).fetchall()
                    src = "wo"
                # وجهة الدفعة من قيدها نفسه — لا من عمودٍ مستقل
                dline = inventory.batch_dest_line(conn, wo["entry_id"])
                dkarat = inventory.batch_dest_karat(conn, wo["entry_id"])
                dref = inventory.batch_reference(conn, wo["entry_id"])
            # المخزَّن بمكافئ 18 ← المعروض بعيار سطره
            if src == "batch":
                self.batch = [_to_view({
                    "model_no": r["model_no"] or "",
                    "wo_no": r["wo_no"], "gold": r["gold"],
                    "small_stones": r["small_stones"],
                    "big_stones": r["big_stones"],
                    "discount_rate": r["discount_rate"],
                    "wage_per_gram": r["wage_per_gram"],
                    "karat": (r["karat"] if "karat" in r.keys() else 0),
                    "notes": r["notes"] or ""}) for r in rows]
            else:
                self.batch = [_to_view({
                    "model_no": (r["model_no"] if "model_no" in r.keys()
                                 else "") or "",
                    "wo_no": r["work_order_no"], "gold": r["gold_weight"],
                    "small_stones": r["small_stones"],
                    "big_stones": r["big_stones"],
                    "discount_rate": r["discount_rate"],
                    "wage_per_gram": r["wage_per_gram"], "karat": 0,
                    "notes": r["notes"] or ""}) for r in rows]
            # التاريخ يبقى تاريخ العملية الأصلي: التعديل تصحيح لا
            # عملية جديدة، فتغيير تاريخه يُزحزح الأرصدة التاريخية.
            try:
                with db() as conn:
                    e = conn.execute(
                        "SELECT entry_date FROM journal_entries WHERE id=?",
                        (wo["entry_id"],)).fetchone()
                if e and e["entry_date"]:
                    self.date.setDate(QtCore.QDate.fromString(
                        e["entry_date"], "yyyy-MM-dd"))
            except Exception:
                pass
            # حساب الوجهة الأصلي يعود معها: التعديل لا يُدخل البضاعة
            # مخزناً غير الذي دخلته أولاً إلا باختيارٍ صريح.
            self._select_dest(dline["code"] if dline else None,
                              dkarat or None)
            self.reference.setText(dref or "")
            self.render_batch()
            self.begin_edit(wo["entry_id"], source_id)
        except Exception as e:
            err(self, e)

    def on_edit_cancelled(self):
        self.batch = []
        self.render_batch()

    def refresh(self):
        # اقتراح الموديلات المسجّلة سابقاً
        try:
            from models import models_catalog as _mc
            with db() as conn:
                names = _mc.model_names(conn)
            cur = self.model_no.currentText()
            self.model_no.clear()
            self.model_no.addItems(names)
            self.model_no.setCurrentText(cur)
        except Exception:
            pass
        with db() as conn:
            if not self.wo_no.text().strip():
                self.wo_no.setPlaceholderText(
                    f"مقترح: {inventory.next_wo_no(conn)}")
            snap = inventory.stock_snapshot(conn)
            self._reload_dests(conn)
        self.tazeena_label.setText(
            f"رصيد خزينة التصنيع: {kv.g(snap['tazeena_gold']):.2f} "
            f"جم {kv.label()}   |   "
            f"الذهب المشغول: {kv.g(snap['mashghool_gold']):.2f} جم "
            f"({snap['wo_count']} طقم)")
        self.render_batch()
        self._restore_draft()
