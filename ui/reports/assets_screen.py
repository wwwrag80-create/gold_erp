# -*- coding: utf-8 -*-
"""الأصول الثابتة والإهلاك — سجلٌّ وقسطٌ شهريٌّ بقيدٍ آلي.

**الفجوة التي تسدّها**: كانت المكائن والسيارات تُشترى وتُقيَّد ثم لا
تُهلَك أبداً. فقائمة الدخل تُظهر ربحاً لم يتحقّق — يُوزَّع أو تُدفع
عنه زكاةٌ وضريبة — والميزانية تُبقي مكينةً عمرها خمس سنوات بثمن
شرائها إلى الأبد.

**ما تفعله**: تعرض ما في الدفتر من أصول، وتحسب قسط كلٍّ منها بالقسط
الثابت، وتُرحّل إهلاك الشهر **بقيدٍ واحد مجمّع** لا يتكرّر.

    من حـ/ مصروف الإهلاك ٥٨٦٠   إلى حـ/ مجمّع الإهلاك ١٧٩٠

**ولا تُقيّد شراءً**: شراء المكينة مُقيَّدٌ أصلاً في «المشتريات».
فالسجل يصف ما في الدفتر ليُحسب منه الإهلاك — ولو قيَّده ثانيةً
لتضاعفت الأصول. ولذلك تُقارَن جملةُ السجل برصيد حسابات الأصول أعلى
الشاشة، فيظهر أي انحراف بدل أن يمرّ صامتاً.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from models import assets as fa
from ui.widgets.common import (Card, ask, big_label, busy, date_edit, dstr,
                               err, fill, info, make_table, mspin,
                               reload_combo, title_label, warn)
from ui.widgets.table_tools import enhance as _enhance

COLS = ["الأصل", "الحساب", "بدء الإهلاك", "التكلفة", "التخريدية",
        "العمر (شهر)", "القسط الشهري", "المُهلَك حتى الآن",
        "الصافي الدفتري", "الحالة"]


class AssetsScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.rows = []

        # ── تسجيل أصل ──
        self.name = QtWidgets.QLineEdit()
        self.name.setPlaceholderText("اسم الأصل — مكينة ليزر، سيارة توصيل…")
        self.acc = QtWidgets.QComboBox()
        self.acc.setMinimumWidth(210)
        self.cost = mspin()
        self.salvage = mspin()
        self.salvage.setToolTip(
            "القيمة المتوقَّعة عند نهاية عمره — تُطرح من التكلفة قبل "
            "القسمة. اتركها صفراً إن كان يُخرَّد بلا قيمة.")
        self.life = QtWidgets.QSpinBox()
        self.life.setRange(1, 600)
        self.life.setValue(60)
        self.life.setSuffix(" شهراً")
        self.life.setToolTip("العمر الإنتاجي بالأشهر — ٦٠ تعني خمس سنوات")
        self.start = date_edit()
        btn_add = QtWidgets.QPushButton("➕ تسجيل الأصل")
        btn_add.clicked.connect(self.add_asset)

        form = QtWidgets.QGridLayout()
        form.addWidget(QtWidgets.QLabel("الاسم:"), 0, 0)
        form.addWidget(self.name, 0, 1)
        form.addWidget(QtWidgets.QLabel("الحساب:"), 0, 2)
        form.addWidget(self.acc, 0, 3)
        form.addWidget(QtWidgets.QLabel("بدء الإهلاك:"), 0, 4)
        form.addWidget(self.start, 0, 5)
        form.addWidget(QtWidgets.QLabel("التكلفة:"), 1, 0)
        form.addWidget(self.cost, 1, 1)
        form.addWidget(QtWidgets.QLabel("التخريدية:"), 1, 2)
        form.addWidget(self.salvage, 1, 3)
        form.addWidget(QtWidgets.QLabel("العمر:"), 1, 4)
        form.addWidget(self.life, 1, 5)
        form.addWidget(btn_add, 1, 6)
        form.setColumnStretch(7, 1)
        box_add = QtWidgets.QGroupBox("تسجيل أصلٍ في السجل — بلا قيد")
        box_add.setLayout(form)

        # ── إهلاك الشهر ──
        self.period = QtWidgets.QLineEdit()
        self.period.setMaximumWidth(120)
        self.period.setPlaceholderText("2026-01")
        self.period.setText(QtCore.QDate.currentDate().toString("yyyy-MM"))
        btn_prev = QtWidgets.QPushButton("👁 ما سيُهلَك")
        btn_prev.setObjectName("ghost")
        btn_prev.clicked.connect(self.show_preview)
        btn_run = QtWidgets.QPushButton("📅 ترحيل إهلاك الشهر")
        btn_run.clicked.connect(self.run_month)
        btn_disp = QtWidgets.QPushButton("⏏ إخراج من الخدمة")
        btn_disp.setObjectName("ghost")
        btn_disp.setToolTip(
            "يوقف قسط الأصل المحدَّد — البيع أو الشطب قيدٌ تكتبه بنفسك")
        btn_disp.clicked.connect(self.dispose)

        run_row = QtWidgets.QHBoxLayout()
        run_row.addWidget(QtWidgets.QLabel("الشهر:"))
        run_row.addWidget(self.period)
        run_row.addWidget(btn_prev)
        run_row.addWidget(btn_run)
        run_row.addSpacing(18)
        run_row.addWidget(btn_disp)
        run_row.addStretch(1)

        self.c_count = Card("أصول في السجل", "غير المُخرَجة")
        self.c_cost = Card("إجمالي التكلفة", "ريال")
        self.c_acc = Card("مجمّع الإهلاك", "ريال")
        self.c_net = Card("الصافي الدفتري", "ريال")
        tiles = QtWidgets.QHBoxLayout()
        for c in (self.c_count, self.c_cost, self.c_acc, self.c_net):
            tiles.addWidget(c)

        self.state = big_label()
        self.table = make_table()
        _enhance(self.table, key="fixed_assets")

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label(
            "الأصول الثابتة والإهلاك — قسطٌ ثابتٌ شهري"))
        intro = QtWidgets.QLabel(
            "الإهلاك مصروفٌ حقيقي لا يُدفع نقداً: إغفاله يُظهر ربحاً لم "
            "يتحقّق، ويُبقي المكينة في الميزانية بثمن شرائها إلى الأبد. "
            "يُرحَّل شهرياً بقيدٍ واحد مجمّع — من مصروف الإهلاك إلى "
            "مجمّع الإهلاك — ولا يتكرّر على الشهر نفسه.")
        intro.setObjectName("cardSub")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        lay.addWidget(box_add)
        lay.addLayout(run_row)
        lay.addLayout(tiles)
        lay.addWidget(self.state)
        lay.addWidget(self.table, 1)
        note = QtWidgets.QLabel(
            "السجل لا يُقيّد شراءً — الشراء مُقيَّدٌ في «المشتريات». وأي "
            "فرقٍ بين جملة السجل ورصيد حسابات الأصول يظهر أعلاه ليُصحَّح.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)

        QtCore.QTimer.singleShot(0, self._boot)

    # ─────────────────────────────── بيانات
    def _boot(self):
        try:
            with db(readonly=True) as conn:
                accs = fa.depreciable_accounts(conn)
            reload_combo(self.acc, accs,
                         lambda a: f"{a['code']} — {a['name']}")
        except Exception as e:
            err(self, e)
            return
        self.refresh()

    def refresh(self):
        try:
            with db(readonly=True) as conn:
                self.rows = fa.list_assets(conn, include_disposed=True)
                t = fa.totals(conn)
                cmp_ = fa.register_vs_ledger(conn)
        except Exception as e:
            err(self, e)
            return
        data = []
        for r in self.rows:
            if r["is_disposed"]:
                st = f"خارج الخدمة {r['disposed_on'] or ''}".strip()
            elif int(r.get("life_months") or 0) <= 0:
                st = "⚠ بلا عمرٍ إنتاجي"
            elif r["done"]:
                st = "اكتمل إهلاكه"
            else:
                st = "يُهلَك"
            data.append((
                r["name"], f"{r['acc_code']} — {r['acc_name']}",
                r["begins"], f"{float(r['cost']):,.2f}",
                f"{float(r['salvage']):,.2f}",
                r["life_months"] or "—",
                f"{r['monthly']:,.2f}" if r["monthly"] else "—",
                f"{r['accumulated']:,.2f}", f"{r['net_book']:,.2f}", st))
        fill(self.table, COLS, data)
        self._paint()

        self.c_count.set_value(f"{t['count']:,}")
        self.c_cost.set_value(f"{t['cost']:,.2f}")
        self.c_acc.set_value(f"{t['accumulated']:,.2f}")
        self.c_net.set_value(f"{t['net_book']:,.2f}",
                             f"قسط الشهر {t['monthly']:,.2f}")

        bits = [f"قسط الشهر القادم: {t['monthly']:,.2f} ريال"]
        if t.get("unset"):
            bits.append(f"⚠ {t['unset']} أصلاً بلا عمرٍ إنتاجي — "
                        f"لا تُهلَك حتى يُحدَّد عمرها")
        if abs(cmp_["difference"]) > 0.01:
            bits.append(
                f"⚠ فرقٌ بين السجل والدفتر: السجل {cmp_['register']:,.2f} · "
                f"الدفتر {cmp_['ledger']:,.2f} · الفرق "
                f"{cmp_['difference']:,.2f}")
        self.state.setText("   |   ".join(bits))

    def _paint(self):
        """يلوّن ما يحتاج استدراكاً — العين تلتقطه قبل أن تقرأ."""
        for i, r in enumerate(self.rows):
            it = self.table.item(i, len(COLS) - 1)
            if it is None:
                continue
            if r["is_disposed"]:
                it.setForeground(QtGui.QColor("#7A7A7A"))
            elif int(r.get("life_months") or 0) <= 0:
                it.setForeground(QtGui.QColor("#B02A2A"))
            elif r["done"]:
                it.setForeground(QtGui.QColor("#2E7D32"))

    # ─────────────────────────────── أفعال
    def add_asset(self):
        try:
            aid = self.acc.currentData()
            if not aid:
                raise ValueError("اختر حساب الأصل")
            with db() as conn:
                fa.add_asset(conn, self.name.text(), aid,
                             self.cost.value(), self.life.value(),
                             dstr(self.start),
                             salvage=self.salvage.value(),
                             username=self.user.get("username", "admin"))
        except Exception as e:
            err(self, e)
            return
        info(self, "سُجّل الأصل.\n\nلم يُنشأ قيد — شراؤه مُقيَّدٌ في "
                   "«المشتريات» أو «القيود اليومية».")
        self.name.clear()
        self.cost.setValue(0)
        self.salvage.setValue(0)
        self.refresh()

    def show_preview(self):
        try:
            p = self.period.text().strip()
            with db(readonly=True) as conn:
                done = fa.run_for_period(conn, p)
                rows = fa.preview(conn, p)
        except Exception as e:
            err(self, e)
            return
        if done:
            info(self, f"شهر {p} مُهلَكٌ من قبل بقيد رقم "
                       f"{done['entry_id']} — {float(done['total']):,.2f} "
                       f"ريال.\n\nلا يُهلَك الشهر مرتين.")
            return
        if not rows:
            warn(self, f"لا يوجد ما يُهلَك في {p}.")
            return
        total = sum(r["amount"] for r in rows)
        txt = "\n".join(f"  {r['name']}: {r['amount']:,.2f}" for r in rows)
        info(self, f"سيُهلَك في {p}:\n\n{txt}\n\nالإجمالي: "
                   f"{total:,.2f} ريال", "معاينة إهلاك الشهر")

    def run_month(self):
        p = self.period.text().strip()
        try:
            with db(readonly=True) as conn:
                if fa.run_for_period(conn, p):
                    warn(self, f"شهر {p} مُهلَكٌ من قبل — لا يُهلَك مرتين.")
                    return
                rows = fa.preview(conn, p)
            if not rows:
                warn(self, f"لا يوجد ما يُهلَك في {p}.")
                return
            total = sum(r["amount"] for r in rows)
            if not ask(self, f"ترحيل إهلاك {p}؟\n\n{len(rows)} أصلاً · "
                             f"{total:,.2f} ريال\n\nمن حـ/ مصروف الإهلاك "
                             f"إلى حـ/ مجمّع الإهلاك."):
                return
            with busy(self, "جارٍ ترحيل الإهلاك…", stage="إهلاك"):
                with db() as conn:
                    res = fa.run_depreciation(
                        conn, p, self.user.get("username", "admin"))
        except Exception as e:
            err(self, e)
            return
        info(self, f"رُحّل إهلاك {res['period']} بقيد رقم "
                   f"{res['entry_id']}.\n\n{res['lines']} أصلاً · "
                   f"{res['total']:,.2f} ريال")
        self.refresh()

    def dispose(self):
        i = self.table.currentRow()
        if not (0 <= i < len(self.rows)):
            warn(self, "اختر أصلاً من الجدول أولاً.")
            return
        r = self.rows[i]
        if r["is_disposed"]:
            warn(self, "هذا الأصل خارج الخدمة أصلاً.")
            return
        if not ask(self, f"إخراج «{r['name']}» من الخدمة؟\n\nيتوقّف قسطه "
                         f"من الآن. صافيه الدفتري {r['net_book']:,.2f} "
                         f"ريال — وبيعه أو شطبه قيدٌ تكتبه بنفسك في "
                         f"«القيود اليومية»."):
            return
        try:
            with db() as conn:
                fa.dispose_asset(conn, r["id"],
                                 QtCore.QDate.currentDate().toString(
                                     "yyyy-MM-dd"),
                                 self.user.get("username", "admin"))
        except Exception as e:
            err(self, e)
            return
        info(self, "أُخرج الأصل من الخدمة — توقّف قسطه.")
        self.refresh()
