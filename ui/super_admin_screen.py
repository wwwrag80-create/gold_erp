# -*- coding: utf-8 -*-
"""لوحة المدير العام — الحسابات وإيقاف المصانع، وصيانة هذا الجهاز.

**منذ 4.29 لا تحمل السحابة أي بيانات لمصنع.** كل مصنع يعمل على جهازه
ويحفظ نسخه عليه، والمدير لا يرى بيانات أحد ولا «يدخل كـ» أحد (أُلغي
انتحال الشخصية مع إلغاء الرفع). ما بقي للمدير سحابياً:

* **الحسابات**: إنشاء حساب مصنع (أو مستخدم إضافي لمصنع قائم) وحذفه.
* **الإيقاف**: إيقاف حساب، أو المصنع كله بكل حساباته — فيتوقّف
  البرنامج عنده خلال دقائق (`services/licensing.AccountGuard`).

وتبويب «هذا الجهاز» لنسخ المدير المحلية وصيانة قاعدته — كأي مصنع.
"""
from PyQt5 import QtWidgets

from database.database import db
from services import licensing, tenant
from ui.widgets.common import (ask, big_label, err, fill, info, make_table,
                               title_label)
from ui.widgets.table_fit import fit_columns

USER_COLS = ["اسم المستخدم", "المصنع", "هوية المصنع", "الصلاحية", "الحالة"]


class SuperAdminScreen(QtWidgets.QWidget):
    # ══ رمز دخول الشاشة ══
    # هذه الشاشة تدير المصانع والنظام السحابي كله، فخطؤها يمسّ كل
    # العملاء لا مصنعاً واحداً. الرمز طبقة ثانية بعد تسجيل الدخول:
    # حتى لو تُرك الجهاز مفتوحاً لا تُفتح بنقرة.
    ACCESS_CODE = "alshabahi"
    _unlocked = False

    @classmethod
    def request_access(cls, parent=None):
        """يطلب رمز الدخول — مرة واحدة لكل تشغيل."""
        if cls._unlocked:
            return True
        from PyQt5 import QtWidgets as _W
        code, ok = _W.QInputDialog.getText(
            parent, "الإدارة العليا",
            "هذه الشاشة تدير النظام السحابي وكل المصانع.\n"
            "أدخل رمز الدخول للمتابعة:",
            _W.QLineEdit.Password)
        if not ok:
            return False
        if str(code).strip() != cls.ACCESS_CODE:
            _W.QMessageBox.warning(
                parent, "رمز غير صحيح",
                "رمز الدخول غير صحيح — لم تُفتح الشاشة.")
            return False
        cls._unlocked = True
        return True

    def __init__(self, user):
        super().__init__()
        self.user = user
        self.factories = []

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self._users_tab(), "الحسابات والمصانع")
        tabs.addTab(self._maint_tab(), "هذا الجهاز — النسخ والصيانة")

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("الإدارة العامة"))
        note = QtWidgets.QLabel(
            "كل مصنع يعمل على جهازه ويحفظ بياناته ونسخه عليه — لا يُرفع "
            "منها شيء ولا يُستقبل. السحابة فيها الحسابات وحالتها فقط: "
            "إنشاء المستخدمين وإيقاف المصانع من هنا.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addWidget(tabs, 1)

    def _users_tab(self):
        """إنشاء حسابات المصانع وإدارتها — للمدير العام حصراً."""
        w = QtWidgets.QWidget()
        self.nu_factory = QtWidgets.QLineEdit()
        self.nu_factory.setPlaceholderText("اسم المصنع")
        self.nu_user = QtWidgets.QLineEdit()
        self.nu_user.setPlaceholderText("اسم المستخدم")
        self.nu_pass = QtWidgets.QLineEdit()
        self.nu_pass.setPlaceholderText("كلمة المرور")
        self.nu_pass.setEchoMode(QtWidgets.QLineEdit.Password)
        self.nu_is_admin = QtWidgets.QCheckBox("حساب مدير عام")
        self.nu_is_admin.setToolTip(
            "المدير العام يرى شاشات الإدارة من أي نسخة")
        btn_new = QtWidgets.QPushButton("➕ إنشاء الحساب")
        btn_new.setObjectName("homeBtn")
        btn_new.clicked.connect(self.create_factory_user)
        btn_load = QtWidgets.QPushButton("↻ تحديث القائمة")
        btn_load.clicked.connect(self.load_users)
        btn_toggle = QtWidgets.QPushButton("⛔ إيقاف / تفعيل الحساب")
        btn_toggle.clicked.connect(self.toggle_user)
        btn_fac_stop = QtWidgets.QPushButton("⛔ إيقاف المصنع كاملاً")
        btn_fac_stop.setToolTip("يوقف كل حسابات المصنع المحدَّد — فيتوقّف "
                                "البرنامج عنده خلال دقائق")
        btn_fac_stop.clicked.connect(lambda: self.set_factory(False))
        btn_fac_go = QtWidgets.QPushButton("✔ تفعيل المصنع")
        btn_fac_go.clicked.connect(lambda: self.set_factory(True))
        btn_add = QtWidgets.QPushButton("➕ مستخدم إضافي لهذا المصنع")
        btn_add.setToolTip("حساب دخول ثانٍ لنفس المصنع المحدَّد")
        btn_add.clicked.connect(self.add_user_to_factory)
        btn_del = QtWidgets.QPushButton("🗑 حذف الحساب نهائياً")
        btn_del.setObjectName("ghost")
        btn_del.clicked.connect(self.delete_user)
        btn_purge = QtWidgets.QPushButton("🧹 حذف البيانات القديمة المرفوعة")
        btn_purge.setToolTip("يمسح من السحابة ما رفعته الإصدارات السابقة "
                             "من فواتير وقيود وسندات لكل المصانع")
        btn_purge.clicked.connect(self.purge_old_cloud_data)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("مصنع:"))
        row.addWidget(self.nu_factory, 2)
        row.addWidget(QtWidgets.QLabel("مستخدم:"))
        row.addWidget(self.nu_user, 2)
        row.addWidget(QtWidgets.QLabel("كلمة المرور:"))
        row.addWidget(self.nu_pass, 2)
        row.addWidget(self.nu_is_admin)
        row.addWidget(btn_new)

        btn_diag2 = QtWidgets.QPushButton("🔍 فحص الإعدادات")
        btn_diag2.setToolTip("يوضّح ما إذا كانت المفاتيح مقروءة فعلاً")
        btn_diag2.clicked.connect(self.check_keys)

        row2 = QtWidgets.QHBoxLayout()
        row2.addWidget(btn_load)
        row2.addWidget(btn_add)
        row2.addWidget(btn_toggle)
        row2.addWidget(btn_fac_stop)
        row2.addWidget(btn_fac_go)
        row2.addStretch(1)
        row3 = QtWidgets.QHBoxLayout()
        row3.addWidget(btn_del)
        row3.addWidget(btn_purge)
        row3.addWidget(btn_diag2)
        row3.addStretch(1)

        self.users_table = make_table()
        note = QtWidgets.QLabel(
            "الحساب الجديد يُنشأ بهوية مصنع فريدة، وكلمة المرور تُجزَّأ "
            "(PBKDF2) ولا تُخزَّن نصاً صريحاً. سلّم العميل نفس الملف "
            "التنفيذي واسم المستخدم وكلمة المرور — بياناته تبقى على جهازه، "
            "وتُخفى عنه شاشات الإدارة. الإيقاف يصل البرنامجَ خلال دقائق "
            "ويمنعه من الدخول ولو بلا إنترنت.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)

        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(note)
        lay.addLayout(row)
        lay.addLayout(row2)
        lay.addLayout(row3)
        lay.addWidget(self.users_table, 1)
        return w

    def check_keys(self):
        """يعرض حالة الإعدادات والاتصال بدقة."""
        try:
            from services import cloud_auth
            import app_config
            d = cloud_auth.diagnose()
            lines = [
                f"ملف الإعدادات: {app_config.ENV_FILE}",
                "",
                f"{'✔' if d['url'] else '✘'} رابط السحابة: "
                f"{d['url'] or 'غير مضبوط'}",
                f"{'✔' if d['pub'] else '✘'} المفتاح العام",
                f"{'✔' if d['reachable'] else '✘'} الاتصال بالخادم",
                f"{'✔' if d['rpc'] else '✘'} دوال الإدارة على الخادم",
                f"{'✔' if d.get('rpc_version') == d.get('expected') else '✘'}"
                f" إصدار الدوال: {d.get('rpc_version') or 'غير معروف'}"
                f" (المطلوب {d.get('expected')})",
                f"{'✔' if d['has_token'] else '—'} الرمز الإداري",
                "",
                d["message"],
            ]
            if not d["rpc"]:
                lines += [
                    "",
                    "الحل: افتح Supabase ← SQL Editor",
                    "ونفّذ الملف:  admin_rpc.sql",
                ]
            elif not d["has_token"]:
                lines += [
                    "",
                    "الخطوة التالية: ضع علامة «حساب مدير عام»",
                    "واكتب اسم مستخدم وكلمة مرور ثم اضغط «إنشاء الحساب».",
                ]
            info(self, "\n".join(lines))
        except Exception as e:
            err(self, e)

    def create_factory_user(self):
        try:
            from services import cloud_auth
            fac = self.nu_factory.text().strip()
            usr = self.nu_user.text().strip()
            pwd = self.nu_pass.text()
            if not (usr and pwd):
                raise ValueError("أدخل اسم المستخدم وكلمة المرور")
            if not self.nu_is_admin.isChecked() and not fac:
                raise ValueError("أدخل اسم المصنع")
            if self.nu_is_admin.isChecked():
                # اسم المصنع اختياري لحساب المدير — نضمن قيمة دائماً
                r = cloud_auth.create_admin(
                    usr, pwd, full_name=(fac or "الإدارة العامة"))
                info(self, f"أُنشئ حساب مدير عام: {r['username']}\n\n"
                           f"تستطيع الدخول به من أي نسخة، بما فيها "
                           f"الملف التنفيذي الموزَّع على العملاء.")
                self.nu_factory.clear()
                self.nu_user.clear()
                self.nu_pass.clear()
                self.nu_is_admin.setChecked(False)
                self.load_users()
                return
            r = cloud_auth.create_user(usr, pwd,
                                       role=cloud_auth.ROLE_FACTORY,
                                       full_name=fac, factory_name=fac)
            info(self, f"أُنشئ حساب المصنع «{fac}».\n\n"
                       f"اسم المستخدم : {r['username']}\n"
                       f"هوية المصنع  : {r['tenant_id']}\n\n"
                       f"سلّم العميل الملف التنفيذي مع اسم المستخدم "
                       f"وكلمة المرور فقط.")
            self.nu_factory.clear()
            self.nu_user.clear()
            self.nu_pass.clear()
            self.load_users()
        except Exception as e:
            err(self, e)

    def load_users(self):
        try:
            from services import cloud_auth
            self.users = cloud_auth.list_users()
            self._fill_users()
        except Exception as e:
            err(self, e)

    def _fill_users(self):
        """جدول الحسابات — حسابات المصنع الواحد متجاورة."""
        self.users = sorted(
            getattr(self, "users", []) or [],
            key=lambda u: (u.get("role") == "super_admin",
                           u.get("full_name") or "", u.get("username", "")))
        fill(self.users_table, USER_COLS,
             [(u.get("username", ""), u.get("full_name") or "—",
               u.get("tenant_id", ""),
               "المدير العام" if u.get("role") == "super_admin"
               else "مصنع",
               "نشط" if u.get("is_active") else "موقوف")
              for u in self.users])
        fit_columns(self.users_table, [20, 30, 24, 14, 12])

    def delete_user(self):
        """يحذف حساب مصنع نهائياً من السحابة."""
        try:
            from services import cloud_auth
            i = self.users_table.currentRow()
            if not (0 <= i < len(getattr(self, "users", []))):
                raise ValueError("اختر حساباً من الجدول")
            u = self.users[i]
            if u.get("role") == "super_admin":
                if not ask(self, "هذا حساب مدير عام.\n"
                                 "حذفه قد يمنعك من الدخول إن كان حسابك.\n\n"
                                 "متأكد؟"):
                    return
            if not ask(self, f"حذف حساب «{u.get('username')}» نهائياً؟\n\n"
                             f"لن يستطيع الدخول بعدها إطلاقاً.\n"
                             f"(بيانات مصنعه المحلية والسحابية تبقى كما هي)\n\n"
                             f"هذا الإجراء لا يمكن التراجع عنه."):
                return
            cloud_auth.delete_user(u.get("username"))
            info(self, f"حُذف حساب «{u.get('username')}» نهائياً.")
            self.load_users()
        except Exception as e:
            err(self, e)

    def toggle_user(self):
        try:
            from services import cloud_auth
            i = self.users_table.currentRow()
            if not (0 <= i < len(getattr(self, "users", []))):
                raise ValueError("اختر حساباً من الجدول")
            u = self.users[i]
            new_state = not bool(u.get("is_active"))
            word = "تفعيل" if new_state else "إيقاف"
            if not ask(self, f"{word} حساب «{u.get('username')}»؟"
                             + ("\n\nسيُمنع من الدخول عند أول اتصال."
                                if not new_state else "")):
                return
            cloud_auth.set_user_active(u.get("username"), new_state)
            info(self, f"تم {word} الحساب.")
            self.load_users()
        except Exception as e:
            err(self, e)

    def _selected_user(self):
        i = self.users_table.currentRow()
        if not (0 <= i < len(getattr(self, "users", []))):
            raise ValueError("اختر حساباً من الجدول")
        return self.users[i]

    def set_factory(self, active):
        """يوقف المصنع المحدَّد بكل حساباته أو يفعّله."""
        try:
            u = self._selected_user()
            if u.get("role") == "super_admin":
                raise ValueError("هذا حساب المدير العام — اختر حساب مصنع")
            tid = u.get("tenant_id")
            accts = licensing.factory_accounts(self.users, tid)
            name = u.get("full_name") or tid
            word = "تفعيل" if active else "إيقاف"
            names = "، ".join(a.get("username", "") for a in accts)
            if not ask(self, f"{word} المصنع «{name}» كاملاً؟\n\n"
                             f"حساباته: {names}\n\n"
                             + ("سيتوقّف البرنامج عنده خلال دقائق، ولا "
                                "يستطيع الدخول ولو بلا إنترنت.\n"
                                "بياناته على جهازه لا تُمسّ."
                                if not active else
                                "يستطيع الدخول والعمل من جديد.")):
                return
            n = licensing.set_factory_active(tid, active, users=self.users)
            info(self, f"تم {word} المصنع «{name}» — {n} حساب تغيّر.")
            self.load_users()
        except Exception as e:
            err(self, e)

    def add_user_to_factory(self):
        """مستخدم إضافي لمصنعٍ قائم — بالهوية نفسها وعلى جهازه نفسه."""
        try:
            from services import cloud_auth
            u = self._selected_user()
            if u.get("role") == "super_admin":
                raise ValueError("اختر حساب مصنع")
            fac = u.get("full_name") or u.get("tenant_id")
            usr, ok = QtWidgets.QInputDialog.getText(
                self, "مستخدم إضافي", f"اسم المستخدم الجديد لمصنع «{fac}»:")
            if not ok or not usr.strip():
                return
            pwd, ok = QtWidgets.QInputDialog.getText(
                self, "مستخدم إضافي", "كلمة المرور:",
                QtWidgets.QLineEdit.Password)
            if not ok or not pwd:
                return
            r = cloud_auth.create_user(
                usr.strip(), pwd, role=cloud_auth.ROLE_FACTORY,
                tenant_id=u.get("tenant_id"), full_name=fac,
                factory_name=fac)
            info(self, f"أُنشئ المستخدم «{r['username']}» لمصنع «{fac}».")
            self.load_users()
        except Exception as e:
            err(self, e)

    def purge_old_cloud_data(self):
        """يمسح ما رفعته الإصدارات السابقة — مرةً واحدة تكفي."""
        try:
            from services import cloud_auth
            users = getattr(self, "users", None) or cloud_auth.list_users()
            tids = sorted({u.get("tenant_id") for u in users
                           if u.get("tenant_id")})
            if not tids:
                raise ValueError("لا مصانع في القائمة — اضغط «تحديث» أولاً")
            if not ask(self, f"حذف البيانات القديمة المرفوعة لـ{len(tids)} "
                             "مصنع من السحابة؟\n\n"
                             "فواتير وقيود وسندات رفعتها الإصدارات السابقة. "
                             "البيانات على أجهزة المصانع لا تُمسّ، والحسابات "
                             "تبقى كما هي."):
                return
            ok, bad = 0, []
            for t in tids:
                try:
                    cloud_auth._admin_call(
                        "admin_wipe_tenant",
                        {"p_token": cloud_auth._need_token(),
                         "p_tenant": t})
                    ok += 1
                except Exception as ex:
                    bad.append(f"{t}: {str(ex)[:80]}")
            info(self, f"مُسحت البيانات القديمة لـ{ok} مصنع."
                       + ("\n\nتعذّر:\n" + "\n".join(bad) if bad else "")
                       + "\n\nوملفات النسخ السحابية القديمة تُحذف من "
                         "لوحة Supabase ← Storage ← factory-backups.")
        except Exception as e:
            err(self, e)

    def _maint_tab(self):
        w = QtWidgets.QWidget()
        btn_now = QtWidgets.QPushButton("💾 أخذ نسخة احتياطية الآن")
        btn_now.setObjectName("homeBtn")
        btn_now.clicked.connect(self.backup_now)
        btn_list = QtWidgets.QPushButton("↻ تحديث القائمة")
        btn_list.clicked.connect(self.load_backups)
        btn_health = QtWidgets.QPushButton("🩺 فحص سلامة النظام")
        btn_health.setToolTip(
            "يتحقق من توازن كل القيود وسلامة قاعدة البيانات")
        btn_health.clicked.connect(self.check_health)
        btn_restore = QtWidgets.QPushButton("♻ استرجاع نسخة…")
        btn_restore.setObjectName("homeBtn")
        btn_restore.clicked.connect(self.open_restore)
        btn_tune = QtWidgets.QPushButton("⚡ صيانة سريعة")
        btn_tune.setToolTip(
            "تنظيف طابور المزامنة المرفوع، دمج ملف WAL، وتحديث "
            "إحصاءات مخطِّط الاستعلام. آمن أثناء العمل ويستغرق ثوانيَ.")
        btn_tune.clicked.connect(self.run_maintenance)
        btn_compact = QtWidgets.QPushButton("🗜 ضغط قاعدة البيانات")
        btn_compact.setToolTip(
            "يعيد بناء الملف بلا صفحات محرَّرة فيصغر حجمه ومعه كل "
            "نسخة احتياطية. يقفل النظام أثناء التنفيذ — نفّذه وقت "
            "الفراغ.")
        btn_compact.clicked.connect(self.compact_db)
        btn_dbstats = QtWidgets.QPushButton("📊 حجم الجداول")
        btn_dbstats.clicked.connect(self.show_db_stats)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(btn_now)
        row.addWidget(btn_restore)
        row.addWidget(btn_list)
        row.addWidget(btn_health)
        row.addStretch(1)

        row_maint = QtWidgets.QHBoxLayout()
        row_maint.addWidget(btn_tune)
        row_maint.addWidget(btn_compact)
        row_maint.addWidget(btn_dbstats)
        row_maint.addStretch(1)
        self.maint_label = QtWidgets.QLabel("")
        self.maint_label.setObjectName("cardSub")
        self.maint_label.setProperty("live", True)
        self.maint_label.setWordWrap(True)

        self.bk_table = make_table()
        self.upd_label = big_label(
            f"الإصدار: {licensing.APP_VERSION}")
        from services import storage
        note = QtWidgets.QLabel(
            f"نسخ هذا الجهاز: تُؤخذ نسخة تلقائياً كل "
            f"{storage.BACKUP_EVERY_SEC // 60} دقيقة وعند الإغلاق، ويُحتفظ "
            f"بآخر {storage.KEEP_LAST} نسخة. ولا يُرفع منها شيء للسحابة.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)

        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(note)
        lay.addLayout(row)
        lay.addWidget(self.bk_table, 1)
        maint_box = QtWidgets.QGroupBox("صيانة قاعدة البيانات")
        ml = QtWidgets.QVBoxLayout(maint_box)
        mnote = QtWidgets.QLabel(
            "قاعدة البيانات لا تبطؤ فجأة بل ببطء: الإحصاءات تتقادم "
            "فيختار المخطِّط مساراً أبطأ، وملف WAL يتضخّم، والصفحات "
            "المحرَّرة تبقى في الملف. الصيانة السريعة تعالج ذلك "
            "تلقائياً كل يوم، وهذه الأزرار لتشغيلها فوراً عند الحاجة.")
        mnote.setObjectName("cardSub")
        mnote.setWordWrap(True)
        ml.addWidget(mnote)
        ml.addLayout(row_maint)
        ml.addWidget(self.maint_label)
        lay.addWidget(maint_box)
        lay.addWidget(self.upd_label)

        # ── منطقة الخطر ──
        danger = QtWidgets.QGroupBox("⚠ منطقة الخطر")
        dl = QtWidgets.QVBoxLayout(danger)
        dnote = QtWidgets.QLabel(
            "مسح كافة بيانات النظام على هذا الجهاز: يحذف كل المبيعات "
            "والمشتريات والخزينة والقيود والرواتب والتارجت والذهب "
            "ويحذف النسخ الاحتياطية، ويعيد النظام كأنه مثبَّت لأول مرة "
            "مع الإبقاء على حساب المدير.\n"
            "لا يمكن التراجع عن هذا الإجراء.")
        dnote.setObjectName("cardSub")
        dnote.setWordWrap(True)
        btn_wipe = QtWidgets.QPushButton("🔥 مسح كافة بيانات النظام")
        btn_wipe.setObjectName("dangerBtn")
        btn_wipe.clicked.connect(self.wipe_system)
        dl.addWidget(dnote)
        dl.addWidget(btn_wipe)
        lay.addWidget(danger)
        return w

    # ══════════════════════════════════════════════════════════════
    #  صيانة قاعدة البيانات
    # ══════════════════════════════════════════════════════════════

    def run_maintenance(self):
        try:
            from services import maintenance
            res = maintenance.light_maintenance()
            wal = res.get("wal")
            parts = [f"حُذفت {res.get('purged', 0):,} حزمة مزامنة مرفوعة"]
            if wal:
                parts.append(f"دُمج ملف WAL ({wal[1]} صفحة)")
            if res.get("optimized"):
                parts.append("حُدِّثت إحصاءات المخطِّط")
            self.maint_label.setText("✔ " + " · ".join(parts))
            info(self, "اكتملت الصيانة السريعة.\n\n" + "\n".join(parts))
        except Exception as e:
            err(self, e)

    def compact_db(self):
        try:
            from services import maintenance
            if not ask(self,
                       "ضغط قاعدة البيانات؟\n\n"
                       "يعيد بناء الملف فيصغر حجمه ومعه كل نسخة "
                       "احتياطية. النظام يتوقّف عن الاستجابة أثناء "
                       "التنفيذ (ثوانٍ إلى دقائق حسب الحجم)، "
                       "والبيانات لا تُمسّ.\n\n"
                       "يُنصح بتنفيذه خارج وقت العمل."):
                return
            before, after = maintenance.compact()
            saved = round(before - after, 1)
            self.maint_label.setText(
                f"✔ ضُغطت القاعدة: {before} → {after} ميجابايت")
            info(self, f"اكتمل الضغط.\n\nقبل: {before} ميجابايت\n"
                       f"بعد: {after} ميجابايت\nالموفَّر: {saved} ميجابايت")
        except Exception as e:
            err(self, e)

    def show_db_stats(self):
        try:
            from services import maintenance
            st = maintenance.db_stats()
            lines = [f"حجم القاعدة: {st['db_mb']} ميجابايت",
                     f"ملف WAL: {st['wal_mb']} ميجابايت", "",
                     "أكبر الجداول:"]
            for t in st["tables"]:
                lines.append(f"   {t['table']}: {t['rows']:,} سجل")
            info(self, "\n".join(lines), "حجم قاعدة البيانات")
        except Exception as e:
            err(self, e)

    def wipe_system(self):
        """تهيئة كاملة — بتأكيد مغلَّظ وكلمة المرور."""
        try:
            if not tenant.is_super_admin() and not self.user.get("is_super"):
                raise PermissionError("متاح للمدير العام فقط")
            if not ask(self,
                       "⚠ تحذير أخير\n\n"
                       "سيُمسح كل شيء: المبيعات · المشتريات · الخزينة · "
                       "القيود · الرواتب · التارجت · الذهب · الجهات\n"
                       "لكل المصانع على هذا الجهاز،\n"
                       "مع حذف النسخ الاحتياطية.\n\n"
                       "لا يمكن التراجع إطلاقاً.\n\nهل أنت متأكد؟"):
                return
            # تأكيد نصي صريح
            txt, ok = QtWidgets.QInputDialog.getText(
                self, "تأكيد المسح",
                "اكتب الكلمة التالية للتأكيد:\n\n    مسح نهائي\n")
            if not ok or str(txt).strip() != "مسح نهائي":
                info(self, "أُلغي المسح — لم تُكتب كلمة التأكيد.")
                return
            # كلمة مرور المدير
            pwd, ok2 = QtWidgets.QInputDialog.getText(
                self, "كلمة المرور", "أدخل كلمة مرور المدير:",
                QtWidgets.QLineEdit.Password)
            if not ok2 or not pwd:
                return
            from services import cloud_auth
            try:
                cloud_auth.login(self.user["username"], pwd)
            except Exception:
                raise ValueError("كلمة المرور غير صحيحة — أُلغي المسح")

            from models import system_reset
            with db() as conn:
                res = system_reset.full_reset(conn)
            msg = [f"تم مسح النظام.",
                   f"جداول مُفرَّغة: {len(res['local'])}",
                   f"قواعد مصانع محذوفة: {len(res.get('tenants') or [])}",
                   f"نسخ احتياطية محذوفة: {res['backups']}"]
            if res.get("last_backup"):
                msg.append(f"\nنسخة ما قبل المسح محفوظة في:\n"
                           f"{res['last_backup']}")
            msg.append("\nأغلق النظام وأعد تشغيله الآن.")
            info(self, "\n".join(msg))
        except Exception as e:
            err(self, e)

    def check_health(self):
        """تقرير سلامة شامل: توازن القيود · اليتامى · سلامة الملف."""
        try:
            from services import health
            with db(readonly=True) as conn:
                h = health.full_health(conn)
            lines = ["حالة النظام: " + ("✔ سليم" if h["ok"]
                                        else "⚠ توجد ملاحظات"), ""]
            if h["unbalanced"]:
                lines.append(f"✘ قيود غير متوازنة: {len(h['unbalanced'])}")
                for u in h["unbalanced"][:5]:
                    lines.append(
                        f"   {u['doc_no']} — {u['date']} — "
                        f"فرق ذهب {u['gold_diff']} · نقد {u['cash_diff']}")
            else:
                lines.append("✔ كل القيود متوازنة")
            if h["orphans"]:
                lines.append("")
                lines.append("✘ سجلات يتيمة:")
                for o in h["orphans"]:
                    lines.append(f"   {o}")
            else:
                lines.append("✔ لا توجد سجلات يتيمة")
            lines.append("")
            lines.append("✔ سلامة قاعدة البيانات" if not h["integrity"]
                         else "✘ " + " · ".join(h["integrity"]))
            lines.append(f"أخطاء مسجّلة: {h['recent_errors']}")
            info(self, "\n".join(lines))
        except Exception as e:
            err(self, e)

    def open_restore(self):
        try:
            from ui.backups_dialog import open_dialog
            open_dialog(self, self.user)
            self.load_backups()
        except Exception as e:
            err(self, e)

    def backup_now(self):
        try:
            from services import storage
            p = storage.make_backup("manual")
            if not p:
                raise ValueError("لا توجد قاعدة بيانات لنسخها")
            info(self, f"أُخذت النسخة:\n{p}")
            self.load_backups()
        except Exception as e:
            err(self, e)

    def load_backups(self):
        try:
            from services import storage
            rows = storage.list_backups()
            fill(self.bk_table, ["التاريخ والوقت", "النوع", "الحجم (ك.ب)",
                                 "الملف"],
                 [(r["when"], r.get("reason_label", ""),
                   f"{r['size_kb']:,.1f}", r["name"]) for r in rows])
        except Exception as e:
            err(self, e)

    def refresh(self):
        self.load_backups()
        try:
            self.load_users()
        except Exception:
            pass
