# -*- coding: utf-8 -*-
"""إنشاء حساب المدير العام في السحابة — مرة واحدة.

بعده تستطيع الدخول من **أي نسخة** بما فيها الـexe الموزَّع على
العملاء، وتظهر لك شاشات الإدارة تلقائياً.

الاستخدام:
    python tools/create_admin.py
"""
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app_config          # noqa: E402
from services import cloud_auth  # noqa: E402


def main():
    print("=" * 54)
    print("  Create Super Admin account")
    print("=" * 54)
    if not app_config.supabase_service_key():
        print("  [ERROR] SUPABASE_SERVICE_KEY is missing in .env")
        print("  Get it from: Supabase > Settings > API > service_role")
        return 1
    print(f"  Cloud: {app_config.supabase_url()}")
    print("-" * 54)

    u = input("  Username: ").strip()
    if not u:
        print("  [ERROR] Username required")
        return 1
    p1 = getpass.getpass("  Password: ")
    p2 = getpass.getpass("  Confirm : ")
    if p1 != p2:
        print("  [ERROR] Passwords do not match")
        return 1
    if len(p1) < 4:
        print("  [ERROR] Password too short (min 4)")
        return 1

    try:
        r = cloud_auth.create_admin(u, p1)
    except Exception as e:
        msg = str(e)
        if "مستخدم مسبقاً" in msg or "already" in msg.lower():
            print(f"  [ERROR] Username '{u}' already exists.")
            print("          It was created before - just sign in with it.")
            print("          Or pick another username.")
        else:
            # تفادي العربية في نافذة الأوامر (تظهر مربعات)
            try:
                print(f"  [ERROR] {msg}")
            except Exception:
                print("  [ERROR] Could not create the account.")
        return 1

    print("-" * 54)
    print(f"  SUCCESS: admin account '{r['username']}' created")
    print("  You can now sign in with it from ANY copy,")
    print("  including the exe you send to factories.")
    print("=" * 54)
    return 0


if __name__ == "__main__":
    sys.exit(main())
