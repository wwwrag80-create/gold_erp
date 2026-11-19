# -*- coding: utf-8 -*-
"""السنة التي يعمل فيها المستخدم الآن (5.9) — يختارها من زرّ «السنة».

بها تبدأ الشاشات فتراتها: «من» أول السنة، و«إلى» اليوم إن كانت السنة الجارية
أو آخرها (31-12) إن كانت سابقة؛ والفترات الجاهزة (هذا الشهر · هذا الربع ·
هذه السنة) تُحسب منها، وتاريخ المستند الجديد يبدأ بها.

تُحفظ لكل مستخدمٍ في قاعدة البيانات (`models.fiscal_years.work_year`) وتُحمَّل
عند الدخول. والرابط (خيط الخادم) لا يتبعها: يبقى على اليوم الحقيقي.
"""
import datetime as _dt

_state = {"year": None, "user": ""}


def today():
    return _dt.date.today()


def year():
    y = _state["year"]
    return int(y) if y else today().year


def load(conn, username):
    """عند الدخول: سنة هذا المستخدم المحفوظة (وإلا السنة الجارية)."""
    from models import fiscal_years
    _state["user"] = username or ""
    _state["year"] = fiscal_years.work_year(conn, username)
    return _state["year"]


def set_year(conn, username, y):
    from models import fiscal_years
    _state["user"] = username or _state["user"]
    _state["year"] = fiscal_years.set_work_year(conn, _state["user"], y)
    return _state["year"]


def is_current():
    return year() == today().year


def start():
    return _dt.date(year(), 1, 1)


def end():
    return _dt.date(year(), 12, 31)


def ref_date():
    """«اليوم» داخل السنة المختارة: اليوم نفسه في السنة الجارية، وآخر السنة
    لسنةٍ سابقة، وأولها لسنةٍ قادمة."""
    t, y = today(), year()
    if y == t.year:
        return t
    return _dt.date(y, 12, 31) if y < t.year else _dt.date(y, 1, 1)


# ── لشاشات Qt ──
def _q(d):
    from PyQt5 import QtCore
    return QtCore.QDate(d.year, d.month, d.day)


def qstart():
    return _q(start())


def qend():
    return _q(end())


def qref():
    return _q(ref_date())
