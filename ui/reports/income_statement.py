# -*- coding: utf-8 -*-
"""قائمة الدخل (الأرباح والخسائر) — تبويبان.

1. **قائمة الدخل** بالنهج المحاسبي المعتمد (IAS 1، طريقة وظيفة المصروف):
   من دفتر الأستاذ نفسه على أساس الاستحقاق — الإيرادات ثم مردوداتها
   وخصومها ⇒ صافي الإيرادات، ثم تكلفة الإيرادات ⇒ مجمل الربح، ثم
   المصاريف التشغيلية ⇒ الربح التشغيلي، ثم الأخرى ⇒ صافي ربح الفترة؛
   مقارنةً بالفترة المماثلة من السنة السابقة، والسالب بين قوسين.
   وصافيها يساوي «صافي ربح الفترة» في قائمة المركز المالي.
2. **نموذج التصريف (نقد ووزن)** — العرض الإداري السابق كما هو:

عمودان متجاوران: (النقد/الريال) و(الوزن/الجرام)، بالمنطق:
* الإيراد النقدي = صافي أجور المبيعات (بيع − مرتجع).
* صافي الذهب المباع يُعرض أعلى الشاشة للتوضيح فقط (انتقال أصل).
* فاقد الذهب العيني = الفاقد الفني للصب + الفاقد التشغيلي للتصنيع.
* المصروفات النقدية = إجمالي سندات الصرف.
* صافي الربح النقدي = صافي الأجور − المصروفات.
* صافي حركة الذهب = − إجمالي الفاقد (عجز عيني).
"""
from datetime import date

from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from services import karat_view as kv
from models import statements
from models.reports import income_statement_consignment
from ui.widgets.common import (date_edit, dstr, err, fill, make_table,
                               tab_widget, title_label)
from ui.widgets.flow_layout import FlowLayout
from ui.widgets.table_tools import enhance as _enhance

PERIODS = [("شهري", "month"), ("ربع سنوي", "quarter"), ("نصف سنوي", "half"),
           ("سنوي", "year"), ("مخصص", "custom")]


def period_range(kind, ref: date):
    y = ref.year
    if kind == "month":
        start = date(y, ref.month, 1)
        nxt = date(y + (ref.month == 12), (ref.month % 12) + 1, 1)
    elif kind == "quarter":
        q = (ref.month - 1) // 3
        start = date(y, q * 3 + 1, 1)
        nxt = date(y + (q == 3), ((q + 1) * 3) % 12 + 1, 1)
    elif kind == "half":
        h = 0 if ref.month <= 6 else 1
        start = date(y, h * 6 + 1, 1)
        nxt = date(y + h, 1 if h else 7, 1)
    else:
        return date(y, 1, 1), date(y, 12, 31)
    return start, date.fromordinal(nxt.toordinal() - 1)


class ConsignmentTab(QtWidgets.QWidget):
    """العرض الإداري: نموذج تسليم البضاعة للتصريف (نقد ووزن)."""

    def __init__(self, user):
        super().__init__()
        self.period = QtWidgets.QComboBox()
        for label, key in PERIODS:
            self.period.addItem(label, key)
        self.period.setCurrentIndex(3)
        self.period.currentIndexChanged.connect(self.apply_period)
        self.d_from = date_edit()
        self.d_from.setDate(QtCore.QDate(QtCore.QDate.currentDate().year(), 1, 1))
        self.d_to = date_edit()
        btn = QtWidgets.QPushButton("إعداد القائمة")
        btn.clicked.connect(self.load)

        head = FlowLayout()
        head.addWidget(QtWidgets.QLabel("الفترة:"))
        head.addWidget(self.period)
        head.addWidget(QtWidgets.QLabel("من:"))
        head.addWidget(self.d_from)
        head.addWidget(QtWidgets.QLabel("إلى:"))
        head.addWidget(self.d_to)
        head.addWidget(btn)
        head.addStretch(1)

        # شريط علوي: صافي الذهب المباع (عرض فقط)
        self.movement = QtWidgets.QLabel("")
        self.movement.setObjectName("eqBar")
        self.movement.setAlignment(QtCore.Qt.AlignCenter)
        self.movement.setWordWrap(True)

        self.table = make_table()
        _enhance(self.table, key="income")

        # شريط سفلي: النتيجة النهائية
        self.result = QtWidgets.QLabel("")
        self.result.setObjectName("eqBar")
        self.result.setAlignment(QtCore.Qt.AlignCenter)
        self.result.setWordWrap(True)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        note = QtWidgets.QLabel(
            "الإيراد النقدي الحقيقي = صافي أجور المبيعات. صافي الذهب المباع "
            "للعرض فقط (انتقال أصل لا ربح). فاقد الذهب العيني = فاقد الصب + "
            "فاقد التصنيع. المصروفات من سندات الصرف.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addLayout(head)
        lay.addWidget(self.movement)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.result)

    def apply_period(self):
        kind = self.period.currentData()
        if kind == "custom":
            return
        s, e = period_range(kind, date.today())
        self.d_from.setDate(QtCore.QDate(s.year, s.month, s.day))
        self.d_to.setDate(QtCore.QDate(e.year, e.month, e.day))

    def load(self):
        try:
            f = dstr(self.d_from)
            t = dstr(self.d_to)
            with db(readonly=True) as conn:
                r = income_statement_consignment(conn, f, t)
            self._render(r)
        except Exception as e:
            err(self, e)

    def _render(self, r):
        def m(v):
            return f"{v:,.2f}"

        def g(v):
            """وزن بمكافئ 18 ← بعيار المصنع (كل أوزان القائمة)."""
            return f"{kv.g(v):,.2f}"

        # الشريط العلوي: حجم حركة البضاعة (وزني، عرض فقط)
        self.movement.setText(
            f"حجم حركة البضاعة (للعرض فقط) — صافي الذهب المباع: "
            f"{g(r['net_gold_sold'])} {kv.unit()}   "
            f"(مبيعات {g(r['sales_weight'])} − مرتجعات {g(r['returns_weight'])})")
        self.movement.setStyleSheet(
            "background:#f3ece0; color:#5E4A0C; font-size:12pt;"
            " font-weight:bold; padding:8px; border-radius:6px;")

        rows = [
            ("═══ أولاً: الإيرادات التشغيلية ═══", "", ""),
            (f"    مبيعات ({r['sales_count']} فاتورة)",
             m(r["sales_wages"]), g(r["sales_weight"])),
            (f"    (−) مرتجعات ({r['returns_count']} فاتورة)",
             m(-r["returns_wages"]), g(-r["returns_weight"])),
            ("    صافي المبيعات", m(r["net_wages"]), g(r["net_gold_sold"])),
            ("", "", ""),
            ("    صافي أجور المبيعات (الإيراد النقدي)", m(r["net_wages"]), "—"),
            ("    صافي حركة الذهب المباع (وزناً — انتقال أصل)",
             "—", g(r["net_gold_sold"])),
            ("", "", ""),
            ("═══ ثانياً: خسائر التشغيل العينية (الذهب) ═══", "", ""),
            ("    الصب والتصفية (1350)", "—", g(r["casting_loss"])),
            ("    الفاقد التشغيلي — قسم التصنيع (5110)", "—",
             g(r["manufacturing_loss"])),
            ("    إجمالي فاقد الذهب", "—", g(r["total_gold_loss"])),
            ("", "", ""),
            ("═══ ثالثاً: المصروفات التشغيلية والعمومية ═══", "", ""),
            (f"    المدفوع عبر سندات الصرف ({r['payments_count']} سند)",
             m(r["expenses_cash"]), "—"),
            ("    إجمالي المصروفات", m(r["expenses_cash"]), "—"),
        ]
        fill(self.table, ["البند", "النقد / الأجور (ريال)",
                          f"الذهب ({kv.unit()})"],
             rows)

        # الشريط السفلي: النتيجة النهائية
        profit = r["net_profit_cash"]
        kind = "ربح" if profit >= 0 else "خسارة"
        color = ("#1e7a34", "#e6f4ea") if profit >= 0 else ("#a61b1b",
                                                             "#fdecea")
        self.result.setText(
            f"صافي ال{kind} النقدي: {m(profit)} ريال "
            f"(صافي الأجور {m(r['net_wages'])} − المصروفات "
            f"{m(r['expenses_cash'])})          "
            f"صافي حركة الذهب العينية: {g(r['net_gold_movement'])} جم "
            f"(عجز عيني = إجمالي الفاقد)")
        self.result.setStyleSheet(
            f"background:{color[1]}; color:{color[0]}; font-size:13pt;"
            f" font-weight:bold; padding:9px; border-radius:6px;")

    def refresh(self):
        pass


# ══════════════════════════════════════════════════════════════════
#  قائمة الدخل بالنهج المحاسبي المعتمد
# ══════════════════════════════════════════════════════════════════
def money(v, gold=False):
    """مبلغ القائمة: السالب بين قوسين والصفر شرطة."""
    v = kv.g(v or 0.0) if gold else (v or 0.0)
    eps = 0.0005 if gold else 0.005
    if abs(v) < eps:
        return "—"
    s = f"{abs(v):,.3f}" if gold else f"{abs(v):,.2f}"
    return f"({s})" if v < 0 else s


class StandardIncomeTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.st = None
        self.rows = []
        self.period = QtWidgets.QComboBox()
        for label, key in PERIODS:
            self.period.addItem(label, key)
        self.period.setCurrentIndex(3)
        self.period.currentIndexChanged.connect(self.apply_period)
        self.d_from = date_edit()
        self.d_from.setDate(
            QtCore.QDate(QtCore.QDate.currentDate().year(), 1, 1))
        self.d_to = date_edit()
        self.d_to.setDate(
            QtCore.QDate(QtCore.QDate.currentDate().year(), 12, 31))
        self.cmp_on = QtWidgets.QCheckBox(
            "مقارنة بالفترة المماثلة من السنة السابقة")
        self.cmp_on.setChecked(True)
        self.accounts = QtWidgets.QCheckBox("إظهار الحسابات تحت كل بند")
        self.accounts.stateChanged.connect(self._rerender)

        btn = QtWidgets.QPushButton("إعداد القائمة")
        btn.setObjectName("homeBtn")
        btn.clicked.connect(self.load)
        btn_print = QtWidgets.QPushButton("🖨 معاينة وطباعة")
        btn_print.clicked.connect(self.print_statement)
        btn_exp = QtWidgets.QPushButton("⬇ تصدير Excel")
        btn_exp.setObjectName("ghost")
        btn_exp.clicked.connect(self.export_csv)

        head = FlowLayout()
        head.setSpacing(6)
        head.addWidget(QtWidgets.QLabel("الفترة:"))
        head.addWidget(self.period)
        head.addWidget(QtWidgets.QLabel("من:"))
        head.addWidget(self.d_from)
        head.addWidget(QtWidgets.QLabel("إلى:"))
        head.addWidget(self.d_to)
        head.addWidget(self.cmp_on)
        head.addWidget(self.accounts)
        head.addWidget(btn)
        head.addWidget(btn_print)
        head.addWidget(btn_exp)
        head.addStretch(1)

        self.table = make_table()
        _enhance(self.table, key="income_std")
        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(4)
        lay.addLayout(head)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.status)

    def apply_period(self):
        kind = self.period.currentData()
        if kind == "custom":
            return
        s, e = period_range(kind, date.today())
        self.d_from.setDate(QtCore.QDate(s.year, s.month, s.day))
        self.d_to.setDate(QtCore.QDate(e.year, e.month, e.day))

    def _params(self):
        f, t = dstr(self.d_from), dstr(self.d_to)
        if f > t:
            raise ValueError("تاريخ «من» بعد تاريخ «إلى»")
        return f, t, self.cmp_on.isChecked()

    def load(self):
        try:
            f, t, cmp = self._params()
            with db(readonly=True) as conn:
                self.st = statements.income_statement(conn, f, t, cmp)
            self._rerender()
        except Exception as e:
            err(self, e)

    def _headers(self):
        cmp = bool(self.st["compare_from"])
        u = f"ذهب ({kv.unit()})"
        h = ["البيان", "ريال\nالفترة الحالية"]
        if cmp:
            h.append("ريال\nفترة المقارنة")
        h.append(f"{u}\nالفترة الحالية")
        if cmp:
            h.append(f"{u}\nفترة المقارنة")
        return h

    def _values(self, r):
        cmp = bool(self.st["compare_from"])
        if r["kind"] == "acct" and cmp:
            # الإيضاح للفترة الحالية وحدها
            return [money(r["cash"]), "", money(r["gold"], True), ""]
        v = [money(r["cash"])]
        if cmp:
            v.append(money(r["cash_cmp"]))
        v.append(money(r["gold"], True))
        if cmp:
            v.append(money(r["gold_cmp"], True))
        return v

    def _rerender(self):
        if not self.st:
            return
        self.rows = statements.is_layout(self.st, self.accounts.isChecked())
        heads = self._headers()
        tbl = self.table
        tbl.setUpdatesEnabled(False)
        try:
            tbl.clear()
            tbl.clearSpans()
            tbl.setColumnCount(len(heads))
            tbl.setHorizontalHeaderLabels(heads)
            tbl.setRowCount(len(self.rows))
            sec_bg = QtGui.QColor("#EFE9DC")
            tot_bg = QtGui.QColor("#F2EEE4")
            muted = QtGui.QColor("#5A5146")
            for i, r in enumerate(self.rows):
                k = r["kind"]
                if k == "sec":
                    vals = [r["label"]] + [""] * (len(heads) - 1)
                else:
                    pad = {"line": "\u2003", "acct": "\u2003" * 3}
                    vals = (["\u200f" + pad.get(k, "") + r["label"]]
                            + self._values(r))
                for c, v in enumerate(vals):
                    it = QtWidgets.QTableWidgetItem(v)
                    it.setTextAlignment(
                        (QtCore.Qt.AlignRight if c == 0
                         else QtCore.Qt.AlignCenter) | QtCore.Qt.AlignVCenter)
                    f = it.font()
                    if k in ("sec", "sub", "grand"):
                        f.setBold(True)
                    if k == "acct":
                        f.setPointSizeF(max(7.0, f.pointSizeF() - 1))
                        it.setForeground(muted)
                    it.setFont(f)
                    if k == "sec":
                        it.setBackground(sec_bg)
                    elif k in ("sub", "grand"):
                        it.setBackground(tot_bg)
                    tbl.setItem(i, c, it)
                if k == "sec":
                    tbl.setSpan(i, 0, 1, len(heads))
        finally:
            tbl.setUpdatesEnabled(True)
        try:
            from ui.widgets.table_fit import fit_columns
            n = len(heads) - 1
            fit_columns(tbl, [40] + [60 // n] * n)
        except Exception:
            pass
        c = self.st["cash"]["totals"]
        net = c["net"]
        rev = c["net_revenue"]
        margin = (f"   ·   هامش مجمل الربح: {c['gross'] / rev * 100:,.1f}%"
                  f"   ·   هامش صافي الربح: {net / rev * 100:,.1f}%"
                  if abs(rev) >= 0.005 else "")
        kind = "ربح" if net >= 0 else "خسارة"
        st = self.st
        per = f"الفترة: من {st['date_from']} إلى {st['date_to']}"
        if st["compare_from"]:
            per += (f"   ·   المقارنة: من {st['compare_from']} إلى "
                    f"{st['compare_to']}")
        self.status.setText(
            f"صافي {kind} الفترة: {abs(net):,.2f} ريال{margin}   ·   {per}"
            "   ·   من دفتر الأستاذ على أساس الاستحقاق، وقيد الإقفال"
            " السنوي مستبعد")
        self.status.setStyleSheet(
            "color:#0F5A24;font-weight:bold" if net >= 0
            else "color:#9A0018;font-weight:bold")

    def export_csv(self):
        try:
            if not self.st:
                self.load()
            if not self.st:
                return
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "حفظ قائمة الدخل", "قائمة_الدخل.csv",
                "ملف Excel (*.csv)")
            if not path:
                return
            import csv
            cmp = bool(self.st["compare_from"])
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh)
                w.writerow(["قائمة الدخل", self.st["date_from"],
                            self.st["date_to"]])
                w.writerow([h.replace("\n", " — ")
                            for h in self._headers()])
                for r in self.rows:
                    if r["kind"] == "sec":
                        w.writerow([r["label"]])
                        continue
                    vals = [round(r["cash"], 2)]
                    if cmp:
                        vals.append(round(r["cash_cmp"], 2))
                    vals.append(round(kv.g(r["gold"]), 3))
                    if cmp:
                        vals.append(round(kv.g(r["gold_cmp"]), 3))
                    w.writerow([r["label"]] + vals)
            from ui.widgets.common import info
            info(self, f"حُفظ الملف:\n{path}")
        except Exception as e:
            err(self, e)

    def print_statement(self):
        try:
            f, t, cmp = self._params()
            from services import print_manager
            print_manager.preview_document(
                self, "income_statement", 0, date_from=f, date_to=t,
                compare=cmp, show_accounts=self.accounts.isChecked())
        except Exception as e:
            err(self, e)


class IncomeStatementScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.standard = StandardIncomeTab(self)
        self.consignment = ConsignmentTab(user)
        self.tabs = tab_widget()
        self.tabs.addTab(self.standard, "قائمة الدخل")
        self.tabs.addTab(self.consignment, "نموذج التصريف (نقد ووزن)")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        lay.addWidget(title_label("قائمة الدخل (الأرباح والخسائر)"))
        lay.addWidget(self.tabs, 1)
        self.standard.load()

    # توافقٌ مع من يستدعي أسماء الشاشة القديمة
    @property
    def d_from(self):
        return self.consignment.d_from

    @property
    def d_to(self):
        return self.consignment.d_to

    def load(self):
        self.standard.load()

    def refresh(self):
        if self.standard.st is not None:
            self.standard.load()
