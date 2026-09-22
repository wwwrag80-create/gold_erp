# -*- coding: utf-8 -*-
"""بوابة النظام — أول ما يراه المستخدم حين ينقر الأيقونة.

**الفكرة**: شاشةٌ كاملة لا نافذةَ صغيرة. ليلٌ دافئ وغبارُ ذهبٍ يرتفع
وخواتمُ تدور، وفي وسطها سطرُ ترحيبٍ وتحته حقلان وزرّ. ثم — بعد
الدخول — لا تُفتح الواجهة فجأةً كمن يُشعل نوراً في وجه نائم، بل
تتّسع موجةٌ ذهبية وتذوب البوابة فيما يظهر النظام خلفها.

**ولماذا البوابة قبل تجهيز القاعدة**: كان الملف التنفيذي يُنشئ
الجداول ويُرقّيها ويبذر الحسابات **قبل** أن يرسم شيئاً، فيقف
المستخدم أمام شاشةٍ سوداء ثوانيَ يظنّ البرنامج معطّلاً. هنا تظهر
البوابة في أول لحظة، ويجري التجهيز وهو يرى سطر حالةٍ يتقدّم —
فالانتظار نفسه صار جزءاً من العرض لا عطلاً فيه.

**والتجهيز على خيط الواجهة بقصد**: لمسُ SQLite من خيطٍ ثانٍ يفتح
باب أعطالٍ لا تُشخَّص، ومكسبُ الثواني لا يساوي ثمنها. تُنفَّذ الخطوة
ثم تُعالَج الأحداث، فتبقى الحركة حيّة والسطر يتقدّم بلا خيوط.
"""
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets

import config
from services import login_flow
from ui.widgets.gold_stage import GoldStage, ShineLabel, animations_on

# اسمُ النظام كما يُخاطَب به صاحبه — لا العنوان التقني
WELCOME = "مرحباً بك في نظام إدارة مصانع الذهب"
ASK_LOGIN = "يرجى تسجيل الدخول"

GATE_QSS = """
/* أولُ إطارٍ يُرسم قبل أن يبدأ المسرح: لو بقي على لون النظام
   الفاتح لرأى المستخدم ومضةً بيضاء قبل الليل. فيُصبغ هنا بلون
   المسرح نفسه — فما يُرى أولاً هو ما يبقى. */
QDialog#gateWindow { background: #17120C; }
QWidget#gateCard {
    background: rgba(28, 22, 14, 218);
    border: 1px solid rgba(201, 162, 39, 110);
    border-radius: 16px;
}
QWidget#gateForm { background: transparent; }
QLabel#gateWelcome { color: #F6E7B6; font-size: 30px; font-weight: bold; }
QLabel#gateHello   { color: #C9A227; font-size: 15px; font-weight: bold; }
QLabel#gateAsk     { color: #E8D9A8; font-size: 16px; }
QLabel#gateNote    { color: #A2916A; font-size: 12px; }
QLabel#gateState   { color: #E3C96B; font-size: 13px; }
QLabel#gateField   { color: #D9C68E; font-size: 13px; font-weight: bold; }
QLineEdit#gateInput {
    background: rgba(255, 252, 244, 20);
    border: 1px solid rgba(201, 162, 39, 90);
    border-radius: 9px; padding: 10px 12px;
    color: #FFF6DC; font-size: 15px;
    selection-background-color: #C9A227; selection-color: #17120C;
}
QLineEdit#gateInput:focus {
    border: 1px solid #E4C665; background: rgba(255, 252, 244, 34);
}
QPushButton#gateEnter {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #D8B23A, stop:1 #A9861E);
    color: #1B1409; border: none; border-radius: 10px;
    padding: 12px 34px; font-size: 16px; font-weight: bold;
}
QPushButton#gateEnter:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #EFCB5A, stop:1 #BE9826);
}
QPushButton#gateEnter:disabled { background: #5A4C2A; color: #9C8C68; }
QPushButton#gateQuit {
    background: transparent; color: #A2916A; border: none;
    padding: 8px 14px; font-size: 13px; font-weight: normal;
}
QPushButton#gateQuit:hover { color: #E8D9A8; }
QPushButton#gateEye {
    background: transparent; color: #A2916A; border: none;
    padding: 0 8px; font-size: 15px; font-weight: normal;
}
QPushButton#gateEye:hover { color: #F0D98A; }
QCheckBox#gateRemember { color: #A2916A; font-size: 12px;
                         background: transparent; padding: 2px; }
QCheckBox#gateRemember::indicator {
    width: 15px; height: 15px; border-radius: 4px;
    border: 1px solid rgba(201, 162, 39, 120);
    background: rgba(255, 252, 244, 18);
}
QCheckBox#gateRemember::indicator:checked {
    background: #D8B23A; border: 1px solid #E4C665;
}
"""


def _emblem(size=104):
    """خاتمٌ بحجرٍ يُرسم رسماً — شعارٌ لا يضيع مع نقل الملفات.

    الملف التنفيذي قد يُنسخ وحده بلا مجلد الأصول، فيُفتح النظام
    بمربّعٍ فارغٍ مكان الشعار. هذا بديلٌ لا ملفَ له.
    """
    pix = QtGui.QPixmap(size, size)
    pix.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    c = size / 2.0
    r = size * 0.34
    ring = QtGui.QLinearGradient(c - r, c - r, c + r, c + r)
    ring.setColorAt(0.0, QtGui.QColor("#F0D98A"))
    ring.setColorAt(0.5, QtGui.QColor("#C9A227"))
    ring.setColorAt(1.0, QtGui.QColor("#8A6F1E"))
    pen = QtGui.QPen(QtGui.QBrush(ring), max(2.0, size * 0.075))
    p.setPen(pen)
    p.setBrush(QtCore.Qt.NoBrush)
    p.drawEllipse(QtCore.QRectF(c - r, c - r + size * 0.07,
                                2 * r, 2 * r))
    # الحجر: معيّنٌ صغير فوق الخاتم
    g = QtGui.QLinearGradient(c, c - r * 1.5, c, c - r * 0.45)
    g.setColorAt(0.0, QtGui.QColor("#FFF6DC"))
    g.setColorAt(1.0, QtGui.QColor("#D8B23A"))
    p.setPen(QtGui.QPen(QtGui.QColor("#8A6F1E"), max(1.0, size * 0.012)))
    p.setBrush(QtGui.QBrush(g))
    s = size * 0.15
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(c, c - r - s * 1.25),
        QtCore.QPointF(c + s, c - r - s * 0.15),
        QtCore.QPointF(c, c - r + s * 0.85),
        QtCore.QPointF(c - s, c - r - s * 0.15)]))
    p.end()
    return pix


def _greeting():
    """تحيّةٌ بحسب الساعة — لمسةٌ صغيرة تجعل الشاشة تُخاطِب لا تُعلن."""
    h = QtCore.QTime.currentTime().hour()
    if 4 <= h < 12:
        return "صباح الخير"
    if 12 <= h < 17:
        return "طاب يومك"
    if 17 <= h < 23:
        return "مساء الخير"
    return "أهلاً بك في هدأة الليل"


class GateWindow(QtWidgets.QDialog):
    """شاشة الترحيب والدخول — تُعاد منها الجلسة في `self.user`."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.user = None
        self._busy = False
        self._ready = False
        self._queue = []            # طابور خطوات التجهيز
        self._failed = []
        self._prep_running = False
        self._card_shown = False
        # يُضبط من `main`: يُنادى بالجلسة بعد نجاح الدخول **والبوابة
        # ما زالت على الشاشة**، فيبني النظام تحتها ثم يطلب التسليم.
        self.on_signed_in = None
        self.setWindowTitle(config.APP_NAME)
        self.setObjectName("gateWindow")
        self.setWindowFlags(QtCore.Qt.Window
                            | QtCore.Qt.FramelessWindowHint)
        self.setLayoutDirection(QtCore.Qt.RightToLeft)
        self.setStyleSheet(GATE_QSS)
        try:
            from services import app_icon
            app_icon.apply(window=self)
        except Exception:
            pass

        # ── المسرح: يملأ الشاشة، وكل شيءٍ بعده فوقه ──
        self.stage = GoldStage(self)
        self.stage.lower()

        self.card = QtWidgets.QWidget(self)
        self.card.setObjectName("gateCard")
        self.card.setFixedWidth(520)
        self._build_card()
        # ══ تُخفى **هنا** لا في `showEvent` ══
        # `showEvent` يصل بعد أول رسمٍ للنافذة، فيُرسم إطارٌ واحد
        # فيه البطاقة كاملةً ثم تختفي — وهي الومضة التي تُرى عند
        # النقر على البرنامج. الإخفاء قبل العرض يمنع رسمها أصلاً.
        if animations_on():
            self.card.hide()

        # ومقاس الشاشة يُؤخذ قبل العرض: نافذةٌ تُرسم بمقاسٍ صغير ثم
        # تتمدّد لملء الشاشة ومضةٌ أخرى — والصحيح أن تولد بمقاسها.
        try:
            scr = QtWidgets.QApplication.primaryScreen()
            if scr is not None:
                self.setGeometry(scr.geometry())
        except Exception:
            pass

        # حركةُ الدخول: الشعار ثم الترحيب ثم البطاقة — بتتابعٍ لطيف
        self._anims = []
        self._intro = QtCore.QVariantAnimation(self)
        self._intro.setStartValue(0.0)
        self._intro.setEndValue(1.0)
        self._intro.setDuration(1400)
        self._intro.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._intro.valueChanged.connect(self._on_intro)
        # المؤثّرات تُرفع عند اكتمال الظهور: مؤثّرُ شفافيةٍ باقٍ على
        # حقلٍ نشط يعيد رسمَه في كل نبضة مؤشّر بلا داعٍ.
        self._intro.finished.connect(self._clear_effects)

        # الموجة: حلقاتٌ تتّسع من موضع البطاقة لحظةَ ظهورها
        self._ripple = QtCore.QVariantAnimation(self)
        self._ripple.setStartValue(0.0)
        self._ripple.setEndValue(1.0)
        self._ripple.setDuration(1250)
        self._ripple.setEasingCurve(QtCore.QEasingCurve.OutQuad)
        self._ripple.valueChanged.connect(self._on_ripple)
        self._ripple.finished.connect(
            lambda: setattr(self.stage, "ripple", -1.0))

        self._exit = QtCore.QVariantAnimation(self)
        self._exit.setStartValue(0.0)
        self._exit.setEndValue(1.0)
        self._exit.setDuration(900)
        self._exit.setEasingCurve(QtCore.QEasingCurve.InCubic)
        self._exit.valueChanged.connect(self._on_exit)
        self._exit.finished.connect(self._exit_done)

    # ─────────────────────────────── البناء
    def _build_card(self):
        lay = QtWidgets.QVBoxLayout(self.card)
        lay.setContentsMargins(38, 30, 38, 26)
        lay.setSpacing(10)

        self.logo = QtWidgets.QLabel()
        self.logo.setAlignment(QtCore.Qt.AlignCenter)
        pix = None
        for path in (getattr(config, "LOGO_GOLD_PATH", None),
                     getattr(config, "LOGO_PATH", None)):
            if path and Path(str(path)).exists():
                cand = QtGui.QPixmap(str(path))
                if not cand.isNull():
                    pix = cand.scaledToWidth(
                        150, QtCore.Qt.SmoothTransformation)
                    break
        # بلا ملف شعار يُرسم خاتمٌ بحجرٍ: البوابة لا تظهر ناقصةً
        # لأن أصلاً لم يُنسخ بجوار الملف التنفيذي.
        self.logo.setPixmap(pix if pix is not None else _emblem(104))
        lay.addWidget(self.logo)

        self.hello = QtWidgets.QLabel(_greeting())
        self.hello.setObjectName("gateHello")
        self.hello.setAlignment(QtCore.Qt.AlignCenter)
        lay.addWidget(self.hello)

        self.welcome = ShineLabel(WELCOME)
        self.welcome.setObjectName("gateWelcome")
        self.welcome.setWordWrap(True)
        lay.addWidget(self.welcome)

        self.ask = QtWidgets.QLabel(ASK_LOGIN)
        self.ask.setObjectName("gateAsk")
        self.ask.setAlignment(QtCore.Qt.AlignCenter)
        lay.addWidget(self.ask)
        lay.addSpacing(6)

        # الحقولُ والزرّ في حاويةٍ واحدة: تظهر مجتمعةً بعد الترحيب،
        # فالعين تقرأ أولاً ثم تُدعى للكتابة — لا الاثنان معاً.
        self.form_box = QtWidgets.QWidget(self.card)
        self.form_box.setObjectName("gateForm")
        lay.addWidget(self.form_box)
        lay = QtWidgets.QVBoxLayout(self.form_box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self.username = QtWidgets.QLineEdit()
        self.username.setObjectName("gateInput")
        self.username.setPlaceholderText("اسم المستخدم")
        self.password = QtWidgets.QLineEdit()
        self.password.setObjectName("gateInput")
        self.password.setPlaceholderText("كلمة المرور")
        self.password.setEchoMode(QtWidgets.QLineEdit.Password)
        self.password.returnPressed.connect(self.try_login)
        self.username.returnPressed.connect(
            lambda: self.password.setFocus())
        for w, label in ((self.username, "اسم المستخدم"),
                         (self.password, "كلمة المرور")):
            cap = QtWidgets.QLabel(label)
            cap.setObjectName("gateField")
            lay.addWidget(cap)
            if w is not self.password:
                lay.addWidget(w)
                continue
            # عينٌ صغيرة تكشف كلمة المرور ما دامت مضغوطة: الخطأ
            # المطبعي في حقلٍ مُقنَّع يُكتشف بعد الرفض لا قبله،
            # ولوحةُ المفاتيح العربية تجعله أكثر وقوعاً.
            row = QtWidgets.QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            row.addWidget(w, 1)
            self.eye = QtWidgets.QPushButton("👁")
            self.eye.setObjectName("gateEye")
            self.eye.setCursor(QtCore.Qt.PointingHandCursor)
            self.eye.setToolTip("اضغط مطوّلاً لإظهار كلمة المرور")
            self.eye.setFocusPolicy(QtCore.Qt.NoFocus)
            self.eye.pressed.connect(
                lambda: self.password.setEchoMode(
                    QtWidgets.QLineEdit.Normal))
            self.eye.released.connect(
                lambda: self.password.setEchoMode(
                    QtWidgets.QLineEdit.Password))
            row.addWidget(self.eye, 0)
            lay.addLayout(row)

        self.remember = QtWidgets.QCheckBox("تذكّر اسمي على هذا الجهاز")
        self.remember.setObjectName("gateRemember")
        last = login_flow.load_last_user()
        if last:
            self.username.setText(last)
            self.remember.setChecked(True)
        lay.addWidget(self.remember)

        self.state = QtWidgets.QLabel("")
        self.state.setObjectName("gateState")
        self.state.setAlignment(QtCore.Qt.AlignCenter)
        self.state.setWordWrap(True)
        self.state.setMinimumHeight(34)
        lay.addWidget(self.state)

        self.btn = QtWidgets.QPushButton("دخول")
        self.btn.setObjectName("gateEnter")
        self.btn.setDefault(True)
        self.btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn.clicked.connect(self.try_login)
        lay.addWidget(self.btn)

        quit_ = QtWidgets.QPushButton("إغلاق البرنامج")
        quit_.setObjectName("gateQuit")
        quit_.setCursor(QtCore.Qt.PointingHandCursor)
        quit_.clicked.connect(self.reject)
        lay.addWidget(quit_, alignment=QtCore.Qt.AlignCenter)

        self.stamp = QtWidgets.QLabel(
            f"{config.COMPANY_NAME}  ·  الإصدار {config.APP_VERSION}"
            f"  ·  {config.BUILD_STAMP}")
        self.stamp.setObjectName("gateNote")
        self.stamp.setAlignment(QtCore.Qt.AlignCenter)
        lay.addWidget(self.stamp)

    # ─────────────────────────────── العرض والحركة
    def showEvent(self, e):
        """المشهد على مرحلتين: مسرحٌ يتنفّس، ثم موجةٌ تُخرج البطاقة.

        **ما كان**: البطاقة تظهر في اللحظة نفسها التي تظهر فيها
        الشاشة، فتبدو مقحمةً على مشهدٍ لم يبدأ بعد — وهو ما يجعل
        الفتح يبدو «غير مرتّب». الآن تُترك الخلفية وحدها نصف ثانية
        حتى تستقرّ العين، ثم ينبثق تموّجٌ من موضع البطاقة وترتفع
        معه: كأن شيئاً لمس السطح فخرج منه ما بعده.
        """
        super().showEvent(e)
        self._layout_card()
        if not animations_on():
            self.card.show()
            self.stage.intro = 1.0
            self._apply_intro(1.0)
            self._start_prepare()
            return
        self.card.hide()
        self.stage.intro = 0.0
        self.stage.setGeometry(self.rect())
        self.stage.start()
        QtCore.QTimer.singleShot(460, self._begin_card)

    def _begin_card(self):
        """تنبثق الموجة وتُرفع البطاقة معها."""
        if not self.isVisible():
            return
        self._layout_card()
        # مركز الموجة = مركز البطاقة، فالحلقات تخرج من تحتها لا من
        # وسط الشاشة — والفرق يُرى وإن لم يُقَل.
        try:
            c = self.card
            self.stage.focus_y = max(0.15, min(0.85, (
                c.y() + c.height() / 2.0) / max(1.0, self.height())))
        except Exception:
            pass
        self._card_shown = True
        self.card.show()
        self.stage.ripple = 0.0
        self._ripple.start()
        self._intro.start()
        self._start_prepare()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.stage.setGeometry(self.rect())
        self._layout_card()

    def _layout_card(self):
        """البطاقة في الوسط — وترتفع قليلاً عن المنتصف فتبدو أخفّ."""
        c = self.card
        c.adjustSize()
        x = int((self.width() - c.width()) / 2)
        y = int((self.height() - c.height()) / 2) - int(self.height() * 0.02)
        c.move(max(0, x), max(0, y) + getattr(self, "_lift", 0))
        c.raise_()

    def _on_intro(self, v):
        self.stage.intro = float(v)
        self._apply_intro(float(v))

    def _apply_intro(self, v):
        """ظهورٌ متدرّج: الشعار أولاً، ثم الترحيب، ثم الحقول.

        **التدرّج بالألوان لا بمؤثّر الشفافية**: مؤثّر Qt يرسم العنصر
        في صورةٍ وسيطة ويُبقيها مخبّأة، فإن تغيّر حجم البطاقة بعد
        تركيبه ظهر النصّ مشوّهاً أو مبتوراً — وهو ما وقع فعلاً في
        أول تجربة. تلوينُ النصّ بشفافيةٍ متدرّجة يُعطي الأثر نفسه
        بلا صورةٍ وسيطة ولا خبيئة تفسد.
        """
        def seg(a, b):
            return max(0.0, min(1.0, (v - a) / max(1e-6, b - a)))

        self._fade_text(self.hello, "#C9A227", seg(0.15, 0.55))
        self._fade_text(self.welcome, "#F6E7B6", seg(0.22, 0.70))
        self._fade_text(self.ask, "#E8D9A8", seg(0.40, 0.85))
        self._fade_pixmap(self.logo, seg(0.00, 0.45))
        self.form_box.setVisible(seg(0.50, 1.00) > 0.01)
        self._set_opacity(self.form_box, seg(0.50, 1.00))
        self._lift = int(26 * (1.0 - seg(0.35, 1.0)))
        self._layout_card()
        self.stage.update()

    @staticmethod
    def _fade_text(label, color, value):
        """يُظهر نصّاً بتلوينه — لا بمؤثّرٍ يُخبّئ رسمه.

        اللون يُكتب في نمطٍ سطري لا في اللوحة (`palette`): ورقة
        الأنماط تحمل لوناً صريحاً لهذه اللافتة، والنمط يغلب اللوحة
        دائماً — فتغييرُ اللوحة وحدها لا يُرى. ويُمحى النمط السطري
        عند اكتمال الظهور فتعود اللافتة لورقة الأنماط.
        """
        c = QtGui.QColor(color)
        v = max(0.0, min(1.0, float(value)))
        label.setStyleSheet(
            f"color: rgba({c.red()}, {c.green()}, {c.blue()}, {v:.3f});")
        pal = label.palette()
        c2 = QtGui.QColor(c)
        c2.setAlphaF(v)
        pal.setColor(QtGui.QPalette.WindowText, c2)
        label.setPalette(pal)
        label.update()

    @staticmethod
    def _fade_pixmap(label, value):
        src = getattr(label, "_src_pix", None)
        if src is None:
            src = label.pixmap()
            if src is None:
                return
            label._src_pix = QtGui.QPixmap(src)
            src = label._src_pix
        v = max(0.0, min(1.0, float(value)))
        if v >= 0.999:
            label.setPixmap(src)
            return
        out = QtGui.QPixmap(src.size())
        out.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(out)
        p.setOpacity(v)
        p.drawPixmap(0, 0, src)
        p.end()
        label.setPixmap(out)

    def _clear_effects(self):
        for w in (self.form_box,):
            try:
                w.setGraphicsEffect(None)
            except Exception:
                pass
        for w in (self.hello, self.welcome, self.ask):
            try:
                w.setStyleSheet("")      # تعود لورقة الأنماط
            except Exception:
                pass
        self._lift = 0
        self._layout_card()

    @staticmethod
    def _set_opacity(widget, value):
        eff = widget.graphicsEffect()
        if not isinstance(eff, QtWidgets.QGraphicsOpacityEffect):
            eff = QtWidgets.QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(eff)
        eff.setOpacity(max(0.0, min(1.0, float(value))))

    # ─────────────────────────────── التجهيز قبل الدخول
    def set_state(self, msg):
        """سطر الحالة — يُرسم بلا `processEvents`.

        الخطوات صارت تُنفَّذ خطوةً في كل نبضة، فالأحداث تُعالَج
        بينها من تلقاء نفسها. ونداءُ `processEvents` داخل نداءِ
        مؤقّتٍ يفتح باب إعادة دخولٍ لا داعي له.
        """
        self.state.setText(str(msg or ""))
        try:
            self.state.repaint()
        except Exception:
            pass

    def prepare(self, steps):
        """يُجدول خطوات التجهيز — خطوةً في كل نبضة، لا حلقةً خانقة.

        **العلة التي كانت**: الخطوات كانت تُنفَّذ في حلقةٍ واحدة مع
        `processEvents` بينها. والحلقة تحتكر خيط الواجهة، فتُبتر
        حركةُ الظهور وتصل البطاقة إلى مكانها قبل أن تُرى وهي
        تتحرّك — فيبدو الفتح قفزةً لا مشهداً.

        الآن تُوضع الخطوات في طابور، وتُنفَّذ **واحدةً في كل نبضة**
        عبر مؤقّت: بين كل خطوتين تعود الأحداث فتُرسم الموجة والغبار
        ويُقرأ سطرُ الحالة. والنتيجة نفسها، والمشهد سليم.
        """
        self._queue = list(steps or [])
        self._failed = []
        self._ready = False
        self.btn.setEnabled(False)
        # إن كانت البطاقة قد ظهرت فعلاً (أو لا حركة أصلاً) يبدأ
        # الطابور فوراً؛ وإلا يبدأ مع ظهورها فلا يُزاحم موجتها.
        if self.isVisible() and (self._card_shown or not animations_on()):
            self._start_prepare()
        return None

    def _start_prepare(self):
        if getattr(self, "_prep_running", False) or not self._queue:
            if not self._queue:
                self._finish_prepare()
            return
        self._prep_running = True
        QtCore.QTimer.singleShot(0, self._next_step)

    def _next_step(self):
        if not self._queue:
            self._prep_running = False
            self._finish_prepare()
            return
        label, fn = self._queue.pop(0)
        self._prep_msg = label
        self.set_state(label)
        try:
            fn()
        except Exception as e:                   # noqa: BLE001
            self._failed.append(f"{label}: {e}")
        QtCore.QTimer.singleShot(0, self._next_step)

    def _finish_prepare(self):
        """ينهي التجهيز — بلا أن يمسح كلاماً ليس كلامَه.

        التجهيز قد ينتهي بعد أن يكون المستخدم قد ضغط «دخول» (فالقاعدة
        جاهزةٌ أصلاً والخطوات سريعة). فلو مسح السطر على عواهنه لمحا
        رسالة خطأٍ أو ترحيبٍ كُتبت بعده — ولا شيء أسوأ من رسالةٍ
        تومض ثم تختفي بلا سبب.
        """
        self._ready = True
        if not self._busy:
            self.btn.setEnabled(True)
        cur = self.state.text()
        mine = cur == getattr(self, "_prep_msg", None)
        if self._failed:
            self.set_state("تنبيه أثناء التجهيز — " + self._failed[0])
        elif mine or not cur:
            self.set_state("")
        if self._busy or self.user:
            return          # الدخول جارٍ — لا يُسرق منه التركيز
        self.username.setFocus()
        if self.username.text().strip():
            self.password.setFocus()
        cb = getattr(self, "on_ready", None)
        if callable(cb):
            cb(not self._failed)
        return not self._failed

    def _on_ripple(self, v):
        self.stage.ripple = float(v)
        self.stage.update()

    # ─────────────────────────────── الدخول
    def try_login(self):
        if self._busy:
            return
        self._busy = True
        self.btn.setEnabled(False)
        try:
            session = login_flow.sign_in(
                self.username.text(), self.password.text(),
                on_progress=self.set_state,
                on_restored=lambda r: self.set_state(
                    "استُرجعت بياناتك من النسخة السحابية"
                    + (f" — آخر نسخة {r.get('when', '')}"
                       if r.get("when") else "")))
        except login_flow.LoginError as e:
            self._busy = False
            self.btn.setEnabled(True)
            self._reject_shake(str(e))
            return
        except Exception as e:                   # noqa: BLE001
            self._busy = False
            self.btn.setEnabled(True)
            self._reject_shake(str(e))
            return
        login_flow.save_last_user(
            self.username.text() if self.remember.isChecked() else "")
        self.user = session
        name = (session.get("full_name") or session.get("username")
                or self.username.text().strip())
        self.state.setText(f"أهلاً {name} — جارٍ فتح النظام…")
        self.form_box.setEnabled(False)
        QtWidgets.QApplication.processEvents()

        # ══ لا `accept()` هنا ══
        # `QDialog.accept` يُخفي النافذة في اللحظة نفسها. والبوابة
        # ملءُ الشاشة، فإخفاؤها يكشف سطحَ المكتب بينما يُبنى النظام
        # خلفها — فيرى صاحبُه البرنامجَ **يُغلق ثم يُفتح**، وهو عكس
        # ما وُضعت له البوابة. لذلك تبقى ظاهرةً ويُبلَّغ من ينتظرها،
        # وهو الذي يبني النظام ثم يطلب التسليم.
        cb = getattr(self, "on_signed_in", None)
        if callable(cb):
            QtCore.QTimer.singleShot(0, lambda: cb(session))
            return
        self.accept()      # مسارٌ احتياطي لمن يستعملها بـ`exec_`

    def fail(self, msg):
        """عطلٌ بعد الدخول: يُقال على البوابة وتُعاد المحاولة منها.

        البديل أن يُغلق كل شيء صامتاً فلا يعرف صاحبُ النظام ما جرى —
        والبوابة أقرب مكانٍ يقرأ فيه الخبر.
        """
        self._busy = False
        self.form_box.setEnabled(True)
        self.btn.setEnabled(True)
        self._reject_shake(str(msg))

    def _reject_shake(self, msg):
        """خطأٌ يُقال في مكانه لا في نافذةٍ تقطع المشهد.

        رسالةٌ حمراء تحت الحقول وهزّةٌ خفيفة للبطاقة: الإشارة تصل في
        أقل من ثانية، ولا تُغلق مربعَ حوارٍ لتعيد المحاولة.
        """
        self.state.setText(str(msg or "تعذّر الدخول"))
        self.state.setStyleSheet("color:#F0A0A0;")
        QtCore.QTimer.singleShot(
            4000, lambda: self.state.setStyleSheet(""))
        self.password.selectAll()
        self.password.setFocus()
        if not animations_on():
            return
        base = self.card.pos()
        anim = QtCore.QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(380)
        import math

        def _move(v):
            dx = int(9 * math.sin(float(v) * math.pi * 6)
                     * (1.0 - float(v)))
            self.card.move(base.x() + dx, base.y())

        anim.valueChanged.connect(_move)
        anim.finished.connect(lambda: self.card.move(base))
        self._anims.append(anim)
        anim.start()

    # ─────────────────────────────── التسليم للنظام
    def hand_off(self, on_done):
        """موجةٌ ذهبية تتّسع، ثم تُسلَّم الشاشة لمن بعدها.

        `on_done()` يُنادى مرةً واحدة عند اكتمال الموجة — وتُنادى ولو
        كانت الحركة مُطفأة، فلا يعتمد فتحُ النظام على زينة.
        """
        self._after_exit = on_done
        if not animations_on():
            self._exit_done()
            return
        for w in (self.card,):
            w.hide()
        self._exit.start()

    def _on_exit(self, v):
        self.stage.exit = float(v)
        self.stage.update()

    def _exit_done(self):
        fn = getattr(self, "_after_exit", None)
        self._after_exit = None
        self.stage.stop()
        if callable(fn):
            fn()

    # ─────────────────────────────── إغلاقٌ آمن
    def keyPressEvent(self, e):
        if e.key() == QtCore.Qt.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(e)

    def closeEvent(self, e):
        self.stage.stop()
        try:
            self.welcome.stop()
        except Exception:
            pass
        super().closeEvent(e)
