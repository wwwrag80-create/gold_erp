# -*- coding: utf-8 -*-
"""نافذة «النسخ الاحتياطية والاسترجاع» — لكل مستخدمٍ على جهازه.

بيانات المصنع على جهازه وحده (لا سحابة منذ 4.29)، فالنسخ المحلية هي
شبكة الأمان الوحيدة، ويجب أن يصل إليها صاحب المصنع نفسه لا المدير:
آخر 20 نسخة بتاريخها وسببها، و«استرجاع» أيٍّ منها بضغطة — مع نسخةٍ
«قبل الاسترجاع» تُؤخذ تلقائياً فيُتراجَع عن الاسترجاع نفسه إن لزم.
"""
import os
import sys

from PyQt5 import QtCore, QtWidgets

from services import storage
from ui.widgets.common import ask, err, fill, info, make_table
from ui.widgets.table_fit import fit_columns

COLS = ["#", "التاريخ والوقت", "النوع", "الحجم (ك.ب)", "الملف"]


class BackupsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, user=None):
        super().__init__(parent)
        self.user = user or {}
        self.rows = []
        self.restored = False
        self.setWindowTitle("النسخ الاحتياطية والاسترجاع")
        self.setLayoutDirection(QtCore.Qt.RightToLeft)
        self.resize(980, 640)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setSpacing(10)
        self.head = QtWidgets.QLabel()
        self.head.setWordWrap(True)
        self.head.setObjectName("cardSub")
        lay.addWidget(self.head)

        self.table = make_table()
        self.table.itemDoubleClicked.connect(lambda *_: self.restore())
        lay.addWidget(self.table, 1)

        row = QtWidgets.QHBoxLayout()
        self.btn_now = QtWidgets.QPushButton("💾 نسخة الآن")
        self.btn_now.setObjectName("primary")
        self.btn_now.setMinimumHeight(40)
        self.btn_now.clicked.connect(self.backup_now)
        self.btn_restore = QtWidgets.QPushButton("♻ استرجاع النسخة المحددة")
        self.btn_restore.setMinimumHeight(40)
        self.btn_restore.clicked.connect(self.restore)
        self.btn_folder = QtWidgets.QPushButton("📂 فتح مجلد النسخ")
        self.btn_folder.clicked.connect(self.open_folder)
        self.btn_close = QtWidgets.QPushButton("إغلاق")
        self.btn_close.clicked.connect(self.reject)
        row.addWidget(self.btn_now)
        row.addWidget(self.btn_restore)
        row.addWidget(self.btn_folder)
        row.addStretch(1)
        row.addWidget(self.btn_close)
        lay.addLayout(row)
        self.load()

    def load(self):
        self.rows = storage.list_backups()
        fill(self.table, COLS,
             [(i + 1, r["when"], r.get("reason_label", ""),
               f"{r['size_kb']:,.1f}", r["name"])
              for i, r in enumerate(self.rows)])
        fit_columns(self.table, [5, 22, 16, 12, 45])
        if self.rows:
            self.table.selectRow(0)
        st = storage.status()
        last = (f"آخر نسخة تلقائية: {st['when']}" if st.get("when")
                else "النسخة التلقائية الأولى بعد دقيقة من التشغيل")
        self.head.setText(
            f"بياناتك محفوظة على هذا الجهاز وحده. تُؤخذ نسخة تلقائياً كل "
            f"{storage.BACKUP_EVERY_SEC // 60} دقيقة وعند الإغلاق — ويُحتفظ "
            f"بآخر {storage.KEEP_LAST} نسخة (المطابقة لسابقتها لا تُكرَّر). "
            f"المحفوظ الآن: {len(self.rows)} نسخة.  ·  {last}\n"
            f"المجلد: {storage.backup_dir()}")
        self.btn_restore.setEnabled(bool(self.rows))

    def backup_now(self):
        try:
            p = storage.make_backup("manual")
            if not p:
                raise ValueError("لا توجد قاعدة بيانات لنسخها")
            self.load()
            info(self, "أُخذت نسخة احتياطية الآن.")
        except Exception as e:                        # noqa: BLE001
            err(self, e)

    def restore(self):
        i = self.table.currentRow()
        if not (0 <= i < len(self.rows)):
            err(self, "اختر نسخة من الجدول أولاً")
            return
        r = self.rows[i]
        ok, why = storage.verify_backup(r["path"])
        if not ok:
            err(self, f"هذه النسخة لا تصلح للاسترجاع:\n{why}")
            return
        if not ask(self,
                   f"استرجاع نسخة {r['when']} ({r.get('reason_label', '')})؟"
                   f"\n\nفيها: {why}.\n\n"
                   "• تُستبدل بيانات النظام الحالية بمحتوى هذه النسخة.\n"
                   "• قبل الاستبدال تُؤخذ نسخة «قبل الاسترجاع» من الحالية، "
                   "فتستطيع الرجوع إليها من هذه القائمة.\n"
                   "• يُعاد تشغيل النظام بعدها ليقرأ البيانات المسترجعة."):
            return
        try:
            storage.restore(r["path"])
        except Exception as e:                        # noqa: BLE001
            err(self, e)
            return
        self.restored = True
        info(self, "تم الاسترجاع بنجاح.\n\nسيُعاد تشغيل النظام الآن.")
        self.accept()
        restart_app()

    def open_folder(self):
        try:
            from PyQt5 import QtGui
            QtGui.QDesktopServices.openUrl(
                QtCore.QUrl.fromLocalFile(str(storage.backup_dir())))
        except Exception as e:                        # noqa: BLE001
            err(self, e)


def restart_app():
    """يُعيد تشغيل البرنامج — فتُقرأ البيانات المسترجعة من أولها."""
    app = QtWidgets.QApplication.instance()
    try:
        exe = sys.executable
        args = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
        if not os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            QtCore.QProcess.startDetached(exe, list(args))
    except Exception:
        pass
    if app is not None:
        QtCore.QTimer.singleShot(0, app.quit)


def open_dialog(parent=None, user=None):
    dlg = BackupsDialog(parent, user)
    dlg.exec_()
    return dlg
