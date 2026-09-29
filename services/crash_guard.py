# -*- coding: utf-8 -*-
"""حارس الإقلاع والأعطال — لا يختفي البرنامج صامتاً بعد اليوم.

**العلة التي يعالجها**: الملف التنفيذي يُبنى بلا نافذة سوداء
(`--windowed`)، فلا مكان تُكتب فيه رسالة الخطأ. ومكتبة PyQt5 تُنهي
البرنامج فوراً (`qFatal`) عند أي خطأ بايثون لم يُعالَج داخل حدثٍ من
أحداث الواجهة (رسم · ظهور · مؤقّت) ما لم يُضبط `sys.excepthook`. فكان
خطأٌ واحد في رسم البوابة على جهازٍ ما يُغلق البرنامج قبل أن يُرى —
فيقول صاحبه «البرنامج لا يظهر»، ولا أثر يُشخَّص منه.

الآن:
* **`install()`**: كل خطأ لم يُعالَج يُسجَّل ولا يُنهي البرنامج، ويُقال
  للمستخدم مرةً في رسالة (بعد انتهاء الحدث لا داخله).
* **`trace(stage)`**: سجلّ إقلاع قصير (`logs/startup.log`) يكتب كل
  مرحلة بوقتها — فإن توقّف البرنامج عُرف أين توقّف بالضبط.
* **`fatal(exc)`**: عطلٌ يمنع الإقلاع أصلاً ⇒ يُكتب في
  `logs/crash.log` ويظهر في رسالة ويندوز أصلية (تعمل ولو لم تعمل Qt).

لا يُرسل شيئاً إلى أي مكان — السجلات على الجهاز وحده.
"""
import datetime as _dt
import os
import sys
import tempfile
import threading
import traceback
from pathlib import Path

_STATE = {"trace_started": False, "shown": set(), "count": 0}
MAX_POPUPS = 3


def log_dir():
    """مجلد السجلات: بجوار بيانات النظام، وإلا المجلد المؤقّت."""
    try:
        import config
        d = Path(config.BASE_DIR) / "logs"
    except Exception:
        d = Path(tempfile.gettempdir()) / "JadeiteERP_logs"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        d = Path(tempfile.gettempdir())
    return d


def _stamp():
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def trace(stage):
    """يسجّل مرحلة إقلاع — والملف يبدأ من جديد مع كل تشغيل."""
    try:
        p = log_dir() / "startup.log"
        mode = "a" if _STATE["trace_started"] else "w"
        _STATE["trace_started"] = True
        with open(p, mode, encoding="utf-8") as f:
            if mode == "w":
                f.write(f"# تشغيل {_stamp()} · frozen="
                        f"{bool(getattr(sys, 'frozen', False))} · "
                        f"python {sys.version.split()[0]} · "
                        f"{sys.platform}\n")
            f.write(f"[{_stamp()}] {stage}\n")
    except Exception:
        pass


def traced(label, fn):
    """يلفّ خطوة تجهيز فتُسجَّل بدايتها ونهايتها أو خطؤها."""
    def _run():
        trace(f"بدء: {label}")
        try:
            out = fn()
        except Exception as e:                   # noqa: BLE001
            trace(f"خطأ: {label} — {type(e).__name__}: {e}")
            raise
        trace(f"تم: {label}")
        return out
    return _run


def _write_crash(kind, etype, value, tb):
    text = "".join(traceback.format_exception(etype, value, tb))
    p = log_dir() / "crash.log"
    try:
        if p.exists() and p.stat().st_size > 512 * 1024:
            p.write_text("", encoding="utf-8")
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"\n{'=' * 60}\n[{_stamp()}] {kind}\n{text}")
    except Exception:
        pass
    trace(f"{kind}: {etype.__name__}: {value}")
    try:
        from services.health import log_error
        log_error(kind, value)
    except Exception:
        pass
    return p, text


def _popup_later(title, msg):
    """رسالة Qt بعد انتهاء الحدث الجاري — لا داخل رسمٍ أو مؤقّت."""
    try:
        from PyQt5 import QtCore, QtWidgets
        if QtWidgets.QApplication.instance() is None:
            return

        def _show():
            try:
                box = QtWidgets.QMessageBox()
                box.setIcon(QtWidgets.QMessageBox.Warning)
                box.setWindowTitle(title)
                box.setText(msg)
                box.setLayoutDirection(QtCore.Qt.RightToLeft)
                box.exec_()
            except Exception:
                pass
        QtCore.QTimer.singleShot(0, _show)
    except Exception:
        pass


def _hook(etype, value, tb):
    if issubclass(etype, KeyboardInterrupt):
        return
    p, _text = _write_crash("خطأ غير معالَج", etype, value, tb)
    # مرةً لكل خطأٍ مختلف، وثلاث رسائل على الأكثر في الجلسة
    frame = traceback.extract_tb(tb)[-1] if tb else None
    key = (etype.__name__, frame.filename if frame else "",
           frame.lineno if frame else 0)
    if key in _STATE["shown"] or _STATE["count"] >= MAX_POPUPS:
        return
    _STATE["shown"].add(key)
    _STATE["count"] += 1
    _popup_later("تنبيه — خطأ غير متوقع",
                 f"حدث خطأ غير متوقع ولم يُغلق البرنامج:\n\n"
                 f"{etype.__name__}: {value}\n\n"
                 f"سُجّل التفصيل في:\n{p}")


def _thread_hook(args):
    if args.exc_type is SystemExit:
        return
    _write_crash(f"خطأ في خيط خلفي ({getattr(args.thread, 'name', '?')})",
                 args.exc_type, args.exc_value, args.exc_traceback)


def install():
    """يُركَّب في أول سطرٍ من الإقلاع — قبل Qt وقبل أي نافذة."""
    sys.excepthook = _hook
    try:
        threading.excepthook = _thread_hook
    except Exception:
        pass


def _native_box(title, msg):
    """رسالة ويندوز أصلية — تعمل ولو تعذّر تشغيل Qt نفسها."""
    if os.name == "nt":
        try:
            import ctypes
            # MB_ICONERROR · MB_SETFOREGROUND · MB_TOPMOST · MB_RIGHT ·
            # MB_RTLREADING — فوق كل نافذة، وبالاتجاه العربي
            ctypes.windll.user32.MessageBoxW(
                None, msg, title,
                0x10 | 0x10000 | 0x40000 | 0x80000 | 0x100000)
            return True
        except Exception:
            pass
    try:
        from PyQt5 import QtWidgets
        app = (QtWidgets.QApplication.instance()
               or QtWidgets.QApplication(sys.argv))
        _ = app
        QtWidgets.QMessageBox.critical(None, title, msg)
        return True
    except Exception:
        pass
    try:
        if sys.stderr:
            sys.stderr.write(f"{title}\n{msg}\n")
    except Exception:
        pass
    return False


def fatal(exc):
    """عطلٌ منع الإقلاع: يُسجَّل ويُقال — لا يختفي البرنامج صامتاً."""
    p, text = _write_crash("تعذّر تشغيل البرنامج", type(exc), exc,
                           exc.__traceback__)
    last = text.strip().splitlines()[-1] if text.strip() else str(exc)
    _native_box(
        "تعذّر تشغيل البرنامج",
        "تعذّر تشغيل نظام إدارة مصانع الذهب.\n\n"
        f"{last}\n\n"
        f"سُجّل التفصيل الكامل في:\n{p}\n\n"
        "أرسل هذا الملف مع ملف startup.log الذي بجواره للدعم الفني.")
