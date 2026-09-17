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
from ui.reconciliation_screen import ReconciliationScreen
from ui.entities_screen import EntitiesScreen
from ui.fixing_screen import FixingScreen
from ui.general_ledger_screen import GeneralLedgerScreen
from ui.journal_screen import JournalScreen
from ui.melting_screen import MeltingScreen
from ui.payroll_run_screen import PayrollRunScreen
from ui.payroll_screen import PayrollScreen
from ui.opening_balances_screen import OpeningBalancesScreen
from ui.mfg_costs_screen import MfgCostsScreen
from ui.operations_screen import OperationsScreen
from ui.super_admin_screen import SuperAdminScreen
from ui.opening_stock_screen import OpeningStockScreen
from ui.production_screen import ProductionScreen
from ui.purchases_screen import PurchasesScreen
from ui.reports.balance_sheet_screen import BalanceSheetScreen
from ui.reports.trial_balance_screen import TrialBalanceScreen
from ui.reports.factory_reports_screen import FactoryReportsScreen
from ui.reports.income_statement import IncomeStatementScreen
from ui.reports.khazina_report_screen import KhazinaReportScreen
from ui.reports.vat_return_screen import VatReturnScreen
from ui.reports.year_end_screen import YearEndScreen
from ui.reports.aging_screen import AgingScreen
from ui.reports.day_close_screen import DayCloseScreen
from ui.reports.integrity_screen import IntegrityScreen
from ui.item_history_screen import ItemHistoryScreen
from ui.models_screen import ModelsScreen
from ui.sales_analytics_screen import SalesAnalyticsScreen
from ui.sales_screen import SalesScreen
from ui.workshop_accounts_screen import WorkshopAccountsScreen
from ui.workshop_losses_screen import WorkshopLossesScreen
from ui.stocktake_screen import StocktakeScreen
from ui.subledger_screen import SubLedgerScreen
from ui.transaction_log_screen import TransactionLogScreen
from ui.vouchers_screen import VouchersScreen
from services import karat_view as kv
from ui import theme
from ui.widgets.common import ElidedLabel, ask, err, info, search_combo

# دور مخصّص يحمل المفتاح الثابت لكل عنصر في القائمة
NAV_KEY_ROLE = QtCore.Qt.UserRole + 1

# ══ إصدار ترتيب القائمة ══
# الترتيب المحفوظ على جهاز المستخدم يُطابَق بمفتاح كل شاشة (اسمها
# الافتراضي). فحين يتغيّر الترتيب المعتمد نفسه — أو تُعاد تسمية شاشات
# — يصير المحفوظ ترتيباً قديماً يحجب الجديد: الشاشات المعاد تسميتها
# تُلحق في ذيل القائمة بأسمائها الجديدة، ويبقى الترتيب القديم فوقها.
# رفع هذا الرقم يُهمل المحفوظ مرةً واحدة فيظهر الترتيب الجديد كما هو،
# ثم يُحفظ تخصيص المستخدم فوقه من جديد.
NAV_VERSION = 2


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.gl_screen = None
        # صلاحية الحساب السحابي: super_admin يرى كل شيء، و factory
        # يرى نظامه المحاسبي وحده بلا أي شاشة إدارية.
        self.is_super = bool(user.get("is_super")
                             or user.get("role") == "super_admin")
        self.setWindowTitle(config.APP_NAME)
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
            self.melting_screen = Lazy(lambda: MeltingScreen(user), "melting_screen")
            self.stocktake_screen = Lazy(lambda: StocktakeScreen(user), "stocktake_screen")
            self.fixing_screen = Lazy(lambda: FixingScreen(user), "fixing_screen")
            self.purchases_screen = Lazy(lambda: PurchasesScreen(user), "purchases_screen")
            self.payroll_screen = Lazy(lambda: PayrollScreen(user), "payroll_screen")
            self.journal_screen = Lazy(lambda: JournalScreen(user), "journal_screen")
            self.txlog_screen = Lazy(lambda: TransactionLogScreen(user), "txlog_screen")
            self.recon_screen = Lazy(lambda: ReconciliationScreen(
                user, on_open_entry=self.open_entry_in_ledger), "recon_screen")
            self.archive_screen = Lazy(lambda: DocumentArchiveScreen(
                user, on_open_ledger=self.open_ledger), "archive_screen")

            # ══════════════════════════════════════════════════════
            #  ترتيب القائمة — اثنتا عشرة شاشة يومية ظاهرة، وما عداها
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
                    ("سندات قبض/صرف", self.vouchers_screen),
                    ("التسكيرات", self.fixing_screen),
                    ("المشتريات", self.purchases_screen),
                    ("القيود اليومية", self.journal_screen),
                    ("تقارير مبيعات وإنتاج المصنع", Lazy(lambda: FactoryReportsScreen(user), "تقارير مبيعات وإنتاج المصنع")),
                    ("أعمار الديون (30/60/90)",
                     Lazy(lambda: AgingScreen(user), "أعمار الديون")),
                ]),
                ("الإدارة والتقارير", [
                    ("الإغلاق اليومي", Lazy(lambda: DayCloseScreen(user),
                                            "الإغلاق اليومي")),
                    ("دليل الحسابات (شجرة الحسابات)", self.coa_screen),
                    ("التكويد الموحّد لجهات التعامل", self.entities_screen),
                    ("أرصدة الأستاذ المساعد", self.subledger_screen),
                    ("الأرصدة الافتتاحية المخزنية", self.opening_screen),
                    ("الصب والتصفية", self.melting_screen),
                    ("تسوية فواقد الورشة", Lazy(lambda: WorkshopLossesScreen(user), "تسوية فواقد الورشة")),
                    ("حسابات الورشة", Lazy(lambda: WorkshopAccountsScreen(user), "حسابات الورشة")),
                    ("الجرد الفعلي", self.stocktake_screen),
                    ("إدارة وتحويل العمليات", Lazy(lambda: OperationsScreen(user), "إدارة وتحويل العمليات")),
                    ("سجل العمليات", self.txlog_screen),
                    ("سلامة السجل (بصمة القيود)",
                     Lazy(lambda: IntegrityScreen(user),
                          "سلامة السجل (بصمة القيود)")),
                    ("المطابقة وتسوية الفروقات", self.recon_screen),
                    ("أرشيف المستندات والطباعة", self.archive_screen),
                    ("الرواتب والموظفون", self.payroll_screen),
                    ("تكاليف ورواتب قسم التصنيع", self.mfg_screen),
                    ("إنزال رواتب الموظفين (نهاية الشهر)", Lazy(lambda: PayrollRunScreen(user), "إنزال رواتب الموظفين (نهاية الشهر)")),
                    ("الإقرار الضريبي (VAT)", Lazy(lambda: VatReturnScreen(user), "الإقرار الضريبي (VAT)")),
                    ("ميزان المراجعة", Lazy(lambda: TrialBalanceScreen(user), "ميزان المراجعة")),
                    ("الميزانية العمومية", Lazy(lambda: BalanceSheetScreen(user), "الميزانية العمومية")),
                    ("تهيئة أرصدة أول المدة (تاريخ القطع)", Lazy(lambda: OpeningBalancesScreen(user), "تهيئة أرصدة أول المدة (تاريخ القطع)")),
                    ("الإقفال السنوي", Lazy(lambda: YearEndScreen(user), "الإقفال السنوي")),
                ]),
            ]

            # سجل التعديل الشامل: لكل نوع مستند شاشتُه ودالة التحميل
            self.edit_targets = {
                "invoices": (self.sales_screen, "load_invoice"),
                "vouchers": (self.vouchers_screen, "load_document"),
                "melting_ops": (self.melting_screen, "load_document"),
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
                ("النظام السحابي وإدارة المصانع",
                 Lazy(lambda: SuperAdminScreen(user),
                      "النظام السحابي وإدارة المصانع")),
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
        h = QtWidgets.QHBoxLayout(header)
        h.setContentsMargins(14, 8, 14, 8)
        h.setSpacing(10)

        # العنوان واسم المستخدم يُقصّان عند الضيق ولا يفرضان عرضاً
        t = ElidedLabel(config.APP_NAME, minimum=90)
        t.setObjectName("headerTitle")

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

        role_label = ("المدير العام" if self.is_super
                      else f"مصنع: {tenant.factory_name()}")
        u = ElidedLabel(
            f"{user.get('full_name') or user['username']} — {role_label}",
            minimum=110)
        u.setObjectName("headerUser")

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
        btn_backup = QtWidgets.QPushButton("💾 نسخة")
        btn_backup.setToolTip("ينشئ نسخة احتياطية كاملة الآن")
        btn_backup.clicked.connect(self.do_backup)
        # فحص صامت عند الإقلاع: يضيء الزر إن وُجد تحديث
        try:
            from services import update_channel
            update_channel.start_background_check(
                delay=8.0,
                on_done=lambda st: QtCore.QTimer.singleShot(
                    0, self._on_update_checked))
        except Exception:
            pass
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

        # الشريط الفرعي: عنوان الشاشة الحالية وزر إغلاقها. يُبنى قبل
        # الشريط الجانبي لأن switch() تستخدم self.crumb و self.btn_close.
        self.crumb = QtWidgets.QLabel(config.COMPANY_NAME)
        self.crumb.setObjectName("crumb")
        self.btn_close = QtWidgets.QPushButton("✖  إغلاق الشاشة")
        self.btn_close.setObjectName("closeBtn")
        self.btn_close.clicked.connect(self._close_screen)
        self.btn_close.setVisible(False)
        subbar = QtWidgets.QFrame()
        subbar.setObjectName("subbar")
        sb = QtWidgets.QHBoxLayout(subbar)
        sb.setContentsMargins(16, 6, 16, 6)
        sb.addWidget(self.crumb)
        sb.addStretch(1)
        # مساحة أدوات تخصّ الشاشة الحالية: تضع كل شاشة أزرارها العامة
        # هنا بجوار «إغلاق الشاشة» بدل ازدحام مساحة العمل بها.
        self.screen_tools = QtWidgets.QWidget()
        self._tools_lay = QtWidgets.QHBoxLayout(self.screen_tools)
        self._tools_lay.setContentsMargins(0, 0, 0, 0)
        self._tools_lay.setSpacing(6)
        sb.addWidget(self.screen_tools)
        sb.addWidget(self.btn_close)

        # شاشة الترحيب (الفهرس 0): مساحة يتوسّطها شعار المصنع. جُرّبت
        # مكانها شاشةُ أرقامٍ حيّة فلم تُرَد — والشعار أوضح وأسرع،
        # والأرقام لها شاشاتها (الإغلاق اليومي · لوحة التحكم).
        self.welcome = WelcomeScreen(user)

        self.sidebar = QtWidgets.QTreeWidget()
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

        # الشريط الجانبي ثابت على اليمين دائماً (RTL يضعه يميناً).
        # عمود جانبي: شجرة التنقل ثم شريط سعر الأونصة الحي أسفلها
        self.gold_bar = GoldPriceBar()
        self.side_panel = QtWidgets.QWidget()
        self.side_panel.setFixedWidth(260)
        sp = QtWidgets.QVBoxLayout(self.side_panel)
        sp.setContentsMargins(0, 0, 0, 0)
        sp.setSpacing(0)
        sp.addWidget(self.sidebar, 1)
        sp.addWidget(self.gold_bar)

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

    def _close_screen(self):
        """يغلق الشاشة الحالية ويعود لواجهة الشعار الفارغة."""
        self.switch(0)

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
            if "السحابي وإدارة المصانع" in label or cls == "SuperAdminScreen":
                from ui.super_admin_screen import SuperAdminScreen as _S
                return _S.request_access(self)
        except Exception:
            pass
        return True

    def switch(self, row):
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
        # أغلق الشاشة السابقة (لا نُغلق شاشة الترحيب فهي خفيفة)
        if prev != row and prev > 0:
            try:
                old = self.screens[prev]
                rel = getattr(old, "release", None)
                if callable(rel):
                    rel()
            except Exception:
                pass
        screen = self.screens[row]
        node = self._items.get(screen)
        self.crumb.setText(
            node.text(0) if node is not None else config.COMPANY_NAME)
        # إخفاء الشريط الجانبي تماماً عند فتح أي شاشة فرعية لتتوسّع
        # لكامل عرض النافذة، وإظهاره عند العودة لشاشة الترحيب.
        is_sub = row != 0
        # قد تُستدعى switch() قبل إنشاء العمود الجانبي أثناء التهيئة
        panel = getattr(self, "side_panel", None) or self.sidebar
        panel.setVisible(not is_sub)
        self.btn_close.setVisible(is_sub)      # زر الإغلاق في كل شاشة فرعية
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
        QtWidgets.QMessageBox.information(
            self, "تم التحديث",
            f"اكتمل التحديث إلى الإصدار {res['version']}.\n"
            f"ملفات مُحدَّثة: {res['files']}\n\n"
            f"أعد تشغيل النظام لتفعيل التحديث.")

    def do_update(self):
        """يرفع حزمة تحديث على النسخة القائمة — بضمانات كاملة."""
        try:
            from services import update_channel, updater
            # ══ أولاً: التحقق عبر الإنترنت ══
            online = None
            try:
                st = update_channel.status()
                online = (st.get("info") if st.get("available")
                          else update_channel.check())
                if online and not online.get("newer"):
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

            info2 = (f"اكتمل التحديث إلى الإصدار {res['version']}.\n"
                     f"ملفات مُحدَّثة: {res['files']}\n\n"
                     f"أعد تشغيل النظام لتفعيل التحديث.")
            QtWidgets.QMessageBox.information(self, "تم التحديث", info2)
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
                       f"تحويل عرض النظام كله إلى عيار {k}؟\n\n"
                       "• كل الأوزان تُعرض وتُدخل بعيار "
                       f"{k} في جميع الشاشات والتقارير.\n"
                       "• المبالغ النقدية لا تتغيّر إطلاقاً.\n"
                       "• القيد يبقى مخزَّناً بمكافئ عيار 18، فلا يتغيّر "
                       "رقم واحد في قاعدة البيانات والتبديل قابل "
                       "للرجوع.\n\n"
                       "أي إدخال لم يُرحَّل في الشاشة المفتوحة سيُفقد."):
                idx = self.karat_box.findData(cur)
                self.karat_box.blockSignals(True)
                if idx >= 0:
                    self.karat_box.setCurrentIndex(idx)
                self.karat_box.blockSignals(False)
                return
            kv.set_active(k, self.user.get("username"))
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
            info(self, f"النظام يعرض الآن كل الأوزان بعيار {k}.")
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

        menu.addSeparator()
        a_find = menu.addAction("🔍 بحث موحّد…        Ctrl+K")
        a_find.triggered.connect(self.open_palette)
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

    def _set_theme(self, name):
        try:
            theme.set_theme(name, self.user.get("username"))
            theme.apply(QtWidgets.QApplication.instance(), theme=name)
        except Exception as e:
            err(self, e)

    def _set_scale(self, value):
        try:
            theme.set_scale(value, self.user.get("username"))
            theme.apply(QtWidgets.QApplication.instance(), scale=value)
        except Exception as e:
            err(self, e)

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
            path = backup.backup_now()
            info(self, f"تم إنشاء نسخة احتياطية:\n{path}")
        except Exception as e:
            err(self, e)

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
            backup.backup_now()
        except Exception:
            pass
        try:
            with db() as conn:
                log_action(conn, self.user["username"], "logout", "users",
                           self.user["id"], "")
        except Exception:
            pass
        event.accept()
