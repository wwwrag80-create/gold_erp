# -*- coding: utf-8 -*-
"""حارس تجمّد الواجهة — يقول **أين** تجمّد النظام، لا أنه تجمّد.

**الشكوى**: «تظهر شاشة سوداء ويقول ويندوز لا يستجيب ثوانيَ ثم يعود،
لا أعرف ما هذا». وهذا سلوك ويندوز حين لا يعالج خيط الواجهة أحداثه
لثوانٍ: لا يُعاد رسم النافذة فتبقى سوداء، ويُعلن النظام معلَّقاً.
والسبب دائماً عمليةٌ طويلة نُفِّذت على خيط الواجهة.

**المشكلة في تشخيصها**: تقع عند المستخدم لا عند المطوّر، وتزول قبل أن
يُلتقط شيء. فتبقى شكوى بلا دليل.

**ما يفعله الحارس**: نبضةٌ كل نصف ثانية على خيط الواجهة، وخيطٌ خلفي
يراقبها. فإن انقطعت النبضة أكثر من الحدّ التقط **مكدّس خيط الواجهة في
تلك اللحظة** وكتبه في سجل الأخطاء باسم الدالة وملفها وسطرها.

فتصير الشكوى سطراً يُقرأ:

    ⏱ تجمّد 6.2ث — ui/reports/aging_screen.py:210 in refresh

**لا يُعالج التجمّد**: يوثّقه. والعلاج أن تُنقل العملية عن خيط الواجهة
أو تُغلَّف بمؤشر انشغال — وهذا لا يُعرف موضعه إلا بهذا السجل.

**ولا يُثقل شيئاً**: النبضة إسنادُ رقم، والمراقبة خيطٌ نائم يستيقظ كل
نصف ثانية. وما لم يقع تجمّد لا يُكتب حرف.
"""
import os
import sys
import threading
import time
import traceback

# الحدّ الذي يراه المستخدم تجمّداً. ويندوز يُعلن «لا يستجيب» عند نحو
# خمس ثوانٍ؛ نلتقط قبله لنرى ما يقترب منه أيضاً.
STALL_SECONDS = 3.0
TICK_MS = 500
# لا يُكتب أكثر من بلاغ لكل موضع في هذه المدة — فلا يمتلئ السجل
# بتكرار عمليةٍ واحدة بطيئة.
COOLDOWN = 60.0

_state = {"beat": 0.0, "thread": None, "stop": False, "main_id": None,
          "seen": {}, "count": 0}
_lock = threading.Lock()


def _fmt_stack(frame):
    """آخر ما كان يُنفَّذ على خيط الواجهة — أهمّ إطارٍ أولاً."""
    try:
        stack = traceback.extract_stack(frame)
    except Exception:
        return "—", ""
    # نتجاهل أطر Qt ومكتبة بايثون: المفيد أطر النظام نفسه
    ours = [f for f in stack
            if "gold_erp" in (f.filename or "")
            or os.sep + "ui" + os.sep in (f.filename or "")
            or os.sep + "models" + os.sep in (f.filename or "")
            or os.sep + "services" + os.sep in (f.filename or "")]
    tail = (ours or stack)[-6:]
    head = tail[-1] if tail else None
    where = (f"{os.path.basename(head.filename)}:{head.lineno} "
             f"in {head.name}" if head else "—")
    lines = "\n".join(
        f"      {os.path.basename(f.filename)}:{f.lineno} in {f.name}"
        for f in tail)
    return where, lines


def _watch():
    while not _state["stop"]:
        time.sleep(TICK_MS / 1000.0)
        beat = _state["beat"]
        if not beat:
            continue
        gap = time.time() - beat
        if gap < STALL_SECONDS:
            continue
        # التقاط مكدّس خيط الواجهة **أثناء** التجمّد — لا بعده
        frame = sys._current_frames().get(_state["main_id"])
        if frame is None:
            continue
        where, lines = _fmt_stack(frame)
        now = time.time()
        with _lock:
            last = _state["seen"].get(where, 0.0)
            if now - last < COOLDOWN:
                continue
            _state["seen"][where] = now
            _state["count"] += 1
        try:
            from services import health
            health.log_slow(f"تجمّد الواجهة عند {where}", gap,
                            "\n" + lines)
        except Exception:
            pass
        # ننتظر انفراج التجمّد قبل قياس التالي
        while not _state["stop"] and time.time() - _state["beat"] >= \
                STALL_SECONDS:
            time.sleep(TICK_MS / 1000.0)


def start(parent=None):
    """يشغّل الحارس — يُستدعى مرة واحدة بعد فتح النافذة الرئيسية."""
    if _state["thread"] is not None:
        return False
    try:
        from PyQt5 import QtCore
    except Exception:
        return False
    _state["main_id"] = threading.get_ident()
    _state["beat"] = time.time()
    timer = QtCore.QTimer(parent)
    timer.setInterval(TICK_MS)
    timer.timeout.connect(beat)
    timer.start()
    _state["timer"] = timer          # مرجع يمنع جمعه
    th = threading.Thread(target=_watch, daemon=True, name="ui-watchdog")
    _state["thread"] = th
    th.start()
    return True


def beat():
    """نبضة خيط الواجهة — إسنادُ رقمٍ لا أكثر."""
    _state["beat"] = time.time()


def stop():
    _state["stop"] = True
    try:
        t = _state.get("timer")
        if t is not None:
            t.stop()
    except Exception:
        pass
    _state["thread"] = None
    return True


def stalls():
    """عدد التجمّدات المرصودة في هذه الجلسة، ومواضعها."""
    with _lock:
        return {"count": _state["count"],
                "places": sorted(_state["seen"].keys())}
