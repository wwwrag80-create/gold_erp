# -*- coding: utf-8 -*-
"""نافذة «📝 الطلبات» في دليل الموديلات (4.59).

قسمان:
  ① **تسجيل طلب** — اسم العميل، ثم الموديلات من صورها (نقرٌ مزدوج أو
     «إضافة») وعددُ كلٍّ منها. وأمام كل موديل ما بالخزنة منه وما يلزم
     تصنيعه. يُحفظ برقمٍ (OR-00001) ويُطبع بصوره.
  ② **الطلبات المحفوظة** — بحثٌ وحالة (مفتوح · مُسلَّم · ملغى)، ومعاينةٌ
     بصور موديلات الطلب المحدَّد وعددها، وطباعته، ونسخه للواتساب،
     و«خلاصة التصنيع» لما تطلبه الطلبات المفتوحة كلها مجتمعةً.

الطلب بلا أثرٍ محاسبي: لا قيد ولا مخزون (`models.model_orders`).
"""
import os

from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from models import model_orders as mo
from models import models_catalog as mc
from ui.widgets.common import ask, date_edit, dstr, err, info, make_table

# ══ مصغّرات الصور — تُقرأ مصغّرةً من القرص مرةً وتُحفظ في الذاكرة ══
_THUMBS = {}
_MAX_THUMBS = 800


def thumb(model, size=110):
    """صورة الموديل مصغّرة (QPixmap) — أو None إن لم تكن له صورة."""
    p = mc.image_path(model)
    if p is None:
        return None
    try:
        st = os.stat(p)
        key = (str(p), mc.file_stamp(st), st.st_size, int(size))
    except OSError:
        return None
    pm = _THUMBS.get(key)
    if pm is not None:
        return pm
    r = QtGui.QImageReader(str(p))
    r.setAutoTransform(True)
    sz = r.size()
    if sz.isValid() and sz.width() > 0:
        # تُفكّ الصورة بمقاسها المصغّر مباشرةً — أسرع بكثير من فكّها
        # كاملةً ثم تصغيرها، والدليل قد يحوي مئات الصور
        r.setScaledSize(sz.scaled(size * 2, size * 2,
                                  QtCore.Qt.KeepAspectRatio))
    img = r.read()
    if img.isNull():
        return None
    pm = QtGui.QPixmap.fromImage(img)
    _THUMBS[key] = pm
    if len(_THUMBS) > _MAX_THUMBS:
        _THUMBS.pop(next(iter(_THUMBS)))
    return pm


def _placeholder(size, text="لا صورة"):
    pm = QtGui.QPixmap(size, size)
    pm.fill(QtGui.QColor("#F1ECE2"))
    p = QtGui.QPainter(pm)
    p.setPen(QtGui.QColor("#9A8F7C"))
    f = p.font()
    f.setPointSize(max(7, size // 11))
    p.setFont(f)
    p.drawText(pm.rect(), QtCore.Qt.AlignCenter, text)
    p.end()
    return pm


def _icon(model, size):
    pm = thumb(model, size)
    return QtGui.QIcon(pm if pm is not None else _placeholder(size))


class ModelOrdersDialog(QtWidgets.QDialog):
    PICK_ICON = 108
    LINE_ICON = 56
    PREV_ICON = 120
    # أعمدة جدول الطلب
    C_IMG, C_MODEL, C_QTY, C_STOCK, C_SHORT, C_NOTE, C_DEL = range(7)

    def __init__(self, parent, user, order_id=None, preset_models=None):
        super().__init__(parent)
        self.user = user or {}
        self.setWindowTitle("📝 طلبات العملاء — من دليل الموديلات")
        self.resize(1200, 780)
        self._order_id = None
        self._dirty = False
        self._catalog = {}
        self._pending_icons = []

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._editor_tab(), "📝 تسجيل طلب")
        self.tabs.addTab(self._list_tab(), "📋 الطلبات المحفوظة")
        self.tabs.currentChanged.connect(self._tab_changed)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addWidget(self.tabs)

        self._icon_timer = QtCore.QTimer(self)
        self._icon_timer.setInterval(15)
        self._icon_timer.timeout.connect(self._load_some_icons)

        self._load_customers()
        self._load_catalog()
        self.new_order(ask_first=False)
        if order_id:
            self.load_order(order_id)
        for m in preset_models or []:
            self.add_model(m)
        self.refresh_list()
        self._dirty = bool(preset_models)

    # ══════════════════════════════════════════════════════════════
    #  ① تسجيل طلب
    # ══════════════════════════════════════════════════════════════
    def _editor_tab(self):
        w = QtWidgets.QWidget()
        self.cust = QtWidgets.QComboBox()
        self.cust.setEditable(True)
        self.cust.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.cust.setMinimumWidth(260)
        self.cust.lineEdit().setPlaceholderText(
            "اسم العميل — من القائمة أو اكتبه")
        comp = QtWidgets.QCompleter(self.cust.model(), self.cust)
        comp.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        comp.setFilterMode(QtCore.Qt.MatchContains)
        comp.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        self.cust.setCompleter(comp)
        self.cust.editTextChanged.connect(self._touch)
        self.o_date = date_edit()
        self.o_date.dateChanged.connect(self._touch)
        self.due_on = QtWidgets.QCheckBox("موعد التسليم:")
        self.due_date = date_edit()
        self.due_date.setDate(QtCore.QDate.currentDate().addDays(7))
        self.due_date.setEnabled(False)
        self.due_on.toggled.connect(self.due_date.setEnabled)
        self.due_on.toggled.connect(self._touch)
        self.due_date.dateChanged.connect(self._touch)
        self.no_lbl = QtWidgets.QLabel("")
        self.no_lbl.setObjectName("cardSub")

        head = QtWidgets.QHBoxLayout()
        head.addWidget(QtWidgets.QLabel("العميل:"))
        head.addWidget(self.cust, 2)
        head.addWidget(QtWidgets.QLabel("التاريخ:"))
        head.addWidget(self.o_date)
        head.addWidget(self.due_on)
        head.addWidget(self.due_date)
        head.addStretch(1)
        head.addWidget(self.no_lbl)

        # ── منتقي الموديلات بصورها ──
        self.pick_search = QtWidgets.QLineEdit()
        self.pick_search.setPlaceholderText("🔍 ابحث برقم الموديل…")
        self.pick_search.textChanged.connect(self._filter_pick)
        self.only_imgs = QtWidgets.QCheckBox("بصورٍ فقط")
        self.only_imgs.toggled.connect(self._filter_pick)
        self.pick = QtWidgets.QListWidget()
        self.pick.setViewMode(QtWidgets.QListView.IconMode)
        self.pick.setIconSize(QtCore.QSize(self.PICK_ICON, self.PICK_ICON))
        # سطرا النص تحت الصورة (الموديل · بالخزنة) بارتفاع الخط الفعلي —
        # فلا يُقصّ الثاني على شاشةٍ خطّها أكبر
        line = self.pick.fontMetrics().height()
        self.pick.setGridSize(QtCore.QSize(self.PICK_ICON + 30,
                                           self.PICK_ICON + 2 * line + 16))
        self.pick.setResizeMode(QtWidgets.QListView.Adjust)
        self.pick.setMovement(QtWidgets.QListView.Static)
        self.pick.setUniformItemSizes(True)
        self.pick.setWordWrap(True)
        self.pick.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection)
        self.pick.itemDoubleClicked.connect(
            lambda it: self.add_model(it.data(QtCore.Qt.UserRole)))
        btn_add = QtWidgets.QPushButton("إضافة المحدَّد إلى الطلب ←")
        btn_add.clicked.connect(self._add_selected)
        pick_box = QtWidgets.QGroupBox(
            "الموديلات — نقرٌ مزدوج على الصورة يضيفها (ومرةً أخرى يزيد"
            " عددها)")
        pv = QtWidgets.QVBoxLayout(pick_box)
        prow = QtWidgets.QHBoxLayout()
        prow.addWidget(self.pick_search, 1)
        prow.addWidget(self.only_imgs)
        pv.addLayout(prow)
        pv.addWidget(self.pick, 1)
        pv.addWidget(btn_add)

        # ── أسطر الطلب ──
        self.lines = make_table()
        self.lines.setColumnCount(7)
        self.lines.setHorizontalHeaderLabels(
            ["الصورة", "الموديل", "العدد", "بالخزنة", "للتصنيع", "ملاحظة",
             ""])
        self.lines.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.SelectedClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed)
        self.lines.setIconSize(QtCore.QSize(self.LINE_ICON, self.LINE_ICON))
        self.lines.verticalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Fixed)
        self.lines.verticalHeader().setDefaultSectionSize(self.LINE_ICON + 8)
        self.lines.itemChanged.connect(self._line_item_changed)
        try:
            from ui.widgets.table_fit import fit_columns
            fit_columns(self.lines, [12, 20, 13, 12, 12, 25, 6])
        except Exception:
            pass
        self.totals = QtWidgets.QLabel("")
        self.totals.setObjectName("cardSub")
        self.notes = QtWidgets.QLineEdit()
        self.notes.setPlaceholderText("ملاحظات الطلب (اختياري) — المقاس،"
                                      " اللون، العيار…")
        self.notes.textChanged.connect(self._touch)
        lines_box = QtWidgets.QGroupBox("الطلب")
        lv = QtWidgets.QVBoxLayout(lines_box)
        lv.addWidget(self.lines, 1)
        lv.addWidget(self.totals)
        lv.addWidget(self.notes)

        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        split.addWidget(pick_box)
        split.addWidget(lines_box)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 5)

        self.btn_save = QtWidgets.QPushButton("💾 حفظ الطلب")
        self.btn_save.setObjectName("homeBtn")
        self.btn_save.clicked.connect(self.save)
        btn_save_print = QtWidgets.QPushButton("🖨 حفظ ومعاينة")
        btn_save_print.clicked.connect(self._save_and_print)
        btn_share = QtWidgets.QPushButton("📋 نسخ للواتساب")
        btn_share.setObjectName("ghost")
        btn_share.clicked.connect(self._share_current)
        btn_new = QtWidgets.QPushButton("🗋 طلب جديد")
        btn_new.setObjectName("ghost")
        btn_new.clicked.connect(lambda: self.new_order())
        acts = QtWidgets.QHBoxLayout()
        acts.addWidget(self.btn_save)
        acts.addWidget(btn_save_print)
        acts.addWidget(btn_share)
        acts.addStretch(1)
        acts.addWidget(btn_new)

        v = QtWidgets.QVBoxLayout(w)
        v.addLayout(head)
        v.addWidget(split, 1)
        v.addLayout(acts)
        return w

    def _touch(self, *_):
        self._dirty = True

    def _load_customers(self):
        try:
            from models import entities
            with db(readonly=True) as conn:
                # كل جهات التعامل كما في شاشة المبيعات — عدا الداخلية
                rows = [r for r in entities.list_customers(conn)
                        if r["entity_type"] != "internal"]
            self._customers = {r["name"]: r["id"] for r in rows}
        except Exception:
            self._customers = {}
        self.cust.blockSignals(True)
        cur = self.cust.currentText()
        self.cust.clear()
        self.cust.addItems(sorted(self._customers))
        self.cust.setCurrentIndex(-1)
        self.cust.setEditText(cur)
        self.cust.blockSignals(False)

    def _load_catalog(self):
        with db(readonly=True) as conn:
            cat = mo.catalog(conn)
        self._catalog = {m["model"]: m for m in cat}
        self.pick.clear()
        self._pending_icons = []
        ph = QtGui.QIcon(_placeholder(self.PICK_ICON, "…"))
        for m in cat:
            it = QtWidgets.QListWidgetItem(
                ph, f"{m['model']}\nبالخزنة {m['in_count']}")
            it.setData(QtCore.Qt.UserRole, m["model"])
            it.setTextAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)
            it.setToolTip(f"الموديل {m['model']} — بالخزنة {m['in_count']}"
                          f" · عند المناديب {m['out_count']}")
            self.pick.addItem(it)
            self._pending_icons.append(it)
        self._icon_timer.start()
        self._filter_pick()

    def _load_some_icons(self):
        """الصور تُحمَّل دفعاتٍ صغيرة — فلا تتجمّد النافذة عند فتحها."""
        for _ in range(14):
            if not self._pending_icons:
                self._icon_timer.stop()
                return
            it = self._pending_icons.pop(0)
            try:
                it.setIcon(_icon(it.data(QtCore.Qt.UserRole),
                                 self.PICK_ICON))
            except RuntimeError:          # عنصرٌ حُذف مع إعادة التحميل
                pass

    def _filter_pick(self, *_):
        q = self.pick_search.text().strip().lower()
        only = self.only_imgs.isChecked()
        for i in range(self.pick.count()):
            it = self.pick.item(i)
            m = self._catalog.get(it.data(QtCore.Qt.UserRole), {})
            hide = (q and q not in str(m.get("model", "")).lower()) or \
                (only and not m.get("has_image"))
            it.setHidden(bool(hide))

    def _add_selected(self):
        sel = self.pick.selectedItems()
        if not sel:
            info(self, "اختر موديلاً أو أكثر من الصور أولاً (Ctrl للتعدد).")
            return
        for it in sel:
            self.add_model(it.data(QtCore.Qt.UserRole))

    # ── الأسطر ──
    def _row_of(self, model):
        for r in range(self.lines.rowCount()):
            it = self.lines.item(r, self.C_MODEL)
            if it is not None and it.text() == model:
                return r
        return -1

    def add_model(self, model, qty=1, note=""):
        model = str(model or "").strip()
        if not model:
            return
        r = self._row_of(model)
        if r >= 0:
            sp = self.lines.cellWidget(r, self.C_QTY)
            if sp is not None:
                sp.setValue(sp.value() + int(qty or 1))
            self.lines.setCurrentCell(r, self.C_MODEL)
            return
        self.lines.blockSignals(True)
        r = self.lines.rowCount()
        self.lines.insertRow(r)
        img = QtWidgets.QTableWidgetItem()
        img.setIcon(_icon(model, self.LINE_ICON))
        img.setFlags(QtCore.Qt.ItemIsEnabled)
        self.lines.setItem(r, self.C_IMG, img)
        mi = QtWidgets.QTableWidgetItem(model)
        mi.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
        mi.setTextAlignment(QtCore.Qt.AlignCenter)
        f = mi.font()
        f.setBold(True)
        mi.setFont(f)
        self.lines.setItem(r, self.C_MODEL, mi)
        sp = QtWidgets.QSpinBox()
        sp.setRange(1, 9999)
        sp.setValue(max(1, int(qty or 1)))
        sp.setAlignment(QtCore.Qt.AlignCenter)
        # كخانة «العدد» في المبيعات الضريبية: رقمٌ يُكتب (والأسهم تزيد
        # وتنقص) — بلا زرّين يزاحمان الرقم في خانةٍ ضيقة
        sp.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        sp.valueChanged.connect(lambda *_: (self._touch(),
                                            self._update_totals()))
        self.lines.setCellWidget(r, self.C_QTY, sp)
        for c in (self.C_STOCK, self.C_SHORT):
            x = QtWidgets.QTableWidgetItem("")
            x.setFlags(QtCore.Qt.ItemIsEnabled)
            x.setTextAlignment(QtCore.Qt.AlignCenter)
            self.lines.setItem(r, c, x)
        ni = QtWidgets.QTableWidgetItem(note or "")
        ni.setToolTip("نقرٌ مزدوج لكتابة ملاحظةٍ على هذا الموديل")
        self.lines.setItem(r, self.C_NOTE, ni)
        btn = QtWidgets.QToolButton()
        btn.setText("✕")
        btn.setToolTip("حذف الموديل من الطلب")
        btn.setAutoRaise(True)
        btn.clicked.connect(lambda _=False, m=model: self._remove(m))
        self.lines.setCellWidget(r, self.C_DEL, btn)
        self.lines.blockSignals(False)
        self._touch()
        self._update_totals()
        self.lines.scrollToBottom()

    def _remove(self, model):
        r = self._row_of(model)
        if r >= 0:
            self.lines.removeRow(r)
            self._touch()
            self._update_totals()

    def _line_item_changed(self, *_):
        self._touch()

    def _rows(self):
        out = []
        for r in range(self.lines.rowCount()):
            m = self.lines.item(r, self.C_MODEL).text()
            sp = self.lines.cellWidget(r, self.C_QTY)
            ni = self.lines.item(r, self.C_NOTE)
            out.append({"model": m, "qty": sp.value() if sp else 1,
                        "note": ni.text().strip() if ni else ""})
        return out

    def _update_totals(self):
        n = pieces = short = 0
        for r in range(self.lines.rowCount()):
            m = self.lines.item(r, self.C_MODEL).text()
            sp = self.lines.cellWidget(r, self.C_QTY)
            q = sp.value() if sp else 1
            have = int(self._catalog.get(m, {}).get("in_count", 0))
            s = max(0, q - have)
            self.lines.item(r, self.C_STOCK).setText(str(have))
            si = self.lines.item(r, self.C_SHORT)
            si.setText(str(s) if s else "✔")
            si.setForeground(QtGui.QColor("#a4262c" if s else "#1E6B33"))
            n += 1
            pieces += q
            short += s
        self.totals.setText(
            f"{n} موديل · {pieces} قطعة"
            + (f" · يلزم تصنيع {short} قطعة (ما لا يكفيه الموجود"
               " بالخزنة)" if short else " · كلها متوفّرة بالخزنة ✔"
               if n else ""))

    # ── حفظ وتحميل ──
    def new_order(self, ask_first=True):
        if ask_first and self._dirty and self.lines.rowCount():
            if not ask(self, "في الطلب الحالي تغييرٌ لم يُحفظ — تجاهله"
                             " والبدء بطلبٍ جديد؟"):
                return
        self._order_id = None
        self.cust.setCurrentIndex(-1)
        self.cust.setEditText("")
        self.o_date.setDate(QtCore.QDate.currentDate())
        self.due_on.setChecked(False)
        self.notes.clear()
        self.lines.setRowCount(0)
        self.no_lbl.setText("طلب جديد")
        self._update_totals()
        self._dirty = False
        self.tabs.setCurrentIndex(0)

    def load_order(self, order_id):
        with db(readonly=True) as conn:
            o = mo.get_order(conn, order_id)
        if not o:
            err(self, "الطلب غير موجود")
            return
        self._order_id = o["id"]
        self.cust.setEditText(o["customer_name"])
        self.o_date.setDate(QtCore.QDate.fromString(o["order_date"],
                                                    "yyyy-MM-dd"))
        self.due_on.setChecked(bool(o.get("due_date")))
        if o.get("due_date"):
            self.due_date.setDate(QtCore.QDate.fromString(o["due_date"],
                                                          "yyyy-MM-dd"))
        self.notes.setText(o.get("notes") or "")
        self.lines.setRowCount(0)
        for ln in o["lines"]:
            self.add_model(ln["model"], ln["qty"], ln.get("note"))
        self.no_lbl.setText(f"تعديل الطلب {o['order_no']} — "
                            f"{o['status_label']}")
        self._dirty = False
        self.tabs.setCurrentIndex(0)

    def save(self):
        """يحفظ الطلب — ويعيد رقمه أو None."""
        try:
            name = self.cust.currentText().strip()
            with db() as conn:
                res = mo.save_order(
                    conn, name, self._rows(),
                    self.user.get("username"), order_id=self._order_id,
                    entity_id=self._customers.get(name),
                    order_date=dstr(self.o_date),
                    due_date=(dstr(self.due_date)
                              if self.due_on.isChecked() else None),
                    notes=self.notes.text().strip())
            self._order_id = res["id"]
            self.no_lbl.setText(f"✔ حُفظ الطلب {res['order_no']} — "
                                f"{res['models']} موديل · {res['pieces']}"
                                " قطعة")
            self._dirty = False
            self.refresh_list(select_id=res["id"])
            return res
        except Exception as e:
            err(self, e)
            return None

    def _save_and_print(self):
        res = self.save()
        if res:
            self.print_order(res["id"])

    def _share_current(self):
        if self._dirty or not self._order_id:
            if not self.save():
                return
        self._share(self._order_id)

    # ══════════════════════════════════════════════════════════════
    #  ② الطلبات المحفوظة
    # ══════════════════════════════════════════════════════════════
    LIST_COLS = ["رقم الطلب", "التاريخ", "العميل", "الموديلات", "القطع",
                 "للتصنيع", "التسليم", "الحالة"]

    def _list_tab(self):
        w = QtWidgets.QWidget()
        self.st_filter = QtWidgets.QComboBox()
        for k, t in (("open", "المفتوحة"), ("all", "الكل"),
                     ("done", "المُسلَّمة"), ("cancelled", "الملغاة")):
            self.st_filter.addItem(t, k)
        self.st_filter.currentIndexChanged.connect(
            lambda *_: self.refresh_list())
        self.l_search = QtWidgets.QLineEdit()
        self.l_search.setPlaceholderText(
            "🔍 ابحث باسم العميل أو رقم الطلب أو رقم موديل…")
        self.l_search.textChanged.connect(lambda *_: self.refresh_list())
        btn_prod = QtWidgets.QPushButton("🏭 خلاصة التصنيع")
        btn_prod.setToolTip("ما تطلبه الطلبات المفتوحة كلها مجتمعةً من كل"
                            " موديل، وما بالخزنة منه، وما يلزم تصنيعه")
        btn_prod.clicked.connect(self.print_production)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("الحالة:"))
        top.addWidget(self.st_filter)
        top.addWidget(self.l_search, 1)
        top.addWidget(btn_prod)

        self.olist = make_table()
        self.olist.itemSelectionChanged.connect(self._preview_selected)
        self.olist.cellDoubleClicked.connect(
            lambda r, _c: self._open_selected())

        self.prev_head = QtWidgets.QLabel("اختر طلباً لمعاينته")
        self.prev_head.setWordWrap(True)
        self.prev_head.setTextFormat(QtCore.Qt.RichText)
        self.prev = QtWidgets.QListWidget()
        self.prev.setViewMode(QtWidgets.QListView.IconMode)
        self.prev.setIconSize(QtCore.QSize(self.PREV_ICON, self.PREV_ICON))
        line = self.prev.fontMetrics().height()
        self.prev.setGridSize(QtCore.QSize(self.PREV_ICON + 34,
                                           self.PREV_ICON + 2 * line + 16))
        self.prev.setResizeMode(QtWidgets.QListView.Adjust)
        self.prev.setMovement(QtWidgets.QListView.Static)
        self.prev.setWordWrap(True)
        self.prev.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        prev_box = QtWidgets.QGroupBox("معاينة الطلب")
        pv = QtWidgets.QVBoxLayout(prev_box)
        pv.addWidget(self.prev_head)
        pv.addWidget(self.prev, 1)

        split = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        split.addWidget(self.olist)
        split.addWidget(prev_box)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 5)

        def _b(text, fn, name=None):
            b = QtWidgets.QPushButton(text)
            if name:
                b.setObjectName(name)
            b.clicked.connect(fn)
            return b

        acts = QtWidgets.QHBoxLayout()
        acts.addWidget(_b("✎ فتح للتعديل", self._open_selected, "homeBtn"))
        acts.addWidget(_b("🖨 معاينة وطباعة",
                          lambda: self._with_sel(self.print_order)))
        acts.addWidget(_b("📋 نسخ للواتساب",
                          lambda: self._with_sel(self._share)))
        acts.addStretch(1)
        acts.addWidget(_b("✔ تم التسليم",
                          lambda: self._set_status("done")))
        acts.addWidget(_b("↺ إعادة فتح", lambda: self._set_status("open"),
                          "ghost"))
        acts.addWidget(_b("✕ إلغاء الطلب",
                          lambda: self._set_status("cancelled"), "ghost"))
        acts.addWidget(_b("🗑 حذف", self._delete, "ghost"))

        v = QtWidgets.QVBoxLayout(w)
        v.addLayout(top)
        v.addWidget(split, 1)
        v.addLayout(acts)
        return w

    def _tab_changed(self, i):
        if i == 1:
            self.refresh_list()

    def refresh_list(self, select_id=None):
        try:
            with db(readonly=True) as conn:
                rows = mo.list_orders(conn, self.st_filter.currentData(),
                                      self.l_search.text())
                n_open = mo.count_open(conn)
        except Exception as e:
            err(self, e)
            return
        self._orders = rows
        from ui.widgets.common import fill
        fill(self.olist, self.LIST_COLS,
             [(r["order_no"], r["order_date"], r["customer_name"],
               r["n_models"], r["n_pieces"], r["short"] or "✔",
               r.get("due_date") or "—", r["status_label"]) for r in rows])
        try:
            from ui.widgets.table_fit import fit_columns
            fit_columns(self.olist, [11, 10, 25, 9, 8, 9, 11, 10])
        except Exception:
            pass
        col = {"open": "#8B5E1E", "done": "#1E6B33", "cancelled": "#888"}
        for i, r in enumerate(rows):
            it = self.olist.item(i, 7)
            if it is not None:
                it.setForeground(QtGui.QColor(col.get(r["status"], "#333")))
            sh = self.olist.item(i, 5)
            if sh is not None and r["short"]:
                sh.setForeground(QtGui.QColor("#a4262c"))
        self.tabs.setTabText(1, f"📋 الطلبات المحفوظة ({n_open} مفتوح)")
        target = select_id
        if target is None and rows:
            target = rows[0]["id"]
        for i, r in enumerate(rows):
            if r["id"] == target:
                # setCurrentCell لا selectRow: في الواجهة العربية (RTL)
                # يقيس selectRow عموده من حافّةٍ خارج الجدول فلا يحدّد شيئاً
                self.olist.setCurrentCell(i, 0)
                break
        if not rows:
            self.prev.clear()
            self.prev_head.setText("لا طلبات بهذا البحث")
            return
        # صراحةً: إن بقي التحديد على صفّه نفسه لا تُطلق Qt إشارة تغييره،
        # فتبقى المعاينة على حالٍ قديمة (حالةٌ تبدّلت مثلاً)
        self._preview_selected()

    def show_order(self, order_id):
        """يفتح على طلبٍ بعينه في «الطلبات المحفوظة» معايَناً بصوره."""
        self.l_search.blockSignals(True)
        self.l_search.clear()
        self.l_search.blockSignals(False)
        self.st_filter.blockSignals(True)
        self.st_filter.setCurrentIndex(max(0, self.st_filter.findData("all")))
        self.st_filter.blockSignals(False)
        self.tabs.setCurrentIndex(1)
        self.refresh_list(select_id=int(order_id))

    def _sel_id(self):
        r = self.olist.currentRow()
        rows = getattr(self, "_orders", [])
        return rows[r]["id"] if 0 <= r < len(rows) else None

    def _with_sel(self, fn):
        oid = self._sel_id()
        if oid is None:
            info(self, "اختر طلباً من القائمة أولاً")
            return
        fn(oid)

    def _preview_selected(self):
        oid = self._sel_id()
        self.prev.clear()
        if oid is None:
            return
        with db(readonly=True) as conn:
            o = mo.get_order(conn, oid)
        if not o:
            return
        from html import escape as _x
        self.prev_head.setText(
            f"<b>{_x(o['order_no'])}</b> — العميل: <b>"
            f"{_x(o['customer_name'])}</b> · {o['order_date']}"
            + (f" · التسليم {o['due_date']}" if o.get("due_date") else "")
            + f" · {o['models']} موديل · <b>{o['pieces']}</b> قطعة"
            + (f" · <span style='color:#a4262c'>للتصنيع {o['short']}"
               "</span>" if o["short"] else "")
            + f" · <i>{o['status_label']}</i>"
            + (f"<br>ملاحظات: {_x(o['notes'])}" if o.get("notes") else ""))
        for ln in o["lines"]:
            it = QtWidgets.QListWidgetItem(
                _icon(ln["model"], self.PREV_ICON),
                f"{ln['model']}  ×  {ln['qty']}"
                + (f"\n{ln['note']}" if ln.get("note") else ""))
            it.setTextAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)
            it.setToolTip(f"بالخزنة {ln['in_count']}"
                          + (f" · للتصنيع {ln['short']}" if ln["short"]
                             else " · متوفّر"))
            self.prev.addItem(it)

    def _open_selected(self):
        oid = self._sel_id()
        if oid is None:
            info(self, "اختر طلباً من القائمة أولاً")
            return
        if self._dirty and self.lines.rowCount() and \
                oid != self._order_id:
            if not ask(self, "في الطلب المفتوح للتعديل تغييرٌ لم يُحفظ —"
                             " تجاهله وفتح هذا الطلب؟"):
                return
        self.load_order(oid)

    def _set_status(self, status):
        oid = self._sel_id()
        if oid is None:
            info(self, "اختر طلباً من القائمة أولاً")
            return
        try:
            with db() as conn:
                mo.set_status(conn, oid, status, self.user.get("username"))
            self.refresh_list(select_id=oid)
        except Exception as e:
            err(self, e)

    def _delete(self):
        oid = self._sel_id()
        if oid is None:
            info(self, "اختر طلباً من القائمة أولاً")
            return
        if not ask(self, "حذف الطلب المحدَّد؟\n\nيختفي من القائمة ويبقى أثره"
                         " في سجل التتبع."):
            return
        try:
            with db() as conn:
                mo.delete_order(conn, oid, self.user.get("username"))
            if oid == self._order_id:
                self.new_order(ask_first=False)
                self.tabs.setCurrentIndex(1)
            self.refresh_list()
        except Exception as e:
            err(self, e)

    def _share(self, oid):
        with db(readonly=True) as conn:
            o = mo.get_order(conn, oid)
        if not o:
            return
        QtWidgets.QApplication.clipboard().setText(mo.share_text(o))
        info(self, "نُسخ الطلب نصّاً — الصقه في واتساب.\n\n"
                   "ولإرسال الصور: «🖨 معاينة وطباعة» ثم «حفظ بصيغة PDF».")

    # ══════════════════════════════════════════════════════════════
    #  الطباعة
    # ══════════════════════════════════════════════════════════════
    def _ask_print_options(self):
        from services.print_manager import photo_grid
        from ui.widgets.common import load_pref, photo_bg_choice, save_pref
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("طباعة الطلب بالصور")
        bgc = photo_bg_choice(dlg)
        dlg._bg_choice = bgc
        dlg.setMinimumWidth(420)
        per = QtWidgets.QSpinBox()
        per.setRange(1, 60)
        try:
            per.setValue(int(load_pref("orders.per_page", "4") or 4))
        except Exception:
            per.setValue(4)
        stock = QtWidgets.QCheckBox(
            "ورقة الورشة: تحت كل صورة ما بالخزنة منه وما يلزم تصنيعه")
        stock.setChecked(load_pref("orders.show_stock", "0") == "1")
        grid = QtWidgets.QLabel()
        grid.setObjectName("cardSub")
        grid.setWordWrap(True)

        def _grid(v):
            c, r, cw, ch = photo_grid(v, height_mm=240.0)
            grid.setText(f"الصفحة: {c} × {r} — كل صورة نحو "
                         f"{min(cw, ch - 16):.0f} ملم، وتحتها اسم الموديل "
                         "والعدد المطلوب. واسم العميل ورقم الطلب أعلى كل"
                         " صفحة.")
        per.valueChanged.connect(_grid)
        _grid(per.value())
        box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        box.button(QtWidgets.QDialogButtonBox.Ok).setText("معاينة وطباعة")
        box.button(QtWidgets.QDialogButtonBox.Cancel).setText("إلغاء")
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        f = QtWidgets.QFormLayout(dlg)
        f.addRow("عدد الصور في الصفحة:", per)
        f.addRow(grid)
        f.addRow("الصور:", bgc)
        f.addRow(stock)
        f.addRow(box)
        self._print_dlg = dlg
        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return None
        u = self.user.get("username")
        save_pref("orders.per_page", str(per.value()), u)
        save_pref("orders.show_stock", "1" if stock.isChecked() else "0", u)
        bgc.remember(u)
        return per.value(), stock.isChecked(), bgc.with_bg()

    def print_order(self, order_id):
        try:
            opts = self._ask_print_options()
            if not opts:
                return
            from services import print_manager
            print_manager.preview_document(
                self, "model_order", int(order_id), per_page=opts[0],
                show_stock=opts[1], with_bg=opts[2])
        except Exception as e:
            err(self, e)

    def print_production(self):
        try:
            from services import print_manager
            print_manager.preview_document(self, "orders_production", 0)
        except Exception as e:
            err(self, e)

    def closeEvent(self, e):
        if self._dirty and self.lines.rowCount():
            if not ask(self, "في الطلب تغييرٌ لم يُحفظ — إغلاق النافذة"
                             " بدون حفظه؟"):
                e.ignore()
                return
        self._icon_timer.stop()
        super().closeEvent(e)

    def reject(self):
        # Esc يمرّ بالسؤال نفسه عن التغيير غير المحفوظ
        if self._dirty and self.lines.rowCount():
            if not ask(self, "في الطلب تغييرٌ لم يُحفظ — إغلاق النافذة"
                             " بدون حفظه؟"):
                return
        self._icon_timer.stop()
        super().reject()
