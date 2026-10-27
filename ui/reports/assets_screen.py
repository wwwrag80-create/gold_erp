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

from ui import kit

from database.database import db
from models import assets as fa
from ui.widgets.common import (Card, ask, big_label, busy, date_edit, dstr,
                               err, fill, info, make_table, mspin,
                               reload_combo, title_label, warn)
from ui.widgets.table_tools import enhance as _enhance
from services import numfmt as _nf

COLS = ["الأصل", "الحساب", "بدء الإهلاك", "التكلفة", "التخريدية",
        "العمر (شهر)", "القسط الشهري", "المُهلَك حتى الآن",
        "الصافي الدفتري", "الحالة"]


class AssetsScreen(QtWidgets.QWidget):
    def __init__(self, user, embedded=False):
        super().__init__()
        self.user = user
        self.rows = []

        # ── تسجيل أصل ──
        self.name = kit.LineEdit()
        self.name.setPlaceholderText("اسم الأصل — مكينة ليزر، سيارة توصيل…")
        self.acc = kit.ComboBox()
        self.acc.setMinimumWidth(210)
        self.cost = mspin()
        self.salvage = mspin()
        self.salvage.setToolTip(
            "القيمة المتوقَّعة عند نهاية عمره — تُطرح من التكلفة قبل "
            "القسمة. اتركها صفراً إن كان يُخرَّد بلا قيمة.")
        self.life = kit.SpinBox()
        self.life.setRange(1, 600)
        self.life.setValue(60)
        self.life.setSuffix(" شهراً")
        self.life.setToolTip("العمر الإنتاجي بالأشهر — ٦٠ تعني خمس سنوات")
        self.start = date_edit()
        btn_add = kit.PushButton("➕ تسجيل الأصل")
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
        self.period = kit.LineEdit()
        self.period.setMaximumWidth(120)
        self.period.setPlaceholderText("2026-01")
        self.period.setText(QtCore.QDate.currentDate().toString("yyyy-MM"))
        btn_prev = kit.PushButton("👁 ما سيُهلَك")
        btn_prev.setObjectName("ghost")
        btn_prev.clicked.connect(self.show_preview)
        btn_run = kit.PushButton("📅 ترحيل إهلاك الشهر")
        btn_run.clicked.connect(self.run_month)
        btn_disp = kit.PushButton("⏏ إخراج من الخدمة")
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
        if not embedded:
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
                r["begins"], f"{_nf.f2(float(r['cost']))}",
                f"{_nf.f2(float(r['salvage']))}",
                r["life_months"] or "—",
                f"{_nf.f2(r['monthly'])}" if r["monthly"] else "—",
                f"{_nf.f2(r['accumulated'])}", f"{_nf.f2(r['net_book'])}", st))
        fill(self.table, COLS, data)
        self._paint()

        self.c_count.set_value(f"{t['count']:,}")
        self.c_cost.set_value(f"{_nf.f2(t['cost'])}")
        self.c_acc.set_value(f"{_nf.f2(t['accumulated'])}")
        self.c_net.set_value(f"{_nf.f2(t['net_book'])}",
                             f"قسط الشهر {_nf.f2(t['monthly'])}")

        bits = [f"قسط الشهر القادم: {_nf.f2(t['monthly'])} ريال"]
        if t.get("unset"):
            bits.append(f"⚠ {t['unset']} أصلاً بلا عمرٍ إنتاجي — "
                        f"لا تُهلَك حتى يُحدَّد عمرها")
        if abs(cmp_["difference"]) > 0.01:
            bits.append(
                f"⚠ فرقٌ بين السجل والدفتر: السجل {_nf.f2(cmp_['register'])} · "
                f"الدفتر {_nf.f2(cmp_['ledger'])} · الفرق "
                f"{_nf.f2(cmp_['difference'])}")
        self.state.setText("   |   ".join(bits))

    def _paint(self):
        """يلوّن ما يحتاج استدراكاً — العين تلتقطه قبل أن تقرأ."""
        for i, r in enumerate(self.rows):
            it = self.table.item(i, len(COLS) - 1)
            if it is None:
                continue
            if r["is_disposed"]:
                it.setForeground(QtGui.QColor("#555049"))
            elif int(r.get("life_months") or 0) <= 0:
                it.setForeground(QtGui.QColor("#9A1414"))
            elif r["done"]:
                it.setForeground(QtGui.QColor("#0F5A24"))

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
                       f"{done['entry_id']} — {_nf.f2(float(done['total']))} "
                       f"ريال.\n\nلا يُهلَك الشهر مرتين.")
            return
        if not rows:
            warn(self, f"لا يوجد ما يُهلَك في {p}.")
            return
        total = sum(r["amount"] for r in rows)
        txt = "\n".join(f"  {r['name']}: {_nf.f2(r['amount'])}" for r in rows)
        info(self, f"سيُهلَك في {p}:\n\n{txt}\n\nالإجمالي: "
                   f"{_nf.f2(total)} ريال", "معاينة إهلاك الشهر")

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
                             f"{_nf.f2(total)} ريال\n\nمن حـ/ مصروف الإهلاك "
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
                   f"{_nf.f2(res['total'])} ريال")
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
                         f"من الآن. صافيه الدفتري {_nf.f2(r['net_book'])} "
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
