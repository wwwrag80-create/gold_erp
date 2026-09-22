# -*- coding: utf-8 -*-
"""من عدّل ماذا بعد الترحيل — ومتى، وكم تغيّرت قيمته.

**السؤال**: التعديل مشروعٌ في هذا النظام — فالخطأ يقع، والصواب أن
يُصحَّح لا أن يُترك. لكن سجل التتبع يقول «عُدِّلت الفاتورة S-00042»
ولا يقول **كم تغيّرت**. والرقابة تبدأ من أن يكون التعديل مرئياً:
تعديلٌ يُرى يُسأل عنه، وتعديلٌ لا يُرى لا يُسأل.

┌ أربع لوحات: عدد التعديلات · ما غيّر قيمة · المتأخّر · أقصى تأخّر
├ **التعديلات**: مستنداً مستنداً، بقيمته قبل وبعد والفرق والتأخّر
├ **بالمستخدم**: من عدّل كم، وكم منها متأخّر
└ **بنوع المستند**: أيّ المستندات يُعدَّل أكثر

قراءةٌ محضة: لا تكتب رقماً ولا تُنشئ قيداً.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from models import doc_edits as de
from services import karat_view as kv
from ui.widgets.common import (Card, big_label, date_edit, dstr, err, fill,
                               ledger_rows, make_table, run_bg, tab_widget,
                               title_label)
from ui.widgets.table_fit import fit_columns
from ui.widgets.table_tools import enhance as _enhance


def snum(v, d=2):
    """السالب بين قوسين — لا بإشارةٍ تزيغ في نصٍّ عربي."""
    return f"({abs(v):,.{d}f})" if v < 0 else f"{v:,.{d}f}"


class DocEditsScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.res = None

        self.d_from = date_edit()
        self.d_from.setDate(QtCore.QDate.currentDate().addMonths(-1))
        self.d_to = date_edit()
        self.kind = QtWidgets.QComboBox()
        self.kind.setMaximumWidth(190)
        self.kind.addItem("كل المستندات", "")
        for k, lbl in sorted(de.LABELS.items(), key=lambda x: x[1]):
            self.kind.addItem(lbl, k)
        self.late_only = QtWidgets.QCheckBox(
            f"المتأخّر فقط (بعد {de.LATE_DAYS} يوماً)")

        btn = QtWidgets.QPushButton("🔎 اعرض التعديلات")
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
        head.addWidget(QtWidgets.QLabel("النوع:"))
        head.addWidget(self.kind, 0)
        head.addWidget(self.late_only, 0)
        head.addWidget(btn, 0)
        head.addWidget(btn_print, 0)
        head.addWidget(btn_copy, 0)
        head.addStretch(1)

        self.c_count = Card("تعديلات", "على مستنداتٍ مُرحَّلة", summary=True)
        self.c_changed = Card("غيّرت القيمة", "لا مجرّد بيان", summary=True)
        self.c_late = Card("تعديلٌ متأخّر", f"بعد {de.LATE_DAYS} يوماً فأكثر")
        self.c_max = Card("أقصى تأخّر", "بين الترحيل والتعديل")
        tiles = QtWidgets.QHBoxLayout()
        for c in (self.c_count, self.c_changed, self.c_late, self.c_max):
            tiles.addWidget(c)

        self.verdict = big_label("اختر الفترة ثم «اعرض التعديلات».")
        self.verdict.setWordWrap(True)

        self.t_rows = make_table()
        _enhance(self.t_rows, key="doc_edits_rows")
        self.t_users = make_table()
        _enhance(self.t_users, key="doc_edits_users")
        self.t_types = make_table()
        _enhance(self.t_types, key="doc_edits_types")

        self.tabs = tab_widget()
        self.tabs.addTab(self.t_rows, "التعديلات")
        self.tabs.addTab(self.t_users, "بالمستخدم")
        self.tabs.addTab(self.t_types, "بنوع المستند")

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        lay.addWidget(title_label("من عدّل ماذا بعد الترحيل"))
        intro = QtWidgets.QLabel(
            "التعديل مشروعٌ في هذا النظام؛ المقصود أن يكون مرئياً. "
            "وقيمة المستند هنا مجموعُ الطرف المدين من قيده — مقياسٌ "
            "واحد يصلح للفاتورة والسند والصهر والقيد اليدوي، لأن القيد "
            "متوازنٌ بالضرورة فمجموع مدينه هو حجمه.")
        intro.setObjectName("cardSub")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        lay.addLayout(head)
        lay.addLayout(tiles)
        lay.addWidget(self.verdict)
        lay.addWidget(self.tabs, 1)
        note = QtWidgets.QLabel(
            "التأخّر يُقاس من لحظة الترحيل لا من تاريخ المستند: تعديلٌ "
            "بعد دقيقتين تصحيحُ إدخال، وتعديلٌ بعد أربعين يوماً — بعد "
            "أن أُغلق الشهر وصُدِّرت أرقامه — شيءٌ آخر يُسأل عنه. "
            "والفرق رقمٌ محفوظٌ وقت التعديل لا نصٌّ يُحلَّل لاحقاً.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)

    # ─────────────────────────────── بيانات
    def load(self):
        d1, d2 = dstr(self.d_from), dstr(self.d_to)
        tbl = self.kind.currentData() or None
        lag = de.LATE_DAYS if self.late_only.isChecked() else 0

        def _read():
            with db(readonly=True) as conn:
                rows = de.report(conn, d1, d2, source_table=tbl,
                                 min_lag=lag)
                return rows, de.summarize(conn, rows)

        ok, out, ex = run_bg(_read, parent=self,
                             text="جارٍ قراءة سجلّ التعديلات…",
                             stage="تعديلات المستندات", timeout=90.0)
        if ex:
            err(self, ex)
            return
        if not ok:
            self.verdict.setText("تأخّرت القراءة — ضيّق الفترة.")
            return
        self.res = {"rows": out[0], "sum": out[1],
                    "date_from": d1, "date_to": d2}
        self._render()

    # ─────────────────────────────── عرض
    def _render(self):
        rows, s = self.res["rows"], self.res["sum"]
        t = s["total"]
        u = kv.unit()

        def w(v):
            return snum(kv.g(v), 3)

        def m(v):
            return snum(v, 2)

        self.c_count.set_value(f"{t['count']:,}",
                               f"في {len(s['users']):,} مستخدماً")
        self.c_changed.set_value(
            f"{t['changed']:,}",
            f"وزناً {w(t['d_gold'])} · نقداً {m(t['d_cash'])}")
        self.c_late.set_value(f"{t['late']:,}",
                              f"من {t['count']:,} تعديلاً")
        self.c_max.set_value(f"{t['max_lag']:,}", "يوماً")
        self.verdict.setText("   ·   ".join(de.verdict(s, w, m)))

        # ── التعديلات ──
        fill(self.t_rows,
             ["وقت التعديل", "المستخدم", "النوع", "المستند",
              "تاريخ المستند", "التأخّر (يوم)", "الطريقة",
              f"قبل ({u})", f"بعد ({u})", f"الفرق ({u})",
              "قبل (ريال)", "بعد (ريال)", "الفرق (ريال)"],
             [(r["edited_at"], r["user"], r["label"], r["doc_no"],
               r["doc_date"],
               f"{r['lag']:,}" if r["lag"] is not None else "—",
               r["kind_label"], w(r["old_gold"]), w(r["new_gold"]),
               w(r["d_gold"]), m(r["old_cash"]), m(r["new_cash"]),
               m(r["d_cash"])) for r in rows])
        fit_columns(self.t_rows,
                    [12, 9, 13, 10, 10, 8, 11, 9, 9, 9, 10, 10, 10])
        ledger_rows(self.t_rows, wrap_cols=(2,))
        self.tabs.setTabText(0, f"التعديلات ({len(rows)})")
        self._paint_late(rows)

        # ── بالمستخدم ──
        data = [(x["name"], f"{x['count']:,}", f"{x['late']:,}",
                 w(x["d_gold"]), m(x["d_cash"])) for x in s["users"]]
        if data:
            data.append(("الإجمالي", f"{t['count']:,}", f"{t['late']:,}",
                         w(t["d_gold"]), m(t["d_cash"])))
        fill(self.t_users,
             ["المستخدم", "تعديلات", "منها متأخّر", f"صافي الوزن ({u})",
              "صافي النقد (ريال)"], data)
        fit_columns(self.t_users, [26, 14, 16, 22, 22])
        ledger_rows(self.t_users, wrap_cols=(0,))
        if data:
            self._mark(self.t_users, [len(data) - 1])

        # ── بنوع المستند ──
        data2 = [(x["label"], f"{x['count']:,}", w(x["d_gold"]),
                  m(x["d_cash"])) for x in s["types"]]
        if data2:
            data2.append(("الإجمالي", f"{t['count']:,}", w(t["d_gold"]),
                          m(t["d_cash"])))
        fill(self.t_types,
             ["نوع المستند", "تعديلات", f"صافي الوزن ({u})",
              "صافي النقد (ريال)"], data2)
        fit_columns(self.t_types, [34, 16, 25, 25])
        ledger_rows(self.t_types, wrap_cols=(0,))
        if data2:
            self._mark(self.t_types, [len(data2) - 1])

    def _paint_late(self, rows):
        """المتأخّر يُلوَّن: العين تلتقطه قبل أن تقرأ عمود التأخّر."""
        from ui import theme
        pal = theme.palette(theme.current_theme())
        bg = QtGui.QColor(pal.get("sumBg", "#FDF3E2"))
        ink = QtGui.QColor(pal.get("sumInk", "#7A4F10"))
        for i, r in enumerate(rows):
            if r["lag"] is None or r["lag"] < de.LATE_DAYS:
                continue
            for c in range(self.t_rows.columnCount()):
                it = self.t_rows.item(i, c)
                if it is None:
                    continue
                it.setBackground(bg)
                it.setForeground(ink)

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
            err(self, "اعرض التعديلات أولاً")
            return
        from services import print_manager
        try:
            print_manager.preview_document(
                self, "doc_edits", 0, date_from=self.res["date_from"],
                date_to=self.res["date_to"],
                source_table=self.kind.currentData() or None,
                min_lag=de.LATE_DAYS if self.late_only.isChecked() else 0)
        except Exception as e:
            err(self, e)

    def copy_summary(self):
        if not self.res:
            return
        s = self.res["sum"]

        def w(v):
            return snum(kv.g(v), 3)

        def m(v):
            return snum(v, 2)

        out = [f"من عدّل ماذا — من {self.res['date_from']} إلى "
               f"{self.res['date_to']}", "", *de.verdict(s, w, m), ""]
        for x in s["users"]:
            out.append(f"  {x['name']:<18} {x['count']:>5,} تعديلاً   "
                       f"متأخّر {x['late']:>4,}   وزن {w(x['d_gold']):>12}"
                       f"   نقد {m(x['d_cash']):>14}")
        QtWidgets.QApplication.clipboard().setText("\n".join(out))
        self.verdict.setText("نُسخت الخلاصة — الصقها في أي رسالة.")

    def refresh(self):
        if self.res:
            self.load()
