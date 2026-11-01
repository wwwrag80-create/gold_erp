# -*- coding: utf-8 -*-
"""الهوية البصرية: RTL كامل، خط واضح، ولوحة ذهبي معتّق.

**البنية هنا، واللون في `ui.theme`**: كل لون في هذا الملف اسمٌ رمزي
(`@ink` · `@surface` · `@gold`) يستبدله محرّك المظهر بقيمته من اللوحة
المختارة — فالوضع الفاتح والليلي بنيةٌ واحدة لا نسختان تتباعدان.
"""
from ui import theme

TEMPLATE = """
/* ══════════════════════════════════════════════════════════════════
   نظام تصميم جاديت (5.1)
   ------------------------------------------------------------------
   الألوان كما هي منذ سنة (`ui.theme`) — لم يُغيَّر لونٌ ولم يُضَف لون:
   كل عنصرٍ هنا بلونه الذي كان له. الذي تغيّر **البنية**: سلّم خطٍّ
   واحد ومسافاتٌ من مضاعفات 4 وزوايا وارتفاعاتٌ موحّدة (`ui.design`)
   بأسماء رمزية — `@fsTitle` · `@rCard` · `@sp_md` — فلا تبدو شاشةٌ
   وكأنها صُمّمت وحدها.

   الركائز:
   · الأسطح (@surface) على خلفية (@bg)، والحدود رفيعة بلون واحد —
     فالشاشة تُقرأ بالتباين لا بالخطوط الثقيلة.
   · الذهب لون **الفعل والعناوين** لا لون كل شيء.
   · الزوايا: 6 للحقول والأزرار · 10 للقوائم واللوحات · 12 للبطاقات والجداول.
   · حالة كل عنصر معلومة: عادي · تمرير · تركيز · معطّل — والتركيز
     يُرى دائماً (حلقة ذهبية) لأن الإدخال هنا بلوحة المفاتيح غالباً.
   ══════════════════════════════════════════════════════════════════ */

QWidget { background: @bg; color: @ink; font-size: @fsBody; }
QLabel { background: transparent; }
/* ══ سلّم العناوين ══ */
QLabel#title { font-size: 20px; font-weight: bold; color: @goldDim;
               padding: @sp_xs 2px 2px 2px; }
QLabel#big { font-size: @fsH2; font-weight: bold; color: @ink; }
QLabel#warn { font-size: 15px; font-weight: bold; color: @redText; }
QLabel#ok { font-size: 15px; font-weight: bold; color: @green; }
QToolTip { background: @tipBg; color: @tipFg; border: none;
           padding: 7px 10px; border-radius: @rSm; font-size: @fsLabel; }

/* ══ الحاويات: بطاقةٌ بعنوانٍ ذهبي ══
   هامشٌ علويٌّ يتّسع للعنوان، وحشوٌ داخلي من السلّم نفسه في كل شاشة. */
QGroupBox { border: 1px solid @line; border-radius: @rCard;
            margin-top: 20px; padding: 14px 12px 10px 12px;
            font-size: @fsH3; font-weight: bold; background: @surface; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top right;
                   right: 16px; padding: 0 @sp_sm; color: @goldDim;
                   background: transparent; }
/* حاويةٌ مدمجة (`dense`): حشوٌ أقلّ لتُترك المساحة لجدولٍ تحتها —
   الإطار والعنوان ولونهما كما هما (المبيعات 5.1.2). */
QGroupBox[dense="true"] { padding: 2px 4px 2px 4px; }

/* ══ الأزرار ══
   الأساسي ذهبي ممتلئ، والثانوي محدّد بإطار، والخفيف بلا لون —
   ثلاث درجات تكفي لتُعرف أهمية كل زر من شكله. */
QPushButton { background: @gold; color: #FFFFFF; border: none;
              border-radius: @rCtl; padding: 8px 18px; font-weight: bold;
              min-height: 20px; }
QPushButton:hover { background: @goldHi; }
QPushButton:pressed { background: @goldDim; }
QPushButton:disabled { background: @disBg; color: @disFg; }
QPushButton:focus { border: 2px solid @goldRing; }
QPushButton#ghost { background: @surface; color: @ink;
                    border: 1px solid @line2; }
QPushButton#ghost:hover { background: @hover; border-color: @line3; }
QPushButton#danger, QPushButton#dangerBtn { background: @red; }
QPushButton#danger:hover, QPushButton#dangerBtn:hover { background: @redHi; }
QPushButton[dense="true"] { padding: 0px 10px 1px 10px; min-height: 20px; }
QToolButton { background: @surface; color: @ink; border: 1px solid @line2;
              border-radius: @rCtl; padding: 7px 12px; font-weight: bold; }
QToolButton:hover { background: @hover; border-color: @line3; }
QToolButton:pressed { background: @goldSoft2; }
QToolButton::menu-indicator { width: 0; }
/* أزرار الصف داخل الجداول: تعديلٌ وحذفٌ لكل سطرٍ في عموده الأول.
   حشوٌ ضيّق ليسعها ارتفاع الصف، والحذف بلون التحذير فلا يُخلط. */
QToolButton#rowAct, QToolButton#rowDel { padding: 1px 7px; min-width: 20px;
  border-radius: @rSm; font-size: 11pt; font-weight: bold; }
QToolButton#rowAct:hover { background: @goldSoft; border-color: @gold; }
QToolButton#rowDel { color: @redText; border-color: @redSoft; }
QToolButton#rowDel:hover { background: @red; color: #FFFFFF; }
QMenu { background: @surface; border: 1px solid @line2;
        border-radius: 10px; padding: 6px; }
QMenu::item { padding: 8px 26px 8px 14px; border-radius: @rSm; }
QMenu::item:selected { background: @goldSoft; color: @ink; }
QMenu::item:disabled { color: @disFg; }
QMenu::separator { height: 1px; background: @line; margin: 5px 10px; }

/* ══ الحقول ══ ارتفاعٌ واحد (36) وحدٌّ رفيع، والتركيز حلقةٌ ذهبية */
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QDateEdit, QTextEdit,
QPlainTextEdit {
  background: @surface; border: 1px solid @line2; border-radius: @rCtl;
  padding: 6px 10px; color: @ink; selection-background-color: @goldRing;
  selection-color: @ink2; font-weight: 500; }
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QDateEdit {
  min-height: 22px; }
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus,
QDateEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
  border: 2px solid @goldBright; background: @focusBg; }
QLineEdit:disabled, QDoubleSpinBox:disabled, QComboBox:disabled,
QDateEdit:disabled, QSpinBox:disabled { background: @disField;
  color: @disFg; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: @surface; border: 1px solid @line2;
  color: @ink; selection-background-color: @goldSoft; selection-color: @ink;
  outline: none; padding: @sp_xs; border-radius: @rCtl; }
QCheckBox, QRadioButton { spacing: 8px; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 5px;
  border: 1px solid @line3; background: @surface; }
QCheckBox::indicator:hover { border-color: @goldEdge2; }
QCheckBox::indicator:checked { background: @gold; border-color: @goldDim; }
QRadioButton::indicator { width: 17px; height: 17px; border-radius: 9px;
  border: 1px solid @line3; background: @surface; }
QRadioButton::indicator:checked { background: @gold; border-color: @goldDim; }

/* ══ وزن الأرقام والأسماء (4.20) ══
   الجداول والخانات بوزن «شبه عريض» (SemiBold) لا العادي: كل رقمٍ واسمٍ
   بخطوطٍ أسمك فيُقرأ من بعيد. وقيمة 500 هنا — لا 600 — مقصودة: محلّل
   أنماط Qt يقسم الوزن على 8، فـ500 ← 62 = شبه عريض، و600 ← 75 = عريض. */

/* ══ الجداول ══
   الرأس فاتح لا أسود: الرأس الداكن يسحب العين إليه وهي يجب أن تكون
   على الأرقام. التمييز بالثقل والخط الفاصل يكفي. */
QTableWidget, QTreeWidget, QListWidget, QTableView#ledgerView {
  background: @surface; alternate-background-color: @surface2;
  gridline-color: @grid; border: 1px solid @line; border-radius: @rCard;
  color: @ink; selection-background-color: @goldSoft; selection-color: @ink;
  font-size: 13pt; font-weight: 500; }
QTableWidget::item, QTableView#ledgerView::item { padding: 8px 6px; }
QTableWidget::item:hover { background: @hover; }
/* الشجرة (دليل الحسابات): صفٌّ مريح كصفوف الجداول لا سطرٌ مضغوط */
QTreeView::item { padding: 7px 4px; }
/* ══ إطارٌ حديث (4.25) ══
   لا مستطيل تركيزٍ منقّط حول الخلية، ورأسٌ أعلى بخطٍّ أوضح، وزاوية
   الجدول بلون رأسه — فيبدو الجدول لوحةً واحدةً مؤطّرة لا شبكةً عارية. */
QTableView, QTreeView { outline: 0; }
QHeaderView { background: @hdrBg; border: none;
  border-top-left-radius: @rCard; border-top-right-radius: @rCard; }
QHeaderView::section { background: @hdrBg; color: @hdrFg; padding: 10px 10px;
  font-size: 12pt; font-weight: bold; border: none;
  border-bottom: 2px solid @hdrLine; border-left: 1px solid @hdrLine2; }
QHeaderView::section:first { border-left: none; }
QTableCornerButton::section { background: @hdrBg; border: none;
  border-bottom: 2px solid @hdrLine; }
QHeaderView::section:hover { color: @goldDim; }

/* ══ التبويبات: خط سفلي بدل الحبّات الممتلئة ══ */
QTabWidget::pane { border: 1px solid @line; border-radius: @rCard;
                   background: @surface; top: -1px; }
/* الخط العريض على الشريط نفسه لا على التبويب وحده: Qt يقيس عرض
   التبويب بخط الشريط ويرسمه بخط التبويب — فكان يُقصّ حرفٌ من العنوان
   الطويل («موذج التصريف»، «لقوائم الختامية») */
QTabBar { font-weight: bold; }
QTabBar::tab { background: transparent; padding: 10px 22px; margin: 0 2px;
  min-width: 96px;
  color: @muted; font-weight: bold; border-bottom: 3px solid transparent; }
QTabBar::tab:hover { color: @goldDim; }
QTabBar::tab:selected { color: @goldDim; border-bottom: 3px solid @gold; }

/* ══ أشرطة التمرير: رفيعة محايدة ══ */
QScrollBar:vertical { background: transparent; width: 11px; margin: 2px; }
QScrollBar::handle:vertical { background: @scroll; border-radius: 5px;
  min-height: 36px; }
QScrollBar::handle:vertical:hover { background: @scrollHi; }
QScrollBar:horizontal { background: transparent; height: 11px; margin: 2px; }
QScrollBar::handle:horizontal { background: @scroll; border-radius: 5px;
  min-width: 36px; }
QScrollBar::handle:horizontal:hover { background: @scrollHi; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QProgressBar { border: 1px solid @line; border-radius: 7px; height: 12px;
  background: @surface2; text-align: center; color: @ink; }
QProgressBar::chunk { background: @gold; border-radius: 6px; }

/* ══════════ الشريط الجانبي ══════════
   خلفية السطح وأسماء بارزة، وإطار ذهبي على الحافة. البطاقة
   المحدَّدة ذهبٌ هادئ لا متدرّج صارخ — التمييز بالوضوح لا باللمعان.
   (5.1) أيقونةٌ لكل بند، والمجموعات عناوينُ أقسامٍ أخفّ من بنودها،
   وكثافةٌ أعلى قليلاً فيُرى أكثر بلا تمرير. */
QListWidget#sidebar, QTreeWidget#sidebar {
  background: @surface;
  color: @ink;
  border: none;
  border-left: 3px solid qlineargradient(x1:0, y1:0, x2:0, y2:1,
      stop:0 @goldPale, stop:0.5 @goldBright, stop:1 @goldPale);
  border-radius: 0;
  font-size: 16px;
  font-weight: bold;
  outline: none;
  padding: @sp_sm 0;
}
QListWidget#sidebar::item, QTreeWidget#sidebar::item {
  padding: 9px 12px;
  margin: 2px 8px;
  border-radius: @rCtl;
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
QLabel#headerUser { color: @goldRing; font-size: 15px; font-weight: bold; }
QFrame#header QPushButton, QFrame#header QToolButton { background: @barBtn;
  color: @barFg; border: 1px solid @barEdge; border-radius: @rCtl;
  padding: 7px 13px; }
QFrame#header QPushButton:hover, QFrame#header QToolButton:hover {
  background: @barBtnHi; border-color: @gold; }
QFrame#header QPushButton#ghost { background: @barBtn; color: @barFg; }
QFrame#header QComboBox, QFrame#header QLineEdit {
  background: @surface; color: @ink; border: 1px solid @barEdge; }
/* ══ رأس الصفحة (5.1) ══
   مسار المستخدم داخل النظام (القسم ‹ الشاشة) صغيراً فوق عنوانها،
   والعنوان كبيرٌ عريض — فيُعرف المكان من نظرة. */
QFrame#subbar { background: @surface; border-bottom: 1px solid @line; }
QLabel#crumb { font-size: 19px; font-weight: bold; color: @ink; }
QLabel#pagePath { font-size: @fsCaption; font-weight: 500; color: @muted; }
QLabel#pageIcon { font-size: 20px; color: @goldDim; padding: 0 2px; }
QToolButton#navToggle { background: @surface; color: @goldDim;
  border: 1px solid @line2; border-radius: @rCtl; padding: 5px 10px;
  font-size: 15px; font-weight: bold; }
QToolButton#navToggle:hover { background: @goldSoft2; border-color: @goldEdge2; }
QToolButton#navToggle:checked { background: @goldSel; border-color: @goldEdge2; }
QPushButton#homeBtn { background: @gold; color: white; font-weight: bold;
  padding: 7px 16px; border-radius: @rCtl; font-size: 11.5pt; }
QPushButton#homeBtn:hover { background: @goldHi; }
QPushButton#closeBtn { background: @surface; color: @redText;
  font-weight: bold; padding: 7px 16px; border-radius: @rCtl;
  font-size: 11.5pt; border: 1px solid @redSoft; }
QPushButton#closeBtn:hover { background: @red; color: #FFFFFF; }

/* ══ لوحات لوحة التحكم ══ */
QPushButton#dashPanel {
  background: @surface; border: 1px solid @line; border-radius: 10px;
  padding: 8px 12px; font-size: 10pt; font-weight: bold; color: @hdrFg;
  text-align: center;
}
QPushButton#dashPanel:hover { background: @hover; border-color: @hdrLine; }
QPushButton#dashPanel:checked { background: @goldSel;
  border: 1px solid @goldEdge2; color: @ink; }
QPushButton#updateReady {
  background: @goldRing; border: 1px solid @goldEdge2; border-radius: @rCtl;
  color: #000000; font-weight: bold; padding: 6px 12px;
}
QPushButton#updateReady:hover { background: @goldHi; }
QFrame#ratioBar { background: @surface; border: 1px solid @line;
  border-right: 4px solid @goldBright; border-radius: 10px; }
QFrame#ratioBar QLabel { font-size: 11pt; font-weight: bold; color: @hdrFg; }

/* ══ الشاشة الرئيسية والبطاقات ══ */
QWidget#welcomeRoot { background: @bg; }
QLabel#welcomeName { font-size: 23pt; font-weight: bold; color: @goldHi;
  padding-top: 14px; }
QLabel#welcomeSub { font-size: 12pt; color: @muted; }
QLabel#welcomeHint { font-size: 11.5pt; color: @disFg; }
QFrame#tile { background: @surface; border: 1px solid @line;
  border-radius: @rCard; }
QFrame#tile:hover { border: 1px solid @goldBright; background: @focusBg; }
QLabel#tileIcon { font-size: 25pt; }
QLabel#tileTitle { font-size: 13pt; font-weight: bold; color: @ink; }
QLabel#tileSub { font-size: 10.5pt; color: @muted; }
QLabel#groupTitle { font-size: 12.5pt; font-weight: bold; color: @goldDim;
  padding-top: 6px; }

/* ══ بطاقات الأرقام: عنوانٌ صغير ثم الرقم كبيراً ثم وحدته ══ */
QFrame#card { background: @surface; border: 1px solid @line;
  border-radius: @rCard; padding: 8px; }
QFrame#card:hover { border: 1px solid @goldBright; background: @focusBg; }
QLabel#cardTitle { color: @goldDim; font-size: 15px; font-weight: bold; }
QLabel#cardValue { color: @ink; font-size: 25px; font-weight: bold; }
QLabel#cardSub { color: @muted; font-size: 14px; }

/* ══ لوحة الخلاصة: الرصيد وحده ══
   بين ستّ لوحاتٍ متشابهة يضيع الرصيد — وهو الرقم الذي فُتحت الشاشة
   لأجله. فتُعطى لوحتاه نبرةً كهرمانيةً خافتة وحدّاً أوضح وخطاً
   أكبر: تُلتقط أولاً، وتبقى من العائلة نفسها فلا تبدو دخيلة. */
QFrame#cardSum { background: @sumBg; border: 1px solid @sumEdge;
  border-radius: @rCard; padding: 8px; }
QFrame#cardSum:hover { border: 1px solid @goldBright; background: @sumBg2; }
QFrame#cardSum QLabel#cardTitle { color: @sumInk; }
QFrame#cardSum QLabel#cardValue { color: @sumInk; font-size: 27px; }
QFrame#cardSum QLabel#cardSub { color: @sumInk; }

/* ══ لوحة إجماليٍّ مدمجة (chip) ══
   تحت جداول الإدخال: العنوان والرقم في سطرٍ واحد، فيأخذ الجدول
   المساحة كلّها ولا تحتاج الشاشة إلى تمرير. */
QFrame#chip { background: @surface; border: 1px solid @line;
  border-radius: 10px; }
QFrame#chipSum { background: @sumBg; border: 1px solid @sumEdge;
  border-radius: 10px; }
QLabel#chipTitle { color: @goldDim; font-size: 14px; font-weight: bold; }
QLabel#chipValue { color: @ink; font-size: 20px; font-weight: bold; }
QLabel#chipSub { color: @muted; font-size: 13px; }
QFrame#chipSum QLabel#chipTitle, QFrame#chipSum QLabel#chipValue,
QFrame#chipSum QLabel#chipSub { color: @sumInk; }

/* ══ شاشة البداية الحيّة ══
   بطاقاتٌ تُقرأ لا تُزيَّن: الرقم كبير، وعنوانه فوقه صغير، وحالته
   لونٌ على حافته اليمنى — فالعين تلتقط الخلل قبل أن تقرأ. */
QFrame#homeBox { background: @surface; border: 1px solid @line;
  border-radius: @rCard; }
QLabel#homeBoxTitle { font-size: 12.5pt; font-weight: bold; color: @goldDim;
  padding: 2px 2px 6px 2px; }
QFrame#kpi { background: @surface; border: 1px solid @line;
  border-right: 4px solid @goldBright; border-radius: @rCard; }
QFrame#kpi:hover { border-color: @goldBright; background: @focusBg;
  border-right: 4px solid @goldBright; }
QFrame#kpiAlert { background: @surface; border: 1px solid @redSoft;
  border-right: 4px solid @red; border-radius: @rCard; }
QFrame#kpiGood { background: @surface; border: 1px solid @line;
  border-right: 4px solid @green; border-radius: @rCard; }
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
  border-radius: @rDlg; }
QLineEdit#paletteInput { font-size: 15pt; padding: 12px 14px;
  border: none; border-bottom: 1px solid @line; border-radius: 0;
  background: @surface; }
QLineEdit#paletteInput:focus { border: none;
  border-bottom: 2px solid @goldBright; background: @surface; }
QListWidget#paletteList { border: none; background: @surface;
  font-size: 12pt; outline: none; }
QListWidget#paletteList::item { padding: 9px 12px; border-radius: @rCtl;
  margin: 1px 6px; }
QListWidget#paletteList::item:selected { background: @goldSoft;
  color: @ink; }
QLabel#paletteHint { color: @disFg; font-size: 10pt; padding: 7px 12px;
  border-top: 1px solid @line; }

/* ══ شريط سعر الذهب الحي ══ */
QFrame#goldBar {
  background: @surface;
  border: 1px solid @line;
  border-top: 3px solid @goldBright;
  border-radius: @rCard;
  padding: 8px;
  margin: 4px 8px;
}
QLabel#goldBarTitle { color: @goldDim; font-size: 14px; font-weight: bold; }
QLabel#goldBarValue { color: @ink; font-size: 19px; font-weight: bold; }
QLabel#goldBarSub   { color: @hdrFg; font-size: 15px; font-weight: bold; }
QLabel#goldBarStamp { color: @disFg; font-size: 13px; }
QLabel#goldKarat {
  color: @ink; font-size: 16px; font-weight: bold;
  background: @goldSoft2; border: 1px solid @goldEdge;
  border-radius: 7px; padding: 5px 7px;
}

/* ══ شريط السعر الأفقي (أعلى النافذة) ══ */
QFrame#goldStrip { background: @goldSoft2; border: 1px solid @goldEdge;
  border-radius: 10px; }
QLabel#goldStripTitle { color: @goldDim; font-size: 14px; font-weight: bold; }
QLabel#goldStripOunce { color: @ink; font-size: 15px; font-weight: bold;
  padding: 0 4px; }
QLabel#goldPill { color: @ink; font-size: 14px; font-weight: bold;
  background: @surface; border: 1px solid @goldEdge; border-radius: 7px;
  padding: 2px 8px; }
QToolButton#goldStripBtn { color: @goldDim; font-size: 16px;
  font-weight: bold; padding: 0 4px; }

/* ══ لوحات تحليل المبيعات ══ */
QFrame#statPanel { background: @surface; border: 1px solid @line;
  border-radius: @rCard; padding: 8px; }
QFrame#statPanel:hover { border: 1px solid @goldBright; }
QLabel#panelTitle { font-size: 11.5pt; font-weight: bold; color: @goldDim; }
QLabel#panelValue { font-size: 18pt; font-weight: bold; color: @ink; }
QLabel#panelSub { font-size: 9.5pt; color: @muted; }

/* ══ الحوارات ══ */
QDialog { background: @bg; }
QMessageBox { background: @surface; }
QMessageBox QLabel { font-size: 15px; }
QDialogButtonBox QPushButton { min-width: 96px; }

/* ══════════════════════════════════════════════════════════════════
   الطبقة الحديثة
   ------------------------------------------------------------------
   · الزر الأساسي تدرّجٌ ذهبيٌّ خفيف (أفتح أعلاه) بدل لونٍ مسطّح —
     يُقرأ زرّاً قابلاً للضغط من أول نظرة، ويغمق عند الضغط.
   · الصف المحدَّد في أي جدول ذهبٌ واضح وخطٌّ أغمق، فلا يضيع السطر
     الذي يعمل عليه المستخدم بين أسطرٍ متشابهة.
   · شريط الحالة وبحث الجدول والإشعار المنبثق بلغة الأسطح نفسها.
   ══════════════════════════════════════════════════════════════════ */
QPushButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
    stop:0 @goldHi, stop:1 @gold); }
QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
    stop:0 @goldBright, stop:1 @goldHi); }
QPushButton:pressed { background: @goldDim; }
QPushButton:disabled { background: @disBg; color: @disFg; }
QPushButton#ghost, QPushButton#ghost:hover { background: @surface; }
QPushButton#ghost:hover { background: @hover; }
QPushButton#danger, QPushButton#dangerBtn { background: @red; }
QPushButton#danger:hover, QPushButton#dangerBtn:hover { background: @redHi; }
QPushButton#closeBtn { background: @surface; }
QPushButton#closeBtn:hover { background: @red; }
QPushButton#dashPanel { background: @surface; }
QPushButton#dashPanel:hover { background: @hover; }
QPushButton#dashPanel:checked { background: @goldSel; }
QPushButton#homeRow, QPushButton#homeRow:hover { background: transparent; }
QPushButton#homeRow:hover { background: @hover; }
QFrame#header QPushButton, QFrame#header QPushButton#ghost {
    background: @barBtn; }
QFrame#header QPushButton:hover { background: @barBtnHi; }

QTableWidget::item:selected, QTreeWidget::item:selected,
QListWidget::item:selected, QTableView#ledgerView::item:selected {
  background: @goldSel; color: @ink2; }
QTableWidget:focus, QTreeWidget:focus { border: 1px solid @goldEdge; }
QHeaderView::section:hover { background: @goldSoft2; }
QLineEdit:hover, QDoubleSpinBox:hover, QSpinBox:hover, QComboBox:hover,
QDateEdit:hover { border-color: @line3; }

/* شريط الحالة */
QStatusBar#statusbar { background: @surface; border-top: 1px solid @line; }
QStatusBar#statusbar::item { border: none; }
QLabel#statusItem { color: @hdrFg; font-size: 11.5pt; padding: 5px 14px;
  border-left: 1px solid @line; }
QLabel#statusHint { color: @muted; font-size: 11pt; padding: 5px 14px; }

/* بحثٌ فوريّ داخل الجدول (Ctrl+F) */
QFrame#tableSearch { background: @surface; border: 1px solid @goldEdge2;
  border-radius: @rCard; }
QLineEdit#tableSearchInput { font-size: 12pt; padding: 6px 9px; }
QLabel#tableSearchCount { color: @goldDim; font-weight: bold;
  font-size: 11pt; padding: 0 4px; }

/* الإشعار المنبثق */
QLabel#toast { background: @tipBg; color: @tipFg; font-size: 12pt;
  font-weight: bold; border-radius: @rCard; padding: 9px 20px;
  border: 1px solid @goldEdge2; }

/* حالة الربط مع الهيئة في شريط الحالة — رابطٌ لا زرّ */
QPushButton#statusLink { background: transparent; border: none;
  padding: 5px 14px; font-size: 11.5pt; }
QPushButton#statusLink:hover { background: @hover; }

/* «ⓘ» شرح الشاشة المطويّ — وبطاقته العائمة */
QToolButton#notesBtn { color: @goldDim; font-size: 15pt; font-weight: bold;
  border: 1px solid transparent; border-radius: 14px; padding: 0 6px;
  background: transparent; }
QToolButton#notesBtn:hover { background: @goldSoft2; border-color: @goldEdge2; }
QFrame#notesPop { background: @surface; border: 1px solid @goldEdge2;
  border-radius: @rCard; }
QLabel#notesPopTitle { color: @goldDim; font-size: 13pt; font-weight: bold; }
QLabel#notesPopText { color: @ink; font-size: 12pt; }
"""

# نسخة جاهزة باللوحة الفاتحة — للتوافق مع أي مستدعٍ قديم يقرأ `QSS`
QSS = theme.build(TEMPLATE, theme.LIGHT, 1.0)


def apply(app):
    """يطبّق المظهر المحفوظ (فاتح/ليلي) بمقاس الخط المحفوظ."""
    return theme.apply(app)
