# -*- coding: utf-8 -*-
"""شاشة الترحيب — مساحة فارغة يتوسّطها شعار المصنع (من «هوية المصنع»).

تظهر عند فتح النظام وعند إغلاق أي شاشة، فتبقى الواجهة نظيفة والتنقّل
عبر الشريط الجانبي الثابت على اليمين.

**وهجٌ ساكن لا حركةٌ دائمة**: خلفُ الشعار تدرّجٌ ذهبيٌّ خافت يُرسم
مرةً ولا يتحرّك. هذه شاشةُ عملٍ تبقى مفتوحةً ساعات، وأي حركةٍ
مستمرة فيها تسرق النظر من الجداول وتُبقي وحدة المعالجة مشغولة بلا
عائد. الحركةُ كلُّها في البوابة، والراحةُ هنا.
"""
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets

import config


class _Glow(QtWidgets.QWidget):
    """هالةٌ ذهبية خلف الشعار — تُرسم ولا تتحرّك."""

    def paintEvent(self, _e):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        g = QtGui.QRadialGradient(w * 0.5, h * 0.42, max(w, h) * 0.42)
        c0 = QtGui.QColor("#C9A227")
        c0.setAlpha(26)
        c1 = QtGui.QColor("#C9A227")
        c1.setAlpha(0)
        g.setColorAt(0.0, c0)
        g.setColorAt(1.0, c1)
        p.fillRect(self.rect(), QtGui.QBrush(g))
        p.end()


class WelcomeScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.setObjectName("welcomeRoot")

        self.glow = _Glow(self)
        self.glow.lower()

        self.box = QtWidgets.QWidget(self)
        lay = QtWidgets.QVBoxLayout(self.box)
        lay.setAlignment(QtCore.Qt.AlignCenter)
        lay.addStretch(1)

        self.logo = QtWidgets.QLabel()
        self.logo.setAlignment(QtCore.Qt.AlignCenter)
        lay.addWidget(self.logo)

        self.name = QtWidgets.QLabel()
        self.name.setObjectName("welcomeName")
        self.name.setAlignment(QtCore.Qt.AlignCenter)
        lay.addWidget(self.name)

        self.sub = QtWidgets.QLabel()
        self.sub.setObjectName("welcomeSub")
        self.sub.setAlignment(QtCore.Qt.AlignCenter)
        lay.addWidget(self.sub)
        self.refresh_identity()

        hint = QtWidgets.QLabel(
            "اختر شاشة من القائمة على اليمين للبدء  ·  أو اضغط Ctrl+K "
            "للبحث الموحّد (اسم · رقم تشغيل · رقم فاتورة · اسم شاشة)")
        hint.setObjectName("welcomeHint")
        hint.setAlignment(QtCore.Qt.AlignCenter)
        hint.setWordWrap(True)
        lay.addSpacing(18)
        lay.addWidget(hint)
        lay.addStretch(2)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.box)

    def refresh_identity(self):
        """الشعار والاسم من «هوية المصنع» — يُعاد بعد اعتمادها."""
        path = getattr(config, "LOGO_GOLD_PATH", None) or \
            getattr(config, "LOGO_PATH", None)
        pix = QtGui.QPixmap(str(path)) if path and Path(str(path)).exists() \
            else QtGui.QPixmap()
        if pix.isNull():
            self.logo.clear()
            self.logo.hide()
        else:
            self.logo.setPixmap(pix.scaled(
                300, 220, QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation))
            self.logo.show()
        self.name.setText(config.COMPANY_NAME)
        self.sub.setText("  ·  ".join(
            x for x in (getattr(config, "COMPANY_NAME_EN", ""),
                        getattr(config, "COMPANY_TAGLINE", "")) if x))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.glow.setGeometry(self.rect())

    def play_entrance(self):
        """ظهورٌ صاعدٌ مرةً واحدة عند أول دخول — ثم يُرفع المؤثّر."""
        try:
            from ui.widgets.gold_stage import animations_on
            if not animations_on():
                return
        except Exception:
            return
        eff = QtWidgets.QGraphicsOpacityEffect(self.box)
        eff.setOpacity(0.0)
        self.box.setGraphicsEffect(eff)
        base = self.box.pos()
        anim = QtCore.QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(620)
        anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)

        def _step(v):
            f = float(v)
            eff.setOpacity(f)
            self.box.move(base.x(), base.y() + int(18 * (1 - f)))

        def _end():
            try:
                self.box.setGraphicsEffect(None)
                self.box.move(base)
            except Exception:
                pass

        anim.valueChanged.connect(_step)
        anim.finished.connect(_end)
        self._entrance = anim
        QtCore.QTimer.singleShot(160, anim.start)

    def refresh(self):
        pass
