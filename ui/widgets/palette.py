# -*- coding: utf-8 -*-
"""شريط الأوامر الموحّد (Ctrl+K) — بابٌ واحد إلى كل شيء في النظام.

**المشكلة التي يحلّها**: الوصول إلى معلومةٍ واحدة يمرّ اليوم بثلاث
خطوات: تذكّر الشاشة ← فتحها من القائمة ← البحث داخلها. وعدد الشاشات
أربعٌ وثلاثون، فتذكّر أيّها يحمل الجواب عبءٌ بذاته.

**الحل**: نافذة واحدة تُفتح بـ`Ctrl+K` من أي مكان. تكتب فيها ما تعرفه
— اسم عميل، رقم تشغيل، رقم فاتورة، اسم شاشة — فتظهر النتائج مصنَّفةً
وتنتقل بـ`Enter` إلى موضعها مباشرةً. لا تذكّر ولا تنقّل: ما تعرفه
يكفي للوصول.

**الأداء**: فهرس الأسماء والشاشات يُبنى مرة واحدة ويُمرَّر جاهزاً.
وأرقام التشغيل والفواتير لا تُحمَّل إطلاقاً — تُستعلَم عند الكتابة
وحدها وبحدٍّ أعلى ثابت، فالنافذة تفتح فوراً مهما كبرت القاعدة.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from ui.widgets.common import _norm

# أنواع النتائج — النوع يحدّد ما يحدث عند الاختيار
SCREEN, ACCOUNT, WORK_ORDER, INVOICE = "screen", "account", "wo", "invoice"

KIND_ICON = {SCREEN: "▸", ACCOUNT: "👤", WORK_ORDER: "🏷", INVOICE: "🧾"}
KIND_NAME = {SCREEN: "شاشة", ACCOUNT: "حساب", WORK_ORDER: "رقم تشغيل",
             INVOICE: "فاتورة"}

MAX_PER_KIND = 8
MAX_TOTAL = 26


def _score(query, text):
    """رتبة المطابقة: البداية أقوى من الوسط، والأقصر أقوى من الأطول.

    بحثٌ بسيط مقصود: المطلوب ترتيبٌ مفهوم يتوقّعه المستخدم، لا
    خوارزمية تقارب ذكية تفاجئه بنتيجةٍ لا يرى وجه قربها.
    """
    if not query:
        return 50
    i = text.find(query)
    if i < 0:
        return -1
    return (0 if i == 0 else 20 + min(i, 20)) + min(len(text) // 8, 8)


class CommandPalette(QtWidgets.QDialog):
    """نافذة البحث الموحّد. تُعيد النتيجة المختارة عبر `on_pick`."""

    def __init__(self, parent, static_items, on_pick, db_search=None):
        """`static_items`: [(kind, label, hint, payload)] جاهزة في الذاكرة.

        `db_search(text)` اختيارية: تُستدعى عند الكتابة لجلب ما لا
        يُفهرَس مسبقاً (أرقام التشغيل والفواتير) وتُرجع نفس البنية.
        """
        super().__init__(parent)
        self.setObjectName("palette")
        self.setWindowTitle("بحث سريع")
        self.setWindowFlags(QtCore.Qt.Dialog
                            | QtCore.Qt.FramelessWindowHint)
        self.setModal(True)
        self._static = list(static_items or [])
        self._on_pick = on_pick
        self._db_search = db_search
        self._rows = []

        self.input = QtWidgets.QLineEdit()
        self.input.setObjectName("paletteInput")
        self.input.setPlaceholderText(
            "اكتب اسم عميل أو حساب · رقم تشغيل · رقم فاتورة · اسم شاشة…")
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("paletteList")
        hint = QtWidgets.QLabel(
            "↑↓ للتنقّل · Enter للفتح · Esc للإغلاق")
        hint.setObjectName("paletteHint")

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.input)
        lay.addWidget(self.list, 1)
        lay.addWidget(hint)

        # البحث مؤجَّل قليلاً: الكتابة السريعة تُطلق حدثاً لكل حرف،
        # واستعلام القاعدة مع كل حرف يجعل الكتابة نفسها تتلعثم.
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._search)
        self.input.textChanged.connect(lambda *_: self._timer.start())
        self.list.itemActivated.connect(lambda *_: self._accept())
        self.list.itemDoubleClicked.connect(lambda *_: self._accept())
        self.input.installEventFilter(self)

        self.resize(620, 430)
        self._search()

    # ── التنقّل بالأسهم والمؤشر في حقل الكتابة معاً ──
    def eventFilter(self, obj, ev):
        if obj is self.input and ev.type() == QtCore.QEvent.KeyPress:
            k = ev.key()
            if k in (QtCore.Qt.Key_Down, QtCore.Qt.Key_Up):
                n = self.list.count()
                if n:
                    cur = self.list.currentRow()
                    self.list.setCurrentRow(
                        (cur + (1 if k == QtCore.Qt.Key_Down else -1)) % n)
                return True
            if k in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                self._accept()
                return True
        return False

    # ── البحث ──
    def _search(self):
        q = _norm(self.input.text().strip())
        found = {}
        for kind, label, hint, payload in self._static:
            s = _score(q, _norm(label))
            if s < 0 and hint:
                s = _score(q, _norm(hint))
                s = s + 30 if s >= 0 else -1
            if s < 0:
                continue
            found.setdefault(kind, []).append((s, label, hint, payload))
        # ما لا يُفهرَس مسبقاً: يُستعلَم عند الكتابة وحدها
        if q and len(q) >= 1 and self._db_search is not None:
            try:
                for kind, label, hint, payload in self._db_search(
                        self.input.text().strip()):
                    found.setdefault(kind, []).append((0, label, hint,
                                                       payload))
            except Exception:
                pass
        rows = []
        for kind in (ACCOUNT, WORK_ORDER, INVOICE, SCREEN):
            got = sorted(found.get(kind, []), key=lambda x: (x[0], x[1]))
            rows.extend((kind,) + r[1:] for r in got[:MAX_PER_KIND])
        self._fill(rows[:MAX_TOTAL])

    def _fill(self, rows):
        self._rows = rows
        self.list.clear()
        for kind, label, hint, _payload in rows:
            text = f"{KIND_ICON.get(kind, '•')}  {label}"
            if hint:
                text += f"   —  {hint}"
            it = QtWidgets.QListWidgetItem(text)
            it.setToolTip(f"{KIND_NAME.get(kind, '')}: {label}")
            self.list.addItem(it)
        if rows:
            self.list.setCurrentRow(0)
        else:
            it = QtWidgets.QListWidgetItem("لا نتائج — جرّب أول حروف الاسم")
            it.setFlags(QtCore.Qt.NoItemFlags)
            self.list.addItem(it)

    def _accept(self):
        i = self.list.currentRow()
        if not (0 <= i < len(self._rows)):
            return
        kind, _label, _hint, payload = self._rows[i]
        self.accept()
        # الفتح بعد إغلاق النافذة: بناء الشاشة الهدف قد يطول لحظة،
        # فتبقى نافذة البحث معلّقة فوقها لو فُتحت قبل إغلاقها.
        QtCore.QTimer.singleShot(0, lambda: self._on_pick(kind, payload))

    def keyPressEvent(self, ev):
        if ev.key() == QtCore.Qt.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(ev)

    def showEvent(self, ev):
        super().showEvent(ev)
        # تُفتح في ثلث الشاشة العلوي: موضعٌ ثابت متوقَّع، وأقرب للعين
        # من مركز الشاشة تماماً.
        try:
            p = self.parent()
            g = (p.geometry() if p is not None
                 else QtWidgets.QApplication.desktop().availableGeometry())
            self.move(g.center().x() - self.width() // 2,
                      g.top() + max(40, g.height() // 6))
        except Exception:
            pass
        self.input.setFocus(QtCore.Qt.OtherFocusReason)
        self.input.selectAll()


def db_lookup(conn, text, limit=MAX_PER_KIND):
    """أرقام التشغيل والفواتير المطابقة — استعلامان محدودان لا أكثر.

    يُستدعى عند الكتابة فقط. الحدّ الأعلى ثابت: نتيجةٌ تاسعة لا تُقرأ
    أصلاً، وجلبها يُبطئ ما يجب أن يكون فورياً.
    """
    t = (text or "").strip()
    if not t:
        return []
    like = f"%{t}%"
    out = []
    status_ar = {"in_stock": "في المخزون", "sold": "مُباع"}
    try:
        for r in conn.execute(
                "SELECT work_order_no wo, model_no, status, registered_weight w"
                " FROM work_orders WHERE work_order_no LIKE ?"
                " AND is_deleted=0 ORDER BY id DESC LIMIT ?",
                (like, int(limit))):
            bits = []
            if r["model_no"]:
                bits.append(f"موديل {r['model_no']}")
            if r["status"]:
                bits.append(status_ar.get(str(r["status"]), str(r["status"])))
            out.append((WORK_ORDER, f"رقم تشغيل {r['wo']}",
                        " · ".join(bits), str(r["wo"])))
    except Exception:
        pass
    try:
        for r in conn.execute(
                "SELECT i.id, i.invoice_no, i.invoice_date, i.kind,"
                " e.name FROM invoices i"
                " LEFT JOIN entities e ON e.id=i.customer_id"
                " WHERE i.invoice_no LIKE ? AND i.is_deleted=0"
                " ORDER BY i.id DESC LIMIT ?", (like, int(limit))):
            kind = "مرتجع" if "return" in str(r["kind"] or "") else "فاتورة"
            hint = " · ".join(x for x in (r["name"] or "",
                                          str(r["invoice_date"] or "")) if x)
            # الرقم هو الحمولة لا المعرّف: الفتح يمرّ بأرشيف المستندات
            # (معاينة · طباعة · PDF) لا بشاشة التعديل — فالبحث عن
            # فاتورةٍ اطّلاعٌ عليها لا تعديلٌ لها.
            out.append((INVOICE, f"{kind} {r['invoice_no']}", hint,
                        str(r["invoice_no"])))
    except Exception:
        pass
    return out
