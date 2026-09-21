# -*- coding: utf-8 -*-
"""خريطة الذهب — أين الذهب الآن، ومن يحوزه.

**السؤال**: صاحب المصنع يعرف كم اشترى وكم باع، ولا يعرف في لحظةٍ
واحدة **أين ذهبه**: كم في خزينة التصنيع، وكم أطقمٌ في المعرض، وكم
كسرٌ ينتظر الصهر، وكم **ليس عنده أصلاً** — عند عميلٍ أو ورشةٍ أو
شريك. كانت تلك عشرَ شاشاتٍ تُفتح وتُجمع باليد.

┌ أربع لوحات: في اليد · عند الغير · خارج الخريطة · الإجمالي
├ **الخريطة**: الدلاء الثمانية بمجموعيها، والنسبة، والفرق عن تاريخٍ سابق
├ **التفصيل**: اضغط دلواً فترى حساباته حساباً حساباً
└ **لمن هو**: الطرف المقابل — وبه تقفل الخريطة على الصفر

قراءةٌ محضة: لا تكتب رقماً ولا تُنشئ قيداً.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from models import gold_map as gmap
from services import karat_view as kv
from ui.widgets.common import (Card, big_label, date_edit, dstr, err, fill,
                               ledger_rows, make_table, run_bg, tab_widget,
                               title_label)
from ui.widgets.table_fit import fit_columns
from ui.widgets.table_tools import enhance as _enhance

SIDE_TITLE = {"hand": "◂ في يد المصنع", "out": "◂ عند الغير"}


def wnum(v):
    """وزنٌ يُقرأ في واجهةٍ عربية — والسالب بين قوسين لا بسالبٍ أمامه.

    **العلة**: علامة الناقص في نصٍّ عربيٍّ تُرسم على الطرف الخطأ،
    فيظهر «1,313.667−» فيقرؤها المستخدم موجبةً وقد بقيت الإشارة خلفه.
    والقوسان اصطلاحُ المحاسبين في كل لغة، ولا يُحرّكهما اتجاه النص.
    """
    g = kv.g(v)
    return f"({abs(g):,.3f})" if g < 0 else f"{g:,.3f}"


class GoldMapScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.res = None
        self._row_bucket = {}

        self.as_of = date_edit()
        self.cmp_on = QtWidgets.QCheckBox("قارن بتاريخ")
        self.cmp_on.setChecked(True)
        self.cmp_date = date_edit()
        self.cmp_date.setDate(QtCore.QDate.currentDate().addMonths(-1))
        self.cmp_on.toggled.connect(self.cmp_date.setEnabled)

        btn = QtWidgets.QPushButton("🗺 ارسم الخريطة")
        btn.clicked.connect(self.load)
        btn_print = QtWidgets.QPushButton("👁 معاينة وطباعة")
        btn_print.clicked.connect(self.print_report)
        btn_copy = QtWidgets.QPushButton("📋 نسخ الخلاصة")
        btn_copy.setObjectName("ghost")
        btn_copy.clicked.connect(self.copy_summary)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(QtWidgets.QLabel("بتاريخ:"))
        head.addWidget(self.as_of, 0)
        head.addWidget(self.cmp_on, 0)
        head.addWidget(self.cmp_date, 0)
        head.addWidget(btn, 0)
        head.addWidget(btn_print, 0)
        head.addWidget(btn_copy, 0)
        head.addStretch(1)

        self.c_hand = Card("في يد المصنع", "خزينة · مشغول · كسر · تصفية",
                           summary=True)
        self.c_out = Card("عند الغير", "عملاء · جهات · شركاء · ورشة",
                          summary=True)
        self.c_lost = Card("خارج الخريطة", "حسابات ذهبٍ لا دلوَ لها")
        self.c_total = Card("إجمالي الذهب", "مجموع الخريطة")
        tiles = QtWidgets.QHBoxLayout()
        for c in (self.c_hand, self.c_out, self.c_lost, self.c_total):
            tiles.addWidget(c)

        self.verdict = big_label("اختر التاريخ ثم «ارسم الخريطة».")
        # الخلاصة عدة جملٍ قد تطول — تُلفّ ولا تُقصّ
        self.verdict.setWordWrap(True)

        self.t_map = make_table()
        _enhance(self.t_map, key="gold_map")
        self.t_map.itemSelectionChanged.connect(self._show_detail)
        self.t_detail = make_table()
        _enhance(self.t_detail, key="gold_map_detail")
        self.t_src = make_table()
        _enhance(self.t_src, key="gold_map_src")

        self.tabs = tab_widget()
        self.tabs.addTab(self.t_map, "الخريطة")
        self.tabs.addTab(self.t_detail, "التفصيل")
        self.tabs.addTab(self.t_src, "لمن هو")

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        lay.addWidget(title_label("خريطة الذهب — أين الذهب الآن"))
        intro = QtWidgets.QLabel(
            "ذهب المصنع ليس في مكانٍ واحد: بعضه في الخزينة، وبعضه أطقمٌ "
            "تامّة، وبعضه كسرٌ أو تحت التصفية — وبعضه ليس عنده أصلاً. "
            "هذه الخريطة تجمعه في صفحةٍ واحدة، وتقول كم منه خرج من يده.")
        intro.setObjectName("cardSub")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        lay.addLayout(head)
        lay.addLayout(tiles)
        lay.addWidget(self.verdict)
        lay.addWidget(self.tabs, 1)
        self.note = QtWidgets.QLabel(
            "الخريطة تقفل بحكم القيد المزدوج: مجموعها يساوي تماماً ما "
            "على الجانب المقابل. فلو أُضيف حساب ذهبٍ جديد لا تعرفه "
            "الدلاء الثمانية لم يضع رصيده — يظهر في «خارج الخريطة» "
            "باسمه. اضغط أيَّ دلوٍ لترى حساباته في تبويب «التفصيل».")
        self.note.setObjectName("cardSub")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)

    # ─────────────────────────────── بيانات
    def load(self):
        d = dstr(self.as_of)
        c = dstr(self.cmp_date) if self.cmp_on.isChecked() else None
        if c and c >= d:
            err(self, "تاريخ المقارنة يجب أن يكون أقدم من تاريخ الخريطة")
            return

        def _read():
            with db(readonly=True) as conn:
                return gmap.gold_map(conn, d, c)

        ok, res, ex = run_bg(_read, parent=self, text="جارٍ رسم الخريطة…",
                             stage="خريطة الذهب", timeout=90.0)
        if ex:
            err(self, ex)
            return
        if not ok:
            self.verdict.setText("تأخّر الحساب — أعد المحاولة.")
            return
        self.res = res
        self._render()

    # ─────────────────────────────── عرض
    def _render(self):
        m = self.res
        u = kv.unit()
        cmp_on = bool(m.get("compare_to"))

        self.c_hand.set_value(wnum(m['hand']),
                              f"{u} · {m['hand_share'] or 0:,.1f}%")
        self.c_out.set_value(wnum(m['outside_hands']),
                             f"{u} · {m['out_share'] or 0:,.1f}%")
        n_out = len(m["outside"])
        self.c_lost.set_value(
            wnum(m['unmapped']),
            ("لا شيء — الخريطة كاملة" if not n_out else
             "حسابٌ واحد خارج الدلاء" if n_out == 1 else
             f"{n_out} حسابات خارج الدلاء"))
        self.c_total.set_value(
            wnum(m['total']),
            ("مقفلة ✔" if m["balanced"]
             else f"⚠ فرق {kv.g(abs(m['diff'])):,.3f}"))
        self.verdict.setText("   ·   ".join(gmap.verdict(m, wnum)))

        # ── الخريطة ──
        cols = ["المكان", "ما فيه", f"الوزن ({u})", "النسبة"]
        if cmp_on:
            cols += [f"سابقاً ({u})", "الاتجاه", f"التغيّر ({u})"]
        rows, marks = [], []
        self._row_bucket = {}

        def _grp(side, total, prev):
            marks.append(len(rows))
            r = [SIDE_TITLE[side], "", wnum(total), ""]
            if cmp_on:
                ch = round(total - (prev or 0.0), 3)
                r += [wnum(prev or 0.0),
                      "▲" if ch > 0 else ("▼" if ch < 0 else "—"),
                      wnum(abs(ch))]
            rows.append(tuple(r))

        def _row(b):
            self._row_bucket[len(rows)] = b
            r = [b["label"], b["hint"], wnum(b['gold']),
                 f"{b['share']:,.1f}%" if b["share"] is not None else "—"]
            if cmp_on:
                ch = b["change"] or 0.0
                r += [wnum(b['prev'] or 0.0),
                      "▲" if ch > 0 else ("▼" if ch < 0 else "—"),
                      wnum(abs(ch)) if ch else "—"]
            rows.append(tuple(r))

        _grp("hand", m["hand"], m.get("prev_hand"))
        for b in m["buckets"]:
            if b["side"] == "hand":
                _row(b)
        _grp("out", m["outside_hands"], m.get("prev_outside_hands"))
        for b in m["buckets"]:
            if b["side"] == "out":
                _row(b)
        base = m["gross"] or 0.0
        for r in m["outside"]:
            rows.append(tuple(
                [r["name"], f"خارج الدلاء — {r['code']}",
                 wnum(r['gold']),
                 f"{max(r['gold'], 0.0) / base * 100.0:,.1f}%"
                 if base > 0.011 else "—"]
                + (["—", "—", "—"] if cmp_on else [])))
        marks.append(len(rows))
        tot = ["إجمالي الذهب", "", wnum(m['total']), "100%"]
        if cmp_on:
            ch = m.get("change_total") or 0.0
            tot += [wnum(m.get('prev_total') or 0.0),
                    "▲" if ch > 0 else ("▼" if ch < 0 else "—"),
                    wnum(abs(ch))]
        rows.append(tuple(tot))
        fill(self.t_map, cols, rows)
        # الاتجاه سهمٌ واحد لا يحتاج عرض عمودٍ كامل؛ والمكان ووصفه
        # نصٌّ يُقرأ فيأخذان نصيب الأسد
        fit_columns(self.t_map, [17, 22, 15, 9, 15, 6, 16] if cmp_on
                    else [26, 34, 24, 16])
        ledger_rows(self.t_map, wrap_cols=(0, 1))
        self._mark(self.t_map, marks)

        # ── لمن هو ──
        # **الطرف عمودٌ مستقل لا إشارةٌ على الرقم**: «له (دائن) ٥٠»
        # يقرؤها المصنعيّ في لمحة، و«‎−٥٠» تحتاج تفسيراً — ثم ترسمها
        # الواجهة العربية على الطرف الخطأ فتُقرأ موجبةً.
        def _side(v):
            return "له (دائن)" if v > 0.0005 else (
                "عليه (مدين)" if v < -0.0005 else "—")

        fill(self.t_src,
             ["الحساب", "الكود", "التصنيف", "الطرف", f"الوزن ({u})"],
             [(r["name"], r["code"], r.get("group", "—"),
               _side(-r["gold"]), f"{abs(kv.g(r['gold'])):,.3f}")
              for r in m["other"]]
             + [("الصافي — يقابل مجموع الخريطة", "", "",
                 _side(-m["other_total"]),
                 f"{abs(kv.g(m['other_total'])):,.3f}")])
        fit_columns(self.t_src, [34, 10, 26, 14, 16])
        ledger_rows(self.t_src, wrap_cols=(0, 2))
        self._mark(self.t_src, [len(m["other"])])

        self._show_detail()

    def _show_detail(self):
        """الدلو المختار مفصّلاً — وبلا اختيارٍ تُعرض كل الحسابات."""
        if not self.res:
            return
        u = kv.unit()
        rows = self.t_map.selectionModel().selectedRows() \
            if self.t_map.selectionModel() else []
        idx = rows[0].row() if rows else -1
        b = self._row_bucket.get(idx)
        cols = ["المكان", "الحساب", "الكود", f"الوزن ({u})"]
        if b is not None:
            data = [(b["label"], lf["name"], lf["code"],
                     wnum(lf['gold'])) for lf in b["leaves"]]
            title = f"«{b['label']}» — {len(b['leaves'])} حساباً"
        else:
            data = [(x["label"], lf["name"], lf["code"],
                     wnum(lf['gold']))
                    for x in self.res["buckets"] for lf in x["leaves"]]
            # وما خرج عن الدلاء يُعرض معها لا دونها: التفصيل يجب أن
            # يجمع كل ما في «الخريطة» وإلا لم يساوِ مجموعُه إجماليَها
            data += [("خارج الدلاء", r["name"], r["code"], wnum(r["gold"]))
                     for r in self.res["outside"]]
            title = "كل الدلاء — اضغط دلواً في «الخريطة» لتصفيته"
        fill(self.t_detail, cols, data)
        fit_columns(self.t_detail, [22, 40, 14, 18])
        ledger_rows(self.t_detail, wrap_cols=(1,))
        self.tabs.setTabText(1, f"التفصيل ({len(data)})")
        self.t_detail.setToolTip(title)

    def _mark(self, table, rows):
        """صفوف الخلاصة تلبس نبرة الإبراز نفسها في كل النظام."""
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
            err(self, "ارسم الخريطة أولاً")
            return
        from services import print_manager
        try:
            print_manager.preview_document(
                self, "gold_map", 0, as_of=self.res["as_of"],
                compare_to=self.res.get("compare_to"), detail=True)
        except Exception as e:
            err(self, e)

    def copy_summary(self):
        if not self.res:
            return
        m = self.res
        u = kv.unit()
        out = [f"خريطة الذهب — بتاريخ {m['as_of']}"]
        if m.get("compare_to"):
            out.append(f"مقارنةً بـ {m['compare_to']}")
        out += ["", *gmap.verdict(m, wnum), ""]
        for b in m["buckets"]:
            line = f"  {b['label']:<22} {kv.g(b['gold']):>12,.3f} {u}"
            if b["change"] is not None and abs(b["change"]) > 0.0005:
                line += (f"   ({'زيادة' if b['change'] > 0 else 'نقص'} "
                         f"{kv.g(abs(b['change'])):,.3f})")
            out.append(line)
        if m["outside"]:
            out.append("  — خارج الخريطة —")
            for r in m["outside"]:
                out.append(f"  {r['name']:<22} {kv.g(r['gold']):>12,.3f}")
        out += ["", f"  في يد المصنع : {kv.g(m['hand']):,.3f} {u}",
                f"  عند الغير    : {kv.g(m['outside_hands']):,.3f} {u}",
                f"  الإجمالي     : {kv.g(m['total']):,.3f} {u}"]
        QtWidgets.QApplication.clipboard().setText("\n".join(out))
        self.verdict.setText("نُسخت الخلاصة — الصقها في أي رسالة.")

    def refresh(self):
        if self.res:
            self.load()
