# -*- coding: utf-8 -*-
"""نافذة «⧉ دمج فواتير» من كشف الحساب (4.95).

فواتير المبيعات (أو المرتجع) الظاهرة في الكشف بعلامة اختيار، فتُختار
اثنتان أو أكثر من النوع نفسه، وتُختار «الفاتورة التي تبقى» برقمها
وتاريخها — فتنتقل إليها أطقم الأخرى وتُحذف تلك منطقياً. والفحص كله في
`models.operations.merge_invoices` داخل معاملةٍ واحدة: ما يكسر حركة طقمٍ
يُرفض بأسمائه ولا يُحفظ منه شيء.
"""
from PyQt5 import QtCore, QtWidgets

from ui import kit

from database.database import db
from models import operations
from services import karat_view as kv
from ui.widgets.common import ask, err, info, make_table

KINDS = (("sale", "المبيعات"), ("sale_return", "المرتجع"))


def candidates(conn, invoice_ids):
    """بيانات فواتير البيع والمرتجع من بين هذه — للعرض والاختيار."""
    ids = sorted({int(i) for i in invoice_ids if i})
    if not ids:
        return []
    q = ",".join("?" * len(ids))
    out = []
    for r in conn.execute(
            "SELECT i.id, i.invoice_no, i.kind, i.invoice_date,"
            " i.total_weight, i.total_wages, i.customer_id,"
            " (SELECT GROUP_CONCAT(w.work_order_no, '، ') FROM invoice_items"
            "  it JOIN work_orders w ON w.id=it.work_order_id"
            "  WHERE it.invoice_id=i.id) wos,"
            " (SELECT COUNT(*) FROM invoice_items it"
            "  WHERE it.invoice_id=i.id) n"
            f" FROM invoices i WHERE i.id IN ({q}) AND i.is_deleted=0"
            " AND i.kind IN ('sale','sale_return')"
            " ORDER BY i.invoice_date, i.id", ids):
        out.append(dict(r))
    return out


class MergeInvoicesDialog(QtWidgets.QDialog):
    COLS = ["✓", "رقم الفاتورة", "التاريخ", "عدد البنود",
            "الوزن", "الأجور", "أرقام التشغيل"]

    def __init__(self, parent, user, rows, preselect=()):
        super().__init__(parent)
        self.user = user
        self.rows = rows
        self.result_info = None
        self.setWindowTitle("دمج فواتير في فاتورةٍ واحدة")
        self.setMinimumSize(820, 480)
        self.setLayoutDirection(QtCore.Qt.RightToLeft)
        pre = {int(i) for i in preselect}
        first = next((r["kind"] for r in rows if r["id"] in pre), None)

        self.kind = kit.ComboBox()
        for k, t in KINDS:
            self.kind.addItem(t, k)
        if first:
            self.kind.setCurrentIndex(max(self.kind.findData(first), 0))
        self.kind.currentIndexChanged.connect(self._fill)
        self.table = make_table()
        self.table.itemChanged.connect(self._changed)
        self.keep = kit.ComboBox()
        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)
        note = QtWidgets.QLabel(
            "اختر فاتورتين أو أكثر من النوع نفسه لهذه الجهة. «الفاتورة التي"
            " تبقى» تحتفظ برقمها وتاريخها وتنتقل إليها أطقم الأخرى بأوزانها"
            " وأجورها، والأخرى تُحذف منطقياً. المخزون لا يتحرّك — وإن جعل"
            " تاريخُها حركةَ طقمٍ غير منتظمة رُفض الدمج كله.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        btn = kit.PushButton("⧉ دمج")
        btn.clicked.connect(self._merge)
        cancel = kit.PushButton("إلغاء")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("النوع:"))
        top.addWidget(self.kind)
        top.addStretch(1)
        bottom = QtWidgets.QHBoxLayout()
        bottom.addWidget(QtWidgets.QLabel("الفاتورة التي تبقى:"))
        bottom.addWidget(self.keep, 1)
        bottom.addStretch(1)
        bottom.addWidget(btn)
        bottom.addWidget(cancel)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(note)
        lay.addLayout(top)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.summary)
        lay.addLayout(bottom)
        self._pre = pre
        self._fill()

    def _shown(self):
        k = self.kind.currentData()
        return [r for r in self.rows if r["kind"] == k]

    def _fill(self, *_):
        rows = self._shown()
        self.table.blockSignals(True)
        try:
            self.table.clear()
            self.table.setColumnCount(len(self.COLS))
            self.table.setHorizontalHeaderLabels(self.COLS)
            self.table.setRowCount(len(rows))
            for i, r in enumerate(rows):
                chk = QtWidgets.QTableWidgetItem("")
                chk.setFlags(QtCore.Qt.ItemIsUserCheckable
                             | QtCore.Qt.ItemIsEnabled)
                chk.setCheckState(QtCore.Qt.Checked if r["id"] in self._pre
                                  else QtCore.Qt.Unchecked)
                chk.setData(QtCore.Qt.UserRole, r["id"])
                self.table.setItem(i, 0, chk)
                vals = (r["invoice_no"], r["invoice_date"], r["n"],
                        f"{kv.g(r['total_weight'] or 0):,.2f}",
                        f"{float(r['total_wages'] or 0):,.2f}",
                        r["wos"] or "")
                for c, v in enumerate(vals, start=1):
                    it = QtWidgets.QTableWidgetItem(str(v))
                    it.setFlags(QtCore.Qt.ItemIsEnabled
                                | QtCore.Qt.ItemIsSelectable)
                    it.setTextAlignment(QtCore.Qt.AlignCenter)
                    if c == 6:
                        it.setToolTip(str(v))
                    self.table.setItem(i, c, it)
            self.table.resizeColumnsToContents()
            self.table.horizontalHeader().setStretchLastSection(True)
        finally:
            self.table.blockSignals(False)
        self._changed()

    def checked_ids(self):
        out = []
        for i in range(self.table.rowCount()):
            it = self.table.item(i, 0)
            if it is not None and it.checkState() == QtCore.Qt.Checked:
                out.append(int(it.data(QtCore.Qt.UserRole)))
        return out

    def _changed(self, *_):
        ids = self.checked_ids()
        sel = [r for r in self._shown() if r["id"] in ids]
        cur = self.keep.currentData()
        self.keep.blockSignals(True)
        self.keep.clear()
        for r in sel:                       # الأقدم أولاً — والافتراضي
            self.keep.addItem(f"{r['invoice_no']} — {r['invoice_date']}",
                              r["id"])
        if cur in ids:
            self.keep.setCurrentIndex(self.keep.findData(cur))
        self.keep.blockSignals(False)
        n = sum(int(r["n"] or 0) for r in sel)
        w = sum(float(r["total_weight"] or 0) for r in sel)
        g = sum(float(r["total_wages"] or 0) for r in sel)
        self.summary.setText(
            f"المختار: {len(sel)} فاتورة · {n} بنداً · الوزن "
            f"{kv.g(w):,.2f} {kv.unit()} · الأجور {g:,.2f} ريال"
            if sel else "لم تُختر فواتير بعد")

    def _merge(self):
        ids = self.checked_ids()
        keep = self.keep.currentData()
        try:
            with db(readonly=True) as conn:
                operations.merge_check(conn, ids)
            nos = [r["invoice_no"] for r in self._shown() if r["id"] in ids]
            keep_no = next((r["invoice_no"] for r in self._shown()
                            if r["id"] == keep), "")
            if not ask(self, f"دمج الفواتير {'، '.join(nos)} في الفاتورة "
                             f"{keep_no}؟\n\nتنتقل إليها الأطقم كلها بتاريخها،"
                             " وتُحذف الأخرى منطقياً. يمكن مراجعة العملية في"
                             " «سجل العمليات»."):
                return
            with db() as conn:
                self.result_info = operations.merge_invoices(
                    conn, ids, self.user["username"], keep_id=keep)
        except Exception as e:
            err(self, e)
            return
        r = self.result_info
        info(self, f"دُمجت {'، '.join(r['merged'])} في الفاتورة "
                   f"{r['invoice_no']} ({r['invoice_date']}) — "
                   f"{r['items']} بنداً.", "تم الدمج")
        self.accept()
