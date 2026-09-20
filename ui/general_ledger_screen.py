# -*- coding: utf-8 -*-
"""دفتر الأستاذ العام / كشف الحساب الشامل — أي حساب من شجرة الحسابات
كاملة (عميل، خزينة تصنيع، مشغول، بنك، فاقد، مصروف رواتب...) بنفس
الأعمدة الثمانية المزدوجة (ذهب/نقد) بغض النظر عن طبيعة الحساب."""
from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from models import entities, journal
from models.accounts import list_postable
from services.audit import soft_delete_entry

from services import browser_print, gold_math, karat_view as kv
from ui.widgets.table_fit import fit_columns
from ui.widgets.common import (Card, ask, big_label, date_edit, dstr, err,
                               fill, info, karat_combo, ledger_rows,
                               make_table, num_item, search_combo, text_item,
                               title_label)

from models.editing import EDITABLE


class GeneralLedgerScreen(QtWidgets.QWidget):
    def __init__(self, user, on_edit_doc=None):
        super().__init__()
        self.user = user
        self._col_weights = []
        self.on_edit_doc = on_edit_doc
        self.accounts = []
        self.rows = []

        self.account = search_combo("اكتب رقم الحساب أو اسمه…")
        # عرض **ثابت**: القائمة لا تتمدد بطول اسم الحساب فتدفع الأزرار
        # وحقول التواريخ خارج الشاشة.
        self.account.setMinimumWidth(300)
        self.account.setMaximumWidth(340)
        self.account.setSizePolicy(QtWidgets.QSizePolicy.Fixed,
                                   QtWidgets.QSizePolicy.Fixed)
        self.account.setSizeAdjustPolicy(
            QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        try:
            # النص الطويل يُقصّ في العرض ولا يوسّع العنصر
            self.account.view().setTextElideMode(QtCore.Qt.ElideRight)
        except Exception:
            pass
        self.d_from = date_edit()
        self.d_from.setDate(QtCore.QDate(QtCore.QDate.currentDate().year(), 1, 1))
        self.d_to = date_edit()
        # مرشّح نوع العملية: يعرض حركة الحساب من نوع بعينه
        self.op_kind = QtWidgets.QComboBox()
        self.op_kind.setMaximumWidth(130)
        for label, val in (("كل العمليات", ""), ("سند قبض", "قبض"),
                           ("سند صرف", "صرف"), ("مبيعات", "مبيعات"),
                           ("مرتجع", "مرتجع"), ("توريد", "توريد"),
                           ("تسوية", "تسوية"), ("قيد يومي", "قيد يومي"),
                           ("تسكير", "تسكير"), ("صب وتصفية", "صب"),
                           ("مشتريات", "مشتريات")):
            self.op_kind.addItem(label, val)
        # العيارات: يعرض الكشف نفسه بالعيار المختار (عرضٌ محض)
        self.karat = karat_combo()
        self.karat.currentIndexChanged.connect(self._karat_changed)
        btn = QtWidgets.QPushButton("عرض")
        btn.clicked.connect(self.load)
        # ست بطاقات: مدين · دائن · الرصيد — للذهب والنقد
        self.g_debit = Card("إجمالي المدين — ذهب", f"جم {kv.label()}")
        self.g_credit = Card("إجمالي الدائن — ذهب", f"جم {kv.label()}")
        self.g_bal = Card("رصيد الذهب", "", summary=True)
        self.c_debit = Card("إجمالي المدين — نقد", "ريال")
        self.c_credit = Card("إجمالي الدائن — نقد", "ريال")
        self.c_bal = Card("الرصيد النقدي", "", summary=True)
        self.summary = big_label()
        self.summary.setVisible(False)
        self.table = make_table()
        # المعاينة بالنقر المزدوج بدل زر في كل صف (أسرع بكثير)
        self.table.doubleClicked.connect(lambda *_: self.preview_selected())

        # شريط أدوات ثابت: الأزرار والتواريخ لا تخرج من الشاشة مهما
        # طال اسم الحساب — المساحة الفائضة تذهب لفراغ في النهاية.
        head = QtWidgets.QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(QtWidgets.QLabel("الحساب:"))
        head.addWidget(self.account, 0)
        head.addWidget(QtWidgets.QLabel("من:"))
        head.addWidget(self.d_from, 0)
        head.addWidget(QtWidgets.QLabel("إلى:"))
        head.addWidget(self.d_to, 0)
        head.addWidget(QtWidgets.QLabel("العملية:"))
        head.addWidget(self.op_kind, 0)
        head.addWidget(QtWidgets.QLabel("العيارات:"))
        head.addWidget(self.karat, 0)
        head.addWidget(btn, 0)
        head.addStretch(1)

        lay = QtWidgets.QVBoxLayout(self)
        # واجهة مضغوطة: حشو وتباعد أقل فيتسع المحتوى على أي شاشة
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        lay.addWidget(title_label(
            "دفتر الأستاذ العام — أي حساب من الشجرة، ميزان الذهب وميزان "
            "النقد معاً"))
        lay.addLayout(head)
        btn_edit = QtWidgets.QPushButton("✎ تعديل")
        btn_edit.clicked.connect(self.edit_doc)
        btn_move = QtWidgets.QPushButton("⇄ نقل لحساب آخر")
        btn_move.setToolTip(
            "ينقل العملية لجهة أخرى بنفس التاريخ والرقم والمبالغ")
        btn_move.clicked.connect(self.transfer_doc)
        btn_del = QtWidgets.QPushButton("🗑 حذف وعكس")
        btn_del.setObjectName("danger")
        btn_del.clicked.connect(self.delete_doc)
        actions = QtWidgets.QHBoxLayout()
        btn_print = QtWidgets.QPushButton("👁 معاينة")
        btn_print.clicked.connect(self.print_statement)
        btn_direct = QtWidgets.QPushButton("🖨 طباعة")
        btn_direct.setToolTip(
            "يفتح نافذة طباعة النظام مباشرةً متجاوزاً شاشة المعاينة")
        btn_direct.clicked.connect(self.print_statement_direct)
        actions.addWidget(btn_edit)
        actions.addWidget(btn_move)
        actions.addWidget(btn_del)
        actions.addStretch(1)
        actions.addWidget(btn_print)
        actions.addWidget(btn_direct)
        actions.addStretch(1)
        actions.addWidget(self.summary)
        # شريط الإجماليات: ست بطاقات أسفل الجدول
        totals = QtWidgets.QHBoxLayout()
        totals.setSpacing(4)
        for _c in (self.g_debit, self.g_credit, self.g_bal,
                   self.c_debit, self.c_credit, self.c_bal):
            totals.addWidget(_c)

        lay.addWidget(self.table, 1)
        lay.addLayout(actions)

        lay.addLayout(totals)
        note = QtWidgets.QLabel(
            "التعديل يفتح الشاشة الأصلية معبّأة بالبيانات؛ عند الحفظ يُلغى "
            "أثر القيد القديم ويُرحَّل قيد جديد داخل معاملة واحدة. الحذف "
            "يعكس الأثر المالي والمخزني بالكامل.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)

    # ══════════════════════════════════════════════════════════════
    #  العيار: تحويل عرضٍ محض — القيد يبقى بمكافئ عيار 18
    # ══════════════════════════════════════════════════════════════

    def _sum_row(self, row, items):
        """يضع صف الختام ويُلبسه نبرة الخلاصة نفسها التي في لوحتَيها.

        اللون من `theme` لا رقمٌ مكتوب هنا: فيتبع الوضع الفاتح
        والداكن معاً بدل أن يصير في الداكن بقعةً بيضاء.
        """
        from ui import theme
        pal = theme.palette(theme.current_theme())
        bg = QtGui.QColor(pal.get("sumBg", "#FDF3E2"))
        ink = QtGui.QColor(pal.get("sumInk", "#7A4F10"))
        for c, it in enumerate(items):
            f = it.font()
            f.setBold(True)
            it.setFont(f)
            it.setBackground(bg)
            it.setForeground(ink)
            self.table.setItem(row, c, it)

    def _k(self):
        """العيار المختار حالياً (18 افتراضاً)."""
        try:
            return int(self.karat.currentData() or 18)
        except (TypeError, ValueError):
            return 18

    def _g(self, value):
        """يحوّل وزناً من مكافئ 18 إلى العيار المعروض."""
        return gold_math.from_base_karat(value or 0, self._k())

    def _karat_changed(self):
        """يعيد عرض الكشف بالعيار المختار فوراً.

        الشاشة تفتح على **عيار المصنع** المختار من الشريط العلوي،
        وهذه القائمة معاينة مؤقتة لهذا الكشف وحده — لقراءة حساب بعيار
        يختلف عن عيار المصنع دون تبديل النظام كله.
        """
        # لا نعيد الاستعلام إن لم يُعرض شيء بعد
        if self.account.currentData() is not None and self.table.rowCount():
            self.load()

    def open_for_code(self, account_code):
        """تُستدعى من لوحة التحكم عند الضغط على بطاقة — تفتح الكشف
        مفلتراً جاهزاً على حساب البطاقة."""
        idx = self.account.findData(account_code)
        if idx >= 0:
            self.account.setCurrentIndex(idx)
        self.load()

    def _preview_btn(self, r):
        from services import print_manager
        """زر «معاينة العملية» داخل كل صف من كشف الحساب: يلتقط نوع
        المستند ورقمه ويفتح المستند الأصلي (فاتورة/سند/قيد) الذي أنتج
        هذه الحركة، للمراجعة والتدقيق السريع."""
        src, sid = r.get("src"), r.get("sid")
        if src == "manual" or (src is None and r.get("eid")):
            src, sid = "manual", r.get("eid")
        if not src or not sid or src not in print_manager.BUILDERS:
            return None
        b = QtWidgets.QPushButton("👁")
        b.setObjectName("ghost")
        b.setToolTip("فتح المستند في المتصفح للمعاينة والطباعة")
        b.setMaximumWidth(40)
        b.clicked.connect(lambda _, s=src, i=sid: self._preview(s, i))
        return b

    def _preview(self, src, sid):
        from services import print_manager
        try:
                        print_manager.preview_document(self, src, sid)
        except Exception as e:
            err(self, e)

    def print_statement(self):
        from services import print_manager
        """معاينة/طباعة كشف الحساب كاملاً للحساب والفترة المعروضين."""
        try:
            code = self.account.currentData()
            if code is None:
                raise ValueError("اختر الحساب أولاً ثم اعرض الكشف")
            with db(readonly=True) as conn:
                acc = conn.execute("SELECT id FROM accounts WHERE code=?",
                                   (code,)).fetchone()
                if not acc:
                    raise ValueError("الحساب غير موجود")
            print_manager.preview_document(
                self, "statement", acc["id"],
                date_from=dstr(self.d_from),
                date_to=dstr(self.d_to),
                karat=self._k())
        except Exception as e:
            err(self, e)

    def print_statement_direct(self):
        from services import print_manager
        """طباعة كشف الحساب مباشرةً عبر نافذة طباعة النظام."""
        try:
            code = self.account.currentData()
            if code is None:
                raise ValueError("اختر الحساب أولاً ثم اعرض الكشف")
            with db(readonly=True) as conn:
                acc = conn.execute("SELECT id FROM accounts WHERE code=?",
                                   (code,)).fetchone()
                if not acc:
                    raise ValueError("الحساب غير موجود")
            print_manager.print_document(
                self, "statement", acc["id"],
                date_from=dstr(self.d_from),
                date_to=dstr(self.d_to),
                karat=self._k())
        except Exception as e:
            err(self, e)

    def load(self):
        try:
            code = self.account.currentData()
            if code is None:
                raise ValueError(
                    "اختر الحساب — أو اختر «★ كل الحسابات» لعرض عمليات "
                    "الفترة كلها")
            if code == journal.ALL_ACCOUNTS:
                return self._load_day_book()
            with db(readonly=True) as conn:
                acc = conn.execute("SELECT id FROM accounts WHERE code=?",
                                   (code,)).fetchone()
                if not acc:
                    raise ValueError("الحساب غير موجود")
                rows = journal.statement(
                    conn, acc["id"],
                    dstr(self.d_from),
                    dstr(self.d_to))
            # ترشيح بنوع العملية — مع إبقاء سطر الرصيد السابق دائماً
            kind = self.op_kind.currentData()
            if kind:
                rows = [r for r in rows
                        if r["op"] == "رصيد سابق" or kind in (r["op"] or "")]
                # إعادة حساب الأرصدة التراكمية للمعروض فقط
                gb = cb = 0.0
                for r in rows:
                    if r["op"] == "رصيد سابق":
                        gb, cb = r["gbal"], r["cbal"]
                        continue
                    gb = round(gb + (r["gd"] or 0) - (r["gc"] or 0), 3)
                    cb = round(cb + (r["cd"] or 0) - (r["cc"] or 0), 2)
                    r["gbal"], r["cbal"] = gb, cb
            self.rows = rows
            # عناوين مختصرة على سطرين — تُقلّص عرض الأعمدة فيظهر
            # الجدول كاملاً بلا تمرير أفقي.
            k = self._k()
            headers = ["التاريخ", "نوع\nالعملية", "رقم\nالسند",
                       "الجهة /\nالحساب المقابل", "البيان",
                       f"مدين\nذهب {k}", f"دائن\nذهب {k}",
                       f"رصيد\nذهب {k}",
                       "مدين\nنقد", "دائن\nنقد", "رصيد\nنقد", "معاينة"]
            self.table.setRowCount(0)
            self.table.setColumnCount(len(headers))
            self.table.setHorizontalHeaderLabels(headers)
            # توزيع العرض: البيان والجهة يأخذان الفائض، والأرقام ضيقة
            # مُحجِّم موحّد: يوزّع الأعمدة على العرض المتاح ويُعيد
            # الحساب تلقائياً مع أي تغيّر في حجم النافذة أو الشاشة.
            fit_columns(self.table, [
                8,    # التاريخ
                7,    # نوع العملية
                6,    # رقم السند
                19,   # الجهة / الحساب المقابل — اسمٌ كاملٌ لا كلمتان
                19,   # البيان
                6, 6, 7,      # مدين/دائن/رصيد ذهب
                6, 6, 7,      # مدين/دائن/رصيد نقد
                7,    # معاينة
            ])
            # ══ بناء الجدول دفعةً واحدة ══
            # **الخلل السابق**: زر معاينة QPushButton لكل صف — 500 صف
            # تعني 500 عنصر واجهة إضافي، وكل واحد يُنشئ تخطيطه وأنماطه
            # فيتجمّد النظام عند عرض حساب كثير الحركة.
            # الحل: عمود نصي بسيط، والمعاينة بالنقر المزدوج على الصف.
            # ══ صفُّ الإجمالي داخل الجدول ══
            # الإجماليات كانت في لوحاتٍ أسفل الشاشة وحدها، فمن طبع
            # الكشف أو صوّره لم يأخذ معه جُمَله. وصفُّ الختام في آخر
            # الجدول عُرفُ كل كشف حساب: يُقرأ مع آخر حركةٍ لا بعد
            # مسافة، ويُطبع معها.
            tgd_ = sum(float(r.get("gd") or 0) for r in rows
                       if r["op"] != "رصيد سابق")
            tgc_ = sum(float(r.get("gc") or 0) for r in rows
                       if r["op"] != "رصيد سابق")
            tcd_ = sum(float(r.get("cd") or 0) for r in rows
                       if r["op"] != "رصيد سابق")
            tcc_ = sum(float(r.get("cc") or 0) for r in rows
                       if r["op"] != "رصيد سابق")
            self.table.setUpdatesEnabled(False)
            self.table.setSortingEnabled(False)
            try:
                self.table.setRowCount(len(rows) + (1 if rows else 0))
                # ══ هيئة الكشف: سطرٌ لكل حركة، وارتفاعٌ واحد ══
                # التاريخ والنوع والمستند تُوسَّط (طولها ثابت)، والاسم
                # والبيان يُحاذَيان اليمين كالنصّ العربي، والأرقام
                # تُحاذى اليمين فتصطفّ الآحاد تحت الآحاد وتُقارَن
                # خانةٌ بخانة. وما طال يُقصّ ويبقى كاملاً في التلميح.
                _C = QtCore.Qt.AlignCenter
                for i, r in enumerate(rows):
                    cellv = [
                        text_item(r["date"], _C), text_item(r["op"], _C),
                        text_item(r["doc_no"], _C), text_item(r["name"]),
                        text_item(r["desc"]),
                        num_item(self._g(r["gd"]) if r["gd"] else ""),
                        num_item(self._g(r["gc"]) if r["gc"] else ""),
                        num_item(self._g(r["gbal"])),
                        num_item(r["cd"] or ""), num_item(r["cc"] or ""),
                        num_item(r["cbal"]),
                        text_item("👁" if (r.get("src") and r.get("sid"))
                                  else "", _C),
                    ]
                    for c, it in enumerate(cellv):
                        self.table.setItem(i, c, it)
                if rows:
                    last_g = rows[-1]["gbal"]
                    last_c = rows[-1]["cbal"]
                    tot = [
                        text_item("الإجمالي", _C), text_item("", _C),
                        text_item("", _C), text_item(""), text_item(""),
                        num_item(self._g(tgd_)), num_item(self._g(tgc_)),
                        num_item(self._g(last_g)),
                        num_item(f"{tcd_:,.2f}"), num_item(f"{tcc_:,.2f}"),
                        num_item(f"{last_c:,.2f}"), text_item("", _C),
                    ]
                    self._sum_row(len(rows), tot)
            finally:
                self.table.setUpdatesEnabled(True)
            # الجهة (٣) والبيان (٤): يتّسعان لسطرين إن لزم،
            # وكل الصفوف ترتفع معاً فيبقى الجدول منتظماً
            ledger_rows(self.table, wrap_cols=(3, 4))
            self.table.setHorizontalScrollBarPolicy(
                QtCore.Qt.ScrollBarAlwaysOff)
            fit_columns(self.table)
            if rows:
                g, c = rows[-1]["gbal"], rows[-1]["cbal"]
            else:
                g = c = 0.0
            # إجماليات الحركة خلال الفترة (بلا الرصيد السابق)
            tgd = sum(float(r.get("gd") or 0) for r in rows
                      if r["op"] != "رصيد سابق")
            tgc = sum(float(r.get("gc") or 0) for r in rows
                      if r["op"] != "رصيد سابق")
            tcd = sum(float(r.get("cd") or 0) for r in rows
                      if r["op"] != "رصيد سابق")
            tcc = sum(float(r.get("cc") or 0) for r in rows
                      if r["op"] != "رصيد سابق")
            self.g_debit.set_value(f"{self._g(tgd):,.2f}", f"جم عيار {k}")
            self.g_credit.set_value(f"{self._g(tgc):,.2f}", f"جم عيار {k}")
            self.g_bal.set_value(
                f"{abs(self._g(g)):,.2f}",
                f"{'مدين/عليه' if g >= 0 else 'دائن/له'} — عيار {k}")
            self.c_debit.set_value(f"{tcd:,.2f}")
            self.c_credit.set_value(f"{tcc:,.2f}")
            self.c_bal.set_value(
                f"{abs(c):,.2f}",
                "مدين/عليه" if c >= 0 else "دائن/له")
            # الجهة/الحساب المقابل (3) والبيان (4): يُلفّان على أسطر
            self._show_latest()
        except Exception as e:
            err(self, e)

    def _show_latest(self):
        """ينزل بالكشف إلى **آخر** العمليات عند العرض.

        الكشف مرتّب زمنياً تصاعدياً، فيفتح على أقدم حركة — وهي أبعد ما
        يُسأل عنه. المحاسب يريد آخر ما جرى على الحساب ورصيده الأخير،
        وهما في آخر الصفوف. فيُنزل الجدول إليها ويُحدَّد آخر صف.
        """
        try:
            n = self.table.rowCount()
            if n <= 0:
                return
            self.table.setCurrentCell(n - 1, 0)
            self.table.scrollToBottom()
        except Exception:
            pass          # التمرير رفاهية عرض لا تُفشل الكشف

    def _selected(self):
        r = self.table.currentRow()
        if r < 0 or r >= len(self.rows):
            return None
        row = self.rows[r]
        return row if row.get("eid") else None

    def edit_doc(self):
        row = self._selected()
        if not row:
            err(self, "اختر سطر مستند من الكشف أولاً")
            return
        src = row.get("src") or "manual"
        sid = row.get("sid")
        eid = row.get("eid")
        # لا يوجد سطر بلا قيد: إن غاب معرّف المستند المصدري نفتح القيد
        # نفسه — فيُعكس أثره القديم ويُرحَّل الجديد بنفس الآلية.
        if not sid:
            if not eid:
                err(self, "هذا السطر رصيد افتتاحي ولا يقبل التعديل.")
                return
            src, sid = "manual", eid
        # قيد تسوية وزن طقم يُفتح بحواره لا بشاشة التوريد
        if src == "work_orders" and (row.get("desc") or "").startswith(
                ("حذف رقم التشغيل", "زيادة في رقم التشغيل",
                 "تعديل وزن رقم التشغيل")):
            src = "wo_adjust"
        if src not in EDITABLE:
            # لا نمنع المستخدم: نفتح القيد نفسه للتعديل اليدوي، فيُعكس
            # الأثر القديم ويُرحَّل الجديد بنفس آلية بقية المستندات.
            if not ask(self,
                       "هذا السطر ناتج عن عملية مجمّعة.\n\n"
                       "سيُفتح القيد المحاسبي نفسه للتعديل، وعند الحفظ "
                       "يُعكس الأثر القديم ويُرحَّل الجديد على كل "
                       "الحسابات المقابلة.\n\nالمتابعة؟"):
                return
            src, sid = "manual", eid
        if self.on_edit_doc:
            self.on_edit_doc(src, sid)

    def transfer_doc(self):
        """ينقل العملية المحددة لجهة أخرى — بنفس تاريخها ورقمها.

        **الضمان المحاسبي**: يُبدَّل الطرف المقابل فقط. التاريخ والرقم
        والمبالغ والأوزان تبقى كما هي، فتخرج من كشف الجهة القديمة
        وتدخل كشف الجديدة في مكانها الزمني نفسه — والميزان لا يتأثر
        لأن المبلغ لم يتغيّر.
        """
        try:
            from models import doc_transfer
            r = self._selected()
            if not r:
                raise ValueError("اختر سطراً من الكشف أولاً")
            src, sid = r.get("src"), r.get("sid")
            if not src or not sid:
                raise ValueError("هذا السطر بلا مستند مصدري")
            if not doc_transfer.can_transfer(src):
                raise ValueError(
                    "هذا النوع من المستندات لا يُنقل — النقل متاح "
                    "للفواتير والسندات والمشتريات والتسكير.")
            with db(readonly=True) as conn:
                info = doc_transfer.preview(conn, src, sid)
                ents = conn.execute(
                    "SELECT id, name, entity_type FROM entities"
                    " WHERE is_deleted=0 AND id<>? ORDER BY name",
                    (info["from_id"],)).fetchall()
            if not ents:
                raise ValueError("لا توجد جهة أخرى للنقل إليها")

            dlg = QtWidgets.QDialog(self)
            dlg.setWindowTitle("نقل العملية لحساب آخر")
            dlg.setMinimumWidth(440)
            cb = search_combo("اكتب اسم الجهة…")
            for e in ents:
                cb.addItem(
                    f"[{entities.TYPE_LABELS.get(e['entity_type'], '')}] "
                    f"{e['name']}", e["id"])
            note = QtWidgets.QLabel(
                f"العملية: {info['doc_no']}\n"
                f"التاريخ: {info['date']}  (لن يتغيّر)\n"
                f"من: {info['from_name']}\n"
                f"أسطر ستُنقل: {info['line_count']}\n\n"
                f"يُبدَّل الطرف المقابل فقط — المبالغ والأوزان "
                f"والتاريخ والرقم تبقى كما هي.")
            note.setWordWrap(True)
            reason = QtWidgets.QLineEdit()
            reason.setPlaceholderText("سبب النقل (يُسجَّل في التدقيق)")
            box = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.Ok
                | QtWidgets.QDialogButtonBox.Cancel)
            box.accepted.connect(dlg.accept)
            box.rejected.connect(dlg.reject)
            f = QtWidgets.QFormLayout()
            f.addRow(note)
            f.addRow("إلى الجهة:", cb)
            f.addRow("السبب:", reason)
            lay = QtWidgets.QVBoxLayout(dlg)
            lay.addLayout(f)
            lay.addWidget(box)
            if dlg.exec_() != QtWidgets.QDialog.Accepted:
                return
            new_id = cb.currentData()
            if new_id is None:
                raise ValueError("اختر الجهة المنقول إليها")
            with db() as conn:
                res = doc_transfer.transfer(
                    conn, src, sid, new_id, self.user["username"],
                    reason.text().strip())
            info2 = (f"نُقلت العملية {res['doc_no']} بتاريخ "
                     f"{res['date']}\n\n"
                     f"من: {res['from_name']}\n"
                     f"إلى: {res['to_name']}\n"
                     f"أسطر منقولة: {res['lines_moved']}\n\n"
                     f"التاريخ والمبالغ لم تتغيّر.")
            from ui.widgets.common import info as _info
            _info(self, info2)
            self.refresh()
        except Exception as e:
            err(self, e)

    def delete_doc(self):
        row = self._selected()
        if not row:
            err(self, "اختر سطر مستند من الكشف أولاً")
            return
        if not ask(self, f"حذف القيد رقم {row['eid']} وعكس أثره المالي "
                         "والمخزني بالكامل؟ لا يمكن التراجع."):
            return
        try:
            info(self, soft_delete_entry(int(row["eid"]), self.user["username"]))
            self.load()
        except Exception as e:
            err(self, e)

    def preview_selected(self):
        from services import print_manager
        """يعاين مستند الصف المحدد (نقر مزدوج أو زر المعاينة)."""
        try:
            i = self.table.currentRow()
            rows = getattr(self, "rows", [])
            if not (0 <= i < len(rows)):
                return
            r = rows[i]
            src, sid = r.get("src"), r.get("sid")
            if not src or not sid or src not in print_manager.BUILDERS:
                return
            print_manager.preview_document(self, src, sid)
        except Exception as e:
            err(self, e)

    # ══════════════════════════════════════════════════════════════
    #  دفتر اليومية — كل عمليات الفترة بلا تحديد حساب
    # ══════════════════════════════════════════════════════════════

    def _load_day_book(self):
        """يعرض كل مستندات الفترة على جميع الحسابات.

        الغرض عملي: بعد جرد أو مراجعة يظهر فرق، فيُراد معرفة ما جرى
        في يوم بعينه دون معرفة حسابه مسبقاً. كشف الحساب لا يجيب عن
        هذا لأنه يشترط حساباً، والرصيد التراكمي بلا معنى عبر الحسابات.
        """
        d1, d2 = dstr(self.d_from), dstr(self.d_to)
        if d1 > d2:
            raise ValueError("تاريخ «من» بعد تاريخ «إلى»")
        kind = self.op_kind.currentData()
        with db(readonly=True) as conn:
            rows = journal.day_book(conn, d1, d2, kind)
        self.rows = rows

        k = self._k()
        headers = ["التاريخ", "نوع\nالعملية", "رقم\nالسند",
                   "الحسابات المتأثرة", "البيان",
                   f"إجمالي\nذهب {k}", "إجمالي\nنقد", "المستخدم", "معاينة"]
        self.table.setRowCount(0)
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        fit_columns(self.table, [9, 8, 8, 26, 20, 8, 8, 8, 5])

        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        try:
            self.table.setRowCount(len(rows) + (1 if rows else 0))
            _C = QtCore.Qt.AlignCenter
            for i, r in enumerate(rows):
                cellv = [
                    text_item(r["date"], _C), text_item(r["op"], _C),
                    text_item(r["doc_no"], _C), text_item(r["accounts"]),
                    text_item(r["desc"]),
                    num_item(f"{self._g(r['gold']):,.3f}" if r["gold"] else ""),
                    num_item(f"{r['cash']:,.2f}" if r["cash"] else ""),
                    text_item(r["who"], _C),
                    text_item("👁" if (r.get("src") and r.get("sid")) else "",
                              _C),
                ]
                for c, it in enumerate(cellv):
                    self.table.setItem(i, c, it)
            if rows:
                # صفُّ الختام هنا أيضاً: اليومية تُطبع كما يُطبع الكشف
                self._sum_row(len(rows), [
                    text_item("الإجمالي", _C), text_item("", _C),
                    text_item("", _C), text_item(""), text_item(""),
                    num_item(f"{self._g(sum(r['gold'] for r in rows)):,.3f}"),
                    num_item(f"{sum(r['cash'] for r in rows):,.2f}"),
                    text_item("", _C), text_item("", _C),
                ])
        finally:
            self.table.setUpdatesEnabled(True)
        ledger_rows(self.table, wrap_cols=(3, 4))
        self.table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        fit_columns(self.table)

        tg = sum(r["gold"] for r in rows)
        tc = sum(r["cash"] for r in rows)
        self.g_debit.set_value(f"{self._g(tg):,.2f}", f"جم عيار {k}")
        self.g_credit.set_value("—")
        self.g_bal.set_value(f"{len(rows):,}", "عدد المستندات")
        self.c_debit.set_value(f"{tc:,.2f}")
        self.c_credit.set_value("—")
        self.c_bal.set_value(f"{len(rows):,}", "عدد المستندات")
        # الحسابات المتأثرة (3) والبيان (4)
        self._show_latest()
        if not rows:
            info(self, f"لا توجد عمليات بين {d1} و{d2}.")

    def refresh(self):
        with db(readonly=True) as conn:
            self.accounts = list_postable(conn)
        current = self.account.currentData()
        self.account.blockSignals(True)
        self.account.clear()
        # خيار «كل الحسابات» أولاً: يعرض عمليات الفترة كلها بلا تحديد
        # حساب — للبحث عن خطأ لا يُعرف حسابه مسبقاً.
        self.account.addItem("★ كل الحسابات — عمليات الفترة كاملةً",
                             journal.ALL_ACCOUNTS)
        for a in self.accounts:
            self.account.addItem(f"{a['code']} — {a['name']}", a["code"])
        if current is not None:
            idx = self.account.findData(current)
            if idx >= 0:
                self.account.setCurrentIndex(idx)
        else:
            # عند فتح الشاشة تبقى قائمة البحث فارغة تماماً حتى يبحث
            # المستخدم ويختار حساباً بنفسه.
            self.account.setCurrentIndex(-1)
            if hasattr(self.account, "lineEdit") and self.account.lineEdit():
                self.account.lineEdit().clear()
            self.table.setRowCount(0)
        self.account.blockSignals(False)
