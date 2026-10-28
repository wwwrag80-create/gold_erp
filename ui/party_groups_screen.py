# -*- coding: utf-8 -*-
"""شاشة مجموعات العملاء والجهات (4.79).

مجموعةٌ مثل «عملاء الرميزان» حسابٌ تجميعي تحت «إجمالي العملاء» وعملاؤها
فروعه — فلكل عميلٍ رصيده، وللمجموعة مجموعُ أرصدتهم (`models.party_groups`).

يمين الشاشة المجموعات برصيد كلٍّ وحالته وعدد عملائها؛ واليسار عملاء
المجموعة المحددة برصيد كلٍّ منهم ذهباً ونقداً وحالته (مدين/دائن). البحث
يجد المجموعة أو العميل، والنقر المزدوج على عميلٍ يفتح كشف حسابه.

4.80: المجموعة الجديدة تُنشأ ومعها عملاؤها من أي مجموعةٍ كانوا فيها
(ينتقلون إليها ويخرجون من السابقة)، وتُطبع المجموعة أو المجموعات كلها.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from ui import kit

from database.database import db
from models import party_groups as pg
from services import karat_view as kv
from ui.widgets.common import (ask, date_edit, dstr, err, info, make_table,
                               title_label)
from services import numfmt as _nf
from ui.widgets.common import guard_click

NO_GROUP = -1      # صفّ «بلا مجموعة» — من حساباتهم تحت الأصل مباشرة


def _bal(v, gold):
    """(الرصيد بلا إشارة، حالته) — مدين/دائن، والصفر شرطة."""
    v = kv.g(v) if gold else float(v or 0.0)
    d = 3 if gold else 2
    st = pg.state(v, gold)
    return (_nf.f2(abs(v)) if st != "—" else "—"), st


_RED, _GREEN = QtGui.QColor("#a4262c"), QtGui.QColor("#107c10")


class AddMembersDialog(QtWidgets.QDialog):
    """اختيار جهاتٍ تُنقل إلى المجموعة — من أي مجموعةٍ كانت فيها.

    `ask_name`: نافذة «مجموعة جديدة» — الاسم ثم عملاؤها في خطوةٍ واحدة."""

    def __init__(self, parent, rows, group_name, ask_name=False):
        super().__init__(parent)
        self.setWindowTitle("مجموعة جديدة" if ask_name
                            else f"إضافة إلى «{group_name}»")
        self.setLayoutDirection(QtCore.Qt.RightToLeft)
        self.resize(500, 600)
        self.name = kit.LineEdit()
        self.name.setPlaceholderText("اسم المجموعة — مثل «عملاء الرميزان»")
        self.name.setVisible(ask_name)
        hint = QtWidgets.QLabel(
            "حدّد الحسابات التي تنتقل إلى المجموعة — من أي مجموعةٍ كانت"
            " فيها: تخرج من مجموعتها السابقة، ويبقى رصيدها وكشفها كما هما.")
        hint.setWordWrap(True)
        hint.setObjectName("cardSub")
        self.find = kit.LineEdit()
        self.find.setPlaceholderText("🔍 ابحث بالاسم أو الكود…")
        self.find.textChanged.connect(self._filter)
        self.lst = QtWidgets.QListWidget()
        for r in rows:
            where = (f"   ← في «{r['group']}»" if r.get("group")
                     else "   ← بلا مجموعة")
            it = QtWidgets.QListWidgetItem(f"{r['code']} · {r['name']}{where}")
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Unchecked)
            it.setData(QtCore.Qt.UserRole, r["entity_id"])
            self.lst.addItem(it)
        ok = kit.PushButton("إنشاء المجموعة ونقل المحدَّدين إليها"
                            if ask_name else "نقل المحدَّدين إلى المجموعة")
        ok.setObjectName("homeBtn")
        ok.clicked.connect(self.accept)
        cancel = kit.PushButton("إلغاء")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        b = QtWidgets.QHBoxLayout()
        b.addWidget(ok)
        b.addStretch(1)
        b.addWidget(cancel)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self.name)
        lay.addWidget(hint)
        lay.addWidget(self.find)
        lay.addWidget(self.lst, 1)
        lay.addLayout(b)

    def _filter(self, text):
        from ui.widgets.common import _norm
        q = _norm(text).strip()
        for i in range(self.lst.count()):
            it = self.lst.item(i)
            it.setHidden(bool(q) and q not in _norm(it.text()))

    def chosen(self):
        return [self.lst.item(i).data(QtCore.Qt.UserRole)
                for i in range(self.lst.count())
                if self.lst.item(i).checkState() == QtCore.Qt.Checked]


class PartyGroupsScreen(QtWidgets.QWidget):
    def __init__(self, user, on_drill_account=None):
        super().__init__()
        self.user = user
        self.on_drill_account = on_drill_account
        self.groups = []
        self.rows = []

        self.kind = kit.ComboBox()
        self.kind.addItem("مجموعات العملاء", "customer")
        self.kind.addItem("مجموعات الجهات الأخرى", "other")
        self.kind.currentIndexChanged.connect(self._reload)
        self.as_of = date_edit()
        self.as_of.dateChanged.connect(self._reload)
        self.search = kit.LineEdit()
        self.search.setPlaceholderText(
            "🔍 ابحث عن مجموعة (مثل الرميزان) أو عميل…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_search)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.kind)
        top.addWidget(QtWidgets.QLabel("الأرصدة حتى:"))
        top.addWidget(self.as_of)
        top.addWidget(self.search, 1)

        # ── المجموعات ──
        self.g_table = make_table()
        self.g_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows)
        self.g_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection)
        self.g_table.itemSelectionChanged.connect(self.load_members)
        b_new = kit.PushButton("➕ مجموعة جديدة")
        b_new.setObjectName("homeBtn")
        b_new.clicked.connect(self.new_group)
        b_ren = kit.PushButton("✎ تسمية")
        b_ren.clicked.connect(self.rename_group)
        b_del = kit.PushButton("🗑 حذف")
        b_del.setToolTip("تُحذف المجموعة الخالية وحدها")
        b_del.clicked.connect(self.delete_group)
        gb = QtWidgets.QHBoxLayout()
        for b in (b_new, b_ren, b_del):
            gb.addWidget(b)
        gb.addStretch(1)
        left = QtWidgets.QWidget()
        gl = QtWidgets.QVBoxLayout(left)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.addWidget(QtWidgets.QLabel("<b>المجموعات</b>"))
        gl.addWidget(self.g_table, 1)
        gl.addLayout(gb)

        # ── أعضاء المجموعة ──
        self.title = QtWidgets.QLabel("")
        self.title.setObjectName("big")
        self.m_table = make_table()
        self.m_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows)
        self.m_table.doubleClicked.connect(guard_click(lambda *_: self.open_ledger()))
        b_add = kit.PushButton("➕ إضافة عملاء للمجموعة")
        b_add.setObjectName("homeBtn")
        b_add.clicked.connect(self.add_members)
        b_out = kit.PushButton("↩ إخراج من المجموعة")
        b_out.clicked.connect(self.remove_members)
        b_led = kit.PushButton("📄 كشف حساب العميل")
        b_led.clicked.connect(self.open_ledger)
        b_prn = kit.PushButton("🖨 معاينة المجموعة")
        b_prn.setToolTip("أرصدة عملاء المجموعة الظاهرين وحالة كلٍّ منهم")
        b_prn.clicked.connect(self.print_group)
        b_all = kit.PushButton("🖨 معاينة كل المجموعات")
        b_all.setToolTip("كل مجموعةٍ برصيدها وحالته ثم عملاؤها")
        b_all.clicked.connect(self.print_all)
        mb = QtWidgets.QHBoxLayout()
        for b in (b_add, b_out, b_led, b_prn, b_all):
            mb.addWidget(b)
        mb.addStretch(1)
        right = QtWidgets.QWidget()
        ml = QtWidgets.QVBoxLayout(right)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.addWidget(self.title)
        ml.addWidget(self.m_table, 1)
        ml.addLayout(mb)

        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 5)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("مجموعات العملاء والجهات"))
        lay.addLayout(top)
        lay.addWidget(split, 1)
        self.refresh()

    # ══ القراءة ══
    def _reload(self, *_):
        self.refresh()

    def _kind(self):
        return self.kind.currentData() or "customer"

    def _gid(self):
        r = self.g_table.currentRow()
        if not (0 <= r < self.g_table.rowCount()):
            return None
        it = self.g_table.item(r, 0)
        return it.data(QtCore.Qt.UserRole) if it is not None else None

    def refresh(self, keep=None):
        try:
            keep = keep if keep is not None else self._gid()
            with db(readonly=True) as conn:
                self.groups = pg.groups(conn, self._kind(), dstr(self.as_of))
                loose = pg.members(conn, None, dstr(self.as_of), self._kind())
            rows = [{"id": NO_GROUP, "code": "", "name": "بلا مجموعة",
                     "count": len(loose), "depth": 0,
                     "gold": sum(x["gold"] for x in loose),
                     "cash": sum(x["cash"] for x in loose)}] + self.groups
            t = self.g_table
            t.blockSignals(True)
            t.clear()
            heads = ["المجموعة", "الكود", "العدد",
                     f"رصيد الذهب ({kv.unit()})", "حالته",
                     "الرصيد النقدي (ريال)", "حالته"]
            t.setColumnCount(len(heads))
            t.setHorizontalHeaderLabels(heads)
            t.setRowCount(len(rows))
            sel = 0
            for i, g in enumerate(rows):
                gv, gs = _bal(g["gold"], True)
                cv, cs = _bal(g["cash"], False)
                vals = ["   " * g.get("depth", 0) + g["name"], g["code"],
                        str(g["count"]), gv, gs, cv, cs]
                for c, v in enumerate(vals):
                    it = QtWidgets.QTableWidgetItem(v)
                    it.setTextAlignment(QtCore.Qt.AlignCenter if c else
                                        QtCore.Qt.AlignRight
                                        | QtCore.Qt.AlignVCenter)
                    if c == 0:
                        it.setData(QtCore.Qt.UserRole, g["id"])
                    if g["id"] == NO_GROUP:
                        it.setForeground(QtGui.QBrush(QtGui.QColor("#666")))
                    elif c in (4, 6) and v != "—":
                        it.setForeground(QtGui.QBrush(
                            _RED if v == "مدين" else _GREEN))
                    t.setItem(i, c, it)
                if g["id"] == keep:
                    sel = i
            t.blockSignals(False)
            if rows and len(rows) > 1 and keep is None:
                sel = 1                    # أول مجموعةٍ حقيقية
            t.selectRow(sel)
            self.load_members()
            self._apply_search()
        except Exception as e:
            err(self, e)

    def load_members(self):
        gid = self._gid()
        try:
            with db(readonly=True) as conn:
                self.rows = pg.members(
                    conn, None if gid in (None, NO_GROUP) else gid,
                    dstr(self.as_of), self._kind())
        except Exception as e:
            self.rows = []
            err(self, e)
        g = next((x for x in self.groups if x["id"] == gid), None)
        name = g["name"] if g else "بلا مجموعة"
        tg = sum(r["gold"] for r in self.rows)
        tc = sum(r["cash"] for r in self.rows)
        tgv, tgs = _bal(tg, True)
        tcv, tcs = _bal(tc, False)
        self.title.setText(
            f"{name} — {len(self.rows)} · الذهب {tgv} {kv.unit()} {tgs}"
            f" · النقد {tcv} ريال {tcs}")
        heads = ["الكود", "الاسم", "الهاتف", "مجموعة فرعية",
                 f"رصيد الذهب ({kv.unit()})", "حالته",
                 "الرصيد النقدي (ريال)", "حالته"]
        t = self.m_table
        t.setUpdatesEnabled(False)
        try:
            t.clear()
            t.setColumnCount(len(heads))
            t.setHorizontalHeaderLabels(heads)
            t.setRowCount(len(self.rows) + 1)
            for i, r in enumerate(self.rows):
                gv, gs = _bal(r["gold"], True)
                cv, cs = _bal(r["cash"], False)
                vals = [r["code"], r["name"], r["phone"], r["sub"],
                        gv, gs, cv, cs]
                for c, v in enumerate(vals):
                    it = QtWidgets.QTableWidgetItem(_nf.txt(v))
                    it.setTextAlignment(
                        (QtCore.Qt.AlignRight if c in (1, 3)
                         else QtCore.Qt.AlignCenter) | QtCore.Qt.AlignVCenter)
                    if c in (5, 7) and v != "—":
                        it.setForeground(QtGui.QBrush(
                            _RED if v == "مدين" else _GREEN))
                    t.setItem(i, c, it)
            last = len(self.rows)
            tot = ["", "الإجمالي (صافي المجموعة)", "", "", tgv, tgs, tcv,
                   tcs]
            bold = QtGui.QFont(t.font())
            bold.setBold(True)
            for c, v in enumerate(tot):
                it = QtWidgets.QTableWidgetItem(v)
                it.setTextAlignment(QtCore.Qt.AlignCenter)
                it.setFont(bold)
                try:
                    from ui.widgets.table_tools import TOTAL_ROLE
                    it.setData(TOTAL_ROLE, True)
                except Exception:
                    pass
                t.setItem(last, c, it)
        finally:
            t.setUpdatesEnabled(True)
        try:
            from ui.widgets.table_fit import fit_columns
            fit_columns(t, [8, 20, 10, 12, 11, 7, 11, 7])
        except Exception:
            pass
        self._apply_search(groups=False)

    # ══ البحث ══
    def _apply_search(self, *_a, groups=True):
        from ui.widgets.common import _norm
        q = _norm(self.search.text()).strip()
        if groups:
            # مجموعةٌ تُطابق باسمها أو بأحد عملائها
            hit_ids = set()
            if q:
                try:
                    with db(readonly=True) as conn:
                        for g in self.groups:
                            if q in _norm(g["name"]) or q in g["code"]:
                                hit_ids.add(g["id"])
                                continue
                            if any(q in _norm(m["name"]) or q in m["code"]
                                   for m in pg.members(conn, g["id"],
                                                       None, self._kind())):
                                hit_ids.add(g["id"])
                        if any(q in _norm(m["name"]) or q in m["code"]
                               for m in pg.members(conn, None, None,
                                                   self._kind())):
                            hit_ids.add(NO_GROUP)
                except Exception:
                    pass
            t = self.g_table
            first = None
            for i in range(t.rowCount()):
                gid = t.item(i, 0).data(QtCore.Qt.UserRole)
                hide = bool(q) and gid not in hit_ids
                t.setRowHidden(i, hide)
                if not hide and first is None:
                    first = i
            if q and first is not None and t.isRowHidden(t.currentRow()):
                t.selectRow(first)
        t = self.m_table
        # البحث باسم المجموعة يُبقي عملاءها كلهم ظاهرين
        g = next((x for x in self.groups if x["id"] == self._gid()), None)
        whole = bool(g and q and q in _norm(g["name"]))
        for i in range(len(self.rows)):
            r = self.rows[i]
            hide = (bool(q) and not whole and q not in _norm(r["name"])
                    and q not in r["code"] and q not in (r["phone"] or ""))
            t.setRowHidden(i, hide)

    # ══ المجموعات ══
    def new_group(self):
        """الاسم ثم عملاؤها — من أي مجموعةٍ كانوا فيها — في خطوةٍ واحدة."""
        try:
            with db(readonly=True) as conn:
                cand = pg.everyone(conn, self._kind())
            dlg = AddMembersDialog(self, cand, "", ask_name=True)
            if dlg.exec_() != QtWidgets.QDialog.Accepted:
                return
            name = dlg.name.text().strip()
            if not name:
                raise ValueError("أدخل اسم المجموعة — مثل «عملاء الرميزان»")
            ids = dlg.chosen()
            with db() as conn:
                gid = pg.create_group(conn, name, self.user["username"],
                                      self._kind())
                n = (pg.assign(conn, ids, gid, self.user["username"],
                               self._kind()) if ids else 0)
            if n:
                info(self, f"أُنشئت «{name}» ونُقل إليها {n} — خرجوا من"
                           " مجموعاتهم السابقة، والأرصدة والكشوف كما هي.")
            self.refresh(keep=gid)
        except Exception as e:
            err(self, e)

    def _real_gid(self):
        gid = self._gid()
        if gid in (None, NO_GROUP):
            raise ValueError("اختر مجموعةً من القائمة أولاً")
        return gid

    def rename_group(self):
        try:
            gid = self._real_gid()
            g = next(x for x in self.groups if x["id"] == gid)
            name, ok = QtWidgets.QInputDialog.getText(
                self, "تسمية المجموعة", "الاسم الجديد:", text=g["name"])
            if not ok or not name.strip():
                return
            with db() as conn:
                pg.rename_group(conn, gid, name, self.user["username"],
                                self._kind())
            self.refresh(keep=gid)
        except Exception as e:
            err(self, e)

    def delete_group(self):
        try:
            gid = self._real_gid()
            g = next(x for x in self.groups if x["id"] == gid)
            if not ask(self, f"حذف المجموعة «{g['name']}»؟"):
                return
            with db() as conn:
                pg.delete_group(conn, gid, self.user["username"],
                                self._kind())
            self.refresh(keep=NO_GROUP)
        except Exception as e:
            err(self, e)

    # ══ الأعضاء ══
    def add_members(self):
        try:
            gid = self._real_gid()
            g = next(x for x in self.groups if x["id"] == gid)
            # من أي مجموعةٍ كانت (أو بلا مجموعة) — عدا من هم فيها أصلاً
            with db(readonly=True) as conn:
                inside = pg.in_group(conn, gid, self._kind())
                uniq = [m for m in pg.everyone(conn, self._kind())
                        if m["entity_id"] not in inside]
            if not uniq:
                raise ValueError("لا جهات أخرى تُضاف — كلها في هذه المجموعة")
            dlg = AddMembersDialog(self, uniq, g["name"])
            if dlg.exec_() != QtWidgets.QDialog.Accepted:
                return
            ids = dlg.chosen()
            if not ids:
                return
            with db() as conn:
                n = pg.assign(conn, ids, gid, self.user["username"],
                              self._kind())
            info(self, f"نُقل {n} إلى «{g['name']}» وخرجوا من مجموعاتهم"
                       " السابقة — الأرصدة والكشوف كما هي.")
            self.refresh(keep=gid)
        except Exception as e:
            err(self, e)

    def _selected(self):
        rows = sorted({i.row() for i in self.m_table.selectedIndexes()
                       if i.row() < len(self.rows)})
        return [self.rows[r] for r in rows]

    def remove_members(self):
        try:
            gid = self._real_gid()
            sel = self._selected()
            if not sel:
                raise ValueError("حدّد عميلاً أو أكثر من الجدول")
            if not ask(self, f"إخراج {len(sel)} من المجموعة؟\n(يبقى عميلاً"
                             " بحسابه ورصيده — يعود إلى «بلا مجموعة»)"):
                return
            with db() as conn:
                pg.assign(conn, [r["entity_id"] for r in sel], None,
                          self.user["username"], self._kind())
            self.refresh(keep=gid)
        except Exception as e:
            err(self, e)

    def open_ledger(self):
        try:
            sel = self._selected()
            if not sel:
                raise ValueError("حدّد عميلاً من الجدول")
            if callable(self.on_drill_account):
                self.on_drill_account(sel[0]["account_id"])
        except Exception as e:
            err(self, e)

    def visible_entities(self):
        return [r["entity_id"] for i, r in enumerate(self.rows)
                if not self.m_table.isRowHidden(i)]

    def print_group(self):
        try:
            gid = self._gid()
            from services import print_manager
            print_manager.preview_document(
                self, "party_group", 0 if gid in (None, NO_GROUP) else gid,
                kind=self._kind(), as_of=dstr(self.as_of),
                entity_ids=self.visible_entities())
        except Exception as e:
            err(self, e)

    def print_all(self):
        """كل المجموعات: لكلٍّ رصيده وحالته ثم عملاؤه بأرصدتهم."""
        try:
            from services import print_manager
            print_manager.preview_document(
                self, "party_groups_all", 0, kind=self._kind(),
                as_of=dstr(self.as_of))
        except Exception as e:
            err(self, e)
