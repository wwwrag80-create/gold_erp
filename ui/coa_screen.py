# -*- coding: utf-8 -*-
"""دليل الحسابات (Chart of Accounts) — شجرة الحسابات الديناميكية.

عرض هرمي بـQTreeView مع قائمة سياقية بزر الماوس الأيمن:
إضافة حساب فرعي (بوراثة محاسبية آلية)، تعديل الاسم، تجميد/تنشيط،
كشف حساب، وحذف محمي.

دلالات بصرية:
* **خط عريض** = حساب تجميعي لا يقبل الحركات المباشرة.
* رمادي فاتح = حساب مجمَّد (غير نشط) لا يظهر في قوائم الإدخال.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from models import coa
from ui.widgets.common import ask, big_label, err, info, title_label

HEADERS = ["الحساب", "الكود", "النوع", "الطبيعة", "المستوى", "نوع القياس",
           "يقبل الحركة", "الحالة", "الوسم النظامي"]


class AddSubDialog(QtWidgets.QDialog):
    """إضافة حساب فرعي — لا يُطلب سوى الاسم، والباقي يُورَث من الأب."""

    def __init__(self, parent, parent_acc):
        super().__init__(parent)
        self.setWindowTitle("إضافة حساب فرعي")
        self.setMinimumWidth(460)
        self.name = QtWidgets.QLineEdit()
        self.name.setPlaceholderText("اسم الحساب الجديد")
        self.measure = QtWidgets.QComboBox()
        for key, label in coa.MEASURE_LABELS.items():
            self.measure.addItem(label, key)
        i = self.measure.findData(parent_acc["balance_type"])
        if i >= 0:
            self.measure.setCurrentIndex(i)

        form = QtWidgets.QFormLayout(self)
        form.addRow(big_label(f"تحت: {parent_acc['code']} — {parent_acc['name']}"))
        inherit = QtWidgets.QLabel(
            f"يرث آلياً — النوع: {coa.TYPE_LABELS.get(parent_acc['type'], parent_acc['type'])}"
            f"   |   الطبيعة: {coa.NATURE_LABELS.get(parent_acc['nature'], parent_acc['nature'])}"
            f"   |   المستوى: {(parent_acc['account_level'] or 1) + 1}")
        inherit.setObjectName("cardSub")
        form.addRow(inherit)
        form.addRow("اسم الحساب:", self.name)
        form.addRow("نوع القياس:", self.measure)
        note = QtWidgets.QLabel(
            "الكود يُولَّد آلياً من كود الأب، ولا يُطلب إدخاله. عند إضافة "
            "أول فرع يتحوّل الحساب الأب إلى حساب تجميعي لا يقبل الحركات "
            "المباشرة (ما لم تكن له حركة تاريخية).")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        form.addRow(note)
        box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        form.addRow(box)


class CoaScreen(QtWidgets.QWidget):
    def __init__(self, user, on_open_ledger=None):
        super().__init__()
        self.user = user
        self.on_open_ledger = on_open_ledger

        self.tree = QtWidgets.QTreeView()
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.menu)
        self.tree.setAlternatingRowColors(True)
        self.tree.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.model = QtGui.QStandardItemModel()
        self.model.setHorizontalHeaderLabels(HEADERS)
        self.tree.setModel(self.model)
        self.tree.doubleClicked.connect(self.open_ledger)

        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("بحث بالاسم أو الكود…")
        self.search.textChanged.connect(self.apply_filter)
        self.show_frozen = QtWidgets.QCheckBox("إظهار الحسابات المجمَّدة")
        self.show_frozen.setChecked(True)
        self.show_frozen.stateChanged.connect(self.refresh)
        btn_expand = QtWidgets.QPushButton("توسيع الكل")
        btn_expand.setObjectName("ghost")
        btn_expand.clicked.connect(self.tree.expandAll)
        btn_collapse = QtWidgets.QPushButton("طي الكل")
        btn_collapse.setObjectName("ghost")
        btn_collapse.clicked.connect(self.tree.collapseAll)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.search, 2)
        top.addWidget(self.show_frozen)
        top.addWidget(btn_expand)
        top.addWidget(btn_collapse)

        self.summary = big_label()
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("دليل الحسابات — شجرة الحسابات الديناميكية"))
        lay.addLayout(top)
        lay.addWidget(self.tree, 1)
        lay.addWidget(self.summary)
        note = QtWidgets.QLabel(
            "انقر بزر الماوس الأيمن على أي حساب: إضافة حساب فرعي (يرث نوع "
            "الأب وطبيعته آلياً) · تعديل الاسم · تجميد/تنشيط · كشف حساب · "
            "حذف. الخط العريض = حساب تجميعي، والرمادي = حساب مجمَّد لا "
            "يظهر في قوائم الإدخال.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)

    # ── بناء الشجرة ──
    def refresh(self, force=False):
        """يعيد بناء الشجرة — **فقط إن تغيّرت**.

        بناء الشجرة يُنشئ عنصراً لكل خلية (400 حساب × 9 أعمدة =
        3,600 عنصر). إعادته عند كل فتح شاشة بلا تغيّر إهدار خالص،
        فنقارن بصمة الشجرة أولاً.
        """
        with db() as conn:
            rows = coa.tree_rows(conn, include_inactive=self.show_frozen.isChecked())
            sig = conn.execute(
                "SELECT COUNT(*) n, COALESCE(MAX(id),0) m,"
                " COALESCE(SUM(is_active),0) a FROM accounts").fetchone()
            fingerprint = (sig["n"], sig["m"], sig["a"],
                           self.show_frozen.isChecked())
            counts = conn.execute(
                "SELECT COUNT(*) t, SUM(is_postable=1 AND is_active=1) p,"
                " SUM(is_active=0) f FROM accounts").fetchone()
        if not force and fingerprint == getattr(self, "_fp", None):
            return                    # لا تغيير — الشجرة المعروضة صالحة
        self._fp = fingerprint
        # ══ بناء الشجرة دفعةً واحدة ══
        # **الخلل السابق**: `resizeColumnToContents` لكل عمود يقيس كل
        # خلية في الشجرة — مع 400 حساب × 8 أعمدة يعني آلاف القياسات
        # فتتجمّد الشاشة عند كل فتح.
        self.tree.setUpdatesEnabled(False)
        try:
            self.model.removeRows(0, self.model.rowCount())
            self.model.setHorizontalHeaderLabels(HEADERS)
            items, pending = {}, []
            for r in rows:
                items[r["id"]] = self._row_items(r)
                pending.append(r)
            root = self.model.invisibleRootItem()
            for r in pending:
                cells = items[r["id"]]
                parent = items.get(r["parent_id"])
                (parent[0] if parent else root).appendRow(cells)
            self.tree.expandToDepth(1)
        finally:
            try:
                self.tree.setUpdatesEnabled(True)
            except Exception:
                pass
        # عرض ثابت للأعمدة: أسرع بكثير من قياس المحتوى، والعمود الأول
        # (اسم الحساب) يمتصّ الفائض.
        try:
            hh = self.tree.header()
            hh.setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
            widths = (280, 70, 70, 60, 60, 80, 70, 70)
            for c in range(len(HEADERS)):
                self.tree.setColumnWidth(
                    c, widths[c] if c < len(widths) else 80)
            hh.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        except Exception:
            pass
        self.summary.setText(
            f"إجمالي الحسابات: {counts['t']}   |   حسابات تقبل الحركة "
            f"ونشطة: {counts['p'] or 0}   |   مجمَّدة: {counts['f'] or 0}")

    def _shared_styles(self):
        """خط وفرشاة يُعادان استخدامهما لكل الخلايا.

        **الخلل السابق**: `it.font()` كان يُنشئ كائن خط جديد لكل خلية
        — مع 410 حساب × 9 أعمدة يعني 3,690 كائناً، وكل واحد يُنسخ
        ويُضبط. إعادة الاستخدام تُلغي ذلك تماماً.
        """
        st = getattr(self, "_styles", None)
        if st is None:
            bold = QtGui.QFont()
            bold.setBold(True)
            st = {"bold": bold,
                  "gray": QtGui.QBrush(QtGui.QColor("#9aa0a6"))}
            self._styles = st
        return st

    def _row_items(self, r):
        vals = [f"{r['name']}", r["code"],
                coa.TYPE_LABELS.get(r["type"], r["type"]),
                coa.NATURE_LABELS.get(r["nature"], r["nature"]),
                str(r["account_level"] or 1),
                coa.MEASURE_ENUM.get(r["balance_type"], "BOTH"),
                "نعم" if r["is_postable"] else "— تجميعي —",
                "نشط" if r["is_active"] else "مجمَّد",
                r["system_tag"] or ""]
        st = self._shared_styles()
        bold = not r["is_postable"]
        frozen = not r["is_active"]
        cells = []
        for v in vals:
            it = QtGui.QStandardItem(str(v))
            it.setEditable(False)
            if bold:                            # حساب تجميعي → عريض
                it.setFont(st["bold"])
            if frozen:                          # مجمَّد → رمادي فاتح
                it.setForeground(st["gray"])
            cells.append(it)
        cells[0].setData(r["id"], QtCore.Qt.UserRole)
        return cells

    def apply_filter(self, text):
        text = (text or "").strip()

        def walk(item):
            hit = False
            for i in range(item.rowCount()):
                child = item.child(i, 0)
                sub = walk(child)
                code = item.child(i, 1).text()
                mine = (not text) or (text in child.text()) or (text in code)
                idx = self.model.indexFromItem(child)
                self.tree.setRowHidden(i, self.model.indexFromItem(item),
                                       not (mine or sub))
                if mine or sub:
                    hit = True
                    if text:
                        self.tree.expand(idx.parent())
            return hit

        walk(self.model.invisibleRootItem())

    # ── القائمة السياقية ──
    def _selected_id(self):
        idx = self.tree.currentIndex()
        if not idx.isValid():
            return None
        item = self.model.itemFromIndex(idx.siblingAtColumn(0))
        return item.data(QtCore.Qt.UserRole) if item else None

    def menu(self, pos):
        idx = self.tree.indexAt(pos)
        if idx.isValid():
            self.tree.setCurrentIndex(idx)
        aid = self._selected_id()
        if aid is None:
            return
        with db() as conn:
            acc = coa.get_account(conn, aid)
        if not acc:
            return
        m = QtWidgets.QMenu(self)
        m.addAction("➕ إضافة حساب فرعي", lambda: self.add_sub(aid))
        m.addAction("✎ تعديل اسم الحساب", lambda: self.rename(aid))
        m.addSeparator()
        m.addAction("📄 كشف حساب", lambda: self.open_ledger())
        m.addSeparator()
        m.addAction("❄ تجميد الحساب" if acc["is_active"] else "✔ تنشيط الحساب",
                    lambda: self.toggle_active(aid, not acc["is_active"]))
        m.addAction("🏷 تعديل الوسم النظامي", lambda: self.edit_tag(aid))
        m.addSeparator()
        m.addAction("🗑 حذف الحساب", lambda: self.delete(aid))
        m.addAction("🗑 حذف الحساب وكل فروعه",
                    lambda: self.delete_tree(aid))
        m.addAction("🔥 حذف نهائي بالحركات (يؤثر على الميزانية)",
                    lambda: self.purge_tree(aid))
        m.exec_(self.tree.viewport().mapToGlobal(pos))

    def add_sub(self, parent_id):
        try:
            with db() as conn:
                parent = coa.get_account(conn, parent_id)
            dlg = AddSubDialog(self, parent)
            if dlg.exec_() != QtWidgets.QDialog.Accepted:
                return
            with db() as conn:
                res = coa.add_sub_account(conn, parent_id, dlg.name.text(),
                                          self.user["username"],
                                          dlg.measure.currentData())
            info(self, f"تم إنشاء الحساب {res['code']} — {res['name']}\n"
                       f"ورث النوع «{coa.TYPE_LABELS.get(res['type'])}» "
                       f"والطبيعة «{coa.NATURE_LABELS.get(res['nature'])}» "
                       f"من الحساب الأب (المستوى {res['level']}).\n"
                       "وسيظهر فوراً في قوائم الإدخال بكل الشاشات.")
            self.refresh(force=True)
        except Exception as e:
            err(self, e)

    def rename(self, aid):
        try:
            with db() as conn:
                acc = coa.get_account(conn, aid)
            name, ok = QtWidgets.QInputDialog.getText(
                self, "تعديل اسم الحساب", "الاسم الجديد:",
                QtWidgets.QLineEdit.Normal, acc["name"])
            if not ok:
                return
            with db() as conn:
                coa.rename_account(conn, aid, name, self.user["username"])
            self.refresh(force=True)
        except Exception as e:
            err(self, e)

    def edit_tag(self, aid):
        try:
            with db() as conn:
                acc = coa.get_account(conn, aid)
            tag, ok = QtWidgets.QInputDialog.getText(
                self, "الوسم النظامي",
                "وسم يربط العمليات الآلية بهذا الحساب (مثل VAT_PAYABLE).\n"
                "اتركه فارغاً لإزالة الوسم:",
                QtWidgets.QLineEdit.Normal, acc["system_tag"] or "")
            if not ok:
                return
            with db() as conn:
                coa.set_tag(conn, aid, tag, self.user["username"])
            self.refresh(force=True)
        except Exception as e:
            err(self, e)

    def toggle_active(self, aid, active):
        try:
            if not active and not ask(
                    self, "تجميد الحساب يخفيه من كل قوائم الإدخال ويمنع "
                          "ترحيل أي حركة جديدة عليه، مع بقاء حركاته "
                          "التاريخية وأرصدته كما هي. متابعة؟"):
                return
            with db() as conn:
                coa.set_active(conn, aid, active, self.user["username"])
            self.refresh(force=True)
        except Exception as e:
            err(self, e)

    def purge_tree(self, aid):
        """حذف نهائي: الحساب وفروعه وكل قيوده — يؤثر على الميزانية."""
        try:
            with db() as conn:
                acc = conn.execute("SELECT name FROM accounts WHERE id=?",
                                   (aid,)).fetchone()
                n = conn.execute(
                    "WITH RECURSIVE t(id) AS ("
                    " SELECT id FROM accounts WHERE id=?"
                    " UNION ALL SELECT a.id FROM accounts a"
                    " JOIN t ON a.parent_id=t.id)"
                    " SELECT COUNT(DISTINCT l.entry_id) c"
                    " FROM journal_lines l JOIN t ON t.id=l.account_id",
                    (aid,)).fetchone()["c"]
            if not acc:
                raise ValueError("الحساب غير موجود")
            if not ask(self,
                       f"⚠ حذف نهائي\n\n"
                       f"الحساب: {acc['name']}\n"
                       f"القيود التي ستُحذف: {n}\n\n"
                       f"تُحذف القيود **كاملةً بكل أطرافها** فتبقى بقية "
                       f"القيود متوازنة، وتتحدّث الميزانية بنقصان ما "
                       f"حُذف.\n\nلا يمكن التراجع إطلاقاً. المتابعة؟"):
                return
            txt, ok = QtWidgets.QInputDialog.getText(
                self, "تأكيد الحذف النهائي",
                "اكتب العبارة التالية للتأكيد:\n\n    حذف نهائي\n")
            if not ok:
                return
            with db() as conn:
                r = coa.purge_account_tree(conn, aid,
                                           self.user["username"],
                                           confirm_text=str(txt))
            info(self, f"حُذفت شجرة «{r['root']}» نهائياً.\n"
                       f"حسابات: {r['accounts']}   ·   "
                       f"قيود: {r['entries']}   ·   "
                       f"مستندات: {r['docs']}")
            self.refresh(force=True)
        except Exception as e:
            err(self, e)

    def delete_tree(self, aid):
        """يحذف الحساب وكل فروعه — مع حماية ذوات الحركة."""
        try:
            with db() as conn:
                acc = conn.execute("SELECT name FROM accounts WHERE id=?",
                                   (aid,)).fetchone()
                n = conn.execute(
                    "WITH RECURSIVE t(id) AS ("
                    " SELECT id FROM accounts WHERE id=?"
                    " UNION ALL SELECT a.id FROM accounts a"
                    " JOIN t ON a.parent_id=t.id)"
                    " SELECT COUNT(*) c FROM t", (aid,)).fetchone()["c"]
            if not acc:
                raise ValueError("الحساب غير موجود")
            if not ask(self,
                       f"حذف «{acc['name']}» وكل فروعه؟\n\n"
                       f"عدد الحسابات في الشجرة: {n}\n\n"
                       f"الحسابات ذات الحركة المحاسبية لن تُحذف — "
                       f"تُجمَّد بدلاً من ذلك حفاظاً على الميزان."):
                return
            # المحاولة الأولى بلا إجبار: ترفض إن وُجدت حركة
            try:
                with db() as conn:
                    r = coa.delete_subtree(conn, aid,
                                           self.user["username"])
            except ValueError as e:
                if "لا يمكن الحذف" not in str(e):
                    raise
                if not ask(self, f"{e}\n\nهل تريد المتابعة مع تجميد "
                                 f"ذوات الحركة؟"):
                    return
                with db() as conn:
                    r = coa.delete_subtree(conn, aid,
                                           self.user["username"], force=True)
            info(self, f"شجرة «{r['root']}»:\n"
                       f"محذوف: {r['deleted']}   ·   "
                       f"مجمَّد (له حركة): {r['frozen']}")
            self.refresh(force=True)
        except Exception as e:
            err(self, e)

    def delete(self, aid):
        try:
            with db() as conn:
                acc = coa.get_account(conn, aid)
            if not ask(self, f"حذف الحساب «{acc['name']}» نهائياً؟"):
                return
            with db() as conn:
                coa.delete_account(conn, aid, self.user["username"])
            info(self, "تم حذف الحساب")
            self.refresh(force=True)
        except Exception as e:
            err(self, e)

    def open_ledger(self):
        aid = self._selected_id()
        if aid is None:
            return
        with db() as conn:
            acc = coa.get_account(conn, aid)
        if acc and self.on_open_ledger:
            self.on_open_ledger(acc["code"])
