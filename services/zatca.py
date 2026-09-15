# -*- coding: utf-8 -*-
"""QR الفوترة الإلكترونية — هيئة الزكاة والضريبة والجمارك (TLV → Base64)."""
import base64

import config

QR_DIR = config.BASE_DIR / "assets" / "qrcodes"


def _tlv(tag: int, value: str) -> bytes:
    b = value.encode("utf-8")
    return bytes([tag, len(b)]) + b


def build_tlv_base64(seller_name: str, vat_number: str, timestamp_iso: str,
                     invoice_total: float, vat_total: float) -> str:
    payload = (_tlv(1, seller_name) + _tlv(2, vat_number) +
               _tlv(3, timestamp_iso) + _tlv(4, f"{invoice_total:.2f}") +
               _tlv(5, f"{vat_total:.2f}"))
    return base64.b64encode(payload).decode("ascii")


def generate_qr_image(b64_payload: str, name: str):
    """يحفظ صورة QR ويعيد مسارها، أو `None` عند أي تعذّر.

    **قاعدة صارمة**: توليد الصورة تحسين بصري لا ركن من أركان القيد،
    فلا يجوز أن يمنع حفظ فاتورة. تُلتقط كل الأخطاء — لا الاستيراد
    وحده — لأن فشل الكتابة أو الخطوط يرفع أخطاء أخرى.
    """
    try:
        import qrcode
        QR_DIR.mkdir(parents=True, exist_ok=True)
        safe = str(name).replace("/", "-").replace("\\", "-")
        path = QR_DIR / f"{safe}.png"
        qrcode.make(b64_payload).save(str(path))
        return str(path)
    except Exception:
        return None          # النص البديل يُعرض في الفاتورة
