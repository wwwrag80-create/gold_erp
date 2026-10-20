# -*- coding: utf-8 -*-
"""شاشة المبيعات والمرتجعات — ثلاث طبقات: العملية والطرف (ومن أي حساب
يخرج الذهب)، ثم سطر إدخال الطقم بترتيب الورقة نفسها والتنقّل فيه
بـEnter والأسهم، ثم البنود بأعمدة الفاتورة المطبوعة حرفياً وصفُّ
إجماليٍّ في ذيلها ولوحاتُ ما بعد الفاتورة.

تدعم: عيار إدخالٍ لكل سطر (والقيد بمكافئ 18 دائماً)، والتحويل الداخلي
(إعادة تشغيل)، والرقمان التجميعيان 00010 و0010 بالوزن الجزئي، والمرتجع لرقم تشغيل
غير مسجّل، وإشعاراً مديناً ضريبياً لفاتورة سابقة غير ضريبية.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from ui import kit

import config
from database.database import db
from models import entities, inventory, invoices, pending, stock_home
from models.accounts import acc_id
from models.inventory import BULK_LABEL, is_bulk_no
from services import drafts
from services import gold_math, karat_view as kv
from ui.widgets.common import (busy, cell, confirm_post, posted, ask,
                               big_label, date_edit, dstr, enter_chain, err,
                               fill, has_model_image, info, load_pref,
                               make_table, mspin, reload_combo,
                               row_action_buttons, row_height, run_bg,
                               save_pref, search_combo, show_model_image,
                               TitledSections, wspin)
from ui.widgets.table_fit import fit_columns

DRAFT_KEY = "sales"


class _HeldEnterGuard(QtCore.QObject):
    """إصبعٌ باقٍ على Enter لا يضيف السطر (4.61).

    المفتاح المضغوط باستمرار يكرّر نفسه (auto-repeat) عشرات المرات في
    الثانية: فكان يمشي على الخانات حتى الأجر — وهذا مقصود — ثم تُحسب
    تكراراته «الضغطةَ الثانية» فيُضاف السطر قبل أن تُرفع اليد. الآن عند
    الوقفة على الأجر لا يضيف السطر إلا **ضغطةٌ جديدة بعد رفع الإصبع**:
    تكرارات المفتاح تُبتلع، ويُشترط تحريرٌ حقيقي له منذ الوقفة.

    يُركَّب على خانة الأجر **بعد** سلسلة Enter فيسبقها (آخر مرشّحٍ
    يُركَّب هو أول من يرى الحدث).
    """

    KEYS = (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter)

    def __init__(self, screen):
        super().__init__(screen)
        self.screen = screen

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t not in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            return False
        if ev.key() not in self.KEYS:
            return False
        if t == QtCore.QEvent.KeyRelease:
            # تحريرٌ حقيقي — لا ما يولّده التكرار التلقائي في بعض الأنظمة
            if not ev.isAutoRepeat():
                self.screen._enter_up = True
            return False
        if self.screen._wage_armed and (ev.isAutoRepeat()
                                        or not self.screen._enter_up):
            return True           # الإصبع ما زال على Enter: لا إضافة
        return False


class _WageDelegate(QtWidgets.QStyledItemDelegate):
    """خانتا الأجر في جدول البنود تُكتبان في مكانهما (4.59).

    كان تصحيح أجر سطرٍ يمرّ بنافذة «✎» كاملة، ومراجعةُ أجور فاتورةٍ من
    عشرة أسطر عشرُ نوافذ. الآن نقرةٌ على الخانة تفتحها للكتابة، وEnter
    يحفظ وينزل إلى خانة الأجر في السطر التالي مفتوحةً — فتُراجَع أجور
    الفاتورة كلها متتابعةً بلوحة المفاتيح. ↑ ↓ تصعد وتنزل كذلك، وEsc
    يتراجع عمّا كُتب. والخانة حقلٌ ذكي كخانات الإدخال: «120+35» تُحسب،
    والأرقام العربية تُقبل.

    ما يُكتب يدخل بيانات السطر **فوراً** (`_set_inline_wage`)؛ وإعادةُ رسم
    الجدول والنزول للسطر التالي تتأخّر لحظةً حتى تُغلق الخانة — فترحيلٌ
    بـF2 والخانة مفتوحة لا يفوته الرقم الجديد.
    """

    def __init__(self, screen):
        super().__init__(screen.items_table)
        self.screen = screen
        self.editor = None
        self.index = None
        self.move = 0
        self.cancelled = False

    def createEditor(self, parent, option, index):
        ed = mspin()
        ed.setParent(parent)
        ed.setAlignment(QtCore.Qt.AlignCenter)
        ed.setFrame(False)
        ed.setToolTip("Enter يحفظ وينزل للسطر التالي · ↑ ↓ تنقّل · "
                      "Esc تراجع")
        self.editor = ed
        self.index = QtCore.QPersistentModelIndex(index)
        self.move = 0
        self.cancelled = False
        return ed

    def setEditorData(self, editor, index):
        # Qt يحدّد النص كله عند الفتح، فالكتابة تستبدل القيمة كلها
        editor.setValue(self.screen._inline_value(index.row(),
                                                  index.column()))

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)

    def setModelData(self, editor, model, index):
        """لا يُكتب نصٌّ في الخانة: السطر يُحدَّث ثم يُعاد رسم الجدول."""
        if self.cancelled:
            return
        self.cancelled = True          # مرةً واحدة لكل فتح
        try:
            editor.interpretText()
            val = editor.value()
        except RuntimeError:
            return
        row, col, move = index.row(), index.column(), self.move
        self.move = 0
        changed = self.screen._set_inline_wage(row, col, val)
        QtCore.QTimer.singleShot(
            0, lambda: self.screen._after_inline_wage(row, col, move,
                                                     changed))

    def eventFilter(self, editor, ev):
        if ev.type() == QtCore.QEvent.KeyPress:
            k = ev.key()
            if k in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                self.move = 1
            elif k in (QtCore.Qt.Key_Down, QtCore.Qt.Key_Up,
                       QtCore.Qt.Key_Tab, QtCore.Qt.Key_Backtab):
                # السهمان يزيدان قيمة الحقل وينقصانها في العادة — وهنا
                # يتنقّلان بين الأسطر. وTab لا يتجوّل في خانات السطر
                # الأخرى (لا تُكتب): يحفظ ويبقى.
                self.move = {QtCore.Qt.Key_Down: 1,
                             QtCore.Qt.Key_Up: -1}.get(k, 0)
                self.commitData.emit(editor)
                self.closeEditor.emit(
                    editor, QtWidgets.QAbstractItemDelegate.NoHint)
                return True
        return super().eventFilter(editor, ev)

    def is_open(self):
        try:
            return self.editor is not None and self.editor.isVisible()
        except RuntimeError:
            self.editor = None
            return False

    def flush(self):
        """ما كُتب في الخانة المفتوحة يُعتمد الآن — قبل الترحيل أو التعليق
        أو تفريغ الفاتورة."""
        if not self.is_open() or self.cancelled or self.index is None:
            return False
        ed = self.editor
        try:
            ed.interpretText()
            val = ed.value()
        except RuntimeError:
            return False
        row, col = self.index.row(), self.index.column()
        self.cancelled = True
        self.closeEditor.emit(ed, QtWidgets.QAbstractItemDelegate.NoHint)
        if self.screen._set_inline_wage(row, col, val):
            self.screen._after_inline_wage(row, col, 0, True)
        return True

    def cancel(self):
        """Esc والخانة مفتوحة: تُغلق كما كانت بلا حفظ."""
        if not self.is_open():
            return False
        self.cancelled = True
        self.closeEditor.emit(
            self.editor, QtWidgets.QAbstractItemDelegate.RevertModelCache)
        self.screen.items_table.setFocus()
        return True


class NewCustomerDialog(QtWidgets.QDialog):
    def __init__(self, parent, username):
        super().__init__(parent)
        self.username = username
        self.customer_id = None
        self.setWindowTitle("عميل جديد")
        self.name = kit.LineEdit()
        self.phone = kit.LineEdit()
        self.vat = kit.LineEdit()
        form = QtWidgets.QFormLayout(self)
        form.addRow("الاسم:", self.name)
        form.addRow("الجوال:", self.phone)
        form.addRow("الرقم الضريبي:", self.vat)
        btn = kit.PushButton("حفظ")
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
    """نافذة إدخال الوزن المطلوب من رقمٍ تجميعي (00010 أو 0010)."""

    def __init__(self, parent, available, is_sale, wo_no=""):
        super().__init__(parent)
        self.setWindowTitle(f"الرقم التجميعي {wo_no}".strip())
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
        self.invoice = kit.ComboBox()
        self.date = date_edit()
        self.preview = big_label()
        self.invoice.currentIndexChanged.connect(self.update_preview)
        btn = kit.PushButton("إصدار الإشعار وترحيل قيد الضريبة")
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
        self.adj_dir = kit.ComboBox()
        self.adj_dir.addItem("زيادة رصيد العميل المدين (عليه)", "debit")
        self.adj_dir.addItem("تخفيض رصيد العميل (له)", "credit")
        self.adj_contra = kit.ComboBox()
        self.adj_contra.addItem("حساب التسويات المباشرة (2900)", "adjust")
        self.adj_contra.addItem("حساب ضريبة المخرجات (2100)", "vat")
        self.adj_date = date_edit()
        self.adj_note = kit.LineEdit()
        self.adj_note.setPlaceholderText("بيان التسوية (اختياري)")
        self.adj_prev = big_label()
        btn = kit.PushButton("ترحيل التسوية المباشرة")
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


class _Panel(QtWidgets.QFrame):
    """لوحةُ رقمٍ واحد: عنوانٌ صغير، ثم الرقم كبيراً، ثم سطرُ شرح.

    الأرقام التي يُسأل عنها بعد كل فاتورة (الوزن · الأجور · رصيد
    العميل) كانت سطراً نصياً واحداً تحت الجدول تقرؤه العين بجهد.
    هنا كلُّ رقمٍ في لوحته، فيُلتقط بنظرةٍ لا بقراءة.
    """

    def __init__(self, title, sub=""):
        # مدمجة (سطرٌ للعنوان والرقم): الجدول فوقها يأخذ المساحة كلّها،
        # والشاشة كلّها أمام العين بلا تمريرٍ صعوداً ونزولاً
        super().__init__()
        self.setObjectName("chip")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setSpacing(0)
        lay.setContentsMargins(10, 4, 10, 4)
        row = QtWidgets.QHBoxLayout()
        t = QtWidgets.QLabel(title)
        t.setObjectName("chipTitle")
        self.value = QtWidgets.QLabel("—")
        self.value.setObjectName("chipValue")
        row.addWidget(t)
        row.addStretch(1)
        row.addWidget(self.value)
        lay.addLayout(row)
        self.sub = QtWidgets.QLabel(sub, self)
        self.sub.setObjectName("chipSub")
        lay.addWidget(self.sub)
        self.sub.setVisible(bool(sub))
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred,
                           QtWidgets.QSizePolicy.Maximum)

    def set_value(self, value, sub=None):
        self.value.setText(value)
        if sub is not None:
            self.sub.setText(sub)
            self.sub.setVisible(bool(sub))


class NewSourceDialog(QtWidgets.QDialog):
    """حسابُ مخزنٍ جديد يخرج منه ذهب الفواتير.

    يُضاف تحت مجموعة الذهب والمخازن فيرث طبيعتها، فلا يُسأل المستخدم
    عن نوعٍ ولا طبيعةٍ ولا كود — الاسم وحده، والباقي من الشجرة.
    """

    def __init__(self, parent, username):
        super().__init__(parent)
        self.username = username
        self.account_id = None
        self.setWindowTitle("حساب مخزن جديد")
        self.setMinimumWidth(420)
        self.name = kit.LineEdit()
        self.name.setPlaceholderText("مثال: مخزن ذهب المعرض")
        note = QtWidgets.QLabel(
            "يُنشأ الحساب تحت «الأصول المتداولة — الذهب والمخازن» "
            "بقياسٍ وزني، فيصلح فوراً حساباً يخرج منه ذهب الفاتورة "
            "ويظهر له كشف حسابٍ مستقل.")
        note.setWordWrap(True)
        note.setObjectName("cardSub")
        form = QtWidgets.QFormLayout(self)
        form.addRow(note)
        form.addRow("اسم الحساب:", self.name)
        box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        box.accepted.connect(self.save)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def save(self):
        try:
            from models import coa
            with db() as conn:
                res = coa.add_sub_account(
                    conn, acc_id(conn, invoices.GOLD_GROUP),
                    self.name.text().strip(), self.username,
                    measurement="gold")
            self.account_id = res["id"]
            self.accept()
        except Exception as e:
            err(self, e)


class SalesScreen(QtWidgets.QWidget):
    """المبيعات والمرتجعات — ثلاث طبقات لا واحدة.

    **لماذا أُعيد تصميمها**: كانت الشاشة صفَّ حقولٍ واحداً يخلط رأس
    العملية (الطرف والتاريخ والضريبة) بسطر الإدخال (الطقم وأجره)،
    فيقرأ العين في السطر الواحد شيئين مختلفين. والترتيب المحاسبي
    الصحيح ثلاث طبقات، كلٌّ تُقرأ مرةً واحدة في وقتها:

      ① **العملية والطرف** — يُملأ مرةً في أول الفاتورة: النوع، ثم
         مَن، ثم **من أي حساب** يخرج الذهب (والعيار إن كان كسراً).
      ② **سطر الإدخال** — يتكرّر مع كل طقم، بترتيب الورقة نفسه:
         الموديل ← رقم التشغيل ← المقيد ← القائم ← الأجر ← العيار ←
         الذهب ← الفصوص ← الأحجار ← بعد الخصم. وEnter والأسهم تنقل
         بين خاناته فلا تُترك لوحة المفاتيح لالتقاط الفأرة.
      ③ **البنود والخلاصة** — الجدول بأعمدة الفاتورة المطبوعة حرفياً،
         وصفُّ إجماليٍّ في ذيله، ثم لوحات ما بعد الفاتورة.

    **ما لا يتغيّر**: كل وزنٍ يعبر إلى القاعدة بمكافئ عيار 18 مهما
    كان عيار الإدخال (`services.karat_view`)، والقيد كما هو تماماً.
    عيارُ السطر **وحدةُ كتابةٍ وقراءة** لا أكثر — يُحفظ مع السطر
    ليُعاد عرضه كما كُتب.
    """

    # العمود الأول بلا عنوان: فيه زرّا تعديل السطر وحذفه.
    COLS = ["", "الموديل", "رقم التشغيل", "العيار", "الحساب", "الوزن المقيد",
            "الوزن القائم", "الذهب", "الفصوص", "الأحجار",
            "الأحجار بعد الخصم", "الأجر/جم", "الأجرة (ريال)"]
    # أوزان العرض (مجموعها 100): عمود الأزرار يكفيه القليل
    COL_W = [5, 9, 9, 6, 10, 8, 8, 7, 7, 7, 8, 7, 9]
    # خانتا الأجر — تُكتبان في مكانهما (4.59)
    C_WAGE, C_AMOUNT = 11, 12
    WAGE_COLS = (C_WAGE, C_AMOUNT)

    def __init__(self, user):
        super().__init__()
        self.user = user
        self.items = []          # [{wo, weight, wage, karat, مكوّنات}]
        self.editing_id = None
        self.customers = []
        self.sources = []
        self._agreed_wage = 0.0      # بعيار العرض · صفر = بلا اتفاق
        self._calc = False           # حارس إعادة الحساب المتبادل
        self._reg_manual = False     # هل كُتب الوزن المقيد يدوياً؟
        self._rate = config.STONE_DISCOUNT_RATE
        self._wo = None              # آخر طقمٍ استُدعي في سطر الإدخال
        self._held_bar = None        # إشعار «مدة بقاء الطقم» في المرتجع
        self._w18 = [0.0] * 6        # ظلُّ الأوزان بمكافئ 18
        self._wage18 = 0.0           # وظلُّ الأجر
        self._held_id = None         # المعلّقة المفتوحة للاستكمال

        # قسمان (4.44): «إصدار فاتورة» و«المعلّقات» — فواتير بدأ
        # إعدادها ولم تُثبت: بلا قيدٍ ولا أثر حتى تُستكمل وتُرحَّل
        issue = QtWidgets.QWidget()
        il = QtWidgets.QVBoxLayout(issue)
        il.setContentsMargins(0, 4, 0, 0)
        il.addWidget(self._build_header())
        il.addWidget(self._build_entry())
        il.addWidget(self._build_items(), 1)
        il.addLayout(self._build_footer())
        self.tabs = TitledSections(
            "المبيعات والمرتجعات والتحويلات الداخلية — فوترة ZATCA")
        self.tabs.addTab(issue, "إصدار فاتورة")
        self.tabs.addTab(self._build_held(), "⏸ المعلّقات")
        self.tabs.currentChanged.connect(
            lambda i: self.load_held() if i == 1 else None)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self.tabs, 1)
        self._install_shortcuts()
        self._sync_kind_labels()
        self._update_mode()

    # ══════════════════════════════════════════════════════════════
    #  ① العملية والطرف
    # ══════════════════════════════════════════════════════════════

    def _build_header(self):
        box = QtWidgets.QGroupBox("① العملية والطرف")
        self.kind = kit.ComboBox()
        self.kind.addItem("فاتورة بيع", "sale")
        self.kind.addItem("مرتجع بيع", "sale_return")
        self.kind.setMinimumWidth(150)
        self.kind.currentIndexChanged.connect(self.clear_items)
        self.kind.currentIndexChanged.connect(self._clear_held)
        self.kind.currentIndexChanged.connect(self._sync_kind_labels)
        self.date = date_edit()
        self.customer = search_combo("اكتب اسم العميل أو الطرف المقابل…")
        self.customer.currentIndexChanged.connect(self.customer_changed)
        btn_new_cust = kit.PushButton("+ عميل جديد")
        btn_new_cust.setObjectName("ghost")
        btn_new_cust.clicked.connect(self.new_customer)

        # ══ من أي حساب يخرج الذهب ══
        # آخر اختيارٍ يُحفظ ويعود: من يبيع يومه كله من صندوق الكسر لا
        # يُطالَب باختياره في كل فاتورة، ومن لا يعرف الخيار أصلاً يجد
        # الذهب المشغول كما كان دائماً.
        self.source = kit.ComboBox()
        self.source.setMinimumWidth(240)
        self.source.setToolTip(
            "الحساب الذي يخرج منه ذهب هذه الفاتورة — ويعود إليه في "
            "المرتجع. يُحفظ مع الفاتورة ويُطبع عليها.")
        self.source.currentIndexChanged.connect(self._source_changed)
        self.scrap_karat = kit.ComboBox()
        self.scrap_karat.setMaximumWidth(120)
        for k in config.KARATS:
            self.scrap_karat.addItem(f"عيار {k}", k)
        self.scrap_karat.setToolTip(
            "صندوق الكسر حسابٌ واحد يضمّ الأعيرة الأربعة — وهذا يقول "
            "من أي عيارٍ خُصم الوزن فعلاً.")
        self.scrap_karat.currentIndexChanged.connect(self._save_source_pref)
        self.scrap_lbl = QtWidgets.QLabel("عيار الخصم:")
        btn_new_src = kit.PushButton("+ حساب")
        btn_new_src.setObjectName("ghost")
        btn_new_src.setToolTip("إضافة حساب مخزنٍ جديد يخرج منه الذهب")
        btn_new_src.clicked.connect(self.new_source)

        self.description = kit.LineEdit()
        self.description.setPlaceholderText(
            "البيان (اختياري) — يُحفظ مع العملية ويظهر في كشف الحساب")
        self.vat_check = kit.CheckBox("ضريبة 15% (فاتورة ضريبية + QR)")
        self.vat_check.setChecked(False)
        self.vat_check.stateChanged.connect(self.recalc)
        # ══ رمز QR لصفحة الفاتورة — قرارٌ لكل فاتورة ══
        # إنشاؤه يعني رفع صور موديلاتها إلى التخزين، فلا يُنشأ ما لم
        # يُطلب. وآخر اختيارٍ يبقى فلا يُسأل عنه كل مرة.
        self.qr_check = kit.CheckBox("رمز QR لصفحة الفاتورة")
        self.qr_check.setToolTip(
            "عند تفعيله يُطبع على الفاتورة رمزٌ يفتح صفحتها على الجوال:\n"
            "الفاتورة أولاً ثم موديلاتها بأسمائها وأعدادها.\n\n"
            "يبقى الاختيار مفعّلاً للفواتير التالية حتى تُلغيه — "
            "وما لم يُفعَّل لا يُنشأ رمز ولا تُرفع صورة ولا تُستهلك "
            "مساحة.")
        self.qr_check.setChecked(
            str(load_pref("sales_qr_enabled", "0")).strip() == "1")
        self.qr_check.stateChanged.connect(self._qr_pref_changed)
        btn_tax_note = kit.PushButton("إشعار مدين ضريبي")
        btn_tax_note.setObjectName("ghost")
        btn_tax_note.clicked.connect(self.open_tax_note)

        self.internal_note = QtWidgets.QLabel(
            "🏭 تحويل داخلي (إعادة تشغيل): تخرج الأطقم إلى خزينة التصنيع "
            "بالوزن فقط — بلا أجور ولا ضريبة.")
        self.internal_note.setObjectName("warn")
        self.internal_note.setVisible(False)
        # الأجرة المتفق عليها تُستدعى من بطاقة العميل وتظهر أمام عين
        # البائع، ويُنبَّه فوراً إن خالفها — بلا منع.
        self.wage_note = QtWidgets.QLabel("")
        self.wage_note.setObjectName("cardSub")
        self.wage_note.setProperty("live", True)     # تنبيهٌ حيّ لا شرح
        self.wage_note.setWordWrap(True)
        # 4.59: للعميل طلبٌ مفتوح من دليل الموديلات؟ يظهر هنا عند اختياره
        # برابطٍ يفتحه — فلا يُباع له وطلبه منسيّ في الدفتر
        self.order_note = QtWidgets.QLabel("")
        self.order_note.setObjectName("cardSub")
        self.order_note.setProperty("live", True)
        self.order_note.setWordWrap(True)
        self.order_note.setTextFormat(QtCore.Qt.RichText)
        self.order_note.linkActivated.connect(self._open_customer_order)
        self.order_note.setVisible(False)

        g = QtWidgets.QGridLayout(box)
        g.setHorizontalSpacing(10)
        g.addWidget(QtWidgets.QLabel("نوع العملية:"), 0, 0)
        g.addWidget(self.kind, 0, 1)
        g.addWidget(QtWidgets.QLabel("العميل / الطرف:"), 0, 2)
        g.addWidget(self.customer, 0, 3)
        g.addWidget(btn_new_cust, 0, 4)
        # العنوان يتبع نوع العملية: البيع **يخرج من** حساب، والمرتجع
        # **يدخل إلى** الحساب نفسه — فالكلمة تقول اتجاه الحركة لا
        # اسم الحقل وحده.
        self.source_lbl = QtWidgets.QLabel("من حساب:")
        g.addWidget(self.source_lbl, 0, 5)
        g.addWidget(self.source, 0, 6)
        g.addWidget(self.scrap_lbl, 0, 7)
        g.addWidget(self.scrap_karat, 0, 8)
        g.addWidget(btn_new_src, 0, 9)
        g.addWidget(QtWidgets.QLabel("التاريخ:"), 1, 0)
        g.addWidget(self.date, 1, 1)
        g.addWidget(QtWidgets.QLabel("البيان:"), 1, 2)
        g.addWidget(self.description, 1, 3, 1, 3)
        opts = QtWidgets.QHBoxLayout()
        opts.addWidget(self.vat_check)
        opts.addWidget(self.qr_check)
        opts.addWidget(btn_tax_note)
        opts.addStretch(1)
        g.addLayout(opts, 1, 6, 1, 4)
        g.addWidget(self.internal_note, 2, 0, 1, 10)
        g.addWidget(self.wage_note, 3, 0, 1, 10)
        g.addWidget(self.order_note, 4, 0, 1, 10)
        g.setColumnStretch(3, 3)
        g.setColumnStretch(6, 3)
        # ══ Enter يمضي إلى الأمام في الشاشة كلها ══
        # كان التنقّل بـEnter في سطر الإدخال وحده، فمن اختار العميل
        # أو الحساب في الرأس وقف — ويده على لوحة المفاتيح — ينتظر
        # الفأرة لينزل. الآن رأسُ الشاشة سلسلةٌ أولى تُسلّم لسطر
        # الإدخال، فالفاتورة كلها بضغطات Enter متتابعة.
        self._head_chain = [self.kind, self.customer, self.source,
                            self.scrap_karat, self.date, self.description]
        enter_chain(self, self._head_chain,
                    on_last=lambda: self.barcode)
        return box

    # ══════════════════════════════════════════════════════════════
    #  ② سطر الإدخال
    # ══════════════════════════════════════════════════════════════

    def _build_entry(self):
        # العنوان قصير — وشرح المفاتيح تلميحٌ عند الوقوف عليه لا سطرٌ
        # يزاحم الجدول
        box = QtWidgets.QGroupBox("② إدخال الطقم")
        box.setToolTip("Enter ينتقل للخانة التالية · الأسهم ← → تتنقّل · "
                       "وعند خانة الأجر يقف: Enter مرةً ثانية يضيف السطر")
        # رقم الموديل أولاً: يُملأ تلقائياً من دليل الموديلات عند
        # إدخال رقم تشغيل مسجّل، ويُكتب يدوياً للأطقم الجديدة فيُسجَّل
        # في الدليل ويبقى مرتبطاً بالطقم.
        self.model_no = kit.ComboBox()
        self.model_no.setEditable(True)
        self.model_no.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.model_no.lineEdit().setPlaceholderText("رقم الموديل")
        self.barcode = kit.LineEdit()
        self.barcode.setPlaceholderText(
            f"امسح الباركود أو اكتب الرقم ({BULK_LABEL} = رصيد تجميعي)")
        # البحث عند مغادرة الخانة لا عند Enter وحده: الماسح الضوئي
        # يُنهي بـEnter فينتقل التركيز فيقع البحث، ومن ينقر بالفأرة
        # على الخانة التالية يجد البيانات جاهزةً كذلك.
        self.barcode.editingFinished.connect(self._wo_lookup)
        self.line_reg = wspin()
        self.line_reg.setToolTip(
            "الوزن المقيد — صاحب الأثر المالي والمخزني. يظهر تلقائياً "
            "للأطقم المسجّلة، ويُكتب يدوياً للجديد وللرقم التجميعي.")
        self.line_standing = wspin()
        self.line_standing.setToolTip(
            "الذهب القائم = الذهب + الفصوص + الأحجار قبل الخصم — "
            "للمعرفة والإحصاء، بلا أثرٍ محاسبي.")
        self.line_wage = mspin()
        self.line_karat = kit.ComboBox()
        for k in config.KARATS:
            self.line_karat.addItem(f"عيار {k}", k)
        self.line_karat.setToolTip(
            "عيار أوزان هذا السطر. القيد يُخزَّن بمكافئ 18 دائماً، "
            "وتبديل العيار هنا يعيد كتابة الأوزان بعياره — فالذهب "
            "الفعلي واحدٌ لا يتغيّر.")
        self.line_karat.currentIndexChanged.connect(self._karat_changed)
        self._karat_now = kv.active()
        i = self.line_karat.findData(self._karat_now)
        if i >= 0:
            self.line_karat.setCurrentIndex(i)
        self.line_gold = wspin()
        self.line_small = wspin()
        self.line_big = wspin()
        self.line_after = wspin()
        # ثلاث منازلٍ لا منزلتان في خانات الوزن: تبديل العيار يقسم
        # ويضرب، وتقريبُ منزلتين يُرجع 40.01 بدل 40.000 بعد ذهابٍ
        # وإياب — فيبدو للمستخدم أن الرقم تغيّر من تلقاء نفسه.
        for w in (self.line_reg, self.line_standing, self.line_gold,
                  self.line_small, self.line_big, self.line_after):
            w.setDecimals(3)
        # ══ الأجر يُحفظ بمكافئ 18 في الظلّ ══
        # خانة الأجر بمنزلتين (ريالٌ وهللتان)، وتبديل العيار يضرب
        # ويقسم: 22 بعيار 18 تصير 25.67 بعيار 21، والعودة تُرجع
        # 21.99 — فتخرج فاتورة المئة جرام ناقصةً ريالاً من لا شيء.
        # فالمرجع قيمةٌ ظلّيةٌ بمكافئ 18 لا تُقرَّب، والخانة عرضٌ لها.
        self._wage18 = 0.0
        self.line_wage.valueChanged.connect(self._wage_typed)
        for w in (self.line_gold, self.line_small, self.line_big):
            w.valueChanged.connect(self._parts_changed)
        self.line_after.valueChanged.connect(self._after_changed)
        self.line_reg.valueChanged.connect(self._reg_changed)
        self.btn_add_line = kit.PushButton("+ إضافة سطر")
        self.btn_add_line.clicked.connect(self.add_item)
        # ══ سطر «أجر فقط» ══ أجرٌ على العميل بلا طقم ولا ذهب (تلميع،
        # تعديل مقاس، أجرةٌ فاتت): يدخل أجوره وحدها ولا يمسّ المخزون.
        # ويُضاف كذلك بكتابة المبلغ في خانة الأجر ورقمُ التشغيل فارغ.
        self.btn_wage_only = kit.PushButton("+ أجر فقط")
        self.btn_wage_only.setObjectName("ghost")
        self.btn_wage_only.setToolTip(
            "سطر أجرٍ بلا طقم ولا ذهب — يُضاف إلى أجور العميل وحدها.\n"
            "أو: اكتب المبلغ في خانة الأجر ورقم التشغيل فارغ ثم Enter"
            " مرتين.")
        self.btn_wage_only.clicked.connect(self.add_wage_only)

        def _sub(t):
            lbl = QtWidgets.QLabel(t)
            lbl.setObjectName("cardSub")
            lbl.setAlignment(QtCore.Qt.AlignCenter)
            return lbl

        # الترتيب كما طلبه صاحب النظام: الموديل والرقم ثم المكوّنات،
        # وفي الآخر المقيد والقائم والعيار والأجر — ما يُراجَع قبل
        # الإضافة مباشرةً، والأجرُ آخرها: Enter يقف عنده، والثانية تضيف.
        fields = [
            ("رقم الموديل", self.model_no, 2),
            ("رقم التشغيل", self.barcode, 3),
            ("الذهب", self.line_gold, 2),
            ("الفصوص", self.line_small, 2),
            ("الأحجار", self.line_big, 2),
            ("الأحجار بعد الخصم", self.line_after, 2),
            ("الوزن المقيد", self.line_reg, 2),
            ("الوزن القائم", self.line_standing, 2),
            ("العيار", self.line_karat, 2),
            ("الأجر/جم", self.line_wage, 2),
        ]
        g = QtWidgets.QGridLayout(box)
        g.setHorizontalSpacing(6)
        for c, (label, widget, stretch) in enumerate(fields):
            widget.setMinimumWidth(86)
            g.addWidget(_sub(label), 0, c)
            g.addWidget(widget, 1, c)
            g.setColumnStretch(c, stretch)
        g.addWidget(self.btn_add_line, 1, len(fields))
        g.addWidget(self.btn_wage_only, 1, len(fields) + 1)
        # Enter على زرّ الإضافة يضغطه (الزر خارج سلسلة الخانات، ومن
        # وصل إليه بـTab كان يحتاج المسطرة لا Enter)
        for _b in (self.btn_add_line, self.btn_wage_only):
            _b.setAutoDefault(True)

        # ترتيب التنقّل هو ترتيب الخانات نفسه، وEnter على آخر خانة
        # يضيف السطر. ورقم التشغيل **إلزامي**: Enter لا يتجاوزه وهو
        # فارغ. وبعد الإضافة يعود المؤشر إليه لا إلى الموديل — فالموديل
        # يُملأ من بطاقة الطقم، والرقم هو ما يُكتب في كل سطر.
        self._chain = [w for _, w, _ in fields]
        enter_chain(self, self._chain, on_last=self._add_from_enter,
                    require={self.barcode:
                             lambda: bool(self.barcode.text().strip())})
        # 4.60: «وقفةٌ» عند الأجر — تُلغى بأي كتابةٍ فيه أو بمغادرته
        self._wage_armed = False
        self._enter_up = True
        # 4.61: والإضافة بضغطةٍ جديدة بعد رفع الإصبع عن Enter لا بتكراره
        self._held_guard = _HeldEnterGuard(self)
        self.line_wage.installEventFilter(self._held_guard)
        try:
            self.line_wage.lineEdit().installEventFilter(self._held_guard)
        except Exception:
            pass
        self._add_text = self.btn_add_line.text()
        try:
            self.line_wage.lineEdit().textEdited.connect(
                lambda *_: self._arm_wage(False))
        except Exception:
            pass
        QtWidgets.QApplication.instance().focusChanged.connect(
            self._entry_focus_moved)
        return box

    def _add_from_enter(self):
        """Enter على خانة الأجر (آخر السطر): **الأولى تقف، والثانية تضيف**.

        طلب صاحب النظام (4.60): Enter من رقم التشغيل يمشي على الخانات حتى
        الأجر ثم **يقف عنده** — فيُراجَع الأجر أو يُكتب — ولا يُضاف السطر
        إلا بضغطةٍ ثانية. كانت ضغطةٌ واحدة تضيفه قبل أن تقع العين على
        الأجر. والأولى تعتمد ما كُتب («12+3» تصير 15) فيُرى قبل الإضافة،
        وأي كتابةٍ في الخانة بعدها تعيدها «أولى» من جديد.

        وبعد الإضافة يعود المؤشر لرقم التشغيل. وإن رُفض السطر يبقى حيث
        هو ليُصحَّح — لا يقفز إلى أول السطر فيضيع موضع الخطأ.
        """
        if not self._wage_armed:
            try:
                self.line_wage.interpretText()
            except Exception:
                pass
            self.line_wage.selectAll()
            self._arm_wage(True)
            return False             # يبقى المؤشر في خانة الأجر
        self._arm_wage(False)
        return self.barcode if self.add_item() else False

    def _arm_wage(self, on):
        """الوقفة عند الأجر: الزرّ يقول إن Enter التالية تضيف السطر."""
        on = bool(on)
        if on == self._wage_armed and not on:
            return
        self._wage_armed = on
        if on:
            # الوقفة تبدأ والإصبع على Enter — لا إضافة قبل رفعه
            self._enter_up = False
        self.btn_add_line.setText("↵ " + self._add_text.lstrip("+ ").strip()
                                  if on else self._add_text)
        if on:
            w = self.line_wage
            QtWidgets.QToolTip.showText(
                w.mapToGlobal(QtCore.QPoint(0, w.height())),
                "↵ ارفع إصبعك ثم Enter مرةً ثانية يضيف السطر", w)
        else:
            QtWidgets.QToolTip.hideText()

    def _entry_focus_moved(self, _old, new):
        if not getattr(self, "_wage_armed", False):
            return
        try:
            inner = self.line_wage.lineEdit()
            if new is not self.line_wage and new is not inner:
                self._arm_wage(False)
        except RuntimeError:          # الشاشة أُغلقت وحُرِّر كائنها
            pass

    # ══════════════════════════════════════════════════════════════
    #  ③ البنود والخلاصة
    # ══════════════════════════════════════════════════════════════

    def _build_items(self):
        box = QtWidgets.QGroupBox("③ بنود الفاتورة")
        self.items_table = make_table()
        self.items_table.cellClicked.connect(self._model_clicked)
        self.items_table.setToolTip(
            "انقر خانة الموديل لعرض صورته المحفوظة في دليل الموديلات\n"
            "وانقر خانة الأجر لتعديله في مكانه — Enter يحفظ وينزل للسطر"
            " التالي")
        # 4.59: الأجر يُكتب في خانته — نقرةً أو بالكتابة مباشرةً والخانة
        # محدّدة. وما سواها من الخانات لا يُكتب (`_mark_wage_cells`).
        self._wage_delegate = _WageDelegate(self)
        for c in self.WAGE_COLS:
            self.items_table.setItemDelegateForColumn(c, self._wage_delegate)
        self.items_table.setEditTriggers(
            QtWidgets.QAbstractItemView.AnyKeyPressed)
        # الزر الأيمن على سطر: أجرُه على كل الأسطر، أو المتفق عليه
        self.items_table._tt_extra = self._wage_menu
        # التعديل والحذف في **عمود السطر الأول** لا تحت الجدول:
        # زرٌّ في صفّه لا يُخطئ صاحبه، ولا يحتاج تحديداً سابقاً.
        hint = QtWidgets.QLabel(
            "✎ يفتح السطر كاملاً للتصحيح   ·   ✕ يحذفه من الفاتورة "
            "  ·   خانة الأجر تُعدَّل بالنقر عليها، وEnter ينزل للتي تحتها")
        hint.setObjectName("cardSub")

        self.p_weight = _Panel("إجمالي الوزن المقيد")
        self.p_wages = _Panel("إجمالي الأجور")
        self.p_gold_bal = _Panel("رصيد ذهب العميل بعد الفاتورة")
        self.p_cash_bal = _Panel("رصيد أجور العميل بعد الفاتورة")

        self.live_note = QtWidgets.QLabel("")
        self.live_note.setObjectName("ok")
        self.live_note.setWordWrap(True)
        self.live_note.setVisible(False)
        self.edit_banner = QtWidgets.QLabel(
            "✎ وضع التعديل: تُعدَّل الفاتورة في مكانها برقمها نفسه، "
            "ويُرحَّل الفرق وحده على قيدها القائم.")
        self.edit_banner.setObjectName("warn")
        self.edit_banner.setWordWrap(True)
        self.edit_banner.setVisible(False)

        v = QtWidgets.QVBoxLayout(box)
        v.addWidget(self.items_table, 1)
        v.addWidget(hint)
        panels = QtWidgets.QHBoxLayout()
        for p in (self.p_weight, self.p_wages,
                  self.p_gold_bal, self.p_cash_bal):
            panels.addWidget(p, 1)
        v.addLayout(panels)
        v.addWidget(self.live_note)
        v.addWidget(self.edit_banner)
        return box

    def _build_footer(self):
        self.btn_save = kit.PushButton("ترحيل الفاتورة")
        self.btn_save.clicked.connect(self.save)
        self.btn_cancel_edit = kit.PushButton("إلغاء التعديل")
        self.btn_cancel_edit.setObjectName("ghost")
        self.btn_cancel_edit.clicked.connect(self.cancel_edit)
        self.btn_cancel_edit.setVisible(False)
        # تعليق: تُحفظ الفاتورة في «المعلّقات» بلا قيد ولا أثر
        self.btn_hold = kit.PushButton("⏸ تعليق الفاتورة")
        self.btn_hold.setObjectName("ghost")
        self.btn_hold.setToolTip(
            "تُحفظ الفاتورة في «المعلّقات» بلا ترحيل ولا أثر على المخزون أو"
            " الحسابات — تُفتح لاحقاً لاستكمالها وإثباتها")
        self.btn_hold.clicked.connect(self.hold_invoice)
        keys = QtWidgets.QLabel(
            "⌨ F3 رقم التشغيل  ·  F4 العميل  ·  Enter ينتقل ويضيف  ·  "
            "F2 ترحيل الفاتورة  ·  Delete حذف السطر المحدد  ·  "
            "Esc إلغاء التعديل   |   سجل الفواتير وحذفها: شاشة "
            "«سجل العمليات».")
        keys.setObjectName("cardSub")
        keys.setWordWrap(True)
        v = QtWidgets.QVBoxLayout()
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.btn_save, 1)
        row.addWidget(self.btn_hold)
        row.addWidget(self.btn_cancel_edit)
        v.addLayout(row)
        v.addWidget(keys)
        return v

    # ══════════════════════════════════════════════════════════════
    #  ⏸ المعلّقات — فواتير لم تُثبت بعد (بلا قيد ولا أثر)
    # ══════════════════════════════════════════════════════════════

    def _build_held(self):
        w = QtWidgets.QWidget()
        self.held_tbl = make_table()
        self.held_tbl.doubleClicked.connect(lambda *_: self.open_held())
        self.held_rows = []
        b_open = kit.PushButton("↩ فتح لاستكمالها وإثباتها")
        b_open.setObjectName("homeBtn")
        b_open.clicked.connect(self.open_held)
        b_drop = kit.PushButton("🗑 إلغاء المعلّقة")
        b_drop.setObjectName("ghost")
        b_drop.clicked.connect(self.drop_held)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(b_open)
        row.addWidget(b_drop)
        row.addStretch(1)
        self.held_note = QtWidgets.QLabel("")
        self.held_note.setObjectName("cardSub")
        self.held_note.setWordWrap(True)
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.addLayout(row)
        lay.addWidget(self.held_tbl, 1)
        lay.addWidget(self.held_note)
        return w

    def load_held(self):
        try:
            with db(readonly=True) as conn:
                self.held_rows = pending.list_held(conn)
            u = kv.unit()
            kinds = {"sale": "مبيعات", "sale_return": "مرتجع"}
            fill(self.held_tbl,
                 ["رقم", "النوع", "الطرف", "التاريخ", "عدد\nالأطقم",
                  f"الوزن\n({u})", "الأجور\n(ريال)", "تنبيه",
                  "ملاحظة", "علّقها", "آخر تحديث"],
                 [(r["id"], kinds.get(r["kind"], r["kind"]), r["customer"],
                   r["date"], r["count"], f"{kv.g(r['weight']):,.3f}",
                   f"{r['wages']:,.2f}",
                   (f"⚠ {r['unavailable']} طقم لم يعد بالمخزن"
                    if r["unavailable"] else "—"),
                   r["note"] or "—", r["created_by"],
                   (r["created_at"] or "")[:16])
                  for r in self.held_rows])
            n = len(self.held_rows)
            self.tabs.setTabText(1, f"⏸ المعلّقات ({n})" if n
                                 else "⏸ المعلّقات")
            self.held_note.setText(
                "الفاتورة المعلّقة لا قيد لها ولا أثر على المخزون أو الذمم —"
                " لا تُثبت إلا بالترحيل. «فتح لاستكمالها» يعيدها إلى «إصدار"
                " فاتورة»: أكملها ثم رحّلها فتُثبت وتخرج من هنا. والتعليق لا"
                " يحجز الطقم: إن بِيع في فاتورةٍ أخرى ظهر هنا تنبيه."
                if n else "لا فواتير معلّقة.")
        except Exception as e:
            err(self, e)

    def _held_selected(self):
        i = self.held_tbl.currentRow()
        if not (0 <= i < len(self.held_rows)):
            raise ValueError("اختر فاتورةً معلّقة من الجدول أولاً")
        return self.held_rows[i]

    def hold_invoice(self):
        """يعلّق الفاتورة الجارية: تُحفظ بلا ترحيل وتُمسح الشاشة."""
        self._wage_delegate.flush()
        try:
            if self.editing_id is not None:
                raise ValueError("فاتورةٌ مُرحَّلة مفتوحة للتعديل لا تُعلَّق —"
                                 " احفظ تعديلها أو ألغِه")
            state = self.draft_state()
            if not state:
                raise ValueError("لا بنود في الفاتورة — أضف طقماً قبل"
                                 " تعليقها")
            note, ok = QtWidgets.QInputDialog.getText(
                self, "تعليق الفاتورة",
                "ملاحظة تُذكّرك بها (اختياري):",
                text=self.description.text().strip())
            if not ok:
                return
            with db() as conn:
                hid = pending.hold_invoice(conn, state,
                                           self.user["username"],
                                           note.strip(), self._held_id)
            self._held_id = None
            self.description.clear()
            self._clear_items_now()
            self._clear_entry()
            self.live_note.setVisible(False)
            drafts.clear(DRAFT_KEY, self.user.get("username"))
            self.load_held()
            info(self, f"عُلّقت الفاتورة برقم {hid} في «المعلّقات» — بلا قيد"
                       " ولا أثر على المخزون أو الحسابات.")
        except Exception as e:
            err(self, e)

    def open_held(self):
        """يعيد المعلّقة إلى «إصدار فاتورة» لاستكمالها وترحيلها."""
        try:
            r = self._held_selected()
            if self.items and self._held_id != r["id"] and not ask(
                    self, "في «إصدار فاتورة» بنودٌ لم تُرحَّل — ستُستبدل"
                          " بالفاتورة المعلّقة. متابعة؟"):
                return
            if self.editing_id is not None:
                self.cancel_edit()
            with db(readonly=True) as conn:
                state = pending.get_held(conn, r["id"])
            self._clear_items_now()
            if not self.apply_draft(state):
                raise ValueError("أطقم هذه الفاتورة لم تعد موجودة —"
                                 " ألغِ المعلّقة")
            self._held_id = r["id"]
            self.tabs.setCurrentIndex(0)
            self.live_note.setText(
                f"⏸ فاتورة معلّقة رقم {r['id']} — أكملها ثم رحّلها لإثباتها"
                " (أو علّقها ثانيةً)."
                + (f"  ⚠ {r['unavailable']} طقم فيها لم يعد بالمخزن"
                   " — احذفه قبل الترحيل." if r["unavailable"] else ""))
            self.live_note.setVisible(True)
        except Exception as e:
            err(self, e)

    def drop_held(self):
        try:
            r = self._held_selected()
            if not ask(self, f"إلغاء الفاتورة المعلّقة رقم {r['id']}"
                             f" ({r['customer']} · {r['count']} طقم)؟"
                             "\nلا قيد لها فلا يتأثر شيء في الحسابات."):
                return
            with db() as conn:
                pending.drop_held(conn, r["id"], self.user["username"],
                                  "أُلغيت")
            if self._held_id == r["id"]:
                self._held_id = None
            self.load_held()
        except Exception as e:
            err(self, e)

    # ══════════════════════════════════════════════════════════════
    #  حساب المصدر
    # ══════════════════════════════════════════════════════════════

    def _reload_sources(self, conn):
        """يملأ قائمة الحسابات ويعيد آخر اختيارٍ محفوظ.

        **في التعديل يبقى حساب الفاتورة نفسها**: كان تحديث الشاشة أثناء
        تعديل فاتورة يعيد «آخر اختيار» المحفوظ مكان حسابها — فتنتقل
        أطقمها عند الحفظ إلى حسابٍ لم يختره أحد.
        """
        want = str(load_pref("sales_source_account", "")).strip()
        if self.editing_id is not None or getattr(self, "_loading_doc",
                                                  False):
            cur = self._source_code()
            if cur:
                want = cur
        self.sources = invoices.source_accounts(conn)
        self.source.blockSignals(True)
        self.source.clear()
        for r in self.sources:
            self.source.addItem(f"{r['name']} ({r['code']})", r["id"])
        idx = -1
        if want:
            for i, r in enumerate(self.sources):
                if r["code"] == want:
                    idx = i
                    break
        if idx < 0:
            for i, r in enumerate(self.sources):
                if r["code"] == invoices.DEFAULT_SOURCE:
                    idx = i
                    break
        if idx >= 0:
            self.source.setCurrentIndex(idx)
        self.source.blockSignals(False)
        # عيار الكسر: آخر ما اختاره المستخدم، وإلا عيار المصنع المختار
        # في أعلى النافذة — فتبديل العيار إلى 21 يجعل الصندوق بمكافئ 21
        k = str(load_pref("sales_scrap_karat", "") or kv.active()).strip()
        if k.isdigit():
            i = self.scrap_karat.findData(int(k))
            if i >= 0:
                self.scrap_karat.blockSignals(True)
                self.scrap_karat.setCurrentIndex(i)
                self.scrap_karat.blockSignals(False)
        self._sync_scrap_box()

    def _source_code(self):
        i = self.source.currentIndex()
        return self.sources[i]["code"] if 0 <= i < len(self.sources) else ""

    def _is_scrap_source(self):
        from models.inventory import SCRAP_ACCOUNT
        return self._source_code() == SCRAP_ACCOUNT

    def _sync_scrap_box(self):
        """خانة العيار لا تظهر إلا لصندوق الكسر — فلا تُسأل عمّا لا يعني."""
        on = self._is_scrap_source()
        self.scrap_lbl.setVisible(on)
        self.scrap_karat.setVisible(on)

    def _is_return(self):
        return self.kind.currentData() == "sale_return"

    def _sync_kind_labels(self, *_):
        """«من حساب» في البيع و«إلى حساب» في المرتجع — الحساب واحد.

        المرتجع يُدخل البضاعة إلى المخزن نفسه الذي خرجت منه، فتسميته
        «من حساب» تقلب المعنى في ذهن من يقرأ الشاشة.
        """
        ret = self._is_return()
        self.source_lbl.setText("إلى حساب:" if ret else "من حساب:")
        self.source.setToolTip(
            ("الطقم المرتبط بحسابٍ (من دفعة توريده) يعود إلى حسابه هو.\n"
             "وهذا الحساب لما لا حساب له: الطقم الجديد غير المسجّل "
             "(فيصير حسابه) والرقم التجميعي.") if ret else
            ("الطقم المرتبط بحسابٍ (من دفعة توريده) يخرج من حسابه هو — "
             "عمود «الحساب» في البنود.\nوهذا الحساب لما لا حساب له: "
             "الرقم التجميعي وما لم يُعرف حسابه."))
        self.scrap_lbl.setText("عيار الإضافة:" if ret else "عيار الخصم:")

    def _source_changed(self, *_):
        self._sync_scrap_box()
        # اختيار حساب فاتورةٍ تُعدَّل لا يصير «آخر اختيار» للفواتير الجديدة
        if self.editing_id is None and not getattr(self, "_loading_doc",
                                                   False):
            self._save_source_pref()
        if getattr(self, "items", None):
            self.render_items()      # أسطر بلا بيتٍ تتبع الحساب المختار

    def _line_acc_id(self, it):
        """الحساب الذي يخرج منه السطر أو يعود إليه: المحفوظ مع سطر
        فاتورةٍ تُعدَّل، وإلا بيت الطقم، وإلا حساب العملية المختار."""
        if it.get("wage_only"):
            return None
        if it.get("acc"):
            return int(it["acc"])
        h = stock_home.home_of(it["wo"])
        return h or self.source.currentData()

    def _line_acc_name(self, it):
        a = self._line_acc_id(it)
        for r in self.sources:
            if r["id"] == a:
                return r["name"]
        if a:
            try:
                with db(readonly=True) as conn:
                    r = conn.execute("SELECT name FROM accounts WHERE id=?",
                                     (a,)).fetchone()
                return r["name"] if r else "—"
            except Exception:
                return "—"
        return "—"

    def _save_source_pref(self, *_):
        code = self._source_code()
        if code:
            save_pref("sales_source_account", code,
                      self.user.get("username"))
        save_pref("sales_scrap_karat",
                  str(self.scrap_karat.currentData() or ""),
                  self.user.get("username"))

    def new_source(self):
        dlg = NewSourceDialog(self, self.user["username"])
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            with db(readonly=True) as conn:
                self._reload_sources(conn)
            i = self.source.findData(dlg.account_id)
            if i >= 0:
                self.source.setCurrentIndex(i)

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
            "source": self._source_code(),
            "scrap_karat": self.scrap_karat.currentData(),
            "items": [({"wage_only": True, "amount": i["amount"],
                        "note": i.get("note") or "", "weight": 0.0,
                        "wage": 0.0}
                       if i.get("wage_only") else
                       {"wo_id": i["wo"]["id"], "weight": i["weight"],
                        "wage": i["wage"], "karat": i.get("karat") or 0})
                      for i in self.items],
        }

    def apply_draft(self, d):
        """يعيد بناء الشاشة من مسوّدة — بتجاهل ما لم يعد موجوداً."""
        if not d or not d.get("items"):
            return False
        items = []
        try:
            with db() as conn:
                for it in d["items"]:
                    if it.get("wage_only"):
                        items.append(self._wage_item(
                            stock_home.service_wo(conn),
                            float(it.get("amount") or 0),
                            it.get("note") or ""))
                        continue
                    wo = conn.execute(
                        "SELECT * FROM work_orders WHERE id=? AND"
                        " is_deleted=0", (it.get("wo_id"),)).fetchone()
                    if wo is None:
                        continue      # طقمٌ حُذف بعد حفظ المسوّدة
                    items.append(self._item_from_wo(
                        wo, float(it.get("weight") or 0),
                        float(it.get("wage") or 0),
                        int(it.get("karat") or 0) or kv.active()))
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
        self._select_source(d.get("source"), d.get("scrap_karat"))
        self.items = items
        self.render_items()
        return True

    def _select_source(self, code=None, karat=None):
        """يختار حساب المصدر بكوده — أو يترك المحفوظ كما هو."""
        if code:
            for i, r in enumerate(self.sources):
                if r["code"] == code:
                    self.source.setCurrentIndex(i)
                    break
        if karat:
            i = self.scrap_karat.findData(int(karat))
            if i >= 0:
                self.scrap_karat.setCurrentIndex(i)
        self._sync_scrap_box()

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
        self._wage_delegate.flush()
        self._save_draft()

    # ══════════════════════════════════════════════════════════════
    #  الإدخال السريع بلوحة المفاتيح
    # ══════════════════════════════════════════════════════════════

    def _install_shortcuts(self):
        """مفاتيح تُغني عن الفأرة في شاشة الإدخال الأكثر استعمالاً.

        **لماذا هنا بالذات**: المبيعات شاشةُ الدوام كله — عشرات
        الفواتير في اليوم، وكل فاتورة عدة أسطر. وترك لوحة المفاتيح
        لالتقاط الفأرة بين كل سطرٍ وآخر يضاعف زمن الفاتورة ويُدخل
        أخطاءً في النقر.

        المفاتيح محصورة في هذه الشاشة (`WidgetWithChildrenShortcut`)
        فلا تتسرّب إلى شاشةٍ أخرى ولا تصطدم باختصار عام.
        """
        self._shortcuts = []
        for seq, fn in (("F2", self._save_shortcut),
                        ("F3", lambda: self._focus(self.barcode)),
                        ("F4", lambda: self._focus(self.customer)),
                        ("Ctrl+Return", self.add_item),
                        ("Ctrl+Enter", self.add_item),
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
        if self._wage_delegate.cancel():   # خانة أجرٍ مفتوحة: تراجعٌ عنها
            return
        if self.editing_id is not None:
            self.cancel_edit()
        else:
            self._focus(self.barcode)

    # ══════════════════════════════════════════════════════════════
    #  الطرف المقابل
    # ══════════════════════════════════════════════════════════════

    def _is_internal(self, cid):
        return any(c["id"] == cid and c["is_internal"] for c in self.customers)

    def customer_changed(self):
        cid = self.customer.currentData()
        internal = cid is not None and self._is_internal(cid)
        self.vat_check.setEnabled(not internal)
        self.internal_note.setVisible(internal)
        if internal:
            self.vat_check.setChecked(False)
        self._load_agreed_wage(cid)
        self._load_open_orders(cid)
        # الأجور تُخفى في التحويل الداخلي وتعود لغيره — وخاناتها تتبعها
        self.render_items()

    def _load_open_orders(self, cid):
        """طلبات العميل المفتوحة من دليل الموديلات — تنبيهٌ برابط."""
        orders = []
        if cid is not None and not self._is_internal(cid):
            try:
                from models import model_orders as mo
                with db(readonly=True) as conn:
                    orders = mo.open_for_customer(
                        conn, cid, self.customer.currentText())
            except Exception:
                orders = []
        if not orders:
            self.order_note.setText("")
            self.order_note.setVisible(False)
            return
        links = " · ".join(
            f"<a href='{o['id']}'>{o['order_no']}</a> ({o['n_models']} موديل"
            f" · {o['n_pieces']} قطعة)" for o in orders[:4])
        more = f" و{len(orders) - 4} غيرها" if len(orders) > 4 else ""
        self.order_note.setText(
            f"📝 لهذا العميل {'طلبٌ مفتوح' if len(orders) == 1 else 'طلبات مفتوحة'}"
            f" من دليل الموديلات: {links}{more} — انقر الرقم لعرضه بالصور.")
        self.order_note.setVisible(True)

    def _open_customer_order(self, link):
        try:
            from ui.model_orders_dialog import ModelOrdersDialog
            dlg = ModelOrdersDialog(self, self.user)
            dlg.show_order(int(link))
            self._order_dlg = dlg
            dlg.exec_()
        except Exception as e:
            err(self, e)
        finally:
            self._order_dlg = None
            self._load_open_orders(self.customer.currentData())

    def _load_agreed_wage(self, cid):
        """أجرة العميل المتفق عليها — تُقرأ مرةً عند اختياره.

        **صفرٌ يعني بلا اتفاق** لا اتفاقاً بصفر، فلا يُفرض على من لم
        يُكتب له اتفاق. والتحويل إلى عيار العرض هنا: المخزَّن مكافئ
        عيار 18 وحقلُ الأجر في الشاشة بعيار المصنع.
        """
        self._agreed_wage = 0.0
        if not cid:
            self.wage_note.setText("")
            return
        try:
            with db(readonly=True) as conn:
                stored = entities.agreed_wage(conn, cid)
        except Exception:
            stored = 0.0
        if stored > 0:
            self._agreed_wage = round(kv.rate(stored), 2)
            self.wage_note.setText(
                f"💠 الأجرة المتفق عليها مع هذا العميل: "
                f"{self._agreed_wage:,.2f} ريال لكل {kv.unit()} — "
                "تُملأ تلقائياً، ولك أن تغيّرها في أي سطر.")
        else:
            self.wage_note.setText(
                "لا أجرةَ متفق عليها مسجّلة لهذا العميل — تُكتب في "
                "بطاقة الجهة، فيُقاس عليها ويُكشف أي انحراف.")

    def _wage_hint(self, used):
        """يوازن أجر السطر بالمتفق عليه ويقول الفرق — بلا منع."""
        if self._agreed_wage <= 0:
            return
        d = round(used - self._agreed_wage, 2)
        if abs(d) < 0.005:
            self.wage_note.setText(
                f"✔ أجر السطر {used:,.2f} — مطابقٌ للمتفق عليه.")
        else:
            self.wage_note.setText(
                f"⚠ أجر السطر {used:,.2f} والمتفق عليه "
                f"{self._agreed_wage:,.2f} — "
                + ("أقلّ" if d < 0 else "أعلى") +
                f" بـ {abs(d):,.2f} ريال لكل {kv.unit()}. "
                "أُضيف كما أدخلتَه — راجعه إن لم يكن عن قصد.")

    def new_customer(self):
        dlg = NewCustomerDialog(self, self.user["username"])
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self.refresh()
            idx = self.customer.findData(dlg.customer_id)
            if idx >= 0:
                self.customer.setCurrentIndex(idx)

    def open_tax_note(self):
        TaxDebitNoteDialog(self, self.user["username"]).exec_()

    # ══════════════════════════════════════════════════════════════
    #  سطر الإدخال: الاستدعاء والحساب
    # ══════════════════════════════════════════════════════════════

    def _k(self):
        """عيار السطر المختار الآن."""
        return int(self.line_karat.currentData() or kv.active())

    def _clear_entry(self):
        """يُفرغ سطر الإدخال — والعيار يبقى كما اختاره المستخدم.

        الموديل يُمسح كغيره: تركه يجعل الطقم التالي يرث موديل سابقه
        فيُسجَّل خطأً في الدليل.
        """
        self._calc = True
        try:
            self.barcode.clear()
            self.model_no.setCurrentText("")
            for w in (self.line_reg, self.line_standing, self.line_wage,
                      self.line_gold, self.line_small, self.line_big,
                      self.line_after):
                w.setValue(0)
        finally:
            self._calc = False
        self._snap_w18()
        self._wage18 = 0.0
        self._reg_manual = False
        self._rate = config.STONE_DISCOUNT_RATE
        self._wo = None
        self._clear_held()            # أُضيف السطر ⇒ يُغلق إشعار المدة

    def _fill_from_wo(self, wo):
        """ينسخ بطاقة الطقم إلى سطر الإدخال بعيار السطر المختار."""
        k = self._k()
        self._calc = True
        try:
            mn = (wo["model_no"] if "model_no" in wo.keys() else "") or ""
            if mn:
                self.model_no.setCurrentText(str(mn))
            if wo["is_bulk"]:
                # الرقم التجميعي رصيدٌ وزني لا قطعة: لا تُنسخ بطاقته
                # (فهي الرصيد كله) — يُكتب الوزن المطلوب وحده.
                self.line_gold.setValue(0)
                self.line_small.setValue(0)
                self.line_big.setValue(0)
                self.line_after.setValue(0)
                self.line_standing.setValue(0)
                self.line_reg.setValue(0)
            else:
                # 4.82: المقترح الباقي في الخزنة (بيع) أو الخارج (مرتجع) —
                # طقمٌ بِيع منه جزءٌ يُعرض بباقيه، ومكوّناته بنسبته
                full = float(wo["registered_weight"] or 0)
                avail = full
                try:
                    from models import wo_moves as _wm
                    kind = ("sale" if self.kind.currentData() == "sale"
                            else "sale_return")
                    with db(readonly=True) as conn:
                        avail = _wm.default_weight(conn, wo, kind)
                except Exception:
                    pass
                f = avail / full if full > 0.001 else 1.0
                self.line_gold.setValue(kv.g((wo["gold_weight"] or 0) * f, k))
                self.line_small.setValue(
                    kv.g((wo["small_stones"] or 0) * f, k))
                self.line_big.setValue(kv.g((wo["big_stones"] or 0) * f, k))
                self.line_after.setValue(
                    kv.g((wo["stones_after_discount"] or 0) * f, k))
                self.line_standing.setValue(
                    kv.g((wo["standing_gold"] or 0) * f, k))
                self.line_reg.setValue(kv.g(avail, k))
                self.line_reg.setToolTip(
                    "" if abs(avail - full) < 0.001 else
                    f"وزن الطقم {kv.g(full, k):,.2f} — المقترح هنا"
                    f" {kv.g(avail, k):,.2f} (الباقي بعد ما بِيع/رُدّ منه)."
                    " اكتب وزناً أقل لبيع جزءٍ يبقى باقيه في الخزنة.")
            self._rate = float(wo["discount_rate"]
                               if "discount_rate" in wo.keys()
                               else config.STONE_DISCOUNT_RATE)
            # الأجر: أولويةُ **اتفاق العميل** على أجر بطاقة الطقم —
            # الأول اتفاقٌ مع من يشتري، والثاني تقديرُ المصنع وقت
            # الإنتاج. وكلاهما يُحوَّل لعيار السطر.
            if self.line_wage.value() <= 0:
                base = (kv.rate_store(self._agreed_wage)
                        if self._agreed_wage > 0
                        else (wo["wage_per_gram"] or 0))
                self._wage18 = float(base or 0)
                self.line_wage.setValue(kv.rate(base, k))
        finally:
            self._calc = False
        self._reg_manual = False
        self._snap_w18()

    def _wo_lookup(self):
        """يستدعي بطاقة الطقم من رقم التشغيل ويملأ السطر بها."""
        no = self.barcode.text().strip()
        if not no:
            return
        if self._wo is not None and self._wo["work_order_no"] == no:
            # الطقم نفسه أُعيد إدخاله: يعود إشعاره إن أُغلق (4.88)
            if (self._is_return() and not self._wo["is_bulk"]
                    and not self._held_shown()):
                self._held_note(self._wo)
            return
        try:
            with db(readonly=True) as conn:
                wo = inventory.get_wo_by_no(conn, no)
        except Exception:
            wo = None
        if wo is None:
            # لا رسالةَ خطأ هنا: قد يكون الرقم جديداً في مرتجع، أو
            # ما زال المستخدم يكتبه. الرفض موضعه الإضافة لا الكتابة.
            self._wo = None
            self._clear_held()
            return
        self._wo = wo
        self._fill_from_wo(wo)
        if self._is_return() and not wo["is_bulk"]:
            self._held_note(wo)
        else:
            self._clear_held()
        # الخانة التي انتقل إليها المؤشر تُحدَّد كاملة، فيُكتب فوقها
        # مباشرةً إن أراد المستخدم تصحيح ما جاء من البطاقة.
        fw = QtWidgets.QApplication.focusWidget()
        if fw is not None and hasattr(fw, "selectAll"):
            fw.selectAll()

    def _held_note(self, wo):
        """المرتجع (4.87): إشعارٌ بكم جلس الطقم عند الجهة منذ بِيع لها —
        حتى تاريخ هذه الفاتورة. وإن بِيع لغير العميل المختار يُنبَّه.

        ثابتٌ (4.88): يبقى حتى «إضافة سطر» أو إدخال طقمٍ آخر أو مغادرة
        الشاشة — ويعود إن أُعيد إدخال الطقم نفسه."""
        self._clear_held()
        if not self.isVisible():
            # مغادرة الشاشة تُفقد رقمَ التشغيل التركيز فيُستدعى الطقم —
            # والإشعار لا يُعرض فوق شاشةٍ أخرى
            return None
        try:
            from models import wo_moves as _wm
            with db(readonly=True) as conn:
                h = _wm.last_out(conn, wo, dstr(self.date))
        except Exception:
            return None
        if not h:
            return None
        n = h["days"]
        span = ("أُرجع في يوم بيعه نفسه" if n <= 0
                else f"جلس عند «{h['party']}» {_wm.days_ar(n)}")
        # LRM حول التاريخ: بدونه يُقلب في السطر العربي (05-10-2026)
        txt = (f"الطقم {wo['work_order_no']}: {span} — بِيع بالفاتورة"
               f" {h['invoice_no']} بتاريخ \u200e{h['date']}\u200e")
        cust = self.customer.currentData()
        other = bool(cust and h["party_id"]
                     and int(cust) != int(h["party_id"]))
        if other:
            txt += f"\n⚠ بِيع لـ«{h['party']}» لا للعميل المختار"
        bar = kit.notify(self, txt, "warning" if other else "info",
                         title="مدة بقاء الطقم", ms=-1)
        if bar is None:
            from ui.widgets import toast
            bar = toast.show(self, txt, -1)
        self._held_bar = bar
        return txt

    def _held_shown(self):
        try:
            bar = getattr(self, "_held_bar", None)
            return bar is not None and bar.isVisible()
        except RuntimeError:          # أُغلق بزرّه فحُذف
            return False

    def _clear_held(self, *_):
        """يُغلق إشعار «مدة بقاء الطقم» إن كان ظاهراً."""
        bar, self._held_bar = getattr(self, "_held_bar", None), None
        if bar is None:
            return
        try:
            if isinstance(bar, QtWidgets.QLabel):
                bar.deleteLater()
            else:
                bar.close()
        except RuntimeError:
            pass

    def hideEvent(self, e):
        # الإشعار على النافذة لا على الشاشة: لا يبقى فوق شاشةٍ أخرى
        self._clear_held()
        super().hideEvent(e)

    def _w_fields(self):
        """خانات الوزن الست بترتيبها — مرجعٌ واحد لكل ما يمسّها."""
        return (self.line_reg, self.line_standing, self.line_gold,
                self.line_small, self.line_big, self.line_after)

    def _snap_w18(self):
        """لقطةٌ ظلّيةٌ للأوزان بمكافئ 18 — مرجعُ تبديل العيار.

        **لماذا**: الخانة تعرض ثلاث منازل، وتبديل العيار قسمةٌ ثم
        ضرب. فوزنٌ كُتب 45.000 يعود 44.999 بعد ذهابٍ وإياب، فتنقص
        أجرة الفاتورة هللتين من لا شيء ويظن المستخدم أن الرقم تغيّر
        وحده. الظلُّ لا يُقرَّب، فالعودة تُرجع ما كُتب حرفياً.
        """
        self._w18 = [kv.store(w.value(), self._karat_now)
                     for w in self._w_fields()]

    def _parts_changed(self, *_):
        """تغيّر الذهب أو الفصوص أو الأحجار ⇒ يُعاد حساب المشتقّات."""
        if self._calc:
            return
        self._calc = True
        try:
            big = self.line_big.value()
            after = gold_math.stones_after_discount(big, self._rate)
            self.line_after.setValue(after)
            self.line_standing.setValue(gold_math.standing_gold(
                self.line_gold.value(), self.line_small.value(), big))
            if not self._reg_manual:
                self.line_reg.setValue(
                    round(self.line_gold.value()
                          + self.line_small.value() + after, 3))
        finally:
            self._calc = False
        self._snap_w18()

    def _after_changed(self, *_):
        """كتابةُ «الأحجار بعد الخصم» يدوياً تُعيد اشتقاق نسبة الخصم.

        بعض البطاقات خُصمت بنسبةٍ خاصة، فمن كتب الرقم الصحيح بيده
        يجب ألا يُدهس رقمُه بنسبةٍ افتراضية عند أول تعديلٍ تالٍ.
        """
        if self._calc:
            return
        big = self.line_big.value()
        if big > 0:
            self._rate = max(0.0, min(1.0, 1.0 - self.line_after.value() / big))
        self._calc = True
        try:
            if not self._reg_manual:
                self.line_reg.setValue(
                    round(self.line_gold.value() + self.line_small.value()
                          + self.line_after.value(), 3))
        finally:
            self._calc = False
        self._snap_w18()

    def _reg_changed(self, *_):
        """الوزن المقيد المكتوب بيدٍ يُحترم ولا يُعاد حسابه بعدها."""
        if self._calc:
            return
        self._reg_manual = True
        self._snap_w18()

    def _karat_changed(self, *_):
        """العيار في آخر السطر — ومعناه يتبع مصدر الأوزان.

        • **أوزانٌ من بطاقة الطقم** (رقم تشغيلٍ مسجّل): هي ذهبٌ فعليٌّ
          معروف، فتبديل العيار يعيد كتابتها بعياره — ما كان 100 جم
          عيار 18 هو 85.71 جم عيار 21 — والأجر يتحرّك عكسياً فيبقى
          حاصلُ الضرب (مبلغاً نقدياً) كما هو.
        • **أوزانٌ كُتبت باليد** (طقمٌ جديد في مرتجع): العيار بعدها
          **يصفها** ولا يحوّلها — من كتب 40 ثم اختار 21 يعني أربعين
          جراماً عيار 21. فالأرقام تبقى، والظلُّ يُعاد أخذه بالعيار
          الجديد.
        """
        old, new = self._karat_now, self._k()
        self._karat_now = new
        if old == new or self._calc:
            return
        if self._wo is None:
            self._snap_w18()
            self._wage18 = kv.rate_store(self.line_wage.value(), new)
            return
        self._calc = True
        try:
            # الأوزان من ظلّها بمكافئ 18 لا من الخانات المقرَّبة
            for w, base in zip(self._w_fields(), self._w18):
                w.setValue(kv.g(base, new))
            # والأجر كذلك — من قيمته الظلّية غير المقرَّبة
            self.line_wage.setValue(kv.rate(self._wage18, new))
        finally:
            self._calc = False

    def _wage_typed(self, *_):
        """كلّ أجرٍ يكتبه المستخدم يُحفظ بمكافئ 18 في الظلّ."""
        if self._calc:
            return
        self._wage18 = kv.rate_store(self.line_wage.value(),
                                     self._karat_now)

    # ══════════════════════════════════════════════════════════════
    #  بنود الفاتورة
    # ══════════════════════════════════════════════════════════════

    def clear_items(self, *_):
        """يُفرغ السلة — إلا أثناء تحميل فاتورة للتعديل."""
        if getattr(self, "_loading_doc", False):
            return
        return self._clear_items_now()

    def _clear_items_now(self):
        self.items = []
        self.render_items()

    def _item_from_wo(self, wo, weight, wage, karat, item_id=None,
                      parts=None):
        """سطرُ سلّةٍ كامل: الوزن والأجر بعياره، والمكوّنات معه.

        المكوّنات تُقرأ من بطاقة الطقم ما لم تُمرَّر صراحةً — فالسطر
        يعرض ما في البطاقة لا فراغاً، وما كُتب يدوياً يبقى كما كُتب.
        """
        k = int(karat or kv.active())
        if parts is None:
            if wo["is_bulk"]:
                parts = {"gold": weight, "small": 0.0, "big": 0.0,
                         "after": 0.0, "standing": weight}
            else:
                parts = {"gold": kv.g(wo["gold_weight"], k),
                         "small": kv.g(wo["small_stones"], k),
                         "big": kv.g(wo["big_stones"], k),
                         "after": kv.g(wo["stones_after_discount"], k),
                         "standing": kv.g(wo["standing_gold"], k)}
        return {"wo": wo, "weight": round(float(weight or 0), 3),
                "wage": float(wage or 0), "karat": k, "item_id": item_id,
                **parts}

    def _parts_of(self, it):
        """مكوّنات السطر — تُشتقّ من بطاقته إن كان السطر قديماً بلا مكوّنات.

        الأسطر المحفوظة قبل هذا التصميم (وفي الاختبارات) لا تحمل
        مكوّنات، فلا يجوز أن يسقط الجدول عليها.
        """
        wo = it["wo"]
        k = int(it.get("karat") or kv.active())
        if "gold" in it:
            return {key: it.get(key, 0.0) or 0.0
                    for key in ("gold", "small", "big", "after", "standing")}
        if wo["is_bulk"]:
            w = float(it.get("weight") or 0)
            return {"gold": w, "small": 0.0, "big": 0.0, "after": 0.0,
                    "standing": w}
        return {"gold": kv.g(wo["gold_weight"], k),
                "small": kv.g(wo["small_stones"], k),
                "big": kv.g(wo["big_stones"], k),
                "after": kv.g(wo["stones_after_discount"], k),
                "standing": kv.g(wo["standing_gold"], k)}

    def _store_w(self, it, key="weight"):
        """وزن السطر بمكافئ 18 — الحدّ الفاصل بين العرض والدفتر."""
        return kv.store(float(it.get(key) or 0),
                        int(it.get("karat") or kv.active()))

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
                    if stock_home.is_service(wo):
                        cart.append(self._wage_item(
                            wo, float(it["wages"] or 0),
                            it["line_note"] or "", item_id=it["item_id"]))
                        continue
                    # المخزَّن بمكافئ 18 ← المعروض بعيار السطر كما كُتب
                    k = int(it["karat"] or 0) or kv.active()
                    cart.append(self._item_from_wo(
                        wo, kv.g(it["registered_weight"], k),
                        self._wage_view(it["wage_per_gram"], k), k,
                        # هويّة السطر: بها يعرف التعديل أيَّ سطرٍ
                        # يُحدِّث. الرقم التجميعي يتكرّر في الفاتورة
                        # بأسطرٍ مستقلة، ولا يميّزها إلا هذا الرقم.
                        item_id=it["item_id"]))
                    cart[-1]["acc"] = it["stock_account_id"]
                src = conn.execute(
                    "SELECT code FROM accounts WHERE id=?",
                    (inv["source_account_id"],)).fetchone() \
                    if inv["source_account_id"] else None
            self.editing_id = invoice_id
            self.refresh()
            # ══ تعطيل الإشارات أثناء التحميل ══
            # تغيير نوع العملية مربوط بـ`clear_items`، وتغيير الجهة
            # بـ`customer_changed` — وكلاهما يُفرغ السلة. ضبطهما هنا
            # كان يمسح أطقم الفاتورة فور تحميلها.
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
            # حساب الفاتورة الأصلي يعود معها: التعديل لا يُخرج الذهب
            # من حسابٍ غير الذي خرج منه أولاً إلا باختيارٍ صريح.
            self._select_source(src["code"] if src else invoices.DEFAULT_SOURCE,
                                inv["scrap_karat"] or None)
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
        self.btn_save.setText("حفظ التعديل (في مكانه بنفس الرقم)"
                              if editing else "ترحيل الفاتورة")

    def add_item(self):
        """يضيف سطر الإدخال إلى بنود الفاتورة بعد التحقّق منه."""
        self._commit_spins()
        no = self.barcode.text().strip()
        if not no:
            # رقم تشغيلٍ فارغ ومبلغٌ في خانة الأجر ⇒ سطر «أجر فقط»
            if self.line_wage.value() > 0:
                return self._append_wage_only(self.line_wage.value(), "")
            self._focus(self.barcode)
            return
        try:
            # من كتب 0001 بحكم العادة يُدلّ على الرقم الجديد
            inventory.assert_not_legacy(no)
            is_sale = self.kind.currentData() == "sale"
            k = self._k()
            reg_view = self.line_reg.value()
            with db() as conn:
                wo = inventory.get_wo_by_no(conn, no)
                if not wo and is_bulk_no(no):
                    wo = inventory.get_or_create_bulk_wo(
                        conn, self.user["username"], no)
            if not wo and not is_sale:
                # **مرتجع لرقم تشغيل غير مسجّل**: بضاعة قديمة تعود
                # للمصنع قبل تشغيل النظام. تُسجَّل بمكوّناتها المكتوبة
                # في سطر الإدخال — فيُنشأ الطقم بحالة «مباع» ثم يرجعه
                # المرتجع للمخزون، فيبقى القيد المزدوج سليماً.
                d = {"gold": self.line_gold.value(),
                     "small": self.line_small.value(),
                     "big": self.line_big.value(),
                     "rate": self._rate, "wage": self.line_wage.value()}
                if d["gold"] <= 0 and reg_view <= 0:
                    dlg = NewReturnItemDialog(self, no)
                    if dlg.exec_() != QtWidgets.QDialog.Accepted:
                        return
                    d = dlg.values()
                if d["gold"] <= 0 and reg_view > 0:
                    # وزنٌ بلا تفصيل: يُعتبر كلّه ذهباً فيستقيم المقيد
                    d["gold"] = reg_view
                with db() as conn:
                    # الطقم يُنشأ بمكافئ 18 مهما كان عيار الإدخال
                    wo = inventory.create_return_stub(
                        conn, no, kv.store(d["gold"], k),
                        kv.store(d["small"], k), kv.store(d["big"], k),
                        d["rate"], kv.rate_store(d["wage"] or 0, k),
                        self.user["username"])
                self._wo = wo
            if not wo:
                raise ValueError(
                    f"لا يوجد طقم برقم التشغيل {no}"
                    + (" — تحقق من الرقم أو أدخله من شاشة التوريد"
                       if is_sale else ""))

            if wo["is_bulk"]:
                # الرصيد والمقارنة بعيار السطر معاً — مقارنة رقمٍ
                # معروضٍ برقمٍ مخزَّنٍ تُنذر خطأً حيث لا خطأ.
                avail = kv.g(wo["registered_weight"], k)
                weight = reg_view
                if weight <= 0:
                    dlg = BulkWeightDialog(self, avail, is_sale,
                                           wo["work_order_no"])
                    if dlg.exec_() != QtWidgets.QDialog.Accepted:
                        return
                    weight = dlg.value()
                if weight <= 0:
                    raise ValueError("أدخل وزناً أكبر من صفر")
                # الرقم التجميعي يقبل التجاوز (يصير رصيده سالباً)،
                # لكن ننبّه المستخدم فلا يمرّ خطأ إدخال بلا انتباه.
                if is_sale and weight > avail + 0.001:
                    if not ask(self,
                               f"الوزن المطلوب {weight:,.2f} "
                               f"{kv.unit(k)} يتجاوز المتاح "
                               f"{avail:,.2f} {kv.unit(k)} في الرقم "
                               f"التجميعي.\n\nسيصبح رصيده سالباً "
                               f"({avail - weight:,.2f} "
                               f"{kv.unit(k)}).\n\nالمتابعة؟"):
                        return
                parts = {"gold": weight, "small": 0.0, "big": 0.0,
                         "after": 0.0, "standing": weight}
            else:
                # حالة الطقم تُشترط عند **إنشاء** فاتورة جديدة فقط.
                # أما تعديل فاتورة قائمة فتصحيح لمستند سابق: حالة
                # الطقم اليوم نتيجة آخر حركة له — وقد تكون حركةً بعد
                # هذه الفاتورة — و`update_invoice` لا يمسّ المخزون إلا
                # إن كانت هذه الفاتورة آخر حركة فعلاً.
                # 4.82: بالوزن لا بالحالة — يُباع ما بقي منه في الخزنة
                # ولو بِيع جزءٌ قبله، ويُرتجع ما خرج منه ولو بقي جزءٌ فيها
                from models import wo_moves as _wm
                with db(readonly=True) as conn:
                    _st = _wm.state(conn, wo)
                part = _st["rem"] if is_sale else _st["out"]
                if self.editing_id is None and part <= _wm.EPS:
                    raise ValueError(
                        f"الطقم {no} حالته لا تسمح: "
                        + ("خرج بوزنه كله — لا باقي منه في الخزنة يُباع"
                           if is_sale else
                           "لا شيء منه خارجٌ عند الجهات يُرتجع"))
                if any(i["wo"]["id"] == wo["id"] for i in self.items):
                    raise ValueError("الطقم مضاف مسبقاً للفاتورة")
                weight = reg_view if reg_view > 0 else kv.g(
                    part if part > _wm.EPS else wo["registered_weight"], k)
                parts = {"gold": self.line_gold.value(),
                         "small": self.line_small.value(),
                         "big": self.line_big.value(),
                         "after": self.line_after.value(),
                         "standing": (self.line_standing.value()
                                      or weight)}
                if parts["gold"] <= 0 and parts["small"] <= 0 \
                        and parts["big"] <= 0:
                    parts = None      # فارغٌ ⇒ تُقرأ من البطاقة

            # الأجر: قيمة الحقل إن أُدخلت، وإلا أجر الطقم الافتراضي.
            # كلاهما بعيار السطر — والتحويل عند الحفظ وحده.
            wage = self.line_wage.value()
            if wage <= 0:
                wage = kv.rate(
                    kv.rate_store(self._agreed_wage) if self._agreed_wage > 0
                    else (wo["wage_per_gram"] or 0.0), k)
            self._wage_hint(kv.rate(kv.rate_store(wage, k)))
            # ربط الطقم بالموديل المكتوب إن لم يكن له موديل
            self._apply_model(wo)
            with db() as conn:
                wo = inventory.get_wo_by_no(conn, wo["work_order_no"]) or wo
            self.items.append(self._item_from_wo(wo, weight, wage, k,
                                                 parts=parts))
            self._clear_entry()
            self.barcode.setFocus()      # العودة لرقم التشغيل مباشرة
            self.render_items()
            return True
        except Exception as e:
            err(self, e)
            return False

    def _commit_spins(self):
        """ما كُتب في خانةٍ ولم يُعتمد بعد (عمليةٌ مثل 12+3، أو رقمٌ
        لم تُغادَر خانته) يُعتمد قبل قراءة السطر."""
        for w in (self.line_reg, self.line_standing, self.line_gold,
                  self.line_small, self.line_big, self.line_after,
                  self.line_wage):
            try:
                w.interpretText()
            except Exception:
                pass

    def add_wage_only(self):
        """زرّ «+ أجر فقط»: مبلغٌ وبيانٌ اختياري."""
        try:
            self._guard_wage_only()
        except Exception as e:
            err(self, e)
            return
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("سطر أجر فقط")
        dlg.setLayoutDirection(QtCore.Qt.RightToLeft)
        amt = mspin()
        amt.setDecimals(2)
        if self.line_wage.value() > 0 and not self.barcode.text().strip():
            amt.setValue(self.line_wage.value())
        note = kit.LineEdit()
        note.setPlaceholderText("مثلاً: تلميع · تعديل مقاس · أجرة سابقة")
        form = QtWidgets.QFormLayout()
        form.addRow("المبلغ (ريال):", amt)
        form.addRow("البيان:", note)
        hint = QtWidgets.QLabel(
            "يُضاف إلى أجور العميل وحدها — بلا ذهب ولا أثرٍ على المخزون."
            "\nوفي المرتجع يُردّ من أجوره.")
        hint.setObjectName("cardSub")
        bb = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.button(QtWidgets.QDialogButtonBox.Ok).setText("إضافة")
        bb.button(QtWidgets.QDialogButtonBox.Cancel).setText("إلغاء")
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v = QtWidgets.QVBoxLayout(dlg)
        v.addLayout(form)
        v.addWidget(hint)
        v.addWidget(bb)
        amt.setFocus()
        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return
        amt.interpretText()
        self._append_wage_only(amt.value(), note.text().strip())

    def _guard_wage_only(self):
        cid = self.customer.currentData()
        if cid is not None and self._is_internal(cid):
            raise ValueError("سطر «أجر فقط» لا يصح في تحويلٍ داخلي —"
                             " لا أجور على خزينة التصنيع")

    def _append_wage_only(self, amount, note=""):
        try:
            self._guard_wage_only()
            amount = round(float(amount or 0), 2)
            if amount <= 0:
                raise ValueError("أدخل مبلغ الأجر")
            with db() as conn:
                swo = stock_home.service_wo(conn, self.user["username"])
            self.items.append(self._wage_item(swo, amount, note))
            self._clear_entry()
            self.barcode.setFocus()
            self.render_items()
            return True
        except Exception as e:
            err(self, e)
            return False

    @staticmethod
    def _wage_item(swo, amount, note="", item_id=None):
        return {"wo": swo, "wage_only": True, "amount": round(amount, 2),
                "note": note or "", "weight": 0.0, "wage": 0.0,
                "karat": kv.active(), "item_id": item_id,
                "gold": 0.0, "small": 0.0, "big": 0.0, "after": 0.0,
                "standing": 0.0}

    @staticmethod
    def _wage_store(it):
        """أجر جرام السطر بمكافئ 18 للقيد — بستّ منازل في كل عيار.

        `kv.rate_store` يقرّب عيار 18 إلى منزلتين، وهو ما يكتبه المستخدم
        فلا يضيع منه شيء. لكن الأجرة المقطوعة للقطعة (تُكتب في خانة
        «الأجرة (ريال)» — 4.59) تُقسَم على الوزن فتخرج بمنازل أكثر،
        وتقريبها إلى منزلتين يزيد الأجرة هللاتٍ أو ينقصها: 333 تصير 333.09.
        """
        k = int(it.get("karat") or kv.active())
        return round(float(it.get("wage") or 0) * kv.BASE / k, 6)

    @staticmethod
    def _wage_view(rate18, karat):
        """عكس `_wage_store`: الأجر المرحَّل بعيار السطر بلا تقريبٍ —
        فأجرةٌ مقطوعة تُفتح للتعديل وتُعاد كما رُحّلت لا تزيد هللة."""
        return round(float(rate18 or 0) * int(karat) / kv.BASE, 6)

    @staticmethod
    def _wages_of(it, internal=False):
        if internal:
            return 0.0
        if it.get("wage_only"):
            return float(it.get("amount") or 0)
        return gold_math.total_wages(it["wage"] or 0.0, it["weight"])

    def remove_item(self, row=None):
        """يحذف السطر — ويفكّ ربط الموديل الذي سُجّل في هذه الجلسة.

        **لماذا**: لو أخطأ المستخدم في رقم الموديل ثم حذف السطر
        ليعيده، يجب أن يعود الطقم بلا موديل فيُدخل الصحيح — لا أن
        يرث الخطأ. أما موديل كان مسجّلاً قبل الجلسة فيبقى كما هو.

        `row` يأتي من زرّ الصف نفسه؛ وبلا رقمٍ يعمل على المحدَّد
        (اختصار Delete).
        """
        r = self.items_table.currentRow() if row is None else int(row)
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

    def edit_item(self, row=None):
        """يفتح السطر كاملاً للتصحيح — بنفس خانات سطر الإدخال.

        **لماذا الصفّ كلّه لا الوزن وحده**: الخطأ في الإدخال السريع
        لا يقع في خانةٍ بعينها. وفتحُ نافذةٍ لكل خانة يعني ثلاث
        نوافذ لتصحيح سطرٍ واحد — فصارت نافذةً واحدة فيها ما في
        السطر، تُفتح من زرّ السطر نفسه فلا تُخطئ صاحبها.

        والوزن المقيد للطقم المفرد يبقى محروساً: تغييره يخالف بطاقة
        الطقم، فيُسأل عنه صراحةً قبل القبول.
        """
        r = self.items_table.currentRow() if row is None else int(row)
        if not (0 <= r < len(self.items)):
            err(self, "اختر سطراً من جدول البنود أولاً")
            return
        it = self.items[r]
        wo = it["wo"]
        if it.get("wage_only"):
            v, ok = QtWidgets.QInputDialog.getDouble(
                self, "تعديل سطر أجر فقط", "المبلغ (ريال):",
                float(it.get("amount") or 0), 0.01, 1e9, 2)
            if ok:
                n, ok2 = QtWidgets.QInputDialog.getText(
                    self, "تعديل سطر أجر فقط", "البيان:",
                    text=it.get("note") or "")
                it["amount"] = round(v, 2)
                if ok2:
                    it["note"] = n.strip()
                self.render_items()
            return
        k0 = int(it.get("karat") or kv.active())
        p = self._parts_of(it)
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(f"تعديل السطر — {wo['work_order_no']}")
        dlg.setMinimumWidth(460)
        w_model = kit.LineEdit(
            ((wo["model_no"] if "model_no" in wo.keys() else "") or ""))
        w_karat = kit.ComboBox()
        for kk in config.KARATS:
            w_karat.addItem(f"عيار {kk}", kk)
        i = w_karat.findData(k0)
        if i >= 0:
            w_karat.setCurrentIndex(i)
        w_reg, w_stand = wspin(), wspin()
        w_gold, w_small, w_big, w_after = wspin(), wspin(), wspin(), wspin()
        w_wage = mspin()
        w_reg.setValue(float(it.get("weight") or 0))
        w_stand.setValue(p["standing"])
        w_gold.setValue(p["gold"])
        w_small.setValue(p["small"])
        w_big.setValue(p["big"])
        w_after.setValue(p["after"])
        w_wage.setValue(float(it.get("wage") or 0))
        agreed = QtWidgets.QLabel(
            f"💠 المتفق عليه مع هذا العميل: {self._agreed_wage:,.2f}"
            if self._agreed_wage > 0 else "")
        agreed.setObjectName("cardSub")

        f = QtWidgets.QFormLayout()
        f.addRow("رقم الموديل:", w_model)
        f.addRow("رقم التشغيل:", QtWidgets.QLabel(wo["work_order_no"]))
        f.addRow("العيار:", w_karat)
        f.addRow("الوزن المقيد:", w_reg)
        f.addRow("الوزن القائم:", w_stand)
        f.addRow("الذهب:", w_gold)
        f.addRow("الفصوص:", w_small)
        f.addRow("الأحجار:", w_big)
        f.addRow("الأحجار بعد الخصم:", w_after)
        f.addRow("الأجر/جم:", w_wage)
        f.addRow(agreed)
        box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save
            | QtWidgets.QDialogButtonBox.Cancel)
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.addLayout(f)
        lay.addWidget(box)
        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return
        k = int(w_karat.currentData() or k0)
        reg = round(w_reg.value(), 3)
        if reg <= 0:
            err(self, "الوزن المقيد يجب أن يكون أكبر من صفر")
            return
        # 4.82: وزنٌ أقل من المتاح = جزءٌ يبقى باقيه (في الخزنة للبيع، وعند
        # الجهة للمرتجع) — يُقال صراحةً؛ والأكثر منه يُسأل عنه
        if not wo["is_bulk"]:
            try:
                from models import wo_moves as _wm
                with db(readonly=True) as conn:
                    _st = _wm.state(conn, wo)
                avail = (_st["rem"] if self.kind.currentData() == "sale"
                         else _st["out"]) or _st["full"]
                if self.editing_id is not None:
                    avail = max(avail, float(it.get("weight_store") or 0),
                                kv.store(float(it.get("weight") or 0), k0))
            except Exception:
                avail = float(wo["registered_weight"] or 0)
            new18 = kv.store(reg, k)
            if new18 > avail + 0.001:
                if not ask(self,
                           f"الطقم {wo['work_order_no']} المتاح منه"
                           f" {kv.g(avail, k):,.2f} {kv.unit(k)}، وأنت تكتب"
                           f" {reg:,.2f}.\n\nالمتابعة على أي حال؟"):
                    return
            elif new18 < avail - 0.001:
                where = ("في الخزنة ويُباع لاحقاً"
                         if self.kind.currentData() == "sale"
                         else "عند الجهة")
                info(self, f"يبقى من الطقم {wo['work_order_no']}"
                           f" {kv.g(avail - new18, k):,.2f} {kv.unit(k)}"
                           f" {where}.")
        # الأجر الدقيق (أجرةٌ مقطوعة قُسمت على الوزن) يبقى كما هو ما لم
        # يُغيَّر رقمه الظاهر أو عياره — فحفظ النافذة بلا تغييرٍ لا يقرّبه
        wage = round(w_wage.value(), 2)
        if k == k0 and reg == round(float(it.get("weight") or 0), 3) and \
                abs(wage - round(float(it.get("wage") or 0), 2)) < 0.005:
            wage = float(it.get("wage") or 0)
        it.update({"karat": k, "weight": reg,
                   "wage": wage,
                   "gold": round(w_gold.value(), 3),
                   "small": round(w_small.value(), 3),
                   "big": round(w_big.value(), 3),
                   "after": round(w_after.value(), 3),
                   "standing": round(w_stand.value() or reg, 3)})
        typed = w_model.text().strip()
        cur_model = ((wo["model_no"] if "model_no" in wo.keys() else "")
                     or "").strip()
        if typed and typed != cur_model:
            try:
                from models import models_catalog as mc
                with db() as conn:
                    mc.assign_model(conn, wo["id"], typed,
                                    self.user["username"])
                    it["wo"] = inventory.get_wo_by_no(
                        conn, wo["work_order_no"]) or wo
                self._remember_model_change(wo, cur_model)
                self._reload_models()
            except Exception:
                pass      # الموديل وصفي: فشله لا يُبطل تصحيح الأوزان
        self._wage_hint(kv.rate(kv.rate_store(it["wage"], k)))
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
        if col in self.WAGE_COLS:
            # بعد لحظة: خانةٌ أخرى كانت مفتوحة تُعتمد ويُعاد رسم الجدول
            # أولاً، ثم تُفتح هذه على البيانات الجديدة
            QtCore.QTimer.singleShot(
                0, lambda: self.start_wage_edit(row, col))
            return
        if col != 1:          # العمود الأول للأزرار، والموديل يليه
            return
        try:
            show_model_image(self, cell(self.items_table, row, 1))
        except Exception as e:
            info(self, str(e), "صورة الموديل")

    # ══ الأجر في خانته (4.59) ══
    def _wage_editable(self, row, col):
        """تُكتب الخانة في مكانها؟ أسطر البنود وحدها — لا صفّ الإجمالي،
        ولا شيء في التحويل الداخلي (بلا أجور). وسطر «أجر فقط» خانته
        المبلغ، والأجرة الكلية لسطرٍ بلا وزنٍ لا تُقسَم على شيء."""
        if col not in self.WAGE_COLS or not (0 <= row < len(self.items)):
            return False
        cid = self.customer.currentData()
        if cid is not None and self._is_internal(cid):
            return False
        it = self.items[row]
        if it.get("wage_only"):
            return col == self.C_AMOUNT
        return col == self.C_WAGE or float(it.get("weight") or 0) > 0

    def _inline_value(self, row, col):
        if not (0 <= row < len(self.items)):
            return 0.0
        it = self.items[row]
        if it.get("wage_only"):
            return float(it.get("amount") or 0)
        if col == self.C_WAGE:
            return round(float(it.get("wage") or 0), 2)
        return gold_math.total_wages(float(it.get("wage") or 0),
                                     float(it.get("weight") or 0))

    def _set_inline_wage(self, row, col, val):
        """يكتب ما أُدخل في بيانات السطر — ويعيد هل تغيّر شيء.

        الأجر/جم يُحفظ كما كُتب. والأجرة الكلية (ريال) تُقسَم على الوزن
        المقيد بستّ منازل — فأجرةٌ مقطوعة للقطعة تبقى هي هي في الفاتورة
        ولا تزيد هللةً ولا تنقصها بالتقريب.
        """
        if not self._wage_editable(row, col):
            return False
        it = self.items[row]
        val = round(max(0.0, float(val or 0)), 2)
        if abs(val - self._inline_value(row, col)) < 0.005:
            return False
        if it.get("wage_only"):
            if val <= 0:
                return False     # سطر أجرٍ بلا مبلغ يُحذف بزرّه لا يُصفَّر
            it["amount"] = val
        elif col == self.C_WAGE:
            it["wage"] = val
        else:
            it["wage"] = round(val / float(it["weight"]), 6)
        return True

    def _after_inline_wage(self, row, col, move=0, changed=True):
        if changed:
            it = self.items[row] if 0 <= row < len(self.items) else None
            if it is not None and not it.get("wage_only"):
                k = int(it.get("karat") or kv.active())
                self._wage_hint(kv.rate(kv.rate_store(it["wage"], k)))
            self.render_items()
        if move:
            nxt = self._next_wage_row(row, col, move)
            if nxt is not None:
                self.start_wage_edit(nxt, col)
                return
            if move > 0:
                # بعد آخر سطر: إلى رقم التشغيل لطقمٍ تالٍ — Enter يمضي
                # إلى الأمام في الشاشة كلها
                self._focus(self.barcode)
                return
        if 0 <= row < len(self.items):
            self.items_table.setCurrentCell(row, col)
        self.items_table.setFocus()

    def _next_wage_row(self, row, col, step):
        r = row + step
        while 0 <= r < len(self.items):
            if self._wage_editable(r, col):
                return r
            r += step
        return None

    def start_wage_edit(self, row, col=None):
        """يفتح خانة أجر السطر للكتابة في مكانها."""
        col = self.C_WAGE if col is None else col
        if 0 <= row < len(self.items) and self.items[row].get("wage_only"):
            col = self.C_AMOUNT          # سطر «أجر فقط»: مبلغه هو أجره
        if not self._wage_editable(row, col):
            return False
        item = self.items_table.item(row, col)
        if item is None:
            return False
        self.items_table.setCurrentCell(row, col)
        self.items_table.scrollToItem(item)
        self.items_table.setFocus()
        self.items_table.editItem(item)
        return True

    def _wage_menu(self, pos):
        """أفعال الأجر في قائمة الزر الأيمن على سطرٍ من البنود."""
        idx = self.items_table.indexAt(pos)
        r = idx.row() if idx.isValid() else -1
        if not (0 <= r < len(self.items)):
            return []
        cid = self.customer.currentData()
        if cid is not None and self._is_internal(cid):
            return []
        it = self.items[r]
        sets = [i for i in self.items if not i.get("wage_only")]
        out = [("✎ تعديل الأجر في خانته",
                lambda: self.start_wage_edit(r, idx.column()
                                             if idx.column() in
                                             self.WAGE_COLS else None))]
        if not it.get("wage_only") and len(sets) > 1:
            k = int(it.get("karat") or kv.active())
            w = float(it.get("wage") or 0)
            out.append((f"⇊ أجر هذا السطر ({w:,.2f}/جم {k}) لكل الأطقم",
                        lambda: self.apply_wage_all(w, k)))
        if self._agreed_wage > 0 and sets:
            a = self._agreed_wage
            out.append((f"💠 الأجرة المتفق عليها ({a:,.2f}) لكل الأطقم",
                        lambda: self.apply_wage_all(a, kv.active())))
        return out

    def apply_wage_all(self, wage, karat):
        """أجرٌ واحد لكل أطقم الفاتورة — بمكافئه في عيار كل سطر.

        الأجر/جم بعيارٍ يقابله في غيره أجرٌ يُبقي الأجرة نفسها لذهبٍ واحد
        (`kv.rate`): 18 ريالاً لجرام 18 هي 21 لجرام 21. وأسطر «أجر فقط»
        لا تُمسّ.
        """
        self._wage_delegate.flush()
        karat = int(karat or kv.active())
        n = 0
        for it in self.items:
            if it.get("wage_only"):
                continue
            k = int(it.get("karat") or kv.active())
            it["wage"] = (round(float(wage), 6) if k == karat
                          else round(float(wage) * k / karat, 6))
            n += 1
        if n:
            self._wage_hint(kv.rate(kv.rate_store(wage, karat)))
            self.render_items()
        return n

    def _mark_wage_cells(self):
        """خانات الأجر القابلة للكتابة بلونٍ ذهبي خفيف — وما سواها لا
        يُكتب (فالكتابة والخانة محدّدة لا تفتح إلا الأجر)."""
        tint = QtGui.QColor(201, 162, 39, 46)
        tip = ("انقر لتعديل الأجر هنا — Enter يحفظ وينزل للسطر التالي،"
               " وEsc يتراجع")
        t = self.items_table
        for r in range(t.rowCount()):
            for c in range(t.columnCount()):
                x = t.item(r, c)
                if x is None:
                    continue
                if self._wage_editable(r, c):
                    x.setFlags(x.flags() | QtCore.Qt.ItemIsEditable)
                    x.setBackground(tint)
                    x.setToolTip(tip)
                else:
                    x.setFlags(x.flags() & ~QtCore.Qt.ItemIsEditable)

    # ══════════════════════════════════════════════════════════════
    #  العرض والحساب
    # ══════════════════════════════════════════════════════════════

    def render_items(self):
        cid = self.customer.currentData()
        internal = cid is not None and self._is_internal(cid)
        rows = []
        t = {"reg": 0.0, "standing": 0.0, "gold": 0.0, "small": 0.0,
             "big": 0.0, "after": 0.0, "wages": 0.0}
        n_sets = 0
        for it in self.items:
            wo = it["wo"]
            if it.get("wage_only"):
                amt = 0.0 if internal else float(it.get("amount") or 0)
                rows.append(("", "—", "أجر فقط" + (
                    f" — {it['note']}" if it.get("note") else ""),
                    "—", "أجور العميل", "", "", "", "", "", "", "—", amt))
                t["wages"] += amt
                continue
            n_sets += 1
            k = int(it.get("karat") or kv.active())
            wage = 0.0 if internal else (it["wage"] or 0.0)
            weight = float(it.get("weight") or 0)
            p = self._parts_of(it)
            mn = (wo["model_no"] if "model_no" in wo.keys() else "") or "—"
            # 🖼 يسبق الموديل الذي له صورة محفوظة — فيُعرف القابل للنقر
            if mn != "—" and has_model_image(mn):
                mn = f"🖼 {mn}"
            wages = gold_math.total_wages(wage, weight)
            rows.append(("", mn, wo["work_order_no"], f"عيار {k}",
                         self._line_acc_name(it), weight,
                         p["standing"], p["gold"], p["small"], p["big"],
                         p["after"], wage, wages))
            # الإجماليات تُجمع بمكافئ 18 لا بأرقام الشاشة: أسطرٌ
            # بأعيرةٍ مختلفة لا يصحّ جمعها كما تُعرض.
            t["reg"] += kv.store(weight, k)
            for key in ("standing", "gold", "small", "big", "after"):
                t[key] += kv.store(p[key], k)
            t["wages"] += wages
        if rows:
            u = kv.active()
            n_w = len(self.items) - n_sets
            rows.append(("", "الإجمالي", f"{n_sets} طقم"
                         + (f" + {n_w} أجر" if n_w else ""),
                         f"عيار {u}", "", round(kv.g(t['reg']), 3),
                         round(kv.g(t["standing"]), 3),
                         round(kv.g(t["gold"]), 3),
                         round(kv.g(t["small"]), 3),
                         round(kv.g(t["big"]), 3),
                         round(kv.g(t["after"]), 3), "—",
                         round(t["wages"], 2)))
        fill(self.items_table, self.COLS, rows)
        # صفوفٌ أعلى من جداول العرض: البنود تُراجَع رقماً رقماً قبل الترحيل
        self.items_table.verticalHeader().setDefaultSectionSize(
            row_height(self.items_table) + 12)
        fit_columns(self.items_table, self.COL_W)
        if rows:
            self._bold_row(len(rows) - 1)
            # الأزرار لأسطر البنود وحدها — وصفُّ الإجمالي لا يُعدَّل
            row_action_buttons(self.items_table, len(self.items),
                               on_edit=self.edit_item,
                               on_delete=self.remove_item,
                               edit_tip="تعديل هذا السطر كاملاً",
                               del_tip="حذف هذا السطر من الفاتورة")
        self._mark_wage_cells()
        self.recalc()

    def _bold_row(self, r):
        """صفُّ الإجمالي يُعلَّم فلا يُقرأ سطراً من البنود."""
        try:
            from ui import theme
            pal = theme.palette(theme.current_theme())
            bg = QtGui.QColor(pal.get("totBg", "#1C1A17"))
            ink = QtGui.QColor(pal.get("totFg", "#FFFFFF"))
        except Exception:
            bg, ink = QtGui.QColor("#1C1A17"), QtGui.QColor("#FFFFFF")
        for c in range(self.items_table.columnCount()):
            item = self.items_table.item(r, c)
            if item is None:
                continue
            f = item.font()
            f.setBold(True)
            item.setFont(f)
            item.setBackground(bg)
            item.setForeground(ink)

    def recalc(self):
        cid = self.customer.currentData()
        internal = cid is not None and self._is_internal(cid)
        w18 = round(sum(self._store_w(i) for i in self.items), 3)
        u = kv.unit()
        if internal:
            self.p_weight.set_value(f"{kv.g(w18):,.2f} {u}",
                                    "تحويل داخلي — بالوزن وحده")
            self.p_wages.set_value("—", "بلا أجور ولا ضريبة")
            self._update_live_balance(cid, w18, 0.0)
            return
        wages = round(sum(self._wages_of(i) for i in self.items), 2)
        self.p_weight.set_value(
            f"{kv.g(w18):,.2f} {u}",
            f"{len(self.items)} طقم — وهو وعاء الأجور")
        if self.vat_check.isChecked():
            vat = gold_math.wages_vat(wages)
            self.p_wages.set_value(
                f"{wages + vat:,.2f} ريال",
                f"الأجور {wages:,.2f} + ضريبة 15% {vat:,.2f}")
        else:
            self.p_wages.set_value(f"{wages:,.2f} ريال",
                                   "فاتورة غير ضريبية — بلا QR")
        self._update_live_balance(cid, w18, wages)

    def _update_live_balance(self, cid, weight18, wages):
        """رصيد العميل بعد ترحيل هذه الفاتورة — قبل أن تُرحَّل.

        الرقم الذي يُسأل عنه في كل فاتورة: «كم صار عليه؟». حسابه
        هنا: الرصيد الدفتري الحالي + أثر ما في الشاشة (بيعٌ يزيد،
        مرتجعٌ ينقص).
        """
        if cid is None:
            self.p_gold_bal.set_value("—", "اختر العميل أولاً")
            self.p_cash_bal.set_value("—", "")
            return
        try:
            with db() as conn:
                gold_bal, cash_bal = entities.balances(conn, cid)
        except Exception:
            self.p_gold_bal.set_value("—", "تعذّرت قراءة الرصيد")
            self.p_cash_bal.set_value("—", "")
            return
        sign = -1 if self.kind.currentData() == "sale_return" else 1
        gold_after = round(gold_bal + sign * weight18, 3)
        cash_after = round(cash_bal + sign * wages, 2)
        u = kv.unit()

        def _f(v, dec=2):
            # السالب بين قوسين: الإشارة قبل الرقم تنقلب في السطر
            # العربي فتُقرأ «1,234.5-»، والقوسان عرفٌ محاسبي لا يلتبس.
            return (f"({abs(v):,.{dec}f})" if v < 0 else f"{v:,.{dec}f}")

        self.p_gold_bal.set_value(
            f"{_f(kv.g(gold_after))} {u}",
            f"كان {_f(kv.g(gold_bal))} {u} قبل هذه الفاتورة")
        self.p_cash_bal.set_value(
            f"{_f(cash_after)} ريال",
            f"كان {_f(cash_bal)} ريال قبل هذه الفاتورة")

    # ══════════════════════════════════════════════════════════════
    #  الترحيل
    # ══════════════════════════════════════════════════════════════

    def save(self):
        # أجرٌ كُتب في خانته ولم تُغادَر بعد (F2 والخانة مفتوحة) يُعتمد أولاً
        self._wage_delegate.flush()
        try:
            cid = self.customer.currentData()
            if cid is None:
                raise ValueError("اختر العميل أو الطرف المقابل")
            if not self.items:
                raise ValueError("أضف طقماً واحداً على الأقل")
            internal = self._is_internal(cid)
            apply_vat = False if internal else self.vat_check.isChecked()
            src_id = self.source.currentData()
            karat = (self.scrap_karat.currentData()
                     if self._is_scrap_source() else None)
            # الحد الفاصل: كل ما يعبر إلى القاعدة بمكافئ 18
            cart = [({"wage_only": True, "amount": i["amount"],
                      "note": i.get("note") or "",
                      "item_id": i.get("item_id"), "weight": 0.0}
                     if i.get("wage_only") else
                     {"work_order_id": i["wo"]["id"],
                      # سطرٌ حُمِّل من فاتورةٍ تُعدَّل يحمل رقمه؛
                      # والمُضاف حديثاً بلا رقم فيُسجَّل سطراً جديداً
                      "item_id": i.get("item_id"),
                      "weight": self._store_w(i),
                      "karat": int(i.get("karat") or kv.active()),
                      "wage_override": (None if internal
                                        else self._wage_store(i))})
                    for i in self.items]
            desc = self.description.text().strip()
            # تأكيد الترحيل: أثر محاسبي لا يُلغى إلا بقيد عكسي
            kind_label = ("فاتورة مبيعات"
                          if self.kind.currentData() == "sale"
                          else "فاتورة مرتجع")
            tot_w = round(sum(c["weight"] for c in cart), 3)
            tot_wage = sum(self._wages_of(i) for i in self.items)
            # الذهب موزّعاً على حساباته: كل طقمٍ يخرج من حسابه
            _by = {}
            for i in self.items:
                if i.get("wage_only"):
                    continue
                n = self._line_acc_name(i)
                _by[n] = _by.get(n, 0.0) + self._store_w(i)
            _acc_txt = "".join(
                f"\n   • {n}: {kv.g(w):,.2f} {kv.unit()}"
                for n, w in _by.items())
            if not confirm_post(
                    self,
                    f"{kind_label}\n\n"
                    f"الطرف: {self.customer.currentText()}\n"
                    + ("إلى حساب: " if self._is_return() else "من حساب: ")
                    + f"{self.source.currentText()}"
                    + (f" — عيار {karat}" if karat else "") + "\n"
                    f"عدد الأطقم: {len(self.items)}\n"
                    + (("دخول الذهب إلى:" if self._is_return()
                        else "خروج الذهب من:") + _acc_txt + "\n"
                       if _by else "")
                    + f"الوزن المقيد: {kv.g(tot_w):,.2f} {kv.unit()}\n"
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
                        # التاريخ والحساب يُمرَّران كما هما في الشاشة:
                        # إن غيّرهما المستخدم انتقلت الفاتورة إليهما.
                        res = invoices.update_invoice(
                            conn, self.editing_id, cart,
                            self.user["username"], apply_vat=apply_vat,
                            description=desc,
                            invoice_date=dstr(self.date),
                            source_account_id=src_id, scrap_karat=karat,
                            # الطرف كما في الشاشة: إن غيّره المستخدم
                            # انتقلت الذمّة كلها إلى الطرف الجديد
                            entity_id=cid)
                    elif self.kind.currentData() == "sale":
                        res = invoices.create_sale(
                            conn, cid, cart, dstr(self.date),
                            self.user["username"], apply_vat, desc,
                            qr_enabled=self.qr_check.isChecked(),
                            source_account_id=src_id, scrap_karat=karat)
                    else:
                        res = invoices.create_sale_return(
                            conn, cid, cart, dstr(self.date),
                            self.user["username"], apply_vat, desc,
                            qr_enabled=self.qr_check.isChecked(),
                            source_account_id=src_id, scrap_karat=karat)
                    # المعلّقة المستكملة أُثبتت الآن — تخرج من المعلّقات
                    # في المعاملة نفسها (فلا تبقى معلّقةً فاتورةٌ رُحّلت)
                    if self._held_id and self.editing_id is None:
                        pending.drop_held(
                            conn, self._held_id, self.user["username"],
                            f"أُثبتت بالفاتورة {res.get('invoice_no', '')}")
            # ══ نشر صفحة الفاتورة — **بعد إغلاق المعاملة، وخارج خيط
            #    الواجهة** ══
            # الرفع داخل معاملة الكتابة يحبس قفل القاعدة ثوانيَ فتتعطّل
            # المزامنة. وعلى خيط الواجهة تبقى النافذة لا تستجيب حتى
            # ينتهي. فهنا في خيطٍ جانبي بسقف انتظارٍ عشر ثوانٍ: بعده
            # يُكمل الرفع في الخلفية ولا يُحبَس أحدٌ خلف شبكةٍ بطيئة.
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
                if not parts and res.get("moved_date"):
                    parts.append("نُقل تاريخها")
                if not parts and res.get("moved_source"):
                    parts.append("نُقل حسابها")
                info(self,
                     f"عُدّلت الفاتورة {res['invoice_no']} في مكانها.\n"
                     + ("   ·   ".join(parts) or "لا تغيير")
                     + f"\n\nالوزن: "
                       f"{kv.g(res.get('total_weight', 0)):,.2f} "
                       f"{kv.unit()}"
                       f"   ·   الأجور: {res.get('total_wages', 0):,.2f} ريال"
                     + stock
                     + ("\n\nرقم الفاتورة ثابت، وتاريخها نُقل من "
                        f"{res['moved_date'][0]} إلى "
                        f"{res['moved_date'][1]} — وقيدُها معه."
                        if res.get("moved_date")
                        else "\n\nرقم الفاتورة وتاريخها لم يتغيّرا.")
                     + (f"\nوحساب الذهب نُقل من {res['moved_source'][0]} "
                        f"إلى {res['moved_source'][1]}."
                        if res.get("moved_source") else ""))
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
                             f"{res['grand_total']:,.2f} ريال\n"
                             f"من حساب: {res.get('source_name', '—')}",
                       "invoices", res["id"])
            self.editing_id = None
            if self._held_id:
                self._held_id = None
                self.load_held()
            self.description.clear()
            self.clear_items()
            self._clear_entry()
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
            self._reload_sources(conn)
        reload_combo(self.customer, self.customers,
                    lambda r: ("🏭 " if r["is_internal"] else
                              f"[{entities.TYPE_LABELS[r['entity_type']]}] ")
                              + r["name"])
        self.render_items()
        self.customer_changed()
        # الاستعادة بعد تعبئة قائمة العملاء: قبلها لا يوجد ما يُختار
        # منه، فيضيع العميل المحفوظ في المسوّدة.
        self._restore_draft()
        self.load_held()             # عدّاد «المعلّقات» على عنوانه
