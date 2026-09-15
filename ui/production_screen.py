# -*- coding: utf-8 -*-
"""الإنتاج والتوريد — إدخال مجمّع مع تفكيك أوزان رقم التشغيل:
الذهب | الفصوص | الأحجار | الأحجار بعد الخصم | الوزن المقيد (الأثر
المالي والمخزني) | الذهب القائم (للإحصاء فقط، بلا أثر محاسبي)."""
from PyQt5 import QtCore, QtWidgets

import config
from database.database import db
from models import editing, inventory
from services import gold_math
from ui.widgets.common import (confirm_post, posted, ask, big_label, date_edit, dstr, enter_chain,
                               err, fill, info, make_table, mspin,
                               title_label, wspin)

COLS = ["رقم الموديل", "رقم التشغيل", "النوع", "الذهب", "الفصوص", "الأحجار",
        "الأحجار بعد الخصم", "نسبة الخصم", "الوزن المقيد", "الذهب القائم",
        "الأجر/جم", "ملاحظات"]


class DiscountDialog(QtWidgets.QDialog):
    """نافذة صغيرة لتحديد نسبة الخصم التجاري على الأحجار."""

    def __init__(self, parent, current_rate):
        super().__init__(parent)
        self.setWindowTitle("نسبة الخصم على الأحجار")
        self.rate = QtWidgets.QDoubleSpinBox()
        self.rate.setDecimals(1)
        self.rate.setRange(0, 100)
        self.rate.setSuffix(" %")
        self.rate.setValue(current_rate * 100)
        form = QtWidgets.QFormLayout(self)
        form.addRow(QtWidgets.QLabel(
            "نسبة الخصم التجاري المخصومة من وزن الأحجار.\n"
            "الأحجار بعد الخصم = وزن الأحجار × (1 − النسبة)."))
        form.addRow("نسبة الخصم:", self.rate)
        box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def value(self):
        return self.rate.value() / 100.0


from ui.widgets.edit_mode import EditModeMixin


class ProductionScreen(EditModeMixin, QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.batch = []
        self.rate = config.STONE_DISCOUNT_RATE

        # رقم الموديل: تصنيف وصفي يجمع الأطقم المتشابهة تصميماً.
        # يُدخَل قبل رقم التشغيل ويبقى ثابتاً لأطقم الدفعة الواحدة،
        # فيُدخل مرة ويُربط بكل ما بعده حتى يُغيّره المستخدم.
        self.model_no = QtWidgets.QComboBox()
        self.model_no.setEditable(True)
        self.model_no.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.model_no.lineEdit().setPlaceholderText("رقم الموديل")
        self.wo_no = QtWidgets.QLineEdit()
        self.gold = wspin()
        self.small = wspin()
        self.big = wspin()
        self.after = QtWidgets.QLabel("0.000")
        self.after.setObjectName("big")
        self.btn_rate = QtWidgets.QPushButton(f"خصم {self.rate*100:.0f}%")
        self.btn_rate.setObjectName("ghost")
        self.btn_rate.setMaximumWidth(110)
        self.btn_rate.clicked.connect(self.edit_rate)
        self.wage = mspin()
        self.wage.setValue(config.DEFAULT_WAGE_PER_GRAM)
        self.notes = QtWidgets.QLineEdit()
        self.notes.setMaximumWidth(150)
        self.reg_label = big_label("الوزن المقيد: 0.000 جم")
        self.standing_label = QtWidgets.QLabel(
            "الذهب القائم: 0.000 جم (للإحصاء فقط)")
        self.standing_label.setObjectName("cardSub")
        for w in (self.gold, self.small, self.big):
            w.valueChanged.connect(self.recalc)

        btn_add = QtWidgets.QPushButton("+ إضافة")
        btn_add.clicked.connect(self.add_row)

        def _lbl(t):
            l = QtWidgets.QLabel(t)
            l.setObjectName("cardSub")
            return l

        # كل خانات رقم التشغيل في صف أفقي واحد لإدخال سريع
        def col(label, widget, w=None):
            c = QtWidgets.QVBoxLayout()
            c.setSpacing(2)
            c.addWidget(_lbl(label))
            if w:
                widget.setMaximumWidth(w)
            c.addWidget(widget)
            return c

        after_box = QtWidgets.QHBoxLayout()
        after_box.setSpacing(2)
        after_box.addWidget(self.after)
        after_box.addWidget(self.btn_rate)
        after_w = QtWidgets.QWidget()
        after_w.setLayout(after_box)

        entry_row = QtWidgets.QHBoxLayout()
        entry_row.addLayout(col("رقم الموديل", self.model_no, 120))
        entry_row.addLayout(col("رقم التشغيل", self.wo_no, 130))
        entry_row.addLayout(col("الذهب", self.gold, 95))
        entry_row.addLayout(col("الفصوص", self.small, 85))
        entry_row.addLayout(col("الأحجار", self.big, 85))
        entry_row.addLayout(col("بعد الخصم", after_w, 170))
        entry_row.addLayout(col("الأجر/جم", self.wage, 90))
        entry_row.addLayout(col("ملاحظات", self.notes, 150))
        entry_row.addLayout(col("", btn_add, 110))

        totals_row = QtWidgets.QHBoxLayout()
        totals_row.addWidget(self.reg_label)
        totals_row.addStretch(1)
        totals_row.addWidget(self.standing_label)

        entry_box = QtWidgets.QGroupBox(
            "إدخال طقم — الوزن المقيد وحده صاحب الأثر المالي والمخزني")
        ebl = QtWidgets.QVBoxLayout(entry_box)
        ebl.addLayout(entry_row)
        ebl.addLayout(totals_row)

        self.grid = make_table()
        btn_edit_row = QtWidgets.QPushButton("✎ تعديل السطر المحدد")

        btn_edit_row.setToolTip("يفتح كل خانات السطر لتصحيحها")

        btn_edit_row.clicked.connect(self.edit_row)
        btn_remove = QtWidgets.QPushButton("حذف السطر المحدد")
        btn_remove.setObjectName("ghost")
        btn_remove.clicked.connect(self.remove_row)
        self.date = date_edit()
        self.totals = big_label()
        btn_post = QtWidgets.QPushButton("ترحيل الدفعة (قيد محاسبي مجمّع واحد)")
        btn_post.clicked.connect(self.post_batch)
        self.init_edit_mode(btn_post, "التوريد")

        batch_box = QtWidgets.QGroupBox("الدفعة الحالية — قبل الترحيل")
        bl = QtWidgets.QVBoxLayout(batch_box)
        bl.addWidget(self.grid)
        r2 = QtWidgets.QHBoxLayout()
        r2.addWidget(btn_edit_row)
        r2.addWidget(btn_remove)
        r2.addStretch(1)
        r2.addWidget(QtWidgets.QLabel("تاريخ الترحيل:"))
        r2.addWidget(self.date)
        bl.addLayout(r2)
        bl.addWidget(self.totals)
        bl.addWidget(self.edit_banner)
        prow = QtWidgets.QHBoxLayout()
        prow.addWidget(btn_post, 1)
        prow.addWidget(self.btn_cancel_edit)
        bl.addLayout(prow)

        self.tazeena_label = big_label()
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("الإنتاج والتوريد — خزينة التصنيع والذهب المشغول"))
        lay.addWidget(self.tazeena_label)
        # Enter ينقل للخانة التالية، وعند آخر خانة يضيف السطر ويعود لأولها
        # رقم الموديل أول السلسلة: Enter ينقل لرقم التشغيل
        enter_chain(self, [self.model_no, self.wo_no, self.gold,
                           self.small, self.big,
                           self.wage, self.notes], self.add_row)
        lay.addWidget(entry_box)
        lay.addWidget(batch_box, 1)

    def edit_rate(self):
        dlg = DiscountDialog(self, self.rate)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self.rate = dlg.value()
            self.btn_rate.setText(f"خصم {self.rate*100:.0f}%")
            self.recalc()

    def recalc(self):
        after = gold_math.stones_after_discount(self.big.value(), self.rate)
        reg = gold_math.registered_weight(self.gold.value(), self.small.value(),
                                          self.big.value(), self.rate)
        standing = gold_math.standing_gold(self.gold.value(), self.small.value(),
                                           self.big.value())
        self.after.setText(f"{after:.2f}")
        self.reg_label.setText(f"الوزن المقيد: {reg:.2f} جم")
        self.standing_label.setText(
            f"الذهب القائم: {standing:.2f} جم (للإحصاء فقط — بلا أثر محاسبي)")

    def add_row(self):
        try:
            wo_no = self.wo_no.text().strip()
            if not wo_no:
                raise ValueError("أدخل رقم التشغيل")
            if any(b["wo_no"] == wo_no for b in self.batch):
                raise ValueError(f"رقم التشغيل {wo_no} مضاف مسبقاً في هذه الدفعة")
            if self.gold.value() + self.small.value() + self.big.value() <= 0:
                raise ValueError("أدخل وزناً واحداً على الأقل")
            self.batch.append({
                "model_no": self.model_no.currentText().strip(),
                "wo_no": wo_no, "gold": self.gold.value(),
                "small_stones": self.small.value(),
                "big_stones": self.big.value(), "discount_rate": self.rate,
                "wage_per_gram": self.wage.value(),
                "notes": self.notes.text().strip()})
            self.wo_no.clear()
            for w in (self.gold, self.small, self.big):
                w.setValue(0)
            self.wage.setValue(config.DEFAULT_WAGE_PER_GRAM)
            self.notes.clear()
            self.wo_no.setFocus()
            self.render_batch()
        except Exception as e:
            err(self, e)

    def edit_row(self):
        """يعدّل بيانات السطر المحدد في الدفعة قبل الترحيل.

        يفتح كل خانات السطر (الموديل · رقم التشغيل · الأوزان · النسبة
        · الأجر · الملاحظات) لتصحيحها دفعةً واحدة.
        """
        r = self.grid.currentRow()
        if not (0 <= r < len(self.batch)):
            err(self, "اختر سطراً من الجدول أولاً")
            return
        b = self.batch[r]
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(f"تعديل السطر — {b['wo_no']}")
        dlg.setMinimumWidth(420)
        w_model = QtWidgets.QLineEdit(str(b.get("model_no") or ""))
        w_no = QtWidgets.QLineEdit(str(b["wo_no"]))
        w_gold, w_small, w_big = wspin(), wspin(), wspin()
        w_gold.setValue(b["gold"])
        w_small.setValue(b["small_stones"])
        w_big.setValue(b["big_stones"])
        w_rate = mspin()
        w_rate.setValue(b["discount_rate"] * 100)
        w_wage = mspin()
        w_wage.setValue(b.get("wage_per_gram", 0))
        w_notes = QtWidgets.QLineEdit(str(b.get("notes") or ""))
        prev = QtWidgets.QLabel("")

        def _calc():
            reg = gold_math.registered_weight(
                w_gold.value(), w_small.value(), w_big.value(),
                w_rate.value() / 100.0)
            prev.setText(f"الوزن المقيد: {reg:,.2f} جم")
        for w in (w_gold, w_small, w_big, w_rate):
            w.valueChanged.connect(_calc)
        _calc()

        f = QtWidgets.QFormLayout()
        f.addRow("رقم الموديل:", w_model)
        f.addRow("رقم التشغيل:", w_no)
        f.addRow("الذهب (جم):", w_gold)
        f.addRow("الفصوص (جم):", w_small)
        f.addRow("الأحجار (جم):", w_big)
        f.addRow("نسبة الخصم %:", w_rate)
        f.addRow("الأجر/جم:", w_wage)
        f.addRow("ملاحظات:", w_notes)
        f.addRow(prev)
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
        no = w_no.text().strip()
        if not no:
            err(self, "أدخل رقم التشغيل")
            return
        if w_gold.value() <= 0:
            err(self, "أدخل وزن الذهب")
            return
        b.update({
            "model_no": w_model.text().strip(),
            "wo_no": no, "gold": w_gold.value(),
            "small_stones": w_small.value(), "big_stones": w_big.value(),
            "discount_rate": w_rate.value() / 100.0,
            "wage_per_gram": w_wage.value(),
            "notes": w_notes.text().strip()})
        self.render_batch()

    def remove_row(self):
        r = self.grid.currentRow()
        if r >= 0:
            self.batch.pop(r)
            self.render_batch()

    def render_batch(self):
        rows = []
        for b in self.batch:
            after = gold_math.stones_after_discount(b["big_stones"],
                                                    b["discount_rate"])
            reg = gold_math.registered_weight(b["gold"], b["small_stones"],
                                              b["big_stones"], b["discount_rate"])
            standing = gold_math.standing_gold(b["gold"], b["small_stones"],
                                               b["big_stones"])
            item_type = inventory.classify_item(
                b["wo_no"], b["gold"], b["small_stones"], b["big_stones"])
            rows.append((b.get("model_no") or "—",
                        b["wo_no"], item_type, b["gold"], b["small_stones"],
                        b["big_stones"], after,
                        f"{b['discount_rate']*100:.0f}%", reg, standing,
                        b.get("wage_per_gram", config.DEFAULT_WAGE_PER_GRAM),
                        b["notes"] or "—"))
        fill(self.grid, COLS, rows)
        # الإجمالي يُحسب من مصدر البيانات لا من فهرس عمود في الجدول:
        # إضافة أي عمود تُزيح الفهارس فيجمع النظام نصاً بدل رقم.
        total = round(sum(
            gold_math.registered_weight(b["gold"], b["small_stones"],
                                        b["big_stones"], b["discount_rate"])
            for b in self.batch), 3)
        self.totals.setText(
            f"عدد أطقم الدفعة: {len(self.batch)}   |   إجمالي الوزن المقيد: "
            f"{total:.2f} جم")
        self.recalc()

    def post_batch(self):
        if not self.batch:
            err(self, "أضف طقماً واحداً على الأقل إلى الدفعة قبل الترحيل")
            return
        if not ask(self, f"ترحيل {len(self.batch)} طقم بقيد محاسبي مجمّع واحد؟"):
            return
        try:
            # التحقق من حياة القيد **قبل** فتح المعاملة — لا داخلها
            self.verify_edit_target()
            if not confirm_post(self, "دفعة توريد أطقم"):
                return

            with db() as conn:
                if self.is_editing:
                    # تحديث **تفاضلي** لا إعادة إنشاء: المباع يبقى
                    # كما هو، والموجود يُعدَّل، والجديد يُضاف —
                    # والقيد يُعدَّل بالفرق الصافي وحده.
                    res = inventory.update_supply_batch(
                        conn, self.editing_entry_id, self.batch,
                        dstr(self.date), self.user["username"])
                else:
                    res = inventory.create_work_orders_batch(
                        conn, self.batch, dstr(self.date), self.user["username"])
            if res.get("delta") is not None:
                # ملخّص التعديل التفاضلي
                parts = []
                if res.get("added"):
                    parts.append(f"أُضيف {len(res['added'])} طقم")
                if res.get("updated"):
                    parts.append(f"عُدّل {len(res['updated'])}")
                if res.get("removed"):
                    parts.append(f"حُذف {len(res['removed'])}")
                if res.get("kept_sold"):
                    parts.append(
                        f"{len(res['kept_sold'])} مباع بقي كما هو")
                lines = ("   ·   ".join(parts)
                         + f"\nصافي التغيّر في الذهب المشغول: "
                           f"{res['delta']:+.3f} جم")
            else:
                lines = "\n".join(f"• {i['work_order_no']}: مقيد "
                                  f"{i['registered_weight']:.2f} / قائم "
                                  f"{i['standing_gold']:.2f} جم"
                                  for i in res["items"])
            was_editing = bool(self.is_editing)
            posted(self, f"تم ترحيل الدفعة بقيد رقم {res['entry_id']}\n"
                       f"إجمالي الوزن المقيد: {res['total_registered']:.2f} جم\n"
                       f"{lines}", "work_orders",
                   (res.get("items") or [{}])[0].get("id"),
                   editing=was_editing)
            self.end_edit()
            self.batch = []
            self.render_batch()
            self.refresh()
        except Exception as e:
            err(self, e)

    def load_document(self, source_id):
        """يفتح دفعة توريد قائمة للتعديل: يُنزل كل أطقم القيد المجمّع
        نفسه في الجدول (لأن عكس القيد يعكس الدفعة كاملة)."""
        try:
            with db() as conn:
                wo = conn.execute(
                    "SELECT * FROM work_orders WHERE id=?", (source_id,)).fetchone()
                if not wo:
                    raise ValueError("رقم التشغيل غير موجود")
                # الطقم المباع يُعدَّل توريده أيضاً: تصحيح وزن مُدخل
                # خطأً واجب سواء بقي بالمخزن أو خرج. القيد العكسي
                # يُلغي أثر التوريد القديم كاملاً ويُرحَّل الجديد،
                # فالميزان يبقى سليماً وفاتورة البيع تظل قائمة على
                # الطقم نفسه بوزنه المصحَّح.
                # نقرأ **حصة الدفعة** من سطورها المحفوظة لا من رصيد
                # الطقم: الرقم التجميعي 0001 تراكمي، فرصيده يشمل كل
                # الدفعات السابقة ولا يمثل ما أُدخل هنا.
                lines = conn.execute(
                    "SELECT * FROM wo_batch_lines WHERE entry_id=?"
                    " ORDER BY seq, id", (wo["entry_id"],)).fetchall()
                if lines:
                    rows = lines
                    src = "batch"
                else:
                    rows = conn.execute(
                        "SELECT * FROM work_orders WHERE entry_id=?"
                        " AND is_deleted=0 ORDER BY id",
                        (wo["entry_id"],)).fetchall()
                    src = "wo"
            if src == "batch":
                self.batch = [{
                    "model_no": r["model_no"] or "",
                    "wo_no": r["wo_no"], "gold": r["gold"],
                    "small_stones": r["small_stones"],
                    "big_stones": r["big_stones"],
                    "discount_rate": r["discount_rate"],
                    "wage_per_gram": r["wage_per_gram"],
                    "notes": r["notes"] or ""} for r in rows]
            else:
                self.batch = [{
                    "model_no": (r["model_no"] if "model_no" in r.keys()
                                 else "") or "",
                    "wo_no": r["work_order_no"], "gold": r["gold_weight"],
                    "small_stones": r["small_stones"],
                    "big_stones": r["big_stones"],
                    "discount_rate": r["discount_rate"],
                    "wage_per_gram": r["wage_per_gram"],
                    "notes": r["notes"] or ""} for r in rows]
            # التاريخ يبقى تاريخ العملية الأصلي: التعديل تصحيح لا
            # عملية جديدة، فتغيير تاريخه يُزحزح الأرصدة التاريخية.
            try:
                with db() as conn:
                    e = conn.execute(
                        "SELECT entry_date FROM journal_entries WHERE id=?",
                        (wo["entry_id"],)).fetchone()
                if e and e["entry_date"]:
                    self.date.setDate(QtCore.QDate.fromString(
                        e["entry_date"], "yyyy-MM-dd"))
            except Exception:
                pass
            self.render_batch()
            self.begin_edit(wo["entry_id"], source_id)
        except Exception as e:
            err(self, e)

    def on_edit_cancelled(self):
        self.batch = []
        self.render_batch()

    def refresh(self):
        # اقتراح الموديلات المسجّلة سابقاً
        try:
            from models import models_catalog as _mc
            with db() as conn:
                names = _mc.model_names(conn)
            cur = self.model_no.currentText()
            self.model_no.clear()
            self.model_no.addItems(names)
            self.model_no.setCurrentText(cur)
        except Exception:
            pass
        with db() as conn:
            if not self.wo_no.text().strip():
                self.wo_no.setPlaceholderText(f"مقترح: {inventory.next_wo_no(conn)}")
            snap = inventory.stock_snapshot(conn)
        self.tazeena_label.setText(
            f"رصيد خزينة التصنيع: {snap['tazeena_gold']:.2f} جم عيار 18   |   "
            f"الذهب المشغول: {snap['mashghool_gold']:.2f} جم "
            f"({snap['wo_count']} طقم)")
        self.render_batch()
