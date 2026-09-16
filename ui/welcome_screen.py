# -*- coding: utf-8 -*-
"""شاشة البداية الحيّة — أرقام اليوم لا شعارٌ ثابت.

**ما تغيّر ولماذا**: كانت الشاشة الأولى شعاراً يتوسّط فراغاً. والشعار
يُرى مرةً ثم يصير مساحةً تُتجاوَز كل صباح. وأسئلة أول الدوام ثابتة:
ماذا جرى اليوم؟ هل في الخزائن رصيدٌ سالب؟ من تأخّر في السداد؟ ماذا
رُحِّل آخر شيء ومن رحّله؟ — أربعة أسئلة تُفتح لها أربع شاشات.

الآن تُجاب كلها هنا، **وكل رقم بابٌ إلى تفصيله**: الرصيد يفتح كشف
حسابه، والدين يفتح كشف صاحبه، والعملية تفتح مستندها للتعديل. فالشاشة
الأولى نقطة بداية العمل لا لافتةً على بابه.

**لا تُبطئ الإقلاع**: البيانات تُقرأ بعد ظهور الشاشة لا قبله، وكل
جزء مستقل — فقاعدة ينقصها حساب تعرض بقية الأجزاء كاملةً.
"""
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets

import config
from services import karat_view as kv


def _money(v):
    return f"{float(v or 0):,.2f}"


class KpiCard(QtWidgets.QFrame):
    """بطاقة رقمٍ واحد: عنوانه فوقه صغيراً، وحالته لونٌ على حافته."""

    clicked = QtCore.pyqtSignal()

    def __init__(self, title, value="—", sub="", state=""):
        super().__init__()
        self.setObjectName(
            {"bad": "kpiAlert", "good": "kpiGood"}.get(state, "kpi"))
        self.setCursor(QtCore.Qt.PointingHandCursor)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(13, 10, 13, 10)
        lay.setSpacing(2)
        self.t = QtWidgets.QLabel(title)
        self.t.setObjectName("kpiTitle")
        self.t.setWordWrap(True)
        self.v = QtWidgets.QLabel(value)
        self.v.setObjectName("kpiValue")
        self.s = QtWidgets.QLabel(sub)
        self.s.setObjectName("kpiSub")
        self.s.setWordWrap(True)
        lay.addWidget(self.t)
        lay.addWidget(self.v)
        lay.addWidget(self.s)

    def set(self, value, sub=None, state=None):
        self.v.setText(str(value))
        if sub is not None:
            self.s.setText(str(sub))
        if state is not None:
            self.setObjectName({"bad": "kpiAlert",
                                "good": "kpiGood"}.get(state, "kpi"))
            # إعادة تطبيق النمط: تغيير الاسم وحده لا يُعيد رسم العنصر
            self.style().unpolish(self)
            self.style().polish(self)

    def mouseReleaseEvent(self, ev):
        if ev.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(ev)


class Box(QtWidgets.QFrame):
    """لوحة معنونة تحوي صفوفاً قابلة للنقر."""

    def __init__(self, title):
        super().__init__()
        self.setObjectName("homeBox")
        self.lay = QtWidgets.QVBoxLayout(self)
        self.lay.setContentsMargins(13, 11, 13, 11)
        self.lay.setSpacing(1)
        t = QtWidgets.QLabel(title)
        t.setObjectName("homeBoxTitle")
        self.lay.addWidget(t)
        self.body = QtWidgets.QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(0)
        self.lay.addLayout(self.body)
        self.lay.addStretch(1)

    def clear(self):
        while self.body.count():
            it = self.body.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)

    def row(self, text, tip="", on_click=None):
        b = QtWidgets.QPushButton(text)
        b.setObjectName("homeRow")
        b.setCursor(QtCore.Qt.PointingHandCursor)
        if tip:
            b.setToolTip(tip)
        if on_click is not None:
            b.clicked.connect(lambda *_: on_click())
        else:
            b.setEnabled(False)
        self.body.addWidget(b)
        return b

    def note(self, text):
        lb = QtWidgets.QLabel(text)
        lb.setObjectName("kpiSub")
        lb.setWordWrap(True)
        self.body.addWidget(lb)
        return lb


class WelcomeScreen(QtWidgets.QWidget):
    """الشاشة الأولى: نبض اليوم · الخزائن · التنبيهات · آخر العمليات."""

    def __init__(self, user, on_open_ledger=None, on_open_doc=None,
                 on_open_screen=None):
        super().__init__()
        self.user = user
        self.on_open_ledger = on_open_ledger
        self.on_open_doc = on_open_doc
        self.on_open_screen = on_open_screen
        self.setObjectName("welcomeRoot")

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        inner = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(inner)
        lay.setContentsMargins(16, 12, 16, 16)
        lay.setSpacing(12)

        # ── الترويسة: الشعار صغيراً بجوار التحية، لا متوسّطاً للفراغ ──
        head = QtWidgets.QHBoxLayout()
        head.setSpacing(12)
        logo = QtWidgets.QLabel()
        path = (getattr(config, "LOGO_GOLD_PATH", None)
                or getattr(config, "LOGO_PATH", None))
        if path and Path(str(path)).exists():
            pix = QtGui.QPixmap(str(path))
            if not pix.isNull():
                logo.setPixmap(pix.scaledToWidth(
                    96, QtCore.Qt.SmoothTransformation))
        head.addWidget(logo)
        names = QtWidgets.QVBoxLayout()
        names.setSpacing(0)
        who = user.get("full_name") or user.get("username") or ""
        hello = QtWidgets.QLabel(f"أهلاً {who}")
        hello.setObjectName("welcomeName")
        sub = QtWidgets.QLabel(config.COMPANY_NAME)
        sub.setObjectName("welcomeSub")
        names.addWidget(hello)
        names.addWidget(sub)
        head.addLayout(names)
        head.addStretch(1)
        self.stamp = QtWidgets.QLabel("")
        self.stamp.setObjectName("welcomeHint")
        self.stamp.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignBottom)
        head.addWidget(self.stamp)
        lay.addLayout(head)

        hint = QtWidgets.QLabel(
            "Ctrl+K يفتح البحث الموحّد: اسم عميل أو رقم تشغيل أو رقم "
            "فاتورة أو اسم شاشة — وينقلك إليه مباشرةً.")
        hint.setObjectName("welcomeHint")
        lay.addWidget(hint)

        # ── نبض اليوم ──
        self.k_ops = KpiCard("عمليات اليوم", "—", "كل ما رُحِّل اليوم")
        self.k_gold = KpiCard("وزن اليوم", "—", "")
        self.k_in = KpiCard("نقدٌ داخل", "—", "قبضٌ في الصندوق")
        self.k_out = KpiCard("نقدٌ خارج", "—", "صرفٌ من الصندوق")
        pulse = QtWidgets.QHBoxLayout()
        pulse.setSpacing(10)
        for c in (self.k_ops, self.k_gold, self.k_in, self.k_out):
            pulse.addWidget(c, 1)
            c.clicked.connect(
                lambda *_: self._screen("الإغلاق اليومي"))
        lay.addLayout(pulse)

        # ── الخزائن: بطاقة لكل خزينة، نقرةٌ تفتح كشفها ──
        self.treasury_row = QtWidgets.QHBoxLayout()
        self.treasury_row.setSpacing(10)
        self._tcards = {}
        lay.addLayout(self.treasury_row)

        # ── التنبيهات وأقدم الديون جنباً إلى جنب ──
        mid = QtWidgets.QHBoxLayout()
        mid.setSpacing(12)
        self.box_alerts = Box("⚠ ما يحتاج انتباهاً")
        self.box_debts = Box("⏳ أقدم الديون المتأخّرة")
        mid.addWidget(self.box_alerts, 1)
        mid.addWidget(self.box_debts, 1)
        lay.addLayout(mid, 1)

        # ── آخر العمليات ──
        self.box_ops = Box("🧾 آخر ما رُحِّل")
        lay.addWidget(self.box_ops, 1)

        lay.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        self._loaded = False

    # ══════════════ التنقّل ══════════════

    def _screen(self, name):
        if callable(self.on_open_screen):
            self.on_open_screen(name)

    def _ledger(self, code):
        if callable(self.on_open_ledger) and code:
            self.on_open_ledger(code)

    def _doc(self, src, sid):
        if callable(self.on_open_doc) and src and sid:
            self.on_open_doc(src, sid)

    # ══════════════ البيانات ══════════════

    def refresh(self):
        """يقرأ لقطة اليوم ويعيد رسم اللوحات — بلا تعطيل الواجهة أبداً."""
        try:
            from database.database import db
            from models import home_panels as hp
            with db(readonly=True) as conn:
                snap = hp.snapshot(conn)
        except Exception:
            snap = {"pulse": {}, "treasury": [], "negatives": [],
                    "debts": [], "ops": []}
        self._loaded = True
        self._draw_pulse(snap.get("pulse") or {})
        self._draw_treasury(snap.get("treasury") or [])
        self._draw_alerts(snap.get("negatives") or [])
        self._draw_debts(snap.get("debts") or [])
        self._draw_ops(snap.get("ops") or [])

    def _draw_pulse(self, p):
        self.stamp.setText(f"اليوم {p.get('date', '')}")
        n = int(p.get("count") or 0)
        self.k_ops.set(f"{n:,}",
                       "لم تُرحَّل عملية بعد اليوم" if not n
                       else "اضغط لفتح ورقة الإغلاق اليومي")
        self.k_gold.set(kv.fmt(p.get("gold") or 0), kv.unit())
        self.k_in.set(_money(p.get("cash_in")), "ريال")
        net = float(p.get("cash_net") or 0)
        self.k_out.set(_money(p.get("cash_out")),
                       f"صافي الحركة {_money(net)} ريال")

    def _draw_treasury(self, rows):
        while self.treasury_row.count():
            it = self.treasury_row.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
        self._tcards = {}
        for t in rows:
            if t["dim"] == "cash":
                val, sub = _money(t["cash"]), "ريال"
            else:
                val, sub = kv.fmt(t["gold"]), kv.unit()
            c = KpiCard(t["name"], val, sub,
                        "bad" if t["negative"] else "good")
            c.setToolTip(f"حساب {t['code']} — اضغط لفتح كشفه")
            c.clicked.connect(lambda _=None, code=t["code"]:
                              self._ledger(code))
            self.treasury_row.addWidget(c, 1)
            self._tcards[t["code"]] = c
        if not rows:
            self.treasury_row.addWidget(QtWidgets.QLabel(""), 1)

    def _draw_alerts(self, negs):
        self.box_alerts.clear()
        if not negs:
            self.box_alerts.note(
                "✔ لا توجد أرصدة سالبة في الخزائن ولا في الصندوق.\n"
                "الرصيد السالب في مخزونٍ مادي يعني عمليةً نقصت أو "
                "رُحِّلت بتاريخٍ سابق — والنظام ينبّه عليه لحظة حدوثه.")
            return
        for t in negs:
            if t["dim"] == "cash":
                amount = f"{_money(t['cash'])} ريال"
            else:
                amount = f"{kv.fmt(t['gold'])} {kv.unit()}"
            self.box_alerts.row(
                f"⛔  {t['name']}  —  رصيد سالب: {amount}",
                f"حساب {t['code']} — اضغط لفتح كشفه ومعرفة سبب السالب",
                lambda code=t["code"]: self._ledger(code))

    def _draw_debts(self, debts):
        self.box_debts.clear()
        if not debts:
            self.box_debts.note("✔ لا ديون متأخّرة فوق 60 يوماً.")
            return
        for d in debts:
            bits = []
            if abs(d["cash"]) > 0.01:
                bits.append(f"{_money(d['cash'])} ريال")
            if abs(d["gold"]) > 0.001:
                bits.append(f"{kv.fmt(d['gold'])} {kv.unit()}")
            self.box_debts.row(
                f"⏳  {d['name']}  —  {' · '.join(bits)}"
                f"   (أقدم دين {d['days']} يوماً)",
                "اضغط لفتح كشف حسابه في دفتر الأستاذ",
                lambda code=d["code"]: self._ledger(code))
        self.box_debts.row(
            "◂  فتح تقرير أعمار الديون كاملاً",
            "التوزيع على الفئات 30/60/90 لكل الجهات",
            lambda: self._screen("أعمار الديون (30/60/90)"))

    def _draw_ops(self, ops):
        self.box_ops.clear()
        if not ops:
            self.box_ops.note("لم تُرحَّل عمليات بعد.")
            return
        for o in ops:
            bits = []
            if abs(float(o["gold"] or 0)) > 0.001:
                bits.append(f"{kv.fmt(o['gold'])} {kv.unit()}")
            if abs(float(o["cash"] or 0)) > 0.01:
                bits.append(f"{_money(o['cash'])} ريال")
            who = f" — {o['who']}" if o["who"] else ""
            desc = f"  ·  {o['desc'][:40]}" if o["desc"] else ""
            self.box_ops.row(
                f"{o['date']}   {o['op']}   {o['doc_no']}   "
                f"{' · '.join(bits)}{who}{desc}",
                "اضغط لفتح المستند الأصلي",
                lambda src=o["src"], sid=o["sid"]: self._doc(src, sid))
