# -*- coding: utf-8 -*-
"""نافذة كشف «ايطالي / نواعم» — الرقمان التجميعيان 0010 و00010 (5.1.9).

كل حركة سطر: توريدٌ من خزينة التصنيع، أو بيعٌ إلى عميل، أو مرتجعٌ منه —
بالمدين (الوارد) والدائن (الصادر) والرصيد الجاري، وصفّ إجمالي آخر
الجدول. وتُفتح فاتورة السطر أو دفعته بنقرتين. (`models.italian`)
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from models import italian
from services import karat_view as kv
from services import numfmt as _nf
from ui import kit
from ui.widgets.common import (date_edit, dstr, err, make_table, fill,
                               style_total_item)

COLS = ["التاريخ", "العملية", "المستند", "الرقم", "من / إلى",
        "وارد (مدين)", "صادر (دائن)", "الرصيد"]


class ItalianStatementDialog(QtWidgets.QDialog):
    def __init__(self, parent, date_from=None, date_to=None):
        super().__init__(parent)
        self.setWindowTitle("كشف ايطالي / نواعم — 0010 · 00010")
        self.setMinimumSize(980, 560)
        self._rows = []

        self.use_dates = QtWidgets.QCheckBox("فترة:")
        self.d1 = date_edit()
        self.d2 = date_edit()
        if date_from:
            self.d1.setDate(QtCore.QDate.fromString(date_from, "yyyy-MM-dd"))
        else:
            self.d1.setDate(QtCore.QDate.currentDate().addMonths(-1))
        if date_to:
            self.d2.setDate(QtCore.QDate.fromString(date_to, "yyyy-MM-dd"))
        self.use_dates.setChecked(bool(date_from or date_to))
        for w in (self.d1, self.d2):
            w.dateChanged.connect(self.load)
        self.use_dates.toggled.connect(self.load)
        btn_print = kit.PushButton("🖨 طباعة")
        btn_print.clicked.connect(self.print_)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.use_dates)
        top.addWidget(QtWidgets.QLabel("من"))
        top.addWidget(self.d1)
        top.addWidget(QtWidgets.QLabel("إلى"))
        top.addWidget(self.d2)
        top.addStretch(1)
        top.addWidget(btn_print)

        self.head = QtWidgets.QLabel()
        self.head.setObjectName("cardSub")
        self.head.setWordWrap(True)
        self.table = make_table()
        self.table.cellDoubleClicked.connect(self._open_row)
        self.note = QtWidgets.QLabel()
        self.note.setWordWrap(True)
        self.note.setObjectName("cardSub")

        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.head)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.note)
        self.load()

    def _dates(self):
        if not self.use_dates.isChecked():
            return None, None
        return dstr(self.d1), dstr(self.d2)

    def load(self, *_):
        try:
            d1, d2 = self._dates()
            with db(readonly=True) as conn:
                st = italian.statement(conn, d1, d2)
            self._st = st
            g = lambda v: _nf.f2(kv.g(v))          # noqa: E731
            data, self._rows = [], []
            if st["date_from"]:
                data.append(("", "رصيد أول الفترة", "", "", "", "", "",
                             g(st["opening"])))
                self._rows.append(None)
            for r in st["rows"]:
                data.append((r["date"] or "—", r["label"], r["doc"] or "—",
                             r["no"] or "—", r["party"],
                             g(r["debit"]) if r["debit"] else "—",
                             g(r["credit"]) if r["credit"] else "—",
                             g(r["balance"])))
                self._rows.append(r)
            data.append(("الإجمالي", "", "", "", "", g(st["debit"]),
                         g(st["credit"]), g(st["closing"])))
            u = kv.unit()
            fill(self.table, COLS, data)
            # كل عمودٍ بقدر نصّه، و«من / إلى» يأخذ الباقي — فلا يُقصّ شيء
            hh = self.table.horizontalHeader()
            for c in range(self.table.columnCount()):
                hh.setSectionResizeMode(
                    c, QtWidgets.QHeaderView.Stretch if c == 4
                    else QtWidgets.QHeaderView.ResizeToContents)
            last = self.table.rowCount() - 1
            for c in range(self.table.columnCount()):
                it = self.table.item(last, c)
                if it is not None:
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                    try:
                        style_total_item(it)
                    except Exception:
                        pass
            for i, r in enumerate(self._rows):
                if r and r["kind"] == "open":
                    for c in range(self.table.columnCount()):
                        it = self.table.item(i, c)
                        if it is not None:
                            it.setForeground(QtGui.QColor("#9a6b00"))
            n = st["counts"]
            per = "   ·   ".join(f"{c['no']}: {g(c['balance'])} {u}"
                                 for c in st["cards"]) or "لا رصيد"
            self.head.setText(
                f"الرصيد الآن — {per}   |   في الكشف: {n['supply']} توريد ·"
                f" {n['sale']} بيع · {n['return']} مرتجع   |   الأوزان:"
                f" {u}")
            msg = ("المدين: ما ورد من خزينة التصنيع وما رجع من العملاء ·"
                   " الدائن: ما بِيع للعملاء. انقر على سطرٍ مرتين لفتح"
                   " فاتورته أو دفعته.")
            if abs(st["gap"]) > 0.005:
                msg += (f"\n«رصيد سابق غير مفصّل» {g(st['gap'])} {u}: رصيدٌ"
                        " على الرقمين لا تقابله مستنداتٌ مفصّلة في النظام"
                        " (دخل قبل حفظ تفصيل الدفعات، أو من تعديلٍ قديم). يُعرض"
                        " ليتطابق آخر الكشف مع لوحة التحكم ودليل الموديلات.")
            self.note.setText(msg)
        except Exception as e:
            err(self, e)

    def _open_row(self, row, _col):
        r = self._rows[row] if 0 <= row < len(self._rows) else None
        if not r or not r.get("ref"):
            return
        kind, rid = r["ref"]
        try:
            win = self.window().parent() or self.parent()
            mw = win.window() if win else None
            opener = getattr(mw, "open_document_for_edit", None)
            if kind == "invoice":
                from services import print_manager
                print_manager.preview_document(self, "invoice", rid)
            elif opener:
                with db(readonly=True) as conn:
                    w = conn.execute(
                        "SELECT id FROM work_orders WHERE entry_id=?"
                        " AND is_deleted=0 ORDER BY id LIMIT 1",
                        (rid,)).fetchone()
                if w:
                    opener("work_orders", w["id"])
        except Exception as e:
            err(self, e)

    def print_(self):
        try:
            from services import print_manager
            d1, d2 = self._dates()
            print_manager.preview_document(self, "italian_statement", 0,
                                           date_from=d1, date_to=d2)
        except Exception as e:
            err(self, e)
