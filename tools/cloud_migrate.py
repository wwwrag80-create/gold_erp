# -*- coding: utf-8 -*-
"""مُهاجِر المخطط السحابي — ينشئ الجداول على Supabase تلقائياً.

يغنيك عن فتح محرر SQL يدوياً: يتصل بقاعدة PostgreSQL مباشرةً وينفّذ
`cloud/supabase_schema.sql` كاملاً داخل معاملة واحدة، ثم يتحقق من
الجداول ويسجّل مصنعك في جدول `factories`.

الاستخدام:
    pip install psycopg2-binary
    python tools/cloud_migrate.py                # ينفّذ الهجرة
    python tools/cloud_migrate.py --check        # يتحقق فقط بلا تعديل

بيانات الاتصال تُقرأ من ملف `.env`:
    SUPABASE_DB_HOST · SUPABASE_DB_PORT · SUPABASE_DB_NAME
    SUPABASE_DB_USER · SUPABASE_DB_PASSWORD
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app_config          # noqa: E402
from services import tenant  # noqa: E402

SCHEMA_FILE = ROOT / "cloud" / "supabase_schema.sql"

REQUIRED = ["factories", "sync_bundles", "journal_entries", "journal_lines",
            "invoices", "invoice_items", "vouchers", "voucher_lines",
            "work_orders"]


def _driver():
    """يعيد وحدة الاتصال المتاحة أو يشرح كيفية تثبيتها."""
    try:
        import psycopg2
        return psycopg2, "psycopg2"
    except ImportError:
        pass
    try:
        import psycopg
        return psycopg, "psycopg"
    except ImportError:
        pass
    print("✘ لا يوجد عميل PostgreSQL مثبَّت.")
    print("  ثبّته بهذا الأمر ثم أعد المحاولة:")
    print("      pip install psycopg2-binary")
    return None, None


def _dsn_from_args():
    """سلسلة اتصال من سطر الأوامر أو من .env أو بإدخال آمن."""
    for i, a in enumerate(sys.argv):
        if a == "--dsn" and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if a.startswith("--dsn="):
            return a.split("=", 1)[1]
    dsn = app_config.get("SUPABASE_DB_URL", "")
    return dsn or None


def _conn_params():
    host = app_config.get("SUPABASE_DB_HOST", "")
    port = app_config.get("SUPABASE_DB_PORT", "5432")
    name = app_config.get("SUPABASE_DB_NAME", "postgres")
    user = app_config.get("SUPABASE_DB_USER", "postgres")
    pwd = app_config.get("SUPABASE_DB_PASSWORD", "")
    missing = [k for k, v in (("SUPABASE_DB_HOST", host),
                              ("SUPABASE_DB_PASSWORD", pwd)) if not v]
    if not pwd and host:
        # إدخال آمن بلا تخزين كلمة المرور في أي ملف
        import getpass
        try:
            pwd = getpass.getpass("كلمة مرور قاعدة البيانات: ").strip()
        except Exception:
            pwd = ""
        missing = [] if pwd else ["SUPABASE_DB_PASSWORD"]
    if missing:
        print("✘ بيانات ناقصة في ملف .env: " + " · ".join(missing))
        print("  أضف كلمة مرور القاعدة (من Supabase → Settings → Database)")
        print("  ثم أعد التشغيل. مثال في .env:")
        print("      SUPABASE_DB_HOST=db.xxxx.supabase.co")
        print("      SUPABASE_DB_PASSWORD=************")
        return None
    return {"host": host, "port": int(port), "dbname": name,
            "user": user, "password": pwd, "connect_timeout": 20,
            "sslmode": "require"}


def _connect(drv, params):
    return drv.connect(**params)


def check(conn):
    """يتحقق من وجود الجداول ودالة الاستيعاب."""
    cur = conn.cursor()
    cur.execute(
        "SELECT table_name FROM information_schema.tables"
        " WHERE table_schema='public'")
    have = {r[0] for r in cur.fetchall()}
    missing = [t for t in REQUIRED if t not in have]
    for t in REQUIRED:
        print(f"  {'✔' if t in have else '✘'} {t}")
    cur.execute(
        "SELECT 1 FROM pg_proc WHERE proname='ingest_bundle' LIMIT 1")
    fn = cur.fetchone() is not None
    print(f"  {'✔' if fn else '✘'} دالة ingest_bundle")
    cur.close()
    return not missing and fn


def migrate(conn):
    """ينفّذ ملف المخطط كاملاً داخل معاملة واحدة."""
    if not SCHEMA_FILE.exists():
        print(f"✘ ملف المخطط غير موجود: {SCHEMA_FILE}")
        return False
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    cur = conn.cursor()
    try:
        cur.execute(sql)          # الملف كله idempotent (IF NOT EXISTS)
        conn.commit()
        print("✔ نُفِّذ المخطط بنجاح (الجداول والسياسات والدالة)")
        return True
    except Exception as e:
        conn.rollback()
        print(f"✘ فشل التنفيذ وتراجعت المعاملة بالكامل:\n  {e}")
        return False
    finally:
        cur.close()


def register_factory(conn):
    """يسجّل هذا المصنع في جدول factories إن لم يكن مسجّلاً."""
    tid = tenant.tenant_id()
    name = tenant.factory_name()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO factories(tenant_id, name, is_active)"
            " VALUES (%s, %s, TRUE) ON CONFLICT (tenant_id) DO NOTHING",
            (tid, name))
        conn.commit()
        print(f"✔ سُجّل المصنع: {name} — {tid}")
        return True
    except Exception as e:
        conn.rollback()
        print(f"⚠ تعذّر تسجيل المصنع: {e}")
        return False
    finally:
        cur.close()


def main():
    only_check = "--check" in sys.argv
    print("═" * 58)
    print("مُهاجِر المخطط السحابي — نظام جاديت")
    print("═" * 58)

    drv, drv_name = _driver()
    if drv is None:
        return 1
    dsn = _dsn_from_args()
    params = None
    if dsn:
        print(f"العميل  : {drv_name}")
        print("الخادم  : (من سلسلة الاتصال المُمرَّرة)")
    else:
        params = _conn_params()
        if params is None:
            return 1
        print(f"العميل  : {drv_name}")
        print(f"الخادم  : {params['host']}:{params['port']}/{params['dbname']}")
    print(f"المصنع  : {tenant.tenant_id()}")
    print("-" * 58)

    try:
        conn = drv.connect(dsn) if dsn else _connect(drv, params)
    except Exception as e:
        print(f"✘ تعذّر الاتصال بالقاعدة:\n  {e}")
        print("  تحقّق من: كلمة المرور · السماح بعنوانك في Supabase ·"
              " اتصال الإنترنت")
        return 1

    try:
        if only_check:
            print("فحص الجداول:")
            ok = check(conn)
        else:
            ok = migrate(conn)
            if ok:
                print("-" * 58)
                print("التحقق بعد التنفيذ:")
                ok = check(conn)
                if ok:
                    register_factory(conn)
        print("═" * 58)
        print("✔ السحابة جاهزة — شغّل النظام وستُرفع العمليات تلقائياً"
              if ok else "✘ لم تكتمل التهيئة — راجع الرسائل أعلاه")
        return 0 if ok else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
