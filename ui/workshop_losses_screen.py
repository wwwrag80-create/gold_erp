# -*- coding: utf-8 -*-
"""شاشة تسوية فواقد الورشة.

تُرحّل فاقد كل مرحلة تشغيلية لحسابه الخاص، فيُعرف نصيب البوليش من
الصب من الكاستنج… بدل رقم إجمالي واحد لا يقول شيئاً.

    مدين  حـ/ فاقد <النوع>      بالوزن
    دائن  حـ/ خزينة التصنيع     بالوزن نفسه
"""
from PyQt5 import QtCore, QtWidgets

from database.database import db
from services import karat_view as kv
from models import workshop_losses as wl
from services.accounting_engine import balance_by_code
from ui.widgets.common import (ask, big_label, confirm_post, date_edit, dstr,
                               err, fill, info, make_table, posted,
                               title_label, wspin)


class WorkshopLossesScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.types = []

        self.date = date_edit()
        self.doc_no = QtWidgets.QLineEdit()
        self.doc_no.setPlaceholderText("يُولَّد تلقائياً")
        self.doc_no.setMaximumWidth(140)
        self.kind = QtWidgets.QComboBox()
        self.kind.setMinimumWidth(200)
        self.weight = wspin()
        self.desc = QtWidgets.QLineEdit()
        self.desc.setPlaceholderText("البيان (اختياري)")

        btn_new_type = QtWidgets.QPushButton("➕ نوع فاقد جديد")
        btn_new_type.setToolTip(
            "يُنشئ حساباً جديداً تحت «فواقد الورشة» في الدليل تلقائياً")
        btn_new_type.clicked.connect(self.new_type)
        btn_post = QtWidgets.QPushButton("📥 ترحيل الفاقد")
        btn_post.setObjectName("homeBtn")
        btn_post.clicked.connect(self.save)

        form = QtWidgets.QHBoxLayout()
        form.addWidget(QtWidgets.QLabel("التاريخ:"))
        form.addWidget(self.date, 0)
        form.addWidget(QtWidgets.QLabel("رقم السند:"))
        form.addWidget(self.doc_no, 0)
        form.addWidget(QtWidgets.QLabel("نوع الفاقد:"))
        form.addWidget(self.kind, 0)
        form.addWidget(QtWidgets.QLabel(f"الوزن ({kv.unit()}):"))
        form.addWidget(self.weight, 0)
        form.addStretch(1)

        form2 = QtWidgets.QHBoxLayout()
        form2.addWidget(QtWidgets.QLabel("البيان:"))
        form2.addWidget(self.desc, 1)
        form2.addWidget(btn_new_type)
        form2.addWidget(btn_post)

        self.treasury = big_label()
        self.table = make_table()
        self.totals = big_label()

        btn_refresh = QtWidgets.QPushButton("↻ تحديث")
        btn_refresh.clicked.connect(self.refresh)
        btn_print = QtWidgets.QPushButton("🖨 طباعة السجل")
        btn_print.clicked.connect(self.print_log)
        btn_del = QtWidgets.QPushButton("🗑 حذف السند المحدد")
        btn_del.setObjectName("ghost")
        btn_del.setToolTip("يحذف السند ويعكس أثره المحاسبي معاً")
        btn_del.clicked.connect(self.delete_selected)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(btn_refresh)
        row.addWidget(btn_print)
        row.addWidget(btn_del)
        row.addStretch(1)

        note = QtWidgets.QLabel(
            "الفاقد خروج فعلي للذهب من خزينة التصنيع: يُرحَّل مديناً "
            "لحساب نوعه ودائناً لخزينة التصنيع — فيبقى ميزان الذهب "
            "متوازناً ويُعرف نصيب كل مرحلة من الفاقد.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("تسوية فواقد الورشة"))
        lay.addWidget(note)
        lay.addWidget(self.treasury)
        lay.addLayout(form)
        lay.addLayout(form2)
        lay.addLayout(row)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.totals)
        self.refresh()

    # ══════════ البيانات ══════════
    def delete_selected(self):
        """يحذف السند المحدد ويعكس قيده في معاملة واحدة."""
        try:
            i = self.table.currentRow()
            if not (0 <= i < len(getattr(self, "rows", []))):
                raise ValueError("اختر سنداً من الجدول")
            r = self.rows[i]
            if not ask(self,
                       f"حذف سند الفاقد {r['doc_no']}؟\n\n"
                       f"النوع: {r['acc_name']}\n"
                       f"الوزن: {kv.g(r['weight']):,.3f} {kv.unit()}\n\n"
                       f"سيُعكس القيد فيعود الوزن لخزينة التصنيع.\n"
                       f"لا يمكن التراجع."):
                return
            with db() as conn:
                d = wl.delete_loss(conn, r["id"], self.user["username"])
            info(self, f"حُذف السند {d['doc_no']}\n"
                       f"عاد {kv.g(d['weight']):,.3f} {kv.unit()} "
                       f"لخزينة التصنيع.")
            self.refresh()
        except Exception as e:
            err(self, e)

    def refresh(self):
        try:
            with db() as conn:
                # مزامنة: سندات حُذف قيدها من مكان آخر تُخفى هنا أيضاً
                wl.purge_orphans(conn, self.user["username"])
                self.types = wl.loss_types(conn)
                rows = wl.list_losses(conn)
                g, _c = balance_by_code(conn, "1100")
                self.doc_no.setPlaceholderText(wl.next_doc_no(conn))
            cur = self.kind.currentData()
            self.kind.clear()
            for t in self.types:
                self.kind.addItem(f"{t['code']} — {t['name']}", t["id"])
            if cur is not None:
                i = self.kind.findData(cur)
                if i >= 0:
                    self.kind.setCurrentIndex(i)
            self.treasury.setText(
                f"رصيد خزينة التصنيع: {kv.g(g):,.2f} جم {kv.label()}")
            self.rows = rows
            fill(self.table,
                 ["رقم السند", "التاريخ", "نوع الفاقد",
                  f"الوزن ({kv.unit()})", "البيان"],
                 [(r["doc_no"] or "—", r["loss_date"], r["acc_name"],
                   f"{kv.g(r['weight']):,.3f}", r["description"] or "")
                  for r in rows])
            tot = sum(float(r["weight"] or 0) for r in rows)
            self.totals.setText(
                f"{len(rows)} عملية   |   إجمالي الفاقد المُرحَّل: "
                f"{kv.g(tot):,.3f} {kv.unit()}")
        except Exception as e:
            err(self, e)

    # ══════════ الإجراءات ══════════
    def new_type(self):
        try:
            name, ok = QtWidgets.QInputDialog.getText(
                self, "نوع فاقد جديد",
                "اسم نوع الفاقد:\n(سيُنشأ له حساب تحت «فواقد الورشة»)")
            if not ok or not name.strip():
                return
            with db() as conn:
                r = wl.add_loss_type(conn, name.strip(),
                                     self.user["username"])
            info(self, f"أُنشئ نوع الفاقد «{r['name']}»\n"
                       f"رقم حسابه في الدليل: {r['code']}")
            self.refresh()
            i = self.kind.findData(r["id"])
            if i >= 0:
                self.kind.setCurrentIndex(i)
        except Exception as e:
            err(self, e)

    def save(self):
        try:
            aid = self.kind.currentData()
            if aid is None:
                raise ValueError("اختر نوع الفاقد")
            w = float(self.weight.value() or 0)
            if w <= 0:
                raise ValueError("أدخل وزن الفاقد")
            label = self.kind.currentText()
            if not confirm_post(
                    self, f"تسوية فاقد ورشة\n\n"
                          f"النوع: {label}\n"
                          f"الوزن: {w:,.3f} {kv.unit()}\n"
                          f"التاريخ: {dstr(self.date)}\n\n"
                          f"مدين  حـ/ {label.split('—')[-1].strip()}\n"
                          f"دائن  حـ/ خزينة التصنيع"):
                return
            with db() as conn:
                r = wl.create_loss(
                    conn, aid, kv.store(w), dstr(self.date),
                    self.user["username"],
                    self.desc.text().strip(),
                    doc_no=self.doc_no.text().strip() or None)
            posted(self, f"رُحّل الفاقد {r['doc_no']} — {r['account']} "
                         f"بوزن {kv.g(r['weight']):,.3f} {kv.unit()}",
                   "workshop_losses", r["id"])
            self.weight.setValue(0)
            self.desc.clear()
            self.doc_no.clear()
            self.refresh()
        except Exception as e:
            err(self, e)

    def print_log(self):
        try:
            from services import print_manager
            print_manager.preview_document(self, "workshop_losses_log", 0)
        except Exception as e:
            err(self, e)
