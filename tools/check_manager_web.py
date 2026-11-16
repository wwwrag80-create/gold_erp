"""5.6.0: رابط المدير — الهيكل الجديد والتسجيل منه.

    python3 tools/check_manager_web.py

يمرّ على `models_web.handle` مباشرةً (بلا متصفح): الرئيسية واللوحات،
والصناديق، وحركة المصنع، وكشف الحساب، والمستند وصوره — ثم تسجيل العمليات
الستّ من الرابط وحمايته: رمز الدخول، والإيقاف من البرنامج، ورمز التحقق
(CSRF)، والترحيل مرةً واحدة لكل nonce. وفي آخره: الدفتر متوازن والخزنة =
أطقمها.
"""
import datetime
import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
T = tempfile.mkdtemp(prefix="mweb_")
os.environ["GOLD_ERP_DATA_DIR"] = T
os.environ["JADEITE_STOCK_GUARD"] = "on"
import config  # noqa: E402

config.DB_PATH = pathlib.Path(T) / "t.db"
import main  # noqa: E402

for _l, f in main.prepare_steps():
    f()
from database.database import db  # noqa: E402
from models import inventory, invoices, stock_guard, vouchers  # noqa: E402
from models.entities import add_entity  # noqa: E402
from services import manager_web as mweb  # noqa: E402
from services import models_web as mw  # noqa: E402

OK, BAD = [], []


def check(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print(("  ✔ " if cond else "  ✘ ") + name + ("" if cond else f"  [{info}]"))


D0 = datetime.date.today().isoformat()
D1 = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
with db() as c:
    A = add_entity(c, "محل الياسمين", "customer", username="t")
    B = add_entity(c, "محل النخبة", "customer", username="t")
    inventory.create_work_orders_batch(c, [
        {"wo_no": f"{700 + i}", "model_no": ("K1", "K2")[i % 2],
         "gold": 9 + i, "small_stones": .2, "big_stones": .3,
         "wage_per_gram": 12} for i in range(8)], D1, "t")
    W = {r[1]: r[0] for r in c.execute(
        "SELECT id, work_order_no FROM work_orders")}
    invoices.create_sale(c, A, [{"work_order_id": W["700"]}], D0, "t",
                         apply_vat=False)
    vouchers.create_voucher(c, "receipt", D0, "t", entity_id=A,
                            rows=[{"kind": "cash", "amount": 100}])
    TOK = mw.ensure_token(c)
    mw.set_enabled(c, True)
    SECRET = mw._get(c, mw.K_SECRET)


OPS_CK = {"on": True}       # ملف تعريف لوحة التسجيل (إن كان لها رمز)


def call(method, path, query=None, body=None, cookie=True):
    with db(readonly=True) as c:
        pin = mw._get(c, mw.K_PIN).strip()
        opin = mw._get(c, mweb.K_OPS_PIN).strip()
    headers = {}
    cks = []
    if cookie and pin:
        cks.append(f"{mw.COOKIE}={mw._cookie_value(TOK, SECRET, pin)}")
    if cookie and opin and OPS_CK["on"]:
        cks.append(f"{mweb.OPS_COOKIE}="
                   f"{mweb._ops_cookie_value(mw._csrf(TOK, SECRET), opin)}")
    if cks:
        headers["Cookie"] = "; ".join(cks)
    parts = [TOK] + [p for p in path.split("/") if p]
    raw = (json.dumps(body, ensure_ascii=False).encode("utf-8")
           if body is not None else None)
    r = mw.handle(method, parts, query or {}, headers, raw)
    b = r["body"]
    return r["code"], (b.decode("utf-8", "replace")
                       if isinstance(b, bytes) else b)


def post(kind, data):
    data = dict(data, csrf=mw._csrf(TOK, SECRET))
    _c, b = call("POST", f"api/post/{kind}", body=data)
    return json.loads(b)


print("── 1) الرئيسية واللوحات")
code, h = call("GET", "")
check("الرابط يفتح الرئيسية بلوحاتها", code == 200 and "الرئيسية" in h
      and h.count('class="tile') >= 9, code)
check("«دليل الموديلات» أول لوحة، و«حركة الطقم» في «المزيد»",
      h.index("<b>دليل الموديلات</b>") < h.index("<b>الصناديق</b>")
      < h.index("<b>فواتير / حركة المصنع</b>") < h.index("المزيد</div>")
      < h.index("<b>حركة الطقم</b>") < h.index("<b>الوارد بتاريخ</b>"))
check("الرئيسية بلا بطاقات الأرقام (الذهب المشغول · المتاح للبيع · الصندوق"
      " النقدي · عمليات اليوم)", 'class="kpi' not in h
      and "الذهب المشغول" not in h and "المتاح للبيع" not in h
      and "الصندوق النقدي" not in h and "عمليات اليوم" not in h)
check("«حركة اليوم» و«طلبات العملاء» حُذفتا من الرئيسية وشريط التنقل",
      "حركة اليوم" not in h and "طلبات العملاء" not in h
      and "tab=day" not in h and "tab=orders" not in h)
_c1, h1 = call("GET", "", {"tab": "day"})
_c2, h2 = call("GET", "", {"tab": "orders"})
_c3, _h3 = call("GET", "order/new")
check("روابطهما المحفوظة تفتح الرئيسية، ومسار الطلبات مغلق",
      "<b>دليل الموديلات</b>" in h1 and "<b>دليل الموديلات</b>" in h2
      and _c3 == 404, (_c1, _c2, _c3))
code, h = call("GET", "", {"tab": "guide"})
check("الدليل بشريط التنقل الموحّد", code == 200 and 'class="mnav"' in h
      and "دليل الموديلات" in h)
code, h = call("GET", "", {"view": "in_stock"})
check("رابط الدليل المحفوظ قديماً (بعرضٍ دون تبويب) يبقى دليلاً",
      "دليل الموديلات" in h, h[:200])

print("── 2) الصناديق")
code, h = call("GET", "boxes")
check("الصناديق مزروعة من لوحات لوحة التحكم", code == 200
      and h.count("data-box=") >= 1)
r = json.loads(call("POST", "boxes", body={
    "csrf": mw._csrf(TOK, SECRET), "act": "add_box",
    "name": "صناديق الذهب"})[1])
with db(readonly=True) as c:
    bid = next(b["id"] for b in mweb.load_boxes(c)
               if b["name"] == "صناديق الذهب")
r2 = json.loads(call("POST", "boxes", body={
    "csrf": mw._csrf(TOK, SECRET), "act": "add_acc", "id": bid,
    "code": "1400"})[1])
r3 = json.loads(call("POST", "boxes", body={
    "csrf": mw._csrf(TOK, SECRET), "act": "add_acc", "id": bid,
    "code": "9999999"})[1])
code, h0 = call("GET", "boxes")
code, h = call("GET", "boxes", {"b": bid})
check("قسمٌ جديد وحسابٌ فيه برصيده", r["ok"] and r2["ok"]
      and r.get("id") == bid and "صناديق الذهب" in h
      and "الصندوق الرئيسي" in h, (r, r2))
# 5.6.1: كـ«حركة المصنع» — لوحات الأقسام في الأعلى، والمختار جدوله تحته
check("الأقسام لوحاتٌ في الأعلى، والمختار يُظهر جدول حساباته تحته",
      'class="btiles"' in h and h.count('class="tile') >= 2
      and 'class="tile main"' in h and f'data-box="{bid}"' in h
      and 'class="tbl bx"' in h and "/stmt?code=1400" in h
      and "الإجمالي" in h and f'data-box="{bid}"' not in h0, h[-500:])
check("حسابٌ غير موجود يُرفض", r3["ok"] is False)
# 5.6.5: «صندوق الكسر» قسمٌ في الصناديق — عيار 18 أولاً برصيده وكشفه
CS = mw._csrf(TOK, SECRET)
code, h = call("GET", "boxes", {"b": "scrap"})
check("صندوق الكسر قسمٌ بأعيرته: 18 أولاً ثم البقية وكشف 18 تحته",
      code == 200 and "<b>صندوق الكسر</b>" in h
      and h.index("<b>عيار 18</b>") < h.index("<b>عيار 21</b>")
      < h.index("<b>عيار 22</b>") < h.index("<b>عيار 24</b>")
      and "كشف صندوق الكسر — عيار 18" in h and "/stmt?code=1310" in h
      and 'class="accin"' not in h, h[-400:])
code, h = call("GET", "boxes", {"b": "scrap", "k": "21", "per": "all"})
check("«كشف» أمام عيارٍ آخر يُظهر كشفه هو",
      "كشف صندوق الكسر — عيار 21" in h and 'name="k" value="21"' in h)
code, h = call("GET", "boxes", {"b": "scrap", "k": "99"})
check("عيارٌ غير معروف في الرابط يعود إلى 18 بأمان",
      "كشف صندوق الكسر — عيار 18" in h)
rs = json.loads(call("POST", "boxes", body={
    "csrf": CS, "act": "add_acc", "id": "scrap", "code": "1400"})[1])
check("لا تُضاف حساباتٌ إلى صندوق الكسر", rs["ok"] is False, rs)
rd = json.loads(call("POST", "boxes", body={
    "csrf": CS, "act": "del_box", "id": "scrap"})[1])
with db(readonly=True) as c:
    gone = not any(b["id"] == "scrap" for b in mweb.load_boxes(c))
ra = json.loads(call("POST", "boxes", body={
    "csrf": CS, "act": "add_box", "name": "صندوق الكسر"})[1])
with db(readonly=True) as c:
    back = [b for b in mweb.load_boxes(c) if b["id"] == "scrap"]
check("حذفه يبقى محذوفاً، وإضافة قسمٍ باسمه تعيده بأعيرته",
      rd["ok"] and gone and ra.get("id") == "scrap" and len(back) == 1
      and back[0].get("kind") == "scrap", (rd, ra, back))
bad = json.loads(call("POST", "boxes", body={"csrf": "x", "act": "add_box",
                                             "name": "z"})[1])
check("رمز تحقّق خاطئ يُرفض", bad["ok"] is False)
with db(readonly=True) as c:
    s = mweb.search_accounts(c, "صند")
    p = mweb.search_parties(c, "محل ال")
check("الاقتراح من أول الحروف: حسابات وجهات",
      s and any(x["code"] == "1400" for x in s) and len(p) == 2,
      (s[:2], p))

print("── 3) حركة المصنع وكشف الحساب والمستند")
code, h = call("GET", "moves", {"g": "sale", "per": "month"})
check("سجل المبيعات بالطرف والوزن والصور والفاتورة",
      code == 200 and "محل الياسمين" in h and "/doc/invoice_models/" in h
      and "/doc/invoices/" in h)
code, h = call("GET", "moves", {"g": "supply", "from": D1, "to": D1})
check("الوارد بتاريخٍ مختار بصور دفعته", "/doc/supply_models/" in h, h[-300:])
with db(readonly=True) as c:
    acc = c.execute("SELECT account_id FROM entities WHERE id=?",
                    (A,)).fetchone()[0]
code, h = call("GET", "stmt", {"acc": str(acc), "per": "all"})
check("كشف الحساب بأزرار الصور والفاتورة", code == 200
      and "/doc/invoice_models/" in h and "رصيد الذهب" in h)
inv_id = invoices_id = None
with db(readonly=True) as c:
    inv_id = c.execute("SELECT id FROM invoices LIMIT 1").fetchone()[0]
code, h = call("GET", f"doc/invoice_models/{inv_id}")
check("صفحة صور الفاتورة بقالب المجمّعة", code == 200 and "gwos" in h)
code, _h = call("GET", "doc/../../etc")
check("مستندٌ بنوعٍ غير مسموح يُرفض", code == 404)

print("── 3ب) حركة الطقم")
code, h = call("GET", "sets")
check("صفحة حركة الطقم بالبحث", code == 200 and 'name="q"' in h
      and 'name="by"' in h and 'class="mnav"' in h)
code, h = call("GET", "sets", {"by": "no", "q": "700"})
check("برقم التشغيل: تفصيل الوزن والدفعة ومكانه وحركاته",
      code == 200 and "الطقم 700" in h and "الفصوص" in h
      and "الأحجار" in h and "دفعة التوريد" in h and "سجل حركة الطقم" in h
      and "عند محل الياسمين" in h and "/doc/invoices/" in h
      and "/doc/supply_models/" in h, h[-600:])
code, h = call("GET", "sets", {"by": "reg", "q": "10"})
check("بالوزن: الأطقم الأقرب أولاً وكلٌّ يفتح حركته",
      code == 200 and "أقرب" in h and "by=no&amp;q=" in h, h[-400:])
code, h = call("GET", "sets", {"by": "no", "q": "zz9"})
code2, h2 = call("GET", "sets", {"by": "standing", "q": "abc"})
code3, h3 = call("GET", "sets", {"by": "no", "q": "<script>x</script>"})
check("رقمٌ غير موجود أو وزنٌ غير رقمي: رسالةٌ واضحة بلا خطأ",
      code == 200 and "لا يوجد طقم" in h and "اكتب الوزن رقماً" in h2
      and "<script>x" not in h3 and code3 == 200)

print("── 4) الحماية قبل التسجيل")
# 5.6.1: خيارٌ واحد — يُسمح أو لا يُسمح — بلا اشتراط رمز دخول
code, h = call("GET", "ops")
check("بلا رمز دخول ومسموح: لوحات العمليات الست",
      h.count('class="tile main"') == 6, h[-300:])
with db() as c:
    mweb.set_ops_enabled(c, False)
code, h = call("GET", "ops")
r = post("receipt", {"nonce": "n-nopin-01", "party": A, "box": "1400",
                     "date": D0, "rows": [{"kind": "cash", "amount": 5}]})
check("بلا رمز دخول وغير مسموح: الصفحة والترحيل مقفلان",
      "موقوف" in h and 'class="tile' not in h and r["ok"] is False, r)
with db() as c:
    mweb.set_ops_enabled(c, True)
    mw.set_pin(c, "1234")
code, h = call("GET", "ops", cookie=False)
check("برمز الدخول: لا دخول بلا ملف التعريف", "name=\"pin\"" in h
      or "name='pin'" in h or 'name="pin"' in h)
with db() as c:
    mweb.set_ops_enabled(c, False)
code, h = call("GET", "ops")
r = post("receipt", {"nonce": "n-off-0001", "party": A, "box": "1400",
                     "date": D0, "rows": [{"kind": "cash", "amount": 5}]})
check("موقوفٌ من البرنامج: الصفحة والترحيل", "موقوف" in h
      and r["ok"] is False, r)
with db() as c:
    mweb.set_ops_enabled(c, True)
code, h = call("GET", "ops")
check("مفعّل: لوحات العمليات الست", h.count('class="tile main"') == 6)

print("── 5) تسجيل العمليات")
with db(readonly=True) as c:
    info = mweb.wo_info(c, "702", "sale", D0)
check("بيانات رقم التشغيل للبيع: الموديل والباقي", info["ok"]
      and info["model"] == "K1" and info["avail"] > 0, info)
r = post("sale", {"nonce": "n-sale-0001", "party": B, "src": None,
                  "date": D0, "vat": False, "lines": []})
check("الحساب إلزامي", r["ok"] is False, r)
with db(readonly=True) as c:
    src = c.execute("SELECT id FROM accounts WHERE code='1200'").fetchone()[0]
sale = post("sale", {"nonce": "n-sale-0002", "party": B, "src": src,
                     "date": D0, "vat": True, "notes": "من الرابط",
                     "lines": [{"no": "702", "weight": info["avail"],
                                "karat": info["karat"], "wage": 15},
                               {"wage_only": True, "amount": 30,
                                "note": "تلميع"}]})
check("فاتورة بيع من الرابط", sale["ok"] and sale["no"].startswith("S-"),
      sale)
again = post("sale", {"nonce": "n-sale-0002", "party": B, "src": src,
                      "date": D0, "lines": [{"no": "703", "weight": 1,
                                             "karat": 18, "wage": 1}]})
with db(readonly=True) as c:
    n_sales = c.execute("SELECT COUNT(*) FROM invoices WHERE kind='sale'"
                        " AND is_deleted=0").fetchone()[0]
    st = c.execute("SELECT status FROM work_orders WHERE work_order_no="
                   "'702'").fetchone()[0]
    inv = c.execute("SELECT * FROM invoices WHERE invoice_no=?",
                    (sale["no"],)).fetchone()
check("الطلب نفسه مرتين: ترحيلٌ واحد", again.get("again")
      and again["no"] == sale["no"] and n_sales == 2, (again, n_sales))
check("الطقم خرج · الأجر 15 · والضريبة على الأجور · بيد «رابط المدير»",
      st == "sold" and inv["vat_applied"] and inv["created_by"] == mweb.WEB_USER
      and abs(inv["total_wages"] - round(info["avail"] * 15 + 30, 2)) < 0.02,
      dict(inv))
ret = post("sale_return", {"nonce": "n-ret-00001", "party": B, "src": src,
                           "date": D0, "lines": [{"no": "702", "weight":
                                                  info["avail"], "karat":
                                                  info["karat"], "wage": 15}]})
check("مرتجع من الرابط", ret["ok"] and ret["no"].startswith("R-"), ret)
rc = post("receipt", {"nonce": "n-rc-000001", "party": A, "box": "1500",
                      "date": D0, "notes": "دفعة", "rows": [
                          {"kind": "gold", "weight": 6, "karat": 21},
                          {"kind": "cash", "amount": 250}]})
pm = post("payment", {"nonce": "n-pm-000001", "account": src, "box": "1400",
                      "date": D0, "rows": [{"kind": "cash", "amount": 1}]})
check("سند قبض ذهب ونقد للبنك", rc["ok"], rc)
check("الصرف لحسابٍ تجميعي/غير قابل للترحيل يمرّ بتحقق الدليل",
      pm["ok"] or "الحساب" in pm.get("error", ""), pm)
with db(readonly=True) as c:
    a1 = c.execute("SELECT id FROM accounts WHERE code='1400'").fetchone()[0]
    a2 = c.execute("SELECT id FROM accounts WHERE code='4200'").fetchone()[0]
jv = post("journal", {"nonce": "n-jv-000001", "date": D0, "notes": "تسوية",
                      "lines": [{"account": a1, "cd": 20},
                                {"account": a2, "cc": 20}]})
jbad = post("journal", {"nonce": "n-jv-000002", "date": D0, "notes": "x",
                        "lines": [{"account": a1, "cd": 20},
                                  {"account": a2, "cc": 19}]})
check("قيد يومي متوازن يُرحَّل وغير المتوازن يُرفض", jv["ok"]
      and jbad["ok"] is False, (jv, jbad))
sp = post("supply", {"nonce": "n-sp-000001", "src": src, "date": D0,
                     "notes": "دفعة الورشة", "lines": [
                         {"no": "950", "model": "K9", "gold": 7, "small": 0.4,
                          "big": 0.6, "karat": 21},
                         {"no": "951", "model": "K9", "gold": 5, "karat": 18}]})
dup = post("supply", {"nonce": "n-sp-000002", "src": src, "date": D0,
                      "lines": [{"no": "950", "gold": 1, "karat": 18}]})
check("دفعة توريد (عيار 21 يُخزَّن بمكافئ 18) · والرقم المكرّر يُرفض",
      sp["ok"] and dup["ok"] is False, (sp, dup))
with db(readonly=True) as c:
    g = c.execute("SELECT gold_weight FROM work_orders WHERE"
                  " work_order_no='950'").fetchone()[0]
check("ذهب 7 جم عيار 21 = 8.167 بمكافئ 18", abs(g - 7 * 21 / 18) < 0.002, g)
fut = post("receipt", {"nonce": "n-fut-00001", "party": A, "box": "1400",
                       "date": "2099-01-01",
                       "rows": [{"kind": "cash", "amount": 5}]})
check("تاريخٌ بعد اليوم مرفوض", fut["ok"] is False)
code, h = call("GET", "ops")
check("«آخر ما سُجِّل من الرابط» في صفحة العمليات",
      "آخر ما سُجِّل من الرابط" in h and sale["no"] in h)

print("── 7) التعديل والحذف والدمج من الرابط (5.7.0)")
CS = mw._csrf(TOK, SECRET)


def api(path, data):
    _c, b = call("POST", path, body=dict(data, csrf=CS))
    return json.loads(b)


with db() as c:
    s_a = invoices.create_sale(c, A, [{"work_order_id": W["704"]}], D0,
                               "t", apply_vat=False)
    s_b = invoices.create_sale(c, A, [{"work_order_id": W["705"]}], D0,
                               "t", apply_vat=False)
    e_a = c.execute("SELECT entry_id FROM invoices WHERE id=?",
                    (s_a["id"],)).fetchone()[0]
    e_b = c.execute("SELECT entry_id FROM invoices WHERE id=?",
                    (s_b["id"],)).fetchone()[0]
    a_code = c.execute("SELECT a.code FROM entities n JOIN accounts a ON"
                       " a.id=n.account_id WHERE n.id=?", (A,)).fetchone()[0]
code, h = call("GET", "stmt", {"code": a_code, "per": "all"})
check("الكشف: أزرار تعديل وحذف لكل مستند، واختيار فواتير البيع للدمج",
      f'data-delx="{e_a}"' in h and f"/ops/sale?edit={e_a}" in h
      and 'class="mg"' in h and 'id="mgbtn"' in h)
code, h = call("GET", "moves", {"g": "sale", "per": "all"})
check("وحركة المصنع كذلك", f'data-delx="{e_a}"' in h
      and f"/ops/sale?edit={e_a}" in h)
code, h = call("GET", "ops/sale", {"edit": str(e_a)})
check("نموذج التعديل مملوءٌ بالفاتورة ورقمها", code == 200
      and f"تعديل فاتورة المبيعات {s_a['invoice_no']}" in h
      and '"edit"' in h and '"no": "704"' in h)
with db(readonly=True) as c:
    pay = mweb.edit_payload(c, "sale", e_a)
ln = dict(pay["lines"][0], wage=20)
ed = api(f"api/edit/sale/{e_a}", {
    "nonce": "n-edit-0001", "party": A, "src": pay["src"],
    "date": pay["date"], "vat": False, "notes": "معدّلة",
    "lines": [ln]})
with db(readonly=True) as c:
    iv = c.execute("SELECT invoice_no, total_wages, is_deleted, description"
                   " FROM invoices WHERE id=?", (s_a["id"],)).fetchone()
    it = c.execute("SELECT registered_weight FROM invoice_items WHERE"
                   " invoice_id=?", (s_a["id"],)).fetchone()[0]
    w0 = c.execute("SELECT registered_weight FROM work_orders WHERE id=?",
                   (W["704"],)).fetchone()[0]
check("تعديل الفاتورة في مكانها برقمها: الأجر الجديد والوزن كما هو بلا تقريب",
      ed["ok"] and iv["invoice_no"] == s_a["invoice_no"]
      and iv["is_deleted"] == 0 and iv["description"] == "معدّلة"
      and abs(iv["total_wages"] - round(pay["lines"][0]["weight"] * 20, 2))
      < 0.02 and abs(it - w0) < 1e-9, (ed, dict(iv), it, w0))
# القيد اليومي: التعديل برقمه
j0 = post("journal", {"nonce": "n-jv-ed-001", "date": D0, "notes": "قيد",
                      "lines": [{"account": a1, "cd": 11},
                                {"account": a2, "cc": 11}]})
with db(readonly=True) as c:
    jp = mweb.edit_payload(c, "journal", j0["id"])
jl = [dict(jp["lines"][0], cd=13), dict(jp["lines"][1], cc=13)]
je = api(f"api/edit/journal/{j0['id']}", {"nonce": "n-jv-ed-002",
         "date": D0, "notes": "قيد معدّل", "lines": jl})
check("تعديل القيد اليومي برقمه نفسه", je["ok"] and je["no"] == j0["no"]
      and je["id"] != j0["id"], (j0, je))
# سند قبض: التعديل في مكانه
r0 = post("receipt", {"nonce": "n-rc-ed-001", "party": A, "box": "1400",
                      "date": D0, "rows": [{"kind": "cash", "amount": 40}]})
with db(readonly=True) as c:
    re_ = c.execute("SELECT entry_id FROM vouchers WHERE id=?",
                    (r0["id"],)).fetchone()[0]
    vp = mweb.edit_payload(c, "receipt", re_)
ve = api(f"api/edit/receipt/{re_}", {"nonce": "n-rc-ed-002",
         "party": A, "box": "1400", "date": D0,
         "rows": [dict(vp["rows"][0], amount=45)]})
with db(readonly=True) as c:
    vamt = c.execute("SELECT cash_amount, voucher_no FROM vouchers WHERE"
                     " id=?", (r0["id"],)).fetchone()
check("تعديل سند القبض في مكانه برقمه", ve["ok"] and vamt["voucher_no"]
      == r0["no"] and abs(vamt["cash_amount"] - 45) < 0.01, (ve, dict(vamt)))
# الحذف: الرقم يتحرّر للمستند التالي
dl = api("api/delete", {"nonce": "n-del-0001", "eid": e_b})
with db(readonly=True) as c:
    st_b = c.execute("SELECT status FROM work_orders WHERE id=?",
                     (W["705"],)).fetchone()[0]
with db(readonly=True) as c:
    i706 = mweb.wo_info(c, "706", "sale", D0)
nx = post("sale", {"nonce": "n-sale-after-del", "party": B, "src": src,
                   "date": D0, "vat": False, "lines": [{
                       "no": "706", "weight": i706["avail"],
                       "karat": i706["karat"], "wage": 1}]})
check("حذف فاتورةٍ من الرابط: يعود طقمها، وأول فاتورةٍ بعدها تأخذ رقمها",
      dl["ok"] and st_b == "in_stock" and nx["ok"]
      and nx["no"] == s_b["invoice_no"], (dl, st_b, nx))
dd = api("api/delete", {"nonce": "n-del-0001", "eid": e_b})
check("وإعادة الطلب نفسه لا تحذف ثانيةً", dd.get("again") and dd["ok"], dd)
# الفاتورة الضريبية: لا حذف — عكسٌ بمرتجع
with db(readonly=True) as c:
    e_vat = c.execute("SELECT entry_id FROM invoices WHERE invoice_no=?",
                      (sale["no"],)).fetchone()[0]
code, h = call("GET", "stmt", {"code": a_code, "per": "all"})
dv = api("api/delete", {"nonce": "n-del-vat-1", "eid": e_vat})
check("الفاتورة الضريبية لا تُحذف من الرابط", dv["ok"] is False
      and "ضريبية" in dv["error"], dv)
# الدمج
with db() as c:
    m1 = invoices.create_sale(c, A, [{"work_order_id": W["707"]}], D0,
                              "t", apply_vat=False)
    m2 = invoices.create_sale(c, A, [{"work_order_id": W["701"]}], D0,
                              "t", apply_vat=False) \
        if c.execute("SELECT status FROM work_orders WHERE id=?",
                     (W["701"],)).fetchone()[0] == "in_stock" else None
if m2 is None:
    with db() as c:
        inventory.create_work_orders_batch(c, [{"wo_no": "790", "gold": 5,
            "small_stones": 0, "big_stones": 0, "wage_per_gram": 5}], D1, "t")
        w790 = c.execute("SELECT id FROM work_orders WHERE work_order_no="
                         "'790'").fetchone()[0]
        m2 = invoices.create_sale(c, A, [{"work_order_id": w790}], D0, "t",
                                  apply_vat=False)
mg = api("api/merge", {"nonce": "n-merge-001", "ids": [m1["id"], m2["id"]]})
with db(readonly=True) as c:
    gone = c.execute("SELECT is_deleted FROM invoices WHERE id=?",
                     (m2["id"],)).fetchone()[0]
    n_items = c.execute("SELECT COUNT(*) FROM invoice_items WHERE"
                        " invoice_id=?", (m1["id"],)).fetchone()[0]
check("الدمج من الرابط: الأقدم تحمل البندين، والأخرى أُلغيت",
      mg["ok"] and gone == 1 and n_items == 2, mg)
# رمز لوحة التسجيل
with db() as c:
    mweb.set_ops_pin(c, "4321")
OPS_CK["on"] = False
code, h = call("GET", "ops")
lk = api("api/delete", {"nonce": "n-del-lock-1", "eid": e_a})
code2, h2 = call("GET", "ops/sale", {"edit": str(e_a)})
check("برمز اللوحة: الصفحة تطلبه، والحذف والتعديل مقفلان بلا رمزها",
      'name="pin"' in h and "لوحة تسجيل العمليات" in h
      and lk.get("locked") and lk["ok"] is False and 'name="pin"' in h2
      and "next" in h2, lk)
with db(readonly=True) as c:
    _lp = mw._get(c, mw.K_PIN).strip()
LH = {"Cookie": f"{mw.COOKIE}={mw._cookie_value(TOK, SECRET, _lp)}"} \
    if _lp else {}
r_bad = mw.handle("POST", [TOK, "ops", "unlock"], {}, LH,
                  json.dumps({"csrf": CS, "pin": "0000"}).encode())
r_ok = mw.handle("POST", [TOK, "ops", "unlock"], {}, LH,
                 json.dumps({"csrf": CS, "pin": "4321",
                             "next": f"/m/{TOK}/ops/sale"}).encode())
ck = r_ok["headers"].get("Set-Cookie", "")
check("رمزٌ خاطئ يُرفض، والصحيح يفتح اللوحة 12 ساعة ويعود إلى الصفحة",
      r_bad["code"] == 401 and r_ok["code"] == 303 and mweb.OPS_COOKIE in ck
      and "Max-Age=43200" in ck and r_ok["headers"]["Location"].endswith(
          "/ops/sale"), (r_bad["code"], r_ok["code"], ck))
r_evil = mw.handle("POST", [TOK, "ops", "unlock"], {}, LH,
                   json.dumps({"csrf": CS, "pin": "4321",
                               "next": "https://evil.example/x"}).encode())
check("ولا يُعاد التوجيه إلى موقعٍ آخر", r_evil["headers"]["Location"]
      .endswith(f"/m/{TOK}/ops"), r_evil["headers"])
OPS_CK["on"] = True
code, h = call("GET", "ops")
check("ومع ملف تعريف اللوحة: تفتح بزر «قفل اللوحة»",
      h.count('class="tile main"') == 6 and "قفل اللوحة" in h)
with db() as c:
    mweb.set_ops_pin(c, "")
    mweb.set_ops_enabled(c, False)
code, h = call("GET", "stmt", {"code": a_code, "per": "all"})
check("التسجيل موقوف ⇒ لا أزرار تعديل ولا حذف في الكشف",
      'data-delx="' not in h and "/ops/sale?edit=" not in h)
with db() as c:
    mweb.set_ops_enabled(c, True)

print("── 8) الكشوف من آخر الحركات (5.7.3)")
import re as _re  # noqa: E402
with db() as c:
    s_old = invoices.create_sale(c, B, [{"work_order_id": W["703"]}], D1,
                                 "t", apply_vat=False) \
        if c.execute("SELECT status FROM work_orders WHERE id=?",
                     (W["703"],)).fetchone()[0] == "in_stock" else None
    b_code = c.execute("SELECT a.code FROM entities n JOIN accounts a ON"
                       " a.id=n.account_id WHERE n.id=?", (B,)).fetchone()[0]
code, h = call("GET", "stmt", {"code": b_code})
dates = _re.findall(r'<tr data-s="[^"]*"><td class="n">(?:<input[^>]*>)?'
                    r'(\d{4}-\d{2}-\d{2})', h)
check("كشف الحساب يُفتح على كل الحركة والأحدث أعلاه",
      "الأحدث أولاً" in h and 'class="chip on"' in h
      and h.index('class="chip on"') > h.index("هذه السنة")
      and dates and dates == sorted(dates, reverse=True), dates[:6])
with db(readonly=True) as c:
    bid2 = next(b["id"] for b in mweb.load_boxes(c) if b["codes"])
code, h = call("GET", "boxes", {"b": bid2})
check("القسم بلا لوحة «آخر الحركات» (5.7.4 — أُلغيت لأنها تأخذ مساحة)",
      code == 200 and "آخر الحركات" not in h and 'data-box="' in h)
code, h = call("GET", "moves", {"g": "supply"})
check("«فواتير / حركة المصنع» اسم الصفحة، والوارد طرفُه «خزينة التصنيع»",
      "فواتير / حركة المصنع" in h and "<b>خزينة التصنيع</b>" in h
      and "<b>الذهب المشغول</b>" not in h)
code, h = call("GET", "sets", {"by": "no", "q": "702"})
i_sup, i_sale = h.find(">توريد<"), h.find(">مبيعات<")
check("سجل حركة الطقم: الأحدث أولاً (التوريد في آخره)",
      i_sup > 0 and i_sale > 0 and i_sale < i_sup, (i_sup, i_sale))
code, h = call("GET", "boxes", {"b": "scrap"})
check("كشف صندوق الكسر على كل الحركة والأحدث أولاً",
      "كشف صندوق الكسر — عيار 18" in h and "الأحدث أولاً" in h)

print("── 9) تحليل مبيعات العملاء · الأجر في السطر · تظليل الرصيد (5.7.5)")
from models import sales_analytics as _sa  # noqa: E402
from services import gold_math as _gm  # noqa: E402
code, h = call("GET", "")
_more = h[h.index("المزيد</div>"):]
check("«تحليل مبيعات العملاء» في «المزيد» بعد «العملاء» مباشرة",
      _more.index("<b>العملاء — المبيعات والسداد</b>")
      < _more.index("<b>تحليل مبيعات العملاء</b>")
      < _more.index("<b>الأرباح والخسائر</b>")
      if "<b>تحليل مبيعات العملاء</b>" in _more else False)
with db() as c:
    _int = add_entity(c, "محل داخلي للتحليل", "customer", username="t")
    c.execute("UPDATE entities SET is_internal=1 WHERE id=?", (_int,))
code, j = call("GET", "api/cust", {"q": "محل"})
_ids = [x["id"] for x in json.loads(j)]
check("اقتراح العملاء كقائمة البرنامج: العملاء الخارجيون وحدهم",
      A in _ids and B in _ids and _int not in _ids, _ids)
code, h = call("GET", "analytics")
check("الصفحة بلا عميل تطلب اختياره", code == 200 and 'id="ancust"' in h
      and 'class="ancol"' not in h)
_d1, _d2 = "2000-01-01", datetime.date.today().isoformat()
code, h = call("GET", "analytics", {"c": A, "from": _d1, "to": _d2,
                                    "k": "21", "mf": "1"})
with db(readonly=True) as c:
    _p = _sa.all_panels(c, A, _d1, _d2)
    _ret = _sa.panel_details(c, "sales", A, _d1, _d2)


def _g21(v):
    return mweb._m(_gm.from_base_karat(float(v or 0), 21))


check("اللوحات الأربع بأرقام البرنامج نفسها (بعيار 21)",
      code == 200 and h.count('class="ancol"') == 4
      and f"{_g21(_p['sales']['weight'])} جم 21" in h
      and f"{_g21(_p['returns']['weight'])} جم 21" in h
      and f"{_g21(_p['net_sold']['weight'])} جم 21" in h
      and f"ذهب {_g21(_p['collection']['gold'])} · نقد "
          f"{mweb._m(_p['collection']['cash'])}" in h)
check("جدول المبيعات بأرقام تشغيله", bool(_ret) and all(
    f"<td>{r['wo']}</td>" in h for r in _ret), [r["wo"] for r in _ret])
check("الرصيد المتبقي على العميل أسفل اللوحات",
      "الرصيد المتبقي على العميل" in h and "عيار 21" in h)
code, h = call("GET", "analytics", {"c": A, "from": _d1, "to": _d2,
                                    "mode": "report", "mf": "1"})
check("«تقرير»: المصروف والمرتجع والصافي بلا جداول ولا تحصيل",
      h.count('class="ancol"') == 3 and "المصروف (المبيعات)" in h
      and "المباع الصافي" in h and "antog" not in h.split("<script>")[0]
      .split("</style>")[-1] and 'data-k="collection"' not in h)
code, h = call("GET", "analytics", {"c": A, "from": _d1, "to": _d2,
                                    "mf": "1", "m_sales": "1"})
check("«فرز»: أرقام التشغيل بلا تكرار في اللوحة المختارة",
      "رقم التشغيل (بلا تكرار)" in h and 'name="m_sales" value="1" checked'
      in h)
code, h = call("GET", f"doc/customer_analytics/{A}",
               {"from": _d1, "to": _d2, "k": "18", "mode": "detail",
                "vis": "sales,returns,net_sold,collection", "exp": "sales"})
check("طباعة تقرير العميل بقالب البرنامج", code == 200
      and "تقرير المبيعات" in h)
code, h = call("GET", "stmt", {"code": "1601"})
check("كشف الحساب: عمودا رصيد الذهب والنقد مظلّلان",
      h.count('<th class="n bal">') == 2 and 'class="n bal"' in h)
with db() as c:      # حركةٌ في صندوق كسر 18 ليظهر كشفه بجدوله
    vouchers.create_voucher(c, "receipt", D1, "t", entity_id=A, rows=[
        {"kind": "gold", "weight": 2, "karat": 18}])
code, h = call("GET", "boxes", {"b": "scrap", "k": "18"})
check("كشف صندوق الكسر: عمودا الرصيد مظلّلان",
      h.count('<th class="n bal">') == 2)
code, h = call("GET", "ops/sale")
check("لوحة البيع: أجر السطر المضاف خانةٌ تُعدَّل",
      "input.lwg" in h and "class=\"lwg num\"" in h.replace("\\'", "'")
      or "lwg num" in h)

print("── 10) قفل التعديل والحذف من أعلى الرابط برمز البرنامج (5.7.6)")
code, h = call("GET", "")
check("بلا رمز: الزر ظاهر في الأعلى ويطلب ضبط الرمز من البرنامج",
      'id="elockb"' in h and 'data-pin="0"' in h and "🔓 قفل التعديل والحذف"
      in h)
r = api("api/editlock", {"pin": "1234", "lock": True})
check("بلا رمز: القفل يُرفض بسببٍ مفهوم", not r["ok"]
      and "اضبطه من البرنامج" in r["error"], r)
with db() as c:
    mweb.set_edit_pin(c, "2468", "t")
    try:
        mweb.set_edit_pin(c, "12", "t")
        _short = False
    except ValueError:
        _short = True
check("رمز القفل من 4 إلى 12 خانة", _short)
r = api("api/editlock", {"pin": "9999", "lock": True})
check("رمزٌ خاطئ لا يقفل", not r["ok"] and r["error"] == "الرمز غير صحيح", r)
r = api("api/editlock", {"pin": "2468", "lock": True})
with db(readonly=True) as c:
    _lk = mweb.edits_locked(c)
check("الرمز الصحيح يقفل التعديل والحذف", r["ok"] and r["locked"] and _lk, r)
with db(readonly=True) as c:
    _ent = c.execute("SELECT i.entry_id FROM invoices i WHERE i.is_deleted=0"
                     " AND i.kind='sale' AND COALESCE(i.vat_applied,0)=0"
                     " AND i.customer_id=? ORDER BY i.id DESC LIMIT 1",
                     (A,)).fetchone()[0]
code, h = call("GET", "stmt", {"code": a_code, "per": "all"})
check("مقفل: الكشف بلا أزرار تعديل وحذف ودمج، والزر «🔒» في الأعلى",
      'data-delx="' not in h and "?edit=" not in h and 'class="mg"' not in h
      and "🔒 التعديل والحذف مقفل" in h and 'class="mw elock"' in h)
code, h = call("GET", "moves", {"g": "all", "per": "all"})
check("مقفل: حركة المصنع بلا أزرار تعديل وحذف", 'data-delx="' not in h
      and "?edit=" not in h)
r = api("api/delete", {"nonce": "n-lock-del1", "eid": _ent})
with db(readonly=True) as c:
    _alive = c.execute("SELECT is_deleted FROM journal_entries WHERE id=?",
                       (_ent,)).fetchone()[0] == 0
check("مقفل: الحذف يُرفض عند الحفظ نفسه", not r["ok"]
      and "مقفلان" in r["error"] and _alive, r)
with db(readonly=True) as c:
    _pay = mweb.edit_payload(c, "sale", _ent)
r = api(f"api/edit/sale/{_ent}", {"nonce": "n-lock-ed01", "party": A,
        "src": _pay["src"], "date": _pay["date"], "vat": False,
        "notes": "x", "lines": _pay["lines"]})
check("مقفل: التعديل يُرفض", not r["ok"] and "مقفلان" in r["error"], r)
r = api("api/merge", {"nonce": "n-lock-mg01", "ids": [1, 2]})
check("مقفل: الدمج يُرفض", not r["ok"] and "مقفلان" in r["error"], r)
code, h = call("GET", "ops/sale", {"edit": str(_ent)})
check("مقفل: صفحة التعديل لا تُفتح", "مقفلان" in h and '"edit"' not in h)
r = post("receipt", {"nonce": "n-lock-rc01", "party": A, "box": "1400",
                     "date": D0, "rows": [{"kind": "cash", "amount": 5}]})
check("مقفل: تسجيل عملية جديدة يبقى مسموحاً", r["ok"], r)
r = api("boxes", {"act": "add_box", "name": "قسم وقت القفل"})
check("مقفل: أقسام الصناديق لا تُعدَّل", not r["ok"]
      and "مقفلان" in r["error"], r)
code, h = call("GET", "", {"tab": "guide"})
check("صفحات الدليل تُظهر حال القفل في أعلاها", "🔒 التعديل والحذف مقفل"
      in h)
r = api("api/editlock", {"pin": "2468", "lock": False})
code, h = call("GET", "stmt", {"code": a_code, "per": "all"})
check("الرمز يفتح القفل فتعود الأزرار", r["ok"] and not r["locked"]
      and 'data-delx="' in h and "🔓 قفل التعديل والحذف" in h, r)
with db() as c:
    mweb.set_edits_locked(c, True, "t")
    mweb.set_edit_pin(c, "", "t")
    _after = (mweb.edits_locked(c), mweb.has_edit_pin(c))
check("إلغاء الرمز من البرنامج يفتح القفل", _after == (False, False),
      _after)
with db(readonly=True) as c:
    _aud = c.execute("SELECT COUNT(*) FROM audit_log WHERE action LIKE"
                     " '%قفل التعديل والحذف%' OR details LIKE"
                     " '%قفل التعديل والحذف%'").fetchone()[0]
check("القفل والفتح مسجّلان في سجل التتبع", _aud >= 2, _aud)

print("── 6) السلامة")
with db(readonly=True) as c:
    g = c.execute("SELECT ROUND(SUM(gold_debit-gold_credit),3),"
                  " ROUND(SUM(cash_debit-cash_credit),2) FROM journal_lines l"
                  " JOIN journal_entries e ON e.id=l.entry_id WHERE"
                  " e.is_deleted=0").fetchone()
    rep = stock_guard.report(c)
    n_audit = c.execute("SELECT COUNT(*) FROM audit_log WHERE username=?",
                        (mweb.WEB_USER,)).fetchone()[0]
check("الدفتر متوازن", tuple(g) == (0.0, 0.0), tuple(g))
check("الخزنة = أطقمها", not rep["broken"]
      and abs((rep["worked"] or {}).get("diff", 0)) < 0.001, rep)
check("كل ترحيلٍ في سجل التتبع باسم «رابط المدير»", n_audit >= 6, n_audit)

print()
print(f"{len(OK)} ✔ · {len(BAD)} ✘")
for b in BAD:
    print("  ✘", b)
sys.exit(1 if BAD else 0)
