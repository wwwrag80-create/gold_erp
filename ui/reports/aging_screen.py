# -*- coding: utf-8 -*-
"""أعمار الديون — توزيع أرصدة الجهات على فئات عمرية (30/60/90 يوماً).

الرصيد رقمٌ واحد لا يقول شيئاً عن خطورته: مئة ألف عمرها أسبوع غير
مئة ألف عمرها سنة. هذه الشاشة تُظهر أيّ الديون تأخّرت وكم، وتُبرز
أقدمها أولاً.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from models import aging, entities
from services import karat_view as kv
from ui.widgets.common import (Card, big_label, date_edit, dstr, err,
                               make_table, title_label)
from ui.widgets.table_fit import fit_columns

TYPES = [("العملاء", "customer"), ("الموردون", "supplier"),
         ("جهات أخرى", "other")]


class AgingScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.rows = []

        self.kind = QtWidgets.QComboBox()
        self.kind.setMaximumWidth(140)
        for label, val in TYPES:
            self.kind.addItem(label, val)
        self.kind.currentIndexChanged.connect(self.refresh)
        self.as_of = date_edit()
        self.dim = QtWidgets.QComboBox()
        self.dim.setMaximumWidth(150)
        # النقد أولاً: أربعة عشر عموداً في شاشة واحدة لا تُقرأ، وسؤال
        # «كم تأخّر علينا؟» نقديٌّ في الغالب. والبعدان متاحان لمن أراد.
        self.dim.addItem("النقد فقط", "cash")
        self.dim.addItem("الذهب فقط", "gold")
        self.dim.addItem("نقد وذهب معاً", "both")
        self.dim.currentIndexChanged.connect(self.render)

        # ── ترشيح بالأسماء ──
        # التقرير كاملاً مفيد للنظرة العامة، لكن المتابعة اليومية تكون
        # مع جهةٍ بعينها أو مجموعة. النافذة أنسب من قائمة منسدلة لأن
        # الجهات قد تبلغ المئات، وفيها بحثٌ بالاسم.
        self.selected = []                  # فارغة = كل الجهات
        self.btn_names = QtWidgets.QPushButton("الجهات: كل الجهات ▾")
        self.btn_names.setMinimumWidth(220)
        self.btn_names.setToolTip(
            "اختر جهةً أو أكثر ليقتصر الجدول عليها — والفراغ يعني الكل")
        self.btn_names.clicked.connect(self.pick_names)
        btn_clear = QtWidgets.QPushButton("مسح التحديد")
        btn_clear.setObjectName("ghost")
        btn_clear.setToolTip("يعيد عرض كل الجهات")
        btn_clear.clicked.connect(self.clear_names)
        btn = QtWidgets.QPushButton("عرض")
        btn.clicked.connect(self.refresh)
        btn_print = QtWidgets.QPushButton("👁 معاينة وطباعة")
        btn_print.clicked.connect(self.print_report)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(QtWidgets.QLabel("الفئة:"))
        head.addWidget(self.kind, 0)
        head.addWidget(QtWidgets.QLabel("حتى تاريخ:"))
        head.addWidget(self.as_of, 0)
        head.addWidget(QtWidgets.QLabel("البعد:"))
        head.addWidget(self.dim, 0)
        head.addWidget(self.btn_names, 0)
        head.addWidget(btn_clear, 0)
        head.addWidget(btn, 0)
        head.addStretch(1)
        head.addWidget(btn_print, 0)

        self.c_count = Card("عدد الجهات المدينة", "لها رصيد قائم")
        self.c_cur = Card("جارٍ (0 – 30)", "ريال")
        self.c_late = Card("متأخر (31 – 90)", "ريال")
        self.c_bad = Card("متعثّر (أكثر من 90)", "ريال")
        cards = QtWidgets.QHBoxLayout()
        cards.setSpacing(4)
        for c in (self.c_count, self.c_cur, self.c_late, self.c_bad):
            cards.addWidget(c)

        self.table = make_table()
        self.note = big_label()
        self.lbl_sel = QtWidgets.QLabel("المعروض: كل الجهات")
        self.lbl_sel.setObjectName("cardSub")

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        lay.addWidget(title_label(
            "أعمار الديون — توزيع الأرصدة على فئات عمرية بطريقة "
            "«الأقدم فالأقدم»"))
        lay.addLayout(head)
        lay.addWidget(self.lbl_sel)
        lay.addWidget(self.table, 1)
        lay.addLayout(cards)
        lay.addWidget(self.note)
        hint = QtWidgets.QLabel(
            "كل مدين يفتح دفعة بتاريخها، وكل دائن يُسدّد أقدم الدفعات "
            "المفتوحة أولاً — وهو المتّبع محاسبياً ما لم يخصّص العميل "
            "دفعته. الرصيد الدائن (له علينا) لا عمر له فيُعرض مستقلاً.")
        hint.setObjectName("cardSub")
        hint.setWordWrap(True)
        lay.addWidget(hint)

    # ══════════════════════════════════════════════════════════════

    # ── اختيار الجهات ──

    def pick_names(self):
        """نافذة اختيار الجهات: بحث بالاسم وتأشير متعدّد."""
        try:
            kind = self.kind.currentData()
            with db(readonly=True) as conn:
                rows = [e for e in entities.list_entities(conn)
                        if e["entity_type"] == kind and not e["is_internal"]]
            # الجهات ذات الرصيد أولاً — وهي المقصودة في تقرير الأعمار
            with_bal = {r["entity_id"] for r in self.rows}
            rows.sort(key=lambda e: (e["id"] not in with_bal, e["name"]))

            dlg = QtWidgets.QDialog(self)
            dlg.setWindowTitle("اختيار الجهات")
            dlg.setMinimumSize(420, 480)
            search = QtWidgets.QLineEdit()
            search.setPlaceholderText("اكتب أول حروف الاسم للتصفية…")
            lst = QtWidgets.QListWidget()
            chosen = set(self.selected)
            for e in rows:
                it = QtWidgets.QListWidgetItem(
                    e["name"] + ("" if e["id"] in with_bal
                                 else "   (بلا رصيد)"))
                it.setData(QtCore.Qt.UserRole, e["id"])
                it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
                it.setCheckState(QtCore.Qt.Checked if e["id"] in chosen
                                 else QtCore.Qt.Unchecked)
                lst.addItem(it)

            def _filter(txt):
                n = (txt or "").strip()
                for i in range(lst.count()):
                    it = lst.item(i)
                    it.setHidden(bool(n) and n not in it.text())
            search.textChanged.connect(_filter)

            def _set_all(state):
                for i in range(lst.count()):
                    if not lst.item(i).isHidden():
                        lst.item(i).setCheckState(state)

            btn_all = QtWidgets.QPushButton("تحديد الظاهر")
            btn_all.setObjectName("ghost")
            btn_all.clicked.connect(lambda: _set_all(QtCore.Qt.Checked))
            btn_none = QtWidgets.QPushButton("إلغاء التحديد")
            btn_none.setObjectName("ghost")
            btn_none.clicked.connect(lambda: _set_all(QtCore.Qt.Unchecked))
            box = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.Ok
                | QtWidgets.QDialogButtonBox.Cancel)
            box.accepted.connect(dlg.accept)
            box.rejected.connect(dlg.reject)

            row = QtWidgets.QHBoxLayout()
            row.addWidget(btn_all)
            row.addWidget(btn_none)
            row.addStretch(1)
            lay = QtWidgets.QVBoxLayout(dlg)
            lay.addWidget(search)
            lay.addWidget(lst, 1)
            lay.addLayout(row)
            lay.addWidget(box)
            if dlg.exec_() != QtWidgets.QDialog.Accepted:
                return
            self.selected = [lst.item(i).data(QtCore.Qt.UserRole)
                             for i in range(lst.count())
                             if lst.item(i).checkState() == QtCore.Qt.Checked]
            self._update_names_label()
            self.render()
        except Exception as e:
            err(self, e)

    def _selected_label(self):
        if not self.selected:
            return "كل الجهات"
        if len(self.selected) == 1:
            one = [r for r in self.rows
                   if r["entity_id"] == self.selected[0]]
            return one[0]["name"] if one else "جهة واحدة"
        return f"{len(self.selected)} جهات"

    def _update_names_label(self):
        txt = self._selected_label()
        self.btn_names.setText(f"الجهات: {txt} ▾")
        self.lbl_sel.setText(f"المعروض: {txt}")

    def clear_names(self):
        self.selected = []
        self._update_names_label()
        self.render()

    def refresh(self):
        try:
            with db(readonly=True) as conn:
                self.rows = aging.report(conn, self.kind.currentData(),
                                         dstr(self.as_of))
            self._update_names_label()
            self.render()
        except Exception as e:
            err(self, e)

    def _visible_rows(self):
        """الصفوف بعد الترشيح بالأسماء — الفراغ يعني الكل."""
        chosen = set(self.selected)
        if not chosen:
            return self.rows
        return [r for r in self.rows if r["entity_id"] in chosen]

    # عناوين مختصرة على الشاشة: الفئة رقمان لا جملة، فالعمود يضيق
    # والعنوان يُقرأ كاملاً بدل أن يُقصّ.
    SHORT = ("0 – 30", "31 – 60", "61 – 90", "+90")

    def _headers(self, dim):
        cols = ["الجهة", "الجوال", "أقدم\nدين"]
        both = dim == "both"
        if dim in ("both", "cash"):
            cols += [(f"نقد\n{b}" if both else b) for b in self.SHORT]
            cols += ["إجمالي\nالنقد"]
        if dim in ("both", "gold"):
            cols += [(f"ذهب\n{b}" if both else b) for b in self.SHORT]
            cols += [f"إجمالي\nالذهب"]
        cols += ["له علينا"]
        return cols

    def _row_cells(self, r, dim):
        out = [r["name"], r["phone"] or "—",
               str(r["days"]) if r["days"] else "—"]
        if dim in ("both", "cash"):
            out += [f"{x:,.2f}" if x else "" for x in r["cash_buckets"]]
            out += [f"{r['cash']:,.2f}" if r["cash"] else ""]
        if dim in ("both", "gold"):
            out += [f"{kv.g(x):,.3f}" if x else ""
                    for x in r["gold_buckets"]]
            out += [f"{kv.g(r['gold']):,.3f}" if r["gold"] else ""]
        cr = []
        if r["cash_credit"]:
            cr.append(f"نقد {abs(r['cash_credit']):,.2f}")
        if r["gold_credit"]:
            cr.append(f"ذهب {kv.g(abs(r['gold_credit'])):,.3f}")
        out.append(" · ".join(cr) or "—")
        return out

    def render(self):
        dim = self.dim.currentData() or "both"
        headers = self._headers(dim)
        rows = self._visible_rows()
        t = aging.totals(rows)

        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        try:
            self.table.setColumnCount(len(headers))
            self.table.setHorizontalHeaderLabels(headers)
            self.table.setRowCount(len(rows) + (1 if rows else 0))
            for i, r in enumerate(rows):
                for c, v in enumerate(self._row_cells(r, dim)):
                    it = QtWidgets.QTableWidgetItem(str(v))
                    it.setTextAlignment(QtCore.Qt.AlignCenter)
                    # المتعثّر يُلوَّن: العين تلتقطه قبل أن تقرأ الأرقام
                    if r["days"] >= 91:
                        it.setForeground(QtGui.QColor("#B02A2A"))
                    elif r["days"] >= 61:
                        it.setForeground(QtGui.QColor("#8A6D1D"))
                    self.table.setItem(i, c, it)
            if rows:
                tot = ["الإجمالي", "—", "—"]
                if dim in ("both", "cash"):
                    tot += [f"{x:,.2f}" for x in t["cash_buckets"]]
                    tot += [f"{t['cash']:,.2f}"]
                if dim in ("both", "gold"):
                    tot += [f"{kv.g(x):,.3f}" for x in t["gold_buckets"]]
                    tot += [f"{kv.g(t['gold']):,.3f}"]
                tot.append(f"نقد {abs(t['cash_credit']):,.2f}"
                           if t["cash_credit"] else "—")
                last = len(rows)
                for c, v in enumerate(tot):
                    it = QtWidgets.QTableWidgetItem(str(v))
                    it.setTextAlignment(QtCore.Qt.AlignCenter)
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                    try:
                        it.setBackground(QtGui.QColor("#EFE9DC"))
                    except Exception:
                        pass
                    self.table.setItem(last, c, it)
        finally:
            self.table.setUpdatesEnabled(True)
        # الاسم يأخذ الحصة الأكبر، والأرقام تتساوى
        w = [20, 9, 7] + [8] * (len(headers) - 4) + [10]
        fit_columns(self.table, w)

        self.c_count.set_value(f"{t['count']:,}")
        self.c_cur.set_value(f"{t['cash_buckets'][0]:,.2f}",
                             f"{t['cash_pct'][0]:.1f}% من الإجمالي")
        late = t["cash_buckets"][1] + t["cash_buckets"][2]
        self.c_late.set_value(
            f"{late:,.2f}",
            f"{(t['cash_pct'][1] + t['cash_pct'][2]):.1f}% من الإجمالي")
        self.c_bad.set_value(f"{t['cash_buckets'][3]:,.2f}",
                             f"{t['cash_pct'][3]:.1f}% من الإجمالي")
        worst = rows[0] if rows else None
        self.note.setText(
            (f"أقدم دين: {worst['name']} منذ {worst['days']} يوماً "
             f"({worst['oldest']})" if worst else
             "لا توجد أرصدة قائمة في هذه الفئة."))

    def print_report(self):
        from services import print_manager
        try:
            print_manager.preview_document(
                self, "aging", 0, entity_type=self.kind.currentData(),
                as_of=dstr(self.as_of), dim=self.dim.currentData(),
                only=list(self.selected))
        except Exception as e:
            err(self, e)
