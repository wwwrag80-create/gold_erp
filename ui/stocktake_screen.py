# -*- coding: utf-8 -*-
"""الجرد الفعلي — وضعان: كتلي بالوزن (خزينة التصنيع وصناديق الكسر) عبر
مقارنة الميزان بالدفتري، وتفصيلي بالباركود (الذهب المشغول) عبر تمرير
أرقام التشغيل ومطابقتها بالمتاح فعلياً في النظام."""
from PyQt5 import QtWidgets

from database.database import db
from services import karat_view as kv
from models import inventory, stocktake
from services.accounting_engine import account_balance
from ui.widgets.common import (search_combo, ask, big_label, date_edit, dstr, err, fill,
                               info, make_table, title_label, wspin)

BULK_CHOICES = [("خزينة التصنيع", "1100"), ("صندوق كسر عيار 18", "1310"),]


class StocktakeScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.scanned = []  # أرقام تشغيل مُدخَلة للجرد التفصيلي
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self._build_bulk_tab(), "جرد وزني — خزينة التصنيع وصناديق الكسر")
        tabs.addTab(self._build_itemized_tab(), "جرد بالباركود — الذهب المشغول")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("الجرد الفعلي"))
        lay.addWidget(tabs)

    # ---------- التبويب الأول: جرد وزني ----------
    def _build_bulk_tab(self):
        w = QtWidgets.QWidget()
        self.b_account = search_combo("اكتب اسم الصندوق أو الحساب…")
        for label, code in BULK_CHOICES:
            self.b_account.addItem(label, code)
        self.b_account.currentIndexChanged.connect(self.show_ledger)
        self.b_ledger = big_label()
        self.b_actual = wspin()
        self.b_actual.valueChanged.connect(self.show_diff)
        self.b_diff = big_label()
        self.b_date = date_edit()
        self.b_notes = QtWidgets.QLineEdit()

        form = QtWidgets.QFormLayout()
        form.addRow("الحساب:", self.b_account)
        form.addRow(self.b_ledger)
        form.addRow(f"الوزن الفعلي على الميزان ({kv.unit()}):",
                    self.b_actual)
        form.addRow(self.b_diff)
        form.addRow("تاريخ الجرد:", self.b_date)
        form.addRow("ملاحظات:", self.b_notes)

        btn = QtWidgets.QPushButton("ترحيل تسوية الجرد (عجز/زيادة آلياً حسب الفرق)")
        btn.clicked.connect(self.save_bulk)

        box = QtWidgets.QGroupBox(
            "الفرق = الفعلي − الدفتري. عجز (فعلي أقل) → مدين حساب الفاقد المخصص "
            "/ دائن الحساب. زيادة → العكس")
        bl = QtWidgets.QVBoxLayout(box)
        bl.addLayout(form)
        bl.addWidget(btn)

        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(box)
        lay.addStretch(1)
        note = QtWidgets.QLabel(
            "لعرض سجل عمليات الجرد السابقة أو حذفها منطقياً: افتح شاشة (سجل العمليات).")
        note.setObjectName("cardSub")
        lay.addWidget(note)
        return w

    def show_ledger(self):
        code = self.b_account.currentData()
        if not code:                       # القائمة لم تُملأ بعد
            self._ledger_value = 0.0
            self.b_ledger.setText("")
            return
        with db() as conn:
            from models.accounts import acc_id
            ledger = account_balance(conn, acc_id(conn, code))[0]
        self._ledger_value = ledger
        # الرصيد الدفتري والوزن المُدخل بوحدة واحدة — وإلا بدا فرقٌ
        # حيث لا فرق وقُيّد عجزٌ وهميّ.
        self._ledger_value = ledger
        self.b_ledger.setText(
            f"الرصيد الدفتري الحالي: {kv.g(ledger):,.2f} جم {kv.label()}")
        self.show_diff()

    def show_diff(self):
        actual = self.b_actual.value()
        ledger = kv.g(getattr(self, "_ledger_value", 0.0))
        diff = round(actual - ledger, 3)
        u = kv.unit()
        if diff == 0:
            self.b_diff.setText(
                f"الفرق: 0.000 {u} (مطابق تماماً — لا حاجة لقيد)")
        elif diff < 0:
            self.b_diff.setText(
                f"عجز: {abs(diff):,.2f} {u} (سيُقيَّد كخسارة)")
        else:
            self.b_diff.setText(
                f"زيادة: {diff:,.2f} {u} (سيُقيَّد كتخفيض فاقد سابق)")

    def save_bulk(self):
        try:
            with db() as conn:
                res = stocktake.create_bulk_stocktake(
                    conn, self.b_account.currentData(),
                    kv.store(self.b_actual.value()),
                    dstr(self.b_date), self.user["username"], self.b_notes.text())
            if res["entry_id"]:
                info(self, f"تم ترحيل جرد {res['stocktake_no']} — الفرق "
                           f"{kv.g(res['diff']):+.2f} {kv.unit()} "
                           f"(قيد رقم {res['entry_id']})")
            else:
                info(self, f"تم تسجيل جرد {res['stocktake_no']} — مطابق تماماً، "
                           "بلا قيد تسوية")
            self.b_actual.setValue(0)
            self.b_notes.clear()
            self.show_ledger()
        except Exception as e:
            err(self, e)

    # ---------- التبويب الثاني: جرد بالباركود ----------
    def _build_itemized_tab(self):
        w = QtWidgets.QWidget()
        self.scan_input = QtWidgets.QLineEdit()
        self.scan_input.setPlaceholderText(
            "امسح الباركود أو اكتب رقم التشغيل ثم Enter لإضافته لقائمة الجرد")
        self.scan_input.returnPressed.connect(self.add_scan)
        self.scan_table = make_table()
        self.scan_count = big_label("عدد الأطقم الممسوحة: 0")
        btn_remove = QtWidgets.QPushButton("حذف السطر المحدد من القائمة")
        btn_remove.setObjectName("ghost")
        btn_remove.clicked.connect(self.remove_scan)
        btn_clear = QtWidgets.QPushButton("تفريغ القائمة")
        btn_clear.setObjectName("ghost")
        btn_clear.clicked.connect(self.clear_scans)
        self.i_date = date_edit()
        self.i_notes = QtWidgets.QLineEdit()
        btn_reconcile = QtWidgets.QPushButton(
            "مطابقة (Reconcile) — وترحيل قيد عجز المفقود تلقائياً")
        btn_reconcile.clicked.connect(self.reconcile)

        top = QtWidgets.QVBoxLayout()
        top.addWidget(self.scan_input)
        top.addWidget(self.scan_table)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(btn_remove)
        row.addWidget(btn_clear)
        row.addStretch(1)
        row.addWidget(self.scan_count)
        top.addLayout(row)
        form = QtWidgets.QFormLayout()
        form.addRow("تاريخ الجرد:", self.i_date)
        form.addRow("ملاحظات:", self.i_notes)
        top.addLayout(form)
        top.addWidget(btn_reconcile)

        box = QtWidgets.QGroupBox(
            "مطابق: مسجَّل ومُجرَّد. عجز/مفقود: مسجَّل بالنظام ولم يُجرَد "
            "(يُقيَّد ويُخرَج من الرصيد المتاح). زيادة: مُجرَد ولا يطابق أي "
            "طقم متاح بالنظام (يُبلَّغ فقط دون قيد آلي — يحتاج مراجعة يدوية)")
        bl = QtWidgets.QVBoxLayout(box)
        bl.addLayout(top)

        self.result_table = make_table()
        result_box = QtWidgets.QGroupBox("نتيجة آخر مطابقة")
        rl = QtWidgets.QVBoxLayout(result_box)
        rl.addWidget(self.result_table)

        lay = QtWidgets.QVBoxLayout(w)
        lay.addWidget(box)
        lay.addWidget(result_box, 1)
        return w

    def add_scan(self):
        no = self.scan_input.text().strip()
        if not no:
            return
        if no in self.scanned:
            self.scan_input.clear()
            return
        self.scanned.append(no)
        self.scan_input.clear()
        self.render_scans()

    def remove_scan(self):
        r = self.scan_table.currentRow()
        if r >= 0:
            self.scanned.pop(r)
            self.render_scans()

    def clear_scans(self):
        self.scanned = []
        self.render_scans()

    def render_scans(self):
        fill(self.scan_table, ["رقم التشغيل الممسوح"], [(n,) for n in self.scanned])
        self.scan_count.setText(f"عدد الأطقم الممسوحة: {len(self.scanned)}")

    def reconcile(self):
        if not self.scanned:
            err(self, "امسح أو أدخل رقم تشغيل واحد على الأقل قبل المطابقة")
            return
        try:
            with db() as conn:
                system_rows = inventory.list_in_stock(conn)
            system_nos = {r["work_order_no"] for r in system_rows}
            scanned_set = set(self.scanned)
            missing = system_nos - scanned_set
            excess = scanned_set - system_nos
            missing_w = sum(r["registered_weight"] for r in system_rows
                            if r["work_order_no"] in missing)
            msg = (f"مطابق: {len(scanned_set & system_nos)} | "
                  f"عجز/مفقود: {len(missing)} "
                  f"(وزن {kv.g(missing_w):.2f} {kv.unit()}) | "
                  f"زيادة/غير مسجَّل: {len(excess)}\n\n"
                  "سيُرحَّل قيد عجز بوزن المفقود تلقائياً (إن وُجد) وتُخرَج "
                  "أرقامه من الرصيد المتاح. متابعة؟")
            if not ask(self, msg):
                return
            with db() as conn:
                res = stocktake.create_itemized_reconcile(
                    conn, self.scanned, dstr(self.i_date), self.user["username"],
                    self.i_notes.text())
            rows = ([(n, "مطابق", "") for n in res["matched"]]
                   + [(n, "عجز/مفقود", "أُخرِج من الرصيد المتاح") for n in res["missing"]]
                   + [(n, "زيادة/غير مسجَّل", "يحتاج مراجعة يدوية") for n in res["excess"]])
            fill(self.result_table, ["رقم التشغيل", "الحالة", "ملاحظة"], rows)
            if res["entry_id"]:
                info(self, f"تم ترحيل الجرد {res['stocktake_no']} — عجز "
                           f"{kv.g(res['missing_weight']):.2f} {kv.unit()} "
                           f"(قيد رقم {res['entry_id']})")
            else:
                info(self, f"تم تسجيل الجرد {res['stocktake_no']} — لا عجز، بلا قيد")
            self.clear_scans()
        except Exception as e:
            err(self, e)

    def refresh(self):
        self.show_ledger()
        self.render_scans()
