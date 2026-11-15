"""5.5: المشتريات والمبيعات الضريبية بالأطقم — المحاسبة كاملة.

    python3 tools/check_tax_shop.py

يُشتري المحلّ أطقماً بفاتورةٍ ضريبية (الطرق الثلاث: أجر · سعر جرام · سعر
طقم)، ويبيعها بفاتورةٍ ضريبية، ويُصدر إشعاراً دائناً (مرتجع مبيعات)،
ويُرجع للمورد — وحارس المخزون الصارم مفعّل طوال ذلك. ويُفحص بعد كل خطوة:
الميزانان (ذهب · نقد) · الخزنة = أطقمها · ضريبتا المدخلات والمخرجات ·
ذمم الأطراف · حالة كل طقم · ومنع تعديل الفاتورة الضريبية.
"""
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
T = tempfile.mkdtemp(prefix="taxshop_")
os.environ["GOLD_ERP_DATA_DIR"] = T
os.environ["JADEITE_STOCK_GUARD"] = "on"
import config  # noqa: E402

config.DB_PATH = pathlib.Path(T) / "t.db"
import main  # noqa: E402
from database.database import db  # noqa: E402

for _l, f in main.prepare_steps():
    f()
from models import set_purchases as sp, tax_invoices as ti  # noqa: E402
from models.accounts import acc_id  # noqa: E402
from models.entities import add_entity, get_entity  # noqa: E402
from models import stock_guard, wo_moves  # noqa: E402
from services.accounting_engine import account_balance  # noqa: E402

OK, BAD = [], []


def check(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print(("  ✔ " if cond else "  ✘ ") + name + ("" if cond else f"  [{info}]"))


def bal(conn, code_or_id):
    aid = code_or_id if isinstance(code_or_id, int) else acc_id(conn, code_or_id)
    g, c = account_balance(conn, aid)
    return round(g, 3), round(c, 2)


def ent_bal(conn, eid):
    return bal(conn, get_entity(conn, eid)["account_id"])


def ledger_ok(conn):
    r = conn.execute(
        "SELECT ROUND(SUM(gold_debit-gold_credit),3) g,"
        " ROUND(SUM(cash_debit-cash_credit),2) c FROM journal_lines l"
        " JOIN journal_entries e ON e.id=l.entry_id WHERE e.is_deleted=0"
        ).fetchone()
    return abs(r["g"] or 0) < 1e-6 and abs(r["c"] or 0) < 1e-6, tuple(r)


def guard_clean(conn):
    r = stock_guard.report(conn)
    w, it = r["worked"] or {}, r["italian"] or {}
    ok = (abs(w.get("diff", 0)) < 0.001 and abs(it.get("diff", 0)) < 0.001
          and not r["broken"])
    return ok, {"worked": w, "italian": it, "broken": r["broken"]}


D = "2026-11-10"
with db() as c:
    sup = add_entity(c, "شركة الذهب للتوريد", "supplier", vat_number="300000000000003", username="t")
    cus = add_entity(c, "عميل المحل", "customer", vat_number="311111111111113", username="t")
    w0 = bal(c, "1200")
print("── 1) فاتورة شراء ضريبية — الأجر فقط (الذهب بالوزن)")
with db() as c:
    r1 = sp.create_purchase(c, sup, D, "SUP-1001", [
        {"wo_no": "T501", "model_no": "A1", "pieces": 3, "registered": 10,
         "standing": 11, "wage": 20},
        {"wo_no": "T502", "pieces": 2, "registered": 5, "standing": 5,
         "wage": 30}], "t", pricing="wage")
    check("الفاتورة: صافي 350 · ضريبة 52.50 · إجمالي 402.50",
          (r1["net"], r1["vat"], r1["total"]) == (350.0, 52.5, 402.5), r1)
    check("الخزنة +15 جم بالأطقم", bal(c, "1200")[0] == round(w0[0] + 15, 3), bal(c, "1200"))
    check("المورد دائن 15 جم ذهب و402.50 ريال", ent_bal(c, sup) == (-15.0, -402.5), ent_bal(c, sup))
    check("ضريبة المدخلات 1900 مدينة 52.50", bal(c, "1900")[1] == 52.5, bal(c, "1900"))
    check("مصنعية المشتريات 5530 مدينة 350", bal(c, "5530")[1] == 350.0, bal(c, "5530"))
    wo = c.execute("SELECT * FROM work_orders WHERE work_order_no='T501'").fetchone()
    check("بطاقة الطقم: مقيد 10 · قائم 11 · عدد 3 · في الخزنة",
          (wo["registered_weight"], wo["standing_gold"], wo["pieces"], wo["status"]) == (10, 11, 3, "in_stock"),
          dict(wo))
    check("الدفتر متوازن", ledger_ok(c)[0], ledger_ok(c))
    try:
        sp.create_purchase(c, sup, D, "SUP-1001", [{"wo_no": "T509", "registered": 1, "wage": 1}], "t")
        check("فاتورة المورد نفسها لا تُقيَّد مرتين", False)
    except ValueError:
        check("فاتورة المورد نفسها لا تُقيَّد مرتين", True)
    try:
        sp.create_purchase(c, sup, D, "SUP-1002", [{"wo_no": "T501", "registered": 1, "wage": 1}], "t")
        check("رقم تشغيلٍ في الخزنة لا يُشترى ثانيةً", False)
    except ValueError:
        check("رقم تشغيلٍ في الخزنة لا يُشترى ثانيةً", True)

print("── 2) شراء بسعر الجرام + الأجر (بالريال كاملاً)")
with db() as c:
    b6100 = bal(c, "6100")
    r2 = sp.create_purchase(c, sup, D, "SUP-1003", [
        {"wo_no": "T503", "pieces": 1, "registered": 8, "standing": 8.5, "wage": 10}],
        "t", pricing="gram", gold_price=200, price_karat=18)
    # 8 جم × (200 + 10) = 1680 · ضريبة 252
    check("صافي 1680 · ضريبة 252 · إجمالي 1932",
          (r2["net"], r2["vat"], r2["total"]) == (1680.0, 252.0, 1932.0), r2)
    check("المورد بلا ذهب — ريالٌ فقط", ent_bal(c, sup) == (-15.0, -2334.5), ent_bal(c, sup))
    g, cc = bal(c, "6100")
    check("الذهب اشتُري عبر مركز التسكير: −8 جم و+1600 ريال",
          (round(g - b6100[0], 3), round(cc - b6100[1], 2)) == (-8.0, 1600.0), (g, cc))
    check("الدفتر متوازن", ledger_ok(c)[0], ledger_ok(c))

print("── 3) شراء بسعر الطقم + عيار 21 لسعر الجرام")
with db() as c:
    r3 = sp.create_purchase(c, sup, D, "SUP-1004", [
        {"wo_no": "T504", "pieces": 4, "registered": 6, "standing": 6, "piece_price": 2000}],
        "t", pricing="piece", gold_price=230, price_karat=21)
    # قيمة الذهب: 6×18/21 × 230 = 1182.86 · المصنعية 817.14 · ضريبة 300
    check("صافي 2000 · ضريبة 300 · إجمالي 2300",
          (r3["net"], r3["vat"], r3["total"]) == (2000.0, 300.0, 2300.0), r3)
    check("قيمة الذهب بعيار السعر 1182.86 والمصنعية 817.14",
          (r3["gold_value"], r3["wages"]) == (1182.86, 817.14), r3)
    try:
        sp.create_purchase(c, sup, D, "SUP-1005", [{"wo_no": "T505", "registered": 6, "piece_price": 500}],
                           "t", pricing="piece", gold_price=230, price_karat=21)
        check("سعر طقمٍ أقل من قيمة ذهبه يُرفض", False)
    except ValueError:
        check("سعر طقمٍ أقل من قيمة ذهبه يُرفض", True)
    check("الدفتر متوازن", ledger_ok(c)[0], ledger_ok(c))
    ok, p = guard_clean(c)
    check("حارس المخزون: الخزنة = أطقمها", ok, p)

print("── 4) فاتورة بيع ضريبية — الأجر فقط")
with db() as c:
    ids = {r["work_order_no"]: r["id"] for r in c.execute(
        "SELECT id, work_order_no FROM work_orders WHERE work_order_no LIKE 'T50%' AND is_deleted=0")}
    s1 = ti.create_invoice(c, cus, [{"work_order_id": ids["T501"], "wage_override": 40, "pieces": 3}],
                           D, "t", "wage")
    check("بيع 10 جم × أجر 40 = 400 · ضريبة 60", (s1["total_wages"], s1["vat"], s1["grand_total"]) == (400, 60, 460), s1)
    check("العميل مدين 10 جم و460 ريال", ent_bal(c, cus) == (10.0, 460.0), ent_bal(c, cus))
    check("الطقم خرج من الخزنة", c.execute("SELECT status FROM work_orders WHERE id=?", (ids["T501"],)).fetchone()[0] == "sold")
    check("الفاتورة معلَّمة ضريبية بطريقتها", ti.is_tax(c, s1["id"]))
    check("الدفتر متوازن", ledger_ok(c)[0], ledger_ok(c))

print("── 5) فاتورة بيع ضريبية بسعر الجرام (بالريال كاملاً)")
with db() as c:
    g0 = bal(c, "6100")
    s2 = ti.create_invoice(c, cus, [{"work_order_id": ids["T503"], "wage_override": 25, "pieces": 1}],
                           D, "t", "gram", gold_price=210, price_karat=18)
    # 8 × (210 + 25) = 1880 · ضريبة 282 · إجمالي 2162
    check("صافي 1880 · ضريبة 282 · إجمالي 2162",
          (round(s2["total_wages"] + s2["gold_value"], 2), s2["vat"], s2["grand_total"]) == (1880, 282, 2162), s2)
    check("العميل بلا ذهبٍ زائد — ريالٌ فقط", ent_bal(c, cus) == (10.0, 2622.0), ent_bal(c, cus))
    g1 = bal(c, "6100")
    check("الذهب بيع عبر مركز التسكير: +8 جم و−1680 ريال",
          (round(g1[0] - g0[0], 3), round(g1[1] - g0[1], 2)) == (8.0, -1680.0), (g0, g1))
    check("الدفتر متوازن", ledger_ok(c)[0], ledger_ok(c))

print("── 6) فاتورة بيع بسعر الطقم")
with db() as c:
    s3 = ti.create_invoice(c, cus, [{"work_order_id": ids["T504"], "piece_price": 2600, "pieces": 4}],
                           D, "t", "piece", gold_price=235, price_karat=21)
    check("صافي 2600 · ضريبة 390 · إجمالي 2990",
          (round(s3["total_wages"] + s3["gold_value"], 2), s3["vat"], s3["grand_total"]) == (2600, 390, 2990), s3)
    check("الدفتر متوازن", ledger_ok(c)[0], ledger_ok(c))
    ok, p = guard_clean(c)
    check("حارس المخزون بعد البيع", ok, p)

print("── 7) الفاتورة الضريبية لا تُعدَّل ولا تُنقل ولا تُعكس")
from models import invoices as inv_mod, operations, reversal  # noqa: E402
for label, fn in (("تعديل", lambda c: inv_mod.update_invoice(c, s1["id"], [], "t")),
                  ("نقل", lambda c: operations.transfer_invoice(c, s1["id"], sup, "t")),
                  ("عكس نوع", lambda c: operations.flip_invoice_kind(c, s1["id"], "t")),
                  ("عكس", lambda c: reversal.reverse(c, s1["entry_id"], "t"))):
    try:
        with db() as c:
            fn(c)
        check(f"«{label}» مرفوض للفاتورة الضريبية", False)
    except ValueError as e:
        check(f"«{label}» مرفوض للفاتورة الضريبية", "إشعار" in str(e) or "ضريبية" in str(e), str(e)[:90])

print("── 8) إشعار دائن (مرتجع مبيعات) من فاتورة سعر الجرام")
with db() as c:
    left = ti.returnable(c, s2["id"])
    cn = ti.create_credit_note(c, s2["id"], D, [{"item_id": left[0]["item_id"]}], "إرجاع العميل", "t")
    check("المرتجع يعكس الفاتورة: 1880 + 282", (round(cn["total_wages"] + cn["gold_value"], 2), cn["vat"]) == (1880, 282), cn)
    check("العميل عاد إلى ما قبلها", ent_bal(c, cus) == (10.0, 3450.0), ent_bal(c, cus))
    check("الطقم عاد إلى الخزنة", c.execute("SELECT status FROM work_orders WHERE id=?", (ids["T503"],)).fetchone()[0] == "in_stock")
    ref = c.execute("SELECT ref_invoice_id, pricing FROM invoices WHERE id=?", (cn["id"],)).fetchone()
    check("الإشعار يشير إلى فاتورته ويأخذ طريقتها", (ref[0], ref[1]) == (s2["id"], "gram"), tuple(ref))
    try:
        ti.create_credit_note(c, s2["id"], D, [{"item_id": left[0]["item_id"]}], "مرة ثانية", "t")
        check("لا يُرتجع الطقم مرتين من الفاتورة نفسها", False)
    except ValueError:
        check("لا يُرتجع الطقم مرتين من الفاتورة نفسها", True)
    check("الدفتر متوازن", ledger_ok(c)[0], ledger_ok(c))
    lbl = __import__("models.journal", fromlist=["x"])._doc_info(c, "invoices", cn["id"], {})[1]
    check("يظهر في كشف الحساب «مرتجع مبيعات»", "مرتجع مبيعات" in lbl, lbl)

print("── 9) مرتجع مشتريات")
with db() as c:
    rr = sp.returnable(c, r1["id"])
    t501 = next(x for x in rr if x["wo_no"] == "T501")
    t502 = next(x for x in rr if x["wo_no"] == "T502")
    check("الطقم المباع لا يُرجع للمورد", bool(t501["why"]), t501)
    check("الطقم في الخزنة يُرجع", not t502["why"] and t502["left"] == 5, t502)
    before = ent_bal(c, sup)
    pr = sp.create_return(c, r1["id"], D, [{"line_id": t502["line_id"]}], "عيب صناعة", "t")
    # 5 جم × 30 = 150 + 22.50
    check("المرتجع: 150 + 22.50 = 172.50", (pr["net"], pr["vat"], pr["total"]) == (150, 22.5, 172.5), pr)
    after = ent_bal(c, sup)
    check("المورد: ينقص 5 جم و172.50 ريال",
          (round(after[0] - before[0], 3), round(after[1] - before[1], 2)) == (5.0, 172.5), (before, after))
    w = c.execute("SELECT is_deleted, out_doc FROM work_orders WHERE work_order_no='T502'").fetchone()
    check("بطاقة الطقم مطويّة ومرجعها المرتجع", w[0] == 1 and w[1] == pr["doc_no"], tuple(w))
    check("الدفتر متوازن", ledger_ok(c)[0], ledger_ok(c))
    ok, p = guard_clean(c)
    check("حارس المخزون بعد المرتجع", ok, p)

print("── 10) الضريبة والإقرار")
from models import reports  # noqa: E402
with db() as c:
    vr = reports.vat_return(c, "2026-01-01", "2026-12-31")
    out_exp = 60 + 282 + 390 - 282
    in_exp = 52.5 + 252 + 300 - 22.5
    check(f"ضريبة المخرجات {out_exp}", round(vr["output_vat"], 2) == out_exp, vr["output_vat"])
    check(f"ضريبة المدخلات {in_exp}", round(vr["input_vat"], 2) == in_exp, vr["input_vat"])
    st = ti.totals(c, "2026-01-01", "2026-12-31")
    check("وعاء المبيعات الضريبية = 400 + 1880 + 2600 − 1880 = 3000", st["base"] == 3000, st)
    pt = sp.totals(c, "2026-01-01", "2026-12-31")
    check("وعاء المشتريات الضريبية = 350 + 1680 + 2000 − 150 = 3880", pt["base"] == 3880, pt)
    check("وعاء الإقرار للمبيعات يشمل قيمة الذهب",
          round(vr["sales_base"], 2) == 3000.0, vr["sales_base"])

print("── 11) سلسلة الحركة بعد الإقلاع (resync)")
with db() as c:
    fixed = wo_moves.resync(c, None, "t")
    check("لا تصحيح يلزم — الحالات متّسقة", not fixed, fixed)

print("── 12) نوع الفاتورة (5.5.1): ضريبية لمنشأة · مبسطة لفرد · عميل نقدي")
with db() as c:
    ind = add_entity(c, "فرد بلا رقم", "customer", username="t")
    r9 = sp.create_purchase(c, sup, D, "SUP-9", [
        {"wo_no": "T901", "pieces": 1, "registered": 6, "wage": 10},
        {"wo_no": "T902", "pieces": 1, "registered": 4, "wage": 10}], "t")
    ids9 = {r["work_order_no"]: r["id"] for r in c.execute(
        "SELECT id, work_order_no FROM work_orders WHERE work_order_no IN"
        " ('T901','T902')")}
    try:
        ti.create_invoice(c, ind, [{"work_order_id": ids9["T901"]}], D, "t",
                          "wage")
        check("الضريبية لفردٍ بلا رقمٍ ضريبي تُرفض", False)
    except ValueError as e:
        check("الضريبية لفردٍ بلا رقمٍ ضريبي تُرفض وتدلّ على المبسطة",
              "مبسطة" in str(e), str(e))
    try:
        ti.create_invoice(c, None, [{"work_order_id": ids9["T901"]}], D, "t",
                          "wage", subtype="simplified", pay_mode="cash")
        check("العميل النقدي بالأجر وحده يُرفض", False)
    except ValueError as e:
        check("العميل النقدي بالأجر وحده يُرفض (لا ذهب على حسابٍ بلا صاحب)",
              "بالريال" in str(e), str(e))
    try:
        ti.create_invoice(c, None, [{"work_order_id": ids9["T901"]}], D, "t",
                          "piece", 300, 18, subtype="simplified")
        check("العميل النقدي آجلاً يُرفض", False)
    except ValueError as e:
        check("العميل النقدي لا يُباع آجلاً", "نقداً" in str(e), str(e))
    box0 = bal(c, "1400")[1]
    w9 = ti.create_invoice(c, None, [{"work_order_id": ids9["T901"],
                                      "piece_price": 2300, "pieces": 1}],
                           D, "t", "piece", 300, 18, subtype="simplified",
                           buyer_name="محمد", buyer_phone="0555",
                           pay_mode="cash")
    row = c.execute("SELECT tax_subtype, buyer_name, buyer_phone, pay_mode,"
                    " pay_voucher_id FROM invoices WHERE id=?",
                    (w9["id"],)).fetchone()
    check("المبسطة لعميلٍ نقدي: النوع والاسم والجوال والدفع على الفاتورة",
          tuple(row)[:4] == ("simplified", "محمد", "0555", "cash")
          and row[4], tuple(row))
    wk = ti.walkin_customer(c, False)
    check("سند قبضٍ تلقائي: الصندوق +2645 وحساب العميل النقدي صفر",
          round(bal(c, "1400")[1] - box0, 2) == 2645.0
          and ent_bal(c, wk) == (0.0, 0.0), (bal(c, "1400"), ent_bal(c, wk)))
    from services.fatoora import ledger as _fl
    doc = _fl.build_doc(c, w9["id"])
    check("المستند الإلكتروني: مبسطة باسم المشتري المكتوب",
          doc["subtype"] == "simplified" and doc["buyer"]["name"] == "محمد",
          (doc["subtype"], doc["buyer"]))
    cn9 = ti.create_credit_note(c, w9["id"], D, [{"item_id": ti.returnable(
        c, w9["id"])[0]["item_id"]}], "مرتجع", "t")
    rr9 = c.execute("SELECT tax_subtype, buyer_name, pay_mode FROM invoices"
                    " WHERE id=?", (cn9["id"],)).fetchone()
    check("الإشعار يرث النوع والمشتري ويُردّ نقداً بسند صرف",
          tuple(rr9) == ("simplified", "محمد", "cash")
          and cn9.get("voucher_no") and round(bal(c, "1400")[1] - box0, 2)
          == 0.0 and ent_bal(c, wk) == (0.0, 0.0),
          (tuple(rr9), bal(c, "1400"), ent_bal(c, wk)))
    s9 = ti.create_invoice(c, ind, [{"work_order_id": ids9["T902"],
                                     "wage_override": 15, "pieces": 1}],
                           D, "t", "wage", subtype="simplified",
                           pay_mode="bank")
    bank = bal(c, "1500")[1]
    check("مبسطة لفردٍ من الدليل بالشبكة: الأجور + الضريبة للبنك، والذهب "
          "على حسابه وزناً", ent_bal(c, ind) == (4.0, 0.0)
          and round(bank, 2) == round(4 * 15 * 1.15, 2),
          (ent_bal(c, ind), bank))
    check("الدفتر متوازن", ledger_ok(c)[0], ledger_ok(c))
    ok, p = guard_clean(c)
    check("حارس المخزون", ok, p)
    _ = (r9, s9)

print("── 13) 5.5.2: سعر الجرام لكل سطر · «إلى حساب» (الألماس) والبيع منه")
with db() as c:
    from models import coa
    from models.invoices import GOLD_GROUP
    dia = coa.add_sub_account(c, acc_id(c, GOLD_GROUP), "الألماس", "t",
                              measurement="gold")["id"]
    names = [r["code"] for r in sp.dest_accounts(c)]
    check("«إلى حساب»: الذهب المشغول والألماس — بلا الكسر ولا الإيطالي ولا"
          " خزينة التصنيع ولا التسويات",
          "1200" in names and any(r["id"] == dia for r in sp.dest_accounts(c))
          and not {"1100", "1210", "1250", "1310"} & set(names), names)
    for bad_code in ("1310", "1210", "1100"):
        try:
            sp.create_purchase(c, sup, D, f"SUP-X{bad_code}", [
                {"wo_no": f"TX{bad_code}", "registered": 1, "wage": 1}], "t",
                dest_account_id=acc_id(c, bad_code))
            check(f"الشراء إلى {bad_code} يُرفض", False)
        except ValueError:
            check(f"الشراء إلى {bad_code} يُرفض", True)
    w1200 = bal(c, "1200")
    # سطران بعيارين وسعرين: 10 جم عيار 18 بسعر 250 · 6 جم عيار 21 (مكافئها
    # 7 بعيار 18 — الأوزان تُمرَّر للدفتر بمكافئ 18) بسعر 290
    r13 = sp.create_purchase(c, sup, D, "SUP-13", [
        {"wo_no": "T131", "pieces": 1, "registered": 10, "wage": 20,
         "karat": 18, "gold_price": 250},
        {"wo_no": "T132", "pieces": 1, "registered": 7.0, "wage": 15,
         "karat": 21, "gold_price": 290}], "t", pricing="gram",
        gold_price=250, price_karat=18, dest_account_id=dia)
    # T131: 10 × (250 + 20) = 2700 · T132: ذهب 6 × 290 = 1740 + أجر 7 × 15
    # = 105 → 1845 · الصافي 4545
    lines = c.execute("SELECT wo_no, gold_price, gold_value, wages FROM"
                      " set_purchase_lines WHERE doc_id=? ORDER BY line_no",
                      (r13["id"],)).fetchall()
    check("قيمة ذهب كل سطرٍ بسعره وعياره: 2500 · 1740 (6 جم عيار 21 × 290)",
          [round(x["gold_value"], 2) for x in lines] == [2500.0, 1740.0]
          and [x["gold_price"] for x in lines] == [250, 290],
          [tuple(x) for x in lines])
    check("صافي الفاتورة = Σ (قيمة الذهب + الأجور) = 4545",
          r13["net"] == 4545.0, r13)
    check("الأطقم دخلت حساب الألماس لا الذهب المشغول",
          bal(c, dia)[0] == 17.0 and bal(c, "1200") == w1200,
          (bal(c, dia), bal(c, "1200")))
    homes = {r[0]: r[1] for r in c.execute(
        "SELECT work_order_no, stock_account_id FROM work_orders WHERE"
        " work_order_no IN ('T131','T132')")}
    check("بيت كل طقمٍ حساب الألماس", set(homes.values()) == {dia}, homes)
    ok, p = guard_clean(c)
    check("حارس المخزون بعد الشراء إلى الألماس", ok, p)
    ids13 = {r["work_order_no"]: r["id"] for r in c.execute(
        "SELECT id, work_order_no FROM work_orders WHERE work_order_no IN"
        " ('T131','T132')")}
    s13 = ti.create_invoice(c, cus, [
        {"work_order_id": ids13["T131"], "wage_override": 30, "pieces": 1,
         "karat": 18, "gold_price": 300},
        {"work_order_id": ids13["T132"], "wage_override": 20,
         "pieces": 1, "karat": 21, "gold_price": 340}], D, "t", "gram",
        gold_price=300, price_karat=18)
    its = c.execute("SELECT gold_price, gold_value, wages FROM invoice_items"
                    " WHERE invoice_id=? ORDER BY id", (s13["id"],)).fetchall()
    check("البيع: سعر جرام كل سطرٍ محفوظ وقيمته 3000 · 2040 (6 × 340)",
          [x["gold_price"] for x in its] == [300, 340]
          and [round(x["gold_value"], 2) for x in its] == [3000.0, 2040.0],
          [tuple(x) for x in its])
    # 10×(300+30) = 3300 · 2040 + 7×20 = 2180 → 5480 · ضريبة 822
    check("صافي 5480 · ضريبة 822",
          (round(s13["total_wages"] + s13["gold_value"], 2), s13["vat"])
          == (5480.0, 822.0), s13)
    check("البيع خرج من حساب الألماس (برقم التشغيل)", bal(c, dia)[0] == 0.0,
          bal(c, dia))
    cn13 = ti.create_credit_note(c, s13["id"], D, [
        {"item_id": ti.returnable(c, s13["id"])[1]["item_id"]}], "مرتجع", "t")
    check("الإشعار الدائن بسعر جرام السطر نفسه (2040) ويعود للألماس",
          round(cn13["gold_value"], 2) == 2040.0 and bal(c, dia)[0] == 7.0,
          (cn13.get("gold_value"), bal(c, dia)))
    pr13 = sp.create_return(c, r13["id"], D, [
        {"line_id": sp.returnable(c, r13["id"])[1]["line_id"]}], "عيب", "t")
    check("مرتجع المشتريات يخرج من الألماس", bal(c, dia)[0] == 0.0
          and pr13["total"] > 0, (bal(c, dia), pr13))
    check("الدفتر متوازن", ledger_ok(c)[0], ledger_ok(c))
    ok, p = guard_clean(c)
    check("حارس المخزون", ok, p)
    from services import print_manager as pm
    h = pm.build_html("invoice", s13["id"])
    hp = pm.build_html("set_purchase", r13["id"])
    hm = pm.build_html("invoice_models", s13["id"])
    check("الطباعة: لا «المصنعية»، و«سعر الجرام» لكل سطر، و«إلى حساب»",
          "المصنعية" not in h and "سعر الجرام" in h and "340.00" in h
          and "المصنعية" not in hp and "290.00" in hp and "الألماس" in hp)
    check("صور موديلات الفاتورة بقالب المجمّعة: أرقام التشغيل داخل الإطار",
          'class="gwos"' in hm and "T131" in hm and "T132" in hm)

print()
print(f"{len(OK)} ✔ · {len(BAD)} ✘")
for b in BAD:
    print("  ✘", b)
sys.exit(1 if BAD else 0)
