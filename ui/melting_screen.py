# -*- coding: utf-8 -*-
"""شاشة الصب والتصفية — دورة مرحلية من ثلاث خطوات محورها حساب
«الصب والتصفية (1350)»، وكل الأوزان تُقيَّد بمعادل عيار 18:

  (أ) سند صرف للصب   → مدين الصب والتصفية / دائن صناديق العيارات
  (ب) سند قبض مصفى   → مدين صناديق العيارات / دائن الصب والتصفية
  (جـ) إقفال الفاقد   → مدين الفاقد الفني للصب / دائن الصب والتصفية

الفاقد الفني للصب مستقل تماماً عن فاقد التصنيع والخياس، ولا يظهر ضمن
لوحة فاقد الذهب في تقرير خزينة التصنيع."""
from PyQt5 import QtCore, QtWidgets

import config
from database.database import db
from services import karat_view as kv
from models import editing, melting
from models.inventory import scrap_actuals
from services import gold_math
from ui.widgets.common import (confirm_post, posted, ask, big_label, date_edit, dstr, enter_chain,
                               err, fill, info, make_table, title_label,
                               wspin)
from ui.widgets.edit_mode import EditModeMixin

# الوزن الفعلي وزنٌ حقيقي بعياره المُدخل — لا يُحوَّل أبداً.
# المعادل وحده هو الذي يُقرأ بوحدة المصنع.
COLS = ["العيار", "الوزن الفعلي (جم)", "معادل عيار 18 (جم)"]
LOG_COLS = ["المستند", "النوع", "التاريخ", "معادل 18 (جم)", "البيان"]


def _cols():
    return ["العيار", "الوزن الفعلي (جم)", f"المعادل ({kv.unit()})"]


def _log_cols():
    return ["المستند", "النوع", "التاريخ", f"المعادل ({kv.unit()})",
            "البيان"]


class MeltingScreen(EditModeMixin, QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.lines = []
        self.mode = "disbursement"

        # ── اختيار مرحلة الدورة ──
        self.kind = QtWidgets.QComboBox()
        self.kind.addItem("(أ) سند صرف للصب — إخراج كسر/خام للصهر",
                          "disbursement")
        self.kind.addItem("(ب) سند قبض مصفى — إدخال الناتج بعد التصفية",
                          "receipt")
        self.kind.currentIndexChanged.connect(self.mode_changed)
        self.date = date_edit()
        self.notes = QtWidgets.QLineEdit()
        self.notes.setPlaceholderText("البيان / ملاحظات (اختياري)")

        # ── سطر إدخال عيار ووزن ──
        self.karat = QtWidgets.QComboBox()
        for k in melting.KARATS:
            self.karat.addItem(f"عيار {k}", k)
        self.weight = wspin()
        self.weight.valueChanged.connect(self.recalc_line)
        self.equiv_label = QtWidgets.QLabel("0.000")
        self.equiv_label.setObjectName("big")
        self.karat.currentIndexChanged.connect(self.recalc_line)
        btn_add = QtWidgets.QPushButton("+ إضافة سطر")
        btn_add.clicked.connect(self.add_line)

        def _lbl(t):
            l = QtWidgets.QLabel(t)
            l.setObjectName("cardSub")
            return l

        def col(label, w, width=None):
            c = QtWidgets.QVBoxLayout()
            c.setSpacing(2)
            c.addWidget(_lbl(label))
            if width:
                w.setMaximumWidth(width)
            c.addWidget(w)
            return c

        entry_row = QtWidgets.QHBoxLayout()
        entry_row.addLayout(col("العيار", self.karat, 130))
        entry_row.addLayout(col("الوزن الفعلي (جم)", self.weight, 130))
        entry_row.addLayout(col(f"المعادل ({kv.unit()})",
                                self.equiv_label, 120))
        entry_row.addLayout(col("", btn_add, 130))
        entry_row.addStretch(1)

        self.table = make_table()
        btn_del = QtWidgets.QPushButton("حذف السطر المحدد")
        btn_del.setObjectName("ghost")
        btn_del.clicked.connect(self.remove_line)
        self.totals = big_label()
        self.btn_save = QtWidgets.QPushButton("ترحيل السند")
        self.btn_save.clicked.connect(self.save)
        self.init_edit_mode(self.btn_save, "سند الصهر")

        box = QtWidgets.QGroupBox("سند الصب والتصفية")
        bl = QtWidgets.QVBoxLayout(box)
        head = QtWidgets.QHBoxLayout()
        head.addWidget(QtWidgets.QLabel("مرحلة الدورة:"))
        head.addWidget(self.kind, 2)
        head.addWidget(QtWidgets.QLabel("التاريخ:"))
        head.addWidget(self.date)
        bl.addLayout(head)
        bl.addWidget(self.notes)
        bl.addLayout(entry_row)
        bl.addWidget(self.table)
        r2 = QtWidgets.QHBoxLayout()
        r2.addWidget(btn_del)
        r2.addStretch(1)
        r2.addWidget(self.totals)
        bl.addLayout(r2)
        bl.addWidget(self.edit_banner)
        srow = QtWidgets.QHBoxLayout()
        srow.addWidget(self.btn_save, 1)
        srow.addWidget(self.btn_cancel_edit)
        bl.addLayout(srow)

        # ── حالة الدورة والإقفال ──
        self.cycle_label = big_label()
        self.cycle_note = QtWidgets.QLabel()
        self.cycle_note.setObjectName("cardSub")
        self.cycle_note.setWordWrap(True)
        self.close_date = date_edit()
        btn_close = QtWidgets.QPushButton(
            "ترحيل قيد إقفال الفاقد الفني للصب (تصفير حساب الصهر)")
        btn_close.clicked.connect(self.close_cycle)
        cbox = QtWidgets.QGroupBox("(جـ) حالة الدورة وإقفال الفاقد الفني")
        cl = QtWidgets.QVBoxLayout(cbox)
        cl.addWidget(self.cycle_label)
        cl.addWidget(self.cycle_note)
        crow = QtWidgets.QHBoxLayout()
        crow.addWidget(QtWidgets.QLabel("تاريخ الإقفال:"))
        crow.addWidget(self.close_date)
        crow.addWidget(btn_close, 1)
        cl.addLayout(crow)

        self.boxes_label = big_label()
        self.log = make_table()

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label(
            "الصب والتصفية — دورة مرحلية بمعادل عيار 18"))
        lay.addWidget(self.boxes_label)
        lay.addWidget(box)
        lay.addWidget(cbox)
        lay.addWidget(QtWidgets.QLabel("آخر مستندات الدورة:"))
        lay.addWidget(self.log, 1)
        note = QtWidgets.QLabel(
            "الفاقد الفني للصب مستقل تماماً عن فاقد التصنيع والخياس — "
            "لا يدخل ضمن لوحة فاقد الذهب في تقرير خزينة التصنيع.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)
        enter_chain(self, [self.weight], self.add_line)

    # ── الإدخال ──
    def mode_changed(self):
        self.mode = self.kind.currentData() or "disbursement"
        self.btn_save.setText(
            "ترحيل سند الصرف للصب" if self.mode == "disbursement"
            else "ترحيل سند القبض المصفى")
        self.render()

    def recalc_line(self):
        k = self.karat.currentData() or 18
        self.equiv_label.setText(
            f"{kv.g(gold_math.to_base_karat(self.weight.value(), k)):.2f}")

    def add_line(self):
        try:
            k = self.karat.currentData() or 18
            w = self.weight.value()
            if w <= 0:
                raise ValueError("أدخل وزناً أكبر من صفر")
            for ln in self.lines:
                if ln["karat"] == k:
                    ln["weight"] = round(ln["weight"] + w, 3)
                    break
            else:
                self.lines.append({"karat": k, "weight": w})
            self.weight.setValue(0)
            self.weight.setFocus()
            self.render()
        except Exception as e:
            err(self, e)

    def remove_line(self):
        r = self.table.currentRow()
        if 0 <= r < len(self.lines):
            self.lines.pop(r)
            self.render()

    def render(self):
        rows, total = [], 0.0
        for ln in self.lines:
            eq = gold_math.to_base_karat(ln["weight"], ln["karat"])
            total = round(total + eq, 3)
            rows.append((f"عيار {ln['karat']}", ln["weight"], kv.g(eq)))
        fill(self.table, _cols(), rows)
        side = "مدين حساب الصب والتصفية" if self.mode == "disbursement" \
            else "دائن حساب الصب والتصفية"
        self.totals.setText(
            f"إجمالي المعادل بـ{kv.label()}: {kv.g(total):.2f} جم"
            f"  →  {side}")
        self.recalc_line()

    # ── الترحيل ──
    def save(self):
        try:
            # التحقق من حياة القيد **قبل** فتح المعاملة — لا داخلها
            self.verify_edit_target()
            if not self.lines:
                raise ValueError("أضف سطر عيار واحداً على الأقل")
            fn = (melting.create_disbursement if self.mode == "disbursement"
                  else melting.create_receipt)
            args = (self.lines, dstr(self.date), self.user["username"],
                    self.notes.text().strip())
            if not confirm_post(self, "عملية صب وتصفية"):
                return

            with db() as conn:
                if self.is_editing:
                    res = editing.repost(conn, self.editing_entry_id,
                                         self.user["username"], fn, *args)
                else:
                    res = fn(conn, *args)
            posted(self, f"تم ترحيل {res['op_no']} بمعادل "
                       f"{kv.active()} = {kv.g(res['equiv18']):.2f} جم\n"
                       f"رصيد حساب الصب والتصفية الآن: "
                       f"{kv.g(res['refining_balance']):.2f} جم",
                   "melting_ops", res["id"])
            self.end_edit()
            self.lines = []
            self.notes.clear()
            self.render()
            self.refresh()
        except Exception as e:
            err(self, e)

    def close_cycle(self):
        try:
            with db() as conn:
                s = melting.cycle_summary(conn)
            if not ask(self, f"إقفال حساب الصب والتصفية وترحيل الفرق "
                             f"({kv.g(s['outstanding']):.2f} جم معادل "
                             f"{kv.active()}) إلى "
                             "حساب الفاقد الفني للصب؟"):
                return
            with db() as conn:
                res = melting.close_cycle(conn, dstr(self.close_date),
                                          self.user["username"])
            msg = (f"تم ترحيل قيد الإقفال {res['op_no']}\n"
                   f"الفاقد الفني للصب: {kv.g(res['loss18']):.2f} جم "
                   f"معادل {kv.active()} "
                   f"({res['loss_ratio']*100:.2f}%)")
            if res["exceeded"]:
                msg += (f"\n\n⚠ تنبيه: النسبة تجاوزت الحد المسموح "
                        f"({config.MELTING_LOSS_LIMIT*100:.1f}%)")
            info(self, msg)
            self.refresh()
        except Exception as e:
            err(self, e)

    # ── التعديل ──
    def load_document(self, source_id):
        try:
            with db() as conn:
                op = conn.execute("SELECT * FROM melting_ops WHERE id=?",
                                  (source_id,)).fetchone()
                if not op:
                    raise ValueError("المستند غير موجود")
                if op["kind"] == "close":
                    raise ValueError(
                        "قيد إقفال الفاقد يُحتسب آلياً من رصيد حساب الصهر — "
                        "احذفه ثم أعد ترحيل الإقفال بعد تصحيح السندات")
                if op["kind"] == "legacy":
                    raise ValueError(
                        "عملية صهر بالنسخة السابقة — احذفها وأعد إدخالها "
                        "بسندي الصرف والقبض")
                lines = melting.op_lines(conn, source_id)
                eid = editing.entry_of(conn, "melting_ops", source_id)
            i = self.kind.findData(op["kind"])
            if i >= 0:
                self.kind.setCurrentIndex(i)
            self.date.setDate(QtCore.QDate.fromString(op["op_date"],
                                                      "yyyy-MM-dd"))
            self.notes.setText(op["notes"] or "")
            self.lines = [{"karat": l["karat"], "weight": l["weight"]}
                          for l in lines]
            self.render()
            self.begin_edit(eid, source_id)
        except Exception as e:
            err(self, e)

    def on_edit_cancelled(self):
        self.lines = []
        self.notes.clear()
        self.render()

    def refresh(self):
        with db() as conn:
            actuals = scrap_actuals(conn)
            s = melting.cycle_summary(conn)
            rows = [(o["op_no"], melting.KIND_LABELS.get(o["kind"], o["kind"]),
                     o["op_date"], kv.g(o["equiv18"]), o["notes"] or "—")
                    for o in melting.recent_melting(conn)]
        self.boxes_label.setText(
            "أرصدة صناديق الكسر الفعلية — "
            + " | ".join(f"عيار {k}: {actuals.get(k, 0.0):.2f} جم"
                         for k in melting.KARATS))
        self.cycle_label.setText(
            f"المصروف للصب: {kv.g(s['disbursed']):.2f} جم معادل "
            f"{kv.active()}   |   "
            f"المقبوض مصفى: {kv.g(s['received']):.2f} جم   |   "
            f"الرصيد القائم (الفاقد المرشح): "
            f"{kv.g(s['outstanding']):.2f} جم")
        if abs(s["outstanding"]) < 0.001:
            self.cycle_note.setText(
                "حساب الصب والتصفية متزن — لا يوجد فاقد بانتظار الإقفال.")
        else:
            self.cycle_note.setText(
                f"نسبة الفاقد الحالية {s['loss_ratio']*100:.2f}% "
                f"(الحد المسموح {config.MELTING_LOSS_LIMIT*100:.1f}%)"
                + ("  ⚠ تجاوز الحد" if s["exceeded"] else ""))
        fill(self.log, _log_cols(), rows)
        self.render()
