# -*- coding: utf-8 -*-
"""إشعارٌ منبثق هادئ — يظهر أعلى النافذة ثم يتلاشى وحده.

للتأكيدات التي لا تحتاج قراراً («✔ حُدّثت الشاشة» · «✔ نُسخ») — فلا
يُوقف المستخدم نافذةٌ تنتظر «موافق» لخبرٍ لا يسأله شيئاً. أما الخطأ
وما يحتاج قراراً فيبقى نافذةً صريحة كما كان.
"""
from PyQt5 import QtCore, QtWidgets


def show(parent, text, ms=2200):
    """يعرض الإشعار فوق `parent` (أو نافذته العليا). يعيد الملصق."""
    try:
        win = parent.window() if parent is not None else None
    except Exception:
        win = None
    if win is None:
        return None
    old = win.findChild(QtWidgets.QLabel, "toast")
    if old is not None:
        old.deleteLater()
    lbl = QtWidgets.QLabel(str(text), win)
    lbl.setObjectName("toast")
    lbl.setAlignment(QtCore.Qt.AlignCenter)
    lbl.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
    lbl.adjustSize()
    lbl.resize(lbl.width() + 36, lbl.height() + 16)
    lbl.move((win.width() - lbl.width()) // 2, 70)
    eff = QtWidgets.QGraphicsOpacityEffect(lbl)
    eff.setOpacity(0.0)
    lbl.setGraphicsEffect(eff)
    lbl.show()
    lbl.raise_()

    fade_in = QtCore.QPropertyAnimation(eff, b"opacity", lbl)
    fade_in.setDuration(180)
    fade_in.setStartValue(0.0)
    fade_in.setEndValue(1.0)
    fade_out = QtCore.QPropertyAnimation(eff, b"opacity", lbl)
    fade_out.setDuration(420)
    fade_out.setStartValue(1.0)
    fade_out.setEndValue(0.0)
    fade_out.finished.connect(lbl.deleteLater)
    fade_in.start()
    QtCore.QTimer.singleShot(max(600, int(ms)), lbl, fade_out.start)
    lbl._anims = (fade_in, fade_out)
    return lbl
