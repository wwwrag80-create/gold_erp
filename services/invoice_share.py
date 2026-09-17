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
    srcs = {}
    for i, m in enumerate(models):
        if not m["path"]:
            continue
        try:
            data, ctype = compress(m["path"])
            sha = hashlib.sha1(data).hexdigest()
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
            if _put(url, key, name, data, ctype):
                link = public_url(url, name)
                srcs[i] = link
                _asset_save(conn, sha, link, len(data))
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
        path = f"{tenant.effective_tenant_id()}/{r['share_token']}/index.html"
        page = _CANCELLED.format(no=_esc(r["invoice_no"]),
                                 company=_esc(company))
        if _put(url, key, path, page.encode("utf-8"),
                "text/html; charset=utf-8"):
            return public_url(url, path)
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
                hint = {
                    404: "المجلد «invoice-photos» غير موجود — أنشئه من "
                         "Supabase ← Storage ← New bucket.",
                    403: "المجلد موجود لكن الرفع ممنوع: ينقصه إذن "
                         "الكتابة (Policy). أضف من Storage ← Policies "
                         "سياسةً تسمح بـINSERT و UPDATE على "
                         "«invoice-photos» للدور anon.",
                    400: "رُفض الطلب — غالباً سياسة أمان ناقصة على "
                         "المجلد (Policies).",
                }.get(e.code, "")
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
    return out


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
    names = [f"{tid}/{r['share_token']}/index.html" for r in rows]
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
