# -*- coding: utf-8 -*-
"""أرشيف المستندات — مركز البحث الشامل في كل ما يصدره النظام.

يبحث في الفواتير والمرتجعات والسندات وفواتير المشتريات ومستندات الصب
والتصفية والتسكير والقيود اليدوية، بفلاتر: رقم المستند، نوعه، اسم
الجهة، ونطاق التاريخ.

كل صف يحمل أزرار إجراءات (معاينة · طباعة · تصدير PDF) تستدعي محرك
الطباعة ليعيد بناء المستند من قاعدة البيانات تماماً كما صدر أول مرة.
"""
from PyQt5 import QtCore, QtWidgets

from database.database import db
from services import karat_view as kv
from services import browser_print
from ui.widgets.common import (big_label, bulk_rows, busy, date_edit, dstr,
                               err, info, make_table, run_bg, title_label,
                               warn)

# ══ سقف العرض ══
# البحث قد يُرجع آلاف المستندات، وكل صفٍّ يحمل ثلاثة أزرار. لا أحد
# يقلّب ألفاً بعينه — يضيّق البحث. فيُعرض أحدثها، وتبقى **الإجماليات
# محسوبة على النتيجة كاملة** فلا يُضلّل السقفُ قارئاً.
PAGE = 300

DOC_TYPES = [
    ("كل المستندات", "all"),
    ("فواتير ومرتجعات", "invoices"),
    ("سندات قبض وصرف", "vouchers"),
    ("فواتير مشتريات", "purchases"),
    ("صب وتصفية", "melting_ops"),
    ("تسكير", "fixing_ops"),
    ("قيود يومية يدوية", "manual"),
]

COLS = ["نوع المستند", "رقم المستند", "التاريخ", "الجهة / الحساب",
        "القيمة النقدية", "الوزن", "الحالة", "إجراءات"]

# لكل نوع: استعلام موحّد يعيد الأعمدة نفسها
QUERIES = {
    "invoices": """
        SELECT i.id, i.invoice_no doc_no, i.invoice_date d,
               COALESCE(e.name,'—') party, i.grand_total cash,
               i.total_weight gold, i.is_deleted,
               CASE i.kind WHEN 'sale' THEN 'فاتورة مبيعات'
                           ELSE 'مرتجع مبيعات' END label
        FROM invoices i LEFT JOIN entities e ON e.id=i.customer_id""",
    "vouchers": """
        SELECT v.id, v.voucher_no doc_no, v.voucher_date d,
               COALESCE(e.name, a.name, '—') party, v.cash_amount cash,
               v.gold_equiv18 gold, v.is_deleted,
               CASE v.kind WHEN 'receipt' THEN 'سند قبض'
                           ELSE 'سند صرف' END label
        FROM vouchers v LEFT JOIN entities e ON e.id=v.customer_id
                        LEFT JOIN accounts a ON a.id=v.target_account_id""",
    "purchases": """
        SELECT p.id, p.purchase_no doc_no, p.purchase_date d,
               COALESCE(e.name,'—') party,
               (COALESCE(p.amount,0)+COALESCE(p.vat_amount,0)) cash,
               0 gold, p.is_deleted, 'فاتورة مشتريات' label
        FROM purchases p LEFT JOIN entities e ON e.id=p.supplier_id""",
    "melting_ops": """
        SELECT m.id, m.op_no doc_no, m.op_date d, '—' party, 0 cash,
               m.equiv18 gold, m.is_deleted,
               CASE m.kind WHEN 'disbursement' THEN 'سند صرف للصب'
                           WHEN 'receipt' THEN 'سند قبض مصفى'
                           WHEN 'close' THEN 'إقفال فاقد فني'
                           ELSE 'صب وتصفية' END label
        FROM melting_ops m""",
    "fixing_ops": """
        SELECT f.id, f.op_no doc_no, f.op_date d,
               COALESCE(e.name,'—') party, f.amount cash, f.weight gold,
               f.is_deleted, 'سند تسكير' label
        FROM fixing_ops f LEFT JOIN entities e ON e.id=f.customer_id""",
    "manual": """
        SELECT j.id, '#'||j.id doc_no, j.entry_date d, '—' party, 0 cash,
               0 gold, j.is_deleted, 'قيد يومية' label
        FROM journal_entries j WHERE j.source_table='manual'""",
}


class DocumentArchiveScreen(QtWidgets.QWidget):
    def __init__(self, user, on_open_ledger=None):
        super().__init__()
        self.user = user
        self.on_open_ledger = on_open_ledger
        self.results = []
        self.shown = PAGE

        self.q = QtWidgets.QLineEdit()
        self.q.setPlaceholderText("رقم المستند أو اسم الجهة…")
        self.q.returnPressed.connect(self.search)
        self.kind = QtWidgets.QComboBox()
        for label, key in DOC_TYPES:
            self.kind.addItem(label, key)
        self.kind.currentIndexChanged.connect(self.search)
        self.d_from = date_edit()
        self.d_from.setDate(QtCore.QDate.currentDate().addMonths(-6))
        self.d_to = date_edit()
        self.include_deleted = QtWidgets.QCheckBox("إظهار المحذوف منطقياً")
        self.include_deleted.stateChanged.connect(self.search)
        btn = QtWidgets.QPushButton("بحث")
        btn.clicked.connect(self.search)

        top = QtWidgets.QGridLayout()
        top.addWidget(QtWidgets.QLabel("بحث:"), 0, 0)
        top.addWidget(self.q, 0, 1)
        top.addWidget(QtWidgets.QLabel("نوع المستند:"), 0, 2)
        top.addWidget(self.kind, 0, 3)
        top.addWidget(QtWidgets.QLabel("من:"), 1, 0)
        top.addWidget(self.d_from, 1, 1)
        top.addWidget(QtWidgets.QLabel("إلى:"), 1, 2)
        top.addWidget(self.d_to, 1, 3)
        top.addWidget(self.include_deleted, 1, 4)
        top.addWidget(btn, 0, 4)

        self.table = make_table()
        self.table.setColumnCount(len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.summary = big_label()
        self.btn_more = QtWidgets.QPushButton()
        self.btn_more.setObjectName("ghost")
        self.btn_more.setToolTip(
            "يُعرض أحدث المستندات أولاً — وضيّق البحث بالتاريخ أو النوع "
            "بدل تقليب الكل")
        self.btn_more.clicked.connect(self.show_more)
        self.btn_more.setVisible(False)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("أرشيف المستندات — البحث الشامل وإعادة الطباعة"))
        lay.addLayout(top)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.btn_more)
        lay.addWidget(self.summary)
        note = QtWidgets.QLabel(
            "أزرار كل صف: 👁 معاينة · 🖨 طباعة · 💾 PDF — يُعاد بناء المستند "
            "من قاعدة البيانات بنفس صورته الأصلية وقت الإصدار.")
        note.setObjectName("cardSub")
        lay.addWidget(note)

    def search(self):
        try:
            key = self.kind.currentData() or "all"
            keys = [k for _, k in DOC_TYPES[1:]] if key == "all" else [key]
            term = self.q.text().strip()
            d1, d2 = dstr(self.d_from), dstr(self.d_to)
            rows = []
            with db(readonly=True) as conn:
                for k in keys:
                    # الفلاتر تُطبَّق **خارج** الاستعلام الأساسي حتى لا
                    # تتعارض أسماء الأعمدة المكرّرة بين الجداول المرتبطة
                    sql = f"SELECT * FROM ({QUERIES[k]}) WHERE d>=? AND d<=?"
                    params = [d1, d2]
                    if not self.include_deleted.isChecked():
                        sql += " AND is_deleted=0"
                    if term:
                        sql += " AND (doc_no LIKE ? OR party LIKE ?)"
                        params += [f"%{term}%", f"%{term}%"]
                    sql += " ORDER BY d DESC, id DESC"
                    for r in conn.execute(sql, params):
                        rows.append({"src": k, "id": r["id"],
                                     "doc_no": r["doc_no"], "date": r["d"],
                                     "party": r["party"], "cash": r["cash"],
                                     "gold": r["gold"], "label": r["label"],
                                     "deleted": r["is_deleted"]})
            rows.sort(key=lambda x: (x["date"], x["id"]), reverse=True)
            self.results = rows
            self.shown = PAGE          # كل بحثٍ يبدأ من صفحته الأولى
            self.render()
        except Exception as e:
            err(self, e)

    def render(self):
        """يرسم أحدث `self.shown` مستنداً، ويجمع الإجماليات على الكل.

        الرسم هنا يمرّ بـ`bulk_rows`: بدونه كانت كلفة الخلية الواحدة
        ١٢.٦ مللي ثانية (لفّ النص يُعيد قياس الصف مع كل خلية)، فبلغ
        فتح الشاشة ثلاثين ثانيةً تظهر فيها نافذةٌ سوداء لا تستجيب.
        """
        shown = self.results[:self.shown]
        with bulk_rows(self.table, len(shown), COLS):
            for i, r in enumerate(shown):
                vals = [r["label"], r["doc_no"], r["date"], r["party"],
                        f"{(r['cash'] or 0):,.2f}",
                        f"{kv.g(r['gold'] or 0):,.2f}",
                        "ملغى" if r["deleted"] else "ساري"]
                for c, v in enumerate(vals):
                    it = QtWidgets.QTableWidgetItem(str(v))
                    it.setTextAlignment(QtCore.Qt.AlignCenter)
                    self.table.setItem(i, c, it)
                self.table.setCellWidget(i, len(COLS) - 1, self._actions(r))
        tc = sum(x["cash"] or 0 for x in self.results)
        tg = sum(x["gold"] or 0 for x in self.results)
        rest = len(self.results) - len(shown)
        self.summary.setText(
            f"عدد المستندات: {len(self.results):,}"
            + (f"   ({len(shown):,} معروضة · {rest:,} بقيّة)" if rest else "")
            + f"   |   إجمالي القيم النقدية: {tc:,.2f} ريال"
            + f"   |   إجمالي الأوزان: {kv.g(tg):,.2f} {kv.unit()}")
        self.btn_more.setVisible(bool(rest))
        self.btn_more.setText(f"▼ عرض {min(PAGE, rest):,} مستنداً إضافياً")

    def show_more(self):
        """يزيد المعروض صفحةً — الإجماليات لم تكن ناقصةً أصلاً."""
        self.shown += PAGE
        self.render()

    def _actions(self, r):
        w = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(w)
        h.setContentsMargins(2, 2, 2, 2)
        h.setSpacing(4)
        for text, tip, fn in (("👁", "معاينة وطباعة عبر المتصفح",
                               self.preview),
                              ("🖨", "طباعة مباشرة (طابعة النظام)",
                               self.do_print),
                              ("💾", "تصدير PDF", self.to_pdf)):
            b = QtWidgets.QPushButton(text)
            b.setObjectName("ghost")
            b.setToolTip(tip)
            b.setMaximumWidth(38)
            b.clicked.connect(lambda _, rr=r, f=fn: f(rr))
            h.addWidget(b)
        # رمز الفاتورة: تفعيله لفاتورة رُحّلت بلا رمز، أو نسخ رابطها
        # لإرساله للعميل. الفواتير وحدها — لا السندات ولا القيود.
        if r.get("src") == "invoices" and not r.get("deleted"):
            b = QtWidgets.QPushButton("🔗")
            b.setObjectName("ghost")
            b.setToolTip("رمز QR: تفعيله لهذه الفاتورة أو نسخ رابط صفحتها")
            b.setMaximumWidth(38)
            b.clicked.connect(lambda _, rr=r: self.share_qr(rr))
            h.addWidget(b)
        return w

    def share_qr(self, r):
        """يفعّل رمز الفاتورة وينشر صفحتها، ثم يعرض رابطها للنسخ.

        **لماذا يلزم هذا الزر**: قرار الرمز يُتخذ في شاشة المبيعات قبل
        الترحيل ويُحفظ مع الفاتورة. فمن رحّل بلا رمز ثم بدا له أن
        يُعطي العميل صفحتها لم يكن أمامه سبيل. هذا هو السبيل — ولا
        يُعيد ترحيل شيء ولا يمسّ رقماً محاسبياً.
        """
        try:
            import config
            from services import invoice_share
            with db() as conn:
                conn.execute("UPDATE invoices SET qr_enabled=1 WHERE id=?",
                             (r["id"],))
            # الرفع في خيطٍ جانبي: على اتصالٍ بطيء كان يترك النافذة
            # سوداء لا تستجيب حتى ينتهي.
            _iid, _co = r["id"], config.COMPANY_NAME
            run_bg(lambda: invoice_share.ensure_published(_iid, _co),
                   parent=self, text="جارٍ تجهيز صفحة الفاتورة…",
                   stage="نشر صفحة فاتورة", timeout=20.0)
            with busy(self, "جارٍ قراءة رابط الصفحة…"):
                with db(readonly=True) as conn:
                    link, where = invoice_share.publish(
                        conn, r["id"], config.COMPANY_NAME)
            if not link:
                warn(self, "تعذّر تجهيز صفحة الفاتورة.\n\n"
                           "افتح «⚙ عرض ← رمز QR على الفاتورة ← لماذا لم "
                           "يظهر الرمز؟» لمعرفة السبب بالضبط.")
                return
            QtWidgets.QApplication.clipboard().setText(link)
            info(self,
                 ("رابط عام — يفتحه العميل من أي مكان:"
                  if where == "cloud" else
                  "رابط على شبكة المصنع — لا يفتحه إلا من كان عليها:")
                 + f"\n\n{link}\n\nنُسخ الرابط. وسيُطبع الرمز على "
                 "الفاتورة في أي طباعة قادمة.")
            self.search()
        except Exception as e:
            err(self, e)

    def open_browser(self, r):
        """يفتح المستند في المتصفح بتنسيق كامل (مستقل عن محرك Qt)."""
        try:
            browser_print.open_document(r["src"], r["id"])
        except Exception as e:
            err(self, e)

    def preview(self, r):
        from services import print_manager
        try:
                        print_manager.preview_document(self, r["src"], r["id"])
        except Exception as e:
            err(self, e)

    def do_print(self, r):
        from services import print_manager
        try:
            print_manager.print_document(self, r["src"], r["id"])
        except Exception as e:
            err(self, e)

    def to_pdf(self, r):
        from services import print_manager
        try:
            path = print_manager.export_pdf_dialog(
                self, r["src"], r["id"], suggested=r["doc_no"] or "مستند")
            if path:
                QtWidgets.QMessageBox.information(
                    self, "تم", f"تم حفظ المستند:\n{path}")
        except Exception as e:
            err(self, e)

    def refresh(self):
        self.search()

    def open_for_term(self, term, months=36):
        """يفتح الأرشيف على رقم مستندٍ أو اسم جهةٍ بعينه.

        يُستدعى من شريط الأوامر الموحّد (Ctrl+K): المستند المطلوب قد
        يكون أقدم من نطاق البحث الافتراضي (ستة أشهر)، فيُوسَّع النطاق
        هنا وإلا ظهر «لا نتائج» لمستندٍ موجود.
        """
        try:
            self.q.setText(str(term or ""))
            self.kind.setCurrentIndex(0)          # كل الأنواع
            self.d_from.setDate(
                QtCore.QDate.currentDate().addMonths(-int(months)))
            self.d_to.setDate(QtCore.QDate.currentDate())
            self.search()
        except Exception as e:
            err(self, e)
