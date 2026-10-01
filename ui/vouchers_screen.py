# -*- coding: utf-8 -*-
"""شاشة السندات: تسديد ذهب (تحويل عيار آلي) ونقد وفرق صافي وخصومات —
توجيه شامل: إلى جهة تعامل (عميل/مورد/شريك/داخلي) أو أي حساب مباشر من
شجرة الحسابات — أداة التسوية المالية والوزنية الوحيدة لسداد الموردين."""
from PyQt5 import QtCore, QtWidgets

from database.database import db
from models import coa, editing, entities, inventory, vouchers
from models.accounts import list_postable
from services import drafts, gold_math, karat_view as kv
from services.accounting_engine import account_balance
from ui.widgets.common import (busy, confirm_post, big_label, posted, date_edit, dstr, enter_chain, err,
                               fill, info, make_table, mspin, reload_combo,
                               search_combo, title_label, wspin)


from ui.widgets.edit_mode import EditModeMixin

DRAFT_KEY = "vouchers"


def _sub(t):
    lbl = QtWidgets.QLabel(t)
    lbl.setObjectName("cardSub")
    lbl.setAlignment(QtCore.Qt.AlignCenter)
    return lbl


class VouchersScreen(EditModeMixin, QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user

        self.kind = QtWidgets.QComboBox()
        self.kind.addItem("سند قبض (نستلم)", "receipt")
        self.kind.addItem("سند صرف (ندفع)", "payment")
        self.kind.currentIndexChanged.connect(self.kind_changed)

        self.target_mode = QtWidgets.QComboBox()
        self.target_mode.addItem("جهة تعامل (عميل/مورد/شريك/داخلي)", "entity")
        self.target_mode.addItem("حساب مباشر من شجرة الحسابات", "account")
        self.target_mode.currentIndexChanged.connect(self.mode_changed)

        self.entity_combo = search_combo("اكتب اسم الجهة…")
        self.entity_combo.currentIndexChanged.connect(self.show_balances)
        self.account_combo = search_combo("اكتب رقم الحساب أو اسمه…")
        self.account_combo.currentIndexChanged.connect(self.show_balances)
        self.target_stack = QtWidgets.QStackedWidget()
        self.target_stack.addWidget(self.entity_combo)
        self.target_stack.addWidget(self.account_combo)

        self.date = date_edit()
        self.balances = big_label()
        self.measure_note = QtWidgets.QLabel()
        self.measure_note.setObjectName("warn")
        self.measure_note.setWordWrap(True)

        # ── شبكة أسطر السند: تسمح بأعيرة مختلفة ونقد في السند الواحد ──
        self.rows = []

        self.g_weight = wspin()
        self.g_karat = QtWidgets.QComboBox()
        # الأعيرة من BOX_CODE فيظهر أي عيار يُضاف مستقبلاً تلقائياً
        for k in sorted(inventory.BOX_CODE):
            self.g_karat.addItem(f"عيار {k}", k)
        self.g_equiv = big_label(f"المكافئ بـ{kv.label()}: 0.00 جم")
        self.g_weight.valueChanged.connect(self.recalc_equiv)
        _ki = self.g_karat.findData(kv.active())
        if _ki >= 0:
            self.g_karat.setCurrentIndex(_ki)
        self.g_karat.currentIndexChanged.connect(self.recalc_equiv)
        self.g_note = QtWidgets.QLineEdit()
        self.g_note.setPlaceholderText("بيان السطر (اختياري)")
        btn_add_gold = QtWidgets.QPushButton("➕ إضافة سطر ذهب")
        btn_add_gold.clicked.connect(self.add_gold_row)
        # ══ الترتيب: صفٌّ للسند · لوحتا الذهب والنقد متجاورتين · صفُّ
        # الخصومات بخاناتٍ صغيرة · ثم الجدول والترحيل — كلّه أمام العين
        # بلا تمرير ══
        gold_box = QtWidgets.QGroupBox("🟡 الذهب")
        gg = QtWidgets.QGridLayout(gold_box)
        gg.addWidget(_sub("الوزن الفعلي (جم)"), 0, 0)
        gg.addWidget(_sub("العيار"), 0, 1)
        gg.addWidget(_sub("البيان"), 0, 2)
        gg.addWidget(self.g_weight, 1, 0)
        gg.addWidget(self.g_karat, 1, 1)
        gg.addWidget(self.g_note, 1, 2)
        gg.addWidget(self.g_equiv, 2, 0, 1, 2)
        gg.addWidget(btn_add_gold, 2, 2)
        gg.setColumnStretch(0, 2)
        gg.setColumnStretch(1, 1)
        gg.setColumnStretch(2, 3)

        # تسديد النقد
        self.c_amount = mspin()
        self.c_target = QtWidgets.QComboBox()
        self.c_target.addItem("الصندوق", "1400")
        self.c_target.addItem("البنك", "1500")
        self.c_note = QtWidgets.QLineEdit()
        self.c_note.setPlaceholderText("بيان السطر (اختياري)")
        btn_add_cash = QtWidgets.QPushButton("➕ إضافة سطر نقد")
        btn_add_cash.clicked.connect(self.add_cash_row)
        cash_box = QtWidgets.QGroupBox("💵 النقد")
        cg = QtWidgets.QGridLayout(cash_box)
        cg.addWidget(_sub("المبلغ (ريال)"), 0, 0)
        cg.addWidget(_sub("من / إلى"), 0, 1)
        cg.addWidget(_sub("البيان"), 0, 2)
        cg.addWidget(self.c_amount, 1, 0)
        cg.addWidget(self.c_target, 1, 1)
        cg.addWidget(self.c_note, 1, 2)
        cg.addWidget(btn_add_cash, 2, 2)
        cg.setColumnStretch(0, 2)
        cg.setColumnStretch(1, 1)
        cg.setColumnStretch(2, 3)

        # جدول أسطر السند
        self.rows_table = make_table()
        btn_del_row = QtWidgets.QPushButton("حذف السطر المحدد")
        btn_del_row.setObjectName("ghost")
        btn_del_row.clicked.connect(self.del_row)
        self.rows_total = big_label()

        # فرق الصافي والخصومات — ضابط صارم: لا يُحتسب شيءٌ منها إلا
        # بتفعيل صريح، وإلا فُرضت القيمة صفراً مهما كان في الخانة.
        self.adj_enable = QtWidgets.QCheckBox("تفعيل الخصم والفرق")
        self.adj_enable.stateChanged.connect(self.toggle_adjustments)
        self.net_diff = mspin(minimum=-1_000_000_000.0)
        self.net_diff.setToolTip("+ يزيد مديونية الطرف النقدية / − يخفضها")
        self.disc_cash = mspin()
        self.disc_gold = wspin()
        self.notes = QtWidgets.QLineEdit()
        self.notes.setPlaceholderText("البيان / ملاحظات السند")
        adj = QtWidgets.QHBoxLayout()
        adj.addWidget(self.adj_enable)
        for lbl, wd in (("مسموح نقداً:", self.disc_cash),
                        (f"خصم ذهباً ({kv.unit()}):", self.disc_gold),
                        ("فرق صافي:", self.net_diff)):
            adj.addWidget(QtWidgets.QLabel(lbl))
            wd.setFixedWidth(130)
            adj.addWidget(wd)
        adj.addSpacing(12)
        adj.addWidget(self.notes, 1)
        # ══ صرفٌ لعاملٍ أو موظف ══ يُحمَّل أجراً/راتباً (مصروفاً) أو يبقى
        # سلفةً/سداداً على حسابه. الافتراضي يُقرأ من رصيده: من له أجرٌ
        # مستحقٌّ مُرحَّل من المسير يُسدَّد له، ومن لا فيُحمَّل مصروفاً.
        self.staff_exp = QtWidgets.QCheckBox(
            "يُحمَّل أجراً مصروفاً (مصروفات العمال / رواتب الإدارة)")
        self.staff_exp.setToolTip(
            "سند صرف لعامل أو موظف: إن فُعِّل يُحمَّل المبلغ النقدي مصروفاً"
            " — «مصروفات العمال» 5710 للعامل و«رواتب الإدارة» 5700 للموظف —"
            " ويظهر في كشف حسابه مدفوعاً ومُحمَّلاً.\nوإن لم يُفعَّل يبقى"
            " على حسابه: سلفةً، أو سداداً لراتبٍ رُحِّل من مسير الرواتب"
            " (فلا يُحمَّل مرتين).")
        self.staff_exp.setVisible(False)
        self._staff_touched = False
        self.staff_exp.clicked.connect(
            lambda *_: setattr(self, "_staff_touched", True))

        btn_save = QtWidgets.QPushButton("✔ ترحيل السند")
        btn_save.clicked.connect(self.save)
        self.init_edit_mode(btn_save, "السند")

        head = QtWidgets.QHBoxLayout()
        head.addWidget(QtWidgets.QLabel("نوع السند:"))
        head.addWidget(self.kind)
        head.addWidget(QtWidgets.QLabel("التاريخ:"))
        head.addWidget(self.date)
        head.addWidget(QtWidgets.QLabel("الوجهة:"))
        head.addWidget(self.target_mode)
        head.addWidget(self.target_stack, 1)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("السندات والخصومات — ميزان مزدوج (ذهب/نقد)"))
        lay.addLayout(head)
        info_row = QtWidgets.QHBoxLayout()
        info_row.addWidget(self.balances, 1)
        info_row.addWidget(self.measure_note)
        lay.addLayout(info_row)
        panels = QtWidgets.QHBoxLayout()
        panels.addWidget(gold_box, 1)
        panels.addWidget(cash_box, 1)
        lay.addLayout(panels)
        lay.addLayout(adj)
        lay.addWidget(self.staff_exp)
        enter_chain(self, [self.g_weight, self.c_amount, self.notes],
                    self.save)
        lay.addWidget(self.rows_table, 1)
        trow = QtWidgets.QHBoxLayout()
        trow.addWidget(self.rows_total, 1)
        trow.addWidget(btn_del_row)
        lay.addLayout(trow)
        # يظهر حين يُستعاد سند لم يُرحَّل — فلا يظن المستخدم أن أسطراً
        # ظهرت من تلقاء نفسها.
        self.draft_note = QtWidgets.QLabel("")
        self.draft_note.setObjectName("ok")
        self.draft_note.setWordWrap(True)
        self.draft_note.setVisible(False)
        lay.addWidget(self.draft_note)
        lay.addWidget(self.edit_banner)
        srow = QtWidgets.QHBoxLayout()
        srow.addWidget(btn_save, 1)
        srow.addWidget(self.btn_cancel_edit)
        lay.addLayout(srow)
        self.toggle_adjustments()

    def kind_changed(self):
        self._sync_staff()
        receipt = self.kind.currentData() == "receipt"
        self.disc_cash.setEnabled(receipt)
        self.disc_gold.setEnabled(receipt)
        if not receipt:
            self.disc_cash.setValue(0)
            self.disc_gold.setValue(0)

    def mode_changed(self):
        self.target_stack.setCurrentIndex(
            0 if self.target_mode.currentData() == "entity" else 1)
        self.show_balances()
        self._apply_measurement()

    def recalc_equiv(self):
        """المكافئ المعروض بعيار المصنع.

        **الوزن المستلم لا يُحوَّل**: هو وزن حقيقي بعياره المختار في
        الحقل المجاور (كسر 21 مثلاً)، لا مكافئ. المكافئ وحده هو الذي
        يُقرأ بوحدة المصنع.
        """
        karat = self.g_karat.currentData() or 18
        eq = gold_math.to_base_karat(self.g_weight.value(), karat)
        self.g_equiv.setText(f"المكافئ بـ{kv.label()}: {kv.g(eq):.2f} جم")

    def _current_target(self):
        if self.target_mode.currentData() == "entity":
            return "entity", self.entity_combo.currentData()
        return "account", self.account_combo.currentData()

    def _apply_measurement(self):
        """يربط حقول النقد/الذهب بنوع قياس الحساب المختار: حساب نقدي
        فقط (CASH_ONLY) يُعطَّل فيه إدخال الوزن، والعكس صحيح."""
        mode, val = self._current_target()
        measure = "both"
        if val is not None:
            with db() as conn:
                if mode == "entity":
                    ent = entities.get_entity(conn, val)
                    if ent:
                        measure = coa.measurement_of(conn, ent["account_id"])
                else:
                    measure = coa.measurement_of(conn, val)
        gold_ok = measure in ("gold", "both")
        cash_ok = measure in ("cash", "both")
        for w in (self.g_weight, self.g_karat):
            w.setEnabled(gold_ok)
        self.c_amount.setEnabled(cash_ok)
        if not gold_ok:
            self.g_weight.setValue(0)
        if not cash_ok:
            self.c_amount.setValue(0)
        self.measure_note.setText(
            "" if measure == "both" else
            ("هذا الحساب نقدي فقط (CASH_ONLY) — إدخال الوزن معطَّل."
             if measure == "cash" else
             "هذا الحساب وزني فقط (GOLD_ONLY) — إدخال المبلغ معطَّل."))

    def _sync_staff(self):
        """خيار «يُحمَّل مصروفاً» لسند صرفٍ لعاملٍ أو موظف وحده."""
        mode, val = self._current_target()
        on = False
        dflt = False
        if mode == "entity" and val is not None \
                and self.kind.currentData() == "payment":
            try:
                with db(readonly=True) as conn:
                    e = entities.get_entity(conn, val)
                    on = bool(e) and e["entity_type"] in ("worker",
                                                          "employee")
                    if on:
                        dflt = vouchers.staff_expense_default(conn, val)
            except Exception:
                on = False
        self.staff_exp.setVisible(on)
        if on and not self._staff_touched:
            self.staff_exp.setChecked(dflt)

    def show_balances(self):
        self._sync_staff()
        mode, val = self._current_target()
        if val is None:
            self.balances.setText("")
            return
        with db() as conn:
            if mode == "entity":
                g, c = entities.balances(conn, val)
            else:
                g, c = account_balance(conn, val)
        self.balances.setText(
            f"الرصيد الحالي — ذهب: {kv.g(g):,.2f} جم {kv.label()} "
            f"({'مدين' if g >= 0 else 'دائن'}) | "
            f"نقد: {c:,.2f} ريال ({'مدين' if c >= 0 else 'دائن'})")

    def add_gold_row(self):
        """يضيف سطر ذهب بعياره الخاص إلى أسطر السند."""
        try:
            wt = round(self.g_weight.value(), 2)
            if wt <= 0:
                raise ValueError("أدخل وزناً أكبر من صفر")
            kt = self.g_karat.currentData()
            self.rows.append({"kind": "gold", "weight": wt, "karat": kt,
                              "amount": 0.0,
                              "notes": self.g_note.text().strip()})
            self.g_weight.setValue(0)
            self.g_note.clear()
            self.render_rows()
        except Exception as e:
            err(self, e)

    def add_cash_row(self):
        """يضيف سطر نقد إلى أسطر السند."""
        try:
            amt = round(self.c_amount.value(), 2)
            if amt <= 0:
                raise ValueError("أدخل مبلغاً أكبر من صفر")
            self.rows.append({"kind": "cash", "weight": 0.0, "karat": 0,
                              "amount": amt,
                              "notes": self.c_note.text().strip()})
            self.c_amount.setValue(0)
            self.c_note.clear()
            self.render_rows()
        except Exception as e:
            err(self, e)

    def del_row(self):
        i = self.rows_table.currentRow()
        if 0 <= i < len(self.rows):
            self.rows.pop(i)
            self.render_rows()

    def render_rows(self):
        data, tg, tc = [], 0.0, 0.0
        for r in self.rows:
            if r["kind"] == "gold":
                eq = gold_math.to_base_karat(r["weight"], r["karat"])
                tg += eq
                data.append(("ذهب", f"{r['weight']:,.2f}",
                             f"عيار {r['karat']}",
                             f"{kv.g(eq):,.2f}", "—", r["notes"] or "—"))
            else:
                tc += r["amount"]
                data.append(("نقد", "—", "—", "—",
                             f"{r['amount']:,.2f}", r["notes"] or "—"))
        fill(self.rows_table, ["النوع", "الوزن الفعلي", "العيار",
                               f"المكافئ ع{kv.active()}", "المبلغ",
                               "البيان"], data)
        self.rows_total.setText(
            f"إجمالي السند — ذهب: {kv.g(tg):,.2f} جم {kv.label()}   |   "
            f"نقد: {tc:,.2f} ريال   ({len(self.rows)} سطر)")

    def toggle_adjustments(self):
        """تعطيل حقول الخصم وفرق الصافي وتصفيرها ما لم تُفعَّل صراحةً."""
        on = self.adj_enable.isChecked()
        for w in (self.net_diff, self.disc_cash, self.disc_gold):
            w.setEnabled(on)
            if not on:
                w.setValue(0)
        if on:
            self.kind_changed()      # الخصم المسموح للقبض وحده

    def adj_values(self):
        """القيم المعتمدة للترحيل — أصفار ما لم يُفعّلها المستخدم."""
        if not self.adj_enable.isChecked():
            return 0.0, 0.0, 0.0
        return (round(self.net_diff.value(), 2),
                round(self.disc_cash.value(), 2),
                round(kv.store(self.disc_gold.value()), 2))

    def _target_label(self):
        """اسم الجهة أو الحساب المختار — لعرضه في تأكيد الترحيل."""
        try:
            mode, _val = self._current_target()
            if mode == "entity":
                return self.entity_combo.currentText()
            return self.account_combo.currentText()
        except Exception:
            return "—"

    def save(self):
        try:
            # التحقق من حياة القيد **قبل** فتح المعاملة — لا داخلها
            self.verify_edit_target()
            mode, val = self._current_target()
            if val is None:
                raise ValueError("اختر جهة التعامل أو الحساب المباشر")
            # الأسطر المضافة للجدول هي مصدر السند. وإن لم يُضف المستخدم
            # سطراً، تُستخدم القيم المكتوبة في الحقول مباشرة (سطر واحد).
            nd, dc, dg = self.adj_values()
            rows = list(self.rows)
            if not rows:
                if self.g_weight.value() > 0:
                    rows.append({"kind": "gold",
                                 "weight": self.g_weight.value(),
                                 "karat": self.g_karat.currentData(),
                                 "notes": self.g_note.text().strip()})
                if self.c_amount.value() > 0:
                    rows.append({"kind": "cash",
                                 "amount": self.c_amount.value(),
                                 "notes": self.c_note.text().strip()})
            if not rows and not any((nd, dc, dg)):
                raise ValueError("أضف سطراً واحداً على الأقل في السند")
            # تأكيد الترحيل قبل إحداث أي أثر في الحسابات
            k_label = ("سند قبض" if self.kind.currentData() == "receipt"
                       else "سند صرف")
            tg = sum(float(r.get("weight") or 0) for r in rows
                     if r.get("kind") == "gold")
            tc = sum(float(r.get("amount") or 0) for r in rows
                     if r.get("kind") == "cash")
            if not confirm_post(
                    self,
                    f"{k_label}\n\n"
                    f"الجهة: {self._target_label()}\n"
                    f"الذهب: {tg:,.2f} جم\n"
                    f"النقد: {tc:,.2f} ريال\n"
                    f"التاريخ: {dstr(self.date)}"):
                return
            kw = dict(
                    entity_id=val if mode == "entity" else None,
                    account_id=val if mode == "account" else None,
                    rows=rows or None,
                    cash_account_code=self.c_target.currentData(),
                    net_diff=nd, disc_cash=dc, disc_gold=dg,
                    notes=self.notes.text(),
                    staff_expense=(self.staff_exp.isChecked()
                                   if not self.staff_exp.isHidden()
                                   else None))
            with busy(self, "جارٍ ترحيل السند…", stage="ترحيل سند"):
                with db() as conn:
                    if self.is_editing:
                        # تعديل **في مكانه**: نفس رقم السند وتاريخه وقيده
                        # التاريخ يُمرَّر كما هو في الحقل: إن غيّره
                        # المستخدم انتقل السند وقيده إليه.
                        res = vouchers.update_voucher(
                            conn, self.editing_source_id,
                            self.user["username"],
                            kind=self.kind.currentData(),
                            voucher_date=dstr(self.date), **kw)
                    else:
                        res = vouchers.create_voucher(
                            conn, self.kind.currentData(), dstr(self.date),
                            self.user["username"], **kw)
            if res.get("in_place"):
                info(self, f"عُدّل السند {res['voucher_no']} في مكانه.\n\n"
                           + (f"رقم السند ثابت، وتاريخه نُقل من "
                              f"{res['moved_date'][0]} إلى "
                              f"{res['moved_date'][1]} — وقيدُه معه."
                              if res.get("moved_date")
                              else "رقم السند وتاريخه وقيده لم تتغيّر."))
                self.end_edit()
                self._staff_touched = False
                self.rows = []
                self._drop_draft()
                self.render_rows()
                self.refresh()
                return
            posted(self, f"تم ترحيل السند {res['voucher_no']} إلى "
                         f"{res['target_label']} (قيد رقم {res['entry_id']})"
                         + (" — بديلاً عن السند السابق بعد عكس قيده"
                            if res.get("replaced_id") else ""),
                   "vouchers", res["id"],
                   editing=bool(res.get("replaced_id")))
            self.end_edit()
            self._staff_touched = False
            self.rows = []
            self._drop_draft()
            self.adj_enable.setChecked(False)
            self.toggle_adjustments()
            self.render_rows()
            self.g_note.clear()
            self.c_note.clear()
            for w in (self.g_weight, self.c_amount, self.net_diff,
                      self.disc_cash, self.disc_gold):
                w.setValue(0)
            self.notes.clear()
            self.refresh()
        except Exception as e:
            err(self, e)

    def load_document(self, source_id):
        """يفتح سنداً قائماً للتعديل ويعبّئ كل حقوله."""
        try:
            with db() as conn:
                v = editing.load_document(conn, "vouchers", source_id)
                if not v:
                    raise ValueError("السند غير موجود")
                eid = editing.entry_of(conn, "vouchers", source_id)
            self.refresh()
            i = self.kind.findData(v["kind"])
            if i >= 0:
                self.kind.setCurrentIndex(i)
            # الأعمدة الفعلية: customer_id (جهة التعامل) و target_account_id
            if v.get("customer_id"):
                self.target_mode.setCurrentIndex(0)
                i = self.entity_combo.findData(v["customer_id"])
                if i >= 0:
                    self.entity_combo.setCurrentIndex(i)
            elif v.get("target_account_id"):
                self.target_mode.setCurrentIndex(1)
                i = self.account_combo.findData(v["target_account_id"])
                if i >= 0:
                    self.account_combo.setCurrentIndex(i)
            # ══ الأسطر تُحمَّل في الجدول لا في خانة الإدخال ══
            # وضعها في خانة الإدخال يجعل السند يبدو سطراً واحداً مهما
            # كان عدد أسطره، فيفقد المستخدم رؤية ما سجّله فعلاً.
            rows = []
            with db() as conn:
                for ln in conn.execute(
                        "SELECT * FROM voucher_lines WHERE voucher_id=?"
                        " ORDER BY id", (source_id,)):
                    if ln["line_kind"] == "gold":
                        rows.append({
                            "kind": "gold",
                            "weight": float(ln["gold_weight"] or 0),
                            "karat": int(ln["gold_karat"] or 18),
                            "equiv": float(ln["gold_equiv18"] or 0),
                            "amount": 0.0,
                            "notes": ln["line_notes"] or ""})
                    else:
                        rows.append({
                            "kind": "cash", "weight": 0.0, "karat": None,
                            "equiv": 0.0,
                            "amount": float(ln["cash_amount"] or 0),
                            "notes": ln["line_notes"] or ""})
            self.rows = rows
            self.render_rows()
            # خانات الإدخال تبقى فارغة: الأسطر معروضة في الجدول
            self.g_weight.setValue(0)
            self.c_amount.setValue(0)
            i = self.g_karat.findData(v.get("gold_karat") or 18)
            if i >= 0:
                self.g_karat.setCurrentIndex(i)
            # الخصم والفرق مقفلان ما لم يُفعَّلا — والسند المفتوح للتعديل
            # يحملهما فيُفعَّلان أولاً، وإلا صُفّرا عند الحفظ بصمت
            self._staff_touched = True
            self.staff_exp.setChecked(bool(v.get("staff_expense")))
            has_adj = any(v.get(k) for k in ("net_diff", "disc_cash",
                                             "disc_gold"))
            self.adj_enable.setChecked(bool(has_adj))
            self.net_diff.setValue(v.get("net_diff") or 0)
            self.disc_cash.setValue(v.get("disc_cash") or 0)
            self.disc_gold.setValue(kv.g(v.get("disc_gold") or 0))
            self.notes.setText(v.get("notes") or "")
            self.begin_edit(eid, source_id)
        except Exception as e:
            err(self, e)

    # ══════════════════════════════════════════════════════════════
    #  مسوّدة السند غير المرحَّل
    #  الشرح كاملاً في `services/drafts.py`.
    # ══════════════════════════════════════════════════════════════

    def draft_state(self):
        """أسطر السند ورأسه — والأوزان بأعيارها الفعلية كما أُدخلت."""
        if getattr(self, "is_editing", False):
            return None          # وضع التعديل لا يُحفظ مسوّدةً
        if not self.rows:
            return None
        return {
            "kind": self.kind.currentData(),
            "target_mode": self.target_mode.currentData(),
            "entity_id": self.entity_combo.currentData(),
            "account_id": self.account_combo.currentData(),
            "date": dstr(self.date),
            "notes": self.notes.text().strip(),
            "rows": [dict(r) for r in self.rows],
        }

    def apply_draft(self, d):
        if not d or not d.get("rows"):
            return False
        for combo, key in ((self.kind, "kind"),
                           (self.target_mode, "target_mode"),
                           (self.entity_combo, "entity_id"),
                           (self.account_combo, "account_id")):
            i = combo.findData(d.get(key))
            if i >= 0:
                combo.setCurrentIndex(i)
        if d.get("date"):
            self.date.setDate(QtCore.QDate.fromString(d["date"],
                                                      "yyyy-MM-dd"))
        self.notes.setText(d.get("notes") or "")
        self.rows = [dict(r) for r in d["rows"]]
        self.render_rows()
        return True

    def _restore_draft(self):
        if getattr(self, "_draft_done", False):
            return
        self._draft_done = True
        try:
            if self.apply_draft(drafts.load(DRAFT_KEY,
                                            self.user.get("username"))):
                self.draft_note.setText(
                    "↩ استُعيد سند لم يُرحَّل بعد — أكمله أو احذف أسطره.")
                self.draft_note.setVisible(True)
        except Exception:
            pass

    def _drop_draft(self):
        """يمحو المسوّدة — فور الترحيل."""
        try:
            drafts.clear(DRAFT_KEY, self.user.get("username"))
            self.draft_note.setVisible(False)
        except Exception:
            pass

    def on_close(self):
        """يُستدعى من `LazyScreen.release` عند مغادرة الشاشة."""
        try:
            drafts.save(DRAFT_KEY, self.user.get("username"),
                        self.draft_state())
        except Exception:
            pass

    def refresh(self):
        with db() as conn:
            reload_combo(self.entity_combo, entities.list_entities(conn),
                        lambda r: (("🏭 " if r["is_internal"] else
                                   f"[{entities.TYPE_LABELS[r['entity_type']]}] ")
                                  + r["name"]))
            reload_combo(self.account_combo, list_postable(conn),
                        lambda r: f"{r['code']} — {r['name']}")
        self.show_balances()
        self._apply_measurement()
        self.kind_changed()
        self.recalc_equiv()
        self._restore_draft()
