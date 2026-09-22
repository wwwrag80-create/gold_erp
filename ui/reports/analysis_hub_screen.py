# -*- coding: utf-8 -*-
"""التحليل والدراسات — أربعة تقارير في شاشةٍ واحدة بأقسام.

**العلة**: أربع شاشاتٍ تسأل أسئلةً متجاورة — حركة الرصيد، وأعمار
الموديلات، وملف الجهة، وربحية الموديل — كانت أربعة بنودٍ في القائمة
الجانبية، لكلٍّ عنوانه وشرحُه ولوحاتُه. فمن أراد أن ينتقل بينها خرج
من الشاشة ودخل أخرى، وضاع نصفُ الارتفاع في عناوين تتكرّر.

**الحل**: قسمٌ واحد في القائمة، وأقسامُه شريطٌ **أعلى** الشاشة. يُضغط
القسم فتُفتح واجهته أسفله — والعنوان مكتوبٌ مرةً واحدة فوق الشريط،
فيبقى الارتفاع كلُّه للجداول وهي أحوجُ ما يكون إليه.

**والبناء كسول**: لا يُبنى القسم حتى يُفتح أول مرة. فبناءُ أربع شاشاتٍ
دفعةً واحدة يعني أربع استعلاماتٍ للقوائم وأربعة جداول تُنشأ قبل أن
يطلبها أحد — وهو ما يجعل فتح الشاشة يتأخّر بلا سبب. ومن فتح قسماً
واحداً لا يدفع ثمن الثلاثة الباقية.
"""
from PyQt5 import QtCore, QtWidgets

from ui.widgets.common import tab_widget, title_label

# (العنوان، الوحدة، الصنف) — ترتيبُ العرض ترتيبُ الاستعمال
SECTIONS = [
    ("حركة الرصيد", "ui.reports.movement_screen", "MovementScreen"),
    ("ملف الجهة", "ui.reports.dossier_screen", "DossierScreen"),
    ("أعمار الموديلات", "ui.reports.stock_aging_screen",
     "StockAgingScreen"),
    ("ربحية الموديل", "ui.reports.model_profit_screen",
     "ModelProfitScreen"),
    ("أعمار الديون", "ui.reports.aging_screen", "AgingScreen"),
]


class AnalysisHubScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self._built = {}                     # فهرس القسم ← الشاشة

        self.tabs = tab_widget()
        for label, _mod, _cls in SECTIONS:
            # صفحةٌ خاوية تُستبدل بالشاشة عند أول فتح
            holder = QtWidgets.QWidget()
            QtWidgets.QVBoxLayout(holder).setContentsMargins(0, 0, 0, 0)
            self.tabs.addTab(holder, label)
        self.tabs.currentChanged.connect(self._ensure)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        lay.addWidget(title_label("التحليل والدراسات"))
        lay.addWidget(self.tabs, 1)

        # القسم الأول يُبنى بعد أن تُرسم الشاشة، فلا يتأخّر فتحها
        QtCore.QTimer.singleShot(0, lambda: self._ensure(0))

    # ─────────────────────────────── بناءٌ عند الطلب
    def _ensure(self, index):
        """يبني قسماً إن لم يكن مبنيّاً — ويُظهر الخطأ ولا يُسقط الشاشة."""
        if index in self._built or not (0 <= index < len(SECTIONS)):
            return
        label, mod_name, cls_name = SECTIONS[index]
        holder = self.tabs.widget(index)
        try:
            mod = __import__(mod_name, fromlist=[cls_name])
            w = getattr(mod, cls_name)(self.user, embedded=True)
        except Exception as e:                       # noqa: BLE001
            w = QtWidgets.QLabel(f"تعذّر فتح «{label}»:\n{e}")
            w.setObjectName("warn")
            w.setWordWrap(True)
        holder.layout().addWidget(w)
        self._built[index] = w

    # ─────────────────────────────── تمريرٌ للقسم المفتوح
    def current(self):
        return self._built.get(self.tabs.currentIndex())

    def refresh(self):
        """يُحدِّث القسم المفتوح وحده — لا الأربعة.

        تحديثُ ما لا يُرى استعلامٌ بلا قارئ؛ وكلُّ قسمٍ يُحدَّث حين
        يُفتح على أي حال.
        """
        self._ensure(self.tabs.currentIndex())
        w = self.current()
        fn = getattr(w, "refresh", None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass
