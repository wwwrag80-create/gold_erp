# -*- coding: utf-8 -*-
"""شاشة تسجيل الدخول: التحقق عبر services.auth مع تسجيل المحاولات."""
from PyQt5 import QtCore, QtWidgets

import config
from services import auth
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

    def _bootstrap_tenant_db(self):
        """يُنشئ جداول المصنع وشجرة حساباته إن كانت قاعدته جديدة."""
        from database.database import (create_tables, db, migrate_schema,
                                       run_migrations_files)
        from database.seed import (ensure_new_accounts, ensure_system_tags,
                                   seed_initial_data)
        from models.entities import (ensure_employee_accrual_accounts,
                                     ensure_internal_counterparties)
        create_tables()
        migrate_schema()
        run_migrations_files()
        seed_initial_data()
        ensure_new_accounts()
        with db() as conn:
            ensure_internal_counterparties(conn)
            ensure_employee_accrual_accounts(conn)
            ensure_system_tags(conn)

    def try_login(self):
        """الدخول عبر السحابة (جدول factory_users) مع ذاكرة محلية.

        الحسابات تُدار مركزياً، والصلاحية (`role`) تُجلب مع الجلسة
        فتُخفى شاشات الإدارة تلقائياً عن المصانع.
        """
        from services import cloud_auth
        self.hint.setText("جارٍ التحقق…")
        QtWidgets.QApplication.processEvents()
        try:
            session = cloud_auth.login(self.username.text().strip(),
                                       self.password.text())
        except Exception as e:
            self.hint.setText("")
            msg = str(e)
            # أضف سبب الفشل الحقيقي بدل رسالة غامضة
            try:
                from services import cloud_auth
                d = cloud_auth.diagnose()
                if not (d["url"] and d["pub"]):
                    msg += ("\n\nالسبب: إعدادات السحابة ناقصة في هذه "
                            "النسخة.")
                elif not d["reachable"]:
                    msg += "\n\nالسبب: تعذّر الوصول للخادم — تحقق من الإنترنت."
                elif not d["table"]:
                    msg += f"\n\nالسبب: {d['message']}"
            except Exception:
                pass
            err(self, msg)
            return
        # صلاحيات النظام المحلي تُشتق من صلاحية الحساب السحابي
        session["role_local"] = ("accountant" if session["is_super"]
                                 else "accountant")
        # ══ عزل البيانات ══
        # تُضبط هوية المصنع فوراً بعد التحقق من الهوية، **قبل** أي
        # قراءة أو كتابة — فيُوجَّه النظام لقاعدة بيانات هذا المصنع
        # وحده ولا يرى بيانات أي مصنع آخر على الجهاز نفسه.
        try:
            from services import tenant_db
            tid = session.get("tenant_id") or ""
            if tid:
                tenant_db.set_active_tenant(tid)
                # أول دخول للمالك: تُنقل قاعدته القديمة المشتركة إليه
                if session.get("is_super"):
                    tenant_db.migrate_legacy_into(config.BASE_DIR, tid)
                # تهيئة قاعدة المصنع الجديد إن كانت فارغة
                self._bootstrap_tenant_db()
        except Exception as e:
            err(self, f"تعذّر تجهيز مساحة عمل المصنع: {e}")
            return

        # استرجاع تلقائي: نسخة جديدة عند مصنع له بيانات سحابية
        try:
            from services import cloud_backup
            self.hint.setText("جارٍ التحقق من بياناتك…")
            QtWidgets.QApplication.processEvents()
            r = cloud_backup.auto_restore_if_needed(
                on_progress=lambda m: (self.hint.setText(m),
                                       QtWidgets.QApplication
                                       .processEvents()))
            if r.get("done"):
                info(self, "تم استرجاع بياناتك تلقائياً من النسخة "
                           f"السحابية.\n\nآخر نسخة: {r.get('when', '')}\n\n"
                           "كل محاسبتك السابقة متاحة الآن.")
        except Exception:
            pass          # الاسترجاع لا يمنع الدخول أبداً
        if session.get("notice"):
            self.hint.setText(session["notice"])
        self.user = session
        self.accept()
