# -*- coding: utf-8 -*-
"""شاشة «الحركة اليومية» (5.6.0) — كل عمليات يومٍ واحد بنظرةٍ واحدة.

يختار المستخدم اليوم (اليوم · أمس · أي تاريخ)، فتظهر عمليات ذلك اليوم
كلها — ثم يفرزها بزرّ نوعها: «المبيعات» يُظهر فواتير البيع وحدها باسم
العميل والوزن الذي أخذه، و«القبض» السندات… وفي كل سطرٍ «📄 عرض» يفتح
المستند كما يُطبع، و«🖼 الصور» يفتح صور موديلاته بأرقام تشغيلها (للفواتير
والتوريد والمشتريات الضريبية).

المصدر `models.day_feed.day` — المصدر نفسه الذي يقرأ منه رابط المدير،
فلا يختلف ما يراه المدير في الرابط عمّا في الشاشة. قراءةٌ محضة.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from ui import kit

from database.database import db
from models import day_feed
from services import karat_view as kv
from services import numfmt as _nf
from ui.widgets.common import StatChip as Chip
from ui.widgets.common import (date_edit, dstr, err, make_table, num_item,
                               text_item, title_label)
from ui.widgets.table_fit import fit_columns

FILTERS = (("all", "الكل"),) + tuple(
    (k, t) for k, t in day_feed.GROUPS)
SHORT = {"sale": "مبيعات", "sale_return": "مرتجع", "receipt": "قبض",
         "payment": "صرف", "supply": "توريد", "purchase": "مشتريات",
         "manual": "قيد يومي", "fixing": "تسكير", "other": "أخرى"}
COLOR = {"sale": "#1E7B45", "sale_return": "#B4232A", "receipt": "#1E6B8F",
         "payment": "#8B5E1E", "supply": "#A8822E", "purchase": "#6B4FA0",
         "manual": "#555555", "fixing": "#2F6F6F", "other": "#777777"}
COLS = ["النوع", "رقم المستند", "الجهة", "الوزن", "الأجور / النقد",
        "الوقت", "المستخدم", ""]


class DailyMovesScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.data = None
        self.docs = []
        self.shown = []
        self.group = "all"

        self.date = date_edit()
        self.date.dateChanged.connect(lambda *_: self.reload())
        b_today = kit.PushButton("اليوم")
        b_today.clicked.connect(lambda: self._go(0))
        b_yest = kit.PushButton("أمس")
        b_yest.clicked.connect(lambda: self._go(-1))
        b_prev = kit.PushButton("◀ السابق")
        b_prev.setObjectName("ghost")
        b_prev.clicked.connect(lambda: self._step(-1))
        b_next = kit.PushButton("التالي ▶")
        b_next.setObjectName("ghost")
        b_next.clicked.connect(lambda: self._step(1))
        self.search = kit.LineEdit()
        self.search.setPlaceholderText("ابحث بالجهة أو رقم المستند أو رقم"
                                       " التشغيل أو الموديل…")
        self.search.textChanged.connect(lambda *_: self._render())
        self.day_lbl = QtWidgets.QLabel("")
        self.day_lbl.setObjectName("cardSub")
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("اليوم:"))
        top.addWidget(self.date)
        for b in (b_today, b_yest, b_prev, b_next):
            top.addWidget(b)
        top.addWidget(self.day_lbl)
        top.addSpacing(12)
        top.addWidget(self.search, 1)

        # أزرار الفرز — بعدد كل نوعٍ في اليوم
        self.fbar = QtWidgets.QHBoxLayout()
        self.fbar.setSpacing(6)
        self.fbtn = {}
        grp = QtWidgets.QButtonGroup(self)
        grp.setExclusive(True)
        for key, label in FILTERS:
            b = kit.PushButton(label)
            b.setCheckable(True)
            b.clicked.connect(lambda _c=False, k=key: self._pick(k))
            grp.addButton(b)
            self.fbtn[key] = (b, label)
            self.fbar.addWidget(b)
        self.fbar.addStretch(1)
        self.fbtn["all"][0].setChecked(True)
        self._mark()

        self.c_n = Chip("المستندات")
        self.c_sale = Chip("المبيعات")
        self.c_ret = Chip("المرتجع")
        self.c_rc = Chip("القبض")
        self.c_py = Chip("الصرف")
        self.c_cash = Chip("الصندوق النقدي", summary=True)
        chips = QtWidgets.QHBoxLayout()
        for c in (self.c_n, self.c_sale, self.c_ret, self.c_rc, self.c_py,
                  self.c_cash):
            chips.addWidget(c, 1)

        self.tbl = make_table()
        self.tbl.setColumnCount(len(COLS))
        self.tbl.setHorizontalHeaderLabels(COLS)
        self.tbl.cellDoubleClicked.connect(lambda r, _c: self.view(r))
        fit_columns(self.tbl, [9, 12, 26, 11, 13, 7, 9, 13])
        self.hint = QtWidgets.QLabel(
            "نقرٌ مزدوج على السطر يفتح المستند · «🖼 الصور» صور موديلاته "
            "بأرقام تشغيلها")
        self.hint.setObjectName("cardSub")

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("الحركة اليومية"))
        lay.addLayout(top)
        lay.addLayout(self.fbar)
        lay.addLayout(chips)
        lay.addWidget(self.tbl, 1)
        lay.addWidget(self.hint)
        self._loaded = False

    def showEvent(self, e):
        super().showEvent(e)
        self.reload()

    def refresh(self):
        self.reload()

    # ══════════ اليوم ══════════
    def _go(self, days):
        self.date.setDate(QtCore.QDate.currentDate().addDays(days))

    def _step(self, days):
        d = self.date.date().addDays(days)
        if d > QtCore.QDate.currentDate():
            return
        self.date.setDate(d)

    def reload(self):
        try:
            with db(readonly=True) as conn:
                self.data = day_feed.day(conn, dstr(self.date))
        except Exception as e:                       # noqa: BLE001
            err(self, e)
            return
        self.docs = [d for g in self.data["groups"] for d in g["docs"]]
        self.docs.sort(key=lambda d: (d.get("time") or "", d["eid"]),
                       reverse=True)
        d = self.date.date()
        t = QtCore.QDate.currentDate()
        self.day_lbl.setText("اليوم" if d == t else
                             "أمس" if d == t.addDays(-1) else
                             d.toString("dddd"))
        counts = {}
        for x in self.docs:
            counts[x["group"]] = counts.get(x["group"], 0) + 1
        for key, (b, label) in self.fbtn.items():
            n = len(self.docs) if key == "all" else counts.get(key, 0)
            b.setText(f"{label} ({n})" if n else label)
            b.setVisible(key == "all" or n > 0 or key == self.group)
        self._summary()
        self._render()

    def _summary(self):
        u = kv.unit()
        by = {g["key"]: g["totals"] for g in self.data["groups"]}
        self.c_n.set_value(str(self.data["count"]))

        def sets(key):
            t = by.get(key)
            if not t:
                return "—", ""
            return (f"{_nf.f2(kv.g(t.get('weight', 0)))} {u}",
                    f"{t['count']} فاتورة · {t.get('sets', 0)} طقم")

        def vouch(key):
            t = by.get(key)
            if not t:
                return "—", ""
            parts = []
            if t.get("gold_equiv"):
                parts.append(f"{_nf.f2(kv.g(t['gold_equiv']))} {u}")
            if t.get("cash"):
                parts.append(f"{_nf.f2(t['cash'])} ريال")
            return (" · ".join(parts) or "—", f"{t['count']} سند")
        for chip, val in ((self.c_sale, sets("sale")),
                          (self.c_ret, sets("sale_return")),
                          (self.c_rc, vouch("receipt")),
                          (self.c_py, vouch("payment"))):
            chip.set_value(val[0], val[1])
        sm = self.data["summary"]
        self.c_cash.set_value(
            f"{_nf.f2(sm['cash_net'])} ريال",
            f"داخل {_nf.f2(sm['cash_in'])} · خارج {_nf.f2(sm['cash_out'])}")

    # ══════════ الفرز والجدول ══════════
    def _pick(self, key):
        self.group = key
        self._mark()
        self._render()

    def _mark(self):
        """الزر المختار بلونه — والبقية خفيفة (ghost)."""
        for key, (b, _l) in self.fbtn.items():
            on = key == self.group
            b.setChecked(on)
            name = "" if on else "ghost"
            if b.objectName() != name:
                b.setObjectName(name)
                b.style().unpolish(b)
                b.style().polish(b)

    @staticmethod
    def _keys(d):
        out = [d["no"], d.get("party"), d.get("op"), d.get("desc")]
        det = d.get("detail") or {}
        for m in det.get("models") or []:
            out.append(m["model"])
            out += [i["wo"] for i in m["items"]]
        return " ".join(str(x) for x in out if x).lower()

    def _amount(self, d):
        det = d.get("detail") or {}
        g = d["group"]
        if g in ("sale", "sale_return") and det:
            return f"أجور {_nf.f2(det.get('wages', 0))}"
        if g in ("receipt", "payment") and det:
            return (f"{_nf.f2(det['cash'])} ريال" if det.get("cash")
                    else "—")
        return f"{_nf.f2(d['cash'])} ريال" if d.get("cash") else "—"

    def _render(self):
        q = self.search.text().strip().lower()
        self.shown = [d for d in self.docs
                      if (self.group == "all" or d["group"] == self.group)
                      and (not q or q in self._keys(d))]
        t = self.tbl
        t.setRowCount(0)
        t.setRowCount(len(self.shown))
        u = kv.unit()
        for r, d in enumerate(self.shown):
            g = d["group"]
            kind = text_item(SHORT.get(g, d.get("op") or "—"),
                             tip=d.get("op") or "")
            kind.setForeground(QtGui.QBrush(QtGui.QColor(COLOR.get(g,
                                                                   "#555"))))
            f = kind.font()
            f.setBold(True)
            kind.setFont(f)
            t.setItem(r, 0, kind)
            no = d["no"] + (f"  (عُكس بـ {d['reversed_by']})"
                            if d.get("reversed_by") else "")
            t.setItem(r, 1, text_item(no))
            t.setItem(r, 2, text_item(d.get("party") or d.get("desc") or
                                      "—"))
            w = float(d.get("weight") or 0)
            det = d.get("detail") or {}
            tip = ""
            if det.get("n_sets"):
                tip = f"{det['n_sets']} طقم"
            t.setItem(r, 3, num_item(f"{_nf.f2(kv.g(w))} {u}" if w else "—",
                                     tip=tip))
            t.setItem(r, 4, num_item(self._amount(d)))
            t.setItem(r, 5, text_item(d.get("time") or ""))
            t.setItem(r, 6, text_item(d.get("who") or ""))
            t.setCellWidget(r, 7, self._actions(r, d))
        fit_columns(t)
        self.hint.setText(
            (f"{len(self.shown)} من {len(self.docs)} عملية — " if
             (q or self.group != "all") else "")
            + "نقرٌ مزدوج على السطر يفتح المستند · «🖼 الصور» صور موديلاته "
              "بأرقام تشغيلها")

    def _actions(self, r, d):
        from services import print_manager as pm
        box = QtWidgets.QWidget()
        box.setProperty("rowActions", True)
        h = QtWidgets.QHBoxLayout(box)
        h.setContentsMargins(2, 0, 2, 0)
        h.setSpacing(4)
        b = QtWidgets.QToolButton()
        b.setObjectName("rowAct")
        b.setText("📄 عرض")
        b.setToolTip("فتح المستند كما يُطبع")
        b.clicked.connect(lambda _c=False, i=r: self.view(i))
        h.addWidget(b)
        if pm.models_target(d.get("src"), d.get("sid")):
            p = QtWidgets.QToolButton()
            p.setObjectName("rowAct")
            p.setText("🖼 الصور")
            p.setToolTip("صور موديلات المستند بأرقام تشغيلها")
            p.clicked.connect(lambda _c=False, i=r: self.photos(i))
            h.addWidget(p)
        h.addStretch(1)
        return box

    # ══════════ المعاينة ══════════
    def view(self, r):
        from services import print_manager as pm
        if not 0 <= r < len(self.shown):
            return
        d = self.shown[r]
        try:
            src, sid = d.get("src"), d.get("sid")
            if src and sid and src in pm.BUILDERS and src != "manual":
                pm.preview_document(self, src, sid)
            else:
                pm.preview_document(self, "manual", d["eid"])
        except Exception as e:                       # noqa: BLE001
            err(self, e)

    def photos(self, r):
        from services import print_manager as pm
        if not 0 <= r < len(self.shown):
            return
        d = self.shown[r]
        try:
            t = pm.models_target(d.get("src"), d.get("sid"))
            if t:
                pm.preview_document(self, t[0], t[1])
        except Exception as e:                       # noqa: BLE001
            err(self, e)
