# -*- coding: utf-8 -*-
"""شريط أدوات ينطوي على سطرين بدل أن يدفع الشاشة خارج إطارها.

**المشكلة**: شريطٌ أفقي (`QHBoxLayout`) فيه تاريخان وقوائم وخانات وثلاثة
أزرار يفرض على الشاشة حدّاً أدنى من العرض (١٥٠٠ بكسل في ميزان
المراجعة). فإن كانت النافذة أضيق — شاشة لابتوب مع الشريط الجانبي —
لا يصغر الشريط بل تتّسع الشاشة كلها خلف إطارها، وفي الواجهة العربية
يُقصّ طرفها الأيسر: نصف الجدول وأزراره خارج الرؤية.

**الحل**: `FlowLayout` يرصّ العناصر من اليمين ويكمل في سطرٍ جديد ما لا
يتّسع له السطر، فحدّه الأدنى عرضُ أعرض عنصرٍ فيه لا مجموع العناصر.
والتسمية المنتهية بـ«:» تبقى ملتصقةً بالحقل الذي بعدها — لا يُفصل
«من:» عن تاريخه في سطرين.

يقبل `addStretch`/`addSpacing` كـ`QHBoxLayout` فيُستبدل به بلا تعديلٍ
آخر.
"""
from PyQt5 import QtCore, QtWidgets


class FlowLayout(QtWidgets.QLayout):
    def __init__(self, parent=None, hspacing=6, vspacing=4):
        super().__init__(parent)
        self._items = []
        self._gap = {}          # فاصلٌ إضافي قبل العنصر (addSpacing)
        self._pending_gap = 0
        self._h = hspacing
        self._v = vspacing
        self.setContentsMargins(0, 0, 0, 0)

    # ── واجهة QHBoxLayout ─────────────────────────────────────────
    def setSpacing(self, s):
        self._h = s

    def spacing(self):
        return self._h

    def addStretch(self, _s=0):
        """السطر يبدأ من اليمين دائماً — لا حاجة لمطّاط."""

    def addSpacing(self, px):
        self._pending_gap += int(px)

    def addLayout(self, lay, _stretch=0):
        w = QtWidgets.QWidget()
        lay.setContentsMargins(0, 0, 0, 0)
        w.setLayout(lay)
        self.addWidget(w)

    def addWidget(self, w, _stretch=0, _align=None):
        super().addWidget(w)

    # ── واجهة QLayout ────────────────────────────────────────────
    def addItem(self, item):
        if self._pending_gap:
            self._gap[id(item)] = self._pending_gap
            self._pending_gap = 0
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        if 0 <= i < len(self._items):
            it = self._items.pop(i)
            self._gap.pop(id(it), None)
            return it
        return None

    def expandingDirections(self):
        return QtCore.Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QtCore.QRect(0, 0, w, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, apply=True)

    def sizeHint(self):
        # العرض المفضّل: الكل في سطرٍ واحد
        units = self._units()
        w = sum(u[1] for u in units) + self._h * max(0, len(units) - 1)
        h = max((u[2] for u in units), default=0)
        m = self.contentsMargins()
        return QtCore.QSize(w + m.left() + m.right(),
                            h + m.top() + m.bottom())

    def minimumSize(self):
        # الحدّ الأدنى: أعرض وحدةٍ واحدة — لا مجموعها
        units = self._units()
        w = max((u[1] for u in units), default=0)
        h = max((u[2] for u in units), default=0)
        m = self.contentsMargins()
        return QtCore.QSize(w + m.left() + m.right(),
                            h + m.top() + m.bottom())

    # ── الحساب ───────────────────────────────────────────────────
    def _visible(self):
        out = []
        for it in self._items:
            w = it.widget()
            if w is not None and w.isHidden():
                continue
            out.append(it)
        return out

    def _units(self):
        """وحدات لا تنقسم: تسميةٌ تنتهي بـ«:» مع الحقل الذي يليها.

        كل وحدة (العناصر، العرض، الارتفاع).
        """
        items = self._visible()
        units, i = [], 0
        while i < len(items):
            grp = [items[i]]
            # سلسلة: «نسبة المخصص:» ← «أقل من 30:» ← حقلها — كلها وحدة
            while self._glued(items[i]) and i + 1 < len(items):
                i += 1
                grp.append(items[i])
            i += 1
            sizes = [it.sizeHint() for it in grp]
            width = sum(s.width() for s in sizes) \
                + self._h * (len(grp) - 1) \
                + sum(self._gap.get(id(it), 0) for it in grp[1:])
            height = max(s.height() for s in sizes)
            units.append((grp, width, height, self._gap.get(id(grp[0]), 0)))
        return units

    @staticmethod
    def _glued(item):
        w = item.widget()
        return isinstance(w, QtWidgets.QLabel) \
            and w.text().rstrip().endswith(":")

    def _do(self, rect, apply):
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        lines, line, used = [], [], 0
        for u in self._units():
            extra = (self._h + u[3]) if line else 0
            if line and used + extra + u[1] > r.width():
                lines.append(line)
                line, used, extra = [], 0, 0
            line.append(u)
            used += extra + u[1]
        if line:
            lines.append(line)
        y = r.y()
        rtl = self._rtl()
        for ln in lines:
            lh = max(u[2] for u in ln)
            x = r.x()
            for k, (grp, _uw, _uh, gap) in enumerate(ln):
                if k:
                    x += self._h + gap
                for j, it in enumerate(grp):
                    if j:
                        x += self._h
                    s = it.sizeHint()
                    if apply:
                        g = QtCore.QRect(x, y + (lh - s.height()) // 2,
                                         s.width(), s.height())
                        if rtl:
                            g.moveLeft(r.x() + r.right() - g.right())
                        it.setGeometry(g)
                    x += s.width()
            y += lh + self._v
        return max(0, y - self._v - rect.y()) + m.bottom() if lines else 0

    def _rtl(self):
        w = self.parentWidget()
        d = w.layoutDirection() if w is not None \
            else QtWidgets.QApplication.layoutDirection()
        return d == QtCore.Qt.RightToLeft
