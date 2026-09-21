# -*- coding: utf-8 -*-
"""انحرافات الأجرة — أين يتسرّب الربح بلا أن يُرى.

**السؤال**: ربح مصنع الذهب هو **الأجرة على الجرام**. والمصنع يتفق مع
كل عميلٍ على أجرة، ثم يُدخل البائع الرقم في كل سطرٍ من ذاكرته —
فينزل عميلٌ درجةً بلا أن يدري أحد. الفاتورة سليمة، والقيد متوازن،
والميزان يقفل؛ الخطأ أن **أحداً لم يقارن**.

┌ أربع لوحات: أقلّ من المتفق · أعلى منه · الصافي · نسبة المطابقة
├ **بالعميل**: من انحرف وكم، ومتوسط المطبَّق مقابل المتفق
├ **سطراً سطراً**: أسوأ الأسطر أولاً، بفاتورتها وطقمها
└ **بلا اتفاق**: جهاتٌ تبيع لها ولم تُكتب أجرتها بعد

قراءةٌ محضة: لا تكتب رقماً ولا تُنشئ قيداً.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from models import wage_audit as wa
from services import karat_view as kv
from ui.widgets.common import (Card, big_label, date_edit, dstr, err, fill,
                               ledger_rows, make_table, run_bg, tab_widget,
                               title_label)
from ui.widgets.table_fit import fit_columns
from ui.widgets.table_tools import enhance as _enhance


def rnum(v):
    """ريالٌ يُقرأ — والسالب بين قوسين لا بإشارةٍ تزيغ في نصٍّ عربي."""
    return f"({abs(v):,.2f})" if v < 0 else f"{v:,.2f}"


class WageAuditScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.res = None

        self.d_from = date_edit()
        self.d_from.setDate(QtCore.QDate.currentDate().addMonths(-1))
        self.d_to = date_edit()
        self.only_dev = QtWidgets.QCheckBox("الانحرافات فقط")
        self.only_dev.setChecked(True)
        self.only_dev.setToolTip(
            "بلا تأشير تُعرض الأسطر المطابقة أيضاً — لمراجعةٍ كاملة")

        btn = QtWidgets.QPushButton("🔍 فحص الأجور")
        btn.clicked.connect(self.load)
        btn_print = QtWidgets.QPushButton("👁 معاينة وطباعة")
        btn_print.clicked.connect(self.print_report)
        btn_copy = QtWidgets.QPushButton("📋 نسخ الخلاصة")
        btn_copy.setObjectName("ghost")
        btn_copy.clicked.connect(self.copy_summary)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(QtWidgets.QLabel("من:"))
        head.addWidget(self.d_from, 0)
        head.addWidget(QtWidgets.QLabel("إلى:"))
        head.addWidget(self.d_to, 0)
        head.addWidget(self.only_dev, 0)
        head.addWidget(btn, 0)
        head.addWidget(btn_print, 0)
        head.addWidget(btn_copy, 0)
        head.addStretch(1)

        self.c_loss = Card("أقلّ من المتفق", "ربحٌ لم يدخل", summary=True)
        self.c_gain = Card("أعلى من المتفق", "راجعها قبل العميل",
                           summary=True)
        self.c_net = Card("الصافي", "أثر الانحرافات كلّها")
        self.c_match = Card("نسبة المطابقة", "من الأسطر المقيسة")
        tiles = QtWidgets.QHBoxLayout()
        for c in (self.c_loss, self.c_gain, self.c_net, self.c_match):
            tiles.addWidget(c)

        self.verdict = big_label("اختر الفترة ثم «فحص الأجور».")
        self.verdict.setWordWrap(True)

        self.t_parties = make_table()
        _enhance(self.t_parties, key="wage_audit_parties")
        self.t_lines = make_table()
        _enhance(self.t_lines, key="wage_audit_lines")
        self.t_missing = make_table()
        _enhance(self.t_missing, key="wage_audit_missing")

        self.tabs = tab_widget()
        self.tabs.addTab(self.t_parties, "بالعميل")
        self.tabs.addTab(self.t_lines, "سطراً سطراً")
        self.tabs.addTab(self.t_missing, "بلا اتفاق")

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        lay.addWidget(title_label("انحرافات الأجرة — أين يتسرّب الربح"))
        intro = QtWidgets.QLabel(
            "أجرةٌ نقصت ريالاً واحداً على عشرة كيلوات عشرةُ آلافِ ريالٍ "
            "ضاعت في شهر — ولا يظهر ذلك في أي تقرير لأن الفاتورة سليمة "
            "والقيد متوازن. هنا تُقاس كلُّ فاتورةٍ بالاتفاق الذي كان "
            "نافذاً «يوم صدورها»، فلا يصير تغييرُ الاتفاق انحرافاً.")
        intro.setObjectName("cardSub")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        lay.addLayout(head)
        lay.addLayout(tiles)
        lay.addWidget(self.verdict)
        lay.addWidget(self.tabs, 1)
        note = QtWidgets.QLabel(
            "الأثر بالمال لا بالفرق: (المطبَّق − المتفق) × الوزن — "
            "وإشارته في المرتجع معكوسة لأن الوزن يعود لا يخرج. وما لا "
            "اتفاق له ليس انحرافاً: يُفرز في «بلا اتفاق» تذكيراً بأن "
            "تُكتب أجرته في بطاقة الجهة.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)

    # ─────────────────────────────── بيانات
    def load(self):
        d1, d2 = dstr(self.d_from), dstr(self.d_to)
        only = self.only_dev.isChecked()

        def _read():
            with db(readonly=True) as conn:
                return wa.report(conn, d1, d2, only)

        ok, res, ex = run_bg(_read, parent=self, text="جارٍ فحص الأجور…",
                             stage="انحرافات الأجرة", timeout=120.0)
        if ex:
            err(self, ex)
            return
        if not ok:
            self.verdict.setText("تأخّر الفحص — ضيّق الفترة وأعد المحاولة.")
            return
        self.res = res
        self._render()

    # ─────────────────────────────── عرض
    def _render(self):
        r = self.res
        u = kv.unit()
        t = r["total"]

        def w(v):
            return f"{kv.g(v):,.3f}"

        self.c_loss.set_value(f"{abs(r['loss']):,.2f}",
                              f"ريال · {t['below']:,} سطراً")
        self.c_gain.set_value(f"{r['gain']:,.2f}",
                              f"ريال · {t['above']:,} سطراً")
        self.c_net.set_value(rnum(t["impact"]),
                             "ريال — سالبٌ يعني نقصاً عن المتفق")
        self.c_match.set_value(f"{t['match_pct']:,.1f}%",
                               f"{t['match']:,} من {t['lines']:,} سطراً")
        self.verdict.setText("   ·   ".join(wa.verdict(r)))

        # ── بالعميل ──
        cols = ["العميل", "أسطر", f"الوزن ({u})", "متوسط المطبَّق",
                "متوسط المتفق", "أقلّ", "أعلى", "مطابق", "الأثر (ريال)"]
        data = [(p["name"], f"{p['lines']:,}", w(p["weight"]),
                 f"{p['avg_applied']:,.2f}", f"{p['avg_agreed']:,.2f}",
                 f"{p['below']:,}", f"{p['above']:,}", f"{p['match']:,}",
                 rnum(p["impact"])) for p in r["parties"]]
        if data:
            data.append(("الإجمالي", f"{t['lines']:,}", w(t["weight"]),
                         f"{t['avg_applied']:,.2f}",
                         f"{t['avg_agreed']:,.2f}", f"{t['below']:,}",
                         f"{t['above']:,}", f"{t['match']:,}",
                         rnum(t["impact"])))
        fill(self.t_parties, cols, data)
        fit_columns(self.t_parties, [24, 8, 13, 13, 13, 7, 7, 8, 15])
        ledger_rows(self.t_parties, wrap_cols=(0,))
        if data:
            self._mark(self.t_parties, [len(data) - 1])

        # ── سطراً سطراً ──
        fill(self.t_lines,
             ["التاريخ", "الفاتورة", "النوع", "العميل", "رقم التشغيل",
              "الموديل", f"الوزن ({u})", "المطبَّق", "المتفق", "الفرق",
              "الحالة", "الأثر (ريال)"],
             [(x["date"], x["invoice_no"],
               "بيع" if x["kind"] == "sale" else "مرتجع",
               x["party"], x["wo_no"], x["model"], w(x["weight"]),
               f"{x['applied']:,.2f}", f"{x['agreed']:,.2f}",
               rnum(x["diff"]), x["state"], rnum(x["impact"]))
              for x in r["lines"]])
        fit_columns(self.t_lines,
                    [11, 11, 7, 18, 11, 11, 11, 9, 9, 9, 13, 12])
        ledger_rows(self.t_lines, wrap_cols=(3,))
        self.tabs.setTabText(1, f"سطراً سطراً ({len(r['lines'])})")

        # ── بلا اتفاق ──
        fill(self.t_missing,
             ["الجهة", "أسطر", f"الوزن ({u})", "الأجور المحصَّلة (ريال)"],
             [(x["name"], f"{x['lines']:,}", w(x["weight"]),
               rnum(x["wages"])) for x in r["missing"]])
        fit_columns(self.t_missing, [40, 12, 20, 28])
        ledger_rows(self.t_missing, wrap_cols=(0,))
        self.tabs.setTabText(2, f"بلا اتفاق ({len(r['missing'])})")

    def _mark(self, table, rows):
        from ui import theme
        pal = theme.palette(theme.current_theme())
        bg = QtGui.QColor(pal.get("sumBg", "#FDF3E2"))
        ink = QtGui.QColor(pal.get("sumInk", "#7A4F10"))
        for i in rows:
            for c in range(table.columnCount()):
                it = table.item(i, c)
                if it is None:
                    continue
                f = it.font()
                f.setBold(True)
                it.setFont(f)
                it.setBackground(bg)
                it.setForeground(ink)

    # ─────────────────────────────── مخرجات
    def print_report(self):
        if not self.res:
            err(self, "افحص الأجور أولاً")
            return
        from services import print_manager
        try:
            print_manager.preview_document(
                self, "wage_audit", 0, date_from=self.res["date_from"],
                date_to=self.res["date_to"],
                only_deviations=self.only_dev.isChecked())
        except Exception as e:
            err(self, e)

    def copy_summary(self):
        if not self.res:
            return
        r = self.res
        t = r["total"]
        out = [f"انحرافات الأجرة — من {r['date_from']} إلى {r['date_to']}",
               "", *wa.verdict(r), ""]
        for p in r["parties"]:
            if abs(p["impact"]) < 0.005:
                continue
            out.append(f"  {p['name']:<24} {rnum(p['impact']):>14} ريال   "
                       f"(مطبَّق {p['avg_applied']:,.2f} · متفق "
                       f"{p['avg_agreed']:,.2f})")
        out += ["", f"  الصافي: {rnum(t['impact'])} ريال · "
                    f"المطابقة {t['match_pct']:,.1f}%"]
        if r["missing"]:
            out.append("  بلا اتفاق: "
                       + "، ".join(x["name"] for x in r["missing"]))
        QtWidgets.QApplication.clipboard().setText("\n".join(out))
        self.verdict.setText("نُسخت الخلاصة — الصقها في أي رسالة.")

    def refresh(self):
        if self.res:
            self.load()
