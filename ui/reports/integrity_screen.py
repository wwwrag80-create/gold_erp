# -*- coding: utf-8 -*-
"""سلامة السجل — التحقق من سلسلة بصمات القيود.

تكشف أي تغييرٍ جرى على قيدٍ مرحَّل **من خارج النظام** (بفتح ملف قاعدة
البيانات ببرنامج آخر). شرح الآلية كاملاً في `models/integrity.py`.
"""
from PyQt5 import QtWidgets

from database.database import db
from models import integrity
from ui.widgets.common import (ask, big_label, err, fill, info, make_table,
                               title_label)
from ui.widgets.table_tools import enhance

COLS = ["رقم القيد", "رقم المستند", "التاريخ", "المستخدم", "البيان",
        "نوع الخلل"]


class IntegrityScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user

        self.state = big_label("اضغط «تحقّق الآن» لفحص السلسلة.")
        self.detail = QtWidgets.QLabel("")
        self.detail.setObjectName("cardSub")
        self.detail.setWordWrap(True)

        btn_check = QtWidgets.QPushButton("🔍 تحقّق الآن")
        btn_check.clicked.connect(self.run_check)
        self.btn_seal = QtWidgets.QPushButton("🔒 ختم القيود غير المختومة")
        self.btn_seal.setObjectName("ghost")
        self.btn_seal.clicked.connect(self.seal)
        self.btn_rebuild = QtWidgets.QPushButton("♻ إعادة بناء السلسلة")
        self.btn_rebuild.setObjectName("ghost")
        self.btn_rebuild.setToolTip(
            "بعد معالجة خللٍ مُثبت (استعادة نسخة احتياطية مثلاً). "
            "العملية تُسجَّل في سجل التدقيق باسمك وزمنها.")
        self.btn_rebuild.clicked.connect(self.rebuild)

        self.table = make_table()
        enhance(self.table, key="integrity")
        self.table.setColumnCount(len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(btn_check)
        top.addWidget(self.btn_seal)
        top.addWidget(self.btn_rebuild)
        top.addStretch(1)
        top.addWidget(self.state)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("سلامة السجل — بصمة كل قيد وسلسلتها"))
        intro = QtWidgets.QLabel(
            "لكل قيد بصمةٌ تُحسب من مضمونه وبصمة القيد الذي قبله معاً. "
            "فتغيير رقمٍ في قيدٍ قديم — من داخل النظام أو من خارجه — "
            "يُفسد بصمته ويُفسد معها بصمة كل ما بعده، فيظهر هنا بموضعه "
            "بالضبط.\n"
            "لا تشمل البصمة حالة الحذف المنطقي: الحذف عملٌ مشروع يجري "
            "من داخل النظام ويُوثَّق في سجل التدقيق.")
        intro.setObjectName("cardSub")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        lay.addLayout(top)
        lay.addWidget(self.detail)
        lay.addWidget(self.table, 1)
        note = QtWidgets.QLabel(
            "القيود التي رُحّلت قبل تفعيل الميزة تُختم دفعةً واحدة "
            "بمضمونها الحالي — وهذا خطُّ الأساس: السلسلة تشهد على ما "
            "بعد الختم لا على ما قبله.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)

    def run_check(self):
        try:
            with db(readonly=True) as conn:
                rep = integrity.verify(conn)
        except Exception as e:
            err(self, e)
            return
        rows = [(b["id"], b["doc_no"], b["date"], b["who"],
                 (b["desc"] or "")[:60], b["kind"]) for b in rep["breaks"]]
        fill(self.table, COLS, rows)
        self.btn_seal.setEnabled(bool(rep["unsealed"]))
        if rep["ok"] and not rep["unsealed"]:
            self.state.setText(f"✔ السلسلة سليمة — {rep['checked']:,} قيداً")
        elif rep["ok"]:
            self.state.setText(
                f"✔ السلسلة سليمة — {rep['checked']:,} قيداً مختوماً · "
                f"{rep['unsealed']:,} بلا بصمة")
        else:
            self.state.setText(
                f"⛔ خللٌ في {len(rep['breaks'])} قيداً — راجع الجدول")
        bits = [f"مختوم: {rep['checked']:,}",
                f"غير مختوم: {rep['unsealed']:,}"]
        if rep["first_sealed"]:
            bits.append(f"من القيد {rep['first_sealed']} "
                        f"إلى {rep['last_sealed']}")
        if not rep["ok"]:
            bits.append("⛔ القيد الأول المختل هو موضع البداية: كل ما "
                        "بعده يظهر مختلاً تبعاً له، فعالجه أولاً ثم "
                        "أعد الفحص")
        self.detail.setText("  ·  ".join(bits))

    def seal(self):
        """يختم ما لا بصمة له — خطّ الأساس لقاعدةٍ تعمل منذ قبل الميزة."""
        try:
            with db(readonly=True) as conn:
                st = integrity.status(conn)
            if not st["unsealed"]:
                info(self, "كل القيود مختومة.")
                return
            if not ask(self,
                       f"ختم {st['unsealed']:,} قيداً بمضمونها الحالي؟\n\n"
                       "هذا خطُّ الأساس: ما بعده تشهد عليه السلسلة، وما "
                       "قبله لا تشهد عليه. لا يتغيّر رقمٌ محاسبي واحد — "
                       "تُكتب البصمات وحدها."):
                return
            with db() as conn:
                n = integrity.seal_all(conn, self.user.get("username"))
            info(self, f"خُتم {n:,} قيداً.")
            self.run_check()
        except Exception as e:
            err(self, e)

    def rebuild(self):
        """يعيد ربط السلسلة بعد معالجة خللٍ مُثبت — بقرارٍ صريح مسجَّل."""
        try:
            if not ask(self,
                       "إعادة بناء سلسلة البصمات من أولها؟\n\n"
                       "تُستعمل بعد معالجة خللٍ مُثبت: استعادة نسخة "
                       "احتياطية، أو صيانةٍ مسحت سجلات، أو تعديلٍ جرى "
                       "بنسخةٍ قديمة من النظام.\n\n"
                       "• لا يتغيّر رقمٌ محاسبي واحد — تُعاد كتابة "
                       "البصمات وحدها.\n"
                       "• بعدها تشهد السلسلة على الحالة الراهنة، ولا "
                       "تشهد على ما سبق إعادة البناء.\n"
                       "• العملية تُسجَّل في سجل التدقيق باسمك وزمنها."):
                return
            with db() as conn:
                n = integrity.rebuild(conn, username=self.user.get("username"))
            info(self, f"أُعيد بناء السلسلة — {n:,} قيداً.")
            self.run_check()
        except Exception as e:
            err(self, e)

    def refresh(self):
        self.run_check()
