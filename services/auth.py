# -*- coding: utf-8 -*-
"""تسجيل الدخول والصلاحيات: PBKDF2-HMAC-SHA256 (مكتبة قياسية)."""
import hashlib
import os

ITER = 200_000
ROLE_LABELS = {"accountant": "محاسب (كامل الصلاحيات)", "sales": "مبيعات"}


def hash_password(plain: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, ITER)
    return salt.hex() + "$" + dk.hex()


def verify_password(plain: str, stored: str) -> bool:
    try:
        salt_hex, dk_hex = stored.split("$", 1)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"),
                             bytes.fromhex(salt_hex), ITER)
    return dk.hex() == dk_hex


def verify_login(username: str, plain: str):
    """يعيد بيانات المستخدم dict عند النجاح وإلا None، مع تسجيل المحاولة."""
    from database.database import db
    from services.audit import log_action
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username=? AND is_active=1",
            (username,)).fetchone()
        ok = bool(row) and verify_password(plain, row["password_hash"])
        log_action(conn, username, "login_ok" if ok else "login_failed", "users",
                   row["id"] if row else None, "")
        return dict(row) if ok else None
