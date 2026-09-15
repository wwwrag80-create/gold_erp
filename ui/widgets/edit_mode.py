# -*- coding: utf-8 -*-
"""مزيج التعديل الشامل: يمنح أي شاشة عمليات وضعَ تعديل موحّداً
(شريط تنبيه + زر إلغاء + تبديل نص زر الحفظ) بنفس السلوك في كل النظام."""
from PyQt5 import QtWidgets


class EditModeMixin:
    def init_edit_mode(self, save_button, label="العملية"):
        self.editing_entry_id = None      # رقم القيد الجاري تعديله
        self.editing_source_id = None     # رقم المستند الجاري تعديله
        self._edit_label = label
        self._save_btn = save_button
        self._save_text = save_button.text()
        self.edit_banner = QtWidgets.QLabel(
            f"✎ وضع تعديل {label}: عند الحفظ يُعكس أثر القيد القديم بالكامل "
            "ويُرحَّل قيد جديد داخل معاملة واحدة، ويُسجَّل التعديل في سجل "
            "العمليات.")
        self.edit_banner.setObjectName("warn")
        self.edit_banner.setWordWrap(True)
        self.edit_banner.setVisible(False)
        self.btn_cancel_edit = QtWidgets.QPushButton("إلغاء التعديل")
        self.btn_cancel_edit.setObjectName("ghost")
        self.btn_cancel_edit.clicked.connect(self.cancel_edit)
        self.btn_cancel_edit.setVisible(False)

    def edit_widgets(self):
        """يُدرجان في تخطيط الشاشة: الشريط وزر الإلغاء."""
        return self.edit_banner, self.btn_cancel_edit

    def begin_edit(self, entry_id, source_id):
        self.editing_entry_id = entry_id
        self.editing_source_id = source_id
        self._sync_edit_ui()

    def cancel_edit(self):
        self.editing_entry_id = None
        self.editing_source_id = None
        self._sync_edit_ui()
        if hasattr(self, "on_edit_cancelled"):
            self.on_edit_cancelled()

    def end_edit(self):
        self.cancel_edit()

    @property
    def is_editing(self):
        """هل الشاشة في وضع تعديل قيد **صالح**؟

        لا يكفي وجود رقم قيد: قد يكون المستخدم حذف القيد بعد فتحه
        للتعديل، فيبقى الوضع مفعّلاً ويُرفض أي حفظ جديد صامتاً —
        وهو ما يجعل عملية القبض أو الصرف تبدو كأنها لم تُسجَّل.

        لذلك نتحقق من بقاء القيد حياً، وإن حُذف نخرج من وضع التعديل
        تلقائياً فتُحفظ العملية الجديدة كعملية مستقلة.
        """
        eid = getattr(self, "editing_entry_id", None)
        if eid is None:
            return False
        # ══ بلا أي اتصال بقاعدة البيانات ══
        # فتح اتصال هنا كارثي: هذه الخاصية تُستدعى **داخل** معاملة
        # مفتوحة في كل دالة حفظ، فينتظر الاتصال الثاني قفل الأول
        # ثلاثين ثانية — فيتجمّد النظام ثم يكمل بنجاح.
        # التحقق من حياة القيد يجري في `verify_edit_target()` التي
        # تُستدعى قبل فتح المعاملة لا داخلها.
        if getattr(self, "_edit_dead", False):
            self.editing_entry_id = None
            self.editing_source_id = None
            self._edit_dead = False
            try:
                self._sync_edit_ui()
            except Exception:
                pass
            return False
        return True

    def verify_edit_target(self):
        """يتحقق من بقاء القيد المفتوح للتعديل — **قبل** فتح المعاملة.

        تُستدعى في أول دالة الحفظ، فيجري الفحص باتصال مستقل بلا
        تنازع. إن كان القيد محذوفاً تُرفع الراية فتخرج الشاشة من وضع
        التعديل وتُحفظ العملية كعملية جديدة مستقلة.
        """
        eid = getattr(self, "editing_entry_id", None)
        if eid is None:
            return False
        if not self._entry_alive(eid):
            self._edit_dead = True
            self.editing_entry_id = None
            self.editing_source_id = None
            try:
                self._sync_edit_ui()
            except Exception:
                pass
            return False
        return True

    @staticmethod
    def _entry_alive(entry_id):
        """هل القيد ما زال قائماً وغير محذوف؟"""
        try:
            from database.database import db
            with db() as conn:
                r = conn.execute(
                    "SELECT is_deleted FROM journal_entries WHERE id=?",
                    (entry_id,)).fetchone()
            return bool(r) and not r["is_deleted"]
        except Exception:
            return True          # تعذّر التحقق: لا نُسقط وضع التعديل

    def _sync_edit_ui(self):
        on = self.is_editing
        self.edit_banner.setVisible(on)
        self.btn_cancel_edit.setVisible(on)
        self._save_btn.setText(
            f"حفظ تعديل {self._edit_label} (عكس القيد القديم وترحيل جديد)"
            if on else self._save_text)
