# -*- coding: utf-8 -*-
"""تحميل مسبق للوحدات الثقيلة في الخلفية.

**المشكلة التي يحلّها**: بعض الوحدات مكلفة عند أول استيراد — وأثقلها
`QtPrintSupport`، الذي يُعدّد طابعات النظام عند تحميله. على ويندوز مع
طابعات شبكية غير متصلة قد يستغرق ذلك ثوانيَ طويلة، وخيط الواجهة
متوقّف طوال ذلك فيعلن النظام «لا يستجيب» وتظهر شاشة بيضاء.

وهذا بالضبط ما كان يحدث عند **أول** حفظ تعديل سند أو قيد: مربع
«تم الترحيل» يستورد وحدة الطباعة لأول مرة فيتجمّد النظام قبل ظهوره.

**الحل**: تُحمَّل هذه الوحدات في خيط خلفي بعد الإقلاع بثوانٍ — بينما
المستخدم يقرأ الشاشة الأولى — فتكون جاهزة في الذاكرة عند أول استعمال
ولا يشعر بأي تأخير.
"""
import threading
import time

# الوحدات المكلفة، مرتّبة بحسب الأولوية
HEAVY = [
    "PyQt5.QtPrintSupport",     # الأثقل: يُعدّد الطابعات
    "services.print_manager",
    "services.browser_print",
    "PyQt5.QtSvg",
    # مكتبة رمز QR: أول استيراد لها يقع عند حفظ أول فاتورة ضريبية،
    # فيتجمّد الحفظ لحظتها. تحميلها هنا يجعله مجانياً.
    "qrcode",
]

_state = {"done": False, "loaded": [], "failed": [], "ms": 0}
_thread = None


def _load():
    import importlib
    t0 = time.time()
    for name in HEAVY:
        try:
            importlib.import_module(name)
            _state["loaded"].append(name)
        except Exception as e:
            _state["failed"].append(f"{name}: {type(e).__name__}")
    # خادم صور الموديلات: ربط المنفذ (وسؤال جدار الحماية على ويندوز)
    # يقع أول مرة عند الطباعة، فيبدو النظام متجمّداً خلف نافذة السؤال.
    # تشغيله هنا — في الخلفية بعد الإقلاع — ينقل ذلك بعيداً عن العمل.
    try:
        from services import photo_server
        photo_server.ensure_running()
        _state["loaded"].append("photo_server")
    except Exception as e:
        _state["failed"].append(f"photo_server: {type(e).__name__}")
    _state["ms"] = int((time.time() - t0) * 1000)
    _state["done"] = True


def start(delay=2.0):
    """يبدأ التحميل المسبق بعد تأخير قصير — لا يزاحم الإقلاع."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return _thread

    def runner():
        time.sleep(delay)
        _load()

    _thread = threading.Thread(target=runner, daemon=True,
                               name="JadeitePreload")
    _thread.start()
    return _thread


def ensure(timeout=0.0):
    """يضمن اكتمال التحميل — يُستدعى قبل أول استعمال فعلي.

    بلا مهلة يعود فوراً (التحميل جارٍ أو تمّ)؛ مع مهلة ينتظرها كحد
    أقصى فلا يتجمّد النظام مهما طال التحميل.
    """
    if _state["done"]:
        return True
    if _thread is None:
        start(delay=0.0)
    if timeout > 0 and _thread is not None:
        _thread.join(timeout)
    return _state["done"]


def status():
    return dict(_state)
