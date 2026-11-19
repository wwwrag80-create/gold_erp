# -*- coding: utf-8 -*-
"""نافذة «رمز المدير» (5.9): تُطلب عند كل تعديلٍ أو حذفٍ في البرنامج حين
يقفلهما المدير من رابطه — ويستدعيها `services.desk_guard`."""
from PyQt5 import QtCore, QtWidgets


def ask_manager_code(action):
    """يعيد الرمز المكتوب، أو None إن أُلغيت النافذة."""
    parent = QtWidgets.QApplication.activeWindow()
    dlg = QtWidgets.QInputDialog(parent)
    dlg.setWindowTitle("رمز المدير")
    dlg.setLayoutDirection(QtCore.Qt.RightToLeft)
    dlg.setInputMode(QtWidgets.QInputDialog.TextInput)
    dlg.setTextEchoMode(QtWidgets.QLineEdit.Password)
    dlg.setLabelText(f"🔒 {action} مقفلٌ برمز المدير.\n"
                     "اكتب رمز المدير للمتابعة:")
    dlg.setOkButtonText("متابعة")
    dlg.setCancelButtonText("إلغاء")
    if dlg.exec_() != QtWidgets.QDialog.Accepted:
        return None
    return dlg.textValue()
