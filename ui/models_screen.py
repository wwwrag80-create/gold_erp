# -*- coding: utf-8 -*-
"""شاشة دليل الموديلات.

شجرة كدليل الحسابات: كل موديل جذر يتفرّع منه فرعان —

    ◄ الموديل 55                    3 أطقم · 75.00 جم
        ├─ المبيعات                 1 طقم · 20.00 جم
        │    └─ A1 — أبو مالك
        └─ الموجود                  2 طقم · 55.00 جم
             └─ A2 · A3

**الطبيعة المحاسبية**: رقم الموديل تصنيف **وصفي** لا مالي — لا يُنشأ
له حساب ولا يدخل في أي قيد. لكنه يجيب سؤالاً إدارياً: أين ذهبت قطع
هذا التصميم وكم بقي منه.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from services import karat_view as kv
from models import models_catalog as mc
from ui.widgets.common import (ask, big_label, date_edit, dstr, err, info,
                               title_label)

HEADERS = ["الموديل / رقم التشغيل", "العدد", "الوزن المقيد",
           "الجهة / التاريخ"]


class ModelsScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self._fp = None

        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("ابحث برقم الموديل أو رقم التشغيل…")
        self.search.setMaximumWidth(280)
        self.search.textChanged.connect(self.apply_filter)

        # مرشّح العرض: يحدّد أي الفروع تُعرض
        self.view_mode = QtWidgets.QComboBox()
        self.view_mode.setMaximumWidth(210)
        for lbl, val in (("الكل", "all"),
                         ("المتاح للبيع", "in_stock"),
                         ("طرف المناديب", "sold")):
            self.view_mode.addItem(lbl, val)
        self.view_mode.currentIndexChanged.connect(
            lambda: self.refresh(force=True))

        # الفرز
        self.sort_mode = QtWidgets.QComboBox()
        self.sort_mode.setMaximumWidth(180)
        for lbl, val in (("أ ← ي", "az"), ("ي ← أ", "za"),
                         ("الأكثر عدداً", "most"),
                         ("الأقل عدداً", "least")):
            self.sort_mode.addItem(lbl, val)
        self.sort_mode.currentIndexChanged.connect(
            lambda: self.refresh(force=True))

        btn_refresh = QtWidgets.QPushButton("↻ تحديث")
        btn_refresh.clicked.connect(lambda: self.refresh(force=True))
        btn_expand = QtWidgets.QPushButton("توسيع الكل")
        btn_expand.clicked.connect(lambda: self.tree.expandAll())
        btn_collapse = QtWidgets.QPushButton("طيّ الكل")
        btn_collapse.clicked.connect(lambda: self.tree.collapseAll())
        btn_print = QtWidgets.QPushButton("🖨 طباعة الدليل")
        btn_print.clicked.connect(self.print_catalog)
        btn_photos = QtWidgets.QPushButton("🖼 طباعة الصور")
        btn_photos.setToolTip(
            "أربع صور في كل صفحة A4 — للموديلات التي بلغت حدّاً معيناً")
        btn_photos.clicked.connect(self.print_photos)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(QtWidgets.QLabel("عرض:"))
        head.addWidget(self.view_mode, 0)
        head.addWidget(QtWidgets.QLabel("فرز:"))
        head.addWidget(self.sort_mode, 0)
        head.addWidget(QtWidgets.QLabel("بحث:"))
        head.addWidget(self.search, 0)
        head.addWidget(btn_refresh)
        head.addWidget(btn_expand)
        head.addWidget(btn_collapse)
        head.addWidget(btn_print)
        head.addWidget(btn_photos)
        head.addStretch(1)

        self.tree = QtWidgets.QTreeView()
        self.tree.setAlternatingRowColors(True)
        self.tree.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.model = QtGui.QStandardItemModel()
        self.model.setHorizontalHeaderLabels(HEADERS)
        self.tree.setModel(self.model)

        self.summary = big_label()
        note = QtWidgets.QLabel(
            "رقم الموديل تصنيف وصفي لا مالي — لا يُنشأ له حساب ولا يدخل "
            "في القيود. يُدخَل من شاشة الإنتاج والتوريد قبل رقم التشغيل.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        lay.addWidget(title_label("دليل الموديلات"))
        lay.addWidget(note)
        lay.addLayout(head)
        lay.addWidget(self.tree, 1)
        lay.addWidget(self.summary)
        self.refresh()

    # ══════════ البناء ══════════
    def _styles(self):
        st = getattr(self, "_st", None)
        if st is None:
            bold = QtGui.QFont()
            bold.setBold(True)
            head = QtGui.QFont()
            head.setBold(True)
            head.setPointSize(max(9, head.pointSize() + 1))
            st = {"bold": bold, "head": head,
                  "model": QtGui.QBrush(QtGui.QColor("#5A3E1B")),
                  "sold": QtGui.QBrush(QtGui.QColor("#8B5E1E")),
                  "stock": QtGui.QBrush(QtGui.QColor("#1E6B33")),
                  "bg": QtGui.QBrush(QtGui.QColor("#EFE9DC"))}
            self._st = st
        return st

    def _cells(self, vals, bold=False, brush=None, data=None):
        st = self._styles()
        cells = []
        for v in vals:
            it = QtGui.QStandardItem(str(v))
            it.setEditable(False)
            if bold:
                it.setFont(st["bold"])
            if brush is not None:
                it.setForeground(brush)
            cells.append(it)
        if data is not None:
            cells[0].setData(data, QtCore.Qt.UserRole)
        return cells

    def refresh(self, force=False):
        """يبني الشجرة — فقط إن تغيّرت الأطقم."""
        try:
            with db() as conn:
                sig = conn.execute(
                    "SELECT COUNT(*) n, COALESCE(MAX(id),0) m,"
                    " COALESCE(SUM(status='sold'),0) s"
                    " FROM work_orders WHERE is_deleted=0").fetchone()
                fp = (sig["n"], sig["m"], sig["s"],
                      self.view_mode.currentData(),
                      self.sort_mode.currentData())
                if not force and fp == self._fp:
                    return
                models = mc.list_models(conn)
                mode = self.view_mode.currentData() or "all"
                # الموديلات التي لا شيء لها في الفرع المطلوب تُستبعد
                if mode == "in_stock":
                    models = [m for m in models if m["in_count"]]
                elif mode == "sold":
                    models = [m for m in models if m["out_count"]]
                models = self._sorted(models)
                data = {}
                for m in models:
                    data[m["model"]] = {
                        "sold": (mc.model_items(conn, m["model"], "sold")
                                 if mode in ("all", "sold") else []),
                        "in_stock": (mc.model_items(conn, m["model"],
                                                    "in_stock")
                                     if mode in ("all", "in_stock") else []),
                    }
            self._fp = fp
            self._render(models, data)
        except Exception as e:
            err(self, e)

    def _sorted(self, models):
        """يرتّب الموديلات بحسب الاختيار.

        الفرز الأبجدي يعتمد ترتيب Python الطبيعي للنصوص العربية،
        والفرز بالعدد يعتمد عدد الأطقم **المعروضة** في الوضع الحالي
        لا الإجمالي — فيكون الترتيب موافقاً لما يراه المستخدم.
        """
        mode = self.sort_mode.currentData() or "az"
        view = self.view_mode.currentData() or "all"

        def _count(m):
            if view == "in_stock":
                return m["in_count"]
            if view == "sold":
                return m["out_count"]
            return m["count"]

        if mode == "az":
            return sorted(models, key=lambda m: str(m["model"]))
        if mode == "za":
            return sorted(models, key=lambda m: str(m["model"]),
                          reverse=True)
        if mode == "most":
            return sorted(models, key=lambda m: (-_count(m),
                                                 str(m["model"])))
        return sorted(models, key=lambda m: (_count(m), str(m["model"])))

    def _render(self, models, data):
        st = self._styles()
        self.tree.setUpdatesEnabled(False)
        try:
            self.model.removeRows(0, self.model.rowCount())
            self.model.setHorizontalHeaderLabels(HEADERS)
            root = self.model.invisibleRootItem()
            mode = self.view_mode.currentData() or "all"
            for m in models:
                # العدد والوزن في رأس الموديل يتبعان الوضع المعروض:
                # عرض «المتاح» يُظهر عدد المتاح لا الإجمالي — وإلا
                # ظهر رقم في الرأس وآخر في الفرع فيبدو تناقضاً.
                if mode == "in_stock":
                    head_n, head_w = m["in_count"], m["in_weight"]
                elif mode == "sold":
                    head_n, head_w = m["out_count"], m["out_weight"]
                else:
                    head_n = m["count"]
                    head_w = round(m["in_weight"] + m["out_weight"], 2)
                total_w = head_w
                _img = "🖼 " if mc.image_path(m["model"]) else ""
                node = self._cells(
                    [f"◄  {_img}الموديل {m['model']}", head_n,
                     f"{kv.g(head_w):,.2f}", ""],
                    bold=True, brush=st["model"],
                    data=("model", m["model"]))
                # إبراز صف الموديل: خط أكبر وخلفية مميّزة
                for it in node:
                    try:
                        it.setFont(st["head"])
                        it.setBackground(st["bg"])
                    except Exception:
                        pass
                root.appendRow(node)

                if mode in ("all", "sold"):
                    sold = self._cells(
                        ["طرف المناديب", m["out_count"],
                         f"{kv.g(m['out_weight']):,.2f}", "عند المناديب"],
                        bold=True, brush=st["sold"],
                        data=("branch", m["model"]))
                    node[0].appendRow(sold)
                    for i in data[m["model"]]["sold"]:
                        sold[0].appendRow(self._cells(
                            [i["wo"], "", f"{kv.g(i['reg']):,.2f}",
                             f"{i['holder']}  ·  {i['date']}"],
                            data=("wo", i["id"])))

                if mode in ("all", "in_stock"):
                    stock = self._cells(
                        ["الموجود (متاح للبيع)", m["in_count"],
                         f"{kv.g(m['in_weight']):,.2f}",
                         "في الذهب المشغول"],
                        bold=True, brush=st["stock"],
                        data=("branch", m["model"]))
                    node[0].appendRow(stock)
                    for i in data[m["model"]]["in_stock"]:
                        stock[0].appendRow(self._cells(
                            [i["wo"], "", f"{i['reg']:,.2f}",
                             f"أُدخل: {i['date']}"],
                            data=("wo", i["id"])))
            # مطوية عند الفتح: القائمة قد تطول، والمستخدم يفتح ما
            # يعنيه فقط — أسرع وأوضح.
            self.tree.collapseAll()
        finally:
            try:
                self.tree.setUpdatesEnabled(True)
            except Exception:
                pass
        try:
            hh = self.tree.header()
            hh.setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
            for c, w in enumerate((320, 80, 130, 240)):
                self.tree.setColumnWidth(c, w)
            hh.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        except Exception:
            pass

        mode = self.view_mode.currentData() or "all"
        tot_in = sum(m["in_weight"] for m in models)
        tot_out = sum(m["out_weight"] for m in models)
        n_in = sum(m["in_count"] for m in models)
        n_out = sum(m["out_count"] for m in models)
        if mode == "in_stock":
            txt = (f"{len(models)} موديل   |   المتاح للبيع: "
                   f"{n_in} طقم · {kv.g(tot_in):,.2f} {kv.unit()}")
        elif mode == "sold":
            txt = (f"{len(models)} موديل   |   المباع بالخارج: "
                   f"{n_out} طقم · {kv.g(tot_out):,.2f} {kv.unit()}")
        else:
            txt = (f"{len(models)} موديل   |   المتاح: {n_in} طقم · "
                   f"{kv.g(tot_in):,.2f} {kv.unit()}   |   المباع: "
                   f"{n_out} طقم · {kv.g(tot_out):,.2f} {kv.unit()}")
        self.summary.setText(txt)

    # ══════════ الإجراءات ══════════
    def apply_filter(self, text):
        text = (text or "").strip()
        for i in range(self.model.rowCount()):
            node = self.model.item(i)
            show = not text or text in node.text()
            if not show:
                for b in range(node.rowCount()):
                    br = node.child(b)
                    for k in range(br.rowCount()):
                        if text in br.child(k).text():
                            show = True
                            break
                    if show:
                        break
            self.tree.setRowHidden(i, self.model.invisibleRootItem().index(),
                                   not show)

    def _menu(self, pos):
        idx = self.tree.indexAt(pos)
        if not idx.isValid():
            return
        item = self.model.itemFromIndex(idx.siblingAtColumn(0))
        if item is None:
            return
        d = item.data(QtCore.Qt.UserRole)
        if not d:
            return
        kind, val = d
        m = QtWidgets.QMenu(self)
        if kind == "model":
            m.addAction("✎ إعادة تسمية الموديل",
                        lambda: self.rename_model(val))
            m.addAction("🗑 حذف الموديل وفروعه",
                        lambda: self.delete_model(val))
            m.addSeparator()
            has = mc.image_path(val) is not None
            m.addAction("🖼 استعراض الصورة" if has else "🖼 لا توجد صورة",
                        lambda: self.view_image(val)).setEnabled(has)
            m.addAction("➕ إضافة/استبدال الصورة",
                        lambda: self.add_image(val))
            act = m.addAction("🗑 حذف الصورة",
                              lambda: self.del_image(val))
            act.setEnabled(has)
        elif kind == "wo":
            m.addAction("✎ تغيير موديل هذا الطقم",
                        lambda: self.assign_model(val))
        m.exec_(self.tree.viewport().mapToGlobal(pos))

    # ══════════ صور الموديلات ══════════
    def add_image(self, model_no):
        """يضيف صورة للموديل من جهاز المستخدم."""
        try:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, f"اختر صورة الموديل {model_no}", "",
                "صور (*.png *.jpg *.jpeg *.webp *.bmp)")
            if not path:
                return
            mc.set_image(model_no, path, self.user["username"])
            info(self, f"أُضيفت صورة الموديل {model_no}.\n\n"
                       f"الصورة وصفية بحتة — لا أثر محاسبي لها.")
            self.refresh(force=True)
        except Exception as e:
            err(self, e)

    def del_image(self, model_no):
        """يحذف صورة الموديل."""
        try:
            if not ask(self, f"حذف صورة الموديل {model_no}؟"):
                return
            if mc.remove_image(model_no):
                info(self, "حُذفت الصورة.")
                self.refresh(force=True)
        except Exception as e:
            err(self, e)

    def view_image(self, model_no):
        """يعرض صورة الموديل — بالتطبيق المشترك نفسه في كل الشاشات."""
        try:
            from ui.widgets.common import show_model_image
            show_model_image(self, model_no)
        except Exception as e:
            err(self, e)

    def delete_model(self, model_no):
        """يحذف الموديل بكامله — بلا أي أثر محاسبي."""
        try:
            with db() as conn:
                n = conn.execute(
                    "SELECT COUNT(*) c FROM work_orders"
                    " WHERE is_deleted=0"
                    " AND TRIM(COALESCE(model_no,''))=?",
                    (str(model_no).strip(),)).fetchone()["c"]
            if not ask(self,
                       f"حذف الموديل «{model_no}» وفروعه؟\n\n"
                       f"سيُفكّ عن {n} طقم، وتُحذف صورته إن وُجدت.\n\n"
                       f"لا أثر محاسبي إطلاقاً: الأطقم تبقى بأوزانها "
                       f"وحالاتها وفواتيرها، وتنتقل لمجموعة "
                       f"«بلا موديل»."):
                return
            with db() as conn:
                r = mc.delete_model(conn, model_no,
                                    self.user["username"])
            info(self, f"حُذف الموديل «{r['model']}».\n"
                       f"فُكّ عن {r['count']} طقم"
                       + ("\nوحُذفت صورته." if r["image"] else "."))
            self.refresh(force=True)
        except Exception as e:
            err(self, e)

    def rename_model(self, model_no):
        try:
            new, ok = QtWidgets.QInputDialog.getText(
                self, "إعادة تسمية موديل",
                f"الموديل الحالي: {model_no}\n\nالرقم الجديد:",
                text=str(model_no))
            if not ok or not str(new).strip():
                return
            with db() as conn:
                r = mc.rename_model(conn, model_no, str(new).strip(),
                                    self.user["username"])
            info(self, f"الموديل: {r['old']} ← {r['new']}\n"
                       f"تأثّر {r['count']} طقم.\n\nلا أثر مالي — "
                       f"الموديل تصنيف وصفي.")
            self.refresh(force=True)
        except Exception as e:
            err(self, e)

    def assign_model(self, wo_id):
        try:
            with db() as conn:
                names = mc.model_names(conn)
                w = conn.execute(
                    "SELECT work_order_no, model_no FROM work_orders"
                    " WHERE id=?", (wo_id,)).fetchone()
            new, ok = QtWidgets.QInputDialog.getItem(
                self, "تغيير موديل الطقم",
                f"رقم التشغيل: {w['work_order_no']}\n\nالموديل:",
                names or [""], 0, True)
            if not ok:
                return
            with db() as conn:
                r = mc.assign_model(conn, wo_id, new,
                                    self.user["username"])
            info(self, f"الطقم {r['wo']} ← الموديل {r['model'] or '—'}")
            self.refresh(force=True)
        except Exception as e:
            err(self, e)

    def _expanded_models(self):
        """الموديلات الموسّعة حالياً — ليحاكيها قالب الطباعة."""
        out = []
        try:
            root = self.model.invisibleRootItem()
            for i in range(root.rowCount()):
                it = root.child(i)
                d = it.data(QtCore.Qt.UserRole)
                if not d:
                    continue
                if self.tree.isExpanded(it.index()):
                    out.append(d[1])
        except Exception:
            pass
        return out

    def print_photos(self):
        """يطبع صور الموديلات — أربع في كل صفحة A4."""
        try:
            from services import print_manager
            n, ok = QtWidgets.QInputDialog.getInt(
                self, "طباعة صور الموديلات",
                "اطبع صور الموديلات التي عددها:\n"
                "(القطع فأكثر — تُطبع أربع صور في كل صفحة A4)",
                3, 1, 999, 1)
            if not ok:
                return
            print_manager.preview_document(
                self, "model_photos", 0, min_count=int(n),
                mode=self.view_mode.currentData() or "all",
                sort=self.sort_mode.currentData() or "az")
        except Exception as e:
            err(self, e)

    def print_catalog(self):
        """يطبع الدليل **كما يظهر على الشاشة**.

        الموديلات المطوية تُطبع سطراً واحداً بإجمالياتها، والموسّعة
        تُطبع بفروعها — فالورقة تطابق ما يراه المستخدم.
        """
        try:
            from services import print_manager
            print_manager.preview_document(
                self, "models_catalog", 0,
                mode=self.view_mode.currentData() or "all",
                sort=self.sort_mode.currentData() or "az",
                expanded=self._expanded_models())
        except Exception as e:
            err(self, e)
