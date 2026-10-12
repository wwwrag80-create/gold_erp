# -*- coding: utf-8 -*-
"""استوديو صورة الموديل (4.63) — تحسينٌ بالعين قبل الحفظ.

يمين النافذة **الأصل** كما أُضيف، ويسارها **بعد التحسين** كما سيظهر في
الدليل والطباعة والرابط — يتبدّل مع كل حركة منزلق. وفيها:
  · نوع الصورة: رسمٌ ممسوح أو صورةٌ فوتوغرافية (يُعرف تلقائياً).
  · قوة الخط والظل، وتبييض الورق.
  · **تظليل القطعة** (4.64): رماديٌّ موحّد داخل قطع الطقم وحدها — لا
    إطار ولا خلفية — فيبرز الخطّ والفصوص؛ و«سدّ الفراغات» لرسمٍ حدوده
    منقّطة أو متقطّعة.
  · محو الكتابة الملوّنة، وحافّة الماسح السوداء، ونقاط الغبار.
  · القصّ على الرسم (التناسب)، والخلفية الشفافة.
  · التدوير: ربع دورة، أو بالدرجة لرسمٍ مُسح مائلاً.
  · **الممحاة**: تمرّ بالفأرة على الأصل فتمحو ما لا يُراد (رقمٌ مطبوع،
    ملاحظةٌ بالقلم، بقعة) — وتُحفظ مع الضبط فيُعاد فتحه كما تُرك.

الحفظ يعالج الأصل بدقّته الكاملة، والأصل لا يُمسّ — يُستعاد بنقرة.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from models import models_catalog as mc
from services import cutout as _co
from services import enhance as en

PREVIEW_SIDE = 820       # المعاينة على نسخةٍ أصغر — حركةٌ بلا انتظار


def _checker(w, h, cell=12):
    pm = QtGui.QPixmap(w, h)
    pm.fill(QtGui.QColor("#ffffff"))
    p = QtGui.QPainter(pm)
    c = QtGui.QColor("#eef1f5")
    for y in range(0, h, cell):
        for x in range(0, w, cell):
            if (x // cell + y // cell) % 2:
                p.fillRect(x, y, cell, cell, c)
    p.end()
    return pm


class _Canvas(QtWidgets.QLabel):
    """لوحة الأصل — والممحاة ترسم عليها بالفأرة."""

    stroke = QtCore.pyqtSignal(float, float, float)
    released = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setMinimumSize(380, 380)
        self.erasing = False
        self.brush = 18                  # نصف قطر الممحاة بالبكسل المعروض
        self._img = None
        self._rect = QtCore.QRect()

    def set_image(self, img, bg=None):
        self._img = img
        self._bg = bg
        self._render()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._render()

    def _render(self):
        if self._img is None or self.width() < 10:
            return
        s = self._img.scaled(self.width() - 8, self.height() - 8,
                             QtCore.Qt.KeepAspectRatio,
                             QtCore.Qt.SmoothTransformation)
        pm = self._bg(s.width(), s.height()) if self._bg else \
            QtGui.QPixmap(s.width(), s.height())
        if not self._bg:
            pm.fill(QtGui.QColor("#ffffff"))
        p = QtGui.QPainter(pm)
        p.drawImage(0, 0, s)
        p.end()
        self.setPixmap(pm)
        x = (self.width() - s.width()) // 2
        y = (self.height() - s.height()) // 2
        self._rect = QtCore.QRect(x, y, s.width(), s.height())

    def _emit(self, pos):
        r = self._rect
        if not r.contains(pos) or r.width() < 2:
            return
        nx = (pos.x() - r.x()) / float(r.width())
        ny = (pos.y() - r.y()) / float(r.height())
        nr = self.brush / float(max(r.width(), r.height()))
        self.stroke.emit(nx, ny, nr)

    def mousePressEvent(self, e):
        if self.erasing and e.button() == QtCore.Qt.LeftButton:
            self._emit(e.pos())

    def mouseMoveEvent(self, e):
        if self.erasing and e.buttons() & QtCore.Qt.LeftButton:
            self._emit(e.pos())

    def mouseReleaseEvent(self, e):
        if self.erasing:
            self.released.emit()


class ImageStudio(QtWidgets.QDialog):
    def __init__(self, parent, model_no, user=None):
        super().__init__(parent)
        self.model_no = model_no
        self.user = user or {}
        self.setWindowTitle(f"🎨 استوديو صورة الموديل {model_no}")
        self.resize(1240, 820)
        src = mc.original_path(model_no) or mc.image_path(model_no)
        if src is None:
            raise ValueError("لا توجد صورة لهذا الموديل")
        self.src_path = src
        self.full = en.load(src)
        self.small = en._cap(self.full, PREVIEW_SIDE)
        saved = (mc.image_meta(model_no) or {}).get("opts") or {}
        self.opts = en.options(**saved)
        self._groups = []                # كل سحبة ممحاة = مجموعة (للتراجع)
        self._cur_group = 0
        self._result = None

        self.before = _Canvas()
        self.before.stroke.connect(self._erase_at)
        self.before.released.connect(self._end_stroke)
        self.after = _Canvas()
        lb = QtWidgets.QLabel("الأصل — والممحاة تعمل هنا")
        la = QtWidgets.QLabel("بعد التحسين — كما يظهر في الدليل والطباعة")
        for l_ in (lb, la):
            l_.setObjectName("cardSub")
            l_.setAlignment(QtCore.Qt.AlignCenter)
        self.note = QtWidgets.QLabel("")
        self.note.setObjectName("cardSub")
        self.note.setProperty("live", True)
        self.note.setWordWrap(True)

        # ── الضبط ──
        self.mode = QtWidgets.QComboBox()
        for t, k in (("تلقائي", "auto"), ("رسمٌ ممسوح", "drawing"),
                     ("صورةٌ فوتوغرافية", "photo")):
            self.mode.addItem(t, k)
        self.strength = self._slider()
        self.paper = self._slider()
        self.shade = self._slider()
        self.shade.setToolTip("رماديٌّ داخل قطع الطقم وحدها — 0 بلا تظليل")
        self.reach = self._slider()
        self.reach.setToolTip("ارفعه إن بقي جزءٌ من قطعةٍ أبيض (حدودٌ"
                              " منقّطة)، واخفضه إن امتدّ الظلّ بين قطعٍ"
                              " منفصلة")
        self.c_color = QtWidgets.QCheckBox("محو الكتابة بالقلم الملوّن")
        self.c_edges = QtWidgets.QCheckBox("محو حافّة الماسح السوداء")
        self.c_speck = QtWidgets.QCheckBox("تنظيف نقاط الغبار")
        self.c_crop = QtWidgets.QCheckBox("قصٌّ على الرسم (التناسب)")
        self.c_trans = QtWidgets.QCheckBox("خلفية شفافة")
        self.rot = QtWidgets.QDoubleSpinBox()
        self.rot.setRange(-180.0, 180.0)
        self.rot.setSingleStep(0.5)
        self.rot.setDecimals(1)
        self.rot.setSuffix("°")
        b_left = QtWidgets.QToolButton()
        b_left.setText("↶ 90°")
        b_left.clicked.connect(lambda: self._turn(-90))
        b_right = QtWidgets.QToolButton()
        b_right.setText("↷ 90°")
        b_right.clicked.connect(lambda: self._turn(90))
        self.b_erase = QtWidgets.QPushButton("🧽 ممحاة")
        self.b_erase.setCheckable(True)
        self.b_erase.setToolTip("مرّر الفأرة على صورة الأصل لمحو رقمٍ أو"
                                " ملاحظةٍ أو بقعة")
        self.b_erase.toggled.connect(self._erase_mode)
        self.brush = QtWidgets.QSpinBox()
        self.brush.setRange(4, 80)
        self.brush.setValue(18)
        self.brush.setSuffix(" بكسل")
        self.brush.valueChanged.connect(
            lambda v: setattr(self.before, "brush", v))
        b_undo = QtWidgets.QPushButton("↩ تراجع عن المسح")
        b_undo.setObjectName("ghost")
        b_undo.clicked.connect(self._undo)
        b_clear = QtWidgets.QPushButton("مسح الممحاة كلها")
        b_clear.setObjectName("ghost")
        b_clear.clicked.connect(self._clear_erase)

        form = QtWidgets.QFormLayout()
        form.addRow("نوع الصورة:", self.mode)
        form.addRow("قوة الخط والظل:", self.strength)
        form.addRow("تبييض الورق:", self.paper)
        form.addRow("تظليل القطعة:", self.shade)
        form.addRow("سدّ الفراغات:", self.reach)
        for c in (self.c_color, self.c_edges, self.c_speck, self.c_crop,
                  self.c_trans):
            form.addRow(c)
        rot = QtWidgets.QHBoxLayout()
        rot.addWidget(b_left)
        rot.addWidget(b_right)
        rot.addWidget(self.rot, 1)
        form.addRow("التدوير:", rot)
        er = QtWidgets.QHBoxLayout()
        er.addWidget(self.b_erase)
        er.addWidget(self.brush)
        form.addRow("الممحاة:", er)
        er2 = QtWidgets.QHBoxLayout()
        er2.addWidget(b_undo)
        er2.addWidget(b_clear)
        form.addRow(er2)
        side = QtWidgets.QWidget()
        side.setLayout(form)
        side.setMaximumWidth(380)

        pics = QtWidgets.QGridLayout()
        pics.addWidget(lb, 0, 0)
        pics.addWidget(la, 0, 1)
        pics.addWidget(self.before, 1, 0)
        pics.addWidget(self.after, 1, 1)
        pics.setColumnStretch(0, 1)
        pics.setColumnStretch(1, 1)
        pics.setRowStretch(1, 1)

        b_reset = QtWidgets.QPushButton("↺ الضبط الافتراضي")
        b_reset.setObjectName("ghost")
        b_reset.clicked.connect(self._reset)
        self.b_save = QtWidgets.QPushButton("💾 حفظ الصورة المحسّنة")
        self.b_save.setObjectName("homeBtn")
        self.b_save.clicked.connect(self.save)
        b_cancel = QtWidgets.QPushButton("إلغاء")
        b_cancel.clicked.connect(self.reject)
        acts = QtWidgets.QHBoxLayout()
        acts.addWidget(self.b_save)
        acts.addWidget(b_cancel)
        acts.addStretch(1)
        acts.addWidget(b_reset)

        top = QtWidgets.QHBoxLayout()
        top.addLayout(pics, 1)
        top.addWidget(side)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(top, 1)
        lay.addWidget(self.note)
        lay.addLayout(acts)

        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(160)
        self._timer.timeout.connect(self._refresh)
        self._load_opts(self.opts)
        for w in (self.mode,):
            w.currentIndexChanged.connect(self._changed)
        for w in (self.strength, self.paper, self.shade, self.reach):
            w.valueChanged.connect(self._changed)
        for c in (self.c_color, self.c_edges, self.c_speck, self.c_crop,
                  self.c_trans):
            c.toggled.connect(self._changed)
        self.rot.valueChanged.connect(self._changed)
        self._show_source()
        self._refresh()

    @staticmethod
    def _slider():
        s = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        s.setRange(0, 100)
        return s

    # ── الضبط ↔ الخيارات ──
    def _load_opts(self, o):
        widgets = (self.mode, self.strength, self.paper, self.shade,
                   self.reach, self.c_color, self.c_edges, self.c_speck,
                   self.c_crop, self.c_trans, self.rot)
        for w in widgets:
            w.blockSignals(True)
        self.mode.setCurrentIndex(max(0, self.mode.findData(o["mode"])))
        self.strength.setValue(int(o["strength"]))
        self.paper.setValue(int(o["paper"]))
        self.shade.setValue(int(o.get("shade", 0)))
        self.reach.setValue(int(o.get("reach", 30)))
        self.c_color.setChecked(bool(o["remove_color"]))
        self.c_edges.setChecked(bool(o["remove_edges"]))
        self.c_speck.setChecked(bool(o.get("despeckle", True)))
        self.c_crop.setChecked(bool(o["crop"]))
        self.c_trans.setChecked(bool(o["transparent"]))
        self.rot.setValue(float(o["rotate"]))
        for w in widgets:
            w.blockSignals(False)
        self.erase = [tuple(x) for x in (o.get("erase") or [])]

    def current_opts(self):
        return en.options(
            mode=self.mode.currentData(), strength=self.strength.value(),
            paper=self.paper.value(), shade=self.shade.value(),
            reach=self.reach.value(), remove_color=self.c_color.isChecked(),
            remove_edges=self.c_edges.isChecked(),
            despeckle=self.c_speck.isChecked(), crop=self.c_crop.isChecked(),
            transparent=self.c_trans.isChecked(), rotate=self.rot.value(),
            erase=[list(x) for x in self.erase])

    def _changed(self, *_):
        self._timer.start()

    def _turn(self, d):
        v = self.rot.value() + d
        while v > 180:
            v -= 360
        while v < -180:
            v += 360
        self.rot.setValue(v)

    def _reset(self):
        self._load_opts(en.options())
        self._groups = []
        self._show_source()
        self._refresh()

    # ── الممحاة ──
    def _erase_mode(self, on):
        self.before.erasing = on
        self.before.setCursor(QtCore.Qt.CrossCursor if on
                              else QtCore.Qt.ArrowCursor)

    def _erase_at(self, x, y, r):
        if self._cur_group == 0:
            self._groups.append(len(self.erase))     # بداية سحبة جديدة
            self._cur_group = 1
        self.erase.append((round(x, 5), round(y, 5), round(r, 5)))
        self._show_source()

    def _end_stroke(self):
        self._cur_group = 0
        self._changed()

    def _undo(self):
        if self._groups:
            self.erase = self.erase[:self._groups.pop()]
        elif self.erase:
            self.erase = []
        self._show_source()
        self._changed()

    def _clear_erase(self):
        self.erase = []
        self._groups = []
        self._show_source()
        self._changed()

    def _show_source(self):
        img = en._apply_erase(en._on_white(self.small), self.erase)
        self.before.set_image(img)

    # ── المعاينة والحفظ ──
    def _refresh(self):
        try:
            out, mode, note = en.process(self.small, self.current_opts())
            self._result = (mode, note)
            self.after.set_image(out, _checker if out.hasAlphaChannel()
                                 else None)
            kind = "رسمٌ ممسوح" if mode == "drawing" else "صورةٌ فوتوغرافية"
            self.note.setText(f"النوع: {kind} · {note}")
            self.b_save.setEnabled(True)
        except _co.CutoutError as e:
            self.after.set_image(en._on_white(self.small))
            self.note.setText(f"⚠ {e}")
            self.b_save.setEnabled(False)

    def save(self):
        from ui.widgets.common import busy, err
        try:
            opts = self.current_opts()
            with busy(self, "جارٍ حفظ الصورة المحسّنة…",
                      stage="استوديو الصورة"):
                out, mode, note = en.process(self.full, opts)
                opts["mode"] = mode if opts["mode"] == "auto" \
                    else opts["mode"]
                mc.save_studio(self.model_no, out, opts)
            self.saved_note = note
            self.accept()
        except Exception as e:                       # noqa: BLE001
            err(self, e)
