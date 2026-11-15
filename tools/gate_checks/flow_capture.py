"""5.4: الإقلاع والدخول على شاشةٍ حقيقية — لقطاتٌ متتابعة وسطوعُ كلٍّ منها.

    python tools/gate_checks/flow_capture.py <مجلد_اللقطات>

يُشغَّل في فحص ويندوز (`.github/workflows/desktop-exe.yml`) — حيث النوافذ
تُركَّب كما على جهاز العميل (الشفافية والترتيب)، لا في بيئةٍ بلا شاشة.

الشكوى: «عندما أدخل بيانات الدخول يخرج كاملاً ثم يدخل». فيُصوَّر الدخول
كلّه لقطةً كل 150 م.ث من النقرة حتى تُغلق البوابة، ويُطبع سطوع كل لقطة:
لقطةٌ شبه سوداء أو سطحُ مكتبٍ بين البوابة والنظام = عودةُ العلّة.

الدخول هنا **محاكى** (لا سحابة في الفحص): `sign_in` يُستبدل في هذا الملف
وحده بجلسةٍ تجريبية — لا شيء منه في البرنامج نفسه.
"""
import os
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "out/flow")
OUT.mkdir(parents=True, exist_ok=True)
T = tempfile.mkdtemp(prefix="flow54_")
os.environ["GOLD_ERP_DATA_DIR"] = T

import config  # noqa: E402

config.DB_PATH = pathlib.Path(T) / "flow.db"

from ui.gate_window import GateWindow  # noqa: E402  (قبل التطبيق: محرّك الويب)
from PyQt5 import QtCore, QtGui, QtWidgets  # noqa: E402

import main  # noqa: E402
from services import login_flow  # noqa: E402

app = QtWidgets.QApplication(sys.argv)
from ui import styles  # noqa: E402

styles.apply(app)
T0 = time.time()
LOG = []


def note(msg):
    line = f"{time.time() - T0:6.2f}  {msg}"
    LOG.append(line)
    print(line, flush=True)


gate = GateWindow()
note(f"stage={type(gate.stage).__name__} 3d={gate._3d}")
gate.revealed.connect(lambda: note("revealed"))
gate.curtain.connect(lambda: note("curtain — العرض بدأ"))
if hasattr(gate.stage, "ready"):
    gate.stage.ready.connect(lambda: note("stage ready"))
    gate.stage.failed.connect(lambda w: note("stage failed: " + w))
gate.showFullScreen()
app.processEvents()
gate.prepare(main.prepare_steps() + main._ui_steps())
holder = main.wire_gate(app, gate)
login_flow.sign_in = lambda *a, **k: (time.sleep(0.3), {
    "username": "admin", "full_name": "مدير النظام", "id": 1,
    "role": "admin", "role_local": "accountant"})[1]

SHOTS = []


def lum(img):
    """متوسّط السطوع (0–255) على شبكةٍ من النقاط — يكفي لكشف السواد."""
    w, h = img.width(), img.height()
    tot = n = 0
    for y in range(h // 40, h, max(1, h // 20)):
        for x in range(w // 40, w, max(1, w // 32)):
            c = QtGui.QColor(img.pixel(x, y))
            tot += 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
            n += 1
    return tot / max(1, n)


def shot(tag):
    scr = app.primaryScreen()
    img = scr.grabWindow(0).toImage()
    k = len(SHOTS) + 1
    img.scaledToWidth(960, QtCore.Qt.SmoothTransformation).save(
        str(OUT / f"{k:02d}_{tag}.png"))
    win = holder.get("win")
    state = (f"phase={gate._phase} gate={'ظاهرة' if gate.isVisible() else '—'}"
             f" نظام={'%.2f' % win.windowOpacity() if win and win.isVisible() else '—'}")
    SHOTS.append((tag, lum(img), state))
    note(f"لقطة {k:02d} {tag:<10} سطوع {SHOTS[-1][1]:6.1f}  {state}")


def poll_show():
    if gate._phase == "show" and gate.card is not None \
            and gate.card.isVisible():
        note("الحقول ظاهرة")
        for i, ms in enumerate((300, 1200, 2400)):
            QtCore.QTimer.singleShot(ms, lambda i=i: shot(f"show{i}"))
        QtCore.QTimer.singleShot(3600, login)
        return
    QtCore.QTimer.singleShot(50, poll_show)


def login():
    note("دخول")
    gate.username.setText("admin")
    gate.password.setText("x")
    gate.try_login()
    burst(0)


def burst(i):
    shot(f"in{i:02d}")
    done = holder.get("win") is not None and not gate.isVisible()
    if (done and i > 2 and getattr(burst, "after", 0) >= 3) or i > 60:
        QtCore.QTimer.singleShot(400, end)
        return
    if done:
        burst.after = getattr(burst, "after", 0) + 1
    QtCore.QTimer.singleShot(150, lambda: burst(i + 1))


def end():
    win = holder.get("win")
    note(f"النهاية: النظام ظاهر={bool(win and win.isVisible())}"
         f" البوابة ظاهرة={gate.isVisible()}")
    # الحكم: من النقرة إلى النظام لا لقطة شبه سوداء (المشهد الهادئ أو
    # النظام دائماً)، والبوابة أُغلقت والنظام وحده
    # المرجع: المشهد بحقوله قبل الدخول. المشهد الهادئ بعده (بلا حقول وضوءٌ
    # أخفض قليلاً) أعتم منه بقليل — والسواد (علّة 5.3) أقلّ من ثلثه بكثير
    ref = max((s[1] for s in SHOTS if s[0].startswith("show")), default=0.0)
    ins = [s for s in SHOTS if s[0].startswith("in")]
    dark = [s for s in ins if ref > 0 and s[1] < 0.35 * ref]
    for s in ins:
        print(f"   {s[0]}  {s[1] / ref if ref else 0:5.2f}× المرجع  {s[2]}")
    print("──", f"المرجع {ref:.1f} · لقطات الدخول {len(ins)} · أقلّ سطوع "
          f"{min((s[1] for s in ins), default=0):.1f} · أعتم من ثلث المرجع"
          f" {len(dark)}")
    ok = bool(win and win.isVisible()) and not gate.isVisible() and not dark
    (OUT / "flow.log").write_text("\n".join(LOG), encoding="utf-8")
    print("FLOW", "OK" if ok else "FAIL", flush=True)
    app.exit(0 if ok else 1)


QtCore.QTimer.singleShot(150, lambda: shot("boot"))
QtCore.QTimer.singleShot(200, poll_show)
QtCore.QTimer.singleShot(90000, end)          # حارس: لا يعلق الفحص
sys.exit(app.exec_())
