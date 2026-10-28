# -*- coding: utf-8 -*-
"""شاشة تسوية فواقد الورشة — عمليات خزينة التصنيع (4.77).

كل عمليةٍ طرفُها خزينة التصنيع:

    صرف (فاقد خرج):        مدين حـ/ <الحساب>         ·  دائن حـ/ خزينة التصنيع
    قبض (ذهب عاد للخزينة):  مدين حـ/ خزينة التصنيع    ·  دائن حـ/ <الحساب>

الحساب أيُّ حسابٍ من الدليل بالبحث، و«+ إضافة حساب» يُنشئ جديداً تحت
«فواقد الورشة»،
ولكل عمليةٍ سندُها المطبوع (سند صرف · سند قبض) من الجدول بنقرةٍ مزدوجة.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from ui import kit

from database.database import db
from services import karat_view as kv
from models import workshop_losses as wl
from services.accounting_engine import balance_by_code
from ui.widgets.common import (ask, big_label, confirm_post, date_edit, dstr,
                               err, fill, info, make_table, posted,
                               reload_combo, search_combo, title_label, wspin)
from services import numfmt as _nf
from ui.widgets.common import guard_click

KIND_ITEMS = (("payment", "صرف — يخرج الذهب من خزينة التصنيع"),
              ("receipt", "قبض — يعود الذهب إلى خزينة التصنيع"))


class WorkshopLossesScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.types = []
        self.rows = []

        # ── العملية ──
        self.kind = kit.ComboBox()
        for k, label in KIND_ITEMS:
            self.kind.addItem(label, k)
        self.kind.setMinimumWidth(260)
        self.kind.currentIndexChanged.connect(self._preview)
        self.date = date_edit()
        self.doc_no = kit.LineEdit()
        self.doc_no.setPlaceholderText("يُولَّد تلقائياً")
        self.doc_no.setMaximumWidth(140)

        # ── الحساب: أي حسابٍ من الدليل بالبحث (4.78) ──
        self.account = search_combo("اكتب رقم الحساب أو اسمه…")
        self.account.setMinimumWidth(300)
        self.account.currentIndexChanged.connect(self._preview)
        btn_add_acc = kit.PushButton("➕ إضافة حساب")
        btn_add_acc.setToolTip(
            "يُنشئ حساباً جديداً تحت «فواقد الورشة» في الدليل تلقائياً")
        btn_add_acc.clicked.connect(self.new_account)
        self.weight = wspin()
        self.weight.valueChanged.connect(self._preview)
        self.desc = kit.LineEdit()
        self.desc.setPlaceholderText("البيان (اختياري)")

        self.btn_post = kit.PushButton("📤 ترحيل الصرف")
        self.btn_post.setObjectName("homeBtn")
        self.btn_post.clicked.connect(self.save)

        r1 = QtWidgets.QHBoxLayout()
        r1.addWidget(QtWidgets.QLabel("العملية:"))
        r1.addWidget(self.kind, 0)
        r1.addWidget(QtWidgets.QLabel("التاريخ:"))
        r1.addWidget(self.date, 0)
        r1.addWidget(QtWidgets.QLabel("رقم السند:"))
        r1.addWidget(self.doc_no, 0)
        r1.addStretch(1)

        r2 = QtWidgets.QHBoxLayout()
        r2.addWidget(QtWidgets.QLabel("الحساب:"))
        r2.addWidget(self.account, 0)
        r2.addWidget(btn_add_acc)
        r2.addWidget(QtWidgets.QLabel(f"الوزن ({kv.unit()}):"))
        r2.addWidget(self.weight, 0)
        r2.addWidget(QtWidgets.QLabel("البيان:"))
        r2.addWidget(self.desc, 1)
        r2.addWidget(self.btn_post)

        # القيد قبل ترحيله — يتبع العملية والحساب والوزن
        self.effect = QtWidgets.QLabel()
        self.effect.setObjectName("cardSub")

        form = QtWidgets.QFrame()
        form.setObjectName("card")
        fl = QtWidgets.QVBoxLayout(form)
        fl.addLayout(r1)
        fl.addLayout(r2)
        fl.addWidget(self.effect)

        self.treasury = big_label()
        self.table = make_table()
        self.table.doubleClicked.connect(guard_click(lambda *_: self.print_selected()))
        self.totals = big_label()

        btn_refresh = kit.PushButton("↻ تحديث")
        btn_refresh.clicked.connect(self.refresh)
        btn_doc = kit.PushButton("🖨 طباعة السند المحدد")
        btn_doc.setToolTip("قالب السند: سند صرف أو سند قبض — خزينة التصنيع"
                           " (أو نقرة مزدوجة على السطر)")
        btn_doc.clicked.connect(self.print_selected)
        btn_print = kit.PushButton("🖨 طباعة السجل")
        btn_print.clicked.connect(self.print_log)
        btn_del = kit.PushButton("🗑 حذف السند المحدد")
        btn_del.setObjectName("ghost")
        btn_del.setToolTip("يحذف السند ويعكس أثره المحاسبي معاً")
        btn_del.clicked.connect(self.delete_selected)
        row = QtWidgets.QHBoxLayout()
        for b in (btn_refresh, btn_doc, btn_print, btn_del):
            row.addWidget(b)
        row.addStretch(1)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("تسوية فواقد الورشة — عمليات خزينة التصنيع"))
        lay.addWidget(self.treasury)
        lay.addWidget(form)
        lay.addLayout(row)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.totals)
        self.refresh()

    # ══════════ العرض ══════════
    def _kind(self):
        return self.kind.currentData() or "payment"

    def _preview(self, *_):
        pay = self._kind() == "payment"
        self.btn_post.setText("📤 ترحيل الصرف" if pay else "📥 ترحيل القبض")
        acc = self.account.currentText().split("—")[-1].strip() or "الحساب"
        w = float(self.weight.value() or 0)
        amt = f"{_nf.f2(w)} {kv.unit()}" if w else "بالوزن"
        if pay:
            self.effect.setText(
                f"القيد:  مدين حـ/ {acc}  ·  دائن حـ/ خزينة التصنيع  — {amt}"
                "   (الذهب يخرج من الخزينة)")
        else:
            self.effect.setText(
                f"القيد:  مدين حـ/ خزينة التصنيع  ·  دائن حـ/ {acc}  — {amt}"
                "   (الذهب يعود إلى الخزينة)")

    def refresh(self):
        try:
            with db() as conn:
                # مزامنة: سندات حُذف قيدها من مكان آخر تُخفى هنا أيضاً
                wl.purge_orphans(conn, self.user["username"])
                self.types = wl.accounts(conn)
                rows = wl.list_losses(conn)
                g, _c = balance_by_code(conn, "1100")
                self.doc_no.setPlaceholderText(wl.next_doc_no(conn))
            reload_combo(self.account, self.types,
                         lambda t: f"{t['code']} — {t['name']}")
            self.treasury.setText(
                f"رصيد خزينة التصنيع: {_nf.f2(kv.g(g))} جم {kv.label()}")
            self.rows = rows
            fill(self.table,
                 ["رقم السند", "التاريخ", "العملية", "الحساب",
                  f"الوزن ({kv.unit()})", "البيان"],
                 [(r["doc_no"] or "—", r["loss_date"],
                   wl.KINDS.get(r.get("kind") or "payment", "صرف"),
                   r["acc_name"], f"{_nf.f2(kv.g(r['weight']))}",
                   r["description"] or "")
                  for r in rows])
            red, green = QtGui.QColor("#9A1414"), QtGui.QColor("#1E6B33")
            for i, r in enumerate(rows):
                it = self.table.item(i, 2)
                if it is not None:
                    it.setForeground(green if r.get("kind") == "receipt"
                                     else red)
            pay = sum(float(r["weight"] or 0) for r in rows
                      if (r.get("kind") or "payment") == "payment")
            rec = sum(float(r["weight"] or 0) for r in rows
                      if r.get("kind") == "receipt")
            u = kv.unit()
            self.totals.setText(
                f"{len(rows)} عملية   |   صرف {_nf.f2(kv.g(pay))} {u}   ·   "
                f"قبض {_nf.f2(kv.g(rec))} {u}   ·   صافي الفاقد "
                f"{_nf.f2(kv.g(pay - rec))} {u}")
            self._preview()
        except Exception as e:
            err(self, e)

    # ══════════ الإجراءات ══════════
    def _selected(self):
        i = self.table.currentRow()
        if not (0 <= i < len(self.rows)):
            raise ValueError("اختر سنداً من الجدول")
        return self.rows[i]

    def new_account(self):
        try:
            name, ok = QtWidgets.QInputDialog.getText(
                self, "إضافة حساب",
                "اسم الحساب:\n(سيُنشأ تحت «فواقد الورشة» في الدليل)")
            if not ok or not name.strip():
                return
            with db() as conn:
                r = wl.add_loss_type(conn, name.strip(),
                                     self.user["username"])
            info(self, f"أُنشئ الحساب «{r['name']}»\n"
                       f"رقمه في الدليل: {r['code']}")
            self.refresh()
            i = self.account.findData(r["id"])
            if i >= 0:
                self.account.setCurrentIndex(i)
        except Exception as e:
            err(self, e)

    # الاسم القديم للزرّ — تبقى الشاشات والاختبارات التي تناديه تعمل
    new_type = new_account

    def save(self):
        try:
            aid = self.account.currentData()
            if aid is None:
                raise ValueError("اختر الحساب")
            w = float(self.weight.value() or 0)
            if w <= 0:
                raise ValueError("أدخل الوزن")
            kind = self._kind()
            acc = self.account.currentText().split("—")[-1].strip()
            pay = kind == "payment"
            if not confirm_post(
                    self, f"{'سند صرف' if pay else 'سند قبض'} — "
                          f"خزينة التصنيع\n\n"
                          f"الحساب: {acc}\n"
                          f"الوزن: {_nf.f2(w)} {kv.unit()}\n"
                          f"التاريخ: {dstr(self.date)}\n\n"
                          + (f"مدين  حـ/ {acc}\nدائن  حـ/ خزينة التصنيع"
                             if pay else
                             f"مدين  حـ/ خزينة التصنيع\nدائن  حـ/ {acc}")):
                return
            with db() as conn:
                r = wl.create_loss(
                    conn, aid, kv.store(w), dstr(self.date),
                    self.user["username"], self.desc.text().strip(),
                    doc_no=self.doc_no.text().strip() or None, kind=kind)
            posted(self, f"رُحّل {'الصرف' if pay else 'القبض'} {r['doc_no']}"
                         f" — {r['account']} بوزن "
                         f"{_nf.f2(kv.g(r['weight']))} {kv.unit()}",
                   "workshop_losses", r["id"])
            self.weight.setValue(0)
            self.desc.clear()
            self.doc_no.clear()
            self.refresh()
        except Exception as e:
            err(self, e)

    def delete_selected(self):
        """يحذف السند المحدد ويعكس قيده في معاملة واحدة."""
        try:
            r = self._selected()
            pay = (r.get("kind") or "payment") == "payment"
            if not ask(self,
                       f"حذف {'سند الصرف' if pay else 'سند القبض'} "
                       f"{r['doc_no']}؟\n\n"
                       f"الحساب: {r['acc_name']}\n"
                       f"الوزن: {_nf.f2(kv.g(r['weight']))} {kv.unit()}\n\n"
                       + ("سيُعكس القيد فيعود الوزن لخزينة التصنيع.\n"
                          if pay else
                          "سيُعكس القيد فيخرج الوزن من خزينة التصنيع.\n")
                       + "لا يمكن التراجع."):
                return
            with db() as conn:
                d = wl.delete_loss(conn, r["id"], self.user["username"])
            info(self, f"حُذف السند {d['doc_no']} وعُكس أثره على "
                       f"خزينة التصنيع.")
            self.refresh()
        except Exception as e:
            err(self, e)

    def print_selected(self):
        try:
            r = self._selected()
            from services import print_manager
            print_manager.preview_document(self, "workshop_losses", r["id"])
        except Exception as e:
            err(self, e)

    def print_log(self):
        try:
            from services import print_manager
            print_manager.preview_document(self, "workshop_losses_log", 0)
        except Exception as e:
            err(self, e)
