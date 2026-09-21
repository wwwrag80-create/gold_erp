-- سجلّ التعديل بعد الترحيل — من عدّل ماذا، ومتى، وكم تغيّرت قيمته.
--
-- **العلة**: سجل التتبع `audit_log` يقول «عُدِّلت الفاتورة S-00042»
-- ولا يقول **كم تغيّرت**. فمن أراد أن يعرف أن فاتورةً نقص وزنها
-- كيلواً بعد شهرٍ من ترحيلها فتح القيد وجمع بيده — ولا أحد يفعل.
-- والتعديل مشروعٌ في النظام كله وليس تهمة؛ لكن الرقابة تبدأ من أن
-- يكون **مرئياً**: تعديلٌ يُرى يُسأل عنه، وتعديلٌ لا يُرى لا يُسأل.
--
-- ولا يُقرأ الفرق من نصّ التفصيل في `audit_log`: النصّ للإنسان لا
-- للحاسب، وتحليله بتعبيرٍ نمطي يكسر بأول تغييرٍ في صياغته. فتُحفظ
-- القيمتان **رقمين** قبل وبعد، ويُحسب الفرق منهما.
--
-- **وقيمة المستند = مجموع الطرف المدين من قيده**: مقياسٌ واحد يصلح
-- لكل نوع — فاتورةٍ وسندٍ وصهرٍ وقيدٍ يدوي — لأن القيد متوازنٌ
-- بالضرورة فمجموع مدينه هو حجمه. ولا يحتاج كل نوعٍ قاعدةً خاصة.
CREATE TABLE IF NOT EXISTS doc_edits(
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  source_table TEXT    NOT NULL,
  source_id    INTEGER NOT NULL,
  doc_no       TEXT    NOT NULL DEFAULT '',
  entry_id     INTEGER,
  new_entry_id INTEGER,
  -- تاريخ المستند نفسه (تاريخ قيده) — لا لحظة التعديل
  doc_date     TEXT    NOT NULL DEFAULT '',
  -- لحظة الترحيل الأصلية، ومنها يُقاس كم مضى قبل التعديل
  posted_at    TEXT    NOT NULL DEFAULT '',
  edited_at    TEXT    DEFAULT (datetime('now','localtime')),
  username     TEXT,
  -- inplace: عُدِّل في مكانه بنفس رقمه · repost: أُلغي وأُعيد ترحيله
  kind         TEXT    NOT NULL DEFAULT 'inplace',
  old_gold     REAL    NOT NULL DEFAULT 0,
  new_gold     REAL    NOT NULL DEFAULT 0,
  old_cash     REAL    NOT NULL DEFAULT 0,
  new_cash     REAL    NOT NULL DEFAULT 0,
  note         TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_doc_edits_when  ON doc_edits(edited_at);
CREATE INDEX IF NOT EXISTS idx_doc_edits_doc
  ON doc_edits(source_table, source_id);
