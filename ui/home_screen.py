# -*- coding: utf-8 -*-
"""الشاشة الرئيسية (Index 0) — بوابة النظام ببطاقات كبيرة للوحدات.

تعمل كواجهة الدخول داخل الـQStackedWidget: بطاقات مصنّفة حسب دورة
العمل (العمليات اليومية · المخزون والتصنيع · الإدارة والتقارير)، وكل
بطاقة تنقل مباشرة إلى وحدتها. ويظل الشريط الجانبي متاحاً لمن يفضّله.
"""
from PyQt5 import QtCore, QtWidgets

from ui.widgets.common import title_label


class Tile(QtWidgets.QFrame):
    """بطاقة وحدة كبيرة قابلة للنقر."""

    clicked = QtCore.pyqtSignal()

    def __init__(self, icon, title, subtitle):
        super().__init__()
        self.setObjectName("tile")
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setMinimumSize(215, 112)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(3)
        top = QtWidgets.QHBoxLayout()
        ic = QtWidgets.QLabel(icon)
        ic.setObjectName("tileIcon")
        t = QtWidgets.QLabel(title)
        t.setObjectName("tileTitle")
        t.setWordWrap(True)
        top.addWidget(ic)
        top.addWidget(t, 1)
        sub = QtWidgets.QLabel(subtitle)
        sub.setObjectName("tileSub")
        sub.setWordWrap(True)
        lay.addLayout(top)
        lay.addWidget(sub)
        lay.addStretch(1)

    def mouseReleaseEvent(self, ev):
        if ev.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(ev)


class HomeScreen(QtWidgets.QWidget):
    def __init__(self, user, groups, on_open):
        """groups: [(عنوان المجموعة, [(أيقونة, عنوان, وصف, شاشة)])]"""
        super().__init__()
        self.user = user
        self.on_open = on_open

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        inner = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(inner)
        lay.setContentsMargins(18, 14, 18, 18)
        lay.setSpacing(14)

        hello = title_label(
            f"أهلاً {user.get('full_name') or user.get('username')} — "
            "اختر الوحدة التي تريد العمل عليها")
        lay.addWidget(hello)

        for gtitle, tiles in groups:
            if gtitle:
                lbl = QtWidgets.QLabel(gtitle)
                lbl.setObjectName("groupTitle")
                lay.addWidget(lbl)
            grid = QtWidgets.QGridLayout()
            grid.setSpacing(11)
            for i, (icon, title, sub, screen) in enumerate(tiles):
                tile = Tile(icon, title, sub)
                tile.clicked.connect(
                    lambda s=screen: self.on_open(s))
                grid.addWidget(tile, i // 4, i % 4)
            for c in range(4):
                grid.setColumnStretch(c, 1)
            lay.addLayout(grid)

        lay.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def refresh(self):
        pass
