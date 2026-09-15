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
import calendar

from PyQt5 import QtCore, QtWidgets

from database.database import db
from models import mfg_costs
from ui.widgets.common import (ask, big_label, err, info, make_table,
                               title_label)

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
    ("name", "اسم العامل", True),
    ("basic_salary", "الأساسي", False),
    ("hours", "ساعات", True),
    ("overtime_rate", "معامل", False),
    ("overtime", "الإضافي", True),
    ("absence", "الغياب", True),
    ("deduction", "الخصم", False),
    ("gold_loss", "الفاقد/ذهب", False),
    ("gold_deduction", "خصم/ذهب", False),
    ("target_amount", "التارجت", False),
    ("bonus", "المكافأة", False),
    # السحوبات محذوفة من العرض: تظهر في كشف حساب العامل نفسه،
    # ووجودها هنا يُكرّر المعلومة ويوسّع الجدول بلا فائدة.
    # (تُحتسب في الصافي كما كانت — الحذف من العرض لا من المحاسبة)
    ("net_salary", "الصافي", True),
]


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
    try:
        return f"{float(v or 0):,.{d}f}"
    except Exception:
        return "0.00"


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

        head = QtWidgets.QHBoxLayout()
        head.addWidget(QtWidgets.QLabel("الشهر:"))
        head.addWidget(self.month)
        head.addWidget(self.year)
        head.addWidget(btn_reload)
        head.addStretch(1)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._target_tab(), "التارجت")
        self.tabs.addTab(self._salary_tab(), "رواتب العمال")
        self.tabs.addTab(self._summary_tab(), "الملخص")

        # شريط مسح بيانات الشهر — فوق شريط الشهر مباشرةً
        wipe_row = QtWidgets.QHBoxLayout()
        btn_wipe = QtWidgets.QPushButton(
            "🔥 مسح بيانات هذا الشهر (تارجت ورواتب)")
        btn_wipe.setObjectName("dangerBtn")
        btn_wipe.setToolTip(
            "يمسح صفوف التارجت والرواتب غير المرحَّلة للشهر المحدد")
        btn_wipe.clicked.connect(self.wipe_month)
        wipe_row.addWidget(btn_wipe)
        wipe_row.addStretch(1)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("تكاليف ورواتب قسم التصنيع"))
        lay.addLayout(wipe_row)
        lay.addLayout(head)
        lay.addWidget(self.tabs, 1)

    # ══════════ التبويب الأول: التارجت ══════════
    def _target_tab(self):
        w = QtWidgets.QWidget()
        self.t_table = VerticalEnterTable()
        self._setup_table(self.t_table)
        self.t_table.cellChanged.connect(self.on_target_edit)
        btn_save = QtWidgets.QPushButton("💾 حفظ التارجت")
        btn_save.setObjectName("homeBtn")
        btn_save.clicked.connect(self.save_targets)
        btn_print_t = QtWidgets.QPushButton("🖨 طباعة")
        btn_print_t.clicked.connect(self.print_current)
        note = QtWidgets.QLabel(
            "الأعمدة المحسوبة (الخصم · المفترض إنتاجه · الفرق) تتحدّث "
            "تلقائياً ولا تُدخل يدوياً. اضغط Enter للانتقال للخلية "
            "التي أسفلها في نفس العمود.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(btn_save)
        row.addWidget(btn_print_t)
        row.addStretch(1)
        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(note)
        lay.addWidget(self.t_table, 1)
        lay.addLayout(row)
        return w

    # ══════════ التبويب الثاني: الرواتب ══════════
    def _salary_tab(self):
        w = QtWidgets.QWidget()
        self.s_table = VerticalEnterTable()
        self._setup_table(self.s_table)
        self.s_table.cellChanged.connect(self.on_salary_edit)

        self.s_date = QtWidgets.QDateEdit()
        self.s_date.setCalendarPopup(True)
        self.s_date.setDisplayFormat("yyyy-MM-dd")
        self.s_date.setDate(QtCore.QDate.currentDate())

        btn_save = QtWidgets.QPushButton("💾 حفظ")
        btn_save.clicked.connect(self.save_salaries)
        btn_post = QtWidgets.QPushButton("📥 إنزال رواتب العمال")
        btn_post.setObjectName("homeBtn")
        btn_post.clicked.connect(self.post_salaries)
        btn_print = QtWidgets.QPushButton("🖨 طباعة")
        btn_print.clicked.connect(self.print_current)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("تاريخ القيد:"))
        row.addWidget(self.s_date)
        row.addWidget(btn_save)
        row.addWidget(btn_post)
        row.addWidget(btn_print)
        row.addStretch(1)

        note = QtWidgets.QLabel(
            "الساعات والغياب والخصم تُجلب من شاشة التارجت، والسحوبات "
            "من سندات الصرف المسجّلة على حساب العامل خلال الشهر. "
            "الصافي = (الأساسي + الإضافي + التارجت + المكافأة) − "
            "(الخصم + خصم/ذهب + السحوبات).")
        note.setObjectName("cardSub")
        note.setWordWrap(True)

        self.s_total = big_label("")
        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(note)
        lay.addLayout(row)
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

    def _setup_table(self, t):
        t.setAlternatingRowColors(True)
        t.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectItems)
        t.verticalHeader().setVisible(False)
        t.verticalHeader().setDefaultSectionSize(34)
        hh = t.horizontalHeader()
        # الأعمدة تتوزّع على عرض الشاشة كاملاً فلا يُقصّ أو يختفي عمود،
        # ولا يظهر شريط تمرير أفقي إطلاقاً.
        hh.setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        hh.setMinimumSectionSize(44)
        hh.setStretchLastSection(False)
        hh.setDefaultAlignment(QtCore.Qt.AlignCenter)
        t.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        # لفّ العناوين والنصوص داخل خاناتها بدل تصغير الخط
        t.setWordWrap(True)
        t.setTextElideMode(QtCore.Qt.ElideNone)
        t.verticalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeToContents)

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
                    txt = v if key == "name" else _num(v)
                    it = QtWidgets.QTableWidgetItem(str(txt))
                    it.setTextAlignment(QtCore.Qt.AlignCenter)
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
                    r[key] = float(str(it.text()).replace(",", "") or 0)
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

    def _update_total(self):
        tot = sum(float(r.get("net_salary") or 0) for r in self.salary_rows)
        n = len([r for r in self.salary_rows
                 if float(r.get("net_salary") or 0)])
        self.s_total.setText(
            f"{n} عامل   |   إجمالي الرواتب الصافية: {tot:,.2f} ريال")

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
            date = self.s_date.date().toString("yyyy-MM-dd")
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

    def wipe_month(self):
        """يمسح بيانات الشهر المحدد — التارجت والرواتب غير المرحَّلة.

        لا يمسّ القيود المرحَّلة: الرواتب التي أُنزلت محاسبياً تبقى
        كما هي، فلا يختلّ أي ميزان. تُحذف بيانات الإدخال فقط.
        """
        try:
            per = self.period()
            with db() as conn:
                posted = conn.execute(
                    "SELECT COUNT(*) c FROM mfg_salaries"
                    " WHERE period=? AND is_posted=1", (per,)).fetchone()["c"]
            msg = (f"مسح بيانات شهر {self.period_label()}؟\n\n"
                   f"سيُحذف: صفوف التارجت + صفوف الرواتب غير المرحَّلة.")
            if posted:
                msg += (f"\n\n⚠ يوجد {posted} راتب مُرحَّل محاسبياً — "
                        f"لن يُمسّ ويبقى قيده كما هو.")
            msg += "\n\nلا يمكن التراجع."
            if not ask(self, msg):
                return
            with db() as conn:
                n1 = conn.execute("DELETE FROM mfg_targets WHERE period=?",
                                  (per,)).rowcount or 0
                n2 = conn.execute(
                    "DELETE FROM mfg_salaries WHERE period=?"
                    " AND COALESCE(is_posted,0)=0", (per,)).rowcount or 0
            info(self, f"مُسحت بيانات {self.period_label()}.\n"
                       f"تارجت: {n1} صف   ·   رواتب: {n2} صف"
                       + (f"\nبقي {posted} راتب مُرحَّل بلا مساس."
                          if posted else ""))
            self.reload()
        except Exception as e:
            err(self, e)

    def period_label(self):
        return f"{MONTHS[self.month.currentIndex()]} {int(self.year.value())}"

    def refresh(self):
        self.reload()
