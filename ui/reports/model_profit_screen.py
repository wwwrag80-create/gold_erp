# -*- coding: utf-8 -*-
"""ربحية الموديل — أيّ موديلٍ يكسب المصنع، وأيّه مالٌ راكد.

**السؤال الذي تجيبه**: النظام يعرف كم طقماً أُنتج من كل موديل وكم
بِيع، ولم يكن يعرف **كم كسب** منه. فقرار «أيّ موديلٍ نُكثر منه» كان
يُتّخذ بالانطباع: ما يُرى يخرج كثيراً — وهو قد يكون كثيرَ الخروج
قليلَ الأجرة.

لوحان: **ما كسب** (من الفواتير، والمرتجع مطروح)، و**ما لم يُبَع بعد**
(من المخزون، بأجرته المتوقَّعة) — فالسؤالان مختلفان ولكلٍّ جدوله.

قراءة محضة: لا تكتب رقماً ولا تُنشئ قيداً.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from models import model_profit as mp
from services import karat_view as kv
from ui.widgets.common import (Card, big_label, busy, date_edit, dstr, err,
                               fill, make_table, title_label)
from ui.widgets.table_tools import enhance as _enhance


def _cols():
    u = kv.unit()
    return ["الموديل", "مباع", "مرتجع", "الصافي", f"الوزن الصافي ({u})",
            "صافي الأجور (ريال)", "متوسط أجرة الجرام", "حصته من الأجور %",
            "فصوص", "أحجار"]


def _cols_unsold():
    return ["الموديل", "أطقم في المخزن", f"الوزن ({kv.unit()})",
            "متوسط أجرة الجرام", "أجرة لم تُحصَّل بعد (ريال)"]


class ModelProfitScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.rows = []

        self.d_from = date_edit()
        self.d_from.setDate(QtCore.QDate(QtCore.QDate.currentDate().year(),
                                         1, 1))
        self.d_to = date_edit()
        btn = QtWidgets.QPushButton("📊 إعداد التقرير")
        btn.clicked.connect(self.load)
        btn_copy = QtWidgets.QPushButton("📋 نسخ الجدول")
        btn_copy.setObjectName("ghost")
        btn_copy.clicked.connect(self.copy_table)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("من:"))
        top.addWidget(self.d_from)
        top.addWidget(QtWidgets.QLabel("إلى:"))
        top.addWidget(self.d_to)
        top.addWidget(btn)
        top.addWidget(btn_copy)
        top.addStretch(1)

        self.c_models = Card("موديلات بِيع منها", "خلال الفترة")
        self.c_wages = Card("صافي الأجور", "بعد طرح المرتجع")
        self.c_avg = Card("متوسط أجرة الجرام", "للمصنع كله")
        self.c_top = Card("أعلى موديل", "بصافي أجوره")
        tiles = QtWidgets.QHBoxLayout()
        for c in (self.c_models, self.c_wages, self.c_avg, self.c_top):
            tiles.addWidget(c)

        self.table = make_table()
        _enhance(self.table, key="model_profit")
        self.table_unsold = make_table()
        _enhance(self.table_unsold, key="model_unsold")
        self.state = big_label("اختر الفترة ثم «إعداد التقرير».")

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self.table, "ما كسب (من الفواتير)")
        tabs.addTab(self.table_unsold, "ما لم يُبَع بعد (من المخزن)")

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("ربحية الموديل — أين يكسب المصنع"))
        intro = QtWidgets.QLabel(
            "مصدر الربح في مصنع ذهب هو **الأجرة** لا الذهب: الذهب يدخل "
            "ويخرج بوزنه (انتقال أصلٍ لا بيع)، والمكسب أجرةُ التصنيع على "
            "كل جرام. فالأجرة هنا مقروءةٌ من بنود الفواتير المباعة فعلاً "
            "— لا المقدَّرة وقت الإنتاج — والمرتجع مطروح.")
        intro.setObjectName("cardSub")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        lay.addLayout(top)
        lay.addLayout(tiles)
        lay.addWidget(self.state)
        lay.addWidget(tabs, 1)
        note = QtWidgets.QLabel(
            "«ما لم يُبَع بعد» أجرةٌ متوقَّعة لا محقَّقة: هي ما كان المصنع "
            "سيكسبه لو بِيع ما في المخزن بأجرته المسجّلة — تُقرأ لقياس "
            "الركود، ولا تدخل في أي قائمة دخل.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)

    def load(self):
        try:
            with busy(self, "جارٍ حساب ربحية الموديلات…",
                      stage="ربحية الموديل"):
                with db(readonly=True) as conn:
                    self.rows = mp.by_model(conn, dstr(self.d_from),
                                            dstr(self.d_to))
                    unsold = mp.unsold(conn)
        except Exception as e:
            err(self, e)
            return
        t = mp.totals(self.rows)
        data = [(r["model"], r["sold"], r["returned"], r["net_count"],
                 f"{kv.g(r['net_weight']):,.3f}", f"{r['wages']:,.2f}",
                 f"{r['avg_wage']:,.2f}", f"{r['share']:,.1f}",
                 f"{kv.g(r['small_stones']):,.2f}",
                 f"{kv.g(r['big_stones']):,.2f}") for r in self.rows]
        if data:
            data.append(("الإجمالي", "", "", t["net_count"],
                         f"{kv.g(t['net_weight']):,.3f}",
                         f"{t['wages']:,.2f}", f"{t['avg_wage']:,.2f}",
                         "100.0", f"{kv.g(t['small_stones']):,.2f}",
                         f"{kv.g(t['big_stones']):,.2f}"))
        fill(self.table, _cols(), data)
        self._bold_last(self.table, len(data))

        fill(self.table_unsold, _cols_unsold(),
             [(u["model"], u["count"], f"{kv.g(u['weight']):,.3f}",
               f"{u['wage_per_gram']:,.2f}", f"{u['potential']:,.2f}")
              for u in unsold])

        self.c_models.set_value(f"{t['models']:,}",
                                f"{t['net_count']:,} طقماً صافياً")
        self.c_wages.set_value(f"{t['wages']:,.2f}", "ريال")
        self.c_avg.set_value(f"{t['avg_wage']:,.2f}",
                             f"ريال لكل {kv.unit()}")
        best = self.rows[0] if self.rows else None
        self.c_top.set_value(best["model"] if best else "—",
                             f"{best['wages']:,.2f} ريال · "
                             f"{best['share']:,.1f}%" if best else "")
        idle = sum(u["potential"] for u in unsold)
        self.state.setText(
            f"{t['models']:,} موديلاً بِيع منه خلال الفترة · صافي أجوره "
            f"{t['wages']:,.2f} ريال"
            + (f"   |   وفي المخزن أجرةٌ لم تُحصَّل بعد: {idle:,.2f} ريال"
               if idle else ""))

    def _bold_last(self, table, n):
        """صف الإجمالي يُميَّز: العين تلتقطه قبل أن تقرأ الأرقام."""
        if n < 1:
            return
        for c in range(table.columnCount()):
            it = table.item(n - 1, c)
            if it is None:
                continue
            f = it.font()
            f.setBold(True)
            it.setFont(f)
            try:
                it.setBackground(QtGui.QColor("#EFE9DC"))
            except Exception:
                pass

    def copy_table(self):
        """ينسخ الجدول نصّاً مفصولاً بجدولات — يُلصق في أي جدول بيانات."""
        if not self.rows:
            return
        out = ["\t".join(_cols())]
        for r in self.rows:
            out.append("\t".join(str(x) for x in (
                r["model"], r["sold"], r["returned"], r["net_count"],
                round(kv.g(r["net_weight"]), 3), round(r["wages"], 2),
                round(r["avg_wage"], 2), round(r["share"], 1),
                round(kv.g(r["small_stones"]), 2),
                round(kv.g(r["big_stones"]), 2))))
        QtWidgets.QApplication.clipboard().setText("\n".join(out))
        self.state.setText("نُسخ الجدول — الصقه في أي جدول بيانات.")

    def refresh(self):
        self.load()
