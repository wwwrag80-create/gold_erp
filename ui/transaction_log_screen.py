# -*- coding: utf-8 -*-
"""سجل العمليات المركزي: بديل موحّد عن جداول (آخر العمليات/الفواتير)
المتناثرة في كل شاشة — قائمة منسدلة لنوع المستند + بحث برقم المستند
أو التاريخ، مع إمكانية الحذف المنطقي (للمحاسب) من مكان واحد."""
from PyQt5 import QtCore, QtWidgets

from database.database import db
from models import fixing, inventory, invoices, journal, melting, payroll
from models import purchases, shrinkage, stocktake, vouchers
from services.audit import soft_delete_entry
from ui.widgets.common import (ask, date_edit, dstr, err, fill, info, make_table, title_label)


def _inv_kind(r):
    internal = r["entity_type"] == "internal"
    if r["kind"] == "sale":
        return "تحويل داخلي" if internal else "بيع"
    return "عكس تحويل داخلي" if internal else "مرتجع"


def _wo_status(r):
    return "بالمخزون" if r["status"] == "in_stock" else "خرج/بيع"


DOC_TYPES = [
    ("sales", "فواتير المبيعات والتحويلات الداخلية",
     ["الرقم", "النوع", "الطرف الآخر", "التاريخ", "الوزن", "الأجور",
      "الضريبة", "الإجمالي", "رقم القيد"],
     lambda conn, q, f, t: invoices.search_invoices(conn, q, f, t),
     lambda r: (r["invoice_no"], _inv_kind(r), r["customer_name"],
               r["invoice_date"], r["total_weight"], r["total_wages"],
               r["vat_amount"], r["grand_total"], r["entry_id"])),

    ("receipt", "سندات القبض",
     ["الرقم", "العميل", "التاريخ", "الذهب الفعلي", "مكافئ 18", "النقد",
      "فرق الصافي", "رقم القيد"],
     lambda conn, q, f, t: vouchers.search_vouchers(conn, "receipt", q, f, t),
     lambda r: (r["voucher_no"], r["customer_name"], r["voucher_date"],
               f"{r['gold_weight']:.2f} ع{r['gold_karat']}"
               if r["gold_weight"] else "—",
               r["gold_equiv18"], r["cash_amount"], r["net_diff"],
               r["entry_id"])),

    ("payment", "سندات الصرف",
     ["الرقم", "العميل", "التاريخ", "الذهب الفعلي", "مكافئ 18", "النقد",
      "فرق الصافي", "رقم القيد"],
     lambda conn, q, f, t: vouchers.search_vouchers(conn, "payment", q, f, t),
     lambda r: (r["voucher_no"], r["customer_name"], r["voucher_date"],
               f"{r['gold_weight']:.2f} ع{r['gold_karat']}"
               if r["gold_weight"] else "—",
               r["gold_equiv18"], r["cash_amount"], r["net_diff"],
               r["entry_id"])),

    ("production", "إدخال إنتاج (توريد أطقم)",
     ["رقم التشغيل", "الإجمالي", "الأحجار", "نسبة الخصم", "الوزن المقيد",
      "الحالة", "تاريخ الإدخال", "رقم القيد"],
     lambda conn, q, f, t: inventory.search_work_orders(conn, q, f, t),
     lambda r: (r["work_order_no"], r["gross_weight"], r["stones_weight"],
               f"{r['discount_rate']*100:.0f}%", r["registered_weight"],
               _wo_status(r), r["created_at"], r["entry_id"])),

    ("journal", "قيود يومية يدوية",
     ["رقم القيد", "التاريخ", "البيان", "مدين ذهب", "مدين نقد", "المستخدم"],
     lambda conn, q, f, t: journal.search_manual_entries(conn, q, f, t),
     lambda r: (r["id"], r["entry_date"], r["description"], r["gd"], r["cd"],
               r["created_by"] or "—", r["id"])),

    ("melting", "عمليات الصب والتصفية",
     ["الرقم", "التاريخ", "منصرف 18", "منصرف 21", "متوقع 24", "فعلي 24",
      "الفاقد", "النسبة", "رقم القيد"],
     lambda conn, q, f, t: melting.search_melting(conn, q, f, t),
     lambda r: (r["op_no"], r["op_date"], r["w18"], r["w21"], r["expected24"],
               r["actual24"], r["loss24"],
               f"{r['loss_ratio']*100:.2f}%" + (" ⚠" if r["exceeded"] else ""),
               r["entry_id"])),

    ("fixing", "عمليات التسكير",
     ["الرقم", "التاريخ", "العميل", "الوزن", "سعر الجرام", "المبلغ",
      "رقم القيد"],
     lambda conn, q, f, t: fixing.search_fixing(conn, q, f, t),
     lambda r: (r["op_no"], r["op_date"], r["customer_name"], r["weight"],
               r["price"], r["amount"], r["entry_id"])),

    ("purchases", "المشتريات والأصول (آجلة)",
     ["الرقم", "النوع", "المورد", "البيان", "المبلغ", "الضريبة", "الإجمالي",
      "التاريخ", "رقم القيد"],
     lambda conn, q, f, t: purchases.search_purchases(conn, q, f, t),
     lambda r: (r["purchase_no"], "أصل" if r["kind"] == "asset" else "مصروف",
               r["supplier_name"] or "—", r["description"], r["amount"],
               r["vat_amount"], r["total"], r["purchase_date"], r["entry_id"])),


    ("shrinkage", "تسويات فاقد التصنيع (يدوية)",
     ["الرقم", "التاريخ", "الفترة", "الوزن", "رقم القيد"],
     lambda conn, q, f, t: shrinkage.search_shrinkage(conn, q, f, t),
     lambda r: (r["op_no"], r["op_date"], r["period"], r["weight"],
               r["entry_id"])),

    ("stocktake", "الجرد الفعلي (وزني/باركود)",
     ["الرقم", "النوع", "الحساب", "التاريخ", "الدفتري", "الفعلي", "الفرق",
      "مطابق/عجز/زيادة", "رقم القيد"],
     lambda conn, q, f, t: stocktake.search_stocktakes(conn, q, f, t),
     lambda r: (r["stocktake_no"], "وزني" if r["mode"] == "bulk" else "باركود",
               r["account_name"] or "الذهب المشغول", r["stocktake_date"],
               r["ledger_value"], r["actual_value"], r["diff"],
               (f"{r['matched_count']}/{r['missing_count']}/{r['excess_count']}"
                if r["mode"] == "itemized" else "—"), r["entry_id"] or "")),

    ("payroll", "حركات الرواتب (استحقاق/سلف/صرف)",
     ["الموظف", "الفترة", "النوع", "المبلغ", "سلفة مخصومة", "رقم القيد"],
     lambda conn, q, f, t: payroll.search_ledger(conn, q, f, t),
     lambda r: (r["emp_name"], r["period"],
               {"accrual": "استحقاق", "advance": "سلفة",
                "payment": "صرف"}[r["kind"]],
               r["amount"], r["advance_deducted"], r["entry_id"])),
]


class TransactionLogScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user

        self.doc_type = QtWidgets.QComboBox()
        for key, label, *_ in DOC_TYPES:
            self.doc_type.addItem(label, key)
        self.doc_type.currentIndexChanged.connect(self.search)
        self.q = QtWidgets.QLineEdit()
        self.q.setPlaceholderText("بحث برقم المستند أو اسم العميل...")
        self.q.returnPressed.connect(self.search)
        self.d_from = date_edit()
        self.d_from.setDate(QtCore.QDate(QtCore.QDate.currentDate().year(), 1, 1))
        self.d_to = date_edit()
        btn = QtWidgets.QPushButton("بحث")
        btn.clicked.connect(self.search)

        head = QtWidgets.QHBoxLayout()
        head.addWidget(QtWidgets.QLabel("نوع المستند:"))
        head.addWidget(self.doc_type)
        head.addWidget(self.q, 1)
        head.addWidget(QtWidgets.QLabel("من:"))
        head.addWidget(self.d_from)
        head.addWidget(QtWidgets.QLabel("إلى:"))
        head.addWidget(self.d_to)
        head.addWidget(btn)

        self.table = make_table()
        self.btn_del = QtWidgets.QPushButton("حذف منطقي للعملية المحددة وعكس أثرها")
        self.btn_del.setObjectName("danger")
        self.btn_del.clicked.connect(self.delete_selected)
        if user["role"] != "accountant":
            self.btn_del.setVisible(False)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("سجل العمليات — كل مستندات النظام من مكان واحد"))
        lay.addLayout(head)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.btn_del)

    def _current_spec(self):
        key = self.doc_type.currentData()
        for spec in DOC_TYPES:
            if spec[0] == key:
                return spec
        return DOC_TYPES[0]

    def search(self):
        try:
            _, _, columns, loader, mapper = self._current_spec()
            with db(readonly=True) as conn:
                rows = loader(conn, self.q.text().strip(),
                             dstr(self.d_from),
                             dstr(self.d_to))
            data = [mapper(r) for r in rows]
            fill(self.table, columns, data)
        except Exception as e:
            err(self, e)

    def delete_selected(self):
        r = self.table.currentRow()
        if r < 0:
            return
        entry_col = self.table.columnCount() - 1
        item = self.table.item(r, entry_col)
        entry_id = item.text() if item else ""
        if not entry_id:
            return
        if not ask(self, f"حذف منطقي للقيد رقم {entry_id} وعكس آثاره بالكامل؟"):
            return
        try:
            msg = soft_delete_entry(int(entry_id), self.user["username"])
            info(self, msg)
            self.search()
        except Exception as e:
            err(self, e)

    def refresh(self):
        self.search()
