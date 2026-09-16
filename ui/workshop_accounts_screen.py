# -*- coding: utf-8 -*-
"""شاشة حسابات الورشة — مقارنة أرصدة عدة حسابات في واجهة واحدة.

الغرض: بدل فتح كشف كل حساب على حدة، يُضاف الحساب سطراً في جدول
مقارنة يعرض إجمالي المدين والدائن (ذهباً ونقداً) والرصيد الحالي —
فتُقارَن حسابات الورشة التشغيلية دفعةً واحدة.
"""
import json
from pathlib import Path

from PyQt5 import QtCore, QtWidgets

from database.database import db
from services import karat_view as kv
from ui.widgets.common import (ask, big_label, date_edit, dstr, err, fill,
                               info, make_table, search_combo, title_label)


class WorkshopAccountsScreen(QtWidgets.QWidget):
    STATE_FILE = "workshop_compare.json"

    def __init__(self, user):
        super().__init__()
        self.user = user
        # المقارنة تُحفظ بين الجلسات: المستخدم يبني مقارنته مرة
        # ويجدها كما تركها — لا يعيد بناءها كل فتح.
        self.rows = self._load_state()

        self.account = search_combo("اكتب رقم الحساب أو اسمه…")
        self.account.setMinimumWidth(300)
        self.account.setMaximumWidth(340)
        self.account.setSizePolicy(QtWidgets.QSizePolicy.Fixed,
                                   QtWidgets.QSizePolicy.Fixed)
        self.d_from = date_edit()
        self.d_from.setDate(
            QtCore.QDate(QtCore.QDate.currentDate().year(), 1, 1))
        self.d_to = date_edit()

        btn_add = QtWidgets.QPushButton("➕ إضافة الحساب للمقارنة")
        btn_add.setObjectName("homeBtn")
        btn_add.clicked.connect(self.add_account)
        btn_del = QtWidgets.QPushButton("🗑 حذف السطر")
        btn_del.clicked.connect(self.remove_row)
        btn_clear = QtWidgets.QPushButton("↺ تفريغ الجدول")
        btn_clear.clicked.connect(self.clear_all)
        btn_reload = QtWidgets.QPushButton("↻ تحديث الأرصدة")
        btn_reload.clicked.connect(self.reload_all)
        btn_print = QtWidgets.QPushButton("🖨 طباعة المقارنة")
        btn_print.clicked.connect(self.print_cmp)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(QtWidgets.QLabel("الحساب:"))
        head.addWidget(self.account, 0)
        head.addWidget(QtWidgets.QLabel("من:"))
        head.addWidget(self.d_from, 0)
        head.addWidget(QtWidgets.QLabel("إلى:"))
        head.addWidget(self.d_to, 0)
        head.addWidget(btn_add, 0)
        head.addStretch(1)

        row2 = QtWidgets.QHBoxLayout()
        row2.addWidget(btn_reload)
        row2.addWidget(btn_del)
        row2.addWidget(btn_clear)
        row2.addWidget(btn_print)
        row2.addStretch(1)

        self.table = make_table()
        self.summary = big_label()
        note = QtWidgets.QLabel(
            "اختر حساباً واضغط «إضافة» لينزل سطراً في الجدول، ثم أضف "
            "حساباً آخر — فتقارن أرصدة عدة حسابات في واجهة واحدة.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("حسابات الورشة — مقارنة الأرصدة"))
        lay.addWidget(note)
        lay.addLayout(head)
        lay.addLayout(row2)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.summary)
        self.refresh()

    # ══════════ الحفظ بين الجلسات ══════════
    def _state_path(self):
        import config
        d = Path(config.BASE_DIR) / "data"
        d.mkdir(parents=True, exist_ok=True)
        return d / self.STATE_FILE

    def _load_state(self):
        try:
            p = self._state_path()
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                return [x for x in data if isinstance(x, dict)
                        and x.get("id")]
        except Exception:
            pass
        return []

    def _save_state(self):
        try:
            self._state_path().write_text(
                json.dumps([{k: r[k] for k in ("id", "code", "name")}
                            for r in self.rows], ensure_ascii=False),
                encoding="utf-8")
        except Exception:
            pass

    # ══════════ البيانات ══════════
    def refresh(self):
        try:
            with db() as conn:
                accs = conn.execute(
                    "SELECT id, code, name FROM accounts WHERE is_postable=1"
                    " ORDER BY code").fetchall()
            cur = self.account.currentData()
            self.account.clear()
            for a in accs:
                self.account.addItem(f"{a['code']} — {a['name']}", a["id"])
            if cur is not None:
                i = self.account.findData(cur)
                if i >= 0:
                    self.account.setCurrentIndex(i)
            if self.rows:
                self.reload_all()      # يحدّث أرصدة المقارنة المحفوظة
            else:
                self.render()
        except Exception as e:
            err(self, e)

    def _totals(self, conn, account_id):
        """إجمالي المدين والدائن والرصيد خلال الفترة."""
        r = conn.execute(
            "SELECT COALESCE(SUM(l.gold_debit),0) gd,"
            " COALESCE(SUM(l.gold_credit),0) gc,"
            " COALESCE(SUM(l.cash_debit),0) cd,"
            " COALESCE(SUM(l.cash_credit),0) cc"
            " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
            " WHERE e.is_deleted=0 AND l.account_id=?"
            " AND e.entry_date BETWEEN ? AND ?",
            (account_id, dstr(self.d_from), dstr(self.d_to))).fetchone()
        return (round(r["gd"], 3), round(r["gc"], 3),
                round(r["cd"], 2), round(r["cc"], 2))

    def add_account(self):
        try:
            aid = self.account.currentData()
            if aid is None:
                raise ValueError("اختر حساباً من القائمة")
            if any(x["id"] == aid for x in self.rows):
                raise ValueError("الحساب مضاف مسبقاً في الجدول")
            with db() as conn:
                a = conn.execute(
                    "SELECT code, name FROM accounts WHERE id=?",
                    (aid,)).fetchone()
                gd, gc, cd, cc = self._totals(conn, aid)
            self.rows.append({
                "id": aid, "code": a["code"], "name": a["name"],
                "gd": gd, "gc": gc, "cd": cd, "cc": cc})
            self.render()
            self._save_state()
        except Exception as e:
            err(self, e)

    def reload_all(self):
        try:
            with db() as conn:
                for x in self.rows:
                    gd, gc, cd, cc = self._totals(conn, x["id"])
                    x.update({"gd": gd, "gc": gc, "cd": cd, "cc": cc})
            self.render()
            self._save_state()
        except Exception as e:
            err(self, e)

    def remove_row(self):
        i = self.table.currentRow()
        if 0 <= i < len(self.rows):
            self.rows.pop(i)
            self.render()
            self._save_state()

    def clear_all(self):
        if self.rows and ask(self, "تفريغ جدول المقارنة؟"):
            self.rows = []
            self.render()
            self._save_state()

    def render(self):
        data = []
        tg = tc = 0.0
        for x in self.rows:
            gbal = round(x["gd"] - x["gc"], 3)
            cbal = round(x["cd"] - x["cc"], 2)
            tg += gbal
            tc += cbal
            data.append((
                f"{x['code']} — {x['name']}",
                f"{x['gd']:,.3f}", f"{x['gc']:,.3f}", f"{gbal:,.3f}",
                f"{x['cd']:,.2f}", f"{x['cc']:,.2f}", f"{cbal:,.2f}"))
        fill(self.table,
             ["الحساب", "مدين ذهب", "دائن ذهب", "رصيد الذهب",
              "مدين نقد", "دائن نقد", "رصيد النقد"], data)
        self.summary.setText(
            f"{len(self.rows)} حساب   |   مجموع أرصدة الذهب: "
            f"{kv.g(tg):,.3f} {kv.unit()}   |   "
            f"مجموع أرصدة النقد: {tc:,.2f} ريال")

    def print_cmp(self):
        try:
            from services import print_manager
            print_manager.preview_document(
                self, "workshop_accounts", 0, rows=self.rows,
                date_from=dstr(self.d_from), date_to=dstr(self.d_to))
        except Exception as e:
            err(self, e)
