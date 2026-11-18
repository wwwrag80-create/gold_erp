"""5.8.5: حارس رابط المدير — يعمل ولو انطفأت الشاشة أو نام الجهاز.

    python3 tools/check_link_keeper.py

يُختبر منطق الحارس بلا ويندوز: طلب «النظام مطلوب» يُطلب ما دام الرابط
مفعّلاً والخيار مختاراً ويُرفع بإيقاف أيّهما، والاستيقاظ من النوم أو توقّف
الخادم يعيد الرابط مرةً واحدة، وقراءة إعداد الغطاء من ناتج powercfg بأي
لغة، والبدء مع ويندوز يتبع الرابط.
"""
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
T = tempfile.mkdtemp(prefix="keeper_")
os.environ["GOLD_ERP_DATA_DIR"] = T
import config  # noqa: E402

config.DB_PATH = pathlib.Path(T) / "t.db"
import main  # noqa: E402

for _l, f in main.prepare_steps():
    f()
from database.database import db  # noqa: E402
from services import link_keeper as lk, models_web as mw  # noqa: E402

OK, BAD = [], []


def check(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print(("  ✔ " if cond else "  ✘ ") + name + ("" if cond else f"  [{info}]"))


calls, restarts = [], []
lk._execution_state = lambda flags: calls.append(flags) or True
lk._restart_link = lambda why="": restarts.append(why) or True
lk._hold_lid = lambda on: None
alive = {"v": True}
lk._server_alive = lambda: alive["v"]
_apply_now = lk.apply_now
lk.apply_now = lambda: None          # الفحص يقود الحارس بيده — بلا خيط


def set_link(on):
    with db() as c:
        mw._set(c, mw.K_ENABLED, "1" if on else "0")


print("── الجهاز لا ينام ما دام الرابط مفعّلاً")
set_link(False)
check("الخيار مختارٌ افتراضاً", lk.always_on())
check("والرابط موقوف ⇒ لا شيء", lk.tick(1000.0) == [] and not calls, calls)
set_link(True)
did = lk.tick(1030.0)
check("تفعيل الرابط ⇒ طلب «النظام مطلوب» (مستمر)", "awake" in did and calls
      and calls[-1] & lk.ES_SYSTEM_REQUIRED and calls[-1] & lk.ES_CONTINUOUS,
      (did, calls))
check("والشاشة تبقى تنطفئ (لا طلب للشاشة)",
      not any(c & 0x00000002 for c in calls), calls)
n = len(calls)
lk.tick(1060.0)
check("الفحص التالي يجدّد الطلب", len(calls) > n)
lk.set_always_on(False, "t")
did = lk.tick(1090.0)
check("إيقاف الخيار يرفع الطلب", "released" in did
      and calls[-1] == lk.ES_CONTINUOUS, (did, calls[-1:]))
lk.set_always_on(True, "t")
lk.tick(1120.0)
set_link(False)
did = lk.tick(1150.0)
check("وإيقاف الرابط يرفعه", "released" in did and not lk._STATE["awake"])

print("── الاستيقاظ وتوقّف الخادم")
set_link(True)
lk.tick(2000.0)
restarts.clear()
did = lk.tick(2000.0 + lk.WAKE_GAP + 600)
check("قفزةٌ في الوقت (نام ثم استيقظ) ⇒ يعود الرابط", "wake" in did
      and restarts == ["wake"], (did, restarts))
restarts.clear()
alive["v"] = False
did = lk.tick(lk._STATE["last"] + 30)
check("توقّف الخادم ⇒ يعود الرابط", "server" in did and restarts == ["server"],
      (did, restarts))
alive["v"] = True
restarts.clear()
did = lk.tick(lk._STATE["last"] + 30)
check("وفي الحال العادية لا إعادة", restarts == [] and "wake" not in did, did)

print("── إعداد الغطاء من ناتج powercfg (بأي لغة)")
EN = """Power Setting GUID: 5ca83367-6e45-459f-a27b-476b1d01c936  (Lid close action)
      Possible Setting Index: 000
      Possible Setting Friendly Name: Do nothing
      Possible Setting Index: 001
      Possible Setting Friendly Name: Sleep
    Current AC Power Setting Index: 0x00000001
    Current DC Power Setting Index: 0x00000002
"""
AR = """معرف GUID لإعداد الطاقة: 5ca83367-6e45-459f-a27b-476b1d01c936  (إجراء إغلاق الغطاء)
    فهرس إعداد طاقة التيار المتردد الحالي: 0x00000003
    فهرس إعداد طاقة التيار المستمر الحالي: 0x00000001
"""
for txt, want, nm in ((EN, 1, "الإنجليزية"), (AR, 3, "العربية")):
    lk._powercfg = lambda args, timeout=15, t=txt: (0, t)
    check(f"قيمة الكهرباء تُقرأ من ناتج ويندوز بـ{nm}", lk._lid_ac() == want,
          lk._lid_ac())

print("── البدء مع ويندوز")
check("نسخة المطوّر لا تُسجَّل (exe وحدها)", lk._exe_command() == "")
sys.frozen = True
check("ونسخة exe تُسجَّل بمسارها بين علامتي تنصيص",
      lk._exe_command().startswith('"') and lk._exe_command().endswith('"'))
del sys.frozen
check("خارج ويندوز لا شيء يُكتب", lk.set_autostart(True) is False
      and lk.autostart_registered() is False)
set_link(True)
check("سطر الحال يذكر أن الجهاز لا ينام والبرنامج يبقى بجوار الساعة",
      "لا ينام" in lk.status_text() and "بجوار الساعة" in lk.status_text(),
      lk.status_text())

print("── الحارس يبدأ مرةً واحدة")
lk.CHECK_EVERY = 3600
lk.apply_now = _apply_now
first = lk.start()
again = lk.start()
check("start ثم start ⇒ خيطٌ واحد", first and not again and lk.started())
lk.stop()

print(f"\n{len(OK)} ✔ · {len(BAD)} ✘")
sys.exit(1 if BAD else 0)
