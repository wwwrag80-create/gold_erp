# -*- coding: utf-8 -*-
"""الأرصدة الافتتاحية المخزنية: إدخال أرقام تشغيل قديمة موجودة فعلياً
بالمخزن مباشرة إلى الذهب المشغول — متاحة للبيع فوراً دون المرور بدورة
تصنيع كاملة. القيد: مدين الذهب المشغول (1200) / دائن الأرصدة الافتتاحية
للتسوية (3900) بإجمالي الوزن المقيد، بقيد واحد مجمّع."""
from PyQt5 import QtWidgets

import config
from database.database import db
from models import inventory
from services import gold_math, karat_view as kv
from ui.widgets.common import (ask, big_label, date_edit, dstr, enter_chain,
                               err, fill, info, make_table, mspin,
                               title_label, wspin)

COLS = ["رقم التشغيل", "الذهب", "الفصوص", "الأحجار", "الأحجار بعد الخصم",
        "نسبة الخصم", "الوزن المقيد", "الذهب القائم", "الأجر/جم"]


class OpeningStockScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.batch = []
        self.rate = config.STONE_DISCOUNT_RATE

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
        for w in (self.gold, self.small, self.big):
            w.valueChanged.connect(self.recalc)
        self.reg_label = big_label("الوزن المقيد: 0.000 جم")

        btn_add = QtWidgets.QPushButton("+ إضافة")
        btn_add.clicked.connect(self.add_row)

        def _lbl(t):
            l = QtWidgets.QLabel(t)
            l.setObjectName("cardSub")
            return l

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
        entry_row.addLayout(col("رقم التشغيل", self.wo_no, 130))
        entry_row.addLayout(col("الذهب", self.gold, 95))
        entry_row.addLayout(col("الفصوص", self.small, 85))
        entry_row.addLayout(col("الأحجار", self.big, 85))
        entry_row.addLayout(col("بعد الخصم", after_w, 170))
        entry_row.addLayout(col("الأجر/جم", self.wage, 90))
        entry_row.addLayout(col("", btn_add, 110))

        entry_box = QtWidgets.QGroupBox(
            "إدخال رقم تشغيل موجود فعلياً بالمخزن قبل بدء استخدام النظام")
        ebl = QtWidgets.QVBoxLayout(entry_box)
        ebl.addLayout(entry_row)
        ebl.addWidget(self.reg_label)

        self.grid = make_table()
        btn_remove = QtWidgets.QPushButton("حذف السطر المحدد")
        btn_remove.setObjectName("ghost")
        btn_remove.clicked.connect(self.remove_row)
        self.date = date_edit()
        self.totals = big_label()
        btn_post = QtWidgets.QPushButton(
            "ترحيل الرصيد الافتتاحي المخزني (قيد مجمّع واحد)")
        btn_post.clicked.connect(self.post_batch)

        batch_box = QtWidgets.QGroupBox("الدفعة الافتتاحية — قبل الترحيل")
        bl = QtWidgets.QVBoxLayout(batch_box)
        bl.addWidget(self.grid)
        r2 = QtWidgets.QHBoxLayout()
        r2.addWidget(btn_remove)
        r2.addStretch(1)
        r2.addWidget(QtWidgets.QLabel("تاريخ الرصيد الافتتاحي:"))
        r2.addWidget(self.date)
        bl.addLayout(r2)
        bl.addWidget(self.totals)
        bl.addWidget(btn_post)

        self.stock_label = big_label()
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("الأرصدة الافتتاحية المخزنية — الذهب المشغول"))
        lay.addWidget(self.stock_label)
        enter_chain(self, [self.wo_no, self.gold, self.small, self.big,
                           self.wage], self.add_row)
        lay.addWidget(entry_box)
        lay.addWidget(batch_box, 1)
        note = QtWidgets.QLabel(
            "تُستخدم مرة واحدة عند بدء التشغيل لإدخال البضاعة القائمة فعلاً. "
            "الأطقم المُدخلة هنا تدخل الذهب المشغول مباشرة وتصبح متاحة للبيع "
            "فوراً، والطرف المقابل هو حساب الأرصدة الافتتاحية للتسوية (3900) "
            "— لا تمر على خزينة التصنيع ولا تُحتسب ضمن إنتاج الفترة.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)

    def edit_rate(self):
        val, ok = QtWidgets.QInputDialog.getDouble(
            self, "نسبة الخصم على الأحجار", "نسبة الخصم (%):",
            self.rate * 100, 0.0, 100.0, 1)
        if ok:
            self.rate = val / 100.0
            self.btn_rate.setText(f"خصم {self.rate*100:.0f}%")
            self.recalc()

    def recalc(self):
        after = gold_math.stones_after_discount(self.big.value(), self.rate)
        reg = gold_math.registered_weight(self.gold.value(), self.small.value(),
                                          self.big.value(), self.rate)
        self.after.setText(f"{after:.2f}")
        self.reg_label.setText(f"الوزن المقيد: {reg:.2f} {kv.unit()}")

    def add_row(self):
        try:
            wo_no = self.wo_no.text().strip()
            if not wo_no:
                raise ValueError("أدخل رقم التشغيل")
            if any(b["wo_no"] == wo_no for b in self.batch):
                raise ValueError(f"رقم التشغيل {wo_no} مضاف مسبقاً في الدفعة")
            if self.gold.value() + self.small.value() + self.big.value() <= 0:
                raise ValueError("أدخل وزناً واحداً على الأقل")
            self.batch.append({
                "wo_no": wo_no, "gold": self.gold.value(),
                "small_stones": self.small.value(),
                "big_stones": self.big.value(), "discount_rate": self.rate,
                "wage_per_gram": self.wage.value()})
            self.wo_no.clear()
            for w in (self.gold, self.small, self.big):
                w.setValue(0)
            self.wage.setValue(config.DEFAULT_WAGE_PER_GRAM)
            self.wo_no.setFocus()
            self.render_batch()
        except Exception as e:
            err(self, e)

    def remove_row(self):
        r = self.grid.currentRow()
        if 0 <= r < len(self.batch):
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
            rows.append((b["wo_no"], b["gold"], b["small_stones"],
                        b["big_stones"], after,
                        f"{b['discount_rate']*100:.0f}%", reg, standing,
                        b["wage_per_gram"]))
        fill(self.grid, COLS, rows)
        # الإجمالي من مصدر البيانات لا من فهرس عمود (الفهارس تُزاح)
        total = round(sum(
            gold_math.registered_weight(b["gold"], b["small_stones"],
                                        b["big_stones"], b["discount_rate"])
            for b in self.batch), 3)
        self.totals.setText(
            f"عدد الأطقم: {len(self.batch)}   |   إجمالي الوزن المقيد: "
            f"{total:.2f} {kv.unit()}")
        self.recalc()

    def post_batch(self):
        if not self.batch:
            err(self, "أضف رقم تشغيل واحداً على الأقل قبل الترحيل")
            return
        if not ask(self, f"ترحيل {len(self.batch)} طقم كرصيد افتتاحي مخزني "
                         "مباشرة إلى الذهب المشغول؟"):
            return
        try:
            # الحد الفاصل: الإدخال بعيار المصنع والتخزين بمكافئ 18
            batch = [{**b,
                      "gold": kv.store(b["gold"]),
                      "small_stones": kv.store(b["small_stones"]),
                      "big_stones": kv.store(b["big_stones"]),
                      "wage_per_gram": kv.rate_store(b["wage_per_gram"])}
                     for b in self.batch]
            with db() as conn:
                res = inventory.opening_stock_batch(
                    conn, batch, dstr(self.date), self.user["username"])
            info(self, f"تم ترحيل الرصيد الافتتاحي بقيد رقم {res['entry_id']}\n"
                       f"إجمالي الوزن المقيد: "
                       f"{kv.g(res['total_registered']):.2f} {kv.unit()}")
            self.batch = []
            self.render_batch()
            self.refresh()
        except Exception as e:
            err(self, e)

    def refresh(self):
        with db() as conn:
            snap = inventory.stock_snapshot(conn)
        self.stock_label.setText(
            f"الذهب المشغول حالياً: "
            f"{kv.g(snap['mashghool_gold']):.2f} جم {kv.label()} "
            f"({snap['wo_count']} طقم)")
        self.render_batch()
