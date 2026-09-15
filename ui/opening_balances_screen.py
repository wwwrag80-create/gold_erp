# -*- coding: utf-8 -*-
"""شاشة تهيئة أرصدة أول المدة (تاريخ القطع — Cut-off Date).

تتيح بدء استخدام النظام في أي تاريخ: تُدخل الأرصدة الفعلية للمصنع
(نقداً وذهباً) موجّهةً لحساباتها في دفتر الأستاذ، ويُحفظ قيد افتتاحي
متوازن بالتاريخ الذي تختاره — وليس بالضرورة 1 يناير.
"""
from PyQt5 import QtCore, QtWidgets

from database.database import db
import config
from models import closing, inventory
from models.accounts import list_postable
from ui.widgets.common import (ask, big_label, date_edit, dstr, err, fill,
                               info, make_table, mspin, reload_combo,
                               search_combo, title_label, wspin)

COLS = ["الحساب", "الرصيد النقدي (ريال)", "رصيد الذهب (جم 18)", "البيان"]


class OpeningBalancesScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.rows = []

        self.account = search_combo("اكتب اسم أو كود الحساب…")
        self.account.currentIndexChanged.connect(self.on_account_changed)
        self.cash = mspin()
        self.cash.setRange(-9_999_999, 9_999_999)
        self.gold = wspin()
        self.gold.setRange(-999_999, 999_999)
        self.desc = QtWidgets.QLineEdit()
        self.desc.setPlaceholderText("بيان اختياري")
        btn_add = QtWidgets.QPushButton("إضافة السطر")
        btn_add.clicked.connect(self.add_row)
        btn_del = QtWidgets.QPushButton("حذف المحدد")
        btn_del.setObjectName("ghost")
        btn_del.clicked.connect(self.del_row)

        entry = QtWidgets.QGridLayout()
        entry.addWidget(QtWidgets.QLabel("الحساب:"), 0, 0)
        entry.addWidget(self.account, 0, 1)
        entry.addWidget(QtWidgets.QLabel("نقد:"), 0, 2)
        entry.addWidget(self.cash, 0, 3)
        entry.addWidget(QtWidgets.QLabel("ذهب:"), 0, 4)
        entry.addWidget(self.gold, 0, 5)
        entry.addWidget(QtWidgets.QLabel("البيان:"), 1, 0)
        entry.addWidget(self.desc, 1, 1, 1, 3)
        entry.addWidget(btn_add, 1, 4)
        entry.addWidget(btn_del, 1, 5)

        self.date = date_edit()
        self.notes = QtWidgets.QLineEdit()
        self.notes.setPlaceholderText("ملاحظة على القيد الافتتاحي")
        btn_save = QtWidgets.QPushButton("💾 ترحيل القيد الافتتاحي")
        btn_save.setObjectName("homeBtn")
        btn_save.clicked.connect(self.save)

        foot = QtWidgets.QHBoxLayout()
        foot.addWidget(QtWidgets.QLabel("تاريخ القطع:"))
        foot.addWidget(self.date)
        foot.addWidget(QtWidgets.QLabel("ملاحظة:"))
        foot.addWidget(self.notes, 1)
        foot.addWidget(btn_save)

        self.table = make_table()
        self.totals = big_label()

        # ── شبكة أطقم الذهب المشغول (تظهر عند اختيار حساب 1200) ──
        self.wo_rows = []
        self.wo_no = QtWidgets.QLineEdit()
        self.wo_no.setPlaceholderText("رقم التشغيل")
        self.wo_reg = wspin()
        self.wo_no.returnPressed.connect(lambda: self.wo_reg.setFocus())
        btn_wo_add = QtWidgets.QPushButton("➕ إضافة طقم")
        btn_wo_add.clicked.connect(self.add_wo_row)
        btn_wo_del = QtWidgets.QPushButton("حذف المحدد")
        btn_wo_del.setObjectName("ghost")
        btn_wo_del.clicked.connect(self.del_wo_row)
        btn_wo_save = QtWidgets.QPushButton("💾 ترحيل أطقم الذهب المشغول")
        btn_wo_save.setObjectName("homeBtn")
        btn_wo_save.clicked.connect(self.save_wo)

        self.wo_table = make_table()
        self.wo_total = big_label()
        self.wo_box = QtWidgets.QGroupBox(
            "أرصدة أول المدة — الذهب المشغول (أطقم متاحة للبيع فوراً)")
        wl = QtWidgets.QVBoxLayout(self.wo_box)
        note2 = QtWidgets.QLabel(
            "أدخل أرقام التشغيل القديمة وأوزانها المقيدة. مجموع الأوزان هو "
            "الرصيد الافتتاحي لحساب الذهب المشغول، وتُرحَّل الأطقم تلقائياً "
            "لتصبح متاحة للبيع الفعلي في المخزون.")
        note2.setObjectName("cardSub")
        note2.setWordWrap(True)
        wl.addWidget(note2)
        wrow = QtWidgets.QHBoxLayout()
        wrow.addWidget(QtWidgets.QLabel("رقم التشغيل:"))
        wrow.addWidget(self.wo_no, 1)
        wrow.addWidget(QtWidgets.QLabel("الوزن المقيد (جم):"))
        wrow.addWidget(self.wo_reg, 1)
        wrow.addWidget(btn_wo_add)
        wrow.addWidget(btn_wo_del)
        wl.addLayout(wrow)
        wl.addWidget(self.wo_table, 1)
        wl.addWidget(self.wo_total)
        wl.addWidget(btn_wo_save)
        self.wo_box.setVisible(False)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("تهيئة أرصدة أول المدة — تاريخ القطع"))
        note = QtWidgets.QLabel(
            "أدخل الأرصدة الفعلية للمصنع بأي تاريخ تختاره. الأرقام الموجبة "
            "تُقيَّد مدينة (أصول)، والسالبة دائنة (خصوم وحقوق ملكية). أي فرق "
            "متبقٍّ يُرحَّل تلقائياً لحساب «الأرصدة الافتتاحية للتسوية» ليخرج "
            "القيد متوازناً.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addLayout(entry)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.totals)
        lay.addWidget(self.wo_box, 1)
        lay.addLayout(foot)

    def on_account_changed(self):
        """شبكة الأطقم تظهر حصراً عند اختيار حساب الذهب المشغول."""
        code = self.account.currentData()
        self.wo_box.setVisible(str(code) == "1200")

    def add_wo_row(self):
        try:
            no = self.wo_no.text().strip()
            reg = round(self.wo_reg.value(), 2)
            if not no:
                raise ValueError("أدخل رقم التشغيل")
            if reg <= 0:
                raise ValueError("أدخل الوزن المقيد")
            if any(r["wo_no"] == no for r in self.wo_rows):
                raise ValueError(f"رقم التشغيل {no} مضاف مسبقاً")
            self.wo_rows.append({"wo_no": no, "reg": reg})
            self.wo_no.clear()
            self.wo_reg.setValue(0)
            self.wo_no.setFocus()
            self.render_wo()
        except Exception as e:
            err(self, e)

    def del_wo_row(self):
        i = self.wo_table.currentRow()
        if 0 <= i < len(self.wo_rows):
            self.wo_rows.pop(i)
            self.render_wo()

    def render_wo(self):
        fill(self.wo_table, ["رقم التشغيل", "الوزن المقيد (جم)"],
             [(r["wo_no"], f"{r['reg']:,.2f}") for r in self.wo_rows])
        tot = round(sum(r["reg"] for r in self.wo_rows), 2)
        self.wo_total.setText(
            f"عدد الأطقم: {len(self.wo_rows)}   |   "
            f"إجمالي الوزن المقيد (الرصيد الافتتاحي): {tot:,.2f} جم 18")

    def save_wo(self):
        """يرحّل الأطقم إلى مخزون الذهب المشغول بقيد افتتاحي واحد."""
        try:
            if not self.wo_rows:
                raise ValueError("أضف طقماً واحداً على الأقل")
            tot = round(sum(r["reg"] for r in self.wo_rows), 2)
            if not ask(self, f"ترحيل {len(self.wo_rows)} طقماً بإجمالي "
                             f"{tot:,.2f} جم إلى الذهب المشغول بتاريخ "
                             f"{dstr(self.date)}؟"):
                return
            # الوزن المقيد يُدخل كذهب صافٍ بلا أحجار، فيتطابق المقيد معه
            rows = [{"wo_no": r["wo_no"], "gold": r["reg"],
                     "small_stones": 0, "big_stones": 0,
                     "discount_rate": 0.5,
                     "wage_per_gram": config.DEFAULT_WAGE_PER_GRAM}
                    for r in self.wo_rows]
            with db() as conn:
                res = inventory.opening_stock_batch(
                    conn, rows, dstr(self.date), self.user["username"])
            info(self, f"تم ترحيل {len(res)} طقماً بإجمالي {tot:,.2f} جم.\n"
                       f"الأطقم متاحة الآن للبيع في مخزون الذهب المشغول.")
            self.wo_rows = []
            self.render_wo()
        except Exception as e:
            err(self, e)

    def add_row(self):
        try:
            code = self.account.currentData()
            if not code:
                raise ValueError("اختر الحساب")
            cash = round(self.cash.value(), 2)
            gold = round(self.gold.value(), 3)
            if not cash and not gold:
                raise ValueError("أدخل رصيداً نقدياً أو وزنياً")
            name = self.account.currentText()
            self.rows.append({"code": code, "name": name, "cash": cash,
                              "gold": gold, "desc": self.desc.text().strip()})
            self.cash.setValue(0)
            self.gold.setValue(0)
            self.desc.clear()
            self.render()
        except Exception as e:
            err(self, e)

    def del_row(self):
        i = self.table.currentRow()
        if 0 <= i < len(self.rows):
            self.rows.pop(i)
            self.render()

    def render(self):
        data = [(r["name"], f"{r['cash']:,.2f}", f"{r['gold']:,.2f}",
                 r["desc"] or "—") for r in self.rows]
        fill(self.table, COLS, data)
        tc = round(sum(r["cash"] for r in self.rows), 2)
        tg = round(sum(r["gold"] for r in self.rows), 3)
        self.totals.setText(
            f"مجموع المُدخل — نقد: {tc:,.2f} ريال   |   ذهب: {tg:,.2f} جم 18"
            + ("   (سيُرحَّل الفرق لحساب التسوية تلقائياً)"
               if abs(tc) > 0.01 or abs(tg) > 0.001 else "   (متوازن)"))

    def save(self):
        try:
            if not self.rows:
                raise ValueError("أضف سطراً واحداً على الأقل")
            if not ask(self, f"ترحيل القيد الافتتاحي بتاريخ "
                             f"{dstr(self.date)}؟"):
                return
            with db() as conn:
                res = closing.create_opening_entry(
                    conn, self.rows, dstr(self.date),
                    self.user["username"], self.notes.text().strip())
            info(self, f"تم ترحيل القيد الافتتاحي #{res['entry_id']} "
                       f"بتاريخ {res['date']}\n"
                       f"عدد الأسطر: {res['lines']}")
            self.rows = []
            self.notes.clear()
            self.render()
        except Exception as e:
            err(self, e)

    def refresh(self):
        with db() as conn:
            accs = list_postable(conn)
        reload_combo(self.account, accs,
                     lambda a: f"{a['code']} — {a['name']}",
                     id_key="code")
        self.render()
