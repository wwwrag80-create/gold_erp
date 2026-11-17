"""شاشتا المبيعات والمشتريات الضريبية بالضغط على الأزرار نفسها (5.8.4).

    python3 tools/check_tax_screens_ui.py [مجلد_للصور]

يبني الشاشات فعلاً (Qt بلا نافذة) ويُدخل ويُرحّل كما يفعل المستخدم:
* المشتريات: فاتورة ذهب، ومرتجع، والمشتريات النقدية بخانة «العملية» الملوّنة
  (مشتريات أخضر · مرتجع أحمر) على أي حساب — حتى جهةٍ من نوعٍ أنشأه المستخدم.
* المبيعات: فاتورة على حسابٍ أيّاً كان نوعه، والسجل وزرّ «بحث».
* «+ جديد» في خانة الحساب: نوع الجهة يُختار (ومنه نوعٌ جديد).
* التكويد الموحّد: «+ نوع جهة جديد» ثم جهةٌ تحته.
* خانة الدفع اختيارٌ فقط، وسندات القبض/الصرف.
ثم الدفتر متوازن، ولا رسالة خطأ في الواجهة.
"""
import datetime
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
T = tempfile.mkdtemp(prefix="taxui_")
os.environ["GOLD_ERP_DATA_DIR"] = T
os.environ["QT_QPA_PLATFORM"] = "offscreen"
OUT = sys.argv[1] if len(sys.argv) > 1 else ""
import config  # noqa: E402

config.DB_PATH = pathlib.Path(T) / "t.db"
config.COMPANY_VAT_NUMBER = "300000000000003"
import main  # noqa: E402

for _l, f in main.prepare_steps():
    f()
from database.database import db  # noqa: E402
from models import entities, entity_types as et  # noqa: E402

with db() as c:
    C = entities.add_entity(c, "شركة الريان", "customer",
                            vat_number="311111111111113", username="t")
    S1 = entities.add_entity(c, "مورد أ", "supplier",
                             vat_number="322222222222223", username="t")
    OT = entities.add_entity(c, "جهة الأمانة", "other", username="t",
                             vat_number="333333333333333")
    SHOP = et.create(c, "مكاتب الصيانة", "مكتب صيانة", "asset", "both", "t")
    M1 = entities.add_entity(c, "مكتب الأمل", SHOP, username="t",
                             vat_number="344444444444443")

from PyQt5 import QtCore, QtTest, QtWidgets  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
try:
    # مظهر البرنامج نفسه (الاتجاه من اليمين والخط والأنماط) — كما يراه المستخدم
    from ui import theme
    theme.apply(app)
except Exception as e:  # noqa: BLE001
    print("theme", e)
    app.setLayoutDirection(QtCore.Qt.RightToLeft)

OK, BAD, MSGS = [], [], []


def ok(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print(("  ✔ " if cond else "  ✘ ") + name + ("" if cond else f"  [{info}]"))


def snap(w, name, h=860):
    if not OUT:
        return
    w.resize(1366, h)
    w.show()
    QtTest.QTest.qWait(250)
    w.grab().save(f"{OUT}/{name}.png")


import ui.widgets.common as common  # noqa: E402

common.confirm_post = lambda *a, **k: True
common.confirm_doc_date = lambda *a, **k: True
_PREV = []
for mod in ("ui.tax_sets_sales", "ui.tax_purchases_screen",
            "ui.purchases_screen", "ui.entities_screen", "ui.vouchers_screen",
            "ui.tax_sales_screen", "ui.entity_type_dialog"):
    m = __import__(mod, fromlist=["x"])
    for nm in ("confirm_post", "confirm_doc_date"):
        if hasattr(m, nm):
            setattr(m, nm, lambda *a, **k: True)
    if hasattr(m, "posted"):
        m.posted = lambda w, msg, *a, **k: MSGS.append(str(msg))
    if hasattr(m, "err"):
        m.err = lambda w, e, *a, **k: MSGS.append("ERR: " + str(e))
    if hasattr(m, "info"):
        m.info = lambda w, msg, *a, **k: MSGS.append(str(msg))
    if hasattr(m, "ask"):
        m.ask = lambda *a, **k: True

user = {"username": "t", "role": "admin", "full_name": "t"}
from ui import tax_trade_kit as tk  # noqa: E402
from ui.tax_purchases_screen import TaxPurchasesScreen  # noqa: E402
from ui.tax_sales_screen import TaxSalesScreen  # noqa: E402

app.processEvents()

print("— المشتريات الضريبية")
pw = TaxPurchasesScreen(user)
pw.resize(1366, 860)
pw.show()
app.processEvents()
tabs = [pw.tabs.tabText(i) for i in range(pw.tabs.count())]
ok("الأقسام: ذهب · مرتجع · «المشتريات النقدية» · السجل",
   len(tabs) == 4 and "المشتريات النقدية" in tabs[2]
   and not any("العامة" in t for t in tabs), tabs)
inv = pw.inv_tab
inv.reload()
app.processEvents()
items = [inv.supplier.itemText(i) for i in range(inv.supplier.count())]
ok("خانة الحساب: كل الأنواع بنوعها بجانب الاسم (ومنها النوع الجديد)",
   any("مورد أ  ·  مورد" in x for x in items)
   and any("شركة الريان  ·  عميل" in x for x in items)
   and any("مكتب الأمل  ·  مكتب صيانة" in x for x in items), items)
ok("خانة الدفع اختيارٌ فقط بزر «+ إضافة»", not inv.pay.cb.isEditable()
   and inv.pay.b_add.text() == "+ إضافة")
inv.supplier.setCurrentIndex(inv.supplier.findData(M1))
inv.sup_inv.setText("M-1")
inv.e_wo.setText("BC-1")
inv.e_reg.setValue(20.0)
inv.e_rate.setValue(10)
ok("سطر شراء", inv.add_item())
snap(pw, "w_pur")
inv.post()
app.processEvents()
ok("شراء ذهب من «مكتب صيانة» (نوعٌ أنشأه المستخدم)",
   MSGS and not MSGS[-1].startswith("ERR"), MSGS[-1:])

print("— المشتريات النقدية")
pw.tabs.setCurrentIndex(2)
app.processEvents()
gen = pw.gen_tab
ok("قسم المشتريات النقدية يُفتح", gen is not None)
gen.refresh()
op_items = [gen.op.itemText(i) for i in range(gen.op.count())]
ok("خانة «العملية» واحدة: مشتريات · مرتجع مشتريات",
   op_items == ["🧾  مشتريات", "↩  مرتجع مشتريات"], op_items)
ok("المشتريات بالأخضر", "#1F8A4C" in gen.op.styleSheet()
   and gen.box_head.title() == "① فاتورة مشتريات", gen.op.styleSheet()[:80])
gitems = [gen.supplier.itemText(i) for i in range(gen.supplier.count())]
ok("حساب المشتريات النقدية: أي نوع (عميل · مورد · جهة · النوع الجديد)",
   any("شركة الريان" in x for x in gitems)
   and any("مكتب الأمل" in x for x in gitems)
   and any("جهة الأمانة" in x for x in gitems), gitems)
gen.supplier.setCurrentIndex(gen.supplier.findData(OT))
gen.inv_no.setText("E-1")
gen.desc.setText("صيانة المكائن")
gen.l_price.setValue(200)
gen.add_line()
snap(pw, "w_gen")
gen.save_purchase()
app.processEvents()
ok("شراء نقدي على «جهة أخرى» يُرحَّل", MSGS
   and not MSGS[-1].startswith("ERR"), MSGS[-1:])
gen.op.setCurrentIndex(1)
app.processEvents()
ok("المرتجع بالأحمر وعنوانه وزرّه", "#C0392B" in gen.op.styleSheet()
   and gen.box_head.title() == "① مرتجع مشتريات"
   and "مرتجع" in gen.btn_save.text() and gen.doc_hint.isVisible(),
   (gen.box_head.title(), gen.btn_save.text()))
snap(pw, "w_gen_ret")
gen.op.setCurrentIndex(0)
gen.tabs.setCurrentIndex(1)
gen.r_from.setDate(QtCore.QDate(2000, 1, 1))
gen.refresh_register()
ok("سجل ضريبة المدخلات: صفّ التاريخين والزرّين بارتفاعٍ واحد",
   len({w.height() for w in (gen.r_from, gen.r_to)}) == 1
   and gen.reg.rowCount() >= 1, gen.reg.rowCount())
snap(pw, "w_gen_reg")
gen.tabs.setCurrentIndex(0)

print("— المبيعات الضريبية")
sw = TaxSalesScreen(user)
sw.resize(1366, 860)
sw.show()
app.processEvents()
si = sw.inv_tab
si.reload()
app.processEvents()
sitems = [si.customer.itemText(i) for i in range(si.customer.count())]
ok("خانة الحساب في المبيعات: كل الأنواع بنوعها",
   any("مكتب الأمل  ·  مكتب صيانة" in x for x in sitems)
   and any("مورد أ  ·  مورد" in x for x in sitems), sitems)
ok("وعنوانها «الحساب»", si.cust_field.caption.text().startswith("الحساب"),
   si.cust_field.caption.text())
si.customer.setCurrentIndex(si.customer.findData(M1))
si.e_wo.setText("BC-1")
si.e_reg.setValue(12)
si.e_rate.setValue(15)
si.add_item()
snap(sw, "w_sale")
si.post()
app.processEvents()
ok("بيعٌ ضريبي لجهةٍ من النوع الجديد", MSGS
   and not MSGS[-1].startswith("ERR"), MSGS[-1:])

print("— «+ جديد»: حسابٌ بنوعه")
from ui.tax_sales_screen import NewCustomerDialog  # noqa: E402
dlg = NewCustomerDialog(sw, "t", "customer")
types = [dlg.type.itemData(i) for i in range(dlg.type.count())]
ok("أنواع الحساب: عميل · مورد · جهة أخرى · النوع الجديد",
   types[:3] == ["customer", "supplier", "other"] and SHOP in types, types)
dlg.type.setCurrentIndex(dlg.type.findData(SHOP))
dlg.name.setText("مكتب النور")
dlg.save()
with db(readonly=True) as c:
    e = entities.get_entity(c, dlg.customer_id) if dlg.customer_id else None
ok("حُفظ «مكتب النور» من نوع «مكتب صيانة»", e is not None
   and e["entity_type"] == SHOP, MSGS[-1:])
dlg2 = NewCustomerDialog(sw, "t", "customer")
dlg2.type.setCurrentIndex(dlg2.type.findData("supplier"))
dlg2.name.setText("مورد بلا رقم")
dlg2.save()
ok("المورد بلا رقمٍ ضريبي يُرفض", dlg2.customer_id is None
   and "إلزامي للموردين" in MSGS[-1], MSGS[-1:])
if OUT:
    dlg.show()
    QtTest.QTest.qWait(150)
    dlg.grab().save(f"{OUT}/w_newacc.png")

print("— السجلّان")
sw.tabs.setCurrentIndex(2)
app.processEvents()
sr = sw.reg_tab
sr.period.set_mode("month")
sr.period._shift(-4)
app.processEvents()
sr.b_search.click()
app.processEvents()
ok("«🔍 بحث» يعرض كل السندات في كل الفترات", sr.period.mode == "all"
   and len(sr._rows) >= 1, (sr.period.mode, len(sr._rows)))
def _bar(reg, *more):
    """كل ما في صفّ فرز السجل: أزرار الفترة والبحث والقوائم والزر."""
    ws = list(reg.period.btns.values()) + [w for w in more]
    return {(w.objectName() or type(w).__name__, w.height(),
             w.mapTo(reg, QtCore.QPoint(0, 0)).y()) for w in ws}


bar = _bar(sr, sr.q, sr.kind, sr.sub, sr.b_search)
ok("صفّ السجل على ارتفاعٍ واحد وخطٍّ واحد (لا ميل)",
   len({h for _n, h, _y in bar}) == 1 and len({y for *_x, y in bar}) == 1,
   bar)
snap(sw, "w_sreg")
pw.tabs.setCurrentIndex(3)
app.processEvents()
pr = pw.reg_tab
pr.b_search.click()
app.processEvents()
kinds = [r["kind_label"] for r in pr._rows]
ok("سجل المشتريات: الذهب والمشتريات النقدية", "مشتريات نقدية (مصروف)" in kinds
   and "مشتريات ذهب ضريبية" in kinds, kinds)
bar = _bar(pr, pr.q, pr.kind, pr.b_search)
ok("صفّ سجل المشتريات على ارتفاعٍ واحد وخطٍّ واحد",
   len({h for _n, h, _y in bar}) == 1 and len({y for *_x, y in bar}) == 1,
   bar)
snap(pw, "w_preg")

print("— التكويد الموحّد")
from ui.entities_screen import EntitiesScreen  # noqa: E402
import ui.entity_type_dialog as etd  # noqa: E402
es = EntitiesScreen(user)
es.refresh()
ok("نوع «مكتب صيانة» في قائمة الأنواع وقائمة الفرز",
   es.etype.findData(SHOP) >= 0 and es.f_type.findData(SHOP) >= 0)


def fake_new_type(parent, username="", plural=""):
    with db() as c:
        return et.create(c, "شركات الشحن", "شركة شحن", "liability", "cash",
                         username)


etd.new_entity_type = fake_new_type
es.new_type()
ship = [t for t in et.codes() if t != SHOP][0]
ok("«+ نوع جهة جديد» يُنشئه ويختاره فوراً", es.etype.currentData() == ship
   and es.f_type.findData(ship) >= 0, es.etype.currentData())
es.name.setText("سمسا")
es.save()
with db(readonly=True) as c:
    rows = entities.list_entities(c, (ship,))
ok("جهةٌ تحته من الشاشة نفسها", len(rows) == 1 and rows[0]["name"] == "سمسا",
   MSGS[-2:])
es.f_type.setCurrentIndex(es.f_type.findData(ship))
es.refresh()
texts = [es.table.item(r, 1).text() for r in range(es.table.rowCount())
         if es.table.item(r, 1)]
ok("الدليل: «إجمالي شركات الشحن (1)»", any("إجمالي شركات الشحن (1)" in x
                                           for x in texts), texts)
es.f_type.setCurrentIndex(0)
es.tabs.setCurrentIndex(1)
es.etype.setCurrentIndex(es.etype.findData(SHOP))
snap(es, "w_ent_add", 760)
es.tabs.setCurrentIndex(0)
snap(es, "w_ent_dir", 760)

print("— سندات القبض والصرف")
from ui.vouchers_screen import VouchersScreen  # noqa: E402
vs = VouchersScreen(user)
vs.refresh()
app.processEvents()
ok("خانة الصندوق/البنك اختيارٌ فقط والصندوق الرئيسي مختار",
   not vs.c_target.isEditable() and vs.c_target.currentData() == "1400")
snap(vs, "w_vouch", 760)

with db(readonly=True) as c:
    tb = c.execute(
        "SELECT ROUND(SUM(gold_debit-gold_credit),3),"
        " ROUND(SUM(cash_debit-cash_credit),2) FROM journal_lines l"
        " JOIN journal_entries e ON e.id=l.entry_id WHERE e.is_deleted=0"
        ).fetchone()
ok("الدفتر متوازن", abs(tb[0] or 0) < 1e-6 and abs(tb[1] or 0) < 1e-6,
   tuple(tb))
errs = [m for m in MSGS if m.startswith("ERR") and "إلزامي للموردين" not in m]
ok("لا أخطاء في الواجهة", not errs, errs)
print(f"\n{len(OK)} ✔ · {len(BAD)} ✘")
sys.stdout.flush()
os._exit(1 if BAD else 0)
