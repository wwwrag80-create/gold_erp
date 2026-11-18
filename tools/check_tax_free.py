"""5.8.0: المبيعات والمشتريات الضريبية بالإدخال اليدوي (أي رقم تشغيل).

    python3 tools/check_tax_free.py

رقم التشغيل نصٌّ حر ولو تكرّر (يُشترى «1» من مورد ومن مندوب)، والوزن
يتحرّك في «مخزون الذهب الضريبي» 1230 وقد يصير سالباً، بلا مساسٍ بالذهب
المشغول 1200 ولا الإيطالي 1210 (حارس المخزون الصارم مفعّل طوال الفحص).
ومعه الخصم النقدي على المستند: الضريبة على (الصافي − الخصم)، ويُردّ
بنسبته في المرتجع، وتظهر الأنواع في الكشف بأسمائها الضريبية.
"""
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
T = tempfile.mkdtemp(prefix="taxfree_")
os.environ["GOLD_ERP_DATA_DIR"] = T
os.environ["JADEITE_STOCK_GUARD"] = "on"
import config  # noqa: E402

config.DB_PATH = pathlib.Path(T) / "t.db"
import main  # noqa: E402
from database.database import db  # noqa: E402

for _l, f in main.prepare_steps():
    f()
from models import set_purchases as sp, tax_invoices as tx  # noqa: E402
from models import tax_free as tf, stock_guard, journal  # noqa: E402
from models.accounts import acc_id  # noqa: E402
from models.entities import add_entity, get_entity  # noqa: E402
from services.accounting_engine import account_balance  # noqa: E402

OK, BAD = [], []


def check(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print(("  ✔ " if cond else "  ✘ ") + name + ("" if cond else f"  [{info}]"))


def bal(conn, code):
    g, c = account_balance(conn, acc_id(conn, code))
    return round(g, 3), round(c, 2)


def ent_bal(conn, eid):
    g, c = account_balance(conn, get_entity(conn, eid)["account_id"])
    return round(g, 3), round(c, 2)


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


def raises(fn, needle=""):
    try:
        fn()
    except ValueError as e:
        return needle in str(e)
    return False


D = "2026-11-10"
with db() as c:
    sup = add_entity(c, "مورد أ", "supplier", vat_number="300000000000003",
                     username="t")
    rep = add_entity(c, "مندوب ب", "customer", username="t")
    com = add_entity(c, "شركة الريان", "customer",
                     vat_number="311111111111113", username="t")
    n_wo0 = c.execute("SELECT COUNT(*) FROM work_orders").fetchone()[0]
    w0, i0 = bal(c, "1200"), bal(c, "1210")

    print("— الحسابات")
    check("«مخزون الذهب الضريبي» 1230 موجود وأول قائمة الإدخال اليدوي",
          tf.stock_accounts(c)[0]["code"] == "1230")
    codes = {r["code"] for r in tf.stock_accounts(c)}
    check("المشغول 1200 والإيطالي 1210 ليسا في قائمة الإدخال اليدوي",
          not codes & {"1200", "1210"}, codes)
    check("حساب 1200 مرفوض للإدخال اليدوي",
          raises(lambda: tf.check_stock(c, acc_id(c, "1200")), "لا يمسّ"))
    check("حسابا الخصم 5200 و4600 موجودان",
          bool(acc_id(c, "5200")) and bool(acc_id(c, "4600")))

    print("— المشتريات: رقم التشغيل نفسه من جهتين")
    p1 = sp.create_purchase(c, sup, D, "INV-77", [
        {"wo_no": "1", "registered": 10, "karat": 18, "wage": 12}], "t",
        pricing="wage", mode="free")
    check("شراء «1» وزن 10 بالأجر: صافي 120 وضريبة 18",
          (p1["net"], p1["vat"], p1["total"]) == (120.0, 18.0, 138.0), p1)
    p2 = sp.create_purchase(c, rep, D, "B-5", [
        {"wo_no": "1", "registered": 30 * 21 / 18, "karat": 21,
         "piece_price": 9000, "gold_price": 250}], "t", pricing="piece",
        gold_price=250, price_karat=21, mode="free", discount=100)
    check("شراء «1» مرةً ثانية من المندوب (رقم مكرر مسموح)",
          bool(p2.get("id")), p2)
    check("خصم 100: الضريبة على 8,900 = 1,335 والإجمالي 10,235",
          (p2["net"], p2["discount"], p2["vat"], p2["total"])
          == (9000.0, 100.0, 1335.0, 10235.0), p2)
    check("لا أطقم جديدة في دليل التشغيل",
          c.execute("SELECT COUNT(*) FROM work_orders").fetchone()[0] == n_wo0)
    check("1230 = 10 + 35 = 45", tf.balance(c) == 45.0, tf.balance(c))
    check("الخصم المكتسب 4600 دائن 100", bal(c, "4600")[1] == -100.0,
          bal(c, "4600"))
    check("خصم ≥ الصافي مرفوض", raises(lambda: sp.create_purchase(
        c, sup, D, "X", [{"wo_no": "9", "registered": 1, "karat": 18,
                          "wage": 10}], "t", pricing="wage", mode="free",
        discount=10), "أقل"))

    print("— المبيعات: بيع أكثر من الرصيد (سالب مسموح)")
    s1 = tf.create_sale(c, com, [
        {"wo_no": "1", "weight": 50, "karat": 18, "wage": 15,
         "model_no": "M9"}], D, "t", "wage", subtype="standard", discount=50)
    check("بيع «1» وزن 50: صافي 750 خصم 50 ضريبة 105 إجمالي 805",
          (s1["net"], s1["discount"], s1["vat"], s1["grand_total"])
          == (750.0, 50.0, 105.0, 805.0), s1)
    check("1230 صار سالباً (−5) ولم يُمنع البيع", tf.balance(c) == -5.0,
          tf.balance(c))
    check("ذمة الشركة: ذهب 50 ونقد 805", ent_bal(c, com) == (50.0, 805.0),
          ent_bal(c, com))
    check("الخصم المسموح به 5200 مدين 50", bal(c, "5200")[1] == 50.0,
          bal(c, "5200"))
    check("الفاتورة بإدخالٍ يدوي ورقمها S", tf.is_free(c, s1["id"])
          and s1["invoice_no"].startswith("S"), s1["invoice_no"])
    s2 = tf.create_sale(c, com, [
        {"wo_no": "7", "weight": 20, "karat": 21, "gold_price": 260,
         "wage": 8}], D, "t", "gram", gold_price=260, price_karat=21,
        subtype="standard", pay_mode="cash")
    # 5.8.2: طريقة الدفع تُكتب على الفاتورة فقط — لا سند قبضٍ تلقائي
    check("بيعٌ «نقداً»: الدفع على الفاتورة بلا سندٍ تلقائي",
          not s2.get("voucher_no") and c.execute(
              "SELECT pay_mode FROM invoices WHERE id=?",
              (s2["id"],)).fetchone()[0] == "cash"
          and c.execute("SELECT COUNT(*) FROM vouchers").fetchone()[0] == 0,
          s2)
    check("البحث في السجل برقم التشغيل اليدوي",
          any(r["id"] == s1["id"] for r in tx.search(c, "1")))

    print("— الإشعار الدائن (مرتجع مبيعات ضريبي)")
    rl = tx.returnable(c, s1["id"])
    check("ما يُرتجع: سطرٌ يدوي باقيه 50 وبنوع تسعيره",
          len(rl) == 1 and rl[0]["left"] == 50.0 and rl[0].get("free"), rl)
    cn = tx.create_credit_note(c, s1["id"], D, [
        {"item_id": rl[0]["item_id"], "weight": 25}], "مرتجع جزئي", "t")
    check("نصف الوزن: صافي 375 خصم مردود 25 ضريبة 52.5 إجمالي 402.5",
          (cn["net"], cn["discount"], cn["vat"], cn["grand_total"])
          == (375.0, 25.0, 52.5, 402.5), cn)
    check("الباقي للإرجاع 25", tx.returnable(c, s1["id"])[0]["left"] == 25.0)
    check("مرتجع أكثر من الباقي مرفوض", raises(lambda: tx.create_credit_note(
        c, s1["id"], D, [{"item_id": rl[0]["item_id"], "weight": 30}],
        "x", "t")))
    check("1230 بعد المرتجع = −5 − 20 + 25 = 0", tf.balance(c) == 0.0,
          tf.balance(c))
    check("5200 بعد ردّ الخصم = 25", bal(c, "5200")[1] == 25.0,
          bal(c, "5200"))

    print("— مرتجع المشتريات (وزن جزئي)")
    rr = sp.returnable(c, p2["id"])
    check("ما يُرتجع للمندوب: 35 بنوع تسعيره وسعره",
          len(rr) == 1 and abs(rr[0]["left"] - 35.0) < 1e-6
          and rr[0].get("free"), rr)
    pr = sp.create_return(c, p2["id"], D, [
        {"line_id": rr[0]["line_id"], "weight": 10}], "عيب", "t")
    check("مرتجع 10 من 35: خصم مردود 28.57 والإجمالي 2,924.29",
          (pr["discount"], pr["total"]) == (28.57, 2924.29), pr)
    check("4600 بعد ردّ الخصم = −71.43", bal(c, "4600")[1] == -71.43,
          bal(c, "4600"))
    check("1230 في النهاية = 0 − 10 = −10 (سالب مسموح)",
          tf.balance(c) == -10.0, tf.balance(c))
    from models import reports as _rp
    bs = _rp.balance_sheet(c)
    check("الميزانية العمومية متوازنة (ذهب · نقد) ومعها 1230",
          bs["balanced_cash"] and bs["balanced_gold"],
          (bs["diff_cash"], bs["diff_gold"]))

    print("— الضريبة والدفتر")
    from models import reports
    v = reports.vat_return(c, D, D)
    sb = round(700 + 4617.14 - 350, 2)
    pb = round(120 + 8900 - (2571.43 - 28.57), 2)
    check(f"إقرار: وعاء المبيعات {sb} بعد الخصم والإشعار",
          abs(v["sales_base"] - sb) < 0.02, v["sales_base"])
    check("إقرار: ضريبة المخرجات = 105 + 692.57 − 52.5",
          abs(v["output_vat"] - round(105 + 692.57 - 52.5, 2)) < 0.02,
          v["output_vat"])
    check(f"إقرار: وعاء المشتريات {pb}",
          abs(v["purchases_base"] - pb) < 0.02, v["purchases_base"])
    check("إقرار: ضريبة المدخلات = 18 + 1335 − 381.43",
          abs(v["input_vat"] - round(18 + 1335 - 381.43, 2)) < 0.02,
          v["input_vat"])
    check("الدفتر متوازن (ذهب · نقد)", ledger_ok(c)[0], ledger_ok(c))
    check("المشغول 1200 والإيطالي 1210 لم يتحرّكا",
          bal(c, "1200") == w0 and bal(c, "1210") == i0,
          (bal(c, "1200"), bal(c, "1210")))
    ok, info = guard_clean(c)
    check("حارس المخزون نظيف", ok, info)
    from services.fatoora import ledger as fl
    el = fl._lines(c, s1["id"])
    check("أسطر الفاتورة الإلكترونية = الصافي بعد الخصم (700)",
          abs(sum(x["amount"] for x in el) - 700.0) < 0.005, el)

    print("— الكشوف والقوالب")
    st = journal.statement(c, get_entity(c, com)["account_id"])
    ops = [r["op"] for r in st]
    check("كشف الشركة: «مبيعات ضريبية» و«مرتجع مبيعات ضريبي»",
          "مبيعات ضريبية" in ops
          and "مرتجع مبيعات ضريبي (إشعار دائن)" in ops, ops)
    ops2 = [r["op"] for r in journal.statement(
        c, get_entity(c, rep)["account_id"])]
    check("كشف المندوب: «مشتريات ضريبية» و«مرتجع مشتريات ضريبي»",
          "مشتريات ضريبية" in ops2 and "مرتجع مشتريات ضريبي" in ops2, ops2)
    from models import doc_delete
    eid = c.execute("SELECT entry_id FROM invoices WHERE id=?",
                    (s1["id"],)).fetchone()[0]
    check("الفاتورة الضريبية اليدوية لا تُحذف",
          raises(lambda: doc_delete.check(c, eid)))
    check("ولا تُعدَّل", raises(lambda: tx.guard(c, s1["id"]), "إشعار"))
    from services import print_manager as pm
    h = pm.build_html("invoice", s1["id"])
    hc = pm.build_html("invoice", cn["id"])
    hp = pm.build_html("set_purchase", p2["id"])
    hr = pm.build_html("set_purchase", pr["id"])
    # 5.8.1: لا «من/إلى حساب» ولا «الأسطر» ولا عمود موديل — والدفع ظاهر
    # و«رقم الباركود/الصنف» اسم العمود
    # 5.8.5: نوع التسعير لا يُطبع على الفاتورة الضريبية (بيعاً وشراءً)
    check("قالب البيع: الدفع · الخصم · رقم الباركود/الصنف — بلا نوع التسعير",
          all(x in h for x in ("الدفع", "خصم نقدي",
                               "الإجمالي الخاضع للضريبة",
                               "رقم الباركود/الصنف"))
          and not any(x in h for x in ("من حساب", "إلى حساب", "الأسطر",
                                       "الموديل", "رقم التشغيل",
                                       "نوع التسعير", "الأجر فقط —")))
    check("قالب الإشعار: «إشعار دائن — مرتجع مبيعات ضريبي» و«وزن المرتجع»",
          "مرتجع مبيعات ضريبي" in hc and "وزن المرتجع" in hc
          and "إلى حساب" not in hc and "خصم نقدي مردود" in hc)
    check("قالب الشراء: الدفع · الخصم — بلا «إلى حساب» ولا نوع التسعير",
          all(x in hp for x in ("الدفع", "خصم نقدي من المورد",
                                "رقم الباركود/الصنف"))
          and "إلى حساب" not in hp and "الموديل" not in hp
          and "نوع التسعير" not in hp and "الأجر فقط —" not in hp)
    check("قالب مرتجع الشراء: «مرتجع مشتريات ضريبي» · وزن المرتجع",
          all(x in hr for x in ("مرتجع مشتريات ضريبي", "وزن المرتجع",
                                "خصم نقدي مردود"))
          and "من حساب" not in hr)
    from models import purchases as pu
    rows, tot, _by = pu.vat_register(c, D, D)
    check("سجل المشتريات: الصافي الخاضع بعد الخصم",
          any(abs(r["amount"] - 8900.0) < 0.005 for r in rows), rows)


# ══════════════════════════════════════════════════════════════════
#  5.8.1: حسابا المشتريات ومردوداتها · الدفع من البنك · المصروفات الضريبية
# ══════════════════════════════════════════════════════════════════
print("— 5.8.1: المشتريات الضريبية ومردوداتها في الدليل")
with db() as c:
    st = journal.statement(c, acc_id(c, "5540"))
    docs = [r for r in st if r["doc_no"]]
    check("كشف «المشتريات الضريبية» 5540: صفٌّ لكل فاتورة باسم المورد",
          len(docs) == 2 and {r["name"] for r in docs} == {"مورد أ",
                                                           "مندوب ب"},
          [(r["doc_no"], r["name"]) for r in docs])
    check("5540 = الوزن المشترى 45 جم ومصنعية 120 + 1500",
          bal(c, "5540") == (45.0, 1620.0), bal(c, "5540"))
    st2 = [r for r in journal.statement(c, acc_id(c, "5545"))
           if r["doc_no"]]
    check("كشف «مردودات المشتريات الضريبية» 5545: المرتجع باسم مورده",
          len(st2) == 1 and st2[0]["name"] == "مندوب ب"
          and st2[0]["op"] == "مرتجع مشتريات ضريبي", st2)
    check("مقابل الوزن 5549 يعيده للمخزون (−45 + 10)",
          bal(c, "5549") == (-35.0, 0.0), bal(c, "5549"))
    bs = __import__("models.reports", fromlist=["x"]).balance_sheet(c)
    check("الميزانية متوازنة بعد حسابات 5.8.1",
          bs["balanced_cash"] and bs["balanced_gold"],
          (bs["diff_cash"], bs["diff_gold"]))

print("— 5.8.2: الدفع يُكتب على الفاتورة · حسابٌ جديد باسمه · بلا سندات")
with db() as c:
    from models.accounts import (create_pay_account, pay_accounts,
                                 resolve_pay)
    bank = create_pay_account(c, "بنك الراجحي", "bank", "t")
    box2 = create_pay_account(c, "صندوق المعرض", "cash", "t")
    codes = {r["id"]: r["code"] for r in pay_accounts(c)}
    check("حسابٌ جديد باسمه: البنك 15xx والصندوق 14xx تحت النقدية",
          codes.get(bank, "").startswith("15")
          and codes.get(box2, "").startswith("14"), codes)
    check("الاسم المكرّر مرفوض", raises(lambda: create_pay_account(
        c, "بنك الراجحي", "bank", "t"), "موجود"))
    check("البنك الجديد يُقرأ «بنكي» والصندوق «نقداً»",
          resolve_pay(c, "cash", bank) == ("bank", bank)
          and resolve_pay(c, "cash", box2) == ("cash", box2))
    check("حسابٌ ليس صندوقاً ولا بنكاً مرفوض للدفع",
          raises(lambda: resolve_pay(c, "cash", acc_id(c, "1230")),
                 "صندوقاً"))
    nv0 = c.execute("SELECT COUNT(*) FROM vouchers").fetchone()[0]
    sup_b0 = ent_bal(c, sup)
    p3 = sp.create_purchase(c, sup, D, "INV-90", [
        {"wo_no": "X1", "registered": 5, "karat": 18, "wage": 10}], "t",
        pricing="wage", mode="free", pay_mode="cash", pay_account_id=bank)
    check("شراءٌ «من البنك»: على حساب المورد ولا سند صرفٍ ولا حركة بنك",
          bal(c, codes[bank])[1] == 0.0 and round(ent_bal(c, sup)[1]
                                             - sup_b0[1], 2) == -57.5
          and c.execute("SELECT COUNT(*) FROM vouchers").fetchone()[0]
          == nv0, (bal(c, codes[bank]), ent_bal(c, sup)))
    check("والفاتورة تحفظ البنك للطباعة", c.execute(
        "SELECT pay_mode, pay_account_id FROM set_purchases WHERE id=?",
        (p3["id"],)).fetchone()[:] == ("bank", bank))
    rr3 = sp.returnable(c, p3["id"])
    sp.create_return(c, p3["id"], D, [
        {"line_id": rr3[0]["line_id"], "weight": 2}], "عيب", "t")
    check("مرتجعه بلا سند قبضٍ تلقائي", c.execute(
        "SELECT COUNT(*) FROM vouchers").fetchone()[0] == nv0)
    s3 = tf.create_sale(c, com, [
        {"wo_no": "Z9", "weight": 4, "karat": 18, "wage": 20}], D, "t",
        "wage", subtype="standard", pay_mode="cash", pay_account_id=box2)
    rl3 = tx.returnable(c, s3["id"])
    cn3 = tx.create_credit_note(c, s3["id"], D, [
        {"item_id": rl3[0]["item_id"]}], "إرجاع", "t")
    check("بيعٌ «في الصندوق» وإشعاره: لا سند قبضٍ ولا صرفٍ تلقائي",
          not s3.get("voucher_no") and not cn3.get("voucher_no")
          and bal(c, codes[box2])[1] == 0.0 and c.execute(
              "SELECT COUNT(*) FROM vouchers").fetchone()[0] == nv0)
    check("الإشعار يرث صندوق فاتورته للطباعة", c.execute(
        "SELECT pay_account_id FROM invoices WHERE id=?",
        (cn3["id"],)).fetchone()[0] == box2)
    hs = __import__("services.print_manager",
                    fromlist=["x"]).build_html("invoice", s3["id"])
    check("قالب البيع يذكر الصندوق في «الدفع»", "صندوق المعرض" in hs)

print("— 5.8.2: المبيعات الضريبية ومردوداتها في الدليل")
with db() as c:
    st = [r for r in journal.statement(c, acc_id(c, "4130")) if r["doc_no"]]
    check("كشف «المبيعات الضريبية» 4130: صفٌّ لكل فاتورة باسم العميل",
          len(st) == 3 and all(r["name"] == "شركة الريان" for r in st)
          and all(r["op"] == "مبيعات ضريبية" for r in st),
          [(r["doc_no"], r["name"], r["op"]) for r in st])
    check("4130 دائن بالوزن المباع كله 74 جم (50 + 20 + 4)",
          bal(c, "4130")[0] == -74.0, bal(c, "4130"))
    st2 = [r for r in journal.statement(c, acc_id(c, "4930"))
           if r["doc_no"]]
    check("كشف «مردودات المبيعات الضريبية» 4930: الإشعاران باسم العميل",
          len(st2) == 2 and all(r["name"] == "شركة الريان" for r in st2),
          [(r["doc_no"], r["name"]) for r in st2])
    check("لا شيء من الفواتير الضريبية في 4110/4120 بعد اليوم",
          bal(c, "4110") == (0.0, 0.0) and bal(c, "4120") == (0.0, 0.0),
          (bal(c, "4110"), bal(c, "4120")))
    bs = __import__("models.reports", fromlist=["x"]).balance_sheet(c)
    check("الميزانية متوازنة", bs["balanced_cash"] and bs["balanced_gold"])
    reg = tx.sales_register(c, "0000-01-01", "9999-12-31", "Z9")
    check("سجل المبيعات: البحث برقم الصنف في كل الفترات (الفاتورة ومرتجعها)",
          [r["no"] for r in reg] == [s3["invoice_no"], cn3["invoice_no"]],
          [r["no"] for r in reg])
    allr = tx.sales_register(c, D, D)
    base = round(sum((-1 if r["ret"] else 1) * r["base"] for r in allr), 2)
    v = __import__("models.reports", fromlist=["x"]).vat_return(c, D, D)
    check("وعاء سجل المبيعات = وعاء الإقرار",
          abs(base - v["sales_base"]) < 0.02, (base, v["sales_base"]))

print("— 5.8.2: مشتريات عامة (كهرباء) والسجل الموحّد")
with db() as c:
    from models import purchases as pu
    el = add_entity(c, "شركة الكهرباء", "supplier",
                    vat_number="300000000000013", username="t")
    net, vat = pu.split_amount(1150, "gross", "standard")
    e1 = pu.create_purchase(c, "expense", el, "كهرباء نوفمبر", net, vat, D,
                            "t", supplier_invoice_no="EL-11",
                            account_code="5820", price_mode="gross",
                            pay_mode="cash", pay_account_id=bank)
    check("فاتورة الكهرباء: صافي 1,000 وضريبة 150 — من البنك",
          (net, vat, e1["total"]) == (1000.0, 150.0, 1150.0)
          and bal(c, "5820")[1] == 1000.0, (net, vat, e1))
    reg = sp.tax_register(c, D, D)
    kinds = [r["kind_label"] for r in reg]
    check("السجل الموحّد: ذهب ومرتجعه والمشتريات النقدية",
          "مشتريات نقدية (مصروف)" in kinds and "مشتريات ذهب ضريبية" in kinds
          and "مرتجع مشتريات ضريبي" in kinds, kinds)
    claim = round(sum((-1 if r["ret"] else 1) * r["claim"] for r in reg), 2)
    v = __import__("models.reports", fromlist=["x"]).vat_return(c, D, D)
    check("ضريبة المدخلات في السجل = ضريبة المدخلات في الإقرار",
          abs(claim - v["input_vat"]) < 0.02, (claim, v["input_vat"]))
    check("حسابات شراء الذهب ليست في قائمة حسابات المصروف",
          not {"5530", "5540", "5545", "5549"}
          & {a["code"] for a in pu.purchase_accounts(c, "expense")})
    hx = __import__("services.print_manager",
                    fromlist=["x"]).build_html("purchase", e1["id"])
    check("قالب فاتورة المصروف: «فاتورة مصروفات ضريبية» والبنك",
          "فاتورة مصروفات ضريبية" in hx and "بنك الراجحي" in hx)
    check("الدفتر متوازن في النهاية", ledger_ok(c)[0], ledger_ok(c))

print()
print(f"{len(OK)} ✔ · {len(BAD)} ✘")
for b in BAD:
    print("  ✘", b)
sys.exit(1 if BAD else 0)
