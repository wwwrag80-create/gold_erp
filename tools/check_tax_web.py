"""5.8.5: المبيعات والمشتريات الضريبية من رابط المدير.

    python3 tools/check_tax_web.py [مجلد_للصور]

يمرّ على `models_web.handle` مباشرةً: الصفحتان بأقسامهما، والاقتراح، ثم
ترحيل كل مستند (فاتورة ضريبية · مبسطة لعميلٍ نقدي · «شامل الضريبة» ·
إشعار دائن · فاتورة مشتريات ذهب · مرتجعها · مشتريات نقدية ومرتجعها) بدوالّ
البرنامج نفسها — والقفل برمز لوحة العمليات، والإيقاف من البرنامج، والضغطة
الواحدة = مستندٌ واحد، والسجلّان. وفي آخره: الدفتر متوازن.
ومع مجلدٍ للصور: تُفتح الصفحات في متصفحٍ حقيقي (جوال وكمبيوتر) وتُصوَّر.
"""
import datetime
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
T = tempfile.mkdtemp(prefix="taxweb_")
os.environ["GOLD_ERP_DATA_DIR"] = T
import config  # noqa: E402

config.DB_PATH = pathlib.Path(T) / "t.db"
OUT = sys.argv[1] if len(sys.argv) > 1 else ""
import main  # noqa: E402

for _l, f in main.prepare_steps():
    f()
from database.database import db  # noqa: E402
from models.entities import add_entity  # noqa: E402
from services import manager_web as mweb  # noqa: E402
from services import models_web as mw  # noqa: E402
from services import tax_web  # noqa: E402

OK, BAD = [], []


def check(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print(("  ✔ " if cond else "  ✘ ") + name + ("" if cond else f"  [{info}]"))


D0 = datetime.date.today().isoformat()
with db() as c:
    SHOP = add_entity(c, "شركة الريان", "customer", username="t",
                      vat_number="300000000000003")
    IND = add_entity(c, "عميل فرد", "customer", username="t")
    SUP = add_entity(c, "مورد الذهب", "supplier", username="t",
                     vat_number="311111111111113")
    TOK = mw.ensure_token(c)
    mw.set_enabled(c, True)
    mweb.set_ops_enabled(c, True)
    SECRET = mw._get(c, mw.K_SECRET)
    BOX = c.execute("SELECT id FROM accounts WHERE code='1400'").fetchone()[0]
    STOCK = c.execute("SELECT id FROM accounts WHERE code='1230'"
                      ).fetchone()[0]

OPS = {"cookie": True}
N = {"n": 0}


def call(method, path, query=None, body=None):
    with db(readonly=True) as c:
        opin = mw._get(c, mweb.K_OPS_PIN).strip()
    headers = {}
    if opin and OPS["cookie"]:
        headers["Cookie"] = (f"{mweb.OPS_COOKIE}="
                             f"{mweb._ops_cookie_value(mw._csrf(TOK, SECRET), opin)}")
    parts = [TOK] + [p for p in path.split("/") if p]
    raw = (json.dumps(body, ensure_ascii=False).encode("utf-8")
           if body is not None else None)
    r = mw.handle(method, parts, query or {}, headers, raw)
    b = r["body"]
    return r["code"], (b.decode("utf-8", "replace")
                       if isinstance(b, bytes) else b)


def post(kind, data, nonce=None):
    N["n"] += 1
    data = dict(data, csrf=mw._csrf(TOK, SECRET),
                nonce=nonce or f"nonce-{N['n']:06d}")
    _c, b = call("POST", f"tax/post/{kind}", body=data)
    return json.loads(b)


def last(table, order="id"):
    with db(readonly=True) as c:
        return dict(c.execute(f"SELECT * FROM {table} ORDER BY {order} DESC"
                              " LIMIT 1").fetchone())


print("── 1) الصفحتان بأقسامهما")
for path, q, want in (("taxs", {}, "فاتورة ضريبية"),
                      ("taxs", {"tab": "ret"}, "مرتجع مبيعات"),
                      ("taxs", {"tab": "reg"}, "صافي ضريبة المخرجات"),
                      ("taxp", {}, "فاتورة مشتريات ذهب"),
                      ("taxp", {"tab": "ret"}, "فاتورة الشراء الأصلية"),
                      ("taxp", {"tab": "cash"}, "مرتجع مشتريات"),
                      ("taxp", {"tab": "reg"}, "ضريبة المدخلات")):
    code, h = call("GET", path, q)
    check(f"/{path} {q.get('tab', 'inv')} يفتح", code == 200 and want in h,
          (code, h[:200]))
code, h = call("GET", "taxs")
check("طرق التسعير كلها ومنها «شامل الضريبة»", all(
    x in h for x in ("الأجر فقط — الذهب بالوزن", "سعر الجرام + الأجر",
                     "سعر الطقم — بالريال", "الأجر شامل الضريبة",
                     "سعر الطقم شامل الضريبة")))
check("نوع الفاتورة (ضريبية · مبسطة) ومصدر الأصناف وحساب المخزون والدفع",
      all(x in h for x in ("ضريبية (شركة)", "مبسطة (فرد)", "إدخال يدوي حر",
                           "من أطقم الخزنة", "حساب المخزون",
                           "آجل — على حساب المشتري")))

print("── 2) الاقتراح")
_c, j = call("GET", "tax/api/party", {"q": "ع", "std": "1"})
ids = [x["id"] for x in json.loads(j)]
check("الفاتورة الضريبية: ذوو الرقم الضريبي وحدهم", IND not in ids, ids)
_c, j = call("GET", "tax/api/party", {"q": "مورد"})
check("وأي حساب بنوعه (المورد في المبيعات أيضاً)",
      any(x["id"] == SUP and "مورد" in x["sub"] for x in json.loads(j)), j)

print("── 3) المبيعات الضريبية")
r = post("tax_sale", {
    "party": SHOP, "subtype": "standard", "date": D0, "pay": "credit",
    "pricing": "wage", "src": "free", "stock": STOCK, "disc": 0,
    "notes": "من الرابط", "lines": [
        {"no": "A-1", "pieces": 1, "weight": 10, "karat": 18, "rate": 20}]})
inv1 = last("invoices")
check("فاتورة ضريبية «الأجر فقط»: 200 + 30 = 230", r.get("ok")
      and round(inv1["grand_total"], 2) == 230 and inv1["pricing"] == "wage"
      and inv1["created_by"] == mweb.WEB_USER, r)
r = post("tax_sale", {
    "party": SHOP, "subtype": "standard", "date": D0, "pay": "credit",
    "pricing": "wage_incl", "src": "free", "stock": STOCK, "lines": [
        {"no": "A-2", "pieces": 1, "weight": 8, "karat": 18, "incl": 1150},
        {"no": "A-3", "pieces": 1, "weight": 2, "karat": 21, "incl": 230}]})
inv2 = last("invoices")
check("«الأجر شامل الضريبة»: 1150 + 230 = 1380 بالهللة (1200 + 180)",
      r.get("ok") and round(inv2["grand_total"], 2) == 1380
      and round(inv2["vat_amount"], 2) == 180, (r, dict(inv2)))
r = post("tax_sale", {
    "party": "walkin", "subtype": "simplified", "date": D0, "pay": BOX,
    "pricing": "piece_incl", "src": "free", "stock": STOCK,
    "wname": "أحمد", "wphone": "0500000000", "lines": [
        {"no": "W-1", "pieces": 2, "weight": 5, "karat": 18, "gp": 100,
         "incl": 1000}]})
inv3 = last("invoices")
check("مبسطة لعميلٍ نقدي «سعر الطقم شامل»: 1000 ← أقرب هللة 999.99",
      r.get("ok") and inv3["tax_subtype"] == "simplified"
      and inv3["buyer_name"] == "أحمد" and inv3["pay_account_id"] == BOX
      and round(inv3["grand_total"], 2) == 999.99, (r, dict(inv3)))
r = post("tax_sale", {"party": "walkin", "subtype": "simplified", "date": D0,
                      "pay": "credit", "pricing": "piece", "src": "free",
                      "stock": STOCK, "lines": [
                          {"no": "W-2", "weight": 1, "karat": 18, "gp": 100,
                           "rate": 300}]})
check("والعميل النقدي لا يُباع له آجلاً", not r.get("ok")
      and "يدفع في الحال" in r.get("error", ""), r)
r = post("tax_sale", {"party": IND, "subtype": "standard", "date": D0,
                      "pay": "credit", "pricing": "wage", "src": "free",
                      "stock": STOCK, "lines": [
                          {"no": "X", "weight": 1, "karat": 18, "rate": 5}]})
check("والضريبية لفردٍ بلا رقمٍ ضريبي تُرفض برسالة البرنامج", not r.get("ok")
      and "رقمٍ ضريبي" in r.get("error", ""), r)

print("── 4) مرتجع المبيعات (إشعار دائن)")
code, h = call("GET", "taxs", {"tab": "ret"})
check("الفاتورة في قائمة ما يُرتجع", inv1["invoice_no"] in h)
_c, j = call("GET", "tax/api/sret", {"id": inv1["id"]})
rr = json.loads(j)
check("أسطرها بباقيها وسعرها", rr.get("ok") and rr["rows"][0]["left"] == 10
      and "أجر 20.00/جم" in rr["rows"][0]["price"], rr)
r = post("tax_sale_ret", {"orig": inv1["id"], "date": D0, "reason":
                          "إرجاع بضاعة من العميل", "rets": [
                              {"id": rr["rows"][0]["id"], "weight": 4}]})
cn = last("invoices")
check("إشعار دائن بـ4 جم من 10: 80 + 12 = 92", r.get("ok")
      and cn["kind"] == "sale_return" and round(cn["grand_total"], 2) == 92,
      (r, dict(cn)))
r = post("tax_sale_ret", {"orig": inv1["id"], "date": D0, "reason": "",
                          "rets": [{"id": rr["rows"][0]["id"], "weight": 1}]})
check("والسبب إلزامي", not r.get("ok") and "سبب" in r.get("error", ""), r)

print("── 5) المشتريات الضريبية")
r = post("tax_pur", {"party": SUP, "supinv": "S-77", "date": D0,
                     "pay": "credit", "pricing": "wage", "src": "free",
                     "stock": STOCK, "lines": [
                         {"no": "P-1", "pieces": 1, "weight": 20,
                          "karat": 18, "rate": 10}]})
p1 = last("set_purchases")
check("فاتورة مشتريات ذهب: 200 + 30", r.get("ok") and p1["kind"] ==
      "purchase" and round(p1["total"], 2) == 230
      and p1["supplier_inv_no"] == "S-77", (r, dict(p1)))
r = post("tax_pur", {"party": SUP, "supinv": "", "date": D0, "pay": "credit",
                     "pricing": "wage", "src": "free", "stock": STOCK,
                     "lines": [{"no": "P-2", "weight": 1, "karat": 18,
                                "rate": 1}]})
check("ورقم فاتورة المورد إلزامي", not r.get("ok")
      and "فاتورة المورد" in r.get("error", ""), r)
r = post("tax_pur", {"party": SHOP, "supinv": "S-78", "date": D0,
                     "pay": "credit", "pricing": "wage_incl", "src": "free",
                     "stock": STOCK, "lines": [
                         {"no": "P-3", "weight": 10, "karat": 18,
                          "incl": 575}]})
p2 = last("set_purchases")
check("شراءٌ من عميل (أي حساب) بـ«شامل الضريبة»: 500 + 75 = 575",
      r.get("ok") and round(p2["total"], 2) == 575
      and round(p2["vat"], 2) == 75, (r, dict(p2)))
_c, j = call("GET", "tax/api/pret", {"id": p1["id"]})
pr = json.loads(j)
r = post("tax_pur_ret", {"orig": p1["id"], "date": D0,
                         "reason": "إرجاع بضاعة للمورد", "rets": [
                             {"id": pr["rows"][0]["id"], "weight": 5}]})
p3 = last("set_purchases")
check("مرتجع مشتريات بـ5 جم من 20: 50 + 7.5", r.get("ok")
      and p3["kind"] == "purchase_return"
      and round(p3["total"], 2) == 57.5, (r, dict(p3)))

print("── 6) المشتريات النقدية")
r = post("cash_pur", {"op": "buy", "party": SUP, "supinv": "E-1",
                      "date": D0, "itype": "standard", "pay": "credit",
                      "kind": "expense", "treat": "standard",
                      "notes": "صيانة", "lines": [
                          {"acc": "5500", "qty": 2, "price": 100,
                           "disc": 0}]})
g1 = last("purchases")
check("مشتريات نقدية (مصروف): 200 + 30", r.get("ok")
      and round(g1["total"], 2) == 230 and not g1.get("is_return"),
      (r, g1))
r = post("cash_pur", {"op": "ret", "party": SUP, "supinv": "", "date": D0,
                      "itype": "standard", "pay": "credit", "notes": "إرجاع",
                      "kind": "expense", "treat": "standard", "lines": [
                          {"acc": "5500", "qty": 1, "price": 50,
                           "disc": 0}]})
g2 = last("purchases")
check("ومرتجعها (بالأحمر في الشاشة): 50 + 7.5", r.get("ok")
      and round(g2["total"], 2) == 57.5, (r, g2))

print("── 7) السجلّان")
code, h = call("GET", "taxs", {"tab": "reg", "all": "1"})
check("سجل المبيعات: الفواتير والإشعار بزرّ «عرض»", all(
    x in h for x in (inv1["invoice_no"], inv2["invoice_no"],
                     cn["invoice_no"])) and "/doc/invoices/" in h, h[-400:])
code, h = call("GET", "taxs", {"tab": "reg", "q": inv2["invoice_no"]})
check("والبحث في كل الفترات", inv2["invoice_no"] in h
      and inv1["invoice_no"] not in h)
code, h = call("GET", "taxp", {"tab": "reg", "all": "1"})
check("سجل المشتريات: الذهب والنقدية ومرتجعاتها", all(
    x in h for x in (p1["doc_no"], p3["doc_no"], g1["purchase_no"])))

print("── 8) الحماية")
r1 = post("cash_pur", {"op": "buy", "party": SUP, "supinv": "E-9",
                       "date": D0, "itype": "standard", "pay": "credit",
                       "kind": "expense", "treat": "standard",
                       "notes": "قرطاسية", "lines": [
                           {"acc": "5500", "qty": 1, "price": 10,
                            "disc": 0}]}, nonce="same-nonce-1")
r2 = post("cash_pur", {"op": "buy", "party": SUP, "supinv": "E-9",
                       "date": D0, "itype": "standard", "pay": "credit",
                       "kind": "expense", "treat": "standard",
                       "notes": "قرطاسية", "lines": [
                           {"acc": "5500", "qty": 1, "price": 10,
                            "disc": 0}]}, nonce="same-nonce-1")
with db(readonly=True) as c:
    n9 = c.execute("SELECT COUNT(*) FROM purchases WHERE supplier_invoice_no"
                   "='E-9'").fetchone()[0]
check("الضغطة المكرّرة = مستندٌ واحد", r1.get("ok") and r2.get("again")
      and n9 == 1, (r1, r2, n9))
_c, b = call("POST", "tax/post/tax_sale", body={"csrf": "x"})
check("بلا رمز الصفحة (CSRF) ⇒ مرفوض", _c == 403)
with db() as c:
    mweb.set_ops_pin(c, "4321")
OPS["cookie"] = False
code, h = call("GET", "taxs")
check("5.8.6: المقفلة تفتح على سجلّها بلا رمز — والعمليات بـ🔒", code == 200
      and "صافي ضريبة المخرجات" in h and "فاتورة ضريبية 🔒" in h
      and "رمز اللوحة" not in h, h[:300])
code, h = call("GET", "taxp", {"tab": "reg", "all": "1"})
check("وسجل المشتريات يُقرأ بلا رمز", "ضريبة المدخلات" in h
      and "رمز اللوحة" not in h)
code, h = call("GET", "taxs", {"tab": "inv"})
check("وفاتورة البيع تطلب رمز اللوحات", "رمز اللوحة" in h
      and "طريقة التسعير" not in h)
code, h = call("GET", "taxp", {"tab": "cash"})
check("والمشتريات النقدية كذلك", "رمز اللوحة" in h)
r = post("tax_sale", {"party": SHOP})
check("والترحيل بلا الرمز مقفل", r.get("locked") is True, r)
OPS["cookie"] = True
code, h = call("GET", "taxs")
check("وبالرمز تفتح", "طريقة التسعير" in h)
with db() as c:
    mweb.set_ops_enabled(c, False)
code, h = call("GET", "taxp")
check("إيقاف التسجيل يقفل عمليات الشاشتين", "من الرابط موقوف" in h)
code, h = call("GET", "taxp", {"tab": "reg"})
check("ويبقى السجل يُقرأ", "ضريبة المدخلات" in h
      and "من الرابط موقوف" not in h)
with db() as c:
    mweb.set_ops_enabled(c, True)

print("── 9) الدفتر والواجهة")
with db(readonly=True) as c:
    gd, cd = c.execute(
        "SELECT ROUND(SUM(gold_debit-gold_credit),3),"
        " ROUND(SUM(cash_debit-cash_credit),2) FROM journal_lines l"
        " JOIN journal_entries e ON e.id=l.entry_id WHERE e.is_deleted=0"
        ).fetchone()
check("الدفتر متوازن (ذهباً ونقداً)", not gd and not cd, (gd, cd))
js = pathlib.Path(T) / "tax.js"
js.write_text(tax_web._TAX_JS, encoding="utf-8")
r = subprocess.run(["node", "--check", str(js)], capture_output=True,
                   text=True)
check("شيفرة الصفحة سليمة (node --check)", r.returncode == 0, r.stderr[:300])

if OUT:
    print("── 10) في متصفحٍ حقيقي (جوال وكمبيوتر)")
    from services import photo_server
    addr = photo_server.ensure_running(wait=8)
    mw.register()                    # مسار الرابط في الخادم (كالتفعيل)
    base = f"http://127.0.0.1:{addr[1]}/{mw.PREFIX}/{TOK}"
    opin = "4321"
    with db(readonly=True) as c:
        SHOP_CODE = c.execute("SELECT a.code FROM entities e JOIN accounts a"
                              " ON a.id=e.account_id WHERE e.id=?",
                              (SHOP,)).fetchone()[0]
    code = f"""
const {{ chromium }} = require('playwright');
(async () => {{
  const b = await chromium.launch();
  const errs = [];
  for (const [w, h, tag] of [[1366, 900, 'pc'], [390, 844, 'phone']]) {{
    const ctx = await b.newContext({{ viewport: {{ width: w, height: h }} }});
    const p = await ctx.newPage();
    p.on('pageerror', (e) => errs.push(String(e)));
    await p.goto('{base}/ops/unlock?next=' + encodeURIComponent('{base[base.index("/", 8):]}/taxs'));
    await p.fill('input[name=pin]', '{opin}');
    await Promise.all([p.waitForNavigation(), p.click('form button')]);
    for (const [u, n] of [['/taxs', 'sale'], ['/taxs?tab=reg&all=1', 'sreg'],
        ['/taxs?tab=ret', 'sret'], ['/taxp', 'pur'], ['/taxp?tab=cash', 'cash'],
        ['/taxp?tab=reg&all=1', 'preg'], ['/stmt?code={SHOP_CODE}', 'stmt'],
        ['/sec', 'sec'], ['', 'home']]) {{
      await p.goto('{base}' + u);
      await p.waitForTimeout(300);
      if (n === 'sale') {{
        await p.selectOption('#pricing', 'wage_incl');
        await p.fill('#party', 'شركة');
        await p.waitForTimeout(400);
        await p.click('.list [data-i="0"]');
        await p.fill('#eno', 'Z-1'); await p.fill('#ew', '10');
        await p.fill('#enet', '1150'); await p.press('#enet', 'Enter');
        await p.waitForTimeout(200);
      }}
      if (n === 'sret') {{
        await p.selectOption('#orig', {{ index: 1 }});
        await p.waitForTimeout(500);
        await p.click('#all'); await p.waitForTimeout(200);
        const tot = await p.locator('#tot .kpi.gold .v').innerText();
        if (!(parseFloat(tot.replace(/,/g, '')) > 0)) errs.push('sret total ' + tot);
      }}
      if (n === 'cash') {{
        await p.click('.opsel .ret'); await p.fill('#cp', '50');
        await p.press('#cp', 'Enter'); await p.waitForTimeout(200);
        const t = await p.locator('#tot .kpi.gold .v').innerText();
        if (t.trim() !== '57.50') errs.push('cash total ' + t);
        if (!(await p.locator('#post').innerText()).includes('مرتجع')) errs.push('cash ret label');
      }}
      if (n === 'stmt') {{
        const opts = await p.locator('#mop option').allInnerTexts();
        if (opts.length < 3) errs.push('stmt filter options ' + opts.join('|'));
        await p.selectOption('#mop', {{ index: 1 }});
        await p.waitForTimeout(200);
        const vis = await p.locator('tr[data-s]:visible').count();
        const all = await p.locator('tr[data-s]').count();
        const sum = await p.locator('#mopsum').innerText();
        if (!(vis > 0 && vis < all) || !sum.includes('حركة')) errs.push('stmt filter ' + vis + '/' + all + ' ' + sum);
      }}
      if (n === 'home') {{ await p.click('#more summary'); await p.waitForTimeout(200); }}
      await p.screenshot({{ path: '{OUT}/web_' + n + '_' + tag + '.png', fullPage: n !== 'home' }});
    }}
    await ctx.close();
  }}
  console.log(JSON.stringify(errs));
  await b.close();
}})();
"""
    jsf = pathlib.Path(T) / "shots.js"
    jsf.write_text(code, encoding="utf-8")
    r = subprocess.run(["node", str(jsf)], capture_output=True, text=True,
                       timeout=300)
    errs = r.stdout.strip().splitlines()[-1:] if r.stdout.strip() else []
    check("الصفحات تُفتح وتُصوَّر بلا خطأ في المتصفح", r.returncode == 0
          and errs == ["[]"], (r.stderr[-400:], r.stdout[-400:]))

print(f"\n{len(OK)} ✔ · {len(BAD)} ✘")
os._exit(1 if BAD else 0)
