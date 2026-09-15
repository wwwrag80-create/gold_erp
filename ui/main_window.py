# -*- coding: utf-8 -*-
"""لوحة التحكم: شريط جانبي RTL + شاشة لكل عملية حسب صلاحية المستخدم.
تبدأ بلوحة تحكم تفاعلية (بطاقات قابلة للنقر) تتيح Drill-down إلى دفتر
الأستاذ العام الموحّد لأي حساب في الشجرة."""
import json

from PyQt5 import QtCore, QtWidgets

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
from ui.widgets.common import ask, err, info


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

            # العمليات اليومية تبقى ظاهرة، والشاشات الإدارية والتقارير
            # تُجمَّع تحت قائمة رئيسية واحدة لتقليل الازدحام.
            groups = [
                (None, [
                    ("دفتر الأستاذ العام", self.gl_screen),
                    ("تقارير مبيعات وإنتاج المصنع", Lazy(lambda: FactoryReportsScreen(user), "تقارير مبيعات وإنتاج المصنع")),
                    ("حركة الطقم", Lazy(lambda: ItemHistoryScreen(user), "حركة الطقم")),
                    ("دليل الموديلات", Lazy(lambda: ModelsScreen(user), "دليل الموديلات")),
                ]),
                (None, [
                    ("لوحة التحكم", dashboard),
                    ("الأرصدة الافتتاحية المخزنية", self.opening_screen),
                    ("الإنتاج والتوريد", self.production_screen),
                    ("المبيعات والمرتجعات والتحويلات", self.sales_screen),
                    ("السندات والخصومات", self.vouchers_screen),
                    ("الصب والتصفية", self.melting_screen),
                    ("تسوية فواقد الورشة", Lazy(lambda: WorkshopLossesScreen(user), "تسوية فواقد الورشة")),
                    ("حسابات الورشة", Lazy(lambda: WorkshopAccountsScreen(user), "حسابات الورشة")),
                    ("التسكير (تسعير الذهب)", self.fixing_screen),
                    ("المشتريات والأصول", self.purchases_screen),
                    ("القيود اليومية", self.journal_screen),
                ]),
                ("الإدارة والتقارير", [
                    ("دليل الحسابات (شجرة الحسابات)", self.coa_screen),
                    ("التكويد الموحّد لجهات التعامل", self.entities_screen),
                    ("أرصدة الأستاذ المساعد", self.subledger_screen),
                    ("الجرد الفعلي", self.stocktake_screen),
                    ("إدارة وتحويل العمليات", Lazy(lambda: OperationsScreen(user), "إدارة وتحويل العمليات")),
                    ("سجل العمليات", self.txlog_screen),
                    ("المطابقة وتسوية الفروقات", self.recon_screen),
                    ("أرشيف المستندات والطباعة", self.archive_screen),
                    ("الرواتب والموظفون", self.payroll_screen),
                    ("تكاليف ورواتب قسم التصنيع", self.mfg_screen),
                    ("إنزال رواتب الموظفين (نهاية الشهر)", Lazy(lambda: PayrollRunScreen(user), "إنزال رواتب الموظفين (نهاية الشهر)")),
                    ("الإقرار الضريبي (VAT)", Lazy(lambda: VatReturnScreen(user), "الإقرار الضريبي (VAT)")),
                ]),
                ("التقارير الختامية والفترات المالية", [
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

        header = QtWidgets.QFrame()
        header.setObjectName("header")
        h = QtWidgets.QHBoxLayout(header)
        h.setContentsMargins(16, 10, 16, 10)
        t = QtWidgets.QLabel(config.APP_NAME)
        t.setObjectName("headerTitle")
        role_label = ("المدير العام" if self.is_super
                      else f"مصنع: {tenant.factory_name()}")
        u = QtWidgets.QLabel(
            f"المستخدم: {user.get('full_name') or user['username']} — "
            f"{role_label}")
        u.setObjectName("headerUser")
        btn_backup = QtWidgets.QPushButton("نسخة احتياطية الآن")
        btn_backup.clicked.connect(self.do_backup)
        h.addWidget(t)
        h.addStretch(1)
        h.addWidget(u)
        btn_reset_nav = QtWidgets.QPushButton("↺ ترتيب القائمة الافتراضي")
        btn_reset_nav.setVisible(True)
        btn_reset_nav.setObjectName("ghost")
        btn_reset_nav.setToolTip(
            "القائمة الجانبية قابلة للسحب والإفلات وإعادة التسمية — "
            "هذا الزر يعيدها لترتيبها الأصلي")
        btn_reset_nav.clicked.connect(self.reset_nav_layout)
        h.addWidget(btn_reset_nav)
        btn_update = QtWidgets.QPushButton("⬆ التحديثات")
        btn_update.setToolTip(
            "تحقّق من التحديثات عبر الإنترنت، أو ثبّت حزمة محفوظة")
        btn_update.clicked.connect(self.do_update)
        self.btn_update = btn_update
        # فحص صامت عند الإقلاع: يضيء الزر إن وُجد تحديث
        try:
            from services import update_channel
            update_channel.start_background_check(
                delay=8.0,
                on_done=lambda st: QtCore.QTimer.singleShot(
                    0, self._on_update_checked))
        except Exception:
            pass
        h.addWidget(btn_update)
        h.addWidget(btn_backup)

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

        # شاشة الترحيب: مساحة فارغة يتوسّطها شعار جاديت (الفهرس 0)
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
        for group_name, items in groups:
            parent = None
            if group_name:
                parent = QtWidgets.QTreeWidgetItem(self.sidebar, [group_name])
                parent.setData(0, QtCore.Qt.UserRole, -1)
                parent.setFlags(parent.flags() | QtCore.Qt.ItemIsEditable)
                f = parent.font(0)
                f.setBold(True)
                parent.setFont(0, f)
            for name, w in items:
                idx = len(self.screens)
                node = (QtWidgets.QTreeWidgetItem(parent, [name]) if parent
                        else QtWidgets.QTreeWidgetItem(self.sidebar, [name]))
                node.setData(0, QtCore.Qt.UserRole, idx)
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
            data = [self._nav_node(self.sidebar.topLevelItem(i))
                    for i in range(self.sidebar.topLevelItemCount())]
            path = self._nav_layout_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception:
            pass          # تخصيص الواجهة لا يعطّل النظام أبداً

    def _restore_nav_layout(self):
        """يعيد بناء الشجرة من ملف الإعدادات إن وُجد.

        يُطابَق كل عنصر بفهرس شاشته (idx)، فلو حُذفت شاشة أو أُضيفت
        جديدة يبقى الباقي سليماً وتُلحق الشاشات الجديدة في النهاية.
        """
        path = self._nav_layout_path()
        if not path.exists():
            return
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
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

            # خريطة الاسم ← الفهرس الحالي.
            # الملف المحفوظ يخزّن فهرساً رقمياً، لكن إضافة أو حذف أي
            # شاشة تُزيح كل الفهارس فتُفتح شاشة غير المقصودة. لذلك
            # نطابق بالاسم أولاً — وهو ثابت — ونعود للفهرس عند تطابقه.
            by_text = {}
            for i, t in current.items():
                by_text.setdefault(t, i)

            def build(nodes, parent):
                for n in nodes:
                    idx = n.get("idx")
                    text = n.get("text", "")
                    if idx is not None and idx >= 0:
                        # ══ مطابقة الشاشة المحفوظة ══
                        # الاسم أولاً (يصمد أمام إعادة الترتيب)، ثم
                        # الفهرس المحفوظ إن كان ما يزال متاحاً.
                        # **الخلل السابق**: الشاشة المُعاد تسميتها لا
                        # يطابق اسمها المحفوظ أي اسم أصلي، فكانت
                        # تُسقَط كلياً — فيضيع الترتيب والتسمية معاً.
                        real = by_text.get(text)
                        if real is None or real in used:
                            # الاسم مُعاد تسميته أو مستهلك: نعتمد
                            # الفهرس المحفوظ ما دام حرّاً وصالحاً
                            if idx in current and idx not in used:
                                real = idx
                            else:
                                real = None
                        if real is None or real in used:
                            continue
                        idx = real
                        used.add(idx)
                    it = QtWidgets.QTreeWidgetItem([text])
                    it.setData(0, QtCore.Qt.UserRole,
                               idx if idx is not None else -1)
                    it.setFlags(it.flags() | QtCore.Qt.ItemIsEditable)
                    if parent is None:
                        self.sidebar.addTopLevelItem(it)
                    else:
                        parent.addChild(it)
                    build(n.get("children", []), it)
                    it.setExpanded(bool(n.get("expanded", True)))

            self.sidebar.clear()
            build(saved, None)
            # أي شاشة جديدة لم تكن في الملف تُلحق في النهاية
            for idx, text in sorted(current.items()):
                if idx in used:
                    continue
                it = QtWidgets.QTreeWidgetItem([text])
                it.setData(0, QtCore.Qt.UserRole, idx)
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
