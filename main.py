# -*- coding: utf-8 -*-
"""نقطة تشغيل نظام محاسبة مصنع الذهب — عيار 18."""
import sys


def main():
    try:
        from PyQt5 import QtWidgets
    except ImportError:
        print("يلزم تثبيت PyQt5 أولاً:  pip install PyQt5")
        return
    from database.database import run_migrations_files, create_tables, db, migrate_schema
    from database.seed import (ensure_new_accounts, ensure_system_tags,
                              seed_initial_data)
    from models.entities import (ensure_employee_accrual_accounts,
                             ensure_internal_counterparties)
    create_tables()
    # استرداد تلقائي: إن كانت القاعدة مفقودة تُسحب أحدث نسخة
    try:
        from services import storage
        rec = storage.auto_recover()
        if rec.get("recovered"):
            print(f"[recovery] استُعيدت البيانات من {rec['from']}")
    except Exception:
        pass
    migrate_schema()
    run_migrations_files()
    seed_initial_data()
    ensure_new_accounts()
    with db() as conn:
        ensure_internal_counterparties(conn)
        ensure_employee_accrual_accounts(conn)
        ensure_system_tags(conn)

    # الخدمات الخلفية تبدأ الآن — بعد جهوزية القاعدة والترقيات
    start_background_workers()

    from ui import styles
    from ui.login_window import LoginDialog
    from ui.main_window import MainWindow

    app = QtWidgets.QApplication(sys.argv)
    # تناسب تلقائي مع حجم شاشة المستخدم: الخطوط والحشو تصغر على
    # الأجهزة الصغيرة وتكبر على الكبيرة — فيبدو النظام متناسقاً
    # على أي جهاز بلا ضبط يدوي.
    # أيقونة البرنامج: التطبيق وشريط المهام معاً
    try:
        from services import app_icon
        app_icon.apply(app)
    except Exception:
        pass

    try:
        from ui.widgets.table_fit import apply_screen_scale
        apply_screen_scale(app)
    except Exception:
        pass
    styles.apply(app)
    dlg = LoginDialog()
    if dlg.exec_() != QtWidgets.QDialog.Accepted:
        return
    win = MainWindow(dlg.user)
    win.showMaximized()
    # ══ حارس التجمّد ══
    # يرصد توقّف خيط الواجهة عن معالجة أحداثه — وهو ما يراه المستخدم
    # «شاشة سوداء ولا يستجيب» — ويكتب في السجل **موضعه** بالملف
    # والسطر والدالة. لا يُعالج شيئاً؛ يجعل الشكوى دليلاً يُقرأ.
    try:
        from services import ui_watchdog
        ui_watchdog.start(win)
    except Exception:
        pass
    sys.exit(app.exec_())


def start_background_workers():
    """يشغّل الخدمات الخلفية بعد جهوزية قاعدة البيانات.

    كانت هذه الكتلة تُنفَّذ عند **استيراد** الملف، أي قبل إنشاء
    الجداول وقبل وجود QApplication، ومع كل استيراد لـ main من أي أداة
    (tools/…) — فتبدأ خيوط نسخ ومزامنة ورقابة على قاعدة قد لا تكون
    مهيأة بعد. ربطها بدالة تُستدعى في مكانها الصحيح يزيل هذا كله.
    """
    for label, fn in (
            ("tenant", lambda: __import__(
                "services.tenant", fromlist=["x"]).ensure_tenant_id()),
            ("cloud_sync", lambda: __import__(
                "services.cloud_sync", fromlist=["x"]).start_worker()),
            # نسخ احتياطي محلي دوري
            ("licensing_backup", lambda: __import__(
                "services.licensing", fromlist=["x"]).start_backup_worker()),
            # نسخ إلى قرص آخر كل 30 دقيقة
            ("disk_backup", lambda: __import__(
                "services.storage", fromlist=["x"]).start_backup_worker()),
            # مراقب سلامة القيود
            ("health", lambda: __import__(
                "services.health", fromlist=["x"]).start_health_worker()),
            # تحميل مسبق للوحدات الثقيلة (وحدة الطباعة أثقلها): تُحمَّل
            # في الخلفية بعد الإقلاع فتكون جاهزة عند أول استعمال، ولا
            # يتجمّد النظام عند أول فتح لمربع «تم الترحيل».
            ("preload", lambda: __import__(
                "services.preload", fromlist=["x"]).start(delay=2.0)),
            # نسخة سحابية كل ساعة
            ("cloud_backup", lambda: __import__(
                "services.cloud_backup", fromlist=["x"]).start_worker()),
            # صيانة يومية: تنظيف الطابور، تفتيش WAL، تحديث إحصاءات
            # مخطِّط الاستعلام — بها يبقى النظام سريعاً مع نموّ الدفتر
            ("maintenance", lambda: __import__(
                "services.maintenance", fromlist=["x"]).start_worker()),
    ):
        try:
            fn()
        except Exception as e:
            # فشل خدمة خلفية واحدة لا يمنع البقية — وكانت الصيغة
            # السابقة (try واحد يلفّها كلها) توقف كل ما بعد أول خطأ
            # وتبتلعه صامتاً بلا أثر يُشخَّص منه العطل.
            try:
                from services.health import log_error
                log_error(f"start_background_workers/{label}", e)
            except Exception:
                pass


if __name__ == "__main__":
    main()
