# -*- coding: utf-8 -*-
"""كشف الأرصدة المجمعة للجهات (Entities Balances Summary).

اختر الفئة — عملاء، موردون، شركاء، موظفون، جهات أخرى — ليعرض الجدول
كل جهات الفئة بأرصدتها النقدية والوزنية ومعلومات التواصل، مع زر
«كشف حساب» داخل كل صف ينقلك مباشرة إلى حركات تلك الجهة التفصيلية،
وزر لطباعة القائمة كاملة PDF لتقديمها للإدارة."""
from PyQt5 import QtWidgets

from database.database import db
from models import coa, entities
from PyQt5 import QtCore


from ui.widgets.common import (Card, cell, err, fill, info,
                               make_table, title_label)

CATEGORIES = [("إجمالي العملاء", "customer"), ("إجمالي الموردين", "supplier"),
              ("الشركاء", "partner"), ("الموظفون", "employee"),
              ("العمال", "worker"),
              ("الجهات الأخرى (مدينون آخرون)", "other")]


class SubLedgerScreen(QtWidgets.QWidget):
    def __init__(self, user, on_drill_account=None):
        super().__init__()
        self.user = user
        self.on_drill_account = on_drill_account
        self._rows = []

        self.category = QtWidgets.QComboBox()
        for label, val in CATEGORIES:
            self.category.addItem(label, val)
        self.category.currentIndexChanged.connect(self.refresh)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("بحث بالاسم داخل الفئة…")
        self.search.textChanged.connect(self.render)

        head = QtWidgets.QHBoxLayout()
        head.addWidget(QtWidgets.QLabel("حساب المراقبة التجميعي:"))
        head.addWidget(self.category)
        head.addWidget(self.search, 1)

        self.c_count = Card("عدد الجهات المسجلة", "في هذه الفئة")
        self.c_cash = Card("إجمالي الرصيد النقدي", "ريال — موجب مدين / سالب دائن")
        self.c_gold = Card("إجمالي الرصيد الوزني", "جم عيار 18")
        cards = QtWidgets.QHBoxLayout()
        for c in (self.c_count, self.c_cash, self.c_gold):
            cards.addWidget(c)

        self.table = make_table()
        self.table.doubleClicked.connect(self.open_ledger)
        btn = QtWidgets.QPushButton("فتح دفتر الأستاذ للجهة المحددة")
        btn.setObjectName("ghost")
        btn.clicked.connect(self.open_ledger)
        btn_rename = QtWidgets.QPushButton("✎ تعديل الاسم")

        btn_rename.setToolTip("يعدّل اسم الجهة وحسابها معاً")

        btn_rename.clicked.connect(self.rename_selected)
        btn_print = QtWidgets.QPushButton("🖨 معاينة/طباعة قائمة الأرصدة (PDF)")
        btn_print.clicked.connect(self.print_report)
        btn_pdf = QtWidgets.QPushButton("💾 حفظ القائمة PDF")
        btn_pdf.setObjectName("ghost")
        btn_pdf.clicked.connect(self.save_pdf)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label(
            "كشف الأرصدة المجمعة للجهات — أرصدة نقدية ووزنية"))
        lay.addLayout(head)
        lay.addLayout(cards)
        lay.addWidget(self.table, 1)
        brow = QtWidgets.QHBoxLayout()
        brow.addWidget(btn)
        brow.addStretch(1)
        brow.addWidget(btn_rename)
        brow.addWidget(btn_print)
        brow.addWidget(btn_pdf)
        lay.addLayout(brow)
        note = QtWidgets.QLabel(
            "الموجب = مدين (على الجهة لصالح المصنع) | السالب = دائن (للجهة "
            "على المصنع). أرصدة الشركاء تشمل الجاري ورأس المال معاً في "
            "الإجمالي، وتُفصَّل في الجدول.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)

    def open_ledger(self):
        r = self.table.currentRow()
        if r < 0 or not self.on_drill_account:
            return
        visible = self._visible_rows()
        if r < len(visible):
            self.on_drill_account(visible[r]["account_id"])

    def _visible_rows(self):
        q = self.search.text().strip()
        if not q:
            return self._rows
        nq = entities.normalize_name(q)
        return [d for d in self._rows
                if nq in entities.normalize_name(d["name"])]

    def render(self):
        cat = self.category.currentData()
        vis = self._visible_rows()
        if cat == "partner":
            headers = ["الشريك", "الجوال", "جاري — نقد", "جاري — ذهب",
                      "رأس المال — نقد", "رأس المال — ذهب", "إجراءات"]
            data = [(d["name"], d["phone"] or "—", f"{d['cash']:,.2f}",
                     f"{d['gold']:,.2f}", f"{d['cap_cash']:,.2f}",
                     f"{d['cap_gold']:,.2f}") for d in vis]
        else:
            headers = ["الاسم", "الجوال", "الرصيد النقدي", "الحالة النقدية",
                      "رصيد الذهب (جم 18)", "الحالة الوزنية", "إجراءات"]
            data = []
            for d in vis:
                cs = ("مدين" if d["cash"] > 0 else
                      ("دائن" if d["cash"] < 0 else "متزن"))
                gs = ("مدين" if d["gold"] > 0 else
                      ("دائن" if d["gold"] < 0 else "متزن"))
                data.append((d["name"], d["phone"] or "—",
                             f"{d['cash']:,.2f}", cs,
                             f"{d['gold']:,.2f}", gs))
        self.table.setRowCount(0)
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        for i, row in enumerate(data):
            self.table.insertRow(i)
            for c, v in enumerate(row):
                it = QtWidgets.QTableWidgetItem(str(v))
                it.setTextAlignment(QtCore.Qt.AlignCenter)
                self.table.setItem(i, c, it)
            self.table.setCellWidget(i, len(headers) - 1,
                                    self._ledger_btn(vis[i]))
        self.table.resizeColumnsToContents()

    def _ledger_btn(self, d):
        """زر «كشف حساب» داخل كل صف — تعمّق فوري لحركات الجهة."""
        b = QtWidgets.QPushButton("📄 كشف حساب")
        b.setObjectName("ghost")
        b.clicked.connect(
            lambda _, acc=d["account_id"]: self.on_drill_account(acc)
            if self.on_drill_account else None)
        return b

    def print_report(self):
        from services import print_manager
        try:
                        print_manager.preview_document(
                self, "balances", self.category.currentData(),
                rows=self._visible_rows())
        except Exception as e:
            err(self, e)

    def save_pdf(self):
        from services import print_manager
        try:
            path = print_manager.export_pdf_dialog(
                self, "balances", self.category.currentData(),
                suggested=f"أرصدة {self.category.currentText()}",
                rows=self._visible_rows())
            if path:
                info(self, f"تم حفظ التقرير:\n{path}")
        except Exception as e:
            err(self, e)

    def rename_selected(self):
        """يعدّل اسم الجهة المحددة — والاسم يتزامن مع حسابها."""
        try:
            i = self.table.currentRow()
            rows = self._visible_rows()
            if not (0 <= i < len(rows)):
                raise ValueError("اختر جهة من الجدول أولاً")
            r = rows[i]
            cur = r.get("name") if isinstance(r, dict) else r["name"]
            new, ok = QtWidgets.QInputDialog.getText(
                self, "تعديل الاسم",
                f"الاسم الحالي: {cur}\n\nالاسم الجديد:", text=str(cur))
            if not ok or not str(new).strip():
                return
            eid = r.get("id") if isinstance(r, dict) else r["id"]
            with db() as conn:
                ent = conn.execute(
                    "SELECT account_id FROM entities WHERE id=?",
                    (eid,)).fetchone()
                if not ent:
                    raise ValueError("الجهة غير موجودة")
                acc = conn.execute(
                    "SELECT name FROM accounts WHERE id=?",
                    (ent["account_id"],)).fetchone()
                # نُبقي البادئة الوصفية («عميل: » مثلاً) كما هي
                old_full = acc["name"] if acc else ""
                pre = ""
                for p_ in ("عميل: ", "مورد: ", "موظف: ", "عامل: ",
                           "أخرى: ", "شريك: "):
                    if old_full.startswith(p_):
                        pre = p_
                        break
                coa.rename_account(conn, ent["account_id"],
                                   pre + str(new).strip(),
                                   self.user["username"])
            info(self, f"عُدّل الاسم إلى «{str(new).strip()}»\n"
                       f"وتزامن مع حسابه في دليل الحسابات.")
            self.refresh()
        except Exception as e:
            err(self, e)

    def refresh(self):
        try:
            cat = self.category.currentData()
            with db(readonly=True) as conn:
                summary, details = entities.subledger_summary(conn, cat)
            self._rows = details
            self.c_count.set_value(str(summary["count"]),
                                  f"فئة: {self.category.currentText()}")
            self.c_cash.set_value(f"{summary['total_cash']:,.2f}",
                                 "إجمالي الفئة — ريال")
            self.c_gold.set_value(f"{summary['total_gold']:,.2f}",
                                 "إجمالي الفئة — جم عيار 18")
            self.render()
        except Exception as e:
            err(self, e)
