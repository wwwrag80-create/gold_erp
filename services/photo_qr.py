# -*- coding: utf-8 -*-
"""رمز QR لصور موديلات الفاتورة.

يجمع صور موديلات أرقام تشغيل الفاتورة، ينشرها على شبكة المصنع
المحلية (`photo_server`)، ويعيد وسم `<img>` جاهزاً للقالب.

**قاعدة صارمة**: الرمز تحسين بصري لا ركن من أركان الفاتورة. أي تعذّر
— مكتبة ناقصة، منفذ مشغول، جدار حماية — يعيد `""` فتُطبع الفاتورة
كاملة بلا رمز. لا يجوز أن يمنع خللٌ في صورة طباعةَ مستند محاسبي.
"""
import base64
import io


def invoice_models(conn, invoice_id):
    """[(رقم الموديل, مسار صورته)] لأطقم الفاتورة التي لها صور.

    الموديل الواحد مرة واحدة ولو تكرر في أكثر من سطر.
    """
    try:
        from models import models_catalog as mc
        rows = conn.execute(
            "SELECT DISTINCT w.model_no m FROM invoice_items it"
            " JOIN work_orders w ON w.id=it.work_order_id"
            " WHERE it.invoice_id=? AND w.model_no IS NOT NULL"
            "   AND TRIM(w.model_no) <> ''"
            " ORDER BY w.model_no", (invoice_id,)).fetchall()
    except Exception:
        return []
    out = []
    for r in rows:
        try:
            p = mc.image_path(r["m"])
        except Exception:
            p = None
        if p is not None:
            out.append((str(r["m"]), str(p)))
    return out


def _png_gray(matrix, scale=4, border=2):
    """يكتب مصفوفة QR صورةَ PNG رمادية بلا أي مكتبة خارجية.

    **لماذا لا نستعمل `qrcode.make`**: هي تُنتج الصورة عبر Pillow،
    وPillow قد لا تكون مثبّتة على جهاز المصنع — فيختفي الرمز. أما
    مصفوفة الرمز فتُبنى بـpython خالص، وكتابة PNG منها لا تحتاج سوى
    `zlib` و`struct` من المكتبة القياسية. فالرمز يظهر دائماً.
    """
    import struct
    import zlib

    n = len(matrix)
    side = (n + border * 2) * scale
    white, black = b"\xff", b"\x00"
    rows = []
    blank = white * side
    for _ in range(border * scale):
        rows.append(b"\x00" + blank)
    for line in matrix:
        row = b"".join((black if cell else white) * scale for cell in line)
        row = white * (border * scale) + row + white * (border * scale)
        for _ in range(scale):
            rows.append(b"\x00" + row)
    for _ in range(border * scale):
        rows.append(b"\x00" + blank)

    def chunk(tag, data):
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body)))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", side, side, 8, 0,
                                         0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
            + chunk(b"IEND", b""))


def qr_png_bytes(text, box_size=4, border=2):
    """بايتات صورة PNG لرمز QR، أو b"" إن تعذّر بناؤها.

    تستعملها فاتورة الضريبة (`services.zatca`) وصفحة صور الموديلات
    معاً — بناءٌ واحد بلا مكتبات خارجية غير `qrcode` الخالصة.
    """
    try:
        import qrcode
        q = qrcode.QRCode(border=border, box_size=box_size)
        q.add_data(text)
        q.make(fit=True)
        return _png_gray(q.get_matrix(), scale=box_size, border=0)
    except Exception:
        return b""


def qr_png_data_uri(text, box_size=4, border=2):
    """صورة QR كـ data-URI، أو "" إن تعذّر بناؤها."""
    raw = qr_png_bytes(text, box_size, border)
    if not raw:
        return ""
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def qr_for_invoice(conn, invoice_id, invoice_no, size=112):
    """وسم QR لصور موديلات الفاتورة — أو "" إن تعذّر شيء.

    القيمة المعادة HTML جاهز للإدراج في القالب مباشرةً.
    """
    try:
        items = invoice_models(conn, invoice_id)
        if not items:
            return ""
        from services import photo_server
        url = photo_server.publish_invoice(invoice_no, items)
        if not url:
            return ""
        uri = qr_png_data_uri(url)
        if not uri:
            return ""
        # يلتصق بحافة الورقة اليمنى تحت عنوان المستند — لا يزاحم
        # جدول أرقام الفاتورة ولا يبتلع مساحتها.
        # يلتصق بحافة الورقة اليمنى تحت عنوان المستند — لا يزاحم
        # جدول أرقام الفاتورة ولا يبتلع مساحتها.
        return (
            f'<div style="text-align:right">'
            f'<img src="{uri}" width="{size}" height="{size}" alt="QR"/>'
            f'<div style="font-size:7.5pt; padding-top:2px;'
            f' text-align:right">صور الموديلات</div></div>')
    except Exception:
        return ""
