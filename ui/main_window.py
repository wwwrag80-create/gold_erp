# -*- coding: utf-8 -*-
"""لوحة التحكم: شريط جانبي RTL + شاشة لكل عملية حسب صلاحية المستخدم.
تبدأ بلوحة تحكم تفاعلية (بطاقات قابلة للنقر) تتيح Drill-down إلى دفتر
الأستاذ العام الموحّد لأي حساب في الشجرة."""
import json

from PyQt5 import QtCore, QtGui, QtWidgets

from pathlib import Path

import config
from ui.widgets.lazy_screen import LazyScreen as Lazy
from services import tenant
from database.database import db
from services import auth, backup
from services.audit import log_action
from ui.coa_screen import CoaScreen
from ui.document_archive_screen import DocumentArchiveScreen
from ui.welcome_screen import WelcomeScreen
from ui.widgets.gold_price import GoldPriceBar
from ui.dashboard_screen import DashboardScreen
from ui.entities_screen import EntitiesScreen
from ui.fixing_screen import FixingScreen
from ui.general_ledger_screen import GeneralLedgerScreen
from ui.journal_screen import JournalScreen
from ui.opening_balances_screen import OpeningBalancesScreen
from ui.mfg_costs_screen import MfgCostsScreen
from ui.operations_screen import OperationsScreen
from ui.super_admin_screen import SuperAdminScreen
from ui.opening_stock_screen import OpeningStockScreen
from ui.production_screen import ProductionScreen
from ui.purchases_screen import PurchasesScreen
from ui.reports.financial_statements_screen import FinancialStatementsScreen
from ui.reports.factory_reports_screen import FactoryReportsScreen
from ui.reports.khazina_report_screen import KhazinaReportScreen
from ui.reports.vat_return_screen import VatReturnScreen
from ui.reports.year_end_screen import YearEndScreen
from ui.reports.bank_recon_screen import BankReconScreen
from ui.reports.analysis_hub_screen import AnalysisHubScreen
from ui.reports.doc_edits_screen import DocEditsScreen
from ui.reports.day_close_screen import DayCloseScreen
from ui.reports.diagnostics_screen import DiagnosticsScreen
from ui.reports.integrity_screen import IntegrityScreen
from ui.item_history_screen import ItemHistoryScreen
from ui.models_screen import ModelsScreen
from ui.sales_analytics_screen import SalesAnalyticsScreen
from ui.sales_screen import SalesScreen
from ui.tax_sales_screen import TaxSalesScreen
from ui.workshop_accounts_screen import WorkshopAccountsScreen
from ui.workshop_losses_screen import WorkshopLossesScreen
from ui.stocktake_screen import StocktakeScreen
from ui.subledger_screen import SubLedgerScreen
from ui.transaction_log_screen import TransactionLogScreen
from ui.vouchers_screen import VouchersScreen
from ui.customers_screen import CustomersScreen
from services import karat_view as kv
from ui import theme
from ui.widgets.common import (ElidedLabel, ask, busy, err, info, run_bg,
                               save_pref, search_combo, warn)

# دور مخصّص يحمل المفتاح الثابت لكل عنصر في القائمة
NAV_KEY_ROLE = QtCore.Qt.UserRole + 1

# ══ إصدار ترتيب القائمة ══
# الترتيب المحفوظ على جهاز المستخدم يُطابَق بمفتاح كل شاشة (اسمها
# الافتراضي). فحين يتغيّر الترتيب المعتمد نفسه — أو تُعاد تسمية شاشات
# — يصير المحفوظ ترتيباً قديماً يحجب الجديد: الشاشات المعاد تسميتها
# تُلحق في ذيل القائمة بأسمائها الجديدة، ويبقى الترتيب القديم فوقها.
# رفع هذا الرقم يُهمل المحفوظ مرةً واحدة فيظهر الترتيب الجديد كما هو،
# ثم يُحفظ تخصيص المستخدم فوقه من جديد.
NAV_VERSION = 13      # 4.46: «التحليل والدراسات» إلى القائمة الرئيسية

# ══ شاشاتٌ أُعيدت تسميتها — بلا إهمال ترتيب المستخدم ══
# المفتاح القديم يُطابَق بالجديد، والاسم القديم المعروض يُستبدل —
# فتبقى الشاشة في موضعها الذي رتّبه صاحب النظام.
NAV_RENAMES = {
    "تكاليف ورواتب قسم التصنيع": "رواتب العمال والإدارة",
}


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.gl_screen = None
        # صلاحية الحساب السحابي: super_admin يرى كل شيء، و factory
        # يرى نظامه المحاسبي وحده بلا أي شاشة إدارية.
        self.is_super = bool(user.get("is_super")
                             or user.get("role") == "super_admin")
        self.setWindowTitle(self._app_title())
        try:
            from services import app_icon
            app_icon.apply(window=self)
        except Exception:
            pass

        if user.get("role_local", "accountant") == "accountant":
            self.mfg_screen = Lazy(lambda: MfgCostsScreen(user), "mfg_screen")
            self.sales_screen = Lazy(lambda: SalesScreen(user), "sales_screen")
            self.gl_screen = Lazy(lambda: GeneralLedgerScreen(
                user, on_edit_doc=self.open_document_for_edit), "gl_screen")
            self.analytics_screen = Lazy(lambda: SalesAnalyticsScreen(user), "analytics_screen")
            self.subledger_screen = Lazy(lambda: SubLedgerScreen(
                user, on_drill_account=self.open_ledger_by_account), "subledger_screen")
            self.dashboard_screen = Lazy(lambda: DashboardScreen(
                user, on_drill_code=self.open_ledger,
                on_open_subledger=self.open_subledger), "dashboard_screen")
            dashboard = self.dashboard_screen
            self.coa_screen = Lazy(lambda: CoaScreen(user, on_open_ledger=self.open_ledger), "coa_screen")
            self.entities_screen = Lazy(lambda: EntitiesScreen(user), "entities_screen")
            self.opening_screen = Lazy(lambda: OpeningStockScreen(user), "opening_screen")
            self.production_screen = Lazy(lambda: ProductionScreen(user), "production_screen")
            self.vouchers_screen = Lazy(lambda: VouchersScreen(user), "vouchers_screen")
            self.stocktake_screen = Lazy(lambda: StocktakeScreen(user), "stocktake_screen")
            self.fixing_screen = Lazy(lambda: FixingScreen(user), "fixing_screen")
            self.purchases_screen = Lazy(lambda: PurchasesScreen(user), "purchases_screen")
            self.tax_sales_screen = Lazy(lambda: TaxSalesScreen(user),
                                         "tax_sales_screen")
            self.journal_screen = Lazy(lambda: JournalScreen(user), "journal_screen")
            self.txlog_screen = Lazy(lambda: TransactionLogScreen(user), "txlog_screen")
            self.archive_screen = Lazy(lambda: DocumentArchiveScreen(
                user, on_open_ledger=self.open_ledger), "archive_screen")

            # ══════════════════════════════════════════════════════
            #  ترتيب القائمة — ثلاث عشرة شاشة يومية ظاهرة، وما عداها
            #  تحت «الإدارة والتقارير» يُفتح بالسهم.
            # ------------------------------------------------------
            #  الترتيب هنا هو ترتيب العمل نفسه: تُفتح لوحة التحكم،
            #  يُراجَع الموديل وحركة طقمه، يُقرأ كشف الحساب، ثم دورة
            #  اليوم — وارد ← بيع ← قبض ← تسكير ← شراء ← قيد، ثم
            #  تقارير المصنع وأعمار الديون في آخر الدوام. وما يُفتح
            #  مرة في الشهر لا يزاحم ما يُفتح كل ساعة.
            # ══════════════════════════════════════════════════════
            groups = [
                (None, [
                    ("لوحة التحكم", dashboard),
                    ("دليل الموديلات", Lazy(lambda: ModelsScreen(user), "دليل الموديلات")),
                    ("حركة الطقم", Lazy(lambda: ItemHistoryScreen(user), "حركة الطقم")),
                    ("كشف حساب", self.gl_screen),
                    ("الوارد من التصنيع", self.production_screen),
                    ("مبيعات/مرتجعات", self.sales_screen),
                    # فواتير ضريبية بالريال — لا ذهب ولا مخزون
                    ("المبيعات الضريبية", self.tax_sales_screen),
                    ("سندات قبض/صرف", self.vouchers_screen),
                    # من يسدّد ومن يتأخّر — بعد البيع والقبض مباشرةً
                    ("العملاء — المبيعات والسداد", Lazy(
                        lambda: CustomersScreen(
                            user,
                            on_drill_account=self.open_ledger_by_account),
                        "العملاء — المبيعات والسداد")),
                    ("التسكيرات", self.fixing_screen),
                    ("المشتريات", self.purchases_screen),
                    ("القيود اليومية", self.journal_screen),
                    ("تقارير مبيعات وإنتاج المصنع", Lazy(lambda: FactoryReportsScreen(user), "تقارير مبيعات وإنتاج المصنع")),
                    # ══ التحليل والدراسات في القائمة الرئيسية (4.46) ══
                    # حركةُ الرصيد وأعمارُ الموديلات وربحيةُ الموديل
                    # أقسامٌ في شاشةٍ واحدة — تُفتح كل يوم لا كل شهر،
                    # فمكانها مع شاشات العمل لا تحت «الإدارة والتقارير».
                    ("التحليل والدراسات",
                     Lazy(lambda: AnalysisHubScreen(user),
                          "التحليل والدراسات")),
                ]),
                ("الإدارة والتقارير", [
                    ("الإغلاق اليومي", Lazy(lambda: DayCloseScreen(user),
                                            "الإغلاق اليومي")),
                    ("دليل الحسابات (شجرة الحسابات)", self.coa_screen),
                    ("التكويد الموحّد لجهات التعامل", self.entities_screen),
                    ("أرصدة الأستاذ المساعد", self.subledger_screen),
                    ("الأرصدة الافتتاحية المخزنية", self.opening_screen),
                    ("تسوية فواقد الورشة", Lazy(lambda: WorkshopLossesScreen(user), "تسوية فواقد الورشة")),
                    ("حسابات الورشة", Lazy(lambda: WorkshopAccountsScreen(user), "حسابات الورشة")),
                    ("الجرد الفعلي", self.stocktake_screen),
                    ("إدارة وتحويل العمليات", Lazy(lambda: OperationsScreen(user), "إدارة وتحويل العمليات")),
                    ("سجل العمليات", self.txlog_screen),
                    ("سلامة السجل (بصمة القيود)",
                     Lazy(lambda: IntegrityScreen(user),
                          "سلامة السجل (بصمة القيود)")),
                    ("صحة النظام",
                     Lazy(lambda: DiagnosticsScreen(user), "صحة النظام")),
                    # مطابقة الدفتر بكشف المصرف — كانت تُعمل بورقةٍ
                    # وقلمٍ خارج النظام، والورقة لا تُدقَّق ولا تُؤرشَف
                    ("مطابقة كشف البنك",
                     Lazy(lambda: BankReconScreen(user), "مطابقة كشف البنك")),
                    ("أرشيف المستندات والطباعة", self.archive_screen),
                    # التعديل مشروع؛ المقصود أن يكون مرئياً —
                    # فتعديلٌ يُرى يُسأل عنه، ولا يُرى لا يُسأل
                    ("من عدّل ماذا بعد الترحيل",
                     Lazy(lambda: DocEditsScreen(user),
                          "من عدّل ماذا بعد الترحيل")),
                    # الأصول الثابتة والإهلاك صارت تبويباً في شاشة
                    # المشتريات: الأصل يُشترى هناك، فإهلاكُه بجانبه
                    # 4.54: شاشة «إنزال رواتب الموظفين» أُلغيت — كل
                    # موظفٍ عاملاً أو إدارياً تُنزَل رواتبه من هنا
                    ("رواتب العمال والإدارة", self.mfg_screen),
                    ("الإقرار الضريبي (VAT)", Lazy(lambda: VatReturnScreen(user), "الإقرار الضريبي (VAT)")),
                    # ══ القوائم المالية في بندٍ واحد (4.37) ══
                    # ميزان المراجعة والقوائم الأربع وتسويات نهاية
                    # الفترة كانت ستة بنودٍ متفرّقة — صارت تبويباتٍ
                    # بترتيبها المحاسبي في شاشةٍ واحدة يسهل الوصول إليها.
                    ("القوائم المالية",
                     Lazy(lambda: FinancialStatementsScreen(user),
                          "القوائم المالية")),
                    ("تحليل مبيعات العملاء", self.analytics_screen),
                    ("إنتاج خزينة التصنيع (مطابقة)",
                     Lazy(lambda: KhazinaReportScreen(user),
                          "إنتاج خزينة التصنيع (مطابقة)")),
                    ("تهيئة أرصدة أول المدة (تاريخ القطع)", Lazy(lambda: OpeningBalancesScreen(user), "تهيئة أرصدة أول المدة (تاريخ القطع)")),
                    ("الإقفال السنوي", Lazy(lambda: YearEndScreen(user), "الإقفال السنوي")),
                ]),
            ]

            # سجل التعديل الشامل: لكل نوع مستند شاشتُه ودالة التحميل
            self.edit_targets = {
                "invoices": (self.sales_screen, "load_invoice"),
                "vouchers": (self.vouchers_screen, "load_document"),
                "wo_supply": (self.production_screen, "load_document"),
                "wo_adjust": (self.dashboard_screen, "load_document"),
                "mfg_costs": (self.mfg_screen, "refresh"),
                "fixing_ops": (self.fixing_screen, "load_document"),
                "work_orders": (self.production_screen, "load_document"),
                "purchases": (self.purchases_screen, "load_document"),
                "manual": (self.journal_screen, "load_document"),
            }
        else:  # مبيعات فقط
            self.sales_screen = Lazy(lambda: SalesScreen(user), "sales_screen")
            self.edit_targets = {}
            groups = [(None, [("المبيعات والمرتجعات", self.sales_screen)])]

        # ══════════════ قيد الصلاحيات (RBAC) ══════════════
        # شاشات الإدارة العليا **لا تُبنى إطلاقاً** لحساب المصنع، فلا
        # يمكن الوصول إليها ولو بالتنقّل اليدوي أو تعديل ملف القائمة.
        if self.is_super:
            groups.append(("الإدارة العليا", [
                ("الحسابات وإيقاف المصانع",
                 Lazy(lambda: SuperAdminScreen(user),
                      "الحسابات وإيقاف المصانع")),
            ]))

        # ══════════════════════════════════════════════════════════
        #  الشريط العلوي
        # ----------------------------------------------------------
        #  ترتيب ثابت لا يتزاحم: الهوية والبحث يميناً، ثم فراغ مرن،
        #  ثم أدوات النظام يساراً. كل عنصر بعرض محدود فلا يدفع جاره
        #  ولا يتمدّد الشريط بطول اسمٍ في قائمة.
        # ══════════════════════════════════════════════════════════
        header = QtWidgets.QFrame()
        header.setObjectName("header")
        self._header_bar = header
        h = QtWidgets.QHBoxLayout(header)
        h.setContentsMargins(14, 8, 14, 8)
        h.setSpacing(10)

        # العنوان واسم المستخدم يُقصّان عند الضيق ولا يفرضان عرضاً
        t = ElidedLabel(self._app_title(), minimum=90)
        t.setObjectName("headerTitle")
        self._title_lbl = t

        # ── البحث السريع ──
        # السؤال الأكثر تكراراً في أي نظام محاسبي: «كم على فلان؟».
        # اسمٌ من أي مكان ← كشف حسابه مباشرةً.
        self.quick = search_combo("🔍 بحث باسم الجهة أو الحساب…")
        self.quick.setFixedWidth(200)
        self.quick.setMinimumWidth(200)
        self.quick.setSizePolicy(QtWidgets.QSizePolicy.Fixed,
                                 QtWidgets.QSizePolicy.Fixed)
        self.quick.setToolTip(
            "اكتب أول حروف الاسم ثم اختر — يفتح كشف الحساب مباشرةً")
        self.quick.activated.connect(self._quick_open)
        try:
            self.quick.lineEdit().returnPressed.connect(self._quick_open)
        except Exception:
            pass
        # القائمة تُملأ بعد اكتمال الإقلاع فلا تتأخّر النافذة
        QtCore.QTimer.singleShot(400, self._load_quick_index)
        # 4.52: رابط دليل الموديلات للمدير — إن كان مفعّلاً يعود مع البرنامج
        # (في خيطٍ خلفي: أوامر Tailscale قد تستغرق ثواني)
        QtCore.QTimer.singleShot(3000, self._start_models_link)

        # ── عيار المصنع ──
        # وحدة القراءة والكتابة في النظام كله. التخزين يبقى بمكافئ 18
        # مهما اختير — وهذا ما يجعل الأرصدة قابلة للجمع والمقارنة.
        lbl_karat = QtWidgets.QLabel("العيار:")
        lbl_karat.setObjectName("headerUser")
        self.karat_box = QtWidgets.QComboBox()
        self.karat_box.setObjectName("karatBox")
        self.karat_box.setFixedWidth(96)
        self.karat_box.setToolTip(
            "وحدة عرض وإدخال الأوزان في كل شاشات النظام.\n"
            "القيد يُخزَّن بمكافئ عيار 18 دائماً — لا تتغيّر البيانات.")
        for _k in kv.KARATS:
            self.karat_box.addItem(f"عيار {_k}", _k)
        _idx = self.karat_box.findData(kv.active())
        if _idx >= 0:
            self.karat_box.setCurrentIndex(_idx)
        self.karat_box.currentIndexChanged.connect(self._change_karat)

        u = ElidedLabel(self._user_label(), minimum=110)
        u.setObjectName("headerUser")
        self._hdr_user = u

        # ── الأدوات ──
        # نصوص قصيرة وشرحها في التلميح: الشريط أداةٌ لا صفحة شرح.
        # زر «عرض» يجمع ما كان مبعثراً: المظهر ومقاس الخط والبحث
        # الموحّد وإعادة ترتيب القائمة. الشريط أداةٌ لا لوحة أزرار،
        # وكل زرٍّ يُضاف إليه يُضيّق ما قبله.
        btn_view = self._view_menu_button()
        btn_update = QtWidgets.QPushButton("⬆ تحديث")
        btn_update.setToolTip(
            "تحقّق من التحديثات عبر الإنترنت، أو ثبّت حزمة محفوظة")
        btn_update.clicked.connect(self.do_update)
        self.btn_update = btn_update
        # «💾 نسخة»: الضغط ينسخ الآن، وسهمه يفتح النسخ والاسترجاع.
        # البيانات على الجهاز وحده (لا سحابة 4.29)، فالاسترجاع لكل
        # مستخدمٍ على جهازه لا للمدير وحده.
        btn_backup = QtWidgets.QToolButton()
        btn_backup.setText("💾 نسخة")
        btn_backup.setToolTip("نسخة احتياطية الآن — والسهم: آخر 20 نسخة "
                              "واسترجاع أيٍّ منها")
        btn_backup.setPopupMode(QtWidgets.QToolButton.MenuButtonPopup)
        btn_backup.clicked.connect(self.do_backup)
        m_bk = QtWidgets.QMenu(btn_backup)
        m_bk.addAction("💾 نسخة احتياطية الآن").triggered.connect(
            self.do_backup)
        m_bk.addAction("♻ النسخ الاحتياطية والاسترجاع…").triggered.connect(
            self.open_backups)
        btn_backup.setMenu(m_bk)
        self._backup_menu = m_bk
        # ══ لا فحص تحديثات صامت (4.29) ══
        # برنامج المصنع لا يتصل بالسحابة إلا ليسأل عن حالة حسابه.
        # التحديث عند الطلب من زر «⬆ تحديث» (أو حزمة محفوظة).
        for b in (btn_view, btn_update, btn_backup):
            b.setSizePolicy(QtWidgets.QSizePolicy.Fixed,
                            QtWidgets.QSizePolicy.Fixed)

        h.addWidget(t)
        h.addWidget(self.quick)
        h.addStretch(1)                  # الفراغ يفصل الهوية عن الأدوات
        h.addWidget(u)
        h.addSpacing(8)
        h.addWidget(lbl_karat)
        h.addWidget(self.karat_box)
        h.addSpacing(8)
        h.addWidget(btn_view)
        h.addWidget(btn_update)
        h.addWidget(btn_backup)

        # ── شريط الأوامر الموحّد ──
        # اختصارٌ واحد من أي شاشة، ومن أي حقل — فلا يحتاج المستخدم
        # إلى إغلاق ما هو فيه ليبحث عن شيء.
        for seq in ("Ctrl+K", "Ctrl+Space"):
            sc = QtWidgets.QShortcut(QtGui.QKeySequence(seq), self)
            sc.setContext(QtCore.Qt.ApplicationShortcut)
            sc.activated.connect(self.open_palette)
        # اختصاراتٌ حديثة موحّدة في كل الشاشات — قائمتها كاملةً بـF1
        for seq, fn in (("Ctrl+F", self.search_table),
                        ("F5", self.refresh_screen),
                        ("Ctrl+Shift+E", self.export_table),
                        ("F1", self.show_shortcuts)):
            sc = QtWidgets.QShortcut(QtGui.QKeySequence(seq), self)
            sc.setContext(QtCore.Qt.WindowShortcut)
            sc.activated.connect(fn)

        # الشريط الفرعي: عنوان الشاشة الحالية وزر إغلاقها. يُبنى قبل
        # الشريط الجانبي لأن switch() تستخدم self.crumb و self.btn_close.
        self.crumb = QtWidgets.QLabel(config.COMPANY_NAME)
        self.crumb.setObjectName("crumb")
        # «رجوع» لا «إغلاق» (4.54): يعود إلى الشاشة التي جاء منها كما
        # تركها — كشفُ الحساب بحسابه بعد تعديل فاتورةٍ منه — لا إلى
        # الرئيسية ثم دخولٍ من جديد. ومن شاشةٍ فُتحت من القائمة يعود
        # إلى الرئيسية.
        self._history = []
        self.btn_close = QtWidgets.QPushButton("→  رجوع")
        self.btn_close.setObjectName("closeBtn")
        self.btn_close.clicked.connect(self._close_screen)
        for _seq in ("Alt+Left", "Alt+Right"):
            _sc = QtWidgets.QShortcut(QtGui.QKeySequence(_seq), self)
            _sc.setContext(QtCore.Qt.WindowShortcut)
            _sc.activated.connect(self._back_shortcut)
        self.btn_close.setVisible(False)
        subbar = QtWidgets.QFrame()
        subbar.setObjectName("subbar")
        # الشريط الفرعي لا يفرض عرضاً على النافذة أبداً: ما زاد عن
        # عرضها يُضغط داخله بدل أن تتّسع النافذة خارج الشاشة
        subbar.setSizePolicy(QtWidgets.QSizePolicy.Ignored,
                             QtWidgets.QSizePolicy.Fixed)
        sb = QtWidgets.QHBoxLayout(subbar)
        sb.setContentsMargins(16, 6, 16, 6)
        sb.addWidget(self.crumb)
        # «ⓘ» — شرح الشاشة المطويّ، يظهر عند الطلب لا فوق الجدول
        self.btn_notes = QtWidgets.QToolButton()
        self.btn_notes.setObjectName("notesBtn")
        self.btn_notes.setText("ⓘ")
        self.btn_notes.setAutoRaise(True)
        self.btn_notes.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_notes.clicked.connect(self.show_screen_notes)
        self.btn_notes.setVisible(False)
        sb.addWidget(self.btn_notes)
        sb.addStretch(1)
        # مساحة أدوات تخصّ الشاشة الحالية: تضع كل شاشة أزرارها العامة
        # هنا بجوار «إغلاق الشاشة» بدل ازدحام مساحة العمل بها.
        self.screen_tools = QtWidgets.QWidget()
        self._tools_lay = QtWidgets.QHBoxLayout(self.screen_tools)
        self._tools_lay.setContentsMargins(0, 0, 0, 0)
        self._tools_lay.setSpacing(6)
        sb.addWidget(self.screen_tools)
        sb.addWidget(self.btn_close)
        # سعر الذهب: شريطٌ أفقي في أقصى يسار الشريط الفرعي — تحت أزرار
        # «عرض» و«تحديث» — لا لوحةً تأكل من طول الشريط الجانبي
        self.gold_bar = GoldPriceBar()
        sb.addSpacing(8)
        sb.addWidget(self.gold_bar)

        # شاشة الترحيب (الفهرس 0): مساحة يتوسّطها شعار المصنع. جُرّبت
        # مكانها شاشةُ أرقامٍ حيّة فلم تُرَد — والشعار أوضح وأسرع،
        # والأرقام لها شاشاتها (الإغلاق اليومي · لوحة التحكم).
        self.welcome = WelcomeScreen(user)

        # أبٌ منذ اللحظة الأولى: widget بلا أبٍ يصير **نافذةً مستقلة**
        # بمجرّد إظهاره، فيومض على الشاشة قبل أن يُضمّ إلى مكانه.
        self.sidebar = QtWidgets.QTreeWidget(self)
        # قائمة ديناميكية: سحب وإفلات لإعادة الترتيب والتجميع،
        # وإعادة تسمية بالنقر المزدوج — تُحفظ في ملف إعدادات محلي.
        self.sidebar.setDragDropMode(
            QtWidgets.QAbstractItemView.InternalMove)
        self.sidebar.setDefaultDropAction(QtCore.Qt.MoveAction)
        self.sidebar.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection)
        self.sidebar.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed)
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(260)
        self.sidebar.setHeaderHidden(True)
        self.sidebar.setIndentation(14)
        self.stack = QtWidgets.QStackedWidget()
        # اسمٌ يعرف به مرشّح فقرات الشرح أن الملصق داخل شاشة لا حوار
        self.stack.setObjectName("screenHost")
        self._current_row = 0
        self.screens = [self.welcome]     # Index 0 = شاشة الترحيب
        self.stack.addWidget(self.welcome)
        self._items = {}
        # مفتاح ثابت لكل شاشة = اسمها الافتراضي في القائمة. الفهرس
        # الرقمي يتغيّر مع كل إضافة شاشة، فحفظ الترتيب به يفتح شاشةً
        # غير المقصودة بعد أي تحديث. الاسم الافتراضي لا يتغيّر.
        self._screen_keys = {}
        for group_name, items in groups:
            parent = None
            if group_name:
                parent = QtWidgets.QTreeWidgetItem(self.sidebar, [group_name])
                parent.setData(0, QtCore.Qt.UserRole, -1)
                parent.setData(0, NAV_KEY_ROLE, f"::group::{group_name}")
                parent.setFlags(parent.flags() | QtCore.Qt.ItemIsEditable)
                f = parent.font(0)
                f.setBold(True)
                parent.setFont(0, f)
            for name, w in items:
                idx = len(self.screens)
                node = (QtWidgets.QTreeWidgetItem(parent, [name]) if parent
                        else QtWidgets.QTreeWidgetItem(self.sidebar, [name]))
                node.setData(0, QtCore.Qt.UserRole, idx)
                node.setData(0, NAV_KEY_ROLE, name)
                self._screen_keys[idx] = name
                node.setFlags(node.flags() | QtCore.Qt.ItemIsEditable)
                self.screens.append(w)
                self.stack.addWidget(self._scrollable(w))
                self._items[w] = node
            if parent:
                parent.setExpanded(False)
        self.sidebar.itemClicked.connect(self._nav_clicked)
        # الحفظ عند كل تغيير: إعادة تسمية · طيّ · **وسحب وإفلات**
        self.sidebar.itemChanged.connect(lambda *_: self._save_nav_layout())
        try:
            _m = self.sidebar.model()
            for _sig in ("rowsMoved", "rowsInserted", "rowsRemoved"):
                getattr(_m, _sig).connect(
                    lambda *_: self._schedule_nav_save())
        except Exception:
            pass          # بيئة بلا نموذج حقيقي
        self.sidebar.model().rowsMoved.connect(
            lambda *_: self._save_nav_layout())
        self._restore_nav_layout()
        self._items[self.welcome] = None
        self.switch(0)

        # الشريط الجانبي ثابت على اليمين دائماً (RTL يضعه يميناً)،
        # كاملاً إلى أسفل النافذة — شجرة التنقل وحدها.
        self.side_panel = QtWidgets.QWidget(self)
        self.side_panel.setFixedWidth(260)
        sp = QtWidgets.QVBoxLayout(self.side_panel)
        sp.setContentsMargins(0, 0, 0, 0)
        sp.setSpacing(0)
        sp.addWidget(self.sidebar, 1)
        # الحالة المحفوظة من `switch` أثناء التهيئة تُطبَّق الآن
        self.side_panel.setVisible(getattr(self, "_panel_visible", True))

        body = QtWidgets.QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.side_panel)
        body.addWidget(self.stack, 1)
        central = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(header)
        v.addWidget(subbar)
        v.addLayout(body, 1)
        self.setCentralWidget(central)
        self._build_status_bar()
        self._start_account_guard()

    # ══════════ دخولُ الواجهة ══════════
    def play_entrance(self):
        """حركةُ وصولٍ قصيرة بعد البوابة — لا زينةَ دائمة.

        القائمة الجانبية تنزلق من اليمين وشاشةُ الترحيب تصعد قليلاً
        وهي تظهر، في أقل من ثلثَي ثانية. **ثم تُرفع المؤثّرات
        كلُّها**: مؤثّرُ شفافيةٍ باقٍ على شجرةٍ أو جدول يُعيد رسمه في
        كل تمريرة تمرير، فيصير الجمالُ بطئاً — والحركة تُفتتح بها
        الجلسة لا تُلازمها.
        """
        try:
            from ui.widgets.gold_stage import animations_on
            if not animations_on():
                return
        except Exception:
            return
        self._entrance = []
        for w, dx, dy, delay, ms in ((self.side_panel, 34, 0, 0, 480),
                                     (self.stack, 0, 22, 110, 520)):
            eff = QtWidgets.QGraphicsOpacityEffect(w)
            eff.setOpacity(0.0)
            w.setGraphicsEffect(eff)
            base = w.pos()
            anim = QtCore.QVariantAnimation(self)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setDuration(ms)
            anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)

            def _step(v, _w=w, _e=eff, _b=base, _dx=dx, _dy=dy):
                f = float(v)
                _e.setOpacity(f)
                _w.move(_b.x() + int(_dx * (1 - f)),
                        _b.y() + int(_dy * (1 - f)))

            def _end(_w=w, _b=base):
                try:
                    _w.setGraphicsEffect(None)
                    _w.move(_b)
                except Exception:
                    pass

            anim.valueChanged.connect(_step)
            anim.finished.connect(_end)
            QtCore.QTimer.singleShot(delay, anim.start)
            self._entrance.append(anim)
        try:
            self.welcome.play_entrance()
        except Exception:
            pass

    # ══════════ تخصيص القائمة الجانبية ══════════
    def _nav_layout_path(self):
        """مسار ملف الترتيب — **داخل مجلد المصنع النشط**.

        كان يُحفظ في مجلد التطبيق الثابت، فيضيع عند تحديث النسخة أو
        يختلط بين المصانع. الآن بجوار قاعدة بيانات المصنع نفسه.
        """
        try:
            return Path(str(config.DB_PATH)).parent / "nav_layout.json"
        except Exception:
            return config.BASE_DIR / "data" / "nav_layout.json"

    def _iter_nav(self, parent=None):
        """يمرّ على كل عناصر الشجرة (الأب ثم أبناؤه)."""
        if parent is None:
            for i in range(self.sidebar.topLevelItemCount()):
                yield self.sidebar.topLevelItem(i), None
                yield from self._iter_nav(self.sidebar.topLevelItem(i))
        else:
            for i in range(parent.childCount()):
                yield parent.child(i), parent
                yield from self._iter_nav(parent.child(i))

    def _nav_node(self, item):
        return {
            "idx": item.data(0, QtCore.Qt.UserRole),
            "key": item.data(0, NAV_KEY_ROLE) or "",
            "text": item.text(0),
            "expanded": item.isExpanded(),
            "children": [self._nav_node(item.child(i))
                         for i in range(item.childCount())],
        }

    def _schedule_nav_save(self):
        """يؤجّل الحفظ قليلاً: السحب يُطلق عدة أحداث متتالية."""
        try:
            t = getattr(self, "_nav_save_timer", None)
            if t is None:
                t = QtCore.QTimer(self)
                t.setSingleShot(True)
                t.setInterval(250)
                t.timeout.connect(self._save_nav_layout)
                self._nav_save_timer = t
            t.start()
        except Exception:
            self._save_nav_layout()

    def _save_nav_layout(self):
        """يحفظ الترتيب والأسماء والتجميع في ملف JSON محلي."""
        if getattr(self, "_nav_loading", False):
            return
        try:
            data = {
                "version": NAV_VERSION,
                "nodes": [self._nav_node(self.sidebar.topLevelItem(i))
                          for i in range(self.sidebar.topLevelItemCount())],
            }
            path = self._nav_layout_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception:
            pass          # تخصيص الواجهة لا يعطّل النظام أبداً

    def _restore_nav_layout(self):
        """يعيد بناء الشجرة من ملف الإعدادات إن وُجد.

        **الخلل الذي عُولج هنا**: الملف كان يُطابَق بالفهرس الرقمي
        للشاشة. والفهرس ترتيبٌ لا هوية: إضافة شاشة واحدة في وسط
        القائمة تُزيح كل ما بعدها، فيصير البند المحفوظ يشير إلى جارته
        — «المبيعات» تفتح «التوريد»، وتتكرر بنود، وتختفي أخرى.

        العلاج: مفتاح ثابت لكل شاشة هو اسمها الافتراضي، يُحفظ مع
        البند ويُطابَق به أولاً. ثم الاسم المعروض (للملفات القديمة
        التي لا مفتاح فيها). **ولا يُطابَق بالفهرس إطلاقاً** — فهو
        أصل الخلل. البند الذي لا يُطابق يُسقَط، وشاشته تُلحق في
        نهاية القائمة باسمها الافتراضي، فتُصلح القائمة نفسها بنفسها
        عند أول فتح.
        """
        path = self._nav_layout_path()
        if not path.exists():
            return
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        # ترتيبٌ محفوظ بإصدارٍ أقدم: يُهمل مرةً واحدة ليظهر الترتيب
        # المعتمد الجديد كاملاً. وبدون ذلك تبقى الأسماء القديمة فوق
        # والشاشات المعاد تسميتها ملحقةً في الذيل.
        if not isinstance(saved, dict) or saved.get("version") != NAV_VERSION:
            try:
                path.unlink()
            except Exception:
                pass
            return
        saved = saved.get("nodes") or []
        if not saved:
            return
        # خريطة الفهرس ← نص افتراضي لكل عنصر حالي
        current = {}
        for item, _ in self._iter_nav():
            idx = item.data(0, QtCore.Qt.UserRole)
            if idx is not None and idx >= 0:
                current[idx] = item.text(0)
        if not current:
            return

        self._nav_loading = True
        try:
            used = set()
            keys = getattr(self, "_screen_keys", {})
            by_key = {k: i for i, k in keys.items()}
            by_text = {}
            for i, t in current.items():
                by_text.setdefault(t, i)

            def build(nodes, parent):
                for n in nodes:
                    idx = n.get("idx")
                    text = n.get("text", "")
                    key = n.get("key") or ""
                    key = NAV_RENAMES.get(key, key)
                    text = NAV_RENAMES.get(text, text)
                    if idx is not None and idx >= 0:
                        # المفتاح الثابت أولاً، ثم الاسم المعروض.
                        real = by_key.get(key)
                        if real is None or real in used:
                            real = by_text.get(text)
                        if real is None or real in used:
                            continue      # لا مطابقة — تُلحق لاحقاً
                        idx = real
                        used.add(idx)
                    it = QtWidgets.QTreeWidgetItem([text])
                    it.setData(0, QtCore.Qt.UserRole,
                               idx if idx is not None else -1)
                    it.setData(0, NAV_KEY_ROLE,
                               keys.get(idx, key) if idx is not None
                               and idx >= 0 else key)
                    it.setFlags(it.flags() | QtCore.Qt.ItemIsEditable)
                    if parent is None:
                        self.sidebar.addTopLevelItem(it)
                    else:
                        parent.addChild(it)
                    build(n.get("children", []), it)
                    it.setExpanded(bool(n.get("expanded", True)))

            self.sidebar.clear()
            build(saved, None)
            # أي شاشة لم تُطابق (جديدة أو ضاع بندها) تُلحق في النهاية
            # باسمها الافتراضي — فلا تختفي شاشة من القائمة أبداً.
            for idx, text in sorted(current.items()):
                if idx in used:
                    continue
                it = QtWidgets.QTreeWidgetItem([text])
                it.setData(0, QtCore.Qt.UserRole, idx)
                it.setData(0, NAV_KEY_ROLE, keys.get(idx, text))
                it.setFlags(it.flags() | QtCore.Qt.ItemIsEditable)
                self.sidebar.addTopLevelItem(it)
            # إعادة بناء خريطة العناصر
            self._items = {}
            for item, _ in self._iter_nav():
                idx = item.data(0, QtCore.Qt.UserRole)
                if idx is not None and 0 <= idx < len(self.screens):
                    self._items[self.screens[idx]] = item
        finally:
            self._nav_loading = False

    def reset_nav_layout(self):
        """يعيد القائمة لترتيبها الافتراضي (يُحذف ملف التخصيص)."""
        try:
            p = self._nav_layout_path()
            if p.exists():
                p.unlink()
            info(self, "أُعيدت القائمة لترتيبها الافتراضي.\n"
                       "أعد تشغيل النظام لتطبيق ذلك.")
        except Exception as e:
            err(self, e)

    def _nav_clicked(self, item, _col=0):
        idx = item.data(0, QtCore.Qt.UserRole)
        if idx is None or idx < 0:      # عنوان مجموعة — يفتح/يطوي فقط
            item.setExpanded(not item.isExpanded())
            return
        self.switch(idx)

    def _scrollable(self, widget):
        """يغلّف الشاشة بمنطقة تمرير عمودية حتى لا تُقصّ الأزرار السفلية
        (الترحيل/الحفظ) خارج حدود الشاشة على الدقّات المنخفضة."""
        area = QtWidgets.QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QtWidgets.QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        area.setWidget(widget)
        # ══ النافذة لا تتمدّد لتُرضي شاشةً عريضة ══
        # منطقة التمرير تُورّث أدنى عرضٍ تطلبه الشاشة داخلها، فشاشة
        # ذات جدول كثير الأعمدة كانت تدفع النافذة لتتّسع أفقياً —
        # فيضطر المستخدم لتصغيرها يدوياً بعد كل فتح. الحد الأدنى هنا
        # صغير صريح: الشاشة الأعرض تُمرَّر أفقياً داخل إطارها، والنافذة
        # تبقى بحجمها الذي اختاره المستخدم.
        area.setMinimumWidth(360)
        area.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                           QtWidgets.QSizePolicy.Expanding)
        return area

    # عدد الشاشات التي تبقى حيّةً خلف الحالية — حدٌّ صغير: «شاشة واحدة
    # حيّة» هي ما يمنع التجمّد، والرجوع يحتاج سلسلةً قصيرة لا القائمة كلها
    HISTORY_MAX = 4

    def _close_screen(self):
        """«رجوع»: إلى الشاشة السابقة كما تُركت، وإلا إلى الرئيسية."""
        hist = getattr(self, "_history", [])
        while hist:
            row = hist.pop()
            if 0 < row < len(self.screens) and row != self._current_row:
                self.switch(row, _back=True)
                return
        self.switch(0)

    def _back_shortcut(self):
        if getattr(self, "_current_row", 0) > 0:
            self._close_screen()

    def _release(self, row):
        """يُغلق شاشةً غادرها المستخدم نهائياً (لا شاشةً في سلسلة الرجوع)."""
        if row <= 0 or row in getattr(self, "_history", []):
            return
        try:
            rel = getattr(self.screens[row], "release", None)
            if callable(rel):
                rel()
        except Exception:
            pass

    def _release_old(self, row):
        if row != getattr(self, "_current_row", 0):
            self._release(row)

    def _update_back_btn(self):
        hist = getattr(self, "_history", [])
        prev = hist[-1] if hist else 0
        name = ""
        if prev > 0:
            node = self._items.get(self.screens[prev])
            name = node.text(0) if node is not None else ""
        if name:
            short = name if len(name) <= 22 else name[:21] + "…"
            self.btn_close.setText(f"→  رجوع: {short}")
            self.btn_close.setToolTip(f"العودة إلى «{name}» كما تركتها"
                                      "  (Alt+←)")
        else:
            self.btn_close.setText("→  رجوع")
            self.btn_close.setToolTip("العودة إلى الواجهة الرئيسية  (Alt+←)")

    def _guard_screen(self, row):
        """يحرس الشاشات الحسّاسة برمز دخول قبل فتحها."""
        try:
            name = ""
            it = self.sidebar.topLevelItem(0)
            scr = self.screens[row] if 0 <= row < len(self.screens) else None
            real = getattr(scr, "real", scr)
            cls = type(real).__name__ if real is not None else ""
            builder = getattr(scr, "_builder", None)
            label = getattr(scr, "title", "") or ""
            if "إيقاف المصانع" in label or cls == "SuperAdminScreen":
                from ui.super_admin_screen import SuperAdminScreen as _S
                return _S.request_access(self)
        except Exception:
            pass
        return True

    def switch(self, row, _back=False):
        """ينتقل لشاشة — ويُغلق السابقة تماماً.

        **شاشة واحدة حيّة في كل لحظة**: إبقاء كل الشاشات في الذاكرة
        يجعل أحداث تغيير الحجم والمؤقّتات تتفاعل بينها فيتجمّد
        النظام عند العودة لشاشة سابقة. الإغلاق عند الخروج يمنع ذلك
        نهائياً، والشاشة تُبنى من جديد ببيانات محدّثة عند فتحها.
        """
        if row < 0 or row >= len(self.screens):
            return
        # الشاشات الحسّاسة تُحرس برمز دخول قبل فتحها
        if not self._guard_screen(row):
            return
        # نتتبّع الشاشة الحالية بأنفسنا: `stack.currentIndex()` قد
        # لا يعكس الحالة فوراً في كل الأحوال.
        prev = getattr(self, "_current_row", 0)
        self._current_row = row
        self.stack.setCurrentIndex(row)
        # ══ سلسلة الرجوع ══
        # الانتقال من شاشةٍ إلى أخرى يُبقي الأولى حيّةً خلفها (فيعود
        # إليها «رجوع» كما تُركت). والرجوع يُغلق الشاشة المغادَرة،
        # والرئيسية تُغلق السلسلة كلها. وما زاد عن الحدّ يُغلق أقدمه.
        hist = self.__dict__.setdefault("_history", [])
        if row == 0:
            dropped = hist[:]
            hist.clear()
            for r in dropped + [prev]:
                if r != row:
                    self._release(r)
        else:
            if row in hist:
                hist.remove(row)
            if prev != row and prev > 0:
                if _back:
                    self._release(prev)
                else:
                    if prev in hist:
                        hist.remove(prev)
                    hist.append(prev)
                    while len(hist) > self.HISTORY_MAX:
                        self._release_old(hist.pop(0))
        screen = self.screens[row]
        node = self._items.get(screen)
        self.crumb.setText(
            node.text(0) if node is not None else config.COMPANY_NAME)
        # إخفاء الشريط الجانبي تماماً عند فتح أي شاشة فرعية لتتوسّع
        # لكامل عرض النافذة، وإظهاره عند العودة لشاشة الترحيب.
        is_sub = row != 0
        # ══ لا تُظهر شيئاً بلا أب ══
        # `switch(0)` تُستدعى أثناء التهيئة — قبل أن يُبنى العمود
        # الجانبي. وكان البديل حينها شجرةَ التنقّل نفسها وهي بلا أبٍ
        # بعد، و«إظهارُ» widget بلا أب يجعله **نافذةً مستقلة**:
        # فتومض شجرةٌ عاريةٌ على الشاشة لحظةً بعد تسجيل الدخول ثم
        # تختفي حين تُضمّ إلى مكانها. وهي «النوافذ السريعة» التي
        # شُكي منها. الآن: إن لم يُبنَ العمود تُحفظ الحالة وتُطبَّق
        # عند بنائه — ولا يُعرض شيءٌ بلا أب أبداً.
        panel = getattr(self, "side_panel", None)
        if panel is not None:
            panel.setVisible(not is_sub)
        else:
            self._panel_visible = not is_sub
        self.btn_close.setVisible(is_sub)      # زر الرجوع في كل شاشة فرعية
        if is_sub and hasattr(self, "_items"):
            self._update_back_btn()
        # ══ الشريط الأسود العلوي في الرئيسية وحدها (4.31) ══
        # العنوان والبحث والعيار و«تحديث» و«عرض» أدوات الواجهة، لا
        # الشاشة: داخلها يُطوى الشريط فترتفع الشاشة وتأخذ جداولها
        # الارتفاع كله. ويعود فور الرجوع إلى الرئيسية.
        # (بلا أب بعدُ أثناء التهيئة: إظهارُه حينها يجعله نافذةً تومض)
        hb = getattr(self, "_header_bar", None)
        if hb is not None and hb.parentWidget() is not None:
            hb.setVisible(not is_sub)
        # سعر الذهب في الواجهة الرئيسية وحدها — داخل الشاشة لا يزاحمها
        gb = getattr(self, "gold_bar", None)
        if gb is not None:
            if not is_sub:
                # أدوات الشاشة المغلقة تُفرَّغ **قبل** ظهور شريط السعر:
                # لو اجتمعا لحظةً لطلب الشريط الفرعي عرضهما معاً فتتّسع
                # النافذة خارج الشاشة وينزاح الشريط الجانبي عن مكانه
                self._mount_screen_tools(None)
            gb.setVisible(not is_sub)
        # ══ شريط الحالة في الرئيسية وحدها ══
        # داخل الشاشة كل سطرٍ للجدول: الشريط السفلي يُطوى ويعود
        # عند الرجوع إلى الرئيسية.
        if getattr(self, "_sb_user", None) is not None:
            self.statusBar().setVisible(not is_sub)
        self.btn_notes.setVisible(False)
        if is_sub:
            QtCore.QTimer.singleShot(250, self._update_notes_btn)
        # التحديث مؤجَّل لدورة أحداث لاحقة: يظهر التبديل فورياً
        # ثم تُحمَّل البيانات — فلا تتجمّد الواجهة أثناء الاستعلام.
        QtCore.QTimer.singleShot(0, lambda: self._mount_screen_tools(screen))
        if hasattr(screen, "refresh"):
            QtCore.QTimer.singleShot(0, self._refresh_current)

    def _on_update_checked(self):
        """يضيء زر التحديثات إن كان هناك إصدار أحدث منشور."""
        try:
            from services import update_channel
            st = update_channel.status()
            if not st.get("available"):
                return
            info = st.get("info") or {}
            v = info.get("version", "")
            self.btn_update.setText(f"⬆ تحديث متاح {v}")
            self.btn_update.setObjectName("updateReady")
            self.btn_update.setToolTip(
                f"الإصدار {v} متاح للتحميل — اضغط للتثبيت")
            # إعادة تطبيق النمط ليأخذ الشكل الجديد
            self.btn_update.setStyleSheet(self.btn_update.styleSheet())
            self.btn_update.style().unpolish(self.btn_update)
            self.btn_update.style().polish(self.btn_update)
        except Exception:
            pass

    def _online_update(self, info):
        """يحمّل التحديث من الإنترنت ويثبّته."""
        from services import update_channel
        prog = QtWidgets.QProgressDialog(
            "جارٍ تحميل التحديث…", "إلغاء", 0, 100, self)
        prog.setWindowTitle("تحديث عبر الإنترنت")
        prog.setMinimumWidth(400)
        prog.setAutoClose(False)
        prog.show()
        QtWidgets.QApplication.processEvents()
        cancelled = {"v": False}

        def on_prog(got, total):
            if prog.wasCanceled():
                cancelled["v"] = True
                raise ValueError("أُلغي التحميل")
            if total:
                prog.setValue(int(got * 100 / total))
                prog.setLabelText(
                    f"جارٍ التحميل… {got / 1048576:.1f} من "
                    f"{total / 1048576:.1f} ميجابايت")
            else:
                prog.setLabelText(
                    f"جارٍ التحميل… {got / 1048576:.1f} ميجابايت")
            QtWidgets.QApplication.processEvents()

        def on_step(msg):
            prog.setLabelText(msg)
            QtWidgets.QApplication.processEvents()

        try:
            res = update_channel.download_and_apply(
                info, on_progress=on_prog, on_step=on_step)
        finally:
            prog.close()
        self._update_done(res)

    def _update_done(self, res):
        """اكتمل التثبيت: إعادة التشغيل الآن تفعّل الإصدار الجديد."""
        if ask(self, f"اكتمل التحديث إلى الإصدار {res['version']}.\n\n"
                     "يعمل الإصدار الجديد بعد إعادة تشغيل البرنامج.\n"
                     "إعادة التشغيل الآن؟"):
            self._restart_app()

    def _restart_app(self):
        """يُغلق البرنامج ويفتحه من جديد (exe أو من المصدر)."""
        import os
        import subprocess
        import sys
        try:
            env = dict(os.environ)
            env.pop("JADEITE_CODE_DIR", None)
            if getattr(sys, "frozen", False):
                env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
                env.pop("_MEIPASS2", None)
                cmd = [sys.executable]
            else:
                import main as _m
                cmd = [sys.executable, os.path.abspath(_m.__file__)]
            subprocess.Popen(cmd, env=env, close_fds=True,
                             cwd=os.path.dirname(cmd[-1]))
        except Exception as e:                      # noqa: BLE001
            err(self, f"أعد تشغيل البرنامج يدوياً لتفعيل التحديث.\n{e}")
            return
        QtWidgets.QApplication.quit()

    def do_update(self):
        """يرفع حزمة تحديث على النسخة القائمة — بضمانات كاملة."""
        try:
            from services import update_channel, updater
            # ══ أولاً: التحقق عبر الإنترنت ══
            # في خيطٍ جانبي: خادمٌ لا يستجيب كان يترك النافذة سوداء
            # حتى تنتهي مهلة الاتصال.
            def _check():
                st = update_channel.status()
                return (st.get("info") if st.get("available")
                        else update_channel.check())

            online = None
            try:
                ok, online, _ex = run_bg(
                    _check, parent=self, text="جارٍ التحقق من التحديثات…",
                    stage="فحص التحديث", timeout=25.0)
                if not ok or _ex or (online and not online.get("newer")):
                    online = None
            except Exception:
                online = None      # بلا إنترنت: نتابع بالملف المحلي

            if online:
                msg = [
                    f"يتوفّر تحديث جديد: الإصدار {online['version']}",
                    f"الإصدار المثبَّت: {online['current']}",
                ]
                if online.get("date"):
                    msg.append(f"تاريخ النشر: {online['date']}")
                if online.get("size"):
                    msg.append(
                        f"الحجم: {online['size'] / 1048576:.1f} ميجابايت")
                msg.append("")
                msg.append("يُحمَّل من السحابة، وتُطابَق بصمته قبل "
                           "التثبيت، وتُؤخذ نسخة احتياطية أولاً — "
                           "والبيانات لا تُمسّ.")
                if online.get("notes"):
                    msg.append("")
                    msg.append("ما في هذا التحديث:")
                    msg.append(str(online["notes"])[:900])
                msg.append("")
                msg.append("تحميل التحديث وتثبيته الآن؟")
                if ask(self, "\n".join(msg)):
                    self._online_update(online)
                    return

            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "اختر حزمة التحديث (ملف محفوظ)", "",
                "حزمة تحديث (*.zip *.jup)")
            if not path:
                return
            info = updater.inspect(path)
            msg = [
                f"الإصدار في الحزمة: {info['version']}",
                f"الإصدار المثبَّت:   {info['current']}",
                f"عدد الملفات: {info['files']}",
            ]
            if info.get("date"):
                msg.append(f"تاريخ الحزمة: {info['date']}")
            msg.append("")
            if info["is_older"]:
                msg.append("⚠ الحزمة **أقدم** من المثبَّت — التثبيت "
                           "يُرجع النظام للخلف.")
            elif info["is_same"]:
                msg.append("ℹ الحزمة بنفس الإصدار المثبَّت.")
            msg.append("")
            msg.append("قبل التثبيت تُؤخذ نسخة احتياطية كاملة، "
                       "والبيانات (قواعد المصانع والإعدادات والصور) "
                       "لا تُمسّ إطلاقاً.")
            msg.append("وإن فشل فحص ما بعد التثبيت تُستعاد النسخة "
                       "السابقة تلقائياً.")
            if info.get("notes"):
                msg.append("")
                msg.append("ما في هذا التحديث:")
                msg.append(str(info["notes"])[:900])
            msg.append("")
            msg.append("المتابعة؟")
            if not ask(self, "\n".join(msg)):
                return

            prog = QtWidgets.QProgressDialog(
                "جارٍ التحديث…", "", 0, 0, self)
            prog.setWindowTitle("تحديث النظام")
            prog.setCancelButton(None)
            prog.setMinimumWidth(380)
            prog.show()
            QtWidgets.QApplication.processEvents()

            def _step(m):
                prog.setLabelText(m)
                QtWidgets.QApplication.processEvents()

            try:
                res = updater.apply_update(
                    path, allow_older=info["is_older"], on_step=_step)
            finally:
                prog.close()

            self._update_done(res)
        except Exception as e:
            err(self, e)

    def _mount_screen_tools(self, screen):
        """يعرض أزرار الشاشة العامة في الشريط العلوي.

        كل شاشة قد توفّر `toolbar_widgets()` تُرجع أزرارها العامة،
        فتظهر بجوار «إغلاق الشاشة» — أوضح وأقرب لليد، ولا تزاحم
        محتوى الشاشة.
        """
        try:
            while self._tools_lay.count():
                it = self._tools_lay.takeAt(0)
                w = it.widget()
                if w is not None:
                    w.setParent(None)
            real = getattr(screen, "real", screen)
            fn = getattr(real, "toolbar_widgets", None)
            widgets = fn() if callable(fn) else []
            for w in widgets or []:
                self._tools_lay.addWidget(w)
            self.screen_tools.setVisible(bool(widgets))
        except Exception:
            try:
                self.screen_tools.setVisible(False)
            except Exception:
                pass

    # ══════════ الربط مع الهيئة ══════════
    def open_identity(self):
        """حوار هوية المصنع — وبعد الاعتماد تتبدّل الواجهة فوراً."""
        try:
            from ui.factory_identity_dialog import open_dialog
            dlg = open_dialog(self, self.user)
        except Exception as e:
            err(self, e)
            return
        if getattr(dlg, "applied", False):
            self.refresh_identity()

    @staticmethod
    def _app_title():
        """«نظام محاسبة مصنع الذهب — عيار 21»: بعيار المصنع الفعّال."""
        try:
            return kv.rename(config.APP_NAME)
        except Exception:
            return config.APP_NAME

    def _factory_name(self):
        """اسم المصنع المعروض: المعتمد في «هوية المصنع» إن ضُبطت."""
        try:
            from services import branding
            if branding.current().get("custom"):
                return config.COMPANY_NAME
        except Exception:
            pass
        return tenant.factory_name()

    def _user_label(self):
        role = ("المدير العام" if self.is_super
                else f"مصنع: {self._factory_name()}")
        return (f"{self.user.get('full_name') or self.user['username']}"
                f" — {role}")

    def refresh_identity(self):
        """الاسم والشعار في الواجهة بعد تغيير الهوية (القوالب تقرؤها
        عند كل طباعة فلا تحتاج شيئاً)."""
        name = config.COMPANY_NAME
        try:
            self.welcome.refresh_identity()
        except Exception:
            pass
        if self.stack.currentIndex() == 0:
            self.crumb.setText(name)
        lbl = getattr(self, "_sb_fac", None)
        if lbl is not None:
            lbl.setText(f"🏭 {name}")
        hu = getattr(self, "_hdr_user", None)
        if hu is not None:
            hu.setText(self._user_label())
        try:
            from services import tenant
            if tenant.get_all().get("factory_name") != name:
                tenant.update(factory_name=name)
        except Exception:
            pass

    def open_fatoora(self):
        """نافذة الربط والجاهزية — ثم يُحدَّث مؤشّرها في شريط الحالة."""
        try:
            from ui.fatoora_screen import open_dialog
            open_dialog(self, self.user)
        except Exception as e:
            err(self, e)
        self._tick_fatoora()

    def _tick_fatoora(self):
        """مؤشّر الربط في شريط الحالة: الحكم نفسه بكلمتين ولونه."""
        lbl = getattr(self, "_sb_zatca", None)
        if lbl is None:
            return
        try:
            from services.fatoora import readiness
            with db(readonly=True) as conn:
                level, title, _d = readiness.verdict(conn)
        except Exception:
            return
        color = {"ok": "#0F5A24", "warn": "#8A5A00",
                 "fail": "#9A1414"}.get(level, "#555")
        lbl.setText(f"🧾 {title}")
        lbl.setStyleSheet(f"color:{color}; font-weight:bold;")
        lbl.setToolTip("الربط مع هيئة الزكاة والضريبة — انقر لفتحه")

    # ══════════ شرح الشاشة المطويّ ══════════
    def _current_notes(self):
        from ui.widgets import declutter
        row = getattr(self, "_current_row", 0)
        if not (0 < row < len(self.screens)):
            return []
        return declutter.notes_in(self.screens[row])

    def _update_notes_btn(self):
        """يُظهر «ⓘ» حين يكون للشاشة شرحٌ مطويّ، وتلميحُه أوّلُه."""
        try:
            from ui.widgets import declutter
            notes = [] if declutter.showing() else self._current_notes()
            self.btn_notes.setVisible(bool(notes))
            if notes:
                self.btn_notes.setToolTip(
                    "شرح الشاشة — انقر لعرضه كاملاً\n\n" + notes[0])
        except Exception:
            pass

    def show_screen_notes(self):
        """يعرض شرح الشاشة كله في بطاقةٍ عائمة تُغلق بأي نقرة."""
        try:
            notes = self._current_notes()
            if not notes:
                return
            pop = QtWidgets.QFrame(self, QtCore.Qt.Popup)
            pop.setObjectName("notesPop")
            pop.setLayoutDirection(QtCore.Qt.RightToLeft)
            lay = QtWidgets.QVBoxLayout(pop)
            lay.setContentsMargins(16, 12, 16, 12)
            lay.setSpacing(8)
            from ui.widgets import declutter
            row = getattr(self, "_current_row", 0)
            head = declutter.title_in(self.screens[row]) or self.crumb.text()
            title = QtWidgets.QLabel("ⓘ  " + head)
            title.setWordWrap(True)
            title.setObjectName("notesPopTitle")
            lay.addWidget(title)
            for t in notes:
                lbl = QtWidgets.QLabel("•  " + t)
                lbl.setObjectName("notesPopText")
                lbl.setWordWrap(True)
                lbl.setTextInteractionFlags(
                    QtCore.Qt.TextSelectableByMouse)
                lay.addWidget(lbl)
            width = min(560, max(360, self.width() // 2))
            pop.setFixedWidth(width)
            lay.activate()
            pop.setFixedHeight(max(lay.heightForWidth(width),
                                   lay.minimumSize().height()))
            btn = self.btn_notes
            at = btn.mapToGlobal(QtCore.QPoint(btn.width() - pop.width(),
                                               btn.height() + 4))
            scr = QtWidgets.QApplication.desktop().availableGeometry(btn)
            at.setX(max(scr.left() + 8,
                        min(at.x(), scr.right() - pop.width() - 8)))
            pop.move(at)
            pop.show()
            self._notes_pop = pop
        except Exception as e:
            err(self, e)

    def _set_show_notes(self, on):
        try:
            from ui.widgets import declutter
            declutter.set_showing(bool(on), self.user.get("username"))
            self._update_notes_btn()
        except Exception as e:
            err(self, e)

    def _refresh_current(self):
        """يحدّث الشاشة الظاهرة حالياً، بحماية من أي استثناء."""
        try:
            row = getattr(self, "_current_row", 0)
            if not (0 <= row < len(self.screens)):
                return
            scr = self.screens[row]
            fn = getattr(scr, "refresh", None)
            if callable(fn):
                fn()
        except Exception:
            pass          # فشل التحديث لا يُجمّد النظام

    def _goto(self, screen):
        """ينتقل إلى شاشة معيّنة ويفتح مجموعتها إن كانت مطوية."""
        if screen not in self.screens:
            return
        node = self._items.get(screen)
        if node is not None:
            if node.parent() is not None:
                node.parent().setExpanded(True)
            self.sidebar.setCurrentItem(node)
        self.switch(self.screens.index(screen))

    def open_subledger(self, entity_type):
        """من لوحة التحكم: يفتح كشف أرصدة الأستاذ المساعد على الفئة."""
        scr = getattr(self, "subledger_screen", None)
        if scr is None:
            return
        idx = scr.category.findData(entity_type)
        if idx >= 0:
            scr.category.setCurrentIndex(idx)
        self._goto(scr)

    def open_document_for_edit(self, source_table, source_id):
        """التعمق المستندي الشامل: يفتح الشاشة الأصلية لأي عملية معبّأة
        ببياناتها استعداداً للتعديل."""
        target = self.edit_targets.get(source_table)
        if target is None:
            err(self, "لا توجد شاشة تعديل لهذا النوع من المستندات")
            return
        screen, loader = target
        self._goto(screen)
        # التحميل مؤجَّل لدورة أحداث لاحقة: `_goto` يبني الشاشة ويجدول
        # تحديثها، والتحميل الفوري يسبق البناء فيضيع — ثم يمسح التحديث
        # ما حُمِّل. التأجيل يجعل الترتيب: بناء ← تحديث ← تحميل.
        QtCore.QTimer.singleShot(
            0, lambda: self._load_doc_now(screen, loader, source_id))

    def _load_doc_now(self, screen, loader, source_id):
        """يحمّل المستند بعد اكتمال بناء الشاشة وتحديثها."""
        try:
            real = getattr(screen, "real", screen)
            fn = getattr(real, loader, None)
            if callable(fn):
                fn(source_id)
        except Exception as e:
            err(self, e)

    # ══════════════════════════════════════════════════════════════
    #  عيار المصنع
    # ══════════════════════════════════════════════════════════════

    def _change_karat(self):
        """يبدّل وحدة عرض وإدخال الأوزان في النظام كله.

        **لا يُكتب رقم واحد في قاعدة البيانات**: القيد يبقى بمكافئ
        عيار 18، والعيار المختار وحدةُ قراءة وكتابة في الواجهة فقط.
        لذلك التبديل قابل للرجوع في أي لحظة بلا أي أثر على الأرصدة.

        الشاشة الحالية تُعاد بناؤها بالعيار الجديد. وبقية الشاشات
        تُبنى عند فتحها أصلاً (شاشة واحدة حيّة في كل لحظة) فتقرأ
        العيار الجديد تلقائياً.
        """
        try:
            k = self.karat_box.currentData()
            cur = kv.active()
            if k is None or int(k) == cur:
                return
            if not ask(self,
                       f"تحويل المصنع إلى مصنع عيار {k}؟\n\n"
                       f"• كل القيود والأرصدة والمخزون والفواتير وصناديق "
                       f"الكسر والتقارير والقوالب تُعرض وتُدخل وتُطبع "
                       f"بمكافئ عيار {k}.\n"
                       "• المبالغ النقدية لا تتغيّر إطلاقاً، والأجر "
                       "للجرام يتعدّل ليبقى إجمالي الأجور كما هو.\n"
                       "• التبديل آمن وقابل للرجوع في أي لحظة: الأرصدة "
                       "نفسها لا تتغيّر، وتُقرأ بالعيار الجديد.\n\n"
                       "أي إدخال لم يُرحَّل في الشاشة المفتوحة سيُفقد."):
                idx = self.karat_box.findData(cur)
                self.karat_box.blockSignals(True)
                if idx >= 0:
                    self.karat_box.setCurrentIndex(idx)
                self.karat_box.blockSignals(False)
                return
            kv.set_active(k, self.user.get("username"))
            # عنوان النظام يحمل عيار المصنع
            self.setWindowTitle(self._app_title())
            tl = getattr(self, "_title_lbl", None)
            if tl is not None:
                tl.setText(self._app_title())
            # الوحدة الجديدة للنظام كله: عيار صندوق الكسر في المبيعات
            # والتوريد يتبعها من الآن (يُنسى آخر اختيارٍ بالعيار القديم)
            for _pref in ("sales_scrap_karat", "supply_scrap_karat"):
                save_pref(_pref, "", self.user.get("username"))
            try:
                with db() as conn:
                    log_action(conn, self.user.get("username"), "update",
                               "app_settings", None, f"factory_karat={k}")
            except Exception:
                pass
            row = getattr(self, "_current_row", 0)
            if row > 0:
                scr = self.screens[row]
                rel = getattr(scr, "release", None)
                if callable(rel):
                    rel()
                self._current_row = 0
                self.switch(row)
            info(self, f"أصبح المصنع مصنع عيار {k}: كل القيود والأرصدة "
                       f"والمخزون والتقارير بمكافئ عيار {k}.")
        except Exception as e:
            err(self, e)

    # ══════════════════════════════════════════════════════════════
    #  المظهر ومقاس الخط
    # ══════════════════════════════════════════════════════════════

    def _view_menu_button(self):
        """زر «عرض» وقائمته: المظهر · مقاس الخط · البحث · ترتيب القائمة.

        التبديل فوريّ بلا إعادة تشغيل: Qt يعيد رسم كل النوافذ المفتوحة
        عند تغيير ورقة الأنماط، فيرى المستخدم أثر اختياره في اللحظة
        نفسها ويعدل عنه إن لم يعجبه.
        """
        btn = QtWidgets.QToolButton()
        btn.setText("⚙ عرض")
        btn.setToolTip("المظهر (فاتح/ليلي) · مقاس الخط · البحث الموحّد")
        btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        menu = QtWidgets.QMenu(btn)

        # ══ هوية المصنع — أول بندٍ: كل مصنعٍ باسمه وشعاره ══
        a_id = menu.addAction("🏭 هوية المصنع — الشعار والاسم والعنوان"
                              " والسجل…")
        f = a_id.font()
        f.setBold(True)
        a_id.setFont(f)
        a_id.triggered.connect(self.open_identity)
        a_bk = menu.addAction("♻ النسخ الاحتياطية والاسترجاع (آخر 20)…")
        a_bk.triggered.connect(self.open_backups)
        # ══ الربط مع الهيئة ══
        a_zatca = menu.addAction("🧾 الربط مع هيئة الزكاة والضريبة "
                                 "(الفوترة الإلكترونية)…")
        a_zatca.setFont(f)
        a_zatca.triggered.connect(self.open_fatoora)
        menu.addSeparator()

        cur_theme = theme.current_theme()
        m_theme = menu.addMenu("🎨 المظهر")
        gt = QtWidgets.QActionGroup(menu)
        gt.setExclusive(True)
        for key, label, _tk in theme.THEMES:
            a = m_theme.addAction(label)
            a.setCheckable(True)
            a.setChecked(key == cur_theme)
            gt.addAction(a)
            a.triggered.connect(lambda _c=False, k=key: self._set_theme(k))

        cur_scale = theme.current_scale()
        m_font = menu.addMenu("🔠 مقاس الخط")
        gf = QtWidgets.QActionGroup(menu)
        gf.setExclusive(True)
        for val, label in theme.SCALES:
            a = m_font.addAction(f"{label}  ({int(val * 100)}%)")
            a.setCheckable(True)
            a.setChecked(abs(val - cur_scale) < 0.01)
            gf.addAction(a)
            a.triggered.connect(lambda _c=False, v=val: self._set_scale(v))

        # ══ الخط والتأثيرات ══
        from ui import fonts as _fonts
        from ui.widgets import effects as _fx
        m_fam = menu.addMenu("🔤 الخط")
        gfam = QtWidgets.QActionGroup(menu)
        gfam.setExclusive(True)
        cur_fam = _fonts.current_choice()
        for key, label in _fonts.CHOICES:
            a = m_fam.addAction(label)
            a.setCheckable(True)
            a.setChecked(key == cur_fam)
            gfam.addAction(a)
            a.triggered.connect(lambda _c=False, k=key: self._set_font(k))
        a_fx = menu.addAction("✨ التأثيرات الحديثة (ظلال البطاقات)")
        a_fx.setCheckable(True)
        a_fx.setChecked(_fx.enabled())
        a_fx.toggled.connect(self._set_effects)
        from ui.widgets import declutter as _dc
        a_notes = menu.addAction("📝 إظهار العناوين والملاحظات التوضيحية")
        a_notes.setCheckable(True)
        a_notes.setChecked(_dc.showing())
        a_notes.toggled.connect(self._set_show_notes)

        # ══ وجهة رمز QR على الفاتورة ══
        # القرار ليس تجميلياً: الرابط السحابي يفتحه العميل من بيته،
        # والمحلي لا يفتحه إلا من على شبكة المصنع. فمن يريد أن يرى
        # عميله الصفحة يحتاج السحابة، ومن يريد ألا يخرج شيء من المصنع
        # يقصره على الشبكة.
        m_qr = menu.addMenu("🔗 رمز QR على الفاتورة")
        gq = QtWidgets.QActionGroup(menu)
        gq.setExclusive(True)
        cur_qr = self._qr_mode()
        for key, label in (
                ("auto", "تلقائي — السحابة ثم شبكة المصنع"),
                ("cloud", "السحابة فقط (يفتحه العميل من أي مكان)"),
                ("lan", "شبكة المصنع فقط (لا يخرج شيء للإنترنت)"),
                ("off", "بلا رمز")):
            a = m_qr.addAction(label)
            a.setCheckable(True)
            a.setChecked(key == cur_qr)
            gq.addAction(a)
            a.triggered.connect(lambda _c=False, k=key: self._set_qr_mode(k))
        m_qr.addSeparator()
        a_diag = m_qr.addAction("🩺 لماذا لم يظهر الرمز؟ (فحص)")
        a_diag.triggered.connect(self._qr_diagnose)
        a_use = m_qr.addAction("📊 المساحة السحابية المستعملة…")
        a_use.triggered.connect(self._qr_usage)
        a_clean = m_qr.addAction("🧹 حذف صفحات الفواتير القديمة…")
        a_clean.triggered.connect(self._qr_purge)

        menu.addSeparator()
        a_find = menu.addAction("🔍 بحث موحّد…        Ctrl+K")
        a_find.triggered.connect(self.open_palette)
        a_tf = menu.addAction("🔎 بحث في الجدول…     Ctrl+F")
        a_tf.triggered.connect(self.search_table)
        a_keys = menu.addAction("⌨ الاختصارات…         F1")
        a_keys.triggered.connect(self.show_shortcuts)
        a_nav = menu.addAction("↺ إعادة القائمة الجانبية لترتيبها الأصلي")
        a_nav.triggered.connect(self.reset_nav_layout)

        btn.setMenu(menu)
        self._view_menu = menu          # مرجع يمنع جمعه مبكّراً
        return btn

    def _qr_mode(self):
        try:
            from services import invoice_share
            with db(readonly=True) as conn:
                return invoice_share.mode(conn)
        except Exception:
            return "auto"

    def _set_qr_mode(self, value):
        try:
            from services import invoice_share
            with db() as conn:
                invoice_share.set_mode(conn, value,
                                       self.user.get("username"))
            if value == "cloud":
                info(self, "رمز الفاتورة سيحمل رابطاً سحابياً يفتحه "
                           "العميل من أي مكان.\n\n"
                           "يتطلب مجلد تخزين عام باسم «invoice-photos» "
                           "في حساب المصنع السحابي. وإن تعذّر الرفع "
                           "فلن يُطبع رمز — اختر «تلقائي» ليعود للرابط "
                           "المحلي عند التعذّر.")
            elif value == "lan":
                info(self, "رمز الفاتورة سيحمل رابطاً على شبكة المصنع "
                           "وحدها.\n\nيفتحه من كان جواله على شبكة "
                           "المصنع والنظام يعمل — ولا يفتحه العميل بعد "
                           "خروجه.")
        except Exception as e:
            err(self, e)

    def _qr_diagnose(self):
        """يمشي مسار رمز QR خطوةً خطوة ويعرض أين توقّف بالضبط.

        الطباعة لا تتوقف لأجل صورة، فكل تعذّر فيها صامت — وهذا يحمي
        المستند لكنه يُعمي المستخدم عن السبب. هذه النافذة تكشفه.
        """
        try:
            from services import invoice_share
            # تسعُ خطواتٍ منها نداءاتُ شبكةٍ برفعٍ وقراءةٍ وجلبٍ
            # للرابط — دقيقةٌ كاملة على اتصالٍ بطيء. على خيط الواجهة
            # كانت النافذة تبقى سوداء طوالها.
            def _report():
                with db() as conn:
                    return invoice_share.report(conn)

            ok, txt, ex = run_bg(_report, parent=self,
                                 text="جارٍ فحص مسار الرمز…",
                                 stage="فحص QR", timeout=90.0)
            if ex:
                raise ex
            if not ok:
                warn(self, "تأخّر الفحص أكثر من دقيقة ونصف — الاتصال "
                           "بالإنترنت بطيءٌ أو محجوب. أعد المحاولة، أو "
                           "استعمل «رمز على شبكة المصنع».")
                return
            box = QtWidgets.QMessageBox(self)
            box.setWindowTitle("فحص رمز QR على الفاتورة")
            box.setIcon(QtWidgets.QMessageBox.Information)
            box.setText("نتيجة فحص مسار الرمز لآخر فاتورة:")
            box.setDetailedText(txt)
            box.setInformativeText(
                txt if len(txt) < 900 else
                "التفاصيل كاملةً في «إظهار التفاصيل».")
            b_sql = box.addButton("📋 نسخ أمر SQL لصلاحيات المجلد",
                                  QtWidgets.QMessageBox.ActionRole)
            b_pub = box.addButton("☁ نشر الفواتير المفعَّلة غير المنشورة",
                                  QtWidgets.QMessageBox.ActionRole)
            box.addButton("إغلاق", QtWidgets.QMessageBox.RejectRole)
            box.exec_()
            if box.clickedButton() is b_sql:
                QtWidgets.QApplication.clipboard().setText(
                    invoice_share.policy_sql())
                info(self,
                     "نُسخ الأمر. الصقه في Supabase ← SQL Editor ثم "
                     "Run.\n\n"
                     "• يحذف أي سياسة سابقة بنفس الاسم أولاً، فلا يفشل "
                     "بـ«already exists» — وهذا الخطأ يُفشل الدفعة كلها "
                     "فيبقى ما بعده غير منفَّذ.\n"
                     "• يمنح القراءة والرفع والاستبدال معاً.\n\n"
                     "ثم أعد هذا الفحص: سطر الرفع يجب أن يصير ✔.")
            elif box.clickedButton() is b_pub:
                self._qr_republish()
        except Exception as e:
            err(self, e)

    def _qr_republish(self):
        """يمنح روابط سحابية للفواتير التي طُبعت برابطٍ محلي.

        بعد إصلاح صلاحيات المجلد تبقى الفواتير السابقة بلا رابط عام،
        فرموزها المطبوعة لا تُفتح إلا من شبكة المصنع. هذا يعالجها
        دفعةً واحدة — بلا إعادة ترحيل، والرمز المطبوع لا يتغيّر.
        """
        try:
            import config
            from services import invoice_share
            # نشرٌ دفعي: فاتورةٌ بعد فاتورة عبر الإنترنت. مئةُ فاتورةٍ
            # تعني دقائق — لا يجوز أن تمرّ على خيط الواجهة.
            _co = config.COMPANY_NAME
            ok, out, ex = run_bg(
                lambda: invoice_share.republish_pending(_co),
                parent=self, text="جارٍ نشر الفواتير…", stage="نشر دفعي",
                timeout=600.0)
            if ex:
                raise ex
            if not ok:
                warn(self, "ما زال النشر جارياً في الخلفية — أعد فتح "
                           "«لماذا لم يظهر الرمز؟» بعد قليل لمعرفة ما تمّ.")
                return
            done, total = out
            if not total:
                info(self, "لا توجد فواتير مفعَّلة تنتظر النشر.")
            elif done:
                info(self, f"نُشرت {done:,} فاتورة من {total:,}."
                           + ("" if done == total else
                              "\n\nتوقّف الباقي — أعد الفحص لمعرفة السبب."))
            else:
                err(self, "لم تُنشر أي فاتورة — الرفع ما زال مرفوضاً.\n\n"
                          "نفّذ أمر SQL لصلاحيات المجلد أولاً "
                          "(زر «نسخ أمر SQL» في شاشة الفحص).")
        except Exception as e:
            err(self, e)

    def _qr_usage(self):
        """يعرض ما تشغله صفحات الفواتير وصورها من المساحة السحابية."""
        try:
            from services import invoice_share
            with db(readonly=True) as conn:
                u = invoice_share.usage(conn)
            txt = (
                f"صور الموديلات المرفوعة: {u['images']:,} صورة — "
                f"{u['image_mb']:,.2f} ميجابايت\n"
                f"صفحات الفواتير المنشورة: {u['pages']:,} صفحة — "
                f"{u['page_mb']:,.2f} ميجابايت\n"
                f"الإجمالي: {u['total_mb']:,.2f} ميجابايت\n\n"
                "الصورة تُصغَّر وتُضغط قبل رفعها، وتُرفع **مرة واحدة** "
                "مهما تكرّر موديلها في الفواتير — فلا تتضاعف المساحة "
                "مع كل فاتورة.")
            orph, omb = u.get("orphans", 0), u.get("orphan_mb", 0.0)
            if not orph:
                info(self, txt, "المساحة السحابية")
                return
            if ask(self,
                   txt + f"\n\n♻ صورٌ لم تعد تستعملها أي فاتورة منشورة: "
                         f"{orph:,} صورة — {omb:,.2f} ميجابايت.\n\n"
                         "حذفها الآن؟ (مساحة محجوزة بلا مقابل — ولا يُحذف "
                         "رقمٌ محاسبي ولا صفحةٌ ما زالت مستعملة)",
                   "المساحة السحابية"):
                with busy(self, "جارٍ حذف الصور غير المستعملة…",
                          stage="تنظيف التخزين"):
                    with db() as conn:
                        n, mb = invoice_share.purge_orphan_images(
                            conn, self.user.get("username"))
                info(self, f"حُذفت {n:,} صورة — استُرجع "
                           f"{mb:,.2f} ميجابايت.")
        except Exception as e:
            err(self, e)

    def _qr_purge(self):
        """يحذف صفحات الفواتير الأقدم من سنة — وصور الموديلات تبقى."""
        try:
            import datetime as _dt
            from services import invoice_share
            cut = (_dt.date.today() - _dt.timedelta(days=365)).isoformat()
            if not ask(self,
                       f"حذف صفحات الفواتير الأقدم من {cut} من التخزين "
                       "السحابي؟\n\n"
                       "• لا يُحذف رقمٌ محاسبي ولا فاتورة — الصفحة "
                       "المعروضة على الجوال وحدها.\n"
                       "• صور الموديلات تبقى: الصورة الواحدة تشير "
                       "إليها فواتير كثيرة.\n"
                       "• رموز QR على الأوراق القديمة لن تفتح بعدها."):
                return
            with db() as conn:
                n = invoice_share.purge_pages(
                    conn, cut, self.user.get("username"))
            info(self, f"حُذفت {n:,} صفحة فاتورة من التخزين السحابي.")
        except Exception as e:
            err(self, e)

    def _set_theme(self, name):
        try:
            theme.set_theme(name, self.user.get("username"))
            theme.apply(QtWidgets.QApplication.instance(), theme=name)
            # ألوانٌ تُرسم بالشيفرة (صفّ الإجمالي، الدرجات) تُقرأ من
            # المظهر لحظة العرض — فتُعاد قراءة الشاشة لتأخذ ألوانه
            self._refresh_current()
        except Exception as e:
            err(self, e)

    def _set_scale(self, value):
        try:
            theme.set_scale(value, self.user.get("username"))
            theme.apply(QtWidgets.QApplication.instance(), scale=value)
        except Exception as e:
            err(self, e)

    def _set_font(self, key):
        try:
            from ui import fonts as _fonts
            _fonts.set_choice(key, self.user.get("username"))
            theme.apply(QtWidgets.QApplication.instance())
            self.toast("✔ طُبّق الخط: " + dict(_fonts.CHOICES).get(key, key))
        except Exception as e:
            err(self, e)

    def _set_effects(self, on):
        try:
            from ui.widgets import effects as _fx
            _fx.set_enabled(bool(on), self.user.get("username"))
            _fx.refresh_all()
        except Exception as e:
            err(self, e)

    # ══════════════════════════════════════════════════════════════
    #  أدواتٌ حديثة موحّدة: بحث الجدول · تحديث · تصدير · اختصارات
    # ══════════════════════════════════════════════════════════════

    def toast(self, text, ms=2200):
        try:
            from ui.widgets import toast as _t
            return _t.show(self, text, ms)
        except Exception:
            return None

    def _current_page(self):
        try:
            return self.stack.currentWidget()
        except Exception:
            return None

    def _table_target(self):
        from ui.widgets import table_search as ts
        v = ts.target_view()
        if v is None or not v.isVisible() or v.objectName() == "sidebar":
            v = ts.largest_visible(self._current_page())
        return v

    def search_table(self):
        """Ctrl+F: شريط بحثٍ فوريّ فوق الجدول المعروض."""
        from ui.widgets import table_search as ts
        v = self._table_target()
        if v is None:
            self.toast("لا جدول في هذه الشاشة يُبحث فيه")
            return None
        return ts.open_search(v)

    def refresh_screen(self):
        """F5: يعيد قراءة الشاشة الظاهرة من القاعدة."""
        row = getattr(self, "_current_row", 0)
        scr = self.screens[row] if 0 <= row < len(self.screens) else None
        if scr is None or not callable(getattr(scr, "refresh", None)):
            return
        self._refresh_current()
        self.toast("↻ حُدّثت الشاشة")

    def export_table(self):
        """Ctrl+Shift+E: يصدّر الجدول المعروض إلى Excel."""
        v = self._table_target()
        if not isinstance(v, QtWidgets.QTableWidget):
            self.toast("لا جدول في هذه الشاشة يُصدَّر")
            return
        try:
            from ui.widgets.table_tools import export_csv
            name = self.crumb.text() if hasattr(self, "crumb") else "جدول"
            export_csv(self, v, name)
        except Exception as e:
            err(self, e)

    SHORTCUTS = (
        ("Ctrl+K", "بحثٌ موحّد: أي شاشة أو حساب أو جهة"),
        ("Ctrl+F", "بحثٌ فوريّ داخل الجدول المعروض (Esc يغلقه)"),
        ("F5", "تحديث الشاشة الحالية من القاعدة"),
        ("Ctrl+Shift+E", "تصدير الجدول المعروض إلى Excel"),
        ("Enter / الأسهم", "الانتقال بين خانات الإدخال للأمام وللخلف"),
        ("120+35.5 ثم Enter", "حاسبةٌ في كل خانة وزنٍ أو مبلغ"),
        ("١٢٫٥", "الأرقام العربية تُقبل في الخانات وتتحوّل إلى 12.5"),
        ("F1", "هذه القائمة"),
    )

    def show_shortcuts(self):
        """F1: نافذةٌ بكل الاختصارات والخصائص الحديثة."""
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("الاختصارات والخصائص")
        dlg.setMinimumWidth(560)
        t = QtWidgets.QTableWidget(len(self.SHORTCUTS), 2)
        t.setHorizontalHeaderLabels(["الاختصار", "ما يفعله"])
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        t.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        for i, (k, d) in enumerate(self.SHORTCUTS):
            a = QtWidgets.QTableWidgetItem(k)
            a.setTextAlignment(QtCore.Qt.AlignCenter)
            f = a.font()
            f.setBold(True)
            a.setFont(f)
            t.setItem(i, 0, a)
            t.setItem(i, 1, QtWidgets.QTableWidgetItem(d))
        hh = t.horizontalHeader()
        hh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        t.verticalHeader().setDefaultSectionSize(40)
        t.setMinimumHeight(40 * len(self.SHORTCUTS) + 50)
        box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        box.button(QtWidgets.QDialogButtonBox.Close).setText("إغلاق")
        box.rejected.connect(dlg.reject)
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.addWidget(t)
        lay.addWidget(box)
        self._shortcuts_dlg = dlg
        dlg.exec_()

    # ══════════ شريط الحالة ══════════
    _DAYS = ("الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة",
             "السبت", "الأحد")

    def _build_status_bar(self):
        """شريطٌ سفليّ هادئ: المستخدم · المصنع · الإصدار · الوقت · الاختصارات."""
        try:
            sb = self.statusBar()
            sb.setObjectName("statusbar")
            sb.setSizeGripEnabled(False)
            u = self.user.get("full_name") or self.user.get("username", "")
            try:
                fac = self._factory_name()
            except Exception:
                fac = getattr(config, "COMPANY_NAME", "")
            self._sb_user = QtWidgets.QLabel(f"👤 {u}")
            self._sb_fac = QtWidgets.QLabel(f"🏭 {fac}")
            self._sb_ver = QtWidgets.QLabel(
                f"الإصدار {getattr(config, 'APP_VERSION', '')}")
            self._sb_hint = QtWidgets.QLabel(
                "Ctrl+K بحث · Ctrl+F بحث في الجدول · F5 تحديث · F1 الاختصارات")
            self._sb_clock = QtWidgets.QLabel("")
            for w in (self._sb_user, self._sb_fac, self._sb_ver,
                      self._sb_hint, self._sb_clock):
                w.setObjectName("statusItem")
            self._sb_hint.setObjectName("statusHint")
            sb.addWidget(self._sb_user)
            sb.addWidget(self._sb_fac)
            sb.addWidget(self._sb_ver)
            # حالة الربط مع الهيئة — ظاهرةٌ في الرئيسية، والنقر يفتحها
            self._sb_zatca = QtWidgets.QPushButton("🧾 …")
            self._sb_zatca.setObjectName("statusLink")
            self._sb_zatca.setFlat(True)
            self._sb_zatca.setCursor(QtCore.Qt.PointingHandCursor)
            self._sb_zatca.clicked.connect(self.open_fatoora)
            sb.addWidget(self._sb_zatca)
            QtCore.QTimer.singleShot(400, self._tick_fatoora)
            # مُرسِل الفواتير الإلكترونية في الخلفية — لا يفعل شيئاً ما لم
            # يُفعَّل الربط، ويُرسل المعلّق فور عودة الإنترنت
            try:
                from services.fatoora import ledger as _ft
                _ft.start_worker()
            except Exception:
                pass
            sb.addPermanentWidget(self._sb_hint)
            sb.addPermanentWidget(self._sb_clock)
            self._tick_clock()
            self._clock = QtCore.QTimer(self)
            self._clock.timeout.connect(self._tick_clock)
            self._clock.start(20_000)
            # بُني بعد `switch(0)`: يأخذ حالة الشاشة الحالية
            sb.setVisible(getattr(self, "_current_row", 0) == 0)
        except Exception:
            pass

    def _tick_clock(self):
        try:
            now = QtCore.QDateTime.currentDateTime()
            day = self._DAYS[now.date().dayOfWeek() - 1]
            self._sb_clock.setText(
                f"🕒 {day} {now.toString('dd-MM-yyyy')} · "
                f"{now.toString('hh:mm')}")
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════
    #  شريط الأوامر الموحّد (Ctrl+K)
    # ══════════════════════════════════════════════════════════════

    def _palette_static(self):
        """ما يُبحث فيه بلا استعلام: الشاشات والأسماء المفهرسة سلفاً."""
        from ui.widgets import palette as pal
        items = []
        for idx, name in sorted(getattr(self, "_screen_keys", {}).items()):
            node = self._items.get(self.screens[idx]) \
                if 0 <= idx < len(self.screens) else None
            shown = node.text(0) if node is not None else name
            hint = "" if shown == name else name
            items.append((pal.SCREEN, shown, hint, idx))
        try:
            for i in range(self.quick.count()):
                items.append((pal.ACCOUNT, self.quick.itemText(i), "",
                              self.quick.itemData(i)))
        except Exception:
            pass
        return items

    def open_palette(self):
        """يفتح نافذة البحث الموحّد — من أي شاشة وأي حقل."""
        try:
            from database.database import db as _db
            from ui.widgets import palette as pal

            def lookup(text):
                with _db(readonly=True) as conn:
                    return pal.db_lookup(conn, text)

            dlg = pal.CommandPalette(self, self._palette_static(),
                                     self._palette_pick, lookup)
            dlg.exec_()
        except Exception as e:
            err(self, e)

    def _palette_pick(self, kind, payload):
        """ينفّذ ما اختاره المستخدم من شريط الأوامر."""
        from ui.widgets import palette as pal
        try:
            if kind == pal.SCREEN:
                self.switch(int(payload))
            elif kind == pal.ACCOUNT:
                self.open_ledger(payload)
            elif kind == pal.WORK_ORDER:
                self._open_named("حركة الطقم", "open_for_wo", payload)
            elif kind == pal.INVOICE:
                self._open_named("أرشيف المستندات والطباعة",
                                 "open_for_term", payload)
        except Exception as e:
            err(self, e)

    def goto_by_name(self, name):
        """ينتقل إلى شاشة باسمها الافتراضي — للوصلات داخل الشاشات.

        يُطابَق بالاسم الافتراضي لا بالفهرس: الفهرس يتغيّر مع كل
        إضافة شاشة، وقد أفسد ترتيب القائمة مرةً من قبل.
        """
        idx = self._index_of(name)
        if idx is not None:
            self.switch(idx)
        return idx is not None

    def _index_of(self, name):
        keys = getattr(self, "_screen_keys", {})
        for idx, key in keys.items():
            if key == name:
                return idx
        for idx, key in keys.items():
            if name in key or key in name:
                return idx
        return None

    def _open_named(self, name, method, arg):
        """يفتح شاشةً باسمها ثم يستدعي دالتها بالوسيط بعد اكتمال بنائها."""
        if not self.goto_by_name(name):
            err(self, f"الشاشة «{name}» غير متاحة لهذا المستخدم")
            return

        def _run():
            try:
                idx = self._index_of(name)
                scr = self.screens[idx]
                real = getattr(scr, "real", scr)
                fn = getattr(real, method, None)
                if callable(fn):
                    fn(arg)
            except Exception as e:
                err(self, e)

        QtCore.QTimer.singleShot(0, _run)

    # ══════════════════════════════════════════════════════════════
    #  البحث السريع
    # ══════════════════════════════════════════════════════════════

    def _load_quick_index(self):
        """يبني فهرس البحث السريع: الجهات أولاً ثم بقية الحسابات.

        الجهات أولاً لأنها المقصودة في تسعة من كل عشرة أسئلة، وبقية
        الحسابات بعدها فلا يضطر أحد لفتح شجرة الحسابات ليقرأ كشفاً.
        """
        try:
            from models.accounts import list_postable
            with db(readonly=True) as conn:
                ents = conn.execute(
                    "SELECT e.name, a.code FROM entities e"
                    " JOIN accounts a ON a.id=e.account_id"
                    " WHERE e.is_deleted=0 ORDER BY e.name").fetchall()
                accs = list_postable(conn)
            seen = set()
            self.quick.blockSignals(True)
            self.quick.clear()
            for e in ents:
                if e["code"] in seen:
                    continue
                seen.add(e["code"])
                self.quick.addItem(e["name"], e["code"])
            for a in accs:
                if a["code"] in seen:
                    continue
                self.quick.addItem(f"{a['code']} — {a['name']}", a["code"])
            self.quick.setCurrentIndex(-1)
            if self.quick.lineEdit():
                self.quick.lineEdit().clear()
            self.quick.blockSignals(False)
        except Exception:
            pass          # البحث السريع رفاهية لا تُعطّل الإقلاع

    def _quick_open(self, *_):
        """يفتح كشف حساب الاسم المختار في دفتر الأستاذ."""
        try:
            code = self.quick.currentData()
            if code is None:
                return
            self.open_ledger(code)
        except Exception as e:
            err(self, e)

    def open_ledger_by_account(self, account_id):
        """Drill-down من شاشة أرصدة الأستاذ المساعد إلى دفتر أستاذ الجهة."""
        if not self.gl_screen:
            return
        with db() as conn:
            row = conn.execute("SELECT code FROM accounts WHERE id=?",
                               (account_id,)).fetchone()
        if row:
            self.open_ledger(row["code"])

    def open_ledger(self, account_code):
        """Drill-down: يُستدعى من بطاقات لوحة التحكم — يفتح دفتر الأستاذ
        العام مفلتراً جاهزاً على حساب البطاقة المضغوطة."""
        if not self.gl_screen:
            return
        self._goto(self.gl_screen)
        # الشاشة تُبنى عند الانتقال إليها، فيُؤجَّل الفتح لدورة أحداث
        # لاحقة حتى تكتمل — وإلا ضاع الحساب وظهرت «اختر الحساب».
        QtCore.QTimer.singleShot(
            0, lambda: self._open_code_now(account_code))

    def _open_code_now(self, account_code):
        """يفتح الحساب في دفتر الأستاذ بعد اكتمال بنائه."""
        try:
            scr = self.gl_screen
            real = getattr(scr, "real", scr)
            fn = getattr(real, "open_for_code", None)
            if callable(fn):
                fn(account_code)
        except Exception:
            pass

    def open_entry_in_ledger(self, entry_id):
        """يُستدعى من أداة المطابقة: يفتح دفتر الأستاذ على أول حساب
        يمسّه القيد المختل لمعالجته مباشرة."""
        if not self.gl_screen:
            return
        with db() as conn:
            row = conn.execute(
                "SELECT a.code FROM journal_lines l"
                " JOIN accounts a ON a.id=l.account_id"
                " WHERE l.entry_id=? ORDER BY l.id LIMIT 1",
                (entry_id,)).fetchone()
        if row:
            self.open_ledger(row["code"])

    def do_backup(self):
        try:
            backup.backup_now()
            from services import storage
            n = len(storage.list_backups())
            info(self, f"تم إنشاء نسخة احتياطية على هذا الجهاز.\n\n"
                       f"المحفوظ: {n} من آخر {storage.KEEP_LAST} نسخة — "
                       f"وتسترجع أيّها من سهم زر «💾 نسخة».")
        except Exception as e:
            err(self, e)

    def open_backups(self):
        try:
            from ui.backups_dialog import open_dialog
            open_dialog(self, self.user)
        except Exception as e:
            err(self, e)

    # ══════════════════════════════════════════════════════════════
    #  إيقاف البرنامج من الإدارة — الشيء الوحيد الذي يأتي من السحابة
    # ══════════════════════════════════════════════════════════════

    def _start_account_guard(self):
        """يسأل دورياً: هل ما زال الحساب نشطاً؟ — لحسابات المصانع."""
        if self.is_super or not self.user.get("username"):
            return
        try:
            from services import licensing
            self._guard = licensing.AccountGuard(
                self.user["username"],
                lambda: QtCore.QMetaObject.invokeMethod(
                    self, "_on_suspended", QtCore.Qt.QueuedConnection))
            self._guard.start()
        except Exception:
            self._guard = None

    @QtCore.pyqtSlot()
    def _on_suspended(self):
        """أوقفت الإدارة الحساب: يُحفظ كل شيء ثم يُغلق البرنامج."""
        try:
            from services import storage
            storage.make_backup("exit")
        except Exception:
            pass
        QtWidgets.QMessageBox.critical(
            self, "تم إيقاف البرنامج",
            "أوقفت الإدارة هذا الحساب — سيُغلق البرنامج الآن.\n\n"
            "بياناتك محفوظة على هذا الجهاز كما هي ولم يُحذف منها شيء.\n"
            "للتفعيل يرجى مراجعة الإدارة.")
        self._suspended = True
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.quit()

    def _start_models_link(self):
        try:
            import threading
            from services import models_web
            threading.Thread(target=models_web.autostart, daemon=True,
                             name="models-link").start()
        except Exception:
            pass

    def closeEvent(self, event):
        # ضمان أخير: يُحفظ ترتيب القائمة وأسماؤها قبل الإغلاق
        try:
            self._save_nav_layout()
        except Exception:
            pass
        try:
            # خادم صور الموديلات يُغلق مع النظام — فلا يبقى منفذ
            # مفتوحاً بعد الخروج.
            from services import photo_server
            photo_server.stop()
        except Exception:
            pass
        try:
            g = getattr(self, "_guard", None)
            if g is not None:
                g.stop()
        except Exception:
            pass
        try:
            # نسخة الإغلاق: لا تُحفظ إن لم يتغيّر شيء منذ آخر نسخة
            from services import storage
            storage.make_backup("exit")
        except Exception:
            pass
        try:
            with db() as conn:
                log_action(conn, self.user["username"], "logout", "users",
                           self.user["id"], "")
        except Exception:
            pass
        event.accept()
