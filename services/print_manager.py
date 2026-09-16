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
from models.inventory import BULK_WO_NO
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
  body { font-family: 'Segoe UI', 'Cairo', Tahoma, sans-serif;
         font-size: 10.5pt; color: #1a1a1a; }
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
  table.items th { background-color: #EFEFEF; font-weight: bold;
                   white-space: nowrap; }   /* لا تُكسر العناوين لسطرين */
  table.items td.nw { white-space: nowrap; }
  table.items td.r  { text-align: right; }
  table.items tr.total td { background-color: #EFEFEF; font-weight: bold; }

  /* جدول تخطيط بلا حدود (للترويسة والصفوف الجانبية) */
  table.plain { width: 100%; border-collapse: collapse; margin: 0; }
  table.plain td { padding: 2px; vertical-align: top; }

  /* عنوان المستند: شريط ممتد بعرض الصفحة */
  table.titlebar { width: 100%; border-collapse: collapse; margin: 6px 0; }
  table.titlebar td { border: 1px solid #999; background-color: #EFEFEF;
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


def tdw(value, pct=None, align="center"):
    """خلية بيانات؛ align='right' لعمود البيان."""
    cls = ' class="r"' if align == "right" else ""
    return f'<td{cls}>{value}</td>'


def _logo_tag(height=120):
    """وسم صورة الشعار الرسمي (يُتجاهل بأمان إن لم يوجد الملف)."""
    path = getattr(config, "LOGO_PATH", None)
    if path and Path(str(path)).exists():
        return (f'<img src="{Path(str(path)).as_uri()}" height="{height}">')
    return ""


def _header(doc_type, doc_no, date, extra="", show_meta=True):
    """الترويسة الموحدة بخصائص HTML صريحة (يدعمها محرك Qt للطباعة):
    عربي يميناً · الشعار بارزاً في المنتصف · إنجليزي يساراً · خط فاصل ·
    عنوان المستند في مربع ممتد بعرض الصفحة بخلفية رمادية فاتحة.
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
    ar_cell = f'''<td align="right" width="35%"
            style="text-align:right; direction:rtl;">
          <div style="font-size:14pt; font-weight:bold;">{config.COMPANY_NAME}</div>
          <div style="font-size:9.5pt;">{config.COMPANY_COUNTRY}</div>
          <div style="font-size:9.5pt;">{config.COMPANY_ADDRESS}</div>
          <div style="font-size:9.5pt;">سجل تجاري: {en(config.COMPANY_CR)}</div>
        </td>'''
    logo_cell = (f'<td align="center" width="30%" '
                 f'style="text-align:center;">{_logo_tag()}</td>')
    en_cell = f'''<td align="left" width="35%"
            style="text-align:left; direction:ltr;">
          <div style="font-size:14pt; font-weight:bold;">{config.COMPANY_NAME_EN}</div>
          <div style="font-size:9.5pt;">{config.COMPANY_COUNTRY_EN}</div>
          <div style="font-size:9.5pt;">{config.COMPANY_ADDRESS_EN}</div>
          <div style="font-size:9.5pt;">C.R: {en(config.COMPANY_CR)}</div>
        </td>'''
    return f"""
    <table class="lh" width="100%" cellspacing="0" cellpadding="4"><tr>{cells(ar_cell, logo_cell, en_cell)}</tr></table>
    <table class="titlebar" width="100%" cellspacing="0" cellpadding="6"><tr><td width="100%">{doc_type}</td></tr></table>{meta}
    """


def _footer(notes=""):
    """تذييل نظيف: سطر ملاحظات اختياري + سطر توقيع واحد على اليسار.
    لا توقيعات متعددة ولا نصوص برمجية سفلية."""
    note_html = (f'<div class="note">ملاحظات: {notes}</div>'
                 if notes else "")
    return f"""
    <br/>{note_html}
    <div style="text-align:left; padding-top:22px; font-size:10.5pt">
      التوقيع: .............................
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
        # الرقم التجميعي 0001 سجل واحد يحمل **الرصيد الكلي**، فطباعة
        # أعمدته كما هي تُظهر كل الرصيد بدل الوزن المُدخل في السطر.
        # لذلك نعرض وزن السطر نفسه: القائم = المقيد والذهب = المقيد.
        if wo and (wo["work_order_no"] or "").strip() == BULK_WO_NO:
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

    body = f'''{info}
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
        f'<td {TH} width="25%">وزن الذهب (عيار 18)</td>',
        f'''<td align="center" style="text-align:center;
            border:1px solid #999; padding:4px; font-size:12pt;
            font-weight:bold; width:25%;">{_w(v["gold_equiv18"])}</td>''',
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
          <td>{_w(abs(g_bal))}</td><td>{side(g_bal)}</td></tr>
    </table>

    <table class="sig" width="100%" cellspacing="0" cellpadding="6">
      <tr>{sig_cells}</tr>
    </table>
    '''
    return (_header(kind, v["voucher_no"] or f"#{voucher_id}",
                    v["voucher_date"], show_meta=False) + body)


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
                     _w(l["gold_debit"]) if l["gold_debit"] else "",
                     _w(l["gold_credit"]) if l["gold_credit"] else "",
                     _w(l["cash_debit"], 2) if l["cash_debit"] else "",
                     _w(l["cash_credit"], 2) if l["cash_credit"] else ""))
    balanced = (abs(tg_d - tg_c) < 0.011 and abs(tc_d - tc_c) < 0.011)
    body = f"""
    <table class="items">
      <tr><th>الحساب</th><th>مدين ذهب</th><th>دائن ذهب</th>
          <th>مدين نقد</th><th>دائن نقد</th></tr>
      {_rows(rows)}
      <tr class="total"><td class="num">الإجمالي</td>
        <td class="num">{_w(tg_d)}</td><td class="num">{_w(tg_c)}</td>
        <td class="num">{_w(tc_d, 2)}</td><td class="num">{_w(tc_c, 2)}</td></tr>
    </table><br/>
    <div class="note">حالة التوازن:
      <b>{'متوازن — الميزانان الوزني والنقدي متطابقان' if balanced else 'غير متوازن'}</b></div>
    """
    return (_header("قيد يومية", f"#{entry_id}", e["entry_date"])
            + body + _footer(e["user_note"] or ""))


def _tpl_melting(conn, op_id):
    op = conn.execute("SELECT * FROM melting_ops WHERE id=?",
                      (op_id,)).fetchone()
    if not op:
        raise ValueError("المستند غير موجود")
    label = melting.KIND_LABELS.get(op["kind"], "عملية صب وتصفية")
    rows = [(f"عيار {l['karat']}", _w(l["weight"]), _w(l["equiv18"]))
            for l in melting.op_lines(conn, op_id)]
    if not rows:
        rows = [("—", "—", _w(op["equiv18"]))]
    body = f"""
    <table class="items">
      <tr><th>العيار</th><th>الوزن الفعلي (جم)</th><th>معادل عيار 18 (جم)</th></tr>
      {_rows(rows)}
      <tr class="total"><td class="num">الإجمالي</td><td class="num">—</td>
        <td class="num">{_w(op['equiv18'])}</td></tr>
    </table><br/>
    <div class="note">كل الأوزان تُقيَّد بمعادل عيار 18:
      الوزن الفعلي × العيار ÷ 18.</div>
    """
    return (_header(label, op["op_no"] or f"#{op_id}", op["op_date"])
            + body + _footer(op["notes"] or ""))


def _tpl_purchase(conn, pid):
    p = conn.execute("SELECT * FROM purchases WHERE id=?", (pid,)).fetchone()
    if not p:
        raise ValueError("الفاتورة غير موجودة")
    sup = conn.execute("SELECT name, phone FROM entities WHERE id=?",
                       (p["supplier_id"],)).fetchone()
    rows = [(p["description"] or "—", _w(p["amount"], 2),
             _w(p["vat_amount"], 2),
             _w((p["amount"] or 0) + (p["vat_amount"] or 0), 2))]
    body = f"""
    <div class="party">المورد:
      <span class="party-name">{sup['name'] if sup else '—'}</span></div><br/>
    <table class="items">
      <tr><th>البيان</th><th>المبلغ</th><th>الضريبة</th><th>الإجمالي</th></tr>
      {_rows(rows)}
    </table><br/>
    <div class="tafqeet">فقط: {tafqeet((p['amount'] or 0) + (p['vat_amount'] or 0))}</div>
    """
    kind = "فاتورة مشتريات (أصل ثابت)" if p["asset_id"] else "فاتورة مشتريات"
    return (_header(kind, p["purchase_no"] or f"#{pid}", p["purchase_date"])
            + body + _footer(""))


def _tpl_fixing(conn, op_id):
    f = conn.execute("SELECT * FROM fixing_ops WHERE id=?", (op_id,)).fetchone()
    if not f:
        raise ValueError("العملية غير موجودة")
    ent = conn.execute("SELECT name FROM entities WHERE id=?",
                       (f["customer_id"],)).fetchone()
    rows = [(_w(f["weight"]), _w(f["price"], 2), _w(f["amount"], 2))]
    body = f"""
    <div class="party">الجهة:
      <span class="party-name">{ent['name'] if ent else '—'}</span></div><br/>
    <table class="items">
      <tr><th>الوزن (جم 18)</th><th>سعر الجرام</th><th>القيمة (ريال)</th></tr>
      {_rows(rows)}
    </table><br/>
    <div class="tafqeet">فقط: {tafqeet(f['amount'])}</div>
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
            hdr = ["اسم العامل", "الأساسي", "ساعات", "معامل", "الإضافي",
                   "الغياب", "الخصم", "الفاقد/ذهب", "خصم/ذهب", "التارجت",
                   "المكافأة", "سحب/نقدي", "سحب/بنك", "الصافي"]
            keys = ["name", "basic_salary", "hours", "overtime_rate",
                    "overtime", "absence", "deduction", "gold_loss",
                    "gold_deduction", "target_amount", "bonus",
                    "draw_cash", "draw_bank", "net_salary"]
        rows = [[r.get("name")] + [_w(r.get(k, 0), 2) for k in keys[1:]]
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
                           f'<td>{_w(i["reg"])}</td>',
                           f'<td>{_w(i["standing"])}</td>') + "</tr>"
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
                 thw(_w(d["total_reg"])),
                 thw(_w(d["total_standing"])))}</tr>
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
            f'<td>{_w(abs(r["gold"]))}</td>'
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
      <tr>{cells(thw("الجهة", 34), thw("ذهب 18 (جم)", 18),
                 thw("الحالة", 12), thw("الأجور (ريال)", 24),
                 thw("الحالة", 12))}</tr>
      {body_rows}
    </table>

    <table class="items totals" width="100%" cellspacing="0"
           cellpadding="6" style="margin-top:8px">
      <tr>{cells(thw("الإجمالي", 34), thw("مدين", 18),
                 thw("دائن", 18), thw("الصافي", 30))}</tr>
      <tr>{cells('<td class="r"><b>ذهب 18 (جم)</b></td>',
                 f'<td>{_w(dg)}</td>', f'<td>{_w(cg)}</td>',
                 f'<td><b>{_w(ng)}</b> — {_side(ng)}</td>')}</tr>
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
        if doc_type in ("workshop_losses", "workshop_losses_log"):
            return en(_tpl_workshop_losses(conn, doc_id,
                                           kw.get("date_from"),
                                           kw.get("date_to")))
        if doc_type == "models_catalog":
            return en(_tpl_models_catalog(conn, doc_id,
                                          kw.get("mode", "all"),
                                          kw.get("sort", "az"),
                                          kw.get("expanded")))
        if doc_type == "model_photos":
            return en(_tpl_model_photos(conn, doc_id,
                                        kw.get("min_count", 3),
                                        kw.get("mode", "all"),
                                        kw.get("sort", "az")))
        if doc_type == "dash_panel":
            return en(_tpl_dash_panel(
                conn, doc_id, kw.get("title", ""),
                kw.get("kind", "accounts"), kw.get("codes"),
                kw.get("ratios"), kw.get("date_from"),
                kw.get("date_to")))
        if doc_type == "balance_tree":
            return en(_tpl_balance_tree(conn, doc_id, kw.get("date_to"),
                                        kw.get("max_level", 3),
                                        kw.get("hide_zero", True)))
        if doc_type == "trial_balance":
            return en(_tpl_trial_balance(conn, doc_id, kw.get("date_from"),
                                         kw.get("date_to"),
                                         kw.get("include_zero", False)))
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
    #   • الرقم التجميعي 0001: سجل واحد مربوط بأول دفعة فقط
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
            tdw(en(r["work_order_no"])), tdw(_w(r["gold_weight"])),
            tdw(_w(r["small_stones"])), tdw(_w(r["big_stones"])),
            tdw(_w(r["stones_after_discount"])),
            tdw(_w(r["standing_gold"])),
            tdw(_w(r["registered_weight"]))) + "</tr>"
    if not body:
        body = f'<tr><td {TD} colspan="7">لا توجد أطقم</td></tr>'

    head = cells(thw("رقم التشغيل"), thw("الذهب"), thw("الفصوص"),
                 thw("الأحجار"), thw("بعد الخصم"), thw("الذهب القائم"),
                 thw("الوزن المقيد"))
    foot = cells(thw("الإجمالي"), thw(_w(t_gold)), thw(_w(t_small)),
                 thw(_w(t_big)), thw(_w(t_after)), thw(_w(t_stand)),
                 thw(_w(t_reg)))
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
            tdw(_w(r["weight"])),
            f'<td class="r">{r["description"] or ""}</td>') + "</tr>"
        for r in rows)
    if not body:
        body = f'<tr><td {TD} colspan="5">لا توجد سندات</td></tr>'
    tot = round(sum(float(r["weight"] or 0) for r in rows), 3)
    head = cells(thw("رقم السند"), thw("التاريخ"), thw("نوع الفاقد"),
                 thw("الوزن (جم)"), thw("البيان"))
    foot = cells(thw("الإجمالي"), thw(""), thw(f"{len(rows)} سند"),
                 thw(_w(tot)), thw(""))
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
            tdw(_w(gd)), tdw(_w(gc)), tdw(_w(gb)),
            tdw(_w(cd, 2)), tdw(_w(cc, 2)),
            tdw(_w(cb, 2))) + "</tr>"
    if not body:
        body = f'<tr><td {TD} colspan="7">لا توجد حسابات</td></tr>'
    head = cells(thw("الحساب"), thw("مدين ذهب"), thw("دائن ذهب"),
                 thw("رصيد الذهب"), thw("مدين نقد"), thw("دائن نقد"),
                 thw("رصيد النقد"))
    foot = cells(thw("الإجمالي"), thw(""), thw(""), thw(_w(tg)),
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
            f'<td><b>{_w(sec["gold"])}</b></td>') + "</tr>")
        for r in sec["rows"]:
            if r["level"] == 1:
                continue
            pad = 12 * (r["level"] - 1)
            body += ("<tr>" + cells(
                f'<td class="r" style="padding-right:{pad}px">'
                f'{r["name"]}</td>',
                f'<td>{en(r["code"])}</td>',
                f'<td>{_w(r["cash"], 2)}</td>',
                f'<td>{_w(r["gold"])}</td>') + "</tr>")
    if not body:
        body = f'<tr><td {TD} colspan="4">لا توجد أرصدة</td></tr>'

    ag, ac = b["assets"]
    rg, rc = b["right_side"]
    ok = b["balanced_cash"] and b["balanced_gold"]
    head = cells(thw("الحساب", 42), thw("الكود", 12),
                 thw("النقد / الأجور (ريال)", 23),
                 thw("الذهب (جم 18)", 23))
    meta = f'''{TBL}
      <tr>{cells(thw("حتى تاريخ"), f'<td>{en(date_to or today)}</td>',
                 thw("مستوى التفصيل"), f'<td>{en(max_level)}</td>')}</tr>
    </table><br/>'''
    totals = f'''
    <table class="items totals" width="100%" cellspacing="0"
           cellpadding="6" style="margin-top:8px">
      <tr>{cells(thw("البيان", 40), thw("النقد (ريال)", 30),
                 thw("الذهب (جم 18)", 30))}</tr>
      <tr>{cells('<td class="r"><b>إجمالي الأصول</b></td>',
                 f'<td><b>{_w(ac, 2)}</b></td>',
                 f'<td><b>{_w(ag)}</b></td>')}</tr>
      <tr>{cells('<td class="r"><b>الخصوم + حقوق الملكية + النتيجة</b>'
                 '</td>',
                 f'<td><b>{_w(rc, 2)}</b></td>',
                 f'<td><b>{_w(rg)}</b></td>')}</tr>
      <tr>{cells('<td class="r">الفرق</td>',
                 f'<td>{_w(b["diff_cash"], 2)}</td>',
                 f'<td>{_w(b["diff_gold"])}</td>')}</tr>
    </table>
    <div {WIDE} style="margin-top:6px">
      <b>{"✔ الميزانية متوازنة في البعدين" if ok
          else "✘ يوجد عجز — راجع القيود"}</b>
    </div>'''
    table = f"{TBL}<tr>{head}</tr>{body}</table>"
    return (_header("الميزانية العمومية", "—", date_to or today,
                    show_meta=False) + meta + table + totals)


def _tpl_trial_balance(conn, _id=0, date_from=None, date_to=None,
                       include_zero=False):
    """قالب ميزان المراجعة — أرصدة أول المدة والحركة والإقفال."""
    from models.reports import trial_balance
    tb = trial_balance(conn, date_from, date_to, bool(include_zero))
    today = _qd(QtCore.QDate.currentDate())
    types = {"asset": "أصل", "liability": "خصم", "equity": "حقوق ملكية",
             "revenue": "إيراد", "expense": "مصروف", "bridge": "وسيط"}

    body = ""
    for r in tb["rows"]:
        body += ("<tr>" + cells(
            f'<td>{en(r["code"])}</td>',
            f'<td class="r">{r["name"]}</td>',
            f'<td>{types.get(r["type"], r["type"])}</td>',
            f'<td>{_w(r["open_gold"])}</td>',
            f'<td>{_w(r["gold_debit"])}</td>',
            f'<td>{_w(r["gold_credit"])}</td>',
            f'<td>{_w(r["close_gold"])}</td>',
            f'<td>{_w(r["open_cash"], 2)}</td>',
            f'<td>{_w(r["cash_debit"], 2)}</td>',
            f'<td>{_w(r["cash_credit"], 2)}</td>',
            f'<td>{_w(r["close_cash"], 2)}</td>') + "</tr>")
    if not body:
        body = f'<tr><td {TD} colspan="11">لا توجد حركة في الفترة</td></tr>'

    t = tb["totals"]
    body += ("<tr>" + cells(
        '<td></td>', '<td class="r"><b>الإجمالي</b></td>', '<td></td>',
        f'<td><b>{_w(t["open_gold"])}</b></td>',
        f'<td><b>{_w(t["gold_debit"])}</b></td>',
        f'<td><b>{_w(t["gold_credit"])}</b></td>',
        f'<td><b>{_w(t["close_gold"])}</b></td>',
        f'<td><b>{_w(t["open_cash"], 2)}</b></td>',
        f'<td><b>{_w(t["cash_debit"], 2)}</b></td>',
        f'<td><b>{_w(t["cash_credit"], 2)}</b></td>',
        f'<td><b>{_w(t["close_cash"], 2)}</b></td>') + "</tr>")

    head = cells(thw("الكود", 7), thw("الحساب", 21), thw("النوع", 8),
                 thw("افتتاح ذهب", 8), thw("مدين ذهب", 8),
                 thw("دائن ذهب", 8), thw("إقفال ذهب", 8),
                 thw("افتتاح نقد", 8), thw("مدين نقد", 8),
                 thw("دائن نقد", 8), thw("إقفال نقد", 8))
    meta = f'''{TBL}
      <tr>{cells(thw("من تاريخ"), f'<td>{en(date_from or "البداية")}</td>',
                 thw("إلى تاريخ"), f'<td>{en(date_to or today)}</td>',
                 thw("عدد الحسابات"), f'<td>{en(len(tb["rows"]))}</td>')}</tr>
    </table><br/>'''
    ok = t["balanced_gold"] and t["balanced_cash"]
    verdict = f'''
    <div {WIDE} style="margin-top:6px">
      <b>{"✔ الميزان متوازن في البعدين — مدين الفترة = دائنها وأرصدة "
          "الإقفال مجموعها صفر"
          if ok else "✘ الميزان غير متوازن — راجع القيود"}</b>
    </div>'''
    table = f"{TBL}<tr>{head}</tr>{body}</table>"
    return (_header("ميزان المراجعة", "—", date_to or today,
                    show_meta=False) + meta + table + verdict)


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
        models.sort(key=lambda m: str(m["model"]), reverse=True)
    elif sort == "most":
        models.sort(key=lambda m: (-_n(m), str(m["model"])))
    elif sort == "least":
        models.sort(key=lambda m: (_n(m), str(m["model"])))
    else:
        models.sort(key=lambda m: str(m["model"]))

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
            f'<td><b>{_w(hw)}</b></td>', '<td></td>') + "</tr>")
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
                f'<td>{en(n)}</td>', f'<td>{_w(w)}</td>',
                '<td></td>') + "</tr>")
            for i in items:
                body += ("<tr>" + cells(
                    f'<td class="r" style="padding-right:30px">'
                    f'{en(i["wo"])}</td>',
                    '<td></td>', f'<td>{_w(i["reg"])}</td>',
                    f'<td>{i["holder"]}  ·  {en(i["date"])}</td>')
                    + "</tr>")
    if not body:
        body = f'<tr><td {TD} colspan="4">لا توجد موديلات</td></tr>'

    tin = sum(m["in_weight"] for m in models)
    tout = sum(m["out_weight"] for m in models)
    head = cells(thw("الموديل / رقم التشغيل", 40), thw("العدد", 12),
                 thw("الوزن المقيد (جم)", 22), thw("الجهة / التاريخ", 26))
    foot = cells(thw(f"الإجمالي — {len(models)} موديل"), thw(""),
                 thw(_w(tin + tout if mode == "all"
                        else tin if mode == "in_stock" else tout)),
                 thw(""))
    meta = (f'<div {WIDE}>العرض: <b>{labels.get(mode, mode)}</b>'
            f' &nbsp;·&nbsp; المعروض موسّعاً: '
            f'<b>{en(len(expanded))}</b> موديل</div>')
    table = f"{TBL}<tr>{head}</tr>{body}<tr>{foot}</tr></table>"
    return (_header("دليل الموديلات", "—", today, show_meta=False)
            + meta + table)


def _tpl_dash_panel(conn, _id=0, title="", kind="accounts", codes=None,
                    ratios=None, date_from=None, date_to=None):
    """قالب لوحة التحكم — مطابق لما يظهر على الشاشة."""
    from models import dash_panels as dp
    today = _qd(QtCore.QDate.currentDate())

    if kind == "scrap":
        rows = dp.scrap_rows(conn)
        body = "".join(
            "<tr>" + cells(f'<td class="r">عيار {en(r["karat"])}</td>',
                           f'<td>{_w(r["actual"])}</td>',
                           f'<td>{_w(r["eq18"])}</td>') + "</tr>"
            for r in rows)
        ta = round(sum(r["actual"] for r in rows), 3)
        te = round(sum(r["eq18"] for r in rows), 3)
        head = cells(thw("العيار", 34), thw("الوزن الفعلي (جم)", 33),
                     thw("المكافئ بعيار 18 (جم)", 33))
        foot = cells(thw("الإجمالي"), thw(_w(ta)), thw(_w(te)))
        table = f"{TBL}<tr>{head}</tr>{body}<tr>{foot}</tr></table>"
        note = (f'<div {WIDE}>صندوق الكسر حساب واحد (1310) يضمّ '
                f'الأعيرة الأربعة؛ الرصيد المحاسبي بمكافئ 18.</div>')
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
            f'<td>{_w(r["gold_debit"])}</td>',
            f'<td>{_w(r["gold_credit"])}</td>',
            f'<td>{_w(r["gold_balance"])}</td>',
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
    foot = cells(thw("الإجمالي"), thw(_w(t["gold_debit"])),
                 thw(_w(t["gold_credit"])), thw(_w(t["gold_balance"])),
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


def _tpl_model_photos(conn, _id=0, min_count=3, mode="all", sort="az"):
    """ورقة صور الموديلات — أربع صور في كل صفحة A4.

    تُطبع صور الموديلات التي بلغ عددها الحدّ المطلوب فقط (ثلاثة
    فأكثر افتراضياً)، فلا تُهدر أوراق على موديلات نادرة.

    كل صفحة أربع صور في شبكة 2×2 بأبعاد تناسب A4، وتحت كل صورة اسم
    موديلها. وما زاد ينتقل للصفحة التالية تلقائياً.
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

    if sort == "za":
        picked.sort(key=lambda x: str(x[0]["model"]), reverse=True)
    elif sort == "most":
        picked.sort(key=lambda x: (-x[2], str(x[0]["model"])))
    elif sort == "least":
        picked.sort(key=lambda x: (x[2], str(x[0]["model"])))
    else:
        picked.sort(key=lambda x: str(x[0]["model"]))

    today = _qd(QtCore.QDate.currentDate())
    if not picked:
        body = ('<div style="text-align:center;padding:40px">'
                'لا توجد موديلات بصور تبلغ الحدّ المطلوب '
                f'({en(min_count)} قطع فأكثر)</div>')
        return (_header("صور الموديلات", "—", today, show_meta=False)
                + body)

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

    # شبكة 2×2 لكل صفحة — الأبعاد بالنسبة المئوية من عرض A4
    cells_html = []
    for m, p_img, n in picked:
        uri = _data_uri(p_img)
        if not uri:
            continue
        cells_html.append(
            '<td class="ph">'
            '<div class="phbox"><img src="' + uri + '" /></div>'
            '<div class="phcap">الموديل ' + str(m["model"])
            + '  ·  ' + str(n) + ' قطعة</div></td>')

    pages = ""
    per_page = 4
    total_pages = (len(cells_html) + per_page - 1) // per_page
    for pg in range(total_pages):
        chunk = cells_html[pg * per_page:(pg + 1) * per_page]
        while len(chunk) < per_page:
            chunk.append('<td class="ph"></td>')
        brk = ' style="page-break-before:always"' if pg else ""
        pages += (
            '<table class="photos" width="100%" cellspacing="0"'
            ' cellpadding="0"' + brk + ">"
            "<tr>" + chunk[0] + chunk[1] + "</tr>"
            "<tr>" + chunk[2] + chunk[3] + "</tr>"
            "</table>")

    css = """
    <style>
      table.photos { table-layout: fixed; width: 100%; }
      table.photos td.ph {
        width: 50%; height: 128mm; vertical-align: top;
        padding: 3mm; text-align: center;
      }
      .phbox {
        height: 108mm; border: 1px solid #D8CDB4; border-radius: 4px;
        display: table-cell; vertical-align: middle; width: 100%;
        text-align: center; background: #FFFFFF;
      }
      .phbox img { max-width: 96%; max-height: 104mm; }
      .phcap {
        margin-top: 2mm; font-size: 11pt; font-weight: bold;
        color: #4A3A1E;
      }
    </style>
    """
    meta = ('<div ' + WIDE + '>الحدّ الأدنى للعدد: <b>'
            + en(min_count) + '</b> &nbsp;·&nbsp; موديلات مطبوعة: <b>'
            + en(len(cells_html)) + '</b> &nbsp;·&nbsp; الصفحات: <b>'
            + en(total_pages) + "</b></div>")
    return (_header("صور الموديلات", "—", today, show_meta=False)
            + css + meta + pages)


# خريطة نوع المستند ← قالبه. تُبنى من الدوال الموجودة فعلاً،
# فلا تنكسر إن أُعيد ترتيب الملف.
BUILDERS = {
    "invoice": _tpl_invoice, "invoices": _tpl_invoice,
    "voucher": _tpl_voucher, "vouchers": _tpl_voucher,
    "journal": _tpl_journal, "manual": _tpl_journal,
    "melting": _tpl_melting, "melting_ops": _tpl_melting,
    "purchase": _tpl_purchase, "purchases": _tpl_purchase,
    "fixing": _tpl_fixing, "fixing_ops": _tpl_fixing,
    "work_orders": _tpl_work_order, "wo_supply": _tpl_work_order,
    "wo_adjust": _tpl_work_order,
    "workshop_losses": _tpl_workshop_losses,
    "workshop_losses_log": _tpl_workshop_losses,
    "workshop_accounts": _tpl_workshop_accounts,
    "balance_tree": _tpl_balance_tree,
    "trial_balance": _tpl_trial_balance,
    "models_catalog": _tpl_models_catalog,
    "dash_panel": _tpl_dash_panel,
    "model_photos": _tpl_model_photos,
}

DOC_LABELS = {
    "invoices": "فاتورة/مرتجع", "vouchers": "سند قبض/صرف",
    "purchases": "فاتورة مشتريات", "melting_ops": "صب وتصفية",
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
    return (f"<html dir='rtl'><head><meta charset='utf-8'>{BASE_CSS}</head>"
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
                        "customer_analytics", "turnover",
                        "mfg_target", "mfg_salary")
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
