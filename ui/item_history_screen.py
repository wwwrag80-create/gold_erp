# -*- coding: utf-8 -*-
"""شاشة حركة الطقم (Item History Movement) — رقابية.

بحث برقم التشغيل، تعرض جدولاً زمنياً لكل حركات الطقم (توريد، مبيعات،
مرتجع، تسوية) مع نوع الحركة والتاريخ والجهة المقابلة والأوزان التفصيلية
ونوع الطقم.
"""
from PyQt5 import QtCore, QtWidgets

from database.database import db
from services import karat_view as kv
from models import inventory

from ui.widgets.common import (big_label, date_edit, dstr, err, fill,
                               make_table, title_label)

COLS = ["نوع الحركة", "التاريخ", "الجهة المقابلة", "الذهب", "الفصوص",
        "الأحجار", "الوزن المقيد", "نوع الطقم"]


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

        self.toggle = QtWidgets.QPushButton("إخفاء الجدول")
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
            f"{kv.g(data['total_reg']):,.2f} {kv.unit()}")
        # لوحات الصادر تعرض «البائع» (من أخذ الطقم)، ولوحات الوارد
        # تعرض «المُرجِع» (من أعاده) — كلٌّ بما يناسب طبيعته.
        ret = "مرتجعة" in (self.title_text or "")
        key = "returner" if ret else "buyer"
        fill(self.table,
             ["رقم التشغيل", "المُرجِع" if ret else "البائع",
              "الوزن المقيد", "الوزن القائم"],
             [(i["wo"], i.get(key) or "—",
               f"{i['reg']:,.2f}", f"{i['standing']:,.2f}")
              for i in data["items"]])


class ItemHistoryScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user

        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("أدخل رقم التشغيل (مثال: 1)…")
        self.search.returnPressed.connect(self.load)
        btn = QtWidgets.QPushButton("بحث")
        btn.clicked.connect(self.load)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("رقم التشغيل:"))
        top.addWidget(self.search, 1)
        top.addWidget(btn)

        self.info = big_label()
        self.table = make_table()

        hist = QtWidgets.QWidget()
        hl = QtWidgets.QVBoxLayout(hist)
        hl.addLayout(top)
        hl.addWidget(self.info)
        hl.addWidget(self.table, 1)

        # ── تبويب تحليلات دوران المخزون ──
        self.d_from = date_edit()
        self.d_from.setDate(QtCore.QDate.currentDate().addYears(-1))
        self.d_to = date_edit()
        btn_run = QtWidgets.QPushButton("تحديث اللوحات")
        btn_run.clicked.connect(self.load_turnover)
        btn_print = QtWidgets.QPushButton("🖨 طباعة تقرير الدوران")
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

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label(
            "حركة الطقم — السجل الزمني وتحليلات الدوران"))
        lay.addWidget(tabs, 1)

    def _w(self, v):
        """وزن مخزَّن بمكافئ 18 ← معروضاً بعيار المصنع."""
        if v == "" or v is None:
            return ""
        try:
            return f"{kv.g(float(v)):,.2f}"
        except (TypeError, ValueError):
            return str(v)

    def load(self):
        no = self.search.text().strip()
        if not no:
            return
        try:
            with db(readonly=True) as conn:
                wo, rows = inventory.item_history(conn, no)
            self.info.setText(
                f"الطقم {wo['work_order_no']}  ·  النوع: {wo['item_type'] or '—'}"
                f"  ·  الوزن المقيد الحالي: "
                f"{kv.g(wo['registered_weight']):,.2f} {kv.unit()}"
                f"  ·  الحالة: {'بالمخزون' if wo['status'] == 'in_stock' else 'خارج/مباع'}")
            data = [(r["kind"], r["date"], r["party"], self._w(r["gold"]),
                     self._w(r["small"]), self._w(r["big"]), self._w(r["reg"]),
                     r["type"]) for r in rows]
            fill(self.table, COLS, data)
        except Exception as e:
            self.info.setText("")
            self.table.setRowCount(0)
            err(self, e)

    def load_turnover(self):
        """يحدّث اللوحات الأربع من التتبّع الفردي لأرقام التشغيل."""
        try:
            with db(readonly=True) as conn:
                data = inventory.turnover_all(
                    conn, dstr(self.d_from), dstr(self.d_to))
            for key, pnl in self.panels.items():
                pnl.fill_panel(data[key])
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

    def refresh(self):
        self.load_turnover()
