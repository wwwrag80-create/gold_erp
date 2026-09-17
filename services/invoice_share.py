# -*- coding: utf-8 -*-
"""صفحة الفاتورة للجوال — ما يفتحه رمز QR المطبوع عليها.

**ما تعرضه**: الفاتورة أولاً (رقمها وتاريخها والعميل وأصنافها
وإجمالياتها)، ثم أسفلها موديلاتها — كل موديل بصورته واسمه وعدد قطعه
في هذه الفاتورة.

**أين تُنشر — وهذا هو الفرق الذي يهمّ العميل**:

1. **السحابة** إن كانت مهيّأة: تُرفع الصور والصفحة إلى تخزين المصنع
   السحابي فيصير الرابط عاماً يُفتح **من أي مكان وفي أي وقت** — من
   بيت العميل، بعد أسبوع، وجهاز المصنع مطفأ.
2. **شبكة المصنع** إن تعذّرت السحابة: الصفحة على الجهاز نفسه، ولا
   تُفتح إلا من جوالٍ متصل بشبكة المصنع وما دام النظام يعمل.

**ولماذا هذا التقسيم**: الرابط المحلي عنوانه `192.168.x.x` — وهو عنوان
لا معنى له خارج شبكة المصنع. فالموظف يفتحه لأنه على الشبكة، والعميل
يخرج بالفاتورة فلا يفتح شيئاً. النشر السحابي هو الحل الوحيد لأن تصل
الصفحة إلى جهازٍ ليس على الشبكة.

**الرابط لا يُخمَّن**: لكل فاتورة رمزٌ عشوائي يُحفظ معها، فلا يصل إلى
صفحتها إلا من بيده ورقتها. ويُعاد استعمال الرمز نفسه عند إعادة
الطباعة، فلا تتكاثر النسخ ولا يتغيّر رابط سُلّم للعميل.
"""
import hashlib
import html
import json
import mimetypes
import secrets
import urllib.error
import urllib.parse
import urllib.request

BUCKET = "invoice-photos"
SETTING_MODE = "invoice_share_mode"      # auto · cloud · lan · off
# مهلة قصيرة عن قصد: النشر يجري أثناء بناء ورقة الطباعة، فمهلةٌ طويلة
# على إنترنت متقطّع تُجمّد الطباعة دقيقة لكل صورة. وأول تعذّرٍ يُنهي
# المحاولة كلها بدل تكرار الانتظار صورةً صورة.
UPLOAD_TIMEOUT = 8

# ══════════════════════════════════════════════════════════════════
#  حجم ما يُرفع — وهو ما يحسم سؤال «هل تكفي مساحتي السحابية؟»
# ------------------------------------------------------------------
#  صورة الموديل من الكاميرا تزن 2–5 ميجابايت، وهي عرضٌ على شاشة جوال
#  عرضها 400 نقطة. فرفعها كما هي إسرافٌ بلا فائدة يُرى.
#
#  · **تصغير وضغط**: أقصى عرض 800 نقطة وجودة 62 — تنزل الصورة إلى
#    ‏40–80 كيلوبايت وتبقى واضحة تماماً على الجوال.
#  · **مرة واحدة لكل صورة**: الصور تُخزَّن ببصمة محتواها، فموديلٌ باعه
#    المصنع في مئة فاتورة تُرفع صورته **مرة واحدة** وتشير إليها
#    الفواتير كلها. وهذا هو الفرق الأكبر: بلا ذلك تتضاعف المساحة مع
#    كل فاتورة.
#  · صفحة الفاتورة نفسها نصٌّ لا يتجاوز بضعة كيلوبايتات.
#
#  فمصنعٌ بـ500 موديل يشغل نحو 30 ميجابايت مرةً واحدة، وكل ألف فاتورة
#  بعدها نحو 5 ميجابايت. وهذا جزءٌ يسير من أصغر باقة تخزين.
# ══════════════════════════════════════════════════════════════════
MAX_WIDTH = 800
JPEG_QUALITY = 62
SMALL_ENOUGH = 60 * 1024         # دون هذا الحجم لا داعي لإعادة الضغط


# ══════════════════════════════════════════════════════════════════
#  بيانات الصفحة
# ══════════════════════════════════════════════════════════════════

def invoice_data(conn, invoice_id):
    """بيانات الفاتورة كما تُعرض في الصفحة — بعيار المصنع المختار."""
    from models import invoices
    from services import karat_view as kv
    inv, items = invoices.get_invoice_full(conn, invoice_id)
    if not inv:
        return None
    cust = conn.execute("SELECT name FROM entities WHERE id=?",
                        (inv["customer_id"],)).fetchone()
    lines = []
    for it in items:
        wo = conn.execute(
            "SELECT work_order_no, model_no FROM work_orders WHERE id=?",
            (it["work_order_id"],)).fetchone()
        lines.append({
            "wo": (wo["work_order_no"] if wo else "—") or "—",
            "model": ((wo["model_no"] if wo else "") or "—"),
            "weight": kv.g(it["registered_weight"]),
            "wage": it["wages"] or 0.0,
        })
    return {
        "no": inv["invoice_no"],
        "date": inv["invoice_date"],
        "kind": "فاتورة مبيعات" if inv["kind"] == "sale" else "مرتجع مبيعات",
        "customer": (cust["name"] if cust else "—"),
        "lines": lines,
        "unit": kv.unit(),
        "weight": kv.g(inv["total_weight"]),
        "wages": inv["total_wages"] or 0.0,
        "vat": inv["vat_amount"] or 0.0,
        "total": inv["grand_total"] or 0.0,
        "vat_applied": bool(inv["vat_applied"]),
    }


def model_lines(conn, invoice_id):
    """موديلات الفاتورة: [(الموديل, العدد, الوزن, مسار الصورة أو None)].

    العدد عدد **قطع هذه الفاتورة** من الموديل لا رصيده في المخزن:
    السؤال هنا «ماذا في هذه الورقة؟» لا «كم عندنا منه؟».
    """
    from models import models_catalog as mc
    from services import karat_view as kv
    try:
        rows = conn.execute(
            "SELECT COALESCE(NULLIF(TRIM(w.model_no),''),'—') m,"
            " COUNT(*) n, ROUND(SUM(it.registered_weight),3) g"
            " FROM invoice_items it"
            " JOIN work_orders w ON w.id=it.work_order_id"
            " WHERE it.invoice_id=? GROUP BY m ORDER BY m",
            (invoice_id,)).fetchall()
    except Exception:
        return []
    out = []
    for r in rows:
        model = str(r["m"])
        path = None
        if model != "—":
            try:
                p = mc.image_path(model)
                path = str(p) if p is not None else None
            except Exception:
                path = None
        out.append({"model": model, "count": int(r["n"] or 0),
                    "weight": kv.g(r["g"] or 0), "path": path,
                    "unit": kv.unit()})
    return out


# ══════════════════════════════════════════════════════════════════
#  الصفحة
# ══════════════════════════════════════════════════════════════════

_PAGE = """<!DOCTYPE html>
<html dir="rtl" lang="ar"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
 :root {{ --gold:#9A7B22; --ink:#1F1B17; --mut:#6B6459; --line:#E3DDD0; }}
 * {{ box-sizing: border-box; }}
 body {{ font-family: system-ui, "Segoe UI", Tahoma, sans-serif; margin:0;
        padding:12px; background:#F5F2EA; color:var(--ink); }}
 .card {{ background:#fff; border:1px solid var(--line); border-radius:14px;
         padding:14px; margin-bottom:14px; }}
 h1 {{ font-size:17px; margin:0 0 3px; color:var(--gold); }}
 .sub {{ font-size:12px; color:var(--mut); margin-bottom:10px; }}
 .kv {{ display:flex; justify-content:space-between; font-size:14px;
       padding:6px 0; border-bottom:1px solid #F0EBE0; }}
 .kv b {{ font-weight:600; color:var(--mut); }}
 table {{ width:100%; border-collapse:collapse; font-size:13px;
         margin-top:8px; }}
 th {{ background:#F1ECE0; color:#4A4237; padding:7px 5px;
      border-bottom:2px solid #D8CDB4; font-size:12px; }}
 td {{ padding:7px 5px; border-bottom:1px solid #F0EBE0;
      text-align:center; }}
 tfoot td {{ font-weight:bold; background:#FAF8F3; }}
 h2 {{ font-size:15px; margin:16px 0 8px; color:var(--gold); }}
 .g {{ display:grid; gap:12px;
      grid-template-columns:repeat(auto-fill, minmax(150px,1fr)); }}
 .m {{ background:#fff; border:1px solid var(--line); border-radius:12px;
      overflow:hidden; }}
 .m img {{ width:100%; height:165px; object-fit:cover; display:block;
          background:#F1ECE0; }}
 .noimg {{ height:165px; display:flex; align-items:center;
          justify-content:center; color:#B3AB9A; font-size:13px;
          background:#F7F4EC; }}
 .mt {{ padding:8px; text-align:center; font-size:13px;
       border-top:1px solid #F0EBE0; }}
 .mt b {{ display:block; font-size:14px; margin-bottom:2px; }}
 .mt span {{ color:var(--mut); font-size:12px; }}
 .foot {{ text-align:center; color:#9A9384; font-size:11px;
         padding:10px 0 4px; }}
</style></head><body>
<div class="card">
  <h1>{kind} · {no}</h1>
  <div class="sub">{company}</div>
  <div class="kv"><b>التاريخ</b><span>{date}</span></div>
  <div class="kv"><b>العميل</b><span>{customer}</span></div>
  {table}
</div>
<h2>موديلات الفاتورة</h2>
<div class="g">{models}</div>
<div class="foot">{company} — صفحة الفاتورة</div>
</body></html>"""


def _esc(v):
    return html.escape(str(v if v is not None else ""))


def _table(d):
    rows = "".join(
        "<tr>"
        f"<td>{_esc(l['model'])}</td>"
        f"<td>{_esc(l['wo'])}</td>"
        f"<td>{l['weight']:,.3f}</td>"
        f"<td>{l['wage']:,.2f}</td>"
        "</tr>" for l in d["lines"])
    if not rows:
        rows = '<tr><td colspan="4">لا توجد أصناف</td></tr>'
    vat = ""
    if d["vat_applied"]:
        vat = (f'<tr><td colspan="3">ضريبة القيمة المضافة</td>'
               f'<td>{d["vat"]:,.2f}</td></tr>')
    return (
        '<table><thead><tr>'
        '<th>الموديل</th><th>رقم التشغيل</th>'
        f'<th>الوزن ({_esc(d["unit"])})</th><th>الأجرة</th>'
        '</tr></thead>'
        f'<tbody>{rows}</tbody><tfoot>'
        f'<tr><td colspan="2">الإجمالي</td>'
        f'<td>{d["weight"]:,.3f}</td><td>{d["wages"]:,.2f}</td></tr>'
        f'{vat}'
        f'<tr><td colspan="3">الإجمالي النهائي (ريال)</td>'
        f'<td>{d["total"]:,.2f}</td></tr>'
        '</tfoot></table>')


def page_html(data, models, img_src, company=""):
    """يبني الصفحة. `img_src(i)` يعيد عنوان صورة الموديل رقم i أو ""."""
    cards = []
    for i, m in enumerate(models):
        src = img_src(i) or ""
        pic = (f'<img src="{_esc(src)}" alt="{_esc(m["model"])}">' if src
               else '<div class="noimg">لا توجد صورة</div>')
        cards.append(
            f'<div class="m">{pic}<div class="mt">'
            f'<b>{_esc(m["model"])}</b>'
            f'<span>العدد: {m["count"]} · {m["weight"]:,.3f} '
            f'{_esc(m["unit"])}</span></div></div>')
    body = ("".join(cards) if cards
            else '<div class="card">لا توجد موديلات في هذه الفاتورة.</div>')
    return _PAGE.format(
        title=f'{_esc(data["kind"])} {_esc(data["no"])}',
        kind=_esc(data["kind"]), no=_esc(data["no"]),
        company=_esc(company), date=_esc(data["date"]),
        customer=_esc(data["customer"]), table=_table(data),
        models=body)


# ══════════════════════════════════════════════════════════════════
#  الصفحة **صورةً** — لأن التخزين السحابي لا يعرض HTML
# ------------------------------------------------------------------
#  **الخلل الذي عولج هنا**: رُفعت الصفحة بصيغة HTML فظهرت على جوال
#  العميل **كوداً نصّياً** لا فاتورة. السبب أن تخزين Supabase يقدّم
#  ملفات HTML بنوع `text/plain` عمداً — إجراءُ أمانٍ يمنع استضافة
#  صفحات تصيّد على نطاقه. فلا سبيل لجعله يعرض HTML مهما ضُبطت
#  الترويسات، والعلاج ليس في الترويسة بل في الصيغة.
#
#  **الصورة تُعرض دائماً**: لا متصفح يرفضها، ولا نوع محتوى يُعاد
#  كتابته، ولا خطّ عربي ناقص على جهاز العميل — النص مرسومٌ داخلها.
#  وتكبيرها باللمس أسهل من تكبير صفحة. والصفحة المحلية تبقى HTML
#  لأن خادم المصنع يقدّمها بنوعها الصحيح.
# ══════════════════════════════════════════════════════════════════

PAGE_WIDTH = 760
PAGE_QUALITY = 58
THUMB_W, THUMB_H = 352, 264

_C_BG = "#F5F2EA"
_C_CARD = "#FFFFFF"
_C_INK = "#1F1B17"
_C_MUT = "#6B6459"
_C_GOLD = "#8A6E1E"
_C_LINE = "#E0D9C8"
_C_HEAD = "#F1ECE0"


def _painter_ready():
    """هل يمكن الرسم؟ رسم النصوص يحتاج تطبيق واجهة قائماً."""
    try:
        from PyQt5.QtWidgets import QApplication
        return QApplication.instance() is not None
    except Exception:
        return False


def render_page_image(data, models, company="", width=PAGE_WIDTH):
    """يرسم صفحة الفاتورة صورةَ JPEG — أو b"" إن تعذّر الرسم."""
    if not _painter_ready():
        return b""
    try:
        from PyQt5.QtCore import QBuffer, QByteArray, QRect, Qt
        from PyQt5.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter
    except Exception:
        return b""
    p = None
    try:
        # لوحة طويلة تُقصّ عند آخر ما رُسم — أبسط من حساب الارتفاع
        # مرّتين، وأدقّ لأن لفّ النص العربي يقرّره القياس لا التقدير.
        img = QImage(width, 9000, QImage.Format_RGB32)
        img.fill(QColor(_C_BG))
        p = QPainter(img)
        # ══ الرسّام يُغلق دائماً ══
        # أي استثناء أثناء الرسم كان يترك الرسّام مفتوحاً على الصورة،
        # فيُجهض Qt التطبيق كلّه عند جمعها («Cannot destroy paint device
        # that is being painted»). خللٌ في تجميل يُسقط نظاماً محاسبياً —
        # فالإغلاق في `finally` لا في نهاية المسار الناجح وحده.
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setLayoutDirection(Qt.RightToLeft)

        pad, y = 18, 18
        inner = width - pad * 2
        AR = Qt.AlignRight | Qt.AlignVCenter
        AC = Qt.AlignCenter

        def font(size, bold=False):
            f = QFont("Segoe UI", size)
            f.setBold(bold)
            return f

        def text(s, x, yy, w, h, f, color, align=AR):
            p.setFont(f)
            p.setPen(QColor(color))
            p.drawText(QRect(int(x), int(yy), int(w), int(h)), align, str(s))

        def card(yy, h):
            p.setPen(QColor(_C_LINE))
            p.setBrush(QColor(_C_CARD))
            p.drawRoundedRect(QRect(pad, int(yy), inner, int(h)), 12, 12)

        # ── ترويسة الفاتورة ──
        rows = data["lines"]
        head_h = 96
        tbl_h = 34 + 30 * (len(rows) or 1) + 30 * (3 if data["vat_applied"]
                                                   else 2)
        box_h = head_h + tbl_h + 34
        card(y, box_h)
        text(f'{data["kind"]} · {data["no"]}', pad + 14, y + 12, inner - 28,
             30, font(15, True), _C_GOLD)
        text(company, pad + 14, y + 42, inner - 28, 20, font(9), _C_MUT)
        text(f'التاريخ: {data["date"]}', pad + 14, y + 64, inner - 28, 24,
             font(10), _C_INK)
        text(f'العميل: {data["customer"]}', pad + 14, y + 64, inner - 28, 24,
             font(10, True), _C_INK, Qt.AlignLeft | Qt.AlignVCenter)
        ty = y + head_h

        # ── جدول الأصناف ──
        cols = [("الموديل", 0.22), ("رقم التشغيل", 0.28),
                (f'الوزن ({data["unit"]})', 0.25), ("الأجرة", 0.25)]
        x0 = pad + 10
        tw = inner - 20
        p.setBrush(QColor(_C_HEAD))
        p.setPen(QColor(_C_LINE))
        p.drawRect(QRect(x0, int(ty), tw, 34))
        cx = x0 + tw
        for title, frac in cols:
            w = int(tw * frac)
            cx -= w
            text(title, cx, ty, w, 34, font(9, True), "#4A4237", AC)
        ty += 34
        for ln in (rows or [{}]):
            cx = x0 + tw
            vals = [ln.get("model", "—"), ln.get("wo", "—"),
                    f'{ln.get("weight", 0):,.3f}', f'{ln.get("wage", 0):,.2f}']
            for (t_, frac), v in zip(cols, vals):
                w = int(tw * frac)
                cx -= w
                text(v, cx, ty, w, 30, font(9), _C_INK, AC)
            p.setPen(QColor("#F0EBE0"))
            p.drawLine(x0, int(ty + 30), x0 + tw, int(ty + 30))
            ty += 30

        def total_row(label, value, bold=True):
            nonlocal ty
            p.setBrush(QColor("#FAF8F3"))
            p.setPen(QColor(_C_LINE))
            p.drawRect(QRect(x0, int(ty), tw, 30))
            text(label, x0 + 8, ty, tw - 16, 30, font(9, bold), _C_INK)
            text(value, x0 + 8, ty, tw - 16, 30, font(10, True), _C_GOLD,
                 Qt.AlignLeft | Qt.AlignVCenter)
            ty += 30

        total_row("إجمالي الوزن", f'{data["weight"]:,.3f} {data["unit"]}')
        if data["vat_applied"]:
            total_row("الأجور قبل الضريبة", f'{data["wages"]:,.2f}', False)
            total_row("ضريبة القيمة المضافة", f'{data["vat"]:,.2f}', False)
        total_row("الإجمالي النهائي (ريال)", f'{data["total"]:,.2f}')
        y += box_h + 16

        # ── الموديلات ──
        text("موديلات الفاتورة", pad + 4, y, inner - 8, 28, font(12, True),
             _C_GOLD)
        y += 32
        cols_n = 2
        cw = (inner - 12) // cols_n
        for idx, m in enumerate(models):
            col = idx % cols_n
            if col == 0 and idx:
                y += THUMB_H + 66
            cx = pad + (cols_n - 1 - col) * (cw + 12)
            p.setPen(QColor(_C_LINE))
            p.setBrush(QColor(_C_CARD))
            p.drawRoundedRect(QRect(int(cx), int(y), cw, THUMB_H + 58), 10, 10)
            ph = QRect(int(cx) + 6, int(y) + 6, cw - 12, THUMB_H)
            pic = QImage(str(m["path"])) if m.get("path") else QImage()
            if not pic.isNull():
                sc = pic.scaled(ph.width(), ph.height(), Qt.KeepAspectRatio,
                                Qt.SmoothTransformation)
                p.drawImage(ph.x() + (ph.width() - sc.width()) // 2,
                            ph.y() + (ph.height() - sc.height()) // 2, sc)
            else:
                p.setBrush(QColor("#F7F4EC"))
                p.setPen(QColor("#EDE6D8"))
                p.drawRect(ph)
                text("لا توجد صورة", ph.x(), ph.y(), ph.width(), ph.height(),
                     font(10), "#B3AB9A", AC)
            text(m["model"], cx + 6, y + THUMB_H + 8, cw - 12, 24,
                 font(11, True), _C_INK, AC)
            text(f'العدد: {m["count"]} · {m["weight"]:,.3f} {m["unit"]}',
                 cx + 6, y + THUMB_H + 30, cw - 12, 22, font(9), _C_MUT, AC)
        if models:
            y += THUMB_H + 66
        else:
            text("لا توجد موديلات في هذه الفاتورة.", pad + 4, y, inner - 8,
                 26, font(10), _C_MUT)
            y += 30

        text(company or "صفحة الفاتورة", pad, y + 4, inner, 24, font(8),
             "#9A9384", AC)
        y += 34
        p.end()

        out = img.copy(0, 0, width, min(int(y), img.height()))
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QBuffer.WriteOnly)
        ok = out.save(buf, "JPEG", PAGE_QUALITY)
        buf.close()
        return bytes(ba) if ok else b""
    except Exception:
        return b""
    finally:
        try:
            if p is not None and p.isActive():
                p.end()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════
#  الرمز المحفوظ مع الفاتورة
# ══════════════════════════════════════════════════════════════════

def _token(conn, invoice_id):
    """رمز الفاتورة العشوائي — يُنشأ مرة ويُعاد استعماله بعدها.

    ثباته مقصود: رابطٌ سُلّم للعميل يجب أن يبقى يعمل، وإعادة طباعة
    الفاتورة لا يجوز أن تُبطل ورقته الأولى.
    """
    try:
        r = conn.execute("SELECT share_token FROM invoices WHERE id=?",
                         (invoice_id,)).fetchone()
    except Exception:
        return None               # قاعدة قبل الترقية
    if r and (r["share_token"] or "").strip():
        return r["share_token"].strip()
    tok = secrets.token_urlsafe(12)
    try:
        conn.execute("UPDATE invoices SET share_token=? WHERE id=?",
                     (tok, invoice_id))
    except Exception:
        return None
    return tok


def cached_url(conn, invoice_id):
    """الرابط السحابي المنشور سابقاً لهذه الفاتورة، أو ""."""
    try:
        r = conn.execute("SELECT share_url FROM invoices WHERE id=?",
                         (invoice_id,)).fetchone()
        return (r["share_url"] or "").strip() if r else ""
    except Exception:
        return ""


def mode(conn):
    try:
        from models import fiscal
        m = (fiscal.get_setting(conn, SETTING_MODE, "") or "").strip()
    except Exception:
        m = ""
    return m if m in ("auto", "cloud", "lan", "off") else "auto"


def set_mode(conn, value, username=None):
    if value not in ("auto", "cloud", "lan", "off"):
        raise ValueError(f"وضع غير مدعوم: {value}")
    from models import fiscal
    fiscal.set_setting(conn, SETTING_MODE, value, username)
    return value


# ══════════════════════════════════════════════════════════════════
#  النشر السحابي
# ══════════════════════════════════════════════════════════════════

def _cloud_cfg():
    from services import tenant
    cfg = tenant.cloud_config()
    if not (cfg.get("url") and cfg.get("key")):
        return None
    return cfg["url"].rstrip("/"), cfg["key"]


def compress(path):
    """يصغّر صورة الموديل ويضغطها — (البايتات, نوعها).

    يستعمل Qt الموجود أصلاً في النظام (لا مكتبة صور إضافية قد لا تكون
    مثبّتة على جهاز المصنع). وإن تعذّر شيء تُعاد الصورة كما هي: صورةٌ
    كبيرة خيرٌ من صفحةٍ بلا صورة.
    """
    raw = open(path, "rb").read()
    ctype = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    if len(raw) <= SMALL_ENOUGH:
        return raw, ctype
    try:
        from PyQt5.QtCore import QBuffer, QByteArray
        from PyQt5.QtGui import QImage
        img = QImage()
        if not img.loadFromData(raw):
            return raw, ctype
        if img.width() > MAX_WIDTH:
            img = img.scaledToWidth(MAX_WIDTH, 1)   # 1 = Smooth
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QBuffer.WriteOnly)
        if not img.save(buf, "JPEG", JPEG_QUALITY):
            return raw, ctype
        out = bytes(ba)
        buf.close()
        # لا نستبدل صورةً بأكبر منها
        return (out, "image/jpeg") if 0 < len(out) < len(raw) \
            else (raw, ctype)
    except Exception:
        return raw, ctype


# ══════════════════════════════════════════════════════════════════
#  سجل ما رُفع — فلا تُرفع صورةٌ مرتين
# ══════════════════════════════════════════════════════════════════

def _asset_url(conn, sha):
    try:
        r = conn.execute("SELECT url FROM cloud_assets WHERE sha=?",
                         (sha,)).fetchone()
        return (r["url"] or "") if r else ""
    except Exception:
        return ""


def _link_asset(conn, invoice_id, sha):
    """يربط الصورة بالفاتورة التي تستعملها.

    بلا هذا الربط لا سبيل لمعرفة الصور التي لم تعد مستعملة، فتتراكم
    في التخزين إلى الأبد ولو حُذفت كل الفواتير التي كانت فيها.
    """
    try:
        conn.execute("INSERT OR IGNORE INTO invoice_assets(invoice_id,sha)"
                     " VALUES(?,?)", (int(invoice_id), str(sha)))
    except Exception:
        pass


def _asset_save(conn, sha, url, size):
    try:
        conn.execute(
            "INSERT OR REPLACE INTO cloud_assets(sha,url,size_bytes)"
            " VALUES(?,?,?)", (sha, url, int(size)))
    except Exception:
        pass


def _put(url, key, path, data, ctype):
    req = urllib.request.Request(
        f"{url}/storage/v1/object/{BUCKET}/{path}", data=data,
        method="POST",
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": ctype, "x-upsert": "true"})
    with urllib.request.urlopen(req, timeout=UPLOAD_TIMEOUT) as r:
        return r.status in (200, 201)


def public_url(url, path):
    return f"{url}/storage/v1/object/public/{BUCKET}/{path}"


def cloud_publish(conn, invoice_id, data, models, company=""):
    """يرفع الصفحة وصورها إلى تخزين المصنع ويعيد رابطها العام.

    يعيد "" عند أي تعذّر — مكتبة ناقصة، بلا إنترنت، مجلد تخزين غير
    موجود. فالطباعة لا تتوقف على شبكة، ويُكتفى بالرابط المحلي.
    """
    cfg = _cloud_cfg()
    if not cfg:
        return ""
    url, key = cfg
    tok = _token(conn, invoice_id)
    if not tok:
        return ""
    from services import tenant
    base = f"{tenant.effective_tenant_id()}/{tok}"

    tid = tenant.effective_tenant_id()

    # ══ الصفحة صورةٌ واحدة ══
    # التخزين يقدّم HTML بنوع `text/plain` فيظهر كوداً على الجوال
    # (الشرح في `render_page_image`). والصورة تُعرض دائماً، وهي
    # مكتفية بذاتها فلا تُرفع معها صور الموديلات منفصلةً — طلبٌ واحد
    # بدل عشرة، وملفٌ واحد بدل أحد عشر.
    shot = render_page_image(data, models, company)
    if shot:
        name = f"{base}/invoice.jpg"
        try:
            if _put(url, key, name, shot, "image/jpeg"):
                link = public_url(url, name)
                try:
                    conn.execute(
                        "UPDATE invoices SET share_url=? WHERE id=?",
                        (link, invoice_id))
                except Exception:
                    pass
                return link
        except Exception:
            pass
        return ""          # تعذّر الرفع — لا يُستبدل بصفحة لا تُعرض

    # لم يتيسّر الرسم (بلا واجهة رسومية): تُرفع الصفحة نصّاً مع صورها.
    # قد لا تُعرض على كل متصفح، لكنها خيرٌ من لا شيء.
    srcs = {}
    for i, m in enumerate(models):
        if not m["path"]:
            continue
        try:
            # ══ `raw` لا `data` ══
            # `data` هنا **بيانات الفاتورة** التي تُبنى منها الصفحة
            # أدناه. تسميةُ بايتات الصورة بالاسم نفسه كانت تدهسها،
            # فتُستدعى `page_html` ببايتات صورة بدل قاموس الفاتورة
            # فترفع استثناءً يبتلعه الحارس — فلا تُرفع صفحة ولا يُطبع
            # رمز، ولا يظهر سببٌ إطلاقاً. ولا يقع الخلل إلا حين يكون
            # لموديلٍ صورةٌ محفوظة، ولهذا مرّ من كل الفحوص التي لم
            # يكن فيها صورة.
            raw, ctype = compress(m["path"])
            sha = hashlib.sha1(raw).hexdigest()
            # ══ الصورة تُرفع مرةً واحدة مهما تكرّرت في الفواتير ══
            # البصمة من محتوى الصورة نفسها، فموديلٌ في مئة فاتورة
            # صورته كائنٌ واحد في التخزين تشير إليه المئة كلها.
            _link_asset(conn, invoice_id, sha)
            cached = _asset_url(conn, sha)
            if cached:
                srcs[i] = cached
                continue
            ext = "jpg" if ctype == "image/jpeg" else \
                (mimetypes.guess_extension(ctype) or ".jpg").lstrip(".")
            name = f"{tid}/models/{sha}.{ext}"
            if _put(url, key, name, raw, ctype):
                link = public_url(url, name)
                srcs[i] = link
                _asset_save(conn, sha, link, len(raw))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return ""         # المجلد غير موجود — لا جدوى من المتابعة
        except OSError:
            # انقطاع شبكة أو انتهاء مهلة: المحاولة كلها تُنهى هنا.
            # تكرارها لكل صورة يعني انتظاراً مضاعفاً وطباعةً متجمّدة.
            return ""
        except Exception:
            continue              # صورةٌ تعذّرت قراءتها: تُنشر الصفحة بدونها

    html_doc = page_html(data, models, lambda i: srcs.get(i, ""), company)
    try:
        if not _put(url, key, f"{base}/index.html",
                    html_doc.encode("utf-8"), "text/html; charset=utf-8"):
            return ""
    except Exception:
        return ""
    link = public_url(url, f"{base}/index.html")
    try:
        conn.execute("UPDATE invoices SET share_url=? WHERE id=?",
                     (link, invoice_id))
    except Exception:
        pass
    return link


# ══════════════════════════════════════════════════════════════════
#  النشر — سحابةً أو على شبكة المصنع
# ══════════════════════════════════════════════════════════════════

def enabled_for(conn, invoice_id):
    """هل طُلب رمزٌ لهذه الفاتورة بعينها؟

    القرار يُتخذ في شاشة المبيعات قبل الترحيل ويُحفظ مع الفاتورة. وما
    لم يُطلب لا يُبنى رمز ولا تُرفع صورة ولا تُستهلك مساحة — فالفواتير
    التي لا يحتاج أصحابها صورها لا تُكلّف شيئاً.
    """
    try:
        r = conn.execute("SELECT qr_enabled FROM invoices WHERE id=?",
                         (invoice_id,)).fetchone()
    except Exception:
        return False              # قاعدة قبل الترقية
    return bool(r and r["qr_enabled"])


def invalidate(conn, invoice_id):
    """يُعلِن أن صفحة الفاتورة لم تعد مطابقة لها — تُعاد كتابتها.

    يُستدعى عند **تعديل** الفاتورة: الورقة المطبوعة بيد العميل تحمل
    رمزاً يشير إلى رابطٍ ثابت، فلو بقيت الصفحة على مضمونها القديم لرأى
    العميل فاتورةً غير التي بيده. والرمز **لا يتغيّر** — يُعاد رفع
    الصفحة على المسار نفسه، فالورقة القديمة تظل صحيحة وتعرض الجديد.
    """
    try:
        conn.execute("UPDATE invoices SET share_url=NULL WHERE id=?",
                     (invoice_id,))
        return True
    except Exception:
        return False


_CANCELLED = """<!DOCTYPE html>
<html dir="rtl" lang="ar"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>فاتورة ملغاة</title>
<style>
 body {{ font-family: system-ui, "Segoe UI", Tahoma, sans-serif;
        background:#F5F2EA; color:#1F1B17; margin:0; padding:26px;
        text-align:center; }}
 .c {{ background:#fff; border:1px solid #E2C3C3; border-radius:14px;
      padding:26px 16px; max-width:420px; margin:40px auto; }}
 h1 {{ color:#A33131; font-size:19px; margin:0 0 10px; }}
 p {{ color:#6B6459; font-size:14px; line-height:1.9; margin:0; }}
</style></head><body>
<div class="c"><h1>⛔ هذه الفاتورة أُلغيت</h1>
<p>الفاتورة <b>{no}</b> أُلغيت في سجلات المصنع ولم تعد سارية.<br>
للاستفسار راجع {company}.</p></div></body></html>"""


def render_cancelled_image(invoice_no, company="", width=PAGE_WIDTH):
    """صورة «هذه الفاتورة أُلغيت» — أو b"" إن تعذّر الرسم."""
    if not _painter_ready():
        return b""
    p = None
    try:
        from PyQt5.QtCore import QBuffer, QByteArray, QRect, Qt
        from PyQt5.QtGui import QColor, QFont, QImage, QPainter
        img = QImage(width, 300, QImage.Format_RGB32)
        img.fill(QColor(_C_BG))
        p = QPainter(img)      # يُغلق في `finally` أدناه
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setLayoutDirection(Qt.RightToLeft)
        p.setPen(QColor("#E2C3C3"))
        p.setBrush(QColor(_C_CARD))
        p.drawRoundedRect(QRect(18, 30, width - 36, 240), 14, 14)
        f = QFont("Segoe UI", 17)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#A33131"))
        p.drawText(QRect(30, 70, width - 60, 46), Qt.AlignCenter,
                   "⛔ هذه الفاتورة أُلغيت")
        p.setFont(QFont("Segoe UI", 11))
        p.setPen(QColor(_C_MUT))
        p.drawText(QRect(40, 130, width - 80, 110),
                   Qt.AlignCenter | Qt.TextWordWrap,
                   f"الفاتورة {invoice_no} أُلغيت في سجلات المصنع ولم تعد "
                   f"سارية.\nللاستفسار راجع {company}.")
        p.end()
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QBuffer.WriteOnly)
        ok = img.save(buf, "JPEG", 70)
        buf.close()
        return bytes(ba) if ok else b""
    except Exception:
        return b""
    finally:
        try:
            if p is not None and p.isActive():
                p.end()
        except Exception:
            pass


def mark_cancelled(invoice_id, company=""):
    """يستبدل صفحة فاتورةٍ حُذفت بصفحة «أُلغيت».

    **لماذا لا تُحذف الصفحة**: من بيده الورقة سيصوّر رمزها يوماً ما.
    صفحةٌ مفقودة تُربكه، وصفحةٌ باقية بمضمونها القديم تُوهمه أن
    فاتورةً ملغاة ما زالت سارية — وهذا أخطر. الإعلان الصريح أصدق من
    الاثنين، وحجمه كيلوبايت واحد.
    """
    from database.database import db
    try:
        with db(readonly=True) as conn:
            if not cached_url(conn, invoice_id):
                return ""         # لم تُنشر أصلاً — لا شيء يُصحَّح
            r = conn.execute(
                "SELECT invoice_no, share_token FROM invoices WHERE id=?",
                (invoice_id,)).fetchone()
        if not r or not (r["share_token"] or "").strip():
            return ""
        cfg = _cloud_cfg()
        if not cfg:
            return ""
        url, key = cfg
        from services import tenant
        base = f"{tenant.effective_tenant_id()}/{r['share_token']}"
        # الإعلان صورةً كذلك: نفس سبب صفحة الفاتورة — التخزين لا يعرض
        # HTML، فإعلانٌ لا يُقرأ كإعلانٍ لم يكن.
        shot = render_cancelled_image(r["invoice_no"], company)
        if shot and _put(url, key, f"{base}/invoice.jpg", shot,
                         "image/jpeg"):
            return public_url(url, f"{base}/invoice.jpg")
        page = _CANCELLED.format(no=_esc(r["invoice_no"]),
                                 company=_esc(company))
        if _put(url, key, f"{base}/index.html", page.encode("utf-8"),
                "text/html; charset=utf-8"):
            return public_url(url, f"{base}/index.html")
    except Exception:
        pass
    return ""


def ensure_published(invoice_id, company=""):
    """ينشر صفحة الفاتورة سحابياً — **بعد الترحيل وخارج أي معاملة**.

    **لماذا هنا لا عند الطباعة**: بناء ورقة الطباعة يجري داخل معاملة
    كتابة مفتوحة. ورفعُ صورٍ عبر الإنترنت داخلها يحبس قفل الكتابة
    ثوانيَ — فتتعطّل النسخ الاحتياطي والمزامنة، وتتجمّد الواجهة. وهو
    عين الخلل الذي عولج من قبل حين كانت صورة QR تُبنى داخل المعاملة.

    فالرفع يجري مرةً واحدة عقب الترحيل (والقراءة عند الطباعة تجد
    الرابط جاهزاً)، والشبكة لا تُلامس قفل القاعدة أبداً.
    """
    from database.database import db
    try:
        with db(readonly=True) as conn:
            if mode(conn) not in ("auto", "cloud"):
                return ""
            if not enabled_for(conn, invoice_id):
                return ""
            if cached_url(conn, invoice_id):
                return cached_url(conn, invoice_id)
            data = invoice_data(conn, invoice_id)
            models = model_lines(conn, invoice_id)
        if not data:
            return ""
        with db() as conn:
            return cloud_publish(conn, invoice_id, data, models, company)
    except Exception:
        return ""             # النشر رفاهية لا تُعطّل ترحيلاً تمّ


def publish(conn, invoice_id, company="", allow_upload=False):
    """يعيد (الرابط، «cloud» أو «lan»)، أو ("", "") إن تعذّر كلاهما.

    `allow_upload=False` (وهو حال الطباعة): يُكتفى برابطٍ منشور سابقاً،
    ولا تُلامس الشبكةُ قفلَ الكتابة. الرفع فعلٌ صريح في
    `ensure_published` عقب الترحيل.
    """
    m = mode(conn)
    if m == "off" or not enabled_for(conn, invoice_id):
        return "", ""
    data = invoice_data(conn, invoice_id)
    if not data:
        return "", ""
    models = model_lines(conn, invoice_id)

    if m in ("auto", "cloud"):
        cached = cached_url(conn, invoice_id)
        if cached:
            return cached, "cloud"
        if allow_upload:
            # ══ تعثّر السحابة لا يجوز أن يمنع البديل المحلي ══
            # كان أي استثناء هنا — إعداداتٌ ناقصة، رفضٌ من التخزين،
            # انقطاعُ شبكة — يخرج من `publish` كلها فلا تُجرَّب الشبكة
            # المحلية أصلاً، ويُطبع المستند بلا رمز بلا أن يُعرف السبب.
            try:
                link = cloud_publish(conn, invoice_id, data, models,
                                     company)
            except Exception:
                link = ""
            if link:
                return link, "cloud"
        if m == "cloud":
            return "", ""

    # البديل المحلي: الصفحة نفسها على شبكة المصنع
    try:
        from services import photo_server
        link = photo_server.publish_page(
            data["no"],
            [(m2["model"], m2["path"]) for m2 in models],
            lambda src: page_html(data, models, src, company))
        return (link or ""), ("lan" if link else "")
    except Exception:
        return "", ""


# ══════════════════════════════════════════════════════════════════
#  التشخيص — لماذا لم يظهر الرمز؟
# ------------------------------------------------------------------
#  كل مسار في هذه الوحدة يعيد "" عند التعذّر ولا يرفع خطأً: ورقةٌ
#  محاسبية لا يجوز أن تتوقف طباعتها لأجل صورة. لكن الصمت الذي يحمي
#  الطباعة يُعمي المستخدم عن السبب — فيرى رمزاً لا يظهر بلا تفسير.
#  هذه الدالة تمشي المسار نفسه خطوةً خطوة وتقول أين توقّف بالضبط.
# ══════════════════════════════════════════════════════════════════

def diagnose(conn, invoice_id=None):
    """يفحص مسار رمز QR ويعيد [(الخطوة, نجحت؟, التفصيل)]."""
    out = []

    def add(step, ok, detail=""):
        out.append({"step": step, "ok": bool(ok), "detail": str(detail)})
        return ok

    # 1) مكتبة بناء الرمز
    try:
        import qrcode                      # noqa: F401
        add("مكتبة بناء الرمز (qrcode)", True, "مثبّتة")
    except Exception as e:
        add("مكتبة بناء الرمز (qrcode)", False,
            f"غير مثبّتة — {e}. بدونها لا يُبنى رمز إطلاقاً.")
        return out

    # 2) وضع الرمز
    m = mode(conn)
    labels = {"auto": "تلقائي (سحابة ثم شبكة المصنع)",
              "cloud": "السحابة فقط", "lan": "شبكة المصنع فقط",
              "off": "بلا رمز"}
    if not add("وضع الرمز", m != "off", labels.get(m, m)):
        return out

    # 3) الفاتورة المفحوصة
    if invoice_id is None:
        r = conn.execute(
            "SELECT id FROM invoices WHERE is_deleted=0"
            " ORDER BY id DESC LIMIT 1").fetchone()
        invoice_id = r["id"] if r else None
    if not add("آخر فاتورة", invoice_id is not None,
               f"رقم {invoice_id}" if invoice_id else "لا توجد فواتير"):
        return out

    # 4) هل فُعّل الرمز لهذه الفاتورة؟
    if not add("تفعيل الرمز لهذه الفاتورة", enabled_for(conn, invoice_id),
               "مفعَّل" if enabled_for(conn, invoice_id) else
               "غير مفعَّل — الخانة في شاشة المبيعات تُفعَّل **قبل** "
               "الترحيل، والقرار يُحفظ مع الفاتورة. الفواتير التي "
               "رُحّلت قبل تفعيلها تبقى بلا رمز."):
        return out

    # 5) موديلات الفاتورة وصورها
    models = model_lines(conn, invoice_id)
    with_img = [m2 for m2 in models if m2["path"]]
    add("موديلات الفاتورة", True,
        f"{len(models)} موديل · {len(with_img)} منها له صورة محفوظة")

    # 6) السحابة
    if m in ("auto", "cloud"):
        cached = cached_url(conn, invoice_id)
        if cached:
            add("رابط سحابي منشور سابقاً", True, cached)
            return out
        cfg = _cloud_cfg()
        if not add("إعدادات السحابة", cfg is not None,
                   "مهيّأة" if cfg else
                   "غير مهيّأة (SUPABASE_URL / KEY) — يُستعمل البديل "
                   "المحلي"):
            pass
        else:
            url, key = cfg
            # نوع المفتاح — بادئته وحدها، فلا يُكتب المفتاح في أي سجل
            k = str(key)
            kind = ("publishable (sb_publishable_…)"
                    if k.startswith("sb_publishable") else
                    "secret (sb_secret_…) ⚠ لا يصلح لبرنامج على أجهزة "
                    "المستخدمين" if k.startswith("sb_secret") else
                    "anon (JWT قديم)" if k.startswith("eyJ") else
                    "غير معروف")
            add("مفتاح السحابة", True, f"{kind} · الطول {len(k)}")

            # قراءة المجلد: تُثبت أن المفتاح يصل للمشروع والمجلد موجود
            try:
                _list(url, key, f"{tenant_id_safe()}/", limit=1)
                add("قراءة مجلد invoice-photos", True,
                    "المفتاح يصل للمشروع والمجلد موجود")
            except urllib.error.HTTPError as e:
                add("قراءة مجلد invoice-photos", False,
                    f"HTTP {e.code} — "
                    + ("المجلد غير موجود — أنشئه من Storage ← New bucket"
                       if e.code == 404 else "المفتاح لا يصل للمشروع"))
            except Exception as e:
                add("قراءة مجلد invoice-photos", False,
                    f"{type(e).__name__}: {e} (بلا إنترنت؟)")

            probe = f"{tenant_id_safe()}/_probe.txt"
            try:
                ok = _put(url, key, probe, b"ok", "text/plain")
                add("الرفع إلى مجلد invoice-photos", ok,
                    "نجح" if ok else "رُفض بلا رسالة")
            except urllib.error.HTTPError as e:
                body = ""
                try:
                    body = e.read().decode("utf-8", "ignore")[:200]
                except Exception:
                    pass
                deny = e.code in (400, 401, 403) or "row-level" in body
                hint = ("المجلد «invoice-photos» غير موجود — أنشئه من "
                        "Supabase ← Storage ← New bucket."
                        if e.code == 404 else
                        "المجلد موجود والرفع إليه ممنوع: تنقصه سياسة "
                        "كتابة. انسخ أمر SQL من زر «نسخ أمر SQL» "
                        "ونفّذه في Supabase ← SQL Editor — وهو يحذف "
                        "أي سياسة سابقة بنفس الاسم أولاً، فلا يفشل "
                        "بـ«already exists»." if deny else "")
                add("الرفع إلى مجلد invoice-photos", False,
                    f"HTTP {e.code} — {hint} {body}".strip())
            except Exception as e:
                add("الرفع إلى مجلد invoice-photos", False,
                    f"{type(e).__name__}: {e}")

    # 7) شبكة المصنع
    try:
        from services import photo_server
        addr = photo_server.ensure_running()
        add("خادم شبكة المصنع", bool(addr),
            f"يعمل على {addr[0]}:{addr[1]}" if addr
            else "تعذّر تشغيله (منفذ مشغول أو جدار حماية)")
    except Exception as e:
        add("خادم شبكة المصنع", False, f"{type(e).__name__}: {e}")

    # 8) النتيجة النهائية كما ستُطبع
    # الفحص فعلٌ صريح من المستخدم، فيُسمح فيه بالرفع ليُرى أثره فعلاً
    link, where = publish(conn, invoice_id, "", allow_upload=True)
    add("الرابط الذي سيحمله الرمز", bool(link),
        f"[{ 'سحابي' if where == 'cloud' else 'محلي' }] {link}" if link
        else "لا رابط — لن يُطبع رمز")

    # 9) **فتح الرابط فعلاً** — لا يكفي أن يُرفع، يجب أن يُعرض
    # الفحص السابق كان يقف عند «رُفع بنجاح»، فمرّت صفحةٌ رُفعت وقُدّمت
    # نصّاً فظهرت على الجوال كوداً. هذه الخطوة تفتح الرابط كما يفتحه
    # جوال العميل وتقرأ نوع المحتوى الذي يُقدَّم به.
    if link:
        try:
            req = urllib.request.Request(link, method="GET")
            with urllib.request.urlopen(req, timeout=UPLOAD_TIMEOUT) as r:
                ctype = (r.headers.get("Content-Type") or "").lower()
                size = len(r.read(4096))
            shows = ctype.startswith("image/") or "text/html" in ctype
            add("فتح الرابط كما يفتحه العميل", shows and size > 0,
                f"يُقدَّم بنوع «{ctype or '—'}»"
                + ("" if shows else
                   " — لن يُعرض كصفحة. صفحة الفاتورة تُرفع صورةً لهذا "
                   "السبب؛ إن ظهر هذا السطر فالمرفوع نصٌّ لا صورة."))
        except Exception as e:
            add("فتح الرابط كما يفتحه العميل", False,
                f"{type(e).__name__}: {e}")
    return out


POLICY_SQL = """-- صلاحيات مجلد صور الفواتير (نفّذه في Supabase ← SQL Editor)
-- يحذف أي سياسة سابقة بنفس الاسم أولاً، فلا يفشل بـ«already exists».
drop policy if exists "invoice photos read"   on storage.objects;
drop policy if exists "invoice photos upload" on storage.objects;
drop policy if exists "invoice photos update" on storage.objects;

create policy "invoice photos read" on storage.objects
  for select to public
  using (bucket_id = 'invoice-photos');

create policy "invoice photos upload" on storage.objects
  for insert to public
  with check (bucket_id = 'invoice-photos');

create policy "invoice photos update" on storage.objects
  for update to public
  using (bucket_id = 'invoice-photos')
  with check (bucket_id = 'invoice-photos');
"""


def policy_sql():
    """أمر SQL جاهز يمنح مجلد الصور صلاحية الكتابة.

    ثلاثة أشياء تجعله يعمل حيث فشل غيره:

    · **`drop policy if exists` أولاً** — فتكرار التنفيذ لا يرفع
      «already exists». وهذا الخطأ يُفشل الدفعة كلها في محرّر SQL،
      فيبقى ما بعده غير منفَّذ ويظن المستخدم أنه أتمّ العمل.
    · **`to public` لا `to anon`** — يشمل `anon` و`authenticated` معاً،
      فلا يتوقف الأمر على الدور الذي يحمله المفتاح.
    · **`with check` على التعديل أيضاً** — الرفع يجري بـ«استبدال إن
      وُجد» (upsert)، وهو إدراجٌ وتعديل معاً؛ فسياسة تعديلٍ بلا
      `with check` تمنع إعادة رفع صفحةٍ عُدّلت فاتورتها.
    """
    return POLICY_SQL


def republish_pending(company="", limit=200):
    """ينشر سحابياً كل فاتورة مفعَّلة لم يُنشر لها رابط بعد.

    يُستعمل بعد إصلاح صلاحيات المجلد: الفواتير التي رُحّلت والرفع
    ممنوع طُبعت برابطٍ محلي، وهذه تمنحها روابط تُفتح من أي مكان بلا
    إعادة ترحيل ولا مساس برقم محاسبي. والرمز المطبوع لا يتغيّر.
    """
    from database.database import db
    try:
        with db(readonly=True) as conn:
            if mode(conn) not in ("auto", "cloud"):
                return 0, 0
            ids = [r["id"] for r in conn.execute(
                "SELECT id FROM invoices WHERE is_deleted=0"
                " AND qr_enabled=1 AND COALESCE(share_url,'')=''"
                " ORDER BY id DESC LIMIT ?", (int(limit),))]
    except Exception:
        return 0, 0
    done = 0
    for i in ids:
        if ensure_published(i, company):
            done += 1
        elif done == 0:
            break             # أول فشلٍ قبل أي نجاح: العطل عام لا فردي
    return done, len(ids)


def tenant_id_safe():
    try:
        from services import tenant
        return tenant.effective_tenant_id()
    except Exception:
        return "unknown"


def report(conn, invoice_id=None):
    """تقرير التشخيص نصّاً عربياً جاهزاً للعرض."""
    lines = []
    for r in diagnose(conn, invoice_id):
        mark = "✔" if r["ok"] else "✘"
        lines.append(f"{mark} {r['step']}"
                     + (f"\n     {r['detail']}" if r["detail"] else ""))
    return "\n".join(lines)


def as_json(data, models):
    """تمثيل نصّي للصفحة — يُستعمل في الفحوص لا في العرض."""
    return json.dumps({"invoice": data, "models": models},
                      ensure_ascii=False, sort_keys=True)


# ══════════════════════════════════════════════════════════════════
#  المساحة المستعملة وتنظيفها
# ------------------------------------------------------------------
#  المساحة السحابية مدفوعة ومحدودة، فمن حقّ المستخدم أن يرى كم يشغل
#  ويحذف ما لم يعد يُطلب — لا أن يكتشف الامتلاء فجأة.
# ══════════════════════════════════════════════════════════════════

def _list(url, key, prefix="", limit=1000, timeout=25):
    """أسماء وأحجام ما في مجلد التخزين تحت بادئة معيّنة."""
    body = json.dumps({"prefix": prefix, "limit": int(limit),
                       "sortBy": {"column": "name", "order": "asc"}})
    req = urllib.request.Request(
        f"{url}/storage/v1/object/list/{BUCKET}",
        data=body.encode("utf-8"), method="POST",
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        rows = json.loads(r.read().decode("utf-8"))
    out = []
    for it in rows or []:
        meta = it.get("metadata") or {}
        out.append({"name": f"{prefix}{it.get('name', '')}",
                    "size": int(meta.get("size") or 0),
                    "at": str(it.get("created_at") or "")})
    return out


def _delete(url, key, names, timeout=30):
    """يحذف كائنات من التخزين — دفعةً واحدة."""
    if not names:
        return 0
    body = json.dumps({"prefixes": list(names)})
    req = urllib.request.Request(
        f"{url}/storage/v1/object/{BUCKET}",
        data=body.encode("utf-8"), method="DELETE",
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return len(names) if r.status in (200, 204) else 0


def orphan_images(conn):
    """الصور التي لم تعد تستعملها أي فاتورة منشورة — [(البصمة, الحجم)].

    الصورة تُرفع مرةً وتشترك فيها الفواتير. فمتى حُذفت صفحاتها كلها
    (بالتنظيف أو بحذف الفواتير) لم يبق لها مستعمل — وهي حينئذ مساحةٌ
    محجوزة بلا مقابل.
    """
    try:
        return [(r["sha"], int(r["size_bytes"] or 0)) for r in conn.execute(
            "SELECT a.sha, a.size_bytes FROM cloud_assets a"
            " WHERE NOT EXISTS ("
            "   SELECT 1 FROM invoice_assets ia"
            "   JOIN invoices i ON i.id=ia.invoice_id"
            "   WHERE ia.sha=a.sha AND i.is_deleted=0"
            "     AND COALESCE(i.share_url,'')<>'')")]
    except Exception:
        return []


def purge_orphan_images(conn, username=None):
    """يحذف من التخزين الصور التي لم تعد مستعملة، ويعيد عددها وحجمها."""
    rows = orphan_images(conn)
    if not rows:
        return 0, 0.0
    cfg = _cloud_cfg()
    if not cfg:
        return 0, 0.0
    url, key = cfg
    names, shas, size = [], [], 0
    for sha, sz in rows:
        r = conn.execute("SELECT url FROM cloud_assets WHERE sha=?",
                         (sha,)).fetchone()
        link = (r["url"] or "") if r else ""
        marker = f"/public/{BUCKET}/"
        if marker not in link:
            continue
        names.append(link.split(marker, 1)[1])
        shas.append(sha)
        size += sz
    done = 0
    for i in range(0, len(names), 100):
        try:
            done += _delete(url, key, names[i:i + 100])
        except Exception:
            break
    if done:
        qs = ",".join("?" * len(shas))
        conn.execute(f"DELETE FROM cloud_assets WHERE sha IN ({qs})", shas)
        conn.execute(f"DELETE FROM invoice_assets WHERE sha IN ({qs})", shas)
        try:
            from services.audit import log_action
            log_action(conn, username, "delete", "cloud_assets", None,
                       f"حذف {done} صورة غير مستعملة من التخزين")
        except Exception:
            pass
    return done, round(size / 1048576.0, 2)


def usage(conn):
    """ما تشغله صفحات الفواتير وصورها: عددٌ وحجمٌ بالميجابايت.

    الصور تُقرأ من السجل المحلي (سريع وبلا إنترنت)، وصفحات الفواتير
    تُعدّ من القاعدة نفسها.
    """
    out = {"images": 0, "image_mb": 0.0, "pages": 0, "page_mb": 0.0,
           "total_mb": 0.0}
    try:
        r = conn.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(size_bytes),0) s"
            " FROM cloud_assets").fetchone()
        out["images"] = int(r["n"] or 0)
        out["image_mb"] = round((r["s"] or 0) / 1048576.0, 2)
    except Exception:
        pass
    try:
        r = conn.execute(
            "SELECT COUNT(*) n FROM invoices"
            " WHERE COALESCE(share_url,'')<>''").fetchone()
        out["pages"] = int(r["n"] or 0)
        # الصفحة نصٌّ لا صور فيه — متوسطها نحو 5 كيلوبايت
        out["page_mb"] = round(out["pages"] * 5 / 1024.0, 2)
    except Exception:
        pass
    out["total_mb"] = round(out["image_mb"] + out["page_mb"], 2)
    try:
        orph = orphan_images(conn)
        out["orphans"] = len(orph)
        out["orphan_mb"] = round(sum(s for _h, s in orph) / 1048576.0, 2)
    except Exception:
        out["orphans"], out["orphan_mb"] = 0, 0.0
    return out


def purge_pages(conn, before_date, username=None):
    """يحذف صفحات الفواتير الأقدم من تاريخ — وصورها تبقى مشتركة.

    الصور **لا تُحذف**: كائنٌ واحد تشير إليه فواتير كثيرة، وحذفه
    لأجل فاتورة قديمة يُفرغ صور فواتير حديثة. وهي الجزء الصغير من
    المساحة أصلاً بعد الضغط.
    """
    cfg = _cloud_cfg()
    if not cfg:
        return 0
    url, key = cfg
    rows = conn.execute(
        "SELECT id, share_token FROM invoices"
        " WHERE COALESCE(share_url,'')<>'' AND invoice_date<?"
        " AND COALESCE(share_token,'')<>''", (str(before_date)[:10],)
    ).fetchall()
    if not rows:
        return 0
    from services import tenant
    tid = tenant.effective_tenant_id()
    # الاسمان معاً: الصفحة صورةٌ اليوم وكانت HTML قبله
    names = []
    for r in rows:
        names.append(f"{tid}/{r['share_token']}/invoice.jpg")
        names.append(f"{tid}/{r['share_token']}/index.html")
    n = 0
    for i in range(0, len(names), 100):        # دفعات معقولة
        try:
            n += _delete(url, key, names[i:i + 100])
        except Exception:
            break
    if n:
        conn.execute(
            "UPDATE invoices SET share_url=NULL"
            " WHERE COALESCE(share_url,'')<>'' AND invoice_date<?",
            (str(before_date)[:10],))
        try:
            from services.audit import log_action
            log_action(conn, username, "delete", "invoices", None,
                       f"حذف {n} صفحة فاتورة من التخزين السحابي")
        except Exception:
            pass
    return n
