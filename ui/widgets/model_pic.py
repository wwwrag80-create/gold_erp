# -*- coding: utf-8 -*-
"""صورة الموديل — مشتركةٌ بين الشاشات (4.93).

`ModelPic`: الصورة مصغّرةً بجانب رقم الموديل في سطر الإدخال (التوريد ·
المبيعات والمرتجع) — ونقرةٌ تكبّرها. و`thumb`: مصغّرةٌ للجداول والنوافذ
تُقرأ من القرص مرةً وتُحفظ في الذاكرة.
"""
import os

from PyQt5 import QtCore, QtGui, QtWidgets

from models import models_catalog as mc

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


class ModelPic(QtWidgets.QLabel):
    """صورة الموديل مصغّرةً بجانب رقمه في سطر التوريد — ونقرةٌ تكبّرها.

    تُفكّ الصورة بحجمها الصغير مباشرة (`QImageReader.setScaledSize`) لا
    كاملةً ثم تُصغَّر: صورة الهاتف كاملةً عشرات الملايين من النقاط، وفكّها
    مع كل حرفٍ يُكتب يُبطئ الكتابة. ويُحفظ آخر ما عُرض فلا يُعاد فكّه."""

    clicked = QtCore.pyqtSignal()
    W, H = 64, 48

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.W, self.H)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setObjectName("modelPic")
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setStyleSheet("QLabel#modelPic{border:1px solid #c8bfae;"
                           "border-radius:4px;color:#8a8070;font-size:8pt}")
        self._key = None
        self.show_model("")

    def show_model(self, model_no):
        from models import models_catalog as mc
        no = str(model_no or "").strip()
        p = mc.image_path(no) if no else None
        try:
            key = (str(p), p.stat().st_mtime) if p else ("", no)
        except OSError:
            key = ("", no)
        if key == self._key:
            return
        self._key = key
        if p is None:
            self.setPixmap(QtGui.QPixmap())
            self.setText("لا صورة" if no else "الصورة")
            self.setToolTip(f"لا صورة محفوظة للموديل {no}" if no else
                            "صورة الموديل تظهر هنا حين يُكتب رقمه")
            return
        r = QtGui.QImageReader(str(p))
        r.setAutoTransform(True)
        sz = r.size()
        if sz.isValid() and sz.width() > 0 and sz.height() > 0:
            r.setScaledSize(sz.scaled(self.W * 2, self.H * 2,
                                      QtCore.Qt.KeepAspectRatio))
        img = r.read()
        if img.isNull():
            self.setText("—")
            return
        pix = QtGui.QPixmap.fromImage(img).scaled(
            self.W - 2, self.H - 2, QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation)
        self.setText("")
        self.setPixmap(pix)
        self.setToolTip(f"الموديل {no} — انقر لتكبير الصورة")

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)
