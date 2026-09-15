# -*- coding: utf-8 -*-
"""تخصيص بطاقات لوحة التحكم.

يتيح للمستخدم بناء لوحة تحكم تناسب عمله: يضبط عرض كل بطاقة وارتفاعها
وترتيبها، ويضيف بطاقة لأي حساب من دليل الحسابات.

**لماذا هذا مهم في نظام محاسبي**: كل مصنع يراقب أرقاماً مختلفة —
واحد يهمّه الذهب عند العملاء، وآخر مديونية الموردين. لوحة ثابتة تفرض
رؤية واحدة على الجميع.
"""
import json
from pathlib import Path

from PyQt5 import QtCore, QtWidgets

CONFIG_FILE = "dashboard_cards.json"

# القيم الافتراضية للبطاقة (بوحدات الشبكة والبكسل)
DEFAULT_SPAN = 1          # عدد أعمدة الشبكة التي تشغلها
DEFAULT_HEIGHT = 0        # 0 = الارتفاع التلقائي
COLUMNS = 4               # أعمدة الشبكة


def config_path():
    import config as _cfg
    d = Path(_cfg.BASE_DIR) / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d / CONFIG_FILE


def load_config():
    """يقرأ إعدادات البطاقات — الترتيب والأحجام والبطاقات المخصّصة."""
    try:
        p = config_path()
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {
                    "order": list(data.get("order") or []),
                    "sizes": dict(data.get("sizes") or {}),
                    "custom": list(data.get("custom") or []),
                    "combos": list(data.get("combos") or []),
                    "hidden": list(data.get("hidden") or []),
                    "columns": int(data.get("columns") or COLUMNS),
                }
    except Exception:
        pass
    return {"order": [], "sizes": {}, "custom": [], "combos": [],
            "hidden": [], "columns": COLUMNS}


def save_config(cfg):
    try:
        config_path().write_text(
            json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        return True
    except Exception:
        return False


class ComboCardDialog(QtWidgets.QDialog):
    """إنشاء لوحة مركّبة: اسم + ثلاثة حسابات + نسبتان محسوبتان.

    **الغرض الإداري**: مقارنة ثلاثة أرقام مترابطة في بطاقة واحدة مع
    نسبتيهما — مثل: الذهب عند العملاء ÷ الذهب المشغول (نسبة التوزيع)،
    ثم المحصَّل ÷ المستحق (نسبة التحصيل).

        النسبة الأولى = الحساب الثاني ÷ الحساب الأول
        النسبة الثانية = الحساب الثالث ÷ الحساب الثاني
    """

    def __init__(self, parent, accounts, existing=None):
        super().__init__(parent)
        self.setWindowTitle("لوحة مركّبة (ثلاثة حسابات)")
        self.setMinimumWidth(520)
        self.accounts = accounts

        self.title = QtWidgets.QLineEdit()
        self.title.setPlaceholderText("اسم اللوحة — مثل: نسبة التوزيع")
        self.combos = []
        form = QtWidgets.QFormLayout()
        form.addRow("اسم اللوحة:", self.title)
        for i, lbl in enumerate(("الحساب الأول:", "الحساب الثاني:",
                                 "الحساب الثالث:")):
            cb = QtWidgets.QComboBox()
            cb.setEditable(True)
            cb.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
            for a in accounts:
                cb.addItem(f"{a['code']} — {a['name']}", a["code"])
            self.combos.append(cb)
            form.addRow(lbl, cb)

        self.mode = QtWidgets.QComboBox()
        self.mode.addItem("الذهب (جم)", "gold")
        self.mode.addItem("النقد (ريال)", "cash")
        form.addRow("البعد المعروض:", self.mode)

        note = QtWidgets.QLabel(
            "تُعرض النسبة الأولى بعد الحساب الثاني مباشرةً:\n"
            "    الثاني ÷ الأول × 100\n"
            "والنسبة الثانية بعد الحساب الثالث:\n"
            "    الثالث ÷ الثاني × 100")
        note.setObjectName("cardSub")
        note.setWordWrap(True)

        box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save
            | QtWidgets.QDialogButtonBox.Cancel)
        box.accepted.connect(self._ok)
        box.rejected.connect(self.reject)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(note)
        lay.addWidget(box)

        if existing:
            self.title.setText(existing.get("title", ""))
            for cb, code in zip(self.combos, existing.get("codes", [])):
                i = cb.findData(code)
                if i >= 0:
                    cb.setCurrentIndex(i)
            i = self.mode.findData(existing.get("mode", "gold"))
            if i >= 0:
                self.mode.setCurrentIndex(i)

    def _ok(self):
        if not self.title.text().strip():
            QtWidgets.QMessageBox.warning(self, "تنبيه", "أدخل اسم اللوحة")
            return
        codes = [c.currentData() for c in self.combos]
        if any(not x for x in codes):
            QtWidgets.QMessageBox.warning(self, "تنبيه",
                                          "اختر الحسابات الثلاثة")
            return
        self.accept()

    def result(self):
        return {
            "title": self.title.text().strip(),
            "codes": [c.currentData() for c in self.combos],
            "names": [
                next((a["name"] for a in self.accounts
                      if a["code"] == c.currentData()), c.currentData())
                for c in self.combos],
            "mode": self.mode.currentData() or "gold",
        }


class CardSettingsDialog(QtWidgets.QDialog):
    """حوار التحكم الكامل: الترتيب · الحجم · الإظهار · حسابات مخصّصة."""

    def __init__(self, parent, cards, cfg, accounts):
        super().__init__(parent)
        self.setWindowTitle("تخصيص لوحات لوحة التحكم")
        self.setMinimumSize(620, 480)
        self.cfg = {
            "order": list(cfg.get("order") or []),
            "sizes": dict(cfg.get("sizes") or {}),
            "custom": list(cfg.get("custom") or []),
            "combos": list(cfg.get("combos") or []),
            "hidden": list(cfg.get("hidden") or []),
            "columns": int(cfg.get("columns") or COLUMNS),
        }
        self.cards = cards            # [(key, label)]
        self.accounts = accounts      # [{id, code, name}]

        # ── قائمة الترتيب ──
        self.lst = QtWidgets.QListWidget()
        self.lst.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.lst.currentRowChanged.connect(self._on_select)
        self._fill_list()

        # ── ضوابط الحجم ──
        # العرض بأنصاف الأعمدة: نصف · 1 · 1.5 · 2 … حتى 4
        # يُخزَّن مضاعفاً بـ2 (نصف = 1، عمود = 2) فالشبكة تعمل
        # بأعمدة صحيحة مضاعفة.
        self.span = QtWidgets.QDoubleSpinBox()
        self.span.setRange(0.5, 4.0)
        self.span.setSingleStep(0.5)
        self.span.setDecimals(1)
        self.span.setSuffix("  عمود")
        self.span.setToolTip(
            "عرض البطاقة: 0.5 = نصف عمود · 1 = عمود · 2 = عمودان")
        self.span.valueChanged.connect(self._apply_size)
        self.height = QtWidgets.QSpinBox()
        self.height.setRange(0, 400)
        self.height.setSingleStep(10)
        self.height.setSuffix("  بكسل")
        self.height.setSpecialValueText("تلقائي")
        self.height.setToolTip("ارتفاع البطاقة — صفر يعني التلقائي")
        self.height.valueChanged.connect(self._apply_size)
        self.visible = QtWidgets.QCheckBox("إظهار البطاقة")
        self.visible.stateChanged.connect(self._apply_visible)

        self.columns = QtWidgets.QSpinBox()
        self.columns.setRange(2, 6)
        self.columns.setValue(self.cfg["columns"])
        self.columns.setSuffix("  بكل صف")

        form = QtWidgets.QFormLayout()
        form.addRow("عرض البطاقة:", self.span)
        form.addRow("ارتفاع البطاقة:", self.height)
        form.addRow("", self.visible)
        form.addRow("أعمدة الشبكة:", self.columns)

        # ── إضافة حساب ──
        self.acc = QtWidgets.QComboBox()
        self.acc.setEditable(True)
        self.acc.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        for a in accounts:
            self.acc.addItem(f"{a['code']} — {a['name']}", a["code"])
        btn_add = QtWidgets.QPushButton("➕ إضافة بطاقة لهذا الحساب")
        btn_add.clicked.connect(self._add_custom)
        btn_del = QtWidgets.QPushButton("🗑 حذف البطاقة")
        btn_del.clicked.connect(self._del_custom)
        btn_combo = QtWidgets.QPushButton("➕ لوحة مركّبة (3 حسابات)")
        btn_combo.setToolTip("اسم + ثلاثة حسابات + نسبتان محسوبتان")
        btn_combo.clicked.connect(self._add_combo)

        arow = QtWidgets.QHBoxLayout()
        arow.addWidget(self.acc, 1)
        arow.addWidget(btn_add)
        arow.addWidget(btn_del)
        arow.addWidget(btn_combo)

        note = QtWidgets.QLabel(
            "اسحب البطاقة لتغيير ترتيبها · اخترها لضبط حجمها · "
            "أضف بطاقة لأي حساب من الدليل.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)

        btn_reset = QtWidgets.QPushButton("↺ الترتيب الافتراضي")
        btn_reset.clicked.connect(self._reset)
        box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save
            | QtWidgets.QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        brow = QtWidgets.QHBoxLayout()
        brow.addWidget(btn_reset)
        brow.addStretch(1)
        brow.addWidget(box)

        left = QtWidgets.QVBoxLayout()
        left.addWidget(QtWidgets.QLabel("ترتيب البطاقات:"))
        left.addWidget(self.lst, 1)
        right = QtWidgets.QVBoxLayout()
        right.addLayout(form)
        right.addStretch(1)
        mid = QtWidgets.QHBoxLayout()
        mid.addLayout(left, 3)
        mid.addLayout(right, 2)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(note)
        lay.addLayout(mid, 1)
        lay.addWidget(QtWidgets.QLabel("إضافة بطاقة لحساب من الدليل:"))
        lay.addLayout(arow)
        lay.addLayout(brow)
        if self.lst.count():
            self.lst.setCurrentRow(0)

    # ── القائمة ──
    def _all_entries(self):
        """كل البطاقات: الثابتة ثم المخصّصة."""
        out = list(self.cards)
        for c in self.cfg["custom"]:
            out.append((f"acc:{c['code']}",
                        f"{c['code']} — {c['name']}"))
        for c in self.cfg.get("combos", []):
            out.append((f"combo:{c['title']}",
                        f"◆ {c['title']} (مركّبة)"))
        return out

    def _fill_list(self):
        self.lst.clear()
        entries = dict(self._all_entries())
        order = [k for k in self.cfg["order"] if k in entries]
        for k, _lbl in self._all_entries():
            if k not in order:
                order.append(k)
        for k in order:
            it = QtWidgets.QListWidgetItem(entries[k])
            it.setData(QtCore.Qt.UserRole, k)
            self.lst.addItem(it)

    def _current_key(self):
        it = self.lst.currentItem()
        return it.data(QtCore.Qt.UserRole) if it else None

    def _on_select(self, *_):
        k = self._current_key()
        if not k:
            return
        sz = self.cfg["sizes"].get(k, {})
        self.span.blockSignals(True)
        self.span.setValue(float(sz.get("span", DEFAULT_SPAN)))
        self.span.blockSignals(False)
        self.height.blockSignals(True)
        self.height.setValue(int(sz.get("height", DEFAULT_HEIGHT)))
        self.height.blockSignals(False)
        self.visible.blockSignals(True)
        self.visible.setChecked(k not in self.cfg["hidden"])
        self.visible.blockSignals(False)

    def _apply_size(self, *_):
        k = self._current_key()
        if not k:
            return
        self.cfg["sizes"][k] = {"span": float(self.span.value()),
                                "height": int(self.height.value())}

    def _apply_visible(self, *_):
        k = self._current_key()
        if not k:
            return
        hidden = set(self.cfg["hidden"])
        if self.visible.isChecked():
            hidden.discard(k)
        else:
            hidden.add(k)
        self.cfg["hidden"] = sorted(hidden)

    # ── البطاقات المخصّصة ──
    def _add_custom(self):
        code = self.acc.currentData()
        if not code:
            txt = self.acc.currentText().strip()
            code = txt.split("—")[0].strip() if "—" in txt else txt
        if not code:
            return
        if any(c["code"] == code for c in self.cfg["custom"]):
            QtWidgets.QMessageBox.information(
                self, "موجود", "توجد بطاقة لهذا الحساب مسبقاً.")
            return
        name = next((a["name"] for a in self.accounts
                     if a["code"] == code), code)
        self.cfg["custom"].append({"code": code, "name": name})
        self.cfg["order"] = self._read_order() + [f"acc:{code}"]
        self._fill_list()

    def _del_custom(self):
        """يحذف البطاقة المحددة — المخصّصة تُحذف، والأساسية تُخفى."""
        k = self._current_key()
        if not k:
            return
        if not str(k).startswith(("acc:", "combo:")):
            # البطاقة الأساسية تُخفى (لا تُحذف فقد تُطلب لاحقاً)
            hidden = set(self.cfg["hidden"])
            hidden.add(k)
            self.cfg["hidden"] = sorted(hidden)
            self.visible.setChecked(False)
            QtWidgets.QMessageBox.information(
                self, "أُخفيت",
                "أُخفيت البطاقة الأساسية. لإعادتها ضع علامة "
                "«إظهار البطاقة».")
            return
        if str(k).startswith("combo:"):
            title = str(k)[6:]
            self.cfg["combos"] = [c for c in self.cfg.get("combos", [])
                                  if c.get("title") != title]
            self.cfg["order"] = [x for x in self._read_order() if x != k]
            self._fill_list()
            return
        code = str(k)[4:]
        self.cfg["custom"] = [c for c in self.cfg["custom"]
                              if c["code"] != code]
        self.cfg["order"] = [x for x in self._read_order() if x != k]
        self._fill_list()

    def _add_combo(self):
        """ينشئ لوحة مركّبة بثلاثة حسابات ونسبتين."""
        dlg = ComboCardDialog(self, self.accounts)
        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return
        r = dlg.result()
        key = "combo:" + r["title"]
        self.cfg.setdefault("combos", [])
        self.cfg["combos"] = [c for c in self.cfg["combos"]
                              if c.get("title") != r["title"]]
        self.cfg["combos"].append(r)
        order = self._read_order()
        if key not in order:
            order.append(key)
        self.cfg["order"] = order
        self._fill_list()

    def _reset(self):
        self.cfg = {"order": [], "sizes": {}, "custom": [], "combos": [],
                    "hidden": [], "columns": COLUMNS}
        self.columns.setValue(COLUMNS)
        self._fill_list()

    def _read_order(self):
        return [self.lst.item(i).data(QtCore.Qt.UserRole)
                for i in range(self.lst.count())]

    def result_config(self):
        self.cfg["order"] = self._read_order()
        self.cfg["columns"] = int(self.columns.value())
        return self.cfg
