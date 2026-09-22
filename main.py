# -*- coding: utf-8 -*-
"""نقطة تشغيل نظام محاسبة مصنع الذهب — عيار 18."""
import sys

_SPLASH = {"closed": False}


def _close_splash():
    """يُغلق شاشة بدء الـexe مرةً واحدة — من أي نداءٍ سبق.

    تُنادى من إشارة الرسم ومن مؤقّت الحارس معاً، فالحراسة من
    التكرار هنا لا عند كل نداء.
    """
    if _SPLASH["closed"]:
        return
    _SPLASH["closed"] = True
    try:
        import pyi_splash                      # داخل الـexe فقط
        pyi_splash.close()
    except Exception:
        pass


def main():
    try:
        from PyQt5 import QtCore, QtWidgets
    except ImportError:
        print("يلزم تثبيت PyQt5 أولاً:  pip install PyQt5")
        return
    from ui import styles
    from ui.gate_window import GateWindow

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

    # ══ البوابة أولاً، ثم التجهيز خلفها ══
    # كان التجهيز (إنشاء الجداول · الترقيات · بذر الحسابات) يسبق أول
    # رسمٍ للشاشة، فيقف صاحب النظام أمام سوادٍ ثوانيَ يظنّ الملف
    # معطّلاً — وهي أسوأ ثوانٍ في عمر أي برنامج. الآن تظهر البوابة في
    # أول لحظة ويجري التجهيز وهو يقرأ سطر الحالة يتقدّم.
    gate = GateWindow()
    # ══ تسليمٌ بلا فجوة ولا تداخل ══
    # شاشة بدء الـexe تُغلق على **أول رسمٍ فعلي** للبوابة لا على
    # `show()`: بينهما على ويندوز عشراتُ ثانيةٍ يرى فيها المستخدم
    # الشعار يختفي ثم سواداً ثم البوابة تظهر — وهو «التداخل» الذي
    # شُكي منه. والمؤقّت حارسٌ إن لم يصل حدثُ الرسم (بيئةٌ بلا
    # عرض): لا يبقى الشعار فوق البوابة بحال.
    gate.painted.connect(_close_splash)
    QtCore.QTimer.singleShot(2500, _close_splash)
    gate.showFullScreen()
    app.processEvents()
    gate.prepare(prepare_steps())

    wire_gate(app, gate)
    sys.exit(app.exec_())


def fade_ok():
    """هل يُسمح بالتلاشي؟ — يتبع مفتاح الحركة نفسه."""
    try:
        from ui.widgets.gold_stage import animations_on
        return animations_on()
    except Exception:
        return False


def wire_gate(app, gate, main_window_factory=None):
    """يربط البوابة بالنظام — ويُعيد قاموساً يحمل النافذة حين تُبنى.

    مفصولةٌ عن `main` لتُختبر: الاختبار يمرّر بوابةً ومصنعَ نافذةٍ
    ويتحقّق أن البوابة لا تختفي قبل أن يظهر النظام. وتسلسلُ الفتح
    عُطلٌ إن انكسر، فيستحقّ فحصاً دائماً كغيره.
    """
    from PyQt5 import QtCore

    if main_window_factory is None:
        from ui.main_window import MainWindow
        main_window_factory = MainWindow

    # ══ مشهدٌ متّصل: البوابة لا تختفي حتى يصير النظام على الشاشة ══
    #
    # **العلة التي كانت**: البوابة كانت تُعرض بـ`exec_`، و`accept`
    # يُخفي النافذة في لحظته. فيرى صاحب النظام: شاشةً كاملة تختفي،
    # ثم سطحَ المكتب ثوانيَ بينما تُبنى الواجهة، ثم تظهر فجأة —
    # أي «خرج البرنامج ثم دخل». والموجة الذهبية كانت تُشغَّل على
    # نافذةٍ مخفيّة فلا يراها أحد أصلاً.
    #
    # **الترتيب الصحيح**: نجاحُ الدخول لا يُخفي شيئاً؛ البوابة تبقى
    # وتقول «جارٍ تجهيز الشاشات…»، ويُبنى النظام **تحتها**، ثم
    # تنطلق الموجة، ثم يتمازج الاثنان وتُغلق البوابة أخيراً. فلا
    # تظهر لحظةُ فراغٍ واحدة من النقرة إلى أول جدول.
    holder = {}

    def _reveal(win):
        if not fade_ok():
            win.setWindowOpacity(1.0)
            win.raise_()
            win.activateWindow()
            gate.close()
            return
        up = QtCore.QPropertyAnimation(win, b"windowOpacity", win)
        up.setStartValue(0.0)
        up.setEndValue(1.0)
        up.setDuration(700)
        up.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        down = QtCore.QPropertyAnimation(gate, b"windowOpacity", gate)
        down.setStartValue(1.0)
        down.setEndValue(0.0)
        down.setDuration(520)
        down.setEasingCurve(QtCore.QEasingCurve.InCubic)
        down.finished.connect(gate.close)
        up.start()
        down.start()
        win._boot_anim = (up, down)    # مرجعٌ يمنعهما من الجمع مبكراً
        win.raise_()
        win.activateWindow()
        try:
            win.play_entrance()
        except Exception:
            pass

    def _build_system(session):
        """يبني النظام والبوابةُ ما زالت ظاهرة، ثم يُسلّم."""
        gate.set_state("جارٍ تجهيز الشاشات…")
        try:
            win = main_window_factory(session)
        except Exception as e:                   # noqa: BLE001
            # فشلُ البناء يُقال على البوابة — لا يُغلق كل شيء صامتاً
            gate.fail(f"تعذّر فتح النظام: {e}")
            return
        holder["win"] = win
        # تُعرض مخفيّةَ الشفافية قبل الموجة: جاهزةٌ خلف البوابة،
        # فحين تنتهي الموجة لا يبقى إلا أن تظهر.
        win.setWindowOpacity(0.0 if fade_ok() else 1.0)
        win.showMaximized()
        # ويندوز يمنح النافذة الجديدة الواجهة فور عرضها، فتنزل
        # البوابة خلفها — والبوابة هي التي تُغطّي المشهد الآن
        # (النظام شفافٌ تماماً بعد). رفعُها يُبقي الشاشة مشغولة
        # حتى تبدأ الموجة، فلا يظهر سطح المكتب لحظةً واحدة.
        try:
            gate.raise_()
            gate.activateWindow()
        except Exception:
            pass
        # ══ حارس التجمّد ══
        # يرصد توقّف خيط الواجهة عن معالجة أحداثه — وهو ما يراه
        # المستخدم «شاشة سوداء ولا يستجيب» — ويكتب في السجل موضعه
        # بالملف والسطر والدالة. لا يُعالج شيئاً؛ يجعل الشكوى دليلاً.
        try:
            from services import ui_watchdog
            ui_watchdog.start(win)
        except Exception:
            pass
        gate.hand_off(lambda: _reveal(win))

    def _on_signed_in(session):
        # مهلةٌ قصيرة: تُرسم رسالة الترحيب قبل أن يشغل البناءُ الخيط
        QtCore.QTimer.singleShot(80, lambda: _build_system(session))

    gate.on_signed_in = _on_signed_in
    # إغلاق البوابة قبل الدخول = إنهاء البرنامج، لا نافذةٌ معلّقة
    gate.rejected.connect(
        lambda: (None if holder.get("win") else app.quit()))
    return holder


def prepare_steps():
    """خطوات تجهيز النظام — تُعرض أسماؤها على البوابة وهي تُنفَّذ.

    كانت كتلةً واحدة صامتة؛ صارت خطواتٍ مسمّاة: من يقف أمام الشاشة
    يعرف أين وصل، ومن يُبلّغ عن عطلٍ يعرف **أي** خطوةٍ توقّفت.
    """
    from database.database import (create_tables, db, migrate_schema,
                                   run_migrations_files)
    from database.seed import (ensure_new_accounts, ensure_system_tags,
                               seed_initial_data)
    from models.entities import (ensure_employee_accrual_accounts,
                                 ensure_internal_counterparties)

    def _recover():
        # استرداد تلقائي: إن كانت القاعدة مفقودة تُسحب أحدث نسخة
        try:
            from services import storage
            rec = storage.auto_recover()
            if rec.get("recovered"):
                print(f"[recovery] استُعيدت البيانات من {rec['from']}")
        except Exception:
            pass

    def _identities():
        with db() as conn:
            ensure_internal_counterparties(conn)
            ensure_employee_accrual_accounts(conn)
            ensure_system_tags(conn)

    return [
        ("جارٍ تجهيز قاعدة البيانات…", create_tables),
        ("جارٍ التحقّق من سلامة البيانات…", _recover),
        ("جارٍ ترقية المخطّط…", migrate_schema),
        ("جارٍ تطبيق التحديثات…", run_migrations_files),
        ("جارٍ تهيئة شجرة الحسابات…", seed_initial_data),
        ("جارٍ ضبط الحسابات المستحدثة…", ensure_new_accounts),
        ("جارٍ تجهيز الجهات والوسوم…", _identities),
        ("جارٍ تشغيل الخدمات الخلفية…", start_background_workers),
    ]


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
