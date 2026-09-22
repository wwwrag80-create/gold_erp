-- الأصول الثابتة والإهلاك.
--
-- جدول `fixed_assets` موجودٌ أصلاً وتملؤه شاشة المشتريات عند شراء
-- أصل. فيُوسَّع هنا ولا يُستبدل: كل أصلٍ اشتُري من قبل يدخل الإهلاك
-- بمجرّد أن يُكتب عمره الإنتاجي — بلا إعادة إدخال.
--
-- `life_months = 0` تعني «لم يُحدَّد عمره بعد»: لا يُهلَك حتى
-- يُكتب، وتُبرزه الشاشة ليُستدرك بدل أن يبقى مجهولاً.
ALTER TABLE fixed_assets ADD COLUMN account_id INTEGER REFERENCES accounts(id);
ALTER TABLE fixed_assets ADD COLUMN salvage REAL NOT NULL DEFAULT 0;
ALTER TABLE fixed_assets ADD COLUMN life_months INTEGER NOT NULL DEFAULT 0;
ALTER TABLE fixed_assets ADD COLUMN start_date TEXT;
ALTER TABLE fixed_assets ADD COLUMN notes TEXT NOT NULL DEFAULT '';
ALTER TABLE fixed_assets ADD COLUMN is_disposed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE fixed_assets ADD COLUMN disposed_on TEXT;

-- ما اشتُري قبل اليوم: حسابه «الأصول الثابتة» ١٧٠٠ لأنه ما قُيّد
-- عليه فعلاً في شاشة المشتريات، وبدء إهلاكه تاريخ شرائه.
UPDATE fixed_assets
   SET account_id = (SELECT id FROM accounts WHERE code='1700')
 WHERE account_id IS NULL;
UPDATE fixed_assets SET start_date = purchase_date WHERE start_date IS NULL;

-- شهرٌ واحدٌ لا يُهلك مرتين: `period` مفتاحٌ فريد، فإعادة التشغيل
-- على الشهر نفسه لا تُنشئ قيداً ثانياً.
CREATE TABLE IF NOT EXISTS depreciation_runs(
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  period     TEXT NOT NULL UNIQUE,
  entry_id   INTEGER REFERENCES journal_entries(id),
  total      REAL NOT NULL DEFAULT 0,
  created_by TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- تفصيل القسط لكل أصلٍ في كل شهر — به يُبنى جدول الإهلاك ويُراجَع.
CREATE TABLE IF NOT EXISTS depreciation_lines(
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id   INTEGER NOT NULL REFERENCES depreciation_runs(id) ON DELETE CASCADE,
  asset_id INTEGER NOT NULL REFERENCES fixed_assets(id),
  amount   REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dep_lines_asset ON depreciation_lines(asset_id);
CREATE INDEX IF NOT EXISTS idx_dep_lines_run   ON depreciation_lines(run_id);
