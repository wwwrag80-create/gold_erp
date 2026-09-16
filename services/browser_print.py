# -*- coding: utf-8 -*-
"""محرك طباعة مستقل تماماً عن Qt (browser_print).

سبب وجوده: محرك `QTextDocument` في Qt يدعم مجموعة محدودة جداً من CSS،
فيتجاهل عرض الجداول وارتفاعها والاتجاه، وتخرج المستندات منكمشة مهما
ضُبطت. الحل الجذري: توليد صفحة HTML كاملة وفتحها في المتصفح الافتراضي
للجهاز — ومحركات المتصفحات (Edge/Chrome/Firefox) تدعم CSS كاملاً
والاتجاه العربي والطباعة إلى A4 بدقة.

الاستخدام:
    browser_print.open_document("invoices", invoice_id)
    browser_print.save_pdf_html("invoices", invoice_id, path)

لا يحتاج أي مكتبة خارجية — المتصفح موجود على كل جهاز.
"""
import os
import tempfile
import threading
import webbrowser
from pathlib import Path

import config

# ══════════════════════════════════════════════════════════════════
# أنماط الطباعة الكاملة — يدعمها المتصفح بالكامل خلاف محرك Qt
# ══════════════════════════════════════════════════════════════════
PRINT_CSS = """
<style>
  @page {
    size: %(size)s;
    margin: %(margin)s;
  }
  * { box-sizing: border-box; }
  html, body {
    direction: rtl;
    margin: 0;
    padding: 0;
    width: 100%%;
    font-family: 'Segoe UI', 'Cairo', 'Tahoma', sans-serif;
    font-size: 11pt;
    color: #111;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }

  /* الإطار الخارجي يملأ الورقة طولاً وعرضاً */
  .sheet {
    width: 100%%;
    min-height: %(minheight)s;
    border: 1.5px solid #333;
    padding: 10px;
    display: flex;
    flex-direction: column;
  }
  .sheet-body { flex: 1 1 auto; }

  /* كل الجداول بعرض الصفحة كاملاً */
  table { width: 100%%; border-collapse: collapse; direction: rtl;
          table-layout: auto; margin: 6px 0; }
  table.items, table.wide, table.boxes, table.titlebar,
  table.plain, table.sig, table.frame { width: 100%%; }

  table.items th, table.items td,
  table.wide td, table.boxes td, table.titlebar td {
    border: 1px solid #999;
    padding: 6px 5px;
    text-align: center;
    vertical-align: middle;
    word-wrap: break-word;
  }
  table.items th, table.titlebar td, .lbl, th {
    background: #EFEFEF;
    font-weight: bold;
    white-space: nowrap;
  }
  table.items td.r, table.wide td.val { text-align: right; }
  table.items tr.total td, table.items td.nw { white-space: nowrap; }
  tr.total td { background: #EFEFEF; font-weight: bold; }

  /* الترويسة */
  table.lh { border-bottom: 2px solid #999; }
  table.lh td { border: none; padding: 4px; vertical-align: middle; }
  table.plain td { border: none; padding: 2px; vertical-align: top; }
  table.sig td { border: none; padding: 8px; text-align: center; }
  table.titlebar td { font-size: 15pt; }

  .co     { font-size: 14pt; font-weight: bold; white-space: nowrap; }
  .co-sub { font-size: 9.5pt; white-space: nowrap; }
  /* عزل اتجاهي آمن: لا يقلب الحروف العربية */
  .num    { unicode-bidi: isolate; }

  /* صف الإجماليات البارز أسفل كشف الأرصدة */
  table.totals th, table.totals td { background: #F2EEE4; font-size: 9pt; }
  table.totals td b { font-size: 10pt; }

  /* جداول قسم التصنيع: كل الأعمدة في صفحة واحدة */
  table.compact { table-layout: fixed; width: 100%%; font-size: 8pt; }
  table.compact th, table.compact td {
      padding: 2px 2px; font-size: 8pt; white-space: nowrap;
      overflow: hidden; text-overflow: clip; word-break: keep-all; }
  table.compact th { font-weight: bold; }
  .note   { font-size: 9.5pt; color: #555; }
  img     { max-height: 110px; }

  /* لوحات تحليل المبيعات */
  table.ca-wrap { border-spacing: 6px 0; border-collapse: separate; }
  .ca-head  { width: 25%%; border: 2px solid #333; padding: 9px 4px;
              text-align: center; }
  .ca-title { font-size: 10pt; white-space: nowrap; }
  .ca-value { font-size: 15pt; font-weight: bold; }
  .ca-detail{ width: 25%%; vertical-align: top; }
  table.ca-tbl th, table.ca-tbl td { border: 1px solid #999; padding: 3px;
                                     text-align: center; font-size: 9pt; }

  /* جدولا الرصيد الصغيران أعلى اللوحات (ذهب · نقد) */
  table.ca-bal { border-collapse: collapse; font-size: 9.5pt; }
  table.ca-bal th, table.ca-bal td { border: 1px solid #777; padding: 4px;
                                     text-align: center; white-space: nowrap; }
  table.ca-bal th { background: #EFEFEF; font-weight: bold; }

  @media print {
    .noprint { display: none !important; }
    .sheet { border: 1.5px solid #333; }
  }

  /* شريط الأدوات على الشاشة فقط */
  .toolbar {
    background: #8A6D1D; color: #fff; padding: 10px;
    text-align: center; font-size: 13pt; margin-bottom: 8px;
  }
  .toolbar button {
    font-size: 13pt; padding: 7px 22px; margin: 0 6px; cursor: pointer;
    border: none; border-radius: 5px; background: #fff; color: #8A6D1D;
    font-weight: bold;
  }
</style>
"""


def _page_setup(doc_type):
    """اتجاه الصفحة والهوامش بحسب نوع المستند."""
    wide = doc_type in ("statement", "journal", "manual", "balances",
                        "customer_analytics", "turnover", "balance_tree",
                        "dash_panel", "aging", "day_close",
                        "mfg_target", "mfg_salary")
    if wide:
        # تقارير التصنيع عريضة الأعمدة — هوامش أضيق لتتسع الصفحة
        margin = "5mm" if doc_type in ("mfg_target", "mfg_salary") else "8mm"
        return {"size": "A4 landscape", "margin": margin,
                "minheight": "180mm"}
    return {"size": "A4 portrait", "margin": "8mm", "minheight": "265mm"}


def build_page(doc_type, doc_id, auto_print=True, **kw):
    """يبني صفحة HTML كاملة جاهزة للطباعة من المتصفح."""
    from services import print_manager
    # المتصفح يطبّق RTL صحيحاً، فتُكتب الأعمدة بترتيبها الطبيعي
    prev = print_manager.RTL_ORDER_OVERRIDE
    print_manager.RTL_ORDER_OVERRIDE = True
    try:
        inner = print_manager.build_body(doc_type, doc_id, **kw)
    finally:
        print_manager.RTL_ORDER_OVERRIDE = prev
    setup = _page_setup(doc_type)
    toolbar = ""
    script = ""
    if auto_print:
        toolbar = (
            '<div class="toolbar noprint">'
            '<button onclick="window.print()">🖨 طباعة</button>'
            '<button onclick="window.close()">إغلاق</button>'
            ' &nbsp; اضغط «طباعة» ثم اختر الطابعة أو «حفظ بصيغة PDF»'
            '</div>')
        script = ("<script>window.addEventListener('load',function(){"
                  "setTimeout(function(){window.print();},350);});</script>")
    return (
        "<!DOCTYPE html>\n"
        "<html dir='rtl' lang='ar'><head><meta charset='utf-8'>"
        f"<title>{config.COMPANY_NAME}</title>"
        + (PRINT_CSS % setup) +
        f"</head><body dir='rtl'>{toolbar}"
        f"<div class='sheet'><div class='sheet-body'>{inner}</div></div>"
        f"{script}</body></html>")


def open_document(doc_type, doc_id, auto_print=True, **kw):
    """يحفظ المستند صفحةً مؤقتة ويفتحها في المتصفح الافتراضي للطباعة."""
    html = build_page(doc_type, doc_id, auto_print=auto_print, **kw)
    out_dir = Path(tempfile.gettempdir()) / "jadeite_print"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{doc_type}_{doc_id}.html"
    path.write_text(html, encoding="utf-8")
    url = path.resolve().as_uri()

    # ══ فتح المتصفح في خيط منفصل ══
    # `webbrowser.open_new_tab` **محجوب**: ينتظر إقلاع المتصفح كاملاً
    # (ثوانٍ عند أول فتح)، وخيط الواجهة متوقّف طوال ذلك فيعلن ويندوز
    # «لا يستجيب» — وهو سبب الشاشة البيضاء بعد حفظ التعديل.
    # الفتح في خيط منفصل يُعيد التحكم للواجهة فوراً.
    def _launch():
        try:
            webbrowser.open_new_tab(url)
        except Exception:
            try:
                if hasattr(os, "startfile"):
                    os.startfile(str(path))
            except Exception:
                pass

    try:
        threading.Thread(target=_launch, daemon=True,
                         name="JadeitePrintOpen").start()
    except Exception:
        _launch()
    return str(path)


def save_html(doc_type, doc_id, path, **kw):
    """يحفظ المستند ملف HTML في مسار يختاره المستخدم."""
    html = build_page(doc_type, doc_id, auto_print=False, **kw)
    Path(path).write_text(html, encoding="utf-8")
    return str(path)
