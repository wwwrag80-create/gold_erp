# -*- coding: utf-8 -*-
"""أداة الإقفال السنوي (Year-End Closing).

تعاين نتيجة السنة ثم تُقفلها آلياً: تصفير حسابات الإيرادات والمصروفات،
وترحيل صافي الربح/الخسارة إلى الأرباح المحتجزة أو جاري الشركاء، مع
خيار إنشاء قيد تدوير صريح للسنة الجديدة.
"""
from PyQt5 import QtCore, QtWidgets

from database.database import db
from services import karat_view as kv
from models import closing, fiscal
from ui.widgets.common import (ask, big_label, dstr, err, fill, info, make_table, title_label)

COLS = ["الكود", "الحساب", "النوع", "الرصيد النقدي", "رصيد الذهب"]


class YearEndScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.preview = None

        self.year = QtWidgets.QSpinBox()
        self.year.setRange(2000, 2100)
        self.year.setValue(QtCore.QDate.currentDate().year())
        btn_prev = QtWidgets.QPushButton("معاينة نتيجة السنة")
        btn_prev.clicked.connect(self.load_preview)

        self.to_partners = QtWidgets.QCheckBox(
            "ترحيل الصافي إلى جاري الشركاء بدل الأرباح المحتجزة")
        self.roll = QtWidgets.QCheckBox(
            "إنشاء قيد تدوير صريح للسنة الجديدة (اختياري)")

        btn_run = QtWidgets.QPushButton("🔒 تنفيذ الإقفال السنوي")
        btn_run.setObjectName("closeBtn")
        btn_run.clicked.connect(self.run_closing)

        head = QtWidgets.QHBoxLayout()
        head.addWidget(QtWidgets.QLabel("السنة المالية:"))
        head.addWidget(self.year)
        head.addWidget(btn_prev)
        head.addStretch(1)
        head.addWidget(btn_run)

        self.summary = big_label()
        self.table = make_table()

        # ══ قفل الفترات ══
        self.lock_state = QtWidgets.QLabel("—")
        self.lock_state.setObjectName("cardSub")
        self.lock_date = QtWidgets.QDateEdit()
        self.lock_date.setCalendarPopup(True)
        self.lock_date.setDisplayFormat("yyyy-MM-dd")
        self.lock_date.setDate(QtCore.QDate.currentDate())
        btn_lock = QtWidgets.QPushButton("🔒 اقفل حتى هذا التاريخ")
        btn_lock.clicked.connect(self.apply_lock)
        btn_unlock = QtWidgets.QPushButton("🔓 ارفع القفل")
        btn_unlock.clicked.connect(self.clear_lock)

        lock_row = QtWidgets.QHBoxLayout()
        lock_row.addWidget(QtWidgets.QLabel("تاريخ القفل:"))
        lock_row.addWidget(self.lock_date)
        lock_row.addWidget(btn_lock)
        lock_row.addWidget(btn_unlock)
        lock_row.addStretch(1)

        lock_box = QtWidgets.QGroupBox("قفل الفترات المحاسبية")
        lock_lay = QtWidgets.QVBoxLayout(lock_box)
        lock_note = QtWidgets.QLabel(
            "بعد تسليم ميزانية فترة أو إقرارها الضريبي، اقفلها. عندئذٍ "
            "يُرفض أي قيد أو حذف بتاريخ داخلها — فلا تتغيّر أرقام سبق "
            "اعتمادها بسبب خطأ في حقل التاريخ. رفع القفل متاح للمحاسب "
            "وقت الحاجة، وكل تغيير يُسجَّل في سجل التدقيق.")
        lock_note.setObjectName("cardSub")
        lock_note.setWordWrap(True)
        lock_lay.addWidget(lock_note)
        lock_lay.addLayout(lock_row)
        lock_lay.addWidget(self.lock_state)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("الإقفال السنوي — إغلاق الفترة المالية"))
        note = QtWidgets.QLabel(
            "يصفّر حسابات الإيرادات والمصروفات بقيد إقفال بتاريخ 31-12، "
            "ويرحّل صافي النتيجة إلى حقوق الملكية. أرصدة الميزانية تنتقل "
            "للسنة الجديدة تلقائياً بحكم استمرارية دفتر الأستاذ، وقيد "
            "التدوير الصريح اختياري لمن يريد فصلاً دفترياً بين السنتين.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addLayout(head)
        lay.addWidget(self.to_partners)
        lay.addWidget(self.roll)
        lay.addWidget(self.summary)
        lay.addWidget(self.table, 1)
        lay.addWidget(lock_box)
        self.load_lock()

    def load_preview(self):
        try:
            with db() as conn:
                self.preview = closing.year_end_preview(
                    conn, int(self.year.value()))
            p = self.preview
            data = [(i["code"], i["name"],
                     "إيراد" if i["type"] == "revenue" else "مصروف",
                     f"{i['cash']:,.2f}", f"{kv.g(i['gold']):,.2f}")
                    for i in p["items"]]
            fill(self.table, COLS, data)
            kind = "ربح" if p["net_cash"] >= 0 else "خسارة"
            self.summary.setText(
                f"سنة {p['year']}: {len(p['items'])} حساب نتيجة   |   "
                f"صافي ال{kind}: {p['net_cash']:,.2f} ريال · "
                f"{kv.g(p['net_gold']):,.2f} {kv.unit()}")
        except Exception as e:
            err(self, e)

    def run_closing(self):
        try:
            year = int(self.year.value())
            if self.preview is None or self.preview["year"] != year:
                self.load_preview()
            if not self.preview or not self.preview["items"]:
                raise ValueError(f"لا توجد حركات إيراد أو مصروف في سنة {year}")
            target = ("جاري الشركاء" if self.to_partners.isChecked()
                      else "الأرباح المحتجزة")
            if not ask(self,
                       f"سيتم إقفال سنة {year} نهائياً:\n"
                       f"• تصفير {len(self.preview['items'])} حساب نتيجة\n"
                       f"• ترحيل صافي "
                       f"{self.preview['net_cash']:,.2f} ريال و"
                       f"{kv.g(self.preview['net_gold']):,.2f} "
                       f"{kv.unit()} إلى {target}\n\n"
                       f"هل تريد المتابعة؟"):
                return
            with db() as conn:
                res = closing.run_year_end_closing(
                    conn, year, self.user["username"],
                    to_partners=self.to_partners.isChecked(),
                    open_next_year=self.roll.isChecked())
            msg = (f"تم إقفال سنة {res['year']}.\n"
                   f"قيد الإقفال: #{res['close_entry']}\n"
                   f"الحسابات المُقفلة: {res['closed_accounts']}\n"
                   f"صافي النتيجة: {res['net_cash']:,.2f} ريال · "
                   f"{kv.g(res['net_gold']):,.2f} {kv.unit()} → {target}")
            if res["opening_entry"]:
                msg += f"\nقيد افتتاحي لسنة {year + 1}: #{res['opening_entry']}"
            info(self, msg)
            self.preview = None
            self.table.setRowCount(0)
            self.summary.setText("")
        except Exception as e:
            err(self, e)

    # ══════════════════════════════════════════════════════════════
    #  قفل الفترات
    # ══════════════════════════════════════════════════════════════

    def load_lock(self):
        try:
            with db(readonly=True) as conn:
                st = fiscal.status(conn)
        except Exception:
            return
        if st["locked"]:
            self.lock_state.setText(
                f"🔒 الفترة حتى {st['date']} مقفلة — "
                f"{st['entries_locked']:,} قيداً محميّاً من التعديل.")
            self.lock_date.setDate(
                QtCore.QDate.fromString(st["date"], "yyyy-MM-dd"))
        else:
            self.lock_state.setText(
                "🔓 لا يوجد قفل — كل الفترات مفتوحة للترحيل والتعديل.")

    def apply_lock(self):
        try:
            d = dstr(self.lock_date)
            with db(readonly=True) as conn:
                n = conn.execute(
                    "SELECT COUNT(*) c FROM journal_entries"
                    " WHERE is_deleted=0 AND entry_date<=?", (d,)).fetchone()["c"]
            if not ask(self,
                       f"قفل كل ما هو حتى {d}؟\n\n"
                       f"القيود المتأثرة: {n:,}\n"
                       f"بعد القفل يُرفض أي ترحيل أو حذف بتاريخ ≤ {d}، "
                       f"ويبقى العرض والطباعة والتقارير كما هي.\n\n"
                       f"يمكن رفع القفل لاحقاً من هذه الشاشة."):
                return
            with db() as conn:
                fiscal.set_lock(conn, d, self.user["username"])
            self.load_lock()
            info(self, f"أُقفلت الفترة حتى {d}.")
        except Exception as e:
            err(self, e)

    def clear_lock(self):
        try:
            with db(readonly=True) as conn:
                cur = fiscal.lock_date(conn)
            if not cur:
                info(self, "لا يوجد قفل مفعّل.")
                return
            if not ask(self,
                       f"رفع القفل عن الفترة حتى {cur}؟\n\n"
                       f"ستعود الفترة قابلةً للترحيل والحذف — وهو ما قد "
                       f"يغيّر ميزانيةً سبق تسليمها. يُسجَّل هذا الإجراء "
                       f"في سجل التدقيق باسمك."):
                return
            with db() as conn:
                fiscal.set_lock(conn, "", self.user["username"])
            self.load_lock()
            info(self, "رُفع القفل.")
        except Exception as e:
            err(self, e)

    def refresh(self):
        self.load_lock()
