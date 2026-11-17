# -*- coding: utf-8 -*-
"""رابط المدير — الهيكل الجديد (5.6.0).

أول ما يُفتح الرابط **شاشةٌ رئيسية بلوحات** — هادئةٌ مرتّبة كشاشة البرنامج:

  ① **الدليل** (أول لوحة) — صور الموديلات، وكم بالخزنة وعند من، والمتاح للبيع.
  ② **الصناديق** — أقسامٌ يسمّيها المدير ويضع فيها ما يشاء من الحسابات،
     ولكلّ قسمٍ جدول حساباته بأرصدتها (ذهب · نقد). إضافة الحساب باسمه:
     يكتب أول حرف فتظهر الأسماء المتقاربة.
  ③ **فواتير / حركة المصنع** — لوحاتٌ بالأنواع: الوارد · المبيعات · المرتجعات · القبض
     · الصرف · القيود اليومية · التسكير. يُختار نوعٌ وفترةٌ فيظهر سجلّه: كل
     عمليةٍ بطرفها ووزن ما أخذ، ولها «عرض الصور» و«عرض الفاتورة».
  ④ **كشف حساب** — يُكتب الاسم فيظهر كشفه، ولكل حركةٍ الصور والفاتورة.
  ⑤ **تسجيل عمليات** — بيع · مرتجع · قبض · صرف · قيد يومي · توريد، بخانات
     شاشات البرنامج نفسها، تُرحَّل في قاعدة جهاز المصنع **بدوالّ البرنامج
     نفسها** (`invoices` · `vouchers` · `journal` · `inventory`) — فكل تحقّقٍ
     في البرنامج يسري هنا كما هو، والعملية كأنها أُدخلت من الجهاز.

**الحماية في الكتابة** — ولا كتابة بغيرها:
  * التسجيل لا يعمل إلا ورمز الدخول (PIN) مضبوط للرابط، ومع تفعيله من
    البرنامج («السماح بتسجيل العمليات من الرابط»).
  * كل طلب كتابة يحمل رمز التحقق من الصفحة نفسها (CSRF) — صفحةٌ من موقعٍ
    آخر لا تعرفه فلا تكتب.
  * ولكل ترحيلٍ رقمٌ فريد من المتصفح (nonce): الضغط مرتين أو إعادة الإرسال
    بعد انقطاعٍ يعيد نتيجة الترحيل الأول ولا يرحّل ثانيةً.
  * الترحيل واحدٌ بعد واحد (قفل)، وفي معاملةٍ ذرّية: يُحفظ كله أو لا شيء.
  * المستخدم في كل مستندٍ وسجل التتبع «رابط المدير».
"""
import hmac
import json
import re
import threading
from collections import OrderedDict
from urllib.parse import parse_qs, quote

from services import numfmt as _nf

WEB_USER = "رابط المدير"
K_BOXES = "mw_boxes"
K_SCRAP_OFF = "mw_boxes_scrap_off"  # "1" = حذف المدير «صندوق الكسر» من الصناديق
K_OPS = "mw_ops_enabled"          # "0" = موقوف من البرنامج
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_post_lock = threading.Lock()
_nonces = OrderedDict()            # nonce → ردّ الترحيل الأول
_NONCE_CAP = 600


# ══════════════════════════════════════════════════════════════════
#  أدوات
# ══════════════════════════════════════════════════════════════════

def _mw():
    from services import models_web
    return models_web


def _e(v):
    return _mw()._e(v)


def _w(v):
    """وزنٌ مخزَّن (مكافئ 18) بعيار العرض."""
    return _mw()._w(v)


def _m(v):
    return _nf.f2(float(v or 0))


def _unit():
    from services import karat_view as kv
    return kv.unit()


def _resp(code, body, ctype="text/html; charset=utf-8", headers=None):
    return _mw()._resp(code, body, ctype, headers)


def _json(obj, code=200):
    return _resp(code, json.dumps(obj, ensure_ascii=False),
                 "application/json; charset=utf-8",
                 {"Cache-Control": "no-store"})


def _link(base, path="", **kw):
    q = "&".join(f"{k}={quote(str(v))}" for k, v in kw.items()
                 if v not in (None, ""))
    return base + path + ("?" + q if q else "")


def _today():
    import datetime as _dt
    return _dt.date.today()


def _date(v, default=""):
    v = str(v or "").strip()
    return v if _DATE.match(v) else default


def _get(conn, key, default=""):
    return _mw()._get(conn, key, default)


def _set(conn, key, value, username=WEB_USER):
    return _mw()._set(conn, key, value, username)


def ops_enabled(conn):
    """التسجيل من الرابط مسموحٌ؟ (يُوقف من نافذة الرابط في البرنامج)"""
    return _get(conn, K_OPS, "1") != "0"


def set_ops_enabled(conn, on, username=None):
    _set(conn, K_OPS, "1" if on else "0", username or WEB_USER)


# 5.7.0: رمزٌ خاص بلوحة «تسجيل العمليات» — يُطلب قبل التسجيل والتعديل
# والحذف والدمج من الرابط (ولو فُتح الرابط نفسه). يُضبط من نافذة «🔗 رابط
# المدير» في البرنامج، ويبقى مفتوحاً على الجهاز 12 ساعة بملف تعريفٍ موقَّع.
K_OPS_PIN = "mw_ops_pin"
OPS_COOKIE = "mwop"
OPS_HOURS = 12


def has_ops_pin(conn):
    return bool(_get(conn, K_OPS_PIN, "").strip())


def set_ops_pin(conn, pin, username=None):
    """رمز لوحة تسجيل العمليات: 4 إلى 12 خانة — وفارغٌ يلغيه."""
    pin = str(pin or "").strip()
    if pin and not (4 <= len(pin) <= 12):
        raise ValueError("رمز اللوحة من 4 إلى 12 خانة")
    _set(conn, K_OPS_PIN, _mw()._hash_pin(pin) if pin else "",
         username or WEB_USER)
    _mw()._audit(conn, username, "تعيين رمز لوحة تسجيل العمليات" if pin
                 else "إلغاء رمز لوحة تسجيل العمليات")


def _ops_cookie_value(csrf, h):
    import hashlib
    return hmac.new(str(csrf).encode("utf-8"), f"ops|{h}".encode("utf-8"),
                    hashlib.sha256).hexdigest()[:40]


def ops_unlocked(conn, headers, csrf):
    """اللوحة مفتوحة: لا رمز لها، أو معه ملف تعريفها الموقَّع."""
    h = _get(conn, K_OPS_PIN, "").strip()
    if not h:
        return True
    got = _mw()._cookies(headers).get(OPS_COOKIE, "")
    return bool(got) and hmac.compare_digest(got, _ops_cookie_value(csrf, h))


# 5.7.6: «قفل التعديل والحذف» — زرٌّ في أعلى كل صفحة من الرابط يقفل
# التعديل والحذف والعكس والدمج (في الكشوف وحركة المصنع ولوحة التسجيل
# وأقسام الصناديق) أو يفتحها، برمزٍ يُضبط من نافذة «🔗 رابط المدير» في
# البرنامج. القفل حالٌ واحدة في دفاتر المصنع تسري على كل من يفتح الرابط،
# والتحقّق منه عند الحفظ نفسه لا في الصفحة وحدها.
K_EDIT_PIN = "mw_edit_pin"
K_EDIT_LOCK = "mw_edit_locked"
EDIT_LOCKED_MSG = ("التعديل والحذف مقفلان في الرابط — افتح القفل من زر "
                   "«🔒» في أعلى الصفحة برمزه")


def has_edit_pin(conn):
    return bool(_get(conn, K_EDIT_PIN, "").strip())


def edits_locked(conn):
    """القفل يسري ما دام له رمز وحاله «مقفل»."""
    return has_edit_pin(conn) and _get(conn, K_EDIT_LOCK, "0") == "1"


def set_edits_locked(conn, on, username=None):
    _set(conn, K_EDIT_LOCK, "1" if on else "0", username or WEB_USER)
    _mw()._audit(conn, username or WEB_USER,
                 "قفل التعديل والحذف في رابط المدير" if on
                 else "فتح التعديل والحذف في رابط المدير")


def set_edit_pin(conn, pin, username=None):
    """رمز قفل التعديل والحذف: 4 إلى 12 خانة — وفارغٌ يلغيه ويفتح القفل
    (فلا يبقى الرابط مقفلاً بلا رمزٍ يفتحه)."""
    pin = str(pin or "").strip()
    if pin and not (4 <= len(pin) <= 12):
        raise ValueError("رمز القفل من 4 إلى 12 خانة")
    _set(conn, K_EDIT_PIN, _mw()._hash_pin(pin) if pin else "",
         username or WEB_USER)
    if not pin:
        _set(conn, K_EDIT_LOCK, "0", username or WEB_USER)
    _mw()._audit(conn, username, "تعيين رمز قفل التعديل والحذف في الرابط"
                 if pin else "إلغاء رمز قفل التعديل والحذف في الرابط")


def _edit_lock_state():
    """(له رمز؟، مقفل؟) — لرأس كل صفحة."""
    try:
        from database.database import db
        with db(readonly=True) as conn:
            return has_edit_pin(conn), edits_locked(conn)
    except Exception:
        return False, False


def edit_lock_action(data):
    """زرّ القفل في الرابط: يقفل أو يفتح بالرمز — والمحاولات الخاطئة
    تُحصى كرمز الدخول (ربع ساعة بعد تكرارها)."""
    from database.database import db
    m = _mw()
    want = bool(data.get("lock"))
    with _post_lock:
        with db(readonly=True) as conn:
            h = _get(conn, K_EDIT_PIN, "").strip()
        if not h:
            return {"ok": False, "error": "لا رمز للقفل بعد — اضبطه من "
                    "البرنامج: «🔗 رابط المدير» ← «رمز قفل التعديل والحذف»"}
        if m._locked():
            return {"ok": False, "error": "محاولات كثيرة — انتظر ربع ساعة ثم"
                                          " حاول ثانيةً"}
        if not m._pin_ok(h, str(data.get("pin") or "").strip()):
            m._fail()
            return {"ok": False, "error": "الرمز غير صحيح"}
        with db() as conn:
            set_edits_locked(conn, want)
    return {"ok": True, "locked": want,
            "msg": "قُفل التعديل والحذف في الرابط" if want
            else "فُتح التعديل والحذف في الرابط"}


def _safe_next(base, nxt):
    nxt = str(nxt or "")
    if nxt.startswith(base + "/") and "//" not in nxt[len(base):] \
            and "\\" not in nxt and "\n" not in nxt and "\r" not in nxt:
        return nxt
    return base + "/ops"


def _norm(t):
    t = str(t or "").strip().lower()
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ة", "ه"), ("ى", "ي"),
                 ("ـ", "")):
        t = t.replace(a, b)
    return " ".join(t.split())


# ══════════════════════════════════════════════════════════════════
#  الأيقونات (خطوطٌ بسيطة — تُرسم داخل الصفحة بلا ملفات)
# ══════════════════════════════════════════════════════════════════

_ICON = {
    "home": '<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'
            '<path d="M9 22V12h6v10"/>',
    "guide": '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>'
             '<path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',
    "boxes": '<rect x="2" y="3" width="20" height="5" rx="1"/>'
             '<path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/>'
             '<path d="M10 12h4"/>',
    "moves": '<path d="M2 20a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8l-7 5V8l-7 5V4a2'
             ' 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z"/><path d="M17 18h1"/>'
             '<path d="M12 18h1"/><path d="M7 18h1"/>',
    "stmt": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0'
            ' 2-2V8z"/><path d="M14 2v6h6"/><path d="M16 13H8"/>'
            '<path d="M16 17H8"/><path d="M10 9H8"/>',
    "ops": '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4'
           ' 1 1-4Z"/>',
    "received": '<path d="m7.5 4.27 9 5.15"/><path d="M21 8a2 2 0 0 0-1-1.73l'
                '-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7'
                ' 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7'
                ' 5 8.7-5"/><path d="M12 22V12"/>',
    "sets": '<path d="M6 3h12l4 6-10 13L2 9Z"/><path d="M11 3 8 9l4 13 4-13'
            '-3-6"/><path d="M2 9h20"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "day": '<rect x="3" y="4" width="18" height="18" rx="2"/>'
           '<path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/>',
    "orders": '<rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2'
              'a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-'
              '2h2"/><path d="M12 11h4"/><path d="M12 16h4"/>'
              '<path d="M8 11h.01"/><path d="M8 16h.01"/>',
    "customers": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>'
                 '<circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3'
                 '-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "pnl": '<path d="m22 7-8.5 8.5-5-5L2 17"/><path d="M16 7h6v6"/>',
    "analytics": '<path d="M21 12c.552 0 1.005-.449.95-.998a10 10 0 0 0-'
                 '8.953-8.951c-.55-.055-.998.398-.998.95v8a1 1 0 0 0 1 1z"/>'
                 '<path d="M21.21 15.89A10 10 0 1 1 8 2.83"/>',
    "sale": '<path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z"/>'
            '<path d="M3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/>',
    "sale_return": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1'
                   ' 5.5 5.5v0a5.5 5.5 0 0 1-5.5 5.5H11"/>',
    "receipt": '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
    "payment": '<path d="M12 19V5"/><path d="m5 12 7-7 7 7"/>',
    "supply": '<path d="m7.5 4.27 9 5.15"/><path d="M21 8a2 2 0 0 0-1-1.73l-7'
              '-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2'
              ' 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="M12 22V12"/>',
    "manual": '<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0'
              ' 1 0-5H20"/><path d="M8 7h8"/><path d="M8 11h6"/>',
    "fixing": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "purchase": '<circle cx="8" cy="21" r="1"/><circle cx="19" cy="21" r="1"/>'
                '<path d="M2.05 2.05h2l2.66 12.42a2 2 0 0 0 2 1.58h9.78a2 2 0'
                ' 0 0 1.95-1.57l1.65-7.43H5.12"/>',
    "other": '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>'
             '<circle cx="5" cy="12" r="1"/>',
    "all": '<path d="M3 3h7v7H3z"/><path d="M14 3h7v7h-7z"/>'
           '<path d="M14 14h7v7h-7z"/><path d="M3 14h7v7H3z"/>',
    "photo": '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9"'
             ' cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
    "doc": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8'
           'z"/><path d="M14 2v6h6"/>',
    "plus": '<path d="M12 5v14"/><path d="M5 12h14"/>',
    "trash": '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2'
             '-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    "edit": '<path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>',
    "lock": '<rect x="3" y="11" width="18" height="11" rx="2"/>'
            '<path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
}


def icon(name, size=24):
    p = _ICON.get(name, _ICON["other"])
    return (f'<svg class="ic" width="{size}" height="{size}" viewBox="0 0 24 '
            f'24" fill="none" stroke="currentColor" stroke-width="1.8" '
            f'stroke-linecap="round" stroke-linejoin="round" '
            f'aria-hidden="true">{p}</svg>')


# ══════════════════════════════════════════════════════════════════
#  الإطار: الرأس وشريط التنقل
# ══════════════════════════════════════════════════════════════════

def nav_items(base):
    """[(مفتاح، اسم، رابط، أيقونة)] — شريط الرابط كله بترتيبه."""
    try:
        pnl = _mw()._pnl_title()
    except Exception:
        pnl = "الأرباح والخسائر"
    return [
        ("home", "الرئيسية", base, "home"),
        ("guide", "دليل الموديلات", _link(base, tab="guide"), "guide"),
        ("boxes", "الصناديق", _link(base, "/boxes"), "boxes"),
        ("moves", MOVES_TITLE, _link(base, "/moves"), "moves"),
        ("stmt", "كشف حساب", _link(base, "/stmt"), "stmt"),
        ("ops", "تسجيل عمليات", _link(base, "/ops"), "ops"),
        ("sets", "حركة الطقم", _link(base, "/sets"), "sets"),
        ("received", "الوارد بتاريخ", _link(base, tab="received"),
         "received"),
        ("customers", "العملاء", _link(base, tab="customers"),
         "customers"),
        ("analytics", "تحليل المبيعات", _link(base, "/analytics"),
         "analytics"),
        ("pnl", pnl, _link(base, tab="pnl"), "pnl"),
    ]


def nav_html(base, active):
    return '<nav class="mnav">' + "".join(
        f'<a class="{"on" if k == active else ""}" href="{_e(u)}">'
        f'{icon(ic, 17)}<span>{_e(t)}</span></a>'
        for k, t, u, ic in nav_items(base)) + '</nav>'


NAV_CSS = """
.mnav{max-width:1500px;margin:auto;display:flex;gap:4px;overflow-x:auto;
padding:0 16px 10px;scrollbar-width:none}
.mnav::-webkit-scrollbar{display:none}
.mnav a{display:flex;align-items:center;gap:6px;padding:8px 9px;
border-radius:11px;color:#f3e7cf;text-decoration:none;font-size:14px;
white-space:nowrap}
.mnav a:hover{background:rgba(255,255,255,.10)}
.mnav a.on{background:#F5F2EB;color:#4E3618;font-weight:700}
.mnav .ic{width:17px;height:17px}
"""

MCSS = """
:root{--bg:#F5F2EB;--card:#fff;--ink:#2b2723;--muted:#7a6f62;--line:#e8e0d2;
--brown:#4E3618;--gold:#A8822E;--gold2:#C9A24A;--soft:#FBF8F2;--in:#1E6B33;
--out:#9A3B1E;--ok:#1E6B33;--bad:#A4262C}
*{box-sizing:border-box}
body.mw{margin:0;background:var(--bg);color:var(--ink);
font-family:system-ui,"Segoe UI",Tahoma,sans-serif;font-size:15px;
-webkit-text-size-adjust:100%}
.mw a{color:inherit}
.mhead{background:linear-gradient(180deg,#523a1c,#43301a);color:#fff}
.mhead .in{max-width:1400px;margin:auto;padding:14px 20px 10px;display:flex;
align-items:center;gap:14px;flex-wrap:wrap}
.mhead h1{margin:0;font-size:21px;font-weight:700;letter-spacing:.2px}
.mhead .sub{font-size:12.5px;opacity:.82;margin-top:3px}
.mhead .sp{flex:1 1 auto}
.mhead .live{font-size:12.5px;background:rgba(255,255,255,.12);
border-radius:20px;padding:5px 12px;white-space:nowrap}
.elockb{font:inherit;font-size:12.5px;font-weight:700;border-radius:20px;
padding:5px 13px;white-space:nowrap;cursor:pointer;color:#f7ecd3;
background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.35)}
.elockb:hover{background:rgba(255,255,255,.16)}
.elockb.on{background:#F5E3B3;color:#4E3618;border-color:#F5E3B3}
#lkdlg input{width:100%;padding:11px;font-size:18px;text-align:center;
letter-spacing:5px;border:1px solid var(--line);border-radius:10px;
margin:6px 0 10px;box-sizing:border-box}
#lkdlg .note{margin:0 0 6px;white-space:normal}
/* القفل مفعّل: أدوات تعديل أقسام الصناديق تختفي (والحفظ يرفضها أيضاً) */
.elock .newbox,.elock .addacc,.elock [data-del],.elock .ren,.elock .delbox,
.elock .bx .up,.elock .bx .down,.elock h3 .up,.elock h3 .down{display:none!important}
.mnav{max-width:1400px;margin:auto;display:flex;gap:4px;overflow-x:auto;
padding:0 16px 10px;scrollbar-width:none}
.mnav::-webkit-scrollbar{display:none}
.mnav a{display:flex;align-items:center;gap:6px;padding:8px 9px;
border-radius:11px;color:#f3e7cf;text-decoration:none;font-size:14px;
white-space:nowrap;transition:background .15s}
.mnav a:hover{background:rgba(255,255,255,.10)}
.mnav a.on{background:#F5F2EB;color:var(--brown);font-weight:700}
.mmain{max-width:1400px;margin:auto;padding:18px 20px 30px}
.ptitle{display:flex;align-items:center;gap:12px;margin:2px 0 14px;
flex-wrap:wrap}
.ptitle h2{margin:0;font-size:20px;color:var(--brown);display:flex;
align-items:center;gap:9px}
.ptitle .hint{color:var(--muted);font-size:13px}
.ptitle .sp{flex:1 1 auto}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));
gap:12px;margin:0 0 18px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:16px;
padding:14px 16px;box-shadow:0 1px 2px rgba(60,40,10,.04)}
.kpi .k{font-size:13px;color:var(--muted);display:flex;gap:7px;
align-items:center}
.kpi .v{font-size:23px;font-weight:700;margin-top:6px;color:var(--ink);
font-variant-numeric:tabular-nums;direction:ltr;text-align:right}
.kpi .s{font-size:12.5px;color:var(--muted);margin-top:3px}
.kpi.gold{background:#FFF8E8;border-color:#EBD8A8}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));
gap:14px}
.tile{display:flex;flex-direction:column;align-items:center;
justify-content:center;gap:10px;min-height:150px;padding:20px 14px;
background:var(--card);border:1px solid var(--line);border-radius:18px;
text-decoration:none;color:var(--ink);text-align:center;
box-shadow:0 1px 2px rgba(60,40,10,.04);transition:transform .12s,
box-shadow .12s,border-color .12s}
.tile:hover{transform:translateY(-2px);border-color:#dcc58c;
box-shadow:0 8px 22px rgba(70,45,10,.08)}
.tile .ic{color:var(--gold);width:38px;height:38px}
.tile b{font-size:17px;color:var(--brown)}
.tile small{color:var(--muted);font-size:12.5px;line-height:1.55}
.tile.main{background:linear-gradient(180deg,#FFFDF7,#FFF6E2);
border-color:#E9D59F}
.tile .n{font-size:12px;background:#F3ECDD;color:var(--brown);
border-radius:10px;padding:2px 9px}
.sect{font-size:14px;color:var(--muted);margin:22px 4px 10px;font-weight:600}
.panel{background:var(--card);border:1px solid var(--line);border-radius:16px;
padding:14px 16px;margin:0 0 14px;box-shadow:0 1px 2px rgba(60,40,10,.04)}
.panel h3{margin:0 0 10px;font-size:17px;color:var(--brown);display:flex;
align-items:center;gap:8px;flex-wrap:wrap}
.panel h3 .sp{flex:1 1 auto}
.tbl{width:100%;border-collapse:collapse;font-size:14px}
.tbl th{background:#F4EEE2;color:#4a3f33;font-weight:600;padding:9px 8px;
text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}
.tbl td{padding:9px 8px;border-bottom:1px solid #F0EADF;vertical-align:middle}
.tbl tr:nth-child(even) td{background:var(--soft)}
.tbl td.n,.tbl th.n{text-align:left;direction:ltr;
font-variant-numeric:tabular-nums;white-space:nowrap}
.tbl tr.tot td{background:#2f2519;color:#fff;font-weight:700}
.tbl .neg{color:var(--bad)}
.tbl .acts{white-space:nowrap;text-align:left}
.tbl th.bal{background:#EDE2C6;color:#4a3519}
.tbl td.bal,.tbl tr:nth-child(even) td.bal{background:#FAF3E1;color:#3f2f18;
font-weight:600}
.tbl tr:nth-child(even) td.bal{background:#F6EDD6}
.tbl input.lwg{width:96px;padding:5px 8px;border:1px solid #E2D3AE;
border-radius:8px;background:#FFFDF6;font:inherit;font-size:14px;
text-align:left;direction:ltr;color:var(--ink)}
.tbl input.lwg:focus{outline:2px solid #E7CF8E;border-color:#C9A24A;
background:#fff}
.scroll{overflow-x:auto}
.btn{display:inline-flex;align-items:center;gap:6px;padding:8px 14px;
border-radius:10px;border:1px solid var(--brown);background:var(--brown);
color:#fff;text-decoration:none;font-weight:600;font-size:14px;
cursor:pointer;white-space:nowrap;font-family:inherit}
.btn:hover{filter:brightness(1.08)}
.btn.gold{background:var(--gold);border-color:var(--gold)}
.btn.gh{background:#fff;color:var(--brown);border-color:var(--line)}
.btn.sm{padding:5px 10px;font-size:13px;border-radius:9px}
.btn.big{padding:12px 26px;font-size:16px;border-radius:12px}
.btn.red{background:#fff;color:var(--bad);border-color:#efc9c9}
.btn[disabled]{opacity:.55;cursor:wait}
.btn .ic{width:16px;height:16px}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 14px}
.chip{display:inline-flex;align-items:center;gap:6px;padding:8px 14px;
border-radius:12px;background:#fff;border:1px solid var(--line);
text-decoration:none;color:var(--ink);font-size:14px}
.chip .ic{width:17px;height:17px;color:var(--gold)}
.chip.on{background:var(--brown);border-color:var(--brown);color:#fff}
.chip.on .ic{color:#f0d78f}
.chip .c{font-size:12px;background:#F3ECDD;color:var(--brown);
border-radius:9px;padding:1px 8px}
.chip.on .c{background:rgba(255,255,255,.18);color:#fff}
.fl{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;margin:0 0 14px}
.fl label,.fg label{display:flex;flex-direction:column;gap:5px;
font-size:12.5px;color:var(--muted)}
.mw input,.mw select,.mw textarea{font:inherit;font-size:15px;padding:9px 11px;
border:1px solid #ddd2bf;border-radius:10px;background:#fff;color:var(--ink);
min-width:0}
.mw input:focus,.mw select:focus,.mw textarea:focus{outline:2px solid #e3cb8c;
border-color:#c9a24a}
.mw input.num{direction:ltr;text-align:right;font-variant-numeric:tabular-nums}
.erow{display:flex;gap:14px;align-items:flex-start}
.erow .eflds{flex:1 1 auto;min-width:0}
.eph{flex:0 0 168px;height:168px;border:1px dashed #E2D3AE;border-radius:14px;
background:#FFFDF7;display:flex;align-items:center;justify-content:center;
overflow:hidden;text-align:center}
.eph img{width:100%;height:100%;object-fit:contain;background:#fff;display:block}
.eph a{display:block;width:100%;height:100%}
.eph .none{color:var(--muted);font-size:12.5px;padding:10px;line-height:1.6}
.eph.has{border-style:solid;border-color:#E9D59F}
@media (max-width:640px){.erow{flex-direction:column-reverse}
.eph{flex-basis:auto;width:100%;height:190px}}
.fg input.hot{outline:2px solid #E7CF8E;background:#FFFBEF;
transition:background .3s}
.fg{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
gap:10px 12px}
.fg .w2{grid-column:span 2}
.note{color:var(--muted);font-size:13px;line-height:1.7}
.msg{border-radius:12px;padding:11px 14px;margin:0 0 14px;font-weight:600}
.msg.ok{background:#E8F3EA;color:var(--ok)}
.msg.bad{background:#FBEAEA;color:var(--bad)}
.msg.info{background:#FFF7E2;color:#6b5020}
.empty{padding:34px;text-align:center;color:var(--muted)}
.ac{position:relative}
.ac .list{position:absolute;inset-inline:0;top:100%;z-index:30;background:#fff;
border:1px solid var(--line);border-radius:12px;margin-top:4px;
box-shadow:0 10px 28px rgba(50,30,5,.14);max-height:300px;overflow:auto;
display:none}
.ac .list div{padding:9px 12px;cursor:pointer;border-bottom:1px solid #f4efe5;
display:flex;gap:8px;align-items:baseline}
.ac .list div:hover,.ac .list div.hi{background:#FFF6E0}
.ac .list small{color:var(--muted);font-size:12px;direction:ltr}
.ac .list .none{color:var(--muted);cursor:default}
.toast{position:fixed;inset-inline:16px;bottom:18px;max-width:560px;
margin:auto;z-index:60;border-radius:14px;padding:14px 18px;font-weight:600;
box-shadow:0 12px 30px rgba(0,0,0,.18);display:none}
.toast.ok{background:#1E6B33;color:#fff}
.toast.bad{background:#A4262C;color:#fff}
.dlg{position:fixed;inset:0;background:rgba(30,20,8,.42);z-index:70;
display:none;align-items:center;justify-content:center;padding:16px}
.dlg .box{background:#fff;border-radius:18px;max-width:520px;width:100%;
padding:20px 22px;box-shadow:0 20px 50px rgba(0,0,0,.25)}
.dlg h4{margin:0 0 10px;font-size:18px;color:var(--brown)}
.dlg pre{white-space:pre-wrap;font-family:inherit;margin:0 0 16px;
line-height:1.8;font-size:14.5px}
.dlg .row{display:flex;gap:10px;justify-content:flex-start}
.mfoot{text-align:center;color:var(--muted);font-size:12px;padding:6px 0 22px}
.mfoot a{color:var(--muted)}
.pill{display:inline-block;font-size:12px;border-radius:9px;padding:2px 9px;
background:#F3ECDD;color:var(--brown)}
.pill.sale{background:#E6F2EA;color:#1E7B45}
.pill.sale_return{background:#F8E5E4;color:#B4232A}
.pill.receipt{background:#E3EFF5;color:#1E6B8F}
.pill.payment{background:#F5EADB;color:#8B5E1E}
.pill.supply{background:#F7EFD9;color:#8a6a1e}
.pill.manual{background:#ECECEC;color:#444}
.pill.fixing{background:#E2F0EF;color:#2F6F6F}
@media (max-width:640px){.mmain{padding:12px}.kpi .v{font-size:19px}
.kpis{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.kpi{padding:10px 12px}.tiles{grid-template-columns:repeat(2,minmax(0,1fr));
gap:10px}.tile{padding:14px 8px}.tile small{font-size:11.5px}
.tile{min-height:120px}.fg .w2{grid-column:span 1}
.tbl{font-size:13px}.tbl td,.tbl th{padding:7px 5px}}
"""

_BASE_JS = r"""
(function(){
 window.MW={base:document.documentElement.getAttribute('data-base'),
  csrf:document.documentElement.getAttribute('data-csrf')};
 MW.esc=function(s){return String(s==null?'':s).replace(/[&<>"']/g,
  function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',
  "'":'&#39;'}[c];});};
 MW.fmt=function(x){x=+x||0;return x.toLocaleString('en-US',
  {minimumFractionDigits:2,maximumFractionDigits:2});};
 MW.num=function(el){var v=String(el.value||'').replace(/[٠-٩]/g,function(d){
  return '٠١٢٣٤٥٦٧٨٩'.indexOf(d);}).replace(/[,،\s]/g,'').replace('٫','.');
  var n=parseFloat(v);return isNaN(n)?0:n;};
 MW.toast=function(t,ok){var b=document.getElementById('toast');if(!b)return;
  b.className='toast '+(ok?'ok':'bad');b.textContent=t;b.style.display='block';
  clearTimeout(MW._tt);MW._tt=setTimeout(function(){b.style.display='none';},
  ok?4200:7000);};
 MW.get=function(path,q){var u=MW.base+path+(q?('?'+Object.keys(q).map(
  function(k){return k+'='+encodeURIComponent(q[k]);}).join('&')):'');
  return fetch(u,{credentials:'same-origin',cache:'no-store'}).then(
  function(r){return r.json();});};
 MW.post=function(path,data){data=data||{};data.csrf=MW.csrf;
  return fetch(MW.base+path,{method:'POST',credentials:'same-origin',
  headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})
  .then(function(r){return r.json().catch(function(){return {ok:false,
  error:'تعذّر قراءة الرد ('+r.status+')'};});})
  .catch(function(){return {ok:false,error:'تعذّر الاتصال بجهاز المصنع — '+
  'تحقّق من الإنترنت ثم أعد المحاولة'};});};
 MW.confirm=function(title,text){return new Promise(function(res){
  var d=document.getElementById('dlg');d.querySelector('h4').textContent=title;
  d.querySelector('pre').textContent=text;d.style.display='flex';
  var y=d.querySelector('.yes'),n=d.querySelector('.no');
  function done(v){d.style.display='none';y.onclick=n.onclick=null;res(v);}
  y.onclick=function(){done(true);};n.onclick=function(){done(false);};});};
 // حقل اقتراحٍ من أول حرف: data-ac="مسار" ← قائمةٌ تحته، والاختيار
 // يملأ الحقل المخفي data-for
 MW.ac=function(inp,path,onpick,extra){
  var wrap=inp.parentNode,list=document.createElement('div');list.className='list';
  wrap.appendChild(list);var t=null,hi=-1,items=[];
  function hide(){list.style.display='none';hi=-1;}
  function show(rows){items=rows||[];if(!items.length){list.innerHTML=
   '<div class="none">لا أسماء مطابقة</div>';list.style.display='block';
   return;}list.innerHTML=items.map(function(r,i){return '<div data-i="'+i+
   '">'+MW.esc(r.label)+(r.sub?' <small>'+MW.esc(r.sub)+'</small>':'')+
   '</div>';}).join('');list.style.display='block';}
  function pick(i){var r=items[i];if(!r)return;inp.value=r.label;hide();
   if(onpick)onpick(r);}
  list.addEventListener('mousedown',function(e){var d=e.target.closest('[data-i]');
   if(d){e.preventDefault();pick(+d.getAttribute('data-i'));}});
  inp.addEventListener('input',function(){if(onpick)onpick(null,true);
   var v=inp.value.trim();clearTimeout(t);if(!v){hide();return;}
   t=setTimeout(function(){var q={q:v};if(extra)Object.assign(q,extra());
   MW.get(path,q).then(show).catch(hide);},120);});
  inp.addEventListener('keydown',function(e){var ds=list.querySelectorAll('[data-i]');
   if(list.style.display!=='block'||!ds.length)return;
   if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();
    hi=(hi+(e.key==='ArrowDown'?1:-1)+ds.length)%ds.length;
    ds.forEach(function(d,i){d.classList.toggle('hi',i===hi);});}
   else if(e.key==='Enter'){e.preventDefault();pick(hi<0?0:hi);}
   else if(e.key==='Escape'){hide();}});
  inp.addEventListener('blur',function(){setTimeout(hide,150);});};
})();
"""


def frame(base, active, title, inner, csrf="", css="", js="", sub=""):
    """صفحةٌ كاملة بالرأس وشريط التنقل — كل صفحات الهيكل الجديد."""
    from datetime import datetime
    co = _mw()._company().strip()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    _has_pin, _locked_now = _edit_lock_state()

    def _lock_btn():
        """زرّ قفل التعديل والحذف بجانب «مباشر» (5.7.6)."""
        if not csrf:
            return ""
        if _locked_now:
            return ('<button type="button" id="elockb" class="elockb on" '
                    'data-locked="1" data-pin="1" title="التعديل والحذف '
                    'مقفلان في الرابط — اضغط لفتحهما بالرمز">🔒 التعديل '
                    'والحذف مقفل</button>')
        return (f'<button type="button" id="elockb" class="elockb" '
                f'data-locked="0" data-pin="{"1" if _has_pin else "0"}" '
                f'title="اضغط لقفل التعديل والحذف في الرابط كله بالرمز">'
                f'🔓 قفل التعديل والحذف</button>')
    return f"""<!DOCTYPE html>
<html dir="rtl" lang="ar" data-base="{_e(base)}" data-csrf="{_e(csrf)}"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">{_mw()._install_head(base)}
<title>{_e(title)}{(" — " + _e(co)) if co else ""}</title>
<style>{MCSS}{css}</style></head><body class="mw{" elock" if _locked_now else ""}">
<header class="mhead"><div class="in"><div><h1>{_e(co or "رابط المدير")}</h1>
<div class="sub">{_e(sub or "مباشرةً من جهاز المصنع")}</div></div>
<span class="sp"></span><span class="live">● مباشر · {now} · الأوزان
 {_e(_unit())}</span>{_lock_btn()}</div>{nav_html(base, active)}</header>
<main class="mmain">{inner}</main>
<div class="mfoot"><a href="{_e(base)}">الرئيسية</a> · إصدار
 {_e(_mw()._version())} · <a href="{_e(base)}/logout">خروج</a></div>
<div id="toast" class="toast"></div>
<div id="dlg" class="dlg"><div class="box"><h4></h4><pre></pre>
<div class="row"><button class="btn yes">✔ تأكيد</button>
<button class="btn gh no">إلغاء</button></div></div></div>
<div id="lkdlg" class="dlg"><div class="box"><h4></h4><p class="note"></p>
<input id="lkpin" type="password" inputmode="numeric" maxlength="12"
 autocomplete="off" placeholder="رمز القفل">
<div id="lkerr" class="msg bad" style="display:none"></div>
<div class="row"><button class="btn yes">✔ تأكيد</button>
<button class="btn gh no">إلغاء</button></div></div></div>
<script>{_BASE_JS}{_LOCK_JS}{js}</script></body></html>"""


_LOCK_JS = r"""
(function(){var b=document.getElementById('elockb'),d=document.getElementById('lkdlg');
 if(!b||!d)return;var inp=document.getElementById('lkpin'),
  er=document.getElementById('lkerr');
 function close(){d.classList.remove('on');d.style.display='none';}
 b.addEventListener('click',function(){var lk=b.getAttribute('data-locked')==='1';
  if(b.getAttribute('data-pin')!=='1'){MW.toast('اضبط رمز القفل أولاً من '+
   'البرنامج: «🔗 رابط المدير» ← «رمز قفل التعديل والحذف»',false);return;}
  d.querySelector('h4').textContent=lk?'🔓 فتح التعديل والحذف':
   '🔒 قفل التعديل والحذف';
  d.querySelector('.note').textContent=lk?'يعود التعديل والحذف والدمج في '+
   'الرابط كله بعد إدخال الرمز.':'تختفي أزرار التعديل والحذف والعكس والدمج '+
   'من الرابط كله، ويُرفض أي تعديل أو حذف حتى يُفتح القفل بالرمز.';
  inp.value='';er.style.display='none';d.style.display='flex';
  d.classList.add('on');setTimeout(function(){inp.focus();},30);});
 function go(){var lk=b.getAttribute('data-locked')==='1',p=inp.value.trim();
  if(!p){inp.focus();return;}
  MW.post('/api/editlock',{pin:p,lock:!lk}).then(function(r){
   if(r&&r.ok){close();MW.toast(r.msg,true);setTimeout(function(){
    location.reload();},400);}
   else{er.textContent=(r&&r.error)||'تعذّر';er.style.display='block';
    inp.select();}});}
 d.querySelector('.yes').addEventListener('click',go);
 d.querySelector('.no').addEventListener('click',close);
 inp.addEventListener('keydown',function(e){if(e.key==='Enter'){
  e.preventDefault();go();}else if(e.key==='Escape')close();});
})();
"""


# ══════════════════════════════════════════════════════════════════
#  التوجيه
# ══════════════════════════════════════════════════════════════════

ROUTES = ("home", "sets", "boxes", "moves", "stmt", "analytics", "ops",
          "doc", "api")


def handles(rest, query):
    """هل هذا الطلب من الهيكل الجديد؟ — والرابط المجرّد يفتح الرئيسية،
    وروابط الدليل المحفوظة قبل 5.6.0 (بفرزٍ أو عرض) تبقى تفتح الدليل."""
    if not rest:
        if query.get("tab"):
            # 5.6.1: «حركة اليوم» و«طلبات العملاء» حُذفتا — روابطهما
            # المحفوظة تفتح الرئيسية
            return query.get("tab") in ("home", "day", "orders")
        return not any(query.get(k) for k in ("view", "sort", "day", "st",
                                              "d", "from", "to"))
    return rest[0] in ROUTES


def route(method, rest, query, headers, body, base, csrf, pin_set=False):
    from database.database import db
    head = rest[0] if rest else "home"
    if method == "POST":
        try:
            data = json.loads((body or b"{}").decode("utf-8", "replace")
                              or "{}")
        except ValueError:
            form = parse_qs((body or b"").decode("utf-8", "replace"),
                            keep_blank_values=True)
            data = {k: v[-1] for k, v in form.items()}
        if not isinstance(data, dict) or not hmac.compare_digest(
                str(data.get("csrf") or ""), csrf):
            return _json({"ok": False, "error": "انتهت صلاحية الصفحة — "
                          "حدّثها ثم أعد المحاولة"}, 403)
        if head == "api" and rest[1:2] == ["editlock"]:
            return _json(edit_lock_action(data))
        if head == "boxes":
            with db(readonly=True) as conn:
                if edits_locked(conn):
                    return _json({"ok": False, "error": EDIT_LOCKED_MSG})
            return _json(boxes_action(data))
        if head == "ops" and rest[1:2] == ["unlock"]:
            return _unlock(data, base, csrf)
        if head == "ops" and rest[1:2] == ["lock"]:
            ck = (f"{OPS_COOKIE}=; Path={base}; Max-Age=0; HttpOnly;"
                  " SameSite=Strict")
            return _resp(303, "", headers={"Location": base + "/ops",
                                           "Set-Cookie": ck})
        if head == "api" and len(rest) >= 2 and rest[1] in (
                "post", "edit", "delete", "merge"):
            # كل كتابةٍ من الرابط خلف رمز اللوحة (إن ضُبط)
            with db(readonly=True) as conn:
                if not ops_unlocked(conn, headers, csrf):
                    return _json({"ok": False, "locked": True,
                                  "unlock": base + "/ops/unlock",
                                  "error": "لوحة تسجيل العمليات برمز — "
                                           "أدخل رمزها أولاً"})
            if rest[1] == "post" and len(rest) == 3:
                return _json(post_op(rest[2], data))
            if rest[1] == "edit" and len(rest) == 4 and rest[3].isdigit():
                return _json(edit_op(rest[2], int(rest[3]), data))
            if rest[1] == "delete" and len(rest) == 2:
                return _json(delete_op(data))
            if rest[1] == "merge" and len(rest) == 2:
                return _json(merge_op(data))
        return _json({"ok": False, "error": "غير موجود"}, 404)
    if method != "GET":
        return _resp(405, "")
    if head == "api":
        with db(readonly=True) as conn:
            return _json(api(conn, rest[1:], query))
    if head == "doc":
        return doc_page(rest[1:], base, query)
    with db(readonly=True) as conn:
        if head == "home":
            return _resp(200, home(conn, base, csrf))
        if head == "sets":
            return _resp(200, sets_page(conn, base, csrf, query))
        if head == "boxes":
            return _resp(200, boxes_page(conn, base, csrf, query))
        if head == "moves":
            return _resp(200, moves_page(conn, base, csrf, query))
        if head == "stmt":
            return _resp(200, stmt_page(conn, base, csrf, query))
        if head == "analytics":
            return _resp(200, analytics_page(conn, base, csrf, query))
        if head == "ops":
            if rest[1:2] == ["unlock"]:
                return _resp(200, unlock_page(
                    base, csrf, _safe_next(base, query.get("next"))))
            if not ops_unlocked(conn, headers, csrf) and ops_enabled(conn):
                nxt = base + "/" + "/".join(rest) + (
                    f"?edit={query.get('edit')}"
                    if str(query.get("edit") or "").isdigit() else "")
                return _resp(200, unlock_page(base, csrf,
                                              _safe_next(base, nxt)))
            return _resp(200, ops_page(conn, base, csrf, rest[1:], query,
                                       has_ops_pin(conn)))
    return _resp(404, _mw()._GONE)


# ══════════════════════════════════════════════════════════════════
#  البحث والاقتراح (JSON)
# ══════════════════════════════════════════════════════════════════

_TYPE_LABEL = {"customer": "عميل", "supplier": "مورد", "partner": "شريك",
               "employee": "موظف", "worker": "عامل", "other": "جهة",
               "internal": "داخلي"}


def _type_label(t):
    """اسم النوع — والأنواع التي أنشأها المستخدم (5.8.4) باسمها هي."""
    if t in _TYPE_LABEL:
        return _TYPE_LABEL[t]
    try:
        from models.entities import TYPE_LABELS
        return TYPE_LABELS.get(t, "")
    except Exception:                         # noqa: BLE001
        return ""


def search_accounts(conn, q, postable=False, limit=14):
    """حسابات الدليل باسمها أو رقمها — من أول حرف (همزةٌ وتاءٌ مربوطة
    لا تُفرّقان)."""
    n = _norm(q)
    if not n:
        return []
    rows = conn.execute(
        "SELECT id, code, name, is_postable FROM accounts WHERE is_active=1"
        + (" AND is_postable=1" if postable else "")
        + " ORDER BY code").fetchall()
    starts, has = [], []
    for r in rows:
        name, code = _norm(r["name"]), str(r["code"])
        if code.startswith(n) or name.startswith(n):
            starts.append(r)
        elif n in name or n in code:
            has.append(r)
    out = []
    for r in (starts + has)[:limit]:
        out.append({"id": r["id"], "code": r["code"], "name": r["name"],
                    "label": f"{r['name']}", "sub": r["code"],
                    "group": not r["is_postable"]})
    return out


def search_parties(conn, q, limit=14, types=None):
    """جهات التعامل باسمها — كل الأنواع كما في شاشات البرنامج."""
    n = _norm(q)
    if not n:
        return []
    sql = ("SELECT e.id, e.name, e.entity_type, e.account_id, a.code"
           " FROM entities e JOIN accounts a ON a.id=e.account_id"
           " WHERE e.is_deleted=0")
    p = []
    if types:
        sql += " AND e.entity_type IN (%s)" % ",".join("?" * len(types))
        p += list(types)
    starts, has = [], []
    for r in conn.execute(sql + " ORDER BY e.name", p):
        nm = _norm(r["name"])
        if nm.startswith(n) or str(r["code"]).startswith(n):
            starts.append(r)
        elif n in nm:
            has.append(r)
    return [{"id": r["id"], "label": r["name"], "acc": r["account_id"],
             "type": r["entity_type"],
             "sub": f"{_type_label(r['entity_type'])} · {r['code']}"}
            for r in (starts + has)[:limit]]


def wo_info(conn, no, mode, date=None, edit_inv=None):
    """بيانات رقم التشغيل لسطر الإدخال — كما يستدعيها البرنامج."""
    from models import inventory
    from models import invoices as inv
    from models import stock_home
    from models import wo_moves as wm
    from services import karat_view as kv
    no = str(no or "").strip()
    if not no:
        return {"ok": False, "error": "اكتب رقم التشغيل"}
    if mode == "supply":
        if inventory.is_bulk_no(no):
            return {"ok": True, "bulk": True, "no": no,
                    "model": inventory.ITALIAN_MODEL}
        if inventory.get_wo_by_no(conn, no) is not None:
            return {"ok": False, "error": f"رقم التشغيل {no} موجود من قبل —"
                                          " لكل طقمٍ رقمه"}
        return {"ok": True, "bulk": False, "no": no, "new": True}
    wo = inventory.get_wo_by_no(conn, no)
    if wo is None:
        return {"ok": False, "error": f"رقم التشغيل {no} غير موجود"}
    kind = wm.SALE if mode == "sale" else wm.RETURN
    bulk = bool(wo["is_bulk"])
    avail = 0.0 if bulk else float(wm.default_weight(conn, wo, kind))
    # 5.7.0: في تعديل فاتورة — الطقم الذي فيها متاحٌ بوزنه فيها (سطرُه
    # حُذف من النموذج ثم أُعيد)
    mine = 0.0
    if edit_inv and not bulk:
        r = conn.execute("SELECT COALESCE(SUM(it.registered_weight),0) w"
                         " FROM invoice_items it JOIN invoices i"
                         " ON i.id=it.invoice_id AND i.is_deleted=0"
                         " WHERE it.invoice_id=? AND it.work_order_id=?",
                         (int(edit_inv), wo["id"])).fetchone()
        mine = float(r["w"] or 0)
    if mine > 0:
        # حصّته في هذه الفاتورة + ما بقي متاحاً منه (في الخزنة للبيع، أو
        # عند الجهات للمرتجع) — لا الوزن الافتراضي الكامل
        st = wm.state(conn, wo)
        free = float(st["rem"] if kind == wm.SALE else st["out"])
        avail = round(mine + max(0.0, free), 3)
    elif not bulk:
        why = wm.refusal(conn, wo, kind, date or _today().isoformat(), avail)
        if why == "none-left":
            need = "في الخزنة" if kind == wm.SALE else "مباعاً"
            return {"ok": False, "error": f"الطقم {no} ليس {need}"
                                          + inv._where_is(conn, wo["id"])}
        if why:
            return {"ok": False, "error": why}
    last = inv.last_wage(conn, wo["id"]) if not bulk else None
    wage18 = float((last or {}).get("wage") or wo["wage_per_gram"] or 0)
    acc = None
    try:
        aid = stock_home.line_account(conn, wo)
        if aid:
            r = conn.execute("SELECT code, name FROM accounts WHERE id=?",
                             (aid,)).fetchone()
            acc = f"{r['code']} — {r['name']}" if r else None
    except Exception:
        acc = None
    model = (wo["model_no"] or "").strip()
    k = int(kv.active())
    ver = ""
    if model:
        try:
            ver = _mw()._img_versions().get(_mw()._vkey(model)) or ""
        except Exception:
            ver = ""
    return {"ok": True, "id": wo["id"], "no": wo["work_order_no"],
            "bulk": bulk, "model": model or ("ايطالي" if bulk else ""),
            "avail18": round(avail, 3), "karat": k,
            "avail": round(kv.g(avail, k), 2) if avail else 0.0,
            "wage18": round(wage18, 4),
            "wage": round(kv.rate(wage18, k), 2),
            "diamond": float(wo["diamond_weight"] or 0)
            if "diamond_weight" in wo.keys() else 0.0,
            "acc": acc, "img": bool(ver), "ver": ver}


def api(conn, rest, query):
    what = rest[0] if rest else ""
    q = str(query.get("q") or "")[:60]
    if what == "acc":
        return search_accounts(conn, q, postable=query.get("p") == "1")
    if what == "party":
        return search_parties(conn, q)
    if what == "cust":
        return search_customers(conn, q)
    if what == "wo":
        inv = str(query.get("inv") or "")
        return wo_info(conn, query.get("no"), query.get("mode") or "sale",
                       _date(query.get("d")), int(inv) if inv.isdigit()
                       else None)
    if what == "models":
        from models.models_catalog import model_names
        n = _norm(q)
        names = [m for m in model_names(conn) if n and n in _norm(m)]
        return [{"label": m} for m in names[:14]]
    return {"ok": False, "error": "غير موجود"}


# ══════════════════════════════════════════════════════════════════
#  الرئيسية
# ══════════════════════════════════════════════════════════════════

def home(conn, base, csrf):
    # 5.6.3: بلا بطاقات الأرقام أعلى الرئيسية (الذهب المشغول · المتاح للبيع ·
    # الصندوق النقدي · عمليات اليوم) — اللوحات وحدها

    def tile(key, title, sub, href, main=False, badge=""):
        return (f'<a class="tile{" main" if main else ""}" href="{_e(href)}">'
                f'{icon(key, 38)}<b>{_e(title)}</b><small>{_e(sub)}</small>'
                + (f'<span class="n">{_e(badge)}</span>' if badge else "")
                + '</a>')
    main = "".join((
        tile("guide", "دليل الموديلات", "صور الموديلات · كم بالخزنة وعند من",
             _link(base, tab="guide"), True),
        tile("boxes", "الصناديق", "أقسامك وحساباتها وأرصدتها — ذهباً "
             "ونقداً", _link(base, "/boxes"), True),
        tile("moves", MOVES_TITLE, "الوارد · المبيعات · المرتجعات · القبض"
             " · الصرف · القيود · التسكير", _link(base, "/moves"), True),
        tile("stmt", "كشف حساب", "اكتب الاسم يظهر كشفه — مع الصور والفواتير",
             _link(base, "/stmt"), True),
        tile("ops", "تسجيل عمليات", "بيع · مرتجع · قبض · صرف · قيد · توريد",
             _link(base, "/ops"), True)))
    try:
        pnl = _mw()._pnl_title()
    except Exception:
        pnl = "الأرباح والخسائر"
    # 5.6.4: «حركة الطقم» في «المزيد»
    more = "".join((
        tile("sets", "حركة الطقم", "ابحث برقم التشغيل أو بالوزن — تفصيل "
             "وزنه ودفعته وحركاته", _link(base, "/sets")),
        tile("received", "الوارد بتاريخ", "البضاعة الواردة بموديلاتها",
             _link(base, tab="received")),
        tile("customers", "العملاء — المبيعات والسداد",
             "من يسدّد ومن يتأخر", _link(base, tab="customers")),
        tile("analytics", AN_TITLE, "المبيعات · المرتجعات · المباع الفعلي ·"
             " التحصيل — لكل عميل كشاشة البرنامج", _link(base, "/analytics")),
        tile("pnl", pnl, "لوحة الأرباح كما في البرنامج",
             _link(base, tab="pnl"))))
    inner = (f'<div class="ptitle"><h2>{icon("home", 22)}الرئيسية</h2>'
             f'<span class="hint">اختر لوحةً — كل الأرقام من جهاز المصنع '
             f'لحظة الفتح</span></div>'
             f'<div class="tiles">{main}</div>'
             f'<div class="sect">المزيد</div><div class="tiles">{more}</div>')
    return frame(base, "home", "الرئيسية", inner, csrf)


# ══════════════════════════════════════════════════════════════════
#  حركة الطقم (5.6.1) — كشاشة البرنامج: برقم التشغيل أو بالوزن
# ------------------------------------------------------------------
#  برقم التشغيل: بطاقة تفاصيله (الأوزان والذهب والفصوص والأحجار، ودفعة
#  توريده، ومكانه الآن) وصورة موديله، ثم سجل حركاته زمنياً بأزرار الصور
#  والفاتورة. وبالوزن المقيد أو القائم: الأطقم الأقرب إليه، الأقرب أولاً.
#  المصدر `inventory.item_history` و`set_lookup` — قراءةٌ محضة.
# ══════════════════════════════════════════════════════════════════

SET_MODES = (("no", "رقم التشغيل"), ("reg", "الوزن المقيد"),
             ("standing", "الوزن القائم"))

_SETS_CSS = """
.sform{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;margin:0}
.sform .q{flex:1 1 240px}
.sform .q input{width:100%;font-size:17px}
.shead{display:flex;gap:16px;flex-wrap:wrap;align-items:stretch}
.shead .ph{flex:0 0 220px;max-width:100%;border:1px solid var(--line);
border-radius:14px;overflow:hidden;background:#fff;display:flex;
align-items:center;justify-content:center;min-height:160px}
.shead .ph img{width:100%;height:auto;display:block}
.shead .ph .none{color:var(--muted);font-size:13px;padding:20px}
.shead .info{flex:1 1 380px;display:flex;flex-direction:column;gap:10px;
min-width:0}
.shead .wo{font-size:26px;font-weight:800;color:var(--brown);display:flex;
gap:10px;align-items:center;flex-wrap:wrap}
.shead .where{font-size:15px;font-weight:600}
.shead .where.in{color:var(--ok)}
.shead .where.out{color:var(--out)}
.wgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));
gap:8px}
.wgrid div{background:var(--soft);border:1px solid var(--line);
border-radius:12px;padding:8px 11px;font-size:12px;color:var(--muted)}
.wgrid div.main{background:#FFF8E8;border-color:#EBD8A8}
.wgrid b{display:block;font-size:18px;color:var(--ink);direction:ltr;
text-align:right;font-variant-numeric:tabular-nums;margin-top:2px}
.batch{display:flex;gap:10px;align-items:center;flex-wrap:wrap;
background:#F7F2E7;border:1px dashed #DCCDAE;border-radius:12px;
padding:9px 12px;font-size:14px}
.batch > .ic{color:var(--gold)}
.batch .sp{flex:1 1 auto}
.tbl tr.bad td{background:#FBEAEA}
@media (max-width:640px){.shead .ph{flex-basis:100%;min-height:0}
.shead .ph .none{padding:12px}
.wgrid{grid-template-columns:repeat(2,minmax(0,1fr))}.shead .wo{font-size:22px}}
"""


def _num_in(txt):
    """وزنٌ مكتوب (بأرقامٍ عربية أو بفاصلة) ← رقم، أو None."""
    t = str(txt or "").strip().translate(str.maketrans(
        "٠١٢٣٤٥٦٧٨٩٫،", "0123456789.,")).replace(",", ".")
    try:
        v = float(t)
    except ValueError:
        return None
    return v if 0 < v < 1e6 else None


def _wv(v):
    """وزنٌ لعمود الجدول — «—» للفارغ."""
    if v in ("", None):
        return "—"
    try:
        return _w(float(v))
    except (TypeError, ValueError):
        return _e(v)


def _set_photo(base, model):
    m = _mw()
    try:
        ver = m._img_versions().get(m._vkey(model), "") if model else ""
    except Exception:
        ver = ""
    if not model or not ver:
        return (f'<div class="ph"><span class="none">'
                f'{"لا توجد صورة للموديل" if model else "بلا موديل"}</span>'
                '</div>')
    return (f'<a class="ph" target="_blank" rel="noopener" href="'
            f'{_e(m._img_url(base, model, ver, True))}"><img alt="'
            f'{_e(model)}" src="{_e(m._img_url(base, model, ver))}"></a>')


def _set_detail(conn, base, no):
    from models import inventory, set_lookup, wo_moves
    wo, rows = inventory.item_history(conn, no)
    det = set_lookup.details(conn, wo)
    keys = wo.keys()
    u = _e(_unit())
    w = det["where"]
    bulk = bool(wo["is_bulk"])
    where_cls = "in" if w["place"] == "treasury" else "out"
    where_txt = w["label"] + (f" · فاتورة {w['invoice_no']}"
                              if w.get("invoice_no") else "")
    if not bulk:
        st = wo_moves.state(conn, wo)
        split = (f'<div>في الخزنة<b>{_w(st["rem"])}</b></div>'
                 f'<div>عند الجهات<b>{_w(st["out"])}</b></div>')
    else:
        split = ""
    dia = (float(wo["diamond_weight"] or 0)
           if "diamond_weight" in keys else 0.0)
    cells = (f'<div class="main">الوزن المقيد ({u})<b>{_w(det["reg"])}</b>'
             f'</div><div class="main">الوزن القائم<b>{_w(det["standing"])}'
             f'</b></div><div>الذهب<b>{_w(det["gold"])}</b></div>'
             f'<div>الفصوص<b>{_w(det["small"])}</b></div>'
             f'<div>الأحجار<b>{_w(det["big"])}</b></div>'
             + (f'<div>الألماس (قيراط)<b>{_m(dia)}</b></div>' if dia else "")
             + split)
    b = rows[0].get("batch") if rows else None
    if b:
        batch = (f'<div class="batch">{icon("supply", 18)}<span>دفعة التوريد:'
                 f' <b>{_e(b["label"])}</b></span><span class="sp"></span>'
                 f'{_doc_links(base, "work_orders", wo["id"], wo["entry_id"])}'
                 '</div>')
    else:
        batch = (f'<div class="batch">{icon("supply", 18)}<span>'
                 f'{_e(rows[0]["party"] if rows else "—")}</span></div>')
    status = ('<span class="pill sale">بالخزنة</span>'
              if wo["status"] == "in_stock" else
              '<span class="pill sale_return">خارج / مباع</span>')
    head = (f'<div class="panel"><div class="shead">'
            f'{_set_photo(base, det["model_no"])}<div class="info">'
            f'<div class="wo">{icon("sets", 26)}الطقم {_e(wo["work_order_no"])}'
            f'{status}<span class="pill">الموديل {_e(det["model_no"] or "—")}'
            f'</span>'
            + (f'<span class="pill">{_e(det["item_type"])}</span>'
               if det["item_type"] else "")
            + f'</div><div class="where {where_cls}">📍 {_e(where_txt)}</div>'
            f'<div class="wgrid">{cells}</div>{batch}</div></div></div>')
    trs = []
    for r in reversed(rows):        # الأحدث أولاً (5.7.3)
        acts = (_doc_links(base, "invoices", r["inv_id"], None)
                if r.get("inv_id") else "")
        party = _e(r["party"]) + (f' <span class="pill">{_e(r["inv"])}</span>'
                                  if r.get("inv") else "")
        kind = _e(r["kind"]) + (' <span class="pill sale_return">⚠ غير '
                                'منتظمة</span>' if r.get("bad") else "")
        trs.append(
            f'<tr class="{"bad" if r.get("bad") else ""}"><td>{kind}</td>'
            f'<td class="n">{_e(r["date"] or "")}</td><td>{party}</td>'
            f'<td class="n">{_wv(r["gold"])}</td>'
            f'<td class="n">{_wv(r["small"])}</td>'
            f'<td class="n">{_wv(r["big"])}</td>'
            f'<td class="n">{_wv(r["reg"])}</td>'
            f'<td class="n">{_wv(r.get("left"))}</td>'
            f'<td class="acts">{acts}</td></tr>')
    table = (f'<div class="panel"><h3>{icon("moves", 19)}سجل حركة الطقم'
             f'<span class="pill">{len(rows)} حركة</span><span class="pill">'
             f'الأحدث أولاً</span></h3>'
             f'<div class="scroll"><table class="tbl"><tr><th>نوع الحركة</th>'
             f'<th class="n">التاريخ</th><th>الجهة المقابلة</th>'
             f'<th class="n">الذهب</th><th class="n">الفصوص</th>'
             f'<th class="n">الأحجار</th><th class="n">الوزن المقيد</th>'
             f'<th class="n">في الخزنة بعدها</th><th></th></tr>'
             f'{"".join(trs)}</table></div></div>')
    return head + table


def _set_near(conn, base, by, v):
    from models import set_lookup
    from services import karat_view as kv
    rows = set_lookup.near_weight(conn, kv.store(v), by, limit=40)
    u = _e(_unit())
    label = dict(SET_MODES)[by]
    trs = "".join(
        f'<tr><td><a class="btn sm gh" href="'
        f'{_e(_link(base, "/sets", by="no", q=r["work_order_no"]))}">'
        f'{_e(r["work_order_no"])}</a></td><td>{_e(r["model_no"] or "—")}'
        f'</td><td class="n">{_w(r["reg"])}</td>'
        f'<td class="n">{_w(r["standing"])}</td><td class="n">'
        f'{_w(r["gold"])}</td><td class="n">{_w(r["small"])}</td>'
        f'<td class="n">{_w(r["big"])}</td><td class="n">{_w(r["diff"])}</td>'
        f'<td>{_e(r["where"]["label"])}</td></tr>' for r in rows)
    if not rows:
        return '<div class="panel"><div class="empty">لا أطقم مفردة</div></div>'
    return (f'<div class="panel"><h3>{icon("search", 19)}أقرب {len(rows)} طقماً'
            f' إلى {_e(label)} {_m(v)} {u}<span class="hint" style="font-'
            f'weight:400;font-size:13px;color:var(--muted)">— الأقرب أولاً · '
            f'انقر رقم التشغيل يفتح حركته</span></h3><div class="scroll">'
            f'<table class="tbl"><tr><th>رقم التشغيل</th><th>الموديل</th>'
            f'<th class="n">الوزن المقيد</th><th class="n">الوزن القائم</th>'
            f'<th class="n">الذهب</th><th class="n">الفصوص</th>'
            f'<th class="n">الأحجار</th><th class="n">الفرق</th>'
            f'<th>مكانه الآن</th></tr>{trs}</table></div></div>')


def sets_page(conn, base, csrf, query):
    by = query.get("by") if query.get("by") in dict(SET_MODES) else "no"
    q = str(query.get("q") or "").strip()[:40]
    opts = "".join(f'<option value="{k}"{" selected" if k == by else ""}>'
                   f'{t}</option>' for k, t in SET_MODES)
    ph = ("اكتب رقم التشغيل…" if by == "no" else
          f"اكتب الوزن ({_unit()}) — تظهر الأطقم الأقرب إليه…")
    form = (f'<div class="panel"><form class="sform" method="get" action="'
            f'{_e(base + "/sets")}"><label>البحث بـ<select name="by" '
            f'onchange="this.form.q.placeholder=this.value===\'no\'?'
            f'\'اكتب رقم التشغيل…\':\'اكتب الوزن — تظهر الأطقم الأقرب '
            f'إليه…\';this.form.q.focus()">{opts}</select></label>'
            f'<label class="q">رقم التشغيل أو الوزن<input name="q" value="'
            f'{_e(q)}" placeholder="{_e(ph)}" autocomplete="off" autofocus '
            f'inputmode="{"text" if by == "no" else "decimal"}"></label>'
            f'<button class="btn">{icon("search", 16)}بحث</button></form>'
            '</div>')
    body = ""
    if q:
        try:
            if by == "no":
                body = _set_detail(conn, base, q)
            else:
                v = _num_in(q)
                if v is None:
                    raise ValueError("اكتب الوزن رقماً (مثال: 12.5)")
                body = _set_near(conn, base, by, v)
        except ValueError as e:
            body = f'<div class="msg bad">{_e(str(e))}</div>'
    else:
        body = ('<div class="panel"><div class="empty">اكتب رقم التشغيل ثم '
                '«بحث» — تظهر تفاصيل الطقم ودفعته وحركاته كاملةً. أو اختر '
                '«الوزن المقيد» أو «الوزن القائم» واكتب الوزن.</div></div>')
    inner = (f'<div class="ptitle"><h2>{icon("sets", 22)}حركة الطقم</h2>'
             f'<span class="hint">كشاشة البرنامج — الأوزان والدفعة ومكانه'
             f' الآن وكل حركاته</span></div>{form}{body}')
    return frame(base, "sets", "حركة الطقم", inner, csrf, css=_SETS_CSS)


# ══════════════════════════════════════════════════════════════════
#  الصناديق — أقسامٌ يسمّيها المدير وحساباتٌ يضعها فيها
# ══════════════════════════════════════════════════════════════════

MAX_BOXES, MAX_ACCS = 40, 120


def load_boxes(conn):
    """[{id,name,codes}] — وأول مرةٍ تُزرع من لوحات «لوحة التحكم» (لوحات
    الحسابات: الصناديق · الذهب الفاقد · المبيعات…) فيجد المدير ما يعرفه."""
    raw = _get(conn, K_BOXES, "")
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return _with_scrap(conn, [
                    b for b in data if isinstance(b, dict)
                    and b.get("id") and b.get("name")])
        except ValueError:
            pass
    out = []
    try:
        from models import dash_panels as dp
        for i, p in enumerate(dp.load_panels(), 1):
            if (p.get("kind") or "accounts") != "accounts" or dp.is_pnl(p):
                continue
            codes = [dp.ITALIAN_ACC if c == dp.ITALIAN else str(c)
                     for c in p.get("accounts") or []]
            if codes:
                out.append({"id": f"b{i}", "name": p["title"],
                            "codes": codes})
    except Exception:
        out = []
    if not out:
        out = [{"id": "b1", "name": "الصناديق",
                "codes": ["1400", "1500", "1200", "1210"]}]
    return _with_scrap(conn, out)


# 5.6.5: «صندوق الكسر» قسمٌ في الصناديق كلوحته في لوحة التحكم — عيار 18
# برصيده وكشفه أولاً ثم بقية الأعيرة. قسمٌ خاص (kind=scrap): أعيرته من سجل
# الكسر فلا تُضاف إليه حسابات. ويُضاف مرةً لمن له أقسامٌ محفوظة من قبل،
# فإن حذفه المدير لم يعد (ويعود بإضافة قسمٍ اسمه «صندوق الكسر»).
SCRAP_ID = "scrap"
SCRAP_NAME = "صندوق الكسر"


def _scrap_box(name=SCRAP_NAME):
    return {"id": SCRAP_ID, "name": name, "codes": [], "kind": "scrap"}


def _with_scrap(conn, boxes):
    if any(b.get("kind") == "scrap" for b in boxes) or \
            _get(conn, K_SCRAP_OFF, "") == "1":
        return boxes
    return boxes + [_scrap_box()]


def _save_boxes(boxes, flags=None):
    from database.database import db
    with db() as conn:
        _set(conn, K_BOXES, json.dumps(boxes, ensure_ascii=False))
        for k, v in (flags or {}).items():
            _set(conn, k, v)


def boxes_action(data):
    """تعديل الأقسام (عرضٌ لا محاسبة: لا يُنشئ حساباً ولا قيداً)."""
    import time as _t
    from database.database import db
    act = str(data.get("act") or "")
    bid = str(data.get("id") or "")
    name = " ".join(str(data.get("name") or "").split())[:60]
    code = str(data.get("code") or "").strip()[:20]
    with _post_lock:
        with db(readonly=True) as conn:
            boxes = load_boxes(conn)
            if code and not conn.execute(
                    "SELECT 1 FROM accounts WHERE code=? AND is_active=1",
                    (code,)).fetchone():
                return {"ok": False, "error": "الحساب غير موجود في الدليل"}
        box = next((b for b in boxes if b["id"] == bid), None)
        flags = {}
        scrap = box is not None and box.get("kind") == "scrap"
        if act == "add_box":
            if not name:
                return {"ok": False, "error": "اكتب اسم القسم"}
            if len(boxes) >= MAX_BOXES:
                return {"ok": False, "error": "بلغت الأقسام حدّها"}
            if name == SCRAP_NAME and not any(b.get("kind") == "scrap"
                                              for b in boxes):
                # يعود «صندوق الكسر» بأعيرته إن حُذف من قبل
                new_id = SCRAP_ID
                boxes.append(_scrap_box())
                flags[K_SCRAP_OFF] = "0"
            else:
                new_id = f"b{int(_t.time() * 1000)}"
                boxes.append({"id": new_id, "name": name, "codes": []})
        elif box is None:
            return {"ok": False, "error": "القسم غير موجود — حدّث الصفحة"}
        elif scrap and act in ("add_acc", "del_acc"):
            return {"ok": False, "error": "صندوق الكسر يعرض أعيرته من سجل "
                                          "الكسر — لا تُضاف إليه حسابات"}
        elif act == "ren_box":
            if not name:
                return {"ok": False, "error": "اكتب الاسم الجديد"}
            box["name"] = name
        elif act == "del_box":
            boxes.remove(box)
            if scrap:
                flags[K_SCRAP_OFF] = "1"
        elif act in ("up", "down"):
            i = boxes.index(box)
            j = i - 1 if act == "up" else i + 1
            if 0 <= j < len(boxes):
                boxes[i], boxes[j] = boxes[j], boxes[i]
        elif act == "add_acc":
            if not code:
                return {"ok": False, "error": "اختر الحساب من الاقتراحات"}
            if code in box["codes"]:
                return {"ok": False, "error": "الحساب في القسم من قبل"}
            if len(box["codes"]) >= MAX_ACCS:
                return {"ok": False, "error": "بلغ القسم حدّه"}
            box["codes"].append(code)
        elif act == "del_acc":
            box["codes"] = [c for c in box["codes"] if c != code]
        else:
            return {"ok": False, "error": "أمرٌ غير معروف"}
        _save_boxes(boxes, flags)
    return {"ok": True, "id": new_id if act == "add_box" else bid}


_BOX_JS = r"""
(function(){
 function act(d,go){return MW.post('/boxes',d).then(function(r){
  if(r.ok){if(go)location.href=go(r);else location.reload();}
  else{MW.toast(r.error||'تعذّر الحفظ',false);}});}
 var nb=document.getElementById('nbname');
 document.getElementById('nbadd').onclick=function(){
  if(!nb.value.trim()){nb.focus();return;}
  act({act:'add_box',name:nb.value},function(r){
   return MW.base+'/boxes?b='+encodeURIComponent(r.id);});};
 nb.addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();
  document.getElementById('nbadd').click();}});
 var p=document.querySelector('[data-box]');if(!p)return;
 var id=p.getAttribute('data-box'),inp=p.querySelector('.accin'),
  add=p.querySelector('.accadd'),picked=null;
 if(inp&&add){MW.ac(inp,'/api/acc',function(r){picked=r;add.disabled=!r;});
  add.disabled=true;
  add.onclick=function(){if(picked)act({act:'add_acc',id:id,code:picked.code});};}
 p.querySelectorAll('[data-del]').forEach(function(b){b.onclick=function(){
  act({act:'del_acc',id:id,code:b.getAttribute('data-del')});};});
 p.querySelector('.ren').onclick=function(){var n=prompt('الاسم الجديد للقسم:',
  p.getAttribute('data-name'));if(n&&n.trim())act({act:'ren_box',id:id,name:n});};
 p.querySelector('.up').onclick=function(){act({act:'up',id:id});};
 p.querySelector('.down').onclick=function(){act({act:'down',id:id});};
 p.querySelector('.delbox').onclick=function(){MW.confirm('حذف القسم',
  'حذف القسم «'+p.getAttribute('data-name')+'» من الرابط؟\nالحسابات نفسها لا '+
  'تتأثر — يُحذف العرض وحده.').then(function(y){if(y)act({act:'del_box',id:id},
  function(){return MW.base+'/boxes';});});};
})();
"""

# 5.6.1: كـ«حركة المصنع» — الأقسام لوحاتٌ في الأعلى، واختيار قسمٍ يُظهر تحته
# جدول حساباته بأرصدتها
_BOX_CSS = """
.newbox{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.newbox input{min-width:220px}
.btiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));
gap:12px;margin:0 0 16px}
.btiles .tile{min-height:118px}
.btiles .tile .g{font-size:12.5px;color:var(--muted);direction:ltr;
font-variant-numeric:tabular-nums}
.addacc{display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;
margin:14px 0 0}
.addacc label{flex:1 1 280px}
.bx tr.on td{background:#FFF6E0}
.bx .cdm{display:none;color:var(--muted);font-size:12px;font-weight:400;
direction:ltr;text-align:right}
@media (max-width:640px){.newbox input{min-width:0;flex:1 1 auto}
.btiles{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.btiles .tile{min-height:96px;padding:12px 6px}
.btiles .tile .ic{width:28px;height:28px}
.bx .cd{display:none}.bx .cdm{display:block}.bx .acts .lbl{display:none}
.bx .acts .btn{padding:5px 7px}.bx .acts{width:1%}
.bx{font-size:12.5px}.bx th{white-space:normal}
.bx td,.bx th{padding:7px 4px}}
"""


def _box_head(sel, n_label):
    """رأس القسم المختار: اسمه وأزرار الترتيب والتسمية والحذف."""
    return (f'<h3>{icon("boxes", 20)}{_e(sel["name"])}'
            f'<span class="pill">{_e(n_label)}</span><span class="sp">'
            f'</span><button class="btn sm gh up" title="نقل القسم قبل '
            f'(يميناً)">▶</button><button class="btn sm gh down" title="نقل '
            f'القسم بعد (يساراً)">◀</button><button class="btn sm gh ren">'
            f'{icon("edit", 15)}تسمية</button><button class="btn sm red '
            f'delbox">{icon("trash", 15)}حذف القسم</button></h3>')


def _scrap_section(conn, base, sel, query):
    """صندوق الكسر كلوحته في البرنامج: كل عيارٍ بوزنه الفعلي ومكافئه —
    عيار 18 أولاً — والمختار منها كشفُه تحته (`scrap_karat_statement`)."""
    import config
    from models import dash_panels as dp
    from models.inventory import scrap_karat_statement
    from models.accounts import SCRAP_BOX
    u = _e(_unit())
    base_k = config.BASE_KARAT
    rows = sorted(dp.scrap_rows(conn),
                  key=lambda r: (r["karat"] != base_k, r["karat"]))
    kq = str(query.get("k") or "").strip()
    k = int(kq) if kq.isdigit() and int(kq) in config.KARATS else base_k

    def f2(v):
        return _m(v) if abs(v) >= 0.0005 else "—"
    trs = "".join(
        f'<tr class="{"on" if r["karat"] == k else ""}"><td><b>عيار '
        f'{r["karat"]}</b></td><td class="n">{f2(r["actual"])}</td>'
        f'<td class="n">{_w(r["eq18"]) if abs(r["eq18"]) >= 0.0005 else "—"}'
        f'</td><td class="acts"><a class="btn sm {"gold" if r["karat"] == k else "gh"}"'
        f' href="{_e(_link(base, "/boxes", b=sel["id"], k=r["karat"]))}">'
        f'{icon("stmt", 15)}<span class="lbl">كشف</span></a></td></tr>'
        for r in rows)
    ta = round(sum(r["actual"] for r in rows), 3)
    te = round(sum(r["eq18"] for r in rows), 3)
    table = (f'<div class="scroll"><table class="tbl bx"><tr><th>العيار</th>'
             f'<th class="n">الوزن الفعلي (جم)</th><th class="n">المكافئ '
             f'({u})</th><th></th></tr>{trs}<tr class="tot"><td>الإجمالي</td>'
             f'<td class="n">{_m(ta)}</td><td class="n">{_w(te)}</td><td '
             f'class="acts"><a class="btn sm gh" href="'
             f'{_e(_link(base, "/stmt", code=SCRAP_BOX))}" title="كشف الحساب '
             f'{_e(SCRAP_BOX)} كاملاً">{icon("stmt", 15)}<span class="lbl">'
             f'كشف الحساب </span>{_e(SCRAP_BOX)}</a></td></tr></table></div>')
    box = (f'<section class="panel" data-box="{_e(sel["id"])}" data-name="'
           f'{_e(sel["name"])}">{_box_head(sel, "الأعيرة")}{table}'
           f'<p class="note" style="margin:10px 0 0">الوزن الفعلي بعيار كل '
           f'صندوق، والمكافئ هو الرصيد المحاسبي — انقر «كشف» أمام العيار '
           f'يظهر كشفه تحته.</p></section>')
    # كشف العيار المختار — الأحدث أولاً، وكل الحركة افتراضاً (5.7.3)
    d1, d2, key = _period(query, "all")
    try:
        st = scrap_karat_statement(conn, k, d1, d2)
    except ValueError as e:
        return box + f'<div class="msg bad">{_e(str(e))}</div>'
    srows = []
    shown, hidden = _latest_first(st["rows"])
    for r in shown:
        s = " ".join(str(x) for x in (r.get("doc_no"), r.get("op"),
                                      r.get("name"), r.get("desc")) if x)
        acts = ("" if r.get("op") in ("رصيد سابق", "تسوية") else
                _doc_links(base, r.get("src"), r.get("sid"), r.get("eid")))
        srows.append(
            f'<tr data-s="{_e(s.lower())}"><td class="n">{_e(r["date"])}'
            f'</td><td>{_e(r.get("op") or "")}</td><td class="n">'
            f'{_e(r.get("doc_no") or "")}</td><td>{_e(r.get("name") or "")}'
            + (f'<br><small class="note">{_e(r["desc"])}</small>'
               if r.get("desc") else "") + '</td>'
            f'<td class="n">{f2(r["inw"])}</td><td class="n">{f2(r["outw"])}'
            f'</td><td class="n bal">{_m(r["bal"])}</td><td class="n bal">'
            f'{_w(r["bal18"])}</td><td class="acts">{acts}</td></tr>')
    stmt = (f'<div class="panel"><h3>{icon("stmt", 20)}كشف صندوق الكسر — '
            f'عيار {k}<span class="pill">الأحدث أولاً</span>'
            f'<span class="pill">الرصيد {_m(st["closing"])} جم</span>'
            f'<span class="pill">وارد {_m(st["total_in"])}</span><span '
            f'class="pill">صادر {_m(st["total_out"])}</span><span class="sp">'
            f'</span><input id="mq" placeholder="ابحث في الكشف…" style="'
            f'min-width:200px"></h3>'
            + (f'<div class="scroll"><table class="tbl"><tr><th>التاريخ</th>'
               f'<th>العملية</th><th>المستند</th><th>الجهة / البيان</th>'
               f'<th class="n">وارد (جم)</th><th class="n">صادر (جم)</th>'
               f'<th class="n bal">الرصيد (عيار {k})</th><th class="n bal">بمكافئ '
               f'{u}</th><th></th></tr>{"".join(srows)}</table></div>'
               '<div id="mnone" class="empty" style="display:none">لا نتائج'
               '</div>' + _more_note(hidden) if srows else
               f'<div class="empty">لا حركة لعيار {k} في {_e(_span(d1, d2))}'
               '</div>') + '</div>')
    return (box + _period_bar(base, "/boxes", key, d1, d2,
                              {"b": sel["id"], "k": k}) + stmt)


def boxes_page(conn, base, csrf, query=None):
    from models import dash_panels as dp
    query = query or {}
    u = _e(_unit())
    boxes = load_boxes(conn)
    sel = next((b for b in boxes if b["id"] == query.get("b")),
               boxes[0] if boxes else None)
    tiles = []
    for b in boxes:
        tiles.append(
            f'<a class="tile{" main" if sel is b else ""}" href="'
            f'{_e(_link(base, "/boxes", b=b["id"]))}">{icon("boxes", 32)}'
            f'<b>{_e(b["name"])}</b><span class="n">'
            + ("الأعيرة" if b.get("kind") == "scrap"
               else f'{len(b["codes"])} حساب') + '</span></a>')
    head = (f'<div class="ptitle"><h2>{icon("boxes", 22)}الصناديق</h2>'
            f'<span class="hint">اختر قسماً يظهر تحته جدول حساباته</span>'
            f'<span class="sp"></span><span class="newbox"><input id="nbname"'
            f' maxlength="60" placeholder="اسم القسم الجديد…"><button '
            f'class="btn" id="nbadd">{icon("plus", 16)}إضافة قسم</button>'
            f'</span></div>'
            + (f'<div class="btiles">{"".join(tiles)}</div>' if tiles else
               '<div class="panel"><div class="empty">لا أقسام بعد — اكتب '
               'اسم القسم في الأعلى ثم «إضافة قسم»</div></div>'))
    if sel is None:
        return frame(base, "boxes", "الصناديق", head, csrf, css=_BOX_CSS,
                     js=_BOX_JS)
    if sel.get("kind") == "scrap":
        return frame(base, "boxes", f"الصناديق — {sel['name']}",
                     head + _scrap_section(conn, base, sel, query), csrf,
                     css=_BOX_CSS, js=_BOX_JS + _SEARCH_JS)
    rows = dp.account_rows(conn, sel["codes"]) if sel["codes"] else []
    tg = round(sum(r["gold_balance"] for r in rows), 3)
    tc = round(sum(r["cash_balance"] for r in rows), 2)

    def num(v, money=False):
        if not v:
            return "—"
        return (f'<span class="{"neg" if v < 0 else ""}">'
                f'{_m(v) if money else _w(v)}</span>')
    trs = "".join(
        f'<tr><td><b>{_e(r["name"])}</b><small class="cdm">{_e(r["code"])}'
        f'</small></td><td class="n cd">{_e(r["code"])}'
        f'</td><td class="n">{num(r["gold_balance"])}</td><td class="n">'
        f'{num(r["cash_balance"], True)}</td><td class="acts"><a class="btn sm'
        f' gh" href="{_e(_link(base, "/stmt", code=r["code"]))}" title="كشف '
        f'الحساب">{icon("stmt", 15)}<span class="lbl">كشف</span></a> '
        f'<button class="btn sm red" data-del="'
        f'{_e(r["code"])}" title="إزالة من القسم">✕</button></td></tr>'
        for r in rows)
    table = (f'<div class="scroll"><table class="tbl bx"><tr><th>الحساب</th>'
             f'<th class="n cd">الرقم</th><th class="n">الذهب ({u})</th>'
             f'<th class="n">النقد (ريال)</th><th></th></tr>{trs}'
             f'<tr class="tot"><td>الإجمالي</td><td class="cd"></td><td class="n">'
             f'{_w(tg)}</td><td class="n">{_m(tc)}</td><td></td></tr>'
             f'</table></div>' if rows else
             '<div class="empty">لا حسابات في هذا القسم بعد — أضفها من '
             'الخانة أدناه</div>')
    body = (f'<section class="panel" data-box="{_e(sel["id"])}" data-name="'
            f'{_e(sel["name"])}">{_box_head(sel, f"{len(rows)} حساب")}{table}'
            f'<div class="addacc"><label class="ac">إضافة حساب للقسم — اكتب '
            f'أول الحروف<input class="accin" placeholder="اسم الحساب أو '
            f'رقمه…" autocomplete="off"></label><button class="btn gold '
            f'accadd">{icon("plus", 16)}إضافة الحساب</button></div>'
            f'</section>')
    return frame(base, "boxes", f"الصناديق — {sel['name']}", head + body,
                 csrf, css=_BOX_CSS, js=_BOX_JS)


# ══════════════════════════════════════════════════════════════════
#  الفترة (اليوم · أمس · الأسبوع · الشهر · …) — مشتركة
# ══════════════════════════════════════════════════════════════════

PERIODS = (("today", "اليوم"), ("yesterday", "أمس"), ("week", "هذا الأسبوع"),
           ("month", "هذا الشهر"), ("prev_month", "الشهر الماضي"),
           ("year", "هذه السنة"), ("all", "كل الحركة"))


def _period(query, default="month"):
    """(من، إلى، مفتاح الفترة) — من الرابط، أو تاريخين مكتوبين."""
    from models import dash_panels as dp
    d1, d2 = _date(query.get("from")), _date(query.get("to"))
    if d1 or d2:
        return d1 or None, d2 or None, "custom"
    key = query.get("per") if query.get("per") in dict(PERIODS) else default
    a, b = dp.period_range(key)
    return a, b, key


def _period_bar(base, path, key, d1, d2, keep):
    links = "".join(
        f'<a class="chip{" on" if k == key else ""}" href="'
        f'{_e(_link(base, path, per=k, **keep))}">{_e(t)}</a>'
        for k, t in PERIODS)
    hidden = "".join(f'<input type="hidden" name="{_e(k)}" value="{_e(v)}">'
                     for k, v in keep.items() if v not in (None, ""))
    return (f'<div class="chips">{links}</div>'
            f'<form class="fl" method="get" action="{_e(base + path)}">'
            f'{hidden}<label>من<input type="date" name="from" value="'
            f'{_e(d1 or "")}"></label><label>إلى<input type="date" name="to"'
            f' value="{_e(d2 or "")}"></label><button class="btn gh">عرض '
            f'الفترة</button></form>')


def _span(d1, d2):
    if not d1 and not d2:
        return "كل الحركة"
    if d1 == d2:
        return d1
    return f"{d1 or 'البداية'} ← {d2 or 'اليوم'}"


def _doc_links(base, src, sid, eid):
    """أزرار «الصور» و«الفاتورة/عرض» لمستند — بقوالب البرنامج نفسها."""
    from services import print_manager as pm
    out = ""
    t = pm.models_target(src, sid)
    if t:
        out += (f'<a class="btn sm gold" target="_blank" rel="noopener" '
                f'href="{_e(_link(base, f"/doc/{t[0]}/{t[1]}"))}">'
                f'{icon("photo", 15)}الصور</a> ')
    if src and sid and src in pm.BUILDERS and src != "manual":
        label = ("الفاتورة" if src in ("invoices", "set_purchases",
                                       "purchases") else "عرض")
        href = _link(base, f"/doc/{src}/{sid}")
    elif eid:
        label, href = "عرض", _link(base, f"/doc/manual/{eid}")
    else:
        return out
    return out + (f'<a class="btn sm gh" target="_blank" rel="noopener" '
                  f'href="{_e(href)}">{icon("doc", 15)}{label}</a>')


# 5.7.3: الكشوف كلها تُفتح على **آخر الحركات** — الأحدث أعلاها — وعلى «كل
# الحركة» افتراضاً (فيظهر آخر ما للحساب ولو قبل سنة)؛ والعرض يقف عند آخر
# LATEST_ROWS سطراً، وما قبلها باختيار فترة.
LATEST_ROWS = 400


def _latest_first(rows, limit=LATEST_ROWS):
    """(الأسطر الأحدث أولاً، كم سطراً حُجب) — والأرصدة كما حُسبت تصاعدياً."""
    out = list(reversed(rows))
    return out[:limit], max(0, len(out) - limit)


def _more_note(hidden):
    return (f'<div class="note" style="margin-top:8px">تظهر آخر {LATEST_ROWS}'
            f' حركة — وقبلها {hidden} حركة: اختر فترةً من الأعلى لعرضها.'
            '</div>' if hidden else "")


# ══════════════════════════════════════════════════════════════════
#  أزرار التعديل والحذف لكل سطر (5.7.0) — في كشف الحساب وحركة المصنع
# ══════════════════════════════════════════════════════════════════

def _acts_ctx(conn, rows):
    """{رقم القيد: {kind, vat, rec}} لأسطر الصفحة — باستعلاماتٍ مجمّعة،
    فلا يُسأل عن كل سطرٍ وحده. الحكم النهائي عند الحفظ (`doc_delete`)."""
    if not ops_enabled(conn) or edits_locked(conn):
        return None
    inv_ids = {int(r["sid"]) for r in rows if r.get("src") == "invoices"
               and r.get("sid")}
    v_ids = {int(r["sid"]) for r in rows if r.get("src") == "vouchers"
             and r.get("sid")}
    eids = {int(r["eid"]) for r in rows if str(r.get("eid") or "").isdigit()}

    def grab(sql, ids):
        if not ids:
            return []
        ids = sorted(ids)
        return conn.execute(sql.format(",".join("?" * len(ids))),
                            ids).fetchall()
    invs = {r["id"]: r for r in grab(
        "SELECT id, kind, COALESCE(vat_applied,0) vat FROM invoices"
        " WHERE id IN ({})", inv_ids)}
    vs = {r["id"]: r["kind"] for r in grab(
        "SELECT id, kind FROM vouchers WHERE id IN ({})", v_ids)}
    try:
        reversed_ = {r[0] for r in grab(
            "SELECT src_entry_id FROM doc_reversals WHERE src_entry_id"
            " IN ({})", eids)}
    except Exception:
        reversed_ = set()
    out = {}
    for r in rows:
        eid = r.get("eid")
        if not str(eid or "").isdigit():
            continue
        eid = int(eid)
        src, sid = r.get("src"), r.get("sid")
        info = None
        if src == "invoices" and sid in invs and invs[sid]["kind"] in (
                "sale", "sale_return"):
            info = {"kind": invs[sid]["kind"], "vat": bool(invs[sid]["vat"]),
                    "rec": sid}
        elif src == "vouchers" and sid in vs:
            info = {"kind": vs[sid], "vat": False, "rec": sid}
        elif src in (None, "", "manual"):
            info = {"kind": "journal", "vat": False, "rec": eid}
        elif src == "fixing_ops":
            info = {"kind": "fixing", "vat": False, "rec": sid}
        if info:
            info["reversed"] = eid in reversed_
            out[eid] = info
    return out


def _row_acts(base, ctx, eid, no=""):
    """✎ تعديل و🗑 حذف (أو ↺ عكس للضريبية) لسطر مستند."""
    if not ctx or not str(eid or "").isdigit():
        return ""
    info = ctx.get(int(eid))
    if not info or info["reversed"]:
        return ""
    out = ""
    if info["kind"] in EDIT_KINDS:
        out += (f'<a class="btn sm gh" href="'
                f'{_e(_link(base, "/ops/" + info["kind"], edit=eid))}" '
                f'title="تعديل في مكانه برقمه">{icon("edit", 14)}'
                f'<span class="lbl">تعديل</span></a> ')
    if info["vat"]:
        out += (f'<button class="btn sm red" data-delx="{_e(eid)}" '
                f'data-rev="1" data-no="{_e(no)}" title="فاتورة ضريبية — '
                f'تُعكس بمرتجع">↺<span class="lbl"> عكس</span></button>')
    else:
        out += (f'<button class="btn sm red" data-delx="{_e(eid)}" '
                f'data-no="{_e(no)}" title="حذف وعكس القيد — ورقمه للمستند '
                f'التالي">{icon("trash", 14)}<span class="lbl">حذف</span>'
                f'</button>')
    return out


_ACTS_CSS = """
.tbl input.mg{width:18px;height:18px;margin:0 0 0 6px;vertical-align:middle;
accent-color:#A8822E}
.tbl .acts .btn{margin:1px 0}
@media (max-width:640px){.tbl .acts .lbl{display:none}
.tbl .acts .btn{padding:5px 7px}}
"""


_ACTS_JS = r"""
(function(){
 function nn(){return Date.now().toString(36)+Math.random().toString(36).slice(2,10);}
 function locked(r){if(r&&r.locked&&r.unlock){location.href=r.unlock+'?next='+
  encodeURIComponent(location.pathname+location.search);return true;}return false;}
 document.addEventListener('click',function(e){
  var b=e.target.closest?e.target.closest('[data-delx]'):null;if(!b)return;
  e.preventDefault();var rev=b.getAttribute('data-rev')==='1',
   no=b.getAttribute('data-no')||'';
  MW.confirm(rev?'عكس الفاتورة الضريبية':'حذف وعكس القيد',rev?
   ('الفاتورة '+no+' ضريبية — لا تُحذف نظاماً.\nتُعكس بمرتجعٍ يشير إليها،'+
    ' وتبقى هي برقمها.'):
   ('حذف '+no+' نهائياً؟\nيُعكس قيده كاملاً (الأرصدة والأطقم وصندوق الكسر)'+
    '، ويختفي من الكشوف، وأول مستندٍ جديد من نوعه يأخذ رقمه.'))
  .then(function(y){if(!y)return;b.disabled=true;
   MW.post('/api/delete',{eid:+b.getAttribute('data-delx'),reverse:rev,
    nonce:nn()}).then(function(r){if(locked(r))return;
    if(!r.ok){b.disabled=false;MW.toast(r.error||'تعذّر',false);return;}
    MW.toast(r.msg,true);setTimeout(function(){location.reload();},1100);});});});
 var mg=document.getElementById('mgbtn');if(!mg)return;
 function sel(){return Array.prototype.slice.call(
  document.querySelectorAll('input.mg:checked'));}
 document.addEventListener('change',function(e){var t=e.target;
  if(!t.classList||!t.classList.contains('mg'))return;var n=sel().length;
  mg.style.display=n>=2?'':'none';mg.textContent='⧉ دمج المحدد ('+n+')';});
 mg.onclick=function(){var s=sel(),ks={};
  s.forEach(function(x){ks[x.getAttribute('data-k')]=1;});
  if(Object.keys(ks).length>1){MW.toast('الدمج لفواتير من نوعٍ واحد: مبيعات '+
   'مع مبيعات أو مرتجع مع مرتجع',false);return;}
  var nos=s.map(function(x){return x.getAttribute('data-no');});
  MW.confirm('دمج الفواتير','دمج '+nos.join('، ')+' في أقدمها؟\nتنتقل إليها '+
   'الأطقم كلها بأوزانها وأجورها، وتُلغى الأخرى ويأخذ رقمَها أولُ فاتورةٍ'+
   ' جديدة من نوعها.').then(function(y){if(!y)return;mg.disabled=true;
   MW.post('/api/merge',{ids:s.map(function(x){return +x.getAttribute('data-id');}),
    nonce:nn()}).then(function(r){if(locked(r))return;mg.disabled=false;
    if(!r.ok){MW.toast(r.error||'تعذّر الدمج',false);return;}
    MW.toast(r.msg,true);setTimeout(function(){location.reload();},1300);});});};
})();
"""


# ══════════════════════════════════════════════════════════════════
#  حركة المصنع — لوحاتٌ بالأنواع، ثم سجلّ النوع المختار
# ══════════════════════════════════════════════════════════════════

MOVES_TITLE = "فواتير / حركة المصنع"    # 5.7.4: كان «حركة المصنع»

MOVE_KINDS = (("supply", "الوارد"), ("sale", "المبيعات"),
              ("sale_return", "المرتجعات"), ("receipt", "القبض"),
              ("payment", "الصرف"), ("manual", "القيود اليومية"),
              ("fixing", "التسكير"), ("purchase", "المشتريات"),
              ("other", "عمليات أخرى"), ("all", "الكل"))

_SEARCH_JS = r"""
(function(){var q=document.getElementById('mq');if(!q)return;
 q.addEventListener('input',function(){var v=q.value.trim().toLowerCase(),n=0;
  document.querySelectorAll('tr[data-s]').forEach(function(r){
   var hit=!v||(r.getAttribute('data-s')||'').indexOf(v)>=0;
   r.style.display=hit?'':'none';if(hit)n++;});
  var e=document.getElementById('mnone');if(e)e.style.display=n?'none':'';});
})();
"""


def _amount_txt(d):
    det = d.get("detail") or {}
    g = d["group"]
    if g in ("sale", "sale_return") and det:
        return f'أجور {_m(det.get("wages"))}'
    if g in ("receipt", "payment") and det:
        ks = " · ".join(f'عيار {k["karat"]}: {_m(k["weight"])}'
                        for k in det.get("karats") or [])
        cash = f'{_m(det["cash"])} ريال' if det.get("cash") else ""
        return " · ".join(x for x in (ks, cash) if x) or "—"
    return f'{_m(d["cash"])} ريال' if d.get("cash") else "—"


def moves_page(conn, base, csrf, query):
    from models import day_feed
    g = query.get("g") if query.get("g") in dict(MOVE_KINDS) else ""
    # 5.7.3: كل الحركة افتراضاً — الأحدث أولاً، وآخر LATEST_ROWS مستنداً
    d1, d2, key = _period(query, "all")
    data = day_feed.period(conn, d1, d2, g or "all",
                           limit=(LATEST_ROWS if key == "all" else 1500)
                           if g else 1)
    counts = data["counts"]
    total = sum(counts.values())
    tiles = "".join(
        f'<a class="tile{" main" if k == g else ""}" style="min-height:118px"'
        f' href="{_e(_link(base, "/moves", g=k, per=key if key != "custom" else None, **({"from": d1, "to": d2} if key == "custom" else {})))}">'
        f'{icon(k, 32)}<b>{_e(t)}</b><span class="n">'
        f'{total if k == "all" else counts.get(k, 0)}</span></a>'
        for k, t in MOVE_KINDS
        if k in ("all", "supply", "sale", "sale_return", "receipt", "payment",
                 "manual", "fixing") or counts.get(k))
    keep = {"g": g}
    head = (f'<div class="ptitle"><h2>{icon("moves", 22)}{MOVES_TITLE}</h2>'
            f'<span class="hint">{_e(_span(d1, d2))} — اختر نوعاً يظهر '
            f'سجلّه</span></div>'
            + _period_bar(base, "/moves", key, d1, d2, keep)
            + f'<div class="tiles" style="grid-template-columns:repeat('
              f'auto-fill,minmax(150px,1fr));margin-bottom:16px">{tiles}</div>')
    if not g:
        return frame(base, "moves", MOVES_TITLE, head, csrf)
    u = _e(_unit())
    docs = data["docs"]
    actx = _acts_ctx(conn, docs)
    title = dict(MOVE_KINDS)[g]
    tw = round(sum(float(d.get("weight") or 0) for d in docs), 3)
    rows = []
    for d in docs:
        det = d.get("detail") or {}
        keys = [d["no"], d.get("party"), d.get("op"), d.get("desc")]
        for m in det.get("models") or []:
            keys.append(m["model"])
            keys += [i["wo"] for i in m["items"]]
        s = " ".join(str(x) for x in keys if x).lower()
        sets = (f'<span class="pill">{det["n_sets"]} طقم</span>'
                if det.get("n_sets") else "")
        rev = (f' <span class="pill sale_return">عُكس بـ '
               f'{_e(d["reversed_by"])}</span>' if d.get("reversed_by")
               else "")
        w = float(d.get("weight") or 0)
        rows.append(
            f'<tr data-s="{_e(s)}"><td class="n">{_e(d.get("date"))}'
            f'<br><small>{_e(d.get("time") or "")}</small></td>'
            f'<td><span class="pill {_e(d["group"])}">{_e(d.get("op") or "")}'
            f'</span></td><td class="n">{_e(d["no"])}</td>'
            f'<td><b>{_e(d.get("party") or d.get("desc") or "—")}</b>{rev}'
            + (f'<br><small class="note">{_e(d["desc"])}</small>'
               if d["group"] == "supply" and d.get("party")
               and d.get("desc") else "")
            + f'</td><td class="n">{_w(w) + " " + u if w else "—"} {sets}</td>'
            f'<td>{_e(_amount_txt(d))}</td>'
            f'<td class="acts">{_doc_links(base, d.get("src"), d.get("sid"), d.get("eid"))}'
            f' {_row_acts(base, actx, d.get("eid"), d.get("no"))}'
            f'</td></tr>')
    body = (f'<div class="panel"><h3>{icon(g, 20)}{_e(title)} — '
            f'{_e(_span(d1, d2))}<span class="pill">{len(docs)} عملية</span>'
            f'<span class="pill">{_w(tw)} {u}</span><span class="sp"></span>'
            f'<input id="mq" placeholder="ابحث بالطرف أو الرقم أو رقم التشغيل'
            f'…" style="min-width:240px"></h3>'
            + ('<div class="scroll"><table class="tbl"><tr><th>التاريخ</th>'
               '<th>العملية</th><th>المستند</th><th>الطرف</th>'
               '<th class="n">الوزن</th><th>الأجور / النقد</th><th></th></tr>'
               + "".join(rows) + '</table></div>'
               '<div id="mnone" class="empty" style="display:none">لا نتائج'
               '</div>' + _more_note(max(0, int(
                   (data.get("count") if g == "all"
                    else (data.get("counts") or {}).get(g)) or 0)
                   - len(docs))) if rows else
               f'<div class="empty">لا {_e(title)} في {_e(_span(d1, d2))}'
               '</div>') + '</div>')
    return frame(base, "moves", f"{MOVES_TITLE} — {title}", head + body, csrf,
                 css=_ACTS_CSS, js=_SEARCH_JS + _ACTS_JS)


# ══════════════════════════════════════════════════════════════════
#  كشف حساب — يُكتب الاسم فيظهر كشفه
# ══════════════════════════════════════════════════════════════════

_STMT_JS = r"""
(function(){var i=document.getElementById('sacc');if(!i)return;
 MW.ac(i,'/api/acc',function(r){if(r){var u=new URL(location.href);
  u.searchParams.delete('code');u.searchParams.set('acc',r.id);
  location.href=u.toString();}});i.focus();})();
"""


def stmt_page(conn, base, csrf, query):
    from models import journal
    from models.accounts import subtree_ids
    acc = None
    a = str(query.get("acc") or "").strip()
    c = str(query.get("code") or "").strip()[:20]
    if a.isdigit():
        acc = conn.execute("SELECT * FROM accounts WHERE id=?",
                           (int(a),)).fetchone()
    elif c:
        acc = conn.execute("SELECT * FROM accounts WHERE code=?",
                           (c,)).fetchone()
    d1, d2, key = _period(query, "all")
    keep = {"acc": acc["id"]} if acc else {}
    head = (f'<div class="ptitle"><h2>{icon("stmt", 22)}كشف حساب</h2>'
            f'<span class="hint">اكتب أول حروف الاسم واختره من القائمة</span>'
            f'</div><div class="panel"><div class="fl" style="margin:0">'
            f'<label class="ac" style="flex:1 1 340px">الحساب أو الجهة<input '
            f'id="sacc" autocomplete="off" placeholder="اسم العميل أو المورد '
            f'أو رقم الحساب…" value="{_e(acc["name"] if acc else "")}">'
            f'</label></div></div>')
    if acc is None:
        return frame(base, "stmt", "كشف حساب", head + (
            '<div class="empty">اكتب اسم الحساب أعلاه — تظهر الأسماء '
            'المتقاربة من أول حرف</div>'), csrf, js=_STMT_JS)
    ids = subtree_ids(conn, acc["id"]) if not acc["is_postable"] \
        else [acc["id"]]
    rows = journal.statement(conn, ids if len(ids) > 1 else acc["id"],
                             d1, d2)
    u = _e(_unit())
    shown, hidden = _latest_first(rows)
    actx = _acts_ctx(conn, [r for r in shown if r.get("op") != "رصيد سابق"])
    n_mg = 0
    trs = []
    for r in shown:
        s = " ".join(str(x) for x in (r.get("doc_no"), r.get("op"),
                                      r.get("name"), r.get("desc")) if x)
        acts = ("" if r.get("op") == "رصيد سابق" else
                _doc_links(base, r.get("src"), r.get("sid"), r.get("eid"))
                + " " + _row_acts(base, actx, r.get("eid"), r.get("doc_no")))
        # 5.7.0: فواتير البيع (أو المرتجع) غير الضريبية تُختار للدمج
        info = (actx or {}).get(int(r["eid"])) if str(
            r.get("eid") or "").isdigit() else None
        mg = ""
        if info and info["kind"] in ("sale", "sale_return") \
                and not info["vat"] and not info["reversed"]:
            n_mg += 1
            mg = (f'<input type="checkbox" class="mg" data-id="'
                  f'{_e(info["rec"])}" data-k="{_e(info["kind"])}" data-no="'
                  f'{_e(r.get("doc_no") or "")}" title="اختر للدمج">')
        trs.append(
            f'<tr data-s="{_e(s.lower())}"><td class="n">{mg}{_e(r["date"])}</td>'
            f'<td>{_e(r.get("op") or "")}</td><td class="n">'
            f'{_e(r.get("doc_no") or "")}</td><td>{_e(r.get("name") or "")}'
            + (f'<br><small class="note">{_e(r["desc"])}</small>'
               if r.get("desc") else "") + '</td>'
            # 5.7.5: عمودا الرصيد مظلّلان تظليلاً هادئاً — يُعرف بهما الرصيد
            + "".join(
                f'<td class="n{c}">{v}</td>' for v, c in (
                    (_w(r["gd"]) if r["gd"] else "", ""),
                    (_w(r["gc"]) if r["gc"] else "", ""),
                    (_w(r["gbal"]), " bal"),
                    (_m(r["cd"]) if r["cd"] else "", ""),
                    (_m(r["cc"]) if r["cc"] else "", ""),
                    (_m(r["cbal"]), " bal")))
            + f'<td class="acts">{acts}</td></tr>')
    gb = rows[-1]["gbal"] if rows else 0.0
    cb = rows[-1]["cbal"] if rows else 0.0
    kp = (f'<div class="kpis"><div class="kpi gold"><div class="k">رصيد '
          f'الذهب</div><div class="v">{_w(gb)} <small>{u}</small></div>'
          f'<div class="s">{"مدين" if gb > 0 else "دائن" if gb < 0 else "—"}'
          f'</div></div><div class="kpi"><div class="k">رصيد النقد</div>'
          f'<div class="v">{_m(cb)}</div><div class="s">ريال · '
          f'{"مدين" if cb > 0 else "دائن" if cb < 0 else "—"}</div></div>'
          f'<div class="kpi"><div class="k">الحركات</div><div class="v">'
          f'{max(0, len(rows) - (1 if rows and rows[0].get("op") == "رصيد سابق" else 0))}'
          f'</div><div class="s">{_e(_span(d1, d2))}</div></div></div>')
    mg_btn = ('<button class="btn sm gold" id="mgbtn" style="display:none">'
              '⧉ دمج المحدد</button>' if n_mg >= 2 else "")
    table = (f'<div class="panel"><h3>{icon("stmt", 20)}{_e(acc["name"])}'
             f'<span class="pill">{_e(acc["code"])}</span><span class="pill">'
             f'الأحدث أولاً</span><span class="sp">'
             f'</span>{mg_btn}<input id="mq" placeholder="ابحث في الكشف…" '
             f'style="min-width:220px"></h3><div class="scroll"><table '
             f'class="tbl"><tr><th>التاريخ</th><th>العملية</th><th>المستند'
             f'</th><th>الطرف / البيان</th><th class="n">مدين ذهب</th>'
             f'<th class="n">دائن ذهب</th><th class="n bal">رصيد ذهب ({u})</th>'
             f'<th class="n">مدين نقد</th><th class="n">دائن نقد</th>'
             f'<th class="n bal">رصيد نقد</th><th></th></tr>' + "".join(trs)
             + '</table></div><div id="mnone" class="empty" style="display:'
               'none">لا نتائج</div>' + _more_note(hidden) + '</div>'
             if trs else
             '<div class="empty">لا حركة في الفترة</div>')
    inner = (head + _period_bar(base, "/stmt", key, d1, d2, keep) + kp
             + table)
    return frame(base, "stmt", f"كشف حساب — {acc['name']}", inner, csrf,
                 css=_ACTS_CSS, js=_STMT_JS + _SEARCH_JS + _ACTS_JS)


# ══════════════════════════════════════════════════════════════════
#  تحليل مبيعات العملاء (5.7.5) — شاشة البرنامج نفسها بكل ما فيها:
#  العميل · من/إلى · العيار · «تحديث اللوحات» تفصيلي/تقرير · «فرز» ·
#  أربع لوحات تحت كلٍّ جدولها (إخفاء/إظهار) · الرصيد المتبقي · الطباعة
# ══════════════════════════════════════════════════════════════════

AN_TITLE = "تحليل مبيعات العملاء"
AN_PANELS = (("sales", "إجمالي المبيعات"), ("returns", "إجمالي المرتجعات"),
             ("net_sold", "إجمالي المباع الفعلي"),
             ("collection", "إجمالي التحصيل"))
AN_MERGE_PREF = "sales_analytics_merged"     # اختيار «فرز» في البرنامج
_NC = ' class="n"'

_AN_CSS = """
.anf{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end}
.anf label{display:flex;flex-direction:column;gap:5px;font-size:13px;
color:var(--muted)}
.anf input,.anf select{padding:9px 10px;border:1px solid var(--line);
border-radius:10px;font:inherit;font-size:14px;background:#fff;color:var(--ink)}
.anf .cust{flex:1 1 260px}
.anf .cust input{width:100%}
.anf .msort{display:flex;gap:6px;flex-wrap:wrap;align-items:center;
font-size:13px;color:var(--ink)}
.anf .msort span{color:var(--muted)}
.anf .msort label{flex-direction:row;align-items:center;gap:5px;
background:#F8F3E8;border:1px solid var(--line);border-radius:9px;
padding:6px 9px;color:var(--ink);cursor:pointer}
.ancols{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;
align-items:start}
.ancols.rep{grid-template-columns:repeat(3,minmax(0,1fr))}
.ancol{background:var(--card);border:1px solid var(--line);border-radius:16px;
padding:12px;box-shadow:0 1px 2px rgba(60,40,10,.04);min-width:0}
.anbox{background:linear-gradient(180deg,#FFFDF7,#FFF6E2);
border:1px solid #E9D59F;border-radius:13px;padding:12px 10px;text-align:center;
min-height:84px;display:flex;flex-direction:column;justify-content:center;gap:6px}
.anbox .t{font-size:14px;color:var(--brown);font-weight:700}
.anbox .v{font-size:19px;font-weight:700;color:var(--ink);direction:ltr;
font-variant-numeric:tabular-nums}
.anbox .s{font-size:12px;color:var(--muted)}
.antog{width:100%;justify-content:center;margin:8px 0}
.ancol .tbl{font-size:13.5px}
.ancol .tbl td,.ancol .tbl th{padding:7px 6px}
.ancol tr.it td{font-weight:700}
.ancol tr.op td{color:#8a6a1e;font-weight:600}
.anrem{margin-top:14px;background:#2f2519;color:#fff;border-radius:14px;
padding:14px 16px;font-size:16px;font-weight:700;text-align:center;
line-height:1.7}
.anrem small{color:#EAD9AE;font-weight:600}
@media (max-width:1100px){.ancols,.ancols.rep{grid-template-columns:
repeat(2,minmax(0,1fr))}}
@media (max-width:640px){.ancols,.ancols.rep{grid-template-columns:1fr}
.anf .cust{flex-basis:100%}}
"""

_AN_JS = r"""
(function(){var i=document.getElementById('ancust');if(!i)return;
 var h=document.getElementById('anc');
 MW.ac(i,'/api/cust',function(r,typing){if(r){h.value=r.id;i.form.submit();}
  else if(typing){h.value='';}});
 document.querySelectorAll('.antog').forEach(function(b){
  b.addEventListener('click',function(){var c=b.closest('.ancol'),
   t=c.querySelector('.anbody'),vis=t.style.display==='none';
   t.style.display=vis?'':'none';b.textContent=vis?'إخفاء الجدول':'إظهار الجدول';
   c.setAttribute('data-exp',vis?'1':'0');});});
 var pr=document.getElementById('anprint');
 if(pr)pr.addEventListener('click',function(e){e.preventDefault();
  var u=new URL(pr.href,location.href),exp=[];
  document.querySelectorAll('.ancol[data-exp="1"]').forEach(function(c){
   exp.push(c.getAttribute('data-k'));});
  u.searchParams.set('exp',exp.join(','));location.href=u.toString();});
})();
"""


def _an_default_from():
    """من: قبل ستة أشهر — كما تفتح شاشة البرنامج."""
    import calendar
    from datetime import date
    t = date.today()
    y, m = t.year, t.month - 6
    if m < 1:
        y, m = y - 1, m + 12
    return date(y, m, min(t.day, calendar.monthrange(y, m)[1])).isoformat()


def search_customers(conn, q, limit=14):
    """عملاء التحليل كقائمة البرنامج: العملاء الخارجيون وحدهم."""
    out = search_parties(conn, q, limit=60, types=("customer",))
    if not out:
        return []
    ids = [r["id"] for r in out]
    internal = {r[0] for r in conn.execute(
        "SELECT id FROM entities WHERE COALESCE(is_internal,0)=1 AND id IN"
        f" ({','.join('?' * len(ids))})", ids)}
    return [r for r in out if r["id"] not in internal][:limit]


def analytics_page(conn, base, csrf, query):
    from models import fiscal
    from models import sales_analytics as sa
    from services import gold_math
    from services import karat_view as kv
    cid = str(query.get("c") or "")
    cust = conn.execute(
        "SELECT id, name, account_id FROM entities WHERE id=? AND"
        " is_deleted=0 AND entity_type='customer'",
        (int(cid),)).fetchone() if cid.isdigit() else None
    d1 = _date(query.get("from")) or _an_default_from()
    d2 = _date(query.get("to")) or _today().isoformat()
    if d2 < d1:
        d1, d2 = d2, d1
    try:
        k = int(query.get("k") or 0)
    except (TypeError, ValueError):
        k = 0
    if k not in KARATS:
        k = int(kv.active() or 18)
    mode = "report" if query.get("mode") == "report" else "detail"
    report = mode == "report"
    # «فرز»: من النموذج إن أُرسل، وإلا آخر اختيارٍ حُفظ في البرنامج
    if query.get("mf"):
        merged = {x for x in sa.MERGEABLE if query.get("m_" + x)}
    else:
        saved = str(fiscal.get_setting(conn, AN_MERGE_PREF, "") or "")
        merged = {x for x in saved.split(",") if x in sa.MERGEABLE}
    titles = dict(AN_PANELS)
    sort = "".join(
        f'<label><input type="checkbox" name="m_{x}" value="1"'
        f'{" checked" if x in merged else ""}>{_e(titles[x])}</label>'
        for x in sa.MERGEABLE)
    kopts = "".join(f'<option value="{x}"{" selected" if x == k else ""}>'
                    f'عيار {x}</option>' for x in KARATS)
    form = (
        f'<form class="panel anf" method="get" action="{_e(base)}/analytics">'
        f'<input type="hidden" name="c" id="anc" value="'
        f'{_e(cust["id"] if cust else "")}"><input type="hidden" name="mf"'
        f' value="1"><label class="ac cust">العميل<input id="ancust" '
        f'autocomplete="off" placeholder="اكتب اسم العميل…" value="'
        f'{_e(cust["name"] if cust else "")}"></label>'
        f'<label>من<input type="date" name="from" value="{_e(d1)}"></label>'
        f'<label>إلى<input type="date" name="to" value="{_e(d2)}"></label>'
        f'<label>العيارات<select name="k">{kopts}</select></label>'
        f'<label>العرض<select name="mode"><option value="detail"'
        f'{"" if report else " selected"}>تفصيلي — اللوحات وأرقام التشغيل '
        f'والأوزان</option><option value="report"'
        f'{" selected" if report else ""}>تقرير — المصروف والمرتجع والصافي '
        f'بأرقامها فقط</option></select></label>'
        f'<div class="msort"><span>فرز (بلا تكرار):</span>{sort}</div>'
        f'<button class="btn">{icon("moves", 16)}تحديث اللوحات</button>'
        f'</form>')
    head = (f'<div class="ptitle"><h2>{icon("analytics", 22)}{AN_TITLE}'
            f'</h2><span class="hint">رقابة إدارية — كشاشة البرنامج '
            f'تماماً</span></div>')
    if cust is None:
        return frame(base, "analytics", AN_TITLE, head + form + (
            '<div class="empty">اكتب اسم العميل أعلاه واختره — تظهر '
            'لوحاته الأربع وجداولها</div>'), csrf, css=_AN_CSS, js=_AN_JS)

    def g(v):
        return gold_math.from_base_karat(float(v or 0), k)
    p = sa.all_panels(conn, cust["id"], d1, d2)
    details = {key: sa.panel_details(conn, key, cust["id"], d1, d2,
                                     merged=key in merged)
               for key, _t in AN_PANELS}
    if report:
        p["net_sold"] = sa.report_net(p)
    coll = p["collection"]
    vals = {"sales": f"{_m(g(p['sales']['weight']))} جم {k}",
            "returns": f"{_m(g(p['returns']['weight']))} جم {k}",
            "net_sold": f"{_m(g(p['net_sold']['weight']))} جم {k}",
            "collection": f"ذهب {_m(g(coll['gold']))} · نقد "
                          f"{_m(coll['cash'])}"}
    subs = {"sales": f"{p['sales']['count']} فاتورة · أجور "
                     f"{_m(p['sales']['wages'])}",
            "returns": f"{p['returns']['count']} فاتورة · أجور "
                       f"{_m(p['returns']['wages'])}",
            "net_sold": ("المصروف − المرتجع" if report else
                         f"{p['net_sold']['count']} رقم تشغيل"),
            "collection": f"{coll['count']} سند قبض"}
    if report:
        titles.update({"sales": "المصروف (المبيعات)",
                       "net_sold": "المباع الصافي"})
    cols = []
    for key, _t in AN_PANELS:
        if report and key == "collection":
            continue
        if key == "collection":
            heads = ["رقم السند", f"الذهب (جم {k})", "المبلغ (ريال)"]
            rows = [(d["wo"], _m(g(d["weight"])), _m(d.get("cash", 0)))
                    for d in details[key]]
        else:
            if key in merged:
                heads = ["رقم التشغيل (بلا تكرار)",
                         f"الوزن (جم {k})" if key == "net_sold"
                         else f"الوزن المقيد (جم {k})"]
            elif key == "net_sold":
                heads = ["رقم التشغيل", f"الوزن (جم {k})"]
            else:
                heads = ["رقم التشغيل", f"الوزن المقيد (جم {k})"]
            rows = [(d["wo"], _m(g(d["weight"]))) for d in details[key]]
        trs = "".join(
            f'<tr class="{"it" if r[0] == sa.ITALIAN_LABEL else "op" if r[0] == sa.OPENING_LABEL else ""}"'
            + (' title="الرقمان التجميعيان 00010 و0010 معاً: ما صُرف منهما'
               ' ناقص ما رجع منهما"' if r[0] == sa.ITALIAN_LABEL else "")
            + '>' + "".join(f'<td{_NC if j else ""}>{_e(v)}</td>'
                            for j, v in enumerate(r)) + '</tr>'
            for r in rows)
        table = (f'<div class="scroll"><table class="tbl"><tr>'
                 + "".join(f'<th{_NC if j else ""}>{_e(h)}</th>'
                           for j, h in enumerate(heads)) + f'</tr>{trs}'
                 '</table></div>' if trs else
                 '<div class="empty" style="padding:14px">لا شيء في الفترة'
                 '</div>')
        body = ("" if report else
                f'<button type="button" class="btn sm gh antog">إخفاء الجدول'
                f'</button><div class="anbody">{table}</div>')
        cols.append(
            f'<section class="ancol" data-k="{key}" data-exp="'
            f'{"0" if report else "1"}"><div class="anbox"><div class="t">'
            f'{_e(titles[key])}</div><div class="v">{_e(vals[key])}</div>'
            f'<div class="s">{_e(subs[key])}</div></div>{body}</section>')
    # الرصيد المتبقي = رصيد حساب العميل في الدليل (كالبرنامج)
    gb = cb = 0.0
    if cust["account_id"]:
        r = conn.execute(
            "SELECT COALESCE(SUM(l.gold_debit-l.gold_credit),0) g,"
            " COALESCE(SUM(l.cash_debit-l.cash_credit),0) c FROM journal_lines"
            " l JOIN journal_entries e ON e.id=l.entry_id WHERE"
            " e.is_deleted=0 AND l.account_id=?",
            (cust["account_id"],)).fetchone()
        gb, cb = round(r["g"], 2), round(r["c"], 2)
    side = "مدين/عليه" if (gb > 0 or cb > 0) else "دائن/له"
    rem = (f'<div class="anrem">الرصيد المتبقي على العميل — ذهب: '
           f'{_m(g(gb))} جم عيار {k} &nbsp;|&nbsp; نقد: {_m(cb)} ريال '
           f'<small>({side})</small></div>')
    visible = [key for key, _t in AN_PANELS
               if not (report and key == "collection")]
    plink = _link(base, f"/doc/customer_analytics/{cust['id']}", **{
        "from": d1, "to": d2, "k": k, "mode": mode,
        "m": ",".join(x for x in sa.MERGEABLE if x in merged),
        "vis": ",".join(visible),
        "exp": "" if report else ",".join(visible)})
    bar = (f'<div class="ptitle" style="margin-top:4px"><h2 style="font-size:'
           f'17px">{icon("customers", 20)}{_e(cust["name"])}</h2><span '
           f'class="hint">{_e(d1)} ← {_e(d2)} · عيار {k} · '
           f'{"تقرير" if report else "تفصيلي"}</span><span class="sp"></span>'
           f'<a class="btn gold" id="anprint" href="{_e(plink)}">🖨 طباعة '
           f'تقرير العميل</a><a class="btn gh" href="'
           f'{_e(_link(base, "/stmt", acc=cust["account_id"]))}">'
           f'{icon("stmt", 16)}كشف حسابه</a></div>')
    inner = (head + form + bar
             + f'<div class="ancols{" rep" if report else ""}">'
             + "".join(cols) + '</div>' + rem)
    return frame(base, "analytics", f"{AN_TITLE} — {cust['name']}", inner,
                 csrf, css=_AN_CSS, js=_AN_JS)


# ══════════════════════════════════════════════════════════════════
#  المستند وصوره — بقوالب الطباعة نفسها
# ══════════════════════════════════════════════════════════════════

DOC_TYPES = ("invoices", "vouchers", "manual", "work_orders", "set_purchases",
             "purchases", "fixing_ops", "melting_ops", "invoice_models",
             "set_purchase_models", "supply_models", "customer_analytics")
_DOC_CSP = ("default-src 'none'; img-src 'self' data:; style-src "
            "'unsafe-inline'; font-src data:; script-src 'unsafe-inline';"
            " base-uri 'none'; form-action 'none'")


def _an_print_kw(query):
    """خيارات طباعة تقرير العميل من الرابط — كما تمرّرها شاشة البرنامج."""
    from models import sales_analytics as sa
    keys = [k for k, _t in AN_PANELS]

    def lst(name, allowed):
        return [x for x in str(query.get(name) or "").split(",")
                if x in allowed]
    try:
        k = int(query.get("k") or 0)
    except (TypeError, ValueError):
        k = 0
    return {"date_from": _date(query.get("from")) or None,
            "date_to": _date(query.get("to")) or None,
            "visible": lst("vis", keys) or keys,
            "expanded": lst("exp", keys),
            "merged": lst("m", sa.MERGEABLE),
            "karat": k if k in KARATS else None,
            "mode": "report" if query.get("mode") == "report" else "detail"}


def doc_page(rest, base, query=None):
    if len(rest) != 2 or rest[0] not in DOC_TYPES or not rest[1].isdigit():
        return _resp(404, _mw()._GONE)
    from services import browser_print
    kw = (_an_print_kw(query or {}) if rest[0] == "customer_analytics"
          else {})
    try:
        html = browser_print.build_page(rest[0], int(rest[1]),
                                        auto_print=False, viewer=False, **kw)
    except Exception as e:                       # noqa: BLE001
        return _resp(404, frame(base, "", "المستند", f'<div class="msg bad">'
                                f'تعذّر عرض المستند: {_e(e)}</div>'))
    bar = ('<div class="noprint" style="position:sticky;top:0;z-index:9;'
           'display:flex;gap:8px;justify-content:center;padding:10px;'
           'background:#43301a;font-family:system-ui,Tahoma">'
           '<button onclick="window.print()" style="padding:8px 18px;border:0;'
           'border-radius:9px;background:#c9a24a;font-weight:700;cursor:'
           'pointer">🖨 طباعة / PDF</button><button onclick="history.length>1'
           '?history.back():window.close()" style="padding:8px 18px;border:0;'
           'border-radius:9px;background:#fff;cursor:pointer">رجوع</button>'
           '</div>')
    html = html.replace("<body dir='rtl'>", "<body dir='rtl'>" + bar, 1)
    html = html.replace("<head>", "<head><meta name='viewport' content="
                                  "'width=device-width,initial-scale=1'>", 1)
    return _resp(200, html, headers={"Content-Security-Policy": _DOC_CSP})


# ══════════════════════════════════════════════════════════════════
#  تسجيل العمليات — بخانات شاشات البرنامج، وبدوالّه في الترحيل
# ══════════════════════════════════════════════════════════════════

OPS = (("sale", "مبيعات", "فاتورة بيع أطقم من الخزنة"),
       ("sale_return", "مرتجع", "مرتجع أطقم إلى الخزنة"),
       ("receipt", "قبض", "سند قبض ذهب ونقد"),
       ("payment", "صرف", "سند صرف ذهب ونقد"),
       ("journal", "قيد يومي", "قيد يومية يدوي متوازن"),
       ("supply", "توريد", "دفعة أطقم واردة من التصنيع"))
OP_ICON = {"journal": "manual"}
KARATS = (18, 21, 22, 24)
MAX_LINES = 300


def _gold_accounts(conn):
    from models.accounts import SCRAP_BOX, gold_accounts
    return [{"id": r["id"], "label": f"{r['code']} — {r['name']}",
             "code": r["code"], "scrap": r["code"] == SCRAP_BOX}
            for r in gold_accounts(conn)]


def _lock_page(base, csrf, why):
    return frame(base, "ops", "تسجيل عمليات", (
        f'<div class="ptitle"><h2>{icon("lock", 22)}تسجيل العمليات</h2></div>'
        f'<div class="panel"><div class="msg info">{_e(why)}</div>'
        '<p class="note">التسجيل من الرابط يكتب في دفاتر المصنع مباشرةً. '
        'لتفعيله افتح في البرنامج: «🔗 رابط المدير» ← علّم خانة «السماح '
        'بتسجيل العمليات من الرابط».</p></div>'), csrf)


def unlock_page(base, csrf, nxt, error=""):
    """رمز لوحة تسجيل العمليات — يُطلب مرةً ويبقى 12 ساعة على الجهاز."""
    return frame(base, "ops", "رمز لوحة تسجيل العمليات", (
        f'<div class="ptitle"><h2>{icon("lock", 22)}لوحة تسجيل العمليات'
        f'</h2></div><div class="panel" style="max-width:460px;margin:20px '
        f'auto"><p class="note" style="margin-top:0">التسجيل والتعديل والحذف '
        f'والدمج من الرابط برمزٍ خاص ضبطه المدير في البرنامج. أدخله لفتح '
        f'اللوحة على هذا الجهاز {OPS_HOURS} ساعة.</p>'
        + (f'<div class="msg bad">{_e(error)}</div>' if error else "")
        + f'<form method="post" action="{_e(base + "/ops/unlock")}" '
        f'class="fl" style="margin:0"><input type="hidden" name="csrf" '
        f'value="{_e(csrf)}"><input type="hidden" name="next" value="'
        f'{_e(nxt)}"><label style="flex:1 1 200px">رمز اللوحة<input '
        f'name="pin" type="password" inputmode="numeric" maxlength="12" '
        f'autocomplete="off" autofocus required></label><button class="btn">'
        f'{icon("lock", 16)}فتح اللوحة</button></form></div>'), csrf)


def _unlock(data, base, csrf):
    from database.database import db
    m = _mw()
    nxt = _safe_next(base, data.get("next"))
    with db(readonly=True) as conn:
        h = _get(conn, K_OPS_PIN, "").strip()
    if not h:
        return _resp(303, "", headers={"Location": nxt})
    if m._locked():
        return _resp(429, unlock_page(base, csrf, nxt, "محاولات كثيرة — "
                                      "انتظر ربع ساعة ثم حاول ثانيةً"))
    if not m._pin_ok(h, str(data.get("pin") or "").strip()):
        m._fail()
        return _resp(401, unlock_page(base, csrf, nxt, "الرمز غير صحيح"))
    ck = (f"{OPS_COOKIE}={_ops_cookie_value(csrf, h)}; Path={base}; "
          f"Max-Age={OPS_HOURS * 3600}; HttpOnly; SameSite=Strict")
    return _resp(303, "", headers={"Location": nxt, "Set-Cookie": ck})


def ops_page(conn, base, csrf, rest, query=None, has_pin=False):
    # 5.6.1: خيارٌ واحد يقرّره المدير — «يُسمح» أو «لا يُسمح» — بلا اشتراط
    # رمز دخول (الرمز يبقى حمايةً اختيارية للرابط كله). 5.7.0: ورمزٌ خاص
    # باللوحة (`has_ops_pin`) يُطلب قبلها في `route`
    query = query or {}
    if not ops_enabled(conn):
        return _lock_page(base, csrf, "تسجيل العمليات من الرابط موقوفٌ من "
                                      "البرنامج.")
    kind = rest[0] if rest else ""
    lock_btn = (f'<form method="post" action="{_e(base + "/ops/lock")}" '
                f'style="margin:0"><input type="hidden" name="csrf" value="'
                f'{_e(csrf)}"><button class="btn sm gh">{icon("lock", 15)}'
                f'قفل اللوحة</button></form>' if has_pin else "")
    if kind not in dict((k, t) for k, t, _s in OPS):
        tiles = "".join(
            f'<a class="tile main" href="{_e(_link(base, f"/ops/{k}"))}">'
            f'{icon(OP_ICON.get(k, k), 38)}<b>{_e(t)}</b><small>{_e(s)}'
            f'</small></a>' for k, t, s in OPS)
        recent = _recent_web(conn, base)
        return frame(base, "ops", "تسجيل عمليات", (
            f'<div class="ptitle"><h2>{icon("ops", 22)}تسجيل عمليات</h2>'
            f'<span class="hint">تُرحَّل في جهاز المصنع كأنها أُدخلت منه — '
            f'باسم «{WEB_USER}»</span><span class="sp"></span>{lock_btn}'
            f'</div><div class="tiles">{tiles}</div>'
            + recent), csrf)
    edit = None
    eq = str(query.get("edit") or "")
    if eq.isdigit() and edits_locked(conn):
        return frame(base, "ops", "تعديل", (
            f'<div class="ptitle"><h2>{icon("lock", 22)}تعديل</h2></div>'
            f'<div class="msg info">{_e(EDIT_LOCKED_MSG)}</div>'), csrf)
    if eq.isdigit():
        try:
            edit = edit_payload(conn, kind, int(eq))
        except ValueError as e:
            return frame(base, "ops", "تعديل", (
                f'<div class="ptitle"><h2>{icon("edit", 22)}تعديل</h2></div>'
                f'<div class="msg bad">{_e(str(e))}</div>'), csrf)
    title = dict((k, t) for k, t, _s in OPS)[kind]
    return frame(base, "ops", (f"تعديل {edit['no']}" if edit else title),
                 _op_form(conn, base, kind, edit), csrf, js=_OPS_JS)


def _recent_web(conn, base):
    rows = conn.execute(
        "SELECT id, entry_date, doc_no, description, source_table,"
        " source_id, created_at FROM journal_entries WHERE is_deleted=0"
        " AND created_by=? ORDER BY id DESC LIMIT 12",
        (WEB_USER,)).fetchall()
    if not rows:
        return ""
    trs = "".join(
        f'<tr><td class="n">{_e(r["entry_date"])}</td><td class="n">'
        f'{_e(r["doc_no"] or "")}</td><td>{_e(r["description"] or "")}</td>'
        f'<td class="acts">{_doc_links(base, r["source_table"], r["source_id"], r["id"])}'
        f'</td></tr>' for r in rows)
    return (f'<div class="sect">آخر ما سُجِّل من الرابط</div><div class="panel">'
            f'<div class="scroll"><table class="tbl"><tr><th>التاريخ</th>'
            f'<th>المستند</th><th>البيان</th><th></th></tr>{trs}</table></div>'
            f'</div>')


def _sel(name, opts, val=None, cls=""):
    return (f'<select id="{name}" class="{cls}">' + "".join(
        f'<option value="{_e(k)}"{" selected" if str(k) == str(val) else ""}>'
        f'{_e(t)}</option>' for k, t in opts) + '</select>')


def _op_form(conn, base, kind, edit=None):
    from services import karat_view as kv
    import config
    k = int(kv.active())
    today = _today().isoformat()
    title = dict((x, t) for x, t, _s in OPS)[kind]
    karats = [(x, f"عيار {x}") for x in KARATS]
    data = {"kind": kind, "k": k, "today": today, "unit": _unit(),
            "vat": float(getattr(config, "VAT_RATE", 0.15) or 0)}
    gaccs = _gold_accounts(conn)
    data["gaccs"] = gaccs
    default_acc = next((a["id"] for a in gaccs if a["code"] == "1200"),
                       gaccs[0]["id"] if gaccs else "")
    if edit:
        # 5.7.0: التعديل في مكانه — برقم المستند نفسه
        data["edit"] = edit
        title = f"تعديل {edit['label']} {edit['no']}"
    head = (f'<div class="ptitle"><h2>{icon("edit" if edit else OP_ICON.get(kind, kind), 22)}'
            f'{_e(title)}</h2><a class="btn gh sm" href="'
            f'{_e(_link(base, "/ops"))}">← كل العمليات</a><span class="sp">'
            f'</span><span class="hint">'
            + (f'يُحفظ في مكانه برقمه {_e(edit["no"])} — وينعكس في البرنامج'
               f' فوراً' if edit else
               f'تُرحَّل باسم «{WEB_USER}» — وتظهر في البرنامج فوراً')
            + '</span></div>'
            '<div id="okbox" class="msg ok" style="display:none"></div>')
    date_f = (f'<label>التاريخ<input id="date" type="date" value="{today}" '
              f'max="{today}"></label>')
    notes_f = ('<label class="w2">البيان (اختياري)<input id="notes" '
               'maxlength="300"></label>')
    party_f = ('<label class="ac w2">الطرف — اكتب أول الحروف<input id="party"'
               ' autocomplete="off" placeholder="اسم العميل أو الجهة…">'
               '</label>')
    acc_opts = [(a["id"], a["label"]) for a in gaccs]
    karat_sel = _sel("scrapk", karats, k)
    if kind in ("sale", "sale_return"):
        sale = kind == "sale"
        h1 = (f'<section class="panel"><h3>① الفاتورة</h3><div class="fg">'
              f'{party_f}<label>{"من حساب" if sale else "إلى حساب"}'
              f'{_sel("src", acc_opts, default_acc)}</label>'
              f'<label id="scrapw" style="display:none">عيار الكسر{karat_sel}'
              f'</label>{date_f}<label style="flex-direction:row;align-items:'
              f'center;gap:8px;margin-top:22px"><input id="vat" type="checkbox"'
              f'> ضريبة {data["vat"] * 100:g}%</label>{notes_f}</div>'
              f'<div class="note" id="pinfo"></div></section>')
        # 5.7.7: خانة صورة الطقم (صورة موديله إن وُجدت) بجانب الإدخال
        h2 = (f'<section class="panel"><h3>② إدخال الطقم</h3>'
              f'<div class="erow"><div class="eflds"><div class="fg">'
              f'<label>رقم التشغيل<input id="eno" autocomplete="off" '
              f'placeholder="اكتب الرقم ثم Enter"></label>'
              f'<label>الموديل<input id="emodel" readonly placeholder="تلقائي">'
              f'</label><label>الوزن<input id="ew" class="num" '
              f'inputmode="decimal"></label><label>العيار'
              f'{_sel("ek", karats, k)}</label><label>الأجر/جم<input id="ewage"'
              f' class="num" inputmode="decimal"></label><label>الماس (للعرض)'
              f'<input id="edia" class="num" inputmode="decimal"></label>'
              f'<label style="justify-content:flex-end"><button class="btn gold"'
              f' id="eadd">{icon("plus", 16)}إضافة سطر</button></label></div>'
              f'<div class="note" id="einfo"></div></div>'
              f'<div class="eph" id="eph"><span class="none">صورة الطقم تظهر '
              f'هنا بعد رقم التشغيل</span></div></div>'
              f'<details style="margin-top:8px"><summary class="note">سطر «أجر '
              f'فقط» (بلا ذهب)</summary><div class="fg" style="margin-top:8px">'
              f'<label>المبلغ<input id="woamt" class="num" inputmode="decimal">'
              f'</label><label class="w2">الوصف<input id="wonote" maxlength="120">'
              f'</label><label style="justify-content:flex-end"><button '
              f'class="btn gh" id="woadd">إضافة الأجر</button></label></div>'
              f'</details></section>')
        h3 = ('<section class="panel"><h3>③ البنود</h3><div class="scroll">'
              '<table class="tbl" id="lines"><tr><th>#</th><th>رقم التشغيل</th>'
              '<th>الموديل</th><th class="n">الوزن</th><th>العيار</th>'
              '<th class="n">الأجر/جم</th><th class="n">الأجور</th>'
              '<th class="n">الماس</th><th></th></tr></table></div>'
              '<div class="kpis" id="tot" style="margin:12px 0 0"></div>'
              '</section>')
        btn = f'✔ ترحيل {"فاتورة المبيعات" if sale else "فاتورة المرتجع"}'
    elif kind in ("receipt", "payment"):
        h1 = (f'<section class="panel"><h3>① السند</h3><div class="fg">'
              f'<label>نوع الطرف{_sel("tmode", [("party", "جهة"), ("account", "حساب من الدليل")], "party")}'
              f'</label>{party_f}<label class="ac w2" id="accw" style="display:'
              f'none">الحساب — اكتب أول الحروف<input id="acc" autocomplete='
              f'"off" placeholder="اسم الحساب أو رقمه…"></label>'
              f'<label>{"إلى" if kind == "receipt" else "من"} الصندوق'
              f'{_sel("box", [("1400", "الصندوق النقدي"), ("1500", "البنك")], "1400")}'
              f'</label>{date_f}{notes_f}</div></section>')
        h2 = (f'<section class="panel"><h3>② السطر</h3><div class="fg">'
              f'<label>النوع{_sel("lk", [("gold", "ذهب"), ("cash", "نقد")], "gold")}'
              f'</label><label class="gw">الوزن الفعلي (جم)<input id="lw" '
              f'class="num" inputmode="decimal"></label><label class="gw">'
              f'العيار{_sel("lkar", karats, k)}</label><label class="cw" '
              f'style="display:none">المبلغ (ريال)<input id="la" class="num" '
              f'inputmode="decimal"></label><label class="w2">ملاحظة<input '
              f'id="ln" maxlength="120"></label><label style="justify-content:'
              f'flex-end"><button class="btn gold" id="ladd">{icon("plus", 16)}'
              f'إضافة سطر</button></label></div></section>')
        h3 = ('<section class="panel"><h3>③ أسطر السند</h3><div class="scroll">'
              '<table class="tbl" id="lines"><tr><th>#</th><th>النوع</th>'
              '<th>العيار</th><th class="n">الوزن الفعلي</th><th class="n">'
              'المكافئ</th><th class="n">المبلغ</th><th>ملاحظة</th><th></th>'
              '</tr></table></div><div class="kpis" id="tot" style="margin:'
              '12px 0 0"></div></section>')
        btn = f'✔ ترحيل {"سند القبض" if kind == "receipt" else "سند الصرف"}'
    elif kind == "journal":
        h1 = (f'<section class="panel"><h3>① القيد</h3><div class="fg">'
              f'{date_f}<label class="w2">بيان القيد (إلزامي)<input id="notes"'
              f' maxlength="300"></label></div></section>')
        h2 = (f'<section class="panel"><h3>② السطر — الذهب بعيار {k}</h3>'
              f'<div class="fg"><label class="ac w2">الحساب — اكتب أول الحروف'
              f'<input id="jacc" autocomplete="off" placeholder="اسم الحساب أو'
              f' رقمه…"></label><label>مدين ذهب<input id="jgd" class="num" '
              f'inputmode="decimal"></label><label>دائن ذهب<input id="jgc" '
              f'class="num" inputmode="decimal"></label><label>مدين نقد<input '
              f'id="jcd" class="num" inputmode="decimal"></label><label>دائن '
              f'نقد<input id="jcc" class="num" inputmode="decimal"></label>'
              f'<label class="w2">بيان السطر<input id="jn" maxlength="120">'
              f'</label><label style="justify-content:flex-end"><button '
              f'class="btn gold" id="jadd">{icon("plus", 16)}إضافة سطر'
              f'</button></label></div></section>')
        h3 = ('<section class="panel"><h3>③ أسطر القيد</h3><div class="scroll">'
              '<table class="tbl" id="lines"><tr><th>#</th><th>الحساب</th>'
              '<th class="n">مدين ذهب</th><th class="n">دائن ذهب</th>'
              '<th class="n">مدين نقد</th><th class="n">دائن نقد</th>'
              '<th>البيان</th><th></th></tr></table></div><div class="kpis" '
              'id="tot" style="margin:12px 0 0"></div></section>')
        btn = "✔ ترحيل القيد"
    else:  # supply
        h1 = (f'<section class="panel"><h3>① الدفعة</h3><div class="fg">'
              f'<label>إلى حساب{_sel("src", acc_opts, default_acc)}</label>'
              f'<label id="scrapw" style="display:none">عيار الكسر{karat_sel}'
              f'</label>{date_f}<label class="w2">المرجع (اختياري)<input '
              f'id="notes" maxlength="80" placeholder="رقم فاتورة الورشة أو '
              f'اسم الدفعة"></label></div></section>')
        h2 = (f'<section class="panel"><h3>② إدخال الطقم</h3><div class="fg">'
              f'<label>رقم التشغيل<input id="sno" autocomplete="off"></label>'
              f'<label class="ac">الموديل<input id="smodel" autocomplete="off">'
              f'</label><label>الذهب<input id="sg" class="num" inputmode='
              f'"decimal"></label><label>الفصوص<input id="ss" class="num" '
              f'inputmode="decimal"></label><label>الأحجار<input id="sb" '
              f'class="num" inputmode="decimal"></label><label>العيار'
              f'{_sel("sk", karats, k)}</label><label>الماس (للعرض)<input '
              f'id="sd" class="num" inputmode="decimal"></label><label '
              f'class="w2">ملاحظة<input id="sn" maxlength="120"></label>'
              f'<label style="justify-content:flex-end"><button class="btn gold"'
              f' id="sadd">{icon("plus", 16)}إضافة سطر</button></label></div>'
              f'<div class="note">الوزن المقيد = الذهب + الفصوص + الأحجار بعد '
              f'خصمها ({int(config.STONE_DISCOUNT_RATE * 100)}%) — كما في شاشة '
              f'التوريد.</div></section>')
        h3 = ('<section class="panel"><h3>③ أطقم الدفعة</h3><div class="scroll">'
              '<table class="tbl" id="lines"><tr><th>#</th><th>رقم التشغيل</th>'
              '<th>الموديل</th><th class="n">الذهب</th><th class="n">الفصوص'
              '</th><th class="n">الأحجار</th><th>العيار</th><th class="n">'
              'الماس</th><th></th></tr></table></div><div class="kpis" id="tot"'
              ' style="margin:12px 0 0"></div></section>')
        data["disc"] = float(config.STONE_DISCOUNT_RATE)
        btn = "✔ ترحيل دفعة التوريد"
    if edit:
        btn = "✔ حفظ التعديل"
    return (head + h1 + h2 + h3
            + f'<div style="display:flex;gap:10px;align-items:center;'
              f'flex-wrap:wrap"><button class="btn big" id="post">{_e(btn)}'
              f'</button><button class="btn gh" id="clear">تفريغ</button></div>'
            + '<script id="opdata" type="application/json">'
            + json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
            + '</script>')


_OPS_JS = r"""
(function(){
 var D=JSON.parse(document.getElementById('opdata').textContent),K=D.kind;
 function $(i){return document.getElementById(i);}
 function nn(){return Date.now().toString(36)+Math.random().toString(36).slice(2,10);}
 var NONCE=nn(),lines=[],party=null,acc=null;
 var w18=function(w,k){return w*k/18;},wk=function(v18,k){return v18*18/k;};
 var U=D.unit;
 if($('party'))MW.ac($('party'),'/api/party',function(r){party=r;
  if($('pinfo'))$('pinfo').textContent=r?(r.sub||''):'';});
 if($('acc'))MW.ac($('acc'),'/api/acc',function(r){acc=r;},function(){return {p:1};});
 function scrapToggle(){var s=$('src');if(!s||!$('scrapw'))return;
  var a=D.gaccs.filter(function(x){return String(x.id)===s.value;})[0];
  $('scrapw').style.display=(a&&a.scrap)?'':'none';}
 if($('src')){$('src').onchange=scrapToggle;scrapToggle();}
 function scrapK(){var s=$('src');if(!s)return null;
  var a=D.gaccs.filter(function(x){return String(x.id)===s.value;})[0];
  return (a&&a.scrap)?+$('scrapk').value:null;}
 function del(i){lines.splice(i,1);render();}
 function tbl(rows){var t=$('lines');while(t.rows.length>1)t.deleteRow(1);
  rows.forEach(function(h,i){var r=t.insertRow(-1);r.innerHTML=h;
   var b=r.querySelector('[data-x]');if(b)b.onclick=function(){del(i);};});}
 function kpis(a){$('tot').innerHTML=a.map(function(x){return '<div class="kpi'+
  (x[2]?' gold':'')+'"><div class="k">'+MW.esc(x[0])+'</div><div class="v">'+
  x[1]+'</div></div>';}).join('');}
 var X='<button class="btn sm red" data-x="1">✕</button>';
 var render=function(){};var build=function(){return null;};
 var summary=function(){return '';};var reset=function(){};
 // ═══ مبيعات · مرتجع ═══
 if(K==='sale'||K==='sale_return'){
  var cur=null,curK=D.k;
  function look(){var no=$('eno').value.trim();if(!no)return;
   if(cur&&cur.no===no){goNext();return;}cur=null;photo(null);$('einfo').textContent='…';
   MW.get('/api/wo',{no:no,mode:K==='sale'?'sale':'return',d:$('date').value,
    inv:(D.edit&&D.edit.inv)||''})
   .then(function(r){if(!r.ok){$('einfo').textContent='';MW.toast(r.error,false);
     $('eno').select();return;}
    cur=r;photo(r);$('emodel').value=r.model||'—';$('ek').value=r.karat;curK=r.karat;
    $('ew').value=r.bulk?'':r.avail.toFixed(2);$('ewage').value=
     (r.wage||0).toFixed(2);$('edia').value=r.diamond?r.diamond:'';
    $('einfo').textContent=(r.bulk?'رقمٌ تجميعي — اكتب الوزن':
     (K==='sale'?'الباقي في الخزنة ':'الخارج عند الجهات ')+r.avail.toFixed(2)+
     ' عيار '+r.karat)+(r.acc?' · من '+r.acc:'');
    goNext();});}
  // 5.7.6: بعد رقم التشغيل يظهر وزنه وينتقل المؤشر إلى خانة الأجر وقيمتها
  // محدّدة — يُكتب أجرٌ جديد فوقها مباشرةً أو تُترك، ثم Enter يضيف السطر.
  // (الرقم التجميعي: إلى الوزن أولاً، ثم Enter إلى الأجر)
  // 5.7.7: صورة الطقم (موديله) — تُكبَّر بالنقر في صفحةٍ جديدة
  function photo(r){var b=$('eph');if(!b)return;
   if(!r){b.className='eph';b.innerHTML='<span class="none">صورة الطقم تظهر '+
    'هنا بعد رقم التشغيل</span>';return;}
   if(r.img&&r.model){var u=MW.base+'/img/'+encodeURIComponent(r.model),
     v=r.ver?('v='+encodeURIComponent(r.ver)):'';
    b.className='eph has';b.innerHTML='<a target="_blank" rel="noopener" href="'+
     MW.esc(u+'?full=1'+(v?'&'+v:''))+'" title="تكبير الصورة"><img alt="'+
     MW.esc(r.model)+'" src="'+MW.esc(u+(v?'?'+v:''))+'"></a>';}
   else{b.className='eph';b.innerHTML='<span class="none">'+(r.model?
    'لا توجد صورة للموديل '+MW.esc(r.model):'بلا موديل')+'</span>';}}
  function hot(el){el.focus();try{el.select();}catch(_){}
   el.classList.add('hot');setTimeout(function(){el.classList.remove('hot');},1400);}
  function goNext(){if(!cur)return;hot(cur.bulk&&!MW.num($('ew'))?$('ew'):$('ewage'));}
  $('eno').addEventListener('keydown',function(e){if(e.key==='Enter'){
   e.preventDefault();look();}});
  $('eno').addEventListener('change',look);
  $('ek').onchange=function(){var nk=+$('ek').value,w=MW.num($('ew')),
   g=MW.num($('ewage'));if(w)$('ew').value=wk(w18(w,curK),nk).toFixed(2);
   if(g)$('ewage').value=(g*18/curK*nk/18).toFixed(2);curK=nk;};
  function add(){if(!cur){look();return;}
   var w=MW.num($('ew')),k=+$('ek').value,g=MW.num($('ewage'));
   if(w<=0){MW.toast('اكتب الوزن',false);$('ew').focus();return;}
   if(!cur.bulk&&w18(w,k)>cur.avail18+0.006){MW.toast(
    'الوزن أكبر من الباقي ('+cur.avail.toFixed(2)+')',false);return;}
   if(!cur.bulk&&lines.some(function(l){return l.id===cur.id;})){
    MW.toast('الطقم مضافٌ من قبل',false);return;}
   lines.push({no:cur.no,id:cur.id,model:cur.model,weight:w,karat:k,wage:g,
    diamond:MW.num($('edia')),bulk:cur.bulk});
   cur=null;photo(null);['eno','emodel','ew','ewage','edia'].forEach(function(i){$(i).value='';});
   $('einfo').textContent='';render();$('eno').focus();}
  $('eadd').onclick=add;
  $('ew').addEventListener('keydown',function(e){if(e.key==='Enter'){
   e.preventDefault();if(MW.num($('ew'))>0)hot($('ewage'));else add();}});
  ['ewage','edia'].forEach(function(i){$(i).addEventListener('keydown',
   function(e){if(e.key==='Enter'){e.preventDefault();add();}});});
  $('ewage').addEventListener('focus',function(){try{$('ewage').select();}catch(_){}});
  $('woadd').onclick=function(){var a=MW.num($('woamt'));if(a<=0){
   MW.toast('اكتب مبلغ الأجر',false);return;}lines.push({wage_only:true,
   amount:a,note:$('wonote').value.trim()});$('woamt').value='';
   $('wonote').value='';render();};
  // 5.7.5: أجر كل سطرٍ مضاف يُعدَّل في مكانه — خانةٌ في الجدول تحدّث
  // الإجمالي فوراً دون إعادة رسمه (فلا يضيع المؤشر من الخانة)
  function wgIn(i,v,t){return '<input class="lwg num" inputmode="decimal" '+
   'data-i="'+i+'" value="'+(+v||0).toFixed(2)+'" title="'+t+'">';}
  function totals(){var tw=0,tg=0;lines.forEach(function(l){
    if(l.wage_only){tg+=l.amount;return;}
    tw+=w18(l.weight,l.karat);tg+=l.weight*l.wage;});
   var vat=$('vat').checked?tg*D.vat:0;
   kpis([['الأطقم',lines.filter(function(l){return !l.wage_only;}).length],
    ['الوزن ('+U+')',MW.fmt(wk(tw,D.k))],['الأجور',MW.fmt(tg)],
    ['الضريبة',MW.fmt(vat)],['الإجمالي',MW.fmt(tg+vat),1]]);}
  render=function(){tbl(lines.map(function(l,i){
    if(l.wage_only)return '<td>'+(i+1)+'</td><td colspan="5">'+
     'أجر فقط'+(l.note?' — '+MW.esc(l.note):'')+'</td><td class="n">'+
     wgIn(i,l.amount,'عدّل مبلغ الأجر')+'</td><td></td><td class="acts">'+X+'</td>';
    return '<td>'+(i+1)+'</td><td class="n">'+MW.esc(l.no)+'</td><td>'+
     MW.esc(l.model||'—')+'</td><td class="n">'+MW.fmt(l.weight)+'</td><td>'+
     l.karat+'</td><td class="n">'+wgIn(i,l.wage,'عدّل أجر الجرام')+
     '</td><td class="n lwt">'+MW.fmt(l.weight*l.wage)+'</td><td class="n">'+
     (l.diamond?MW.fmt(l.diamond):'')+'</td><td class="acts">'+X+'</td>';}));
   document.querySelectorAll('#lines input.lwg').forEach(function(inp){
    inp.addEventListener('input',function(){var l=lines[+inp.getAttribute('data-i')];
     if(!l)return;var v=Math.max(0,MW.num(inp));
     if(l.wage_only)l.amount=v;else{l.wage=v;var c=inp.closest('tr')
      .querySelector('.lwt');if(c)c.textContent=MW.fmt(l.weight*v);}
     totals();});
    inp.addEventListener('focus',function(){inp.select();});
    inp.addEventListener('keydown',function(e){if(e.key==='Enter'){
     e.preventDefault();inp.blur();}});
    inp.addEventListener('blur',function(){inp.value=(MW.num(inp)||0).toFixed(2);});});
   totals();};
  $('vat').onchange=function(){totals();};
  build=function(){if(!party){MW.toast('اختر الطرف من الاقتراحات',false);
    $('party').focus();return null;}
   if(!lines.length){MW.toast('أضف طقماً واحداً على الأقل',false);return null;}
   if(lines.some(function(l){return l.wage_only&&!(l.amount>0);})){
    MW.toast('سطر «أجر فقط» بلا مبلغ — اكتب المبلغ أو احذف السطر',false);
    return null;}
   return {party:party.id,src:+$('src').value,scrap_karat:scrapK(),
    date:$('date').value,vat:$('vat').checked,notes:$('notes').value,
    lines:lines};};
  summary=function(){var n=lines.filter(function(l){return !l.wage_only;}).length;
   return 'الطرف: '+party.label+'\n'+($('src').selectedOptions[0]||{}).text+
    '\nعدد الأطقم: '+n+'\nالتاريخ: '+$('date').value+
    ($('vat').checked?'\nفاتورة ضريبية':'');};
  reset=function(){lines=[];render();$('notes').value='';};
  if(D.edit){var E=D.edit;party=E.party;if(party){$('party').value=party.label;
    $('pinfo').textContent=party.sub||'';}
   if(E.src)$('src').value=E.src;scrapToggle();
   if(E.scrap_karat)$('scrapk').value=E.scrap_karat;
   $('date').value=E.date;$('vat').checked=!!E.vat;$('notes').value=E.notes||'';
   lines=E.lines.slice();}
  render();}
 // ═══ قبض · صرف ═══
 else if(K==='receipt'||K==='payment'){
  function mode(){var a=$('tmode').value==='account';
   $('party').parentNode.style.display=a?'none':'';$('accw').style.display=a?'':'none';}
  $('tmode').onchange=mode;mode();
  function lk(){var g=$('lk').value==='gold';
   document.querySelectorAll('.gw').forEach(function(e){e.style.display=g?'':'none';});
   document.querySelectorAll('.cw').forEach(function(e){e.style.display=g?'none':'';});}
  $('lk').onchange=lk;lk();
  function add(){var g=$('lk').value==='gold';
   if(g){var w=MW.num($('lw'));if(w<=0){MW.toast('اكتب الوزن',false);return;}
    lines.push({kind:'gold',weight:w,karat:+$('lkar').value,notes:$('ln').value.trim()});}
   else{var a=MW.num($('la'));if(a<=0){MW.toast('اكتب المبلغ',false);return;}
    lines.push({kind:'cash',amount:a,notes:$('ln').value.trim()});}
   ['lw','la','ln'].forEach(function(i){$(i).value='';});render();
   (g?$('lw'):$('la')).focus();}
  $('ladd').onclick=add;
  ['lw','la','ln'].forEach(function(i){$(i).addEventListener('keydown',
   function(e){if(e.key==='Enter'){e.preventDefault();add();}});});
  render=function(){var eq=0,c=0;tbl(lines.map(function(l,i){
    if(l.kind==='gold'){var e=w18(l.weight,l.karat);eq+=e;
     return '<td>'+(i+1)+'</td><td>ذهب</td><td>'+l.karat+'</td><td class="n">'+
      MW.fmt(l.weight)+'</td><td class="n">'+MW.fmt(wk(e,D.k))+'</td><td></td><td>'+
      MW.esc(l.notes)+'</td><td class="acts">'+X+'</td>';}
    c+=l.amount;return '<td>'+(i+1)+'</td><td>نقد</td><td></td><td></td><td></td>'+
     '<td class="n">'+MW.fmt(l.amount)+'</td><td>'+MW.esc(l.notes)+
     '</td><td class="acts">'+X+'</td>';}));
   kpis([['الذهب (مكافئ '+U+')',MW.fmt(wk(eq,D.k)),1],['النقد (ريال)',MW.fmt(c),1]]);};
  build=function(){var a=$('tmode').value==='account';
   if(a?!acc:!party){MW.toast(a?'اختر الحساب من الاقتراحات':
    'اختر الجهة من الاقتراحات',false);return null;}
   if(!lines.length){MW.toast('أضف سطراً واحداً على الأقل',false);return null;}
   return {party:a?null:party.id,account:a?acc.id:null,box:$('box').value,
    date:$('date').value,notes:$('notes').value,rows:lines};};
  summary=function(){var a=$('tmode').value==='account';
   return 'الطرف: '+(a?acc.label+' ('+acc.sub+')':party.label)+'\nالأسطر: '+
    lines.length+'\n'+($('box').selectedOptions[0]||{}).text+'\nالتاريخ: '+
    $('date').value;};
  reset=function(){lines=[];render();$('notes').value='';};
  if(D.edit){var E=D.edit;
   if(E.party){party=E.party;$('party').value=party.label;$('tmode').value='party';}
   else if(E.acc){acc=E.acc;$('acc').value=acc.label;$('tmode').value='account';}
   mode();$('box').value=E.box||'1400';$('date').value=E.date;
   $('notes').value=E.notes||'';lines=E.rows.slice();}
  render();}
 // ═══ قيد يومي ═══
 else if(K==='journal'){
  var jac=null;MW.ac($('jacc'),'/api/acc',function(r){jac=r;},function(){return {p:1};});
  function add(){if(!jac){MW.toast('اختر الحساب من الاقتراحات',false);
    $('jacc').focus();return;}
   var v=['jgd','jgc','jcd','jcc'].map(function(i){return MW.num($(i));});
   if(!v.some(function(x){return x>0;})){MW.toast('اكتب قيمةً في السطر',false);return;}
   lines.push({account:jac.id,label:jac.label+' ('+jac.sub+')',gd:v[0],gc:v[1],
    cd:v[2],cc:v[3],note:$('jn').value.trim()});jac=null;
   ['jacc','jgd','jgc','jcd','jcc','jn'].forEach(function(i){$(i).value='';});
   render();$('jacc').focus();}
  $('jadd').onclick=add;
  ['jgd','jgc','jcd','jcc','jn'].forEach(function(i){$(i).addEventListener('keydown',
   function(e){if(e.key==='Enter'){e.preventDefault();add();}});});
  render=function(){var s=[0,0,0,0];tbl(lines.map(function(l,i){
    s[0]+=l.gd;s[1]+=l.gc;s[2]+=l.cd;s[3]+=l.cc;
    return '<td>'+(i+1)+'</td><td>'+MW.esc(l.label)+'</td>'+[l.gd,l.gc,l.cd,l.cc]
     .map(function(x){return '<td class="n">'+(x?MW.fmt(x):'')+'</td>';}).join('')+
     '<td>'+MW.esc(l.note)+'</td><td class="acts">'+X+'</td>';}));
   var ok=Math.abs(s[0]-s[1])<0.011&&Math.abs(s[2]-s[3])<0.011&&lines.length;
   kpis([['ذهب: مدين / دائن',MW.fmt(s[0])+' / '+MW.fmt(s[1])],
    ['نقد: مدين / دائن',MW.fmt(s[2])+' / '+MW.fmt(s[3])],
    ['التوازن',ok?'متوازن ✔':'غير متوازن ✘',ok]]);};
  build=function(){if(!$('notes').value.trim()){MW.toast('اكتب بيان القيد',false);
    $('notes').focus();return null;}
   if(lines.length<2){MW.toast('القيد سطران على الأقل',false);return null;}
   return {date:$('date').value,notes:$('notes').value,lines:lines};};
  summary=function(){return 'البيان: '+$('notes').value+'\nالأسطر: '+lines.length+
   '\nالتاريخ: '+$('date').value;};
  reset=function(){lines=[];render();$('notes').value='';};
  if(D.edit){$('date').value=D.edit.date;$('notes').value=D.edit.notes||'';
   lines=D.edit.lines.slice();}
  render();}
 // ═══ توريد ═══
 else if(K==='supply'){
  MW.ac($('smodel'),'/api/models',null);
  function chk(){var no=$('sno').value.trim();if(!no)return Promise.resolve(false);
   if(lines.some(function(l){return l.no===no&&!l.bulk;})){
    MW.toast('رقم التشغيل مكرّر في الدفعة',false);return Promise.resolve(false);}
   return MW.get('/api/wo',{no:no,mode:'supply'}).then(function(r){
    if(!r.ok){MW.toast(r.error,false);$('sno').select();return false;}
    if(r.bulk&&!$('smodel').value)$('smodel').value=r.model||'';
    return r;});}
  $('sno').addEventListener('keydown',function(e){if(e.key==='Enter'){
   e.preventDefault();chk().then(function(r){if(r)$('smodel').focus();});}});
  function add(){chk().then(function(r){if(!r)return;
   var g=MW.num($('sg')),s=MW.num($('ss')),b=MW.num($('sb'));
   if(g+s+b<=0){MW.toast('اكتب وزن الذهب',false);$('sg').focus();return;}
   lines.push({no:r.no||$('sno').value.trim(),bulk:!!r.bulk,model:$('smodel').value.trim(),
    gold:g,small:s,big:b,karat:+$('sk').value,diamond:MW.num($('sd')),
    note:$('sn').value.trim()});
   ['sno','smodel','sg','ss','sb','sd','sn'].forEach(function(i){$(i).value='';});
   render();$('sno').focus();});}
  $('sadd').onclick=add;
  ['sg','ss','sb','sd','sn'].forEach(function(i){$(i).addEventListener('keydown',
   function(e){if(e.key==='Enter'){e.preventDefault();add();}});});
  render=function(){var reg=0;tbl(lines.map(function(l,i){
    reg+=w18(l.gold+l.small+l.big*(1-D.disc),l.karat);
    return '<td>'+(i+1)+'</td><td class="n">'+MW.esc(l.no)+'</td><td>'+
     MW.esc(l.model||'—')+'</td>'+[l.gold,l.small,l.big].map(function(x){
     return '<td class="n">'+(x?MW.fmt(x):'')+'</td>';}).join('')+'<td>'+l.karat+
     '</td><td class="n">'+(l.diamond?MW.fmt(l.diamond):'')+'</td><td class="acts">'+
     X+'</td>';}));
   kpis([['الأطقم',lines.length],['الوزن المقيد التقريبي ('+U+')',
    MW.fmt(wk(reg,D.k)),1]]);};
  build=function(){if(!lines.length){MW.toast('أضف طقماً واحداً على الأقل',false);
    return null;}return {src:+$('src').value,scrap_karat:scrapK(),
    date:$('date').value,notes:$('notes').value,lines:lines};};
  summary=function(){return ($('src').selectedOptions[0]||{}).text+'\nعدد الأطقم: '+
   lines.length+'\nالتاريخ: '+$('date').value;};
  reset=function(){lines=[];render();$('notes').value='';};
  render();}
 $('clear').onclick=function(){if(lines.length&&!confirm('تفريغ الأسطر؟'))return;
  reset();};
 var busy=false,EDIT=D.edit||null,
  PURL=EDIT?('/api/edit/'+K+'/'+EDIT.eid):('/api/post/'+K);
 $('post').onclick=function(){if(busy)return;var p=build();if(!p)return;
  MW.confirm(EDIT?'تأكيد التعديل':'تأكيد الترحيل',summary()+(EDIT?
   '\n\nيُحفظ في مكانه برقمه '+EDIT.no+' — وينعكس في دفاتر المصنع الآن.':
   '\n\nتُرحَّل في دفاتر المصنع الآن.'))
  .then(function(y){if(!y)return;busy=true;var b=$('post');b.disabled=true;
   var t=b.textContent;b.textContent=EDIT?'… جارٍ الحفظ':'… جارٍ الترحيل';
   p.nonce=NONCE;
   MW.post(PURL,p).then(function(r){busy=false;b.disabled=false;
    b.textContent=t;if(!r.ok){if(r.locked&&r.unlock){location.href=r.unlock+
     '?next='+encodeURIComponent(location.pathname+location.search);return;}
     MW.toast(r.error||'تعذّر الترحيل',false);return;}
    if(EDIT){lines=[];b.style.display='none';$('clear').style.display='none';}
    NONCE=nn();if(!EDIT)reset();var ok=$('okbox');ok.style.display='block';
    ok.innerHTML='✔ '+MW.esc(r.msg)+(r.links||[]).map(function(l){
     return ' <a class="btn sm gh" target="_blank" rel="noopener" href="'+
     MW.esc(MW.base+l[1])+'">'+MW.esc(l[0])+'</a>';}).join('');
    ok.scrollIntoView({behavior:'smooth',block:'center'});
    MW.toast((EDIT?'تم حفظ التعديل: ':'تم الترحيل: ')+(r.no||''),true);});});};
 window.addEventListener('beforeunload',function(e){if(lines.length){
  e.preventDefault();e.returnValue='';}});
})();
"""


# ══════════════════════════════════════════════════════════════════
#  الترحيل — بدوالّ البرنامج نفسها، بعد تحقّقٍ صارم من كل خانة
# ══════════════════════════════════════════════════════════════════

def _f(v, name, lo=0.0, hi=1e9):
    """رقمٌ آمن: لا نصّ ولا سالب ولا ما لا نهاية."""
    try:
        x = float(v or 0)
    except (TypeError, ValueError):
        raise ValueError(f"قيمةٌ غير صحيحة في «{name}»")
    if x != x or x < lo or x > hi:
        raise ValueError(f"قيمةٌ خارج الحدود في «{name}»")
    return x


def _txt(v, n=200):
    return " ".join(str(v or "").split())[:n]


def _id(v, name):
    try:
        i = int(v)
    except (TypeError, ValueError):
        raise ValueError(f"اختر {name}")
    if i <= 0:
        raise ValueError(f"اختر {name}")
    return i


def _post_date(v):
    d = _date(v)
    if not d:
        raise ValueError("اكتب التاريخ")
    if d > _today().isoformat():
        raise ValueError("لا يُرحَّل من الرابط بتاريخٍ بعد اليوم")
    return d


def _entity(conn, eid):
    r = conn.execute("SELECT * FROM entities WHERE id=? AND is_deleted=0",
                     (eid,)).fetchone()
    if not r:
        raise ValueError("الطرف غير موجود — اختره من الاقتراحات")
    return r


def _karat(v):
    k = int(_f(v, "العيار", 0, 99))
    if k not in KARATS:
        raise ValueError("عيارٌ غير معروف")
    return k


def _gold_src(conn, v, karat_v):
    """(حساب الذهب، عيار الكسر) — حسابٌ من مخازن الذهب وحدها."""
    from models.accounts import SCRAP_BOX
    aid = _id(v, "الحساب")
    row = next((a for a in _gold_accounts(conn) if a["id"] == aid), None)
    if row is None:
        raise ValueError("الحساب ليس من مخازن الذهب")
    karat = None
    if row["code"] == SCRAP_BOX:
        karat = _karat(karat_v)
    return aid, karat


def _lines_of(data, key="lines"):
    rows = data.get(key) or []
    if not isinstance(rows, list) or not rows:
        raise ValueError("أضف سطراً واحداً على الأقل")
    if len(rows) > MAX_LINES:
        raise ValueError("الأسطر أكثر من المسموح في مستندٍ واحد")
    return [r for r in rows if isinstance(r, dict)]


def _invoice_input(conn, kind, data, orig=None):
    """(الطرف، الحساب، العيار، التاريخ، الضريبة، البيان، السلة) من خانات
    النموذج — مُتحقَّقاً. `orig` في التعديل: {طقم: (الوزن المخزَّن، الأجر
    المخزَّن)} فيبقى ما لم يُغيَّر كما هو بلا تقريبٍ ذهاباً وإياباً."""
    from models import inventory
    from models import wo_moves as wm
    from services import karat_view as kv
    orig = orig or {}
    pid = _id(data.get("party"), "الطرف")
    ent = _entity(conn, pid)
    internal = ent["entity_type"] == "internal"
    src, karat = _gold_src(conn, data.get("src"), data.get("scrap_karat"))
    date = _post_date(data.get("date"))
    vat = bool(data.get("vat")) and not internal
    desc = _txt(data.get("notes"), 300)
    wk = wm.SALE if kind == "sale" else wm.RETURN
    cart = []
    for li in _lines_of(data):
        if li.get("wage_only"):
            cart.append({"wage_only": True, "weight": 0.0,
                         "amount": _f(li.get("amount"), "مبلغ الأجر", 0.01),
                         "note": _txt(li.get("note"), 120)})
            continue
        wo = inventory.get_wo_by_no(conn, _txt(li.get("no"), 40))
        if wo is None:
            raise ValueError(f"رقم التشغيل {li.get('no')} غير موجود")
        k = _karat(li.get("karat"))
        wv = _f(li.get("weight"), "الوزن", 0.0, 1e6)
        if wv <= 0:
            raise ValueError(f"اكتب وزن الطقم {wo['work_order_no']}")
        w18 = kv.store(wv, k)
        o = orig.get(wo["id"])
        if o and abs(kv.g(o[0], k) - wv) <= 0.0051:
            w18 = o[0]          # سطر الفاتورة المعدَّلة كما كان
        elif not wo["is_bulk"]:
            # الوزن كما هو مخزَّن إن لم يُغيَّر — بلا تقريبٍ ذهاباً وإياباً
            avail = float(wm.default_weight(conn, wo, wk))
            if avail and abs(kv.g(avail, k) - wv) <= 0.0051:
                w18 = avail
        rate = _f(li.get("wage"), "الأجر", 0.0, 1e6)
        r18 = kv.rate_store(rate, k)
        if o and o[1] is not None and abs(kv.rate(o[1], k) - rate) <= 0.0051:
            r18 = o[1]
        cart.append({"work_order_id": wo["id"], "weight": w18, "karat": k,
                     "diamond": _f(li.get("diamond"), "الماس", 0.0, 1e5),
                     "wage_override": None if internal else r18})
    return pid, ent, src, karat, date, vat, desc, cart


def _inv_links(docs):
    links = []
    for d in docs:
        links.append((f"🖼 صور {d['invoice_no']}",
                      f"/doc/invoice_models/{d['id']}"))
        links.append((f"📄 الفاتورة {d['invoice_no']}",
                      f"/doc/invoices/{d['id']}"))
    return links


def _post_invoice(conn, kind, data):
    from models import invoices
    pid, ent, src, karat, date, vat, desc, cart = _invoice_input(conn, kind,
                                                                 data)
    fn = invoices.create_sale if kind == "sale" else invoices.create_sale_return
    res = fn(conn, pid, cart, date, WEB_USER, vat, desc,
             source_account_id=src, scrap_karat=karat)
    docs = [res] + ([res["split"]] if res.get("split") else [])
    links = _inv_links(docs)
    nos = " · ".join(d["invoice_no"] for d in docs)
    label = "فاتورة المبيعات" if kind == "sale" else "فاتورة المرتجع"
    return {"ok": True, "no": nos, "id": res["id"], "links": links,
            "msg": f"رُحّلت {label} {nos} — «{ent['name']}»"}


def _voucher_input(conn, data):
    pid = data.get("party")
    aid = data.get("account")
    if pid:
        pid = _id(pid, "الجهة")
        ent = _entity(conn, pid)
        target = ent["name"]
        aid = None
    else:
        aid = _id(aid, "الحساب")
        a = conn.execute("SELECT code, name FROM accounts WHERE id=? AND"
                         " is_active=1 AND is_postable=1", (aid,)).fetchone()
        if not a:
            raise ValueError("الحساب غير صالح — اختر حساباً قابلاً للترحيل")
        target = f"{a['code']} — {a['name']}"
        pid = None
    box = str(data.get("box") or "1400")
    if box not in ("1400", "1500"):
        raise ValueError("الصندوق غير معروف")
    rows = []
    for r in _lines_of(data, "rows"):
        if r.get("kind") == "gold":
            rows.append({"kind": "gold",
                         "weight": _f(r.get("weight"), "الوزن", 0.01, 1e6),
                         "karat": _karat(r.get("karat")),
                         "notes": _txt(r.get("notes"), 120)})
        elif r.get("kind") == "cash":
            rows.append({"kind": "cash",
                         "amount": _f(r.get("amount"), "المبلغ", 0.01, 1e10),
                         "notes": _txt(r.get("notes"), 120)})
    if not rows:
        raise ValueError("أضف سطراً واحداً على الأقل")
    return pid, aid, target, box, rows


def _post_voucher(conn, kind, data):
    from models import vouchers
    pid, aid, target, box, rows = _voucher_input(conn, data)
    res = vouchers.create_voucher(
        conn, kind, _post_date(data.get("date")), WEB_USER, entity_id=pid,
        account_id=aid, rows=rows, cash_account_code=box,
        notes=_txt(data.get("notes"), 300))
    label = "سند القبض" if kind == "receipt" else "سند الصرف"
    return {"ok": True, "no": res["voucher_no"], "id": res["id"],
            "links": [(f"📄 {label} {res['voucher_no']}",
                       f"/doc/vouchers/{res['id']}")],
            "msg": f"رُحّل {label} {res['voucher_no']} — {target}"}


def _journal_input(conn, data):
    from services import karat_view as kv
    desc = _txt(data.get("notes"), 300)
    if not desc:
        raise ValueError("اكتب بيان القيد")
    lines = []
    for li in _lines_of(data):
        aid = _id(li.get("account"), "الحساب")
        if not conn.execute("SELECT 1 FROM accounts WHERE id=? AND"
                            " is_active=1 AND is_postable=1",
                            (aid,)).fetchone():
            raise ValueError("حسابٌ غير قابل للترحيل في القيد")
        lines.append({
            "account_id": aid,
            "gold_debit": kv.store(_f(li.get("gd"), "مدين ذهب", 0, 1e7)),
            "gold_credit": kv.store(_f(li.get("gc"), "دائن ذهب", 0, 1e7)),
            "cash_debit": round(_f(li.get("cd"), "مدين نقد", 0, 1e11), 2),
            "cash_credit": round(_f(li.get("cc"), "دائن نقد", 0, 1e11), 2),
            "line_desc": _txt(li.get("note"), 120)})
    return desc, lines


def _post_journal(conn, data):
    from models import journal
    desc, lines = _journal_input(conn, data)
    eid = journal.manual_entry(conn, _post_date(data.get("date")), desc,
                               lines, WEB_USER)
    no = conn.execute("SELECT doc_no FROM journal_entries WHERE id=?",
                      (eid,)).fetchone()
    no = (no["doc_no"] if no and no["doc_no"] else f"#{eid}")
    return {"ok": True, "no": no, "id": eid,
            "links": [(f"📄 القيد {no}", f"/doc/manual/{eid}")],
            "msg": f"رُحّل القيد {no} — {desc}"}


def _post_supply(conn, data):
    import config
    from models import inventory
    from services import karat_view as kv
    dest, karat = _gold_src(conn, data.get("src"), data.get("scrap_karat"))
    rows = []
    for li in _lines_of(data):
        k = _karat(li.get("karat"))
        rows.append({
            "wo_no": _txt(li.get("no"), 40),
            "model_no": _txt(li.get("model"), 60),
            "gold": kv.store(_f(li.get("gold"), "الذهب", 0, 1e6), k),
            "small_stones": kv.store(_f(li.get("small"), "الفصوص", 0, 1e6), k),
            "big_stones": kv.store(_f(li.get("big"), "الأحجار", 0, 1e6), k),
            "discount_rate": float(config.STONE_DISCOUNT_RATE),
            "wage_per_gram": float(config.DEFAULT_WAGE_PER_GRAM),
            "diamond": _f(li.get("diamond"), "الماس", 0, 1e5),
            "karat": k, "notes": _txt(li.get("note"), 120)})
    res = inventory.create_work_orders_batch(
        conn, rows, _post_date(data.get("date")), WEB_USER,
        dest_account_id=dest, scrap_karat=karat,
        reference=_txt(data.get("notes"), 80))
    eid = res.get("entry_id")
    wo = conn.execute("SELECT id FROM work_orders WHERE entry_id=? AND"
                      " is_deleted=0 ORDER BY id LIMIT 1", (eid,)).fetchone()
    no = conn.execute("SELECT doc_no FROM journal_entries WHERE id=?",
                      (eid,)).fetchone()
    no = (no["doc_no"] if no and no["doc_no"] else f"#{eid}")
    links = []
    if wo:
        links = [("🖼 صور الدفعة", f"/doc/supply_models/{wo['id']}"),
                 ("📄 فاتورة الوارد", f"/doc/work_orders/{wo['id']}")]
    return {"ok": True, "no": no, "id": eid, "links": links,
            "msg": f"رُحّلت دفعة التوريد {no} — {len(rows)} طقم"}


def _guarded(data, fn, kind, action="web_post", where="post_op"):
    """كل كتابةٍ من الرابط: nonce واحد = ترحيلٌ واحد، وقفلٌ يُرتّبها،
    ومعاملةٌ ذرّية، والتسجيل مسموحٌ من البرنامج — وإلا سببٌ مفهوم."""
    from database.database import db
    nonce = _txt(data.get("nonce"), 40)
    if len(nonce) < 8:
        return {"ok": False, "error": "حدّث الصفحة ثم أعد المحاولة"}
    with _post_lock:
        if nonce in _nonces:
            # الضغط مرتين أو إعادة الإرسال: الأول نفسه — لا ثانٍ
            return dict(_nonces[nonce], again=True)
        try:
            with db(readonly=True) as conn:
                if not ops_enabled(conn):
                    return {"ok": False, "error": "تسجيل العمليات من الرابط "
                                                  "موقوفٌ من البرنامج"}
            with db() as conn:
                if action != "web_post" and edits_locked(conn):
                    raise ValueError(EDIT_LOCKED_MSG)
                res = fn(conn)
                _audit(conn, kind, res, action)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:                   # noqa: BLE001
            try:
                from services.health import log_error
                log_error(f"manager_web/{where}", e)
            except Exception:
                pass
            return {"ok": False, "error": "تعذّر الحفظ — خطأٌ في البرنامج "
                                          f"على جهاز المصنع ({type(e).__name__})"}
        _nonces[nonce] = res
        while len(_nonces) > _NONCE_CAP:
            _nonces.popitem(last=False)
    if res.get("cancel_invoice"):
        try:
            from models import doc_delete
            doc_delete._announce_cancel(res["cancel_invoice"])
        except Exception:
            pass
    return res


def post_op(kind, data):
    """يرحّل عمليةً من الرابط — أو {"ok": False, "error"} بسببٍ مفهوم."""
    if kind not in dict((k, t) for k, t, _s in OPS):
        return {"ok": False, "error": "عمليةٌ غير معروفة"}

    def run(conn):
        if kind in ("sale", "sale_return"):
            return _post_invoice(conn, kind, data)
        if kind in ("receipt", "payment"):
            return _post_voucher(conn, kind, data)
        if kind == "journal":
            return _post_journal(conn, data)
        return _post_supply(conn, data)
    return _guarded(data, run, kind)


# ══════════════════════════════════════════════════════════════════
#  التعديل والحذف والدمج من الرابط (5.7.0)
# ------------------------------------------------------------------
#  بدوالّ البرنامج نفسها: الفاتورة والسند يُعدَّلان **في مكانهما** برقمهما
#  (`update_invoice` · `update_voucher`)، والقيد اليومي برقمه
#  (`editing.repost_manual`). والحذف `models.doc_delete` (يعكس القيد
#  ويُحرِّر الرقم للمستند التالي)، والدمج `operations.merge_invoices`.
# ══════════════════════════════════════════════════════════════════

EDIT_KINDS = ("sale", "sale_return", "receipt", "payment", "journal")


def _doc_for_edit(conn, kind, eid):
    from models import doc_delete
    e, d = doc_delete._doc(conn, eid)
    want = "manual" if kind == "journal" else kind
    if d["deleted"] or d["kind"] != want:
        raise ValueError("المستند غير موجود أو تغيّر — حدّث الصفحة")
    from models import fiscal
    fiscal.assert_open(conn, e["entry_date"])
    return e, d


def edit_payload(conn, kind, eid):
    """خانات المستند لتعبئة نموذجه عند التعديل — كما هي في دفاتره."""
    from services import karat_view as kv
    if kind not in EDIT_KINDS:
        raise ValueError("هذه العملية لا تُعدَّل من الرابط — عدّلها من البرنامج")
    e, d = _doc_for_edit(conn, kind, eid)
    k = int(kv.active())
    out = {"eid": e["id"], "no": d["no"], "label": _KIND_LABEL.get(
        d["kind"], ""), "date": e["entry_date"]}

    def party(pid):
        r = conn.execute("SELECT id, name, entity_type FROM entities WHERE"
                         " id=?", (pid,)).fetchone()
        return ({"id": r["id"], "label": r["name"],
                 "sub": _type_label(r["entity_type"])} if r else None)
    if kind in ("sale", "sale_return"):
        inv = conn.execute("SELECT * FROM invoices WHERE id=?",
                           (d["rec_id"],)).fetchone()
        lines = []
        for it in conn.execute(
                "SELECT it.*, w.work_order_no no, w.model_no model,"
                " COALESCE(w.is_bulk,0) bulk, COALESCE(w.is_service,0) svc"
                " FROM invoice_items it JOIN work_orders w"
                " ON w.id=it.work_order_id WHERE it.invoice_id=?"
                " ORDER BY it.id", (inv["id"],)):
            if it["svc"]:
                lines.append({"wage_only": True,
                              "amount": float(it["wages"] or 0),
                              "note": it["line_note"] or ""})
                continue
            lk = int(it["karat"] or k) or k
            r18 = float(it["wage_per_gram"] or 0)
            lines.append({"no": it["no"], "id": it["work_order_id"],
                          "model": (it["model"] or "").strip()
                          or ("ايطالي" if it["bulk"] else ""),
                          "weight": kv.g(float(it["registered_weight"] or 0),
                                         lk),
                          "karat": lk, "wage": kv.rate(r18, lk),
                          "diamond": float(it["diamond"] or 0),
                          "bulk": bool(it["bulk"])})
        out.update(party=party(inv["customer_id"]),
                   src=inv["source_account_id"],
                   scrap_karat=int(inv["scrap_karat"] or 0) or None,
                   date=inv["invoice_date"], vat=bool(inv["vat_applied"]),
                   notes=inv["description"] or "", lines=lines,
                   inv=inv["id"])
    elif kind in ("receipt", "payment"):
        v = conn.execute("SELECT * FROM vouchers WHERE id=?",
                         (d["rec_id"],)).fetchone()
        if abs(float(v["net_diff"] or 0)) > 1e-9 or abs(
                float(v["disc_cash"] or 0)) > 1e-9 or abs(
                float(v["disc_gold"] or 0)) > 1e-9:
            raise ValueError("في هذا السند خصمٌ أو فرق — عدّله من البرنامج")
        from models import vouchers
        rows = []
        for r in vouchers.voucher_lines(conn, v["id"]):
            if r["line_kind"] == "gold":
                rows.append({"kind": "gold", "weight": float(r["gold_weight"]),
                             "karat": int(r["gold_karat"] or 18),
                             "notes": r["line_notes"] or ""})
            else:
                rows.append({"kind": "cash",
                             "amount": float(r["cash_amount"] or 0),
                             "notes": r["line_notes"] or ""})
        acc = None
        if not v["customer_id"]:
            a = conn.execute("SELECT id, code, name FROM accounts WHERE id=?",
                             (v["target_account_id"],)).fetchone()
            acc = ({"id": a["id"], "label": a["name"], "sub": a["code"]}
                   if a else None)
        out.update(party=party(v["customer_id"]) if v["customer_id"]
                   else None, acc=acc,
                   box=v["cash_account_code"] or "1400",
                   date=v["voucher_date"], notes=v["notes"] or "", rows=rows)
    else:
        lines = []
        for r in conn.execute(
                "SELECT l.*, a.code, a.name FROM journal_lines l JOIN"
                " accounts a ON a.id=l.account_id WHERE l.entry_id=?"
                " ORDER BY l.id", (e["id"],)):
            lines.append({"account": r["account_id"],
                          "label": f"{r['name']} ({r['code']})",
                          "gd": kv.g(float(r["gold_debit"] or 0)),
                          "gc": kv.g(float(r["gold_credit"] or 0)),
                          "cd": float(r["cash_debit"] or 0),
                          "cc": float(r["cash_credit"] or 0),
                          "note": r["line_desc"] or ""})
        out.update(notes=(e["user_note"] or e["description"] or ""),
                   lines=lines)
    return out


_KIND_LABEL = {"sale": "فاتورة المبيعات", "sale_return": "فاتورة المرتجع",
               "receipt": "سند القبض", "payment": "سند الصرف",
               "manual": "القيد اليومي", "fixing": "التسكير"}


def _edit_invoice(conn, kind, eid, data):
    from models import invoices
    _e0, d = _doc_for_edit(conn, kind, eid)
    orig = {r["work_order_id"]: (float(r["registered_weight"] or 0),
                                 float(r["wage_per_gram"])
                                 if r["wage_per_gram"] is not None else None)
            for r in conn.execute(
                "SELECT work_order_id, registered_weight, wage_per_gram"
                " FROM invoice_items WHERE invoice_id=?", (d["rec_id"],))}
    pid, ent, src, karat, date, vat, desc, cart = _invoice_input(
        conn, kind, data, orig)
    res = invoices.update_invoice(
        conn, d["rec_id"], cart, WEB_USER, apply_vat=vat, description=desc,
        invoice_date=date, source_account_id=src, scrap_karat=karat,
        entity_id=pid)
    label = _KIND_LABEL[kind]
    return {"ok": True, "no": res["invoice_no"], "id": res["id"],
            "links": _inv_links([res]), "edited": True,
            "msg": f"عُدّلت {label} {res['invoice_no']} في مكانها — "
                   f"«{ent['name']}»"}


def _edit_voucher(conn, kind, eid, data):
    from models import vouchers
    _e0, d = _doc_for_edit(conn, kind, eid)
    v = conn.execute("SELECT * FROM vouchers WHERE id=?",
                     (d["rec_id"],)).fetchone()
    if abs(float(v["net_diff"] or 0)) > 1e-9 or abs(
            float(v["disc_cash"] or 0)) > 1e-9 or abs(
            float(v["disc_gold"] or 0)) > 1e-9:
        raise ValueError("في هذا السند خصمٌ أو فرق — عدّله من البرنامج")
    pid, aid, target, box, rows = _voucher_input(conn, data)
    res = vouchers.update_voucher(
        conn, d["rec_id"], WEB_USER, kind=kind, entity_id=pid,
        account_id=aid, rows=rows, cash_account_code=box,
        notes=_txt(data.get("notes"), 300),
        voucher_date=_post_date(data.get("date")))
    label = _KIND_LABEL[kind]
    return {"ok": True, "no": res["voucher_no"], "id": res["id"],
            "edited": True,
            "links": [(f"📄 {label} {res['voucher_no']}",
                       f"/doc/vouchers/{res['id']}")],
            "msg": f"عُدّل {label} {res['voucher_no']} في مكانه — {target}"}


def _edit_journal(conn, eid, data):
    from models import editing
    e0, d = _doc_for_edit(conn, "journal", eid)
    desc, lines = _journal_input(conn, data)
    new = editing.repost_manual(conn, e0["id"], _post_date(data.get("date")),
                                desc, lines, WEB_USER)
    no = conn.execute("SELECT doc_no FROM journal_entries WHERE id=?",
                      (new,)).fetchone()["doc_no"] or f"#{new}"
    return {"ok": True, "no": no, "id": new, "edited": True,
            "links": [(f"📄 القيد {no}", f"/doc/manual/{new}")],
            "msg": f"عُدّل القيد {no} برقمه — {desc}"}


def edit_op(kind, eid, data):
    """يحفظ تعديل مستندٍ من الرابط — في مكانه وبرقمه."""
    if kind not in EDIT_KINDS:
        return {"ok": False, "error": "هذه العملية لا تُعدَّل من الرابط"}

    def run(conn):
        if kind in ("sale", "sale_return"):
            return _edit_invoice(conn, kind, eid, data)
        if kind in ("receipt", "payment"):
            return _edit_voucher(conn, kind, eid, data)
        return _edit_journal(conn, eid, data)
    return _guarded(data, run, kind, "web_edit", "edit_op")


def delete_op(data):
    """حذف مستندٍ وعكس قيده من الرابط (وتحرير رقمه) — والفاتورة الضريبية
    تُعكس بمرتجع بدل الحذف."""
    from models import doc_delete
    try:
        eid = int(data.get("eid"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "مستندٌ غير معروف"}

    def run(conn):
        d = doc_delete.describe(conn, eid)
        if d.get("can_delete"):
            res = doc_delete.delete(conn, eid, WEB_USER, "من رابط المدير")
            if res["src"] == "invoices":
                res["cancel_invoice"] = res["sid"]
            res["id"] = eid
            return res
        if d.get("can_reverse") and data.get("reverse"):
            res = doc_delete.reverse_vat(conn, eid, WEB_USER)
            res["id"] = eid
            return res
        raise ValueError(d.get("why") or "لا يُحذف هذا المستند")
    return _guarded(data, run, "delete", "web_delete", "delete_op")


def merge_op(data):
    """دمج فواتير الجهة في الأولى منها — والأخرى تُلغى ويتحرّر رقمها."""
    from models import operations
    ids = data.get("ids")
    if not isinstance(ids, list) or not 2 <= len(ids) <= 40:
        return {"ok": False, "error": "اختر فاتورتين أو أكثر للدمج"}
    try:
        ids = [int(i) for i in ids]
    except (TypeError, ValueError):
        return {"ok": False, "error": "فاتورةٌ غير معروفة"}

    def run(conn):
        r = operations.merge_invoices(conn, ids, WEB_USER,
                                      notes="من رابط المدير")
        return {"ok": True, "no": r["invoice_no"], "id": r["id"],
                "links": _inv_links([{"id": r["id"],
                                      "invoice_no": r["invoice_no"]}]),
                "msg": f"دُمجت {'، '.join(r['merged'])} في الفاتورة "
                       f"{r['invoice_no']} ({r['items']} بنداً) — وأرقام "
                       "المدموجة حُرِّرت للفواتير التالية"}
    return _guarded(data, run, "merge", "web_merge", "merge_op")


def _audit(conn, kind, res, action="web_post"):
    try:
        from services.audit import log_action
    except Exception:
        try:
            from models.audit import log_action
        except Exception:
            return
    try:
        log_action(conn, WEB_USER, action, kind, res.get("id"),
                   f"من رابط المدير: {res.get('msg', '')}")
    except Exception:
        pass
