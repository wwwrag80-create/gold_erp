# -*- coding: utf-8 -*-
"""لوحة تحليل مبيعات العملاء — أداة رقابة إدارية.

أربع لوحات علوية (المبيعات · المرتجعات · المباع الفعلي · التحصيل)
لعميل مختار خلال فترة، وتحت كل لوحة جدولها التفصيلي المستقل (رقم
التشغيل والوزن المقيد) مع زر إخفاء/إظهار لطيّه أو فرده، وزر لطباعة
تقرير العميل.
"""
from PyQt5 import QtCore, QtWidgets

from database.database import db
from models import entities, sales_analytics as sa

from ui.widgets.common import (big_label, date_edit, dstr, err, fill, make_table,
                               reload_combo, search_combo, title_label)

PANELS = [("sales", "إجمالي المبيعات"), ("returns", "إجمالي المرتجعات"),
          ("net_sold", "إجمالي المباع الفعلي"), ("collection", "إجمالي التحصيل")]


class PanelColumn(QtWidgets.QFrame):
    """لوحة إحصائية يعلوها المربع الرئيسي وأسفلها جدولها التفصيلي."""

    def __init__(self, key, title):
        super().__init__()
        self.key = key

        lay = QtWidgets.QVBoxLayout(self)
        lay.setSpacing(4)

        box = QtWidgets.QFrame()
        box.setObjectName("statPanel")
        box.setFixedHeight(96)   # المربع الرئيسي ثابت لا يختفي أبداً
        bl = QtWidgets.QVBoxLayout(box)
        t = QtWidgets.QLabel(title)
        t.setObjectName("panelTitle")
        t.setAlignment(QtCore.Qt.AlignCenter)
        self.value = QtWidgets.QLabel("—")
        self.value.setObjectName("panelValue")
        self.value.setAlignment(QtCore.Qt.AlignCenter)
        bl.addWidget(t)
        bl.addWidget(self.value)
        lay.addWidget(box)

        self.toggle = QtWidgets.QPushButton("إخفاء الجدول")
        self.toggle.setObjectName("ghost")
        self.toggle.clicked.connect(self._toggle)
        lay.addWidget(self.toggle)

        self.table = make_table()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["رقم التشغيل", "الوزن المقيد"])
        lay.addWidget(self.table, 1)

    def _toggle(self):
        """يطوي/يفرد الجدول التفصيلي فقط — المربع الرئيسي (الوزن
        الإجمالي) يبقى ظاهراً وثابتاً دائماً."""
        vis = not self.table.isVisible()
        self.table.setVisible(vis)
        self.toggle.setText("إخفاء الجدول" if vis else "إظهار الجدول")

    def set_value(self, text):
        self.value.setText(text)

    def set_rows(self, rows, headers=None):
        fill(self.table, headers or ["رقم التشغيل", "الوزن المقيد"], rows)


class SalesAnalyticsScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.customer_id = None

        # شريط الرصيد المتبقي — بارز أسفل الشاشة
        self.remaining = big_label("اختر عميلاً لعرض رصيده")
        self.remaining.setObjectName("cardValue")

        self.customer = search_combo("اكتب اسم العميل…")
        self.customer.currentIndexChanged.connect(self.on_customer)
        self.d_from = date_edit()
        self.d_from.setDate(QtCore.QDate.currentDate().addMonths(-6))
        self.d_to = date_edit()
        btn_run = QtWidgets.QPushButton("تحديث اللوحات")
        btn_run.clicked.connect(self.reload_panels)
        btn_print = QtWidgets.QPushButton("🖨 طباعة تقرير العميل")
        btn_print.clicked.connect(self.print_report)

        filt = QtWidgets.QHBoxLayout()
        filt.addWidget(QtWidgets.QLabel("العميل:"))
        filt.addWidget(self.customer, 2)
        filt.addWidget(QtWidgets.QLabel("من:"))
        filt.addWidget(self.d_from)
        filt.addWidget(QtWidgets.QLabel("إلى:"))
        filt.addWidget(self.d_to)
        filt.addWidget(btn_run)
        filt.addWidget(btn_print)

        self.columns = {}
        cols = QtWidgets.QHBoxLayout()
        for key, title in PANELS:
            c = PanelColumn(key, title)
            self.columns[key] = c
            cols.addWidget(c)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("لوحة تحليل مبيعات العملاء — رقابة إدارية"))
        lay.addLayout(filt)
        lay.addLayout(cols, 1)
        lay.addWidget(self.remaining)

    def on_customer(self):
        self.customer_id = self.customer.currentData()
        self.reload_panels()

    def reload_panels(self):
        if self.customer_id is None:
            return
        try:
            with db() as conn:
                p = sa.all_panels(conn, self.customer_id,
                                  dstr(self.d_from), dstr(self.d_to))
                details = {k: sa.panel_details(conn, k, self.customer_id,
                                               dstr(self.d_from), dstr(self.d_to))
                           for k, _ in PANELS}
            self.columns["sales"].set_value(
                f"{p['sales']['weight']:,.2f} جم")
            self.columns["returns"].set_value(
                f"{p['returns']['weight']:,.2f} جم")
            self.columns["net_sold"].set_value(
                f"{p['net_sold']['weight']:,.2f} جم")
            coll = p["collection"]
            self.columns["collection"].set_value(
                f"ذهب {coll['gold']:,.2f} · نقد {coll['cash']:,.2f}")
            # الرصيد المتبقي = رصيد حساب العميل في الدليل
            with db() as conn:
                acc = conn.execute(
                    "SELECT account_id FROM entities WHERE id=?",
                    (self.customer_id,)).fetchone()
                g = c = 0.0
                if acc and acc["account_id"]:
                    r = conn.execute(
                        "SELECT COALESCE(SUM(l.gold_debit-l.gold_credit),0) g,"
                        " COALESCE(SUM(l.cash_debit-l.cash_credit),0) c"
                        " FROM journal_lines l"
                        " JOIN journal_entries e ON e.id=l.entry_id"
                        " WHERE e.is_deleted=0 AND l.account_id=?",
                        (acc["account_id"],)).fetchone()
                    g, c = round(r["g"], 2), round(r["c"], 2)
            self.remaining.setText(
                f"الرصيد المتبقي على العميل — ذهب: {g:,.2f} جم عيار 18   "
                f"|   نقد: {c:,.2f} ريال      "
                f"({'مدين/عليه' if (g > 0 or c > 0) else 'دائن/له'})")
            for key, _ in PANELS:
                if key == "collection":
                    # التحصيل: عمود المبلغ النقدي بجانب الذهب
                    rows = [(d["wo"], f"{d['weight']:,.2f}",
                             f"{d.get('cash', 0):,.2f}")
                            for d in details[key]]
                    self.columns[key].set_rows(
                        rows, ["رقم السند", "الذهب (جم)", "المبلغ (ريال)"])
                elif key == "net_sold":
                    # المباع الفعلي: المبيعات والمرتجعات والصافي
                    rows = [(d["wo"], f"{d.get('sold', 0):,.2f}",
                             f"{d.get('returned', 0):,.2f}",
                             f"{d['weight']:,.2f}")
                            for d in details[key]]
                    self.columns[key].set_rows(
                        rows, ["رقم التشغيل", "المباع", "المرتجع", "الصافي"])
                else:
                    rows = [(d["wo"], f"{d['weight']:,.2f}")
                            for d in details[key]]
                    self.columns[key].set_rows(rows)
        except Exception as e:
            err(self, e)

    def print_report(self):
        from services import print_manager
        if self.customer_id is None:
            err(self, ValueError("اختر العميل أولاً"))
            return
        try:
            from services import print_manager
            # القالب يحاكي الشاشة: اللوحات المخفية لا تُطبع، والجداول
            # المطوية تُطبع بإجمالياتها فقط بلا تفاصيل.
            print_manager.preview_document(
                self, "customer_analytics", self.customer_id,
                date_from=dstr(self.d_from), date_to=dstr(self.d_to),
                visible=self._visible_panels(),
                expanded=self._expanded_panels())
        except Exception as e:
            err(self, e)

    def _visible_panels(self):
        """اللوحات الظاهرة حالياً — ليطبعها القالب وحدها."""
        out = []
        for key, _t in PANELS:
            c = self.columns.get(key)
            try:
                if c is not None and c.isVisible():
                    out.append(key)
            except Exception:
                out.append(key)
        return out

    def _expanded_panels(self):
        """اللوحات التي جدولها مفرود — لتُطبع بتفاصيلها."""
        out = []
        for key, _t in PANELS:
            c = self.columns.get(key)
            try:
                if c is not None and c.table.isVisible():
                    out.append(key)
            except Exception:
                pass
        return out

    def refresh(self):
        with db() as conn:
            custs = [e for e in entities.list_entities(conn)
                     if e["entity_type"] == "customer" and not e["is_internal"]]
            reload_combo(self.customer, custs, lambda r: r["name"])
        if self.customer.count():
            self.customer_id = self.customer.currentData()
