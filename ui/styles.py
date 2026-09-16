# -*- coding: utf-8 -*-
"""الهوية البصرية: RTL كامل، خط واضح، ولوحة ذهبي معتّق على خلفية دافئة."""
from PyQt5 import QtCore, QtGui

QSS = """
/* ══════════════════════════════════════════════════════════════════
   الهوية البصرية — نظام تصميم واحد لا مجموعة ألوان متفرّقة
   ------------------------------------------------------------------
   الركائز:
   · الأسطح بيضاء والخلفية رملية فاتحة، والحدود رفيعة بلون واحد —
     فالشاشة تُقرأ بالتباين لا بالخطوط الثقيلة.
   · الذهب لون **الفعل والعناوين** لا لون كل شيء؛ استعماله في كل
     موضع يُفقده معناه.
   · نصف قطر موحّد: 10 للبطاقات و8 للحقول والأزرار.
   · حالة كل عنصر معلومة: عادي · تمرير · تركيز · معطّل — والتركيز
     يُرى دائماً (حلقة ذهبية) لأن الإدخال هنا بلوحة المفاتيح غالباً.

   الألوان:
   الحبر #1F1B17 · الخافت #6B6459 · الخلفية #F7F5F0 · السطح #FFFFFF
   الحد #E3DDD0 · الحد البارز #CFC7B6 · الذهب #9A7B22 · الذهب الفاتح
   #EFE6CE · أخضر #1E6B33 · أحمر #B02A2A
   ══════════════════════════════════════════════════════════════════ */

QWidget { background: #F7F5F0; color: #1F1B17; font-size: 14px; }
QLabel { background: transparent; }
QLabel#title { font-size: 19px; font-weight: bold; color: #7A611A;
               padding: 6px 2px 2px 2px; }
QLabel#big { font-size: 15px; font-weight: bold; color: #1F1B17; }
QLabel#warn { font-size: 15px; font-weight: bold; color: #B02A2A; }
QToolTip { background: #2B2723; color: #F3EEE2; border: none;
           padding: 6px 9px; border-radius: 6px; }

/* ══ الحاويات ══ */
QGroupBox { border: 1px solid #E3DDD0; border-radius: 10px;
            margin-top: 18px; padding: 12px 10px 10px 10px;
            font-weight: bold; background: #FFFFFF; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top right;
                   right: 14px; padding: 0 6px; color: #7A611A;
                   background: transparent; }

/* ══ الأزرار ══
   الأساسي ذهبي ممتلئ، والثانوي محدّد بإطار، والخفيف بلا لون —
   ثلاث درجات تكفي لتُعرف أهمية كل زر من شكله. */
QPushButton { background: #9A7B22; color: #FFFFFF; border: none;
              border-radius: 8px; padding: 9px 18px; font-weight: bold; }
QPushButton:hover { background: #B08E2A; }
QPushButton:pressed { background: #7A611A; }
QPushButton:disabled { background: #DED8CB; color: #9A9384; }
QPushButton:focus { border: 2px solid #E4C665; }
QPushButton#ghost { background: #FFFFFF; color: #5A5346;
                    border: 1px solid #D6CFC0; }
QPushButton#ghost:hover { background: #F3EFE6; border-color: #C0B79F; }
QPushButton#danger, QPushButton#dangerBtn { background: #A33131; }
QPushButton#danger:hover, QPushButton#dangerBtn:hover { background: #BE3C3C; }

/* ══ الحقول ══ */
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QDateEdit, QTextEdit {
  background: #FFFFFF; border: 1px solid #D6CFC0; border-radius: 8px;
  padding: 6px 9px; selection-background-color: #E4C665;
  selection-color: #1F1B17; }
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus,
QDateEdit:focus, QTextEdit:focus { border: 2px solid #C9A227;
  background: #FFFDF6; }
QLineEdit:disabled, QDoubleSpinBox:disabled, QComboBox:disabled,
QDateEdit:disabled { background: #F2EFE8; color: #9A9384; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: #FFFFFF; border: 1px solid #D6CFC0;
  selection-background-color: #F3E9CE; selection-color: #1F1B17;
  outline: none; padding: 2px; }
QCheckBox { spacing: 7px; }
QCheckBox::indicator { width: 17px; height: 17px; border-radius: 4px;
  border: 1px solid #C0B79F; background: #FFFFFF; }
QCheckBox::indicator:checked { background: #9A7B22; border-color: #7A611A; }

/* ══ الجداول ══
   الرأس فاتح لا أسود: الرأس الداكن يسحب العين إليه وهي يجب أن تكون
   على الأرقام. التمييز بالثقل والخط الفاصل يكفي. */
QTableWidget, QTreeWidget, QListWidget {
  background: #FFFFFF; alternate-background-color: #FAF8F3;
  gridline-color: #EDE8DC; border: 1px solid #E3DDD0; border-radius: 10px;
  selection-background-color: #F3E9CE; selection-color: #1F1B17;
  font-size: 12pt; }
QTableWidget::item { padding: 5px 6px; }
QTableWidget::item:hover { background: #FBF7EC; }
QHeaderView::section { background: #F1ECE0; color: #4A4237; padding: 9px 6px;
  font-size: 11pt; font-weight: bold; border: none;
  border-bottom: 2px solid #D8CDB4; border-left: 1px solid #E6E0D2; }
QHeaderView::section:first { border-left: none; }

/* ══ التبويبات: خط سفلي بدل الحبّات الممتلئة ══ */
QTabWidget::pane { border: 1px solid #E3DDD0; border-radius: 10px;
                   background: #FFFFFF; top: -1px; }
QTabBar::tab { background: transparent; padding: 9px 20px; margin: 0 2px;
  color: #6B6459; font-weight: bold; border-bottom: 3px solid transparent; }
QTabBar::tab:hover { color: #7A611A; }
QTabBar::tab:selected { color: #7A611A; border-bottom: 3px solid #9A7B22; }

/* ══ أشرطة التمرير: رفيعة محايدة ══ */
QScrollBar:vertical { background: transparent; width: 11px; margin: 2px; }
QScrollBar::handle:vertical { background: #D8D1C2; border-radius: 5px;
  min-height: 34px; }
QScrollBar::handle:vertical:hover { background: #C0B79F; }
QScrollBar:horizontal { background: transparent; height: 11px; margin: 2px; }
QScrollBar::handle:horizontal { background: #D8D1C2; border-radius: 5px;
  min-width: 34px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* ══════════ الشريط الجانبي ══════════
   خلفية بيضاء وأسماء سوداء بارزة، وإطار ذهبي على الحافة. البطاقة
   المحدَّدة ذهبٌ هادئ لا متدرّج صارخ — التمييز بالوضوح لا باللمعان. */
QListWidget#sidebar, QTreeWidget#sidebar {
  background: #FFFFFF;
  color: #1F1B17;
  border: none;
  border-left: 3px solid qlineargradient(x1:0, y1:0, x2:0, y2:1,
      stop:0 #F0E0AE, stop:0.5 #C9A227, stop:1 #F0E0AE);
  border-radius: 0;
  font-size: 14.5px;
  font-weight: bold;
  outline: none;
  padding: 6px 0;
}
QListWidget#sidebar::item, QTreeWidget#sidebar::item {
  padding: 10px 12px;
  margin: 2px 7px;
  border-radius: 8px;
  color: #1F1B17;
  border: 1px solid transparent;
  background: #FCFAF5;
}
QTreeWidget#sidebar::item:hover, QListWidget#sidebar::item:hover {
  background: #F7EFD9;
  border: 1px solid #E0CC8F;
}
QListWidget#sidebar::item:selected, QTreeWidget#sidebar::item:selected {
  background: #EFDFAE;
  border: 1px solid #B99B33;
  color: #14100A;
}
QTreeWidget#sidebar::branch { background: transparent; }

/* ══ الشريطان العلوي والفرعي ══ */
QFrame#header { background: #2B2723; border-bottom: 2px solid #9A7B22; }
QLabel#headerTitle { color: #F3EEE2; font-size: 17px; font-weight: bold; }
QLabel#headerUser { color: #E4C665; font-size: 13px; font-weight: bold; }
QFrame#header QPushButton { background: #3A342D; color: #F3EEE2;
  border: 1px solid #4E463C; border-radius: 7px; padding: 7px 12px; }
QFrame#header QPushButton:hover { background: #4A4239; border-color: #9A7B22; }
QFrame#header QPushButton#ghost { background: #3A342D; color: #E8E1D2; }
QFrame#header QComboBox, QFrame#header QLineEdit {
  background: #FFFFFF; border: 1px solid #4E463C; }
QFrame#subbar { background: #FFFFFF; border-bottom: 1px solid #E3DDD0; }
QLabel#crumb { font-size: 13pt; font-weight: bold; color: #3F382E; }
QPushButton#homeBtn { background: #9A7B22; color: white; font-weight: bold;
  padding: 7px 16px; border-radius: 8px; font-size: 11.5pt; }
QPushButton#homeBtn:hover { background: #B08E2A; }
QPushButton#closeBtn { background: #FFFFFF; color: #A33131; font-weight: bold;
  padding: 7px 16px; border-radius: 8px; font-size: 11.5pt;
  border: 1px solid #E2C3C3; }
QPushButton#closeBtn:hover { background: #A33131; color: #FFFFFF; }

/* ══ لوحات لوحة التحكم ══ */
QPushButton#dashPanel {
  background: #FFFFFF; border: 1px solid #E3DDD0; border-radius: 9px;
  padding: 7px 11px; font-size: 10pt; font-weight: bold; color: #4A4237;
  text-align: center;
}
QPushButton#dashPanel:hover { background: #FBF7EC; border-color: #D8CDB4; }
QPushButton#dashPanel:checked { background: #EFDFAE; border: 1px solid #B99B33;
  color: #1F1B17; }
QPushButton#updateReady {
  background: #E4C665; border: 1px solid #B99B33; border-radius: 7px;
  color: #14100A; font-weight: bold; padding: 6px 12px;
}
QPushButton#updateReady:hover { background: #EFD98F; }
QFrame#ratioBar { background: #FFFFFF; border: 1px solid #E3DDD0;
  border-right: 4px solid #C9A227; border-radius: 8px; }
QFrame#ratioBar QLabel { font-size: 11pt; font-weight: bold; color: #4A4237; }

/* ══ شاشة الترحيب والبطاقات ══ */
QWidget#welcomeRoot { background: #F7F5F0; }
QLabel#welcomeName { font-size: 23pt; font-weight: bold; color: #B08E2A;
  padding-top: 14px; }
QLabel#welcomeSub { font-size: 12pt; color: #6B6459; }
QLabel#welcomeHint { font-size: 11.5pt; color: #9A9384; }
QFrame#tile { background: #FFFFFF; border: 1px solid #E3DDD0;
  border-radius: 12px; }
QFrame#tile:hover { border: 1px solid #C9A227; background: #FFFDF6; }
QLabel#tileIcon { font-size: 25pt; }
QLabel#tileTitle { font-size: 13pt; font-weight: bold; color: #1F1B17; }
QLabel#tileSub { font-size: 10.5pt; color: #6B6459; }
QLabel#groupTitle { font-size: 12.5pt; font-weight: bold; color: #7A611A;
  padding-top: 6px; }

QFrame#card { background: #FFFFFF; border: 1px solid #E3DDD0;
  border-radius: 10px; padding: 6px; }
QFrame#card:hover { border: 1px solid #C9A227; background: #FFFDF6; }
QLabel#cardTitle { color: #7A611A; font-size: 12.5px; font-weight: bold; }
QLabel#cardValue { color: #1F1B17; font-size: 19px; font-weight: bold; }
QLabel#cardSub { color: #6B6459; font-size: 11.5px; }

/* ══ شريط سعر الذهب الحي ══ */
QFrame#goldBar {
  background: #FFFFFF;
  border: 1px solid #E3DDD0;
  border-top: 3px solid #C9A227;
  border-radius: 10px;
  padding: 8px;
  margin: 4px 7px;
}
QLabel#goldBarTitle { color: #7A611A; font-size: 12px; font-weight: bold; }
QLabel#goldBarValue { color: #1F1B17; font-size: 17px; font-weight: bold; }
QLabel#goldBarSub   { color: #4A4237; font-size: 11px; }
QLabel#goldBarStamp { color: #9A9384; font-size: 10px; }
QLabel#goldKarat {
  color: #1F1B17; font-size: 13px; font-weight: bold;
  background: #F7EFD9; border: 1px solid #E0CC8F;
  border-radius: 7px; padding: 5px 7px;
}

/* ══ لوحات تحليل المبيعات ══ */
QFrame#statPanel { background: #FFFFFF; border: 1px solid #E3DDD0;
  border-radius: 12px; padding: 6px; }
QFrame#statPanel:hover { border: 1px solid #C9A227; }
QLabel#panelTitle { font-size: 11.5pt; font-weight: bold; color: #7A611A; }
QLabel#panelValue { font-size: 18pt; font-weight: bold; color: #1F1B17; }
QLabel#panelSub { font-size: 9.5pt; color: #6B6459; }

/* ══ الحوارات ══ */
QDialog { background: #F7F5F0; }
QMessageBox { background: #FFFFFF; }
QMessageBox QLabel { font-size: 13px; }
"""


def apply(app):
    app.setLayoutDirection(QtCore.Qt.RightToLeft)
    # ══ شكل الأرقام: إنجليزية دائماً ══
    # على ويندوز بلغة عربية تُنتج Qt أرقاماً عربية-هندية في حقول
    # التاريخ (٢٠٢٦-٠٩-١٦). والتواريخ تُحفظ نصاً وتُقارَن نصاً، ورمز
    # الرقم العربي أكبر من الإنجليزي في يونيكود — فيفشل شرط «أصغر من
    # أو يساوي» ويسقط القيد من كل فلتر تاريخ. ومن هنا كُتبت تواريخ
    # عربية في القاعدة، ومن هنا صارت الفلاتر نفسها عربية فلا تطابق
    # شيئاً وتظهر كل الحركات «رصيداً سابقاً».
    # لغة الواجهة نصوصها مكتوبة في الكود، فضبط اللغة هنا لا يغيّر
    # كلمةً واحدة — يضبط شكل الأرقام والتواريخ وحدها.
    QtCore.QLocale.setDefault(
        QtCore.QLocale(QtCore.QLocale.English, QtCore.QLocale.UnitedStates))
    font = QtGui.QFont("Segoe UI", 10)
    app.setFont(font)
    app.setStyleSheet(QSS)
