# -*- coding: utf-8 -*-
"""مكونات واجهة مشتركة: حقول أوزان/مبالغ، جداول، رسائل، مربعات اختيار."""
import contextlib
import time

from PyQt5 import QtCore, QtGui, QtWidgets


class Card(QtWidgets.QFrame):
    """بطاقة إحصائية قابلة للنقر (للوحة التحكم التفاعلية) — تصدر clicked
    عند الضغط لفتح دفتر الأستاذ العام مفلتراً على حساب البطاقة."""
    clicked = QtCore.pyqtSignal()

    def __init__(self, title, subtitle_hint="", summary=False):
        """`summary=True` للوحة الخلاصة — الرصيد وحده.

        بين ستّ لوحاتٍ متشابهة يضيع الرصيد، وهو الرقم الذي فُتحت
        الشاشة لأجله. فيُعطى نبرةً كهرمانيةً خافتة تلتقطها العين
        أولاً، من عائلة الألوان نفسها فلا تبدو دخيلة.
        """
        super().__init__()
        self.setObjectName("cardSum" if summary else "card")
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


class ElidedLabel(QtWidgets.QLabel):
    """ملصق يقصّ نصّه بثلاث نقاط بدل أن يفرض عرضه على النافذة.

    **لماذا**: `QLabel` يطلب عرضاً بطول نصّه كاملاً، ولا يقبل أقلّ
    منه. فاسم مصنع طويل في الشريط العلوي كان يجعل أدنى عرضٍ للنافذة
    أكبر من الشاشة — فتُفتح النافذة متمدّدة أفقياً ويضطر المستخدم
    لتصغيرها بعد كل فتح.

    هنا: أدنى عرض صغير ثابت، والنص يُقصّ في العرض المتاح، وكامله في
    التلميح. فالشريط يضيق ويتّسع مع النافذة بلا أن يفرض عليها شيئاً.
    """

    def __init__(self, text="", minimum=90, parent=None):
        super().__init__(text, parent)
        self._full = text
        self._min = int(minimum)
        self.setToolTip(text)
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred,
                           QtWidgets.QSizePolicy.Preferred)

    def setText(self, text):
        self._full = text or ""
        self.setToolTip(self._full)
        super().setText(self._full)

    def minimumSizeHint(self):
        sh = super().minimumSizeHint()
        return QtCore.QSize(min(self._min, sh.width()), sh.height())

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        fm = QtGui.QFontMetrics(self.font())
        txt = fm.elidedText(self._full, QtCore.Qt.ElideRight,
                            max(10, self.width() - 2))
        painter.drawText(self.rect(), int(self.alignment()), txt)


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
    # النسخ والتصدير في كل جدول بلا استثناء (الزر الأيمن): حاجةٌ
    # يوميّة لا ميزةَ تقرير. والفرز بالنقر يُطلب صراحةً في شاشات
    # العرض وحدها — شرحه في `table_tools.attach_sorter`.
    try:
        from ui.widgets.table_tools import attach_menu
        attach_menu(t)
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


def tab_widget():
    """تبويباتٌ تُظهر عناوينها كاملة.

    **الخلل**: Qt يقصّ عنوان التبويب حين يحسب عرضاً أضيق مما يلزم —
    وفي الواجهة العربية يقصّه من طرفيه معاً، فيصير «جسر الرصيد»
    «تسر الرصيـ» ولا يُفهم. فيُمنع القصّ صراحةً وتُمنع أزرار التمرير،
    ويُترك للتبويب عرضه الطبيعي.
    """
    t = QtWidgets.QTabWidget()
    try:
        bar = t.tabBar()
        bar.setElideMode(QtCore.Qt.ElideNone)
        bar.setUsesScrollButtons(False)
        bar.setExpanding(False)
    except Exception:
        pass
    return t


def row_height(table, lines=1, tight=False):
    """ارتفاع صفٍّ مريحٌ مشتقٌّ من قياس الخط لا من رقمٍ ثابت.

    الرقم الثابت يصلح لجهازٍ واحد: يكبر خطُّ النظام أو تدقّ الشاشة
    فيُقصّ النصّ في صفٍّ ضيق، أو يتباعد في صفٍّ فارغ. والاشتقاق من
    `lineSpacing` يجعل النسبة بين الخط والصف واحدةً على أي جهاز.

    `tight` للجداول الكبيرة: حشوٌ أقلّ فيظهر منها أكثر في الشاشة
    نفسها، ويبقى النصّ كاملاً غير مقصوص.
    """
    fm = QtGui.QFontMetrics(table.font())
    line = max(16, fm.lineSpacing())
    pad = 10 if tight else 14
    return int(max(lines, 1) * line + pad)


def row_action_buttons(table, count, on_edit=None, on_delete=None,
                       col=0, skip=(), edit_tip="تعديل هذا السطر",
                       del_tip="حذف هذا السطر"):
    """زرّا «تعديل» و«حذف» في أول عمودٍ من الجدول — لكل صفٍّ زرّاه.

    **لماذا في الصف لا تحته**: الأزرار أسفل الجدول تعمل على «السطر
    المحدد»، فتحتاج نقرتين ونيّةً صحيحة: يحدّد المستخدم سطراً ثم
    يضغط الزر، وإن سها عن التحديد عدّل غير ما أراد. والزرّ في صفّه
    لا يُخطئ صاحبه أبداً — نقرةٌ واحدة على السطر المقصود بعينه.

    `skip` لصفوف لا تُعدَّل ولا تُحذف (صفّ الإجمالي مثلاً)، فيبقى
    عمودها فارغاً.
    """
    for r in range(count):
        if r in skip:
            continue
        box = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(box)
        h.setContentsMargins(2, 0, 2, 0)
        h.setSpacing(3)
        if on_edit is not None:
            b = QtWidgets.QToolButton()
            b.setObjectName("rowAct")
            b.setText("✎")
            b.setToolTip(edit_tip)
            b.setCursor(QtCore.Qt.PointingHandCursor)
            # `r=r` يثبّت رقم الصف لحظة الإنشاء: بدونه تقرأ كل
            # الأزرار آخر قيمةٍ للمتغيّر فتعدّل جميعها السطر الأخير.
            b.clicked.connect(lambda _=False, i=r: on_edit(i))
            h.addWidget(b)
        if on_delete is not None:
            d = QtWidgets.QToolButton()
            d.setObjectName("rowDel")
            d.setText("✕")
            d.setToolTip(del_tip)
            d.setCursor(QtCore.Qt.PointingHandCursor)
            d.clicked.connect(lambda _=False, i=r: on_delete(i))
            h.addWidget(d)
        h.addStretch(1)
        table.setCellWidget(r, col, box)


def fill(table, headers, rows):
    """يملأ الجدول دفعةً واحدة — بلا قياس مكلف على الجداول الكبيرة.

    **الخلل السابق**: `resizeColumnsToContents()` يقيس كل خلية في كل
    عمود، و`resizeRowsToContents()` مع لفّ النص يقيس كل صف — على 600
    صف يعني مئات آلاف القياسات، فيتجمّد النظام دقائق.

    الآن: التحديث مُعطَّل أثناء الملء، والقياس المكلف يُستبدل بتوزيع
    نسبي حسابي لا يقرأ المحتوى.

    **وارتفاع الصف واحدٌ دائماً** — لا للجداول الكبيرة وحدها كما كان.
    الشكوى: «الجدول غير مرتب: صفٌّ واسع وصفٌّ قصير وصفٌّ كبير». وسببها
    أن ارتفاع الصف كان تابعاً لمحتواه، فصفٌّ بيانه سطرٌ يبقى قصيراً
    وصفٌّ بيانه طويل يُلفّ على ثلاثة أسطر فيعلو ثلاثة أضعاف — فيخرج
    الكشف مموّجاً لا تتتبّع العين سطراً فيه. والكشف المحاسبي سطرٌ
    واحد لكل حركة بارتفاع واحد؛ وما طال يُقصّ ويبقى كاملاً في التلميح.
    """
    big = len(rows) > BIG_TABLE
    try:
        table.setUpdatesEnabled(False)
        table.setSortingEnabled(False)
        table.setWordWrap(False)
        table.setTextElideMode(QtCore.Qt.ElideRight)
        vh = table.verticalHeader()
        vh.setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
        # الارتفاع من قياس الخط لا برقمٍ ثابت: يكبر مع تكبير خط
        # النظام ومع دقّة الشاشة، فلا يُقصّ النصّ على جهازٍ ولا يتباعد
        # على آخر. والجداول الكبيرة أضيق قليلاً فيظهر منها أكثر.
        vh.setDefaultSectionSize(row_height(table, tight=big))
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                if isinstance(val, float):
                    val = (f"{val:,.2f}".rstrip("0").rstrip(".")
                           if abs(val) < 1e12 else str(val))
                txt = "" if val is None else str(val)
                item = QtWidgets.QTableWidgetItem(txt)
                # النصّ الكامل في التلميح: القصّ لا يُخفي شيئاً
                if len(txt) > 14:
                    item.setToolTip(txt)
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

@contextlib.contextmanager
def bulk_rows(table, n_rows, headers=None):
    """يهيّئ جدولاً لملءٍ يدويٍّ سريع، ثم يعيده إلى هيئته.

    **الخلل الذي وُجد لأجله**: `make_table` يفعّل لفّ النص ويجعل ارتفاع
    الصف تابعاً لمحتواه. فكل `setItem` يُعيد قياس الصف كله، وقياس صفٍّ
    يُعيد حساب الأعمدة — فتصير كلفة الخلية الواحدة ثابتةً باهظة (قيست
    ١٢.٦ مللي ثانية للخلية الواحدة). على ٣٧٨ صفاً وثمانية أعمدة صار
    فتح **أرشيف المستندات** ثلاثين ثانية: الواجهة لا تعالج أحداثها،
    فيرسمها ويندوز سوداءَ ويعلن «لا يستجيب» — وهي الشكوى بعينها.

    `fill()` يتفادى هذا داخلياً، لكن كل شاشةٍ تملأ جدولها بيدها (لأنها
    تضع أزراراً في الصفوف أو تلوّن خلاياها) كانت تدفع الثمن كاملاً.
    فهذا هو المخرج المشترك:

        with bulk_rows(self.table, len(rows), COLS):
            for i, r in enumerate(rows):
                ...  self.table.setItem(i, c, it)

    ولا يُستعمل `insertRow` داخله: عدد الصفوف يُضبط مرةً واحدة.
    """
    vh = table.verticalHeader()
    big = n_rows > BIG_TABLE
    try:
        table.setUpdatesEnabled(False)
        table.setSortingEnabled(False)
        # ارتفاعٌ واحد دائماً — لا للكبيرة وحدها: الجدول المموّج
        # (صفٌّ واسع وصفٌّ قصير) لا تتتبّعه العين مهما قلّت صفوفه.
        table.setWordWrap(False)
        table.setTextElideMode(QtCore.Qt.ElideRight)
        vh.setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
        vh.setDefaultSectionSize(row_height(table, tight=big))
        if headers:
            table.setColumnCount(len(headers))
            table.setHorizontalHeaderLabels(list(headers))
        table.setRowCount(0)
        table.setRowCount(n_rows)
        yield table
    finally:
        try:
            table.setUpdatesEnabled(True)
        except Exception:
            pass
        # توزيعٌ حسابي لا يقرأ محتوى الخلايا — بديل
        # `resizeColumnsToContents` الذي يقيس كل خلية (وكل widget فيها)
        try:
            from ui.widgets.table_fit import fit_columns
            fit_columns(table)
        except Exception:
            pass


def ledger_rows(table, height=38, wrap_cols=(), max_lines=2):
    """صفوفٌ متساوية الارتفاع — هيئة الكشف المحاسبي.

    **الشكوى**: «الجدول يظهر غير مرتب: صفٌّ واسع وصفٌّ قصير وصفٌّ
    كبير». وسببها أن `make_table` يفعّل لفّ النص ويجعل ارتفاع الصف
    تابعاً لمحتواه: صفٌّ بيانه سطرٌ واحد يبقى قصيراً، وصفٌّ بيانه
    طويل يُلفّ على ثلاثة أسطر فيعلو ثلاثة أضعاف. فيخرج الكشف مموّجاً
    لا تستطيع العين تتبّع سطرٍ فيه بالمسطرة — وهو أول ما يحتاجه من
    يراجع كشف حساب.

    الكشف المحاسبي سطرٌ واحد لكل حركة، بارتفاع واحد.

    **وارتفاعٌ يكفي المحتوى**: قصُّ اسم الحساب على كلمتين يُفقده
    تمييزه — «خزينة التصنيع…» لا تقول أيّ خزينة. فيُقاس أطولُ اسمٍ
    في العمود مرةً واحدة: إن احتاج سطرين رُفع **كل** الصفوف إلى
    سطرين. فالاسم يظهر كاملاً والجدول يبقى منتظماً — لا هذا على حساب
    ذاك. وسطران حدٌّ أقصى: ما جاوزهما يُقصّ ويبقى في التلميح، وإلا
    صار الصفُّ فقرة.

    الارتفاع يُشتقّ من قياس الخط لا برقمٍ ثابت، فيكبر مع تكبير خط
    النظام ومع دقّة الشاشة بلا ضبطٍ يدوي.

    `wrap_cols` أعمدة النصّ الطويل (الجهة · البيان). بلا تمريرها
    يبقى السطر واحداً كما كان.
    """
    fm = QtGui.QFontMetrics(table.font())
    line = max(16, fm.lineSpacing())
    need = 1
    if wrap_cols:
        # أطولُ نصٍّ في الأعمدة المطلوبة — بعدد الحروف، فالقياس
        # الحقيقي يجري مرةً واحدة على أطولها لا على كل خلية.
        longest, col_w = "", {}
        for c in wrap_cols:
            col_w[c] = max(60, table.columnWidth(c) - 14)
        pick = None
        for r in range(min(table.rowCount(), 400)):
            for c in wrap_cols:
                it = table.item(r, c)
                t = it.text() if it else ""
                if len(t) > len(longest):
                    longest, pick = t, c
        if longest and pick is not None:
            h = fm.boundingRect(0, 0, col_w[pick], 0,
                                QtCore.Qt.TextWordWrap, longest).height()
            need = max(1, min(int(max_lines), -(-h // line)))
    table.setWordWrap(need > 1)
    table.setTextElideMode(QtCore.Qt.ElideRight)
    vh = table.verticalHeader()
    vh.setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
    vh.setDefaultSectionSize(max(int(height), row_height(table, need)))


def num_item(text, tip=None):
    """خلية رقم: محاذاةٌ لليمين فتصطفّ الآحاد تحت الآحاد.

    الأرقام الموسَّطة تتراقص يميناً ويساراً بطول الرقم، فلا تُقارَن
    خانةٌ بخانة. ومحاذاتها لليمين هي عُرف كل كشف حساب.
    """
    it = QtWidgets.QTableWidgetItem(str(text))
    # `AlignAbsolute` ضرورية: بدونها يقلب Qt معنى «اليمين» في الواجهة
    # العربية فتلتصق الأرقام بالحافة اليسرى — وهو عكس المقصود تماماً.
    it.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignAbsolute
                        | QtCore.Qt.AlignVCenter)
    if tip:
        it.setToolTip(str(tip))
    return it


def text_item(text, align=QtCore.Qt.AlignRight, tip=None):
    """خلية نصّ: محاذاةٌ واحدة، والنصّ الكامل في التلميح إن قُصّ."""
    it = QtWidgets.QTableWidgetItem(str(text))
    it.setTextAlignment(align | QtCore.Qt.AlignVCenter)
    it.setToolTip(str(tip if tip is not None else text))
    return it


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
        self.setMinimumWidth(200)
        # ══ العرض لا يتبع أطول عنصر ══
        # السياسة الافتراضية (AdjustToContentsOnFirstShow) تجعل عرض
        # القائمة بعرض أطول اسم فيها. وقوائم الحسابات تحوي أسماءً
        # طويلة («1602 — عميل: مؤسسة الشرق الأوسط للمجوهرات…»)، فتتمدّد
        # القائمة ويتمدّد معها الشريط ثم النافذة كلها أفقياً — وهو سبب
        # اتساع النظام عند فتح الشاشات. العرض الآن ثابت والنص الطويل
        # يُقصّ في العرض وحده بلا أي تأثير على الاختيار.
        self.setSizeAdjustPolicy(
            QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        try:
            self.setMinimumContentsLength(16)
            self.view().setTextElideMode(QtCore.Qt.ElideRight)
        except Exception:
            pass
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
                # ══ النصّ كلّه محدَّد ⇒ المؤشر على الطرف ══
                # الانتقال إلى خانةٍ يحدّد محتواها كلّه (ليُكتب فوقه
                # مباشرة)، وموضع المؤشر حينها يختلف بين حقلٍ وآخر —
                # فكان السهم يبدو معطَّلاً في أول ضغطةٍ بعد الانتقال
                # ويعمل بعد الثانية. والتحديد الكامل يعني أن لا نصّ
                # يُتنقَّل داخله أصلاً، فالسهم للانتقال بين الخانات.
                sel = (le.selectedText() or "") if hasattr(
                    le, "selectedText") else ""
                if not (length and sel == (le.text() or "")):
                    if key == QtCore.Qt.Key_Left and pos < length:
                        return False      # ما زال داخل النص
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
    # تنبيه حدّ الائتمان يظهر مع رسالة الترحيل نفسها — لا في شاشة
    # أخرى ولا بعد أسابيع. الموضع واحد لكل الشاشات لأنها كلها تمرّ
    # من هنا بعد الترحيل. (وكان معه تنبيه الرصيد السالب فأُلغي.)
    warns = []
    for mod in ("credit_guard",):
        try:
            m = __import__(f"services.{mod}", fromlist=["x"])
            t = m.take_warning()
            if t:
                warns.append(t)
        except Exception:
            pass
    warn_txt = "\n\n".join(warns)
    if warn_txt:
        message = f"{message}\n\n{warn_txt}"

    box = QtWidgets.QMessageBox(parent)
    box.setWindowTitle("تم الترحيل")
    box.setIcon(QtWidgets.QMessageBox.Warning if warn_txt
                else QtWidgets.QMessageBox.Information)
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


# ══════════════════════════════════════════════════════════════════
#  مؤشر الانشغال ورصد البطء
# ══════════════════════════════════════════════════════════════════

SLOW_SECONDS = 1.5


@contextlib.contextmanager
def busy(parent=None, text="جارٍ التنفيذ…", stage="", slow=SLOW_SECONDS):
    """يُظهر انشغال النظام أثناء عملية قد تطول، ويسجّل بطأها.

    **المشكلة**: عملية تستغرق ثانيتين على خيط الواجهة تجعل ويندوز
    يعلن «لا يستجيب» ويرسم النافذة سوداء — فيظن المستخدم أن النظام
    تعطّل، وقد يضغط ثانيةً فيكرّر العملية.

    هنا ثلاثة أشياء معاً:
    · مؤشر الانتظار يظهر فوراً، ودورة رسم واحدة قبل العمل حتى تُرسم
      النافذة كاملةً بدل أن تُترك سوداء.
    · النافذة تُعطَّل أثناء العمل فلا يُقبل ضغطٌ مكرّر ينتج عملية
      ثانية.
    · ما تجاوز الحد يُسجَّل في `system_errors.log` باسم مرحلته وزمنها
      — فالشكوى تصير دليلاً يُقرأ بدل تخمين.
    """
    app = QtWidgets.QApplication.instance()
    t0 = time.time()
    try:
        if app is not None:
            app.setOverrideCursor(QtGui.QCursor(QtCore.Qt.WaitCursor))
            app.processEvents()
        if parent is not None:
            try:
                parent.setEnabled(False)
                app and app.processEvents()
            except Exception:
                pass
        yield
    finally:
        if parent is not None:
            try:
                parent.setEnabled(True)
            except Exception:
                pass
        if app is not None:
            try:
                app.restoreOverrideCursor()
            except Exception:
                pass
        took = time.time() - t0
        if took > slow:
            try:
                from services import health
                health.log_slow(stage or text, took)
            except Exception:
                pass


def run_bg(fn, parent=None, text="جارٍ التنفيذ…", stage="", timeout=None,
           slow=SLOW_SECONDS):
    """ينفّذ عملاً بطيئاً في خيطٍ جانبي **والواجهة حيّة**.

    **الفرق عن `busy`**: `busy` يُظهر مؤشر انتظارٍ ثم ينفّذ العمل على
    خيط الواجهة نفسه. فما دام العمل جارياً لا تعالج الواجهة حدثاً
    واحداً: لا تُرسم النافذة فتبقى سوداء، ويُعلن ويندوز «لا يستجيب».
    مقبولٌ لاستعلامٍ في جزء من ثانية، وغيرُ مقبولٍ لنداء **شبكة**:
    رفعُ صفحة فاتورة قد يستغرق عشر ثوانٍ على اتصالٍ بطيء — وهي عشر
    ثوانٍ يرى فيها المستخدم شاشةً سوداء بعد كل ترحيل.

    هنا يجري العمل في خيطٍ جانبي، وتُدار حلقةُ الأحداث أثناءه فتُرسم
    النافذة ويبقى النظام حيّاً. وتُستبعَد أحداث **إدخال المستخدم**
    من الحلقة: الضغط أثناء العمل لا يُنفَّذ ولا يُصطفّ ليُنفَّذ بعده
    على شاشةٍ تغيّرت — وهو ما يُشتكى منه بـ«نقرتُ في مكان خاطئ».

    تُرجع `(تمّ, النتيجة, الخطأ)`. و`timeout` سقفُ الانتظار: بعده
    يُترك العمل يُكمل في الخلفية وتعود الدالة بـ`تمّ=False` — فلا
    يُحبس المستخدم خلف شبكةٍ لا تستجيب.

    ملاحظة: `fn` يعمل على خيطٍ آخر، فلا يلمس أي widget. اتصال قاعدة
    البيانات محليٌّ لكل خيط (`database.db`) فالكتابة منه سليمة.
    """
    import threading
    box = {"done": False, "res": None, "err": None}

    def work():
        try:
            box["res"] = fn()
        except Exception as e:                  # الخطأ يُنقل لا يُبتلع
            box["err"] = e
        finally:
            box["done"] = True

    app = QtWidgets.QApplication.instance()
    t0 = time.time()
    th = threading.Thread(target=work, daemon=True, name="run_bg")
    th.start()
    if app is None:                             # بلا واجهة (أدوات الفحص)
        th.join(timeout)
        return box["done"], box["res"], box["err"]

    app.setOverrideCursor(QtGui.QCursor(QtCore.Qt.WaitCursor))
    if parent is not None:
        try:
            parent.setEnabled(False)
        except Exception:
            pass
    try:
        while not box["done"]:
            if timeout is not None and time.time() - t0 > timeout:
                break
            # بلا أحداث إدخال: الواجهة تُرسم ولا يُنفَّذ ضغطٌ عارض
            app.processEvents(QtCore.QEventLoop.ExcludeUserInputEvents, 40)
            th.join(0.02)
    finally:
        if parent is not None:
            try:
                parent.setEnabled(True)
            except Exception:
                pass
        try:
            app.restoreOverrideCursor()
        except Exception:
            pass
        took = time.time() - t0
        if took > slow:
            try:
                from services import health
                health.log_slow(stage or text, took)
            except Exception:
                pass
    return box["done"], box["res"], box["err"]
