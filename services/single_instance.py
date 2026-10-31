# -*- coding: utf-8 -*-
"""نسخةٌ واحدة من البرنامج على الجهاز (5.0.5).

**ما كان يحدث**: البرنامج بطيء الظهور لحظةً أو مُصغَّرٌ في شريط المهام،
فيُنقر رمزه مرةً ثانية — فتعمل نسختان على **قاعدة المصنع نفسها**. كلٌّ
منهما تحفظ وتزامن وتنسخ احتياطياً، فتنتظر إحداهما الأخرى على قفل
الكتابة حتى 30 ثانية: شاشةٌ بيضاء و«لا يستجيب» تتنقّل بين الحالات بلا
سببٍ ظاهر.

**الآن**: النسخة الأولى تفتح قناةً محلية باسمٍ ثابتٍ لهذا التثبيت وهذا
المستخدم. والنسخة الثانية تجدها فتطلب منها الظهور (ترفع نافذتها إلى
الأمام) وتخرج بهدوء. وإن لم تُجب الأولى (مشغولةٌ أو معلّقة) قيل للمستخدم
ذلك بدل أن تُفتح نسخةٌ ثانية تزيد الأمر سوءاً.
"""
import getpass
import hashlib

_TARGET = [None]          # دالةٌ تعيد النافذة التي تُرفع عند الطلب
_SERVER = [None]

PING = b"raise"
PONG = b"ok"
# إعادة التشغيل (بعد تحديثٍ أو استرجاع نسخة) تُطلق النسخة الجديدة قبل أن
# تُغلق القديمة: هذا المتغيّر يقول للجديدة «انتظري خروج القديمة» بدل
# أن تظنّها نسخةً مفتوحة فتخرج — فيبقى المستخدم بلا برنامج.
RELAUNCH_ENV = "GOLD_ERP_RELAUNCH"


def key():
    """اسم القناة: ثابتٌ لهذا التثبيت ولمستخدم ويندوز هذا."""
    try:
        from core.config import BASE_DIR
        base = str(BASE_DIR).lower()
    except Exception:
        base = ""
    try:
        who = getpass.getuser()
    except Exception:
        who = ""
    h = hashlib.sha1(f"{base}|{who}".encode("utf-8")).hexdigest()[:16]
    return f"gold_erp-{h}"


def probe(name, wait_ms=1500):
    """هل نسخةٌ أخرى تعمل؟ — "none" لا · "answered" ردّت وظهرت ·
    "busy" موجودةٌ ولم تردّ (مشغولة أو معلّقة)."""
    from PyQt5 import QtNetwork
    sock = QtNetwork.QLocalSocket()
    sock.connectToServer(name)
    if not sock.waitForConnected(400):
        return "none"
    try:
        sock.write(PING)
        sock.flush()
        sock.waitForBytesWritten(400)
        if sock.waitForReadyRead(int(wait_ms)) and PONG in bytes(
                sock.readAll()):
            return "answered"
        return "busy"
    finally:
        sock.disconnectFromServer()


def _alive(name):
    from PyQt5 import QtNetwork
    sock = QtNetwork.QLocalSocket()
    sock.connectToServer(name)
    ok = sock.waitForConnected(300)
    if ok:
        sock.disconnectFromServer()
    return ok


def _wait_gone(name, seconds=20.0):
    """إعادة تشغيل: ننتظر خروج النسخة السابقة (دون أن نطلب ظهورها)."""
    import time
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if not _alive(name):
            return True
        time.sleep(0.25)
    return False


def set_target(fn):
    """`fn()` تعيد النافذة الظاهرة الآن (البوابة ثم النظام)."""
    _TARGET[0] = fn


def _bring_up():
    fn = _TARGET[0]
    try:
        w = fn() if fn else None
    except Exception:
        w = None
    if w is None:
        return
    try:
        if w.isMinimized():
            w.showMaximized()
        w.raise_()
        w.activateWindow()
        toast = getattr(w, "toast", None)
        if callable(toast):
            toast("البرنامج مفتوحٌ هنا بالفعل — لا تُفتح منه نسخةٌ ثانية.",
                  4000)
    except Exception:
        pass


def _serve(server):
    from PyQt5 import QtCore
    sock = server.nextPendingConnection()
    if sock is None:
        return

    def _read():
        try:
            if PING in bytes(sock.readAll()):
                sock.write(PONG)
                sock.flush()
                QtCore.QTimer.singleShot(0, _bring_up)
        except Exception:
            pass

    sock.readyRead.connect(_read)
    sock.disconnected.connect(sock.deleteLater)


def listen(app, name):
    """تفتح النسخة الأولى قناتها. تعيد True إن نجحت."""
    from PyQt5 import QtNetwork
    # قناةٌ متروكة من تشغيلٍ انتهى فجأة (لينكس/ماك) — لا نسخة خلفها،
    # فقد فشل الاتصال بها قبل الوصول إلى هنا
    QtNetwork.QLocalServer.removeServer(name)
    server = QtNetwork.QLocalServer(app)
    server.setSocketOptions(QtNetwork.QLocalServer.UserAccessOption)
    if not server.listen(name):
        return False
    server.newConnection.connect(lambda: _serve(server))
    _SERVER[0] = server
    return True


def claim(app):
    """يُستدعى بعد إنشاء التطبيق وقبل أي نافذة.

    يعيد True إن كانت هذه هي النسخة الوحيدة فيكمل الإقلاع، وFalse إن
    كانت نسخةٌ أخرى تعمل — فيخرج المستدعي. أي عطلٍ في الآلية نفسها
    لا يمنع التشغيل (يعيد True)."""
    import os
    try:
        name = key()
        if os.environ.pop(RELAUNCH_ENV, None) and not _wait_gone(name, 30):
            # القديمة ما زالت تُغلق (نسخٌ احتياطي عند الخروج مثلاً): نحن
            # إعادة تشغيلٍ مطلوبة لا نقرةٌ ثانية — نُكمل بلا قناة
            return True
        state = probe(name)
    except Exception:
        return True
    if state == "none":
        try:
            listen(app, name)
        except Exception:
            pass
        return True
    if state == "busy":
        try:
            from PyQt5 import QtCore, QtWidgets
            app.setLayoutDirection(QtCore.Qt.RightToLeft)
            QtWidgets.QMessageBox.information(
                None, "البرنامج مفتوح",
                "البرنامج مفتوحٌ بالفعل على هذا الجهاز وهو مشغولٌ الآن.\n\n"
                "انتظر قليلاً ثم انتقل إلى نافذته من شريط المهام.\n"
                "وإن بقي «لا يستجيب» طويلاً فأغلقه من «مدير المهام» ثم"
                " افتحه من جديد — ما كتبته محفوظٌ في المسوّدة.")
        except Exception:
            pass
    return False
