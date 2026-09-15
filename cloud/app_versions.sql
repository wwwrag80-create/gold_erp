-- ═══════════════════════════════════════════════════════════════
-- جدول إصدارات التطبيق — نظام التحديث الآلي
-- ═══════════════════════════════════════════════════════════════
DROP TABLE IF EXISTS app_versions CASCADE;

CREATE TABLE app_versions (
  id                   BIGSERIAL PRIMARY KEY,
  version              TEXT NOT NULL UNIQUE,   -- مثال: 1.2.0
  download_url         TEXT NOT NULL,          -- رابط ملف التحديث (zip)
  min_required_version TEXT,                   -- أقل إصدار يقبل الترقية منه
  release_notes        TEXT,                   -- ملاحظات الإصدار
  is_critical          BOOLEAN NOT NULL DEFAULT FALSE,  -- تحديث إجباري
  sha256               TEXT,                   -- بصمة الملف للتحقق
  released_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_versions_released ON app_versions(released_at DESC);

-- ═══════════════════════════════════════════════════════════════
-- سياسات الأمان: القراءة للجميع · الكتابة ممنوعة تماماً
-- ═══════════════════════════════════════════════════════════════
ALTER TABLE app_versions ENABLE ROW LEVEL SECURITY;

-- قراءة مسموحة لكل حامل مفتاح (المصانع تحتاجها للتحقق من التحديث)
DROP POLICY IF EXISTS versions_select_all ON app_versions;
CREATE POLICY versions_select_all ON app_versions
  FOR SELECT TO anon, authenticated
  USING (TRUE);

-- لا سياسات INSERT/UPDATE/DELETE إطلاقاً ⇒ RLS يمنعها افتراضياً.
-- النشر يتم بمفتاح service_role وحده (يتجاوز RLS) من نسخة المالك.
REVOKE INSERT, UPDATE, DELETE ON app_versions FROM anon, authenticated;
GRANT SELECT ON app_versions TO anon, authenticated;

-- ═══════════════════════════════════════════════════════════════
-- مثال نشر إصدار (يُنفَّذ بمفتاح service_role)
-- ═══════════════════════════════════════════════════════════════
-- INSERT INTO app_versions
--   (version, download_url, min_required_version, release_notes, is_critical)
-- VALUES
--   ('1.1.0',
--    'https://your-cdn.com/gold_erp_1.1.0.zip',
--    '1.0.0',
--    'إضافة تقارير دوران المخزون وإصلاح تنسيق الطباعة',
--    FALSE);
