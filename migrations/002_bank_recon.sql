-- مطابقة كشف البنك: علامةُ مطابقةٍ لكل سطرٍ في الدفتر رآه المحاسب
-- في كشف المصرف. علامةٌ لا قيد — المطابقة لا تُغيّر رقماً محاسبياً.
-- الحذف المتتالي مقصود: سطرُ قيدٍ زال لا معنى لعلامةٍ عليه.
CREATE TABLE IF NOT EXISTS bank_recon_marks(
  line_id       INTEGER PRIMARY KEY
                REFERENCES journal_lines(id) ON DELETE CASCADE,
  matched_at    TEXT NOT NULL,
  matched_by    TEXT NOT NULL DEFAULT '',
  statement_ref TEXT NOT NULL DEFAULT ''
);
