# -*- coding: utf-8 -*-
"""حوار تعديل عملية التوريد من كشف حساب خزينة التصنيع.

يفتح **العملية نفسها** المسجّلة مسبقاً بكل تفاصيلها، فتُعدَّل أوزانها
أو يُحذف الطقم كلياً — وينعكس الأثر محاسبياً في **الخزنتين معاً**:
خزينة التصنيع (المصدر) والذهب المشغول (الوجهة)، داخل معاملة واحدة
فلا يختلّ ميزان الذهب بينهما إطلاقاً.
"""
from PyQt5 import QtCore, QtWidgets

from database.database import db
from services import karat_view as kv
from models import operations
from services import gold_math
from ui.widgets.common import ask, big_label, err, fill, info, make_table, wspin


class SupplyEditDialog(QtWidgets.QDialog):
    def __init__(self, parent, wo_id, user):
        super().__init__(parent)
        self.wo_id = wo_id
        self.user = user
        self.setWindowTitle("تعديل عملية التوريد")
        self.setMinimumWidth(680)

        with db() as conn:
            wo = conn.execute(
                "SELECT * FROM work_orders WHERE id=?", (wo_id,)).fetchone()
            if not wo:
                raise ValueError("الطقم غير موجود")
            self.wo = dict(wo)
            entry = conn.execute(
                "SELECT * FROM journal_entries WHERE id=?",
                (wo["entry_id"],)).fetchone()
            self.entry = dict(entry) if entry else {}
            self.lines = [dict(r) for r in conn.execute(
                "SELECT a.code, a.name, l.gold_debit gd, l.gold_credit gc"
                " FROM journal_lines l JOIN accounts a ON a.id=l.account_id"
                " WHERE l.entry_id=?", (wo["entry_id"],)).fetchall()] \
                if entry else []
        self.rate = self.wo["discount_rate"]

        # ── بيانات العملية الأصلية ──
        info_box = QtWidgets.QGroupBox("العملية المسجّلة")
        gl = QtWidgets.QFormLayout(info_box)
        gl.addRow("رقم التشغيل:",
                  QtWidgets.QLabel(str(self.wo["work_order_no"])))
        gl.addRow("التاريخ:",
                  QtWidgets.QLabel(str(self.entry.get("entry_date", "—"))))
        gl.addRow("الحالة:", QtWidgets.QLabel(
            "متاح في المخزن" if self.wo["status"] == "in_stock"
            else "مباع"))

        # ── القيد الحالي ──
        self.jt = make_table()
        fill(self.jt, ["الحساب", "مدين (ذهب)", "دائن (ذهب)"],
             [(l["name"], f"{kv.g(l['gd']):,.2f}", f"{kv.g(l['gc']):,.2f}")
              for l in self.lines])
        self.jt.setMaximumHeight(150)

        # ── الحقول القابلة للتعديل ──
        # الحقول بعيار المصنع، والتخزين بمكافئ 18 عند الحفظ
        self.gold = wspin()
        self.gold.setValue(kv.g(self.wo["gold_weight"]))
        self.small = wspin()
        self.small.setValue(kv.g(self.wo["small_stones"]))
        self.big = wspin()
        self.big.setValue(kv.g(self.wo["big_stones"]))
        self.wage = wspin()
        self.wage.setValue(kv.rate(self.wo["wage_per_gram"]))
        for w in (self.gold, self.small, self.big):
            w.valueChanged.connect(self.recalc)
        self.notes = QtWidgets.QLineEdit()
        self.notes.setPlaceholderText("سبب التعديل (يُسجَّل في التدقيق)")

        edit_box = QtWidgets.QGroupBox("التعديل")
        fl = QtWidgets.QFormLayout(edit_box)
        fl.addRow(f"الذهب ({kv.unit()}):", self.gold)
        fl.addRow(f"الفصوص ({kv.unit()}):", self.small)
        fl.addRow(f"الأحجار ({kv.unit()}):", self.big)
        fl.addRow(f"الأجر/جم {kv.active()}:", self.wage)
        fl.addRow("السبب:", self.notes)

        self.preview = big_label("")
        self.preview.setWordWrap(True)

        btn_del = QtWidgets.QPushButton("🗑 حذف العملية نهائياً")
        btn_del.setObjectName("ghost")
        btn_del.clicked.connect(self.delete_supply)
        box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        box.accepted.connect(self.save)
        box.rejected.connect(self.reject)
        btns = QtWidgets.QHBoxLayout()
        btns.addWidget(btn_del)
        btns.addStretch(1)
        btns.addWidget(box)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(info_box)
        lay.addWidget(QtWidgets.QLabel("القيد المحاسبي الحالي:"))
        lay.addWidget(self.jt)
        lay.addWidget(edit_box)
        lay.addWidget(self.preview)
        lay.addLayout(btns)
        self.recalc()

    def recalc(self):
        """يعرض الأثر المتوقَّع على الخزنتين قبل الحفظ."""
        new_reg = gold_math.registered_weight(
            self.gold.value(), self.small.value(), self.big.value(), self.rate)
        old = kv.g(self.wo["registered_weight"])
        diff = round(new_reg - old, 2)
        u = kv.unit()
        self.preview.setText(
            f"الوزن المقيد: {old:,.2f} → {new_reg:,.2f} {u} "
            f"(فرق {diff:+,.2f})\n\n"
            f"الأثر المحاسبي:\n"
            f"   خزينة التصنيع  {-diff:+,.2f} {u}\n"
            f"   الذهب المشغول  {diff:+,.2f} {u}\n"
            f"يُعكس القيد القديم ويُرحَّل الجديد داخل معاملة واحدة.")

    def save(self):
        try:
            if self.wo["status"] != "in_stock":
                raise ValueError(
                    f"الطقم {self.wo['work_order_no']} مباع حالياً — "
                    f"أعد فاتورته أولاً ثم عدّل التوريد")
            with db() as conn:
                r = operations.edit_supply(
                    conn, self.wo_id, kv.store(self.gold.value()),
                    kv.store(self.small.value()),
                    kv.store(self.big.value()), self.user["username"],
                    wage_per_gram=kv.rate_store(self.wage.value()),
                    notes=self.notes.text().strip())
            info(self, f"عُدِّل توريد {r['wo_no']}.\n"
                       f"الوزن المقيد: {r['old_reg']:,.2f} → "
                       f"{r['new_reg']:,.2f} جم\n\n"
                       f"تحدّثت خزينة التصنيع والذهب المشغول معاً.")
            self.accept()
        except Exception as e:
            err(self, e)

    def delete_supply(self):
        """يحذف عملية التوريد ويعكس أثرها على الخزنتين."""
        try:
            if self.wo["status"] != "in_stock":
                raise ValueError("الطقم مباع — أعد فاتورته أولاً")
            if not ask(self,
                       f"حذف توريد {self.wo['work_order_no']} نهائياً؟\n\n"
                       f"سيُعكس القيد فتعود {self.wo['registered_weight']:,.2f}"
                       f" جم لخزينة التصنيع\n"
                       f"وتُخصم من الذهب المشغول.\n\n"
                       f"لا يمكن التراجع."):
                return
            from services.audit import reverse_entry
            from services.audit import log_action
            with db() as conn:
                if self.wo.get("entry_id"):
                    reverse_entry(conn, self.wo["entry_id"],
                                  self.user["username"])
                conn.execute("UPDATE work_orders SET is_deleted=1"
                             " WHERE id=?", (self.wo_id,))
                log_action(conn, self.user["username"], "soft_delete",
                           "work_orders", self.wo_id,
                           f"حذف توريد {self.wo['work_order_no']}"
                           + (f" | {self.notes.text().strip()}"
                              if self.notes.text().strip() else ""))
            info(self, "حُذفت العملية وعُكس أثرها على الخزنتين.")
            self.accept()
        except Exception as e:
            err(self, e)
