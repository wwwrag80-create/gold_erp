# اختبار 5.2.0: حساب «ايطالي / نواعم» (1210)، فصل الفاتورة، التوريد، الترقية — python3 tools/check_italian.py
import sys, os, tempfile, pathlib  # noqa: E401
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
T = tempfile.mkdtemp(prefix="t520_")
import config
config.DB_PATH = pathlib.Path(T) / "t.db"
from database.database import create_tables, db, migrate_schema, run_migrations_files
from database.seed import ensure_new_accounts, ensure_system_tags, seed_initial_data
from models.entities import ensure_employee_accrual_accounts, ensure_internal_counterparties, add_entity
from models.accounts import acc_id
from models import invoices, inventory, italian
ok = bad = 0
def check(n, c, d=""):
    global ok, bad
    if c: ok += 1; print("  ✔", n)
    else: bad += 1; print("  ✘", n, d)
create_tables(); migrate_schema(); run_migrations_files(); seed_initial_data(); ensure_new_accounts()
with db() as conn:
    ensure_internal_counterparties(conn); ensure_employee_accrual_accounts(conn); ensure_system_tags(conn)
def bal(conn, code):
    r = conn.execute("SELECT COALESCE(SUM(l.gold_debit),0)-COALESCE(SUM(l.gold_credit),0) b FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id WHERE e.is_deleted=0 AND l.account_id=?", (acc_id(conn, code),)).fetchone()
    return round(r["b"], 3)
def balanced(conn):
    r = conn.execute("SELECT ROUND(SUM(gold_debit)-SUM(gold_credit),3) g, ROUND(SUM(cash_debit)-SUM(cash_credit),2) c FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id WHERE e.is_deleted=0").fetchone()
    return abs(r["g"] or 0) < 0.001 and abs(r["c"] or 0) < 0.01
with db() as conn:
    check("حساب 1210 في الشجرة تحت 1020", conn.execute("SELECT 1 FROM accounts a JOIN accounts p ON p.id=a.parent_id WHERE a.code='1210' AND p.code='1020' AND a.is_postable=1").fetchone() is not None)
    cust = add_entity(conn, "عميل الاختبار", "customer", username="t")
    cid = cust if isinstance(cust, int) else cust["id"]
    b = inventory.create_work_orders_batch(conn, [
        {"wo_no": "A100", "gold": 20, "small_stones": 0, "big_stones": 0, "wage_per_gram": 10},
        {"wo_no": "A101", "gold": 15, "small_stones": 0, "big_stones": 0, "wage_per_gram": 10},
        {"wo_no": "00010", "gold": 50, "small_stones": 0, "big_stones": 0, "wage_per_gram": 5},
        {"wo_no": "0010", "gold": 30, "small_stones": 0, "big_stones": 0, "wage_per_gram": 5}],
        "2026-11-01", "t")
    check("توريد مختلط: المشغول 35 والإيطالي 80", bal(conn, "1200") == 35 and bal(conn, "1210") == 80, (bal(conn,"1200"), bal(conn,"1210")))
    check("وخزينة التصنيع دائنة 115", bal(conn, "1100") == -115, bal(conn, "1100"))
    check("وجهة الدفعة ما زالت الذهب المشغول", inventory.batch_dest_line(conn, b["entry_id"])["code"] == "1200")
    wo = {r["work_order_no"]: r["id"] for r in conn.execute("SELECT id, work_order_no FROM work_orders")}
    res = invoices.create_sale(conn, cid, [
        {"work_order_id": wo["A100"]}, {"work_order_id": wo["00010"], "weight": 12},
        {"work_order_id": wo["0010"], "weight": 8},
        {"wage_only": True, "amount": 25}], "2026-11-02", "t", apply_vat=False)
    sp = res.get("split")
    check("بيع مختلط ⇒ فاتورتان", bool(sp) and sp["invoice_no"] != res["invoice_no"], res.get("invoice_no"))
    check("فاتورة الأطقم: 20 جم من المشغول + أجر فقط", res["total_weight"] == 20, res["total_weight"])
    check("فاتورة الإيطالي: 20 جم من حساب 1210", sp and sp["total_weight"] == 20 and "1210" in sp["source_name"], sp and sp["source_name"])
    check("المشغول 35−20=15 · الإيطالي 80−20=60", bal(conn, "1200") == 15 and bal(conn, "1210") == 60, (bal(conn,"1200"), bal(conn,"1210")))
    lines = conn.execute("SELECT a.code FROM journal_lines l JOIN accounts a ON a.id=l.account_id WHERE l.entry_id=?", (res["entry_id"],)).fetchall()
    check("قيد فاتورة الأطقم لا يمسّ 1210", all(r["code"] != "1210" for r in lines))
    lines = conn.execute("SELECT a.code FROM journal_lines l JOIN accounts a ON a.id=l.account_id WHERE l.entry_id=?", (sp["entry_id"],)).fetchall()
    check("وقيد فاتورة الإيطالي لا يمسّ 1200", all(r["code"] != "1200" for r in lines))
    cards = {c["no"]: c["balance"] for c in italian.cards(conn)}
    check("البطاقتان: 00010=38 · 0010=22 (=رصيد 1210)", cards.get("00010") == 38 and cards.get("0010") == 22 and round(sum(cards.values()),3) == bal(conn, "1210"), cards)
    r2 = invoices.create_sale_return(conn, cid, [
        {"work_order_id": wo["A100"]}, {"work_order_id": wo["00010"], "weight": 5}], "2026-11-03", "t", apply_vat=False)
    check("مرتجع مختلط ⇒ فاتورتان: الأطقم إلى المشغول والإيطالي إلى 1210", bool(r2.get("split")) and bal(conn, "1200") == 35 and bal(conn, "1210") == 65, (bal(conn,"1200"), bal(conn,"1210")))
    r3 = invoices.create_sale(conn, cid, [{"work_order_id": wo["0010"], "weight": 2}], "2026-11-04", "t", apply_vat=False)
    check("فاتورة إيطالي وحده: فاتورةٌ واحدة رأسها حساب 1210", not r3.get("split") and "1210" in r3["source_name"] and bal(conn, "1210") == 63, r3["source_name"])
    r4 = invoices.create_sale(conn, cid, [{"work_order_id": wo["A101"]}], "2026-11-04", "t", apply_vat=False)
    check("فاتورة أطقم وحدها: من المشغول", not r4.get("split") and bal(conn, "1200") == 20, bal(conn, "1200"))
    # تعديل التوريد: 00010 من 50 إلى 40، وإضافة طقم
    rows = inventory._batch_rows(conn, b["entry_id"])
    for r in rows:
        if r["wo_no"] == "00010": r["gold"] = 40
    rows.append({"wo_no": "A102", "gold": 7, "small_stones": 0, "big_stones": 0, "wage_per_gram": 10})
    inventory.update_supply_batch(conn, b["entry_id"], rows, "2026-11-01", "t")
    check("تعديل التوريد: الإيطالي −10 = 53 · المشغول +7 = 27", bal(conn, "1210") == 53 and bal(conn, "1200") == 27, (bal(conn,"1200"), bal(conn,"1210")))
    cards = {c["no"]: c["balance"] for c in italian.cards(conn)}
    check("ورصيد 1210 = البطاقتين", round(sum(cards.values()),3) == bal(conn, "1210"), (cards, bal(conn, "1210")))
    # تعديل فاتورة الإيطالي: 12 ← 10
    it = conn.execute("SELECT id FROM invoice_items WHERE invoice_id=? AND work_order_id=?", (sp["id"], wo["00010"])).fetchone()["id"]
    it2 = conn.execute("SELECT id FROM invoice_items WHERE invoice_id=? AND work_order_id=?", (sp["id"], wo["0010"])).fetchone()["id"]
    invoices.update_invoice(conn, sp["id"], [{"work_order_id": wo["00010"], "weight": 10, "item_id": it}, {"work_order_id": wo["0010"], "weight": 8, "item_id": it2}], "t", apply_vat=False)
    cards = {c["no"]: c["balance"] for c in italian.cards(conn)}
    check("تعديل فاتورة الإيطالي: 1210 = 55 = البطاقتين", bal(conn, "1210") == 55 and round(sum(cards.values()),3) == 55, (cards, bal(conn, "1210")))
    check("القيود متوازنة ذهباً ونقداً", balanced(conn))
    # رصيد افتتاحي مختلط
    inventory.opening_stock_batch(conn, [{"wo_no": "A200", "gold": 9, "small_stones": 0, "big_stones": 0}, {"wo_no": "00010", "gold": 4, "small_stones": 0, "big_stones": 0}], "2026-11-05", "t")
    check("رصيد افتتاحي مختلط: المشغول +9 والإيطالي +4", bal(conn, "1200") == 36 and bal(conn, "1210") == 59, (bal(conn,"1200"), bal(conn,"1210")))
    st = italian.statement(conn)
    check("كشف الإيطالي بلا فرق غير مفصّل", abs(st["gap"]) < 0.005, st["gap"])

# ══ الترقية: قاعدةٌ قديمة (كل شيء في 1200) ══
print("— الترقية —")
with db() as conn:
    from models.fiscal import set_setting
    ita = acc_id(conn, "1210"); fin = acc_id(conn, "1200")
    # نُرجع القاعدة كأنها قبل 5.2.0: سطور 1210 إلى 1200، وبنود الفواتير بلا حساب
    conn.execute("UPDATE journal_lines SET account_id=? WHERE account_id=?", (fin, ita))
    conn.execute("UPDATE invoice_items SET stock_account_id=NULL WHERE work_order_id IN (SELECT id FROM work_orders WHERE is_bulk=1)")
    conn.execute("UPDATE invoices SET source_account_id=? WHERE source_account_id=?", (fin, ita))
    # رصيدٌ قديم بلا مستندات: +6 على البطاقة وعلى المشغول
    conn.execute("UPDATE work_orders SET registered_weight=registered_weight+6 WHERE work_order_no='0010'")
    from services.accounting_engine import post_entry
    post_entry(conn, "2026-10-01", "رصيد قديم", [{"account_id": fin, "gold_debit": 6}, {"account_id": acc_id(conn, "3900"), "gold_credit": 6}], username="t")
    conn.execute("DELETE FROM app_settings WHERE key=?", (italian.MIGRATION_KEY,))
    before_total = bal(conn, "1200") + bal(conn, "1210")
    check("قبل الترقية: 1210 صفر", bal(conn, "1210") == 0)
    out = italian.migrate(conn, "t", today="2026-11-05")
    print("   ", out)
    cards = {c["no"]: c["balance"] for c in italian.cards(conn)}
    check("بعد الترقية: 1210 = البطاقتين", bal(conn, "1210") == round(sum(cards.values()), 3), (bal(conn, "1210"), cards))
    check("والمجموع لم يتغيّر (المشغول + الإيطالي)", round(bal(conn, "1200") + bal(conn, "1210"), 3) == round(before_total, 3))
    check("والمشغول = الأطقم وحدها (36)", bal(conn, "1200") == 36, bal(conn, "1200"))
    check("والتحويل الظاهر = الرصيد القديم 6 (والتوريد والافتتاحي نُقلا بتاريخهما)", abs(out["transfer"] - 6) < 0.001 and out["entries"] == 2, out)
    check("ومرةً واحدة فقط", italian.migrate(conn, "t") is None)
    check("القيود متوازنة بعد الترقية", balanced(conn))
print(f"\n{'✔' if not bad else '✘'} {ok} نجح · {bad} فشل")
sys.exit(1 if bad else 0)
