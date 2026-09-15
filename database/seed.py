# -*- coding: utf-8 -*-
"""البيانات الافتتاحية: شجرة الحسابات (5 مستويات)، مراكز التكلفة، المستخدمون.
كل حساب يحمل: طبيعته (مدين/دائن) ونوع الرصيد الذي يقبله (نقد/ذهب/كلاهما)."""
from database.database import db
from services.auth import hash_password

# (code, name, type, parent_code, is_postable, balance_type)
ACCOUNTS = [
    # ═══ 1) الأصول ═══
    ("1000", "الأصول", "asset", None, 0, "both"),
    ("1010", "الأصول المتداولة — النقدية وشبه النقدية", "asset", "1000", 0, "cash"),
    ("1400", "الصندوق الرئيسي", "asset", "1010", 1, "cash"),
    ("1410", "صندوق المصروفات النثرية", "asset", "1010", 1, "cash"),
    ("1500", "البنك", "asset", "1010", 1, "cash"),
    ("1020", "الأصول المتداولة — الذهب والمخازن", "asset", "1000", 0, "gold"),
    ("1100", "خزينة التصنيع (تشغيل — أوزان ذهب وفصوص)", "asset", "1020", 1, "gold"),
    ("1150", "مخزون الفصوص والأحجار", "asset", "1020", 1, "gold"),
    ("1200", "الذهب المشغول (بضاعة تامة — أطقم)", "asset", "1020", 1, "gold"),
    ("1300", "صناديق الكسر والذهب الصافي", "asset", "1020", 0, "gold"),
    ("1310", "صندوق الكسر (18 · 21 · 22 · 24)", "asset", "1300", 1, "gold"),

    ("1350", "الصهر والتصفية (ذهب تحت التصفية)", "asset", "1020", 1, "gold"),
    # المسترجع من التصفية: ذهب عاد للمصنع بعد تصفية الفواقد.
    # أصل متداول — يُصنَّف مع مخزون الذهب (1020) لا مع المصروفات،
    # لأن الفاقد أُثبت مصروفاً عند وقوعه، وما يعود منه أصلٌ مستردّ.
    # حساب تجميعي تُضاف تحته فروع بحسب مصدر الاسترجاع.
    ("1360", "مسترجع من التصفية", "asset", "1020", 0, "gold"),
    ("1250", "مخزون تسويات أوزان الطقوم", "asset", "1020", 1, "gold"),
    ("1030", "الأصول المتداولة — الذمم المدينة", "asset", "1000", 0, "both"),
    ("1600", "إجمالي العملاء (نقد وذهب)", "asset", "1030", 0, "both"),
    ("1650", "إجمالي الجهات الأخرى (مدينون آخرون)", "asset", "1030", 0, "both"),
    ("1950", "سلف الموظفين", "asset", "1030", 1, "cash"),
    ("1970", "سلف عمال التصنيع", "asset", "1030", 1, "cash"),
    ("1960", "عهد الموظفين", "asset", "1030", 1, "cash"),
    ("1700", "الأصول الثابتة", "asset", "1000", 1, "cash"),
    ("1710", "المكائن والمعدات", "asset", "1700", 1, "cash"),
    ("1720", "الأثاث والتجهيزات", "asset", "1700", 1, "cash"),
    ("1730", "السيارات", "asset", "1700", 1, "cash"),
    ("1740", "أجهزة الكمبيوتر", "asset", "1700", 1, "cash"),
    ("1900", "ضريبة القيمة المضافة — المدخلات", "asset", "1000", 1, "cash"),
    # ═══ 2) الخصوم ═══
    ("2000", "الخصوم والالتزامات", "liability", None, 0, "both"),
    ("2010", "الخصوم المتداولة", "liability", "2000", 0, "both"),
    ("2300", "إجمالي الموردين", "liability", "2010", 0, "both"),
    ("2250", "رواتب العمال المستحقة", "liability", "2010", 0, "cash"),
    ("2200", "مستحقات الموظفين (الرواتب والأجور المستحقة)", "liability",
     "2010", 0, "cash"),
    ("2900", "تسويات مباشرة على أرصدة الجهات", "liability", "2010", 1, "cash"),
    ("2020", "الالتزامات الضريبية", "liability", "2000", 0, "cash"),
    ("2100", "ضريبة القيمة المضافة — المخرجات", "liability", "2020", 1, "cash"),
    ("2150", "حساب تسوية ضريبة القيمة المضافة", "liability", "2020", 1, "cash"),
    # ═══ 3) حقوق الملكية ═══
    ("3000", "حقوق الملكية", "equity", None, 0, "both"),
    ("3100", "حقوق الشركاء", "equity", "3000", 0, "both"),
    ("3110", "رأس مال الشركاء", "equity", "3100", 1, "both"),
    ("3120", "جاري الشركاء (المسحوبات والتوزيعات)", "equity", "3100", 1, "both"),
    ("3200", "الأرباح المحتجزة", "equity", "3000", 1, "both"),
    ("3210", "أرباح وخسائر العام الحالي", "equity", "3000", 1, "both"),
    ("3900", "الأرصدة الافتتاحية للتسوية", "equity", "3000", 1, "both"),
    # ═══ 4) الإيرادات ═══
    ("4000", "الإيرادات", "revenue", None, 0, "cash"),
    ("4100", "إيرادات الأجور والمصنعية", "revenue", "4000", 1, "cash"),
    ("4110", "إيرادات مبيعات ذهب", "revenue", "4000", 1, "gold"),
    ("4120", "إيرادات مبيعات أجور", "revenue", "4000", 1, "cash"),
    ("4900", "مردودات المبيعات", "revenue", "4000", 0, "both"),
    ("4910", "مردودات مبيعات ذهب", "revenue", "4900", 1, "gold"),
    ("4920", "مردودات مبيعات أجور", "revenue", "4900", 1, "cash"),
    ("4200", "إيرادات أخرى / عرضية (تصفية التراب والشفط)", "revenue", "4000", 1, "cash"),
    ("4300", "أرباح فروقات الجرد والتسويات", "revenue", "4000", 1, "both"),
    # ═══ 5) المصروفات ═══
    ("5000", "المصروفات", "expense", None, 0, "both"),
    ("5050", "تكاليف التشغيل المباشرة", "expense", "5000", 0, "both"),
    ("5100", "خسائر تشغيل الذهب", "expense", "5050", 0, "gold"),
    ("5110", "فواقد الورشة", "expense", "5100", 0, "gold"),
    ("5111", "فاقد البوليش", "expense", "5110", 1, "gold"),
    ("5112", "فاقد الصب", "expense", "5110", 1, "gold"),
    ("5113", "فاقد الكاستنج", "expense", "5110", 1, "gold"),
    ("5114", "فاقد التلميع النهائي", "expense", "5110", 1, "gold"),
    ("5115", "فاقد الالترا بوليش", "expense", "5110", 1, "gold"),
    ("5120", "الفاقد الفني للصب (الصهر والتصفية)", "expense", "5100", 1, "gold"),
    ("5130", "خسائر فروقات الجرد — الذهب المشغول", "expense", "5100", 1, "gold"),
    ("5150", "تكلفة مبيعات الذهب (وزناً)", "expense", "5100", 1, "gold"),
    ("5500", "مصروفات تشغيلية", "expense", "5050", 1, "cash"),
    ("5510", "مصروف مواد التشغيل والجلي", "expense", "5050", 1, "cash"),
    ("5700", "مصروف الرواتب والأجور", "expense", "5050", 1, "cash"),
    ("5710", "مصروف رواتب عمال التصنيع", "expense", "5050", 1, "cash"),
    ("5800", "المصاريف الإدارية والعمومية", "expense", "5000", 0, "cash"),
    ("5810", "الإيجار", "expense", "5800", 1, "cash"),
    ("5820", "الكهرباء والماء", "expense", "5800", 1, "cash"),
    ("5830", "الصيانة", "expense", "5800", 1, "cash"),
    ("5840", "الرسوم والتراخيص", "expense", "5800", 1, "cash"),
    ("5850", "مصاريف الضيافة", "expense", "5800", 1, "cash"),
    ("5900", "مصروفات أخرى", "expense", "5000", 0, "both"),
    ("5200", "خصم مسموح به نقداً", "expense", "5900", 1, "cash"),
    ("5300", "خصم مسموح به وزناً", "expense", "5900", 1, "gold"),
    ("5600", "فروقات الصافي", "expense", "5900", 1, "cash"),
    # ═══ 6) حسابات وسيطة ═══
    ("6000", "حسابات وسيطة", "bridge", None, 0, "both"),
    ("6100", "مركز التسكير (ذهب ↔ نقد)", "bridge", "6000", 1, "both"),
]

CREDIT_TYPES = ("liability", "equity", "revenue")


def _nature(acc_type):
    return "credit" if acc_type in CREDIT_TYPES else "debit"


USERS = [  # (اسم الدخول، كلمة المرور، الاسم، الدور)
    ("admin", "admin", "المدير العام", "accountant"),
    ("sales", "sales", "موظف المبيعات", "sales"),
]


def seed_initial_data() -> None:
    with db() as conn:
        if conn.execute("SELECT COUNT(*) c FROM accounts").fetchone()["c"]:
            return  # سبق التأسيس
        ids = {}
        for code, name, typ, parent, postable, bal in ACCOUNTS:
            cur = conn.execute(
                "INSERT INTO accounts(code,name,type,parent_id,is_postable,"
                "nature,balance_type) VALUES(?,?,?,?,?,?,?)",
                (code, name, typ, ids.get(parent), postable, _nature(typ), bal))
            ids[code] = cur.lastrowid
        for u, p, full, role in USERS:
            conn.execute(
                "INSERT INTO users(username,password_hash,full_name,role) VALUES(?,?,?,?)",
                (u, hash_password(p), full, role))


# ترقية قواعد البيانات القائمة: تُضاف الحسابات الناقصة فقط، وتُعاد هيكلة
# الآباء للحسابات التي انتقلت لمجموعات جديدة (دون أي مساس بالأرصدة).
REPARENT = {
    "1400": "1010", "1410": "1010", "1500": "1010",
    "1100": "1020", "1150": "1020", "1200": "1020", "1250": "1020",
    "1300": "1020",
    "1600": "1030", "1650": "1030", "1950": "1030", "1970": "1030", "1960": "1030",
    "2300": "2010", "2200": "2010", "2100": "2020", "2150": "2020",
    "5100": "5050", "5500": "5050", "5510": "5050", "5700": "5050",
    "5200": "5900", "5300": "5900", "5600": "5900",
}

RENAMES = {
    "1400": "الصندوق الرئيسي",
    "1250": "مخزون تسويات أوزان الطقوم",
    "1100": "خزينة التصنيع (تشغيل — أوزان ذهب وفصوص)",
    "1200": "الذهب المشغول (بضاعة تامة — أطقم)",
    "1300": "صناديق الكسر والذهب الصافي",

    "1350": "الصهر والتصفية (ذهب تحت التصفية)",
    "1360": "مسترجع من التصفية",
    "2200": "مستحقات الموظفين (الرواتب والأجور المستحقة)",
    "2900": "تسويات مباشرة على أرصدة الجهات",
    "1600": "إجمالي العملاء (نقد وذهب)",
    "6100": "مركز التسكير (ذهب ↔ نقد)",
    "1650": "إجمالي الجهات الأخرى (مدينون آخرون)",
    "2300": "إجمالي الموردين",
    "3100": "حقوق الشركاء",
    "3120": "جاري الشركاء (المسحوبات والتوزيعات)",
    "4100": "إيرادات الأجور والمصنعية",
    "5110": "فواقد الورشة",
    "5120": "فاقد فني — قسم الصب (تبخير)",
    "5130": "خسائر فروقات الجرد — الذهب المشغول",
}


SYSTEM_TAGS = {
    "1100": "MANUFACTURING_VAULT",   # خزينة التصنيع
    "1200": "FINISHED_GOLD",         # الذهب المشغول
    "1310": "SCRAP_18", "1320": "SCRAP_21", "1330": "SCRAP_24",
    "1350": "REFINING",              # الصب والتصفية
    "1400": "CASH_BOX", "1500": "BANK",
    "1900": "VAT_INPUT", "2100": "VAT_PAYABLE",
    "1600": "CUSTOMERS_PARENT", "1650": "OTHER_PARENT",
    "2300": "SUPPLIERS_PARENT", "1950": "EMP_ADVANCES_PARENT", "1970": "WORKER_ADVANCES_PARENT",
    "2200": "EMP_ACCRUED_PARENT", "2900": "DIRECT_ADJUSTMENT",
    # ملاحظة: الوسم النظامي واحد لكل حساب (فهرس فريد على system_tag).
    # كانت 3110 و3120 مكررتين هنا فتضيع القيمة الأولى صامتةً ولا
    # يُوسَم أي حساب بـ PARTNER_CAPITAL_PARENT / PARTNER_CURRENT_PARENT.
    "3900": "OPENING_SUSPENSE", "3200": "RETAINED_EARNINGS",
    "3210": "CURRENT_YEAR_PL", "3110": "CAPITAL", "3120": "PARTNERS_CURRENT",
    "4100": "WAGE_REVENUE",
    "5110": "GOLD_LOSS_MANUFACTURING",   # فاقد التصنيع والخياس
    "5120": "GOLD_LOSS_CASTING",         # الفاقد الفني للصب
    "1250": "WO_ADJUST_STOCK",           # مخزون تسويات أوزان الطقوم
    "4110": "SALES_GOLD", "4120": "SALES_WAGES",
    "4910": "RETURNS_GOLD", "4920": "RETURNS_WAGES",
    "5150": "COGS_GOLD",
    "5130": "GOLD_LOSS_STOCKTAKE",
    "5700": "SALARY_EXPENSE", "5710": "WORKER_SALARY_EXPENSE",
    "2250": "WORKER_PAYABLE", "6100": "FIXING_BRIDGE",
}


def ensure_system_tags(conn) -> int:
    """يربط الوسوم النظامية بالحسابات — يجعل العمليات الآلية مستقلة عن
    أرقام الحسابات المكتوبة في الكود."""
    n = 0
    for code, tag in SYSTEM_TAGS.items():
        row = conn.execute("SELECT id, system_tag FROM accounts WHERE code=?",
                           (code,)).fetchone()
        if not row or row["system_tag"] == tag:
            continue
        clash = conn.execute(
            "SELECT 1 FROM accounts WHERE system_tag=? AND id<>?",
            (tag, row["id"])).fetchone()
        if clash:
            continue
        conn.execute("UPDATE accounts SET system_tag=? WHERE id=?",
                     (tag, row["id"]))
        n += 1
    return n


def ensure_new_accounts() -> None:
    """يضيف الحسابات الناقصة ويعيد هيكلة الشجرة دون المساس بالأرصدة."""
    with db() as conn:
        rows = conn.execute("SELECT code, id FROM accounts").fetchall()
        if not rows:
            return
        ids = {r["code"]: r["id"] for r in rows}

        # حسابات كانت قابلة للترحيل ثم صارت مجموعات — تبقى قابلة للترحيل
        # فقط إن كانت لها حركة تاريخية فعلية حتى لا تُفقد قراءتها.
        for parent_code, first_child in (("5100", "5110"), ("3100", "3110"),
                                        ("1300", "1310"), ("1600", "1601"),
                                        ("2300", "2301"), ("2200", "2201")):
            if parent_code in ids and first_child not in ids:
                used = conn.execute(
                    "SELECT 1 FROM journal_lines WHERE account_id=? LIMIT 1",
                    (ids[parent_code],)).fetchone()
                conn.execute("UPDATE accounts SET is_postable=? WHERE code=?",
                             (1 if used else 0, parent_code))

        # إضافة كل الحسابات الناقصة (بترتيب الشجرة لضمان وجود الآباء)
        for code, name, typ, parent, postable, bal in ACCOUNTS:
            if code in ids:
                conn.execute(
                    "UPDATE accounts SET nature=?, balance_type=? WHERE code=?",
                    (_nature(typ), bal, code))
                continue
            cur = conn.execute(
                "INSERT INTO accounts(code,name,type,parent_id,is_postable,"
                "nature,balance_type) VALUES(?,?,?,?,?,?,?)",
                (code, name, typ, ids.get(parent), postable, _nature(typ), bal))
            ids[code] = cur.lastrowid

        ensure_system_tags(conn)
        from models.coa import recompute_levels
        recompute_levels(conn)

        # إعادة الهيكلة والتسميات للحسابات التي انتقلت لمجموعات جديدة
        for child, parent in REPARENT.items():
            if child in ids and parent in ids:
                conn.execute("UPDATE accounts SET parent_id=? WHERE code=?",
                             (ids[parent], child))
        # التسميات القياسية لا تُفرض على حساب سمّاه المستخدم بنفسه:
        # `name_locked` يُرفع عند أي إعادة تسمية يدوية، فيبقى الاسم
        # كما اختاره مهما حُدّث النظام.
        for code, name in RENAMES.items():
            if code in ids:
                conn.execute(
                    "UPDATE accounts SET name=? WHERE code=?"
                    " AND COALESCE(name_locked,0)=0", (name, code))

        # ضمانة عامة: أي حساب له حركة فعلية في دفتر الأستاذ يبقى قابلاً
        # للترحيل مهما تغيّرت هيكلة الشجرة — حتى لا يختفي من القوائم
        # المنسدلة ومن دفتر الأستاذ العام وتُفقد قراءة رصيده.
        conn.execute(
            "UPDATE accounts SET is_postable=1 WHERE id IN"
            " (SELECT DISTINCT account_id FROM journal_lines)")
