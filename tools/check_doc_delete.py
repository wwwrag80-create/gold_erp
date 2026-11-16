"""5.7.0: حذف المستند وعكس قيده — ورقمه يتحرّر للمستند التالي.

    python3 tools/check_doc_delete.py

بيع · مرتجع · قبض · صرف · قيد يومي · تسكير: الحذف يعكس الأثر كاملاً
(الأرصدة والأطقم وصندوق الكسر)، ويُحرِّر الرقم فيأخذه أول مستندٍ جديد من
نوعه. والدمج يُلغي المدموجة ويُحرِّر رقمها. وما لا يُحذف نظاماً يُرفض:
الفاتورة الضريبية (تُعكس بمرتجع)، والمستند المعكوس، وحذفٌ يكسر حركة طقم.
وفي آخره: الدفتر متوازن والخزنة = أطقمها.
"""
import datetime
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
T = tempfile.mkdtemp(prefix="ddel_")
os.environ["GOLD_ERP_DATA_DIR"] = T
os.environ["JADEITE_STOCK_GUARD"] = "on"
import config  # noqa: E402

config.DB_PATH = pathlib.Path(T) / "t.db"
import main  # noqa: E402

for _l, f in main.prepare_steps():
    f()
from database.database import db  # noqa: E402
from models import (doc_delete, fixing, inventory, invoices, journal,  # noqa
                    numbering, operations, reversal, stock_guard, vouchers)
from models.accounts import acc_id  # noqa: E402
from models.entities import add_entity  # noqa: E402

OK, BAD = [], []


def check(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print(("  ✔ " if cond else "  ✘ ") + name + ("" if cond else f"  [{info}]"))


D0 = datetime.date.today().isoformat()
D1 = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
U = "t"


def entry_of(c, table, rid):
    return c.execute("SELECT entry_id FROM " + table + " WHERE id=?",
                     (rid,)).fetchone()[0]


def bal(c, code):
    r = c.execute(
        "SELECT ROUND(COALESCE(SUM(l.gold_debit-l.gold_credit),0),3) g,"
        " ROUND(COALESCE(SUM(l.cash_debit-l.cash_credit),0),2) m"
        " FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id"
        " AND e.is_deleted=0 JOIN accounts a ON a.id=l.account_id"
        " WHERE a.code=?", (code,)).fetchone()
    return (r["g"], r["m"])


with db() as c:
    A = add_entity(c, "محل الياسمين", "customer", username=U)
    B = add_entity(c, "محل النخبة", "customer", username=U)
    inventory.create_work_orders_batch(c, [
        {"wo_no": f"{800 + i}", "model_no": "M1", "gold": 10 + i,
         "small_stones": .2, "big_stones": .3, "wage_per_gram": 12}
        for i in range(10)], D1, U)
    W = {r[1]: r[0] for r in c.execute(
        "SELECT id, work_order_no FROM work_orders")}
    s1 = invoices.create_sale(c, A, [{"work_order_id": W["800"]}], D0, U,
                              apply_vat=False)
    s2 = invoices.create_sale(c, A, [{"work_order_id": W["801"]}], D0, U,
                              apply_vat=False)
    s3 = invoices.create_sale(c, A, [{"work_order_id": W["802"]}], D0, U,
                              apply_vat=False)
    r1 = vouchers.create_voucher(c, "receipt", D0, U, entity_id=A, rows=[
        {"kind": "gold", "weight": 5, "karat": 21},
        {"kind": "cash", "amount": 300}])
    r2 = vouchers.create_voucher(c, "receipt", D0, U, entity_id=A, rows=[
        {"kind": "cash", "amount": 100}])
    p1 = vouchers.create_voucher(c, "payment", D0, U, entity_id=B, rows=[
        {"kind": "cash", "amount": 70}])
    j1 = journal.manual_entry(c, D0, "تسوية", [
        {"account_id": acc_id(c, "1400"), "cash_debit": 50},
        {"account_id": acc_id(c, "4200"), "cash_credit": 50}], U)
    fx = fixing.create_fixing(c, A, 3, 200, D0, U)
    START_1400 = bal(c, "1400")
    SCRAP0 = inventory.scrap_actuals(c)

print("── 1) حذف فاتورة مبيعات وتحرير رقمها")
with db(readonly=True) as c:
    n2 = s2["invoice_no"]
    e2 = entry_of(c, "invoices", s2["id"])
    d = doc_delete.describe(c, e2)
check("الوصف: فاتورة مبيعات قابلة للحذف", d["can_delete"] and
      d["kind"] == "sale" and d["no"] == n2, d)
with db() as c:
    res = doc_delete.delete(c, e2, U)
with db(readonly=True) as c:
    st = c.execute("SELECT status FROM work_orders WHERE id=?",
                   (W["801"],)).fetchone()[0]
    gone = c.execute("SELECT is_deleted, invoice_no FROM invoices WHERE"
                     " id=?", (s2["id"],)).fetchone()
    pool = numbering.pooled(c, "S")
check("حُذفت وعاد طقمها للخزنة", res["ok"] and st == "in_stock"
      and gone["is_deleted"] == 1, (st, tuple(gone)))
check("رقمها حُرِّر (والمحذوف يحمل علامة الحذف)",
      pool == [n2] and numbering.RETIRED in gone["invoice_no"],
      (pool, gone["invoice_no"]))
with db() as c:
    s4 = invoices.create_sale(c, B, [{"work_order_id": W["803"]}], D0, U,
                              apply_vat=False)
    s5 = invoices.create_sale(c, B, [{"work_order_id": W["804"]}], D0, U,
                              apply_vat=False)
check("الفاتورة الجديدة تأخذ الرقم المحذوف، والتي بعدها تكمل التسلسل",
      s4["invoice_no"] == n2 and s5["invoice_no"] > s3["invoice_no"],
      (s4["invoice_no"], s5["invoice_no"], s3["invoice_no"]))

print("── 2) سند القبض والصرف")
with db() as c:
    nr1 = r1["voucher_no"]
    doc_delete.delete(c, entry_of(c, "vouchers", r1["id"]), U)
with db(readonly=True) as c:
    scrap = inventory.scrap_actuals(c)
    cash = bal(c, "1400")
check("حذف القبض يعكس النقد وذهب الكسر بعياره",
      abs(scrap.get(21, 0) - (SCRAP0.get(21, 0) - 5)) < 1e-6
      and abs(cash[1] - (START_1400[1] - 300)) < 0.01, (scrap, cash))
with db() as c:
    r3 = vouchers.create_voucher(c, "receipt", D0, U, entity_id=B, rows=[
        {"kind": "cash", "amount": 40}])
    p2 = vouchers.create_voucher(c, "payment", D0, U, entity_id=B, rows=[
        {"kind": "cash", "amount": 10}])
check("سند القبض الجديد يأخذ رقم المحذوف — والصرف دفتره مستقل",
      r3["voucher_no"] == nr1 and p2["voucher_no"] != nr1
      and p2["voucher_no"].startswith("PV-"),
      (r3["voucher_no"], p2["voucher_no"]))
with db() as c:
    np1 = p1["voucher_no"]
    doc_delete.delete(c, entry_of(c, "vouchers", p1["id"]), U)
    p3 = vouchers.create_voucher(c, "payment", D0, U, entity_id=B, rows=[
        {"kind": "cash", "amount": 5}])
check("وحذف الصرف يُعطي رقمه لأول صرفٍ جديد", p3["voucher_no"] == np1,
      (p3["voucher_no"], np1))

print("── 3) القيد اليومي والتسكير")
with db() as c:
    nj = c.execute("SELECT doc_no FROM journal_entries WHERE id=?",
                   (j1,)).fetchone()[0]
    doc_delete.delete(c, j1, U)
    j2 = journal.manual_entry(c, D0, "قيد جديد", [
        {"account_id": acc_id(c, "1400"), "cash_debit": 7},
        {"account_id": acc_id(c, "4200"), "cash_credit": 7}], U)
    nj2 = c.execute("SELECT doc_no FROM journal_entries WHERE id=?",
                    (j2,)).fetchone()[0]
check("القيد الجديد يأخذ رقم القيد المحذوف", nj2 == nj, (nj, nj2))
with db() as c:
    fe = entry_of(c, "fixing_ops", fx["id"])
    fno = fx["op_no"]
    doc_delete.delete(c, fe, U)
    fx2 = fixing.create_fixing(c, B, 2, 210, D0, U)
    gone = c.execute("SELECT is_deleted FROM fixing_ops WHERE id=?",
                     (fx["id"],)).fetchone()[0]
check("حذف التسكير وتحرير رقمه", gone == 1 and fx2["op_no"] == fno,
      (gone, fx2["op_no"], fno))

print("── 4) ما لا يُحذف")
with db() as c:
    sv = invoices.create_sale(c, B, [{"work_order_id": W["805"]}], D0, U,
                              apply_vat=True)
    ev = entry_of(c, "invoices", sv["id"])
    dv = doc_delete.describe(c, ev)
check("الفاتورة الضريبية لا تُحذف — تُعكس بمرتجع", not dv["can_delete"]
      and dv["can_reverse"] and "ضريبية" in dv["why"], dv)
try:
    with db() as c:
        doc_delete.delete(c, ev, U)
    refused = False
except ValueError:
    refused = True
check("ومحاولة حذفها تُرفض ولا يتغيّر شيء", refused)
with db() as c:
    out = doc_delete.reverse_vat(c, ev, U)
    rv = reversal.reversal_of(c, ev)
check("وعكسها بمرتجعٍ يشير إليها", out["ok"] and rv is not None, out)
# مستندٌ (غير ضريبي) عُكس بمستندٍ آخر: لا يُحذف قبل مستند عكسه، وحذفُ
# مستند العكس يُعيد الأصل سارياً
with db() as c:
    vr = vouchers.create_voucher(c, "receipt", D0, U, entity_id=B, rows=[
        {"kind": "cash", "amount": 25}])
    evr = entry_of(c, "vouchers", vr["id"])
    reversal.reverse(c, evr, U)
    rrow = reversal.reversal_of(c, evr)
    dv2 = doc_delete.describe(c, evr)
check("المستند المعكوس لا يُحذف قبل مستند عكسه",
      not dv2["can_delete"] and "عُكس" in dv2["why"], dv2)
with db() as c:
    out2 = doc_delete.delete(c, rrow["rev_entry_id"], U)
    back = reversal.reversal_of(c, evr) is None
    dv3 = doc_delete.describe(c, evr)
check("وحذف مستند العكس يعيد الأصل سارياً قابلاً للحذف",
      out2["ok"] and back and dv3["can_delete"], (out2, dv3))
# حذفٌ يكسر حركة طقم: بيعٌ ثم مرتجع — حذف البيع يترك مرتجعاً بلا بيع
with db() as c:
    s6 = invoices.create_sale(c, B, [{"work_order_id": W["806"]}], D0, U,
                              apply_vat=False)
    invoices.create_sale_return(c, B, [{"work_order_id": W["806"]}], D0, U,
                                apply_vat=False)
    e6 = entry_of(c, "invoices", s6["id"])
try:
    with db() as c:
        doc_delete.delete(c, e6, U)
    msg = ""
except ValueError as e:
    msg = str(e)
with db(readonly=True) as c:
    alive = c.execute("SELECT is_deleted FROM invoices WHERE id=?",
                      (s6["id"],)).fetchone()[0] == 0
    no_pool = s6["invoice_no"] not in numbering.pooled(c, "S")
check("حذفٌ يجعل حركة الطقم غير منتظمة يُرفض كله بأسماء الأطقم",
      "806" in msg and alive and no_pool, msg)

print("── 5) الدمج")
with db() as c:
    m1 = invoices.create_sale(c, A, [{"work_order_id": W["807"]}], D0, U,
                              apply_vat=False)
    m2 = invoices.create_sale(c, A, [{"work_order_id": W["808"]}], D0, U,
                              apply_vat=False)
    a_before = c.execute(
        "SELECT ROUND(SUM(l.gold_debit-l.gold_credit),3) FROM journal_lines"
        " l JOIN journal_entries e ON e.id=l.entry_id AND e.is_deleted=0"
        " JOIN entities n ON n.account_id=l.account_id WHERE n.id=?",
        (A,)).fetchone()[0]
    mres = operations.merge_invoices(c, [m1["id"], m2["id"]], U)
    a_after = c.execute(
        "SELECT ROUND(SUM(l.gold_debit-l.gold_credit),3) FROM journal_lines"
        " l JOIN journal_entries e ON e.id=l.entry_id AND e.is_deleted=0"
        " JOIN entities n ON n.account_id=l.account_id WHERE n.id=?",
        (A,)).fetchone()[0]
    items = c.execute("SELECT COUNT(*) FROM invoice_items WHERE"
                      " invoice_id=?", (m1["id"],)).fetchone()[0]
    m2row = c.execute("SELECT is_deleted FROM invoices WHERE id=?",
                      (m2["id"],)).fetchone()[0]
    st8 = c.execute("SELECT status FROM work_orders WHERE id=?",
                    (W["808"],)).fetchone()[0]
check("الدمج: الأولى تحمل البندين، والأخيرة أُلغيت، والذمّة كما هي",
      items == 2 and m2row == 1 and a_before == a_after and st8 == "sold"
      and mres["freed"] == [m2["invoice_no"]], (items, m2row, a_before,
                                                a_after, st8, mres))
with db() as c:
    m3 = invoices.create_sale(c, B, [{"work_order_id": W["809"]}], D0, U,
                              apply_vat=False)
check("وأول فاتورة مبيعاتٍ بعده تأخذ رقم المدموجة",
      m3["invoice_no"] == m2["invoice_no"], (m3["invoice_no"],
                                             m2["invoice_no"]))

print("── 6) السلامة")
with db(readonly=True) as c:
    g = c.execute("SELECT ROUND(SUM(gold_debit-gold_credit),3),"
                  " ROUND(SUM(cash_debit-cash_credit),2) FROM journal_lines l"
                  " JOIN journal_entries e ON e.id=l.entry_id WHERE"
                  " e.is_deleted=0").fetchone()
    rep = stock_guard.report(c)
    dup = c.execute("SELECT invoice_no, COUNT(*) FROM invoices WHERE"
                    " is_deleted=0 GROUP BY invoice_no HAVING COUNT(*)>1"
                    ).fetchall()
    logs = c.execute("SELECT COUNT(*) FROM audit_log WHERE"
                     " action='delete_doc'").fetchone()[0]
check("الدفتر متوازن", tuple(g) == (0.0, 0.0), tuple(g))
check("الخزنة = أطقمها", not rep["broken"]
      and abs((rep["worked"] or {}).get("diff", 0)) < 0.001, rep)
check("لا رقم فاتورة مكرّر بين القائمة", not dup, dup)
check("كل حذفٍ في سجل التتبع", logs >= 5, logs)

print()
print(f"{len(OK)} ✔ · {len(BAD)} ✘")
for b in BAD:
    print("  ✘", b)
sys.exit(1 if BAD else 0)
