# -*- coding: utf-8 -*-
"""سلامة السجل — التحقق من سلسلة بصمات القيود.

تكشف أي تغييرٍ جرى على قيدٍ مرحَّل **من خارج النظام** (بفتح ملف قاعدة
البيانات ببرنامج آخر). شرح الآلية كاملاً في `models/integrity.py`.
"""
from PyQt5 import QtCore, QtWidgets

from ui import kit

from database.database import db
from models import integrity
from services import karat_view as kv
from services import numfmt as _nf
from ui.widgets.common import (ask, big_label, date_edit, dstr, err, fill,
                               info, make_table, tab_widget, title_label)
from ui.widgets.table_tools import enhance

COLS = ["رقم القيد", "رقم المستند", "التاريخ", "المستخدم", "البيان",
        "نوع الخلل"]
# 5.2.7: مستنداتٌ رُحّلت بتاريخٍ غير يوم تسجيلها
DRIFT_COLS = ["يوم التسجيل", "تاريخ المستند", "الفرق", "العملية",
              "رقم المستند", "الجهة", "الذهب", "النقد", "المستخدم", "البيان"]


class IntegrityScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user

        self.state = big_label("اضغط «تحقّق الآن» لفحص السلسلة.")
        self.detail = QtWidgets.QLabel("")
        self.detail.setObjectName("cardSub")
        self.detail.setProperty("live", True)        # نتيجةٌ لا شرح
        self.detail.setWordWrap(True)

        btn_check = kit.PushButton("🔍 تحقّق الآن")
        # الزرّ فحصٌ كامل دائماً؛ وفتح الشاشة يستأنف ما ثبت في الجلسة
        btn_check.clicked.connect(self.check_full)
        self.btn_seal = kit.PushButton("🔒 ختم القيود غير المختومة")
        self.btn_seal.setObjectName("ghost")
        self.btn_seal.clicked.connect(self.seal)
        self.btn_rebuild = kit.PushButton("♻ إعادة بناء السلسلة")
        self.btn_rebuild.setObjectName("ghost")
        self.btn_rebuild.setToolTip(
            "بعد معالجة خللٍ مُثبت (استعادة نسخة احتياطية مثلاً). "
            "العملية تُسجَّل في سجل التدقيق باسمك وزمنها.")
        self.btn_rebuild.clicked.connect(self.rebuild)

        self.table = make_table()
        enhance(self.table, key="integrity")
        self.table.setColumnCount(len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(btn_check)
        top.addWidget(self.btn_seal)
        top.addWidget(self.btn_rebuild)
        top.addStretch(1)
        top.addWidget(self.state)

        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(0, 4, 0, 0)
        intro = QtWidgets.QLabel(
            "لكل قيد بصمةٌ تُحسب من مضمونه وبصمة القيد الذي قبله معاً. "
            "فتغيير رقمٍ في قيدٍ قديم — من داخل النظام أو من خارجه — "
            "يُفسد بصمته ويُفسد معها بصمة كل ما بعده، فيظهر هنا بموضعه "
            "بالضبط.\n"
            "لا تشمل البصمة حالة الحذف المنطقي: الحذف عملٌ مشروع يجري "
            "من داخل النظام ويُوثَّق في سجل التدقيق.")
        intro.setObjectName("cardSub")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        lay.addLayout(top)
        lay.addWidget(self.detail)
        lay.addWidget(self.table, 1)
        note = QtWidgets.QLabel(
            "القيود التي رُحّلت قبل تفعيل الميزة تُختم دفعةً واحدة "
            "بمضمونها الحالي — وهذا خطُّ الأساس: السلسلة تشهد على ما "
            "بعد الختم لا على ما قبله.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)

        # ══ 5.2.7: مستنداتٌ بتاريخٍ مغاير لتاريخ النظام ══
        self.tabs = tab_widget()
        self.tabs.addTab(page, "بصمة القيود")
        self.tabs.addTab(self._drift_page(), "بتاريخٍ مغاير لتاريخ النظام")
        # ══ 5.3.2: سلامة المخزون — الحسابان مقابل الواقع ══
        self.tabs.addTab(self._stock_page(), "سلامة المخزون")
        self.tabs.currentChanged.connect(
            lambda i: self.load_drift() if i == 1 else (
                self.load_stock() if i == 2 else None))
        outer = QtWidgets.QVBoxLayout(self)
        outer.addWidget(title_label("سلامة السجل — بصمة كل قيد وسلسلتها،"
                                    " وما رُحّل بتاريخٍ مغاير"))
        outer.addWidget(self.tabs, 1)

    # ══════════ بتاريخٍ مغاير ══════════
    def _drift_page(self):
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(0, 4, 0, 0)
        intro = QtWidgets.QLabel(
            "كل فاتورة وسندٍ وقيدٍ رُحّل بتاريخٍ غير اليوم الذي سُجّل فيه في"
            " النظام — مبيعات ومرتجع وقبض وصرف وتوريد وغيرها. فاتورةٌ"
            " سُجّلت اليوم بتاريخ الأسبوع الماضي تظهر هنا بيوم تسجيلها"
            " وتاريخها والفرق بينهما ومن سجّلها. نقرةٌ مزدوجة تعاين المستند.")
        intro.setObjectName("cardSub")
        intro.setWordWrap(True)
        self.d_from = date_edit()
        self.d_from.setDate(QtCore.QDate.currentDate().addMonths(-3))
        self.d_to = date_edit()
        self.sys_chk = QtWidgets.QCheckBox(
            "مع الأرصدة الافتتاحية والإقفال وتسويات نهاية الفترة")
        btn = kit.PushButton("عرض")
        btn.clicked.connect(self.load_drift)
        bar = QtWidgets.QHBoxLayout()
        bar.addWidget(QtWidgets.QLabel("سُجّلت من:"))
        bar.addWidget(self.d_from)
        bar.addWidget(QtWidgets.QLabel("إلى:"))
        bar.addWidget(self.d_to)
        bar.addWidget(self.sys_chk)
        bar.addWidget(btn)
        bar.addStretch(1)
        self.drift_state = big_label("")
        self.drift_table = make_table()
        enhance(self.drift_table, key="integrity_drift")
        self.drift_table.setProperty(
            "emptyText", "لا مستندات رُحّلت بتاريخٍ مغاير في هذه الفترة")
        self.drift_table.doubleClicked.connect(self._preview_drift)
        self._drift = []
        lay.addWidget(intro)
        lay.addLayout(bar)
        lay.addWidget(self.drift_state)
        lay.addWidget(self.drift_table, 1)
        return page

    # ══════════ سلامة المخزون (5.3.2) ══════════
    def _stock_page(self):
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(0, 4, 0, 0)
        intro = QtWidgets.QLabel(
            "حارس المخزون يفحص كل عمليةٍ قبل حفظها: إن جعلت رصيد «الذهب"
            " المشغول» يختلف عن أوزان الأطقم الموجودة فعلاً في الخزنة، أو"
            " رصيد «ايطالي / نواعم» يختلف عن بطاقتي 0010 و00010، أو جعلت"
            " حركة طقمٍ غير منتظمة (بيعٌ وهو ليس في الخزنة، مرتجعٌ وهو فيها،"
            " حركةٌ بتاريخٍ يسبق توريده) — رُفضت كلها ولم يُحفظ منها شيء."
            "\nالفرق القائم من بياناتٍ قديمة يظهر هنا ليُصلَح بمستندٍ صحيح، ولا"
            " يُعطّل العمل.")
        intro.setObjectName("cardSub")
        intro.setWordWrap(True)
        btn = kit.PushButton("🔍 افحص الآن")
        btn.clicked.connect(self.load_stock)
        self.stock_state = big_label("")
        bar = QtWidgets.QHBoxLayout()
        bar.addWidget(btn)
        bar.addStretch(1)
        bar.addWidget(self.stock_state)
        self.stock_table = make_table()
        enhance(self.stock_table, key="integrity_stock")
        self.stock_broken = make_table()
        enhance(self.stock_broken, key="integrity_stock_broken")
        self.stock_broken.setProperty(
            "emptyText", "لا طقم حركته غير منتظمة ✔")
        self.stock_broken.doubleClicked.connect(self._preview_broken)
        self._broken = []
        lay.addWidget(intro)
        lay.addLayout(bar)
        lay.addWidget(self.stock_table)
        cap = QtWidgets.QLabel("فواتير قديمة كسرت حركة طقمها (قبل الحارس) —"
                               " نقرةٌ مزدوجة تعاين الفاتورة:")
        cap.setObjectName("cardSub")
        lay.addWidget(cap)
        lay.addWidget(self.stock_broken, 1)
        return page

    def load_stock(self):
        try:
            from models import stock_guard
            with db(readonly=True) as conn:
                rep = stock_guard.report(conn)
            rows, bad = [], 0
            for label, r, what in (
                    ("الذهب المشغول (1200)", rep["worked"],
                     "أوزان الأطقم في الخزنة"),
                    ("ايطالي / نواعم (1210)", rep["italian"],
                     "رصيد بطاقتي 0010 و00010")):
                if r is None:
                    continue
                ok = abs(r["diff"]) < 0.011
                bad += 0 if ok else 1
                rows.append((label, _nf.f2(kv.g(r["gl"])), what,
                             _nf.f2(kv.g(r["stock"])),
                             _nf.f2(kv.g(r["diff"])),
                             "✔ مطابق" if ok else "⚠ فرقٌ قديم"))
            fill(self.stock_table, ["الحساب", "رصيد الدفتر", "يقابله",
                                    "الواقع", "الفرق", "الحالة"], rows)
            from ui.widgets.table_fit import fit_columns
            fit_columns(self.stock_table, [22, 14, 22, 14, 12, 16])
            self.stock_table.setMaximumHeight(
                self.stock_table.verticalHeader().defaultSectionSize() * 3
                + self.stock_table.horizontalHeader().height() + 6)
            self._broken = rep["broken"]
            fill(self.stock_broken, ["التاريخ", "الفاتورة", "النوع", "الجهة"],
                 [(b["invoice_date"], b["invoice_no"] or "—",
                   "بيع" if b["kind"] == "sale" else "مرتجع", b["party"])
                  for b in self._broken])
            fit_columns(self.stock_broken, [18, 22, 14, 46])
            on = stock_guard.mode() == "on"
            if not bad and not self._broken:
                txt = "✔ الدفاتر = الواقع"
            else:
                txt = (f"⚠ {bad} حساب بفرقٍ قديم · "
                       f"{len(self._broken)} فاتورة قديمة غير منتظمة")
            self.stock_state.setText(txt + ("" if on else
                                            " — الحارس معطّل على هذا الجهاز"))
        except Exception as e:
            err(self, e)

    def _preview_broken(self, index):
        try:
            i = index.row()
            if 0 <= i < len(self._broken):
                from services import print_manager
                print_manager.preview_document(self, "invoices",
                                               self._broken[i]["id"])
        except Exception as e:
            err(self, e)

    def load_drift(self):
        try:
            from models import date_drift
            with db(readonly=True) as conn:
                rows = date_drift.drifted(
                    conn, dstr(self.d_from), dstr(self.d_to),
                    include_system=self.sys_chk.isChecked())
            self._drift = rows
            data = [(r["registered"][:16], r["date"],
                     date_drift.days_text(r["days"]), r["op"], r["doc_no"],
                     r["party"] or "—",
                     _nf.f2(kv.g(r["gold"])) if r["gold"] else "—",
                     _nf.f2(r["cash"]) if r["cash"] else "—",
                     r["who"] or "—", (r["desc"] or "")[:70])
                    for r in rows]
            fill(self.drift_table, DRIFT_COLS, data)
            # الأعمدة على عرض الجدول كله: يوم التسجيل بساعته والبيان أعرض
            from ui.widgets.table_fit import fit_columns
            fit_columns(self.drift_table, [12, 9, 9, 7, 9, 16, 8, 8, 7, 15])
            back = sum(1 for r in rows if r["days"] < 0)
            self.drift_state.setText(
                f"{len(rows):,} مستنداً بتاريخٍ مغاير — {back:,} بتاريخٍ"
                f" أقدم من يوم تسجيله و{len(rows) - back:,} بتاريخٍ أحدث"
                if rows else "✔ لا مستندات بتاريخٍ مغاير في هذه الفترة")
        except Exception as e:
            err(self, e)

    def _preview_drift(self, index):
        try:
            i = index.row()
            if not (0 <= i < len(self._drift)):
                return
            r = self._drift[i]
            from services import print_manager
            if r["src"] and r["sid"] and r["src"] in print_manager.BUILDERS:
                print_manager.preview_document(self, r["src"], r["sid"])
            else:
                print_manager.preview_document(self, "manual", r["eid"])
        except Exception as e:
            err(self, e)

    def check_full(self):
        self.run_check(full=True)

    def run_check(self, full=False):
        try:
            with db(readonly=True) as conn:
                rep = integrity.verify(conn, full=bool(full))
        except Exception as e:
            err(self, e)
            return
        rows = [(b["id"], b["doc_no"], b["date"], b["who"],
                 (b["desc"] or "")[:60], b["kind"]) for b in rep["breaks"]]
        fill(self.table, COLS, rows)
        self.btn_seal.setEnabled(bool(rep["unsealed"]))
        if rep["ok"] and not rep["unsealed"]:
            self.state.setText(f"✔ السلسلة سليمة — {rep['checked']:,} قيداً")
        elif rep["ok"]:
            self.state.setText(
                f"✔ السلسلة سليمة — {rep['checked']:,} قيداً مختوماً · "
                f"{rep['unsealed']:,} بلا بصمة")
        else:
            self.state.setText(
                f"⛔ خللٌ في {len(rep['breaks'])} قيداً — راجع الجدول")
        bits = [f"مختوم: {rep['checked']:,}",
                f"غير مختوم: {rep['unsealed']:,}"]
        if rep["first_sealed"]:
            bits.append(f"من القيد {rep['first_sealed']} "
                        f"إلى {rep['last_sealed']}")
        if not rep["ok"]:
            bits.append("⛔ القيد الأول المختل هو موضع البداية: كل ما "
                        "بعده يظهر مختلاً تبعاً له، فعالجه أولاً ثم "
                        "أعد الفحص")
        self.detail.setText("  ·  ".join(bits))

    def seal(self):
        """يختم ما لا بصمة له — خطّ الأساس لقاعدةٍ تعمل منذ قبل الميزة."""
        try:
            with db(readonly=True) as conn:
                st = integrity.status(conn)
            if not st["unsealed"]:
                info(self, "كل القيود مختومة.")
                return
            if not ask(self,
                       f"ختم {st['unsealed']:,} قيداً بمضمونها الحالي؟\n\n"
                       "هذا خطُّ الأساس: ما بعده تشهد عليه السلسلة، وما "
                       "قبله لا تشهد عليه. لا يتغيّر رقمٌ محاسبي واحد — "
                       "تُكتب البصمات وحدها."):
                return
            with db() as conn:
                n = integrity.seal_all(conn, self.user.get("username"))
            info(self, f"خُتم {n:,} قيداً.")
            self.run_check(full=True)
        except Exception as e:
            err(self, e)

    def rebuild(self):
        """يعيد ربط السلسلة بعد معالجة خللٍ مُثبت — بقرارٍ صريح مسجَّل."""
        try:
            if not ask(self,
                       "إعادة بناء سلسلة البصمات من أولها؟\n\n"
                       "تُستعمل بعد معالجة خللٍ مُثبت: استعادة نسخة "
                       "احتياطية، أو صيانةٍ مسحت سجلات، أو تعديلٍ جرى "
                       "بنسخةٍ قديمة من النظام.\n\n"
                       "• لا يتغيّر رقمٌ محاسبي واحد — تُعاد كتابة "
                       "البصمات وحدها.\n"
                       "• بعدها تشهد السلسلة على الحالة الراهنة، ولا "
                       "تشهد على ما سبق إعادة البناء.\n"
                       "• العملية تُسجَّل في سجل التدقيق باسمك وزمنها."):
                return
            with db() as conn:
                n = integrity.rebuild(conn, username=self.user.get("username"))
            info(self, f"أُعيد بناء السلسلة — {n:,} قيداً.")
            self.run_check(full=True)
        except Exception as e:
            err(self, e)

    def refresh(self):
        if getattr(self, "tabs", None) is not None \
                and self.tabs.currentIndex() == 1:
            self.load_drift()
        elif getattr(self, "tabs", None) is not None \
                and self.tabs.currentIndex() == 2:
            self.load_stock()
        else:
            self.run_check()

    def open_tab(self, title):
        """يفتح قسماً باسمه — من القائمة الجانبية (5.2.7)."""
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == title:
                self.tabs.setCurrentIndex(i)
                return
