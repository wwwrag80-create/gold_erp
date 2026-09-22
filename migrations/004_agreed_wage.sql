-- الأجرة المتفق عليها مع كل جهة — واتفاقاتها عبر الزمن.
--
-- **العلة**: أجرة الجرام تُكتب يدوياً في كل سطر فاتورة. والمصنع
-- يتفق مع كل عميلٍ على أجرة، ثم يُدخل البائع الأرقام من ذاكرته —
-- فينزل عميلٌ درجةً بلا أن يدري أحد، ولا يُكتشف الفرق إلا بجمعٍ
-- يدويٍّ لا يقوم به أحد. أجرةٌ نقصت ريالاً واحداً على عشرة كيلوات
-- عشرةُ آلافِ ريالٍ ضاعت في شهر.
--
-- `agreed_wage = 0` تعني **بلا اتفاق** لا اتفاقاً بصفر: فالجهات
-- القائمة تبقى بلا أجرةٍ متفق عليها حتى يكتبها المستخدم صراحةً،
-- تماماً كما يفعل سقف الائتمان.
ALTER TABLE entities ADD COLUMN agreed_wage REAL NOT NULL DEFAULT 0;

-- **ولماذا جدولُ تاريخٍ لا عمودٌ وحده**: الاتفاق يتغيّر. لو قُورنت
-- فواتيرُ العام كلّه بالاتفاق **الحالي** لصارت كلُّ فاتورةٍ قبل آخر
-- تعديلٍ «انحرافاً» — فيمتلئ التقرير بما ليس بخطأ ويُهمَل. فكل
-- فاتورة تُقاس باتفاقها **يوم صدورها**، وهذا الجدول يحفظه.
--
-- والعمود أعلاه يبقى: هو الاتفاق النافذ الآن، تقرؤه شاشة المبيعات
-- في كل سطرٍ جديد بلا استعلامٍ على التاريخ.
CREATE TABLE IF NOT EXISTS wage_agreements(
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_id  INTEGER NOT NULL REFERENCES entities(id),
  wage       REAL    NOT NULL,
  from_date  TEXT    NOT NULL,
  note       TEXT    NOT NULL DEFAULT '',
  created_by TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_wage_agr_entity
  ON wage_agreements(entity_id, from_date);
