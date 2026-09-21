# -*- coding: utf-8 -*-
"""ملف الجهة — كل ما يخصّ عميلاً في صفحةٍ واحدة.

**السؤال**: يتّصل العميل فيريد صاحب المصنع أن يعرف حاله الآن: كم
رصيده، وهل تجاوز سقفه، وكم من دينه قديم، وماذا جرى معه الشهر
الماضي، ومتى آخر مرةٍ سدّد، وأيَّ الموديلات يأخذ، وكم يُرجع. وكل
جوابٍ منها في شاشةٍ غير شاشة الأخرى — وسبعُ شاشاتٍ تُفتح في مكالمة
هاتفية تعني أن أحداً لن يفتحها.

┌ أربع لوحات: الرصيد · سقف الائتمان · أقدم دين · آخر تحصيل
├ **الفترة**: جسر الرصيد — ما زاد وما نقص وكم سُدّد
├ **أعمار دينه**: كم منه أقلّ من ٣٠ وكم فوق التسعين
├ **موديلاته**: أكثر ما يأخذ، بالصافي بعد المرتجع
└ **أجرته**: المتفق عليه مقابل المطبَّق وأثر الفرق

لا رقمَ يُحسب هنا: كل قسمٍ يُستدعى من مصدره الأصلي فلا يخالف الكشف.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from models import dossier, entities
from models.aging import BUCKET_LABELS
from services import karat_view as kv
from ui.widgets.common import (Card, big_label, date_edit, dstr, err, fill,
                               ledger_rows, make_table, run_bg, search_combo,
                               tab_widget, title_label)
from ui.widgets.table_fit import fit_columns
from ui.widgets.table_tools import enhance as _enhance


def rnum(v, d=2):
    """السالب بين قوسين — لا بإشارةٍ تزيغ في نصٍّ عربي."""
    return f"({abs(v):,.{d}f})" if v < 0 else f"{v:,.{d}f}"


class DossierScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.res = None

        self.party = search_combo("اكتب اسم الجهة…")
        self.party.setMinimumWidth(300)
        self.party.setMaximumWidth(340)
        self.d_from = date_edit()
        self.d_from.setDate(QtCore.QDate.currentDate().addMonths(-1))
        self.d_to = date_edit()

        btn = QtWidgets.QPushButton("📇 افتح الملف")
        btn.clicked.connect(self.load)
        btn_print = QtWidgets.QPushButton("👁 معاينة وطباعة")
        btn_print.clicked.connect(self.print_report)
        btn_copy = QtWidgets.QPushButton("📋 نسخ الخلاصة")
        btn_copy.setObjectName("ghost")
        btn_copy.clicked.connect(self.copy_summary)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(QtWidgets.QLabel("الجهة:"))
        head.addWidget(self.party, 0)
        head.addWidget(QtWidgets.QLabel("من:"))
        head.addWidget(self.d_from, 0)
        head.addWidget(QtWidgets.QLabel("إلى:"))
        head.addWidget(self.d_to, 0)
        head.addWidget(btn, 0)
        head.addWidget(btn_print, 0)
        head.addWidget(btn_copy, 0)
        head.addStretch(1)

        self.c_bal = Card("الرصيد", "وزناً ونقداً", summary=True)
        self.c_limit = Card("سقف الائتمان", "كم استُهلك منه", summary=True)
        self.c_old = Card("أقدم دين", "منذ كم يوماً")
        self.c_pay = Card("آخر تحصيل", "متى وكم")
        tiles = QtWidgets.QHBoxLayout()
        for c in (self.c_bal, self.c_limit, self.c_old, self.c_pay):
            tiles.addWidget(c)

        self.verdict = big_label("اختر الجهة ثم «افتح الملف».")
        self.verdict.setWordWrap(True)

        self.t_bridge = make_table()
        _enhance(self.t_bridge, key="dossier_bridge")
        self.t_aging = make_table()
        _enhance(self.t_aging, key="dossier_aging")
        self.t_models = make_table()
        _enhance(self.t_models, key="dossier_models")
        self.t_wage = make_table()
        _enhance(self.t_wage, key="dossier_wage")

        self.tabs = tab_widget()
        self.tabs.addTab(self.t_bridge, "الفترة")
        self.tabs.addTab(self.t_aging, "أعمار دينه")
        self.tabs.addTab(self.t_models, "موديلاته")
        self.tabs.addTab(self.t_wage, "أجرته وحركته")

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        lay.addWidget(title_label("ملف الجهة — كل ما يخصّها في صفحة"))
        intro = QtWidgets.QLabel(
            "رصيده وسقفه وأعمار دينه وحركة فترته وآخر تحصيلٍ منه "
            "وموديلاته ونسبة مرتجعه وأجرته — مجموعةً في صفحةٍ تُقرأ "
            "في مكالمةٍ هاتفية. ولا رقمَ يُحسب هنا: كل قسمٍ من مصدره "
            "الأصلي فلا يخالف كشف الحساب.")
        intro.setObjectName("cardSub")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        lay.addLayout(head)
        lay.addLayout(tiles)
        lay.addWidget(self.verdict)
        lay.addWidget(self.tabs, 1)

        QtCore.QTimer.singleShot(0, self._load_parties)

    # ─────────────────────────────── بيانات
    def _load_parties(self):
        try:
            with db(readonly=True) as conn:
                ents = entities.list_entities(conn)
        except Exception as e:
            err(self, e)
            return
        self.party.blockSignals(True)
        self.party.clear()
        for e in ents:
            aid = e["account_id"] if "account_id" in e.keys() else None
            if aid:
                self.party.addItem(e["name"], e["id"])
        self.party.blockSignals(False)
        try:
            self.party.clear_selection()
        except Exception:
            pass

    def load(self):
        eid = self.party.currentData()
        if not eid:
            err(self, "اختر الجهة أولاً")
            return
        d1, d2 = dstr(self.d_from), dstr(self.d_to)

        def _read():
            with db(readonly=True) as conn:
                return dossier.build(conn, eid, d1, d2)

        ok, res, ex = run_bg(_read, parent=self, text="جارٍ فتح الملف…",
                             stage="ملف الجهة", timeout=90.0)
        if ex:
            err(self, ex)
            return
        if not ok:
            self.verdict.setText("تأخّر الحساب — ضيّق الفترة وأعد المحاولة.")
            return
        self.res = res
        self._render()

    # ─────────────────────────────── عرض
    def _render(self):
        d = self.res
        u = kv.unit()

        def w(v):
            return rnum(kv.g(v), 3)

        def m(v):
            return rnum(v, 2)

        b = d["balance"]
        self.c_bal.set_value(w(b["gold"]), f"{u} · {m(b['cash'])} ريال")

        lg, lc = d["limit"]["gold"], d["limit"]["cash"]
        if lg["limit"] or lc["limit"]:
            pct = max(x["pct"] or 0 for x in (lg, lc))
            self.c_limit.set_value(
                f"{pct:,.0f}%",
                ("⚠ تجاوز السقف" if (lg["over"] or lc["over"])
                 else f"متبقٍّ {w(lg['free'] or 0)} {u}"))
        else:
            self.c_limit.set_value("—", "بلا سقفٍ محدَّد")

        a = d["aging"]
        self.c_old.set_value(f"{a['days']:,}" if a else "—",
                             (f"يوماً · منذ {a['oldest']}" if a
                              else "لا دينَ قائم"))
        lr = d["last_receipt"]
        self.c_pay.set_value(
            lr["date"] if lr else "—",
            (f"{w(lr['gold'])} {u} · {m(lr['cash'])} ريال"
             if lr else "لم يُسدَّد منه شيءٌ قط"))
        self.verdict.setText("   ·   ".join(dossier.verdict(d, w, m)))

        self._fill_bridge(d, u, w, m)
        self._fill_aging(d, u, w, m)
        self._fill_models(d, u, w, m)
        self._fill_wage(d, u, w, m)

    def _fill_bridge(self, d, u, w, m):
        """جسر الرصيد للفترة — مصدره `movement` نفسه لا حسابٌ جديد."""
        r = d["bridge"]
        rows = [("رصيد أول المدة", w(r["opening"]["gold"]),
                 m(r["opening"]["cash"]), "", "")]
        for x in r["buckets"]:
            if abs(x["gold"]) < 0.0005 and abs(x["cash"]) < 0.005:
                continue
            rows.append((x["label"], w(x["gold"]), m(x["cash"]),
                         f"{x['docs']:,}", f"{x['days']:,}"))
        marks = [0, len(rows)]
        rows.append(("رصيد آخر المدة", w(r["closing"]["gold"]),
                     m(r["closing"]["cash"]), "", ""))
        fill(self.t_bridge,
             ["البند", f"الوزن ({u})", "النقد (ريال)", "مستندات", "أيام"],
             rows)
        fit_columns(self.t_bridge, [30, 20, 20, 15, 15])
        ledger_rows(self.t_bridge, wrap_cols=(0,))
        self._mark(self.t_bridge, marks)
        dd = r["days"]
        self.tabs.setTabText(
            0, f"الفترة ({dd['active']} من {dd['span']} يوماً)")

    def _fill_aging(self, d, u, w, m):
        a = d["aging"]
        if not a:
            fill(self.t_aging, ["الفئة العمرية", f"الوزن ({u})",
                                "النقد (ريال)"],
                 [("لا دينَ قائمٌ على هذه الجهة", "—", "—")])
            return
        rows = [(BUCKET_LABELS[i], w(a["gold_buckets"][i]),
                 m(a["cash_buckets"][i])) for i in range(len(BUCKET_LABELS))]
        marks = [len(rows)]
        rows.append(("الإجمالي المدين", w(a["gold"]), m(a["cash"])))
        if a["gold_credit"] or a["cash_credit"]:
            rows.append(("رصيدٌ دائن (له علينا) — لا عمر له",
                         w(a["gold_credit"]), m(a["cash_credit"])))
        fill(self.t_aging,
             ["الفئة العمرية", f"الوزن ({u})", "النقد (ريال)"], rows)
        fit_columns(self.t_aging, [40, 30, 30])
        ledger_rows(self.t_aging, wrap_cols=(0,))
        self._mark(self.t_aging, marks)

    def _fill_models(self, d, u, w, m):
        rows = []
        for src, tag in ((d["models"], "الفترة"),
                         (d["models_life"], "من البداية")):
            for x in src:
                rows.append((tag, x["model"], f"{x['sold']:,}",
                             f"{x['returned']:,}", f"{x['net_count']:,}",
                             w(x["weight"]), m(x["wages"])))
        fill(self.t_models,
             ["النطاق", "الموديل", "خرج", "رجع", "الصافي",
              f"الوزن الصافي ({u})", "الأجور (ريال)"], rows)
        fit_columns(self.t_models, [14, 24, 10, 10, 11, 16, 15])
        ledger_rows(self.t_models, wrap_cols=(1,))
        self.tabs.setTabText(2, f"موديلاته ({len(d['models_life'])})")

    def _fill_wage(self, d, u, w, m):
        f, fl, wg = d["flow"], d["flow_life"], d["wage"]

        def _pct(v):
            return f"{v:,.1f}%" if v is not None else "—"

        rows = [
            ("ما خرج إليه", w(f["out_weight"]), w(fl["out_weight"]),
             f"{f['sold_lines']:,} / {fl['sold_lines']:,} سطراً"),
            ("ما رجع منه", w(f["back_weight"]), w(fl["back_weight"]),
             f"{f['return_lines']:,} / {fl['return_lines']:,} سطراً"),
            ("الصافي", w(f["net_weight"]), w(fl["net_weight"]), ""),
            ("نسبة المرتجع (بالوزن)", _pct(f["return_pct"]),
             _pct(fl["return_pct"]), "بالوزن لا بالعدد"),
            ("أجور ما خرج (ريال)", m(f["out_wages"]), m(fl["out_wages"]),
             ""),
        ]
        # يُبرَز ما يُقرأ حكماً: نسبة المرتجع وأثر فرق الأجرة
        marks = [3]
        rows += [
            ("الأجرة المتفق عليها",
             m(kv.rate(wg["agreed"])) if wg["agreed"] else "بلا اتفاق",
             "", "من بطاقة الجهة"),
            ("متوسط الأجرة المطبَّقة",
             m(kv.rate(wg["avg_applied"])) if wg["avg_applied"] else "—",
             "", f"{wg['lines']:,} سطراً في الفترة"),
            ("أثر فرق الأجرة (ريال)", m(wg["impact"]), "",
             f"{wg['deviations']:,} سطراً مخالفاً"),
        ]
        marks.append(len(rows) - 1)
        fill(self.t_wage,
             ["البند", "الفترة", "من البداية", "ملاحظة"], rows)
        fit_columns(self.t_wage, [30, 20, 20, 30])
        ledger_rows(self.t_wage, wrap_cols=(0, 3))
        self._mark(self.t_wage, marks)

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
            err(self, "افتح الملف أولاً")
            return
        from services import print_manager
        try:
            print_manager.preview_document(
                self, "dossier", self.res["entity"]["id"],
                date_from=self.res["date_from"], date_to=self.res["as_of"])
        except Exception as e:
            err(self, e)

    def copy_summary(self):
        if not self.res:
            return
        d = self.res
        u = kv.unit()

        def w(v):
            return rnum(kv.g(v), 3)

        def m(v):
            return rnum(v, 2)

        out = [f"ملف الجهة — {d['entity']['name']}",
               f"الفترة: {d['date_from']} إلى {d['as_of']}", "",
               *dossier.verdict(d, w, m), "",
               f"  الرصيد      : {w(d['balance']['gold'])} {u} · "
               f"{m(d['balance']['cash'])} ريال"]
        a = d["aging"]
        if a:
            out.append(f"  أقدم دين    : {a['days']:,} يوماً ({a['oldest']})")
        lr = d["last_receipt"]
        out.append(f"  آخر تحصيل   : "
                   + (f"{lr['date']} — {w(lr['gold'])} {u} · "
                      f"{m(lr['cash'])} ريال" if lr else "لا شيء"))
        f = d["flow"]
        out.append(f"  خرج/رجع     : {w(f['out_weight'])} / "
                   f"{w(f['back_weight'])} {u}"
                   + (f"  (مرتجع {f['return_pct']:,.1f}%)"
                      if f["return_pct"] is not None else ""))
        if d["models"]:
            out.append("  موديلاته    : "
                       + "، ".join(x["model"] for x in d["models"][:5]))
        QtWidgets.QApplication.clipboard().setText("\n".join(out))
        self.verdict.setText("نُسخت الخلاصة — الصقها في أي رسالة.")

    def refresh(self):
        if self.res:
            self.load()
