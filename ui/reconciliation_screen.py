# -*- coding: utf-8 -*-
"""شاشة المطابقة وتسوية الفروقات الآلية (Ledger Reconciliation).

بضغطة زر تُجري تدقيقاً آلياً شاملاً على النظام كله، وتعرض أي اختلالات
مصنّفة بخطورتها مع موقعها ووصفها، وزر تعمّق يفتح القيد المختل مباشرة
في دفتر الأستاذ لمعالجته.
"""
from PyQt5 import QtCore, QtWidgets

from database.database import db
from models import reconciliation
from ui.widgets.common import (big_label, bulk_rows, err, make_table,
                               title_label)

COLS = ["الخطورة", "نوع الاختلال", "الموقع", "الوصف", "فرق النقد",
        "فرق الذهب", "تعمّق"]


class ReconciliationScreen(QtWidgets.QWidget):
    def __init__(self, user, on_open_entry=None):
        super().__init__()
        self.user = user
        self.on_open_entry = on_open_entry
        self.issues = []

        btn = QtWidgets.QPushButton("🔍 تشغيل التدقيق الآلي الشامل")
        btn.setObjectName("homeBtn")
        btn.clicked.connect(self.run)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(btn)
        top.addStretch(1)

        self.summary = big_label()
        self.table = make_table()

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label(
            "المطابقة وتسوية الفروقات الآلية — تدقيق النظام"))
        note = QtWidgets.QLabel(
            "يقارن كل القيود والأرصدة ويكتشف أي اختلال بين يومية الصندوق "
            "وحسابات الذهب: قيود غير متوازنة · اختلال الميزان الكلي · "
            "أرصدة لا تساوي صفراً · قيود يتيمة أو بطرف واحد.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addLayout(top)
        lay.addWidget(self.summary)
        lay.addWidget(self.table, 1)

    def run(self):
        try:
            with db(readonly=True) as conn:
                res = reconciliation.reconcile(conn)
            self.issues = res["issues"]
            self._render(res)
        except Exception as e:
            err(self, e)

    def _render(self, res):
        self.table.setRowCount(0)
        self.table.setColumnCount(len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        if res["clean"]:
            self.summary.setText(
                "✅ النظام سليم تماماً — كل القيود متوازنة والأرصدة مطابقة، "
                "لا اختلالات.")
            return
        self.summary.setText(
            f"⚠ نتيجة التدقيق: {res['critical']} اختلال حرج · "
            f"{res['warnings']} تحذير — راجع الجدول لمعالجتها.")
        # دفترٌ مختلٌّ قد يُخرج ألفَ اختلال — ولا يُرسم ألفُ صفٍّ بخليةٍ
        # تُعيد قياس صفّها. `bulk_rows` يجعل الرسم لحظياً مهما كثرت.
        with bulk_rows(self.table, len(self.issues), COLS):
            for i, issue in enumerate(self.issues):
                sev = ("🔴 حرج" if issue["severity"] == "critical"
                       else "🟡 تحذير")
                cd = f"{issue['cash_diff']:,.2f}" if issue["cash_diff"] else "—"
                gd = f"{issue['gold_diff']:,.2f}" if issue["gold_diff"] else "—"
                vals = [sev, issue["kind"], issue["ref"], issue["detail"],
                        cd, gd]
                for c, v in enumerate(vals):
                    it = QtWidgets.QTableWidgetItem(str(v))
                    it.setTextAlignment(QtCore.Qt.AlignCenter)
                    self.table.setItem(i, c, it)
                if issue.get("entry_id") and self.on_open_entry:
                    b = QtWidgets.QPushButton("فتح القيد")
                    b.setObjectName("ghost")
                    b.clicked.connect(
                        lambda _, e=issue["entry_id"]: self.on_open_entry(e))
                    self.table.setCellWidget(i, len(COLS) - 1, b)

    def refresh(self):
        pass
