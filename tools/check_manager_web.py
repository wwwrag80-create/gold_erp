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


def call(method, path, query=None, body=None, cookie=True):
    with db(readonly=True) as c:
        pin = mw._get(c, mw.K_PIN).strip()
    headers = {}
    if cookie and pin:
        headers["Cookie"] = (f"{mw.COOKIE}="
                             f"{mw._cookie_value(TOK, SECRET, pin)}")
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
check("«دليل الموديلات» أول لوحة ثم «حركة الطقم»",
      h.index("<b>دليل الموديلات</b>") < h.index("<b>حركة الطقم</b>")
      < h.index("<b>الصناديق</b>") < h.index("<b>حركة المصنع</b>"))
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
