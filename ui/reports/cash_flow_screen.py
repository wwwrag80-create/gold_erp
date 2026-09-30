# -*- coding: utf-8 -*-
"""قائمة التدفقات النقدية — معيار المحاسبة الدولي 7 (IAS 7).

ثلاثة أنشطة: تشغيلية · استثمارية · تمويلية، ثم صافي التغير في النقد
وما في حكمه ورصيداه أول الفترة وآخرها — وآخرها يساوي بند «النقد وما في
حكمه» في قائمة المركز المالي.

طريقتان للأنشطة التشغيلية تنتهيان إلى الرقم نفسه:
* **غير المباشرة** (الأشيع في القوائم المدقّقة): صافي الربح ← الإهلاك ←
  تغيّرات رأس المال العامل.
* **المباشرة** (يشجّعها المعيار): المتحصلات من العملاء، المدفوع
  للموردين وللموظفين وللمصروفات والضريبة.

القائمة بالريال: الذهب مخزونٌ لا نقد، وحركته في قائمة المركز المالي.
"""
import csv
from datetime import date

from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from models import statements
from ui.reports.income_statement import PERIODS, money, period_range
from ui.widgets.common import (date_edit, dstr, err, info, make_table,
                               title_label)
from ui.widgets.flow_layout import FlowLayout
from ui.widgets.table_tools import enhance as _enhance


class CashFlowScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.cf = None
        self.rows = []

        self.period = QtWidgets.QComboBox()
        for label, key in PERIODS:
            self.period.addItem(label, key)
        self.period.setCurrentIndex(3)
        self.period.currentIndexChanged.connect(self.apply_period)
        today = date.today()
        self.d_from = date_edit()
        self.d_from.setDate(QtCore.QDate(today.year, 1, 1))
        self.d_to = date_edit()
        self.d_to.setDate(QtCore.QDate(today.year, 12, 31))
        self.method = QtWidgets.QComboBox()
        self.method.addItem("الطريقة غير المباشرة", "indirect")
        self.method.addItem("الطريقة المباشرة", "direct")
        self.method.currentIndexChanged.connect(self._rerender)
        self.cmp_on = QtWidgets.QCheckBox(
            "مقارنة بالفترة المماثلة من السنة السابقة")
        self.cmp_on.setChecked(True)

        btn = QtWidgets.QPushButton("إعداد القائمة")
        btn.setObjectName("homeBtn")
        btn.clicked.connect(self.load)
        btn_print = QtWidgets.QPushButton("🖨 معاينة وطباعة")
        btn_print.clicked.connect(self.print_statement)
        btn_exp = QtWidgets.QPushButton("⬇ تصدير Excel")
        btn_exp.setObjectName("ghost")
        btn_exp.clicked.connect(self.export_csv)
        btn_mov = QtWidgets.QPushButton("🔎 حركة الصندوق والبنوك")
        btn_mov.setToolTip("حسابات النقد وما في حكمه، ومن كلٍّ منها كشف"
                           " حركته في الفترة بأرقام السندات")
        btn_mov.clicked.connect(self.show_movement)

        head = FlowLayout()
        head.setSpacing(6)
        head.addWidget(QtWidgets.QLabel("الفترة:"))
        head.addWidget(self.period)
        head.addWidget(QtWidgets.QLabel("من:"))
        head.addWidget(self.d_from)
        head.addWidget(QtWidgets.QLabel("إلى:"))
        head.addWidget(self.d_to)
        head.addWidget(self.method)
        head.addWidget(self.cmp_on)
        head.addWidget(btn)
        head.addWidget(btn_mov)
        head.addWidget(btn_print)
        head.addWidget(btn_exp)
        head.addStretch(1)

        self.table = make_table()
        _enhance(self.table, key="cash_flow")
        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        lay.addWidget(title_label("قائمة التدفقات النقدية"))
        lay.addLayout(head)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.status)
        self.load()

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
                self.cf = statements.cash_flow(conn, f, t, cmp)
            self._rerender()
        except Exception as e:
            err(self, e)

    def _headers(self):
        h = ["البيان", "ريال\nالفترة الحالية"]
        if self.cf["compare_from"]:
            h.append("ريال\nفترة المقارنة")
        return h

    def _rerender(self):
        if not self.cf:
            return
        method = self.method.currentData() or "indirect"
        self.rows = statements.cf_layout(self.cf, method)
        heads = self._headers()
        cmp = bool(self.cf["compare_from"])
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
            for i, r in enumerate(self.rows):
                k = r["kind"]
                if k == "sec":
                    vals = [r["label"]] + [""] * (len(heads) - 1)
                else:
                    # علامة الاتجاه RLM أولاً: سطرٌ يبدأ بقوس يقلبه Qt
                    # فيُقرأ «النقص … (الزيادة)» معكوساً
                    pad = "\u2003" if k == "line" else ""
                    vals = ["\u200f" + pad + r["label"], money(r["cash"])]
                    if cmp:
                        vals.append(money(r["cash_cmp"]))
                for c, v in enumerate(vals):
                    it = QtWidgets.QTableWidgetItem(v)
                    it.setTextAlignment(
                        (QtCore.Qt.AlignRight if c == 0
                         else QtCore.Qt.AlignCenter) | QtCore.Qt.AlignVCenter)
                    if k in ("sec", "sub", "grand"):
                        f = it.font()
                        f.setBold(True)
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
            fit_columns(tbl, [56, 22, 22] if cmp else [64, 36])
        except Exception:
            pass
        t = self.cf["cur"]["totals"]
        ok = self.cf["balanced"]
        extra = (f"   ·   معاملات استثمارية غير نقدية (أصول بالأجل): "
                 f"{t['noncash']:,.2f} ريال" if abs(t["noncash"]) >= 0.005
                 else "")
        self.status.setText(
            ("✔ آخر الفترة = أولها + صافي التدفقات، ويطابق رصيد الصندوق"
             " والبنوك في الدفتر" if ok else
             f"✘ فرق {t['diff']:,.2f} ريال بين التدفقات والرصيد الدفتري")
            + f"   ·   الفترة: من {self.cf['date_from']} إلى "
            f"{self.cf['date_to']}" + extra)
        self.status.setStyleSheet(
            "color:#0F5A24;font-weight:bold" if ok
            else "color:#9A0018;font-weight:bold")

    def show_movement(self):
        """النقد وما في حكمه: كل صندوقٍ وبنك برصيده، ومنه كشف حركته."""
        from models.accounts import subtree_ids_by_code
        from ui.widgets.account_movement import AccountsPicker
        try:
            d1, d2 = dstr(self.d_from), dstr(self.d_to)
            with db(readonly=True) as conn:
                ids = subtree_ids_by_code(conn, "1010")
                if not ids:
                    raise ValueError("مجموعة النقد 1010 غير موجودة")
                qs = ",".join("?" * len(ids))
                items = [(r["code"], r["name"], r["c"] or 0.0, 0.0)
                         for r in conn.execute(
                    "SELECT a.code, a.name,"
                    " (SELECT COALESCE(SUM(l.cash_debit-l.cash_credit),0)"
                    "  FROM journal_lines l JOIN journal_entries e"
                    "  ON e.id=l.entry_id AND e.is_deleted=0"
                    "  WHERE l.account_id=a.id AND e.entry_date<=?) c"
                    f" FROM accounts a WHERE a.id IN ({qs})"
                    " AND a.is_postable=1 ORDER BY a.code", [d2] + ids)]
            AccountsPicker(self, "النقد وما في حكمه", items, d1, d2,
                           note=f"الأرصدة كما في {d2}").exec_()
        except Exception as e:
            err(self, e)

    def export_csv(self):
        try:
            if not self.cf:
                self.load()
            if not self.cf:
                return
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "حفظ قائمة التدفقات النقدية",
                "قائمة_التدفقات_النقدية.csv", "ملف Excel (*.csv)")
            if not path:
                return
            cmp = bool(self.cf["compare_from"])
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh)
                w.writerow(["قائمة التدفقات النقدية", self.cf["date_from"],
                            self.cf["date_to"]])
                w.writerow([h.replace("\n", " — ")
                            for h in self._headers()])
                for r in self.rows:
                    if r["kind"] == "sec":
                        w.writerow([r["label"]])
                        continue
                    vals = [round(r["cash"], 2)]
                    if cmp:
                        vals.append(round(r["cash_cmp"], 2))
                    w.writerow([r["label"]] + vals)
            info(self, f"حُفظ الملف:\n{path}")
        except Exception as e:
            err(self, e)

    def print_statement(self):
        try:
            f, t, cmp = self._params()
            from services import print_manager
            print_manager.preview_document(
                self, "cash_flow", 0, date_from=f, date_to=t, compare=cmp,
                method=self.method.currentData() or "indirect")
        except Exception as e:
            err(self, e)

    def refresh(self):
        if self.cf is not None:
            self.load()
