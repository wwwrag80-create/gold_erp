# -*- coding: utf-8 -*-
"""تفصيل حركة حساب — من أين جاء الرقم ومتى.

رقمٌ في ميزان المراجعة أو المركز المالي أو قائمة الدخل لا يكفي
المراجعَ وحده: يسأل «ما السندات التي كوّنته؟». هذه النافذة تفتح من أي
حسابٍ في «القوائم المالية» كشفَ حركته في فترة القائمة نفسها: التاريخ،
نوع العملية، **رقم السند**، الجهة المقابلة، البيان، المدين والدائن
والرصيد المتراكم بالريال وبالوزن — وآخر رصيدٍ فيها هو رقم القائمة.
والنقر المزدوج على سطرٍ يفتح السند الأصلي نفسه (فاتورة · سند قبض أو
صرف · مشتريات · قيد يومية).

`AccountsPicker`: بندٌ في القائمة يجمع أكثر من حساب (المخزون، الذمم
المدينة…) — تُعرض حساباته بأرصدتها، ومنها يُفتح كشف كلٍّ منها.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from services import karat_view as kv
from ui.widgets.common import err, make_table, title_label

# ما تستبعده كل قائمة من القيود — فيطابق آخرُ رصيدٍ رقمَها
# · قائمة الدخل: قيد الإقفال السنوي (يصفّر الإيراد والمصروف)
# · المركز المالي: قيدا الإقفال الدفتري وفتح السنة المتعاكسان
PL_EXCLUDE = "COALESCE(e.source_table,'')='year_close'"


def bs_exclude():
    from models import statements
    return statements._BOOK_PAIR


def _ids(conn, code):
    """الحساب وكل فروعه — كشف المجموعة هو كشف فروعها مجتمعة."""
    from models.accounts import subtree_ids_by_code
    return subtree_ids_by_code(conn, code)


def _num(v, gold=False):
    if gold:
        v = kv.g(v)
        return f"{v:,.3f}" if abs(v) >= 0.0005 else ""
    return f"{v:,.2f}" if abs(v) >= 0.005 else ""


def _bal(v, gold=False):
    """رصيدٌ متراكم: يُطبع صفره ولا يُترك فارغاً."""
    if gold:
        return f"{kv.g(v):,.3f}"
    return f"{v:,.2f}"


class AccountMovementDialog(QtWidgets.QDialog):
    """كشف حركة حساب (أو مجموعة) في فترة، بأرقام السندات."""

    def __init__(self, parent, code, name="", date_from=None, date_to=None,
                 exclude_sql=None):
        super().__init__(parent)
        self.code = code
        self.date_from = date_from or None
        self.date_to = date_to or None
        self.exclude_sql = exclude_sql
        self.rows = []
        self.setWindowTitle(f"تفصيل حركة الحساب — {code} {name}".strip())
        self.setLayoutDirection(QtCore.Qt.RightToLeft)
        self.resize(1180, 640)

        per = (f"من {self.date_from} إلى {self.date_to}"
               if self.date_from else f"حتى {self.date_to or 'اليوم'}")
        head = title_label(f"{code} — {name}")
        sub = QtWidgets.QLabel(
            f"{per} · النقر المزدوج على أي سطر يفتح السند الذي أنشأه")
        sub.setWordWrap(True)

        self.table = make_table()
        self.table.doubleClicked.connect(lambda *_: self.open_selected())
        self.summary = QtWidgets.QLabel("")
        self.summary.setObjectName("big")
        self.summary.setWordWrap(True)

        b_open = QtWidgets.QPushButton("👁 فتح السند المحدد")
        b_open.setObjectName("homeBtn")
        b_open.clicked.connect(self.open_selected)
        b_print = QtWidgets.QPushButton("🖨 طباعة الكشف")
        b_print.clicked.connect(self.print_statement)
        b_close = QtWidgets.QPushButton("إغلاق")
        b_close.setObjectName("ghost")
        b_close.clicked.connect(self.reject)
        btns = QtWidgets.QHBoxLayout()
        btns.addWidget(b_open)
        btns.addWidget(b_print)
        btns.addStretch(1)
        btns.addWidget(b_close)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(head)
        lay.addWidget(sub)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.summary)
        lay.addLayout(btns)
        self.load()

    # ──────────────────────────────────────────────────────────────
    def load(self):
        from models import journal
        with db(readonly=True) as conn:
            ids = _ids(conn, self.code)
            if not ids:
                raise ValueError(f"الحساب {self.code} غير موجود")
            self.rows = journal.statement(conn, ids, self.date_from,
                                          self.date_to,
                                          exclude_sql=self.exclude_sql)
        self._render()

    def _render(self):
        rows = self.rows
        has_g = any(abs(r["gd"]) + abs(r["gc"]) + abs(r["gbal"]) >= 0.0005
                    for r in rows)
        has_c = any(abs(r["cd"]) + abs(r["cc"]) + abs(r["cbal"]) >= 0.005
                    for r in rows)
        if not has_g and not has_c:
            has_c = True
        u = kv.unit()
        cols = [("التاريخ", 9), ("نوع العملية", 10), ("رقم السند", 9),
                ("الجهة / الحساب المقابل", 17), ("البيان", 15)]
        keys = []
        if has_c:
            cols += [("مدين\nريال", 9), ("دائن\nريال", 9),
                     ("الرصيد\nريال", 10)]
            keys += [("cd", False), ("cc", False), ("cbal", False)]
        if has_g:
            cols += [(f"مدين\n{u}", 8), (f"دائن\n{u}", 8),
                     (f"الرصيد\n{u}", 9)]
            keys += [("gd", True), ("gc", True), ("gbal", True)]
        t = self.table
        t.setUpdatesEnabled(False)
        try:
            t.clear()
            t.setColumnCount(len(cols))
            t.setHorizontalHeaderLabels([c for c, _w in cols])
            t.setRowCount(len(rows))
            bold = QtGui.QFont(t.font())
            bold.setBold(True)
            for i, r in enumerate(rows):
                opening = r.get("op") == "رصيد سابق"
                vals = [r["date"] or "", r["op"] or "",
                        str(r.get("doc_no") or ""), r.get("name") or "",
                        r.get("desc") or ""]
                for k, gold in keys:
                    v = r[k]
                    vals.append(_bal(v, gold) if k.endswith("bal")
                                else _num(v, gold))
                for c, s in enumerate(vals):
                    it = QtWidgets.QTableWidgetItem(s)
                    it.setTextAlignment(
                        (QtCore.Qt.AlignRight if c in (3, 4)
                         else QtCore.Qt.AlignCenter) | QtCore.Qt.AlignVCenter)
                    if c in (3, 4) and s:
                        it.setToolTip(s)
                    if opening or c == 2:
                        it.setFont(bold)
                    t.setItem(i, c, it)
        finally:
            t.setUpdatesEnabled(True)
        try:
            from ui.widgets.table_fit import fit_columns
            fit_columns(t, [w for _c, w in cols])
        except Exception:
            pass
        # الخلاصة: أول الفترة · الحركة · آخرها
        mov = [r for r in rows if r.get("op") != "رصيد سابق"]
        first = rows[0] if rows and rows[0].get("op") == "رصيد سابق" \
            else None
        parts = [f"عدد الحركات: {len(mov)}"]
        if has_c:
            o = first["cbal"] if first else 0.0
            dr = sum(r["cd"] for r in mov)
            cr = sum(r["cc"] for r in mov)
            end = rows[-1]["cbal"] if rows else 0.0
            parts.append(f"ريال: أول الفترة {_bal(o)} · مدين {_bal(dr)}"
                         f" · دائن {_bal(cr)} · الرصيد {_bal(end)}")
        if has_g:
            o = first["gbal"] if first else 0.0
            dr = sum(r["gd"] for r in mov)
            cr = sum(r["gc"] for r in mov)
            end = rows[-1]["gbal"] if rows else 0.0
            parts.append(f"{u}: أول الفترة {_bal(o, True)} · مدين"
                         f" {_bal(dr, True)} · دائن {_bal(cr, True)}"
                         f" · الرصيد {_bal(end, True)}")
        self.summary.setText("\n".join(parts))

    # ──────────────────────────────────────────────────────────────
    def open_selected(self):
        """يفتح السند الأصلي للسطر المحدد (أو قيده إن لم يكن له قالب)."""
        try:
            i = self.table.currentRow()
            if not (0 <= i < len(self.rows)):
                raise ValueError("اختر سطراً من الكشف أولاً")
            r = self.rows[i]
            if r.get("op") == "رصيد سابق":
                raise ValueError("«رصيد سابق» مجموع ما قبل الفترة — ليس"
                                 " سنداً واحداً. وسّع الفترة لترى سنداته")
            from services import print_manager
            from ui.general_ledger_screen import _doc_target
            target = _doc_target(r, print_manager.BUILDERS)
            if target is None:
                raise ValueError("لا مستند مرتبط بهذا السطر")
            print_manager.preview_document(self, *target)
        except Exception as e:
            err(self, e)

    def print_statement(self):
        try:
            from services import print_manager
            with db(readonly=True) as conn:
                acc = conn.execute("SELECT id FROM accounts WHERE code=?",
                                   (self.code,)).fetchone()
            if not acc:
                raise ValueError("الحساب غير موجود")
            print_manager.preview_document(
                self, "statement", acc["id"],
                date_from=self.date_from or "", date_to=self.date_to or "")
        except Exception as e:
            err(self, e)


def show_movement(parent, code, name="", date_from=None, date_to=None,
                  exclude_sql=None):
    """يفتح كشف حركة الحساب — والخطأ يُعرض ولا يُسقط الشاشة."""
    try:
        if not code or not str(code)[:1].isdigit():
            raise ValueError("هذا السطر مجموعٌ محسوب وليس حساباً — اختر"
                             " حساباً من تفصيله")
        dlg = AccountMovementDialog(parent, str(code), name, date_from,
                                    date_to, exclude_sql)
        dlg.exec_()
        return dlg
    except Exception as e:
        err(parent, e)
        return None


class AccountsPicker(QtWidgets.QDialog):
    """حسابات بندٍ من القائمة بأرصدتها — ومن كلٍّ منها كشف حركته.

    items: [(code, name, cash, gold)]
    """

    def __init__(self, parent, title, items, date_from=None, date_to=None,
                 exclude_sql=None, note=""):
        super().__init__(parent)
        self.items = [x for x in items]
        self.date_from, self.date_to = date_from, date_to
        self.exclude_sql = exclude_sql
        self.setWindowTitle(f"تفصيل البند — {title}")
        self.setLayoutDirection(QtCore.Qt.RightToLeft)
        self.resize(720, 460)
        t = self.table = make_table()
        heads = ["الكود", "الحساب", "ريال", f"ذهب ({kv.unit()})"]
        t.setColumnCount(4)
        t.setHorizontalHeaderLabels(heads)
        t.setRowCount(len(self.items))
        for i, (code, name, cash, gold) in enumerate(self.items):
            for c, s in enumerate((code, name, _bal(cash), _bal(gold, True))):
                it = QtWidgets.QTableWidgetItem(s)
                it.setTextAlignment((QtCore.Qt.AlignRight if c == 1
                                     else QtCore.Qt.AlignHCenter)
                                    | QtCore.Qt.AlignVCenter)
                t.setItem(i, c, it)
        t.doubleClicked.connect(lambda *_: self.open_selected())
        b_mov = QtWidgets.QPushButton("🔎 تفصيل حركة الحساب المحدد")
        b_mov.setObjectName("homeBtn")
        b_mov.clicked.connect(self.open_selected)
        b_close = QtWidgets.QPushButton("إغلاق")
        b_close.setObjectName("ghost")
        b_close.clicked.connect(self.reject)
        btns = QtWidgets.QHBoxLayout()
        btns.addWidget(b_mov)
        btns.addStretch(1)
        btns.addWidget(b_close)
        lbl = QtWidgets.QLabel(
            (note + " · " if note else "")
            + "النقر المزدوج على حساب يفتح حركته بأرقام السندات")
        lbl.setWordWrap(True)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label(title))
        lay.addWidget(t, 1)
        lay.addWidget(lbl)
        lay.addLayout(btns)
        try:
            from ui.widgets.table_fit import fit_columns
            fit_columns(t, [14, 46, 20, 20])
        except Exception:
            pass

    def open_selected(self):
        i = self.table.currentRow()
        if not (0 <= i < len(self.items)):
            err(self, ValueError("اختر حساباً من القائمة أولاً"))
            return
        code, name = self.items[i][0], self.items[i][1]
        show_movement(self, code, name, self.date_from, self.date_to,
                      self.exclude_sql)


def merge_detail(st_or_fp, key):
    """حسابات بندٍ من تفصيل القائمة بالبعدين: [(code, name, cash, gold)]."""
    acc = {}
    for dim in ("cash", "gold"):
        for code, name, amt in st_or_fp[dim]["detail"].get(key, []):
            e = acc.setdefault((code, name), {"cash": 0.0, "gold": 0.0})
            e[dim] += amt
    return [(c, n, v["cash"], v["gold"]) for (c, n), v in sorted(acc.items())]
