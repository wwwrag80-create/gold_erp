#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""فحص شامل للنظام قبل التشغيل — يُشغَّل بلا حاجة إلى PyQt5.

    python tools/verify_all.py

يفحص أربع طبقات:
  1. الترجمة: كل ملف بايثون يُترجم بلا أخطاء صياغة.
  2. الدوال: كل دالة مربوطة بزر أو مستدعاة عبر self معرَّفة فعلاً.
  3. الإقلاع: مسار main.py كاملاً + بناء كل شاشة + التنقل بينها.
  4. المعالجات: استدعاء كل دالة مربوطة بزر لاصطياد الأخطاء المخفية
     خلف try/except.

يستخدم محاكي Qt في tools/qt_stub.py، وهو مضبوط ليرفع AttributeError
لأي اسم خارج واجهة Qt — تماماً كما يفعل PyQt5 الحقيقي.
"""
import ast
import glob
import importlib
import inspect
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

QT_INHERITED = {
    # توابع الجداول الموروثة (QTableWidget) — تظهر في الأصناف المشتقة
    "state", "setCurrentCell", "currentRow", "currentColumn", "rowCount",
    "indexWidget", "commitData", "closeEditor", "currentIndex",
    "completer", "setCompleter", "lineEdit", "setModel", "model",
    "setIndexWidget", "openPersistentEditor", "closePersistentEditor",
    "columnCount", "item", "editItem", "setItem", "setRowCount",
    "setColumnCount", "setHorizontalHeaderLabels", "horizontalHeader",
    "verticalHeader", "clear", "selectRow", "keyPressEvent",
    "setAlternatingRowColors", "setSelectionBehavior", "setEditTriggers",
    "horizontalHeaderItem", "setHorizontalScrollBarPolicy",
    "resizeColumnsToContents", "setWordWrap", "setShowGrid",
    "close", "show", "hide", "update", "repaint", "setFocus", "raise_",
    "accept", "reject", "done", "deleteLater", "setEnabled", "setVisible",
    "setWindowTitle", "resize", "exec_", "parent", "window", "font",
    "setFont", "setLayout", "layout", "setObjectName", "objectName",
    "setToolTip", "setMinimumWidth", "setMaximumWidth", "setStyleSheet",
    "adjustSize", "activateWindow", "showMaximized", "showNormal",
    "setCursor", "mouseReleaseEvent", "setContentsMargins", "setSpacing",
    "sender", "installEventFilter", "removeEventFilter", "setProperty",
    "property", "style", "unpolish", "polish", "setSizePolicy", "geometry",
    "setGeometry", "move", "width", "height", "isVisible", "setCheckable",
    "setChecked", "isChecked", "addWidget", "addLayout", "setCentralWidget",
    "statusBar", "menuBar", "setWindowIcon", "setMinimumSize", "showEvent",
    "closeEvent", "keyPressEvent", "eventFilter", "setWindowState",
    "setEditable", "setInsertPolicy", "lineEdit", "model", "setCompleter",
    # موروثات QComboBox/QLabel المستعملة في الأصناف المشتقة
    "setSizeAdjustPolicy", "setMinimumContentsLength", "view",
    "rect", "alignment", "setAlignment", "text", "setText",
    "minimumSizeHint", "sizeHint", "paintEvent", "setWordWrap",
    # موروثات QDialog/QWidget في نوافذ الأدوات (شريط الأوامر)
    "setWindowFlags", "setWindowTitle", "accept", "reject", "resize",
    "move", "width", "height", "parent", "window", "setFocus", "selectAll",
    "itemText", "count", "setCurrentIndex", "currentIndex", "itemData",
    "setFrameShape", "setModal", "addItem", "clear", "findData",
    "currentData", "currentText", "setText", "text", "setValue", "value",
    "setRange", "setDecimals", "setSuffix", "setPlaceholderText",
    "selectAll", "setDate", "date", "setCalendarPopup", "setDisplayFormat",
    "setWordWrap", "setAlignment", "setPixmap", "setReadOnly",
    "setPlainText", "setMaximumHeight", "setMinimumHeight",
}
OPTIONAL = {"on_edit_cancelled", "refresh", "load_document"}
MIXIN = {"init_edit_mode", "edit_widgets", "begin_edit", "cancel_edit",
         "verify_edit_target", "_entry_alive",
         "end_edit", "is_editing", "_sync_edit_ui", "edit_banner",
         "btn_cancel_edit", "editing_entry_id", "editing_source_id"}

SCREENS = [
    ("ui.payroll_screen", "PayrollScreen"),
    ("ui.shrinkage_screen", "ShrinkageScreen"),
    ("ui.melting_screen", "MeltingScreen"),
    ("ui.fixing_screen", "FixingScreen"),
    ("ui.purchases_screen", "PurchasesScreen"),
    ("ui.opening_stock_screen", "OpeningStockScreen"),
    ("ui.production_screen", "ProductionScreen"),
    ("ui.sales_screen", "SalesScreen"),
    ("ui.coa_screen", "CoaScreen"),
    ("ui.entities_screen", "EntitiesScreen"),
    ("ui.subledger_screen", "SubLedgerScreen"),
    ("ui.stocktake_screen", "StocktakeScreen"),
    ("ui.journal_screen", "JournalScreen"),
    ("ui.general_ledger_screen", "GeneralLedgerScreen"),
    ("ui.transaction_log_screen", "TransactionLogScreen"),
    ("ui.dashboard_screen", "DashboardScreen"),
    ("ui.vouchers_screen", "VouchersScreen"),
    ("ui.document_archive_screen", "DocumentArchiveScreen"),
    ("ui.reports.income_statement", "IncomeStatementScreen"),
    ("ui.reports.vat_return_screen", "VatReturnScreen"),
    ("ui.reports.khazina_report_screen", "KhazinaReportScreen"),
    # الشاشات التي كانت خارج الفحص — وهي التي اختبأت فيها الأخطاء
    ("ui.mfg_costs_screen", "MfgCostsScreen"),
    ("ui.models_screen", "ModelsScreen"),
    ("ui.operations_screen", "OperationsScreen"),
    ("ui.opening_balances_screen", "OpeningBalancesScreen"),
    ("ui.payroll_run_screen", "PayrollRunScreen"),
    ("ui.reconciliation_screen", "ReconciliationScreen"),
    ("ui.sales_analytics_screen", "SalesAnalyticsScreen"),
    ("ui.workshop_accounts_screen", "WorkshopAccountsScreen"),
    ("ui.workshop_losses_screen", "WorkshopLossesScreen"),
    ("ui.item_history_screen", "ItemHistoryScreen"),
    ("ui.reports.balance_sheet_screen", "BalanceSheetScreen"),
    ("ui.reports.trial_balance_screen", "TrialBalanceScreen"),
    ("ui.reports.factory_reports_screen", "FactoryReportsScreen"),
    ("ui.reports.stock_report", "StockReportScreen"),
    ("ui.reports.year_end_screen", "YearEndScreen"),
    ("ui.reports.aging_screen", "AgingScreen"),
    ("ui.reports.day_close_screen", "DayCloseScreen"),
    ("ui.reports.integrity_screen", "IntegrityScreen"),
    ("ui.reports.diagnostics_screen", "DiagnosticsScreen"),
    ("ui.reports.bank_recon_screen", "BankReconScreen"),
    ("ui.reports.model_profit_screen", "ModelProfitScreen"),
    ("ui.reports.assets_screen", "AssetsScreen"),
    ("ui.reports.movement_screen", "MovementScreen"),
    ("ui.reports.gold_map_screen", "GoldMapScreen"),
    ("ui.reports.stock_aging_screen", "StockAgingScreen"),
    ("ui.reports.wage_audit_screen", "WageAuditScreen"),
    ("ui.reports.dossier_screen", "DossierScreen"),
    ("ui.reports.doc_edits_screen", "DocEditsScreen"),
    ("ui.super_admin_screen", "SuperAdminScreen"),
    ("ui.main_window", "MainWindow"),
]
BUGS = (AttributeError, NameError, KeyError, IndexError, ImportError)
failures = []


def step(title):
    print(f"\n═══ {title} ═══")


def check_compile():
    step("1) الترجمة")
    r = subprocess.run([sys.executable, "-m", "compileall", "-q", "."],
                       capture_output=True, text=True)
    if r.returncode:
        failures.append(("compileall", r.stdout + r.stderr))
        print("  ✘ فشلت الترجمة:\n", r.stdout, r.stderr)
    else:
        print("  ✔ كل الملفات تُترجم بلا أخطاء صياغة")


def _handlers_of(path, clsname):
    tree = ast.parse(open(path, encoding="utf-8").read())
    target = [n for n in tree.body
              if isinstance(n, ast.ClassDef) and n.name == clsname]
    if not target:
        return set()
    out = set()
    for n in ast.walk(target[0]):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "connect"):
            for a in n.args:
                if (isinstance(a, ast.Attribute)
                        and isinstance(a.value, ast.Name)
                        and a.value.id == "self"):
                    out.add(a.attr)
    return out


def check_methods():
    step("2) الدوال المربوطة والمستدعاة")
    problems = []
    for path in sorted(glob.glob("ui/**/*.py", recursive=True)):
        tree = ast.parse(open(path, encoding="utf-8").read(), path)
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            defined = {m.name for m in cls.body
                       if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
            assigned = {n.attr for n in ast.walk(cls)
                        if isinstance(n, ast.Attribute)
                        and isinstance(n.value, ast.Name)
                        and n.value.id == "self"
                        and isinstance(n.ctx, ast.Store)}
            bases = {b.id for b in cls.bases if isinstance(b, ast.Name)}
            known = (defined | assigned | QT_INHERITED | OPTIONAL
                     | (MIXIN if "EditModeMixin" in bases else set()))
            used = {}
            for n in ast.walk(cls):
                if (isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Attribute)
                        and isinstance(n.func.value, ast.Name)
                        and n.func.value.id == "self"):
                    used.setdefault(n.func.attr, n.lineno)
                if (isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Attribute)
                        and n.func.attr == "connect"):
                    for a in n.args:
                        if (isinstance(a, ast.Attribute)
                                and isinstance(a.value, ast.Name)
                                and a.value.id == "self"):
                            used.setdefault(a.attr, a.lineno)
            for name, line in sorted(used.items(), key=lambda kv: kv[1]):
                if name not in known:
                    problems.append(f"{path}:{line} {cls.name}.{name}")
    if problems:
        failures.append(("methods", problems))
        print(f"  ✘ دوال مفقودة: {len(problems)}")
        for p in problems:
            print("     ", p)
    else:
        print("  ✔ لا توجد دالة مربوطة أو مستدعاة بلا تعريف")


def check_boot():
    step("3) الإقلاع وبناء الشاشات")
    from database.database import (create_tables, db, migrate_schema,
                                   run_migrations_files)
    from database.seed import (ensure_new_accounts, ensure_system_tags,
                               seed_initial_data)
    from models.entities import (ensure_employee_accrual_accounts,
                                 ensure_internal_counterparties)
    # `run_migrations_files` جزءٌ من إقلاع النظام الحقيقي (main.py).
    # إغفالها هنا جعل الفحص يعمل على قاعدةٍ **أقدم** من التي يُشغَّل
    # عليها النظام: أي ميزةٍ تعتمد جدولاً من ملفات الهجرة تفشل عند
    # المستخدم ويمرّ الفحص. تُشغَّل بالترتيب نفسه: بعد الترقية.
    create_tables(); migrate_schema(); run_migrations_files()
    seed_initial_data(); ensure_new_accounts()
    with db() as conn:
        ensure_internal_counterparties(conn)
        ensure_employee_accrual_accounts(conn)
        ensure_system_tags(conn)
    print("  ✔ تهيئة قاعدة البيانات والترقيات")
    user = {"username": "admin", "role": "accountant", "full_name": "المدير"}
    # ══ نافذةٌ قافلة أثناء بناء الشاشة = تجمّدٌ لا فشل ══
    # الشاشة تُبنى داخل `switch()`. فإن فتحت نافذة خطأ أثناء بنائها
    # وقف الفحص إلى الأبد — لا رسالة ولا سطر يُقرأ منه السبب، وعند
    # المستخدم يقف النظام كله قبل أن تُعرض الشاشة. تُسجَّل هنا بدل
    # أن تُفتح، فيصير التجمّد فشلاً باسم شاشته.
    popped = _no_modals_during_build()
    try:
        from ui.main_window import MainWindow
        win = MainWindow(user)
        print(f"  ✔ MainWindow — {len(win.screens)} شاشة")
        for i, scr in enumerate(win.screens):
            popped.clear()
            try:
                win.switch(i)
            except Exception as ex:
                failures.append((type(scr).__name__, ex))
                print(f"  ✘ {type(scr).__name__}: {type(ex).__name__}: {ex}")
                continue
            if popped:
                name = getattr(win, "_screen_keys", {}).get(
                    i, type(scr).__name__)
                ex = RuntimeError(
                    f"فتحت نافذة حوار أثناء بنائها — توقف النظام قبل "
                    f"عرضها: {popped[0]}")
                failures.append((name, ex))
                print(f"  ✘ {name}: {ex}")
        print(f"  ✔ التنقل عبر كل الشاشات")
    except Exception as ex:
        failures.append(("MainWindow", ex))
        print(f"  ✘ MainWindow: {type(ex).__name__}: {ex}")


def _no_modals_during_build():
    """يمنع فتح أي نافذة حوارٍ ويسجّل محاولتها — يعيد قائمة ما سُجّل."""
    from PyQt5 import QtWidgets
    seen = []

    def grab(kind):
        def f(*a, **k):
            seen.append(f"{kind}: {a[2] if len(a) > 2 else ''}"[:160])
            return QtWidgets.QMessageBox.Ok
        return staticmethod(f)

    qmb = QtWidgets.QMessageBox
    qmb.critical = grab("خطأ")
    qmb.warning = grab("تنبيه")
    qmb.information = grab("رسالة")
    qmb.question = staticmethod(lambda *a, **k: qmb.No)
    QtWidgets.QDialog.exec_ = lambda self, *a, **k: QtWidgets.QDialog.Rejected
    return seen


def _silence_dialogs(modules, captured):
    """يستبدل كل صناديق الحوار بدوال صامتة قبل استدعاء المعالجات.

    أي `info`/`warn`/`ask` أو `QMessageBox` حقيقي يفتح نافذة **قافلة**
    تنتظر ضغطة المستخدم — فيتوقّف الفحص عند أول معالج ناجح ولا يُكمل
    بقية الشاشات إطلاقاً. إسكاتها يجعل الفحص يمرّ على كل المعالجات.
    كذلك نمنع فتح مربعات اختيار الملفات والطباعة للسبب نفسه.
    """
    from PyQt5 import QtWidgets
    qmb = QtWidgets.QMessageBox
    qmb.information = staticmethod(lambda *a, **k: qmb.Ok)
    qmb.warning = staticmethod(lambda *a, **k: qmb.Ok)
    qmb.critical = staticmethod(
        lambda *a, **k: (captured.append(RuntimeError(
            str(a[2]) if len(a) > 2 else "critical")), qmb.Ok)[1])
    qmb.question = staticmethod(lambda *a, **k: qmb.No)
    qmb.about = staticmethod(lambda *a, **k: None)
    QtWidgets.QFileDialog.getOpenFileName = staticmethod(
        lambda *a, **k: ("", ""))
    QtWidgets.QFileDialog.getSaveFileName = staticmethod(
        lambda *a, **k: ("", ""))
    QtWidgets.QFileDialog.getExistingDirectory = staticmethod(
        lambda *a, **k: "")
    QtWidgets.QInputDialog.getText = staticmethod(lambda *a, **k: ("", False))
    QtWidgets.QInputDialog.getItem = staticmethod(lambda *a, **k: ("", False))
    QtWidgets.QInputDialog.getInt = staticmethod(lambda *a, **k: (0, False))
    QtWidgets.QInputDialog.getDouble = staticmethod(lambda *a, **k: (0.0, False))
    QtWidgets.QDialog.exec_ = lambda self, *a, **k: QtWidgets.QDialog.Rejected
    for mod in modules:
        for name in ("info", "warn"):
            if hasattr(mod, name):
                setattr(mod, name, lambda *a, **k: None)
        if hasattr(mod, "ask"):
            setattr(mod, "ask", lambda *a, **k: False)
        if hasattr(mod, "confirm_post"):
            setattr(mod, "confirm_post", lambda *a, **k: False)
        if hasattr(mod, "err"):
            setattr(mod, "err", lambda p, e: captured.append(e))


def check_handlers():
    step("4) معالجات الأزرار")
    import ui.widgets.common as common
    captured = []
    common.err = lambda p, e: captured.append(e)
    _silence_dialogs([common], captured)
    user = {"username": "admin", "role": "accountant", "full_name": "المدير"}
    bugs, total = [], 0
    for modname, cls in SCREENS:
        m = importlib.import_module(modname)
        _silence_dialogs([m], captured)
        C = getattr(m, cls)
        try:
            obj = C(user)
        except TypeError:
            obj = C(user, None)
        for h in sorted(_handlers_of(modname.replace(".", "/") + ".py", cls)):
            fn = getattr(obj, h, None)
            if not callable(fn):
                bugs.append((cls, h, AttributeError("غير معرَّفة")))
                continue
            if any(p.default is p.empty
                   for p in inspect.signature(fn).parameters.values()):
                continue
            total += 1
            before = len(captured)
            try:
                fn()
            except BUGS as ex:
                bugs.append((cls, h, ex))
            except Exception:
                pass
            for e in captured[before:]:
                if isinstance(e, BUGS):
                    bugs.append((cls, h, e))
    print(f"  استُدعيت {total} دالة مربوطة بأزرار")
    if bugs:
        failures.append(("handlers", bugs))
        for cls, h, ex in bugs:
            print(f"  ✘ {cls}.{h}() → {type(ex).__name__}: {ex}")
    else:
        print("  ✔ لا أخطاء برمجية في المعالجات")


_QAPP = None


def _ensure_qapp():
    """ينشئ QApplication واحداً قبل بناء أي واجهة.

    بناء أي QWidget بلا QApplication يُنهي العملية فوراً (Aborted)
    فيتوقّف الفحص عند الخطوة الثالثة ولا تُفحص الشاشات ولا المعالجات
    إطلاقاً — وهو ما كان يجعل الفحص يبدو ناجحاً وهو لم يكتمل.
    """
    global _QAPP
    if _QAPP is not None:
        return _QAPP
    try:
        from PyQt5 import QtWidgets
    except ImportError:
        return None
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _QAPP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    return _QAPP


def main():
    try:
        from PyQt5 import QtWidgets           # noqa: F401
        print("(PyQt5 مثبَّت — الفحص يستخدمه مباشرة)")
        _ensure_qapp()
    except ImportError:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import qt_stub                        # noqa: F401
        print("(PyQt5 غير مثبَّت — يُستخدم محاكي Qt في tools/qt_stub.py)")
    check_compile()
    check_methods()
    check_boot()
    check_handlers()
    print("\n" + "═" * 46)
    if failures:
        print(f"✘ فشل الفحص — {len(failures)} مجموعة أخطاء. لا تشغّل النظام قبل إصلاحها.")
        return 1
    print("✔ النظام سليم — كل الفحوص نجحت، التشغيل آمن.")
    return 0


def _structural():
    """فحص بنيوي وقائي قبل بقية الفحوص."""
    try:
        import subprocess, sys as _s
        for script in ("tools/selfcheck.py", "tools/audit.py"):
            r = subprocess.run([_s.executable, script],
                               capture_output=True, text=True)
            if r.returncode != 0:
                print(r.stdout)
                return False
    except Exception:
        pass
    return True


if __name__ == "__main__":
    ok_struct = _structural()
    code = main()
    sys.exit(code if ok_struct else 1)
