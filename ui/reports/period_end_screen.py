# -*- coding: utf-8 -*-
"""تسويات نهاية الفترة والقوائم الختامية — قبل رفع القوائم المالية.

فترةٌ واحدة أعلى الشاشة تسري على كل التبويبات:

1. **القوائم الختامية**: قائمة تحقّقٍ قبل الرفع (الميزان · المخصصات ·
   الإطفاء · قفل الفترة)، وطباعة القوائم الكاملة مع الإيضاحات، وحزمةٌ
   للمحاسب القانوني / منصة «قوائم».
2. **الزكاة**: الوعاء الزكوي بنداً بنداً ومقدار الزكاة، وقيد المخصص.
3. **مكافأة نهاية الخدمة**: تاريخ التعيين والأجر لكل موظف، والمخصص.
4. **الديون المشكوك فيها**: مصفوفة المخصص على أعمار الذمم.
5. **المقدمة والمستحقة**: إطفاء المصروفات المدفوعة مقدماً واستحقاق ما
   لم تصل فاتورته.

كل تسوية تُقيَّد **بالفرق** عمّا قُيِّد قبلها — فإعادة الحساب لا تكرّر القيد.
"""
from datetime import date

from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from models import period_end as pe
from ui.widgets.common import (ask, big_label, date_edit, dstr, err, fill,
                               info, make_table, tab_widget, title_label)
from ui.widgets.flow_layout import FlowLayout


def _m(v):
    v = v or 0.0
    if abs(v) < 0.005:
        return "—"
    s = f"{abs(v):,.2f}"
    return f"({s})" if v < 0 else s


def _accounts(conn, where):
    return [(r["code"], f"{r['code']} — {r['name']}") for r in conn.execute(
        "SELECT a.code, a.name FROM accounts a WHERE a.is_postable=1 AND "
        + where + " ORDER BY a.code")]


class PeriodEndScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        today = date.today()
        self.d_from = date_edit()
        self.d_from.setDate(QtCore.QDate(today.year, 1, 1))
        self.d_to = date_edit()
        self.d_to.setDate(QtCore.QDate(today.year, 12, 31))
        self.cmp_on = QtWidgets.QCheckBox("مع المقارنة")
        self.cmp_on.setChecked(True)
        btn = QtWidgets.QPushButton("تحديث")
        btn.setObjectName("homeBtn")
        btn.clicked.connect(self.refresh_all)

        head = FlowLayout()
        head.addWidget(QtWidgets.QLabel("الفترة المالية من:"))
        head.addWidget(self.d_from)
        head.addWidget(QtWidgets.QLabel("إلى:"))
        head.addWidget(self.d_to)
        head.addWidget(self.cmp_on)
        head.addWidget(btn)
        head.addStretch(1)

        self.tabs = tab_widget()
        self.tabs.addTab(self._tab_close(), "القوائم الختامية وقائمة التحقق")
        self.tabs.addTab(self._tab_zakat(), "الزكاة")
        self.tabs.addTab(self._tab_eos(), "مكافأة نهاية الخدمة")
        self.tabs.addTab(self._tab_ecl(), "الديون المشكوك فيها")
        self.tabs.addTab(self._tab_prepaid(), "المقدمة والمستحقة")
        self.tabs.currentChanged.connect(lambda _i: self.refresh_all())

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        lay.addWidget(title_label(
            "تسويات نهاية الفترة والقوائم المالية الختامية"))
        lay.addLayout(head)
        lay.addWidget(self.tabs, 1)
        self.refresh_all()

    # ─────────────────────────────────────────── أدوات
    def _period(self):
        d1, d2 = dstr(self.d_from), dstr(self.d_to)
        if d1 > d2:
            raise ValueError("تاريخ «من» بعد تاريخ «إلى»")
        return d1, d2

    def _user(self):
        return (self.user or {}).get("username") or "admin"

    def refresh_all(self):
        i = self.tabs.currentIndex()
        try:
            (self.load_close, self.load_zakat, self.load_eos,
             self.load_ecl, self.load_prepaid)[i]()
        except Exception as e:
            err(self, e)

    # ═══════════════════════════════════════ 1) القوائم الختامية
    def _tab_close(self):
        w = QtWidgets.QWidget()
        self.chk = make_table()
        b_full = QtWidgets.QPushButton(
            "🖨 القوائم المالية الكاملة مع الإيضاحات")
        b_full.setObjectName("homeBtn")
        b_full.clicked.connect(lambda: self._print("fs_full"))
        b_notes = QtWidgets.QPushButton("🖨 الإيضاحات وحدها")
        b_notes.clicked.connect(lambda: self._print("fs_notes"))
        b_pkg = QtWidgets.QPushButton(
            "⬇ حزمة للمحاسب القانوني / منصة «قوائم»")
        b_pkg.setObjectName("ghost")
        b_pkg.clicked.connect(self.export_package)
        row = FlowLayout()
        for b in (b_full, b_notes, b_pkg):
            row.addWidget(b)
        row.addStretch(1)
        self.chk_status = big_label()
        self.chk_status.setWordWrap(True)
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.addLayout(row)
        lay.addWidget(self.chk, 1)
        lay.addWidget(self.chk_status)
        return w

    def load_close(self):
        from services import fs_package
        d1, d2 = self._period()
        with db(readonly=True) as conn:
            items = fs_package.readiness(conn, d1, d2)
        fill(self.chk, ["البند", "الحالة", "التفصيل"],
             [(t, "✔ جاهز" if ok else "✘ يحتاج إجراء", d)
              for t, ok, d in items])
        for i, (_t, ok, _d) in enumerate(items):
            it = self.chk.item(i, 1)
            if it:
                it.setForeground(QtGui.QColor("#0F5A24" if ok
                                              else "#9A0018"))
        ready = sum(1 for _t, ok, _d in items if ok)
        self.chk_status.setText(
            f"{ready} من {len(items)} بنود جاهزة — أكمل التسويات من"
            " التبويبات، ثم اطبع القوائم أو صدّر الحزمة، ثم اقفل الفترة"
            " من شاشة «الإقفال السنوي» بعد اعتمادها.")

    def _print(self, kind):
        try:
            d1, d2 = self._period()
            from services import print_manager
            print_manager.preview_document(
                self, kind, 0, date_from=d1, date_to=d2,
                compare=self.cmp_on.isChecked())
        except Exception as e:
            err(self, e)

    def export_package(self):
        try:
            d1, d2 = self._period()
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "حفظ حزمة القوائم المالية",
                f"القوائم_المالية_{d1}_{d2}.zip", "ملف مضغوط (*.zip)")
            if not path:
                return
            from services import fs_package
            names = fs_package.export(path, d1, d2,
                                      self.cmp_on.isChecked())
            info(self, "حُفظت الحزمة:\n" + path + "\n\nتحتوي:\n• "
                 + "\n• ".join(names))
        except Exception as e:
            err(self, e)

    # ═══════════════════════════════════════ 2) الزكاة
    def _tab_zakat(self):
        w = QtWidgets.QWidget()
        self.z_add = QtWidgets.QDoubleSpinBox()
        self.z_ded = QtWidgets.QDoubleSpinBox()
        for sp in (self.z_add, self.z_ded):
            sp.setRange(0, 1e12)
            sp.setDecimals(2)
            sp.setGroupSeparatorShown(True)
            sp.setMinimumWidth(140)
        b_calc = QtWidgets.QPushButton("احسب")
        b_calc.clicked.connect(self.load_zakat)
        b_post = QtWidgets.QPushButton("✔ قيّد مخصص الزكاة")
        b_post.setObjectName("homeBtn")
        b_post.clicked.connect(self.post_zakat)
        b_print = QtWidgets.QPushButton("🖨 طباعة الاحتساب")
        b_print.clicked.connect(self.print_zakat)
        row = FlowLayout()
        row.addWidget(QtWidgets.QLabel("إضافات أخرى:"))
        row.addWidget(self.z_add)
        row.addWidget(QtWidgets.QLabel("حسميات أخرى:"))
        row.addWidget(self.z_ded)
        for b in (b_calc, b_post, b_print):
            row.addWidget(b)
        row.addStretch(1)
        self.z_tbl = make_table()
        self.z_sum = big_label()
        self.z_sum.setWordWrap(True)
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.addLayout(row)
        lay.addWidget(self.z_tbl, 1)
        lay.addWidget(self.z_sum)
        return w

    def load_zakat(self):
        d1, d2 = self._period()
        with db(readonly=True) as conn:
            z = pe.zakat_compute(conn, d1, d2, self.z_add.value(),
                                 self.z_ded.value())
        rows = ([("+", l, _m(v)) for l, v in z["additions"]]
                + [("−", l, _m(v)) for l, v in z["deductions"]])
        fill(self.z_tbl, ["", "البند", "ريال"], rows)
        try:
            from ui.widgets.table_fit import fit_columns
            fit_columns(self.z_tbl, [6, 64, 30])
        except Exception:
            pass
        self.z_sum.setText(
            f"الوعاء الزكوي: {z['base']:,.2f}"
            + (" (رُفع إلى صافي الربح المعدّل)" if z["base_floor"] else "")
            + f"   ·   النسبة {z['rate'] * 100:.4f}%"
            f"   ·   الزكاة: {z['zakat']:,.2f}"
            f"   ·   المقيَّد: {z['booked']:,.2f}"
            f"   ·   المطلوب قيده: {z['due']:,.2f} ريال")
        self._z = z

    def post_zakat(self):
        try:
            self.load_zakat()
            z = self._z
            if abs(z["due"]) < 0.01:
                info(self, "مخصص الزكاة مقيَّدٌ بالكامل لهذه الفترة.")
                return
            d1, d2 = self._period()
            if not ask(self, f"قيد مخصص الزكاة بمبلغ {z['due']:,.2f} ريال"
                             f" بتاريخ {d2}؟\n(مدين الزكاة / دائن مخصص"
                             " الزكاة)"):
                return
            with db() as conn:
                pe.zakat_post(conn, d1, d2, self._user(),
                              self.z_add.value(), self.z_ded.value())
            info(self, "قُيِّد مخصص الزكاة.")
            self.load_zakat()
        except Exception as e:
            err(self, e)

    def print_zakat(self):
        try:
            d1, d2 = self._period()
            from services import print_manager
            print_manager.preview_document(
                self, "zakat_calc", 0, date_from=d1, date_to=d2,
                extra_add=self.z_add.value(), extra_ded=self.z_ded.value())
        except Exception as e:
            err(self, e)

    # ═══════════════════════════════════════ 3) نهاية الخدمة
    EOS_COLS = ["الموظف", "النوع", "تاريخ التعيين (YYYY-MM-DD)",
                "أجر المكافأة الشهري", "تاريخ الانتهاء", "سنوات الخدمة",
                "المكافأة المستحقة"]

    def _tab_eos(self):
        w = QtWidgets.QWidget()
        b_save = QtWidgets.QPushButton("💾 حفظ بيانات الموظفين")
        b_save.clicked.connect(self.save_eos)
        b_post = QtWidgets.QPushButton("✔ قيّد تسوية المخصص")
        b_post.setObjectName("homeBtn")
        b_post.clicked.connect(self.post_eos)
        row = FlowLayout()
        hint = QtWidgets.QLabel(
            "عدّل تاريخ التعيين والأجر في الجدول ثم احفظ:")
        hint.setToolTip("الأجر = الأساسي + البدلات الثابتة")
        row.addWidget(hint)
        row.addWidget(b_save)
        row.addWidget(b_post)
        row.addStretch(1)
        self.e_tbl = make_table()
        self.e_tbl.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked
                                   | QtWidgets.QAbstractItemView.EditKeyPressed
                                   | QtWidgets.QAbstractItemView.AnyKeyPressed)
        self.e_sum = big_label()
        self.e_sum.setWordWrap(True)
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.addLayout(row)
        lay.addWidget(self.e_tbl, 1)
        lay.addWidget(self.e_sum)
        return w

    def load_eos(self):
        _d1, d2 = self._period()
        with db() as conn:
            c = pe.eos_compute(conn, d2)
        self._eos_rows = c["rows"]
        t = self.e_tbl
        t.blockSignals(True)
        t.clear()
        t.setColumnCount(len(self.EOS_COLS))
        t.setHorizontalHeaderLabels(self.EOS_COLS)
        t.setRowCount(len(c["rows"]))
        kinds = {"employee": "موظف", "worker": "عامل"}
        for i, r in enumerate(c["rows"]):
            vals = [r["name"], kinds.get(r["kind"], r["kind"]),
                    r["hire_date"], f"{r['wage']:.2f}", r["end_date"],
                    f"{r['years']:.2f}" if r["counted"] else "—",
                    _m(r["award"])]
            for col, v in enumerate(vals):
                it = QtWidgets.QTableWidgetItem(v)
                it.setTextAlignment(QtCore.Qt.AlignCenter)
                if col not in (2, 3, 4):
                    it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
                else:
                    it.setBackground(QtGui.QColor("#FFF8E6"))
                t.setItem(i, col, it)
        t.blockSignals(False)
        miss = (f"   ·   ✘ بلا تاريخ تعيين: {len(c['missing_hire'])}"
                if c["missing_hire"] else "")
        self.e_sum.setText(
            f"الالتزام المطلوب في {d2}: {c['required']:,.2f}   ·   الرصيد"
            f" المقيَّد: {c['current']:,.2f}   ·   المطلوب قيده:"
            f" {c['due']:,.2f} ريال{miss}   ·   المادة 84: نصف أجر شهر عن"
            " كل سنة من الخمس الأولى، وأجر شهر عمّا بعدها")

    def save_eos(self):
        try:
            t = self.e_tbl
            with db() as conn:
                for i, r in enumerate(getattr(self, "_eos_rows", [])):
                    hire = (t.item(i, 2).text() if t.item(i, 2) else "").strip()
                    wage = (t.item(i, 3).text() if t.item(i, 3) else "")
                    wage = wage.replace(",", "").strip()
                    end = (t.item(i, 4).text() if t.item(i, 4) else "").strip()
                    try:
                        pe.eos_update(conn, r["id"], hire, wage, end,
                                      self._user())
                    except ValueError:
                        raise ValueError(f"تاريخ غير صالح للموظف «{r['name']}»"
                                         " — الصيغة YYYY-MM-DD")
            info(self, "حُفظت بيانات الموظفين.")
            self.load_eos()
        except Exception as e:
            err(self, e)

    def post_eos(self):
        try:
            _d1, d2 = self._period()
            with db() as conn:
                c = pe.eos_compute(conn, d2)
            if abs(c["due"]) < 0.01:
                info(self, "المخصص مطابقٌ للالتزام المحسوب — لا قيد.")
                return
            if not ask(self, f"قيد تسوية مخصص نهاية الخدمة بمبلغ"
                             f" {c['due']:,.2f} ريال بتاريخ {d2}؟"):
                return
            with db() as conn:
                pe.eos_post(conn, d2, self._user())
            info(self, "قُيِّدت تسوية المخصص.")
            self.load_eos()
        except Exception as e:
            err(self, e)

    # ═══════════════════════════════════════ 4) الديون المشكوك فيها
    def _tab_ecl(self):
        from models import aging
        w = QtWidgets.QWidget()
        self.rate_boxes = []
        row = FlowLayout()
        row.addWidget(QtWidgets.QLabel("نسبة المخصص لكل فئة:"))
        for lbl in aging.BUCKET_LABELS:
            sp = QtWidgets.QDoubleSpinBox()
            sp.setRange(0, 100)
            sp.setDecimals(2)
            sp.setSuffix(" %")
            row.addWidget(QtWidgets.QLabel(lbl + ":"))
            row.addWidget(sp)
            self.rate_boxes.append(sp)
        b_calc = QtWidgets.QPushButton("احسب")
        b_calc.clicked.connect(lambda: self.load_ecl(keep=True))
        b_save = QtWidgets.QPushButton("💾 حفظ النسب")
        b_save.clicked.connect(self.save_rates)
        b_post = QtWidgets.QPushButton("✔ قيّد تسوية المخصص")
        b_post.setObjectName("homeBtn")
        b_post.clicked.connect(self.post_ecl)
        for b in (b_calc, b_save, b_post):
            row.addWidget(b)
        row.addStretch(1)
        self.c_tbl = make_table()
        self.c_sum = big_label()
        self.c_sum.setWordWrap(True)
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.addLayout(row)
        lay.addWidget(self.c_tbl, 1)
        lay.addWidget(self.c_sum)
        return w

    def _rates(self):
        return [sp.value() for sp in self.rate_boxes]

    def load_ecl(self, keep=False):
        _d1, d2 = self._period()
        with db(readonly=True) as conn:
            if not keep:
                for sp, v in zip(self.rate_boxes, pe.ecl_rates(conn)):
                    sp.setValue(v)
            c = pe.ecl_compute(conn, d2, self._rates())
        fill(self.c_tbl, ["عمر الدين", "رصيد ذمم العملاء", "النسبة",
                          "المخصص"],
             [(x["label"], _m(x["balance"]), f"{x['rate']:g}%",
               _m(x["allowance"])) for x in c["lines"]])
        self.c_sum.setText(
            f"المخصص المطلوب في {d2}: {c['required']:,.2f}   ·   الرصيد"
            f" المقيَّد: {c['current']:,.2f}   ·   المطلوب قيده:"
            f" {c['due']:,.2f} ريال   ·   المنهج المبسّط (IFRS 9) بمصفوفة"
            " المخصص على أعمار ذمم العملاء النقدية")

    def save_rates(self):
        try:
            with db() as conn:
                pe.ecl_set_rates(conn, self._rates(), self._user())
            info(self, "حُفظت النسب.")
        except Exception as e:
            err(self, e)

    def post_ecl(self):
        try:
            _d1, d2 = self._period()
            with db(readonly=True) as conn:
                c = pe.ecl_compute(conn, d2, self._rates())
            if abs(c["due"]) < 0.01:
                info(self, "المخصص مطابقٌ للمحسوب — لا قيد.")
                return
            if not ask(self, f"قيد تسوية مخصص الخسائر الائتمانية بمبلغ"
                             f" {c['due']:,.2f} ريال بتاريخ {d2}؟"):
                return
            with db() as conn:
                pe.ecl_post(conn, d2, self._user(), self._rates())
            info(self, "قُيِّدت تسوية المخصص.")
            self.load_ecl(keep=True)
        except Exception as e:
            err(self, e)

    # ═══════════════════════════════════════ 5) المقدمة والمستحقة
    def _tab_prepaid(self):
        w = QtWidgets.QWidget()
        with db(readonly=True) as conn:
            # مصروفات نقدية فقط — لا فواقد ذهبٍ وزنية ولا حسابات التسويات
            # الآلية (إهلاك · زكاة · نهاية خدمة · خسائر ائتمانية)
            exp = _accounts(conn, "a.type='expense'"
                            " AND COALESCE(a.balance_type,'cash')"
                            " IN ('cash','both')"
                            " AND a.code NOT IN ('5860','5870','5880','5950')")
            cash = _accounts(conn, "a.code IN ('1400','1410','1500')"
                             " OR a.parent_id IN (SELECT id FROM accounts"
                             " WHERE code='1010')")
        # ── مصروف مدفوع مقدماً
        g1 = QtWidgets.QGroupBox("مصروف مدفوع مقدماً (إيجار سنوي · تأمين …)")
        self.p_name = QtWidgets.QLineEdit()
        self.p_name.setPlaceholderText("البيان — مثال: إيجار المصنع 2026")
        self.p_exp = QtWidgets.QComboBox()
        for code, lbl in exp:
            self.p_exp.addItem(lbl, code)
        self.p_amt = QtWidgets.QDoubleSpinBox()
        self.p_amt.setRange(0, 1e12)
        self.p_amt.setDecimals(2)
        self.p_amt.setGroupSeparatorShown(True)
        self.p_start = date_edit()
        self.p_months = QtWidgets.QSpinBox()
        self.p_months.setRange(1, 120)
        self.p_months.setValue(12)
        self.p_mode = QtWidgets.QComboBox()
        self.p_mode.addItem("قُيِّد مصروفاً عند دفعه — انقله للمقدّم",
                            "reclass")
        self.p_mode.addItem("يُدفع الآن من الصندوق/البنك", "paid")
        self.p_cash = QtWidgets.QComboBox()
        for code, lbl in cash:
            self.p_cash.addItem(lbl, code)
        self._select(self.p_exp, "5810")
        b_add = QtWidgets.QPushButton("➕ تسجيل")
        b_add.clicked.connect(self.add_prepaid)
        # قائمةٌ بعرض أطول بنودها تدفع المجموعة خارج إطار الشاشة
        for cb in (self.p_exp, self.p_mode, self.p_cash):
            cb.setSizeAdjustPolicy(
                QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(14)
        f1 = QtWidgets.QGridLayout(g1)
        f1.addWidget(self.p_name, 0, 0, 1, 2)
        f1.addWidget(QtWidgets.QLabel("حساب المصروف:"), 0, 2)
        f1.addWidget(self.p_exp, 0, 3)
        f1.addWidget(QtWidgets.QLabel("المبلغ:"), 1, 0)
        f1.addWidget(self.p_amt, 1, 1)
        f1.addWidget(QtWidgets.QLabel("يبدأ من:"), 1, 2)
        f1.addWidget(self.p_start, 1, 3)
        f1.addWidget(QtWidgets.QLabel("عدد الأشهر:"), 1, 4)
        f1.addWidget(self.p_months, 1, 5)
        f1.addWidget(self.p_mode, 2, 0, 1, 2)
        f1.addWidget(self.p_cash, 2, 2, 1, 2)
        f1.addWidget(b_add, 2, 5)
        self.p_tbl = make_table()
        b_amort = QtWidgets.QPushButton("✔ أطفئ المستحق حتى نهاية الفترة")
        b_amort.setObjectName("homeBtn")
        b_amort.clicked.connect(self.amortize)
        # ── مصروف مستحق
        g2 = QtWidgets.QGroupBox("مصروف مستحق (استُهلك ولم تصل فاتورته)")
        self.a_exp = QtWidgets.QComboBox()
        for code, lbl in exp:
            self.a_exp.addItem(lbl, code)
        self._select(self.a_exp, "5820")
        self.a_amt = QtWidgets.QDoubleSpinBox()
        self.a_amt.setRange(0, 1e12)
        self.a_amt.setDecimals(2)
        self.a_amt.setGroupSeparatorShown(True)
        self.a_note = QtWidgets.QLineEdit()
        self.a_note.setPlaceholderText("البيان — مثال: كهرباء ديسمبر")
        self.a_rev = QtWidgets.QCheckBox("عكسٌ تلقائي أول الفترة التالية")
        self.a_rev.setChecked(True)
        b_acc = QtWidgets.QPushButton("✔ قيّد الاستحقاق بتاريخ نهاية الفترة")
        b_acc.clicked.connect(self.accrue)
        self.a_exp.setSizeAdjustPolicy(
            QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.a_exp.setMinimumContentsLength(14)
        self.a_note.setMinimumWidth(200)
        f2 = FlowLayout(g2)
        for x in (self.a_exp, self.a_amt, self.a_note, self.a_rev, b_acc):
            f2.addWidget(x)
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.addWidget(g1)
        lay.addWidget(self.p_tbl, 1)
        lay.addWidget(b_amort)
        lay.addWidget(g2)
        return w

    @staticmethod
    def _select(combo, code):
        i = combo.findData(code)
        if i >= 0:
            combo.setCurrentIndex(i)

    def load_prepaid(self):
        _d1, d2 = self._period()
        with db() as conn:
            items = pe.prepaid_list(conn, d2)
        fill(self.p_tbl, ["البيان", "حساب المصروف", "المبلغ", "من", "إلى",
                          "المستحق حتى الفترة", "المُطفأ", "المطلوب إطفاؤه",
                          "المتبقي مقدّماً"],
             [(x["name"], f"{x['exp_code']} — {x['exp_name']}",
               _m(x["amount"]), x["start"], x["end"], _m(x["should"]),
               _m(x["done"]), _m(x["due"]), _m(x["remaining"]))
              for x in items])

    def add_prepaid(self):
        try:
            name = self.p_name.text().strip()
            if not name:
                raise ValueError("اكتب بيان المصروف")
            with db() as conn:
                pe.prepaid_add(conn, name, self.p_exp.currentData(),
                               self.p_amt.value(), dstr(self.p_start),
                               self.p_months.value(), self._user(),
                               mode=self.p_mode.currentData(),
                               cash_code=self.p_cash.currentData() or "1400")
            self.p_name.clear()
            self.p_amt.setValue(0)
            info(self, "سُجِّل المصروف المقدّم.")
            self.load_prepaid()
        except Exception as e:
            err(self, e)

    def amortize(self):
        try:
            _d1, d2 = self._period()
            with db() as conn:
                done = pe.prepaid_amortize(conn, d2, self._user())
            info(self, ("أُطفئ:\n" + "\n".join(
                f"• {n}: {a:,.2f}" for n, a, _e in done)) if done
                 else "لا شيء مستحق الإطفاء حتى نهاية الفترة.")
            self.load_prepaid()
        except Exception as e:
            err(self, e)

    def accrue(self):
        try:
            _d1, d2 = self._period()
            if self.a_amt.value() <= 0:
                raise ValueError("أدخل المبلغ")
            with db() as conn:
                pe.accrue_expense(conn, self.a_exp.currentData(),
                                  self.a_amt.value(), d2, self._user(),
                                  note=self.a_note.text().strip(),
                                  auto_reverse=self.a_rev.isChecked())
            self.a_amt.setValue(0)
            self.a_note.clear()
            info(self, f"قُيِّد الاستحقاق بتاريخ {d2}"
                       + (" وعُكس أول الفترة التالية."
                          if self.a_rev.isChecked() else "."))
        except Exception as e:
            err(self, e)

    def refresh(self):
        self.refresh_all()
