# -*- coding: utf-8 -*-
"""أعمار المخزون — كم من رأس المال راكد، ومنذ متى.

**السؤال**: «في المخزن ٨٤٠ طقماً وزنها ١٢ كيلو» رقمٌ لا يُتَّخذ عليه
قرار. الذي يُتَّخذ عليه قرارٌ هو **كم منها راقدٌ فوق التسعين يوماً**:
ذهبٌ مجمَّدٌ لا يدور، وأجرةٌ صُرفت على العامل ولم تُحصَّل من أحد.

┌ أربع لوحات: في المخزن · فوق ٩٠ يوماً · أجرة راكدة · متوسط المكث
├ **الفئات**: أقل من ٣٠ · ٦٠ · ٩٠ · أكثر — بالوزن والعدد والأجرة
├ **بالموديل**: أيّ موديلٍ يرقد، ونسبة ما تجاوز التسعين منه
└ **قطعة قطعة**: الأقدم أولاً، بتاريخ دخولها وعمرها

قراءةٌ محضة: لا تكتب رقماً ولا تُنشئ قيداً.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from models import stock_aging as sa
from models.aging import BUCKET_LABELS
from services import karat_view as kv
from ui.widgets.common import (Card, big_label, date_edit, dstr, err, fill,
                               ledger_rows, make_table, run_bg, search_combo,
                               tab_widget, title_label)
from ui.widgets.table_fit import fit_columns
from ui.widgets.table_tools import enhance as _enhance

ALL = "— كل الموديلات —"


class StockAgingScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.res = None

        self.as_of = date_edit()
        self.model = search_combo("كل الموديلات — أو اكتب موديلاً…")
        self.model.setMinimumWidth(240)
        self.model.setMaximumWidth(280)

        btn = QtWidgets.QPushButton("📦 إعداد التقرير")
        btn.clicked.connect(self.load)
        btn_print = QtWidgets.QPushButton("👁 معاينة وطباعة")
        btn_print.clicked.connect(self.print_report)
        btn_copy = QtWidgets.QPushButton("📋 نسخ الخلاصة")
        btn_copy.setObjectName("ghost")
        btn_copy.clicked.connect(self.copy_summary)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(QtWidgets.QLabel("حتى تاريخ:"))
        head.addWidget(self.as_of, 0)
        head.addWidget(QtWidgets.QLabel("الموديل:"))
        head.addWidget(self.model, 0)
        head.addWidget(btn, 0)
        head.addWidget(btn_print, 0)
        head.addWidget(btn_copy, 0)
        head.addStretch(1)

        self.c_stock = Card("في المخزن", "قطعٌ مفردة", summary=True)
        self.c_old = Card("فوق ٩٠ يوماً", "مالٌ راكد", summary=True)
        self.c_wage = Card("أجرة راكدة", "صُرفت ولم تُحصَّل")
        self.c_avg = Card("متوسط المكث", "مرجَّحاً بالوزن")
        tiles = QtWidgets.QHBoxLayout()
        for c in (self.c_stock, self.c_old, self.c_wage, self.c_avg):
            tiles.addWidget(c)

        self.verdict = big_label("اختر التاريخ ثم «إعداد التقرير».")
        # الخلاصة عدة جملٍ قد تطول — تُلفّ ولا تُقصّ
        self.verdict.setWordWrap(True)

        self.t_buckets = make_table()
        _enhance(self.t_buckets, key="stock_aging_buckets")
        self.t_models = make_table()
        _enhance(self.t_models, key="stock_aging_models")
        self.t_items = make_table()
        _enhance(self.t_items, key="stock_aging_items")

        self.tabs = tab_widget()
        self.tabs.addTab(self.t_buckets, "الفئات")
        self.tabs.addTab(self.t_models, "بالموديل")
        self.tabs.addTab(self.t_items, "قطعة قطعة")

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        lay.addWidget(title_label("أعمار المخزون — رأس المال الراكد"))
        intro = QtWidgets.QLabel(
            "الطقم الذي دخل أمس بضاعة، والذي دخل قبل سنةٍ مالٌ مدفون: "
            "ذهبُه لا يدور وأجرةُ تصنيعه صُرفت ولم تُحصَّل. هذا التقرير "
            "يوزّع المخزون على فئاته العمرية بالفئات نفسها المستعملة في "
            "أعمار الديون.")
        intro.setObjectName("cardSub")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        lay.addLayout(head)
        lay.addLayout(tiles)
        lay.addWidget(self.verdict)
        lay.addWidget(self.tabs, 1)
        note = QtWidgets.QLabel(
            "تاريخ الدخول من قيد التوريد لا من وقت كتابة السجل، فالدفعة "
            "التي تُسجَّل اليوم وقد ورَدَت الشهر الماضي عمرها من تاريخ "
            "قيدها. والرقم التجميعي ٠٠٠١ رصيدُ وزنٍ لا قطعة فلا عمر له — "
            "يُعرض في سطرٍ مستقل خارج الفئات.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)

        QtCore.QTimer.singleShot(0, self._load_models)

    # ─────────────────────────────── بيانات
    def _load_models(self):
        try:
            with db(readonly=True) as conn:
                rows = conn.execute(
                    "SELECT DISTINCT TRIM(model_no) m FROM work_orders"
                    " WHERE is_deleted=0 AND status='in_stock'"
                    "   AND TRIM(COALESCE(model_no,''))<>''"
                    " ORDER BY m").fetchall()
        except Exception as e:
            err(self, e)
            return
        self.model.blockSignals(True)
        self.model.clear()
        self.model.addItem(ALL, "")
        for r in rows:
            self.model.addItem(r["m"], r["m"])
        self.model.blockSignals(False)
        self.model.setCurrentIndex(0)

    def load(self):
        d = dstr(self.as_of)
        mdl = self.model.currentData() or None

        def _read():
            with db(readonly=True) as conn:
                return sa.report(conn, d, mdl)

        ok, res, ex = run_bg(_read, parent=self,
                             text="جارٍ حساب أعمار المخزون…",
                             stage="أعمار المخزون", timeout=90.0)
        if ex:
            err(self, ex)
            return
        if not ok:
            self.verdict.setText("تأخّر الحساب — أعد المحاولة.")
            return
        self.res = res
        self._render()

    # ─────────────────────────────── عرض
    def _render(self):
        r = self.res
        u = kv.unit()

        def w(v):
            return f"{kv.g(v):,.3f}"

        def m(v):
            return f"{v:,.2f}"

        t = r["total"]
        self.c_stock.set_value(f"{t['count']:,}",
                               f"قطعة · {w(t['weight'])} {u}")
        self.c_old.set_value(w(r["old_weight"]),
                             f"{u} · {r['old_pct']:,.1f}% من المخزون")
        self.c_wage.set_value(m(r["buckets"][-1]["idle_wage"]),
                              f"ريال فوق ٩٠ · {m(t['idle_wage'])} إجمالاً")
        self.c_avg.set_value(f"{r['avg_days']:,.1f}",
                             "يوماً — مرجّحاً بالوزن")
        self.verdict.setText("   ·   ".join(sa.verdict(r, w, m)))

        # ── الفئات ──
        # الترتيب يمنع الالتباس: الفئات، ثم مجموعُها، ثم ما لا عمر
        # له، ثم المخزون كلّه — فلا يبدو مجموعٌ وكأنه يشمل سطراً
        # فوقه وهو لا يشمله
        rows = [(b["label"], f"{b['count']:,}", w(b["weight"]),
                 f"{b['weight_pct']:,.1f}%", m(b["idle_wage"]))
                for b in r["buckets"]]
        marks = [len(rows)]
        rows.append(("إجمالي القطع المفردة", f"{t['count']:,}",
                     w(t["weight"]), "100%", m(t["idle_wage"])))
        if r["bulk"]["count"]:
            g = r["grand"]
            rows.append(("رصيد تجميعي — خارج الفئات (بلا عمر)",
                         f"{r['bulk']['count']:,}", w(r["bulk"]["weight"]),
                         "—", m(r["bulk"]["idle_wage"])))
            marks.append(len(rows))
            rows.append(("إجمالي المخزون", f"{g['count']:,}",
                         w(g["weight"]), "—", m(g["idle_wage"])))
        fill(self.t_buckets, ["الفئة العمرية", "عدد القطع",
                              f"الوزن ({u})", "النسبة",
                              "أجرة راكدة (ريال)"], rows)
        fit_columns(self.t_buckets, [28, 16, 20, 14, 22])
        ledger_rows(self.t_buckets, wrap_cols=(0,))
        self._mark(self.t_buckets, marks)

        # ── بالموديل ──
        # الفئات ثم مجموعها — ترتيب ورقة أعمار الديون نفسه، فلا
        # يتعلّم المستخدم قراءتين لجدولين متشابهين
        cols = ["الموديل", "العدد"] \
            + [f"{b} ({u})" for b in BUCKET_LABELS] \
            + [f"الوزن ({u})", "فوق ٩٠ %", "أقدم قطعة (يوم)",
               "أجرة راكدة (ريال)"]
        data = [tuple([mm["model"], f"{mm['count']:,}"]
                      + [w(b["weight"]) if b["weight"] else "—"
                         for b in mm["buckets"]]
                      + [w(mm["weight"]), f"{mm['old_pct']:,.1f}%",
                         f"{mm['oldest']:,}", m(mm["idle_wage"])])
                for mm in r["models"]]
        if data:
            data.append(tuple(
                ["الإجمالي", f"{t['count']:,}"]
                + [w(b["weight"]) for b in r["buckets"]]
                + [w(t["weight"]), f"{r['old_pct']:,.1f}%", "—",
                   m(t["idle_wage"])]))
        fill(self.t_models, cols, data)
        fit_columns(self.t_models, [20, 9, 12, 12, 12, 12, 13, 10, 12, 15])
        ledger_rows(self.t_models, wrap_cols=(0,))
        if data:
            self._mark(self.t_models, [len(data) - 1])

        # ── قطعة قطعة ──
        fill(self.t_items,
             ["رقم التشغيل", "الموديل", "النوع", "تاريخ الدخول",
              "العمر (يوم)", "الفئة", f"الوزن ({u})",
              "أجرة الجرام", "أجرة راكدة (ريال)"],
             [(x["wo_no"], x["model"], x["item_type"] or "—",
               x["in_date"], f"{x['days']:,}",
               BUCKET_LABELS[x["bucket"]], w(x["weight"]),
               m(x["wage_per_gram"]), m(x["idle_wage"]))
              for x in r["items"]])
        fit_columns(self.t_items, [14, 18, 10, 13, 10, 12, 12, 10, 14])
        ledger_rows(self.t_items, wrap_cols=(1,))
        self.tabs.setTabText(2, f"قطعة قطعة ({len(r['items'])})")

    def _mark(self, table, rows):
        from ui import theme
        pal = theme.palette(theme.current_theme())
        bg = QtGui.QColor(pal.get("sumBg", "#FDF3E2"))
        ink = QtGui.QColor(pal.get("sumInk", "#7A4F10"))
        for i in rows:
            for c in range(table.columnCount()):
                it = table.item(i, c)
                if it is None:
                    continue
                f = it.font()
                f.setBold(True)
                it.setFont(f)
                it.setBackground(bg)
                it.setForeground(ink)

    # ─────────────────────────────── مخرجات
    def print_report(self):
        if not self.res:
            err(self, "أعدّ التقرير أولاً")
            return
        from services import print_manager
        try:
            print_manager.preview_document(
                self, "stock_aging", 0, as_of=self.res["as_of"],
                model=self.res.get("model"), detail=True)
        except Exception as e:
            err(self, e)

    def copy_summary(self):
        if not self.res:
            return
        r = self.res
        u = kv.unit()

        def w(v):
            return f"{kv.g(v):,.3f}"

        def m(v):
            return f"{v:,.2f}"

        out = [f"أعمار المخزون — حتى {r['as_of']}"]
        if r.get("model"):
            out.append(f"الموديل: {r['model']}")
        out += ["", *sa.verdict(r, w, m), ""]
        for b in r["buckets"]:
            out.append(f"  {b['label']:<14} {b['count']:>6,} قطعة   "
                       f"{w(b['weight']):>12} {u}   "
                       f"{m(b['idle_wage']):>12} ريال")
        if r["bulk"]["count"]:
            out.append(f"  {'تجميعي (بلا عمر)':<14} "
                       f"{r['bulk']['count']:>6,} قطعة   "
                       f"{w(r['bulk']['weight']):>12} {u}")
        out += ["", f"  الإجمالي: {r['total']['count']:,} قطعة · "
                    f"{w(r['total']['weight'])} {u} · "
                    f"{m(r['total']['idle_wage'])} ريال أجرةً راكدة"]
        QtWidgets.QApplication.clipboard().setText("\n".join(out))
        self.verdict.setText("نُسخت الخلاصة — الصقها في أي رسالة.")

    def refresh(self):
        if self.res:
            self.load()
