# -*- coding: utf-8 -*-
"""تبويباتٌ تُبنى عند أول فتحٍ لها لا كلُّها مع الشاشة (5.6.0).

**الشكوى**: «شاشة المبيعات الضريبية تتأخر عند الفتح». كانت تبني تبويباتها
كلها دفعةً واحدة — الفاتورة والمرتجع والسجل وفواتير المندوب بتبويباتها
الأربعة — وأغلبها لا يُفتح في الزيارة أصلاً. فقيس: ثلثا زمن الفتح في
تبويباتٍ لم تُرَ.

فالتبويب هنا حاويةٌ فارغة، ومحتواه يُبنى عند أول اختيارٍ له (أو أول طلبٍ
له من الشيفرة) ثم يبقى. والشاشة نفسها تسأل `get(i)` فتجد المكوّن مبنيّاً
أيّاً كان سبب طلبه.
"""
from PyQt5 import QtWidgets


class LazyTabs:
    def __init__(self, tabs):
        self.tabs = tabs
        self._items = []           # [{"factory","wrap","host","widget"}]

    def add(self, label, factory, wrap=None, icon=None):
        """يضيف تبويباً يُبنى محتواه عند الحاجة — ويعيد رقمه."""
        host = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._items.append({"factory": factory, "wrap": wrap, "host": host,
                            "widget": None})
        if icon is not None:
            return self.tabs.addTab(host, icon, label)
        return self.tabs.addTab(host, label)

    def built(self, i):
        return 0 <= i < len(self._items) and \
            self._items[i]["widget"] is not None

    def get(self, i):
        """المكوّن الحقيقي للتبويب `i` — يُبنى الآن إن لم يُبنَ."""
        if not 0 <= i < len(self._items):
            return None
        it = self._items[i]
        if it["widget"] is None:
            w = it["factory"]()
            it["widget"] = w
            shown = it["wrap"](w) if it["wrap"] else w
            it["host"].layout().addWidget(shown)
        return it["widget"]

    def current(self):
        return self.get(self.tabs.currentIndex())

    def index_of(self, widget):
        for i, it in enumerate(self._items):
            if it["widget"] is widget:
                return i
        return -1
