"""5.9: السنوات المالية — زرّ «السنة»: لكل سنةٍ حساباتها، والأرصدة تنتقل.

    python3 tools/check_fiscal_years.py

* السنوات من أول قيد، وأيّها مقفل، وأيّها التالي للإقفال.
* الإقفال بالترتيب، ولا سنةٌ لم تنتهِ — ونسخةٌ احتياطية قبله.
* قيد الإقفال يصفّر الإيرادات والمصروفات ويرحّل الصافي إلى الأرباح المحتجزة.
* السنة المقفلة لا تقبل قيداً، والجديدة تقبل — والكشف يبدأ برصيدها السابق.
* إعادة فتح آخر سنةٍ للتصحيح ثم إقفالها ثانيةً يرحّل الفرق وحده.
* سنة العمل لكل مستخدم: تاريخ الشاشات والفترات منها — والزرّ ونافذة الإقفال.
* ورمز المدير (إن قفل التعديل) يُطلب للإقفال.
"""
import datetime
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
T = tempfile.mkdtemp(prefix="fiscal_years_")
os.environ["GOLD_ERP_DATA_DIR"] = T
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import config  # noqa: E402

config.DB_PATH = pathlib.Path(T) / "t.db"
import main  # noqa: E402

for _l, f in main.prepare_steps():
    f()
from database.database import db  # noqa: E402
from models import closing, fiscal, fiscal_years as fy, journal  # noqa: E402
from models.accounts import acc_id  # noqa: E402
from models.entities import add_entity  # noqa: E402
from services.accounting_engine import post_entry  # noqa: E402

OK, BAD = [], []


def check(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print(("  ✔ " if cond else "  ✘ ") + name + ("" if cond else f"  [{info}]"))


TODAY = datetime.date.today()
Y0, Y1, Y2 = TODAY.year - 2, TODAY.year - 1, TODAY.year


def sale(c, d, acct, cash, gold=0.0):
    """بيعٌ آجل: مدين العميل · دائن الإيراد (4110 ذهب · 4120 أجور)."""
    lines = [{"account_id": acct, "cash_debit": cash, "gold_debit": gold},
             {"account_id": acc_id(c, "4120"), "cash_credit": cash},
             ]
    if gold:
        lines.append({"account_id": acc_id(c, "4110"), "gold_credit": gold})
    return post_entry(c, d, "بيع للفحص", lines, username="t")


def expense(c, d, cash):
    return post_entry(c, d, "مصروف للفحص",
                      [{"account_id": acc_id(c, "5100") if c.execute(
                          "SELECT 1 FROM accounts WHERE code='5100' AND is_postable=1"
                      ).fetchone() else EXP, "cash_debit": cash},
                       {"account_id": acc_id(c, "1400"), "cash_credit": cash}],
                      username="t")


with db() as c:
    EXP = c.execute("SELECT id FROM accounts WHERE type='expense' AND is_postable=1"
                    " ORDER BY code LIMIT 1").fetchone()[0]
    A = add_entity(c, "عميل السنوات", "customer", username="t")
    ACC = c.execute("SELECT account_id FROM entities WHERE id=?", (A,)).fetchone()[0]
    sale(c, f"{Y0}-03-10", ACC, 500, 10)
    expense(c, f"{Y0}-04-01", 120)
    sale(c, f"{Y1}-05-05", ACC, 800, 20)
    expense(c, f"{Y1}-06-01", 200)
    sale(c, f"{Y2}-01-15", ACC, 300)

print("── 1) السنوات وحالها")
with db(readonly=True) as c:
    ys = fy.years(c)
    check(f"السنوات من أول قيد ({Y0}) حتى الجارية ({Y2})",
          [y["year"] for y in ys] == [Y0, Y1, Y2], ys)
    check("لا شيء مقفل بعد، والتالي للإقفال أقدمها", not any(y["closed"] for y in ys)
          and fy.next_to_close(c) == Y0)
    check("السنة الجارية لا تُقفل قبل انتهائها", "لم تنتهِ" in fy.check_close(c, Y2))
    check("ولا سنةٌ قبل ما قبلها", f"أقفل سنة {Y0}" in fy.check_close(c, Y1))

print(f"── 2) إقفال {Y0} ثم {Y1}")
with db() as c:
    r0 = fy.close_year(c, Y0, "t")
check(f"أُقفلت {Y0}: نسخةٌ احتياطية وقيد إقفال", r0["year"] == Y0 and r0["close_entry"]
      and r0["backup"] and pathlib.Path(r0["backup"]).exists(), r0)
check(f"وصافيها ربحٌ نقدي 380 (500 − 120) وذهب 10", abs(r0["net_cash"] - 380) < 0.01
      and abs(r0["net_gold"] - 10) < 0.001, r0)
with db(readonly=True) as c:
    check(f"والقفل حتى {Y0}-12-31", fiscal.lock_date(c) == f"{Y0}-12-31")
    check("وإيراداتها ومصروفاتها صُفّرت", not closing.year_end_preview(c, Y0)["items"])
    re_ = c.execute("SELECT ROUND(SUM(l.cash_credit-l.cash_debit),2) c FROM journal_lines l"
                    " JOIN journal_entries e ON e.id=l.entry_id AND e.is_deleted=0"
                    " WHERE l.account_id=?", (acc_id(c, "3200"),)).fetchone()["c"]
    check("والربح في الأرباح المحتجزة", abs((re_ or 0) - 380) < 0.01, re_)
    check(f"والتالي للإقفال {Y1}", fy.next_to_close(c) == Y1 and fy.is_closed(c, Y0))
with db() as c:
    r1 = fy.close_year(c, Y1, "t", to_partners=True)
check(f"وأُقفلت {Y1} (الصافي 600 إلى جاري الشركاء)", abs(r1["net_cash"] - 600) < 0.01)
with db(readonly=True) as c:
    check(f"لا شيء يُقفل الآن ({Y2} جارية)", fy.next_to_close(c) is None
          and fy.closed_through(c) == Y1)
    check("والسنوات: المقفلة مُعلَّمة", [y["closed"] for y in fy.years(c)] == [True, True, False])

print("── 3) السنة المقفلة محفوظة ولا تقبل قيداً — والجديدة تبدأ برصيدها")
try:
    with db() as c:
        sale(c, f"{Y1}-12-30", ACC, 50)
    blocked = False
except ValueError as e:
    blocked = "مقفلة" in str(e)
check(f"قيدٌ بتاريخ {Y1} مرفوض", blocked)
with db() as c:
    sale(c, f"{Y2}-02-01", ACC, 70)
check(f"وقيدٌ في {Y2} مقبول", True)
with db(readonly=True) as c:
    st = journal.statement(c, ACC, f"{Y2}-01-01", f"{Y2}-12-31")
    rows = st["rows"] if isinstance(st, dict) else st
    first = rows[0]
    check(f"كشف العميل في {Y2} يبدأ برصيده السابق (1300 ريال · 30 جم)",
          first["op"] == "رصيد سابق" and abs(first["cbal"] - 1300) < 0.01
          and abs(first["gbal"] - 30) < 0.001, first)
    old = journal.statement(c, ACC, f"{Y1}-01-01", f"{Y1}-12-31")
    old = old["rows"] if isinstance(old, dict) else old
    check(f"وكشف {Y1} محفوظٌ كما أُقفل", any(abs((r.get("cd") or 0) - 800) < 0.01
                                            for r in old))
    check(f"ونتيجة {Y2} تبدأ من صفر (مبيعاتها وحدها)",
          abs(-sum(i["cash"] for i in closing.year_end_preview(c, Y2)["items"]) - 370) < 0.01)

print(f"── 4) إعادة فتح {Y1} للتصحيح ثم إقفالها ثانيةً")
try:
    with db() as c:
        fy.reopen_year(c, Y0, "t")
    wrong = False
except ValueError:
    wrong = True
check("تُفتح آخر سنةٍ مقفلة وحدها", wrong)
with db() as c:
    fy.reopen_year(c, Y1, "t")
with db(readonly=True) as c:
    check(f"فُتحت {Y1} وما قبلها مقفل", fiscal.lock_date(c) == f"{Y0}-12-31"
          and not fy.is_closed(c, Y1) and fy.is_closed(c, Y0))
with db() as c:
    sale(c, f"{Y1}-12-20", ACC, 40)
    r1b = fy.close_year(c, Y1, "t")
check("وإقفالها ثانيةً يرحّل الفرق وحده (40)", abs(r1b["net_cash"] - 40) < 0.01, r1b)

print("── 5) سنة العمل لكل مستخدم — والشاشات منها")
from services import work_year as wy  # noqa: E402
with db() as c:
    check("الافتراضي: السنة الجارية", wy.load(c, "u1") == Y2)
    wy.set_year(c, "u1", Y1)
with db(readonly=True) as c:
    check("تُحفظ للمستخدم نفسه", fy.work_year(c, "u1") == Y1
          and fy.work_year(c, "u2") == Y2)
check(f"«اليوم» في {Y1} آخرها، وبدايتها أولها",
      wy.ref_date() == datetime.date(Y1, 12, 31) and wy.start() == datetime.date(Y1, 1, 1))
from PyQt5 import QtWidgets  # noqa: E402
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
from ui.widgets.common import date_edit  # noqa: E402
check(f"وحقل التاريخ يبدأ بآخر {Y1}", date_edit().date().toString("yyyy-MM-dd")
      == f"{Y1}-12-31")
from ui.reports.income_statement import period_range  # noqa: E402
s, e = period_range("year", wy.ref_date())
check(f"و«هذه السنة» في التقارير = {Y1}", (s.year, e.year) == (Y1, Y1))
from ui.reports.trial_balance_screen import TrialBalanceScreen  # noqa: E402
tb = TrialBalanceScreen({"username": "u1", "role": "super_admin", "id": 1})
check(f"وميزان المراجعة يُفتح على {Y1}",
      tb.d_from.date().toString("yyyy-MM-dd") == f"{Y1}-01-01"
      and tb.d_to.date().toString("yyyy-MM-dd") == f"{Y1}-12-31")
with db() as c:
    wy.set_year(c, "u1", Y2)
check("والعودة إلى الجارية: «اليوم» هو اليوم", wy.ref_date() == TODAY)

print("── 6) نافذة الإقفال")
from ui.year_dialog import YearCloseDialog  # noqa: E402
d = YearCloseDialog(None, {"username": "t", "role": "super_admin"}, Y2)
check("للسنة الجارية: الزرّ معطّل وسبب المنع ظاهر", not d.btn.isEnabled()
      and "لم تنتهِ" in d.warn.text())

print("── 7) رمز المدير يُطلب للإقفال (إن قفل التعديل)")
from services import desk_guard, manager_web as mweb  # noqa: E402
with db() as c:
    fy.reopen_year(c, Y1, "t")
    mweb.set_desk_pin(c, "2580", "t")
desk_guard.set_prompt(lambda action: "1111")
desk_guard.reset()
try:
    with db() as c:
        fy.close_year(c, Y1, "t")
    need = False
except desk_guard.ManagerCodeRequired:
    need = True
with db(readonly=True) as c:
    check("برمزٍ خاطئ: لا إقفال", need and not fy.is_closed(c, Y1))
desk_guard.set_prompt(lambda action: "2580")
desk_guard.reset()
with db() as c:
    fy.close_year(c, Y1, "t")
with db(readonly=True) as c:
    check("وبرمز المدير يُقفل", fy.is_closed(c, Y1))
desk_guard.set_prompt(None)

print("── 8) بدء سنةٍ جديدة دون إقفال السابقة — والأرصدة الافتتاحية تنتقل (5.10.2)")
with db(readonly=True) as c:
    last0 = fy.latest_year(c)
    ob_expected = journal.statement(c, ACC, f"{Y2}-01-01", f"{Y2}-12-31")
check(f"آخر سنةٍ في القائمة الآن {Y2}", last0 == Y2, last0)
with db() as c:
    ny = fy.start_next_year(c, "u9")
with db(readonly=True) as c:
    ys = [y["year"] for y in fy.years(c)]
    check(f"بدأت سنة {Y2 + 1} وظهرت في القائمة", ny == Y2 + 1 and ys[-1] == Y2 + 1, ys)
    check(f"وسنة {Y2} باقيةٌ مفتوحة (لم تُقفل)", not fy.is_closed(c, Y2)
          and fiscal.lock_date(c) == f"{Y1}-12-31")
    check("وصار المستخدم يعمل فيها", fy.work_year(c, "u9") == Y2 + 1)
    ob = fy.opening_balances(c, Y2 + 1)
    rec = [r for r in ob["rows"] if r["type"] == "asset"]
    bal = c.execute("SELECT ROUND(SUM(l.cash_debit-l.cash_credit),2) c,"
                    " ROUND(SUM(l.gold_debit-l.gold_credit),3) g FROM journal_lines l"
                    " JOIN journal_entries e ON e.id=l.entry_id AND e.is_deleted=0"
                    " WHERE l.account_id=? AND e.entry_date<?", (ACC, f"{Y2 + 1}-01-01")).fetchone()
    tot_assets_c = sum(r["cash"] for r in rec)
    all_c = c.execute("SELECT ROUND(SUM(l.cash_debit-l.cash_credit),2) FROM journal_lines l"
                      " JOIN journal_entries e ON e.id=l.entry_id AND e.is_deleted=0"
                      " JOIN accounts a ON a.id=l.account_id WHERE a.type='asset'"
                      " AND e.entry_date<?", (f"{Y2 + 1}-01-01",)).fetchone()[0]
    check(f"الأرصدة الافتتاحية = أرصدة 31-12-{Y2} (الأصول {tot_assets_c:.2f})",
          abs(tot_assets_c - (all_c or 0)) < 0.01 and ob["as_of"] == f"{Y2}-12-31",
          (tot_assets_c, all_c))
    check(f"ونتيجة {Y2} (لم تُقفل) ظاهرةٌ وحدها: ربح 370", abs(ob["unclosed_cash"] - 370) < 0.01,
          ob["unclosed_cash"])
    bal_sheet = sum(r["cash"] for r in ob["rows"])      # مدين − دائن
    check("والميزانية الافتتاحية متوازنة (الأصول = الخصوم + الملكية + النتيجة)",
          abs(bal_sheet - ob["unclosed_cash"]) < 0.01, (bal_sheet, ob["unclosed_cash"]))
with db() as c:
    sale(c, f"{Y2 + 1}-01-03", ACC, 90)
with db(readonly=True) as c:
    st = journal.statement(c, ACC, f"{Y2 + 1}-01-01", f"{Y2 + 1}-12-31")
    rows = st["rows"] if isinstance(st, dict) else st
    check(f"قيدٌ في {Y2 + 1} مقبول، وكشف العميل يبدأ برصيده الافتتاحي ({bal['c']:.0f})",
          rows[0]["op"] == "رصيد سابق" and abs(rows[0]["cbal"] - bal["c"]) < 0.01, rows[0])
with db() as c:
    sale(c, f"{Y2}-11-30", ACC, 15)
check(f"و{Y2} المفتوحة تقبل التصحيح بعد بدء {Y2 + 1}", True)
with db(readonly=True) as c:
    ob2 = fy.opening_balances(c, Y2 + 1)
check("والأرصدة الافتتاحية تتعدّل معه تلقائياً (+15)",
      abs(ob2["unclosed_cash"] - ob["unclosed_cash"] - 15) < 0.01)
with db() as c:
    ny2 = fy.start_next_year(c, "u9")
check(f"و«بدء سنةٍ» ثانيةً يبدأ التي بعدها ({Y2 + 2})", ny2 == Y2 + 2)
from ui.year_dialog import YearStartDialog  # noqa: E402
dlg = YearStartDialog(None, {"username": "u9", "role": "super_admin"}, Y2 + 3)
check("نافذة البدء تعرض الأرصدة الافتتاحية وزرّ البدء",
      dlg.findChild(QtWidgets.QTableWidget).rowCount() >= 2 and dlg.btn.isEnabled())

print(f"\n{len(OK)} ✔ · {len(BAD)} ✘")
os._exit(1 if BAD else 0)
