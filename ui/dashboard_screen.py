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

from database.database import db
from models import dash_panels as dp
from services import karat_view as kv
from ui.widgets.common import (ask, big_label, date_edit, dstr, err,
                               info, make_table, search_combo,
                               title_label)

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

        btn_add_panel = QtWidgets.QPushButton("➕ لوحة رئيسية")
        btn_add_panel.setToolTip("ينشئ لوحة جديدة تجمع حسابات تختارها")
        btn_add_panel.clicked.connect(self.add_panel)
        btn_del_panel = QtWidgets.QPushButton("🗑 حذف اللوحة")
        btn_del_panel.clicked.connect(self.del_panel)
        btn_rename = QtWidgets.QPushButton("✎ تسمية اللوحة")
        btn_rename.clicked.connect(self.rename_panel)

        # هذه الأزرار تُعرض في الشريط العلوي بجوار «إغلاق الشاشة»
        btn_left = QtWidgets.QPushButton("◄")
        btn_left.setToolTip("تحريك اللوحة يميناً")
        btn_left.setMaximumWidth(36)
        btn_left.clicked.connect(lambda: self.move_panel(-1))
        btn_right = QtWidgets.QPushButton("►")
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
        btn_add_acc = QtWidgets.QPushButton("➕ إضافة حساب للجدول")
        btn_add_acc.setToolTip("يضيف حساباً من دليل الحسابات لهذه اللوحة")
        btn_add_acc.clicked.connect(self.add_account)
        btn_del_acc = QtWidgets.QPushButton("🗑 حذف الحساب المحدد")
        btn_del_acc.clicked.connect(self.del_account)
        btn_print = QtWidgets.QPushButton("🖨 طباعة الجدول")
        btn_print.setToolTip("قالب مطابق لما يظهر على الشاشة")
        btn_print.clicked.connect(self.print_panel)
        btn_ratio = QtWidgets.QPushButton("％ النسبة")
        btn_ratio.setToolTip("شريط نسبة أسفل الجدول: الثاني ÷ الأول")
        btn_ratio.clicked.connect(self.add_ratio)
        btn_up = QtWidgets.QPushButton("▲")
        btn_up.setToolTip("تحريك الصف لأعلى")
        btn_up.setMaximumWidth(38)
        btn_up.clicked.connect(lambda: self.move_row(-1))
        btn_dn = QtWidgets.QPushButton("▼")
        btn_dn.setToolTip("تحريك الصف لأسفل")
        btn_dn.setMaximumWidth(38)
        btn_dn.clicked.connect(lambda: self.move_row(1))
        btn_refresh = QtWidgets.QPushButton("↻ تحديث")
        btn_refresh.clicked.connect(self.refresh)

        tools = QtWidgets.QHBoxLayout()
        tools.setSpacing(6)
        tools.addWidget(self.tbl_title, 1)
        tools.addWidget(btn_up)
        tools.addWidget(btn_dn)
        tools.addWidget(btn_add_acc)
        tools.addWidget(btn_del_acc)
        tools.addWidget(btn_ratio)
        tools.addWidget(btn_print)
        tools.addWidget(btn_refresh)

        self.table = make_table()
        self.table.doubleClicked.connect(self._drill_row)
        self.totals = big_label()

        # نطاق التاريخ لهذه اللوحة — يُحفظ معها
        self.d_from = date_edit()
        self.d_from.setDate(
            QtCore.QDate(QtCore.QDate.currentDate().year(), 1, 1))
        self.d_to = date_edit()
        self.use_period = QtWidgets.QCheckBox("تحديد فترة")
        self.use_period.setToolTip(
            "بلا تحديد تُعرض كل الحركة منذ بداية النشاط")
        try:
            for w in (self.d_from, self.d_to):
                w.dateChanged.connect(self._period_changed)
            self.use_period.stateChanged.connect(self._period_changed)
        except Exception:
            pass          # بيئة بلا إشارات Qt حقيقية
        # مقارنة بالفترة السابقة المساوية طولاً — الرقم وحده لا يقول
        # إن كان النشاط يصعد أو يهبط.
        self.compare = QtWidgets.QCheckBox("مقارنة بالفترة السابقة")
        self.compare.setToolTip(
            "يضيف أعمدة الفترة السابقة (بنفس الطول) والفرق ونسبته.\n"
            "المقارنة على حجم الحركة لا على الرصيد التراكمي.")
        try:
            self.compare.stateChanged.connect(lambda *_: self.refresh())
        except Exception:
            pass
        per = QtWidgets.QHBoxLayout()
        per.setSpacing(6)
        per.addWidget(self.use_period)
        per.addWidget(QtWidgets.QLabel("من:"))
        per.addWidget(self.d_from)
        per.addWidget(QtWidgets.QLabel("إلى:"))
        per.addWidget(self.d_to)
        per.addWidget(self.compare)
        per.addStretch(1)
        self._period_row = per

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
        for i, p in enumerate(self.panels):
            b = PanelButton(p["title"])
            b.clicked.connect(lambda _=False, k=i: self.select(k))
            self.panel_row.addWidget(b)
            self.buttons.append(b)
        self._sync_checked()

    def _sync_checked(self):
        for i, b in enumerate(self.buttons):
            b.setChecked(i == self.current)

    def select(self, idx):
        if 0 <= idx < len(self.panels):
            self.current = idx
            self._sync_checked()
            self.refresh()

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
            e_name = QtWidgets.QLineEdit()
            e_name.setPlaceholderText("اسم اللوحة")
            cb_unit = QtWidgets.QComboBox()
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
            with db(readonly=True) as conn:
                accs = [dict(r) for r in conn.execute(
                    "SELECT code, name FROM accounts ORDER BY code")]
            # قائمة بحث حيّ: تقترح أقرب اسم مع أول حرف تكتبه
            dlg = QtWidgets.QDialog(self)
            dlg.setWindowTitle("إضافة حساب للجدول")
            dlg.setMinimumWidth(460)
            cb = search_combo("اكتب رقم الحساب أو اسمه…")
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
            if code in p["accounts"]:
                raise ValueError("الحساب مضاف مسبقاً في هذه اللوحة")
            p["accounts"].append(code)
            dp.save_panels(self.panels)
            self.refresh()
        except Exception as e:
            err(self, e)

    def del_account(self):
        try:
            p = self.panels[self.current]
            i = self.table.currentRow()
            if not (0 <= i < len(self._rows)):
                raise ValueError("اختر حساباً من الجدول أولاً")
            code = self._rows[i].get("code")
            if not code or code not in p["accounts"]:
                raise ValueError("هذا الصف لا يُحذف")
            p["accounts"].remove(code)
            dp.save_panels(self.panels)
            self.refresh()
        except Exception as e:
            err(self, e)

    def move_row(self, delta):
        """يحرّك الحساب المحدد في ترتيب الجدول."""
        try:
            p = self.panels[self.current]
            if p.get("kind") == "scrap":
                raise ValueError("ترتيب أعيرة صندوق الكسر ثابت")
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
            e_title = QtWidgets.QLineEdit()
            e_title.setPlaceholderText("اسم النسبة — مثل: نسبة التحصيل")
            cb1 = QtWidgets.QComboBox()
            cb2 = QtWidgets.QComboBox()
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
            cb_mode = QtWidgets.QComboBox()
            cb_mode.addItem("مئوية مباشرة — الثاني ÷ الأول", "direct")
            cb_mode.addItem("عكسية — الفرق ÷ الأول", "inverse")
            cb_mode.setToolTip(
                "مثال على 10 و 8:\n"
                "   مباشرة → 80%\n"
                "   عكسية  → 20%")
            cb_dim = QtWidgets.QComboBox()
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

    def _period_changed(self, *_):
        """يحفظ نطاق التاريخ مع اللوحة ويعيد العرض."""
        try:
            if getattr(self, "_loading", False):
                return
            p = self.panels[self.current]
            if self.use_period.isChecked():
                p["date_from"] = dstr(self.d_from)
                p["date_to"] = dstr(self.d_to)
            else:
                p["date_from"] = ""
                p["date_to"] = ""
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
        bars = dp.ratio_bars(rows, p.get("ratios") or [])
        for i, b in enumerate(bars):
            frame = QtWidgets.QFrame()
            frame.setObjectName("ratioBar")
            pct = ("—" if b["pct"] is None else f"{b['pct']:,.2f}%")
            lbl = QtWidgets.QLabel(
                f"{b['title']}:   {pct}      "
                f"({b['second_name']} {b['second_value']:,.2f}  ÷  "
                f"{b['first_name']} {b['first_value']:,.2f} "
                f"{b.get('unit', '')})")
            lbl.setWordWrap(True)
            x = QtWidgets.QPushButton("✕")
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
            code = self._rows[i].get("code")
            if code and self.on_drill_code:
                self.on_drill_code(code)
        except Exception:
            pass

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
                has = bool(p.get("date_from") or p.get("date_to"))
                self.use_period.setChecked(has)
                if p.get("date_from"):
                    self.d_from.setDate(QtCore.QDate.fromString(
                        p["date_from"], "yyyy-MM-dd"))
                if p.get("date_to"):
                    self.d_to.setDate(QtCore.QDate.fromString(
                        p["date_to"], "yyyy-MM-dd"))
                self.d_from.setEnabled(has)
                self.d_to.setEnabled(has)
            finally:
                self._loading = False
            with db(readonly=True) as conn:
                if p.get("kind") == "scrap":
                    self._render_scrap(conn, p)
                else:
                    self._render_accounts(conn, p)
                self._update_buttons(conn)
        except Exception as e:
            err(self, e)

    def _render_accounts(self, conn, p):
        d1 = p.get("date_from") or None
        d2 = p.get("date_to") or None
        if (self.compare.isChecked() and d1 and d2
                and p.get("kind") != "scrap"):
            return self._render_compare(conn, p, d1, d2)
        rows = dp.account_rows(conn, p["accounts"], d1, d2)
        self._rows = rows
        bars = dp.ratio_bars(rows, p.get("ratios") or [])
        t = dp.totals(rows)

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
                    + ("—" if x["pct"] is None else f"{x['pct']:,.1f}%")
                    for x in bl) or "—"
                data.append((txt, f"{r['code']} — {r['name']}",
                             f"{kv.g(r['gold_balance']):,.2f}",
                             f"{r['cash_balance']:,.2f}"))
            vals = [x["pct"] for x in bars if x["pct"] is not None]
            tot = (f"{sum(vals):,.1f}%" if vals else "—")
            data.append((f"إجمالي النسب: {tot}", "الإجمالي",
                         f"{kv.g(t['gold_balance']):,.2f}",
                         f"{t['cash_balance']:,.2f}"))
            self._fill(cols, data, bold_last=True,
                       weights=[26, 34, 20, 20])
        else:
            data = [(f"{r['code']} — {r['name']}",
                     f"{kv.g(r['gold_balance']):,.2f}",
                     f"{r['cash_balance']:,.2f}") for r in rows]
            data.append(("الإجمالي", f"{kv.g(t['gold_balance']):,.2f}",
                         f"{t['cash_balance']:,.2f}"))
            self._fill(ACC_COLS_NOW(), data, bold_last=True,
                       weights=[46, 27, 27])
        span = (f"   ({d1 or 'البداية'} → {d2 or 'الآن'})" if d1 or d2
                else "")
        self.tbl_title.setText(f"◄ {p['title']}{span}")
        self.totals.setText(
            f"الإجمالي — رصيد الذهب: {kv.g(t['gold_balance']):,.2f} "
            f"جم {kv.label()}"
            f"   ·   الرصيد النقدي: {t['cash_balance']:,.2f} ريال")
        self._render_ratios(rows, p)

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
                f"{r['code']} — {r['name']}",
                f"{kv.g(r['gold']):,.2f}", f"{kv.g(r['gold_prev']):,.2f}",
                f"{kv.g(r['gold_diff']):+,.2f}", _pct(r["gold_pct"]),
                f"{r['cash']:,.2f}", f"{r['cash_prev']:,.2f}",
                f"{r['cash_diff']:+,.2f}", _pct(r["cash_pct"])))
        data.append(("الإجمالي",
                     f"{kv.g(t['gold']):,.2f}",
                     f"{kv.g(t['gold_prev']):,.2f}",
                     f"{kv.g(t['gold_diff']):+,.2f}", _pct(t["gold_pct"]),
                     f"{t['cash']:,.2f}", f"{t['cash_prev']:,.2f}",
                     f"{t['cash_diff']:+,.2f}", _pct(t["cash_pct"])))
        self._fill(cols, data, bold_last=True,
                   weights=[22, 11, 10, 10, 8, 11, 10, 10, 8])
        self.tbl_title.setText(
            f"◄ {p['title']}   ({d1} → {d2})  مقابل  "
            f"({cmp_['from']} → {cmp_['to']})")
        self.totals.setText(
            f"الفترة الحالية — ذهب: {kv.g(t['gold']):,.2f} {kv.unit()} "
            f"({_pct(t['gold_pct'])})   ·   "
            f"نقد: {t['cash']:,.2f} ريال ({_pct(t['cash_pct'])})"
            f"   |   المقارنة على حجم الحركة لا على الرصيد")
        self._render_ratios([], p)

    def _render_scrap(self, conn, p):
        rows = dp.scrap_rows(conn)
        self._rows = [{"code": "1310"} for _ in rows]
        data = [(f"عيار {r['karat']}", f"{r['actual']:,.2f}",
                 f"{kv.g(r['eq18']):,.2f}") for r in rows]
        tot_a = round(sum(r["actual"] for r in rows), 3)
        tot_e = round(sum(r["eq18"] for r in rows), 3)
        data.append(("الإجمالي", f"{tot_a:,.2f}", f"{kv.g(tot_e):,.2f}"))
        self._fill(SCRAP_COLS_NOW(), data, bold_last=True,
                   weights=[34, 33, 33])
        self.tbl_title.setText(f"◄ {p['title']} — حساب 1310")
        self.totals.setText(
            f"مجموع الأوزان الفعلية: {tot_a:,.2f} جم   ·   "
            f"الرصيد المحاسبي بمكافئ {kv.active()}: "
            f"{kv.g(tot_e):,.2f} جم")
        self._render_ratios([], p)

    def _fill(self, cols, data, bold_last=False, weights=None):
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setColumnCount(len(cols))
            self.table.setHorizontalHeaderLabels(cols)
            self.table.setRowCount(len(data))
            for i, row in enumerate(data):
                for c, v in enumerate(row):
                    it = QtWidgets.QTableWidgetItem(str(v))
                    it.setTextAlignment(
                        QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
                        if c == 0 else QtCore.Qt.AlignCenter)
                    if bold_last and i == len(data) - 1:
                        f = it.font()
                        f.setBold(True)
                        it.setFont(f)
                        try:
                            it.setBackground(QtGui.QColor("#EFE9DC"))
                        except Exception:
                            pass
                    self.table.setItem(i, c, it)
        finally:
            try:
                self.table.setUpdatesEnabled(True)
            except Exception:
                pass
        try:
            from ui.widgets.table_fit import fit_columns
            fit_columns(self.table, weights or [])
        except Exception:
            pass

    def _update_buttons(self, conn):
        """قيمة كل لوحة: رصيد حساباتها بالذهب."""
        for i, p in enumerate(self.panels):
            if i >= len(self.buttons):
                break
            try:
                if p.get("kind") == "scrap":
                    v = round(sum(x["eq18"] for x in dp.scrap_rows(conn)), 2)
                    self.buttons[i].set_value(f"{kv.g(v):,.2f} جم")
                    continue
                t = dp.totals(dp.account_rows(
                    conn, p["accounts"],
                    p.get("date_from") or None,
                    p.get("date_to") or None))
                if (p.get("unit") or "gold") == "cash":
                    self.buttons[i].set_value(
                        f"{t['cash_balance']:,.2f} ريال")
                else:
                    self.buttons[i].set_value(
                        f"{kv.g(t['gold_balance']):,.2f} جم")
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
                date_from=p.get("date_from") or None,
                date_to=p.get("date_to") or None)
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
