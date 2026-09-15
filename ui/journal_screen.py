# -*- coding: utf-8 -*-
"""القيود اليومية المزدوجة رباعية الأعمدة + قائمة القيود والحذف المنطقي."""
from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from models import editing, journal
from models.accounts import list_postable
from services.accounting_engine import validate_lines
from services.audit import soft_delete_entry
from ui.widgets.common import (confirm_post, posted, ask, big_label, cell, date_edit, dstr,
                               enter_chain, err, fill, info, make_table,
                               mspin, search_combo, title_label, wspin)

COLS = ["الحساب", "مدين ذهب", "دائن ذهب", "مدين نقد", "دائن نقد"]


class EntryLinesDialog(QtWidgets.QDialog):
    def __init__(self, parent, entry_id):
        super().__init__(parent)
        self.setWindowTitle(f"أسطر القيد رقم {entry_id}")
        self.setMinimumSize(760, 340)
        table = make_table()
        if not confirm_post(self, "قيد يومية"):
            return

        with db() as conn:
            rows = [(f"{l['acode']} — {l['aname']}",
                     l["gold_debit"], l["gold_credit"], l["cash_debit"],
                     l["cash_credit"], l["line_desc"])
                    for l in journal.entry_lines(conn, entry_id)]
        fill(table, COLS + ["البيان"], rows)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(table)


from ui.widgets.edit_mode import EditModeMixin


class JournalScreen(EditModeMixin, QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.accounts = []

        self.date = date_edit()
        self.desc = QtWidgets.QLineEdit()
        self.lines = QtWidgets.QTableWidget()
        self.lines.setColumnCount(len(COLS))
        self.lines.setHorizontalHeaderLabels(COLS)
        self.lines.verticalHeader().setVisible(False)
        self.lines.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.Stretch)
        self.totals = big_label()

        btn_add = QtWidgets.QPushButton("+ إضافة سطر")
        btn_add.setObjectName("ghost")
        btn_add.clicked.connect(self.add_row)
        btn_rem = QtWidgets.QPushButton("حذف السطر المحدد")
        btn_rem.setObjectName("ghost")
        btn_rem.clicked.connect(self.remove_row)
        btn_post = QtWidgets.QPushButton("ترحيل القيد")
        btn_post.clicked.connect(self.post)
        self.init_edit_mode(btn_post, "القيد")

        head = QtWidgets.QFormLayout()
        head.addRow("التاريخ:", self.date)
        head.addRow("بيان القيد:", self.desc)

        box = QtWidgets.QGroupBox(
            "قيد يومية مزدوج: يجب توازن ميزان الذهب وميزان النقد كلٌّ على حدة")
        bl = QtWidgets.QVBoxLayout(box)
        bl.addLayout(head)
        bl.addWidget(self.lines)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(btn_add)
        row.addWidget(btn_rem)
        row.addStretch(1)
        row.addWidget(self.totals)
        bl.addLayout(row)
        bl.addWidget(self.edit_banner)
        prow = QtWidgets.QHBoxLayout()
        prow.addWidget(btn_post, 1)
        prow.addWidget(self.btn_cancel_edit)
        bl.addLayout(prow)

        self.entries = make_table()
        btn_view = QtWidgets.QPushButton("عرض أسطر القيد المحدد")
        btn_view.setObjectName("ghost")
        btn_view.clicked.connect(self.view_entry)
        btn_del = QtWidgets.QPushButton("حذف منطقي للقيد المحدد")
        btn_del.setObjectName("danger")
        btn_del.clicked.connect(self.delete_entry)
        # سجل القيود مخفيّ افتراضياً: بناء مئات الصفوف عند كل فتح
        # يُبطئ الشاشة، وهو متاح كاملاً في دفتر الأستاذ العام.
        ebox = QtWidgets.QGroupBox("سجل القيود (يشمل المحذوف منطقياً)")
        ebox.setVisible(False)
        self._log_box = ebox
        self.btn_log = QtWidgets.QPushButton("إظهار سجل القيود")
        self.btn_log.setObjectName("ghost")
        self.btn_log.clicked.connect(self.toggle_log)
        el = QtWidgets.QVBoxLayout(ebox)
        el.addWidget(self.entries)
        hrow = QtWidgets.QHBoxLayout()
        hrow.addWidget(btn_view)
        hrow.addWidget(btn_del)
        hrow.addStretch(1)
        el.addLayout(hrow)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("القيود اليومية والافتتاحية وقيود التسوية"))
        lay.addWidget(box, 1)
        lay.addWidget(self.btn_log)
        lay.addWidget(ebox, 1)

    # ---- بناء أسطر القيد ----
    def _account_model(self):
        """نموذج حسابات **واحد** تتشاركه كل أسطر القيد.

        **الخلل السابق**: كل سطر كان يُنشئ قائمته ويملؤها بكل
        الحسابات — قيد بعشرة أسطر وشجرة بمئة حساب يعني ألف عنصر
        واجهة، فيتجمّد النظام عند فتح قيد للتعديل.

        النموذج المشترك يُبنى مرة واحدة، وكل قائمة تعرضه بلا نسخ.
        """
        m = getattr(self, "_acc_model", None)
        if m is not None and getattr(self, "_acc_count", -1) == len(
                self.accounts):
            return m
        m = QtGui.QStandardItemModel()
        for a in self.accounts:
            it = QtGui.QStandardItem(f"{a['code']} — {a['name']}")
            it.setData(a["id"], QtCore.Qt.UserRole)
            m.appendRow(it)
        self._acc_model = m
        self._acc_count = len(self.accounts)
        return m

    def _sync_row_models(self):
        """يحدّث نموذج كل قائمة حسابات قائمة بعد تغيّر الشجرة."""
        try:
            m = self._account_model()
            for r in range(self.lines.rowCount()):
                w = self.lines.cellWidget(r, 0)
                if w is not None and hasattr(w, "setModel"):
                    cur = w.currentData()
                    w.setModel(m)
                    if cur is not None:
                        i = w.findData(cur)
                        if i >= 0:
                            w.setCurrentIndex(i)
        except Exception:
            pass

    def _load_log(self):
        """يملأ سجل القيود — عند إظهاره فقط."""
        try:
            with db() as conn:
                rows = [(e["id"], e["entry_date"], e["description"],
                         e["source_table"] or "—", e["gd"], e["cd"],
                         e["created_by"] or "—",
                         "محذوف" if e["is_deleted"] else "ساري")
                        for e in journal.list_entries(conn)]
            fill(self.entries,
                 ["رقم", "التاريخ", "البيان", "المصدر", "مدين ذهب",
                  "مدين نقد", "المستخدم", "الحالة"], rows)
        except Exception:
            pass

    def toggle_log(self):
        """يُظهر سجل القيود أو يُخفيه."""
        try:
            vis = not self._log_box.isVisible()
            self._log_box.setVisible(vis)
            if vis:
                self._load_log()
            self.btn_log.setText("إخفاء سجل القيود" if vis
                                 else "إظهار سجل القيود")
        except Exception:
            pass

    def add_row(self):
        r = self.lines.rowCount()
        self.lines.insertRow(r)
        acc = search_combo("اكتب رقم الحساب أو اسمه…")
        acc.setModel(self._account_model())
        acc.clear_selection()
        self.lines.setCellWidget(r, 0, acc)
        for col in (1, 2):
            s = wspin()
            s.valueChanged.connect(self.recalc)
            self.lines.setCellWidget(r, col, s)
        for col in (3, 4):
            s = mspin()
            s.valueChanged.connect(self.recalc)
            self.lines.setCellWidget(r, col, s)
        self.lines.setRowHeight(r, 42)
        # Enter: ينتقل بين خانات السطر، وفي آخر خانة يضيف سطراً جديداً
        # ويضع المؤشر في أول خانة فيه
        widgets = [self.lines.cellWidget(r, c) for c in range(len(COLS))]
        enter_chain(self, widgets, self._enter_new_row)
        return r

    def _enter_new_row(self):
        self.add_row()
        w = self.lines.cellWidget(self.lines.rowCount() - 1, 0)
        if w is not None:
            w.setFocus()

    def remove_row(self):
        r = self.lines.currentRow()
        if r >= 0:
            self.lines.removeRow(r)
            self.recalc()

    def collect(self):
        out = []
        for r in range(self.lines.rowCount()):
            vals = [self.lines.cellWidget(r, c).value() for c in (1, 2, 3, 4)]
            if not any(vals):
                continue
            out.append({
                "account_id": self.lines.cellWidget(r, 0).currentData(),
                "gold_debit": vals[0], "gold_credit": vals[1],
                "cash_debit": vals[2], "cash_credit": vals[3]})
        return out

    def recalc(self):
        lines = self.collect()
        gd = sum(l["gold_debit"] for l in lines)
        gc = sum(l["gold_credit"] for l in lines)
        cd = sum(l["cash_debit"] for l in lines)
        cc = sum(l["cash_credit"] for l in lines)
        ok = abs(gd - gc) < 0.011 and abs(cd - cc) < 0.011 and lines
        state = "متوازن ✔" if ok else "غير متوازن ✘"
        self.totals.setText(
            f"ذهب: {gd:.2f} / {gc:.2f} | نقد: {cd:,.2f} / {cc:,.2f} — {state}")
        self.totals.setStyleSheet(
            "color:#1E6B33;font-weight:bold" if ok
            else "color:#B02A2A;font-weight:bold")

    def post(self):
        try:
            # التحقق من حياة القيد **قبل** فتح المعاملة — لا داخلها
            self.verify_edit_target()
            lines = self.collect()
            validate_lines(lines)
            with db() as conn:
                if self.is_editing:
                    editing.void_for_edit(conn, self.editing_entry_id,
                                          self.user["username"])
                    eid = journal.manual_entry(conn, dstr(self.date),
                                               self.desc.text(), lines,
                                               self.user["username"])
                    editing.log_edit(conn, self.user["username"], "manual",
                                    self.editing_entry_id, eid, eid)
                else:
                    eid = journal.manual_entry(conn, dstr(self.date),
                                               self.desc.text(), lines,
                                               self.user["username"])
            was_editing = bool(self.is_editing)
            posted(self, f"تم ترحيل القيد رقم {eid}"
                       + (" بديلاً عن القيد السابق بعد عكسه"
                          if was_editing else ""), "manual", eid,
                   editing=was_editing)
            self.end_edit()
            self.lines.setRowCount(0)
            self.desc.clear()
            self.recalc()
            self.refresh()
        except Exception as e:
            err(self, e)

    # ---- سجل القيود ----
    def view_entry(self):
        r = self.entries.currentRow()
        if r >= 0 and cell(self.entries, r, 0):
            EntryLinesDialog(self, int(cell(self.entries, r, 0))).exec_()

    def delete_entry(self):
        r = self.entries.currentRow()
        if r < 0:
            return
        eid = cell(self.entries, r, 0)
        if not ask(self, f"حذف منطقي للقيد رقم {eid} وعكس آثار مستنده المصدر؟"):
            return
        try:
            info(self, soft_delete_entry(int(eid), self.user["username"]))
            self.refresh()
        except Exception as e:
            err(self, e)

    def load_document(self, source_id):
        """يفتح قيداً يدوياً قائماً للتعديل بكل أسطره."""
        try:
            with db() as conn:
                self.accounts = list_postable(conn)
                doc = editing.load_document(conn, "manual", source_id)
            if not doc:
                raise ValueError("القيد غير موجود")
            e, lines = doc["entry"], doc["lines"]
            if e["is_deleted"]:
                raise ValueError("القيد محذوف — لا يمكن تعديله")
            self.date.setDate(QtCore.QDate.fromString(e["entry_date"],
                                                      "yyyy-MM-dd"))
            self.desc.setText(e["description"] or "")
            self.lines.setRowCount(0)
            for ln in lines:
                r = self.add_row()
                acc = self.lines.cellWidget(r, 0)
                i = acc.findData(ln["account_id"])
                if i >= 0:
                    acc.setCurrentIndex(i)
                for col, key in ((1, "gold_debit"), (2, "gold_credit"),
                                (3, "cash_debit"), (4, "cash_credit")):
                    self.lines.cellWidget(r, col).setValue(ln[key] or 0)
            self.begin_edit(e["id"], e["id"])
            self.recalc()
        except Exception as ex:
            err(self, ex)

    def on_edit_cancelled(self):
        self.lines.setRowCount(0)
        self.desc.clear()
        self.add_row()
        self.add_row()
        self.recalc()

    def refresh(self):
        # لا نُعيد بناء النموذج أثناء وضع التعديل: القيد محمَّل
        # وأسطره مربوطة، وإعادة البناء تمسح ما حُمِّل.
        if getattr(self, "editing_entry_id", None):
            return
        with db() as conn:
            self.accounts = list_postable(conn)
        # النموذج يُعاد بناؤه مرة واحدة عند تغيّر الشجرة
        self._acc_model = None
        self._sync_row_models()
        # السجل لا يُبنى إلا إن كان ظاهراً — يوفّر بناء مئات الصفوف
        if getattr(self, "_log_box", None) is not None \
                and self._log_box.isVisible():
            self._load_log()
        if self.lines.rowCount() == 0:
            self.add_row()
            self.add_row()
        self.recalc()
