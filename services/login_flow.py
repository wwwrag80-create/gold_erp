# -*- coding: utf-8 -*-
"""مسار الدخول — منطقٌ واحد لشاشتَي الدخول.

**لماذا خرج المنطق من الشاشة**: الدخول ليس تحقّقاً من كلمة مرور
فحسب؛ بعده تُضبط هوية المصنع (وبها تُختار قاعدة بياناته)، وتُهيَّأ
قاعدته إن كانت جديدة، ويُستعاد آخر نسخةٍ سحابية إن كان الجهاز
جديداً. فلو نُسخ هذا كلُّه في شاشةٍ ثانية لتباعدت النسختان، ولدخل
المستخدم من إحداهما فرأى مصنعاً ومن الأخرى فرأى غيره — وهو أسوأ
خللٍ يمكن أن يقع في نظامٍ متعدّد المصانع.

فالمنطق هنا بلا أي عنصر واجهة: يُبلِّغ عن حاله برسائلَ عبر
`on_progress`، ويرفع `LoginError` برسالةٍ مفهومة عند الفشل.
"""


class LoginError(Exception):
    """فشلُ دخولٍ برسالةٍ تُعرض للمستخدم كما هي."""


def _noop(_msg):
    pass


def _diagnosed(msg):
    """يُلحق بالرسالة سببَ الفشل الحقيقي بدل غموضٍ لا يُعالَج."""
    try:
        from services import cloud_auth
        d = cloud_auth.diagnose()
        if not (d["url"] and d["pub"]):
            return msg + ("\n\nالسبب: إعدادات السحابة ناقصة في هذه "
                          "النسخة.")
        if not d["reachable"]:
            return msg + "\n\nالسبب: تعذّر الوصول للخادم — تحقق من الإنترنت."
        if not d["table"]:
            return msg + f"\n\nالسبب: {d['message']}"
    except Exception:
        pass
    return msg


def bootstrap_tenant_db():
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


def sign_in(username, password, on_progress=None, on_restored=None):
    """يُدخل المستخدم ويُعيد جلسته — أو يرفع `LoginError`.

    `on_progress(msg)` لسطر الحالة، و`on_restored(info)` يُنادى مرةً
    إن استُرجعت بيانات المصنع من النسخة السحابية.
    """
    say = on_progress or _noop
    user = str(username or "").strip()
    if not user:
        raise LoginError("أدخل اسم المستخدم")
    if not password:
        raise LoginError("أدخل كلمة المرور")

    from services import cloud_auth
    say("جارٍ التحقق…")
    try:
        session = cloud_auth.login(user, password)
    except Exception as e:                       # noqa: BLE001
        raise LoginError(_diagnosed(str(e)))

    # صلاحيات النظام المحلي تُشتق من صلاحية الحساب السحابي
    session["role_local"] = ("accountant" if session.get("is_super")
                             else "accountant")

    # ══ عزل البيانات ══
    # تُضبط هوية المصنع فوراً بعد التحقق، **قبل** أي قراءة أو كتابة —
    # فيُوجَّه النظام لقاعدة هذا المصنع وحده ولا يرى بيانات غيره.
    try:
        import config
        from services import tenant_db
        tid = session.get("tenant_id") or ""
        if tid:
            say("جارٍ تجهيز مساحة المصنع…")
            tenant_db.set_active_tenant(tid)
            if session.get("is_super"):
                tenant_db.migrate_legacy_into(config.BASE_DIR, tid)
            bootstrap_tenant_db()
    except Exception as e:                       # noqa: BLE001
        raise LoginError(f"تعذّر تجهيز مساحة عمل المصنع: {e}")

    # استرجاع تلقائي: نسخة جديدة عند مصنع له بيانات سحابية
    try:
        from services import cloud_backup
        say("جارٍ التحقق من بياناتك…")
        r = cloud_backup.auto_restore_if_needed(on_progress=say)
        if r.get("done") and on_restored:
            on_restored(r)
    except Exception:
        pass          # الاسترجاع لا يمنع الدخول أبداً
    say(session.get("notice") or "")
    return session


# ══════════════════════════════════════════════════════════════════
# اسمُ آخر من دخل — تيسيرٌ لا تخزينَ سرّ
# ══════════════════════════════════════════════════════════════════
#
# يُحفظ **الاسم وحده**؛ كلمة المرور لا تُكتب على القرص أبداً مهما
# بدا ذلك مريحاً. والملف في مساحة النظام لا في مجلد البرنامج، فيبقى
# مع المستخدم ولا يضيع مع كل تحديث.

def _last_user_path():
    from pathlib import Path

    import config
    d = Path(str(config.DB_PATH)).parent
    d.mkdir(parents=True, exist_ok=True)
    return d / "last_user.txt"


def load_last_user():
    try:
        p = _last_user_path()
        if p.exists():
            return p.read_text(encoding="utf-8").strip()[:80]
    except Exception:
        pass
    return ""


def save_last_user(username):
    try:
        name = str(username or "").strip()[:80]
        if name:
            _last_user_path().write_text(name, encoding="utf-8")
        else:
            p = _last_user_path()
            if p.exists():
                p.unlink()
        return True
    except Exception:
        return False
