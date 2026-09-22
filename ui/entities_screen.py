# -*- coding: utf-8 -*-
"""شاشة التكويد الموحّدة لجهات التعامل — البوابة الوحيدة لتأسيس
الحسابات. الحقول تتغير ديناميكياً حسب نوع الجهة، مع إكمال تلقائي ذكي
على الاسم يمنع تكرار الحسابات (توحيد الهمزات والتاء المربوطة)."""
from PyQt5 import QtCore, QtWidgets

from database.database import db
from services import karat_view as kv
from models import entities
from ui.widgets.common import (ask, big_label, date_edit, dstr, err, fill,
                               info, make_table, mspin, title_label, wspin)
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
              "شاشة تكاليف ورواتب قسم التصنيع. مستقل تماماً عن "
              "الموظفين الإداريين.",
    "employee": "يُنشأ حساب فرعي تحت «سلف الموظفين» + سجل في جدول الموظفين "
               "ليظهر في مسيرات الرواتب.",
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
        self.summary = big_label()
        btn_refresh = QtWidgets.QPushButton("تحديث الأرصدة")
        btn_refresh.setObjectName("ghost")
        btn_refresh.clicked.connect(self.refresh)
        btn_del = QtWidgets.QPushButton("حذف الجهة المحددة (بلا حركات فقط)")
        btn_del.setObjectName("danger")
        btn_del.clicked.connect(self.delete_selected)

        list_box = QtWidgets.QGroupBox("دليل جهات التعامل")
        ll = QtWidgets.QVBoxLayout(list_box)
        ll.addWidget(self.table)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(btn_refresh)
        row.addWidget(btn_del)
        row.addStretch(1)
        row.addWidget(self.summary)
        ll.addLayout(row)
        ll.addWidget(self._credit_box())

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("التكويد الموحّد لجهات التعامل"))
        sp = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        w1 = QtWidgets.QWidget(); QtWidgets.QVBoxLayout(w1).addWidget(add_box)
        w2 = QtWidgets.QWidget(); QtWidgets.QVBoxLayout(w2).addWidget(list_box)
        sp.addWidget(w1); sp.addWidget(w2)
        # نموذج الإضافة ثابت الطول، والدليل يطول بعدد الجهات — فالتمدّد
        # للدليل وحده، والفاصل قابل للسحب لمن يريد غير ذلك.
        sp.setStretchFactor(0, 0)
        sp.setStretchFactor(1, 1)
        lay.addWidget(sp, 1)
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
            r = self.table.currentRow()
            ids = getattr(self, "_row_ids", [])
            if r < 0 or r >= len(ids):
                raise ValueError("حدّد جهةً من الدليل أولاً")
            with db() as conn:
                entities.set_agreed_wage(
                    conn, ids[r], kv.rate_store(self.agreed_wage.value()),
                    dstr(self.agreed_from), "", self.user["username"])
            info(self, "حُفظت الأجرة المتفق عليها — وسُجّلت بتاريخها.")
            self.refresh()
        except Exception as e:
            err(self, e)

    def _row_selected(self):
        """يملأ حقول السقف بقيم الجهة المحددة في الدليل."""
        try:
            r = self.table.currentRow()
            ids = getattr(self, "_row_ids", [])
            if r < 0 or r >= len(ids):
                self.lbl_credit_who.setText("— لم تُحدَّد جهة —")
                return
            with db(readonly=True) as conn:
                e = entities.get_entity(conn, ids[r])
                c, g = entities.credit_limit(conn, ids[r])
                aw = entities.agreed_wage(conn, ids[r])
                hist = entities.wage_history(conn, ids[r])
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
            r = self.table.currentRow()
            ids = getattr(self, "_row_ids", [])
            if r < 0 or r >= len(ids):
                raise ValueError("حدّد جهةً من الدليل أولاً")
            with db() as conn:
                entities.set_credit_limit(
                    conn, ids[r], self.lim_cash.value(),
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
        r = self.table.currentRow()
        if r < 0 or r >= len(getattr(self, "_row_ids", [])):
            return
        if not ask(self, "حذف الجهة المحددة؟ (يُسمح فقط لمن ليس لها أي حركة)"):
            return
        try:
            with db() as conn:
                entities.delete_entity(conn, self._row_ids[r], self.user["username"])
            info(self, "تم حذف الجهة")
            self.refresh()
        except Exception as e:
            err(self, e)

    def refresh(self):
        from services import credit_guard
        with db() as conn:
            rows, self._row_ids = [], []
            # المتجاوزون يُقرأون دفعةً واحدة لا جهةً جهة — الدليل قد
            # يحوي مئات الأسماء، واستعلامٌ لكل اسم يُبطئ فتح الشاشة.
            over = {r["entity_id"]: r for r in credit_guard.over_limit(conn)}
            for e in entities.list_entities(conn):
                g, c = entities.balances(conn, e["id"])
                if e["entity_type"] == "partner":
                    cg, cc_ = entities.capital_balance(conn, e["id"])
                    extra = (f"رأس مال: {abs(cc_):,.2f} ر / {abs(cg):,.2f} جم "
                            f"— حصة {e['share_percent']:.1f}%")
                elif e["entity_type"] in ("employee", "worker"):
                    extra = (f"{e['job_title'] or '—'} — راتب "
                            f"{e['basic_salary']:,.2f}")
                else:
                    extra = e["vat_number"] or "—"
                lc, lg = entities.credit_limit(conn, e["id"])
                bits = []
                if lc:
                    bits.append(f"{lc:,.0f} ريال")
                if lg:
                    bits.append(f"{kv.g(lg):,.0f} {kv.unit()}")
                limit_txt = " · ".join(bits) if bits else "بلا حدّ"
                if e["id"] in over:
                    limit_txt = "⛔ تجاوز — " + limit_txt
                rows.append((e["name"], entities.TYPE_LABELS[e["entity_type"]],
                            f"{c:,.2f}", f"{g:,.2f}", limit_txt, extra))
                self._row_ids.append(e["id"])
            share_total = entities.partners_share_total(conn)
        fill(self.table, ["الاسم", "النوع", "رصيد نقدي",
                          "رصيد ذهب (جم 18)", "حدّ الائتمان",
                          "بيانات إضافية"], rows)
        w = "" if abs(share_total - 100) < 0.01 or share_total == 0 else \
            "  ⚠ المجموع لا يساوي 100%"
        over_txt = f" | ⛔ متجاوزون للسقف: {len(over)}" if over else ""
        self.summary.setText(
            f"عدد الجهات: {len(rows)} | مجموع حصص الشركاء: "
            f"{share_total:.2f}%{w}{over_txt}")
        self._reload_completer()
        self._load_mode()
