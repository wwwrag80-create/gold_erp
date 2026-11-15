# -*- coding: utf-8 -*-
"""ترتيب شجرة القائمة بأوامر صريحة لا بالسحب وحده (5.6.0).

**الشكوى**: «لا يمكنني ترتيب الشاشات ولا دمج شاشةٍ مع شاشةٍ أسفلها ولا
تغيير أسمائها». كان الترتيب كله بالسحب والإفلات: والإفلات «فوق» بندٍ
يجعله داخله و«بين» بندين يجعله بجواره — فرقُ بضع نقاط في موضع الفأرة،
وفي القائمة العربية (من اليمين) يلتبس أكثر. والتسمية بنقرٍ مزدوج يفتح
الشاشة أيضاً.

فهنا أوامر لا تلتبس، تعمل على أي `QTreeWidget`:

  ▲ أعلى · ▼ أسفل      — بين أخواتها في المستوى نفسه
  ⇲ داخل التي فوقها    — تصير شاشةً داخل الشاشة (أو المجموعة) التي فوقها
  ⇱ إخراجها مستوىً     — تخرج من الشاشة التي هي فيها إلى جوارها
  ✎ إعادة تسمية        — بنافذةٍ صغيرة فيها الاسم الحالي
  ⟲ الاسم الأصلي

ويبقى السحب والإفلات لمن يحبّه. والبند يُنقل **بكائنه نفسه** (take ثم
insert) فتبقى بياناته وما يشير إليه من الشاشات كما هو.
"""
from PyQt5 import QtGui, QtWidgets


def _siblings(tree, item):
    """(الأب أو None، موضعه بين أخواته)."""
    p = item.parent()
    if p is None:
        return None, tree.indexOfTopLevelItem(item)
    return p, p.indexOfChild(item)


def _take(tree, item):
    p, i = _siblings(tree, item)
    if p is None:
        return tree.takeTopLevelItem(i)
    return p.takeChild(i)


def _insert(tree, parent, pos, item):
    if parent is None:
        tree.insertTopLevelItem(pos, item)
    else:
        parent.insertChild(pos, item)


def _keep_open(item):
    """حالة الطيّ تضيع مع النقل — تُحفظ وتُعاد للبند وأبنائه."""
    state = []

    def walk(it):
        state.append((it, it.isExpanded()))
        for k in range(it.childCount()):
            walk(it.child(k))
    walk(item)
    return state


def _restore(state):
    for it, op in state:
        it.setExpanded(op)


def _count(tree, parent):
    return tree.topLevelItemCount() if parent is None else parent.childCount()


def _child(tree, parent, i):
    return tree.topLevelItem(i) if parent is None else parent.child(i)


def move(tree, item, delta, movable=None):
    """▲/▼ بين أخواتها — يتخطّى ما لا يُنقل (أقسام الشاشة الثابتة)."""
    if item is None:
        return False
    p, i = _siblings(tree, item)
    j = i + delta
    n = _count(tree, p)
    while 0 <= j < n and movable is not None and not movable(
            _child(tree, p, j)):
        j += delta
    if not 0 <= j < n:
        return False
    st = _keep_open(item)
    _take(tree, item)
    _insert(tree, p, j, item)
    _restore(st)
    tree.setCurrentItem(item)
    return True


def indent(tree, item, accepts=None):
    """⇲ تصير داخل البند الذي فوقها مباشرةً (آخر أبنائه)."""
    if item is None:
        return False
    p, i = _siblings(tree, item)
    if i <= 0:
        return False
    above = _child(tree, p, i - 1)
    if accepts is not None and not accepts(above):
        return False
    st = _keep_open(item)
    _take(tree, item)
    above.addChild(item)
    _restore(st)
    above.setExpanded(True)
    tree.setCurrentItem(item)
    return True


def outdent(tree, item):
    """⇱ تخرج من أبيها إلى جواره — بعده مباشرةً."""
    if item is None or item.parent() is None:
        return False
    p = item.parent()
    gp, pi = _siblings(tree, p)
    st = _keep_open(item)
    _take(tree, item)
    _insert(tree, gp, pi + 1, item)
    _restore(st)
    tree.setCurrentItem(item)
    return True


def rename(parent_w, item, original=""):
    """✎ نافذةٌ صغيرة بالاسم الحالي — الفارغ يُرجع الاسم الأصلي."""
    if item is None:
        return False
    name, ok = QtWidgets.QInputDialog.getText(
        parent_w, "إعادة تسمية",
        "الاسم الظاهر في القائمة:"
        + (f"\n(اسمها الأصلي: {original})" if original else ""),
        QtWidgets.QLineEdit.Normal, item.text(0))
    if not ok:
        return False
    name = " ".join(str(name).split())
    item.setText(0, name or original or item.text(0))
    return True


def menu(parent_w, tree, item, actions):
    """قائمة النقر الأيمن: `actions` = [(نص، دالة) أو None للفاصل]."""
    m = QtWidgets.QMenu(parent_w)
    for a in actions:
        if a is None:
            m.addSeparator()
            continue
        text, fn = a[0], a[1]
        act = m.addAction(text)
        act.triggered.connect(lambda _c=False, f=fn: f())
        if len(a) > 2 and not a[2]:
            act.setEnabled(False)
    m.exec_(QtGui.QCursor.pos())
    return m
