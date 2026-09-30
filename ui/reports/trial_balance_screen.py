# -*- coding: utf-8 -*-
"""ميزان المراجعة بالأرصدة والمجاميع — بالشكل الذي يطلبه المراجع.

لكل حساب ثلاثة أزواج (مدين | دائن): رصيد أول المدة، حركة الفترة، رصيد
آخر المدة — وكل زوجٍ متوازنٌ وحده في الإجمالي. بشجرة الحسابات
ومستوياتها (من الأقسام الرئيسية إلى الحساب التفصيلي) ومجموعٍ لكل قسم،
وبُعدٍ واحد في كل مرة: النقد بالريال، أو الذهب وزناً بعيار المصنع —
فلا يُجمع ريالٌ مع جرام في عمودٍ واحد.
"""
import csv
from datetime import date

from PyQt5 import QtCore, QtWidgets

from database.database import db
from models import statements
from services import karat_view as kv
from ui.widgets.common import (big_label, date_edit, dstr, err, info,
                               make_table, style_group_row, style_total_row,
                               title_label)
from ui.widgets.flow_layout import FlowLayout
from ui.widgets.table_tools import enhance as _enhance

COLS = ["الكود", "اسم الحساب",
        "أول المدة — مدين", "أول المدة — دائن",
        "حركة الفترة — مدين", "حركة الفترة — دائن",
        "آخر المدة — مدين", "آخر المدة — دائن"]
KEYS = ("open_dr", "open_cr", "dr", "cr", "close_dr", "close_cr")
LEVELS = ((1, "1 — الأقسام الرئيسية"), (2, "2 — المجموعات"),
          (3, "3 — الفروع"), (4, "4 — التفصيل"), (9, "الكل — كل الحسابات"))

# للتوافق مع من يستورد الاسم القديم
TYPE_AR = statements.TYPE_AR


def fmt(v, dim):
    """قيمةٌ للعرض — الصفر فارغٌ كما في الموازين المطبوعة."""
    if dim == "gold":
        v = kv.g(v)
        return f"{v:,.3f}" if abs(v) >= 0.0005 else ""
    return f"{v:,.2f}" if abs(v) >= 0.005 else ""


class TrialBalanceScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.last = None

        today = date.today()
        self.d_from = date_edit()
        self.d_from.setDate(QtCore.QDate(today.year, 1, 1))
        self.d_to = date_edit()
        self.d_to.setDate(QtCore.QDate(today.year, 12, 31))
        self.all_time = QtWidgets.QCheckBox("كل المدة")
        self.all_time.stateChanged.connect(self._toggle_period)
        self.dim = QtWidgets.QComboBox()
        self.dim.addItem("النقد (ريال سعودي)", "cash")
        self.dim.addItem(f"الذهب ({kv.unit()})", "gold")
        self.dim.currentIndexChanged.connect(self.load)
        self.level = QtWidgets.QComboBox()
        for v, lbl in LEVELS:
            self.level.addItem(lbl, v)
        self.level.setCurrentIndex(len(LEVELS) - 1)
        self.level.currentIndexChanged.connect(self.load)
        self.show_zero = QtWidgets.QCheckBox("إظهار الحسابات الصفرية")

        btn = QtWidgets.QPushButton("إعداد الميزان")
        btn.setObjectName("homeBtn")
        btn.clicked.connect(self.load)
        btn_print = QtWidgets.QPushButton("🖨 معاينة وطباعة")
        btn_print.clicked.connect(self.print_report)
        btn_exp = QtWidgets.QPushButton("⬇ تصدير Excel")
        btn_exp.setObjectName("ghost")
        btn_exp.clicked.connect(self.export_csv)
        btn_mov = QtWidgets.QPushButton("🔎 تفصيل الحركة")
        btn_mov.setToolTip("كشف حركة الحساب المحدد في فترة الميزان —"
                           " بأرقام السندات وتواريخها")
        btn_mov.clicked.connect(self.show_movement)

        head = FlowLayout()
        head.setSpacing(6)
        head.addWidget(QtWidgets.QLabel("من:"))
        head.addWidget(self.d_from)
        head.addWidget(QtWidgets.QLabel("إلى:"))
        head.addWidget(self.d_to)
        head.addWidget(self.all_time)
        head.addSpacing(8)
        head.addWidget(QtWidgets.QLabel("العملة:"))
        head.addWidget(self.dim)
        head.addWidget(QtWidgets.QLabel("المستوى:"))
        head.addWidget(self.level)
        head.addWidget(self.show_zero)
        head.addWidget(btn)
        head.addWidget(btn_mov)
        head.addWidget(btn_print)
        head.addWidget(btn_exp)
        head.addStretch(1)

        self.table = make_table()
        _enhance(self.table, key="trial_balance_std")
        self.table.doubleClicked.connect(lambda *_: self.show_movement())
        self.status = big_label()
        self.status.setWordWrap(True)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        lay.addWidget(title_label("ميزان المراجعة بالأرصدة والمجاميع"))
        lay.addLayout(head)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.status)

    def _toggle_period(self):
        on = not self.all_time.isChecked()
        self.d_from.setEnabled(on)
        self.d_to.setEnabled(on)

    def _range(self):
        if self.all_time.isChecked():
            return None, None
        return dstr(self.d_from), dstr(self.d_to)

    # ══════════════════════════════════════════════════════════════
    def load(self):
        try:
            d1, d2 = self._range()
            if d1 and d2 and d1 > d2:
                raise ValueError("تاريخ «من» بعد تاريخ «إلى»")
            dim = self.dim.currentData() or "cash"
            with db(readonly=True) as conn:
                tb = statements.trial_balance(
                    conn, d1, d2, dim, int(self.level.currentData() or 9),
                    include_zero=self.show_zero.isChecked())
            self.last = tb
            self._render(tb)
        except Exception as e:
            err(self, e)

    def _render(self, tb):
        dim = tb["dim"]
        rows = tb["rows"]
        t = tb["totals"]
        tbl = self.table
        tbl.setUpdatesEnabled(False)
        try:
            tbl.clear()
            tbl.setColumnCount(len(COLS))
            # الزوج في سطرين («أول المدة» فوق «مدين») — في سطرٍ واحد
            # يُقصّ العنوان على شاشة اللابتوب فيُقرأ «ول المدة — مدي»
            tbl.setHorizontalHeaderLabels(
                [c.replace(" — ", "\n") for c in COLS])
            tbl.setRowCount(len(rows) + 1)
            for i, r in enumerate(rows):
                kind = r.get("kind", "account")
                name = ("\u2003\u2003" * (r["level"] - 1)) + r["name"]
                # عنوان المجموعة بلا أرقام — أرقامها في «إجمالي …» بعد فروعها
                nums = ([""] * len(KEYS) if kind == "header"
                        else [fmt(r[k], dim) for k in KEYS])
                vals = [r["code"] if kind != "total" else "", name] + nums
                for c, v in enumerate(vals):
                    it = QtWidgets.QTableWidgetItem(v)
                    it.setTextAlignment(
                        (QtCore.Qt.AlignRight if c == 1
                         else QtCore.Qt.AlignCenter) | QtCore.Qt.AlignVCenter)
                    tbl.setItem(i, c, it)
                if kind in ("header", "total"):
                    style_group_row(tbl, i, r["level"])
                elif r["is_group"]:
                    # مجموعةٌ لم تُفتح فروعها (بالمستوى المختار): عريضة
                    for c in range(tbl.columnCount()):
                        f = tbl.item(i, c).font()
                        f.setBold(True)
                        tbl.item(i, c).setFont(f)
            last = len(rows)
            tot = ["", "الإجمالي"] + [fmt(t[k], dim) for k in KEYS]
            for c, v in enumerate(tot):
                it = QtWidgets.QTableWidgetItem(v)
                it.setTextAlignment(QtCore.Qt.AlignCenter)
                tbl.setItem(last, c, it)
            style_total_row(tbl, last)
        finally:
            tbl.setUpdatesEnabled(True)
        try:
            from ui.widgets.table_fit import fit_columns
            fit_columns(tbl, [7, 25, 11, 11, 12, 12, 11, 11])
        except Exception:
            pass
        unit = "ريال" if dim == "cash" else kv.unit()
        marks = [("أول المدة", t["ok_open"]), ("حركة الفترة", t["ok_period"]),
                 ("آخر المدة", t["ok_close"])]
        per = "   ·   ".join(
            f"{n}: {'✔ مدين = دائن' if ok else '✘ غير متوازن'}"
            for n, ok in marks)
        span = (f"{tb['date_from'] or 'البداية'} ← {tb['date_to'] or 'اليوم'}")
        self.status.setText(
            f"{'✔ الميزان متوازن' if t['balanced'] else '✘ الميزان غير متوازن'}"
            f" ({unit})   ·   {per}   ·   الفترة: {span}   ·   "
            f"عدد الحسابات: {tb['accounts']}")
        self.status.setStyleSheet(
            "color:#0F5A24;font-weight:bold" if t["balanced"]
            else "color:#9A0018;font-weight:bold")

    def show_movement(self):
        """كشف حركة الحساب المحدد في فترة الميزان — من أين جاء رقمه."""
        from ui.widgets.account_movement import show_movement
        i = self.table.currentRow()
        rows = (self.last or {}).get("rows") or []
        if not (0 <= i < len(rows)):
            err(self, ValueError("اختر حساباً من الميزان أولاً"))
            return
        r = rows[i]
        show_movement(self, r["code"], r["name"], self.last["date_from"],
                      self.last["date_to"])

    # ══════════════════════════════════════════════════════════════
    def export_csv(self):
        try:
            if not self.last:
                self.load()
            if not self.last:
                raise ValueError("أعِدّ الميزان أولاً")
            tb = self.last
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "حفظ ميزان المراجعة", "ميزان_المراجعة.csv",
                "ملف Excel (*.csv)")
            if not path:
                return
            dim = tb["dim"]
            conv = (lambda v: round(kv.g(v), 3)) if dim == "gold" else \
                (lambda v: round(v, 2))
            # utf-8-sig ليفتح Excel العربية بلا رموز مشوّهة
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["ميزان المراجعة بالأرصدة والمجاميع",
                            f"من {tb['date_from'] or 'البداية'}",
                            f"إلى {tb['date_to'] or 'اليوم'}",
                            "ريال سعودي" if dim == "cash" else kv.unit()])
                w.writerow(["المستوى"] + COLS)
                for r in tb["rows"]:
                    hdr = r.get("kind") == "header"
                    w.writerow([r["level"], r["code"], r["name"]]
                               + [("" if hdr else conv(r[k])) for k in KEYS])
                w.writerow(["", "", "الإجمالي"]
                           + [conv(tb["totals"][k]) for k in KEYS])
            info(self, f"حُفظ الملف:\n{path}")
        except Exception as e:
            err(self, e)

    def print_report(self):
        try:
            if not self.last:
                self.load()
            if not self.last:
                raise ValueError("أعِدّ الميزان أولاً")
            from services import print_manager
            print_manager.preview_document(
                self, "trial_balance", 0,
                date_from=self.last["date_from"] or None,
                date_to=self.last["date_to"] or None,
                include_zero=self.show_zero.isChecked(),
                dim=self.last["dim"], max_level=self.last["max_level"])
        except Exception as e:
            err(self, e)

    def refresh(self):
        if self.last:
            self.load()
