# -*- coding: utf-8 -*-
"""مطابقة كشف البنك — بين ما في الدفتر وما في كشف المصرف.

**لماذا لزمت**: في النظام حسابُ بنكٍ تُقيَّد عليه السندات، ولم يكن
فيه ما يقابل رصيده بكشف المصرف. فكان المحاسب يطابق بورقةٍ وقلم خارج
النظام — والورقة لا تُدقَّق ولا تُؤرشَف ولا يعرف خَلَفه ما فعله ولا
لماذا قبِل فرقاً.

**كيف تُقرأ**: تُعلَّم الحركات التي ظهرت في كشف المصرف، فيُحسب من
غير المعلَّم رصيدٌ متوقَّع في الكشف. يُكتَب الرصيد المُعلَن في الكشف
فيظهر الفرق. الفرق صفراً يعني مطابقةً تامّة، وغير ذلك خطأٌ يُبحث
عنه: قيدٌ ناقص، أو مبلغٌ مقلوب، أو رسمٌ مصرفيٌّ لم يُقيَّد.

**لا تُنشئ قيداً ولا تُعدّل رقماً**: المطابقة شهادةٌ على الدفتر لا
تصحيحٌ له. وما ينقص الدفتر يُقيَّد في «القيود اليومية» بمستنده.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from models import bank_recon as br
from ui.widgets.common import (Card, big_label, bulk_rows, busy, date_edit,
                               dstr, err, info, make_table, mspin,
                               reload_combo, title_label, warn)

COLS = ["✓", "التاريخ", "المستند", "البيان", "وارد (مدين)",
        "صادر (دائن)", "مرجع الكشف", "طُوبق بواسطة"]


class BankReconScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.rows = []

        self.acc = QtWidgets.QComboBox()
        self.acc.setMinimumWidth(240)
        self.acc.currentIndexChanged.connect(self.load)
        self.d_from = date_edit()
        self.d_from.setDate(QtCore.QDate.currentDate().addMonths(-1))
        self.d_to = date_edit()
        self.stmt = mspin(minimum=-1_000_000_000.0)
        self.stmt.setToolTip(
            "الرصيد كما هو مكتوبٌ في كشف المصرف آخر الفترة.\n"
            "اتركه صفراً إن أردت المطابقة بلا مقارنة رصيد.")
        self.stmt.valueChanged.connect(self._recompute)

        btn = QtWidgets.QPushButton("📄 عرض الحركات")
        btn.clicked.connect(self.load)
        btn_all = QtWidgets.QPushButton("✓ تعليم المعروض")
        btn_all.setObjectName("ghost")
        btn_all.setToolTip("يضع علامة المطابقة على كل الحركات المعروضة")
        btn_all.clicked.connect(lambda: self._mark_all(True))
        btn_none = QtWidgets.QPushButton("✗ رفع التعليم")
        btn_none.setObjectName("ghost")
        btn_none.clicked.connect(lambda: self._mark_all(False))
        btn_save = QtWidgets.QPushButton("💾 حفظ المطابقة")
        btn_save.setToolTip(
            "يحفظ علامات المطابقة — لا يُنشئ قيداً ولا يمسّ رقماً")
        btn_save.clicked.connect(self.save)
        btn_print = QtWidgets.QPushButton("🖨 كشف المطابقة")
        btn_print.setObjectName("ghost")
        btn_print.clicked.connect(self.print_statement)

        top = QtWidgets.QGridLayout()
        top.addWidget(QtWidgets.QLabel("الحساب البنكي/النقدي:"), 0, 0)
        top.addWidget(self.acc, 0, 1)
        top.addWidget(QtWidgets.QLabel("من:"), 0, 2)
        top.addWidget(self.d_from, 0, 3)
        top.addWidget(QtWidgets.QLabel("إلى:"), 0, 4)
        top.addWidget(self.d_to, 0, 5)
        top.addWidget(btn, 0, 6)
        top.addWidget(QtWidgets.QLabel("رصيد كشف المصرف:"), 1, 0)
        top.addWidget(self.stmt, 1, 1)
        top.addWidget(btn_all, 1, 2)
        top.addWidget(btn_none, 1, 3)
        top.addWidget(btn_save, 1, 4)
        top.addWidget(btn_print, 1, 5)
        top.setColumnStretch(7, 1)

        self.c_book = Card("رصيد الدفتر", "آخر الفترة")
        self.c_unmatched = Card("غير مطابَق", "حركاتٌ لم تظهر في الكشف")
        self.c_expected = Card("المتوقَّع في الكشف", "بعد استبعاد غير المطابَق")
        self.c_diff = Card("الفرق", "المُعلَن − المتوقَّع")
        tiles = QtWidgets.QHBoxLayout()
        for c in (self.c_book, self.c_unmatched, self.c_expected, self.c_diff):
            tiles.addWidget(c)

        self.table = make_table()
        self.table.setColumnCount(len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.itemChanged.connect(self._on_item_changed)
        self.state = big_label("اختر الحساب والفترة ثم «عرض الحركات».")

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("مطابقة كشف البنك — الدفتر مقابل المصرف"))
        intro = QtWidgets.QLabel(
            "علّم كل حركةٍ ظهرت في كشف المصرف. ما بقي بلا علامة هو ما لم "
            "يصل المصرفَ بعد — شيكٌ لم يُصرَف أو إيداعٌ لم يُقيَّد — "
            "ويُستبعَد ليظهر الرصيد المتوقَّع. فرقٌ غير صفرٍ يعني خللاً "
            "يُبحث عنه، لا رقماً يُقبَل.")
        intro.setObjectName("cardSub")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        lay.addLayout(top)
        lay.addLayout(tiles)
        lay.addWidget(self.state)
        lay.addWidget(self.table, 1)
        note = QtWidgets.QLabel(
            "المطابقة شهادةٌ على الدفتر لا تصحيحٌ له: لا تُنشئ قيداً ولا "
            "تُعدّل رصيداً. ما نقص الدفترَ (رسمٌ مصرفي · فائدة · شيكٌ "
            "مرتدّ) يُقيَّد في «القيود اليومية» بمستنده، ثم يُعاد العرض.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)

        self._loading = False
        # ══ لا قراءة ولا نافذة أثناء البناء ══
        # الشاشة تُبنى داخل `LazyScreen.ensure()` وهو نفسه داخل
        # `switch()`. فأي استعلامٍ يفشل هنا يفتح نافذةً **قافلة** قبل
        # أن تُعرض الشاشة أصلاً، فيقف النظام كله بلا شيءٍ يُضغط.
        # التأجيل دورةَ أحداثٍ واحدة يجعل الشاشة تظهر أولاً، ثم تُقرأ
        # بياناتها ويُعرض أي خطأ فوقها لا قبلها.
        QtCore.QTimer.singleShot(0, self._load_accounts)

    # ───────────────────────────── بيانات
    def _load_accounts(self):
        try:
            with db(readonly=True) as conn:
                accs = br.bank_accounts(conn)
        except Exception as e:
            self.state.setText(f"تعذّرت قراءة الحسابات: {e}")
            err(self, e)
            return
        self._loading = True
        reload_combo(self.acc, accs, lambda a: f"{a['code']} — {a['name']}")
        self._loading = False
        if accs:
            self.load()
        else:
            self.state.setText(
                "لا يوجد حسابٌ نقديٌّ قابل للترحيل — أنشئه في «دليل "
                "الحسابات» بنوع «أصل» ورصيدٍ نقدي.")

    def load(self):
        if self._loading:
            return
        aid = self.acc.currentData()
        if not aid:
            return
        try:
            with busy(self, "جارٍ قراءة حركات الحساب…"):
                with db(readonly=True) as conn:
                    self.rows = br.movements(conn, aid, dstr(self.d_from),
                                             dstr(self.d_to))
        except Exception as e:
            err(self, e)
            return
        self._render()

    def _render(self):
        self._loading = True
        try:
            with bulk_rows(self.table, len(self.rows), COLS):
                for i, r in enumerate(self.rows):
                    chk = QtWidgets.QTableWidgetItem()
                    chk.setFlags((chk.flags() | QtCore.Qt.ItemIsUserCheckable)
                                 & ~QtCore.Qt.ItemIsEditable)
                    chk.setCheckState(QtCore.Qt.Checked if r["matched"]
                                      else QtCore.Qt.Unchecked)
                    self.table.setItem(i, 0, chk)
                    vals = [r["date"], r["doc_no"], r["desc"],
                            f"{r['debit']:,.2f}" if r["debit"] else "",
                            f"{r['credit']:,.2f}" if r["credit"] else "",
                            r["ref"], r["matched_by"] or ""]
                    for c, v in enumerate(vals, start=1):
                        it = QtWidgets.QTableWidgetItem(str(v))
                        it.setTextAlignment(QtCore.Qt.AlignCenter)
                        if c == 6:          # مرجع الكشف وحده يُكتب فيه
                            it.setFlags(it.flags() | QtCore.Qt.ItemIsEditable)
                        else:
                            it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
                        if not r["matched"]:
                            it.setForeground(QtGui.QColor("#8A6D1D"))
                        self.table.setItem(i, c, it)
        finally:
            self._loading = False
        self._recompute()

    # ───────────────────────────── حساب
    def _recompute(self):
        """يعيد حساب الكشف من حالة الجدول — بلا قراءةٍ من القاعدة."""
        opening = 0.0
        aid = self.acc.currentData()
        if aid:
            try:
                with db(readonly=True) as conn:
                    opening = br.opening_balance(conn, aid, dstr(self.d_from))
            except Exception:
                opening = 0.0
        book = opening + sum(r["debit"] - r["credit"] for r in self.rows)
        un_in = sum(r["debit"] for r in self.rows if not r["matched"])
        un_out = sum(r["credit"] for r in self.rows if not r["matched"])
        expected = book - un_in + un_out
        n_un = sum(1 for r in self.rows if not r["matched"])

        self.c_book.set_value(f"{book:,.2f}", f"الافتتاحي {opening:,.2f}")
        self.c_unmatched.set_value(
            f"{n_un:,}", f"وارد {un_in:,.2f} · صادر {un_out:,.2f}")
        self.c_expected.set_value(f"{expected:,.2f}")

        stmt = float(self.stmt.value() or 0)
        if not stmt:
            self.c_diff.set_value("—", "اكتب رصيد الكشف للمقارنة")
            self.state.setText(
                f"{len(self.rows):,} حركة · طُوبق "
                f"{len(self.rows) - n_un:,} · بقي {n_un:,}")
            return
        diff = round(stmt - expected, 2)
        self.c_diff.set_value(f"{diff:,.2f}",
                              "مطابقة تامّة" if diff == 0 else "يحتاج بحثاً")
        self.state.setText(
            ("✔ مطابقةٌ تامّة — رصيد الكشف يساوي المتوقَّع بالضبط."
             if diff == 0 else
             f"⚠ فرقٌ قدره {diff:,.2f} ريال — ابحث عن قيدٍ ناقص أو مبلغٍ "
             f"مقلوب أو رسمٍ مصرفيٍّ لم يُقيَّد.")
            + f"   |   {len(self.rows):,} حركة · بقي {n_un:,} بلا مطابقة")

    def _on_item_changed(self, item):
        if self._loading or item is None:
            return
        i = item.row()
        if not (0 <= i < len(self.rows)):
            return
        if item.column() == 0:
            self.rows[i]["matched"] = (
                item.checkState() == QtCore.Qt.Checked)
            self._recompute()
        elif item.column() == 6:
            self.rows[i]["ref"] = item.text().strip()

    def _mark_all(self, value):
        self._loading = True
        try:
            for i, r in enumerate(self.rows):
                r["matched"] = bool(value)
                it = self.table.item(i, 0)
                if it is not None:
                    it.setCheckState(QtCore.Qt.Checked if value
                                     else QtCore.Qt.Unchecked)
        finally:
            self._loading = False
        self._recompute()

    # ───────────────────────────── حفظ وطباعة
    def save(self):
        if not self.rows:
            warn(self, "لا حركات معروضة.")
            return
        on = [r for r in self.rows if r["matched"]]
        off = [r for r in self.rows if not r["matched"]]
        try:
            who = self.user.get("username", "")
            with db() as conn:
                for r in on:
                    br.set_matched(conn, [r["line_id"]], True, who, r["ref"])
                br.set_matched(conn, [r["line_id"] for r in off], False, who)
        except Exception as e:
            err(self, e)
            return
        info(self, f"حُفظت المطابقة: {len(on):,} حركة معلَّمة، "
                   f"{len(off):,} بلا علامة.\n\n"
                   "لم يُنشأ قيدٌ ولم يتغيّر رصيد.")
        self.load()

    def print_statement(self):
        """كشف المطابقة نصّاً جاهزاً للنسخ أو الطباعة أو الإرفاق بالملف."""
        if not self.rows:
            warn(self, "لا حركات معروضة.")
            return
        aid = self.acc.currentData()
        try:
            with db(readonly=True) as conn:
                s = br.summary(conn, aid, dstr(self.d_from), dstr(self.d_to),
                               float(self.stmt.value() or 0) or None)
        except Exception as e:
            err(self, e)
            return
        un = [r for r in self.rows if not r["matched"]]
        lines = [
            f"كشف مطابقة البنك — {self.acc.currentText()}",
            f"الفترة: {dstr(self.d_from)} إلى {dstr(self.d_to)}",
            "",
            f"الرصيد الافتتاحي          {s['opening']:>16,.2f}",
            f"رصيد الدفتر آخر الفترة    {s['book']:>16,.2f}",
            f"− إيداعات لم تظهر بالكشف  {s['unmatched_in']:>16,.2f}",
            f"+ شيكات لم تُصرَف بعد      {s['unmatched_out']:>16,.2f}",
            "─" * 46,
            f"= الرصيد المتوقَّع بالكشف  {s['expected']:>16,.2f}",
        ]
        if s["statement"] is not None:
            lines += [
                f"  الرصيد المُعلَن بالكشف   {s['statement']:>16,.2f}",
                f"  الفــــــــرق            {s['difference']:>16,.2f}",
                "",
                ("✔ مطابقة تامّة." if s["difference"] == 0
                 else "⚠ الفرق غير صفر — راجع الحركات غير المطابَقة أدناه، "
                      "وابحث عن قيدٍ ناقص أو مبلغٍ مقلوب."),
            ]
        if un:
            lines += ["", f"الحركات غير المطابَقة ({len(un):,}):"]
            for r in un[:80]:
                amt = r["debit"] or -r["credit"]
                lines.append(f"  {r['date']}  {r['doc_no']:<12} "
                             f"{amt:>14,.2f}  {r['desc'][:40]}")
            if len(un) > 80:
                lines.append(f"  … و{len(un) - 80:,} حركة أخرى")
        text = "\n".join(lines)
        QtWidgets.QApplication.clipboard().setText(text)
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("كشف المطابقة")
        box.setIcon(QtWidgets.QMessageBox.Information)
        box.setText("نُسخ كشف المطابقة — ألصقه في أي مستند.")
        box.setDetailedText(text)
        box.exec_()

    def refresh(self):
        self.load()
