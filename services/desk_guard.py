# -*- coding: utf-8 -*-
"""قفل التعديل والحذف في البرنامج برمز المدير (5.9).

يضبط المدير من رابطه («🔐 الرموز والأقفال» ← «رمز المدير») رمزاً واحداً،
فيُقفل به التعديل والحذف في البرنامج على كل جهاز: أي مستندٍ (فاتورة · سند ·
قيد · توريد · رواتب) وأي حسابٍ أو جهةٍ أو موديلٍ أو رقم تشغيل أو مجموعة —
لا يُعدَّل ولا يُحذف إلا بإدخال رمز المدير عند التنفيذ.

**أين يُطلب**: في الدوالّ المركزية التي يمرّ بها كل تعديلٍ وحذف (لا في كل
شاشةٍ على حدة) — فلا يفلت منه طريقٌ جديد. والطلب نفسه نافذةٌ يضعها البرنامج
عند بدئه (`set_prompt`)، فالنماذج لا تعرف الواجهة.

**ما لا يمسّه**: الرابط نفسه (له قفله الخاص في صفحته، ويعمل في خيط الخادم)،
والفحوص والأدوات بلا واجهة، والتسجيل الجديد (بيع · شراء · سند …) — القفل
للتعديل والحذف وحدهما.

**مرةٌ للعملية**: الرمز الصحيح يفتح دقيقةً واحدة — تكفي فتح المستند للتعديل
ثم حفظه — ثم يُقفل من جديد. وخمس محاولاتٍ خاطئة توقف الطلب عشر دقائق.
"""
import threading
import time

GRANT_SECONDS = 60
MAX_FAILS = 5
BLOCK_SECONDS = 600

_prompt = None
_grant_until = 0.0
_fails = 0
_blocked_until = 0.0


class ManagerCodeRequired(PermissionError):
    """أُلغي التعديل أو الحذف: يلزم رمز المدير."""


def set_prompt(fn):
    """يضعه البرنامج: `fn(action_text) -> str | None` (الرمز، أو None عند الإلغاء)."""
    global _prompt
    _prompt = fn


def reset():
    """للفحوص: يُنهي أي فتحٍ سابق وعدّاد المحاولات."""
    global _grant_until, _fails, _blocked_until
    _grant_until = 0.0
    _fails = 0
    _blocked_until = 0.0


def _mw():
    from services import manager_web
    return manager_web


def active(conn):
    """القفل يسري: للمدير رمزٌ وحاله «مقفل»."""
    try:
        return _mw().desk_locked(conn)
    except Exception:
        return False


def require(conn, action="التعديل والحذف"):
    """يُستدعى أول كل تعديلٍ أو حذف. يمرّ بلا سؤال إن لم يكن القفل مفعّلاً،
    أو كان الطلب من غير الواجهة؛ وإلا يطلب رمز المدير — والخطأ أو الإلغاء
    يرفع `ManagerCodeRequired` فلا يُنفَّذ شيء."""
    global _grant_until, _fails, _blocked_until
    if _prompt is None or threading.current_thread() is not threading.main_thread():
        return
    if not active(conn):
        return
    now = time.monotonic()
    if now < _grant_until:
        return
    if now < _blocked_until:
        mins = int((_blocked_until - now) // 60) + 1
        raise ManagerCodeRequired(
            f"محاولاتٌ خاطئة كثيرة لرمز المدير — انتظر {mins} دقيقة ثم حاول ثانيةً")
    pin = _prompt(action)
    if pin is None:
        raise ManagerCodeRequired(f"أُلغي — {action} مقفلٌ برمز المدير")
    if not _mw().check_desk_pin(conn, pin):
        _fails += 1
        if _fails >= MAX_FAILS:
            _fails = 0
            _blocked_until = time.monotonic() + BLOCK_SECONDS
        raise ManagerCodeRequired("رمز المدير غير صحيح — لم يُنفَّذ شيء")
    _fails = 0
    _grant_until = time.monotonic() + GRANT_SECONDS
