# -*- coding: utf-8 -*-
"""مسرح البوابة ثلاثي الأبعاد (5.3) — مشهدٌ حيّ يُصيَّر لحظةً بلحظة.

**ما الجديد عن المقطع المصوَّر** (`cinema_stage`): ذاك فيديو مسجَّل يتكرّر؛
هذا مشهدٌ ثلاثيّ الأبعاد حقيقي يرسمه كرت الشاشة الآن (WebGL عبر محرّك
Chromium المدمج في Qt — `QtWebEngine`):
  · سبائك ذهبٍ مجسّمة من Blender بختمها المحفور (JADEITE · FINE GOLD ·
    999.9 · 1 KILO) بمادّة ذهبٍ فيزيائية، على أرضٍ سوداء لامعة تعكسها.
  · إضاءة استوديو (صورة بيئة من Poly Haven + صناديق ضوء) وظلالٌ ناعمة،
    وغبارُ ذهبٍ في شعاعٍ مائل، وتوهّجٌ وحبيبٌ سينمائي.
  · الكاميرا تخرج من العتمة وتقترب ثم تدور ببطءٍ حول السبائك.
  · شعار JADEITE مجسّماً في موضع شعار البوابة نفسه: يستدير إلى الأمام
    ثم تعبره لمعة كل بضع ثوانٍ.

**كلّه من القرص**: الصفحة وثلاثة ملفّاتٍ بجوارها (`assets/gate3d`) — لا
إنترنت ولا خوادم. تُبنى من `tools/gate3d` (انظر `build.mjs`).

**والبديل مضمون**: إن غاب محرّك الويب (ملفٌّ تنفيذي قديم)، أو رفض كرت الشاشة
WebGL، أو لم يجهز المشهد في وقته، أو توقّفت عملية العرض — يُطلق `failed`
فتستبدل البوابة به المقطعَ المصوَّر القديم في مكانه، والدخول لا ينتظر شيئاً.

خصائصه هي خصائص `CinemaStage` نفسها (`intro` · `exit` · `card_rect` …) فتعمل
البوابة معه كما هي، ويزيد عليها `set_logo_rect` و`ready` و`failed`.
"""
import os
import sys
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets

# محرّك الويب يُستورد قبل إنشاء التطبيق (شرطٌ من Qt) — هذا الملف يُستورد
# من البوابة قبله. وبعده (اختبارٌ أنشأ التطبيق أولاً) يتعذّر: فلا 3D.
_web = None
_WEB_ERR = ""
# «صندوق العزل» في Chromium يُسقط عملية العرض فوراً (0xC0000005) حين يعمل من
# ملف ويندوز التنفيذي الواحد — ثبت ذلك بفحص ويندوز في GitHub (ومن بايثون
# مباشرةً يعمل). الصفحة هنا ملفٌّ محلّيٌّ واحد من البرنامج نفسه، ممنوعٌ من
# الشبكة ومن الانتقال إلى أي عنوان (انظر `_Page`) — فلا محتوى غريبَ يُعزل
# عنه. يُضبط قبل أن يبدأ المحرّك، ولا يغلب ضبطاً صريحاً من البيئة.
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
try:
    if QtCore.QCoreApplication.instance() is None:
        QtCore.QCoreApplication.setAttribute(
            QtCore.Qt.AA_ShareOpenGLContexts, True)
    from PyQt5 import QtWebEngineWidgets as _web   # noqa: E402
except Exception as _e:                            # ملفٌّ تنفيذيّ بلا المحرّك
    _web = None
    _WEB_ERR = str(_e)

PAGE = "index.html"
FILES = ("index.html", "gate3d.js", "data.js")
BUILT_MS = 7000         # مهلة بناء المشهد (تحميل المجسّمات وتجهيز الإضاءة)
READY_MS = 4000         # ومهلة أول إطارٍ بعد البناء
# حارس السلاسة: بعد أول إطار تُقاس استجابة خيط الواجهة ثوانيَ — إن كان
# عرضُ المشهد يُثقلها (كرتٌ ضعيف أو Qt نفسه يرسم بالمعالج) فالكتابة في
# الحقول تتباطأ، وهذا ما لا يُقبل أبداً: يُستبدل المقطع المصوَّر بالمشهد.
WATCH_DELAY_MS = 1500   # يُترك الإقلاع (تجهيز القاعدة) يمرّ أولاً
WATCH_TICK_MS = 30
WATCH_SAMPLES = 90      # ≈ ثلاث ثوانٍ
WATCH_LAG_MS = 40.0     # وسيط التأخّر فوقه يُعدّ العرضُ ثقيلاً


def too_slow(lags):
    """وسيط تأخّر نبضات الواجهة (م.ث) فوق الحدّ؟ الوسيط لا المتوسّط: خطوةُ
    تجهيزٍ ثقيلةٌ عابرة لا تُحسب على المشهد، والثقلُ الدائم يُحسب."""
    if not lags:
        return False
    s = sorted(lags)
    return s[len(s) // 2] > WATCH_LAG_MS


def forced():
    """`JADEITE_GATE3D=force`: المشهد ولو بالمعالج وبلا حارس — للاختبار وحده."""
    return os.environ.get("JADEITE_GATE3D", "").strip().lower() == "force"


def page_dir():
    """مجلد المشهد: من التحديث المثبَّت أو الحزمة أو المستودع."""
    try:
        import config
        p = Path(config.BUNDLE_DIR) / "assets" / "gate3d"
        if all((p / f).exists() for f in FILES):
            return p
    except Exception:
        pass
    p = Path(__file__).resolve().parents[2] / "assets" / "gate3d"
    return p if all((p / f).exists() for f in FILES) else None


def _version():
    try:
        import config
        return str(getattr(config, "APP_VERSION", ""))
    except Exception:
        return ""


def _memory():
    """ذاكرة الجهاز (سجلّ ويندوز للمستخدم) — لا شيء في مجلد البيانات."""
    return QtCore.QSettings("Jadeite", "Gate3D")


def remembered_failure():
    """تعذّر المشهد على هذا الجهاز في هذا الإصدار؟ (كرتٌ لا يرسم أو بطيء)

    يُتذكّر فلا يُجرَّب في كل فتح ثم يُستبدل أمام صاحبه. وإصدارٌ جديد
    يُجرّبه مرةً أخرى (لعلّ تعريف الكرت تحدّث أو المشهد خفّ).
    """
    try:
        m = _memory()
        if str(m.value("failed_version", "") or "") == _version() != "":
            return str(m.value("failed_reason", "") or "تعذّر سابقاً")
    except Exception:
        pass
    return ""


def remember_failure(why):
    try:
        m = _memory()
        m.setValue("failed_version", _version())
        m.setValue("failed_reason", str(why)[:200])
        m.sync()
    except Exception:
        pass


def why_not():
    """سبب تعذّر المشهد ثلاثي الأبعاد — أو "" إن كان متاحاً."""
    v = os.environ.get("JADEITE_GATE3D", "").strip().lower()
    if v in ("0", "off", "no", "false"):
        return "أُطفئ بالإعداد"
    if not forced():
        old = remembered_failure()
        if old:
            return "تعذّر سابقاً على هذا الجهاز: " + old
    if _web is None:
        return "محرّك الويب غير مضمَّن" + (f" ({_WEB_ERR})" if _WEB_ERR else "")
    if page_dir() is None:
        return "ملفّات المشهد غير موجودة"
    try:
        from ui.widgets.cinema_stage import motion_allowed
        if not motion_allowed():
            return "تقليل الحركة"
    except Exception:
        pass
    return ""


def available():
    return not why_not()


def _trace(msg):
    try:
        from services import crash_guard
        crash_guard.trace("مشهد 3D: " + str(msg))
    except Exception:
        pass


if _web is not None:
    class _Page(_web.QWebEnginePage):
        """صفحة المشهد: رسائله تصل من وحدة التحكّم («GATE3D:…»)."""
        said = QtCore.pyqtSignal(str)

        def javaScriptConsoleMessage(self, level, msg, line, source):
            msg = str(msg or "")
            if msg.startswith("GATE3D:"):
                self.said.emit(msg[7:])
            elif level >= 2:          # خطأ في الصفحة نفسها
                self.said.emit("error " + msg[:300])

        def acceptNavigationRequest(self, url, typ, main):
            # الصفحة محلّية لا تنتقل إلى أي مكان (ولا روابط فيها أصلاً)
            return url.isLocalFile() or url.scheme() in ("about", "data")
else:
    _Page = None


class Gate3DStage(QtWidgets.QWidget):
    """خلفية البوابة: المشهد ثلاثي الأبعاد يملأ الشاشة."""

    uses_overlay = False
    first_paint = QtCore.pyqtSignal()
    ready = QtCore.pyqtSignal()         # أول إطارٍ رُسم فعلاً — يبدأ الترحيب
    failed = QtCore.pyqtSignal(str)     # تعذّر المشهد — يُستبدل به المقطع

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QtGui.QPalette.Window, QtCore.Qt.black)
        self.setPalette(pal)
        # خصائص المسرح — تضبطها البوابة كما مع المقطع
        self.intro = 0.0
        self.exit = 0.0
        self.ripple = -1.0
        self.focus_y = 0.5
        self.logo_center = None
        self.card_rect = None
        self.card_k = 0.0
        self.overlay = None
        self.side = "right"
        self.mode = "movie"
        self.is_ready = False
        self._built = False
        self._dead = False
        self._want_start = False
        self._sent_exit = -1.0
        self._logo = None

        self.view = _web.QWebEngineView(self)
        self.view.setFocusPolicy(QtCore.Qt.NoFocus)
        self.view.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.view.setContextMenuPolicy(QtCore.Qt.NoContextMenu)
        self.page = _Page(self.view)
        self.page.setBackgroundColor(QtCore.Qt.black)
        self.page.said.connect(self._on_said)
        self.page.loadFinished.connect(self._on_loaded)
        self.page.renderProcessTerminated.connect(self._on_crash)
        S = _web.QWebEngineSettings
        st = self.page.settings()
        for attr, on in (("WebGLEnabled", True), ("Accelerated2dCanvasEnabled", True),
                         ("LocalContentCanAccessFileUrls", True),
                         ("LocalContentCanAccessRemoteUrls", False),
                         ("JavascriptCanOpenWindows", False),
                         ("ShowScrollBars", False), ("ErrorPageEnabled", False),
                         ("FocusOnNavigationEnabled", False),
                         ("PluginsEnabled", False), ("AutoLoadImages", True)):
            a = getattr(S, attr, None)
            if a is not None:
                st.setAttribute(a, on)
        self.view.setPage(self.page)
        self.view.setGeometry(self.rect())
        self.view.hide()                # يظهر مع أول إطار — لا ومضةَ بيضاء

        self._built_timer = QtCore.QTimer(self, singleShot=True)
        self._built_timer.timeout.connect(lambda: self._fail("لم يُبنَ المشهد في وقته"))
        self._ready_timer = QtCore.QTimer(self, singleShot=True)
        self._ready_timer.timeout.connect(lambda: self._fail("لم يُرسم أول إطار"))
        self._built_timer.start(BUILT_MS)
        self._watch = QtCore.QTimer(self)
        self._watch.setTimerType(QtCore.Qt.PreciseTimer)
        self._watch.setInterval(WATCH_TICK_MS)
        self._watch.timeout.connect(self._watch_tick)
        self._lags = []
        self._last_tick = None
        url = QtCore.QUrl.fromLocalFile(str(page_dir() / PAGE))
        if forced():
            url.setQuery("soft=1")
        self.view.load(url)
        _trace("تحميل الصفحة")

    # ─────────────────────────────── من الصفحة
    def _on_said(self, msg):
        kind = msg.split(" ", 1)[0]
        if kind == "built":
            self._built = True
            self._built_timer.stop()
            self.view.show()            # الصفحة سوداء — والمشهد يبدأ من العتمة
            if self._logo is not None:
                self._js("gate3d.setLogoRect(%f,%f,%f,%f)" % self._logo)
            if self._want_start:
                self._kick()
        elif kind == "ready":
            self._ready_timer.stop()
            if not self.is_ready:
                self.is_ready = True
                _trace("جاهز " + msg[6:80])
                self.ready.emit()
                if not forced():
                    QtCore.QTimer.singleShot(WATCH_DELAY_MS, self._watch_start)
        elif kind == "nogl":            # كرتٌ لا يرسم WebGL2 أو يرسم بالمعالج
            self._fail(msg, remember=True)
        elif kind == "fail":
            self._fail(msg)
        elif kind in ("tier", "fps"):
            _trace(msg)
        elif kind == "error" and not self._built:
            _trace(msg)

    # ─────────────────────────────── حارس السلاسة
    def _watch_start(self):
        if self._dead or not self.isVisible():
            return
        self._lags = []
        self._last_tick = None
        self._clock = QtCore.QElapsedTimer()
        self._clock.start()
        self._watch.start()

    def _watch_tick(self):
        now = self._clock.elapsed()
        if self._last_tick is not None:
            self._lags.append(max(0.0, now - self._last_tick - WATCH_TICK_MS))
        self._last_tick = now
        if len(self._lags) < WATCH_SAMPLES:
            return
        self._watch.stop()
        lags = sorted(self._lags)
        med = lags[len(lags) // 2]
        _trace("استجابة الواجهة: وسيط التأخّر %.0f م.ث" % med)
        if too_slow(self._lags):
            self._fail("العرض يُثقل الواجهة (%.0f م.ث)" % med, remember=True)

    def _on_loaded(self, ok):
        if not ok:
            self._fail("تعذّر فتح صفحة المشهد")

    def _on_crash(self, status, code):
        self._fail(f"توقّفت عملية العرض ({int(status)}/{code})")

    def _fail(self, why, remember=False):
        if self._dead:
            return
        if remember and not forced():
            remember_failure(why)
        self._dead = True
        self._built_timer.stop()
        self._ready_timer.stop()
        self._watch.stop()
        _trace("تعذّر: " + str(why))
        self.failed.emit(str(why))

    def _js(self, code):
        if self._dead:
            return
        try:
            self.page.runJavaScript("window.gate3d&&" + code)
        except Exception:
            pass

    # ─────────────────────────────── واجهة المسرح
    def _kick(self):
        """أول تشغيل: المشهد يخرج من العتمة — ويُنتظر أول إطارٍ منه."""
        if getattr(self, "_kicked", False):
            return
        self._kicked = True
        self._ready_timer.start(READY_MS)
        self._js("gate3d.start()")

    def start(self):
        self._want_start = True
        if not self._built:
            return                      # يبدأ حين يُبنى
        if getattr(self, "_kicked", False):
            self._js("gate3d.resume()")
        else:
            self._kick()

    def stop(self):
        self._js("gate3d.pause()")

    def set_exit(self, v):
        v = max(0.0, min(1.0, float(v)))
        self.exit = v
        if abs(v - self._sent_exit) >= 0.01 or v in (0.0, 1.0):
            self._sent_exit = v
            self._js("gate3d.setExit(%f)" % v)

    def set_logo_rect(self, rect):
        """الشعار المجسّم في هذا المستطيل (إحداثيات المسرح) — أو None لإخفائه."""
        if rect is None:
            self._logo = None
            self._js("gate3d.hideLogo()")
            return
        r = QtCore.QRectF(rect)
        logo = (r.center().x(), r.center().y(), r.width(), r.height())
        if logo == self._logo:
            return
        self._logo = logo
        self._js("gate3d.setLogoRect(%f,%f,%f,%f)" % logo)

    @property
    def disposed(self):
        return bool(getattr(self, "_disposed", False))

    def dispose(self):
        """يُطلق كرت الشاشة وعملية العرض بعد أن تغيب البوابة."""
        if getattr(self, "_disposed", False):
            return
        self._disposed = True
        self._dead = True
        self._built_timer.stop()
        self._ready_timer.stop()
        self._watch.stop()
        try:
            self.view.setUrl(QtCore.QUrl("about:blank"))
            self.view.deleteLater()
            self.page.deleteLater()
        except Exception:
            pass

    # ─────────────────────────────── Qt
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.view.setGeometry(self.rect())

    def showEvent(self, e):
        super().showEvent(e)
        QtCore.QTimer.singleShot(0, self._announce)

    def _announce(self):
        if not getattr(self, "_announced", False):
            self._announced = True
            self.first_paint.emit()


def make_stage(parent):
    """المسرح المناسب لهذا الجهاز: ثلاثي الأبعاد إن أمكن، وإلا المقطع."""
    why = why_not()
    if not why:
        try:
            return Gate3DStage(parent)
        except Exception as e:          # لا يمنع الدخولَ مسرحٌ أبداً
            why = f"تعذّر إنشاؤه ({e})"
    _trace("المقطع المصوَّر بدلاً منه: " + why)
    from ui.widgets.cinema_stage import CinemaStage
    return CinemaStage(parent)
