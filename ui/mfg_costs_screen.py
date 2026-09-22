# -*- coding: utf-8 -*-
"""شاشة تكاليف ورواتب قسم التصنيع.

ثلاثة تبويبات:
* **التارجت** — جدول إدخال بأعمدة محسوبة تلقائياً.
* **رواتب العمال** — مرتبط ديناميكياً بالتارجت وسندات الصرف، وبه زر
  الترحيل المحاسبي.
* **الملخص** — إجماليات الشهر ومقارنة الإنتاج بالمستهدف.

**تسريع الإدخال**: زر Enter ينقل المؤشر للخلية **أسفلها في نفس
العمود** بدل الانتقال أفقياً — وهو ما يناسب إدخال عمود كامل دفعةً.
"""
from PyQt5 import QtCore, QtWidgets

from database.database import db
from models import mfg_costs
from ui.widgets.common import (ask, big_label, dstr, err, info, make_table, title_label)

MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو",
          "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]

# (المفتاح، العنوان، للقراءة فقط)
TARGET_COLS = [
    ("name", "الاسم", True),
    ("month_days", "أيام", False),
    ("hours", "ساعات", False),
    ("overtime_hours", "إضافية", False),
    ("absence", "الغياب", False),
    ("deduction", "الخصم", True),
    ("overtime_month", "إضافية/شهر", True),
    ("target_per_hour", "تارجت/ساعة", True),
    ("expected_output", "المفترض", True),
    ("actual_output", "الفعلي", False),
    ("difference", "الفرق", True),
    ("target_amount", "التارجت", False),
]

SALARY_COLS = [
    ("name", "اسم العامل", False),        # يُعدَّل ويتبعه دليل الحسابات
    ("basic_salary", "الأساسي", False),
    # **ساعات الإضافي لا ساعات الدوام**: العمود الثالث كان «ساعات»
    # فيُضرب معاملُ الإضافي في ساعات الشهر كلها ويصير «الإضافي»
    # راتباً ثانياً. الصواب عمود «إضافية» من شاشة التارجت.
    ("overtime_hours", "إضافية", True),
    ("overtime_rate", "معامل", False),
    ("overtime", "الإضافي", True),
    ("absence", "الغياب", True),
    ("deduction", "الخصم", False),
    ("gold_loss", "الفاقد/ذهب", False),
    ("gold_deduction", "خصم/ذهب", False),
    ("target_amount", "التارجت", False),
    ("bonus", "المكافأة", False),
    ("net_salary", "الصافي", True),
    # **عليه (مدين)**: رصيدُ العامل في كشف حسابه إلى هذه اللحظة —
    # يُعرض إن كان مديناً (أخذ أكثر مما استحقّ)، ويُترك فارغاً إن
    # كان دائناً. وهو أصدق من «مسحوبات الشهر» لأنه يحمل باقي
    # الشهور السابقة أيضاً. والمستحق = الصافي − عليه.
    # الاثنان للعرض والطباعة وحدهما: **الصافي** هو ما يُنزَل في
    # حساب كل عامل عند الترحيل.
    ("owed", "عليه (مدين)", True),
    ("due", "المستحق", True),
]

# أعمدةٌ يُترك فيها الصفر فراغاً لا «0.00»
BLANK_IF_ZERO = {"owed"}

# أوزان أعمدة الجدولين — تُوزَّع على العرض المتاح بلا تمرير أفقي
# ولا سحبٍ باليد. الاسم أعرضها لأنه نصٌّ، والباقي أرقام.
TARGET_W = [20, 7, 7, 7, 7, 7, 9, 9, 8, 8, 7, 8]
SALARY_W = [19, 8, 7, 6, 7, 6, 7, 7, 7, 7, 7, 8, 8, 8]


class VerticalEnterTable(QtWidgets.QTableWidget):
    """جدول ينقل المؤشر لأسفل عند Enter — لتسريع إدخال عمود كامل.

    **سبب الانهيار السابق**: كان المعالج ينادي `setCurrentCell` أثناء
    حالة التحرير، فيُطلق `cellChanged` الذي يعيد بناء الجدول كاملاً،
    فتصبح العناصر التي يشير إليها Qt معلَّقة (dangling) وينهار البرنامج.

    **الحل**: إنهاء التحرير بـ`closePersistentEditor`/`commitData` أولاً،
    ثم تأجيل نقل التركيز إلى دورة أحداث لاحقة عبر `QTimer.singleShot`
    فيكتمل إعادة البناء قبل لمس أي خلية. وكل شيء داخل `try` فلا يمكن
    لاستثناء أن يُسقط النافذة.
    """

    def keyPressEvent(self, e):
        try:
            if e.key() not in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                super().keyPressEvent(e)
                return
            r, c = self.currentRow(), self.currentColumn()
            # أنهِ التحرير بأمان ليُحفظ ما كُتب قبل أي إعادة بناء
            ed = self.indexWidget(self.currentIndex()) if hasattr(
                self, "indexWidget") else None
            if ed is not None:
                try:
                    self.commitData(ed)
                    self.closeEditor(
                        ed, QtWidgets.QAbstractItemDelegate.NoHint)
                except Exception:
                    pass
            QtCore.QTimer.singleShot(0, lambda: self._move_down(r, c))
        except Exception:
            # لا يجوز لخطأ في التنقّل أن يُغلق النظام
            pass

    def _move_down(self, r, c):
        """ينقل التركيز للخلية القابلة للتحرير أسفل الحالية."""
        try:
            rows = self.rowCount()
            if rows <= 1 or c < 0:
                return
            nxt = r + 1
            # الصف الأخير هو صف الإجمالي — يُتخطّى
            while nxt < rows - 1:
                it = self.item(nxt, c)
                if it is not None and (it.flags() & QtCore.Qt.ItemIsEditable):
                    break
                nxt += 1
            if nxt >= rows - 1:
                return
            self.setCurrentCell(nxt, c)
            it = self.item(nxt, c)
            if it is not None:
                self.editItem(it)
        except Exception:
            pass


def _num(v, d=2):
    """السالب بين قوسين — لا بإشارةٍ تزيغ في نصٍّ عربي.

    الإشارة الأمامية تُرمى في السطر العربي إلى آخر الرقم، فيُقرأ
    «571.66-» موجباً وهو سالب. والقوسان عُرف المحاسبة للسالب،
    وهما لا يزيغان مع اتجاه الكتابة.
    """
    try:
        f = float(v or 0)
    except Exception:
        return "0.00"
    return f"({abs(f):,.{d}f})" if f < 0 else f"{f:,.{d}f}"


def _val(text):
    """يقرأ ما كتبه `_num` — والقوسان سالبٌ لا زينة.

    الخلية تُعرض بالقوسين وتُقرأ كما هي عند الحفظ؛ فلو قُرئت قراءةً
    ساذجة لصار السالبُ صفراً في أول حفظٍ بلا تعديل.
    """
    s = str(text or "").strip().replace(",", "").replace("٬", "")
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1].strip()
    v = float(s or 0)
    return -v if neg else v


class MfgCostsScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.target_rows = []
        self.salary_rows = []
        self._loading = False

        today = QtCore.QDate.currentDate()
        self.month = QtWidgets.QComboBox()
        for i, m in enumerate(MONTHS, 1):
            self.month.addItem(m, i)
        self.month.setCurrentIndex(today.month() - 1)
        self.year = QtWidgets.QSpinBox()
        self.year.setRange(2000, 2100)
        self.year.setValue(today.year())
        self.month.currentIndexChanged.connect(self.reload)
        self.year.valueChanged.connect(self.reload)
        btn_reload = QtWidgets.QPushButton("↻ تحديث")
        btn_reload.clicked.connect(self.reload)

        self.s_date = QtWidgets.QDateEdit()
        self.s_date.setCalendarPopup(True)
        self.s_date.setDisplayFormat("yyyy-MM-dd")
        self.s_date.setDate(QtCore.QDate.currentDate())
        self.s_date.setMaximumWidth(130)

        btn_save = QtWidgets.QPushButton("💾 حفظ")
        btn_save.setToolTip("يحفظ التبويب المعروض — التارجت أو الرواتب")
        btn_save.clicked.connect(self.save_current)
        btn_post = QtWidgets.QPushButton("📥 إنزال رواتب العمال")
        btn_post.setObjectName("homeBtn")
        btn_post.clicked.connect(self.post_salaries)
        btn_print = QtWidgets.QPushButton("🖨 طباعة")
        btn_print.clicked.connect(self.print_current)
        btn_add = QtWidgets.QPushButton("➕ إضافة حساب")
        btn_add.setObjectName("ghost")
        btn_add.setToolTip("يضيف موظفاً من خارج عمال التصنيع لجدول الرواتب")
        btn_add.clicked.connect(self.add_staff)
        btn_drop = QtWidgets.QPushButton("➖ رفع المضاف")
        btn_drop.setObjectName("ghost")
        btn_drop.setToolTip("يرفع الصف المضاف يدوياً — لا يمسّ عمال القسم")
        btn_drop.clicked.connect(self.drop_staff)
        btn_up = QtWidgets.QPushButton("▲ أعلى")
        btn_up.setObjectName("ghost")
        btn_up.setMaximumWidth(90)
        btn_up.setToolTip("تحريك العامل المحدَّد لأعلى — الترتيب يُحفظ")
        btn_up.clicked.connect(lambda: self.move_staff(-1))
        btn_dn = QtWidgets.QPushButton("▼ أسفل")
        btn_dn.setObjectName("ghost")
        btn_dn.setMaximumWidth(90)
        btn_dn.setToolTip("تحريك العامل المحدَّد لأسفل — الترتيب يُحفظ")
        btn_dn.clicked.connect(lambda: self.move_staff(1))

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(QtWidgets.QLabel("الشهر:"))
        head.addWidget(self.month)
        head.addWidget(self.year)
        head.addWidget(btn_reload)
        head.addWidget(QtWidgets.QLabel("تاريخ القيد:"))
        head.addWidget(self.s_date)
        head.addWidget(btn_save)
        head.addWidget(btn_post)
        head.addWidget(btn_print)
        head.addWidget(btn_add)
        head.addWidget(btn_drop)
        head.addWidget(btn_up)
        head.addWidget(btn_dn)
        head.addStretch(1)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._target_tab(), "التارجت")
        self.tabs.addTab(self._salary_tab(), "رواتب العمال")
        self.tabs.addTab(self._summary_tab(), "الملخص")

        # ══ الأزرار كلُّها في شريطٍ واحد أعلى الشاشة ══
        # كانت موزّعةً: شريطُ مسحٍ فوق، وأزرارُ التارجت تحت جدوله،
        # وأزرارُ الرواتب فوق جدولها. فيختلف موضع الزرّ باختلاف
        # التبويب، ويأكل كلُّ شريطٍ سطراً من ارتفاع الجدول.
        # وزرُّ «مسح بيانات الشهر» حُذف: عمليةٌ لا رجعة فيها ليس
        # مكانُها شاشةَ إدخالٍ يومية.
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        lay.addWidget(title_label("تكاليف ورواتب قسم التصنيع"))
        lay.addLayout(head)
        lay.addWidget(self.tabs, 1)

    # ══════════ التبويب الأول: التارجت ══════════
    def _target_tab(self):
        w = QtWidgets.QWidget()
        self.t_table = VerticalEnterTable()
        self._setup_table(self.t_table, TARGET_W)
        self.t_table.cellChanged.connect(self.on_target_edit)
        note = QtWidgets.QLabel(
            "الأعمدة المحسوبة (الخصم · المفترض إنتاجه · الفرق) تتحدّث "
            "تلقائياً ولا تُدخل يدوياً. اضغط Enter للانتقال للخلية "
            "التي أسفلها في نفس العمود.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 2, 0, 0)
        lay.setSpacing(3)
        lay.addWidget(note)
        lay.addWidget(self.t_table, 1)
        return w

    # ══════════ التبويب الثاني: الرواتب ══════════
    def _salary_tab(self):
        w = QtWidgets.QWidget()
        self.s_table = VerticalEnterTable()
        self._setup_table(self.s_table, SALARY_W)
        self.s_table.cellChanged.connect(self.on_salary_edit)
        # نقرٌ مزدوج على «عليه» أو «المستحق» يفتح كشف حساب العامل
        self.s_table.cellDoubleClicked.connect(self.peek_ledger)

        # لا شرحَ تحت الجدول: الأعمدة تقول نفسها، والشرح يأكل سطراً
        # من ارتفاعٍ الجدولُ أحوجُ إليه. وما يحتاج بياناً فتلميحةٌ
        # على رأس عموده تكفيه.
        self.s_total = big_label("")
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 2, 0, 0)
        lay.setSpacing(3)
        lay.addWidget(self.s_table, 1)
        lay.addWidget(self.s_total)
        return w

    # ══════════ التبويب الثالث: الملخص ══════════
    def _summary_tab(self):
        w = QtWidgets.QWidget()
        self.sum_table = make_table()
        btn_add = QtWidgets.QPushButton("➕ إضافة حساب للملخص")
        btn_add.setToolTip("يضيف صفاً يعرض حركة حساب من دليل الحسابات")
        btn_add.clicked.connect(self.add_summary_account)
        btn_del = QtWidgets.QPushButton("🗑 حذف الصف المحدد")
        btn_del.setToolTip(
            "الصف المضاف يُحذف نهائياً، والأساسي يُخفى")
        btn_del.clicked.connect(self.del_summary_row)
        btn_reset = QtWidgets.QPushButton("↺ استعادة الصفوف الأساسية")
        btn_reset.clicked.connect(self.reset_summary)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(btn_add)
        row.addWidget(btn_del)
        row.addWidget(btn_reset)
        row.addStretch(1)
        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(QtWidgets.QLabel(
            "ملخص أداء وتكاليف قسم التصنيع للشهر المحدد:"))
        lay.addLayout(row)
        lay.addWidget(self.sum_table, 1)
        return w

    # ══════════ تخصيص الملخص ══════════
    def add_summary_account(self):
        """يضيف صفاً للملخص يعرض حركة حساب خلال الشهر."""
        try:
            with db() as conn:
                accs = [dict(r) for r in conn.execute(
                    "SELECT code, name FROM accounts ORDER BY code")]
            items = [f"{a['code']} — {a['name']}" for a in accs]
            if not items:
                raise ValueError("لا توجد حسابات")
            txt, ok = QtWidgets.QInputDialog.getItem(
                self, "إضافة حساب للملخص",
                "اختر الحساب (يُعرض إجمالي حركته وفروعه في الشهر):",
                items, 0, True)
            if not ok or not txt:
                return
            code = str(txt).split("—")[0].strip()
            name = next((a["name"] for a in accs if a["code"] == code),
                        code)
            cfg = mfg_costs.load_summary_config()
            if any(x.get("code") == code for x in cfg["accounts"]):
                raise ValueError("هذا الحساب مضاف مسبقاً")
            cfg["accounts"].append({"code": code, "name": name})
            mfg_costs.save_summary_config(cfg)
            self.reload()
        except Exception as e:
            err(self, e)

    def del_summary_row(self):
        """يحذف الصف المضاف أو يُخفي الأساسي."""
        try:
            i = self.sum_table.currentRow()
            it = self.sum_table.item(i, 0) if i >= 0 else None
            if it is None:
                raise ValueError("اختر صفاً من الجدول أولاً")
            label = it.text().strip()
            if label == "الإجمالي":
                raise ValueError("صف الإجمالي لا يُحذف")
            cfg = mfg_costs.load_summary_config()
            # صف مضاف؟
            before = len(cfg["accounts"])
            cfg["accounts"] = [x for x in cfg["accounts"]
                               if (x.get("name") or x.get("code")) != label]
            if len(cfg["accounts"]) == before:
                # صف أساسي → يُخفى
                key = next((k for k, t in mfg_costs.SUMMARY_KEYS
                            if t == label), None)
                if key is None:
                    raise ValueError("تعذّر تحديد الصف")
                if not ask(self, f"إخفاء صف «{label}» من الملخص؟"):
                    return
                if key not in cfg["hidden"]:
                    cfg["hidden"].append(key)
            mfg_costs.save_summary_config(cfg)
            self.reload()
        except Exception as e:
            err(self, e)

    def reset_summary(self):
        """يستعيد كل الصفوف الأساسية ويُبقي المضافة."""
        try:
            cfg = mfg_costs.load_summary_config()
            cfg["hidden"] = []
            mfg_costs.save_summary_config(cfg)
            self.reload()
        except Exception as e:
            err(self, e)

    def _setup_table(self, t, weights=None):
        """جدولٌ مرتّب لا يتمدّد ولا يُسحب عموده باليد.

        **الوزن لا التساوي**: `Stretch` يعطي كل عمودٍ العرض نفسه،
        فيضيق عمود الاسم — وهو النصّ الوحيد — ويتّسع عمودُ «معامل»
        وفيه رقمٌ من خانتين. الأوزان تعطي كلاً بقدر ما يحمل.
        """
        from ui.widgets.table_fit import fit_columns
        t.setAlternatingRowColors(True)
        t.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectItems)
        vh = t.verticalHeader()
        vh.setVisible(False)
        vh.setDefaultSectionSize(32)
        vh.setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
        hh = t.horizontalHeader()
        hh.setMinimumSectionSize(40)
        hh.setStretchLastSection(False)
        hh.setDefaultAlignment(QtCore.Qt.AlignCenter)
        try:
            hh.setTextElideMode(QtCore.Qt.ElideNone)
        except Exception:
            pass
        t.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        t.setWordWrap(True)
        t.setTextElideMode(QtCore.Qt.ElideNone)
        fit_columns(t, list(weights or []), min_px=40)

    # ══════════ العرض ══════════
    def period(self):
        return f"{int(self.year.value()):04d}-{int(self.month.currentData()):02d}"

    def _fill(self, table, cols, rows, totals_skip=("name",)):
        """يملأ الجدول ويضيف صف إجمالي في الأسفل."""
        self._loading = True
        try:
            table.clear()
            table.setColumnCount(len(cols))
            table.setRowCount(len(rows) + 1)
            table.setHorizontalHeaderLabels([c[1] for c in cols])
            for i, r in enumerate(rows):
                for j, (key, _, ro) in enumerate(cols):
                    v = r.get(key, "")
                    if key == "name":
                        txt = v
                    elif key in BLANK_IF_ZERO and not float(v or 0):
                        # صفرٌ في خانةٍ معناها «عليه» يُقرأ رقماً
                        # محسوباً؛ والفراغ يقول «لا شيء عليه» بصدق.
                        txt = ""
                    else:
                        txt = _num(v)
                    it = QtWidgets.QTableWidgetItem(str(txt))
                    it.setTextAlignment(QtCore.Qt.AlignCenter)
                    if key == "owed":
                        it.setToolTip(
                            "رصيده في كشف حسابه الآن — يظهر إن كان "
                            "مديناً، ويبقى فارغاً إن كان دائناً")
                    if not ro:
                        it.setFlags(it.flags() | QtCore.Qt.ItemIsEditable)
                    if ro:
                        it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
                        it.setBackground(QtCore.Qt.lightGray)
                    table.setItem(i, j, it)
            # صف الإجمالي
            last = len(rows)
            for j, (key, _, _) in enumerate(cols):
                if key in totals_skip:
                    txt = "الإجمالي"
                else:
                    tot = sum(float(r.get(key) or 0) for r in rows)
                    txt = _num(tot)
                it = QtWidgets.QTableWidgetItem(txt)
                it.setTextAlignment(QtCore.Qt.AlignCenter)
                it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
                f = it.font()
                f.setBold(True)
                it.setFont(f)
                table.setItem(last, j, it)
            # عددُ الأعمدة قد يتغيّر بين تبويبٍ وآخر، والمُحجِّم يعيد
            # التوزيع عند تغيّره — لكنه لا يسمع تغييراً لم يُصحبه
            # حدثُ حجم، فيُطلب منه صراحةً بعد كل تعبئة.
            f = table.property("_fitter")
            if f is not None:
                try:
                    f.refit()
                except Exception:
                    pass
        finally:
            self._loading = False

    def _read(self, table, cols, rows):
        """يقرأ القيم المُدخلة من الجدول إلى الصفوف."""
        for i, r in enumerate(rows):
            for j, (key, _, ro) in enumerate(cols):
                if ro or key == "name":
                    continue
                it = table.item(i, j)
                if it is None:
                    continue
                try:
                    r[key] = _val(it.text())
                except ValueError:
                    r[key] = 0.0
        return rows

    # ══════════ الأحداث ══════════
    def on_target_edit(self, *_):
        if self._loading:
            return
        self._read(self.t_table, TARGET_COLS, self.target_rows)
        for r in self.target_rows:
            r.update(mfg_costs.compute_target_row(r))
        cur = (self.t_table.currentRow(), self.t_table.currentColumn())
        self._fill(self.t_table, TARGET_COLS, self.target_rows)
        self.t_table.setCurrentCell(*cur)

    def on_salary_edit(self, *_):
        if self._loading:
            return
        col = self.s_table.currentColumn()
        edited = SALARY_COLS[col][0] if 0 <= col < len(SALARY_COLS) else ""
        if edited == "name":
            self._rename_worker()
            return
        self._read(self.s_table, SALARY_COLS, self.salary_rows)
        for i, r in enumerate(self.salary_rows):
            # الكتابة في خانة الخصم تعني خصماً يدوياً يتجاوز المعادلة
            if edited == "deduction" and i == self.s_table.currentRow():
                r["deduction_manual"] = r.get("deduction") or 0
            # تعديل الأساسي أو الغياب يُعيد الحساب التلقائي
            elif edited in ("basic_salary", "absence"):
                r["deduction_manual"] = 0
            r.update(mfg_costs.compute_salary_row(r))
        cur = (self.s_table.currentRow(), self.s_table.currentColumn())
        self._fill(self.s_table, SALARY_COLS, self.salary_rows)
        self.s_table.setCurrentCell(*cur)
        self._update_total()

    def _rename_worker(self):
        """اسمٌ يُكتب في الخانة يُعاد تسميته في **دليل الحسابات**.

        الاسم يُخزَّن في ثلاثة مواضع: الحساب، والجهة، وسجلّ الموظف.
        فتغييرُه هنا وحده يجعل الجدول يقول اسماً وكشفُ الحساب آخر —
        ولا يُصدَّق نظامٌ يسمّي الرجل باسمين. لذلك يمرّ التعديل من
        `coa.rename_account` وهو الذي يُزامن المواضع الثلاثة.
        """
        r = self.s_table.currentRow()
        it = self.s_table.item(r, 0)
        if it is None or not (0 <= r < len(self.salary_rows)):
            return
        new = str(it.text()).strip()
        row = self.salary_rows[r]
        old = str(row.get("name") or "").strip()
        if not new or new == old:
            self._fill(self.s_table, SALARY_COLS, self.salary_rows)
            return
        try:
            from models import coa
            with db() as conn:
                ent = conn.execute(
                    "SELECT account_id FROM entities WHERE employee_id=?"
                    " AND is_deleted=0", (row.get("employee_id"),)
                ).fetchone()
                if not ent or not ent["account_id"]:
                    raise ValueError(f"«{old}» بلا حساب في الشجرة")
                coa.rename_account(conn, ent["account_id"], new,
                                   self.user["username"])
            info(self, f"أُعيدت التسمية: «{old}» ← «{new}»\n"
                       "وتبعها اسمُ الحساب في الدليل وكشوفه.")
        except Exception as e:
            err(self, e)
        self.reload()

    def save_current(self):
        """يحفظ التبويب المعروض — فزرٌّ واحد يكفي التبويبين."""
        if self.tabs.currentIndex() == 0:
            self.save_targets()
        else:
            self.save_salaries()

    # ══════════ إضافة حسابٍ لجدول الرواتب ══════════
    def add_staff(self):
        """يضيف موظفاً من خارج عمال التصنيع لجدول الرواتب."""
        try:
            from models import payroll
            with db() as conn:
                have = {r.get("employee_id") for r in self.salary_rows}
                people = [e for e in payroll.list_employees(conn)
                          if e["id"] not in have]
            if not people:
                raise ValueError("كل الموظفين مضافون مسبقاً")
            items = [f"{e['name']}   (#{e['id']})" for e in people]
            txt, ok = QtWidgets.QInputDialog.getItem(
                self, "إضافة حساب لجدول الرواتب",
                "اختر الموظف — يُضاف صفُّه ويبقى حتى ترفعه:",
                items, 0, True)
            if not ok or not txt:
                return
            pick = people[items.index(txt)] if txt in items else None
            if pick is None:
                raise ValueError("اختر اسماً من القائمة")
            ids = mfg_costs.load_extra_staff()
            if pick["id"] not in ids:
                ids.append(pick["id"])
            mfg_costs.save_extra_staff(ids)
            self.reload()
            info(self, f"أُضيف «{pick['name']}» لجدول الرواتب.")
        except Exception as e:
            err(self, e)

    def drop_staff(self):
        """يرفع صفاً مضافاً يدوياً — ولا يمسّ عمال القسم."""
        try:
            r = self.s_table.currentRow()
            if not (0 <= r < len(self.salary_rows)):
                raise ValueError("اختر صفاً من جدول الرواتب أولاً")
            row = self.salary_rows[r]
            if not row.get("is_extra"):
                raise ValueError(
                    f"«{row.get('name')}» من عمال قسم التصنيع — "
                    "يُرفع من دليل الجهات لا من هنا")
            if not ask(self, f"رفع «{row.get('name')}» من جدول الرواتب؟\n"
                             "لا يُحذف الموظف ولا قيوده — يُرفع صفُّه فقط."):
                return
            ids = [i for i in mfg_costs.load_extra_staff()
                   if i != row.get("employee_id")]
            mfg_costs.save_extra_staff(ids)
            self.reload()
        except Exception as e:
            err(self, e)

    # ══════════ كشف حساب العامل ══════════
    def peek_ledger(self, row=None, col=None):
        """نقرٌ مزدوج على «عليه (مدين)» يفتح كشف حساب العامل.

        العمود يقول رقماً، وهذه النافذة تقول **من أين جاء**: راتبٌ
        مُرحَّل هنا وسندُ صرفٍ هناك. فمن رأى رقماً استغربه وجد جوابه
        في نقرةٍ واحدة بدل أن يخرج إلى شاشة كشف الحساب ويبحث.
        """
        try:
            keys = [c[0] for c in SALARY_COLS]
            if col is not None and keys[col] not in ("owed", "due", "name"):
                return
            r = row if row is not None else self.s_table.currentRow()
            if not (0 <= r < len(self.salary_rows)):
                raise ValueError("اختر عاملاً من الجدول أولاً")
            person = self.salary_rows[r]
            from models import journal
            with db(readonly=True) as conn:
                ent = conn.execute(
                    "SELECT account_id, name FROM entities"
                    " WHERE employee_id=? AND is_deleted=0",
                    (person.get("employee_id"),)).fetchone()
                if not ent or not ent["account_id"]:
                    raise ValueError("لا حساب لهذا العامل في الدليل")
                rows = journal.statement(conn, ent["account_id"],
                                         "1900-01-01", dstr(self.s_date))
            dlg = QtWidgets.QDialog(self)
            dlg.setWindowTitle(f"كشف حساب: {ent['name']}")
            dlg.resize(820, 480)
            t = make_table()
            cols = ["التاريخ", "العملية", "الجهة/البيان", "مدين",
                    "دائن", "الرصيد"]
            t.setColumnCount(len(cols))
            t.setHorizontalHeaderLabels(cols)
            t.setRowCount(len(rows))
            for i, x in enumerate(rows):
                d = float(x.get("cd") or 0)
                c = float(x.get("cc") or 0)
                vals = (x.get("date", ""), x.get("op", ""),
                        (x.get("desc") or x.get("name") or ""),
                        _num(d) if d else "", _num(c) if c else "",
                        _num(x.get("cbal") or 0))
                for j, v in enumerate(vals):
                    it = QtWidgets.QTableWidgetItem(str(v))
                    it.setTextAlignment(
                        QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
                        if j == 2 else QtCore.Qt.AlignCenter)
                    t.setItem(i, j, it)
            bal = float(rows[-1].get("cbal") or 0) if rows else 0.0
            lbl = big_label(
                f"الرصيد الآن: {_num(abs(bal))} ريال  "
                + ("عليه (مدين)" if bal > 0.004 else
                   "له (دائن)" if bal < -0.004 else "صفر"))
            lay = QtWidgets.QVBoxLayout(dlg)
            lay.addWidget(lbl)
            lay.addWidget(t, 1)
            box = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.Close)
            box.rejected.connect(dlg.reject)
            lay.addWidget(box)
            try:
                from ui.widgets.table_fit import fit_columns
                fit_columns(t, [13, 15, 33, 13, 13, 13])
            except Exception:
                pass
            dlg.exec_()
        except Exception as e:
            err(self, e)

    # ══════════ ترتيب الأسماء ══════════
    def move_staff(self, delta):
        """يحرّك العامل المحدَّد في ترتيب الجدولين معاً.

        الترتيب واحدٌ للتارجت وللرواتب: لو اختلفا لقرأ المستخدم
        الاسم في سطرٍ هنا وسطرٍ آخر هناك، فيُقارن صفّاً بصفٍّ ليس له.
        وهو عرضٌ محض — لا يمسّ راتباً ولا قيداً.
        """
        try:
            salary = self.tabs.currentIndex() == 1
            table = self.s_table if salary else self.t_table
            rows = self.salary_rows if salary else self.target_rows
            if self.tabs.currentIndex() == 2:
                raise ValueError("الترتيب في جدولَي التارجت والرواتب")
            i = table.currentRow()
            if not (0 <= i < len(rows)):
                raise ValueError("اختر عاملاً من الجدول أولاً")
            j = i + delta
            if not (0 <= j < len(rows)):
                return
            order = [r.get("employee_id") for r in rows
                     if r.get("employee_id")]
            if len(order) != len(rows):
                raise ValueError("تعذّر قراءة ترتيب الأسماء")
            order[i], order[j] = order[j], order[i]
            # الأسماء التي لا تظهر في هذا الجدول تبقى خلفهم بترتيبها
            rest = [x for x in mfg_costs.load_staff_order()
                    if x not in set(order)]
            mfg_costs.save_staff_order(order + rest)
            self.reload()
            table.setCurrentCell(j, 0)
        except Exception as e:
            err(self, e)

    def _update_total(self):
        tot = sum(float(r.get("net_salary") or 0) for r in self.salary_rows)
        ow = sum(float(r.get("owed") or 0) for r in self.salary_rows)
        n = len([r for r in self.salary_rows
                 if float(r.get("net_salary") or 0)])
        self.s_total.setText(
            f"{n} عامل   |   الصافي: {tot:,.2f}   |   عليهم (مدين): "
            f"{ow:,.2f}   |   المستحق: {tot - ow:,.2f} ريال")

    # ══════════ الإجراءات ══════════
    def reload(self):
        try:
            per = self.period()
            with db() as conn:
                self.target_rows = mfg_costs.list_targets(conn, per)
                self.salary_rows = mfg_costs.list_salaries(conn, per)
            self._fill(self.t_table, TARGET_COLS, self.target_rows)
            self._fill(self.s_table, SALARY_COLS, self.salary_rows)
            self._update_total()
            self._fill_summary()
        except Exception as e:
            err(self, e)

    def _fill_summary(self):
        """ملخص القسم: الاسم · المبلغ · الذهب، مع صف إجمالي."""
        from ui.widgets.common import fill
        try:
            with db() as conn:
                rows = mfg_costs.summary(conn, self.period())
        except Exception:
            rows = []
        fill(self.sum_table, ["الاسم", "المبلغ", "الذهب"],
             [(n, _num(c), _num(g)) for n, c, g in rows])
        # إبراز صف الإجمالي
        last = self.sum_table.rowCount() - 1
        if last >= 0:
            for j in range(self.sum_table.columnCount()):
                it = self.sum_table.item(last, j)
                if it:
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
        return

    def _fill_summary_old(self):
        from ui.widgets.common import fill
        t = self.target_rows
        s = self.salary_rows
        exp = sum(float(r.get("expected_output") or 0) for r in t)
        act = sum(float(r.get("actual_output") or 0) for r in t)
        rows = [
            ("عدد العمال", f"{len(t)}"),
            ("إجمالي الساعات", _num(sum(float(r.get('hours') or 0)
                                        for r in t))),
            ("إجمالي الغياب", _num(sum(float(r.get('absence') or 0)
                                       for r in t))),
            ("المفترض إنتاجه", _num(exp)),
            ("الإنتاج الفعلي", _num(act)),
            ("الفرق", _num(act - exp)),
            ("نسبة الإنجاز", f"{(act / exp * 100):,.1f}%" if exp else "—"),
            ("إجمالي الرواتب الأساسية",
             _num(sum(float(r.get('basic_salary') or 0) for r in s))),
            ("إجمالي الإضافي",
             _num(sum(float(r.get('overtime') or 0) for r in s))),
            ("إجمالي الخصومات",
             _num(sum(float(r.get('deduction') or 0)
                      + float(r.get('gold_deduction') or 0) for r in s))),
            ("إجمالي السحوبات",
             _num(sum(float(r.get('draw_cash') or 0)
                      + float(r.get('draw_bank') or 0) for r in s))),
            ("إجمالي الرواتب الصافية",
             _num(sum(float(r.get('net_salary') or 0) for r in s))),
        ]
        fill(self.sum_table, ["البند", "القيمة"], rows)

    def save_targets(self):
        try:
            self._read(self.t_table, TARGET_COLS, self.target_rows)
            for r in self.target_rows:
                r.update(mfg_costs.compute_target_row(r))
            with db() as conn:
                n = mfg_costs.save_targets(conn, self.period(),
                                           self.target_rows,
                                           self.user["username"])
            info(self, f"حُفظ تارجت {n} عامل.")
            self.reload()
        except Exception as e:
            err(self, e)

    def save_salaries(self):
        try:
            self._read(self.s_table, SALARY_COLS, self.salary_rows)
            for r in self.salary_rows:
                r.update(mfg_costs.compute_salary_row(r))
            with db() as conn:
                n = mfg_costs.save_salaries(conn, self.period(),
                                            self.salary_rows,
                                            self.user["username"])
            info(self, f"حُفظت رواتب {n} عامل.")
            self.reload()
        except Exception as e:
            err(self, e)

    def post_salaries(self):
        """يرحّل الرواتب بقيد مفصّل بسطرين لكل عامل."""
        try:
            self._read(self.s_table, SALARY_COLS, self.salary_rows)
            for r in self.salary_rows:
                r.update(mfg_costs.compute_salary_row(r))
            pending = [r for r in self.salary_rows
                       if float(r.get("net_salary") or 0)
                       and not r.get("is_posted")]
            if not pending:
                raise ValueError(
                    "لا توجد رواتب معلّقة — ربما رُحّلت مسبقاً")
            tot = sum(float(r["net_salary"]) for r in pending)
            date = dstr(self.s_date)
            if not ask(self,
                       f"ترحيل رواتب عمال التصنيع لشهر {self.period()}؟\n\n"
                       f"عدد العمال: {len(pending)}\n"
                       f"إجمالي الصافي: {tot:,.2f} ريال\n"
                       f"تاريخ القيد: {date}\n\n"
                       f"سيُنشأ قيد واحد بسطرين لكل عامل:\n"
                       f"  مدين حـ/ مصروف رواتب عمال التصنيع\n"
                       f"  دائن حـ/ حساب العامل"):
                return
            with db() as conn:
                mfg_costs.save_salaries(conn, self.period(),
                                        self.salary_rows,
                                        self.user["username"])
                res = mfg_costs.post_salaries(
                    conn, self.period(), self.user["username"],
                    entry_date=date, rows=self.salary_rows)
            info(self, f"تم الترحيل.\nعدد العمال: {res['count']}\n"
                       f"الإجمالي: {res['total']:,.2f} ريال\n\n"
                       f"يظهر في كشف مصروف رواتب العمال سطرٌ باسم كل "
                       f"عامل، وفي كشف حسابه راتبه دائناً.")
            self.reload()
        except Exception as e:
            err(self, e)

    def print_current(self):
        """يطبع التبويب المعروض حالياً بقالبه الخاص."""
        try:
            from services import print_manager
            kinds = {0: "mfg_target", 1: "mfg_salary", 2: "mfg_summary"}
            kind = kinds.get(self.tabs.currentIndex(), "mfg_summary")
            self._read(self.t_table, TARGET_COLS, self.target_rows)
            self._read(self.s_table, SALARY_COLS, self.salary_rows)
            for r in self.target_rows:
                r.update(mfg_costs.compute_target_row(r))
            for r in self.salary_rows:
                r.update(mfg_costs.compute_salary_row(r))
            print_manager.preview_document(
                self, kind, 0, period=self.period(),
                targets=self.target_rows, salaries=self.salary_rows)
        except Exception as e:
            err(self, e)

    def period_label(self):
        return f"{MONTHS[self.month.currentIndex()]} {int(self.year.value())}"

    def refresh(self):
        self.reload()
