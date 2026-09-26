# -*- coding: utf-8 -*-
"""العملاء — المبيعات والمرتجع والسداد والباقي لكل عميل.

شاشةٌ تجيب عن سؤال الإدارة: **من يسدّد ومن يتأخّر؟**

┌ شريطٌ واحد: الفترة (أو منذ البداية) · بحث · إخفاء من لا حركة له
├ لوحاتٌ خمس: العملاء · المبيعات · المرتجع · السداد · الباقي
├ ثلاثة تبويبات:
│     الذهب  — الأرقام وزناً بعيار المصنع
│     النقد  — الأجور والضريبة بالريال
│     نظرةٌ عامة — الباقيان ذهباً ونقداً جنباً إلى جنب، وتقديرٌ لكلٍّ
└ سطرٌ هادئ أسفل الجدول يفصّل العميل المحدَّد

والعملاء المسجّلون يظهرون وحدهم، ويُضاف إليهم أي حسابٍ من الشجرة بزرّ
«إضافة حساب» — ويبقى مضافاً بين الجلسات. نقرةٌ مزدوجة تفتح كشف الحساب.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from models import customer_board as cb
from services import karat_view as kv
from ui import theme
from ui.widgets.common import (Card, ask, big_label, date_edit, dstr, err,
                               fill, info, load_pref, make_table, save_pref,
                               search_combo, tab_widget, title_label)
from ui.widgets.table_fit import fit_columns
from ui.widgets.table_tools import (TOTAL_ROLE, enhance, export_csv,
                                    total_row)

ACC_ROLE = QtCore.Qt.UserRole + 11          # معرّف الحساب في خلية الاسم

# أعمدة تبويبَي الذهب والنقد — بالترتيب الذي تُقرأ به المعادلة
SIDE_COLS = ["العميل", "رصيد سابق", "المبيعات", "المرتجع",
             "صافي المبيعات", "السداد", "حركات أخرى", "الباقي",
             "نسبة المرتجع", "نسبة السداد", "آخر سداد", "التقدير"]
SIDE_W = [18, 8, 9, 8, 9, 9, 8, 10, 8, 8, 9, 8]
C_OPEN, C_OTHER = 1, 6

OVER_COLS = ["العميل", "الجوال", "عدد الفواتير", "آخر بيع", "آخر سداد",
             "منذ آخر سداد", "الباقي ذهباً", "تقدير الذهب",
             "الباقي نقداً", "تقدير النقد"]
OVER_W = [20, 10, 7, 9, 9, 8, 10, 8, 10, 8]

HINTS = {
    "رصيد سابق": "الرصيد قبل بداية الفترة، ومعه الرصيد الافتتاحي للعميل: "
                 "بطاقته، وأرصدة أول المدة، والقيد اليومي الذي طرفه "
                 "المقابل «الأرصدة الافتتاحية»",
    "المبيعات": "كل ما قُيّد على العميل من فواتير البيع في الفترة",
    "المرتجع": "ما رجع من العميل بفواتير المرتجع",
    "صافي المبيعات": "رصيدٌ سابق + المبيعات − المرتجع: كل ما يُطالَب به "
                     "العميل",
    "السداد": "ما قبضه المصنع من العميل بسندات القبض (ومعه خصم السند)"
              " — والجدول مرتّبٌ بالأعلى سداداً",
    "حركات أخرى": "تثبيت، سند صرف، تسوية أو قيد يدوي — (+) تزيد ما "
                  "على العميل و(−) تنقصه",
    "الباقي": "رصيد الحساب في دفتر الأستاذ: موجبٌ على العميل، "
              "وسالبٌ له",
    "نسبة المرتجع": "المرتجع ÷ المبيعات",
    "نسبة السداد": "السداد ÷ صافي المبيعات (رصيد سابق + مبيعات − مرتجع)",
    "آخر سداد": "تاريخ آخر سند قبض حتى نهاية الفترة",
    "التقدير": "ممتاز ≥ ٩٠٪ · جيد ≥ ٧٠٪ · متابعة ≥ ٤٠٪ · متأخر أقل من ذلك",
}


def _pal():
    try:
        return theme.palette(theme.current_theme())
    except Exception:
        return theme.LIGHT


class CustomersScreen(QtWidgets.QWidget):
    def __init__(self, user, on_drill_account=None):
        super().__init__()
        self.user = user
        self.on_drill_account = on_drill_account
        self.res = None
        self._sorters = {}

        # ── الشريط ──
        self.since_start = QtWidgets.QCheckBox("منذ البداية")
        self.since_start.setToolTip(
            "كل حركة العميل منذ فتح حسابه — بلا «رصيد سابق»")
        self.d_from = date_edit()
        self.d_from.setDate(
            QtCore.QDate(QtCore.QDate.currentDate().year(), 1, 1))
        self.d_to = date_edit()
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("🔍 ابحث باسم العميل أو رقم حسابه…")
        self.search.setClearButtonEnabled(True)
        self.hide_idle = QtWidgets.QCheckBox("إخفاء من لا حركة له")
        btn_load = QtWidgets.QPushButton("↻ تحديث")
        btn_load.clicked.connect(self.refresh)

        self.since_start.setChecked(
            load_pref("customers.since_start", "1") == "1")
        self.hide_idle.setChecked(
            load_pref("customers.hide_idle", "1") == "1")
        self.d_from.setEnabled(not self.since_start.isChecked())
        self.since_start.toggled.connect(self._since_toggled)
        self.hide_idle.toggled.connect(self._hide_toggled)
        self.search.textChanged.connect(self._render)
        self.d_from.dateChanged.connect(self._dates_changed)
        self.d_to.dateChanged.connect(self._dates_changed)

        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(6)
        bar.addWidget(QtWidgets.QLabel("من:"))
        bar.addWidget(self.d_from)
        bar.addWidget(QtWidgets.QLabel("إلى:"))
        bar.addWidget(self.d_to)
        bar.addWidget(self.since_start)
        bar.addSpacing(10)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.hide_idle)
        bar.addWidget(btn_load)

        # ── اللوحات ──
        self.c_count = Card("العملاء", "")
        self.c_sales = Card("المبيعات", "")
        self.c_ret = Card("المرتجع", "")
        self.c_paid = Card("السداد", "")
        self.c_rem = Card("الباقي على العملاء", "", summary=True)
        cards = QtWidgets.QHBoxLayout()
        for c in (self.c_count, self.c_sales, self.c_ret, self.c_paid,
                  self.c_rem):
            cards.addWidget(c)

        # ── الجداول ──
        self.t_gold = self._table("customers_gold", SIDE_W)
        self.t_cash = self._table("customers_cash", SIDE_W)
        self.t_over = self._table("customers_over", OVER_W)
        self.tabs = tab_widget()
        self.tabs.addTab(self.t_gold, f"الذهب ({kv.unit()})")
        self.tabs.addTab(self.t_cash, "النقد (ريال)")
        self.tabs.addTab(self.t_over, "نظرة عامة")
        try:
            self.tabs.setCurrentIndex(int(load_pref("customers.tab", "0")))
        except Exception:
            pass
        self.tabs.currentChanged.connect(self._tab_changed)

        # ── الأزرار ──
        btn_add = QtWidgets.QPushButton("➕ إضافة حساب من الشجرة")
        btn_add.setToolTip(
            "يضيف أي حسابٍ من دليل الحسابات إلى اللوحة — ويبقى مضافاً")
        btn_add.clicked.connect(self.add_account)
        self.btn_remove = QtWidgets.QPushButton("✕ إخراج الحساب المضاف")
        self.btn_remove.setObjectName("ghost")
        self.btn_remove.setToolTip(
            "يُخرج الحساب المحدّد من اللوحة (للحسابات المضافة وحدها)")
        self.btn_remove.clicked.connect(self.remove_account)
        self.btn_remove.setEnabled(False)
        btn_ledger = QtWidgets.QPushButton("📄 كشف حساب العميل")
        btn_ledger.setObjectName("ghost")
        btn_ledger.clicked.connect(self.open_ledger)
        btn_print = QtWidgets.QPushButton("🖨 معاينة وطباعة")
        btn_print.clicked.connect(self.print_report)
        btn_export = QtWidgets.QPushButton("⬇ تصدير Excel")
        btn_export.setObjectName("ghost")
        btn_export.setToolTip("يحفظ التبويب المعروض ملفاً يفتحه Excel")
        btn_export.clicked.connect(self._export_current)
        tools = QtWidgets.QHBoxLayout()
        tools.addWidget(btn_add)
        tools.addWidget(self.btn_remove)
        tools.addStretch(1)
        tools.addWidget(btn_ledger)
        tools.addWidget(btn_export)
        tools.addWidget(btn_print)

        self.detail = big_label("اختر عميلاً لترى تفاصيله.")
        self.detail.setWordWrap(True)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(6)
        lay.addWidget(title_label("العملاء — المبيعات والسداد"))
        intro = QtWidgets.QLabel(
            "لكل عميلٍ ما اشترى وما أرجع وما سدّد وما بقي عليه — الذهب "
            "وحده والنقد وحده، ونسبتان تقولان من يسدّد ومن يتأخّر. "
            "نقرةٌ مزدوجة على عميل تفتح كشف حسابه.")
        intro.setObjectName("cardSub")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        lay.addLayout(bar)
        lay.addLayout(cards)
        lay.addWidget(self.tabs, 1)
        lay.addWidget(self.detail)
        lay.addLayout(tools)
        note = QtWidgets.QLabel(
            "صافي المبيعات = رصيدٌ سابق + المبيعات − المرتجع · الباقي = "
            "صافي المبيعات − السداد + حركاتٌ أخرى، وهو رصيد الحساب في دفتر "
            "الأستاذ نفسه. ونسبة السداد من صافي المبيعات؛ ونسبة المرتجع من "
            "المبيعات. الترتيب: الأعلى سداداً أولاً، ويتغيّر بالنقر على "
            "أي عمود.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)

    # ══════════ بناء ══════════
    def _table(self, key, weights):
        t = make_table()
        t.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        t.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        t.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        t.doubleClicked.connect(self.open_ledger)
        t.itemSelectionChanged.connect(self._selection_changed)
        t.currentCellChanged.connect(
            lambda *_: self._selection_changed())
        bundle = enhance(t, key=key, username=self.user.get("username"))
        self._sorters[id(t)] = bundle.get("sorter")
        t.setProperty("_weights", weights)
        return t

    def _mark_sorted(self, t, col):
        """سهم الفرز على عمود «السداد» — والنقرة التالية عليه تعكسه."""
        srt = self._sorters.get(id(t))
        if srt is not None:
            srt.col, srt.desc = col, True
        try:
            hh = t.horizontalHeader()
            hh.setSortIndicator(col, QtCore.Qt.DescendingOrder)
            hh.setSortIndicatorShown(col >= 0)
        except Exception:
            pass

    def _current_table(self):
        return self.tabs.currentWidget()

    # ══════════ أحداث الشريط ══════════
    def _since_toggled(self, on):
        self.d_from.setEnabled(not on)
        save_pref("customers.since_start", "1" if on else "0",
                  self.user.get("username"))
        self.refresh()

    def _hide_toggled(self, on):
        save_pref("customers.hide_idle", "1" if on else "0",
                  self.user.get("username"))
        self._render()

    def _dates_changed(self, *_):
        if self.res is not None:
            self.refresh()

    def _tab_changed(self, i):
        save_pref("customers.tab", str(i), self.user.get("username"))
        self._cards()
        self._selection_changed()

    # ══════════ البيانات ══════════
    def refresh(self):
        try:
            d_from = None if self.since_start.isChecked() else dstr(self.d_from)
            with db(readonly=True) as conn:
                self.res = cb.board(conn, d_from, dstr(self.d_to))
            self._render()
        except Exception as e:
            err(self, e)

    def _visible(self):
        if not self.res:
            return []
        rows = self.res["rows"]
        if self.hide_idle.isChecked():
            rows = [r for r in rows if r["active"]]
        q = self.search.text().strip()
        if q:
            from models import entities
            nq = entities.normalize_name(q)
            rows = [r for r in rows
                    if nq in entities.normalize_name(r["name"])
                    or q in str(r["code"])]
        return rows

    # ══════════ العرض ══════════
    def _render(self):
        rows = self._visible()
        self._fill_side(self.t_gold, rows, "gold")
        self._fill_side(self.t_cash, rows, "cash")
        self._fill_over(self.t_over, rows)
        self._cards()
        self._selection_changed()

    @staticmethod
    def _fmt(side, v):
        return (f"{kv.g(v):,.3f}" if side == "gold" else f"{v:,.2f}")

    @staticmethod
    def _pct(v):
        return "—" if v is None else f"{v:,.1f}%"

    def _name_item(self, t, i, r):
        it = t.item(i, 0)
        it.setData(ACC_ROLE, r["account_id"])
        it.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        tip = f"رقم الحساب: {r['code']}"
        if r["added"]:
            it.setForeground(QtGui.QBrush(QtGui.QColor(_pal()["goldDim"])))
            tip += "\nمضافٌ من الشجرة — يُخرَج بزرّ «إخراج الحساب المضاف»"
        it.setToolTip(tip)

    def _paint_grade(self, it, grade):
        p = _pal()
        col = {"ممتاز": p["green"], "مسدَّد": p["green"],
               "جيد": p["goldDim"], "متابعة": p["goldHi"],
               "متأخر": p["redText"], "لم يسدّد": p["redText"]}.get(grade)
        if col:
            it.setForeground(QtGui.QBrush(QtGui.QColor(col)))

    def _fill_side(self, t, rows, side):
        # الأعلى سداداً أولاً — بمبلغ عمود «السداد» لا بنسبته
        rows = cb.by_paid(rows, side)
        data = []
        for r in rows:
            x = r[side]
            data.append((
                r["name"], self._fmt(side, x["open"]),
                self._fmt(side, x["sales"]), self._fmt(side, x["returns"]),
                self._fmt(side, x["net"]), self._fmt(side, x["paid"]),
                self._fmt(side, x["other"]), self._fmt(side, x["remaining"]),
                self._pct(x["ret_pct"]), self._pct(x["paid_pct"]),
                r["last_paid"] or "—", x["grade"]))
        fill(t, SIDE_COLS, data)
        self._headers(t)
        p = _pal()
        bold = QtGui.QFont(t.font())
        bold.setBold(True)
        for i, r in enumerate(rows):
            x = r[side]
            self._name_item(t, i, r)
            for c in range(1, len(SIDE_COLS)):
                t.item(i, c).setTextAlignment(QtCore.Qt.AlignCenter)
            rem = t.item(i, 7)
            rem.setFont(bold)
            if x["remaining"] < -0.0005:
                rem.setForeground(QtGui.QBrush(QtGui.QColor(p["green"])))
                rem.setToolTip("دائن: للعميل على المصنع")
            if x["ret_pct"] is not None and x["ret_pct"] >= 20:
                t.item(i, 8).setForeground(
                    QtGui.QBrush(QtGui.QColor(p["redText"])))
            self._paint_grade(t.item(i, 11), x["grade"])
            self._paint_grade(t.item(i, 9), x["grade"])
        # صف الإجمالي من المعروض لا من الكل: يطابق ما أمام المستخدم
        tot = {k: sum(r[side][k] for r in rows) for k in cb.KINDS}
        s = cb._side(tot, side)
        fr = total_row(t, {
            0: f"الإجمالي ({len(rows)})", 1: self._fmt(side, s["open"]),
            2: self._fmt(side, s["sales"]), 3: self._fmt(side, s["returns"]),
            4: self._fmt(side, s["net"]), 5: self._fmt(side, s["paid"]),
            6: self._fmt(side, s["other"]),
            7: self._fmt(side, s["remaining"]),
            8: self._pct(s["ret_pct"]), 9: self._pct(s["paid_pct"])})
        self._paint_total(t, fr)
        # عمودا «رصيد سابق» و«حركات أخرى» يُخفيان إن خلَوا — فلا يزاحم
        # صفرٌ متكرّرٌ الأرقامَ التي فُتحت الشاشة لأجلها.
        t.setColumnHidden(C_OPEN, abs(s["open"]) < 0.0005 and not any(
            abs(r[side]["open"]) > 0.0005 for r in rows))
        t.setColumnHidden(C_OTHER, not any(
            abs(r[side]["other"]) > 0.0005 for r in rows))
        self._fit(t)
        self._mark_sorted(t, 5)

    def _fill_over(self, t, rows):
        rows = cb.by_paid(rows, "gold")
        data = []
        for r in rows:
            d = r["days_since_paid"]
            data.append((
                r["name"], r["phone"] or "—", f"{r['n_sales']:,}",
                r["last_sale"] or "—", r["last_paid"] or "—",
                "—" if d is None else f"{d:,} يوماً",
                self._fmt("gold", r["gold"]["remaining"]),
                r["gold"]["grade"],
                self._fmt("cash", r["cash"]["remaining"]),
                r["cash"]["grade"]))
        fill(t, OVER_COLS, data)
        p = _pal()
        for i, r in enumerate(rows):
            self._name_item(t, i, r)
            for c in range(1, len(OVER_COLS)):
                t.item(i, c).setTextAlignment(QtCore.Qt.AlignCenter)
            self._paint_grade(t.item(i, 7), r["gold"]["grade"])
            self._paint_grade(t.item(i, 9), r["cash"]["grade"])
            d = r["days_since_paid"]
            owes = (r["gold"]["remaining"] > 0.0005
                    or r["cash"]["remaining"] > 0.005)
            if owes and (d is None or d > 60):
                t.item(i, 5).setForeground(
                    QtGui.QBrush(QtGui.QColor(p["redText"])))
                t.item(i, 5).setToolTip("عليه رصيدٌ ولم يسدّد منذ أكثر من "
                                        "٦٠ يوماً")
        g = sum(r["gold"]["remaining"] for r in rows)
        c = sum(r["cash"]["remaining"] for r in rows)
        fr = total_row(t, {0: f"الإجمالي ({len(rows)})",
                           2: f"{sum(r['n_sales'] for r in rows):,}",
                           6: self._fmt("gold", g), 8: self._fmt("cash", c)})
        self._paint_total(t, fr)
        self._fit(t)
        self._mark_sorted(t, -1)

    def _paint_total(self, t, r):
        p = _pal()
        bg = QtGui.QBrush(QtGui.QColor(p.get("sumBg", p["goldSoft"])))
        ink = QtGui.QBrush(QtGui.QColor(p.get("sumInk", p["ink"])))
        for c in range(t.columnCount()):
            it = t.item(r, c)
            if it is None:
                continue
            it.setBackground(bg)
            it.setForeground(ink)
            it.setTextAlignment(QtCore.Qt.AlignCenter if c else
                                QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

    def _headers(self, t):
        for c in range(t.columnCount()):
            h = t.horizontalHeaderItem(c)
            if h is not None and h.text() in HINTS:
                h.setToolTip(HINTS[h.text()])

    def _fit(self, t):
        # الأعمدة المخفية لا تأخذ حصّة — المُحجِّم يتخطّاها
        fit_columns(t, list(t.property("_weights") or []))

    def _cards(self):
        if not self.res:
            return
        rows = self._visible()
        total = len(self.res["rows"])
        active = sum(1 for r in self.res["rows"] if r["active"])
        self.c_count.set_value(
            f"{len(rows):,}", f"ظاهرون · {active:,} بحركة من {total:,}")
        side = "cash" if self.tabs.currentIndex() == 1 else "gold"
        tot = {k: sum(r[side][k] for r in rows) for k in cb.KINDS}
        s = cb._side(tot, side)
        u = kv.unit() if side == "gold" else "ريال"
        tag = "ذهباً" if side == "gold" else "نقداً"
        self.c_sales.set_value(self._fmt(side, s["sales"]),
                               f"{u} · صافيها {self._fmt(side, s['net'])}")
        self.c_ret.set_value(self._fmt(side, s["returns"]),
                             f"{u} · {self._pct(s['ret_pct'])} من المبيعات")
        self.c_paid.set_value(self._fmt(side, s["paid"]),
                              f"{u} · {self._pct(s['paid_pct'])} من الصافي")
        owing = sum(1 for r in rows if r[side]["remaining"] > 0.0005)
        self.c_rem.set_value(self._fmt(side, s["remaining"]),
                             f"{u} {tag} · على {owing:,} عميلاً")

    # ══════════ التحديد ══════════
    def _selected(self):
        t = self._current_table()
        r = t.currentRow() if t is not None else -1
        if r < 0:
            return None
        it = t.item(r, 0)
        if it is None or it.data(TOTAL_ROLE):
            return None
        aid = it.data(ACC_ROLE)
        if aid is None or not self.res:
            return None
        return next((x for x in self.res["rows"]
                     if x["account_id"] == aid), None)

    def _selection_changed(self):
        r = self._selected()
        self.btn_remove.setEnabled(bool(r and r["added"]))
        if not r:
            self.detail.setText("اختر عميلاً لترى تفاصيله — ونقرةٌ مزدوجة "
                                "تفتح كشف حسابه.")
            return
        g, c = r["gold"], r["cash"]
        parts = [f"<b>{r['name']}</b>"]
        if r["n_sales"]:
            parts.append(
                f"{r['n_sales']:,} فاتورة · متوسطها "
                f"{kv.g(r['avg_sale_gold']):,.3f} {kv.unit()} و"
                f"{r['avg_sale_cash']:,.2f} ريال")
        if r["last_sale"]:
            parts.append(f"آخر بيع {r['last_sale']}")
        d = r["days_since_paid"]
        parts.append("لم يسدّد بعد" if d is None else
                     f"آخر سداد قبل {d:,} يوماً")
        lim = []
        if r["limit_gold"] > 0:
            use = max(g["remaining"], 0) / r["limit_gold"] * 100
            lim.append(f"سقف الذهب مستهلكٌ {use:,.0f}٪")
        if r["limit_cash"] > 0:
            use = max(c["remaining"], 0) / r["limit_cash"] * 100
            lim.append(f"سقف النقد مستهلكٌ {use:,.0f}٪")
        parts += lim
        if r["added"]:
            parts.append(f"حسابٌ مضاف ({r['code']})")
        self.detail.setText("  ·  ".join(parts))

    # ══════════ الإجراءات ══════════
    def open_ledger(self, *_):
        r = self._selected()
        if r and self.on_drill_account:
            self.on_drill_account(r["account_id"])

    def add_account(self):
        try:
            with db(readonly=True) as conn:
                taken = {x["account_id"] for x in (self.res or {}).get(
                    "rows", [])}
                accs = [dict(a) for a in conn.execute(
                    "SELECT id, code, name FROM accounts WHERE is_postable=1"
                    " ORDER BY code").fetchall() if a["id"] not in taken]
            dlg = QtWidgets.QDialog(self)
            dlg.setWindowTitle("إضافة حساب من الشجرة")
            dlg.setMinimumWidth(480)
            combo = search_combo("اكتب رقم الحساب أو اسمه…")
            for a in accs:
                combo.addItem(f"{a['code']} — {a['name']}", a["id"])
            combo.clear_selection()
            note = QtWidgets.QLabel(
                "يظهر الحساب سطراً في اللوحة بمبيعاته ومرتجعه وسداده "
                "كأي عميل، ويبقى مضافاً حتى تُخرجه.")
            note.setObjectName("cardSub")
            note.setWordWrap(True)
            box = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.Ok
                | QtWidgets.QDialogButtonBox.Cancel)
            box.button(QtWidgets.QDialogButtonBox.Ok).setText("إضافة")
            box.button(QtWidgets.QDialogButtonBox.Cancel).setText("إلغاء")
            box.accepted.connect(dlg.accept)
            box.rejected.connect(dlg.reject)
            f = QtWidgets.QFormLayout()
            f.addRow("الحساب:", combo)
            f.addRow(note)
            lay = QtWidgets.QVBoxLayout(dlg)
            lay.addLayout(f)
            lay.addWidget(box)
            if dlg.exec_() != QtWidgets.QDialog.Accepted:
                return
            aid = combo.currentData()
            if aid is None:
                raise ValueError("اختر حساباً من القائمة")
            with db() as conn:
                name = cb.add_account(conn, int(aid),
                                      self.user.get("username"))
            self.refresh()
            self._select_account(int(aid))
            info(self, f"أُضيف «{name}» إلى لوحة العملاء.")
        except Exception as e:
            err(self, e)

    def remove_account(self):
        try:
            r = self._selected()
            if not r or not r["added"]:
                raise ValueError("اختر حساباً مضافاً من الجدول")
            if not ask(self, f"إخراج «{r['name']}» من لوحة العملاء؟\n"
                             "الحساب نفسه وحركته لا يُمسّان."):
                return
            with db() as conn:
                cb.remove_account(conn, r["account_id"],
                                  self.user.get("username"))
            self.refresh()
        except Exception as e:
            err(self, e)

    def _select_account(self, aid):
        t = self._current_table()
        for i in range(t.rowCount()):
            it = t.item(i, 0)
            if it is not None and it.data(ACC_ROLE) == aid:
                t.selectRow(i)
                t.scrollToItem(it)
                return

    def _export_current(self):
        names = {0: "العملاء — الذهب", 1: "العملاء — النقد",
                 2: "العملاء — نظرة عامة"}
        export_csv(self, self._current_table(),
                   names.get(self.tabs.currentIndex(), "العملاء"))

    def _shown_ids(self, t):
        out = []
        for i in range(t.rowCount()):
            it = t.item(i, 0)
            if it is not None and not it.data(TOTAL_ROLE):
                aid = it.data(ACC_ROLE)
                if aid is not None:
                    out.append(aid)
        return out

    def print_report(self):
        try:
            from services import print_manager
            side = "cash" if self.tabs.currentIndex() == 1 else "gold"
            t = self.t_cash if side == "cash" else self.t_gold
            print_manager.preview_document(
                self, "customer_board", 0,
                date_from=(None if self.since_start.isChecked()
                           else dstr(self.d_from)),
                date_to=dstr(self.d_to), side=side,
                account_ids=self._shown_ids(t))
        except Exception as e:
            err(self, e)
