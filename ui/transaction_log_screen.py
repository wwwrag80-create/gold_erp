# -*- coding: utf-8 -*-
"""سجل العمليات المركزي: بديل موحّد عن جداول (آخر العمليات/الفواتير)
المتناثرة في كل شاشة — قائمة منسدلة لنوع المستند + بحث برقم المستند
أو التاريخ، مع إمكانية الحذف المنطقي (للمحاسب) من مكان واحد.

**الجدول على نموذج بيانات (4.69)** — `ui.widgets.ledger_view`: سنةٌ من
الفواتير تُعرض فوراً، والفرز بالقيمة، والتصفية الفورية داخل النتائج
بلا رجوعٍ للقاعدة، وصفّ إجماليٍّ لما يظهر يتغيّر مع التصفية."""
from PyQt5 import QtCore, QtWidgets

from ui import kit

from database.database import db
from services import karat_view as kv
from models import fixing, inventory, invoices, journal, melting, payroll
from models import purchases, shrinkage, stocktake, tax_sales, vouchers
from services.audit import soft_delete_entry
from ui.widgets.common import ask, date_edit, dstr, err, info, title_label
from ui.widgets.ledger_view import LedgerView


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
               r["invoice_date"], kv.g(r["total_weight"]), r["total_wages"],
               r["vat_amount"], r["grand_total"], r["entry_id"])),

    ("receipt", "سندات القبض",
     ["الرقم", "العميل", "التاريخ", "الذهب الفعلي", "مكافئ 18", "النقد",
      "فرق الصافي", "رقم القيد"],
     lambda conn, q, f, t: vouchers.search_vouchers(conn, "receipt", q, f, t),
     lambda r: (r["voucher_no"], r["customer_name"], r["voucher_date"],
               f"{r['gold_weight']:.2f} ع{r['gold_karat']}"
               if r["gold_weight"] else "—",
               kv.g(r["gold_equiv18"]), r["cash_amount"], r["net_diff"],
               r["entry_id"])),

    ("payment", "سندات الصرف",
     ["الرقم", "العميل", "التاريخ", "الذهب الفعلي", "مكافئ 18", "النقد",
      "فرق الصافي", "رقم القيد"],
     lambda conn, q, f, t: vouchers.search_vouchers(conn, "payment", q, f, t),
     lambda r: (r["voucher_no"], r["customer_name"], r["voucher_date"],
               f"{r['gold_weight']:.2f} ع{r['gold_karat']}"
               if r["gold_weight"] else "—",
               kv.g(r["gold_equiv18"]), r["cash_amount"], r["net_diff"],
               r["entry_id"])),

    ("production", "إدخال إنتاج (توريد أطقم)",
     ["رقم التشغيل", "الإجمالي", "الأحجار", "نسبة الخصم", "الوزن المقيد",
      "الحالة", "تاريخ الإدخال", "رقم القيد"],
     lambda conn, q, f, t: inventory.search_work_orders(conn, q, f, t),
     lambda r: (r["work_order_no"], kv.g(r["gross_weight"]),
               kv.g(r["stones_weight"]),
               f"{r['discount_rate']*100:.0f}%",
               kv.g(r["registered_weight"]),
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

    ("tax_sales", "المبيعات الضريبية (خارج المخزون)",
     ["الرقم", "النوع", "الشركة", "المندوب", "الصافي", "الضريبة",
      "الإجمالي", "على الفاتورة", "التاريخ", "رقم القيد"],
     lambda conn, q, f, t: tax_sales.search(conn, q, f, t),
     lambda r: (r["doc_no"], {"credit": "إشعار دائن",
                              "debit": "إشعار مدين"}.get(
                                  r["kind"], "فاتورة ضريبية"),
               r["customer_name"], r["rep_name"] or "—", r["net"],
               r["vat"], r["total"], r["ref_no"] or "—", r["doc_date"],
               r["entry_id"])),


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

        self.doc_type = kit.ComboBox()
        for key, label, *_ in DOC_TYPES:
            self.doc_type.addItem(label, key)
        self.doc_type.currentIndexChanged.connect(self.search)
        self.q = kit.LineEdit()
        self.q.setPlaceholderText("بحث برقم المستند أو اسم العميل...")
        self.q.returnPressed.connect(self.search)
        self.d_from = date_edit()
        self.d_from.setDate(QtCore.QDate(QtCore.QDate.currentDate().year(), 1, 1))
        self.d_to = date_edit()
        btn = kit.PushButton("بحث")
        btn.clicked.connect(self.search)
        # تصفيةٌ فورية داخل النتائج المعروضة — تطبيعٌ عربي ومجموعٌ حيّ
        self.flt = kit.SearchLineEdit()
        self.flt.setPlaceholderText("تصفية فورية داخل النتائج…")
        self.flt.setClearButtonEnabled(True)
        self.flt.setMaximumWidth(320)
        self.flt.textChanged.connect(self._filter)
        self.count = QtWidgets.QLabel("")
        self.count.setObjectName("tableSearchCount")

        head = QtWidgets.QHBoxLayout()
        head.addWidget(QtWidgets.QLabel("نوع المستند:"))
        head.addWidget(self.doc_type)
        head.addWidget(self.q, 1)
        head.addWidget(QtWidgets.QLabel("من:"))
        head.addWidget(self.d_from)
        head.addWidget(QtWidgets.QLabel("إلى:"))
        head.addWidget(self.d_to)
        head.addWidget(btn)

        self.table = LedgerView()
        self.btn_del = kit.PushButton("حذف منطقي للعملية المحددة وعكس أثرها")
        self.btn_del.setObjectName("danger")
        self.btn_del.clicked.connect(self.delete_selected)
        if user["role"] != "accountant":
            self.btn_del.setVisible(False)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("سجل العمليات — كل مستندات النظام من مكان واحد"))
        lay.addLayout(head)
        sub = QtWidgets.QHBoxLayout()
        sub.addWidget(self.flt)
        sub.addWidget(self.count)
        sub.addStretch(1)
        lay.addLayout(sub)
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
            # عناوين الأعمدة بعيار المصنع («مكافئ 18» ← «مكافئ 21»)
            self.table.set_data([kv.rename(c) for c in columns], data)
            self.table.set_filter(self.flt.text())
            self._show_count()
        except Exception as e:
            err(self, e)

    def _filter(self, text):
        self.table.set_filter(text)
        self._show_count()

    def _show_count(self):
        n, total = self.table.shown_count(), len(self.table.source.rows)
        self.count.setText(f"{n:,} من {total:,}" if n != total
                           else f"{total:,} مستند")

    def delete_selected(self):
        # رقم القيد **آخر قيمةٍ في الصفّ** لا آخر عمودٍ ظاهر: قيود اليومية
        # تحمل رقمها خلف عمود «المستخدم»، فكان الحذف يقرأ اسم المستخدم
        vals = self.table.current_values()
        if not vals:
            return
        entry_id = str(vals[-1] if vals[-1] is not None else "").strip()
        if not entry_id or not entry_id.isdigit():
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
