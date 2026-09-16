#!/usr/bin/env python3
"""فحص ثابت (شغّله قبل كل تسليم): كل `self.X` يُستدعى أو يُربط بإشارة يجب أن يكون معرَّفاً.

يكتشف تحديداً نوع الخطأ الذي حدث: دالة رُبطت بزر لكنها لم تُعرَّف —
وهو ما لا يكشفه الـstub لأنه يُرجع كائناً وهمياً لأي اسم مفقود.
"""
import ast, glob, sys

# دوال Qt الموروثة الشائعة التي قد تُربط أو تُستدعى بشكل مشروع
QT_INHERITED = {
    "close", "show", "hide", "update", "repaint", "setFocus", "raise_",
    "accept", "reject", "done", "deleteLater", "setEnabled", "setVisible",
    "setWindowTitle", "resize", "exec_", "parent", "window", "font",
    "setFont", "setLayout", "layout", "setObjectName", "objectName",
    "setToolTip", "setMinimumWidth", "setMaximumWidth", "setStyleSheet",
    "adjustSize", "activateWindow", "showMaximized", "showNormal",
    "setCursor", "mouseReleaseEvent", "setContentsMargins", "setSpacing",
    "sender", "installEventFilter", "removeEventFilter", "setProperty",
    "property", "style", "unpolish", "polish", "setSizePolicy", "geometry",
    "setGeometry", "move", "width", "height", "isVisible", "setCheckable",
    "setChecked", "isChecked", "addWidget", "addLayout", "setCentralWidget",
    "statusBar", "menuBar", "setWindowIcon", "setMinimumSize", "showEvent",
    "closeEvent", "keyPressEvent", "eventFilter", "setWindowState",
    # موروثة من QComboBox / QFrame / QDialog / QLineEdit
    "setEditable", "setInsertPolicy", "lineEdit", "model", "setCompleter",
    # موروثات QComboBox/QLabel المستعملة في الأصناف المشتقة
    "setSizeAdjustPolicy", "setMinimumContentsLength", "view",
    "rect", "alignment", "setAlignment", "text", "setText",
    "minimumSizeHint", "sizeHint", "paintEvent", "setWordWrap",
    # موروثات QDialog/QWidget في نوافذ الأدوات (شريط الأوامر)
    "setWindowFlags", "setWindowTitle", "accept", "reject", "resize",
    "move", "width", "height", "parent", "window", "setFocus", "selectAll",
    "itemText", "count", "setCurrentIndex", "currentIndex", "itemData",
    "setFrameShape", "setModal", "addItem", "clear", "findData",
    "currentData", "currentText", "setText", "text", "setValue", "value",
    "setRange", "setDecimals", "setSuffix", "setPlaceholderText",
    "selectAll", "setDate", "date", "setCalendarPopup", "setDisplayFormat",
    "setWordWrap", "setAlignment", "setPixmap", "setReadOnly",
    "setPlainText", "setMaximumHeight", "setMinimumHeight",
}

# دوال اختيارية يُتحقق منها بـhasattr قبل الاستدعاء
OPTIONAL = {"on_edit_cancelled", "refresh", "load_document"}

problems = []
import os
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

for path in sorted(glob.glob("ui/**/*.py", recursive=True)):
    tree = ast.parse(open(path).read(), path)
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        defined = {m.name for m in cls.body
                   if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assigned = set()
        for n in ast.walk(cls):
            if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                    and n.value.id == "self" and isinstance(n.ctx, ast.Store)):
                assigned.add(n.attr)
        # الوراثة من أصناف مشروعنا (مثل EditModeMixin)
        bases = {b.id if isinstance(b, ast.Name) else
                 (b.attr if isinstance(b, ast.Attribute) else "") 
                 for b in cls.bases}
        mixin_methods = set()
        if "EditModeMixin" in bases:
            mixin_methods = {"init_edit_mode", "edit_widgets", "begin_edit",
                             "cancel_edit", "end_edit", "is_editing",
                             "_sync_edit_ui", "edit_banner", "btn_cancel_edit",
                             "editing_entry_id", "editing_source_id"}
        known = defined | assigned | QT_INHERITED | mixin_methods | OPTIONAL

        used = {}
        for n in ast.walk(cls):
            # self.X(...)  — استدعاء مباشر
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and isinstance(n.func.value, ast.Name)
                    and n.func.value.id == "self"):
                used.setdefault(n.func.attr, n.lineno)
            # ....connect(self.X)  — ربط بإشارة
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "connect"):
                for a in n.args:
                    if (isinstance(a, ast.Attribute)
                            and isinstance(a.value, ast.Name)
                            and a.value.id == "self"):
                        used.setdefault(a.attr, a.lineno)
        for name, line in sorted(used.items(), key=lambda kv: kv[1]):
            if name not in known:
                problems.append((path, cls.name, name, line))

if problems:
    print(f"✘ دوال مفقودة: {len(problems)}")
    for path, cls, name, line in problems:
        print(f"   {path}:{line}  {cls}.{name}  ← مستدعاة/مربوطة وغير معرَّفة")
    sys.exit(1)
print("✔ لا توجد دوال مربوطة أو مستدعاة بلا تعريف في أي شاشة")
