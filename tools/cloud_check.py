# -*- coding: utf-8 -*-
"""أداة التحقق من الاتصال السحابي وتوافق الجداول.

الاستخدام:  python tools/cloud_check.py
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app_config          # noqa: E402
from services import tenant  # noqa: E402

REQUIRED_TABLES = ["factories", "sync_bundles", "journal_entries",
                   "journal_lines", "invoices", "invoice_items",
                   "vouchers", "voucher_lines", "work_orders"]


class BlockedError(Exception):
    """الطلب حُجب قبل الوصول للخادم (جدار حماية أو وكيل شبكة)."""


def _req(url, key, path, method="GET", body=None):
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{url.rstrip('/')}{path}", data=data, method=method,
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "x-tenant-id": tenant.tenant_id()})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        # تمييز حجب الشبكة عن استجابة الخادم الحقيقية
        if e.headers.get("x-deny-reason") or e.code == 403 and \
                b"allowlist" in (e.read() or b""):
            raise BlockedError(
                "الطلب محجوب من الشبكة قبل الوصول لـSupabase — "
                "تحقق من جدار الحماية أو إعدادات البروكسي")
        raise


def main():
    url = app_config.supabase_url()
    key = app_config.supabase_key()
    print("═" * 58)
    print("فحص الاتصال السحابي — نظام جاديت")
    print("═" * 58)
    print(f"الرابط : {url or '(غير مضبوط)'}")
    print(f"المفتاح: {(key[:24] + '…') if key else '(غير مضبوط)'}")
    print(f"هوية المصنع: {tenant.tenant_id()}")
    print("-" * 58)
    if not url or not key:
        print("✘ أكمل الرابط والمفتاح في ملف .env أولاً")
        return 1

    ok = True
    # 1) الاتصال الأساسي
    try:
        _req(url, key, "/rest/v1/")
        print("✔ الاتصال بالخادم ناجح")
    except BlockedError as e:
        print(f"✘ {e}")
        print("  لا يمكن إكمال الفحص — عالج الحجب ثم أعد التشغيل")
        return 2
    except urllib.error.HTTPError as e:
        print(f"{'✔' if e.code in (200, 401, 404) else '✘'} استجاب الخادم "
              f"(رمز {e.code})")
    except Exception as e:
        print(f"✘ تعذّر الاتصال: {e}")
        return 1

    # 2) الجداول المطلوبة
    print("-" * 58)
    missing = []
    for t in REQUIRED_TABLES:
        try:
            _req(url, key, f"/rest/v1/{t}?select=*&limit=1")
            print(f"  ✔ {t}")
        except BlockedError:
            print(f"  ⚠ {t} — تعذّر الفحص (الشبكة محجوبة)")
            ok = False
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                print(f"  ⚠ {t} — موجود لكن محمي بسياسة RLS")
            else:
                print(f"  ✘ {t} — غير موجود (رمز {e.code})")
                missing.append(t)
                ok = False
        except Exception as e:
            print(f"  ✘ {t} — {e}")
            missing.append(t)
            ok = False

    # 3) دالة الاستيعاب
    print("-" * 58)
    try:
        _req(url, key, "/rest/v1/rpc/ingest_bundle", "POST", {"batch": []})
        print("✔ دالة ingest_bundle موجودة وتعمل")
    except BlockedError:
        print("⚠ تعذّر فحص ingest_bundle (الشبكة محجوبة)")
        ok = False
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            print("⚠ ingest_bundle موجودة لكنها محمية بسياسة")
        else:
            print(f"✘ ingest_bundle غير موجودة (رمز {e.code}) — "
                  f"شغّل cloud/supabase_schema.sql")
            ok = False
    except Exception as e:
        print(f"✘ ingest_bundle: {e}")
        ok = False

    print("═" * 58)
    if ok and not missing:
        print("✔ السحابة جاهزة — شغّل النظام وستُرفع العمليات تلقائياً")
    else:
        print("✘ أكمل تشغيل cloud/supabase_schema.sql في محرر SQL بـSupabase")
        if missing:
            print(f"   الجداول الناقصة: {', '.join(missing)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
