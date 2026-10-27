# -*- coding: utf-8 -*-
"""لوحة تحليل مبيعات العملاء — أداة رقابة إدارية.

أربع لوحات علوية (المبيعات · المرتجعات · المباع الفعلي · التحصيل)
لعميل مختار خلال فترة، وتحت كل لوحة جدولها التفصيلي المستقل (رقم
التشغيل والوزن المقيد) مع زر إخفاء/إظهار لطيّه أو فرده، وزر لطباعة
تقرير العميل. وزر «فرز» يعرض أرقام تشغيل اللوحات المختارة بلا تكرار
بأوزانها، والورقة تطبعها كما تُرى.
"""
from PyQt5 import QtCore, QtWidgets

from ui import kit

from database.database import db
from models import entities, sales_analytics as sa
from services import gold_math

from ui.widgets.common import (big_label, date_edit, dstr, err, fill,
                               karat_combo, load_pref, make_table,
                               reload_combo, save_pref, search_combo,
                               title_label)
from ui.widgets.table_tools import enhance as _enhance
from services import numfmt as _nf

PANELS = [("sales", "إجمالي المبيعات"), ("returns", "إجمالي المرتجعات"),
          ("net_sold", "إجمالي المباع الفعلي"), ("collection", "إجمالي التحصيل")]
MERGE_PREF = "sales_analytics_merged"
WO_UNIQUE = "رقم التشغيل (بلا تكرار)"


class _StayOpenMenu(QtWidgets.QMenu):
    """قائمةٌ تبقى مفتوحة عند تأشير خياراتها — تُختار عدة لوحات معاً."""

    def mouseReleaseEvent(self, e):
        a = self.activeAction()
        if a is not None and a.isEnabled() and a.isCheckable():
            a.trigger()
            return
        super().mouseReleaseEvent(e)


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
        self.title = t
        t.setObjectName("panelTitle")
        t.setAlignment(QtCore.Qt.AlignCenter)
        self.value = QtWidgets.QLabel("—")
        self.value.setObjectName("panelValue")
        self.value.setAlignment(QtCore.Qt.AlignCenter)
        bl.addWidget(t)
        bl.addWidget(self.value)
        lay.addWidget(box)

        self.toggle = kit.PushButton("إخفاء الجدول")
        self.toggle.setObjectName("ghost")
        self.toggle.clicked.connect(self._toggle)
        lay.addWidget(self.toggle)

        self.table = make_table()
        _enhance(self.table, key="sales_analytics")
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["رقم التشغيل", "الوزن المقيد"])
        lay.addWidget(self.table, 1)
        # حشوةٌ تظهر في «تقرير» وحده: اللوحات بلا جداول تبقى في أعلى
        # الشاشة لا في وسطها
        self.filler = QtWidgets.QWidget()
        self.filler.setVisible(False)
        lay.addWidget(self.filler, 1)

    def _toggle(self):
        """يطوي/يفرد الجدول التفصيلي فقط — المربع الرئيسي (الوزن
        الإجمالي) يبقى ظاهراً وثابتاً دائماً."""
        vis = not self.table.isVisible()
        self.table.setVisible(vis)
        self.toggle.setText("إخفاء الجدول" if vis else "إظهار الجدول")

    def set_value(self, text):
        self.value.setText(text)

    def set_title(self, text):
        self.title.setText(text)

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
        # العيارات: اللوحات والتقرير المطبوع يخرجان بالعيار المختار
        self.karat = karat_combo()
        self.karat.currentIndexChanged.connect(self._karat_changed)
        # «تحديث اللوحات» بخيارين (4.50): تفصيلي — اللوحات وتحتها أرقام
        # التشغيل وأوزانها كما كان · تقرير — اللوحات وحدها بالمعادلة:
        # المصروف − المرتجع = المباع الفعلي، بلا أرقام تشغيل
        self.mode = "detail"
        btn_run = kit.PushButton("تحديث اللوحات ▾")
        menu = QtWidgets.QMenu(btn_run)
        menu.addAction("تفصيلي — اللوحات وأرقام التشغيل والأوزان",
                       lambda: self.run_mode("detail"))
        menu.addAction("تقرير — المصروف والمرتجع والصافي بأرقامها فقط",
                       lambda: self.run_mode("report"))
        btn_run.setMenu(menu)
        self.btn_run = btn_run
        # «فرز» (4.72): لوحةٌ أو أكثر تُعرض أرقام تشغيلها بلا تكرار —
        # كل رقمٍ سطرٌ واحد بمجموع وزنه. الاختيار يُحفظ للمرة القادمة
        saved = str(load_pref(MERGE_PREF, "") or "")
        self.merged = {k for k in saved.split(",") if k in sa.MERGEABLE}
        self.btn_sort = kit.PushButton()
        sort_menu = _StayOpenMenu(self.btn_sort)
        self._sort_actions = {}
        titles = dict(PANELS)
        for key in sa.MERGEABLE:
            a = sort_menu.addAction(titles[key])
            a.setCheckable(True)
            a.setChecked(key in self.merged)
            a.toggled.connect(lambda on, k=key: self._toggle_merge(k, on))
            self._sort_actions[key] = a
        sort_menu.addSeparator()
        sort_menu.addAction("فرز كل اللوحات",
                            lambda: self.set_merged(sa.MERGEABLE))
        sort_menu.addAction("إلغاء الفرز", lambda: self.set_merged(()))
        self.btn_sort.setMenu(sort_menu)
        self._sort_label()
        btn_print = kit.PushButton("🖨 طباعة تقرير العميل")
        btn_print.clicked.connect(self.print_report)

        filt = QtWidgets.QHBoxLayout()
        filt.addWidget(QtWidgets.QLabel("العميل:"))
        filt.addWidget(self.customer, 2)
        filt.addWidget(QtWidgets.QLabel("من:"))
        filt.addWidget(self.d_from)
        filt.addWidget(QtWidgets.QLabel("إلى:"))
        filt.addWidget(self.d_to)
        filt.addWidget(QtWidgets.QLabel("العيارات:"))
        filt.addWidget(self.karat)
        filt.addWidget(btn_run)
        filt.addWidget(self.btn_sort)
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

    def run_mode(self, mode):
        """يبدّل بين التفصيلي والتقرير ثم يحدّث اللوحات."""
        self.mode = mode if mode in ("detail", "report") else "detail"
        report = self.mode == "report"
        for key, c in self.columns.items():
            # التقرير: المصروف والمرتجع والصافي وحدها — بلا جداول
            c.setVisible(not report or key != "collection")
            c.table.setVisible(not report)
            c.toggle.setVisible(not report)
            c.filler.setVisible(report)
            c.toggle.setText("إخفاء الجدول")
        self.columns["sales"].set_title(
            "المصروف (المبيعات)" if report else "إجمالي المبيعات")
        self.columns["net_sold"].set_title(
            "المباع الصافي" if report else "إجمالي المباع الفعلي")
        # التقرير بلا جداول أرقام تشغيل — فلا شيء يُفرز
        self.btn_sort.setEnabled(not report)
        self.reload_panels()

    # ══════════════════════════════════════════════════════════════
    #  الفرز: أرقام التشغيل بلا تكرار بأوزانها وحدها (4.72)
    # ══════════════════════════════════════════════════════════════

    def set_merged(self, keys):
        """يحدّد اللوحات المفروزة دفعةً واحدة (الكل · لا شيء · قائمة)."""
        self.merged = {k for k in keys if k in sa.MERGEABLE}
        for k, a in self._sort_actions.items():
            a.blockSignals(True)
            a.setChecked(k in self.merged)
            a.blockSignals(False)
        self._merge_changed()

    def _toggle_merge(self, key, on):
        (self.merged.add if on else self.merged.discard)(key)
        self._merge_changed()

    def _merge_changed(self):
        self._sort_label()
        u = self.user if isinstance(self.user, dict) else {}
        save_pref(MERGE_PREF, ",".join(k for k in sa.MERGEABLE
                                       if k in self.merged),
                  u.get("username"))
        self.reload_panels()

    def _sort_label(self):
        n = len(self.merged)
        self.btn_sort.setText(f"فرز ({n}) ▾" if n else "فرز ▾")
        titles = dict(PANELS)
        self.btn_sort.setToolTip(
            "أرقام التشغيل بلا تكرار في: "
            + "، ".join(titles[k] for k in sa.MERGEABLE if k in self.merged)
            if n else "اختر لوحةً أو أكثر لعرض أرقام تشغيلها بلا تكرار")

    def _merged_panels(self):
        """اللوحات المفروزة بترتيب الشاشة — ليطبعها القالب كما تُرى."""
        return [k for k in sa.MERGEABLE if k in self.merged]

    def on_customer(self):
        self.customer_id = self.customer.currentData()
        self.reload_panels()

    # ══════════════════════════════════════════════════════════════
    #  العيار: تحويل عرضٍ محض — القيد يبقى بمكافئ عيار 18
    # ══════════════════════════════════════════════════════════════

    def _k(self):
        try:
            return int(self.karat.currentData() or 18)
        except (TypeError, ValueError):
            return 18

    def _g(self, value):
        return gold_math.from_base_karat(value or 0, self._k())

    def _karat_changed(self):
        """يعيد بناء اللوحات بالعيار المختار.

        الشاشة تفتح على عيار المصنع، وهذه القائمة معاينة مؤقتة لهذا
        التقرير وحده.
        """
        self.reload_panels()

    def reload_panels(self):
        if self.customer_id is None:
            return
        try:
            with db(readonly=True) as conn:
                p = sa.all_panels(conn, self.customer_id,
                                  dstr(self.d_from), dstr(self.d_to))
                details = {k: sa.panel_details(conn, k, self.customer_id,
                                               dstr(self.d_from), dstr(self.d_to),
                                               merged=k in self.merged)
                           for k, _ in PANELS}
            k = self._k()
            if self.mode == "report":
                p["net_sold"] = sa.report_net(p)
            self.columns["sales"].set_value(
                f"{_nf.f2(self._g(p['sales']['weight']))} جم {k}")
            self.columns["returns"].set_value(
                f"{_nf.f2(self._g(p['returns']['weight']))} جم {k}")
            # الصافي ناتجاً مباشرةً (4.51) — في «تقرير» يُحسب: المصروف −
            # المرتجع، ويُعرض رقمه وحده بلا المعادلة
            self.columns["net_sold"].set_value(
                f"{_nf.f2(self._g(p['net_sold']['weight']))} جم {k}")
            coll = p["collection"]
            self.columns["collection"].set_value(
                f"ذهب {_nf.f2(self._g(coll['gold']))} · "
                f"نقد {_nf.f2(coll['cash'])}")
            # الرصيد المتبقي = رصيد حساب العميل في الدليل
            with db(readonly=True) as conn:
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
                f"الرصيد المتبقي على العميل — ذهب: {_nf.f2(self._g(g))} جم "
                f"عيار {k}   |   نقد: {_nf.f2(c)} ريال      "
                f"({'مدين/عليه' if (g > 0 or c > 0) else 'دائن/له'})")
            for key, _ in PANELS:
                if key == "collection":
                    # التحصيل: عمود المبلغ النقدي بجانب الذهب
                    rows = [(d["wo"], f"{_nf.f2(self._g(d['weight']))}",
                             f"{_nf.f2(d.get('cash', 0))}")
                            for d in details[key]]
                    self.columns[key].set_rows(
                        rows, ["رقم السند", f"الذهب (جم {k})",
                               "المبلغ (ريال)"])
                elif key in self.merged:
                    # مفروزة: رقم التشغيل مرةً واحدة ووزنه وحده
                    rows = [(d["wo"], f"{_nf.f2(self._g(d['weight']))}")
                            for d in details[key]]
                    self.columns[key].set_rows(
                        rows, [WO_UNIQUE,
                               f"الصافي (جم {k})" if key == "net_sold"
                               else f"الوزن المقيد (جم {k})"])
                elif key == "net_sold":
                    # المباع الفعلي: المبيعات والمرتجعات والصافي
                    rows = [(d["wo"], f"{_nf.f2(self._g(d.get('sold', 0)))}",
                             f"{_nf.f2(self._g(d.get('returned', 0)))}",
                             f"{_nf.f2(self._g(d['weight']))}")
                            for d in details[key]]
                    self.columns[key].set_rows(
                        rows, ["رقم التشغيل", "المباع", "المرتجع", "الصافي"])
                else:
                    rows = [(d["wo"], f"{_nf.f2(self._g(d['weight']))}")
                            for d in details[key]]
                    self.columns[key].set_rows(
                        rows, ["رقم التشغيل", f"الوزن المقيد (جم {k})"])
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
            # المطوية تُطبع بإجمالياتها فقط بلا تفاصيل، والمفروزة تُطبع
            # بأرقامها بلا تكرار — على ورقةٍ عمودية.
            print_manager.preview_document(
                self, "customer_analytics", self.customer_id,
                date_from=dstr(self.d_from), date_to=dstr(self.d_to),
                visible=self._visible_panels(),
                expanded=self._expanded_panels(),
                merged=self._merged_panels(),
                karat=self._k(), mode=self.mode)
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
        with db(readonly=True) as conn:
            custs = [e for e in entities.list_entities(conn)
                     if e["entity_type"] == "customer" and not e["is_internal"]]
            reload_combo(self.customer, custs, lambda r: r["name"])
        if self.customer.count():
            self.customer_id = self.customer.currentData()
