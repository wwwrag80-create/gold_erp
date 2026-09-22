# -*- coding: utf-8 -*-
"""شاشة دخولٍ بسيطة — احتياطٌ خلف بوابة الدخول.

البوابة (`ui.gate_window`) هي الواجهة المعتادة؛ وهذه تبقى نافذةً
صغيرة تُستعمل حين لا تُناسب الشاشةُ الكاملة (تشغيلٌ عن بُعد، أو
أداةٌ تفتح النظام بلا عرض). والمنطق واحدٌ في الحالين:
`services.login_flow`.
"""
from PyQt5 import QtCore, QtWidgets

import config
from ui.widgets.common import err, info, title_label


class LoginDialog(QtWidgets.QDialog):
    def __init__(self):
        super().__init__()
        self.user = None
        self.setWindowTitle("تسجيل الدخول")
        try:
            from services import app_icon
            app_icon.apply(window=self)
        except Exception:
            pass
        self.setModal(True)
        self.setMinimumWidth(400)

        self.username = QtWidgets.QLineEdit()
        self.username.setPlaceholderText("اسم المستخدم")
        self.password = QtWidgets.QLineEdit()
        self.password.setPlaceholderText("كلمة المرور")
        self.password.setEchoMode(QtWidgets.QLineEdit.Password)

        btn_login = QtWidgets.QPushButton("دخول")
        btn_login.setDefault(True)
        btn_login.clicked.connect(self.try_login)
        btn_exit = QtWidgets.QPushButton("خروج")
        btn_exit.setObjectName("ghost")
        btn_exit.clicked.connect(self.reject)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setSpacing(12)
        lay.addWidget(title_label(config.APP_NAME),
                      alignment=QtCore.Qt.AlignCenter)
        # لا تُعرض بيانات المدير — النسخة تصل لأيدي العملاء
        hint = QtWidgets.QLabel(
            "أدخل اسم المستخدم وكلمة المرور المُسلَّمين لك")
        hint.setAlignment(QtCore.Qt.AlignCenter)
        # بصمة البناء: تكشف فوراً إن كنت تشغّل نسخة قديمة
        stamp = QtWidgets.QLabel(
            f"الإصدار {config.APP_VERSION} — {config.BUILD_STAMP}")
        stamp.setObjectName("cardSub")
        stamp.setAlignment(QtCore.Qt.AlignCenter)
        lay.addWidget(hint)
        # سطر حالة الترخيص/الاتصال
        self.hint = QtWidgets.QLabel("")
        self.hint.setAlignment(QtCore.Qt.AlignCenter)
        self.hint.setObjectName("cardSub")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        lay.addWidget(stamp)
        form = QtWidgets.QFormLayout()
        form.addRow("اسم المستخدم:", self.username)
        form.addRow("كلمة المرور:", self.password)
        lay.addLayout(form)
        btns = QtWidgets.QHBoxLayout()
        btns.addWidget(btn_login)
        btns.addWidget(btn_exit)
        lay.addLayout(btns)
        self.password.returnPressed.connect(self.try_login)

    def try_login(self):
        """الدخول عبر مسار الدخول المشترك (`services.login_flow`).

        المنطق كلُّه هناك — التحقّق، وعزل بيانات المصنع، والاسترجاع
        السحابي — فلا تتباعد هذه الشاشة عن بوابة الدخول الجديدة.
        """
        from services import login_flow

        def say(msg):
            self.hint.setText(str(msg or ""))
            QtWidgets.QApplication.processEvents()

        try:
            session = login_flow.sign_in(
                self.username.text(), self.password.text(),
                on_progress=say,
                on_restored=lambda r: info(
                    self, "تم استرجاع بياناتك تلقائياً من النسخة "
                          f"السحابية.\n\nآخر نسخة: {r.get('when', '')}\n\n"
                          "كل محاسبتك السابقة متاحة الآن."))
        except Exception as e:                   # noqa: BLE001
            self.hint.setText("")
            err(self, str(e))
            return
        self.user = session
        self.accept()
