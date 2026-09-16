# -*- coding: utf-8 -*-
"""شاشة السندات: تسديد ذهب (تحويل عيار آلي) ونقد وفرق صافي وخصومات —
توجيه شامل: إلى جهة تعامل (عميل/مورد/شريك/داخلي) أو أي حساب مباشر من
شجرة الحسابات — أداة التسوية المالية والوزنية الوحيدة لسداد الموردين."""
from PyQt5 import QtWidgets

from database.database import db
from models import coa, editing, entities, inventory, vouchers
from models.accounts import list_postable
from services import gold_math, karat_view as kv
from services.accounting_engine import account_balance
from ui.widgets.common import (busy, confirm_post, big_label, posted, date_edit, dstr, enter_chain, err,
                               fill, info, make_table, mspin, reload_combo,
                               search_combo, title_label, wspin)


from ui.widgets.edit_mode import EditModeMixin


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
        self.g_karat.currentIndexChanged.connect(self.recalc_equiv)
        self.g_note = QtWidgets.QLineEdit()
        self.g_note.setPlaceholderText("بيان السطر (اختياري)")
        btn_add_gold = QtWidgets.QPushButton("➕ إضافة سطر ذهب")
        btn_add_gold.clicked.connect(self.add_gold_row)
        gold_box = QtWidgets.QGroupBox(
            "تسديد الذهب (يمكن إضافة عدة أسطر بأعيرة مختلفة)")
        gf = QtWidgets.QFormLayout(gold_box)
        gf.addRow("الوزن المستلم (جم):", self.g_weight)
        gf.addRow("العيار:", self.g_karat)
        gf.addRow("البيان:", self.g_note)
        gf.addRow(self.g_equiv)
        gf.addRow(btn_add_gold)

        # تسديد النقد
        self.c_amount = mspin()
        self.c_target = QtWidgets.QComboBox()
        self.c_target.addItem("الصندوق", "1400")
        self.c_target.addItem("البنك", "1500")
        self.c_note = QtWidgets.QLineEdit()
        self.c_note.setPlaceholderText("بيان السطر (اختياري)")
        btn_add_cash = QtWidgets.QPushButton("➕ إضافة سطر نقد")
        btn_add_cash.clicked.connect(self.add_cash_row)
        cash_box = QtWidgets.QGroupBox(
            "تسديد النقد (يمكن إضافة عدة أسطر)")
        cf = QtWidgets.QFormLayout(cash_box)
        cf.addRow("المبلغ (ريال):", self.c_amount)
        cf.addRow("من/إلى:", self.c_target)
        cf.addRow("البيان:", self.c_note)
        cf.addRow(btn_add_cash)

        # جدول أسطر السند
        self.rows_table = make_table()
        btn_del_row = QtWidgets.QPushButton("حذف السطر المحدد")
        btn_del_row.setObjectName("ghost")
        btn_del_row.clicked.connect(self.del_row)
        self.rows_total = big_label()

        # فرق الصافي والخصومات
        # ضابط صارم: لا يُحتسب أي خصم أو فرق صافي إلا بتفعيل صريح
        # من المستخدم، وإلا فُرضت القيمة صفراً مهما كان محتوى الحقل.
        self.adj_enable = QtWidgets.QCheckBox(
            "تفعيل الخصم / فرق الصافي (إدخال يدوي صريح)")
        self.adj_enable.stateChanged.connect(self.toggle_adjustments)
        self.net_diff = mspin(minimum=-1_000_000_000.0)
        self.disc_cash = mspin()
        self.disc_gold = wspin()
        adj_box = QtWidgets.QGroupBox("فرق الصافي والخصومات")
        af = QtWidgets.QFormLayout(adj_box)
        af.addRow("فرق الصافي (+ يزيد مديونية الطرف النقدية / − يخفضها):",
                  self.net_diff)
        af.addRow(self.adj_enable)
        af.addRow("خصم مسموح نقداً (ريال):", self.disc_cash)
        af.addRow(f"خصم مسموح وزناً ({kv.unit()}):", self.disc_gold)

        self.notes = QtWidgets.QLineEdit()
        btn_save = QtWidgets.QPushButton("ترحيل السند")
        btn_save.clicked.connect(self.save)
        self.init_edit_mode(btn_save, "السند")

        head = QtWidgets.QGridLayout()
        head.addWidget(QtWidgets.QLabel("نوع السند:"), 0, 0)
        head.addWidget(self.kind, 0, 1)
        head.addWidget(QtWidgets.QLabel("التاريخ:"), 0, 2)
        head.addWidget(self.date, 0, 3)
        head.addWidget(QtWidgets.QLabel("الوجهة:"), 1, 0)
        head.addWidget(self.target_mode, 1, 1)
        head.addWidget(self.target_stack, 1, 2, 1, 2)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("السندات والخصومات — توجيه شامل، ميزان مزدوج (ذهب/نقد)"))
        lay.addLayout(head)
        lay.addWidget(self.balances)
        lay.addWidget(self.measure_note)
        grid = QtWidgets.QGridLayout()
        grid.addWidget(gold_box, 0, 0)
        grid.addWidget(cash_box, 0, 1)
        grid.addWidget(adj_box, 1, 0, 1, 2)
        lay.addLayout(grid)
        form = QtWidgets.QFormLayout()
        form.addRow("البيان / ملاحظات:", self.notes)
        enter_chain(self, [self.g_weight, self.c_amount, self.notes],
                    self.save)
        lay.addLayout(form)
        lay.addWidget(QtWidgets.QLabel("أسطر السند:"))
        lay.addWidget(self.rows_table, 1)
        lay.addWidget(btn_del_row)
        lay.addWidget(self.rows_total)
        lay.addWidget(self.edit_banner)
        srow = QtWidgets.QHBoxLayout()
        srow.addWidget(btn_save, 1)
        srow.addWidget(self.btn_cancel_edit)
        lay.addLayout(srow)
        lay.addStretch(1)
        note = QtWidgets.QLabel(
            "لسداد مورد: اختر «حساب مباشر» غير مطلوب — اختر المورد نفسه من "
            "«جهة تعامل» في سند صرف. لعرض سجل السندات أو حذفها: افتح شاشة "
            "(سجل العمليات).")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)

    def kind_changed(self):
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

    def show_balances(self):
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
                return self.entity.currentText()
            return self.account.currentText()
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
                    notes=self.notes.text())
            with busy(self, "جارٍ ترحيل السند…", stage="ترحيل سند"):
                with db() as conn:
                    if self.is_editing:
                        # تعديل **في مكانه**: نفس رقم السند وتاريخه وقيده
                        res = vouchers.update_voucher(
                            conn, self.editing_source_id,
                            self.user["username"],
                            kind=self.kind.currentData(), **kw)
                    else:
                        res = vouchers.create_voucher(
                            conn, self.kind.currentData(), dstr(self.date),
                            self.user["username"], **kw)
            if res.get("in_place"):
                info(self, f"عُدّل السند {res['voucher_no']} في مكانه.\n\n"
                           f"رقم السند وتاريخه وقيده لم تتغيّر.")
                self.end_edit()
                self.rows = []
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
            self.rows = []
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
            self.net_diff.setValue(v.get("net_diff") or 0)
            self.disc_cash.setValue(v.get("disc_cash") or 0)
            self.disc_gold.setValue(v.get("disc_gold") or 0)
            self.notes.setText(v.get("notes") or "")
            self.begin_edit(eid, source_id)
        except Exception as e:
            err(self, e)

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
