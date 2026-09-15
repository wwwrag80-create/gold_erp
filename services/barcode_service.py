# -*- coding: utf-8 -*-
"""باركود Code128 لأرقام التشغيل — **اختياري تماماً**.

قاعدة صارمة: توليد الباركود **لا يُعطّل أي عملية محاسبية أبداً**. فهو
تحسين بصري لا ركن من أركان القيد. لذلك تُلتقط كل الأخطاء هنا ويُعاد
`None` بهدوء، فيستمر التوريد والبيع بلا انقطاع.

سبب شائع للفشل: مكتبة `python-barcode` تحتاج ملف خط (`DejaVuSans.ttf`)
لكتابة الرقم أسفل الصورة، وهو غير مُرفق مع النسخة التنفيذية — فيرفع
`OSError: cannot open resource`. نتجاوزه بإيقاف كتابة النص، وإن فشل
مجدداً نتخطّى الباركود كلياً.
"""
import config

_WARNED = False


def _warn_once(err):
    """ينبّه مرة واحدة في السجل بلا إزعاج المستخدم."""
    global _WARNED
    if not _WARNED:
        _WARNED = True
        try:
            print(f"[barcode] معطّل: {type(err).__name__}: {err}")
        except Exception:
            pass


def generate_work_order_barcode(work_order_no: str):
    """يعيد مسار صورة الباركود، أو `None` عند أي تعذّر.

    لا يرفع استثناءً إطلاقاً — العمليات المحاسبية أهم من الباركود.
    """
    try:
        from barcode import Code128
        from barcode.writer import ImageWriter
    except Exception as e:
        _warn_once(e)
        return None

    try:
        config.BARCODE_DIR.mkdir(parents=True, exist_ok=True)
        safe = str(work_order_no).replace("/", "-").replace("\\", "-")
        # `write_text=False` يمنع الحاجة لملف الخط، وهو السبب الأشهر
        # لخطأ «cannot open resource» في النسخة التنفيذية.
        opts = {"write_text": False, "quiet_zone": 1.0,
                "module_height": 8.0}
        return Code128(str(work_order_no), writer=ImageWriter()).save(
            str(config.BARCODE_DIR / safe), options=opts)
    except Exception as e:
        _warn_once(e)
        return None
