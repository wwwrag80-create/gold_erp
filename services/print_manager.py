# -*- coding: utf-8 -*-
"""محرك الطباعة والتقارير (Print & Report Engine).

وحدة مستقلة تستقبل **نوع المستند ورقمه** فقط، فتجلب بياناته من قاعدة
البيانات، وتدمجها مع قالب HTML/CSS مناسب، ثم تصيّرها عبر
`QTextDocument` لتعرضها في `QPrintPreviewDialog` أو ترسلها إلى
`QPrinter` (طابعة أو ملف PDF).

الاستخدام من أي شاشة:

    from services.print_manager import preview_document, export_pdf
    preview_document(self, "invoice", invoice_id)
    export_pdf("voucher", voucher_id, "/path/out.pdf")

كل المستندات تشترك في هوية موحّدة: ترويسة المنشأة، جسم المستند،
تذييل التوقيعات — ويُبنى المستند القديم من قاعدة البيانات تماماً كما
صدر أول مرة.
"""
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtPrintSupport, QtWidgets

import config
from models.inventory import is_bulk_no
from database.database import db
from models import melting

def _qd(qdate):
    """نص تاريخ بأرقام إنجليزية دائماً (انظر ui.widgets.common.qdstr)."""
    from services.dates import normalize_digits
    return normalize_digits(qdate.toString("yyyy-MM-dd"))


def _qd_w(w):
    return _qd(w.date())

# ══════════════════════ التفقيط (الرقم بالحروف) ══════════════════════
_ONES = ["", "واحد", "اثنان", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة",
         "ثمانية", "تسعة", "عشرة", "أحد عشر", "اثنا عشر", "ثلاثة عشر",
         "أربعة عشر", "خمسة عشر", "ستة عشر", "سبعة عشر", "ثمانية عشر",
         "تسعة عشر"]
_TENS = ["", "", "عشرون", "ثلاثون", "أربعون", "خمسون", "ستون", "سبعون",
         "ثمانون", "تسعون"]
_HUNDREDS = ["", "مائة", "مائتان", "ثلاثمائة", "أربعمائة", "خمسمائة",
             "ستمائة", "سبعمائة", "ثمانمائة", "تسعمائة"]


def _under_thousand(n):
    parts = []
    if n >= 100:
        parts.append(_HUNDREDS[n // 100])
        n %= 100
    if n >= 20:
        u, t = n % 10, n // 10
        parts.append(f"{_ONES[u]} و{_TENS[t]}" if u else _TENS[t])
    elif n:
        parts.append(_ONES[n])
    return " و".join(p for p in parts if p)


def tafqeet(amount, currency="ريال", fraction="هللة"):
    """تفقيط المبالغ بالعربية — يُطبع أسفل السندات والفواتير."""
    try:
        amount = round(float(amount), 2)
    except (TypeError, ValueError):
        return ""
    neg = amount < 0
    amount = abs(amount)
    whole = int(amount)
    frac = int(round((amount - whole) * 100))
    if whole == 0:
        words = "صفر"
    else:
        groups = [(1_000_000_000, "مليار", "ملياران", "مليارات"),
                  (1_000_000, "مليون", "مليونان", "ملايين"),
                  (1_000, "ألف", "ألفان", "آلاف")]
        chunks, rest = [], whole
        for size, one, two, many in groups:
            q, rest = divmod(rest, size)
            if not q:
                continue
            if q == 1:
                chunks.append(one)
            elif q == 2:
                chunks.append(two)
            elif q <= 10:
                chunks.append(f"{_under_thousand(q)} {many}")
            else:
                chunks.append(f"{_under_thousand(q)} {one}")
        if rest:
            chunks.append(_under_thousand(rest))
        words = " و".join(chunks)
    out = f"{words} {currency}"
    if frac:
        out += f" و{_under_thousand(frac)} {fraction}"
    return ("سالب " if neg else "") + out + " لا غير"


# ══════════════════════ القالب الرئيسي الموحّد ══════════════════════
BASE_CSS = """
<style>
  /* ══ محرك Qt يطبّق عرض الجداول من CSS لا من خاصية width ══ */
  html, body { direction: rtl; text-align: right;
               margin: 0; padding: 0; width: 100%; height: 100%;
               max-width: none; }
  body { font-family: @FAMILY@;
         font-size: 10.5pt; line-height: 133%; color: #1a1a1a; }
  div.doc { width: 100%; height: 100%; margin: 0; padding: 0;
             max-width: none; }

  /* الإطار الخارجي يمتد بعرض الورقة كاملاً */
  table.frame { width: 100%; height: 100%; border-collapse: collapse;
                border: 1.5px solid #333; margin: 0; }
  table.frame td.framecell { border: 1.5px solid #333; padding: 10px;
                width: 100%; vertical-align: top; }

  /* ── الجداول: عرض كامل إجباري وبلا حد أقصى ── */
  table.items { width: 100%; border-collapse: collapse; font-size: 10pt;
                margin: 6px 0; }
  table.items th, table.items td {
                border: 1px solid #999; padding: 5px 4px;
                text-align: center; vertical-align: middle; }
  table.items th { background-color: #F1ECE0; font-weight: bold;
                   white-space: nowrap; }   /* لا تُكسر العناوين لسطرين */
  table.items td.nw { white-space: nowrap; }
  table.items td.r  { text-align: right; }
  table.items tr.total td { background-color: #F3EBD3; font-weight: bold; }

  /* جدول تخطيط بلا حدود (للترويسة والصفوف الجانبية) */
  table.plain { width: 100%; border-collapse: collapse; margin: 0; }
  table.plain td { padding: 2px; vertical-align: top; }

  /* عنوان المستند: شريط ممتد بعرض الصفحة */
  table.titlebar { width: 100%; border-collapse: collapse; margin: 6px 0; }
  table.titlebar td { border: 1px solid #999; background-color: #F1ECE0;
                      text-align: center; font-size: 14pt;
                      font-weight: bold; padding: 7px; white-space: nowrap; }

  /* الترويسة */
  table.lh { width: 100%; border-collapse: collapse;
             border-bottom: 2px solid #999; margin: 0; }
  table.lh td { padding: 4px; vertical-align: middle; }
  .co    { font-size: 13pt; font-weight: bold; white-space: nowrap; }
  .co-sub{ font-size: 9pt; white-space: nowrap; }

  /* مربعا الذهب والنقد */
  table.boxes { width: 100%; border-collapse: collapse; margin: 6px 0; }
  table.boxes td { border: 1px solid #999; padding: 5px;
                   text-align: center; white-space: nowrap; }
  table.boxes td.lbl { background-color: #EFEFEF; font-weight: bold; }
  table.boxes td.val { font-size: 12pt; font-weight: bold; }

  /* سطر عريض */
  table.wide { width: 100%; border-collapse: collapse; margin: 6px 0; }
  table.wide td { border: 1px solid #999; padding: 7px; }
  table.wide td.lbl { background-color: #EFEFEF; font-weight: bold;
                      text-align: center; white-space: nowrap; }
  table.wide td.val { text-align: right; font-weight: bold; }

  /* التوقيعات */
  table.sig { width: 100%; border-collapse: collapse; margin-top: 22px; }
  table.sig td { text-align: center; padding: 6px; white-space: nowrap; }

  /* الأرقام تُعزل اتجاهياً بلا override — الـoverride يقلب حروف
     أي نص عربي يقع في الخلية (نقد ← دقن) */
  .num  { unicode-bidi: isolate; }

  /* صف الإجماليات البارز أسفل كشف الأرصدة */
  table.totals th, table.totals td { background: #F2EEE4; font-size: 9pt; }
  table.totals td b { font-size: 10pt; }

  /* جداول قسم التصنيع: كل الأعمدة في صفحة واحدة */
  table.compact { table-layout: fixed; width: 100%; font-size: 8pt; }
  table.compact th, table.compact td {
      padding: 2px 2px; font-size: 8pt; white-space: nowrap;
      overflow: hidden; text-overflow: clip; word-break: keep-all; }
  table.compact th { font-weight: bold; }
  .note { font-size: 9pt; color: #555; }

  /* لوحات تحليل المبيعات */
  table.ca-wrap { width: 100%; border-collapse: separate;
                  border-spacing: 5px 0; }
  .ca-head { width: 25%; border: 2px solid #2b2723; padding: 8px 4px;
             text-align: center; vertical-align: middle; }
  .ca-title { font-size: 9.5pt; white-space: nowrap; }
  .ca-value { font-size: 14pt; font-weight: bold; padding-top: 3px; }
  .ca-detail { width: 25%; vertical-align: top; }
  table.ca-tbl { width: 100%; border-collapse: collapse; font-size: 8.5pt; }
  table.ca-tbl th { background-color: #EFEFEF; border: 1px solid #999;
                    padding: 3px; font-weight: bold; text-align: center;
                    white-space: nowrap; }
  table.ca-tbl td { border: 1px solid #999; padding: 3px;
                    text-align: center; }
  table.ca-tbl tr.total td { background-color: #EFEFEF; font-weight: bold; }

  /* جدولا الرصيد الصغيران أعلى لوحات التحليل (ذهب · نقد) */
  table.ca-bal { border-collapse: collapse; font-size: 9pt; }
  table.ca-bal th { background-color: #EFEFEF; border: 1px solid #777;
                    padding: 3px; font-weight: bold; text-align: center;
                    white-space: nowrap; }
  table.ca-bal td { border: 1px solid #777; padding: 3px;
                    text-align: center; white-space: nowrap; }
</style>
"""


# ══════════════════════════════════════════════════════════════════
# ثوابت التنسيق المضمّن (inline)
# ------------------------------------------------------------------
# محرك الطباعة في Qt (QTextDocument) يدعم مجموعة محدودة جداً من CSS
# ويتجاهل !important (فيُسقط القاعدة كاملةً) و table-layout. لذلك يُبنى
# كل جدول بخصائص HTML صريحة (width/border/cellpadding/align) مع أنماط
# inline — وهو ما كان يعمل في النسخ القديمة الناجحة.
# ══════════════════════════════════════════════════════════════════

# عند التوليد لمحرك المتصفح يُضبط هذا إلى True لأن المتصفح يطبّق RTL
# بشكل صحيح، فلا حاجة لعكس الأعمدة فيزيائياً.
RTL_ORDER_OVERRIDE = None


def cells(*items):
    """يرتّب خلايا الصف بحسب قدرة محرك الطباعة على تطبيق RTL.

    تُمرَّر الخلايا بالترتيب **الطبيعي من اليمين لليسار** (أي أول عنصر
    هو العمود الذي يجب أن يظهر أقصى اليمين). فإن كان المحرك لا يطبّق
    RTL (config.PRINT_RTL_ENGINE = False) عُكس الترتيب فيزيائياً ليخرج
    المستند صحيحاً على أي محرك.
    """
    seq = list(items)
    rtl_ok = (RTL_ORDER_OVERRIDE if RTL_ORDER_OVERRIDE is not None
              else getattr(config, "PRINT_RTL_ENGINE", False))
    if not rtl_ok:
        seq.reverse()
    return "".join(seq)


# جدول بيانات: العرض الكامل يأتي من CSS (محرك Qt يطبّقه من هناك فقط)
TBL = '<table class="items" width="100%" cellspacing="0" cellpadding="4">'
TBL_PLAIN = '<table class="plain" width="100%" cellspacing="0" cellpadding="0">'

# خلايا الرأس والبيانات — بلا عرض ثابت فتتمدد حسب المحتوى بانتظام
TH = 'class="nw"'
TD = ''
TD_R = 'class="r"'
TD_TOT = 'class="nw"'
WIDE = 'class="note"'


def thw(label, pct=None):
    """خلية رأس. العرض يُترك للمحرك ليوزّعه بانتظام، مع منع كسر
    العنوان إلى سطرين (white-space: nowrap من CSS)."""
    return f'<th>{label}</th>'


def thspan(label, colspan=1, rowspan=1, align="center"):
    """خلية رأس تمتدّ على عدة أعمدة أو صفوف.

    تلزم للرؤوس ذات الطابقين: طابقٌ يجمع أعمدة الذهب تحت عنوان واحد
    وأعمدة الأجور تحت آخر، وطابقٌ تحته بالفئات العمرية. فيعرف
    القارئ أيّ وحدةٍ يقرأ قبل أن يقرأ الرقم.
    """
    a = ' class="r"' if align == "right" else ""
    cs = f' colspan="{colspan}"' if colspan > 1 else ""
    rs = f' rowspan="{rowspan}"' if rowspan > 1 else ""
    return f'<th{a}{cs}{rs}>{label}</th>'


def tdw(value, pct=None, align="center"):
    """خلية بيانات؛ align='right' لعمود البيان."""
    cls = ' class="r"' if align == "right" else ""
    return f'<td{cls}>{value}</td>'


def _logo_tag(height=None):
    """وسم صورة الشعار (يُتجاهل بأمان إن لم يوجد الملف).

    الشعار والمقاس من «هوية المصنع» — لكل مصنعٍ شعاره.
    """
    path = getattr(config, "LOGO_PATH", None)
    h = int(height or getattr(config, "LOGO_HEIGHT", 120) or 120)
    if path and Path(str(path)).exists():
        return f'<img src="{Path(str(path)).as_uri()}" height="{h}">'
    return ""


def _id_lines(lang="ar", align=None):
    """أسطر الهوية تحت الاسم: البلد · العنوان · السجل · (الضريبي) · الاتصال."""
    if lang == "en":
        rows = [config.COMPANY_COUNTRY_EN, config.COMPANY_ADDRESS_EN,
                f"C.R: {en(config.COMPANY_CR)}" if config.COMPANY_CR else ""]
        if getattr(config, "HEADER_SHOW_VAT", False) and \
                getattr(config, "COMPANY_VAT_NUMBER", ""):
            rows.append(f"VAT: {en(config.COMPANY_VAT_NUMBER)}")
    else:
        rows = [config.COMPANY_COUNTRY, config.COMPANY_ADDRESS,
                f"سجل تجاري: {en(config.COMPANY_CR)}"
                if config.COMPANY_CR else ""]
        if getattr(config, "HEADER_SHOW_VAT", False) and \
                getattr(config, "COMPANY_VAT_NUMBER", ""):
            rows.append(f"الرقم الضريبي: {en(config.COMPANY_VAT_NUMBER)}")
        contact = "  ·  ".join(
            x for x in (
                f"هاتف: {en(config.COMPANY_PHONE)}"
                if getattr(config, "COMPANY_PHONE", "") else "",
                en(getattr(config, "COMPANY_EMAIL", "") or ""))
            if x)
        rows.append(contact)
    # `align` صفةً لا `text-align` في CSS: محرك Qt يعكس الثانية داخل
    # النص العربي (فيقع يساراً) ويحترم الأولى في المحرّكين معاً.
    a = align or ("left" if lang == "en" else "right")
    return "".join(f'<div align="{a}" style="font-size:9.5pt;">{r}</div>'
                   for r in rows if r)


def letterhead():
    """ترويسة المصنع وحدها — بحسب ترتيب «هوية المصنع».

    * `logo_left`: الاسم وتحته البلد والعنوان والسجل يميناً، والشعار يساراً.
    * `logo_right`: الشعار يميناً والبيانات يساراً.
    * `classic`: عربي يميناً · الشعار في الوسط · إنجليزي يساراً.
    """
    layout = getattr(config, "HEADER_LAYOUT", "classic")
    name_en = (config.COMPANY_NAME_EN
               if getattr(config, "HEADER_SHOW_EN", True) else "")
    logo = _logo_tag()
    if layout in ("logo_left", "logo_right"):
        a = "right" if layout == "logo_left" else "left"
        sub_en = (f'<div align="{a}" style="font-size:10pt;color:#555;">'
                  f'{name_en}</div>' if name_en else "")
        info = (f'<td width="62%" align="{a}" style="width:62%;'
                f' vertical-align:middle;">'
                f'<div align="{a}" style="font-size:16pt; font-weight:bold;">'
                f'{config.COMPANY_NAME}</div>{sub_en}{_id_lines("ar", a)}'
                f'</td>')
        lside = "left" if layout == "logo_left" else "right"
        logo_cell = (f'<td width="38%" align="{lside}" style="width:38%;'
                     f' vertical-align:middle;">'
                     f'<div align="{lside}">{logo}</div></td>')
        row = (cells(info, logo_cell) if layout == "logo_left"
               else cells(logo_cell, info))
    else:
        ar_cell = (f'<td width="35%" align="right" style="width:35%;">'
                   f'<div align="right" style="font-size:14pt;'
                   f' font-weight:bold;">{config.COMPANY_NAME}</div>'
                   f'{_id_lines()}</td>')
        logo_cell = (f'<td width="30%" align="center" style="width:30%;">'
                     f'<div align="center">{logo}</div></td>')
        en_cell = (f'<td width="35%" align="left" style="width:35%;">'
                   f'<div align="left" style="font-size:14pt;'
                   f' font-weight:bold;">{name_en}</div>'
                   f'{_id_lines("en") if name_en else ""}</td>')
        row = cells(ar_cell, logo_cell, en_cell)
    return (f'<table class="lh" width="100%" cellspacing="0" cellpadding="4">'
            f'<tr>{row}</tr></table>')


def _header(doc_type, doc_no, date, extra="", show_meta=True):
    """الترويسة الموحدة بخصائص HTML صريحة (يدعمها محرك Qt للطباعة):
    ترويسة المصنع (`letterhead`) · خط فاصل · عنوان المستند في مربع
    ممتد بعرض الصفحة بخلفية رمادية فاتحة.
    """
    meta = ""
    if show_meta:
        meta = f'''
    {TBL_PLAIN}<tr>
      <td width="55%"></td>
      <td width="45%">
        {TBL}
          <tr><th>رقم المستند</th>
              <td>{en(doc_no)}</td></tr>
          <tr><th>التاريخ</th><td>{en(date)}</td></tr>
        </table>{extra}
      </td>
    </tr></table>'''
    return f"""
    {letterhead()}
    <table class="titlebar" width="100%" cellspacing="0" cellpadding="6"><tr><td width="100%">{doc_type}</td></tr></table>{meta}
    """


def _footer(notes=""):
    """تذييل نظيف: سطر ملاحظات اختياري + سطر توقيع واحد على اليسار.
    لا توقيعات متعددة ولا نصوص برمجية سفلية."""
    note_html = (f'<div class="note">ملاحظات: {notes}</div>'
                 if notes else "")
    stamp = getattr(config, "STAMP_PATH", None)
    stamp_img = (f'<img src="{Path(str(stamp)).as_uri()}" height="90"'
                 f' style="vertical-align:middle">'
                 if stamp and Path(str(stamp)).exists() else "")
    return f"""
    <br/>{note_html}
    <div style="text-align:left; padding-top:22px; font-size:10.5pt">
      {stamp_img} التوقيع: .............................
    </div>
    """


AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,")


def en(v):
    """يفرض الأرقام الإنجليزية (0-9) ويلغي الأرقام الهندية تماماً."""
    return str(v).translate(AR_DIGITS)


def _rows(rows, date_col=None):
    """يبني صفوف الجدول مع تظليل الصفوف الفردية.

    `date_col` رقم عمود التاريخ ليأخذ صنف .dt (عرض 15% بلا كسر أسطر).
    """
    out = []
    for i, r in enumerate(rows):
        cls = ' class="alt"' if i % 2 else ""
        tds = "".join(
            f'<td class="{"dt" if date_col == j else "num"}">{en(c)}</td>'
            for j, c in enumerate(r))
        out.append(f"<tr{cls}>{tds}</tr>")
    return "".join(out)


def _w(v, d=2):
    """تنسيق رقمي موحّد بأرقام إنجليزية دائماً — منزلتان عشريتان
    في كل مستندات النظام."""
    try:
        return en(f"{float(v):,.{d}f}")
    except (TypeError, ValueError):
        return "—"


def _gw(v, d=2):
    """وزن مخزَّن بمكافئ 18 ← مطبوعاً بعيار المصنع.

    الورقة تخرج بنفس عيار الشاشة — وإلا قرأ العميل رقماً وقرأ
    المحاسب آخر للحركة نفسها.
    """
    from services import karat_view
    return _w(karat_view.g(v), d)


def _kunit():
    from services import karat_view
    return karat_view.unit()


def _karat_kw(kw):
    """عيار الطباعة: ما مرّرته الشاشة، وإلا عيار المصنع الفعّال."""
    from services import karat_view
    return int(kw.get("karat") or karat_view.active())


def _kactive():
    from services import karat_view
    return karat_view.active()


def _krate(v):
    """أجر الجرام بعيار المصنع — يتحرك عكس الوزن ليبقى حاصلهما ثابتاً."""
    from services import karat_view
    return karat_view.rate(v)


# ══════════════════════ قوالب المستندات ══════════════════════
def _tpl_invoice(conn, invoice_id):
    """فاتورة المبيعات/المرتجعات — الأعمدة تطابق شاشة إدخال الطقم حرفياً:
    م · رقم التشغيل · الوزن القائم · وزن الفصوص · وزن الأحجار ·
    الأحجار بعد الخصم · الوزن الصافي · الأجر · الإجمالي.
    """
    from models import invoices
    from services.accounting_engine import account_balance
    inv, items = invoices.get_invoice_full(conn, invoice_id)
    if not inv:
        raise ValueError("الفاتورة غير موجودة")
    cust = conn.execute("SELECT * FROM entities WHERE id=?",
                        (inv["customer_id"],)).fetchone()
    kind = "المبيعات" if inv["kind"] == "sale" else "المرتجعات"
    # ══ الفاتورة الإلكترونية (المرحلة الثانية) ══
    # ما صدر له مستندٌ إلكتروني يُطبع بالعنوان الذي يشترطه نظام الفوترة
    # («فاتورة ضريبية» · «فاتورة ضريبية مبسطة» · «إشعار دائن») ومعه
    # رمز QR الموقّع والرقمان الضريبيان — لا بعنوان «المبيعات» العام.
    edoc = None
    try:
        from services.fatoora import ledger as _ft
        edoc = _ft.doc_for(conn, "invoices", invoice_id)
    except Exception:
        edoc = None
    if edoc is not None:
        kind = {("invoice", "standard"): "فاتورة ضريبية",
                ("invoice", "simplified"): "فاتورة ضريبية مبسطة",
                ("credit", "standard"): "إشعار دائن",
                ("credit", "simplified"): "إشعار دائن",
                ("debit", "standard"): "إشعار مدين",
                ("debit", "simplified"): "إشعار مدين"}.get(
                    (edoc["kind"], edoc["subtype"]), kind)

    # الأعمدة تطابق شاشة المبيعات تماماً، والجدول يبدأ من اليمين:
    # رقم التشغيل ← الذهب ← الفصوص ← الأحجار ← الأحجار بعد الخصم ←
    # الوزن المقيد ← الذهب القائم ← الأجر ← الإجمالي
    # الترتيب المعتمد من اليمين لليسار: رقم التشغيل · الوزن المقيد ·
    # الوزن القائم · الذهب · الفصوص · الأحجار · الأحجار بعد الخصم ·
    # الأجر · الأجور
    body_rows = ""
    t_reg = t_standing = t_gold = t_small = t_big = t_after = 0.0
    for it in items:
        wo = conn.execute("SELECT * FROM work_orders WHERE id=?",
                          (it["work_order_id"],)).fetchone()
        gold = (wo["gold_weight"] if wo else 0) or 0
        small = (wo["small_stones"] if wo else 0) or 0
        big = (wo["big_stones"] if wo else 0) or 0
        after = (wo["stones_after_discount"] if wo else 0) or 0
        standing = (wo["standing_gold"] if wo else 0) or 0
        reg = it["registered_weight"]
        # الرقم التجميعي سجلٌّ واحد يحمل **الرصيد الكلي**، فطباعة
        # أعمدته كما هي تُظهر كل الرصيد بدل الوزن المُدخل في السطر.
        # لذلك نعرض وزن السطر نفسه: القائم = المقيد والذهب = المقيد.
        if wo and (wo["is_bulk"] or is_bulk_no(wo["work_order_no"])):
            standing = reg
            gold = reg
            small = big = after = 0.0
        t_reg += reg
        t_standing += standing
        t_gold += gold
        t_small += small
        t_big += big
        t_after += after
        _mn = ((wo["model_no"] if wo and "model_no" in wo.keys() else "")
               or "—")
        body_rows += "<tr>" + cells(
            tdw(en(_mn)),
            tdw(en(wo["work_order_no"] if wo else "—")),
            tdw(_gw(reg)), tdw(_gw(standing)), tdw(_gw(gold)),
            tdw(_gw(small)), tdw(_gw(big)), tdw(_gw(after)),
            tdw(_w(_krate(it["wage_per_gram"]), 2)),
            tdw(_w(it["wages"], 2))) + "</tr>"
    if not body_rows:
        body_rows = f'<tr><td {TD} colspan="9">لا توجد أصناف</td></tr>'

    gold_bal = cash_bal = 0.0
    if cust:
        gold_bal, cash_bal = account_balance(conn, cust["account_id"])

    # نسب الأعمدة (المجموع 100%) تُجبر الجدول على ملء عرض الورقة
    W = (11, 12, 11, 11, 12, 10, 10, 10, 13)
    _u = _kunit()
    head_cells = cells(
        thw("الموديل"),
        thw("رقم التشغيل"), thw(f"الوزن المقيد<br/>{_u}"),
        thw(f"الوزن القائم<br/>{_u}"),
        thw("الذهب"), thw("الفصوص"), thw("الأحجار"),
        thw("الأحجار بعد الخصم"), thw("الأجر"), thw("الأجور"))
    total_cells = cells(
        thw(""),
        thw("الإجمالي"), thw(_gw(t_reg)), thw(_gw(t_standing)),
        thw(_gw(t_gold)), thw(_gw(t_small)), thw(_gw(t_big)),
        thw(_gw(t_after)), thw("—"), thw(_w(inv["total_wages"], 2)))

    vat_block = ""
    if inv["vat_applied"]:
        vat_block = f'''
    {TBL}
      <tr><td {TH} width="70%">إجمالي الأجور قبل الضريبة</td>
          <td>{_w(inv['total_wages'], 2)}</td></tr>
      <tr><th>ضريبة القيمة المضافة (15%)</th>
          <td>{_w(inv['vat_amount'], 2)}</td></tr>
      <tr><td>الإجمالي شامل الضريبة</td>
          <td>{_w(inv['grand_total'], 2)}</td></tr>
    </table>'''

    # «من حساب» **لا يُطبع**: الفاتورة ورقةُ العميل، والمخزن الذي خرج
    # منه الذهب شأنٌ داخليٌّ للمصنع لا يعني العميل. يبقى في الشاشة وفي
    # القيد وكشف الحساب — ومن أراده فتح المستند لا الورقة.
    time_str = (inv["created_at"] or "")[11:19] or "—"
    # رمز QR لصور موديلات الفاتورة — يمين الورقة تحت عنوان المستند.
    # تحسين بصري بحت: تعذّره يعيد "" فتُطبع الفاتورة كما هي.
    from services import photo_qr
    qr_html = photo_qr.qr_for_invoice(conn, invoice_id, inv["invoice_no"])
    info = f'''
    {TBL_PLAIN}<tr>
      <td width="55%" valign="top" align="right"
          style="text-align:right;">{qr_html}</td>
      <td width="45%">
        {TBL}
          <tr><th>رقم الفاتورة</th>
              <td>{en(inv['invoice_no'])}</td></tr>
          <tr><th>التاريخ</th><td>{en(inv['invoice_date'])}</td></tr>
          <tr><th>الوقت</th><td>{en(time_str)}</td></tr>
        </table>
      </td>
    </tr></table>
    <table class="wide" width="100%" cellspacing="0" cellpadding="6">
      <tr><td {TH} width="18%">اسم العميل</td>
          <td style="text-align:right; border:1px solid #999; padding:6px;
                     font-weight:bold; font-size:12pt;">
            {cust['name'] if cust else '—'}</td></tr>
    </table>'''

    body = f'''{info}{_fatoora_block(conn, inv, cust, edoc)}
    {TBL}
      <tr>{head_cells}</tr>
      {body_rows}
      <tr>{total_cells}</tr>
    </table>
    {TBL}
      <tr><td {TH} width="70%">إجمالي الوزن (المقيد) — {_u}</td>
          <td>{_gw(t_reg)}</td></tr>
      <tr><th>إجمالي الأجور</th>
          <td>{_w(inv['total_wages'], 2)}</td></tr>
      <tr><th>إجمالي الذهب الكلي في حسابكم بعد الفاتورة</th>
          <td>{_gw(gold_bal)}</td></tr>
      <tr><th>إجمالي الأجور الكلي في حسابكم بعد الفاتورة</th>
          <td>{_w(cash_bal, 2)}</td></tr>
    </table>
    {vat_block}
    '''
    return (_header(kind, inv["invoice_no"], inv["invoice_date"],
                    show_meta=False) + body
            + _footer(inv["description"] or ""))


def _fatoora_block(conn, inv, cust, edoc):
    """رمز QR الموقّع والبيانات الضريبية — لمستندٍ إلكتروني صدر فقط."""
    if edoc is None:
        return ""
    try:
        from services import photo_qr
        from services.fatoora import ledger as _ft
        from services.fatoora import profile as _pf
        prof = _pf.load(conn)
        qr = edoc["cleared_qr"] or edoc["qr"]
        uri = photo_qr.qr_png_data_uri(qr, box_size=3, border=1)
        img = (f'<img src="{uri}" style="width:40mm; height:40mm;'
               f' max-height:none;" width="150" height="150"/>'
               if uri else '<div class="note">رمز QR</div>')
        rows = [("الرقم الضريبي للمنشأة", en(prof.get("vat", ""))),
                ("السجل التجاري", en(prof.get("crn", "")))]
        if edoc["subtype"] == "standard":
            b = _pf.buyer(conn, inv["customer_id"]) or {}
            rows += [("الرقم الضريبي للمشتري", en(b.get("vat", ""))),
                     ("عنوان المشتري", f"{en(b.get('building', ''))} "
                      f"{b.get('street', '')}، {b.get('district', '')}، "
                      f"{b.get('city', '')} {en(b.get('postal', ''))}")]
        if edoc["kind"] == "credit":
            import re
            refs = re.findall(r"<cac:InvoiceDocumentReference>\s*<cbc:ID>"
                              r"([^<]+)</cbc:ID>", edoc["xml"])
            if refs:
                rows.append(("إشعارٌ للفاتورة", en("، ".join(refs))))
        rows += [("عدّاد الفاتورة (ICV)", en(str(edoc["icv"]))),
                 ("حالتها لدى الهيئة",
                  _ft.STATUS_LABELS.get(edoc["status"], edoc["status"]))]
        trs = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows)
        return f'''
    {TBL_PLAIN}<tr>
      <td width="68%" valign="top">{TBL}{trs}</table></td>
      <td width="32%" align="center" valign="middle"
          style="text-align:center;">{img}</td>
    </tr></table>'''
    except Exception:
        return ""


def _tpl_voucher(conn, voucher_id):
    """سند القبض/الصرف — جدولان فقط (ذهب · نقد) بأسطر متعددة الأعيرة،
    بلا تفقيط وبلا جدول طريقة الدفع. خانة التفاصيل تبقى فارغة إلا إذا
    كتب المستخدم بياناً لذلك السطر، و«وذلك مقابل» تعرض بيان السند العام.
    """
    from models.vouchers import voucher_lines
    from services.accounting_engine import account_balance
    v = conn.execute("SELECT * FROM vouchers WHERE id=?",
                     (voucher_id,)).fetchone()
    if not v:
        raise ValueError("السند غير موجود")
    is_receipt = v["kind"] == "receipt"
    kind = "سند قبض" if is_receipt else "سند صرف"
    lead = "استلمنا من المكرم" if is_receipt else "صرفنا للمكرم"

    party, acc_no, acc_ref = "—", "—", None
    if v["customer_id"]:
        e = conn.execute(
            "SELECT e.name, e.account_id, a.code FROM entities e"
            " LEFT JOIN accounts a ON a.id=e.account_id WHERE e.id=?",
            (v["customer_id"],)).fetchone()
        if e:
            party, acc_no, acc_ref = e["name"], e["code"] or "—", e["account_id"]
    elif v["target_account_id"]:
        a = conn.execute("SELECT name, code, id FROM accounts WHERE id=?",
                         (v["target_account_id"],)).fetchone()
        if a:
            party, acc_no, acc_ref = a["name"], a["code"], a["id"]

    g_bal = c_bal = 0.0
    if acc_ref:
        g_bal, c_bal = account_balance(conn, acc_ref)

    def side(val):
        return "مدين" if val > 0 else ("دائن" if val < 0 else "متوازن")

    rows = voucher_lines(conn, voucher_id)
    time_str = (v["created_at"] or "")[11:19] or "—"

    # ── جدول الذهب: سطر لكل عيار ──
    gold_rows, tot_w, tot_e = "", 0.0, 0.0
    for r in rows:
        if r["line_kind"] != "gold":
            continue
        tot_w += r["gold_weight"]
        tot_e += r["gold_equiv18"]
        # التفاصيل فارغة إلا إذا كتب المستخدم بياناً لهذا السطر
        gold_rows += "<tr>" + cells(
            tdw(r["line_notes"] or "", 40, "right"),
            tdw(_w(r["gold_weight"]), 20),
            tdw(en(r["gold_karat"]), 15),
            tdw(_gw(r["gold_equiv18"]), 25)) + "</tr>"
    if v["disc_gold"]:
        gold_rows += "<tr>" + cells(
            tdw("خصم وزني", 40, "right"),
            tdw(_gw(v["disc_gold"]), 20),
            tdw(en(str(_kactive())), 15),
            tdw(_gw(v["disc_gold"]), 25)) + "</tr>"
    gold_block = ""
    if gold_rows:
        gold_block = f'''
    {TBL}
      <tr>{cells(thw("التفاصيل", 40), thw("الوزن القائم", 20),
                 thw("العيار", 15),
                 thw(f"وزن الذهب المعتمد ({_kunit()})", 25))}</tr>
      {gold_rows}
      <tr>{cells(thw("الإجمالي", 40), thw(_w(tot_w), 20),
                 thw("—", 15), thw(_gw(tot_e), 25))}</tr>
    </table>'''

    # ── جدول النقد ──
    cash_rows, tot_c = "", 0.0
    for r in rows:
        if r["line_kind"] != "cash":
            continue
        tot_c += r["cash_amount"]
        cash_rows += "<tr>" + cells(
            tdw(r["line_notes"] or "", 45, "right"),
            tdw("ريال سعودي", 30), tdw(_w(r["cash_amount"], 2), 25)) + "</tr>"
    if v["disc_cash"]:
        cash_rows += "<tr>" + cells(
            tdw("خصم نقدي", 45, "right"), tdw("ريال سعودي", 30),
            tdw(_w(v["disc_cash"], 2), 25)) + "</tr>"
    if v["net_diff"]:
        cash_rows += "<tr>" + cells(
            tdw("فرق الصافي", 45, "right"), tdw("ريال سعودي", 30),
            tdw(_w(v["net_diff"], 2), 25)) + "</tr>"
    cash_block = ""
    if cash_rows:
        cash_block = f'''
    {TBL}
      <tr>{cells(thw("التفاصيل", 45), thw("العملة", 30),
                 thw("المبلغ", 25))}</tr>
      {cash_rows}
      <tr>{cells(thw("الإجمالي", 45), thw("—", 30),
                 thw(_w(tot_c, 2), 25))}</tr>
    </table>'''

    sig_right = "توقيع المحاسب" if is_receipt else "توقيع المدير / المحاسب"
    info_cells = cells(
        f'''<td width="49%" style="vertical-align:top;">{TBL}
          <tr><th>رقم السند</th>
              <td>{en(v["voucher_no"] or voucher_id)}</td></tr>
          <tr><th>رقم الحساب</th><td>{en(acc_no)}</td></tr>
        </table></td>''',
        '<td width="2%"></td>',
        f'''<td width="49%" style="vertical-align:top;">{TBL}
          <tr><th>التاريخ</th>
              <td>{en(v["voucher_date"])}</td></tr>
          <tr><th>الوقت</th><td>{en(time_str)}</td></tr>
        </table></td>''')
    box_cells = cells(
        f'<td {TH} width="25%">وزن الذهب ({_kunit()})</td>',
        f'''<td align="center" style="text-align:center;
            border:1px solid #999; padding:4px; font-size:12pt;
            font-weight:bold; width:25%;">{_gw(v["gold_equiv18"])}</td>''',
        f'<td {TH} width="25%">ريال سعودي</td>',
        f'''<td align="center" style="text-align:center;
            border:1px solid #999; padding:4px; font-size:12pt;
            font-weight:bold; width:25%;">{_w(v["cash_amount"], 2)}</td>''')
    sig_cells = cells(
        f'''<td width="50%" align="center"
            style="text-align:center;">{sig_right}</td>''',
        '<td width="50%" align="center" style="text-align:center;">'
        'توقيع المستلم</td>')

    body = f'''
    {TBL_PLAIN}<tr>{info_cells}</tr></table>

    <table class="wide" width="100%" cellspacing="0" cellpadding="6">
      <tr>{box_cells}</tr>
    </table>

    <table class="wide" width="100%" cellspacing="0" cellpadding="6">
      <tr><td {TH} width="22%">{lead}</td>
          <td style="text-align:right; border:1px solid #999; padding:8px;
                     font-weight:bold; font-size:12pt;">{party}</td></tr>
    </table>
    {gold_block}{cash_block}

    <table class="wide" width="100%" cellspacing="0" cellpadding="6">
      <tr><td {TH} width="22%">وذلك مقابل</td>
          <td style="text-align:right; border:1px solid #999; padding:8px;">
            {v["notes"] or ""}</td></tr>
    </table>

    {TBL}
      <tr><td {TH} width="60%">رصيدكم الجديد للنقدية هو</td>
          <td>{_w(abs(c_bal), 2)}</td><td>{side(c_bal)}</td></tr>
      <tr><th>رصيدكم الجديد للذهب هو</th>
          <td>{_gw(abs(g_bal))}</td><td>{side(g_bal)}</td></tr>
    </table>

    <table class="sig" width="100%" cellspacing="0" cellpadding="6">
      <tr>{sig_cells}</tr>
    </table>
    '''
    return (_header(kind, v["voucher_no"] or f"#{voucher_id}",
                    v["voucher_date"], show_meta=False) + body)


def _balances_after(conn, entry_id, account_ids, title="الرصيد بعد العملية"):
    """جدول «الرصيد بعد العملية» — كما في فاتورة المبيعات والمرتجعات.

    الرصيد **حتى هذا القيد بعينه** لا رصيد اليوم: الورقة تُطبع بعد شهر
    فتبقى تقول ما كان بعد العملية نفسها. والترتيب بالتاريخ ثم بمفتاح
    الترتيب — كما يُحسب كشف الحساب — فيطابق رقمُ الورقة رقمَ الكشف.
    """
    if not entry_id or not account_ids:
        return ""
    e = conn.execute("SELECT entry_date, COALESCE(sort_key, id) k FROM"
                     " journal_entries WHERE id=?", (entry_id,)).fetchone()
    if not e:
        return ""
    u = _kunit()
    rows = ""
    for aid in list(dict.fromkeys(account_ids))[:4]:
        acc = conn.execute(
            "SELECT a.code, a.name, e.name ename FROM accounts a"
            " LEFT JOIN entities e ON e.account_id=a.id AND e.is_deleted=0"
            " WHERE a.id=?", (aid,)).fetchone()
        if not acc:
            continue
        b = conn.execute(
            "SELECT COALESCE(SUM(l.gold_debit-l.gold_credit),0) g,"
            " COALESCE(SUM(l.cash_debit-l.cash_credit),0) c"
            " FROM journal_lines l JOIN journal_entries j ON j.id=l.entry_id"
            " WHERE l.account_id=? AND j.is_deleted=0 AND (j.entry_date<?"
            " OR (j.entry_date=? AND COALESCE(j.sort_key, j.id)<=?))",
            (aid, e["entry_date"], e["entry_date"], e["k"])).fetchone()
        name = acc["ename"] or f"{acc['code']} — {acc['name']}"
        rows += (f'<tr><td {TH} width="70%">رصيد الذهب في حساب {name}'
                 f' ({u})</td><td>{_gw(b["g"])}</td></tr>'
                 f'<tr><th>رصيد النقد في حساب {name}</th>'
                 f'<td>{_w(b["c"], 2)}</td></tr>')
    if not rows:
        return ""
    return (f'<div class="note" style="margin-top:6px"><b>{title}</b></div>'
            f'{TBL}{rows}</table>')


def _party_accounts(conn, entry_id):
    """حسابات جهات التعامل في القيد — وإلا كل حساباته."""
    ids = [r[0] for r in conn.execute(
        "SELECT DISTINCT l.account_id FROM journal_lines l WHERE"
        " l.entry_id=? ORDER BY l.id", (entry_id,))]
    party = {r[0] for r in conn.execute(
        "SELECT account_id FROM entities WHERE is_deleted=0")}
    mine = [a for a in ids if a in party]
    return mine or ids


def _tpl_journal(conn, entry_id):
    e = conn.execute("SELECT * FROM journal_entries WHERE id=?",
                     (entry_id,)).fetchone()
    if not e:
        raise ValueError("القيد غير موجود")
    lines = conn.execute(
        "SELECT l.*, a.code, a.name FROM journal_lines l"
        " JOIN accounts a ON a.id=l.account_id WHERE l.entry_id=?"
        " ORDER BY l.id", (entry_id,)).fetchall()
    rows, tg_d = [], 0.0
    tg_c = tc_d = tc_c = 0.0
    for l in lines:
        tg_d += l["gold_debit"]; tg_c += l["gold_credit"]
        tc_d += l["cash_debit"]; tc_c += l["cash_credit"]
        rows.append((f"{l['code']} — {l['name']}",
                     _gw(l["gold_debit"]) if l["gold_debit"] else "",
                     _gw(l["gold_credit"]) if l["gold_credit"] else "",
                     _w(l["cash_debit"], 2) if l["cash_debit"] else "",
                     _w(l["cash_credit"], 2) if l["cash_credit"] else ""))
    balanced = (abs(tg_d - tg_c) < 0.011 and abs(tc_d - tc_c) < 0.011)
    body = f"""
    <table class="items">
      <tr><th>الحساب</th><th>مدين ذهب ({_kunit()})</th>
          <th>دائن ذهب ({_kunit()})</th>
          <th>مدين نقد</th><th>دائن نقد</th></tr>
      {_rows(rows)}
      <tr class="total"><td class="num">الإجمالي</td>
        <td class="num">{_gw(tg_d)}</td><td class="num">{_gw(tg_c)}</td>
        <td class="num">{_w(tc_d, 2)}</td><td class="num">{_w(tc_c, 2)}</td></tr>
    </table><br/>
    <div class="note">حالة التوازن:
      <b>{'متوازن — الميزانان الوزني والنقدي متطابقان' if balanced else 'غير متوازن'}</b></div>
    {_balances_after(conn, entry_id, _party_accounts(conn, entry_id))}
    """
    return (_header("قيد يومية", e["doc_no"] or f"#{entry_id}",
                    e["entry_date"])
            + body + _footer(e["user_note"] or ""))


def _tpl_melting(conn, op_id):
    op = conn.execute("SELECT * FROM melting_ops WHERE id=?",
                      (op_id,)).fetchone()
    if not op:
        raise ValueError("المستند غير موجود")
    label = melting.KIND_LABELS.get(op["kind"], "عملية صب وتصفية")
    rows = [(f"عيار {l['karat']}", _w(l["weight"]), _gw(l["equiv18"]))
            for l in melting.op_lines(conn, op_id)]
    if not rows:
        rows = [("—", "—", _gw(op["equiv18"]))]
    body = f"""
    <table class="items">
      <tr><th>العيار</th><th>الوزن الفعلي (جم)</th><th>المعادل ({_kunit()})</th></tr>
      {_rows(rows)}
      <tr class="total"><td class="num">الإجمالي</td><td class="num">—</td>
        <td class="num">{_gw(op['equiv18'])}</td></tr>
    </table><br/>
    <div class="note">المعادل بعيار المصنع: الوزن الفعلي × العيار ÷
      {_kactive()}.</div>
    """
    return (_header(label, op["op_no"] or f"#{op_id}", op["op_date"])
            + body + _footer(op["notes"] or ""))


def _purchase_party(conn, p):
    """المورد للآجل، والصندوق أو البنك للمدفوع — ما تغيّر رصيده بالفاتورة."""
    mode = (p["pay_mode"] if "pay_mode" in p.keys() else "") or "credit"
    if mode == "credit":
        r = conn.execute("SELECT account_id FROM entities WHERE id=?",
                         (p["supplier_id"],)).fetchone()
        return [r[0]] if r else []
    code = {"cash": "1400", "bank": "1500"}.get(mode)
    r = conn.execute("SELECT id FROM accounts WHERE code=?",
                     (code,)).fetchone()
    return [r[0]] if r else []


def _tpl_purchase(conn, pid):
    """فاتورة المورد كما قُيّدت: رقمها لدى المورد ورقمه الضريبي،
    والمعالجة الضريبية، والحساب المحمَّل، والصافي والضريبة والإجمالي."""
    from models import purchases as _pu
    p = conn.execute(
        "SELECT p.*, a.code acc_code, a.name acc_name FROM purchases p"
        " LEFT JOIN accounts a ON a.id=p.account_id WHERE p.id=?",
        (pid,)).fetchone()
    if not p:
        raise ValueError("الفاتورة غير موجودة")
    sup = conn.execute("SELECT name, phone, vat_number FROM entities"
                       " WHERE id=?", (p["supplier_id"],)).fetchone()
    keys = p.keys()
    tr = (p["tax_treatment"] if "tax_treatment" in keys else "") \
        or "standard"
    inv_no = (p["supplier_invoice_no"] if "supplier_invoice_no" in keys
              else "") or "—"
    amount = float(p["amount"] or 0)
    vat = float(p["vat_amount"] or 0)
    claim = tr == "standard" and vat > 0
    acc = (f"{p['acc_code']} — {p['acc_name']}" if p["acc_code"] else
           ("1700 — الأصول الثابتة" if p["asset_id"]
            else "5500 — مصروفات تشغيلية"))
    info = [("المورد", sup["name"] if sup else "—"),
            ("الرقم الضريبي للمورد", en((sup["vat_number"] if sup else "")
                                        or "—")),
            ("رقم فاتورة المورد", en(inv_no)),
            ("نوع فاتورة المورد", dict(_pu.INVOICE_TYPES).get(
                (p["invoice_type"] if "invoice_type" in keys else "")
                or "standard")),
            ("طريقة الدفع", dict(_pu.PAY_MODES).get(
                (p["pay_mode"] if "pay_mode" in keys else "")
                or "credit", "")),
            ("المعالجة الضريبية", dict(_pu.TAX_TREATMENTS).get(tr, tr)),
            ("يُحمَّل على حساب", acc)]
    trs = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in info)
    disc = float((p["discount"] if "discount" in keys else 0) or 0)
    rows = "<tr>" + cells(
        tdw(p["description"] or "—", align="right"),
        tdw(_w(amount + disc, 2)), tdw(_w(disc, 2)), tdw(_w(amount, 2)),
        tdw(_w(vat, 2)), tdw(_w(amount + vat, 2))) + "</tr>"
    head = cells(thw("البيان"), thw("المبلغ"), thw("الخصم"),
                 thw("الصافي الخاضع"), thw("الضريبة"), thw("الإجمالي"))
    body = f"""
    {TBL}{trs}</table><br/>
    {TBL}<tr>{head}</tr>{rows}</table>
    {TBL}
      <tr><th width="70%">ضريبة المدخلات القابلة للخصم (حساب 1900)</th>
          <td>{_w(vat if claim else 0, 2)}</td></tr>
      <tr><th>{"المستحق للمورد (آجل)" if ((p["pay_mode"] if "pay_mode"
                 in keys else "") or "credit") == "credit"
                 else "المدفوع للمورد"}</th>
          <td><b>{_w(amount + vat, 2)}</b></td></tr>
    </table>
    <div class="tafqeet">فقط: {tafqeet(amount + vat)}</div>
    {_balances_after(conn, p["entry_id"], _purchase_party(conn, p))}
    """
    kind = "فاتورة مشتريات (أصل ثابت)" if p["asset_id"] else "فاتورة مشتريات"
    return (_header(kind, p["purchase_no"] or f"#{pid}", p["purchase_date"])
            + body + _footer(""))


def _tpl_tax_sale(conn, sid):
    """الفاتورة الضريبية / المبسطة / الإشعار الدائن — من شاشة المبيعات
    الضريبية. عنوانها ومحتواها بما تشترطه الهيئة: الرقمان الضريبيان،
    عنوان المشتري للضريبية، الأسطر بصافيها وضريبتها، الإجماليات، ورمز
    QR (الموقّع إن صدر مستندٌ إلكتروني، وإلا رمز المرحلة الأولى)."""
    from models import tax_sales
    from services import photo_qr
    from services.fatoora import ledger as _ft
    from services.fatoora import profile as _pf
    s, lines = tax_sales.get(conn, sid)
    if not s:
        raise ValueError("المستند غير موجود")
    prof = _pf.load(conn)
    b = _pf.buyer(conn, s["customer_id"]) or {}
    std = _pf.buyer_is_b2b(b)
    edoc = None
    try:
        edoc = _ft.doc_for(conn, "tax_sales", sid)
    except Exception:
        edoc = None
    if edoc is not None:
        std = edoc["subtype"] == "standard"
    if s["kind"] == "credit":
        title = "إشعار دائن — مرتجع مبيعات ضريبية"
    elif s["kind"] == "debit":
        title = "إشعار مدين — زيادة على فاتورة ضريبية"
    else:
        title = "فاتورة ضريبية" if std else "فاتورة ضريبية مبسطة"
    qr = (edoc["cleared_qr"] or edoc["qr"]) if edoc is not None else (
        s["qr_base64"] or "")
    uri = photo_qr.qr_png_data_uri(qr, box_size=3, border=1) if qr else ""
    img = (f'<img src="{uri}" style="width:40mm; height:40mm;'
           f' max-height:none;" width="150" height="150"/>' if uri else "")
    pay = dict(tax_sales.PAY_MODES).get(s["pay_mode"], s["pay_mode"])
    time_str = (s["created_at"] or "")[11:19] or "—"
    meta = [("رقم المستند", en(s["doc_no"])),
            ("تاريخ الإصدار", en(s["doc_date"])),
            ("الوقت", en(time_str)),
            ("طريقة الدفع", pay.split(" — ")[0])]
    if s["rep_id"]:
        meta[-1] = ("المندوب", s["rep_name"] or "—")
    if s["kind"] in ("credit", "debit"):
        meta += [("إشعارٌ على الفاتورة", en(s["ref_no"] or "—")),
                 ("سبب الإشعار", s["reason"] or "—")]
    seller = [("البائع", prof.get("name") or config.COMPANY_NAME),
              ("الرقم الضريبي للبائع",
               en(prof.get("vat") or config.COMPANY_VAT_NUMBER or "—")),
              ("السجل التجاري", en(prof.get("crn") or config.COMPANY_CR))]
    buyer = [("المشتري", s["customer_name"])]
    if std:
        buyer += [("الرقم الضريبي للمشتري", en(b.get("vat", ""))),
                  ("عنوان المشتري",
                   f"{en(b.get('building', ''))} {b.get('street', '')}، "
                   f"{b.get('district', '')}، {b.get('city', '')} "
                   f"{en(b.get('postal', ''))}".strip(" ،"))]
    if edoc is not None:
        buyer += [("عدّاد الفاتورة (ICV)", en(str(edoc["icv"]))),
                  ("حالتها لدى الهيئة",
                   _ft.STATUS_LABELS.get(edoc["status"], edoc["status"]))]

    def _kv(rows):
        return "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows)

    info = f'''
    {TBL_PLAIN}<tr>
      <td width="36%" valign="top">{TBL}{_kv(meta)}</table></td>
      <td width="38%" valign="top">{TBL}{_kv(seller + buyer)}</table></td>
      <td width="26%" align="center" valign="middle"
          style="text-align:center;">{img}</td>
    </tr></table>'''
    rate = float(s["vat_rate"] or 0) * 100
    body_rows = ""
    wo_mode = any(li["wo_no"] for li in lines)
    has_disc = any(li["discount"] for li in lines)
    for li in lines:
        dcells = ((tdw(_w(li["net"] + li["discount"], 2)),
                   tdw(_w(li["discount"], 2))) if has_disc else ())
        if wo_mode and li["wo_no"]:
            body_rows += "<tr>" + cells(
                tdw(en(li["line_no"])), tdw(en(li["model_no"] or "—")),
                tdw(en(li["wo_no"])), tdw(_gw(li["qty"], 3)),
                tdw(_w(_krate(li["unit_price"]), 2)), *dcells,
                tdw(_w(li["net"], 2)), tdw(_w(li["vat"], 2)),
                tdw(_w(li["total"], 2))) + "</tr>"
        elif wo_mode:
            body_rows += "<tr>" + cells(
                tdw(en(li["line_no"])),
                f'<td class="r" colspan="4">{li["description"]}</td>',
                *dcells, tdw(_w(li["net"], 2)), tdw(_w(li["vat"], 2)),
                tdw(_w(li["total"], 2))) + "</tr>"
        else:
            body_rows += "<tr>" + cells(
                tdw(en(li["line_no"])), tdw(li["description"], align="right"),
                tdw(_w(li["qty"], 2)), tdw(_w(li["unit_price"], 2)),
                tdw(_w(li["discount"], 2)), tdw(_w(li["net"], 2)),
                tdw(en(f"{rate:g}%")), tdw(_w(li["vat"], 2)),
                tdw(_w(li["total"], 2))) + "</tr>"
    if wo_mode:
        head = cells(thw("م"), thw("رقم الموديل"), thw("رقم التشغيل"),
                     thw(f"الوزن<br/>{_kunit()}"), thw("الأجر/جم"),
                     *((thw("الأجور"), thw("الخصم")) if has_disc else ()),
                     thw("الصافي (الخاضع)" if has_disc
                         else "الأجور (الخاضع)"),
                     thw(f"الضريبة {en(f'{rate:g}')}%"), thw("الإجمالي"))
    else:
        head = cells(thw("م"), thw("البيان"), thw("الكمية"),
                     thw("سعر الوحدة"), thw("الخصم"),
                     thw("الصافي (الخاضع)"), thw("النسبة"),
                     thw("الضريبة"), thw("الإجمالي"))
    tdisc = sum(float(li["discount"] or 0) for li in lines)
    disc_rows = (f"<tr><th>الإجمالي قبل الخصم</th>"
                 f"<td>{_w(s['net'] + tdisc, 2)}</td></tr>"
                 f"<tr><th>الخصم</th><td>{_w(tdisc, 2)}</td></tr>"
                 if tdisc else "")
    totals = f'''
    {TBL}{disc_rows}
      <tr><th width="70%">الإجمالي الخاضع للضريبة (غير شامل)</th>
          <td>{_w(s['net'], 2)}</td></tr>
      <tr><th>ضريبة القيمة المضافة ({en(f"{rate:g}")}%)</th>
          <td>{_w(s['vat'], 2)}</td></tr>
      <tr><th>الإجمالي شامل الضريبة</th>
          <td><b>{_w(s['total'], 2)}</b></td></tr>
    </table>
    <div class="tafqeet">فقط: {tafqeet(s['total'])}</div>'''
    body = f'''{info}
    {TBL}<tr>{head}</tr>{body_rows}</table>
    {totals}'''
    return (_header(title, s["doc_no"], s["doc_date"], show_meta=False)
            + body + _footer(s["notes"] or ""))


def _period_head(date_from, date_to):
    today = _qd(QtCore.QDate.currentDate())
    return f'''
    {TBL}
      <tr><th>الفترة من</th><td>{en(date_from or "—")}</td>
          <th>إلى</th><td>{en(date_to or "—")}</td>
          <th>تاريخ الطباعة</th><td>{en(today)}</td></tr>
    </table><br/>''', today


def _tpl_tax_sales_register(conn, _id=0, date_from=None, date_to=None):
    """سجل المبيعات الضريبية للفترة — ضريبية/مبسطة لكل مستند، والإجماليات
    التي تنتقل للإقرار."""
    from models import tax_sales
    rows = sorted(tax_sales.search(conn, "", date_from, date_to,
                                   limit=100000),
                  key=lambda r: (r["doc_date"], r["id"]))
    kinds = {"invoice": "فاتورة", "credit": "إشعار دائن",
             "debit": "إشعار مدين"}
    body_rows, n_std, n_simp = "", 0, 0
    for r in rows:
        sub = tax_sales.subtype(conn, r)
        n_std += sub == "standard"
        n_simp += sub == "simplified"
        sign = "−" if r["kind"] == "credit" else ""
        body_rows += "<tr>" + cells(
            tdw(en(r["doc_no"])), tdw(kinds.get(r["kind"], r["kind"])),
            tdw(tax_sales.SUBTYPE_LABEL[sub]), tdw(en(r["doc_date"])),
            tdw(r["customer_name"], align="right"),
            tdw(en(r["customer_vat"] or "—")),
            tdw(r["rep_name"] or "—"),
            tdw(sign + _w(r["net"], 2)), tdw(sign + _w(r["vat"], 2)),
            tdw(sign + _w(r["total"], 2))) + "</tr>"
    if not body_rows:
        body_rows = f'<tr><td {TD} colspan="10">لا مستندات في الفترة</td></tr>'
    t = tax_sales.totals(conn, date_from or "0000-00-00",
                         date_to or "9999-12-31")
    head, today = _period_head(date_from, date_to)
    body = f'''{head}
    {TBL}<tr>{cells(thw("الرقم"), thw("النوع"), thw("ضريبية/مبسطة"),
                    thw("التاريخ"), thw("المشتري"), thw("رقمه الضريبي"),
                    thw("المندوب"), thw("الصافي"), thw("الضريبة"),
                    thw("الإجمالي"))}</tr>{body_rows}</table>
    {TBL}
      <tr><th width="70%">فواتير ضريبية (للشركات) · مبسطة (للأفراد)</th>
          <td>{en(n_std)} · {en(n_simp)}</td></tr>
      <tr><th>صافي المبيعات الضريبية بعد الإشعارات</th>
          <td>{_w(t["net"], 2)}</td></tr>
      <tr><th>صافي ضريبة المخرجات</th><td><b>{_w(t["vat"], 2)}</b></td></tr>
    </table>'''
    return (_header("سجل المبيعات الضريبية", "—", today, show_meta=False)
            + body + _footer(""))


def _tpl_purchases_register(conn, _id=0, date_from=None, date_to=None):
    """سجل المشتريات الضريبية للفترة — ما يُطلب عند الفحص: فاتورة المورد
    ونوعها ورقمه الضريبي والصافي والضريبة."""
    from models import purchases as _pu
    rows, tot, by = _pu.vat_register(conn, date_from or "0000-00-00",
                                     date_to or "9999-12-31")
    types = {"standard": "ضريبية", "simplified": "مبسطة"}
    pays = {"credit": "آجل", "cash": "نقداً", "bank": "بنكي"}
    treats = {"standard": "خاضعة 15%", "blocked": "لا تُسترد",
              "zero": "صفرية", "exempt": "معفاة", "unregistered": "غير مسجّل"}
    body_rows = ""
    for r in rows:
        body_rows += "<tr>" + cells(
            tdw(en(r["purchase_no"])), tdw(en(r["purchase_date"])),
            tdw(r["supplier_name"], align="right"),
            tdw(en(r["supplier_vat"] or "—")),
            tdw(en(r["supplier_invoice_no"] or "—")),
            tdw(types.get(r["invoice_type"] or "standard", "—")),
            tdw(pays.get(r["pay_mode"] or "credit", "—")),
            tdw(treats.get(r["tax_treatment"] or "standard", "—")),
            tdw(_w(r["amount"], 2)), tdw(_w(r["vat_amount"], 2)),
            tdw(_w(r["total"], 2))) + "</tr>"
    if not body_rows:
        body_rows = f'<tr><td {TD} colspan="11">لا فواتير في الفترة</td></tr>'
    head, today = _period_head(date_from, date_to)
    body = f'''{head}
    {TBL}<tr>{cells(thw("الرقم"), thw("التاريخ"), thw("المورد"),
                    thw("رقمه الضريبي"), thw("فاتورة المورد"),
                    thw("نوعها"), thw("الدفع"), thw("المعالجة"),
                    thw("الصافي"), thw("الضريبة"), thw("الإجمالي"))}</tr>
    {body_rows}</table>
    {TBL}
      <tr><th width="70%">عدد الفواتير</th><td>{en(tot["n"])}</td></tr>
      <tr><th>صافي المشتريات</th><td>{_w(tot["net"], 2)}</td></tr>
      <tr><th>ضريبة المدخلات القابلة للخصم</th>
          <td><b>{_w(tot["claimed"], 2)}</b></td></tr>
    </table>'''
    return (_header("سجل المشتريات الضريبية", "—", today, show_meta=False)
            + body + _footer(""))


def _tpl_fixing(conn, op_id):
    f = conn.execute("SELECT * FROM fixing_ops WHERE id=?", (op_id,)).fetchone()
    if not f:
        raise ValueError("العملية غير موجودة")
    ent = conn.execute("SELECT name FROM entities WHERE id=?",
                       (f["customer_id"],)).fetchone()
    rows = [(_gw(f["weight"]), _w(_krate(f["price"]), 2),
             _w(f["amount"], 2))]
    cacc = conn.execute("SELECT account_id FROM entities WHERE id=?",
                        (f["customer_id"],)).fetchone()
    body = f"""
    <div class="party">الجهة:
      <span class="party-name">{ent['name'] if ent else '—'}</span></div><br/>
    <table class="items">
      <tr><th>الوزن ({_kunit()})</th><th>سعر الجرام</th>
          <th>القيمة (ريال)</th></tr>
      {_rows(rows)}
    </table><br/>
    <div class="tafqeet">فقط: {tafqeet(f['amount'])}</div>
    {_balances_after(conn, f["entry_id"], [cacc[0]] if cacc else [])}
    """
    return (_header("سند تسكير (تسعير ذهب)", f["op_no"] or f"#{op_id}",
                    f["op_date"]) + body + _footer(""))


def _tpl_statement(conn, account_id, date_from=None, date_to=None,
                   karat=None):
    """كشف الحساب بالمعيار التصميمي الموحد: RTL إجباري · الجدول بعرض
    الصفحة ومتوسط · أعمدة مرنة (البيان يأخذ المساحة الأكبر والتواريخ
    والمبالغ تتقلص) · صف رصيد ختامي بارز · توقيعان.

    `karat` عيار **عرض** الأوزان: الورقة تخرج بنفس عيار الشاشة فلا
    يقرأ المستخدم رقمين مختلفين للحركة الواحدة. القيد لا يتغيّر.
    """
    from models import journal
    from services import gold_math
    acc = conn.execute("SELECT code, name FROM accounts WHERE id=?",
                       (account_id,)).fetchone()
    if not acc:
        raise ValueError("الحساب غير موجود")
    rows = journal.statement(conn, account_id, date_from, date_to)
    from services import karat_view
    k = int(karat or karat_view.active())

    def _g(v):
        return gold_math.from_base_karat(v or 0, k)

    body_rows = ""
    tot_gd = tot_gc = tot_cd = tot_cc = 0.0
    for r in rows:
        tot_gd += r["gd"] or 0
        tot_gc += r["gc"] or 0
        tot_cd += r["cd"] or 0
        tot_cc += r["cc"] or 0
        body_rows += "<tr>" + cells(
            tdw(en(r["date"]), 9), tdw(r["op"], 9),
            tdw(en(r["doc_no"] or ""), 9), tdw(r["name"] or "", 12),
            tdw(r["desc"] or "", 16, "right"),
            tdw(_w(_g(r["gd"])) if r["gd"] else "", 7),
            tdw(_w(_g(r["gc"])) if r["gc"] else "", 7),
            tdw(_w(_g(r["gbal"])), 8),
            tdw(_w(r["cd"], 2) if r["cd"] else "", 7),
            tdw(_w(r["cc"], 2) if r["cc"] else "", 7),
            tdw(_w(r["cbal"], 2), 9)) + "</tr>"
    if not body_rows:
        body_rows = f'<tr><td {TD} colspan="11">لا توجد حركات</td></tr>'

    g = rows[-1]["gbal"] if rows else 0.0
    c = rows[-1]["cbal"] if rows else 0.0
    gside = "مدين" if g > 0 else ("دائن" if g < 0 else "متوازن")
    cside = "مدين" if c > 0 else ("دائن" if c < 0 else "متوازن")
    today = _qd(QtCore.QDate.currentDate())

    body = f'''
    {TBL}
      <tr><td {TH} width="15%">اسم الحساب</td>
          <td class="r">{acc["name"]}</td>
          <td {TH} width="15%">رقم الحساب</td>
          <td>{en(acc["code"])}</td></tr>
      <tr><th>الفترة من</th><td>{en(date_from or "—")}</td>
          <th>إلى</th><td>{en(date_to or "—")}</td></tr>
      <tr><th>تاريخ الطباعة</th>
          <td {TD} colspan="3">{en(today)}</td></tr>
    </table>

    {TBL}
      <tr>{cells(thw("التاريخ", 9), thw("نوع العملية", 9),
                 thw("رقم المستند", 9), thw("الجهة المقابلة", 12),
                 thw("البيان", 16), thw(f"مدين ذهب {en(k)}", 7),
                 thw(f"دائن ذهب {en(k)}", 7),
                 thw(f"رصيد ذهب {en(k)}", 8),
                 thw("مدين نقد", 7), thw("دائن نقد", 7),
                 thw("رصيد نقد", 9))}</tr>
      {body_rows}
      <tr><td {TD_TOT} colspan="5">إجمالي الحركة</td>
        <td>{_w(_g(tot_gd))}</td><td>{_w(_g(tot_gc))}</td>
        <td>—</td>
        <td>{_w(tot_cd, 2)}</td><td>{_w(tot_cc, 2)}</td>
        <td>—</td></tr>
    </table>

    {TBL}
      <tr><td {TH} width="60%">الرصيد الختامي للذهب (عيار {en(k)})</td>
          <td>{_w(abs(_g(g)))}</td><td>{gside}</td></tr>
      <tr><th>الرصيد الختامي للنقد</th>
          <td>{_w(abs(c), 2)}</td><td>{cside}</td></tr>
    </table>

    <table class="sig" width="100%" cellspacing="0" cellpadding="6">
      <tr><td width="50%" align="center" style="text-align:center;">
            توقيع المحاسب<br/>........................</td>
          <td width="50%" align="center" style="text-align:center;">
            توقيع المستلم / العميل<br/>........................</td></tr>
    </table>
    '''
    return (_header("كشف حساب", acc["code"], today, show_meta=False) + body)


def _tpl_customer_analytics(conn, customer_id, date_from=None,
                            date_to=None, visible=None, expanded=None,
                            karat=None):
    """قالب طبق الأصل من شاشة تحليل المبيعات (WYSIWYG).

    يحاكي الشاشة تماماً: اللوحة المخفية لا تُطبع، والجدول المطويّ
    يُطبع بإجمالياته بلا تفاصيله — فالورقة تطابق ما يراه المستخدم.

    مسمّيات الورقة مسمّيات كشف الحساب لا مسمّيات الشاشة: ما يخرج
    للعميل «مصروف» و«مرتجع» و«مباع صافي» و«سداد» — وهي لغته التي
    يوقّع عليها، لا لغة التحليل الإداري الداخلي.

    `karat` عيار عرض الأوزان: القيد بمكافئ 18 دائماً، والورقة تخرج
    بعيار العميل المتفق عليه.
    """
    from models import sales_analytics as sa
    from services import gold_math
    ent = conn.execute("SELECT * FROM entities WHERE id=?",
                       (customer_id,)).fetchone()
    if not ent:
        raise ValueError("العميل غير موجود")
    p = sa.all_panels(conn, customer_id, date_from, date_to)
    from services import karat_view
    k = int(karat or karat_view.active())

    def _g(v):
        return gold_math.from_base_karat(v or 0, k)

    # نفس ترتيب الشاشة: المصروف · المرتجع · المباع الصافي · السداد
    coll = p["collection"]
    panels = [
        ("المصروف", f"{_w(_g(p['sales']['weight']))} جم", "sales"),
        ("المرتجع", f"{_w(_g(p['returns']['weight']))} جم", "returns"),
        ("المباع الصافي", f"{_w(_g(p['net_sold']['weight']))} جم",
         "net_sold"),
        ("السداد",
         f"ذهب {_w(_g(coll['gold']))}<br/>نقد {_w(coll['cash'], 2)}",
         "collection"),
    ]

    # اللوحات المخفية على الشاشة لا تُطبع إطلاقاً
    vis = set(visible) if visible is not None else {k for _t, _v, k in panels}
    exp = set(expanded) if expanded is not None else set(vis)
    panels = [x for x in panels if x[2] in vis]

    head_cells, detail_cells = [], []
    for title, value, key in panels:
        head_cells.append(
            f'<td class="ca-head"><div class="ca-title">{title}</div>'
            f'<div class="ca-value num">{value}</div></td>')
        # الجدول المطويّ يُطبع بإجمالياته فقط بلا تفاصيله
        rows = (sa.panel_details(conn, key, customer_id, date_from, date_to)
                if key in exp else [])
        if key == "collection":
            body_rows = "".join(
                "<tr>" + cells(
                    f'<td>{en(r["wo"])}</td>',
                    f'<td>{_w(_g(r["weight"]))}</td>',
                    f'<td>{_w(r.get("cash", 0), 2)}</td>') + "</tr>"
                for r in rows)
        else:
            body_rows = "".join(
                "<tr>" + cells(f'<td>{en(r["wo"])}</td>',
                               f'<td>{_w(_g(r["weight"]))}</td>') + "</tr>"
                for r in rows)
        if not body_rows:
            body_rows = '<tr><td colspan="3">لا يوجد</td></tr>'
        total = (p["sales"]["weight"] if key == "sales" else
                 p["returns"]["weight"] if key == "returns" else
                 p["net_sold"]["weight"] if key == "net_sold" else
                 coll["gold"])
        if key == "collection":
            head = "<tr>" + cells(thw("رقم السند"),
                                  thw(f"سداد ذهب {en(k)}"),
                                  thw("سداد نقد")) + "</tr>"
            foot = ("<tr class=\"total\">" + cells(
                f'<td>الإجمالي</td>', f'<td>{_w(_g(coll["gold"]))}</td>',
                f'<td>{_w(coll["cash"], 2)}</td>') + "</tr>")
        else:
            head = ("<tr>" + cells(thw("رقم التشغيل"),
                                   thw(f"الوزن {en(k)}")) + "</tr>")
            foot = ("<tr class=\"total\">" + cells(
                f'<td>الإجمالي</td>', f'<td>{_w(_g(total))}</td>')
                + "</tr>")
        detail_cells.append(
            f'<td class="ca-detail"><table class="ca-tbl">'
            f'{head}{body_rows}{foot}</table></td>')

    # الرصيد المتبقي = رصيد حساب العميل في الدليل (لا الفترة وحدها)
    rem_g = rem_c = 0.0
    if ent["account_id"]:
        rb = conn.execute(
            "SELECT COALESCE(SUM(l.gold_debit-l.gold_credit),0) g,"
            " COALESCE(SUM(l.cash_debit-l.cash_credit),0) c"
            " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
            " WHERE e.is_deleted=0 AND l.account_id=?",
            (ent["account_id"],)).fetchone()
        rem_g, rem_c = round(rb["g"], 2), round(rb["c"], 2)

    # كل رصيد وحالته: الذهب قد يكون عليه والنقد له في آنٍ واحد، فحالة
    # واحدة مشتركة للاثنين تكون خاطئة في نصف الحالات.
    def _side(v):
        return "مدين" if v > 0 else ("دائن" if v < 0 else "متوازن")

    # جدولان صغيران متلاصقان أعلى اليمين: الذهب والنقد. كل جدول سطر
    # عنوان وسطر قيمة من خانتين (الرقم · مدين/دائن) — الرصيد يُقرأ في
    # لمحة بلا شريط عريض يزاحم اللوحات.
    def _mini(title, value, side_txt):
        return (
            '<table class="ca-bal" width="100%" cellspacing="0"'
            ' cellpadding="3">'
            f'<tr><th colspan="2">{title}</th></tr>'
            '<tr>' + cells(f'<td class="num"><b>{value}</b></td>',
                           f'<td>{side_txt}</td>') + '</tr>'
            '</table>')

    bal_pair = (
        '<table class="plain" width="100%" cellspacing="0" cellpadding="0">'
        '<tr>' + cells(
            f'<td width="50%" valign="top">'
            f'{_mini(f"ذهب {en(k)}", _w(abs(_g(rem_g))), _side(rem_g))}</td>',
            f'<td width="50%" valign="top">'
            f'{_mini("نقد ريال", _w(abs(rem_c), 2), _side(rem_c))}</td>')
        + '</tr></table>')

    body = f'''
    <div class="party">اسم العميل:
      <span class="party-name">{ent['name']}</span></div>
    <div class="party" style="margin-top:4px">نطاق التاريخ:
      <span class="num">{date_from or 'جميع التواريخ المسجلة'}</span>
      {('إلى <span class="num">' + str(date_to) + '</span>') if date_to else ''}
    </div>
    <table class="plain" width="100%" cellspacing="0" cellpadding="0"
           style="margin-top:6px">
      <tr>{cells(f'<td width="38%" valign="top">{bal_pair}</td>',
                 '<td width="62%"></td>')}</tr>
    </table><br/>
    <table class="ca-wrap"><tr>{''.join(head_cells)}</tr></table>
    <table class="ca-wrap" style="margin-top:6px"><tr>{''.join(detail_cells)}</tr></table>
    '''
    return (_header("تقرير المبيعات", ent["name"],
                    _qd(QtCore.QDate.currentDate()))
            + body + _footer(""))


def _tpl_mfg(conn, _id=0, period=None, targets=None, salaries=None,
             kind="mfg_summary"):
    """قوالب طباعة شاشة تكاليف ورواتب قسم التصنيع (ثلاثة تبويبات)."""
    from models import mfg_costs
    period = period or ""
    today = _qd(QtCore.QDate.currentDate())

    def _table(headers, rows, totals=None):
        """جدول مضغوط: `table-layout:fixed` وخط صغير — فتظهر كل
        الأعمدة في صفحة واحدة بلا قصّ."""
        n = max(1, len(headers))
        # خط يتناسب مع عدد الأعمدة — يضمن ظهورها كلها في صفحة واحدة
        # الطباعة تبقى بحجمها المعتاد؛ التقليص طفيف عند كثرة الأعمدة
        fs = 7.5 if n >= 13 else (8 if n >= 11 else 8.5)
        first = 14 if n > 10 else (16 if n > 6 else 22)
        rest = round((100 - first) / (n - 1), 3) if n > 1 else 100
        cg = "".join(
            f'<col style="width:{first if i == 0 else rest}%"/>'
            for i in range(n))
        head = "<tr>" + cells(*[thw(h) for h in headers]) + "</tr>"
        body = "".join(
            "<tr>" + cells(*[f"<td>{en(c)}</td>" for c in r]) + "</tr>"
            for r in rows)
        if not body:
            body = f'<tr><td {TD} colspan="{n}">لا بيانات</td></tr>'
        foot = ("<tr>" + cells(*[thw(str(c)) for c in totals]) + "</tr>"
                if totals else "")
        return (f'<table class="items compact" width="100%"'
                f' cellspacing="0" cellpadding="1"'
                f' style="font-size:{fs}pt">'
                f'{cg}{head}{body}{foot}</table>')

    # الأعمدة تُقرأ من تعريف الشاشة نفسها فلا يختلف المطبوع عن المعروض
    try:
        from ui.mfg_costs_screen import SALARY_COLS, TARGET_COLS
    except Exception:
        TARGET_COLS = SALARY_COLS = None

    if kind == "mfg_target":
        title = "تارجت وإنتاج عمال قسم التصنيع"
        if TARGET_COLS:
            keys = [c[0] for c in TARGET_COLS]
            hdr = [c[1] for c in TARGET_COLS]
        else:
            hdr = ["الاسم", "أيام", "ساعات", "إضافية", "الغياب", "الخصم",
                   "إضافية/شهر", "تارجت/ساعة", "المفترض", "الفعلي",
                   "الفرق", "التارجت"]
            keys = ["name", "month_days", "hours", "overtime_hours",
                    "absence", "deduction", "overtime_month",
                    "target_per_hour", "expected_output", "actual_output",
                    "difference", "target_amount"]
        rows = [[r.get("name")] + [_w(r.get(k, 0), 2) for k in keys[1:]]
                for r in (targets or [])]
        tot = ["الإجمالي"] + [
            _w(sum(float(r.get(k) or 0) for r in (targets or [])), 2)
            for k in keys[1:]]
        body = _table(hdr, rows, tot)

    elif kind == "mfg_salary":
        title = "رواتب عمال قسم التصنيع"
        if SALARY_COLS:
            keys = [c[0] for c in SALARY_COLS]
            hdr = [c[1] for c in SALARY_COLS]
        else:
            hdr = ["اسم العامل", "الأساسي", "إضافية", "معامل", "الإضافي",
                   "الغياب", "الخصم", "الفاقد/ذهب", "خصم/ذهب", "التارجت",
                   "المكافأة", "الصافي", "عليه (مدين)", "المستحق"]
            keys = ["name", "basic_salary", "overtime_hours",
                    "overtime_rate", "overtime", "absence", "deduction",
                    "gold_loss", "gold_deduction", "target_amount",
                    "bonus", "net_salary", "owed", "due"]
        # عمود «عليه (مدين)» يُترك فارغاً عند الصفر كما على الشاشة:
        # الورقة تطابق ما يراه المستخدم، والصفر فيه يُقرأ خطأً.
        def _cell(r, k):
            v = r.get(k, 0)
            if k == "owed" and not float(v or 0):
                return ""
            return _w(v, 2)

        rows = [[r.get("name")] + [_cell(r, k) for k in keys[1:]]
                for r in (salaries or [])]
        tot = ["الإجمالي"] + [
            _w(sum(float(r.get(k) or 0) for r in (salaries or [])), 2)
            for k in keys[1:]]
        body = _table(hdr, rows, tot)

    else:
        title = "ملخص تكاليف قسم التصنيع"
        data = mfg_costs.summary(conn, period) if period else []
        rows = [[n, _w(c, 2), _w(g, 2)] for n, c, g in data[:-1]]
        tot = ([data[-1][0], _w(data[-1][1], 2), _w(data[-1][2], 2)]
               if data else None)
        body = _table(["الاسم", "المبلغ", "الذهب"], rows, tot)

    meta = f'''{TBL}
      <tr>{cells(thw("الشهر"), f'<td>{en(period)}</td>',
                 thw("تاريخ الطباعة"), f'<td>{en(today)}</td>')}</tr>
    </table><br/>'''
    return (_header(title, "—", today, show_meta=False)
            + meta + body + _footer(""))


def _tpl_turnover(conn, _id=0, date_from=None, date_to=None):
    """تقرير دوران المخزون: أربع لوحات، كل واحدة في جدول مستقل بترويسة
    باسمها وإجمالَي الوزن المقيد والقائم في نهايته."""
    from models import inventory
    data = inventory.turnover_all(conn, date_from, date_to)
    today = _qd(QtCore.QDate.currentDate())

    blocks = ""
    for key, title, hint in inventory.TURNOVER_PANELS:
        d = data[key]
        # الوارد يعرض المُرجِع، والصادر يعرض البائع
        _ret = "مرتجعة" in title
        _key = "returner" if _ret else "buyer"
        rows_html = "".join(
            "<tr>" + cells(f'<td>{en(i["wo"])}</td>',
                           f'<td>{en(i.get(_key) or "—")}</td>',
                           f'<td>{_gw(i["reg"])}</td>',
                           f'<td>{_gw(i["standing"])}</td>') + "</tr>"
            for i in d["items"])
        if not rows_html:
            rows_html = f'<tr><td {TD} colspan="4">لا توجد أطقم</td></tr>'
        blocks += f'''
    <table class="titlebar" width="100%" cellspacing="0" cellpadding="6">
      <tr><td width="100%">{title} — {d["count"]} طقم</td></tr>
    </table>
    <div class="note">{hint}</div>
    {TBL}
      <tr>{cells(thw("رقم التشغيل"),
                 thw("المُرجِع" if _ret else "البائع"),
                 thw("الوزن المقيد"), thw("الوزن القائم"))}</tr>
      {rows_html}
      <tr>{cells(thw("الإجمالي"), thw(f'{d["count"]} طقم'),
                 thw(_gw(d["total_reg"])),
                 thw(_gw(d["total_standing"])))}</tr>
    </table><br/>'''

    body = f'''
    {TBL}
      <tr><th>الفترة من</th><td>{en(date_from or "—")}</td>
          <th>إلى</th><td>{en(date_to or "—")}</td>
          <th>تاريخ الطباعة</th><td>{en(today)}</td></tr>
    </table><br/>
    {blocks}'''
    return (_header("تقرير دوران المخزون — تتبّع أرقام التشغيل",
                    "—", today, show_meta=False) + body + _footer(""))


def _tpl_balances(conn, entity_type, rows):
    """كشف الأرصدة المجمعة.

    ترتيب الأعمدة: الجهة · ذهب 18 · الحالة · الأجور · الحالة.
    **الخلل السابق**: الرأس كان خمسة أعمدة والصف ستة (بعمود ترقيم)،
    فتنزاح كل القيم عموداً وتظهر تحت عناوين خاطئة.
    """
    from models.entities import TYPE_LABELS

    def _side(v):
        return "مدين" if v >= 0 else "دائن"

    body_rows = ""
    for r in rows:
        body_rows += (
            f'<tr><td class="r">{r["name"]}</td>'
            f'<td>{_gw(abs(r["gold"]))}</td>'
            f'<td>{_side(r["gold"])}</td>'
            f'<td>{_w(abs(r["cash"]), 2)}</td>'
            f'<td>{_side(r["cash"])}</td></tr>')
    if not body_rows:
        body_rows = f'<tr><td {TD} colspan="5">لا توجد أرصدة</td></tr>'

    # الإجماليات: مدين · دائن · الصافي لكل بُعد
    dg = round(sum(r["gold"] for r in rows if r["gold"] > 0), 3)
    cg = round(-sum(r["gold"] for r in rows if r["gold"] < 0), 3)
    dc = round(sum(r["cash"] for r in rows if r["cash"] > 0), 2)
    cc = round(-sum(r["cash"] for r in rows if r["cash"] < 0), 2)
    ng = round(dg - cg, 3)
    nc = round(dc - cc, 2)

    today = _qd(QtCore.QDate.currentDate())
    label = TYPE_LABELS.get(entity_type, entity_type or "")
    body = f'''
    <div {WIDE}>تاريخ الكشف: <b>{en(today)}</b></div>
    {TBL}
      <tr>{cells(thw("الجهة", 34), thw(f"ذهب ({_kunit()})", 18),
                 thw("الحالة", 12), thw("الأجور (ريال)", 24),
                 thw("الحالة", 12))}</tr>
      {body_rows}
    </table>

    <table class="items totals" width="100%" cellspacing="0"
           cellpadding="6" style="margin-top:8px">
      <tr>{cells(thw("الإجمالي", 34), thw("مدين", 18),
                 thw("دائن", 18), thw("الصافي", 30))}</tr>
      <tr>{cells(f'<td class="r"><b>ذهب ({_kunit()})</b></td>',
                 f'<td>{_gw(dg)}</td>', f'<td>{_gw(cg)}</td>',
                 f'<td><b>{_gw(ng)}</b> — {_side(ng)}</td>')}</tr>
      <tr>{cells('<td class="r"><b>الأجور (ريال)</b></td>',
                 f'<td>{_w(dc, 2)}</td>', f'<td>{_w(cc, 2)}</td>',
                 f'<td><b>{_w(nc, 2)}</b> — {_side(nc)}</td>')}</tr>
      <tr>{cells('<td class="r">عدد الجهات</td>',
                 f'<td {TD} colspan="3">{en(len(rows))} جهة</td>')}</tr>
    </table>

    <table class="sig" width="100%" cellspacing="0" cellpadding="6">
      <tr><td width="50%"></td>
          <td width="50%" align="center" style="text-align:center;">
            التوقيع<br/>...........................</td></tr>
    </table>
    '''
    return (_header(f"كشف الأرصدة المجمعة — {label}", "—", today,
                    show_meta=False) + body)


def build_body(doc_type, doc_id, **kw):
    """يبني **جسم** المستند فقط (بلا ترويسة HTML ولا أنماط).

    يستخدمه محرك الطباعة عبر المتصفح (`services.browser_print`) الذي
    يوفّر أنماطه الكاملة بنفسه.
    """
    with db() as conn:
        if doc_type == "statement":
            return en(_tpl_statement(conn, doc_id, kw.get("date_from"),
                                     kw.get("date_to"),
                                     _karat_kw(kw)))
        if doc_type == "balances":
            return en(_tpl_balances(conn, doc_id, kw.get("rows") or []))
        if doc_type == "customer_analytics":
            return en(_tpl_customer_analytics(
                conn, doc_id, kw.get("date_from"), kw.get("date_to"),
                kw.get("visible"), kw.get("expanded"),
                _karat_kw(kw)))
        if doc_type in ("mfg_target", "mfg_salary", "mfg_summary"):
            return en(_tpl_mfg(conn, doc_id, kw.get("period"),
                               kw.get("targets"), kw.get("salaries"),
                               doc_type))
        if doc_type == "turnover":
            return en(_tpl_turnover(conn, doc_id, kw.get("date_from"),
                                    kw.get("date_to")))
        if doc_type == "tax_sales_register":
            return en(_tpl_tax_sales_register(
                conn, doc_id, kw.get("date_from"), kw.get("date_to")))
        if doc_type == "purchases_register":
            return en(_tpl_purchases_register(
                conn, doc_id, kw.get("date_from"), kw.get("date_to")))
        if doc_type in ("workshop_losses", "workshop_losses_log"):
            return en(_tpl_workshop_losses(conn, doc_id,
                                           kw.get("date_from"),
                                           kw.get("date_to")))
        if doc_type == "models_catalog":
            return en(_tpl_models_catalog(conn, doc_id,
                                          kw.get("mode", "all"),
                                          kw.get("sort", "az"),
                                          kw.get("expanded")))
        if doc_type == "models_received":
            return en(_tpl_models_received(conn, doc_id,
                                           kw.get("date_from"),
                                           kw.get("date_to"),
                                           kw.get("mode", "all"),
                                           kw.get("sort", "az")))
        if doc_type == "dossier_models":
            return en(_tpl_dossier_models(
                conn, doc_id, kw.get("date_from"), kw.get("date_to"),
                kw.get("per_page", 4)))
        if doc_type == "models_received_photos":
            return en(_tpl_models_received_photos(
                conn, doc_id, kw.get("date_from"), kw.get("date_to"),
                kw.get("mode", "all"), kw.get("sort", "az"),
                kw.get("per_page", 4)))
        if doc_type == "model_photos":
            return en(_tpl_model_photos(conn, doc_id,
                                        kw.get("min_count", 3),
                                        kw.get("mode", "all"),
                                        kw.get("sort", "az"),
                                        kw.get("per_page", 4)))
        if doc_type == "dash_panel":
            return en(_tpl_dash_panel(
                conn, doc_id, kw.get("title", ""),
                kw.get("kind", "accounts"), kw.get("codes"),
                kw.get("ratios"), kw.get("date_from"),
                kw.get("date_to"), kw.get("search", "")))
        if doc_type == "aging":
            return en(_tpl_aging(conn, doc_id,
                                 kw.get("entity_type", "customer"),
                                 kw.get("as_of"), kw.get("dim", "both"),
                                 kw.get("only")))
        if doc_type == "day_close":
            return en(_tpl_day_close(conn, doc_id, kw.get("date")))
        if doc_type == "stock_aging":
            return en(_tpl_stock_aging(conn, doc_id, kw.get("as_of"),
                                       kw.get("model"),
                                       kw.get("detail", False)))
        if doc_type == "dossier":
            return en(_tpl_dossier(conn, doc_id, kw.get("date_from"),
                                   kw.get("date_to")))
        if doc_type == "doc_edits":
            return en(_tpl_doc_edits(conn, doc_id, kw.get("date_from"),
                                     kw.get("date_to"),
                                     kw.get("source_table"),
                                     kw.get("min_lag", 0)))
        if doc_type == "balance_tree":
            return en(_tpl_balance_tree(conn, doc_id, kw.get("date_to"),
                                        kw.get("max_level", 3),
                                        kw.get("hide_zero", True)))
        if doc_type == "trial_balance":
            return en(_tpl_trial_balance(conn, doc_id, kw.get("date_from"),
                                         kw.get("date_to"),
                                         kw.get("include_zero", False),
                                         kw.get("dim", "cash"),
                                         kw.get("max_level", 9)))
        if doc_type == "financial_position":
            return en(_tpl_financial_position(conn, doc_id, kw.get("as_of"),
                                              kw.get("compare_to")))
        if doc_type == "equity_changes":
            return en(_tpl_equity_changes(
                conn, doc_id, kw.get("date_from"), kw.get("date_to"),
                kw.get("compare", True), kw.get("dim", "cash")))
        if doc_type == "cash_flow":
            return en(_tpl_cash_flow(
                conn, doc_id, kw.get("date_from"), kw.get("date_to"),
                kw.get("compare", True), kw.get("method", "indirect")))
        if doc_type == "income_statement":
            return en(_tpl_income_statement(
                conn, doc_id, kw.get("date_from"), kw.get("date_to"),
                kw.get("compare", True), kw.get("show_accounts", False)))
        if doc_type == "workshop_accounts":
            return en(_tpl_workshop_accounts(conn, doc_id,
                                             kw.get("rows") or [],
                                             kw.get("date_from"),
                                             kw.get("date_to")))
        fn = BUILDERS.get(doc_type)
        if not fn:
            raise ValueError(f"لا يوجد قالب طباعة للنوع: {doc_type}")
        # القوالب التي تقبل معطيات إضافية تستقبلها، وغيرها بالمعرّف فقط
        try:
            import inspect
            params = set(inspect.signature(fn).parameters)
            extra = {k: v for k, v in kw.items() if k in params}
        except Exception:
            extra = {}
        return en(fn(conn, doc_id, **extra) if extra else fn(conn, doc_id))


def _tpl_work_order(conn, wo_id):
    """قالب طباعة دفعة التوريد: كل أطقم القيد المجمّع نفسه."""
    wo = conn.execute("SELECT * FROM work_orders WHERE id=?",
                      (wo_id,)).fetchone()
    if not wo:
        raise ValueError("رقم التشغيل غير موجود")
    entry = conn.execute("SELECT * FROM journal_entries WHERE id=?",
                         (wo["entry_id"],)).fetchone()
    # ══ نقرأ سطور الدفعة المحفوظة ══
    # القراءة من `work_orders` بـ`entry_id` تفشل في حالتين:
    #   • بعد التعديل: الأطقم تُربط بقيد جديد فلا يطابق قيد الكشف
    #   • الرقم التجميعي: سجل واحد مربوط بأول دفعة فقط
    # جدول سطور الدفعة يحفظ ما أُدخل فعلاً في كل قيد — فيصحّ دائماً.
    rows = []
    if entry:
        bl = conn.execute(
            "SELECT * FROM wo_batch_lines WHERE entry_id=?"
            " ORDER BY seq, id", (wo["entry_id"],)).fetchall()
        if bl:
            rows = [{
                "work_order_no": r["wo_no"],
                "gold_weight": r["gold"],
                "small_stones": r["small_stones"],
                "big_stones": r["big_stones"],
                "stones_after_discount": round(
                    (r["small_stones"] + r["big_stones"])
                    * (1 - r["discount_rate"]), 3),
                "standing_gold": round(
                    r["gold"] + r["small_stones"] + r["big_stones"], 3),
                "registered_weight": r["registered_weight"],
                "model_no": r["model_no"] or "",
            } for r in bl]
        else:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM work_orders WHERE entry_id=? AND is_deleted=0"
                " ORDER BY id", (wo["entry_id"],))]
    if not rows:
        rows = [dict(wo)]
    date = (entry["entry_date"] if entry else "") or ""
    desc = (entry["description"] if entry else "") or "توريد أطقم"

    body = ""
    t_gold = t_small = t_big = t_after = t_reg = t_stand = 0.0
    for r in rows:
        t_gold += r["gold_weight"] or 0
        t_small += r["small_stones"] or 0
        t_big += r["big_stones"] or 0
        t_after += r["stones_after_discount"] or 0
        t_reg += r["registered_weight"] or 0
        t_stand += r["standing_gold"] or 0
        body += "<tr>" + cells(
            tdw(en(r["work_order_no"])), tdw(_gw(r["gold_weight"])),
            tdw(_gw(r["small_stones"])), tdw(_gw(r["big_stones"])),
            tdw(_gw(r["stones_after_discount"])),
            tdw(_gw(r["standing_gold"])),
            tdw(_gw(r["registered_weight"]))) + "</tr>"
    if not body:
        body = f'<tr><td {TD} colspan="7">لا توجد أطقم</td></tr>'

    head = cells(thw("رقم التشغيل"), thw("الذهب"), thw("الفصوص"),
                 thw("الأحجار"), thw("بعد الخصم"), thw("الذهب القائم"),
                 thw("الوزن المقيد"))
    foot = cells(thw("الإجمالي"), thw(_gw(t_gold)), thw(_gw(t_small)),
                 thw(_gw(t_big)), thw(_gw(t_after)), thw(_gw(t_stand)),
                 thw(_gw(t_reg)))
    meta = f'''{TBL}
      <tr>{cells(thw("رقم القيد"),
                 f'<td>{en("#" + str(wo["entry_id"] or ""))}</td>',
                 thw("التاريخ"), f'<td>{en(date)}</td>',
                 thw("عدد الأطقم"), f'<td>{en(str(len(rows)))}</td>')}</tr>
    </table><br/>'''
    table = f"{TBL}<tr>{head}</tr>{body}<tr>{foot}</tr></table>"
    return (_header("سند توريد أطقم", "—", date, show_meta=False)
            + meta + table + _footer(desc))


def _tpl_workshop_losses(conn, _id=0, date_from=None, date_to=None):
    """سجل فواقد الورشة خلال الفترة."""
    from models import workshop_losses as wl
    rows = wl.list_losses(conn, date_from, date_to)
    today = _qd(QtCore.QDate.currentDate())
    body = "".join(
        "<tr>" + cells(
            tdw(en(r["doc_no"] or "—")), tdw(en(r["loss_date"])),
            f'<td class="r">{r["acc_name"]}</td>',
            tdw(_gw(r["weight"])),
            f'<td class="r">{r["description"] or ""}</td>') + "</tr>"
        for r in rows)
    if not body:
        body = f'<tr><td {TD} colspan="5">لا توجد سندات</td></tr>'
    tot = round(sum(float(r["weight"] or 0) for r in rows), 3)
    head = cells(thw("رقم السند"), thw("التاريخ"), thw("نوع الفاقد"),
                 thw("الوزن (جم)"), thw("البيان"))
    foot = cells(thw("الإجمالي"), thw(""), thw(f"{len(rows)} سند"),
                 thw(_gw(tot)), thw(""))
    table = f"{TBL}<tr>{head}</tr>{body}<tr>{foot}</tr></table>"
    return (_header("سجل فواقد الورشة", "—", today, show_meta=False)
            + table)


def _tpl_workshop_accounts(conn, _id=0, rows=None, date_from=None,
                           date_to=None):
    """مقارنة أرصدة حسابات الورشة."""
    rows = rows or []
    today = _qd(QtCore.QDate.currentDate())
    body = ""
    tg = tc = 0.0
    for x in rows:
        # الصفوف المحمّلة من الحفظ قد تحمل المفاتيح الأساسية فقط
        gd = float(x.get("gd") or 0)
        gc = float(x.get("gc") or 0)
        cd = float(x.get("cd") or 0)
        cc = float(x.get("cc") or 0)
        gb = round(gd - gc, 3)
        cb = round(cd - cc, 2)
        tg += gb
        tc += cb
        body += "<tr>" + cells(
            f'<td class="r">{x.get("code", "")} — {x.get("name", "")}</td>',
            tdw(_gw(gd)), tdw(_gw(gc)), tdw(_gw(gb)),
            tdw(_w(cd, 2)), tdw(_w(cc, 2)),
            tdw(_w(cb, 2))) + "</tr>"
    if not body:
        body = f'<tr><td {TD} colspan="7">لا توجد حسابات</td></tr>'
    head = cells(thw("الحساب"), thw("مدين ذهب"), thw("دائن ذهب"),
                 thw("رصيد الذهب"), thw("مدين نقد"), thw("دائن نقد"),
                 thw("رصيد النقد"))
    foot = cells(thw("الإجمالي"), thw(""), thw(""), thw(_gw(tg)),
                 thw(""), thw(""), thw(_w(tc, 2)))
    table = f"{TBL}<tr>{head}</tr>{body}<tr>{foot}</tr></table>"
    meta = (f'<div {WIDE}>الفترة: <b>{en(date_from or "—")}</b>'
            f' إلى <b>{en(date_to or "—")}</b></div>')
    return (_header("مقارنة حسابات الورشة", "—", today, show_meta=False)
            + meta + table)


def _tpl_balance_tree(conn, _id=0, date_to=None, max_level=3,
                      hide_zero=True):
    """قالب الميزانية العمومية الشجرية بمستوياتها."""
    from models import balance_tree
    b = balance_tree.balance_sheet_tree(
        conn, date_to=date_to, max_level=int(max_level or 3),
        hide_zero=bool(hide_zero))
    today = _qd(QtCore.QDate.currentDate())

    body = ""
    for sec in b["sections"]:
        if not sec["rows"] and abs(sec["gold"]) < 0.001 \
                and abs(sec["cash"]) < 0.01:
            continue
        body += ("<tr>" + cells(
            f'<td class="r"><b>◄ {sec["title"]}</b></td>',
            f'<td><b>{en(sec["code"])}</b></td>',
            f'<td><b>{_w(sec["cash"], 2)}</b></td>',
            f'<td><b>{_gw(sec["gold"])}</b></td>') + "</tr>")
        for r in sec["rows"]:
            if r["level"] == 1:
                continue
            pad = 12 * (r["level"] - 1)
            body += ("<tr>" + cells(
                f'<td class="r" style="padding-right:{pad}px">'
                f'{r["name"]}</td>',
                f'<td>{en(r["code"])}</td>',
                f'<td>{_w(r["cash"], 2)}</td>',
                f'<td>{_gw(r["gold"])}</td>') + "</tr>")
    if not body:
        body = f'<tr><td {TD} colspan="4">لا توجد أرصدة</td></tr>'

    ag, ac = b["assets"]
    rg, rc = b["right_side"]
    ok = b["balanced_cash"] and b["balanced_gold"]
    head = cells(thw("الحساب", 42), thw("الكود", 12),
                 thw("النقد / الأجور (ريال)", 23),
                 thw(f"الذهب ({_kunit()})", 23))
    meta = f'''{TBL}
      <tr>{cells(thw("حتى تاريخ"), f'<td>{en(date_to or today)}</td>',
                 thw("مستوى التفصيل"), f'<td>{en(max_level)}</td>')}</tr>
    </table><br/>'''
    totals = f'''
    <table class="items totals" width="100%" cellspacing="0"
           cellpadding="6" style="margin-top:8px">
      <tr>{cells(thw("البيان", 40), thw("النقد (ريال)", 30),
                 thw(f"الذهب ({_kunit()})", 30))}</tr>
      <tr>{cells('<td class="r"><b>إجمالي الأصول</b></td>',
                 f'<td><b>{_w(ac, 2)}</b></td>',
                 f'<td><b>{_gw(ag)}</b></td>')}</tr>
      <tr>{cells('<td class="r"><b>الخصوم + حقوق الملكية + النتيجة</b>'
                 '</td>',
                 f'<td><b>{_w(rc, 2)}</b></td>',
                 f'<td><b>{_gw(rg)}</b></td>')}</tr>
      <tr>{cells('<td class="r">الفرق</td>',
                 f'<td>{_w(b["diff_cash"], 2)}</td>',
                 f'<td>{_gw(b["diff_gold"])}</td>')}</tr>
    </table>
    <div {WIDE} style="margin-top:6px">
      <b>{"✔ الميزانية متوازنة في البعدين" if ok
          else "✘ يوجد عجز — راجع القيود"}</b>
    </div>'''
    table = f"{TBL}<tr>{head}</tr>{body}</table>"
    return (_header("الميزانية العمومية", "—", date_to or today,
                    show_meta=False) + meta + table + totals)


def _sign_block():
    """توقيعات القوائم المالية: أعدّه · راجعه · اعتمده — بخاتم المصنع."""
    stamp = getattr(config, "STAMP_PATH", None)
    stamp_img = (f'<img src="{Path(str(stamp)).as_uri()}" height="70">'
                 if stamp and Path(str(stamp)).exists() else "")
    sig = ("<br/>الاسم: ......................<br/><br/>"
           "التوقيع: ....................")
    return ('<table class="sig" width="100%" cellspacing="0"'
            ' cellpadding="6"><tr>'
            + cells(f'<td width="33%" align="center"><b>أعدّه (المحاسب)</b>'
                    f'{sig}</td>',
                    f'<td width="33%" align="center"><b>راجعه (المراجع)</b>'
                    f'{sig}</td>',
                    f'<td width="34%" align="center"><b>اعتمده (المدير /'
                    f' المالك)</b>{sig}<br/>{stamp_img}</td>')
            + "</tr></table>")


def _nowrap(text):
    """فترةٌ لا تنكسر عند شرطة التاريخ."""
    return f'<span style="white-space:nowrap">{text}</span>'


def _entity_meta(pairs):
    """بيانات القائمة: المنشأة والسجل والرقم الضريبي ثم ما يُمرَّر."""
    items = [("المنشأة", config.COMPANY_NAME)]
    if getattr(config, "COMPANY_CR", ""):
        items.append(("السجل التجاري", en(config.COMPANY_CR)))
    if getattr(config, "COMPANY_VAT_NUMBER", ""):
        items.append(("الرقم الضريبي", en(config.COMPANY_VAT_NUMBER)))
    items += list(pairs)
    rows = ""
    for i in range(0, len(items), 3):
        tds = []
        for k, v in items[i:i + 3]:
            tds += [thw(k), f"<td>{v}</td>"]
        rows += f"<tr>{cells(*tds)}</tr>"
    return f"{TBL}{rows}</table><br/>"


def _tpl_trial_balance(conn, _id=0, date_from=None, date_to=None,
                       include_zero=False, dim="cash", max_level=9):
    """ميزان المراجعة بالأرصدة والمجاميع — الشكل الذي يطلبه المراجع.

    لكل حساب ثلاثة أزواج (مدين | دائن): أول المدة · حركة الفترة · آخر
    المدة؛ بشجرة الحسابات ومستوياتها، وبُعدٍ واحد (ريال أو ذهب).
    """
    from models import statements
    tb = statements.trial_balance(conn, date_from or None, date_to or None,
                                  dim, int(max_level or 9),
                                  include_zero=bool(include_zero))
    today = _qd(QtCore.QDate.currentDate())
    gold = tb["dim"] == "gold"

    def f(v):
        if gold:
            return _gw(v, 3) if abs(v) >= 0.0005 else ""
        return _w(v, 2) if abs(v) >= 0.005 else ""

    keys = ("open_dr", "open_cr", "dr", "cr", "close_dr", "close_cr")
    body = ""
    for r in tb["rows"]:
        bold = r["is_root"] or not r["terminal"]
        b0, b1 = ("<b>", "</b>") if bold else ("", "")
        bg = "background-color:#EFE9DC;" if r["is_root"] else ""
        st = f' style="{bg}"' if bg else ""
        pad = 10 * (r["level"] - 1) + 4
        tds = [f'<td{st}>{b0}{en(r["code"])}{b1}</td>',
               f'<td class="r" style="{bg}padding-right:{pad}px">'
               f'{b0}{r["name"]}{b1}</td>']
        tds += [f'<td class="num"{st}>{b0}{f(r[k])}{b1}</td>'
                for k in keys]
        body += "<tr>" + cells(*tds) + "</tr>"
    if not body:
        body = f'<tr><td {TD} colspan="8">لا توجد أرصدة ولا حركة</td></tr>'
    t = tb["totals"]
    tot_st = ' style="background-color:#F2EEE4;border-top:2px solid #333"'
    body += ("<tr>" + cells(
        f'<td{tot_st}></td>', f'<td class="r"{tot_st}><b>الإجمالي</b></td>',
        *[f'<td class="num"{tot_st}><b>{f(t[k]) or "0"}</b></td>'
          for k in keys]) + "</tr>")

    head1 = cells(thspan("رقم الحساب", rowspan=2),
                  thspan("اسم الحساب", rowspan=2),
                  thspan("رصيد أول المدة", 2), thspan("حركة الفترة", 2),
                  thspan("رصيد آخر المدة", 2))
    head2 = cells(*(thw(x) for x in ("مدين", "دائن") * 3))

    # ملخص الأقسام الرئيسية — ما يقرؤه المراجع أولاً
    summ = ""
    for s_ in tb["sections"]:
        summ += ("<tr>" + cells(
            f'<td>{en(s_["code"])}</td>', f'<td class="r">{s_["name"]}</td>',
            *[f'<td class="num">{f(s_[k])}</td>' for k in keys]) + "</tr>")
    summary = ""
    if summ and int(max_level or 9) > 1:
        summary = ('<br/><div class="note"><b>ملخص بحسب الأقسام الرئيسية'
                   f'</b></div>{TBL}<tr>{head1}</tr><tr>{head2}</tr>'
                   f'{summ}</table>')

    unit = f"الذهب وزناً ({_kunit()})" if gold else "ريال سعودي"
    lvl = "كل الحسابات" if int(max_level or 9) >= 9 else en(max_level)
    meta = _entity_meta([
        ("الفترة من", en(date_from or "بداية الدفاتر")),
        ("إلى", en(date_to or today)),
        ("العملة / الوحدة", unit), ("المستوى", lvl),
        ("عدد الحسابات", en(tb["accounts"]))])
    marks = (("أول المدة", t["ok_open"]), ("حركة الفترة", t["ok_period"]),
             ("آخر المدة", t["ok_close"]))
    per = " · ".join(f"{n}: {'مدين = دائن ✔' if ok else 'غير متوازن ✘'}"
                     for n, ok in marks)
    head_v = ("✔ الميزان متوازن" if t["balanced"]
              else "✘ الميزان غير متوازن — راجع القيود")
    verdict = (f'<div {WIDE} style="margin-top:6px"><b>{head_v}</b> — {per}.'
               ' الأرصدة من دفتر الأستاذ بالقيد المزدوج، والقيود المحذوفة'
               ' مستبعدة.</div>')
    table = f"{TBL}<tr>{head1}</tr><tr>{head2}</tr>{body}</table>"
    return (_header("ميزان المراجعة بالأرصدة والمجاميع", "—",
                    date_to or today, show_meta=False)
            + meta + table + verdict + summary + _sign_block())


def _fp_money(v, gold=False):
    """مبلغ القائمة: السالب بين قوسين والصفر شرطة — كالقوائم المدقّقة."""
    eps = 0.0005 if gold else 0.005
    if abs(v or 0.0) < eps:
        return "—"
    s = _gw(abs(v), 3) if gold else _w(abs(v), 2)
    return f"({s})" if v < 0 else s


def _tpl_income_statement(conn, _id=0, date_from=None, date_to=None,
                          compare=True, show_accounts=False):
    """قائمة الدخل بطريقة وظيفة المصروف (IAS 1) — بمقارنة وإيضاحات.

    من دفتر الأستاذ على أساس الاستحقاق: صافي الإيرادات ← مجمل الربح ←
    الربح التشغيلي ← صافي ربح الفترة. السالب بين قوسين.
    """
    from models import statements
    today = _qd(QtCore.QDate.currentDate())
    d1 = date_from or f"{today[:4]}-01-01"
    d2 = date_to or today
    st = statements.income_statement(conn, d1, d2, bool(compare))
    rows = statements.is_layout(st, bool(show_accounts))
    has_cmp = bool(st["compare_from"])
    ncol = 5 if has_cmp else 3

    body = ""
    for r in rows:
        k = r["kind"]
        if k == "sec":
            body += (f'<tr><td class="r" colspan="{ncol}"'
                     f' style="background-color:#EFE9DC">'
                     f'<b>{r["label"]}</b></td></tr>')
            continue
        vals = [_fp_money(r["cash"])]
        if has_cmp:
            vals.append("" if k == "acct" else _fp_money(r["cash_cmp"]))
        vals.append(_fp_money(r["gold"], True))
        if has_cmp:
            vals.append("" if k == "acct" else _fp_money(r["gold_cmp"], True))
        if k == "line":
            lbl = (f'<td class="r" style="padding-right:18px">'
                   f'{r["label"]}</td>')
            tds = [f'<td class="num">{v}</td>' for v in vals]
        elif k == "acct":
            st_ = ' style="font-size:8pt;color:#555"'
            lbl = (f'<td class="r" style="padding-right:34px;font-size:8pt;'
                   f'color:#555">{en(r["label"])}</td>')
            tds = [f'<td class="num"{st_}>{v}</td>' for v in vals]
        else:
            sty = (' style="background-color:#F2EEE4;border-top:2px solid'
                   ' #333;border-bottom:3px double #333"' if k == "grand"
                   else ' style="border-top:1.5px solid #333"')
            lbl = f'<td class="r"{sty}><b>{r["label"]}</b></td>'
            tds = [f'<td class="num"{sty}><b>{v}</b></td>' for v in vals]
        body += "<tr>" + cells(lbl, *tds) + "</tr>"

    p1 = _nowrap(f"من {en(st['date_from'])} إلى {en(st['date_to'])}")
    p2 = _nowrap(f"من {en(st['compare_from'])} إلى {en(st['compare_to'])}")
    if has_cmp:
        head1 = cells(thspan("البيان", rowspan=2),
                      thspan("النقد — ريال سعودي", 2),
                      thspan(f"الذهب — وزناً ({_kunit()})", 2))
        head2 = cells(thw("الفترة الحالية"), thw("فترة المقارنة"),
                      thw("الفترة الحالية"), thw("فترة المقارنة"))
        head = f"<tr>{head1}</tr><tr>{head2}</tr>"
    else:
        head = ("<tr>" + cells(thw("البيان"), thw("ريال"),
                               thw(f"ذهب ({_kunit()})")) + "</tr>")
    meta = _entity_meta([
        ("الفترة الحالية", p1),
        ("فترة المقارنة", p2 if has_cmp else "—"),
        ("العملة", "ريال سعودي؛ والذهب وزناً بعيار المصنع")])
    ct = st["cash"]["totals"]
    net = ct["net"]
    rev = ct["net_revenue"]
    ratios = ""
    if abs(rev) >= 0.005:
        gm = en(f"{ct['gross'] / rev * 100:,.1f}")
        nm = en(f"{net / rev * 100:,.1f}")
        ratios = f" · هامش مجمل الربح {gm}% · هامش صافي الربح {nm}%"
    verdict = (
        f'<div {WIDE} style="margin-top:6px"><b>صافي '
        f'{"ربح" if net >= 0 else "خسارة"} الفترة: {_w(abs(net), 2)} ريال'
        f'</b>{ratios}<br/>'
        'أُعدّت بطريقة «وظيفة المصروف» وفق معيار المحاسبة الدولي 1 من دفتر'
        ' الأستاذ على أساس الاستحقاق: الإيراد بعد المردودات والخصومات وبلا'
        ' ضريبة القيمة المضافة؛ والمصروف ما حُمّل على حساباته لا ما دُفع'
        ' نقداً؛ وقيد الإقفال السنوي مستبعد. الأرقام بين القوسين سالبة.'
        '</div>')
    table = f"{TBL}{head}{body}</table>"
    return (_header("قائمة الدخل (الأرباح والخسائر)", "—", st["date_to"],
                    show_meta=False)
            + meta + table + verdict + _sign_block())


def _tpl_cash_flow(conn, _id=0, date_from=None, date_to=None, compare=True,
                   method="indirect"):
    """قائمة التدفقات النقدية (IAS 7) — تشغيلية · استثمارية · تمويلية."""
    from models import statements
    today = _qd(QtCore.QDate.currentDate())
    d1 = date_from or f"{today[:4]}-01-01"
    d2 = date_to or today
    cf = statements.cash_flow(conn, d1, d2, bool(compare))
    rows = statements.cf_layout(cf, method or "indirect")
    has_cmp = bool(cf["compare_from"])
    ncol = 3 if has_cmp else 2

    body = ""
    for r in rows:
        k = r["kind"]
        if k == "sec":
            body += (f'<tr><td class="r" colspan="{ncol}"'
                     f' style="background-color:#EFE9DC">'
                     f'<b>{r["label"]}</b></td></tr>')
            continue
        vals = [_fp_money(r["cash"])]
        if has_cmp:
            vals.append(_fp_money(r["cash_cmp"]))
        if k == "line":
            lbl = (f'<td class="r" style="padding-right:18px">'
                   f'{r["label"]}</td>')
            tds = [f'<td class="num">{v}</td>' for v in vals]
        elif k == "bal":
            lbl = f'<td class="r">{r["label"]}</td>'
            tds = [f'<td class="num">{v}</td>' for v in vals]
        else:
            sty = (' style="background-color:#F2EEE4;border-top:2px solid'
                   ' #333;border-bottom:3px double #333"' if k == "grand"
                   else ' style="border-top:1.5px solid #333"')
            lbl = f'<td class="r"{sty}><b>{r["label"]}</b></td>'
            tds = [f'<td class="num"{sty}><b>{v}</b></td>' for v in vals]
        body += "<tr>" + cells(lbl, *tds) + "</tr>"

    p1 = _nowrap(f"من {en(cf['date_from'])} إلى {en(cf['date_to'])}")
    p2 = _nowrap(f"من {en(cf['compare_from'])} إلى {en(cf['compare_to'])}")
    hd = [thw("البيان"), thw("الفترة الحالية — ريال")]
    if has_cmp:
        hd.append(thw("فترة المقارنة — ريال"))
    head = "<tr>" + cells(*hd) + "</tr>"
    meth = ("الطريقة غير المباشرة" if (method or "indirect") == "indirect"
            else "الطريقة المباشرة")
    meta = _entity_meta([
        ("الفترة الحالية", p1), ("فترة المقارنة", p2 if has_cmp else "—"),
        ("العملة", "ريال سعودي"), ("طريقة العرض", meth)])
    t = cf["cur"]["totals"]
    head_v = ("✔ النقد آخر الفترة = أولها + صافي التدفقات، ويطابق رصيد"
              " الصندوق والبنوك في الدفتر" if cf["balanced"] else
              f"✘ فرق {_w(t['diff'], 2)} ريال بين التدفقات والرصيد الدفتري")
    noncash = ""
    if abs(t["noncash"]) >= 0.005:
        noncash = (f"<br/><b>معاملات غير نقدية (IAS 7.43):</b> أصول ثابتة"
                   f" اشتُريت بالأجل ولم يُسدَّد ثمنها في الفترة"
                   f" {_w(t['noncash'], 2)} ريال — لا تظهر تدفقاً.")
    verdict = (
        f'<div {WIDE} style="margin-top:6px"><b>{head_v}</b>{noncash}<br/>'
        'أُعدّت وفق معيار المحاسبة الدولي 7: النقد وما في حكمه هو الصندوق'
        ' والبنوك؛ والتحويل بينهما ليس تدفقاً؛ وثمن الأصول الثابتة استثماري'
        ' ولو سُدِّد عبر حساب المورّد؛ والذهب مخزونٌ لا نقد. الأرقام بين'
        ' القوسين تدفقٌ خارج.</div>')
    table = f"{TBL}{head}{body}</table>"
    return (_header("قائمة التدفقات النقدية", "—", cf["date_to"],
                    show_meta=False)
            + meta + table + verdict + _sign_block())


def _tpl_equity_changes(conn, _id=0, date_from=None, date_to=None,
                        compare=True, dim="cash"):
    """قائمة التغيرات في حقوق الملكية (IAS 1.106) — مكوّنٌ لكل عمود."""
    from models import statements
    today = _qd(QtCore.QDate.currentDate())
    d1 = date_from or f"{today[:4]}-01-01"
    d2 = date_to or today
    eq = statements.equity_changes(conn, d1, d2, bool(compare), dim)
    rows = statements.eq_layout(eq)
    gold = eq["dim"] == "gold"
    keys = [k for k, _t in eq["columns"]] + ["total"]
    ncol = len(keys) + 1

    body = ""
    for r in rows:
        k = r["kind"]
        if k == "sec":
            body += (f'<tr><td class="r" colspan="{ncol}"'
                     f' style="background-color:#2b2723;color:#ffffff">'
                     f'<b>{en(r["label"])}</b></td></tr>')
            continue
        vals = [_fp_money(r["values"].get(c, 0.0), gold) for c in keys]
        if k == "line":
            lbl = (f'<td class="r" style="padding-right:18px">'
                   f'{r["label"]}</td>')
            tds = [f'<td class="num">{v}</td>' for v in vals[:-1]]
            tds.append(f'<td class="num"><b>{vals[-1]}</b></td>')
        else:
            sty = {"grand": ' style="background-color:#F2EEE4;border-top:2px'
                            ' solid #333;border-bottom:3px double #333"',
                   "sub": ' style="border-top:1.5px solid #333"',
                   "bal": ' style="background-color:#EFE9DC"'}.get(k, "")
            lbl = f'<td class="r"{sty}><b>{en(r["label"])}</b></td>'
            tds = [f'<td class="num"{sty}><b>{v}</b></td>' for v in vals]
        body += "<tr>" + cells(lbl, *tds) + "</tr>"

    head = ("<tr>" + cells(thw("البيان"),
                           *[thw(t) for _k, t in eq["columns"]],
                           thw("المجموع")) + "</tr>")
    p1 = _nowrap(f"من {en(eq['date_from'])} إلى {en(eq['date_to'])}")
    p2 = (_nowrap(f"من {en(eq['compare_from'])} إلى {en(eq['compare_to'])}")
          if eq["compare_from"] else "—")
    meta = _entity_meta([
        ("الفترة الحالية", p1), ("فترة المقارنة", p2),
        ("العملة", f"الذهب وزناً ({_kunit()})" if gold else "ريال سعودي")])
    head_v = ("✔ كل عمود: رصيد أول الفترة + الحركات = رصيد آخرها، ويطابق"
              " حقوق الملكية في قائمة المركز المالي" if eq["balanced"]
              else "✘ فرقٌ بين الحركات والأرصدة — راجع القيود")
    verdict = (
        f'<div {WIDE} style="margin-top:6px"><b>{head_v}</b><br/>'
        'أُعدّت وفق معيار المحاسبة الدولي 1 (الفقرة 106): عمودٌ لكل مكوّن'
        ' من حقوق الملكية، وصافي ربح الفترة من قائمة الدخل، والمعاملات مع'
        ' الملاك (رأس المال · جاري الشركاء · التوزيعات) منفصلةً عن الدخل؛'
        ' والأرباح المبقاة تشمل نتائج لم يمرّ عليها الإقفال السنوي بعد.'
        ' الأرقام بين القوسين سالبة.</div>')
    table = f"{TBL}{head}{body}</table>"
    return (_header("قائمة التغيرات في حقوق الملكية", "—", eq["date_to"],
                    show_meta=False)
            + meta + table + verdict + _sign_block())


def _tpl_financial_position(conn, _id=0, as_of=None, compare_to=None):
    """قائمة المركز المالي (الميزانية العمومية) بترتيب IAS 1 — بمقارنة.

    الأصول غير المتداولة ثم المتداولة؛ حقوق الملكية ثم المطلوبات؛ بلا
    مقاصّة بين المدين والدائن من الجهات، والإهلاك مطروحاً من التكلفة،
    وصافي ربح الفترة في حقوق الملكية. السالب بين قوسين.
    """
    from models import statements
    today = _qd(QtCore.QDate.currentDate())
    fp = statements.financial_position(conn, as_of or today, compare_to)
    rows = statements.layout(fp)
    has_cmp = bool(fp["compare_to"])
    ncol = 5 if has_cmp else 3

    body = ""
    for r in rows:
        k = r["kind"]
        if k in ("head", "sec"):
            st = ("background-color:#2b2723;color:#ffffff" if k == "head"
                  else "background-color:#EFE9DC")
            body += (f'<tr><td class="r" colspan="{ncol}" style="{st}">'
                     f'<b>{r["label"]}</b></td></tr>')
            continue
        vals = [_fp_money(r["cash"])]
        if has_cmp:
            vals.append(_fp_money(r["cash_cmp"]))
        vals.append(_fp_money(r["gold"], True))
        if has_cmp:
            vals.append(_fp_money(r["gold_cmp"], True))
        if k in ("line", "net"):
            i0, i1 = ("<i>", "</i>") if k == "net" else ("", "")
            lbl = (f'<td class="r" style="padding-right:18px">'
                   f'{i0}{r["label"]}{i1}</td>')
            tds = [f'<td class="num">{i0}{v}{i1}</td>' for v in vals]
        else:
            st = (' style="background-color:#F2EEE4;border-top:2px solid'
                  ' #333;border-bottom:3px double #333"' if k == "grand"
                  else ' style="border-top:1.5px solid #333"')
            lbl = f'<td class="r"{st}><b>{r["label"]}</b></td>'
            tds = [f'<td class="num"{st}><b>{v}</b></td>' for v in vals]
        body += "<tr>" + cells(lbl, *tds) + "</tr>"

    d1, d2 = en(fp["as_of"]), en(fp["compare_to"])
    if has_cmp:
        head1 = cells(thspan("البيان", rowspan=2),
                      thspan("النقد — ريال سعودي", 2),
                      thspan(f"الذهب — وزناً ({_kunit()})", 2))
        head2 = cells(thw(f"كما في {d1}"), thw(f"كما في {d2}"),
                      thw(f"كما في {d1}"), thw(f"كما في {d2}"))
        head = f"<tr>{head1}</tr><tr>{head2}</tr>"
    else:
        head = ("<tr>" + cells(thw("البيان"), thw(f"ريال — كما في {d1}"),
                               thw(f"ذهب ({_kunit()}) — كما في {d1}"))
                + "</tr>")
    meta = _entity_meta([
        ("كما في", d1), ("المقارنة", d2 if has_cmp else "—"),
        ("العملة", "ريال سعودي؛ والذهب وزناً بعيار المصنع")])
    ct, gt = fp["cash"]["totals"], fp["gold"]["totals"]
    if fp["balanced_cash"] and fp["balanced_gold"]:
        head_v = "✔ القائمة متوازنة: مجموع الأصول = حقوق الملكية + المطلوبات"
    else:
        head_v = (f"✘ فرق: نقد {_w(ct['diff'], 2)} · "
                  f"ذهب {_gw(gt['diff'], 3)}")
    verdict = (
        f'<div {WIDE} style="margin-top:6px"><b>{head_v}</b><br/>'
        'أُعدّت بترتيب معيار المحاسبة الدولي 1 «عرض القوائم المالية»'
        ' المعتمد في المملكة: لا مقاصّة بين أرصدة الجهات المدينة والدائنة؛'
        ' الإهلاك مطروحٌ من التكلفة؛ ونتيجة الإيرادات والمصروفات تظهر في'
        ' حقوق الملكية وحدها (صافي ربح الفترة من بداية السنة المالية).'
        ' الأرقام بين القوسين سالبة.</div>')
    table = f"{TBL}{head}{body}</table>"
    return (_header("قائمة المركز المالي (الميزانية العمومية)", "—",
                    fp["as_of"], show_meta=False)
            + meta + table + verdict + _sign_block())


def _tpl_models_catalog(conn, _id=0, mode="all", sort="az",
                        expanded=None):
    """قالب دليل الموديلات — يحاكي ما يظهر على الشاشة.

    المطوية تُطبع سطراً واحداً بإجمالياتها، والموسّعة بفروعها.
    """
    from models import models_catalog as mc
    expanded = set(expanded or [])
    models = mc.list_models(conn)
    if mode == "in_stock":
        models = [m for m in models if m["in_count"]]
    elif mode == "sold":
        models = [m for m in models if m["out_count"]]

    def _n(m):
        return (m["in_count"] if mode == "in_stock"
                else m["out_count"] if mode == "sold" else m["count"])

    if sort == "za":
        models.sort(key=lambda m: mc.model_key(m["model"]), reverse=True)
    elif sort == "most":
        models.sort(key=lambda m: (-_n(m), mc.model_key(m["model"])))
    elif sort == "least":
        models.sort(key=lambda m: (_n(m), mc.model_key(m["model"])))
    else:
        models.sort(key=lambda m: mc.model_key(m["model"]))

    today = _qd(QtCore.QDate.currentDate())
    labels = {"all": "الكل", "in_stock": "المتاح للبيع",
              "sold": "طرف المناديب"}
    body = ""
    for m in models:
        if mode == "in_stock":
            hn, hw = m["in_count"], m["in_weight"]
        elif mode == "sold":
            hn, hw = m["out_count"], m["out_weight"]
        else:
            hn = m["count"]
            hw = round(m["in_weight"] + m["out_weight"], 2)
        img = "🖼 " if mc.image_path(m["model"]) else ""
        body += ("<tr>" + cells(
            f'<td class="r"><b>◄ {img}الموديل {m["model"]}</b></td>',
            f'<td><b>{en(hn)}</b></td>',
            f'<td><b>{_gw(hw)}</b></td>', '<td></td>') + "</tr>")
        if m["model"] not in expanded:
            continue          # مطويّ على الشاشة → سطر واحد
        for branch, label in (("sold", "طرف المناديب"),
                              ("in_stock", "الموجود (متاح)")):
            if mode == "in_stock" and branch == "sold":
                continue
            if mode == "sold" and branch == "in_stock":
                continue
            items = mc.model_items(conn, m["model"], branch)
            n = m["out_count"] if branch == "sold" else m["in_count"]
            w = m["out_weight"] if branch == "sold" else m["in_weight"]
            body += ("<tr>" + cells(
                f'<td class="r" style="padding-right:14px">'
                f'<b>{label}</b></td>',
                f'<td>{en(n)}</td>', f'<td>{_gw(w)}</td>',
                '<td></td>') + "</tr>")
            for i in items:
                body += ("<tr>" + cells(
                    f'<td class="r" style="padding-right:30px">'
                    f'{en(i["wo"])}</td>',
                    '<td></td>', f'<td>{_gw(i["reg"])}</td>',
                    f'<td>{i["holder"]}  ·  {en(i["date"])}</td>')
                    + "</tr>")
    if not body:
        body = f'<tr><td {TD} colspan="4">لا توجد موديلات</td></tr>'

    tin = sum(m["in_weight"] for m in models)
    tout = sum(m["out_weight"] for m in models)
    head = cells(thw("الموديل / رقم التشغيل", 40), thw("العدد", 12),
                 thw("الوزن المقيد (جم)", 22), thw("الجهة / التاريخ", 26))
    foot = cells(thw(f"الإجمالي — {len(models)} موديل"), thw(""),
                 thw(_gw(tin + tout if mode == "all"
                        else tin if mode == "in_stock" else tout)),
                 thw(""))
    meta = (f'<div {WIDE}>العرض: <b>{labels.get(mode, mode)}</b>'
            f' &nbsp;·&nbsp; المعروض موسّعاً: '
            f'<b>{en(len(expanded))}</b> موديل</div>')
    table = f"{TBL}<tr>{head}</tr>{body}<tr>{foot}</tr></table>"
    return (_slim_title("دليل الموديلات", today)
            + meta + table)


def _tpl_models_received(conn, _id=0, date_from=None, date_to=None,
                         mode="all", sort="az"):
    """قالب «الوارد من التصنيع بتاريخ» — موديلاً موديلاً ومع من هو.

    الورقة تجيب سؤالاً واحداً: ما الذي ورد في ذلك اليوم، وأين كل
    قطعةٍ منه **اليوم** — في الخزنة أم عند جهة.
    """
    from models import models_catalog as mc
    res = mc.received(conn, date_from, date_to)
    today = _qd(QtCore.QDate.currentDate())
    labels = {"all": "الكل", "in_stock": "الباقي بالخزنة",
              "sold": "الخارج للجهات"}

    models = []
    for m in res["models"]:
        items = [i for i in m["items"]
                 if mode == "all"
                 or (mode == "in_stock" and i["safe"])
                 or (mode == "sold" and not i["safe"])]
        if not items:
            continue
        g = dict(m)
        g["items"] = items
        g["count"] = len(items)
        g["weight"] = round(sum(i["reg"] for i in items), 2)
        g["in_count"] = sum(1 for i in items if i["safe"])
        g["out_count"] = g["count"] - g["in_count"]
        models.append(g)

    if sort == "za":
        models.sort(key=lambda m: mc.model_key(m["model"]), reverse=True)
    elif sort == "most":
        models.sort(key=lambda m: (-m["count"], mc.model_key(m["model"])))
    elif sort == "least":
        models.sort(key=lambda m: (m["count"], mc.model_key(m["model"])))
    else:
        models.sort(key=lambda m: mc.model_key(m["model"]))

    body = ""
    for m in models:
        where = []
        if m["in_count"]:
            where.append(f'بالخزنة {en(m["in_count"])}')
        if m["out_count"]:
            where.append(f'عند الجهات {en(m["out_count"])}')
        body += ("<tr>" + cells(
            f'<td class="r"><b>◄ الموديل {m["model"]}</b></td>',
            f'<td><b>{en(m["count"])}</b></td>',
            f'<td><b>{_gw(m["weight"])}</b></td>',
            f'<td>{"  ·  ".join(where)}</td>') + "</tr>")
        for i in m["items"]:
            tail = f'{i["holder"]}  ·  {en(i["date"])}'
            if i["bulk"]:
                tail += "  ·  رصيد مجمّع"
            body += ("<tr>" + cells(
                f'<td class="r" style="padding-right:22px">'
                f'{en(i["wo"])}</td>',
                '<td></td>', f'<td>{_gw(i["reg"])}</td>',
                f'<td>{tail}</td>') + "</tr>")
    if not body:
        body = (f'<tr><td {TD} colspan="4">'
                f'لا وارد من التصنيع في هذه الفترة</td></tr>')

    n = sum(m["count"] for m in models)
    w = round(sum(m["weight"] for m in models), 2)
    n_in = sum(m["in_count"] for m in models)
    span = (res["date_from"] if res["date_from"] == res["date_to"]
            else f'{en(res["date_from"])} ← {en(res["date_to"])}')
    head = cells(thw("الموديل / رقم التشغيل", 38), thw("العدد", 10),
                 thw("الوزن المقيد (جم)", 22),
                 thw("مع من الآن · تاريخ الوارد", 30))
    foot = cells(thw(f"الإجمالي — {en(len(models))} موديل"),
                 thw(en(n)), thw(_gw(w)),
                 thw(f"بالخزنة {en(n_in)} · عند الجهات {en(n - n_in)}"))
    meta = (f'<div {WIDE}>الوارد من التصنيع في: <b>{en(span)}</b>'
            f' &nbsp;·&nbsp; العرض: <b>{labels.get(mode, mode)}</b></div>')
    table = f"{TBL}<tr>{head}</tr>{body}<tr>{foot}</tr></table>"
    return (_slim_title("الوارد من التصنيع بتاريخ", today)
            + meta + table)


def _img_uri(path):
    """صورة الموديل كما هي — بلا تصغير، فتُطبع بدقّتها الأصلية."""
    import base64
    try:
        ext = str(path).rsplit(".", 1)[-1].lower()
        mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png",
                "webp": "webp", "bmp": "bmp"}.get(ext, "png")
        raw = open(str(path), "rb").read()
        return ("data:image/" + mime + ";base64,"
                + base64.b64encode(raw).decode("ascii"))
    except Exception:
        return ""


# شبكة صور الوارد: خليةٌ ثابتة الارتفاع، لا تتمدّد بعدد القطع.
# **لماذا ثابتة**: لو تُرك الجدول يطول بطول قائمة أرقام التشغيل
# لدفع الموديلَ التالي إلى نصف صفحة، فتخرج الورقة بثلاث صورٍ وربع
# وينتقل الباقي بلا نظام. فالخلية تأخذ مساحتها كاملةً، والزائد عن
# سعتها يُختصر بسطر «+ كذا قطعة» — فتبقى الأربع صور في كل صفحة.
# الارتفاعات مقيسةٌ لا مقدَّرة: صفحةُ A4 بهوامش 8 مم تُعطي 281 مم،
# وترويسةُ المستند تأكل ~44 مم من الصفحة الأولى — فيبقى للشبكة 237
# مم، أي 118 مم لكل صفّ. أُخذ 116 مم احتياطاً لفروق الخطوط بين
# الأجهزة، فتخرج الأربع صور في الصفحة الأولى كما في التي بعدها.
PHOTO_ROWS = 6            # أسطر جدول القطع الظاهرة في كل خلية

RECV_PHOTO_CSS = """
<style>
  table.pgrid { table-layout: fixed; width: 100%;
                border-collapse: separate; }
  table.pgrid td.cell {
    width: 50%; height: 128mm; vertical-align: top; padding: 2mm;
  }
  /* البطاقة عمودٌ مرن: الجدول يأخذ ما يحتاجه، والصورةُ تبتلع ما
     بقي. فالموديل ذو القطعتين تكبر صورتُه بدل أن يُترك أسفلَه
     بياضٌ، والذو ستٍّ تصغر قليلاً — والارتفاع الخارجي واحدٌ في
     الحالين فتبقى الشبكة منتظمة. */
  .card { border: 1px solid #D8CDB4; border-radius: 5px;
          padding: 2mm; background: #FFFFFF; height: 122mm;
          display: flex; flex-direction: column; }
  .imgbox { flex: 1 1 auto; min-height: 42mm; width: 100%;
            display: flex; align-items: center; justify-content: center;
            background: #FCFAF5; border-radius: 3px; overflow: hidden; }
  .imgbox img { max-width: 97%; max-height: 100%; object-fit: contain; }
  .noimg { color: #9A8C6E; font-size: 9pt; }
  .cap { margin: 1.5mm 0 1mm; font-size: 10.5pt; font-weight: bold;
         color: #4A3A1E; text-align: center; }
  .sub { font-size: 8pt; color: #6B5B3A; text-align: center;
         margin-bottom: 1mm; }
  table.wos { width: 100%; border-collapse: collapse;
              font-size: 7.6pt; table-layout: fixed; }
  table.wos th { background: #EFE9DC; color: #4A3A1E; font-weight: bold;
                 border: 1px solid #DCD3BE; padding: 0.6mm 1mm; }
  table.wos td { border: 1px solid #E6DFCB; padding: 0.6mm 1mm;
                 text-align: center; }
  table.wos td.h { text-align: center; }
  .more { font-size: 7.4pt; color: #6B5B3A; text-align: center;
          padding-top: 0.8mm; }
</style>
"""


def _tpl_models_received_photos(conn, _id=0, date_from=None, date_to=None,
                                mode="all", sort="az", per_page=4):
    """صور الوارد من التصنيع — أربع في كل صفحة A4، وتحتها بياناتها.

    تحت كل صورة: اسم الموديل وعددُ قطعه ووزنُها، ثم جدولٌ بأرقام
    التشغيل ووزن كلٍّ ومَن هي عنده الآن.

    **الموديل بلا صورة يُطبع أيضاً** بإطارٍ فارغ: الورقة تقرير وارد
    قبل أن تكون ألبوم صور، وإسقاطُ موديلٍ لأن صورته ناقصة يجعل
    الجمع لا يساوي الوارد.
    """
    from models import models_catalog as mc
    res = mc.received(conn, date_from, date_to)
    today = _qd(QtCore.QDate.currentDate())

    picked = []
    for m in res["models"]:
        items = [i for i in m["items"]
                 if mode == "all"
                 or (mode == "in_stock" and i["safe"])
                 or (mode == "sold" and not i["safe"])]
        if not items:
            continue
        picked.append({
            "model": m["model"], "items": items, "count": len(items),
            "weight": round(sum(i["reg"] for i in items), 2),
            "in_count": sum(1 for i in items if i["safe"]),
        })
    # ورقة الصور بأسماء الموديلات دائماً — ترتيبٌ طبيعي (A1 ← A2 ← B1)
    picked.sort(key=lambda m: mc.model_key(m["model"]))

    span = (en(res["date_from"]) if res["date_from"] == res["date_to"]
            else f'{en(res["date_from"])} ← {en(res["date_to"])}')
    if not picked:
        return (_slim_title("صور الوارد من التصنيع", today)
                + f'<div style="text-align:center;padding:40px">'
                  f'لا وارد من التصنيع في {span}</div>')

    # يومٌ واحد؟ فلا داعي لعمود تاريخٍ يكرّر ما في العنوان — تُوسَّع
    # به أعمدةُ رقم التشغيل والجهة، وهي ما جاء القارئ من أجله.
    one_day = len({i["date"] for m in picked for i in m["items"]}) <= 1

    cards = []
    for m in picked:
        uri = _img_uri(mc.image_path(m["model"]) or "")
        img = (f'<img src="{uri}" />' if uri
               else '<span class="noimg">لا صورة لهذا الموديل</span>')
        shown = m["items"][:PHOTO_ROWS]
        rows = "".join(
            "<tr>" + f'<td class="h">{en(i["wo"])}</td>'
            + f'<td>{_gw(i["reg"])}</td>'
            + f'<td class="h">{i["holder"]}</td>'
            + ("" if one_day else f'<td>{en(i["date"])}</td>') + "</tr>"
            for i in shown)
        extra = len(m["items"]) - len(shown)
        more = (f'<div class="more">+ {en(extra)} قطعة أخرى — '
                f'تفصيلُها في ورقة «الوارد»</div>' if extra > 0 else "")
        out_n = m["count"] - m["in_count"]
        where = []
        if m["in_count"]:
            where.append(f'بالخزنة {en(m["in_count"])}')
        if out_n:
            where.append(f'عند الجهات {en(out_n)}')
        cards.append(
            '<td class="cell"><div class="card">'
            f'<div class="imgbox">{img}</div>'
            f'<div class="cap">الموديل {m["model"]}  ·  '
            f'{en(m["count"])} قطعة  ·  {_gw(m["weight"])} جم</div>'
            f'<div class="sub">{"  ·  ".join(where)}</div>'
            '<table class="wos"><tr>'
            + ('<th style="width:32%">رقم التشغيل</th>'
               '<th style="width:22%">الوزن</th>'
               '<th style="width:46%">مع من</th>' if one_day else
               '<th style="width:26%">رقم التشغيل</th>'
               '<th style="width:20%">الوزن</th>'
               '<th style="width:32%">مع من</th>'
               '<th style="width:22%">الوارد</th>')
            + "</tr>"
            f'{rows}</table>{more}</div></td>')

    per_page = max(2, int(per_page or 4))
    cols = 2
    pages = ""
    total_pages = (len(cards) + per_page - 1) // per_page
    for pg in range(total_pages):
        chunk = cards[pg * per_page:(pg + 1) * per_page]
        while len(chunk) % cols:
            chunk.append('<td class="cell"></td>')
        trs = "".join(
            "<tr>" + "".join(chunk[i:i + cols]) + "</tr>"
            for i in range(0, len(chunk), cols))
        brk = ' style="page-break-before:always"' if pg else ""
        pages += ('<table class="pgrid" width="100%" cellspacing="0"'
                  ' cellpadding="0"' + brk + ">" + trs + "</table>")

    n = sum(m["count"] for m in picked)
    w = round(sum(m["weight"] for m in picked), 2)
    meta = (f'<div {WIDE}>الوارد من التصنيع في: <b>{span}</b>'
            f' &nbsp;·&nbsp; <b>{en(len(picked))}</b> موديل · '
            f'<b>{en(n)}</b> قطعة · <b>{_gw(w)}</b> جم'
            f' &nbsp;·&nbsp; الصفحات: <b>{en(total_pages)}</b></div>')
    return (_slim_title("صور الوارد من التصنيع", today)
            + RECV_PHOTO_CSS + meta + pages)


def _model_photo_pages(models, per_page=4):
    """شبكة صور الموديلات: خليةٌ لكل رقم موديل — صورته، وتحتها أرقام
    التشغيل بوزنها وحركتها. تُعيد (الصفحات، عددها)."""
    from models import models_catalog as mc
    cards = []
    for m in models:
        uri = _img_uri(mc.image_path(m["model"]) or "")
        img = (f'<img src="{uri}" />' if uri
               else '<span class="noimg">لا صورة لهذا الموديل</span>')
        shown = m["items"][:PHOTO_ROWS]
        rows = "".join(
            "<tr>" + f'<td class="h">{en(i["wo"])}</td>'
            + f'<td>{_gw(i["weight"])}</td>'
            + f'<td class="h">{i["kind"]}</td>'
            + f'<td>{en(i["date"])}</td></tr>'
            for i in shown)
        extra = len(m["items"]) - len(shown)
        more = (f'<div class="more">+ {en(extra)} قطعة أخرى</div>'
                if extra > 0 else "")
        sub = f'خرج {en(m["sold"])}'
        if m["returned"]:
            sub += f'  ·  رجع {en(m["returned"])}'
        cards.append(
            '<td class="cell"><div class="card">'
            f'<div class="imgbox">{img}</div>'
            f'<div class="cap">الموديل {m["model"]}  ·  '
            f'{en(m["net_count"])} قطعة  ·  {_gw(m["weight"])} {_kunit()}'
            f'</div><div class="sub">{sub}</div>'
            '<table class="wos"><tr>'
            '<th style="width:30%">رقم التشغيل</th>'
            '<th style="width:22%">الوزن</th>'
            '<th style="width:20%">الحركة</th>'
            '<th style="width:28%">التاريخ</th></tr>'
            f'{rows}</table>{more}</div></td>')
    per_page = max(2, int(per_page or 4))
    cols = 2
    pages = ""
    total_pages = (len(cards) + per_page - 1) // per_page
    for pg in range(total_pages):
        chunk = cards[pg * per_page:(pg + 1) * per_page]
        while len(chunk) % cols:
            chunk.append('<td class="cell"></td>')
        trs = "".join("<tr>" + "".join(chunk[i:i + cols]) + "</tr>"
                      for i in range(0, len(chunk), cols))
        brk = ' style="page-break-before:always"' if pg else ""
        pages += ('<table class="pgrid" width="100%" cellspacing="0"'
                  ' cellpadding="0"' + brk + ">" + trs + "</table>")
    return pages, total_pages


def _group_models(rows):
    """أسطرٌ (موديل، رقم تشغيل، وزن، نوع، تاريخ) ← موديلات بقطعها."""
    out = {}
    for r in rows:
        m = out.setdefault(r["m"], {"model": r["m"], "items": [],
                                    "sold": 0, "returned": 0,
                                    "weight": 0.0})
        sale = r["k"] == "sale"
        wt = float(r["wt"] or 0.0)
        m["items"].append({"wo": r["wo"] or "—", "weight": wt,
                           "kind": "بيع" if sale else "مرتجع",
                           "date": r["d"]})
        m["sold" if sale else "returned"] += 1
        m["weight"] += wt if sale else -wt
    res = list(out.values())
    for m in res:
        m["weight"] = round(m["weight"], 3)
        m["net_count"] = m["sold"] - m["returned"]
    return res


def _tpl_dossier_models(conn, entity_id=0, date_from=None, date_to=None,
                        per_page=4):
    """صور موديلات الجهة في الفترة: صورةٌ لكل رقم موديل، وتحتها أرقام
    التشغيل بوزنها وحركتها (بيع/مرتجع) — على شبكة ورقة الوارد نفسها."""
    from models import dossier as ds
    from models import models_catalog as mc
    ent = conn.execute("SELECT name FROM entities WHERE id=?",
                       (entity_id,)).fetchone()
    if not ent:
        raise ValueError("الجهة غير موجودة")
    today = _qd(QtCore.QDate.currentDate())
    models = ds.model_items(conn, entity_id, date_from, date_to)
    models.sort(key=lambda m: mc.model_key(m["model"]))
    span = (f'{en(date_from or "—")} ← {en(date_to or "—")}')
    title = f"موديلات {ent['name']}"
    if not models:
        return (_slim_title(title, today)
                + f'<div style="text-align:center;padding:40px">'
                  f'لا موديلات لهذه الجهة في {span}</div>')
    pages, _n = _model_photo_pages(models, per_page)
    n = sum(m["net_count"] for m in models)
    w = round(sum(m["weight"] for m in models), 3)
    meta = (f'<div {WIDE}>الفترة: <b>{span}</b> &nbsp;·&nbsp; '
            f'<b>{en(len(models))}</b> موديل · صافي <b>{en(n)}</b> قطعة · '
            f'<b>{_gw(w)}</b> {_kunit()}</div>')
    return _slim_title(title, today) + RECV_PHOTO_CSS + meta + pages


def _tpl_invoice_models(conn, invoice_id=0, per_page=4):
    """صور موديلات فاتورةٍ واحدة — صورةٌ لكل رقم موديل وتحتها أرقام
    تشغيله في الفاتورة بوزنها. تُفتح من معاينة كشف الحساب."""
    from models import models_catalog as mc
    inv = conn.execute(
        "SELECT i.invoice_no, i.invoice_date, i.kind, e.name"
        " FROM invoices i LEFT JOIN entities e ON e.id=i.customer_id"
        " WHERE i.id=?", (invoice_id,)).fetchone()
    if not inv:
        raise ValueError("الفاتورة غير موجودة")
    rows = conn.execute(
        "SELECT COALESCE(NULLIF(TRIM(w.model_no),''),'— بلا موديل —') m,"
        " w.work_order_no wo, it.registered_weight wt, i.kind k,"
        " i.invoice_date d FROM invoice_items it"
        " JOIN invoices i ON i.id=it.invoice_id"
        " LEFT JOIN work_orders w ON w.id=it.work_order_id"
        " WHERE it.invoice_id=? ORDER BY m, w.work_order_no",
        (invoice_id,)).fetchall()
    models = _group_models(rows)
    models.sort(key=lambda m: mc.model_key(m["model"]))
    kind = "فاتورة مبيعات" if inv["kind"] == "sale" else "فاتورة مرتجع"
    title = f"موديلات {kind} {inv['invoice_no'] or ''}"
    if not models:
        return (_slim_title(title, inv["invoice_date"])
                + '<div style="text-align:center;padding:40px">'
                  'لا أصناف في هذه الفاتورة</div>')
    pages, _n = _model_photo_pages(models, per_page)
    n = sum(len(m["items"]) for m in models)
    w = round(sum(abs(m["weight"]) for m in models), 3)
    meta = (f'<div {WIDE}>الجهة: <b>{inv["name"] or "—"}</b> &nbsp;·&nbsp; '
            f'<b>{en(len(models))}</b> موديل · <b>{en(n)}</b> قطعة · '
            f'<b>{_gw(w)}</b> {_kunit()}</div>')
    return (_slim_title(title, inv["invoice_date"]) + RECV_PHOTO_CSS
            + meta + pages)


def _tpl_dash_panel(conn, _id=0, title="", kind="accounts", codes=None,
                    ratios=None, date_from=None, date_to=None,
                    search=""):
    """قالب لوحة التحكم — مطابق لما يظهر على الشاشة."""
    from models import dash_panels as dp
    from services import karat_view
    today = _qd(QtCore.QDate.currentDate())

    if kind == "scrap":
        rows = dp.scrap_rows(conn)
        body = "".join(
            "<tr>" + cells(f'<td class="r">عيار {en(r["karat"])}</td>',
                           f'<td>{_w(r["actual"])}</td>',
                           f'<td>{_gw(r["eq18"])}</td>') + "</tr>"
            for r in rows)
        ta = round(sum(r["actual"] for r in rows), 3)
        te = round(sum(r["eq18"] for r in rows), 3)
        head = cells(thw("العيار", 34), thw("الوزن الفعلي (جم)", 33),
                     thw(f"المكافئ ({_kunit()})", 33))
        foot = cells(thw("الإجمالي"), thw(_w(ta)), thw(_gw(te)))
        table = f"{TBL}<tr>{head}</tr>{body}<tr>{foot}</tr></table>"
        note = (f'<div {WIDE}>صندوق الكسر حساب واحد (1310) يضمّ '
                f'الأعيرة الأربعة؛ الرصيد المحاسبي بمكافئ 18.</div>')
        return (_header(f"لوحة التحكم — {title}", "—", today,
                        show_meta=False) + note + table)

    if kind == "stock":
        rows = dp.stock_rows(conn, search or "")
        t = dp.stock_totals(rows)
        body = "".join(
            "<tr>" + cells(
                f'<td class="r">{en(r["wo"])}'
                + ("  (مجمّع)" if r["bulk"] else "") + "</td>",
                f'<td class="r">{r["model"]}</td>',
                f'<td>{_gw(r["gold"])}</td>', f'<td>{_gw(r["small"])}</td>',
                f'<td>{_gw(r["big"])}</td>', f'<td>{_gw(r["after"])}</td>',
                f'<td>{_gw(r["reg"])}</td>',
                f'<td>{_gw(r["standing"])}</td>') + "</tr>"
            for r in rows)
        if not body:
            body = f'<tr><td {TD} colspan="8">لا أطقم متاحة للبيع</td></tr>'
        u = karat_view.unit()
        head = cells(thw("رقم التشغيل", 14), thw("الموديل", 16),
                     thw(f"الذهب ({u})", 11), thw(f"الفصوص ({u})", 10),
                     thw(f"الأحجار ({u})", 10),
                     thw(f"بعد الخصم ({u})", 11),
                     thw(f"الوزن المقيد ({u})", 14),
                     thw(f"الذهب القائم ({u})", 14))
        foot = cells(thw(f"الإجمالي — {en(t['count'])} طقم"),
                     thw(f"{en(t['models'])} موديل"),
                     thw(_gw(t["gold"])), thw(_gw(t["small"])),
                     thw(_gw(t["big"])), thw(_gw(t["after"])),
                     thw(_gw(t["reg"])), thw(_gw(t["standing"])))
        table = f"{TBL}<tr>{head}</tr>{body}<tr>{foot}</tr></table>"
        note = (f'<div {WIDE}>المتاح للبيع الآن — ما لم يخرج بفاتورة. '
                f'الوزن المقيد هو الأثر المالي والمخزني، والذهب القائم '
                f'للإحصاء وحده.'
                + (f' &nbsp;·&nbsp; بحث: <b>{en(search)}</b>'
                   if search else "") + '</div>')
        return (_header(f"لوحة التحكم — {title}", "—", today,
                        show_meta=False) + note + table)

    # ══ الطباعة تُفصّل أكثر من الشاشة ══
    # الشاشة تعرض الرصيد وحده (نظرة سريعة)، والورقة تُفصّل المدين
    # والدائن معه — فالورقة مستند مراجعة يُدقّق عليه، ورؤية حجم
    # الحركة فيه ضرورية لا مجرد محصّلتها.
    rows = dp.account_rows(conn, list(codes or []), date_from, date_to)
    body = "".join(
        "<tr>" + cells(
            f'<td class="r">{r["code"]} — {r["name"]}</td>',
            f'<td>{_gw(r["gold_debit"])}</td>',
            f'<td>{_gw(r["gold_credit"])}</td>',
            f'<td>{_gw(r["gold_balance"])}</td>',
            f'<td>{_w(r["cash_debit"], 2)}</td>',
            f'<td>{_w(r["cash_credit"], 2)}</td>',
            f'<td>{_w(r["cash_balance"], 2)}</td>') + "</tr>"
        for r in rows)
    if not body:
        body = (f'<tr><td {TD} colspan="7">لا توجد حسابات في هذه '
                f'اللوحة</td></tr>')
    t = dp.totals(rows)
    head = cells(thw("الاسم", 25), thw("مدين ذهب", 12),
                 thw("دائن ذهب", 12), thw("رصيد ذهب", 13),
                 thw("مدين نقد", 12), thw("دائن نقد", 12),
                 thw("رصيد نقد", 14))
    foot = cells(thw("الإجمالي"), thw(_gw(t["gold_debit"])),
                 thw(_gw(t["gold_credit"])), thw(_gw(t["gold_balance"])),
                 thw(_w(t["cash_debit"], 2)),
                 thw(_w(t["cash_credit"], 2)),
                 thw(_w(t["cash_balance"], 2)))
    table = f"{TBL}<tr>{head}</tr>{body}<tr>{foot}</tr></table>"

    # أشرطة النسب أسفل الجدول — كما تظهر على الشاشة
    bars = dp.ratio_bars(rows, ratios or [])
    extra = ""
    if bars:
        items = ""
        for b in bars:
            pct = "—" if b["pct"] is None else "{:,.2f}%".format(b["pct"])
            mode = ("عكسية" if b.get("mode") == "inverse" else "مباشرة")
            detail = "{} · {} {} ÷ {} {}".format(
                mode, b["second_name"], _w(b["second_value"]),
                b["first_name"], _w(b["first_value"]))
            c1 = '<td class="r"><b>' + str(b["title"]) + "</b></td>"
            c2 = "<td><b>" + pct + "</b></td>"
            c3 = '<td class="r">' + detail + "</td>"
            items += "<tr>" + cells(c1, c2, c3) + "</tr>"
        vals = [b["pct"] for b in bars if b["pct"] is not None]
        tot = ("{:,.1f}%".format(sum(vals)) if vals else "—")
        items += ("<tr>" + cells(thw("إجمالي النسب"), thw(tot), thw(""))
                  + "</tr>")
        rhead = cells(thw("النسبة", 30), thw("القيمة", 18),
                      thw("التفصيل", 52))
        extra = ('<table class="items totals" width="100%" cellspacing="0"'
                 ' cellpadding="6" style="margin-top:8px">'
                 + "<tr>" + rhead + "</tr>" + items + "</table>")
    span = ""
    if date_from or date_to:
        span = (f'<div {WIDE}>الفترة: <b>{en(date_from or "البداية")}</b>'
                f' إلى <b>{en(date_to or "الآن")}</b></div>')
    return (_header(f"لوحة التحكم — {title}", "—", today,
                    show_meta=False) + span + table + extra)


def _slim_title(title, date):
    """سطرُ عنوانٍ رفيع لقوالب دليل الموديلات — بلا ترويسة المصنع وشعاره.

    ورقة الموديلات للصور والأرقام: الترويسة الكاملة كانت تأكل ربع
    الصفحة الأولى. سطرٌ واحد يكفي ليُعرف ما في الورقة وتاريخها، ويرتفع
    ما تحته ليأخذ المساحة.
    """
    return (
        '<table width="100%" cellspacing="0" cellpadding="2" style="'
        'border-bottom:1.5px solid #C9A227;margin-bottom:2mm"><tr>'
        f'<td style="text-align:right;font-size:12pt;font-weight:bold">'
        f'{title}</td><td style="text-align:left;font-size:9.5pt;'
        f'color:#6B5A2E">{en(date)}</td></tr></table>')


def photo_grid(n, width_mm=190.0, height_mm=258.0, caption_mm=14.0):
    """أنسب شبكةٍ لـ`n` صورة في صفحة: (أعمدة، صفوف، عرض الخلية، ارتفاعها).

    **الأنسب = أكبر صورة**: لكل عددِ أعمدةٍ ممكن تُحسب مساحة الصورة
    (الأصغر من عرض الخلية وارتفاعها بعد التعليق)، ويُختار ما يُكبّرها.
    فثمانٍ في صفحةٍ طولية تخرج ٢×٤ لا ٣×٣ بخانةٍ فارغة، واثنتا عشرة
    ٣×٤ — والصورة في كلٍّ بأكبر مقاسٍ يسمح به الورق.
    """
    n = max(1, int(n or 1))
    best = None
    for cols in range(1, n + 1):
        rows = -(-n // cols)
        cw, ch = width_mm / cols, height_mm / rows
        side = min(cw, ch - caption_mm)
        # التعادل يُحسم بالأقلّ فراغاً
        key = (round(side, 2), -(cols * rows - n))
        if best is None or key > best[0]:
            best = (key, cols, rows, cw, ch)
    _, cols, rows, cw, ch = best
    return cols, rows, cw, ch


def _tpl_model_photos(conn, _id=0, min_count=3, mode="all", sort="az",
                      per_page=4):
    """ورقة صور الموديلات — بالعدد الذي يختاره المستخدم في كل صفحة.

    تُطبع صور الموديلات التي بلغ عددها الحدّ المطلوب، و**عدد الصور في
    الصفحة يختاره المستخدم** (٤ افتراضاً): فتُحسب له أنسب شبكةٍ تملأ
    صفحة A4 (`photo_grid`) وتُصغَّر الصور معها بتناسبها — ثمانٍ في
    الصفحة تخرج ٢×٤ بصورٍ كبيرةٍ واضحة لا مضغوطة.

    وتحت كل صورة: اسم الموديل، وكم منه **بالخزنة**، وكم **عند المناديب**.
    """
    import base64
    from models import models_catalog as mc

    models = mc.list_models(conn)
    if mode == "in_stock":
        models = [m for m in models if m["in_count"]]
    elif mode == "sold":
        models = [m for m in models if m["out_count"]]

    def _n(m):
        return (m["in_count"] if mode == "in_stock"
                else m["out_count"] if mode == "sold" else m["count"])

    # الحدّ الأدنى للعدد + وجود صورة
    picked = []
    for m in models:
        if _n(m) < int(min_count or 0):
            continue
        p_img = mc.image_path(m["model"])
        if p_img is None:
            continue
        picked.append((m, p_img, _n(m)))

    # **ورقة الصور بأسماء الموديلات دائماً**: A1 ← A2 ← A3 ← B1 — ترتيبٌ
    # طبيعي تُقرأ فيه الأرقام أرقاماً (فلا يسبق A10 الموديلَ A2). من
    # يقلّب الورقة يبحث عن موديلٍ باسمه، لا بعدد قطعه.
    picked.sort(key=lambda x: mc.model_key(x[0]["model"]))

    today = _qd(QtCore.QDate.currentDate())
    if not picked:
        body = ('<div style="text-align:center;padding:40px">'
                'لا توجد موديلات بصور تبلغ الحدّ المطلوب '
                f'({en(min_count)} قطع فأكثر)</div>')
        return _slim_title("صور الموديلات", today) + body

    def _data_uri(path):
        try:
            ext = str(path).rsplit(".", 1)[-1].lower()
            mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png",
                    "webp": "webp", "bmp": "bmp"}.get(ext, "png")
            raw = open(str(path), "rb").read()
            return ("data:image/" + mime + ";base64,"
                    + base64.b64encode(raw).decode("ascii"))
        except Exception:
            return ""

    per_page = max(1, min(int(per_page or 4), 60))
    cols, rows, cw, ch = photo_grid(per_page)
    # الخط يصغر مع الخلية فلا يزاحم الصورة — ولا ينزل عن المقروء
    fs = max(8.5, min(13.0, cw / 6.0))
    cap_mm = max(10.0, fs * 1.1)
    img_h = max(15.0, ch - cap_mm - 4)

    cells_html = []
    for m, p_img, n in picked:
        uri = _data_uri(p_img)
        if not uri:
            continue
        cells_html.append(
            '<td class="ph">'
            '<div class="phbox"><img src="' + uri + '" /></div>'
            '<div class="phcap"><b class="mn">' + str(m["model"])
            + '</b><br/>'
            'بالخزنة: <b>' + en(m["in_count"]) + '</b>'
            ' &nbsp;·&nbsp; عند المناديب: <b>' + en(m["out_count"])
            + '</b></div></td>')

    pages = ""
    total_pages = (len(cells_html) + per_page - 1) // per_page
    for pg in range(total_pages):
        chunk = cells_html[pg * per_page:(pg + 1) * per_page]
        while len(chunk) < rows * cols:
            chunk.append('<td class="ph"></td>')
        brk = ' style="page-break-before:always"' if pg else ""
        trs = "".join(
            "<tr>" + "".join(chunk[r * cols:(r + 1) * cols]) + "</tr>"
            for r in range(rows)
            if any("phbox" in c for c in chunk[r * cols:(r + 1) * cols])
            or r == 0)
        pages += (
            '<table class="photos" width="100%" cellspacing="0"'
            ' cellpadding="0"' + brk + ">" + trs + "</table>")

    css = f"""
    <style>
      table.photos {{ table-layout: fixed; width: 100%; }}
      table.photos td.ph {{
        width: {100.0 / cols:.3f}%; height: {ch:.1f}mm; vertical-align: top;
        padding: 1.5mm; text-align: center;
      }}
      .phbox {{
        height: {img_h:.1f}mm; border: 1px solid #D8CDB4; border-radius: 4px;
        display: flex; align-items: center; justify-content: center;
        background: #FFFFFF; overflow: hidden;
      }}
      .phbox img {{ max-width: 96%; max-height: {img_h - 2:.1f}mm;
                   object-fit: contain; }}
      .phcap {{
        margin-top: 1mm; font-size: {fs:.1f}pt; line-height: 1.25;
        color: #4A3A1E;
      }}
      .phcap b.mn {{ font-size: {fs * 1.12:.1f}pt; }}
    </style>
    """
    meta = ('<div ' + WIDE + '>الحدّ الأدنى للعدد: <b>'
            + en(min_count) + '</b> &nbsp;·&nbsp; صور في الصفحة: <b>'
            + en(per_page) + '</b> (' + en(cols) + '×' + en(rows)
            + ') &nbsp;·&nbsp; موديلات مطبوعة: <b>'
            + en(len(cells_html)) + '</b> &nbsp;·&nbsp; الصفحات: <b>'
            + en(total_pages) + "</b></div>")
    return (_slim_title("صور الموديلات", today)
            + css + meta + pages)


# خريطة نوع المستند ← قالبه. تُبنى من الدوال الموجودة فعلاً،
# فلا تنكسر إن أُعيد ترتيب الملف.
def _tpl_aging(conn, _id=0, entity_type="customer", as_of=None, dim="both",
               only=None):
    """تقرير أعمار الديون — الأقدم أولاً وصف إجمالي بارز.

    `only` معرّفات جهات بعينها: الورقة تطابق ما رُشّح على الشاشة، فلا
    يُطبع تقريرٌ يخالف ما أمام المستخدم.
    """
    from models import aging
    from services import karat_view
    rows = aging.report(conn, entity_type, as_of)
    if only:
        chosen = set(only)
        rows = [r for r in rows if r["entity_id"] in chosen]
    t = aging.totals(rows)
    today = _qd(QtCore.QDate.currentDate())
    label = {"customer": "العملاء", "supplier": "الموردين",
             "other": "جهات أخرى"}.get(entity_type, entity_type)
    u = karat_view.unit()

    show_cash = dim in ("both", "cash")
    show_gold = dim in ("both", "gold")

    # ══ رأسٌ من صفّين ══
    # صفّ علويٌّ يجمع أعمدة **الذهب** تحت عنوان واحد، وآخر يجمع
    # أعمدة **الأجور** — فالعين تعرف أيّ وحدةٍ تقرأ قبل أن تقرأ
    # الرقم. كان الرأس صفّاً واحداً يكرّر «ذهب» و«نقد» في كل عمود،
    # فتضيق الأعمدة ويطول العنوان ويصعب تتبّع الصف بالمسطرة.
    # والذهب أولاً: المصنع يزن قبل أن يحاسب.
    nb = len(aging.BUCKET_LABELS) + 1          # الفئات + عمود الإجمالي
    # **عمودا العمر ضيّقان**: «أحدث» و«أقدم دين» — والوحدة (يوم) في
    # سطر الشرح فوق الجدول. بالعنوان الطويل كان الجدول بالذهب والنقد
    # معاً أعرض من الورقة فيُقصّ عمود الإجمالي الأخير.
    top = ['<th class="r" rowspan="2" style="width:12%">الجهة</th>',
           '<th class="age" rowspan="2" style="width:4.5%;'
           'white-space:nowrap">أحدث</th>',
           '<th class="age" rowspan="2" style="width:5%">أقدم دين</th>']
    sub = []
    if show_gold:
        top.append(thspan(f"الذهب ({u})", colspan=nb))
        sub += [thw(b) for b in aging.BUCKET_LABELS] + [thw("الإجمالي")]
    if show_cash:
        top.append(thspan("الأجور (ريال)", colspan=nb))
        sub += [thw(b) for b in aging.BUCKET_LABELS] + [thw("الإجمالي")]
    ncols = 3 + (nb if show_gold else 0) + (nb if show_cash else 0)
    head_html = ("<tr>" + cells(*top) + "</tr>"
                 + ("<tr>" + cells(*sub) + "</tr>" if sub else ""))

    body = ""
    for r in rows:
        nd, od = aging.ages(r, dim)
        tds = [tdw(r["name"], align="right"),
               tdw("—" if nd is None else en(str(nd))),
               tdw(en(str(od or "—")))]
        if show_gold:
            tds += [tdw(_gw(x) if x else "—") for x in r["gold_buckets"]]
            tds += [tdw(_gw(r["gold"]))]
        if show_cash:
            tds += [tdw(_w(x, 2) if x else "—") for x in r["cash_buckets"]]
            tds += [tdw(_w(r["cash"], 2))]
        body += "<tr>" + cells(*tds) + "</tr>"
    if not body:
        body = f'<tr><td {TD} colspan="{ncols}">لا توجد أرصدة قائمة</td></tr>'

    tot = [thw("الإجمالي"), thw("—"), thw("—")]
    if show_gold:
        tot += [thw(_gw(x)) for x in t["gold_buckets"]]
        tot += [thw(_gw(t["gold"]))]
    if show_cash:
        tot += [thw(_w(x, 2)) for x in t["cash_buckets"]]
        tot += [thw(_w(t["cash"], 2))]

    pct_rows = ""
    for i, lbl in enumerate(aging.BUCKET_LABELS):
        pct = en(f"{t['cash_pct'][i]:,.1f}%")
        pct_rows += "<tr>" + cells(
            thw(lbl), tdw(_w(t["cash_buckets"][i], 2)), tdw(pct)) + "</tr>"

    html = f'''
    {TBL}
      <tr><td {TH} width="25%">الفئة</td><td>{label}</td>
          <th>حتى تاريخ</th><td>{en(as_of or today)}</td></tr>
      <tr><th>عدد الجهات المدينة</th><td>{en(f"{t['count']:,}")}</td>
          <th>النطاق</th>
          <td>{("جهات مختارة: " + en(str(len(only)))) if only
               else "كل الجهات"}</td></tr>
      <tr><th>تاريخ الطباعة</th><td {TD} colspan="3">{en(today)}</td></tr>
    </table>

    <style>
      /* الخط كما هو في كل الأوراق — العرض يُكسب من عمودَي العمر وحدهما */
      table.agetbl {{ table-layout: fixed; width: 100%; }}
      table.agetbl th {{ white-space: normal; }}
      table.agetbl td {{ white-space: nowrap; }}
      table.agetbl td.r {{ white-space: normal; }}
      table.agetbl th.age {{ padding-left: 1px; padding-right: 1px; }}
    </style>
    <div class="note">«أحدث»: أقدم دينٍ في فئة «أقل من 30» (منذ كم يوماً
      بدأ الدين الجاري) · «أقدم دين»: أقدم دينٍ قائم — بالأيام.</div>
    <table class="items agetbl" width="100%" cellspacing="0" cellpadding="3">
      {head_html}
      {body}
      <tr>{cells(*tot)}</tr>
    </table>

    <br/>
    {TBL_PLAIN}<tr>
      <td width="50%" valign="top">
        {TBL}
          <tr>{cells(thw("الفئة العمرية"), thw("المبلغ (ريال)"),
                     thw("النسبة"))}</tr>
          {pct_rows}
        </table>
      </td>
      <td width="50%"></td>
    </tr></table>

    <div class="note">طريقة الاحتساب: الأقدم فالأقدم — كل مدين يفتح
      دفعة بتاريخها وكل دائن يُسدّد أقدم الدفعات المفتوحة. الرصيد
      الدائن (له علينا) لا عمر له فلا يظهر في الفئات.</div>
    '''
    return (_header(f"أعمار الديون — {label}", "—", today, show_meta=False)
            + html + _footer(""))


def _tpl_day_close(conn, _id=0, date=None):
    """ورقة الإغلاق اليومي — حركة اليوم وأرصدته في صفحة واحدة."""
    from models import day_close
    from services import karat_view
    d = day_close.summary(conn, date)
    u = karat_view.unit()
    today = _qd(QtCore.QDate.currentDate())

    kinds = "".join(
        "<tr>" + cells(tdw(k["op"], align="right"),
                       tdw(en(f"{k['count']:,}")),
                       tdw(_gw(k["gold"])),
                       tdw(_w(k["cash"], 2))) + "</tr>"
        for k in d["kinds"])
    if not kinds:
        kinds = f'<tr><td {TD} colspan="4">لا حركة في هذا اليوم</td></tr>'

    # الأرقام بقيمتها المطلقة وحالتها في عمودها: إشارة السالب في نصٍّ
    # عربي تُطبع في آخر الرقم فتُقرأ خطأً.
    bal = "".join(
        "<tr>" + cells(
            tdw(b["name"], align="right"), tdw(en(b["code"])),
            tdw(_gw(abs(b["gold"])) if b["dim"] != "cash" else "—"),
            tdw(_w(abs(b["cash"]), 2) if b["dim"] != "gold" else "—"),
            tdw("مدين" if (b["gold"] > 0 or b["cash"] > 0)
                else ("دائن" if (b["gold"] < 0 or b["cash"] < 0)
                      else "متزن"))) + "</tr>"
        for b in d["balances"])

    docs = "".join(
        "<tr>" + cells(
            tdw(en((r["when"] or "")[11:16] or "—")),
            tdw(r["op"]), tdw(en(r["doc_no"] or "—")),
            tdw(r["accounts"], align="right"),
            tdw(_gw(r["gold"]) if r["gold"] else "—"),
            tdw(_w(r["cash"], 2) if r["cash"] else "—"),
            tdw(r["who"] or "—")) + "</tr>"
        for r in d["docs"])
    if not docs:
        docs = f'<tr><td {TD} colspan="7">لا مستندات</td></tr>'

    who = "   ·   ".join(f"{x['user']}: {x['count']}" for x in d["users"])

    html = f'''
    {TBL}
      <tr><td {TH} width="25%">اليوم</td><td>{en(d["date"])}</td>
          <th>عدد العمليات</th><td>{en(f"{d['count']:,}")}</td></tr>
      <tr><th>حركة الذهب</th><td>{_gw(d["gold_total"])} {u}</td>
          <th>حركة النقد</th><td>{_w(d["cash_total"], 2)} ريال</td></tr>
      <tr><th>داخل الصندوق</th><td>{_w(d["cash_in"], 2)}</td>
          <th>خارج الصندوق</th><td>{_w(d["cash_out"], 2)}
             (الصافي {_w(d["cash_net"], 2)})</td></tr>
      <tr><th>الإدخال</th><td {TD} colspan="3">{who or "—"}</td></tr>
    </table>

    <div class="party">حركة اليوم بأنواعها</div>
    {TBL}
      <tr>{cells(thw("نوع العملية"), thw("العدد"), thw(f"الذهب ({u})"),
                 thw("النقد (ريال)"))}</tr>
      {kinds}
    </table>

    <div class="party">الأرصدة الختامية بنهاية اليوم</div>
    {TBL}
      <tr>{cells(thw("الحساب"), thw("الكود"), thw(f"الذهب ({u})"),
                 thw("النقد (ريال)"), thw("الحالة"))}</tr>
      {bal}
    </table>

    <div class="party">مستندات اليوم</div>
    {TBL}
      <tr>{cells(thw("الوقت"), thw("العملية"), thw("رقم السند"),
                 thw("الحسابات"), thw(f"الذهب ({u})"), thw("النقد"),
                 thw("المستخدم"))}</tr>
      {docs}
    </table>

    <table class="sig" width="100%" cellspacing="0" cellpadding="6">
      <tr><td width="50%" align="center" style="text-align:center;">
            أمين الصندوق<br/>........................</td>
          <td width="50%" align="center" style="text-align:center;">
            المحاسب<br/>........................</td></tr>
    </table>
    '''
    return (_header("الإغلاق اليومي", d["date"], today, show_meta=False)
            + html)


def _tpl_stock_aging(conn, _id=0, as_of=None, model=None, detail=False):
    """أعمار الموديلات — ورقةٌ تُرفق بالجرد أو تُسلَّم للإدارة.

    جدولٌ واحد بالقطع، الأقدم أولاً، ورأسٌ يقول الخلاصة قبله. والفئات
    والموديلات لا تُطبع جداولَ لأن السؤال عن **القطعة**، والتجميع
    يخفي القطعةَ التي يُراد الوصول إليها.
    """
    from models import stock_aging
    from services import karat_view
    r = stock_aging.report(conn, as_of, model)
    u = karat_view.unit()
    today = _qd(QtCore.QDate.currentDate())
    t = r["total"]
    _chosen = ("، ".join(r["filter_models"]) if r["filter_models"]
               else "كل الموديلات")

    def _g(v):
        return _gw(v, 3)

    body = ""
    for x in r["items"]:
        body += "<tr>" + cells(
            tdw(en(x["wo_no"])), tdw(x["model"], align="right"),
            tdw(en(x["in_date"])),
            tdw(en(f"{x['days']:,}")),
            tdw(stock_aging.BUCKET_LABELS[x["bucket"]]),
            tdw(_g(x["weight"]))) + "</tr>"
    # سطرٌ لكل رقمٍ تجميعي (00010 · 0010): رصيدان مستقلّان
    for b in r.get("bulk_rows") or []:
        body += "<tr>" + cells(
            thw(en(b["wo_no"])), thw("رصيد تجميعي"), thw("—"), thw("—"),
            thw("بلا عمر — خارج الفئات"),
            thw(_g(b["weight"]))) + "</tr>"
    if not body:
        body = f'<tr><td {TD} colspan="6">لا مخزون</td></tr>'

    # الفئات في سطرٍ واحد أعلى الورقة — خلاصةٌ لا جدول
    bl = " · ".join(
        f'{b["label"]}: {en(_g(b["weight"]))}' for b in r["buckets"])
    lines = "".join(f"<li>{v}</li>"
                    for v in stock_aging.verdict(r, _g, lambda v: _w(v, 2)))
    html = f'''
    {TBL}
      <tr><td {TH} width="25%">حتى تاريخ</td><td>{en(as_of or today)}</td>
          <th>الموديل</th><td>{_chosen}</td></tr>
      <tr><th>في المخزن</th>
          <td>{en(f"{t['count']:,}")} قطعة · {en(_g(t["weight"]))} {u}</td>
          <th>فوق ٩٠ يوماً</th>
          <td>{en(_g(r["old_weight"]))} {u}
              ({en(f"{r['old_pct']:,.1f}%")})</td></tr>
      <tr><th>الفئات ({u})</th><td {TD} colspan="3">{bl}</td></tr>
      <tr><th>تاريخ الطباعة</th><td {TD} colspan="3">{en(today)}</td></tr>
    </table>

    {TBL}
      <tr>{cells(thw("رقم التشغيل"), thw("الموديل"),
                 thw("تاريخ الدخول"), thw("العمر (يوم)"), thw("الفئة"),
                 thw(f"الوزن ({u})"))}</tr>
      {body}
    </table>

    <div class="note">تاريخ الدخول من قيد التوريد لا من وقت كتابة
      السجل، فالدفعة التي تُسجَّل اليوم وقد ورَدَت الشهر الماضي عمرها
      من تاريخ قيدها. والرقمان التجميعيان 00010 و0010 رصيدُ وزنٍ لا
      قطع فلا عمر لهما — يُعرض كلٌّ منهما في ذيل الجدول خارج الفئات.</div>
    <div class="note"><ul>{lines}</ul></div>
    '''
    return (_header("أعمار الموديلات — ما رقد في المخزن", "—", today,
                    show_meta=False) + html + _footer(""))



def _tpl_customer_board(conn, _id=0, date_from=None, date_to=None,
                        side="gold", account_ids=None):
    """لوحة العملاء — جانبٌ واحد (ذهب أو نقد) بالعملاء الظاهرين.

    `account_ids` ترتيب الشاشة وتصفيتها كما هي: ما يراه المستخدم مفروزاً
    ومصفّى هو ما يُطبع، لا القائمة كلّها.
    """
    from models import customer_board as cb
    from services import karat_view
    res = cb.board(conn, date_from or None, date_to or None)
    by_id = {r["account_id"]: r for r in res["rows"]}
    if account_ids is None:
        rows = cb.by_paid([r for r in res["rows"] if r["active"]], side)
    else:
        rows = [by_id[a] for a in account_ids if a in by_id]
    gold = side != "cash"
    unit = karat_view.unit() if gold else "ريال"
    today = _qd(QtCore.QDate.currentDate())

    def _v(v):
        return _gw(v, 3) if gold else _w(v, 2)

    def _p(v):
        return "—" if v is None else en(f"{v:,.1f}%")

    tot = {k: 0.0 for k in cb.KINDS}
    for r in rows:
        for k in cb.KINDS:
            tot[k] += r[side][k]
    t = cb._side(tot, side)
    # كما في الشاشة: «رصيد سابق» و«حركات أخرى» لا يُطبعان إن خلَوا
    show_open = any(abs(r[side]["open"]) > 0.0005 for r in rows)
    show_other = any(abs(r[side]["other"]) > 0.0005 for r in rows)

    def _row(name, x, grade_txt, last, cell):
        out = [cell(name)]
        if show_open:
            out.append(cell(_v(x["open"])))
        out += [cell(_v(x["sales"])), cell(_v(x["returns"])),
                cell(_v(x["net"])), cell(_v(x["paid"]))]
        if show_other:
            out.append(cell(_v(x["other"])))
        out += [cell(f"<b>{_v(x['remaining'])}</b>"
                     if cell is tdw else _v(x["remaining"])),
                cell(_p(x["ret_pct"])), cell(_p(x["paid_pct"])),
                cell(last), cell(grade_txt)]
        return out

    body = ""
    for r in rows:
        x = r[side]
        c = _row(r["name"], x, x["grade"], en(r["last_paid"] or "—"), tdw)
        c[0] = tdw(r["name"], align="right")
        body += "<tr>" + cells(*c) + "</tr>"
    ncol = 10 + show_open + show_other
    if not body:
        body = (f'<tr><td {TD} colspan="{ncol}">'
                'لا عملاء بحركة في الفترة</td></tr>')
    foot = cells(*_row("الإجمالي", t, "", "", thw))
    hdr = ["العميل"] + (["رصيد سابق"] if show_open else []) + [
        "المبيعات", "المرتجع", "صافي المبيعات", "السداد"] + (
        ["حركات أخرى"] if show_other else []) + [
        "الباقي", "نسبة المرتجع", "نسبة السداد", "آخر سداد", "التقدير"]
    head = cells(*[thw(h) for h in hdr])
    period = (f'{en(date_from)} إلى {en(date_to or today)}' if date_from
              else f'منذ البداية حتى {en(date_to or today)}')
    meta = (f'<div {WIDE}>الفترة: <b>{period}</b> · الوحدة: <b>{unit}</b>'
            f' · عدد العملاء: <b>{en(len(rows))}</b></div>')
    note = ('<div class="note">صافي المبيعات = رصيدٌ سابق + المبيعات −'
            ' المرتجع · الباقي = صافي المبيعات − السداد + حركاتٌ أخرى'
            ' (سند صرف، تسوية)، وهو رصيد الحساب في دفتر الأستاذ. والسداد'
            ' يشمل سندات القبض والتسكير وما سُدّد بقيدٍ يومي.'
            ' ونسبة السداد من صافي المبيعات، ونسبة المرتجع من (رصيد سابق +'
            ' المبيعات).'
            ' الترتيب: الأعلى سداداً أولاً.</div>')
    title = "لوحة العملاء — " + ("الذهب" if gold else "النقد")
    return (_header(title, "—", today, show_meta=False) + meta
            + f"{TBL}<tr>{head}</tr>{body}<tr>{foot}</tr></table>"
            + note + _footer(""))


def _tpl_dossier(conn, entity_id=0, date_from=None, date_to=None):
    """ملف الجهة في ورقةٍ واحدة — تُطبع وتُوضع في الملف أو تُرسل.

    ترتيبها ترتيبُ السؤال لا ترتيبُ قاعدة البيانات: الخلاصة أولاً،
    ثم الرصيد والسقف، ثم ما جرى في الفترة، ثم أعمار الدين، ثم
    موديلاته وأجرته. فمن قرأ السطر الأول عرف الحال، ومن أراد التفصيل
    وجده تحته.
    """
    from models import dossier
    from models.aging import BUCKET_LABELS
    from services import karat_view
    d = dossier.build(conn, entity_id, date_from, date_to)
    u = karat_view.unit()
    today = _qd(QtCore.QDate.currentDate())
    e, b = d["entity"], d["balance"]

    def _g(v):
        s = _gw(abs(v or 0.0), 3)
        return f"({s})" if (v or 0.0) < 0 else s

    def _m(v):
        s = _w(abs(v or 0.0), 2)
        return f"({s})" if (v or 0.0) < 0 else s

    # ── جسر الفترة ──
    r = d["bridge"]
    bridge = "<tr>" + cells(
        thw("رصيد أول المدة"), thw(_g(r["opening"]["gold"])),
        thw(_m(r["opening"]["cash"])), thw("—"), thw("—")) + "</tr>"
    for x in r["buckets"]:
        if abs(x["gold"]) < 0.0005 and abs(x["cash"]) < 0.005:
            continue
        bridge += "<tr>" + cells(
            tdw(x["label"], align="right"), tdw(_g(x["gold"])),
            tdw(_m(x["cash"])), tdw(en(f"{x['docs']:,}")),
            tdw(en(x["days_label"]))) + "</tr>"
    bridge += "<tr>" + cells(
        thw("رصيد آخر المدة"), thw(_g(r["closing"]["gold"])),
        thw(_m(r["closing"]["cash"])), thw("—"), thw("—")) + "</tr>"

    # ── أعمار دينه ──
    a = d["aging"]
    if a:
        age = "<tr>" + cells(
            tdw("الوزن", align="right"),
            *[tdw(_g(x)) for x in a["gold_buckets"]],
            thw(_g(a["gold"]))) + "</tr><tr>" + cells(
            tdw("النقد", align="right"),
            *[tdw(_m(x)) for x in a["cash_buckets"]],
            thw(_m(a["cash"]))) + "</tr>"
        oldest = f'{en(str(a["days"]))} يوماً — منذ {en(a["oldest"])}'
    else:
        age = (f'<tr><td {TD} colspan="{len(BUCKET_LABELS) + 2}">'
               'لا دينَ قائمٌ على هذه الجهة</td></tr>')
        oldest = "—"

    # ── موديلاته ──
    mdl = ""
    for x in (d["models"] or [])[:20]:        # موديلات الفترة — كالشاشة
        mdl += "<tr>" + cells(
            tdw(x["model"], align="right"), tdw(en(f"{x['sold']:,}")),
            tdw(en(f"{x['returned']:,}")), tdw(en(f"{x['net_count']:,}")),
            tdw(_g(x["weight"])), tdw(_m(x["wages"]))) + "</tr>"
    if not mdl:
        mdl = f'<tr><td {TD} colspan="6">لا مبيعات في الفترة</td></tr>'

    fl, flife = d["flow"], d["flow_life"]

    def _pct(v):
        return en(f"{v:,.1f}%") if v is not None else "—"

    _other_up = ""
    if abs(fl["other_up"]) > 0.0005 or abs(flife["other_up"]) > 0.0005:
        _other_up = "<tr>" + cells(
            tdw("وما زاد ذمّته بغير البضاعة", align="right"),
            tdw(_g(fl["other_up"])), tdw("—"),
            tdw(_g(flife["other_up"]))) + "</tr>"

    lr, lp = d["last_receipt"], d["last_payment"]
    lim_g, lim_c = d["limit"]["gold"], d["limit"]["cash"]

    def _lim(st, f):
        if not st["limit"]:
            return "بلا سقف"
        tag = " ⚠ تجاوز" if st["over"] else ""
        pct = en("{:,.0f}%".format(st["pct"] or 0))
        return f'{f(st["used"])} من {f(st["limit"])} ({pct}){tag}'

    lines = "".join(f"<li>{v}</li>"
                    for v in dossier.verdict(d, _g, _m))
    html = f'''
    <div class="note"><ul>{lines}</ul></div>

    {TBL}
      <tr><td {TH} width="22%">الجهة</td><td>{e["name"]}</td>
          <th>الفترة</th>
          <td>{en(d["date_from"])} إلى {en(d["as_of"])}</td></tr>
      <tr><th>الهاتف</th><td>{en(e["phone"] or "—")}</td>
          <th>الرقم الضريبي</th><td>{en(e["vat"] or "—")}</td></tr>
      <tr><th>الرصيد</th>
          <td>{en(_g(b["gold"]))} {u} · {en(_m(b["cash"]))} ريال</td>
          <th>أقدم دين</th><td>{oldest}</td></tr>
      <tr><th>سقف وزني</th><td>{_lim(lim_g, _g)}</td>
          <th>سقف نقدي</th><td>{_lim(lim_c, _m)}</td></tr>
      <tr><th>آخر تحصيل</th>
          <td>{(en(lr["date"]) + " — " + en(_g(lr["gold"])) + " " + u
                + " · " + en(_m(lr["cash"])) + " ريال") if lr
               else "لم يُسدَّد منه شيءٌ قط"}</td>
          <th>آخر صرفٍ له</th>
          <td>{en(lp["date"]) if lp else "—"}</td></tr>
      <tr><th>تاريخ الطباعة</th><td {TD} colspan="3">{en(today)}</td></tr>
    </table>

    <div class="party">ما جرى في الفترة — جسر الرصيد</div>
    {TBL}
      <tr>{cells(thw("البند"), thw(f"الوزن ({u})"), thw("النقد (ريال)"),
                 thw("مستندات"), thw("أيام من الفترة"))}</tr>
      {bridge}
    </table>

    <div class="party">أعمار دينه</div>
    {TBL}
      <tr>{cells(thw("البُعد"), *[thw(x) for x in BUCKET_LABELS],
                 thw("الإجمالي"))}</tr>
      {age}
    </table>

    <div class="party">حركته — وما كان تحت يده</div>
    {TBL}
      <tr>{cells(thw("البند"), thw(f"الفترة ({u})"), thw("الفترة (ريال)"),
                 thw(f"من البداية ({u})"))}</tr>
      <tr>{cells(tdw("رصيد أول المدة", align="right"),
                 tdw(_g(fl["opening_weight"])), tdw("—"),
                 tdw(_g(flife["opening_weight"])))}</tr>
      <tr>{cells(tdw("ما خرج إليه — بضاعة (مبيعات)", align="right"),
                 tdw(_g(fl["out_weight"])), tdw(_m(fl["out_wages"])),
                 tdw(_g(flife["out_weight"])))}</tr>
      {_other_up}
      <tr>{cells(thw("ما كان عنده (الأساس)"),
                 thw(_g(fl["held_weight"])), thw("—"),
                 thw(_g(flife["held_weight"])))}</tr>
      <tr>{cells(tdw("ما رجع منه", align="right"),
                 tdw(_g(fl["back_weight"])), tdw(_m(fl["back_wages"])),
                 tdw(_g(flife["back_weight"])))}</tr>
      <tr>{cells(tdw("ما سدّده", align="right"),
                 tdw(_g(fl["paid_weight"])), tdw(_m(fl["paid_cash"])),
                 tdw(_g(flife["paid_weight"])))}</tr>
      <tr>{cells(thw("الباقي عليه (رصيد آخر المدة)"),
                 thw(_g(fl["closing_weight"])),
                 thw(_m(fl["closing_cash"])),
                 thw(_g(flife["closing_weight"])))}</tr>
      <tr>{cells(tdw("نسبة المرتجع (من الذي كان عنده)", align="right"),
                 tdw(_pct(fl["return_pct"])), tdw("—"),
                 tdw(_pct(flife["return_pct"])))}</tr>
      <tr>{cells(tdw("نسبة السداد (من الذي كان عنده)", align="right"),
                 tdw(_pct(fl["paid_pct"])), tdw("—"),
                 tdw(_pct(flife["paid_pct"])))}</tr>
      <tr>{cells(thw("نسبة التصفية (مرتجع + سداد)"),
                 thw(_pct(fl["settled_pct"])), thw("—"),
                 thw(_pct(flife["settled_pct"])))}</tr>
    </table>

    <div class="party">أكثر ما يأخذ من الموديلات (من البداية)</div>
    {TBL}
      <tr>{cells(thw("الموديل"), thw("خرج"), thw("رجع"), thw("الصافي"),
                 thw(f"الوزن الصافي ({u})"), thw("الأجور (ريال)"))}</tr>
      {mdl}
    </table>

    <div class="note">لا رقمَ يُحسب في هذه الورقة: الأعمار من تقرير
      أعمار الديون، والجسر من تحليل حركة الرصيد، والرصيد من الدفتر —
      فلا تخالف الورقةُ كشفَ الحساب. والسالب بين قوسين كما يكتبه
      المحاسبون.</div>
    '''
    return (_header(f"ملف الجهة — {e['name']}", "—", today,
                    show_meta=False) + html + _footer(""))


def _tpl_doc_edits(conn, _id=0, date_from=None, date_to=None,
                   source_table=None, min_lag=0):
    """من عدّل ماذا بعد الترحيل — ورقةٌ تُوضع أمام المدقّق.

    المتأخّر أولاً في جدولٍ مستقل: هو ما يُسأل عنه، وإدراجه ضمن
    المئة سطرٍ الأخرى يجعله لا يُرى.
    """
    from models import doc_edits
    from services import karat_view
    rows = doc_edits.report(conn, date_from, date_to,
                            source_table=source_table, min_lag=min_lag)
    s = doc_edits.summarize(conn, rows)
    t = s["total"]
    u = karat_view.unit()
    today = _qd(QtCore.QDate.currentDate())

    def _g(v):
        x = _gw(abs(v or 0.0), 3)
        return f"({x})" if (v or 0.0) < 0 else x

    def _m(v):
        x = _w(abs(v or 0.0), 2)
        return f"({x})" if (v or 0.0) < 0 else x

    def _row(r):
        return "<tr>" + cells(
            tdw(en(r["edited_at"])), tdw(r["user"], align="right"),
            tdw(r["label"], align="right"), tdw(en(r["doc_no"])),
            tdw(en(r["doc_date"])),
            tdw(en(f"{r['lag']:,}") if r["lag"] is not None else "—"),
            tdw(_g(r["old_gold"])), tdw(_g(r["new_gold"])),
            tdw(_g(r["d_gold"])), tdw(_m(r["old_cash"])),
            tdw(_m(r["new_cash"])), tdw(_m(r["d_cash"]))) + "</tr>"

    late = [r for r in rows if r["lag"] is not None
            and r["lag"] >= doc_edits.LATE_DAYS]
    head = cells(thw("وقت التعديل"), thw("المستخدم"), thw("النوع"),
                 thw("المستند"), thw("تاريخ المستند"), thw("التأخّر"),
                 thw(f"قبل ({u})"), thw(f"بعد ({u})"), thw(f"الفرق ({u})"),
                 thw("قبل (ريال)"), thw("بعد (ريال)"), thw("الفرق (ريال)"))
    body = "".join(_row(r) for r in rows) \
        or f'<tr><td {TD} colspan="12">لا تعديلات في هذه الفترة</td></tr>'
    late_block = ""
    if late:
        late_block = (
            f'<div class="party">المتأخّر — بعد {en(doc_edits.LATE_DAYS)} '
            f'يوماً أو أكثر من الترحيل ({en(len(late))})</div>{TBL}'
            + "<tr>" + head + "</tr>" + "".join(_row(r) for r in late)
            + "</table>")

    users = ""
    for x in s["users"]:
        users += "<tr>" + cells(
            tdw(x["name"], align="right"), tdw(en(f"{x['count']:,}")),
            tdw(en(f"{x['late']:,}")), tdw(_g(x["d_gold"])),
            tdw(_m(x["d_cash"]))) + "</tr>"
    if users:
        users += "<tr>" + cells(
            thw("الإجمالي"), thw(en(f"{t['count']:,}")),
            thw(en(f"{t['late']:,}")), thw(_g(t["d_gold"])),
            thw(_m(t["d_cash"]))) + "</tr>"
    else:
        users = f'<tr><td {TD} colspan="5">لا تعديلات</td></tr>'

    lines = "".join(f"<li>{v}</li>"
                    for v in doc_edits.verdict(s, _g, _m))
    html = f'''
    {TBL}
      <tr><td {TH} width="22%">الفترة</td>
          <td>{en(date_from or "—")} إلى {en(date_to or today)}</td>
          <th>النوع</th>
          <td>{doc_edits.LABELS.get(source_table, "كل المستندات")}</td></tr>
      <tr><th>عدد التعديلات</th><td>{en(f"{t['count']:,}")}</td>
          <th>منها غيّرت القيمة</th>
          <td>{en(f"{t['changed']:,}")}</td></tr>
      <tr><th>تعديلٌ متأخّر</th>
          <td>{en(f"{t['late']:,}")} (أقصاه
              {en(f"{t['max_lag']:,}")} يوماً)</td>
          <th>تاريخ الطباعة</th><td>{en(today)}</td></tr>
    </table>

    <div class="note"><ul>{lines}</ul></div>
    {late_block}

    <div class="party">كل التعديلات — الأحدث أولاً</div>
    {TBL}
      <tr>{head}</tr>
      {body}
    </table>

    <div class="party">بالمستخدم</div>
    {TBL}
      <tr>{cells(thw("المستخدم"), thw("تعديلات"), thw("منها متأخّر"),
                 thw(f"صافي الوزن ({u})"), thw("صافي النقد (ريال)"))}</tr>
      {users}
    </table>

    <div class="note">قيمة المستند = مجموع الطرف المدين من قيده —
      مقياسٌ واحد يصلح لكل نوع لأن القيد متوازنٌ بالضرورة. والفرق رقمٌ
      محفوظٌ لحظة التعديل لا نصٌّ يُحلَّل بعده. والتأخّر يُقاس من لحظة
      الترحيل لا من تاريخ المستند. والتعديل مشروعٌ في هذا النظام؛
      المقصود أن يكون مرئياً.</div>
    '''
    return (_header("من عدّل ماذا بعد الترحيل", "—", today,
                    show_meta=False) + html + _footer(""))


BUILDERS = {
    "invoice": _tpl_invoice, "invoices": _tpl_invoice,
    "voucher": _tpl_voucher, "vouchers": _tpl_voucher,
    "journal": _tpl_journal, "manual": _tpl_journal,
    "melting": _tpl_melting, "melting_ops": _tpl_melting,
    "purchase": _tpl_purchase, "purchases": _tpl_purchase,
    "tax_sale": _tpl_tax_sale, "tax_sales": _tpl_tax_sale,
    "tax_sales_register": _tpl_tax_sales_register,
    "purchases_register": _tpl_purchases_register,
    "fixing": _tpl_fixing, "fixing_ops": _tpl_fixing,
    "work_orders": _tpl_work_order, "wo_supply": _tpl_work_order,
    "wo_adjust": _tpl_work_order,
    "workshop_losses": _tpl_workshop_losses,
    "workshop_losses_log": _tpl_workshop_losses,
    "workshop_accounts": _tpl_workshop_accounts,
    "balance_tree": _tpl_balance_tree,
    "trial_balance": _tpl_trial_balance,
    "financial_position": _tpl_financial_position,
    "income_statement": _tpl_income_statement,
    "cash_flow": _tpl_cash_flow,
    "equity_changes": _tpl_equity_changes,
    "models_catalog": _tpl_models_catalog,
    "models_received": _tpl_models_received,
    "models_received_photos": _tpl_models_received_photos,
    "dossier_models": _tpl_dossier_models,
    "invoice_models": _tpl_invoice_models,
    "dash_panel": _tpl_dash_panel,
    "model_photos": _tpl_model_photos,
    "aging": _tpl_aging,
    "day_close": _tpl_day_close,
    "stock_aging": _tpl_stock_aging,
    "dossier": _tpl_dossier,
    "doc_edits": _tpl_doc_edits,
    "customer_board": _tpl_customer_board,
}

DOC_LABELS = {
    "invoices": "فاتورة/مرتجع", "vouchers": "سند قبض/صرف",
    "purchases": "فاتورة مشتريات", "tax_sales": "فاتورة ضريبية/إشعار دائن",
    "melting_ops": "صب وتصفية",
    "fixing_ops": "تسكير", "manual": "قيد يومية",
    "work_orders": "سند توريد", "workshop_losses": "سند فاقد ورشة",
}


def build_html(doc_type, doc_id, **kw):
    """يبني مستند HTML كاملاً من قاعدة البيانات (لمحرك Qt)."""
    with db() as conn:
        if doc_type == "statement":
            html = _tpl_statement(conn, doc_id, kw.get("date_from"),
                                  kw.get("date_to"), _karat_kw(kw))
        elif doc_type == "balances":
            html = _tpl_balances(conn, doc_id, kw.get("rows") or [])
        elif doc_type == "customer_analytics":
            html = _tpl_customer_analytics(
                conn, doc_id, kw.get("date_from"), kw.get("date_to"),
                kw.get("visible"), kw.get("expanded"),
                _karat_kw(kw))
        elif doc_type in ("mfg_target", "mfg_salary", "mfg_summary"):
            html = _tpl_mfg(conn, doc_id, kw.get("period"),
                            kw.get("targets"), kw.get("salaries"),
                            doc_type)
        elif doc_type == "turnover":
            html = _tpl_turnover(conn, doc_id, kw.get("date_from"),
                                 kw.get("date_to"))
        elif doc_type == "aging":
            html = _tpl_aging(conn, doc_id,
                              kw.get("entity_type", "customer"),
                              kw.get("as_of"), kw.get("dim", "both"),
                              kw.get("only"))
        elif doc_type in ("tax_sales_register", "purchases_register"):
            fn = (_tpl_tax_sales_register if doc_type == "tax_sales_register"
                  else _tpl_purchases_register)
            html = fn(conn, doc_id, kw.get("date_from"), kw.get("date_to"))
        elif doc_type == "day_close":
            html = _tpl_day_close(conn, doc_id, kw.get("date"))
        elif doc_type == "dossier_models":
            html = _tpl_dossier_models(conn, doc_id, kw.get("date_from"),
                                       kw.get("date_to"),
                                       kw.get("per_page", 4))
        elif doc_type == "trial_balance":
            html = _tpl_trial_balance(conn, doc_id, kw.get("date_from"),
                                      kw.get("date_to"),
                                      kw.get("include_zero", False),
                                      kw.get("dim", "cash"),
                                      kw.get("max_level", 9))
        elif doc_type == "financial_position":
            html = _tpl_financial_position(conn, doc_id, kw.get("as_of"),
                                           kw.get("compare_to"))
        elif doc_type == "equity_changes":
            html = _tpl_equity_changes(
                conn, doc_id, kw.get("date_from"), kw.get("date_to"),
                kw.get("compare", True), kw.get("dim", "cash"))
        elif doc_type == "cash_flow":
            html = _tpl_cash_flow(
                conn, doc_id, kw.get("date_from"), kw.get("date_to"),
                kw.get("compare", True), kw.get("method", "indirect"))
        elif doc_type == "income_statement":
            html = _tpl_income_statement(
                conn, doc_id, kw.get("date_from"), kw.get("date_to"),
                kw.get("compare", True), kw.get("show_accounts", False))
        elif doc_type == "customer_board":
            html = _tpl_customer_board(conn, doc_id, kw.get("date_from"),
                                       kw.get("date_to"),
                                       kw.get("side", "gold"),
                                       kw.get("account_ids"))
        else:
            fn = BUILDERS.get(doc_type)
            if not fn:
                raise ValueError(f"لا يوجد قالب طباعة للنوع: {doc_type}")
            html = fn(conn, doc_id)
    # إطار خارجي كامل يحيط بالمستند ويمتد بعرض ورقة A4
    framed = (
        '<table class="frame" width="100%" height="100%" cellspacing="0"'
        ' cellpadding="8"><tr><td class="framecell" width="100%" valign="top">'
        f'{en(html)}</td></tr></table>')
    # محرك Qt يعرف الخط المرفق بعد تسجيله في التطبيق — فالاسم يكفيه
    from services import print_fonts
    css = BASE_CSS.replace("@FAMILY@", print_fonts.family_css())
    return (f"<html dir='rtl'><head><meta charset='utf-8'>{css}</head>"
            f"<body dir='rtl'><div class='doc'>{framed}</div></body></html>")


def _document(html, printer=None):
    """يبني مستند الطباعة.

    **مهم**: ضبط `setPageSize`/`setTextWidth` يجب أن يتم بعد أن تعرف
    الطابعة أبعادها الفعلية — أي داخل `paintRequested` في نافذة
    المعاينة، لا قبلها. لذلك يُمرَّر `printer` هنا فقط عند توفّره
    فعلياً بأبعاده النهائية.
    """
    doc = QtGui.QTextDocument()
    doc.setDocumentMargin(0)
    opt = QtGui.QTextOption()
    opt.setTextDirection(QtCore.Qt.RightToLeft)
    doc.setDefaultTextOption(opt)
    doc.setHtml(html)
    if printer is not None:
        _fit_to_printer(doc, printer)
    return doc


def _fit_to_printer(doc, printer):
    """يُلائم المستند مع مساحة الورقة القابلة للطباعة.

    **مهم**: يُضبط `setPageSize` وحده. ضبط `setTextWidth` معه يتعارض
    ويجعل المحرك يقيّد عرض التخطيط فيخرج المستند أضيق من الورقة —
    وهي علة تقلّص القوالب.
    """
    try:
        rect = printer.pageRect()
        doc.setPageSize(QtCore.QSizeF(rect.width(), rect.height()))
    except Exception:
        pass


def _printer(landscape=False):
    p = QtPrintSupport.QPrinter(QtPrintSupport.QPrinter.HighResolution)
    p.setPageSize(QtPrintSupport.QPrinter.A4)
    p.setOrientation(QtPrintSupport.QPrinter.Landscape if landscape
                     else QtPrintSupport.QPrinter.Portrait)
    # هوامش صغيرة جداً: الإطار الخارجي يوفّر الهامش البصري بنفسه
    p.setPageMargins(5, 5, 5, 5, QtPrintSupport.QPrinter.Millimeter)
    return p


def preview_document(parent, doc_type, doc_id, landscape=None, **kw):
    """**المعاينة الافتراضية للنظام كله — عبر المتصفح.**

    كل استدعاء للمعاينة في أي شاشة يمرّ من هنا، فيُفتح المستند في
    المتصفح الافتراضي بتنسيق كامل (عرض الورقة · الاتجاه العربي ·
    الأعمدة المنتظمة) بدل محرك Qt المحدود.

    إن تعذّر فتح المتصفح لأي سبب، يُرجع النظام تلقائياً إلى معاينة Qt
    حتى لا تتعطّل الطباعة.
    """
    try:
        from services import browser_print
        browser_print.open_document(doc_type, doc_id, **kw)
        return True
    except Exception:
        return qt_preview_document(parent, doc_type, doc_id, landscape, **kw)


def qt_preview_document(parent, doc_type, doc_id, landscape=None, **kw):
    """معاينة Qt الاحتياطية (تُستخدم فقط إن تعذّر فتح المتصفح)."""
    html = build_html(doc_type, doc_id, **kw)
    wide = doc_type in ("statement", "journal", "manual", "balances",
                        "customer_analytics", "turnover", "aging",
                        "day_close", "mfg_target", "mfg_salary",
                        "customer_board", "trial_balance",
                        "equity_changes")
    printer = _printer(wide if landscape is None else landscape)
    dlg = QtPrintSupport.QPrintPreviewDialog(printer, parent)
    dlg.setWindowTitle("معاينة قبل الطباعة")
    dlg.resize(1000, 720)

    def _render(pr):
        d = _document(html)
        _fit_to_printer(d, pr)
        d.print_(pr)

    dlg.paintRequested.connect(_render)
    return dlg.exec_()


def print_document(parent, doc_type, doc_id, **kw):
    """يفتح نافذة طباعة النظام مباشرةً (بلا معاينة Qt).

    يتجاوز مشاكل `QPrintPreviewDialog` تماماً: تُبنى الوثيقة وتُلاءم
    مع أبعاد الطابعة **بعد** أن يؤكد المستخدم اختيار الطابعة.
    """
    html = build_html(doc_type, doc_id, **kw)
    printer = _printer(doc_type in ("statement", "journal", "manual",
                                    "balances", "customer_analytics"))
    dlg = QtPrintSupport.QPrintDialog(printer, parent)
    dlg.setWindowTitle("الطباعة المباشرة")
    if dlg.exec_() == QtWidgets.QDialog.Accepted:
        doc = _document(html)
        _fit_to_printer(doc, printer)
        doc.print_(printer)
        return True
    return False


def export_pdf(doc_type, doc_id, path, **kw):
    """يصدّر المستند ملف PDF بجودة طباعة."""
    html = build_html(doc_type, doc_id, **kw)
    printer = _printer(doc_type in ("statement", "journal", "manual", "balances"))
    printer.setOutputFormat(QtPrintSupport.QPrinter.PdfFormat)
    printer.setOutputFileName(str(path))
    doc = _document(html)
    _fit_to_printer(doc, printer)
    doc.print_(printer)
    return str(path)


def export_pdf_dialog(parent, doc_type, doc_id, suggested="مستند", **kw):
    """يسأل المستخدم عن مسار الحفظ ثم يصدّر PDF."""
    path, _ = QtWidgets.QFileDialog.getSaveFileName(
        parent, "حفظ المستند بصيغة PDF", f"{suggested}.pdf", "PDF (*.pdf)")
    if not path:
        return None
    return export_pdf(doc_type, doc_id, path, **kw)
