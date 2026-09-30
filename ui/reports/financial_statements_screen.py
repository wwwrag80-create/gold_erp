# -*- coding: utf-8 -*-
"""القوائم المالية — شاشةٌ واحدة تجمع كل ما يُرفع ويُراجَع.

كانت ستة بنودٍ متفرّقة في القائمة الجانبية؛ صارت تبويباتٍ بترتيبها
المحاسبي: ميزان المراجعة ← المركز المالي ← الدخل ← التغيرات في حقوق
الملكية ← التدفقات النقدية ← تسويات نهاية الفترة والقوائم الختامية.

كل تبويب يُبنى **عند أول فتحٍ له** لا مع الشاشة — ففتح «القوائم المالية»
لا يحسب ستّ قوائم دفعةً واحدة.
"""
from PyQt5 import QtWidgets

# استيرادٌ صريح (لا ديناميكي) — فيراها الـexe عند بنائه
from ui.reports.balance_sheet_screen import BalanceSheetScreen
from ui.reports.cash_flow_screen import CashFlowScreen
from ui.reports.equity_changes_screen import EquityChangesScreen
from ui.reports.income_statement import IncomeStatementScreen
from ui.reports.period_end_screen import PeriodEndScreen
from ui.reports.trial_balance_screen import TrialBalanceScreen
from ui.widgets.common import tab_widget, title_label

TABS = [
    ("ميزان المراجعة", TrialBalanceScreen),
    ("قائمة المركز المالي", BalanceSheetScreen),
    ("قائمة الدخل", IncomeStatementScreen),
    ("التغيرات في حقوق الملكية", EquityChangesScreen),
    ("التدفقات النقدية", CashFlowScreen),
    ("تسويات نهاية الفترة والقوائم الختامية", PeriodEndScreen),
]
# عنوان التبويب المختصر — ستة عناوين كاملة في شريطٍ لا يلتفّ كانت تفرض
# على الشاشة عرضاً أكبر من نافذة اللابتوب، فتنزاح القوائم خارج الإطار.
# الاسم الكامل في التلميح وفي `open_tab`.
SHORT = {
    "قائمة المركز المالي": "المركز المالي",
    "قائمة الدخل": "الدخل",
    "التغيرات في حقوق الملكية": "حقوق الملكية",
    "تسويات نهاية الفترة والقوائم الختامية": "نهاية الفترة",
}


class FinancialStatementsScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.screens = {}
        self.tabs = tab_widget()
        for title, _cls in TABS:
            holder = QtWidgets.QWidget()
            QtWidgets.QVBoxLayout(holder).setContentsMargins(0, 0, 0, 0)
            # الشاشة الداخلية لا تفرض عرضها على التبويب — تنطوي داخله
            holder.setSizePolicy(QtWidgets.QSizePolicy.Ignored,
                                 QtWidgets.QSizePolicy.Preferred)
            i = self.tabs.addTab(holder, SHORT.get(title, title))
            self.tabs.setTabToolTip(i, title)
        self.tabs.currentChanged.connect(self._ensure)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        lay.addWidget(title_label("القوائم المالية"))
        lay.addWidget(self.tabs, 1)
        self._ensure(0)

    def _ensure(self, i):
        """يبني تبويب القائمة عند أول فتحٍ له."""
        if i < 0 or i in self.screens:
            return self.screens.get(i)
        _title, cls = TABS[i]
        scr = cls(self.user)
        # عنوان الشاشة الداخلية يكرّر اسم التبويب — يُخفى
        for lb in scr.findChildren(QtWidgets.QLabel, "title"):
            lb.hide()
        self.tabs.widget(i).layout().addWidget(scr)
        self.screens[i] = scr
        return scr

    def open_tab(self, title):
        """يفتح تبويباً باسمه — لمن يريد قائمةً بعينها."""
        for i, (t, _c) in enumerate(TABS):
            if t == title:
                self.tabs.setCurrentIndex(i)
                return self._ensure(i)
        return None

    def refresh(self):
        scr = self.screens.get(self.tabs.currentIndex())
        if scr is not None and hasattr(scr, "refresh"):
            scr.refresh()
