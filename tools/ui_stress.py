#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""إجهاد الواجهة — يفتح كل شاشة ويضغط كل زر ويقيس زمنه.

    python tools/ui_stress.py [عدد_الفواتير]

**الشكوى التي وُجد لأجلها**: «تظهر شاشة سوداء ويقول ويندوز: لا
يستجيب، ثم يعود». هذا سلوك ويندوز حين **لا يعالج خيط الواجهة أحداثه
لثوانٍ**: فلا يُعاد رسم النافذة فتبقى سوداء، ويُعلن النظام معلَّقاً.
والسبب دائماً عمليةٌ طويلة نُفِّذت على خيط الواجهة — استعلامٌ ثقيل أو
بناء جدولٍ كبير أو نداء شبكة.

و`verify_all` يثبت أن الشاشات **تعمل**، ولا يقول شيئاً عن **بطئها**.
فهذه الأداة تكمّله: تبني دفتراً بحجم مصنعٍ حقيقي، ثم:

1. تفتح كل شاشة وتقيس زمن بنائها وتحديثها.
2. تستدعي كل دالة مربوطة بزر وتقيس زمنها.
3. تُصنّف ما تجاوز الحدّ: `SLOW` تحذير، و`FREEZE` تجمّد يراه المستخدم.

فيصير الكلام على البطء أرقاماً تُقارَن قبل الإصلاح وبعده، لا انطباعاً.
"""
import os
import shutil
import sys
import tempfile
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

_TMP = tempfile.mkdtemp(prefix="gold_stress_")
os.environ["GOLD_ERP_DATA_DIR"] = _TMP
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pathlib                                           # noqa: E402
import config                                            # noqa: E402
config.DB_PATH = pathlib.Path(_TMP) / "stress.db"

# حدود ما يراه المستخدم — لا اجتهاد فيها:
#  · دون 0.4 ثانية: فوري.
#  · 0.4–1.5: محسوس لكنه محتمل.
#  · فوق 1.5: انتظارٌ يستحق مؤشر انشغال.
#  · فوق 4: ويندوز يُعلن «لا يستجيب» ويرسم النافذة سوداء.
SLOW = 1.5
FREEZE = 4.0

RESULTS = []


def rec(kind, name, seconds, note=""):
    RESULTS.append({"kind": kind, "name": name, "sec": seconds,
                    "note": note})
    tag = ("FREEZE" if seconds >= FREEZE else
           "SLOW" if seconds >= SLOW else "ok")
    if tag != "ok":
        print(f"  {'⛔' if tag == 'FREEZE' else '⚠'} {tag:6} "
              f"{seconds:6.2f}ث  {name}{('  — ' + note) if note else ''}")
    return tag


def build_data(n_invoices):
    """دفترٌ بحجم مصنعٍ يعمل منذ سنة."""
    from database.database import create_tables, db, migrate_schema
    from database.seed import (ensure_new_accounts, ensure_system_tags,
                               seed_initial_data)
    from models.entities import (ensure_employee_accrual_accounts,
                                 ensure_internal_counterparties, add_entity)
    from models.inventory import create_work_orders_batch
    from models.invoices import create_sale
    from models.vouchers import create_voucher

    create_tables()
    migrate_schema()
    seed_initial_data()
    ensure_new_accounts()
    with db() as conn:
        ensure_internal_counterparties(conn)
        ensure_employee_accrual_accounts(conn)
        ensure_system_tags(conn)

    t0 = time.time()
    with db() as conn:
        custs = [add_entity(conn, f"عميل رقم {i}", "customer",
                            username="admin") for i in range(1, 26)]
        for i in range(1, 6):
            add_entity(conn, f"مورد رقم {i}", "supplier",
                       vat_number=f"30012345600{i:03d}", username="admin")

    wo_no = 1000
    for batch_i in range(n_invoices // 5 + 1):
        rows = []
        for _ in range(5):
            wo_no += 1
            rows.append({"wo_no": f"W{wo_no}", "gold": 12.0 + wo_no % 40,
                         "small_stones": 1.0, "big_stones": 2.0,
                         "wage_per_gram": 20.0 + (wo_no % 7),
                         "model_no": f"M{wo_no % 60}"})
        with db() as conn:
            create_work_orders_batch(
                conn, rows, f"2026-{1 + batch_i % 9:02d}-{1 + batch_i % 27:02d}",
                "admin")

    made = 0
    with db(readonly=True) as conn:
        free = [r["id"] for r in conn.execute(
            "SELECT id FROM work_orders WHERE status='in_stock'"
            " AND is_bulk=0 AND is_deleted=0 ORDER BY id")]
    for i in range(min(n_invoices, len(free) // 2)):
        pair = [{"work_order_id": free[i * 2]},
                {"work_order_id": free[i * 2 + 1]}]
        try:
            with db() as conn:
                create_sale(conn, custs[i % len(custs)], pair,
                            f"2026-{1 + i % 9:02d}-{1 + i % 27:02d}", "admin",
                            apply_vat=(i % 3 == 0))
            made += 1
        except Exception:
            break
    for i in range(min(120, made)):
        try:
            with db() as conn:
                create_voucher(conn, "receipt",
                               f"2026-{1 + i % 9:02d}-{1 + i % 27:02d}",
                               "admin", entity_id=custs[i % len(custs)],
                               cash_amount=500.0 + i)
        except Exception:
            break
    with db(readonly=True) as conn:
        n_entries = conn.execute(
            "SELECT COUNT(*) c FROM journal_entries").fetchone()["c"]
    print(f"  بُني الدفتر في {time.time() - t0:.1f}ث — "
          f"{made} فاتورة · {n_entries} قيداً · {wo_no - 1000} طقماً")
    return made, n_entries


def run_screens(user):
    """يفتح كل شاشة ويقيس بناءها وتحديثها واستدعاء أزرارها."""
    import inspect
    from PyQt5 import QtCore, QtWidgets
    from ui.main_window import MainWindow

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    # كل صناديق الحوار تُسكَت: أي نافذة قافلة توقف الأداة
    qmb = QtWidgets.QMessageBox
    qmb.information = staticmethod(lambda *a, **k: qmb.Ok)
    qmb.warning = staticmethod(lambda *a, **k: qmb.Ok)
    qmb.critical = staticmethod(lambda *a, **k: qmb.Ok)
    qmb.question = staticmethod(lambda *a, **k: qmb.No)
    qmb.about = staticmethod(lambda *a, **k: None)
    QtWidgets.QDialog.exec_ = lambda self, *a, **k: QtWidgets.QDialog.Rejected
    QtWidgets.QFileDialog.getSaveFileName = staticmethod(
        lambda *a, **k: ("", ""))
    QtWidgets.QFileDialog.getOpenFileName = staticmethod(
        lambda *a, **k: ("", ""))
    QtWidgets.QInputDialog.getText = staticmethod(lambda *a, **k: ("", False))
    QtWidgets.QInputDialog.getInt = staticmethod(lambda *a, **k: (1, True))
    QtWidgets.QInputDialog.getDouble = staticmethod(lambda *a, **k: (1.0, True))
    QtWidgets.QInputDialog.getItem = staticmethod(lambda *a, **k: ("", False))

    # ══ الطباعة تُقاس ولا تُفتح ══
    # فتح المعاينة يُظهر نافذة قافلة توقف الأداة، لكن **بناء** المستند
    # هو الجزء الثقيل الذي يُجمّد الواجهة عند المستخدم — فنقيسه وحده.
    from services import print_manager as _pm

    def _measure_build(parent, doc_type, doc_id, **kw):
        t = time.time()
        try:
            _pm.build_html(doc_type, doc_id, **kw)
        except Exception as e:
            rec("print", f"بناء مستند: {doc_type}", time.time() - t,
                f"{type(e).__name__}: {e}")
            return None
        rec("print", f"بناء مستند: {doc_type}", time.time() - t)
        return None

    _pm.preview_document = _measure_build
    _pm.print_document = _measure_build
    _pm.export_pdf_dialog = lambda *a, **k: None
    try:
        from services import browser_print as _bp
        _bp.open_document = lambda *a, **k: None
    except Exception:
        pass

    t0 = time.time()
    win = MainWindow(user)
    win.resize(1500, 950)
    win.show()
    app.processEvents()
    rec("boot", "بناء النافذة الرئيسية", time.time() - t0)

    names = getattr(win, "_screen_keys", {})
    for idx in sorted(names):
        label = names[idx]
        print(f"  ── {label}", flush=True)
        t0 = time.time()
        try:
            win.switch(idx)
            app.processEvents()
            # `switch` يؤجّل التحديث لدورة أحداث لاحقة
            for _ in range(6):
                app.processEvents()
                time.sleep(0.01)
        except Exception as e:
            rec("screen", f"فتح: {label}", time.time() - t0,
                f"{type(e).__name__}: {e}")
            continue
        rec("screen", f"فتح: {label}", time.time() - t0)

        scr = win.screens[idx]
        real = getattr(scr, "real", scr)
        # كل دالة عامة بلا وسائط إلزامية — وهي ما تربطه الأزرار
        for fn_name in sorted(dir(real)):
            if fn_name.startswith("_") or fn_name in SKIP:
                continue
            fn = getattr(real, fn_name, None)
            if not callable(fn) or not inspect.isroutine(fn):
                continue
            try:
                sig = inspect.signature(fn)
            except (TypeError, ValueError):
                continue
            if any(p.default is p.empty
                   and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
                   for p in sig.parameters.values()):
                continue
            print(f"       · {fn_name}()", flush=True)
            t0 = time.time()
            note = ""
            try:
                fn()
                app.processEvents()
            except Exception as e:
                note = f"{type(e).__name__}: {e}"
            rec("handler", f"{label} ← {fn_name}()", time.time() - t0, note)
    win.close()
    app.processEvents()
    return win


# دوال لا تُستدعى: تُغلق النظام أو تُغيّر حالة عامة أو تفتح متصفحاً
SKIP = {
    "close", "deleteLater", "destroy", "hide", "show", "showMaximized",
    "showMinimized", "showFullScreen", "showNormal", "raise_", "lower",
    "setFocus", "clearFocus", "update", "repaint", "grab", "render",
    "activateWindow", "releaseKeyboard", "releaseMouse", "releaseShortcut",
    "unsetCursor", "adjustSize", "updateGeometry", "dumpObjectInfo",
    "dumpObjectTree", "startTimer", "killTimer", "nextInFocusChain",
    "previousInFocusChain", "createWinId", "winId", "effectiveWinId",
    "open_browser", "do_print", "print_turnover", "do_update", "do_backup",
    "reset_nav_layout", "open_palette", "logout", "exit", "quit",
}


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    print("=" * 64)
    print("  إجهاد الواجهة — كل شاشة وكل زر، بالثواني")
    print("=" * 64)
    print(f"\n═══ 1) بناء دفتر بحجم واقعي ({n} فاتورة) ═══")
    build_data(n)

    print("\n═══ 2) فتح كل شاشة واستدعاء كل زر ═══")
    user = {"id": 1, "username": "admin", "full_name": "المحاسب",
            "role": "admin", "role_local": "accountant"}
    try:
        run_screens(user)
    except Exception:
        traceback.print_exc()
        return 2

    print("\n═══ 3) الخلاصة ═══")
    freezes = [r for r in RESULTS if r["sec"] >= FREEZE]
    slows = [r for r in RESULTS if SLOW <= r["sec"] < FREEZE]
    errors = [r for r in RESULTS if r["note"]]
    total = len(RESULTS)
    print(f"  قيست {total} عملية")
    print(f"  ⛔ تجمّد (≥{FREEZE}ث): {len(freezes)}")
    print(f"  ⚠ بطيء ({SLOW}–{FREEZE}ث): {len(slows)}")
    print(f"  ✘ أخطاء: {len(errors)}")
    top = sorted(RESULTS, key=lambda r: -r["sec"])[:12]
    print("\n  الأبطأ اثنتا عشرة عملية:")
    for r in top:
        print(f"    {r['sec']:6.2f}ث  {r['name']}")
    if errors:
        print("\n  الأخطاء:")
        for r in errors[:20]:
            print(f"    ✘ {r['name']} → {r['note'][:110]}")
    print("=" * 64)
    if freezes or errors:
        print("  ⛔ توجد عمليات تُجمّد الواجهة أو تُخطئ")
        return 1
    print("  ✔ لا عملية تُجمّد الواجهة")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
    sys.exit(code)
