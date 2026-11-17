"""5.8.4: أنواع جهات التعامل التي يُنشئها المستخدم.

    python3 tools/check_entity_types.py

نوعٌ جديد («مكاتب الصيانة» مدينون لنا، و«شركات الشحن» دائنون لنا) يصير
رسمياً في كل مكان: حسابٌ رقابي في الشجرة تحت 1030 أو 2010 وجهاتُه فروعٌ
تحته بكودٍ من كوده، واسمه يظهر بجانب جهاته، وسطرٌ له في الميزانية، ويُقرأ
في القوائم المالية كالعملاء أو كالموردين، وتنتقل الجهة بينه وبين العميل
والجهة الأخرى، والسقف الائتماني يحرسه.
"""
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
T = tempfile.mkdtemp(prefix="etypes_")
os.environ["GOLD_ERP_DATA_DIR"] = T
import config  # noqa: E402

config.DB_PATH = pathlib.Path(T) / "t.db"
import main  # noqa: E402
from database.database import db  # noqa: E402

for _l, f in main.prepare_steps():
    f()
from models import entities, entity_types as et, reports, journal  # noqa: E402
from models.accounts import acc_id  # noqa: E402
from services.accounting_engine import account_balance, post_entry  # noqa: E402

OK, BAD = [], []


def check(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print(("  ✔ " if cond else "  ✘ ") + name + ("" if cond else f"  [{info}]"))


def raises(fn, needle=""):
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        return needle in str(e)
    return False


print("── إنشاء نوعٍ جديد")
with db() as c:
    shop = et.create(c, "مكاتب الصيانة", "مكتب صيانة", "asset", "both", "t")
    ship = et.create(c, "شركات الشحن", "شركة شحن", "liability", "cash", "t")
    ctrl = c.execute("SELECT * FROM accounts WHERE id=?",
                     (et.get(shop)["account_id"],)).fetchone()
    ctrl2 = c.execute("SELECT * FROM accounts WHERE id=?",
                      (et.get(ship)["account_id"],)).fetchone()
    par = c.execute("SELECT code FROM accounts WHERE id=?",
                    (ctrl["parent_id"],)).fetchone()["code"]
    par2 = c.execute("SELECT code FROM accounts WHERE id=?",
                     (ctrl2["parent_id"],)).fetchone()["code"]
check("مفتاحان مستقلان", shop.startswith("x_") and ship.startswith("x_")
      and shop != ship, (shop, ship))
check("حسابٌ رقابي «إجمالي مكاتب الصيانة» تحت الذمم المدينة 1030 (تجميعي)",
      ctrl["name"] == "إجمالي مكاتب الصيانة" and par == "1030"
      and ctrl["is_postable"] == 0 and ctrl["type"] == "asset"
      and ctrl["code"].startswith("1030"), dict(ctrl))
check("والدائن تحت الخصوم المتداولة 2010 بطبيعة دائنة ونقدٍ فقط",
      par2 == "2010" and ctrl2["type"] == "liability"
      and ctrl2["nature"] == "credit" and ctrl2["balance_type"] == "cash",
      dict(ctrl2))
check("اسم النوع في القواميس كالأنواع الثابتة",
      entities.TYPE_LABELS[shop] == "مكتب صيانة"
      and entities.PLURALS[shop] == "مكاتب الصيانة"
      and entities.TYPE_LABELS.get(ship) == "شركة شحن"
      and shop in entities.TYPE_LABELS
      and entities.TYPE_LABELS.get("x_404", "؟") == "؟")
check("في قائمة الأنواع بعد الثابتة", [t for t, _ in entities.all_types()][-2:]
      == [shop, ship])
check("والأنواع التجارية تشمله", shop in entities.trade_types()
      and ship in entities.trade_types())
with db() as c:
    check("لا يتكرّر اسم نوع", raises(
        lambda: et.create(c, "مكاتب الصيانة", side="asset"), "يوجد"))
    check("ولا يُنشأ باسم نوعٍ ثابت", raises(
        lambda: et.create(c, "العملاء", side="asset"), "يوجد"))

print("── جهاتٌ تحت النوع")
with db() as c:
    a = entities.add_entity(c, "مكتب الأمل", shop, phone="055",
                            username="t", open_cash=500, open_gold=10)
    b = entities.add_entity(c, "سمسا", ship, username="t", open_cash=-300)
    ea, eb = entities.get_entity(c, a), entities.get_entity(c, b)
    acc_a = c.execute("SELECT * FROM accounts WHERE id=?",
                      (ea["account_id"],)).fetchone()
    acc_b = c.execute("SELECT * FROM accounts WHERE id=?",
                      (eb["account_id"],)).fetchone()
    ga, ca = account_balance(c, ea["account_id"])
check("حساب الجهة تحت حساب نوعه بكودٍ من كوده واسمه «مكتب صيانة: مكتب الأمل»",
      acc_a["parent_id"] == ctrl["id"] and acc_a["code"].startswith(
          ctrl["code"]) and acc_a["name"] == "مكتب صيانة: مكتب الأمل"
      and acc_a["is_postable"] == 1 and acc_a["balance_type"] == "both",
      dict(acc_a))
check("والرصيد الافتتاحي قُيِّد (500 ريال و10 جم)", round(ca, 2) == 500
      and round(ga, 3) == 10, (ga, ca))
check("جهة الشحن تحت حساب نوعها نقداً فقط", acc_b["parent_id"] == ctrl2["id"]
      and acc_b["balance_type"] == "cash" and acc_b["type"] == "liability")
with db(readonly=True) as c:
    d = entities.directory(c, (shop,))
    ids = {e["id"] for e in entities.list_customers(c)}
check("الدليل يعرضها بنوعها ومجموعتها", len(d) == 1 and d[0]["type"] == shop
      and "إجمالي مكاتب الصيانة" in d[0]["group"] and d[0]["cash"] == 500, d)
check("وتظهر في قوائم الشاشات التجارية", a in ids and b in ids)
with db() as c:
    check("لا يتكرّر الاسم داخل النوع", raises(
        lambda: entities.add_entity(c, "مكتب الامل", shop, username="t"),
        "يوجد"))

print("── الميزانية والقوائم")
with db(readonly=True) as c:
    bs = reports.balance_sheet(c)
    lines = {n: (v, g) for n, v, g in bs["assets"] + bs["liabilities"]}
check("سطرٌ مستقل للنوع المدين في الأصول (500 ريال · 10 جم)",
      lines.get("أرصدة مكاتب الصيانة المدينة") == (500.0, 10.0),
      lines.get("أرصدة مكاتب الصيانة المدينة"))
check("وللدائن في الخصوم (300 ريال)",
      lines.get("أرصدة شركات الشحن الدائنة") == (300.0, 0.0),
      lines.get("أرصدة شركات الشحن الدائنة"))
check("والميزانية متوازنة", bs["balanced_cash"] and bs["balanced_gold"],
      (bs["diff_cash"], bs["diff_gold"]))
from models import statements  # noqa: E402
with db(readonly=True) as c:
    rows = {r["id"]: r for r in c.execute("SELECT * FROM accounts")}
check("القوائم المالية تقرأ النوع المدين كالعملاء والدائن كالموردين",
      statements._classify(rows[acc_a["id"]], rows) == "party_customer"
      and statements._classify(rows[acc_b["id"]], rows) == "party_supplier")

print("── نقل الجهة بين الأنواع")
with db() as c:
    cid = entities.add_entity(c, "عميل يصير مكتباً", "customer", username="t")
    res = entities.change_entity_type(c, cid, shop, "t")
    e = entities.get_entity(c, cid)
    acc = c.execute("SELECT * FROM accounts WHERE id=?",
                    (e["account_id"],)).fetchone()
check("عميلٌ ينتقل إلى النوع الجديد ويتبعه حسابه واسمه",
      res["changed"] and e["entity_type"] == shop
      and acc["parent_id"] == ctrl["id"]
      and acc["name"] == "مكتب صيانة: عميل يصير مكتباً", dict(acc))
with db() as c:
    res2 = entities.change_entity_type(c, cid, "other", "t")
    e = entities.get_entity(c, cid)
check("ويعود إلى «جهة أخرى»", res2["changed"] and e["entity_type"] == "other")
with db() as c:
    check("ولا يُنقل إليه موظف (بنية مختلفة)", raises(
        lambda: entities.change_entity_type(
            c, entities.add_entity(c, "موظف س", "employee", username="t",
                                   basic_salary=3000), shop, "t"),
        "لا يُنقل"))

print("── نقل الحساب في الشجرة يتبعه النوع")
with db() as c:
    oid = entities.add_entity(c, "جهة تُنقل في الشجرة", "other", username="t")
    from models import coa
    coa.move_account(c, entities.get_entity(c, oid)["account_id"],
                     ctrl["id"], "t", entity_ok=True)
    out = entities.sync_types_from_tree(
        c, [entities.get_entity(c, oid)["account_id"]], "t")
    e = entities.get_entity(c, oid)
check("حسابٌ نُقل تحت «إجمالي مكاتب الصيانة» صارت جهته منه",
      e["entity_type"] == shop, (e["entity_type"], out))

print("── القيود والتعديل والكشف")
with db() as c:
    post_entry(c, "2026-01-05", "بيع لمكتب", [
        {"account_id": entities.get_entity(c, a)["account_id"],
         "cash_debit": 200},
        {"account_id": acc_id(c, "1400"), "cash_credit": 200}],
        source_table="test", source_id=1, username="t")
    entities.update_entity(c, a, "t", name="مكتب الأمل الجديد")
    e = entities.get_entity(c, a)
    acc = c.execute("SELECT name FROM accounts WHERE id=?",
                    (e["account_id"],)).fetchone()
    g, cc = account_balance(c, e["account_id"])
check("التعديل يعيد تسمية حسابه ببادئ نوعه",
      acc["name"] == "مكتب صيانة: مكتب الأمل الجديد", acc["name"])
check("وقيدٌ عليه يُرحَّل (700 ريال)", round(cc, 2) == 700, cc)

print("── بعد إعادة التشغيل (القاعدة نفسها)")
et._CACHE["rows"] = None
check("الأنواع تُقرأ من القاعدة", entities.TYPE_LABELS[shop] == "مكتب صيانة"
      and set(et.codes()) == {shop, ship})

print(f"\n{len(OK)} ✔ · {len(BAD)} ✘")
sys.exit(1 if BAD else 0)
