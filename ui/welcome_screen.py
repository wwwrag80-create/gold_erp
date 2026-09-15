# -*- coding: utf-8 -*-
"""شاشة الترحيب — مساحة فارغة يتوسّطها شعار مصنع جاديت.

تظهر عند فتح النظام وعند إغلاق أي شاشة، فتبقى الواجهة نظيفة والتنقّل
عبر الشريط الجانبي الثابت على اليمين.
"""
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets

import config


class WelcomeScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.setObjectName("welcomeRoot")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setAlignment(QtCore.Qt.AlignCenter)
        lay.addStretch(1)

        logo = QtWidgets.QLabel()
        logo.setAlignment(QtCore.Qt.AlignCenter)
        path = getattr(config, "LOGO_GOLD_PATH", None) or \
            getattr(config, "LOGO_PATH", None)
        if path and Path(str(path)).exists():
            pix = QtGui.QPixmap(str(path))
            if not pix.isNull():
                logo.setPixmap(pix.scaledToWidth(
                    300, QtCore.Qt.SmoothTransformation))
        lay.addWidget(logo)

        name = QtWidgets.QLabel(config.COMPANY_NAME)
        name.setObjectName("welcomeName")
        name.setAlignment(QtCore.Qt.AlignCenter)
        lay.addWidget(name)

        sub = QtWidgets.QLabel(
            f"{config.COMPANY_NAME_EN}  ·  {getattr(config, 'COMPANY_TAGLINE', '')}")
        sub.setObjectName("welcomeSub")
        sub.setAlignment(QtCore.Qt.AlignCenter)
        lay.addWidget(sub)

        hint = QtWidgets.QLabel("اختر شاشة من القائمة على اليمين للبدء")
        hint.setObjectName("welcomeHint")
        hint.setAlignment(QtCore.Qt.AlignCenter)
        lay.addSpacing(18)
        lay.addWidget(hint)
        lay.addStretch(2)

    def refresh(self):
        pass
