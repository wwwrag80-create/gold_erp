# -*- coding: utf-8 -*-
"""«المبيعات» — أطقم فواتير بيعٍ مختارة: هل ما زالت معه أم رجعت، وإلى أين
ذهبت (5.2.4).

١) اختر الجهة (أو كل الجهات) والفترة، ثم «اختر الفواتير…» — نافذةٌ بفواتير
   المبيعات بعلامة اختيار لكلٍّ منها.
٢) يُعرض كل طقمٍ فيها بوزنه وحاله: «مباع معه» أو «مرتجع» برقم مرتجعه —
   ومكانه الآن: «الخزنة»، أو «عند فلان» إن بِيع بعد رجوعه لمندوبٍ آخر.
٣) «🖨 طباعة» تُخرجها بصورة موديل كل طقم.

قراءةٌ فقط: لا تُغيّر في الدفاتر شيئاً.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from models import entities, sales_sets
from services import karat_view as kv
from services import numfmt as _nf
from ui import kit
from ui.widgets.common import (big_label, date_edit, dstr, err, fill,
                               make_table, search_combo, title_label)

COLS = ["فاتورة البيع", "التاريخ", "بِيع إلى", "رقم التشغيل", "الموديل",
        "الوزن", "الحال", "المرتجع", "أين هو الآن"]
PICK_COLS = ["", "رقم الفاتورة", "التاريخ", "الجهة", "الأطقم", "الوزن",
             "ملاحظة"]
ALL = "__all__"


class InvoicePicker(QtWidgets.QDialog):
    """نافذة اختيار فواتير المبيعات — علامةٌ لكل فاتورة."""

    def __init__(self, rows, chosen=(), parent=None):
        super().__init__(parent)
        self.setWindowTitle("اختر فواتير المبيعات")
        self.setLayoutDirection(QtCore.Qt.RightToLeft)
        self.resize(820, 560)
        self.rows = rows
        chosen = set(chosen or ())
        self.table = make_table()
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        data = [("", r["invoice_no"], r["invoice_date"], r["party"],
                 str(r["n"]), _nf.f2(kv.g(r["wt"])),
                 (f"ملغاة بالمستند {r['reversed_by']}"
                  if r.get("reversed_by") else "")) for r in rows]
        fill(self.table, PICK_COLS, data)
        for i, r in enumerate(rows):
            it = QtWidgets.QTableWidgetItem()
            it.setFlags(QtCore.Qt.ItemIsUserCheckable
                        | QtCore.Qt.ItemIsEnabled)
            it.setCheckState(QtCore.Qt.Checked if r["id"] in chosen
                             else QtCore.Qt.Unchecked)
            self.table.setItem(i, 0, it)
        self.table.setColumnWidth(0, 38)
        self.table.cellClicked.connect(self._toggle)
        self.count = QtWidgets.QLabel("")
        self.table.itemChanged.connect(lambda *_: self._count())

        b_all = kit.PushButton("تحديد الكل")
        b_all.clicked.connect(lambda: self._set_all(True))
        b_none = kit.PushButton("إلغاء التحديد")
        b_none.clicked.connect(lambda: self._set_all(False))
        ok = kit.PushButton("عرض الأطقم")
        ok.clicked.connect(self.accept)
        cancel = kit.PushButton("إلغاء")
        cancel.clicked.connect(self.reject)

        note = QtWidgets.QLabel(
            "ضع علامةً على الفواتير التي تريد تتبّع أطقمها — من جهةٍ واحدة "
            "أو من عدة جهات — ثم «عرض الأطقم».")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        bar = QtWidgets.QHBoxLayout()
        bar.addWidget(b_all)
        bar.addWidget(b_none)
        bar.addWidget(self.count)
        bar.addStretch(1)
        bar.addWidget(cancel)
        bar.addWidget(ok)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(note)
        lay.addWidget(self.table, 1)
        lay.addLayout(bar)
        self._count()

    def _toggle(self, row, col):
        if col == 0:
            return              # مربّع العلامة نفسه يتبدّل وحده
        it = self.table.item(row, 0)
        if it is not None:
            it.setCheckState(QtCore.Qt.Unchecked
                             if it.checkState() == QtCore.Qt.Checked
                             else QtCore.Qt.Checked)

    def _set_all(self, on):
        self.table.blockSignals(True)
        for i in range(self.table.rowCount()):
            it = self.table.item(i, 0)
            if it is not None:
                it.setCheckState(QtCore.Qt.Checked if on
                                 else QtCore.Qt.Unchecked)
        self.table.blockSignals(False)
        self._count()

    def _count(self):
        n = len(self.chosen())
        self.count.setText(f"مختار: {n} فاتورة")

    def chosen(self):
        out = []
        for i, r in enumerate(self.rows):
            it = self.table.item(i, 0)
            if it is not None and it.checkState() == QtCore.Qt.Checked:
                out.append(r["id"])
        return out


class SalesSetsScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.chosen = []
        self.rows = []

        self.party = search_combo("كل الجهات — أو اكتب اسم الجهة…")
        self.party.setMinimumWidth(260)
        self.d_from = date_edit()
        self.d_from.setDate(QtCore.QDate.currentDate().addMonths(-3))
        self.d_to = date_edit()
        b_pick = kit.PushButton("☑ اختر الفواتير…")
        b_pick.clicked.connect(self.pick)
        b_print = kit.PushButton("🖨 طباعة بصور الموديلات")
        b_print.clicked.connect(self.print_report)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("الجهة:"))
        top.addWidget(self.party)
        top.addWidget(QtWidgets.QLabel("من:"))
        top.addWidget(self.d_from)
        top.addWidget(QtWidgets.QLabel("إلى:"))
        top.addWidget(self.d_to)
        top.addWidget(b_pick)
        top.addStretch(1)
        top.addWidget(b_print)

        intro = QtWidgets.QLabel(
            "اختر فواتير مبيعاتٍ بعينها فيظهر كل طقمٍ فيها بوزنه: هل ما زال "
            "مع من بِيع له، أم رجع — ومكانه الآن: الخزنة، أو عند مندوبٍ "
            "آخر باسمه.")
        intro.setObjectName("cardSub")
        intro.setWordWrap(True)
        self.summary = big_label("لم تُختر فواتير بعد.")
        self.summary.setWordWrap(True)
        self.table = make_table()
        self.table.setProperty(
            "emptyText", "اضغط «☑ اختر الفواتير…» — ثم ضع علامةً على "
            "الفواتير التي تريد تتبّع أطقمها")
        self.table.setProperty(
            "searchHint", "🔍 ابحث: رقم تشغيل · موديل · جهة · فاتورة…")

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("المبيعات — أطقم الفواتير وأين صارت"))
        lay.addWidget(intro)
        lay.addLayout(top)
        lay.addWidget(self.summary)
        lay.addWidget(self.table, 1)
        self._load_parties()

    # ── الجهات ──
    def _load_parties(self):
        try:
            with db(readonly=True) as conn:
                rows = [e for e in entities.list_customers(conn)
                        if e["entity_type"] != "internal"]
            self.party.blockSignals(True)
            self.party.clear()
            self.party.addItem("★ كل الجهات", ALL)
            for e in rows:
                self.party.addItem(e["name"], e["id"])
            self.party.setCurrentIndex(0)
            self.party.blockSignals(False)
        except Exception as e:
            err(self, e)

    def refresh(self):
        self._load_parties()
        if self.chosen:
            self.show_sets()

    # ── الاختيار ──
    def pick(self):
        try:
            pid = self.party.currentData()
            with db(readonly=True) as conn:
                rows = sales_sets.pick_list(
                    conn, None if pid in (None, ALL) else pid,
                    dstr(self.d_from), dstr(self.d_to))
            if not rows:
                raise ValueError("لا فواتير مبيعات لهذه الجهة في الفترة")
            dlg = InvoicePicker(rows, self.chosen, self)
            if dlg.exec_() != QtWidgets.QDialog.Accepted:
                return
            self.chosen = dlg.chosen()
            self.show_sets()
        except Exception as e:
            err(self, e)

    def show_sets(self, ids=None):
        if ids is not None:
            self.chosen = list(ids)
        try:
            with db(readonly=True) as conn:
                self.rows = sales_sets.track(conn, self.chosen)
            sm = sales_sets.summary(self.rows)
            u = kv.unit()

            def nw(k):
                return f"{sm[k]['n']} طقم ({_nf.f2(kv.g(sm[k]['w']))} {u})"
            self.summary.setText(
                f"{nw('all')} في {sm['invoices']} فاتورة  —  مباع معه: "
                f"{nw('with')}  ·  مرتجع: {nw('returned')}، منها في الخزنة "
                f"{nw('ret_treasury')} وعند غيره {nw('ret_others')}"
                + (f"  ·  ملغاة بعكس: {nw('reversed')}"
                   if sm["reversed"]["n"] else ""))
            data = [(r["invoice_no"], r["date"], r["party"], r["wo_no"],
                     r["model_no"] or "—", _nf.f2(kv.g(r["weight"])),
                     r["status_label"],
                     (f"{r['ret_no']} · {r['ret_date']}" if r["ret_no"]
                      else "—"),
                     r["where"] or "—") for r in self.rows]
            fill(self.table, COLS, data)
            self.table.horizontalHeader().setSectionResizeMode(
                len(COLS) - 1, QtWidgets.QHeaderView.Stretch)
            self._tint()
        except Exception as e:
            err(self, e)

    def _tint(self):
        """الحال بلونها: الأخضر معه، والأحمر مرتجع."""
        col = COLS.index("الحال")
        colors = {sales_sets.WITH: "#1E7B45",
                  sales_sets.RETURNED: "#B4232A"}
        for i, r in enumerate(self.rows):
            c = colors.get(r["status"])
            it = self.table.item(i, col)
            if c and it is not None:
                it.setForeground(QtGui.QBrush(QtGui.QColor(c)))
                f = it.font()
                f.setBold(True)
                it.setFont(f)

    # ── الطباعة ──
    def print_report(self):
        try:
            if not self.chosen:
                raise ValueError("اختر الفواتير أولاً — «☑ اختر الفواتير…»")
            from services import print_manager
            print_manager.preview_document(
                self, "sales_sets", 0, invoice_ids=list(self.chosen))
        except Exception as e:
            err(self, e)
