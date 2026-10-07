# -*- coding: utf-8 -*-
"""من عدّل ماذا بعد الترحيل — ومتى، وكم تغيّرت قيمته.

**السؤال**: التعديل مشروعٌ في هذا النظام — فالخطأ يقع، والصواب أن
يُصحَّح لا أن يُترك. لكن سجل التتبع يقول «عُدِّلت الفاتورة S-00042»
ولا يقول **كم تغيّرت**. والرقابة تبدأ من أن يكون التعديل مرئياً:
تعديلٌ يُرى يُسأل عنه، وتعديلٌ لا يُرى لا يُسأل.

┌ أربع لوحات: عدد التعديلات · ما غيّر قيمة · المتأخّر · أقصى تأخّر
├ **التعديلات**: مستنداً مستنداً، بقيمته قبل وبعد والفرق والتأخّر
├ **بالمستخدم**: من عدّل كم، وكم منها متأخّر
└ **بنوع المستند**: أيّ المستندات يُعدَّل أكثر

قراءةٌ محضة: لا تكتب رقماً ولا تُنشئ قيداً.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from models import doc_edits as de
from services import karat_view as kv
from ui.widgets.common import (Card, big_label, date_edit, dstr, err, fill,
                               ledger_rows, make_table, run_bg, tab_widget,
                               title_label)
from ui.widgets.table_fit import fit_columns
from ui.widgets.table_tools import enhance as _enhance


def snum(v, d=2):
    """السالب بين قوسين — لا بإشارةٍ تزيغ في نصٍّ عربي."""
    return f"({abs(v):,.{d}f})" if v < 0 else f"{v:,.{d}f}"


# أعمدة جدول التعديلات — والأخير زرُّ القالب قبل/بعد
ROW_COLS = ["وقت التعديل", "المستخدم", "المستند", "الطرف", "تاريخه",
            "التأخّر", "ما الذي تغيّر", "الوزن: قبل ← بعد", "فرق الوزن",
            "النقد: قبل ← بعد", "فرق النقد", "القالب"]
ROW_W = [9, 7, 12, 10, 8, 5, 13, 14, 8, 14, 7, 6]


class DocEditsScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.res = None
        self._rows = []

        # المدة تُختار باسمها فتُحسب تواريخها وتُعرض التعديلات فوراً
        from models import dash_panels as _dp
        self._dp = _dp
        self.period = QtWidgets.QComboBox()
        for k, lbl in _dp.PERIODS:
            self.period.addItem(lbl, k)
        self.period.setCurrentIndex(self.period.findData("month"))
        self.d_from = date_edit()
        self.d_to = date_edit()
        self._apply_period()
        self.kind = QtWidgets.QComboBox()
        self.kind.setMaximumWidth(190)
        self.kind.addItem("كل المستندات", "")
        for k, lbl in sorted(de.LABELS.items(), key=lambda x: x[1]):
            self.kind.addItem(lbl, k)
        self.late_only = QtWidgets.QCheckBox(
            f"المتأخّر فقط (بعد {de.LATE_DAYS} يوماً)")
        self.period.currentIndexChanged.connect(self._period_picked)
        for w in (self.kind,):
            w.currentIndexChanged.connect(lambda *_: self.load())
        self.late_only.toggled.connect(lambda *_: self.load())
        for d in (self.d_from, self.d_to):
            d.dateChanged.connect(self._date_typed)

        btn_cmp = QtWidgets.QPushButton("🧾 القالب قبل / بعد")
        btn_cmp.setObjectName("homeBtn")
        btn_cmp.setToolTip("المستند المحدَّد كما كان قبل التعديل وكما "
                           "صار بعده — أو نقرٌ مزدوج على السطر")
        btn_cmp.clicked.connect(lambda: self.open_compare())
        btn_print = QtWidgets.QPushButton("🖨 طباعة السجل")
        btn_print.clicked.connect(self.print_report)
        btn_copy = QtWidgets.QPushButton("📋 نسخ الخلاصة")
        btn_copy.setObjectName("ghost")
        btn_copy.clicked.connect(self.copy_summary)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(QtWidgets.QLabel("المدة:"))
        head.addWidget(self.period, 0)
        head.addWidget(QtWidgets.QLabel("من:"))
        head.addWidget(self.d_from, 0)
        head.addWidget(QtWidgets.QLabel("إلى:"))
        head.addWidget(self.d_to, 0)
        head.addWidget(QtWidgets.QLabel("النوع:"))
        head.addWidget(self.kind, 0)
        head.addWidget(self.late_only, 0)
        head.addStretch(1)
        head.addWidget(btn_cmp, 0)
        head.addWidget(btn_print, 0)
        head.addWidget(btn_copy, 0)

        self.c_count = Card("تعديلات", "على مستنداتٍ مُرحَّلة", summary=True)
        self.c_changed = Card("غيّرت القيمة", "لا مجرّد بيان", summary=True)
        self.c_late = Card("تعديلٌ متأخّر", f"بعد {de.LATE_DAYS} يوماً فأكثر")
        self.c_max = Card("أقصى تأخّر", "بين الترحيل والتعديل")
        tiles = QtWidgets.QHBoxLayout()
        for c in (self.c_count, self.c_changed, self.c_late, self.c_max):
            tiles.addWidget(c)

        self.verdict = QtWidgets.QLabel("")
        self.verdict.setObjectName("cardSub")
        self.verdict.setProperty("live", True)   # خلاصةٌ حيّة لا شرحٌ يُطوى
        self.verdict.setWordWrap(True)

        self.t_rows = make_table()
        _enhance(self.t_rows, key="doc_edits_rows2")
        self.t_rows.cellDoubleClicked.connect(
            lambda r, _c: self.open_compare(r))
        self.t_rows.cellClicked.connect(self._cell_clicked)
        self.t_users = make_table()
        _enhance(self.t_users, key="doc_edits_users")
        self.t_types = make_table()
        _enhance(self.t_types, key="doc_edits_types")

        self.tabs = tab_widget()
        self.tabs.addTab(self.t_rows, "التعديلات")
        self.tabs.addTab(self.t_users, "بالمستخدم")
        self.tabs.addTab(self.t_types, "بنوع المستند")

        # لا فقرات شرحٍ فوق الجدول ولا تحته: الأعمدة تقول نفسها،
        # والجدول أحوج إلى ارتفاع الشاشة
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        lay.addWidget(title_label("من عدّل ماذا بعد الترحيل"))
        lay.addLayout(head)
        lay.addLayout(tiles)
        lay.addWidget(self.verdict)
        lay.addWidget(self.tabs, 1)

    # ─────────────────────────────── الفترة
    def _apply_period(self):
        k = self.period.currentData()
        if k == "custom":
            return
        if k == "all":
            a, b = "2000-01-01", QtCore.QDate.currentDate().toString(
                "yyyy-MM-dd")
        else:
            a, b = self._dp.period_range(k)
        for d, v in ((self.d_from, a), (self.d_to, b)):
            d.blockSignals(True)
            d.setDate(QtCore.QDate.fromString(v, "yyyy-MM-dd"))
            d.blockSignals(False)

    def _period_picked(self, *_):
        if self.period.currentData() == "custom":
            return
        self._apply_period()
        self.load()

    def _date_typed(self, *_):
        """تاريخٌ كُتب بيدٍ يجعل المدة «مخصّصة» ويُعرض فوراً."""
        i = self.period.findData("custom")
        if i >= 0 and self.period.currentIndex() != i:
            self.period.blockSignals(True)
            self.period.setCurrentIndex(i)
            self.period.blockSignals(False)
        self.load()

    # ─────────────────────────────── بيانات
    def load(self):
        d1, d2 = dstr(self.d_from), dstr(self.d_to)
        tbl = self.kind.currentData() or None
        lag = de.LATE_DAYS if self.late_only.isChecked() else 0

        def _read():
            with db(readonly=True) as conn:
                rows = de.report(conn, d1, d2, source_table=tbl,
                                 min_lag=lag)
                return rows, de.summarize(conn, rows)

        ok, out, ex = run_bg(_read, parent=self,
                             text="جارٍ قراءة سجلّ التعديلات…",
                             stage="تعديلات المستندات", timeout=90.0)
        if ex:
            err(self, ex)
            return
        if not ok:
            self.verdict.setText("تأخّرت القراءة — ضيّق الفترة.")
            return
        self.res = {"rows": out[0], "sum": out[1],
                    "date_from": d1, "date_to": d2}
        self._render()

    # ─────────────────────────────── عرض
    def _render(self):
        rows, s = self.res["rows"], self.res["sum"]
        self._rows = rows
        t = s["total"]
        u = kv.unit()

        def w(v):
            return snum(kv.g(v), 3)

        def m(v):
            return snum(v, 2)

        self.c_count.set_value(f"{t['count']:,}",
                               f"في {len(s['users']):,} مستخدماً")
        self.c_changed.set_value(
            f"{t['changed']:,}",
            f"وزناً {w(t['d_gold'])} · نقداً {m(t['d_cash'])}")
        self.c_late.set_value(f"{t['late']:,}",
                              f"من {t['count']:,} تعديلاً")
        self.c_max.set_value(f"{t['max_lag']:,}", "يوماً")
        v = de.verdict(s, w, m)
        self.verdict.setText("   ·   ".join(v[:-1] if len(v) > 1 else v))

        # ── التعديلات ──
        def _pair(a, b, fmt):
            return f"{fmt(a)} ← {fmt(b)}"

        def _wt(v):
            return f"{kv.g(v):,.3f}"

        def _ms(v):
            return f"{v:,.2f}"

        cols = list(ROW_COLS)
        cols[8] = f"فرق الوزن ({u})"
        fill(self.t_rows, cols,
             [(r["edited_at"], r["user"],
               f"{r['label']} {r.get('doc_label') or r['doc_no']}",
               r.get("party") or "—", r["doc_date"],
               f"{r['lag']:,}" if r["lag"] is not None else "—",
               r.get("change") or "—",
               _pair(r["old_gold"], r["new_gold"], _wt)
               if (r["old_gold"] or r["new_gold"]) else "—",
               w(r["d_gold"]) if abs(r["d_gold"]) > 0.0005 else "—",
               _pair(r["old_cash"], r["new_cash"], _ms)
               if (r["old_cash"] or r["new_cash"]) else "—",
               m(r["d_cash"]) if abs(r["d_cash"]) > 0.005 else "—",
               "🧾 عرض") for r in rows])
        fit_columns(self.t_rows, ROW_W)
        ledger_rows(self.t_rows, wrap_cols=(2, 3, 6))
        self.tabs.setTabText(0, f"التعديلات ({len(rows)})")
        self._paint_rows(rows)

        # ── بالمستخدم ──
        data = [(x["name"], f"{x['count']:,}", f"{x['late']:,}",
                 w(x["d_gold"]), m(x["d_cash"])) for x in s["users"]]
        if data:
            data.append(("الإجمالي", f"{t['count']:,}", f"{t['late']:,}",
                         w(t["d_gold"]), m(t["d_cash"])))
        fill(self.t_users,
             ["المستخدم", "تعديلات", "منها متأخّر", f"صافي الوزن ({u})",
              "صافي النقد (ريال)"], data)
        fit_columns(self.t_users, [26, 14, 16, 22, 22])
        ledger_rows(self.t_users, wrap_cols=(0,))
        if data:
            self._mark(self.t_users, [len(data) - 1])

        # ── بنوع المستند ──
        data2 = [(x["label"], f"{x['count']:,}", w(x["d_gold"]),
                  m(x["d_cash"])) for x in s["types"]]
        if data2:
            data2.append(("الإجمالي", f"{t['count']:,}", w(t["d_gold"]),
                          m(t["d_cash"])))
        fill(self.t_types,
             ["نوع المستند", "تعديلات", f"صافي الوزن ({u})",
              "صافي النقد (ريال)"], data2)
        fit_columns(self.t_types, [34, 16, 25, 25])
        ledger_rows(self.t_types, wrap_cols=(0,))
        if data2:
            self._mark(self.t_types, [len(data2) - 1])

    def _paint_rows(self, rows):
        """الفرق يُلوَّن باتجاهه، وعمود القالب يبدو زرّاً يُنقر."""
        up, dn = QtGui.QColor("#2F7D3A"), QtGui.QColor("#B23A3A")
        link = QtGui.QColor("#8A6D1D")
        last = self.t_rows.columnCount() - 1
        for i, r in enumerate(rows):
            for c, v in ((8, r["d_gold"]), (10, r["d_cash"])):
                it = self.t_rows.item(i, c)
                if it is not None and abs(v) > 0.0005:
                    it.setForeground(up if v > 0 else dn)
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
            it = self.t_rows.item(i, last)
            if it is not None:
                it.setForeground(link)
                f = it.font()
                f.setBold(True)
                f.setUnderline(True)
                it.setFont(f)
                it.setToolTip("المستند قبل التعديل وبعده")
        self._paint_late(rows)

    def _cell_clicked(self, row, col):
        if col == self.t_rows.columnCount() - 1:
            self.open_compare(row)

    # ─────────────────────────────── قبل / بعد
    def open_compare(self, row=None):
        """المستند كما كان قبل التعديل وكما صار — بقالب طباعته."""
        try:
            r = self.t_rows.currentRow() if row is None else row
            if not (0 <= r < len(self._rows)):
                raise ValueError("اختر تعديلاً من الجدول أولاً")
            eid = self._rows[r]["id"]
            try:
                from services import browser_print
                return browser_print.open_compare(eid)
            except Exception:
                return self._compare_dialog(eid)
        except Exception as e:
            err(self, e)

    def _compare_dialog(self, edit_id):
        """بديلٌ داخل البرنامج إن تعذّر فتح المتصفح."""
        from services import browser_print
        html = browser_print.build_compare_page(edit_id)
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("المستند قبل التعديل وبعده")
        dlg.resize(1000, 720)
        view = QtWidgets.QTextBrowser()
        view.setHtml(html)
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.addWidget(view, 1)
        box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        box.rejected.connect(dlg.reject)
        lay.addWidget(box)
        dlg.exec_()
        return dlg

    def _paint_late(self, rows):
        """المتأخّر يُلوَّن: العين تلتقطه قبل أن تقرأ عمود التأخّر."""
        from ui import theme
        pal = theme.palette(theme.current_theme())
        bg = QtGui.QColor(pal.get("totBg", "#1C1A17"))
        ink = QtGui.QColor(pal.get("totFg", "#FFFFFF"))
        for i, r in enumerate(rows):
            if r["lag"] is None or r["lag"] < de.LATE_DAYS:
                continue
            for c in range(self.t_rows.columnCount()):
                it = self.t_rows.item(i, c)
                if it is None:
                    continue
                it.setBackground(bg)
                it.setForeground(ink)

    def _mark(self, table, rows):
        from ui import theme
        pal = theme.palette(theme.current_theme())
        bg = QtGui.QColor(pal.get("totBg", "#1C1A17"))
        ink = QtGui.QColor(pal.get("totFg", "#FFFFFF"))
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
            err(self, "اعرض التعديلات أولاً")
            return
        from services import print_manager
        try:
            print_manager.preview_document(
                self, "doc_edits", 0, date_from=self.res["date_from"],
                date_to=self.res["date_to"],
                source_table=self.kind.currentData() or None,
                min_lag=de.LATE_DAYS if self.late_only.isChecked() else 0)
        except Exception as e:
            err(self, e)

    def copy_summary(self):
        if not self.res:
            return
        s = self.res["sum"]

        def w(v):
            return snum(kv.g(v), 3)

        def m(v):
            return snum(v, 2)

        out = [f"من عدّل ماذا — من {self.res['date_from']} إلى "
               f"{self.res['date_to']}", "", *de.verdict(s, w, m), ""]
        for x in s["users"]:
            out.append(f"  {x['name']:<18} {x['count']:>5,} تعديلاً   "
                       f"متأخّر {x['late']:>4,}   وزن {w(x['d_gold']):>12}"
                       f"   نقد {m(x['d_cash']):>14}")
        QtWidgets.QApplication.clipboard().setText("\n".join(out))
        self.verdict.setText("نُسخت الخلاصة — الصقها في أي رسالة.")

    def refresh(self):
        """يُعرض السجل فور فتح الشاشة — بلا زرّ «اعرض»."""
        self.load()
