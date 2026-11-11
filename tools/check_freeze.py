# -*- coding: utf-8 -*-
"""اختبار 5.2.9: لا تجمّد مع النقر السريع والكتابة والجداول الكبيرة.

    python3 tools/check_freeze.py

الشكوى: «عند الانتقال من لوحة إلى لوحة في لوحة التحكم يعلق النظام ويقول
لا يستجيب وتظهر شاشة بيضاء — وأحياناً في شاشات أخرى عند النقر السريع أو
الكتابة». يثبت هنا ما عولج:

1. الجدول ارتفاع صفّه ثابت بلا لفّ — ملء آلاف الصفوف لا يقيس كل صف.
2. النقرات المتتالية على لوحات لوحة التحكم تُدمج في تحديثٍ واحد.
3. لوحة أرقام التشغيل الكبيرة تظهر فوراً وتُكمل صفوفها على دفعات.
4. أرقام اللوحات لا تُعاد قراءتها مع كل نقرة.
5. البحث الحيّ يُنفَّذ بعد أن تهدأ الكتابة لا مع كل حرف.
6. دليل الموديلات يبني أرقام التشغيل عند فتح موديلها لا كلها مسبقاً.
7. النقرات السريعة على القائمة الجانبية تفتح آخر شاشةٍ نُقرت وحدها.
"""
import os
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
T = tempfile.mkdtemp(prefix="tfz_")
os.environ["GOLD_ERP_DATA_DIR"] = T
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import config  # noqa: E402
config.DB_PATH = pathlib.Path(T) / "t.db"

from PyQt5 import QtCore, QtWidgets  # noqa: E402
from PyQt5.QtTest import QTest  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
qmb = QtWidgets.QMessageBox
for _n in ("information", "warning", "critical", "about"):
    setattr(qmb, _n, staticmethod(lambda *a, **k: qmb.Ok))
qmb.question = staticmethod(lambda *a, **k: qmb.No)
QtWidgets.QDialog.exec_ = lambda self, *a, **k: QtWidgets.QDialog.Rejected

from database.database import (create_tables, db, migrate_schema,  # noqa: E402
                               run_migrations_files)
from database.seed import (ensure_new_accounts, ensure_system_tags,  # noqa: E402
                           seed_initial_data)
from models.entities import (ensure_employee_accrual_accounts,  # noqa: E402
                             ensure_internal_counterparties)
from models.inventory import create_work_orders_batch  # noqa: E402

create_tables(); migrate_schema(); run_migrations_files()
seed_initial_data(); ensure_new_accounts()
with db() as conn:
    ensure_internal_counterparties(conn)
    ensure_employee_accrual_accounts(conn)
    ensure_system_tags(conn)

N_WO = 1800
with db() as conn:
    for b in range(N_WO // 60):
        create_work_orders_batch(conn, [
            {"wo_no": f"{b * 60 + k + 1}", "gold": 10 + k % 9,
             "small_stones": 0.5, "big_stones": 1.0, "wage_per_gram": 12,
             "model_no": f"M{(b * 60 + k) % 40}"} for k in range(60)],
            "2026-03-01", "t")

ok = bad = 0


def check(name, cond, detail=""):
    global ok, bad
    print(("  ✔ " if cond else "  ✘ ") + name, "" if cond else detail)
    ok += bool(cond)
    bad += (not cond)


def pump(n=4):
    for _ in range(n):
        app.processEvents()


T0 = time.perf_counter
user = {"id": 1, "username": "admin", "full_name": "المحاسب",
        "role": "admin", "role_local": "accountant"}

# ── 1) الجدول: ارتفاعٌ ثابت بلا لفّ، والملء اليدوي سريع ──
from ui.widgets.common import make_table, live_search  # noqa: E402
w = QtWidgets.QWidget()
lay = QtWidgets.QVBoxLayout(w)
t = make_table()
lay.addWidget(t)
w.resize(1200, 700)
w.show()
pump()
check("الجدول بارتفاع صفٍّ ثابت وبلا لفّ",
      t.verticalHeader().sectionResizeMode(0) == QtWidgets.QHeaderView.Fixed
      and not t.wordWrap())
a = T0()
for rnd in range(2):                      # ملءٌ ثم إعادة ملءٍ فوق الموجود
    t.setColumnCount(6)
    t.setRowCount(2000)
    for r in range(2000):
        for c in range(6):
            t.setItem(r, c, QtWidgets.QTableWidgetItem(f"خلية {r}-{c}"))
    pump()
dt = T0() - a
check(f"ملء 2000 صفٍّ مرتين يدوياً في جدولٍ ظاهر: {dt:.2f}ث (كان دقائق)",
      dt < 3.0, dt)
w.close()

# ── 2–4) لوحة التحكم ──
from ui.dashboard_screen import DashboardScreen  # noqa: E402
d = DashboardScreen(user)
d.resize(1400, 850)
d.show()
pump()
stock = next((i for i, p in enumerate(d.panels) if p.get("kind") == "stock"),
             None)
check("لوحة أرقام التشغيل موجودة", stock is not None)
calls = {"n": 0}
_orig_refresh = d.refresh


def _counting():
    calls["n"] += 1
    return _orig_refresh()


d.refresh = _counting
d._sel_timer = None
d.__dict__.pop("_sel_timer", None)
order = [0, 1, 2, stock, 0, stock]
for i in order:
    d.buttons[i].click()               # نقراتٌ متتالية قبل أي معالجة
pump(6)
check(f"ست نقرات سريعة على اللوحات = تحديثٌ واحد ({calls['n']})",
      calls["n"] == 1, calls["n"])
check("والمؤشَّرة واللوحة المعروضة آخر نقرة",
      d.current == stock and d.buttons[stock].isChecked()
      and d.table.rowCount() == N_WO + 1, (d.current, d.table.rowCount()))
d.refresh = _orig_refresh
a = T0()
d.select(0)
d.select(stock)
first = T0() - a
filled = sum(1 for r in range(d.table.rowCount())
             if d.table.item(r, 0) is not None)
check(f"اللوحة الكبيرة تظهر فوراً ({first * 1000:.0f} ملّي ث) بأول صفوفها"
      " وصفّ الإجمالي", filled < d.table.rowCount()
      and d.table.item(d.table.rowCount() - 1, 0).text() == "الإجمالي",
      (filled, d.table.rowCount()))
for _ in range(40):
    pump(2)
filled = sum(1 for r in range(d.table.rowCount())
             if d.table.item(r, 0) is not None)
check("ثم تكتمل صفوفها على دفعاتٍ بين أحداث الواجهة",
      filled == d.table.rowCount(), (filled, d.table.rowCount()))
# لوحةٌ أخرى أثناء الملء: الدفعات القديمة تتوقّف ولا تكتب في الجدول الجديد
d.select(stock)
d.select(0)
pump(30)
check("تغيير اللوحة أثناء الملء يوقف الدفعات القديمة",
      d.table.rowCount() < 50, d.table.rowCount())
from models import dash_panels as dp  # noqa: E402
cnt = {"n": 0}
_orig_sum = dp.stock_summary


def _sum(conn):
    cnt["n"] += 1
    return _orig_sum(conn)


dp.stock_summary = _sum
for i in (1, 2, 0, 1):
    d.select(i)
check(f"أرقام اللوحات لا تُعاد قراءتها مع كل نقرة ({cnt['n']})",
      cnt["n"] == 0, cnt["n"])
with db() as conn:
    create_work_orders_batch(conn, [{"wo_no": "X1", "gold": 5,
                                     "small_stones": 0, "big_stones": 0,
                                     "wage_per_gram": 1}], "2026-03-02", "t")
d.select(1)
check("وتُعاد إن تغيّرت البيانات", cnt["n"] == 1, cnt["n"])
with db(readonly=True) as conn:
    s = dp.stock_summary(conn)
    r = dp.stock_totals(dp.stock_rows(conn))
check("مجموع زرّ الأطقم من القاعدة = مجموع الجدول",
      s["count"] == r["count"] and abs(s["reg"] - r["reg"]) < 0.01, (s, r))
dp.stock_summary = _orig_sum
# بحث الأطقم: بعد أن تهدأ الكتابة
d.select(stock)
pump()
cnt2 = {"n": 0}
_o = d.refresh


def _c2():
    cnt2["n"] += 1
    return _o()


d.refresh = _c2
d.stock_search.setFocus()
pump()
for ch in "M12":
    QTest.keyClick(d.stock_search, ch)
pump()
check("بحث الأطقم لا يُعيد البناء مع كل حرف", cnt2["n"] == 0, cnt2["n"])
QTest.qWait(400)
pump()
check("ويُنفَّذ مرةً واحدة بعد أن تهدأ الكتابة", cnt2["n"] == 1, cnt2["n"])
d.refresh = _o
d.close()

# ── 5) البحث الحيّ المشترك ──
e = QtWidgets.QLineEdit()
e.show()
hits = []
live_search(e, lambda txt: hits.append(txt))
e.setText("برمجياً")
check("الضبط من الشيفرة (بلا تركيز) يُنفَّذ في حينه", hits == ["برمجياً"],
      hits)
e.clear()
hits.clear()
e.setFocus()
pump()
for ch in "abc":
    QTest.keyClick(e, ch)
check("الكتابة لا تُنفّذ البحث مع كل حرف", not hits, hits)
QTest.keyClick(e, QtCore.Qt.Key_Return)
check("و«Enter» تنفّذه فوراً بآخر نص", hits == ["abc"], hits)
e.close()

# ── 6) دليل الموديلات ──
from ui.models_screen import ModelsScreen  # noqa: E402
m = ModelsScreen(user)
m.resize(1300, 850)
m.show()
pump()


def leaves(node):
    n = 0
    for r in range(node.rowCount()):
        b = node.child(r, 0)
        for k in range(b.rowCount()):
            dd = b.child(k, 0).data(QtCore.Qt.UserRole)
            n += bool(dd and dd[0] == "wo")
    return n


total = sum(leaves(m.model.item(i)) for i in range(m.model.rowCount()))
check(f"الدليل يُفتح بلا بناء أرقام التشغيل ({total} مبنياً من {N_WO + 1})",
      total == 0, total)
n0 = m.model.item(0)
m.tree.expand(n0.index())
pump()
check("فتح الموديل يبني أرقامه بعددها في رأسه",
      leaves(n0) == int(m.model.item(0, 1).text()),
      (leaves(n0), m.model.item(0, 1).text()))
m.search.setText("1799")
pump()
shown = [i for i in range(m.model.rowCount())
         if not m.tree.isRowHidden(i, QtCore.QModelIndex())]
check("البحث برقم تشغيل يجده وإن لم يُفتح موديله",
      len(shown) == 1 and "1 طقم" in m.summary.text(), m.summary.text())
m.search.setText("")
m.tree.collapseAll()
pump()
m._toggle_fold()
pump()
total = sum(leaves(m.model.item(i)) for i in range(m.model.rowCount()))
check(f"«توسيع الكل» يبني الكل ({total})", total == N_WO + 1, total)
a = T0()
m._toggle_fold()
pump()
check(f"و«طيّ الكل» سريع ({(T0() - a) * 1000:.0f} ملّي ث)",
      T0() - a < 2.0 and not m._any_expanded())
m.close()

# ── 7) القائمة الجانبية ──
from ui.main_window import MainWindow  # noqa: E402
win = MainWindow(user)
win.resize(1500, 950)
win.show()
pump()
nodes = []
for i in range(win.sidebar.topLevelItemCount()):
    top = win.sidebar.topLevelItem(i)
    for k in range(top.childCount()):
        it = top.child(k)
        idx = it.data(0, QtCore.Qt.UserRole)
        if isinstance(idx, int) and idx > 0 and win._plan_allows(idx) \
                and "إيقاف المصانع" not in it.text(0):
            nodes.append(it)
built = []
_sw = win.switch


def _spy(row, _back=False):
    built.append(row)
    return _sw(row, _back)


win.switch = _spy
for it in nodes[:5]:
    win._nav_clicked(it)
pump(6)
want = nodes[4].data(0, QtCore.Qt.UserRole)
check(f"خمس نقراتٍ سريعة على القائمة = شاشةٌ واحدة تُفتح ({len(built)})",
      built == [want] and win._current_row == want, built)
win.close()

print(f"{ok} ✔ · {bad} ✘")
sys.exit(1 if bad else 0)
