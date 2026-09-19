# -*- coding: utf-8 -*-
"""شاشة المبيعات والمرتجعات: باركود → تفاصيل الطقم كاملة (نفس أعمدة
شاشة التوريد) → أجر مرتبط برقم التشغيل نفسه (قابل للتعديل لكل سطر) +
ضريبة + QR. تدعم التحويل الداخلي (إعادة تشغيل)، والرقم التجميعي 0001
بالوزن الجزئي، وإصدار إشعار مدين ضريبي لفاتورة سابقة غير ضريبية."""
from PyQt5 import QtCore, QtGui, QtWidgets

import config
from database.database import db
from models import entities, inventory, invoices
from models.inventory import BULK_WO_NO
from services import gold_math, karat_view as kv
from services import drafts
from ui.widgets.common import (busy, cell, confirm_post, posted, ask,
                               big_label, date_edit, dstr, err, fill,
                               has_model_image, info, load_pref, make_table,
                               mspin, reload_combo, run_bg, save_pref,
                               search_combo, show_model_image, title_label,
                               wspin)

DRAFT_KEY = "sales"

# نفس أعمدة جدول التوريد + الأجر والأجرة
COLS = ["الموديل", "رقم التشغيل", "الذهب", "الفصوص", "الأحجار", "الأحجار بعد الخصم",
        "الوزن المقيد", "الذهب القائم", "الأجر/جم", "الأجرة (ريال)"]


class NewCustomerDialog(QtWidgets.QDialog):
    def __init__(self, parent, username):
        super().__init__(parent)
        self.username = username
        self.customer_id = None
        self.setWindowTitle("عميل جديد")
        self.name = QtWidgets.QLineEdit()
        self.phone = QtWidgets.QLineEdit()
        self.vat = QtWidgets.QLineEdit()
        form = QtWidgets.QFormLayout(self)
        form.addRow("الاسم:", self.name)
        form.addRow("الجوال:", self.phone)
        form.addRow("الرقم الضريبي:", self.vat)
        btn = QtWidgets.QPushButton("حفظ")
        btn.clicked.connect(self.save)
        form.addRow(btn)

    def save(self):
        try:
            if not self.name.text().strip():
                raise ValueError("أدخل اسم العميل")
            with db() as conn:
                self.customer_id = entities.add_entity(
                    conn, self.name.text().strip(), "customer",
                    self.phone.text().strip(), self.vat.text().strip(),
                    self.username)
            self.accept()
        except Exception as e:
            err(self, e)


class NewReturnItemDialog(QtWidgets.QDialog):
    """إدخال طقم غير مسجّل عائد بمرتجع — بوزنه ومكوّناته."""

    def __init__(self, parent, wo_no):
        super().__init__(parent)
        self.setWindowTitle(f"طقم غير مسجّل: {wo_no}")
        self.setMinimumWidth(420)
        self.gold = wspin()
        self.small = wspin()
        self.big = wspin()
        self.rate = mspin()
        self.rate.setValue(config.STONE_DISCOUNT_RATE * 100)
        self.wage = mspin()
        self.wage.setValue(config.DEFAULT_WAGE_PER_GRAM)
        self.preview = QtWidgets.QLabel("")
        for w in (self.gold, self.small, self.big, self.rate):
            w.valueChanged.connect(self._calc)

        note = QtWidgets.QLabel(
            f"رقم التشغيل {wo_no} غير مسجّل في النظام.\n"
            f"أدخل وزنه ومكوّناته لتسجيله وإرجاعه للمخزون.")
        note.setWordWrap(True)
        f = QtWidgets.QFormLayout()
        f.addRow(note)
        f.addRow(f"الذهب ({kv.unit()}):", self.gold)
        f.addRow(f"الفصوص ({kv.unit()}):", self.small)
        f.addRow(f"الأحجار ({kv.unit()}):", self.big)
        f.addRow("نسبة خصم الأحجار %:", self.rate)
        f.addRow(f"الأجر/جم {kv.active()}:", self.wage)
        f.addRow(self.preview)
        box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(f)
        lay.addWidget(box)
        self._calc()

    def _calc(self):
        from services import gold_math
        reg = gold_math.registered_weight(
            self.gold.value(), self.small.value(), self.big.value(),
            self.rate.value() / 100.0)
        self.preview.setText(f"الوزن المقيد: {reg:,.2f} {kv.unit()}")

    def values(self):
        """القيم كما أدخلها المستخدم — بعيار المصنع لا بمكافئ 18.

        التحويل عند الحفظ وحده (`add_item`)، فتبقى النافذة تعرض ما
        كُتب فيها حرفياً.
        """
        return {"gold": self.gold.value(), "small": self.small.value(),
                "big": self.big.value(), "rate": self.rate.value() / 100.0,
                "wage": self.wage.value()}


class BulkWeightDialog(QtWidgets.QDialog):
    """نافذة إدخال الوزن المطلوب من الرقم التجميعي 0001."""

    def __init__(self, parent, available, is_sale):
        super().__init__(parent)
        self.setWindowTitle(f"الرقم التجميعي {BULK_WO_NO}")
        self.w = wspin()
        form = QtWidgets.QFormLayout(self)
        form.addRow(QtWidgets.QLabel(
            f"الرصيد التجميعي المتاح حالياً: {available:,.2f} {kv.unit()}"
            if is_sale else
            f"الرصيد التجميعي الحالي: {available:,.2f} {kv.unit()} "
            "(المرتجع يزيده)"))
        form.addRow(f"الوزن المطلوب ({kv.unit()}):", self.w)
        box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def value(self):
        return self.w.value()


class TaxDebitNoteDialog(QtWidgets.QDialog):
    """إشعار مدين ضريبي: تسوية ضريبية لاحقة لفاتورة سابقة غير ضريبية."""

    def __init__(self, parent, username):
        super().__init__(parent)
        self.username = username
        self.setWindowTitle("تسويات على أرصدة العملاء")
        self.setMinimumWidth(760)
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self._tax_tab(), "إشعار مدين ضريبي")
        tabs.addTab(self._direct_tab(), "إضافة مبلغ مباشر")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(tabs)
        self.reload()
        self.reload_entities()

    def _tax_tab(self):
        w = QtWidgets.QWidget()
        self.invoice = QtWidgets.QComboBox()
        self.date = date_edit()
        self.preview = big_label()
        self.invoice.currentIndexChanged.connect(self.update_preview)
        btn = QtWidgets.QPushButton("إصدار الإشعار وترحيل قيد الضريبة")
        btn.clicked.connect(self.issue)
        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(QtWidgets.QLabel(
            "اختر فاتورة سابقة صدرت بدون ضريبة ليصدر لها إشعار مدين ضريبي "
            "ملحق برقمها. القيد: مدين حساب العميل / دائن ضريبة المخرجات — "
            "دون أي مساس برصيد المخزون أو أوزان الفاتورة الأصلية."))
        form = QtWidgets.QFormLayout()
        form.addRow("الفاتورة غير الضريبية:", self.invoice)
        form.addRow("تاريخ الإشعار:", self.date)
        form.addRow(self.preview)
        lay.addLayout(form)
        lay.addWidget(btn)
        return w

    def _direct_tab(self):
        """إضافة مبلغ مباشر لرصيد العميل دون المساس بالصندوق."""
        w = QtWidgets.QWidget()
        self.adj_entity = search_combo("اكتب اسم الجهة…")
        self.adj_entity.currentIndexChanged.connect(self.adj_preview)
        self.adj_amount = mspin()
        self.adj_amount.valueChanged.connect(self.adj_preview)
        self.adj_dir = QtWidgets.QComboBox()
        self.adj_dir.addItem("زيادة رصيد العميل المدين (عليه)", "debit")
        self.adj_dir.addItem("تخفيض رصيد العميل (له)", "credit")
        self.adj_contra = QtWidgets.QComboBox()
        self.adj_contra.addItem("حساب التسويات المباشرة (2900)", "adjust")
        self.adj_contra.addItem("حساب ضريبة المخرجات (2100)", "vat")
        self.adj_date = date_edit()
        self.adj_note = QtWidgets.QLineEdit()
        self.adj_note.setPlaceholderText("بيان التسوية (اختياري)")
        self.adj_prev = big_label()
        btn = QtWidgets.QPushButton("ترحيل التسوية المباشرة")
        btn.clicked.connect(self.issue_direct)
        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(QtWidgets.QLabel(
            "إضافة مبلغ مباشر إلى رصيد العميل النقدي دون ربطه بفاتورة، "
            "ودون أي مساس بحساب الصندوق أو البنك — قيد تسوية دفتري بحت "
            "مقابل حساب التسويات أو الضريبة."))
        form = QtWidgets.QFormLayout()
        form.addRow("الجهة:", self.adj_entity)
        form.addRow("المبلغ (ريال):", self.adj_amount)
        form.addRow("اتجاه التسوية:", self.adj_dir)
        form.addRow("الحساب المقابل:", self.adj_contra)
        form.addRow("التاريخ:", self.adj_date)
        form.addRow("البيان:", self.adj_note)
        form.addRow(self.adj_prev)
        lay.addLayout(form)
        lay.addWidget(btn)
        return w

    def reload_entities(self):
        with db() as conn:
            reload_combo(self.adj_entity, entities.list_entities(conn),
                        lambda r: ((("🏭 " if r["is_internal"] else
                                    f"[{entities.TYPE_LABELS[r['entity_type']]}] ")
                                   + r["name"])))
        self.adj_preview()

    def adj_preview(self):
        eid = self.adj_entity.currentData()
        if eid is None:
            self.adj_prev.setText("")
            return
        with db() as conn:
            g, c = entities.balances(conn, eid)
        self.adj_prev.setText(
            f"رصيد العميل الحالي — نقد: {c:,.2f} ريال "
            f"(هذه التسوية لا تمس الصندوق إطلاقاً)")

    def issue_direct(self):
        try:
            eid = self.adj_entity.currentData()
            if eid is None:
                raise ValueError("اختر الجهة")
            with db() as conn:
                res = invoices.create_direct_adjustment(
                    conn, eid, self.adj_amount.value(), dstr(self.adj_date),
                    self.username, contra=self.adj_contra.currentData(),
                    direction=self.adj_dir.currentData(),
                    notes=self.adj_note.text().strip())
            info(self, f"تمت التسوية المباشرة {res['note_no']} بمبلغ "
                       f"{res['amount']:,.2f} ريال مقابل حساب "
                       f"{res['contra_code']} — دون أي مساس بالصندوق.")
            self.adj_amount.setValue(0)
            self.adj_note.clear()
            self.adj_preview()
        except Exception as e:
            err(self, e)

    def reload(self):
        with db() as conn:
            rows = conn.execute(
                "SELECT i.id, i.invoice_no, i.invoice_date, i.total_wages,"
                " e.name cname FROM invoices i JOIN entities e"
                " ON e.id=i.customer_id WHERE i.is_deleted=0"
                " AND i.vat_applied=0 AND i.kind='sale'"
                " AND e.entity_type<>'internal'"
                " AND NOT EXISTS (SELECT 1 FROM tax_debit_notes n"
                "                 WHERE n.invoice_id=i.id AND n.is_deleted=0)"
                " ORDER BY i.id DESC").fetchall()
        self.invoice.clear()
        for r in rows:
            self.invoice.addItem(
                f"{r['invoice_no']} — {r['cname']} — {r['invoice_date']} — "
                f"أجور {r['total_wages']:,.2f}", r["id"])
        self.update_preview()

    def update_preview(self):
        iid = self.invoice.currentData()
        if iid is None:
            self.preview.setText("لا توجد فواتير غير ضريبية بانتظار تسوية.")
            return
        with db() as conn:
            r = conn.execute("SELECT total_wages FROM invoices WHERE id=?",
                             (iid,)).fetchone()
        base = r["total_wages"] if r else 0.0
        self.preview.setText(
            f"الوعاء: {base:,.2f} ريال — الضريبة المستحقة "
            f"({config.VAT_RATE*100:.0f}%): {gold_math.wages_vat(base):,.2f} ريال")

    def issue(self):
        try:
            iid = self.invoice.currentData()
            if iid is None:
                raise ValueError("لا توجد فاتورة قابلة للتسوية")
            with db() as conn:
                res = invoices.create_tax_debit_note(
                    conn, iid, dstr(self.date), self.username)
            info(self, f"تم إصدار الإشعار {res['note_no']} بقيمة ضريبة "
                       f"{res['vat_amount']:,.2f} ريال (قيد {res['entry_id']})")
            self.reload()
        except Exception as e:
            err(self, e)


class QRDialog(QtWidgets.QDialog):
    def __init__(self, parent, res):
        super().__init__(parent)
        self.setWindowTitle(f"فاتورة {res['invoice_no']} — QR هيئة الزكاة")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(big_label(
            f"الإجمالي شامل الضريبة: {res['grand_total']:,.2f} ريال — "
            f"الضريبة: {res['vat']:,.2f} ريال"))
        # الصورة تُبنى الآن لا عند الحفظ — فالحفظ يبقى فورياً
        if not res.get("qr_path") and res.get("qr_base64"):
            try:
                from services import zatca
                res["qr_path"] = zatca.generate_qr_image(
                    res["qr_base64"], res["invoice_no"])
            except Exception:
                res["qr_path"] = None
        if res.get("qr_path"):
            img = QtWidgets.QLabel()
            img.setAlignment(QtCore.Qt.AlignCenter)
            img.setPixmap(QtGui.QPixmap(res["qr_path"]).scaledToWidth(
                240, QtCore.Qt.SmoothTransformation))
            lay.addWidget(img)
        else:
            lay.addWidget(QtWidgets.QLabel(
                "لعرض صورة QR ثبّت: pip install qrcode Pillow\n"
                "محتوى TLV Base64 (متوافق مع ZATCA):"))
        txt = QtWidgets.QTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText(res["qr_base64"])
        txt.setMaximumHeight(90)
        lay.addWidget(txt)


class SalesScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.items = []          # [{wo, weight, wage}]
        self.editing_id = None
        self.customers = []

        self.kind = QtWidgets.QComboBox()
        self.kind.addItem("فاتورة بيع", "sale")
        self.kind.addItem("مرتجع بيع", "sale_return")
        self.kind.currentIndexChanged.connect(self.clear_items)
        self.customer = search_combo("اكتب اسم العميل أو الطرف المقابل…")
        self.customer.currentIndexChanged.connect(self.customer_changed)
        btn_new_cust = QtWidgets.QPushButton("+ عميل جديد")
        btn_new_cust.setObjectName("ghost")
        btn_new_cust.clicked.connect(self.new_customer)
        btn_tax_note = QtWidgets.QPushButton("إشعار مدين ضريبي")
        btn_tax_note.setObjectName("ghost")
        btn_tax_note.clicked.connect(self.open_tax_note)
        self.date = date_edit()
        self.description = QtWidgets.QLineEdit()
        self.description.setPlaceholderText(
            "البيان (اختياري) — يُحفظ مع العملية ويظهر في كشف الحساب")
        # رقم الموديل قبل رقم التشغيل: يُملأ تلقائياً من دليل
        # الموديلات عند إدخال رقم تشغيل مسجّل، ويُدخَل يدوياً للأطقم
        # الجديدة فيُسجَّل في الدليل ويبقى مرتبطاً بالطقم.
        self.model_no = QtWidgets.QComboBox()
        self.model_no.setEditable(True)
        self.model_no.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.model_no.setMaximumWidth(130)
        self.model_no.lineEdit().setPlaceholderText("رقم الموديل")
        self.barcode = QtWidgets.QLineEdit()
        self.barcode.setPlaceholderText(
            f"امسح الباركود أو اكتب رقم التشغيل (الرقم {BULK_WO_NO} = "
            "رصيد تجميعي بالوزن)")
        # Enter على رقم التشغيل يضيف السطر مباشرة ويبقي التركيز على
        # خانة رقم التشغيل لاستكمال الإدخال المتتابع بالماسح الضوئي.
        self.barcode.returnPressed.connect(self.wo_entered)
        # حقل الأجر/المصنعية المستقل بجانب رقم التشغيل — يُستدعى دينامياً
        # من رقم التشغيل نفسه ويقبل التعديل قبل إضافة السطر
        self.line_wage = mspin()
        self.line_wage.setMaximumWidth(120)
        # حقل الوزن المقيد: يُملأ تلقائياً من رقم التشغيل المسجّل،
        # ويُدخَل يدوياً لأرقام التشغيل الجديدة في المرتجعات.
        self.line_reg = wspin()
        self.line_reg.setMaximumWidth(120)
        self.line_reg.setToolTip(
            "الوزن المقيد — يظهر تلقائياً للأطقم المسجّلة، "
            "ويُدخَل يدوياً للأطقم الجديدة في المرتجع")
        self.line_reg.installEventFilter(self)
        # Enter في حقل الأجر يضيف السطر مباشرة
        self.line_wage.installEventFilter(self)
        self.btn_add_line = QtWidgets.QPushButton("+ إضافة سطر")
        self.btn_add_line.clicked.connect(self.add_item)
        self.vat_check = QtWidgets.QCheckBox(
            "تطبيق القيمة المضافة (15%) — فاتورة ضريبية مع QR")
        self.vat_check.setChecked(False)
        self.vat_check.stateChanged.connect(self.recalc)
        # ══ رمز QR لصفحة الفاتورة — قرارٌ لكل فاتورة ══
        # ليست كل فاتورة تحتاج صفحةً للعميل. وإنشاء الرمز يعني رفع
        # صور موديلاتها إلى التخزين — مساحةٌ تُستهلك بلا داعٍ إن لم
        # تُطلب. فالافتراضي إذن **غير مفعَّل**، والتفعيل باختيار صريح.
        # وآخر اختيار يُحفظ: من يعمل يومه كله بفواتير ذات رمز لا
        # يُطالَب بتفعيله في كل فاتورة.
        self.qr_check = QtWidgets.QCheckBox(
            "إنشاء رمز QR لصفحة الفاتورة (الفاتورة + صور الموديلات)")
        self.qr_check.setToolTip(
            "عند تفعيله يُطبع على الفاتورة رمزٌ يفتح صفحتها على الجوال:\n"
            "الفاتورة أولاً ثم موديلاتها بأسمائها وأعدادها.\n\n"
            "يبقى الاختيار مفعّلاً للفواتير التالية حتى تُلغيه — "
            "وما لم يُفعَّل لا يُنشأ رمز ولا تُرفع صورة ولا تُستهلك "
            "مساحة.")
        self.qr_check.setChecked(
            str(load_pref("sales_qr_enabled", "0")).strip() == "1")
        self.qr_check.stateChanged.connect(self._qr_pref_changed)
        self.internal_note = QtWidgets.QLabel(
            "🏭 تحويل داخلي (إعادة تشغيل): تخرج الأطقم إلى خزينة التصنيع "
            "بالوزن فقط — بلا أجور ولا ضريبة.")
        self.internal_note.setObjectName("warn")
        self.internal_note.setVisible(False)

        top = QtWidgets.QGridLayout()
        top.addWidget(QtWidgets.QLabel("نوع العملية:"), 0, 0)
        top.addWidget(self.kind, 0, 1)
        top.addWidget(QtWidgets.QLabel("العميل / الطرف المقابل:"), 0, 2)
        top.addWidget(self.customer, 0, 3)
        top.addWidget(btn_new_cust, 0, 4)
        top.addWidget(btn_tax_note, 0, 5)
        top.addWidget(QtWidgets.QLabel("التاريخ:"), 1, 0)
        top.addWidget(self.date, 1, 1)
        top.addWidget(QtWidgets.QLabel("البيان:"), 1, 2)
        top.addWidget(self.description, 1, 3, 1, 3)
        top.addWidget(self.vat_check, 2, 0, 1, 6)
        top.addWidget(self.qr_check, 3, 0, 1, 6)
        top.addWidget(self.internal_note, 4, 0, 1, 6)
        def _sub(t):
            l = QtWidgets.QLabel(t)
            l.setObjectName("cardSub")
            return l

        entry = QtWidgets.QGridLayout()
        # الموديل أولاً ثم رقم التشغيل
        entry.addWidget(_sub("رقم الموديل"), 0, 0)
        entry.addWidget(_sub("رقم التشغيل / الباركود"), 0, 1)
        entry.addWidget(_sub("الأجر / المصنعية (ريال/جم)"), 0, 2)
        entry.addWidget(_sub(""), 0, 3)
        entry.addWidget(self.model_no, 1, 0)
        entry.addWidget(self.barcode, 1, 1)
        entry.addWidget(self.line_wage, 1, 2)
        entry.addWidget(self.btn_add_line, 1, 3)
        entry.setColumnStretch(0, 1)
        entry.setColumnStretch(1, 4)
        entry.setColumnStretch(2, 1)
        top.addLayout(entry, 5, 0, 1, 6)

        self.items_table = make_table()
        # النقر على خانة الموديل يفتح صورته المحفوظة
        self.items_table.cellClicked.connect(self._model_clicked)
        self.items_table.setToolTip(
            "انقر خانة الموديل لعرض صورته المحفوظة في دليل الموديلات")
        btn_remove = QtWidgets.QPushButton("حذف الطقم المحدد من الفاتورة")
        btn_remove.setObjectName("ghost")
        btn_remove.clicked.connect(self.remove_item)
        btn_weight = QtWidgets.QPushButton("⚖ تعديل وزن السطر المحدد")
        btn_weight.setToolTip("تصحيح الوزن المقيد المُدخل خطأً")
        btn_weight.clicked.connect(self.edit_line_weight)
        btn_wage = QtWidgets.QPushButton("تعديل أجر السطر المحدد")
        btn_wage.setObjectName("ghost")
        btn_wage.clicked.connect(self.edit_line_wage)
        self.totals = big_label()
        self.live_balance = QtWidgets.QLabel("")
        self.live_balance.setObjectName("cardSub")
        self.live_balance.setWordWrap(True)
        self.btn_save = QtWidgets.QPushButton("ترحيل الفاتورة")
        self.btn_save.clicked.connect(self.save)
        self.btn_cancel_edit = QtWidgets.QPushButton("إلغاء التعديل")
        self.btn_cancel_edit.setObjectName("ghost")
        self.btn_cancel_edit.clicked.connect(self.cancel_edit)
        self.btn_cancel_edit.setVisible(False)
        self.edit_banner = QtWidgets.QLabel(
            "✎ وضع التعديل: عند الحفظ يُلغى أثر القيد القديم ويُرحَّل قيد "
            "جديد بالبيانات الحالية داخل معاملة واحدة.")
        self.edit_banner.setObjectName("warn")
        self.edit_banner.setWordWrap(True)
        self.edit_banner.setVisible(False)
        # يظهر حين تُستعاد فاتورة لم تُرحَّل — فلا يظن المستخدم أن
        # أسطراً ظهرت من تلقاء نفسها.
        self.live_note = QtWidgets.QLabel("")
        self.live_note.setObjectName("ok")
        self.live_note.setWordWrap(True)
        self.live_note.setVisible(False)

        inv_box = QtWidgets.QGroupBox("بنود الفاتورة")
        il = QtWidgets.QVBoxLayout(inv_box)
        il.addLayout(top)
        il.addWidget(self.items_table)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(btn_remove)
        row.addWidget(btn_weight)
        row.addWidget(btn_wage)
        row.addStretch(1)
        row.addWidget(self.totals)
        il.addLayout(row)
        il.addWidget(self.live_balance)
        il.addWidget(self.live_note)
        il.addWidget(self.edit_banner)
        srow = QtWidgets.QHBoxLayout()
        srow.addWidget(self.btn_save, 1)
        srow.addWidget(self.btn_cancel_edit)
        il.addLayout(srow)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label(
            "المبيعات والمرتجعات والتحويلات الداخلية — فوترة ZATCA"))
        # الأجر يُستدعى آلياً عند الإضافة؛ تعديله اختياري عبر زر مستقل.
        lay.addWidget(inv_box, 1)
        keys = QtWidgets.QLabel(
            "⌨ إدخالٌ بلوحة المفاتيح وحدها:  F3 رقم التشغيل  ·  Enter "
            "ينتقل ويضيف السطر  ·  F4 العميل  ·  F2 ترحيل الفاتورة  ·  "
            "Delete حذف السطر المحدد  ·  Esc إلغاء التعديل")
        keys.setObjectName("cardSub")
        keys.setWordWrap(True)
        lay.addWidget(keys)
        note = QtWidgets.QLabel(
            "لعرض سجل الفواتير والتحويلات السابقة أو حذفها منطقياً: افتح "
            "شاشة (سجل العمليات).")
        note.setObjectName("cardSub")
        lay.addWidget(note)
        self._install_shortcuts()

    def _qr_pref_changed(self):
        """يحفظ آخر اختيار لرمز QR فيبقى بعد الخروج من الشاشة والنظام."""
        save_pref("sales_qr_enabled",
                  "1" if self.qr_check.isChecked() else "0",
                  self.user.get("username"))

    # ══════════════════════════════════════════════════════════════
    #  مسوّدة الفاتورة غير المرحَّلة
    # --------------------------------------------------------------
    #  الشاشة تُغلق عند الانتقال لغيرها، فما لم يُرحَّل يُحفظ ويُستعاد.
    #  شرح الفكرة كاملاً في `services/drafts.py`.
    # ══════════════════════════════════════════════════════════════

    def draft_state(self):
        """وصفُ ما في الشاشة الآن — أو None إن لم يكن فيها شيء.

        تُحفظ **أرقام** الأطقم لا صفوفها: الصف صورةٌ من لحظةٍ مضت، وقد
        تتغيّر حالة الطقم قبل العودة. القراءة من جديد عند الاستعادة
        تضمن أن ما يُرحَّل يطابق الواقع.
        """
        if self.editing_id is not None:
            return None          # وضع التعديل لا يُحفظ مسوّدةً
        if not self.items:
            return None
        return {
            "kind": self.kind.currentData(),
            "customer_id": self.customer.currentData(),
            "date": dstr(self.date),
            "description": self.description.text().strip(),
            "vat": bool(self.vat_check.isChecked()),
            "qr": bool(self.qr_check.isChecked()),
            "items": [{"wo_id": i["wo"]["id"], "weight": i["weight"],
                       "wage": i["wage"]} for i in self.items],
        }

    def apply_draft(self, d):
        """يعيد بناء الشاشة من مسوّدة — بتجاهل ما لم يعد موجوداً."""
        if not d or not d.get("items"):
            return False
        items = []
        try:
            with db(readonly=True) as conn:
                for it in d["items"]:
                    wo = conn.execute(
                        "SELECT * FROM work_orders WHERE id=? AND"
                        " is_deleted=0", (it.get("wo_id"),)).fetchone()
                    if wo is None:
                        continue      # طقمٌ حُذف بعد حفظ المسوّدة
                    items.append({"wo": wo,
                                  "weight": float(it.get("weight") or 0),
                                  "wage": float(it.get("wage") or 0)})
        except Exception:
            return False
        if not items:
            return False
        self._loading_doc = True
        try:
            i = self.kind.findData(d.get("kind") or "sale")
            if i >= 0:
                self.kind.setCurrentIndex(i)
            i = self.customer.findData(d.get("customer_id"))
            if i >= 0:
                self.customer.setCurrentIndex(i)
        finally:
            self._loading_doc = False
        if d.get("date"):
            self.date.setDate(QtCore.QDate.fromString(d["date"], "yyyy-MM-dd"))
        self.description.setText(d.get("description") or "")
        self.vat_check.setChecked(bool(d.get("vat")))
        self.qr_check.setChecked(bool(d.get("qr")))
        self.items = items
        self.render_items()
        return True

    def _restore_draft(self):
        """يستعيد المسوّدة مرةً واحدة عند أول بناء للشاشة."""
        if getattr(self, "_draft_done", False):
            return
        self._draft_done = True
        try:
            if self.apply_draft(drafts.load(DRAFT_KEY,
                                            self.user.get("username"))):
                self.live_note.setText(
                    "↩ استُعيدت فاتورة لم تُرحَّل بعد — أكملها أو "
                    "امسح أسطرها.")
                self.live_note.setVisible(True)
        except Exception:
            pass          # المسوّدة راحةٌ لا تُعطّل الشاشة

    def _save_draft(self):
        try:
            drafts.save(DRAFT_KEY, self.user.get("username"),
                        self.draft_state())
        except Exception:
            pass

    def on_close(self):
        """يُستدعى من `LazyScreen.release` عند مغادرة الشاشة."""
        self._save_draft()

    # ══════════════════════════════════════════════════════════════
    #  الإدخال السريع بلوحة المفاتيح
    # ══════════════════════════════════════════════════════════════

    def _install_shortcuts(self):
        """مفاتيح تُغني عن الفأرة في شاشة الإدخال الأكثر استعمالاً.

        **لماذا هنا بالذات**: المبيعات شاشةُ الدوام كله — عشرات
        الفواتير في اليوم، وكل فاتورة عدة أسطر. وترك لوحة المفاتيح
        لالتقاط الفأرة بين كل سطرٍ وآخر يضاعف زمن الفاتورة ويُدخل
        أخطاءً في النقر. الأسهم وEnter كانا موجودين؛ ما ينقص هو
        الحفظ والإلغاء والقفز — فأُضيفت هنا.

        المفاتيح محصورة في هذه الشاشة (`WidgetWithChildrenShortcut`)
        فلا تتسرّب إلى شاشةٍ أخرى ولا تصطدم باختصار عام.
        """
        self._shortcuts = []
        for seq, fn in (("F2", self._save_shortcut),
                        ("F3", lambda: self._focus(self.barcode)),
                        ("F4", lambda: self._focus(self.customer)),
                        ("Esc", self._escape)):
            sc = QtWidgets.QShortcut(QtGui.QKeySequence(seq), self)
            sc.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
            self._shortcuts.append(sc)
        # ══ Delete على الجدول وحده ══
        # الاختصار يبتلع المفتاح قبل أن يصل لمن تحته. فلو كان مداه
        # الشاشة كلها لحذف سطراً من الفاتورة كلما ضغط المستخدم Delete
        # وهو يصحّح رقماً في حقل الكتابة — وهو أسوأ ما يمكن أن يفعله
        # اختصارٌ يُفترض أنه تسهيل.
        sc = QtWidgets.QShortcut(QtGui.QKeySequence("Delete"),
                                 self.items_table)
        sc.setContext(QtCore.Qt.WidgetShortcut)
        sc.activated.connect(self._delete_shortcut)
        self._shortcuts.append(sc)

    def _focus(self, widget):
        widget.setFocus(QtCore.Qt.ShortcutFocusReason)
        if hasattr(widget, "selectAll"):
            widget.selectAll()
        elif hasattr(widget, "lineEdit") and widget.lineEdit() is not None:
            widget.lineEdit().selectAll()

    def _save_shortcut(self):
        """F2 يرحّل — وزرُّ الترحيل هو المرجع لا الدالة مباشرةً.

        الزر يُعطَّل أثناء الترحيل، فالمرور به يمنع ترحيلاً ثانياً لو
        ضُغط المفتاح مرتين متتاليتين.
        """
        if self.btn_save.isEnabled():
            self.btn_save.click()

    def _delete_shortcut(self):
        """Delete يحذف السطر المحدد — ولا يعمل إلا والجدول هو المُركَّز."""
        if self.items_table.currentRow() >= 0:
            self.remove_item()

    def _escape(self):
        """Esc يلغي وضع التعديل، أو يعيد المؤشر لرقم التشغيل.

        لا يمسح فاتورةً قيد الإدخال: مفتاحٌ واحد يمحو عمل خمس دقائق
        خطأٌ في التصميم لا تسهيل.
        """
        if self.editing_id is not None:
            self.cancel_edit()
        else:
            self._focus(self.barcode)

    # ---- الطرف المقابل ----
    def _is_internal(self, cid):
        return any(c["id"] == cid and c["is_internal"] for c in self.customers)

    def customer_changed(self):
        cid = self.customer.currentData()
        internal = cid is not None and self._is_internal(cid)
        self.vat_check.setEnabled(not internal)
        self.internal_note.setVisible(internal)
        if internal:
            self.vat_check.setChecked(False)
        self.recalc()

    def new_customer(self):
        dlg = NewCustomerDialog(self, self.user["username"])
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self.refresh()
            idx = self.customer.findData(dlg.customer_id)
            if idx >= 0:
                self.customer.setCurrentIndex(idx)

    def open_tax_note(self):
        TaxDebitNoteDialog(self, self.user["username"]).exec_()

    # ---- بنود الفاتورة ----
    def clear_items(self, *_):
        """يُفرغ السلة — إلا أثناء تحميل فاتورة للتعديل."""
        if getattr(self, "_loading_doc", False):
            return
        return self._clear_items_now()

    def _clear_items_now(self):
        self.items = []
        self.render_items()

    def load_invoice(self, invoice_id):
        """يفتح فاتورة قائمة للتعديل ويُنزل أطقمها بكامل تفاصيلها."""
        try:
            with db() as conn:
                inv, items = invoices.get_invoice_full(conn, invoice_id)
                if not inv:
                    raise ValueError("الفاتورة غير موجودة")
                if inv["is_deleted"]:
                    raise ValueError("الفاتورة محذوفة — لا يمكن تعديلها")
                cart = []
                for it in items:
                    wo = conn.execute("SELECT * FROM work_orders WHERE id=?",
                                      (it["work_order_id"],)).fetchone()
                    # المخزَّن بمكافئ 18 ← المعروض بعيار المصنع
                    cart.append({
                        "wo": wo,
                        # هويّة السطر: بها يعرف التعديل أيَّ سطرٍ
                        # يُحدِّث. الرقم التجميعي يتكرّر في الفاتورة
                        # بأسطرٍ مستقلة، ولا يميّزها إلا هذا الرقم.
                        "item_id": it["item_id"],
                        "weight": kv.g(it["registered_weight"]),
                        "wage": kv.rate(it["wage_per_gram"])})
            self.editing_id = invoice_id
            self.refresh()
            # ══ تعطيل الإشارات أثناء التحميل ══
            # تغيير نوع العملية مربوط بـ`clear_items`، وتغيير الجهة
            # بـ`customer_changed` — وكلاهما يُفرغ السلة. ضبطهما هنا
            # كان يمسح أطقم الفاتورة فور تحميلها، فيبدو للمستخدم أن
            # التعديل حذف كل الأسطر وأبقى ما أضافه فقط.
            self._loading_doc = True
            try:
                self.kind.blockSignals(True)
                self.customer.blockSignals(True)
                idx = self.kind.findData(inv["kind"])
                if idx >= 0:
                    self.kind.setCurrentIndex(idx)
                idx = self.customer.findData(inv["customer_id"])
                if idx >= 0:
                    self.customer.setCurrentIndex(idx)
            finally:
                self.kind.blockSignals(False)
                self.customer.blockSignals(False)
                self._loading_doc = False
            self.date.setDate(QtCore.QDate.fromString(inv["invoice_date"],
                                                      "yyyy-MM-dd"))
            self.description.setText(inv["description"] or "")
            self.vat_check.setChecked(bool(inv["vat_applied"]))
            self.items = cart
            self.render_items()
            self._update_mode()
        except Exception as e:
            err(self, e)

    def cancel_edit(self):
        self.editing_id = None
        self.description.clear()
        self.clear_items()
        self._update_mode()

    def _update_mode(self):
        editing = self.editing_id is not None
        self.edit_banner.setVisible(editing)
        self.btn_cancel_edit.setVisible(editing)
        self.btn_save.setText("حفظ التعديل (إلغاء القيد القديم وترحيل قيد جديد)"
                              if editing else "ترحيل الفاتورة")

    def eventFilter(self, obj, event):
        """Enter في حقل الأجر ⇒ إضافة السطر (المؤشر يعود لرقم التشغيل).

        **القراءة بـ`getattr` لا بالسمة مباشرةً**: الشاشة تُغلق عند
        الانتقال لغيرها (شاشة واحدة حيّة في كل لحظة)، وأثناء هدمها
        يصل حدث `Destroy` لكل حقل فيها بعد أن يكون كائن بايثون قد
        بدأ فناءه وفرغت سماته — فيرفع `self.line_wage` استثناءً في
        مرشّح أحداث، وهو استثناء يقتل التطبيق لا يُلتقط.
        """
        wage = getattr(self, "line_wage", None)
        if wage is not None and obj is wage \
                and event.type() == QtCore.QEvent.KeyPress:
            if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                self.add_item()
                return True
        return super().eventFilter(obj, event)

    def wo_entered(self):
        """Enter على رقم التشغيل: يتحقق من الطقم، يستدعي أجره تلقائياً،
        ثم ينقل المؤشر إلى خانة الأجر. لا ينتقل إن كان الرقم فارغاً أو
        غير موجود — فيبقى المؤشر في مكانه للتصحيح."""
        no = self.barcode.text().strip()
        if not no:
            return
        try:
            with db() as conn:
                wo = inventory.get_wo_by_no(conn, no)
            if not wo:
                raise ValueError(f"لا يوجد طقم برقم التشغيل {no}")
            # موديل الطقم يظهر تلقائياً من دليل الموديلات
            try:
                mn = (wo["model_no"] if "model_no" in wo.keys() else "") or ""
                if mn:
                    self.model_no.setCurrentText(str(mn))
            except Exception:
                pass
            # استدعاء أجر الطقم تلقائياً ليكون جاهزاً للتعديل أو التأكيد
            if self.line_wage.value() <= 0:
                self.line_wage.setValue(kv.rate(wo["wage_per_gram"] or 0))
            self.line_wage.setFocus()
            self.line_wage.selectAll()
        except Exception as e:
            err(self, e)

    def add_item(self):
        no = self.barcode.text().strip()
        if not no:
            return
        try:
            is_sale = self.kind.currentData() == "sale"
            with db() as conn:
                wo = inventory.get_wo_by_no(conn, no)
                if not wo and no == BULK_WO_NO:
                    wo = inventory.get_or_create_bulk_wo(conn,
                                                         self.user["username"])
            if not wo and not is_sale:
                # **مرتجع لرقم تشغيل غير مسجّل**: بضاعة قديمة تعود
                # للمصنع قبل تشغيل النظام. نسمح بإدخالها بوزنها فيُنشأ
                # الطقم بحالة «مباع» ثم يُرجعه المرتجع للمخزون — فيبقى
                # القيد المزدوج سليماً ويُثبت الذهب في مكانه الصحيح.
                dlg = NewReturnItemDialog(self, no)
                if dlg.exec_() != QtWidgets.QDialog.Accepted:
                    return
                d = dlg.values()
                with db() as conn:
                    # الطقم يُنشأ بمكافئ 18 مهما كان عيار الإدخال
                    wo = inventory.create_return_stub(
                        conn, no, kv.store(d["gold"]), kv.store(d["small"]),
                        kv.store(d["big"]), d["rate"],
                        kv.rate_store(d["wage"]), self.user["username"])
            if not wo:
                raise ValueError(
                    f"لا يوجد طقم برقم التشغيل {no}"
                    + (" — تحقق من الرقم أو أدخله من شاشة التوريد"
                       if is_sale else ""))

            if wo["is_bulk"]:
                # الرصيد والمقارنة بعيار العرض معاً — مقارنة رقمٍ
                # معروضٍ برقمٍ مخزَّنٍ تُنذر خطأً حيث لا خطأ.
                avail = kv.g(wo["registered_weight"])
                dlg = BulkWeightDialog(self, avail, is_sale)
                if dlg.exec_() != QtWidgets.QDialog.Accepted:
                    return
                weight = dlg.value()
                if weight <= 0:
                    raise ValueError("أدخل وزناً أكبر من صفر")
                # الرقم التجميعي يقبل التجاوز (يصير رصيده سالباً)،
                # لكن ننبّه المستخدم فلا يمرّ خطأ إدخال بلا انتباه.
                if is_sale and weight > avail + 0.001:
                    if not ask(self,
                               f"الوزن المطلوب {weight:,.2f} {kv.unit()} "
                               f"يتجاوز المتاح {avail:,.2f} {kv.unit()} "
                               f"في الرقم التجميعي.\n\n"
                               f"سيصبح رصيده سالباً "
                               f"({avail - weight:,.2f} "
                               f"{kv.unit()}).\n\nالمتابعة؟"):
                        return
            else:
                # حالة الطقم تُشترط عند **إنشاء** فاتورة جديدة فقط.
                # أما تعديل فاتورة قائمة فتصحيح لمستند سابق: حالة
                # الطقم اليوم نتيجة آخر حركة له — وقد تكون حركةً بعد
                # هذه الفاتورة — و`update_invoice` لا يمسّ المخزون إلا
                # إن كانت هذه الفاتورة آخر حركة فعلاً. فاشتراط الحالة
                # هنا يمنع تصحيحاً مشروعاً (كتعديل أجر) بلا سبب.
                need = "in_stock" if is_sale else "sold"
                if self.editing_id is None and wo["status"] != need:
                    raise ValueError(
                        f"الطقم {no} حالته لا تسمح: "
                        + ("يجب أن يكون بالمخزون للبيع/التحويل" if is_sale
                           else "يجب أن يكون خارجاً/مباعاً للمرتجع"))
                if any(i["wo"]["id"] == wo["id"] for i in self.items):
                    raise ValueError("الطقم مضاف مسبقاً للفاتورة")
                weight = kv.g(wo["registered_weight"])

            # الأجر: قيمة الحقل إن أُدخلت، وإلا أجر الطقم الافتراضي.
            # كلاهما بعيار العرض — والتحويل عند الحفظ وحده.
            wage = self.line_wage.value()
            if wage <= 0:
                wage = kv.rate(wo["wage_per_gram"] or 0.0)
            # ربط الطقم بالموديل المكتوب إن لم يكن له موديل
            self._apply_model(wo)
            with db() as conn:
                wo = inventory.get_wo_by_no(conn, wo["work_order_no"]) or wo
            self.items.append({"wo": wo, "weight": round(weight, 3),
                              "wage": wage})
            self.barcode.clear()
            # الموديل يُمسح بعد كل سطر: تركه يجعل الطقم التالي يرث
            # موديل سابقه فيُسجَّل خطأً في الدليل.
            self.model_no.setCurrentText("")
            self.line_wage.setValue(0)
            self.barcode.setFocus()      # العودة لرقم التشغيل مباشرة
            self.render_items()
        except Exception as e:
            err(self, e)

    def remove_item(self):
        """يحذف السطر — ويفكّ ربط الموديل الذي سُجّل في هذه الجلسة.

        **لماذا**: لو أخطأ المستخدم في رقم الموديل ثم حذف السطر
        ليعيده، يجب أن يعود الطقم بلا موديل فيُدخل الصحيح — لا أن
        يرث الخطأ. أما موديل كان مسجّلاً قبل الجلسة فيبقى كما هو.
        """
        r = self.items_table.currentRow()
        if not (0 <= r < len(self.items)):
            return
        it = self.items.pop(r)
        try:
            wo = it.get("wo") or {}
            wid = wo["id"] if "id" in wo.keys() else None
            sess = getattr(self, "_session_models", {})
            if wid is not None and wid in sess:
                from models import models_catalog as mc
                with db() as conn:
                    mc.assign_model(conn, wid, sess.pop(wid),
                                    self.user["username"])
                self._reload_models()
        except Exception:
            pass          # الموديل وصفي: فشله لا يعطّل الحذف
        self.render_items()

    def edit_line_weight(self):
        """يصحّح الوزن المقيد لسطر مُدخَل خطأً.

        الرقم التجميعي 0001 يقبل أي وزن (رصيد وزني مجمّع)، أما الطقم
        المفرد فوزنه ثابت من بطاقته — فتغييره يعني تسوية وزن يجب أن
        تمر بشاشة التسوية لا بالفاتورة، حفاظاً على سلامة المخزون.
        """
        r = self.items_table.currentRow()
        if not (0 <= r < len(self.items)):
            err(self, "اختر سطراً من جدول البنود أولاً")
            return
        it = self.items[r]
        wo = it["wo"]
        if not wo["is_bulk"]:
            if not ask(self,
                       f"الطقم {wo['work_order_no']} وزنه المقيد "
                       f"{kv.g(wo['registered_weight']):,.2f} "
                       f"{kv.unit()} من بطاقته.\n\n"
                       f"تغييره هنا يخالف بطاقة الطقم — الأصح تعديله "
                       f"من شاشة تسوية وزن الطقم.\n\n"
                       f"هل تريد المتابعة على أي حال؟"):
                return
        cur = float(it.get("weight") or 0)
        val, ok = QtWidgets.QInputDialog.getDouble(
            self, "تعديل الوزن المقيد",
            f"الوزن المقيد للطقم {wo['work_order_no']} "
            f"({kv.unit()}):",
            cur, 0.0, 1000000.0, 3)
        if not ok:
            return
        if val <= 0:
            err(self, "الوزن يجب أن يكون أكبر من صفر")
            return
        it["weight"] = round(val, 3)
        self.render_items()

    def edit_line_wage(self):
        r = self.items_table.currentRow()
        if not (0 <= r < len(self.items)):
            err(self, "اختر سطراً من جدول البنود أولاً")
            return
        cur = self.items[r]["wage"]
        val, ok = QtWidgets.QInputDialog.getDouble(
            self, "تعديل الأجر",
            f"أجر الجرام للطقم {self.items[r]['wo']['work_order_no']}:",
            float(cur or 0), 0.0, 100000.0, 2)
        if ok:
            self.items[r]["wage"] = val
            self.render_items()

    def _remember_model_change(self, wo, before):
        """يسجّل أن الموديل رُبط في هذه الجلسة — ليُفكّ عند الحذف."""
        try:
            self._session_models = getattr(self, "_session_models", {})
            self._session_models[wo["id"]] = before or ""
        except Exception:
            pass

    def _apply_model(self, wo):
        """يربط الطقم بالموديل المكتوب إن لم يكن له موديل.

        **الطبيعة**: الموديل تصنيف وصفي لا مالي — ربطه أو تغييره لا
        يمسّ أي رصيد. يُسجَّل مرة ويبقى مع الطقم، إلا أن يُغيَّر صراحةً.
        """
        try:
            typed = self.model_no.currentText().strip()
            if not typed:
                return
            cur = (wo["model_no"] if "model_no" in wo.keys() else "") or ""
            if cur.strip() == typed:
                return
            from models import models_catalog as mc
            with db() as conn:
                mc.assign_model(conn, wo["id"], typed,
                                self.user["username"])
            # نحفظ الموديل السابق ليُستعاد إن حُذف السطر
            self._remember_model_change(wo, cur)
            self._reload_models()
        except Exception:
            pass          # الموديل وصفي: فشله لا يوقف البيع

    def _reload_models(self):
        """يحدّث قائمة اقتراح الموديلات."""
        try:
            from models import models_catalog as mc
            with db() as conn:
                names = mc.model_names(conn)
            cur = self.model_no.currentText()
            self.model_no.clear()
            self.model_no.addItems(names)
            self.model_no.setCurrentText(cur)
        except Exception:
            pass

    def _model_clicked(self, row, col):
        """النقر على خانة الموديل يفتح صورته المحفوظة.

        من يبيع أو يرتجع يحتاج التأكد من شكل الموديل، وكان ذلك يتطلب
        ترك الشاشة والبحث في دليل الموديلات. الصورة وصفية بحتة بلا أي
        أثر محاسبي، فعرضها هنا لا يمسّ شيئاً.
        """
        if col != 0:
            return
        try:
            show_model_image(self, cell(self.items_table, row, 0))
        except Exception as e:
            info(self, str(e), "صورة الموديل")

    def render_items(self):
        cid = self.customer.currentData()
        internal = cid is not None and self._is_internal(cid)
        rows = []
        for it in self.items:
            w, wo = it["wo"], it["wo"]
            wage = 0.0 if internal else (it["wage"] or 0.0)
            weight = it["weight"]
            if wo["is_bulk"]:
                gold = small = big = after = 0.0
                standing = weight
            else:
                gold, small = (kv.g(wo["gold_weight"]),
                               kv.g(wo["small_stones"]))
                big = kv.g(wo["big_stones"])
                after = kv.g(wo["stones_after_discount"])
                standing = kv.g(wo["standing_gold"])
            mn = (wo["model_no"] if "model_no" in wo.keys() else "") or "—"
            # 🖼 يسبق الموديل الذي له صورة محفوظة — فيُعرف القابل للنقر
            if mn != "—" and has_model_image(mn):
                mn = f"🖼 {mn}"
            rows.append((mn, wo["work_order_no"], gold, small, big, after,
                        weight, standing, wage,
                        gold_math.total_wages(wage, weight)))
        fill(self.items_table, COLS, rows)
        self.recalc()

    def recalc(self):
        cid = self.customer.currentData()
        internal = cid is not None and self._is_internal(cid)
        w = round(sum(i["weight"] for i in self.items), 3)
        if internal:
            self.totals.setText(
                f"الوزن: {w:.2f} {kv.unit()} — تحويل داخلي "
                "(بلا أجور ولا ضريبة)")
            return
        wages = round(sum(gold_math.total_wages(i["wage"] or 0.0, i["weight"])
                          for i in self.items), 2)
        if self.vat_check.isChecked():
            vat = gold_math.wages_vat(wages)
            tail = f"الضريبة 15%: {vat:,.2f} | الإجمالي: {wages + vat:,.2f} ريال"
        else:
            tail = f"الإجمالي: {wages:,.2f} ريال (غير ضريبية — بدون QR)"
        self.totals.setText(
            f"الوزن: {w:.2f} {kv.unit()} | الأجور: {wages:,.2f} | {tail}")
        self._update_live_balance(cid, w, wages)

    def _update_live_balance(self, cid, weight, wages):
        """أرصدة العميل اللحظية بعد ترحيل الفاتورة الحالية:
        الرصيد الحالي + أثر هذه الفاتورة (مبيعات تزيد المديونية،
        مرتجع يخفّضها)."""
        if cid is None:
            self.live_balance.setText("")
            return
        try:
            with db() as conn:
                gold_bal, cash_bal = entities.balances(conn, cid)
        except Exception:
            self.live_balance.setText("")
            return
        sign = -1 if self.kind.currentData() == "sale_return" else 1
        # الحساب بمكافئ 18 (وحدة الرصيد) ثم العرض بعيار المصنع
        gold_after = round(gold_bal + sign * kv.store(weight), 3)
        cash_after = round(cash_bal + sign * wages, 2)
        self.live_balance.setText(
            f"إجمالي الوزن المقيد بعد الفاتورة: "
            f"{kv.g(gold_after):,.2f} {kv.unit()}   |   "
            f"إجمالي الأجور بعد الفاتورة: {cash_after:,.2f} ريال")

    # ---- الحفظ ----
    def save(self):
        try:
            cid = self.customer.currentData()
            if cid is None:
                raise ValueError("اختر العميل أو الطرف المقابل")
            if not self.items:
                raise ValueError("أضف طقماً واحداً على الأقل")
            internal = self._is_internal(cid)
            apply_vat = False if internal else self.vat_check.isChecked()
            # الحد الفاصل: كل ما يعبر إلى القاعدة بمكافئ 18
            cart = [{"work_order_id": i["wo"]["id"],
                     # سطرٌ حُمِّل من فاتورةٍ تُعدَّل يحمل رقمه؛
                     # والمُضاف حديثاً بلا رقم فيُسجَّل سطراً جديداً
                     "item_id": i.get("item_id"),
                     "weight": kv.store(i["weight"]),
                     "wage_override": (None if internal
                                       else kv.rate_store(i["wage"]))}
                    for i in self.items]
            desc = self.description.text().strip()
            # تأكيد الترحيل: أثر محاسبي لا يُلغى إلا بقيد عكسي
            kind_label = ("فاتورة مبيعات"
                          if self.kind.currentData() == "sale"
                          else "فاتورة مرتجع")
            tot_w = sum(float(i.get("weight") or 0) for i in self.items)
            tot_wage = sum(float(i.get("wage") or 0) * float(i.get("weight") or 0)
                           for i in self.items)
            if not confirm_post(
                    self,
                    f"{kind_label}\n\n"
                    f"الطرف: {self.customer.currentText()}\n"
                    f"عدد الأطقم: {len(self.items)}\n"
                    f"الوزن المقيد: {tot_w:,.2f} {kv.unit()}\n"
                    f"الأجور: {tot_wage:,.2f} ريال\n"
                    f"التاريخ: {dstr(self.date)}"
                    + ("\n\nفاتورة ضريبية (15%)" if apply_vat else "")):
                return
            # حارس وضع التعديل: لو حُذفت الفاتورة الأصلية بعد فتحها
            # للتعديل، لا يجوز محاولة تعديلها — نخرج من الوضع تلقائياً
            # وتُحفظ العملية كفاتورة جديدة مستقلة، فلا تضيع صامتة.
            if self.editing_id is not None:
                with db() as conn:
                    alive = conn.execute(
                        "SELECT 1 FROM invoices WHERE id=? AND is_deleted=0",
                        (self.editing_id,)).fetchone()
                if not alive:
                    self.editing_id = None
                    self._update_mode()
            # الترحيل داخل مؤشر انشغال: النافذة تُرسم وتُعطَّل فلا
            # يظهر «لا يستجيب» ولا يُقبل ضغطٌ مكرّر ينتج فاتورة ثانية.
            with busy(self, "جارٍ ترحيل الفاتورة…", stage="ترحيل فاتورة"):
                with db() as conn:
                    if self.editing_id is not None:
                        # تعديل **في مكانه**: نفس رقم الفاتورة وتاريخها،
                        # والفرق وحده يُرحَّل — لا فاتورة جديدة ولا قيد
                        # عكسي، فتبقى العملية عمليةً واحدة في السجل.
                        res = invoices.update_invoice(
                            conn, self.editing_id, cart,
                            self.user["username"], apply_vat=apply_vat,
                            description=desc)
                    elif self.kind.currentData() == "sale":
                        res = invoices.create_sale(
                            conn, cid, cart, dstr(self.date),
                            self.user["username"], apply_vat, desc,
                            qr_enabled=self.qr_check.isChecked())
                    else:
                        res = invoices.create_sale_return(
                            conn, cid, cart, dstr(self.date),
                            self.user["username"], apply_vat, desc,
                            qr_enabled=self.qr_check.isChecked())
            # ══ نشر صفحة الفاتورة — **بعد إغلاق المعاملة، وخارج خيط
            #    الواجهة** ══
            # الرفع داخل معاملة الكتابة يحبس قفل القاعدة ثوانيَ فتتعطّل
            # المزامنة — لذلك هو هنا والمعاملة مغلقة. وكان يجري مع ذلك
            # على خيط الواجهة داخل `busy`: فعلى اتصالٍ بطيء تبقى
            # النافذة **سوداء لا تستجيب** عشر ثوانٍ بعد كل ترحيل، وهي
            # شكوى المستخدم بعينها. الآن في خيطٍ جانبي وحلقةُ الأحداث
            # تعمل، بسقف انتظارٍ عشر ثوانٍ: بعده يُكمل الرفع في
            # الخلفية ولا يُحبَس أحدٌ خلف شبكةٍ لا تستجيب.
            # يشمل التعديل: `update_invoice` يُلغي صلاحية الصفحة
            # المنشورة، فتُعاد كتابتها هنا على **المسار نفسه** — فورقة
            # العميل القديمة تبقى صحيحة وتعرض الفاتورة بعد تعديلها.
            if res.get("id"):
                try:
                    from services import invoice_share
                    _iid, _co = res["id"], config.COMPANY_NAME
                    run_bg(lambda: invoice_share.ensure_published(_iid, _co),
                           parent=self, text="جارٍ تجهيز صفحة الفاتورة…",
                           stage="نشر صفحة الفاتورة", timeout=10.0)
                except Exception:
                    pass          # تعذّر النشر لا يُبطل ترحيلاً تمّ

            if res.get("added") is not None and self.editing_id is not None:
                parts = []
                if res.get("added"):
                    parts.append(f"أُضيف {len(res['added'])} طقم")
                if res.get("updated"):
                    parts.append(f"عُدّل {len(res['updated'])}")
                if res.get("removed"):
                    parts.append(f"حُذف {len(res['removed'])}")
                touched = res.get("stock_touched") or []
                stock = ("\n\nتأثّر المخزون: "
                         + " · ".join(touched)
                         + "\n(هذه الفاتورة آخر حركة لها)"
                         if touched else
                         "\n\nلم يتأثر المخزون: للأطقم حركات أحدث "
                         "من هذه الفاتورة، فحالتها اليوم تتبع آخر "
                         "حركة لا هذه.")
                info(self,
                     f"عُدّلت الفاتورة {res['invoice_no']} في مكانها.\n"
                     + ("   ·   ".join(parts) or "لا تغيير")
                     + f"\n\nالوزن: "
                       f"{kv.g(res.get('total_weight', 0)):,.2f} "
                       f"{kv.unit()}"
                       f"   ·   الأجور: {res.get('total_wages', 0):,.2f} ريال"
                     + stock
                     + "\n\nرقم الفاتورة وتاريخها لم يتغيّرا.")
            elif res["internal"]:
                posted(self, f"تم ترحيل التحويل الداخلي {res['invoice_no']} — "
                           f"الوزن: {kv.g(res['total_weight']):.2f} "
                           f"{kv.unit()} — إلى "
                           f"{res['customer_name']}", "invoices", res["id"])
            elif res["vat_applied"]:
                QRDialog(self, res).exec_()
            else:
                posted(self, f"تم ترحيل الفاتورة {res['invoice_no']} "
                             f"(غير ضريبية) — الإجمالي "
                             f"{res['grand_total']:,.2f} ريال",
                       "invoices", res["id"])
            self.editing_id = None
            self.description.clear()
            self.clear_items()
            self._update_mode()
            # المسوّدة تُمحى فور الترحيل — بديلٌ عن الذاكرة لا عن
            # الدفتر، فلا يجوز أن تُعيد أسطراً صارت قيداً.
            self.live_note.setVisible(False)
            drafts.clear(DRAFT_KEY, self.user.get("username"))
            with busy(self, "جارٍ تحديث الشاشة…", stage="تحديث المبيعات"):
                self.refresh()
        except Exception as e:
            err(self, e)

    def refresh(self):
        self._reload_models()
        with db() as conn:
            self.customers = entities.list_customers(conn)
        reload_combo(self.customer, self.customers,
                    lambda r: ("🏭 " if r["is_internal"] else
                              f"[{entities.TYPE_LABELS[r['entity_type']]}] ")
                              + r["name"])
        self.render_items()
        self.customer_changed()
        # الاستعادة بعد تعبئة قائمة العملاء: قبلها لا يوجد ما يُختار
        # منه، فيضيع العميل المحفوظ في المسوّدة.
        self._restore_draft()
