# -*- coding: utf-8 -*-
"""أعمار الديون — توزيع أرصدة الجهات على فئات عمرية (30/60/90 يوماً).

الرصيد رقمٌ واحد لا يقول شيئاً عن خطورته: مئة ألف عمرها أسبوع غير
مئة ألف عمرها سنة. هذه الشاشة تُظهر أيّ الديون تأخّرت وكم، وتُبرز
أقدمها أولاً.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from models import aging
from services import karat_view as kv
from ui.widgets.common import (Card, big_label, date_edit, dstr, err,
                               make_table, title_label)
from ui.widgets.table_fit import fit_columns

TYPES = [("العملاء", "customer"), ("الموردون", "supplier"),
         ("جهات أخرى", "other")]


class AgingScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.rows = []

        self.kind = QtWidgets.QComboBox()
        self.kind.setMaximumWidth(140)
        for label, val in TYPES:
            self.kind.addItem(label, val)
        self.kind.currentIndexChanged.connect(self.refresh)
        self.as_of = date_edit()
        self.dim = QtWidgets.QComboBox()
        self.dim.setMaximumWidth(150)
        self.dim.addItem("نقد وذهب معاً", "both")
        self.dim.addItem("النقد فقط", "cash")
        self.dim.addItem("الذهب فقط", "gold")
        self.dim.currentIndexChanged.connect(self.render)
        btn = QtWidgets.QPushButton("عرض")
        btn.clicked.connect(self.refresh)
        btn_print = QtWidgets.QPushButton("👁 معاينة وطباعة")
        btn_print.clicked.connect(self.print_report)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(QtWidgets.QLabel("الفئة:"))
        head.addWidget(self.kind, 0)
        head.addWidget(QtWidgets.QLabel("حتى تاريخ:"))
        head.addWidget(self.as_of, 0)
        head.addWidget(QtWidgets.QLabel("البعد:"))
        head.addWidget(self.dim, 0)
        head.addWidget(btn, 0)
        head.addStretch(1)
        head.addWidget(btn_print, 0)

        self.c_count = Card("عدد الجهات المدينة", "لها رصيد قائم")
        self.c_cur = Card("جارٍ (0 – 30)", "ريال")
        self.c_late = Card("متأخر (31 – 90)", "ريال")
        self.c_bad = Card("متعثّر (أكثر من 90)", "ريال")
        cards = QtWidgets.QHBoxLayout()
        cards.setSpacing(4)
        for c in (self.c_count, self.c_cur, self.c_late, self.c_bad):
            cards.addWidget(c)

        self.table = make_table()
        self.note = big_label()

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        lay.addWidget(title_label(
            "أعمار الديون — توزيع الأرصدة على فئات عمرية بطريقة "
            "«الأقدم فالأقدم»"))
        lay.addLayout(head)
        lay.addWidget(self.table, 1)
        lay.addLayout(cards)
        lay.addWidget(self.note)
        hint = QtWidgets.QLabel(
            "كل مدين يفتح دفعة بتاريخها، وكل دائن يُسدّد أقدم الدفعات "
            "المفتوحة أولاً — وهو المتّبع محاسبياً ما لم يخصّص العميل "
            "دفعته. الرصيد الدائن (له علينا) لا عمر له فيُعرض مستقلاً.")
        hint.setObjectName("cardSub")
        hint.setWordWrap(True)
        lay.addWidget(hint)

    # ══════════════════════════════════════════════════════════════

    def refresh(self):
        try:
            with db(readonly=True) as conn:
                self.rows = aging.report(conn, self.kind.currentData(),
                                         dstr(self.as_of))
            self.render()
        except Exception as e:
            err(self, e)

    def _headers(self, dim):
        cols = ["الجهة", "الجوال", "أقدم دين (يوم)"]
        if dim in ("both", "cash"):
            cols += [f"نقد {b}" for b in aging.BUCKET_LABELS]
            cols += ["إجمالي النقد"]
        if dim in ("both", "gold"):
            cols += [f"ذهب {b}" for b in aging.BUCKET_LABELS]
            cols += [f"إجمالي الذهب ({kv.unit()})"]
        cols += ["له علينا"]
        return cols

    def _row_cells(self, r, dim):
        out = [r["name"], r["phone"] or "—",
               str(r["days"]) if r["days"] else "—"]
        if dim in ("both", "cash"):
            out += [f"{x:,.2f}" if x else "" for x in r["cash_buckets"]]
            out += [f"{r['cash']:,.2f}" if r["cash"] else ""]
        if dim in ("both", "gold"):
            out += [f"{kv.g(x):,.3f}" if x else ""
                    for x in r["gold_buckets"]]
            out += [f"{kv.g(r['gold']):,.3f}" if r["gold"] else ""]
        cr = []
        if r["cash_credit"]:
            cr.append(f"نقد {abs(r['cash_credit']):,.2f}")
        if r["gold_credit"]:
            cr.append(f"ذهب {kv.g(abs(r['gold_credit'])):,.3f}")
        out.append(" · ".join(cr) or "—")
        return out

    def render(self):
        dim = self.dim.currentData() or "both"
        headers = self._headers(dim)
        rows = self.rows
        t = aging.totals(rows)

        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        try:
            self.table.setColumnCount(len(headers))
            self.table.setHorizontalHeaderLabels(headers)
            self.table.setRowCount(len(rows) + (1 if rows else 0))
            for i, r in enumerate(rows):
                for c, v in enumerate(self._row_cells(r, dim)):
                    it = QtWidgets.QTableWidgetItem(str(v))
                    it.setTextAlignment(QtCore.Qt.AlignCenter)
                    # المتعثّر يُلوَّن: العين تلتقطه قبل أن تقرأ الأرقام
                    if r["days"] >= 91:
                        it.setForeground(QtGui.QColor("#B02A2A"))
                    elif r["days"] >= 61:
                        it.setForeground(QtGui.QColor("#8A6D1D"))
                    self.table.setItem(i, c, it)
            if rows:
                tot = ["الإجمالي", "—", "—"]
                if dim in ("both", "cash"):
                    tot += [f"{x:,.2f}" for x in t["cash_buckets"]]
                    tot += [f"{t['cash']:,.2f}"]
                if dim in ("both", "gold"):
                    tot += [f"{kv.g(x):,.3f}" for x in t["gold_buckets"]]
                    tot += [f"{kv.g(t['gold']):,.3f}"]
                tot.append(f"نقد {abs(t['cash_credit']):,.2f}")
                last = len(rows)
                for c, v in enumerate(tot):
                    it = QtWidgets.QTableWidgetItem(str(v))
                    it.setTextAlignment(QtCore.Qt.AlignCenter)
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                    try:
                        it.setBackground(QtGui.QColor("#EFE9DC"))
                    except Exception:
                        pass
                    self.table.setItem(last, c, it)
        finally:
            self.table.setUpdatesEnabled(True)
        fit_columns(self.table)

        self.c_count.set_value(f"{t['count']:,}")
        self.c_cur.set_value(f"{t['cash_buckets'][0]:,.2f}",
                             f"{t['cash_pct'][0]:.1f}% من الإجمالي")
        late = t["cash_buckets"][1] + t["cash_buckets"][2]
        self.c_late.set_value(
            f"{late:,.2f}",
            f"{(t['cash_pct'][1] + t['cash_pct'][2]):.1f}% من الإجمالي")
        self.c_bad.set_value(f"{t['cash_buckets'][3]:,.2f}",
                             f"{t['cash_pct'][3]:.1f}% من الإجمالي")
        worst = rows[0] if rows else None
        self.note.setText(
            (f"أقدم دين: {worst['name']} منذ {worst['days']} يوماً "
             f"({worst['oldest']})" if worst else
             "لا توجد أرصدة قائمة في هذه الفئة."))

    def print_report(self):
        from services import print_manager
        try:
            print_manager.preview_document(
                self, "aging", 0, entity_type=self.kind.currentData(),
                as_of=dstr(self.as_of), dim=self.dim.currentData())
        except Exception as e:
            err(self, e)
