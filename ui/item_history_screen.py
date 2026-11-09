# -*- coding: utf-8 -*-
"""شاشة حركة الطقم (Item History Movement) — رقابية.

بحث برقم التشغيل، تعرض جدولاً زمنياً لكل حركات الطقم (توريد، مبيعات،
مرتجع، تسوية) مع نوع الحركة والتاريخ والجهة المقابلة والأوزان التفصيلية
ونوع الطقم — وبطاقة تفاصيله (المقيد والقائم والذهب والفصوص والأحجار ومكانه
الآن). أو بحثٌ بالوزن المقيد أو القائم: الأطقم الأقرب إليه أولاً (5.2.4).
"""
from PyQt5 import QtCore, QtWidgets

from ui import kit

from database.database import db
from services import karat_view as kv
from models import inventory

from ui.widgets.common import (big_label, date_edit, dstr, err, fill,
                               make_table, title_label)
from services import numfmt as _nf

COLS = ["نوع الحركة", "التاريخ", "الجهة المقابلة", "الذهب", "الفصوص",
        "الأحجار", "الوزن المقيد", "في الخزنة بعدها", "نوع الطقم"]
# البحث بالوزن (5.2.4): الأطقم الأقرب إلى الوزن المكتوب
NEAR_COLS = ["رقم التشغيل", "الموديل", "الوزن المقيد", "الوزن القائم",
             "الذهب", "الفصوص", "الأحجار", "الفرق", "مكانه الآن"]
MODES = [("no", "رقم التشغيل"), ("reg", "الوزن المقيد"),
         ("standing", "الوزن القائم")]
# بطاقة تفاصيل الطقم: (المفتاح، العنوان)
CARD = [("reg", "الوزن المقيد"), ("standing", "الوزن القائم"),
        ("gold", "الذهب"), ("small", "الفصوص"), ("big", "الأحجار"),
        ("model_no", "الموديل"), ("where", "مكانه الآن")]


class TurnoverPanel(QtWidgets.QFrame):
    """لوحة تحليل دوران — تعرض أطقمها وعدد مرات حركتها."""

    """لوحة دوران: مربع بارز أعلاه وجدول تفصيلي أسفله."""

    def __init__(self, title, hint):
        self.title_text = title
        super().__init__()
        lay = QtWidgets.QVBoxLayout(self)
        lay.setSpacing(4)

        box = QtWidgets.QFrame()
        box.setObjectName("statPanel")
        box.setFixedHeight(104)
        bl = QtWidgets.QVBoxLayout(box)
        t = QtWidgets.QLabel(title)
        t.setObjectName("panelTitle")
        t.setAlignment(QtCore.Qt.AlignCenter)
        t.setWordWrap(True)
        self.value = QtWidgets.QLabel("—")
        self.value.setObjectName("panelValue")
        self.value.setAlignment(QtCore.Qt.AlignCenter)
        self.sub = QtWidgets.QLabel(hint)
        self.sub.setObjectName("panelSub")
        self.sub.setAlignment(QtCore.Qt.AlignCenter)
        self.sub.setWordWrap(True)
        bl.addWidget(t)
        bl.addWidget(self.value)
        bl.addWidget(self.sub)
        lay.addWidget(box)

        self.toggle = kit.PushButton("إخفاء الجدول")
        self.toggle.setObjectName("ghost")
        self.toggle.clicked.connect(self._toggle)
        lay.addWidget(self.toggle)

        self.table = make_table()
        lay.addWidget(self.table, 1)

    def _toggle(self):
        vis = not self.table.isVisible()
        self.table.setVisible(vis)
        self.toggle.setText("إخفاء الجدول" if vis else "إظهار الجدول")

    def fill_panel(self, data):
        self.value.setText(
            f"{data['count']} طقم  ·  "
            f"{_nf.f2(kv.g(data['total_reg']))} {kv.unit()}")
        # لوحات الصادر تعرض «البائع» (من أخذ الطقم)، ولوحات الوارد
        # تعرض «المُرجِع» (من أعاده) — كلٌّ بما يناسب طبيعته.
        ret = "مرتجعة" in (self.title_text or "")
        key = "returner" if ret else "buyer"
        fill(self.table,
             ["رقم التشغيل", "المُرجِع" if ret else "البائع",
              "الوزن المقيد", "الوزن القائم"],
             [(i["wo"], i.get(key) or "—",
               f"{_nf.f2(kv.g(i['reg']))}", f"{_nf.f2(kv.g(i['standing']))}")
              for i in data["items"]])


class ItemHistoryScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user

        # نوع البحث (5.2.4): برقم التشغيل كالعادة، أو بالوزن المقيد أو
        # القائم — فتظهر أرقام التشغيل الأقرب إلى الوزن المكتوب
        self.mode = kit.ComboBox()
        for key, label in MODES:
            self.mode.addItem(label, key)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.search = kit.LineEdit()
        self.search.setPlaceholderText("أدخل رقم التشغيل (مثال: 1)…")
        self.search.returnPressed.connect(self.load)
        btn = kit.PushButton("بحث")
        btn.clicked.connect(self.load)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("البحث بـ:"))
        top.addWidget(self.mode)
        top.addWidget(self.search, 1)
        top.addWidget(btn)

        self.info = big_label()
        # بطاقة تفاصيل الطقم: أوزانه وذهبه وفصوصه وأحجاره ومكانه الآن
        self.card = QtWidgets.QFrame()
        self.card.setObjectName("card")
        cg = QtWidgets.QGridLayout(self.card)
        cg.setContentsMargins(10, 6, 10, 6)
        cg.setHorizontalSpacing(18)
        cg.setVerticalSpacing(2)
        self.card_vals = {}
        for c, (key, title) in enumerate(CARD):
            t = QtWidgets.QLabel(title)
            t.setObjectName("cardSub")
            v = QtWidgets.QLabel("—")
            v.setObjectName("big" if key != "where" else "")
            v.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            cg.addWidget(t, 0, c)
            cg.addWidget(v, 1, c)
            self.card_vals[key] = v
        cg.setColumnStretch(len(CARD) - 1, 1)
        self.card.hide()
        self.table = make_table()
        self.table.setProperty(
            "emptyText", "اكتب رقم التشغيل ثم اضغط «بحث» أو Enter — تظهر "
            "حركة الطقم كاملةً")
        self.table.cellDoubleClicked.connect(self._open_near)
        self._near = []

        hist = QtWidgets.QWidget()
        hl = QtWidgets.QVBoxLayout(hist)
        hl.addLayout(top)
        hl.addWidget(self.info)
        hl.addWidget(self.card)
        hl.addWidget(self.table, 1)

        # ── تبويب تحليلات دوران المخزون ──
        self.d_from = date_edit()
        self.d_from.setDate(QtCore.QDate.currentDate().addYears(-1))
        self.d_to = date_edit()
        btn_run = kit.PushButton("تحديث اللوحات")
        btn_run.clicked.connect(self.load_turnover)
        btn_print = kit.PushButton("🖨 طباعة تقرير الدوران")
        btn_print.clicked.connect(self.print_turnover)
        filt = QtWidgets.QHBoxLayout()
        filt.addWidget(QtWidgets.QLabel("من:"))
        filt.addWidget(self.d_from)
        filt.addWidget(QtWidgets.QLabel("إلى:"))
        filt.addWidget(self.d_to)
        filt.addWidget(btn_run)
        filt.addWidget(btn_print)
        filt.addStretch(1)

        # ست لوحات في شبكة **لوحتين بكل سطر** — فيتسع جدول كل لوحة
        # لعرض تفاصيلها بدل انكماشها إلى عمود ضيق.
        self.panels = {}
        sec1 = QtWidgets.QGroupBox("القسم الأول — الأطقم المباعة (الصادر)")
        g1 = QtWidgets.QGridLayout(sec1)
        g1.setHorizontalSpacing(8)
        g1.setVerticalSpacing(8)
        sec2 = QtWidgets.QGroupBox(
            "القسم الثاني — المرتجعة والمخزون المتاح (الوارد)")
        g2 = QtWidgets.QGridLayout(sec2)
        g2.setHorizontalSpacing(8)
        g2.setVerticalSpacing(8)

        OUT_KEYS = ("first_sale", "resold_few", "resold_many")
        i_out = i_in = 0
        for key, title, hint in inventory.TURNOVER_PANELS:
            pnl = TurnoverPanel(title, hint)
            self.panels[key] = pnl
            if key in OUT_KEYS:
                g1.addWidget(pnl, i_out // 2, i_out % 2)
                i_out += 1
            else:
                g2.addWidget(pnl, i_in // 2, i_in % 2)
                i_in += 1
        for g in (g1, g2):
            g.setColumnStretch(0, 1)
            g.setColumnStretch(1, 1)

        turn = QtWidgets.QWidget()
        tl = QtWidgets.QVBoxLayout(turn)
        tl.addLayout(filt)
        tl.addWidget(sec1, 1)
        tl.addWidget(sec2, 1)

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(hist, "سجل حركة الطقم")
        tabs.addTab(turn, "تحليلات دوران المخزون")
        # لوحات الدوران آلاف الأسطر — تُقرأ حين يُفتح تبويبها لا مع فتح
        # الشاشة (4.80: كانت نصف ثانيةٍ تُدفع قبل ظهور الشاشة كل مرة)
        self.tabs = tabs
        self._turn_stale = True
        tabs.currentChanged.connect(self._tab_changed)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label(
            "حركة الطقم — السجل الزمني وتحليلات الدوران"))
        lay.addWidget(tabs, 1)

    def _w(self, v):
        """وزن مخزَّن بمكافئ 18 ← معروضاً بعيار المصنع."""
        if v == "" or v is None:
            return ""
        try:
            return _nf.f2(kv.g(float(v)))
        except (TypeError, ValueError):
            return str(v)

    def open_for_wo(self, wo_no):
        """يفتح تاريخ رقم تشغيلٍ بعينه — من شريط الأوامر الموحّد."""
        self.mode.setCurrentIndex(0)
        self.search.setText(str(wo_no or "").strip())
        self.load()

    def _mode_changed(self, _i=0):
        key = self.mode.currentData()
        self.search.setPlaceholderText(
            "أدخل رقم التشغيل (مثال: 1)…" if key == "no" else
            f"أدخل {self.mode.currentText()} ({kv.unit()}) — تظهر الأطقم"
            " الأقرب إليه…")
        self.search.setFocus()

    def _fill_card(self, d):
        """بطاقة التفاصيل من `models.set_lookup.details`."""
        for key, v in self.card_vals.items():
            if key == "where":
                w = d["where"]
                txt = w["label"]
                if w.get("invoice_no"):
                    txt += f" · {w['invoice_no']}"
                v.setText(txt)
            elif key == "model_no":
                v.setText(d["model_no"] or "—")
            else:
                v.setText(f"{_nf.f2(kv.g(d[key]))}")
        self.card.show()

    def load(self):
        if self.mode.currentData() != "no":
            return self.load_near()
        no = self.search.text().strip()
        if not no:
            return
        try:
            with db(readonly=True) as conn:
                wo, rows = inventory.item_history(conn, no)
                st = None
                if not wo["is_bulk"]:
                    from models import wo_moves
                    st = wo_moves.state(conn, wo)
                from models import set_lookup
                det = set_lookup.details(conn, wo)
            self._near = []
            self._fill_card(det)
            where = ""
            if st is not None:
                # 4.82: كم منه في الخزنة وكم عند الجهات — بيعُ جزءٍ يُرى
                where = (f"  ·  في الخزنة {_nf.f2(kv.g(st['rem']))} · عند الجهات"
                         f" {_nf.f2(kv.g(st['out']))} {kv.unit()}")
            self.info.setText(
                f"الطقم {wo['work_order_no']}  ·  النوع: {wo['item_type'] or '—'}"
                f"  ·  الوزن المقيد: "
                f"{_nf.f2(kv.g(wo['registered_weight']))} {kv.unit()}"
                f"  ·  الحالة: {'بالمخزون' if wo['status'] == 'in_stock' else 'خارج/مباع'}"
                + where)
            # 4.85: رقم الفاتورة بجانب الجهة، والحركة التي لا تسمح بها
            # حالتها مُعلَّمة — رسالة الرفض تُحيل إليها بأرقام فواتيرها
            data = [(r["kind"] + (" ⚠ غير منتظمة" if r.get("bad") else ""),
                     r["date"],
                     r["party"] + (f" · {r['inv']}" if r.get("inv") else ""),
                     self._w(r["gold"]),
                     self._w(r["small"]), self._w(r["big"]), self._w(r["reg"]),
                     self._w(r.get("left", "")), r["type"]) for r in rows]
            fill(self.table, COLS, data)
        except Exception as e:
            self.info.setText("")
            self.card.hide()
            self.table.setRowCount(0)
            err(self, e)

    def load_near(self):
        """الأطقم الأقرب إلى الوزن المكتوب — الأقرب أولاً. نقرةٌ مزدوجة
        على طقمٍ تفتح حركته."""
        txt = self.search.text().strip().replace("٫", ".").replace(",", ".")
        if not txt:
            return
        try:
            v = float(txt.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩",
                                                  "0123456789")))
        except ValueError:
            err(self, ValueError("اكتب الوزن رقماً (مثال: 12.5)"))
            return
        try:
            from models import set_lookup
            with db(readonly=True) as conn:
                rows = set_lookup.near_weight(
                    conn, kv.store(v), self.mode.currentData(), limit=40)
            self._near = [r["work_order_no"] for r in rows]
            self.card.hide()
            self.info.setText(
                f"أقرب {len(rows)} طقماً إلى {self.mode.currentText()} "
                f"{_nf.f2(v)} {kv.unit()} — الأقرب أولاً · نقرةٌ مزدوجة على"
                " طقمٍ تفتح حركته وتفاصيله")
            data = [(r["work_order_no"], r["model_no"] or "—",
                     self._w(r["reg"]), self._w(r["standing"]),
                     self._w(r["gold"]), self._w(r["small"]),
                     self._w(r["big"]), self._w(r["diff"]),
                     r["where"]["label"]) for r in rows]
            fill(self.table, NEAR_COLS, data)
            # «مكانه الآن» يأخذ باقي العرض فيُقرأ اسم الجهة كاملاً
            self.table.horizontalHeader().setSectionResizeMode(
                len(NEAR_COLS) - 1, QtWidgets.QHeaderView.Stretch)
        except Exception as e:
            self.info.setText("")
            self.table.setRowCount(0)
            err(self, e)

    def _open_near(self, row, _col=0):
        if not self._near or not (0 <= row < len(self._near)):
            return
        self.open_for_wo(self._near[row])

    def load_turnover(self):
        """يحدّث اللوحات الأربع من التتبّع الفردي لأرقام التشغيل."""
        try:
            with db(readonly=True) as conn:
                data = inventory.turnover_all(
                    conn, dstr(self.d_from), dstr(self.d_to))
            for key, pnl in self.panels.items():
                pnl.fill_panel(data[key])
            self._turn_stale = False
        except Exception as e:
            err(self, e)

    def print_turnover(self):
        from services import print_manager
        """تقرير رسمي بأربعة جداول مستقلة وإجمالياتها."""
        try:
                        print_manager.preview_document(
                self, "turnover", 0,
                date_from=dstr(self.d_from), date_to=dstr(self.d_to))
        except Exception as e:
            err(self, e)

    def _tab_changed(self, i):
        if i == 1 and self._turn_stale:
            self.load_turnover()

    def refresh(self):
        if self.tabs.currentIndex() == 1:
            self.load_turnover()
        else:
            self._turn_stale = True
