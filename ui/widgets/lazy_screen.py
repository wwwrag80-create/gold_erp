# -*- coding: utf-8 -*-
"""تحميل الشاشات عند الطلب (Lazy Loading).

**المشكلة التي يحلّها**: كانت كل شاشات النظام (٢٧ شاشة) تُبنى دفعةً
واحدة عند تسجيل الدخول — وكل شاشة تُنشئ جداولها وقوائمها وتقرأ من
قاعدة البيانات. فيتجمّد النظام ثوانيَ طويلة عند الإقلاع، وويندوز
يعلن «لا يستجيب» لأن خيط الواجهة مشغول.

**الحل**: الشاشة تُبنى **أول مرة تُفتح فيها فقط**، ثم تبقى محفوظة.
فالإقلاع فوري، ولا تُدفع تكلفة شاشة لا يستعملها المستخدم أصلاً.

هذا هو النمط المعتمد في أنظمة ERP الكبيرة.
"""
from PyQt5 import QtCore, QtWidgets


class LazyScreen(QtWidgets.QWidget):
    """غلاف يؤجّل بناء الشاشة الحقيقية حتى أول فتح.

    يعرض مؤشر تحميل بسيط، ثم يستبدل نفسه بالشاشة الفعلية عند أول
    ظهور — فلا يشعر المستخدم إلا بجزء من الثانية.
    """

    def __init__(self, factory, title=""):
        super().__init__()
        self._factory = factory
        self._real = None
        self._title = title
        self._lay = QtWidgets.QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._placeholder = QtWidgets.QLabel(f"جارٍ فتح {title}…")
        self._placeholder.setAlignment(QtCore.Qt.AlignCenter)
        self._lay.addWidget(self._placeholder)

    # ── البناء عند الطلب ──
    def ensure(self):
        """يبني الشاشة الحقيقية إن لم تُبنَ بعد."""
        if self._real is not None:
            return self._real
        try:
            self._real = self._factory()
        except Exception as e:
            self._real = QtWidgets.QLabel(
                f"تعذّر فتح {self._title}:\n{type(e).__name__}: {e}")
            self._real.setAlignment(QtCore.Qt.AlignCenter)
            self._real.setWordWrap(True)
        self._lay.removeWidget(self._placeholder)
        self._placeholder.setParent(None)
        self._lay.addWidget(self._real)
        return self._real

    @property
    def built(self):
        return self._real is not None

    @property
    def real(self):
        """الشاشة الحقيقية — تُبنى إن لزم."""
        return self.ensure()

    def showEvent(self, e):
        """أول ظهور يبني الشاشة."""
        try:
            self.ensure()
        except Exception:
            pass
        super().showEvent(e)

    def release(self):
        """يُغلق الشاشة ويُحرّر مواردها عند مغادرتها.

        **لماذا هذا ضروري**: إبقاء كل الشاشات حيّة معاً يجعل أحداث
        تغيير الحجم والمؤقّتات تتفاعل بينها، فيتجمّد النظام عند
        العودة لشاشة سابقة. إغلاق الشاشة عند الخروج يضمن أن **شاشة
        واحدة فقط حيّة** في كل لحظة — وهو ما يفعله أي نظام ERP.

        الشاشة تُبنى من جديد عند فتحها، فتظهر ببيانات محدّثة دائماً.
        """
        real = self.__dict__.get("_real")
        if real is None:
            return False
        try:
            # أوقف أي مؤقّتات أو خيوط تخص الشاشة
            for child in real.findChildren(QtCore.QTimer):
                try:
                    child.stop()
                except Exception:
                    pass
            fn = getattr(real, "on_close", None)
            if callable(fn):
                fn()
        except Exception:
            pass
        try:
            self._lay.removeWidget(real)
            real.setParent(None)
            real.deleteLater()
        except Exception:
            pass
        self._real = None
        # عنصر نائب حتى الفتح التالي
        try:
            self._placeholder = QtWidgets.QLabel(
                f"جارٍ فتح {self._title}…")
            self._placeholder.setAlignment(QtCore.Qt.AlignCenter)
            self._lay.addWidget(self._placeholder)
        except Exception:
            pass
        return True

    # ── تمرير النداءات للشاشة الحقيقية ──
    def __getattr__(self, name):
        """أي دالة غير معروفة تُمرَّر للشاشة الفعلية (refresh مثلاً).

        يُستدعى فقط عند فشل البحث المعتاد، فلا يتعارض مع خصائص Qt.
        """
        # أسماء الغلاف نفسه لا تُمرَّر للشاشة الداخلية
        if name.startswith("_") or name in ("ensure", "built", "real",
                                            "release"):
            raise AttributeError(name)
        real = self.__dict__.get("_real")
        if real is None:
            factory = self.__dict__.get("_factory")
            if factory is None:
                raise AttributeError(name)
            real = self.ensure()
        return getattr(real, name)
