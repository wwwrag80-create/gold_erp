# -*- coding: utf-8 -*-
"""شاشة إدارة وتعديل وتحويل العمليات + سجل التدقيق.

تصحيح أخطاء الإدخال دون المساس بسلامة الدفاتر: كل تحويل أو تعديل يُعكس
فيه القيد القديم بقيد صريح ثم تُنشأ العملية الجديدة، وكل ذلك داخل
معاملة ذرّية واحدة، ويُسجَّل في سجل التدقيق.
"""
from PyQt5 import QtCore, QtWidgets

from database.database import db
from services import karat_view as kv
from models import entities, invoices, operations
from ui.widgets.common import (ask, big_label, date_edit, dstr, err, fill,
                               info, make_table, reload_combo, search_combo,
                               title_label)

DOC_COLS = ["الرقم", "النوع", "التاريخ", "الجهة", "الوزن", "القيمة"]
AUDIT_COLS = ["التاريخ والوقت", "المستخدم", "نوع التعديل", "الجدول",
              "رقم السجل", "التفاصيل"]


class OperationsScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.docs = []

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self._docs_tab(), "تحويل وتعديل العمليات")
        tabs.addTab(self._audit_tab(), "سجل التدقيق")

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("إدارة وتعديل وتحويل العمليات"))
        note = QtWidgets.QLabel(
            "لا يُعدَّل أي قيد سابق في مكانه: تُعكس العملية القديمة بقيد "
            "صريح ثم تُنشأ الجديدة داخل معاملة واحدة — فيبقى الأثر "
            "التاريخي كاملاً وتنعكس النتيجة فوراً في كشوفات الحساب.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addWidget(tabs, 1)

    # ══════════ تبويب العمليات ══════════
    def _docs_tab(self):
        w = QtWidgets.QWidget()
        self.kind = QtWidgets.QComboBox()
        self.kind.addItem("فواتير المبيعات والمرتجعات", "invoices")
        self.kind.addItem("سندات القبض والصرف", "vouchers")
        self.kind.currentIndexChanged.connect(self.load_docs)
        self.d_from = date_edit()
        self.d_from.setDate(QtCore.QDate.currentDate().addMonths(-3))
        self.d_to = date_edit()
        btn_load = QtWidgets.QPushButton("عرض العمليات")
        btn_load.clicked.connect(self.load_docs)
        self.search_no = QtWidgets.QLineEdit()
        self.search_no.setPlaceholderText("بحث برقم الفاتورة أو السند…")
        self.search_no.setMaximumWidth(220)
        self.search_no.returnPressed.connect(self.search_doc)
        btn_search = QtWidgets.QPushButton("🔍 بحث بالرقم")
        btn_search.clicked.connect(self.search_doc)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("النوع:"))
        top.addWidget(self.kind)
        top.addWidget(QtWidgets.QLabel("من:"))
        top.addWidget(self.d_from)
        top.addWidget(QtWidgets.QLabel("إلى:"))
        top.addWidget(self.d_to)
        top.addWidget(btn_load)
        top.addWidget(self.search_no)
        top.addWidget(btn_search)
        top.addStretch(1)

        self.table = make_table()
        self.table.itemSelectionChanged.connect(self.on_pick)

        self.target = search_combo("اكتب اسم الجهة الجديدة…")
        self.reason = QtWidgets.QLineEdit()
        self.reason.setPlaceholderText("سبب التحويل / التعديل (يُسجَّل)")
        btn_transfer = QtWidgets.QPushButton("↪ تحويل العملية للجهة المحددة")
        btn_transfer.setObjectName("homeBtn")
        btn_transfer.clicked.connect(self.do_transfer)
        btn_edit = QtWidgets.QPushButton("✎ تعديل بنود الفاتورة")
        btn_edit.clicked.connect(self.do_edit_items)
        btn_flip = QtWidgets.QPushButton("⇄ عكس نوع الفاتورة")
        btn_flip.setToolTip("تحويل مبيعات ⇄ مرتجع لنفس الجهة")
        btn_flip.clicked.connect(self.do_flip)

        act = QtWidgets.QHBoxLayout()
        act.addWidget(QtWidgets.QLabel("الجهة الجديدة:"))
        act.addWidget(self.target, 2)
        act.addWidget(QtWidgets.QLabel("السبب:"))
        act.addWidget(self.reason, 2)
        act.addWidget(btn_transfer)
        act.addWidget(btn_edit)
        act.addWidget(btn_flip)

        self.picked = big_label("لم تُحدَّد عملية بعد")

        lay = QtWidgets.QVBoxLayout(w)
        lay.addLayout(top)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.picked)
        lay.addLayout(act)
        return w

    # ══════════ تبويب سجل التدقيق ══════════
    def _audit_tab(self):
        w = QtWidgets.QWidget()
        self.a_from = date_edit()
        self.a_from.setDate(QtCore.QDate.currentDate().addMonths(-3))
        self.a_to = date_edit()
        self.a_action = QtWidgets.QComboBox()
        self.a_action.addItem("كل الأنواع", None)
        for k, v in operations.AUDIT_ACTIONS.items():
            self.a_action.addItem(v, k)
        btn = QtWidgets.QPushButton("عرض السجل")
        btn.clicked.connect(self.load_audit)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("من:"))
        top.addWidget(self.a_from)
        top.addWidget(QtWidgets.QLabel("إلى:"))
        top.addWidget(self.a_to)
        top.addWidget(QtWidgets.QLabel("النوع:"))
        top.addWidget(self.a_action)
        top.addWidget(btn)
        top.addStretch(1)

        self.audit_table = make_table()
        lay = QtWidgets.QVBoxLayout(w)
        lay.addLayout(top)
        lay.addWidget(self.audit_table, 1)
        return w

    # ══════════ التحميل ══════════
    def load_docs(self):
        try:
            src = self.kind.currentData()
            f, t = dstr(self.d_from), dstr(self.d_to)
            with db() as conn:
                if src == "invoices":
                    rows = conn.execute(
                        "SELECT i.id, i.invoice_no no, i.kind k,"
                        " i.invoice_date d, e.name party,"
                        " i.total_weight w, i.grand_total v"
                        " FROM invoices i LEFT JOIN entities e"
                        " ON e.id=i.customer_id"
                        " WHERE i.is_deleted=0 AND i.invoice_date BETWEEN ? AND ?"
                        " ORDER BY i.id DESC", (f, t)).fetchall()
                    lbl = {"sale": "مبيعات", "sale_return": "مرتجع"}
                else:
                    rows = conn.execute(
                        "SELECT v.id, v.voucher_no no, v.kind k,"
                        " v.voucher_date d, e.name party,"
                        " v.gold_equiv18 w, v.cash_amount v"
                        " FROM vouchers v LEFT JOIN entities e"
                        " ON e.id=v.customer_id"
                        " WHERE v.is_deleted=0 AND v.voucher_date BETWEEN ? AND ?"
                        " ORDER BY v.id DESC", (f, t)).fetchall()
                    lbl = {"receipt": "قبض", "payment": "صرف"}
            self.docs = [{"id": r["id"], "no": r["no"], "kind": r["k"],
                          "src": src, "party": r["party"] or "—"}
                         for r in rows]
            fill(self.table, DOC_COLS,
                 [(r["no"], lbl.get(r["k"], r["k"]), r["d"],
                   r["party"] or "—", f"{r['w'] or 0:,.2f}",
                   f"{r['v'] or 0:,.2f}") for r in rows])
            self.picked.setText(f"{len(rows)} عملية — اختر سطراً للتحويل")
        except Exception as e:
            err(self, e)

    def load_audit(self):
        try:
            with db() as conn:
                rows = operations.audit_trail(
                    conn, dstr(self.a_from), dstr(self.a_to),
                    self.a_action.currentData())
            fill(self.audit_table, AUDIT_COLS,
                 [(r["when"], r["user"], r["action"], r["table"],
                   str(r["record"] or "—"), r["details"]) for r in rows])
        except Exception as e:
            err(self, e)

    def on_pick(self):
        i = self.table.currentRow()
        if 0 <= i < len(self.docs):
            d = self.docs[i]
            self.picked.setText(
                f"المحدَّد: {d['no']} — الجهة الحالية: {d['party']}")

    def _selected(self):
        i = self.table.currentRow()
        if not (0 <= i < len(self.docs)):
            raise ValueError("اختر عملية من الجدول أولاً")
        return self.docs[i]

    # ══════════ الإجراءات ══════════
    def do_transfer(self):
        try:
            d = self._selected()
            new_id = self.target.currentData()
            if new_id is None:
                raise ValueError("اختر الجهة الجديدة")
            new_name = self.target.currentText()
            if not ask(self, f"تحويل {d['no']} من «{d['party']}» إلى "
                             f"«{new_name}»؟\n\nسيُعكس القيد القديم وتُنشأ "
                             f"عملية جديدة على الجهة الجديدة."):
                return
            with db() as conn:
                if d["src"] == "invoices":
                    r = operations.transfer_invoice(
                        conn, d["id"], new_id, self.user["username"],
                        self.reason.text().strip())
                else:
                    r = operations.transfer_voucher(
                        conn, d["id"], new_id, self.user["username"],
                        self.reason.text().strip())
            info(self, f"تم التحويل بنجاح.\n"
                       f"القديمة: {r['old_no']} ({r['from']})\n"
                       f"الجديدة: {r['new_no']} ({r['to']})")
            self.reason.clear()
            self.load_docs()
        except Exception as e:
            err(self, e)

    def search_doc(self):
        """بحث مباشر برقم الفاتورة أو السند وعرضه للتعديل."""
        try:
            num = self.search_no.text().strip()
            if not num:
                return
            with db() as conn:
                d = operations.find_document(conn, num)
            self.kind.blockSignals(True)
            self.kind.setCurrentIndex(0 if d["src"] == "invoices" else 1)
            self.kind.blockSignals(False)
            self.docs = [{"id": d["id"], "no": d["no"], "kind": d["kind"],
                          "src": d["src"], "party": d["party"]}]
            lbl = {"sale": "مبيعات", "sale_return": "مرتجع",
                   "receipt": "قبض", "payment": "صرف"}
            fill(self.table, DOC_COLS,
                 [(d["no"], lbl.get(d["kind"], d["kind"]), d["date"],
                   d["party"], "—", "—")])
            self.table.selectRow(0)
            self.picked.setText(
                f"المحدَّد: {d['no']} — الجهة الحالية: {d['party']}")
        except Exception as e:
            err(self, e)

    def do_flip(self):
        """عكس نوع الفاتورة (مبيعات ⇄ مرتجع) لنفس الجهة."""
        try:
            d = self._selected()
            if d["src"] != "invoices":
                raise ValueError("عكس النوع يخص الفواتير فقط")
            lbl = {"sale": "مبيعات", "sale_return": "مرتجع"}
            new = "مرتجع" if d["kind"] == "sale" else "مبيعات"
            if not ask(self, f"عكس نوع {d['no']} من «{lbl[d['kind']]}» إلى "
                             f"«{new}»؟\n\nسيُعكس القيد المالي بالكامل "
                             f"وتُحدَّث حالة كل أرقام التشغيل."):
                return
            with db() as conn:
                r = operations.flip_invoice_kind(
                    conn, d["id"], self.user["username"],
                    self.reason.text().strip())
            info(self, f"تم عكس النوع.\n{r['old_no']} ({r['from']}) → "
                       f"{r['new_no']} ({r['to']})\n{r['items']} بند")
            self.reason.clear()
            self.load_docs()
        except Exception as e:
            err(self, e)

    def do_edit_items(self):
        try:
            d = self._selected()
            if d["src"] != "invoices":
                raise ValueError("تعديل البنود يخص الفواتير فقط")
            dlg = InvoiceItemsDialog(self, d["id"], self.user)
            if dlg.exec_():
                self.load_docs()
        except Exception as e:
            err(self, e)

    def refresh(self):
        with db() as conn:
            ents = [e for e in entities.list_entities(conn)
                    if not e["is_internal"]]
        reload_combo(self.target, ents, lambda r: r["name"])
        self.load_docs()
        self.load_audit()


class InvoiceItemsDialog(QtWidgets.QDialog):
    """حوار إضافة/حذف أرقام التشغيل من فاتورة محفوظة."""

    def __init__(self, parent, invoice_id, user):
        super().__init__(parent)
        self.invoice_id = invoice_id
        self.user = user
        self.setWindowTitle("تعديل بنود الفاتورة")
        self.setMinimumWidth(680)

        with db() as conn:
            inv, items = invoices.get_invoice_full(conn, invoice_id)
            self.cart = [{"work_order_id": it["work_order_id"],
                          "weight": it["registered_weight"],
                          "wage_override": it["wage_per_gram"],
                          "wo": conn.execute(
                              "SELECT work_order_no n FROM work_orders"
                              " WHERE id=?", (it["work_order_id"],)
                          ).fetchone()["n"]} for it in items]
        self.inv = inv

        self.wo_no = QtWidgets.QLineEdit()
        self.wo_no.setPlaceholderText("رقم التشغيل المراد إضافته")
        self.wo_no.returnPressed.connect(self.add_item)
        btn_add = QtWidgets.QPushButton("➕ إضافة")
        btn_add.clicked.connect(self.add_item)
        btn_del = QtWidgets.QPushButton("🗑 حذف المحدد")
        btn_del.setObjectName("ghost")
        btn_del.clicked.connect(self.del_item)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.wo_no, 1)
        row.addWidget(btn_add)
        row.addWidget(btn_del)

        self.table = make_table()
        self.total = big_label()
        box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        box.accepted.connect(self.save)
        box.rejected.connect(self.reject)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel(
            f"الفاتورة {inv['invoice_no']} — حذف رقم تشغيل يُعيده للمخزون "
            f"ويخفّض المديونية، وإضافته تجعله مباعاً وتزيدها."))
        lay.addLayout(row)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.total)
        lay.addWidget(box)
        self.render()

    def render(self):
        # السلة تبقى بمكافئ 18 كما قُرئت وكما تُحفظ — التحويل عرضٌ
        # هنا وحده، فلا يمرّ رقم معروض إلى القاعدة.
        fill(self.table, ["رقم التشغيل", f"الوزن المقيد ({kv.unit()})",
                          f"الأجر/جم {kv.active()}"],
             [(c["wo"], f"{kv.g(c['weight']):,.2f}",
               f"{kv.rate(c['wage_override']):,.2f}")
              for c in self.cart])
        self.total.setText(
            f"{len(self.cart)} بند — إجمالي الوزن: "
            f"{kv.g(sum(c['weight'] for c in self.cart)):,.2f} "
            f"{kv.unit()}")

    def add_item(self):
        try:
            no = self.wo_no.text().strip()
            if not no:
                return
            # رقابة صارمة على حالة المخزون قبل الإضافة
            with db() as conn:
                wo = operations.check_item_addable(
                    conn, no, self.inv["kind"],
                    [c["work_order_id"] for c in self.cart])
            self.cart.append({"work_order_id": wo["id"],
                              "weight": wo["registered_weight"],
                              "wage_override": wo["wage_per_gram"],
                              "wo": no})
            self.wo_no.clear()
            self.wo_no.setFocus()
            self.render()
        except Exception as e:
            err(self, e)

    def del_item(self):
        i = self.table.currentRow()
        if 0 <= i < len(self.cart):
            self.cart.pop(i)
            self.render()

    def save(self):
        try:
            if not self.cart:
                raise ValueError("لا يمكن ترك الفاتورة بلا بنود")
            with db() as conn:
                r = operations.edit_invoice_items(
                    conn, self.invoice_id,
                    [{"work_order_id": c["work_order_id"],
                      "weight": c["weight"],
                      "wage_override": c["wage_override"]}
                     for c in self.cart],
                    self.user["username"])
            info(self, f"تم التعديل.\n{r['old_no']} → {r['new_no']}\n"
                       f"حُذف {r['removed']} بند · أُضيف {r['added']} بند")
            self.accept()
        except Exception as e:
            err(self, e)
