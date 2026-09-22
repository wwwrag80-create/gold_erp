# -*- coding: utf-8 -*-
"""الهوية البصرية: RTL كامل، خط واضح، ولوحة ذهبي معتّق.

**البنية هنا، واللون في `ui.theme`**: كل لون في هذا الملف اسمٌ رمزي
(`@ink` · `@surface` · `@gold`) يستبدله محرّك المظهر بقيمته من اللوحة
المختارة — فالوضع الفاتح والليلي بنيةٌ واحدة لا نسختان تتباعدان.
"""
from ui import theme

TEMPLATE = """
/* ══════════════════════════════════════════════════════════════════
   نظام تصميم واحد لا مجموعة ألوان متفرّقة
   ------------------------------------------------------------------
   الركائز:
   · الأسطح (@surface) على خلفية (@bg)، والحدود رفيعة بلون واحد —
     فالشاشة تُقرأ بالتباين لا بالخطوط الثقيلة.
   · الذهب لون **الفعل والعناوين** لا لون كل شيء؛ استعماله في كل
     موضع يُفقده معناه.
   · نصف قطر موحّد: 10 للبطاقات و8 للحقول والأزرار.
   · حالة كل عنصر معلومة: عادي · تمرير · تركيز · معطّل — والتركيز
     يُرى دائماً (حلقة ذهبية) لأن الإدخال هنا بلوحة المفاتيح غالباً.
   ══════════════════════════════════════════════════════════════════ */

QWidget { background: @bg; color: @ink; font-size: 14px; }
QLabel { background: transparent; }
QLabel#title { font-size: 19px; font-weight: bold; color: @goldDim;
               padding: 6px 2px 2px 2px; }
QLabel#big { font-size: 15px; font-weight: bold; color: @ink; }
QLabel#warn { font-size: 15px; font-weight: bold; color: @redText; }
QLabel#ok { font-size: 13px; font-weight: bold; color: @green; }
QToolTip { background: @tipBg; color: @tipFg; border: none;
           padding: 6px 9px; border-radius: 6px; }

/* ══ الحاويات ══ */
QGroupBox { border: 1px solid @line; border-radius: 10px;
            margin-top: 18px; padding: 12px 10px 10px 10px;
            font-weight: bold; background: @surface; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top right;
                   right: 14px; padding: 0 6px; color: @goldDim;
                   background: transparent; }

/* ══ الأزرار ══
   الأساسي ذهبي ممتلئ، والثانوي محدّد بإطار، والخفيف بلا لون —
   ثلاث درجات تكفي لتُعرف أهمية كل زر من شكله. */
QPushButton { background: @gold; color: #FFFFFF; border: none;
              border-radius: 8px; padding: 9px 18px; font-weight: bold; }
QPushButton:hover { background: @goldHi; }
QPushButton:pressed { background: @goldDim; }
QPushButton:disabled { background: @disBg; color: @disFg; }
QPushButton:focus { border: 2px solid @goldRing; }
QPushButton#ghost { background: @surface; color: @ink;
                    border: 1px solid @line2; }
QPushButton#ghost:hover { background: @hover; border-color: @line3; }
QPushButton#danger, QPushButton#dangerBtn { background: @red; }
QPushButton#danger:hover, QPushButton#dangerBtn:hover { background: @redHi; }
QToolButton { background: @surface; color: @ink; border: 1px solid @line2;
              border-radius: 8px; padding: 7px 12px; font-weight: bold; }
QToolButton:hover { background: @hover; border-color: @line3; }
QToolButton::menu-indicator { width: 0; }
/* أزرار الصف داخل الجداول: تعديلٌ وحذفٌ لكل سطرٍ في عموده الأول.
   حشوٌ ضيّق ليسعها ارتفاع الصف، والحذف بلون التحذير فلا يُخلط. */
QToolButton#rowAct, QToolButton#rowDel { padding: 1px 7px; min-width: 20px;
  border-radius: 6px; font-size: 11pt; font-weight: bold; }
QToolButton#rowAct:hover { background: @goldSoft; border-color: @gold; }
QToolButton#rowDel { color: @redText; border-color: @redSoft; }
QToolButton#rowDel:hover { background: @red; color: #FFFFFF; }
QMenu { background: @surface; border: 1px solid @line2; border-radius: 8px;
        padding: 5px; }
QMenu::item { padding: 7px 24px 7px 14px; border-radius: 6px; }
QMenu::item:selected { background: @goldSoft; color: @ink; }
QMenu::separator { height: 1px; background: @line; margin: 4px 8px; }

/* ══ الحقول ══ */
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QDateEdit, QTextEdit {
  background: @surface; border: 1px solid @line2; border-radius: 8px;
  padding: 6px 9px; color: @ink; selection-background-color: @goldRing;
  selection-color: @ink2; }
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus,
QDateEdit:focus, QTextEdit:focus { border: 2px solid @goldBright;
  background: @focusBg; }
QLineEdit:disabled, QDoubleSpinBox:disabled, QComboBox:disabled,
QDateEdit:disabled { background: @disField; color: @disFg; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: @surface; border: 1px solid @line2;
  color: @ink; selection-background-color: @goldSoft; selection-color: @ink;
  outline: none; padding: 2px; }
QCheckBox { spacing: 7px; }
QCheckBox::indicator { width: 17px; height: 17px; border-radius: 4px;
  border: 1px solid @line3; background: @surface; }
QCheckBox::indicator:checked { background: @gold; border-color: @goldDim; }
QRadioButton::indicator { width: 16px; height: 16px; border-radius: 8px;
  border: 1px solid @line3; background: @surface; }
QRadioButton::indicator:checked { background: @gold; border-color: @goldDim; }

/* ══ الجداول ══
   الرأس فاتح لا أسود: الرأس الداكن يسحب العين إليه وهي يجب أن تكون
   على الأرقام. التمييز بالثقل والخط الفاصل يكفي. */
QTableWidget, QTreeWidget, QListWidget {
  background: @surface; alternate-background-color: @surface2;
  gridline-color: @grid; border: 1px solid @line; border-radius: 10px;
  color: @ink; selection-background-color: @goldSoft; selection-color: @ink;
  font-size: 12.5pt; }
QTableWidget::item { padding: 7px 8px; }
QTableWidget::item:hover { background: @hover; }
QHeaderView::section { background: @hdrBg; color: @hdrFg; padding: 9px 6px;
  font-size: 11pt; font-weight: bold; border: none;
  border-bottom: 2px solid @hdrLine; border-left: 1px solid @hdrLine2; }
QHeaderView::section:first { border-left: none; }
QHeaderView::section:hover { color: @goldDim; }

/* ══ التبويبات: خط سفلي بدل الحبّات الممتلئة ══ */
QTabWidget::pane { border: 1px solid @line; border-radius: 10px;
                   background: @surface; top: -1px; }
QTabBar::tab { background: transparent; padding: 9px 20px; margin: 0 2px;
  min-width: 96px;
  color: @muted; font-weight: bold; border-bottom: 3px solid transparent; }
QTabBar::tab:hover { color: @goldDim; }
QTabBar::tab:selected { color: @goldDim; border-bottom: 3px solid @gold; }

/* ══ أشرطة التمرير: رفيعة محايدة ══ */
QScrollBar:vertical { background: transparent; width: 11px; margin: 2px; }
QScrollBar::handle:vertical { background: @scroll; border-radius: 5px;
  min-height: 34px; }
QScrollBar::handle:vertical:hover { background: @scrollHi; }
QScrollBar:horizontal { background: transparent; height: 11px; margin: 2px; }
QScrollBar::handle:horizontal { background: @scroll; border-radius: 5px;
  min-width: 34px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QProgressBar { border: 1px solid @line; border-radius: 7px; height: 12px;
  background: @surface2; text-align: center; color: @ink; }
QProgressBar::chunk { background: @gold; border-radius: 6px; }

/* ══════════ الشريط الجانبي ══════════
   خلفية السطح وأسماء بارزة، وإطار ذهبي على الحافة. البطاقة
   المحدَّدة ذهبٌ هادئ لا متدرّج صارخ — التمييز بالوضوح لا باللمعان. */
QListWidget#sidebar, QTreeWidget#sidebar {
  background: @surface;
  color: @ink;
  border: none;
  border-left: 3px solid qlineargradient(x1:0, y1:0, x2:0, y2:1,
      stop:0 @goldPale, stop:0.5 @goldBright, stop:1 @goldPale);
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
  color: @ink;
  border: 1px solid transparent;
  background: @sideItem;
}
QTreeWidget#sidebar::item:hover, QListWidget#sidebar::item:hover {
  background: @goldSoft2;
  border: 1px solid @goldEdge;
}
QListWidget#sidebar::item:selected, QTreeWidget#sidebar::item:selected {
  background: @goldSel;
  border: 1px solid @goldEdge2;
  color: @ink2;
}
QTreeWidget#sidebar::branch { background: transparent; }

/* ══ الشريطان العلوي والفرعي ══ */
QFrame#header { background: @barBg; border-bottom: 2px solid @gold; }
QLabel#headerTitle { color: @barFg; font-size: 17px; font-weight: bold; }
QLabel#headerUser { color: @goldRing; font-size: 13px; font-weight: bold; }
QFrame#header QPushButton, QFrame#header QToolButton { background: @barBtn;
  color: @barFg; border: 1px solid @barEdge; border-radius: 7px;
  padding: 7px 12px; }
QFrame#header QPushButton:hover, QFrame#header QToolButton:hover {
  background: @barBtnHi; border-color: @gold; }
QFrame#header QPushButton#ghost { background: @barBtn; color: @barFg; }
QFrame#header QComboBox, QFrame#header QLineEdit {
  background: @surface; color: @ink; border: 1px solid @barEdge; }
QFrame#subbar { background: @surface; border-bottom: 1px solid @line; }
QLabel#crumb { font-size: 13pt; font-weight: bold; color: @ink; }
QPushButton#homeBtn { background: @gold; color: white; font-weight: bold;
  padding: 7px 16px; border-radius: 8px; font-size: 11.5pt; }
QPushButton#homeBtn:hover { background: @goldHi; }
QPushButton#closeBtn { background: @surface; color: @redText;
  font-weight: bold; padding: 7px 16px; border-radius: 8px;
  font-size: 11.5pt; border: 1px solid @redSoft; }
QPushButton#closeBtn:hover { background: @red; color: #FFFFFF; }

/* ══ لوحات لوحة التحكم ══ */
QPushButton#dashPanel {
  background: @surface; border: 1px solid @line; border-radius: 9px;
  padding: 7px 11px; font-size: 10pt; font-weight: bold; color: @hdrFg;
  text-align: center;
}
QPushButton#dashPanel:hover { background: @hover; border-color: @hdrLine; }
QPushButton#dashPanel:checked { background: @goldSel;
  border: 1px solid @goldEdge2; color: @ink; }
QPushButton#updateReady {
  background: @goldRing; border: 1px solid @goldEdge2; border-radius: 7px;
  color: #14100A; font-weight: bold; padding: 6px 12px;
}
QPushButton#updateReady:hover { background: @goldHi; }
QFrame#ratioBar { background: @surface; border: 1px solid @line;
  border-right: 4px solid @goldBright; border-radius: 8px; }
QFrame#ratioBar QLabel { font-size: 11pt; font-weight: bold; color: @hdrFg; }

/* ══ الشاشة الرئيسية والبطاقات ══ */
QWidget#welcomeRoot { background: @bg; }
QLabel#welcomeName { font-size: 23pt; font-weight: bold; color: @goldHi;
  padding-top: 14px; }
QLabel#welcomeSub { font-size: 12pt; color: @muted; }
QLabel#welcomeHint { font-size: 11.5pt; color: @disFg; }
QFrame#tile { background: @surface; border: 1px solid @line;
  border-radius: 12px; }
QFrame#tile:hover { border: 1px solid @goldBright; background: @focusBg; }
QLabel#tileIcon { font-size: 25pt; }
QLabel#tileTitle { font-size: 13pt; font-weight: bold; color: @ink; }
QLabel#tileSub { font-size: 10.5pt; color: @muted; }
QLabel#groupTitle { font-size: 12.5pt; font-weight: bold; color: @goldDim;
  padding-top: 6px; }

QFrame#card { background: @surface; border: 1px solid @line;
  border-radius: 10px; padding: 6px; }
QFrame#card:hover { border: 1px solid @goldBright; background: @focusBg; }
QLabel#cardTitle { color: @goldDim; font-size: 12.5px; font-weight: bold; }
QLabel#cardValue { color: @ink; font-size: 19px; font-weight: bold; }
QLabel#cardSub { color: @muted; font-size: 11.5px; }

/* ══ لوحة الخلاصة: الرصيد وحده ══
   بين ستّ لوحاتٍ متشابهة يضيع الرصيد — وهو الرقم الذي فُتحت الشاشة
   لأجله. فتُعطى لوحتاه نبرةً كهرمانيةً خافتة وحدّاً أوضح وخطاً
   أكبر: تُلتقط أولاً، وتبقى من العائلة نفسها فلا تبدو دخيلة. */
QFrame#cardSum { background: @sumBg; border: 1px solid @sumEdge;
  border-radius: 10px; padding: 6px; }
QFrame#cardSum:hover { border: 1px solid @goldBright; background: @sumBg2; }
QFrame#cardSum QLabel#cardTitle { color: @sumInk; }
QFrame#cardSum QLabel#cardValue { color: @sumInk; font-size: 21px; }
QFrame#cardSum QLabel#cardSub { color: @sumInk; }

/* ══ شاشة البداية الحيّة ══
   بطاقاتٌ تُقرأ لا تُزيَّن: الرقم كبير، وعنوانه فوقه صغير، وحالته
   لونٌ على حافته اليمنى — فالعين تلتقط الخلل قبل أن تقرأ. */
QFrame#homeBox { background: @surface; border: 1px solid @line;
  border-radius: 12px; }
QLabel#homeBoxTitle { font-size: 12.5pt; font-weight: bold; color: @goldDim;
  padding: 2px 2px 6px 2px; }
QFrame#kpi { background: @surface; border: 1px solid @line;
  border-right: 4px solid @goldBright; border-radius: 10px; }
QFrame#kpi:hover { border-color: @goldBright; background: @focusBg;
  border-right: 4px solid @goldBright; }
QFrame#kpiAlert { background: @surface; border: 1px solid @redSoft;
  border-right: 4px solid @red; border-radius: 10px; }
QFrame#kpiGood { background: @surface; border: 1px solid @line;
  border-right: 4px solid @green; border-radius: 10px; }
QLabel#kpiTitle { color: @muted; font-size: 11pt; font-weight: bold; }
QLabel#kpiValue { color: @ink; font-size: 19pt; font-weight: bold; }
QLabel#kpiSub { color: @muted; font-size: 10pt; }
QLabel#kpiBad { color: @redText; font-size: 10pt; font-weight: bold; }
QLabel#kpiGoodText { color: @green; font-size: 10pt; font-weight: bold; }
QPushButton#homeRow { background: transparent; border: none;
  border-bottom: 1px solid @grid; border-radius: 0; color: @ink;
  font-weight: normal; font-size: 11pt; padding: 8px 6px;
  text-align: right; }
QPushButton#homeRow:hover { background: @hover; color: @goldDim; }
QPushButton#homeRow:focus { border: 1px solid @goldBright; }

/* ══ شريط الأوامر (Ctrl+K) ══ */
QDialog#palette { background: @surface; border: 1px solid @goldEdge2;
  border-radius: 12px; }
QLineEdit#paletteInput { font-size: 15pt; padding: 10px 12px;
  border: none; border-bottom: 1px solid @line; border-radius: 0;
  background: @surface; }
QLineEdit#paletteInput:focus { border: none;
  border-bottom: 2px solid @goldBright; background: @surface; }
QListWidget#paletteList { border: none; background: @surface;
  font-size: 12pt; outline: none; }
QListWidget#paletteList::item { padding: 9px 10px; border-radius: 8px;
  margin: 1px 4px; }
QListWidget#paletteList::item:selected { background: @goldSoft;
  color: @ink; }
QLabel#paletteHint { color: @disFg; font-size: 10pt; padding: 6px 10px;
  border-top: 1px solid @line; }

/* ══ شريط سعر الذهب الحي ══ */
QFrame#goldBar {
  background: @surface;
  border: 1px solid @line;
  border-top: 3px solid @goldBright;
  border-radius: 10px;
  padding: 8px;
  margin: 4px 7px;
}
QLabel#goldBarTitle { color: @goldDim; font-size: 12px; font-weight: bold; }
QLabel#goldBarValue { color: @ink; font-size: 17px; font-weight: bold; }
QLabel#goldBarSub   { color: @hdrFg; font-size: 11px; }
QLabel#goldBarStamp { color: @disFg; font-size: 10px; }
QLabel#goldKarat {
  color: @ink; font-size: 13px; font-weight: bold;
  background: @goldSoft2; border: 1px solid @goldEdge;
  border-radius: 7px; padding: 5px 7px;
}

/* ══ لوحات تحليل المبيعات ══ */
QFrame#statPanel { background: @surface; border: 1px solid @line;
  border-radius: 12px; padding: 6px; }
QFrame#statPanel:hover { border: 1px solid @goldBright; }
QLabel#panelTitle { font-size: 11.5pt; font-weight: bold; color: @goldDim; }
QLabel#panelValue { font-size: 18pt; font-weight: bold; color: @ink; }
QLabel#panelSub { font-size: 9.5pt; color: @muted; }

/* ══ الحوارات ══ */
QDialog { background: @bg; }
QMessageBox { background: @surface; }
QMessageBox QLabel { font-size: 13px; }
"""

# نسخة جاهزة باللوحة الفاتحة — للتوافق مع أي مستدعٍ قديم يقرأ `QSS`
QSS = theme.build(TEMPLATE, theme.LIGHT, 1.0)


def apply(app):
    """يطبّق المظهر المحفوظ (فاتح/ليلي) بمقاس الخط المحفوظ."""
    return theme.apply(app)
