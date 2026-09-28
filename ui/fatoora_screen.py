# -*- coding: utf-8 -*-
"""الربط مع هيئة الزكاة والضريبة والجمارك — بوابة «فاتورة».

نافذةٌ واحدة تجيب عن سؤال صاحب النظام الأول: **هل النظام مربوطٌ فعلاً؟**
ثم تقوده خطوةً خطوة إلى الربط، وتُريه كل فاتورةٍ أُرسلت وما ردّت به
الهيئة. خمسة تبويبات:

  ① الحالة والجاهزية — حكمٌ صريح في الأعلى وقائمةٌ بكل متطلبٍ ونتيجته
  ② بيانات المنشأة — الاسم والرقم الضريبي والسجل والعنوان الوطني
  ③ التسجيل والربط — مفتاح الجهاز · OTP · فحوص الامتثال · الشهادة ·
     التفعيل (كل خطوةٍ عبر الإنترنت تجري في الخلفية فلا تتجمّد النافذة)
  ④ المشترون — العنوان الوطني لكل عميلٍ مسجّل ضريبياً (فواتير B2B)
  ⑤ سجل الفواتير الإلكترونية — العدّاد والحالة وردّ الهيئة وملف XML
"""
import json
import threading

from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from services.fatoora import api, ledger, onboard, readiness
from services.fatoora import profile as pf
from ui.widgets.common import err, info

ICONS = {"ok": "✔", "warn": "⚠", "fail": "✘", "info": "ℹ"}
COLORS = {"ok": "#0F5A24", "warn": "#8A5A00", "fail": "#9A1414",
          "info": "#3A4A66"}
BANNER = {"ok": ("#E6F4EA", "#0F5A24"), "warn": ("#FFF4DB", "#7A4F00"),
          "fail": ("#FBE7E7", "#8A1010")}


class _Job(QtCore.QObject):
    done = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)


class FatooraDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, user=None):
        super().__init__(parent)
        self.user = user or {}
        self._jobs = []
        self.setWindowTitle("الربط مع هيئة الزكاة والضريبة والجمارك — "
                            "الفوترة الإلكترونية")
        self.setLayoutDirection(QtCore.Qt.RightToLeft)
        self.resize(1180, 800)
        lay = QtWidgets.QVBoxLayout(self)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._tab_status(), "① الحالة والجاهزية")
        self.tabs.addTab(self._tab_profile(), "② بيانات المنشأة")
        self.tabs.addTab(self._tab_onboard(), "③ التسجيل والربط")
        self.tabs.addTab(self._tab_buyers(), "④ المشترون (B2B)")
        self.tabs.addTab(self._tab_log(), "⑤ سجل الفواتير الإلكترونية")
        lay.addWidget(self.tabs)
        box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        box.button(QtWidgets.QDialogButtonBox.Close).setText("إغلاق")
        lay.addWidget(box)
        self.tabs.currentChanged.connect(self._on_tab)
        self.refresh_all()

    # ══════════ أدوات ══════════
    def _bg(self, fn, on_done, busy_btn=None):
        """يشغّل `fn` في خيطٍ خلفي — والنافذة حيّة."""
        job = _Job(self)
        self._jobs.append(job)
        if busy_btn is not None:
            busy_btn.setEnabled(False)
            old = busy_btn.text()
            busy_btn.setText("⏳ جارٍ…")

        def _restore():
            if busy_btn is not None:
                busy_btn.setEnabled(True)
                busy_btn.setText(old)

        job.done.connect(lambda r: (_restore(), on_done(r)))
        job.failed.connect(lambda m: (_restore(), err(self, m),
                                      self.refresh_all()))

        def _t():
            try:
                job.done.emit(fn())
            except Exception as e:                    # noqa: BLE001
                job.failed.emit(str(e))

        threading.Thread(target=_t, daemon=True, name="FatooraUI").start()

    def _uname(self):
        return self.user.get("username")

    def _on_tab(self, i):
        if i == 0:
            self.refresh_status()
        elif i == 3:
            self.refresh_buyers()
        elif i == 4:
            self.refresh_log()

    def refresh_all(self):
        self.load_profile()
        self.refresh_status()
        self.refresh_onboard()

    # ══════════ ① الحالة والجاهزية ══════════
    def _tab_status(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        self.banner = QtWidgets.QLabel()
        self.banner.setWordWrap(True)
        self.banner.setTextFormat(QtCore.Qt.RichText)
        v.addWidget(self.banner)
        row = QtWidgets.QHBoxLayout()
        self.score = QtWidgets.QLabel()
        self.score.setObjectName("big")
        row.addWidget(self.score, 1)
        b_ping = QtWidgets.QPushButton("📡 اختبار الاتصال بالبوابة")
        b_ping.setObjectName("ghost")
        b_ping.clicked.connect(lambda: self.test_connection(b_ping))
        b_re = QtWidgets.QPushButton("🔄 إعادة الفحص")
        b_re.clicked.connect(self.refresh_status)
        row.addWidget(b_ping)
        row.addWidget(b_re)
        v.addLayout(row)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["", "المتطلب", "النتيجة"])
        self.tree.setRootIsDecorated(True)
        hh = self.tree.header()
        hh.setSectionResizeMode(0, QtWidgets.QHeaderView.Fixed)
        self.tree.setColumnWidth(0, 44)
        hh.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        v.addWidget(self.tree, 1)
        return w

    def refresh_status(self):
        try:
            with db() as conn:
                r = readiness.run(conn)
        except Exception as e:
            self.banner.setText(f"تعذّر الفحص: {e}")
            return
        level, title, desc = r["verdict"]
        bg, fg = BANNER.get(level, BANNER["warn"])
        self.banner.setStyleSheet(
            f"background:{bg}; color:{fg}; border:1px solid {fg};"
            " border-radius:12px; padding:14px 18px;")
        env_txt = dict(pf.ENVS).get(r["env"], r["env"])
        self.banner.setText(
            f"<div style='font-size:20pt; font-weight:bold'>{title}</div>"
            f"<div style='font-size:12.5pt; margin-top:6px'>{desc}</div>"
            f"<div style='font-size:11pt; margin-top:6px'>البيئة: {env_txt}"
            "</div>")
        done, need = r["score"]
        self.score.setText(f"الجاهزية: {done} من {need} متطلباً متحقّق")
        self.tree.clear()
        groups = {}
        for it in r["items"]:
            g = groups.get(it["section"])
            if g is None:
                g = QtWidgets.QTreeWidgetItem(["", it["section"], ""])
                f = g.font(1)
                f.setBold(True)
                g.setFont(1, f)
                self.tree.addTopLevelItem(g)
                groups[it["section"]] = g
            row = QtWidgets.QTreeWidgetItem(
                [ICONS[it["status"]], it["title"], it["detail"]])
            col = QtGui.QColor(COLORS[it["status"]])
            for c in range(3):
                row.setForeground(c, QtGui.QBrush(col))
            row.setToolTip(2, it["detail"])
            g.addChild(row)
        self.tree.expandAll()
        self._last = r

    def test_connection(self, btn):
        env = self.env.currentData()

        def _done(res):
            ok, st = res
            (info if ok else err)(
                self, ("بوابة فاتورة متاحة من هذا الجهاز ✔"
                       + (f"\nفرق ساعة الجهاز عن ساعة الهيئة: "
                          f"{abs(api.LAST['server_skew']):.0f} ثانية"
                          if api.LAST.get("server_skew") is not None else ""))
                if ok else f"تعذّر الوصول لبوابة فاتورة:\n{st}")
            self.refresh_status()
        self._bg(lambda: api.ping(env), _done, btn)

    # ══════════ ② بيانات المنشأة ══════════
    def _tab_profile(self):
        w = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(w)
        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        self.f = {}
        for key, label, ph in (
                ("name", "الاسم القانوني للمنشأة", "كما في السجل التجاري"),
                ("vat", "الرقم الضريبي", "15 رقماً يبدأ بـ3 وينتهي بـ3"),
                ("crn", "السجل التجاري / المعرّف", "10 أرقام"),
                ("street", "الشارع", ""), ("building", "رقم المبنى",
                                           "4 أرقام"),
                ("plot", "الرقم الإضافي (اختياري)", "4 أرقام"),
                ("district", "الحي", ""), ("city", "المدينة", ""),
                ("postal", "الرمز البريدي", "5 أرقام"),
                ("branch", "اسم الفرع", ""),
                ("industry", "النشاط", "مثال: Gold Jewelry Manufacturing")):
            e = QtWidgets.QLineEdit()
            e.setPlaceholderText(ph)
            self.f[key] = e
            form.addRow(label + ":", e)
        self.scheme = QtWidgets.QComboBox()
        for k, lbl in pf.ID_SCHEMES:
            self.scheme.addItem(lbl, k)
        form.addRow("نوع المعرّف:", self.scheme)
        self.env = QtWidgets.QComboBox()
        for k, lbl in pf.ENVS:
            self.env.addItem(lbl, k)
        form.addRow("بيئة الربط:", self.env)
        self.pm = QtWidgets.QComboBox()
        for k, lbl in pf.PAYMENT_MEANS:
            self.pm.addItem(lbl, k)
        form.addRow("طريقة الدفع الافتراضية:", self.pm)
        outer.addLayout(form)
        self.prof_msg = QtWidgets.QLabel()
        self.prof_msg.setObjectName("warn")
        self.prof_msg.setWordWrap(True)
        outer.addWidget(self.prof_msg)
        b = QtWidgets.QPushButton("💾 حفظ بيانات المنشأة")
        b.clicked.connect(self.save_profile)
        outer.addWidget(b, alignment=QtCore.Qt.AlignLeft)
        outer.addStretch(1)
        return w

    def load_profile(self):
        with db(readonly=True) as conn:
            p = pf.load(conn)
        for k, e in self.f.items():
            e.setText(str(p.get(k, "") or ""))
        for combo, val in ((self.scheme, p.get("crn_scheme")),
                           (self.env, p.get("env")),
                           (self.pm, p.get("payment_means"))):
            i = combo.findData(val)
            if i >= 0:
                combo.setCurrentIndex(i)
        probs = pf.seller_problems(p)
        self.prof_msg.setText("" if not probs else
                              "ينقص: " + "، ".join(probs))

    def save_profile(self):
        data = {k: e.text().strip() for k, e in self.f.items()}
        data.update(crn_scheme=self.scheme.currentData(),
                    env=self.env.currentData(),
                    payment_means=self.pm.currentData())
        try:
            with db() as conn:
                old = pf.load(conn)
                if old.get("env") != data["env"] and old.get("enabled"):
                    data["enabled"] = False       # بيئةٌ جديدة = تسجيلٌ جديد
                p = pf.save(conn, data, self._uname())
        except Exception as e:
            err(self, e)
            return
        probs = pf.seller_problems(p)
        self.prof_msg.setText("" if not probs else
                              "ينقص: " + "، ".join(probs))
        info(self, "حُفظت بيانات المنشأة." + (
            "" if not probs else "\n\nما زال ينقص:\n• " + "\n• ".join(probs)))
        self.refresh_all()

    # ══════════ ③ التسجيل والربط ══════════
    def _tab_onboard(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        self.env_note = QtWidgets.QLabel()
        self.env_note.setWordWrap(True)
        v.addWidget(self.env_note)

        def step(title):
            g = QtWidgets.QGroupBox(title)
            h = QtWidgets.QHBoxLayout(g)
            st = QtWidgets.QLabel()
            st.setWordWrap(True)
            h.addWidget(st, 1)
            v.addWidget(g)
            return h, st

        h1, self.s1 = step("① مفتاح الجهاز وطلب الشهادة (CSR) — على هذا "
                           "الجهاز بلا إنترنت")
        self.b1 = QtWidgets.QPushButton("توليد المفتاح وطلب الشهادة")
        self.b1.clicked.connect(self.do_generate)
        h1.addWidget(self.b1)

        h2, self.s2 = step("② شهادة الامتثال — برمز OTP من بوابة فاتورة")
        self.otp = QtWidgets.QLineEdit()
        self.otp.setPlaceholderText("رمز OTP (6 أرقام)")
        self.otp.setMaximumWidth(170)
        h2.addWidget(self.otp)
        self.b2 = QtWidgets.QPushButton("طلب شهادة الامتثال")
        self.b2.clicked.connect(self.do_compliance)
        h2.addWidget(self.b2)

        h3, self.s3 = step("③ فحوص الامتثال — ستة مستندات تجريبية يتحقّق منها "
                           "خادم الهيئة")
        self.b3 = QtWidgets.QPushButton("تشغيل الفحوص")
        self.b3.clicked.connect(self.do_checks)
        h3.addWidget(self.b3)

        h4, self.s4 = step("④ الشهادة الإنتاجية — بها تُرسل الفواتير الحقيقية")
        self.b4 = QtWidgets.QPushButton("طلب الشهادة الإنتاجية")
        self.b4.clicked.connect(self.do_production)
        h4.addWidget(self.b4)

        h5, self.s5 = step("⑤ الإصدار والإرسال التلقائي مع كل فاتورة")
        self.b5 = QtWidgets.QPushButton("تفعيل")
        self.b5.clicked.connect(self.do_toggle)
        h5.addWidget(self.b5)

        how = QtWidgets.QLabel(
            "<b>من أين رمز OTP؟</b> ادخل بوابة فاتورة "
            "(fatoora.zatca.gov.sa) بحساب المنشأة ← «تسجيل وحدة/جهاز جديد» "
            "← يظهر رمزٌ صالح لساعة واحدة. للتجربة استخدم بوابة المحاكاة "
            "أولاً، ثم أعد الخطوات في «البيئة الرسمية» برمزٍ رسمي.")
        how.setWordWrap(True)
        how.setTextFormat(QtCore.Qt.RichText)
        v.addWidget(how)
        v.addStretch(1)
        return w

    def refresh_onboard(self):
        with db(readonly=True) as conn:
            p = pf.load(conn)
            on = ledger.enabled(conn)
        env = p.get("env") or "simulation"
        st = onboard.stage(env)
        env_lbl = dict(pf.ENVS).get(env, env)
        warn = ("" if env == "production" else
                "<br/><span style='color:#8A5A00'>⚠ في غير البيئة الرسمية لا "
                "يُعتدّ بالفواتير ضريبياً: جرّب بفواتير تجريبية ثم انتقل "
                "للرسمية.</span>")
        self.env_note.setText(f"<b>البيئة الحالية:</b> {env_lbl} — تُغيَّر من "
                              f"«بيانات المنشأة».{warn}")
        self.env_note.setTextFormat(QtCore.Qt.RichText)
        k = st["keys"]
        self.s1.setText(("✔ مولَّد " + k.get("created_at", "")) if st["key"]
                        else "لم يُولَّد بعد")
        comp = k.get("compliance") or {}
        self.s2.setText(("✔ صدرت " + comp.get("at", "")) if st["compliance"]
                        else "لم تصدر")
        checks = st["checks"]
        if checks:
            names = {"standard:invoice": "ضريبية", "standard:credit":
                     "دائن ضريبي", "standard:debit": "مدين ضريبي",
                     "simplified:invoice": "مبسطة", "simplified:credit":
                     "دائن مبسط", "simplified:debit": "مدين مبسط"}
            self.s3.setText("  ".join(
                f"{'✔' if c.get('ok') else '✘'} {names.get(n, n)}"
                for n, c in checks.items()) + (
                "" if st["checks_passed"] == 6 else "\n" + "؛ ".join(
                    e for c in checks.values() for e in c.get("errors", [])
                )[:400]))
        else:
            self.s3.setText("لم تُشغَّل")
        prod = k.get("production") or {}
        self.s4.setText(("✔ صدرت " + prod.get("at", "")
                         + (f" · تنتهي {prod['expires'][:10]}"
                            if prod.get("expires") else ""))
                        if st["production"] else "لم تصدر")
        self.s5.setText("✔ مفعّل — كل فاتورة ضريبية تُصدر إلكترونياً وتُرسل"
                        if on else "غير مفعّل")
        self.b5.setText("إيقاف" if on else "تفعيل")
        self.b2.setEnabled(st["key"])
        self.b3.setEnabled(st["compliance"])
        self.b4.setEnabled(st["checks_passed"] == 6 and st["compliance"])
        self.b5.setEnabled(st["production"])

    def _env(self):
        with db(readonly=True) as conn:
            return pf.load(conn).get("env") or "simulation"

    def do_generate(self):
        env = self._env()
        if onboard.stage(env)["key"]:
            if QtWidgets.QMessageBox.question(
                    self, "مفتاح جديد",
                    "يوجد مفتاحٌ مسجّل لهذه البيئة. توليد مفتاحٍ جديد يُلغي "
                    "شهاداتها ويتطلب التسجيل من جديد برمز OTP. متابعة؟") != \
                    QtWidgets.QMessageBox.Yes:
                return
        try:
            with db() as conn:
                onboard.generate(conn, env, self._uname())
        except Exception as e:
            err(self, e)
            return
        info(self, "وُلّد مفتاح الجهاز وطلب الشهادة وحُفظا على هذا الجهاز.\n"
                   "الخطوة التالية: رمز OTP من بوابة فاتورة.")
        self.refresh_all()

    def do_compliance(self):
        env, otp = self._env(), self.otp.text().strip()
        self._bg(lambda: onboard.request_compliance(env, otp),
                 lambda _r: (info(self, "✔ صدرت شهادة الامتثال.\nالخطوة "
                                        "التالية: فحوص الامتثال."),
                             self.refresh_all()), self.b2)

    def do_checks(self):
        env = self._env()

        def _run():
            with db() as conn:
                return onboard.run_checks(conn, env)

        def _done(res):
            ok = sum(1 for v in res.values() if v["ok"])
            (info if ok == 6 else err)(
                self, f"نجح {ok} من 6 فحوص امتثال."
                + ("\nالخطوة التالية: الشهادة الإنتاجية." if ok == 6 else
                   "\nراجع التفاصيل في الخطوة ③."))
            self.refresh_all()
        self._bg(_run, _done, self.b3)

    def do_production(self):
        env = self._env()
        self._bg(lambda: onboard.request_production(env),
                 lambda _r: (info(self, "✔ صدرت الشهادة الإنتاجية.\nفعّل "
                                        "الإرسال من الخطوة ⑤."),
                             self.refresh_all()), self.b4)

    def do_toggle(self):
        try:
            with db() as conn:
                on = not ledger.enabled(conn)
                if on and QtWidgets.QMessageBox.question(
                        self, "تفعيل الفوترة الإلكترونية",
                        "من الآن: كل فاتورة بيع ضريبية ومرتجعها تُصدر مستنداً "
                        "إلكترونياً مختوماً ويُرسل للهيئة، ولا تُعدَّل "
                        "الفاتورة بعد إصدارها ولا تُحذف (التصحيح بمرتجع).\n\n"
                        "تفعيل؟") != QtWidgets.QMessageBox.Yes:
                    return
                onboard.set_enabled(conn, on, self._uname())
        except Exception as e:
            err(self, e)
            return
        if on:
            ledger.start_worker()
        self.refresh_all()

    # ══════════ ④ المشترون ══════════
    BUYER_COLS = (("name", "العميل"), ("vat", "الرقم الضريبي"),
                  ("street", "الشارع"), ("building", "المبنى"),
                  ("district", "الحي"), ("city", "المدينة"),
                  ("postal", "الرمز البريدي"), ("state", "الحالة"))

    def _tab_buyers(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        self.btable = QtWidgets.QTableWidget(0, len(self.BUYER_COLS))
        self.btable.setHorizontalHeaderLabels([c[1] for c in
                                               self.BUYER_COLS])
        hh = self.btable.horizontalHeader()
        hh.setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        for c in (1, 3, 6):                    # الرقم · المبنى · البريدي
            hh.setSectionResizeMode(c, QtWidgets.QHeaderView.ResizeToContents)
        self.btable.verticalHeader().setVisible(False)
        v.addWidget(self.btable, 1)
        b = QtWidgets.QPushButton("💾 حفظ عناوين المشترين")
        b.clicked.connect(self.save_buyers)
        v.addWidget(b, alignment=QtCore.Qt.AlignLeft)
        return w

    def refresh_buyers(self):
        with db() as conn:
            pf.ensure_tables(conn)
            ids = [r["id"] for r in conn.execute(
                "SELECT id FROM entities WHERE is_deleted=0 AND entity_type"
                " IN ('customer','other') AND"
                " TRIM(COALESCE(vat_number,''))<>'' ORDER BY name")]
            rows = [pf.buyer(conn, i) for i in ids]
        t = self.btable
        t.setRowCount(len(rows))
        for r, b in enumerate(rows):
            probs = pf.buyer_problems(b) if pf.valid_vat(b["vat"]) else \
                ["رقم ضريبي غير صحيح"]
            vals = dict(b, state="✔ مكتمل" if not probs else
                        "✘ ينقص: " + "، ".join(probs))
            for c, (key, _l) in enumerate(self.BUYER_COLS):
                it = QtWidgets.QTableWidgetItem(str(vals.get(key, "") or ""))
                if key in ("name", "vat", "state"):
                    it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
                if key == "state":
                    it.setForeground(QtGui.QBrush(QtGui.QColor(
                        COLORS["ok" if not probs else "fail"])))
                if c == 0:
                    it.setData(QtCore.Qt.UserRole, b["entity_id"])
                t.setItem(r, c, it)

    def save_buyers(self):
        t = self.btable
        try:
            with db() as conn:
                for r in range(t.rowCount()):
                    eid = t.item(r, 0).data(QtCore.Qt.UserRole)
                    data = {key: (t.item(r, c).text() if t.item(r, c) else "")
                            for c, (key, _l) in enumerate(self.BUYER_COLS)
                            if key in pf.BUYER_FIELDS}
                    pf.save_buyer(conn, eid, data)
        except Exception as e:
            err(self, e)
            return
        self.refresh_buyers()
        info(self, "حُفظت عناوين المشترين.")

    # ══════════ ⑤ السجل ══════════
    LOG_COLS = ("العدّاد", "المستند", "النوع", "التاريخ", "الصافي",
                "الضريبة", "الإجمالي", "البيئة", "الحالة", "رسالة الهيئة")

    def _tab_log(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        self.ltable = QtWidgets.QTableWidget(0, len(self.LOG_COLS))
        self.ltable.setHorizontalHeaderLabels(list(self.LOG_COLS))
        self.ltable.verticalHeader().setVisible(False)
        self.ltable.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.ltable.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows)
        self.ltable.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeToContents)
        self.ltable.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.ltable, 1)
        row = QtWidgets.QHBoxLayout()
        b_send = QtWidgets.QPushButton("📤 إرسال المعلّق الآن")
        b_send.clicked.connect(lambda: self.send_now(b_send))
        b_xml = QtWidgets.QPushButton("💾 حفظ ملف XML")
        b_xml.setObjectName("ghost")
        b_xml.clicked.connect(self.save_xml)
        b_resp = QtWidgets.QPushButton("🧾 ردّ الهيئة")
        b_resp.setObjectName("ghost")
        b_resp.clicked.connect(self.show_response)
        for b in (b_send, b_xml, b_resp):
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        return w

    def refresh_log(self):
        with db() as conn:
            ledger.ensure_tables(conn)
            rows = [dict(r) for r in conn.execute(
                "SELECT id, icv, doc_no, kind, subtype, issue_date, net, vat,"
                " gross, env, status, last_error FROM fatoora_documents"
                " WHERE archived=0 ORDER BY icv DESC LIMIT 1000")]
        t = self.ltable
        t.setRowCount(len(rows))
        for r, d in enumerate(rows):
            vals = (str(d["icv"]), d["doc_no"],
                    f"{ledger.KIND_LABELS.get(d['kind'], d['kind'])} "
                    f"{ledger.SUB_LABELS.get(d['subtype'], '')}",
                    d["issue_date"], f"{d['net']:,.2f}", f"{d['vat']:,.2f}",
                    f"{d['gross']:,.2f}", dict(pf.ENVS).get(d["env"],
                                                           d["env"])[:14],
                    ledger.STATUS_LABELS.get(d["status"], d["status"]),
                    d["last_error"] or "")
            for c, val in enumerate(vals):
                it = QtWidgets.QTableWidgetItem(val)
                if c == 0:
                    it.setData(QtCore.Qt.UserRole, d["id"])
                if c == 8:
                    lvl = ("ok" if d["status"] in ledger.ACCEPTED else
                           "fail" if d["status"] == "rejected" else "warn")
                    it.setForeground(QtGui.QBrush(QtGui.QColor(COLORS[lvl])))
                t.setItem(r, c, it)

    def _sel_id(self):
        r = self.ltable.currentRow()
        it = self.ltable.item(r, 0) if r >= 0 else None
        return it.data(QtCore.Qt.UserRole) if it else None

    def send_now(self, btn):
        self._bg(ledger.process_queue,
                 lambda n: (info(self, f"أُرسل {n} مستند."),
                            self.refresh_log(), self.refresh_status()), btn)

    def save_xml(self):
        did = self._sel_id()
        if not did:
            info(self, "اختر مستنداً من الجدول أولاً.")
            return
        with db(readonly=True) as conn:
            d = conn.execute("SELECT doc_no, xml, cleared_xml FROM"
                             " fatoora_documents WHERE id=?",
                             (did,)).fetchone()
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "حفظ ملف الفاتورة الإلكترونية", f"{d['doc_no']}.xml",
            "XML (*.xml)")
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(d["cleared_xml"] or d["xml"])
            info(self, "حُفظ الملف.")

    def show_response(self):
        did = self._sel_id()
        if not did:
            info(self, "اختر مستنداً من الجدول أولاً.")
            return
        with db(readonly=True) as conn:
            d = conn.execute("SELECT response, last_error FROM"
                             " fatoora_documents WHERE id=?",
                             (did,)).fetchone()
        try:
            txt = json.dumps(json.loads(d["response"] or "{}"),
                             ensure_ascii=False, indent=2)
        except Exception:
            txt = d["response"] or ""
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("ردّ الهيئة")
        dlg.resize(760, 520)
        lay = QtWidgets.QVBoxLayout(dlg)
        te = QtWidgets.QPlainTextEdit(
            (d["last_error"] + "\n\n" if d["last_error"] else "")
            + (txt or "لم يُرسل بعد"))
        te.setReadOnly(True)
        te.setLayoutDirection(QtCore.Qt.LeftToRight)
        lay.addWidget(te)
        dlg.exec_()


def open_dialog(parent=None, user=None):
    dlg = FatooraDialog(parent, user)
    dlg.exec_()
    return dlg
