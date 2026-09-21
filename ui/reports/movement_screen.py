# -*- coding: utf-8 -*-
"""تحليل حركة الرصيد — من أين جاء الرصيد وإلى أين ذهب.

**السؤال**: «كانت مديونية العميل ٤٠ كيلو. أجيء بعد شهرٍ فأريد أن
أعرف كم صارت، وماذا حصل: كم خرج وكم رجع وكم سُدّد — وفي كم يوم».

وكشف الحساب لا يجيبه: هو سردٌ زمني، مئةُ سطرٍ يُقرأ منها كل شيء ولا
يُفهم منها شيء. فهذه الشاشة تقلب السرد إلى **جواب**:

┌ الخلاصة بجملةٍ واحدة تُقرأ قبل الأرقام
├ **جسر الرصيد**: أول المدة + ما زاد − ما نقص = آخر المدة
├ **نشاط الأيام**: في كم يومٍ كان بيعٌ ومرتجعٌ وتحصيل
└ **الجدول اليومي**: كيف مشى الرصيد يوماً بيوم

قراءةٌ محضة: لا تكتب رقماً ولا تُنشئ قيداً.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from models import entities, movement
from models.accounts import list_postable
from services import karat_view as kv
from ui.widgets.common import (Card, big_label, date_edit, dstr, err, fill,
                               make_table, run_bg, search_combo, tab_widget,
                               title_label)
from ui.widgets.table_tools import enhance as _enhance


class MovementScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.res = None

        self.account = search_combo("اكتب اسم الجهة أو رقم الحساب…")
        self.account.setMinimumWidth(300)
        self.account.setMaximumWidth(340)
        self.d_from = date_edit()
        self.d_from.setDate(QtCore.QDate.currentDate().addMonths(-1))
        self.d_to = date_edit()
        self.dim = QtWidgets.QComboBox()
        self.dim.setMaximumWidth(120)
        self.dim.addItem("الذهب", "gold")
        self.dim.addItem("النقد", "cash")
        self.dim.currentIndexChanged.connect(self._render)
        btn = QtWidgets.QPushButton("📊 تحليل الفترة")
        btn.clicked.connect(self.load)
        btn_copy = QtWidgets.QPushButton("📋 نسخ الخلاصة")
        btn_copy.setObjectName("ghost")
        btn_copy.clicked.connect(self.copy_summary)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(QtWidgets.QLabel("الحساب:"))
        head.addWidget(self.account, 0)
        head.addWidget(QtWidgets.QLabel("من:"))
        head.addWidget(self.d_from, 0)
        head.addWidget(QtWidgets.QLabel("إلى:"))
        head.addWidget(self.d_to, 0)
        head.addWidget(QtWidgets.QLabel("البعد:"))
        head.addWidget(self.dim, 0)
        head.addWidget(btn, 0)
        head.addWidget(btn_copy, 0)
        head.addStretch(1)

        # الرصيدان لوحتا خلاصة — وهما الرقمان اللذان فُتحت الشاشة لهما
        self.c_open = Card("رصيد أول المدة", "", summary=True)
        self.c_close = Card("رصيد آخر المدة", "", summary=True)
        self.c_change = Card("صافي التغيّر", "زيادة الدين أم نقصه")
        self.c_days = Card("أيام فيها حركة", "من أيام الفترة")
        tiles = QtWidgets.QHBoxLayout()
        for c in (self.c_open, self.c_close, self.c_change, self.c_days):
            tiles.addWidget(c)

        self.verdict = QtWidgets.QLabel("اختر الحساب والفترة ثم «تحليل».")
        self.verdict.setObjectName("big")
        self.verdict.setWordWrap(True)

        self.t_bridge = make_table()
        _enhance(self.t_bridge, key="mv_bridge")
        self.t_days = make_table()
        _enhance(self.t_days, key="mv_days")
        self.t_daily = make_table()
        _enhance(self.t_daily, key="mv_daily")

        tabs = tab_widget()
        tabs.addTab(self.t_bridge, "جسر الرصيد")
        tabs.addTab(self.t_days, "نشاط الأيام")
        tabs.addTab(self.t_daily, "يوماً بيوم")

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        lay.addWidget(title_label(
            "تحليل حركة الرصيد — من أين جاء وإلى أين ذهب"))
        intro = QtWidgets.QLabel(
            "كشف الحساب يسرد الحركات؛ هذه الشاشة تُجيب: كم كان الرصيد "
            "أول المدة، وكم خرج وكم رجع وكم سُدّد، وكم صار آخرها — "
            "وفي كم يومٍ من الفترة جرى كلُّ نوع.")
        intro.setObjectName("cardSub")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        lay.addLayout(head)
        lay.addLayout(tiles)
        lay.addWidget(self.verdict)
        lay.addWidget(tabs, 1)
        note = QtWidgets.QLabel(
            "الجسر يقفل دائماً: أثر كل حركة يُؤخذ من «مدين − دائن» لا "
            "من اسمها، فلا يسقط منه شيء ولو أُضيف نوعُ عملياتٍ جديد. "
            "وما لا يُعرف اسمه يظهر في «أخرى» ولا يضيع. والأرصدة "
            "الافتتاحية والقيود اليومية تُضمّ إلى «رصيد أول المدة» "
            "لأنها رصيدُ بدايةٍ لا حركة — وتلميحُ السطر يقول كم ضُمّ.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)

        QtCore.QTimer.singleShot(0, self._load_accounts)

    # ─────────────────────────────── بيانات
    def _load_accounts(self):
        """الجهات أولاً ثم بقية الحسابات — السؤال عن عميلٍ غالباً.

        **والحسابات التجميعية معها**: «إجمالي العملاء» لا يُرحَّل عليه
        شيء، لكنّ السؤال «كم صارت مديونية العملاء كلهم» سؤالٌ يُسأل —
        وجوابه مجموع شجرته. فتُدرج مُعلَّمةً بـ«(مجمّع)» ليعرف القارئ
        أنه يقرأ شجرةً لا حساباً.
        """
        try:
            with db(readonly=True) as conn:
                ents = entities.list_entities(conn)
                accs = list_postable(conn)
                groups = conn.execute(
                    "SELECT id, code, name FROM accounts"
                    " WHERE is_postable=0 ORDER BY code").fetchall()
        except Exception as e:
            err(self, e)
            return
        self.account.blockSignals(True)
        self.account.clear()
        seen = set()
        for e in ents:
            # `sqlite3.Row` لا تعرف `get` — تُقرأ بالمفتاح مباشرةً
            aid = e["account_id"] if "account_id" in e.keys() else None
            if aid:
                self.account.addItem(f"{e['name']}", aid)
                seen.add(aid)
        for a in accs:
            if a["id"] in seen:
                continue
            self.account.addItem(f"{a['code']} — {a['name']}", a["id"])
            seen.add(a["id"])
        for a in groups:
            if a["id"] in seen:
                continue
            self.account.addItem(
                f"{a['code']} — {a['name']} (مجمّع)", a["id"])
        self.account.blockSignals(False)
        try:
            self.account.clear_selection()
        except Exception:
            pass

    def load(self):
        aid = self.account.currentData()
        if not aid:
            err(self, "اختر الحساب أو الجهة أولاً")
            return
        d1, d2 = dstr(self.d_from), dstr(self.d_to)

        def _read():
            with db(readonly=True) as conn:
                return movement.analyze(conn, aid, d1, d2)

        ok, res, ex = run_bg(_read, parent=self, text="جارٍ تحليل الفترة…",
                             stage="تحليل الحركة", timeout=90.0)
        if ex:
            err(self, ex)
            return
        if not ok:
            self.verdict.setText("تأخّر التحليل — ضيّق الفترة وأعد المحاولة.")
            return
        self.res = res
        self._render()

    # ─────────────────────────────── عرض
    def _fmt(self, v, dim):
        return (f"{kv.g(v):,.3f}" if dim == "gold" else f"{v:,.2f}")

    def _unit(self, dim):
        return kv.unit() if dim == "gold" else "ريال"

    def _render(self):
        if not self.res:
            return
        r = self.res
        dim = self.dim.currentData() or "gold"
        u = self._unit(dim)
        op = r["opening"][dim]
        cl = r["closing"][dim]
        ch = r["change"][dim]

        self.c_open.set_value(self._fmt(op, dim), u)
        self.c_close.set_value(self._fmt(cl, dim), u)
        self.c_change.set_value(
            self._fmt(abs(ch), dim),
            "▲ الدين زاد" if ch > 0 else
            ("▼ الدين نقص" if ch < 0 else "لم يتغيّر"))
        d = r["days"]
        self.c_days.set_value(f"{d['active']} من {d['span']}",
                              f"{d['active_pct']}% · صامتة {d['silent']}")
        # المنسِّق والوحدة من الواجهة: الأرقام في النموذج مكافئُ عيار
        # 18، والمستخدم يقرأ بعيار مصنعه — فلولا تمريرهما لاختلف رقم
        # الجملة عن رقم الجدول للحركة نفسها
        self.verdict.setText(
            movement.verdict(r, dim, lambda v: self._fmt(v, dim), u)
            .replace("**", ""))

        # ── جسر الرصيد ──
        cols = ["البند", "الأثر", f"المبلغ ({u})", "خرج", "رجع/سُدّد",
                "مستندات", "أيام من الفترة"]
        rows = [("رصيد أول المدة", "", self._fmt(op, dim), "", "", "", "")]
        for b in r["buckets"]:
            v = b[dim]
            up = b["gold_up"] if dim == "gold" else b["cash_up"]
            dn = b["gold_dn"] if dim == "gold" else b["cash_dn"]
            if abs(v) < 0.0005 and abs(up) < 0.0005 and abs(dn) < 0.0005:
                continue
            rows.append((
                b["label"],
                "▲ يزيد الدين" if v > 0 else
                ("▼ ينقص الدين" if v < 0 else "—"),
                self._fmt(abs(v), dim),
                self._fmt(up, dim) if up else "",
                self._fmt(dn, dim) if dn else "",
                f"{b['docs']:,}", b["days_label"]))
        rows.append(("رصيد آخر المدة", "", self._fmt(cl, dim), "", "",
                     "", ""))
        fill(self.t_bridge, cols, rows)
        self._mark(self.t_bridge, [0, len(rows) - 1])
        self._opening_tip(self.t_bridge, 0, dim, u)

        # ── نشاط الأيام ──
        cols2 = ["نوع العملية", "أيام من الفترة", "النسبة",
                 "عدد المستندات", f"الإجمالي ({u})", "متوسط اليوم النشط"]
        rows2 = []
        for x in d["by_op"]:
            v = abs(x[dim])
            n = x["days"] or 1
            rows2.append((
                x["label"], x["days_label"], f"{x['days_pct']}%",
                f"{x['docs']:,}", self._fmt(v, dim),
                self._fmt(v / n, dim)))
        rows2.append(("— أيام فيها حركة —", d["active_label"],
                      f"{d['active_pct']}%", "", "", ""))
        rows2.append(("— أيام صامتة —", f"{d['silent']:,} من {d['span']:,}",
                      "", "", "", ""))
        fill(self.t_days, cols2, rows2)
        self._mark(self.t_days, [len(rows2) - 2, len(rows2) - 1])

        # ── يوماً بيوم ──
        cols3 = ["التاريخ", "ما جرى", "مستندات", f"صافي اليوم ({u})",
                 f"الرصيد بعده ({u})"]
        bal = "gbal" if dim == "gold" else "cbal"
        fill(self.t_daily, cols3,
             [(x["date"], " · ".join(x["ops"]), f"{x['docs']:,}",
               ("▲ " if x[dim] > 0 else ("▼ " if x[dim] < 0 else ""))
               + self._fmt(abs(x[dim]), dim),
               self._fmt(x[bal], dim)) for x in r["daily"]])

    def _opening_tip(self, table, row, dim, unit):
        """يُعلن ما ضُمّ إلى الافتتاحي من داخل الفترة.

        الرصيد الافتتاحي والقيد اليومي يُضمّان إلى «أول المدة» لأنهما
        رصيدُ بدايةٍ لا حركة. ولئلّا يُخفى ذلك، يقوله تلميحُ السطر
        بالرقم والعدد.
        """
        d = (self.res or {}).get("opening_in_period") or {}
        v = d.get(dim, 0.0)
        if not d.get("docs") or abs(v) < 0.0005:
            return
        tip = (f"يشمل {d['docs']:,} قيداً افتتاحياً/يومياً وقع داخل "
               f"الفترة بمقدار {self._fmt(v, dim)} {unit} — "
               "أُضيف إلى الرصيد لأنه رصيدُ بدايةٍ لا حركة.")
        for c in range(table.columnCount()):
            it = table.item(row, c)
            if it is not None:
                it.setToolTip(tip)

    def _mark(self, table, rows):
        """يُلبس صفوف الخلاصة نبرة الإبراز نفسها في كل النظام."""
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

    def copy_summary(self):
        """الخلاصة نصّاً — تُلصق في رسالةٍ للإدارة أو للعميل."""
        if not self.res:
            return
        r = self.res
        dim = self.dim.currentData() or "gold"
        u = self._unit(dim)
        out = [f"تحليل حركة الرصيد — {self.account.currentText()}",
               f"الفترة: {r['date_from']} إلى {r['date_to']}", "",
               movement.verdict(r, dim, lambda v: self._fmt(v, dim), u)
               .replace("**", ""), "",
               f"رصيد أول المدة : {self._fmt(r['opening'][dim], dim)} {u}"]
        for b in r["buckets"]:
            v = b[dim]
            if abs(v) < 0.0005:
                continue
            out.append(f"  {b['label']:<10} {('زيادة' if v > 0 else 'نقص')} "
                       f"{self._fmt(abs(v), dim)}   "
                       f"({b['docs']} مستند · {b['days_label']} يوماً)")
        out += [f"رصيد آخر المدة : {self._fmt(r['closing'][dim], dim)} {u}",
                ""]
        d = r["days"]
        out.append(f"نشاط الأيام: {d['active']} يوماً فيها حركة من "
                   f"{d['span']} ({d['active_pct']}%)")
        for x in d["by_op"]:
            out.append(f"  {x['label']:<10} في {x['days_label']} يوماً")
        QtWidgets.QApplication.clipboard().setText("\n".join(out))
        self.verdict.setText("نُسخت الخلاصة — الصقها في أي رسالة.")

    def refresh(self):
        if self.res:
            self.load()
