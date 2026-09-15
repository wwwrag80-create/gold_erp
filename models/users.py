# -*- coding: utf-8 -*-
"""المستخدمون: الاستعلام (التحقق من الدخول في services.auth)."""


def get_user(conn, username):
    return conn.execute(
        "SELECT * FROM users WHERE username=? AND is_active=1",
        (username,)).fetchone()


def list_users(conn):
    return conn.execute(
        "SELECT id, username, full_name, role, is_active FROM users"
        " ORDER BY id").fetchall()
