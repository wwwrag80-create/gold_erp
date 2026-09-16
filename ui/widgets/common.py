# -*- coding: utf-8 -*-
"""مكونات واجهة مشتركة: حقول أوزان/مبالغ، جداول، رسائل، مربعات اختيار."""
from PyQt5 import QtCore, QtGui, QtWidgets


class Card(QtWidgets.QFrame):
    """بطاقة إحصائية قابلة للنقر (للوحة التحكم التفاعلية) — تصدر clicked
    عند الضغط لفتح دفتر الأستاذ العام مفلتراً على حساب البطاقة."""
    clicked = QtCore.pyqtSignal()

    def __init__(self, title, subtitle_hint=""):
        super().__init__()
        self.setObjectName("card")
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setSpacing(4)
        self.title_lbl = QtWidgets.QLabel(title)
        self.title_lbl.setObjectName("cardTitle")
        self.value_lbl = QtWidgets.QLabel("—")
        self.value_lbl.setObjectName("cardValue")
        self.sub_lbl = QtWidgets.QLabel(subtitle_hint)
        self.sub_lbl.setObjectName("cardSub")
        lay.addWidget(self.title_lbl)
        lay.addWidget(self.value_lbl)
        lay.addWidget(self.sub_lbl)

    def set_value(self, value_text, subtitle=None):
        self.value_lbl.setText(value_text)
        if subtitle is not None:
            self.sub_lbl.setText(subtitle)

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)


class _BlankZeroSpin(QtWidgets.QDoubleSpinBox):
    """QDoubleSpinBox يظهر فارغاً تماماً عند القيمة صفر (بدل "0.00") —
    يمنع أخطاء التداخل أثناء الإدخال السريع، ويعمل بلا أثر جانبي على
    Range أو minimum/maximum الفعلي للحقل (خلافاً لـ setSpecialValueText
    التي ترتبط حصراً بالحد الأدنى)."""

    def textFromValue(self, value):
        if value == 0:
            return ""
        return super().textFromValue(value)

    def valueFromText(self, text):
        if not text.strip():
            return 0.0
        return super().valueFromText(text)

    def validate(self, text, pos):
        if not text.strip():
            return (QtGui.QValidator.Acceptable, text, pos)
        return super().validate(text, pos)


def wspin(maximum=10_000_000.0):
    s = _BlankZeroSpin()
    s.setDecimals(2)
    s.setRange(0.0, maximum)
    s.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
    s.setGroupSeparatorShown(True)
    return s


def mspin(maximum=1_000_000_000.0, minimum=0.0):
    s = _BlankZeroSpin()
    s.setDecimals(2)
    s.setRange(minimum, maximum)
    s.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
    s.setGroupSeparatorShown(True)
    return s


def date_edit():
    d = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
    d.setCalendarPopup(True)
    d.setDisplayFormat("yyyy-MM-dd")
    return d


def qdstr(qdate) -> str:
    """نص التاريخ `YYYY-MM-DD` **بأرقام إنجليزية دائماً**.

    على ويندوز بلغة عربية يُنتج `QDate.toString` أرقاماً عربية-هندية
    (`٢٠٢٦-٠٩-١٦`). والتواريخ تُحفظ نصاً وتُقارَن نصاً، ورمز الرقم
    العربي في يونيكود أكبر من الإنجليزي — فالتاريخ العربي يفشل في
    شرط «أصغر من أو يساوي» ويسقط من كل فلتر.

    وهذا يضرب من طرفين معاً: ما يُحفظ (فيصير القيد غير مرئي)، وما
    يُبحث به (فلا يطابق الفلتر شيئاً ويظهر كل شيء «رصيداً سابقاً»).
    كل نص تاريخ في النظام يمرّ من هنا.
    """
    from services.dates import normalize_digits
    return normalize_digits(qdate.toString("yyyy-MM-dd"))


def dstr(date_widget) -> str:
    return qdstr(date_widget.date())


def make_table(stretch_last=True):
    """جدول بمواصفات أنظمة ERP: أعمدة تتمدد لملء الإطار، صفوف متناوبة
    الألوان، رأس داكن غامق، إخفاء أرقام الصفوف، وارتفاع صف مريح."""
    t = QtWidgets.QTableWidget()
    t.setAlternatingRowColors(True)
    t.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    t.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
    t.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    t.setWordWrap(False)
    t.setShowGrid(True)
    vh = t.verticalHeader()
    vh.setVisible(False)                     # إخفاء أرقام الصفوف الجانبية
    # الخط يبقى بحجمه الطبيعي؛ الاتساع يُعالَج بلفّ النص داخل الخانة
    # (كلمة تحت كلمة) بدل تصغير الخط أو تمديد الجدول أفقياً.
    vh.setDefaultSectionSize(38)
    vh.setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
    hh = t.horizontalHeader()
    hh.setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
    hh.setHighlightSections(False)
    hh.setMinimumSectionSize(56)
    hh.setDefaultAlignment(QtCore.Qt.AlignCenter)
    hh.setStretchLastSection(False)
    # رأس الجدول يلفّ عناوينه الطويلة على سطرين بدل تمديد العمود
    hh.setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
    try:
        hh.setTextElideMode(QtCore.Qt.ElideNone)
    except Exception:
        pass
    t.setWordWrap(True)                      # لفّ النص داخل الخانة
    t.setTextElideMode(QtCore.Qt.ElideNone)
    # لا تمرير أفقي: الأعمدة تتوزّع على العرض المتاح دائماً
    t.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    t.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
    # مُحجِّم موحّد: يوزّع الأعمدة على العرض المتاح ويتابع تغيّر الحجم
    try:
        from ui.widgets.table_fit import fit_columns
        fit_columns(t)
    except Exception:
        pass
    return t


def stretch_column(table, col):
    """يجعل عموداً بعينه (البيان/اسم الحساب) هو الذي يملأ الفراغ،
    وبقية الأعمدة بحجم محتواها."""
    hh = table.horizontalHeader()
    for c in range(table.columnCount()):
        hh.setSectionResizeMode(
            c, QtWidgets.QHeaderView.Stretch if c == col
            else QtWidgets.QHeaderView.ResizeToContents)


# فوق هذا العدد يُعطَّل لفّ النص وقياس المحتوى — كلاهما يقيس كل
# خلية على حدة فيتجمّد النظام على الجداول الكبيرة.
BIG_TABLE = 120


def fill(table, headers, rows):
    """يملأ الجدول دفعةً واحدة — بلا قياس مكلف على الجداول الكبيرة.

    **الخلل السابق**: `resizeColumnsToContents()` يقيس كل خلية في كل
    عمود، و`resizeRowsToContents()` مع لفّ النص يقيس كل صف — على 600
    صف يعني مئات آلاف القياسات، فيتجمّد النظام دقائق.

    الآن: التحديث مُعطَّل أثناء الملء، والقياس المكلف يُستبدل بتوزيع
    نسبي حسابي لا يقرأ المحتوى.
    """
    big = len(rows) > BIG_TABLE
    try:
        table.setUpdatesEnabled(False)
        table.setSortingEnabled(False)
        if big:
            # لفّ النص وارتفاع الصف التلقائي مكلفان جداً هنا
            table.setWordWrap(False)
            vh = table.verticalHeader()
            vh.setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
            vh.setDefaultSectionSize(26)
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                if isinstance(val, float):
                    val = (f"{val:,.2f}".rstrip("0").rstrip(".")
                           if abs(val) < 1e12 else str(val))
                item = QtWidgets.QTableWidgetItem(
                    "" if val is None else str(val))
                table.setItem(r, c, item)
    finally:
        try:
            table.setUpdatesEnabled(True)
        except Exception:
            pass

    try:
        from ui.widgets.table_fit import fit_columns
        # التوزيع النسبي حسابي محض — لا يقرأ محتوى الخلايا
        fit_columns(table)
    except Exception:
        pass

def cell(table, row, col):
    it = table.item(row, col)
    return it.text() if it else ""


def info(parent, text, title="تم بنجاح"):
    QtWidgets.QMessageBox.information(parent, title, text)


def err(parent, text, title="خطأ"):
    QtWidgets.QMessageBox.critical(parent, title, str(text))


def warn(parent, text, title="تنبيه"):
    QtWidgets.QMessageBox.warning(parent, title, text)


def ask(parent, text, title="تأكيد") -> bool:
    r = QtWidgets.QMessageBox.question(
        parent, title, text,
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
    return r == QtWidgets.QMessageBox.Yes


def reload_combo(cb, rows, label_fn, id_key="id"):
    """يعيد تعبئة القائمة مع الحفاظ على الاختيار الحالي إن أمكن.

    حقول البحث الذكية (SearchCombo) تبدأ **فارغة** بلا اسم افتراضي —
    فلا يُرحَّل أي مستند على جهة لم يخترها المستخدم صراحةً."""
    current = cb.currentData()
    cb.blockSignals(True)
    cb.clear()
    for r in rows:
        cb.addItem(label_fn(r), r[id_key])
    restored = False
    if current is not None:
        idx = cb.findData(current)
        if idx >= 0:
            cb.setCurrentIndex(idx)
            restored = True
    if not restored and isinstance(cb, SearchCombo):
        cb.clear_selection()
    cb.blockSignals(False)


def title_label(text):
    lb = QtWidgets.QLabel(text)
    lb.setObjectName("title")
    return lb


def big_label(text=""):
    lb = QtWidgets.QLabel(text)
    lb.setObjectName("big")
    return lb


# ═══════════ قائمة منسدلة قابلة للبحث (Searchable Autocomplete) ═══════════

def _norm(text):
    """تطبيع عربي خفيف للبحث: توحيد الهمزات والتاء المربوطة والألف
    المقصورة وحذف التطويل — حتى يجد «الافق» الاسمَ «الأفق»."""
    m = {"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي",
         "ؤ": "و", "ئ": "ي", "\u0640": ""}
    return "".join(m.get(c, c) for c in (text or "")).strip().lower()


class SearchCombo(QtWidgets.QComboBox):
    """حقل اختيار ذكي: يبدأ فارغاً بلا اسم افتراضي، يقبل الكتابة اليدوية،
    ويقترح الأسماء/الحسابات المتقاربة فور كتابة أول الحروف. إن لم يُطابق
    ما كُتبَ أي عنصر يُترك الاختيار فارغاً حتى لا تُلتقط قيمة خاطئة."""

    def __init__(self, placeholder="اكتب أول الحروف للبحث…"):
        super().__init__()
        self.setEditable(True)
        self.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.setMinimumWidth(240)
        self.lineEdit().setPlaceholderText(placeholder)
        comp = QtWidgets.QCompleter(self)
        comp.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        comp.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        comp.setFilterMode(QtCore.Qt.MatchContains)
        comp.setModel(self.model())
        self.setCompleter(comp)
        self.lineEdit().editingFinished.connect(self._resolve)

    def setModel(self, model):
        """يُعيد ربط المكمّل بالنموذج الجديد.

        **الخلل السابق**: المكمّل يحتفظ بمرجع النموذج القديم عند
        `setModel`، فيتوقف اقتراح الأسماء عند أول حرف — وهو ما حدث
        بعد تحويل قوائم القيود إلى نموذج مشترك.
        """
        try:
            super().setModel(model)
        except AttributeError:
            pass          # بيئة اختبار بلا Qt حقيقي
        try:
            c = self.completer()
            if c is not None:
                c.setModel(model)
                c.setCompletionColumn(0)
        except Exception:
            pass

    def _resolve(self):
        """يحوّل النص المكتوب إلى اختيار فعلي (مطابق ثم مُطبَّع ثم جزئي)."""
        txt = self.lineEdit().text().strip()
        if not txt:
            self.setCurrentIndex(-1)
            return
        if self.currentIndex() >= 0 and self.itemText(self.currentIndex()) == txt:
            return
        items = [self.itemText(i) for i in range(self.count())]
        for i, t in enumerate(items):
            if t == txt:
                self.setCurrentIndex(i)
                return
        n = _norm(txt)
        for i, t in enumerate(items):
            if _norm(t) == n:
                self.setCurrentIndex(i)
                return
        for i, t in enumerate(items):
            if n in _norm(t):
                self.setCurrentIndex(i)
                return
        self.setCurrentIndex(-1)          # لا مطابقة — يبقى فارغاً
        self.lineEdit().clear()

    def currentData(self, role=QtCore.Qt.UserRole):
        idx = self.currentIndex()
        if idx < 0:
            return None
        return self.itemData(idx, role)

    def clear_selection(self):
        self.setCurrentIndex(-1)
        self.lineEdit().clear()


def search_combo(placeholder="اكتب أول الحروف للبحث…"):
    return SearchCombo(placeholder)


# ═══════════ التنقل بزر Enter وإضافة الأسطر آلياً ═══════════

class _EnterNav(QtCore.QObject):
    """ينقل مؤشر الكتابة للخانة التالية عند Enter؛ وعند آخر خانة ينفّذ
    on_last (إضافة سطر جديد) ثم يعيد التركيز لأول خانة للإدخال الفوري."""

    def __init__(self, chain, on_last=None, parent=None):
        super().__init__(parent)
        self.chain = list(chain)
        self.on_last = on_last
        for w in self.chain:
            w.installEventFilter(self)

    def _focus(self, w):
        w.setFocus(QtCore.Qt.OtherFocusReason)
        if hasattr(w, "selectAll"):
            w.selectAll()
        elif hasattr(w, "lineEdit") and w.lineEdit() is not None:
            w.lineEdit().selectAll()

    def eventFilter(self, obj, ev):
        if ev.type() != QtCore.QEvent.KeyPress:
            return False
        key = ev.key()

        # ══ التنقّل بالأسهم بين الخانات ══
        # الواجهة عربية (يمين ← يسار): السهم الأيسر يتقدّم للخانة
        # التالية والأيمن يرجع للسابقة — كاتجاه القراءة نفسه.
        # لا نعترض السهم إن كان المؤشر داخل نص ولم يبلغ طرفه، فيبقى
        # تحريك المؤشر داخل الحقل ممكناً.
        if key in (QtCore.Qt.Key_Left, QtCore.Qt.Key_Right):
            try:
                i = self.chain.index(obj)
            except ValueError:
                return False
            le = obj if hasattr(obj, "cursorPosition") else (
                obj.lineEdit() if hasattr(obj, "lineEdit") else None)
            if le is not None and hasattr(le, "cursorPosition"):
                pos = le.cursorPosition()
                length = len(le.text() or "")
                if key == QtCore.Qt.Key_Left and pos < length:
                    return False          # ما زال داخل النص
                if key == QtCore.Qt.Key_Right and pos > 0:
                    return False
            nxt = i + (1 if key == QtCore.Qt.Key_Left else -1)
            if 0 <= nxt < len(self.chain):
                self._focus(self.chain[nxt])
                return True
            return False

        if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            try:
                i = self.chain.index(obj)
            except ValueError:
                return False
            if i < len(self.chain) - 1:
                self._focus(self.chain[i + 1])
            else:
                if self.on_last:
                    self.on_last()
                if self.chain:
                    self._focus(self.chain[0])
            return True
        return False


def enter_chain(widget_owner, widgets, on_last=None):
    """يفعّل تسلسل Enter على قائمة حقول. يُحفظ المرجع على الشاشة نفسها
    حتى لا يُلتقط بواسطة جامع المهملات."""
    nav = _EnterNav(widgets, on_last, widget_owner)
    if not hasattr(widget_owner, "_enter_navs"):
        widget_owner._enter_navs = []
    widget_owner._enter_navs.append(nav)
    return nav


def confirm_post(parent, summary):
    """تأكيد صريح قبل ترحيل أي عملية محاسبية.

    الترحيل يُحدث أثراً في الحسابات ولا يُلغى إلا بقيد عكسي، فيستحق
    تأكيداً واعياً — كما في أنظمة ERP الكبيرة.
    """
    box = QtWidgets.QMessageBox(parent)
    box.setWindowTitle("تأكيد الترحيل")
    box.setIcon(QtWidgets.QMessageBox.Question)
    box.setText("هل تريد ترحيل هذه العملية؟")
    box.setInformativeText(summary)
    yes = box.addButton("✔ ترحيل", QtWidgets.QMessageBox.AcceptRole)
    box.addButton("إلغاء", QtWidgets.QMessageBox.RejectRole)
    box.exec_()
    return box.clickedButton() is yes


def posted(parent, message, doc_type=None, doc_id=None,
           editing=False, **print_kw):
    """يؤكّد الترحيل ثم يعرض خيار الطباعة/المعاينة.

    تُستدعى بعد كل عملية ترحيل (بيع · مرتجع · قبض · صرف · توريد ·
    صب · تسكير · قيد يومي · مشتريات) فتوحّد التجربة: رسالة تأكيد
    واضحة، ثم سؤال عن الطباعة بدل البحث عن المستند لاحقاً.
    """
    box = QtWidgets.QMessageBox(parent)
    box.setWindowTitle("تم الترحيل")
    box.setIcon(QtWidgets.QMessageBox.Information)
    box.setText(message)
    if not (doc_type and doc_id):
        box.setStandardButtons(QtWidgets.QMessageBox.Ok)
        box.exec_()
        return None
    # ══ التعديل لا يعرض خيار الطباعة ══
    # التعديل تصحيح لعملية مطبوعة سابقاً، وعرض مربع الطباعة بعده
    # يستورد وحدة الطباعة ويفتح المتصفح — فيبطئ ما يجب أن يكون
    # فورياً. رسالة نجاح مباشرة أوضح وأسرع.
    if editing:
        box = QtWidgets.QMessageBox(parent)
        box.setWindowTitle("تم")
        box.setIcon(QtWidgets.QMessageBox.Information)
        box.setText(message)
        box.setStandardButtons(QtWidgets.QMessageBox.Ok)
        box.exec_()
        return "ok"

    # نضمن جاهزية وحدة الطباعة **قبل** عرض المربع، بمهلة قصيرة
    # فلا يتجمّد النظام إن لم تكتمل بعد.
    try:
        from services import preload
        preload.ensure(timeout=0.2)
    except Exception:
        pass
    box.setInformativeText("هل تريد طباعة المستند أو معاينته؟")
    b_prev = box.addButton("👁 معاينة وطباعة",
                           QtWidgets.QMessageBox.AcceptRole)
    b_print = box.addButton("🖨 طباعة مباشرة",
                            QtWidgets.QMessageBox.ActionRole)
    box.addButton("لاحقاً", QtWidgets.QMessageBox.RejectRole)
    box.exec_()
    clicked = box.clickedButton()
    try:
        from services import print_manager
        if clicked is b_prev:
            # المعاينة مؤجَّلة لدورة أحداث لاحقة: يُغلق مربع الحوار
            # أولاً فيرى المستخدم أن العملية تمّت، ثم يُفتح المستند.
            QtCore.QTimer.singleShot(
                0, lambda: print_manager.preview_document(
                    parent, doc_type, doc_id, **print_kw))
            return "preview"
        if clicked is b_print:
            print_manager.print_document(parent, doc_type, doc_id,
                                         **print_kw)
            return "print"
    except Exception as e:
        err(parent, f"تعذّرت الطباعة: {e}")
    return None


def show_model_image(parent, model_no):
    """يعرض صورة الموديل في نافذة — من أي شاشة.

    الصورة **وصفية بحتة** بلا أثر محاسبي. كانت متاحة من شاشة دليل
    الموديلات وحدها، فمن يبيع أو يرتجع لا يرى شكل الموديل إلا بترك
    شاشته والبحث فيه. هذه الدالة تجعل العرض متاحاً حيثما ظهر رقم
    الموديل، بتطبيق واحد لا بنسختين تتباعدان.
    """
    from PyQt5 import QtGui
    from models import models_catalog as mc

    no = (str(model_no or "").strip().lstrip("🖼").strip())
    if not no or no == "—":
        raise ValueError("لا يوجد رقم موديل لهذا السطر")
    p = mc.image_path(no)
    if p is None:
        raise ValueError(
            f"لا توجد صورة محفوظة للموديل {no}.\n\n"
            "تُضاف الصور من شاشة «دليل الموديلات».")
    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle(f"صورة الموديل {no}")
    lbl = QtWidgets.QLabel()
    pix = QtGui.QPixmap(str(p))
    try:
        if pix.width() > 900 or pix.height() > 700:
            pix = pix.scaled(900, 700, QtCore.Qt.KeepAspectRatio,
                             QtCore.Qt.SmoothTransformation)
    except Exception:
        pass
    lbl.setPixmap(pix)
    lbl.setAlignment(QtCore.Qt.AlignCenter)
    btn = QtWidgets.QPushButton("إغلاق")
    btn.clicked.connect(dlg.accept)
    lay = QtWidgets.QVBoxLayout(dlg)
    lay.addWidget(lbl, 1)
    lay.addWidget(btn)
    dlg.exec_()
    return True


def has_model_image(model_no):
    """هل للموديل صورة محفوظة؟ — لوسم الخلية القابلة للنقر."""
    try:
        from models import models_catalog as mc
        no = str(model_no or "").strip()
        return bool(no and no != "—" and mc.image_path(no) is not None)
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════
#  تفضيلات العرض — تُحفظ في قاعدة بيانات المصنع نفسها
# ------------------------------------------------------------------
#  تُخزَّن في `app_settings` لا في ملف على الجهاز: فالتفضيل يتبع بيانات
#  المصنع أينما فُتحت، ويبقى بعد إعادة بناء التطبيق (وهو ما يجري هنا
#  كل تحديث). وهي تفضيلات **عرض** محضة لا تمسّ قيداً.
# ══════════════════════════════════════════════════════════════════

def load_pref(key, default=""):
    """يقرأ تفضيل عرض. لا يُفشل الشاشة أبداً — يعود بالافتراضي."""
    try:
        from database.database import db
        from models import fiscal
        with db(readonly=True) as conn:
            return fiscal.get_setting(conn, key, default) or default
    except Exception:
        return default


def save_pref(key, value, username=None):
    """يحفظ تفضيل عرض. الفشل لا يمنع المستخدم من متابعة عمله."""
    try:
        from database.database import db
        from models import fiscal
        with db() as conn:
            fiscal.set_setting(conn, key, value, username)
        return True
    except Exception:
        return False


def karat_combo(pref_key=None, width=112):
    """قائمة اختيار العيار (18 · 21 · 22 · 24).

    القيد كله بمكافئ عيار 18 — وهذا لا يتغيّر. لكن العميل قد يُحوَّل
    حسابه إلى 21 أو 22 أو 24، فيريد قراءة الكشف نفسه بعياره. الاختيار
    **عرضٌ محض**: نفس الأرقام مقسومة على العيار، والقيد لا يُمسّ.

    `pref_key` يجعل آخر اختيار يُحفظ فيُستعاد عند العودة للشاشة.
    """
    cb = QtWidgets.QComboBox()
    cb.setMaximumWidth(width)
    cb.setToolTip("عيار عرض الأوزان — القيد يبقى بمكافئ عيار 18")
    for k in (18, 21, 22, 24):
        cb.addItem(f"عيار {k}", k)
    # بلا مفتاح تفضيل: يتبع عيار المصنع المختار من الشريط العلوي،
    # ويبقى تغييره هنا معاينةً مؤقتة لهذه الشاشة وحدها.
    default = 18
    if pref_key:
        try:
            default = int(str(load_pref(pref_key, "18")).strip() or 18)
        except (TypeError, ValueError):
            default = 18
    else:
        try:
            from services import karat_view
            default = karat_view.active()
        except Exception:
            default = 18
    idx = cb.findData(default)
    if idx >= 0:
        cb.setCurrentIndex(idx)
    return cb
