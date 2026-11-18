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

from ui import kit

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
            "بوزنه ومع من هو — والبضاعة الواردة بتاريخ. يُفتح على الجوال "
            "<b>بتصميم الكمبيوتر</b>: خمس صور في الصف، والتكبير والتصغير "
            "بالأصابع. يُعرض مباشرةً من هذا الجهاز "
            "<b>بلا سحابة ولا مساحة</b>، ويعمل والبرنامج مفتوح ومتصل.")
        note.setWordWrap(True)
        note.setObjectName("cardSub")

        self.mode = kit.ComboBox()
        for k, lbl in mw.MODES:
            self.mode.addItem(lbl, k)

        self.pin = kit.LineEdit()
        self.pin.setEchoMode(QtWidgets.QLineEdit.Password)
        self.pin.setPlaceholderText("4 إلى 12 خانة — مستحسن")
        self.pin.setMaxLength(12)
        self.pin.setMaximumWidth(200)
        btn_pin = kit.PushButton("حفظ الرمز")
        btn_pin.clicked.connect(self.save_pin)
        btn_nopin = kit.PushButton("بلا رمز")
        btn_nopin.setObjectName("ghost")
        btn_nopin.clicked.connect(lambda: self.save_pin(clear=True))
        self.pin_state = QtWidgets.QLabel("")

        self.btn_on = kit.PushButton("✔ تفعيل الرابط")
        self.btn_on.setObjectName("homeBtn")
        self.btn_on.clicked.connect(self.enable)
        self.btn_off = kit.PushButton("⏹ إيقاف")
        self.btn_off.clicked.connect(self.disable)
        self.btn_new = kit.PushButton("↻ رابط جديد (يُبطل القديم)")
        self.btn_new.setObjectName("ghost")
        self.btn_new.clicked.connect(self.new_link)
        # 4.58: يجرّب الرابط فعلاً من هذا الجهاز طبقةً طبقة ويقول أين انقطع
        self.btn_check = kit.PushButton("🔎 فحص الرابط")
        self.btn_check.setToolTip("يجرّب الرابط من البرنامج إلى الإنترنت "
                                  "ويقول أين ينقطع وما إصلاحه")
        self.btn_check.clicked.connect(self.check)

        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        self.status.setTextFormat(QtCore.Qt.RichText)
        self.status.setOpenExternalLinks(True)

        self.url = kit.LineEdit()
        self.url.setReadOnly(True)
        self.url.setLayoutDirection(QtCore.Qt.LeftToRight)
        self.url.setAlignment(QtCore.Qt.AlignLeft)
        btn_copy = kit.PushButton("📋 نسخ")
        btn_copy.clicked.connect(self.copy)
        btn_open = kit.PushButton("🌐 فتح")
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
        # 5.6.0: تسجيل العمليات من الرابط (بيع · مرتجع · قبض · صرف · قيد ·
        # توريد). 5.6.1: خيارٌ واحد — يُسمح أو لا يُسمح — بلا اشتراط رمز
        self.ops = kit.CheckBox("السماح بتسجيل العمليات من الرابط")
        self.ops.setToolTip("بيع · مرتجع · قبض · صرف · قيد يومي · توريد — "
                            "تُرحَّل في دفاتر هذا الجهاز باسم «رابط المدير»")
        self.ops.toggled.connect(self._ops_toggled)
        g.addWidget(self.ops, 2, 1, 1, 4)
        # 5.7.0: رمزٌ خاص بلوحة «تسجيل العمليات» (والتعديل والحذف والدمج من
        # الرابط) — فلا يسجّل فيها إلا من يعرفه، ولو فُتح الرابط نفسه
        self.ops_pin = kit.LineEdit()
        self.ops_pin.setEchoMode(QtWidgets.QLineEdit.Password)
        self.ops_pin.setPlaceholderText("4 إلى 12 خانة")
        self.ops_pin.setMaxLength(12)
        self.ops_pin.setMaximumWidth(200)
        b_opin = kit.PushButton("حفظ الرمز")
        b_opin.clicked.connect(self.save_ops_pin)
        b_noopin = kit.PushButton("إلغاء الرمز")
        b_noopin.setObjectName("ghost")
        b_noopin.clicked.connect(lambda: self.save_ops_pin(clear=True))
        self.ops_pin_state = QtWidgets.QLabel("")
        g.addWidget(QtWidgets.QLabel("رمز لوحة تسجيل العمليات:"), 3, 0)
        g.addWidget(self.ops_pin, 3, 1)
        g.addWidget(b_opin, 3, 2)
        g.addWidget(b_noopin, 3, 3)
        g.addWidget(self.ops_pin_state, 3, 4)
        # 5.7.6: رمز «قفل التعديل والحذف» — زرٌّ في أعلى صفحات الرابط يقفل
        # التعديل والحذف والعكس والدمج كلها أو يفتحها بهذا الرمز
        self.edit_pin = kit.LineEdit()
        self.edit_pin.setEchoMode(QtWidgets.QLineEdit.Password)
        self.edit_pin.setPlaceholderText("4 إلى 12 خانة")
        self.edit_pin.setMaxLength(12)
        self.edit_pin.setMaximumWidth(200)
        b_epin = kit.PushButton("حفظ الرمز")
        b_epin.clicked.connect(self.save_edit_pin)
        b_noepin = kit.PushButton("إلغاء الرمز")
        b_noepin.setObjectName("ghost")
        b_noepin.setToolTip("يلغي الرمز ويفتح القفل إن كان مقفلاً")
        b_noepin.clicked.connect(lambda: self.save_edit_pin(clear=True))
        self.edit_pin_state = QtWidgets.QLabel("")
        g.addWidget(QtWidgets.QLabel("رمز قفل التعديل والحذف:"), 4, 0)
        g.addWidget(self.edit_pin, 4, 1)
        g.addWidget(b_epin, 4, 2)
        g.addWidget(b_noepin, 4, 3)
        g.addWidget(self.edit_pin_state, 4, 4)
        self.edit_lock = kit.CheckBox(
            "التعديل والحذف في الرابط مقفلان الآن")
        self.edit_lock.setToolTip(
            "يُقفل ويُفتح من زر «🔒» في أعلى صفحات الرابط برمز القفل — "
            "أو من هنا مباشرةً")
        self.edit_lock.toggled.connect(self._edit_lock_toggled)
        g.addWidget(self.edit_lock, 5, 1, 1, 4)
        # 5.8.5: الرابط يعمل دائماً — ولو انطفأت الشاشة أو أُغلقت النافذة
        self.always = kit.CheckBox(
            "الرابط يعمل دائماً: الجهاز لا ينام · البرنامج يبقى في الخلفية"
            " · يبدأ مع ويندوز")
        self.always.setToolTip(
            "ما دام الرابط مفعّلاً: الشاشة تنطفئ وتُقفل كالمعتاد والجهاز يبقى"
            " يعمل ومتصلاً، وإغلاق الغطاء على الكهرباء لا يُنيمه،\nوزرّ الإغلاق"
            " يُخفي البرنامج بجوار الساعة بدل إيقافه، وبعد إعادة تشغيل الجهاز"
            " يبدأ البرنامج والرابط وحدهما،\nوإن نام الجهاز ثم استيقظ عاد"
            " الرابط بلا لمسة. يُرفع كل ذلك عند إيقاف الرابط أو هذا الخيار.")
        self.always.toggled.connect(self._always_toggled)
        g.addWidget(self.always, 6, 1, 1, 4)
        self.always_state = QtWidgets.QLabel("")
        self.always_state.setObjectName("cardSub")
        self.always_state.setWordWrap(True)
        g.addWidget(self.always_state, 7, 1, 1, 4)
        g.setColumnStretch(4, 1)

        acts = QtWidgets.QHBoxLayout()
        acts.addWidget(self.btn_on, 1)
        acts.addWidget(self.btn_check)
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
        self.resize(760, 640)

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
        try:
            from services import manager_web
            with db(readonly=True) as conn:
                on = manager_web.ops_enabled(conn)
            self.ops.blockSignals(True)
            self.ops.setChecked(on)
            self.ops.blockSignals(False)
            with db(readonly=True) as conn:
                self._ops_pin_label(manager_web.has_ops_pin(conn))
                self._edit_lock_label(manager_web.has_edit_pin(conn),
                                      manager_web.edits_locked(conn))
        except Exception:
            pass
        try:
            from services import link_keeper
            self.always.blockSignals(True)
            self.always.setChecked(link_keeper.always_on())
            self.always.blockSignals(False)
            self._always_label()
        except Exception:
            pass
        if st["enabled"]:
            self._run(mw.peek, self._show_peek, "جارٍ قراءة حال الرابط…")
        else:
            self._show(None, "<span style='color:#776b5e'>الرابط موقوف —"
                             " اضغط «تفعيل الرابط»</span>")

    def _always_toggled(self, on):
        try:
            from services import link_keeper
            link_keeper.set_always_on(on, self.user.get("username"))
        except Exception as e:
            err(self, e)
        self._always_label()

    def _always_label(self):
        try:
            from services import link_keeper
            self.always_state.setText(link_keeper.status_text())
        except Exception:
            self.always_state.setText("")

    def _keeper_now(self):
        """بعد التفعيل أو الإيقاف: الجهاز والبدء مع ويندوز يتبعان الرابط."""
        try:
            from services import link_keeper
            link_keeper.apply_now()
        except Exception:
            pass
        QtCore.QTimer.singleShot(400, self._always_label)

    def _ops_toggled(self, on):
        try:
            from database.database import db
            from services import manager_web
            user = (getattr(self, "user", None) or {}).get("username")
            with db() as conn:
                manager_web.set_ops_enabled(conn, on, user)
        except Exception as e:
            err(self, e)

    def save_ops_pin(self, clear=False):
        try:
            from database.database import db
            from services import manager_web
            with db() as conn:
                manager_web.set_ops_pin(
                    conn, "" if clear else self.ops_pin.text(),
                    (getattr(self, "user", None) or {}).get("username"))
            self.ops_pin.clear()
            self._ops_pin_label(not clear)
            info(self, "أُلغي رمز لوحة تسجيل العمليات." if clear else
                 "حُفظ رمز لوحة تسجيل العمليات — يُطلب قبل التسجيل أو التعديل"
                 " أو الحذف أو الدمج من الرابط، ويبقى مفتوحاً على الجهاز 12"
                 " ساعة.")
        except Exception as e:
            err(self, e)

    def save_edit_pin(self, clear=False):
        try:
            from database.database import db
            from services import manager_web
            with db() as conn:
                manager_web.set_edit_pin(
                    conn, "" if clear else self.edit_pin.text(),
                    (getattr(self, "user", None) or {}).get("username"))
                has = manager_web.has_edit_pin(conn)
                locked = manager_web.edits_locked(conn)
            self.edit_pin.clear()
            self._edit_lock_label(has, locked)
            info(self, "أُلغي رمز قفل التعديل والحذف، وفُتح القفل." if clear
                 else "حُفظ رمز قفل التعديل والحذف — زرّ «🔒» في أعلى صفحات "
                 "الرابط يقفل التعديل والحذف والعكس والدمج أو يفتحها بهذا "
                 "الرمز.")
        except Exception as e:
            err(self, e)

    def _edit_lock_toggled(self, on):
        try:
            from database.database import db
            from services import manager_web
            user = (getattr(self, "user", None) or {}).get("username")
            with db() as conn:
                if not manager_web.has_edit_pin(conn):
                    raise ValueError("اضبط رمز القفل أولاً")
                manager_web.set_edits_locked(conn, on, user)
                self._edit_lock_label(True, manager_web.edits_locked(conn))
        except Exception as e:
            try:                       # يُعاد الحال كما هو في الدفاتر
                from database.database import db
                from services import manager_web
                with db(readonly=True) as conn:
                    self._edit_lock_label(manager_web.has_edit_pin(conn),
                                          manager_web.edits_locked(conn))
            except Exception:
                pass
            err(self, e)

    def _edit_lock_label(self, has, locked):
        self.edit_pin_state.setText(
            ("🔒 مقفل الآن" if locked else "✔ برمز — مفتوح الآن") if has
            else "بلا رمز — زرّ القفل في الرابط لا يعمل")
        self.edit_lock.blockSignals(True)
        self.edit_lock.setChecked(bool(locked))
        self.edit_lock.setEnabled(bool(has))
        self.edit_lock.blockSignals(False)

    def _ops_pin_label(self, has):
        self.ops_pin_state.setText(
            "✔ اللوحة برمز" if has
            else "⚠ بلا رمز — يسجّل فيها كل من معه الرابط")

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
        if res.get("ts_down"):
            return self._show(res["url"], (
                "<span style='color:#8B5E1E'><b>هذا رابطك الثابت نفسه — لم"
                " يتغيّر.</b> لكن Tailscale غير متصل على هذا الجهاز الآن، فلا"
                " يُفتح من الجوال حتى يتصل: افتح Tailscale من شريط المهام"
                " وتأكّد أنه «Connected»، ثم اضغط «✔ تفعيل الرابط»."
                "<br><b>لا تضغط «رابط جديد»</b> — فهو وحده يغيّر الرابط.</span>"))
        if st["mode"] != "lan" and res["url"] == res["lan"]:
            return self._show(res["lan"], "<span style='color:#8B5E1E'>"
                              "الرابط الثابت غير مفعّل بعد — هذا رابط شبكة"
                              " المصنع. اضغط «تفعيل الرابط».</span>")
        self._show(res["url"], self._ok_text(st["mode"]))

    def _ok_text(self, mode):
        where = {"funnel": "يُفتح من أي جوال عبر الإنترنت",
                 "serve": "يُفتح على أجهزة المدير التي عليها Tailscale",
                 "lan": "يُفتح من أي جهاز على شبكة المصنع"}[mode]
        return (f"<span style='color:#1E6B33'><b>✔ الرابط مفعّل</b> — "
                f"{where}. يبقى ثابتاً ما دام لم يُضغط «رابط جديد».</span>"
                "<br><span style='color:#776b5e'>للتأكد أنه يُفتح فعلاً"
                " اضغط «🔎 فحص الرابط».</span>")

    def _show_activate(self, res):
        if res.get("ok"):
            return self._show(res["url"], self._ok_text(res["mode"]))
        extra = ""
        for key, label in (("enable_url", "رابط الموافقة على التفعيل"),
                           ("login_url", "رابط تسجيل الدخول في Tailscale")):
            if res.get(key):
                extra += (f"<br><a href='{res[key]}'>افتح {label}</a> ثم"
                          f" اضغط «تفعيل الرابط» مرةً أخرى.")
        fx = mw.fixed_url() if res.get("mode") in ("funnel", "serve") else ""
        if fx:
            # رابطٌ ثابت نجح من قبل: هو نفسه يُعرض — لا رابط الشبكة المحلية
            return self._show(fx, (
                f"<span style='color:#a4262c'><b>{res.get('message') or 'تعذّر التفعيل'}"
                f"</b></span>{extra}<br><span style='color:#8B5E1E'>الرابط"
                " أدناه رابطك الثابت نفسه — لم يتغيّر، ويعود يعمل حين يتصل"
                " Tailscale وتضغط «تفعيل الرابط». لا تضغط «رابط جديد».</span>"))
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
        for b in (self.btn_on, self.btn_off, self.btn_new,
                  self.btn_check):
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
        for b in (self.btn_on, self.btn_off, self.btn_new,
                  self.btn_check):
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

        def _done(res):
            self._show_activate(res)
            self._keeper_now()
        self._run(lambda: mw.activate(uname), _done,
                  "جارٍ تفعيل الرابط… (قد يستغرق ثواني)")

    def disable(self):
        uname = self.user.get("username")
        def _done(_r):
            self._show(None, "<span style='color:#776b5e'>الرابط موقوف — لا"
                             " يُفتح من أي مكان</span>")
            self._keeper_now()
        self._run(lambda: mw.deactivate(uname), _done, "جارٍ الإيقاف…")

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

    # ══════════ فحص الرابط ══════════
    def check(self):
        self._run(mw.diagnose, self._show_diag,
                  "جارٍ فحص الرابط من البرنامج إلى الإنترنت… "
                  "(قد يستغرق نصف دقيقة)")

    @staticmethod
    def diag_text(items):
        """النتيجة نصّاً — تُنسخ وتُرسل كما هي."""
        mark = {True: "✔", False: "✘", None: "•"}
        out = []
        for it in items:
            out.append(f"{mark[it['ok']]} {it['title']}")
            if it["detail"]:
                out.append("    " + it["detail"].replace("\n", "\n    "))
        return "\n".join(out)

    @staticmethod
    def verdict(items):
        """جملة الخلاصة: أين انقطع الطريق — أو أن الرابط سليم."""
        bad = [i for i in items if i["ok"] is False]
        pub = [i for i in items if i["key"] == "public"]
        if not bad and pub and pub[0]["ok"]:
            return (True, "الرابط يعمل من الإنترنت ✔ — إن لم يُفتح على "
                    "جوال المدير: تأكّد أنه يفتح الرابط الذي يبدأ بـ "
                    "https:// (لا رابط 192.168) وأن الإنترنت في الجوال "
                    "يعمل، وجرّب متصفحاً آخر (كروم/سفاري).")
        if not bad:
            return (True, "لا عطل في البرنامج — الرابط المتاح الآن رابط "
                    "شبكة المصنع، فيُفتح والجوال على Wi-Fi المصنع نفسه.")
        b = bad[0]
        return (False, f"موضع الانقطاع: {b['title']}.")

    def _show_diag(self, items):
        import html as _h
        ok, head = self.verdict(items)
        color = {True: "#1E6B33", False: "#a4262c", None: "#776b5e"}
        mark = {True: "✔", False: "✘", None: "•"}
        rows = []
        for it in items:
            det = ""
            if it["detail"]:
                det = ("<div style='color:#555;font-size:12px;"
                       "white-space:pre-wrap' dir='auto'>"
                       f"{_h.escape(it['detail'][:1500])}</div>")
            rows.append(
                f"<div style='margin:6px 0'><b style='color:"
                f"{color[it['ok']]}'>{mark[it['ok']]}</b> "
                f"<b>{_h.escape(it['title'])}</b>{det}</div>")
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("فحص رابط المدير")
        dlg.resize(720, 560)
        lay = QtWidgets.QVBoxLayout(dlg)
        top = QtWidgets.QLabel(head)
        top.setWordWrap(True)
        top.setStyleSheet(f"font-weight:bold;font-size:15px;color:"
                          f"{color[ok]}")
        lay.addWidget(top)
        view = QtWidgets.QTextBrowser()
        view.setOpenExternalLinks(True)
        view.setHtml("".join(rows))
        lay.addWidget(view, 1)
        btns = QtWidgets.QHBoxLayout()
        fixes = {it["fix"]: it for it in items if it["fix"]
                 and it["ok"] is not True}

        def _btn(text, fn):
            b = kit.PushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
            return b

        if "firewall" in fixes:
            def _fw():
                if mw.firewall_allow():
                    info(dlg, "وافق على نافذة ويندوز التي ظهرت، ثم اضغط "
                              "«🔎 فحص الرابط» مرةً أخرى.")
                else:
                    err(dlg, "تعذّر طلب الإذن من ويندوز — شغّل البرنامج "
                             "كمسؤول وأعد المحاولة.")
            _btn("🛡 السماح عبر جدار الحماية", _fw)
        if "activate" in fixes:
            def _act():
                dlg.accept()
                self.enable()
            _btn("↻ إعادة تفعيل الرابط", _act)
        for key, label in (("ts_install", "⬇ تنزيل Tailscale"),
                           ("ts_login", "🔑 تسجيل الدخول في Tailscale")):
            if key in fixes:
                u = fixes[key].get("url") or "https://tailscale.com/download"
                _btn(label, lambda _=False, u=u:
                     QtGui.QDesktopServices.openUrl(QtCore.QUrl(u)))
        txt = self.diag_text(items)

        def _copy():
            QtWidgets.QApplication.clipboard().setText(txt)
            top.setText(head + "  —  📋 نُسخت النتيجة، أرسلها للدعم.")
        _btn("📋 نسخ النتيجة", _copy)
        btns.addStretch(1)
        close = kit.PushButton("إغلاق")
        close.clicked.connect(dlg.accept)
        btns.addWidget(close)
        lay.addLayout(btns)
        self._diag = dlg
        dlg.exec_()

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
