# -*- coding: utf-8 -*-
"""لوحة التحكم — لوحات رئيسية بجداول حسابات.

**البنية**: صف لوحات مضغوطة في الأعلى؛ النقر على لوحة يفتح جدولها
كاملاً أسفلها: كل حساب بمدينه ودائنه ورصيده، وصف إجمالي بارز.

**الأساس المحاسبي**: اللوحة تجميع **عرضي** لا محاسبي — لا تُنشئ حساباً
ولا قيداً، بل تعرض أرصدة حسابات قائمة في الدليل. فإضافة لوحة أو حذفها
أو تعديل حساباتها لا يمسّ أي ميزان.

**لوحة صندوق الكسر** خاصة: الصندوق حساب واحد يضمّ الأعيرة الأربعة
(18·21·22·24)، فتعرض وزن كل عيار الفعلي ومكافئه بعيار 18 والإجمالي.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from ui import kit

from database.database import db
from models import dash_panels as dp
from services import karat_view as kv
from ui.widgets.common import (ask, big_label, date_edit, dstr, err,
                               info, make_table, search_combo,
                               title_label)
from services import numfmt as _nf
from ui.widgets.common import guard_click

def _acc_label(r):
    """اسم الصف: «الرمز — الاسم» للحساب، والاسم وحده لصفّ «ايطالي / نواعم»."""
    return r["name"] if r.get("virtual") else f"{r['code']} — {r['name']}"


def ACC_COLS_NOW():
    """عناوين أعمدة الأرصدة بعيار المصنع الفعّال."""
    return ["الاسم", f"رصيد الذهب ({kv.unit()})", "الرصيد النقدي (ريال)"]


ACC_COLS = ["الاسم", "رصيد الذهب (جم 18)", "الرصيد النقدي (ريال)"]
def SCRAP_COLS_NOW():
    """الوزن الفعلي لكل عيار يبقى كما هو — وزنٌ حقيقي لا مكافئ.
    المكافئ وحده يتحوّل بعيار المصنع."""
    return ["العيار", "الوزن الفعلي (جم)",
            f"المكافئ ({kv.unit()})"]


SCRAP_COLS = ["العيار", "الوزن الفعلي (جم)", "المكافئ بعيار 18 (جم)"]


def _signed(v):
    """رقمٌ بإشارة ناقصٍ في مكانها: LRM قبلها، فلا يُعرض «300-» في سطرٍ
    عربي (لوحة الأرباح والخسائر — 4.91)."""
    v = float(v or 0.0)
    return (f"\u200e-{_nf.f2(abs(v))}" if v < -0.004 else _nf.f2(abs(v)))


class _LazyRows:
    """صفوف جدولٍ تُصاغ نصوصها عند الطلب، وآخرها صفّ الإجمالي."""

    def __init__(self, rows, fn, tail):
        self._rows, self._fn, self._tail = rows, fn, tail

    def __len__(self):
        return len(self._rows) + 1

    def __getitem__(self, i):
        if i < 0:
            i += len(self)
        if i == len(self._rows):
            return self._tail
        return self._fn(self._rows[i])


class PanelButton(QtWidgets.QPushButton):
    """لوحة رئيسية: عنوان وقيمة، بحجم مضغوط لا يمتد بعرض الشاشة."""

    def __init__(self, title):
        super().__init__()
        self.setCheckable(True)
        self.setObjectName("dashPanel")
        # أصغر: تُضاف لوحات كثيرة فلا يتمدّد الصف ويُدفع الجدول
        self.setMinimumWidth(146)
        self.setMaximumWidth(196)
        self.setMinimumHeight(62)
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed,
                           QtWidgets.QSizePolicy.Fixed)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.title = title
        self.value = "—"
        self._render()

    def set_value(self, value):
        self.value = value
        self._render()

    def _render(self):
        self.setText(f"{self.title}\n{self.value}")


class DashboardScreen(QtWidgets.QWidget):
    def __init__(self, user, on_drill_code=None, on_open_subledger=None):
        super().__init__()
        self.user = user
        self.on_drill_code = on_drill_code
        self.on_open_subledger = on_open_subledger
        self.panels = dp.load_panels()
        self.current = 0
        self.buttons = []
        self._rows = []

        # ── صف اللوحات ──
        self.panel_row = QtWidgets.QHBoxLayout()
        self.panel_row.setSpacing(8)
        self.panel_box = QtWidgets.QWidget()
        self.panel_box.setLayout(self.panel_row)

        btn_add_panel = kit.PushButton("➕ لوحة رئيسية")
        btn_add_panel.setToolTip("ينشئ لوحة جديدة تجمع حسابات تختارها")
        btn_add_panel.clicked.connect(self.add_panel)
        btn_del_panel = kit.PushButton("🗑 حذف اللوحة")
        btn_del_panel.clicked.connect(self.del_panel)
        btn_rename = kit.PushButton("✎ تسمية اللوحة")
        btn_rename.clicked.connect(self.rename_panel)

        # هذه الأزرار تُعرض في الشريط العلوي بجوار «إغلاق الشاشة»
        btn_left = kit.PushButton("◄")
        btn_left.setToolTip("تحريك اللوحة يميناً")
        btn_left.setMaximumWidth(36)
        btn_left.clicked.connect(lambda: self.move_panel(-1))
        btn_right = kit.PushButton("►")
        btn_right.setToolTip("تحريك اللوحة يساراً")
        btn_right.setMaximumWidth(36)
        btn_right.clicked.connect(lambda: self.move_panel(1))
        self._top_tools = [btn_left, btn_right, btn_rename,
                           btn_add_panel, btn_del_panel]

        top = QtWidgets.QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(self.panel_box, 0)
        top.addStretch(1)

        # ── أدوات الجدول ──
        self.tbl_title = big_label()
        btn_add_acc = kit.PushButton("➕ إضافة حساب للجدول")
        btn_add_acc.setToolTip("يضيف حساباً من دليل الحسابات لهذه اللوحة")
        btn_add_acc.clicked.connect(self.add_account)
        btn_del_acc = kit.PushButton("🗑 حذف الحساب المحدد")
        btn_del_acc.clicked.connect(self.del_account)
        btn_print = kit.PushButton("🖨 طباعة الجدول")
        btn_print.setToolTip("قالب مطابق لما يظهر على الشاشة")
        btn_print.clicked.connect(self.print_panel)
        btn_ratio = kit.PushButton("％ النسبة")
        btn_ratio.setToolTip("شريط نسبة أسفل الجدول: الثاني ÷ الأول")
        btn_ratio.clicked.connect(self.add_ratio)
        btn_up = kit.PushButton("▲")
        btn_up.setToolTip("تحريك الصف لأعلى")
        btn_up.setMaximumWidth(38)
        btn_up.clicked.connect(lambda: self.move_row(-1))
        btn_dn = kit.PushButton("▼")
        btn_dn.setToolTip("تحريك الصف لأسفل")
        btn_dn.setMaximumWidth(38)
        btn_dn.clicked.connect(lambda: self.move_row(1))
        btn_refresh = kit.PushButton("↻ تحديث")
        btn_refresh.clicked.connect(self.refresh)

        # أدوات لوحة أرقام التشغيل — تظهر معها وحدها
        self.stock_search = kit.LineEdit()
        self.stock_search.setPlaceholderText("ابحث برقم التشغيل أو الموديل…")
        self.stock_search.setMaximumWidth(230)
        # (5.2.9) البحث بعد أن تهدأ الكتابة: كان كل حرفٍ يعيد قراءة آلاف
        # الأطقم وبناء الجدول كاملاً — فتتجمّد الواجهة مع الكتابة السريعة
        self._search_timer = QtCore.QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(260)
        self._search_timer.timeout.connect(
            lambda: self.refresh() if self._is_stock() else None)
        self.stock_search.textChanged.connect(
            lambda *_: self._search_timer.start())
        try:
            self.stock_search.returnPressed.connect(
                lambda: (self._search_timer.stop(), self.refresh()))
        except Exception:
            pass
        self.btn_edit_wo = kit.PushButton("✎ تعديل الطقم")
        self.btn_edit_wo.setToolTip(
            "يعدّل موديل الطقم أو رقم تشغيله (نقر مزدوج على الصف)")
        self.btn_edit_wo.clicked.connect(self.edit_stock_item)
        self.btn_del_wo = kit.PushButton("🗑 حذف الطقم")
        self.btn_del_wo.setObjectName("ghost")
        self.btn_del_wo.setToolTip(
            "يحذف رقم التشغيل المحدَّد (والتجميعي كذلك) فيختفي من هنا ومن"
            " دليل الموديلات — بلا أي أثر على الأرصدة")
        self.btn_del_wo.clicked.connect(self.delete_stock_item)
        self._stock_tools = [self.stock_search, self.btn_edit_wo,
                             self.btn_del_wo]

        tools = QtWidgets.QHBoxLayout()
        tools.setSpacing(6)
        tools.addWidget(self.tbl_title, 1)
        tools.addWidget(self.stock_search)
        tools.addWidget(self.btn_edit_wo)
        tools.addWidget(self.btn_del_wo)
        tools.addWidget(btn_up)
        tools.addWidget(btn_dn)
        tools.addWidget(btn_add_acc)
        tools.addWidget(btn_del_acc)
        tools.addWidget(btn_ratio)
        tools.addWidget(btn_print)
        tools.addWidget(btn_refresh)
        self._acc_tools = [btn_up, btn_dn, btn_add_acc, btn_del_acc,
                           btn_ratio]

        self.table = make_table()
        self.table.doubleClicked.connect(guard_click(self._drill_row))
        # لوحة صناديق الكسر: نقرةٌ واحدة على العيار تفتح كشفه
        self.table.clicked.connect(self._click_row)
        self.totals = big_label()

        # نطاق التاريخ لهذه اللوحة — يُحفظ معها
        self.d_from = date_edit()
        self.d_from.setDate(
            QtCore.QDate(QtCore.QDate.currentDate().year(), 1, 1))
        self.d_to = date_edit()
        # الفترة تُختار باسمها فتُحسب تواريخها وتظهر الأرقام فوراً — والكتابة
        # باليد في «فترة مخصّصة» وحدها (4.49)
        self.period = kit.ComboBox()
        for k, lbl in dp.PERIODS:
            self.period.addItem(lbl, k)
        self.period.setToolTip("اختر المدة فتظهر أرقامها مباشرةً —"
                               " «كل الحركة» منذ بداية النشاط")
        try:
            for w in (self.d_from, self.d_to):
                w.dateChanged.connect(self._period_changed)
            self.period.currentIndexChanged.connect(self._period_changed)
        except Exception:
            pass          # بيئة بلا إشارات Qt حقيقية
        # مقارنة بالفترة السابقة المساوية طولاً — الرقم وحده لا يقول
        # إن كان النشاط يصعد أو يهبط.
        self.compare = kit.CheckBox("مقارنة بالفترة السابقة")
        self.compare.setToolTip(
            "يضيف أعمدة الفترة السابقة (بنفس الطول) والفرق ونسبته.\n"
            "المقارنة على حجم الحركة لا على الرصيد التراكمي.")
        try:
            self.compare.stateChanged.connect(lambda *_: self.refresh())
        except Exception:
            pass
        lbl_from = QtWidgets.QLabel("من:")
        lbl_to = QtWidgets.QLabel("إلى:")
        per = QtWidgets.QHBoxLayout()
        per.setSpacing(6)
        lbl_per = QtWidgets.QLabel("المدة:")
        per.addWidget(lbl_per)
        per.addWidget(self.period)
        per.addWidget(lbl_from)
        per.addWidget(self.d_from)
        per.addWidget(lbl_to)
        per.addWidget(self.d_to)
        per.addWidget(self.compare)
        per.addStretch(1)
        # ── فترات «الأرباح والخسائر» (4.92) — كرابط المدير ──
        # خلال السنة (افتراضاً) · الشهر الحالي · الشهر السابق نقرةً بعد
        # نقرة · الأحدث. والرجوع بالأشهر يقف عند «يُعتمد من»
        # (`dp.pnl_range`)، و«خلال السنة» من أول السنة كاملةً.
        self._pnl_per, self._pnl_m = "year", 0
        self.pnl_year = kit.PushButton("خلال السنة")
        self.pnl_cur = kit.PushButton("الشهر الحالي")
        self.pnl_prev = kit.PushButton("الشهر السابق")
        self.pnl_next = kit.PushButton("الشهر الأحدث")
        self.pnl_year.clicked.connect(lambda *_: self._pnl_go("year", 0))
        self.pnl_cur.clicked.connect(lambda *_: self._pnl_go("month", 0))
        self.pnl_prev.clicked.connect(lambda *_: self._pnl_go(
            "month", self._pnl_m + 1
            if self._pnl_per == "month" and self._pnl_m >= 1 else 1))
        self.pnl_next.clicked.connect(lambda *_: self._pnl_go(
            "month", max(self._pnl_m - 1, 0)))
        self.pnl_lbl = QtWidgets.QLabel("")
        lbl_start = QtWidgets.QLabel("يُعتمد من:")
        self.pnl_start = date_edit()
        self.pnl_start.setToolTip("«الشهر السابق» يرجع حتى شهر هذا التاريخ"
                                  " ويقف — هنا وفي رابط المدير. و«خلال"
                                  " السنة» من أول السنة كاملةً")
        try:
            self.pnl_start.dateChanged.connect(self._pnl_start_changed)
        except Exception:
            pass
        for w in (self.pnl_year, self.pnl_cur, self.pnl_prev,
                  self.pnl_next, self.pnl_lbl, lbl_start, self.pnl_start):
            per.insertWidget(per.count() - 1, w)
        self._pnl_tools = [self.pnl_year, self.pnl_cur, self.pnl_prev,
                           self.pnl_next, self.pnl_lbl, lbl_start,
                           self.pnl_start]
        self._period_row = per
        # صفُّ الفترة كلُّه — ليُخفى مع عناوينه، لا حقولُه وحدها
        self._period_tools = [lbl_per, self.period, lbl_from, self.d_from,
                              lbl_to, self.d_to, self.compare]
        self._date_tools = [lbl_from, self.d_from, lbl_to, self.d_to]

        # أشرطة النسب البارزة أسفل الجدول
        self.ratio_box = QtWidgets.QWidget()
        self.ratio_lay = QtWidgets.QVBoxLayout(self.ratio_box)
        self.ratio_lay.setContentsMargins(0, 2, 0, 2)
        self.ratio_lay.setSpacing(3)

        note = QtWidgets.QLabel(
            "اضغط أي لوحة لعرض جدول حساباتها · نقر مزدوج على الصف يفتح "
            "كشف الحساب · اللوحات عرض فقط ولا تُنشئ قيوداً.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(5)
        lay.addWidget(title_label("لوحة التحكم"))
        lay.addWidget(note)
        lay.addLayout(top)
        lay.addLayout(tools)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.totals)
        lay.addWidget(self.ratio_box)
        lay.addLayout(self._period_row)

        self._build_buttons()
        self.refresh()

    def toolbar_widgets(self):
        """أزرار الشاشة العامة — تُعرض في الشريط العلوي."""
        return list(getattr(self, "_top_tools", []))

    # ══════════ اللوحات ══════════
    def _build_buttons(self):
        for b in self.buttons:
            self.panel_row.removeWidget(b)
            b.setParent(None)
            b.deleteLater()
        self.buttons = []
        self._btn_sig = None          # أزرارٌ جديدة: أرقامها تُحسب من جديد
        for i, p in enumerate(self.panels):
            b = PanelButton(p["title"])
            b.clicked.connect(lambda _=False, k=i: self._select_soon(k))
            self.panel_row.addWidget(b)
            self.buttons.append(b)
        self._sync_checked()

    def _sync_checked(self):
        for i, b in enumerate(self.buttons):
            b.setChecked(i == self.current)

    def select(self, idx):
        if 0 <= idx < len(self.panels):
            if idx != self.current:
                # «الأرباح والخسائر» تُفتح دائماً على «خلال السنة»
                self._pnl_per, self._pnl_m = "year", 0
            self.current = idx
            self._sync_checked()
            self.refresh()

    def _select_soon(self, idx):
        """نقرة المستخدم على لوحة (5.2.9): الزرّ يُؤشَّر فوراً، والجدول
        يُحدَّث مرةً واحدة لآخر لوحةٍ استقرّ عليها.

        كانت كل نقرةٍ تحدّث الجدول وأرقام كل اللوحات قبل أن تُعالَج النقرة
        التالية: خمس نقراتٍ سريعة = خمس قراءاتٍ كاملة متتابعة والواجهة
        واقفة حتى تنتهي — «لا يستجيب» وشاشة بيضاء. الآن النقرات المتتابعة
        تُدمج، ولا يُقرأ إلا ما انتهى إليه المستخدم."""
        if not (0 <= idx < len(self.panels)):
            return
        if idx != self.current:
            self._pnl_per, self._pnl_m = "year", 0
        self.current = idx
        self._sync_checked()
        t = self.__dict__.get("_sel_timer")
        if t is None:
            t = QtCore.QTimer(self)
            t.setSingleShot(True)
            t.setInterval(0)
            t.timeout.connect(self.refresh)
            self._sel_timer = t
        t.start()

    def move_panel(self, delta):
        """يحرّك اللوحة الحالية في ترتيب الصف — ويُحفظ الترتيب."""
        try:
            i = self.current
            j = i + delta
            if not (0 <= j < len(self.panels)):
                return
            self.panels[i], self.panels[j] = self.panels[j], self.panels[i]
            dp.save_panels(self.panels)
            self.current = j
            self._build_buttons()
            self.refresh()
        except Exception as e:
            err(self, e)

    def add_panel(self):
        try:
            dlg = QtWidgets.QDialog(self)
            dlg.setWindowTitle("لوحة رئيسية جديدة")
            dlg.setMinimumWidth(420)
            e_name = kit.LineEdit()
            e_name.setPlaceholderText("اسم اللوحة")
            cb_unit = kit.ComboBox()
            cb_unit.addItem(f"الوزن ({kv.unit()})", "gold")
            cb_unit.addItem("النقد (ريال)", "cash")
            note = QtWidgets.QLabel(
                "الوحدة تحدّد الرقم المعروض على واجهة اللوحة.\n"
                "الجدول يعرض البعدين معاً على أي حال.")
            note.setObjectName("cardSub")
            note.setWordWrap(True)
            box = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.Ok
                | QtWidgets.QDialogButtonBox.Cancel)
            box.accepted.connect(dlg.accept)
            box.rejected.connect(dlg.reject)
            f = QtWidgets.QFormLayout()
            f.addRow("اسم اللوحة:", e_name)
            f.addRow("وحدة العرض:", cb_unit)
            f.addRow(note)
            lay = QtWidgets.QVBoxLayout(dlg)
            lay.addLayout(f)
            lay.addWidget(box)
            if dlg.exec_() != QtWidgets.QDialog.Accepted:
                return
            name = e_name.text().strip()
            if not name:
                raise ValueError("أدخل اسم اللوحة")
            self.panels.append({"key": name, "title": name,
                                "accounts": [], "kind": "accounts",
                                "unit": cb_unit.currentData() or "gold"})
            dp.save_panels(self.panels)
            self.current = len(self.panels) - 1
            self._build_buttons()
            self.refresh()
            info(self, f"أُنشئت اللوحة «{name}».\n"
                       f"أضف إليها حسابات من زر «إضافة حساب للجدول».")
        except Exception as e:
            err(self, e)

    def del_panel(self):
        try:
            if len(self.panels) <= 1:
                raise ValueError("لا يمكن حذف آخر لوحة")
            p = self.panels[self.current]
            if not ask(self, f"حذف لوحة «{p['title']}»؟\n\n"
                             f"العرض فقط — لا تتأثر أي حسابات أو قيود."):
                return
            self.panels.pop(self.current)
            dp.save_panels(self.panels)
            self.current = max(0, self.current - 1)
            self._build_buttons()
            self.refresh()
        except Exception as e:
            err(self, e)

    def rename_panel(self):
        try:
            p = self.panels[self.current]
            name, ok = QtWidgets.QInputDialog.getText(
                self, "تسمية اللوحة", "الاسم الجديد:", text=p["title"])
            if not ok or not name.strip():
                return
            p["title"] = name.strip()
            dp.save_panels(self.panels)
            self._build_buttons()
            self.refresh()
        except Exception as e:
            err(self, e)

    # ══════════ الحسابات ══════════
    def add_account(self):
        try:
            p = self.panels[self.current]
            if p.get("kind") == "scrap":
                raise ValueError(
                    "لوحة صندوق الكسر تعرض الأعيرة تلقائياً — "
                    "لا تُضاف إليها حسابات")
            if p.get("kind") == "stock":
                raise ValueError(
                    "لوحة أرقام التشغيل تعرض المتاح للبيع تلقائياً — "
                    "لا تُضاف إليها حسابات")
            with db(readonly=True) as conn:
                accs = [dict(r) for r in conn.execute(
                    "SELECT code, name FROM accounts ORDER BY code")]
            # قائمة بحث حيّ: تقترح أقرب اسم مع أول حرف تكتبه
            dlg = QtWidgets.QDialog(self)
            dlg.setWindowTitle("إضافة حساب للجدول")
            dlg.setMinimumWidth(460)
            cb = search_combo("اكتب رقم الحساب أو اسمه…")
            # صفّ «ايطالي / نواعم» (0010 · 00010) — كشفٌ من المستندات
            cb.addItem("ايطالي / نواعم — الرقمان 0010 و00010", dp.ITALIAN)
            for a in accs:
                cb.addItem(f"{a['code']} — {a['name']}", a["code"])
            cb.clear_selection()
            note = QtWidgets.QLabel(
                "يُعرض الحساب **وفروعه** مجمّعاً في صف واحد.")
            note.setObjectName("cardSub")
            note.setWordWrap(True)
            box = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.Ok
                | QtWidgets.QDialogButtonBox.Cancel)
            box.accepted.connect(dlg.accept)
            box.rejected.connect(dlg.reject)
            f = QtWidgets.QFormLayout()
            f.addRow("الحساب:", cb)
            f.addRow(note)
            lay = QtWidgets.QVBoxLayout(dlg)
            lay.addLayout(f)
            lay.addWidget(box)
            if dlg.exec_() != QtWidgets.QDialog.Accepted:
                return
            code = cb.currentData()
            if not code:
                txt = cb.currentText().strip()
                code = txt.split("—")[0].strip() if "—" in txt else txt
            if not code:
                raise ValueError("اختر حساباً من القائمة")
            # «ايطالي / نواعم» حسابٌ رسمي (1210) — يُضاف برمزه كأي حساب
            if code == dp.ITALIAN:
                code = dp.ITALIAN_ACC
            same = {code} | ({dp.ITALIAN} if code == dp.ITALIAN_ACC else set())
            if same & set(p["accounts"]):
                raise ValueError("الحساب مضاف مسبقاً في هذه اللوحة")
            p["accounts"].append(code)
            dp.save_panels(self.panels)
            self.refresh()
        except Exception as e:
            err(self, e)

    def del_account(self):
        try:
            p = self.panels[self.current]
            if p.get("kind") in ("scrap", "stock"):
                raise ValueError("صفوف هذه اللوحة تُبنى تلقائياً ولا تُحذف")
            i = self.table.currentRow()
            if not (0 <= i < len(self._rows)):
                raise ValueError("اختر حساباً من الجدول أولاً")
            code = self._rows[i].get("code")
            # «ايطالي / نواعم»: صفّه يظهر برمز حسابه (1210) والمحفوظ في
            # اللوحة رمزه القديم — فكان الحذف يقول «لا يُحذف» (5.2.5)
            if code == dp.ITALIAN_ACC and code not in p["accounts"] \
                    and dp.ITALIAN in p["accounts"]:
                code = dp.ITALIAN
            if not code or code not in p["accounts"]:
                raise ValueError("هذا الصف لا يُحذف")
            if not ask(self, f"حذف «{_acc_label(self._rows[i])}» من لوحة"
                             f" «{p['title']}»؟\n\nيُحذف من اللوحة فقط — "
                             "الحساب وقيوده باقية، وتعيده بـ«إضافة حساب»."):
                return
            p["accounts"].remove(code)
            p["ratios"] = [r for r in (p.get("ratios") or [])
                           if code not in (r.get("first"), r.get("second"))]
            dp.save_panels(self.panels)
            self.refresh()
        except Exception as e:
            err(self, e)

    def move_row(self, delta):
        """يحرّك الحساب المحدد في ترتيب الجدول."""
        try:
            p = self.panels[self.current]
            if p.get("kind") in ("scrap", "stock"):
                raise ValueError("ترتيب صفوف هذه اللوحة تلقائي")
            i = self.table.currentRow()
            accs = p["accounts"]
            if not (0 <= i < len(accs)):
                raise ValueError("اختر حساباً من الجدول أولاً")
            j = i + delta
            if not (0 <= j < len(accs)):
                return
            accs[i], accs[j] = accs[j], accs[i]
            dp.save_panels(self.panels)
            self.refresh()
            self.table.setCurrentCell(j, 0)
        except Exception as e:
            err(self, e)

    def add_ratio(self):
        """يضيف شريط نسبة أسفل الجدول: الحساب الثاني ÷ الأول."""
        try:
            p = self.panels[self.current]
            if p.get("kind") == "stock":
                raise ValueError("لوحة أرقام التشغيل لا نسب فيها")
            accs = p.get("accounts") or []
            if len(accs) < 2:
                raise ValueError(
                    "أضف حسابين على الأقل للجدول قبل إنشاء نسبة")
            with db(readonly=True) as conn:
                names = {}
                for c in accs:
                    r = conn.execute(
                        "SELECT name FROM accounts WHERE code=?",
                        (c,)).fetchone()
                    names[c] = r["name"] if r else c
            items = [f"{c} — {names[c]}" for c in accs]

            dlg = QtWidgets.QDialog(self)
            dlg.setWindowTitle("شريط نسبة جديد")
            dlg.setMinimumWidth(420)
            e_title = kit.LineEdit()
            e_title.setPlaceholderText("اسم النسبة — مثل: نسبة التحصيل")
            cb1 = kit.ComboBox()
            cb2 = kit.ComboBox()
            for cb in (cb1, cb2):
                for c in accs:
                    cb.addItem(f"{c} — {names[c]}", c)
            if cb2.count() > 1:
                cb2.setCurrentIndex(1)
            note = QtWidgets.QLabel(
                "النسبة = رصيد الحساب الثاني ÷ رصيد الأول × 100.\n"
                "تُعرض في شريط بارز أسفل الجدول لا بين صفوفه — فهي "
                "مؤشر لا رصيد، وإدراجها بينها يُفسد الإجمالي.")
            note.setObjectName("cardSub")
            note.setWordWrap(True)
            f = QtWidgets.QFormLayout()
            f.addRow("اسم النسبة:", e_title)
            f.addRow("الحساب الأول (المقام):", cb1)
            f.addRow("الحساب الثاني (البسط):", cb2)
            cb_mode = kit.ComboBox()
            cb_mode.addItem("مئوية مباشرة — الثاني ÷ الأول", "direct")
            cb_mode.addItem("عكسية — الفرق ÷ الأول", "inverse")
            cb_mode.setToolTip(
                "مثال على 10 و 8:\n"
                "   مباشرة → 80%\n"
                "   عكسية  → 20%")
            cb_dim = kit.ComboBox()
            cb_dim.addItem("تلقائي (ذهب أو نقد)", "")
            cb_dim.addItem("الذهب", "gold")
            cb_dim.addItem("النقد", "cash")
            f.addRow("نوع النسبة:", cb_mode)
            f.addRow("البعد:", cb_dim)
            f.addRow(note)
            box = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.Ok
                | QtWidgets.QDialogButtonBox.Cancel)
            box.accepted.connect(dlg.accept)
            box.rejected.connect(dlg.reject)
            lay = QtWidgets.QVBoxLayout(dlg)
            lay.addLayout(f)
            lay.addWidget(box)
            if dlg.exec_() != QtWidgets.QDialog.Accepted:
                return
            a, b = cb1.currentData(), cb2.currentData()
            if not a or not b or a == b:
                raise ValueError("اختر حسابين مختلفين")
            p.setdefault("ratios", []).append({
                "title": e_title.text().strip()
                         or f"{names[b]} ÷ {names[a]}",
                "first": a, "second": b,
                "mode": cb_mode.currentData() or "direct",
                "dim": cb_dim.currentData() or ""})
            dp.save_panels(self.panels)
            self.refresh()
        except Exception as e:
            err(self, e)

    def del_ratio(self, idx):
        try:
            p = self.panels[self.current]
            rs = p.get("ratios") or []
            if 0 <= idx < len(rs):
                if not ask(self, f"حذف شريط «{rs[idx].get('title')}»؟"):
                    return
                rs.pop(idx)
                dp.save_panels(self.panels)
                self.refresh()
        except Exception as e:
            err(self, e)

    def _pnl_go(self, per, m):
        self._pnl_per, self._pnl_m = per, m
        self.refresh()

    def _pnl_start_changed(self, *_):
        """«يُعتمد من» يُحفظ مع اللوحة — والرابط يقرؤه منها."""
        if getattr(self, "_loading", False):
            return
        try:
            p = self.panels[self.current]
            p["start"] = dstr(self.pnl_start)
            dp.save_panels(self.panels)
            self.refresh()
        except Exception:
            pass

    def _pnl_apply(self, p):
        """يكتب تواريخ لوحة الأرباح والخسائر من فترتها المختارة هنا."""
        rg = dp.pnl_range(self._pnl_per, self._pnl_m, dp.pnl_start(p))
        self._pnl_per, self._pnl_m = rg["per"], rg["m"]
        p["date_from"] = rg["from"].isoformat()
        p["date_to"] = rg["to"].isoformat()
        return rg

    def _pnl_sync(self, p, rg):
        """أزرار الفترة على حالها: المختار مؤشَّر، والسابق يقف عند شهر
        بداية الاعتماد، والأحدث يظهر بعد الرجوع شهرين فأكثر."""
        per, m = rg["per"], rg["m"]
        # المختار بعلامة ✔ — أزرار Fluent لا تُظهر حالة «مضغوط»
        for b, t, on in ((self.pnl_year, "خلال السنة", per == "year"),
                         (self.pnl_cur, "الشهر الحالي",
                          per == "month" and m == 0),
                         (self.pnl_prev, "الشهر السابق",
                          per == "month" and m >= 1)):
            b.setText(("✔ " if on else "") + t)
        back = m + 1 if per == "month" and m >= 1 else 1
        self.pnl_prev.setEnabled(back <= rg["max"])
        st = dp.pnl_start(p)
        self.pnl_prev.setToolTip("" if back <= rg["max"] else
                                 f"يبدأ الاعتماد من {st}")
        self.pnl_next.setVisible(per == "month" and m >= 2)
        self.pnl_lbl.setText(f"{rg['label']}: {rg['from']} → {rg['to']}")
        if st:
            self.pnl_start.setDate(QtCore.QDate(st.year, st.month, st.day))

    def _period_changed(self, *_):
        """يحفظ نطاق التاريخ مع اللوحة ويعيد العرض."""
        try:
            if getattr(self, "_loading", False):
                return
            p = self.panels[self.current]
            k = self.period.currentData() or "all"
            p["period"] = k
            if k == "custom":
                p["date_from"] = dstr(self.d_from)
                p["date_to"] = dstr(self.d_to)
            else:
                dp.apply_period(p)
            dp.save_panels(self.panels)
            self.refresh()
        except Exception:
            pass

    def _render_ratios(self, rows, p):
        """يبني أشرطة النسب البارزة أسفل الجدول."""
        while self.ratio_lay.count():
            it = self.ratio_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
        bars = dp.ratio_bars(rows, p.get("ratios") or [], p.get("unit"))
        for i, b in enumerate(bars):
            frame = QtWidgets.QFrame()
            frame.setObjectName("ratioBar")
            pct = ("—" if b["pct"] is None else f"{_nf.f2(b['pct'])}%")
            # الذهب بعيار العرض كما في الجدول فوقه — لا بمكافئ 18
            g = (lambda v: kv.g(v)) if b.get("dim") == "gold" else float
            unit = (f"جم {kv.label()}" if b.get("dim") == "gold"
                    else b.get("unit", ""))
            lbl = QtWidgets.QLabel(
                f"{b['title']}:   {pct}      "
                f"({b['second_name']} {_signed(g(b['second_value']))}  ÷  "
                f"{b['first_name']} {_signed(g(b['first_value']))} "
                f"{unit})")
            lbl.setWordWrap(True)
            x = kit.PushButton("✕")
            x.setMaximumWidth(30)
            x.setToolTip("حذف هذا الشريط")
            x.clicked.connect(lambda _=False, k=i: self.del_ratio(k))
            h = QtWidgets.QHBoxLayout(frame)
            h.setContentsMargins(8, 4, 8, 4)
            h.addWidget(lbl, 1)
            h.addWidget(x)
            self.ratio_lay.addWidget(frame)
        self.ratio_box.setVisible(bool(bars))

    def _drill_row(self, *_):
        try:
            i = self.table.currentRow()
            if not (0 <= i < len(self._rows)):
                return
            # في لوحة أرقام التشغيل لا كشفَ حسابٍ يُفتح — النقر
            # المزدوج على الطقم يفتح تعديله.
            p = self.panels[min(self.current, len(self.panels) - 1)]
            if p.get("kind") == "stock":
                return self.edit_stock_item()
            if p.get("kind") == "scrap" and self._rows[i].get("karat"):
                return self._open_scrap_karat(self._rows[i]["karat"])
            code = self._rows[i].get("code")
            # 5.2.1: «ايطالي / نواعم» حسابٌ رسمي (1210) — يُفتح كشف حسابه
            # كأي حساب، لا نافذة كشفٍ منفصلة
            if code == dp.ITALIAN:
                code = dp.ITALIAN_ACC
            if code and self.on_drill_code:
                self.on_drill_code(code)
        except Exception:
            pass

    def _click_row(self, index):
        """نقرة على عيارٍ في لوحة الكسر ← كشف ذلك العيار وحده."""
        try:
            p = self.panels[min(self.current, len(self.panels) - 1)]
            i = index.row()
            if p.get("kind") != "scrap" or not (0 <= i < len(self._rows)):
                return
            k = self._rows[i].get("karat")
            if k:
                self._open_scrap_karat(k)
        except Exception as e:
            err(self, e)

    def _open_scrap_karat(self, karat):
        import time as _t
        # النقرة المزدوجة تبدأ بنقرةٍ مفردة — لا تُفتح النافذة مرتين
        now = _t.monotonic()
        if now - getattr(self, "_scrap_ts", 0.0) < 0.8:
            return None
        self._scrap_ts = now
        from ui.widgets.scrap_statement import ScrapKaratDialog
        p = self.panels[min(self.current, len(self.panels) - 1)]
        try:
            dlg = ScrapKaratDialog(self, karat, p.get("date_from") or None,
                                   p.get("date_to") or None)
        except Exception as e:
            err(self, e)
            return None
        dlg.exec_()
        self._scrap_ts = _t.monotonic()
        return dlg

    # ══════════ العرض ══════════
    def refresh(self):
        try:
            if not self.panels:
                self.panels = dp.load_panels()
                self._build_buttons()
            p = self.panels[min(self.current, len(self.panels) - 1)]
            # مزامنة حقول الفترة مع اللوحة الحالية بلا إطلاق حدث
            self._loading = True
            try:
                # الفترة باسمها تُحسب من جديد في كل فتح («هذا الشهر»
                # يبقى الشهرَ الجاري)
                pnl = dp.is_pnl(p)
                if pnl:
                    self._pnl_sync(p, self._pnl_apply(p))
                    k = dp.panel_period(p)
                else:
                    k = dp.apply_period(p)
                self.period.setCurrentIndex(
                    max(self.period.findData(k), 0))
                if p.get("date_from"):
                    self.d_from.setDate(QtCore.QDate.fromString(
                        p["date_from"], "yyyy-MM-dd"))
                if p.get("date_to"):
                    self.d_to.setDate(QtCore.QDate.fromString(
                        p["date_to"], "yyyy-MM-dd"))
                custom = k == "custom"
                self.d_from.setEnabled(custom)
                self.d_to.setEnabled(custom)
            finally:
                self._loading = False
            self._sync_tools()
            with db(readonly=True) as conn:
                if p.get("kind") == "scrap":
                    self._render_scrap(conn, p)
                elif p.get("kind") == "stock":
                    self._render_stock(conn, p)
                else:
                    self._render_accounts(conn, p)
                self._update_buttons(conn)
        except Exception as e:
            err(self, e)

    def _render_accounts(self, conn, p):
        d1 = p.get("date_from") or None
        d2 = p.get("date_to") or None
        if (self.compare.isChecked() and d1 and d2 and not dp.is_pnl(p)
                and p.get("kind") != "scrap"):
            return self._render_compare(conn, p, d1, d2)
        rows = dp.account_rows(conn, p["accounts"], d1, d2)
        self._rows = rows
        bars = dp.ratio_bars(rows, p.get("ratios") or [], p.get("unit"))
        # 4.91: «الأرباح والخسائر» بمنظور الربح — الربح موجب والخسارة
        # سالبةٌ حمراء (`dp.profit_view`)؛ وبقية اللوحات على طبيعتها
        pnl = dp.is_pnl(p)
        if pnl:
            rows, bars = dp.profit_view(rows), dp.profit_bars(bars)
        t = dp.totals(rows)
        money = _signed if pnl else (lambda v: _nf.f2(v))

        # ══ عمود النسبة ══
        # يظهر أول الأعمدة حين تُعرَّف نسبة واحدة على الأقل: النسبة
        # تُنسب لحسابها فتُقرأ بجواره مباشرةً.
        if bars:
            by_code = {}
            for b in bars:
                by_code.setdefault(b["second"], []).append(b)
            cols = ["النسبة"] + ACC_COLS_NOW()
            data = []
            for r in rows:
                bl = by_code.get(r["code"]) or []
                txt = "   ·   ".join(
                    f"{x['title']}: "
                    + ("—" if x["pct"] is None else f"{_nf.f2(x['pct'])}%")
                    for x in bl) or "—"
                data.append((txt, _acc_label(r),
                             money(kv.g(r['gold_balance'])),
                             money(r['cash_balance'])))
            # 5.2.5: لا «إجمالي نسب» — جمعُ نسبٍ مختلفة يتخطّى المئة بلا معنى
            data.append(("", "الإجمالي",
                         money(kv.g(t['gold_balance'])),
                         money(t['cash_balance'])))
            self._fill(cols, data, bold_last=True,
                       weights=[26, 34, 20, 20], red_neg=pnl)
        else:
            data = [(_acc_label(r),
                     money(kv.g(r['gold_balance'])),
                     money(r['cash_balance'])) for r in rows]
            data.append(("الإجمالي", money(kv.g(t['gold_balance'])),
                         money(t['cash_balance'])))
            self._fill(ACC_COLS_NOW(), data, bold_last=True,
                       weights=[46, 27, 27], red_neg=pnl)
        span = (f"   ({d1 or 'البداية'} → {d2 or 'الآن'})" if d1 or d2
                else "")
        self.tbl_title.setText(f"◄ {p['title']}{span}")
        self.totals.setText(
            f"الإجمالي — رصيد الذهب: {money(kv.g(t['gold_balance']))} "
            f"جم {kv.label()}"
            f"   ·   الرصيد النقدي: {money(t['cash_balance'])} ريال"
            + ("   ·   الموجب ربح والسالب خسارة" if pnl else "")
            + ("   ·   «ايطالي / نواعم» خارج الإجمالي (وزنه داخل الذهب"
               " المشغول) — انقر عليه مرتين لكشفه"
               if any(r.get("virtual") for r in rows) else ""))
        self._render_ratios(rows, p)      # الصفوف بإشارتها المعروضة

    def _render_compare(self, conn, p, d1, d2):
        """يعرض اللوحة نفسها مقارنةً بالفترة السابقة المساوية طولاً."""
        cmp_ = dp.compare_rows(conn, p["accounts"], d1, d2)
        rows = cmp_["rows"]
        self._rows = [{"code": r["code"]} for r in rows]
        t = dp.compare_totals(rows)

        def _pct(v):
            return "—" if v is None else f"{v:+,.1f}%"

        cols = ["الحساب",
                f"حركة الذهب ({kv.unit()})", "السابقة", "الفرق", "%",
                "حركة النقد (ريال)", "السابقة", "الفرق", "%"]
        data = []
        for r in rows:
            data.append((
                _acc_label(r),
                f"{_nf.f2(kv.g(r['gold']))}", f"{_nf.f2(kv.g(r['gold_prev']))}",
                f"{_nf.f2(kv.g(r['gold_diff']), sign=True)}", _pct(r["gold_pct"]),
                f"{_nf.f2(r['cash'])}", f"{_nf.f2(r['cash_prev'])}",
                f"{_nf.f2(r['cash_diff'], sign=True)}", _pct(r["cash_pct"])))
        data.append(("الإجمالي",
                     f"{_nf.f2(kv.g(t['gold']))}",
                     f"{_nf.f2(kv.g(t['gold_prev']))}",
                     f"{_nf.f2(kv.g(t['gold_diff']), sign=True)}", _pct(t["gold_pct"]),
                     f"{_nf.f2(t['cash'])}", f"{_nf.f2(t['cash_prev'])}",
                     f"{_nf.f2(t['cash_diff'], sign=True)}", _pct(t["cash_pct"])))
        self._fill(cols, data, bold_last=True,
                   weights=[22, 11, 10, 10, 8, 11, 10, 10, 8])
        self.tbl_title.setText(
            f"◄ {p['title']}   ({d1} → {d2})  مقابل  "
            f"({cmp_['from']} → {cmp_['to']})")
        self.totals.setText(
            f"الفترة الحالية — ذهب: {_nf.f2(kv.g(t['gold']))} {kv.unit()} "
            f"({_pct(t['gold_pct'])})   ·   "
            f"نقد: {_nf.f2(t['cash'])} ريال ({_pct(t['cash_pct'])})"
            f"   |   المقارنة على حجم الحركة لا على الرصيد")
        self._render_ratios([], p)

    def _render_scrap(self, conn, p):
        rows = dp.scrap_rows(conn)
        # كل عيار يفتح كشفه وحده؛ وصفّ الإجمالي كشفَ الصندوق كاملاً
        self._rows = [{"code": "1310", "karat": r["karat"]} for r in rows]
        self._rows.append({"code": "1310"})
        data = [(f"عيار {r['karat']}", f"{_nf.f2(r['actual'])}",
                 f"{_nf.f2(kv.g(r['eq18']))}") for r in rows]
        tot_a = round(sum(r["actual"] for r in rows), 3)
        tot_e = round(sum(r["eq18"] for r in rows), 3)
        data.append(("الإجمالي", _nf.f2(tot_a), _nf.f2(kv.g(tot_e))))
        self._fill(SCRAP_COLS_NOW(), data, bold_last=True,
                   weights=[34, 33, 33])
        self.tbl_title.setText(f"◄ {p['title']} — حساب 1310   ·   انقر على"
                               " العيار لعرض كشفه وحده")
        self.totals.setText(
            f"مجموع الأوزان الفعلية: {_nf.f2(tot_a)} جم   ·   "
            f"الرصيد المحاسبي بمكافئ {kv.active()}: "
            f"{_nf.f2(kv.g(tot_e))} جم")
        self._render_ratios([], p)

    # ══════════ لوحة أرقام التشغيل المتاحة ══════════
    def STOCK_COLS(self):
        u = kv.unit()
        return ["رقم التشغيل", "الموديل", f"الذهب ({u})",
                f"الفصوص ({u})", f"الأحجار ({u})",
                f"بعد الخصم ({u})", f"الوزن المقيد ({u})",
                f"الذهب القائم ({u})"]

    def _is_stock(self):
        try:
            p = self.panels[min(self.current, len(self.panels) - 1)]
            return p.get("kind") == "stock"
        except Exception:
            return False

    def _sync_tools(self):
        """كل لوحةٍ وأدواتُها: لا زرَّ لا معنى له في اللوحة المفتوحة."""
        on = self._is_stock()
        try:
            pnl = dp.is_pnl(self.panels[self.current])
        except (IndexError, AttributeError):
            pnl = False
        for w in getattr(self, "_stock_tools", []):
            w.setVisible(on)
        for w in getattr(self, "_acc_tools", []):
            w.setVisible(not on)
        # «الأرباح والخسائر» بفتراتها هي (4.92) بدل «المدة» والمقارنة
        for w in getattr(self, "_period_tools", []):
            w.setVisible(not on and not pnl)
        for w in getattr(self, "_pnl_tools", []):
            w.setVisible(pnl)
        if pnl and not (self._pnl_per == "month" and self._pnl_m >= 2):
            self.pnl_next.setVisible(False)
        # «من/إلى» تظهر للفترة المخصّصة وحدها — وغيرها تقول تواريخها
        # في عنوان الجدول
        custom = (getattr(self, "period", None) is not None
                  and self.period.currentData() == "custom")
        for w in getattr(self, "_date_tools", []):
            w.setVisible(not on and custom and not pnl)

    def _render_stock(self, conn, p):
        """كل ما يُباع اليوم: رقم التشغيل وموديله وأوزانه."""
        rows = dp.stock_rows(conn, self.stock_search.text()
                             if hasattr(self, "stock_search") else "")
        self._rows = rows
        t = dp.stock_totals(rows)
        g, f2 = kv.g, _nf.f2

        def line(r):
            return (r["wo"] + ("  (مجمّع)" if r["bulk"] else ""),
                    r["model"], f2(g(r["gold"])), f2(g(r["small"])),
                    f2(g(r["big"])), f2(g(r["after"])), f2(g(r["reg"])),
                    f2(g(r["standing"])))
        # نصوص الصفوف تُصاغ عند ملئها (آلاف الصفوف × ثمانية أرقام) لا كلها
        # قبل أن يظهر شيء
        data = _LazyRows(rows, line, (
            "الإجمالي", f"{t['models']} موديل",
            f2(g(t["gold"])), f2(g(t["small"])), f2(g(t["big"])),
            f2(g(t["after"])), f2(g(t["reg"])), f2(g(t["standing"]))))
        self._fill(self.STOCK_COLS(), data, bold_last=True,
                   weights=[16, 18, 11, 10, 10, 11, 12, 12])
        self.tbl_title.setText(
            f"◄ {p['title']} — {t['count']} رقم تشغيل متاح للبيع")
        self.totals.setText(
            f"المتاح للبيع: {t['count']} طقم في {t['models']} موديل"
            f"   ·   الوزن المقيد: {_nf.f2(kv.g(t['reg']))} {kv.unit()}"
            f"   ·   الذهب القائم: {_nf.f2(kv.g(t['standing']))} {kv.unit()}")
        self._render_ratios([], p)

    def _stock_row(self):
        i = self.table.currentRow()
        if not (0 <= i < len(self._rows)) or not isinstance(
                self._rows[i], dict) or "wo" not in self._rows[i]:
            raise ValueError("اختر رقم تشغيل من الجدول أولاً")
        return self._rows[i]

    def edit_stock_item(self, *_):
        """يعدّل موديل الطقم أو رقم تشغيله — وصفيٌّ بلا أثر مالي."""
        try:
            p = self.panels[min(self.current, len(self.panels) - 1)]
            if p.get("kind") != "stock":
                raise ValueError(
                    "هذا التعديل للوحة أرقام التشغيل المتاحة وحدها")
            r = self._stock_row()
            from models import models_catalog as mc
            with db(readonly=True) as conn:
                names = mc.model_names(conn)
            dlg = QtWidgets.QDialog(self)
            dlg.setWindowTitle(f"تعديل الطقم {r['wo']}")
            dlg.setMinimumWidth(430)
            e_wo = kit.LineEdit(r["wo"])
            cb = kit.ComboBox()
            cb.setEditable(True)
            cb.addItem("")
            for n in names:
                cb.addItem(n)
            cb.setCurrentText("" if r["model"] == "—" else r["model"])
            if r["bulk"]:
                e_wo.setEnabled(False)
                e_wo.setToolTip(f"الرقم {r['wo']} محجوز للرصيد التجميعي")
                from models.inventory import ITALIAN_MODEL
                cb.setCurrentText(ITALIAN_MODEL)
                cb.setEnabled(False)
                cb.setToolTip(f"موديل الرقم التجميعي «{ITALIAN_MODEL}» دائماً")
            note = QtWidgets.QLabel(
                "رقم التشغيل والموديل تصنيفٌ وصفي — تعديلهما لا يمسّ "
                "أي رصيد أو قيد. ويتبع الرقمَ الجديدُ بياناتُ القيود "
                "والفواتير فيبقى الطقم متتبَّعاً.")
            note.setObjectName("cardSub")
            note.setWordWrap(True)
            box = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.Ok
                | QtWidgets.QDialogButtonBox.Cancel)
            box.accepted.connect(dlg.accept)
            box.rejected.connect(dlg.reject)
            f = QtWidgets.QFormLayout()
            f.addRow("رقم التشغيل:", e_wo)
            f.addRow("الموديل:", cb)
            f.addRow(note)
            lay = QtWidgets.QVBoxLayout(dlg)
            lay.addLayout(f)
            lay.addWidget(box)
            if dlg.exec_() != QtWidgets.QDialog.Accepted:
                return
            new_wo = e_wo.text().strip()
            new_model = cb.currentText().strip()
            done = []
            with db() as conn:
                if new_model != ("" if r["model"] == "—" else r["model"]):
                    mc.assign_model(conn, r["id"], new_model,
                                    self.user["username"])
                    done.append(f"الموديل ← {new_model or '—'}")
                if not r["bulk"] and new_wo and new_wo != r["wo"]:
                    from models import inventory
                    res = inventory.rename_work_order(
                        conn, r["id"], new_wo, self.user["username"])
                    done.append(f"رقم التشغيل: {res['old']} ← {res['new']}")
            if not done:
                return
            self.refresh()
            info(self, "تم التعديل:\n• " + "\n• ".join(done)
                       + "\n\nلا أثر محاسبي — الأوزان والأرصدة كما هي.")
        except Exception as e:
            err(self, e)

    def delete_stock_item(self, *_):
        """يحذف رقم التشغيل المحدَّد — فيختفي من هنا ومن دليل الموديلات."""
        try:
            if not self._is_stock():
                raise ValueError("الحذف للوحة أرقام التشغيل المتاحة وحدها")
            r = self._stock_row()
        except Exception as e:
            err(self, e)
            return
        from ui.wo_delete import delete_wo
        if delete_wo(self, r["id"], self.user):
            self.refresh()

    def open_italian(self, p=None):
        """كشف «ايطالي / نواعم» بفترة اللوحة المعروضة."""
        try:
            from ui.italian_statement import ItalianStatementDialog
            p = p or self.panels[min(self.current, len(self.panels) - 1)]
            ItalianStatementDialog(self, p.get("date_from") or None,
                                   p.get("date_to") or None).exec_()
        except Exception as e:
            err(self, e)

    # ══ ملء الجدول (5.2.9) ══
    # لوحة أرقام التشغيل آلاف الصفوف: بناؤها دفعةً واحدة يوقف الواجهة حتى
    # ينتهي آخر صف. فأول الصفوف (وصفّ الإجمالي) يُبنى فوراً فتظهر اللوحة
    # مع النقرة، والباقي على دفعاتٍ صغيرة بين أحداث الواجهة — تبقى النقرات
    # والتمرير والكتابة تُعالَج أثناءها، وتُلغى الدفعات إن غُيّرت اللوحة.
    FILL_FIRST = 250
    FILL_CHUNK = 400

    def _fill(self, cols, data, bold_last=False, weights=None,
              red_neg=False):
        self._fill_gen = gen = getattr(self, "_fill_gen", 0) + 1
        t, n = self.table, len(data)
        chunked = n > self.FILL_FIRST + self.FILL_CHUNK
        first = self.FILL_FIRST if chunked else n
        t.setUpdatesEnabled(False)
        try:
            from ui.widgets.common import row_height
            vh = t.verticalHeader()
            vh.setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
            vh.setDefaultSectionSize(row_height(t, tight=n > 120))
            t.setColumnCount(len(cols))
            t.setHorizontalHeaderLabels(cols)
            if chunked:
                # ما لم يُملأ بعدُ فارغٌ — لا صفوف اللوحة السابقة
                t.setRowCount(0)
            t.setRowCount(n)
            self._fill_rows(data, 0, first, bold_last, red_neg)
            if chunked and bold_last:
                self._fill_rows(data, n - 1, n, bold_last, red_neg)
        finally:
            try:
                t.setUpdatesEnabled(True)
            except Exception:
                pass
        try:
            from ui.widgets.table_fit import fit_columns
            fit_columns(t, weights or [])
        except Exception:
            pass
        if chunked:
            end = n - 1 if bold_last else n
            QtCore.QTimer.singleShot(0, lambda: self._fill_more(
                gen, data, first, end, bold_last, red_neg))

    def _fill_more(self, gen, data, start, end, bold_last, red_neg):
        """الدفعة التالية من صفوف جدولٍ كبير — وتتوقّف إن أُعيد ملؤه."""
        if gen != getattr(self, "_fill_gen", 0) or start >= end:
            return
        try:
            t = self.table
            stop = min(end, start + self.FILL_CHUNK)
            t.setUpdatesEnabled(False)
            try:
                self._fill_rows(data, start, stop, bold_last, red_neg)
            finally:
                t.setUpdatesEnabled(True)
            if stop < end:
                QtCore.QTimer.singleShot(0, lambda: self._fill_more(
                    gen, data, stop, end, bold_last, red_neg))
        except RuntimeError:
            pass                      # الشاشة أُغلقت أثناء الملء

    def _fill_rows(self, data, start, stop, bold_last, red_neg):
        t, last_i = self.table, len(data) - 1
        right = QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
        center = QtCore.Qt.AlignCenter
        style_total = None
        for i in range(start, stop):
            row = data[i]
            total = bold_last and i == last_i
            if total and style_total is None:
                from ui.widgets.common import style_total_item as style_total
            for c, v in enumerate(row):
                it = QtWidgets.QTableWidgetItem(_nf.txt(v))
                it.setTextAlignment(right if c == 0 else center)
                if total:
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                    try:
                        style_total(it)
                    except Exception:
                        pass
                # 4.91: السالب أحمر في لوحة الأرباح والخسائر
                if red_neg and c and str(v).lstrip("\u200e")[:1] == "-":
                    it.setForeground(QtGui.QColor(
                        "#ff9a8f" if total else "#b3261e"))
                t.setItem(i, c, it)

    def _buttons_sig(self):
        """بصمة ما تُحسب منه أرقام الأزرار: البيانات والعيار واليوم
        وتعريف كل لوحة — لا تتغيّر بمجرد التنقّل بين اللوحات."""
        import datetime as _dt
        from database.database import data_token
        return (data_token(), kv.active(), _dt.date.today().isoformat(),
                self._pnl_per, self._pnl_m, len(self.buttons),
                repr([(p.get("title"), p.get("kind"), p.get("unit"),
                       tuple(p.get("accounts") or ()),
                       p.get("date_from") or "", p.get("date_to") or "",
                       p.get("start") or "")
                      for p in self.panels]))

    def _update_buttons(self, conn):
        """قيمة كل لوحة: رصيد حساباتها بالذهب.

        (5.2.9) كانت أرقام **كل** اللوحات تُعاد قراءتها من القاعدة مع كل
        نقرةٍ على أي لوحة — ومنها جمعُ كل أرقام التشغيل المتاحة. الآن
        تُحسب مرةً، ولا تُعاد إلا إن تغيّرت البيانات أو تعريف اللوحات."""
        try:
            sig = self._buttons_sig()
        except Exception:
            sig = None
        if sig is not None and sig == self.__dict__.get("_btn_sig"):
            return
        self._compute_buttons(conn)
        try:
            self._btn_sig = self._buttons_sig()
        except Exception:
            self._btn_sig = None

    def _compute_buttons(self, conn):
        for i, p in enumerate(self.panels):
            if i >= len(self.buttons):
                break
            try:
                if p.get("kind") == "scrap":
                    v = round(sum(x["eq18"] for x in dp.scrap_rows(conn)), 2)
                    self.buttons[i].set_value(f"{_nf.f2(kv.g(v))} جم")
                    continue
                if p.get("kind") == "stock":
                    t = dp.stock_summary(conn)
                    self.buttons[i].set_value(
                        f"{t['count']} طقم · {kv.g(t['reg']):,.0f} جم")
                    continue
                pnl = dp.is_pnl(p)
                if pnl:
                    rg = dp.pnl_range(self._pnl_per, self._pnl_m,
                                      dp.pnl_start(p))
                    p["date_from"] = rg["from"].isoformat()
                    p["date_to"] = rg["to"].isoformat()
                rows = dp.account_rows(
                    conn, p["accounts"],
                    p.get("date_from") or None,
                    p.get("date_to") or None)
                t = dp.totals(dp.profit_view(rows) if pnl else rows)
                money = _signed if pnl else (lambda v: _nf.f2(v))
                if (p.get("unit") or "gold") == "cash":
                    self.buttons[i].set_value(
                        f"{money(t['cash_balance'])} ريال")
                else:
                    self.buttons[i].set_value(
                        f"{money(kv.g(t['gold_balance']))} جم")
            except Exception:
                self.buttons[i].set_value("—")

    def print_panel(self):
        try:
            from services import print_manager
            p = self.panels[min(self.current, len(self.panels) - 1)]
            print_manager.preview_document(
                self, "dash_panel", 0, title=p["title"],
                kind=p.get("kind") or "accounts",
                codes=list(p.get("accounts") or []),
                ratios=list(p.get("ratios") or []),
                unit=p.get("unit") or None,
                date_from=p.get("date_from") or None,
                date_to=p.get("date_to") or None,
                search=(self.stock_search.text()
                        if p.get("kind") == "stock" else ""))
        except Exception as e:
            err(self, e)

    # التوافق مع بقية النظام
    def load_document(self, wo_id):
        try:
            from ui.wo_adjust_dialog import WOAdjustDialog
            dlg = WOAdjustDialog(self, wo_id, self.user)
            if dlg.exec_():
                self.refresh()
        except Exception as e:
            err(self, e)

    def load_supply(self, wo_id):
        self.load_document(wo_id)
