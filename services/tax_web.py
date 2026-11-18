# -*- coding: utf-8 -*-
"""المبيعات الضريبية والمشتريات الضريبية من رابط المدير (5.8.5).

شاشتا البرنامج نفسهما بأقسامهما — في «المزيد» من رئيسية الرابط، وخلف رمز
لوحة تسجيل العمليات (كتسجيل العمليات تماماً):

* **المبيعات الضريبية**: فاتورة ضريبية (ضريبية لمحلٍ أو شركة · مبسطة لفرد أو
  «عميل نقدي») بإدخالٍ يدوي حرّ أو من أطقم الخزنة، وكل طرق التسعير ومنها
  «شامل الضريبة» — ومرتجع مبيعات (إشعار دائن) على فاتورته — والسجل.
* **المشتريات الضريبية**: فاتورة مشتريات ذهب، ومرتجعها، والمشتريات النقدية
  (مصروفات وأصول: مشتريات أو مرتجع)، والسجل.

**الترحيل بدوالّ البرنامج نفسها** (`tax_free` · `tax_invoices` ·
`set_purchases` · `purchases`) بعد تحقّقٍ صارم من كل خانة، وفي حراسة الرابط
نفسها (`manager_web._guarded`): ضغطةٌ واحدة = مستندٌ واحد، ومعاملةٌ ذرّية،
والتسجيل مسموحٌ من البرنامج. ويُكتب باسم «رابط المدير».
"""
import json

from services import manager_web as M

_e, _m = M._e, M._m

PAGES = {"taxs": "المبيعات الضريبية", "taxp": "المشتريات الضريبية"}
TABS = {
    "taxs": (("inv", "فاتورة ضريبية", "sale"),
             ("ret", "مرتجع مبيعات (إشعار دائن)", "sale_return"),
             ("reg", "السجل", "all")),
    "taxp": (("inv", "فاتورة مشتريات ذهب", "purchase"),
             ("ret", "مرتجع مشتريات", "sale_return"),
             ("cash", "المشتريات النقدية (مصروفات وأصول)", "other"),
             ("reg", "السجل", "all")),
}
POST_KINDS = ("tax_sale", "tax_sale_ret", "tax_pur", "tax_pur_ret",
              "cash_pur")
CREDIT = "credit"
WALKIN = "walkin"


# ══════════════════════════ بيانات النماذج ══════════════════════════
def _pay_opts(conn, credit_text):
    """«آجل» ثم الصناديق والبنوك — آخرها إضافةً أولاً (كخانة الدفع)."""
    from models.accounts import pay_accounts, pay_kind
    out = [{"id": CREDIT, "label": credit_text}]
    for r in sorted(pay_accounts(conn), key=lambda x: -int(x["id"])):
        word = "صندوق" if pay_kind(r["code"]) == "cash" else "بنك"
        out.append({"id": int(r["id"]), "label": f"{r['name']} ({word})"})
    return out


def _acc_opts(rows):
    return [{"id": int(r["id"]), "code": r["code"],
             "label": f"{r['code']} — {r['name']}"} for r in rows]


def _pricing_opts():
    from models import tax_invoices as tx
    return ([{"k": k, "label": lbl} for k, lbl in tx.TAX_PRICING]
            + [{"k": k, "label": lbl} for k, lbl, _b in tx.INCL_PRICING])


def _base(conn, mode):
    import config
    from models import tax_invoices as tx
    from services import karat_view as kv
    return {"mode": mode, "k": int(kv.active()), "unit": M._unit(),
            "today": M._today().isoformat(), "karats": list(M.KARATS),
            "vat": float(getattr(config, "VAT_RATE", 0.15) or 0),
            "riyal": list(tx.RIYAL), "incl": dict(tx.INCL_BASE),
            "pricing": _pricing_opts()}


def search_parties(conn, q, std=False, limit=30):
    """أي حساب من دليل جهات التعامل (عميل · مورد · جهة · نوعٌ أنشأه
    المستخدم) — بنوعه ورقمه الضريبي. `std`: ذوو الرقم الضريبي الصحيح."""
    from services.fatoora import profile as pf
    n = M._norm(q)
    if not n:
        return []
    rows = conn.execute(
        "SELECT id, name, entity_type, vat_number FROM entities WHERE"
        " is_deleted=0 AND entity_type<>'internal' ORDER BY name").fetchall()
    starts, has = [], []
    for r in rows:
        if std and not pf.valid_vat(r["vat_number"] or ""):
            continue
        nm = M._norm(r["name"])
        if nm.startswith(n):
            starts.append(r)
        elif n in nm:
            has.append(r)
    out = []
    for r in (starts + has)[:limit]:
        vat = (r["vat_number"] or "").strip()
        sub = M._type_label(r["entity_type"])
        out.append({"id": r["id"], "label": r["name"],
                    "sub": sub + (f" · {vat}" if vat else ""),
                    "vat": vat, "type": r["entity_type"]})
    return out


def _sale_label(r):
    sub = {"standard": "ضريبية", "simplified": "مبسطة"}.get(
        r.get("tax_subtype") or "", "")
    who = (r.get("buyer_name") or "").strip() or r.get("customer_name") or ""
    return (f"{r['invoice_no']} — {who}" + (f" ({sub})" if sub else "")
            + f" — {_m(r['grand_total'])} ريال — {r['invoice_date']}")


def _pur_label(r):
    return (f"{r['doc_no']} — {r['supplier_name']} — فاتورة المورد "
            f"{r['supplier_inv_no']} — {_m(r['total'])} ريال — "
            f"{r['doc_date']}")


def api(conn, rest, query):
    """`/tax/api/<ما يُطلب>` — JSON للنماذج."""
    what = rest[0] if rest else ""
    q = str(query.get("q") or "")[:60]
    if what == "party":
        return search_parties(conn, q, std=query.get("std") == "1")
    if what == "wo":
        return M.wo_info(conn, query.get("no"), "sale",
                         M._date(query.get("d")))
    if what == "sret":
        return _sale_returnable(conn, query.get("id"))
    if what == "pret":
        return _pur_returnable(conn, query.get("id"))
    if what == "bal":
        return _stock_balance(conn, query.get("id"))
    return {"ok": False, "error": "غير موجود"}


def _stock_balance(conn, aid):
    from models import tax_free
    from services import karat_view as kv
    try:
        b = tax_free.balance(conn, int(aid))
    except Exception:                                  # noqa: BLE001
        return {"ok": False}
    return {"ok": True, "text": f"رصيده الآن: {M._w(b)} {kv.unit()}"
            + (" — سالب (مسموح)" if b < -0.0005 else "")}


def _price_txt(pricing, x, k):
    from services import karat_view as kv
    rate = _m(kv.rate(x.get("wage") or 0, k))
    if pricing == "piece":
        return (f"سعر الطقم {_m(x.get('piece_price') or 0)}"
                + (f" (جرام {_m(x.get('gold_price') or 0)})"
                   if x.get("gold_price") else ""))
    if pricing == "gram":
        return f"جرام {_m(x.get('gold_price') or 0)} + أجر {rate}"
    return f"أجر {rate}/جم"


def _sale_returnable(conn, iid):
    from models import tax_invoices as tx
    from models.accounts import pay_label
    from services import karat_view as kv
    try:
        iid = int(iid)
    except (TypeError, ValueError):
        return {"ok": False, "error": "اختر الفاتورة"}
    o = conn.execute("SELECT i.*, e.name customer_name FROM invoices i JOIN"
                     " entities e ON e.id=i.customer_id WHERE i.id=?",
                     (iid,)).fetchone()
    if not o or not (o["pricing"] or ""):
        return {"ok": False, "error": "الفاتورة غير موجودة"}
    o = dict(o)
    rows = []
    for x in tx.returnable(conn, iid):
        k = int(x["karat"] or kv.active())
        rows.append({"id": x["item_id"], "no": x["wo_no"],
                     "pieces": int(x["pieces"] or 0), "k": k,
                     "w18": x["weight"], "left18": x["left"],
                     "w": round(kv.g(x["weight"], k), 2),
                     "left": round(kv.g(x["left"], k), 2),
                     "net": round(float(x["wages"] or 0)
                                  + float(x["gold_value"] or 0), 2),
                     "price": _price_txt(o["pricing"], x, k)})
    pm = o.get("pay_mode") or "credit"
    who = (o.get("buyer_name") or "").strip() or o["customer_name"]
    return {"ok": True, "rows": rows, "no": o["invoice_no"], "who": who,
            "disc": float(o.get("discount") or 0),
            "orig_net": round(float(o.get("total_wages") or 0)
                              + float(o.get("gold_value") or 0), 2),
            "info": (f"{tx.SUBTYPE_LABEL.get(o.get('tax_subtype') or '', 'فاتورة')}"
                     f" · المشتري: {who} · الدفع: "
                     f"{pay_label(conn, pm, o.get('pay_account_id'))}"
                     "\nيُردّ بسعر الفاتورة نفسها ويُخصم من حساب المشتري"
                     + ("." if pm == "credit" else
                        " — والردّ النقدي بسند صرفٍ يدوي."))}


def _pur_returnable(conn, did):
    from models import set_purchases as sp
    from services import karat_view as kv
    try:
        did = int(did)
    except (TypeError, ValueError):
        return {"ok": False, "error": "اختر الفاتورة"}
    o = conn.execute("SELECT d.*, e.name supplier_name FROM set_purchases d"
                     " JOIN entities e ON e.id=d.supplier_id WHERE d.id=?",
                     (did,)).fetchone()
    if not o:
        return {"ok": False, "error": "الفاتورة غير موجودة"}
    o = dict(o)
    rows = []
    for x in sp.returnable(conn, did):
        k = int(x["karat"] or kv.active())
        part = bool(x["bulk"] or x.get("free"))
        rows.append({"id": x["line_id"], "no": x["wo_no"],
                     "pieces": int(x["pieces"] or 0), "k": k,
                     "w18": float(x["registered"] or 0),
                     "left18": x["left"], "part": part,
                     "w": round(kv.g(x["registered"] or 0, k), 2),
                     "left": round(kv.g(x["left"], k), 2),
                     "net": round(float(x["net"] or 0), 2),
                     "why": x["why"],
                     "price": _price_txt(o["pricing"], x, k)})
    return {"ok": True, "rows": rows, "no": o["doc_no"],
            "who": o["supplier_name"], "disc": float(o.get("discount") or 0),
            "orig_net": float(o.get("net") or 0),
            "info": (f"المورد: {o['supplier_name']} · فاتورة المورد "
                     f"{o['supplier_inv_no']}\nيُعاد بسعر الفاتورة نفسها "
                     "ويُخصم من حساب المورد.")}


# ══════════════════════════ الصفحة ══════════════════════════
_CSS = """
.ttabs{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 12px}
.ttabs a{padding:9px 14px;border-radius:12px;border:1px solid #e0d5c3;
background:#fff;font-weight:700;color:#5b4524;text-decoration:none;
display:inline-flex;align-items:center;gap:6px}
.ttabs a.on{background:#f3e6c4;border-color:#c9a24a;color:#3b2a12}
.opsel{display:flex;gap:8px;flex-wrap:wrap}
.opsel button{flex:1 1 140px;padding:11px;border-radius:12px;border:2px solid
#e0d5c3;background:#fff;font-weight:800;cursor:pointer}
.opsel button.buy.on{border-color:#1F8A4C;background:#e7f5ec;color:#1F8A4C}
.opsel button.ret.on{border-color:#C0392B;background:#fbeaea;color:#C0392B}
.seg{display:inline-flex;gap:0;border:1px solid #e0d5c3;border-radius:11px;
overflow:hidden;flex-wrap:nowrap;width:max-content;max-width:100%}
.seg label{flex-direction:row;align-items:center;gap:6px;white-space:nowrap;
padding:8px 12px;margin:0;cursor:pointer;font-weight:700}
.seg label+label{border-inline-start:1px solid #e0d5c3}
.tw input.num{max-width:120px}.rk{color:#a4262c}
.fg label.hide{display:none}
"""


def _tabs(base, head, tab):
    return '<div class="ttabs">' + "".join(
        f'<a class="{"on" if k == tab else ""}" href="'
        f'{_e(M._link(base, "/" + head, tab=k))}">{M.icon(ic, 18)}'
        f'{_e(t)}</a>' for k, t, ic in TABS[head]) + '</div>'


def page(conn, base, csrf, head, query, has_pin=False):
    query = query or {}
    title = PAGES[head]
    if not M.ops_enabled(conn):
        return M._lock_page(base, csrf, "تسجيل العمليات من الرابط موقوفٌ من "
                                        "البرنامج — والشاشات الضريبية منه.")
    keys = [k for k, _t, _i in TABS[head]]
    tab = query.get("tab") if query.get("tab") in keys else keys[0]
    lock_btn = (f'<form method="post" action="{_e(base + "/ops/lock")}" '
                f'style="margin:0"><input type="hidden" name="csrf" value="'
                f'{_e(csrf)}"><button class="btn sm gh">{M.icon("lock", 15)}'
                f'قفل اللوحة</button></form>' if has_pin else "")
    top = (f'<div class="ptitle"><h2>{M.icon("all", 22)}{_e(title)}</h2>'
           f'<span class="hint">كشاشة البرنامج — تُرحَّل باسم «{M.WEB_USER}»'
           f' وتظهر فيه فوراً</span><span class="sp"></span>{lock_btn}</div>'
           + _tabs(base, head, tab))
    if tab == "reg":
        body = (_sales_register(conn, base, query) if head == "taxs"
                else _pur_register(conn, base, query))
        return M.frame(base, head, title, top + body, csrf,
                       css=_CSS + M._ACTS_CSS)
    form, data = {
        ("taxs", "inv"): _sale_form, ("taxs", "ret"): _sret_form,
        ("taxp", "inv"): _pur_form, ("taxp", "ret"): _pret_form,
        ("taxp", "cash"): _cash_form}[(head, tab)](conn)
    return M.frame(base, head, title, (
        top + '<div id="okbox" class="msg ok" style="display:none"></div>'
        + form + '<script id="txdata" type="application/json">'
        + json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
        + '</script>'), csrf, css=_CSS, js=_TAX_JS)


def _sel(name, opts, val=None):
    return M._sel(name, [(o["id"], o["label"]) for o in opts], val)


def _post_row(label):
    return ('<div style="display:flex;gap:10px;align-items:center;flex-wrap:'
            f'wrap"><button class="btn big" id="post">{_e(label)}</button>'
            '<button class="btn gh" id="clear">تفريغ</button></div>')


def _lines_panel(title, heads):
    nc = ' class="n"'
    ths = "".join(f'<th{nc if n else ""}>{_e(h)}</th>' for h, n in heads)
    return (f'<section class="panel"><h3>{_e(title)}</h3><div class="scroll">'
            f'<table class="tbl" id="lines"><tr>{ths}<th></th></tr></table>'
            '</div><div class="note" id="hint"></div><div class="kpis" '
            'id="tot" style="margin:12px 0 0"></div></section>')


def _entry_fields(sale):
    """سطر الإدخال: الرقم · العدد · الوزن · العيار · سعر الجرام · الأجر ·
    إجمالي السطر — كسطر البرنامج."""
    karats = [(x, f"عيار {x}") for x in M.KARATS]
    return (
        f'<label>رقم الباركود/الصنف<input id="eno" autocomplete="off" '
        f'placeholder="{"اكتب الرقم كما تريده" if sale else "الرقم كما في فاتورة المورد"}"></label>'
        '<label>العدد<input id="epc" class="num" inputmode="numeric" '
        'value="1"></label><label>الوزن<input id="ew" class="num" '
        f'inputmode="decimal"></label><label>العيار{M._sel("ek", karats)}'
        '</label><label id="gpw">سعر الجرام<input id="egp" class="num" '
        'inputmode="decimal"></label><label><span id="lrate">الأجر/جم</span>'
        '<input id="erate" class="num" inputmode="decimal"></label><label>'
        '<span id="lnet">صافي السطر</span><input id="enet" class="num" '
        'inputmode="decimal" readonly></label><label style="justify-content:'
        f'flex-end"><button class="btn gold" id="eadd">{M.icon("plus", 16)}'
        'إضافة سطر</button></label>')


def _sale_form(conn):
    from models import tax_free, tax_invoices as tx
    d = _base(conn, "sinv")
    d["pay"] = _pay_opts(conn, "آجل — على حساب المشتري")
    d["stock"] = _acc_opts(tax_free.stock_accounts(conn))
    d["walkin"] = WALKIN
    stock_def = next((a["id"] for a in d["stock"]
                      if a["code"] == tax_free.TAX_STOCK),
                     d["stock"][0]["id"] if d["stock"] else "")
    pricing = M._sel("pricing", [(o["k"], o["label"]) for o in d["pricing"]],
                     "wage")
    h1 = (
        '<section class="panel"><h3>① بيانات الفاتورة</h3><div class="fg">'
        '<label>نوع الفاتورة<span class="seg"><label><input type="radio" '
        'name="st" value="standard" checked> ضريبية (شركة)</label><label>'
        '<input type="radio" name="st" value="simplified"> مبسطة (فرد)'
        '</label></span></label>'
        '<label class="ac w2"><span id="pcap">الحساب — ذو الرقم الضريبي</span>'
        '<input id="party" autocomplete="off" placeholder="اكتب اسم الحساب…">'
        '</label>'
        '<label id="wnw" class="hide">اسم المشتري<input id="wname" '
        'maxlength="120" placeholder="يُطبع على الفاتورة"></label>'
        '<label id="wpw" class="hide">الجوال<input id="wphone" maxlength="30"'
        ' inputmode="tel"></label>'
        f'<label>التاريخ<input id="date" type="date" value="{d["today"]}" '
        f'max="{d["today"]}"></label><label>الدفع{_sel("pay", d["pay"])}'
        f'</label><label class="w2">طريقة التسعير{pricing}</label>'
        '<label>الأصناف<span class="seg"><label><input type="radio" '
        'name="src" value="free" checked> إدخال يدوي حر</label><label><input'
        ' type="radio" name="src" value="vault"> من أطقم الخزنة</label>'
        '</span></label>'
        f'<label id="stw">حساب المخزون{_sel("stock", d["stock"], stock_def)}'
        '<small class="note" id="stbal"></small></label>'
        '<label id="discw">خصم نقدي (ريال)<input id="disc" class="num" '
        'inputmode="decimal"></label><label class="w2">البيان<input id="notes"'
        ' maxlength="300" placeholder="اختياري"></label></div>'
        '<div class="note" id="pinfo"></div></section>')
    h2 = ('<section class="panel"><h3>② إدخال الصنف</h3><div class="fg">'
          + _entry_fields(True) + '</div><div class="note" id="einfo"></div>'
          '</section>')
    h3 = _lines_panel("③ أصناف الفاتورة", (
        ("م", 0), ("رقم الباركود/الصنف", 0), ("العدد", 1), ("الوزن", 1),
        ("العيار", 0), ("سعر الجرام", 1), ("الأجر/جم · السعر", 1),
        ("قيمة الذهب", 1), ("الصافي", 1)))
    d["subtype_label"] = dict(tx.SUBTYPES)
    return h1 + h2 + h3 + _post_row("✔ ترحيل الفاتورة الضريبية"), d


def _pur_form(conn):
    from models import tax_free, set_purchases as sp
    d = _base(conn, "pinv")
    d["pay"] = _pay_opts(conn, "آجل — على حساب المورد")
    d["stock"] = _acc_opts(tax_free.stock_accounts(conn))
    d["dest"] = _acc_opts(sp.dest_accounts(conn))
    pricing = M._sel("pricing", [(o["k"], o["label"]) for o in d["pricing"]],
                     "wage")
    stock_def = next((a["id"] for a in d["stock"]
                      if a["code"] == tax_free.TAX_STOCK),
                     d["stock"][0]["id"] if d["stock"] else "")
    h1 = (
        '<section class="panel"><h3>① بيانات الفاتورة</h3><div class="fg">'
        '<label class="ac w2">الحساب (مورد · عميل · جهة)<input id="party" '
        'autocomplete="off" placeholder="اكتب اسم الحساب…"></label>'
        '<label>رقم فاتورة المورد<input id="supinv" maxlength="60"></label>'
        f'<label>التاريخ<input id="date" type="date" value="{d["today"]}" '
        f'max="{d["today"]}"></label><label>الدفع{_sel("pay", d["pay"])}'
        f'</label><label class="w2">طريقة التسعير{pricing}</label>'
        '<label>الأصناف<span class="seg"><label><input type="radio" '
        'name="src" value="free" checked> إدخال يدوي حر</label><label><input'
        ' type="radio" name="src" value="vault"> إلى أطقم الخزنة</label>'
        '</span></label>'
        f'<label id="stw">حساب المخزون{_sel("stock", d["stock"], stock_def)}'
        '<small class="note" id="stbal"></small></label>'
        '<label id="discw">خصم نقدي (ريال)<input id="disc" class="num" '
        'inputmode="decimal"></label><label class="w2">ملاحظات<input '
        'id="notes" maxlength="300" placeholder="اختياري"></label></div>'
        '<div class="note" id="pinfo"></div></section>')
    h2 = ('<section class="panel"><h3>② إدخال الصنف كما في فاتورة المورد</h3>'
          '<div class="fg">' + _entry_fields(False) + '</div></section>')
    h3 = _lines_panel("③ أصناف الفاتورة", (
        ("م", 0), ("رقم الباركود/الصنف", 0), ("العدد", 1), ("الوزن", 1),
        ("العيار", 0), ("سعر الجرام", 1), ("الأجر/جم · السعر", 1),
        ("قيمة الذهب", 1), ("الصافي", 1)))
    return h1 + h2 + h3 + _post_row("✔ ترحيل فاتورة المشتريات الضريبية"), d


def _ret_form(d, opts, what, reasons):
    sel = ('<select id="orig"><option value="">— اختر الفاتورة —</option>'
           + "".join(f'<option value="{o["id"]}">{_e(o["label"])}</option>'
                     for o in opts) + '</select>')
    rs = "".join(f'<option value="{_e(r)}">' for r in reasons)
    h1 = (f'<section class="panel"><h3>① {_e(what)}</h3><div class="fg">'
          f'<label class="w2">الفاتورة الأصلية{sel}</label>'
          f'<label>التاريخ<input id="date" type="date" value="{d["today"]}" '
          f'max="{d["today"]}"></label><label class="w2">السبب (إلزامي)<input'
          f' id="reason" list="rsn" maxlength="200"><datalist id="rsn">{rs}'
          '</datalist></label></div><div class="note" id="pinfo"></div>'
          + ('' if opts else '<div class="msg info">لا فواتير فيها ما يُرتجع'
             '</div>') + '</section>')
    h2 = ('<section class="panel"><h3>② الأصناف — حدّد ما يُرتجع ووزنه '
          '<span class="sp"></span><button class="btn sm gh" id="all">تحديد '
          'الكل</button></h3><div class="scroll"><table class="tbl" '
          'id="lines"><tr><th></th><th>رقم الباركود/الصنف</th><th class="n">'
          'العدد</th><th class="n">الوزن</th><th class="n">الباقي</th><th>'
          'العيار</th><th>السعر كما في الفاتورة</th><th class="n">وزن المرتجع'
          '</th><th class="n">الصافي</th></tr></table></div><div class="kpis"'
          ' id="tot" style="margin:12px 0 0"></div></section>')
    return h1 + h2


def _sret_form(conn):
    from models import tax_invoices as tx
    d = _base(conn, "sret")
    opts = [{"id": r["id"], "label": _sale_label(r)}
            for r in tx.open_invoices(conn)]
    return (_ret_form(d, opts, "الفاتورة الأصلية", (
        "إرجاع بضاعة من العميل", "خطأ في الفاتورة", "عيبٌ في الصنف",
        "تعديل السعر")) + _post_row("✔ ترحيل مرتجع المبيعات (إشعار دائن)"),
        d)


def _pret_form(conn):
    from models import set_purchases as sp
    d = _base(conn, "pret")
    opts = [{"id": r["id"], "label": _pur_label(r)}
            for r in sp.open_purchases(conn)]
    return (_ret_form(d, opts, "فاتورة الشراء الأصلية", (
        "إرجاع بضاعة للمورد", "خطأ في الفاتورة", "عيبٌ في الصنف"))
        + _post_row("✔ ترحيل مرتجع المشتريات"), d)


def _cash_form(conn):
    from models import purchases
    d = _base(conn, "cash")
    d["accs"] = {k: [{"id": a["code"], "label": f"{a['code']} — {a['name']}"}
                     for a in purchases.purchase_accounts(conn, k)]
                 for k in ("expense", "asset")}
    d["nov"] = list(purchases.NO_VAT)
    kinds = [{"id": "expense", "label": "مصروف تشغيلي"},
             {"id": "asset", "label": "أصل ثابت (يُهلك)"}]
    treat = [{"id": k, "label": v} for k, v in purchases.TAX_TREATMENTS]
    itype = [{"id": k, "label": v} for k, v in purchases.INVOICE_TYPES]
    pays = [{"id": k, "label": v} for k, v in purchases.PAY_MODES]
    h1 = (
        '<section class="panel"><h3 id="ctitle">① فاتورة مشتريات</h3>'
        '<div class="opsel"><button type="button" class="buy on" data-op='
        '"buy">🧾 مشتريات</button><button type="button" class="ret" data-op='
        '"ret">↩ مرتجع مشتريات</button></div><div class="fg" style="margin-'
        'top:10px"><label class="ac w2">الحساب (مورد · عميل · جهة)<input '
        'id="party" autocomplete="off" placeholder="اكتب اسم الحساب…">'
        '</label><label><span id="invcap">رقم فاتورة المورد</span><input '
        'id="supinv" maxlength="60"></label>'
        f'<label>التاريخ<input id="date" type="date" value="{d["today"]}" '
        f'max="{d["today"]}"></label>'
        f'<label>نوع الفاتورة{_sel("itype", itype, "standard")}</label>'
        f'<label>طريقة الدفع{_sel("pay", pays, "credit")}</label>'
        f'<label>نوع الشراء{_sel("kind", kinds, "expense")}</label>'
        f'<label class="w2">المعالجة الضريبية{_sel("treat", treat, "standard")}'
        '</label><label id="lifew" class="hide">العمر الإنتاجي (شهر)<input '
        'id="life" class="num" inputmode="numeric"></label><label class="w2">'
        'البيان (إلزامي)<input id="notes" maxlength="300" placeholder="مثال: '
        'صيانة المكائن"></label></div>'
        '<div class="note" id="pinfo"></div></section>')
    h2 = ('<section class="panel"><h3>② المبالغ والضريبة</h3><div class="fg">'
          '<label class="w2">الحساب<select id="acc"></select></label>'
          '<label>العدد<input id="cq" class="num" inputmode="decimal" '
          'value="1"></label><label>السعر<input id="cp" class="num" '
          'inputmode="decimal"></label><label>الخصم<input id="cd" class="num"'
          ' inputmode="decimal"></label><label style="justify-content:'
          f'flex-end"><button class="btn gold" id="cadd">{M.icon("plus", 16)}'
          'إضافة سطر</button></label></div></section>')
    h3 = _lines_panel("③ الأسطر", (
        ("م", 0), ("الحساب", 0), ("العدد", 1), ("السعر", 1),
        ("المبلغ قبل الضريبة", 1), ("الخصم", 1), ("الضريبة", 1),
        ("بعد الضريبة", 1)))
    return h1 + h2 + h3 + _post_row("✔ ترحيل فاتورة المشتريات"), d


# ══════════════════════════ السجلّان ══════════════════════════
def _reg_head(base, head, key, d1, d2, query, kinds, extra=""):
    q = str(query.get("q") or "")[:60]
    kind = str(query.get("kind") or "")
    keep = {"tab": "reg"}
    if q:
        keep["q"] = q
    if kind:
        keep["kind"] = kind
    if query.get("sub"):
        keep["sub"] = query.get("sub")
    opts = "".join(f'<option value="{_e(k)}"{" selected" if k == kind else ""}>'
                   f'{_e(t)}</option>' for k, t in kinds)
    return (f'<form class="panel fl" method="get" action="{_e(base + "/" + head)}"'
            ' style="margin:0 0 10px"><input type="hidden" name="tab" value="reg">'
            f'<input type="hidden" name="per" value="{_e(key)}">'
            f'<label style="flex:3 1 260px">بحث في كل الفترات<input name="q" '
            f'value="{_e(q)}" placeholder="رقم الفاتورة · الحساب · الجوال · '
            f'رقم الباركود/الصنف…"></label><label style="flex:1 1 170px">النوع'
            f'<select name="kind">{opts}</select></label>{extra}<label style='
            '"justify-content:flex-end"><button class="btn gold" name="all" '
            'value="1">🔍 بحث</button></label></form>'
            + M._period_bar(base, "/" + head, key,
                            "" if d1 == "0000-01-01" else d1,
                            "" if d2 == "9999-12-31" else d2, keep))


def _reg_period(query):
    """فترة السجل — و«🔍 بحث» أو كتابةٌ في البحث: كل الفترات (كالبرنامج)."""
    if query.get("all") == "1" or str(query.get("q") or "").strip():
        return "0000-01-01", "9999-12-31", "all"
    d1, d2, key = M._period(query, "month")
    return d1 or "0000-01-01", d2 or "9999-12-31", key


def _view(base, doc, rid):
    src = {"invoice": "invoices", "tax_sale": None,
           "set_purchase": "set_purchases", "purchase": "purchases",
           "purchases": "purchases"}.get(doc, doc)
    if not src or src not in M.DOC_TYPES:
        return ""
    return (f'<a class="btn sm gh" target="_blank" rel="noopener" href="'
            f'{_e(base + f"/doc/{src}/{rid}")}">عرض</a>')


def _sales_register(conn, base, query):
    from models import tax_invoices as tx
    d1, d2, key = _reg_period(query)
    q = str(query.get("q") or "").strip()[:60]
    kind = str(query.get("kind") or "") or None
    sub = str(query.get("sub") or "") or None
    subs = (("", "ضريبية ومبسطة"), ("standard", "ضريبية"),
            ("simplified", "مبسطة"))
    sub_sel = ('<label style="flex:1 1 150px">الفئة<select name="sub">'
               + "".join(f'<option value="{k}"{" selected" if k == (sub or "") else ""}>'
                         f'{t}</option>' for k, t in subs) + '</select></label>')
    rows = tx.sales_register(conn, d1, d2, q,
                             kind if kind in dict(tx.REG_KINDS) else None,
                             sub if sub in ("standard", "simplified") else None)
    tot = {"w": 0.0, "wg": 0.0, "gv": 0.0, "d": 0.0, "v": 0.0, "t": 0.0,
           "b": 0.0}
    trs = []
    for s in rows:
        sg = -1 if s["ret"] else 1
        for k_, f in (("w", "weight"), ("wg", "wages"), ("gv", "gold_value"),
                      ("d", "discount"), ("v", "vat"), ("t", "total"),
                      ("b", "base")):
            tot[k_] += sg * float(s.get(f) or 0)
        rk = ' class="rk"' if s["ret"] else ""
        trs.append(
            f'<tr><td class="n">{_e(s["no"])}</td><td class="n">'
            f'{_e(s["date"])}</td><td{rk}>{_e(s["kind_label"])}</td><td>'
            f'{_e(s["party"])}</td><td class="n">'
            f'{M._w(s["weight"]) if s["weight"] is not None else "—"}</td>'
            f'<td class="n">{_m(s["wages"])}</td><td class="n">'
            f'{_m(s["gold_value"]) if s["gold_value"] else "—"}</td>'
            f'<td class="n">{_m(s["discount"]) if s["discount"] else "—"}</td>'
            f'<td class="n{" rk" if s["ret"] else ""}">{_m(s["vat"])}</td>'
            f'<td class="n{" rk" if s["ret"] else ""}">{_m(s["total"])}</td>'
            f'<td class="acts">{_view(base, s["doc"], s["id"])}</td></tr>')
    kp = (f'<div class="kpis"><div class="kpi"><div class="k">المستندات</div>'
          f'<div class="v">{len(rows)}</div><div class="s">'
          f'{_e("كل الفترات" if key == "all" else M._span(d1, d2))}</div></div>'
          f'<div class="kpi"><div class="k">صافي المبيعات الخاضعة</div><div '
          f'class="v">{_m(tot["b"])}</div><div class="s">بعد المرتجعات والخصم'
          f'</div></div><div class="kpi"><div class="k">صافي ضريبة المخرجات'
          f'</div><div class="v">{_m(tot["v"])}</div><div class="s">تنتقل '
          f'للإقرار الضريبي</div></div><div class="kpi gold"><div class="k">'
          f'الإجمالي شامل الضريبة</div><div class="v">{_m(tot["t"])}</div>'
          '</div></div>')
    table = ('<div class="panel"><div class="scroll"><table class="tbl"><tr>'
             '<th>رقم الفاتورة</th><th>التاريخ</th><th>النوع</th><th>العميل'
             '</th><th class="n">الوزن</th><th class="n">الأجور</th><th '
             'class="n">قيمة الذهب</th><th class="n">الخصم</th><th class="n">'
             'الضريبة</th><th class="n">الإجمالي</th><th></th></tr>'
             + "".join(trs) + '</table></div></div>' if trs else
             '<div class="empty">لا مستندات بهذه الاختيارات — اختر فترةً أخرى'
             ' أو اضغط «🔍 بحث» لكل الفترات</div>')
    return (_reg_head(base, "taxs", key, d1, d2, query, tx.REG_KINDS, sub_sel)
            + kp + table)


def _pur_register(conn, base, query):
    from models import set_purchases as sp
    d1, d2, key = _reg_period(query)
    q = str(query.get("q") or "").strip()[:60]
    kind = str(query.get("kind") or "") or None
    rows = sp.tax_register(conn, d1, d2, q,
                           kind if kind in dict(sp.REG_KINDS) else None)
    tot = {"b": 0.0, "v": 0.0, "t": 0.0}
    trs = []
    for s in rows:
        sg = -1 if s.get("ret") else 1
        tot["b"] += sg * float(s.get("base") or s.get("net") or 0)
        tot["v"] += sg * float(s.get("vat") or 0)
        tot["t"] += sg * float(s.get("total") or 0)
        rk = " rk" if s.get("ret") else ""
        trs.append(
            f'<tr><td class="n">{_e(s.get("no") or "")}</td><td class="n">'
            f'{_e(s.get("date") or "")}</td><td class="{rk.strip()}">'
            f'{_e(s.get("kind_label") or "")}</td><td>{_e(s.get("party") or "")}'
            f'</td><td class="n">{_e(s.get("sup_no") or "—")}</td><td class="n">'
            f'{M._w(s["weight"]) if s.get("weight") else "—"}</td><td class="n">'
            f'{_m(s.get("wages") or 0)}</td><td class="n">'
            f'{_m(s["discount"]) if s.get("discount") else "—"}</td>'
            f'<td class="n{rk}">{_m(s.get("vat") or 0)}</td>'
            f'<td class="n{rk}">{_m(s.get("total") or 0)}</td><td class="acts">'
            f'{_view(base, s.get("doc"), s.get("id"))}</td></tr>')
    kp = (f'<div class="kpis"><div class="kpi"><div class="k">المستندات</div>'
          f'<div class="v">{len(rows)}</div><div class="s">'
          f'{_e("كل الفترات" if key == "all" else M._span(d1, d2))}</div></div>'
          f'<div class="kpi"><div class="k">صافي المشتريات الخاضعة</div><div '
          f'class="v">{_m(tot["b"])}</div><div class="s">بعد المرتجعات والخصم'
          f'</div></div><div class="kpi"><div class="k">ضريبة المدخلات القابلة'
          f' للخصم</div><div class="v">{_m(tot["v"])}</div><div class="s">'
          f'تنتقل للإقرار الضريبي</div></div><div class="kpi gold"><div '
          f'class="k">الإجمالي شامل الضريبة</div><div class="v">'
          f'{_m(tot["t"])}</div></div></div>')
    table = ('<div class="panel"><div class="scroll"><table class="tbl"><tr>'
             '<th>رقم الفاتورة</th><th>التاريخ</th><th>النوع</th><th>الحساب'
             '</th><th>فاتورة المورد</th><th class="n">الوزن</th><th class="n">'
             'الأجور / المبلغ</th><th class="n">الخصم</th><th class="n">الضريبة'
             '</th><th class="n">الإجمالي</th><th></th></tr>' + "".join(trs)
             + '</table></div></div>' if trs else
             '<div class="empty">لا مستندات بهذه الاختيارات — اختر فترةً أخرى'
             ' أو اضغط «🔍 بحث» لكل الفترات</div>')
    return _reg_head(base, "taxp", key, d1, d2, query, sp.REG_KINDS) + kp + table


# ══════════════════════════ الترحيل ══════════════════════════
def _pricing(v):
    """(طريقة القيد، شامل الضريبة؟) من اختيار النموذج."""
    from models import tax_invoices as tx
    v = str(v or "wage")
    if v in tx.INCL_BASE:
        return tx.INCL_BASE[v], True
    if v not in tx.PRICING_LABEL:
        raise ValueError("طريقة التسعير غير معروفة")
    return v, False


def _pay(conn, v):
    """(الطريقة، حساب الدفع) — «آجل» أو صندوقٌ/بنكٌ من الشجرة."""
    from models.accounts import pay_accounts
    if v in (None, "", CREDIT):
        return CREDIT, None
    aid = M._id(v, "الدفع")
    if aid not in {int(r["id"]) for r in pay_accounts(conn)}:
        raise ValueError("حساب الدفع غير صالح — اختره من القائمة")
    return "cash", aid


def _gold_lines(data, pricing, incl, wkey):
    """أسطر الذهب من النموذج ← بمكافئ 18 وصافي كل سطر (والشامل يُفصل)."""
    from models import tax_invoices as tx
    from services import karat_view as kv
    out = []
    for li in M._lines_of(data):
        k = M._karat(li.get("karat"))
        no = " ".join(M._txt(li.get("no"), 40).split())
        if not no:
            raise ValueError("اكتب رقم الباركود/الصنف لكل سطر")
        w = M._f(li.get("weight"), "الوزن", 0.0, 1e6)
        if w <= 0:
            raise ValueError(f"اكتب وزن {no}")
        it = {"no": no, "karat": k, wkey: kv.store(w, k),
              "pieces": int(M._f(li.get("pieces"), "العدد", 0, 9999)) or 1,
              "gold_price": (round(M._f(li.get("gp"), "سعر الجرام", 0, 1e6), 4)
                             if pricing in tx.RIYAL else 0.0),
              "wage18": 0.0, "piece_price": 0.0, "id": li.get("id")}
        rate = M._f(li.get("rate"), "الأجر", 0.0, 1e9)
        if incl:
            it["incl"] = round(M._f(li.get("incl"), "المبلغ شاملاً", 0.0,
                                    1e10), 2)
            if it["incl"] <= 0:
                raise ValueError(f"اكتب المبلغ شاملاً الضريبة لـ{no}")
        elif pricing == "piece":
            it["piece_price"] = round(rate, 2)
        else:
            it["wage18"] = kv.rate_store(rate, k)
        if pricing in tx.RIYAL and it["gold_price"] <= 0:
            raise ValueError(f"اكتب سعر الجرام لـ{no}")
        out.append(it)
    if incl:
        nets = tx.incl_nets([x["incl"] for x in out])
        for x, n in zip(out, nets):
            if pricing == "piece":
                x["piece_price"] = n
            else:
                x["wage18"] = tx.incl_wage18(n, x[wkey])
    return out


def _head_price(items, pricing):
    from models import tax_invoices as tx
    if pricing in tx.RIYAL and items:
        return items[0]["gold_price"], items[0]["karat"]
    return 0.0, 0


def _post_sale(conn, data):
    from models import tax_free, tax_invoices as tx
    from services import karat_view as kv
    pricing, incl = _pricing(data.get("pricing"))
    subtype = str(data.get("subtype") or "standard")
    if subtype not in dict(tx.SUBTYPES):
        raise ValueError("نوع الفاتورة غير معروف")
    walk = str(data.get("party") or "") == WALKIN
    if walk and subtype != "simplified":
        raise ValueError("«العميل النقدي» فاتورته مبسطة")
    cid = None if walk else M._id(data.get("party"), "الحساب")
    if cid is not None:
        ent = M._entity(conn, cid)
        if ent["entity_type"] == "internal":
            raise ValueError("اختر الحساب من دليل جهات التعامل")
    pay, pay_acc = _pay(conn, data.get("pay"))
    disc = 0.0 if incl else round(M._f(data.get("disc"), "الخصم", 0, 1e9), 2)
    date = M._post_date(data.get("date"))
    notes = M._txt(data.get("notes"), 300)
    bname = M._txt(data.get("wname"), 120) if walk else ""
    bphone = M._txt(data.get("wphone"), 30) if walk else ""
    free = data.get("src") != "vault"
    items = _gold_lines(data, pricing, incl, "w18")
    gp, pk = _head_price(items, pricing)
    if free:
        acc = M._id(data.get("stock"), "حساب المخزون")
        res = tax_free.create_sale(
            conn, cid, [{"wo_no": x["no"], "model_no": "",
                         "pieces": x["pieces"], "weight": x["w18"],
                         "karat": x["karat"], "wage": x["wage18"],
                         "piece_price": x["piece_price"],
                         "gold_price": x["gold_price"]} for x in items],
            date, M.WEB_USER, pricing, gp, pk, notes, subtype=subtype,
            buyer_name=bname, buyer_phone=bphone, pay_mode=pay,
            account_id=acc, discount=disc, pay_account_id=pay_acc)
    else:
        from models import inventory
        cart = []
        for x in items:
            wo = inventory.get_wo_by_no(conn, x["no"])
            if wo is None:
                raise ValueError(f"الرقم {x['no']} غير موجود في خزنتك")
            w18 = x["w18"]
            if not wo["is_bulk"]:
                from models import wo_moves as wm
                avail = float(wm.default_weight(conn, wo, wm.SALE))
                if avail and abs(kv.g(avail, x["karat"])
                                 - kv.g(w18, x["karat"])) <= 0.0051:
                    w18 = avail
            cart.append({"work_order_id": wo["id"], "weight": w18,
                         "wage_override": x["wage18"],
                         "piece_price": x["piece_price"],
                         "pieces": x["pieces"], "karat": x["karat"],
                         "gold_price": x["gold_price"]})
        res = tx.create_invoice(
            conn, cid, cart, date, M.WEB_USER, pricing, gp, pk, notes,
            subtype=subtype, buyer_name=bname, buyer_phone=bphone,
            pay_mode=pay, discount=disc, pay_account_id=pay_acc)
    docs = [res] + ([res["split"]] if res.get("split") else [])
    nos = " · ".join(x["invoice_no"] for x in docs)
    return {"ok": True, "no": nos, "id": res["id"],
            "links": [(f"📄 الفاتورة {x['invoice_no']}",
                       f"/doc/invoices/{x['id']}") for x in docs],
            "msg": (f"رُحّلت {tx.SUBTYPE_LABEL[subtype]} {nos} — الإجمالي "
                    f"{_m(res['grand_total'])} ريال")}


def _post_sale_ret(conn, data):
    from models import tax_invoices as tx
    from services import karat_view as kv
    iid = M._id(data.get("orig"), "الفاتورة الأصلية")
    reason = M._txt(data.get("reason"), 200)
    if not reason:
        raise ValueError("اكتب سبب الإشعار الدائن (إلزامي)")
    rows = {x["item_id"]: x for x in tx.returnable(conn, iid)}
    rets = []
    for r in M._lines_of(data, "rets"):
        x = rows.get(M._id(r.get("id"), "السطر"))
        if x is None:
            raise ValueError("سطرٌ ليس من الفاتورة — حدّث الصفحة")
        k = int(x["karat"] or kv.active())
        v = M._f(r.get("weight"), "وزن المرتجع", 0, 1e6)
        if v <= 0:
            continue
        w18 = (x["left"] if abs(v - kv.g(x["left"], k)) <= 0.0051
               else kv.store(v, k))
        rets.append({"item_id": x["item_id"], "weight": w18})
    if not rets:
        raise ValueError("حدّد صنفاً واحداً على الأقل للإرجاع")
    res = tx.create_credit_note(conn, iid, M._post_date(data.get("date")),
                                rets, reason, M.WEB_USER)
    return {"ok": True, "no": res["invoice_no"], "id": res["id"],
            "links": [(f"📄 الإشعار {res['invoice_no']}",
                       f"/doc/invoices/{res['id']}")],
            "msg": (f"رُحّل مرتجع المبيعات {res['invoice_no']} — الإجمالي "
                    f"{_m(res['grand_total'])} ريال")}


def _post_pur(conn, data):
    from models import set_purchases as sp
    pricing, incl = _pricing(data.get("pricing"))
    sid = M._id(data.get("party"), "الحساب")
    ent = M._entity(conn, sid)
    if ent["entity_type"] == "internal":
        raise ValueError("اختر الحساب من دليل جهات التعامل")
    sup_inv = M._txt(data.get("supinv"), 60)
    if not sup_inv:
        raise ValueError("اكتب رقم فاتورة المورد — بها تُخصم ضريبة المدخلات")
    pay, pay_acc = _pay(conn, data.get("pay"))
    disc = 0.0 if incl else round(M._f(data.get("disc"), "الخصم", 0, 1e9), 2)
    mode = "vault" if data.get("src") == "vault" else "free"
    items = _gold_lines(data, pricing, incl, "reg18")
    gp, pk = _head_price(items, pricing)
    res = sp.create_purchase(
        conn, sid, M._post_date(data.get("date")), sup_inv,
        [{"wo_no": x["no"], "model_no": "", "pieces": x["pieces"],
          "registered": x["reg18"], "standing": x["reg18"],
          "karat": x["karat"], "wage": x["wage18"],
          "piece_price": x["piece_price"], "gold_price": x["gold_price"]}
         for x in items],
        M.WEB_USER, pricing, gp, pk, M._txt(data.get("notes"), 300),
        dest_account_id=M._id(data.get("stock"), "الحساب الذي تدخله"),
        mode=mode, discount=disc, pay_mode=pay, pay_account_id=pay_acc)
    return {"ok": True, "no": res["doc_no"], "id": res["id"],
            "links": [(f"📄 الفاتورة {res['doc_no']}",
                       f"/doc/set_purchases/{res['id']}")],
            "msg": (f"رُحّلت فاتورة المشتريات {res['doc_no']} من "
                    f"{res['supplier_name']} — الإجمالي {_m(res['total'])} "
                    f"ريال (ضريبة المدخلات {_m(res['vat'])})")}


def _post_pur_ret(conn, data):
    from models import set_purchases as sp
    from services import karat_view as kv
    did = M._id(data.get("orig"), "الفاتورة الأصلية")
    reason = M._txt(data.get("reason"), 200)
    if not reason:
        raise ValueError("اكتب سبب المرتجع (إلزامي)")
    rows = {x["line_id"]: x for x in sp.returnable(conn, did)}
    rets = []
    for r in M._lines_of(data, "rets"):
        x = rows.get(M._id(r.get("id"), "السطر"))
        if x is None:
            raise ValueError("سطرٌ ليس من الفاتورة — حدّث الصفحة")
        if x["why"]:
            raise ValueError(f"{x['wo_no']}: {x['why']}")
        if x["bulk"] or x.get("free"):
            k = int(x["karat"] or kv.active())
            v = M._f(r.get("weight"), "وزن المرتجع", 0, 1e6)
            if v <= 0:
                continue
            w18 = (x["left"] if abs(v - kv.g(x["left"], k)) <= 0.0051
                   else kv.store(v, k))
            rets.append({"line_id": x["line_id"], "weight": w18})
        else:
            rets.append({"line_id": x["line_id"], "weight": None})
    if not rets:
        raise ValueError("حدّد صنفاً واحداً على الأقل للإرجاع")
    res = sp.create_return(conn, did, M._post_date(data.get("date")), rets,
                           reason, M.WEB_USER)
    return {"ok": True, "no": res["doc_no"], "id": res["id"],
            "links": [(f"📄 المرتجع {res['doc_no']}",
                       f"/doc/set_purchases/{res['id']}")],
            "msg": (f"رُحّل مرتجع المشتريات {res['doc_no']} — الإجمالي "
                    f"{_m(res['total'])} ريال")}


def _post_cash(conn, data):
    from models import purchases
    kind = str(data.get("kind") or "expense")
    if kind not in ("expense", "asset"):
        raise ValueError("نوع الشراء غير معروف")
    treat = str(data.get("treat") or "standard")
    if treat not in dict(purchases.TAX_TREATMENTS):
        raise ValueError("المعالجة الضريبية غير معروفة")
    itype = str(data.get("itype") or "standard")
    if itype not in dict(purchases.INVOICE_TYPES):
        raise ValueError("نوع الفاتورة غير معروف")
    pay = str(data.get("pay") or "credit")
    if pay not in dict(purchases.PAY_MODES):
        raise ValueError("طريقة الدفع غير معروفة")
    ret = data.get("op") == "ret"
    sid = M._id(data.get("party"), "الحساب")
    ent = M._entity(conn, sid)
    if ent["entity_type"] == "internal":
        raise ValueError("اختر الحساب من دليل جهات التعامل")
    lines, net, vat, disc = [], 0.0, 0.0, 0.0
    for li in M._lines_of(data):
        c = purchases.compute_line(
            M._f(li.get("qty"), "العدد", 0, 1e9),
            M._f(li.get("price"), "السعر", 0, 1e12),
            M._f(li.get("disc"), "الخصم", 0, 1e12), treat)
        if c["net"] <= 0:
            raise ValueError("المبلغ بعد الخصم يجب أن يكون أكبر من صفر")
        code = M._txt(li.get("acc"), 20)
        lines.append({"account_code": code, "qty": c["qty"],
                      "unit_price": c["unit_price"],
                      "discount": c["discount"], "vat": c["vat"]})
        net += c["net"]
        vat += c["vat"]
        disc += c["discount"]
    sup_inv = M._txt(data.get("supinv"), 60)
    if treat == "standard" and vat and not ret and not sup_inv:
        raise ValueError("اكتب رقم فاتورة المورد — ضريبة المدخلات لا تُخصم إلا"
                         " بفاتورةٍ ضريبية مرقّمة")
    res = purchases.create_purchase(
        conn, kind, sid, M._txt(data.get("notes"), 300), round(net, 2),
        round(vat, 2), M._post_date(data.get("date")), M.WEB_USER,
        supplier_invoice_no=sup_inv, tax_treatment=treat,
        account_code=lines[0]["account_code"], price_mode="net",
        life_months=int(M._f(data.get("life"), "العمر", 0, 1200)),
        discount=round(disc, 2), pay_mode=pay, invoice_type=itype,
        is_return=ret, lines=lines)
    label = "مرتجع المشتريات" if ret else "فاتورة المشتريات"
    return {"ok": True, "no": res["purchase_no"], "id": res["id"],
            "links": [(f"📄 {res['purchase_no']}",
                       f"/doc/purchases/{res['id']}")],
            "msg": (f"رُحّل {label} {res['purchase_no']} — "
                    f"{res['supplier_name']} — الإجمالي {_m(res['total'])} "
                    "ريال")}


def post(kind, data):
    """يرحّل مستنداً ضريبياً من الرابط — أو {"ok": False, "error"}."""
    fn = {"tax_sale": _post_sale, "tax_sale_ret": _post_sale_ret,
          "tax_pur": _post_pur, "tax_pur_ret": _post_pur_ret,
          "cash_pur": _post_cash}.get(kind)
    if fn is None:
        return {"ok": False, "error": "عمليةٌ غير معروفة"}
    return M._guarded(data, lambda conn: fn(conn, data), kind,
                      where=f"tax/{kind}")


# ══════════════════════════ الواجهة (JS) ══════════════════════════
_TAX_JS = r"""
(function(){
 var D=JSON.parse(document.getElementById('txdata').textContent),MODE=D.mode;
 function $(i){return document.getElementById(i);}
 function nn(){return Date.now().toString(36)+Math.random().toString(36).slice(2,10);}
 function R2(x){return Math.round((+x||0)*100+1e-9)/100;}
 function vatOf(n){return R2(n*D.vat);}
 var NONCE=nn(),lines=[],party=null,X='<button class="btn sm red" data-x="1">✕</button>';
 var w18=function(w,k){return w*k/18;},wk=function(v18,k){return v18*18/k;};
 function kpis(a){$('tot').innerHTML=a.map(function(x){return '<div class="kpi'+
  (x[2]?' gold':'')+'"><div class="k">'+MW.esc(x[0])+'</div><div class="v">'+
  x[1]+'</div>'+(x[3]?'<div class="s">'+MW.esc(x[3])+'</div>':'')+'</div>';}).join('');}
 function radio(n){var r=document.querySelector('input[name="'+n+'"]:checked');return r?r.value:'';}
 var build=function(){return null;},summary=function(){return '';},
  reset=function(){},URL='',dirty=function(){return lines.length>0;},
  render=function(){};
 // ── الصافي الذي يبلغ الشامل بالهللة (كـ tax_invoices.incl_nets) ──
 function docNet(t){t=R2(t);if(t<=0)return 0;var n0=R2(t/(1+D.vat)),best=null;
  [0,-1,1,-2,2].forEach(function(d){var n=R2(n0+d/100);if(n<0)return;
   var diff=R2(n+vatOf(n)-t),key=[Math.abs(diff),diff>0?1:0];
   if(!best||key[0]<best[0][0]-1e-9||(Math.abs(key[0]-best[0][0])<1e-9&&key[1]<best[0][1]))
    best=[key,n];});return best[1];}
 function inclNets(xs){var nets=xs.map(function(x){return R2(x/(1+D.vat));});
  if(!nets.length)return nets;var s=nets.reduce(function(a,b){return a+b;},0);
  var diff=R2(docNet(xs.reduce(function(a,b){return a+b;},0))-s);
  if(diff){var i=0;nets.forEach(function(v,j){if(v>nets[i])i=j;});nets[i]=R2(nets[i]+diff);}
  return nets;}
 if($('party')){var std=function(){return MODE==='sinv'&&radio('st')==='standard';};
  MW.ac($('party'),'/tax/api/party',function(r){party=r;
   if($('pinfo'))$('pinfo').textContent=r?(r.sub||''):'';},
   function(){return std()?{std:1}:{};});}
 // ═══ فاتورة البيع والشراء (الذهب) ═══
 if(MODE==='sinv'||MODE==='pinv'){
  var sale=MODE==='sinv',curK=D.k,cur=null,typedTot=null;
  function pricing(){return $('pricing').value;}
  function incl(){return !!D.incl[pricing()];}
  function base(){return D.incl[pricing()]||pricing();}
  function riyal(){return D.riyal.indexOf(base())>=0;}
  function piece(){return base()==='piece';}
  function free(){return radio('src')!=='vault';}
  function lineNet(l){var w=l.weight,gv=riyal()?R2(w*l.gp):0;
   if(piece())return {gv:gv,net:R2(l.price),bad:l.price<gv-0.005?'سعر الطقم أقل من قيمة ذهبه':''};
   return {gv:gv,net:R2(gv+w*l.wage),bad:''};}
  function applyIncl(){if(!incl())return;var nets=inclNets(lines.map(function(l){return l.incl;}));
   lines.forEach(function(l,i){if(piece())l.price=nets[i];else l.wage=l.weight>0?nets[i]/l.weight:0;});}
  function setLabels(){var p=piece(),inc=incl();
   $('lrate').textContent=(p?'سعر الطقم':'الأجر/جم')+(inc?' شامل الضريبة':(p?' (ريال)':''));
   $('lnet').textContent=inc&&!p?'إجمالي السطر شامل الضريبة':(inc?'شامل الضريبة':'صافي السطر');
   $('enet').readOnly=!(inc&&!p);$('gpw').style.display=riyal()?'':'none';
   if($('discw')){$('disc').disabled=inc;if(inc)$('disc').value='';}
   typedTot=null;lineNow();}
  function lineNow(){var w=MW.num($('ew')),r=MW.num($('erate')),gp=MW.num($('egp'));
   if(document.activeElement===$('enet')&&incl()&&!piece())return;
   if(!w&&!piece()){$('enet').value='';return;}
   if(incl()){$('enet').value=(piece()?r:(typedTot!=null?typedTot:R2(w*r))).toFixed(2);return;}
   var gv=riyal()?R2(w*gp):0;$('enet').value=(piece()?R2(r):R2(gv+w*r)).toFixed(2);}
  ['ew','erate','egp'].forEach(function(i){$(i).addEventListener('input',function(){
   if(i==='erate')typedTot=null;lineNow();});});
  $('enet').addEventListener('input',function(){if(!incl()||piece())return;
   var t=MW.num($('enet')),w=MW.num($('ew'));typedTot=R2(t);
   if(w>0)$('erate').value=(t/w).toFixed(2);});
  $('pricing').onchange=function(){if(lines.length&&!confirm('تغيير طريقة التسعير يفرّغ الأسطر — متابعة؟')){
    return;}lines=[];render();setLabels();};
  function srcMode(){var f=free();
   if($('stw'))$('stw').style.display=sale?(f?'':'none'):'';
   if(!sale){var s=$('stock'),opts=f?D.stock:D.dest,keep=s.value;
    s.innerHTML=opts.map(function(o){return '<option value="'+o.id+'">'+MW.esc(o.label)+'</option>';}).join('');
    var want=opts.filter(function(o){return o.code===(f?'1230':'1200');})[0];
    s.value=opts.some(function(o){return String(o.id)===keep;})?keep:(want?want.id:(opts[0]||{}).id);}
   $('eno').placeholder=f?(sale?'اكتب الرقم كما تريده (ولو تكرّر)':'الرقم كما في فاتورة المورد')
    :(sale?'امسح الباركود أو اكتب الرقم':'رقمٌ جديد للطقم');bal();}
  document.querySelectorAll('input[name="src"]').forEach(function(r){r.onchange=function(){
   if(lines.length&&!confirm('تغيير مصدر الأصناف يفرّغ الأسطر — متابعة؟')){
    document.querySelector('input[name="src"][value="'+(free()?'vault':'free')+'"]').checked=true;return;}
   lines=[];render();srcMode();};});
  function bal(){if(!$('stbal'))return;var s=$('stock');$('stbal').textContent='';
   if(!free()&&sale)return;MW.get('/tax/api/bal',{id:s.value}).then(function(r){
    $('stbal').textContent=r&&r.ok?r.text:'';});}
  if($('stock'))$('stock').onchange=bal;
  if(sale){var stdNow=function(){var st=radio('st')==='standard';
    $('pcap').textContent=st?'الحساب — ذو الرقم الضريبي':'الحساب — أو «عميل نقدي»';
    var w=party&&party.id===D.walkin;['wnw','wpw'].forEach(function(i){$(i).classList.toggle('hide',!w);});
    var pay=$('pay'),o=pay.querySelector('option[value="credit"]');
    if(o){o.disabled=!!w;if(w&&pay.value==='credit')pay.selectedIndex=1;}
    $('post').textContent=st?'✔ ترحيل الفاتورة الضريبية':'✔ ترحيل الفاتورة المبسطة';};
   document.querySelectorAll('input[name="st"]').forEach(function(r){r.onchange=function(){
    party=null;$('party').value='';$('pinfo').textContent='';stdNow();};});
   var wb=document.createElement('button');wb.type='button';wb.className='btn sm gh';
   wb.textContent='👤 عميل نقدي — بلا حساب';wb.style.marginTop='6px';
   wb.onclick=function(){document.querySelector('input[name="st"][value="simplified"]').checked=true;
    party={id:D.walkin,label:'عميل نقدي'};$('party').value='عميل نقدي — بلا حساب';
    $('pinfo').textContent='اكتب اسم المشتري وجواله — ويدفع في الحال';stdNow();};
   $('party').parentNode.appendChild(wb);stdNow();}
  // من أطقم الخزنة (البيع): الرقم يُسأل عنه — وزنه الباقي وأجره
  function look(){if(free()||!sale)return Promise.resolve(true);var no=$('eno').value.trim();
   if(!no)return Promise.resolve(false);if(cur&&cur.no===no)return Promise.resolve(true);
   return MW.get('/tax/api/wo',{no:no,d:$('date').value}).then(function(r){
    if(!r.ok){MW.toast(r.error,false);$('eno').select();cur=null;return false;}
    cur=r;$('ek').value=r.karat;curK=r.karat;$('ew').value=r.bulk?'':r.avail.toFixed(2);
    if(!piece())$('erate').value=(r.wage*(incl()?1+D.vat:1)).toFixed(2);
    $('einfo').textContent=(r.bulk?'رقمٌ تجميعي — اكتب الوزن':'الباقي في الخزنة '+
     r.avail.toFixed(2)+' عيار '+r.karat);lineNow();$('erate').focus();return true;});}
  $('eno').addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();
   look().then(function(ok){if(ok)(free()?$('ew'):$('erate')).focus();});}});
  $('ek').onchange=function(){var nk=+$('ek').value,w=MW.num($('ew')),g=MW.num($('erate'));
   if(w)$('ew').value=wk(w18(w,curK),nk).toFixed(2);
   if(g&&!piece())$('erate').value=(g*curK/nk).toFixed(2);curK=nk;lineNow();};
  function add(){look().then(function(ok){if(!ok)return;
   var no=$('eno').value.trim().replace(/\s+/g,' '),w=MW.num($('ew')),k=+$('ek').value,
    r=MW.num($('erate')),gp=MW.num($('egp'));
   if(!no){MW.toast('اكتب رقم الباركود/الصنف',false);$('eno').focus();return;}
   if(w<=0){MW.toast('اكتب الوزن',false);$('ew').focus();return;}
   if(!free()&&sale&&cur&&!cur.bulk&&w18(w,k)>cur.avail18+0.006){
    MW.toast('الوزن أكبر من الباقي في الخزنة ('+cur.avail.toFixed(2)+')',false);return;}
   if(lines.some(function(l){return l.no===no;})&&!free()){MW.toast('الرقم مضافٌ من قبل',false);return;}
   if(riyal()&&gp<=0){MW.toast('اكتب سعر الجرام (عيار '+k+')',false);$('egp').focus();return;}
   var l={no:no,pieces:Math.max(1,Math.round(MW.num($('epc'))||1)),weight:w,karat:k,gp:riyal()?gp:0,
    wage:piece()?0:r,price:piece()?r:0};
   if(incl()){l.incl=piece()?R2(r):(typedTot!=null?typedTot:R2(w*r));
    if(!(l.incl>0)){MW.toast('اكتب المبلغ شاملاً الضريبة',false);$('erate').focus();return;}}
   else if(piece()&&r<=0){MW.toast('اكتب سعر الطقم',false);$('erate').focus();return;}
   lines.push(l);cur=null;typedTot=null;['eno','ew','erate','enet'].forEach(function(i){$(i).value='';});
   $('epc').value='1';$('einfo')&&($('einfo').textContent='');render();$('eno').focus();});}
  $('eadd').onclick=add;
  ['ew','egp','erate','enet'].forEach(function(i){$(i).addEventListener('keydown',function(e){
   if(e.key==='Enter'){e.preventDefault();add();}});});
  render=function(){applyIncl();var t=$('lines');while(t.rows.length>1)t.deleteRow(1);
   var tw=0,tgv=0,tnet=0,pcs=0,bad=[];
   lines.forEach(function(l,i){var c=lineNet(l);tw+=w18(l.weight,l.karat);tgv+=c.gv;
    tnet+=c.net;pcs+=l.pieces;if(c.bad)bad.push(l.no+': '+c.bad);
    var r=t.insertRow(-1);r.innerHTML='<td>'+(i+1)+'</td><td class="n">'+MW.esc(l.no)+
     '</td><td class="n">'+l.pieces+'</td><td class="n">'+MW.fmt(l.weight)+'</td><td>'+l.karat+
     '</td><td class="n">'+(riyal()?MW.fmt(l.gp):'—')+'</td><td class="n">'+
     (piece()?MW.fmt(l.price):MW.fmt(l.wage))+'</td><td class="n">'+(riyal()?MW.fmt(c.gv):'—')+
     '</td><td class="n">'+MW.fmt(c.net)+'</td><td class="acts">'+X+'</td>';
    r.querySelector('[data-x]').onclick=function(){lines.splice(i,1);render();};});
   var disc=incl()?0:Math.min(MW.num($('disc')),tnet),b=R2(tnet-disc),v=vatOf(b);
   kpis([['الأصناف',lines.length,0,MW.fmt(wk(tw,D.k))+' '+D.unit+(pcs?' · '+pcs+' قطعة':'')],
    ['قيمة الذهب',riyal()?MW.fmt(tgv):'—',0,riyal()?'بالريال':'ذهبٌ بالوزن'],
    ['الصافي الخاضع',MW.fmt(b),0,disc?('بعد خصم '+MW.fmt(disc)):'قبل الضريبة'],
    [(sale?'ضريبة المخرجات ':'ضريبة المدخلات ')+Math.round(D.vat*100)+'%',MW.fmt(v)],
    ['الإجمالي شامل الضريبة',MW.fmt(b+v),1]]);
   var tot=lines.reduce(function(a,l){return a+(l.incl||0);},0);
   $('hint').textContent=bad.length?'⚠ '+bad.join(' · '):(incl()&&lines.length?
    ((piece()?'سعر الطقم':'الأجور')+' مكتوبةٌ شاملةً الضريبة ('+MW.fmt(tot)+
     ' ريال) — والنظام فصلها: الصافي = المبلغ ÷ '+(1+D.vat)+' والباقي ضريبة'):
    (!riyal()?(sale?'الذهب يُقيَّد على المشتري وزناً، والضريبة على الأجور وحدها':
     'الذهب يُقيَّد للمورد وزناً، والضريبة على الأجور وحدها'):
     (piece()?'الفاتورة كلها بالريال: الصافي سعر الطقم — والضريبة عليه كله':
      'الفاتورة كلها بالريال: الصافي = الوزن × (سعر الجرام + الأجر) — والضريبة عليه كله')));};
  if($('disc'))$('disc').addEventListener('input',function(){render();});
  build=function(){if(!party){MW.toast('اختر الحساب من الاقتراحات',false);$('party').focus();return null;}
   if(!lines.length){MW.toast('أضف صنفاً واحداً على الأقل',false);return null;}
   if(!sale&&!$('supinv').value.trim()){MW.toast('اكتب رقم فاتورة المورد',false);$('supinv').focus();return null;}
   var walk=sale&&party.id===D.walkin;
   if(walk&&$('pay').value==='credit'){MW.toast('«العميل النقدي» يدفع في الحال — اختر الصندوق أو البنك',false);return null;}
   return {party:party.id,subtype:sale?radio('st'):'',date:$('date').value,pay:$('pay').value,
    pricing:pricing(),src:radio('src'),stock:$('stock')?$('stock').value:'',
    disc:$('disc')?MW.num($('disc')):0,notes:$('notes').value,supinv:sale?'':$('supinv').value,
    wname:sale?$('wname').value:'',wphone:sale?$('wphone').value:'',
    lines:lines.map(function(l){return {no:l.no,pieces:l.pieces,weight:l.weight,karat:l.karat,
     gp:l.gp,rate:piece()?l.price:l.wage,incl:l.incl||0};})};};
  summary=function(){var tt=$('tot').querySelector('.kpi.gold .v');
   return (sale?(radio('st')==='standard'?'فاتورة ضريبية':'فاتورة مبسطة'):'فاتورة مشتريات ضريبية')+
    ' — «'+party.label+'»\n'+$('pricing').selectedOptions[0].text+' · الدفع: '+
    $('pay').selectedOptions[0].text+'\n'+lines.length+' صنف — الإجمالي '+(tt?tt.textContent:'')+' ريال';};
  reset=function(){lines=[];render();$('notes').value='';if($('disc'))$('disc').value='';
   if(!sale)$('supinv').value='';};
  URL=sale?'/tax/post/tax_sale':'/tax/post/tax_pur';
  setLabels();srcMode();render();}
 // ═══ المرتجعان ═══
 else if(MODE==='sret'||MODE==='pret'){
  var O=null;
  function load(){var id=$('orig').value;O=null;lines=[];
   if(!id){$('pinfo').textContent='';draw();return;}
   MW.get('/tax/api/'+MODE,{id:id}).then(function(r){if(!r.ok){MW.toast(r.error,false);return;}
    O=r;$('pinfo').textContent=r.info;lines=r.rows.map(function(x){return {x:x,v:0};});draw();});}
  $('orig').onchange=load;
  function draw(){var t=$('lines');while(t.rows.length>1)t.deleteRow(1);
   lines.forEach(function(l,i){var x=l.x,r=t.insertRow(-1),can=x.left>0&&!x.why;
    var edit=MODE==='sret'||x.part;
    r.innerHTML='<td><input type="checkbox" class="ck"'+(can?'':' disabled')+(l.v>0?' checked':'')+
     '></td><td class="n">'+MW.esc(x.no)+(x.why?'<br><small class="note">'+MW.esc(x.why)+'</small>':'')+
     '</td><td class="n">'+(x.pieces||'—')+'</td><td class="n">'+MW.fmt(x.w)+'</td><td class="n">'+
     MW.fmt(x.left)+'</td><td>'+x.k+'</td><td>'+MW.esc(x.price)+'</td><td class="n tw">'+
     (edit?'<input class="num rw" inputmode="decimal" value="'+(l.v?l.v.toFixed(2):'')+'"'+(can?'':' disabled')+'>':
      (l.v?MW.fmt(l.v):''))+'</td><td class="n nt"></td>';
    var ck=r.querySelector('.ck'),rw=r.querySelector('.rw');
    ck.onchange=function(){l.v=ck.checked?x.left:0;if(rw)rw.value=l.v?l.v.toFixed(2):'';
     if(!rw)draw();else calc();};
    if(rw)rw.addEventListener('input',function(){l.v=Math.min(Math.max(0,MW.num(rw)),x.left);
     ck.checked=l.v>0;calc();});});
   calc();}
  function calc(){var n=0,net=0,rows=$('lines').rows;
   lines.forEach(function(l,i){var c=rows[i+1]&&rows[i+1].querySelector('.nt');
    if(!(l.v>0)){if(c)c.textContent='';return;}var f=l.x.w>0?l.v/l.x.w:1,v=R2(l.x.net*f);
    n++;net+=v;if(c)c.textContent=MW.fmt(v);});
   var disc=O&&O.disc>0&&O.orig_net>0?R2(O.disc*net/O.orig_net):0,b=R2(net-disc),vt=vatOf(b);
   kpis([['الأصناف',n],['الصافي',MW.fmt(b),0,disc?('بعد خصمٍ مردود '+MW.fmt(disc)):''],
    ['الضريبة '+Math.round(D.vat*100)+'%',MW.fmt(vt)],['الإجمالي',MW.fmt(b+vt),1]]);}
  $('all').onclick=function(){lines.forEach(function(l){if(l.x.left>0&&!l.x.why)l.v=l.x.left;});draw();};
  dirty=function(){return lines.some(function(l){return l.v>0;});};
  build=function(){if(!O){MW.toast('اختر الفاتورة الأصلية',false);return null;}
   if(!$('reason').value.trim()){MW.toast('اكتب السبب (إلزامي)',false);$('reason').focus();return null;}
   var rets=lines.filter(function(l){return l.v>0;}).map(function(l){return {id:l.x.id,weight:l.v};});
   if(!rets.length){MW.toast('حدّد صنفاً واحداً على الأقل للإرجاع',false);return null;}
   return {orig:+$('orig').value,reason:$('reason').value,date:$('date').value,rets:rets};};
  summary=function(){var tt=$('tot').querySelector('.kpi.gold .v');
   return (MODE==='sret'?'مرتجع مبيعات (إشعار دائن)':'مرتجع مشتريات')+' على '+O.no+' — '+O.who+
    '\nالإجمالي '+(tt?tt.textContent:'')+' ريال\nالسبب: '+$('reason').value;};
  reset=function(){setTimeout(function(){location.reload();},1500);};
  URL=MODE==='sret'?'/tax/post/tax_sale_ret':'/tax/post/tax_pur_ret';draw();}
 // ═══ المشتريات النقدية ═══
 else if(MODE==='cash'){
  var OP='buy';
  document.querySelectorAll('.opsel button').forEach(function(b){b.onclick=function(){
   OP=b.getAttribute('data-op');document.querySelectorAll('.opsel button').forEach(function(x){
    x.classList.toggle('on',x===b);});var ret=OP==='ret';
   $('ctitle').textContent=ret?'① مرتجع مشتريات':'① فاتورة مشتريات';
   $('invcap').textContent=ret?'رقم إشعار المورد':'رقم فاتورة المورد';
   $('post').textContent=ret?'✔ ترحيل مرتجع المشتريات':'✔ ترحيل فاتورة المشتريات';
   $('pinfo').textContent=ret?'المرتجع عكس الشراء: يُنقص رصيد الحساب (أو يُستردّ نقداً/بنكاً) ويُخرج المبلغ من حساب المصروف ويعكس ضريبة المدخلات':'';};});
  function accs(){var k=$('kind').value,s=$('acc');s.innerHTML=(D.accs[k]||[]).map(function(o){
    return '<option value="'+MW.esc(o.id)+'">'+MW.esc(o.label)+'</option>';}).join('');
   var d=(D.accs[k]||[]).filter(function(o){return o.id===(k==='asset'?'1710':'5500');})[0];
   if(d)s.value=d.id;$('lifew').classList.toggle('hide',k!=='asset');}
  $('kind').onchange=function(){if(lines.length&&!confirm('تغيير نوع الشراء يفرّغ الأسطر — متابعة؟'))return;
   lines=[];accs();render();};accs();
  function calcL(l){var g=R2(l.qty*l.price),n=R2(g-l.disc),
   v=D.nov.indexOf($('treat').value)>=0?0:vatOf(n);return {g:g,n:n,v:v};}
  function add(){var q=MW.num($('cq'))||1,p=MW.num($('cp')),d=MW.num($('cd'));
   if(!$('acc').value){MW.toast('اختر الحساب',false);return;}
   if(R2(q*p-d)<=0){MW.toast('المبلغ بعد الخصم يجب أن يكون أكبر من صفر',false);$('cp').focus();return;}
   lines.push({acc:$('acc').value,label:$('acc').selectedOptions[0].text,qty:q,price:p,disc:d});
   $('cp').value='';$('cd').value='';$('cq').value='1';render();$('cp').focus();}
  $('cadd').onclick=add;['cq','cp','cd'].forEach(function(i){$(i).addEventListener('keydown',
   function(e){if(e.key==='Enter'){e.preventDefault();add();}});});
  $('treat').onchange=function(){render();};
  render=function(){var t=$('lines');while(t.rows.length>1)t.deleteRow(1);var S={g:0,d:0,n:0,v:0};
   lines.forEach(function(l,i){var c=calcL(l);S.g+=c.g;S.d+=l.disc;S.n+=c.n;S.v+=c.v;
    var r=t.insertRow(-1);r.innerHTML='<td>'+(i+1)+'</td><td>'+MW.esc(l.label)+'</td><td class="n">'+
     l.qty+'</td><td class="n">'+MW.fmt(l.price)+'</td><td class="n">'+MW.fmt(c.g)+'</td><td class="n">'+
     MW.fmt(l.disc)+'</td><td class="n">'+MW.fmt(c.v)+'</td><td class="n">'+MW.fmt(c.n+c.v)+
     '</td><td class="acts">'+X+'</td>';r.querySelector('[data-x]').onclick=function(){
     lines.splice(i,1);render();};});
   kpis([['المبلغ',MW.fmt(S.g),0,'قبل الخصم والضريبة'],['الخصم',MW.fmt(S.d)],
    ['الصافي الخاضع',MW.fmt(S.n)],['ضريبة المدخلات',MW.fmt(S.v)],
    ['إجمالي الفاتورة',MW.fmt(S.n+S.v),1]]);$('hint').textContent='';};
  build=function(){if(!party){MW.toast('اختر الحساب من الاقتراحات',false);$('party').focus();return null;}
   if(!lines.length){MW.toast('أضف سطراً واحداً على الأقل: الحساب والعدد والسعر',false);return null;}
   if(!$('notes').value.trim()){MW.toast('اكتب البيان — ما الذي اشتُري',false);$('notes').focus();return null;}
   return {op:OP,party:party.id,supinv:$('supinv').value,date:$('date').value,itype:$('itype').value,
    pay:$('pay').value,kind:$('kind').value,treat:$('treat').value,life:MW.num($('life')),
    notes:$('notes').value,lines:lines.map(function(l){return {acc:l.acc,qty:l.qty,price:l.price,disc:l.disc};})};};
  summary=function(){var tt=$('tot').querySelector('.kpi.gold .v');
   return (OP==='ret'?'مرتجع مشتريات':'فاتورة مشتريات')+' — «'+party.label+'»\n'+
    $('pay').selectedOptions[0].text+'\nالإجمالي '+(tt?tt.textContent:'')+' ريال';};
  reset=function(){lines=[];render();$('notes').value='';$('supinv').value='';};
  URL='/tax/post/cash_pur';render();}
 $('clear').onclick=function(){if(dirty()&&!confirm('تفريغ الأسطر؟'))return;reset();};
 var busy=false;
 $('post').onclick=function(){if(busy)return;var p=build();if(!p)return;
  MW.confirm('تأكيد الترحيل',summary()+'\n\nتُرحَّل في دفاتر المصنع الآن.').then(function(y){
   if(!y)return;busy=true;var b=$('post'),t=b.textContent;b.disabled=true;b.textContent='… جارٍ الترحيل';
   p.nonce=NONCE;MW.post(URL,p).then(function(r){busy=false;b.disabled=false;b.textContent=t;
    if(!r.ok){if(r.locked&&r.unlock){location.href=r.unlock+'?next='+
     encodeURIComponent(location.pathname+location.search);return;}
     MW.toast(r.error||'تعذّر الترحيل',false);return;}
    NONCE=nn();reset();var ok=$('okbox');ok.style.display='block';
    ok.innerHTML='✔ '+MW.esc(r.msg)+(r.links||[]).map(function(l){return ' <a class="btn sm gh" '+
     'target="_blank" rel="noopener" href="'+MW.esc(MW.base+l[1])+'">'+MW.esc(l[0])+'</a>';}).join('');
    ok.scrollIntoView({behavior:'smooth',block:'center'});MW.toast('تم الترحيل: '+(r.no||''),true);});});};
 window.addEventListener('beforeunload',function(e){if(dirty()){e.preventDefault();e.returnValue='';}});
})();
"""
