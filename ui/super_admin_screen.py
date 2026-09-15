# -*- coding: utf-8 -*-
"""لوحة المدير الأعلى (Super Admin) + حالة المزامنة.

تبويبان:
* **إعدادات المصنع والمزامنة**: هوية المصنع · بيانات السحابة · حالة
  الطابور الحية (بلا أي إزعاج للمستخدم أثناء العمل).
* **إدارة المصانع** (للمدير الأعلى فقط): إنشاء مصنع وتوليد هويته
  وربطه برخصة، و**الدخول كـ** (انتحال الشخصية) لرؤية النظام كما يراه
  صاحب المصنع دون معرفة كلمة مروره.
"""
from PyQt5 import QtCore, QtWidgets

from database.database import db
from services import cloud_sync, licensing, sync_queue, tenant
from ui.widgets.common import (ask, big_label, err, fill, info, make_table,
                               title_label)

FACT_COLS = ["هوية المصنع", "الاسم", "الرخصة", "الحالة"]


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
        tabs.addTab(self._users_tab(), "حسابات المصانع")
        tabs.addTab(self._factories_tab(), "مراقبة المصانع")
        tabs.addTab(self._settings_tab(), "إعدادات السحابة")
        tabs.addTab(self._maint_tab(), "النسخ الاحتياطي والتحديثات")

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("النظام السحابي متعدد المصانع"))
        note = QtWidgets.QLabel(
            "النظام يعمل محلياً بسرعته القصوى دائماً؛ المزامنة تجري في "
            "خيط خلفي معزول ولا تُعطّل أي شاشة. وعند انقطاع الإنترنت "
            "تتراكم العمليات محلياً وتُرفع كتلةً عند عودته.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addWidget(tabs, 1)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh_status)
        self.timer.start(4000)

    # ══════════ تبويب الإعدادات ══════════
    def _settings_tab(self):
        w = QtWidgets.QWidget()
        st = tenant.get_all()

        self.tid = QtWidgets.QLineEdit(tenant.tenant_id())
        self.tid.setReadOnly(True)
        self.fname = QtWidgets.QLineEdit(st["factory_name"])
        self.license = QtWidgets.QLineEdit(st["license_key"])
        self.url = QtWidgets.QLineEdit(st["cloud_url"])
        self.url.setPlaceholderText("https://xxxx.supabase.co")
        self.key = QtWidgets.QLineEdit(st["cloud_key"])
        self.key.setEchoMode(QtWidgets.QLineEdit.Password)
        self.enabled = QtWidgets.QCheckBox("تفعيل المزامنة السحابية")
        self.enabled.setChecked(bool(st["sync_enabled"]))
        self.interval = QtWidgets.QSpinBox()
        self.interval.setRange(5, 3600)
        self.interval.setValue(int(st["sync_interval_sec"]))
        self.is_admin = QtWidgets.QCheckBox(
            "هذه نسخة المدير الأعلى (Super Admin)")
        self.is_admin.setChecked(tenant.is_super_admin())

        btn_save = QtWidgets.QPushButton("💾 حفظ الإعدادات")
        btn_save.setObjectName("homeBtn")
        btn_save.clicked.connect(self.save_settings)
        btn_retry = QtWidgets.QPushButton("↻ إعادة محاولة العمليات الفاشلة")
        btn_retry.clicked.connect(self.retry_failed)
        btn_diag = QtWidgets.QPushButton("🔍 فحص جاهزية السحابة")
        btn_diag.setToolTip("يحدّد بدقة ما ينقص: الجداول أو المفتاح أو الرابط")
        btn_diag.clicked.connect(self.diagnose)

        form = QtWidgets.QFormLayout()
        form.addRow("هوية المصنع (Tenant ID):", self.tid)
        form.addRow("اسم المصنع:", self.fname)
        form.addRow("مفتاح الرخصة:", self.license)
        form.addRow("رابط السحابة (Supabase):", self.url)
        form.addRow("مفتاح السحابة:", self.key)
        form.addRow("فترة المزامنة (ثانية):", self.interval)
        form.addRow(self.enabled)
        form.addRow(self.is_admin)

        self.status = big_label("حالة المزامنة: —")
        self.qstats = QtWidgets.QLabel("")
        self.qstats.setObjectName("cardSub")

        row = QtWidgets.QHBoxLayout()
        row.addWidget(btn_save)
        row.addWidget(btn_retry)
        row.addWidget(btn_diag)
        row.addStretch(1)

        lay = QtWidgets.QVBoxLayout(w)
        lay.addLayout(form)
        lay.addLayout(row)
        lay.addWidget(self.status)
        lay.addWidget(self.qstats)
        lay.addStretch(1)
        return w

    # ══════════ تبويب المصانع ══════════
    def _factories_tab(self):
        w = QtWidgets.QWidget()
        self.new_name = QtWidgets.QLineEdit()
        self.new_name.setPlaceholderText("اسم المصنع الجديد")
        self.new_lic = QtWidgets.QLineEdit()
        self.new_lic.setPlaceholderText("مفتاح الرخصة (اختياري)")
        btn_new = QtWidgets.QPushButton("➕ إنشاء مصنع وتوليد هويته")
        btn_new.clicked.connect(self.create_factory)
        btn_load = QtWidgets.QPushButton("↻ تحديث القائمة")
        btn_load.clicked.connect(self.load_factories)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.new_name, 2)
        top.addWidget(self.new_lic, 1)
        top.addWidget(btn_new)
        top.addWidget(btn_load)

        self.table = make_table()
        btn_login = QtWidgets.QPushButton("👤 الدخول كـ (انتحال الشخصية)")
        btn_login.setObjectName("homeBtn")
        btn_login.clicked.connect(self.impersonate)
        btn_exit = QtWidgets.QPushButton("↩ إنهاء انتحال الشخصية")
        btn_exit.clicked.connect(self.stop_impersonation)
        btn_toggle = QtWidgets.QPushButton("⛔ إيقاف / تفعيل الحساب")
        btn_toggle.setToolTip(
            "إيقاف الحساب يمنع صاحب المصنع من الدخول فوراً")
        btn_toggle.clicked.connect(self.toggle_active)

        act = QtWidgets.QHBoxLayout()
        act.addWidget(btn_login)
        act.addWidget(btn_toggle)
        act.addWidget(btn_exit)
        act.addStretch(1)

        # ── إنشاء حساب لصاحب المصنع المحدَّد ──
        self.u_name = QtWidgets.QLineEdit()
        self.u_name.setPlaceholderText("اسم المستخدم")
        self.u_full = QtWidgets.QLineEdit()
        self.u_full.setPlaceholderText("الاسم الكامل")
        self.u_pass = QtWidgets.QLineEdit()
        self.u_pass.setPlaceholderText("كلمة المرور")
        self.u_pass.setEchoMode(QtWidgets.QLineEdit.Password)
        btn_user = QtWidgets.QPushButton("👤 إنشاء حساب لصاحب المصنع")
        btn_user.clicked.connect(self.create_user)
        urow = QtWidgets.QHBoxLayout()
        urow.addWidget(QtWidgets.QLabel("حساب صاحب المصنع:"))
        urow.addWidget(self.u_name, 1)
        urow.addWidget(self.u_full, 1)
        urow.addWidget(self.u_pass, 1)
        urow.addWidget(btn_user)

        self.imp_label = big_label("")
        lay = QtWidgets.QVBoxLayout(w)
        lay.addLayout(top)
        lay.addWidget(self.table, 1)
        lay.addLayout(urow)
        lay.addLayout(act)
        lay.addWidget(self.imp_label)
        return w

    # ══════════ الإجراءات ══════════
    def save_settings(self):
        try:
            tenant.update(
                factory_name=self.fname.text().strip(),
                license_key=self.license.text().strip(),
                cloud_url=self.url.text().strip(),
                cloud_key=self.key.text().strip(),
                sync_enabled=self.enabled.isChecked(),
                sync_interval_sec=int(self.interval.value()),
                role="super_admin" if self.is_admin.isChecked() else "factory")
            cloud_sync.start_worker()
            cloud_sync.nudge()
            info(self, "حُفظت الإعدادات. المزامنة تعمل في الخلفية بلا "
                       "أي تأثير على سرعة الشاشات.")
            self.refresh_status()
        except Exception as e:
            err(self, e)

    def retry_failed(self):
        try:
            with db() as conn:
                n = sync_queue.retry_failed(conn)
            cloud_sync.nudge()
            info(self, f"أُعيدت {n} عملية إلى الطابور.")
            self.refresh_status()
        except Exception as e:
            err(self, e)

    def diagnose(self):
        """فحص تشخيصي يشرح سبب أخطاء 404 أو الصلاحيات بدقة."""
        try:
            cfg = tenant.cloud_config()
            ad = cloud_sync.SupabaseAdapter(cfg["url"], cfg["key"])
            d = ad.diagnose()
            lines = [f"الرابط: {d['url'] or '—'}",
                     f"الوصول للخادم: {'✔' if d['reachable'] else '✘'}", ""]
            for t, v in d["tables"].items():
                mark = "✔" if v == "موجود" else "✘"
                lines.append(f"  {mark} {t}: {v}")
            lines.append("")
            lines.append(f"  {'✔' if d['rpc'] else '✘'} دالة ingest_bundle")
            lines.append("")
            lines.append(d["message"])
            info(self, "\n".join(lines))
        except Exception as e:
            err(self, e)

    def refresh_status(self):
        try:
            s = cloud_sync.status()
            with db() as conn:
                q = sync_queue.stats(conn)
            imp = tenant.impersonation_info()
            self.status.setText(
                f"حالة المزامنة: {s['state']}"
                + (f"  ·  {s['error']}" if s.get("error") else ""))
            self.qstats.setText(
                f"الطابور — بانتظار الرفع: {q['pending']}  ·  "
                f"مرفوع: {q['sent']}  ·  فاشل: {q['failed']}")
            self.imp_label.setText(
                f"⚠ تعمل الآن بهوية المصنع: {imp['name']}"
                if tenant.impersonating() else "")
        except Exception:
            pass

    def load_factories(self):
        try:
            cfg = tenant.cloud_config()
            ad = cloud_sync.SupabaseAdapter(cfg["url"], cfg["key"])
            if not ad.available():
                raise ValueError("أدخل رابط السحابة ومفتاحها أولاً")
            self.factories = ad.list_factories()
            fill(self.table, FACT_COLS,
                 [(f.get("tenant_id", ""), f.get("name", ""),
                   f.get("license_key", "") or "—",
                   "نشط" if f.get("is_active") else "موقوف")
                  for f in self.factories])
        except Exception as e:
            err(self, e)

    def create_factory(self):
        try:
            if not tenant.is_super_admin():
                raise PermissionError("متاح للمدير الأعلى فقط")
            name = self.new_name.text().strip()
            if not name:
                raise ValueError("أدخل اسم المصنع")
            import uuid
            tid = f"F-{uuid.uuid4().hex[:12].upper()}"
            cfg = tenant.cloud_config()
            ad = cloud_sync.SupabaseAdapter(cfg["url"], cfg["key"])
            if not ad.available():
                raise ValueError("أدخل رابط السحابة ومفتاحها أولاً")
            d = ad.diagnose()
            if d["tables"].get("factories") == "غير موجود":
                raise ValueError(
                    "جدول factories غير موجود في السحابة.\n"
                    "شغّل المهاجر مرة واحدة:\n"
                    "  python tools/cloud_migrate.py --dsn \"postgresql://…\"")
            ad.create_factory(tid, name, self.new_lic.text().strip())
            info(self, f"أُنشئ المصنع «{name}».\nهويته: {tid}\n\n"
                       f"سلّم هذه الهوية لنسخة المصنع لتربطها بالسحابة.")
            self.new_name.clear()
            self.new_lic.clear()
            self.load_factories()
        except Exception as e:
            err(self, e)

    def create_user(self):
        """ينشئ حساب دخول لصاحب المصنع المحدَّد.

        كلمة المرور تُجزَّأ محلياً (PBKDF2) ولا تُرسل ولا تُخزَّن نصاً
        صريحاً في السحابة إطلاقاً.
        """
        try:
            if not tenant.is_super_admin():
                raise PermissionError("متاح للمدير الأعلى فقط")
            i = self.table.currentRow()
            if not (0 <= i < len(self.factories)):
                raise ValueError("اختر المصنع من القائمة أولاً")
            f = self.factories[i]
            uname = self.u_name.text().strip()
            pwd = self.u_pass.text()
            if not uname or not pwd:
                raise ValueError("أدخل اسم المستخدم وكلمة المرور")
            if len(pwd) < 6:
                raise ValueError("كلمة المرور قصيرة — 6 أحرف على الأقل")
            from services.auth import hash_password
            cfg = tenant.cloud_config()
            ad = cloud_sync.SupabaseAdapter(cfg["url"], cfg["key"])
            if not ad.available():
                raise ValueError("أدخل رابط السحابة ومفتاحها أولاً")
            ad.create_user(f.get("tenant_id"), uname, hash_password(pwd),
                           self.u_full.text().strip())
            info(self, f"أُنشئ حساب «{uname}» لمصنع «{f.get('name')}».\n"
                       f"سلّم بيانات الدخول لصاحب المصنع.")
            self.u_name.clear()
            self.u_full.clear()
            self.u_pass.clear()
        except Exception as e:
            err(self, e)

    def impersonate(self):
        try:
            i = self.table.currentRow()
            if not (0 <= i < len(self.factories)):
                raise ValueError("اختر مصنعاً من القائمة")
            f = self.factories[i]
            if not ask(self, f"الدخول كـ «{f.get('name')}»؟\n\n"
                             f"ستُعرض كل الشاشات والتقارير ببيانات هذا "
                             f"المصنع كما يراها صاحبه."):
                return
            tenant.impersonate(f.get("tenant_id"), f.get("name"))
            info(self, f"تعمل الآن بهوية «{f.get('name')}».\n"
                       f"استخدم «إنهاء انتحال الشخصية» للعودة.")
            self.refresh_status()
        except Exception as e:
            err(self, e)

    def stop_impersonation(self):
        tenant.stop_impersonation()
        info(self, "عُدت إلى هويتك الأصلية.")
        self.refresh_status()

    def toggle_active(self):
        """يوقف حساب المصنع أو يفعّله عن بُعد بضغطة زر."""
        try:
            if not tenant.is_super_admin():
                raise PermissionError("متاح للمدير الأعلى فقط")
            i = self.table.currentRow()
            if not (0 <= i < len(self.factories)):
                raise ValueError("اختر مصنعاً من القائمة")
            f = self.factories[i]
            now_active = bool(f.get("is_active"))
            new_state = not now_active
            word = "تفعيل" if new_state else "إيقاف"
            if not ask(self, f"{word} حساب «{f.get('name')}»؟\n\n"
                             + ("سيُمنع صاحب المصنع من الدخول فوراً."
                                if not new_state
                                else "سيتمكن من الدخول مجدداً.")):
                return
            import app_config
            licensing.set_factory_active(
                f.get("tenant_id"), new_state,
                app_config.supabase_service_key() or None)
            info(self, f"تم {word} الحساب.")
            self.load_factories()
        except Exception as e:
            err(self, e)

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
        btn_del = QtWidgets.QPushButton("🗑 حذف الحساب نهائياً")
        btn_del.setObjectName("ghost")
        btn_del.clicked.connect(self.delete_user)

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
        row2.addWidget(btn_toggle)
        row2.addWidget(btn_del)
        row2.addWidget(btn_diag2)
        row2.addStretch(1)

        self.users_table = make_table()
        note = QtWidgets.QLabel(
            "الحساب الجديد يُنشأ في السحابة بهوية مصنع فريدة، وكلمة "
            "المرور تُجزَّأ (PBKDF2) ولا تُخزَّن نصاً صريحاً. سلّم العميل "
            "نفس الملف التنفيذي واسم المستخدم وكلمة المرور — وستُخفى "
            "عنه شاشات الإدارة تلقائياً.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)

        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(note)
        lay.addLayout(row)
        lay.addLayout(row2)
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
            fill(self.users_table,
                 ["اسم المستخدم", "المصنع", "هوية المصنع",
                  "الصلاحية", "الحالة"],
                 [(u.get("username", ""), u.get("full_name") or "—",
                   u.get("tenant_id", ""),
                   "المدير العام" if u.get("role") == "super_admin"
                   else "مصنع",
                   "نشط" if u.get("is_active") else "موقوف")
                  for u in self.users])
        except Exception as e:
            err(self, e)

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
        btn_cloud_up = QtWidgets.QPushButton("☁ رفع نسخة للسحابة الآن")
        btn_cloud_up.clicked.connect(self.cloud_upload)
        btn_cloud_ls = QtWidgets.QPushButton("☁ عرض النسخ السحابية")
        btn_cloud_ls.clicked.connect(self.cloud_list)
        btn_restore = QtWidgets.QPushButton("♻ استرجاع النسخة المحددة")
        btn_restore.setObjectName("homeBtn")
        btn_restore.clicked.connect(self.cloud_restore)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(btn_now)
        row.addWidget(btn_list)
        row.addStretch(1)

        row_cloud = QtWidgets.QHBoxLayout()
        row_cloud.addWidget(btn_cloud_up)
        row_cloud.addWidget(btn_cloud_ls)
        row_cloud.addWidget(btn_restore)
        row_cloud.addStretch(1)

        self.bk_table = make_table()
        self.upd_label = big_label(
            f"الإصدار: {licensing.APP_VERSION}")
        note = QtWidgets.QLabel(
            "تُؤخذ نسخة احتياطية تلقائياً كل 15 دقيقة في مجلد "
            "backups/auto، وتحفظ معها العمليات التي لم تُرفع بعد — "
            "فتنجو القيود من تلف الجهاز قبل المزامنة.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)

        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(note)
        lay.addLayout(row)
        lay.addWidget(self.bk_table, 1)
        lay.addWidget(QtWidgets.QLabel(
            "النسخ السحابية (تُسترجع على أي جهاز جديد):"))
        lay.addLayout(row_cloud)
        self.cloud_table = make_table()
        lay.addWidget(self.cloud_table, 1)
        lay.addWidget(self.upd_label)

        # ── منطقة الخطر ──
        danger = QtWidgets.QGroupBox("⚠ منطقة الخطر")
        dl = QtWidgets.QVBoxLayout(danger)
        dnote = QtWidgets.QLabel(
            "مسح كافة بيانات النظام: يحذف كل المبيعات والمشتريات "
            "والخزينة والقيود والرواتب والتارجت والذهب — محلياً "
            "وسحابياً — ويحذف النسخ الاحتياطية، ويعيد النظام كأنه "
            "مثبَّت لأول مرة مع الإبقاء على حساب المدير.\n"
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

    def wipe_system(self):
        """تهيئة كاملة — بتأكيد مغلَّظ وكلمة المرور."""
        try:
            if not tenant.is_super_admin() and not self.user.get("is_super"):
                raise PermissionError("متاح للمدير العام فقط")
            if not ask(self,
                       "⚠ تحذير أخير\n\n"
                       "سيُمسح كل شيء: المبيعات · المشتريات · الخزينة · "
                       "القيود · الرواتب · التارجت · الذهب · الجهات\n"
                       "لكل المصانع على هذا الجهاز، وسحابياً،\n"
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
            if res.get("cloud"):
                msg.append("السحابة: "
                           + ("تم" if res["cloud"].get("ok")
                              else res["cloud"].get("error", "تعذّر")))
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

    def cloud_upload(self):
        try:
            from services import cloud_backup
            r = cloud_backup.upload("manual")
            info(self, f"رُفعت النسخة للسحابة.\n"
                       f"الحجم: {r['size_kb']:,.1f} ك.ب")
            self.cloud_list()
        except Exception as e:
            err(self, e)

    def cloud_list(self):
        try:
            from services import cloud_backup
            self.cloud_backups = cloud_backup.list_cloud()
            fill(self.cloud_table,
                 ["الملف", "التاريخ والوقت", "الحجم (ك.ب)"],
                 [(b["file"], b["when"], f"{b['size_kb']:,.1f}")
                  for b in self.cloud_backups])
            if not self.cloud_backups:
                info(self, "لا توجد نسخ سحابية بعد.\n"
                           "اضغط «رفع نسخة للسحابة الآن» لأول نسخة.")
        except Exception as e:
            err(self, e)

    def cloud_restore(self):
        """يستبدل البيانات الحالية بنسخة سحابية — للأجهزة الجديدة."""
        try:
            from services import cloud_backup
            i = self.cloud_table.currentRow()
            rows = getattr(self, "cloud_backups", [])
            if not (0 <= i < len(rows)):
                raise ValueError("اختر نسخة من الجدول أولاً")
            b = rows[i]
            if not ask(self,
                       f"استرجاع النسخة «{b['file']}»؟\n\n"
                       f"سيُستبدل محتوى قاعدة البيانات الحالية بها.\n"
                       f"(تُحفظ الحالية جانباً قبل الاستبدال)\n\n"
                       f"ستحتاج إعادة تشغيل النظام بعدها."):
                return
            cloud_backup.restore(b["name"])
            info(self, "تم الاسترجاع بنجاح.\n\n"
                       "أغلق النظام وأعد تشغيله الآن.")
        except Exception as e:
            err(self, e)

    def backup_now(self):
        try:
            p = licensing.make_backup("manual")
            if not p:
                raise ValueError("لا توجد قاعدة بيانات لنسخها")
            info(self, f"أُخذت النسخة:\n{p}")
            self.load_backups()
        except Exception as e:
            err(self, e)

    def load_backups(self):
        try:
            rows = licensing.list_backups()
            fill(self.bk_table, ["الملف", "التاريخ والوقت", "الحجم (ك.ب)"],
                 [(r["name"], r["when"], f"{r['size_kb']:,.1f}")
                  for r in rows])
        except Exception as e:
            err(self, e)

    def refresh(self):
        self.refresh_status()
        self.load_backups()
        try:
            self.load_users()
        except Exception:
            pass
