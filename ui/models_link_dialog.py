# -*- coding: utf-8 -*-
"""نافذة «رابط المدير» في دليل الموديلات.

رابطٌ ثابت يفتح الشاشة كاملةً على جوال المدير — مباشرةً من جهاز المصنع
بلا سحابة (`services.models_web`). النافذة تولّده وتنسخه وتعرض رمز QR له،
وتختار نوعه (عبر الإنترنت · خاص · شبكة المصنع)، ورمز الدخول، وتوقفه أو
تبدّله برابطٍ جديد يُبطل القديم.

أوامر Tailscale قد تستغرق ثواني — تجري في خيطٍ خلفي والنافذة لا تتجمّد.
"""
import threading

from PyQt5 import QtCore, QtGui, QtWidgets

from services import models_web as mw
from ui.widgets.common import ask, err, info

STEPS = (
    "<b>الرابط الثابت المجاني — مرةً واحدة فقط:</b><br>"
    "١. على جهاز المصنع: نزّل برنامج <b>Tailscale</b> المجاني من "
    "tailscale.com وسجّل الدخول (حساب مجاني — بلا رسوم ولا نطاق).<br>"
    "٢. ارجع هنا واضغط «تفعيل الرابط». إن ظهر «رابط موافقة» افتحه "
    "ووافق على تفعيل Funnel، ثم اضغط «تفعيل الرابط» مرةً أخرى.<br>"
    "٣. انسخ الرابط وأرسله للمدير — <b>لن يتغيّر بعدها أبداً</b>، "
    "ويعمل كلما كان البرنامج مفتوحاً والإنترنت متصلاً.<br>"
    "• في «الخاص»: ثبّت تطبيق Tailscale على جوال المدير بالحساب نفسه — "
    "فلا يُفتح الرابط إلا على أجهزته.")


class ModelsLinkDialog(QtWidgets.QDialog):
    def __init__(self, parent, user):
        super().__init__(parent)
        self.user = user or {}
        self.setWindowTitle("رابط دليل الموديلات للمدير")
        self.setMinimumWidth(640)
        self._job = None

        note = QtWidgets.QLabel(
            "رابطٌ ثابت يفتح شاشة دليل الموديلات كاملةً على جوال المدير: "
            "كل موديل بصورته، وكم بالخزنة وكم عند المناديب، وكل رقم تشغيل "
            "بوزنه ومع من هو — والبضاعة الواردة بتاريخ. يُعرض مباشرةً من هذا الجهاز "
            "<b>بلا سحابة ولا مساحة</b>، ويعمل والبرنامج مفتوح ومتصل.")
        note.setWordWrap(True)
        note.setObjectName("cardSub")

        self.mode = QtWidgets.QComboBox()
        for k, lbl in mw.MODES:
            self.mode.addItem(lbl, k)

        self.pin = QtWidgets.QLineEdit()
        self.pin.setEchoMode(QtWidgets.QLineEdit.Password)
        self.pin.setPlaceholderText("4 إلى 12 خانة — مستحسن")
        self.pin.setMaxLength(12)
        self.pin.setMaximumWidth(200)
        btn_pin = QtWidgets.QPushButton("حفظ الرمز")
        btn_pin.clicked.connect(self.save_pin)
        btn_nopin = QtWidgets.QPushButton("بلا رمز")
        btn_nopin.setObjectName("ghost")
        btn_nopin.clicked.connect(lambda: self.save_pin(clear=True))
        self.pin_state = QtWidgets.QLabel("")

        self.btn_on = QtWidgets.QPushButton("✔ تفعيل الرابط")
        self.btn_on.setObjectName("homeBtn")
        self.btn_on.clicked.connect(self.enable)
        self.btn_off = QtWidgets.QPushButton("⏹ إيقاف")
        self.btn_off.clicked.connect(self.disable)
        self.btn_new = QtWidgets.QPushButton("↻ رابط جديد (يُبطل القديم)")
        self.btn_new.setObjectName("ghost")
        self.btn_new.clicked.connect(self.new_link)

        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        self.status.setTextFormat(QtCore.Qt.RichText)
        self.status.setOpenExternalLinks(True)

        self.url = QtWidgets.QLineEdit()
        self.url.setReadOnly(True)
        self.url.setLayoutDirection(QtCore.Qt.LeftToRight)
        self.url.setAlignment(QtCore.Qt.AlignLeft)
        btn_copy = QtWidgets.QPushButton("📋 نسخ")
        btn_copy.clicked.connect(self.copy)
        btn_open = QtWidgets.QPushButton("🌐 فتح")
        btn_open.setObjectName("ghost")
        btn_open.clicked.connect(self.open_url)
        self.qr = QtWidgets.QLabel()
        self.qr.setAlignment(QtCore.Qt.AlignCenter)
        self.qr.setFixedSize(176, 176)

        steps = QtWidgets.QLabel(STEPS)
        steps.setWordWrap(True)
        steps.setTextFormat(QtCore.Qt.RichText)
        steps.setObjectName("cardSub")

        g = QtWidgets.QGridLayout()
        g.addWidget(QtWidgets.QLabel("نوع الرابط:"), 0, 0)
        g.addWidget(self.mode, 0, 1, 1, 4)
        g.addWidget(QtWidgets.QLabel("رمز الدخول:"), 1, 0)
        g.addWidget(self.pin, 1, 1)
        g.addWidget(btn_pin, 1, 2)
        g.addWidget(btn_nopin, 1, 3)
        g.addWidget(self.pin_state, 1, 4)
        g.setColumnStretch(4, 1)

        acts = QtWidgets.QHBoxLayout()
        acts.addWidget(self.btn_on, 1)
        acts.addWidget(self.btn_off)
        acts.addWidget(self.btn_new)

        link = QtWidgets.QHBoxLayout()
        link.addWidget(self.url, 1)
        link.addWidget(btn_copy)
        link.addWidget(btn_open)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(note)
        lay.addLayout(g)
        lay.addLayout(acts)
        lay.addWidget(self.status)
        lay.addLayout(link)
        # رمز QR بجانب خطوات الإعداد — لا تحتها، فلا تطول النافذة
        bottom = QtWidgets.QHBoxLayout()
        bottom.addWidget(self.qr, 0, QtCore.Qt.AlignTop)
        bottom.addWidget(steps, 1)
        lay.addLayout(bottom)
        self.resize(760, 600)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._poll)
        self._load()

    # ══════════ الحال ══════════
    def _load(self):
        try:
            from database.database import db
            with db(readonly=True) as conn:
                st = mw.settings(conn)
        except Exception as e:
            err(self, e)
            return
        i = self.mode.findData(st["mode"])
        self.mode.setCurrentIndex(max(i, 0))
        self._pin_label(st["has_pin"])
        if st["enabled"]:
            self._run(mw.peek, self._show_peek, "جارٍ قراءة حال الرابط…")
        else:
            self._show(None, "<span style='color:#776b5e'>الرابط موقوف —"
                             " اضغط «تفعيل الرابط»</span>")

    def _pin_label(self, has):
        self.pin_state.setText("✔ عليه رمز دخول" if has
                               else "⚠ بلا رمز — يفتحه كل من معه الرابط")

    def _show(self, url, html):
        self.status.setText(html)
        self.url.setText(url or "")
        self.qr.clear()
        if url:
            try:
                from services.photo_qr import qr_png_bytes
                pm = QtGui.QPixmap()
                if pm.loadFromData(qr_png_bytes(url, box_size=5)):
                    self.qr.setPixmap(pm.scaled(
                        170, 170, QtCore.Qt.KeepAspectRatio,
                        QtCore.Qt.FastTransformation))
            except Exception:
                pass

    def _show_peek(self, res):
        st = res["settings"]
        if not res["running"]:
            return self._show(None, "<span style='color:#a4262c'>الخادم غير"
                                    " مشغّل — اضغط «تفعيل الرابط»</span>")
        if st["mode"] != "lan" and res["url"] == res["lan"]:
            return self._show(res["lan"], "<span style='color:#8B5E1E'>"
                              "الرابط الثابت غير مفعّل بعد — هذا رابط شبكة"
                              " المصنع. اضغط «تفعيل الرابط».</span>")
        self._show(res["url"], self._ok_text(st["mode"]))

    def _ok_text(self, mode):
        where = {"funnel": "يُفتح من أي جوال عبر الإنترنت",
                 "serve": "يُفتح على أجهزة المدير التي عليها Tailscale",
                 "lan": "يُفتح من أي جهاز على شبكة المصنع"}[mode]
        return (f"<span style='color:#1E6B33'><b>✔ الرابط يعمل</b> — "
                f"{where}. يبقى ثابتاً ما دام لم يُضغط «رابط جديد».</span>")

    def _show_activate(self, res):
        if res.get("ok"):
            return self._show(res["url"], self._ok_text(res["mode"]))
        extra = ""
        for key, label in (("enable_url", "رابط الموافقة على التفعيل"),
                           ("login_url", "رابط تسجيل الدخول في Tailscale")):
            if res.get(key):
                extra += (f"<br><a href='{res[key]}'>افتح {label}</a> ثم"
                          f" اضغط «تفعيل الرابط» مرةً أخرى.")
        self._show(res.get("lan") or None,
                   f"<span style='color:#a4262c'><b>{res.get('message') or 'تعذّر التفعيل'}"
                   f"</b></span>{extra}"
                   + ("<br>الرابط أدناه يعمل على شبكة المصنع وحدها إلى أن"
                      " يكتمل الإعداد." if res.get("lan") else ""))

    # ══════════ الخيط الخلفي ══════════
    def _run(self, fn, done, wait_text):
        if self._job is not None:
            return
        box = {}

        def work():
            try:
                box["res"] = fn()
            except Exception as e:                  # noqa: BLE001
                box["err"] = e
        self._job = (threading.Thread(target=work, daemon=True), box, done)
        for b in (self.btn_on, self.btn_off, self.btn_new):
            b.setEnabled(False)
        self.status.setText(f"<span style='color:#776b5e'>{wait_text}</span>")
        self._job[0].start()
        self._timer.start()

    def _poll(self):
        if self._job is None or self._job[0].is_alive():
            return
        _t, box, done = self._job
        self._job = None
        self._timer.stop()
        for b in (self.btn_on, self.btn_off, self.btn_new):
            b.setEnabled(True)
        if "err" in box:
            self._show(None, f"<span style='color:#a4262c'>{box['err']}</span>")
            return
        done(box.get("res") or {})

    # ══════════ الإجراءات ══════════
    def enable(self):
        try:
            from database.database import db
            with db() as conn:
                mw.set_mode(conn, self.mode.currentData(),
                            self.user.get("username"))
        except Exception as e:
            err(self, e)
            return
        uname = self.user.get("username")
        self._run(lambda: mw.activate(uname), self._show_activate,
                  "جارٍ تفعيل الرابط… (قد يستغرق ثواني)")

    def disable(self):
        uname = self.user.get("username")
        self._run(lambda: mw.deactivate(uname),
                  lambda _r: self._show(None, "<span style='color:#776b5e'>"
                                              "الرابط موقوف — لا يُفتح من أي"
                                              " مكان</span>"),
                  "جارٍ الإيقاف…")

    def new_link(self):
        if not ask(self, "إنشاء رابطٍ جديد؟\n\nالرابط القديم يبطل فوراً ولا"
                         " يُفتح بعدها — أرسل الجديد للمدير."):
            return
        try:
            from database.database import db
            with db() as conn:
                mw.regenerate(conn, self.user.get("username"))
        except Exception as e:
            err(self, e)
            return
        self.enable()

    def save_pin(self, clear=False):
        try:
            from database.database import db
            with db() as conn:
                mw.set_pin(conn, "" if clear else self.pin.text(),
                           self.user.get("username"))
            self.pin.clear()
            self._pin_label(not clear)
            info(self, "أُلغي رمز الدخول." if clear else
                 "حُفظ رمز الدخول — يُطلب مرةً على جوال المدير ويُحفظ فيه"
                 " 30 يوماً.")
        except Exception as e:
            err(self, e)

    def copy(self):
        if self.url.text():
            QtWidgets.QApplication.clipboard().setText(self.url.text())
            self.status.setText(self.status.text()
                                + "<br>📋 نُسخ الرابط — الصقه في واتساب.")

    def open_url(self):
        if self.url.text():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(self.url.text()))

    def closeEvent(self, e):
        self._timer.stop()
        super().closeEvent(e)
