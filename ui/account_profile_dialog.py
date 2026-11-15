# -*- coding: utf-8 -*-
"""المدير العام يجهّز الحساب قبل تسليمه (5.5 · دوال الخادم 3.2.0).

* **تعديل الحساب**: الاسم الظاهر · اسم المصنع/المحل · كلمة مرور جديدة.
* **ملف الحساب**: ترتيب القائمة (سحب وإفلات — والشاشة تُسحب فوق شاشةٍ
  فتصير داخلها) وأسماء الشاشات (نقرٌ مزدوج) ومجموعاتٌ جديدة — ثم هوية
  المنشأة وشعارها. يُحفظ على الخادم، ويُطبَّق عند دخول الحساب التالي،
  ويبقى للمستخدم ما يعدّله بعدها حتى يحفظ المدير ملفاً جديداً.
"""
import time

from PyQt5 import QtCore, QtGui, QtWidgets

from ui import kit

from services import account_profile, plan
from ui.widgets import nav_tools
from ui.widgets.common import ask, err, info

KEY_ROLE = QtCore.Qt.UserRole + 1
GROUP = "::group::"


class EditAccountDialog(QtWidgets.QDialog):
    """تعديل حسابٍ قائم — الفارغ يبقى كما هو."""

    def __init__(self, parent, user_row):
        super().__init__(parent)
        self.u = user_row
        self.setWindowTitle(f"تعديل الحساب «{user_row.get('username')}»")
        self.setMinimumWidth(460)
        self.full_name = kit.LineEdit()
        self.full_name.setText(user_row.get("full_name") or "")
        self.factory = kit.LineEdit()
        self.factory.setPlaceholderText("اتركه فارغاً ليبقى كما هو")
        self.pw1 = kit.LineEdit()
        self.pw1.setEchoMode(QtWidgets.QLineEdit.Password)
        self.pw1.setPlaceholderText("اتركها فارغة لتبقى كما هي")
        self.pw2 = kit.LineEdit()
        self.pw2.setEchoMode(QtWidgets.QLineEdit.Password)
        form = QtWidgets.QFormLayout(self)
        form.addRow("اسم المستخدم:", QtWidgets.QLabel(
            user_row.get("username") or ""))
        form.addRow("الاسم الظاهر:", self.full_name)
        if user_row.get("role") != "super_admin":
            form.addRow("اسم المصنع / المحل:", self.factory)
        form.addRow("كلمة مرور جديدة:", self.pw1)
        form.addRow("تأكيدها:", self.pw2)
        note = QtWidgets.QLabel(
            "كلمة المرور الجديدة تُجزَّأ قبل إرسالها ولا تُحفظ نصاً، ويُفتح "
            "قفل الحساب إن كان مقفلاً بمحاولاتٍ خاطئة.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        form.addRow(note)
        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save
            | QtWidgets.QDialogButtonBox.Cancel)
        btns.button(QtWidgets.QDialogButtonBox.Save).setText("حفظ")
        btns.button(QtWidgets.QDialogButtonBox.Cancel).setText("إلغاء")
        btns.accepted.connect(self.save)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def save(self):
        from services import cloud_auth
        try:
            if self.pw1.text() != self.pw2.text():
                raise ValueError("كلمتا المرور غير متطابقتين")
            name = self.full_name.text().strip()
            if name == (self.u.get("full_name") or ""):
                name = ""
            cloud_auth.update_account(self.u.get("username"), name,
                                      self.pw1.text(),
                                      self.factory.text().strip())
            self.accept()
        except Exception as e:                       # noqa: BLE001
            err(self, e)


class NavEditor(QtWidgets.QWidget):
    """شجرة القائمة كما ستظهر للحساب — سحبٌ وإفلات وإعادة تسمية."""

    def __init__(self, screens=None):
        super().__init__()
        self.screens = set(screens or plan.ALL_SCREENS)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.tree.setDefaultDropAction(QtCore.Qt.MoveAction)
        self.tree.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection)
        self.tree.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed)
        self.tree.setIndentation(18)
        # 5.6.0: أوامر صريحة للترتيب — السحب وحده كان يلتبس (فوق البند =
        # داخله · بين بندين = بجواره) فلا تنتقل الشاشة حيث أُريد
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context)
        b_up = kit.PushButton("▲ أعلى")
        b_up.clicked.connect(lambda: self._do(nav_tools.move, -1))
        b_down = kit.PushButton("▼ أسفل")
        b_down.clicked.connect(lambda: self._do(nav_tools.move, 1))
        b_in = kit.PushButton("⇲ داخل التي فوقها")
        b_in.setToolTip("تصير الشاشة المحددة شاشةً داخل الشاشة (أو المجموعة)"
                        " التي فوقها مباشرةً")
        b_in.clicked.connect(lambda: self._do(nav_tools.indent))
        b_out = kit.PushButton("⇱ إخراجها مستوى")
        b_out.setToolTip("تخرج الشاشة من الشاشة أو المجموعة التي هي فيها")
        b_out.clicked.connect(lambda: self._do(nav_tools.outdent))
        b_group = kit.PushButton("+ مجموعة جديدة")
        b_group.clicked.connect(self.add_group)
        b_ren = kit.PushButton("✎ إعادة تسمية")
        b_ren.clicked.connect(self.rename)
        b_orig = kit.PushButton("⟲ الاسم الأصلي")
        b_orig.setToolTip("يعيد للشاشة المحددة اسمها الأصلي")
        b_orig.clicked.connect(self.original_name)
        b_del = kit.PushButton("فكّ المجموعة")
        b_del.setToolTip("يحذف المجموعة المحددة وتبقى شاشاتها في مكانها")
        b_del.clicked.connect(self.ungroup)
        b_def = kit.PushButton("↺ الترتيب الافتراضي")
        b_def.setObjectName("ghost")
        b_def.clicked.connect(self.load_default)
        side = QtWidgets.QVBoxLayout()
        for b in (b_up, b_down, b_in, b_out):
            side.addWidget(b)
        side.addSpacing(10)
        for b in (b_group, b_ren, b_orig, b_del):
            side.addWidget(b)
        side.addStretch(1)
        side.addWidget(b_def)
        hint = QtWidgets.QLabel(
            "حدّد الشاشة ثم: ▲▼ لترتيبها · «داخل التي فوقها» لتصير شاشةً "
            "داخل الشاشة التي فوقها · «إخراجها» لتعود مستوىً · «إعادة تسمية»"
            " لاسمها في القائمة (أو النقر الأيمن عليها). ويبقى السحب "
            "والإفلات متاحاً. والشاشة الرمادية خارج اشتراك الحساب فلا تظهر "
            "له.")
        hint.setObjectName("cardSub")
        hint.setWordWrap(True)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.tree, 1)
        row.addLayout(side)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(hint)
        lay.addLayout(row, 1)

    # ── البناء ──
    def _item(self, key, text, parent=None):
        it = QtWidgets.QTreeWidgetItem([text])
        it.setData(0, KEY_ROLE, key)
        it.setFlags(it.flags() | QtCore.Qt.ItemIsEditable
                    | QtCore.Qt.ItemIsDragEnabled
                    | QtCore.Qt.ItemIsDropEnabled)
        if key.startswith(GROUP):
            f = it.font(0)
            f.setBold(True)
            it.setFont(0, f)
        elif key not in self.screens:
            it.setForeground(0, QtGui.QBrush(QtGui.QColor("#9a9a9a")))
        self._hint(it)
        if parent is None:
            self.tree.addTopLevelItem(it)
        else:
            parent.addChild(it)
        return it

    def load(self, nodes):
        self.tree.clear()
        nodes = account_profile.clean_nodes(nodes or [])
        if not nodes:
            nodes = account_profile.default_nodes()

        def build(items, parent):
            for n in items:
                it = self._item(n["key"], n["text"], parent)
                build(n.get("children") or [], it)
                it.setExpanded(True)
        build(nodes, None)
        # شاشةٌ ليست في الملف (أُضيفت بعد حفظه) تُلحق في آخره
        have = {k for k in self._keys()}
        for name in plan.ALL_SCREENS:
            if name not in have:
                self._item(name, name)

    def load_default(self):
        if self.tree.topLevelItemCount() and not ask(
                self, "إعادة القائمة لترتيبها وأسمائها الافتراضية؟"):
            return
        self.load(account_profile.default_nodes())

    def _keys(self):
        out = []

        def walk(it):
            out.append(it.data(0, KEY_ROLE) or "")
            for i in range(it.childCount()):
                walk(it.child(i))
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))
        return out

    def nodes(self):
        def node(it):
            key = it.data(0, KEY_ROLE) or ""
            return {"idx": -1 if key.startswith(GROUP) else 1, "key": key,
                    "text": it.text(0).strip() or key.replace(GROUP, ""),
                    "expanded": False,
                    "children": [node(it.child(i))
                                 for i in range(it.childCount())]}
        return account_profile.clean_nodes(
            [node(self.tree.topLevelItem(i))
             for i in range(self.tree.topLevelItemCount())])

    # ── الأوامر ──
    def add_group(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "مجموعة جديدة",
                                                  "اسم المجموعة:")
        if not ok or not name.strip():
            return
        it = self._item(f"{GROUP}{name.strip()}·{int(time.time() * 1000)}",
                        name.strip())
        self.tree.setCurrentItem(it)
        info(self, "اسحب الشاشات وأفلتها فوق المجموعة لتدخلها — والمجموعة "
                   "الفارغة لا تُحفظ.")

    def _do(self, fn, *args):
        it = self.tree.currentItem()
        if it is None:
            err(self, "حدّد شاشةً في القائمة أولاً")
            return False
        ok = fn(self.tree, it, *args)
        if not ok and fn is nav_tools.indent:
            info(self, "لا شاشة فوقها في المستوى نفسه — رتّبها أولاً تحت "
                       "الشاشة التي تريدها ثم «داخل التي فوقها».")
        return ok

    def _context(self, pos):
        it = self.tree.itemAt(pos)
        if it is None:
            return
        self.tree.setCurrentItem(it)
        grp = (it.data(0, KEY_ROLE) or "").startswith(GROUP)
        nav_tools.menu(self, self.tree, it, [
            ("▲ أعلى", lambda: self._do(nav_tools.move, -1)),
            ("▼ أسفل", lambda: self._do(nav_tools.move, 1)),
            ("⇲ داخل الشاشة التي فوقها", lambda: self._do(nav_tools.indent)),
            ("⇱ إخراجها مستوى", lambda: self._do(nav_tools.outdent),
             it.parent() is not None),
            None,
            ("✎ إعادة تسمية…", self.rename),
            ("⟲ الاسم الأصلي", self.original_name, not grp),
            ("فكّ المجموعة", self.ungroup, grp)])

    def rename(self):
        it = self.tree.currentItem()
        if it is None:
            err(self, "حدّد شاشةً في القائمة أولاً")
            return
        key = it.data(0, KEY_ROLE) or ""
        orig = "" if key.startswith(GROUP) else key
        if nav_tools.rename(self, it, orig) and orig:
            self._hint(it)

    def original_name(self):
        it = self.tree.currentItem()
        if it is None:
            return
        key = it.data(0, KEY_ROLE) or ""
        if not key.startswith(GROUP):
            it.setText(0, key)
            self._hint(it)

    def _hint(self, it):
        """تلميح الشاشة: خارج الاشتراك أولاً، ثم اسمها الأصلي إن غُيّر."""
        key = it.data(0, KEY_ROLE) or ""
        if key.startswith(GROUP):
            return
        if key not in self.screens:
            tip = "خارج اشتراك الحساب — لا تظهر له"
            if it.text(0) != key:
                tip += f" (اسمها الأصلي: {key})"
        elif it.text(0) != key:
            tip = f"اسمها الأصلي: {key}"
        else:
            tip = ""
        it.setToolTip(0, tip)

    def ungroup(self):
        it = self.tree.currentItem()
        if it is None or not (it.data(0, KEY_ROLE) or "").startswith(GROUP):
            err(self, "حدّد مجموعةً أولاً")
            return
        parent = it.parent()
        kids = [it.takeChild(0) for _ in range(it.childCount())]
        if parent is None:
            pos = self.tree.indexOfTopLevelItem(it)
            self.tree.takeTopLevelItem(pos)
            for i, k in enumerate(kids):
                self.tree.insertTopLevelItem(pos + i, k)
        else:
            pos = parent.indexOfChild(it)
            parent.takeChild(pos)
            for i, k in enumerate(kids):
                parent.insertChild(pos + i, k)


class AccountProfileDialog(QtWidgets.QDialog):
    """ملف الحساب: القائمة · الهوية والشعار — يُحفظ على الخادم."""

    @classmethod
    def create(cls, parent, tenant_id, name, screens=None, user=None):
        """يقرأ ملف الحساب من الخادم ثم يبني النافذة — أو None برسالة."""
        from services import cloud_auth
        try:
            profile, ver = cloud_auth.get_profile(tenant_id)
        except Exception as e:                       # noqa: BLE001
            err(parent, e)
            return None
        return cls(parent, tenant_id, name, screens, user, profile, ver)

    def __init__(self, parent, tenant_id, name, screens=None, user=None,
                 profile=None, ver=0):
        super().__init__(parent)
        self.tenant_id = tenant_id
        self.user = user or {}
        self.setWindowTitle(f"تجهيز الحساب «{name}» — القائمة والهوية")
        self.resize(820, 680)
        self.profile, self.ver = dict(profile or {}), int(ver or 0)
        self.identity = dict(self.profile.get("identity") or {})
        self.nav = NavEditor(screens)
        self.nav.load(self.profile.get("nav"))
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self.nav, "ترتيب القائمة وأسماء الشاشات")
        tabs.addTab(self._identity_tab(), "هوية المنشأة والشعار")
        self.state = QtWidgets.QLabel(
            f"إصدار الملف على الخادم: {self.ver}" if self.ver else
            "لم يُحفظ لهذا الحساب ملفٌ بعد")
        self.state.setObjectName("cardSub")
        b_save = kit.PushButton("✔ حفظ في الحساب")
        b_save.setObjectName("primary")
        b_save.clicked.connect(self.save)
        b_close = kit.PushButton("إغلاق")
        b_close.clicked.connect(self.reject)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.state, 1)
        row.addWidget(b_save)
        row.addWidget(b_close)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(tabs, 1)
        lay.addLayout(row)

    def _identity_tab(self):
        w = QtWidgets.QWidget()
        self.id_lbl = QtWidgets.QLabel()
        self.id_lbl.setWordWrap(True)
        self.logo_lbl = QtWidgets.QLabel()
        self.logo_lbl.setAlignment(QtCore.Qt.AlignCenter)
        self.logo_lbl.setMinimumHeight(140)
        b_edit = kit.PushButton("✎ تعديل الهوية والشعار…")
        b_edit.clicked.connect(self.edit_identity)
        b_clear = kit.PushButton("بلا هوية من الإدارة")
        b_clear.setObjectName("ghost")
        b_clear.setToolTip("لا تُرسل هوية — يبقى للحساب ما ينشئه بنفسه")
        b_clear.clicked.connect(self.clear_identity)
        note = QtWidgets.QLabel(
            "الهوية تُطبَّق على جهاز الحساب عند دخوله التالي: الاسم والعنوان "
            "والسجل والرقم الضريبي والشعار والختم في كل الأوراق. ويستطيع "
            "صاحب الحساب تعديلها بعد ذلك — وحفظُك ملفاً جديداً يُعيد تطبيقها.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(b_edit)
        row.addWidget(b_clear)
        row.addStretch(1)
        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(note)
        lay.addWidget(self.logo_lbl)
        lay.addWidget(self.id_lbl)
        lay.addLayout(row)
        lay.addStretch(1)
        self._show_identity()
        return w

    def _show_identity(self):
        d = self.identity
        if not d.get("name"):
            self.id_lbl.setText("لا هوية من الإدارة — يُنشئ الحساب هويته "
                                "بنفسه.")
            self.logo_lbl.clear()
            return
        rows = [("الاسم", d.get("name")), ("السجل التجاري", d.get("cr")),
                ("الرقم الضريبي", d.get("vat")),
                ("العنوان", d.get("address")), ("الجوال", d.get("phone"))]
        self.id_lbl.setText("\n".join(f"{k}: {v}" for k, v in rows if v))
        pix = QtGui.QPixmap()
        if d.get("logo_b64"):
            import base64
            try:
                pix.loadFromData(base64.b64decode(d["logo_b64"]))
            except Exception:
                pix = QtGui.QPixmap()
        if pix.isNull():
            self.logo_lbl.setText("بلا شعار")
        else:
            self.logo_lbl.setPixmap(pix.scaledToHeight(
                130, QtCore.Qt.SmoothTransformation))

    def edit_identity(self):
        from ui.factory_identity_dialog import FactoryIdentityDialog

        def took(d):
            self.identity = dict(d)
        dlg = FactoryIdentityDialog(self, self.user, initial=self.identity,
                                    on_apply=took)
        dlg.exec_()
        self._show_identity()

    def clear_identity(self):
        self.identity = {}
        self._show_identity()

    def save(self):
        from services import cloud_auth
        try:
            nodes = self.nav.nodes()
            if not nodes:
                raise ValueError("القائمة فارغة")
            v = cloud_auth.set_profile(self.tenant_id, nodes,
                                       self.identity or None)
            self.ver = v
            info(self, f"حُفظ ملف الحساب (الإصدار {v}).\n\nيُطبَّق على جهازه "
                       "عند دخوله التالي — وما يعدّله بعدها يبقى له حتى "
                       "تحفظ ملفاً جديداً.")
            self.accept()
        except Exception as e:                       # noqa: BLE001
            err(self, e)
