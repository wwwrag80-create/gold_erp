# -*- coding: utf-8 -*-
"""شاشة التكويد الموحّدة لجهات التعامل — البوابة الوحيدة لتأسيس
الحسابات. الحقول تتغير ديناميكياً حسب نوع الجهة، مع إكمال تلقائي ذكي
على الاسم يمنع تكرار الحسابات (توحيد الهمزات والتاء المربوطة)."""
from PyQt5 import QtCore, QtWidgets

from database.database import db
from services import karat_view as kv
from models import entities
from ui.widgets.common import (TitledSections, ask, big_label, date_edit,
                               dstr, err, fill, info, make_table, mspin,
                               style_group_row, wspin)
from ui.widgets.table_tools import enhance

TYPE_ITEMS = [("عميل", "customer"), ("مورد", "supplier"),
              ("شريك", "partner"), ("موظف", "employee"),
              ("عامل", "worker"), ("جهة أخرى", "other")]

HINTS = {
    "customer": "يُنشأ حساب فرعي واحد تحت «إجمالي العملاء» يقبل رصيدين: "
               "نقدي ووزني (ذهب).",
    "supplier": "يُنشأ حساب فرعي تحت «إجمالي الموردين» (خصوم). الرقم الضريبي "
               "إلزامي لدعم الفوترة الإلكترونية ZATCA.",
    "partner": "يُنشأ حسابان آلياً: «رأس مال الشريك» و«جاري الشريك» "
              "(المسحوبات والتوزيعات والمعاملات اليومية).",
    "worker": "عامل قسم التصنيع: يُنشأ حسابه تحت «سلف عمال التصنيع» "
              "ومستحقاته تحت «رواتب العمال المستحقة»، ويظهر فوراً في "
              "شاشة رواتب العمال والإدارة (جدولا التارجت والرواتب).",
    "employee": "يُنشأ حساب فرعي تحت «سلف الموظفين» + سجل في جدول الموظفين "
               "ليظهر في جدول الرواتب بشاشة رواتب العمال والإدارة.",
    "other": "جهات متنوعة (مدينون آخرون): يُنشأ حساب فرعي تحت «إجمالي "
            "الجهات الأخرى» ضمن الأصول المتداولة، بأرصدة وكشوفات حساب "
            "مفصّلة تماماً كالعملاء والموردين.",
}


class EntitiesScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user

        self.etype = QtWidgets.QComboBox()
        for label, val in TYPE_ITEMS:
            self.etype.addItem(label, val)
        self.etype.currentIndexChanged.connect(self._type_changed)

        self.name = QtWidgets.QLineEdit()
        self.name.setPlaceholderText("اكتب الاسم — ستظهر الأسماء المشابهة تلقائياً")
        self.name.textChanged.connect(self._check_similar)
        self.completer_model = QtCore.QStringListModel()
        comp = QtWidgets.QCompleter(self.completer_model, self)
        comp.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        comp.setFilterMode(QtCore.Qt.MatchContains)
        self.name.setCompleter(comp)
        self.similar = QtWidgets.QLabel()
        self.similar.setObjectName("warn")
        self.similar.setWordWrap(True)

        self.phone = QtWidgets.QLineEdit()
        self.address = QtWidgets.QLineEdit()
        self.vat = QtWidgets.QLineEdit()
        self.share = mspin(maximum=100.0)
        self.job_title = QtWidgets.QLineEdit()
        self.salary = mspin()
        self.open_cash = mspin(minimum=-1_000_000_000.0)
        self.open_gold = wspin()
        self.gold_sign = QtWidgets.QComboBox()
        self.gold_sign.addItem("مدين (عليه ذهب لنا)", 1)
        self.gold_sign.addItem("دائن (له ذهب علينا)", -1)
        self.open_date = date_edit()

        self.hint = QtWidgets.QLabel()
        self.hint.setObjectName("cardSub")
        self.hint.setProperty("note", True)     # شرح نوع الجهة — يُطوى
        self.hint.setWordWrap(True)

        self.form = QtWidgets.QFormLayout()
        self.form.addRow("نوع الجهة:", self.etype)
        self.form.addRow("الاسم:", self.name)
        self.form.addRow(self.similar)
        self.r_phone = self._row("رقم التواصل:", self.phone)
        self.r_address = self._row("العنوان:", self.address)
        self.r_vat = self._row("الرقم الضريبي:", self.vat)
        self.r_share = self._row("نسبة الحصة في المصنع (%):", self.share)
        self.r_job = self._row("المسمى الوظيفي:", self.job_title)
        self.r_salary = self._row("الراتب الأساسي:", self.salary)

        gw = QtWidgets.QWidget()
        gl = QtWidgets.QHBoxLayout(gw)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.addWidget(self.open_gold, 1)
        gl.addWidget(self.gold_sign, 1)

        self.open_box = QtWidgets.QGroupBox("الأرصدة الافتتاحية (اختيارية)")
        of = QtWidgets.QFormLayout(self.open_box)
        self.lbl_cash = QtWidgets.QLabel("الرصيد النقدي (+ مدين / − دائن):")
        of.addRow(self.lbl_cash, self.open_cash)
        self.lbl_gold = QtWidgets.QLabel(
            f"الرصيد الوزني (ذهب جم {kv.label()}):")
        of.addRow(self.lbl_gold, gw)
        self.gold_widget = gw
        of.addRow("تاريخ الرصيد الافتتاحي:", self.open_date)
        n = QtWidgets.QLabel("يُولَّد قيد افتتاحي آلي مقابل «الأرصدة الافتتاحية "
                            "للتسوية» (3900).")
        n.setObjectName("cardSub")
        n.setWordWrap(True)
        of.addRow(n)

        btn_save = QtWidgets.QPushButton("حفظ واعتماد (إنشاء الحساب + القيد الافتتاحي)")
        btn_save.clicked.connect(self.save)

        add_box = QtWidgets.QGroupBox("إضافة جهة تعامل جديدة")
        al = QtWidgets.QVBoxLayout(add_box)
        al.addLayout(self.form)
        al.addWidget(self.hint)
        al.addWidget(self.open_box)
        al.addWidget(btn_save)

        self.table = make_table()
        # بلا فرزٍ بالنقر: صفوف هذا الجدول موازيةٌ لقائمة `_row_ids`
        # بالترتيب، فإعادة ترتيبها تجعل «احذف المحدد» يحذف غير المحدد.
        enhance(self.table, key="entities", sortable=False)
        self.table.itemSelectionChanged.connect(self._row_selected)
        self.table.doubleClicked.connect(lambda *_: self.edit_selected())
        self.summary = big_label()
        self.summary.setWordWrap(True)

        # ══ ① دليل جهات التعامل — قسمٌ مستقل في الأعلى ══
        # الدليل دفترُ الأستاذ المساعد: كل جهةٍ بكود حسابها ومجموعتها
        # الرقابية في الشجرة ورصيدَيها بطبيعتهما (مدين/دائن)، مجمّعةً
        # بنوعها ولكل نوعٍ مجموعه — فيُطابَق مجموعُ كل نوعٍ رصيدَ
        # مجموعته في ميزان المراجعة.
        self.f_type = QtWidgets.QComboBox()
        self.f_type.addItem("كل الأنواع", None)
        for label, val in TYPE_ITEMS:
            self.f_type.addItem(label, val)
        self.f_type.addItem("حساب داخلي", "internal")
        self.f_type.currentIndexChanged.connect(self.refresh)
        self.f_search = QtWidgets.QLineEdit()
        self.f_search.setPlaceholderText("بحث بالاسم أو الهاتف أو الرقم"
                                         " الضريبي…")
        self.f_search.textChanged.connect(self.refresh)
        btn_edit = QtWidgets.QPushButton("✎ تعديل الجهة / نقل نوعها")
        btn_edit.setObjectName("homeBtn")
        btn_edit.clicked.connect(self.edit_selected)
        btn_stmt = QtWidgets.QPushButton("📄 كشف حساب الجهة")
        btn_stmt.clicked.connect(self.statement_selected)
        btn_refresh = QtWidgets.QPushButton("تحديث الأرصدة")
        btn_refresh.setObjectName("ghost")
        btn_refresh.clicked.connect(self.refresh)
        btn_del = QtWidgets.QPushButton("حذف الجهة المحددة (بلا حركات فقط)")
        btn_del.setObjectName("danger")
        btn_del.clicked.connect(self.delete_selected)
        frow = QtWidgets.QHBoxLayout()
        frow.addWidget(QtWidgets.QLabel("النوع:"))
        frow.addWidget(self.f_type)
        frow.addWidget(self.f_search, 1)
        frow.addWidget(btn_edit)
        frow.addWidget(btn_stmt)
        frow.addWidget(btn_refresh)
        frow.addWidget(btn_del)
        dir_page = QtWidgets.QWidget()
        dl = QtWidgets.QVBoxLayout(dir_page)
        dl.setContentsMargins(0, 4, 0, 0)
        dl.addLayout(frow)
        dl.addWidget(self.table, 1)
        dl.addWidget(self.summary)

        add_page = QtWidgets.QWidget()
        apl = QtWidgets.QVBoxLayout(add_page)
        apl.setContentsMargins(0, 4, 0, 0)
        apl.addWidget(add_box)
        apl.addStretch(1)

        terms_page = QtWidgets.QWidget()
        tpl = QtWidgets.QVBoxLayout(terms_page)
        tpl.setContentsMargins(0, 4, 0, 0)
        tnote = QtWidgets.QLabel("حدّد الجهة من «دليل جهات التعامل» ثم اضبط"
                                 " شروطها هنا.")
        tnote.setObjectName("cardSub")
        tpl.addWidget(tnote)
        tpl.addWidget(self._credit_box())
        tpl.addStretch(1)

        self.tabs = TitledSections("التكويد الموحّد لجهات التعامل")
        self.tabs.addTab(dir_page, "📒 دليل جهات التعامل")
        self.tabs.addTab(add_page, "➕ إضافة جهة")
        self.tabs.addTab(terms_page, "⚖ شروط التعامل")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self.tabs, 1)
        self._type_changed()

    # ══════════════════════════════════════════════════════════════
    #  شروط التعامل: حدّ الائتمان والأجرة المتفق عليها
    # ══════════════════════════════════════════════════════════════

    def _credit_box(self):
        """لوحة شروط التعامل: سقف الجهة، ووضع الحارس، وأجرتها المتفق عليها.

        موضعها تحت الدليل مقصود: السقف يُضبط لجهةٍ **قائمة** في أغلب
        الأحيان لا لجهةٍ تُنشأ الآن — فالحاجة تظهر بعد أن يكبر الرصيد.
        """
        self.lim_cash = mspin()
        self.lim_cash.setToolTip("صفر = بلا حدّ")
        self.lim_gold = wspin()
        self.lim_gold.setToolTip("صفر = بلا حدّ")
        self.lbl_lim_gold = QtWidgets.QLabel(
            f"سقف وزني ({kv.unit()}):")
        self.lbl_credit_who = QtWidgets.QLabel("— لم تُحدَّد جهة —")
        self.lbl_credit_who.setObjectName("big")
        btn = QtWidgets.QPushButton("حفظ سقف الجهة المحددة")
        btn.clicked.connect(self.save_limit)

        self.agreed_wage = mspin()
        self.agreed_wage.setToolTip("صفر = بلا اتفاق")
        self.lbl_agreed = QtWidgets.QLabel(
            f"الأجرة المتفق عليها (ريال/{kv.unit()}):")
        self.agreed_from = date_edit()
        self.lbl_agreed_hist = QtWidgets.QLabel("")
        self.lbl_agreed_hist.setObjectName("cardSub")
        self.lbl_agreed_hist.setProperty("live", True)
        self.lbl_agreed_hist.setWordWrap(True)
        btn_wage = QtWidgets.QPushButton("حفظ الأجرة المتفق عليها")
        btn_wage.clicked.connect(self.save_agreed_wage)

        self.guard_mode = QtWidgets.QComboBox()
        for label, val in (("تنبيه فقط (الافتراضي)", "warn"),
                           ("منع الترحيل عند التجاوز", "block"),
                           ("بلا فحص", "off")):
            self.guard_mode.addItem(label, val)
        self.guard_mode.currentIndexChanged.connect(self._mode_changed)

        box = QtWidgets.QGroupBox(
            "شروط التعامل مع الجهة — سقف الائتمان والأجرة المتفق عليها")
        g = QtWidgets.QGridLayout(box)
        g.addWidget(QtWidgets.QLabel("الجهة:"), 0, 0)
        g.addWidget(self.lbl_credit_who, 0, 1, 1, 3)
        g.addWidget(QtWidgets.QLabel("سقف نقدي (ريال):"), 1, 0)
        g.addWidget(self.lim_cash, 1, 1)
        g.addWidget(self.lbl_lim_gold, 1, 2)
        g.addWidget(self.lim_gold, 1, 3)
        g.addWidget(btn, 1, 4)
        g.addWidget(QtWidgets.QLabel("عند التجاوز:"), 2, 0)
        g.addWidget(self.guard_mode, 2, 1)
        # ══ الأجرة المتفق عليها ══
        # موضعها هنا مع السقف مقصود: كلاهما **شرطُ تعاملٍ** مع الجهة
        # يُضبط مرةً ويُقاس عليه كل مستند — لا بيانٌ تعريفيٌّ كالهاتف.
        g.addWidget(self.lbl_agreed, 3, 0)
        g.addWidget(self.agreed_wage, 3, 1)
        g.addWidget(QtWidgets.QLabel("سارية من:"), 3, 2)
        g.addWidget(self.agreed_from, 3, 3)
        g.addWidget(btn_wage, 3, 4)
        g.addWidget(self.lbl_agreed_hist, 4, 0, 1, 5)
        note = QtWidgets.QLabel(
            "صفر = بلا حدّ. يُفحص السقف «لحظة الترحيل» لا في تقرير آخر "
            "الشهر — فالبضاعة تخرج لحظتها. والسداد الذي يخفّض الدين "
            "يمرّ دائماً ولو كان الرصيد فوق السقف.\n"
            "والأجرة المتفق عليها تُملأ تلقائياً في شاشة المبيعات "
            "ويُنبَّه البائع إن خالفها. صفرٌ فيها يعني «بلا اتفاق» فلا "
            "تُفرض على أحد. وكل تغييرٍ يُحفظ بتاريخه، فمن راجع فاتورةً "
            "قديمة قرأ الاتفاق الذي كان نافذاً يومها لا اتفاق اليوم.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        g.addWidget(note, 5, 0, 1, 5)
        return box

    def save_agreed_wage(self):
        try:
            eid = self._current_id()
            if eid is None:
                raise ValueError("حدّد جهةً من الدليل أولاً")
            with db() as conn:
                entities.set_agreed_wage(
                    conn, eid, kv.rate_store(self.agreed_wage.value()),
                    dstr(self.agreed_from), "", self.user["username"])
            info(self, "حُفظت الأجرة المتفق عليها — وسُجّلت بتاريخها.")
            self.refresh()
        except Exception as e:
            err(self, e)

    def _row_selected(self):
        """يملأ حقول السقف بقيم الجهة المحددة في الدليل."""
        try:
            eid = self._current_id()
            if eid is None:
                self.lbl_credit_who.setText("— لم تُحدَّد جهة —")
                return
            with db(readonly=True) as conn:
                e = entities.get_entity(conn, eid)
                c, g = entities.credit_limit(conn, eid)
                aw = entities.agreed_wage(conn, eid)
                hist = entities.wage_history(conn, eid)
            self.lbl_credit_who.setText(e["name"] if e else "—")
            self.lim_cash.setValue(c)
            self.lim_gold.setValue(kv.g(g))
            self.agreed_wage.setValue(kv.rate(aw) if aw else 0.0)
            # السجلّ يُعرض لأن الرقم وحده لا يقول متى اتُّفق عليه —
            # ومن راجع فاتورةً قديمة احتاج الاتفاقَ الذي كان نافذاً
            self.lbl_agreed_hist.setText(
                ("سجلّ الاتفاقات: " + " · ".join(
                    f"{kv.rate(float(h['wage'])):,.2f} من {h['from_date']}"
                    for h in hist[:5]))
                if hist else "لا سجلّ اتفاقاتٍ لهذه الجهة بعد.")
        except Exception:
            pass          # ضبط السقف رفاهية لا تُعطّل الدليل

    def save_limit(self):
        try:
            eid = self._current_id()
            if eid is None:
                raise ValueError("حدّد جهةً من الدليل أولاً")
            with db() as conn:
                entities.set_credit_limit(
                    conn, eid, self.lim_cash.value(),
                    kv.store(self.lim_gold.value()), self.user["username"])
            info(self, "حُفظ حدّ الائتمان للجهة المحددة.")
            self.refresh()
        except Exception as e:
            err(self, e)

    def _mode_changed(self):
        if getattr(self, "_loading_mode", False):
            return
        try:
            from services import credit_guard
            with db() as conn:
                credit_guard.set_mode(conn, self.guard_mode.currentData(),
                                      self.user["username"])
        except Exception as e:
            err(self, e)

    def _load_mode(self):
        try:
            from services import credit_guard
            with db(readonly=True) as conn:
                m = credit_guard.mode(conn)
            self._loading_mode = True
            i = self.guard_mode.findData(m)
            if i >= 0:
                self.guard_mode.setCurrentIndex(i)
        except Exception:
            pass
        finally:
            self._loading_mode = False

    def _row(self, label_text, widget):
        lbl = QtWidgets.QLabel(label_text)
        self.form.addRow(lbl, widget)
        return (lbl, widget)

    @staticmethod
    def _show(row, visible):
        row[0].setVisible(visible)
        row[1].setVisible(visible)

    def _check_similar(self, text):
        """إكمال تلقائي ذكي: يقترح الأسماء المتقاربة ويحذّر من التكرار."""
        if len(text.strip()) < 2:
            self.similar.setText("")
            return
        t = self.etype.currentData()
        with db() as conn:
            found = entities.find_similar(conn, text, t)
            exact = entities.name_exists(conn, text, t)
        if exact:
            self.similar.setText(
                f"⚠ يوجد {entities.TYPE_LABELS[t]} مسجَّل بنفس الاسم: "
                f"«{exact['name']}» — لا تُنشئ حساباً مكرراً")
        elif found:
            names = "، ".join(f["name"] for f in found[:5])
            self.similar.setText(f"أسماء مشابهة مسجَّلة مسبقاً: {names}")
        else:
            self.similar.setText("")

    def _type_changed(self):
        t = self.etype.currentData()
        is_emp = t in ("employee", "worker")
        is_partner = t == "partner"
        is_trade = t in ("customer", "supplier", "other")
        self._show(self.r_phone, True)
        self._show(self.r_address, is_trade)
        self._show(self.r_vat, is_trade)
        self._show(self.r_share, is_partner)
        self._show(self.r_job, is_emp)
        self._show(self.r_salary, is_emp)
        self.lbl_gold.setVisible(not is_emp)
        self.gold_widget.setVisible(not is_emp)
        if is_partner:
            self.lbl_cash.setText("رأس المال التأسيسي نقداً:")
            self.lbl_gold.setText(
                f"رأس المال التأسيسي ذهباً ({kv.unit()}):")
            self.gold_sign.setVisible(False)
            self.open_box.setTitle("رأس المال التأسيسي (اختياري)")
        else:
            self.gold_sign.setVisible(True)
            self.open_box.setTitle("الأرصدة الافتتاحية (اختيارية)")
            self.lbl_gold.setText(
                f"الرصيد الوزني (ذهب جم {kv.label()}):")
            self.lbl_cash.setText("الرصيد النقدي — سلف سابقة (+ عليه):"
                                  if is_emp else "الرصيد النقدي (+ مدين / − دائن):")
        self.hint.setText(HINTS.get(t, ""))
        self._reload_completer()
        self._check_similar(self.name.text())

    def _reload_completer(self):
        with db() as conn:
            names = [e["name"] for e in
                     entities.list_entities(conn, (self.etype.currentData(),))]
        self.completer_model.setStringList(names)

    def save(self):
        try:
            t = self.etype.currentData()
            sign = 1 if t == "partner" else (self.gold_sign.currentData() or 1)
            with db() as conn:
                entities.add_entity(
                    conn, self.name.text(), t,
                    phone=self.phone.text(), vat_number=self.vat.text(),
                    username=self.user["username"], address=self.address.text(),
                    open_cash=self.open_cash.value(),
                    open_gold=(0.0 if t in ("employee", "worker")
                              else kv.store(self.open_gold.value()) * sign),
                    opening_date=dstr(self.open_date),
                    share_percent=self.share.value(),
                    job_title=self.job_title.text(),
                    basic_salary=self.salary.value())
            info(self, "تم حفظ الجهة وإنشاء حسابها الفرعي آلياً"
                       + (" مع قيد الرصيد الافتتاحي"
                          if (self.open_cash.value() or self.open_gold.value())
                          else ""))
            for w in (self.name, self.phone, self.address, self.vat, self.job_title):
                w.clear()
            for s in (self.share, self.salary, self.open_cash, self.open_gold):
                s.setValue(0)
            self.refresh()
        except Exception as e:
            err(self, e)

    def delete_selected(self):
        eid = self._current_id()
        if eid is None:
            return
        if not ask(self, "حذف الجهة المحددة؟ (يُسمح فقط لمن ليس لها أي حركة)"):
            return
        try:
            with db() as conn:
                entities.delete_entity(conn, eid, self.user["username"])
            info(self, "تم حذف الجهة")
            self.refresh()
        except Exception as e:
            err(self, e)

    def refresh(self, *_):
        from services import credit_guard
        t = self.f_type.currentData()
        types = (t,) if t else None
        with db() as conn:
            rows, self._row_ids, groups = [], [], []
            # المتجاوزون يُقرأون دفعةً واحدة لا جهةً جهة — الدليل قد
            # يحوي مئات الأسماء، واستعلامٌ لكل اسم يُبطئ فتح الشاشة.
            over = {r["entity_id"]: r for r in credit_guard.over_limit(conn)}
            items = entities.directory(conn, types, self.f_search.text().strip())
            share_total = entities.partners_share_total(conn)
            extra_of = {}
            for d in items:
                e = d["row"]
                if e["entity_type"] == "partner":
                    cg, cc_ = entities.capital_balance(conn, e["id"])
                    extra_of[e["id"]] = (
                        f"رأس مال: {abs(cc_):,.2f} ر / {kv.g(abs(cg)):,.2f}"
                        f" — حصة {e['share_percent']:.1f}%")
                elif e["entity_type"] in ("employee", "worker"):
                    extra_of[e["id"]] = (f"{e['job_title'] or '—'} — راتب "
                                         f"{e['basic_salary']:,.2f}")
                else:
                    extra_of[e["id"]] = " · ".join(
                        x for x in ((e["phone"] or ""),
                                    (f"ض: {e['vat_number']}"
                                     if e["vat_number"] else ""))
                        if x) or "—"
                lc, lg = entities.credit_limit(conn, e["id"])
                d["limit"] = lc, lg

        def _side(v, dec, unit=""):
            if abs(v) < (0.0005 if dec == 3 else 0.005):
                return "—"
            return f"{abs(v):,.{dec}f}{unit} " + ("مدين" if v > 0 else "دائن")

        order = [v for _l, v in TYPE_ITEMS] + ["internal"]
        by_t = {}
        for d in items:
            by_t.setdefault(d["type"], []).append(d)
        for tt in order:
            grp = by_t.get(tt)
            if not grp:
                continue
            tc = round(sum(x["cash"] for x in grp), 2)
            tg = round(sum(x["gold"] for x in grp), 3)
            for d in grp:
                lc, lg = d["limit"]
                bits = []
                if lc:
                    bits.append(f"{lc:,.0f} ريال")
                if lg:
                    bits.append(f"{kv.g(lg):,.0f} {kv.unit()}")
                limit_txt = " · ".join(bits) if bits else "بلا حدّ"
                if d["id"] in over:
                    limit_txt = "⛔ تجاوز — " + limit_txt
                rows.append((d["code"], d["name"],
                             entities.TYPE_LABELS[d["type"]], d["group"],
                             _side(d["cash"], 2), _side(kv.g(d["gold"]), 3),
                             limit_txt, extra_of.get(d["id"], "—")))
                self._row_ids.append(d["id"])
            _pl = {"customer": "العملاء", "supplier": "الموردين",
                   "partner": "الشركاء", "employee": "الموظفين",
                   "worker": "العمال", "other": "الجهات الأخرى",
                   "internal": "الحسابات الداخلية"}.get(tt, tt)
            rows.append(("", f"إجمالي {_pl} ({len(grp)})",
                         "", "", _side(tc, 2), _side(kv.g(tg), 3), "", ""))
            self._row_ids.append(None)
            groups.append(len(rows) - 1)
        fill(self.table, ["الكود", "الاسم", "النوع", "الحساب الرقابي",
                          "الرصيد النقدي (ريال)",
                          f"الرصيد الوزني ({kv.unit()})", "حدّ الائتمان",
                          "بيانات"], rows)
        for r in groups:
            try:
                style_group_row(self.table, r, 2)
            except Exception:
                pass
        try:
            from ui.widgets.table_fit import fit_columns
            fit_columns(self.table, [8, 20, 8, 18, 13, 13, 10, 10])
        except Exception:
            pass
        n = sum(1 for x in self._row_ids if x is not None)
        w = "" if abs(share_total - 100) < 0.01 or share_total == 0 else \
            "  ⚠ المجموع لا يساوي 100%"
        over_txt = f" | ⛔ متجاوزون للسقف: {len(over)}" if over else ""
        self.summary.setText(
            f"عدد الجهات: {n} | مجموع حصص الشركاء: "
            f"{share_total:.2f}%{w}{over_txt}\n"
            "مجموع كل نوعٍ يطابق رصيد مجموعته الرقابية في ميزان المراجعة."
            " النقر المزدوج على جهةٍ يفتحها للتعديل أو نقل نوعها.")
        self._reload_completer()
        self._load_mode()

    def _current_id(self):
        r = self.table.currentRow()
        ids = getattr(self, "_row_ids", [])
        return ids[r] if 0 <= r < len(ids) else None

    def edit_selected(self):
        try:
            eid = self._current_id()
            if eid is None:
                raise ValueError("حدّد جهةً من الدليل أولاً (لا صفّ إجمالي)")
            with db(readonly=True) as conn:
                e = entities.get_entity(conn, eid)
            if e["entity_type"] == "internal":
                raise ValueError("الحساب الداخلي يُدار من دليل الحسابات")
            dlg = EntityEditDialog(self, e)
            if dlg.exec_() != QtWidgets.QDialog.Accepted:
                return
            v = dlg.values()
            with db() as conn:
                entities.update_entity(
                    conn, eid, self.user["username"], name=v["name"],
                    phone=v["phone"], address=v["address"],
                    vat_number=v["vat"], job_title=v["job"],
                    basic_salary=v["salary"], share_percent=v["share"],
                    direct_pay=v["direct"])
                res = entities.change_entity_type(
                    conn, eid, v["type"], self.user["username"])
            msg = "حُفظت بيانات الجهة."
            if res.get("changed"):
                msg += ("\n\nنُقل نوعها: "
                        f"{entities.TYPE_LABELS[res['from']]} ← "
                        f"{entities.TYPE_LABELS[res['to']]} — وانتقل حسابها"
                        " بقيوده ورصيده تحت مجموعته الرقابية الجديدة، فيظهر"
                        " في قسمه الصحيح من الميزانية.")
            info(self, msg)
            self.refresh()
        except Exception as e:
            err(self, e)

    def statement_selected(self):
        try:
            eid = self._current_id()
            if eid is None:
                raise ValueError("حدّد جهةً من الدليل أولاً")
            with db(readonly=True) as conn:
                e = entities.get_entity(conn, eid)
                a = conn.execute("SELECT code, name FROM accounts WHERE id=?",
                                 (e["account_id"],)).fetchone()
            from ui.widgets.account_movement import show_movement
            show_movement(self, a["code"], a["name"])
        except Exception as e:
            err(self, e)


class EntityEditDialog(QtWidgets.QDialog):
    """بطاقة الجهة للتعديل — ونوعها بين الأنواع المتوافقة محاسبياً."""

    def __init__(self, parent, e):
        super().__init__(parent)
        self.e = e
        self.setWindowTitle(f"تعديل الجهة — {e['name']}")
        self.setLayoutDirection(QtCore.Qt.RightToLeft)
        self.setMinimumWidth(520)
        t = e["entity_type"]
        self.type = QtWidgets.QComboBox()
        for tt in entities.allowed_types(t):
            self.type.addItem(entities.TYPE_LABELS[tt], tt)
        self.type.setCurrentIndex(max(0, self.type.findData(t)))
        self.name = QtWidgets.QLineEdit(e["name"])
        self.phone = QtWidgets.QLineEdit(e["phone"] or "")
        self.address = QtWidgets.QLineEdit(e["address"] or "")
        self.vat = QtWidgets.QLineEdit(e["vat_number"] or "")
        self.job = QtWidgets.QLineEdit(e["job_title"] or "")
        self.salary = mspin()
        self.salary.setValue(float(e["basic_salary"] or 0))
        self.share = mspin(maximum=100.0)
        self.share.setValue(float(e["share_percent"] or 0))
        f = QtWidgets.QFormLayout()
        f.addRow("نوع الجهة:", self.type)
        f.addRow("الاسم:", self.name)
        f.addRow("رقم التواصل:", self.phone)
        if t in entities.TRADE_TYPES:
            f.addRow("العنوان:", self.address)
            f.addRow("الرقم الضريبي:", self.vat)
        self.direct = QtWidgets.QCheckBox(
            "يُصرف له مباشرةً بلا مسير رواتب — كل سند صرفٍ له يُحمَّل"
            " أجراً (مصروفات العمال / رواتب الإدارة)")
        try:
            self.direct.setChecked(bool(e["direct_pay"]))
        except (IndexError, KeyError):
            pass
        if t in entities.STAFF_TYPES:
            f.addRow("المسمى الوظيفي:", self.job)
            f.addRow("الراتب الأساسي:", self.salary)
            f.addRow("", self.direct)
        if t == "partner":
            f.addRow("نسبة الحصة (%):", self.share)
        self.note = QtWidgets.QLabel()
        self.note.setObjectName("cardSub")
        self.note.setWordWrap(True)
        self.type.currentIndexChanged.connect(self._sync)
        bb = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.button(QtWidgets.QDialogButtonBox.Ok).setText("حفظ")
        bb.button(QtWidgets.QDialogButtonBox.Cancel).setText("إلغاء")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v = QtWidgets.QVBoxLayout(self)
        v.addLayout(f)
        v.addWidget(self.note)
        v.addWidget(bb)
        self._sync()

    def _sync(self, *_):
        t0, t1 = self.e["entity_type"], self.type.currentData()
        if t1 == t0:
            self.note.setText(
                "أنواعٌ يُنقل إليها: " + " · ".join(
                    entities.TYPE_LABELS[x]
                    for x in entities.allowed_types(t0) if x != t0)
                + ". والتجاري لا يُنقل إلى موظفٍ أو شريك — بنيته مختلفة."
                if len(entities.allowed_types(t0)) > 1 else
                "هذا النوع لا يُنقل إلى غيره — بنيته المحاسبية مختلفة.")
        else:
            grp = {"customer": "إجمالي العملاء (أصول متداولة)",
                   "supplier": "إجمالي الموردين (خصوم متداولة)",
                   "other": "إجمالي الجهات الأخرى (أصول متداولة)",
                   "employee": "مستحقات الموظفين",
                   "worker": "رواتب العمال المستحقة"}.get(t1, "")
            self.note.setText(
                f"⚠ نقل النوع إعادةُ تصنيف: ينتقل حساب الجهة بقيوده ورصيده"
                f" تحت «{grp}». لا يُمسّ قيدٌ سابق، ويظهر الرصيد في قسمه"
                " الجديد من الميزانية من الآن.")

    def values(self):
        return {"type": self.type.currentData(), "name": self.name.text(),
                "phone": self.phone.text(), "address": self.address.text(),
                "vat": self.vat.text(), "job": self.job.text(),
                "salary": self.salary.value(), "share": self.share.value(),
                "direct": self.direct.isChecked()}
