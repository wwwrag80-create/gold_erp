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
    ("1200", "الذهب المشغول (بضاعة تامة — أطقم)", "asset", "1020", 1, "gold"),
    ("1300", "صناديق الكسر والذهب الصافي", "asset", "1020", 0, "gold"),
    ("1310", "صندوق الكسر (18 · 21 · 22 · 24)", "asset", "1300", 1, "gold"),

    # الفصوص (5520) والمسترجع من التصفية (5190) والصب والتصفية (5125)
    # **ليست مخزون ذهب** (4.39 · 4.40) — انظر PRODUCTION_MOVES
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
    # مجمّع الإهلاك: حسابٌ **مقابل** للأصل — رصيده دائنٌ فيطرح من
    # تكلفة الأصول في الميزانية. يُفصل عن حساب الأصل نفسه ليبقى
    # في الدفتر ما يطلبه أي مراجع: التكلفة والمجمّع والصافي.
    ("1790", "مجمّع إهلاك الأصول الثابتة", "asset", "1700", 1, "cash"),
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
    # 4.40: لا «إيراد مبيعات ذهب وزناً» ولا «تكلفته» — الذهب يخرج من
    # المخزون إلى ذمة العميل بوزنه (انتقال أصل)، وربح المصنع أجوره.
    # كانت 4110 · 4910 · 5150 زوجاً متقابلاً يتضخّم به الدخل وزناً ثم
    # يُصفَّر؛ انظر `drop_gold_sale_pair`.
    ("4120", "إيرادات مبيعات أجور", "revenue", "4000", 1, "cash"),
    # مبيعاتٌ بالريال بفواتير ضريبية — لا تمسّ الذهب ولا المخزون
    ("4130", "المبيعات الضريبية (خارج المخزون)", "revenue", "4000", 1, "cash"),
    ("4900", "مردودات المبيعات", "revenue", "4000", 0, "both"),
    ("4920", "مردودات مبيعات أجور", "revenue", "4900", 1, "cash"),
    ("4930", "مردودات المبيعات الضريبية", "revenue", "4900", 1, "cash"),
    ("4200", "إيرادات أخرى / عرضية (تصفية التراب والشفط)", "revenue", "4000", 1, "cash"),
    ("4300", "أرباح فروقات الجرد والتسويات", "revenue", "4000", 1, "both"),
    # ═══ 5) المصروفات ═══
    ("5000", "المصروفات", "expense", None, 0, "both"),
    # ── فواقد الورشة (4.40): كل ما فُقد من الذهب في مكانٍ واحد، والمسترجع
    #    منه يُطرح تحته — «خسائر الورشة» في قائمة الدخل
    ("5100", "فواقد الورشة", "expense", "5000", 0, "gold"),
    ("5110", "فواقد قسم التصنيع", "expense", "5100", 0, "gold"),
    ("5111", "فاقد البوليش", "expense", "5110", 1, "gold"),
    ("5112", "فاقد الصب", "expense", "5110", 1, "gold"),
    ("5113", "فاقد الكاستنج", "expense", "5110", 1, "gold"),
    ("5114", "فاقد التلميع النهائي", "expense", "5110", 1, "gold"),
    ("5115", "فاقد الالترا بوليش", "expense", "5110", 1, "gold"),
    ("5120", "الفاقد الفني للصب (الصهر والتصفية)", "expense", "5100", 1, "gold"),
    # الذهب المرسل للصب والتصفية ولم يعد: فاقدٌ لا مخزون (كان 1350 تحت
    # المخزون) — وما يعود منه يُقيَّد دائناً عليه فيُنقص الفاقد
    ("5125", "فاقد التصفية والصب", "expense", "5100", 1, "gold"),
    ("5130", "خسائر فروقات الجرد — الذهب المشغول", "expense", "5100", 1, "gold"),
    ("5140", "فاقد بيع الذهب", "expense", "5100", 1, "gold"),
    # المسترجع من التصفية: ذهبٌ عاد من فاقدٍ أُثبت مصروفاً يوم وقع، ويُصرف
    # لخزينة التصنيع مباشرة (من حـ/ خزينة التصنيع إلى حـ/ المسترجع) —
    # فهو **تخفيضٌ للفاقد** لا مخزونٌ باقٍ. حسابٌ مقابل رصيده دائن يُطرح
    # من الفواقد في قائمة الدخل. مجموعة تُضاف تحتها فروع بمصدر الاسترجاع.
    ("5190", "مسترجع من التصفية (يُطرح من الفواقد)", "expense", "5100", 0,
     "gold"),
    # ── مواد ومصروفات تشغيل مباشرة
    ("5050", "مواد ومصروفات تشغيل مباشرة", "expense", "5000", 0, "both"),
    ("5500", "مصروفات تشغيلية", "expense", "5050", 1, "cash"),
    ("5510", "مصروف مواد التشغيل والجلي", "expense", "5050", 1, "cash"),
    # الفصوص والأحجار: موادٌّ تُركَّب مع الطقم ولا تُعدّ ذهباً — تُصرف
    # لخزينة التصنيع (من حـ/ خزينة التصنيع إلى هذا الحساب) فيقرأ دائنُه
    # الوزنيّ ما صُرف للتصنيع؛ وهو وزنٌ يُباع ضمن الوزن المقيد فيظهر
    # ربحاً وزنياً، وثمن شرائها بالريال مصروفٌ على الحساب نفسه.
    ("5520", "الفصوص والأحجار المصروفة للتصنيع", "expense", "5050", 1,
     "both"),
    # ── رواتب وأجور التشغيل
    ("5690", "رواتب وأجور التشغيل", "expense", "5000", 0, "cash"),
    ("5700", "مصروف الرواتب والأجور", "expense", "5690", 1, "cash"),
    ("5710", "مصروف رواتب عمال التصنيع", "expense", "5690", 1, "cash"),
    ("5800", "المصاريف الإدارية والعمومية", "expense", "5000", 0, "cash"),
    ("5810", "الإيجار", "expense", "5800", 1, "cash"),
    ("5820", "الكهرباء والماء", "expense", "5800", 1, "cash"),
    ("5830", "الصيانة", "expense", "5800", 1, "cash"),
    ("5840", "الرسوم والتراخيص", "expense", "5800", 1, "cash"),
    ("5850", "مصاريف الضيافة", "expense", "5800", 1, "cash"),
    # الإهلاك مصروفٌ لا يُدفع نقداً — وإغفاله يضخّم الربح شهراً
    # بعد شهر ويُبقي المكائن في الميزانية بثمن شرائها إلى الأبد.
    ("5860", "مصروف إهلاك الأصول الثابتة", "expense", "5800", 1, "cash"),
    ("5900", "مصروفات أخرى", "expense", "5000", 0, "both"),
    ("5200", "خصم مسموح به نقداً", "expense", "5900", 1, "cash"),
    ("5300", "خصم مسموح به وزناً", "expense", "5900", 1, "gold"),
    ("5600", "فروقات الصافي", "expense", "5900", 1, "cash"),
    # ═══ 6) حسابات وسيطة ═══
    ("6000", "حسابات وسيطة", "bridge", None, 0, "both"),
    ("6100", "مركز التسكير (ذهب ↔ نقد)", "bridge", "6000", 1, "both"),
    # ═══ تسويات نهاية الفترة (4.36) — ما تطلبه القوائم النظامية ═══
    # مخصص الخسائر الائتمانية حسابٌ مقابل للذمم (رصيده دائن) — خارج
    # 1600 عمداً كي لا يُقرأ عميلاً ولا يُقاصّ برصيد جهة (IFRS 9).
    ("1680", "مخصص الخسائر الائتمانية المتوقعة (ديون مشكوك فيها)",
     "asset", "1030", 1, "cash"),
    ("1980", "مصروفات مدفوعة مقدماً", "asset", "1030", 1, "cash"),
    ("2280", "مصروفات مستحقة", "liability", "2010", 1, "cash"),
    ("2400", "مخصص الزكاة", "liability", "2020", 1, "cash"),
    # التزامٌ غير متداول (IAS 19) — تحت الجذر لا تحت المتداولة
    ("2600", "مخصص مكافأة نهاية الخدمة", "liability", "2000", 1, "cash"),
    ("5870", "مصروف مكافأة نهاية الخدمة", "expense", "5800", 1, "cash"),
    ("5880", "مصروف الخسائر الائتمانية المتوقعة", "expense", "5800", 1,
     "cash"),
    # الزكاة بندٌ مستقل بعد «الربح قبل الزكاة» — لا مصروفاً تشغيلياً
    ("5950", "الزكاة", "expense", "5000", 1, "cash"),
    # ═══ مراجعة دليل الحسابات (4.37) ═══
    # مستوى «متداول / غير متداول» الذي يقرأ به المراجع الميزانية (IAS 1.60)
    ("1005", "الأصول المتداولة", "asset", "1000", 0, "both"),
    ("1690", "الأصول غير المتداولة", "asset", "1000", 0, "cash"),
    ("2500", "الخصوم غير المتداولة", "liability", "2000", 0, "cash"),
    # حساباتٌ يتوقعها المراجع ولم تكن في الشجرة
    ("2290", "التأمينات الاجتماعية المستحقة (GOSI)", "liability", "2010",
     1, "cash"),
    ("2350", "قروض قصيرة الأجل والجزء المتداول من القروض", "liability",
     "2010", 1, "cash"),
    ("2700", "قروض طويلة الأجل", "liability", "2500", 1, "cash"),
    ("3300", "الاحتياطيات (النظامي والاتفاقي)", "equity", "3000", 1,
     "cash"),
    ("4400", "أرباح بيع واستبعاد أصول ثابتة", "revenue", "4000", 1, "cash"),
    ("5805", "رواتب وأجور الإدارة", "expense", "5800", 1, "cash"),
    ("5806", "مصروف التأمينات الاجتماعية (GOSI)", "expense", "5800", 1,
     "cash"),
    ("5825", "الاتصالات والإنترنت", "expense", "5800", 1, "cash"),
    ("5835", "التأمين", "expense", "5800", 1, "cash"),
    ("5845", "النقل والمواصلات", "expense", "5800", 1, "cash"),
    ("5855", "الدعاية والتسويق", "expense", "5800", 1, "cash"),
    ("5890", "مصروفات ورسوم بنكية", "expense", "5800", 1, "cash"),
    ("5910", "خسائر بيع واستبعاد أصول ثابتة", "expense", "5900", 1, "cash"),
]

CREDIT_TYPES = ("liability", "equity", "revenue")

# ══ الحسابات المقابلة (Contra) — طبيعتها عكس نوعها ══
# مجمّع الإهلاك ومخصص الخسائر الائتمانية أصلان رصيدهما دائن (يُطرحان
# من الأصل)، ومردودات المبيعات إيرادٌ رصيده مدين (يُطرح من المبيعات).
# كانت تُسجَّل بطبيعة نوعها، فيقرأ المراجع «مجمّع إهلاك مدين» خطأً.
CONTRA_NATURE = {"1790": "credit", "1680": "credit",
                 "4900": "debit", "4910": "debit", "4920": "debit",
                 "4930": "debit",
                 # المسترجع من التصفية يُطرح من الفواقد (رصيده دائن)
                 "5190": "credit"}

# ══ 4.39: ما ليس مخزون ذهب يخرج من «المخزون — الذهب» ══
# (الكود القديم، الكود الجديد، الاسم، الأب الجديد)
# الحساب يحتفظ بمعرّفه فتبقى قيوده كما هي — يتغيّر كوده ونوعه وموضعه
# في الشجرة فقط، وتنتقل فروعه معه (136001 ← 519001).
PRODUCTION_MOVES = (
    ("1150", "5520", "الفصوص والأحجار المصروفة للتصنيع", "5050"),
    ("1360", "5190", "مسترجع من التصفية (يُطرح من الفواقد)", "5100"),
    # 4.40: الذهب لدى جهة الصب والتصفية فاقدٌ من فواقد الورشة
    ("1350", "5125", "فاقد التصفية والصب", "5100"),
)


# مجموعاتٌ تبقى تقبل الترحيل: ترحيلٌ احتياطي عليها من الرواتب
KEEP_POSTABLE_GROUPS = ("1950", "1960", "1970")


def _nature(acc_type, code=None):
    if code in CONTRA_NATURE:
        return CONTRA_NATURE[code]
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
                (code, name, typ, ids.get(parent), postable,
                 _nature(typ, code), bal))
            ids[code] = cur.lastrowid
        for u, p, full, role in USERS:
            conn.execute(
                "INSERT INTO users(username,password_hash,full_name,role) VALUES(?,?,?,?)",
                (u, hash_password(p), full, role))


# ترقية قواعد البيانات القائمة: تُضاف الحسابات الناقصة فقط، وتُعاد هيكلة
# الآباء للحسابات التي انتقلت لمجموعات جديدة (دون أي مساس بالأرصدة).
REPARENT = {
    "1400": "1010", "1410": "1010", "1500": "1010",
    "1100": "1020", "1200": "1020", "1250": "1020",
    "1300": "1020",
    "1600": "1030", "1650": "1030", "1950": "1030", "1970": "1030", "1960": "1030",
    "2300": "2010", "2200": "2010", "2100": "2020", "2150": "2020",
    # 4.40: فواقد الورشة · رواتب وأجور التشغيل · مواد التشغيل — تحت
    # المصروفات مباشرة؛ ولا مجموعة «تكاليف التشغيل المباشرة» فوقها
    "5100": "5000", "5500": "5050", "5510": "5050",
    "5700": "5690", "5710": "5690", "5150": "5000",
    "5200": "5900", "5300": "5900", "5600": "5900",
    # 4.37: مستوى المتداول / غير المتداول، وضريبة المدخلات مع الأرصدة
    # المدينة المتداولة، والالتزامات الضريبية مع الخصوم المتداولة
    "1010": "1005", "1020": "1005", "1030": "1005", "1900": "1030",
    "1700": "1690", "2020": "2010", "2600": "2500",
}

RENAMES = {
    "1400": "الصندوق الرئيسي",
    "1250": "مخزون تسويات أوزان الطقوم",
    "1100": "خزينة التصنيع (تشغيل — أوزان ذهب وفصوص)",
    "1200": "الذهب المشغول (بضاعة تامة — أطقم)",
    "1300": "صناديق الكسر والذهب الصافي",

    "2200": "مستحقات الموظفين (الرواتب والأجور المستحقة)",
    "2900": "تسويات مباشرة على أرصدة الجهات",
    "1600": "إجمالي العملاء (نقد وذهب)",
    "6100": "مركز التسكير (ذهب ↔ نقد)",
    "1650": "إجمالي الجهات الأخرى (مدينون آخرون)",
    "2300": "إجمالي الموردين",
    "3100": "حقوق الشركاء",
    "3120": "جاري الشركاء (المسحوبات والتوزيعات)",
    "4100": "إيرادات الأجور والمصنعية",
    "5100": "فواقد الورشة",
    "5110": "فواقد قسم التصنيع",
    "5050": "مواد ومصروفات تشغيل مباشرة",
    "5120": "فاقد فني — قسم الصب (تبخير)",
    "5130": "خسائر فروقات الجرد — الذهب المشغول",
    # 4.37: أسماء المجموعات بعد مستوى المتداول / غير المتداول
    "1010": "النقد وما في حكمه",
    "1020": "المخزون — الذهب الخام والمشغول والكسر",
    "1030": "الذمم المدينة والأرصدة المدينة الأخرى",
    "1700": "الممتلكات والآلات والمعدات",
    "2010": "الخصوم المتداولة",
    "2020": "الالتزامات الضريبية والزكوية",
}


SYSTEM_TAGS = {
    "1100": "MANUFACTURING_VAULT",   # خزينة التصنيع
    "1200": "FINISHED_GOLD",         # الذهب المشغول
    "1310": "SCRAP_18", "1320": "SCRAP_21", "1330": "SCRAP_24",
    "5125": "REFINING",              # فاقد التصفية والصب (كان 1350)
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


def move_production_accounts(conn) -> list:
    """ينقل الفصوص والمسترجع من التصفية من المخزون إلى تكلفة الإيرادات.

    يُنفَّذ قبل إضافة الحسابات الناقصة — وإلا أُنشئ 5520 جديداً فارغاً
    وبقي 1150 القديم بقيوده تحت المخزون. القيود لا تُمسّ: الحساب نفسه
    (بمعرّفه) يتغيّر كوده ونوعه وأبوه. يعيد ما نُقل [(قديم، جديد)].
    """
    moved = []
    for old, new, name, parent in PRODUCTION_MOVES:
        acc = conn.execute("SELECT id FROM accounts WHERE code=?",
                           (old,)).fetchone()
        par = conn.execute("SELECT id FROM accounts WHERE code=?",
                           (parent,)).fetchone()
        if not acc or not par or conn.execute(
                "SELECT 1 FROM accounts WHERE code=?", (new,)).fetchone():
            continue
        nature = CONTRA_NATURE.get(new, "debit")
        # الحساب وكل فروعه (بأي عمق)
        ids, frontier = [acc["id"]], [acc["id"]]
        while frontier:
            frontier = [r["id"] for r in conn.execute(
                "SELECT id FROM accounts WHERE parent_id IN (%s)"
                % ",".join("?" * len(frontier)), frontier)]
            ids += frontier
        for aid in ids[1:]:
            code = conn.execute("SELECT code FROM accounts WHERE id=?",
                                (aid,)).fetchone()["code"]
            if code.startswith(old):
                cand = new + code[len(old):]
                if not conn.execute("SELECT 1 FROM accounts WHERE code=?",
                                    (cand,)).fetchone():
                    conn.execute("UPDATE accounts SET code=? WHERE id=?",
                                 (cand, aid))
        conn.execute(
            "UPDATE accounts SET type='expense', nature=? WHERE id IN (%s)"
            % ",".join("?" * len(ids)), [nature] + ids)
        conn.execute("UPDATE accounts SET code=?, parent_id=? WHERE id=?",
                     (new, par["id"], acc["id"]))
        conn.execute("UPDATE accounts SET name=? WHERE id=?"
                     " AND COALESCE(name_locked,0)=0", (name, acc["id"]))
        if new == "5520":
            # ثمن شراء الفصوص بالريال يُقيَّد عليه كذلك
            conn.execute("UPDATE accounts SET balance_type='both'"
                         " WHERE id=?", (acc["id"],))
        moved.append((old, new))
    return moved


# زوج «الذهب المباع وزناً» القديم: إيراده ومردوده وتكلفته
GOLD_SALE_PAIR = ("4110", "4910", "5150")


def drop_gold_sale_pair(conn) -> int:
    """يحذف من كل قيدٍ سطورَ الزوج المتقابل (إيراد الذهب وزناً ↔ تكلفته).

    كانت فاتورة البيع تُقيّد: دائن 4110 ومدين 5150 بالوزن نفسه، والمرتجع
    عكسهما عبر 4910 — سطورٌ صافيها في القيد الواحد **صفر**. فلا يتغيّر
    بحذفها رصيد أي حساب في المركز المالي ولا صافي الربح، ويبقى كل قيد
    متوازناً بسطوره الباقية (العميل ↔ المخزون). ولا يُحذف إلا ما صافيه
    صفرٌ داخل قيده: قيدٌ يدوي على أحدها وحده يبقى كما هو.
    ثم يُجمَّد من الثلاثة ما لم يبقَ عليه سطر. يعيد عدد السطور المحذوفة.
    """
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM accounts WHERE code IN (%s)"
        % ",".join("?" * len(GOLD_SALE_PAIR)), GOLD_SALE_PAIR)]
    if not ids:
        return 0
    qs = ",".join("?" * len(ids))
    entries = [r["entry_id"] for r in conn.execute(
        "SELECT entry_id FROM journal_lines"
        f" WHERE account_id IN ({qs}) GROUP BY entry_id"
        " HAVING ABS(SUM(gold_debit-gold_credit)) < 0.0005"
        "    AND ABS(SUM(cash_debit-cash_credit)) < 0.005", ids)]
    n = 0
    for eid in entries:
        n += conn.execute(
            f"DELETE FROM journal_lines WHERE entry_id=? AND account_id"
            f" IN ({qs})", [eid] + ids).rowcount
    conn.execute(
        f"UPDATE accounts SET is_active=0 WHERE id IN ({qs}) AND id NOT IN"
        " (SELECT DISTINCT account_id FROM journal_lines)", ids)
    return n


def ensure_new_accounts() -> None:
    """يضيف الحسابات الناقصة ويعيد هيكلة الشجرة دون المساس بالأرصدة."""
    with db() as conn:
        rows = conn.execute("SELECT code, id FROM accounts").fetchall()
        if not rows:
            return
        move_production_accounts(conn)
        drop_gold_sale_pair(conn)
        rows = conn.execute("SELECT code, id FROM accounts").fetchall()
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
                    (_nature(typ, code), bal, code))
                continue
            cur = conn.execute(
                "INSERT INTO accounts(code,name,type,parent_id,is_postable,"
                "nature,balance_type) VALUES(?,?,?,?,?,?,?)",
                (code, name, typ, ids.get(parent), postable,
                 _nature(typ, code), bal))
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

        # 4.37: الحساب الذي له فروع مجموعةٌ لا يُرحَّل عليها — ما لم تكن
        # عليه حركةٌ تاريخية (تحميه الضمانة التالية). كان «الأصول
        # الثابتة» 1700 يقبل الترحيل وله فروع، فتتوزّع أصولٌ بين المجموعة
        # وفروعها ولا يعرف المراجع ما في المجموعة نفسها.
        # مستثنى: سلف الموظفين والعهد وسلف العمال — الرواتب ترحّل على
        # الحساب الأب نفسه لموظفٍ ليس له حسابٌ فرعي بعد (models.payroll).
        conn.execute(
            "UPDATE accounts SET is_postable=0 WHERE is_postable=1"
            " AND code NOT IN (" + ",".join(
                f"'{c}'" for c in KEEP_POSTABLE_GROUPS) + ")"
            " AND id IN (SELECT DISTINCT parent_id FROM accounts"
            "            WHERE parent_id IS NOT NULL)"
            " AND id NOT IN (SELECT DISTINCT account_id FROM journal_lines)")
        recompute_levels(conn)

        # ضمانة عامة: أي حساب له حركة فعلية في دفتر الأستاذ يبقى قابلاً
        # للترحيل مهما تغيّرت هيكلة الشجرة — حتى لا يختفي من القوائم
        # المنسدلة ومن دفتر الأستاذ العام وتُفقد قراءة رصيده.
        conn.execute(
            "UPDATE accounts SET is_postable=1 WHERE id IN"
            " (SELECT DISTINCT account_id FROM journal_lines)")
