# -*- coding: utf-8 -*-
"""الإغلاق اليومي — ورقة واحدة تُراجع بها اليوم قبل إقفال الدرج.

قراءة محضة: لا تُنشئ قيداً ولا تُقفل حساباً. الإقفال المحاسبي سنويٌّ
وله شاشته المستقلة.
"""
from PyQt5 import QtCore, QtWidgets

from database.database import db
from models import day_close
from services import karat_view as kv
from ui.widgets.common import (Card, big_label, date_edit, dstr, err, fill,
                               make_table, title_label)


class DayCloseScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.data = None

        self.date = date_edit()
        btn = QtWidgets.QPushButton("عرض اليوم")
        btn.clicked.connect(self.refresh)
        btn_yesterday = QtWidgets.QPushButton("أمس")
        btn_yesterday.setObjectName("ghost")
        btn_yesterday.clicked.connect(self._yesterday)
        btn_print = QtWidgets.QPushButton("👁 معاينة وطباعة")
        btn_print.clicked.connect(self.print_report)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(QtWidgets.QLabel("اليوم:"))
        head.addWidget(self.date, 0)
        head.addWidget(btn_yesterday, 0)
        head.addWidget(btn, 0)
        head.addStretch(1)
        head.addWidget(btn_print, 0)

        self.c_docs = Card("عدد العمليات", "مستند")
        self.c_gold = Card("حركة الذهب", kv.unit())
        self.c_cash_in = Card("داخل للصندوق", "ريال")
        self.c_cash_out = Card("خارج من الصندوق", "ريال")
        cards = QtWidgets.QHBoxLayout()
        cards.setSpacing(4)
        for c in (self.c_docs, self.c_gold, self.c_cash_in, self.c_cash_out):
            cards.addWidget(c)

        self.kinds = make_table()
        self.balances = make_table()
        self.docs = make_table()
        self.summary = big_label()

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self._wrap(self.kinds), "حركة اليوم بأنواعها")
        tabs.addTab(self._wrap(self.balances), "الأرصدة الختامية")
        tabs.addTab(self._wrap(self.docs), "مستندات اليوم")

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        lay.addWidget(title_label(
            "الإغلاق اليومي — حركة اليوم وأرصدته في صفحة واحدة"))
        lay.addLayout(head)
        lay.addLayout(cards)
        lay.addWidget(tabs, 1)
        lay.addWidget(self.summary)
        hint = QtWidgets.QLabel(
            "قراءة محضة: لا يُنشأ قيد ولا يُقفل حساب. الأرصدة الختامية "
            "محسوبة حتى نهاية اليوم المختار — والتجميعية منها تشمل كل "
            "فروعها.")
        hint.setObjectName("cardSub")
        hint.setWordWrap(True)
        lay.addWidget(hint)

    @staticmethod
    def _wrap(widget):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(widget)
        return w

    def _yesterday(self):
        self.date.setDate(QtCore.QDate.currentDate().addDays(-1))
        self.refresh()

    def refresh(self):
        try:
            with db(readonly=True) as conn:
                d = day_close.summary(conn, dstr(self.date))
            self.data = d
            self.c_docs.set_value(f"{d['count']:,}")
            self.c_gold.set_value(f"{kv.g(d['gold_total']):,.3f}",
                                  kv.unit())
            self.c_cash_in.set_value(f"{d['cash_in']:,.2f}")
            self.c_cash_out.set_value(f"{d['cash_out']:,.2f}",
                                      f"الصافي {d['cash_net']:+,.2f}")

            fill(self.kinds,
                 ["نوع العملية", "العدد", f"الذهب ({kv.unit()})",
                  "النقد (ريال)"],
                 [(k["op"], k["count"], f"{kv.g(k['gold']):,.3f}",
                   f"{k['cash']:,.2f}") for k in d["kinds"]])

            fill(self.balances,
                 ["الحساب", "الكود", f"رصيد الذهب ({kv.unit()})",
                  "الرصيد النقدي (ريال)", "الحالة"],
                 [(b["name"], b["code"],
                   f"{kv.g(abs(b['gold'])):,.3f}"
                   if b["dim"] != "cash" else "—",
                   f"{abs(b['cash']):,.2f}" if b["dim"] != "gold" else "—",
                   "مدين" if (b["gold"] > 0 or b["cash"] > 0)
                   else ("دائن" if (b["gold"] < 0 or b["cash"] < 0)
                         else "متزن"))
                  for b in d["balances"]])

            fill(self.docs,
                 ["الوقت", "نوع العملية", "رقم السند", "الحسابات",
                  f"الذهب ({kv.unit()})", "النقد", "المستخدم"],
                 [((r["when"] or "")[11:16] or "—", r["op"], r["doc_no"],
                   r["accounts"],
                   f"{kv.g(r['gold']):,.3f}" if r["gold"] else "",
                   f"{r['cash']:,.2f}" if r["cash"] else "",
                   r["who"]) for r in d["docs"]])

            who = "   ·   ".join(f"{u['user']}: {u['count']}"
                                 for u in d["users"]) or "—"
            self.summary.setText(
                f"يوم {d['date']}   |   {d['count']} عملية   |   "
                f"إدخال المستخدمين — {who}")
        except Exception as e:
            err(self, e)

    def print_report(self):
        from services import print_manager
        try:
            print_manager.preview_document(self, "day_close", 0,
                                           date=dstr(self.date))
        except Exception as e:
            err(self, e)
