# -*- coding: utf-8 -*-
"""الهوية البصرية: RTL كامل، خط واضح، ولوحة ذهبي معتّق على خلفية دافئة."""
from PyQt5 import QtCore, QtGui

QSS = """
QWidget { background: #FBF9F4; color: #2B2723; font-size: 14px; }
QLabel { background: transparent; }
QLabel#title { font-size: 21px; font-weight: bold; color: #8A6D1D; padding: 4px; }
QLabel#big { font-size: 16px; font-weight: bold; color: #2B2723; }
QLabel#warn { font-size: 16px; font-weight: bold; color: #B02A2A; }
QGroupBox { border: 1px solid #DCD5C6; border-radius: 8px;
            margin-top: 20px; padding: 10px; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top right;
                   right: 14px; padding: 0 6px; color: #8A6D1D; }
QPushButton { background: #8A6D1D; color: white; border: none;
              border-radius: 6px; padding: 9px 20px; font-weight: bold; }
QPushButton:hover { background: #A5831F; }
QPushButton:disabled { background: #C9C2B2; }
QPushButton#danger { background: #8C2F2F; }
QPushButton#danger:hover { background: #A63A3A; }
QPushButton#ghost { background: #EFEAE0; color: #5A5346; }
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QDateEdit, QTextEdit {
  background: white; border: 1px solid #CFC8BA; border-radius: 6px;
  padding: 6px 8px; selection-background-color: #C9A227; }
QTableWidget { background: white; alternate-background-color: #FAFAFA;
  font-size: 12pt; gridline-color: #E4E4E4; selection-background-color: #E8DCC0;
  selection-color: #1A1A1A;
  gridline-color: #E6E0D2; border: 1px solid #DCD5C6; border-radius: 6px; }
QTableWidget::item { padding: 4px 6px; }
QHeaderView::section { background: #2B2723; color: #EFE7D3; padding: 9px;
  font-size: 11.5pt; font-weight: bold; border: none;
  border-left: 1px solid #443E37;
  border: none; font-weight: bold; }
/* ══════════ الشريط الجانبي ══════════
   خلفية بيضاء وأسماء سوداء بارزة لأقصى وضوح، وإطار ذهبي زجاجي
   بلمعة متدرّجة. المؤشَّر عليه يتوهّج ذهبياً، والمحدَّد ذهب ثابت. */
QListWidget#sidebar, QTreeWidget#sidebar {
  background: #FFFFFF;
  color: #1A1A1A;
  border: none;
  border-left: 3px solid qlineargradient(x1:0, y1:0, x2:0, y2:1,
      stop:0    #FFF3C4,
      stop:0.18 #E8C766,
      stop:0.38 #C9A227,
      stop:0.52 #FFF8DC,
      stop:0.66 #C9A227,
      stop:0.86 #E8C766,
      stop:1    #FFF3C4);
  font-size: 15px;
  font-weight: bold;
  outline: none;
  padding: 4px 0;
}
/* كل شاشة بطاقة زجاجية قائمة بذاتها: برواز ذهبي خفيف ولمعة
   علوية — فتُعرف كشاشة مستقلة بلا حاجة للتمرير عليها. */
QListWidget#sidebar::item, QTreeWidget#sidebar::item {
  padding: 10px 13px;
  margin: 3px 6px;
  border-radius: 7px;
  color: #1A1A1A;
  font-weight: bold;
  border: 1px solid #E4D3A4;
  background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
      stop:0    #FFFFFF,
      stop:0.16 #FEFCF6,
      stop:0.50 #FAF6EA,
      stop:0.84 #F5EEDC,
      stop:1    #F0E6CF);
}
/* التمرير بالماوس: البطاقة نفسها تُضاء ذهباً زجاجياً */
QTreeWidget#sidebar::item:hover, QListWidget#sidebar::item:hover {
  background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
      stop:0    #FFFDF2,
      stop:0.14 #FCF0CE,
      stop:0.42 #F3E0A6,
      stop:0.58 #FFF9E2,
      stop:0.80 #EBD48A,
      stop:1    #E0C36B);
  border: 1px solid #C9A227;
  color: #1A1A1A;
}
/* المحدَّد: ذهب أعمق بإطار بارز — والخط أسود لبقاء الوضوح */
QListWidget#sidebar::item:selected, QTreeWidget#sidebar::item:selected {
  background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
      stop:0    #FBEFC4,
      stop:0.16 #F2DC9A,
      stop:0.46 #E4C665,
      stop:0.60 #FFF6D8,
      stop:0.82 #DDBB50,
      stop:1    #CFA936);
  border: 2px solid #A98A22;
  color: #14100A;
}
QTreeWidget#sidebar::branch { background: transparent; }
QTreeWidget#sidebar QScrollBar:vertical {
  background: #FAF7EF; width: 10px; margin: 0;
}
QTreeWidget#sidebar QScrollBar::handle:vertical {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
      stop:0 #E8C766, stop:0.5 #C9A227, stop:1 #E8C766);
  border-radius: 5px; min-height: 30px;
}
QTreeWidget#sidebar QScrollBar::add-line:vertical,
QTreeWidget#sidebar QScrollBar::sub-line:vertical { height: 0; }

/* الشريط الفرعي: عنوان الشاشة الحالية وزر الرجوع للرئيسية */
QFrame#subbar { background: #F4F0E7; border-bottom: 1px solid #DCD5C6; }
QLabel#crumb { font-size: 14pt; font-weight: bold; color: #4A4237; }
QPushButton#homeBtn { background: #8A6D1D; color: white; font-weight: bold;
  padding: 7px 18px; border-radius: 6px; font-size: 12pt; }

/* لوحات لوحة التحكم: بطاقة مضغوطة قابلة للتحديد */
QPushButton#dashPanel {
  background: #FBF9F4;
  border: 1px solid #D8CDB4;
  border-radius: 6px;
  padding: 5px 9px;
  font-size: 10pt;
  font-weight: bold;
  color: #4A3A1E;
  text-align: center;
}
QPushButton#dashPanel:hover {
  background: #F3EDDF;
  border-color: #B79A5E;
}
/* زر التحديثات حين يتوفّر إصدار جديد: يلمع ذهبياً ليُلفت النظر */
QPushButton#updateReady {
  background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
      stop:0    #FFF7D6,
      stop:0.30 #F2DC9A,
      stop:0.60 #E4C665,
      stop:1    #CFA936);
  border: 2px solid #A98A22;
  border-radius: 6px;
  color: #14100A;
  font-weight: bold;
  padding: 5px 12px;
}
QPushButton#updateReady:hover {
  background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
      stop:0 #FFFDF2, stop:0.5 #F5DE9B, stop:1 #D9B84A);
}

QFrame#ratioBar {
  background: #F3EDDF;
  border: 1px solid #C7B48A;
  border-right: 4px solid #B79A5E;
  border-radius: 5px;
}
QFrame#ratioBar QLabel {
  font-size: 11pt;
  font-weight: bold;
  color: #4A3A1E;
}

QPushButton#dashPanel:checked {
  background: #B79A5E;
  border: 2px solid #8B7333;
  color: #FFFFFF;
}

QPushButton#homeBtn:hover { background: #A6842A; }
QPushButton#closeBtn { background: #8A3A2A; color: white; font-weight: bold;
  padding: 7px 18px; border-radius: 6px; font-size: 12pt; }
QPushButton#closeBtn:hover { background: #A6472F; }

/* شاشة الترحيب */
QWidget#welcomeRoot { background: #FBF9F4; }
QLabel#welcomeName { font-size: 24pt; font-weight: bold; color: #C6A227;
  padding-top: 14px; }
QLabel#welcomeSub { font-size: 12pt; color: #7A7266; }
QLabel#welcomeHint { font-size: 12pt; color: #9aa0a6; }

/* بطاقات الشاشة الرئيسية */
QFrame#tile { background: white; border: 1px solid #DCD5C6; border-radius: 10px; }
QFrame#tile:hover { border: 2px solid #C9A227; background: #FFFDF6; }
QLabel#tileIcon { font-size: 26pt; }
QLabel#tileTitle { font-size: 13.5pt; font-weight: bold; color: #2B2723; }
QLabel#tileSub { font-size: 10.5pt; color: #7A7266; }
QLabel#groupTitle { font-size: 13pt; font-weight: bold; color: #8A6D1D;
  padding-top: 6px; }
QTabWidget::pane { border: 1px solid #DCD5C6; border-radius: 6px; }
QTabBar::tab { background: #EFEAE0; padding: 8px 22px; margin: 2px;
  border-radius: 6px; font-weight: bold; }
QTabBar::tab:selected { background: #8A6D1D; color: white; }
QFrame#header { background: #2B2723; }
QLabel#headerTitle { color: #EFE7D3; font-size: 18px; font-weight: bold; }
QLabel#headerUser { color: #C9A227; font-size: 14px; font-weight: bold; }
QFrame#card { background: white; border: 1px solid #DCD5C6; border-radius: 10px;
  padding: 4px; }
QFrame#card:hover { border: 1px solid #C9A227; background: #FBF6E8; }
QLabel#cardTitle { color: #8A6D1D; font-size: 13px; font-weight: bold; }
QLabel#cardValue { color: #2B2723; font-size: 20px; font-weight: bold; }
QLabel#cardSub { color: #7A7364; font-size: 12px; }
QPushButton#dangerBtn { background: #8B1E1E; color: #fff; font-weight: bold;
  padding: 8px 18px; border: none; border-radius: 5px; }
QPushButton#dangerBtn:hover { background: #A32424; }
QGroupBox { border: 1px solid #C9C2B4; border-radius: 5px;
  margin-top: 10px; padding-top: 8px; }

/* شريط سعر الأونصة العالمية الحي */
/* ══ شريط سعر الذهب — بلغة الشريط الجانبي نفسها ══
   خلفية زجاجية فاتحة، برواز ذهبي، وخط أسود بارز؛ وبطاقات
   الأعيرة نسخة مصغّرة من بطاقة الشاشة في الشريط الجانبي. */
QFrame#goldBar {
  background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
      stop:0    #FFFFFF,
      stop:0.16 #FEFCF6,
      stop:0.50 #FAF6EA,
      stop:0.84 #F5EEDC,
      stop:1    #F0E6CF);
  border: 1px solid #E4D3A4;
  border-top: 3px solid qlineargradient(x1:0, y1:0, x2:1, y2:0,
      stop:0    #FFF3C4,
      stop:0.18 #E8C766,
      stop:0.38 #C9A227,
      stop:0.52 #FFF8DC,
      stop:0.66 #C9A227,
      stop:0.86 #E8C766,
      stop:1    #FFF3C4);
  border-radius: 7px;
  padding: 8px;
  margin: 3px 6px;
}
QLabel#goldBarTitle {
  color: #6B5518; font-size: 12px; font-weight: bold;
}
QLabel#goldBarValue {
  color: #1A1A1A; font-size: 17px; font-weight: bold;
}
QLabel#goldBarSub   { color: #4A3A1E; font-size: 11px; }
QLabel#goldBarStamp { color: #8A7F66; font-size: 10px; }
QLabel#goldKarat {
  color: #1A1A1A; font-size: 13px; font-weight: bold;
  background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
      stop:0    #FFFBEA,
      stop:0.35 #F7E7B4,
      stop:0.70 #EFD98F,
      stop:1    #E4C867);
  border: 1px solid #C9A227;
  border-radius: 5px;
  padding: 5px 7px;
}

/* لوحات تحليل المبيعات */
QFrame#statPanel { background: white; border: 1px solid #DCD5C6;
  border-radius: 10px; padding: 6px; }
QFrame#statPanel:hover { border: 1px solid #C9A227; }
QLabel#panelTitle { font-size: 12pt; font-weight: bold; color: #8A6D1D; }
QLabel#panelValue { font-size: 18pt; font-weight: bold; color: #2B2723; }
QLabel#panelSub { font-size: 9.5pt; color: #7A7266; }
"""


def apply(app):
    app.setLayoutDirection(QtCore.Qt.RightToLeft)
    font = QtGui.QFont("Segoe UI", 10)
    app.setFont(font)
    app.setStyleSheet(QSS)
